from __future__ import annotations

import io
import gc
import itertools
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json, utcnow
from canonical_catalog import CanonicalCatalogAuthorityService
from catalog_choice_authority import (
    COMMITTED_CATALOG_CHOICE_FIELD,
    DELEGATED_FINAL_CATALOG_GRANT_FIELD,
    committed_catalog_grant_plan,
)
from character_creation.choice_snapshot import materialize_choice_snapshot, valid_choice_snapshot
from character_creation.delegated_choice_authority import (
    build_delegated_choice_envelope,
    catalog_stage2_selections,
    final_plan_sha256,
    frozen_owner_target_cl,
    validate_accepted_final_plan_target,
    validate_delegated_target_cl,
    response_authority_representations,
    validate_delegated_choice_plan,
)
from character_creation.response_materialization import (
    RESPONSE_SCHEMA as DELEGATED_RESPONSE_SCHEMA,
    CanonicalSelectionIntent,
    inject_canonical_intent,
    normalize_selection_intent,
)
from non_sphere_authority import NonSphereAuthorityService
from non_sphere_authority.service import (
    _TRUSTED_INITIAL_CATALOG_FINALIZATION,
    _server_initial_catalog_finalization_context,
)
from stage2.service import _TRUSTED_CHARACTER_CREATION_EXECUTION

MODES = {"MANUAL_CHAT", "STANDARD_API", "AUTO_FINALIZE_WHEN_CLEAN"}
ACTIVE_RUN_STATUSES = {"PREPARING_REQUEST", "WAITING_FOR_RESPONSE", "READY_FOR_REVIEW", "NEEDS_REVIEW"}
TERMINAL_RUN_STATUSES = {"CLEAN_AND_FINALIZED", "CANCELLED", "REVISED"}
PLAN_SCHEMA = "TianxiaFoundry.CharacterCreationPlan.v2"
LEGACY_PLAN_SCHEMA = "TianxiaFoundry.CharacterCreationPlan.v1"
RUN_SCHEMA = "TianxiaFoundry.CharacterCreationRun.v3"
QUALITY_SCHEMA = "TianxiaFoundry.CharacterCreationQualityGate.v3"
DRY_RUN_SCHEMA = "TianxiaFoundry.CharacterCreationDryRun.v3"
FORBIDDEN_PLANNER_FIELDS = {
    "compiled_surfaces", "readiness", "ledger_identity", "projection_identity",
    "character_sheet_identity", "gm_model_identity", "portable_character_identity",
    "combat_identity", "ability_scores", "resources", "actions", "reactions",
}
REQUIRED_SURFACES = ("ledger", "projection", "character_sheet", "factory_authoring", "gm_model", "gm_consumer", "portable_character")
PREFERRED_RESPONSE_KEYS = frozenset({
    "schema",
    "request_sha256",
    "selection_intent",
    "acquisition_intent",
    "bounded_choices",
    "owner_descriptive_fields",
})
PREFERRED_ACQUISITION_KEYS = frozenset({
    "sphere_free_talent_pairs",
    "ordinary_talent_ids",
    "insight_occurrences",
})
PREFERRED_BOUNDED_CHOICE_KEYS = frozenset({
    "ability_scores",
    "background_ability",
    "background_ability_amount",
    "ability_score_changes_by_milestone_id",
    "path_progression_by_cl",
})
_IDENTITY_TRANSIENT_PATHS = {
    ("advanced_details", "projection_status", "artifacts", "path"),
    ("artifacts", "path"),
    ("provenance", "advancement_projection", "projection", "artifacts", "path"),
    ("provenance", "character_sheet_projection", "artifact", "path"),
    ("provenance", "mechanical_projection", "projection", "artifacts", "path"),
    ("sheet_artifact", "path"),
    ("audit", "path"),
    ("clean_import", "first", "installed_audit", "path"),
    ("clean_import", "first", "package_path"),
    ("clean_import", "gm_model", "installed_package_path"),
    ("clean_import", "second", "installed_audit", "path"),
    ("clean_import", "second", "package_path"),
}
_IDENTITY_SURFACE_ROOT_FIELDS = {
    "gm_model": frozenset({
        "build",
        "workspace",
        "candidate_zip",
        "build_manifest_path",
        "deep_audit_path",
        "gm_model_path",
        "gm_view_model_path",
    }),
    "gm_consumer": frozenset({"selected_id"}),
}
_IDENTITY_RECEIPT_CONTEXT_NAMES = frozenset({
    "receipt",
    "terminal_receipt",
    "terminal_commit_receipt",
    "commit_receipt",
    "terminal_result_receipt",
})
_IDENTITY_RECEIPT_PROCESS_FIELDS = frozenset({
    # Approval/challenge process identity is verified by Stage 2 separately;
    # it is not part of the semantic character candidate projection.
    "approval_challenge_id",
    "challenge_id",
    "nonce",
    "approval_evidence_id",
    "evidence_id",
    # Terminal binding/projection and external integrity envelope values are
    # process evidence.  Mechanical hashes in the same receipt remain live.
    "binding_set_hash",
    "terminal_projection_hash",
    "terminal_projection_json",
    "terminal_attempt_id",
    "integrity_mac",
    "integrity_key_id",
    "integrity_domain",
    "integrity_version",
})
_IDENTITY_RECEIPT_PROCESS_TIMESTAMP_FIELDS = frozenset({
    "created_at",
    "updated_at",
    "completed_at",
    "issued_at",
    "started_at",
    "finished_at",
    "committed_at",
    "verified_at",
    "timestamp",
    "process_timestamp",
    "attempt_started_at",
    "attempt_completed_at",
})
_IDENTITY_RECEIPT_TRANSIENT_PATH_FIELDS = frozenset({
    "path",
    "artifact_path",
    "package_path",
    "workspace_path",
    "build_manifest_path",
    "candidate_zip",
    "deep_audit_path",
    "gm_model_path",
    "gm_view_model_path",
    "seal_path",
    "consumer_root",
    "harness_package_path",
    "terminal_projection_path",
})
RESPONSE_BINDING_ERROR = "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"
RESPONSE_BINDING_MESSAGE = (
    "The complete response is not bound to this exact active request. "
    "Prepare a new response from this run's complete request and try again."
)
CHARACTER_CREATION_PROVIDER_SYSTEM_MESSAGE = (
    "You are an untrusted Tianxia complete-character planning adapter. Return exactly one JSON object "
    "that follows the delegated selection-intent response contract in the user prompt. Copy the exact active "
    "request_sha256 into the response. Resolve every delegated slot only from the frozen delegated_choice_envelope; "
    "select only offered and allowed IDs, preserve owner locks, and never infer hidden final choices. "
    "Keep ordered priorities separate from explicit acquisitions and provide only the exact bounded choices "
    "advertised by the request. Do not choose target_cl. "
    "If delegated_fields marks the name or concept as delegated, you may propose display-only text in "
    "owner_descriptive_fields for owner review. Do not invent Stage 1 bindings, Stage 2 rows, event kinds, "
    "channels, effective CL values, automatic grants, hashes, compiled surfaces, readiness, artifact identities, "
    "actions, tools, or network instructions. The local Factory validates every choice, materializes the exact "
    "Stage 1/Stage 2 authority, performs two isolated compilations, and retains sole mechanical and commit authority."
)
_SERVER_FINALIZATION_AUTHORITY = object()
_SERVER_SCRATCH_COMPILATION_AUTHORITY = object()


