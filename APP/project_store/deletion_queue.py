"""Reversible deletion requests; destructive processing is startup-only.

Call process_at_startup after schema setup, before constructing any
publisher, cache warmer or request handler. No leases or runtime publisher hooks
are needed. Direct backup/restore operations require an offline data root.
"""
from __future__ import annotations

import json
import logging
import shlex

from app.core import FoundryError, utcnow
from project_store.permanent_deletion import IncompleteDeletionRollback, PermanentProjectDeletion, identifier, refuse

TABLE = "project_deletion_requests"


def recovery_message(db, request):
    """The same actionable, exact-root instructions on every startup retry."""
    root = db.settings.data_dir
    command = shlex.join([
        "python", "-m", "project_store.deletion_recovery", "--data-root", str(root),
        "--project", request["project_id"],
    ])
    return (
        "Factory startup stopped: character recovery is incomplete. No normal service was started. "
        f"Character project: {request['project_id']}. Verified backup: {root / request['backup']}. "
        f"Quarantine: {root / request['quarantine']}; its recovery.json maps the original paths. "
        "Stop automatic restart retries and keep the service stopped. Preserve the backup and quarantine. "
        f"From {db.settings.root_dir} in the application environment, run: {command}. "
        "This offline command reconciles only this character, verifies its rows and files, then clears the halt. "
        "If it refuses, keep the halt and follow project_store/PERMANENT_DELETION.md, "
        "Owner recovery. Never restore over a partial character or replace the data root. Undo cannot clear this halt."
    )


def halt_for_recovery(db, request):
    message = recovery_message(db, request)
    logging.getLogger(__name__).critical(message)
    raise RuntimeError(message)


def hidden_project_ids(db):
    """One indexed small query; no project payloads or filesystem discovery."""
    with db.connection() as conn:
        return {row[0] for row in conn.execute(
            f"""SELECT q.project_id FROM {TABLE} q WHERE status IN ('queued','failed')
                OR (status='deleted' AND NOT EXISTS
                    (SELECT 1 FROM projects p WHERE p.project_id=q.project_id))"""
        )}


def _mentions_project(value, project_id):
    if isinstance(value, dict):
        return any(_mentions_project(k, project_id) or _mentions_project(v, project_id) for k, v in value.items())
    if isinstance(value, list):
        return any(_mentions_project(v, project_id) for v in value)
    return value in (project_id, "actor:factory." + project_id) if isinstance(value, str) else False


def project_matches(db, project_ids):
    """Read persisted fight bindings without loading/replaying or repairing saves.

    MatchLock/Genesis cover portable combatants; FactoryIntegration covers
    factory teams (including opponents). Missing/unknown completion is unsafe.
    Malformed bindings refuse deletion rather than guess whose fight it is.
    """
    if not project_ids:
        return {}
    from combat.diagnostics import CombatGate1Error
    root = PermanentProjectDeletion(db)
    directory = root.checked("Combat/Matches")
    result = {pid: [] for pid in project_ids}
    if not directory.exists():
        return result
    for match in sorted(directory.iterdir()):
        root.checked(match.relative_to(root.root))
        if not match.is_dir():
            continue
        documents = {}
        for name in ("MatchLock.json", "GenesisState.json", "FactoryIntegration.json", "PortableRuntimeAuthority.json"):
            path = root.checked((match / name).relative_to(root.root))
            if path.exists():
                try:
                    documents[name] = json.loads(path.read_bytes())
                except (ValueError, OSError):
                    refuse("A saved fight's character bindings could not be read. Ask the owner to check the saved fights before deleting.")
        try:
            validate_bindings(documents, match.name)
        except (ValueError, TypeError, KeyError, FoundryError, CombatGate1Error):
            refuse("A saved fight's character bindings are missing or invalid. Ask the owner to check the saved fights before deleting.")
        members = [pid for pid in project_ids if any(_mentions_project(doc, pid) for doc in documents.values())]
        if not members:
            continue
        path = root.checked((match / "Manifest.json").relative_to(root.root))
        try:
            complete = json.loads(path.read_bytes()).get("status") == "COMPLETE"
        except (ValueError, OSError, AttributeError):
            complete = False
        for pid in members:
            result[pid].append((match.name, complete))
    return result


