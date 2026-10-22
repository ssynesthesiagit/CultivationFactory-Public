"""Native True Reflection damage reaction and printed independent body.

The native acquired summon profile authenticates ownership. This narrow provider
does not implement Echoed Patterns, Sovereign Reflection or the full command
procedure; those remain explicit parent blockers. No original template, gear,
identity, memories or hidden powers are copied.
"""
from contextvars import ContextVar
from . import hook, effect

SOURCE = 'tianxia.subpath.qi.mirror_cultivator.feature.true_reflection'
GROUP = 'true_doppelganger'
SPENT = 'condition:typed.true_reflection_spent'
_TRIGGER = ContextVar('true_reflection_damage_packet', default=None)


@hook('compile_reaction')
def reactions(row, info):
    """Reseal the acquired row before native Auto/Ask/order/off processing."""
    if row.get('feature_id') != SOURCE:
        return None
    numbers = dict(row['numbers'])
    if int(numbers['cl']) < 18:
        return {**row, 'held_back': True}
    return {**row,
        'block': 'generic', 'feature_id': SOURCE, 'name': 'True Reflection',
        'kind': 'true_reflection_damage', 'subject_relation': 'any', 'includes_self': True,
        'range_ft': 60,
        'costs': [{'resource_id': 'resource:core.qi', 'amount': 8}],
        'numbers': numbers, 'effects': [{'type': 'true_reflection_manifest'}]}


def _spaces(engine, body, original):
    from ..gate2_runtime_models import Position
    from ..footprint_registry import resolve_actor_footprint
    size = original.size_category
    size = size if size in ('Tiny', 'Small', 'Medium', 'Large') else 'Large'
    footprint, _ = resolve_actor_footprint(body.entity_id, summon_record={**body.summon, 'size': size.lower()})
    occupied = {cell for other in engine.state.actors.values() if other.active and other.entity_id != body.entity_id
                for cell in engine._actor_volume(other)}
    return {f'{x},{y},{z}': p
        for z in range(max(0, original.position.z - 2), original.position.z + 3)
        for y in range(max(0, original.position.y - 2), min(engine.grid.height, original.position.y + 3))
        for x in range(max(0, original.position.x - 2), min(engine.grid.width, original.position.x + 3))
        if engine.grid.distance_ft(original.position, p := Position(x=x, y=y, z=z)) <= 10
        and engine.grid.volume_legal(p, footprint=footprint, occupied_cells=occupied)}


@hook('damage_applied')
def damage_trigger(engine, event):
    if int(event.payload.get('hp_damage') or 0) + int(event.payload.get('temporary_hp_absorbed') or 0) <= 0:
        return
    attacker = engine.state.actors.get(event.actor_id)
    if attacker is None:
        return
    from ..typed_reactions import dispatch_creature_reactions
    from ..target_knowledge import located
    from ..summons import owned_by

    def eligible(row, watcher, harmed):
        if row.get('feature_id') != SOURCE or any(c.condition_id == SPENT for c in watcher.conditions.values()):
            return False
        if watcher.entity_id != harmed.entity_id and (watcher.team_id != harmed.team_id or not located(engine, watcher, harmed)):
            return False
        body = next(iter(owned_by(engine, watcher.entity_id, GROUP)), None)
        return body is not None and bool(_spaces(engine, body, attacker))

    for tid in event.target_ids:
        harmed = engine.state.actors.get(tid)
        if harmed is not None:
            token = _TRIGGER.set((engine, event))
            try:
                dispatch_creature_reactions(engine, attacker, 'true_reflection_damage',
                    source_id=event.source_definition_id, target=attacker,
                    accept=lambda row, watcher: eligible(row, watcher, harmed))
            finally:
                _TRIGGER.reset(token)


