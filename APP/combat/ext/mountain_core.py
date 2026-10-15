"""Mountain Core's Earth Resilience, gated by its retained owned passive row.

Every query checks current surface contact. Landing damage is queried after
relocation, so landing on stable ground receives the printed 5 x Qi CL
reduction while airborne attacks/saves do not receive grounded benefits.
"""
from . import hook
from .surface_contact import contact
from .passive_rows import row_of

PREFIX = 'tianxia.subpath.qi.mountain_core_cultivator.feature.'
EARTH = PREFIX + 'earth_resilience'
BLOCK = 'mountain_core'


@hook('compile_block')
def compile_mountain(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'numbers': dict(numbers)}]


def _earth(engine, actor):
    row = row_of(engine, getattr(actor, 'entity_id', ''), BLOCK, 'earth_resilience')
    return row if row and contact(engine, actor, {'earth', 'stone', 'metal'}) else None


@hook('ac')
def earth_ac(engine, target):
    return 1 if _earth(engine, target) else None


@hook('save_mode')
def earth_strength(engine, target, ability, dc, source_id, roll_context):
    return 'ADVANTAGE' if str(ability).upper() == 'STR' and _earth(engine, target) else None


@hook('forced_distance')
def earth_forced_distance(engine, mover, source, distance_ft):
    return 10 if _earth(engine, mover) else None


@hook('size_steps')
def earth_shove_size(engine, actor, role, purposes):
    if role == 'resist' and 'shove' in (purposes or ()) and _earth(engine, actor):
        return 1
    return None


@hook('falling_damage')
def earth_landing(engine, target, amount, fall, intent):
    row = _earth(engine, target)
    if row:
        return {'amount': max(0, amount - 5 * int(row['numbers']['cl']))}
    return None


STONE = PREFIX + 'stone_sense'


@hook('sense_grant_allowed')
def stone_grant(engine, actor, grant, seen):
    if grant.get('feature_id') != STONE:
        return None
    if not row_of(engine, actor.entity_id, BLOCK, 'stone_sense') or not contact(engine, actor, {'earth','stone','metal'},stable=False,standing=False):
        return False
    if seen is None:
        return None
    if getattr(seen, 'perception_cell', False) or not contact(engine, seen, {'earth','stone','metal'},stable=False,standing=False):
        return False
    # Motion lasts through this turn and ends at this creature's next turn
    # start. Read committed native movement, including forced movement, so
    # airborne/teleport destinations never masquerade as ground vibrations.
    for event in reversed(engine.events):
        if event.actor_id != seen.entity_id:
            continue
        if event.event_type == 'TURN_STARTED':
            return False
        if event.event_type == 'MOVEMENT_COMMITTED':
            path = event.payload.get('path') or []
            return len(path)>1 and path[0]!=path[-1] and not event.payload.get('teleport')
    return False


@hook('difficult_zone_exempt')
def mountain_footing(engine, actor, zone):
    if not row_of(engine, actor.entity_id, BLOCK, 'stone_sense'):
        return None
    profile=zone.trigger_profile or {}
    if not profile.get('difficult'):
        return None
    words=' '.join(str(x) for x in profile.get('terrain') or [])+' '+str(profile.get('name') or '')+' '+str((profile.get('visual') or {}).get('material') or '')
    return True if any(x in words.lower() for x in ('rubble','loose earth','mud','stone fragment','uneven worked stone','shallow natural fissure')) else None
