"""Owner-recorded, audience-scoped observations and categorical source states.

These are campaign facts, not facts invented by an AI. The table producer binds
an actual source, current subject, immediate horizon, witnesses, operational
answers and optional exact knowingly undertaken actions. Consumers query only
their own witnessed records. Explicit until-withdrawn categorical states have
no prediction/check authority or round deadline. The journal is the sole store,
including exact-record corrections and withdrawal; default observations expire.
"""
from __future__ import annotations

from typing import Literal
from pydantic import Field, StrictInt, StrictStr, model_validator
from .models import StrictModel

SOURCE = 'system:combat.table_fact'


class PredictedAction(StrictModel):
    actor_id: StrictStr
    kind: Literal['ACTION', 'BONUS_ACTION', 'REACTION', 'MOVE', 'HOLD_POSITION', 'END_TURN']
    source_definition_id: StrictStr
    target_ids: tuple[StrictStr, ...] = ()
    destination: dict[str, StrictInt] | None = None
    option_ids: tuple[StrictStr, ...] = ()
    aware_actor_ids: tuple[StrictStr, ...]
    description: str = Field(min_length=1)
    requires_facts: tuple[StrictStr, ...] = ()


class FactAnswer(StrictModel):
    fact: str = Field(min_length=1)
    category: str = Field(min_length=1)
    visible_sign: str = Field(min_length=1)
    source_cl: StrictInt | None = Field(ge=0)
    check_dc: StrictInt | None = Field(default=None, ge=1)
    condition: str = ''
    predictions: tuple[PredictedAction, ...] = ()

    @model_validator(mode='after')
    def known_authority(self):
        # Classifying a real source/intent does not supply numeric authority.
        # Existing authority-bearing answers retain their known-level gate.
        if self.source_cl is None and self.category != 'source_classification':
            raise ValueError('An authority-bearing answer requires a known source level.')
        return self


class TableFact(StrictModel):
    record_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    subject_name: str = Field(min_length=1)
    subject_kind: Literal['creature', 'object', 'location', 'plan', 'event']
    position: dict[str, StrictInt]
    source_reference: str = Field(min_length=1)
    witness_ids: tuple[StrictStr, ...]
    horizon: Literal['immediate', 'until_withdrawn'] = 'immediate'
    valid_through_round: StrictInt | None = Field(default=None, ge=1)
    active: bool = True
    answers: dict[str, FactAnswer]

    @model_validator(mode='after')
    def validate_coordinates(self):
        from .gate2_runtime_models import Position
        Position.model_validate(self.position)
        if not self.witness_ids:
            raise ValueError('Record who actually observed this subject.')
        if not self.source_reference.strip():
            raise ValueError('Record the actual source reference.')
        if self.horizon == 'immediate' and self.valid_through_round is None:
            raise ValueError('An immediate observation needs its last valid round.')
        if self.horizon == 'until_withdrawn' and (
                self.valid_through_round is not None or not self.answers or any(
                    answer.category != 'source_classification' or answer.predictions or answer.check_dc is not None
                    for answer in self.answers.values())):
            raise ValueError('A persistent state must be categorical, without a round deadline, prediction or numeric check authority.')
        return self


def records(engine, viewer=None):
    """Latest current records. A viewer sees only their personal audience."""
    latest = {}
    for event in engine.events:
        if event.event_type == 'TABLE_FACT_RECORDED':
            fact = TableFact.model_validate(event.payload['fact'])
            latest[fact.record_id] = fact
    return {key: fact for key, fact in latest.items()
            if fact.active and (fact.horizon == 'until_withdrawn' or fact.valid_through_round >= engine.state.round_number)
            and (viewer is None or viewer.entity_id in fact.witness_ids)}


def observable(engine, viewer, fact, range_ft):
    """A recorded meaningful observation still needs present range and sight."""
    from .gate2_runtime_models import Position
    from .target_knowledge import can_see
    subject = engine.state.actors.get(fact.subject_id) if fact.subject_kind == 'creature' else None
    if subject is not None:
        return engine._distance_actor_to_actor(viewer, subject) <= range_ft and can_see(engine, viewer, subject)
    obj = engine.state.objects.get(fact.subject_id) if fact.subject_kind == 'object' else None
    position = obj.position if obj is not None else Position.model_validate(fact.position)
    from .senses import perceives_cell
    return engine.grid.distance_ft(viewer.position, position) <= range_ft and perceives_cell(engine, viewer, position)


def validate(engine, fact):
    from . import ext
    ext.run_strict('table_fact_validate', engine, fact)
    if engine.state.terminal_result is not None or engine.state.pending_resolution is not None or engine.state.setup_tasks:
        raise ValueError('Finish the current choice or fight setup before recording facts.')
    if not set(fact.witness_ids) <= engine.state.actors.keys():
        raise ValueError('Witnesses must be creatures present in this fight.')
    if fact.subject_kind == 'creature' and fact.subject_id not in engine.state.actors:
        raise ValueError('Choose a creature present in this fight.')
    for answer in fact.answers.values():
        for prediction in answer.predictions:
            if prediction.actor_id not in engine.state.actors or not set(prediction.aware_actor_ids) <= engine.state.actors.keys():
                raise ValueError('Record the actual creature and who knows the predicted action.')
            action = engine.action_catalog.get(prediction.source_definition_id)
            if prediction.kind in ('ACTION', 'BONUS_ACTION') and (action is None or action.owner_id != prediction.actor_id):
                raise ValueError('A predicted action must belong to the involved creature.')
            if prediction.destination is not None:
                from .gate2_runtime_models import Position
                Position.model_validate(prediction.destination)