@effect('true_reflection_manifest')
def manifest(ctx, effect):
    from .. import summons
    from ..target_knowledge import located
    from ..senses import perceives_cell
    from .needle import ask, checkpoint_id
    from .effect_durations import round_token
    trigger = _TRIGGER.get()
    if trigger is None or trigger[0] is not ctx.engine or trigger[1].actor_id != getattr(ctx.target, 'entity_id', None):
        raise ValueError('True Reflection requires its actual native damage packet')
    packet = trigger[1]
    original = ctx.target
    body = next(iter(summons.owned_by(ctx.engine, ctx.actor.entity_id, GROUP)), None)
    if original is None or body is None:
        raise ValueError('True Reflection requires its acquired body and damaging creature')
    spaces = _spaces(ctx.engine, body, original)
    label = original.display_name if located(ctx.engine, ctx.actor, original) else 'the damaging creature'
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'true_reflection_space', original.entity_id),
        ctx.actor, 'choice:needle.true_reflection_space', list(spaces),
        labels={k: f'Empty space ({p.x}, {p.y}, {p.z})' for k, p in spaces.items()},
        automatic_options=[k for k, p in spaces.items() if perceives_cell(ctx.engine, ctx.actor, p)],
        feature_id=SOURCE, name='True Reflection',
        prompt=f'True Reflection: after {label} deals damage, place your True Doppelganger within 10 feet of it. Spend your Reaction and 8 Qi; it lasts 1 minute with Concentration, once per scene.')
    mode = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'mirror_strike_reach'), ctx.actor,
        'choice:needle.mirror_strike_reach', ['melee', 'ranged'], feature_id=SOURCE,
        labels={'melee': 'Mirror Strike: reach 10 feet', 'ranged': 'Mirror Strike: range 60 feet'},
        name='True Reflection — Mirror Strike',
        prompt='True Reflection: choose your Doppelganger’s Mirror Strike reach when created: 10 feet or range 60 feet. No additional cost.')
    if not chosen or not mode:
        raise ValueError('True Reflection has no known legal placement')
    size = original.size_category
    body.size_category = size if size in ('Tiny', 'Small', 'Medium', 'Large') else 'Large'
    body.summon['size'] = body.size_category.lower()
    from ..footprint_registry import resolve_actor_footprint
    ctx.engine.actor_footprints[body.entity_id], _ = resolve_actor_footprint(body.entity_id, summon_record=body.summon)
    arrived = summons.summon(ctx.engine, ctx.actor, GROUP, SOURCE, destination=spaces[chosen[0]],
        placement_origin=original.position, placement_range_ft=10)
    if arrived != [body.entity_id]:
        raise ValueError('True Reflection placement was blocked')
    body.summon.update(original_actor=original.entity_id, mirror_strike_mode=mode[0],
        visible_form='A visibly reflected outline', source_cl=int(ctx.numbers['cl']),
        expires_on=round_token(ctx.engine, 10), duration_text='1 minute')
    # The source and owner come only from the acquired profile, not the intent.
    ctx.engine._start_concentration(ctx.actor, SOURCE)
    ctx.engine._apply_condition(ctx.actor, SPENT, SOURCE, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'label': 'True Reflection used this scene'})
    for sense in ('darkvision', 'qi_sensing'):
        ctx.engine._apply_condition(body, 'condition:typed.sense', SOURCE + ':' + sense, ctx.actor.entity_id,
            expires_on=body.summon['expires_on'], data={'sense': sense, 'range_ft': 60,
                'label': sense.replace('_', ' ').title() + ' 60 feet'})
    body.summon['trigger_damage_type'] = str(packet.payload.get('damage_type') or 'UNTYPED')
    body.summon['trigger_sequence'] = int(packet.sequence)


@hook('candidate_allowed')
def strike_geometry(engine, actor, candidate, action):
    record = actor.summon or {}
    if record.get('source') != SOURCE or action is None or not action.display_name.startswith('Mirror Strike'):
        return None
    if ('ranged' in action.display_name) != (record.get('mirror_strike_mode') == 'ranged'):
        return False
    maximum = 60 if record.get('mirror_strike_mode') == 'ranged' else 10
    return False if any(engine._distance_actor_to_actor(actor, engine.state.actors[t]) > maximum for t in candidate.target_ids) else None


@hook('damage_type_choices')
def strike_damage_types(ctx, kinds):
    record = ctx.actor.summon or {}
    if record.get('source') != SOURCE:
        return None
    trigger = str(record.get('trigger_damage_type') or '').upper()
    return [*kinds, trigger] if trigger and trigger != 'UNTYPED' and trigger not in {str(k).upper() for k in kinds} else None