def validate_bindings(documents, directory_name):
    """Validate identity/participant authority only; never load or repair a fight."""
    from combat.gate3_storage import encode_match_directory_name
    lock = documents["MatchLock.json"]
    genesis = documents["GenesisState.json"]
    if not isinstance(lock, dict) or not isinstance(genesis, dict):
        raise ValueError("missing identity")
    match_id = lock.get("match_id")
    if (not isinstance(match_id, str) or not match_id
            or directory_name not in {encode_match_directory_name(match_id), match_id}
            or lock.get("schema") != "TianxiaCombatMatchLock.v1"
            or genesis.get("schema") != "TianxiaCombatGenesis.v1"
            or genesis.get("match_id") != match_id):
        raise ValueError("unknown identity")
    actors = lock.get("actor_ids")
    state = genesis.get("state")
    if (not isinstance(actors, list) or not actors
            or any(not isinstance(a, str) or not a for a in actors)
            or len(set(actors)) != len(actors)
            or not isinstance(state, dict) or state.get("match_id") != match_id
            or not isinstance(state.get("actors"), dict)
            or set(state["actors"]) != set(actors)
            or any(not isinstance(a, dict) or a.get("entity_id") != key
                   for key, a in state["actors"].items())):
        raise ValueError("unknown participants")
    for actor_id in actors:
        if actor_id.startswith("actor:factory."):
            identifier(actor_id[len("actor:factory."):])
    portable_actors = {a for a in actors if a.startswith("portable-character:")}
    if portable_actors and "PortableRuntimeAuthority.json" not in documents:
        raise ValueError("missing portable ownership")
    if "FactoryIntegration.json" in documents:
        doc = documents["FactoryIntegration.json"]
        if (not isinstance(doc, dict) or doc.get("schema") != "TianxiaFactoryCombatIntegration.v1"
                or doc.get("match_id") != match_id
                or not isinstance(doc.get("participant_control_modes"), dict)
                or not doc["participant_control_modes"]
                or any(a not in actors or not isinstance(mode, str) or not mode
                       for a, mode in doc["participant_control_modes"].items())):
            raise ValueError("unknown integration")
        if "factory_match" in doc:
            factory = doc["factory_match"]
            if not isinstance(factory, dict) or not isinstance(factory.get("project_ids"), list) or not factory["project_ids"]:
                raise ValueError("unknown factory bindings")
            for pid in factory["project_ids"]:
                identifier(pid)
                if "actor:factory." + pid not in actors:
                    raise ValueError("factory participant mismatch")
            if "opponent_actor_ids" in factory and (not isinstance(factory["opponent_actor_ids"], list)
                    or any(a not in actors for a in factory["opponent_actor_ids"])):
                raise ValueError("unknown opponents")
    if "PortableRuntimeAuthority.json" in documents:
        from combat.portable_runtime_authority import PortableRuntimeAuthority
        authority = PortableRuntimeAuthority.model_validate(documents["PortableRuntimeAuthority.json"])
        identifier(authority.project_id)
        if authority.runtime_actor_id not in actors:
            raise ValueError("portable participant mismatch")
        if portable_actors != {authority.runtime_actor_id}:
            raise ValueError("unknown portable ownership")


