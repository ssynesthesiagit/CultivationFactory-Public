"""Ordinary strike eligibility shared by Ancestral Channeler and Equal Measure.

The enclosing ability pays its action economy; the chosen weapon/unarmed strike
still owns hand prerequisites, delivery, reach, geometry and attack payload.
No compiled strike is created, no source is identified by its display name.
"""


def ready(engine, actor, action):
    from .hand_occupancy import weapon_allowed
    required = (action.parameters or {}).get('requires_condition')
    return (not required or engine._has_condition(actor, required)) and weapon_allowed(engine, actor, action) is not False


def options(engine, actor, target, *, include_variants=True):
    from ..attack_reach import melee
    from .reach_bonus import MARK, current_reach
    strikes = []
    for aid in actor.action_ids:
        action = engine.action_catalog.get(aid)
        typed = (action.parameters or {}).get('typed') or {} if action else {}
        attack = next((e for e in typed.get('effects', []) if e.get('type') == 'attack'), None)
        if action is None or attack is None or action.economy.value != 'ACTION':
            continue
        if not include_variants and '#' in aid:
            continue
        kind = str(attack.get('attack_kind') or '')
        typed_range = typed.get('range_ft') if type(typed.get('range_ft')) is int else None
        ranged = ('ranged' in kind or 'thrown' in kind or (typed_range is not None and typed_range > 0))
        if (not melee(action) and not ranged) or (action.parameters or {}).get(MARK):
            continue
        if (typed.get('delivered_by') or typed.get('forged_from') or typed.get('base_form') or typed.get('use_limit') or action.costs):
            continue
        if not (typed.get('weapon') is not None or kind in ('unarmed', 'natural_weapon')):
            continue
        if not ready(engine, actor, action) or int((action.parameters or {}).get('expected_damage') or 0) <= 0:
            continue
        reach = int(action.range_ft or action.reach_ft or 5) if ranged else current_reach(engine, actor, action)
        distance = engine._effect_distance(actor, target)
        if distance > reach:
            continue
        selected = action
        if distance > int(action.range_ft or action.reach_ft or 5):
            selected = next((v for v in (engine.action_catalog.get(x) for x in actor.action_ids)
                             if v is not None and ((v.parameters or {}).get(MARK) or {}).get('menu_variant')
                             and ((v.parameters or {}).get(MARK) or {}).get('base') == aid), None)
            if selected is None:
                continue
        strikes.append((selected, attack, typed, list(typed.get('effects') or [])))
    return strikes
