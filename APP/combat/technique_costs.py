"""Pure cost floors shared by native actions and plug-in activations.

Callers retain listed costs separately from their discounted/surcharged proposal.
The query never spends resources, consumes a discount, or changes the catalog.
"""
from types import MappingProxyType


def effective(engine, actor, source_id, listed_costs, reduced_costs=None):
    from . import ext

    listed = tuple(listed_costs)
    proposed = listed if reduced_costs is None else tuple(reduced_costs)
    for resource, amount in (*listed, *proposed):
        if not isinstance(resource, str) or type(amount) is not int or amount < 0:
            raise ValueError('technique costs must have resource IDs and nonnegative integer amounts')
    # Pure, sealed discounts precede all ordinary minimum-cost policies.
    if reduced_costs is None and ext.has('technique_cost_discount'):
        current = {}
        for resource, amount in proposed:
            current[resource] = current.get(resource, 0) + amount
        cuts = {}
        for answer in ext.run_strict('technique_cost_discount', engine, actor, source_id, MappingProxyType(current)):
            if not isinstance(answer, dict):
                raise ValueError('technique_cost_discount requires a resource-to-integer mapping')
            for resource, cut in answer.items():
                if resource not in current or type(cut) is not int or not 0 <= cut <= current[resource]:
                    raise ValueError('technique_cost_discount must reduce a listed cost by a nonnegative integer')
                cuts[resource] = cuts.get(resource, 0) + cut
        remaining = {r: min(n, current[r]) for r, n in cuts.items()}
        adjusted = []
        for resource, amount in proposed:
            cut = min(amount, remaining.get(resource, 0))
            remaining[resource] = remaining.get(resource, 0) - cut
            adjusted.append((resource, amount - cut))
        proposed = tuple(adjusted)
    if not ext.has('technique_cost_floor'):
        return proposed
    def totals(rows):
        result = {}
        for resource, amount in rows:
            result[resource] = result.get(resource, 0) + amount
        return result
    printed, current = totals(listed), totals(proposed)
    floors = dict(current)
    for answer in ext.run_strict('technique_cost_floor', engine, actor, source_id,
                                 MappingProxyType(printed), MappingProxyType(current)):
        if not isinstance(answer, dict):
            raise ValueError('technique_cost_floor must return None or a resource-to-integer mapping')
        for resource, amount in answer.items():
            if resource not in printed or type(amount) is not int or amount < 0:
                raise ValueError('technique_cost_floor must name a listed resource and a nonnegative integer')
            floors[resource] = max(floors.get(resource, 0), amount)
    # Preserve original ordering, duplicate rows and zero-cost events when inert.
    extra = {r: n - current.get(r, 0) for r, n in floors.items() if n > current.get(r, 0)}
    if not extra:
        return proposed
    result = []
    for resource, amount in proposed:
        result.append((resource, amount + extra.pop(resource, 0)))
    result.extend((resource, extra[resource]) for resource in printed if resource in extra)
    return tuple(result)


def permitted_refund(engine, actor, source_id, listed_costs, resource, refund):
    """Keep older post-use discount consumers subject to the same cost floor.

    Qi path and Second Furnace still deliver their other benefits on resolution;
    this bounds their refund without treating it as an unrelated resource gain.
    """
    listed = tuple(listed_costs)
    paid = sum(amount for rid, amount in listed if rid == resource)
    from .paid_relocation import current_activation
    receipt = current_activation(engine)
    recorded_payment = (receipt is not None and receipt.actor_id == actor.entity_id and receipt.source_id == source_id)
    if recorded_payment:
        paid = min(paid, dict(receipt.payments).get(resource, 0))
    already = 0
    for event in reversed(engine.events):
        if (event.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED' and event.actor_id == actor.entity_id
                and event.payload.get('technique_source_id') == source_id):
            # Substituted HP/other pools were never spent as this resource: a
            # later discount must not turn that substitution into free CP.
            paid = min(paid, event.payload['resources_paid'].get(resource, 0))
        if event.actor_id != actor.entity_id or event.payload.get('resource_id') != resource:
            continue
        if event.event_type == 'RESOURCE_SPENT' and event.source_definition_id == source_id:
            # The accepted quote may have reduced this printed cost to zero.
            # Post-use discounts can refund only resources actually paid.
            if not recorded_payment:
                paid = min(paid, int(event.payload.get('amount') or 0))
            break
        if event.event_type == 'RESOURCE_GAINED' and event.payload.get('cost_source_id') == source_id:
            already += event.payload.get('gained', 0)
    proposed = tuple((rid, amount) for rid, amount in listed if rid != resource) + ((resource, max(0, paid - already - refund)),)
    final = effective(engine, actor, source_id, listed, proposed)
    return max(0, paid - already - sum(amount for rid, amount in final if rid == resource))


def refund(engine, actor, source_id, listed_costs, resource, amount, refund_source):
    """Evented bounded refund; its receipt prevents two discounts crossing a floor."""
    allowed = permitted_refund(engine, actor, source_id, listed_costs, resource, amount)
    if allowed:
        engine._gain_resource(actor, resource, allowed, refund_source, cost_source_id=source_id)
    return allowed
