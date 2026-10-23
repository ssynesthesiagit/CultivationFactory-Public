"""Standard Emotion Cultivator source family.

Source acquisition uses feature_access; private visible-response declarations
use fact_consent_admission and observer_information. Declarations are answers
from the affected creature's controller, never conclusions from damage or teams.
The five standard records own these consumers; no Heart-Stealing feature is
granted. Shared helpers in qi_subpaths_1 remain the single Pulse implementation.
"""
from dataclasses import replace
import json
from . import effect, hook
from .qi_subpaths_1 import PULSE, HEART, EXPOSURE, emotional_pulse

PREFIX = 'tianxia.subpath.qi.emotion_cultivator.feature.'
CONTAGION = PREFIX + 'emotional_contagion'
WEATHER = PREFIX + 'weather_of_the_heart'
WEAVER = PREFIX + 'heartweaver'
LEVELS = {PULSE: 3, CONTAGION: 6, HEART: 10, WEATHER: 14, WEAVER: 18}
EMOTIONS = ('rage', 'sorrow', 'fear', 'joy', 'calm')
# Player-facing names for the conditions a witness can perceive (no internal ids).
PERCEIVED_LABELS = {'condition:typed.charmed': 'Charmed', 'condition:typed.frightened': 'Frightened',
    'condition:typed.emotional_rage': 'Rage', 'condition:typed.emotional_sorrow': 'Sorrow',
    'condition:typed.emotional_calm': 'Calm'}
QI = 'resource:core.qi'


@hook('feature_access_policy')
def access(feature_id):
    if feature_id not in LEVELS:
        return None
    return {'path': 'tianxia.path.qi_cultivation', 'minimum_cl': LEVELS[feature_id],
        'subpath': 'tianxia.subpath.qi.emotion_cultivator',
        'classification': 'Restricted Scripture',
        'source_kinds': ['teacher', 'scripture', 'inheritance', 'gm_authorized'],
        'replaced_by': [
            'tianxia.subpath.qi.heart_stealing_emotion_cultivator.feature.' + suffix
            for suffix in ('steal_the_surface_heart', 'heart_anchor',
                           'rewrite_the_inner_heart', 'heart_transplant', 'sovereign_of_ten_thousand_hearts')]}


def owns(engine, actor, source):
    from ..alternative_payments import owned
    return owned(engine, actor, source)


def condition(actor, name):
    return next((c for c in actor.conditions.values() if c.condition_id == 'condition:typed.' + name), None)


def round_boundary(engine):
    return f'START_OF_SLOT_AT:{engine.state.round_number + 1}:0'


def record(ctx, actor, name, data, expiry='UNTIL_REMOVED'):
    ctx.engine._apply_condition(actor, 'condition:typed.' + name, ctx.source,
        ctx.actor.entity_id, expires_on=expiry, data=data)


def pick(ctx, who, kind, options, labels, prompt, *, maximum=1, minimum=1, optional=False, known=None):
    from .needle import ask, checkpoint_id
    return ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'emotion', ctx.source, kind, who.entity_id), who,
        'choice:needle.emotion.' + kind, options, labels=labels, prompt=prompt,
        minimum=minimum, maximum=maximum, allow_decline=optional,
        automatic_options=known, name=ctx.action.display_name, feature_id=ctx.typed.get('source', ''))


@hook('compile_actions')
def ownership_markers(info):
    """A passive trigger needs a sealed, source-owned catalog identity too."""
    from ..gate2_runtime_models import ActionDefinition
    if CONTAGION not in info['owned_ids']:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.emotion_contagion_owner",
        display_name='Emotional Contagion', owner_id=info['actor_id'], economy='NONE',
        resolution_kind='TYPED', target_kind='SELF', range_ft=None,
        parameters={'setting_only': True, 'typed': {'source': CONTAGION,
            'effects': [], 'numbers': dict(info['numbers']), 'duration': {'kind': 'instant'}, 'riders': []}})]


@hook('candidate_allowed')
def passive_marker(engine, actor, candidate, action):
    if action and action.source_definition_id.endswith('.emotion_contagion_owner'):
        return False
    return None


@effect('emotion_pulse_outcome')
def pulse_outcome(ctx, row):
    """Only an actual resolved Pulse branch can produce these receipts."""
    from ..typed_executor import run_effects
    from ..fact_consent_admission import admit_choice
    from ..observer_information import publish
    subject = ctx.target
    if subject is None:
        return
    if not any(c.condition_id == EXPOSURE and c.source_actor_id == ctx.actor.entity_id
               for c in subject.conditions.values()):
        ctx.engine._apply_condition(subject, EXPOSURE, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'label': 'Affected by Emotional Pulse this scene'})
    if not row.get('failed'):
        return
    declared = admit_choice(ctx, subject, PULSE, 'visible_emotional_response', ctx.source,
        list(EMOTIONS), labels={s: s.title() for s in EMOTIONS},
        prompt=f'{subject.display_name}: which of Rage, Sorrow, Fear, Joy or Calm produced the strongest visible response to {ctx.action.display_name}? Decline if this is unknown. No memories or private motives are revealed.',
        expires_on='UNTIL_REMOVED', readers=(ctx.actor.entity_id,), automatic_options=())
    if declared:
        from ..target_knowledge import can_see
        if can_see(ctx.engine, ctx.actor, subject):
            perceived = list(dict.fromkeys(PERCEIVED_LABELS[c.condition_id]
                for c in subject.conditions.values()
                if not c.data.get('secret') and c.condition_id in PERCEIVED_LABELS))
            publish(ctx.engine, ctx.actor, ctx.source, ctx.actor, 'declaration',
                {'subject_id': subject.entity_id, 'strongest_visible_response': declared['value'],
                 'text': f'Emotional Signature: {subject.display_name} showed its strongest visible response to {declared["value"].title()}. Perceived emotional conditions: {", ".join(perceived) or "none"}. This reveals no memories, motives or relationships.',
                 'perceived_conditions': perceived, 'declaration_receipt': declared['receipt_id']}, 'UNTIL_REMOVED')
    if row.get('secondary') or not owns(ctx.engine, ctx.actor, CONTAGION):
        return
    if condition(ctx.actor, 'emotion_contagion_used'):
        return
    used_free = condition(ctx.actor, 'emotion_contagion_free')
    free = condition(ctx.actor, 'heartweaver') and used_free is None
    price = 0 if free else 2
    if ctx.actor.resources.get(QI, 0) < price:
        return
    from ..target_knowledge import located
    pool = [a for a in ctx.engine.state.actors.values() if a.active and a is not subject
        and located(ctx.engine, ctx.actor, a)
        and ctx.engine._distance_actor_to_actor(subject, a) <= 10]
    if not pool:
        return
    chosen = pick(ctx, ctx.actor, 'contagion', [a.entity_id for a in pool],
        {a.entity_id: a.display_name for a in pool},
        f'Emotional Contagion after {ctx.action.display_name} affected {subject.display_name}: choose up to {ctx.numbers["pb"]} other creatures within 10 feet of it. Costs {price} Qi, once this turn. Each resolves separately.',
        minimum=0, maximum=min(int(ctx.numbers['pb']), len(pool)), optional=True)
    if not chosen:
        return
    if price:
        ctx.engine._spend_resource(ctx.actor, QI, price, ctx.source)
    record(ctx, ctx.actor, 'emotion_contagion_used', {'label': 'Emotional Contagion used this turn'},
        'END_OF_CURRENT_TURN')
    if free:
        from .condition_ownership import refresh_owned
        refresh_owned(ctx.engine, ctx.actor, 'condition:typed.emotion_contagion_free', ctx.actor.entity_id, ctx.source)
        record(ctx, ctx.actor, 'emotion_contagion_free', {'label': 'Free Emotional Contagion used this round',
            'round': ctx.engine.state.round_number}, round_boundary(ctx.engine))
    for recipient in pool:
        if recipient.entity_id not in chosen:
            continue
        local = replace(ctx, target=recipient, targets=[recipient])
        form = row['form']
        willing = False
        if form in ('hostile_joy', 'hostile_calm'):
            from .willing_targets import asks_consent
            willing = asks_consent(ctx.engine, ctx.intent, recipient, 'Emotional Contagion',
                f'{recipient.display_name}: accept the willing {form.removeprefix("hostile_").title()} expression of Emotional Contagion instead of its hostile saving throw?',
                prefer_accept=False, asker=ctx.actor)
        received = emotional_pulse(local, {'form': form.replace('hostile_', 'willing_') if willing else form,
            'secondary': True})
        if willing and received:
            courage(local)


