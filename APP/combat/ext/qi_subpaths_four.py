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
BINDING = 'tianxia.subpath.qi.calligraphy_cultivator.feature.character_of_binding'
GREAT = 'tianxia.subpath.qi.calligraphy_cultivator.feature.great_character'
HEAVEN = 'tianxia.subpath.qi.calligraphy_cultivator.feature.heaven_s_script'
SCROLL = 'tianxia.subpath.qi.calligraphy_cultivator.feature.scroll_of_storage'
BINDING_HOLD = 'qi_calligraphy_binding'


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


@hook('compile_action', priority=50)
def binding_action(action, info):
    """Replace the incomplete generated Binding packet at its owned source."""
    original = action.parameters.get('typed') or {}
    if original.get('source') != BINDING or action.parameters.get('qi_binding_rewrite'):
        return None
    typed = deepcopy(original)
    typed.update(effects=[{'type': 'qi_binding_character'}], riders=[], min_cl=14,
                 duration={'kind': 'minutes', 'amount': 1, 'concentration': True})
    return action.model_copy(update={'target_kind': 'ANY_CREATURE', 'range_ft': 60,
        'concentration': True, 'costs': (('resource:core.qi', 5),),
        'parameters': {**action.parameters, 'typed': typed}})


def binding_objects(engine, owner):
    """Live anchors belonging to this source owner; unrelated objects are inert."""
    return [o for o in engine.state.objects.values() if not o.destroyed
            and (o.component or {}).get(BINDING_HOLD, {}).get('owner') == owner.entity_id]


def legal_anchor_cells(engine, origin, feet):
    """Every unoccupied, legal map cell, without a player-menu truncation."""
    from ..gate2_runtime_models import Position
    from .placed import free_square
    from .objects import blocker_at
    grid = engine.grid
    reach = max(0, int(feet) // int(grid.square_size_ft))
    xs = range(max(0, origin.x - reach), min(grid.width, origin.x + reach + 1))
    ys = range(max(0, origin.y - reach), min(grid.height, origin.y + reach + 1))
    # Every legal height within reach, not only the origin's altitude (a space above or below is a legal placement).
    zs = range(max(0, origin.z - reach), origin.z + reach + 1)
    return [p for x in xs for y in ys for z in zs
            if (p := Position(x=x, y=y, z=z)) is not None
            and grid.distance_ft(origin, p) <= feet and free_square(engine, p)
            and grid.volume_legal(p) and blocker_at(engine, p) is None]


def choose_cell(ctx, cells, title, *, chooser=None):
    from .needle import ask, checkpoint_id, cell_id, position_of
    if not cells:
        return None
    options = [cell_id(p, include_altitude=True) for p in cells]
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, title, ctx.source), chooser or ctx.actor,
        'choice:needle.qi_calligraphy_cell', options,
        labels={key: f'{title}: ({p.x}, {p.y}), altitude {p.z * 5} feet'
                for key, p in zip(options, cells)}, prompt=title, name=title)
    return position_of(selected[0]) if selected else None


def end_binding(engine, obj, source):
    from .condition_ownership import remove_instance
    if engine.__dict__.get('_calligraphy_ending_binding'):
        return
    record = (obj.component or {}).get(BINDING_HOLD) or {}
    engine.__dict__['_calligraphy_ending_binding'] = True
    try:
        for actor in engine.state.actors.values():
            for held in list(actor.conditions.values()):
                if held.instance_id in record.get('instances', ()):
                    remove_instance(engine, actor, held.instance_id, source)
        if not obj.destroyed:
            engine._update_object(obj.model_copy(update={'destroyed': True, 'current_hp': 0}),
                                  source, record.get('owner'))
    finally:
        engine.__dict__.pop('_calligraphy_ending_binding', None)


