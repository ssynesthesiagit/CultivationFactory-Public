"""Balanced Flow currents and Restorative Palm from the printed Qi Subpath.

Current selection uses the turn-start owner choice, retained on a condition.
Damage and healing bonuses share one actual-turn clock, including reactions.
Yin applies to one selected damaged or failed-save creature; player decisions
ride the ordinary owner choice transport, with damaged recipients only.
"""
from . import hook, effect
from .passive_rows import row_of
from functools import lru_cache
from ..relations import relation, ALLY, ENEMY

PREFIX = 'tianxia.subpath.qi.yin_yang_cultivator.feature.'
FLOW = PREFIX + 'balanced_flow'
CURRENT = 'condition:typed.yin_yang_current'
BLOCK = 'yin_yang_cultivator'
QI = 'resource:core.qi'
HARMONY = 'resource:named.harmony'
UNITY = 'condition:typed.yin_yang_unity'
SCENE = 'condition:typed.yin_yang_scene'
TIERS = {'balanced_flow': 3, 'reversal': 6, 'taiji_field': 10,
         'essence_circulation': 14, 'ultimate_unity': 18}


def scene_state(actor):
    """Source-owned scene state; portable through native encounter snapshots."""
    held = next((c for c in actor.conditions.values() if c.condition_id == SCENE
                 and c.source_actor_id == actor.entity_id), None)
    return dict(held.data) if held is not None else {'last_alignment': '', 'unity_used': 0}


def record_scene_state(engine, actor, source, **changes):
    """Record actual accepted techniques, never infer a scene transition."""
    from .condition_ownership import refresh_owned
    state = {**scene_state(actor), **changes}
    state['label'] = ('Yin–Yang balance: last aligned technique ' +
        (str(state['last_alignment']).title() or 'none') + '; Ultimate Unity ' +
        ('used' if state['unity_used'] else 'unused') + ' this scene. Resets when the scene ends.')
    refresh_owned(engine, actor, SCENE, actor.entity_id, source)
    engine._apply_condition(actor, SCENE, source, actor.entity_id,
        expires_on='UNTIL_REMOVED', data=state)


@hook('journey_scene_end')
def journey_scene_ended(session, previous, current):
    """Consume the published native owner ruling; disappearance is not spending."""
    import json
    for aid, actor in session.state['actors'].items():
        if not any(row.get('block') == BLOCK and row.get('feature_id') == FLOW
                   for row in actor['bundle'].get('typed_passives', ())):
            continue
        lost = actor['resources'].get(HARMONY, 0)
        if HARMONY in actor['resources']:
            actor['resources'][HARMONY] = 0
        conditions = (actor.get('encounter_snapshot') or {}).get('conditions') or {}
        for iid, encoded in list(conditions.items()):
            condition = json.loads(encoded)
            if condition.get('condition_id') == SCENE and condition.get('source_actor_id') == aid:
                del conditions[iid]
        session.emit('YIN_YANG_SCENE_ENDED', aid, source=FLOW, previous_scene=previous,
            next_scene=current, harmony_lost=lost,
            text=f"{actor['name']}: the scene ends. Harmony disappears; the alignment sequence and Ultimate Unity scene use reset. No Qi is restored.")


def owns(engine, actor, kind):
    """Public sealed ownership reader for this source's consumers."""
    from ..cultivation_access import effective_cl
    row = row_of(engine, actor.entity_id, BLOCK, kind)
    if row is None:
        return None
    numbers = row['numbers']
    printed = min(int(numbers['cl']), int(numbers.get('source_cl') or numbers['cl']))
    level = effective_cl(engine, actor, printed)
    if level < TIERS[kind]:
        return None
    if level == numbers['cl'] and numbers.get('source_cl', level) == level:
        return row
    revised = {**numbers, 'cl': level, 'source_cl': level}
    if level != numbers['cl']:
        pb = min(int(numbers['pb']), 2 + max(0, level - 1) // 4)
        revised.update(pb=pb, save_dc=8 + pb + int(numbers['key_mod']), attack_bonus=pb + int(numbers['key_mod']))
    return {**row, 'numbers': revised}


def source_pb(engine, actor):
    row = owns(engine, actor, 'balanced_flow') or {}
    return int((row.get('numbers') or {}).get('pb') or actor.proficiency_bonus or 2)


@hook('resource_base_capacity')
def harmony_runtime_capacity(base, engine, actor, pool):
    if pool != HARMONY:
        return None
    row = row_of(engine, actor.entity_id, BLOCK, 'balanced_flow')
    if row is None:
        return None
    from ..cultivation_access import effective_cl
    printed = min(int(row['numbers']['cl']), int(row['numbers'].get('source_cl') or row['numbers']['cl']))
    level = effective_cl(engine, actor, printed)
    pb = int(row['numbers']['pb']) if level == printed else min(int(row['numbers']['pb']), 2 + max(0, level - 1) // 4)
    return pb + (2 if owns(engine, actor, 'essence_circulation') else 0)


def synchronize_authority(engine, actor):
    if actor is None or row_of(engine, actor.entity_id, BLOCK, 'balanced_flow') is None:
        return
    from .resource_capacity import maximum
    engine._set_resource_maximum(actor, HARMONY,
        maximum(engine, actor, HARMONY, actor.resource_maximums[HARMONY]), FLOW)
    if not owns(engine, actor, 'taiji_field'):
        from ..zones import remove
        for field in fields(engine, owner=actor):
            remove(engine, field, 'CULTIVATION_SUPPRESSED')
    else:
        from ..zones import commit_update
        from ..zone_sources import capture
        row = owns(engine, actor, 'taiji_field')
        for field in fields(engine, owner=actor):
            before = field.trigger_profile.get('source_profile')
            after = capture(before, row['numbers'])
            if after != before:
                field.trigger_profile['source_profile'] = after
                commit_update(engine, field, field.source_definition_id)
    if unity(actor) and not owns(engine, actor, 'ultimate_unity'):
        engine._remove_condition(actor, UNITY, PREFIX + 'ultimate_unity')
    if not owns(engine, actor, 'balanced_flow'):
        engine._remove_condition(actor, CURRENT, FLOW)


@hook('event', nested=True)
def current_authority_changed(engine, event_type, kwargs):
    if event_type in ('CONDITION_APPLIED', 'CONDITION_REMOVED'):
        affected = kwargs.get('target_ids') or ()
        synchronize_authority(engine, engine.state.actors.get(affected[0] if affected else kwargs.get('actor_id')))


@hook('match_start')
@hook('activity_initialize')
def initial_authority(engine):
    for actor in engine.state.actors.values():
        synchronize_authority(engine, actor)


@hook('journey_native_activity')
def outside_combat_activity(session):
    return True if any(any(row.get('feature_id') == FLOW and row.get('block') == BLOCK
        for row in actor['bundle'].get('typed_passives', ())) for actor in session.state['actors'].values()) else None


@hook('turn_boundary_start')
def authority_turn_boundary(engine, actor):
    synchronize_authority(engine, actor)


def feature_context(engine, actor, kind, target, numbers):
    """A source-owned passive delivery, never another catalog actor's action."""
    from ..gate2_runtime_models import ActionDefinition
    from ..typed_executor import Context
    typed = {'source': PREFIX + kind, 'numbers': dict(numbers), 'qi_powered': True,
             'duration': {'kind': 'instant'}, 'effects': [], 'riders': []}
    action = ActionDefinition(source_definition_id=PREFIX + kind,
        display_name=kind.replace('_', ' ').title(), owner_id=actor.entity_id,
        economy='NONE', resolution_kind='TYPED', target_kind='ANY_CREATURE',
        parameters={'typed': typed})
    return Context(engine, actor, action, getattr(engine, '_active_intent', None),
        typed, [target], target, {})


def known_recipients(engine, actor, feet):
    """Source choices use native observations, never hidden live enemy stats.

    Remembered identities remain reachable despite uncertain range. Actual
    range/life state is checked only when the selected effect resolves.
    """
    from ..target_knowledge import actors_for, knowledge
    from ..candidate_knowledge import query
    from . import ai_controlled
    def collect():
        result = []
        for target in actors_for(engine, actor):
            observed = knowledge(engine, actor, engine.state.actors[target.entity_id])
            if target.active and observed is not None and (observed.mode == 'LAST_OBSERVED'
                    or engine._distance_actor_to_actor(actor, target) <= feet):
                result.append(target)
        return result
    if ai_controlled(engine, actor):
        with query(engine):
            return collect()
    return collect()


def unity(actor):
    return any(c.condition_id == UNITY for c in actor.conditions.values())


@lru_cache(maxsize=1)
def source_texts():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).resolve().parents[2] / 'authority/typed_mechanics/rules_text.json').read_text())