def courage(ctx):
    from ..typed_executor import run_effects
    from .qi_subpaths_1 import relief_options
    options = ['temporary_hp', 'move']
    labels = {'temporary_hp': f'Increase current Temporary Hit Points by {ctx.numbers["pb"]}',
        'move': 'Move an additional 5 feet without Opportunity Attacks'}
    end = {'type': 'source_condition_relief', 'conditions': ['frightened'], 'operation': 'end', 'strictly_lower': True}
    repeat = {'type': 'source_condition_relief', 'conditions': ['frightened'], 'operation': 'repeat', 'equal_or_higher': True}
    for name, spec, label in [('end', end, 'End Frightened from a lower Cultivation Level'),
            ('repeat', repeat, 'Immediately repeat a Frightened save with Advantage against an equal or higher Cultivation Level')]:
        if relief_options(ctx, ctx.target, spec):
            options.append(name); labels[name] = label
    selected = pick(ctx, ctx.actor, 'share_courage', options, labels,
        f'Share Courage for {ctx.target.display_name}: choose one additional benefit from this Emotional Contagion activation. No additional cost.')
    if not selected:
        return
    if selected[0] == 'temporary_hp':
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target',
            'flat': ctx.target.temporary_hp + int(ctx.numbers['pb'])}])
    elif selected[0] == 'move':
        run_effects(ctx, [{'type': 'movement', 'applies_to': 'target', 'distance_ft': 5,
            'choose_subject_destination': True, 'no_opportunity_attacks': True}])
    else:
        run_effects(ctx, [end if selected[0] == 'end' else repeat])


@hook('presentation_hidden_conditions')
def private_information(engine, actor):
    from ..observer_information import READING
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == READING]


def context_for(engine, actor, source, intent=None):
    from ..typed_executor import Context
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
        and (a.parameters.get('typed') or {}).get('source') == source
        and (a.parameters.get('typed') or {}).get('emotion_kind') in ('weather', 'weaver')), None)
    if action is None:
        return None
    return Context(engine=engine, actor=actor, action=action,
        typed=action.parameters['typed'], intent=intent or getattr(engine, '_active_intent', None), targets=[])


@hook('compile_actions')
def family_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    import copy
    out = []
    def make(key, source, name, kind, cost, economy='NONE', **values):
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.emotion.{key}",
            display_name=name, owner_id=info['actor_id'], economy=economy,
            resolution_kind='TYPED', target_kind='SELF', range_ft=None,
            costs=((QI, cost),) if cost else (), parameters={'typed': {
                'source': source, 'emotion_kind': kind, 'numbers': dict(info['numbers']),
                'effects': [{'type': 'emotion_' + kind, **values}], 'riders': [],
                'duration': {'kind': 'instant'}}, 'expected_damage': 0}))
    if WEATHER in info['owned_ids']:
        for weather in EMOTIONS:
            for origin in ('self', 'armament'):
                for free in (False, True) if WEAVER in info['owned_ids'] else (False,):
                    make(f'weather.{weather}.{origin}.{int(free)}', WEATHER,
                        f'Weather of the Heart: {weather.title()} ({"Domain Armament" if origin == "armament" else "centered on you"})' + (' — Heartweaver' if free else ''),
                        'weather', 0 if free else 5, 'BONUS_ACTION', weather=weather, origin=origin, free=int(free))
        make('weather.change', WEATHER, 'Weather of the Heart: change emotional weather', 'change_weather', 0)
        make('weather.aid', WEATHER, 'Weather of the Heart: Heartward Aid', 'heartward', 0)
    if WEAVER not in info['owned_ids']:
        return out or None
    make('weaver', WEAVER, 'Heartweaver — 1 minute, 8 Qi, once per scene', 'weaver', 8, 'BONUS_ACTION')
    for base in info['actions']:
        typed = base.parameters.get('typed') or {}
        source = typed.get('source')
        if source not in (PULSE, HEART):
            continue
        for free in ((False, True) if source == PULSE else (False,)):
            special = copy.deepcopy(typed)
            special.update(emotion_kind='pulse_free' if free else 'discounted', riders=[], range_ft=60)
            out.append(base.model_copy(update={
                'source_definition_id': base.source_definition_id + ('.heartweaver_free' if free else '.heartweaver'),
                'display_name': base.display_name + (' — Heartweaver free Pulse' if free else ' — Heartweaver'),
                'range_ft': 60, 'economy': EconomyKind.NONE if free else base.economy,
                'costs': () if free else ((QI, 2),),
                'parameters': {**base.parameters, 'typed': special}}))
    return out or None


@hook('candidate_allowed')
def family_admission(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    source = typed.get('source')
    kind = typed.get('emotion_kind')
    active = condition(actor, 'heartweaver') is not None and owns(engine, actor, WEAVER)
    if source in (PULSE, HEART) and active != (kind in ('discounted', 'pulse_free')):
        return False
    if kind == 'pulse_free' and condition(actor, 'heartweaver_free_pulse'):
        return False
    if source in (WEATHER, WEAVER) and not kind:
        return False
    if kind == 'weaver' and condition(actor, 'heartweaver_scene'):
        return False
    if kind == 'weather':
        row = typed['effects'][0]
        if bool(row.get('free')) != active:
            return False
        if row['origin'] == 'armament':
            from .qi_path import armament_condition
            if armament_condition(actor) is None:
                return False
    if kind in ('heartward', 'change_weather'):
        if condition(actor, 'heart_weather') is None:
            return False
        if condition(actor, 'emotion_' + kind + '_used'):
            return False
        # Ordinary weather changes belong to the start-of-turn checkpoint.
        if kind == 'change_weather' and not active:
            return False
    return None


@hook('compile_action')
def effective_emotion_authority(action, info):
    typed = action.parameters.get('typed') or {}
    if typed.get('source') not in LEVELS:
        return None
    from ..feature_access import effective_cl
    level = effective_cl(info['owner_sheet'], 'tianxia.path.qi_cultivation')
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'numbers': {**(typed.get('numbers') or {}), 'cl': level}}}})


@hook('technique_used')
def free_pulse_used(ctx):
    if ctx.typed.get('emotion_kind') == 'pulse_free':
        record(ctx, ctx.actor, 'heartweaver_free_pulse', {'label': 'Free Emotional Pulse used this turn'},
            'START_OF_SOURCE_NEXT_TURN')


@effect('emotion_weaver')
def activate_weaver(ctx, row):
    from .effect_durations import round_token
    record(ctx, ctx.actor, 'heartweaver', {'label': 'Heartweaver: Psychic Resistance and Advantage against Charmed, Frightened and emotional features for 1 minute',
        'rule': {'damage_resistances': ['PSYCHIC']}}, round_token(ctx.engine, 10))
    record(ctx, ctx.actor, 'heartweaver_scene', {'label': 'Heartweaver used this scene'})


def weather_origin(engine, owner, held):
    if held.data.get('origin') == 'armament':
        from .qi_path import armament_condition, armament_point
        if armament_condition(owner) is None:
            return None
        from ..gate2_runtime_models import Position
        x, y = armament_point(owner)
        return Position(x=x, y=y, z=owner.position.z)
    return owner.position


def inside(engine, owner, held, actor):
    origin = weather_origin(engine, owner, held)
    if origin is None or not engine._on_battlefield(actor):
        return False
    from ..gate2_runtime_models import Position
    return any(engine.grid.distance_ft(origin, point := Position(x=x, y=y, z=z)) <= 20
        and engine.grid.line_of_physical_transmission(origin, point)
        for x, y, z in engine._actor_volume(actor))


