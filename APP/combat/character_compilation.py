from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceAuthority(FrozenModel):
    record_id: str
    record_hash: str | None = None
    source_path: str
    source_sha256: str
    source_anchor: str
    acquisition_provenance: dict[str, Any]


class TimingContract(FrozenModel):
    action_economy: str
    trigger_checkpoint: str | None = None


class TargetContract(FrozenModel):
    domains: tuple[str, ...]
    range_ft: int | None = Field(default=None, ge=0)
    geometry: str
    line_of_sight_required: bool


class LockedMechanic(FrozenModel):
    stable_id: str
    display_name: str
    classification: Literal["EXECUTABLE", "PASSIVE_EXECUTABLE"]
    mechanic_kind: Literal["ACTION", "REACTION", "AUGMENT", "PASSIVE", "RESOURCE"]
    source: SourceAuthority
    timing: TimingContract
    actor_restrictions: tuple[str, ...]
    targets: TargetContract
    formula: dict[str, Any] | None = None
    damage: dict[str, Any] | None = None
    resource_cost: dict[str, Any] | None = None
    conditions: tuple[str, ...]
    movement: dict[str, Any] | None = None
    concentration: bool
    riders: tuple[dict[str, Any], ...]
    prerequisites: tuple[str, ...]
    repeatability: str
    event_emission: tuple[str, ...]
    required_primitives: tuple[str, ...]
    execution_provenance: dict[str, Any]
    typed_details: dict[str, Any]
    unsupported_diagnostics: tuple[dict[str, Any], ...]


class ClassifiedNonExecutable(FrozenModel):
    stable_id: str
    display_name: str
    classification: Literal["NONCOMBAT_DISPLAY_ONLY", "NOT_APPLICABLE", "EXPLICIT_TYPED_NONE", "BLOCKED_MATERIAL_AMBIGUITY"]
    source: SourceAuthority
    reason: str