def gain_harmony(engine, actor, source, count=1, *, clock=None):
    """Every Harmony gain shares the printed once-per-actual-turn ceiling."""
    clock = clock or _stamp(engine)
    if not _flow(engine, actor) or actor.turn_flags.get('_round_harmony_gain') == clock:
        return
    amount = min(count, actor.resource_maximums.get(HARMONY, 0) - actor.resources.get(HARMONY, 0))
    if amount > 0:
        engine._gain_resource(actor, HARMONY, amount, source)
        actor.turn_flags['_round_harmony_gain'] = clock


@hook('compile_resources')
def harmony_capacity(info):
    if FLOW not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    from ..activation_settlement import path_numbers
    numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    maximum = int(numbers['pb']) + (2 if PREFIX + 'essence_circulation' in info['owned_ids'] else 0)
    return [ResourceDefinition(resource_id=HARMONY, initial=0, maximum=maximum)]


@hook('compile_passives')
def source_numbers(rows, info):
    if not any(r.get('block') == BLOCK for r in rows):
        return None
    from ..activation_settlement import path_numbers
    numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    return [{**r, 'numbers': numbers} if r.get('block') == BLOCK else r for r in rows]


@lru_cache(maxsize=2048)
def alignment_options(source):
    """Eligibility from the exact committed Source Rule, not an effect packet."""
    import re
    text = source_texts().get(source, '').lower()
    if not text:
        return ()
    terms = {
        'yin': ('yin', 'cold', 'dark', 'moon', 'concealment', 'restraint', 'reduction', 'absorption',
                'stillness', 'storage', 'recovery', 'shadow', 'inward movement'),
        'yang': ('yang', 'fire', 'radiance', 'sun', 'revelation', 'forced outward movement', 'expansion',
                 'speed', 'release', 'direct damage', 'vitality', 'outward movement')}
    from ..typed_numbers import authority_mechanics
    record = authority_mechanics().get(source) or {}
    tags = {str(tag).lower() for tag in record.get('tags') or []}
    # Canonical Sphere membership is an explicit source tag; neither the
    # action's display name nor the damage it happens to deliver supplies it.
    sphere = str(record.get('sphere_id') or '')
    if sphere.startswith('tianxia.sphere.'):
        tags.add(sphere.removeprefix('tianxia.sphere.'))
    return ('yin',) if source == FLOW else tuple(mode for mode, words in terms.items()
        if tags.intersection(words) or any(re.search(r'\b' + re.escape(word) + r'\b', text) for word in words))


@hook('compile_action')
def alignment_source(action, info):
    """Seal literal Source Rule alignment, never infer it from delivered damage."""
    from copy import deepcopy
    if FLOW not in info['owned_ids']:
        return None
    typed = (action.parameters or {}).get('typed') or {}
    source = str(typed.get('option_of') or typed.get('source') or '')
    options = list(alignment_options(source))
    parameters = deepcopy(action.parameters)
    parameters['typed']['polarity_alignments'] = options
    if source.startswith(PREFIX):
        from ..activation_settlement import path_numbers
        parameters['typed']['numbers'] = path_numbers(info, 'tianxia.path.qi_cultivation')
    if source == PREFIX + 'taiji_field':
        # This provider owns the single field's creation and mode selection.
        # The compiler's prose-derived preliminary zone would consume creation
        # first, then be removed by the source's replace-existing-field step.
        parameters['typed'].pop('zone_spec', None)
        from ..zone_sources import compile_profile
        parameters['typed']['zone_source_profile'] = compile_profile(parameters['typed'],
            info['mechanics'][source], parameters['typed']['duration'])
    return action.model_copy(update={'parameters': parameters})


@hook('compile_actions')
def preparation_modes(info):
    """Native setup choices declare ambiguous polarity before a peaceful cast."""
    if FLOW not in info['owned_ids']:
        return None
    from copy import deepcopy
    result = []
    for action in info['actions']:
        typed = action.parameters.get('typed') or {}
        source = str(typed.get('option_of') or typed.get('source') or '')
        duration = typed.get('duration') or {}
        long = duration.get('kind') in ('hours', 'days', 'until_long_rest', 'until_short_rest', 'until_dispelled', 'permanent') or (
            duration.get('kind') == 'minutes' and int(duration.get('amount') or 0) >= 10)
        if not long or len(alignment_options(source)) != 2:
            continue
        for mode in ('yin', 'yang'):
            parameters = deepcopy(action.parameters)
            parameters['yin_yang_preparation'] = True
            parameters['typed']['declared_polarity'] = mode
            result.append(action.model_copy(update={
                'source_definition_id': action.source_definition_id + '.prepare_' + mode,
                'display_name': action.display_name + ' (prepare ' + mode.title() + '-aligned)', 'parameters': parameters}))
    return result or None


@hook('prefight_allowed')
def preparation_admission(action):
    typed = action.parameters.get('typed') or {}
    if len(typed.get('polarity_alignments') or []) > 1 and not typed.get('declared_polarity'):
        return False
    return None


@hook('prefight_prepare')
def prepare_peaceful_source(action, engine, actor, option):
    if not _flow(engine, actor):
        return None
    typed = action.parameters.get('typed') or {}
    options = typed.get('polarity_alignments')
    if options is None:
        options = list(alignment_options(str(typed.get('option_of') or typed.get('source') or '')))
    if len(options) > 1 and (action.parameters.get('typed') or {}).get('declared_polarity') not in options:
        raise ValueError('Declare Yin or Yang in the preparation choice before casting')
    return declare_alignment(action, engine, actor, None, None)


@hook('activation_prepare')
def declare_alignment(action, engine, actor, candidate, intent):
    from copy import deepcopy
    if not _flow(engine, actor):
        return None
    typed = action.parameters.get('typed') or {}
    options = typed.get('polarity_alignments')
    if options is None:
        options = list(alignment_options(str(typed.get('option_of') or typed.get('source') or '')))
    if not options:
        return None
    from .rider_choices import pick
    declared = (action.parameters.get('typed') or {}).get('declared_polarity')
    selected = [declared] if declared in options else options if len(options) == 1 else pick(engine, actor, 'yin_yang_alignment',
        'Yin and Yang Alignment', options, subject=actor, intent=intent, optional=False,
        preferred=options[:1],
        labels={'yin': 'Declare this technique Yin-aligned', 'yang': 'Declare this technique Yang-aligned'},
        prompt=f'{action.display_name}: declare Yin or Yang before resolving the technique.')
    parameters = deepcopy(action.parameters)
    parameters['typed']['declared_polarity'] = selected[0]
    source = str(typed.get('source') or '')
    if source.startswith(PREFIX):
        kind = source.removeprefix(PREFIX)
        row = owns(engine, actor, kind) if kind in TIERS else None
        if row is not None:
            parameters['typed']['numbers'] = dict(row['numbers'])
    # Unified field casting never creates a concentration state.
    if unity(actor) and (parameters['typed'].get('source') == PREFIX + 'taiji_field'):
        parameters['typed']['duration']['concentration'] = False
    if source == PREFIX + 'taiji_field':
        from .qi_path import armament_condition
        manifestation = armament_condition(actor)
        if manifestation is not None and manifestation.source_actor_id == actor.entity_id:
            chosen = pick(engine, actor, 'taiji_focus', 'Taiji Field', ['none', 'focus', 'anchor'], subject=actor,
                optional=False, preferred=['none'], intent=intent, labels={
                    'none': 'Create Taiji Field without a Domain Armament focus or Anchor',
                    'focus': 'Use the manifested Domain Armament as a visible focus only; its loss does not end Taiji Field',
                    'anchor': 'Name the manifested Domain Armament as Taiji Field’s Anchor; losing or suppressing that manifestation ends the field'},
                prompt='Taiji Field: use your existing Domain Armament as a visible focus, name it as the field’s Anchor, or use neither?')
            parameters['typed']['taiji_focus'] = chosen[0]
            if chosen == ['anchor']:
                from ..condition_identity import seal
                parameters['typed']['condition_anchor'] = seal(engine, actor, manifestation, action.source_definition_id)
    return action.model_copy(update={'parameters': parameters})


