"""Native, explicitly sourced treatment/challenge/consequence procedures.

GM authors source rules through the table advancement store. Scene facts enter
through table_facts; actors then choose an ordinary action and roll, pay and
resolve it through the typed executor. Absent authored procedures adds no action.
Consumers never manufacture HP receipts or infer subjective scene predicates.
"""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from . import effect, hook, run_strict
from ..recovery_sources import SourceProcedure, Consequence, facts_for, source_id, recovery_event
_applying = ContextVar('source_consequence_application', default=False)
HISTORY = 'condition:source.procedure_history'


def consumed(engine, actor, source):
    """Actual resolved event identities, including native journey continuation.

    The marker is derived only after SOURCE_PROCEDURE_RESOLVED. Its permanent,
    primitive state survives the ordinary encounter snapshot, so closing and
    reopening a native activity cannot turn an old event into new treatment.
    """
    used = {e.payload.get('record_id') for e in engine.events
            if e.event_type == 'SOURCE_PROCEDURE_RESOLVED'
            and e.actor_id == actor.entity_id and e.source_definition_id == source}
    for c in actor.conditions.values():
        if c.condition_id == HISTORY:
            used.update(json.loads(c.data['records']).get(source, ()))
    return used


def remember(ctx, rid):
    actor = ctx.actor
    marker = next((c for c in actor.conditions.values() if c.condition_id == HISTORY), None)
    records = json.loads(marker.data['records']) if marker else {}
    records[ctx.source] = sorted({*records.get(ctx.source, ()), rid})
    data = {'records': json.dumps(records, sort_keys=True),
        'source_audience': json.dumps([actor.entity_id]),
        'label': 'Completed treatment and challenge records: reopening does not repeat a resolved event.'}
    if marker:
        ctx.engine._update_condition_data(actor, marker, data, ctx.source, audience_actor_ids=[actor.entity_id])
    else:
        ctx.engine._apply_condition(actor, HISTORY, ctx.source, actor.entity_id,
                                    expires_on='UNTIL_REMOVED', data=data)


@hook('event', nested=True)
def private_history(engine, event_type, kwargs):
    if event_type in ('CONDITION_APPLIED', 'CONDITION_UPDATED') and (kwargs.get('payload') or {}).get('condition_id') == HISTORY:
        kwargs['payload']['audience_actor_ids'] = list(kwargs.get('target_ids') or ())
        kwargs['payload']['history_hidden'] = True


@hook('journal_notice_types')
def notices():
    """All mechanical changes use native typed events; these retain provenance."""
    return ('SOURCE_PROCEDURE_RESOLVED', 'SOURCE_CONSEQUENCE_RESOLVED',
            'SOURCE_CONSEQUENCE_REDUCED', 'SOURCE_CONSEQUENCE_RECOVERED', 'MEASURABLE_HARM_RESOLVED')


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    result = []
    for document in info['owner_sheet'].get('source_procedures', ()):
        row = SourceProcedure.model_validate(document)
        sid = source_id(info['actor_id'], row.id)
        result.append(ActionDefinition(source_definition_id=sid, owner_id=info['actor_id'],
            display_name=row.name, economy=row.economy, resolution_kind='TYPED',
            target_kind='ANY_CREATURE', range_ft=row.range_ft,
            parameters={'typed': {'source': sid, 'numbers': info['numbers'],
                'duration': {'kind': 'instant'}, 'riders': [],
                'effects': [{'type': 'source_procedure', 'procedure': row.model_dump(mode='json')}]},
                'free_primary': row.economy == 'NONE', 'expected_damage': row.harm,
                'description': row.printed_rule + f' Costs {row.cp_cost} cultivation points; range {row.range_ft} feet.'
                    + (f' On success, refunds up to {row.cp_refund_on_success} of those paid points.' if row.cp_refund_on_success else ''),
                'source_procedure': row.model_dump(mode='json')}))
    return result


