from __future__ import annotations

import gc
import json
import os
import uuid
import zipfile
import unicodedata
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Collection, Mapping

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
    canonical_record_hash,
    canonical_event_from_draft,
    canonical_event_hash,
    canonical_project_document,
    canonical_project_hash,
)
from contracts.registry import ContractValidationError, SchemaRegistry
from catalog.service import CatalogService
from content_packs.membership import PackSeal, verify_pack_seal
from security.approval_challenges import ApprovalChallengeService
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

# Canonical validation still runs everywhere it ran before; only the durable
# audit row is opt-in.  Set this to 1/true/yes/on to record successful write
# boundaries again.  Read boundaries never record, with or without the flag.
CANONICAL_VALIDATION_AUDIT_ENV = "TIANXIA_CANONICAL_VALIDATION_AUDIT"
_CANONICAL_VALIDATION_AUDIT_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})

# Boundaries that only read existing state.  Every other boundary named in this
# module either creates, appends, commits, imports, or materializes.  Any
# boundary whose name ends in ``_reconstruct`` is also a read boundary, so a new
# reconstruction seam is excluded by construction rather than by remembering to
# add it here.
_READ_VALIDATION_BOUNDARIES = frozenset(
    {
        "custom_training_source_snapshot",
        "event_export",
        "event_timeline",
        "project_export",
        "project_get",
        "record_export",
    }
)


def _canonical_validation_audit_enabled() -> bool:
    """Read the opt-in flag per call so a test or run can scope it."""

    return (
        os.environ.get(CANONICAL_VALIDATION_AUDIT_ENV, "").strip().lower()
        in _CANONICAL_VALIDATION_AUDIT_ENABLED_VALUES
    )

# Content-pack membership and install receipts are append-only/immutable for
# any project that holds the corresponding lock.  These caches are deliberately
# exposed only as an operation scope so repeated Stage 2 validation/approval
# transactions can reuse one already-proven complete project lock proof (and
# its PackSeal checks) without creating a process-wide trust cache.
_PROJECT_LOCK_PROOF_SEAL_CACHE: ContextVar[
    dict[tuple[int, str, str, str], PackSeal] | None
] = ContextVar("tianxia_project_lock_proof_seal_cache", default=None)
_PROJECT_LOCK_PROOF_CACHE: ContextVar[
    dict[tuple[int, str, str], dict[str, Any]] | None
] = ContextVar("tianxia_project_lock_proof_cache", default=None)
# Operation-scoped memo for derived, identity-keyed facts about a project:
# ("fingerprint", db, project, membership identity) -> byte fingerprint rows
# (locked rows are immutable by schema, so membership identity is a complete
# guard) and ("user_locks", db, project, revision, project hash) -> the
# owner lock values parsed once instead of re-parsing the whole project
# document on every Path resolution.
_PROJECT_LOCK_SCOPE_MEMO: ContextVar[dict[tuple[Any, ...], Any] | None] = ContextVar(
    "tianxia_project_lock_scope_memo", default=None
)


def ensure_project_lock_proof_cache_scope():
    """Enter a proof cache scope unless the caller already runs inside one.

    Nesting a fresh scope would hide the outer scope's memo for the duration
    of the inner block; reusing the active scope keeps every verified seal
    and resolved row available to the caller and its callees alike.
    """

    if _PROJECT_LOCK_SCOPE_MEMO.get() is not None:
        return nullcontext()
    return project_lock_proof_cache_scope()