@effect('qi_binding_character', harmful=True)
def binding_character(ctx, row):
    from ..typed_executor import run_effects
    from . import bound_objects
    from .placed import note
    if ctx.typed.get('source') != BINDING or ctx.action.owner_id != ctx.actor.entity_id:
        return
    target = ctx.target or next(iter(ctx.targets), None)
    if target is None:
        return
    cells = [p for p in legal_anchor_cells(ctx.engine, target.position, 5)
             if p != target.position]
    location = choose_cell(ctx, cells, f'Character of Binding: place the visible Anchor adjacent to {target.display_name}')
    if location is None:
        raise ValueError('Character of Binding needs a legal unoccupied adjacent Anchor space.')
    for obj in binding_objects(ctx.engine, ctx.actor):
        end_binding(ctx.engine, obj, ctx.source)
    local = replace(ctx, targets=[target], target=target)
    run_effects(local, [{'type': 'save', 'ability': 'cha', 'applies_to': 'target',
        'dc': 'technique_save_dc',
        'on_fail': [{'type': 'condition', 'condition': 'restrained', 'duration': 'concentration',
                     'qi_calligraphy_binding': 1}],
        'on_success': [{'type': 'qi_calligraphy_lock', 'duration': 'until_start_of_your_next_turn',
                        'rule': {'no_willing_teleport': 1, 'speed_ft': -10},
                        'label': 'Character of Binding: Speed reduced by 10 feet; cannot willingly teleport until the writer’s next turn'}]}])
    # The anchor exists on either save result. Its own finite source marker
    # keeps it tied to Concentration without extending the successful-save lock.
    marker = 'condition:typed.qi_calligraphy_anchor'
    ctx.engine._apply_condition(ctx.actor, marker, ctx.source, ctx.actor.entity_id,
        expires_on='CONCENTRATION_END', data={'label': 'Character of Binding: maintaining one Anchor'})
    instance = next(c.instance_id for c in reversed(list(ctx.actor.conditions.values()))
                    if c.condition_id == marker and c.source_definition_id == ctx.source)
    from ..typed_executor import duration_expiry
    timer = 'condition:typed.qi_calligraphy_anchor_duration'
    deadline = duration_expiry(ctx.engine, {'kind': 'minutes', 'amount': 1},
                               source=ctx.actor, holder=ctx.actor)
    if deadline is None:
        raise ValueError('Character of Binding requires its finite one-minute expiry.')
    ctx.engine._apply_condition(ctx.actor, timer, ctx.source, ctx.actor.entity_id,
        expires_on=deadline, data={'label': 'Character of Binding: one-minute maximum duration'})
    timer_instance = next(c.instance_id for c in reversed(list(ctx.actor.conditions.values()))
                          if c.condition_id == timer and c.source_definition_id == ctx.source)
    held = [c for c in target.conditions.values() if c.data.get(BINDING_HOLD)
            and c.source_definition_id == ctx.source and c.source_actor_id == ctx.actor.entity_id]
    obj = bound_objects.place(ctx, {'name': 'Binding Anchor', 'kind': 'binding_anchor',
        'ac': 15, 'hp': '3*cl', 'resist': ['bludgeoning', 'piercing', 'slashing'],
        'native_lifecycle': True}, holder=ctx.actor, instance_ids=[instance], position=location)
    if obj is None:
        raise ValueError('Character of Binding could not create its Anchor.')
    component = deepcopy(obj.component)
    component.update(size='tiny', source_cl=int(ctx.numbers['cl']))
    component[BINDING_HOLD] = {'owner': ctx.actor.entity_id, 'target': target.entity_id,
        'marker': instance, 'timer': timer_instance,
        'instances': [instance, timer_instance, *[c.instance_id for c in held]]}
    ctx.engine._update_object(obj.model_copy(update={'component': component}), ctx.source, ctx.actor.entity_id)
    note(ctx.engine, ctx.source, ctx.actor,
         'Binding Anchor: Tiny, AC 15, '+str(3 * int(ctx.numbers['cl']))+
         ' Hit Points; resists Bludgeoning, Piercing and Slashing; immune to Poison and Psychic. '
         'Destroying or suppressing it ends its restraint.', [target])


@hook('condition_state')
def binding_condition(ctx, subject, row):
    if not row.get('qi_calligraphy_binding'):
        return None
    return {'data': {BINDING_HOLD: 1, 'save_dc': int(ctx.numbers['save_dc']),
        'rule': {'no_willing_teleport': 1, 'no_possession': 1, 'no_incorporeal': 1},
        'label': 'Character of Binding: Restrained; cannot willingly teleport, become Incorporeal or possess; Charisma save at each turn end'}}


@effect('qi_calligraphy_lock', harmful=True)
def character_lock(ctx, row):
    from ..typed_executor import effect_expiry
    for target in [ctx.target] if ctx.target else ctx.targets:
        ctx.engine._apply_condition(target, 'condition:typed.qi_calligraphy_lock', ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, target, condition=True),
            data={'rule': deepcopy(row['rule']), 'label': row['label']})


@hook('condition_attempt')
def calligraphy_condition_gate(ctx, subject, row):
    rules = [c.data.get('rule', {}) for c in subject.conditions.values()
             if c.data.get(BINDING_HOLD) or c.condition_id == 'condition:typed.qi_calligraphy_lock']
    if row.get('condition') == 'incorporeal' and any(r.get('no_incorporeal') for r in rules):
        return False
    if row.get('condition') == 'possessing' and any(r.get('no_possession') for r in rules):
        return False
    return None


@hook('condition_application_attempt')
def native_calligraphy_condition_gate(engine, target, condition_id, source_id, source_actor_id):
    return calligraphy_condition_gate(None, target, {'condition': condition_id.removeprefix('condition:typed.')})


