"""Nudge Consequence's final outcomes, finite Echoes and Refuse Certainty.

Uses native roll_resolution, recipient consent and recorded_facts. This module
owns no other Fate Reader feature and installs no runtime wrappers.
"""
from . import effect, hook, note
from . import spirit_traditions as st

NUDGE = 'tianxia.tradition.spirit.fate_reader.feature.nudge_consequence'
ECHO = 'condition:typed.nudge_named_echo'
COUNTER = 'condition:typed.nudge_counter_omen'
COUNTER_USED = 'condition:typed.nudge_counter_omen_used'
ONCE = 'condition:typed.nudge_refused_certainty'
RESONANCE = 'resource:core.resonance'
TENSION = 'resource:named.fate_tension'
STAKES = {key: label for key, label in (
    ('major_enemy', 'Major enemy'), ('secret_law', 'Secret Law'), ('divine', 'Divine agent'),
    ('artifact', 'Artifact'), ('tribulation', 'Tribulation'), ('fate_protected', 'Fate-protected creature'),
    ('breakthrough', 'Breakthrough'), ('permanent_injury', 'Permanent injury'), ('identity', 'Identity-scale effect'))}
from .fate_perception import register_source
register_source('tianxia.tradition.spirit.fate_reader.feature.read_the_thread')
ECHOS = {
    'reversal': 'Reversal: the next time you change a d20 roll, roll twice and use the result farther from 10',
    'witness': 'Witness: the affected creature learns that the roll was changed and the broad direction it came from',
    'delayed_cost': 'Delayed Cost: at the end of this scene, lose Resonance equal to your Proficiency Bonus; if you lack enough, gain 1 Fate Tension',
    'narrowed_branch': 'Narrowed Branch: you cannot change this creature’s rolls again this scene',
    'borrowed_misfortune': 'Borrowed Misfortune: before the end of your next turn, your next ordinary saving throw cannot have Advantage',
    'marked_cause': 'Marked Cause: until this scene ends, creatures with equally strong or stronger magic-sensing can recognize the involved creature or object',
}


@hook('feature_access_source')
def nudge_sphere_access(sheet, record_id, mechanic):
    if record_id != NUDGE:
        return None
    known = set((sheet.get('spheres_and_talents') or {}).get('sphere_record_ids') or [])
    for key, name in (('tianxia.sphere.fate', 'Fate'), ('tianxia.sphere.karma', 'Karma')):
        if key in known:
            return f'Known {name} Sphere'
    return None


def _remove(engine, actor, held, *, resolved=False):
    st.remove(engine, actor, held, 'RESOLVED' if resolved else 'EXPIRED')
    if resolved and not held.data.get('tension_relieved') and actor.resources.get(TENSION, 0):
        engine._spend_resource(actor, TENSION, 1, NUDGE)


def counter_omen(engine, reader):
    """Nudge's first alteration while Fate-Tangled creates one token per scene."""
    from .fate_reader import tangled
    if not tangled(reader) or any(c.condition_id == COUNTER_USED for c in reader.conditions.values()):
        return
    for condition, label in ((COUNTER, 'Counter-Omen: Disadvantage on your next Cultivation Check or saving throw this scene'),
                             (COUNTER_USED, 'Counter-Omen created this scene')):
        engine._apply_condition(reader, condition, NUDGE, reader.entity_id, expires_on='UNTIL_REMOVED', data={'label': label})


def stage_roll(engine, reader, rc, roll, bonus, *, refused_outcome=None, categories_snapshot=None):
    """Correlate a paid Nudge/refusal with its one native final consumer."""
    from ..paid_relocation import preserve_pending
    from .recorded_facts import categories
    if categories_snapshot is None:
        categories_snapshot = sorted({category for actor in (rc.roller, rc.target, rc.source_actor) if actor is not None
                                      for category in categories(actor) if category in STAKES})
    preserve_pending(engine, '_nudge_outcomes')
    pending = engine.__dict__.setdefault('_nudge_outcomes', {}).setdefault(roll.roll_id, [])
    old = next((item for item in pending if item['reader'] == reader.entity_id), None)
    data = {'reader': reader.entity_id, 'bonus': bonus, 'natural': int(roll.natural_result or 0),
            'categories': categories_snapshot, 'context': engine.d20_context(roll) or {}}
    if refused_outcome is not None:
        data['refused_outcome'] = refused_outcome
    if old is None:
        pending.append(data)
    else:
        old.update(data)


