"""Owned shortfall quotes/payments shared by native actions and plug-in costs.

This is substitution, not a resource grant/refund or damage packet. Ability
consumers own their rate, eligibility, usage limits and automatic-use policy.
"""
from dataclasses import dataclass, asdict
from types import MappingProxyType

from .canonical import canonical_sha256
from .choice_checkpoints import dynamic_choice
from .diagnostics import error, RecoveryDisposition
from .resource_labels import resource_name


@dataclass(frozen=True)
class PaymentAlternative:
    source_id: str
    label: str
    covered: tuple[tuple[str, int], ...]
    costs: tuple[tuple[str, int], ...] = ()
    hp_cost: int = 0
    minimum_hp: int = 1
    resolution_gains: tuple[tuple[str, int], ...] = ()


def totals(rows):
    result = {}
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 2:
            raise ValueError('payment costs require immutable resource/amount pairs')
        resource, amount = row
        if not isinstance(resource, str) or type(amount) is not int or amount < 0:
            raise ValueError('payment costs require resource names and nonnegative integers')
        result[resource] = result.get(resource, 0) + amount
    return result


def shortfall(actor, costs):
    return {r: n - actor.resources.get(r, 0) for r, n in totals(costs).items() if n > actor.resources.get(r, 0)}


def owned(engine, actor, source):
    """Public compiled ownership query shared by payment and fight-setup tasks."""
    if source in (*actor.passive_ids, *actor.augment_ids, *actor.action_ids, *actor.reaction_ids):
        return True
    for field in ('typed_passive_rows', 'typed_reaction_rows'):
        if any(row.get('feature_id') == source for row in getattr(engine, field, {}).get(actor.entity_id, [])):
            return True
    return any((action := engine.action_catalog.get(aid)) is not None
               and action.parameters.get('typed', {}).get('source') == source for aid in actor.action_ids)


def resource_payment(costs, plan):
    remaining = totals(plan.covered)
    rows = []
    for resource, amount in costs:
        replaced = min(amount, remaining.get(resource, 0))
        remaining[resource] = remaining.get(resource, 0) - replaced
        rows.append((resource, amount - replaced))
    return tuple(rows) + plan.costs


def options(engine, actor, source_id, costs):
    """Pure owned quotes: mandatory shortfalls and explicitly enabled substitutions."""
    from . import ext
    from .resource_availability import permits
    costs = tuple(costs)
    missing = shortfall(actor, costs)
    total = totals(costs)
    args = (engine, actor, source_id, MappingProxyType(total), MappingProxyType(missing))
    answers = [(plan, False) for plan in ext.run_strict('payment_shortfall', *args)] if missing else []
    if any(total.values()):
        answers += [(plan, True) for plan in ext.run_strict('payment_substitution', *args)]
    valid = []
    answers = [(p, substitution) for reply, substitution in answers
               for p in (reply if isinstance(reply, (list, tuple)) else (reply,))]
    for plan, substitution in answers:
        if not isinstance(plan, PaymentAlternative):
            raise ValueError('payment_shortfall must return None or PaymentAlternative')
        if (not isinstance(plan.source_id, str) or not plan.source_id or not isinstance(plan.label, str) or not plan.label
                or type(plan.hp_cost) is not int or plan.hp_cost < 0
                or type(plan.minimum_hp) is not int or plan.minimum_hp < 1
                or not isinstance(plan.covered, tuple) or not isinstance(plan.costs, tuple)):
            raise ValueError('invalid alternative payment label, costs or HP minimum')
        covered = totals(plan.covered)
        if substitution:
            if (not covered or any(n <= 0 or n > total.get(r, 0) for r, n in covered.items())
                    or any(covered.get(r, 0) < n for r, n in missing.items())):
                raise ValueError('payment_substitution must cover the shortfall within the actual costs')
        elif covered != missing:
            raise ValueError('alternative payment must cover exactly the current shortfall')
        totals(plan.costs)
        gains = totals(plan.resolution_gains)
        if any(r not in actor.resources or n <= 0 for r, n in gains.items()):
            raise ValueError("resolution gains require represented resources and positive integer amounts")
        if not plan.hp_cost and not any(n for _, n in plan.costs) and not gains:
            raise ValueError('an alternative payment must have a real cost')
        if not owned(engine, actor, plan.source_id):
            continue
        if (actor.active and actor.current_hp - plan.hp_cost >= plan.minimum_hp
                and all(r in actor.resources for r, _ in costs)
                and all(r in actor.resources and actor.resources[r] >= n for r, n in totals(resource_payment(costs, plan)).items())
                and permits(engine,actor,source_id,resource_payment(costs,plan))):
            if plan in valid:
                raise ValueError('duplicate alternative payment')
            valid.append(plan)
    return tuple(valid)