class ProjectDeletionQueue:
    def __init__(self, db):
        self.db = db

    def request(self, project_id, *, requested_by, confirmation):
        project_id = identifier(project_id)
        if confirmation != project_id:
            refuse("Confirm the exact character project before deleting it.", code="PROJECT_DELETE_CONFIRMATION_REQUIRED", status=400)
        with self.db.transaction() as conn:
            # Repeated clicks leave the original request and audit metadata intact.
            existing = conn.execute(f"SELECT status FROM {TABLE} WHERE project_id=?", (project_id,)).fetchone()
            if conn.execute(f"SELECT 1 FROM {TABLE} WHERE project_id=? AND recovery_required=1", (project_id,)).fetchone():
                refuse("The owner must recover this character before requesting deletion again. Undo cannot clear the recovery halt.")
            if existing and existing[0] == "queued":
                return {"project_id": project_id, "queued": True}
            if conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is None:
                refuse("No character project has that ID.", status=404)
            archived = conn.execute("SELECT 1 FROM character_library_archives WHERE project_id=?", (project_id,)).fetchone()
            lifecycle = conn.execute("SELECT persistence_state FROM character_builder_project_lifecycle WHERE project_id=?", (project_id,)).fetchone()
            if not archived and (not lifecycle or lifecycle[0] not in {"temporary", "saved_draft"}):
                refuse("Archive a finished or active character before deleting it permanently.")
            conn.execute(f"""INSERT INTO {TABLE}(project_id,requested_by,requested_at,confirmation,status)
                VALUES(?,?,?,?,'queued') ON CONFLICT(project_id) DO UPDATE SET
                requested_by=excluded.requested_by,requested_at=excluded.requested_at,
                confirmation=excluded.confirmation,status='queued',reason=NULL,backup=NULL,quarantine=NULL,processed_at=NULL""",
                (project_id, requested_by, utcnow(), confirmation))
        return {"project_id": project_id, "queued": True}

    def undo(self, project_id):
        with self.db.transaction() as conn:
            changed = conn.execute(f"DELETE FROM {TABLE} WHERE project_id=? AND status IN ('queued','failed') AND recovery_required=0", (project_id,)).rowcount
        return {"project_id": project_id, "queued": False, "changed": bool(changed)}

    def hidden_cards(self):
        with self.db.connection() as conn:
            return [dict(row) for row in conn.execute(f"""SELECT p.project_id,p.working_name,
                l.persistence_state AS builder_persistence_state,a.archived_at,
                q.status AS deletion_status,q.reason AS deletion_reason,q.requested_at AS deletion_requested_at
                FROM {TABLE} q JOIN projects p ON p.project_id=q.project_id
                LEFT JOIN character_builder_project_lifecycle l ON l.project_id=p.project_id
                LEFT JOIN character_library_archives a ON a.project_id=p.project_id
                WHERE q.status IN ('queued','failed') ORDER BY q.requested_at DESC,p.project_id""")]

    def process_at_startup(self):
        """Synchronous, before app services exist. Failed requests need owner retry.

        An empty queue returns before ownership walking, file reads or backups.
        Unexpected failures expose plain text, never internal exception details.
        """
        with self.db.connection() as conn:
            recovery = conn.execute(f"SELECT * FROM {TABLE} WHERE recovery_required=1 ORDER BY project_id LIMIT 1").fetchone()
            if recovery:
                halt_for_recovery(self.db, dict(recovery))
            requests = [dict(row) for row in conn.execute(f"SELECT * FROM {TABLE} WHERE status='queued' ORDER BY requested_at,project_id")]
        results = []
        for request in requests:
            pid = request["project_id"]
            result = None
            restore_failed = False
            try:
                if request["confirmation"] != pid:
                    refuse("The saved deletion confirmation does not match this character. Undo delete and try again.")
                if any(not complete for _, complete in project_matches(self.db, {pid})[pid]):
                    refuse("Finish this character's saved fight before deleting it permanently.")
                result = PermanentProjectDeletion(self.db).delete(pid)
                if result["cleanup_pending"]:
                    # Cleanup can fail after SQLite committed. The complete
                    # verified backup restores the project, even if quarantine
                    # has already been partly removed. Never overwrite a root.
                    try:
                        PermanentProjectDeletion(self.db).restore(self.db.settings.data_dir / result["backup"])
                    except Exception:
                        restore_failed = True
                        raise
                    refuse("The character was restored because backup cleanup could not finish. Ask the owner to check the backup folder before trying again.")
            except Exception as exc:
                incomplete = isinstance(exc, IncompleteDeletionRollback) or restore_failed
                backup = exc.backup if isinstance(exc, IncompleteDeletionRollback) else result["backup"] if result else None
                quarantine = exc.quarantine if isinstance(exc, IncompleteDeletionRollback) else result["cleanup_pending"] if restore_failed else None
                reason = exc.message if isinstance(exc, FoundryError) else "Deletion could not finish safely. Ask the owner to check the character and its backup before trying again."
                with self.db.transaction() as conn:
                    conn.execute(f"UPDATE {TABLE} SET status='failed',reason=?,backup=?,quarantine=?,recovery_required=?,processed_at=? WHERE project_id=?", (reason, backup, quarantine, int(incomplete), utcnow(), pid))
                if incomplete:
                    halt_for_recovery(self.db, {"project_id": pid, "backup": backup, "quarantine": quarantine})
                results.append({"project_id": pid, "status": "failed", "reason": reason})
            else:
                with self.db.transaction() as conn:
                    conn.execute(f"UPDATE {TABLE} SET status='deleted',backup=?,processed_at=? WHERE project_id=?", (result["backup"], utcnow(), pid))
                results.append({**result, "status": "deleted"})
        return results
