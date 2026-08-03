from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from app.core import FoundryError
from portable_character.service import PortableCharacterPackageService

from .canonical import canonical_sha256, sha256_file
from .character_runtime_adapter import (
    CharacterCombatRuntimeAdapter,
    RUNTIME_ADAPTER_ID,
    RUNTIME_ADAPTER_VERSION,
    RUNTIME_ENGINE_VERSION,
    RuntimeResourceInitialization,
)
from .footprints import standard_actor_footprint
from .models import StrictModel

CANDIDATE_LIBRARY_SCHEMA = "TianxiaCombatantLibraryEntry.v1"
CANDIDATE_INVENTORY_SCHEMA = "TianxiaCombatantLibraryInventory.v1"
RESOURCE_VALIDATION_SCHEMA = "TianxiaEncounterResourceInitializationValidation.v1"
DRAFT_SCHEMA = "TianxiaPreEncounterDraft.v1"
DRAFT_VALIDATION_SCHEMA = "TianxiaPreEncounterDraftValidation.v1"
RESOURCE_CONTRACT_SCHEMA = "TianxiaEncounterResourceInitializationContract.v1"
RUNTIME_READY_SEMANTICS = "RUNTIME_READY_PRE_ENCOUNTER"


class ResourceInitializationRequirement(StrictModel):
    resource_id: str
    display_name: str
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)
    current_value_required_at_encounter_setup: Literal[True] = True
    package_build_state_is_encounter_authority: Literal[False] = False


class CombatantLibraryEntry(StrictModel):
    schema_name: Literal[CANDIDATE_LIBRARY_SCHEMA] = Field(default=CANDIDATE_LIBRARY_SCHEMA, alias="schema")
    entry_id: str
    character_project_id: str
    display_name: str
    source_package_sha256: str
    package_role: str
    package_schema_version: str
    project_revision: int = Field(ge=0)
    event_head_hash: str
    replay_state_hash: str
    content_lock_hash: str
    combat_sheet_id: str
    combat_sheet_version: str
    combat_sheet_commitment_sha256: str
    mechanics_lock_sha256: str
    primitive_registry_sha256: str
    runtime_adapter_id: Literal[RUNTIME_ADAPTER_ID] = RUNTIME_ADAPTER_ID
    runtime_adapter_version: Literal[RUNTIME_ADAPTER_VERSION] = RUNTIME_ADAPTER_VERSION
    runtime_engine_version: Literal[RUNTIME_ENGINE_VERSION] = RUNTIME_ENGINE_VERSION
    actor_template_commitment_sha256: str
    actor_id: str
    hp_maximum: int = Field(ge=1)
    armor_class: int = Field(ge=0)
    initiative_bonus: int
    speed_ft: int = Field(ge=0)
    ability_scores: dict[str, int]
    saving_throws: dict[str, int]
    skills: dict[str, int]
    footprint_contract: dict[str, Any]
    action_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    passive_ids: tuple[str, ...]
    augment_ids: tuple[str, ...]
    resource_maxima: dict[str, int]
    resource_initialization_requirements: tuple[ResourceInitializationRequirement, ...]
    gm_readiness: Literal["GM_SCREEN_SOURCE_CONSUMER_VERIFIED"]
    combat_runtime_readiness: Literal["COMBAT_RUNTIME_READY"]
    combat_ready_semantics: Literal[RUNTIME_READY_SEMANTICS]
    encounter_status: Literal["NOT_ATTEMPTED"]
    controller_status: Literal["NOT_ATTEMPTED"]
    owner_readiness_label: Literal["Combat Runtime Ready"] = "Combat Runtime Ready"
    owner_encounter_label: Literal["Encounter Not Attempted"] = "Encounter Not Attempted"
    provenance: dict[str, Any]
    validation_build_id: str

    @model_validator(mode="after")
    def validate_deterministic_entry(self) -> "CombatantLibraryEntry":
        if tuple(sorted(self.action_ids)) != self.action_ids:
            raise ValueError("action IDs must be sorted")
        if tuple(sorted(self.reaction_ids)) != self.reaction_ids:
            raise ValueError("reaction IDs must be sorted")
        if tuple(sorted(self.passive_ids)) != self.passive_ids:
            raise ValueError("passive IDs must be sorted")
        if tuple(sorted(self.augment_ids)) != self.augment_ids:
            raise ValueError("augment IDs must be sorted")
        if set(self.resource_maxima) != {"resource:core.qi", "resource:core.martial_focus"}:
            raise ValueError("runtime-ready Fire/Qi resources must be exactly Qi and Martial Focus")
        if self.resource_maxima["resource:core.qi"] != 15:
            raise ValueError("Qi maximum must be 15")
        if self.resource_maxima["resource:core.martial_focus"] != 1:
            raise ValueError("Martial Focus maximum must be 1")
        return self


