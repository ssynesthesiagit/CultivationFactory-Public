"""Owner-recorded, audience-scoped observations for divination and planning.

These are campaign facts, not facts invented by an AI. The table producer binds
an actual source, current subject, immediate horizon, witnesses, operational
answers and optional exact knowingly undertaken actions. Consumers query only
their own witnessed records. The journal is the store, including corrections.
"""
from __future__ import annotations

from typing import Literal
from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator
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
    source_cl: StrictInt = Field(ge=0)
    check_dc: StrictInt | None = Field(default=None, ge=1)
    condition: str = ''
    predictions: tuple[PredictedAction, ...] = ()


class ProjectCheck(StrictModel):
    """Source-admitted project roll; results never grant techniques or Spheres.

    Technique Forging uses the canonical 10 + Complexity + Sphere count DC.
    Foundation Challenges bind the GM's printed challenge DC to its source.
    The full protected limitation is recorded, rather than a qualifying tag.
    """
    actor_id: StrictStr
    kind: Literal['technique_forging', 'foundation_challenge']
    sphere_ids: tuple[StrictStr, ...]
    limitation: str = ''
    limitation_kind: Literal['none', 'duty', 'ward', 'oath', 'protected_subject', 'defensive_drawback'] = 'none'
    # Stamped server-side at admission for Foundation Challenges; never GM-supplied.
    foundation_acquisition_id: StrictStr = ''
    complexity: StrictInt | None = Field(default=None, ge=0)
    challenge_dc: StrictInt | None = Field(default=None, ge=1)
    design: dict | None = None
    construction_sha256: StrictStr | None = None
    ability: Literal['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']
    skill: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_project(self):
        if not self.sphere_ids or len(set(self.sphere_ids)) != len(self.sphere_ids):
            raise ValueError('Name the distinct component Spheres from the project source.')
        if self.kind == 'technique_forging' and (self.complexity is None or self.challenge_dc is not None):
            raise ValueError('Technique Forging uses its actual Complexity, not an arbitrary DC.')
        if self.kind == 'technique_forging' and (not self.design or not self.construction_sha256):
            raise ValueError('Technique Forging needs its native rules-checked construction receipt.')
        if self.kind == 'foundation_challenge' and (self.challenge_dc is None or self.complexity is not None):
            raise ValueError('Name the Foundation Challenge DC from the controlling source.')
        if self.limitation_kind != 'none' and not self.limitation.strip():
            raise ValueError('Record the concrete project limitation, not a tag.')
        return self


class DefenseFact(StrictModel):
    """GM's concrete scene assessment, never inferred from team or proximity.

    Position/sight constraints describe this duty, not universal rule ranges.
    Corrections replace the containing record and immediately invalidate queries.
    """
    defender_id: StrictStr
    subject_kind: Literal['ally', 'object', 'doorway', 'warded_place', 'helpless_creature', 'duty']
    meaningful: bool
    status: Literal['defending', 'separated', 'obscured', 'conflicted', 'abandoned', 'not_defending']
    reason: str = Field(min_length=1)
    appeared_round: StrictInt = Field(ge=1)
    maximum_distance_ft: StrictInt | None = Field(default=None, ge=0)
    requires_sight: bool

    @field_validator('reason')
    @classmethod
    def concrete_reason(cls, value):
        if not value.strip():
            raise ValueError('Describe the actual duty and defense.')
        return value.strip()


class SubjectPressure(StrictModel):
    """External intent/meaning requires a named source and actual actor input."""
    actor_id: StrictStr
    kind: Literal['threatened', 'attempted_bypass']
    verdict: Literal['qualifies', 'artificial_denied'] = 'qualifies'
    evidence: str = Field(min_length=1)

    @field_validator('evidence')
    @classmethod
    def concrete_evidence(cls, value):
        if not value.strip():
            raise ValueError('Describe the actual threat or bypass attempt.')
        return value.strip()