class CharacterCreationExecutionService:
    """Three transport policies over one locally authoritative character pipeline."""

    def __init__(
        self,
        db: Database,
        *,
        stage1: Any,
        provider: Any,
        project_store: Any,
        stage2: Any | None = None,
        character_sheets: Any | None = None,
        gm_exports: Any | None = None,
        portable_characters: Any | None = None,
        factory_authoring: Any | None = None,
        projections: Any | None = None,
        gm_consumer: Any | None = None,
        combat_readiness: Any | None = None,
        pipeline_factory: Callable[[Database], dict[str, Any]] | None = None,
        production_release: Any | None = None,
        owner_principal: str = "local-owner",
    ):
        self.db = db
        self.stage1 = stage1
        self.provider = provider
        self.projects = project_store
        self.stage2 = stage2
        self.character_sheets = character_sheets
        self.gm_exports = gm_exports
        self.portable_characters = portable_characters
        self.factory_authoring = factory_authoring
        self.projections = projections
        self.gm_consumer = gm_consumer
        self.combat_readiness = combat_readiness
        self.pipeline_factory = pipeline_factory
        self.production_release = production_release
        self.owner_principal = owner_principal

    def _project(self, project_id: str) -> dict[str, Any]:
        result = self.projects.get_project(project_id)
        project = deepcopy(result.get("project") or result)
        if isinstance(result.get("project"), dict):
            # These server-owned columns are the authoritative project envelope.
            # working_name is copied only as display content; it never replaces project_id.
            for key in ("project_id", "revision", "working_name"):
                if key in result:
                    project[key] = deepcopy(result[key])
        return project

    def _revision(self, project_id: str) -> int:
        return int(self._project(project_id).get("revision") or 0)

    def _content_lock_hash(self, project_id: str) -> str:
        project = self._project(project_id)
        lock = project.get("content_lock") or {}
        return str(lock.get("lock_hash") or project.get("content_lock_hash") or "")

    def _choice_snapshot(self, project_id: str) -> dict[str, Any]:
        return materialize_choice_snapshot(self._project(project_id))

    def _materialize_method_exact_choice(self, run: dict[str, Any], authority_db: Database, *, phase: str) -> dict[str, Any] | None:
        """Materialize a server-derived exact Method route during local compilation."""
        if authority_db is self.db:
            project = self.projects.get_project(run["project_id"])
        else:
            from project_store.service import ProjectStore
            project = ProjectStore(authority_db).get_project(run["project_id"])
        envelope = deepcopy(project.get("project") or project)
        locks = {
            row.get("field"): row.get("value")
            for row in envelope.get("user_locks", []) if isinstance(row, dict)
        }
        mode = locks.get("character_sheet.method_planning_mode")
        if mode not in {"EXACT", "HARD_LOCK"}:
            return None
        access_plan = deepcopy(locks.get("character_sheet.method_access_plan") or {})
        authority = NonSphereAuthorityService(authority_db)
        if not access_plan and mode == "HARD_LOCK":
            # Accepted pre-WIN1-P1R2 project compatibility: those projects put
            # the Method directly in the locked state and never authored a route.
            return None
        method_id = access_plan.get("method_id")
        required = (
            "schema", "method_id", "access_tier", "route_type", "route_label",
            "source_reference", "source_route_sha256", "route_commitment_sha256",
            "method_registry_commitment_sha256", "status",
        )
        missing = [field for field in required if access_plan.get(field) in (None, "", {})]
        if access_plan.get("schema") != "TianxiaFoundry.MethodAccessPlan.v2" or missing:
            raise FoundryError(
                "CG1_METHOD_ACCESS_PLAN_INCOMPLETE",
                "The selected Method has no complete legal learning route; return to Describe and choose another Method or learning route.",
                details={"method_id": method_id, "missing_fields": missing},
            )
        method = authority.methods.get(method_id)
        evidence_targets = {
            key: deepcopy(access_plan[key])
            for key in (
                "method_id", "access_tier", "route_type", "route_label",
                "owner_annotation", "source_reference", "source_route_sha256", "route_commitment_sha256",
                "method_registry_commitment_sha256",
            )
        }
        if method is None:
            raise FoundryError("CG1_METHOD_ACCESS_PLAN_STALE", "The selected Method is no longer installed.", details={"method_id": method_id})
        authority._validate_authority_targets("method_access", evidence_targets)
        receipt = {
            "schema": "TianxiaFoundry.MethodAccessCompilationReceipt.v2",
            "method_id": method_id,
            "access_plan": access_plan,
            "evidence_required": True,
            "evidence_authority_type": "method_access",
            "primary_method_id": method_id,
            "canonical_mutation_boundary": "VALIDATED_LOCAL_COMPILATION",
        }
        evidence = authority.commit_authority_event(
            run["project_id"], "method_access", evidence_targets,
            creation_authority="PROJECT_AUTHORITY_SERVICE",
            idempotency_key=f"cg1.method-access:{run['run_id']}:{method_id}",
        )
        receipt["evidence_id"] = evidence["evidence_id"]
        state = authority.get_state(run["project_id"])
        if state.get("primary_method_id") == method_id:
            return receipt
        updated = authority.set_primary_method(
            run["project_id"], method_id,
            access_source_records=([evidence["evidence_id"]] if evidence else None),
        )
        if updated.get("primary_method_id") != method_id:
            raise FoundryError("CG1_METHOD_ACCESS_COMMIT_FAILED", "The validated Method access route did not materialize its Primary Method.", details={"method_id": method_id})
        return receipt

    # Compatibility for focused callers created during WIN1-P1R2.
    def _materialize_method_hard_lock(self, run: dict[str, Any], authority_db: Database, *, phase: str) -> dict[str, Any] | None:
        return self._materialize_method_exact_choice(run, authority_db, phase=phase)

    def _require_frozen_choice_snapshot(self, run: dict[str, Any]) -> dict[str, Any]:
        expected = run.get("request", {}).get("typed_choice_snapshot") or {}
        actual = self._choice_snapshot(run["project_id"])
        if not valid_choice_snapshot(expected) or actual != expected:
            raise FoundryError(
                "CG1_TYPED_CHOICE_SNAPSHOT_STALE",
                "Committed project choices changed after the build request was frozen.",
                details={
                    "expected_snapshot_sha256": expected.get("snapshot_sha256"),
                    "actual_snapshot_sha256": actual.get("snapshot_sha256"),
                    "project_id": run["project_id"],
                    "project_revision": actual.get("project_revision"),
                },
                status_code=409,
            )
        return expected

    @property
    def owner_principal_hash(self) -> str:
        return sha256_bytes(self.owner_principal.encode("utf-8"))

    def preference(self, project_id: str) -> dict[str, Any]:
        self._project(project_id)
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT execution_mode,updated_at FROM character_creation_preferences "
                "WHERE project_id=? AND owner_principal_hash=?",
                (project_id, self.owner_principal_hash),
            ).fetchone()
        return {
            "schema": "TianxiaFoundry.CharacterCreationExecutionPreference.v1",
            "project_id": project_id,
            "owner_principal_hash": self.owner_principal_hash,
            "execution_mode": row["execution_mode"] if row else "MANUAL_CHAT",
            "explicit": bool(row),
            "updated_at": row["updated_at"] if row else None,
        }

    def set_preference(self, project_id: str, execution_mode: str) -> dict[str, Any]:
        mode = str(execution_mode or "").strip().upper()
        if mode not in MODES:
            raise FoundryError("CG1_EXECUTION_MODE_INVALID", "Choose Manual Chat, Standard API, or Auto-Finalize When Clean.")
        self._project(project_id)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO character_creation_preferences(project_id,owner_principal_hash,execution_mode,updated_at) "
                "VALUES(?,?,?,?) ON CONFLICT(project_id,owner_principal_hash) DO UPDATE SET "
                "execution_mode=excluded.execution_mode,updated_at=excluded.updated_at",
                (project_id, self.owner_principal_hash, mode, utcnow()),
            )
        return self.preference(project_id)

    @staticmethod
    def _loads(row: Any, key: str, default: Any) -> Any:
        value = row[key]
        return json.loads(value) if value else deepcopy(default)

    def _attempt_history(self, run_id: str) -> list[dict[str, Any]]:
        """Read the append-only response/build-attempt ledger for one run."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM character_creation_attempt_history WHERE run_id=? ORDER BY ordinal",
                (run_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key, default in (
                ("canonical_intent_json", {}),
                ("materialization_receipt_json", {}),
                ("validation_json", {}),
                ("quality_json", {}),
                ("binding_json", {}),
                ("links_json", {}),
                ("blockers_json", []),
                ("error_json", {}),
            ):
                raw = item.get(key)
                try:
                    item[key.removesuffix("_json")] = json.loads(raw) if raw else deepcopy(default)
                except (TypeError, json.JSONDecodeError):
                    item[key.removesuffix("_json")] = deepcopy(default)
                item.pop(key, None)
            # Keep the exact bounded response available to the owner while
            # also exposing its digest in the compact projection.
            response_bytes = item.pop("response_bytes", None)
            if response_bytes is not None:
                if isinstance(response_bytes, memoryview):
                    response_bytes = response_bytes.tobytes()
                item["response_byte_count"] = len(response_bytes) if isinstance(response_bytes, (bytes, bytearray)) else None
                item["response_bytes_sha256"] = sha256_bytes(bytes(response_bytes)) if isinstance(response_bytes, (bytes, bytearray)) else None
            result.append(item)
        return result

    def _append_attempt(
        self,
        run: dict[str, Any] | str,
        *,
        action_type: str,
        status: str,
        response_text: str | None = None,
        canonical_intent: dict[str, Any] | None = None,
        materialization_receipt: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        quality: dict[str, Any] | None = None,
        candidate_identity: str | None = None,
        materialized_plan_sha256: str | None = None,
        submitted_plan_sha256: str | None = None,
        prior_attempt_id: str | None = None,
        binding: dict[str, Any] | None = None,
        blockers: list[dict[str, Any]] | None = None,
        error: dict[str, Any] | None = None,
        links: dict[str, Any] | None = None,
        completed: bool = True,
    ) -> str:
        """Append one immutable attempt row; never update a prior attempt."""
        current = self.get(run) if isinstance(run, str) else run
        with self.db.transaction() as conn:
            ordinal = int(
                conn.execute(
                    "SELECT COALESCE(MAX(ordinal),0)+1 FROM character_creation_attempt_history WHERE run_id=?",
                    (current["run_id"],),
                ).fetchone()[0]
            )
            digest_material = {
                "run_id": current["run_id"],
                "ordinal": ordinal,
                "action_type": action_type,
                "status": status,
                "response_sha256": sha256_bytes(response_text.encode("utf-8")) if isinstance(response_text, str) else None,
                "prior_attempt_id": prior_attempt_id,
            }
            attempt_id = "cg1.attempt." + sha256_json(digest_material)[:40]
            request = current.get("request") or {}
            response = current.get("response") or {}
            exact_response = response_text if response_text is not None else response.get("exact_response_text")
            response_sha = (
                sha256_bytes(exact_response.encode("utf-8"))
                if isinstance(exact_response, str)
                else response.get("response_sha256")
            )
            now = utcnow()
            conn.execute(
                """INSERT INTO character_creation_attempt_history(
                   attempt_id,run_id,project_id,ordinal,action_type,status,
                   request_sha256,response_sha256,response_bytes,response_text,canonical_intent_json,
                   materialization_receipt_json,validation_json,quality_json,candidate_identity,
                   materialized_plan_sha256,submitted_plan_sha256,prior_attempt_id,binding_json,links_json,
                   blockers_json,error_json,created_at,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id,
                    current["run_id"],
                    current["project_id"],
                    ordinal,
                    action_type,
                    status,
                    request.get("request_sha256"),
                    response_sha,
                    exact_response.encode("utf-8") if isinstance(exact_response, str) else None,
                    exact_response,
                    canonical_json(canonical_intent or {}),
                    canonical_json(materialization_receipt or {}),
                    canonical_json(validation or {}),
                    canonical_json(quality or {}),
                    candidate_identity or (current.get("dry_run") or {}).get("candidate_identity"),
                    materialized_plan_sha256,
                    submitted_plan_sha256,
                    prior_attempt_id,
                    canonical_json(binding or {}),
                    canonical_json(links or {}),
                    canonical_json(blockers or []),
                    canonical_json(error or {}),
                    now,
                    now if completed else None,
                ),
            )
        return attempt_id

    def _latest_attempt_id(self, run_id: str) -> str | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT attempt_id FROM character_creation_attempt_history WHERE run_id=? ORDER BY ordinal DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return row["attempt_id"] if row else None

    @staticmethod
    def _descriptive_fields(value: Any) -> dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
        name = str(identity.get("name") or raw.get("name") or "").strip() or None
        concept = str(raw.get("concept") or raw.get("character_concept") or "").strip() or None
        return {"identity": {"name": name}, "concept": concept}

    @classmethod
    def _descriptive_from_response_text(cls, response_text: str) -> dict[str, Any]:
        try:
            value = json.loads(response_text)
        except (TypeError, json.JSONDecodeError):
            return cls._descriptive_fields({})
        if isinstance(value, dict) and isinstance(value.get("owner_descriptive_fields"), dict):
            value = value["owner_descriptive_fields"]
        return cls._descriptive_fields(value)

    @classmethod
    def _descriptive_projection(cls, row: Any) -> dict[str, Any]:
        proposed = cls._descriptive_fields(cls._loads(row, "owner_descriptive_fields_json", {}))
        final_plan = cls._loads(row, "final_plan_json", {})
        if not ((proposed.get("identity") or {}).get("name") or proposed.get("concept")):
            proposed = cls._descriptive_fields((final_plan or {}).get("descriptive_fields"))
        accepted = cls._descriptive_fields(cls._loads(row, "accepted_descriptive_fields_json", {}))
        accepted_name = (accepted.get("identity") or {}).get("name")
        accepted_concept = accepted.get("concept")
        proposed_name = (proposed.get("identity") or {}).get("name")
        proposed_concept = proposed.get("concept")
        resolved = {
            "identity": {"name": accepted_name or proposed_name},
            "concept": accepted_concept or proposed_concept,
        }
        if accepted_name or accepted_concept:
            state = "OWNER_ACCEPTED"
        elif proposed_name or proposed_concept:
            state = "AI_PROPOSED"
        else:
            state = "UNRESOLVED"
        return {
            "schema": "TianxiaFoundry.OwnerDescriptiveFieldsProjection.v1",
            "proposed": proposed,
            "accepted": accepted,
            "resolved": resolved,
            "state": state,
            "label": "Owner accepted" if state == "OWNER_ACCEPTED" else "AI proposed" if state == "AI_PROPOSED" else "Owner decision needed",
        }

    def _public(self, row: Any) -> dict[str, Any]:
        validation = self._loads(row, "validation_json", {})
        response = self._loads(row, "response_json", {})
        final_plan = self._loads(row, "final_plan_json", {})
        result = {
            "schema": RUN_SCHEMA, "run_id": row["run_id"], "project_id": row["project_id"],
            "starting_revision": row["starting_revision"], "execution_mode": row["execution_mode"],
            "idempotency_key": row["idempotency_key"], "request": self._loads(row, "request_json", {}),
            "transport": self._loads(row, "transport_json", {}), "response": response,
            "validation": validation, "dry_run": self._loads(row, "dry_run_json", {}),
            "final_plan": final_plan,
            "quality": self._loads(row, "quality_json", {}), "owner_decision": row["owner_decision"],
            "commit": self._loads(row, "commit_json", {}), "final_revision": row["final_revision"],
            "outputs": self._loads(row, "output_json", {}), "blockers": self._loads(row, "blockers_json", []),
            "warnings": self._loads(row, "warnings_json", []), "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "completed_at": row["completed_at"],
            "owner_descriptive_fields": self._descriptive_projection(row),
            "submission_error": deepcopy(validation.get("last_submission_error")) if isinstance(validation, dict) else None,
            "secret_persisted": False,
            "attempt_history": self._attempt_history(row["run_id"]),
            "canonical_intent_hash": validation.get("canonical_intent_hash") or final_plan.get("canonical_intent_hash"),
            "materialized_plan_sha256": validation.get("materialized_stage2_hash") or final_plan.get("materialized_stage2_sha256"),
            "submitted_plan_sha256": final_plan.get("submitted_plan_sha256"),
        }
        result["action_availability"] = self._action_availability(result)
        return result

    def get(self, run_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM character_creation_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise FoundryError("CG1_RUN_NOT_FOUND", "No character build run has that ID.", status_code=404)
        return self._public(row)

    def list(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM character_creation_runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
        return [self._public(row) for row in rows]

    @staticmethod
    def _stage_for_status(status: str) -> int:
        return {
            "PREPARING_REQUEST": 2,
            "WAITING_FOR_RESPONSE": 2,
            "NEEDS_REVIEW": 3,
            "READY_FOR_REVIEW": 3,
            "CLEAN_AND_FINALIZED": 4,
            "CANCELLED": 2,
            "REVISED": 2,
        }.get(status, 2)

    @staticmethod
    def _owner_stage_for_status(status: str) -> int:
        """Map persisted lifecycle states to the eight-screen owner flow.

        ``stage`` remains the legacy four-stage recovery/evidence contract.  The
        owner workspace uses this separate field so a waiting response is not
        presented as the Path/Method screen and a finalized run opens its saved
        sheet rather than the legacy Finalize panel.
        """
        return {
            "PREPARING_REQUEST": 3,
            "WAITING_FOR_RESPONSE": 3,
            "READY_FOR_REVIEW": 4,
            "NEEDS_REVIEW": 4,
            "CLEAN_AND_FINALIZED": 7,
            "CANCELLED": 8,
            "REVISED": 3,
        }.get(status, 1)

    @classmethod
    def _next_action_for_status(cls, run: dict[str, Any]) -> str:
        status = run.get("status")
        if status == "WAITING_FOR_RESPONSE":
            return "Load one response file or paste the complete response."
        if status == "PREPARING_REQUEST":
            return "Resume the build and inspect the request status."
        if status == "NEEDS_REVIEW":
            return "Inspect the blocker, then choose Replace Response, Retry Local Build, Edit Brief / Create New Request, or Cancel Build."
        if status == "READY_FOR_REVIEW":
            return "Review the proposal and choose Finalize, Edit Brief / Create New Request, or Cancel Build."
        if status == "CLEAN_AND_FINALIZED":
            return "Open the completed Character Sheet."
        if status == "CANCELLED":
            return "Start a deliberate new build when you are ready."
        if status == "REVISED":
            return "Resume the replacement build."
        return "Inspect the current build state."

    @classmethod
    def _recovery_summary(cls, run: dict[str, Any]) -> dict[str, Any]:
        request = run.get("request") or {}
        response = run.get("response") or {}
        return {
            "run_id": run.get("run_id"),
            "project_id": run.get("project_id"),
            "starting_revision": run.get("starting_revision"),
            "execution_mode": run.get("execution_mode"),
            "status": run.get("status"),
            "stage": cls._stage_for_status(str(run.get("status") or "")),
            "owner_stage": cls._owner_stage_for_status(str(run.get("status") or "")),
            "next_legal_action": cls._next_action_for_status(run),
            "request_sha256": request.get("request_sha256"),
            "content_lock_hash": request.get("content_lock_hash"),
            "response_sha256": response.get("response_sha256"),
            "response_binding": {
                "request_sha256": request.get("request_sha256"),
                "response_sha256": response.get("response_sha256"),
                "binding_status": "BOUND" if response.get("response_sha256") and not run.get("submission_error") else "WAITING_FOR_RESPONSE" if not response.get("response_sha256") else "REVIEW_REQUIRED",
            },
            "blockers": deepcopy(run.get("blockers") or []),
            "warnings": deepcopy(run.get("warnings") or []),
            "submission_error": deepcopy(run.get("submission_error")),
            "owner_descriptive_fields": deepcopy(run.get("owner_descriptive_fields") or {}),
            "attempt_history": deepcopy(run.get("attempt_history") or []),
            "action_availability": cls._action_availability(run),
            "updated_at": run.get("updated_at"),
        }

    @staticmethod
    def _action_availability(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
        status = str(run.get("status") or "")
        terminal = status in TERMINAL_RUN_STATUSES
        response = run.get("response") or {}
        response_present = bool(response.get("response_sha256"))
        return {
            "replace_response": {
                "available": not terminal and run.get("execution_mode") == "MANUAL_CHAT",
                "reason": "Import one corrected response for this same frozen request." if not terminal and run.get("execution_mode") == "MANUAL_CHAT" else "Replace Response is unavailable after finalization/cancellation or for a provider-only run.",
            },
            "retry_local_build": {
                "available": not terminal and response_present and status in {"READY_FOR_REVIEW", "NEEDS_REVIEW"},
                "reason": "Retry the persisted response without contacting an external provider." if not terminal and response_present and status in {"READY_FOR_REVIEW", "NEEDS_REVIEW"} else "Retry requires a persisted response and a non-terminal review/build state.",
            },
            "edit_brief_create_new_request": {
                "available": not terminal,
                "reason": "Create a linked request with a deliberate brief or lock change; prior history remains inspectable." if not terminal else "A terminal run cannot be edited; start a deliberate new request.",
            },
            "cancel_build": {
                "available": not terminal,
                "reason": "Cancel this build explicitly and retain its attempt history." if not terminal else "This build is already terminal.",
            },
        }

    def recovery(self, project_id: str) -> dict[str, Any]:
        project = self._project(project_id)
        runs = self.list(project_id)
        active = next((run for run in runs if run.get("status") in ACTIVE_RUN_STATUSES), None)
        latest = runs[0] if runs else None
        summary = self._recovery_summary(active or latest) if (active or latest) else None
        return {
            "schema": "TianxiaFoundry.CharacterCreationRecovery.v1",
            "project_id": project_id,
            "project_revision": self._revision(project_id),
            "content_lock_hash": self._content_lock_hash(project_id),
            "project_name": project.get("name"),
            "active": active is not None,
            "active_run": self._recovery_summary(active) if active else None,
            "latest_run": self._recovery_summary(latest) if latest else None,
            "attempt_history": deepcopy((active or latest or {}).get("attempt_history") or []),
            "next_legal_action": summary.get("next_legal_action") if summary else "Start a complete-character build when the owner is ready.",
            "action_availability": self._action_availability(active or latest or {}),
        }

    def recoverable(self) -> list[dict[str, Any]]:
        result = []
        for row in self.projects.list_projects():
            project_id = row.get("project_id")
            if not project_id:
                continue
            recovery = self.recovery(str(project_id))
            if recovery.get("active") or recovery.get("latest_run"):
                result.append(recovery)
        return result

    def evidence(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        request = run.get("request") or {}
        response = run.get("response") or {}
        validation = run.get("validation") or {}
        return {
            "schema": "TianxiaFoundry.CharacterCreationBuildEvidence.v1",
            "run_id": run.get("run_id"),
            "project_id": run.get("project_id"),
            "stage": self._stage_for_status(str(run.get("status") or "")),
            "status": run.get("status"),
            "execution_mode": run.get("execution_mode"),
            "starting_revision": run.get("starting_revision"),
            "request_binding": {
                "request_sha256": request.get("request_sha256"),
                "content_lock_hash": request.get("content_lock_hash"),
                "project_id": request.get("project_id"),
                "project_revision": request.get("project_revision"),
                "typed_choice_snapshot_sha256": (request.get("typed_choice_snapshot") or {}).get("snapshot_sha256"),
                "idempotency_binding_sha256": request.get("idempotency_binding_sha256"),
            },
            "response_binding": {
                "response_sha256": response.get("response_sha256"),
                "submitted_request_sha256": (run.get("transport") or {}).get("submitted_request_sha256"),
                "binding_status": "BOUND" if response.get("response_sha256") and not run.get("submission_error") else "NOT_BOUND_OR_REQUIRES_REVIEW",
            },
            "response_view": {
                "exact_response_present": bool(response.get("exact_response_text")),
                "response_sha256": response.get("response_sha256"),
                "parsed_plan": deepcopy(response.get("parsed_plan")) if isinstance(response.get("parsed_plan"), dict) else None,
                "owner_descriptive_fields": deepcopy(run.get("owner_descriptive_fields")),
            },
            "canonical_intent": {
                "schema": "TianxiaFoundry.DelegatedSelectionIntent.v1" if run.get("canonical_intent_hash") else None,
                "intent_sha256": run.get("canonical_intent_hash"),
                "materialized_plan_sha256": run.get("materialized_plan_sha256"),
                "submitted_plan_sha256": run.get("submitted_plan_sha256"),
                "receipt": deepcopy((run.get("validation") or {}).get("materialization_receipt") or {}),
            },
            "owner_descriptive_fields": deepcopy(run.get("owner_descriptive_fields")),
            "blockers": deepcopy(run.get("blockers") or []),
            "warnings": deepcopy(run.get("warnings") or []),
            "submission_error": deepcopy(run.get("submission_error")),
            "validation": {
                key: deepcopy(value)
                for key, value in validation.items()
                if key != "last_submission_error"
            },
            "last_submission_error": deepcopy(validation.get("last_submission_error")),
            "quality": deepcopy(run.get("quality") or {}),
            "dry_run": {
                key: deepcopy((run.get("dry_run") or {}).get(key))
                for key in ("schema", "candidate_identity", "identities", "deterministic", "independent_compilations", "preview")
                if key in (run.get("dry_run") or {})
            },
            "next_legal_action": self._next_action_for_status(run),
            "action_availability": deepcopy((self.recovery(run["project_id"]).get("active_run") or self.recovery(run["project_id"]).get("latest_run") or {}).get("action_availability") or {}),
            "attempt_history": deepcopy(run.get("attempt_history") or []),
        }

    def _complete_request(
        self,
        project_id: str,
        revision_request: dict[str, Any] | None = None,
        *,
        execution_mode: str = "MANUAL_CHAT",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        prompt = self.stage1.generate_prompt(project_id)
        project = self._project(project_id)
        request = {
            "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
            "project_id": project_id,
            "project_revision": self._revision(project_id),
            "content_lock_hash": self._content_lock_hash(project_id),
            "typed_choice_snapshot": self._choice_snapshot(project_id),
            "stage1_prompt": deepcopy(prompt),
            "required_plan_schema": DELEGATED_RESPONSE_SCHEMA,
            "required_components": sorted(PREFERRED_RESPONSE_KEYS),
            "forbidden_planner_fields": sorted(FORBIDDEN_PLANNER_FIELDS),
            "server_owned_authority": {
                "target_cl": "frozen from project.user_locks[field=target_cl]",
                "stage1_response": True,
                "stage2_proposal": True,
                "event_kinds_channels_effective_cl": True,
                "automatic_components": True,
                "hashes_and_receipts": True,
            },
            "bounded_choice_contract": {
                "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
                "purpose": "Only genuinely non-derivable typed choices may appear here.",
                "fields": {
                    "ability_scores": {
                        "type": "point_buy_scores",
                        "abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"],
                        "allowed_values": [8, 9, 10, 11, 12, 13, 14, 15],
                        "budget": 27,
                    },
                    "background_ability": "only when the frozen Background authority publishes an allowed ability choice",
                    "background_ability_amount": "server-derived amount unless the frozen Background authority exposes a bounded amount",
                    "ability_score_changes_by_milestone_id": "typed ASI deltas keyed by advertised source milestone ID",
                    "path_progression_by_cl": "exact Path ID only when multiple selected Paths can advance at a CL",
                },
            },
            "policy": {
                "planner_prose_is_mechanical_authority": False,
                "priorities_are_non_acquisitive": True,
                "automatic_retries": False,
            },
        }
        delegated = build_delegated_choice_envelope(
            project,
            prompt,
            execution_mode=execution_mode,
            idempotency_key=idempotency_key,
        )
        if delegated is not None:
            request["delegated_choice_envelope"] = delegated
            request["bounded_choice_contract"]["advertised_advancement_choice_milestones"] = deepcopy(
                delegated.get("advancement_choice_milestones") or []
            )
            fields = request["bounded_choice_contract"]["fields"]
            prompt_locks = (request.get("stage1_prompt") or {}).get("envelope", {}).get("user_locks") or []
            point_buy_lock = next(
                (
                    row.get("value")
                    for row in prompt_locks
                    if isinstance(row, dict) and row.get("field") == "character_sheet.ability_point_buy"
                ),
                {},
            )
            fixed_scores = point_buy_lock.get("fixed_scores") if isinstance(point_buy_lock, dict) else None
            if isinstance(fixed_scores, dict) and set(fixed_scores) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"} and not point_buy_lock.get("auto_abilities"):
                fields.pop("ability_scores", None)
            background_contract = delegated.get("typed_choice_authority_by_slot", {}).get("background_choice", {})
            if not (background_contract.get("ability_adjustment_by_choice") or {}):
                fields.pop("background_ability", None)
                fields.pop("background_ability_amount", None)
            else:
                background_amount_choices = {
                    amount
                    for adjustment in (background_contract.get("ability_adjustment_by_choice") or {}).values()
                    if isinstance(adjustment, dict)
                    for amount in (
                        adjustment.get("allowed_amounts")
                        or adjustment.get("amount_choices")
                        or []
                    )
                    if type(amount) is int
                }
                if not background_amount_choices:
                    fields.pop("background_ability_amount", None)
            if not delegated.get("advancement_choice_milestones"):
                fields.pop("ability_score_changes_by_milestone_id", None)
            if not any(
                isinstance(row, dict) and len(row.get("path_ids") or []) > 1
                for row in delegated.get("path_progression_choices") or []
            ):
                fields.pop("path_progression_by_cl", None)
        if revision_request:
            request["revision_request"] = deepcopy(revision_request)
        request["request_sha256"] = self.request_payload_sha256(request)
        return request

    @staticmethod
    def canonical_request_payload(request: dict[str, Any]) -> dict[str, Any]:
        """Return the non-circular payload covered by request_sha256.

        Transport/run commitments are deliberately external to this payload.  In
        particular, start() adds the idempotency binding only after the canonical
        request identity exists; validators must therefore exclude it too.
        """
        payload = deepcopy(request)
        payload.pop("request_sha256", None)
        payload.pop("idempotency_binding_sha256", None)
        return payload

    @classmethod
    def request_payload_bytes(cls, request: dict[str, Any]) -> bytes:
        return canonical_json(cls.canonical_request_payload(request)).encode("utf-8")

    @classmethod
    def request_payload_sha256(cls, request: dict[str, Any]) -> str:
        return sha256_bytes(cls.request_payload_bytes(request))

    @staticmethod
    def _deterministic_zip(entries: dict[str, bytes]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, entries[name])
        return output.getvalue()

    def _complete_request_package(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        request = deepcopy(run["request"])
        envelope = request.get("delegated_choice_envelope") or {}
        allowed_by_slot = envelope.get("allowed_choice_ids_by_slot") or {}
        choices_by_slot = envelope.get("choices_by_slot") or {}
        typed_choice_authority = envelope.get("typed_choice_authority_by_slot") or {}
        locked_records = self._locked_records_for_project(run["project_id"]) if envelope else {}
        selection_properties: dict[str, Any] = {}
        for slot_id in sorted(allowed_by_slot):
            limits = (envelope.get("selection_limits_by_slot") or {}).get(slot_id) or {}
            slot_schema: dict[str, Any] = {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": list(allowed_by_slot.get(slot_id) or []),
                },
                "uniqueItems": True,
            }
            if isinstance(limits.get("final_min"), int):
                slot_schema["minItems"] = limits["final_min"]
            if isinstance(limits.get("final_max"), int):
                slot_schema["maxItems"] = limits["final_max"]
            selection_properties[slot_id] = slot_schema

        sphere_ids = [value for value in allowed_by_slot.get("sphere_priorities") or [] if isinstance(value, str)]
        talent_ids = [value for value in allowed_by_slot.get("advancement_skeleton") or [] if isinstance(value, str)]
        insight_ids = [value for value in allowed_by_slot.get("insight_priorities") or [] if isinstance(value, str)]
        milestone_rows = [
            row for row in envelope.get("advancement_choice_milestones") or []
            if isinstance(row, dict) and isinstance(row.get("milestone_id"), str)
        ]
        milestone_ids = [row["milestone_id"] for row in milestone_rows]

        def authority_for_choice(slot_id: str, choice_id: str) -> dict[str, Any]:
            choice = (choices_by_slot.get(slot_id) or {}).get(choice_id) or {}
            authority = (typed_choice_authority.get(slot_id) or {}).get("stage2_authority_by_choice", {}).get(choice_id)
            if not isinstance(authority, dict):
                authority = choice.get("stage2_authority")
            if not isinstance(authority, dict):
                authority = (choice.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
            return authority if isinstance(authority, dict) else {}

        generation_route = next(
            (
                row.get("value")
                for row in (request.get("stage1_prompt") or {}).get("envelope", {}).get("user_locks") or []
                if isinstance(row, dict) and row.get("field") == "character_sheet.generation_route"
            ),
            "player",
        )
        free_talent_kind = (
            "ai_bootstrap_talent_acquisition"
            if generation_route == "ai_bootstrap"
            else "sect_trial_talent_acquisition"
        )

        def insight_parameter_schema(authority: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            ability_change = authority.get("ability_change") or authority.get("insight_ability_change") or {}
            properties: dict[str, Any] = {}
            required = False
            if isinstance(ability_change, dict) and ability_change.get("allowed_abilities"):
                properties["ability"] = {
                    "type": "string",
                    "enum": sorted({value for value in ability_change["allowed_abilities"] if isinstance(value, str)}),
                }
                required = True
            return {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                **({"required": ["ability"]} if required else {}),
            }, required

        insight_occurrence_alternatives: list[dict[str, Any]] = []
        for insight_id in insight_ids:
            authority = authority_for_choice("insight_priorities", insight_id)
            allowed_cls = authority.get("allowed_cls") or authority.get("allowed_effective_cls") or []
            parameter_schema, parameters_required = insight_parameter_schema(authority)
            for milestone in milestone_rows:
                milestone_cl = milestone.get("cl", milestone.get("effective_cl"))
                if isinstance(allowed_cls, list) and milestone_cl not in allowed_cls:
                    continue
                insight_occurrence_alternatives.append({
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "insight_id",
                        "milestone_id",
                        *(["parameters"] if parameters_required else []),
                    ],
                    "properties": {
                        "insight_id": {"const": insight_id},
                        "milestone_id": {"const": milestone["milestone_id"]},
                        "parameters": parameter_schema,
                    },
                })

        pair_alternatives: list[dict[str, Any]] = []
        free_talents_by_sphere: dict[str, list[str]] = {}
        for talent_id in talent_ids:
            authority = authority_for_choice("advancement_skeleton", talent_id)
            sphere_id = (
                authority.get("owning_canonical_sphere_id")
                or authority.get("owning_sphere_id")
                or authority.get("sphere_id")
            )
            minimum_cl = authority.get("minimum_cl") or 1
            if (
                isinstance(sphere_id, str)
                and sphere_id in sphere_ids
                and free_talent_kind in (authority.get("allowed_kinds") or [])
                and type(minimum_cl) is int
                and minimum_cl <= 1
                and authority.get("free_sphere_talent_eligible") is not False
            ):
                free_talents_by_sphere.setdefault(sphere_id, []).append(talent_id)
        for sphere_id in sorted(free_talents_by_sphere):
            pair_alternatives.append({
                "type": "object",
                "additionalProperties": False,
                "required": ["sphere_id", "talent_id"],
                "properties": {
                    "sphere_id": {"const": sphere_id},
                    "talent_id": {"type": "string", "enum": sorted(set(free_talents_by_sphere[sphere_id]))},
                },
            })
        pair_schema: dict[str, Any] = {
            "oneOf": pair_alternatives,
        }
        ordinary_schema: dict[str, Any] = {
            "type": "array",
            "items": {"type": "string", "enum": talent_ids},
            "uniqueItems": True,
        }
        target_cl = (envelope.get("frozen_owner_target_cl") or {}).get("value")
        expected_ordinary_count = envelope.get("ordinary_talent_count")
        if isinstance(expected_ordinary_count, int):
            ordinary_schema["minItems"] = expected_ordinary_count
            ordinary_schema["maxItems"] = expected_ordinary_count

        acquisition_properties: dict[str, Any] = {
            "sphere_free_talent_pairs": {
                "type": "array",
                "items": pair_schema,
                "uniqueItems": True,
            },
            "ordinary_talent_ids": ordinary_schema,
            "insight_occurrences": {
                "type": "array",
                "uniqueItems": True,
                "items": (
                    {"oneOf": insight_occurrence_alternatives}
                    if insight_occurrence_alternatives
                    else {"type": "object", "enum": []}
                ),
            },
        }

        bounded_properties: dict[str, Any] = {}
        prompt_locks = (request.get("stage1_prompt") or {}).get("envelope", {}).get("user_locks") or []
        point_buy_lock = next(
            (
                row.get("value")
                for row in prompt_locks
                if isinstance(row, dict) and row.get("field") == "character_sheet.ability_point_buy"
            ),
            {},
        )
        fixed_scores = point_buy_lock.get("fixed_scores") if isinstance(point_buy_lock, dict) else None
        ability_scores_are_nonderivable = not (
            isinstance(fixed_scores, dict)
            and set(fixed_scores) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
            and not point_buy_lock.get("auto_abilities")
        )
        if ability_scores_are_nonderivable:
            point_buy_costs = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
            point_buy_alternatives = []
            for values in itertools.product(sorted(point_buy_costs), repeat=6):
                if sum(point_buy_costs[value] for value in values) != 27:
                    continue
                point_buy_alternatives.append({
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["STR", "DEX", "CON", "INT", "WIS", "CHA"],
                    "properties": {
                        ability: {"const": values[index]}
                        for index, ability in enumerate(("STR", "DEX", "CON", "INT", "WIS", "CHA"))
                    },
                })
            bounded_properties["ability_scores"] = {
                "oneOf": point_buy_alternatives,
                "x-point-buy-budget": 27,
            }
        background_contract = typed_choice_authority.get("background_choice") or {}
        background_adjustments = background_contract.get("ability_adjustment_by_choice") or {}
        background_choices = (choices_by_slot.get("background_choice") or {}).values()
        background_adjustment_rows = [
            authority
            for choice in background_choices
            if isinstance(choice, dict)
            for authority in [
                background_adjustments.get(choice.get("choice_id"))
                or choice.get("stage2_authority")
                or (choice.get("compatibility") or {}).get("factory", {}).get("stage2_authority")
                or {}
            ]
        ]
        background_abilities = sorted({
            ability
            for authority in background_adjustment_rows
            # Stage 1 publishes the typed contract as the adjustment itself,
            # while older choice projections wrapped it under
            # ``ability_adjustment``.  Accept both frozen representations;
            # neither path interprets planner prose.
            for adjustment in [
                authority.get("ability_adjustment")
                if isinstance(authority, dict) and isinstance(authority.get("ability_adjustment"), dict)
                else authority
            ]
            if isinstance(adjustment, dict)
            for ability in adjustment.get("allowed_abilities") or []
            if isinstance(ability, str)
        })
        if background_abilities:
            bounded_properties["background_ability"] = {"type": "string", "enum": background_abilities}
            background_amount_choices = sorted({
                amount
                for authority in background_adjustment_rows
                for adjustment in [
                    authority.get("ability_adjustment")
                    if isinstance(authority, dict) and isinstance(authority.get("ability_adjustment"), dict)
                    else authority
                ]
                if isinstance(adjustment, dict)
                for amount in (
                    adjustment.get("allowed_amounts")
                    or adjustment.get("amount_choices")
                    or []
                )
                if type(amount) is int
            })
            if background_amount_choices:
                bounded_properties["background_ability_amount"] = {
                    "type": "integer",
                    "enum": background_amount_choices,
                }

        if milestone_rows:
            asi_alternatives_by_milestone: dict[str, list[dict[str, Any]]] = {}
            for milestone in milestone_rows:
                feature = locked_records.get(milestone.get("feature_record_id")) or {}
                authority = (feature.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {})
                rule = authority.get("ability_change") or {}
                allowed_deltas = [value for value in rule.get("allowed_deltas") or [] if type(value) is int]
                budget = rule.get("budget")
                alternatives: list[dict[str, Any]] = []
                if allowed_deltas and type(budget) is int:
                    for count in range(1, 7):
                        for abilities in itertools.combinations(("STR", "DEX", "CON", "INT", "WIS", "CHA"), count):
                            for deltas in itertools.product(allowed_deltas, repeat=count):
                                if sum(deltas) != budget:
                                    continue
                                alternatives.append({
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": list(abilities),
                                    "properties": {
                                        ability: {"const": delta}
                                        for ability, delta in zip(abilities, deltas)
                                    },
                                })
                asi_alternatives_by_milestone[milestone["milestone_id"]] = alternatives
            bounded_properties["ability_score_changes_by_milestone_id"] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    row["milestone_id"]: {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["deltas"],
                        "properties": {
                            "deltas": {"oneOf": asi_alternatives_by_milestone[row["milestone_id"]]},
                        },
                    }
                    for row in milestone_rows
                },
            }

        ambiguous_progressions = {
            str(row.get("cl")): [value for value in row.get("path_ids") or [] if isinstance(value, str)]
            for row in envelope.get("path_progression_choices") or []
            if isinstance(row, dict) and isinstance(row.get("cl"), int) and len(row.get("path_ids") or []) > 1
        }
        if ambiguous_progressions:
            bounded_properties["path_progression_by_cl"] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    cl: {"type": "string", "enum": path_ids}
                    for cl, path_ids in ambiguous_progressions.items()
                },
            }

        preferred_response_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "TianxiaFoundry delegated selection-intent response",
            "type": "object",
            "additionalProperties": False,
            "required": sorted(PREFERRED_RESPONSE_KEYS),
            "properties": {
                "schema": {"const": DELEGATED_RESPONSE_SCHEMA},
                "request_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "const": request["request_sha256"]},
                "selection_intent": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["by_slot"],
                    "properties": {
                        "by_slot": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": selection_properties,
                        },
                    },
                },
                "acquisition_intent": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": sorted(PREFERRED_ACQUISITION_KEYS),
                    "properties": acquisition_properties,
                },
                "bounded_choices": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": bounded_properties,
                },
                "owner_descriptive_fields": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "identity": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}}},
                        "concept": {"type": "string"},
                    },
                },
            },
            "x-frozen-offered-choice-ids-by-slot": deepcopy(allowed_by_slot),
            "x-choice-records-by-slot": deepcopy(choices_by_slot),
            "x-advertised-advancement-choice-milestones": deepcopy(milestone_rows),
            "x-server-owned-fields": [
                "target_cl",
                "stage1_response",
                "stage2_proposal",
                "event_kinds",
                "acquisition_channels",
                "effective_cl_rows",
                "automatic_grants",
                "hashes",
                "receipts",
            ],
        }
        response_schema = {
            "schema": DELEGATED_RESPONSE_SCHEMA,
            "preferred_required": list(request["required_components"]),
            "preferred_response": preferred_response_schema,
            "historical_compatibility": [PLAN_SCHEMA, LEGACY_PLAN_SCHEMA],
            "request_sha256": request["request_sha256"],
            "forbidden_planner_fields": request["forbidden_planner_fields"],
            "server_owned": request.get("server_owned_authority", {}),
            "bounded_choice_contract": request.get("bounded_choice_contract", {}),
            "authority": "Planner prose, Stage 1 bindings, Stage 2 rows, and asserted compiled surfaces are not mechanical authority.",
        }
        binding = {
            "schema": "TianxiaFoundry.CharacterCreationRequestBinding.v1",
            "project_id": run["project_id"],
            "project_revision": run["starting_revision"],
            "content_lock_hash": request["content_lock_hash"],
            "typed_choice_snapshot_sha256": request["typed_choice_snapshot"]["snapshot_sha256"],
            "request_sha256": request["request_sha256"],
            "owner_principal_hash": self.owner_principal_hash,
        }
        entries = {
            "BINDING.json": canonical_json(binding).encode("utf-8") + b"\n",
            "COMPLETE_REQUEST.json": canonical_json(request).encode("utf-8") + b"\n",
            "README_START_HERE.md": (
                b"# Start Here: Complete Character Response\n\n"
                b"This package is an owner-mediated Manual Chat transfer for automatic character creation only. "
                b"A compatible receiving chat may be ChatGPT, ChatGPT Work, Codex, or another compatible chat. "
                b"It is not a combat or game-session control package.\n\n"
                b"Read COMPLETE_REQUEST.json, PROMPT_INSTRUCTIONS.md, and RESPONSE_SCHEMA.json. Return one "
                b"response file for this exact request. Do not edit the request, invent mechanics, call APIs, "
                b"control combat, or claim mechanical authority. Return stable offered IDs, descriptive fields, "
                b"and semantic acquisition intent/bounded choices only. Use Sphere/free-Talent pairs, ordinary "
                b"Talent IDs, and source-backed Insight occurrences; the local Factory owns target CL, "
                b"Stage 1/Stage 2 materialization, validation, compilation, and receipts. Any plan allowance "
                b"described in the request is not direct API credit.\n"
            ),
            "PROMPT_INSTRUCTIONS.md": (
                b"# Complete Character Creation Request\n\nReturn exactly one JSON object conforming "
                b"to the preferred delegated selection-intent response in RESPONSE_SCHEMA.json. Copy the exact "
                b"request_sha256 into the response. Do not choose or copy target CL, Stage 1 bindings, Stage 2 "
                b"event kinds/channels/effective CL rows, automatic grants, hashes, readiness, or artifact "
                b"identities. Select offered stable IDs only. Keep ordered priorities separate from an explicit "
                b"acquisition_intent semantic object (never backend rows) and provide only exact bounded choices advertised by the request. Owner "
                b"descriptions are allowed; prose never creates mechanics. The local Factory validates and "
                b"materializes every mechanical choice. Historical full-row responses remain compatibility input "
                b"only and must equal the server materialization.\n"
            ),
            "RESPONSE_SCHEMA.json": canonical_json(response_schema).encode("utf-8") + b"\n",
        }
        entries["SHA256SUMS.txt"] = "".join(
            f"{sha256_bytes(entries[name])}  {name}\n" for name in sorted(entries)
        ).encode("ascii")
        filename = f"CG1_COMPLETE_REQUEST_{run['project_id']}_{request['request_sha256'][:12]}.zip"
        member_inventory = [
            {"name": name, "bytes": len(entries[name]), "sha256": sha256_bytes(entries[name])}
            for name in sorted(entries)
        ]
        content_set_sha256 = sha256_json(member_inventory)
        payload = self._deterministic_zip(entries)
        return {
            "filename": filename,
            "payload": payload,
            "request_payload_sha256": self.request_payload_sha256(request),
            "member_inventory": member_inventory,
            "content_set_sha256": content_set_sha256,
            "final_zip_sha256": sha256_bytes(payload),
        }

    def complete_request_zip(self, run_id: str) -> tuple[str, bytes]:
        package = self._complete_request_package(run_id)
        return package["filename"], package["payload"]

    def complete_request_save_receipt(self, run_id: str) -> dict[str, Any]:
        """Return the bounded server-owned identity needed by native Save As."""
        run = self.get(run_id)
        request = run["request"]
        package = self._complete_request_package(run_id)
        return {
            "schema": "TianxiaFoundry.CompleteRequestSaveReceipt.v2",
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "starting_revision": run["starting_revision"],
            "filename": package["filename"],
            "request_payload_sha256": package["request_payload_sha256"],
            "content_set_sha256": package["content_set_sha256"],
            "final_zip_sha256": package["final_zip_sha256"],
            "final_zip_bytes": len(package["payload"]),
            "member_inventory": package["member_inventory"],
            "request": {
                "request_sha256": request["request_sha256"],
                "content_lock_hash": request["content_lock_hash"],
                "typed_choice_snapshot": {
                    "snapshot_sha256": request["typed_choice_snapshot"]["snapshot_sha256"],
                },
            },
        }

    def start(self, project_id: str, *, execution_mode: str, idempotency_key: str, revision_request: dict[str, Any] | None = None) -> dict[str, Any]:
        mode = str(execution_mode or "").strip().upper()
        if mode not in MODES:
            raise FoundryError("CG1_EXECUTION_MODE_INVALID", "Choose Manual Chat, Standard API, or Auto-Finalize When Clean.")
        key = str(idempotency_key or "").strip()
        if len(key) < 8:
            raise FoundryError("CG1_IDEMPOTENCY_KEY_INVALID", "The build request key must be at least 8 characters.")
        self.set_preference(project_id, mode)
        request = self._complete_request(
            project_id,
            revision_request,
            execution_mode=mode,
            idempotency_key=key,
        )
        binding = sha256_json({"project_id": project_id, "starting_revision": request["project_revision"], "content_lock_hash": request["content_lock_hash"], "execution_mode": mode, "request_sha256": request["request_sha256"], "idempotency_key": key, "owner_principal": self.owner_principal})
        request["idempotency_binding_sha256"] = binding
        with self.db.connection() as conn:
            old = conn.execute("SELECT * FROM character_creation_runs WHERE project_id=? AND idempotency_key=?", (project_id, key)).fetchone()
        if old:
            prior = self._public(old)
            if prior["execution_mode"] != mode or prior["request"].get("idempotency_binding_sha256") != binding:
                raise FoundryError("CG1_IDEMPOTENCY_CONFLICT", "That request key is bound to a different project revision, content lock, mode, request, or owner.", status_code=409)
            prior["idempotent"] = True
            return prior
        now = utcnow(); run_id = "cg1.run." + uuid.uuid4().hex
        status = "WAITING_FOR_RESPONSE" if mode == "MANUAL_CHAT" else "PREPARING_REQUEST"
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,status,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (run_id, project_id, request["project_revision"], mode, key, canonical_json(request), status, now, now))
        self._append_attempt(
            run_id,
            action_type="REQUEST_CREATED",
            status=status,
            binding={
                "request_sha256": request.get("request_sha256"),
                "project_revision": request.get("project_revision"),
                "content_lock_hash": request.get("content_lock_hash"),
                "execution_mode": mode,
                "idempotency_key": key,
            },
        )
        if mode == "MANUAL_CHAT":
            result = self.get(run_id); result["idempotent"] = False; return result
        provider_status = self.provider.status() or {}
        if not bool(provider_status.get("ready")):
            warning = {
                "code": "CG1_PROVIDER_NOT_READY_FALLBACK_MANUAL",
                "message": "The configured provider is unavailable; no request was transmitted and the run returned to Manual Chat.",
                "provider": provider_status,
            }
            transport = {
                "mode": mode,
                "provider_called": False,
                "provider_status": provider_status,
                "fallback_mode": "MANUAL_CHAT",
            }
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE character_creation_runs SET execution_mode='MANUAL_CHAT',transport_json=?,status='WAITING_FOR_RESPONSE',warnings_json=?,updated_at=? WHERE run_id=?",
                    (canonical_json(transport), canonical_json([warning]), utcnow(), run_id),
                )
            return self.get(run_id)
        return self._run_provider(run_id)

    @staticmethod
    def _parse_plan(response_text: str) -> tuple[dict[str, Any], bytes]:
        raw = response_text.encode("utf-8")
        try:
            plan = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise FoundryError("CG1_PLAN_JSON_INVALID", "The complete character plan response is not valid JSON.", details={"line": exc.lineno, "column": exc.colno}) from exc
        if isinstance(plan, dict) and not plan.get("schema") and all(
            key in plan
            for key in ("stage1_response", "target_cl", "stage2_proposal", "owner_descriptive_fields", "uncertainties", "fallbacks", "output_profile", "request_sha256")
        ):
            # The first physical owner response used the complete response
            # fields but omitted the explicit schema member. Preserve its exact
            # submitted bytes and bind this compatibility projection only in
            # memory; no response file is rewritten or silently replaced.
            plan["schema"] = PLAN_SCHEMA
        if not isinstance(plan, dict) or plan.get("schema") not in {
            PLAN_SCHEMA,
            LEGACY_PLAN_SCHEMA,
            DELEGATED_RESPONSE_SCHEMA,
        }:
            raise FoundryError(
                "CG1_PLAN_SCHEMA_INVALID",
                f"The response must use {DELEGATED_RESPONSE_SCHEMA} (preferred) or a supported historical plan schema such as TianxiaFoundry.CharacterCreationPlan.v2.",
            )
        if plan.get("schema") == DELEGATED_RESPONSE_SCHEMA:
            missing = sorted(PREFERRED_RESPONSE_KEYS - set(plan))
            extra = sorted(set(plan) - PREFERRED_RESPONSE_KEYS)
            if missing or extra:
                raise FoundryError(
                    "CG1_PREFERRED_RESPONSE_SHAPE_INVALID",
                    "The preferred delegated response must contain only selection intent, explicit acquisition intent, bounded choices, and owner descriptive fields.",
                    details={"missing": missing, "unexpected": extra},
                )
            selection = plan.get("selection_intent")
            if (
                not isinstance(selection, dict)
                or set(selection) != {"by_slot"}
                or not isinstance(selection.get("by_slot"), dict)
            ):
                raise FoundryError(
                    "CG1_PREFERRED_RESPONSE_SHAPE_INVALID",
                    "selection_intent.by_slot is required and is the only preferred selection surface.",
                )
            allowed_slots = {
                "path_choice", "method_choice", "foundation_choice", "subpath_choice",
                "background_choice", "background_sphere_choice", "background_talent_choice",
                "origin_insight_choice", "sphere_priorities", "advancement_skeleton",
                "insight_priorities", "item_priorities",
            }
            unknown_slots = sorted(set(selection["by_slot"]) - allowed_slots)
            if unknown_slots:
                raise FoundryError(
                    "CG1_PREFERRED_RESPONSE_SELECTION_INVALID",
                    "selection_intent.by_slot contains an unknown or aliased slot.",
                    details={"slots": unknown_slots},
                    status_code=422,
                )
            for slot_id, values in selection["by_slot"].items():
                if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                    raise FoundryError(
                        "CG1_PREFERRED_RESPONSE_SELECTION_INVALID",
                        "Every preferred selection slot must contain an array of non-empty stable IDs.",
                        details={"slot_id": slot_id},
                        status_code=422,
                    )
                if len(values) != len(set(values)):
                    raise FoundryError(
                        "CG1_DELEGATED_DUPLICATE_CHOICE",
                        "Preferred selection IDs may not be silently deduplicated.",
                        details={"slot_id": slot_id, "choice_ids": values},
                        status_code=409,
                    )
            acquisition = plan.get("acquisition_intent")
            if not isinstance(acquisition, dict) or set(acquisition) != set(PREFERRED_ACQUISITION_KEYS):
                raise FoundryError(
                    "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
                    "Preferred acquisition_intent must be the exact semantic object with Sphere pairs, ordinary Talent IDs, and Insight occurrences.",
                    details={
                        "required": sorted(PREFERRED_ACQUISITION_KEYS),
                        "actual": sorted(acquisition) if isinstance(acquisition, dict) else None,
                    },
                    status_code=422,
                )
            pairs = acquisition.get("sphere_free_talent_pairs")
            if not isinstance(pairs, list):
                raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "sphere_free_talent_pairs must be an array.", status_code=422)
            pair_spheres: list[str] = []
            pair_talents: list[str] = []
            for index, pair in enumerate(pairs):
                if not isinstance(pair, dict) or set(pair) != {"sphere_id", "talent_id"}:
                    raise FoundryError(
                        "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
                        "Sphere/free-Talent pairs may contain only sphere_id and talent_id.",
                        details={"index": index},
                        status_code=422,
                    )
                if not isinstance(pair.get("sphere_id"), str) or not isinstance(pair.get("talent_id"), str):
                    raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Sphere/free-Talent IDs must be strings.", details={"index": index}, status_code=422)
                pair_spheres.append(pair["sphere_id"]); pair_talents.append(pair["talent_id"])
            if len(pair_spheres) != len(set(pair_spheres)) or len(pair_talents) != len(set(pair_talents)):
                raise FoundryError("CG1_DELEGATED_DUPLICATE_CHOICE", "Sphere/free-Talent pairs must be unique.", status_code=409)
            ordinary = acquisition.get("ordinary_talent_ids")
            if not isinstance(ordinary, list) or any(not isinstance(value, str) or not value for value in ordinary):
                raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "ordinary_talent_ids must be an array of stable IDs.", status_code=422)
            if len(ordinary) != len(set(ordinary)):
                raise FoundryError("CG1_DELEGATED_DUPLICATE_CHOICE", "ordinary_talent_ids must be unique.", status_code=409)
            occurrences = acquisition.get("insight_occurrences")
            if not isinstance(occurrences, list):
                raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "insight_occurrences must be an array.", status_code=422)
            occurrence_keys: set[tuple[str, str]] = set()
            for index, occurrence in enumerate(occurrences):
                if not isinstance(occurrence, dict):
                    raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Each Insight occurrence must be an object.", details={"index": index}, status_code=422)
                if set(occurrence) - {"insight_id", "milestone_id", "parameters"}:
                    raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight occurrences contain an unsupported field.", details={"index": index}, status_code=422)
                if not isinstance(occurrence.get("insight_id"), str) or not isinstance(occurrence.get("milestone_id"), str):
                    raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight occurrences require stable insight_id and milestone_id.", details={"index": index}, status_code=422)
                key = (occurrence["insight_id"], occurrence["milestone_id"])
                if key in occurrence_keys:
                    raise FoundryError("CG1_DELEGATED_DUPLICATE_CHOICE", "An Insight occurrence is repeated for one milestone.", details={"index": index}, status_code=409)
                occurrence_keys.add(key)
                if "parameters" in occurrence and not isinstance(occurrence["parameters"], dict):
                    raise FoundryError("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight parameters must be an object.", details={"index": index}, status_code=422)
                if "parameters" in occurrence:
                    unsupported_parameters = sorted(set(occurrence["parameters"]) - {"ability"})
                    if unsupported_parameters:
                        raise FoundryError(
                            "CG1_INSIGHT_PARAMETER_OUT_OF_AUTHORITY",
                            "Preferred Insight parameters may contain only source-advertised typed ability choices; event metadata is forbidden.",
                            details={"index": index, "unsupported_parameters": unsupported_parameters},
                            status_code=422,
                        )
            if not isinstance(plan.get("bounded_choices"), dict) or not isinstance(plan.get("owner_descriptive_fields"), dict):
                raise FoundryError("CG1_PREFERRED_RESPONSE_SHAPE_INVALID", "The preferred delegated response has an invalid typed component.")
            unknown_bounded = sorted(set(plan["bounded_choices"]) - PREFERRED_BOUNDED_CHOICE_KEYS)
            if unknown_bounded:
                raise FoundryError("CG1_PREFERRED_RESPONSE_BOUNDED_FIELD_INVALID", "The preferred response supplied a bounded field not advertised by the request.", details={"fields": unknown_bounded})
        forbidden = sorted(k for k in plan if k in FORBIDDEN_PLANNER_FIELDS)
        if forbidden:
            raise FoundryError("CG1_PLANNER_AUTHORITY_FIELDS_FORBIDDEN", "Planner responses may not assert compiled surfaces, readiness, or artifact identities.", details={"fields": forbidden})
        return plan, raw

    @staticmethod
    def _server_materialized_stage1_response(
        run: dict[str, Any], intent: CanonicalSelectionIntent
    ) -> dict[str, Any]:
        """Build the closed Stage 1 response from the normalized intent.

        This is intentionally a small projection of the existing Stage 1
        contract.  It copies no planner-authored binding or hash and it never
        exposes target CL as a response choice.
        """
        request = run.get("request") or {}
        prompt = request.get("stage1_prompt") or {}
        envelope = prompt.get("envelope") or {}
        intent_doc = intent.as_dict()
        selected = intent_doc.get("selected_by_slot") or {}
        planning = intent_doc.get("planning_preferences_by_slot") or {}
        # Stage 1 records planning preferences as planning intent only.  They
        # are included in the server-owned blueprint response for transparency,
        # but the later materializer reads acquisition_intent rather than these
        # rows when creating mechanics.
        stage1_selected = {**deepcopy(planning), **deepcopy(selected)}
        owner_locks = ((request.get("delegated_choice_envelope") or {}).get("owner_locks") or {}).get("by_slot") or {}
        decisions: list[dict[str, Any]] = []
        for slot in envelope.get("decision_slots") or []:
            slot_id = slot.get("slot_id")
            if not isinstance(slot_id, str):
                continue
            values = list(stage1_selected.get(slot_id) or [])
            if not values:
                values = list(owner_locks.get(slot_id) or [])
            if values:
                decisions.append({
                    "slot_id": slot_id,
                    "state": "selected",
                    "choice_ids": values,
                })
            elif slot.get("coverage_state") == "blocked_missing_authority":
                decisions.append({
                    "slot_id": slot_id,
                    "state": "blocked_missing_authority",
                    "choice_ids": [],
                    "reason_code": slot.get("blocked_reason_code"),
                    "reason": slot.get("blocked_reason"),
                })
            elif slot.get("allow_none"):
                decisions.append({
                    "slot_id": slot_id,
                    "state": "deferred_with_reason",
                    "choice_ids": [],
                    "reason_code": "deferred_future_decision",
                    "reason": "No explicit selection was supplied; the Factory will not infer one from prose or priority order.",
                })
            else:
                decisions.append({
                    "slot_id": slot_id,
                    "state": "deferred_with_reason",
                    "choice_ids": [],
                    "reason_code": "deferred_future_decision",
                    "reason": "An exact selection is required before the Factory can compile this character.",
                })
        return {
            "protocol_version": "TianxiaFoundry.AIClipboard.Stage1.v2",
            "response_id": "cg1.materialized.stage1." + intent.intent_hash[:32],
            "prompt_id": prompt.get("prompt_id"),
            "prompt_sha256": prompt.get("prompt_sha256"),
            "project_id": envelope.get("project_id") or run.get("project_id"),
            "expected_project_revision": envelope.get("project_revision"),
            "catalog_build_id": envelope.get("catalog_build_id"),
            "content_lock_hash": envelope.get("content_lock_hash"),
            "stage_id": envelope.get("stage_id"),
            "response_payload": {
                "decisions": decisions,
                "authored_notes": [],
                "planner_rationale": "Server-materialized from validated stable-ID selection intent.",
            },
        }

    @staticmethod
    def _project_generation_route(project: dict[str, Any]) -> str:
        return next(
            (
                row.get("value")
                for row in project.get("user_locks") or []
                if isinstance(row, dict) and row.get("field") == "character_sheet.generation_route"
            ),
            "player",
        )

    @classmethod
    def _resolve_event_authority(
        cls,
        record: dict[str, Any],
        project: dict[str, Any],
        *,
        requested_kind: str | None = None,
        requested_channel: str | None = None,
        effective_cl: int | None = None,
        field: str = "stage2_record",
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve one exact kind/channel pair from the record authority.

        The project route is used only to disambiguate the established
        AI-bootstrap versus sect-trial pair when the record publishes both.
        Every selected result is still checked against the record's own
        ``allowed_kinds`` and ``allowed_channels``; no transport map grants
        authority.
        """
        auth = deepcopy(record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {})
        allowed_kinds = [value for value in auth.get("allowed_kinds") or [] if isinstance(value, str)]
        allowed_channels = [value for value in auth.get("allowed_channels") or record.get("legality", {}).get("acquisition_channels", []) if isinstance(value, str)]
        if not allowed_kinds or not allowed_channels or auth.get("authority_complete") is not True:
            raise FoundryError(
                "CG1_AUTHORITY_SHAPE_UNRESOLVED",
                "The selected authority record does not publish a complete Stage 2 kind/channel contract.",
                details={"field": field, "record_id": record.get("record_id"), "allowed_kinds": allowed_kinds, "allowed_channels": allowed_channels},
                status_code=409,
            )
        kind = "cultivation_insight_acquisition" if requested_kind == "insight_acquisition" else requested_kind
        if kind is None:
            candidates = list(allowed_kinds)
            route = cls._project_generation_route(project)
            if route == "ai_bootstrap":
                candidates = [value for value in candidates if "ai_bootstrap" in value] or candidates
            elif route != "ai_bootstrap":
                candidates = [value for value in candidates if "sect_trial" in value] or candidates
            if len(candidates) != 1:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "The installed authority permits multiple Stage 2 event kinds; choose one exact bounded kind.",
                    details={"field": field, "record_id": record.get("record_id"), "allowed_kinds": allowed_kinds, "candidates": candidates},
                    status_code=409,
                )
            kind = candidates[0]
        if kind not in allowed_kinds:
            raise FoundryError(
                "CG1_AUTHORITY_KIND_NOT_ALLOWED",
                "The requested Stage 2 kind is not advertised by the selected authority record.",
                details={"field": field, "record_id": record.get("record_id"), "requested_kind": kind, "allowed_kinds": allowed_kinds},
                status_code=409,
            )
        channel = requested_channel
        if channel is None:
            candidates = list(allowed_channels)
            preferred_tokens = {
                "ai_bootstrap": ("ai-bootstrap", "ai_bootstrap"),
                "sect_trial": ("sect-trial", "sect_trial"),
                "level_advance": ("level-advance",),
                "ability_score_change": ("level-choice",),
                "cultivation_insight_acquisition": ("cultivation-insight",),
                "typed_none": ("typed-none",),
                "background_acquisition": ("background-selection",),
                "background_sphere_acquisition": ("background-grant",),
                "background_talent_acquisition": ("background-grant",),
                "origin_insight_acquisition": ("origin-selection",),
            }
            tokens = preferred_tokens.get(kind)
            if kind == "level_talent_acquisition":
                if effective_cl == 1:
                    tokens = ("ai-bootstrap-free-cl1-talent",) if cls._project_generation_route(project) == "ai_bootstrap" else ("sect-trial-cl1-level-talent",)
                else:
                    tokens = ("level-choice",)
            if tokens is None and isinstance(kind, str):
                if "ai_bootstrap" in kind:
                    tokens = preferred_tokens["ai_bootstrap"]
                elif "sect_trial" in kind:
                    tokens = preferred_tokens["sect_trial"]
            if tokens:
                matching = [value for value in candidates if any(token in value for token in tokens)]
                if matching:
                    candidates = matching
            if len(candidates) != 1:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "The installed authority permits multiple Stage 2 channels; choose one exact bounded channel.",
                    details={"field": field, "record_id": record.get("record_id"), "kind": kind, "allowed_channels": allowed_channels, "candidates": candidates},
                    status_code=409,
                )
            channel = candidates[0]
        if channel not in allowed_channels:
            raise FoundryError(
                "CG1_AUTHORITY_CHANNEL_NOT_ALLOWED",
                "The requested Stage 2 channel is not advertised by the selected authority record.",
                details={"field": field, "record_id": record.get("record_id"), "kind": kind, "requested_channel": channel, "allowed_channels": allowed_channels},
                status_code=409,
            )
        return kind, channel, auth

    def _locked_records_for_project(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Return the exact project-locked records used by server materialization.

        The response transport is not allowed to resolve a display name or to
        consult the live catalog.  Materialization therefore reads the same
        immutable snapshot that Stage 2 will later validate.  The proof is
        performed once for this read, then every record is reconstructed through
        ProjectStore's proof-bound resolver (including authenticated Path and
        Background projections).
        """
        with self.db.connection() as conn:
            self.projects.project_lock_proof(conn, project_id)
            project_row = conn.execute(
                "SELECT project_json FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            rows = conn.execute(
                "SELECT record_id FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                (project_id,),
            ).fetchall()
            project_doc = json.loads(project_row["project_json"] or "{}") if project_row else {}
            lock_values = {
                item.get("field"): item.get("value")
                for item in project_doc.get("user_locks") or []
                if isinstance(item, dict) and isinstance(item.get("field"), str)
            }
            selected_paths = (lock_values.get("character_sheet.locked_choices") or {}).get("path_choice") or []
            authority = NonSphereAuthorityService(self.db)
            selected_feature_ids = {
                feature.get("canonical_id")
                for path_id in selected_paths
                for feature in (authority.path_profiles.get(path_id) or {}).get("features") or []
                if isinstance(feature, dict) and isinstance(feature.get("canonical_id"), str)
            }
            access_plan = lock_values.get("character_sheet.method_access_plan")
            access_method_id = access_plan.get("method_id") if isinstance(access_plan, dict) else None
            result: dict[str, dict[str, Any]] = {}
            if isinstance(access_method_id, str):
                result[access_method_id] = authority.project_locked_method_catalog_record(access_method_id)
            for row in rows:
                record_id = row["record_id"]
                if record_id.startswith("tianxia.path.") and ".feature." in record_id:
                    # Component IDs in the source index are evidence, not
                    # executable catalog records.  Only selected top-level
                    # feature authorities enter the materialization map.
                    if record_id not in selected_feature_ids:
                        continue
                    path_id = record_id.split(".feature.", 1)[0]
                    record = authority.project_locked_path_feature_catalog_record(path_id, record_id)
                elif record_id.startswith("tianxia.path."):
                    if record_id not in selected_paths:
                        continue
                    record = authority.project_locked_path_catalog_record(record_id)
                elif isinstance(access_method_id, str) and record_id == access_method_id:
                    record = authority.project_locked_method_catalog_record(record_id)
                else:
                    record = None
                if record is not None:
                    result[record_id] = record
                    continue
                try:
                    record = self.projects._resolve_locked_record_after_proof(
                        conn, project_id, record_id
                    )
                except FoundryError as exc:
                    # P2A progression may name source-text component IDs that
                    # are evidence inside a feature, not executable Stage 2
                    # records.  They remain in the immutable snapshot but are
                    # intentionally absent from the materialization map.
                    if exc.code != "NS1R_PATH_FEATURE_ID_UNKNOWN":
                        raise
                    continue
                if isinstance(record, dict):
                    result[record_id] = record
            # Path features may not be persisted as ordinary catalog rows. Add
            # the complete selected top-level feature set from the authenticated
            # P2A source once, after the immutable project proof above.
            for path_id in selected_paths:
                profile = authority.path_profiles.get(path_id) or {}
                for feature in profile.get("features") or []:
                    feature_id = feature.get("canonical_id") if isinstance(feature, dict) else None
                    if not isinstance(feature_id, str):
                        continue
                    record = authority.project_locked_path_feature_catalog_record(path_id, feature_id)
                    if isinstance(record, dict):
                        result[feature_id] = record
            return result

    @staticmethod
    def _materialization_bounded_choices(plan: dict[str, Any]) -> dict[str, Any]:
        bounded: dict[str, Any] = {}
        for key in ("bounded_choices", "bounded_choice", "choice_parameters"):
            value = plan.get(key)
            if isinstance(value, dict):
                bounded.update(deepcopy(value))
        selection = plan.get("selection_intent")
        if isinstance(selection, dict) and isinstance(selection.get("bounded_choices"), dict):
            bounded.update(deepcopy(selection["bounded_choices"]))
        return bounded

    @staticmethod
    def _selection_values(intent: CanonicalSelectionIntent, slot_id: str, owner_locks: dict[str, Any]) -> list[str]:
        selected = intent.as_dict().get("selected_by_slot") or {}
        values = selected.get(slot_id)
        if not values:
            values = owner_locks.get(slot_id)
        if isinstance(values, str):
            return [values]
        return [value for value in values or [] if isinstance(value, str) and value]

    @staticmethod
    def _unique_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[Any, ...]] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            key = (
                row.get("kind"),
                row.get("record_id"),
                row.get("effective_cl"),
                row.get("acquisition_channel"),
                sha256_json(row.get("parameters") or {}),
            )
            if key in seen:
                raise FoundryError(
                    "CG1_STAGE2_DERIVATION_DUPLICATE",
                    "The frozen authority produced a duplicate Stage 2 row; compilation is not allowed to silently deduplicate it.",
                    details={"row": row},
                    status_code=409,
                )
            seen.add(key)
            result.append(row)
        return result

    def _derive_stage2_rows_from_frozen_authority(
        self,
        run: dict[str, Any],
        project: dict[str, Any],
        intent: CanonicalSelectionIntent,
    ) -> list[dict[str, Any]]:
        """Build the closed Stage 2 event request from stable-ID intent.

        This is the preferred REC1-P1CR3 path.  The external response supplies
        stable selections and genuinely bounded values; all event kinds,
        channels, level timing, automatic grants, and bookkeeping are selected
        here from the frozen project snapshot.  A missing non-derivable value is
        reported as an owner decision rather than guessed.
        """
        records = self._locked_records_for_project(run["project_id"])
        intent_doc = intent.as_dict()
        # A delegated Path is selected in the frozen Stage 1 envelope rather
        # than necessarily being an owner lock on the project.  Reconstruct its
        # exact P2A source-bound authority here; never resolve a display label
        # through the live catalog or promote a planning priority into a Path.
        selected_path_ids = [
            value
            for value in (intent_doc.get("selected_by_slot") or {}).get("path_choice") or []
            if isinstance(value, str)
        ]
        path_authority = NonSphereAuthorityService(self.db)
        for path_id in selected_path_ids:
            path_record = path_authority.project_locked_path_catalog_record(path_id)
            if isinstance(path_record, dict):
                records[path_id] = path_record
            profile = path_authority.path_profiles.get(path_id) or {}
            for feature in profile.get("features") or []:
                feature_id = feature.get("canonical_id") if isinstance(feature, dict) else None
                if isinstance(feature_id, str):
                    feature_record = path_authority.project_locked_path_feature_catalog_record(path_id, feature_id)
                    if isinstance(feature_record, dict):
                        records[feature_id] = feature_record
        locks = {
            row.get("field"): row.get("value")
            for row in project.get("user_locks") or []
            if isinstance(row, dict) and isinstance(row.get("field"), str)
        }
        locked_choices = locks.get("character_sheet.locked_choices") or {}
        bounded = deepcopy(intent_doc.get("bounded_choices") or {})
        owner_locks = ((run.get("request") or {}).get("delegated_choice_envelope") or {}).get("owner_locks") or {}
        owner_by_slot = owner_locks.get("by_slot") or {}

        def values(slot_id: str) -> list[str]:
            selected = self._selection_values(intent, slot_id, locked_choices)
            if not selected:
                selected = [value for value in owner_by_slot.get(slot_id) or [] if isinstance(value, str)]
            return selected

        def require_record(record_id: str, field: str) -> dict[str, Any]:
            record = records.get(record_id)
            if record is None:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "The frozen project does not contain the exact authority needed to materialize this choice.",
                    details={"field": field, "record_id": record_id},
                    status_code=409,
                )
            return record

        def path_feature_kind(record: dict[str, Any]) -> str:
            return str(
                (record.get("path_feature") or {}).get("feature_kind")
                or (record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}).get("feature_kind")
                or ""
            )

        def row(kind: str | None, effective_cl: int, record_id: str, *, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
            record = require_record(record_id, "stage2_record_id")
            resolved_kind, channel, _authority = self._resolve_event_authority(
                record,
                project,
                requested_kind=kind,
                effective_cl=effective_cl,
                field="stage2_record",
            )
            return {
                "kind": resolved_kind,
                "effective_cl": effective_cl,
                "record_id": record_id,
                "acquisition_channel": channel,
                "parameters": deepcopy(parameters or {}),
            }

        scores = bounded.get("ability_scores") or bounded.get("point_buy_scores")
        if not isinstance(scores, dict):
            point_buy = locks.get("character_sheet.ability_point_buy") or {}
            fixed = point_buy.get("fixed_scores") if isinstance(point_buy, dict) else None
            auto = point_buy.get("auto_abilities") if isinstance(point_buy, dict) else None
            if isinstance(fixed, dict) and not auto and len(fixed) == 6:
                scores = fixed
        if not isinstance(scores, dict) or set(scores) != {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "Choose exact six ability scores before the Factory can materialize the starting-state event.",
                details={"field": "bounded_choices.ability_scores", "required_abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"]},
                status_code=409,
            )

        target_cl = frozen_owner_target_cl(project)
        path_ids = values("path_choice")
        if not path_ids:
            raise FoundryError(
                "CG1_DELEGATED_PATH_REQUIRED",
                "Choose at least one advancing Path before the Factory can materialize Stage 2.",
                status_code=409,
            )
        background_ids = values("background_choice")
        background_sphere_ids = values("background_sphere_choice")
        background_talent_ids = values("background_talent_choice")
        origin_ids = values("origin_insight_choice")
        if not background_ids or not background_sphere_ids or not background_talent_ids or not origin_ids:
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "The complete character requires the exact Background, Background Sphere, Background Talent, and Origin Insight choices.",
                details={
                    "missing_slots": [
                        slot for slot, selected in (
                            ("background_choice", background_ids),
                            ("background_sphere_choice", background_sphere_ids),
                            ("background_talent_choice", background_talent_ids),
                            ("origin_insight_choice", origin_ids),
                        ) if not selected
                    ]
                },
                status_code=409,
            )

        rows = [
            {
                "kind": "starting_state",
                "effective_cl": 0,
                "record_id": "tianxia.source.canon.authority.manifest.p2a.json",
                "acquisition_channel": "source-document",
                "parameters": {"ability_scores": deepcopy(scores)},
            }
        ]

        background_record = require_record(background_ids[0], "background_choice")
        adjustment = (
            background_record.get("compatibility", {}).get("factory", {})
            .get("stage2_authority", {})
            .get("ability_adjustment")
        )
        background_parameters: dict[str, Any] = {}
        if adjustment:
            selected_ability = bounded.get("background_ability")
            allowed_amounts = [
                value
                for value in (
                    adjustment.get("allowed_amounts")
                    or adjustment.get("amount_choices")
                    or []
                )
                if type(value) is int
            ]
            source_amount = adjustment.get("amount")
            amount = (
                source_amount
                if type(source_amount) is int and not allowed_amounts
                else bounded.get("background_ability_amount", source_amount)
            )
            if allowed_amounts and amount not in allowed_amounts:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "The Background ability adjustment amount is outside its frozen typed authority.",
                    details={"field": "bounded_choices.background_ability_amount", "allowed_amounts": allowed_amounts},
                    status_code=409,
                )
            if selected_ability is None:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "Choose the exact Background ability before the Factory can materialize its typed adjustment.",
                    details={"field": "bounded_choices.background_ability", "allowed_abilities": adjustment.get("allowed_abilities")},
                    status_code=409,
                )
            background_parameters = {"ability": selected_ability, "amount": amount}
        rows.append(row("background_acquisition", 1, background_ids[0], parameters=background_parameters))
        rows.append(row("background_sphere_acquisition", 1, background_sphere_ids[0]))
        rows.append(row("background_talent_acquisition", 1, background_talent_ids[0]))
        rows.append(row("origin_insight_acquisition", 1, origin_ids[0]))
        rows.extend(row("path_acquisition", 1, path_id) for path_id in path_ids)
        method_ids = values("method_choice")
        foundation_ids = values("foundation_choice")
        if method_ids:
            rows.append(row("method_acquisition", 1, method_ids[0]))
        if foundation_ids:
            rows.append(row("foundation_acquisition", 1, foundation_ids[0]))

        # A server-validated canonical grant lock is automatic authority.  In
        # its absence, only the preferred semantic acquisition object may create
        # Sphere/Talent rows; planning priorities are never promoted.
        grant_plan = (
            locks.get(COMMITTED_CATALOG_CHOICE_FIELD)
            or locks.get("character_sheet.canonical_grant_plan")
        )
        acquisition = intent_doc.get("acquisition_intent") or {}
        if not isinstance(acquisition, dict):
            raise FoundryError(
                "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
                "The canonical intent has no semantic acquisition object.",
                status_code=422,
            )
        pair_rows = [
            value for value in acquisition.get("sphere_free_talent_pairs") or []
            if isinstance(value, dict)
        ]
        sphere_pairs = [
            (value.get("sphere_id"), value.get("talent_id"))
            for value in pair_rows
            if isinstance(value.get("sphere_id"), str) and isinstance(value.get("talent_id"), str)
        ]
        if not sphere_pairs:
            accounting = grant_plan.get("grant_accounting") if isinstance(grant_plan, dict) else {}
            sphere_pairs = [
                (value.get("sphere_id"), value.get("talent_id"))
                for value in accounting.get("free_sphere_talent_grants") or []
                if isinstance(value, dict) and isinstance(value.get("sphere_id"), str) and isinstance(value.get("talent_id"), str)
            ]
        if not sphere_pairs:
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "Choose explicit Sphere acquisitions or provide a server-validated canonical grant lock; priority order alone cannot acquire a Sphere.",
                details={"field": "acquisition_intent.free_sphere_talent_grants"},
                status_code=409,
            )
        seen_spheres: set[str] = set()
        seen_free_talents: set[str] = set()
        for sphere_id, talent_id in sphere_pairs:
            if not talent_id:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "Each acquired Sphere requires one exact free-Talent selection.",
                    details={"sphere_id": sphere_id},
                    status_code=409,
                )
            if sphere_id in seen_spheres or talent_id in seen_free_talents:
                raise FoundryError(
                    "CG1_DELEGATED_DUPLICATE_CHOICE",
                    "Each acquired Sphere and free Talent may occur only once.",
                    details={"sphere_id": sphere_id, "talent_id": talent_id},
                    status_code=409,
                )
            seen_spheres.add(sphere_id)
            seen_free_talents.add(talent_id)
            sphere_record = require_record(sphere_id, "acquisition_intent.sphere_free_talent_pairs.sphere_id")
            talent_record = require_record(talent_id, "acquisition_intent.sphere_free_talent_pairs.talent_id")
            talent_authority = talent_record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
            owning_sphere = (
                talent_authority.get("owning_canonical_sphere_id")
                or talent_authority.get("sphere_id")
                or talent_record.get("owning_canonical_sphere_id")
            )
            if isinstance(owning_sphere, str) and owning_sphere != sphere_id:
                raise FoundryError(
                    "CG1_DELEGATED_FREE_TALENT_SPHERE_MISMATCH",
                    "The selected free Talent is not owned by its selected Sphere in frozen authority.",
                    details={"sphere_id": sphere_id, "talent_id": talent_id, "owning_sphere_id": owning_sphere},
                    status_code=409,
                )
            if sphere_record.get("content_type") not in {None, "sphere"} or talent_record.get("content_type") not in {None, "talent"}:
                raise FoundryError(
                    "CG1_DELEGATED_ACQUISITION_RECORD_TYPE_INVALID",
                    "A Sphere/free-Talent pair must reference frozen Sphere and Talent authority records.",
                    details={"sphere_id": sphere_id, "sphere_content_type": sphere_record.get("content_type"), "talent_id": talent_id, "talent_content_type": talent_record.get("content_type")},
                    status_code=409,
                )
            # The selected project route and each locked record's published
            # authority decide whether this is the sect-trial or AI-bootstrap
            # pair.  The response never gets to select the route by supplying a
            # convenient event kind.
            rows.append(row(None, 1, sphere_id))
            rows.append(row(None, 1, talent_id))

        accounting = grant_plan.get("grant_accounting") if isinstance(grant_plan, dict) else {}
        ordinary_ids = [
            value for value in acquisition.get("ordinary_talent_ids") or []
            if isinstance(value, str)
        ]
        if not ordinary_ids:
            ordinary_ids = [value for value in accounting.get("ordinary_talent_ids") or [] if isinstance(value, str)]
        # The complete-character source inventory is the governing capacity.
        # A project may already carry an earlier/empty catalog grant lock (for
        # example, before the delegated CL20 response has supplied its
        # acquisitions); that lock must not replace the frozen source count.
        delegated_envelope = (run.get("request") or {}).get("delegated_choice_envelope") or {}
        source_count = delegated_envelope.get("ordinary_talent_count")
        authority_count = source_count if type(source_count) is int else (
            accounting.get("ordinary_talent_count") if isinstance(accounting, dict) else None
        )
        if authority_count is None:
            authority_count = target_cl
        if type(authority_count) is not int or authority_count != target_cl:
            raise FoundryError(
                "CG1_ORDINARY_TALENT_COUNT_AUTHORITY_UNRESOLVED",
                "The installed source authority does not expose the currently supported one-ordinary-Talent-per-CL creation capacity.",
                details={"target_cl": target_cl, "authority_count": authority_count},
                status_code=409,
            )
        if len(ordinary_ids) != authority_count:
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "Choose exactly one source-authorized ordinary Talent for every target CL before the Factory can materialize progression.",
                details={"field": "acquisition_intent.ordinary_talent_ids", "required_count": authority_count, "actual_count": len(ordinary_ids)},
                status_code=409,
            )
        if len(ordinary_ids) != len(set(ordinary_ids)):
            raise FoundryError("CG1_DELEGATED_DUPLICATE_CHOICE", "ordinary_talent_ids must be unique.", status_code=409)

        path_authority_by_id = {
            path_id: records[path_id].get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
            for path_id in path_ids
            if path_id in records
        }
        if len(path_authority_by_id) != len(path_ids):
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "The frozen Path authority is missing an executable selected Path record.",
                details={"path_ids": path_ids},
                status_code=409,
            )
        progression_choice = bounded.get("path_progression_by_cl") or bounded.get("path_progression_choice_by_cl") or {}
        selected_progression: dict[int, tuple[str, list[str]]] = {}
        semantic_insights = [
            value for value in acquisition.get("insight_occurrences") or []
            if isinstance(value, dict)
        ]
        insight_by_milestone = {
            value.get("milestone_id"): value
            for value in semantic_insights
            if isinstance(value.get("milestone_id"), str)
        }
        asi_by_milestone = bounded.get("ability_score_changes_by_milestone_id") or {}
        if not isinstance(asi_by_milestone, dict):
            asi_by_milestone = {}
        resolved_milestones: set[str] = set()
        expected_milestones: dict[str, dict[str, Any]] = {}
        for cl in range(1, target_cl + 1):
            requested_path = progression_choice.get(str(cl), progression_choice.get(cl)) if isinstance(progression_choice, dict) else None
            available_paths = [
                path_id
                for path_id, authority in path_authority_by_id.items()
                if str(cl) in (authority.get("progression_by_cl") or {})
            ]
            if requested_path is not None:
                if str(requested_path) not in available_paths:
                    raise FoundryError(
                        "CG1_BOUNDED_DECISION_REQUIRED",
                        "The bounded Path progression choice is not available at the requested CL.",
                        details={"cl": cl, "requested_path": requested_path, "available_path_ids": available_paths},
                        status_code=409,
                    )
                progression_path = str(requested_path)
            elif len(available_paths) == 1:
                progression_path = available_paths[0]
            elif len(available_paths) > 1:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "More than one selected Path can advance at this CL; choose one exact Path progression route.",
                    details={"cl": cl, "available_path_ids": available_paths},
                    status_code=409,
                )
            else:
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "The frozen Path authority contains no progression entry for the requested CL.",
                    details={"cl": cl, "path_ids": path_ids},
                    status_code=409,
                )
            progression = (path_authority_by_id[progression_path].get("progression_by_cl") or {}).get(str(cl)) or {}
            feature_ids = [
                value for value in progression.get("feature_record_ids") or []
                if isinstance(value, str)
            ]
            if not feature_ids or any(value not in records for value in feature_ids):
                raise FoundryError(
                    "CG1_BOUNDED_DECISION_REQUIRED",
                    "The selected Path progression entry is not fully represented in the frozen record snapshot.",
                    details={"cl": cl, "path_id": progression_path, "feature_record_ids": feature_ids},
                    status_code=409,
                )
            # Representative features always use authenticated source order;
            # historical rows are compared only after this derivation.
            feature_id = feature_ids[0]
            selected_progression[cl] = (progression_path, feature_ids)
            rows.append(row("level_advance", cl, feature_id))
            path_authority = path_authority_by_id[progression_path]
            milestone_specs: list[dict[str, Any]] = []
            for feature in feature_ids:
                if path_feature_kind(records[feature]) != "advancement_choice":
                    continue
                candidates = [
                    value for value in path_authority.get("required_milestones") or []
                    if isinstance(value, dict)
                    and value.get("feature_record_id") == feature
                    and value.get("cl", cl) == cl
                    and "cultivation_insight_acquisition" in (value.get("allowed_kinds") or [])
                ]
                milestone = deepcopy(candidates[0]) if candidates else {
                    "milestone_id": f"{feature}.cl{cl}",
                    "cl": cl,
                    "feature_record_id": feature,
                    "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
                }
                milestone_id = milestone.get("milestone_id")
                if not isinstance(milestone_id, str):
                    raise FoundryError(
                        "CG1_BOUNDED_DECISION_REQUIRED",
                        "The authenticated Path authority has an advancement milestone without a stable ID.",
                        details={"cl": cl, "feature_record_id": feature},
                        status_code=409,
                    )
                milestone["milestone_id"] = milestone_id
                milestone["cl"] = cl
                milestone["feature_record_id"] = feature
                milestone_specs.append(milestone)
                expected_milestones[milestone_id] = milestone
            for milestone in milestone_specs:
                milestone_id = milestone["milestone_id"]
                insight = insight_by_milestone.get(milestone_id)
                change_entry = asi_by_milestone.get(milestone_id)
                if insight is not None and change_entry:
                    raise FoundryError(
                        "CG1_DELEGATED_AUTHORITY_CONFLICT",
                        "An Advancement Choice milestone cannot receive both an ability-score change and a Cultivation Insight.",
                        details={"milestone_id": milestone_id, "effective_cl": cl},
                        status_code=409,
                    )
                if insight is None and not change_entry:
                    raise FoundryError(
                        "CG1_BOUNDED_DECISION_REQUIRED",
                        "Resolve every source-backed advancement milestone exactly once with an ability-score change or Insight.",
                        details={
                            "field": f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}",
                            "milestone_id": milestone_id,
                            "effective_cl": cl,
                            "allowed_resolutions": ["ability_score_change", "cultivation_insight_acquisition"],
                        },
                        status_code=409,
                    )
                if insight is not None:
                    insight_id = insight.get("insight_id")
                    if not isinstance(insight_id, str):
                        raise FoundryError(
                            "CG1_BOUNDED_DECISION_REQUIRED",
                            "An Insight milestone resolution requires an exact Insight ID.",
                            details={"milestone_id": milestone_id},
                            status_code=409,
                        )
                    insight_record = require_record(insight_id, f"acquisition_intent.insight_occurrences[{milestone_id}].insight_id")
                    insight_authority = insight_record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
                    allowed_cls = insight_authority.get("allowed_cls") or insight_authority.get("allowed_effective_cls")
                    if isinstance(allowed_cls, list) and cl not in allowed_cls:
                        raise FoundryError(
                            "CG1_BOUNDED_DECISION_REQUIRED",
                            "The selected Insight is not source-authorized at this milestone CL.",
                            details={"insight_id": insight_id, "milestone_id": milestone_id, "effective_cl": cl, "allowed_cls": allowed_cls},
                            status_code=409,
                        )
                    parameters = deepcopy(insight.get("parameters") or {})
                    rule = insight_authority.get("ability_change") or insight_authority.get("insight_ability_change") or {}
                    if rule:
                        ability = parameters.get("ability")
                        if not isinstance(ability, str):
                            raise FoundryError(
                                "CG1_BOUNDED_DECISION_REQUIRED",
                                "Choose the exact typed ability for this Insight occurrence.",
                                details={"field": f"acquisition_intent.insight_occurrences[{milestone_id}].parameters.ability", "milestone_id": milestone_id, "allowed_abilities": rule.get("allowed_abilities") or []},
                                status_code=409,
                            )
                        if ability not in (rule.get("allowed_abilities") or []):
                            raise FoundryError(
                                "CG1_INSIGHT_PARAMETER_OUT_OF_AUTHORITY",
                                "The Insight ability is outside its frozen typed authority.",
                                details={"milestone_id": milestone_id, "ability": ability, "allowed_abilities": rule.get("allowed_abilities") or []},
                                status_code=409,
                            )
                        parameters["amount"] = int(rule.get("amount", 1))
                        previous_occurrences = [
                            value for value in rows
                            if value.get("kind") == "cultivation_insight_acquisition" and value.get("record_id") == insight_id
                        ]
                        parameters["repeat_index"] = len(previous_occurrences) + 1
                    else:
                        unsupported = sorted(set(parameters) - {"ability"})
                        if unsupported:
                            raise FoundryError(
                                "CG1_INSIGHT_PARAMETER_OUT_OF_AUTHORITY",
                                "The selected Insight does not publish the supplied typed parameters.",
                                details={"milestone_id": milestone_id, "fields": unsupported},
                                status_code=409,
                            )
                        parameters.pop("ability", None)
                    rows.append(row("cultivation_insight_acquisition", cl, insight_id, parameters=parameters))
                else:
                    deltas = change_entry.get("deltas") if isinstance(change_entry, dict) and isinstance(change_entry.get("deltas"), dict) else change_entry
                    if not isinstance(deltas, dict) or not deltas:
                        raise FoundryError(
                            "CG1_BOUNDED_DECISION_REQUIRED",
                            "An ability-score milestone requires typed deltas.",
                            details={"milestone_id": milestone_id},
                            status_code=409,
                        )
                    rows.append(row("ability_score_change", cl, milestone["feature_record_id"], parameters={"deltas": deepcopy(deltas)}))
                resolved_milestones.add(milestone_id)
            if cl == 3 and any(
                path_feature_kind(records[feature]) == "subpath_selection"
                for feature in feature_ids
            ):
                subpaths = values("subpath_choice")
                if subpaths:
                    subpath_record = require_record(subpaths[0], "subpath_choice")
                    minimum = int(subpath_record.get("legality", {}).get("minimum_cl") or 3)
                    if minimum <= cl:
                        rows.append(row("subpath_acquisition", cl, subpaths[0]))
            rows.append(row("level_talent_acquisition", cl, ordinary_ids[cl - 1]))

        for item in intent_doc.get("compatibility_item_occurrences") or []:
            if not isinstance(item, dict) or not isinstance(item.get("record_id"), str):
                raise FoundryError(
                    "CG1_HISTORICAL_ITEM_UNRESOLVED",
                    "A compatibility item occurrence lacks a stable source record ID.",
                    status_code=422,
                )
            item_record = require_record(item["record_id"], "compatibility_item_occurrences.record_id")
            item_authority = item_record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
            allowed_cls = item_authority.get("allowed_cls") or item_authority.get("allowed_effective_cls") or []
            if isinstance(allowed_cls, list) and len(allowed_cls) == 1 and isinstance(allowed_cls[0], int):
                item_cl = allowed_cls[0]
            else:
                item_cl = item_authority.get("minimum_cl")
            if type(item_cl) is not int:
                raise FoundryError(
                    "CG1_HISTORICAL_ITEM_UNRESOLVED",
                    "A compatibility item occurrence has no uniquely source-derived effective CL.",
                    details={"record_id": item["record_id"], "allowed_cls": allowed_cls},
                    status_code=422,
                )
            rows.append(row(None, item_cl, item["record_id"], parameters=item.get("parameters") or {}))

        unknown_insights = sorted(set(insight_by_milestone) - set(expected_milestones))
        unknown_asi = sorted(set(asi_by_milestone) - set(expected_milestones))
        if unknown_insights or unknown_asi:
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "A response supplied a resolution for a milestone that is not advertised by the frozen Path authority.",
                details={"unknown_insight_milestone_ids": unknown_insights, "unknown_ability_score_milestone_ids": unknown_asi},
                status_code=409,
            )
        if resolved_milestones != set(expected_milestones):
            raise FoundryError(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "Every advertised advancement milestone must be resolved exactly once.",
                details={"expected_milestone_ids": sorted(expected_milestones), "resolved_milestone_ids": sorted(resolved_milestones)},
                status_code=409,
            )

        def none_parameters(target: str, reason: str) -> dict[str, Any]:
            return {
                "target": target,
                "reason_code": "not_selected_for_c1a_proof",
                "reason": reason,
            }

        if not method_ids:
            rows.append(row("typed_none", target_cl, "tianxia.c1a.none.method", parameters=none_parameters("method", "No exact Method was selected for this bounded character response.")))
        if not foundation_ids:
            rows.append(row("typed_none", target_cl, "tianxia.c1a.none.foundation", parameters=none_parameters("foundation", "No exact Foundation was selected for this bounded character response.")))
        if not values("subpath_choice"):
            rows.append(row("typed_none", target_cl, "tianxia.c1a.none.subpaths", parameters=none_parameters("subpaths", "No Subpath or Tradition was selected.")))
        for target in ("manuals", "equipment", "forged_techniques"):
            rows.append(row("typed_none", target_cl, f"tianxia.c1a.none.{target}", parameters=none_parameters(target, f"No {target.replace('_', ' ')} was selected.")))
        return self._unique_rows(rows)

    def _historical_stage2_rows_match_derived(
        self,
        historical_rows: list[dict[str, Any]],
        derived_rows: list[dict[str, Any]],
        *,
        run: dict[str, Any],
        project: dict[str, Any],
        intent: CanonicalSelectionIntent,
    ) -> bool:
        """Compare historical rows without promoting their representation.

        Older complete-plan producers emitted one representative Path feature
        per CL and used ``level-choice`` for a CL1 ordinary Talent.  The
        current materializer resolves the exact source-authorized feature and
        channel itself, so those historical representations are compatible
        only when they identify the same frozen progression/record authority.
        Explanatory text on typed-none rows is likewise compatibility metadata,
        not a mechanical input.
        """
        if len(historical_rows) != len(derived_rows):
            return False

        def parameters(row: dict[str, Any]) -> dict[str, Any]:
            raw = row.get("parameters")
            if not isinstance(raw, dict):
                raw = {}
            if row.get("kind") == "typed_none":
                return {
                    key: deepcopy(raw[key])
                    for key in ("target", "reason_code")
                    if key in raw
                }
            return deepcopy(raw)

        selected_paths = [
            value
            for value in (intent.as_dict().get("selected_by_slot") or {}).get("path_choice") or []
            if isinstance(value, str)
        ]
        path_authority = NonSphereAuthorityService(self.db)
        path_feature_alternatives: dict[tuple[int, str], set[str]] = {}
        for path_id in selected_paths:
            path_record = path_authority.project_locked_path_catalog_record(path_id)
            authority = (
                path_record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
                if isinstance(path_record, dict)
                else {}
            )
            for raw_cl, progression in (authority.get("progression_by_cl") or {}).items():
                if not isinstance(progression, dict):
                    continue
                try:
                    effective_cl = int(raw_cl)
                except (TypeError, ValueError):
                    continue
                path_feature_alternatives[(effective_cl, path_id)] = {
                    value
                    for value in progression.get("feature_record_ids") or []
                    if isinstance(value, str)
                }

        records = self._locked_records_for_project(run["project_id"])
        for historical, derived in zip(historical_rows, derived_rows):
            if not isinstance(historical, dict) or not isinstance(derived, dict):
                return False
            if (
                historical.get("kind") == derived.get("kind")
                and historical.get("effective_cl") == derived.get("effective_cl")
                and historical.get("record_id") == derived.get("record_id")
                and historical.get("acquisition_channel") == derived.get("acquisition_channel")
                and parameters(historical) == parameters(derived)
            ):
                continue
            if (
                historical.get("kind") != derived.get("kind")
                or historical.get("effective_cl") != derived.get("effective_cl")
                or parameters(historical) != parameters(derived)
            ):
                return False

            kind = derived.get("kind")
            if kind == "level_advance":
                try:
                    effective_cl = int(derived.get("effective_cl"))
                except (TypeError, ValueError):
                    return False
                alternatives = set()
                for path_id in selected_paths:
                    alternatives.update(path_feature_alternatives.get((effective_cl, path_id), set()))
                if (
                    derived.get("record_id") not in alternatives
                    or historical.get("record_id") not in alternatives
                    or historical.get("acquisition_channel") != derived.get("acquisition_channel")
                ):
                    return False
                continue

            if kind == "level_talent_acquisition":
                if historical.get("record_id") != derived.get("record_id"):
                    return False
                # Established plans represented the CL1 ordinary-Talent row as
                # level-choice even though the current route resolves it to the
                # explicit AI-bootstrap/sect-trial free-at-CL1 channel.
                if (
                    historical.get("acquisition_channel") != "level-choice"
                    or "cl1-talent" not in str(derived.get("acquisition_channel"))
                ):
                    return False
                record = records.get(str(historical.get("record_id")))
                if not isinstance(record, dict):
                    return False
                try:
                    self._resolve_event_authority(
                        record,
                        project,
                        requested_kind=kind,
                        requested_channel="level-choice",
                        effective_cl=int(historical.get("effective_cl")),
                        field="historical_stage2_record",
                    )
                except (FoundryError, TypeError, ValueError):
                    return False
                continue

            if kind == "origin_insight_acquisition":
                if {
                    historical.get("acquisition_channel"),
                    derived.get("acquisition_channel"),
                } == {"origin-selection", "origin-insight-selection"}:
                    continue

            return False
        return True

    def _server_materialized_stage2_proposal(
        self,
        run: dict[str, Any],
        project: dict[str, Any],
        intent: CanonicalSelectionIntent,
        plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Materialize explicit acquisition intent into Stage 2 request rows.

        The common production response supplies only the acquisition objects
        that are not derivable from the frozen authority.  Existing complete
        Stage 2 rows are retained solely as compatibility input; they are
        validated and compared by the Stage 2 authority rather than trusted as
        a new authority surface.
        """
        existing = plan.get("stage2_proposal")
        rows = self._derive_stage2_rows_from_frozen_authority(run, project, intent)
        result = {
            "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
            "project_id": run["project_id"],
            "expected_project_revision": run["starting_revision"] + 1,
            "expected_content_lock_hash": run["request"].get("content_lock_hash"),
            "target_cl": frozen_owner_target_cl(project),
            "idempotency_key": "cg1.materialized.stage2." + intent.intent_hash[:32],
            "choices": rows,
        }
        if isinstance(existing, dict) and isinstance(existing.get("choices"), list) and existing.get("choices"):
            def semantic_rows(value: Any) -> list[dict[str, Any]]:
                return [
                    {
                        "kind": "cultivation_insight_acquisition" if row.get("kind") == "insight_acquisition" else row.get("kind"),
                        "effective_cl": row.get("effective_cl"),
                        "record_id": row.get("record_id"),
                        "acquisition_channel": row.get("acquisition_channel"),
                        "parameters": deepcopy(row.get("parameters") or {}),
                    }
                    for row in value
                    if isinstance(row, dict)
                ]

            historical_semantics = semantic_rows(existing.get("choices"))
            derived_semantics = semantic_rows(rows)
            if not self._historical_stage2_rows_match_derived(
                historical_semantics,
                derived_semantics,
                run=run,
                project=project,
                intent=intent,
            ):
                raise FoundryError(
                    "CG1_HISTORICAL_STAGE2_MISMATCH",
                    "Historical Stage 2 rows are compatibility evidence only and do not equal the server-derived proposal.",
                    details={
                        "historical": historical_semantics,
                        "derived": derived_semantics,
                    },
                    status_code=409,
                )
        return result

    def _normalize_and_materialize_response(
        self, run: dict[str, Any], plan: dict[str, Any]
    ) -> tuple[dict[str, Any], CanonicalSelectionIntent | None, dict[str, Any] | None]:
        if not self._has_delegated_envelope(run):
            return deepcopy(plan), None, None
        project = self._project(run["project_id"])
        target_cl = frozen_owner_target_cl(project)
        intent = normalize_selection_intent(
            plan,
            request_sha256=str(run["request"].get("request_sha256") or ""),
            delegated_envelope=run["request"].get("delegated_choice_envelope") or {},
            project=project,
            target_cl=target_cl,
        )
        normalized = inject_canonical_intent(plan, intent, target_cl=target_cl)
        if not isinstance(normalized.get("stage1_response"), dict):
            normalized["stage1_response"] = self._server_materialized_stage1_response(run, intent)
        normalized.setdefault("uncertainties", [])
        normalized.setdefault("fallbacks", [])
        normalized.setdefault(
            "output_profile",
            {"combat_ready": False, "profile": "CHARACTER_GM_MODEL"},
        )
        stage2 = self._server_materialized_stage2_proposal(run, project, intent, normalized)
        if stage2 is not None:
            normalized["stage2_proposal"] = stage2
        normalized["materialization_receipt"] = {
            "schema": "TianxiaFoundry.DelegatedMaterializationReceipt.v1",
            "canonical_intent_hash": intent.intent_hash,
            "request_sha256": run["request"].get("request_sha256"),
            "delegated_envelope_sha256": (run["request"].get("delegated_choice_envelope") or {}).get("envelope_sha256"),
            "target_cl": target_cl,
            "stage1_server_owned": True,
            "stage2_server_owned": stage2 is not None,
            "mode": "historical_rows_compatibility_input" if isinstance(plan.get("stage2_proposal"), dict) and isinstance(plan.get("stage2_proposal", {}).get("choices"), list) and plan.get("stage2_proposal", {}).get("choices") else "server_materialized_from_selection_intent",
        }
        return normalized, intent, stage2

    def _validate_complete_response_binding(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        *,
        submitted_request_sha256: str | None = None,
    ) -> None:
        active = str(run["request"].get("request_sha256") or "")
        response_hash = plan.get("request_sha256")
        mismatches: list[str] = []
        if not isinstance(response_hash, str) or response_hash != active:
            mismatches.append("response.request_sha256")
        if submitted_request_sha256 is not None and submitted_request_sha256 != active:
            mismatches.append("submission.request_sha256")
        if mismatches:
            raise FoundryError(
                RESPONSE_BINDING_ERROR,
                RESPONSE_BINDING_MESSAGE,
                details={
                    "mismatched_fields": mismatches,
                    "active_request_sha256": active,
                    "response_request_sha256": response_hash if isinstance(response_hash, str) else None,
                    "submitted_request_sha256": submitted_request_sha256,
                },
                status_code=409,
            )

    @staticmethod
    def _validate_preferred_bounded_fields(run: dict[str, Any], plan: dict[str, Any]) -> None:
        """Reject typed fields that the sealed request did not advertise."""
        if plan.get("schema") != DELEGATED_RESPONSE_SCHEMA:
            return
        bounded = plan.get("bounded_choices")
        if not isinstance(bounded, dict):
            return
        advertised = (
            ((run.get("request") or {}).get("bounded_choice_contract") or {}).get("fields")
            or {}
        )
        unknown = sorted(set(bounded) - set(advertised))
        if unknown:
            raise FoundryError(
                "CG1_PREFERRED_RESPONSE_BOUNDED_FIELD_INVALID",
                "The preferred response supplied a bounded field not advertised by the sealed request.",
                details={"fields": unknown},
                status_code=422,
            )

    def _required_collaborators(self, combat_requested: bool) -> list[str]:
        if self.production_release is not None:
            required = ["stage1", "stage2", "projections", "character_sheets", "factory_authoring"]
            if combat_requested:
                required.append("combat_readiness")
            return required
        required = ["stage1", "stage2", "projections", "character_sheets", "factory_authoring", "gm_exports", "gm_consumer", "portable_characters"]
        if combat_requested:
            required.append("combat_readiness")
        return required

    def _collaborator_blockers(self, combat_requested: bool) -> list[dict[str, Any]]:
        blockers=[]
        if self.production_release is not None:
            readiness = self.production_release.readiness()
            if not readiness.get("ready"):
                blockers.append({
                    "code": "CG1_PRODUCTION_AUTHORITY_NOT_READY",
                    "collaborator": "production_release",
                    "message": "The concrete production release authority is unavailable.",
                    "readiness": readiness,
                })
        for name in self._required_collaborators(combat_requested):
            if getattr(self, name, None) is None and self.pipeline_factory is None:
                blockers.append({"code":"CG1_REQUIRED_COLLABORATOR_MISSING","collaborator":name,"message":f"Required local service is unavailable: {name}."})
        return blockers

    def _backup_database(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.execute("PRAGMA wal_checkpoint(FULL)")
            src.backup(dst)

    def _snapshot_data(self, target: Path) -> dict[str, str]:
        src = self.db.settings.data_dir
        target.mkdir(parents=True, exist_ok=True)
        db_rel = self.db.settings.db_path.relative_to(src)
        for item in src.iterdir():
            if item == self.db.settings.db_path or item.name in {self.db.settings.db_path.name+"-wal", self.db.settings.db_path.name+"-shm"}:
                continue
            dest=target/item.name
            if item.is_dir(): shutil.copytree(item,dest,symlinks=True)
            else: shutil.copy2(item,dest)
        self._backup_database(self.db.settings.db_path, target/db_rel)
        return self._tree_hashes(target)

    @staticmethod
    def _tree_hashes(root: Path) -> dict[str, str]:
        return {p.relative_to(root).as_posix():sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file() and not p.name.endswith(("-wal","-shm"))}

    def _restore_data(self, snapshot: Path) -> None:
        live=self.db.settings.data_dir
        for child in list(live.iterdir()):
            if child == self.db.settings.db_path or child.name in {
                self.db.settings.db_path.name+"-wal", self.db.settings.db_path.name+"-shm"
            }:
                continue
            if child.is_dir(): shutil.rmtree(child)
            else: child.unlink(missing_ok=True)
        for child in snapshot.iterdir():
            if child.name == self.db.settings.db_path.name:
                continue
            dest=live/child.name
            if child.is_dir(): shutil.copytree(child,dest,symlinks=True)
            else: shutil.copy2(child,dest)
        source_db = snapshot / self.db.settings.db_path.name
        restore_db = self.db.settings.db_path.with_name(self.db.settings.db_path.name + ".cg1-restore")
        shutil.copy2(source_db, restore_db)
        last_error: OSError | None = None
        for _attempt in range(40):
            try:
                os.replace(restore_db, self.db.settings.db_path)
                for suffix in ("-wal", "-shm"):
                    self.db.settings.db_path.with_name(self.db.settings.db_path.name + suffix).unlink(missing_ok=True)
                return
            except OSError as exc:
                last_error = exc
                gc.collect()
                time.sleep(0.05)
        raise FoundryError(
            "CG1_ATOMIC_RESTORE_FILE_LOCKED",
            "The exact precommit database bytes could not be restored.",
            details={"path": str(self.db.settings.db_path), "cause": str(last_error)},
        )

    def _scratch_services(self, scratch_db: Database) -> dict[str, Any]:
        if self.pipeline_factory:
            return self.pipeline_factory(scratch_db)
        from stage1.service import Stage1ClipboardService
        from stage2 import Stage2AdvancementService
        from projector.service import ProjectionService
        from character_sheet import CharacterSheetService
        from factory_authoring import FactoryAuthoringWorkspaceService
        from gm_export import GMCharacterExportService
        from portable_character import PortableCharacterPackageService
        from character_creation.production_release import CharacterProductionReleaseAdapter, _COMBAT_REQUIRED_FIELDS
        return {
            "stage1": Stage1ClipboardService(scratch_db), "stage2": Stage2AdvancementService(scratch_db),
            "projections": ProjectionService(scratch_db), "character_sheets": CharacterSheetService(scratch_db),
            "factory_authoring": FactoryAuthoringWorkspaceService(scratch_db), "gm_exports": GMCharacterExportService(scratch_db),
            "portable_characters": PortableCharacterPackageService(scratch_db), "gm_consumer": self.gm_consumer,
            "combat_readiness": self.combat_readiness, "production_release": CharacterProductionReleaseAdapter(scratch_db),
        }

    @staticmethod
    def _invoke(obj: Any, names: tuple[str,...], *args: Any, **kwargs: Any) -> Any:
        for name in names:
            fn=getattr(obj,name,None)
            if callable(fn):
                try: return fn(*args,**kwargs)
                except TypeError:
                    try: return fn(*args)
                    except TypeError: continue
        raise FoundryError("CG1_REQUIRED_OPERATION_MISSING", f"Required operation is unavailable: {names[0]}.", details={"operations":names})

    @staticmethod
    def _canonicalize_stage2_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
        """Copy the Stage 2 request and canonicalize its one legacy kind alias."""
        normalized = deepcopy(proposal)
        choices = normalized.get("choices")
        if not isinstance(choices, list):
            return normalized
        for choice in choices:
            if isinstance(choice, dict) and choice.get("kind") == "insight_acquisition":
                choice["kind"] = "cultivation_insight_acquisition"
        return normalized

    def _stage2_commit(
        self,
        svc: Any,
        proposal: dict[str, Any],
        owner: str,
        *,
        creation_run: dict[str, Any] | None = None,
        phase: str | None = None,
    ) -> tuple[Any,Any]:
        scope = nullcontext()
        scope_factory = getattr(svc, "_trusted_character_creation_scope", None)
        if creation_run is not None and callable(scope_factory):
            snapshot = creation_run.get("request", {}).get("typed_choice_snapshot") or {}
            scope = scope_factory(
                run_id=creation_run["run_id"],
                project_id=creation_run["project_id"],
                starting_revision=creation_run["starting_revision"],
                content_lock_hash=creation_run["request"]["content_lock_hash"],
                typed_choice_snapshot_sha256=snapshot["snapshot_sha256"],
                phase=phase,
                candidate_identity=(creation_run.get("dry_run") or {}).get("candidate_identity") if phase == "finalization" else None,
                _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
            )
        with scope:
            stage2_proposal = self._canonicalize_stage2_proposal(proposal)
            # A server-materialized proposal is deliberately rebound to the
            # post-Stage-1 scratch revision here.  The response never authors
            # this value; the active Stage 2 database and frozen content lock
            # do.  Historical full-row callers retain their established
            # proposal binding semantics.
            if creation_run is not None and (
                creation_run.get("canonical_selection_intent")
                or (
                    isinstance((creation_run.get("response") or {}).get("parsed_plan"), dict)
                    and (creation_run.get("response") or {}).get("parsed_plan", {}).get("canonical_selection_intent")
                )
            ):
                with svc.db.connection() as conn:
                    project_row = conn.execute(
                        "SELECT revision,project_json FROM projects WHERE project_id=?",
                        (creation_run["project_id"],),
                    ).fetchone()
                if project_row:
                    project_doc = json.loads(project_row["project_json"] or "{}")
                    stage2_proposal["expected_project_revision"] = int(project_row["revision"])
                    stage2_proposal["expected_content_lock_hash"] = (
                        project_doc.get("content_lock") or {}
                    ).get("lock_hash") or stage2_proposal.get("expected_content_lock_hash")
                    stage2_proposal["target_cl"] = frozen_owner_target_cl(project_doc)
            created=self._invoke(svc,("create_proposal",),stage2_proposal)
            pid=(created or {}).get("proposal_id") if isinstance(created,dict) else created
            validation=self._invoke(svc,("validate_proposal",),pid)
            if isinstance(validation,dict) and validation.get("valid") is False:
                raise FoundryError("CG1_STAGE2_INVALID","Stage 2 validation rejected the proposed advancement.",details=validation)
            if hasattr(svc,"issue_approval_challenge"):
                issued=svc.issue_approval_challenge(pid)
                ch=issued.get("challenge", issued)
                try: svc.approve_proposal(pid, challenge_id=ch.get("challenge_id"), nonce=ch.get("nonce"), approved_by=owner)
                except TypeError:
                    try: svc.approve_proposal(pid, ch.get("challenge_id"), ch.get("nonce"), owner)
                    except TypeError: svc.approve_proposal(pid, approved_by=owner)
            result=self._invoke(svc,("commit_proposal",),pid)
            return validation,result

    @staticmethod
    def _identity_payload(
        value: Any,
        *,
        _context: tuple[str, ...] = (),
        _surface: str | None = None,
    ) -> Any:
        if isinstance(value, dict):
            source = value.get("source")
            if isinstance(source, str) and (
                source.startswith("cg1-delegated-final-grant-plan:")
                or source.startswith("cg1-owner-descriptive:")
            ):
                # Older projects may retain a phase suffix on the same
                # server-derived lock.  The suffix is audit metadata, not
                # character mechanics.
                value = deepcopy(value)
                value["source"] = source.rsplit(":", 1)[0]
                wrapped = value.get("value")
                if isinstance(wrapped, dict) and isinstance(wrapped.get("binding"), dict):
                    wrapped["binding"].pop("phase", None)
            # Only approval/challenge envelopes and explicitly transient
            # process metadata are excluded. Mechanical manifests, package
            # digests, event/state/project hashes, sheet/GM semantics, clean
            # import proofs, and readiness receipts remain identity inputs.
            execution_envelope_fields = set(_IDENTITY_RECEIPT_PROCESS_FIELDS)
            transient_location_fields = {
                "path",
                "artifact_path",
                "package_path",
                "workspace_path",
                "created_at",
                "updated_at",
                "completed_at",
                "phase",
                 "build_manifest_path",
                "candidate_zip",
                "deep_audit_path",
                "gm_model_path",
                "gm_view_model_path",
                "seal_run",
                "harness_run",
                "consumer_root",
                "harness_package_path",
            }
            semantic_context_keys = {
                "identity",
                "mechanics",
                "content",
                "model",
                "stats",
                "cultivation",
                "paths",
                "talents",
                "insights",
                "actions",
                "features",
                "readiness",
            }
            normalized: dict[str, Any] = {}
            folded_context = tuple(str(part).casefold() for part in _context)
            receipt_context = bool(
                set(folded_context) & _IDENTITY_RECEIPT_CONTEXT_NAMES
            )
            for key, item in sorted(value.items()):
                context_keys = {str(part).casefold() for part in _context}
                semantic_context = bool(context_keys & semantic_context_keys)
                key_folded = str(key).casefold()
                root_context = not _context
                identity_path = (*tuple(str(part).casefold() for part in _context), key_folded)
                if receipt_context and (
                    key_folded in _IDENTITY_RECEIPT_PROCESS_FIELDS
                    or key_folded in _IDENTITY_RECEIPT_PROCESS_TIMESTAMP_FIELDS
                    or key_folded in _IDENTITY_RECEIPT_TRANSIENT_PATH_FIELDS
                    or (
                        key_folded in {"mac", "key_id", "domain", "algorithm", "projection_hash"}
                        and bool(set(folded_context) & {"approval_evidence", "integrity"})
                    )
                ):
                    # Stage 2 returns its terminal result as
                    # ``{"receipt": {...}, "project": ..., "replay": ...}``.
                    # These values are excluded only while inside a recognized
                    # receipt envelope.  Do not turn this into a recursive
                    # ``*_hash`` blacklist: event, state, project, source,
                    # package, and model hashes in the same receipt remain
                    # substantive candidate identity.
                    continue
                if key_folded in execution_envelope_fields and root_context and not semantic_context:
                    continue
                if key_folded in transient_location_fields and root_context and not semantic_context:
                    continue
                if identity_path in _IDENTITY_TRANSIENT_PATHS:
                    continue
                if root_context and key_folded in _IDENTITY_SURFACE_ROOT_FIELDS.get(str(_surface or "").casefold(), ()):
                    continue
                if key_folded == "id" and "package_identity" in context_keys:
                    continue
                if key_folded == "selected_id" and ({"consumer", "consumer_report"} & context_keys):
                    continue
                if key_folded in {"created_at", "updated_at", "verified_at"} and root_context:
                    continue
                if key_folded == "source" and isinstance(item, str) and (
                    item.startswith("cg1-delegated-final-grant-plan:")
                    or item.startswith("cg1-owner-descriptive:")
                ):
                    item = item.rsplit(":", 1)[0]
                normalized[key] = CharacterCreationExecutionService._identity_payload(
                    item,
                    _context=(*_context, str(key)),
                    _surface=_surface,
                )
            return normalized
        if isinstance(value, list):
            return [
                CharacterCreationExecutionService._identity_payload(v, _context=_context, _surface=_surface)
                for v in value
            ]
        return value

    @staticmethod
    def _identity_differences(left: Any, right: Any, *, _path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        if len(_path) > 8:
            return [] if left == right else [{"path": ".".join(_path), "left": left, "right": right}]
        if isinstance(left, dict) and isinstance(right, dict):
            differences: list[dict[str, Any]] = []
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    differences.append({"path": ".".join((*_path, str(key))), "left": left.get(key), "right": right.get(key)})
                else:
                    differences.extend(CharacterCreationExecutionService._identity_differences(left[key], right[key], _path=(*_path, str(key))))
                if len(differences) >= 20:
                    return differences[:20]
            return differences
        if isinstance(left, list) and isinstance(right, list):
            differences: list[dict[str, Any]] = []
            for index in range(max(len(left), len(right))):
                if index >= len(left) or index >= len(right):
                    differences.append({"path": ".".join((*_path, str(index))), "left": left[index] if index < len(left) else None, "right": right[index] if index < len(right) else None})
                else:
                    differences.extend(CharacterCreationExecutionService._identity_differences(left[index], right[index], _path=(*_path, str(index))))
                if len(differences) >= 20:
                    return differences[:20]
            return differences
        return [] if left == right else [{"path": ".".join(_path), "left": left, "right": right}]

    @staticmethod
    def _has_delegated_envelope(run: dict[str, Any]) -> bool:
        return bool((run.get("request") or {}).get("delegated_choice_envelope"))

    def _plan_with_accepted_final_target(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        accepted_final_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Make every compilation surface consume the accepted target CL."""

        if not self._has_delegated_envelope(run) or accepted_final_plan is None:
            return plan
        target_cl = validate_accepted_final_plan_target(
            run,
            self._project(run["project_id"]),
            accepted_final_plan,
        )
        bound = deepcopy(plan)
        bound["target_cl"] = target_cl
        stage2 = bound.get("stage2_proposal")
        if isinstance(stage2, dict):
            stage2["target_cl"] = target_cl
        return bound

    def _derive_delegated_final_grant_plan(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        final_plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Derive the exact canonical grant/accounting plan from accepted response rows."""
        if not self._has_delegated_envelope(run):
            return final_plan
        stage2 = catalog_stage2_selections(plan)
        resolution = final_plan.get("resolution") or {}
        selected_by_slot = resolution.get("selected_choices_by_slot") or {}

        def selected(slot_id: str) -> list[str]:
            return [value for value in selected_by_slot.get(slot_id) or [] if isinstance(value, str)]

        # Planning priorities are deliberately not compared with mechanical
        # rows.  Only the semantic acquisition object is an acquisition
        # representation; Stage 2 is the Factory's derived representation.
        canonical_intent = plan.get("canonical_selection_intent") or {}
        semantic_acquisition = canonical_intent.get("acquisition_intent") if isinstance(canonical_intent, dict) else {}
        requested_insights = [
            value.get("insight_id")
            for value in (semantic_acquisition or {}).get("insight_occurrences") or []
            if isinstance(value, dict) and isinstance(value.get("insight_id"), str)
        ]
        if requested_insights != list(stage2["insight_ids"]):
            raise FoundryError(
                "CG1_DELEGATED_CATALOG_REPRESENTATION_MISMATCH",
                "The server-derived Stage 2 Insight occurrences do not equal the semantic Insight acquisition intent.",
                details={
                    "requested_insight_ids": requested_insights,
                    "stage2_insight_ids": list(stage2["insight_ids"]),
                    "stage2_insight_occurrences": deepcopy(stage2["insight_occurrences"]),
                },
                status_code=409,
            )
        sphere_ids = list(stage2["sphere_ids"])
        free_talent_ids = list(stage2["free_sphere_talent_ids"])
        ordinary_talent_ids = list(stage2["ordinary_talent_ids"])
        if len(sphere_ids) != len(set(sphere_ids)) or len(free_talent_ids) != len(set(free_talent_ids)) or len(ordinary_talent_ids) != len(set(ordinary_talent_ids)):
            raise FoundryError(
                "CG1_DELEGATED_DUPLICATE_CHOICE",
                "The accepted delegated catalog response repeats a canonical acquisition.",
                details={"sphere_ids": sphere_ids, "free_sphere_talent_ids": free_talent_ids, "ordinary_talent_ids": ordinary_talent_ids},
                status_code=409,
            )
        catalog = CanonicalCatalogAuthorityService(self.db.settings.root_dir)
        free_by_sphere: dict[str, str] = {}
        for talent_id in free_talent_ids:
            talent = catalog.get_talent(talent_id)
            sphere_id = talent.get("owning_canonical_sphere_id")
            if not isinstance(sphere_id, str) or sphere_id not in sphere_ids:
                raise FoundryError(
                    "CG1_DELEGATED_FREE_TALENT_SPHERE_MISMATCH",
                    "Every accepted free Sphere Talent must belong to an accepted Sphere grant.",
                    details={"talent_id": talent_id, "owning_sphere_id": sphere_id, "sphere_ids": sphere_ids},
                    status_code=409,
                )
            if sphere_id in free_by_sphere:
                raise FoundryError(
                    "CG1_DELEGATED_DUPLICATE_CHOICE",
                    "A Sphere received more than one accepted free Talent grant.",
                    details={"sphere_id": sphere_id, "talent_ids": [free_by_sphere[sphere_id], talent_id]},
                    status_code=409,
                )
            free_by_sphere[sphere_id] = talent_id
        try:
            # Background Sphere/Talent choices remain on the separately
            # authenticated Background route.  The CAT3 grant plan is limited
            # to ordinary canonical Sphere/Talent acquisitions.
            grant_plan = catalog.validate_grant_plan_for_initial_creation(
                target_cl=final_plan["target_cl"],
                acquired_sphere_ids=sphere_ids,
                free_talent_grants=free_by_sphere,
                ordinary_talent_ids=ordinary_talent_ids,
                path_ids=resolution.get("actual_advancing_path_ids") or [],
                subpath_or_tradition_ids=stage2["subpath_or_tradition_ids"] or selected("subpath_choice"),
                method_ids=[resolution["method_id"]] if resolution.get("method_id") else [],
                foundation_or_feature_ids=[resolution["foundation_id"]] if resolution.get("foundation_id") else [],
            )
        except FoundryError:
            raise
        final_plan["canonical_grant_plan"] = grant_plan
        final_plan["canonical_grant_plan_sha256"] = sha256_json(grant_plan)
        final_plan["catalog_response_authority"] = {
            "target_cl": final_plan["target_cl"],
            "stage2_mechanical_choices": deepcopy(stage2),
            "accepted_sphere_ids": deepcopy(sphere_ids),
            "accepted_free_sphere_talent_ids": deepcopy(free_talent_ids),
            "accepted_ordinary_talent_ids": deepcopy(ordinary_talent_ids),
            "accepted_insight_ids": deepcopy(stage2["insight_ids"]),
            "accepted_insight_occurrences": deepcopy(stage2["insight_occurrences"]),
            "accepted_background_sphere_ids": deepcopy(stage2["background_sphere_ids"]),
            "accepted_background_talent_ids": deepcopy(stage2["background_talent_ids"]),
            "accepted_path_ids": deepcopy(resolution.get("actual_advancing_path_ids") or []),
            "accepted_method_id": resolution.get("method_id"),
            "accepted_foundation_id": resolution.get("foundation_id"),
            "grant_plan_provenance": deepcopy(grant_plan.get("selected_talent_dispositions") or []),
        }
        final_plan["response_representations"] = response_authority_representations(plan)
        canonical_intent = plan.get("canonical_selection_intent")
        if isinstance(canonical_intent, dict):
            final_plan["canonical_selection_intent"] = deepcopy(canonical_intent)
            final_plan["canonical_intent_hash"] = canonical_intent.get("intent_sha256")
            final_plan["submitted_plan_sha256"] = sha256_json(plan)
            final_plan["materialized_stage2_sha256"] = sha256_json(plan.get("stage2_proposal") or {})
            final_plan["materialization_receipt"] = deepcopy(plan.get("materialization_receipt") or {})
        final_plan["final_plan_sha256"] = final_plan_sha256(final_plan)
        return final_plan

    def _materialize_delegated_final_grant_plan(
        self,
        run: dict[str, Any],
        final_plan: dict[str, Any],
        authority_db: Database,
        *,
        phase: str,
    ) -> dict[str, Any] | None:
        if not self._has_delegated_envelope(run):
            return None
        from project_store.service import ProjectStore
        store = self.projects if authority_db is self.db else ProjectStore(authority_db)
        project_result = store.get_project(run["project_id"])
        project = deepcopy(project_result.get("project") or project_result)
        validate_accepted_final_plan_target(
            run,
            project,
            final_plan,
        )
        grant_plan = deepcopy(final_plan.get("canonical_grant_plan"))
        if not isinstance(grant_plan, dict) or grant_plan.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1":
            raise FoundryError(
                "CG1_CANONICAL_GRANT_PLAN_LOCK_MISSING",
                "Delegated compilation requires the server-derived canonical final grant plan.",
                status_code=409,
            )
        store.materialize_server_derived_user_lock(
            run["project_id"],
            field=DELEGATED_FINAL_CATALOG_GRANT_FIELD,
            value=grant_plan,
            # The lock is part of the reviewed mechanical snapshot.  Scratch
            # compilation and finalization must therefore persist identical
            # semantic bytes; the server phase is already bound by the caller's
            # sealed authority context and is not copied into the project lock.
            source=f"cg1-delegated-final-grant-plan:{sha256_json(grant_plan)}:server-derived",
            lock_id="lock.cg1.delegated-final-grant-plan",
        )
        return grant_plan

    def _compile_once(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        index: int,
        *,
        prior_attempt_id: str | None = None,
        accepted_final_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        compile_plan = self._plan_with_accepted_final_target(run, plan, accepted_final_plan)
        compile_plan = self._execution_descriptive_fields(run, compile_plan)
        choice_snapshot = self._require_frozen_choice_snapshot(run)
        with tempfile.TemporaryDirectory(prefix=f"cg1-scratch-{index}-", ignore_cleanup_errors=True) as td:
            root=Path(td); data=root/"data"
            self._snapshot_data(data)
            s=self.db.settings
            settings=Settings(root_dir=s.root_dir,data_dir=data,db_path=data/s.db_path.name,inbox_dir=data/"inbox",exports_dir=data/"exports",packs_dir=data/"content_packs",vendor_dir=data/"vendor",logs_dir=data/"logs",backups_dir=data/"backups",security_dir=data/"security",factory_zip=s.factory_zip,fixture_path=s.fixture_path)
            scratch_db=Database(settings); scratch_db.migrate(); services=self._scratch_services(scratch_db)
            self._materialize_descriptive_fields(run, compile_plan, scratch_db, phase="scratch_compile")
            self._materialize_delegated_final_grant_plan(
                run,
                accepted_final_plan or {},
                scratch_db,
                phase="scratch_compile",
            )
            stage1=services["stage1"]
            s1=compile_plan["stage1_response"]; text=s1 if isinstance(s1,str) else canonical_json(s1)
            attempt=stage1.validate_response(
                run["request"]["stage1_prompt"]["prompt_id"],
                text,
                prior_attempt_id=prior_attempt_id,
            )
            v=attempt.get("validation") or {}
            if v.get("valid") is False or v.get("errors") or v.get("blockers"):
                raise FoundryError("CG1_STAGE1_INVALID","Stage 1 validation rejected the plan.",details=v)
            stage1_commit=stage1.approve_and_commit(attempt.get("attempt_id"),self.owner_principal)
            method_access_receipt = self._materialize_method_hard_lock(run, scratch_db, phase="scratch_compile")
            stage2_validation,stage2_commit=self._stage2_commit(
                services["stage2"], deepcopy(compile_plan["stage2_proposal"]), self.owner_principal,
                creation_run=run, phase="scratch_compile",
            )
            self._issue_initial_catalog_provenance(
                run,
                frozen_snapshot=choice_snapshot,
                phase="scratch_compile",
                authority_db=scratch_db,
                _finalization_authority=_SERVER_SCRATCH_COMPILATION_AUTHORITY,
                accepted_final_plan=accepted_final_plan,
            )
            projection=services["projections"].build(run["project_id"], choice_snapshot=deepcopy(choice_snapshot))
            sheet=self._invoke(services["character_sheets"],("build","build_sheet","sheet","current"),run["project_id"])
            if services.get("production_release") is not None:
                release=services["production_release"].compile(
                    run["project_id"],
                    output_root=root/"release",
                    register=False,
                    output_profile=deepcopy(compile_plan.get("output_profile") or {}),
                )
                authoring=release["factory_authoring"]
                gm=release["command5"]
                gm_result=release["consumer"]
                portable={"package_sha256": release["portable_audit"].get("sha256"), "audit": release["portable_audit"], "clean_import": release["clean_import"], "release_identity": release["production_artifact_identity"]}
                stable_release=services["production_release"]._stable(release)
            else:
                authoring=self._invoke(services["factory_authoring"],("build",),run["project_id"])
                gm=self._invoke(services["gm_exports"],("export",),run["project_id"])
                gm_result=self._invoke(services["gm_consumer"],("verify","consume","import_package"),gm)
                portable=self._invoke(services["portable_characters"],("build_for_project","build_verified","export","verified_status"),run["project_id"])
            combat=None
            if bool((compile_plan.get("output_profile") or {}).get("combat_ready")):
                combat=self._invoke(services["combat_readiness"],("compile","build","verify"),run["project_id"])
            artifacts={"stage1":stage1_commit,"stage2_validation":stage2_validation,"stage2":stage2_commit,"method_access":method_access_receipt,"ledger":projection,"projection":projection,"character_sheet":sheet,"factory_authoring":authoring,"gm_model":gm,"gm_consumer":gm_result,"portable_character":portable,"combat":combat}
            identity_artifacts=artifacts
            if services.get("production_release") is not None:
                identity_artifacts={
                    **artifacts,
                    "factory_authoring":stable_release["factory_authoring"],
                    "gm_model":stable_release["command5"],
                    "gm_consumer":stable_release["consumer"],
                    "portable_character":{
                        "package_sha256":stable_release["portable_audit"].get("sha256"),
                        "audit":stable_release["portable_audit"],
                        "clean_import":stable_release["clean_import"],
                        "release_identity":release["production_artifact_identity"],
                    },
                }
            identities={k:sha256_json(self._identity_payload(v, _surface=k)) for k,v in identity_artifacts.items() if v is not None}
            preview={"identity":deepcopy(compile_plan.get("owner_descriptive_fields") or {}),"target_cl":compile_plan.get("target_cl"),"compiled":deepcopy(artifacts),"readiness":{k:{"service":k,"identity":identities.get(k),"verification_status":"VERIFIED","receipt":deepcopy(artifacts.get(k))} for k in REQUIRED_SURFACES},"uncertainties":deepcopy(compile_plan.get("uncertainties") or []),"fallbacks":deepcopy(compile_plan.get("fallbacks") or [])}
            if combat is not None: preview["readiness"]["combat"]={"service":"combat_readiness","identity":identities["combat"],"verification_status":"VERIFIED","receipt":deepcopy(combat)}
            candidate_identity=sha256_json({"plan_sha256":sha256_json(compile_plan),"typed_choice_snapshot_sha256":choice_snapshot["snapshot_sha256"],"identities":identities})
            return {"schema":"TianxiaFoundry.CompiledCharacterCandidate.v3","candidate_identity":candidate_identity,"typed_choice_snapshot":deepcopy(choice_snapshot),"identities":identities,"preview":preview,"artifacts":artifacts}

    def _compile_twice(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        *,
        prior_attempt_id: str | None = None,
        accepted_final_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous_clock=os.environ.get("TIANXIA_DETERMINISTIC_UTC")
        previous_approval_seed=os.environ.get("TIANXIA_DETERMINISTIC_APPROVAL_SEED")
        os.environ["TIANXIA_DETERMINISTIC_UTC"]=run["created_at"]
        os.environ["TIANXIA_DETERMINISTIC_APPROVAL_SEED"]=run["request"]["request_sha256"]
        try:
            compile_kwargs = {"prior_attempt_id": prior_attempt_id}
            if accepted_final_plan is not None:
                compile_kwargs["accepted_final_plan"] = accepted_final_plan
            rebound_plan = self._plan_with_accepted_final_target(
                run,
                plan,
                accepted_final_plan,
            )
            first_plan = deepcopy(rebound_plan)
            second_plan = deepcopy(rebound_plan)
            rebound_plan_sha256 = sha256_json(rebound_plan)
            first_plan_sha256 = sha256_json(first_plan)
            second_plan_sha256 = sha256_json(second_plan)
            if first_plan_sha256 != rebound_plan_sha256 or second_plan_sha256 != rebound_plan_sha256:
                raise FoundryError(
                    "CG1_NONDETERMINISTIC_COMPILATION",
                    "The central scratch-compilation plan rebind was not canonical.",
                    details={
                        "rebound_plan_sha256": rebound_plan_sha256,
                        "first_plan_sha256": first_plan_sha256,
                        "second_plan_sha256": second_plan_sha256,
                    },
                )
            a=self._compile_once(run, first_plan, 1, **compile_kwargs)
            b=self._compile_once(run, second_plan, 2, **compile_kwargs)
        finally:
            if previous_clock is None:
                os.environ.pop("TIANXIA_DETERMINISTIC_UTC",None)
            else:
                os.environ["TIANXIA_DETERMINISTIC_UTC"]=previous_clock
            if previous_approval_seed is None:
                os.environ.pop("TIANXIA_DETERMINISTIC_APPROVAL_SEED",None)
            else:
                os.environ["TIANXIA_DETERMINISTIC_APPROVAL_SEED"]=previous_approval_seed
        if a["candidate_identity"] != b["candidate_identity"] or a["identities"] != b["identities"]:
            first_identity_payload = {
                key: self._identity_payload(value, _surface=key)
                for key, value in (a.get("artifacts") or {}).items()
                if value is not None
            }
            second_identity_payload = {
                key: self._identity_payload(value, _surface=key)
                for key, value in (b.get("artifacts") or {}).items()
                if value is not None
            }
            raise FoundryError(
                "CG1_NONDETERMINISTIC_COMPILATION",
                "The two isolated Factory compilations produced different identities.",
                details={
                    "first": a["identities"],
                    "second": b["identities"],
                    "differences": self._identity_differences(first_identity_payload, second_identity_payload),
                },
            )
        return {**a,"schema":DRY_RUN_SCHEMA,"deterministic":True,"independent_compilations":2}

    def _validate_frozen_catalog_choices(self, run: dict[str, Any], plan: dict[str, Any]) -> None:
        """Require a normal-wizard proposal to equal its exact committed choices.

        Historical explicit grant locks retain their established semantics.  A
        priority-only compatibility projection, however, cannot authorize new
        canonical acquisitions.  New normal-wizard chains use the distinct
        server-validated choice lock and must match it exactly.
        """
        project = self._project(run["project_id"])
        locks = {
            lock.get("field"): lock.get("value")
            for lock in project.get("user_locks", [])
            if isinstance(lock, dict)
        }
        committed = locks.get(COMMITTED_CATALOG_CHOICE_FIELD)
        proposal_choices = (plan.get("stage2_proposal") or {}).get("choices") or []
        sphere_kinds = {"sect_trial_sphere_acquisition", "ai_bootstrap_sphere_acquisition"}
        free_kinds = {"sect_trial_talent_acquisition", "ai_bootstrap_talent_acquisition"}
        proposal_spheres = [
            row.get("record_id") for row in proposal_choices
            if isinstance(row, dict) and row.get("kind") in sphere_kinds
        ]
        proposal_free = [
            row.get("record_id") for row in proposal_choices
            if isinstance(row, dict) and row.get("kind") in free_kinds
        ]
        proposal_free_by_sphere = {
            row.get("record_id"): proposal_choices[index + 1].get("record_id")
            for index, row in enumerate(proposal_choices[:-1])
            if isinstance(row, dict)
            and row.get("kind") in sphere_kinds
            and isinstance(proposal_choices[index + 1], dict)
            and proposal_choices[index + 1].get("kind") in free_kinds
        }
        proposal_ordinary = [
            row.get("record_id") for row in proposal_choices
            if isinstance(row, dict) and row.get("kind") == "level_talent_acquisition"
        ]
        if not isinstance(committed, dict):
            legacy = committed_catalog_grant_plan(project)
            legacy_selected = bool(
                (legacy or {}).get("acquired_canonical_sphere_ids")
                or (legacy or {}).get("grant_accounting", {}).get("ordinary_talent_ids")
                or (legacy or {}).get("grant_accounting", {}).get("free_sphere_talent_grants")
            )
            if (proposal_spheres or proposal_free or proposal_ordinary) and not legacy_selected and not (run.get("request") or {}).get("delegated_choice_envelope"):
                raise FoundryError(
                    "CG1_COMMITTED_CATALOG_CHOICE_PLAN_REQUIRED",
                    "Normal-wizard canonical acquisitions must be server-validated and frozen before scratch compilation.",
                    status_code=409,
                )
            return
        if committed.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1" or committed.get("ready") is not True:
            raise FoundryError(
                "CG1_COMMITTED_CATALOG_CHOICE_PLAN_INVALID",
                "The frozen canonical catalog choice lock is invalid.",
                status_code=409,
            )
        expected_spheres = list(committed.get("acquired_canonical_sphere_ids") or [])
        accounting = committed.get("grant_accounting") or {}
        expected_free_by_sphere = {
            row.get("sphere_id"): row.get("talent_id")
            for row in accounting.get("free_sphere_talent_grants") or []
        }
        expected_free = list(expected_free_by_sphere.values())
        expected_ordinary = list(accounting.get("ordinary_talent_ids") or [])
        mismatches = {
            "target_cl": {
                "expected": committed.get("target_cl"),
                "actual": plan.get("target_cl"),
            },
            "acquired_sphere_ids": {"expected": sorted(expected_spheres), "actual": sorted(proposal_spheres)},
            "free_talent_ids": {"expected": sorted(expected_free), "actual": sorted(proposal_free)},
            "free_talent_grants": {"expected": expected_free_by_sphere, "actual": proposal_free_by_sphere},
            "ordinary_talent_ids": {"expected": sorted(expected_ordinary), "actual": sorted(proposal_ordinary)},
        }
        failed = {
            key: value for key, value in mismatches.items()
            if value["expected"] != value["actual"]
        }
        duplicate = any(
            len(values) != len(set(values))
            for values in (proposal_spheres, proposal_free, proposal_ordinary)
        )
        if failed or duplicate:
            raise FoundryError(
                "CG1_FROZEN_CATALOG_CHOICE_MISMATCH",
                "The provider proposal does not exactly match the revision-bound canonical catalog choices.",
                details={"mismatches": failed, "duplicate_catalog_choice": duplicate},
                status_code=409,
            )

    def _validate_and_compile(
        self,
        run: dict[str, Any],
        response_text: str,
        *,
        submitted_request_sha256: str | None = None,
        prior_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        plan,raw=self._parse_plan(response_text)
        self._validate_complete_response_binding(
            run,
            plan,
            submitted_request_sha256=submitted_request_sha256,
        )
        self._validate_preferred_bounded_fields(run, plan)
        project = self._project(run["project_id"])
        delegated_run = self._has_delegated_envelope(run)
        if plan.get("schema") in {PLAN_SCHEMA, LEGACY_PLAN_SCHEMA}:
            legacy_required = [
                "stage1_response",
                "target_cl",
                "stage2_proposal",
                "owner_descriptive_fields",
                "uncertainties",
                "fallbacks",
                "output_profile",
            ]
            legacy_missing = [field for field in legacy_required if field not in plan]
            if legacy_missing:
                raise FoundryError(
                    "CG1_PLAN_BLOCKED",
                    "The complete character plan is missing required components.",
                    details={
                        "blockers": [
                            {
                                "code": "CG1_PLAN_COMPONENT_MISSING",
                                "field": field,
                                "message": f"The complete plan is missing {field}.",
                            }
                            for field in legacy_missing
                        ]
                    },
                    status_code=409,
                )
        canonical_intent: CanonicalSelectionIntent | None = None
        if delegated_run:
            # Check compatibility copies before the server injects its frozen
            # value.  Otherwise a contradictory historical top-level target
            # could be silently replaced during normalization.
            validate_delegated_target_cl(run, project, plan)
            plan, canonical_intent, _materialized_stage2 = self._normalize_and_materialize_response(run, plan)
            if canonical_intent is not None:
                run["canonical_selection_intent"] = canonical_intent.as_dict()
        if delegated_run:
            # This is deliberately before generic component validation and
            # before final-plan derivation so omitted, stringified, or changed
            # target values all receive the one actionable authority error.
            validate_delegated_target_cl(run, project, plan)
        blockers=[]; warnings=[]
        required_fields = (
            ("stage1_response", "owner_descriptive_fields", "uncertainties", "fallbacks", "output_profile")
            if delegated_run and canonical_intent is not None
            else ("stage1_response", "target_cl", "stage2_proposal", "owner_descriptive_fields", "uncertainties", "fallbacks", "output_profile")
        )
        for k in required_fields:
            if k not in plan: blockers.append({"code":"CG1_PLAN_COMPONENT_MISSING","field":k,"message":f"The complete plan is missing {k}."})
        target_value = plan.get("target_cl")
        if delegated_run and canonical_intent is not None:
            target_value = canonical_intent.as_dict().get("target_cl")
        if not isinstance(target_value,int) or not 1<=int(target_value or 0)<=20:
            blockers.append({"code":"CG1_TARGET_CL_INVALID","message":"Target CL must be 1 through 20."})
        if delegated_run and canonical_intent is not None and not (
            isinstance(plan.get("stage2_proposal"), dict)
            and isinstance(plan.get("stage2_proposal", {}).get("choices"), list)
            and plan.get("stage2_proposal", {}).get("choices")
        ):
            blockers.append({
                "code": "CG1_BOUNDED_DECISION_REQUIRED",
                "message": "The response supplied planning preferences but no explicit acquisition intent. Choose the exact proposed acquisitions or leave the owner decision unresolved.",
                "details": {"field": "acquisition_intent", "planning_only_slots": sorted(canonical_intent.as_dict().get("planning_preferences_by_slot") or {})},
            })
        blockers.extend(self._collaborator_blockers(bool((plan.get("output_profile") or {}).get("combat_ready"))))
        if blockers: raise FoundryError("CG1_PLAN_BLOCKED","The plan cannot enter local compilation.",details={"blockers":blockers})
        final_plan = validate_delegated_choice_plan(
            run,
            project,
            plan,
            response_sha256=sha256_bytes(raw),
        )
        if final_plan is None:
            # Old integrations may provide a minimal Stage1 test double rather
            # than the production envelope.  Preserve their established
            # behavior while still giving every accepted run an immutable
            # server-owned final-plan record.
            final_plan = {
                "schema": "TianxiaFoundry.CharacterCreationFinalPlan.v1",
                "project_id": run["project_id"],
                "project_revision": run["starting_revision"],
                "content_lock_hash": run["request"].get("content_lock_hash"),
                "request_sha256": run["request"].get("request_sha256"),
                "response_sha256": sha256_bytes(raw),
                "idempotency_key": run.get("idempotency_key"),
                "resolution": {"schema": "TianxiaFoundry.LegacyPlanResolution.v1", "authority": "existing-local-validator"},
                "plan_sha256": sha256_json(plan),
                "immutable_after_validation": True,
            }
            final_plan["final_plan_sha256"] = final_plan_sha256(final_plan)
        if delegated_run:
            final_plan = self._derive_delegated_final_grant_plan(run, plan, final_plan)
        else:
            self._validate_frozen_catalog_choices(run, plan)
        candidate=self._compile_twice(
            run,
            plan,
            prior_attempt_id=prior_attempt_id,
            accepted_final_plan=final_plan if delegated_run else None,
        )
        warnings.extend(deepcopy(plan.get("uncertainties") or [])); warnings.extend(deepcopy(plan.get("fallbacks") or []))
        quality={"schema":QUALITY_SCHEMA,"status":"CLEAN" if not warnings else "NEEDS_REVIEW","required_receipts":sorted(candidate["preview"]["readiness"]),"candidate_identity":candidate["candidate_identity"]}
        validation={"valid":True,"response_sha256":sha256_bytes(raw),"plan_sha256":sha256_json(plan),"planner_authority_fields_used":False,"delegated_choice_authority":delegated_run,"owner_descriptive_fields":deepcopy(plan.get("owner_descriptive_fields") or {})}
        if canonical_intent is not None:
            validation["canonical_intent_hash"] = canonical_intent.intent_hash
            validation["materialization_receipt"] = deepcopy(plan.get("materialization_receipt") or {})
            validation["materialized_stage2_hash"] = sha256_json(plan.get("stage2_proposal") or {})
        return {"plan":plan,"final_plan":final_plan or {},"validation":validation,"candidate":candidate,"quality":quality,"warnings":warnings,"raw_sha256":sha256_bytes(raw),"canonical_intent":canonical_intent.as_dict() if canonical_intent is not None else None}

    def _apply_response(
        self,
        run_id: str,
        response_text: str,
        transport: dict[str, Any],
        *,
        submitted_request_sha256: str | None = None,
        prior_attempt_id: str | None = None,
        binding_error_status: bool = False,
        action_type: str = "IMPORT_RESPONSE",
    ) -> dict[str, Any]:
        run = self.get(run_id)
        history_prior_attempt_id = prior_attempt_id or self._latest_attempt_id(run_id)
        transport = deepcopy(transport)
        if prior_attempt_id is not None:
            transport["prior_attempt_id"] = prior_attempt_id
        incoming_response_sha256 = sha256_bytes(response_text.encode("utf-8"))
        existing_final_plan = run.get("final_plan") or {}
        if existing_final_plan:
            if incoming_response_sha256 != existing_final_plan.get("response_sha256"):
                raise FoundryError(
                    "CG1_FINAL_PLAN_IMMUTABLE",
                    "The accepted server final plan is immutable and cannot be replaced by a different response.",
                    status_code=409,
                )
        try:
            # Compilation installs server-derived descriptive locks in the
            # isolated scratch database.  Bind that scratch lock to the exact
            # response bytes being compiled, even though the durable response
            # row is written only after compilation succeeds.  Finalization
            # reads the persisted response hash; using an empty scratch hash
            # would produce a different project input hash and therefore
            # different projection/provenance artifacts.
            compile_run = dict(run)
            compile_run["response"] = {
                **(run.get("response") or {}),
                "response_sha256": incoming_response_sha256,
            }
            compiled = self._validate_and_compile(
                compile_run,
                response_text,
                submitted_request_sha256=submitted_request_sha256,
                prior_attempt_id=prior_attempt_id,
            )
            status = "READY_FOR_REVIEW" if compiled["quality"]["status"] == "CLEAN" else "NEEDS_REVIEW"
            response = {
                "exact_response_text": response_text,
                "response_sha256": compiled["raw_sha256"],
                "parsed_plan": compiled["plan"],
            }
            with self.db.transaction() as conn:
                existing_row = conn.execute("SELECT final_plan_json FROM character_creation_runs WHERE run_id=?", (run_id,)).fetchone()
                existing_final_plan = json.loads(existing_row["final_plan_json"] or "{}") if existing_row else {}
                if existing_final_plan and existing_final_plan != compiled["final_plan"]:
                    raise FoundryError(
                        "CG1_FINAL_PLAN_IMMUTABLE",
                        "The accepted server final plan is immutable and cannot be replaced by a different response.",
                        status_code=409,
                    )
                conn.execute(
                    """UPDATE character_creation_runs SET transport_json=?,response_json=?,validation_json=?,dry_run_json=?,final_plan_json=?,owner_descriptive_fields_json=?,quality_json=?,blockers_json='[]',warnings_json=?,status=?,updated_at=? WHERE run_id=?""",
                    (
                        canonical_json(transport), canonical_json(response), canonical_json(compiled["validation"]),
                        canonical_json(compiled["candidate"]), canonical_json(compiled["final_plan"]), canonical_json(compiled["plan"].get("owner_descriptive_fields") or {}), canonical_json(compiled["quality"]),
                        canonical_json(compiled["warnings"]), status, utcnow(), run_id,
                    ),
                )
        except FoundryError as exc:
            descriptive = self._descriptive_from_response_text(response_text)
            diagnostic = {"code": exc.code, "message": exc.message, "details": exc.details}
            if exc.code == RESPONSE_BINDING_ERROR and binding_error_status:
                validation = deepcopy(run.get("validation") or {})
                validation["last_submission_error"] = diagnostic
                validation["owner_descriptive_fields"] = descriptive
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE character_creation_runs SET transport_json=?,response_json=?,validation_json=?,owner_descriptive_fields_json=?,updated_at=? WHERE run_id=?",
                        (
                            canonical_json(transport),
                            canonical_json({"exact_response_text": response_text, "response_sha256": sha256_bytes(response_text.encode("utf-8"))}),
                            canonical_json(validation), canonical_json(descriptive), utcnow(), run_id,
                        ),
                    )
                self._append_attempt(
                    run,
                    action_type=action_type,
                    status="BLOCKED",
                    response_text=response_text,
                    prior_attempt_id=history_prior_attempt_id,
                    binding={
                        "submitted_request_sha256": submitted_request_sha256,
                        "active_request_sha256": run["request"].get("request_sha256"),
                        "transport": transport,
                    },
                    error=diagnostic,
                )
                raise
            blocker = diagnostic
            validation = deepcopy(run.get("validation") or {})
            validation.pop("last_submission_error", None)
            validation["owner_descriptive_fields"] = descriptive
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE character_creation_runs SET transport_json=?,response_json=?,validation_json=?,owner_descriptive_fields_json=?,blockers_json=?,status='NEEDS_REVIEW',updated_at=? WHERE run_id=?",
                    (
                        canonical_json(transport),
                        canonical_json({
                            "exact_response_text": response_text,
                            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
                        }),
                        canonical_json(validation), canonical_json(descriptive), canonical_json([blocker]), utcnow(), run_id,
                    ),
                )
            self._append_attempt(
                run,
                action_type=action_type,
                status="BLOCKED",
                response_text=response_text,
                prior_attempt_id=history_prior_attempt_id,
                binding={
                    "submitted_request_sha256": submitted_request_sha256,
                    "active_request_sha256": run["request"].get("request_sha256"),
                    "transport": transport,
                },
                blockers=[blocker],
                error=diagnostic,
            )
            return self.get(run_id)
        self._append_attempt(
            run,
            action_type=action_type,
            status=status,
            response_text=response_text,
            canonical_intent=compiled.get("canonical_intent"),
            materialization_receipt=compiled["validation"].get("materialization_receipt"),
            validation=compiled.get("validation"),
            quality=compiled.get("quality"),
            candidate_identity=(compiled.get("candidate") or {}).get("candidate_identity"),
            materialized_plan_sha256=compiled["validation"].get("materialized_stage2_hash"),
            submitted_plan_sha256=compiled["validation"].get("plan_sha256"),
            prior_attempt_id=history_prior_attempt_id,
            binding={
                "submitted_request_sha256": submitted_request_sha256,
                "active_request_sha256": run["request"].get("request_sha256"),
                "transport": transport,
            },
        )
        result = self.get(run_id)
        if result["execution_mode"] == "AUTO_FINALIZE_WHEN_CLEAN" and result["quality"].get("status") == "CLEAN":
            receipt = self._valid_auto_finalize_opt_in(result)
            if receipt:
                return self.finalize(run_id, auto_finalize_receipt=receipt)
        return result

    def accept_descriptive_fields(self, run_id: str, *, name: str | None, concept: str | None) -> dict[str, Any]:
        run = self.get(run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise FoundryError("CG1_DESCRIPTIVE_FIELDS_TERMINAL", "A finalized, cancelled, or revised run cannot accept new descriptive fields.", status_code=409)
        proposed = run.get("owner_descriptive_fields", {}).get("proposed") or {}
        fields = self._descriptive_fields({"identity": {"name": name}, "concept": concept})
        delegated = (run.get("request") or {}).get("delegated_choice_envelope") or {}
        delegated_fields = delegated.get("delegated_fields") or {}
        for field, value in (("identity.name", fields["identity"]["name"]), ("concept", fields["concept"])):
            authority = delegated_fields.get(field) or {}
            if authority.get("state") == "owner_locked":
                expected = str(authority.get("owner_value") or "").strip() or None
                if value != expected:
                    raise FoundryError(
                        "CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED",
                        "This descriptive field is owner-locked and cannot be changed during review.",
                        details={"field": field, "expected": expected, "proposed": value},
                        status_code=409,
                    )
        if not (fields["identity"]["name"] or fields["concept"]):
            fields = self._descriptive_fields(proposed)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET accepted_descriptive_fields_json=?,owner_decision='ACCEPT_DESCRIPTIVE_FIELDS',updated_at=? WHERE run_id=?",
                (canonical_json(fields), utcnow(), run_id),
            )
        return self.get(run_id)

    @staticmethod
    def _execution_descriptive_fields(run: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        projection = run.get("owner_descriptive_fields") or {}
        accepted = projection.get("accepted") if isinstance(projection, dict) else None
        accepted_is_substantive = isinstance(accepted, dict) and (
            (accepted.get("identity") or {}).get("name") or accepted.get("concept")
        )
        proposed_or_resolved = projection.get("resolved") if isinstance(projection, dict) else None
        resolved_is_substantive = isinstance(proposed_or_resolved, dict) and (
            (proposed_or_resolved.get("identity") or {}).get("name") or proposed_or_resolved.get("concept")
        )
        resolved = accepted if accepted_is_substantive else proposed_or_resolved if resolved_is_substantive else None
        if not isinstance(resolved, dict):
            return deepcopy(plan)
        result = deepcopy(plan)
        result["owner_descriptive_fields"] = CharacterCreationExecutionService._descriptive_fields(resolved)
        return result

    def _materialize_descriptive_fields(self, run: dict[str, Any], plan: dict[str, Any], authority_db: Database, *, phase: str) -> None:
        fields = self._descriptive_fields(plan.get("owner_descriptive_fields") or {})
        from project_store.service import ProjectStore
        store = self.projects if authority_db is self.db else ProjectStore(authority_db)
        binding = {
            "schema": "TianxiaFoundry.ServerDerivedDescriptiveFields.v1",
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "request_sha256": run["request"].get("request_sha256"),
            "response_sha256": run.get("response", {}).get("response_sha256"),
            "phase": "server-derived",
        }
        for field, value in (
            ("character.identity.final_display_name", fields["identity"].get("name")),
            ("character.identity.final_concept", fields.get("concept")),
        ):
            if not value:
                continue
            materialize = getattr(store, "materialize_server_derived_user_lock", None)
            if not callable(materialize):
                # Focused legacy test doubles intentionally model only the
                # project read/write surface.  They still exercise the
                # candidate/finalization path; production ProjectStore owns
                # the durable server-derived descriptive locks.
                continue
            materialize(
                run["project_id"],
                field=field,
                value={"value": value, "binding": binding},
                source=f"cg1-owner-descriptive:{run['run_id']}:server-derived",
                lock_id=f"lock.cg1.{field.replace('.', '-')}",
            )

    def submit_manual(
        self,
        run_id: str,
        *,
        response_text: str,
        request_sha256: str,
        prior_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        run = self.get(run_id)
        if run["execution_mode"] != "MANUAL_CHAT":
            raise FoundryError(
                "CG1_MANUAL_RESPONSE_MODE_MISMATCH",
                "This run is not waiting for a Manual Chat response.",
            )
        return self._apply_response(
            run_id,
            response_text,
            {
                "mode": "MANUAL_CHAT",
                "provider_called": False,
                "transfer": "pasted_response",
                "submitted_request_sha256": request_sha256,
            },
            submitted_request_sha256=request_sha256,
            prior_attempt_id=prior_attempt_id,
            binding_error_status=True,
            action_type="IMPORT_RESPONSE",
        )

    def replace_response(
        self,
        run_id: str,
        *,
        response_text: str,
        request_sha256: str,
    ) -> dict[str, Any]:
        """Replace the response while retaining the prior attempt as history."""
        run = self.get(run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise FoundryError(
                "CG1_REPLACE_RESPONSE_TERMINAL",
                "Replace Response is unavailable after a run is finalized, cancelled, or superseded.",
                status_code=409,
            )
        if run.get("execution_mode") != "MANUAL_CHAT":
            raise FoundryError(
                "CG1_REPLACE_RESPONSE_MODE_MISMATCH",
                "Replace Response is available only for a Manual Chat response run.",
                status_code=409,
            )
        prior_attempt_id = self._latest_attempt_id(run_id)
        # The prior accepted candidate remains immutable in the append-only
        # history.  This run row is only the latest-run projection and may be
        # cleared before the replacement is compiled.
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE character_creation_runs SET
                   transport_json='{}',response_json='{}',validation_json='{}',dry_run_json='{}',
                   final_plan_json='{}',owner_descriptive_fields_json='{}',accepted_descriptive_fields_json='{}',
                   quality_json='{}',owner_decision='REPLACE_RESPONSE',commit_json='{}',final_revision=NULL,
                   output_json='{}',blockers_json='[]',warnings_json='[]',status='WAITING_FOR_RESPONSE',completed_at=NULL,updated_at=?
                   WHERE run_id=?""",
                (utcnow(), run_id),
            )
        return self._apply_response(
            run_id,
            response_text,
            {
                "mode": "MANUAL_CHAT",
                "provider_called": False,
                "transfer": "replaced_response",
                "submitted_request_sha256": request_sha256,
                "prior_attempt_id": prior_attempt_id,
            },
            submitted_request_sha256=request_sha256,
            prior_attempt_id=prior_attempt_id,
            binding_error_status=True,
            action_type="REPLACE_RESPONSE",
        )

    def replace_response_file(self, run_id: str, *, filename: str, payload: bytes) -> dict[str, Any]:
        """Replace a Manual Chat response from one bounded local file."""
        run = self.get(run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise FoundryError(
                "CG1_REPLACE_RESPONSE_TERMINAL",
                "Replace Response is unavailable after a run is finalized, cancelled, or superseded.",
                status_code=409,
            )
        if run.get("execution_mode") != "MANUAL_CHAT":
            raise FoundryError(
                "CG1_REPLACE_RESPONSE_MODE_MISMATCH",
                "Replace Response is available only for a Manual Chat response run.",
                status_code=409,
            )
        response_text, upload = self._manual_response_text(filename, payload)
        prior_attempt_id = self._latest_attempt_id(run_id)
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE character_creation_runs SET
                   transport_json='{}',response_json='{}',validation_json='{}',dry_run_json='{}',
                   final_plan_json='{}',owner_descriptive_fields_json='{}',accepted_descriptive_fields_json='{}',
                   quality_json='{}',owner_decision='REPLACE_RESPONSE',commit_json='{}',final_revision=NULL,
                   output_json='{}',blockers_json='[]',warnings_json='[]',status='WAITING_FOR_RESPONSE',completed_at=NULL,updated_at=?
                   WHERE run_id=?""",
                (utcnow(), run_id),
            )
        return self._apply_response(
            run_id,
            response_text,
            {
                "mode": "MANUAL_CHAT",
                "provider_called": False,
                "transfer": "replaced_response_file",
                "submitted_request_sha256": run["request"].get("request_sha256"),
                "prior_attempt_id": prior_attempt_id,
                **upload,
            },
            submitted_request_sha256=run["request"].get("request_sha256"),
            prior_attempt_id=prior_attempt_id,
            binding_error_status=True,
            action_type="REPLACE_RESPONSE",
        )

    def retry_local_build(self, run_id: str) -> dict[str, Any]:
        """Recompile the exact persisted response without external I/O."""
        run = self.get(run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise FoundryError(
                "CG1_RETRY_LOCAL_BUILD_TERMINAL",
                "Retry Local Build is unavailable after a terminal run state.",
                status_code=409,
            )
        response_text = (run.get("response") or {}).get("exact_response_text")
        request_sha256 = (run.get("request") or {}).get("request_sha256")
        submitted = (run.get("transport") or {}).get("submitted_request_sha256")
        if not isinstance(response_text, str) or not response_text:
            raise FoundryError(
                "CG1_RETRY_LOCAL_BUILD_RESPONSE_MISSING",
                "Retry Local Build requires the exact persisted response; import or replace a response first.",
                status_code=409,
            )
        if submitted not in {None, request_sha256}:
            raise FoundryError(
                RESPONSE_BINDING_ERROR,
                RESPONSE_BINDING_MESSAGE,
                details={"submitted_request_sha256": submitted, "active_request_sha256": request_sha256},
                status_code=409,
            )
        prior_attempt_id = self._latest_attempt_id(run_id)
        return self._apply_response(
            run_id,
            response_text,
            {
                "mode": run.get("execution_mode"),
                "provider_called": False,
                "transfer": "retry_local_build",
                "submitted_request_sha256": request_sha256,
                "prior_attempt_id": prior_attempt_id,
            },
            submitted_request_sha256=request_sha256,
            prior_attempt_id=prior_attempt_id,
            binding_error_status=False,
            action_type="RETRY_LOCAL_BUILD",
        )

    @staticmethod
    def _manual_response_text(filename: str, payload: bytes) -> tuple[str, dict[str, Any]]:
        name = Path(str(filename or "")).name
        if name != str(filename or "") or not name:
            raise FoundryError("CG1_MANUAL_RESPONSE_FILENAME_INVALID", "Choose one local response ZIP or JSON file.")
        if len(payload) > 16_000_000:
            raise FoundryError("CG1_MANUAL_RESPONSE_TOO_LARGE", "The complete response file is larger than the 16 MB transfer limit.")
        suffix = Path(name).suffix.casefold()
        response_name = name
        response_payload = payload
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    files = []
                    for info in archive.infolist():
                        path = Path(info.filename)
                        if info.is_dir():
                            continue
                        if info.flag_bits & 0x1:
                            raise FoundryError("CG1_MANUAL_RESPONSE_ZIP_ENCRYPTED", "Encrypted response ZIPs are not accepted.")
                        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
                            raise FoundryError("CG1_MANUAL_RESPONSE_ZIP_PATH_INVALID", "The response ZIP must contain one safe top-level response file.")
                        if path.suffix.casefold() not in {".json", ".txt", ".md"}:
                            continue
                        files.append(info)
                    if len(files) != 1:
                        raise FoundryError("CG1_MANUAL_RESPONSE_ZIP_CONTENT_INVALID", "The response ZIP must contain exactly one JSON, text, or Markdown response file.", details={"eligible_files": [row.filename for row in files]})
                    info = files[0]
                    if info.file_size > 2_000_000:
                        raise FoundryError("CG1_MANUAL_RESPONSE_TOO_LARGE", "The complete response inside the ZIP exceeds 2 MB.")
                    response_name = info.filename
                    response_payload = archive.read(info)
            except zipfile.BadZipFile as exc:
                raise FoundryError("CG1_MANUAL_RESPONSE_ZIP_INVALID", "The selected response ZIP is not a valid ZIP archive.") from exc
        elif suffix not in {".json", ".txt", ".md"}:
            raise FoundryError("CG1_MANUAL_RESPONSE_TYPE_INVALID", "Choose a .zip, .json, .txt, or .md complete response file.")
        if len(response_payload) > 2_000_000:
            raise FoundryError("CG1_MANUAL_RESPONSE_TOO_LARGE", "The complete response exceeds 2 MB.")
        try:
            text = response_payload.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise FoundryError("CG1_MANUAL_RESPONSE_ENCODING_INVALID", "The complete response must be UTF-8 text.") from exc
        if not text:
            raise FoundryError("CG1_MANUAL_RESPONSE_EMPTY", "The selected complete response file is empty.")
        return text, {"uploaded_filename": name, "response_member": response_name, "uploaded_sha256": sha256_bytes(payload)}

    def submit_manual_file(self, run_id: str, *, filename: str, payload: bytes) -> dict[str, Any]:
        run = self.get(run_id)
        if run["execution_mode"] != "MANUAL_CHAT":
            raise FoundryError("CG1_MANUAL_RESPONSE_MODE_MISMATCH", "This run is not waiting for a Manual Chat response.")
        response_text, upload = self._manual_response_text(filename, payload)
        return self._apply_response(
            run_id,
            response_text,
            {
                "mode": "MANUAL_CHAT",
                "provider_called": False,
                "transfer": "response_file",
                "submitted_request_sha256": run["request"].get("request_sha256"),
                **upload,
            },
            binding_error_status=True,
            action_type="IMPORT_RESPONSE",
        )

    def create_auto_finalize_opt_in(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        if run["execution_mode"] != "AUTO_FINALIZE_WHEN_CLEAN":
            raise FoundryError("CG1_AUTO_FINALIZE_MODE_REQUIRED","Explicit Auto-Finalize consent is only valid for an Auto-Finalize When Clean run.",status_code=409)
        if run["status"] not in {"READY_FOR_REVIEW", "NEEDS_REVIEW"} or run["quality"].get("status") != "CLEAN":
            raise FoundryError("CG1_AUTO_FINALIZE_OPT_IN_NOT_CLEAN","Auto-Finalize can only be enabled for a clean reviewed candidate.",status_code=409)
        plan = run["response"].get("parsed_plan") or {}
        payload = {
            "schema": "TianxiaFoundry.CharacterCreationAutoFinalizeOptIn.v1",
            "owner_principal_id": self.owner_principal,
            "owner_principal_hash": self.owner_principal_hash,
            "project_id": run["project_id"],
            "project_revision": run["starting_revision"],
            "content_lock_hash": run["request"]["content_lock_hash"],
            "request_sha256": run["request"]["request_sha256"],
            "candidate_identity": run["dry_run"]["candidate_identity"],
            "output_profile_sha256": sha256_json(plan.get("output_profile") or {}),
        }
        payload["receipt_sha256"] = sha256_json(payload)
        payload["receipt_id"] = "cg1.optin." + payload["receipt_sha256"][:24]
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO character_creation_auto_finalize_opt_ins("
                "receipt_id,project_id,owner_principal_id,owner_principal_hash,project_revision,"
                "content_lock_hash,request_sha256,candidate_identity,output_profile_sha256,"
                "receipt_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (payload["receipt_id"], payload["project_id"], payload["owner_principal_id"],
                 payload["owner_principal_hash"], payload["project_revision"], payload["content_lock_hash"],
                 payload["request_sha256"], payload["candidate_identity"], payload["output_profile_sha256"],
                 payload["receipt_sha256"], utcnow()),
            )
        finalized = self.finalize(run_id, auto_finalize_receipt=payload)
        finalized["auto_finalize_opt_in"] = payload
        return finalized

    def _valid_auto_finalize_opt_in(self, run: dict[str, Any]) -> dict[str, Any] | None:
        plan = run["response"].get("parsed_plan") or {}
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM character_creation_auto_finalize_opt_ins WHERE "
                "project_id=? AND owner_principal_hash=? AND project_revision=? AND content_lock_hash=? "
                "AND request_sha256=? AND candidate_identity=? AND output_profile_sha256=? AND revoked_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (run["project_id"], self.owner_principal_hash, run["starting_revision"],
                 run["request"]["content_lock_hash"], run["request"]["request_sha256"],
                 run["dry_run"]["candidate_identity"], sha256_json(plan.get("output_profile") or {})),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _provider_prompt(run: dict[str, Any]) -> str:
        payload = {
            "schema": "TianxiaFoundry.CharacterCreationProviderPrompt.v1",
            "purpose": "character_creation_complete_plan",
            "complete_request": deepcopy(run["request"]),
            "response_contract": {
                "schema": DELEGATED_RESPONSE_SCHEMA,
                "historical_compatibility": [PLAN_SCHEMA, LEGACY_PLAN_SCHEMA],
                "required_components": list(run["request"].get("required_components") or []),
                "required_request_sha256": run["request"]["request_sha256"],
                "forbidden_planner_fields": list(run["request"].get("forbidden_planner_fields") or []),
                "return_exactly_one_json_object": True,
            },
            "authority": {
                "provider_mechanical_authority": False,
                "provider_direct_commit_allowed": False,
                "automatic_retries": 0,
                "local_two_isolated_compilations_required": True,
            },
        }
        return canonical_json(payload)

    def _provider_fallback(self, run: dict[str, Any], exc: FoundryError) -> dict[str, Any]:
        warning = {
            "code": "CG1_PROVIDER_EXECUTION_FAILED_FALLBACK_MANUAL",
            "message": "The configured provider call did not complete; the run returned to Manual Chat without changing the character.",
            "provider_error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }
        transport = {
            "mode": run["execution_mode"],
            "provider_called": True,
            "fallback_mode": "MANUAL_CHAT",
            "complete_request_sha256": run["request"]["request_sha256"],
            "provider_error": warning["provider_error"],
        }
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET execution_mode='MANUAL_CHAT',transport_json=?,warnings_json=?,status='WAITING_FOR_RESPONSE',updated_at=? WHERE run_id=?",
                (canonical_json(transport), canonical_json([warning]), utcnow(), run["run_id"]),
            )
        return self.get(run["run_id"])

    def _run_provider(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        try:
            receipt = self.provider.complete_json(
                prompt_text=self._provider_prompt(run),
                system_message=CHARACTER_CREATION_PROVIDER_SYSTEM_MESSAGE,
                purpose="character_creation_complete_plan",
            )
        except FoundryError as exc:
            return self._provider_fallback(run, exc)
        response_text = receipt.get("response_text")
        if not isinstance(response_text, str) or not response_text.strip():
            return self._provider_fallback(
                run,
                FoundryError(
                    "CG1_PROVIDER_COMPLETE_RESPONSE_MISSING",
                    "The configured provider returned no complete-character response text.",
                ),
            )
        completion_sha256 = sha256_bytes(response_text.encode("utf-8"))
        if receipt.get("completion_sha256") != completion_sha256:
            return self._provider_fallback(
                run,
                FoundryError(
                    "CG1_PROVIDER_COMPLETION_HASH_MISMATCH",
                    "The configured provider completion did not match its transport hash evidence.",
                    details={
                        "declared_completion_sha256": receipt.get("completion_sha256"),
                        "actual_completion_sha256": completion_sha256,
                    },
                ),
            )
        transport = {
            "mode": run["execution_mode"],
            "provider_called": True,
            "provider_id": receipt.get("provider_id"),
            "model": receipt.get("model"),
            "purpose": receipt.get("purpose"),
            "finish_reason": receipt.get("finish_reason"),
            "complete_request_sha256": run["request"]["request_sha256"],
            "provider_request_sha256": receipt.get("request_sha256"),
            "provider_response_sha256": receipt.get("response_sha256"),
            "provider_completion_sha256": receipt.get("completion_sha256"),
            "usage": deepcopy(receipt.get("usage") or {}),
            "automatic_retries": 0,
            "mechanical_authority": False,
            "direct_commit_allowed": False,
        }
        return self._apply_response(run_id, response_text, transport)

    def _live_pipeline(self) -> dict[str,Any]:
        return {"stage1":self.stage1,"stage2":self.stage2,"projections":self.projections,"character_sheets":self.character_sheets,"factory_authoring":self.factory_authoring,"gm_exports":self.gm_exports,"gm_consumer":self.gm_consumer,"portable_characters":self.portable_characters,"combat_readiness":self.combat_readiness,"production_release":getattr(self,"production_release",None)}

    def _issue_initial_catalog_provenance(
        self,
        run: dict[str, Any],
        *,
        frozen_snapshot: dict[str, Any],
        phase: str,
        authority_db: Database,
        _finalization_authority: object | None = None,
        accepted_final_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Materialize exact initial evidence only in a sealed server phase.

        Scratch materialization occurs only in an isolated database that is
        discarded; it makes the reviewed package identity equal the final one.
        The finalization phase is the only persistent issuance.
        """
        authorized = (
            phase == "scratch_compile"
            and _finalization_authority is _SERVER_SCRATCH_COMPILATION_AUTHORITY
        ) or (
            phase == "finalization"
            and _finalization_authority is _SERVER_FINALIZATION_AUTHORITY
        )
        if not authorized:
            raise FoundryError(
                "CG1_INITIAL_PROVENANCE_ISSUANCE_FORBIDDEN",
                "Initial provenance can be materialized only by an active sealed server creation phase.",
                status_code=403,
            )
        with authority_db.connection() as conn:
            persisted_row = conn.execute(
                "SELECT * FROM character_creation_runs WHERE run_id=? AND project_id=?",
                (run.get("run_id"), run.get("project_id")),
            ).fetchone()
        if persisted_row is None:
            raise FoundryError(
                "CG1_INITIAL_PROVENANCE_CONTEXT_INVALID",
                "Initial provenance requires the exact persisted active creation run.",
                status_code=409,
            )
        persisted_request = json.loads(persisted_row["request_json"] or "{}")
        persisted_quality = json.loads(persisted_row["quality_json"] or "{}")
        persisted_candidate = json.loads(persisted_row["dry_run_json"] or "{}")
        phase_valid = (
            phase == "scratch_compile"
            and persisted_row["status"] in {"PREPARING_REQUEST", "WAITING_FOR_RESPONSE", "READY_FOR_REVIEW", "NEEDS_REVIEW"}
        ) or (
            phase == "finalization"
            and persisted_row["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
            and persisted_quality.get("status") == "CLEAN"
            and persisted_candidate.get("candidate_identity") == (run.get("dry_run") or {}).get("candidate_identity")
        )
        if not phase_valid or persisted_request.get("typed_choice_snapshot") != (run.get("request") or {}).get("typed_choice_snapshot"):
            raise FoundryError(
                "CG1_INITIAL_PROVENANCE_CONTEXT_INVALID",
                "Initial provenance requires the exact active revision-bound server creation context.",
                status_code=409,
            )
        snapshot = deepcopy(frozen_snapshot)
        if snapshot != (run.get("request") or {}).get("typed_choice_snapshot") or not valid_choice_snapshot(snapshot):
            raise FoundryError(
                "CG1_INITIAL_PROVENANCE_SNAPSHOT_INVALID",
                "Initial provenance requires the exact already-validated frozen choice snapshot.",
                status_code=409,
            )
        with authority_db.connection() as conn:
            project_row = conn.execute(
                "SELECT project_json FROM projects WHERE project_id=?", (run["project_id"],),
            ).fetchone()
        project = json.loads(project_row["project_json"] or "{}") if project_row else {}
        if self._has_delegated_envelope(run):
            grant_plan = deepcopy((accepted_final_plan or {}).get("canonical_grant_plan"))
            materialized = committed_catalog_grant_plan(project)
            if grant_plan is None or materialized != grant_plan:
                raise FoundryError(
                    "CG1_DELEGATED_FINAL_GRANT_PLAN_DIVERGED",
                    "The scratch/final project does not contain the exact accepted delegated grant plan.",
                    details={
                        "accepted_plan_sha256": sha256_json(grant_plan) if isinstance(grant_plan, dict) else None,
                        "materialized_plan_sha256": sha256_json(materialized) if isinstance(materialized, dict) else None,
                    },
                    status_code=409,
                )
        else:
            grant_plan = committed_catalog_grant_plan(project)
        if grant_plan is None:
            # Historical/non-catalog creation fixtures can legitimately contain
            # no canonical acquisitions at all.  They issue no provenance; the
            # separate frozen-choice validator still rejects any CAT3
            # acquisition proposed without an exact committed grant-plan lock.
            return {
                "schema": "TianxiaFactory.InitialCatalogProvenanceIssuance.v1",
                "project_id": run["project_id"],
                "character_id": run["project_id"],
                "run_id": run["run_id"],
                "candidate_identity": (run.get("dry_run") or {}).get("candidate_identity"),
                "typed_choice_snapshot_sha256": snapshot["snapshot_sha256"],
                "issuance_route": "initial_character_finalization",
                "record_count": 0,
                "records": [],
            }
        if not isinstance(grant_plan, dict) or grant_plan.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1":
            raise FoundryError(
                "CG1_CANONICAL_GRANT_PLAN_LOCK_MISSING",
                "Trusted finalization requires the exact revision-bound canonical grant-plan lock.",
                status_code=409,
            )
        catalog = CanonicalCatalogAuthorityService(authority_db.settings.root_dir)
        evidence_authority = NonSphereAuthorityService(authority_db)
        finalization_context = _server_initial_catalog_finalization_context(
            run_id=run["run_id"],
            project_id=run["project_id"],
            starting_revision=run["starting_revision"],
            content_lock_hash=run["request"]["content_lock_hash"],
            typed_choice_snapshot_sha256=snapshot["snapshot_sha256"],
            phase=phase,
            candidate_identity=(run.get("dry_run") or {}).get("candidate_identity") if phase == "finalization" else None,
            _authority=_TRUSTED_INITIAL_CATALOG_FINALIZATION,
        )
        issued: list[dict[str, Any]] = []
        for disposition in grant_plan.get("selected_talent_dispositions") or []:
            if not disposition.get("acquisition_provenance_required"):
                continue
            talent_id = disposition.get("canonical_talent_id")
            talent = catalog.get_talent(str(talent_id or ""))
            predicates = [
                row for row in talent.get("typed_prerequisites") or []
                if row.get("kind") == "acquisition_provenance" and row.get("scope") == "acquisition"
            ]
            if not predicates:
                raise FoundryError(
                    "CG1_CANONICAL_PROVENANCE_BINDING_MISSING",
                    "A provenance-gated Talent lacks its exact committed acquisition predicate.",
                    details={"canonical_content_id": talent_id}, status_code=409,
                )
            for predicate in predicates:
                targets = {
                    "canonical_content_id": talent["canonical_talent_id"],
                    "binding_type": "predicate",
                    "binding_id": predicate["predicate_id"],
                    "catalog_record_commitment_sha256": talent["record_commitment_sha256"],
                    "character_id": run["project_id"],
                    "issuance_route": "initial_character_finalization",
                }
                record = evidence_authority.commit_authority_event(
                    run["project_id"], "talent_acquisition_provenance", targets,
                    creation_authority="PROJECT_AUTHORITY_SERVICE",
                    idempotency_key=(
                        f"cg1.catalog-provenance:{run['run_id']}:"
                        f"{snapshot['snapshot_sha256']}:{predicate['predicate_id']}"
                    ),
                    _initial_finalization_authority=finalization_context,
                )
                issued.append({
                    "evidence_id": record["evidence_id"],
                    "authority_type": record["authority_type"],
                    "canonical_content_id": targets["canonical_content_id"],
                    "binding_type": targets["binding_type"],
                    "binding_id": targets["binding_id"],
                    "catalog_record_commitment_sha256": targets["catalog_record_commitment_sha256"],
                    "character_id": targets["character_id"],
                    "issuance_route": targets["issuance_route"],
                    "source_record_id": record["source_identity"],
                    "source_hash": record["source_hash"],
                    "evidence_hash": record["evidence_hash"],
                })
        return {
            "schema": "TianxiaFactory.InitialCatalogProvenanceIssuance.v1",
            "project_id": run["project_id"],
            "character_id": run["project_id"],
            "run_id": run["run_id"],
            "candidate_identity": (run.get("dry_run") or {}).get("candidate_identity"),
            "typed_choice_snapshot_sha256": snapshot["snapshot_sha256"],
            "issuance_route": "initial_character_finalization",
            "record_count": len(issued),
            "records": issued,
        }

    def _execute_live(self, run: dict[str,Any], plan: dict[str,Any], fail_after: str|None=None) -> dict[str,Any]:
        choice_snapshot=self._require_frozen_choice_snapshot(run)
        accepted_final_plan = deepcopy(run.get("final_plan") or {})
        execute_plan = self._plan_with_accepted_final_target(run, plan, accepted_final_plan)
        execute_plan = self._execution_descriptive_fields(run, execute_plan)
        self._materialize_descriptive_fields(run, execute_plan, self.db, phase="finalization")
        self._materialize_delegated_final_grant_plan(
            run,
            accepted_final_plan,
            self.db,
            phase="finalization",
        )
        svc=self._live_pipeline(); outputs={}
        text=execute_plan["stage1_response"] if isinstance(execute_plan["stage1_response"],str) else canonical_json(execute_plan["stage1_response"])
        attempt=svc["stage1"].validate_response(
            run["request"]["stage1_prompt"]["prompt_id"],
            text,
            prior_attempt_id=run["transport"].get("prior_attempt_id"),
        )
        outputs["stage1"]=svc["stage1"].approve_and_commit(attempt.get("attempt_id"),self.owner_principal)
        outputs["method_access"] = self._materialize_method_hard_lock(run, self.db, phase="finalization")
        if fail_after=="stage1": raise RuntimeError("forced failure after stage1")
        outputs["stage2_validation"],outputs["stage2"]=self._stage2_commit(
            svc["stage2"], deepcopy(execute_plan["stage2_proposal"]), self.owner_principal,
            creation_run=run, phase="finalization",
        )
        if fail_after=="stage2": raise RuntimeError("forced failure after stage2")
        outputs["catalog_acquisition_evidence"] = self._issue_initial_catalog_provenance(
            run,
            frozen_snapshot=choice_snapshot,
            phase="finalization",
            authority_db=self.db,
            _finalization_authority=_SERVER_FINALIZATION_AUTHORITY,
            accepted_final_plan=accepted_final_plan,
        )
        outputs["projection"]=svc["projections"].build(run["project_id"], choice_snapshot=deepcopy(choice_snapshot))
        if fail_after=="projection": raise RuntimeError("forced failure after projection")
        outputs["character_sheet"]=self._invoke(svc["character_sheets"],("build","build_sheet","sheet","current"),run["project_id"])
        if fail_after=="character_sheet": raise RuntimeError("forced failure after character_sheet")
        if svc.get("production_release") is not None:
            clean_import_root = (
                self.db.settings.data_dir.parent
                / f".{self.db.settings.data_dir.name}-cg1-clean-imports"
                / run["run_id"]
            )
            release=svc["production_release"].compile(
                run["project_id"],
                output_root=self.db.settings.logs_dir/"cg1_release"/run["run_id"],
                register=True,
                fail_after=fail_after,
                output_profile=deepcopy(execute_plan.get("output_profile") or {}),
                clean_import_root=clean_import_root,
            )
            outputs["factory_authoring"]=release["factory_authoring"]
            outputs["gm_model"]=release["command5"]
            if fail_after=="gm_export": raise RuntimeError("forced failure after gm_export")
            outputs["gm_consumer"]=release["consumer"]
            if fail_after=="gm_consumer": raise RuntimeError("forced failure after gm_consumer")
            outputs["portable_character"]={"package_sha256":release["portable_audit"].get("sha256"),"audit":release["portable_audit"],"clean_import":release["clean_import"],"registration":release["registration"],"gm_export":release["gm_export"],"release_identity":release["production_artifact_identity"]}
            outputs["_production_release"]=release
        else:
            outputs["factory_authoring"]=self._invoke(svc["factory_authoring"],("build",),run["project_id"])
            if fail_after=="factory_authoring": raise RuntimeError("forced failure after factory authoring")
            outputs["gm_model"]=self._invoke(svc["gm_exports"],("export",),run["project_id"])
            if fail_after=="gm_export": raise RuntimeError("forced failure after gm_export")
            outputs["gm_consumer"]=self._invoke(svc["gm_consumer"],("verify","consume","import_package"),outputs["gm_model"])
            if fail_after=="gm_consumer": raise RuntimeError("forced failure after gm_consumer")
            outputs["portable_character"]=self._invoke(svc["portable_characters"],("build_for_project","build_verified","export","verified_status"),run["project_id"])
        if fail_after in {"portable","portable_registration"}: raise RuntimeError("forced failure after portable")
        if bool((execute_plan.get("output_profile") or {}).get("combat_ready")):
            outputs["combat"]=self._invoke(svc["combat_readiness"],("compile","build","verify"),run["project_id"])
            if fail_after=="combat": raise RuntimeError("forced failure after combat")
        return outputs

    @staticmethod
    def _assert_completed_release_gate(outputs: dict[str, Any]) -> None:
        """Require the physical, audited completed package before clean state.

        Production release is intentionally a hard gate.  A receipt-shaped
        dictionary, an unaudited path, or a clean-import status without the
        actual bytes is not sufficient to persist ``CLEAN_AND_FINALIZED``.
        """
        from portable_character import PortableCharacterPackageService
        from character_creation.production_release import CharacterProductionReleaseAdapter, _COMBAT_REQUIRED_FIELDS

        release = outputs.get("_production_release")
        if not isinstance(release, dict):
            raise FoundryError(
                "CG1_COMPLETED_PACKAGE_GATE_FAILED",
                "A production release completion proof is required before CLEAN_AND_FINALIZED.",
                details={"release_present": False},
                status_code=409,
            )
        command6 = release.get("command6") or {}
        proof = release.get("completion_proof") or {}
        package_proof = proof.get("package") or {}
        package_value = package_proof.get("path") or command6.get("portable_character_zip") or (release.get("portable_audit") or {}).get("path")
        package = Path(str(package_value)) if package_value else None
        audit = release.get("portable_audit") or {}
        clean_import = release.get("clean_import") or {}
        first = clean_import.get("first") or {}
        second = clean_import.get("second") or {}
        consumer = release.get("consumer") or {}
        failures: dict[str, Any] = {}
        if proof.get("schema") != "TianxiaFoundry.CharacterProductionCompletionProof.v1":
            failures["completion_proof_schema"] = proof.get("schema")
        if package is None or not package.is_file():
            failures["package"] = {"path": str(package) if package else None, "exists": False}
        else:
            actual_sha = sha256_file(package)
            actual_bytes = package.stat().st_size
            if audit.get("sha256") != actual_sha or release.get("portable_zip_sha256") != actual_sha or package_proof.get("sha256") != actual_sha:
                failures["package_sha256"] = {
                    "audit": audit.get("sha256"),
                    "receipt": release.get("portable_zip_sha256"),
                    "proof": package_proof.get("sha256"),
                    "actual": actual_sha,
                }
            if package_proof.get("filename") != package.name or package_proof.get("bytes") != actual_bytes:
                failures["package_physical_identity"] = {
                    "filename": package.name,
                    "proof_filename": package_proof.get("filename"),
                    "bytes": actual_bytes,
                    "proof_bytes": package_proof.get("bytes"),
                }
            try:
                physical_audit = PortableCharacterPackageService.audit(package)
            except Exception as exc:
                failures["physical_audit"] = {"error": str(exc)}
            else:
                for field in ("sha256", "bytes", "entry_count", "checksum_count", "member_inventory_sha256"):
                    if physical_audit.get(field) != audit.get(field):
                        failures.setdefault("audit_identity", {})[field] = {
                            "receipt": audit.get(field),
                            "physical": physical_audit.get(field),
                        }
                if physical_audit.get("member_inventory") != package_proof.get("member_inventory"):
                    failures["member_inventory"] = {
                        "physical_count": len(physical_audit.get("member_inventory") or []),
                        "proof_count": len(package_proof.get("member_inventory") or []),
                    }
                if physical_audit.get("checksum_manifest") != package_proof.get("checksum_manifest"):
                    failures["checksum_manifest"] = {
                        "physical": physical_audit.get("checksum_manifest"),
                        "proof": package_proof.get("checksum_manifest"),
                    }
                if physical_audit.get("crc_validation") != package_proof.get("crc_validation"):
                    failures["crc_validation"] = {
                        "physical": physical_audit.get("crc_validation"),
                        "proof": package_proof.get("crc_validation"),
                    }
        if audit.get("valid") is not True:
            failures["audit"] = {"valid": audit.get("valid"), "audit": audit}
        if consumer.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            failures["consumer"] = {"status": consumer.get("status")}
        if first.get("status") != "IMPORTED" or second.get("status") != "ALREADY_INSTALLED_IDENTICAL":
            failures["clean_import"] = {"first": first, "second": second}
        clean_proof = proof.get("clean_import") or {}
        if (
            clean_proof.get("first_status") != "IMPORTED"
            or clean_proof.get("second_status") != "ALREADY_INSTALLED_IDENTICAL"
            or clean_proof.get("identical_reimport") is not True
        ):
            failures["clean_import_proof"] = clean_proof
        sheet_proof = proof.get("character_sheet") or {}
        if (
            sheet_proof.get("semantic_equal") is not True
            or not sheet_proof.get("producer_semantic_hash")
            or sheet_proof.get("producer_semantic_hash") != sheet_proof.get("reopened_semantic_hash")
        ):
            failures["character_sheet_semantics"] = sheet_proof
        gm_proof = proof.get("gm") or {}
        gm_equalities = gm_proof.get("equalities") or {}
        gm_source_conversion = gm_proof.get("source_conversion") or {}
        installed_gm_path = Path(str(gm_proof.get("installed_package_path") or ""))
        installed_gm_sha256 = sha256_file(installed_gm_path) if installed_gm_path.is_file() else None
        if installed_gm_sha256 != release.get("portable_zip_sha256"):
            failures["installed_gm_package"] = {
                "path": str(installed_gm_path),
                "expected_sha256": release.get("portable_zip_sha256"),
                "actual_sha256": installed_gm_sha256,
            }
        if (
            gm_proof.get("semantic_equal") is not True
            or not gm_proof.get("package_semantic_hash")
            or not gm_proof.get("installed_semantic_hash")
            or gm_proof.get("package_semantic_hash") != gm_proof.get("installed_semantic_hash")
            or not gm_proof.get("producer_model_sha256")
            or not gm_proof.get("package_sha256")
            or gm_proof.get("package_sha256") != release.get("portable_zip_sha256")
            or gm_source_conversion.get("valid") is not True
            or not gm_equalities
            or not all(value is True for value in gm_equalities.values())
        ):
            failures["gm_semantics"] = gm_proof
        consumer_proof = proof.get("consumer") or {}
        if consumer_proof.get("status") != consumer.get("status") or consumer_proof.get("status_equal") is not True:
            failures["consumer_proof"] = consumer_proof
        combat_proof = proof.get("combat") or {}
        raw_combat_hashes = combat_proof.get("raw_evidence_hashes") or {}
        raw_combat_sections = {
            "producer": combat_proof.get("producer"),
            "producer_output_profile": (combat_proof.get("producer") or {}).get("output_profile") if isinstance(combat_proof.get("producer"), dict) else None,
            "producer_sheet": (combat_proof.get("producer") or {}).get("character_sheet") if isinstance(combat_proof.get("producer"), dict) else None,
            "producer_command5": (combat_proof.get("producer") or {}).get("command5") if isinstance(combat_proof.get("producer"), dict) else None,
            "package": combat_proof.get("package"),
            "clean_import": (combat_proof.get("clean_import") or {}).get("import_report"),
            "installed": (combat_proof.get("clean_import") or {}).get("installed_audit"),
            "reopened_sheet": (combat_proof.get("clean_import") or {}).get("reopened_sheet"),
        }
        expected_raw_names = {
            "producer",
            "producer_output_profile",
            "producer_sheet",
            "producer_command5",
            "package",
            "clean_import",
            "installed",
            "reopened_sheet",
        }
        raw_combat_hashes_valid = (
            set(raw_combat_hashes) == expected_raw_names
            and all(
                isinstance(section, dict)
                and isinstance(raw_combat_hashes.get(name), str)
                and raw_combat_hashes.get(name) == sha256_json(section)
                for name, section in raw_combat_sections.items()
            )
        )
        expected_semantic_projections = {
            name: CharacterProductionReleaseAdapter._combat_semantics(section)
            for name, section in {
                key: value
                for key, value in raw_combat_sections.items()
                if key != "producer"
            }.items()
            if isinstance(section, dict)
        }
        semantic_projections = combat_proof.get("semantic_projections") or {}
        semantic_projections_valid = (
            set(semantic_projections) == set(expected_semantic_projections)
            and semantic_projections == expected_semantic_projections
        )
        combat_layers = {
            name: section
            for name, section in raw_combat_sections.items()
            if name not in {"producer", "producer_output_profile"}
        }
        computed_schema_presence = {
            name: isinstance(section, dict)
            and all(
                field in CharacterProductionReleaseAdapter._combat_semantics(section)
                for field in _COMBAT_REQUIRED_FIELDS
            )
            for name, section in combat_layers.items()
        }
        producer_profile = (
            (raw_combat_sections.get("producer_output_profile") or {}).get("output_profile")
            if isinstance(raw_combat_sections.get("producer_output_profile"), dict)
            else None
        )
        producer_sheet_raw = raw_combat_sections.get("producer_sheet")
        producer_command5_raw = raw_combat_sections.get("producer_command5")
        package_raw = raw_combat_sections.get("package")
        clean_import_raw = raw_combat_sections.get("clean_import")
        installed_raw = raw_combat_sections.get("installed")
        reopened_sheet_raw = raw_combat_sections.get("reopened_sheet")
        command5_layer_status = CharacterProductionReleaseAdapter._layer_combat_execution_status(
            producer_command5_raw,
            layer="command5",
        )
        package_layer_status = CharacterProductionReleaseAdapter._layer_combat_execution_status(
            package_raw,
            layer="package",
        )
        computed_schema_presence["producer_command5"] = computed_schema_presence["producer_command5"] and command5_layer_status["valid"]
        computed_schema_presence["package"] = computed_schema_presence["package"] and package_layer_status["valid"]
        expected_layer_status = {
            "producer_command5": command5_layer_status,
            "package": package_layer_status,
        }
        layer_status_valid = (combat_proof.get("layer_status") or {}) == expected_layer_status
        command5_package_execution_equal = (
            command5_layer_status["valid"]
            and package_layer_status["valid"]
            and command5_layer_status.get("report_combat_execution")
            == package_layer_status.get("statuses", {}).get("manifest")
            == package_layer_status.get("statuses", {}).get("readiness")
            and CharacterProductionReleaseAdapter._combat_fields_equal(
                producer_command5_raw,
                package_raw,
                fields=("combat_execution",),
            )
        )
        computed_combat_equalities = {
            "producer_sheet_reopened_sheet_status_equal": CharacterProductionReleaseAdapter._combat_fields_equal(producer_sheet_raw, reopened_sheet_raw),
            "producer_command5_package_combat_execution_equal": command5_package_execution_equal,
            "producer_command5_package_combat_surfaces_equal": CharacterProductionReleaseAdapter._combat_fields_equal(producer_command5_raw, package_raw) and command5_package_execution_equal,
            "package_installed_audit_status_equal": CharacterProductionReleaseAdapter._combat_fields_equal(package_raw, installed_raw),
            "package_import_status_equal": CharacterProductionReleaseAdapter._combat_fields_equal(package_raw, clean_import_raw),
            "package_clean_import_installed_readiness_equal": CharacterProductionReleaseAdapter._combat_fields_equal(clean_import_raw, installed_raw),
            "package_reopened_sheet_combat_semantics_equal": CharacterProductionReleaseAdapter._combat_fields_equal(package_raw, reopened_sheet_raw),
            "all_corresponding_combat_semantics_equal": all(
                (
                    CharacterProductionReleaseAdapter._combat_fields_equal(producer_sheet_raw, reopened_sheet_raw),
                    command5_package_execution_equal,
                    CharacterProductionReleaseAdapter._combat_fields_equal(producer_command5_raw, package_raw) and command5_package_execution_equal,
                    CharacterProductionReleaseAdapter._combat_fields_equal(package_raw, installed_raw),
                    CharacterProductionReleaseAdapter._combat_fields_equal(package_raw, clean_import_raw),
                    CharacterProductionReleaseAdapter._combat_fields_equal(clean_import_raw, installed_raw),
                    CharacterProductionReleaseAdapter._combat_fields_equal(package_raw, reopened_sheet_raw),
                )
            ),
            "evidence_schema_complete": all(computed_schema_presence.values()),
            "no_false_combat_ready": CharacterProductionReleaseAdapter._combat_no_false_ready_claim(
                combat_layers,
                producer_profile if isinstance(producer_profile, dict) else {},
            ),
        }
        expected_combat_equalities = {
            "producer_sheet_reopened_sheet_status_equal",
            "producer_command5_package_combat_execution_equal",
            "producer_command5_package_combat_surfaces_equal",
            "package_installed_audit_status_equal",
            "package_import_status_equal",
            "package_clean_import_installed_readiness_equal",
            "package_reopened_sheet_combat_semantics_equal",
            "all_corresponding_combat_semantics_equal",
            "evidence_schema_complete",
            "no_false_combat_ready",
        }
        actual_combat_equalities = combat_proof.get("equalities") or {}
        if (
            combat_proof.get("schema_version") != "TianxiaFoundry.CharacterProductionCombatEvidence.v2"
            or combat_proof.get("equality") is not True
            or not raw_combat_hashes_valid
            or not semantic_projections_valid
            or not layer_status_valid
            or (combat_proof.get("schema_presence") or {}) != computed_schema_presence
            or actual_combat_equalities != computed_combat_equalities
            or combat_proof.get("equality") is not all(computed_combat_equalities.values())
            or set(actual_combat_equalities) != expected_combat_equalities
            or not all(value is True for value in actual_combat_equalities.values())
        ):
            failures["combat_proof"] = combat_proof
        registration = release.get("registration")
        if not isinstance(registration, dict) or registration.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            failures["registration"] = registration
        if failures:
            raise FoundryError(
                "CG1_COMPLETED_PACKAGE_GATE_FAILED",
                "The completed-character package was absent, tampered, unaudited, or failed clean-import proof; finalization is rolled back.",
                details=failures,
                status_code=409,
            )

    def finalize(self, run_id: str, *, fail_after: str|None=None, auto_finalize_receipt: dict[str,Any]|None=None) -> dict[str,Any]:
        run=self.get(run_id)
        if run["status"] not in {"READY_FOR_REVIEW","NEEDS_REVIEW"} or run["quality"].get("status")!="CLEAN":
            raise FoundryError("CG1_RUN_NOT_CLEAN","Only a clean, reviewed candidate may be finalized.",status_code=409)
        final_plan = run.get("final_plan") or {}
        if not final_plan:
            raise FoundryError("CG1_FINAL_PLAN_REQUIRED", "Finalization requires the server-owned accepted final plan.", status_code=409)
        if final_plan_sha256(final_plan) != final_plan.get("final_plan_sha256") or final_plan.get("immutable_after_validation") is not True:
            raise FoundryError("CG1_FINAL_PLAN_INTEGRITY_FAILED", "The accepted final plan failed its immutable hash check.", status_code=409)
        if self._has_delegated_envelope(run):
            validate_accepted_final_plan_target(run, self._project(run["project_id"]), final_plan)
        approved_by = self.owner_principal
        if self._revision(run["project_id"])!=run["starting_revision"] or self._content_lock_hash(run["project_id"])!=run["request"].get("content_lock_hash"):
            raise FoundryError("CG1_STALE_RUN","The project revision or content lock changed after preview.",status_code=409)
        response_text=run["response"].get("exact_response_text") or ""
        plan, raw = self._parse_plan(response_text)
        if self._has_delegated_envelope(run):
            validate_delegated_target_cl(run, self._project(run["project_id"]), plan)
            plan, rebound_intent, _ = self._normalize_and_materialize_response(run, plan)
            if rebound_intent is not None:
                run["canonical_selection_intent"] = rebound_intent.as_dict()
        if sha256_bytes(raw) != run["response"].get("response_sha256") or sha256_json(plan) != run["validation"].get("plan_sha256"):
            raise FoundryError("CG1_APPROVED_RESPONSE_DIVERGED","The exact approved response bytes no longer match the reviewed request.",status_code=409)
        if self._has_delegated_envelope(run):
            validate_delegated_target_cl(run, self._project(run["project_id"]), plan)
        if final_plan.get("plan_sha256") and final_plan.get("plan_sha256") != sha256_json(plan):
            raise FoundryError("CG1_FINAL_PLAN_BINDING_DIVERGED", "The accepted final plan is not bound to the exact reviewed plan.", status_code=409)
        if final_plan.get("response_sha256") != run["response"].get("response_sha256") or final_plan.get("request_sha256") != run["request"].get("request_sha256"):
            raise FoundryError("CG1_FINAL_PLAN_BINDING_DIVERGED", "The accepted final plan is not bound to the exact reviewed response and request.", status_code=409)
        accepted_projection = run.get("owner_descriptive_fields") or {}
        accepted_fields = accepted_projection.get("accepted") if isinstance(accepted_projection, dict) else None
        if isinstance(accepted_fields, dict) and (
            (accepted_fields.get("identity") or {}).get("name") or accepted_fields.get("concept")
        ):
            # Owner edits are display/story authority, but the deterministic
            # candidate still needs the accepted identity in its generated
            # Character Sheet before the live identity comparison.
            approved_candidate = self._compile_twice(
                run,
                plan,
                accepted_final_plan=final_plan,
            )
        else:
            approved_candidate = run["dry_run"]
        compiled={"plan":plan,"candidate":approved_candidate}
        if not compiled["candidate"].get("deterministic") or compiled["candidate"].get("independent_compilations") != 2:
            raise FoundryError("CG1_APPROVED_CANDIDATE_DIVERGED","The approved candidate lacks two verified isolated compilations.",status_code=409)
        frozen_snapshot = self._require_frozen_choice_snapshot(run)
        clean_import_root = (
            self.db.settings.data_dir.parent
            / f".{self.db.settings.data_dir.name}-cg1-clean-imports"
            / run["run_id"]
        )
        with tempfile.TemporaryDirectory(prefix="cg1-precommit-", ignore_cleanup_errors=True) as td:
            snap=Path(td)/"data"; before=self._snapshot_data(snap)
            try:
                previous_clock=os.environ.get("TIANXIA_DETERMINISTIC_UTC")
                previous_approval_seed=os.environ.get("TIANXIA_DETERMINISTIC_APPROVAL_SEED")
                os.environ["TIANXIA_DETERMINISTIC_UTC"]=run["created_at"]
                os.environ["TIANXIA_DETERMINISTIC_APPROVAL_SEED"]=run["request"]["request_sha256"]
                try:
                    outputs=self._execute_live(run,compiled["plan"],fail_after=fail_after)
                finally:
                    if previous_clock is None:
                        os.environ.pop("TIANXIA_DETERMINISTIC_UTC",None)
                    else:
                        os.environ["TIANXIA_DETERMINISTIC_UTC"]=previous_clock
                    if previous_approval_seed is None:
                        os.environ.pop("TIANXIA_DETERMINISTIC_APPROVAL_SEED",None)
                    else:
                        os.environ["TIANXIA_DETERMINISTIC_APPROVAL_SEED"]=previous_approval_seed
                identity_outputs=outputs
                release=outputs.get("_production_release")
                if isinstance(release,dict):
                    stable_release=self.production_release._stable(release)
                    identity_outputs={
                        **outputs,
                        "factory_authoring":stable_release["factory_authoring"],
                        "gm_model":stable_release["command5"],
                        "gm_consumer":stable_release["consumer"],
                        "portable_character":{
                            "package_sha256":stable_release["portable_audit"].get("sha256"),
                            "audit":stable_release["portable_audit"],
                            "clean_import":stable_release["clean_import"],
                            "release_identity":release["production_artifact_identity"],
                        },
                    }
                    live_ids={k:sha256_json(self._identity_payload(v, _surface=k)) for k,v in identity_outputs.items() if k in compiled["candidate"]["identities"]}
                expected={k:v for k,v in compiled["candidate"]["identities"].items() if k in live_ids}
                if live_ids!=expected:
                    raise FoundryError("CG1_LIVE_OUTPUT_DIVERGED","Final live outputs do not match the approved scratch candidate.",details={"expected":expected,"actual":live_ids})
                self._assert_completed_release_gate(outputs)
            except Exception as exc:
                shutil.rmtree(clean_import_root, ignore_errors=True)
                self._restore_data(snap)
                after=self._tree_hashes(self.db.settings.data_dir)
                if after!=before:
                    raise FoundryError("CG1_ATOMIC_RESTORE_FAILED","Finalization failed and exact restoration could not be verified.",details={"cause":str(exc)}) from exc
                details={"cause":str(exc),"restored":True}
                if isinstance(exc,FoundryError):
                    details["cause_code"]=exc.code
                    details["cause_details"]=exc.details
                raise FoundryError("CG1_FINALIZATION_ROLLED_BACK","Finalization failed; the exact precommit database and files were restored.",details=details) from exc
        outputs.pop("_production_release",None)
        commit={"schema":"TianxiaFoundry.CharacterCreationCanonicalCommit.v2","approved_candidate_identity":compiled["candidate"]["candidate_identity"],"typed_choice_snapshot_sha256":run["request"]["typed_choice_snapshot"]["snapshot_sha256"],"approved_by":approved_by,"approved_by_sha256":self.owner_principal_hash,"auto_finalize_opt_in_receipt_sha256":(auto_finalize_receipt or {}).get("receipt_sha256"),"outputs":{k:sha256_json(v) for k,v in outputs.items()}}
        final_revision=self._revision(run["project_id"])
        completed_at=utcnow()
        with self.db.transaction() as conn:
            conn.execute("UPDATE character_creation_runs SET owner_decision='FINALIZE',commit_json=?,final_revision=?,output_json=?,status='CLEAN_AND_FINALIZED',updated_at=?,completed_at=? WHERE run_id=?",(canonical_json(commit),final_revision,canonical_json(outputs),completed_at,completed_at,run_id))
        self._append_attempt(
            run,
            action_type="FINALIZE",
            status="FINALIZED",
            canonical_intent=(run.get("response") or {}).get("parsed_plan", {}).get("canonical_selection_intent") if isinstance((run.get("response") or {}).get("parsed_plan"), dict) else None,
            materialization_receipt=(run.get("validation") or {}).get("materialization_receipt"),
            validation=run.get("validation") or {},
            quality=run.get("quality") or {},
            candidate_identity=compiled["candidate"].get("candidate_identity"),
            materialized_plan_sha256=(run.get("validation") or {}).get("materialized_stage2_hash"),
            submitted_plan_sha256=(run.get("validation") or {}).get("plan_sha256"),
            prior_attempt_id=self._latest_attempt_id(run_id),
            binding={"final_plan_sha256": final_plan.get("final_plan_sha256"), "candidate_identity": compiled["candidate"].get("candidate_identity")},
            links={"final_plan_sha256": final_plan.get("final_plan_sha256"), "commit_candidate_identity": compiled["candidate"].get("candidate_identity")},
        )
        return self.get(run_id)

    def prepare_edit_brief(
        self,
        run_id: str,
        *,
        owner_notes: str = "",
        brief: dict[str, Any] | None = None,
        user_locks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist an explicit owner edit before creating a replacement run.

        Preparation is intentionally not a project mutation.  The submitted
        brief/lock proposal is hashed and carried into the child request only
        after the owner submits the returned ``edit_id``.  This keeps the
        existing immutable project-lock and prompt-boundary invariants intact.
        """
        source = self.get(run_id)
        if source["status"] in TERMINAL_RUN_STATUSES:
            raise FoundryError(
                "CG1_EDIT_BRIEF_TERMINAL",
                "A terminal run cannot be edited; start a deliberate new request.",
                status_code=409,
            )
        notes = str(owner_notes or "").strip()
        proposed_brief = deepcopy(brief) if isinstance(brief, dict) else {}
        proposed_locks = deepcopy(user_locks) if isinstance(user_locks, list) else []
        for index, lock in enumerate(proposed_locks):
            if not isinstance(lock, dict) or not isinstance(lock.get("field"), str) or not lock["field"].strip():
                raise FoundryError(
                    "CG1_EDIT_BRIEF_LOCK_INVALID",
                    "Each proposed edit lock requires a non-empty field.",
                    details={"index": index},
                    status_code=422,
                )
        if proposed_locks:
            raise FoundryError(
                "CG1_EDIT_BRIEF_USER_LOCKS_UNSUPPORTED",
                "This recovery action cannot apply user_locks safely; create or edit the project choices through the existing authority before starting a new request.",
                details={"field": "user_locks", "action": "Edit Brief / Create New Request"},
                status_code=422,
            )
        if not notes and not proposed_brief and not proposed_locks:
            raise FoundryError(
                "CG1_EDIT_BRIEF_PAYLOAD_REQUIRED",
                "Submit at least one changed brief note or proposed owner lock before creating a new request.",
                status_code=422,
            )
        payload = {
            "schema": "TianxiaFoundry.CharacterCreationBriefEdit.v1",
            "source_run_id": run_id,
            "project_id": source["project_id"],
            "owner_notes": notes,
            "brief": proposed_brief,
            "proposed_user_locks": proposed_locks,
            "source_project_revision": self._revision(source["project_id"]),
            "source_content_lock_hash": self._content_lock_hash(source["project_id"]),
        }
        payload_sha256 = sha256_json(payload)
        edit_id = "cg1.edit." + uuid.uuid4().hex
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO character_creation_brief_edits(edit_id,source_run_id,project_id,payload_json,payload_sha256,status,created_at) VALUES(?,?,?,?,?,?,?)",
                (edit_id, run_id, source["project_id"], canonical_json(payload), payload_sha256, "PREPARED", utcnow()),
            )
        return {
            "schema": "TianxiaFoundry.CharacterCreationBriefEditPreparation.v1",
            "edit_id": edit_id,
            "source_run_id": run_id,
            "project_id": source["project_id"],
            "payload": payload,
            "payload_sha256": payload_sha256,
            "next_action": "Submit edit_id to create the linked new request.",
        }

    def create_new_request_from_edit(self, edit_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM character_creation_brief_edits WHERE edit_id=?",
                (edit_id,),
            ).fetchone()
        if not row:
            raise FoundryError("CG1_EDIT_BRIEF_NOT_FOUND", "No prepared Edit Brief payload has that ID.", status_code=404)
        if row["status"] != "PREPARED":
            raise FoundryError(
                "CG1_EDIT_BRIEF_ALREADY_SUBMITTED",
                "That prepared Edit Brief has already been consumed or cancelled.",
                details={"edit_id": edit_id, "status": row["status"]},
                status_code=409,
            )
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise FoundryError("CG1_EDIT_BRIEF_CORRUPT", "The prepared Edit Brief payload is not valid JSON.", status_code=500) from exc
        if canonical_json(payload) != row["payload_json"] or sha256_json(payload) != row["payload_sha256"]:
            raise FoundryError("CG1_EDIT_BRIEF_INTEGRITY_FAILED", "The prepared Edit Brief payload failed its immutable hash check.", status_code=409)
        source = self.get(row["source_run_id"])
        if source["status"] in TERMINAL_RUN_STATUSES:
            raise FoundryError("CG1_EDIT_BRIEF_TERMINAL", "The source run is already terminal and cannot create a replacement request.", status_code=409)
        revision_request = {
            "schema": "TianxiaFoundry.CharacterCreationRevisionRequest.v2",
            "source_run_id": source["run_id"],
            "source_candidate_identity": (source.get("dry_run") or {}).get("candidate_identity"),
            "prior_response_sha256": (source.get("response") or {}).get("response_sha256"),
            "blockers": deepcopy(source.get("blockers") or []),
            "warnings": deepcopy(source.get("warnings") or []),
            "owner_notes": payload.get("owner_notes") or "",
            "brief": deepcopy(payload.get("brief") or {}),
            "proposed_user_locks": deepcopy(payload.get("proposed_user_locks") or []),
            "edit_id": edit_id,
            "edit_payload_sha256": row["payload_sha256"],
            "project_revision": self._revision(source["project_id"]),
            "content_lock_hash": self._content_lock_hash(source["project_id"]),
        }
        child_key = f"{source['idempotency_key']}.rev.{uuid.uuid4().hex[:12]}"
        child = self.start(
            source["project_id"],
            execution_mode=source["execution_mode"],
            idempotency_key=child_key,
            revision_request=revision_request,
        )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_brief_edits SET status='CONSUMED',child_run_id=?,consumed_at=? WHERE edit_id=? AND status='PREPARED'",
                (child["run_id"], utcnow(), edit_id),
            )
            conn.execute(
                "UPDATE character_creation_runs SET owner_decision='REVISE',status='REVISED',output_json=?,updated_at=? WHERE run_id=?",
                (canonical_json({"revision_request": revision_request, "child_run_id": child["run_id"], "edit_id": edit_id}), utcnow(), source["run_id"]),
            )
        self._append_attempt(
            source,
            action_type="EDIT_BRIEF_CREATE_NEW_REQUEST",
            status="LINKED_NEW_REQUEST",
            prior_attempt_id=self._latest_attempt_id(source["run_id"]),
            binding={"child_run_id": child["run_id"], "edit_id": edit_id, "edit_payload_sha256": row["payload_sha256"], "revision_request": revision_request},
        )
        return self.get(child["run_id"])

    def edit_brief_create_new_request(
        self,
        run_id: str,
        *,
        edit_id: str | None = None,
        owner_notes: str = "",
        brief: dict[str, Any] | None = None,
        user_locks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Consume a prepared edit; retain a compatibility one-call service API."""
        if edit_id is None:
            prepared = self.prepare_edit_brief(
                run_id,
                owner_notes=owner_notes,
                brief=brief,
                user_locks=user_locks,
            )
            edit_id = prepared["edit_id"]
        with self.db.connection() as conn:
            row = conn.execute("SELECT source_run_id FROM character_creation_brief_edits WHERE edit_id=?", (edit_id,)).fetchone()
        if not row or row["source_run_id"] != run_id:
            raise FoundryError("CG1_EDIT_BRIEF_BINDING_MISMATCH", "The prepared Edit Brief belongs to a different source run.", status_code=409)
        return self.create_new_request_from_edit(edit_id)

    def revise(self, run_id: str, *, owner_notes: str) -> dict[str,Any]:
        """Compatibility alias for the explicit Edit Brief/Create New Request action."""
        return self.edit_brief_create_new_request(run_id, owner_notes=owner_notes)

    def cancel(self, run_id: str) -> dict[str,Any]:
        run=self.get(run_id)
        if run["commit"]: raise FoundryError("CG1_RUN_ALREADY_COMMITTED","A finalized character run cannot be cancelled.",status_code=409)
        with self.db.transaction() as conn:
            conn.execute("UPDATE character_creation_runs SET owner_decision='CANCEL',status='CANCELLED',updated_at=?,completed_at=? WHERE run_id=?",(utcnow(),utcnow(),run_id))
        self._append_attempt(
            run,
            action_type="CANCEL_BUILD",
            status="CANCELLED",
            prior_attempt_id=self._latest_attempt_id(run_id),
            binding={"prior_status": run.get("status"), "request_sha256": (run.get("request") or {}).get("request_sha256")},
        )
        return self.get(run_id)