@hook('activation_settlement')
def settle_polarity(ctx, receipt):
    if not _flow(ctx.engine, ctx.actor):
        return
    # Setup has its own validated payment/effect phase. Foreground/reaction
    # sequences use the shared accepted-activation completion contract below.
    if receipt.get('phase') == 'prefight':
        settle_sequence(ctx, clock='prefight:' + ctx.engine.state.match_id + ':' + ctx.actor.entity_id)
    if unity(ctx.actor) and receipt['qi_powered'] and receipt['damaged_ids']:
        unity_healing(ctx)


@hook('activation_accounting')
def polarity_accounting(engine):
    return True if any(_flow(engine, actor) for actor in engine.state.actors.values()) else None


@hook('technique_resolution_enabled')
def polarity_completion(ctx):
    return True if _flow(ctx.engine, ctx.actor) and ctx.typed.get('declared_polarity') in ('yin', 'yang') else None


@hook('technique_resolved')
def polarity_resolved(ctx, receipt):
    if receipt.actor_id == ctx.actor.entity_id and _flow(ctx.engine, ctx.actor):
        settle_sequence(ctx)


def settle_sequence(ctx, *, clock=None):
    if (ctx.action.parameters.get('typed') or {}).get('yin_yang_transition') == 1:
        gain_harmony(ctx.engine, ctx.actor, ctx.source, clock=clock)


@hook('technique_accepted')
def sequence_accepted(engine, actor, action):
    typed = action.parameters.get('typed') or {}
    polarity = typed.get('declared_polarity')
    if not _flow(engine, actor) or polarity not in ('yin', 'yang'):
        return
    if typed.get('yin_yang_accepted') == 1:
        return  # split native effect phases still belong to one activation
    # activation_prepare supplied an activation-local copy. Record activation
    # order now; a nested technique must see this declaration even though this
    # activation's Harmony award waits for its own successful completion.
    previous = scene_state(actor)['last_alignment']
    typed['yin_yang_accepted'] = 1
    typed['yin_yang_transition'] = int(bool(previous) and previous != polarity)
    record_scene_state(engine, actor, action.source_definition_id, last_alignment=polarity)


@hook('compile_actions')
def advanced_actions(info):
    if FLOW not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    from ..activation_settlement import path_numbers
    numbers = path_numbers(info, 'tianxia.path.qi_cultivation')
    actions = []
    specs = [('taiji_field', 'Taiji Field', 'ACTION', 'CELL', 60, 5, 'yin_yang_field'),
             ('ultimate_unity', 'Ultimate Unity', 'BONUS_ACTION', 'SELF', None, 8, 'yin_yang_unity')]
    for kind, name, economy, target, distance, cost, effect_type in specs:
        if PREFIX + kind not in info['owned_ids']:
            continue
        actions.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.yin_yang.{kind}",
            display_name=name, owner_id=info['actor_id'], economy=economy, resolution_kind='TYPED',
            target_kind=target, range_ft=distance, costs=((QI, cost),),
            parameters={'typed': {'source': PREFIX + kind, 'numbers': numbers,
                'min_cl': TIERS[kind],
                'duration': {'kind': 'minutes', 'amount': 1, 'concentration': kind == 'taiji_field'},
                'effects': [{'type': effect_type}], 'riders': []}, 'expected_damage': 0,
                'description': (f'{name}: spend {cost} Qi; lasts 1 minute. ' +
                    (f'As an Action, place a 20-foot-radius, 20-foot-high field within 60 feet; requires Concentration. '
                     f'Yin: allies gain +1 AC, Advantage on saves against Frightened, Charmed and forced movement, and '
                     f'reduce their first damage packet each round by {numbers["pb"]}; enemies treat it as difficult terrain. '
                     f'Yang: each hostile creature’s first save each turn against your or an ally’s cultivation feature takes -1d4; '
                     f'each ally’s first damage or healing roll each turn gains {numbers["pb"]}. '
                     'Choose the Rotation; maintain or switch at your turn start. Switching grants 1 Harmony, subject to its turn limit and maximum. '
                     'Fields of the same Rotation do not stack.'
                     if kind == 'taiji_field' else
                     'As a Bonus Action, once per scene: both Currents and both Taiji Field Rotations function. '
                     'Fly 40 feet and Hover; resist all damage except Force, Psychic and Void. '
                     'Gain 1 Harmony at each turn start, subject to its maximum and turn limit. Taiji Field needs no Concentration. '
                     'Restorative Palm becomes a Bonus Action, heals 3d8 plus your Qi ability modifier, and costs 0 Qi once per turn. '
                     'Reversal costs 0 Qi once per round and grants two different benefits without Harmony. '
                     'Once per turn after a Qi technique deals damage, choose an ally within 30 feet to regain 1d8 plus your Qi ability modifier HP; '
                     'each creature can receive this healing once per turn.'))}))
    if PREFIX + 'ultimate_unity' in info['owned_ids']:
        base = flow_actions(info)[0]
        parameters = {**base.parameters, 'unity_palm': True,
            'description': 'While Ultimate Unity is active, touch one creature as a Bonus Action. '
                'It regains 3d8 plus your Qi ability modifier HP. Once per turn this costs 0 Qi; otherwise it costs 2 Qi. '
                'Both Currents apply: it gains your Proficiency Bonus in Temporary HP and may move 5 feet without provoking Opportunity Attacks.',
            'typed': {**base.parameters['typed'],
            'numbers': numbers, 'effects': [{'type': 'healing', 'applies_to': 'target',
                'dice': {'count': 3, 'sides': 8}, 'formula': 'key_ability_modifier'}, {'type': 'yin_yang_palm'}]}}
        actions.append(base.model_copy(update={'source_definition_id': base.source_definition_id + '.unity',
            'display_name': 'Restorative Palm (Ultimate Unity)', 'economy': type(base.economy)('BONUS_ACTION'), 'parameters': parameters}))
    return actions


@hook('candidate_allowed')
def unity_candidates(engine, actor, candidate, action):
    if action is None:
        return None
    if action.parameters.get('yin_yang_preparation'):
        return False  # setup-only declared copies; the original combat action stays reachable
    typed = action.parameters.get('typed') or {}
    source = str(typed.get('source') or '')
    if source.startswith(PREFIX):
        kind = source.removeprefix(PREFIX)
        if kind in TIERS and not owns(engine, actor, kind):
            return False
    if typed.get('source') == PREFIX + 'ultimate_unity':
        return not scene_state(actor)['unity_used']
    if typed.get('source') == FLOW:
        return bool(action.parameters.get('unity_palm')) == unity(actor)
    return None


@hook('technique_cost_discount')
def unity_palm_discount(engine, actor, source_id, costs):
    action = engine.action_catalog.get(source_id)
    if (action and action.parameters.get('unity_palm') and unity(actor)
            and actor.turn_flags.get('_round_unity_palm') != _stamp(engine)):
        return {QI: costs.get(QI, 0)}
    return None


@hook('technique_accepted')
def spend_unity_palm(engine, actor, action):
    if (action.parameters.get('typed') or {}).get('source') == PREFIX + 'ultimate_unity' and owns(engine, actor, 'ultimate_unity'):
        record_scene_state(engine, actor, action.source_definition_id, unity_used=1)
    if action.parameters.get('unity_palm') and unity(actor):
        actor.turn_flags['_round_unity_palm'] = _stamp(engine)