class PowerStateFact(StrictModel):
    """Explicit source effect on a power/resource; ordinary dispels aren't severance."""
    actor_id: StrictStr
    power_id: StrictStr
    state: Literal['suppressed', 'fully_severed', 'available']
    effect_kind: Literal['suppression', 'story_severance', 'restoration']
    scope: Literal['power', 'resources'] = 'power'
    resource_ids: tuple[StrictStr, ...] = ()
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_effect(self):
        expected = {'suppressed': 'suppression', 'fully_severed': 'story_severance', 'available': 'restoration'}
        if self.effect_kind != expected[self.state]:
            raise ValueError('Power state must name the actual suppression, story severance or restoration effect.')
        if self.scope == 'resources' and (not self.resource_ids or self.state == 'fully_severed'):
            raise ValueError('Resource-only suppression names actual resources and cannot sever a Foundation.')
        return self


class TechniqueScopeFact(StrictModel):
    """An explicit source interpretation for one owned technique and power."""
    actor_id: StrictStr
    source_definition_id: StrictStr
    power_id: StrictStr
    scope: Literal['compatible', 'fixed_scope']
    reason: str = Field(min_length=1)


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
    defenses: tuple[DefenseFact, ...] = ()
    subject_pressures: tuple[SubjectPressure, ...] = ()
    power_states: tuple[PowerStateFact, ...] = ()
    technique_scopes: tuple[TechniqueScopeFact, ...] = ()
    project_check: ProjectCheck | None = None

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
    if engine.state.terminal_result is not None or engine.state.pending_resolution is not None or engine.state.setup_tasks:
        raise ValueError('Finish the current choice or fight setup before recording facts.')
    if not set(fact.witness_ids) <= engine.state.actors.keys():
        raise ValueError('Witnesses must be creatures present in this fight.')
    if fact.subject_kind == 'creature' and fact.subject_id not in engine.state.actors:
        raise ValueError('Choose a creature present in this fight.')
    if fact.project_check is not None:
        from .project_checks import validate_project
        if fact.project_check.actor_id not in fact.witness_ids:
            raise ValueError('The project owner must know the admitted project.')
        validate_project(engine, fact)
    for defense in fact.defenses:
        if defense.defender_id not in fact.witness_ids or defense.defender_id not in engine.state.actors:
            raise ValueError('The defender must be present and know the declared duty.')
        if defense.appeared_round > engine.state.round_number:
            raise ValueError('A duty must actually have appeared before it can be declared.')
        if defense.subject_kind in {'ally', 'helpless_creature'} and fact.subject_kind != 'creature':
            raise ValueError('A creature duty must identify a present creature.')
        if defense.defender_id == fact.subject_id:
            raise ValueError('Name the subject being protected, rather than an artificial self-declaration.')
        if defense.subject_kind == 'ally' and engine.state.actors[defense.defender_id].team_id != engine.state.actors[fact.subject_id].team_id:
            raise ValueError('An ally declaration must name an ally.')
        if defense.subject_kind == 'object' and (fact.subject_kind != 'object' or fact.subject_id not in engine.state.objects):
            raise ValueError('An object duty must identify a native object.')
    if len({d.defender_id for d in fact.defenses}) != len(fact.defenses):
        raise ValueError('Record one assessment per defender and subject.')
    if any(p.actor_id not in engine.state.actors for p in fact.subject_pressures):
        raise ValueError('Subject pressure must name a present creature.')
    for power in fact.power_states:
        if power.actor_id not in engine.state.actors or power.actor_id not in fact.witness_ids:
            raise ValueError('A power effect must name its present, informed owner.')
        bundle = next((b for b in engine.typed_bundle_documents if b.get('actor_id') == power.actor_id), {})
        if not any(str(r.get('feature_id', '')).startswith(power.power_id + '.') for r in bundle.get('typed_passives', [])):
            raise ValueError('Power effects must identify a power the creature actually owns.')
        if not set(power.resource_ids) <= engine.state.actors[power.actor_id].resources.keys():
            raise ValueError('Suppression must name resources the creature actually has.')
    for scope in fact.technique_scopes:
        action = engine.action_catalog.get(scope.source_definition_id)
        if (scope.actor_id not in fact.witness_ids or action is None or action.owner_id != scope.actor_id
                or not action.parameters.get('typed') or action.parameters.get('setting_only')):
            raise ValueError('Scope must identify an owned native technique known to its actor.')
        bundle = next((b for b in engine.typed_bundle_documents if b.get('actor_id') == scope.actor_id), {})
        if not any(str(r.get('feature_id', '')).startswith(scope.power_id + '.') for r in bundle.get('typed_passives', [])):
            raise ValueError('Scope must identify a power the creature actually owns.')
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