@hook('candidate_allowed')
def available(engine, actor, candidate, action):
    if action is None or not action.parameters.get('source_procedure'):
        return None
    from .d20_rewrite import pool_id
    cost = action.parameters['source_procedure']['cp_cost']
    pool = pool_id(actor, 'cp')
    if cost and (pool is None or actor.resources.get(pool, 0) < cost):
        return False
    # Both seats retain all declared choices; missing facts grant nothing.
    records = list(facts_for(engine, actor, action.source_definition_id))
    targets = set(candidate.target_ids)
    used = consumed(engine, actor, action.source_definition_id)
    return None if any(rid not in used and targets <= set(row.recipient_ids) for rid, row in records) else False


def prepare_consequence(ctx, subject, document):
    """Quote/resolve prevention against this actual source-defined application."""
    row = Consequence.model_validate(document).model_dump(mode='json')
    row['subject_id'] = subject.entity_id
    for changed in run_strict('consequence_pending', ctx, subject, dict(row)):
        if changed is not None:
            if type(changed.get('severity')) is not int or changed['severity'] < 0:
                raise ValueError('Consequence prevention must return a nonnegative whole severity.')
            row.update(changed)
    return row


def record_consequence(ctx, subject, row, condition_ids, modifier_ids):
    """Journal source classification against exact effects that really applied."""
    from ..table_facts import records
    bound = list(facts_for(ctx.engine, ctx.actor, ctx.source, subject.entity_id))
    fact = records(ctx.engine, ctx.actor).get(bound[-1][0]) if bound else None
    audience = list(fact.witness_ids) if fact else [ctx.actor.entity_id, subject.entity_id]
    if row['severity'] > 0:
        from .effect_durations import holder_next_turn
        expiry = holder_next_turn(subject) if row['expires'] == 'START_OF_SELF_NEXT_TURN' else row['expires']
        ctx.engine._apply_condition(subject, 'condition:source.' + ctx.source + '.' + row['category'],
            ctx.source, ctx.actor.entity_id, expires_on=expiry,
            data={'name': row['name'], 'category': row['category'], 'kind': row['kind'],
                  'classification': row['classification'], 'severity': row['severity'],
                  'steps': json.dumps(row['steps']), 'mechanical_effect': row['mechanical_effect'],
                  'source_audience': json.dumps(audience), 'declaration': json.dumps(row),
                  'effect_conditions': json.dumps(sorted(condition_ids)),
                  'effect_modifiers': json.dumps(sorted(modifier_ids)),
                  'native_condition_record': int(row.get('native_condition_record', 0)),
                  'label': consequence_label(row)})
    ctx.engine._append_event('SOURCE_CONSEQUENCE_RESOLVED', ctx.source,
        actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
        payload={**row, 'audience_actor_ids': audience})


def consequence_label(row):
    clock = {'UNTIL_REMOVED': 'until treated or removed',
             'END_OF_CURRENT_TURN': 'until this turn ends',
             'START_OF_SELF_NEXT_TURN': 'until the affected creature starts its next turn'}.get(row['expires'], 'for its source-defined duration')
    return f"{row['name']}, severity {row['severity']}: {row['mechanical_effect']} Lasts {clock}."


@hook('state_event')
def native_consequence_ended(engine, event):
    """A classified native condition ends when its actual linked effects end."""
    if _applying.get() or event.event_type not in ('CONDITION_REMOVED', 'MODIFIER_REMOVED'):
        return
    for aid in set(event.target_ids) | {event.actor_id}:
        actor = engine.state.actors.get(aid)
        if actor is None:
            continue
        for key, marker in list(actor.conditions.items()):
            if not marker.data.get('native_condition_record'):
                continue
            ids = json.loads(marker.data.get('effect_conditions') or '[]')
            mids = json.loads(marker.data.get('effect_modifiers') or '[]')
            if not any(i in actor.conditions for i in ids) and not any(i in actor.modifiers for i in mids):
                engine._remove_condition_instance(actor, key, event.source_definition_id)