def command_candidate(engine, document):
    from .canonical import canonical_sha256
    from .gate2_runtime_models import CandidateKind
    fact = TableFact.model_validate(document)
    validate(engine, fact)
    actor = engine.state.actors[engine.state.current_actor_id]
    candidate = engine._candidate(CandidateKind.ACTION, actor, SOURCE, 'Record an observed fact')
    return candidate.model_copy(update={'candidate_id': 'candidate:' + canonical_sha256(
        [candidate.candidate_id, fact.model_dump(mode='json')])[:24]})


def command_intent(engine, document, expected_state_version):
    from .gate2_runtime_models import ActionIntent
    if expected_state_version != engine.state.state_version:
        raise ValueError('The fight changed. Refresh before recording facts.')
    candidate = command_candidate(engine, document)
    return ActionIntent(intent_id=f'fact:{candidate.candidate_id}', candidate_id=candidate.candidate_id,
        decision_id=candidate.decision_id, state_version=expected_state_version,
        actor_id=candidate.actor_id, table_fact=TableFact.model_validate(document).model_dump(mode='json'))


def apply(engine, document):
    fact = TableFact.model_validate(document)
    validate(engine, fact)
    engine._append_event('TABLE_FACT_RECORDED', SOURCE,
        payload={'fact': fact.model_dump(mode='json'), 'audience_actor_ids': list(fact.witness_ids)})


def action_matches(engine, prediction, actor, candidate, intent, start_sequence):
    """Exact native voluntary completion, with explicit prior knowledge.

    No inference from attack/move categories or action names. Forced/granted
    effects have no enclosing matching voluntary candidate. Interrupted movement
    must actually reach its predicted endpoint. Conditions bind source records.
    """
    if actor.entity_id != prediction.actor_id or actor.entity_id not in prediction.aware_actor_ids:
        return False
    if (candidate.kind.value != prediction.kind or candidate.source_definition_id != prediction.source_definition_id
            or tuple(candidate.target_ids) != prediction.target_ids or tuple(intent.option_ids) != prediction.option_ids):
        return False
    if not set(prediction.requires_facts) <= records(engine).keys():
        return False
    if prediction.kind == 'MOVE':
        if prediction.destination is None or actor.position.model_dump(mode='json') != prediction.destination:
            return False
        return any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == actor.entity_id
                   and not e.payload.get('forced') and not e.payload.get('teleport')
                   and len(e.payload.get('path') or ()) > 1
                   and e.payload['path'][0] != e.payload['path'][-1]
                   for e in engine.events if e.sequence > start_sequence)
    return True


def accepted_source_matches(engine, prediction, source_id, source_actor_id, target_id):
    """Pure pre-resolution binding for a declared source's exact native intent.

    Shared by bodily-save classification and other source-intent consumers.
    Unlike action_matches, this does not claim an action completed. It requires
    the current transaction's real INTENT_ACCEPTED, actor, targets and options;
    a nested foreign reaction cannot borrow an enclosing action's declaration.
    """
    intent = getattr(engine, '_active_intent', None)
    if intent is None or intent.actor_id != source_actor_id or prediction.actor_id != source_actor_id:
        return False
    if not set(prediction.requires_facts) <= records(engine).keys():
        return False
    accepted = next((event for event in reversed(engine.events)
                     if event.event_type == 'INTENT_ACCEPTED'
                     and event.transaction_id == getattr(engine, '_transaction_id', None)), None)
    from .gate2_runtime_models import Position
    destination = Position.model_validate(prediction.destination) if prediction.destination is not None else None
    return bool(accepted is not None and accepted.actor_id == source_actor_id
        and accepted.source_definition_id == source_id == prediction.source_definition_id
        and accepted.payload.get('kind') == prediction.kind
        and tuple(accepted.target_ids) == prediction.target_ids and intent.destination == destination
        and tuple(intent.option_ids) == prediction.option_ids
        and target_id in prediction.aware_actor_ids)


def reaction_matches(engine, prediction, event_type, event):
    """Consume a committed native reaction, never an offered/declined choice.

    Optional variants require explicit native option_ids in the receipt; missing
    variant knowledge cannot be inferred from another action's active intent.
    """
    return (prediction.kind == 'REACTION' and event_type == 'REACTION_RESOLVED'
            and event.get('actor_id') == prediction.actor_id
            and prediction.actor_id in prediction.aware_actor_ids
            and event.get('source_definition_id') == prediction.source_definition_id
            and tuple(event.get('target_ids') or ()) == prediction.target_ids
            and tuple((event.get('payload') or {}).get('option_ids') or ()) == prediction.option_ids
            and set(prediction.requires_facts) <= records(engine).keys())