@effect('emotion_weather')
def activate_weather(ctx, row):
    from .effect_durations import round_token
    from .condition_ownership import refresh_owned
    from ..relations import relation
    pool = [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine, ctx.actor, a) == 'ALLY']
    chosen = pick(ctx, ctx.actor, 'weather_allies', [a.entity_id for a in pool],
        {a.entity_id: a.display_name for a in pool},
        f'Weather of {row["weather"].title()}: choose allies who receive its benefits while inside the 20-foot aura for 1 minute. Costs {0 if row.get("free") else 5} Qi and a Bonus Action.',
        maximum=len(pool), minimum=0, optional=True)
    previous = condition(ctx.actor, 'heart_weather')
    if previous and previous.data.get('concentration'):
        from ..concentration import copies, end_copy
        for sequence in copies(ctx.actor, previous.source_definition_id):
            end_copy(ctx.engine, ctx.actor, sequence, 'REPLACED')
    refresh_owned(ctx.engine, ctx.actor, 'condition:typed.heart_weather', ctx.actor.entity_id, ctx.source)
    if not row.get('free'):
        ctx.engine._start_concentration(ctx.actor, ctx.source)
        # The printed 1-minute aura ends its Concentration copy on the shared deadline.
        from dataclasses import replace
        from ..typed_executor import run_effects
        timer = replace(ctx, typed={**ctx.typed, 'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True}})
        run_effects(timer, [{'type': 'limit_concentration_duration'}])
    record(ctx, ctx.actor, 'heart_weather', {'weather': row['weather'], 'origin': row['origin'],
        'allies': chosen, 'concentration': int(not row.get('free')),
        'label': 'Weather of the Heart: ' + row['weather'].title() + ', 20-foot aura for 1 minute'}, round_token(ctx.engine, 10))


@effect('emotion_change_weather')
def change_weather(ctx, row):
    held = condition(ctx.actor, 'heart_weather')
    if held is None:
        return
    selected = pick(ctx, ctx.actor, 'weather_change', list(EMOTIONS), {s: s.title() for s in EMOTIONS},
        'Weather of the Heart: choose your emotional weather. No action or Qi; once this turn.', optional=True)
    if not selected:
        return
    # Update the held instance in place: its activation source, expiry and
    # Concentration ledger entry stay bound to the original aura.
    data = {**held.data, 'weather': selected[0],
        'label': 'Weather of the Heart: ' + selected[0].title() + ', 20-foot aura'}
    ctx.engine._update_condition_data(ctx.actor, held, data, held.source_definition_id)
    record(ctx, ctx.actor, 'emotion_change_weather_used', {'label': 'Changed emotional weather this turn'}, 'START_OF_SOURCE_NEXT_TURN')


def aid(ctx, subject, kind, feet=5):
    from ..typed_executor import run_effects
    from .qi_subpaths_1 import relief_options
    local = replace(ctx, target=subject, targets=[subject])
    rows = {
        'temporary_hp': [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'double_pb'}],
        'move': [{'type': 'movement', 'applies_to': 'target', 'distance_ft': feet,
            'choose_subject_destination': True, 'no_opportunity_attacks': True}],
        'save': [{'type': 'next_d20_mode', 'applies_to': 'target', 'kinds': ['save'],
            'expires_on': 'START_OF_SOURCE_NEXT_TURN'}]}
    labels = {'temporary_hp': f'Gain {2 * int(ctx.numbers["pb"])} Temporary Hit Points',
        'move': f'Move {feet} feet without Opportunity Attacks',
        'save': 'Advantage on the next saving throw before the start of my next turn'}
    if kind == 'master':
        rows['attack'] = [{'type': 'next_d20_mode', 'kinds': ['attack'], 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}]
        labels['attack'] = 'Advantage on the next attack roll before the start of my next turn'
    else:
        end = {'type': 'source_condition_relief', 'conditions': ['frightened'], 'operation': 'end', 'strictly_lower': True}
        repeat = {'type': 'source_condition_relief', 'conditions': ['frightened', 'charmed'], 'operation': 'repeat', 'higher_only': True}
        for name, spec, label in [('end', end, 'End Frightened from a lower Cultivation Level'),
                ('repeat', repeat, 'Immediately repeat a higher-level Charmed or Frightened save with Advantage')]:
            if relief_options(local, subject, spec):
                rows[name] = [spec]; labels[name] = label
    selected = pick(ctx, ctx.actor, kind + '_benefit', list(rows), labels,
        f'{"Master of the Inner Weather" if kind == "master" else "Heartward Aid"}: choose one benefit for {subject.display_name}. No additional Qi or action.')
    if selected:
        run_effects(local, rows[selected[0]])


@effect('emotion_heartward')
def heartward(ctx, row):
    from ..relations import relation
    held = condition(ctx.actor, 'heart_weather')
    if held is None:
        return
    pool = [a for a in ctx.engine.state.actors.values() if a.active and inside(ctx.engine, ctx.actor, held, a)
        and relation(ctx.engine, ctx.actor, a) == 'ALLY' and not condition(a, 'emotion_heartward_received')]
    selected = pick(ctx, ctx.actor, 'heartward_target', [a.entity_id for a in pool],
        {a.entity_id: a.display_name for a in pool}, 'Heartward Aid: choose one ally in your aura; once on your turn, no additional Qi or action.', optional=True)
    if not selected:
        return
    subject = ctx.engine.state.actors[selected[0]]
    aid(ctx, subject, 'heartward')
    record(ctx, ctx.actor, 'emotion_heartward_used', {'label': 'Heartward Aid used this turn'}, 'START_OF_SOURCE_NEXT_TURN')
    record(ctx, subject, 'emotion_heartward_received', {'label': 'Received Heartward Aid this turn'}, 'END_OF_CURRENT_TURN')


def weather_sources(engine):
    for owner in engine.state.actors.values():
        held = condition(owner, 'heart_weather')
        if held is not None and owner.active:
            yield owner, held


def weather_trigger(engine, owner, held, subject, intent):
    from ..relations import relation
    from ..typed_executor import run_effects, condition_immune
    from .effect_durations import holder_next_turn
    if relation(engine, owner, subject) != 'ENEMY' or not inside(engine, owner, held, subject):
        return
    key = 'condition:typed.emotion_weather_received'
    if any(c.condition_id == key and c.source_actor_id == owner.entity_id for c in subject.conditions.values()):
        return
    ctx = context_for(engine, owner, WEATHER, intent)
    if ctx is None or condition_immune(engine, subject, 'emotion') or condition_immune(engine, subject, 'mind'):
        return
    ctx = replace(ctx, targets=[subject], target=subject)
    record(ctx, subject, 'emotion_weather_received', {'label': 'Affected by this emotional weather this turn'}, 'END_OF_CURRENT_TURN')
    expiry = holder_next_turn(subject)
    denied = {'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': expiry}
    form = held.data['weather']
    if form == 'rage':
        fail = [{'type': 'qi_pulse_rage', 'expires_on': expiry}]
    elif form == 'sorrow':
        fail = [{'type': 'qi_pulse_sorrow', 'dice': True, 'expires_on': expiry}]
        denied = {'type': 'qi_pulse_sorrow', 'dice': False, 'expires_on': expiry}
    elif form == 'fear':
        fail = [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target', 'expires_on': expiry}]
    elif form == 'joy':
        fail = [denied, {'type': 'disadvantage', 'on': 'Concentration saving throws', 'applies_to': 'target', 'expires_on': expiry}]
    else:
        denied = {'type': 'qi_pulse_calm', 'only_oa': True, 'expires_on': expiry}
        fail = [denied, {'type': 'speed', 'flat': -10, 'applies_to': 'target', 'expires_on': expiry}]
    # Weather does not print Pulse of Fear's automatic-success exception.
    # Immunity prevents the failed-save condition; the real save still selects
    # between that branch and the success branch's Reaction denial.
    run_effects(ctx, [{'type': 'save', 'ability': 'wis', 'save_categories': ['mind', 'emotion', 'emotional_escalation'],
        'applies_to': 'target', 'on_fail': fail, 'on_success': [denied]}])


@hook('turn_start_choice')
def weather_start(engine, actor):
    held = condition(actor, 'heart_weather')
    if held:
        ctx = context_for(engine, actor, WEATHER)
        if ctx:
            change_weather(ctx, {})
    for owner, held in list(weather_sources(engine)):
        weather_trigger(engine, owner, held, actor, getattr(engine, '_active_intent', None))
        from ..relations import relation
        if held.data['weather'] != 'joy' or relation(engine, owner, actor) != 'ALLY' or actor.entity_id not in held.data.get('allies', []) or not inside(engine, owner, held, actor):
            continue
        receipt = condition(actor, 'emotion_weather_joy')
        if receipt is not None:
            continue
        ctx = context_for(engine, owner, WEATHER)
        if ctx is not None:
            from ..typed_executor import run_effects
            local = replace(ctx, target=actor, targets=[actor])
            run_effects(local, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
            from .condition_ownership import refresh_owned
            refresh_owned(engine, actor, 'condition:typed.emotion_weather_joy', owner.entity_id, ctx.source)
            record(ctx, actor, 'emotion_weather_joy', {'round': engine.state.round_number,
                'label': 'Joy weather Temporary Hit Points received this round'}, round_boundary(engine))


@hook('movement_landed')
def weather_enter(engine, mover, previous, nxt, intent, forced):
    for owner, held in list(weather_sources(engine)):
        origin = weather_origin(engine, owner, held)
        if origin is not None and engine.grid.distance_ft(origin, previous) > 20:
            weather_trigger(engine, owner, held, mover, intent)


@hook('committed_teleport_receipt')
def weather_teleport_enter(engine, receipt):
    """A teleport that lands a creature in the aura is an entry too (the native
    teleport path does not publish movement_landed)."""
    from ..gate2_runtime_models import Position
    subject = engine.state.actors.get(receipt['actor_id'])
    if subject is None:
        return
    previous = Position(x=receipt['previous_x'], y=receipt['previous_y'], z=receipt['previous_z'])
    for owner, held in list(weather_sources(engine)):
        origin = weather_origin(engine, owner, held)
        if origin is not None and engine.grid.distance_ft(origin, previous) > 20:
            weather_trigger(engine, owner, held, subject, None)


@hook('condition_state')
def weather_condition_origin(ctx, subject, row):
    if ctx.typed.get('source') == WEATHER and row.get('condition') == 'frightened':
        held = condition(ctx.actor, 'heart_weather')
        point = weather_origin(ctx.engine, ctx.actor, held) if held else ctx.actor.position
        return {'data': {'origin_owner': ctx.actor.entity_id, 'origin_source': WEATHER,
            'origin_position': point.model_dump(mode='json')}}
    return None


@hook('condition_origin')
def emotional_fear_origin(engine, holder, held, source):
    if held.data.get('origin_source') != WEATHER or held.data.get('origin_owner') != source.entity_id:
        return None
    weather = condition(source, 'heart_weather')
    if weather:
        return weather_origin(engine, source, weather)
    from ..gate2_runtime_models import Position
    return Position.model_validate(held.data['origin_position'])


@hook('event', nested=True)
def weather_concentration(engine, event_type, event):
    if event_type != 'CONCENTRATION_ENDED':
        return
    owner = engine.state.actors.get(event.get('actor_id'))
    held = condition(owner, 'heart_weather') if owner else None
    if held is not None and held.data.get('concentration') and held.source_definition_id == event.get('source_definition_id'):
        from .condition_ownership import remove_instance
        remove_instance(engine, owner, held.instance_id, held.source_definition_id)


@hook('save')
def emotional_save_modes(ctx, subject, ability, named):
    emotional = bool(set(named).intersection({'charmed', 'frightened', 'category:emotion'}))
    if emotional and condition(subject, 'heartweaver'):
        return {'modes': ['ADVANTAGE']}
    if not set(named).intersection({'charmed', 'frightened'}):
        return None
    for owner, held in weather_sources(ctx.engine):
        if subject.entity_id not in held.data['allies'] or not inside(ctx.engine, owner, held, subject):
            continue
        if held.data['weather'] == 'sorrow':
            return {'modes': ['ADVANTAGE']}
        if held.data['weather'] == 'calm':
            mark = condition(subject, 'emotion_weather_calm_save')
            if mark is None:
                from .condition_ownership import refresh_owned
                refresh_owned(ctx.engine, subject, 'condition:typed.emotion_weather_calm_save', owner.entity_id, ctx.source)
                record(ctx, subject, 'emotion_weather_calm_save', {'round': ctx.engine.state.round_number,
                    'label': 'Calm weather first Charmed or Frightened save used this round'}, round_boundary(ctx.engine))
                return {'modes': ['ADVANTAGE']}
    return None


@hook('condition_attempt')
def fear_weather_protection(ctx, subject, row):
    if row.get('condition') != 'frightened':
        return None
    for owner, held in weather_sources(ctx.engine):
        if held.data['weather'] == 'fear' and subject.entity_id in held.data['allies'] and inside(ctx.engine, owner, held, subject):
            own = context_for(ctx.engine, owner, WEATHER)
            if own is not None and int(ctx.numbers['cl']) < int(own.numbers['cl']):
                return False
    return None


def source_frightened_immunity(ctx, subject):
    """Source-qualified immunity query shared with Pulse of Fear's explicit success rule."""
    from ..typed_executor import condition_immune
    if condition_immune(ctx.engine, subject, 'frightened'):
        return True
    return fear_weather_protection(ctx, subject, {'condition':'frightened'}) is False


@hook('attack_damage_bonus')
def rage_weather_damage(ctx, target, effect):
    if ctx.engine.state.current_actor_id != ctx.actor.entity_id or not (ctx.typed.get('weapon') or ctx.weapon_damage_dice):
        return None
    for owner, held in weather_sources(ctx.engine):
        if held.data['weather'] != 'rage' or ctx.actor.entity_id not in held.data['allies'] or not inside(ctx.engine, owner, held, ctx.actor):
            continue
        if condition(ctx.actor, 'emotion_weather_rage_hit'):
            return None
        record(ctx, ctx.actor, 'emotion_weather_rage_hit', {'label': 'Rage weather first weapon hit used this turn'}, 'END_OF_CURRENT_TURN')
        source = context_for(ctx.engine, owner, WEATHER)
        return int(source.numbers['pb']) if source else None
    return None


@hook('save_final')
def master_weather(ctx, subject, ability, named, failed):
    if failed or ctx.typed.get('source') not in LEVELS or not condition(ctx.actor, 'heartweaver'):
        return
    from ..relations import relation
    if relation(ctx.engine, ctx.actor, subject) != 'ENEMY':
        return
    used = condition(ctx.actor, 'emotion_master_used')
    if used is not None:
        return
    origin = ctx.actor.position
    held = condition(ctx.actor, 'heart_weather')
    if ctx.typed.get('source') == WEATHER and held:
        origin = weather_origin(ctx.engine, ctx.actor, held) or origin
    pool = [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine, ctx.actor, a) == 'ALLY'
        and (ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30 or ctx.engine.grid.distance_ft(origin, a.position) <= 30)]
    chosen = pick(ctx, ctx.actor, 'master_target', [a.entity_id for a in pool],
        {a.entity_id: a.display_name for a in pool},
        f'Master of the Inner Weather: {subject.display_name} succeeded against {ctx.action.display_name}. Choose one ally within 30 feet of you or the effect origin; once this round, no additional action or Qi.', optional=True)
    if chosen:
        aid(ctx, ctx.engine.state.actors[chosen[0]], 'master', feet=10)
        from .condition_ownership import refresh_owned
        refresh_owned(ctx.engine, ctx.actor, 'condition:typed.emotion_master_used', ctx.actor.entity_id, ctx.source)
        record(ctx, ctx.actor, 'emotion_master_used', {'round': ctx.engine.state.round_number,
            'label': 'Master of the Inner Weather used this round'}, round_boundary(ctx.engine))


@hook('save_roll_tags')
def emotional_roll_tags(ctx, subject, ability, pending):
    if any(owns(ctx.engine, a, WEAVER) for a in ctx.engine.state.actors.values()):
        return sorted(set(pending).intersection({'category:emotion', 'category:mind', 'category:emotional_escalation',
            'category:despair', 'category:supernatural_sorrow', 'category:surrender'}))
    return None


def reversal_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        if owns(engine, actor, WEAVER):
            ctx = context_for(engine, actor, WEAVER)
            if ctx:
                yield Holder(actor, WEAVER, {}, WEAVER, dict(ctx.numbers))


def reversal_scope(engine, holder, rc):
    return bool(rc.named.intersection({'charmed', 'frightened', 'category:emotion'}))


def reversal_after(engine, holder, rc, final, bonus):
    if rc.dc is None or final.total < rc.dc:
        return
    ctx = context_for(engine, holder.actor, WEAVER)
    if ctx is None:
        return
    ctx = replace(ctx, targets=[rc.roller], target=rc.roller)
    options = ['move', 'temporary_hp']
    labels = {'move': f'Move {rc.roller.display_name} 10 feet without Opportunity Attacks',
        'temporary_hp': f'Grant {rc.roller.display_name} {2 * int(holder.numbers["pb"])} Temporary Hit Points'}
    if rc.source_actor is not None:
        options.append('source'); labels['source'] = f'{rc.source_actor.display_name} cannot take Reactions until the start of its next turn'
    selected = pick(ctx, holder.actor, 'reversal_benefit', options, labels,
        f'Emotional Reversal turned {rc.roller.display_name}’s save against {rc.source_name or "the triggering emotional feature"} into success. Choose one benefit; no additional cost.')
    if selected:
        from ..typed_executor import run_effects
        if selected[0] == 'move':
            effects = [{'type': 'movement', 'applies_to': 'target', 'distance_ft': 10,
                'choose_subject_destination': True, 'no_opportunity_attacks': True}]
        elif selected[0] == 'temporary_hp':
            effects = [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'double_pb'}]
        else:
            ctx = replace(ctx, target=rc.source_actor, targets=[rc.source_actor])
            effects = [{'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}]
        run_effects(ctx, effects)


from .d20_rewrite import Rule, register
register(Rule('emotion_reversal', 'Emotional Reversal', feature=WEAVER,
    finder=reversal_holders, rolls=('save',), who='ally', range_ft=60,
    when='failed', op='bonus', reaction=True, limit='round', checkpoint='D20_ROLL_BONUS',
    guard=reversal_scope, bonus=lambda engine, holder, rc: int(holder.numbers['pb']),
    ai=lambda engine, holder, rc: rc.dc is not None and rc.total < rc.dc <= rc.total + int(holder.numbers['pb']),
    after_bonus=reversal_after))


ANCHORS = {'courage': {'frightened'}, 'clarity': {'charmed'},
    'patience': {'category:emotional_escalation'},
    'hope': {'category:despair', 'category:supernatural_sorrow', 'category:surrender'}}
RELEASES = ('move', 'temporary_hp', 'short_rest', 'sincere_emotion')
ANCHOR_TEXT = {'courage':'Advantage on saves against Frightened',
    'clarity':'Advantage on saves against Charmed',
    'patience':'Advantage on saves against provoked Rage, Fury or forced emotional escalation',
    'hope':'Advantage on saves against despair, supernatural sorrow or surrender'}
RELEASE_TEXT = {'move':'move 10 feet without Opportunity Attacks after a successful Heart Anchor save',
    'temporary_hp':'gain twice the creator’s Proficiency Bonus in Temporary Hit Points after a successful Heart Anchor save',
    'short_rest':'end one ordinary emotional impairment after a one-hour Short Rest',
    'sincere_emotion':'Advantage on one Insight or Persuasion check to communicate sincere emotion'}
STATE = 'emotion_cultivator'


def journey_owns(session, aid, source):
    return any((a.get('parameters', {}).get('typed') or {}).get('source') == source
        for a in session.state['actors'][aid]['bundle']['action_catalog'])


@hook('journey_native_activity')
def native_emotion_activity(session):
    return True if any(journey_owns(session, aid, source)
        for aid in session.state['actors'] for source in LEVELS) else None


@hook('fact_admission_schema')
def rite_schema(session, source, subject, kind):
    if source != WEAVER or subject not in session.state['actors']:
        return None
    if kind in ('outside_scene', 'cultivation_environment'):
        return {'value_type': 'flag', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'description': 'The GM records that no scene is active for the declared period; this does not declare a creature willing.'}
    if kind in ('heart_rite_consent', 'deep_anchor_consent', 'release_anchor_consent'):
        return {'value_type': 'document', 'maximum_seconds': 86400,
            'description': 'The creature chooses its own Heart Anchor and Release with informed consent. The rite cannot change memories, values, identity or loyalty or impose vulnerability.'}
    return None


@hook('fact_admission_validate')
def validate_rite_input(session, source, subject, kind, value):
    from ..journey import require
    if source != WEAVER:
        return
    if kind == 'heart_rite_consent':
        require(set(value) == {'consent', 'anchor', 'release'} and type(value['consent']) is int
            and value['consent'] in (0, 1) and type(value['anchor']) is str and type(value['release']) is str
            and value['anchor'] in ANCHORS and value['release'] in RELEASES,
            'Choose informed consent, one printed Heart Anchor and one printed Heart Release.')
    elif kind in ('deep_anchor_consent', 'release_anchor_consent'):
        require(set(value) == {'consent'} and type(value['consent']) is int and value['consent'] in (0, 1),
            'Record the target’s explicit informed consent or refusal.')


def rite_state(session, aid):
    state = session.state['actors'][aid].setdefault('source_states', {}).setdefault(STATE,
        {'rites': {}, 'anchors': {}, 'clock':int(session.clock()), 'journey_id':session.state['journey_id']})
    state.setdefault('anchors', {})
    return state


@hook('journey_command')
def rite_command(session, aid, kind, payload):
    from ..journey import require
    from ..fact_consent_admission import read
    if kind not in ('emotion_rite', 'emotion_deep_anchor', 'emotion_release_anchor'):
        return None
    require(set(payload) == {'target_id'} and payload['target_id'] in session.state['actors'],
        'Choose one creature in this journey.')
    target = payload['target_id']
    if kind == 'emotion_release_anchor':
        # The target owns this decision. Completion is a real cultivation
        # activity, with a native clock and its own consent declaration.
        require(target in rite_state(session, aid)['anchors'], 'Choose the creator of your existing Deep Heart Anchor.')
        held = rite_state(session, aid)['anchors'][target]
        require(held.get('deep') == 1, 'This is not a Deep Heart Anchor.')
        consent = read(session, WEAVER, aid, 'release_anchor_consent', target, aid)
        require(consent and consent['value']['consent'] == 1, 'The target must choose to release its own Deep Heart Anchor.')
        # Qi core R4 requires two uninterrupted hours, calm and sufficient
        # ambient spiritual energy (or an appropriate substitute).
        environment = read(session, WEAVER, aid, 'cultivation_environment', session.state['journey_id'], aid)
        require(environment and environment['value'] == 1 and environment['expires_at'] >= session.clock() + 7200,
            'The GM must record calm and sufficient spiritual energy for this two-hour Full Cultivation Session.')
        session.tick(7200)
        del rite_state(session, aid)['anchors'][target]
        session.emit('HEART_ANCHOR_RELEASED', aid, source=WEAVER, creator=target,
            consent_receipt=consent['receipt_id'], elapsed_seconds=7200,
            environment_receipt=environment['receipt_id'])
        return True
    require(journey_owns(session, aid, WEAVER), 'Acquire Heartweaver through its Restricted Scripture first.')
    require(not session.state['actors'][aid]['incapacitated'] and not session.state['actors'][target]['incapacitated'],
        'Both rite participants must be able to participate.')
    from ..gate2_runtime_models import Position
    require(session.grid.distance_ft(Position.model_validate(session.state['actors'][aid]['position']),
        Position.model_validate(session.state['actors'][target]['position'])) <= 5,
        'Perform this rite together, within 5 feet.')
    now = int(session.clock())
    scene = session.state.get('scene_id', session.state['journey_id'])
    outside = read(session, WEAVER, aid, 'outside_scene', scene, aid)
    duration = 3600 if kind == 'emotion_rite' else 25200
    require(outside and outside['value'] == 1 and outside['expires_at'] >= now + duration,
        'The GM must record that the full rite takes place outside a scene.')
    consent_kind = 'heart_rite_consent' if kind == 'emotion_rite' else 'deep_anchor_consent'
    consent = read(session, WEAVER, target, consent_kind, aid, aid)
    require(consent and consent['value']['consent'] == 1 and consent['expires_at'] >= now + duration,
        'The willing target must record informed consent and its own choices for this full rite.')
    actor = session.state['actors'][aid]
    price = 5 if kind == 'emotion_rite' else 10
    require(actor['resources'].get(QI, 0) >= price, f'This rite costs {price} Qi.')
    if kind == 'emotion_deep_anchor':
        previous = rite_state(session, target)['rites'].get(aid)
        require(previous is not None and previous['completed_at'] == now,
            'Continue directly from your completed one-hour Heart-Shaping Rite.')
    actor['resources'][QI] -= price
    session.emit('HEART_RITE_PAYMENT', aid, source=WEAVER, target=target, qi=price)
    session.tick(duration)
    if kind == 'emotion_rite':
        action = next(a for a in actor['bundle']['action_catalog'] if (a.get('parameters', {}).get('typed') or {}).get('source') == WEAVER)
        numbers = action['parameters']['typed']['numbers']
        rite_state(session, target)['rites'][aid] = {'anchor': consent['value']['anchor'],
            'release': consent['value']['release'], 'source_cl': int(numbers['cl']), 'pb': int(numbers['pb']),
            'completed_at': int(session.clock()), 'expires_at': int(session.clock()) + 28800,
            'deep': 0, 'consent_receipt': consent['receipt_id']}
    else:
        rite_state(session, target)['rites'][aid]['deep'] = 1
        rite_state(session, target)['rites'][aid]['deep_consent_receipt'] = consent['receipt_id']
        rite_state(session, target)['anchors'][aid] = {**rite_state(session, target)['rites'][aid], 'release': ''}
    session.emit('HEART_RITE_COMPLETED', aid, source=WEAVER, target=target,
        elapsed_seconds=duration, consent_receipt=consent['receipt_id'],
        anchor=rite_state(session, target)['rites'][aid]['anchor'])
    return True


@hook('journey_elapsed')
def expire_rites(session, aid, before, seconds, moving):
    state = session.state['actors'][aid].get('source_states', {}).get(STATE)
    if not state:
        return
    state['clock'] = int(session.clock())
    state['journey_id'] = session.state['journey_id']
    for owner, rite in list(state['rites'].items()):
        if rite['expires_at'] <= session.clock():
            del state['rites'][owner]
            session.emit('HEART_RITE_EXPIRED', aid, source=WEAVER, creator=owner)


@hook('journey_combat_setup')
def rite_setup(session, aid):
    state = session.state['actors'][aid].get('source_states', {}).get(STATE)
    if not state or not (state['rites'] or state.get('anchors')):
        return None
    import json
    return {'emotion_rites': json.dumps({'clock': int(session.clock()), 'rites': state['rites'],
        'anchors': state.get('anchors', {})}, sort_keys=True)}


@hook('match_initialize')
@hook('activity_initialize')
def initialize_rites(engine):
    import json
    for bundle in engine.typed_bundle_documents:
        raw = (bundle.get('journey_setup') or {}).get('emotion_rites')
        actor = engine.state.actors.get(bundle['actor_id'])
        if raw is None or actor is None:
            continue
        data = json.loads(raw)
        from .effect_durations import round_token
        rows = [(owner, rite, False) for owner, rite in data['rites'].items()]
        rows += [(owner, rite, True) for owner, rite in data.get('anchors', {}).items()]
        for owner, rite, permanent in rows:
            remaining = max(0, rite['expires_at'] - data['clock'])
            if not permanent and not remaining:
                continue
            # The anchor persists; Heart Release always ends after eight hours.
            engine._apply_condition(actor, 'condition:typed.heart_anchor', WEAVER, owner,
                expires_on='UNTIL_REMOVED' if permanent else round_token(engine, max(1, (remaining+5)//6)),
                data={**rite, 'deep': int(permanent),
                    'release_deadline': round_token(engine, max(1, (remaining+5)//6)) if remaining else '',
                    'label': 'Heart Anchor: ' + rite['anchor'].title(), 'permanent': int(permanent)})


@hook('save')
def heart_anchor_save(ctx, subject, ability, named):
    for held in subject.conditions.values():
        if held.condition_id == 'condition:typed.heart_anchor' and set(named).intersection(ANCHORS.get(held.data.get('anchor'), ())):
            return {'modes': ['ADVANTAGE']}
    return None


@hook('after_save_resolved')
def heart_anchor_release(ctx, subject, ability, named, failed):
    if failed:
        return
    from .effect_durations import due
    from .rider_choices import step
    for held in list(subject.conditions.values()):
        if held.condition_id != 'condition:typed.heart_anchor' or not set(named).intersection(ANCHORS.get(held.data.get('anchor'), ())):
            continue
        deadline = held.data.get('release_deadline')
        if not deadline or due(ctx.engine, deadline):
            continue
        release = held.data.get('release')
        if release == 'temporary_hp':
            ctx.engine._grant_temp_hp(subject, 2 * int(held.data['pb']), held.source_definition_id, held.source_actor_id)
        elif release == 'move':
            step(ctx.engine, subject, 'heart_anchor_release', 'Heart Anchor: Heart Release', subject, 10,
                held.source_definition_id, ctx.intent,
                trigger=f'{subject.display_name} succeeded on its Heart Anchor saving throw against {ctx.action.display_name}',
                ignored_oa=list(ctx.engine.state.actors))


@hook('skill_check_mode')
def sincere_emotion_check(ctx, subject, ability, skill):
    if str(skill).lower() not in ('insight', 'persuasion'):
        return None
    from .effect_durations import due
    from ..fact_consent_admission import admit_choice
    for held in list(subject.conditions.values()):
        if held.condition_id != 'condition:typed.heart_anchor' or held.data.get('release') != 'sincere_emotion' or held.data.get('release_check_used'):
            continue
        if not held.data.get('release_deadline') or due(ctx.engine, held.data['release_deadline']):
            continue
        fact = admit_choice(ctx, subject, WEAVER, 'sincere_communication', ctx.source,
            ['yes', 'no'], labels={'yes': 'This check communicates sincere emotion', 'no': 'It does not'},
            prompt=f'{subject.display_name}: is this {skill} check for {ctx.action.display_name} made to communicate sincere emotion? Heart Release grants Advantage on one such check; it reveals no private motive.',
            expires_on='END_OF_CURRENT_TURN', automatic_options=())
        if fact and fact['value'] == 'yes':
            ctx.engine._update_condition_data(subject, held, {**held.data, 'release_check_used': 1}, held.source_definition_id)
            return 'ADVANTAGE'
    return None


@hook('journey_initialize')
def rebase_rite_clock(session, aid):
    state = session.state['actors'][aid].get('source_states', {}).get(STATE)
    if not state:
        return
    old = state.get('clock', int(session.clock()))
    if state.get('journey_id') not in (None, session.state['journey_id']):
        for row in state['rites'].values():
            row['expires_at'] = int(session.clock()) + max(0, row['expires_at'] - old)
            row['completed_at'] = int(session.clock()) - max(0, old - row['completed_at'])
    state['journey_id'] = session.state['journey_id']
    state['clock'] = int(session.clock())


@hook('journey_scene_end')
def clear_emotion_scene(session, previous, current):
    import json
    from ..observer_information import READING
    from ..fact_consent_admission import CONDITION
    scene_conditions = {EXPOSURE, READING, CONDITION, 'condition:typed.heartweaver_scene'}
    source_ids = set(LEVELS)
    for actor in session.state['actors'].values():
        source_ids.update(a['source_definition_id'] for a in actor['bundle']['action_catalog']
            if (a.get('parameters', {}).get('typed') or {}).get('source') in LEVELS)
    for actor in session.state['actors'].values():
        snapshot = actor.get('encounter_snapshot')
        if snapshot:
            snapshot['conditions'] = {iid: raw for iid, raw in snapshot['conditions'].items()
                if not ((row := json.loads(raw))['condition_id'] in scene_conditions
                    and row['source_definition_id'] in source_ids)}


@hook('fact_admission_schema')
def emotional_source_schema(session, source, subject, kind):
    if source != PULSE or subject not in session.state['actors'] or kind not in ('emotional_traits', 'ordinary_emotional_impairment', 'emotional_escalation_sources'):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
        'description': 'The GM records an explicit Source Rule for a subjective emotional state, its actual immunity, or an acquired feature’s emotional escalation classification. Names, teams and damage never establish this fact.'}


@hook('fact_admission_validate')
def validate_emotional_source(session, source, subject, kind, value):
    from ..journey import require
    if source != PULSE:
        return
    require(type(value.get('source_reference')) is str and bool(value['source_reference'].strip()),
        'Record the controlling printed Source Rule reference.')
    if kind == 'emotional_traits':
        require(set(value) == {'source_reference','without_emotions','immunities'}
            and type(value['without_emotions']) is int and value['without_emotions'] in (0,1)
            and isinstance(value['immunities'],list) and all(type(s) is str for s in value['immunities'])
            and set(value['immunities']) <= {'emotion','mind','charmed','frightened'},
            'Record whether the creature lacks emotions, and only immunities its Source Rule actually grants. Lacking emotions alone grants no immunity.')
    elif kind == 'ordinary_emotional_impairment':
        require(set(value) == {'source_reference','category','source_cl','label'}
            and type(value['category']) is str and value['category'] in {'grief','panic','despair','shock','supernatural_agitation'}
            and type(value['source_cl']) is int and value['source_cl'] >= 1
            and type(value['label']) is str and bool(value['label'].strip()),
            'Record one ordinary emotional impairment, its actual Source CL and a plain description.')
    elif kind == 'emotional_escalation_sources':
        require(set(value) == {'source_reference','feature_ids'} and isinstance(value['feature_ids'],list)
            and all(type(s) is str for s in value['feature_ids']),
            'Record the actual acquired Source Rule IDs classified as emotional escalation.')
        actual = {(a.get('parameters',{}).get('typed') or {}).get('source')
            for a in session.state['actors'][subject]['bundle']['action_catalog']}
        require(set(value['feature_ids']) <= actual, 'Every classification must name a source this creature actually acquired.')


@hook('journey_combat_setup')
def emotional_sources_setup(session, aid):
    from ..fact_consent_admission import read
    import json
    records = []
    ended = set(((session.state['actors'][aid].get('source_states') or {}).get('emotion_native_continuation') or {}).get('ended_declaration_receipts', []))
    for kind in ('emotional_traits','ordinary_emotional_impairment','emotional_escalation_sources'):
        receipt = read(session, PULSE, aid, kind, session.state['journey_id'], aid)
        if receipt and receipt['receipt_id'] not in ended:
            records.append({'kind':kind,'value':receipt['value'],'receipt':receipt['receipt_id'],
                'authorized_readers':list(set([aid,*receipt['readers']])),
                'remaining':receipt['expires_at']-int(session.clock())})
    return {'emotion_sources':json.dumps(records, sort_keys=True)} if records else None


@hook('match_initialize')
@hook('activity_initialize')
def emotional_sources_initialize(engine):
    import json
    from .effect_durations import expiry_after_seconds
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        raw = (bundle.get('journey_setup') or {}).get('emotion_sources')
        if actor is None or raw is None:
            continue
        # A declaration owns one durable effect lifetime. A continued instance
        # restored from the same receipt is that lifetime, not a second one.
        live = {(held.data or {}).get('declaration_receipt') for held in actor.conditions.values()}
        for entry in json.loads(raw):
            if entry['receipt'] in live:
                continue
            value = entry['value']
            if entry['kind'] == 'emotional_traits':
                name = 'emotion_source_traits'
                data = {'rule':{'condition_immunities':value['immunities']},
                    'without_emotions':value['without_emotions'],'label':'Source-recorded emotional traits'}
            elif entry['kind'] == 'ordinary_emotional_impairment':
                name = 'ordinary_emotional_impairment'
                data = {'categories':[value['category']], 'source_cl':value['source_cl'],
                    'label':value['label'], 'secret':1,'authorized_readers':entry['authorized_readers']}
            else:
                name = 'emotion_source_classifications'
                data = {'feature_ids':value['feature_ids'], 'label':'Source-recorded emotional escalation classifications'}
            engine._apply_condition(actor, 'condition:typed.'+name, PULSE, actor.entity_id,
                expires_on=expiry_after_seconds(engine, entry['remaining']),
                data={**data,'source_reference':value['source_reference'],'declaration_receipt':entry['receipt']})


@hook('save_mode')
def native_emotional_save_mode(engine, subject, ability, dc, source_id, context):
    names = set(context.get('named') or [])
    if names.intersection({'charmed', 'frightened', 'category:emotion'}) and condition(subject, 'heartweaver'):
        return 'ADVANTAGE'
    for held in subject.conditions.values():
        if held.condition_id == 'condition:typed.heart_anchor' and names.intersection(ANCHORS.get(held.data.get('anchor'), ())):
            return 'ADVANTAGE'
    if names.intersection({'charmed', 'frightened'}):
        for owner, held in weather_sources(engine):
            if held.data['weather'] == 'sorrow' and subject.entity_id in held.data['allies'] and inside(engine, owner, held, subject):
                return 'ADVANTAGE'
    return None


@hook('journey_options')
def rite_options(session, aid):
    if session.state['phase'] != 'travel' or session.state.get('native_activity') is not None:
        return None
    out = []
    now = int(session.clock())
    for owner in session.state['actors']:
        if not journey_owns(session, owner, WEAVER):
            continue
        name = session.state['actors'][owner]['name']
        for anchor in ANCHORS:
            for release in RELEASES:
                out.append({'id': f'emotion:consent:{owner}:{anchor}:{release}', 'kind': 'declare_fact',
                    'label': f'Accept a one-hour Heart-Shaping Rite from {name}: {ANCHOR_TEXT[anchor]}; {RELEASE_TEXT[release]}. These benefits last 8 hours. The creator pays 5 Qi. No change to memories, values, identity or loyalty; no imposed vulnerability.',
                    'payload': {'source': WEAVER, 'subject': aid, 'kind': 'heart_rite_consent', 'scope': owner,
                        'value': {'consent': 1, 'anchor': anchor, 'release': release},
                        'expires_at': now + 86400, 'readers': [owner]}})
        out.append({'id': f'emotion:refuse:{owner}', 'kind': 'declare_fact',
            'label': f'Decline a Heart-Shaping Rite from {name}; grant no permission.',
            'payload': {'source': WEAVER, 'subject': aid, 'kind': 'heart_rite_consent', 'scope': owner,
                'value': {'consent': 0, 'anchor': 'courage', 'release': 'move'},
                'expires_at': now + 86400, 'readers': [owner]}})
        held = (session.state['actors'][aid].get('source_states', {}).get(STATE) or {}).get('rites', {}).get(owner)
        if held and not held['deep'] and held['completed_at'] == now:
            out.append({'id': f'emotion:deep_consent:{owner}', 'kind': 'declare_fact',
                'label': f'Consent to continue {name}’s rite for 7 more hours. The creator pays 10 Qi; only the chosen Heart Anchor becomes permanent. Your Heart Release keeps its original 8-hour duration.',
                'payload': {'source': WEAVER, 'subject': aid, 'kind': 'deep_anchor_consent', 'scope': owner,
                    'value': {'consent': 1}, 'expires_at': now + 86400, 'readers': [owner]}})
        permanent = (session.state['actors'][aid].get('source_states', {}).get(STATE) or {}).get('anchors', {}).get(owner)
        if permanent:
            out.append({'id': f'emotion:release_consent:{owner}', 'kind': 'declare_fact',
                'label': f'Choose to release your Deep Heart Anchor from {name} during a two-hour Full Cultivation Session. Requires a calm environment and sufficient spiritual energy.',
                'payload': {'source': WEAVER, 'subject': aid, 'kind': 'release_anchor_consent', 'scope': owner,
                    'value': {'consent': 1}, 'expires_at': now + 86400, 'readers': [aid]}})
            out.append({'id': f'emotion:release:{owner}', 'kind': 'emotion_release_anchor',
                'label': f'Complete the two-hour Full Cultivation Session and release your willing Deep Heart Anchor from {name}.',
                'payload': {'target_id': owner}})
    if journey_owns(session, aid, WEAVER):
        for target in session.state['actors']:
            out.append({'id': 'emotion:rite:' + target, 'kind': 'emotion_rite',
                'label': f'Perform a one-hour Heart-Shaping Rite with {session.state["actors"][target]["name"]}, outside a scene. Costs 5 Qi; requires that creature’s informed consent and choices.',
                'payload': {'target_id': target}})
            out.append({'id': 'emotion:deep:' + target, 'kind': 'emotion_deep_anchor',
                'label': f'Continue the completed Heart-Shaping Rite with {session.state["actors"][target]["name"]} for 7 additional hours. Costs 10 Qi; requires renewed informed consent.',
                'payload': {'target_id': target}})
    return out or None


def rest_emotional_options(session, aid):
    import json
    from ..gate2_runtime_models import ConditionInstance
    from .qi_subpaths_1 import EMOTIONS
    snapshot = session.state['actors'][aid].get('encounter_snapshot') or {}
    result = []
    for iid, raw in snapshot.get('conditions', {}).items():
        held = ConditionInstance.model_validate(json.loads(raw))
        if held.data.get('permanent') or (held.data.get('secret') and aid not in held.data.get('authorized_readers', [])):
            continue
        if set(held.data.get('categories', [])).intersection(EMOTIONS):
            result.append((iid, held))
    continued = ((session.state['actors'][aid].get('source_states') or {}).get('emotion_native_continuation') or {})
    for index, row in enumerate(continued.get('records', [])):
        if row.get('kind') != 'condition':
            continue
        held = ConditionInstance.model_validate_json(row['instance'])
        if held.data.get('declaration_receipt') and set(held.data.get('categories', [])).intersection(EMOTIONS):
            result.append((f'continued:{index}', held))
    return result


@hook('journey_options')
def heart_release_rest_options(session, aid):
    if session.state['phase'] != 'travel' or session.state.get('native_activity'):
        return None
    state = session.state['actors'][aid].get('source_states', {}).get(STATE) or {}
    options = []
    for owner, rite in state.get('rites', {}).items():
        if rite['release'] != 'short_rest' or rite['expires_at'] <= session.clock() + 3600:
            continue
        for iid, held in rest_emotional_options(session, aid):
            options.append({'id': f'emotion:rest_release:{owner}:{iid}', 'kind': 'emotion_release_short_rest',
                'label': f'Heart Release: complete a one-hour Short Rest and end {held.data.get("label") or "one ordinary emotional impairment"}. No Qi cost.',
                'payload': {'creator': owner, 'condition_instance_id': iid}})
    return options or None


@hook('journey_command')
def heart_release_rest(session, aid, kind, payload):
    if kind != 'emotion_release_short_rest':
        return None
    from ..journey import require
    require(set(payload) == {'creator','condition_instance_id'}, 'Choose the rite and one current ordinary emotional impairment.')
    state = rite_state(session, aid)
    rite = state['rites'].get(payload['creator'])
    require(rite and rite['release'] == 'short_rest' and rite['expires_at'] > session.clock() + 3600,
        'Heart Release must still be active after completing the one-hour Short Rest.')
    require(not session.state['actors'][aid]['incapacitated'], 'This creature cannot begin a Short Rest while incapacitated.')
    options = dict(rest_emotional_options(session, aid))
    iid = payload['condition_instance_id']
    require(iid in options, 'Choose one current ordinary emotional impairment that this creature knows about.')
    continued_index = int(iid.split(':', 1)[1]) if iid.startswith('continued:') else None
    if continued_index is None:
        previous = session.state['actors'][aid]['encounter_snapshot']['conditions'][iid]
    else:
        saved = session.state['actors'][aid]['source_states']['emotion_native_continuation']['records'][continued_index]
        previous = saved['instance']
    session.emit('SHORT_REST_STARTED', aid, source=WEAVER)
    session.tick(3600)
    if continued_index is None:
        snapshot = session.state['actors'][aid]['encounter_snapshot']
        require(snapshot['conditions'].get(iid) == previous, 'The impairment changed during this rest; refresh before ending it.')
        del snapshot['conditions'][iid]
    else:
        continued = session.state['actors'][aid]['source_states']['emotion_native_continuation']
        require(continued['records'][continued_index]['instance'] == previous,
            'The impairment changed during this rest; refresh before ending it.')
        ended = set(continued.get('ended_declaration_receipts', []))
        receipt = json.loads(previous)['data']['declaration_receipt']
        ended.add(receipt)
        continued['ended_declaration_receipts'] = sorted(ended)
        del continued['records'][continued_index]
    session.emit('SHORT_REST_COMPLETED', aid, source=WEAVER, elapsed_seconds=3600)
    session.emit('HEART_RELEASE_IMPAIRMENT_ENDED', aid, source=WEAVER, creator=payload['creator'],
        condition_instance_id=iid, previous_condition=previous)
    return True


@hook('opportunity_allowed')
def calm_short_move(engine, reactor, mover):
    from ..movement_steps import context
    route = context(engine, mover)
    if not route:
        return None
    moved = condition(mover, 'emotion_distance_this_turn')
    distance = int(moved.data['feet']) if moved else 0
    # A whole-route quote prevents dividing a long move into OA-free steps.
    if distance + int(route.get('remaining_ft') or 0) > 5:
        return None
    for owner, held in weather_sources(engine):
        if held.data['weather'] == 'calm' and mover.entity_id in held.data['allies'] and inside(engine, owner, held, mover):
            return False
    return None


@hook('movement_progress_committed')
def weather_distance(engine, mover, receipt):
    if not receipt['voluntary'] or not any(held.data['weather'] == 'calm' and mover.entity_id in held.data['allies']
            for _, held in weather_sources(engine)):
        return
    held = condition(mover, 'emotion_distance_this_turn')
    distance = int(held.data['feet']) if held else 0
    from .condition_ownership import remove_instance
    if held:
        remove_instance(engine, mover, held.instance_id, held.source_definition_id)
    engine._apply_condition(mover, 'condition:typed.emotion_distance_this_turn', WEATHER, mover.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'feet': distance + int(receipt['distance_ft']),
            'label': 'Movement covered this turn for Calm weather'})


@hook('effect_removal_allowed')
def heart_authority_end(engine, holder, kind, held, source):
    if kind != 'condition':
        return None
    if held.condition_id == 'condition:typed.heartweaver':
        weather = condition(holder, 'heart_weather')
        if weather and not weather.data.get('concentration'):
            from .effect_durations import due
            if due(engine, weather.expires_on):
                return None
            ctx = context_for(engine, holder, WEATHER)
            if ctx is None:
                return None
            selected = pick(ctx, holder, 'weather_concentration', ['maintain', 'end'],
                {'maintain': 'Maintain Weather of the Heart with Concentration; normal concentration limits apply',
                 'end': 'End Weather of the Heart'},
                'Heartweaver ends while Weather of the Heart still has time remaining. Maintain the weather with Concentration, or end it? No Qi cost.')
            if selected == ['maintain']:
                engine._start_concentration(holder, weather.source_definition_id)
                weather.data = {**weather.data, 'concentration': 1}
                engine._append_event('CONDITION_UPDATED', weather.source_definition_id,
                    actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                    payload={'instance_id': weather.instance_id, 'data': dict(weather.data)})
            else:
                from .condition_ownership import remove_instance
                remove_instance(engine, holder, weather.instance_id, weather.source_definition_id)
    if held.condition_id == 'condition:typed.heart_anchor' and held.data.get('deep'):
        action = engine.action_catalog.get(source)
        typed = action.parameters.get('typed') or {} if action else {}
        categories = set(typed.get('activation_categories') or [])
        level = (typed.get('numbers') or {}).get('cl')
        return bool(categories.intersection({'heart_cultivation', 'purification', 'sealing', 'identity'})
            and type(level) is int and level >= held.data['source_cl'])
    return None
