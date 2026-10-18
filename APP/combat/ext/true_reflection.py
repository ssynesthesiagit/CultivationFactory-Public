"""True Reflection's source-specific reaction and independent Asset body.

Never clones a creature template: its only statistics/actions are the printed
True Doppelganger profile. Visible form is descriptive, not borrowed identity.
"""
from copy import deepcopy
from . import hook, effect

SOURCE = 'tianxia.subpath.qi.mirror_cultivator.feature.true_reflection'
GROUP = 'true_doppelganger'
SPENT = 'condition:typed.true_reflection_spent'


@hook('summon_catalog')
def catalogue(table, info):
    if SOURCE not in info['owned_ids']:
        return None
    table['sources'][SOURCE] = {'creature': GROUP, 'arrives': 'action', 'count': 1,
        'command': 'bonus_action', 'command_range_ft': None, 'range_ft': 60,
        'concentration': True, 'duration_rounds': 10,
        'actor_policy': {'basic_actions': ['Dash', 'Disengage', 'Dodge', 'Help', 'Hide', 'Search'],
            'printed_reactions_only': 1, 'owning_path': 'tianxia.path.qi_cultivation'}}
    table['creatures'][GROUP] = {'name': 'True Doppelganger', 'ac': '15+pb', 'hp': '6*cl',
        'speed': 40, 'saves_from_owner': True,
        'resist_damage': ['BLUDGEONING', 'PIERCING', 'SLASHING', 'FORCE', 'PSYCHIC'],
        'immune_damage': ['POISON'], 'immune_conditions': ['charmed', 'frightened', 'poisoned'],
        'attacks': [
            {'name': 'Mirror Strike', 'attack_bonus': 'atk', 'dice': '3d8',
                'bonus': 'key', 'damage_type': 'FORCE', 'damage_types': ['FORCE', 'PSYCHIC'], 'reach_ft': 10},
            {'name': 'Mirror Strike (ranged)', 'attack_bonus': 'atk', 'dice': '3d8',
                'bonus': 'key', 'damage_type': 'FORCE', 'damage_types': ['FORCE', 'PSYCHIC'],
                'range_ft': 60, 'attack_kind': 'cultivation_ranged'}]}
    return table


@hook('compile_bundle')
def reactions(bundle, info):
    if not any(c['summon']['source'] == SOURCE for c in bundle.get('summons', ())):
        return None
    from ..activation_settlement import path_numbers
    numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    if numbers['cl'] < 18:
        return None
    bundle['typed_reactions'] = [r for r in bundle['typed_reactions'] if r.get('feature_id') != SOURCE]
    bundle['typed_reactions'].append({'block': 'generic', 'feature_id': SOURCE,
        'name': 'True Reflection', 'kind': 'true_reflection_damage',
        'subject_relation': 'any', 'includes_self': True, 'range_ft': 60,
        'ask': bool(bundle.get('reaction_plan', {}).get('ask')),
        'costs': [{'resource_id': 'resource:core.qi', 'amount': 8}],
        'numbers': numbers, 'effects': [{'type': 'true_reflection_manifest'}]})
    return bundle