@hook('d20_altered')
def nudge_reversal(engine, roll, alteration, intent):
    actor = engine.state.actors.get(alteration.get('user_id'))
    if actor is None:
        return None
    held = next((c for c in actor.conditions.values() if c.condition_id == ECHO and c.data.get('echo') == 'reversal'), None)
    if held is None:
        return None
    draws = [roll, engine.roller.raw_d20(modifier=roll.modifier, actor_id=roll.actor_id, reason=roll.reason, mode=roll.mode)]
    chosen = max(draws, key=lambda r: abs(int(r.natural_result) - 10))
    result = chosen.model_copy(update={'roll_id': roll.roll_id, 'counter_start': roll.counter_start})
    engine.state.roll_counter = engine.roller.counter
    _remove(engine, actor, held, resolved=True)
    engine._append_event('D20_REWRITTEN', NUDGE, actor_id=roll.actor_id,
        payload={'operation': 'reversal', 'original': roll.model_dump(mode='json'),
                 'draws': [r.model_dump(mode='json') for r in draws], 'result': result.model_dump(mode='json'),
                 'user_id': actor.entity_id})
    return result


@hook('fate_perception')
def nudge_marked_cause(engine, observer, subject, source_cl):
    from .fate_perception import subject_id, subject_name
    for owner in engine.state.actors.values():
        for held in owner.conditions.values():
            if (held.condition_id == ECHO and held.data.get('echo') == 'marked_cause'
                    and held.data.get('subject') == subject_id(subject) and source_cl >= held.data['source_cl']):
                return {'subject_id': subject_id(subject), 'source_actor_id': owner.entity_id,
                        'description': f"{subject_name(subject)}'s fate signature is legible after Nudge Consequence."}
    return None