@hook('speed')
def calligraphy_speed(engine, actor):
    return min((int(c.data.get('rule', {}).get('speed_ft', 0)) for c in actor.conditions.values()
                if c.condition_id == 'condition:typed.qi_calligraphy_lock'), default=0) or None


@hook('teleport_context_check')
def calligraphy_willing_teleport(engine, actor, start, destination, movement_context):
    if movement_context != 'WILLING':
        return None
    if any(c.data.get('rule', {}).get('no_willing_teleport') for c in actor.conditions.values()
           if c.data.get(BINDING_HOLD) or c.condition_id == 'condition:typed.qi_calligraphy_lock'):
        return False
    return None


@hook('turn_end')
def binding_repeat_save(engine, actor):
    from .condition_ownership import remove_instance
    for held in list(actor.conditions.values()):
        if not held.data.get(BINDING_HOLD):
            continue
        roll = engine._roll_save(actor, 'CHA', int(held.data['save_dc']), held.source_definition_id)
        if roll is not None and roll.total >= int(held.data['save_dc']):
            anchor = next((o for o in engine.state.objects.values()
                           if held.instance_id in (o.component or {}).get(BINDING_HOLD, {}).get('instances', ())), None)
            if anchor is not None:
                end_binding(engine, anchor, held.source_definition_id)
            else:
                remove_instance(engine, actor, held.instance_id, held.source_definition_id)


@hook('event')
def binding_lifecycle(engine, event_type, kwargs):
    if event_type not in {'OBJECT_UPDATED', 'MOVEMENT_COMMITTED', 'TURN_STARTED', 'CONDITION_REMOVED'}:
        return
    for obj in list(engine.state.objects.values()):
        record = (obj.component or {}).get(BINDING_HOLD)
        if not record:
            continue
        target = engine.state.actors.get(record['target'])
        owner = engine.state.actors.get(record['owner'])
        marker = owner and record['marker'] in owner.conditions and record['timer'] in owner.conditions
        if (obj.destroyed or obj.suppressed or not marker or target is None
                or engine.grid.distance_ft(obj.position, target.position) > 30):
            end_binding(engine, obj, kwargs.get('source_definition_id') or BINDING)


@hook('state_event')
def native_binding_lifecycle(engine, event):
    binding_lifecycle(engine, event.event_type, {'source_definition_id': event.source_definition_id})


@hook('compile_actions')
def rewrite_action(info):
    if BINDING not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.rewrite_binding_boundary",
        display_name='Rewrite the Boundary', owner_id=info['actor_id'], economy='BONUS_ACTION',
        resolution_kind='TYPED', target_kind='SELF', costs=(('resource:core.qi', 1),),
        parameters={'qi_binding_rewrite': 1, 'expected_damage': 0, 'typed': {'source': BINDING,
            'numbers': info['numbers'], 'effects': [{'type': 'qi_binding_rewrite'}], 'riders': []},
            'description': 'Bonus Action, 1 Qi: move your Binding Anchor up to 15 feet to a legal unoccupied space within 30 feet of its target.'})]


def rewrite_cells(engine, obj):
    """Legal Rewrite destinations: within 15 feet of the Anchor, never its own cell, and within
    30 feet of the held target. The one list both Rewrite gating (rewrite_available) and the
    committed move rebuild, so the offered option can never be paid for and do nothing."""
    target = engine.state.actors[(obj.component[BINDING_HOLD])['target']]
    return [p for p in legal_anchor_cells(engine, obj.position, 15)
            if p != obj.position and engine.grid.distance_ft(p, target.position) <= 30]


@hook('candidate_allowed')
def rewrite_available(engine, actor, candidate, action):
    if action is not None and action.parameters.get('qi_binding_rewrite'):
        for obj in binding_objects(engine, actor):
            if rewrite_cells(engine, obj):
                return True
        return False
    if action is not None and (action.parameters.get('typed') or {}).get('source') == BINDING:
        target = engine.state.actors.get(next(iter(candidate.target_ids), ''))
        return target is not None and bool([p for p in legal_anchor_cells(engine, target.position, 5)
                                           if p != target.position])
    return None


@effect('qi_binding_rewrite')
def rewrite_binding(ctx, row):
    for obj in binding_objects(ctx.engine, ctx.actor):
        target = ctx.engine.state.actors[(obj.component[BINDING_HOLD])['target']]
        destination = choose_cell(ctx, rewrite_cells(ctx.engine, obj), f'Rewrite the Boundary: move the Anchor holding {target.display_name} up to 15 feet (1 Qi)')
        if destination is not None:
            ctx.engine._update_object(obj.model_copy(update={'position': destination}), ctx.source, ctx.actor.entity_id)
