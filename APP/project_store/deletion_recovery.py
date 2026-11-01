"""Offline owner recovery for a halted deletion; never overwrite a project.

Uses the existing verified backup/restore primitive. Clearing the interlock
requires exact restored project rows and files; Undo is deliberately unrelated.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core import Database, Settings
from project_store.deletion_queue import TABLE, recovery_message
from project_store.permanent_deletion import PermanentProjectDeletion, encode, identifier, refuse


def normalized(rows):
    return {table: sorted(json.dumps({key: encode(value) for key, value in row.items()
                                     if key != "__rowid__"}, sort_keys=True)
                          for row in values)
            for table, values in rows.items()}


def recover(db, project_id):
    """Reconcile exact retained paths, verify backup equality, then release halt.

    With rolled-back rows, return intact remaining quarantine entries. With
    absent rows, restore from ZIP only if no partial owned paths exist. Refuse
    conflicts without overwriting them, leaving the durable interlock in place.
    """
    project_id = identifier(project_id)
    with db.connection() as conn:
        request = conn.execute(f"SELECT * FROM {TABLE} WHERE project_id=? AND recovery_required=1", (project_id,)).fetchone()
    if request is None:
        refuse("This character has no unresolved deletion recovery halt.")
    request = dict(request)
    storage = PermanentProjectDeletion(db)
    backup = storage.checked(request["backup"])
    manifest, _ = storage.read_backup(backup)
    if manifest["project_id"] != project_id:
        refuse("The retained backup belongs to another character. Keep the recovery halt.")
    with db.connection() as conn:
        schema, rows = storage.snapshot(conn, project_id)
    already_verified = (schema == manifest["schema"]
                        and normalized(rows) == normalized(manifest["rows"])
                        and storage.tree(manifest["roots"]) == manifest["entries"])
    if rows and not already_verified:
        quarantine = storage.checked(request["quarantine"])
        if quarantine.exists():
            recovery_path = storage.checked((quarantine / "recovery.json").relative_to(storage.root))
            recovery = json.loads(recovery_path.read_bytes())
            expected_paths = {str(index): name for index, name in enumerate(manifest["roots"])}
            if (recovery.get("project_id") != project_id or recovery.get("backup") != request["backup"]
                    or recovery.get("paths") != expected_paths):
                refuse("Quarantine recovery paths do not match the verified backup. Keep the recovery halt.")
            # Validate every remaining member before the first move. Unknown
            # entries and changed bytes must never become publication authority.
            if {p.name for p in quarantine.iterdir()} - set(expected_paths) - {"recovery.json"}:
                refuse("Quarantine contains unknown files. Keep the recovery halt.")
            moves = []
            for index, relative in expected_paths.items():
                source = storage.checked((quarantine / index).relative_to(storage.root))
                if not source.exists():
                    continue
                target = storage.checked(relative)
                if target.exists():
                    refuse("A character path conflicts with quarantine. Preserve both copies and keep the recovery halt.")
                prefix = source.relative_to(storage.root).as_posix()
                entries = {relative + name[len(prefix):]: entry for name, entry in storage.tree([prefix]).items()}
                expected = {name: entry for name, entry in manifest["entries"].items()
                            if name == relative or name.startswith(relative + "/")}
                if entries != expected:
                    refuse("Quarantined character files differ from the verified backup. Keep the recovery halt.")
                moves.append((source, target))
            for source, target in moves:
                storage.move_owned(source, target)
    elif not rows:
        # The primitive refuses any existing rows or paths. Never restore over
        # partial publication after a failed restore rollback.
        storage.restore(backup)
    with db.connection() as conn:
        schema, rows = storage.snapshot(conn, project_id)
    if (schema != manifest["schema"] or normalized(rows) != normalized(manifest["rows"])
            or storage.tree(manifest["roots"]) != manifest["entries"]):
        refuse("Character rows or files do not exactly match the verified backup. Keep the recovery halt and preserve all copies for owner review.")
    with db.transaction() as conn:
        conn.execute(f"UPDATE {TABLE} SET recovery_required=0,reason=? WHERE project_id=? AND recovery_required=1",
                     ("The owner recovered and verified this character. Undo delete before trying again.", project_id))
    return {"project_id": project_id, "recovered": True, "backup": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    db = Database(Settings.from_env(Path(__file__).resolve().parents[1], args.data_root.absolute()))
    # Startup already migrated this root. Do not migrate or construct services.
    try:
        result = recover(db, args.project)
    except Exception as exc:
        with db.connection() as conn:
            request = conn.execute(f"SELECT * FROM {TABLE} WHERE project_id=? AND recovery_required=1", (args.project,)).fetchone()
        print(f"Recovery refused: {exc}")
        if request:
            print(recovery_message(db, dict(request)))
        raise SystemExit(1) from exc
    print(f"Character restored and verified; startup halt cleared. Retained backup: {result['backup']}. You may now restart the Factory.")


if __name__ == "__main__":
    main()