@effect('yin_yang_unity')
def activate_unity(ctx, eff):
    if not owns(ctx.engine, ctx.actor, 'ultimate_unity'):
        return
    from ..typed_executor import effect_expiry
    previous = [condition for condition in ctx.actor.conditions.values()
                if condition.condition_id == UNITY and condition.source_actor_id == ctx.actor.entity_id]
    ctx.engine._apply_condition(ctx.actor, UNITY, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {'duration': 'one_minute'}, ctx.actor, condition=True),
        data={'label': 'Ultimate Unity: both Currents and Rotations; Fly 40 feet and Hover; damage resistance except Force, Psychic and Void',
              'fly_speed_ft': 40, 'flight_hover': 1})
    created = any(condition.condition_id == UNITY and condition.source_actor_id == ctx.actor.entity_id
                  and all(condition is not old for old in previous) for condition in ctx.actor.conditions.values())
    if created:
        for old in previous:
            ctx.engine._remove_condition_instance(ctx.actor, old.instance_id, ctx.source, expected=old)
    if not unity(ctx.actor):
        return  # a denied condition grants none of the concentration exception
    # Use the existing exact-copy concentration handover, including held copies.
    from .. import concentration
    for field in fields(ctx.engine, owner=ctx.actor):
        set_field_concentration(ctx.engine, field, False)
        copies = ([ctx.actor.concentration] if ctx.actor.concentration is not None else []) + [state for _, state in concentration.held(ctx.actor)]
        for held in copies:
            if held.zone_id == field.zone_id:
                concentration.end_copy(ctx.engine, ctx.actor, held.started_sequence, 'ULTIMATE_UNITY', retain_zone=True)


@hook('damage_defenses')
def unity_resistance(engine, actor, kind, typed, source_actor_id):
    if unity(actor) and owns(engine, actor, 'ultimate_unity') and kind.upper() not in ('FORCE', 'PSYCHIC', 'VOID'):
        return [{'kind': 'resistance', 'damage_types': [kind.upper()]}]
    return None


def unity_healing(ctx):
    if not owns(ctx.engine, ctx.actor, 'ultimate_unity'):
        return
    from .rider_choices import pick
    from ..typed_executor import run_effects
    if ctx.actor.turn_flags.get('_round_unity_healing') == _stamp(ctx.engine):
        return
    stamp = _stamp(ctx.engine)
    targets = [a for a in known_recipients(ctx.engine, ctx.actor, 30) if a.entity_id != ctx.actor.entity_id
        and relation(ctx.engine, a, ctx.actor) == ALLY
        and a.turn_flags.get('_round_unity_received') != stamp]
    if not targets:
        return
    selected = pick(ctx.engine, ctx.actor, 'unity_healing', 'Ultimate Unity', [a.entity_id for a in targets],
        subject=targets[0], labels={a.entity_id: f'Heal {a.display_name}: 1d8 plus your Qi key ability modifier HP' for a in targets},
        prompt=f'Ultimate Unity: after {ctx.action.display_name} dealt damage, choose an ally within 30 feet to heal.')
    if selected:
        target = ctx.engine.state.actors[selected[0]]
        # Revalidate before spending the source's once-per-turn use. The
        # offered list excludes spent recipients, but movement or another
        # Unity owner may have changed eligibility while the choice was open.
        if (not target.active or ctx.engine._distance_actor_to_actor(ctx.actor, target) > 30
                or target.turn_flags.get('_round_unity_received') == stamp):
            return
        ctx.actor.turn_flags['_round_unity_healing'] = stamp
        target.turn_flags['_round_unity_received'] = stamp
        row = owns(ctx.engine, ctx.actor, 'ultimate_unity')
        run_effects(feature_context(ctx.engine, ctx.actor, 'ultimate_unity', target, row['numbers']),
            [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 1, 'sides': 8}, 'formula': 'key_ability_modifier'}])


def fields(engine, owner=None):
    # Ownership/remote Rotation control includes the source's continuing field
    # on another mapped location; spatial benefits still require that map.
    return [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('yin_yang_field') and anchor_live(engine, z)
            and (owner is None or z.owner_id == owner.entity_id)]


def anchor_live(engine, field):
    reference = field.trigger_profile.get('condition_anchor')
    if reference is None:
        return True
    from ..condition_identity import live
    return live(engine, reference)


@hook('intent_resolved')
def settle_named_anchor(engine, actor, candidate, intent, first_event):
    from ..zones import typed_zones, remove
    # The Anchor promise is not limited to this map: a Taiji Field carried into
    # another encounter keeps its Concentration and must end when its named
    # manifestation is lost or suppressed there (only spatial benefits stay
    # map-filtered, through fields()/field_owners()).
    for field in list(typed_zones(engine, include_remote=True)):
        if field.active and field.trigger_profile.get('yin_yang_field') and not anchor_live(engine, field):
            remove(engine, field, 'NAMED_ANCHOR_ENDED')


@hook('turn_start_settled')
def settle_start_anchors(engine, actor):
    settle_named_anchor(engine, actor, None, None, engine.state.event_sequence)


def set_field_concentration(engine, field, required):
    from ..zones import commit_update
    field.concentration_link = required
    profile = field.trigger_profile.get('source_profile')
    if profile is not None:
        field.trigger_profile['source_profile'] = {**profile, 'concentration': int(required)}
    commit_update(engine, field, field.source_definition_id)


@hook('event', nested=True)
def ended_field_concentration(engine, event_type, kwargs):
    if event_type != 'ZONE_REMOVED':
        return
    field = engine.state.zones.get((kwargs.get('payload') or {}).get('zone_id'))
    if field is None or not field.trigger_profile.get('yin_yang_field'):
        return
    from .. import concentration
    actor = engine.state.actors[field.owner_id]
    copies = ([actor.concentration] if actor.concentration is not None else []) + [state for _, state in concentration.held(actor)]
    for held in copies:
        if held.zone_id == field.zone_id:
            concentration.end_copy(engine, actor, held.started_sequence,
                str((kwargs.get('payload') or {}).get('reason') or 'FIELD_ENDED'))


def field_rotation(engine, field):
    return str(field.trigger_profile.get('taiji_rotation')
        or engine.state.actors[field.owner_id].turn_flags.get('_round_taiji_rotation') or 'yin')


def field_label(field):
    return f'Taiji Field at square ({field.center.x}, {field.center.y})'


def rotation(engine, owner, mode, field=None):
    from .rider_choices import pick
    key = 'taiji_rotation' + (':' + field.zone_id if field is not None and len(fields(engine, owner=owner)) > 1 else '')
    chosen = pick(engine, owner, key, 'Taiji Field', ['yin', 'yang'], subject=owner,
        optional=False, preferred=[mode], labels={
            'yin': f'Yin Rotation: allies gain +1 AC, Advantage against Frightened/Charmed/forced movement, and '
                   f'{source_pb(engine, owner)} reduction to their first damage packet each round; hostile creatures face difficult terrain',
            'yang': f'Yang Rotation: each hostile creature’s first cultivation save each turn takes -1d4; '
                    f'each ally’s first damage or healing roll each turn gains {source_pb(engine, owner)}'},
        prompt=(field_label(field) if field is not None else 'Taiji Field') +
            f': {owner.display_name}, maintain the Rotation or switch it after the old Rotation’s start-of-turn effects finish (no action or Qi cost).')
    return chosen[0]


def set_rotation(engine, owner, mode, *, grant=True, field=None):
    previous = field_rotation(engine, field) if field is not None else owner.turn_flags.get('_round_taiji_rotation')
    owner.turn_flags['_round_taiji_rotation'] = mode
    if field is not None and previous != mode:
        from ..zones import commit_update
        field.trigger_profile['taiji_rotation'] = mode
        commit_update(engine, field, field.source_definition_id)
    if grant and previous and previous != mode:
        gain_harmony(engine, owner, PREFIX + 'taiji_field')


