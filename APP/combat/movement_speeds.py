"""Scoped Speed reductions shared by walking, flight and climbing.

Condition data movement_speed_reductions maps a native mode to nonnegative
integer feet. Omission is inert. Global speed_zero/immobilization still wins;
a zero walking Speed never erases an independently granted Fly/Climb Speed.
"""


def reduced(actor, mode, speed):
    total = 0
    for held in actor.conditions.values():
        if held.data.get('suppressed') or held.condition_id.startswith('condition:typed.suppressed.'):
            continue
        values = held.data.get('movement_speed_reductions', {})
        if not isinstance(values, dict) or any(k not in {'walk', 'fly', 'climb', 'burrow', 'swim'}
                or type(v) is not int or v < 0 for k, v in values.items()):
            raise ValueError('movement_speed_reductions requires native modes and nonnegative integer feet')
        total += values.get(mode, 0)
    return max(0, speed - total)


def globally_mobile(engine, actor):
    if not any(held.data.get('movement_speed_reductions') for held in actor.conditions.values()):
        return engine._effective_speed(actor) > 0
    return engine._effective_speed(actor, ignore_mode_reductions=True) > 0


def can_move(engine, actor, mode):
    if not globally_mobile(engine, actor):
        return False
    if mode == 'fly':
        from .flight import profile
        return profile(engine, actor).speed_ft > 0
    if mode == 'climb':
        from .roof_movement import profile
        return max(engine._effective_speed(actor), profile(engine, actor).speed_ft) > 0
    return engine._effective_speed(actor) > 0
