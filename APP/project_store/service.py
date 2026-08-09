from __future__ import annotations

import gc
import json
import uuid
import zipfile
import unicodedata
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from app.core import (
    Database,
    FoundryError,
    canonical_json,
    sha256_bytes,
    sha256_file,
    sha256_json,
    utcnow,
)
from contracts.canonical import (
    ZERO_HASH,
    canonical_event_from_draft,
    canonical_event_hash,
    canonical_project_document,
    canonical_project_hash,
)
from contracts.registry import ContractValidationError, SchemaRegistry
from catalog.service import CatalogService
from content_packs.membership import PackSeal, verify_pack_seal
from security.integrity import IntegrityService

ALLOWED_DRAFT_EVENT_TYPES = {
    "acquire", "evolve", "replace", "retire", "author_metadata", "lock_change", "migration",
    # Legacy UI aliases. They are transformed into schema-authorized v1 events.
    "reversal", "supersede",
}
ALLOWED_ACTORS = {"human", "ai-planner", "system", "migration"}
RESERVED_GENERIC_DRAFT_ACTORS = {"ai-planner", "system", "migration"}
RESERVED_GENERIC_DRAFT_CHANNELS = {"fixture-reconstruction", "deterministic-projection-migration"}
# The installed CAT3 authority now carries the exact R2 Insight occurrence
# ledger in project lock snapshots.  Keep the expanded archive guard at 256 MiB
# while allowing the resulting compressed portable project to cross the former
# 64 MiB boundary without weakening traversal or expansion checks.
MAX_PROJECT_ARCHIVE = 96 * 1024 * 1024
MAX_PROJECT_EXPANDED = 256 * 1024 * 1024


def _initial_state(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "TianxiaFoundry.ProjectState.v1",
        "project_id": project_id,
        "selections": {},
        "metadata": {},
        "retired_record_ids": [],
        "migration_history": [],
        "reversed_event_ids": [],
        "superseded_event_ids": [],
    }


def _add_selection(state: dict[str, Any], content_type: str, record_id: str) -> None:
    values = state["selections"].setdefault(content_type, [])
    if record_id not in values:
        values.append(record_id)
        values.sort()
    if record_id in state["retired_record_ids"]:
        state["retired_record_ids"].remove(record_id)


def _retire_selection(state: dict[str, Any], record_id: str) -> None:
    for values in state["selections"].values():
        if record_id in values:
            values.remove(record_id)
    if record_id not in state["retired_record_ids"]:
        state["retired_record_ids"].append(record_id)
        state["retired_record_ids"].sort()