class ExecutableMechanicsLock(FrozenModel):
    schema_version: Literal["TianxiaFoundry.ExecutableMechanicsLock.v1"]
    lock_id: Literal["Tianxia_Fire_Qi_Executable_Mechanics_Lock_R1"]
    lock_version: Literal["1.0.0"]
    authority_classification: Literal["SEALED_COMBAT_EXECUTION_AUTHORITY"]
    subordinate_to: dict[str, Any]
    primitive_registry_id: str
    primitive_registry_sha256: str
    engine_api_version: str
    runtime_prose_parsing: Literal[False]
    mechanics: tuple[LockedMechanic, ...]
    classified_nonexecutables: tuple[ClassifiedNonExecutable, ...]
    counts: dict[str, int]
    readiness: str
    encounter_created: Literal[False]
    combat_events_committed: Literal[0]
    dice_rolled: Literal[0]
    lock_sha256: str

    @model_validator(mode="after")
    def verify_lock(self) -> "ExecutableMechanicsLock":
        raw = self.model_dump(mode="json")
        expected = raw.pop("lock_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("mechanics lock checksum mismatch")
        ids = [row.stable_id for row in self.mechanics]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("mechanics must be unique and sorted")
        non_ids = [row.stable_id for row in self.classified_nonexecutables]
        if non_ids != sorted(non_ids) or len(non_ids) != len(set(non_ids)):
            raise ValueError("nonexecutables must be unique and sorted")
        if self.counts.get("total_classified") != len(ids) + len(non_ids):
            raise ValueError("lock count mismatch")
        if any(row.classification == "BLOCKED_MATERIAL_AMBIGUITY" for row in self.classified_nonexecutables):
            raise ValueError("material ambiguity blocks executable lock")
        return self


class PrimitiveDefinition(FrozenModel):
    primitive_id: str
    contract: str


class PrimitiveRegistry(FrozenModel):
    schema_version: Literal["TianxiaFoundry.CombatPrimitiveRegistry.v1"]
    registry_id: str
    engine_api_version: str
    combat_module_version: str
    authority: str
    source_core_registry: dict[str, str]
    primitives: tuple[PrimitiveDefinition, ...]
    conditions: tuple[str, ...]
    event_types: tuple[str, ...]
    target_domains: tuple[str, ...]
    formula_kinds: tuple[str, ...]
    registry_sha256: str

    @model_validator(mode="after")
    def verify_registry(self) -> "PrimitiveRegistry":
        raw = self.model_dump(mode="json")
        expected = raw.pop("registry_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("primitive registry checksum mismatch")
        ids = [row.primitive_id for row in self.primitives]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("primitive IDs must be unique and sorted")
        return self


class CombatantStats(FrozenModel):
    cultivation_level: int
    realm: str
    species: str
    creature_type: str
    size: str
    ability_scores: dict[str, int]
    proficiency_bonus: int
    hit_points_maximum: int
    armor_class: int
    initiative_bonus: int
    speed_ft: int
    technique_attack_bonus: int
    technique_save_dc: int
    saving_throws: dict[str, int]
    skills: dict[str, int]
    equipped_weapon_ids: tuple[str, ...] = ()
    equipped_armor_ids: tuple[str, ...] = ()


class ActionEconomy(FrozenModel):
    action_per_turn: int = 1
    bonus_action_per_turn: int = 1
    reaction_per_round: int = 1
    movement_ft_per_turn: int = 30
    object_interaction: str = "AUTHENTICATED_CORE_RULE_ONLY"


class CombatSheet(FrozenModel):
    schema_version: Literal["TianxiaFoundry.CombatSheet.v1"]
    combat_sheet_id: str
    combat_sheet_version: Literal["1.0.0"]
    source_adapter: Literal["CharacterCombatAdapter.v1"]
    character_id: str
    display_name: str
    source_portable_package_sha256: str
    source_project_id: str
    source_project_revision: int
    source_event_head: str
    source_event_stream_sha256: str
    source_replay_state_hash: str
    source_content_lock_hash: str
    source_authority_identities: dict[str, Any]
    source_projection_identity: dict[str, Any]
    source_factory_build_identity: dict[str, Any]
    mechanics_lock_identity: dict[str, str]
    combat_compiler_identity: dict[str, str]
    readiness_status: Literal["COMBAT_READY", "COMBAT_PROJECTION_INCOMPLETE", "UNSUPPORTED_MECHANICS", "REQUIRES_RECOMPILATION", "SOURCE_IDENTITY_MISMATCH"]
    readiness_diagnostics: tuple[dict[str, Any], ...]
    combatant_stats: CombatantStats
    action_economy: ActionEconomy
    actions: tuple[LockedMechanic, ...]
    reactions: tuple[LockedMechanic, ...]
    augments: tuple[LockedMechanic, ...]
    passives: tuple[LockedMechanic, ...]
    resources: tuple[LockedMechanic, ...]
    movement: dict[str, Any]
    conditions: tuple[str, ...]
    concentration: dict[str, Any]
    zones_terrain_capabilities: tuple[str, ...]
    companions: tuple[dict[str, Any], ...]
    controller_policy_compatibility: dict[str, Any]
    execution_provenance: dict[str, Any]
    unsupported_coverage: tuple[dict[str, Any], ...]
    combat_events_committed: Literal[0]
    dice_rolled: Literal[0]
    encounter_created: Literal[False]
    controller_selected: Literal[False]
    sheet_commitment_sha256: str

    @model_validator(mode="after")
    def verify_sheet_commitment(self) -> "CombatSheet":
        raw = self.model_dump(mode="json")
        expected = raw.pop("sheet_commitment_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("combat sheet commitment mismatch")
        ids = [m.stable_id for group in (self.actions, self.reactions, self.augments, self.passives, self.resources) for m in group]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate action/reaction/passive/resource ID")
        return self


class StaticValidationReport(FrozenModel):
    schema_version: Literal["TianxiaFoundry.C3AStaticExecutionValidation.v1"]
    status: Literal["PASS", "FAIL"]
    combat_sheet_commitment_sha256: str
    mechanics_checked: int
    primitive_references_checked: int
    formula_contracts_checked: int
    target_contracts_checked: int
    condition_references_checked: int
    event_type_references_checked: int
    unresolved_placeholders: tuple[str, ...]
    prose_interpretation_used: Literal[False]
    combat_events_committed: Literal[0]
    dice_rolled: Literal[0]
    diagnostics: tuple[dict[str, Any], ...]