@effect('yin_yang_field')
def create_field(ctx, eff):
    if not owns(ctx.engine, ctx.actor, 'taiji_field'):
        return
    # Area effects share one Context/cache while visiting their recipients.
    # Only the first recipient visit creates this casting's one field. Other
    # castings retain their own center, lifetime, mode and Concentration copy.
    if ctx.damage_cache.get(('yin_yang_field_resolved', ctx.source)):
        return
    ctx.damage_cache[('yin_yang_field_resolved', ctx.source)] = True
    from .. import zones
    selected = rotation(ctx.engine, ctx.actor, 'yin')
    set_rotation(ctx.engine, ctx.actor, selected, grant=False)
    ctx.damage_cache[('yin_yang_field_rotation', ctx.source)] = selected
    profile = ctx.typed.get('zone_source_profile')
    if profile is not None:
        profile = {**profile, 'concentration': int(not unity(ctx.actor))}
    from ..typed_executor import duration_expiry
    zone = zones.create(ctx, {'name': 'Taiji Field', 'shape': 'cylinder', 'size_ft': 20, 'height_ft': 20,
        'persistent_identity': 1,
        'duration_deadline': duration_expiry(ctx.engine, ctx.typed['duration'], source=ctx.actor),
        'duration': {**ctx.typed['duration'], 'concentration': not unity(ctx.actor)},
        'source_profile': profile,
        'difficult': {'who': 'hostile'}})


@hook('zone_created')
def seal_field(ctx, zone):
    if ctx.typed.get('source') == PREFIX + 'taiji_field' and owns(ctx.engine, ctx.actor, 'taiji_field'):
        zone.trigger_profile['yin_yang_field'] = 1
        zone.trigger_profile['taiji_rotation'] = ctx.damage_cache[('yin_yang_field_rotation', ctx.source)]
        from ..zones import current_map_identity
        zone.trigger_profile['map_identity'] = current_map_identity(ctx.engine)
        zone.trigger_profile['taiji_focus'] = str(ctx.typed.get('taiji_focus') or 'none')
        if ctx.typed.get('condition_anchor') is not None:
            zone.trigger_profile['condition_anchor'] = dict(ctx.typed['condition_anchor'])


def field_owners(engine, subject, mode, *, allied):
    from ..zones import actor_inside_zone
    result = []
    for zone in fields(engine):
        owner = engine.state.actors[zone.owner_id]
        if not owns(engine, owner, 'taiji_field'):
            continue
        if relation(engine, owner, subject) != (ALLY if allied else ENEMY) or not actor_inside_zone(engine, subject, zone):
            continue
        if unity(owner) or field_rotation(engine, zone) == mode:
            result.append(owner)
    return result


@hook('difficult_zone_exempt')
def yang_terrain(engine, actor, zone):
    if zone.trigger_profile.get('yin_yang_field'):
        if not anchor_live(engine, zone):
            return True
        owner = engine.state.actors[zone.owner_id]
        return True if not unity(owner) and field_rotation(engine, zone) != 'yin' else None
    return None


@hook('ac')
def field_ac(engine, target):
    return 1 if field_owners(engine, target, 'yin', allied=True) else None


@hook('save')
def field_saves(ctx, target, ability, named):
    if field_owners(ctx.engine, target, 'yin', allied=True) and {'frightened', 'charmed', 'forced_movement'} & set(named):
        return {'modes': ['ADVANTAGE']}
    return None


@hook('save_mode')
def field_native_save_mode(engine, target, ability, dc, source_id, roll_context):
    named = {str(n).removeprefix('condition:typed.') for n in (roll_context or {}).get('named') or []}
    if {'frightened', 'charmed', 'forced_movement'} & named and field_owners(engine, target, 'yin', allied=True):
        return 'ADVANTAGE'
    return None


@hook('d20_bonus')
def field_save_penalty(engine, roll, intent):
    target = engine.state.actors.get(roll.actor_id)
    if target is None or target.turn_flags.get('_round_taiji_save') == _stamp(engine):
        return None
    owners = field_owners(engine, target, 'yang', allied=False)
    if not owners:
        return None
    frame = engine.d20_context(roll) or {}
    caster = engine.state.actors.get(frame.get('source_actor_id'))
    if frame.get('kind') != 'save' or caster is None:
        return None
    owners = [owner for owner in owners if relation(engine, owner, caster) == ALLY]
    if not owners:
        return None
    frame_source = str(frame.get('source_id') or '')
    action = engine.action_catalog.get(frame_source)
    if action is None:
        # Typed actions may roll under their canonical option/source id while
        # their catalog key is an activation wrapper id (notably Sphere talents).
        action = next((a for a in engine.action_catalog.values()
            if a.owner_id == caster.entity_id and frame_source in {
                str(a.source_definition_id or ''),
                str((a.parameters.get('typed') or {}).get('source') or ''),
                str((a.parameters.get('typed') or {}).get('option_of') or ''),
            }), None)
    typed = (action.parameters.get('typed') or {}) if action else {}
    source = str(typed.get('option_of') or typed.get('source') or frame_source)
    source_kind = (typed.get('activation_profile') or {}).get('source_kind')
    # Compiled talents may retain their canonical Sphere only in the typed
    # authority record. Never infer qualification from names or damage types.
    from ..typed_numbers import authority_mechanics
    source_record = authority_mechanics().get(source) or {}
    source_sphere = str(source_record.get('sphere_id') or '')
    if not (typed.get('sphere') or source_sphere.startswith('tianxia.sphere.')
            or source_kind in ('Path', 'Subpath', 'Sphere', 'Tradition', 'Recorded', 'Forged',
                'Immortal', 'Foundation', 'Method', 'Insight', 'Formation')
            or source.startswith(('tianxia.path.', 'tianxia.subpath.', 'tianxia.tradition.',
                'tianxia.sphere.', 'tianxia.recorded_art.', 'tianxia.forged_technique.',
                'tianxia.immortal_art.', 'tianxia.method.', 'foundation.', 'insight.'))):
        return None
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import _roll
    owner = owners[0]
    row = owns(engine, owner, 'taiji_field')
    if row is None:
        return None
    ctx = feature_context(engine, owner, 'taiji_field', target, row['numbers'])
    target.turn_flags['_round_taiji_save'] = _stamp(engine)
    return {'source_id': PREFIX + 'taiji_field', 'user_id': owner.entity_id,
            'bonus': -_roll(ctx, DiceSpec(count=1, sides=4), 'TAIJI_FIELD_SAVE')}


@hook('final_damage')
def field_reduction(engine, target, amount, kind, source_id, source_actor_id, intent):
    owners = field_owners(engine, target, 'yin', allied=True)
    if amount > 0 and owners and target.turn_flags.get('_round_taiji_reduction') != engine.state.round_number:
        target.turn_flags['_round_taiji_reduction'] = engine.state.round_number
        return {'reduction': min(amount, max(source_pb(engine, o) for o in owners))}
    return None


def field_roll(ctx, targets):
    for subject in targets:
        owners = field_owners(ctx.engine, subject, 'yang', allied=True)
        if owners and subject.turn_flags.get('_round_taiji_roll') != _stamp(ctx.engine):
            subject.turn_flags['_round_taiji_roll'] = _stamp(ctx.engine)
            return max(source_pb(ctx.engine, o) for o in owners)
    return None


@hook('damage_roll_bonus')
def field_damage(ctx, eff, kinds):
    # The ally dealing damage is in the field, not necessarily its recipient.
    return field_roll(ctx, [ctx.actor]) if eff is not None else None


@hook('damage_packet_selection')
def field_attack(ctx, target, kinds):
    spec = ctx.attack_defense_spec
    dice = spec.get('damage') if spec else None
    if dice is not None and dice.count > 0 and spec.get('fixed_damage') is None:
        bonus = field_roll(ctx, [ctx.actor])
        if bonus:
            spec['damage'] = dice.model_copy(update={'modifier': dice.modifier + bonus})


@hook('healing_roll_bonus')
def field_healing(ctx, eff):
    from ..typed_amounts import effect_dice
    from ..gate2_runtime_models import DiceSpec
    dice = ctx.dice(effect_dice(eff, ctx.numbers))
    return field_roll(ctx, [ctx.actor]) if isinstance(dice, DiceSpec) and dice.count > 0 else None


