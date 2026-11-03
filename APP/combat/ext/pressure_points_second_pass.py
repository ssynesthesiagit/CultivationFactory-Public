"""Reviewed Pressure Points recovery, diagnosis and first-attack seal riders.

Only newly reviewed effects/Patient Hand rows opt in. All choices use the ordinary
checkpoint transport; state is evented, JSON-only and survives cold reload.
Shared helper API for pressure_points: grant_patient(engine, actor, intent)
asks for the perceived diagnostic subject after Focus is actually regained.

Unknown anatomy, hidden injuries, Hit Dice and narrative authority stay explicit
riders rather than being inferred from names or invented statistics.
"""
from dataclasses import replace

from . import effect, hook
from .condition_ownership import remove_instance
from .needle import ask, checkpoint_id, say

P = 'tianxia.talent.pressure_points.'
USED = 'condition:typed.pp_recovery_used.'
PATIENT = 'condition:typed.pp_patient_subject'
OPENING = 'condition:typed.pp_heartbeat_opening'
ROLL = 'pp_heartbeat_round_roll:'


def pick(ctx, who, key, options, labels, prompt, *, subject, **kw):
    """Keep the chooser separate from the creature affected by this decision.

    Use the actual delivery action, including a nested/off-turn attack, rather
    than the outer intent's actor when describing what triggered the question.
    """
    from .choice_prompt import action_context
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'pp2', key, who.entity_id),
               who, 'choice:needle.pp2.' + key, list(options), labels=labels,
               name=ctx.action.display_name, target_id=subject.entity_id, prompt=prompt,
               prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, subject, action=ctx.action), **kw)


def _used(subject, kind):
    return any(c.condition_id == USED + kind for c in subject.conditions.values())


def _mark_used(ctx, subject, kind, rest):
    ctx.engine._apply_condition(subject, USED + kind, ctx.source, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'label': f'{ctx.action.display_name}: already received this benefit; recharges after a {rest} rest'})