class CandidateBlock(StrictModel):
    installed_record: str
    project_id: str | None = None
    package_sha256: str | None = None
    code: str
    message: str
    details: Any = None


class CombatantLibraryInventory(StrictModel):
    schema_name: Literal[CANDIDATE_INVENTORY_SCHEMA] = Field(default=CANDIDATE_INVENTORY_SCHEMA, alias="schema")
    status: Literal["COMBATANT_LIBRARY_READY_PRE_ENCOUNTER_DRAFT"] = "COMBATANT_LIBRARY_READY_PRE_ENCOUNTER_DRAFT"
    accepted_candidates: tuple[CombatantLibraryEntry, ...]
    blocked_candidates: tuple[CandidateBlock, ...]
    accepted_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    duplicate_identical_count: int = Field(ge=0)
    active_persisted_matches_are_separate: Literal[True] = True
    accepted_demo_encounter_is_separate: Literal[True] = True
    inventory_commitment_sha256: str

    @model_validator(mode="after")
    def validate_inventory(self) -> "CombatantLibraryInventory":
        if self.accepted_count != len(self.accepted_candidates):
            raise ValueError("accepted count mismatch")
        if self.blocked_count != len(self.blocked_candidates):
            raise ValueError("blocked count mismatch")
        raw = self.model_dump(mode="json", by_alias=True)
        expected = raw.pop("inventory_commitment_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("inventory commitment mismatch")
        return self


class ResourceInitializationValidation(StrictModel):
    schema_name: Literal[RESOURCE_VALIDATION_SCHEMA] = Field(default=RESOURCE_VALIDATION_SCHEMA, alias="schema")
    candidate_entry_id: str
    valid: bool
    status: Literal["VALID", "BLOCKED_RESOURCE_INITIALIZATION"]
    values: dict[str, int | None]
    provenance_kind: Literal["ENCOUNTER_AUTHORITY", "TEST_FIXTURE"] | None
    provenance_id: str | None
    canonical_owner_choice: Literal[False] = False
    noncanonical_test_fixture: bool
    unresolved_requirements: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]
    package_current_values_used: Literal[False] = False
    package_mutated: Literal[False] = False
    validation_commitment_sha256: str

    @model_validator(mode="after")
    def validate_commitment(self) -> "ResourceInitializationValidation":
        raw = self.model_dump(mode="json", by_alias=True)
        expected = raw.pop("validation_commitment_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("resource validation commitment mismatch")
        return self


class DraftParticipantSlot(StrictModel):
    slot_id: str
    candidate_entry_id: str
    source_package_sha256: str
    actor_id: str
    display_name: str
    team_id: str
    resource_initialization: dict[str, Any]
    actor_template_commitment_sha256: str
    token_position: None = None
    initiative: None = None
    controller_assignment: None = None


class DraftUnresolvedRequirement(StrictModel):
    code: str
    message: str
    blocking_for_pre_placement_validation: bool
    required_before_live_encounter: Literal[True] = True


class PreEncounterDraftValidation(StrictModel):
    schema_name: Literal[DRAFT_VALIDATION_SCHEMA] = Field(default=DRAFT_VALIDATION_SCHEMA, alias="schema")
    supplied_candidates_valid: bool
    supplied_resources_valid: bool
    supplied_team_assignments_valid: bool
    supplied_battlefield_valid: bool
    no_positions_committed: Literal[True] = True
    no_initiative_committed: Literal[True] = True
    no_controllers_committed: Literal[True] = True
    no_dice_rolled: Literal[True] = True
    no_match_created: Literal[True] = True
    no_events_persisted: Literal[True] = True
    diagnostics: tuple[dict[str, Any], ...]


class PreEncounterDraft(StrictModel):
    schema_name: Literal[DRAFT_SCHEMA] = Field(default=DRAFT_SCHEMA, alias="schema")
    draft_version: Literal["1.0.0"] = "1.0.0"
    draft_id: str
    draft_commitment_sha256: str
    source_candidate_ids: tuple[str, ...]
    source_package_hashes: tuple[str, ...]
    participant_slots: tuple[DraftParticipantSlot, ...]
    battlefield_choice: dict[str, Any] | None
    unresolved_requirements: tuple[DraftUnresolvedRequirement, ...]
    validation_report: PreEncounterDraftValidation
    readiness_state: Literal[
        "DRAFT_INCOMPLETE",
        "DRAFT_VALIDATED_PRE_PLACEMENT",
        "BLOCKED_INVALID_CANDIDATE",
        "BLOCKED_RESOURCE_INITIALIZATION",
        "BLOCKED_TEAM_ASSIGNMENT",
        "BLOCKED_BATTLEFIELD_SELECTION",
    ]
    actor_template_commitment_sha256: str
    token_positions: tuple[()] = ()
    initiative_order: tuple[()] = ()
    controller_assignments: tuple[()] = ()
    journal_path: None = None
    match_directory: None = None
    persisted_event_count: Literal[0] = 0
    project_events_written: Literal[0] = 0
    is_match: Literal[False] = False
    is_encounter_execution_record: Literal[False] = False
    can_roll_dice: Literal[False] = False
    can_start_turn: Literal[False] = False
    can_invoke_controllers: Literal[False] = False
    persistent: Literal[False] = False

    @model_validator(mode="after")
    def validate_draft_commitment(self) -> "PreEncounterDraft":
        raw = self.model_dump(mode="json", by_alias=True)
        expected = raw.pop("draft_commitment_sha256")
        draft_id = raw.pop("draft_id")
        commitment = canonical_sha256(raw)
        if commitment != expected:
            raise ValueError("draft commitment mismatch")
        if draft_id != f"pre-encounter-draft:{commitment[:24]}":
            raise ValueError("draft ID is not derived from canonical commitment")
        return self


class CombatantLibraryService:
    """Read-only installed Character discovery and non-persistent draft preview.

    The service never follows a package path supplied by an API caller or by an
    install pointer. A package is read only from the existing trusted installed
    Character directory beside its ``current.json`` verification pointer.
    """

    def __init__(self, source_root: Path, data_root: Path):
        self.source_root = Path(source_root).resolve()
        self.data_root = Path(data_root).resolve()
        self.install_root = self.data_root / "portable_characters"
        self._battlefield_path = self.source_root / "combat_gate1" / "generated" / "Battlefield.json"

    @staticmethod
    def _read_zip_json(adapter: CharacterCombatRuntimeAdapter, name: str) -> dict[str, Any]:
        try:
            return json.loads(adapter.files[name])
        except KeyError as exc:
            raise FoundryError("C3B_RUNTIME_CONTRACT_MISSING", f"The installed Character package is missing {name}.") from exc
        except json.JSONDecodeError as exc:
            raise FoundryError("C3B_RUNTIME_CONTRACT_INVALID", f"The installed Character package contains invalid JSON in {name}.") from exc

    @staticmethod
    def _block(record: Path, exc: Exception, *, project_id: str | None = None, package_sha: str | None = None) -> CandidateBlock:
        if isinstance(exc, FoundryError):
            return CandidateBlock(
                installed_record=str(record),
                project_id=project_id,
                package_sha256=package_sha,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        return CandidateBlock(
            installed_record=str(record),
            project_id=project_id,
            package_sha256=package_sha,
            code="C3B_CANDIDATE_VALIDATION_FAILED",
            message=str(exc),
        )

    def _candidate_from_record(self, pointer_path: Path) -> CombatantLibraryEntry:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        project_id = str(pointer.get("project_id") or "")
        if not project_id:
            raise FoundryError("C3B_INSTALL_POINTER_INVALID", "The installed Character pointer has no project ID.")
        package = pointer_path.parent / "current.zip"
        if not package.is_file():
            raise FoundryError("C3B_INSTALLED_PACKAGE_MISSING", "The installed Character package is missing.")
        actual_sha = sha256_file(package)
        if pointer.get("package_sha256") != actual_sha:
            raise FoundryError(
                "C3B_INSTALLED_PACKAGE_STALE",
                "The installed Character package no longer matches its verification pointer.",
                details={"expected": pointer.get("package_sha256"), "actual": actual_sha},
            )

        adapter = CharacterCombatRuntimeAdapter(package)
        audit = adapter.audit
        manifest = audit["manifest"]
        readiness = audit["readiness"]
        if manifest.get("project_id") != project_id:
            raise FoundryError("C3B_PROJECT_IDENTITY_MISMATCH", "Installed pointer and package project identities differ.")
        if manifest.get("package_role") != "portable_completed_character_combat_runtime_ready":
            raise FoundryError("C3B_PACKAGE_ROLE_UNSUPPORTED", "Only completed portable Character packages can enter the combatant library.")
        if manifest.get("schema_version") != "TianxiaFoundry.PortableCharacterPackage.v1":
            raise FoundryError("C3B_PACKAGE_SCHEMA_UNSUPPORTED", "The portable Character package schema is unsupported.")

        expected_readiness = {
            "advancement": "ADVANCEMENT_READY",
            "character_sheet": "CHARACTER_SHEET_READY",
            "gm_screen": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "combat": "COMBAT_READY",
            "combat_runtime": "COMBAT_RUNTIME_READY",
            "combat_ready_semantics": RUNTIME_READY_SEMANTICS,
            "combat_sheet": "COMBAT_SHEET_READY",
            "encounter": "NOT_ATTEMPTED",
            "controller_selection": "NOT_ATTEMPTED",
            "encounter_time_resource_initialization": "REQUIRED",
        }
        mismatch = {key: {"expected": value, "actual": readiness.get(key)} for key, value in expected_readiness.items() if readiness.get(key) != value}
        if mismatch:
            raise FoundryError(
                "C3B_RUNTIME_READINESS_INCOMPATIBLE",
                "The Character package is not exactly runtime-ready for pre-encounter setup.",
                details=mismatch,
            )

        combat_readiness = self._read_zip_json(adapter, "combat/Combat_Readiness.json")
        if (
            combat_readiness.get("status") != "COMBAT_READY"
            or combat_readiness.get("combat_ready_semantics") != RUNTIME_READY_SEMANTICS
            or combat_readiness.get("runtime_validation") != "PASS"
            or combat_readiness.get("runtime_support_mechanic_count") != 30
            or combat_readiness.get("runtime_primitive_handler_count") != 19
            or combat_readiness.get("persisted_combat_events") != 0
            or combat_readiness.get("persistent_match_created") is not False
        ):
            raise FoundryError("C3B_COMBAT_READINESS_INVALID", "The sealed Combat readiness record is incompatible with C3B.")

        resource_contract = self._read_zip_json(adapter, "combat/Runtime_Resource_Initialization_Contract.json")
        expected_resources = [
            {"resource_id": "resource:core.qi", "minimum": 0, "maximum": 15, "current": "REQUIRED_AT_ENCOUNTER_TIME"},
            {"resource_id": "resource:core.martial_focus", "minimum": 0, "maximum": 1, "current": "REQUIRED_AT_ENCOUNTER_TIME"},
        ]
        if (
            resource_contract.get("schema") != RESOURCE_CONTRACT_SCHEMA
            or resource_contract.get("resources") != expected_resources
            or resource_contract.get("required_before_actor_instantiation") is not True
            or resource_contract.get("owner_package_contains_current_values") is not False
            or resource_contract.get("provenance_required") is not True
            or resource_contract.get("persistent") is not False
            or resource_contract.get("canonical_owner_choice") is not False
        ):
            raise FoundryError("C3B_RESOURCE_CONTRACT_INVALID", "The sealed resource-initialization contract is incompatible with C3B.")

        support = self._read_zip_json(adapter, "combat/Runtime_Support_Matrix.json")
        rows = support.get("mechanics") or support.get("rows") or []
        if support.get("status") != "PASS" or support.get("runtime_executable_count") != 30 or support.get("static_only_count") != 0:
            raise FoundryError("C3B_RUNTIME_SUPPORT_MATRIX_INVALID", "The runtime support matrix is incomplete.")
        if len(rows) != 30 or any(row.get("status") not in {"RUNTIME_EXECUTABLE", "RUNTIME_EXECUTABLE_AFTER_BOUNDED_EXTENSION"} for row in rows):
            raise FoundryError("C3B_RUNTIME_SUPPORT_MATRIX_INVALID", "The runtime support matrix contains a non-runtime mechanic.")

        sheet = adapter.sheet
        if (
            sheet.readiness_status != "COMBAT_READY"
            or sheet.source_project_id != project_id
            or sheet.source_project_revision != manifest.get("project_revision")
            or sheet.source_event_head != manifest.get("event_head_hash")
            or sheet.source_replay_state_hash != manifest.get("replay_state_hash")
            or sheet.source_content_lock_hash != manifest.get("content_lock_hash")
            or sheet.encounter_created is not False
            or sheet.controller_selected is not False
            or sheet.combat_events_committed != 0
        ):
            raise FoundryError("C3B_COMBAT_SHEET_IDENTITY_INVALID", "The Combat Sheet does not match the installed Character authority.")

        # Build only with explicit noncanonical fixture values for structural
        # validation. No value is copied from the package's saved build state.
        validation_bundle = adapter.build_bundle(
            RuntimeResourceInitialization(
                qi_current=0,
                martial_focus_current=0,
                provenance_kind="TEST_FIXTURE",
                provenance_id="c3b:candidate-structural-validation",
            )
        )
        if len(validation_bundle.support_matrix) != 30 or len(validation_bundle.primitive_bindings) != 19:
            raise FoundryError("C3B_RUNTIME_ADAPTER_INVALID", "The runtime adapter did not produce the accepted support surface.")

        actor = validation_bundle.actor_template
        footprint = standard_actor_footprint().model_dump(mode="json", by_alias=True)
        actor_for_commitment = actor.model_dump(mode="json")
        actor_for_commitment["resources"] = [
            {"resource_id": row.resource_id, "maximum": row.maximum, "initial": "REQUIRED_AT_ENCOUNTER_TIME"}
            for row in actor.resources
        ]
        actor_commitment = canonical_sha256(actor_for_commitment)
        entry_seed = {
            "project_id": project_id,
            "package_sha256": actual_sha,
            "combat_sheet_commitment": sheet.sheet_commitment_sha256,
            "mechanics_lock": adapter.lock.lock_sha256,
            "primitive_registry": adapter.registry.registry_sha256,
            "runtime_adapter": RUNTIME_ADAPTER_ID,
            "runtime_adapter_version": RUNTIME_ADAPTER_VERSION,
            "runtime_engine_version": RUNTIME_ENGINE_VERSION,
        }
        entry_id = f"combatant-library:{project_id}:{actual_sha[:16]}"
        validation_build_id = f"c3b-validation:{canonical_sha256(entry_seed)}"
        requirements = (
            ResourceInitializationRequirement(resource_id="resource:core.qi", display_name="Qi", minimum=0, maximum=15),
            ResourceInitializationRequirement(resource_id="resource:core.martial_focus", display_name="Martial Focus", minimum=0, maximum=1),
        )
        return CombatantLibraryEntry(
            entry_id=entry_id,
            character_project_id=project_id,
            display_name=sheet.display_name,
            source_package_sha256=actual_sha,
            package_role=str(manifest.get("package_role")),
            package_schema_version=str(manifest.get("schema_version")),
            project_revision=sheet.source_project_revision,
            event_head_hash=sheet.source_event_head,
            replay_state_hash=sheet.source_replay_state_hash,
            content_lock_hash=sheet.source_content_lock_hash,
            combat_sheet_id=sheet.combat_sheet_id,
            combat_sheet_version=sheet.combat_sheet_version,
            combat_sheet_commitment_sha256=sheet.sheet_commitment_sha256,
            mechanics_lock_sha256=adapter.lock.lock_sha256,
            primitive_registry_sha256=adapter.registry.registry_sha256,
            actor_template_commitment_sha256=actor_commitment,
            actor_id=actor.entity_id,
            hp_maximum=actor.maximum_hp,
            armor_class=actor.armor_class,
            initiative_bonus=actor.initiative_bonus,
            speed_ft=actor.speed_ft,
            ability_scores=dict(sheet.combatant_stats.ability_scores),
            saving_throws=dict(actor.saving_throws),
            skills=dict(actor.skills),
            footprint_contract=footprint,
            action_ids=tuple(sorted(actor.action_ids)),
            reaction_ids=tuple(sorted(actor.reaction_ids)),
            passive_ids=tuple(sorted(actor.passive_ids)),
            augment_ids=tuple(sorted(actor.augment_ids)),
            resource_maxima={row.resource_id: row.maximum for row in actor.resources},
            resource_initialization_requirements=requirements,
            gm_readiness="GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            combat_runtime_readiness="COMBAT_RUNTIME_READY",
            combat_ready_semantics=RUNTIME_READY_SEMANTICS,
            encounter_status="NOT_ATTEMPTED",
            controller_status="NOT_ATTEMPTED",
            provenance={
                "installed_pointer_schema": pointer.get("schema_version"),
                "installed_pointer_status": pointer.get("status"),
                "portable_package_audit": "PASS",
                "exact_checksum_coverage": "PASS",
                "source_identity_validation": "PASS",
                "combat_sheet_validation": "PASS",
                "mechanics_lock_validation": "PASS",
                "primitive_registry_validation": "PASS",
                "runtime_adapter_validation": "PASS",
                "runtime_support_matrix_validation": "PASS",
                "resource_initialization_contract_validation": "PASS",
                "display_prose_parsed": False,
                "package_build_state_resource_values_used": False,
            },
            validation_build_id=validation_build_id,
        )

    def inventory(self) -> CombatantLibraryInventory:
        accepted_by_project: dict[str, CombatantLibraryEntry] = {}
        blocks: list[CandidateBlock] = []
        duplicate_identical = 0
        conflicted_projects: set[str] = set()
        records = sorted(self.install_root.glob("*/current.json")) if self.install_root.is_dir() else []
        for pointer_path in records:
            project_id = None
            package_sha = None
            try:
                try:
                    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                    project_id = str(pointer.get("project_id") or "") or None
                    package_sha = str(pointer.get("package_sha256") or "") or None
                except Exception:
                    pointer = {}
                entry = self._candidate_from_record(pointer_path)
                if entry.character_project_id in conflicted_projects:
                    blocks.append(CandidateBlock(
                        installed_record=str(pointer_path),
                        project_id=entry.character_project_id,
                        package_sha256=entry.source_package_sha256,
                        code="C3B_SAME_ID_DIFFERENT_PACKAGE_CONFLICT",
                        message="This project ID is already blocked by conflicting installed package hashes.",
                    ))
                    continue
                existing = accepted_by_project.get(entry.character_project_id)
                if existing is None:
                    accepted_by_project[entry.character_project_id] = entry
                elif existing.source_package_sha256 == entry.source_package_sha256:
                    duplicate_identical += 1
                else:
                    accepted_by_project.pop(entry.character_project_id, None)
                    conflicted_projects.add(entry.character_project_id)
                    blocks.append(CandidateBlock(
                        installed_record=str(pointer_path),
                        project_id=entry.character_project_id,
                        package_sha256=entry.source_package_sha256,
                        code="C3B_SAME_ID_DIFFERENT_PACKAGE_CONFLICT",
                        message="Multiple installed packages use the same project ID with different package hashes.",
                        details={"first": existing.source_package_sha256, "second": entry.source_package_sha256},
                    ))
            except Exception as exc:
                blocks.append(self._block(pointer_path, exc, project_id=project_id, package_sha=package_sha))
        accepted = tuple(sorted(accepted_by_project.values(), key=lambda row: row.entry_id))
        blocked = tuple(sorted(blocks, key=lambda row: (row.project_id or "", row.installed_record, row.code)))
        raw = {
            "schema": CANDIDATE_INVENTORY_SCHEMA,
            "status": "COMBATANT_LIBRARY_READY_PRE_ENCOUNTER_DRAFT",
            "accepted_candidates": [row.model_dump(mode="json", by_alias=True) for row in accepted],
            "blocked_candidates": [row.model_dump(mode="json") for row in blocked],
            "accepted_count": len(accepted),
            "blocked_count": len(blocked),
            "duplicate_identical_count": duplicate_identical,
            "active_persisted_matches_are_separate": True,
            "accepted_demo_encounter_is_separate": True,
        }
        raw["inventory_commitment_sha256"] = canonical_sha256(raw)
        return CombatantLibraryInventory.model_validate(raw)

    def candidate(self, entry_id: str) -> CombatantLibraryEntry:
        for row in self.inventory().accepted_candidates:
            if row.entry_id == entry_id:
                return row
        raise FoundryError("C3B_CANDIDATE_NOT_FOUND", "No installed runtime-ready combat candidate has that stable entry ID.", status_code=404)

    def _package_for_entry(self, entry: CombatantLibraryEntry) -> Path:
        matches: list[Path] = []
        for pointer in sorted(self.install_root.glob("*/current.json")) if self.install_root.is_dir() else []:
            package = pointer.parent / "current.zip"
            if not package.is_file() or sha256_file(package) != entry.source_package_sha256:
                continue
            try:
                data = json.loads(pointer.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("project_id") == entry.character_project_id:
                matches.append(package)
        if not matches:
            raise FoundryError("C3B_CANDIDATE_PACKAGE_STALE", "The installed candidate package is no longer available.")
        return matches[0]

    def validate_resource_initialization(
        self,
        entry_id: str,
        *,
        qi_current: int | None,
        martial_focus_current: int | None,
        provenance_kind: str | None,
        provenance_id: str | None,
    ) -> ResourceInitializationValidation:
        self.candidate(entry_id)
        unresolved: list[str] = []
        diagnostics: list[dict[str, Any]] = []
        if qi_current is None:
            unresolved.append("Current Qi is required.")
        if martial_focus_current is None:
            unresolved.append("Current Martial Focus is required.")
        if provenance_kind not in {"ENCOUNTER_AUTHORITY", "TEST_FIXTURE"}:
            unresolved.append("Resource provenance kind is required.")
        if not str(provenance_id or "").strip():
            unresolved.append("Resource provenance ID is required.")
        valid = False
        if not unresolved:
            try:
                RuntimeResourceInitialization(
                    qi_current=qi_current,
                    martial_focus_current=martial_focus_current,
                    provenance_kind=provenance_kind,
                    provenance_id=str(provenance_id),
                    canonical_owner_choice=False,
                )
                valid = True
            except ValidationError as exc:
                diagnostics.extend(exc.errors(include_url=False))
        if diagnostics:
            unresolved.append("One or more resource values are outside the accepted encounter-time bounds.")
        raw = {
            "schema": RESOURCE_VALIDATION_SCHEMA,
            "candidate_entry_id": entry_id,
            "valid": valid,
            "status": "VALID" if valid else "BLOCKED_RESOURCE_INITIALIZATION",
            "values": {
                "resource:core.qi": qi_current,
                "resource:core.martial_focus": martial_focus_current,
            },
            "provenance_kind": provenance_kind if provenance_kind in {"ENCOUNTER_AUTHORITY", "TEST_FIXTURE"} else None,
            "provenance_id": str(provenance_id) if provenance_id else None,
            "canonical_owner_choice": False,
            "noncanonical_test_fixture": provenance_kind == "TEST_FIXTURE",
            "unresolved_requirements": unresolved,
            "diagnostics": diagnostics,
            "package_current_values_used": False,
            "package_mutated": False,
        }
        raw["validation_commitment_sha256"] = canonical_sha256(raw)
        return ResourceInitializationValidation.model_validate(raw)

    def preview_draft(
        self,
        *,
        participants: list[dict[str, Any]],
        battlefield_id: str | None,
        battlefield_provenance_kind: str | None,
        battlefield_provenance_id: str | None,
    ) -> PreEncounterDraft:
        diagnostics: list[dict[str, Any]] = []
        slots: list[DraftParticipantSlot] = []
        candidate_valid = resources_valid = teams_valid = battlefield_valid = True
        source_ids: list[str] = []
        package_hashes: list[str] = []
        actor_commitments: list[str] = []
        readiness_state: str = "DRAFT_VALIDATED_PRE_PLACEMENT"

        if not participants:
            candidate_valid = resources_valid = teams_valid = False
            diagnostics.append({"code": "C3B_PARTICIPANT_REQUIRED", "message": "At least one installed candidate is required."})
            readiness_state = "DRAFT_INCOMPLETE"

        seen_entries: set[str] = set()
        for index, supplied in enumerate(participants):
            entry_id = str(supplied.get("candidate_entry_id") or "")
            if not entry_id or entry_id in seen_entries:
                candidate_valid = False
                diagnostics.append({"code": "C3B_INVALID_OR_DUPLICATE_CANDIDATE", "participant_index": index})
                continue
            seen_entries.add(entry_id)
            try:
                entry = self.candidate(entry_id)
            except FoundryError as exc:
                candidate_valid = False
                diagnostics.append({"code": exc.code, "message": exc.message, "participant_index": index})
                continue
            team_id = str(supplied.get("team_id") or "").strip()
            team_valid_for_slot = bool(team_id)
            if not team_valid_for_slot:
                teams_valid = False
                diagnostics.append({"code": "C3B_TEAM_ASSIGNMENT_REQUIRED", "candidate_entry_id": entry_id})
            validation = self.validate_resource_initialization(
                entry_id,
                qi_current=supplied.get("qi_current"),
                martial_focus_current=supplied.get("martial_focus_current"),
                provenance_kind=supplied.get("provenance_kind"),
                provenance_id=supplied.get("provenance_id"),
            )
            if not validation.valid:
                resources_valid = False
                diagnostics.extend(validation.diagnostics)
                diagnostics.append({
                    "code": "C3B_RESOURCE_INITIALIZATION_BLOCKED",
                    "candidate_entry_id": entry_id,
                    "unresolved_requirements": list(validation.unresolved_requirements),
                })
            if not team_valid_for_slot or not validation.valid:
                continue

            package = self._package_for_entry(entry)
            adapter = CharacterCombatRuntimeAdapter(package)
            initialization = RuntimeResourceInitialization(
                qi_current=int(supplied["qi_current"]),
                martial_focus_current=int(supplied["martial_focus_current"]),
                provenance_kind=supplied["provenance_kind"],
                provenance_id=str(supplied["provenance_id"]),
                canonical_owner_choice=False,
            )
            bundle = adapter.build_bundle(initialization)
            actor = bundle.actor_template.model_copy(update={"team_id": team_id})
            actor_commitment = canonical_sha256(actor.model_dump(mode="json"))
            slots.append(DraftParticipantSlot(
                slot_id=f"slot:{index + 1}:{entry.character_project_id}",
                candidate_entry_id=entry.entry_id,
                source_package_sha256=entry.source_package_sha256,
                actor_id=entry.actor_id,
                display_name=entry.display_name,
                team_id=team_id,
                resource_initialization=initialization.model_dump(mode="json"),
                actor_template_commitment_sha256=actor_commitment,
            ))
            source_ids.append(entry.entry_id)
            package_hashes.append(entry.source_package_sha256)
            actor_commitments.append(actor_commitment)

        battlefield_choice: dict[str, Any] | None = None
        if battlefield_id:
            if not self._battlefield_path.is_file():
                battlefield_valid = False
                diagnostics.append({"code": "C3B_BATTLEFIELD_AUTHORITY_MISSING", "message": "The accepted battlefield definition is missing."})
            else:
                battlefield = json.loads(self._battlefield_path.read_text(encoding="utf-8"))
                if battlefield.get("stable_id") != battlefield_id:
                    battlefield_valid = False
                    diagnostics.append({"code": "C3B_BATTLEFIELD_SELECTION_INVALID", "message": "Only an installed accepted battlefield may be referenced."})
                elif battlefield_provenance_kind not in {"ENCOUNTER_AUTHORITY", "TEST_FIXTURE"} or not str(battlefield_provenance_id or "").strip():
                    battlefield_valid = False
                    diagnostics.append({"code": "C3B_BATTLEFIELD_PROVENANCE_REQUIRED", "message": "Battlefield selection provenance is required."})
                else:
                    battlefield_choice = {
                        "battlefield_id": battlefield_id,
                        "battlefield_sha256": sha256_file(self._battlefield_path),
                        "provenance_kind": battlefield_provenance_kind,
                        "provenance_id": str(battlefield_provenance_id),
                        "canonical_owner_choice": False,
                        "token_positions_committed": False,
                    }
        else:
            battlefield_valid = False

        if not candidate_valid:
            readiness_state = "BLOCKED_INVALID_CANDIDATE"
        elif not resources_valid:
            readiness_state = "BLOCKED_RESOURCE_INITIALIZATION"
        elif not teams_valid:
            readiness_state = "BLOCKED_TEAM_ASSIGNMENT"
        elif not battlefield_valid:
            readiness_state = "BLOCKED_BATTLEFIELD_SELECTION" if participants else "DRAFT_INCOMPLETE"

        unresolved = [
            DraftUnresolvedRequirement(
                code="C3B_OPPOSING_TEAM_PARTICIPANTS_REQUIRED",
                message="A complete opposing team has not been supplied; no opponent was invented.",
                blocking_for_pre_placement_validation=False,
            ),
            DraftUnresolvedRequirement(
                code="C3B_TOKEN_PLACEMENT_REQUIRED",
                message="Authoritative token positions remain unset.",
                blocking_for_pre_placement_validation=False,
            ),
            DraftUnresolvedRequirement(
                code="C3B_LIVE_ENCOUNTER_COMMIT_DEFERRED",
                message="Encounter creation, initiative, controllers, and combat execution are outside C3B.",
                blocking_for_pre_placement_validation=False,
            ),
        ]
        if battlefield_choice and battlefield_choice.get("provenance_kind") == "TEST_FIXTURE":
            unresolved.append(DraftUnresolvedRequirement(
                code="C3B_OWNER_BATTLEFIELD_CHOICE_NOT_COMMITTED",
                message="The proof battlefield is a noncanonical test fixture, not an owner selection.",
                blocking_for_pre_placement_validation=False,
            ))
        if not battlefield_valid:
            unresolved.append(DraftUnresolvedRequirement(
                code="C3B_BATTLEFIELD_SELECTION_REQUIRED",
                message="A valid accepted battlefield selection is required before pre-placement validation.",
                blocking_for_pre_placement_validation=True,
            ))
        if not teams_valid:
            unresolved.append(DraftUnresolvedRequirement(
                code="C3B_TEAM_ASSIGNMENT_REQUIRED",
                message="Every supplied participant requires an explicit team assignment.",
                blocking_for_pre_placement_validation=True,
            ))
        if not resources_valid:
            unresolved.append(DraftUnresolvedRequirement(
                code="C3B_RESOURCE_INITIALIZATION_REQUIRED",
                message="Every supplied participant requires explicit current resource values for Qi and Martial Focus with provenance.",
                blocking_for_pre_placement_validation=True,
            ))
        if not candidate_valid:
            unresolved.append(DraftUnresolvedRequirement(
                code="C3B_VALID_CANDIDATE_REQUIRED",
                message="Every participant must reference an installed runtime-ready candidate.",
                blocking_for_pre_placement_validation=True,
            ))

        validation_report = PreEncounterDraftValidation(
            supplied_candidates_valid=candidate_valid,
            supplied_resources_valid=resources_valid,
            supplied_team_assignments_valid=teams_valid,
            supplied_battlefield_valid=battlefield_valid,
            diagnostics=tuple(diagnostics),
        )
        actor_template_commitment = canonical_sha256(sorted(actor_commitments))
        raw = {
            "schema": DRAFT_SCHEMA,
            "draft_version": "1.0.0",
            "source_candidate_ids": sorted(source_ids),
            "source_package_hashes": sorted(package_hashes),
            "participant_slots": [row.model_dump(mode="json") for row in sorted(slots, key=lambda row: row.slot_id)],
            "battlefield_choice": battlefield_choice,
            "unresolved_requirements": [row.model_dump(mode="json") for row in sorted(unresolved, key=lambda row: row.code)],
            "validation_report": validation_report.model_dump(mode="json", by_alias=True),
            "readiness_state": readiness_state,
            "actor_template_commitment_sha256": actor_template_commitment,
            "token_positions": [],
            "initiative_order": [],
            "controller_assignments": [],
            "journal_path": None,
            "match_directory": None,
            "persisted_event_count": 0,
            "project_events_written": 0,
            "is_match": False,
            "is_encounter_execution_record": False,
            "can_roll_dice": False,
            "can_start_turn": False,
            "can_invoke_controllers": False,
            "persistent": False,
        }
        commitment = canonical_sha256(raw)
        raw["draft_id"] = f"pre-encounter-draft:{commitment[:24]}"
        raw["draft_commitment_sha256"] = commitment
        return PreEncounterDraft.model_validate(raw)

    @staticmethod
    def discard_draft(draft_id: str) -> dict[str, Any]:
        if not str(draft_id or "").startswith("pre-encounter-draft:"):
            raise FoundryError("C3B_DRAFT_ID_INVALID", "The pre-encounter draft ID is invalid.")
        return {
            "schema": "TianxiaPreEncounterDraftDiscard.v1",
            "status": "DISCARDED_NONPERSISTENT_PREVIEW",
            "draft_id": draft_id,
            "state_deleted": False,
            "reason": "C3B previews are never persisted; discard is a verified no-op.",
            "project_events_written": 0,
            "persisted_combat_events": 0,
            "match_created": False,
        }
