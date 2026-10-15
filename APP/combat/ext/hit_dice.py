"""Explicit Hit Die pools shared by Red Thread Release and future die spenders.

Sheets may represent ability_scores_and_statistics.hit_dice as a list of
{sides, remaining, maximum} integer records. Nothing infers die size or count
from CL, Path, Hit Points or a name. Missing data creates no resource.
"""
from . import hook

PREFIX = 'resource:core.hit_dice.d'


@hook('compile_resources')
def pools(info):
    from ..gate2_runtime_models import ResourceDefinition
    rows = (info['owner_sheet'].get('ability_scores_and_statistics') or {}).get('hit_dice') or []
    result = []
    for row in rows:
        sides, remaining, maximum = (row.get(k) for k in ('sides', 'remaining', 'maximum'))
        if sides not in (4, 6, 8, 10, 12, 20) or any(type(v) is not int for v in (sides, remaining, maximum)) or not 0 <= remaining <= maximum:
            raise ValueError('Hit Dice require an explicit die size and valid remaining/maximum counts')
        result.append(ResourceDefinition(resource_id=PREFIX + str(sides), initial=remaining, maximum=maximum))
    return result


def available(actor):
    return {key: int(key.removeprefix(PREFIX)) for key, count in actor.resources.items()
            if key.startswith(PREFIX) and key.removeprefix(PREFIX).isdigit() and count > 0}


def spend(engine, actor, key, source):
    from ..gate2_runtime_models import DiceSpec
    options = available(actor)
    if key not in options:
        raise ValueError('No remaining Hit Die of that size')
    engine._spend_resource(actor, key, 1, source)
    roll = engine.roller.roll(DiceSpec(count=1, sides=options[key]), actor_id=actor.entity_id, reason='HIT_DIE_RELEASE', mode='NORMAL')
    engine._record_roll(roll)
    return roll.total
