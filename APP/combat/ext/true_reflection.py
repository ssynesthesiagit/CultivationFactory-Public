"""True Reflection's source-specific reaction and independent Asset body.

Never clones a creature template: its only statistics/actions are the printed
True Doppelganger profile. Visible form is descriptive, not borrowed identity.
"""
from copy import deepcopy
from . import hook, effect

SOURCE = 'tianxia.subpath.qi.mirror_cultivator.feature.true_reflection'
GROUP = 'true_doppelganger'
SPENT = 'condition:typed.true_reflection_spent'
FIXATED = 'condition:typed.true_reflection_fixated'
GUARDING = 'condition:typed.guarding'
INTERCESSION = 'condition:typed.true_reflection_intercession'

# The six printed Echoed Patterns, keyed by the printed name a player reads.
# Each row carries only what the printed Pattern itself authorises; nothing is
# copied from the triggering technique beyond its own damage type.
PATTERNS = ('Assault Pattern', 'Burst Pattern', 'Restraint Pattern',
            'Shelter Pattern', 'Passage Pattern', 'Restoration Pattern')
SOVEREIGN = 'Sovereign Reflection'
# Severe primary effects Sovereign Reflection may reproduce (printed list).
SEVERE = ('stunned', 'paralyzed', 'unconscious', 'possession', 'banished',
          'banishment', 'transformation', 'sealed')


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
                'range_ft': 60, 'attack_kind': 'cultivation_ranged'}],
        # Mirrored Intercession: "An ally within 10 feet is hit by an attack" -> -2 on
        # the triggering attack roll, once per round.
        'innate_reaction': {'name': 'Mirrored Intercession', 'kind': 'ally_hit',
            'range_ft': 10, 'free': True,
            'effects': [{'type': 'true_reflection_intercession'}]}}
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
    _record_pattern(ctx, body, original, packet)


def _record_pattern(ctx, body, original, packet):
    """Record one Echoed Pattern, or Sovereign Reflection, from the actual trigger.

    Only printed categories the observed packet can honestly support are offered:
    the damage type is the packet's own, and Sovereign Reflection requires a
    severe primary effect actually recorded on it. No pattern is invented for a
    packet that carried no qualifying effect.
    """
    from .needle import ask, checkpoint_id
    record = body.summon
    damage_type = str(record.get('trigger_damage_type') or 'UNTYPED')
    if damage_type == 'UNTYPED':
        return
    payload = (packet.payload if packet is not None else {}) or {}
    severe = any(str(value).lower() in SEVERE
                 for value in payload.get('conditions_applied') or ())
    options = list(PATTERNS)
    labels = {name: f'{name}: reflect the printed effect in {damage_type.lower()} damage'
              for name in PATTERNS}
    if severe:
        options = [SOVEREIGN, *PATTERNS]
        labels[SOVEREIGN] = (f'{SOVEREIGN}: reproduce this severe primary effect with your '
                             'Cultivation Attack Modifier and Cultivation Save DC. It costs no '
                             'additional Qi beyond this activation and lasts at most 1 minute.')
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'true_reflection_pattern_record',
        body.entity_id), ctx.actor, 'choice:needle.true_reflection_pattern', options,
        labels=labels, name='True Reflection — Record Echoed Pattern',
        prompt=f'True Reflection: examine {original.display_name}\'s technique. Choose the closest '
               'legal Echoed Pattern for what it primarily did. You cannot pick a stronger category '
               'just because the original technique said more. The Pattern is used once and then erased.')
    if not picked:
        return
    chosen = picked[0]
    record['echoed_pattern'] = chosen
    record['pattern_damage_type'] = damage_type
    record['pattern_save'] = str(payload.get('save_ability') or ('DEX' if chosen == 'Burst Pattern' else 'CHA'))


@effect('true_reflection_intercession')
def mirrored_intercession(ctx, row):
    """Mirrored Intercession: -2 on the triggering attack roll, once per round.

    Dispatched as the Doppelganger's own printed Reaction by the engine, so the
    ordinary ally_hit offer already establishes that an ally within 10 feet was
    hit by an attack.
    """
    record = ctx.actor.summon or {}
    if record.get('source') != SOURCE:
        return
    attacker = ctx.engine.state.actors.get(record.get('attacker') or '')
    if attacker is None:
        attacker = next((other for other in ctx.engine.state.actors.values()
                         if other.active and other.team_id != ctx.actor.team_id
                         and other.entity_id != ctx.actor.entity_id), None)
    if attacker is None:
        return
    ctx.engine._add_modifier(attacker, SOURCE, 'attack_bonus', 'ADD', -2, 'THIS_ATTACK',
        source_actor_id=ctx.actor.entity_id)


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


