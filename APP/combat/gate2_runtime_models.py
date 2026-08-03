from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import StrictModel


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CandidateKind(StrEnum):
    MOVE = "MOVE"
    ACTION = "ACTION"
    BONUS_ACTION = "BONUS_ACTION"
    OPTIONAL_RIDER = "OPTIONAL_RIDER"
    REACTION = "REACTION"
    DECLINE_REACTION = "DECLINE_REACTION"
    END_TURN = "END_TURN"
    HOLD_POSITION = "HOLD_POSITION"
    TAKE_NO_OPTIONAL_ACTION = "TAKE_NO_OPTIONAL_ACTION"


class TerminalKind(StrEnum):
    VICTORY = "VICTORY"
    DRAW_SIMULTANEOUS = "DRAW_SIMULTANEOUS"
    DRAW_DURATION = "DRAW_DURATION"
    ENGINE_FAILURE = "ENGINE_FAILURE"


class EconomyKind(StrEnum):
    ACTION = "ACTION"
    BONUS_ACTION = "BONUS_ACTION"
    REACTION = "REACTION"
    NONE = "NONE"


class Position(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class DiceSpec(StrictModel):
    count: int = Field(ge=1)
    sides: int = Field(ge=2)
    modifier: int = 0


class SaveDefinition(StrictModel):
    ability: Literal["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    dc: int = Field(ge=1)


class ResourceDefinition(StrictModel):
    resource_id: str
    initial: int = Field(ge=0)
    maximum: int = Field(ge=0)


class ActionDefinition(StrictModel):
    source_definition_id: str
    display_name: str
    owner_id: str
    economy: EconomyKind
    resolution_kind: str
    target_kind: str
    range_ft: int | None = Field(default=None, ge=0)
    reach_ft: int | None = Field(default=None, ge=0)
    attack_bonus: int | None = None
    attack_count: int = Field(default=1, ge=1)
    damage: DiceSpec | None = None
    damage_type: str | None = None
    save: SaveDefinition | None = None
    costs: tuple[tuple[str, int], ...] = ()
    concentration: bool = False
    radius_ft: int | None = Field(default=None, ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ActorTemplate(StrictModel):
    entity_id: str
    display_name: str
    team_id: str
    primary_combatant: bool
    owner_id: str | None = None
    projection_sha256: str | None = None
    armor_class: int = Field(ge=0)
    maximum_hp: int = Field(ge=1)
    speed_ft: int = Field(ge=0)
    initiative_bonus: int
    dexterity_score: int = Field(ge=1)
    proficiency_bonus: int = Field(ge=0)
    saving_throws: dict[str, int]
    skills: dict[str, int] = Field(default_factory=dict, exclude_if=lambda value: not value)
    resources: tuple[ResourceDefinition, ...]
    action_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    passive_ids: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    augment_ids: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    damage_resistances: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)


class ConditionInstance(RuntimeModel):
    instance_id: str
    condition_id: str
    source_definition_id: str
    source_actor_id: str
    target_id: str
    stacks: int = Field(default=1, ge=1)
    applied_sequence: int = Field(ge=0)
    expires_on: str | None = None
    expires_actor_id: str | None = None
    expires_turn_count: int | None = Field(default=None, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


class ModifierInstance(RuntimeModel):
    modifier_id: str
    source_definition_id: str
    source_actor_id: str
    target_id: str
    target_field: str
    operation: str
    value: int | str
    applies_to: str
    expires_on: str | None = None
    expires_actor_id: str | None = None
    expires_turn_count: int | None = Field(default=None, ge=0)
    consumed: bool = False


class ConcentrationState(RuntimeModel):
    source_definition_id: str
    zone_id: str | None = None
    started_sequence: int


class ActorState(RuntimeModel):
    entity_id: str
    display_name: str
    team_id: str
    primary_combatant: bool
    owner_id: str | None = None
    projection_sha256: str | None = None
    armor_class: int
    maximum_hp: int
    current_hp: int
    temporary_hp: int = 0
    active: bool = True
    position: Position
    speed_ft: int
    movement_remaining_ft: int
    initiative_bonus: int
    dexterity_score: int
    proficiency_bonus: int
    saving_throws: dict[str, int]
    skills: dict[str, int] = Field(default_factory=dict, exclude_if=lambda value: not value)
    resources: dict[str, int]
    resource_maximums: dict[str, int]
    conditions: dict[str, ConditionInstance] = Field(default_factory=dict)
    modifiers: dict[str, ModifierInstance] = Field(default_factory=dict)
    concentration: ConcentrationState | None = None
    action_available: bool = True
    bonus_action_available: bool = True
    reaction_available: bool = True
    turn_flags: dict[str, Any] = Field(default_factory=dict)
    turns_started: int = 0
    action_ids: tuple[str, ...] = ()
    reaction_ids: tuple[str, ...] = ()
    passive_ids: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    augment_ids: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    damage_resistances: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ActorState":
        if not 0 <= self.current_hp <= self.maximum_hp:
            raise ValueError("current_hp out of bounds")
        if self.temporary_hp < 0 or self.movement_remaining_ft < 0:
            raise ValueError("negative temporary HP or movement")
        for rid, value in self.resources.items():
            maximum = self.resource_maximums.get(rid)
            if maximum is None or not 0 <= value <= maximum:
                raise ValueError(f"resource out of bounds: {rid}")
        return self


class RuntimeObjectState(RuntimeModel):
    object_id: str
    object_kind: str
    position: Position
    unattended: bool
    flammable: bool
    ignited: bool = False
    ignition_source_definition_id: str | None = None
    ignition_actor_id: str | None = None
    ignition_sequence: int | None = Field(default=None, ge=1)


class ZoneState(RuntimeModel):
    zone_id: str
    source_definition_id: str
    owner_id: str
    center: Position
    radius_cells: int = Field(ge=0)
    affected_cells: tuple[Position, ...]
    concentration_link: bool
    duration_rounds: int | None = Field(default=None, ge=1)
    created_round: int
    active: bool = True
    trigger_profile: dict[str, Any] = Field(default_factory=dict)
    per_turn_triggered: dict[str, int] = Field(default_factory=dict)


class RollRecord(StrictModel):
    roll_id: str
    counter_start: int
    counter_end: int
    expression: str
    actor_id: str
    reason: str
    dice: tuple[int, ...]
    modifier: int
    total: int
    natural_result: int | None = None
    mode: Literal["NORMAL", "ADVANTAGE", "DISADVANTAGE"] = "NORMAL"
    discarded: tuple[int, ...] = ()


class CombatEvent(StrictModel):
    sequence: int = Field(ge=1)
    state_version: int = Field(ge=0)
    event_type: str
    source_definition_id: str
    trigger_or_intent_id: str
    transaction_id: str
    actor_id: str | None = None
    target_ids: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)


class TerminalResult(StrictModel):
    kind: TerminalKind
    winning_team_id: str | None = None
    reason: str
    event_sequence: int


class PendingResolution(RuntimeModel):
    transaction_id: str
    source_definition_id: str
    intent_id: str
    actor_id: str
    target_ids: tuple[str, ...]
    stage: str
    reserved_costs: dict[str, int] = Field(default_factory=dict)
    pending_damage_packets: list[dict[str, Any]] = Field(default_factory=list)
    open_checkpoint: str | None = None
    follow_up_candidates: list[str] = Field(default_factory=list)
    reaction_depth: int = Field(default=0, ge=0, le=2)
    context: dict[str, Any] = Field(default_factory=dict)


class MatchState(RuntimeModel):
    schema_name: Literal["TianxiaGate2MatchState.v1"] = Field(default="TianxiaGate2MatchState.v1", alias="schema")
    match_id: str
    match_seed: str
    gate1_registry_snapshot_sha256: str
    mechanics_lock_sha256: str
    universal_defaults_lock_sha256: str
    round_number: int = Field(default=1, ge=1)
    initiative_order: list[str]
    current_slot_index: int = Field(default=0, ge=0)
    current_actor_id: str
    actors: dict[str, ActorState]
    objects: dict[str, RuntimeObjectState] = Field(default_factory=dict, exclude_if=lambda value: not value)
    zones: dict[str, ZoneState] = Field(default_factory=dict)
    pending_resolution: PendingResolution | None = None
    event_sequence: int = Field(default=0, ge=0)
    state_version: int = Field(default=0, ge=0)
    roll_counter: int = Field(default=0, ge=0)
    terminal_result: TerminalResult | None = None
    maximum_rounds: int = Field(default=20, ge=1)




class CandidateChoiceDomain(StrictModel):
    domain_id: str
    display_name: str
    selection_rule: Literal["EXACTLY_ONE", "ZERO_OR_ONE", "EXACT_SET"]
    option_ids: tuple[str, ...]
    minimum_selections: int = Field(ge=0)
    maximum_selections: int = Field(ge=0)
    default_option_ids: tuple[str, ...] = ()
    option_costs: dict[str, dict[str, int]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_domain(self) -> "CandidateChoiceDomain":
        if self.maximum_selections < self.minimum_selections:
            raise ValueError("maximum_selections is below minimum_selections")
        if self.maximum_selections > len(self.option_ids):
            raise ValueError("maximum_selections exceeds option count")
        if any(option not in self.option_ids for option in self.default_option_ids):
            raise ValueError("default option is not in the domain")
        if len(set(self.option_ids)) != len(self.option_ids):
            raise ValueError("duplicate option ID in domain")
        return self


class CandidateAreaProjection(StrictModel):
    geometry: Literal["RADIUS_CELLS"] = "RADIUS_CELLS"
    center: Position
    radius_cells: int = Field(ge=0)
    affected_cells: tuple[Position, ...]

class LegalCandidate(StrictModel):
    candidate_id: str
    decision_id: str
    state_version: int
    kind: CandidateKind
    actor_id: str
    source_definition_id: str
    display_name: str
    target_ids: tuple[str, ...] = ()
    destination: Position | None = None
    canonical_path: tuple[Position, ...] = ()
    movement_cost_ft: int = 0
    option_ids: tuple[str, ...] = ()
    choice_domains: tuple[CandidateChoiceDomain, ...] = ()
    choice_authority_status: Literal["NOT_APPLICABLE", "COMPLETE", "GAP"] = "NOT_APPLICABLE"
    area: CandidateAreaProjection | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReactionDecision(StrictModel):
    checkpoint: str
    reactor_id: str
    reaction_source_id: str
    selection: Literal["USE", "DECLINE"]
    spend: int = Field(default=0, ge=0)
    option_ids: tuple[str, ...] = ()


class ActionIntent(StrictModel):
    intent_id: str
    decision_id: str
    candidate_id: str
    state_version: int
    actor_id: str
    target_ids: tuple[str, ...] = ()
    destination: Position | None = None
    option_ids: tuple[str, ...] = ()
    reaction_decisions: tuple[ReactionDecision, ...] = ()
    # Optional typed runtime fields used only by sealed portable-character mechanics.
    object_ids: tuple[str, ...] = ()
    condition_instance_id: str | None = None
    penalty_id: str | None = None
    source_effect_dc: int | None = Field(default=None, ge=1)


class ScriptStep(StrictModel):
    actor_id: str
    kind: CandidateKind
    source_definition_id: str
    target_ids: tuple[str, ...] = ()
    destination: Position | None = None
    option_ids: tuple[str, ...] = ()
    reaction_decisions: tuple[ReactionDecision, ...] = ()
    note: str = ""


class ScriptedFight(StrictModel):
    fight_schema: Literal["TianxiaGate2ScriptedFight.v1"] = Field(default="TianxiaGate2ScriptedFight.v1", alias="schema")
    match_seed: str
    maximum_rounds: int = 20
    steps: tuple[ScriptStep, ...]


class RuntimeExport(StrictModel):
    export_schema: Literal["TianxiaGate2RuntimeExport.v1"] = Field(default="TianxiaGate2RuntimeExport.v1", alias="schema")
    final_state: dict[str, Any]
    events: tuple[CombatEvent, ...]
    rolls: tuple[RollRecord, ...]
    canonical_state_sha256: str
    canonical_event_log_sha256: str
