"""Owner-recorded, audience-scoped observations for divination and planning.

These are campaign facts, not facts invented by an AI. The table producer binds
an actual source, current subject, immediate horizon, witnesses and operational
answers. Consumers query only
their own witnessed records. The journal is the store, including corrections.
"""
from __future__ import annotations

from typing import Literal
from pydantic import Field, StrictInt, StrictStr, model_validator
from .models import StrictModel

SOURCE = 'system:combat.table_fact'


class FactAnswer(StrictModel):
    fact: str = Field(min_length=1)
    category: str = Field(min_length=1)
    visible_sign: str = Field(min_length=1)
    source_cl: StrictInt = Field(ge=0)
    check_dc: StrictInt | None = Field(default=None, ge=1)
    condition: str = ''


class TableFact(StrictModel):
    record_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    subject_name: str = Field(min_length=1)
    subject_kind: Literal['creature', 'object', 'location', 'plan', 'event']
    position: dict[str, StrictInt]
    source_reference: str = Field(min_length=1)
    witness_ids: tuple[StrictStr, ...]
    horizon: Literal['immediate'] = 'immediate'
    valid_through_round: StrictInt = Field(ge=1)
    active: bool = True
    answers: dict[str, FactAnswer]

    @model_validator(mode='after')
    def validate_coordinates(self):
        from .gate2_runtime_models import Position
        Position.model_validate(self.position)
        if not self.witness_ids:
            raise ValueError('Record who actually observed this subject.')
        return self


def records(engine, viewer=None):
    """Latest current records. A viewer sees only their personal audience."""
    latest = {}
    for event in engine.events:
        if event.event_type == 'TABLE_FACT_RECORDED':
            fact = TableFact.model_validate(event.payload['fact'])
            latest[fact.record_id] = fact
    return {key: fact for key, fact in latest.items()
            if fact.active and fact.valid_through_round >= engine.state.round_number
            and (viewer is None or viewer.entity_id in fact.witness_ids)}


def validate(engine, fact):
    if engine.state.terminal_result is not None:
        raise ValueError('The fight is over, so no facts can be recorded.')
    if engine.state.pending_resolution is not None or engine.state.setup_tasks:
        raise ValueError('Finish the current choice or fight setup before recording facts.')
    if not set(fact.witness_ids) <= engine.state.actors.keys():
        raise ValueError('Witnesses must be creatures present in this fight.')
    if fact.subject_kind == 'creature' and fact.subject_id not in engine.state.actors:
        raise ValueError('Choose a creature present in this fight.')
    from . import ext
    ext.run_strict('table_fact_validate', engine, fact)


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
        payload={'fact': fact.model_dump(mode='json'), 'audience_actor_ids': list(fact.witness_ids),
                 'history_hidden': 1})
