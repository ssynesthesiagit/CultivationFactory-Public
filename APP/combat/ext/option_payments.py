"""Admission costs for unconditional, fixed self-payment in typed options.

Shared by Glamer, False Obstruction and other compiled paid options. A top-level
spend_resource with a resolved resource, positive integer flat amount and no
formula is a price, not a contingent effect. Move it into ActionDefinition.costs
so normal manual/AI admission refuses an unaffordable choice before its benefits.
Nested, variable and recipient payments keep their existing resolution contract.
No matching owned option means no replacement; saved action definitions are intact.
"""
import copy
import re

from . import hook, note


def unresolved_fixed_alternative(action):
    """Fail closed when a fixed printed CP-or-Stamina price compiled to no cost.

    Reviewed alternatives supply normal priced actions. Older saved definitions
    with neither alternative encoded remain loadable but cannot apply benefits
    free; they need recompilation to expose a way to pay. No ability IDs here.
    """
    if action is None:
        return False  # movement/end-turn candidates have no typed action
    from .ability_source import mechanic_of
    from ..rule_help import printed_rule_text
    if any(pool in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}
           and amount > 0 for pool, amount in action.costs):
        return False
    source = mechanic_of(action)
    return bool(source and re.search(r'^Cost:\s*[1-9]\d* CP or Stamina\.?\s*$',
                                     printed_rule_text(source), re.MULTILINE | re.IGNORECASE))


def fixed_payment(row):
    """Return the fixed self-price, or None for contingent/variable effects."""
    amount = row.get('flat')
    if (row.get('type') == 'spend_resource' and row.get('applies_to') == 'self'
            and row.get('resource_id') and type(amount) is int and amount > 0
            and row.get('formula') in (None, '', 'none')
            and not any(row.get(key) not in (None, '', 'none', False) for key in ('dice', 'condition', 'precondition'))):
        return row['resource_id'], amount
    return None


def pending_prices(action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return [price for row in typed.get('effects') or [] if (price := fixed_payment(row))] if typed.get('option_of') else []


@hook('compile_action')
def option_payment(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if not typed.get('option_of'):
        return None
    costs = list(action.costs)
    effects = []
    changed = False
    for row in typed.get('effects') or []:
        if price := fixed_payment(row):
            costs.append(price)
            changed = True
        else:
            effects.append(copy.deepcopy(row))
    if not changed:
        return None
    parameters = copy.deepcopy(action.parameters)
    parameters['typed']['effects'] = effects
    return action.model_copy(update={'costs': tuple(costs), 'parameters': parameters})


def affordable(actor, prices):
    totals = {}
    for pool, amount in prices:
        totals[pool] = totals.get(pool, 0) + amount
    return all(actor.resources.get(pool, 0) >= amount for pool, amount in totals.items())


def target_mark_prices(action):
    """Unconditional target-mark prices must come from the explicit selected bearer.

    Shared by any typed action whose printed cost names the target's mark.
    Other top-level spends may create/consume a mark as a rider or spend a
    separate bearer to support an ally; those are not target admission prices.
    Nested spends remain contingent and keep their existing resolution contract.
    """
    from .ability_source import mechanic_of
    from ..rule_help import printed_rule_text
    cost = re.search(r'^Cost:([^\n]+)', printed_rule_text(mechanic_of(action)), re.MULTILINE)
    if not cost or not re.search(r"\btarget(?:['’]s|\b)", cost.group(1), re.I):
        return []
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return [row['mark'] for row in typed.get('effects') or []
            if row.get('type') == 'spend_mark' and row.get('applies_to') == 'target' and row.get('mark')
            and str(row['mark']).lower() in cost.group(1).lower()]


def marks_payable(engine, actor, targets, names):
    from ..typed_executor import bears_mark
    return bool(targets) and all(t in engine.state.actors and all(
        bears_mark(engine.state.actors[t], actor.entity_id, name) for name in names) for t in targets)


@hook('candidate_allowed')
def legacy_option_admission(engine, actor, candidate, action):
    """Old saved definitions retain effect payments, but cannot buy benefits free."""
    if unresolved_fixed_alternative(action):
        return False
    prices = pending_prices(action)
    if prices and not affordable(actor, [*action.costs, *prices]):
        return False
    names = target_mark_prices(action)
    if names and not marks_payable(engine, actor, candidate.target_ids, names):
        return False
    return None


@hook('technique_start')
def legacy_option_start(engine, actor, action):
    """Recheck after admission/base payment; never apply an unaffordable benefit."""
    if unresolved_fixed_alternative(action):
        note(engine, action.source_definition_id, actor,
             f'{action.display_name}: this saved technique has no recorded way to pay its cost. Prepare a new fight before using it.')
        return True
    prices = pending_prices(action)
    if prices and not affordable(actor, prices):
        note(engine, action.source_definition_id, actor,
             f'{action.display_name}: insufficient resources; the effect is refused.')
        return True
    names = target_mark_prices(action)
    intent = getattr(engine, '_active_intent', None)
    if names and not marks_payable(engine, actor, getattr(intent, 'target_ids', ()), names):
        note(engine, action.source_definition_id, actor,
             f'{action.display_name}: the selected target does not bear a mark placed by you that you can spend; the effect is refused.')
        return True
    return None