@hook('turn_start_choice')
def field_rotation_choice(engine, actor):
    if unity(actor):
        gain_harmony(engine, actor, PREFIX + 'ultimate_unity')


@hook('turn_start_settled')
def settled_field_rotation_choice(engine, actor):
    for field in fields(engine, owner=actor):
        mode = field_rotation(engine, field)
        set_rotation(engine, actor, rotation(engine, actor, mode, field), field=field)


@hook('effect_ending_choice')
def unity_ending_choice(engine, actor, row):
    if getattr(row, 'condition_id', None) != UNITY or row.source_actor_id != actor.entity_id:
        return
    if any(c.condition_id == UNITY and c.instance_id != row.instance_id for c in actor.conditions.values()):
        return  # replacement Unity still supplies the same live exception
    restore_field_concentration(engine, actor)


def restore_field_concentration(engine, actor):
    # Once the exception expires the field again needs its one concentration
    # state. Native concentration admission preserves every independently held
    # source and applies the ordinary capacity rule.
    for field in fields(engine, owner=actor):
        from .effect_durations import due
        if due(engine, field.trigger_profile.get('duration_deadline')):
            from ..zones import remove
            remove(engine, field, 'DURATION_EXPIRED')
            continue
        if field.concentration_link:
            continue
        from ..zones import remove
        from .needle import incapacitated
        from .rider_choices import pick
        if not actor.active or actor.life_state in ('DYING', 'STABLE') or incapacitated(actor):
            remove(engine, field, 'CONCENTRATION_UNAVAILABLE')
            continue
        key = 'taiji_concentration_restore' + (':' + field.zone_id if len(fields(engine, owner=actor)) > 1 else '')
        selected = pick(engine, actor, key, 'Taiji Field', ['maintain', 'end'],
            subject=actor, optional=False, preferred=['maintain'],
            labels={'maintain': 'Maintain Taiji Field with Concentration; your normal concentration limit applies',
                    'end': 'End Taiji Field and keep your other concentration effects'},
            prompt=f'{field_label(field)}: Ultimate Unity ends for {actor.display_name}. Maintain this field with Concentration, or end it? '
                   'If your concentration slots are full, maintaining it replaces your oldest concentration under the normal rule.')
        if selected == ['end']:
            remove(engine, field, 'OWNER_ENDED')
            continue
        engine._start_concentration(actor, field.source_definition_id)
        actor.concentration.zone_id = field.zone_id
        set_field_concentration(engine, field, True)


def circulation(engine, actor):
    from .rider_choices import pick, step
    from ..typed_executor import run_effects
    row = owns(engine, actor, 'essence_circulation')
    if not row or actor.turn_flags.get('_round_essence_circulation') == engine.state.round_number:
        return
    targets = known_recipients(engine, actor, 60)
    options, labels = ['qi'], {'qi': 'Regain 1 Qi, up to your maximum'}
    for target in targets:
        for mode, description in [('heal', 'regains 2d8 plus your Qi key ability modifier HP'),
                                  ('temp', 'gains Temporary HP equal to twice your Proficiency Bonus'),
                                  ('move', 'may, if willing, move up to 15 feet without provoking Opportunity Attacks')]:
            key = mode + ':' + target.entity_id
            options.append(key)
            labels[key] = target.display_name + ' ' + description
    rotations = {('rotate' if len(fields(engine, owner=actor)) == 1 else 'rotate:' + field.zone_id): field
                 for field in fields(engine, owner=actor)}
    for key, field in rotations.items():
        options.append(key); labels[key] = 'Change ' + field_label(field) + '’s Rotation immediately'
    attempt = 0
    while True:
        key = 'essence_circulation' + (f'_retry_{attempt}' if attempt else '')
        selected = pick(engine, actor, key, 'Essence Circulation', options, labels=labels,
            subject=actor, optional=False, preferred=['qi'],
            prompt='Essence Circulation: immediately after spending Harmony, choose one benefit within 60 feet.')
        chosen = selected[0]
        if not chosen.startswith('move:'):
            break
        target = engine.state.actors[chosen.split(':', 1)[1]]
        if not target.active or engine._distance_actor_to_actor(actor, target) > 60:
            break
        from .willing_targets import asks_consent
        if target.entity_id == actor.entity_id or asks_consent(engine, getattr(engine, '_active_intent', None), target,
                'Essence Circulation', f'Essence Circulation: {target.display_name}, accept movement up to 15 feet without provoking Opportunity Attacks after Harmony is spent?',
                prefer_accept=relation(engine, target, actor) == ALLY, asker=actor):
            break
        # An explicit refusal makes this movement recipient ineligible; every
        # other benefit/recipient stays reachable and no Circulation use is spent.
        options.remove(chosen)
        attempt += 1
    actor.turn_flags['_round_essence_circulation'] = engine.state.round_number
    chosen = selected[0]
    if chosen == 'qi':
        engine._gain_resource(actor, QI, min(1, actor.resource_maximums.get(QI, 0) - actor.resources.get(QI, 0)), PREFIX + 'essence_circulation')
    elif chosen in rotations:
        field = rotations[chosen]
        old = field_rotation(engine, field)
        set_rotation(engine, actor, 'yang' if old == 'yin' else 'yin', field=field)
    else:
        mode, target_id = chosen.split(':', 1)
        target = engine.state.actors[target_id]
        if not target.active or engine._distance_actor_to_actor(actor, target) > 60:
            return
        if mode == 'move':
            step(engine, target, 'circulation_move', 'Essence Circulation', target, 15,
                PREFIX + 'essence_circulation', ignored_oa=list(engine.state.actors),
                all_destinations=True,
                trigger='Harmony is spent; you accepted Essence Circulation’s movement')
        else:
            ctx = feature_context(engine, actor, 'essence_circulation', target, row['numbers'])
            run_effects(ctx, [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                'formula': 'key_ability_modifier'}] if mode == 'heal' else
                [{'type': 'temp_hp', 'applies_to': 'target', 'flat': 2 * int(row['numbers']['pb'])}])


@hook('event', nested=True)
def harmony_spent(engine, event_type, kwargs):
    if event_type == 'RESOURCE_SPENT' and (kwargs.get('payload') or {}).get('resource_id') == HARMONY \
            and int(kwargs['payload'].get('amount') or 0) > 0:
        actor = engine.state.actors.get(kwargs.get('actor_id'))
        if actor:
            from ..paid_relocation import current_activation
            receipt = current_activation(engine)
            if (receipt is None or receipt.actor_id != actor.entity_id
                    or not any(pool == HARMONY and amount > 0 for pool, amount in receipt.payments)):
                return
            try:
                circulation(engine, actor)
            except Exception as exc:
                from . import CheckpointError
                raise CheckpointError('Essence Circulation did not complete after Harmony spending') from exc


def reversal_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        row = owns(engine, actor, 'reversal')
        if row and actor.active:
            yield Holder(actor, PREFIX + 'reversal', row, PREFIX + 'reversal', row['numbers'])


def reversal_guard(engine, holder, rc):
    if rc.kind != 'save' or rc.roll.reason == 'SAVE:death' or str(rc.ability or '').upper() == 'DEATH':
        return False
    # Earlier uses are committed against the exact d20, not an action name.
    # Training and breakthrough checks never enter the saving-throw contract.
    return not any(
        e.event_type == 'PASSIVE_TRIGGERED' and (e.payload or {}).get('reversal_roll') == rc.roll.roll_id
        for e in engine.events)


def reversal_used(engine, holder, rc):
    from ..gate2_runtime_models import CandidateKind
    from ..paid_relocation import preserve_pending
    ctx = feature_context(engine, holder.actor, 'reversal', rc.roller, holder.numbers)
    candidate = engine._candidate(CandidateKind.REACTION, holder.actor, holder.feature_id,
        'Reversal', target_ids=(rc.roller.entity_id,))
    declared = declare_alignment(ctx.action, engine, holder.actor, candidate, ctx.intent)
    if declared is not None:
        ctx.action = declared
        ctx.typed = dict(declared.parameters['typed'])
    sequence_accepted(engine, holder.actor, ctx.action)
    # The native d20 adapter retains its own causal receipt through the save's
    # consequences. Keep only this transient source context beside that roll;
    # the shared transaction restores it if an owner choice pauses or fails.
    preserve_pending(engine, '_yin_yang_reversal_contexts')
    engine.__dict__.setdefault('_yin_yang_reversal_contexts', {})[rc.roll.roll_id] = ctx
    engine._append_event('PASSIVE_TRIGGERED', holder.feature_id, actor_id=holder.actor.entity_id,
        target_ids=(rc.roller.entity_id,), payload={'reversal_roll': rc.roll.roll_id, 'log': 'Reversal adds Proficiency Bonus to this failed saving throw.'})


