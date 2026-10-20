"""Project-only backup, deletion and restore; never restore or erase a data root.

Shared catalogues, security, fights and exports are deliberately not ownership
roots. Ownership is a project_id column or a descendant foreign key, plus the
explicit filesystem layouts below. New layouts must be added here with tests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path

from app.core import FoundryError, utcnow

PROJECT_FOLDERS = (
    "projects", "portable_characters", "character_sheets", "factory_workspaces",
    "factory_gm_authoring", "factory_candidates", "factory_final_character",
    "workspaces", "logs/gm_exports",
)
PROJECT_FILES = ("owner_items", "tabletop_buttons")
RUN_ID_FOLDERS = ("logs/cg1_release",)
RUN_FOLDERS = {
    "character_creation_gm_candidates/runs": 32,
    "character_creation_gm_authoring/runs": 32,
    "creation_training_authority_supplements/runs": 64,
    "agent_acquisition_corrections/runs": 64,
}
AUTHORIZATIONS = "project_permanent_delete_authorizations"


class IncompleteDeletionRollback(RuntimeError):
    """Files could not return from quarantine; normal startup must stay halted."""

    def __init__(self, project_id, backup, quarantine):
        super().__init__("Character files could not be returned from quarantine.")
        self.project_id = project_id
        self.backup = backup
        self.quarantine = quarantine


def refuse(message, *, code="PROJECT_PERMANENT_DELETE_REFUSED", status=409):
    raise FoundryError(code, message, status_code=status)


def identifier(value):
    try:
        canonical = str(uuid.UUID(value)) if isinstance(value, str) else None
    except (ValueError, AttributeError):
        canonical = None
    if canonical != value or canonical is None:
        refuse("Use a valid character project ID.", status=400)
    return value


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def encode(value):
    return {"blob": base64.b64encode(value).decode("ascii")} if isinstance(value, bytes) else value


def decode(value):
    return base64.b64decode(value["blob"], validate=True) if isinstance(value, dict) else value


class PermanentProjectDeletion:
    def __init__(self, db):
        self.db = db
        self.root = Path(db.settings.data_dir).absolute()
        if self.root == Path("/") or self.root.resolve() != self.root:
            refuse("The character data root must be a real directory, not a link.")
        if Path(db.settings.db_path).absolute() != self.root / "foundry.sqlite3":
            refuse("The character database must belong to this exact data root.")
        self.root_identity = (self.root.stat().st_dev, self.root.stat().st_ino)
        database = self.checked("foundry.sqlite3")
        if database.stat().st_nlink != 1:
            refuse("The character database must not be shared through a hard link.")

    def checked(self, relative):
        path = Path(relative)
        if path.is_absolute() or not path.parts or any(p in {".", ".."} for p in path.parts):
            refuse("A character path is outside its expected folder.")
        if (self.root.stat().st_dev, self.root.stat().st_ino) != self.root_identity:
            refuse("The character data root changed during the operation.")
        candidate = self.root
        for component in path.parts:
            candidate = candidate / component
            if candidate.is_symlink():
                refuse("Character paths must not contain symbolic links.")
        if candidate.resolve() != candidate or not candidate.is_relative_to(self.root) or candidate == self.root:
            refuse("A character path is outside its expected folder.")
        return candidate

    @staticmethod
    def schema(conn):
        tables = {}
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            name = row[0]
            if name in {AUTHORIZATIONS, "character_builder_temporary_delete_authorizations", "project_deletion_requests"}:
                continue
            tables[name] = {
                "columns": [r["name"] for r in conn.execute(f"PRAGMA table_info({quote(name)})")],
                "fks": [dict(r) for r in conn.execute(f"PRAGMA foreign_key_list({quote(name)})")],
            }
        return tables

    @staticmethod
    def snapshot(conn, project_id):
        """Walk project columns then child FKs, refusing cross-project references."""
        schema = PermanentProjectDeletion.schema(conn)
        owned = {name: {} for name in schema}
        for name, info in schema.items():
            if "project_id" in info["columns"]:
                for r in conn.execute(f"SELECT rowid AS __rowid__, * FROM {quote(name)} WHERE project_id=?", (project_id,)):
                    owned[name][r["__rowid__"]] = dict(r)
        # Approval subjects are explicit logical references, not SQLite FKs.
        if "exact_approval_challenges" in schema:
            proposal_ids = [r["proposal_id"] for r in owned.get("stage2_proposals", {}).values()]
            for pid in proposal_ids:
                for r in conn.execute("SELECT rowid AS __rowid__, * FROM exact_approval_challenges WHERE subject_type IN ('stage2_proposal','stage2_proposal_v1') AND subject_id=?", (pid,)):
                    owned["exact_approval_challenges"][r["__rowid__"]] = dict(r)
            record_ids = {r["record_id"] for table in ("project_locked_record_refs", "stage2_project_scoped_records") for r in owned.get(table, {}).values()}
            for rid in record_ids:
                for r in conn.execute("SELECT rowid AS __rowid__, * FROM exact_approval_challenges WHERE subject_type='project_custom_training_source' AND subject_id=?", (rid,)):
                    owned["exact_approval_challenges"][r["__rowid__"]] = dict(r)
        if "canonical_object_validations" in schema:
            for r in conn.execute("SELECT rowid AS __rowid__, * FROM canonical_object_validations WHERE object_family='character_project' AND object_key=?", (project_id,)):
                owned["canonical_object_validations"][r["__rowid__"]] = dict(r)
        if "exact_approval_evidence" in schema:
            for r in conn.execute("SELECT rowid AS __rowid__, * FROM exact_approval_evidence WHERE json_valid(evidence_json) AND json_extract(evidence_json,'$.approval_context.project_id')=?", (project_id,)):
                owned["exact_approval_evidence"][r["__rowid__"]] = dict(r)
                for challenge in conn.execute("SELECT rowid AS __rowid__, * FROM exact_approval_challenges WHERE challenge_id=?", (r["challenge_id"],)):
                    owned["exact_approval_challenges"][challenge["__rowid__"]] = dict(challenge)
        changed = True
        while changed:
            changed = False
            for name, info in schema.items():
                grouped = {}
                for fk in info["fks"]:
                    grouped.setdefault(fk["id"], []).append(fk)
                for group in grouped.values():
                    parent = group[0]["table"]
                    for parent_row in list(owned.get(parent, {}).values()):
                        if any(f["to"] is None for f in group):
                            refuse("A foreign key has no explicit ownership column.")
                        values = [parent_row[f["to"]] for f in group]
                        if any(v is None for v in values):
                            continue
                        where = " AND ".join(f"{quote(f['from'])}=?" for f in group)
                        for r in conn.execute(f"SELECT rowid AS __rowid__, * FROM {quote(name)} WHERE {where}", values):
                            if r["__rowid__"] in owned[name]:
                                continue
                            if "project_id" in r.keys() and r["project_id"] != project_id:
                                refuse("Another character refers to this character's data; deletion is unsafe.")
                            owned[name][r["__rowid__"]] = dict(r)
                            changed = True
        # A link table can have no project_id yet connect two different
        # characters. Refuse rather than removing the other character's link.
        domain = {name for name, info in schema.items() if "project_id" in info["columns"]}
        domain.add("exact_approval_challenges")
        changed = True
        while changed:
            expanded = domain | {name for name, info in schema.items() if any(f["table"] in domain for f in info["fks"])}
            changed = expanded != domain
            domain = expanded
        for name, rs in owned.items():
            grouped = {}
            for fk in schema[name]["fks"]:
                if fk["table"] in domain:
                    grouped.setdefault(fk["id"], []).append(fk)
            for row in rs.values():
                for group in grouped.values():
                    values = [row[f["from"]] for f in group]
                    if any(v is None for v in values):
                        continue
                    parent = group[0]["table"]
                    where = " AND ".join(f"{quote(f['to'])}=?" for f in group)
                    for parent_row in conn.execute(f"SELECT rowid FROM {quote(parent)} WHERE {where}", values):
                        if parent_row[0] not in owned[parent]:
                            refuse("A character link belongs to another project; deletion is unsafe.")
        # Approval evidence has no project_id column: its explicit project
        # binding lives in JSON. A parent FK must not override that binding.
        # Restore also uses this ownership walk in its isolated probe.
        for row in owned.get("exact_approval_evidence", {}).values():
            try:
                document = json.loads(row["evidence_json"])
                context = document.get("approval_context", {})
                if not isinstance(context, dict):
                    raise ValueError("Invalid approval context")
            except (ValueError, TypeError, AttributeError):
                refuse("Character approval evidence has an invalid project binding.")
            if "project_id" in context and context["project_id"] != project_id:
                refuse("Character approval evidence belongs to another project; deletion or restore is unsafe.")
        return schema, {name: list(rows.values()) for name, rows in owned.items() if rows}

    def require_allowed(self, conn, project_id, schema):
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            refuse("No character project has that ID.", status=404)
        archived = "character_library_archives" in schema and conn.execute("SELECT 1 FROM character_library_archives WHERE project_id=?", (project_id,)).fetchone()
        lifecycle = conn.execute("SELECT persistence_state FROM character_builder_project_lifecycle WHERE project_id=?", (project_id,)).fetchone()
        state = lifecycle[0] if lifecycle else None
        finalized = conn.execute("SELECT 1 FROM character_creation_runs WHERE project_id=? AND status='CLEAN_AND_FINALIZED'", (project_id,)).fetchone()
        status = str(row["status"]) if "status" in row.keys() else ""
        if not archived and (state not in {"temporary", "saved_draft"} or finalized or status in {"active", "finished", "completed"}):
            refuse("Archive a finished or active character before deleting it permanently.")
        active = conn.execute("SELECT 1 FROM character_creation_runs WHERE project_id=? AND status NOT IN ('CLEAN_AND_FINALIZED','CANCELLED','REVISED')", (project_id,)).fetchone()
        if active:
            refuse("Cancel or finish this character's active build before deleting it permanently.")

    def paths(self, project_id, rows, *, review_records=None):
        paths = [f"{folder}/{project_id}" for folder in PROJECT_FOLDERS]
        paths += [f"{folder}/{project_id}.json" for folder in PROJECT_FILES]
        for row in rows.get("character_creation_runs", []):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", row["run_id"]):
                refuse("A build run has an unsafe filesystem ID.")
            paths += [f"{folder}/{row['run_id']}" for folder in RUN_ID_FOLDERS]
            digest = hashlib.sha256(row["run_id"].encode("utf-8")).hexdigest()
            paths += [f"{folder}/{digest[:length]}" for folder, length in RUN_FOLDERS.items()]
            paths += [f"diagnostics/character_creation/{digest[:32]}.jsonl"]
        # Review receipts live in a shared directory. Select individual files
        # only by their explicit project binding, never by a filename glob.
        if review_records is None:
            review_records = {}
            directory = self.checked("factory_final_character/reviews")
            if directory.exists():
                for path in sorted(directory.iterdir()):
                    if re.fullmatch(r"final-review\.[0-9a-f]{64}\.json", path.name):
                        self.checked(path.relative_to(self.root))
                        document = json.loads(path.read_bytes())
                        if document.get("binding", {}).get("project_id") == project_id:
                            review_records[path.name] = document
        for name, document in review_records.items():
            if not re.fullmatch(r"final-review\.[0-9a-f]{64}\.json", name) or document.get("binding", {}).get("project_id") != project_id or document.get("record_id") != name[:-5]:
                refuse("A final-character review file has an invalid project binding.")
            paths.append(f"factory_final_character/reviews/{name}")
        return sorted(set(paths))

    def tree(self, roots):
        entries = {}
        def visit(path):
            relative = path.relative_to(self.root).as_posix()
            self.checked(relative)
            info = path.stat()
            mode = info.st_mode
            if stat.S_ISDIR(mode):
                entries[relative] = {"kind": "directory", "mode": stat.S_IMODE(mode), "mtime_ns": info.st_mtime_ns}
                for child in sorted(path.iterdir()):
                    visit(child)
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                entries[relative] = {"kind": "file", "mode": stat.S_IMODE(mode), "mtime_ns": info.st_mtime_ns, "sha256": digest.hexdigest(), "size": size}
            else:
                refuse("Only ordinary character files and folders can be backed up.")
        for relative in roots:
            path = self.checked(relative)
            if path.exists():
                visit(path)
        return entries

    def backup(self, project_id, schema, rows, roots):
        entries = self.tree(roots)
        manifest = {
            "format": "CultivationFactory.DeletedProject.v1", "project_id": project_id,
            "created_at": utcnow(), "data_root": str(self.root), "schema": schema,
            "rows": {t: [{k: encode(v) for k, v in r.items()} for r in rs] for t, rs in rows.items()},
            "roots": roots, "entries": entries,
        }
        relative = f"backups/deleted-characters/{utcnow().replace(':', '').replace('.', '-')}-{project_id}-{uuid.uuid4().hex[:8]}.zip"
        path = self.checked(relative)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        created = False
        try:
            with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                created = True
                archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
                for name, entry in entries.items():
                    if entry["kind"] == "file":
                        archive.write(self.checked(name), "files/" + name)
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            path.chmod(0o600)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            verified, _ = self.read_backup(path)
            if verified != manifest or self.tree(roots) != entries:
                refuse("Character data changed while its backup was being written.")
        except Exception:
            # An incomplete archive is never evidence that deletion is safe.
            if created:
                path.unlink(missing_ok=True)
            raise
        return path, manifest

    def read_backup(self, path):
        path = Path(path).absolute()
        if path.parent != self.root / "backups/deleted-characters" or path.suffix != ".zip":
            refuse("Restore requires a deleted-character backup from this data root.")
        self.checked(path.relative_to(self.root))
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                refuse("The character backup failed verification.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "CultivationFactory.DeletedProject.v1":
                refuse("This is not a deleted-character backup.")
            if manifest.get("data_root") != str(self.root):
                refuse("This backup belongs to a different character data root.")
            pid = identifier(manifest["project_id"])
            rows = {t: [{k: decode(v) for k, v in r.items()} for r in rs] for t, rs in manifest["rows"].items()}
            review_records = {
                Path(name).name: json.loads(archive.read("files/" + name))
                for name, entry in manifest["entries"].items()
                if name.startswith("factory_final_character/reviews/") and entry["kind"] == "file"
            }
            if manifest["roots"] != self.paths(pid, rows, review_records=review_records):
                refuse("The backup contains an unexpected character folder.")
            expected = {"manifest.json"}
            contents = {}
            for name, entry in manifest["entries"].items():
                self.checked(name)
                if not any(name == root or name.startswith(root + "/") for root in manifest["roots"]):
                    refuse("A backup file is outside this character's folders.")
                if entry["kind"] == "file":
                    expected.add("files/" + name)
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open("files/" + name) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                            size += len(chunk)
                    if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                        refuse("The character backup failed verification.")
                    contents[name] = "files/" + name
                elif entry["kind"] != "directory":
                    refuse("The character backup contains an invalid file type.")
            if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
                refuse("The character backup contains unexpected or duplicate files.")
        return manifest, contents

    @staticmethod
    def delete_rows(conn, schema, rows):
        conn.execute("PRAGMA defer_foreign_keys=ON")
        if conn.execute(f"SELECT 1 FROM {AUTHORIZATIONS} LIMIT 1").fetchone():
            refuse("Another deletion authorization exists; deletion cannot proceed safely.")
        # Exact row authorizations make append-only guards inert only for this
        # verified snapshot. They never survive the transaction.
        conn.executemany(f"INSERT INTO {AUTHORIZATIONS}(table_name,row_id) VALUES(?,?)", [(t, r["__rowid__"]) for t, rs in rows.items() for r in rs])
        remaining = set(rows)
        order = []
        while remaining:
            leaves = [t for t in sorted(remaining) if not any(f["table"] == t and child != t for child in remaining for f in schema[child]["fks"])]
            if not leaves:
                refuse("A cycle in character storage prevents safe deletion.")
            order.extend(leaves)
            remaining.difference_update(leaves)
        # Remove RESTRICT/NO ACTION descendants and tables without a project FK
        # explicitly. Direct CASCADE tables can be removed by the project row.
        for table in order:
            cascade = any(f["table"] == "projects" and f["on_delete"] == "CASCADE" for f in schema[table]["fks"])
            referenced = any(f["table"] == table and f["on_delete"] != "CASCADE" for info in schema.values() for f in info["fks"])
            restricts_parent = any(f["table"] in rows and f["on_delete"] != "CASCADE" for f in schema[table]["fks"])
            if table != "projects" and cascade and not referenced and not restricts_parent:
                continue
            conn.executemany(f"DELETE FROM {quote(table)} WHERE rowid=?", [(r["__rowid__"],) for r in rows[table]])
        for table, rs in rows.items():
            if any(conn.execute(f"SELECT 1 FROM {quote(table)} WHERE rowid=?", (r["__rowid__"],)).fetchone() for r in rs):
                refuse("Some character rows could not be removed safely.")
        conn.execute(f"DELETE FROM {AUTHORIZATIONS}")

    def delete(self, project_id):
        project_id = identifier(project_id)
        moved = []
        stage = None
        stage_created = False
        try:
            with self.db.transaction() as conn:
                schema, rows = self.snapshot(conn, project_id)
                self.require_allowed(conn, project_id, schema)
                roots = self.paths(project_id, rows)
                backup, manifest = self.backup(project_id, schema, rows, roots)
                stage = self.checked(f"backups/deleted-characters/.delete-{uuid.uuid4().hex}")
                stage.mkdir(mode=0o700)
                stage_created = True
                (stage / "recovery.json").write_text(json.dumps({"project_id": project_id, "backup": str(backup.relative_to(self.root)), "paths": dict(enumerate(roots))}, sort_keys=True))
                # Same-filesystem quarantine is reversible even for read-only
                # trees. On a DB failure put back only the exact paths moved.
                if self.tree(roots) != manifest["entries"]:
                    refuse("Character files changed before deletion.")
                for index, relative in enumerate(roots):
                    source = self.checked(relative)
                    if source.exists():
                        target = stage / str(index)
                        self.move_owned(source, target)
                        moved.append((source, target))
                # Verify the bytes actually being removed, not their former
                # pathnames. Remap quarantine names to the backup's names.
                quarantined = {}
                for source, target in moved:
                    original = source.relative_to(self.root).as_posix()
                    prefix = target.relative_to(self.root).as_posix()
                    for name, entry in self.tree([prefix]).items():
                        quarantined[original + name[len(prefix):]] = entry
                if quarantined != manifest["entries"]:
                    refuse("Character files changed while moving to backup. Deletion was cancelled and the character files were kept.")
                self.delete_rows(conn, schema, rows)
        except BaseException:
            try:
                for source, target in reversed(moved):
                    self.move_owned(target, source)
                if stage_created:
                    (stage / "recovery.json").unlink(missing_ok=True)
                    stage.rmdir()
            except BaseException as recovery_error:
                raise IncompleteDeletionRollback(
                    project_id, str(backup.relative_to(self.root)),
                    str(stage.relative_to(self.root)),
                ) from recovery_error
            raise
        cleanup_pending = None
        try:
            self.remove_stage(stage)
        except OSError:
            cleanup_pending = str(stage.relative_to(self.root))
        return {"project_id": project_id, "deleted": True, "backup": str(backup.relative_to(self.root)), "cleanup_pending": cleanup_pending}

    @staticmethod
    def move_owned(source, target):
        """Move one validated owned entry, retaining read-only directory modes.

        POSIX may require write permission on a directory when changing its
        parent. Change only that owned directory, and undo chmod on failure.
        """
        mode = stat.S_IMODE(source.stat().st_mode)
        directory = source.is_dir()
        if directory:
            source.chmod(mode | 0o700)
        try:
            source.rename(target)
        except BaseException:
            if directory:
                source.chmod(mode)
            raise
        if directory:
            try:
                target.chmod(mode)
            except BaseException:
                target.rename(source)
                source.chmod(mode)
                raise

    @staticmethod
    def remove_stage(stage):
        # Quarantine is task-owned; making its directories writable cannot
        # change any retained character. No parent/shared folder is chmodded.
        for directory, _, _ in os.walk(stage):
            os.chmod(directory, 0o700)
        shutil.rmtree(stage)

    def restore(self, backup_path):
        manifest, contents = self.read_backup(backup_path)
        pid = manifest["project_id"]
        rows = {t: [{k: decode(v) for k, v in r.items()} for r in rs] for t, rs in manifest["rows"].items()}
        stage = self.checked(f"backups/deleted-characters/.restore-{uuid.uuid4().hex}")
        stage_created = False
        moved = []
        try:
            with self.db.transaction() as conn:
                schema = self.schema(conn)
                if schema != manifest["schema"]:
                    refuse("Restore requires the same character database schema as the backup.")
                if conn.execute("SELECT 1 FROM projects WHERE project_id=?", (pid,)).fetchone():
                    refuse("This character already exists; restore never overwrites it.")
                for relative in manifest["roots"]:
                    if self.checked(relative).exists():
                        refuse("A character folder already exists; restore never overwrites it.")
                # Validate the row ownership closure using an isolated in-memory
                # SQLite copy before any real insert or file publication.
                import sqlite3
                probe = sqlite3.connect(":memory:", isolation_level=None)
                probe.row_factory = sqlite3.Row
                try:
                    for r in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"):
                        # Creating an FTS virtual table creates its shadows too.
                        if not probe.execute("SELECT 1 FROM sqlite_master WHERE name=?", (r[0],)).fetchone():
                            probe.execute(r[1])
                    for table, rs in rows.items():
                        if table not in schema:
                            refuse("The backup contains an unknown table.")
                        for row in rs:
                            if set(row) != set(schema[table]["columns"]) | {"__rowid__"}:
                                refuse("The backup contains unexpected row columns.")
                            keys = [k for k in row if k != "__rowid__"]
                            probe.execute(f"INSERT INTO {quote(table)}({','.join(map(quote, keys))}) VALUES({','.join('?' for _ in keys)})", [row[k] for k in keys])
                    _, closure = self.snapshot(probe, pid)
                    def normalized(data):
                        return {t: sorted(json.dumps({k: encode(v) for k, v in r.items() if k != '__rowid__'}, sort_keys=True) for r in rs) for t, rs in data.items()}
                    if normalized(closure) != normalized(rows) or len(rows.get("projects", [])) != 1:
                        refuse("The backup includes rows that do not belong to this character.")
                finally:
                    probe.close()
                conn.execute("PRAGMA defer_foreign_keys=ON")
                for table, rs in rows.items():
                    # Restoring projects/runs fires the library revision triggers.
                    # Restore the backed-up revision last, after those writes;
                    # all other tables retain strict insert-only restoration.
                    if table == "project_library_source_revision":
                        continue
                    for row in rs:
                        keys = [k for k in row if k != "__rowid__"]
                        conn.execute(f"INSERT INTO {quote(table)}({','.join(map(quote, keys))}) VALUES({','.join('?' for _ in keys)})", [row[k] for k in keys])
                for row in rows.get("project_library_source_revision", []):
                    conn.execute(
                        "INSERT INTO project_library_source_revision(project_id,revision) VALUES(?,?) "
                        "ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision",
                        (row["project_id"], row["revision"]),
                    )
                stage.mkdir(mode=0o700)
                stage_created = True
                with zipfile.ZipFile(backup_path) as archive:
                    for name, entry in sorted(manifest["entries"].items(), key=lambda item: (len(Path(item[0]).parts), item[0])):
                        target = stage / name
                        if entry["kind"] == "directory":
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(contents[name]) as source, target.open("xb") as destination:
                                shutil.copyfileobj(source, destination, length=1024 * 1024)
                            digest = hashlib.sha256()
                            with target.open("rb") as stream:
                                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                    digest.update(chunk)
                            if target.stat().st_size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                                refuse("The backup changed during restore.")
                for name, entry in sorted(manifest["entries"].items(), reverse=True):
                    (stage / name).chmod(entry["mode"])
                    os.utime(stage / name, ns=(entry["mtime_ns"], entry["mtime_ns"]))
                for relative in manifest["roots"]:
                    source = stage / relative
                    if source.exists():
                        target = self.checked(relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        self.move_owned(source, target)
                        moved.append((source, target))
        except BaseException:
            for source, target in reversed(moved):
                self.move_owned(target, source)
            raise
        finally:
            if stage_created:
                self.remove_stage(stage)
        return {"project_id": pid, "restored": True}
