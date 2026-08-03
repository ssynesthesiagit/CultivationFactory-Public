from __future__ import annotations

import io
import gc
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
from catalog_choice_authority import COMMITTED_CATALOG_CHOICE_FIELD, committed_catalog_grant_plan
from character_creation.choice_snapshot import materialize_choice_snapshot, valid_choice_snapshot
from non_sphere_authority import NonSphereAuthorityService
from non_sphere_authority.service import (
    _TRUSTED_INITIAL_CATALOG_FINALIZATION,
    _server_initial_catalog_finalization_context,
)
from stage2.service import _TRUSTED_CHARACTER_CREATION_EXECUTION

MODES = {"MANUAL_CHAT", "STANDARD_API", "AUTO_FINALIZE_WHEN_CLEAN"}
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
RESPONSE_BINDING_ERROR = "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"
RESPONSE_BINDING_MESSAGE = (
    "The complete response is not bound to this exact active request. "
    "Prepare a new response from this run's complete request and try again."
)
CHARACTER_CREATION_PROVIDER_SYSTEM_MESSAGE = (
    "You are an untrusted Tianxia complete-character planning adapter. Return exactly one JSON object "
    "that follows the complete response contract in the user prompt. Copy the exact active request_sha256 "
    "into the response. Select only offered IDs. Do not invent mechanics, compiled surfaces, readiness, "
    "artifact identities, actions, tools, or network instructions. The local Factory validates every choice, "
    "performs two isolated compilations, and retains sole mechanical and commit authority."
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

    def _public(self, row: Any) -> dict[str, Any]:
        return {
            "schema": RUN_SCHEMA, "run_id": row["run_id"], "project_id": row["project_id"],
            "starting_revision": row["starting_revision"], "execution_mode": row["execution_mode"],
            "idempotency_key": row["idempotency_key"], "request": self._loads(row, "request_json", {}),
            "transport": self._loads(row, "transport_json", {}), "response": self._loads(row, "response_json", {}),
            "validation": self._loads(row, "validation_json", {}), "dry_run": self._loads(row, "dry_run_json", {}),
            "quality": self._loads(row, "quality_json", {}), "owner_decision": row["owner_decision"],
            "commit": self._loads(row, "commit_json", {}), "final_revision": row["final_revision"],
            "outputs": self._loads(row, "output_json", {}), "blockers": self._loads(row, "blockers_json", []),
            "warnings": self._loads(row, "warnings_json", []), "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "completed_at": row["completed_at"],
            "secret_persisted": False,
        }

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

    def _complete_request(self, project_id: str, revision_request: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = self.stage1.generate_prompt(project_id)
        request = {
            "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v2",
            "project_id": project_id,
            "project_revision": self._revision(project_id),
            "content_lock_hash": self._content_lock_hash(project_id),
            "typed_choice_snapshot": self._choice_snapshot(project_id),
            "stage1_prompt": deepcopy(prompt),
            "required_plan_schema": PLAN_SCHEMA,
            "required_components": ["stage1_response", "target_cl", "stage2_proposal", "owner_descriptive_fields", "uncertainties", "fallbacks", "output_profile"],
            "forbidden_planner_fields": sorted(FORBIDDEN_PLANNER_FIELDS),
            "policy": {"planner_prose_is_mechanical_authority": False, "automatic_retries": False},
        }
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
        response_schema = {
            "schema": PLAN_SCHEMA,
            "required": list(request["required_components"]) + ["request_sha256"],
            "request_sha256": request["request_sha256"],
            "forbidden_planner_fields": request["forbidden_planner_fields"],
            "authority": "Planner prose and asserted compiled surfaces are not mechanical authority.",
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
            "PROMPT_INSTRUCTIONS.md": (
                b"# Complete Character Creation Request\n\nReturn exactly one JSON object conforming "
                b"to RESPONSE_SCHEMA.json. Copy the exact request_sha256 into the response. Do not "
                b"assert compiled mechanics, readiness, or artifact identities. The local Factory "
                b"validates and compiles every mechanical choice.\n"
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
        request = self._complete_request(project_id, revision_request)
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
        if not isinstance(plan, dict) or plan.get("schema") not in {PLAN_SCHEMA, LEGACY_PLAN_SCHEMA}:
            raise FoundryError("CG1_PLAN_SCHEMA_INVALID", f"The response must use {PLAN_SCHEMA}.")
        forbidden = sorted(k for k in plan if k in FORBIDDEN_PLANNER_FIELDS)
        if forbidden:
            raise FoundryError("CG1_PLANNER_AUTHORITY_FIELDS_FORBIDDEN", "Planner responses may not assert compiled surfaces, readiness, or artifact identities.", details={"fields": forbidden})
        return plan, raw

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
        from character_creation.production_release import CharacterProductionReleaseAdapter
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
            created=self._invoke(svc,("create_proposal",),proposal)
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
    def _identity_payload(value: Any) -> Any:
        if isinstance(value, dict):
            # Approval challenges intentionally bind a process-local monotonic
            # clock epoch.  Preserve and validate the complete receipt in the
            # candidate artifacts, but do not make semantic character identity
            # depend on that execution envelope.
            execution_envelope_fields = {
                "approval_evidence_id",
                "binding_set_hash",
                "integrity_mac",
                "terminal_attempt_id",
                "terminal_projection_hash",
                "terminal_projection_json",
            }
            transient_location_fields = {
                "path",
                "artifact_path",
                "package_path",
                "workspace_path",
                "created_at",
                "updated_at",
            }
            excluded = execution_envelope_fields | transient_location_fields
            return {
                k: CharacterCreationExecutionService._identity_payload(v)
                for k, v in sorted(value.items())
                if k not in excluded
            }
        if isinstance(value, list):
            return [CharacterCreationExecutionService._identity_payload(v) for v in value]
        return value

    def _compile_once(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        index: int,
        *,
        prior_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        choice_snapshot = self._require_frozen_choice_snapshot(run)
        with tempfile.TemporaryDirectory(prefix=f"cg1-scratch-{index}-", ignore_cleanup_errors=True) as td:
            root=Path(td); data=root/"data"
            self._snapshot_data(data)
            s=self.db.settings
            settings=Settings(root_dir=s.root_dir,data_dir=data,db_path=data/s.db_path.name,inbox_dir=data/"inbox",exports_dir=data/"exports",packs_dir=data/"content_packs",vendor_dir=data/"vendor",logs_dir=data/"logs",backups_dir=data/"backups",security_dir=data/"security",factory_zip=s.factory_zip,fixture_path=s.fixture_path)
            scratch_db=Database(settings); scratch_db.migrate(); services=self._scratch_services(scratch_db)
            stage1=services["stage1"]
            method_access_receipt = self._materialize_method_hard_lock(run, scratch_db, phase="scratch_compile")
            s1=plan["stage1_response"]; text=s1 if isinstance(s1,str) else canonical_json(s1)
            attempt=stage1.validate_response(
                run["request"]["stage1_prompt"]["prompt_id"],
                text,
                prior_attempt_id=prior_attempt_id,
            )
            v=attempt.get("validation") or {}
            if v.get("valid") is False or v.get("errors") or v.get("blockers"):
                raise FoundryError("CG1_STAGE1_INVALID","Stage 1 validation rejected the plan.",details=v)
            stage1_commit=stage1.approve_and_commit(attempt.get("attempt_id"),self.owner_principal)
            stage2_validation,stage2_commit=self._stage2_commit(
                services["stage2"], deepcopy(plan["stage2_proposal"]), self.owner_principal,
                creation_run=run, phase="scratch_compile",
            )
            self._issue_initial_catalog_provenance(
                run,
                frozen_snapshot=choice_snapshot,
                phase="scratch_compile",
                authority_db=scratch_db,
                _finalization_authority=_SERVER_SCRATCH_COMPILATION_AUTHORITY,
            )
            projection=services["projections"].build(run["project_id"], choice_snapshot=deepcopy(choice_snapshot))
            sheet=self._invoke(services["character_sheets"],("build","build_sheet","sheet","current"),run["project_id"])
            if services.get("production_release") is not None:
                release=services["production_release"].compile(run["project_id"], output_root=root/"release", register=False)
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
            if bool((plan.get("output_profile") or {}).get("combat_ready")):
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
            identities={k:sha256_json(self._identity_payload(v)) for k,v in identity_artifacts.items() if v is not None}
            preview={"identity":deepcopy(plan.get("owner_descriptive_fields") or {}),"target_cl":plan.get("target_cl"),"compiled":deepcopy(artifacts),"readiness":{k:{"service":k,"identity":identities.get(k),"verification_status":"VERIFIED","receipt":deepcopy(artifacts.get(k))} for k in REQUIRED_SURFACES},"uncertainties":deepcopy(plan.get("uncertainties") or []),"fallbacks":deepcopy(plan.get("fallbacks") or [])}
            if combat is not None: preview["readiness"]["combat"]={"service":"combat_readiness","identity":identities["combat"],"verification_status":"VERIFIED","receipt":deepcopy(combat)}
            candidate_identity=sha256_json({"plan_sha256":sha256_json(plan),"typed_choice_snapshot_sha256":choice_snapshot["snapshot_sha256"],"identities":identities})
            return {"schema":"TianxiaFoundry.CompiledCharacterCandidate.v3","candidate_identity":candidate_identity,"typed_choice_snapshot":deepcopy(choice_snapshot),"identities":identities,"preview":preview,"artifacts":artifacts}

    def _compile_twice(
        self,
        run: dict[str, Any],
        plan: dict[str, Any],
        *,
        prior_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        previous_clock=os.environ.get("TIANXIA_DETERMINISTIC_UTC")
        previous_approval_seed=os.environ.get("TIANXIA_DETERMINISTIC_APPROVAL_SEED")
        os.environ["TIANXIA_DETERMINISTIC_UTC"]=run["created_at"]
        os.environ["TIANXIA_DETERMINISTIC_APPROVAL_SEED"]=run["request"]["request_sha256"]
        try:
            a=self._compile_once(run, plan, 1, prior_attempt_id=prior_attempt_id)
            b=self._compile_once(run, plan, 2, prior_attempt_id=prior_attempt_id)
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
            raise FoundryError("CG1_NONDETERMINISTIC_COMPILATION","The two isolated Factory compilations produced different identities.",details={"first":a["identities"],"second":b["identities"]})
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
            if (proposal_spheres or proposal_free or proposal_ordinary) and not legacy_selected:
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
        blockers=[]; warnings=[]
        for k in ("stage1_response","target_cl","stage2_proposal","owner_descriptive_fields","uncertainties","fallbacks","output_profile"):
            if k not in plan: blockers.append({"code":"CG1_PLAN_COMPONENT_MISSING","field":k,"message":f"The complete plan is missing {k}."})
        if not isinstance(plan.get("target_cl"),int) or not 1<=int(plan.get("target_cl") or 0)<=20:
            blockers.append({"code":"CG1_TARGET_CL_INVALID","message":"Target CL must be 1 through 20."})
        blockers.extend(self._collaborator_blockers(bool((plan.get("output_profile") or {}).get("combat_ready"))))
        if blockers: raise FoundryError("CG1_PLAN_BLOCKED","The plan cannot enter local compilation.",details={"blockers":blockers})
        self._validate_frozen_catalog_choices(run, plan)
        candidate=self._compile_twice(run, plan, prior_attempt_id=prior_attempt_id)
        warnings.extend(deepcopy(plan.get("uncertainties") or [])); warnings.extend(deepcopy(plan.get("fallbacks") or []))
        quality={"schema":QUALITY_SCHEMA,"status":"CLEAN" if not warnings else "NEEDS_REVIEW","required_receipts":sorted(candidate["preview"]["readiness"]),"candidate_identity":candidate["candidate_identity"]}
        validation={"valid":True,"response_sha256":sha256_bytes(raw),"plan_sha256":sha256_json(plan),"planner_authority_fields_used":False}
        return {"plan":plan,"validation":validation,"candidate":candidate,"quality":quality,"warnings":warnings,"raw_sha256":sha256_bytes(raw)}

    def _apply_response(
        self,
        run_id: str,
        response_text: str,
        transport: dict[str, Any],
        *,
        submitted_request_sha256: str | None = None,
        prior_attempt_id: str | None = None,
        binding_error_status: bool = False,
    ) -> dict[str, Any]:
        run = self.get(run_id)
        transport = deepcopy(transport)
        if prior_attempt_id is not None:
            transport["prior_attempt_id"] = prior_attempt_id
        try:
            compiled = self._validate_and_compile(
                run,
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
                conn.execute(
                    """UPDATE character_creation_runs SET transport_json=?,response_json=?,validation_json=?,dry_run_json=?,quality_json=?,blockers_json='[]',warnings_json=?,status=?,updated_at=? WHERE run_id=?""",
                    (
                        canonical_json(transport), canonical_json(response), canonical_json(compiled["validation"]),
                        canonical_json(compiled["candidate"]), canonical_json(compiled["quality"]),
                        canonical_json(compiled["warnings"]), status, utcnow(), run_id,
                    ),
                )
        except FoundryError as exc:
            if exc.code == RESPONSE_BINDING_ERROR and binding_error_status:
                raise
            blocker = {"code": exc.code, "message": exc.message, "details": exc.details}
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE character_creation_runs SET transport_json=?,response_json=?,blockers_json=?,status='NEEDS_REVIEW',updated_at=? WHERE run_id=?",
                    (
                        canonical_json(transport),
                        canonical_json({
                            "exact_response_text": response_text,
                            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
                        }),
                        canonical_json([blocker]), utcnow(), run_id,
                    ),
                )
            return self.get(run_id)
        result = self.get(run_id)
        if result["execution_mode"] == "AUTO_FINALIZE_WHEN_CLEAN" and result["quality"].get("status") == "CLEAN":
            receipt = self._valid_auto_finalize_opt_in(result)
            if receipt:
                return self.finalize(run_id, auto_finalize_receipt=receipt)
        return result

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
            {"mode": "MANUAL_CHAT", "provider_called": False, "transfer": "pasted_response"},
            submitted_request_sha256=request_sha256,
            prior_attempt_id=prior_attempt_id,
            binding_error_status=True,
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
            {"mode": "MANUAL_CHAT", "provider_called": False, "transfer": "response_file", **upload},
            binding_error_status=True,
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
                "schema": PLAN_SCHEMA,
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
            and persisted_row["status"] in {"PREPARING_REQUEST", "WAITING_FOR_RESPONSE"}
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
        svc=self._live_pipeline(); outputs={}
        outputs["method_access"] = self._materialize_method_hard_lock(run, self.db, phase="finalization")
        text=plan["stage1_response"] if isinstance(plan["stage1_response"],str) else canonical_json(plan["stage1_response"])
        attempt=svc["stage1"].validate_response(
            run["request"]["stage1_prompt"]["prompt_id"],
            text,
            prior_attempt_id=run["transport"].get("prior_attempt_id"),
        )
        outputs["stage1"]=svc["stage1"].approve_and_commit(attempt.get("attempt_id"),self.owner_principal)
        if fail_after=="stage1": raise RuntimeError("forced failure after stage1")
        outputs["stage2_validation"],outputs["stage2"]=self._stage2_commit(
            svc["stage2"], deepcopy(plan["stage2_proposal"]), self.owner_principal,
            creation_run=run, phase="finalization",
        )
        if fail_after=="stage2": raise RuntimeError("forced failure after stage2")
        outputs["catalog_acquisition_evidence"] = self._issue_initial_catalog_provenance(
            run,
            frozen_snapshot=choice_snapshot,
            phase="finalization",
            authority_db=self.db,
            _finalization_authority=_SERVER_FINALIZATION_AUTHORITY,
        )
        outputs["projection"]=svc["projections"].build(run["project_id"], choice_snapshot=deepcopy(choice_snapshot))
        if fail_after=="projection": raise RuntimeError("forced failure after projection")
        outputs["character_sheet"]=self._invoke(svc["character_sheets"],("build","build_sheet","sheet","current"),run["project_id"])
        if fail_after=="character_sheet": raise RuntimeError("forced failure after character_sheet")
        if svc.get("production_release") is not None:
            release=svc["production_release"].compile(
                run["project_id"],
                output_root=self.db.settings.logs_dir/"cg1_release"/run["run_id"],
                register=True,
                fail_after=fail_after,
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
        if bool((plan.get("output_profile") or {}).get("combat_ready")):
            outputs["combat"]=self._invoke(svc["combat_readiness"],("compile","build","verify"),run["project_id"])
            if fail_after=="combat": raise RuntimeError("forced failure after combat")
        return outputs

    def finalize(self, run_id: str, *, fail_after: str|None=None, auto_finalize_receipt: dict[str,Any]|None=None) -> dict[str,Any]:
        run=self.get(run_id)
        if run["status"] not in {"READY_FOR_REVIEW","NEEDS_REVIEW"} or run["quality"].get("status")!="CLEAN":
            raise FoundryError("CG1_RUN_NOT_CLEAN","Only a clean, reviewed candidate may be finalized.",status_code=409)
        approved_by = self.owner_principal
        if self._revision(run["project_id"])!=run["starting_revision"] or self._content_lock_hash(run["project_id"])!=run["request"].get("content_lock_hash"):
            raise FoundryError("CG1_STALE_RUN","The project revision or content lock changed after preview.",status_code=409)
        response_text=run["response"].get("exact_response_text") or ""
        plan, raw = self._parse_plan(response_text)
        if sha256_bytes(raw) != run["response"].get("response_sha256") or sha256_json(plan) != run["validation"].get("plan_sha256"):
            raise FoundryError("CG1_APPROVED_RESPONSE_DIVERGED","The exact approved response bytes no longer match the reviewed request.",status_code=409)
        compiled={"plan":plan,"candidate":run["dry_run"]}
        if not compiled["candidate"].get("deterministic") or compiled["candidate"].get("independent_compilations") != 2:
            raise FoundryError("CG1_APPROVED_CANDIDATE_DIVERGED","The approved candidate lacks two verified isolated compilations.",status_code=409)
        frozen_snapshot = self._require_frozen_choice_snapshot(run)
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
                live_ids={k:sha256_json(self._identity_payload(v)) for k,v in identity_outputs.items() if k in compiled["candidate"]["identities"]}
                expected={k:v for k,v in compiled["candidate"]["identities"].items() if k in live_ids}
                if live_ids!=expected:
                    raise FoundryError("CG1_LIVE_OUTPUT_DIVERGED","Final live outputs do not match the approved scratch candidate.",details={"expected":expected,"actual":live_ids})
            except Exception as exc:
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
        return self.get(run_id)

    def revise(self, run_id: str, *, owner_notes: str) -> dict[str,Any]:
        source=self.get(run_id); notes=str(owner_notes or "").strip()
        revision_request={"schema":"TianxiaFoundry.CharacterCreationRevisionRequest.v1","source_run_id":run_id,"source_candidate_identity":source["dry_run"].get("candidate_identity"),"prior_response_sha256":source["response"].get("response_sha256"),"blockers":deepcopy(source["blockers"]),"warnings":deepcopy(source["warnings"]),"owner_notes":notes,"project_revision":self._revision(source["project_id"]),"content_lock_hash":self._content_lock_hash(source["project_id"])}
        child_key=f"{source['idempotency_key']}.rev.{uuid.uuid4().hex[:12]}"
        child=self.start(source["project_id"],execution_mode=source["execution_mode"],idempotency_key=child_key,revision_request=revision_request)
        with self.db.transaction() as conn:
            conn.execute("UPDATE character_creation_runs SET owner_decision='REVISE',status='REVISED',output_json=?,updated_at=? WHERE run_id=?",(canonical_json({"revision_request":revision_request,"child_run_id":child["run_id"]}),utcnow(),run_id))
        return self.get(child["run_id"])

    def cancel(self, run_id: str) -> dict[str,Any]:
        run=self.get(run_id)
        if run["commit"]: raise FoundryError("CG1_RUN_ALREADY_COMMITTED","A finalized character run cannot be cancelled.",status_code=409)
        with self.db.transaction() as conn:
            conn.execute("UPDATE character_creation_runs SET owner_decision='CANCEL',status='CANCELLED',updated_at=?,completed_at=? WHERE run_id=?",(utcnow(),utcnow(),run_id))
        return self.get(run_id)