def pay(engine, actor, source_id, costs, intent):
    """Re-quote, choose and commit within the caller's native transaction."""
    from . import ext
    from .ext.choice_costs import covering
    plans = options(engine, actor, source_id, costs)
    if not plans or intent is None or engine._transaction_id is None:
        raise error('GATE2_PAYMENT_UNAVAILABLE', f'{actor.display_name} cannot pay for this technique.',
                    phase='RESOLUTION', subsystem='RESOURCE', recovery=RecoveryDisposition.RETRY,
                    recommended_action='Choose another technique or an affordable payment.')
    def identity(plan):
        body=asdict(plan)
        if not plan.resolution_gains:body.pop('resolution_gains')
        return canonical_sha256(body)[:24]
    keyed = {identity(p): p for p in plans}
    labels = {}
    for key, plan in keyed.items():
        prices = ([f'{plan.hp_cost} HP (keep at least {plan.minimum_hp} HP)'] if plan.hp_cost else [])
        prices += [f'{n} {resource_name(r)}' for r, n in plan.costs if n]
        prices += [f'gain {n} {resource_name(r)} after resolution' for r, n in plan.resolution_gains]
        covered = ', '.join(f'{n} {resource_name(r)}' for r, n in plan.covered)
        labels[key] = f'{plan.label}: pay {" and ".join(prices)} to cover {covered}'
    from .resource_availability import permits
    if not shortfall(actor, costs) and permits(engine,actor,source_id,costs):
        keyed['ordinary'] = None
        labels['ordinary'] = 'Pay the ordinary cost without an alternative'
    action = engine.action_catalog.get(source_id)
    action_name = action.display_name if action is not None else 'this technique'
    _, decision = dynamic_choice(engine, intent, f'PAYMENT_SHORTFALL:{source_id}', actor.entity_id,
        'choice:alternative_payment', {'name': 'Alternative payment', 'actor_id': actor.entity_id,
            'target_id': actor.entity_id, 'labels': labels,
            'cost': covering(costs),  # the amount owed; each option's own price is in its label
            'prompt': (f'{actor.display_name} lacks resources for {action_name}. ' if shortfall(actor, costs)
                       else f'Choose how {actor.display_name} pays for {action_name}. ')
                      + 'Choose a payment, or decline to cancel the technique.'},
        spec_override={'option_ids': tuple(keyed), 'allow_decline': True, 'automatic_use': True,
                       'preferred_option_ids': (next(iter(keyed)),), 'decline_cancels_activation': True})
    if decision is None or decision.selection == 'DECLINE':
        raise error('GATE2_PAYMENT_DECLINED', 'The technique was canceled; no payment was made.',
                    phase='RESOLUTION', subsystem='RESOURCE', recovery=RecoveryDisposition.RETRY,
                    recommended_action='Choose another action or payment.')
    plan = keyed[decision.option_ids[0]]
    if plan is None:
        for resource, amount in costs:
            engine._spend_resource(actor, resource, amount, source_id)
        return
    if plan not in options(engine, actor, source_id, costs):
        raise ValueError('alternative payment changed while choosing')
    for resource, amount in resource_payment(costs, plan):
        engine._spend_resource(actor, resource, amount, source_id)
    if not actor.active or actor.current_hp - plan.hp_cost < plan.minimum_hp:
        raise ValueError('alternative payment no longer meets its HP minimum')
    before = actor.current_hp
    actor.current_hp -= plan.hp_cost
    from .paid_relocation import current_activation
    activation = current_activation(engine)
    activation_payload = {'activation_id': activation.activation_id} if plan.resolution_gains and activation else {}
    engine._append_event('ALTERNATIVE_PAYMENT_COMMITTED', plan.source_id, actor_id=actor.entity_id,
        target_ids=(actor.entity_id,), payload={'technique_source_id': source_id, 'covered': totals(plan.covered),
            'resources_paid': totals(resource_payment(costs, plan)), **activation_payload,
            'costs': totals(plan.costs), **({'resolution_gains': totals(plan.resolution_gains)} if plan.resolution_gains else {}), 'hp_paid': plan.hp_cost, 'hp_before': before, 'hp_after': actor.current_hp,
            'log': f'{actor.display_name} used {labels[decision.option_ids[0]]} for {action_name}.'})
    ext.run_strict('payment_shortfall_paid', engine, actor, source_id, plan, intent)
