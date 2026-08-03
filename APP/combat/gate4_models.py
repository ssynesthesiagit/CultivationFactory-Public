from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable
from pydantic import Field, model_validator

from .models import StrictModel
from .gate2_runtime_models import ActionIntent, LegalCandidate, Position, ReactionDecision


class VisibleActor(StrictModel):
    entity_id: str
    display_name: str
    team_id: str
    primary_combatant: bool
    owner_id: str | None = None
    active: bool
    current_hp: int
    maximum_hp: int
    temporary_hp: int
    armor_class: int
    position: Position
    speed_ft: int
    movement_remaining_ft: int
    action_available: bool
    bonus_action_available: bool
    reaction_available: bool
    resources: dict[str, int]
    conditions: tuple[str, ...]
    concentration_source_id: str | None = None


class VisibleZone(StrictModel):
    zone_id: str
    source_definition_id: str
    owner_id: str
    center: Position
    radius_cells: int
    active: bool


class TeamBehavior(StrictModel):
    focus_target_id: str | None = None
    immediate_defeat_pressure: bool = False
    formation_direction: Literal["CLOSE", "HOLD", "SPREAD"] = "HOLD"


class LocalControllerPolicy(StrictModel):
    schema_name: Literal["TianxiaLocalControllerPolicy.v1"] = Field(
        default="TianxiaLocalControllerPolicy.v1", alias="schema"
    )
    policy_id: str
    policy_version: str
    source_doctrine_id: str | None = None
    source_doctrine_sha256: str | None = None
    source_projection_sha256: str | None = None
    actor_id: str | None = None
    role: tuple[str, ...]
    preferred_range_bands_ft: tuple[tuple[int, int], ...]
    target_priorities: dict[str, int]
    action_priorities: dict[str, int]
    resource_reserves: dict[str, int]
    reaction_rules: dict[str, dict[str, int | str | bool]]
    ally_companion_priorities: dict[str, int]
    low_hp_behavior: dict[str, int | str]
    prohibited_choices: tuple[str, ...]
    weights: dict[str, int]
    generic_fallback: bool = False


class DecisionContext(StrictModel):
    schema_name: Literal["TianxiaDecisionContext.v1"] = Field(
        default="TianxiaDecisionContext.v1", alias="schema"
    )
    match_id: str
    state_version: int
    decision_id: str
    active_actor_id: str
    round_number: int
    current_slot_index: int
    actors: tuple[VisibleActor, ...]
    zones: tuple[VisibleZone, ...]
    legal_candidates: tuple[LegalCandidate, ...]
    policy: LocalControllerPolicy
    team_behavior: TeamBehavior
    recent_events: tuple[dict[str, Any], ...]
    no_progress_signals: tuple[str, ...] = ()


class ReactionContext(StrictModel):
    schema_name: Literal["TianxiaReactionContext.v1"] = Field(
        default="TianxiaReactionContext.v1", alias="schema"
    )
    match_id: str
    state_version: int
    decision_id: str
    checkpoint: str
    reactor_id: str
    protected_target_id: str | None = None
    damaged_target_id: str | None = None
    attacking_actor_id: str | None = None
    reaction_source_id: str
    provisional_hit: bool | None = None
    pending_damage: int | None = None
    legal_reaction_ids: tuple[str, ...]
    spend_options: tuple[int, ...] = ()
    legal_option_ids: tuple[str, ...] = ()
    resources: dict[str, int]
    conditions: tuple[str, ...]
    policy: LocalControllerPolicy
    recent_events: tuple[dict[str, Any], ...] = ()


class ComponentScore(StrictModel):
    component: str
    value: int
    explanation: str


class CandidateScore(StrictModel):
    candidate_id: str
    option_ids: tuple[str, ...]
    total: int
    components: tuple[ComponentScore, ...]


class DecisionRecord(StrictModel):
    schema_name: Literal["TianxiaControllerDecisionRecord.v1"] = Field(
        default="TianxiaControllerDecisionRecord.v1", alias="schema"
    )
    controller_id: str
    controller_version: str
    policy_id: str
    policy_version: str
    decision_id: str
    actor_id: str
    state_version: int
    decision_kind: Literal["PRIMARY", "REACTION"]
    legal_alternatives: tuple[str, ...]
    scored_alternatives: tuple[CandidateScore, ...]
    selected_candidate_id: str
    selected_option_ids: tuple[str, ...]
    selected_reaction: ReactionDecision | None = None
    deterministic_tie_break: str
    explanation: str
    fallback_policy_used: bool = False
    diagnostics: tuple[dict[str, Any], ...] = ()


class ControllerChoice(StrictModel):
    intent: ActionIntent
    record: DecisionRecord


class ReactionChoice(StrictModel):
    decision: ReactionDecision
    record: DecisionRecord


@runtime_checkable
class CombatController(Protocol):
    controller_id: str
    controller_version: str

    def choose_primary_action(self, decision_context: DecisionContext) -> ControllerChoice: ...
    def choose_reaction(self, reaction_context: ReactionContext) -> ReactionChoice: ...