def apply_consequence(ctx, subject, document, *, prepared=None):
    """Apply one actual source consequence after all optional prevention choices.

    Every provider returns a replacement declaration; no provider means the
    source's severity and kind. A zero severity suppresses only this application.
    Source-defined lasting injuries deliberately remain UNTIL_REMOVED.
    """
    token = _applying.set(True)
    try:
        row = prepared if prepared is not None else prepare_consequence(ctx, subject, document)
        before_conditions, before_modifiers = set(subject.conditions), set(subject.modifiers)
        if row['severity'] > 0:
            from ..typed_executor import Context, run_effects
            sub = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject)
            effects = (row['step_effects'][row['severity'] - 1] if row['step_effects'] else row['effects'])
            run_effects(sub, list(effects))
        record_consequence(ctx, subject, row, set(subject.conditions) - before_conditions,
                           set(subject.modifiers) - before_modifiers)
    finally:
        _applying.reset(token)


@hook('condition_resolution_scope')
def native_condition(engine, subject, application):
    """Classify a real native condition without replacing unclassified effects."""
    if _applying.get():
        return None
    actor = engine.state.actors.get(application['source_actor_id'])
    if actor is None:
        return None
    bound = list(facts_for(engine, actor, application['source_id'], subject.entity_id))
    if not bound:
        return None
    template = next((p for p in bound[-1][1].pending_consequences
                     if p.condition_id == application['condition_id']), None)
    if template is None:
        return None
    from ..typed_executor import Context
    from ..gate2_runtime_models import ActionDefinition
    from .needle import numbers_of
    action = engine.action_catalog.get(application['source_id']) or next((a for a in engine.action_catalog.values()
        if a.owner_id == actor.entity_id and (a.parameters.get('typed') or {}).get('source') == application['source_id']), None)
    if action is None:
        source = application['source_id'].removeprefix('reaction:typed.')
        row = next((r for store in (engine.typed_reaction_rows, engine.typed_passive_rows)
                    for r in store.get(actor.entity_id, ()) if r.get('feature_id') == source), None)
        if row is None:
            return None
        action = ActionDefinition(source_definition_id=application['source_id'], owner_id=actor.entity_id,
            display_name=row.get('name') or template.consequence.name, economy='NONE',
            resolution_kind='TYPED', target_kind='SELF', parameters={})
    typed = {**(action.parameters.get('typed') or {}), 'source': application['source_id'],
             'numbers': (action.parameters.get('typed') or {}).get('numbers') or numbers_of(engine, actor)}
    ctx = Context(engine, actor, action, engine._active_intent, typed, [subject], subject)

    @contextmanager
    def scope():
        token = _applying.set(True)
        try:
            original = template.consequence.model_dump(mode='json')
            original['expires'] = application['expires_on'] or 'UNTIL_REMOVED'
            # Reuse the actual native condition and clock at the current step.
            actual = {'type': 'condition', 'condition': application['condition_id'].removeprefix('condition:typed.'),
                      'expires_on': original['expires'], 'applies_to': 'target', 'data': application['data']}
            original['effects'] = [actual]
            if original['step_effects']:
                original['step_effects'][original['severity'] - 1] = [actual]
            # The original native expiry is already resolved; validation of its
            # printed template happened at fact admission, before this scope.
            query = {**original, 'expires': template.consequence.expires}
            prepared = prepare_consequence(ctx, subject, query)
            if prepared['kind'] == original['kind']:
                prepared['expires'] = original['expires']
            changed = prepared['severity'] != original['severity'] or prepared['kind'] != original['kind']
            before = set(subject.conditions)
            if changed:
                apply_consequence(ctx, subject, query, prepared=prepared)
                application['cancel'] = True
            yield
            if not application['cancel']:
                ids = {key for key, c in subject.conditions.items() if key not in before
                       and c.condition_id == application['condition_id']
                       and c.source_definition_id == application['source_id']}
                if ids:
                    prepared['native_condition_record'] = 1
                    record_consequence(ctx, subject, prepared, ids, ())
        finally:
            _applying.reset(token)
    return scope()