@hook('compile_actions')
def nudge_records(info):
    if NUDGE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    def action(suffix, name, effects, target='SELF'):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.nudge_{suffix}",
            display_name=name, owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind=target, range_ft=60,
            parameters={'typed': {'effects': effects, 'numbers': info['numbers'], 'source': NUDGE,
                                  'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0})
    return [action('stakes', 'Record the stakes for Nudge Consequence',
                   [{'type': 'record_subject_fact', 'applies_to': 'target', 'categories': STAKES,
                     'category_scopes': {key: 'next_roll' for key in ('secret_law', 'artifact', 'tribulation', 'breakthrough', 'permanent_injury', 'identity')}}], 'ANY_CREATURE')]


@hook('roll_resolved')
def nudge_resolved(engine, roll, success, frame, intent):
    from ..paid_relocation import preserve_pending
    from .fate_reader import gain_tension
    from . import needle
    preserve_pending(engine, '_nudge_outcomes')
    pending = engine.__dict__.setdefault('_nudge_outcomes', {}).pop(roll.roll_id, [])
    for item in pending:
        reader = engine.state.actors.get(item['reader'])
        roller = engine.state.actors.get(roll.actor_id)
        if reader is None or roller is None:
            continue
        context = {**item['context'], **frame}
        natural_fixed = context.get('check_kind') == 'death_save' and roll.natural_result in (1, 20)
        if frame.get('fixed') and not natural_fixed:
            continue
        baseline = roll.total - item['bonus'] - (int(roll.natural_result or 0) - item['natural'])
        if context.get('kind') == 'attack':
            from ..critical_attacks import hits
            if context.get('ac') is None:
                continue
            before = hits(item['natural'], baseline, context['ac'], (context.get('spec') or {}).get('critical_threshold', 20))
        else:
            if context.get('dc') is None:
                continue
            if context.get('check_kind') == 'death_save' and item['natural'] in (1, 20):
                before = item['natural'] == 20
            else:
                before = baseline >= context['dc']
        modifier_flipped = before != success
        refusal_flipped = item.get('refused_outcome') is not None and (item['refused_outcome'] == 'success') != success
        if not modifier_flipped and not refusal_flipped:
            continue
        if modifier_flipped:
            gain_tension(engine, reader, 1, NUDGE)
        involved = [roller]
        if reader not in involved:
            involved.append(reader)
        for key in ('target_id', 'source_actor_id'):
            actor = engine.state.actors.get(context.get(key))
            if actor is not None and actor not in involved:
                involved.append(actor)
        consequential = context.get('check_kind') == 'death_save' or bool(item.get('categories'))
        if not consequential:
            continue
        options = ['tension', *ECHOS]
        selected = needle.ask(engine, intent, needle.checkpoint_id(engine, 'NUDGE_ECHO', roll.roll_id), reader,
            'choice:needle.fate_reader.echo', options, labels={'tension': 'Gain 1 additional Fate Tension', **ECHOS},
            preferred=['tension'], name='Nudge Consequence: Consequence Echo', feature_id=NUDGE, target_id=roller.entity_id,
            prompt=f"Nudge Consequence changed the result of {roller.display_name}'s {context.get('kind', 'triggering')} roll. Gain 1 additional Fate Tension (a resource for fate powers) or state one Named Echo complication now. It lasts until resolved or the end of the next scene.")
        choice = selected[0] if selected else 'tension'
        if choice == 'tension':
            gain_tension(engine, reader, 1, NUDGE)
            continue
        subject = reader if choice in ('reversal', 'delayed_cost', 'borrowed_misfortune') else roller
        if choice == 'witness' and len(involved) > 1:
            ids = [a.entity_id for a in involved]
            preferred_subject = context.get('target_id') if context.get('kind') == 'attack' else roller.entity_id
            picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'NUDGE_WITNESS', roll.roll_id), reader,
                'choice:needle.fate_reader.witness', ids, labels={a.entity_id: a.display_name for a in involved},
                preferred=[preferred_subject] if preferred_subject in ids else [roller.entity_id],
                name='Witness: creature most affected', target_id=roller.entity_id,
                prompt='Choose the creature most affected by Nudge Consequence. It learns that your reaction changed its roll and the broad direction the change came from.')
            subject = engine.state.actors[picked[0]]
        if choice == 'marked_cause':
            from .fate_perception import subject_id, subject_name
            from ..senses import perceives_object
            objects = [engine.state.objects[key] for key in context.get('object_ids') or []
                       if key in engine.state.objects and perceives_object(engine, reader, engine.state.objects[key])]
            possible = {subject_id(a): a for a in [*involved, *objects]}
            ids = list(possible)
            picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'NUDGE_CAUSE', roll.roll_id), reader,
                'choice:needle.fate_reader.cause', ids, labels={key: subject_name(a) for key, a in possible.items()},
                preferred=[roller.entity_id], name='Marked Cause', target_id=roller.entity_id,
                prompt='Choose a creature, object, or magical anchor directly involved in the changed roll. Until this scene ends, creatures with equally strong or stronger magic-sensing can recognize it.')
            subject = possible[picked[0]]
        from .fate_perception import subject_id, subject_name
        from ..scene_boundaries import serial as scene_serial
        engine._apply_condition(reader, ECHO, NUDGE, reader.entity_id, expires_on='UNTIL_REMOVED',
            data={'echo': choice, 'subject': subject_id(subject), 'turn': reader.turns_started,
                  'scene': scene_serial(engine), 'source_cl': int(st.numbers(engine, reader)['cl']),
                  'tension_relieved': 1,
                  'label': f"{ECHOS[choice]} — subject: {subject_name(subject)}; ends by the end of the next scene"})
        # The printed alternative is to *accept* the Echo. That willingly
        # accepted complication removes one tension now; resolution cannot pay twice.
        if reader.resources.get(TENSION, 0):
            engine._spend_resource(reader, TENSION, 1, NUDGE)
        engine._append_event('PASSIVE_TRIGGERED', NUDGE, actor_id=reader.entity_id, target_ids=(subject_id(subject),),
            payload={'log': f"Named Echo — {ECHOS[choice]}. Subject: {subject_name(subject)}."})
        if choice == 'witness':
            dx, dy = reader.position.x - subject.position.x, reader.position.y - subject.position.y
            direction = ('east' if dx > 0 else 'west') if abs(dx) >= abs(dy) and dx else ('south' if dy > 0 else 'north') if dy else 'here'
            engine._apply_condition(subject, 'condition:typed.fate_witness', NUDGE, reader.entity_id,
                expires_on='UNTIL_REMOVED', data={'direction': direction, 'label': f"Fate was altered; its source was broadly {direction}"})
            held = next(c for c in reversed(list(reader.conditions.values())) if c.condition_id == ECHO and c.data.get('echo') == choice)
            _remove(engine, reader, held, resolved=True)