@contextmanager
def project_lock_proof_cache_scope():
    seal_token = _PROJECT_LOCK_PROOF_SEAL_CACHE.set({})
    proof_token = _PROJECT_LOCK_PROOF_CACHE.set({})
    memo_token = _PROJECT_LOCK_SCOPE_MEMO.set({})
    try:
        yield
    finally:
        _PROJECT_LOCK_SCOPE_MEMO.reset(memo_token)
        _PROJECT_LOCK_PROOF_CACHE.reset(proof_token)
        _PROJECT_LOCK_PROOF_SEAL_CACHE.reset(seal_token)


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

    def delete_project_permanently(self, project_id: str) -> dict[str, Any]:
        """Back up and remove only an eligible project's own rows and files."""
        from project_store.permanent_deletion import PermanentProjectDeletion

        return PermanentProjectDeletion(self.db).delete(project_id)

    def restore_project_permanently(self, backup_path: str | Path) -> dict[str, Any]:
        """Restore a deleted-project backup without overwriting existing data."""
        from project_store.permanent_deletion import PermanentProjectDeletion

        return PermanentProjectDeletion(self.db).restore(backup_path)

    def __init__(self, db: Database, *, integrity: IntegrityService | None = None, principal_provider: Any | None = None):
        self.db = db
        self.integrity = integrity or IntegrityService.for_database(db)
        self.registry = SchemaRegistry(db.settings.root_dir)
        self.challenges = ApprovalChallengeService(
            db,
            principal_provider=principal_provider,
            integrity=self.integrity,
        )

    def _cached_non_sphere_authority(self):
        """Load the authenticated non-Sphere authority once per store.

        Proof-bound record reconstruction can visit the same authority surface
        hundreds of times while replaying a project.  The authority service
        verifies its sealed source files during construction, so recreating it
        for every record is both needlessly expensive and obscures the
        snapshot-vs-live boundary.  Callers may still inject a service for
        tests or an already-authenticated transaction.
        """
        authority = getattr(self, "_non_sphere_authority_cache", None)
        if authority is None:
            from non_sphere_authority import NonSphereAuthorityService

            authority = NonSphereAuthorityService(self.db)
            self._non_sphere_authority_cache = authority
        return authority

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

    # Tables whose rows exist only because the owner acted in the builder.
    OWNER_INPUT_TABLES = ("character_creation_runs", "character_creation_brief_edits")

    # User locks the builder writes at creation with a form default or a
    # computed value (CharacterBuilderService.create_project and the catalog
    # grant plan). The owner did not type these, so they are never owner input.
    SYSTEM_SEEDED_LOCK_FIELDS = frozenset({
        "source_reference",
        "target_cl",
        "power_band",
        "character_sheet.creation_mode",
        "character_sheet.generation_route",
        "character_sheet.method_planning_mode",
        "character_sheet.method_access_plan",
        "character_sheet.canonical_grant_plan",
        "character_sheet.canonical_grant_plan_origin",
        "character_sheet.canonical_character_projection",
        "character_sheet.path_method_compatibility",
    })
    # Locks that always hold a structure: the owner's part is this key.
    OWNER_CONTENT_KEY = {"character_sheet.ability_point_buy": "fixed_scores"}

    @staticmethod
    def _has_content(value: Any) -> bool:
        if isinstance(value, dict):
            return any(ProjectStore._has_content(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(ProjectStore._has_content(item) for item in value)
        if isinstance(value, str):
            return bool(value.strip())
        return value is not None and value is not False and value != 0

    @classmethod
    def _owner_typed_lock(cls, field: Any, value: Any) -> bool:
        if not isinstance(field, str) or field in cls.SYSTEM_SEEDED_LOCK_FIELDS:
            return False
        if field in cls.OWNER_CONTENT_KEY:
            return isinstance(value, dict) and cls._has_content(value.get(cls.OWNER_CONTENT_KEY[field]))
        return cls._has_content(value)

    @classmethod
    def _has_owner_input(cls, conn, project_id: str) -> bool:
        """True when the owner has typed or chosen anything in this project.

        Owner input is a user lock the owner filled in (name, concept, locked
        choices, planning and gear preferences, ability scores, sheet edits)
        plus build runs and brief edits. Builder defaults such as the source
        "Original character", the target level, the power band and the sealed
        catalog grant plan are written for every new character and do not count.
        Locked records count only when they come from outside the project's
        sealed catalog packs: sealing writes every catalog record into
        project_locked_records for every new project. Owner-authored records
        (custom training sources, constructed arts) live in their own packs and
        do count. Used by discard to decide between keeping and deleting.
        """
        row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return False
        project = json.loads(row["project_json"] or "{}")
        for lock in project.get("user_locks") or []:
            if isinstance(lock, dict) and cls._owner_typed_lock(lock.get("field"), lock.get("value")):
                return True
        if any(
            conn.execute(f"SELECT 1 FROM {table} WHERE project_id=? LIMIT 1", (project_id,)).fetchone() is not None
            for table in cls.OWNER_INPUT_TABLES
        ):
            return True
        # pack_id and version are matched together: the seal row is the exact pair.
        return conn.execute(
            """SELECT 1 FROM project_locked_records r WHERE r.project_id=?
               AND NOT EXISTS (
                   SELECT 1 FROM project_content_locks c
                   WHERE c.project_id=r.project_id AND c.pack_id=r.pack_id AND c.version=r.pack_version
               ) LIMIT 1""",
            (project_id,),
        ).fetchone() is not None

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
            has_attempt_history = conn.execute(
                "SELECT 1 FROM character_creation_attempt_history WHERE project_id=? LIMIT 1",
                (project_id,),
            ).fetchone() is not None
            # Start Over never destroys owner input. Anything the owner gave
            # (a name, concept, locked choice, sheet edit or build run) keeps the
            # project as a Saved Draft, exactly like recoverable attempt history.
            # Only a truly empty temporary character is deleted.
            if has_attempt_history or self._has_owner_input(conn, project_id):
                # A cancelled/replaced run is recoverable evidence.  Retain the
                # project as a non-temporary draft instead of allowing the
                # historical project CASCADE to erase immutable attempts.
                retention = "attempt_history" if has_attempt_history else "owner_input"
                self._set_builder_lifecycle(
                    conn,
                    project_id,
                    "saved_draft",
                    source=f"owner_discard_retained_{retention}",
                )
                # Provider runs reference the attempts the project cascade would erase,
                # so they go only on the attempt-history path. Owner-input drafts are
                # not deleted and keep their runs.
                if has_attempt_history:
                    conn.execute("DELETE FROM ai_provider_runs WHERE project_id=?", (project_id,))
                return {
                    "project_id": project_id,
                    "discarded": True,
                    "retained": True,
                    "reason": reason,
                    "retention": retention,
                }
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
                    """SELECT project_id FROM character_builder_project_lifecycle l
                       WHERE persistence_state='temporary' AND NOT EXISTS
                       (SELECT 1 FROM project_deletion_requests q WHERE q.project_id=l.project_id AND q.status IN ('queued','failed'))
                       ORDER BY project_id"""
                )
            ]
            skipped_project_ids = []
            retained_history_project_ids = []
            for project_id in project_ids:
                active_run = conn.execute(
                    "SELECT run_id FROM character_creation_runs WHERE project_id=? AND status IN ('PREPARING_REQUEST','WAITING_FOR_RESPONSE','READY_FOR_REVIEW','NEEDS_REVIEW') LIMIT 1",
                    (project_id,),
                ).fetchone()
                if active_run:
                    skipped_project_ids.append(project_id)
                    continue
                has_attempt_history = conn.execute(
                    "SELECT 1 FROM character_creation_attempt_history WHERE project_id=? LIMIT 1",
                    (project_id,),
                ).fetchone() is not None
                if has_attempt_history:
                    self._set_builder_lifecycle(
                        conn,
                        project_id,
                        "saved_draft",
                        source="startup_cleanup_retained_attempt_history",
                    )
                    retained_history_project_ids.append(project_id)
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
        removed_project_ids = [
            project_id
            for project_id in project_ids
            if project_id not in skipped_project_ids and project_id not in retained_history_project_ids
        ]
        return {
            "reason": reason,
            "removed_project_ids": removed_project_ids,
            "removed_count": len(removed_project_ids),
            "skipped_active_project_ids": skipped_project_ids,
            "retained_history_project_ids": retained_history_project_ids,
        }

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

    @staticmethod
    def _should_record_validation(boundary: str, *, valid: bool) -> bool:
        """Decide whether this validation earns a durable audit row.

        Every successful read boundary used to append a row and hash the whole
        object to fill it, so reading one project wrote to the database and
        hashed 10.5 MB.  That produced 337,810 rows and roughly 100 MB for
        seven projects while proving nothing a re-read could not.

        A failure is always recorded: it is rare and it is the only durable
        trace of what was rejected.  Successful reads are never recorded.
        Successful writes are recorded only when the owner opts in.
        """

        if not valid:
            return True
        if boundary.endswith("_reconstruct") or boundary in _READ_VALIDATION_BOUNDARIES:
            return False
        return _canonical_validation_audit_enabled()

    def _validate_or_raise(self, obj: dict[str, Any], *, boundary: str, family: str, key: str, conn=None) -> None:
        report = self.registry.report(obj)
        if conn is not None and self._should_record_validation(boundary, valid=report["valid"]):
            self._record_validation(
                conn,
                family=family,
                key=key,
                version=report["schema_version"],
                boundary=boundary,
                valid=report["valid"],
                diagnostics=report["diagnostics"],
                # Computed here rather than as an argument so a skipped audit
                # row also skips hashing the object.
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
        # The immutable record snapshot is part of the cache key.  Its byte
        # fingerprint (a SHA-256 of every row's stored JSON) is expensive for
        # a full project, so inside an operation scope it is computed once
        # per membership identity: the cheap identity query below (record
        # ids, packs, hashes; no JSON) guards reuse.  Locked rows cannot be
        # updated in place (schema trigger), so a changed byte set always
        # changes the identity or arrives with a new scope.
        identity_rows = [
            {
                "record_id": row["record_id"],
                "pack_id": row["pack_id"],
                "pack_version": row["pack_version"],
                "record_hash": row["snapshot_record_identity"],
            }
            for row in conn.execute(
                """SELECT record_id,pack_id,pack_version,
                          record_hash AS snapshot_record_identity
                   FROM project_locked_records WHERE project_id=? ORDER BY record_id""",
                (project_id,),
            )
        ]
        fingerprint_cache = _PROJECT_LOCK_SCOPE_MEMO.get()
        fingerprint_key = (
            "fingerprint",
            id(self.db),
            str(project_id),
            sha256_json({"locks": locks, "record_identity": identity_rows}),
        )
        cache_snapshot_rows = (
            fingerprint_cache.get(fingerprint_key) if fingerprint_cache is not None else None
        )
        if cache_snapshot_rows is None:
            cache_snapshot_rows = [
                {
                    "record_id": row["record_id"],
                    "pack_id": row["pack_id"],
                    "pack_version": row["pack_version"],
                    "record_hash": row["record_hash"],
                    "record_json_sha256": sha256_bytes(
                        row["snapshot_record_json"].encode("utf-8")
                        if isinstance(row["snapshot_record_json"], str)
                        else bytes(row["snapshot_record_json"])
                    ),
                }
                for row in conn.execute(
                    """SELECT record_id,pack_id,pack_version,record_hash,
                              record_json AS snapshot_record_json
                       FROM project_locked_records WHERE project_id=? ORDER BY record_id""",
                    (project_id,),
                )
            ]
            if fingerprint_cache is not None:
                fingerprint_cache[fingerprint_key] = cache_snapshot_rows
        proof_cache = _PROJECT_LOCK_PROOF_CACHE.get()
        proof_cache_key = (
            id(self.db),
            str(project_id),
            sha256_json({"locks": locks, "record_snapshot": cache_snapshot_rows}),
        )
        if proof_cache is not None:
            cached_proof = proof_cache.get(proof_cache_key)
            if cached_proof is not None:
                return deepcopy(cached_proof)
        seal_cache = _PROJECT_LOCK_PROOF_SEAL_CACHE.get()
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

            seal = self.verified_pack_seal(conn, lock["pack_id"], lock["version"], lock["pack_hash"])
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
        extra_record_ids = set(actual_rows) - set(expected_members)
        unauthorized_extra: list[str] = []
        from character_creation.constructed_arts.records import CONSTRUCTED_ART_PACK_IDS
        from character_creation.custom_training_source_authority import CUSTOM_TRAINING_SOURCE_PACK_ID

        for record_id in sorted(extra_record_ids):
            raw_record = actual_rows[record_id].get("record_json")
            try:
                record = json.loads(raw_record)
            except (TypeError, json.JSONDecodeError):
                record = None
            binding = record.get("content_binding") if isinstance(record, dict) and isinstance(record.get("content_binding"), dict) else {}
            if not isinstance(record, dict) or binding.get("pack_id") not in {
                "tianxia.non_sphere.authority",
                CUSTOM_TRAINING_SOURCE_PACK_ID,
                *CONSTRUCTED_ART_PACK_IDS,
            }:
                unauthorized_extra.append(record_id)
                continue
            # Server-frozen non-Sphere projections are outside the HF2 pack
            # membership set, but remain part of this immutable project
            # authority boundary and must be validated against their registry.
            self._assert_snapshot_record(conn, project_id, record)
        missing_record_ids = set(expected_members) - set(actual_rows)
        if missing_record_ids or unauthorized_extra:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_INCOMPLETE",
                "The project record snapshot is not the complete immutable membership of its locked pack set.",
                details={
                    "project_id": project_id,
                    "missing": sorted(missing_record_ids),
                    "extra": unauthorized_extra,
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
        for record_id in sorted(extra_record_ids):
            actual = actual_rows[record_id]
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
        complete_proof = {**proof, "lock_proof_hash": sha256_json(proof)}
        if proof_cache is not None:
            proof_cache[proof_cache_key] = deepcopy(complete_proof)
        return deepcopy(complete_proof)

    @staticmethod
    def _custom_training_source_approval_binding(
        project_id: str,
        normalized: dict[str, Any],
        record: dict[str, Any],
        project_row: Any,
        proof_before: dict[str, Any],
    ) -> dict[str, Any]:
        contract = record["compatibility"]["factory"]["custom_training_source"]
        return {
            "schema_version": "TianxiaFoundry.ProjectCustomTrainingSourceApprovalBinding.v1",
            "project_id": project_id,
            "project_revision": int(project_row["revision"]),
            "project_canonical_hash": project_row["canonical_project_hash"],
            "route_id": normalized["route_id"],
            "owner_confirmation_id": normalized["owner_confirmation_id"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
            "source_id": record["source"]["source_id"],
            "source_hash": record["source"]["source_hash"],
            "source_path": record["source"]["path"],
            "source_anchor": record["source"]["anchor"],
            "access_mode": normalized["access_mode"],
            "training_types": list(normalized["training_types"]),
            "target_record_ids": list(contract["target_record_ids"]),
            "project_lock_proof_hash": proof_before["lock_proof_hash"],
        }

    @staticmethod
    def _custom_training_source_evidence_context(
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": "TianxiaFoundry.ProjectCustomTrainingSourceApprovalContext.v1",
            "project_id": binding["project_id"],
            "record_id": binding["record_id"],
            "record_hash": binding["record_hash"],
            "source_id": binding["source_id"],
            "source_hash": binding["source_hash"],
            "route_id": binding["route_id"],
            "project_lock_proof_hash": binding["project_lock_proof_hash"],
        }

    def _validate_custom_training_source_targets(
        self,
        conn,
        project_id: str,
        record: dict[str, Any],
    ) -> list[dict[str, Any]]:
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE,
        )

        contract = record["compatibility"]["factory"]["custom_training_source"]
        allowed_types = {
            CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE[item]
            for item in contract["training_types"]
        }
        target_identities: list[dict[str, Any]] = []
        for target_id in contract["target_record_ids"]:
            if target_id == record["record_id"]:
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training source cannot target itself.",
                    details={"record_id": record["record_id"], "target_record_id": target_id},
                )
            target_row = conn.execute(
                "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                (project_id, target_id),
            ).fetchone()
            if not target_row:
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "Every custom training-source target must already be in the immutable project snapshot.",
                    details={"record_id": record["record_id"], "target_record_id": target_id},
                )
            try:
                target = json.loads(target_row["record_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training-source target is not valid canonical JSON.",
                    details={"target_record_id": target_id},
                ) from exc
            publication = target.get("publication") if isinstance(target, dict) else None
            compatibility = target.get("compatibility") if isinstance(target, dict) else None
            factory = compatibility.get("factory") if isinstance(compatibility, dict) else None
            stage2_authority = factory.get("stage2_authority") if isinstance(factory, dict) else None
            if (
                not isinstance(target, dict)
                or canonical_json(target) != target_row["record_json"]
                or target.get("record_hash") != target_row["record_hash"]
                or canonical_record_hash(target) != target.get("record_hash")
                or not isinstance(publication, dict)
                or publication.get("status") != "published"
                or target.get("content_type") not in allowed_types
                or not isinstance(target.get("display_name"), str)
                or not target["display_name"].strip()
                or not isinstance(stage2_authority, dict)
                or stage2_authority.get("authority_complete") is not True
            ):
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training-source target is not a published supported canonical record.",
                    details={"target_record_id": target_id, "allowed_content_types": sorted(allowed_types)},
                )
            report = self.registry.report(target)
            if not report["valid"]:
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training-source target fails canonical record validation.",
                    details={"target_record_id": target_id, "diagnostics": report["diagnostics"]},
                )
            target_identities.append(
                {
                    "record_id": target["record_id"],
                    "display_name": target["display_name"],
                    "content_type": target["content_type"],
                    "record_hash": target_row["record_hash"],
                }
            )
        return target_identities

    @staticmethod
    def _reject_unbound_selected_ai_custom_training_source(
        normalized: dict[str, Any],
    ) -> None:
        """Keep the generic owner-envelope path closed to selected-AI bytes.

        The selected-AI route is only a contract label until a separate
        server-owned proposal flow binds the generated proposal to the exact
        bytes, project, and review.  The generic challenge/seal path must not
        turn an owner envelope into such a proposal merely because its route
        field says selected-AI.
        """
        if normalized.get("route_id") != "selected_ai_custom_training_source":
            return
        raise FoundryError(
            "CUSTOM_TRAINING_SOURCE_AI_PROPOSAL_REQUIRED",
            "The selected-AI route requires a separate server-owned generated-proposal identifier and exact proposal-to-bytes/project/review binding.",
            details={
                "route_id": normalized.get("route_id"),
                "required_binding": "server_owned_generated_proposal_identifier_and_exact_proposal_to_bytes_project_review_binding",
            },
            status_code=409,
        )

    def _custom_training_source_snapshot(self, project_id: str) -> dict[str, Any]:
        """Return the authenticated immutable records used by custom-source APIs.

        Discovery and target lookup are deliberately project-lock scoped.  They
        never fall back to the live catalog: every returned record must be the
        exact canonical JSON/hash pair already held by this project and must
        satisfy the installed schema.  The lock proof itself remains the
        authority for pack membership and authorized project extras.
        """
        with self.db.connection() as conn:
            project_row = conn.execute(
                "SELECT project_id FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if not project_row:
                raise FoundryError(
                    "PROJECT_NOT_FOUND",
                    "No character project has that ID.",
                    status_code=404,
                )
            proof = self.project_lock_proof(conn, project_id)
            rows = conn.execute(
                """SELECT record_id,pack_id,pack_version,record_hash,record_json
                   FROM project_locked_records WHERE project_id=? ORDER BY record_id""",
                (project_id,),
            ).fetchall()
            records: list[dict[str, Any]] = []
            for row in rows:
                try:
                    record = json.loads(row["record_json"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise FoundryError(
                        "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                        "A project-locked record is not canonical JSON.",
                        details={"project_id": project_id, "record_id": row["record_id"]},
                    ) from exc
                try:
                    record_hash = canonical_record_hash(record)
                except (TypeError, ValueError, KeyError) as exc:
                    raise FoundryError(
                        "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                        "A project-locked record cannot reproduce its canonical hash.",
                        details={"project_id": project_id, "record_id": row["record_id"]},
                    ) from exc
                if (
                    not isinstance(record, dict)
                    or record.get("record_id") != row["record_id"]
                    or record.get("record_hash") != row["record_hash"]
                    or record_hash != row["record_hash"]
                    or canonical_json(record) != row["record_json"]
                ):
                    raise FoundryError(
                        "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                        "A project-locked record is not an exact schema-valid canonical snapshot.",
                        details={
                            "project_id": project_id,
                            "record_id": row["record_id"],
                        },
                    )
                records.append({
                    "record_id": row["record_id"],
                    "pack_id": row["pack_id"],
                    "pack_version": row["pack_version"],
                    "record_hash": row["record_hash"],
                    "record": record,
                })
            return {"project_id": project_id, "lock_proof": proof, "records": records}

    def _authenticated_canonical_training_source_options(
        self,
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return only deeply authenticated canonical training-source options.

        The contract endpoint is an owner-facing discovery surface, so it must
        not turn the presence of a vaguely-shaped Stage-2 field into an
        actionable canonical route.  Every source and target below comes from
        the same project-lock snapshot already authenticated by
        ``_custom_training_source_snapshot``.
        """
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE,
        )

        source_content_types = {
            "source_document",
            "sphere",
            "tradition",
            "item",
            "companion",
            "manual",
            "martial_manual",
            "manual_expression",
        }
        lock_hashes = {
            (lock["pack_id"], lock["version"]): lock["pack_hash"]
            for lock in snapshot["lock_proof"].get("locks", [])
            if isinstance(lock, dict)
        }
        by_id = {row["record_id"]: row for row in snapshot["records"]}

        def clean_list(value: Any, *, maximum: int) -> list[str] | None:
            if not isinstance(value, list) or not value or len(value) > maximum:
                return None
            if any(
                not isinstance(item, str)
                or not item
                or item != item.strip()
                or any(ord(char) < 32 for char in item)
                for item in value
            ):
                return None
            if len(set(value)) != len(value):
                return None
            return list(value)

        options: list[dict[str, Any]] = []
        for row in snapshot["records"]:
            record = row["record"]
            if record.get("content_type") not in source_content_types:
                continue
            factory = (record.get("compatibility") or {}).get("factory")
            stage2 = factory.get("stage2_authority") if isinstance(factory, dict) else None
            access = stage2.get("training_source_access") if isinstance(stage2, dict) else None
            binding = record.get("content_binding")
            publication = record.get("publication")
            lock_hash = lock_hashes.get((row["pack_id"], row["pack_version"]))
            if (
                not isinstance(factory, dict)
                or not isinstance(stage2, dict)
                or stage2.get("authority_complete") is not True
                or not isinstance(stage2.get("allowed_kinds"), list)
                or "training_source_access" not in stage2["allowed_kinds"]
                or not isinstance(access, dict)
                or access.get("mode") != "requires_access_event"
                or not isinstance(binding, dict)
                or binding.get("pack_id") != row["pack_id"]
                or binding.get("pack_version") != row["pack_version"]
                or (lock_hash is not None and binding.get("pack_hash") != lock_hash)
                or not isinstance(publication, dict)
                or publication.get("status") != "published"
                or record.get("custom_design") is True
                or factory.get("custom_design") is True
                or record.get("authority") in {"user_directive", "original_design", "inspiration_source"}
                or factory.get("authority_classification") in {"user_directive", "original_design", "inspiration_source"}
            ):
                continue
            if "access_modes" in access:
                access_modes_value = access.get("access_modes")
            elif record.get("content_type") in {"manual", "martial_manual", "manual_expression"}:
                manual = stage2.get("manual")
                access_modes_value = manual.get("access_modes") if isinstance(manual, dict) else None
            else:
                access_modes_value = None
            access_modes = clean_list(access_modes_value, maximum=50)
            training_types = clean_list(access.get("training_types"), maximum=3)
            target_record_ids = clean_list(access.get("target_record_ids"), maximum=50)
            if access_modes is None or training_types is None or target_record_ids is None:
                continue
            if any(training_type not in CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE for training_type in training_types):
                continue
            expected_target_types = {
                CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE[training_type]
                for training_type in training_types
            }
            target_identities: list[dict[str, Any]] = []
            valid_targets = True
            for target_id in target_record_ids:
                target_row = by_id.get(target_id)
                if target_row is None or target_id == row["record_id"]:
                    valid_targets = False
                    break
                target = target_row["record"]
                target_factory = (target.get("compatibility") or {}).get("factory")
                target_stage2 = target_factory.get("stage2_authority") if isinstance(target_factory, dict) else None
                target_binding = target.get("content_binding")
                target_publication = target.get("publication")
                if (
                    target.get("content_type") not in expected_target_types
                    or not isinstance(target_publication, dict)
                    or target_publication.get("status") != "published"
                    or not isinstance(target_stage2, dict)
                    or target_stage2.get("authority_complete") is not True
                    or not isinstance(target.get("display_name"), str)
                    or not target["display_name"].strip()
                    or not isinstance(target_binding, dict)
                or target_binding.get("pack_id") != target_row["pack_id"]
                or target_binding.get("pack_version") != target_row["pack_version"]
                or (
                    lock_hashes.get((target_row["pack_id"], target_row["pack_version"])) is not None
                    and target_binding.get("pack_hash") != lock_hashes[(target_row["pack_id"], target_row["pack_version"])]
                )
                ):
                    valid_targets = False
                    break
                if not self.registry.report(target).get("valid"):
                    valid_targets = False
                    break
                target_identities.append(
                    {
                        "record_id": target_id,
                        "display_name": target.get("display_name"),
                        "content_type": target.get("content_type"),
                        "record_hash": target_row["record_hash"],
                    }
                )
            if not valid_targets or not self.registry.report(record).get("valid"):
                continue
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            options.append(
                {
                    "record_id": row["record_id"],
                    "record_hash": row["record_hash"],
                    "content_type": record["content_type"],
                    "display_name": record.get("display_name"),
                    "source_path": source.get("path"),
                    "access_modes": access_modes,
                    "training_types": training_types,
                    "target_record_ids": target_record_ids,
                    "target_identities": target_identities,
                }
            )
        options.sort(key=lambda item: (str(item.get("display_name") or "").casefold(), item["record_id"]))
        return options

    def custom_training_source_contract(self, project_id: str) -> dict[str, Any]:
        """Describe the owner decision required for manual-lineage training."""
        snapshot = self._custom_training_source_snapshot(project_id)
        canonical_records = self._authenticated_canonical_training_source_options(snapshot)
        exposed_records = canonical_records[:50]
        canonical_count = len(canonical_records)
        canonical_truncated = canonical_count > len(exposed_records)
        routes = [
            {
                "route_id": "selected_ai_custom_training_source",
                "requirements": "Requires an explicit owner-started AI proposal; discovery never calls a provider.",
                "available": True,
                "actionable_now": False,
                "availability_status": "requires_explicit_ai_proposal",
                "selection": "Not auto-selected.",
                "review": "Candidate/binding review must be regenerated.",
                "candidate_revision": "A new candidate revision is required.",
            },
            {
                "route_id": "owner_supplied_custom_training_source",
                "requirements": "Requires explicit owner-supplied source fields and a user directive.",
                "available": True,
                "actionable_now": True,
                "availability_status": "available_for_owner_entry",
                "selection": "Not auto-selected.",
                "review": "Candidate/binding review must be regenerated.",
                "candidate_revision": "A new candidate revision is required.",
            },
            {
                "route_id": "locked_canonical_training_source",
                "requirements": "Requires an authenticated project-locked canonical training-source record and exact packet.",
                "available": bool(exposed_records),
                "actionable_now": bool(exposed_records),
                "availability_status": "available" if exposed_records else "unavailable_no_authenticated_project_locked_source",
                "record_ids": [item["record_id"] for item in exposed_records],
                "total_count": canonical_count,
                "truncated": canonical_truncated,
                "selection": "Not auto-selected.",
                "review": "Candidate/binding review must be regenerated.",
                "candidate_revision": "A new candidate revision is required.",
            },
        ]
        return {
            "schema": "TianxiaFoundry.ManualLineageTrainingSourceContract.v1",
            "project_id": project_id,
            "slot_id": "manual_lineage_training_source",
            "requirement": "one source-backed training source",
            "selected_route": None,
            "resolution_routes": routes,
            "locked_canonical_records": exposed_records,
            "locked_canonical_record_count": canonical_count,
            "locked_canonical_records_truncated": canonical_truncated,
            "lock_proof_hash": snapshot["lock_proof"]["lock_proof_hash"],
            "owner_warning": "No route is selected automatically. Any sealed source requires a new candidate revision and regenerated candidate/binding review.",
        }

    def search_custom_training_source_targets(
        self,
        project_id: str,
        training_type: str,
        *,
        query: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search only authenticated legal targets in this project's lock."""
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_SOURCE_PACK_ID,
            CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE,
        )

        content_type = CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE.get(training_type)
        if content_type is None:
            raise FoundryError(
                "CUSTOM_TRAINING_SOURCE_TARGET_TYPE_INVALID",
                "The requested training type is not part of the supported target contract.",
                details={"training_type": training_type},
            )
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
            raise FoundryError(
                "CUSTOM_TRAINING_SOURCE_TARGET_LIMIT_INVALID",
                "Target search limit must be between 1 and 50.",
                details={"limit": limit},
            )
        if query is not None and (not isinstance(query, str) or query != query.strip() or len(query) > 200):
            raise FoundryError(
                "CUSTOM_TRAINING_SOURCE_TARGET_QUERY_INVALID",
                "Target search query must be a bounded trimmed string.",
                details={"query": query},
            )
        snapshot = self._custom_training_source_snapshot(project_id)
        needle = query.casefold() if query else ""
        matches: list[dict[str, Any]] = []
        for row in snapshot["records"]:
            record = row["record"]
            factory = (record.get("compatibility") or {}).get("factory")
            stage2 = factory.get("stage2_authority") if isinstance(factory, dict) else None
            publication = record.get("publication")
            binding = record.get("content_binding")
            if (
                record.get("content_type") != content_type
                or not isinstance(publication, dict)
                or publication.get("status") != "published"
                or not isinstance(factory, dict)
                or not isinstance(stage2, dict)
                or stage2.get("authority_complete") is not True
                or not isinstance(binding, dict)
                or binding.get("pack_id") == CUSTOM_TRAINING_SOURCE_PACK_ID
                or factory.get("custom_design") is True
                or factory.get("authority_classification") in {"user_directive", "original_design", "inspiration_source"}
                or record.get("authority") in {"user_directive", "original_design", "inspiration_source"}
            ):
                continue
            if not self.registry.report(record).get("valid"):
                continue
            aliases = record.get("aliases") if isinstance(record.get("aliases"), list) else []
            display_name = record.get("display_name")
            description = record.get("display_projection", {}).get("short_description") if isinstance(record.get("display_projection"), dict) else None
            description = description or record.get("summary") or ""
            search_text = " ".join([str(record.get("record_id") or ""), str(display_name or ""), str(description), *(str(item) for item in aliases)])
            if needle and needle not in search_text.casefold():
                continue
            matches.append({
                "record_id": row["record_id"],
                "display_name": display_name,
                "content_type": content_type,
                "description": description,
                "record_hash": row["record_hash"],
            })
        matches.sort(key=lambda item: (str(item.get("display_name") or "").casefold(), item["record_id"]))
        return {
            "schema": "TianxiaFoundry.ManualLineageTrainingTargetSearch.v1",
            "project_id": project_id,
            "training_type": training_type,
            "content_type": content_type,
            "query": query,
            "limit": limit,
            "count": len(matches[:limit]),
            "records": matches[:limit],
            "lock_proof_hash": snapshot["lock_proof"]["lock_proof_hash"],
        }

    def custom_training_source_target_preview(
        self,
        project_id: str,
        target_record_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Return stable owner display identities for already-authenticated targets."""
        snapshot = self._custom_training_source_snapshot(project_id)
        by_id = {row["record_id"]: row for row in snapshot["records"]}
        result: list[dict[str, Any]] = []
        for record_id in target_record_ids:
            row = by_id.get(record_id)
            if row is None:
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "The requested target is not in the project's authenticated lock.",
                    details={"project_id": project_id, "target_record_id": record_id},
                )
            record = row["record"]
            if not self.registry.report(record).get("valid"):
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "The requested target is not a schema-valid canonical record.",
                    details={"project_id": project_id, "target_record_id": record_id},
                )
            result.append({
                "record_id": record_id,
                "display_name": record.get("display_name"),
                "content_type": record.get("content_type"),
                "record_hash": row["record_hash"],
            })
        return result

    def _prepare_custom_training_source(
        self,
        conn,
        project_id: str,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        from character_creation.custom_training_source_authority import (
            build_custom_training_source_record,
            normalize_custom_training_source,
        )

        normalized = normalize_custom_training_source(envelope)
        self._reject_unbound_selected_ai_custom_training_source(normalized)
        record = build_custom_training_source_record(normalized)
        project_row = conn.execute(
            "SELECT project_id,revision,project_json,canonical_project_hash FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if not project_row:
            raise FoundryError(
                "PROJECT_NOT_FOUND",
                "No character project has that ID.",
                status_code=404,
            )
        proof_before = self.project_lock_proof(conn, project_id)
        target_identities = self._validate_custom_training_source_targets(conn, project_id, record)
        self._validate_or_raise(
            record,
            boundary="custom_training_source_seal",
            family="rules_catalog_record",
            key=record["record_id"],
            conn=conn,
        )
        binding = self._custom_training_source_approval_binding(
            project_id,
            normalized,
            record,
            project_row,
            proof_before,
        )
        return {
            "normalized": normalized,
            "record": record,
            "project_row": project_row,
            "proof_before": proof_before,
            "binding": binding,
            "target_identities": target_identities,
            "exact_bytes": canonical_json(record).encode("utf-8"),
        }

    def _insert_custom_training_source(
        self,
        conn,
        material: dict[str, Any],
        approval_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_SOURCE_PACK_ID,
            CUSTOM_TRAINING_SOURCE_PACK_VERSION,
        )

        project_id = material["binding"]["project_id"]
        normalized = material["normalized"]
        record = material["record"]
        contract = record["compatibility"]["factory"]["custom_training_source"]
        existing = conn.execute(
            "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record["record_id"]),
        ).fetchone()
        if existing:
            exact = (
                existing["pack_id"] == CUSTOM_TRAINING_SOURCE_PACK_ID
                and existing["pack_version"] == CUSTOM_TRAINING_SOURCE_PACK_VERSION
                and existing["record_hash"] == record["record_hash"]
                and existing["record_json"] == material["exact_bytes"].decode("utf-8")
            )
            if not exact:
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_CONFLICT",
                    "The deterministic custom training-source identity is already bound to different bytes.",
                    details={"project_id": project_id, "record_id": record["record_id"]},
                )
            status = "idempotent"
        else:
            conn.execute(
                "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                (
                    project_id,
                    record["record_id"],
                    CUSTOM_TRAINING_SOURCE_PACK_ID,
                    CUSTOM_TRAINING_SOURCE_PACK_VERSION,
                    record["record_hash"],
                    material["exact_bytes"].decode("utf-8"),
                ),
            )
            status = "inserted"

        proof_after = self.project_lock_proof(conn, project_id)
        receipt = {
            "schema": "TianxiaFoundry.ProjectCustomTrainingSourceSeal.v1",
            "project_id": project_id,
            "route_id": normalized["route_id"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
            "source_id": record["source"]["source_id"],
            "source_hash": record["source"]["source_hash"],
            "target_record_ids": list(contract["target_record_ids"]),
            "lock_proof_hash_before": material["proof_before"]["lock_proof_hash"],
            "lock_proof_hash_after": proof_after["lock_proof_hash"],
            "record_snapshot_hash_before": material["proof_before"]["record_snapshot_hash"],
            "record_snapshot_hash_after": proof_after["record_snapshot_hash"],
            "status": status,
        }
        if approval_evidence is not None:
            principal = approval_evidence["principal"]
            challenge = approval_evidence["challenge"]
            receipt["approval"] = {
                "schema": "TianxiaFoundry.ProjectCustomTrainingSourceApprovalEvidence.v1",
                "challenge_id": challenge["challenge_id"],
                "challenge_hash": approval_evidence["challenge_hash"],
                "evidence_id": approval_evidence["evidence_id"],
                "evidence_hash": approval_evidence["evidence_hash"],
                "principal_id": principal["principal_id"],
                "principal_hash": sha256_json(principal),
                "binding_hash": approval_evidence["binding_hash"],
                "project_lock_proof_hash": approval_evidence["project_lock_hash"],
            }
        return receipt

    def issue_custom_training_source_challenge(
        self,
        project_id: str,
        envelope: dict[str, Any],
        *,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        """Issue one exact-byte approval challenge for a custom source."""
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION,
            CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE,
        )

        with self.db.connection() as conn:
            material = self._prepare_custom_training_source(conn, project_id, envelope)
        binding = material["binding"]
        exact_bytes = material["exact_bytes"]
        preview = {
            "schema": "TianxiaFoundry.ProjectCustomTrainingSourceExactPreview.v1",
            "route_id": material["normalized"]["route_id"],
            "display_name": material["normalized"]["display_name"],
            "summary": material["normalized"]["summary"],
            "source_text": material["normalized"]["source_text"],
            "source_anchor": material["normalized"]["source_anchor"],
            "source_path": material["normalized"]["source_path"],
            "source_text_sha256": material["normalized"]["source_text_sha256"],
            "access_mode": material["normalized"]["access_mode"],
            "training_types": list(material["normalized"]["training_types"]),
            "target_record_ids": list(material["normalized"]["target_record_ids"]),
            "target_identities": deepcopy(material["target_identities"]),
            "record_id": material["record"]["record_id"],
            "record_hash": material["record"]["record_hash"],
            "exact_record_bytes_sha256": sha256_bytes(exact_bytes),
            "binding": deepcopy(binding),
            "project_lock_proof_hash": material["proof_before"]["lock_proof_hash"],
            "seals_nothing": True,
        }
        challenge = self.challenges.issue(
            operation=CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION,
            subject_type=CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE,
            subject_id=material["record"]["record_id"],
            exact_bytes=exact_bytes,
            binding=binding,
            project_lock_hash=material["proof_before"]["lock_proof_hash"],
            ttl_seconds=ttl_seconds,
        )
        if preview["exact_record_bytes_sha256"] != challenge["challenge"]["exact_bytes_hash"]:
            raise FoundryError(
                "PROJECT_CUSTOM_TRAINING_SOURCE_PREVIEW_MISMATCH",
                "The human preview does not bind the exact bytes sealed by the approval challenge.",
                details={
                    "preview_exact_record_bytes_sha256": preview["exact_record_bytes_sha256"],
                    "challenge_exact_bytes_hash": challenge["challenge"]["exact_bytes_hash"],
                },
                status_code=409,
            )
        return {
            "schema": "TianxiaFoundry.ProjectCustomTrainingSourceApprovalChallenge.v1",
            "project_id": project_id,
            "route_id": material["normalized"]["route_id"],
            "record_id": material["record"]["record_id"],
            "record_hash": material["record"]["record_hash"],
            "source_id": material["record"]["source"]["source_id"],
            "source_hash": material["record"]["source"]["source_hash"],
            "target_record_ids": list(binding["target_record_ids"]),
            "binding": deepcopy(binding),
            "project_lock_proof_hash": material["proof_before"]["lock_proof_hash"],
            "preview": preview,
            **challenge,
        }

    def approve_and_seal_custom_training_source(
        self,
        project_id: str,
        envelope: dict[str, Any],
        challenge_id: str,
        nonce: str,
    ) -> dict[str, Any]:
        """Consume a one-time challenge and atomically insert the exact source."""
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION,
            CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE,
        )

        with self.db.connection() as conn:
            initial = self._prepare_custom_training_source(conn, project_id, envelope)
        initial_binding = initial["binding"]
        initial_exact = initial["exact_bytes"]
        initial_lock_hash = initial["proof_before"]["lock_proof_hash"]
        evidence_context = self._custom_training_source_evidence_context(initial_binding)

        def protected_seal(conn, approval_evidence):
            current = self._prepare_custom_training_source(conn, project_id, envelope)
            if (
                current["exact_bytes"] != initial_exact
                or current["binding"] != initial_binding
                or current["proof_before"]["lock_proof_hash"] != initial_lock_hash
            ):
                raise FoundryError(
                    "PROJECT_CUSTOM_TRAINING_SOURCE_APPROVAL_MATERIAL_CHANGED",
                    "The project, source, target bindings, or exact record changed before approval consumption.",
                    status_code=409,
                )
            return self._insert_custom_training_source(conn, current, approval_evidence)

        _evidence, receipt = self.challenges.consume_with_action(
            challenge_id=challenge_id,
            nonce=nonce,
            operation=CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION,
            subject_type=CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE,
            subject_id=initial["record"]["record_id"],
            exact_bytes=initial_exact,
            binding=initial_binding,
            project_lock_hash=initial_lock_hash,
            evidence_context=evidence_context,
            action=protected_seal,
        )
        assert receipt is not None
        return receipt

    def seal_custom_training_source(
        self,
        project_id: str,
        envelope: dict[str, Any],
        *,
        challenge_id: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper requiring an exact one-time approval."""
        if not challenge_id or not nonce:
            from character_creation.custom_training_source_authority import normalize_custom_training_source

            normalized = normalize_custom_training_source(envelope)
            self._reject_unbound_selected_ai_custom_training_source(normalized)
            raise FoundryError(
                "APPROVAL_CHALLENGE_REQUIRED",
                "Custom training-source sealing requires an explicitly issued one-time exact-byte challenge.",
                status_code=409,
            )
        return self.approve_and_seal_custom_training_source(
            project_id,
            envelope,
            challenge_id,
            nonce,
        )

    def add_server_locked_records(self, project_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Freeze source-backed non-pack records offered by a server request.

        The ordinary HF2 snapshot already contains every pack member.  A small
        set of authenticated non-Sphere authorities (notably initial Methods)
        is intentionally outside that pack, so a delegated response can name
        an offered record without turning the live registry into a compilation
        fallback.  This server-only insertion adds the exact normalized
        projection before the request is sealed; it never changes the owner
        revision or accepts response content.
        """
        normalized = [record for record in records if isinstance(record, dict)]
        if not normalized:
            return self.get_project(project_id)
        from non_sphere_authority import NonSphereAuthorityService

        authority = NonSphereAuthorityService(self.db)
        with self.db.transaction() as conn:
            project = conn.execute(
                "SELECT project_id FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if not project:
                raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
            lock_proof_verified = False
            for record in normalized:
                record_id = record.get("record_id")
                binding = record.get("content_binding") if isinstance(record.get("content_binding"), dict) else {}
                if not isinstance(record_id, str) or binding.get("pack_id") != "tianxia.non_sphere.authority":
                    raise FoundryError(
                        "PROJECT_SERVER_LOCK_RECORD_INVALID",
                        "Only authenticated non-Sphere authority projections may be added to a project snapshot.",
                        details={"record_id": record_id},
                        status_code=409,
                    )
                expected = authority.reconstruct_locked_method_catalog_record(record)
                if canonical_json(expected) != canonical_json(record):
                    raise FoundryError(
                        "PROJECT_SERVER_LOCK_RECORD_MISMATCH",
                        "The server-provided non-Sphere projection does not match the installed authority.",
                        details={"record_id": record_id},
                        status_code=409,
                    )
                self._validate_or_raise(
                    record,
                    boundary="server_locked_record_create",
                    family="rules_catalog_record",
                    key=record_id,
                    conn=conn,
                )
                existing = conn.execute(
                    "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                    (project_id, record_id),
                ).fetchone()
                if existing:
                    exact_server_projection = (
                        existing["pack_id"] == binding.get("pack_id")
                        and existing["pack_version"] == binding.get("pack_version")
                        and existing["record_hash"] == record.get("record_hash")
                        and existing["record_json"] == canonical_json(record)
                    )
                    if exact_server_projection:
                        continue
                    if existing["pack_id"] != "tianxia.non_sphere.authority":
                        # The Stage 1 prompt prefers an exact record already in
                        # the project's sealed pack snapshot.  Some historical
                        # Method IDs also exist in the newer non-Sphere registry;
                        # that registry projection must not replace or conflict
                        # with the immutable packed bytes.  Prove the complete
                        # snapshot before treating the packed row as canonical.
                        if not lock_proof_verified:
                            self.project_lock_proof(conn, project_id)
                            lock_proof_verified = True
                        continue
                    raise FoundryError(
                        "PROJECT_LOCK_RECORD_ID_CONFLICT",
                        "A source-backed record ID is already frozen to different immutable bytes.",
                        details={"project_id": project_id, "record_id": record_id},
                        status_code=409,
                    )
                conn.execute(
                    "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                    (
                        project_id,
                        record_id,
                        binding["pack_id"],
                        binding["pack_version"],
                        record["record_hash"],
                        canonical_json(record),
                    ),
                )
        return self.get_project(project_id)

    def _assert_custom_training_source_snapshot_record(self, conn, project_id: str, record: dict[str, Any]) -> None:
        """Authenticate one project-scoped custom source and its locked targets."""
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_SOURCE_PACK_ID,
            CUSTOM_TRAINING_SOURCE_PACK_VERSION,
            CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE,
            validate_custom_training_source_record,
        )

        binding = record.get("content_binding") if isinstance(record, dict) and isinstance(record.get("content_binding"), dict) else {}
        if binding.get("pack_id") != CUSTOM_TRAINING_SOURCE_PACK_ID:
            raise FoundryError(
                "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_INVALID",
                "The project-scoped custom training source has an unsupported pack identity.",
                details={"project_id": project_id, "record_id": record.get("record_id")},
            )
        if binding.get("pack_version") != CUSTOM_TRAINING_SOURCE_PACK_VERSION:
            raise FoundryError(
                "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_INVALID",
                "The project-scoped custom training source has an unsupported pack version.",
                details={"project_id": project_id, "record_id": record.get("record_id")},
            )
        row = conn.execute(
            "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record.get("record_id")),
        ).fetchone()
        if not row or (
            row["pack_id"] != CUSTOM_TRAINING_SOURCE_PACK_ID
            or row["pack_version"] != CUSTOM_TRAINING_SOURCE_PACK_VERSION
            or row["record_hash"] != record.get("record_hash")
            or row["record_json"] != canonical_json(record)
        ):
            raise FoundryError(
                "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_INVALID",
                "The custom training source row does not match its immutable project binding.",
                details={"project_id": project_id, "record_id": record.get("record_id")},
            )
        self._validate_or_raise(
            record,
            boundary="custom_training_source_snapshot",
            family="rules_catalog_record",
            key=str(record.get("record_id")),
            conn=conn,
        )
        try:
            contract = validate_custom_training_source_record(record)
        except FoundryError as exc:
            raise FoundryError(
                "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_INVALID",
                "The custom training source does not reproduce its deterministic authority contract.",
                details=exc.details,
            ) from exc
        allowed_types = {
            CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE[item]
            for item in contract["training_types"]
        }
        for target_id in contract["target_record_ids"]:
            if target_id == record.get("record_id"):
                raise FoundryError(
                    "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training source cannot target itself.",
                    details={"project_id": project_id, "record_id": record.get("record_id")},
                )
            target_row = conn.execute(
                "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                (project_id, target_id),
            ).fetchone()
            if not target_row:
                raise FoundryError(
                    "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "Every custom training-source target must already be in the immutable project snapshot.",
                    details={"project_id": project_id, "record_id": record.get("record_id"), "target_record_id": target_id},
                )
            try:
                target = json.loads(target_row["record_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise FoundryError(
                    "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training-source target is not valid canonical JSON.",
                    details={"target_record_id": target_id},
                ) from exc
            if (
                not isinstance(target, dict)
                or canonical_json(target) != target_row["record_json"]
                or target.get("record_hash") != target_row["record_hash"]
                or canonical_record_hash(target) != target.get("record_hash")
                or target.get("publication", {}).get("status") != "published"
                or target.get("content_type") not in allowed_types
                or not isinstance(target.get("compatibility", {}).get("factory", {}).get("stage2_authority"), dict)
                or target["compatibility"]["factory"]["stage2_authority"].get("authority_complete") is not True
            ):
                raise FoundryError(
                    "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training-source target is not a published supported canonical record.",
                    details={"target_record_id": target_id, "allowed_content_types": sorted(allowed_types)},
                )
            report = self.registry.report(target)
            if not report["valid"]:
                raise FoundryError(
                    "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_TARGET_INVALID",
                    "A custom training-source target fails canonical record validation.",
                    details={"target_record_id": target_id, "diagnostics": report["diagnostics"]},
                )

    def _assert_snapshot_record(self, conn, project_id: str, record: dict[str, Any]) -> None:
        binding = record.get("content_binding") if isinstance(record, dict) and isinstance(record.get("content_binding"), dict) else {}
        if binding.get("pack_id") == "tianxia.project.user_directive.training_source":
            self._assert_custom_training_source_snapshot_record(conn, project_id, record)
            return
        from character_creation.constructed_arts.records import CONSTRUCTED_ART_PACK_IDS
        if binding.get("pack_id") in CONSTRUCTED_ART_PACK_IDS:
            self._assert_constructed_art_snapshot_record(conn, project_id, record)
            return
        stage2 = record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
        background_content_projection = (
            record.get("content_type") in {"sphere", "talent"}
            and any(kind in (stage2.get("allowed_kinds") or []) for kind in ("background_sphere_acquisition", "background_talent_acquisition"))
        )
        if record.get("content_binding", {}).get("pack_id") == "tianxia.non_sphere.authority" or background_content_projection or str(record.get("record_id") or "").startswith(("tianxia.background.", "tianxia.background_", "tianxia.origin_insight.")):
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

    def _validate_constructed_art_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Authenticate one constructed record with the correct authority root."""
        from character_creation.constructed_arts.records import (
            constructed_art_contract,
            validate_constructed_art_record,
        )

        contract = constructed_art_contract(record)
        kwargs: dict[str, Any] = {"root_dir": self.db.settings.root_dir}
        if isinstance(contract, dict) and contract.get("kind") in {"manual", "recorded_art", "immortal_art"}:
            from character_creation.constructed_arts.sources import installed_factory_root

            kwargs["factory_root"] = installed_factory_root(self.db.settings.vendor_dir)
        return validate_constructed_art_record(record, **kwargs)

    def _assert_constructed_art_snapshot_record(self, conn, project_id: str, record: dict[str, Any]) -> None:
        """A Factory-constructed art row is authentic only when it re-derives.

        The record must rebuild byte-for-byte from the art it embeds, its
        figures must recompile from the sealed authority, and the stored row
        must carry exactly those bytes under the constructed pack identity.
        """
        try:
            self._validate_constructed_art_record(record)
        except FoundryError as exc:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "A Factory-constructed art row does not re-derive from its sealed authority.",
                details={"project_id": project_id, "record_id": record.get("record_id"), "cause": exc.code},
            ) from exc
        row = conn.execute(
            "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record["record_id"]),
        ).fetchone()
        binding = record["content_binding"]
        valid = bool(row) and (
            row["pack_id"] == binding["pack_id"]
            and row["pack_version"] == binding["pack_version"]
            and row["record_hash"] == record["record_hash"]
            and row["record_json"] == canonical_json(record)
        )
        if not valid:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "A committed event references constructed-art bytes outside the immutable project record snapshot.",
                details={"project_id": project_id, "record_id": record["record_id"]},
            )

    def insert_constructed_art_records(self, conn, project_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Lock Factory-constructed art records into the project snapshot.

        Each record is re-derived before insertion.  An existing row must be
        byte-identical (idempotent replay); different bytes under the same
        deterministic identity are a conflict.  Returns one receipt per record.
        """
        from character_creation.constructed_arts.records import CONSTRUCTED_ART_PACK_IDS

        receipts: list[dict[str, Any]] = []
        for record in records:
            binding = record.get("content_binding") if isinstance(record, dict) else None
            if not isinstance(binding, dict) or binding.get("pack_id") not in CONSTRUCTED_ART_PACK_IDS:
                raise FoundryError(
                    "CONSTRUCTED_ART_RECORD_INVALID",
                    "Only a Factory-constructed art under a constructed pack may be locked this way.",
                    details={"project_id": project_id, "record_id": (record or {}).get("record_id") if isinstance(record, dict) else None},
                )
            self._validate_constructed_art_record(record)
            self._validate_or_raise(
                record,
                boundary="constructed_art_lock",
                family="rules_catalog_record",
                key=record["record_id"],
                conn=conn,
            )
            exact = canonical_json(record)
            existing = conn.execute(
                "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                (project_id, record["record_id"]),
            ).fetchone()
            if existing:
                same = (
                    existing["pack_id"] == binding["pack_id"]
                    and existing["pack_version"] == binding["pack_version"]
                    and existing["record_hash"] == record["record_hash"]
                    and existing["record_json"] == exact
                )
                if not same:
                    raise FoundryError(
                        "PROJECT_CONSTRUCTED_ART_CONFLICT",
                        "The deterministic constructed-art identity is already bound to different bytes.",
                        details={"project_id": project_id, "record_id": record["record_id"]},
                        status_code=409,
                    )
                receipts.append({"record_id": record["record_id"], "record_hash": record["record_hash"], "status": "idempotent"})
                continue
            conn.execute(
                "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                (project_id, record["record_id"], binding["pack_id"], binding["pack_version"], record["record_hash"], exact),
            )
            receipts.append({"record_id": record["record_id"], "record_hash": record["record_hash"], "status": "locked"})
        return receipts

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
                          l.persistence_state AS builder_persistence_state,l.lifecycle_source,l.created_at AS lifecycle_created_at,l.updated_at AS lifecycle_updated_at,
                          (SELECT COUNT(*) FROM character_creation_runs r WHERE r.project_id=p.project_id) AS character_creation_run_count
                   FROM projects p LEFT JOIN character_builder_project_lifecycle l ON l.project_id=p.project_id
                   WHERE NOT EXISTS (SELECT 1 FROM project_deletion_requests q
                       WHERE q.project_id=p.project_id AND q.status IN ('queued','failed'))
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

    @staticmethod
    def _refuse_early_foundation_locks(*, old_locks: list[Any], new_locks: list[dict[str, Any]]) -> None:
        """Refuse a Foundation lock below the published acquisition CL before freezing.

        Runs before any lock is written, so the owner can still change the
        target level or Foundation.  Unfreezing after a prompt is impossible.
        The rule itself lives in ``app.foundation_cl_gate`` so every entry point
        shares one implementation.
        """
        from app.foundation_cl_gate import refuse_early_foundation_locks
        from non_sphere_authority.foundation_mechanics import INITIAL_FOUNDATION_MECHANICS_POLICY

        refuse_early_foundation_locks(
            old_locks=old_locks,
            new_locks=new_locks,
            acquisition_cl=INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"],
        )

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
            self._refuse_early_foundation_locks(old_locks=json.loads(row["project_json"]).get("user_locks") or [], new_locks=locks)
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
                # The canonical project document is the immutable owner-bound
                # lock. ``project_content_locks.pack_hash`` is an internal
                # archive/install identity and must not rebuild that lock.
                frozen_content_lock = deepcopy(old["content_lock"])
                updated = canonical_project_document(
                    project_id=project_id,
                    name=old["name"],
                    revision=revision,
                    status=old["status"],
                    created_at=old["created_at"],
                    updated_at=now,
                    catalog_build_id=frozen_content_lock["catalog_build_id"],
                    pack_locks=frozen_content_lock["packs"],
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
                updated["content_lock"] = frozen_content_lock
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

    def _resolve_locked_record(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        lock_proof_verified: bool = False,
        authorized_delegated_path_ids: Collection[str] | None = None,
    ) -> dict[str, Any] | None:
        # Live catalog rows are discovery/read-model projections only.  HF2
        # authority resolution is strictly from the complete immutable project
        # snapshot proved against receipt-backed pack membership.
        locks = self._project_locks(conn, project_id)
        required = ("record_set_hash", "payload_files_hash", "install_receipt_hash", "membership_snapshot_hash")
        if not lock_proof_verified and locks and all(all(lock.get(field) for field in required) for lock in locks):
            self.project_lock_proof(conn, project_id)
        return self._resolve_locked_record_after_proof(
            conn,
            project_id,
            record_id,
            authorized_delegated_path_ids=authorized_delegated_path_ids,
        )

    def verified_pack_seal(self, conn, pack_id: Any, version: Any, pack_hash: Any) -> PackSeal:
        """Verify one installed pack seal, once per operation scope.

        ``verify_pack_seal`` re-reads and re-canonicalizes every membership
        row of the pack (thousands of records).  The membership of a sealed
        pack hash is immutable, so inside one operation scope the verified
        seal is reused for the same (pack, version, hash); outside a scope
        every call verifies afresh.
        """

        seal_cache = _PROJECT_LOCK_PROOF_SEAL_CACHE.get()
        seal_cache_key = (id(self.db), str(pack_id), str(version), str(pack_hash))
        seal = seal_cache.get(seal_cache_key) if seal_cache is not None else None
        if seal is None:
            seal = verify_pack_seal(
                conn, pack_id=pack_id, version=version, expected_pack_hash=pack_hash,
                integrity=self.integrity,
            )
            if seal_cache is not None:
                seal_cache[seal_cache_key] = seal
        return seal

    def _resolve_locked_record_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
        authorized_delegated_path_ids: Collection[str] | None = None,
        method_version: str | None = None,
        foundation_version: str | None = None,
        prefetched_row: Any = None,
    ) -> dict[str, Any] | None:
        """Resolve one immutable snapshot record after the caller proved the full lock once.

        ``prefetched_row`` lets a caller that already read the row's
        ``record_hash``/``record_json`` (one batched query over the project)
        skip the two per-record reads; the verification is unchanged.

        One compile resolves the same locked rows thousands of times.  Inside
        an operation scope the resolved projection is memoized per exact row
        bytes: the row is still read on every call and its stored bytes must
        equal the memoized bytes before the memoized projection is reused, so
        a tampered or replaced row is re-verified (and fails) exactly as
        before.  Only positive resolutions are memoized.
        """
        if method_version is not None and record_id.startswith("METHOD-"):
            return self._resolve_project_locked_method_version_after_proof(
                conn, project_id, record_id, method_version, authority_service=authority_service,
            )
        memo = _PROJECT_LOCK_SCOPE_MEMO.get()
        memo_key = None
        if memo is not None:
            # Locked rows are immutable by schema (``trg_project_locked_record_no_update``,
            # pinned by ``test_locked_records_by_reference``): the sealed hash is
            # the identity of the row bytes, so a hash match reuses the
            # projection without re-reading the multi-kilobyte document.
            identity = prefetched_row if prefetched_row is not None else conn.execute(
                "SELECT record_hash FROM project_locked_records WHERE project_id=? AND record_id=?",
                (project_id, record_id),
            ).fetchone()
            if identity:
                memo_key = (
                    "locked_record",
                    id(self.db),
                    str(project_id),
                    str(record_id),
                    identity["record_hash"],
                    foundation_version,
                    tuple(sorted(str(value) for value in (authorized_delegated_path_ids or ()))),
                )
                cached = memo.get(memo_key)
                if cached is not None:
                    return deepcopy(cached[1])
        row = prefetched_row if prefetched_row is not None else conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if memo_key is not None and (not row or row["record_hash"] != memo_key[4]):
            memo_key = None
        resolved = self._resolve_locked_record_after_proof_uncached(
            conn,
            project_id,
            record_id,
            row,
            authority_service=authority_service,
            authorized_delegated_path_ids=authorized_delegated_path_ids,
            foundation_version=foundation_version,
        )
        if memo_key is not None and resolved is not None:
            memo[memo_key] = (row["record_json"], deepcopy(resolved))
        return resolved

    def _resolve_locked_record_after_proof_uncached(
        self,
        conn,
        project_id: str,
        record_id: str,
        row: Any,
        *,
        authority_service: Any | None = None,
        authorized_delegated_path_ids: Collection[str] | None = None,
        foundation_version: str | None = None,
    ) -> dict[str, Any] | None:
        # Legacy projects remain readable from already-persisted snapshots, but
        # no live-catalog fallback is permitted. Mutation boundaries must call
        # project_lock_proof() before using this bounded resolver.
        if foundation_version is not None and row and json.loads(row["record_json"]).get("content_type") == "foundation":
            return self._resolve_project_locked_foundation_after_proof(
                conn, project_id, record_id, authority_service=authority_service, version=foundation_version,
            )
        if not row:
            return self._resolve_project_locked_authority_projection_after_proof(
                conn,
                project_id,
                record_id,
                authority_service=authority_service,
                authorized_delegated_path_ids=authorized_delegated_path_ids,
            )
        record = json.loads(row["record_json"])
        if canonical_json(record) != row["record_json"] or record.get("record_hash") != row["record_hash"]:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "The immutable project snapshot record bytes do not match their stored hash binding.",
                details={"project_id": project_id, "record_id": record_id},
            )
        self._validate_or_raise(record, boundary="locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        if record.get("content_type") == "cultivation_method" or record_id.startswith("METHOD-"):
            fallback = self._resolve_project_locked_method_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
            if fallback is not None:
                return fallback
        if record_id.startswith("tianxia.path.") and ".feature." in record_id:
            fallback = self._resolve_project_locked_path_after_proof(
                conn,
                project_id,
                record_id,
                authority_service=authority_service,
                authorized_delegated_path_ids=authorized_delegated_path_ids,
            )
            if fallback is not None:
                return fallback
            return None
        if record_id.startswith("tianxia.path.") and ".feature." not in record_id:
            fallback = self._resolve_project_locked_path_after_proof(
                conn,
                project_id,
                record_id,
                authority_service=authority_service,
                authorized_delegated_path_ids=authorized_delegated_path_ids,
            )
            if fallback is not None:
                return fallback
            return None
        if record_id.startswith(("tianxia.subpath.", "tianxia.tradition.")):
            fallback = self._resolve_project_locked_subpath_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
            if fallback is not None:
                return fallback
        # Foundation IDs are source-owned stable IDs, not a namespace we can
        # safely infer from a prefix.  The immutable row's content type is the
        # authority boundary; use the typed projection for every Foundation,
        # including rows such as ``true_blackblood_physique_v0_2C``.
        if record.get("content_type") == "foundation" or record_id.startswith(("ancient_", "FOUNDATION_")):
            fallback = self._resolve_project_locked_foundation_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
            if fallback is not None:
                return fallback
        if record_id.startswith(("tianxia.background.", "tianxia.background_")) and not record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("authority_complete"):
            fallback = self._resolve_project_locked_background_after_proof(conn, project_id, record_id)
            if fallback is not None:
                return fallback
        if record_id.startswith("tianxia.origin_insight.") and not record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("authority_complete"):
            fallback = self._resolve_project_locked_origin_insight_after_proof(conn, project_id, record_id)
            if fallback is not None:
                return fallback
        return record

    def _resolve_project_locked_origin_insight_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        if not isinstance(record_id, str) or not record_id.startswith("tianxia.origin_insight."):
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
                "The immutable Origin Insight snapshot record bytes do not match their stored hash binding.",
                details={"project_id": project_id, "record_id": record_id},
            )
        self._validate_or_raise(record, boundary="origin_insight_locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        if record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("authority_complete"):
            return record
        projected = deepcopy(record)
        compatibility = deepcopy(projected.get("compatibility") or {})
        legality_channels = projected.get("legality", {}).get("acquisition_channels") or []
        channels = [value for value in legality_channels if isinstance(value, str)] or ["origin-selection"]
        stage2_authority = {
            "authority_complete": True,
            "allowed_kinds": ["origin_insight_acquisition"],
            "allowed_channels": channels,
            "rule_id": f"catalog.{record_id}.origin-insight-acquisition.v1",
        }
        compatibility.setdefault("factory", {})["stage2_authority"] = stage2_authority
        projected["compatibility"] = compatibility
        projected["record_hash"] = canonical_record_hash(projected)
        return projected

    def _resolve_project_locked_background_content_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        """Add the Background route kind to canonical Sphere/Talent records.

        Background package events use the executable canonical Sphere/Talent
        records after owner-facing route IDs are resolved.  The base catalog
        authority must therefore expose the additional Background event kind
        without changing the immutable snapshot bytes.
        """
        if not isinstance(record_id, str):
            return None
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if not row:
            return None
        record = json.loads(row["record_json"])
        if record.get("content_type") not in {"sphere", "talent"}:
            return None
        self._validate_or_raise(record, boundary="background_content_locked_record_reconstruct", family="rules_catalog_record", key=record_id, conn=conn)
        projected = deepcopy(record)
        compatibility = deepcopy(projected.get("compatibility") or {})
        stage2_authority = deepcopy(compatibility.setdefault("factory", {}).get("stage2_authority") or {})
        if not stage2_authority.get("authority_complete"):
            return None
        allowed_kinds = list(stage2_authority.get("allowed_kinds") or [])
        allowed_channels = list(stage2_authority.get("allowed_channels") or [])
        background_kind = (
            "background_sphere_acquisition"
            if record.get("content_type") == "sphere"
            else "background_talent_acquisition"
        )
        if background_kind not in allowed_kinds:
            allowed_kinds.append(background_kind)
        if "background-grant" not in allowed_channels:
            allowed_channels.append("background-grant")
        stage2_authority.update({
            "authority_complete": True,
            "allowed_kinds": allowed_kinds,
            "allowed_channels": allowed_channels,
        })
        compatibility.setdefault("factory", {})["stage2_authority"] = stage2_authority
        projected["compatibility"] = compatibility
        projected["record_hash"] = canonical_record_hash(projected)
        return projected

    def _resolve_project_locked_authority_projection_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
        authorized_delegated_path_ids: Collection[str] | None = None,
    ) -> dict[str, Any] | None:
        return (
            self._resolve_project_locked_non_sphere_after_proof(
                conn,
                project_id,
                record_id,
                authority_service=authority_service,
                authorized_delegated_path_ids=authorized_delegated_path_ids,
            )
            or self._resolve_project_locked_background_after_proof(conn, project_id, record_id)
            or self._resolve_project_locked_origin_insight_after_proof(conn, project_id, record_id)
            or self._resolve_project_locked_background_content_after_proof(conn, project_id, record_id)
        )

    def _resolve_project_locked_non_sphere_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
        authorized_delegated_path_ids: Collection[str] | None = None,
    ) -> dict[str, Any] | None:
        return (
            self._resolve_project_locked_method_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
            or self._resolve_project_locked_path_after_proof(
                conn,
                project_id,
                record_id,
                authority_service=authority_service,
                authorized_delegated_path_ids=authorized_delegated_path_ids,
            )
            or self._resolve_project_locked_subpath_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
            or self._resolve_project_locked_foundation_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
        )

    def _resolve_project_locked_subpath_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(record_id, str) or ".feature." in record_id or not record_id.startswith(("tianxia.subpath.", "tianxia.tradition.")):
            return None
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if not row:
            # The live NS1R registry is discovery authority only.  A selected
            # Subpath/Tradition is executable for this project only when the
            # exact canonical catalog bytes are present in its immutable
            # project-scoped snapshot.
            return None
        snapshot = json.loads(row["record_json"])
        if (
            canonical_json(snapshot) != row["record_json"]
            or snapshot.get("record_hash") != row["record_hash"]
            or snapshot.get("record_id") != record_id
            or snapshot.get("content_type") not in {"subpath", "tradition"}
        ):
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "The immutable Subpath/Tradition snapshot record bytes do not match its project binding.",
                details={"project_id": project_id, "record_id": record_id},
            )
        self._validate_or_raise(
            snapshot,
            boundary="non_sphere_subpath_snapshot_reconstruct",
            family="rules_catalog_record",
            key=record_id,
            conn=conn,
        )
        authority = authority_service or self._cached_non_sphere_authority()
        # Rebuild the typed event contract from the exact immutable snapshot
        # row.  The live registry may authenticate the projection schema, but
        # it must not supply project-specific ownership/features after the
        # project lock has been proved.
        projected = authority.project_locked_subpath_catalog_record(
            record_id,
            snapshot_record=snapshot,
        )
        if projected.get("record_id") != snapshot.get("record_id"):
            raise FoundryError(
                "PROJECT_LOCK_NON_SPHERE_IDENTITY_MISMATCH",
                "The typed Subpath/Tradition projection does not match the immutable project snapshot identity.",
                details={"project_id": project_id, "record_id": record_id, "snapshot_record_id": snapshot.get("record_id"), "projection_record_id": projected.get("record_id")},
            )
        self._validate_or_raise(
            projected,
            boundary="non_sphere_subpath_locked_record_reconstruct",
            family="rules_catalog_record",
            key=record_id,
            conn=conn,
        )
        return projected

    def _resolve_project_locked_foundation_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
        version: str | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(record_id, str):
            return None
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if not row:
            # Do not turn a live Foundation catalog match into project
            # authority.  The exact canonical Foundation row must be present
            # in this project's immutable snapshot first.
            return None
        snapshot = json.loads(row["record_json"])
        if (
            canonical_json(snapshot) != row["record_json"]
            or snapshot.get("record_hash") != row["record_hash"]
            or snapshot.get("record_id") != record_id
        ):
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "The immutable Foundation snapshot record bytes do not match its project binding.",
                details={"project_id": project_id, "record_id": record_id},
            )
        if snapshot.get("content_type") != "foundation":
            # This helper is also probed for arbitrary stable IDs by the
            # generic non-Sphere resolver.  Only a typed Foundation row is in
            # scope; other rows continue through their own resolver.
            if record_id.startswith(("ancient_", "FOUNDATION_")):
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "A Foundation-shaped record ID is not bound to a Foundation snapshot row.",
                    details={"project_id": project_id, "record_id": record_id},
                )
            return None
        self._validate_or_raise(
            snapshot,
            boundary="non_sphere_foundation_snapshot_reconstruct",
            family="rules_catalog_record",
            key=record_id,
            conn=conn,
        )
        authority = authority_service or self._cached_non_sphere_authority()
        from non_sphere_authority.foundation_mechanics import FOUNDATION_MECHANICS_PACK_VERSION
        if version not in {None, "P2A", FOUNDATION_MECHANICS_PACK_VERSION}:
            raise FoundryError("PROJECT_FOUNDATION_VERSION_UNSUPPORTED", "The selected Foundation derivation is not installed.", details={"version": version}, status_code=409)
        projected = authority.project_locked_foundation_catalog_record(
            record_id,
            snapshot_record=snapshot,
            mechanical=version == FOUNDATION_MECHANICS_PACK_VERSION,
        )
        if projected.get("record_id") != snapshot.get("record_id"):
            raise FoundryError(
                "PROJECT_LOCK_NON_SPHERE_IDENTITY_MISMATCH",
                "The typed Foundation projection does not match the immutable project snapshot identity.",
                details={"project_id": project_id, "record_id": record_id, "snapshot_record_id": snapshot.get("record_id"), "projection_record_id": projected.get("record_id")},
            )
        self._validate_or_raise(
            projected,
            boundary="non_sphere_foundation_locked_record_reconstruct",
            family="rules_catalog_record",
            key=record_id,
            conn=conn,
        )
        return projected

    def _resolve_event_bound_foundation_after_proof(
        self, conn, project_id: str, record_id: str, bindings: list[Any], *,
        authority_service: Any | None = None,
    ) -> dict[str, Any] | None:
        derived = [binding for binding in bindings if isinstance(binding, dict)
                   and binding.get("pack_id") == "tianxia.non_sphere.authority"]
        record = self._resolve_project_locked_foundation_after_proof(
            conn, project_id, record_id, authority_service=authority_service,
            version=derived[0].get("pack_version") if derived else None,
        )
        if record is None:
            return None
        if any(binding.get("record_hash") != record["record_hash"] or any(
            binding.get(key) != record["content_binding"].get(key)
            for key in ("pack_id", "pack_version", "pack_hash")
        ) for binding in derived):
            raise FoundryError("PROJECT_FOUNDATION_EVENT_VERSION_MISMATCH", "Historical Foundation bindings do not match one exact source-proved version.", details={"record_id": record_id}, status_code=409)
        return record

    def _sphere_talent_snapshot_rows(self, conn, project_id: str, canonical_sphere_id: str) -> list[dict[str, Any]]:
        """Parsed locked talent rows of one Sphere, once per operation scope."""

        memo = _PROJECT_LOCK_SCOPE_MEMO.get()
        memo_key = ("sphere_talent_snapshot_rows", id(self.db), str(project_id), str(canonical_sphere_id))
        if memo is not None:
            cached = memo.get(memo_key)
            if cached is not None:
                return cached
        rows: list[dict[str, Any]] = []
        for candidate in conn.execute(
            """SELECT record_id,record_hash,record_json FROM project_locked_records
               WHERE project_id=?
                 AND (record_id LIKE 'TAL\\_%' ESCAPE '\\' OR record_id LIKE 'tianxia.talent.%')
                 AND json_extract(record_json, '$.content_type') = 'talent'
                 AND json_extract(record_json, '$.compatibility.factory.stage2_authority.sphere_id') = ?
               ORDER BY record_id""",
            (project_id, canonical_sphere_id),
        ):
            if not candidate["record_id"].startswith(("TAL_", "tianxia.talent.")):
                continue
            rows.append(json.loads(candidate["record_json"]))
        if memo is not None:
            memo[memo_key] = rows
        return rows

    def _resolve_project_locked_background_after_proof(self, conn, project_id: str, record_id: str) -> dict[str, Any] | None:
        """Attach typed C1A authority to the owner-facing Background projections.

        The Background supplement intentionally owns the stable creator-facing
        IDs, while the typed C1A sphere/talent rows own the executable Stage 2
        rules.  Rebuild the alias only from the complete immutable project
        snapshot; never consult the live catalog for this authority boundary.
        """
        if not isinstance(record_id, str) or not record_id.startswith(("tianxia.background.", "tianxia.background_")):
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
        # Background projections retain owner-facing IDs, while the executable
        # route/ability contract is published by the authenticated non-Sphere
        # authority.  Keep the route-to-canonical relation together for every
        # Background-shaped record so alias rows never fall back to a guessed
        # ``tianxia.sphere.<suffix>`` ID.
        from non_sphere_authority import NonSphereAuthorityService

        authority = getattr(self, "_background_authority_cache", None)
        if authority is None:
            authority = NonSphereAuthorityService(self.db)
            self._background_authority_cache = authority
        route_authority = authority.background_route_authority.get(record_id) or {}
        route_authority_sources = (
            [route_authority]
            if record_id.startswith("tianxia.background.")
            else list(authority.background_route_authority.values())
        )
        route_targets_by_choice: dict[str, set[str | None]] = {}
        for authority_source in route_authority_sources:
            for route in authority_source.get("route_options") or []:
                if not isinstance(route, dict):
                    continue
                target = route.get("canonical_sphere_id")
                target = target if isinstance(target, str) and target else None
                for choice_key in ("background_sphere_choice_id", "background_talent_choice_id"):
                    choice_id = route.get(choice_key)
                    if isinstance(choice_id, str) and choice_id:
                        route_targets_by_choice.setdefault(choice_id, set()).add(target)

        def authenticated_canonical_sphere_id(choice_id: str) -> str | None:
            targets = route_targets_by_choice.get(choice_id)
            if not targets or len(targets) != 1:
                return None
            target = next(iter(targets))
            return target if isinstance(target, str) and target else None

        if record_id.startswith("tianxia.background."):
            background = authority.backgrounds.get(record_id)
            if background is None:
                return None

            def executable_talent_id(owner_talent_id: str, canonical_sphere_id: str) -> str:
                suffix = owner_talent_id.removeprefix("tianxia.background_talent.")
                sphere_suffix = canonical_sphere_id.removeprefix("tianxia.sphere.")
                talent_slug = suffix.rsplit(".", 1)[-1]
                sphere_tokens = (sphere_suffix.replace("_", "").upper(), sphere_suffix.upper())
                direct_candidates = tuple(dict.fromkeys(
                    [
                        *(f"TAL_{token}_{talent_slug.upper()}" for token in sphere_tokens),
                        f"tianxia.talent.{sphere_suffix}.{talent_slug}",
                        f"TAL_{suffix.replace('.', '_').upper()}",
                        f"tianxia.talent.{suffix}",
                    ]
                ))
                for candidate_id in direct_candidates:
                    candidate = conn.execute(
                        "SELECT record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                        (project_id, candidate_id),
                    ).fetchone()
                    if not candidate:
                        continue
                    value = json.loads(candidate["record_json"])
                    candidate_authority = value.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
                    if (
                        value.get("content_type") == "talent"
                        and candidate_authority.get("authority_complete")
                        and candidate_authority.get("sphere_id") == canonical_sphere_id
                    ):
                        return candidate_id
                return owner_talent_id

            packages: list[dict[str, Any]] = []
            for route in route_authority.get("route_options") or []:
                if not isinstance(route, dict):
                    continue
                sphere_choice_id = route.get("background_sphere_choice_id")
                talent_choice_id = route.get("background_talent_choice_id")
                if not isinstance(sphere_choice_id, str) or not isinstance(talent_choice_id, str):
                    continue
                canonical_sphere_id = authenticated_canonical_sphere_id(sphere_choice_id)
                if canonical_sphere_id is None:
                    raise FoundryError(
                        "PROJECT_LOCK_BACKGROUND_CANONICAL_SPHERE_UNRESOLVED",
                        "An authenticated Background package has no unique canonical Sphere target.",
                        details={
                            "project_id": project_id,
                            "background_id": record_id,
                            "background_sphere_choice_id": sphere_choice_id,
                        },
                        status_code=409,
                    )
                packages.append({
                    "route_record_id": route.get("background_route_record_id"),
                    "sphere_record_id": canonical_sphere_id,
                    "talent_record_id": executable_talent_id(talent_choice_id, canonical_sphere_id),
                })
            from non_sphere_authority.service import derive_background_ability_adjustment
            ability_adjustment = derive_background_ability_adjustment(background)
            stage2_authority: dict[str, Any] = {
                "authority_complete": True,
                "allowed_kinds": ["background_acquisition"],
                "allowed_channels": ["background-selection"],
                "background_packages": packages,
                "rule_id": f"ns1r.{record_id}.background-acquisition.v1",
                "source_authority_snapshot_hash": authority.authority_snapshot_hash,
            }
            # Single-score +2 bounded form shared with Stage 1 presentation; see
            # derive_background_ability_adjustment for the RAW-041 divergence.
            if ability_adjustment is not None:
                stage2_authority["ability_adjustment"] = ability_adjustment
            authority_record = deepcopy(record)
            compatibility = deepcopy(authority_record.get("compatibility") or {})
            compatibility.setdefault("factory", {})["stage2_authority"] = stage2_authority
            authority_record["compatibility"] = compatibility
            authority_record["record_hash"] = canonical_record_hash(authority_record)
            return authority_record
        if record_id.startswith("tianxia.background_sphere."):
            canonical_sphere_id = authenticated_canonical_sphere_id(record_id)
            if canonical_sphere_id is None:
                raise FoundryError(
                    "PROJECT_LOCK_BACKGROUND_CANONICAL_SPHERE_UNRESOLVED",
                    "An owner-facing Background Sphere has no unique authenticated canonical Sphere target.",
                    details={"project_id": project_id, "record_id": record_id},
                    status_code=409,
                )
            authority_record = snapshot_record_for(canonical_sphere_id)
        elif record_id.startswith("tianxia.background_talent."):
            canonical_sphere_id = authenticated_canonical_sphere_id(record_id)
            if canonical_sphere_id is None:
                raise FoundryError(
                    "PROJECT_LOCK_BACKGROUND_CANONICAL_SPHERE_UNRESOLVED",
                    "An owner-facing Background Talent has no unique authenticated canonical Sphere target.",
                    details={"project_id": project_id, "record_id": record_id},
                    status_code=409,
                )
            display_name = str(record.get("display_name") or "")
            display_name = display_name.rsplit("(", 1)[0].strip() if "(" in display_name else display_name.strip()
            folded_name = "".join(character.casefold() for character in display_name if character.isalnum())
            matches: list[dict[str, Any]] = []
            # Narrow to this Sphere's talent rows inside SQLite; the typed
            # checks below are unchanged and still decide the match.  The
            # parsed rows of one Sphere are reused within an operation scope
            # (locked rows are immutable), so each Background Talent of the
            # same Sphere does not re-parse the whole Sphere.
            for value in self._sphere_talent_snapshot_rows(conn, project_id, canonical_sphere_id):
                candidate_authority = value.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
                candidate_name = "".join(character.casefold() for character in str(value.get("display_name") or "") if character.isalnum())
                if (
                    value.get("content_type") == "talent"
                    and candidate_authority.get("authority_complete")
                    and (
                        "background_talent_acquisition" in candidate_authority.get("allowed_kinds", [])
                        or "level_talent_acquisition" in candidate_authority.get("allowed_kinds", [])
                    )
                    and candidate_authority.get("sphere_id") == canonical_sphere_id
                    and candidate_name == folded_name
                ):
                    matches.append(deepcopy(value))
            if len(matches) == 1:
                authority_record = matches[0]
            elif len(matches) > 1:
                raise FoundryError(
                    "PROJECT_LOCK_BACKGROUND_AUTHORITY_AMBIGUOUS",
                    "The owner-facing Background Talent maps to more than one typed authority record.",
                    details={"project_id": project_id, "record_id": record_id, "matches": [item["record_id"] for item in matches]},
                    status_code=409,
                )
        if authority_record is not None and record_id.startswith(("tianxia.background_sphere.", "tianxia.background_talent.")):
            authority_record = deepcopy(authority_record)
            compatibility = deepcopy(authority_record.get("compatibility") or {})
            stage2_authority = deepcopy(compatibility.setdefault("factory", {}).get("stage2_authority") or {})
            allowed_kinds = list(stage2_authority.get("allowed_kinds") or [])
            if record_id.startswith("tianxia.background_sphere."):
                if "background_sphere_acquisition" not in allowed_kinds:
                    allowed_kinds.append("background_sphere_acquisition")
            elif "background_talent_acquisition" not in allowed_kinds:
                allowed_kinds.append("background_talent_acquisition")
            allowed_channels = list(stage2_authority.get("allowed_channels") or [])
            if "background-grant" not in allowed_channels:
                allowed_channels.append("background-grant")
            stage2_authority.update({
                "authority_complete": True,
                "allowed_kinds": allowed_kinds,
                "allowed_channels": allowed_channels,
            })
            compatibility.setdefault("factory", {})["stage2_authority"] = stage2_authority
            authority_record["compatibility"] = compatibility
            authority_record["record_hash"] = canonical_record_hash(authority_record)
        if not authority_record:
            return None
        return authority_record

    def _resolve_project_locked_method_version_after_proof(
        self, conn, project_id: str, record_id: str, version: str, *,
        authority_service: Any | None = None,
    ) -> dict[str, Any] | None:
        """Derive an explicit installed version without replacing its source.

        Callers authorize version selection from a frozen private creation
        request or exact historical event binding. The original packed or
        extra record must independently pass the unchanged source proof first.
        No supplied mechanics, record hash, or live catalog row is consumed.
        """
        authority = authority_service or self._cached_non_sphere_authority()
        source = self._resolve_project_locked_method_after_proof(
            conn, project_id, record_id, authority_service=authority,
        )
        if source is None:
            return None
        expected = authority.reconstruct_locked_method_catalog_record({
            "record_id": record_id,
            "content_binding": {"pack_id": "tianxia.non_sphere.authority", "pack_version": version},
        })
        self._validate_or_raise(
            expected, boundary="non_sphere_method_version_reconstruct",
            family="rules_catalog_record", key=record_id, conn=conn,
        )
        return expected

    def _resolve_event_bound_method_after_proof(
        self, conn, project_id: str, record_id: str, bindings: list[Any], *,
        authority_service: Any | None = None,
    ) -> dict[str, Any] | None:
        """Reconstruct one historical Method version and compare every binding.

        Access evidence can also bind the raw packed target set. That evidence
        keeps its separate existing target-set validation; it does not choose
        the Method mechanics version.
        """
        derived_bindings = [binding for binding in bindings if isinstance(binding, dict)
                            and binding.get("pack_id") == "tianxia.non_sphere.authority"]
        if not derived_bindings:
            return self._resolve_project_locked_method_after_proof(
                conn, project_id, record_id, authority_service=authority_service,
            )
        record = self._resolve_project_locked_method_version_after_proof(
            conn, project_id, record_id, derived_bindings[0].get("pack_version"),
            authority_service=authority_service,
        )
        if record is None or any(
            binding.get("record_hash") != record.get("record_hash")
            or any(binding.get(key) != record["content_binding"].get(key)
                   for key in ("pack_id", "pack_version", "pack_hash"))
            for binding in derived_bindings
        ):
            raise FoundryError(
                "PROJECT_METHOD_EVENT_VERSION_MISMATCH",
                "Historical Method bindings do not match one exact source-proved version.",
                details={"project_id": project_id, "record_id": record_id}, status_code=409,
            )
        return record

    def _resolve_project_locked_method_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
    ) -> dict[str, Any] | None:
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
        # Delegated initial creation freezes the offered source-backed Method
        # projection at request creation.  A direct-access Method does not
        # need an owner learning-route lock, but its immutable project snapshot
        # is still mandatory and must match the authenticated registry exactly.
        snapshot_row = conn.execute(
            "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if snapshot_row and snapshot_row["pack_id"] == "tianxia.non_sphere.authority":
            authority = authority_service or self._cached_non_sphere_authority()
            expected = authority.reconstruct_locked_method_catalog_record({
                "record_id": record_id,
                "content_binding": {
                    "pack_id": snapshot_row["pack_id"],
                    "pack_version": snapshot_row["pack_version"],
                },
            })
            if (
                snapshot_row["pack_version"] != expected.get("content_binding", {}).get("pack_version")
                or snapshot_row["record_hash"] != expected.get("record_hash")
                or snapshot_row["record_json"] != canonical_json(expected)
            ):
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "The source-backed Method snapshot does not match the authenticated registry.",
                    details={"project_id": project_id, "method_id": record_id},
                    status_code=409,
                )
            self._validate_or_raise(
                expected,
                boundary="non_sphere_method_offered_record_reconstruct",
                family="rules_catalog_record",
                key=record_id,
                conn=conn,
            )
            return expected
        if snapshot_row:
            try:
                snapshot = json.loads(snapshot_row["record_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "The immutable Method snapshot is not valid JSON.",
                    details={"project_id": project_id, "method_id": record_id},
                    status_code=409,
                ) from exc
            if (
                canonical_json(snapshot) != snapshot_row["record_json"]
                or snapshot.get("record_hash") != snapshot_row["record_hash"]
                or snapshot.get("record_id") != record_id
                or snapshot.get("content_type") != "cultivation_method"
            ):
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "The immutable Method snapshot record bytes do not match their project binding.",
                    details={"project_id": project_id, "method_id": record_id},
                    status_code=409,
                )
            self._validate_or_raise(
                snapshot,
                boundary="non_sphere_method_legacy_snapshot_reconstruct",
                family="rules_catalog_record",
                key=record_id,
                conn=conn,
            )
            authority = authority_service or self._cached_non_sphere_authority()
            projected = authority.project_locked_method_catalog_record(
                record_id,
                snapshot_record=snapshot,
            )
            if projected.get("record_id") != snapshot.get("record_id"):
                raise FoundryError(
                    "PROJECT_LOCK_NON_SPHERE_IDENTITY_MISMATCH",
                    "The typed Method projection does not match the immutable project snapshot identity.",
                    details={"project_id": project_id, "method_id": record_id},
                    status_code=409,
                )
            self._validate_or_raise(
                projected,
                boundary="non_sphere_method_legacy_locked_record_reconstruct",
                family="rules_catalog_record",
                key=record_id,
                conn=conn,
            )
            return projected
        project = json.loads(row["project_json"])
        locks = {
            item.get("field"): item.get("value")
            for item in project.get("user_locks", [])
            if isinstance(item, dict)
        }
        access_plan = locks.get("character_sheet.method_access_plan")
        if not isinstance(access_plan, dict) or access_plan.get("method_id") != record_id:
            return None
        authority = authority_service or self._cached_non_sphere_authority()
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

    def _project_user_lock_values(self, conn, project_id: str) -> dict[Any, Any] | None:
        """Return ``{lock field: value}`` from the project's owner locks.

        Only the ``user_locks`` member is needed here; SQLite extracts it
        without handing the multi-megabyte project document to Python, and
        an operation scope memoizes the result per project revision/hash so
        repeated Path resolutions during one Stage 2 operation do not re-read
        it at all.
        """
        row = conn.execute(
            "SELECT revision, canonical_project_hash FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if not row:
            return None
        memo = _PROJECT_LOCK_SCOPE_MEMO.get()
        memo_key = ("user_locks", id(self.db), str(project_id), row["revision"], row["canonical_project_hash"])
        if memo is not None and memo_key in memo:
            return dict(memo[memo_key])
        extracted = conn.execute(
            "SELECT json_extract(project_json, '$.user_locks') FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        user_locks = json.loads(extracted[0]) if extracted and extracted[0] else []
        locks = {
            item.get("field"): item.get("value")
            for item in (user_locks if isinstance(user_locks, list) else [])
            if isinstance(item, dict)
        }
        if memo is not None:
            memo[memo_key] = dict(locks)
        return locks

    def _resolve_project_locked_path_after_proof(
        self,
        conn,
        project_id: str,
        record_id: str,
        *,
        authority_service: Any | None = None,
        authorized_delegated_path_ids: Collection[str] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a selected Path from the authenticated non-Sphere index."""
        if not isinstance(record_id, str) or not record_id.startswith("tianxia.path."):
            return None
        locks = self._project_user_lock_values(conn, project_id)
        if locks is None:
            return None
        authorized_paths = frozenset(
            value for value in (authorized_delegated_path_ids or ())
            if isinstance(value, str) and value.startswith("tianxia.path.")
        )
        delegated_path = record_id in authorized_paths
        locked_choices = locks.get("character_sheet.locked_choices")
        selected_paths = locked_choices.get("path_choice") or [] if isinstance(locked_choices, dict) else []
        feature_path_id = record_id.split(".feature.", 1)[0] if ".feature." in record_id else None
        if feature_path_id is not None:
            if feature_path_id not in selected_paths and feature_path_id not in authorized_paths:
                return None
            if feature_path_id in authorized_paths:
                snapshot_row = conn.execute(
                    "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                    (project_id, feature_path_id),
                ).fetchone()
                if not snapshot_row:
                    return None
            authority = authority_service or self._cached_non_sphere_authority()
            memo = _PROJECT_LOCK_SCOPE_MEMO.get()
            memo_key = ("path_catalog_record", authority.authority_snapshot_hash, feature_path_id, record_id) if memo is not None else None
            if memo is not None and memo_key in memo:
                record = deepcopy(memo[memo_key])
            else:
                record = authority.project_locked_path_feature_catalog_record(feature_path_id, record_id)
                if memo is not None:
                    memo[memo_key] = deepcopy(record)
            self._validate_or_raise(
                record,
                boundary="non_sphere_path_feature_locked_record_reconstruct",
                family="rules_catalog_record",
                key=record_id,
                conn=conn,
            )
            return record
        if record_id not in selected_paths and not delegated_path:
            return None
        if delegated_path:
            snapshot_row = conn.execute(
                "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
                (project_id, record_id),
            ).fetchone()
            if not snapshot_row:
                # A live authenticated Path is still only discovery data until
                # the exact immutable project snapshot row is present.
                return None
            try:
                snapshot = json.loads(snapshot_row["record_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "The immutable delegated Path snapshot is not valid canonical JSON.",
                    details={"project_id": project_id, "record_id": record_id},
                ) from exc
            if (
                canonical_json(snapshot) != snapshot_row["record_json"]
                or snapshot.get("record_hash") != snapshot_row["record_hash"]
                or snapshot.get("record_id") != record_id
                or snapshot.get("content_type") != "path"
            ):
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                    "The immutable delegated Path snapshot does not match its project binding.",
                    details={"project_id": project_id, "record_id": record_id},
                )
            self._validate_or_raise(
                snapshot,
                boundary="non_sphere_delegated_path_snapshot_reconstruct",
                family="rules_catalog_record",
                key=record_id,
                conn=conn,
            )
        authority = authority_service or self._cached_non_sphere_authority()
        memo = _PROJECT_LOCK_SCOPE_MEMO.get()
        memo_key = ("path_catalog_record", authority.authority_snapshot_hash, record_id) if memo is not None else None
        if memo is not None and memo_key in memo:
            record = deepcopy(memo[memo_key])
        else:
            record = authority.project_locked_path_catalog_record(record_id)
            if memo is not None:
                memo[memo_key] = deepcopy(record)
        if record.get("record_id") != record_id:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_MISMATCH",
                "The authenticated Path projection does not preserve the requested stable identity.",
                details={"project_id": project_id, "record_id": record_id, "projection_record_id": record.get("record_id")},
            )
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

    def _record_types(
        self,
        conn,
        project_id: str,
        events: list[dict[str, Any]],
        *,
        lock_already_proved: bool = False,
        record_cache: Mapping[str, dict[str, Any] | None] | None = None,
        type_cache: dict[str, str | None] | None = None,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        # Classification may reuse records already selected by its caller, but
        # its historical lock resolver must not populate that caller's authority
        # cache. Initial creation can select a newer, privately proved version of
        # the same ID; seeding the cache here would bypass that resolver later.
        cache = dict(record_cache) if record_cache is not None else {}
        authority = None
        for event in events:
            rid = event.get("subject", {}).get("record_id")
            if rid and rid not in result:
                # One replay reduces every event prefix twice; locked records
                # are immutable, so a record's content type is resolved once
                # per replay instead of per prefix (151k deepcopied resolves
                # in one retry).  Failed resolutions are never cached.
                if type_cache is not None and rid in type_cache:
                    known = type_cache[rid]
                    result[rid] = known if known is not None else event.get("subject", {}).get("content_type", "unclassified")
                    continue
                if rid not in cache:
                    if isinstance(rid, str) and (
                        rid.startswith("METHOD-")
                        or rid.startswith("tianxia.path.")
                        or rid.startswith("tianxia.subpath.")
                        or rid.startswith("tianxia.tradition.")
                        or rid.startswith("ancient_")
                        or rid.startswith("FOUNDATION_")
                    ):
                        if authority is None:
                            authority = self._cached_non_sphere_authority()
                    cache[rid] = (
                        self._resolve_locked_record_after_proof(
                            conn, project_id, rid, authority_service=authority,
                        )
                        if lock_already_proved
                        else self._resolve_locked_record(conn, project_id, rid)
                    )
                record = cache[rid]
                if type_cache is not None:
                    type_cache[rid] = record.get("content_type", "unclassified") if record else None
                result[rid] = record.get("content_type", "unclassified") if record else event.get("subject", {}).get("content_type", "unclassified")
        return result

    def _reduce_events(
        self,
        events: list[dict[str, Any]],
        project_id: str,
        conn,
        *,
        lock_already_proved: bool = False,
        record_cache: Mapping[str, dict[str, Any] | None] | None = None,
        type_cache: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
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
        record_types = self._record_types(
            conn,
            project_id,
            events,
            lock_already_proved=lock_already_proved,
            record_cache=record_cache,
            type_cache=type_cache,
        )
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
        record_cache: dict[str, dict[str, Any] | None] | None = None,
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
        record_cache = record_cache if record_cache is not None else {}
        type_cache: dict[str, str | None] = {}
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
                before_state = self._reduce_events(
                    prefix,
                    project_id,
                    conn,
                    lock_already_proved=lock_already_proved,
                    record_cache=record_cache,
                    type_cache=type_cache,
                )
                if event.get("state_before_hash") != sha256_json(before_state):
                    errors.append({"code": "STATE_BEFORE_HASH_MISMATCH", "sequence": row["sequence_no"], "pointer": pointer})
                prefix.append(event)
                after_state = self._reduce_events(
                    prefix,
                    project_id,
                    conn,
                    lock_already_proved=lock_already_proved,
                    record_cache=record_cache,
                    type_cache=type_cache,
                )
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
            state = self._reduce_events(
                events,
                project_id,
                conn,
                lock_already_proved=lock_already_proved,
                record_cache=record_cache,
                type_cache=type_cache,
            )
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
        # One replay resolves the same locked rows and owner locks for every
        # event; the operation scope memoizes them (release ran without one:
        # 89% of its time was re-parsing the owner locks per reduction).
        with self.db.connection() as conn, ensure_project_lock_proof_cache_scope():
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
                "dao_iching", "semantic_contract", "release_metadata",
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
        with self.db.connection() as conn, ensure_project_lock_proof_cache_scope():
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
        # Validate the imported project envelope before its immutable locks are
        # used to bind pre-persistence non-Sphere provenance.  The destination
        # row does not exist yet, so this is the authenticated import boundary's
        # exact project document rather than a database lookup.
        self._validate_or_raise(project, boundary="project_import_parse", family="character_project", key=project_id)
        imported_non_sphere_state = None
        imported_non_sphere_hash = None
        imported_non_sphere_ledger = None
        if "non-sphere-authority.json" in contents:
            from non_sphere_authority import NonSphereAuthorityService
            from non_sphere_authority.service import _TRUSTED_PROJECT_IMPORT_BOUNDARY
            imported_non_sphere_state, imported_non_sphere_hash, imported_non_sphere_ledger = NonSphereAuthorityService(self.db).validate_import_payload(
                project_id,
                json.loads(contents["non-sphere-authority.json"]),
                project_document=project,
                _project_document_authority=_TRUSTED_PROJECT_IMPORT_BOUNDARY,
            )
        if canonical_project_hash(project) != manifest.get("canonical_project_hash"):
            raise FoundryError("PROJECT_CANONICAL_HASH_MISMATCH", "Imported canonical project hash does not match its manifest.")
        for event in events:
            self._validate_or_raise(event, boundary="event_import_parse", family="advancement_event", key=event.get("event_id", "unknown"))
        # Do not repeat a full JSON-Schema walk over thousands of exported lock records.
        # The exact archive member hash was verified above, and every supplied record is
        # compared byte-for-byte with the externally keyed immutable installed pack seal
        # inside the transaction below before any project row can commit.
        if not isinstance(records, list) or any(
            not isinstance(record, dict)
            or not isinstance(record.get("record_id"), str)
            or not record.get("record_id")
            for record in records
        ):
            raise FoundryError("PROJECT_LOCK_SNAPSHOT_INVALID", "The imported locked-record set is malformed.")
        seen_record_ids: set[str] = set()
        duplicate_record_ids: set[str] = set()
        for record in records:
            record_id = record["record_id"]
            if record_id in seen_record_ids:
                duplicate_record_ids.add(record_id)
            seen_record_ids.add(record_id)
        if duplicate_record_ids:
            raise FoundryError(
                "PROJECT_LOCK_SNAPSHOT_INVALID",
                "The imported locked-record set contains duplicate record IDs.",
                details={"duplicate_record_ids": sorted(duplicate_record_ids)},
            )
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
            supplied_pack_records = {
                record_id: record_json
                for record_id, record_json in supplied_exported_records.items()
                if record_id in expected_exported_records
            }
            if supplied_pack_records != expected_exported_records:
                raise FoundryError(
                    "PROJECT_LOCK_SNAPSHOT_INCOMPLETE",
                    "The imported locked-record set is not exactly the complete immutable membership of its pack locks.",
                    details={
                        "missing": sorted(set(expected_exported_records) - set(supplied_exported_records)),
                        "extra": sorted(set(supplied_exported_records) - set(expected_exported_records)),
                    },
                )
            imported_non_pack_records: list[dict[str, Any]] = []
            extra_record_ids = sorted(set(supplied_exported_records) - set(expected_exported_records))
            if extra_record_ids:
                from non_sphere_authority import NonSphereAuthorityService

                authority = NonSphereAuthorityService(self.db)
                invalid_extra_record_ids: list[str] = []
                records_by_id = {record["record_id"]: record for record in records}
                from character_creation.constructed_arts.records import CONSTRUCTED_ART_PACK_IDS
                for record_id in extra_record_ids:
                    record = records_by_id[record_id]
                    binding = record.get("content_binding")
                    if isinstance(binding, dict) and binding.get("pack_id") in CONSTRUCTED_ART_PACK_IDS:
                        try:
                            self._validate_constructed_art_record(record)
                        except FoundryError:
                            invalid_extra_record_ids.append(record_id)
                            continue
                        self._validate_or_raise(
                            record,
                            boundary="constructed_art_import_record",
                            family="rules_catalog_record",
                            key=record_id,
                            conn=conn,
                        )
                        imported_non_pack_records.append(record)
                        continue
                    if not isinstance(binding, dict) or binding.get("pack_id") != "tianxia.non_sphere.authority":
                        invalid_extra_record_ids.append(record_id)
                        continue
                    try:
                        expected = authority.reconstruct_locked_method_catalog_record(record)
                    except FoundryError as exc:
                        if exc.code != "NS1R_METHOD_ID_UNKNOWN":
                            raise
                        invalid_extra_record_ids.append(record_id)
                        continue
                    expected_binding = expected.get("content_binding")
                    if (
                        not isinstance(expected_binding, dict)
                        or expected_binding.get("pack_id") != "tianxia.non_sphere.authority"
                        or canonical_json(expected) != canonical_json(record)
                    ):
                        invalid_extra_record_ids.append(record_id)
                        continue
                    self._validate_or_raise(
                        expected,
                        boundary="non_sphere_method_import_record",
                        family="rules_catalog_record",
                        key=record_id,
                        conn=conn,
                    )
                    imported_non_pack_records.append(expected)
                if invalid_extra_record_ids:
                    raise FoundryError(
                        "PROJECT_LOCK_SNAPSHOT_INCOMPLETE",
                        "The imported locked-record set contains an unauthenticated or non-deterministic non-pack extra.",
                        details={
                            "missing": [],
                            "extra": invalid_extra_record_ids,
                        },
                    )
            self._snapshot_pack_seals(conn, project_id, imported_seals, locked_at=project["created_at"])
            for record in imported_non_pack_records:
                binding = record["content_binding"]
                conn.execute(
                    "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                    (
                        project_id,
                        record["record_id"],
                        binding["pack_id"],
                        binding["pack_version"],
                        record["record_hash"],
                        canonical_json(record),
                    ),
                )
            # imported_seals were externally keyed and fully verified immediately above;
            # avoid a second simultaneous full-catalog materialization while their exact
            # bytes are still resident. Future reads independently re-prove the lock.
            method_bindings: dict[str, list[Any]] = {}
            for event in events:
                record_id = (event.get("subject") or {}).get("record_id")
                binding = event.get("content_binding") or {}
                if (isinstance(record_id, str) and record_id.startswith("METHOD-")
                        and binding.get("pack_id") == "tianxia.non_sphere.authority"):
                    method_bindings.setdefault(record_id, []).append(binding)
            for record_id, bindings in method_bindings.items():
                # The package retains original packed/extra source snapshots.
                # Reconstruct event versions from those proved sources rather
                # than accepting a supplied version/hash or replacing a row.
                method_record = self._resolve_event_bound_method_after_proof(conn, project_id, record_id, bindings)
                if method_record is not None:
                    from projector.method_mechanics import validate_initial_method_mechanics
                    # A rehashed downgrade cannot hide an activation behind
                    # acquisition-only authority. Portable import separately
                    # proves real projection packets and creation receipts.
                    validate_initial_method_mechanics(self.db.settings.root_dir, method_record, events)
            foundation_bindings: dict[str, list[Any]] = {}
            for event in events:
                subject = event.get("subject") or {}
                if subject.get("content_type") == "foundation":
                    foundation_bindings.setdefault(subject["record_id"], []).append(event.get("content_binding") or {})
            for record_id, bindings in foundation_bindings.items():
                record = self._resolve_event_bound_foundation_after_proof(conn, project_id, record_id, bindings)
                if record is not None:
                    from projector.foundation_mechanics import validate_initial_foundation_mechanics
                    validate_initial_foundation_mechanics(record, events)
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
        del records, imported_seals, expected_exported_records, supplied_exported_records, imported_non_pack_records
        gc.collect()
        return result