@hook('candidate_allowed')
def recovery_available(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    rows = list(typed.get('effects') or [])
    rows += [child for r in rows if r.get('type') == 'choose_willing' for child in r.get('effects') or []]
    kind = next((r.get('kind') for r in rows if r.get('type') == 'pp_recovery'), None)
    if kind:
        subjects = [engine.state.actors[t] for t in candidate.target_ids if t in engine.state.actors]
        return bool(subjects) and not any(_used(s, kind) for s in subjects)
    return None


@effect('pp_recovery', harmful=False)
def recovery(ctx, row):
    """Exactly one option; a recipient's limit is shared across all healers."""
    from .repeat_saves import repeatable, save_of
    from ..typed_executor import run_effects
    subject = ctx.target or ctx.actor
    kind = row['kind']
    if _used(subject, kind):
        return
    options, labels = {}, {}
    if kind == 'gentle':
        options['temp_hp'] = None
        labels['temp_hp'] = f'Gain {ctx.numbers["pb"]} Temporary HP'
        for name in ('poisoned', 'frightened'):
            for iid, held in repeatable(subject, (name,)):
                save = save_of(held)
                options['repeat:' + iid] = held
                labels['repeat:' + iid] = f'Repeat one {name.title()} saving throw (DC {save["dc"]})'
    else:
        for iid, held in subject.conditions.items():
            if held.condition_id in {'condition:typed.poisoned', 'condition:typed.frightened', 'condition:typed.paralyzed'}:
                # Protected restoration contracts are never silently bypassed.
                from .source_eligibility import ordinary_source
                if held.condition_id.endswith('paralyzed') and not ordinary_source(ctx.engine.action_catalog.get(held.source_definition_id)):
                    continue
                options['end:' + iid] = held
                labels['end:' + iid] = 'End one ' + held.condition_id.rsplit('.', 1)[-1].title() + ' condition'
    if not options:
        say(ctx.engine, ctx.source, ctx.actor, f'{ctx.action.display_name}: {subject.display_name} has no eligible condition this option can end.', (subject.entity_id,))
        return
    chosen = pick(ctx, subject, 'recovery', options, labels,
        f'{ctx.action.display_name}: {subject.display_name} may choose one benefit. This creature can benefit only once per '
        + ('short rest.' if kind == 'gentle' else 'long rest.'), subject=subject, allow_decline=True)
    if not chosen:
        return
    choice = chosen[0]
    if choice == 'temp_hp':
        run_effects(replace(ctx, targets=[subject], target=subject), [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
    elif choice.startswith('repeat:'):
        iid, held = choice[len('repeat:'):], options[choice]
        save = save_of(held)
        roll = ctx.engine._roll_save(subject, str(save['ability']).upper(), int(save['dc']), ctx.source,
            roll_context={'source_actor_id': held.source_actor_id, 'named': [held.condition_id.rsplit('.', 1)[-1]]})
        if roll is not None and roll.total >= int(save['dc']):
            remove_instance(ctx.engine, subject, iid, ctx.source)
    else:
        remove_instance(ctx.engine, subject, choice[len('end:'):], ctx.source)
    _mark_used(ctx, subject, kind, 'short' if kind == 'gentle' else 'long')


@effect('pp_diagnosis', harmful=False)
def diagnosis(ctx, row):
    """Roll the actual Medicine check and reveal only selected diagnostic facts."""
    from ..typed_executor import resolve_opposed_check, condition_rules
    subject = ctx.target
    if subject is None:
        return
    from .willing_targets import asks_consent
    from ..relations import relation, ALLY
    eligible = any(c.condition_id in {'condition:typed.incapacitated', 'condition:typed.restrained'}
                   or c.condition_id == 'condition:typed.grappled' and c.source_actor_id == ctx.actor.entity_id
                   for c in subject.conditions.values()) or any(r.get('no_actions') for r in condition_rules(subject))
    # Perception cannot supply willingness. Every otherwise ineligible recipient
    # controls consent, even when it cannot see or sense the caster.
    if not eligible and subject is not ctx.actor:
        if not asks_consent(ctx.engine, ctx.intent, subject, 'Pulse Diagnosis',
            f'{ctx.actor.display_name} offers Pulse Diagnosis: allow a Medicine check to read your body?',
            prefer_accept=relation(ctx.engine, subject, ctx.actor) == ALLY, asker=ctx.actor):
            return
    # The printed GM-set DC is an explicit table selection. The AI never reads
    # concealed anatomy to forecast it; it uses the ordinary-anatomy default.
    chosen = pick(ctx, ctx.actor, 'diagnosis_dc', ['10', '15', '20'],
        {'10': 'Ordinary anatomy: DC 10', '15': 'Unusual anatomy: DC 15',
         '20': 'Alien, spiritual, heavily transformed or concealed body: DC 20'},
        f'Pulse Diagnosis on {subject.display_name}: choose the agreed anatomy DC before rolling Medicine.', subject=subject, preferred=['10'])
    if not chosen:
        return
    result = resolve_opposed_check(ctx, subject,
        {'kind': 'check', 'ability': 'WIS', 'skill': 'Medicine', 'hazards': ['pressure_points']},
        {'kind': 'dc', 'dc': int(chosen[0]), 'label': 'Pulse Diagnosis'})
    names = {c.condition_id.rsplit('.', 1)[-1] for c in subject.conditions.values()}
    rules = condition_rules(subject)
    weakest = min(('STR', 'DEX', 'CON'), key=lambda a: (subject.saving_throws.get(a, 0), a))
    facts = {
        'illness': ('The body shows poison or disease.' if names & {'poisoned', 'diseased'} else 'No poison or disease is recorded.'),
        'mind': ('An obvious mind-affecting condition is present.' if names & {'charmed', 'frightened', 'stunned'} else 'No obvious mind-affecting condition is recorded.'),
        'impairment': ('Movement, speech, sight or grip is impaired.' if any(r.get(k) for r in rules for k in ('speed_zero', 'cant_see', 'no_actions', 'no_verbal'))
                       or names & {'restrained', 'grappled', 'silenced', 'blinded', 'paralyzed'} or any(m.target_field in {'speed_ft', 'speed_halved'} and (m.target_field == 'speed_halved' or int(m.value) < 0) for m in subject.modifiers.values())
                       else 'No impairment of movement, speech, sight or grip is recorded.'),
        'weakest': {'STR': 'Strength', 'DEX': 'Dexterity', 'CON': 'Constitution'}[weakest] + ' appears most vulnerable to pressure-point disruption.',
        'safe': 'A shallow point can numb pain or release breath without dulling awareness.',
    }
    count = 2 if result.success else 1
    selected = pick(ctx, ctx.actor, 'diagnosis_facts', list(facts),
        {'illness': 'Poison or disease', 'mind': 'Obvious mind-affecting condition',
         'impairment': 'Impaired body functions', 'weakest': 'Weakest physical saving throw', 'safe': 'A safe pressure point'},
        f'Pulse Diagnosis: {"success" if result.success else "failure"}; choose {count} diagnostic '
        + ('facts.' if result.success else 'detail. It is true but does not describe the whole body.'), subject=subject, minimum=count, maximum=count)
    for name in selected:
        say(ctx.engine, ctx.source, ctx.actor, f'Pulse Diagnosis — {subject.display_name}: {facts[name]}', (subject.entity_id,),
            details={'diagnosis': name, 'success': result.success})


@hook('contest_check_mode')
def patient_check(ctx, subject, opponent, spec):
    if subject is not ctx.actor or 'pressure_points' not in (spec.get('hazards') or []):
        return None
    if (spec.get('kind'), spec.get('ability'), spec.get('skill')) != ('check', 'WIS', 'Medicine'):
        return None
    if not any(r.get('type') == 'pp_diagnosis' for r in ctx.typed.get('effects') or []):
        return None
    if any(c.condition_id == PATIENT and c.data.get('subject') == opponent.entity_id for c in subject.conditions.values()):
        return 'ADVANTAGE'
    return None


def grant_patient(engine, actor, intent):
    from ..senses import perceives
    from ..relations import relation, ENEMY
    options = [s.entity_id for s in engine.state.actors.values() if s.active
               and engine._distance_actor_to_actor(actor, s) <= 30 and perceives(engine, actor, s)]
    enemies = [t for t in options if relation(engine, actor, engine.state.actors[t]) == ENEMY]
    selected = ask(engine, intent, checkpoint_id(engine, 'pp_patient', actor.entity_id), actor,
        'choice:needle.pp2.patient', options, automatic_options=enemies, preferred=enemies,
        labels={t: engine.state.actors[t].display_name for t in options}, name='Patient Hand',
        prompt='Patient Hand: choose one perceived creature within 30 feet. Your next Medicine, Sleight of Hand or Cultivation check to read or touch its pressure points has Advantage before the end of your next turn.')
    if selected:
        for held in list(actor.conditions.values()):
            if held.condition_id == PATIENT:
                remove_instance(engine, actor, held.instance_id, P + 'patient_hand')
        from .effect_durations import token
        engine._apply_condition(actor, PATIENT, P + 'patient_hand', actor.entity_id,
            expires_on=token('end', actor.entity_id, actor.turns_started + 1), data={'subject': selected[0],
                'label': 'Patient Hand: Advantage on the next pressure-point check about ' + engine.state.actors[selected[0]].display_name})


@hook('event')
def consume_patient(engine, event_type, kwargs):
    if event_type != 'CHECK_ROLLED' or (kwargs.get('payload') or {}).get('skill') not in {'Medicine', 'Sleight of Hand'}:
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    action = engine.action_catalog.get(kwargs.get('source_definition_id'))
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if actor is None or not any(r.get('type') == 'pp_diagnosis' for r in typed.get('effects') or []):
        return
    for held in list(actor.conditions.values()):
        if held.condition_id == PATIENT and held.data.get('subject') in (kwargs.get('target_ids') or ()):
            remove_instance(engine, actor, held.instance_id, P + 'patient_hand')


@effect('pp_heartbeat_opening')
def heartbeat_opening(ctx, row):
    from ..typed_executor import effect_expiry
    for subject in ctx.targets:
        picked = pick(ctx, ctx.actor, 'heartbeat_damage', ['force', 'psychic'],
            {'force': '6d10 Force damage on the next attack if it hits', 'psychic': '6d10 Psychic damage on the next attack if it hits'},
            f'The Point Between Heartbeats: choose the damage type of the opening on {subject.display_name}.', subject=subject) if row.get('damage') else ['force']
        ctx.engine._apply_condition(subject, OPENING, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, subject, condition=True),
            data={'damage': bool(row.get('damage')), 'damage_type': picked[0],
                  'label': 'The next attack against this creature has Advantage' + (' and adds 6d10 on a hit' if row.get('damage') else '')})


@hook('event')
def heartbeat_roll(engine, event_type, kwargs):
    if event_type != 'ATTACK_ROLLED':
        return
    payload = kwargs.get('payload') or {}
    for tid in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        for held in list(target.conditions.values()):
            if held.condition_id != OPENING or target.turn_flags.get(ROLL + held.instance_id):
                continue
            if not payload.get('provisional_hit'):
                remove_instance(engine, target, held.instance_id, held.source_definition_id)
            else:
                target.turn_flags[ROLL + held.instance_id] = str(payload.get('roll_id') or '')


@hook('attack_packet_start')
def heartbeat_damage(engine, target, amount, provenance):
    if provenance.component != 'primary':
        return
    from ..typed_executor import Context, run_effects
    attacker = engine.state.actors.get(provenance.attacker_id)
    action = engine.action_catalog.get(provenance.source_id)
    if attacker is None or action is None:
        return
    for held in list(target.conditions.values()):
        if held.condition_id != OPENING or target.turn_flags.get(ROLL + held.instance_id) != provenance.roll_id:
            continue
        remove_instance(engine, target, held.instance_id, held.source_definition_id)
        target.turn_flags.pop(ROLL + held.instance_id, None)
        if not held.data.get('damage'):
            continue
        typed = (action.parameters or {}).get('typed') or {}
        ctx = Context(engine, attacker, action, engine._active_intent, typed, [target], target,
                      attack_damage_context=provenance, critical_hit=provenance.critical and not provenance.critical_cancelled)
        run_effects(ctx.on_hit_context(target), [{'type': 'extra_damage', 'applies_to': 'target',
            'dice': {'count': 6, 'sides': 10, 'modifier': 0}, 'damage_types': [held.data['damage_type']]}])


def heartbeat_finish(ctx, target, effect, roll_id):
    if not roll_id:
        return
    for held in list(target.conditions.values()):
        if held.condition_id == OPENING and target.turn_flags.get(ROLL + held.instance_id) == roll_id:
            remove_instance(ctx.engine, target, held.instance_id, held.source_definition_id)
            target.turn_flags.pop(ROLL + held.instance_id, None)


@hook('attack_result')
def heartbeat_settled_roll(ctx, target, hit, critical):
    # The typed roll scope ends before hit_final. Keep a confirmed no-damage
    # hit's opening until that hook can deliver its bonus; settled misses end it.
    if not hit:
        heartbeat_finish(ctx, target, {}, (ctx.attack_result or {}).get('roll_id'))


@hook('hit_final')
def heartbeat_no_primary_packet(ctx, target, kind):
    """A confirmed hit with no ordinary damage still earns its sealed bonus."""
    provenance = ctx.attack_damage_context
    if provenance is not None:
        heartbeat_damage(ctx.engine, target, 0, provenance)


@effect('pp_heaven_gate')
def heaven_gate(ctx, row):
    from ..typed_executor import condition_immune, run_effects
    if ctx.target is None:
        return
    if row.get('failed') and not condition_immune(ctx.engine, ctx.target, 'stunned'):
        run_effects(ctx, [{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target', 'duration': 'until_start_of_your_next_turn'}])
    else:
        run_effects(ctx, [{'type': 'pp_dazed', 'applies_to': 'target'}])


@effect('pp_stolen_step')
def stolen_step(ctx, row):
    from .rider_step import step
    feet = 10
    if ctx.damage_cache.get('pp_preexisting_mark:' + ctx.target.entity_id):
        chosen = pick(ctx, ctx.actor, 'step_distance', ['10', 'half_speed'],
            {'10': 'Move up to 10 feet', 'half_speed': 'Move up to half your Speed'},
            f'Stolen Pulse Step: your {ctx.action.display_name} hit {ctx.target.display_name}, who already bore your Pressure Point before the hit. Choose your movement allowance.', subject=ctx.target)
        if chosen == ['half_speed']:
            feet = ctx.engine._effective_speed(ctx.actor) // 2
    step(ctx, {'distance_ft': feet, 'no_oa_from_target': True, 'label': 'Stolen Pulse Step'})


@hook('compile_action')
def diagnosis_target_kind(action, info):
    if any(r.get('type') == 'pp_diagnosis' for r in ((action.parameters or {}).get('typed') or {}).get('effects') or []):
        return action.model_copy(update={'target_kind': 'ANY_CREATURE'})
    return None


@hook('choice_reactors')
def second_pass_choosers(engine):
    def owns(value):
        if isinstance(value, dict):
            return value.get('type') in {'pp_recovery', 'pp_diagnosis', 'pp_heartbeat_opening'} or any(owns(v) for v in value.values())
        return isinstance(value, (list, tuple)) and any(owns(v) for v in value)
    if any(owns((a.parameters or {}).get('typed') or {}) for a in engine.action_catalog.values()) or any(
        r.get('second_pass') for rows in engine.typed_passive_rows.values() for r in rows if r.get('block') == 'pp_patient_hand'):
        return tuple(engine.state.actors)
    # Off-turn choices can live in sealed passive delivery rows, not just in
    # action effects. Enroll their owners without requiring Ask-me reactions or
    # another ability to happen to enroll them. The service filters manual control.
    return tuple(actor_id for actor_id, rows in engine.typed_passive_rows.items()
                 if any(r.get('block') == 'shi_pp_point' and any(
                     e.get('type') == 'pp_stolen_step' for e in r.get('point_effects') or []) for r in rows))


@hook('ai_candidate_allowed')
def recovery_ai_side(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if any(r.get('type') == 'choose_willing' and any(e.get('type') == 'pp_recovery' for e in r.get('effects') or [])
           for r in typed.get('effects') or []):
        from ..relations import relation, ALLY
        return all(relation(engine, actor, engine.state.actors[t]) == ALLY for t in candidate.target_ids)
    return None


@effect('pp_tap_reduction')
def tap_reduction(ctx, row):
    """Intercepting Tap parks its chosen outcome on the still-pending melee hit."""
    if ctx.target is None:
        return
    from .attack_reduction import park
    amount = int(ctx.numbers.get('pb') or ctx.actor.proficiency_bonus) if row.get('hit') else 1
    park(ctx.actor, ctx.target.entity_id, amount, P + 'intercepting_tap', engine=ctx.engine)


@hook('after_miss')
def heartbeat_native_miss(ctx, target):
    """Settled native post-roll defenses also consume the first-roll opening."""
    from .attack_scope import current
    frame = current(ctx.engine)
    roll_id = getattr(ctx.attack_notice, 'roll_id', '') or (frame['roll_id'] if frame else '')
    if roll_id:
        heartbeat_finish(ctx, target, {}, roll_id)


@hook('hit_snapshot')
def point_before_hit(engine, attacker, target, attack_context, intent):
    """Sample before damage and on-hit riders can create a fresh mark."""
    rows = engine.typed_passive_rows.get(attacker.entity_id, [])
    if not any(any(e.get('type') == 'pp_stolen_step' for e in r.get('point_effects') or []) for r in rows):
        return None
    from ..typed_executor import bears_mark
    return {'pp_preexisting_point': {'owner': attacker.entity_id, 'target': target.entity_id,
                                    'marked': bears_mark(target, attacker.entity_id, 'Pressure Point')}}