class ProjectStore:
    """Persistent character projects with canonical external documents.

    SQLite columns are internal persistence/read-model fields. ``projects.project_json``
    is always the canonical ``CharacterProject.v1`` document after Phase 2R migration.
    ``events.event_json`` is always a canonical ``AdvancementEvent.v1`` document.
    """

    BUILDER_PERSISTENCE_STATES = {"temporary", "saved_draft", "completed"}

    def __init__(self, db: Database, *, integrity: IntegrityService | None = None):
        self.db = db
        self.integrity = integrity or IntegrityService.for_database(db)
        self.registry = SchemaRegistry(db.settings.root_dir)

    @classmethod
    def _validate_builder_persistence_state(cls, state: str) -> str:
        normalized = str(state or "").strip()
        if normalized not in cls.BUILDER_PERSISTENCE_STATES:
            raise FoundryError(
                "CHARACTER_BUILDER_LIFECYCLE_INVALID",
                "The character-builder persistence state is invalid.",
                details={"state": state},
            )
        return normalized

    @staticmethod
    def _builder_lifecycle_row(conn, project_id: str):
        return conn.execute(
            "SELECT project_id,persistence_state,lifecycle_source,created_at,updated_at FROM character_builder_project_lifecycle WHERE project_id=?",
            (project_id,),
        ).fetchone()

    @classmethod
    def _set_builder_lifecycle(cls, conn, project_id: str, state: str, *, source: str) -> None:
        normalized = cls._validate_builder_persistence_state(state)
        now = utcnow()
        conn.execute(
            """INSERT INTO character_builder_project_lifecycle(project_id,persistence_state,lifecycle_source,created_at,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
                 persistence_state=excluded.persistence_state,
                 lifecycle_source=excluded.lifecycle_source,
                 updated_at=excluded.updated_at""",
            (project_id, normalized, source, now, now),
        )

    @staticmethod
    def _lifecycle_projection(row) -> dict[str, Any]:
        if row is None:
            return {
                "persistence_state": "legacy_persistent",
                "is_temporary": False,
                "display_label": "Saved / existing",
                "plain_explanation": "This existing character is retained.",
            }
        state = str(row["persistence_state"])
        labels = {
            "temporary": ("Temporary", "Disappears if abandoned or the Factory closes before you save it."),
            "saved_draft": ("Saved Draft", "Retained for later."),
            "completed": ("Completed/Built", "Retained as a completed or built character."),
        }
        label, explanation = labels[state]
        return {
            "persistence_state": state,
            "is_temporary": state == "temporary",
            "display_label": label,
            "plain_explanation": explanation,
            "lifecycle_source": row["lifecycle_source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def builder_lifecycle(self, project_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            exists = conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not exists:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            return self._lifecycle_projection(self._builder_lifecycle_row(conn, project_id))

    def save_builder_draft(self, project_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            exists = conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not exists:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            row = self._builder_lifecycle_row(conn, project_id)
            if row is None:
                return self._lifecycle_projection(None)
            if row["persistence_state"] == "completed":
                return self._lifecycle_projection(row)
            self._set_builder_lifecycle(conn, project_id, "saved_draft", source="owner_save_draft")
            return self._lifecycle_projection(self._builder_lifecycle_row(conn, project_id))

    def mark_builder_completed(self, project_id: str, *, source: str = "character_build_completed") -> dict[str, Any]:
        with self.db.transaction() as conn:
            exists = conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not exists:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            row = self._builder_lifecycle_row(conn, project_id)
            if row is not None:
                self._set_builder_lifecycle(conn, project_id, "completed", source=source)
            return self._lifecycle_projection(self._builder_lifecycle_row(conn, project_id))

    def discard_temporary_project(self, project_id: str, *, reason: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._builder_lifecycle_row(conn, project_id)
            if row is None or row["persistence_state"] != "temporary":
                raise FoundryError(
                    "CHARACTER_BUILDER_PROJECT_NOT_TEMPORARY",
                    "Only the current temporary character can be discarded by the guided builder.",
                    details={"project_id": project_id},
                    status_code=409,
                )
            active_run = conn.execute(
                "SELECT run_id,status FROM character_creation_runs WHERE project_id=? AND status IN ('PREPARING_REQUEST','WAITING_FOR_RESPONSE','READY_FOR_REVIEW','NEEDS_REVIEW') ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if active_run:
                raise FoundryError(
                    "CHARACTER_BUILDER_ACTIVE_RUN_REQUIRES_OWNER_DECISION",
                    "This temporary character has an incomplete build. Resume it or explicitly cancel the build before starting over.",
                    details={"project_id": project_id, "run_id": active_run["run_id"], "status": active_run["status"]},
                    status_code=409,
                )
            # HF2 snapshot rows are immutable by default. This one-transaction
            # authorization is created only after the explicit temporary marker
            # is verified. Triggers still reject every other deletion path.
            conn.execute(
                "INSERT INTO character_builder_temporary_delete_authorizations(project_id,reason,authorized_at) VALUES(?,?,?)",
                (project_id, reason, utcnow()),
            )
            # The optional provider run table intentionally uses RESTRICT. Remove
            # only rows belonging to this exact temporary project before the
            # project-scoped CASCADE. No unrelated project or owner data is touched.
            conn.execute("DELETE FROM ai_provider_runs WHERE project_id=?", (project_id,))
            deleted = conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,)).rowcount
            if deleted != 1:
                raise FoundryError(
                    "CHARACTER_BUILDER_TEMPORARY_DELETE_FAILED",
                    "The temporary character could not be removed safely.",
                    details={"project_id": project_id, "reason": reason},
                    status_code=500,
                )
            conn.execute("DELETE FROM character_builder_temporary_delete_authorizations WHERE project_id=?", (project_id,))
        return {"project_id": project_id, "discarded": True, "reason": reason}

    def cleanup_temporary_projects(self, *, reason: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            project_ids = [
                row[0] for row in conn.execute(
                    "SELECT project_id FROM character_builder_project_lifecycle WHERE persistence_state='temporary' ORDER BY project_id"
                )
            ]
            skipped_project_ids = []
            for project_id in project_ids:
                active_run = conn.execute(
                    "SELECT run_id FROM character_creation_runs WHERE project_id=? AND status IN ('PREPARING_REQUEST','WAITING_FOR_RESPONSE','READY_FOR_REVIEW','NEEDS_REVIEW') LIMIT 1",
                    (project_id,),
                ).fetchone()
                if active_run:
                    skipped_project_ids.append(project_id)
                    continue
                conn.execute(
                    "INSERT INTO character_builder_temporary_delete_authorizations(project_id,reason,authorized_at) VALUES(?,?,?)",
                    (project_id, reason, utcnow()),
                )
                conn.execute("DELETE FROM ai_provider_runs WHERE project_id=?", (project_id,))
                deleted = conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,)).rowcount
                if deleted != 1:
                    raise FoundryError(
                        "CHARACTER_BUILDER_TEMPORARY_CLEANUP_FAILED",
                        "Abandoned temporary characters could not be cleaned safely.",
                        details={"project_id": project_id, "reason": reason},
                        status_code=500,
                    )
                conn.execute("DELETE FROM character_builder_temporary_delete_authorizations WHERE project_id=?", (project_id,))
        removed_project_ids = [project_id for project_id in project_ids if project_id not in skipped_project_ids]
        return {"reason": reason, "removed_project_ids": removed_project_ids, "removed_count": len(removed_project_ids), "skipped_active_project_ids": skipped_project_ids}

    def _record_validation(
        self,
        conn,
        *,
        family: str,
        key: str,
        version: str,
        boundary: str,
        valid: bool,
        diagnostics: list[dict[str, Any]],
        object_hash: str | None,
    ) -> None:
        conn.execute(
            """INSERT INTO canonical_object_validations(
                object_family,object_key,schema_version,boundary,valid,diagnostics_json,object_hash,validated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (family, key, version, boundary, 1 if valid else 0, canonical_json(diagnostics), object_hash, utcnow()),
        )

    def _validate_or_raise(self, obj: dict[str, Any], *, boundary: str, family: str, key: str, conn=None) -> None:
        report = self.registry.report(obj)
        if conn is not None:
            self._record_validation(
                conn,
                family=family,
                key=key,
                version=report["schema_version"],
                boundary=boundary,
                valid=report["valid"],
                diagnostics=report["diagnostics"],
                object_hash=sha256_json(obj),
            )
        if not report["valid"]:
            raise FoundryError(
                "CANONICAL_SCHEMA_VALIDATION_FAILED",
                f"{family} failed canonical validation at {boundary}.",
                details={"schema_version": report["schema_version"], "diagnostics": report["diagnostics"]},
            )

    def _latest_build_id(self, conn) -> str:
        row = conn.execute("SELECT build_id FROM catalog_builds ORDER BY created_at DESC LIMIT 1").fetchone()
        return row[0] if row else "catalog.unbuilt"

    def _project_locks(self, conn, project_id: str) -> list[dict[str, Any]]:
        return [
            {
                "pack_id": r["pack_id"],
                "version": r["version"],
                "pack_hash": r["pack_hash"],
                "record_set_hash": r["record_set_hash"],
                "payload_files_hash": r["payload_files_hash"],
                "install_receipt_hash": r["install_receipt_hash"],
                "membership_snapshot_hash": r["membership_snapshot_hash"],
                "locked_at": r["locked_at"],
            }
            for r in conn.execute(
                """SELECT pack_id,version,pack_hash,record_set_hash,payload_files_hash,
                          install_receipt_hash,membership_snapshot_hash,locked_at
                   FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version""",
                (project_id,),
            )
        ]

    def _snapshot_pack_seals(self, conn, project_id: str, seals: list[PackSeal], *, locked_at: str) -> None:
        member_by_id: dict[str, dict[str, Any]] = {}
        locked_pack_keys = {(seal.pack_id, seal.version, seal.pack_hash) for seal in seals}
        for seal in sorted(seals, key=lambda item: (item.pack_id, item.version)):
            conn.execute(
                """INSERT INTO project_content_locks(
                   project_id,pack_id,version,pack_hash,record_set_hash,payload_files_hash,
                   install_receipt_hash,membership_snapshot_hash,locked_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    project_id, seal.pack_id, seal.version, seal.pack_hash,
                    seal.record_set_hash, seal.payload_files_hash, seal.install_receipt_hash,
                    seal.membership_snapshot_hash, locked_at,
                ),
            )
            for member in seal.records:
                prior = member_by_id.get(member["record_id"])
                if prior and (prior["record_hash"] != member["record_hash"] or prior["record_json"] != member["record_json"]):
                    raise FoundryError(
                        "PROJECT_LOCK_RECORD_ID_CONFLICT",
                        "Two locked packs bind the same stable record ID to different immutable bytes.",
                        details={"record_id": member["record_id"]},
                    )
                member_by_id[member["record_id"]] = member
        conn.executemany(
            """INSERT INTO project_locked_records(
               project_id,record_id,pack_id,pack_version,record_hash,record_json)
               VALUES(?,?,?,?,?,?)""",
            [
                (project_id, record_id, member["pack_id"], member["pack_version"], member["record_hash"], member["record_json"])
                for record_id, member in sorted(member_by_id.items())
            ],
        )

        for row in conn.execute(
            "SELECT * FROM catalog_record_replacements ORDER BY replacement_pack_id,replacement_pack_version,replacement_id"
        ).fetchall():
            replacement_key = (row["replacement_pack_id"], row["replacement_pack_version"], row["replacement_pack_hash"])
            if replacement_key not in locked_pack_keys:
                continue
            source = member_by_id.get(row["source_record_id"])
            target = member_by_id.get(row["target_record_id"])
            if (
                not source or not target
                or source["record_hash"] != row["source_record_hash"]
                or source["pack_id"] != row["source_pack_id"]
                or source["pack_version"] != row["source_pack_version"]
                or target["record_hash"] != row["target_record_hash"]
                or target["pack_id"] != row["replacement_pack_id"]
                or target["pack_version"] != row["replacement_pack_version"]
            ):
                raise FoundryError(
                    "PROJECT_LOCK_REPLACEMENT_BINDING_INVALID",
                    "A replacement map does not resolve entirely inside the exact immutable project record set.",
                    details={"replacement_id": row["replacement_id"]},
                )
            conn.execute(
                """INSERT INTO project_locked_replacements(
                   project_id,replacement_id,replacement_pack_id,replacement_pack_version,replacement_pack_hash,
                   source_record_id,source_record_hash,source_pack_id,source_pack_version,source_pack_hash,
                   target_record_id,target_record_hash,mode,reason,map_path,map_hash)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id,row["replacement_id"],row["replacement_pack_id"],row["replacement_pack_version"],row["replacement_pack_hash"],
                    row["source_record_id"],row["source_record_hash"],row["source_pack_id"],row["source_pack_version"],row["source_pack_hash"],
                    row["target_record_id"],row["target_record_hash"],row["mode"],row["reason"],row["map_path"],row["map_hash"],
                ),
            )

    def project_lock_proof(self, conn, project_id: str) -> dict[str, Any]:
        locks = self._project_locks(conn, project_id)
        if not locks:
            raise FoundryError(
                "LEGACY_PROJECT_LOCK_MEMBERSHIP_UNPROVEN",
                "The project has no immutable HF2 content locks.",
                details={"project_id": project_id},
                status_code=409,
            )
        expected_members: dict[str, dict[str, Any]] = {}
        proof_locks: list[dict[str, Any]] = []
        for lock in locks:
            required = ("record_set_hash", "payload_files_hash", "install_receipt_hash", "membership_snapshot_hash")
            if not all(lock.get(field) for field in required):
                raise FoundryError(
                    "LEGACY_PROJECT_LOCK_MEMBERSHIP_UNPROVEN",
                    "A legacy project content lock lacks the immutable HF2 membership bindings required for writes.",
                    details={"project_id": project_id, "pack_id": lock["pack_id"], "version": lock["version"]},
                    status_code=409,
                )
            seal = verify_pack_seal(
                conn, pack_id=lock["pack_id"], version=lock["version"], expected_pack_hash=lock["pack_hash"],
                integrity=self.integrity,
            )
            for field in required:
                if lock[field] != getattr(seal, field):
                    raise FoundryError(
                        "PROJECT_LOCK_PROOF_MISMATCH",
                        "A project lock no longer reproduces its immutable pack membership proof.",
                        details={"project_id": project_id, "pack_id": lock["pack_id"], "field": field},
                    )
            proof_locks.append(seal.lock_row())
            for member in seal.records:
                prior = expected_members.get(member["record_id"])
                if prior and (prior["record_hash"] != member["record_hash"] or prior["record_json"] != member["record_json"]):
                    raise FoundryError(
                        "PROJECT_LOCK_RECORD_ID_CONFLICT",
                        "The exact locked pack set contains conflicting bytes for one stable record ID.",
                        details={"record_id": member["record_id"]},
                    )
                expected_members[member["record_id"]] = member
        actual_rows = {
            row["record_id"]: dict(row)
            for row in conn.execute(
                """SELECT record_id,pack_id,pack_version,record_hash,record_json
                   FROM project_locked_records WHERE project_id=? ORDER BY record_id""",
                (project_id,),
            )
        }
        if set(actual_rows) != set(expected_members):
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_INCOMPLETE",
                "The project record snapshot is not the complete immutable membership of its locked pack set.",
                details={
                    "project_id": project_id,
                    "missing": sorted(set(expected_members) - set(actual_rows)),
                    "extra": sorted(set(actual_rows) - set(expected_members)),
                },
            )
        snapshot_rows: list[dict[str, str]] = []
        for record_id, expected in sorted(expected_members.items()):
            actual = actual_rows[record_id]
            if (
                actual["pack_id"] != expected["pack_id"]
                or actual["pack_version"] != expected["pack_version"]
                or actual["record_hash"] != expected["record_hash"]
                or actual["record_json"] != expected["record_json"]
            ):
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "A project record snapshot diverges from its exact immutable pack membership.",
                    details={"project_id": project_id, "record_id": record_id},
                )
            snapshot_rows.append({
                "record_id": record_id,
                "record_hash": actual["record_hash"],
                "pack_id": actual["pack_id"],
                "pack_version": actual["pack_version"],
            })
        replacements = [
            dict(row)
            for row in conn.execute(
                """SELECT replacement_id,replacement_pack_id,replacement_pack_version,replacement_pack_hash,
                          source_record_id,source_record_hash,source_pack_id,source_pack_version,source_pack_hash,
                          target_record_id,target_record_hash,mode,reason,map_path,map_hash
                   FROM project_locked_replacements WHERE project_id=? ORDER BY replacement_id""",
                (project_id,),
            )
        ]
        proof = {
            "schema_version": "TianxiaFoundry.ProjectLockProof.v1",
            "project_id": project_id,
            "locks": sorted(proof_locks, key=lambda row: (row["pack_id"], row["version"])),
            "record_snapshot_hash": sha256_json(snapshot_rows),
            "replacement_snapshot_hash": sha256_json(replacements),
        }
        return {**proof, "lock_proof_hash": sha256_json(proof)}

    def _assert_snapshot_record(self, conn, project_id: str, record: dict[str, Any]) -> None:
        if record.get("content_binding", {}).get("pack_id") == "tianxia.non_sphere.authority" or str(record.get("record_id") or "").startswith("tianxia.background_"):
            fallback = self._resolve_project_locked_authority_projection_after_proof(conn, project_id, record["record_id"])
            if fallback and canonical_json(fallback) == canonical_json(record):
                return
        row = conn.execute(
            "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record["record_id"]),
        ).fetchone()
        binding = record["content_binding"]
        if row:
            valid = (
                row["pack_id"] == binding["pack_id"]
                and row["pack_version"] == binding["pack_version"]
                and row["record_hash"] == record["record_hash"]
                and row["record_json"] == canonical_json(record)
            )
        else:
            # Exact initial Methods may be authenticated by the non-sphere
            # registry rather than by ordinary HF2 pack membership.  Rebuild the
            # same deterministic projection and compare the complete bytes.
            fallback = self._resolve_project_locked_non_sphere_after_proof(conn, project_id, record["record_id"])
            valid = bool(fallback and canonical_json(fallback) == canonical_json(record))
        if not valid:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "A committed event references bytes outside the immutable project record snapshot.",
                details={"project_id": project_id, "record_id": record["record_id"]},
            )

    def _reconstruct_project(self, conn, project_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
        project = json.loads(row["project_json"])
        # Reconstruction validates persisted bytes, not merely the schema document.
        self._validate_or_raise(project, boundary="project_reconstruct", family="character_project", key=project_id, conn=conn)
        return project

    def create_project(
        self,
        *,
        working_name: str,
        pack_locks: list[dict[str, str]],
        quality_target: str = "rival/boss",
        user_locks: list[dict[str, Any]] | None = None,
        source_evidence: list[dict[str, Any]] | None = None,
        builder_persistence_state: str | None = None,
        project_id_override: str | None = None,
    ) -> dict[str, Any]:
        if project_id_override is None:
            project_id = str(uuid.uuid4())
        else:
            try:
                project_id = str(uuid.UUID(str(project_id_override)))
            except (TypeError, ValueError, AttributeError) as exc:
                raise FoundryError(
                    "PROJECT_ID_OVERRIDE_INVALID",
                    "A fixture project ID override must be a canonical UUID.",
                ) from exc
            if project_id != str(project_id_override):
                raise FoundryError(
                    "PROJECT_ID_OVERRIDE_INVALID",
                    "A fixture project ID override must use canonical lowercase UUID form.",
                )
        now = utcnow()
        with self.db.transaction() as conn:
            seals: list[PackSeal] = []
            resolved: list[dict[str, str]] = []
            for lock in pack_locks:
                seal = verify_pack_seal(
                    conn,
                    pack_id=lock["pack_id"],
                    version=lock["version"],
                    expected_pack_hash=lock.get("pack_hash") or lock.get("content_hash"),
                    integrity=self.integrity,
                )
                seals.append(seal)
                resolved.append({"pack_id": seal.pack_id, "version": seal.version, "pack_hash": seal.pack_hash})
            CatalogService.validate_project_lock_set(conn, resolved)
            build_id = self._latest_build_id(conn)
            project = canonical_project_document(
                project_id=project_id,
                name=working_name,
                revision=0,
                status="draft",
                created_at=now,
                updated_at=now,
                catalog_build_id=build_id,
                pack_locks=resolved,
                user_locks=user_locks,
                source_inputs=source_evidence,
                event_count=0,
                head_hash=None,
            )
            self._validate_or_raise(project, boundary="project_create", family="character_project", key=project_id, conn=conn)
            project_hash = canonical_project_hash(project)
            conn.execute(
                """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,target_factory_version,
                target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,quality_target,project_json,
                compatibility_projection_status,compile_status,consumer_verification_status,canonical_project_hash,
                canonical_schema_version,contract_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id, working_name, project["status"], 0, now, now,
                    project["factory_target"]["producer"], project["factory_target"]["candidate_schema"],
                    project["gm_screen_target"]["consumer"], build_id, quality_target, canonical_json(project),
                    "DRAFT_COMPATIBILITY_PROJECTION_NOT_FACTORY_COMPILABLE", "NOT_IMPLEMENTED_PHASE2R",
                    "NOT_RUN_NO_COMPILED_CHARACTER", project_hash, project["schema_version"], "valid",
                ),
            )
            self._snapshot_pack_seals(conn, project_id, seals, locked_at=now)
            if builder_persistence_state is not None:
                self._set_builder_lifecycle(
                    conn, project_id, builder_persistence_state, source="guided_builder_create"
                )
            self.project_lock_proof(conn, project_id)
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT p.project_id,p.working_name,p.status,p.revision,p.created_at,p.updated_at,
                          p.compatibility_projection_status,p.compile_status,p.consumer_verification_status,p.contract_status,
                          l.persistence_state AS builder_persistence_state,l.lifecycle_source,l.created_at AS lifecycle_created_at,l.updated_at AS lifecycle_updated_at
                   FROM projects p LEFT JOIN character_builder_project_lifecycle l ON l.project_id=p.project_id
                   ORDER BY p.updated_at DESC"""
            )]
            for row in rows:
                lifecycle_row = None
                if row.get("builder_persistence_state"):
                    lifecycle_row = {
                        "persistence_state": row["builder_persistence_state"],
                        "lifecycle_source": row.pop("lifecycle_source"),
                        "created_at": row.pop("lifecycle_created_at"),
                        "updated_at": row.pop("lifecycle_updated_at"),
                    }
                else:
                    row.pop("lifecycle_source", None); row.pop("lifecycle_created_at", None); row.pop("lifecycle_updated_at", None)
                lifecycle = self._lifecycle_projection(lifecycle_row)
                row["builder_lifecycle"] = lifecycle
                row["builder_persistence_state"] = lifecycle["persistence_state"]
            return rows

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            result = dict(row)
            project = json.loads(result.pop("project_json"))
            self._validate_or_raise(project, boundary="project_get", family="character_project", key=project_id, conn=conn)
            result["project"] = project
            result["content_locks"] = self._project_locks(conn, project_id)
            result["builder_lifecycle"] = self._lifecycle_projection(self._builder_lifecycle_row(conn, project_id))
            result["builder_persistence_state"] = result["builder_lifecycle"]["persistence_state"]
            result["event_count"] = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
            result["draft_event_count"] = conn.execute("SELECT COUNT(*) FROM draft_events WHERE project_id=?", (project_id,)).fetchone()[0]
            return result

    def append_user_locks(
        self,
        project_id: str,
        locks: list[dict[str, Any]],
        *,
        _require_unstarted_character_creation: bool = False,
    ) -> dict[str, Any]:
        """Append immutable Stage 1 user locks before a prompt is generated.

        Existing locks are never edited or removed. A new prompt must be generated after
        this operation because the canonical project revision changes.
        """
        if not locks:
            raise FoundryError("USER_LOCKS_REQUIRED", "At least one user lock is required.")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            prompt_count = conn.execute("SELECT COUNT(*) FROM stage1_prompt_exchanges WHERE project_id=?", (project_id,)).fetchone()[0]
            if prompt_count:
                raise FoundryError("USER_LOCKS_ALREADY_ENVELOPED", "User locks cannot be changed after a Stage 1 prompt has been generated. Create a new project or retain the existing prompt audit trail.")
            if _require_unstarted_character_creation:
                event_count = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
                run_count = conn.execute(
                    "SELECT COUNT(*) FROM character_creation_runs WHERE project_id=?", (project_id,),
                ).fetchone()[0]
                if event_count or run_count:
                    raise FoundryError(
                        "CATALOG_CHOICE_LOCK_CREATION_ALREADY_STARTED",
                        "Canonical catalog choices must be frozen before any creation run or advancement event exists.",
                        details={"event_count": event_count, "creation_run_count": run_count},
                        status_code=409,
                    )
            old = json.loads(row["project_json"])
            existing = list(old.get("user_locks") or [])
            existing_ids = {x.get("lock_id") for x in existing}
            existing_fields = {x.get("field") for x in existing}
            new_revision = int(row["revision"]) + 1
            additions: list[dict[str, Any]] = []
            for index, item in enumerate(locks, start=1):
                if not isinstance(item, dict) or not isinstance(item.get("field"), str) or not item["field"].strip():
                    raise FoundryError("USER_LOCK_INVALID", "Each user lock requires a non-empty field.", details={"index": index - 1, "pointer": f"/locks/{index-1}/field"})
                lock_id = str(item.get("lock_id") or f"lock.stage1.{new_revision}.{index}")
                if lock_id in existing_ids:
                    raise FoundryError("USER_LOCK_ID_DUPLICATE", "A lock with that immutable ID already exists.", details={"lock_id": lock_id})
                if item["field"] in existing_fields:
                    raise FoundryError("USER_LOCK_FIELD_IMMUTABLE", "An existing immutable lock already controls that field.", details={"field": item["field"]})
                additions.append({"lock_id": lock_id, "field": item["field"], "value": item.get("value"), "created_revision": new_revision, "source": str(item.get("source") or "local-user")})
                existing_ids.add(lock_id); existing_fields.add(item["field"])
            updated = canonical_project_document(
                project_id=project_id, name=old["name"], revision=new_revision, status="stage_1",
                created_at=old["created_at"], updated_at=utcnow(), catalog_build_id=old["content_lock"]["catalog_build_id"],
                pack_locks=self._project_locks(conn, project_id), user_locks=existing + additions, source_inputs=old["source_inputs"],
                event_count=old["event_stream"]["count"], head_hash=old["event_stream"].get("head_hash"), active_stage=1,
                stage_commits=old["stage_commits"], generated_artifacts=old["generated_artifacts"], candidates=old["candidates"], acceptance=old["acceptance"],
            )
            self._validate_or_raise(updated, boundary="stage1_user_lock_append", family="character_project", key=project_id, conn=conn)
            conn.execute("UPDATE projects SET working_name=?,status=?,revision=?,updated_at=?,project_json=?,canonical_project_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=?",
                         (updated["name"], updated["status"], new_revision, updated["updated_at"], canonical_json(updated), canonical_project_hash(updated), updated["schema_version"], project_id))
        return self.get_project(project_id)

    def materialize_server_derived_user_lock(
        self,
        project_id: str,
        *,
        field: str,
        value: Any,
        source: str,
        lock_id: str,
    ) -> dict[str, Any]:
        """Materialize a server-derived acceptance artifact without changing owner revision.

        This is intentionally separate from ``append_user_locks``.  The
        delegated final grant plan is derived only after response validation,
        may be installed in an isolated scratch database, and is installed in
        the live project only inside Finalize's atomic precommit boundary.  It
        is not a new owner choice and therefore does not invalidate the
        revision-bound Stage 1 prompt or typed owner-choice snapshot.
        """
        if not isinstance(field, str) or not field.strip():
            raise FoundryError("SERVER_DERIVED_LOCK_INVALID", "A server-derived lock requires a non-empty field.")
        if not isinstance(lock_id, str) or not lock_id.strip():
            raise FoundryError("SERVER_DERIVED_LOCK_INVALID", "A server-derived lock requires a stable lock ID.")
        already_materialized = False
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            old = json.loads(row["project_json"])
            existing = [item for item in old.get("user_locks") or [] if isinstance(item, dict)]
            prior = next((item for item in existing if item.get("field") == field), None)
            if prior is not None:
                if prior.get("value") != value:
                    raise FoundryError(
                        "CG1_DELEGATED_FINAL_GRANT_PLAN_IMMUTABLE",
                        "A different server-derived delegated grant plan is already materialized for this project.",
                        details={"field": field, "lock_id": prior.get("lock_id")},
                        status_code=409,
                    )
                already_materialized = True
            if already_materialized:
                pass
            elif any(item.get("lock_id") == lock_id for item in existing):
                raise FoundryError(
                    "SERVER_DERIVED_LOCK_ID_DUPLICATE",
                    "The stable server-derived lock ID is already used by another project lock.",
                    details={"lock_id": lock_id},
                    status_code=409,
                )
            else:
                revision = int(row["revision"])
                additions = [
                    *existing,
                    {
                        "lock_id": lock_id,
                        "field": field,
                        "value": deepcopy(value),
                        "created_revision": revision,
                        "source": str(source or "server-derived"),
                    },
                ]
                now = utcnow()
                updated = canonical_project_document(
                    project_id=project_id,
                    name=old["name"],
                    revision=revision,
                    status=old["status"],
                    created_at=old["created_at"],
                    updated_at=now,
                    catalog_build_id=old["content_lock"]["catalog_build_id"],
                    pack_locks=self._project_locks(conn, project_id),
                    user_locks=additions,
                    source_inputs=old["source_inputs"],
                    event_count=old["event_stream"]["count"],
                    head_hash=old["event_stream"].get("head_hash"),
                    active_stage=old.get("active_stage"),
                    stage_commits=old["stage_commits"],
                    generated_artifacts=old["generated_artifacts"],
                    candidates=old["candidates"],
                    acceptance=old["acceptance"],
                )
                self._validate_or_raise(updated, boundary="server_derived_lock_materialization", family="character_project", key=project_id, conn=conn)
                conn.execute(
                    "UPDATE projects SET working_name=?,status=?,revision=?,updated_at=?,project_json=?,canonical_project_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=?",
                    (
                        updated["name"], updated["status"], revision, updated["updated_at"],
                        canonical_json(updated), canonical_project_hash(updated), updated["schema_version"], project_id,
                    ),
                )
        return self.get_project(project_id)

    def append_owner_fixture_locks(self, project_id: str, *, fixture_contract: Path) -> dict[str, Any]:
        """Append the explicit owner-approved C2A-R.1 fixture choices.

        This is a bounded canonical project-lock operation, not a product default.
        It preserves the committed event stream and may run only when the project
        matches the contract's immutable historical prefix.
        """
        contract_path = Path(fixture_contract).resolve()
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FoundryError("OWNER_FIXTURE_CONTRACT_INVALID", "The owner fixture-selection contract is unreadable.", details={"path": str(contract_path), "error": str(exc)}) from exc
        supplied_seal = contract.get("seal_sha256")
        unsigned = {key: value for key, value in contract.items() if key != "seal_sha256"}
        if supplied_seal != sha256_json(unsigned):
            raise FoundryError("OWNER_FIXTURE_CONTRACT_HASH_MISMATCH", "The owner fixture-selection contract seal does not match its canonical bytes.")
        if contract.get("schema_version") != "TianxiaFoundry.OwnerFixtureSelections.v1" or contract.get("product_default") is not False:
            raise FoundryError("OWNER_FIXTURE_CONTRACT_INVALID", "Only a sealed non-default owner fixture-selection contract is accepted.")
        selections = contract.get("selections") or {}
        allowed = contract.get("allowed_sets") or {}
        skills = selections.get("qi_cultivation_skills")
        street = selections.get("street_hardened")
        language = selections.get("language")
        if not isinstance(skills, list) or len(skills) != 2 or len(set(skills)) != 2 or any(x not in allowed.get("qi_cultivation_skills", []) for x in skills):
            raise FoundryError("OWNER_FIXTURE_QI_SKILLS_INVALID", "Exactly two distinct authenticated Qi Cultivation skill options are required.")
        if street not in allowed.get("street_hardened", []):
            raise FoundryError("OWNER_FIXTURE_STREET_HARDENED_INVALID", "The Street-Hardened choice is outside the sealed legal set.")
        if language not in allowed.get("languages", []):
            raise FoundryError("OWNER_FIXTURE_LANGUAGE_INVALID", "The language choice is outside the sealed campaign binding.")
        if selections.get("title") is not None:
            raise FoundryError("OWNER_FIXTURE_TITLE_FABRICATION", "The approved fixture omits its optional title.")
        display_name = selections.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            raise FoundryError("OWNER_FIXTURE_DISPLAY_NAME_INVALID", "The fixture display name must be explicit and non-empty.")
        prefix = contract.get("required_prefix") or {}
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            old = json.loads(row["project_json"])
            count = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
            head = conn.execute("SELECT event_hash FROM events WHERE project_id=? ORDER BY sequence_no DESC LIMIT 1", (project_id,)).fetchone()
            actual_head = head[0] if head else ZERO_HASH
            if int(row["revision"]) != int(prefix.get("revision", -1)) or count != int(prefix.get("event_count", -1)) or actual_head != prefix.get("event_head"):
                raise FoundryError("OWNER_FIXTURE_PREFIX_MISMATCH", "The project does not match the sealed immutable prefix required by this fixture contract.", details={"revision": row["revision"], "event_count": count, "event_head": actual_head})
            if old.get("active_stage") != 2:
                raise FoundryError("OWNER_FIXTURE_STAGE_INVALID", "C2A-R.1 fixture locks require a sealed Stage 2 project.")
            lock_fields = {
                "character.identity.display_name": display_name,
                "character.choices.qi_cultivation_skills": list(skills),
                "character.choices.street_hardened": street,
                "character.choices.language": language,
            }
            existing = list(old.get("user_locks") or [])
            existing_fields = {x.get("field") for x in existing}
            collision = sorted(set(lock_fields) & existing_fields)
            if collision:
                raise FoundryError("OWNER_FIXTURE_LOCK_ALREADY_APPLIED", "One or more owner fixture locks already exist.", details={"fields": collision})
            new_revision = int(row["revision"]) + 1
            contract_sha256 = sha256_file(contract_path)
            additions = [
                {"lock_id": f"lock.c2ar1.{index}", "field": field, "value": value, "created_revision": new_revision, "source": f"owner-ratified:{contract['fixture_id']}:{contract_sha256}"}
                for index, (field, value) in enumerate(lock_fields.items(), start=1)
            ]
            updated = canonical_project_document(
                project_id=project_id, name=display_name, revision=new_revision, status=old["status"],
                created_at=old["created_at"], updated_at=utcnow(), catalog_build_id=old["content_lock"]["catalog_build_id"],
                pack_locks=self._project_locks(conn, project_id), user_locks=existing + additions, source_inputs=old["source_inputs"],
                event_count=old["event_stream"]["count"], head_hash=old["event_stream"].get("head_hash"), active_stage=old.get("active_stage"),
                stage_commits=old["stage_commits"], generated_artifacts=old["generated_artifacts"], candidates=old["candidates"], acceptance=old["acceptance"],
            )
            self._validate_or_raise(updated, boundary="owner_fixture_lock_append", family="character_project", key=project_id, conn=conn)
            conn.execute("UPDATE projects SET working_name=?,revision=?,updated_at=?,project_json=?,canonical_project_hash=?,contract_status='valid' WHERE project_id=?",
                         (updated["name"], new_revision, updated["updated_at"], canonical_json(updated), canonical_project_hash(updated), project_id))
        return self.get_project(project_id)

    def record_stage_commit(self, project_id: str, *, prompt_id: str, response_id: str, event_ids: list[str], state_hash: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            old = json.loads(row["project_json"])
            if any(prompt_id in (x.get("prompt_packet_ids") or []) for x in old.get("stage_commits", [])):
                return old
            commits = list(old.get("stage_commits") or [])
            commits.append({"stage": 1, "revision": int(row["revision"]), "status": "sealed", "state_hash": state_hash, "prompt_packet_ids": [prompt_id], "response_ids": [response_id], "event_ids": list(event_ids)})
            updated = canonical_project_document(
                project_id=project_id, name=old["name"], revision=int(row["revision"]), status="stage_1",
                created_at=old["created_at"], updated_at=utcnow(), catalog_build_id=old["content_lock"]["catalog_build_id"],
                pack_locks=self._project_locks(conn, project_id), user_locks=old["user_locks"], source_inputs=old["source_inputs"],
                event_count=old["event_stream"]["count"], head_hash=old["event_stream"].get("head_hash"), active_stage=1,
                stage_commits=commits, generated_artifacts=old["generated_artifacts"], candidates=old["candidates"], acceptance=old["acceptance"],
            )
            self._validate_or_raise(updated, boundary="stage1_commit_record", family="character_project", key=project_id, conn=conn)
            conn.execute("UPDATE projects SET status=?,updated_at=?,project_json=?,canonical_project_hash=? WHERE project_id=?",
                         (updated["status"], updated["updated_at"], canonical_json(updated), canonical_project_hash(updated), project_id))
            return updated

    def _resolve_locked_record(self, conn, project_id: str, record_id: str, *, lock_proof_verified: bool = False) -> dict[str, Any] | None:
        # Live catalog rows are discovery/read-model projections only.  HF2
        # authority resolution is strictly from the complete immutable project
        # snapshot proved against receipt-backed pack membership.
        locks = self._project_locks(conn, project_id)
        required = ("record_set_hash", "payload_files_hash", "install_receipt_hash", "membership_snapshot_hash")
        if not lock_proof_verified and locks and all(all(lock.get(field) for field in required) for lock in locks):
            self.project_lock_proof(conn, project_id)
        return self._resolve_locked_record_after_proof(conn, project_id, record_id)

    def _resolve_locked_record_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        """Resolve one immutable snapshot record after the caller proved the full lock once."""
        # Legacy projects remain readable from already-persisted snapshots, but
        # no live-catalog fallback is permitted. Mutation boundaries must call
        # project_lock_proof() before using this bounded resolver.
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if not row:
            return self._resolve_project_locked_authority_projection_after_proof(conn, project_id, record_id)
        record = json.loads(row["record_json"])
        if canonical_json(record) != row["record_json"] or record.get("record_hash") != row["record_hash"]:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "The immutable project snapshot record bytes do not match their stored hash binding.",
                details={"project_id": project_id, "record_id": record_id},
            )
        self._validate_or_raise(record, boundary="locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        if record_id.startswith("tianxia.path.") and not record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("authority_complete"):
            fallback = self._resolve_project_locked_path_after_proof(conn, project_id, record_id)
            if fallback is not None:
                return fallback
        if record_id.startswith("tianxia.background_") and not record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("authority_complete"):
            fallback = self._resolve_project_locked_background_after_proof(conn, project_id, record_id)
            if fallback is not None:
                return fallback
        return record

    def _resolve_project_locked_authority_projection_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        return (
            self._resolve_project_locked_non_sphere_after_proof(conn, project_id, record_id)
            or self._resolve_project_locked_background_after_proof(conn, project_id, record_id)
        )

    def _resolve_project_locked_non_sphere_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        return (
            self._resolve_project_locked_method_after_proof(conn, project_id, record_id)
            or self._resolve_project_locked_path_after_proof(conn, project_id, record_id)
        )

    def _resolve_project_locked_background_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        """Attach typed C1A authority to the owner-facing Background projections.

        The Background supplement intentionally owns the stable creator-facing
        IDs, while the typed C1A sphere/talent rows own the executable Stage 2
        rules.  Rebuild the alias only from the complete immutable project
        snapshot; never consult the live catalog for this authority boundary.
        """
        if not isinstance(record_id, str) or not record_id.startswith("tianxia.background_"):
            return None
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if not row:
            return None
        record = json.loads(row["record_json"])
        if canonical_json(record) != row["record_json"] or record.get("record_hash") != row["record_hash"]:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "The immutable Background snapshot record bytes do not match their stored hash binding.",
                details={"project_id": project_id, "record_id": record_id},
            )
        self._validate_or_raise(record, boundary="background_locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        existing = record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {})
        if existing.get("authority_complete"):
            return record

        def snapshot_record_for(snapshot_record_id: str) -> dict[str, Any] | None:
            candidate = conn.execute(
                "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                (project_id, snapshot_record_id),
            ).fetchone()
            if not candidate:
                return None
            value = json.loads(candidate["record_json"])
            if canonical_json(value) != candidate["record_json"] or value.get("record_hash") != candidate["record_hash"]:
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "A typed Background authority record diverges from its immutable snapshot binding.",
                    details={"project_id": project_id, "record_id": snapshot_record_id},
                )
            self._validate_or_raise(value, boundary="background_typed_authority_reconstruct", family="rules_catalog_record", key=snapshot_record_id, conn=conn)
            authority = value.get("compatibility", {}).get("factory", {}).get("stage2_authority")
            return value if isinstance(authority, dict) and authority.get("authority_complete") else None

        authority_record: dict[str, Any] | None = None
        if record_id.startswith("tianxia.background_sphere."):
            suffix = record_id.removeprefix("tianxia.background_sphere.")
            authority_record = snapshot_record_for(f"tianxia.sphere.{suffix}")
        elif record_id.startswith("tianxia.background_talent."):
            background_sphere_id = (record.get("dependencies") or [None])[0]
            canonical_sphere_id = (
                f"tianxia.sphere.{background_sphere_id.removeprefix('tianxia.background_sphere.')}"
                if isinstance(background_sphere_id, str) and background_sphere_id.startswith("tianxia.background_sphere.")
                else None
            )
            display_name = str(record.get("display_name") or "")
            display_name = display_name.rsplit("(", 1)[0].strip() if "(" in display_name else display_name.strip()
            folded_name = "".join(character.casefold() for character in display_name if character.isalnum())
            matches: list[dict[str, Any]] = []
            for candidate in conn.execute(
                "SELECT record_id,record_hash,record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                (project_id,),
            ):
                if not candidate["record_id"].startswith(("TAL_", "tianxia.talent.")):
                    continue
                value = json.loads(candidate["record_json"])
                candidate_authority = value.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
                candidate_name = "".join(character.casefold() for character in str(value.get("display_name") or "") if character.isalnum())
                if (
                    value.get("content_type") == "talent"
                    and candidate_authority.get("authority_complete")
                    and "background_talent_acquisition" in candidate_authority.get("allowed_kinds", [])
                    and candidate_authority.get("sphere_id") == canonical_sphere_id
                    and candidate_name == folded_name
                ):
                    matches.append(value)
            if len(matches) == 1:
                authority_record = matches[0]
            elif len(matches) > 1:
                raise FoundryError(
                    "PROJECT_LOCK_BACKGROUND_AUTHORITY_AMBIGUOUS",
                    "The owner-facing Background Talent maps to more than one typed authority record.",
                    details={"project_id": project_id, "record_id": record_id, "matches": [item["record_id"] for item in matches]},
                    status_code=409,
                )
        if not authority_record:
            return None
        return authority_record

    def _resolve_project_locked_method_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        """Resolve an exact Method projection from the immutable access plan.

        This is not a live-catalog lookup.  The project must carry a complete
        server-created MethodAccessPlan whose registry commitment and exact
        method-record hash still match the authenticated non-sphere authority.
        """
        if not isinstance(record_id, str) or not record_id.startswith("METHOD-"):
            return None
        row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            return None
        project = json.loads(row["project_json"])
        locks = {
            item.get("field"): item.get("value")
            for item in project.get("user_locks", [])
            if isinstance(item, dict)
        }
        access_plan = locks.get("character_sheet.method_access_plan")
        if not isinstance(access_plan, dict) or access_plan.get("method_id") != record_id:
            return None
        from non_sphere_authority import NonSphereAuthorityService

        authority = NonSphereAuthorityService(self.db)
        method = authority.methods.get(record_id)
        if method is None:
            return None
        if access_plan.get("schema") != "TianxiaFoundry.MethodAccessPlan.v2":
            return None
        if access_plan.get("method_registry_commitment_sha256") != authority.method_registry_commitment_sha256:
            raise FoundryError(
                "NS1R_METHOD_REGISTRY_COMMITMENT_MISMATCH",
                "The exact Method access plan is not bound to the installed authenticated registry.",
                details={"project_id": project_id, "method_id": record_id},
                status_code=409,
            )
        source_reference = access_plan.get("source_reference")
        if (
            not isinstance(source_reference, dict)
            or source_reference.get("method_record_sha256") != sha256_json(method)
        ):
            raise FoundryError(
                "NS1R_METHOD_RECORD_COMMITMENT_MISMATCH",
                "The exact Method access plan is not bound to the current authenticated Method record.",
                details={"project_id": project_id, "method_id": record_id},
                status_code=409,
            )
        evidence_targets = {
            key: deepcopy(access_plan.get(key))
            for key in (
                "method_id", "access_tier", "route_type", "route_label", "owner_annotation",
                "source_reference", "source_route_sha256", "route_commitment_sha256",
                "method_registry_commitment_sha256",
            )
        }
        authority._validate_authority_targets("method_access", evidence_targets)
        record = authority.project_locked_method_catalog_record(record_id)
        self._validate_or_raise(record, boundary="non_sphere_method_locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        return record

    def _resolve_project_locked_path_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        """Resolve a selected Path from the authenticated non-Sphere index."""
        if not isinstance(record_id, str) or not record_id.startswith("tianxia.path."):
            return None
        row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            return None
        project = json.loads(row["project_json"])
        locks = {
            item.get("field"): item.get("value")
            for item in project.get("user_locks", [])
            if isinstance(item, dict)
        }
        locked_choices = locks.get("character_sheet.locked_choices")
        if not isinstance(locked_choices, dict) or record_id not in (locked_choices.get("path_choice") or []):
            return None
        from non_sphere_authority import NonSphereAuthorityService

        authority = NonSphereAuthorityService(self.db)
        record = authority.project_locked_path_catalog_record(record_id)
        self._validate_or_raise(record, boundary="non_sphere_path_locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        return record

    @staticmethod
    def _reserved_generic_draft_markers(draft: dict[str, Any]) -> list[str]:
        """Identify authority claims that a public/generic caller cannot confer.

        Actor labels, migration channels, and stage markers are data supplied by
        the caller; none is a capability.  Deterministic migrations and stage
        orchestration use their dedicated services and never enter through the
        generic draft mutation boundary.
        """
        markers: list[str] = []
        actor = draft.get("actor_type")
        if actor in RESERVED_GENERIC_DRAFT_ACTORS:
            markers.append(f"reserved_actor:{actor}")
        channel = draft.get("acquisition_channel")
        if channel in RESERVED_GENERIC_DRAFT_CHANNELS:
            markers.append(f"reserved_channel:{channel}")
        if draft.get("planner_response_id"):
            markers.append("planner_response_id")
        payload = draft.get("payload") if isinstance(draft.get("payload"), dict) else {}
        if payload.get("projection_operations") is not None:
            markers.append("payload:projection_operations")
        for key in ("stage_id", "stage_owner"):
            if isinstance(payload.get(key), str) and payload[key]:
                markers.append(f"payload:{key}")
        return markers

    def _reject_reserved_generic_draft(self, draft: dict[str, Any], *, operation: str, draft_id: str | None = None) -> None:
        markers = self._reserved_generic_draft_markers(draft)
        if markers:
            raise FoundryError(
                "GENERIC_DRAFT_RESERVED_AUTHORITY_FORBIDDEN",
                "Generic draft mutations cannot claim planner, stage, system, fixture, or migration authority.",
                details={"operation": operation, "draft_id": draft_id, "markers": markers},
            )

    def append_draft(self, project_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        self._reject_reserved_generic_draft(draft, operation="append_draft")
        self.get_project(project_id)
        draft_id = str(uuid.uuid4())
        now = utcnow()
        internal = {
            "schema_version": "TianxiaFoundry.DraftEventInternal.v1",
            "draft_id": draft_id,
            "event_type": draft.get("event_type"),
            "effective_point": draft.get("effective_point"),
            "actor_type": draft.get("actor_type", "human"),
            "actor_identifier": draft.get("actor_identifier"),
            "content_pack_references": draft.get("content_pack_references", []),
            "stable_rule_ids": draft.get("stable_rule_ids", []),
            "acquisition_channel": draft.get("acquisition_channel"),
            "prerequisite_evidence": draft.get("prerequisite_evidence", []),
            "payload": draft.get("payload", {}),
            "planner_response_id": draft.get("planner_response_id"),
            "approval_state": "draft",
            "superseded_event_reference": draft.get("superseded_event_reference"),
            "rationale": draft.get("rationale", ""),
        }
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO draft_events(draft_id,project_id,created_at,updated_at,status,event_json) VALUES(?,?,?,?,?,?)",
                (draft_id, project_id, now, now, "draft", canonical_json(internal)),
            )
        return {"draft_id": draft_id, "project_id": project_id, "status": "draft", "event": internal}

    def _draft_issues(self, conn, project_id: str, draft: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str], dict[str, Any] | None]:
        issues: list[dict[str, Any]] = []
        event_type = draft.get("event_type")
        if event_type not in ALLOWED_DRAFT_EVENT_TYPES:
            issues.append({"code": "EVENT_TYPE_INVALID", "pointer": "/event_type"})
        if draft.get("actor_type") not in ALLOWED_ACTORS:
            issues.append({"code": "ACTOR_TYPE_INVALID", "pointer": "/actor_type"})
        planner_response_id = draft.get("planner_response_id")
        if planner_response_id is not None:
            planner = conn.execute(
                "SELECT response_id,project_id,project_revision,validation_json FROM ai_stage_responses WHERE response_id=?",
                (planner_response_id,),
            ).fetchone()
            if not planner:
                issues.append({"code": "PLANNER_RESPONSE_NOT_ACCEPTED", "pointer": "/planner_response_id", "response_id": planner_response_id})
            elif planner["project_id"] != project_id:
                issues.append({"code": "PLANNER_RESPONSE_PROJECT_MISMATCH", "pointer": "/planner_response_id", "response_id": planner_response_id})
            elif not json.loads(planner["validation_json"]).get("valid"):
                issues.append({"code": "PLANNER_RESPONSE_INVALID", "pointer": "/planner_response_id", "response_id": planner_response_id})
        stable_ids = draft.get("stable_rule_ids")
        if not isinstance(stable_ids, list) or any(not isinstance(x, str) for x in stable_ids):
            issues.append({"code": "STABLE_RULE_IDS_INVALID", "pointer": "/stable_rule_ids"})
            stable_ids = []
        expected_packs = {(r["pack_id"], r["version"], r["pack_hash"]) for r in conn.execute(
            "SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=?", (project_id,)
        )}
        for index, ref in enumerate(draft.get("content_pack_references", [])):
            if isinstance(ref, dict):
                key = (ref.get("pack_id"), ref.get("version"), ref.get("pack_hash"))
                if key not in expected_packs:
                    issues.append({"code": "UNLOCKED_CONTENT_VERSION", "pointer": f"/content_pack_references/{index}", "reference": key})
        target_event: dict[str, Any] | None = None
        if event_type in {"reversal", "supersede"}:
            target = (draft.get("payload") or {}).get("target_event_id") or draft.get("superseded_event_reference")
            row = conn.execute("SELECT event_json FROM events WHERE project_id=? AND event_id=?", (project_id, target)).fetchone() if target else None
            if not row:
                issues.append({"code": "TARGET_EVENT_NOT_FOUND", "pointer": "/payload/target_event_id", "target_event_id": target})
            else:
                target_event = json.loads(row[0])
                stable_ids = [target_event["subject"]["record_id"]]
        if event_type in {"acquire", "evolve", "replace", "retire"} and not stable_ids:
            issues.append({"code": "STABLE_RULE_ID_REQUIRED", "pointer": "/stable_rule_ids"})
        subject: dict[str, Any] | None = None
        channel = draft.get("acquisition_channel")
        for rid in stable_ids:
            record = (self._resolve_locked_record_after_proof(conn, project_id, rid) if lock_already_proved else self._resolve_locked_record(conn, project_id, rid))
            if not record:
                issues.append({"code": "UNKNOWN_OR_UNLOCKED_STABLE_ID", "pointer": "/stable_rule_ids", "record_id": rid})
                continue
            if subject is None:
                subject = record
            channels = record.get("legality", {}).get("acquisition_channels", [])
            if channel and channels and channel not in channels and event_type not in {"reversal", "supersede"}:
                issues.append({"code": "INVALID_ACQUISITION_CHANNEL", "pointer": "/acquisition_channel", "record_id": rid, "channel": channel, "allowed": channels})
        projection_operations = (draft.get("payload") or {}).get("projection_operations")
        if projection_operations is not None:
            if event_type != "migration":
                issues.append({"code": "PROJECTION_OPERATIONS_REQUIRE_MIGRATION", "pointer": "/payload/projection_operations"})
            if draft.get("actor_type") not in {"system", "migration"}:
                issues.append({"code": "PROJECTION_OPERATIONS_ACTOR_INVALID", "pointer": "/actor_type"})
            if channel not in {"fixture-reconstruction", "deterministic-projection-migration"}:
                issues.append({"code": "PROJECTION_OPERATIONS_CHANNEL_INVALID", "pointer": "/acquisition_channel"})
            if not isinstance(projection_operations, list) or not projection_operations:
                issues.append({"code": "PROJECTION_OPERATIONS_INVALID", "pointer": "/payload/projection_operations"})
            else:
                for index, operation in enumerate(projection_operations):
                    pointer = f"/payload/projection_operations/{index}"
                    if not isinstance(operation, dict):
                        issues.append({"code": "PROJECTION_OPERATION_INVALID", "pointer": pointer})
                        continue
                    if operation.get("target") not in {"ledger", "rules_selection_packets"}:
                        issues.append({"code": "PROJECTION_TARGET_INVALID", "pointer": pointer + "/target"})
                    if operation.get("op") not in {"set", "append", "merge"}:
                        issues.append({"code": "PROJECTION_OPERATION_INVALID", "pointer": pointer + "/op"})
                    path = operation.get("path")
                    if not isinstance(path, str) or (path and not path.startswith("/")):
                        issues.append({"code": "PROJECTION_POINTER_INVALID", "pointer": pointer + "/path"})
                    if "value" not in operation:
                        issues.append({"code": "PROJECTION_VALUE_MISSING", "pointer": pointer + "/value"})
        return issues, subject, stable_ids, target_event

    def _canonical_event_preview(self, conn, draft_row, draft: dict[str, Any], subject: dict[str, Any], target_event: dict[str, Any] | None) -> dict[str, Any]:
        project_id = draft_row["project_id"]
        project_row = conn.execute("SELECT revision,catalog_build_hash FROM projects WHERE project_id=?", (project_id,)).fetchone()
        last = conn.execute("SELECT sequence_no,event_hash FROM events WHERE project_id=? ORDER BY sequence_no DESC LIMIT 1", (project_id,)).fetchone()
        sequence = (last[0] + 1) if last else 1
        previous = last[1] if last else ZERO_HASH
        current = self._replay_events(conn, project_id)
        legacy_type = draft["event_type"]
        canonical_type = legacy_type
        supersedes: list[str] = []
        migration: dict[str, Any] | None = None
        if legacy_type == "reversal":
            canonical_type = "retire"
            supersedes = [target_event["event_id"]] if target_event else []
            migration = {"operation": "reversal", "legacy_event_type": "reversal", "target_event_id": supersedes[0] if supersedes else None}
        elif legacy_type == "supersede":
            canonical_type = "replace"
            supersedes = [target_event["event_id"]] if target_event else []
            migration = {"operation": "supersession", "legacy_event_type": "supersede", "target_event_id": supersedes[0] if supersedes else None}
        elif legacy_type == "migration" and (draft.get("payload") or {}).get("projection_operations"):
            migration = {
                "operation": (draft.get("payload") or {}).get("migration_operation", "golden_fixture_reconstruction"),
                "projection_operations": deepcopy((draft.get("payload") or {})["projection_operations"]),
                "fixture_authority": deepcopy((draft.get("payload") or {}).get("fixture_authority")),
            }
        provisional = canonical_event_from_draft(
            event_id=draft_row["draft_id"], project_id=project_id, project_revision=project_row["revision"] + 1,
            sequence=sequence, draft=draft, subject_record=subject, catalog_build_id=project_row["catalog_build_hash"] or "catalog.unbuilt",
            previous_event_hash=previous, state_before_hash=current["state_hash"], state_after_hash=ZERO_HASH,
            created_at=draft_row["created_at"], idempotency_key=draft_row["draft_id"], supersedes_event_ids=supersedes,
            canonical_event_type=canonical_type, migration=migration,
        )
        prefix = self._event_rows(conn, project_id)
        after_state = self._reduce_events(prefix + [provisional], project_id, conn)
        provisional["state_after_hash"] = sha256_json(after_state)
        provisional["event_hash"] = canonical_event_hash(provisional)
        return provisional

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM draft_events WHERE draft_id=?", (draft_id,)).fetchone()
            if not row:
                raise FoundryError("DRAFT_EVENT_NOT_FOUND", "No draft event has that ID.", status_code=404)
            draft = json.loads(row["event_json"])
            issues, subject, _stable_ids, target = self._draft_issues(conn, row["project_id"], draft)
            canonical_event = None
            if not issues and subject is not None:
                canonical_event = self._canonical_event_preview(conn, row, draft, subject, target)
                report = self.registry.report(canonical_event)
                if not report["valid"]:
                    issues.extend({"code": "CANONICAL_EVENT_SCHEMA", **d} for d in report["diagnostics"])
            valid = not issues
            validation = {"valid": valid, "issues": issues, "validated_at": utcnow(), "canonical_event": canonical_event}
            conn.execute(
                "UPDATE draft_events SET status=?,updated_at=?,validation_json=? WHERE draft_id=?",
                ("validated" if valid else "invalid", utcnow(), canonical_json(validation), draft_id),
            )
            return {"draft_id": draft_id, **validation}

    def _stage_owned_draft_evidence(self, conn, draft_id: str, draft: dict[str, Any]) -> dict[str, Any] | None:
        """Return durable evidence that a draft belongs to an orchestrated stage.

        Stage-owned drafts are batch artifacts, not independently approvable
        advancement choices.  Earlier Phase 3B builds identified Stage 1 drafts
        primarily through ``planner_response_id``.  The database link and payload
        markers are also checked so legacy or partially migrated rows cannot evade
        the boundary merely because that field is absent.
        """
        markers = self._reserved_generic_draft_markers(draft)
        linked = conn.execute(
            "SELECT attempt_id,ordinal,slot_id FROM stage1_response_draft_links WHERE draft_id=?",
            (draft_id,),
        ).fetchone()
        if linked:
            markers.append("stage1_response_draft_link")
        if not markers:
            return None
        return {
            "draft_id": draft_id,
            "markers": markers,
            "stage1_attempt_id": linked["attempt_id"] if linked else None,
            "stage1_ordinal": linked["ordinal"] if linked else None,
            "stage1_slot_id": linked["slot_id"] if linked else None,
        }

    def _reject_generic_stage_draft(self, conn, draft_id: str, draft: dict[str, Any], *, operation: str) -> None:
        evidence = self._stage_owned_draft_evidence(conn, draft_id, draft)
        if evidence:
            raise FoundryError(
                "GENERIC_DRAFT_RESERVED_AUTHORITY_FORBIDDEN",
                "Generic draft mutations cannot claim planner, stage, system, fixture, or migration authority.",
                details={"operation": operation, **evidence},
            )

    def approve_draft(self, draft_id: str, approved_by: str, *, stage1_attempt_id: str | None = None) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT status,validation_json,event_json FROM draft_events WHERE draft_id=?", (draft_id,)).fetchone()
            if not row:
                raise FoundryError("DRAFT_EVENT_NOT_FOUND", "No draft event has that ID.", status_code=404)
            if row["status"] != "validated":
                raise FoundryError("DRAFT_NOT_VALIDATED", "Only a valid draft event can be approved.")
            internal = json.loads(row["event_json"])
            # ``stage1_attempt_id`` is retained only for call compatibility with
            # pre-HF1 code.  It is deliberately not a capability token: Stage 1
            # decisions no longer become draft advancement events at all.
            self._reject_generic_stage_draft(conn, draft_id, internal, operation="approve_draft")
            validation = json.loads(row["validation_json"])
            self._validate_or_raise(validation["canonical_event"], boundary="draft_approve", family="advancement_event", key=draft_id, conn=conn)
            conn.execute("UPDATE draft_events SET status='approved',approved_by=?,updated_at=? WHERE draft_id=?", (approved_by, utcnow(), draft_id))
            return {"draft_id": draft_id, "status": "approved", "approved_by": approved_by}

    def _event_rows(self, conn, project_id: str) -> list[dict[str, Any]]:
        return [json.loads(r["event_json"]) for r in conn.execute("SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no", (project_id,))]

    def _record_types(self, conn, project_id: str, events: list[dict[str, Any]], *, lock_already_proved: bool = False) -> dict[str, str]:
        result: dict[str, str] = {}
        for event in events:
            rid = event.get("subject", {}).get("record_id")
            if rid and rid not in result:
                record = (self._resolve_locked_record_after_proof(conn, project_id, rid) if lock_already_proved else self._resolve_locked_record(conn, project_id, rid))
                result[rid] = record.get("content_type", "unclassified") if record else event.get("subject", {}).get("content_type", "unclassified")
        return result

    def _reduce_events(self, events: list[dict[str, Any]], project_id: str, conn, *, lock_already_proved: bool = False) -> dict[str, Any]:
        reversed_ids: set[str] = set()
        superseded_ids: set[str] = set()
        for event in events:
            operation = (event.get("migration") or {}).get("operation")
            targets = set(event.get("supersedes_event_ids") or [])
            if operation == "reversal":
                reversed_ids |= targets
            elif operation == "supersession":
                superseded_ids |= targets
        suppressed = reversed_ids | superseded_ids
        state = _initial_state(project_id)
        state["reversed_event_ids"] = sorted(reversed_ids)
        state["superseded_event_ids"] = sorted(superseded_ids)
        record_types = self._record_types(conn, project_id, events, lock_already_proved=lock_already_proved)
        for event in events:
            if event["event_id"] in suppressed:
                continue
            operation = (event.get("migration") or {}).get("operation")
            if operation in {"reversal", "supersession"}:
                state["migration_history"].append({"event_id": event["event_id"], "operation": operation, "targets": event.get("supersedes_event_ids", [])})
                continue
            for rid in event.get("retired_records", []):
                _retire_selection(state, rid)
            for rid in event.get("created_records", []) + event.get("updated_records", []):
                _add_selection(state, record_types.get(rid, event.get("subject", {}).get("content_type", "unclassified")), rid)
            if event["event_type"] == "migration":
                state["migration_history"].append({"event_id": event["event_id"], "migration": event.get("migration")})
            # Phase 4A keeps v1-only replay hashes byte-identical. A Stage 2 summary
            # appears only after the first v2 event and therefore becomes part of
            # state_before/state_after hashing for subsequent mechanical events.
            if event.get("schema_version") in {"TianxiaFoundry.AdvancementEvent.v2", "TianxiaFoundry.AdvancementEvent.v3"}:
                stage2 = state.setdefault("stage2", {"event_ids": [], "kinds": {}, "target_cl": 0})
                stage2["event_ids"].append(event["event_id"])
                kind = event.get("advancement", {}).get("kind", "unclassified")
                stage2["kinds"].setdefault(kind, []).append(event["event_id"])
                stage2["target_cl"] = max(stage2["target_cl"], int(event.get("advancement", {}).get("target_cl", 0)))
        return state

    def _replay_events(
        self,
        conn,
        project_id: str,
        *,
        verify_chain: bool = True,
        lock_proof_already_verified: bool = False,
    ) -> dict[str, Any]:
        rows = conn.execute("SELECT sequence_no,event_hash,previous_event_hash,event_json,canonical_schema_version FROM events WHERE project_id=? ORDER BY sequence_no", (project_id,)).fetchall()
        # A replay verifies many event prefixes. Proving the complete immutable
        # project lock inside every prefix reduction turned a bounded replay into
        # repeated full-catalog hashing. Prove the complete HF2 lock once, then use
        # the already-proved snapshot resolver for every reduction in this replay.
        locks = self._project_locks(conn, project_id)
        required = ("record_set_hash", "payload_files_hash", "install_receipt_hash", "membership_snapshot_hash")
        lock_already_proved = bool(locks) and all(all(lock.get(field) for field in required) for lock in locks)
        if lock_already_proved and not lock_proof_already_verified:
            self.project_lock_proof(conn, project_id)
        previous_hash = ZERO_HASH
        expected_seq = 1
        events: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        prefix: list[dict[str, Any]] = []
        for row in rows:
            pointer = f"/events/{row['sequence_no']}"
            try:
                event = json.loads(row["event_json"])
            except Exception as exc:
                errors.append({"code": "PERSISTED_EVENT_JSON_MALFORMED", "sequence": row["sequence_no"], "pointer": pointer, "exception_type": type(exc).__name__})
                previous_hash = row["event_hash"]
                expected_seq += 1
                continue
            try:
                report = self.registry.report(event)
            except Exception as exc:
                report = {"valid": False, "diagnostics": [{"code": "SCHEMA_REGISTRY_FAILURE", "exception_type": type(exc).__name__}]}
            if not report["valid"]:
                errors.append({"code": "PERSISTED_EVENT_SCHEMA_INVALID", "sequence": row["sequence_no"], "pointer": pointer, "diagnostics": report["diagnostics"]})
            if row["canonical_schema_version"] and event.get("schema_version") != row["canonical_schema_version"]:
                errors.append({"code": "PERSISTED_EVENT_SCHEMA_BINDING_MISMATCH", "sequence": row["sequence_no"], "pointer": pointer, "stored": row["canonical_schema_version"], "embedded": event.get("schema_version")})
            if row["sequence_no"] != expected_seq or event.get("sequence") != expected_seq:
                errors.append({"code": "SEQUENCE_GAP", "expected": expected_seq, "actual": row["sequence_no"], "embedded": event.get("sequence"), "pointer": pointer})
            if row["previous_event_hash"] != previous_hash or event.get("previous_event_hash") != previous_hash:
                errors.append({"code": "BROKEN_HASH_CHAIN", "sequence": row["sequence_no"], "pointer": pointer, "expected": previous_hash, "stored": row["previous_event_hash"], "embedded": event.get("previous_event_hash")})
            try:
                computed = canonical_event_hash(event)
            except Exception as exc:
                computed = None
                errors.append({"code": "PERSISTED_EVENT_HASH_UNCOMPUTABLE", "sequence": row["sequence_no"], "pointer": pointer, "exception_type": type(exc).__name__})
            if computed is not None and (computed != row["event_hash"] or computed != event.get("event_hash")):
                errors.append({"code": "EVENT_HASH_MISMATCH", "sequence": row["sequence_no"], "pointer": pointer, "computed": computed, "stored": row["event_hash"], "embedded": event.get("event_hash")})
            try:
                before_state = self._reduce_events(prefix, project_id, conn, lock_already_proved=lock_already_proved)
                if event.get("state_before_hash") != sha256_json(before_state):
                    errors.append({"code": "STATE_BEFORE_HASH_MISMATCH", "sequence": row["sequence_no"], "pointer": pointer})
                prefix.append(event)
                after_state = self._reduce_events(prefix, project_id, conn, lock_already_proved=lock_already_proved)
                if event.get("state_after_hash") != sha256_json(after_state):
                    errors.append({"code": "STATE_AFTER_HASH_MISMATCH", "sequence": row["sequence_no"], "pointer": pointer})
            except Exception as exc:
                errors.append({"code": "EVENT_REPLAY_FAILURE", "sequence": row["sequence_no"], "pointer": pointer, "exception_type": type(exc).__name__})
                if event not in prefix:
                    prefix.append(event)
            previous_hash = row["event_hash"]
            expected_seq += 1
            events.append(event)
        if verify_chain and errors:
            raise FoundryError("EVENT_CHAIN_INVALID", "The committed event chain is invalid.", details=errors)
        try:
            state = self._reduce_events(events, project_id, conn, lock_already_proved=lock_already_proved)
        except Exception as exc:
            if verify_chain:
                raise FoundryError("EVENT_REPLAY_INVALID", "The committed event stream cannot be mechanically reduced.", details={"exception_type": type(exc).__name__}) from exc
            state = _initial_state(project_id)
            errors.append({"code": "EVENT_REPLAY_FAILURE", "pointer": "/events", "exception_type": type(exc).__name__})
        return {
            "project_id": project_id,
            "event_count": len(events),
            "latest_event_hash": previous_hash if rows else None,
            "chain_valid": not errors,
            "chain_errors": errors,
            "state": state,
            "state_hash": sha256_json(state),
        }

    def _update_project_after_commit(self, conn, project_id: str, replay: dict[str, Any]) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        old = json.loads(row["project_json"])
        updated = canonical_project_document(
            project_id=project_id, name=old["name"], revision=row["revision"] + 1, status=old["status"],
            created_at=old["created_at"], updated_at=utcnow(), catalog_build_id=old["content_lock"]["catalog_build_id"],
            pack_locks=self._project_locks(conn, project_id), user_locks=old["user_locks"], source_inputs=old["source_inputs"],
            event_count=replay["event_count"], head_hash=replay["latest_event_hash"], active_stage=old["active_stage"],
            stage_commits=old["stage_commits"], generated_artifacts=old["generated_artifacts"], candidates=old["candidates"], acceptance=old["acceptance"],
        )
        self._validate_or_raise(updated, boundary="project_commit_update", family="character_project", key=project_id, conn=conn)
        p_hash = canonical_project_hash(updated)
        conn.execute(
            "UPDATE projects SET status=?,revision=?,updated_at=?,project_json=?,canonical_project_hash=?,canonical_schema_version=?,contract_status='valid' WHERE project_id=?",
            (updated["status"], updated["revision"], updated["updated_at"], canonical_json(updated), p_hash, updated["schema_version"], project_id),
        )
        return updated

    def commit_draft(self, draft_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            draft_row = conn.execute("SELECT * FROM draft_events WHERE draft_id=?", (draft_id,)).fetchone()
            if not draft_row:
                raise FoundryError("DRAFT_EVENT_NOT_FOUND", "No draft event has that ID.", status_code=404)
            draft = json.loads(draft_row["event_json"])
            self._reject_generic_stage_draft(conn, draft_id, draft, operation="commit_draft")
            if draft_row["status"] != "approved":
                raise FoundryError("DRAFT_NOT_APPROVED", "Only an approved draft event can be committed.")
            self.project_lock_proof(conn, draft_row["project_id"])
            # Revalidate against current head so concurrent commits cannot stale the preview.
            issues, subject, _stable_ids, target = self._draft_issues(conn, draft_row["project_id"], draft)
            if issues or subject is None:
                raise FoundryError("DRAFT_REVALIDATION_FAILED", "The approved draft is no longer valid.", details=issues)
            event = self._canonical_event_preview(conn, draft_row, draft, subject, target)
            self._validate_or_raise(event, boundary="event_commit_before_insert", family="advancement_event", key=event["event_id"], conn=conn)
            duplicate = conn.execute("SELECT event_json FROM events WHERE project_id=? AND event_id=?", (event["project_id"], event["event_id"])).fetchone()
            if duplicate:
                existing = json.loads(duplicate[0])
                if existing["event_hash"] == event["event_hash"]:
                    return {"committed": True, "idempotent": True, "draft_id": draft_id, "event": existing, "replay": self._replay_events(conn, event["project_id"])}
                raise FoundryError("IDEMPOTENCY_CONFLICT", "The draft ID is already bound to different event bytes.")
            conn.execute(
                """INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,
                legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (event["project_id"], event["sequence"], event["event_id"], event["event_hash"], event["previous_event_hash"], event["created_at"], canonical_json(event), None, event["schema_version"], "valid"),
            )
            for rid in sorted(set(event["created_records"] + event["updated_records"] + event["retired_records"] + [event["subject"]["record_id"]])):
                record = self._resolve_locked_record(conn, event["project_id"], rid)
                if not record:
                    raise FoundryError("UNKNOWN_OR_UNLOCKED_STABLE_ID", "A committed event references content outside the project lock.", details={"record_id": rid})
                self._assert_snapshot_record(conn, event["project_id"], record)
            conn.execute("UPDATE draft_events SET status='committed',updated_at=? WHERE draft_id=?", (utcnow(), draft_id))
            replayed = self._replay_events(conn, event["project_id"])
            project = self._update_project_after_commit(conn, event["project_id"], replayed)
            conn.execute(
                "INSERT OR REPLACE INTO snapshots(project_id,sequence_no,state_hash,state_json,created_at) VALUES(?,?,?,?,?)",
                (event["project_id"], event["sequence"], replayed["state_hash"], canonical_json(replayed["state"]), utcnow()),
            )
        return {"committed": True, "idempotent": False, "draft_id": draft_id, "event": event, "project": project, "replay": replayed}

    def commit_drafts_atomic(self, draft_ids: list[str]) -> dict[str, Any]:
        """Commit an ordered group of approved drafts in one SQLite transaction.

        Stage 1 responses can produce several causal events. This method prevents a
        mid-batch failure from leaving a partially committed planner decision.
        """
        if not draft_ids:
            raise FoundryError("DRAFT_BATCH_EMPTY", "At least one approved draft is required.")
        if len(set(draft_ids)) != len(draft_ids):
            raise FoundryError("DRAFT_BATCH_DUPLICATE", "A draft ID appears more than once in the commit batch.")
        committed: list[dict[str, Any]] = []
        with self.db.transaction() as conn:
            project_id: str | None = None
            replayed: dict[str, Any] | None = None
            project: dict[str, Any] | None = None
            for draft_id in draft_ids:
                draft_row = conn.execute("SELECT * FROM draft_events WHERE draft_id=?", (draft_id,)).fetchone()
                if not draft_row:
                    raise FoundryError("DRAFT_EVENT_NOT_FOUND", "No draft event has that ID.", status_code=404)
                if draft_row["status"] != "approved":
                    raise FoundryError("DRAFT_NOT_APPROVED", "Every draft in an atomic batch must be approved.", details={"draft_id": draft_id, "status": draft_row["status"]})
                draft = json.loads(draft_row["event_json"])
                self._reject_generic_stage_draft(conn, draft_id, draft, operation="commit_drafts_atomic")
                if project_id is None:
                    project_id = draft_row["project_id"]
                elif draft_row["project_id"] != project_id:
                    raise FoundryError("DRAFT_BATCH_PROJECT_MISMATCH", "All drafts in an atomic batch must belong to one project.")
                self.project_lock_proof(conn, draft_row["project_id"])
                issues, subject, _stable_ids, target = self._draft_issues(conn, draft_row["project_id"], draft)
                if issues or subject is None:
                    raise FoundryError("DRAFT_REVALIDATION_FAILED", "An approved draft is no longer valid.", details={"draft_id": draft_id, "issues": issues})
                event = self._canonical_event_preview(conn, draft_row, draft, subject, target)
                self._validate_or_raise(event, boundary="event_atomic_commit_before_insert", family="advancement_event", key=event["event_id"], conn=conn)
                duplicate = conn.execute("SELECT event_json FROM events WHERE project_id=? AND event_id=?", (event["project_id"], event["event_id"])).fetchone()
                if duplicate:
                    existing = json.loads(duplicate[0])
                    if existing["event_hash"] != event["event_hash"]:
                        raise FoundryError("IDEMPOTENCY_CONFLICT", "A draft ID is already bound to different event bytes.")
                    committed.append(existing)
                    continue
                conn.execute(
                    """INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,
                    legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (event["project_id"], event["sequence"], event["event_id"], event["event_hash"], event["previous_event_hash"], event["created_at"], canonical_json(event), None, event["schema_version"], "valid"),
                )
                for rid in sorted(set(event["created_records"] + event["updated_records"] + event["retired_records"] + [event["subject"]["record_id"]])):
                    record = self._resolve_locked_record(conn, event["project_id"], rid)
                    if not record:
                        raise FoundryError("UNKNOWN_OR_UNLOCKED_STABLE_ID", "A committed event references content outside the project lock.", details={"record_id": rid})
                    self._assert_snapshot_record(conn, event["project_id"], record)
                conn.execute("UPDATE draft_events SET status='committed',updated_at=? WHERE draft_id=?", (utcnow(), draft_id))
                replayed = self._replay_events(conn, event["project_id"])
                project = self._update_project_after_commit(conn, event["project_id"], replayed)
                committed.append(event)
            assert project_id is not None
            replayed = self._replay_events(conn, project_id)
            if project is None:
                row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
                project = json.loads(row[0])
            conn.execute(
                "INSERT OR REPLACE INTO snapshots(project_id,sequence_no,state_hash,state_json,created_at) VALUES(?,?,?,?,?)",
                (project_id, replayed["event_count"], replayed["state_hash"], canonical_json(replayed["state"]), utcnow()),
            )
        return {"committed": True, "atomic": True, "events": committed, "project": project, "replay": replayed}

    def replay(self, project_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            self._reconstruct_project(conn, project_id)
            return self._replay_events(conn, project_id)

    def verify_chain(self, project_id: str) -> dict[str, Any]:
        try:
            replay = self.replay(project_id)
            return {"project_id": project_id, "valid": True, "event_count": replay["event_count"], "latest_event_hash": replay["latest_event_hash"]}
        except FoundryError as exc:
            if exc.code != "EVENT_CHAIN_INVALID":
                raise
            return {"project_id": project_id, "valid": False, "errors": exc.details}

    def timeline(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            events = self._event_rows(conn, project_id)
            for event in events:
                self._validate_or_raise(event, boundary="event_timeline", family="advancement_event", key=event["event_id"], conn=conn)
            return events

    def rebuild_read_models(self, project_id: str, *, delete_snapshots: bool = True) -> dict[str, Any]:
        with self.db.transaction() as conn:
            if delete_snapshots:
                conn.execute("DELETE FROM snapshots WHERE project_id=?", (project_id,))
            replay = self._replay_events(conn, project_id)
            conn.execute(
                "INSERT OR REPLACE INTO snapshots(project_id,sequence_no,state_hash,state_json,created_at) VALUES(?,?,?,?,?)",
                (project_id, replay["event_count"], replay["state_hash"], canonical_json(replay["state"]), utcnow()),
            )
            return {"rebuilt": True, **replay}

    def read_models(self, project_id: str) -> dict[str, Any]:
        wrapper = self.get_project(project_id)
        project = wrapper["project"]
        replay = self.replay(project_id)
        with self.db.connection() as conn:
            findings = [dict(r) for r in conn.execute("SELECT * FROM validation_findings WHERE project_id=? ORDER BY created_at", (project_id,))]
        return {
            "project_summary": {"project_id": project_id, "name": project["name"], "status": project["status"], "revision": project["revision"], "created_at": project["created_at"], "updated_at": project["updated_at"]},
            "content_locks": wrapper["content_locks"],
            "event_timeline": self.timeline(project_id),
            "current_selections": replay["state"]["selections"],
            "unresolved_questions": [f for f in findings if not f["resolved"]],
            "validation_findings": findings,
            "compatibility_versions": {"factory": project["factory_target"]["producer"], "candidate_schema": project["factory_target"]["candidate_schema"], "gm_screen": project["gm_screen_target"]["consumer"]},
            "event_chain_health": self.verify_chain(project_id),
            "state_hash": replay["state_hash"],
        }

    def compatibility_projection_status(self, project_id: str) -> dict[str, Any]:
        replay = self.replay(project_id)
        return {
            "project_id": project_id,
            "status": "DRAFT_COMPATIBILITY_PROJECTION_NOT_FACTORY_COMPILABLE",
            "project_state_hash": replay["state_hash"],
            "projector_input_available": True,
            "phase3_sections_required": [
                "identity", "source_profile", "build_profile", "advancement", "background_origin", "paths_subpaths",
                "spheres_talents", "insights", "foundation", "cultivation_method", "equipment", "companions",
                "actions", "states", "modifiers", "resources", "procedures", "recorded_arts", "forged_techniques",
                "composite_playbooks", "dao_iching", "semantic_contract", "release_metadata",
            ],
            "factory_compile_allowed": False,
        }

    def export_project(self, project_id: str, filename: str | None = None) -> dict[str, Any]:
        wrapper = self.get_project(project_id)
        project = wrapper["project"]
        replay = self.replay(project_id)
        filename = filename or f"{project_id}.tianxia-project.zip"
        if Path(filename).name != filename:
            raise FoundryError("UNSAFE_FILENAME", "Export filename must be a plain filename.")
        target = self.db.settings.exports_dir / filename
        with self.db.connection() as conn:
            events = self._event_rows(conn, project_id)
            records = [json.loads(r[0]) for r in conn.execute("SELECT record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id", (project_id,))]
            self._validate_or_raise(project, boundary="project_export", family="character_project", key=project_id, conn=conn)
            for event in events:
                self._validate_or_raise(event, boundary="event_export", family="advancement_event", key=event["event_id"], conn=conn)
            for record in records:
                self._validate_or_raise(record, boundary="record_export", family="rules_catalog_record", key=record["record_id"], conn=conn)
        files: dict[str, bytes] = {
            "project.json": canonical_json(project).encode("utf-8"),
            "content-lock.json": canonical_json(project["content_lock"]).encode("utf-8"),
            "events.json": canonical_json(events).encode("utf-8"),
            "locked-records.json": canonical_json(records).encode("utf-8"),
            "replay.json": canonical_json(replay).encode("utf-8"),
            "compatibility-projection-status.json": canonical_json(self.compatibility_projection_status(project_id)).encode("utf-8"),
        }
        from non_sphere_authority import NonSphereAuthorityService
        non_sphere_export = NonSphereAuthorityService(self.db).export_state(project_id)
        if non_sphere_export is not None:
            files["non-sphere-authority.json"] = canonical_json(non_sphere_export).encode("utf-8")
        checksums = {name: sha256_bytes(data) for name, data in files.items()}
        manifest = {
            "schema_version": "TianxiaFoundry.ProjectExport.v1",
            "project_id": project_id,
            "created_at": utcnow(),
            "canonical_project_hash": canonical_project_hash(project),
            "event_count": len(events),
            "state_hash": replay["state_hash"],
            "latest_event_hash": replay["latest_event_hash"],
            "content_lock_hash": project["content_lock"]["lock_hash"],
            "files": checksums,
        }
        files["manifest.json"] = canonical_json(manifest).encode("utf-8")
        files["SHA256SUMS.txt"] = "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())).encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)
        return {"exported": True, "path": str(target), "filename": target.name, "sha256": sha256_file(target), "project_hash": canonical_project_hash(project), "state_hash": replay["state_hash"], "event_count": len(events)}

    def import_project(self, package: Path) -> dict[str, Any]:
        package = package.resolve()
        if not package.exists() or package.stat().st_size > MAX_PROJECT_ARCHIVE:
            raise FoundryError("PROJECT_PACKAGE_INVALID", "Project package is missing or too large.")
        with zipfile.ZipFile(package) as zf:
            total = 0
            names = []
            collision_keys = set()
            for info in zf.infolist():
                p = PurePosixPath(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
                    raise FoundryError("ZIP_TRAVERSAL", "Project package contains an unsafe path.")
                if info.flag_bits & 0x1:
                    raise FoundryError("PROJECT_PACKAGE_ENCRYPTED", "Encrypted project-package members are forbidden.")
                if mode not in (0, 0o100000) or info.is_dir():
                    raise FoundryError("PROJECT_PACKAGE_SPECIAL_FILE", "Project packages may contain regular files only.")
                key = unicodedata.normalize("NFC", info.filename).casefold()
                if key in collision_keys:
                    raise FoundryError("PROJECT_PACKAGE_PATH_COLLISION", "Project package contains duplicate, case-colliding, or Unicode-colliding paths.")
                collision_keys.add(key); names.append(info.filename)
                total += info.file_size
                if total > MAX_PROJECT_EXPANDED:
                    raise FoundryError("ARCHIVE_EXPANSION_LIMIT", "Project package expands beyond the configured limit.")
                if info.compress_size and info.file_size / max(info.compress_size, 1) > 1000:
                    raise FoundryError("ARCHIVE_EXPANSION_LIMIT", "Project package member has an abusive expansion ratio.")
            required_metadata = {"manifest.json", "SHA256SUMS.txt"}
            required_payload = {"project.json", "content-lock.json", "events.json", "locked-records.json", "replay.json", "compatibility-projection-status.json"}
            if not required_metadata | required_payload <= set(names):
                raise FoundryError("PROJECT_PACKAGE_INCOMPLETE", "Project package is missing required files.")
            contents = {name: zf.read(name) for name in names}
        manifest = json.loads(contents["manifest.json"])
        if manifest.get("schema_version") != "TianxiaFoundry.ProjectExport.v1" or not isinstance(manifest.get("files"), dict):
            raise FoundryError("PROJECT_MANIFEST_INVALID", "Project package manifest schema is invalid.")
        declared = manifest["files"]
        payload_names = set(contents) - {"manifest.json", "SHA256SUMS.txt"}
        if set(declared) != payload_names:
            raise FoundryError("PROJECT_MANIFEST_COVERAGE_MISMATCH", "Project package manifest does not exactly cover every payload member.", details={"declared": sorted(declared), "payload": sorted(payload_names)})
        ledger = {}
        try:
            for raw in contents["SHA256SUMS.txt"].decode("utf-8").splitlines():
                digest, name = raw.split("  ", 1)
                if name in ledger or len(digest) != 64:
                    raise ValueError
                ledger[name] = digest
        except Exception as exc:
            raise FoundryError("PROJECT_CHECKSUM_LEDGER_INVALID", "Project checksum ledger is malformed.") from exc
        if set(ledger) != payload_names:
            raise FoundryError("PROJECT_CHECKSUM_COVERAGE_MISMATCH", "SHA256SUMS.txt does not exactly cover every payload member.", details={"ledger": sorted(ledger), "payload": sorted(payload_names)})
        for name in sorted(payload_names):
            actual = sha256_bytes(contents[name])
            if declared[name] != ledger[name] or actual != declared[name]:
                raise FoundryError("PROJECT_FILE_HASH_MISMATCH", "Manifest, checksum ledger, and actual payload hash must agree.", details={"file": name})
        project = json.loads(contents["project.json"])
        events = json.loads(contents["events.json"])
        records = json.loads(contents["locked-records.json"])
        expected_replay = json.loads(contents["replay.json"])
        compatibility_status = json.loads(contents["compatibility-projection-status.json"])
        project_id = project["project_id"]
        imported_non_sphere_state = None
        imported_non_sphere_hash = None
        imported_non_sphere_ledger = None
        if "non-sphere-authority.json" in contents:
            from non_sphere_authority import NonSphereAuthorityService
            imported_non_sphere_state, imported_non_sphere_hash, imported_non_sphere_ledger = NonSphereAuthorityService(self.db).validate_import_payload(
                project_id, json.loads(contents["non-sphere-authority.json"])
            )
        self._validate_or_raise(project, boundary="project_import_parse", family="character_project", key=project_id)
        if canonical_project_hash(project) != manifest.get("canonical_project_hash"):
            raise FoundryError("PROJECT_CANONICAL_HASH_MISMATCH", "Imported canonical project hash does not match its manifest.")
        for event in events:
            self._validate_or_raise(event, boundary="event_import_parse", family="advancement_event", key=event.get("event_id", "unknown"))
        # Do not repeat a full JSON-Schema walk over thousands of exported lock records.
        # The exact archive member hash was verified above, and every supplied record is
        # compared byte-for-byte with the externally keyed immutable installed pack seal
        # inside the transaction below before any project row can commit.
        if not isinstance(records, list) or any(not isinstance(record, dict) or not record.get("record_id") for record in records):
            raise FoundryError("PROJECT_LOCK_SNAPSHOT_INVALID", "The imported locked-record set is malformed.")
        with self.db.transaction() as conn:
            imported_seals = [
                verify_pack_seal(
                    conn,
                    pack_id=lock["pack_id"],
                    version=lock["version"],
                    expected_pack_hash=lock["content_hash"],
                    integrity=self.integrity,
                )
                for lock in project["content_lock"]["packs"]
            ]
            imported_locks = [
                {"pack_id": seal.pack_id, "version": seal.version, "pack_hash": seal.pack_hash}
                for seal in imported_seals
            ]
            # An exported existing project remains reproducible after a pack is
            # retired, but its exact bytes and replacement graph must still be
            # installed and unambiguous.
            CatalogService.validate_project_lock_set(
                conn,
                imported_locks,
                allow_inactive=True,
                # Synthetic TEST-only fixtures are permitted to exercise the
                # import round trip. They remain isolated by authority plus the
                # explicit TEST namespace and never become production choices.
                allow_test_fixtures=True,
            )
            if conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
                raise FoundryError("PROJECT_ALREADY_EXISTS", "A project with this ID already exists.")
            conn.execute(
                """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,target_factory_version,
                target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,quality_target,project_json,
                compatibility_projection_status,compile_status,consumer_verification_status,canonical_project_hash,
                canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, project["name"], project["status"], project["revision"], project["created_at"], project["updated_at"],
                 project["factory_target"]["producer"], project["factory_target"]["candidate_schema"], project["gm_screen_target"]["consumer"],
                 project["content_lock"]["catalog_build_id"], "imported", canonical_json(project),
                 canonical_json(compatibility_status), "NOT_IMPLEMENTED_PHASE2R", "NOT_RUN_NO_COMPILED_CHARACTER",
                 canonical_project_hash(project), project["schema_version"], "valid"),
            )
            expected_exported_records = {
                member["record_id"]: member["record_json"]
                for seal in imported_seals
                for member in seal.records
            }
            supplied_exported_records = {record["record_id"]: canonical_json(record) for record in records}
            if supplied_exported_records != expected_exported_records:
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_INCOMPLETE",
                    "The imported locked-record set is not exactly the complete immutable membership of its pack locks.",
                    details={
                        "missing": sorted(set(expected_exported_records) - set(supplied_exported_records)),
                        "extra": sorted(set(supplied_exported_records) - set(expected_exported_records)),
                    },
                )
            self._snapshot_pack_seals(conn, project_id, imported_seals, locked_at=project["created_at"])
            # imported_seals were externally keyed and fully verified immediately above;
            # avoid a second simultaneous full-catalog materialization while their exact
            # bytes are still resident. Future reads independently re-prove the lock.
            for event in events:
                conn.execute(
                    "INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (project_id, event["sequence"], event["event_id"], event["event_hash"], event["previous_event_hash"] or ZERO_HASH, event["created_at"], canonical_json(event), None, event["schema_version"], "valid"),
                )
            replay = self._replay_events(conn, project_id, lock_proof_already_verified=True)
            if replay["state_hash"] != manifest["state_hash"] or replay["state_hash"] != expected_replay["state_hash"]:
                raise FoundryError("PROJECT_STATE_HASH_MISMATCH", "Imported project replay did not reproduce the exported state hash.")
            if replay["latest_event_hash"] != manifest["latest_event_hash"]:
                raise FoundryError("PROJECT_EVENT_HASH_MISMATCH", "Imported project event chain differs from the export.")
            if project["event_stream"]["head_hash"] != replay["latest_event_hash"] or project["event_stream"]["count"] != len(events):
                raise FoundryError("PROJECT_EVENT_STREAM_MISMATCH", "Canonical project event stream metadata differs from imported events.")
            conn.execute("INSERT INTO snapshots(project_id,sequence_no,state_hash,state_json,created_at) VALUES(?,?,?,?,?)", (project_id, len(events), replay["state_hash"], canonical_json(replay["state"]), utcnow()))
            if imported_non_sphere_state is not None:
                from non_sphere_authority import NonSphereAuthorityService
                ns = NonSphereAuthorityService(self.db)
                for evidence in (imported_non_sphere_ledger or {}).get("evidence", []):
                    if evidence.get("project_id") != project_id:
                        raise FoundryError("NS1R_IMPORTED_EVIDENCE_PROJECT_MISMATCH", "Imported evidence belongs to another project.")
                    source = ns._source_authority_semantics(
                        conn, project_id, evidence["source_kind"], evidence["source_identity"], evidence,
                    )
                    semantics = source["authority"]
                    if (source["source_hash"] != evidence["source_hash"] or semantics.get("authority_type") != evidence["authority_type"]
                        or canonical_json(semantics.get("targets")) != evidence["targets_json"]
                        or semantics.get("amount_awarded") != evidence.get("amount_awarded")):
                        raise FoundryError("NS1R_IMPORTED_EVIDENCE_MISMATCH", "Imported evidence does not match its exact imported source semantics.")
                    conn.execute("""INSERT INTO non_sphere_authority_evidence(evidence_id,project_id,authority_type,targets_json,source_kind,source_identity,source_hash,project_revision,event_sequence,amount_awarded,amount_consumed,creation_authority,valid,revoked_at,evidence_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        tuple(evidence[k] for k in ("evidence_id","project_id","authority_type","targets_json","source_kind","source_identity","source_hash","project_revision","event_sequence","amount_awarded","amount_consumed","creation_authority","valid","revoked_at","evidence_hash","created_at")))
                for consumption in (imported_non_sphere_ledger or {}).get("ap_consumptions", []):
                    conn.execute("INSERT INTO non_sphere_ap_consumptions(project_id,evidence_id,idempotency_key,operation_hash,amount,transaction_json,created_at) VALUES(?,?,?,?,?,?,?)", tuple(consumption[k] for k in ("project_id","evidence_id","idempotency_key","operation_hash","amount","transaction_json","created_at")))
                access_ids=[row.get("evidence_id") for row in imported_non_sphere_state.get("access_source_records",[]) if isinstance(row,dict)]
                imported_ids={row.get("evidence_id") for row in (imported_non_sphere_ledger or {}).get("evidence",[])}
                if any(evidence_id not in imported_ids for evidence_id in access_ids):
                    raise FoundryError("NS1R_IMPORTED_EVIDENCE_MISMATCH", "Imported state references evidence absent from its immutable ledger.")
                imported_non_sphere_hash=sha256_json(imported_non_sphere_state)
                conn.execute(
                    "INSERT INTO non_sphere_character_states(project_id,schema_version,authority_snapshot_hash,state_json,state_hash,updated_at) VALUES(?,?,?,?,?,?)",
                    (project_id, imported_non_sphere_state["schema_version"], imported_non_sphere_state["authority_snapshot_hash"], canonical_json(imported_non_sphere_state), imported_non_sphere_hash, imported_non_sphere_state["updated_at"]),
                )
            self._validate_or_raise(project, boundary="project_import_persist", family="character_project", key=project_id, conn=conn)
        result = {"imported": True, "project_id": project_id, "project_hash": canonical_project_hash(project), "state_hash": replay["state_hash"], "latest_event_hash": replay["latest_event_hash"], "event_count": len(events)}
        # Drop the exported full-catalog snapshot and verified seal material before
        # the caller begins projection and Character Sheet reconstruction.
        del records, imported_seals, expected_exported_records, supplied_exported_records
        gc.collect()
        return result