def reversal_benefits(engine, holder, rc, result, bonus):
    apply_reversal_benefits(engine, holder, rc, result, bonus)
    from ..paid_relocation import preserve_pending, technique_completed, settle_activation
    preserve_pending(engine, '_yin_yang_reversal_contexts')
    pending = engine.__dict__.get('_yin_yang_reversal_contexts', {})
    ctx = pending.pop(rc.roll.roll_id, None)
    if not pending:
        engine.__dict__.pop('_yin_yang_reversal_contexts', None)
    if ctx is not None:
        technique_completed(ctx)
        settle_activation(engine, ctx.action.source_definition_id, ctx.intent)


def apply_reversal_benefits(engine, holder, rc, result, bonus):
    if result.total < (rc.dc or 0) or rc.resolved_success is False:
        return
    from .rider_choices import pick
    from .condition_authority import source_cl
    from ..typed_executor import run_effects
    actor, target = holder.actor, rc.roller
    labels = {'move': f'Move {target.display_name} up to 10 feet without provoking Opportunity Attacks',
        'temp': f'Grant {target.display_name} {2 * int(holder.numbers["pb"])} Temporary HP',
        'harmony': 'Gain 1 Harmony, up to your maximum; spend 1 after a successful Reversal to choose two benefits'}
    current = next((c.data.get('current') for c in actor.conditions.values() if c.condition_id == CURRENT), None)
    if current in ('yin', 'yang'):
        labels['current'] = 'Switch your active Current from ' + current.title() + ' to ' + ('Yang' if current == 'yin' else 'Yin')
    removable = {iid: c for iid, c in target.conditions.items() if c.condition_id in (
        'charmed', 'frightened', 'condition:typed.charmed', 'condition:typed.frightened')
        and source_cl(engine, c) is not None and source_cl(engine, c) <= int(holder.numbers['cl'])}
    if removable:
        labels['end'] = f'End one Frightened or Charmed effect on {target.display_name} created at Cultivation Level {holder.numbers["cl"]} or lower'
    count = 2 if unity(actor) else 1
    if not unity(actor) and actor.resources.get(HARMONY, 0) > 0:
        spend = pick(engine, actor, 'reversal_harmony', 'Reversal', ['one', 'two'], subject=target,
            optional=False, labels={'one': 'Choose one benefit; spend no Harmony', 'two': 'Spend 1 Harmony to choose two different benefits'},
            prompt=f'Reversal made {target.display_name}’s saving throw succeed. Choose one benefit or spend 1 Harmony for two.')
        if spend == ['two']:
            engine._spend_resource(actor, HARMONY, 1, holder.feature_id)
            count = 2
    chosen = pick(engine, actor, 'reversal_benefits', 'Reversal', list(labels), labels=labels, subject=target,
        optional=False, maximum=count, minimum=count, prompt=f'Reversal: {target.display_name} succeeds against {rc.source_name or "the triggering saving throw"}. Choose {count} different benefits.')
    for benefit in chosen:
        if benefit == 'move':
            from .needle import cell_id
            from .rider_movement import forced_route
            routes = engine.grid.reachable(target.position, movement_ft=10,
                occupied_cells=engine._occupied_cells_except(target.entity_id), footprint=engine._footprint(target))
            paths = {cell_id(cell): path for cell, (path, cost) in routes.items() if cost > 0}
            if paths:
                destination = pick(engine, actor, 'reversal_move', 'Reversal', list(paths), subject=target,
                    labels={key: f'Move {target.display_name} to square {key.removeprefix("cell:")}, without provoking Opportunity Attacks' for key in paths},
                    prompt=f'Reversal: choose where to move {target.display_name}, up to 10 feet without provoking Opportunity Attacks.')
                if destination:
                    forced_route(engine, target, paths[destination[0]], holder.feature_id, actor)
        elif benefit == 'temp':
            run_effects(feature_context(engine, actor, 'reversal', target, holder.numbers),
                [{'type': 'temp_hp', 'applies_to': 'target', 'flat': 2 * int(holder.numbers['pb'])}])
        elif benefit == 'current':
            old = current
            mode = 'yin' if old == 'yang' else 'yang'
            engine._remove_condition(actor, CURRENT, holder.feature_id)
            engine._apply_condition(actor, CURRENT, holder.feature_id, actor.entity_id,
                expires_on='START_OF_SOURCE_NEXT_TURN', data={'current': mode, 'label': mode.title() + ' Current: active until your next turn starts'})
        elif benefit == 'harmony':
            gain_harmony(engine, actor, holder.feature_id)
        elif benefit == 'end':
            selected = pick(engine, actor, 'reversal_end', 'Reversal', list(removable), subject=target,
                optional=False, labels={iid: f'End {c.condition_id.split(".")[-1]} on {target.display_name}' for iid, c in removable.items()})
            c = removable[selected[0]]
            engine._remove_condition_instance(target, c.instance_id, holder.feature_id)


# Additive rules keep the original die and permit ordinary save proficiency.
from .d20_rewrite import Rule, register
register(Rule('yin_yang_reversal', 'Reversal', op='bonus', rolls=('save',), who='any',
    range_ft=30, see=True, reaction=True, limit='round', finder=reversal_holders,
    checkpoint='SAVE_RESULT_BEFORE_DECLARED',
    costs_for=lambda engine, holder, rc: ((),) if unity(holder.actor) else ((("qi", 2),),),
    ai=lambda engine, holder, rc: relation(engine, holder.actor, rc.roller) == ALLY,
    guard=reversal_guard, on_use=reversal_used,
    bonus=lambda engine, holder, rc: int(holder.numbers['pb']), after_bonus=reversal_benefits,
    after_settlement=True, before_consequences=True))


def _flow(engine, actor):
    return owns(engine, actor, 'balanced_flow')


def _current(actor):
    if any(c.condition_id == 'condition:typed.yin_yang_unity' for c in actor.conditions.values()):
        from .activation_requirements import effective_cl
        if effective_cl(actor, 18) >= 18:
            return 'both'
    return next((c.data.get('current') for c in actor.conditions.values() if c.condition_id == CURRENT), None)


def _stamp(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}'


def _qi(ctx):
    if type(ctx.typed.get('qi_powered')) is bool:
        return ctx.typed['qi_powered']
    source = str(ctx.typed.get('option_of') or ctx.typed.get('source') or '')
    return (any(pool == QI for pool, _ in ctx.action.costs)
            or source.startswith(('tianxia.subpath.qi.', 'tianxia.path.qi_cultivation.'))
            or ctx.typed.get('qi_powered') is True)


@hook('compile_block')
def flow_block(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'numbers': dict(numbers), 'choice_owner': True}]
    return None


@hook('compile_actions')
def flow_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    if FLOW not in info['owned_ids']:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.yin_yang.restorative_palm",
        display_name='Restorative Palm', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5, costs=((QI, 2),),
        parameters={'typed': {'source': FLOW, 'numbers': dict(info['numbers']),
            'min_cl': 3,
            'duration': {'kind': 'instant'}, 'riders': [],
            'effects': [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                         'formula': 'key_ability_modifier'}, {'type': 'yin_yang_palm'}]},
            'expected_damage': 0, 'ai_keep_legal_recipients': True, 'description': 'Touch one creature as an Action and spend 2 Qi. '
            'It regains 2d8 plus your Qi key ability modifier HP. Yin Current also grants your Proficiency Bonus in '
            'Temporary HP; Yang Current lets that creature choose a 5-foot move without provoking Opportunity Attacks.'})]


