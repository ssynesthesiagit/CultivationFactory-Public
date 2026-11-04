"""Public source declarations for recovery, contamination and consequence consumers.

Table facts carry the GM's subjective rulings; procedures carry the actual
printed challenge, cost and consequence. Neither a sphere nor an allied team
establishes alignment, willingness or a Minor injury. Used by source_procedures,
Mud Lotus and other recovery consumers. Unknown declarations remain unknown.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal
from pydantic import Field, StrictInt, StrictStr, model_validator
from .models import StrictModel

EXCLUSIONS = frozenset({'friendly', 'staged', 'self_inflicted', 'harmless', 'training',
    'repeated_non_threatening', 'farmed', 'preserve_corruption', 'hide_rot',
    'spread_plague', 'poison_flooding', 'rot_worship', 'forbidden_consumption',
    'sterile', 'hostile_rest', 'dry'})
_event = ContextVar('recorded_recovery_event', default=None)
_origins = ContextVar('recorded_recovery_origins', default=())


@contextmanager
def recovery_event(engine, record_id):
    """Bind one actor-selected, real pending source event for nested consumers."""
    token = _event.set((engine, record_id))
    try:
        yield
    finally:
        _event.reset(token)


@contextmanager
def recovery_origin(engine, actor_id, source_id, target_id):
    """Actual parent receipt provenance for a derived recovery grant."""
    token = _origins.set((*_origins.get(), (engine, actor_id, source_id, target_id)))
    try:
        yield
    finally:
        _origins.reset(token)


class RecoveryFacts(StrictModel):
    actor_id: StrictStr
    source_ids: tuple[StrictStr, ...]
    recipient_ids: tuple[StrictStr, ...]
    # A positive ruling is explicit and must name its observed evidence.
    evidence: str = Field(min_length=1)
    reality: Literal['unknown', 'genuine', 'staged'] = 'unknown'
    scene: Literal['ordinary', 'dangerous', 'treatment', 'stabilization',
        'suppression', 'sickness', 'minor_injury_challenge', 'shared_rest'] = 'ordinary'
    method: Literal['unknown', 'humble_recovery', 'living_water', 'lotus_root',
        'poison_treatment', 'disease_treatment', 'living_pollution',
        'shared_medicine', 'hardship_recovery', 'growth_through_mud', 'food',
        'medicine', 'humble_shelter'] = 'unknown'
    exclusions: tuple[StrictStr, ...] = ()
    willing_ids: tuple[StrictStr, ...] = ()
    # Source ownership and the person doing a qualifying roll may differ.
    purpose_actor_ids: tuple[StrictStr, ...] = ()
    treated_creature_ids: tuple[StrictStr, ...] = ()
    # These describe what the roll actually does, not permissions to add PB.
    treats_another: bool = False
    cleanses_source: bool = False
    accepts_help: bool = False
    humble_material: bool = False
    gm_reduce_minor: bool = False
    gm_consequence_ids: tuple[StrictStr, ...] = ()
    pending_consequences: tuple['PendingConsequence', ...] = ()
    categories: tuple[StrictStr, ...] = ()

    @model_validator(mode='after')
    def checked(self):
        if not self.source_ids or not self.recipient_ids:
            raise ValueError('Bind recovery facts to actual sources and recipients.')
        if set(self.exclusions) - EXCLUSIONS:
            raise ValueError('Unknown recovery boundary.')
        if not set(self.willing_ids) <= set(self.recipient_ids):
            raise ValueError('Consent must name an actual recipient.')
        practitioners = self.purpose_actor_ids or (self.actor_id,)
        patients = self.treated_creature_ids or self.recipient_ids
        if self.treats_another and any(not any(patient != actor for patient in patients) for actor in practitioners):
            raise ValueError('Treating another creature requires an actual other recipient.')
        ids = [p.condition_id for p in self.pending_consequences]
        if len(ids) != len(set(ids)):
            raise ValueError('Give a native condition only one source classification in a declaration.')
        return self


RecoveryMode = Literal['Repair', 'Purify', 'Integrate', 'rest', 'other']


class Strain(StrictModel):
    mechanical_effect: str = Field(min_length=1)
    recovery_mode: RecoveryMode
    duration: str = Field(min_length=1)
    duration_kind: Literal['one_minute', 'until_start_of_your_next_turn', 'until_end_of_turn', 'until_removed']
    effects: tuple[dict[str, Any], ...] = Field(min_length=1)


class Consequence(StrictModel):
    name: str = Field(min_length=1)
    category: Literal['acid', 'poison', 'poisoned', 'disease', 'rot', 'polluted_water',
        'terrain_contamination', 'sickness_exhaustion', 'failed_medicine',
        'hunger', 'alchemy', 'medicine', 'impurity', 'pill_impurity', 'similar_scoped']
    classification: Literal['Minor', 'major', 'ordinary']
    kind: Literal['consequence', 'hidden_injury', 'curse', 'deviation'] = 'consequence'
    # The source, not the plug-in, defines whether a lower step exists.
    steps: tuple[StrictStr, ...] = ()
    severity: StrictInt = Field(ge=1)
    mechanical_effect: str = Field(min_length=1)
    effects: tuple[dict[str, Any], ...] = Field(min_length=1)
    step_effects: tuple[tuple[dict[str, Any], ...], ...] = ()
    # Persistent replacement state for treating an already-applied step. It
    # does not replay the old step's instantaneous damage or refund prior harm.
    step_replacement_effects: tuple[tuple[dict[str, Any], ...], ...] = ()
    strain: Strain | None = None
    expires: Literal['UNTIL_REMOVED', 'END_OF_CURRENT_TURN', 'START_OF_SELF_NEXT_TURN']

    @model_validator(mode='after')
    def ladder(self):
        if self.steps and self.severity > len(self.steps):
            raise ValueError('The consequence severity must name a printed step.')
        if self.steps and len(self.step_effects) != len(self.steps):
            raise ValueError('Each source consequence step must have its actual mechanical effects.')
        if self.steps and len(self.step_replacement_effects) != len(self.steps):
            raise ValueError('Record the ongoing mechanical state of every consequence step.')
        return self


class SourceProcedure(StrictModel):
    id: str = Field(min_length=1, pattern=r'^[a-z0-9_]+$')
    name: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    printed_rule: str = Field(min_length=1)
    kind: Literal['treatment', 'check', 'save', 'harm', 'damage', 'attack', 'consequence']
    origin: Literal['technique', 'environmental_hazard', 'treatment'] = 'technique'
    hostility: Literal['unknown', 'hostile', 'benign'] = 'unknown'
    economy: Literal['ACTION', 'BONUS_ACTION', 'NONE']
    ability: Literal['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'] | None = None
    skill: str = ''
    dc: StrictInt | None = Field(default=None, ge=1)
    modifier: StrictInt = 0
    range_ft: StrictInt = Field(ge=0)
    cp_cost: StrictInt = Field(ge=0)
    cp_refund_on_success: StrictInt = Field(default=0, ge=0)
    hp: StrictInt = Field(default=0, ge=0)
    temporary_hp: StrictInt = Field(default=0, ge=0)
    success_effects: tuple[dict[str, Any], ...] = ()
    harm: StrictInt = Field(default=0, ge=0)
    damage_type: str | None = None
    categories: tuple[StrictStr, ...] = ()
    consequence: Consequence | None = None

    @model_validator(mode='after')
    def meaningful(self):
        if self.cp_refund_on_success > self.cp_cost:
            raise ValueError('A source refund cannot exceed its declared cultivation-point cost.')
        from typing import get_args
        for effect in self.success_effects:
            if effect.get('type') == 'source_recovery' and effect.get('mode') not in set(get_args(RecoveryMode)) - {'rest'}:
                raise ValueError('Record the actual source recovery route; rest requires a completed native rest.')
        if self.kind in ('check', 'save') and (self.dc is None or self.ability is None):
            raise ValueError('Record the actual source DC and ability; no missing number is invented.')
        if self.kind == 'treatment' and 'dc' not in self.model_fields_set:
            raise ValueError('State the treatment DC, or explicitly use null for a source that requires no roll.')
        if self.kind == 'treatment' and self.dc is not None and self.ability is None:
            raise ValueError('Record the actual treatment check ability.')
        if self.kind == 'treatment' and self.dc is None and not (self.hp or self.temporary_hp or self.success_effects):
            raise ValueError('A no-roll treatment must define its actual recovery effects.')
        if self.kind in ('harm', 'damage', 'attack') and self.harm <= 0:
            raise ValueError('A harm procedure needs measurable source harm.')
        if self.kind in ('damage', 'attack') and not (self.damage_type or '').strip():
            raise ValueError('Record the actual source damage type.')
        if self.kind in ('consequence', 'harm') and self.consequence is None:
            raise ValueError('Supply the source-defined consequence.')
        if self.kind == 'harm' and (not self.consequence.steps or self.consequence.severity != self.harm):
            raise ValueError('Measurable consequence harm needs its actual numeric step ladder and matching starting severity.')
        return self


class PendingConsequence(StrictModel):
    """GM/source classification for an actual native condition application."""
    condition_id: str = Field(min_length=1)
    consequence: Consequence


RecoveryFacts.model_rebuild()


def source_matches(engine, source_ids, source_id):
    """A real action identity or its sealed typed feature identity."""
    return any(sid == source_id or (sid in engine.action_catalog and
        (engine.action_catalog[sid].parameters.get('typed') or {}).get('source') == source_id)
        for sid in source_ids)


def event_qualifies(engine):
    """A derived recovery cannot launder a staged/farmed originating event."""
    binding = _event.get()
    if binding is not None and binding[0] is engine:
        from .table_facts import records
        fact = records(engine).get(binding[1])
        if fact is None or fact.recovery is None or not genuine(fact.recovery):
            return False
    for owner, actor_id, source_id, target_id in _origins.get():
        actor = engine.state.actors.get(actor_id) if owner is engine else None
        if actor is not None:
            declarations = list(facts_for(engine, actor, source_id, target_id))
            if declarations and not genuine(declarations[-1][1]):
                return False
    return True


def recovery_records(engine, viewer, source_id=None):
    """Current declarations in last-committed order, including corrections."""
    from .table_facts import records
    current = records(engine, viewer)
    binding = _event.get()
    if binding is not None and binding[0] is engine:
        from .table_facts import records as all_records
        bound = all_records(engine).get(binding[1])
        if bound is not None and bound.recovery is not None and source_id is not None and source_matches(engine, bound.recovery.source_ids, source_id):
            return [current[binding[1]]] if binding[1] in current else []
    order = {e.payload['fact']['record_id']: e.sequence for e in engine.events
             if e.event_type == 'TABLE_FACT_RECORDED'}
    return sorted(current.values(), key=lambda fact: order[fact.record_id])


def facts_for(engine, actor, source_id, subject_id=None):
    """Current, personally known declarations bound to this actor/source/recipient."""
    for fact in recovery_records(engine, actor, source_id):
        row = fact.recovery
        bound = row is not None and source_matches(engine, row.source_ids, source_id)
        if bound and row.actor_id == actor.entity_id:
            if subject_id is None or subject_id in row.recipient_ids:
                yield fact.record_id, row


def genuine(row):
    # These three are rest-scene boundaries, not evidence of a fake recovery
    # or harmless contamination. Pond-Shelter checks them explicitly.
    return row.reality == 'genuine' and not (set(row.exclusions) - {'dry', 'sterile', 'hostile_rest'})


def source_procedure_profile(engine, actor, source):
    """Owned sealed procedure profile for Foundation, Guard and Field readers.

    A source's explicit benign intent is not overridden by an opposing roster
    side. This reads the real compiled producer, never a name or a damage tag.
    """
    if actor is None:
        return None
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                   and (a.source_definition_id == source or (a.parameters.get('typed') or {}).get('source') == source)), None)
    return action.parameters.get('source_procedure') if action else None


def source_id(actor_id, procedure_id):
    return f'action:recorded.{actor_id}.{procedure_id}'
