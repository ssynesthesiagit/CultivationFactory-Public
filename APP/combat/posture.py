"""One evented standing transition, shared by turn starts and explicit abilities."""
from . import ext

SOURCE = 'system:combat.stand_up'


def prone_conditions(actor):
    return [c for c in actor.conditions.values() if c.expires_on == 'STAND_UP']


def walking_extra(engine, actor):
    """Condition-defined extra feet per foot walked; duplicate conditions do not stack."""
    from .typed_executor import condition_rules
    normal = max((int(row.get('walking_extra_cost', 0)) for row in condition_rules(actor)), default=0)
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


def standing_cost(engine, actor, *, cost=None, ignore_speed=False):
    """Pure eligibility/cost query shared by offers and the standing transition.

    An explicit cost bypasses cost providers, not standing vetoes. ignore_speed
    permits standing at zero Speed; neither override bypasses the movement budget.
    Return None when ineligible, otherwise nonnegative integer feet (including 0).
    """
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
    if cost is None:
        costs = [speed // 2]
        for answer in ext.run_strict('stand_cost', engine, actor, speed // 2):
            if type(answer) is not int or answer < 0:
                raise ValueError('stand_cost must return None or a nonnegative integer')
            costs.append(answer)
        cost = min(costs)
    if type(cost) is not int or cost < 0:
        raise ValueError('standing cost must be a nonnegative integer')
    return cost if actor.movement_remaining_ft >= cost else None


def stand_up(engine, actor, *, source_id=SOURCE, cost=None, ignore_speed=False):
    """Stand once, remove all Prone instances, then publish STOOD_UP.

    Explicit abilities may supply a cost and ignore zero Speed, but cannot bypass
    a stand_allowed veto. Ordinary standing requires positive effective Speed.
    No eligible Prone, no allowance, or a veto makes no changes and emits no event.
    """
    cost = standing_cost(engine, actor, cost=cost, ignore_speed=ignore_speed)
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