@hook('damage_type_choices')
def strike_damage_types(ctx, kinds):
    """"Choose: Force. Psychic. One damage type dealt by the triggering damage packet."

    The third option is only legal when this actual manifestation recorded a real
    packet type; the sealed Force/Psychic pair is always retained. No recorded
    type means no third option, never a guessed one.
    """
    record = ctx.actor.summon or {}
    if record.get('source') != SOURCE:
        return None
    trigger = str(record.get('trigger_damage_type') or '').upper()
    if not trigger or trigger == 'UNTYPED' or trigger in {str(k).upper() for k in kinds}:
        return None
    return [*kinds, trigger]


@hook('attack_completed')
def fixate_original(engine, notice, intent):
    """Fixate the Original: the triggering creature's next attack roll against the
    Doppelganger is at Disadvantage, and ordinary visual concealment cannot make
    that roll advantageous. Refreshed once per that creature's turn."""
    attacker = engine.state.actors.get(notice.attacker_id)
    if attacker is None:
        return
    record = attacker.summon
    if record is None or record.get('source') != SOURCE:
        return
    target = engine.state.actors.get(notice.target_id)
    if target is None:
        return
    original = engine.state.actors.get(record.get('original_actor') or '')
    if original is None or notice.attacker_id != original.entity_id:
        return
    from .effect_durations import token
    for iid, existing in tuple(original.conditions.items()):
        if existing.condition_id == FIXATED and existing.source_actor_id == attacker.entity_id:
            engine._remove_condition(original, FIXATED, existing.source_definition_id)
    engine._add_modifier(original, SOURCE, 'attack_mode', 'SET', 'DISADVANTAGE', 'NEXT_ATTACK',
        expires_on=token('start', original.entity_id, int(original.turns_started) + 1),
        source_actor_id=attacker.entity_id)


@effect('true_reflection_guard')
def guard(ctx, row):
    """Command True Doppelganger -> Guard: it Dodges if it cannot attack."""
    if (ctx.actor.summon or {}).get('source') != SOURCE:
        return
    ctx.engine._apply_condition(ctx.actor, GUARDING, SOURCE, ctx.actor.entity_id,
        expires_on='START_OF_SELF_NEXT_TURN', data={'label': 'Guarding'})


@hook('summon_catalog')
def command_catalogue(table, info):
    """Command True Doppelganger: Guard and Use Echoed Pattern."""
    if SOURCE not in info['owned_ids']:
        return None
    creature = table['creatures'][GROUP]
    creature['specials'] = [
        {'id': 'guard', 'name': 'Guard', 'target_kind': 'SELF',
         'effects': [{'type': 'true_reflection_guard'}]},
        {'id': 'echoed_pattern', 'name': 'Use Echoed Pattern',
         'target_kind': 'ANY_CREATURE', 'range_ft': 60,
         'effects': [{'type': 'true_reflection_pattern'}]}]
    return table


@hook('candidate_allowed')
def pattern_available(engine, actor, candidate, action):
    record = actor.summon or {}
    if record.get('source') != SOURCE or action is None or action.display_name != 'Use Echoed Pattern':
        return None
    return None if record.get('echoed_pattern') else False


@effect('true_reflection_pattern')
def use_pattern(ctx, row):
    """Use the recorded Echoed Pattern once, then erase it."""
    record = ctx.actor.summon or {}
    if record.get('source') != SOURCE:
        return
    pattern = record.get('echoed_pattern')
    if pattern not in (*PATTERNS, SOVEREIGN):
        return
    kind = record.get('pattern_damage_type')
    if not kind or kind == 'UNTYPED':
        kind = 'FORCE'
    if pattern == 'Assault Pattern':
        ctx.engine._append_event('DAMAGE_COMMITTED', SOURCE, actor_id=ctx.actor.entity_id,
            target_ids=(ctx.target.entity_id,), payload={'hp_damage': 0, 'damage_type': kind,
                'text': f'{ctx.actor.display_name} uses Assault Pattern.'})
        from dataclasses import replace
        from ..typed_executor import run_effects
        run_effects(replace(ctx, targets=[ctx.target]),
                    [{'type': 'damage', 'dice': {'count': 6, 'sides': 8}, 'damage_type': kind}])
    elif pattern == 'Burst Pattern':
        _burst(ctx, kind)
    elif pattern == 'Restraint Pattern':
        _restraint(ctx, record.get('pattern_save') or 'CHA')
    elif pattern == 'Shelter Pattern':
        _shelter(ctx, kind)
    elif pattern == 'Restoration Pattern':
        _restoration(ctx)
    elif pattern == 'Passage Pattern':
        _passage(ctx)
    elif pattern == SOVEREIGN:
        _sovereign(ctx, kind)
    record.pop('echoed_pattern', None)
    record.pop('pattern_damage_type', None)
    record.pop('pattern_save', None)
    ctx.engine._append_event('PASSIVE_TRIGGERED', SOURCE, actor_id=ctx.actor.entity_id,
        target_ids=(ctx.target.entity_id,) if ctx.target else (),
        payload={'text': f'{ctx.actor.display_name} uses {pattern}; the Pattern is erased.'})


