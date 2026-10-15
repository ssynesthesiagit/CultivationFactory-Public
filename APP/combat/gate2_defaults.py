from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .canonical import canonical_bytes, canonical_sha256
from .models import StrictModel


class UniversalCombatDefault(StrictModel):
    default_id: str
    display_name: str
    authority: str
    authority_locator: str
    scope: str
    typed_rule: dict[str, Any]
    behavioral_consequence: str
    status: Literal["LOCKED_DEFAULT"] = "LOCKED_DEFAULT"


class UniversalCombatDefaultsLock(StrictModel):
    lock_schema: Literal["TianxiaGate2UniversalCombatDefaultsLock.v1"] = Field(
        default="TianxiaGate2UniversalCombatDefaultsLock.v1", alias="schema"
    )
    gate1_registry_snapshot_sha256: str
    continuation_prompt_sha256: str
    defaults: tuple[UniversalCombatDefault, ...]
    lock_sha256: str | None = None

    @model_validator(mode="after")
    def validate_lock(self) -> "UniversalCombatDefaultsLock":
        ids = [entry.default_id for entry in self.defaults]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("universal default IDs must be unique and sorted")
        return self

    def commitment_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", by_alias=True)
        payload.pop("lock_sha256", None)
        return payload

    def calculated_sha256(self) -> str:
        return canonical_sha256(self.commitment_payload())


GATE1_REGISTRY_SHA256 = "c3ed7fa15650d105fe375a2b6f3a1caf00a5ebc01ea8ffc1c23608dea6d403b1"
CONTINUATION_PROMPT_SHA256 = "34a2b126c1690759e4973d57ba94925ce80a8a4a3da0dcfd4d953c284df01c38"
DEFAULT_AUTHORITY = (
    "Owner-accepted Gate 2 continuation directive: use current Tianxia/5.5e-compatible "
    "normal-use defaults only for universal rules not controlled by character authority"
)


def build_universal_defaults_lock() -> UniversalCombatDefaultsLock:
    entries = [
        UniversalCombatDefault(
            default_id="default:combat.dodge",
            display_name="Dodge",
            authority=DEFAULT_AUTHORITY,
            authority_locator="Continuation Prompt R1 / universal defaults; 5.5e-compatible Dodge",
            scope="Basic system Action and Cui's uncommanded default",
            typed_rule={
                "economy": "ACTION",
                "expires": "START_OF_ACTOR_NEXT_TURN",
                "attack_effect": "DISADVANTAGE_IF_DODGER_CAN_SEE_ATTACKER",
                "dexterity_save_effect": "ADVANTAGE",
                "ends_early_if": ["INCAPACITATED", "SPEED_ZERO"],
            },
            behavioral_consequence=(
                "Cui and any actor using Dodge gain a bounded defensive state; it never mutates AC and "
                "does not apply against an unseen attacker."
            ),
        ),
        UniversalCombatDefault(
            default_id="default:combat.initiative_ties",
            display_name="Deterministic Initiative and Tie Resolution",
            authority=DEFAULT_AUTHORITY,
            authority_locator="Continuation Prompt R1 / universal defaults; normal-use deterministic tie policy",
            scope="Primary combatants; Cui is inserted immediately after Bai by character authority",
            typed_rule={
                "roll": "1d20_PLUS_EXACT_CHARACTER_INITIATIVE_BONUS",
                "advantage": "ONLY_WHEN_EXACT_CHARACTER_AUTHORITY_AND_ENCOUNTER_TAGS_QUALIFY",
                "descending_tie_breakers": [
                    "INITIATIVE_TOTAL",
                    "INITIATIVE_BONUS",
                    "DEXTERITY_SCORE",
                ],
                "final_tie_breaker": "LEXICOGRAPHIC_ENTITY_ID_ASCENDING",
                "companion_override": "CUI_IMMEDIATELY_AFTER_BAI_NO_SEPARATE_ROLL",
            },
            behavioral_consequence=(
                "The same seed and participants always produce one initiative order without a manual tie decision."
            ),
        ),
        UniversalCombatDefault(
            default_id="default:combat.opportunity_attack",
            display_name="Opportunity Attack and Disengage",
            authority=DEFAULT_AUTHORITY,
            authority_locator="Continuation Prompt R1 / universal defaults; 5.5e-compatible Opportunity Attack",
            scope="Visible hostile voluntarily leaving an actor's reach",
            typed_rule={
                "checkpoint": "LEAVE_REACH",
                "economy": "REACTION",
                "trigger": "VISIBLE_HOSTILE_VOLUNTARILY_LEAVES_REACH",
                "timing": "IMMEDIATELY_BEFORE_LEAVING_REACH",
                "effect": "ONE_SOURCE_AUTHORIZED_MELEE_ATTACK",
                "disengage_prevents": True,
                "teleport_triggers": False,
                "forced_movement_triggers": False,
                "unseen_target_triggers": False,
                "profile_selection": "EXACT_ACTOR_BASIC_MELEE_PROFILE_ELSE_SYSTEM_UNARMED_STRIKE",
            },
            behavioral_consequence=(
                "Movement paths expose a single bounded reaction candidate instead of allowing arbitrary attacks."
            ),
        ),
        UniversalCombatDefault(
            default_id="default:combat.temporary_hit_points",
            display_name="Temporary Hit Points",
            authority=DEFAULT_AUTHORITY,
            authority_locator="Continuation Prompt R1 / universal defaults; 5.5e-compatible temporary HP",
            scope="All temporary-hit-point grants",
            typed_rule={
                "stacking": "DO_NOT_ADD",
                "replacement": "KEEP_GREATER_AMOUNT_BY_DETERMINISTIC_DEFAULT",
                "absorption_order": "TEMP_HP_BEFORE_HP",
                "source_end_removes_grant": False,
                "expiration": "SOURCE_SPECIFIC_ELSE_UNTIL_DEPLETED_OR_MATCH_END",
                "can_restore_hp": False,
            },
            behavioral_consequence=(
                "Repeated grants cannot inflate defenses; a source ending does not retroactively remove retained temporary HP."
            ),
        ),
    ]
    lock = UniversalCombatDefaultsLock(
        gate1_registry_snapshot_sha256=GATE1_REGISTRY_SHA256,
        continuation_prompt_sha256=CONTINUATION_PROMPT_SHA256,
        defaults=tuple(sorted(entries, key=lambda x: x.default_id)),
    )
    return lock.model_copy(update={"lock_sha256": lock.calculated_sha256()})


def write_universal_defaults_lock(path: Path) -> UniversalCombatDefaultsLock:
    lock = build_universal_defaults_lock()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(lock.model_dump(mode="json", by_alias=True)) + b"\n")
    return lock


def load_universal_defaults_lock(path: Path) -> UniversalCombatDefaultsLock:
    lock = UniversalCombatDefaultsLock.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if lock.lock_sha256 != lock.calculated_sha256():
        raise ValueError("universal defaults lock commitment mismatch")
    return lock