def reduce_existing(ctx, subject, marker):
    """One source-defined step of a real existing Minor consequence.

    Uses exact application receipts, retaining unrelated conditions/modifiers.
    The source supplies replacement ongoing state; prior instantaneous damage
    is neither replayed nor healed. The existing injury clock remains in force.
    """
    token = _applying.set(True)
    try:
        return reduce_recorded_step(ctx, subject, marker)
    finally:
        _applying.reset(token)


def reduce_recorded_step(ctx, subject, marker):
    """Internal guarded transition; public consumers call reduce_existing."""
    row = json.loads(marker.data.get('declaration') or '{}')
    if (row.get('classification') != 'Minor' or row.get('severity', 0) <= 1
            or not row.get('step_replacement_effects')):
        return False
    before = int(row['severity'])
    # The replacement step inherits each removed condition's remaining clock: a
    # reduction shrinks an existing timed harm and never restarts it.
    # Preserve actual expiry clocks by effect kind and creation order. A step
    # may use a different condition id or replace a condition with a modifier;
    # matching on condition ids would silently restart the harm.
    clocks = {'condition': [], 'modifier': []}
    for key in json.loads(marker.data.get('effect_conditions') or '[]'):
        instance = subject.conditions.get(key)
        if instance is not None:
            clocks['condition'].append((instance.expires_on, instance.expires_actor_id,
                                        instance.expires_turn_count))
        ctx.engine._remove_condition_instance(subject, key, ctx.source)
    for key in json.loads(marker.data.get('effect_modifiers') or '[]'):
        instance = subject.modifiers.get(key)
        if instance is not None:
            clocks['modifier'].append((instance.expires_on, instance.expires_actor_id,
                                       instance.expires_turn_count))
        ctx.engine._remove_modifier_instance(subject, key, ctx.source)
    row['severity'] = before - 1
    from ..typed_executor import Context, run_effects
    original_actor = ctx.engine.state.actors.get(marker.source_actor_id, ctx.actor)
    sub = Context(ctx.engine, original_actor, ctx.action, ctx.intent,
        {**ctx.typed, 'source': marker.source_definition_id}, [subject], subject)
    conditions, modifiers = set(subject.conditions), set(subject.modifiers)
    run_effects(sub, list(row['step_replacement_effects'][row['severity'] - 1]))
    for kind, before_ids, collection in (
            ('condition', conditions, subject.conditions), ('modifier', modifiers, subject.modifiers)):
        new_ids = sorted(set(collection) - before_ids)
        for index, key in enumerate(new_ids):
            if index >= len(clocks[kind]):
                break
            expiry, expiry_actor, expiry_turn = clocks[kind][index]
            instance = collection[key]
            if kind == 'condition':
                ctx.engine._update_condition_data(subject, instance, dict(instance.data), ctx.source,
                    expires_on=expiry)
                instance.expires_actor_id = expiry_actor
                instance.expires_turn_count = expiry_turn
            else:
                instance.expires_on = expiry
                instance.expires_actor_id = expiry_actor
                instance.expires_turn_count = expiry_turn
    ctx.engine._update_condition_data(subject, marker,
        {**marker.data, 'severity': row['severity'], 'declaration': json.dumps(row),
         'native_condition_record': 0,
         'effect_conditions': json.dumps(sorted(set(subject.conditions) - conditions)),
         'effect_modifiers': json.dumps(sorted(set(subject.modifiers) - modifiers)),
         'label': consequence_label(row)}, ctx.source,
        audience_actor_ids=json.loads(marker.data.get('source_audience') or '[]'))
    ctx.engine._append_event('SOURCE_CONSEQUENCE_REDUCED', ctx.source,
        actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
        payload={'instance_id': marker.instance_id, 'before': before, 'after': row['severity'],
                 'original_source': marker.source_definition_id,
                 'audience_actor_ids': json.loads(marker.data.get('source_audience') or '[]')})
    return True