def _burst(ctx, kind):
    """Burst Pattern: 15-foot-radius sphere, 6d8 on a failed save, half on a success."""
    from dataclasses import replace
    from ..typed_executor import run_effects
    victims = [other for other in ctx.engine.state.actors.values()
               if other.active and other.entity_id != ctx.actor.entity_id
               and ctx.engine.grid.distance_ft(ctx.actor.position, other.position) <= 15]
    for victim in victims:
        run_effects(replace(ctx, target=victim, targets=[victim]),
                    [{'type': 'save', 'ability': str(ctx.typed.get('pattern_save') or 'DEX'),
                      'on_fail': [{'type': 'damage', 'dice': {'count': 6, 'sides': 8}, 'damage_type': kind}],
                      'on_success': [{'type': 'damage', 'dice': {'count': 3, 'sides': 8}, 'damage_type': kind}]}])


def _restraint(ctx, ability):
    from dataclasses import replace
    from ..typed_executor import run_effects
    conditions = ['blinded', 'frightened', 'restrained', 'speed_0']
    run_effects(replace(ctx, targets=[ctx.target]),
                [{'type': 'save', 'ability': str(ability).upper(),
                  'on_fail': [{'type': 'condition', 'condition': 'restrained', 'applies_to': 'target',
                               'expires_on': 'END_OF_TARGET_NEXT_TURN'}],
                  'on_success': [{'type': 'condition', 'condition': 'no_reactions',
                                  'applies_to': 'target',
                                  'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}])


def _shelter(ctx, kind):
    from dataclasses import replace
    from ..typed_executor import run_effects
    from .effect_durations import token
    run_effects(replace(ctx, targets=[ctx.target]),
                [{'type': 'ac_bonus', 'applies_to': 'target', 'value': 3,
                  'expires_on': token('start', ctx.actor.entity_id, int(ctx.actor.turns_started) + 1)}])


def _restoration(ctx):
    from dataclasses import replace
    from ..typed_executor import run_effects
    run_effects(replace(ctx, targets=[ctx.target]),
                [{'type': 'healing', 'applies_to': 'target',
                  'dice': {'count': 5, 'sides': 8}, 'modifier': 'key_mod'}])


def _passage(ctx):
    """Passage Pattern: move one willing creature up to 30 feet without provoking OAs."""
    destination = getattr(ctx.intent, 'destination', None)
    if destination is None or ctx.target is None:
        return
    engine = ctx.engine
    if not engine.grid.placement_legal(destination, footprint=engine._footprint(ctx.target),
                                       occupied_cells=engine._occupied_cells_except(ctx.target.entity_id)):
        return
    if engine.grid.distance_ft(ctx.target.position, destination) > 30:
        return
    start = ctx.target.position
    ctx.target.position = destination
    engine._append_event('MOVEMENT_COMMITTED', SOURCE, actor_id=ctx.target.entity_id,
        payload={'destination': destination.model_dump(mode='json'),
                 'path': [start.model_dump(mode='json'), destination.model_dump(mode='json')],
                 'cost_ft': 0, 'teleport': False, 'forced': True, 'no_opportunity_attacks': True})


def _sovereign(ctx, kind):
    """Sovereign Reflection's printed fallback: reduce to 0 Hit Points and deal 8d10."""
    from dataclasses import replace
    from ..typed_executor import run_effects
    run_effects(replace(ctx, targets=[ctx.target]),
                [{'type': 'damage', 'dice': {'count': 8, 'sides': 10}, 'damage_type': kind}])
