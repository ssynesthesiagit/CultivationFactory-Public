from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .canonical import canonical_bytes, canonical_sha256
from .diagnostics import CombatGate1Error, RecoveryDisposition, error
from .models import SHA256_RE, STABLE_ID_RE, StrictModel


GATE1_REGISTRY_SNAPSHOT_SHA256 = "c3ed7fa15650d105fe375a2b6f3a1caf00a5ebc01ea8ffc1c23608dea6d403b1"


class MechanicsLockStatus(StrEnum):
    LOCKED_EXECUTABLE = "LOCKED_EXECUTABLE"
    LOCKED_TRACKED_PASSIVE = "LOCKED_TRACKED_PASSIVE"
    LOCKED_NO_GATE2_USE = "LOCKED_NO_GATE2_USE"
    MATERIAL_UNRESOLVED = "MATERIAL_UNRESOLVED"
    NONMATERIAL_DEFERRED = "NONMATERIAL_DEFERRED"


class LockOverallStatus(StrEnum):
    PASS = "PASS"
    BLOCKED_GATE2B = "BLOCKED_GATE2B"


class ProfileKind(StrEnum):
    ATTACK = "ATTACK"
    MULTI_ATTACK = "MULTI_ATTACK"
    SAVE = "SAVE"
    ATTACK_THEN_SAVE = "ATTACK_THEN_SAVE"
    STATE_OR_STANCE = "STATE_OR_STANCE"
    ZONE = "ZONE"
    MOVE = "MOVE"
    COMMAND_COMPANION = "COMMAND_COMPANION"
    ON_HIT_OPTION = "ON_HIT_OPTION"
    REACTION_AC = "REACTION_AC"
    REACTION_REDUCTION = "REACTION_REDUCTION"
    REACTION_PREVENTION = "REACTION_PREVENTION"
    PASSIVE_TRIGGER = "PASSIVE_TRIGGER"
    RESOURCE = "RESOURCE"
    SYSTEM_RULE = "SYSTEM_RULE"
    CONDITION = "CONDITION"
    COMPANION = "COMPANION"


class Economy(StrEnum):
    ACTION = "ACTION"
    BONUS_ACTION = "BONUS_ACTION"
    REACTION = "REACTION"
    MOVEMENT = "MOVEMENT"
    ON_HIT_OPTION = "ON_HIT_OPTION"
    RIDER = "RIDER"
    PASSIVE = "PASSIVE"
    SYSTEM = "SYSTEM"
    NONE = "NONE"


class ConditionalGate(StrEnum):
    ALWAYS = "ALWAYS"
    ON_HIT = "ON_HIT"
    ON_MISS = "ON_MISS"
    ON_CRITICAL_HIT = "ON_CRITICAL_HIT"
    ON_SAVE_FAIL = "ON_SAVE_FAIL"
    ON_SAVE_SUCCESS = "ON_SAVE_SUCCESS"
    ON_DAMAGE_COMMIT = "ON_DAMAGE_COMMIT"
    ON_CONCENTRATION_END = "ON_CONCENTRATION_END"
    AT_TURN_START = "AT_TURN_START"
    AT_TURN_END = "AT_TURN_END"
    ON_ENTER_ZONE = "ON_ENTER_ZONE"
    ON_LEAVE_ZONE = "ON_LEAVE_ZONE"


class SourceBundleIdentity(StrictModel):
    role: str
    filename: str
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    availability: Literal["VERIFIED", "NOT_SUPPLIED"]
    note: str

    @model_validator(mode="after")
    def validate_identity(self) -> "SourceBundleIdentity":
        if self.availability == "VERIFIED":
            if self.sha256 is None or not SHA256_RE.fullmatch(self.sha256):
                raise ValueError("verified bundle requires lowercase SHA-256")
            if self.size_bytes is None:
                raise ValueError("verified bundle requires size_bytes")
        return self


