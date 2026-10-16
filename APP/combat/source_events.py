"""Owner-authored source events, committed through the native combat journal.

Providers validate their own printed source and acquisition. Private narrative
evidence stays outside the fight; only its commitment enters intents/replays.
No actor menu or model provider can author these campaign facts. A source event
costs no action and cannot interrupt setup or an unresolved player decision.
"""
from . import ext
from .canonical import canonical_sha256
from .models import StrictModel
from pydantic import Field, StrictStr

SOURCE = 'system:combat.source_event'


class SourceEvent(StrictModel):
    event_id: StrictStr = Field(min_length=1, max_length=120)
    actor_id: StrictStr
    source_id: StrictStr
    acquisition_id: StrictStr
    kind: StrictStr
    evidence_sha256: StrictStr = Field(pattern=r'^[0-9a-f]{64}$')
    data: dict = Field(default_factory=dict)


def validate(engine, document):
    event = SourceEvent.model_validate(document)
    if (engine.state.terminal_result is not None or engine.state.pending_resolution is not None
            or engine.state.setup_tasks):
        raise ValueError('Finish fight setup and the current decision before recording a source event.')
    if event.actor_id not in engine.state.actors:
        raise ValueError('The affected creature must be present in this scene.')
    admitted = ext.run_strict('validate_source_event', engine, event)
    if sum(value is True for value in admitted) != 1:
        raise ValueError('No single source provider authorizes this event.')
    prior = [e.payload['source_event'] for e in engine.events
             if e.event_type == 'SOURCE_EVENT_RECORDED'
             and e.payload['source_event']['event_id'] == event.event_id]
    if prior:
        raise ValueError('This source event is already committed; synchronize its character receipt instead.')
    return event


def candidate(engine, document):
    from .gate2_runtime_models import CandidateKind
    event = validate(engine, document)
    actor = engine.state.actors[engine.state.current_actor_id]
    made = engine._candidate(CandidateKind.ACTION, actor, SOURCE, 'Record a source event')
    return made.model_copy(update={'candidate_id': 'candidate:' + canonical_sha256(
        [made.candidate_id, event.model_dump(mode='json')])[:24]})


def intent(engine, document, state_version):
    from .gate2_runtime_models import ActionIntent
    if state_version != engine.state.state_version:
        raise ValueError('The fight changed. Refresh before recording the source event.')
    made = candidate(engine, document)
    return ActionIntent(intent_id='source:' + document['event_id'], candidate_id=made.candidate_id,
        decision_id=made.decision_id, state_version=state_version, actor_id=made.actor_id,
        source_event=document)


def apply(engine, document):
    event = validate(engine, document)
    engine._append_event('SOURCE_EVENT_RECORDED', SOURCE, actor_id=event.actor_id,
        payload={'source_event': event.model_dump(mode='json')})
    ext.run_strict('apply_source_event', engine, event)


def synchronize(table, match_id):
    """Retryable journal -> character receipt delivery after a committed event.

    Receipts bind the exact acquisition and journal event hash. Repeated sync
    does not add another bonus. This is also the crash-recovery public caller.
    """
    from . import table_advance
    engine = table.combat._load_session(match_id).engine
    for row in engine.events:
        if row.event_type != 'SOURCE_EVENT_RECORDED':
            continue
        document = row.payload['source_event']
        actor = document['actor_id']
        if not actor.startswith('actor:factory.'):
            continue
        project = actor.removeprefix('actor:factory.')
        saved = table_advance.normalized(table.buttons.get(project).get('advancement'))
        receipt = {'event': document, 'match_id': match_id, 'sequence': row.sequence,
                   'journal_sha256': canonical_sha256(row.model_dump(mode='json'))}
        existing = next((r for r in saved['source_events']
                         if r['event']['event_id'] == document['event_id']), None)
        if existing is not None and existing != receipt:
            raise ValueError('A source event ID already belongs to another committed receipt.')
        if existing is None:
            saved['source_events'].append(receipt)
            table.buttons.save_advancement(project, saved)
    return {'status': 'RECORDED'}


def record(table, match_id, document, evidence, state_version):
    """Trusted owner/GM service caller; HTTP admission uses the session guard.

    The caller supplies concrete private source facts, not numerical effects.
    Commitments in native intents are derived here, never supplied by a seat.
    """
    import json
    import os
    event = SourceEvent.model_validate({**document, 'evidence_sha256': canonical_sha256(evidence)})
    session = table.combat._load_session(match_id)
    validate(session.engine, event.model_dump(mode='json'))
    accepted = ext.run_strict('validate_source_evidence', session.engine, event, evidence)
    if sum(value is True for value in accepted) != 1:
        raise ValueError('No single source provider authorizes these story facts.')
    command = intent(session.engine, event.model_dump(mode='json'), state_version)
    private = table.combat.userdata_root / 'source_event_evidence'
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = private / (event.evidence_sha256 + '.json')
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode('utf-8')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError('A private evidence commitment already has different bytes.')
    else:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(private, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    session.submit_intent(command, primary_decision_record=None, reaction_provider=None)
    return synchronize(table, match_id)
