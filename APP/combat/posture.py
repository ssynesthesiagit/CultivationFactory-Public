"""One evented standing transition, shared by turn starts and explicit abilities."""
from . import ext

SOURCE = 'system:combat.stand_up'


def prone_conditions(actor):
    """Return conditions whose rule ends on standing, regardless of expiry.

    Typed conditions use the shared rule-instance reader (including inline
    rules and suppression). The character runtime's core conditions use the
    same named rules, without changing their serialized IDs or deadlines.
    """
    from .typed_executor import condition_rule_instances, rules
    instances = condition_rule_instances(actor)
    resolved = {condition.instance_id for condition, _rule in instances}
    table = rules()['conditions']
    for condition in actor.conditions.values():
        if (condition.condition_id.startswith('condition:core.') and condition.instance_id not in resolved
                and not condition.data.get('suppressed')):
            name = condition.condition_id.removeprefix('condition:core.')
            instances.append((condition, table.get(name, {})))
    return [condition for condition, rule in instances if rule.get('ends_on_stand_up')]


def walking_extra(engine, actor):
    """Condition-defined extra feet per foot walked; duplicate conditions do not stack."""
    from .typed_executor import condition_rule_instances
    # A printed granted step lifted from Stable/Unconscious is priced as its own grant, not crawled: the Prone
    # that state carries does not double it (granted_movement.speed_zero_exempt). Any other condition's walking
    # cost still applies to that step.
    exempt = getattr(engine, '_speed_zero_exempt', None) == actor.entity_id
    normal = max((int(row.get('walking_extra_cost', 0))
                  for _condition, row in condition_rule_instances(actor)
                  if not (exempt and row.get('ends_on_stand_up'))), default=0)
    if not normal:
        return 0
    costs = [normal]
    for answer in ext.run_strict('walking_cost', engine, actor, normal):
        if type(answer) is not int or answer < 0:
            raise ValueError('walking_cost must return None or a nonnegative integer')
        costs.append(answer)
    return min(costs)


def allows_jumping(actor):
    """Pure condition restriction, independent of extra walking costs."""
    from .typed_executor import condition_rules
    return not any(row.get('no_jumping') for row in condition_rules(actor))


def _standing_cost_parts(engine, actor, *, cost=None, ignore_speed=False, include_offers=False):
    """Return the standing base and additive burdens after pure eligibility checks."""
    if not prone_conditions(actor) or not actor.active or actor.life_state is not None:
        return None
    speed = engine._effective_speed(actor)
    if speed <= 0 and not ignore_speed:
        return None
    for answer in ext.run_strict('stand_allowed', engine, actor):
        if type(answer) is not bool:
            raise ValueError('stand_allowed must return None or a boolean')
        if not answer:
            return None
    if cost is not None:
        if type(cost) is not int or cost < 0:
            raise ValueError('standing cost must be a nonnegative integer')
        return cost, 0
    costs = [speed // 2]
    for answer in ext.run_strict('stand_cost', engine, actor, speed // 2):
        if type(answer) is not int or answer < 0:
            raise ValueError('stand_cost must return None or a nonnegative integer')
        costs.append(answer)
    base = min(costs)
    if include_offers:
        for answer in ext.run_strict('stand_cost_offer', engine, actor, base):
            if type(answer) is not int or answer < 0:
                raise ValueError('stand_cost_offer must return None or a nonnegative integer')
            costs.append(answer)
        base = min(costs)
    extra = 0
    for answer in ext.run_strict('stand_extra_cost', engine, actor):
        if type(answer) is not int or answer < 0:
            raise ValueError('stand_extra_cost must return None or a nonnegative integer')
        extra += answer
    return base, extra


def standing_cost(engine, actor, *, cost=None, ignore_speed=False, include_offers=True, check_budget=True):
    """Pure eligibility/cost query shared by offers and the standing transition.

    An explicit cost bypasses cost providers, not standing vetoes. ignore_speed
    permits standing at zero Speed; neither override bypasses the movement budget.
    Return None when ineligible, otherwise nonnegative integer feet (including 0).
    """
    parts = _standing_cost_parts(engine, actor, cost=cost, ignore_speed=ignore_speed, include_offers=include_offers)
    if parts is None:
        return None
    total = sum(parts)
    return total if not check_budget or actor.movement_remaining_ft >= total else None


def stand_up(engine, actor, *, source_id=SOURCE, cost=None, ignore_speed=False):
    """Stand once, remove all Prone instances, then publish STOOD_UP.

    Explicit abilities may supply a cost and ignore zero Speed, but cannot bypass
    a stand_allowed veto. Ordinary standing requires positive effective Speed.
    No eligible Prone, no allowance, or a veto makes no changes and emits no event.
    """
    offered_choice = cost is None
    parts = _standing_cost_parts(engine, actor, cost=cost, ignore_speed=ignore_speed, include_offers=False)
    cost = None if parts is None else sum(parts)
    if cost is not None and offered_choice:
        base, extra = parts
        offered = [base]
        for answer in ext.run_strict('stand_cost_offer', engine, actor, base):
            if type(answer) is not int or answer < 0:
                raise ValueError('stand_cost_offer must return None or a nonnegative integer')
            offered.append(answer)
        offered_cost = min(offered) + extra
        # Choices are asked only inside the accepted stand transaction. Preview
        # candidates use stand_cost_offer and stay pure.
        for answer in ext.run_strict('stand_cost_decision', engine, actor, base):
            if answer is not None:
                if type(answer) is not int or answer < 0:
                    raise ValueError('stand_cost_decision must return None or a nonnegative integer')
                base = min(base, answer)
        ordinary_cost = base + extra
        cost = ordinary_cost
        # If an optional offer was declined, never silently spend the more
        # expensive ordinary price. Providers may request an explicit answer
        # from the acting creature through this general seam.
        if cost == ordinary_cost and offered_cost < ordinary_cost and actor.movement_remaining_ft >= ordinary_cost:
            answers = ext.run_strict('stand_cost_fallback_decision', engine, actor, offered_cost, ordinary_cost)
            approved = False
            for answer in answers:
                if answer is not None and type(answer) is not bool:
                    raise ValueError('stand_cost_fallback_decision must return None or a boolean')
                approved = approved or answer is True
            if not approved:
                cost = None
    # Every path, including an explicit ability supplied cost, must fit the
    # actor's remaining movement before any conditions or events are changed.
    if cost is not None and actor.movement_remaining_ft < cost:
        cost = None
    if cost is None:
        return False
    conditions = prone_conditions(actor)
    before = actor.movement_remaining_ft
    actor.movement_remaining_ft -= cost
    for condition in conditions:
        del actor.conditions[condition.instance_id]
        engine._append_event('CONDITION_REMOVED', source_id, actor_id=actor.entity_id,
            target_ids=(actor.entity_id,), payload={'instance_id': condition.instance_id,
                'condition_id': condition.condition_id, 'checkpoint': 'STAND_UP'})
    engine._append_event('STOOD_UP', source_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
        payload={'movement_before': before, 'movement_after': actor.movement_remaining_ft, 'cost_ft': cost,
                 'log': f'{actor.display_name} stands up, spending {cost} feet of movement.'})
    return True