@effect('source_consequence', harmful=True)
def consequence(ctx, eff):
    for subject in ctx.targets:
        apply_consequence(ctx, subject, eff['consequence'])


@effect('source_recovery', harmful=False)
def recover_source_strain(ctx, eff):
    """A real source procedure/challenge treats its declared Strain route.

    Generic rests have their own completed-clock consumer. Major injuries and
    unbound/unknown conditions never become eligible through this effect.
    """
    from typing import get_args
    from ..recovery_sources import RecoveryMode
    from .needle import ask, checkpoint_id
    mode = eff.get('mode')
    if mode not in set(get_args(RecoveryMode)) - {'rest'}:
        raise ValueError('A source recovery must name its actual non-rest route.')
    from ..typed_executor import _default_subject
    for subject in _default_subject(ctx, eff, harmful=False):
        declarations = list(facts_for(ctx.engine, ctx.actor, ctx.source, subject.entity_id))
        ids = set(declarations[-1][1].gm_consequence_ids) if declarations else set()
        eligible = []
        for key, condition in subject.conditions.items():
            if key not in ids or not condition.data.get('declaration'):
                continue
            declaration = json.loads(condition.data['declaration'])
            if declaration.get('kind') == 'strain' and declaration.get('recovery_mode') == mode:
                eligible.append(condition)
        if not eligible:
            raise ValueError('Bind an actual current Strain that uses this source-defined recovery route.')
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SOURCE_RECOVERY', subject.entity_id),
            ctx.actor, 'choice:needle.source_recovery', [c.instance_id for c in eligible],
            labels={c.instance_id: c.data['label'] for c in eligible}, name=ctx.action.display_name,
            feature_id=ctx.source, target_id=subject.entity_id,
            prompt=ctx.action.display_name + ': choose the actual Strain this successful treatment clears. '
                   'Only its linked penalties end; no Hit Points are restored and there is no extra action or resource cost.')
        marker = next(c for c in eligible if c.instance_id == picked[0])
        token = _applying.set(True)
        try:
            for key in json.loads(marker.data['effect_conditions']):
                ctx.engine._remove_condition_instance(subject, key, ctx.source)
            for key in json.loads(marker.data['effect_modifiers']):
                ctx.engine._remove_modifier_instance(subject, key, ctx.source)
            ctx.engine._remove_condition_instance(subject, marker.instance_id, ctx.source)
        finally:
            _applying.reset(token)
        ctx.engine._append_event('SOURCE_CONSEQUENCE_RECOVERED', ctx.source,
            actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
            payload={'instance_id': marker.instance_id, 'recovery_mode': mode,
                     'audience_actor_ids': procedure_audience(ctx.engine, ctx.actor, declarations[-1][0])})


@effect('source_procedure', harmful=False)
def resolve(ctx, eff):
    row = SourceProcedure.model_validate(eff['procedure'])
    subjects = ctx.targets or [ctx.actor]
    used = consumed(ctx.engine, ctx.actor, ctx.source)
    bound = [(rid, fact) for rid, fact in facts_for(ctx.engine, ctx.actor, ctx.source)
             if rid not in used and all(s.entity_id in fact.recipient_ids for s in subjects)]
    if not bound:
        raise ValueError('Record a genuine, unresolved source event and its actual recipients first.')
    if len(bound) > 1:
        from .needle import ask, checkpoint_id
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'RECOVERY_EVENT', ctx.actor.entity_id, ctx.source),
            ctx.actor, 'choice:needle.source_recovery_event', [rid for rid, _ in bound],
            labels={rid: fact.evidence for rid, fact in bound},
            name=row.name, feature_id=ctx.source, automatic=True,
            prompt=row.name + ': choose the actual pending source event to resolve. Every unresolved event remains available.')
        rid, fact = next(pair for pair in bound if pair[0] == picked[0])
    else:
        rid, fact = bound[0]
    with recovery_event(ctx.engine, rid):
        resolve_event(ctx, row, subjects, rid, fact)


