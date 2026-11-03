"""Reviewed Qi subpath effects, delivered through existing extension checkpoints.

Fresh catalogs seal scaling and Wind Walker ownership. Unimplemented clauses
remain explicit riders in reviewed authority; this module never reads live text.
"""
from copy import deepcopy
from dataclasses import replace

from . import effect, hook

WIND = 'tianxia.subpath.qi.storm_soul_cultivator.feature.wind_walker'
LIVING = 'tianxia.subpath.qi.calligraphy_cultivator.feature.living_character'
SHIELD = 'condition:typed.qi_character_shield'
MENDED = 'condition:typed.qi_character_mended'


def walk(rows):
    # Other plug-ins can carry non-effect mappings in an effects field.
    # Only typed effect lists belong to this opt-in scaling consumer.
    if not isinstance(rows, list):
        return
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        yield row
        for key in ('on_fail', 'on_success', 'on_hit', 'effects'):
            yield from walk(row.get(key))


@hook('compile_action')
def character_actions(action, info):
    original = action.parameters.get('typed') or {}
    if not any(r.get('qi_subpaths_scaling') for r in walk(original.get('effects'))) and not any(
            r.get('type') in {'qi_character_mend', 'qi_character_shield'}
            for r in original.get('effects') or [] if isinstance(r, dict)):
        return None
    typed = deepcopy(original)
    cl = int(typed.get('numbers', {}).get('cl') or 1)
    for row in walk(typed.get('effects')):
        kind = row.get('qi_subpaths_scaling')
        if kind in {'gale', 'flame'}:
            row['dice']['count'] = (3 if kind == 'gale' else 2) + int(cl >= 11) + int(cl >= 17)
    update = {'parameters': {**action.parameters, 'typed': typed}}
    if any(r.get('type') in {'qi_character_mend', 'qi_character_shield'}
           for r in typed.get('effects') or [] if isinstance(r, dict)):
        update['target_kind'] = 'ALLY_OR_SELF'
    return action.model_copy(update=update)


@hook('compile_passives')
def wind_marker(rows, info):
    if WIND not in info.get('owned_ids', ()):
        return rows
    return [*rows, {'block': 'qi_wind_walker', 'feature_id': WIND,
                   'cl': int(info['numbers'].get('cl') or 1)}]


def wind(engine, actor):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == 'qi_wind_walker' and r.get('feature_id') == WIND), None)


@hook('speed')
def walking_speed(engine, actor):
    return 10 if wind(engine, actor) else None


@hook('save')
def prone_save(ctx, subject, ability, named):
    if wind(ctx.engine, subject) and 'prone' in set(named or ()):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    return None


@hook('falling_damage')
def soften_fall(engine, target, defended, fall, intent):
    row = wind(engine, target)
    return {'amount': max(0, defended - 5 * row['cl'])} if row else None


@hook('forced_movement_reduction')
def wind_displacement(ctx, subject):
    if not wind(ctx.engine, subject):
        return None
    typed = ctx.typed
    tags = {str(tag).lower() for tag in typed.get('tags') or ()}
    sphere = typed.get('sphere')
    if tags & {'air', 'wind', 'weather'} or sphere in {'tianxia.sphere.air', 'tianxia.sphere.weather'}:
        return 10
    return None


@effect('qi_character_displacement')
def displace(ctx, row):
    from .general_combat_riders import directed_forced_movement
    cl = int(ctx.numbers.get('cl') or 1)
    feet = int(row['distance_ft']) + (5 * (int(cl >= 11) + int(cl >= 17)) if row.get('scaled') else 0)
    directed_forced_movement(ctx, {**row, 'distance_ft': feet,
                                   'relative_directions': ['away', 'toward']})


@effect('qi_character_mend')
def mend(ctx, row):
    from ..typed_executor import effect_subjects, block_healing
    cl = int(ctx.numbers.get('cl') or 1)
    for subject in effect_subjects(ctx, row, harmful=False):
        if any(c.condition_id == MENDED for c in subject.conditions.values()):
            continue
        ctx.engine._apply_condition(subject, MENDED, ctx.source, ctx.actor.entity_id,
            expires_on='END_OF_CURRENT_TURN', data={'label': 'Character of Mend received this turn'})
        block_healing(replace(ctx, target=subject, targets=[subject]),
            {'type': 'healing', 'applies_to': 'target',
             'dice': {'count': 1 + int(cl >= 11) + int(cl >= 17), 'sides': 8},
             'formula': 'key_ability_modifier'})


@effect('qi_character_shield')
def shield(ctx, row):
    from ..typed_executor import effect_subjects, effect_expiry
    from .condition_ownership import remove_instance
    cl = int(ctx.numbers.get('cl') or 1)
    for subject in effect_subjects(ctx, row, harmful=False):
        for held in list(subject.conditions.values()):
            if held.condition_id == SHIELD and held.source_actor_id == ctx.actor.entity_id:
                remove_instance(ctx.engine, subject, held.instance_id, ctx.source)
        ctx.engine._apply_condition(subject, SHIELD, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, {'duration': 'until_start_of_your_next_turn'}, subject, condition=True),
            data={'ac': 2 if cl >= 17 else 1, 'label': 'Character of Shield'})
        if cl >= 11:
            ctx.engine._grant_temp_hp(subject, int(ctx.numbers.get('pb') or 0), ctx.source, ctx.actor.entity_id)


@hook('ac')
def shield_ac(engine, target):
    return max((int(c.data['ac']) for c in target.conditions.values() if c.condition_id == SHIELD), default=0) or None