@hook('save_mode')
def nudge_save_mode(engine, target, ability, dc, source, context):
    for c in list(target.conditions.values()):
        if c.condition_id == COUNTER:
            st.remove(engine, target, c, 'CONSUMED')
            return 'DISADVANTAGE'


@hook('check_roll_mode')
def nudge_check_mode(engine, actor, context):
    if context.get('check_kind') != 'cultivation':
        return None
    for c in list(actor.conditions.values()):
        if c.condition_id == COUNTER:
            st.remove(engine, actor, c, 'CONSUMED')
            return 'DISADVANTAGE'


@hook('ordinary_favorable_coincidence')
def nudge_counter_coincidence(engine, beneficiary, source):
    held = next((c for c in beneficiary.conditions.values() if c.condition_id == COUNTER), None)
    if held is not None:
        st.remove(engine, beneficiary, held, 'CONSUMED')
        note(engine, NUDGE, beneficiary, 'Counter-Omen: the ordinary favorable coincidence fails; it creates no new penalty.')
        return False
    return None


@hook('save_advantage_allowed')
def nudge_misfortune(engine, actor, ability):
    if ability == 'DEATH':
        return None
    return False if any(c.condition_id == ECHO and c.data.get('echo') == 'borrowed_misfortune'
                        for c in actor.conditions.values()) else None


@hook('d20_finalized')
def nudge_misfortune_consumed(engine, roll, intent):
    context = engine.d20_context(roll) or {}
    if context.get('kind') != 'save' or context.get('check_kind') == 'death_save':
        return
    actor = engine.state.actors.get(roll.actor_id)
    if actor is not None:
        for held in list(actor.conditions.values()):
            if held.condition_id == ECHO and held.data.get('echo') == 'borrowed_misfortune':
                _remove(engine, actor, held, resolved=True)


@hook('turn_end')
def nudge_echo_turn(engine, actor):
    for held in list(actor.conditions.values()):
        if held.condition_id == ECHO and held.data.get('echo') == 'borrowed_misfortune' and actor.turns_started > held.data['turn']:
            _remove(engine, actor, held)


@hook('scene_ended')
def nudge_echo_scene(engine, serial):
    from .fate_reader import gain_tension
    interested = False
    for actor in engine.state.actors.values():
        interested = interested or st.row(engine, actor, 'nudge_consequence') is not None
        for held in list(actor.conditions.values()):
            interested = interested or held.condition_id in (ECHO, COUNTER, COUNTER_USED, ONCE)
            if held.condition_id == COUNTER:
                gain_tension(engine, actor, 1, NUDGE)
                st.remove(engine, actor, held, 'EXPIRED')
            elif held.condition_id in (ONCE, COUNTER_USED):
                st.remove(engine, actor, held, 'EXPIRED')
            elif held.condition_id == ECHO:
                echo = held.data['echo']
                if echo == 'delayed_cost':
                    cost = int(st.numbers(engine, actor)['pb'])
                    if actor.resources.get(RESONANCE, 0) >= cost:
                        engine._spend_resource(actor, RESONANCE, cost, NUDGE)
                    else:
                        gain_tension(engine, actor, 1, NUDGE)
                    _remove(engine, actor, held, resolved=True)
                elif echo in ('narrowed_branch', 'marked_cause'):
                    _remove(engine, actor, held, resolved=True)
                elif serial > int(held.data['scene']):
                    _remove(engine, actor, held)
    return True if interested else None