def resolve_event(ctx, row, subjects, rid, fact):
    """One explicitly selected source event; never another event's scene facts."""
    from .. import typed_executor as te
    from .d20_rewrite import pool_id
    start_sequence = ctx.engine.state.event_sequence
    if row.cp_cost:
        pool = pool_id(ctx.actor, 'cp')
        if pool is None or ctx.actor.resources.get(pool, 0) < row.cp_cost:
            raise ValueError('Insufficient cultivation points for this source procedure.')
        ctx.engine._spend_resource(ctx.actor, pool, row.cp_cost, ctx.source)
    succeeded = True
    if row.kind in ('treatment', 'check') and row.dc is not None:
        from ..ability_checks import ability_modifier, skill_bonus
        base = (int(ctx.numbers['pb']) + int(ctx.numbers['key_mod']) if row.skill.lower() == 'cultivation'
                else skill_bonus(ctx.engine, ctx.actor, row.skill,
                    ability_modifier(ctx.actor, row.ability, numbers=ctx.numbers)) if row.skill
                else ability_modifier(ctx.actor, row.ability, numbers=ctx.numbers))
        with ctx.engine.d20_scope({'kind': 'check', 'actor_id': ctx.actor.entity_id,
                'target_id': subjects[0].entity_id, 'source_id': ctx.source,
                'source_actor_id': ctx.actor.entity_id, 'ability': row.ability,
                'skill': row.skill, 'dc': row.dc, 'named': list(row.categories)}):
            roll = ctx.engine.roll_check(actor_id=ctx.actor.entity_id, modifier=base + row.modifier,
                reason='CHECK:' + ctx.source, ability=row.ability, skill=row.skill)
        ctx.engine._record_roll(roll)
        succeeded = roll.total >= row.dc
        ctx.engine._append_event('CHECK_ROLLED', ctx.source, actor_id=ctx.actor.entity_id,
            target_ids=tuple(s.entity_id for s in subjects), payload={'roll': roll.model_dump(mode='json'),
                'skill': row.skill, 'dc': row.dc, 'success': succeeded})
    elif row.kind == 'save':
        first = ctx.engine.state.event_sequence
        sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent,
            {**ctx.typed, 'numbers': {**ctx.numbers, 'save_dc': row.dc}}, subjects, subjects[0])
        te.run_effects(sub, [{'type': 'save', 'ability': row.ability,
            'save_categories': list(row.categories),
            'on_fail': ([{'type': 'source_consequence', 'consequence': row.consequence.model_dump(mode='json')}]
                        if row.consequence else []), 'on_success': []}])
        receipts = [e for e in ctx.engine.events if e.sequence > first
                    and e.event_type == 'SAVE_ROLLED' and e.source_definition_id == ctx.source]
        if not receipts or any(type(e.payload.get('success')) is not bool for e in receipts):
            raise ValueError('The saving-throw procedure produced no settled native outcome.')
        succeeded = all(e.payload['success'] for e in receipts)
    elif row.kind == 'harm':
        for subject in subjects:
            amount = row.harm
            for result in run_strict('measurable_harm_pending', ctx, subject, amount, tuple(row.categories)):
                if result is not None:
                    amount = max(0, amount - int(result))
            ctx.engine._append_event('MEASURABLE_HARM_RESOLVED', ctx.source,
                actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                payload={'before': row.harm, 'after': amount, 'categories': list(row.categories)})
            if amount and row.consequence:
                doc = row.consequence.model_dump(mode='json')
                doc['severity'] = min(doc['severity'], amount)
                apply_consequence(ctx, subject, doc)
    elif row.kind in ('damage', 'attack'):
        delivery = [{'type': 'damage', 'flat': row.harm,
                     'damage_types': [row.damage_type], 'applies_to': 'target'}]
        if row.kind == 'attack':
            delivery = [{'type': 'attack', 'attack_kind': 'weapon', 'on_hit': delivery}]
        te.run_effects(ctx, delivery)
    if succeeded and row.kind in ('treatment', 'check'):
        effects = []
        if row.hp:
            effects.append({'type': 'healing', 'flat': row.hp, 'applies_to': 'target'})
        if row.temporary_hp:
            effects.append({'type': 'temp_hp', 'flat': row.temporary_hp, 'applies_to': 'target'})
        effects.extend(row.success_effects)
        te.run_effects(ctx, effects)
    if row.kind == 'consequence' or (not succeeded and row.kind in ('treatment', 'check') and row.consequence):
        for subject in subjects:
            apply_consequence(ctx, subject, row.consequence.model_dump(mode='json'))
    # A no-roll cure of an unaffected creature is not completed treatment.
    # Derive this receipt from real results, never an owner-supplied done flag.
    affected = {s.entity_id for s in subjects}
    settled = [e for e in ctx.engine.events if e.sequence > start_sequence
               and e.source_definition_id == ctx.source]
    treatment_completed = row.kind == 'treatment' and succeeded and any(
        e.event_type == 'CHECK_ROLLED' and e.payload.get('success') is True or
        bool(affected.intersection(e.target_ids)) and (
            e.event_type in ('CONDITION_APPLIED', 'CONDITION_REMOVED', 'MODIFIER_APPLIED',
                             'MODIFIER_REMOVED', 'LIFE_STATE_CHANGED', 'SOURCE_CONSEQUENCE_REDUCED') or
            e.event_type in ('HEALING_APPLIED', 'TEMP_HP_GRANTED')
            and type(e.payload.get('before')) is int and type(e.payload.get('after')) is int
            and e.payload['after'] > e.payload['before'])
        for e in settled)
    from ..technique_costs import net_paid, refund
    from ..typed_executor import CP_POOLS
    paid = net_paid(ctx.engine, ctx.actor, ctx.source, start_sequence, CP_POOLS)
    if succeeded and row.cp_refund_on_success:
        pool = pool_id(ctx.actor, 'cp')
        refund(ctx.engine, ctx.actor, ctx.source, ((pool, row.cp_cost),), pool,
               min(row.cp_refund_on_success, paid.get(pool, 0)), ctx.source)
        paid = net_paid(ctx.engine, ctx.actor, ctx.source, start_sequence, CP_POOLS)
    ctx.engine._append_event('SOURCE_PROCEDURE_RESOLVED', ctx.source,
        actor_id=ctx.actor.entity_id, target_ids=tuple(s.entity_id for s in subjects),
        payload={'record_id': rid, 'kind': row.kind, 'success': int(succeeded),
                 'cp_paid': sum(paid.values()), 'treatment_completed': int(treatment_completed),
                 'source_reference': row.source_reference,
                 'origin': row.origin, 'hostility': row.hostility,
                 'audience_actor_ids': procedure_audience(ctx.engine, ctx.actor, rid)})
    remember(ctx, rid)


def procedure_audience(engine, actor, record_id):
    from ..table_facts import records
    return list(records(engine, actor)[record_id].witness_ids)


@hook('presentation_hidden_conditions')
def private_source_conditions(engine, subject):
    """Conceal private injury records in public presentation, preserving rules."""
    actors = getattr(getattr(engine, 'state', None), 'actors', {})
    return {key for key, c in subject.conditions.items()
            if c.condition_id == HISTORY or (c.condition_id.startswith('condition:source.') and c.data.get('source_audience')
            and (engine is None or set(json.loads(c.data['source_audience'])) != set(actors)))}


@hook('table_fact_recorded')
def declared(engine, fact):
    # Subscribers can respond to an actual newly committed external ruling,
    # e.g. ending a field used to preserve rot. Merely loading facts is inert.
    if fact.recovery is not None:
        run_strict('recovery_declaration', engine, fact)