class TargetingSpec(StrictModel):
    target_kind: str
    range_ft: int | None = Field(default=None, ge=0)
    reach_ft: int | None = Field(default=None, ge=0)
    radius_ft: int | None = Field(default=None, ge=0)
    requires_line_of_sight: bool | None = None
    geometry: str | None = None


class ResourceCost(StrictModel):
    resource_id: str
    amount: int = Field(ge=0)
    timing: str
    optional: bool = False

    @model_validator(mode="after")
    def validate_resource(self) -> "ResourceCost":
        if not STABLE_ID_RE.fullmatch(self.resource_id):
            raise ValueError(f"invalid resource ID: {self.resource_id}")
        return self


class DiceExpression(StrictModel):
    count: int = Field(ge=1)
    sides: int = Field(ge=2)
    modifier: int = 0


class AttackSpec(StrictModel):
    bonus: int
    attack_count: int = Field(default=1, ge=1)
    natural_1_misses: bool = True
    natural_20_critical: bool = True


class SaveSpec(StrictModel):
    ability: Literal["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    dc: int = Field(ge=1)
    automatic_natural_results: bool = False


class DamageSpec(StrictModel):
    dice: DiceExpression
    damage_type: str
    critical_doubles_dice: bool = True


class EffectSpec(StrictModel):
    gate: ConditionalGate
    primitive_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_primitive(self) -> "EffectSpec":
        if not STABLE_ID_RE.fullmatch(self.primitive_id):
            raise ValueError(f"invalid primitive ID: {self.primitive_id}")
        return self


class DurationSpec(StrictModel):
    expiration: str
    source_actor_bound: bool = False
    target_actor_bound: bool = False


class ExecutableMechanicProfile(StrictModel):
    profile_schema: Literal["TianxiaCombatExecutableMechanic.v1"] = Field(
        default="TianxiaCombatExecutableMechanic.v1", alias="schema"
    )
    source_definition_id: str
    display_name: str
    source_authority: str
    source_locator: str
    profile_kind: ProfileKind
    economy: Economy
    targeting: TargetingSpec | None = None
    prerequisites: tuple[str, ...] = ()
    costs: tuple[ResourceCost, ...] = ()
    attack: AttackSpec | None = None
    save: SaveSpec | None = None
    post_hit_save: SaveSpec | None = None
    damage: DamageSpec | None = None
    effects: tuple[EffectSpec, ...] = ()
    duration: DurationSpec | None = None
    concentration: bool | None = None
    reaction_checkpoint: str | None = None
    optional_follow_up: str | None = None
    primitive_ids: tuple[str, ...] = ()
    fidelity_consequence: str
    status: MechanicsLockStatus
    unresolved_fields: tuple[str, ...] = ()
    resolution_request: str | None = None

    @model_validator(mode="after")
    def validate_profile(self) -> "ExecutableMechanicProfile":
        if not STABLE_ID_RE.fullmatch(self.source_definition_id):
            raise ValueError(f"invalid source_definition_id: {self.source_definition_id}")
        if tuple(sorted(set(self.primitive_ids))) != self.primitive_ids:
            raise ValueError("primitive_ids must be unique and sorted")
        for primitive_id in self.primitive_ids:
            if not primitive_id.startswith("primitive:") or not STABLE_ID_RE.fullmatch(primitive_id):
                raise ValueError(f"invalid primitive ID: {primitive_id}")
        if self.status == MechanicsLockStatus.MATERIAL_UNRESOLVED:
            if not self.unresolved_fields or not self.resolution_request:
                raise ValueError("material unresolved profile requires unresolved_fields and resolution_request")
        elif self.unresolved_fields or self.resolution_request:
            raise ValueError("resolved/deferred profile cannot retain unresolved fields")
        if self.status == MechanicsLockStatus.LOCKED_NO_GATE2_USE and self.primitive_ids:
            raise ValueError("LOCKED_NO_GATE2_USE may not reference executable primitives")
        return self


class ExecutableMechanicsLock(StrictModel):
    lock_schema: Literal["TianxiaGate2ExecutableMechanicsLock.v1"] = Field(
        default="TianxiaGate2ExecutableMechanicsLock.v1", alias="schema"
    )
    gate1_registry_snapshot_sha256: str
    source_bundle_identities: tuple[SourceBundleIdentity, ...]
    allowed_primitive_ids: tuple[str, ...]
    profiles: tuple[ExecutableMechanicProfile, ...]
    material_unresolved_count: int = Field(ge=0)
    status: LockOverallStatus
    lock_sha256: str | None = None

    @model_validator(mode="after")
    def validate_lock(self) -> "ExecutableMechanicsLock":
        if self.gate1_registry_snapshot_sha256 != GATE1_REGISTRY_SNAPSHOT_SHA256:
            raise ValueError("Gate 1 registry snapshot identity mismatch")
        if tuple(sorted(set(self.allowed_primitive_ids))) != self.allowed_primitive_ids:
            raise ValueError("allowed_primitive_ids must be unique and sorted")
        profile_ids = [p.source_definition_id for p in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("source_definition_id values must be unique")
        if tuple(sorted(profile_ids)) != tuple(profile_ids):
            raise ValueError("profiles must be sorted by source_definition_id")
        unresolved = sum(p.status == MechanicsLockStatus.MATERIAL_UNRESOLVED for p in self.profiles)
        if self.material_unresolved_count != unresolved:
            raise ValueError("material_unresolved_count does not match profiles")
        expected_status = LockOverallStatus.PASS if unresolved == 0 else LockOverallStatus.BLOCKED_GATE2B
        if self.status != expected_status:
            raise ValueError("overall status is inconsistent with unresolved count")
        allowed = set(self.allowed_primitive_ids)
        used = {pid for p in self.profiles for pid in p.primitive_ids}
        if not used <= allowed:
            raise ValueError(f"profiles reference unsupported primitives: {sorted(used - allowed)}")
        return self

    def commitment_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", by_alias=True)
        payload.pop("lock_sha256", None)
        return payload

    def calculated_sha256(self) -> str:
        return canonical_sha256(self.commitment_payload())


def load_executable_mechanics_lock(path: Path) -> ExecutableMechanicsLock:
    document = json.loads(path.read_text(encoding="utf-8"))
    lock = ExecutableMechanicsLock.model_validate(document)
    if lock.lock_sha256 is not None and lock.lock_sha256 != lock.calculated_sha256():
        raise ValueError("mechanics lock commitment mismatch")
    return lock


def write_executable_mechanics_lock(lock: ExecutableMechanicsLock, path: Path) -> ExecutableMechanicsLock:
    with_hash = lock.model_copy(update={"lock_sha256": lock.calculated_sha256()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(with_hash.model_dump(mode="json", by_alias=True)) + b"\n")
    return with_hash


def assert_gate2b_ready(lock: ExecutableMechanicsLock) -> None:
    if lock.material_unresolved_count:
        unresolved_ids = [
            p.source_definition_id
            for p in lock.profiles
            if p.status == MechanicsLockStatus.MATERIAL_UNRESOLVED
        ]
        raise error(
            "COMBAT_GATE2_MECHANICS_LOCK_UNRESOLVED",
            (
                f"Gate 2B cannot start because {lock.material_unresolved_count} material mechanics "
                "lack exact executable authority."
            ),
            entity_id=unresolved_ids[0] if unresolved_ids else None,
            phase="GATE2A_MECHANICS_LOCK",
            subsystem="COMBAT_MECHANICS_LOCK",
            source_definition=unresolved_ids[0] if unresolved_ids else None,
            recommended_action="Supply the newest exact four-character source bundle or an explicit mechanics amendment.",
            recovery=RecoveryDisposition.STOP,
            details={"material_unresolved_ids": unresolved_ids},
        )