@hook('automatic_result')
def nudge_refuse(engine, target, context, intent):
    from . import needle
    from ..paid_relocation import activation, preserve_pending
    if context.get('source_cl') is None:
        return None
    for reader in engine.state.actors.values():
        if (st.row(engine, reader, 'nudge_consequence') is None or not st.can_react(reader)
                or reader.resources.get(RESONANCE, 0) < 6 or engine._distance_actor_to_actor(reader, target) > 60
                or any(c.condition_id == ONCE for c in reader.conditions.values())):
            continue
        if any(c.condition_id == ECHO and c.data.get('echo') == 'narrowed_branch'
               and c.data.get('subject') == target.entity_id for c in reader.conditions.values()):
            continue
        from .recorded_facts import source_authority
        authority = source_authority(engine, intent, reader, target, context)
        if authority is None:
            continue
        ours = reader.team_id == target.team_id
        prefer = ours == (context['outcome'] == 'failure')
        source_action = engine.action_catalog.get(context.get('source_id'))
        trigger_name = source_action.display_name if source_action is not None else 'the triggering effect'
        choice = needle.ask(engine, intent, needle.checkpoint_id(engine, 'REFUSE_CERTAINTY', context['source_id']),
            reader, 'choice:needle.fate_reader.refuse', ['refuse'],
            labels={'refuse': 'Refuse Certainty: Reaction, 6 Resonance total; require a normal roll (once this scene)'},
            preferred=['refuse'] if prefer else [], allow_decline=True, automatic=prefer,
            default='first' if prefer else 'decline', name='Nudge Consequence: Refuse Certainty', feature_id=NUDGE,
            target_id=target.entity_id, prompt=f"{target.display_name} would automatically {context['outcome']} {trigger_name}. Spend 4 Resonance plus 2 additional Resonance to refuse certainty? Equal or higher authority requires a Cultivation Check contest.")
        if not choice:
            continue
        with activation(engine, reader, NUDGE):
            engine._spend_resource(reader, RESONANCE, 6, NUDGE)
            reader.reaction_available = False
            engine._append_event('REACTION_RESOLVED', NUDGE, actor_id=reader.entity_id, target_ids=(target.entity_id,),
                payload={'checkpoint': 'AUTOMATIC_RESULT', 'reaction_name': 'Nudge Consequence: Refuse Certainty'})
            engine._apply_condition(reader, ONCE, NUDGE, reader.entity_id, expires_on='UNTIL_REMOVED',
                data={'label': 'Refuse Certainty used this scene'})
            passed = authority == 'ordinary' and int(context['source_cl']) < int(st.numbers(engine, reader)['cl'])
            if not passed:
                source = engine.state.actors.get(context.get('source_actor_id'))
                if source is None:
                    note(engine, NUDGE, reader, 'Refuse Certainty cannot contest an authority whose source is unknown.', (target,))
                    continue
                from ..typed_executor import resolve_opposed_check
                ctx = st.context(engine, reader, st.feature_action(engine, reader, NUDGE), [source], st.numbers(engine, reader))
                # Paid Reactions and each reader's scene receipt bound nested
                # refusals; a global guard would cut other readers' legal choices.
                passed = resolve_opposed_check(ctx, source, {'kind': 'cultivation'}, {'kind': 'cultivation'}).success
            if passed:
                preserve_pending(engine, '_nudge_prepaid')
                engine.__dict__.setdefault('_nudge_prepaid', {})[(reader.entity_id, target.entity_id)] = {'outcome': context['outcome']}
                counter_omen(engine, reader)
                note(engine, NUDGE, reader, f'Refuse Certainty: {target.display_name} rolls normally; 6 Resonance and the Reaction are paid.', (target,))
                return False
            note(engine, NUDGE, reader, f'Refuse Certainty: the opposing authority holds; the paid attempt is used this scene.', (target,))
    return None


@hook('roll_context_end')
def clear_prepaid_nudge(engine, frame):
    from ..paid_relocation import preserve_pending
    prepaid = engine.__dict__.get('_nudge_prepaid') or {}
    keys = [key for key in prepaid if key[1] == frame.get('actor_id')]
    if keys:
        preserve_pending(engine, '_nudge_prepaid')
        for key in keys:
            prepaid.pop(key, None)