@hook('turn_start_choice')
def flow_choice(engine, actor):
    if not _flow(engine, actor) or not actor.active:
        return
    from .rider_choices import pick
    selected = pick(engine, actor, 'balanced_flow', 'Balanced Flow', ['yin', 'yang'], subject=actor,
        labels={'yin': 'Yin Current: once per turn, reduce one affected creature’s Speed by 10 feet until the start of your next turn',
                'yang': f'Yang Current: once per turn, add your Proficiency Bonus ({source_pb(engine, actor)}) to one damage or healing roll'},
        preferred=[_current(actor) if _current(actor) in ('yin', 'yang') else 'yin'], optional=False,
        prompt=f'Balanced Flow: choose the current for {actor.display_name} until its next turn starts.')
    if selected:
        engine._remove_condition(actor, CURRENT, FLOW)
        engine._apply_condition(actor, CURRENT, FLOW, actor.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN',
            data={'current': selected[0], 'label':
                ('Yin Current: once per turn, reduce one affected creature’s Speed by 10 feet until the start of your next turn'
                 if selected[0] == 'yin' else
                 f'Yang Current: once per turn, add your Proficiency Bonus ({source_pb(engine, actor)}) to one damage or healing roll')})


@hook('fight_setup_tasks')
def initial_turn_task(engine):
    actor = engine.state.actors[engine.state.initiative_order[0]]
    if _flow(engine, actor) and actor.turns_started == 0:
        # The setup commit starts the actual first turn with its real intent
        # and configured controllers. No constructor chooses for a player.
        return [{'actor_id': actor.entity_id, 'source_id': FLOW}]
    return None


@hook('fight_setup_label')
def initial_turn_caption(engine):
    actors = [engine.state.actors[task.actor_id] for task in engine.state.setup_tasks if task.source_id == FLOW]
    if actors:
        return 'Begin the first turn: choose Balanced Flow for ' + ', '.join(actor.display_name for actor in actors) + ' (no action or Qi cost)'
    return None


@hook('fight_setup')
def begin_initial_turn(engine, actor, source, intent):
    return True if source == FLOW and _flow(engine, actor) else None


def _yang(ctx, roll_kind, effect=None, targets=None):
    if not _flow(ctx.engine, ctx.actor) or _current(ctx.actor) not in ('yang', 'both') or not _qi(ctx):
        return None
    key = '_round_balanced_yang'
    if ctx.actor.turn_flags.get(key) == _stamp(ctx.engine):
        return None
    from .rider_choices import pick
    from .choice_prompt import action_context
    from ..typed_executor import effect_subjects
    affected = list(targets) if targets is not None else (
        effect_subjects(ctx, effect, harmful=(roll_kind == 'damage')) if effect is not None else [])
    # Damage effects roll once for an area, before delivery to each creature.
    # Keep the choice attached to a real recipient while naming the whole batch
    # in display context; never imply the off-turn zone's current actor caused it.
    affected = [creature for creature in affected if creature is not None]
    subject = affected[0] if affected else ctx.target or ctx.actor
    names = ', '.join(creature.display_name for creature in affected) or subject.display_name
    context = action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, subject, action=ctx.action)
    if len(affected) > 1:
        # prompt_context is display-only; a group label avoids presenting the
        # first member as the sole recipient of one shared roll.
        context['affected_id'] = names
    action_name = str(ctx.action.display_name or 'the action')
    source_name = ctx.actor.display_name
    trigger = f"the {roll_kind} roll from {action_name} by {source_name}, affecting {names}"
    selected = pick(ctx.engine, ctx.actor, 'balanced_yang', 'Yang Current', ['increase', 'save'],
        subject=subject,
        labels={'increase': f'Add your Proficiency Bonus ({source_pb(ctx.engine, ctx.actor)}) to this roll; spend Yang Current for this turn',
                'save': 'Keep Yang Current available for a later damage or healing roll'},
        preferred=['increase'], optional=True, automatic=True,
        prompt_context=context,
        prompt=f'Yang Current: add your Proficiency Bonus ({source_pb(ctx.engine, ctx.actor)}) to {trigger}? You can choose one roll per turn.')
    if not selected or selected[0] != 'increase':
        return None
    ctx.actor.turn_flags[key] = _stamp(ctx.engine)
    return source_pb(ctx.engine, ctx.actor)


@hook('damage_roll_bonus')
def yang_damage(ctx, eff, kinds):
    # Attack construction asks this before the hit is known. The hit-only
    # confirmed-hit damage_packet_selection seam below owns those packets.
    return _yang(ctx, 'damage', eff) if eff is not None else None


@hook('damage_packet_selection')
def yang_attack(ctx, target, packet_kinds):
    # This documented callback receives the mutable spec after a confirmed hit,
    # including defensive reactions. Construction and misses spend no use.
    spec=ctx.attack_defense_spec
    dice=spec.get('damage') if spec else None
    if dice is None or dice.count<=0 or dice.sides<2 or spec.get('fixed_damage') is not None:
        return
    bonus=_yang(ctx, 'damage', targets=[target])
    if bonus:
        spec['damage']=dice.model_copy(update={'modifier':dice.modifier+bonus})


@hook('healing_roll_bonus')
def yang_healing(ctx, eff):
    from ..typed_amounts import effect_dice
    from ..gate2_runtime_models import DiceSpec
    dice=ctx.dice(effect_dice(eff,ctx.numbers))
    return _yang(ctx, 'healing', eff) if isinstance(dice,DiceSpec) and dice.count>0 and dice.sides>=2 else None


def _yin(ctx, target):
    if (target is None or not target.active or not _flow(ctx.engine, ctx.actor)
            or _current(ctx.actor) not in ('yin', 'both') or not _qi(ctx)
            or ctx.actor.turn_flags.get('_round_balanced_yin') == _stamp(ctx.engine)):
        return
    from .rider_choices import pick
    selected = pick(ctx.engine, ctx.actor, 'balanced_yin', 'Yin Current', [target.entity_id], subject=target,
        labels={target.entity_id: f"Reduce {target.display_name}'s Speed by 10 feet"}, intent=ctx.intent,
        optional=True, preferred=[target.entity_id] if relation(ctx.engine, target, ctx.actor) == ENEMY else [],
        automatic=relation(ctx.engine, target, ctx.actor) == ENEMY)
    if not selected:
        return
    ctx.actor.turn_flags['_round_balanced_yin'] = _stamp(ctx.engine)
    from ..typed_executor import run_effects
    run_effects(feature_context(ctx.engine, ctx.actor, 'balanced_flow', target,
                               _flow(ctx.engine, ctx.actor)['numbers']),
        [{'type': 'speed', 'applies_to': 'target', 'flat': -10, 'source_owned': True, 'duration': 'until_start_of_your_next_turn',
          'evidence': 'Yin Current: reduce Speed by 10 feet until the start of your next turn.'}])


@hook('damage_dealt')
def yin_damage(ctx, target, amount):
    if amount > 0:
        _yin(ctx, target)


@hook('after_save_resolved')
def yin_save(ctx, target, ability, named, failed):
    if failed:
        _yin(ctx, target)


@effect('yin_yang_palm')
def palm_current(ctx, eff):
    if not _flow(ctx.engine, ctx.actor):
        return
    from ..typed_executor import run_effects
    target = ctx.target or ctx.actor
    if _current(ctx.actor) in ('yin', 'both'):
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'flat': source_pb(ctx.engine, ctx.actor)}])
    if _current(ctx.actor) in ('yang', 'both'):
        from .rider_choices import step
        step(ctx.engine, target, 'restorative_palm_step', 'Restorative Palm', target, 5, ctx.source, ctx.intent,
             trigger='Yang Current heals you', ignored_oa=[a.entity_id for a in ctx.engine.state.actors.values()],
             all_destinations=True)


@hook('ai_candidate_allowed')
def palm_ai_recipient(engine, actor, candidate, action):
    # Printed "one creature": ally preference belongs to ranking, never to
    # legality. Keep hostile and neutral recipients reachable to model seats.
    return None
