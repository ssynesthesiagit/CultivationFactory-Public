"""Native, versioned source declarations through the ordinary durable journal.

Used by CombatService's distinct actor/table-owner fact endpoints and by
Gate3 replay/recovery. This reuses fact_consent_admission schemas and records;
it is not an ability grant, roll override, or alternative combat executor.
No admitted source schema means rejection before any state change.
"""
from copy import deepcopy

from .canonical import canonical_sha256
from .gate2_runtime_models import ActionIntent

KIND = 'SOURCE_INPUT_V1'
SOURCE = 'system:combat.source_input'


class CombatFactContext:
    """Read-only native combat adapter for the shared journey admission schema.

    The temporary history/emitted metadata are committed only after PREPARE.
    Ownership comes from actual compiled bundles, never declaration values.
    Native combat time is whole six-second rounds, matching journey return.
    """
    is_combat_fact_context = True

    def __init__(self, engine):
        from .fact_consent_admission import CONDITION, KEY
        import json
        self.engine = engine
        bundles = {b['actor_id']: b for b in getattr(engine, 'typed_bundle_documents', ())}
        history = [json.loads(c.data['record']) for a in engine.state.actors.values()
                   for c in a.conditions.values() if c.condition_id == CONDITION]
        self.state = {'journey_id': engine.state.match_id, 'scene_id': engine.state.match_id,
            'actors': {aid: {'bundle': deepcopy(bundles.get(aid, {})),
                'position': a.position.model_dump(mode='json'), 'name': a.display_name}
                for aid, a in engine.state.actors.items()}, KEY: deepcopy(history)}
        self.emitted = []

    def clock(self):
        return max(0, self.engine.state.round_number - 1) * 6

    def next_fact_sequence(self):
        return self.engine.state.event_sequence + 1

    def emit(self, event_type, subject, **payload):
        self.emitted.append((event_type, subject, payload))


def binding(authority, payload):
    from .journey import require
    require(authority in ('subject', 'table_owner') and isinstance(payload, dict),
            'Choose actor input or the separate table-owner input path.')
    return {'kind': KIND, 'authority': authority, 'payload': deepcopy(payload)}


def intent_for(engine, policy, state_version):
    subject = policy['payload'].get('subject', '')
    key = canonical_sha256(policy)
    return ActionIntent(intent_id=f'source-input:{state_version}:{key}',
        decision_id='source-input:v1', candidate_id=key, state_version=state_version,
        actor_id=subject, target_ids=(subject,))


def validate(engine, intent, policy):
    """Pure admission before PREPARE and on replay; returns its staged context."""
    from .fact_consent_admission import declare, declare_world, KEY, digest
    from .journey import require
    require(isinstance(policy, dict) and set(policy) == {'kind', 'authority', 'payload'}
            and policy['kind'] == KIND and policy['authority'] in ('subject', 'table_owner')
            and isinstance(policy['payload'], dict), 'Invalid source input binding.')
    require(engine.state.terminal_result is None and engine.state.pending_resolution is None
            and intent.state_version == engine.state.state_version,
            'Refresh the live fight before submitting a source declaration.')
    require(intent.model_dump() == intent_for(engine, policy, engine.state.state_version).model_dump(),
            'A source declaration cannot carry an action, movement, roll, or reaction decision.')
    context = CombatFactContext(engine)
    for record in context.state[KEY]:
        require(record.get('receipt_id') == digest({k: v for k, v in record.items() if k != 'receipt_id'}),
                'An existing source declaration failed its replay commitment check.')
    expires = policy['payload'].get('expires_at')
    require(type(expires) is int and expires % 6 == 0,
            'Combat declarations expire on a whole six-second round boundary.')
    if policy['authority'] == 'table_owner':
        declare_world(context, policy['payload'])
    else:
        declare(context, intent.actor_id, policy['payload'])
    return context


def execute(engine, intent, policy):
    """One ordinary rollback-safe, cold-replayable metadata transaction."""
    from .fact_consent_admission import CONDITION, KEY, canonical
    from .ext.effect_durations import SLOT_AT
    from .journey import require
    context = validate(engine, intent, policy)
    record = context.state[KEY][-1]
    subject = engine.state.actors[record['subject']]
    expiry = f"{SLOT_AT}:{record['expires_at'] // 6 + 1}:0"
    if hasattr(engine, 'gate4_reaction_decision_records'):
        engine.gate4_reaction_decision_records = []
    with engine._transaction(SOURCE, intent.intent_id, subject.entity_id):
        engine._apply_condition(subject, CONDITION, record['source'], subject.entity_id,
            expires_on=expiry, data={'record': canonical(record), 'label': 'Source-scoped declaration'})
        require(any(c.condition_id == CONDITION and c.data.get('record') == canonical(record)
                    for c in subject.conditions.values()), 'The declaration could not be committed.')
        for event_type, actor_id, payload in context.emitted:
            # Declaration receipts are metadata; native condition application
            # already carries their state. Use the reducer's supported envelope
            # rather than inventing an unreplayable combat event type.
            engine._append_event('PASSIVE_TRIGGERED', SOURCE, actor_id=actor_id,
                payload={'checkpoint': event_type, **payload})