@hook('event', nested=True)
def damage_trigger(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    payload = kwargs.get('payload') or {}
    if int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0:
        return
    attacker = engine.state.actors.get(kwargs.get('actor_id'))
    if attacker is None:
        return
    from ..typed_reactions import dispatch_creature_reactions
    from ..target_knowledge import located
    for tid in kwargs.get('target_ids') or ():
        harmed = engine.state.actors.get(tid)
        if harmed is None:
            continue
        dispatch_creature_reactions(engine, attacker, 'true_reflection_damage',
            source_id=kwargs.get('source_definition_id'),
            accept=lambda row, watcher: row.get('feature_id') == SOURCE
                and not any(c.condition_id == SPENT for c in watcher.conditions.values())
                and (watcher.entity_id == tid or (watcher.team_id == harmed.team_id and located(engine, watcher, harmed))))


@effect('true_reflection_manifest')
def manifest(ctx, effect):
    from .. import summons
    from ..gate2_runtime_models import Position
    from .needle import ask, checkpoint_id
    from .effect_durations import round_token
    original = ctx.target
    if original is None:
        return
    body = next(iter(summons.owned_by(ctx.engine, ctx.actor.entity_id, GROUP)), None)
    if body is None:
        return
    size = original.size_category
    body.size_category = size if size in ('Tiny', 'Small', 'Medium', 'Large') else 'Large'
    body.summon['size'] = body.size_category.lower()
    from ..footprint_registry import resolve_actor_footprint
    ctx.engine.actor_footprints[body.entity_id], _ = resolve_actor_footprint(body.entity_id, summon_record=body.summon)
    options = {}
    for y in range(ctx.engine.grid.height):
        for x in range(ctx.engine.grid.width):
            p = Position(x=x, y=y, z=original.position.z)
            if ctx.engine.grid.distance_ft(original.position, p) <= 10 and ctx.engine.grid.placement_legal(
                p, footprint=ctx.engine._footprint(body), occupied_cells=ctx.engine._occupied_cells_except(body.entity_id)):
                options[f'{x},{y},{p.z}'] = p
    if not options:
        return
    from ..target_knowledge import located
    from ..senses import perceives_cell
    original_label = original.display_name if located(ctx.engine, ctx.actor, original) else 'the damaging creature'
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'true_reflection_space', original.entity_id),
        ctx.actor, 'choice:needle.true_reflection_space', list(options),
        labels={k: f'Empty space ({v.x}, {v.y}, {v.z})' for k, v in options.items()},
        automatic_options=[k for k, p in options.items() if perceives_cell(ctx.engine, ctx.actor, p)],
        name='True Reflection', prompt=f'True Reflection: place your Doppelganger within 10 feet of {original_label}. It costs your Reaction and 8 Qi, lasts 1 minute with Concentration, and can be used once per scene.')
    if not chosen:
        return
    reach = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'mirror_strike_reach'), ctx.actor,
        'choice:needle.mirror_strike_reach', ['melee', 'ranged'],
        labels={'melee': 'Mirror Strike: reach 10 feet', 'ranged': 'Mirror Strike: range 60 feet'},
        name='True Reflection — Mirror Strike', prompt='Choose the Doppelganger’s Mirror Strike reach when created: reach 10 feet or range 60 feet. This choice adds no cost.')
    arrived = summons.summon(ctx.engine, ctx.actor, GROUP, SOURCE, destination=options[chosen[0]],
        placement_origin=original.position, placement_range_ft=10)
    if not arrived:
        return
    body.summon.update(original_actor=original.entity_id, mirror_strike_mode=reach[0],
        visible_form='A visibly reflected outline')
    body.summon['expires_on'] = round_token(ctx.engine, 10)
    body.summon['duration_text'] = '1 minute'
    ctx.engine._start_concentration(ctx.actor, SOURCE)
    ctx.engine._apply_condition(ctx.actor, SPENT, SOURCE, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'label': 'True Reflection used this scene'})
    for sense in ('darkvision', 'qi_sensing'):
        ctx.engine._apply_condition(body, 'condition:typed.sense', SOURCE + ':' + sense, ctx.actor.entity_id,
            expires_on=body.summon['expires_on'], data={'sense': sense, 'range_ft': 60,
                'label': sense.replace('_', ' ').title() + ' 60 feet'})
    # Only the actual triggering packet's type is recorded; no catalogue scan.
    packet = next((e for e in reversed(ctx.engine.events) if e.event_type == 'DAMAGE_COMMITTED'
        and e.actor_id == original.entity_id), None)
    if packet is not None:
        body.summon['trigger_damage_type'] = str(packet.payload.get('damage_type') or 'UNTYPED')


@hook('candidate_allowed')
def strike_geometry(engine, actor, candidate, action):
    record = actor.summon or {}
    if record.get('source') != SOURCE or action is None or not action.display_name.startswith('Mirror Strike'):
        return None
    if ('ranged' in action.display_name) != (record.get('mirror_strike_mode') == 'ranged'):
        return False
    maximum = 60 if record.get('mirror_strike_mode') == 'ranged' else 10
    return False if any(engine._distance_actor_to_actor(actor, engine.state.actors[t]) > maximum
                        for t in candidate.target_ids) else None
