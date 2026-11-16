"""Run-owned file publication for CharacterCreationExecutionService.

Order: stage files; commit all character rows AND the run's publishing receipt
in one live Database transaction; atomically rename each staged output into
place (retaining replaced files); mark the lifecycle done; discard staging.
Before commit, failure is a database rollback and staging removal. After commit,
recovery always rolls forward, including after interruption between renames.
The receipt, not a database/file snapshot, is the publication authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields, replace
import fcntl
import json
import os
from pathlib import Path
import shutil
import uuid

from app.core import Database, canonical_json, utcnow


def remove_tree(path: Path) -> None:
    def retry(function, target, _error):
        for item in (os.path.dirname(target), target):
            try:
                os.chmod(item, 0o700)
            except OSError:
                pass
        function(target)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=retry)
    else:
        path.unlink(missing_ok=True)


def publication_root(db: Database) -> Path:
    data = db.settings.data_dir
    return data.parent / ("." + data.name + "-finalizations")


@contextmanager
def publication_lock(db: Database):
    root = publication_root(db)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def relocate(value, source: Path, target: Path):
    """Translate transient absolute output paths, not artifact contents/hashes."""
    if isinstance(value, dict):
        return {key: relocate(item, source, target) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate(item, source, target) for item in value]
    if isinstance(value, str):
        prefix = str(source) + os.sep
        if value.startswith(prefix):
            return str(target) + value[len(str(source)):]
    return value


class Publication:
    def __init__(self, db: Database, directory: Path):
        self.db = db
        self.directory = directory
        self.data = directory / "data"
        self.backups = directory / "replaced"
        self.baseline = {}
        self.baseline_modes = {}

    @classmethod
    def stage(cls, service):
        from .service import _reflink_copy2
        db = service.db
        directory = publication_root(db) / uuid.uuid4().hex
        publication = cls(db, directory)
        publication.data.mkdir(parents=True)
        try:
            excluded = service._snapshot_excluded_names()
            for child in db.settings.data_dir.iterdir():
                if child.name in excluded or child in {
                    db.settings.db_path, Path(str(db.settings.db_path) + "-wal"),
                    Path(str(db.settings.db_path) + "-shm"),
                }:
                    continue
                target = publication.data / child.name
                if child.is_dir():
                    shutil.copytree(child, target, symlinks=False, copy_function=_reflink_copy2)
                else:
                    _reflink_copy2(child, target)
            publication.baseline = publication.file_stats()
            publication.baseline_modes = publication.directory_modes()
            return publication
        except BaseException:
            remove_tree(directory)
            raise

    def file_stats(self):
        return {
            path.relative_to(self.data).as_posix(): (
                path.lstat().st_mtime_ns, path.lstat().st_ctime_ns,
                path.lstat().st_size, path.lstat().st_ino,
            )
            for path in self.data.rglob("*") if path.is_file() or path.is_symlink()
        }

    def directory_modes(self):
        return {path.relative_to(self.data).as_posix(): path.stat().st_mode & 0o777
                for path in self.data.rglob("*") if path.is_dir()}

    def database(self):
        settings = self.db.settings
        replacements = {"data_dir": self.data}
        for field in fields(settings):
            value = getattr(settings, field.name)
            if field.name in {"root_dir", "db_path", "factory_zip", "fixture_path"}:
                continue
            if isinstance(value, Path):
                try:
                    replacements[field.name] = self.data / value.relative_to(settings.data_dir)
                except ValueError:
                    pass
        staged = Database(replace(settings, **replacements),
                          published_data_dir=settings.data_dir)
        return staged

    def receipt(self):
        current = self.file_stats()
        changed = sorted(name for name, stat in current.items()
                         if self.baseline.get(name) != stat)
        for name in changed:
            path = self.data / name
            # Mutable discovery pointers contain absolute locations, unlike sealed
            # artifact payloads. Keep their locations valid after the rename.
            if path.name == "current.json" and not path.is_symlink():
                raw = json.loads(path.read_text(encoding="utf-8"))
                relocated = relocate(raw, self.data, self.db.settings.data_dir)
                if relocated != raw:
                    path.write_text(canonical_json(relocated), encoding="utf-8")
            if path.is_symlink():
                raise ValueError("Finalization outputs must not be symlinks")
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
            sync_directory(path.parent)
        for directory in sorted((p for p in self.data.rglob("*") if p.is_dir()),
                                key=lambda p: len(p.parts), reverse=True):
            sync_directory(directory)
        sync_directory(self.data)
        sync_directory(self.directory)
        sync_directory(self.directory.parent)
        modes = {name: mode for name, mode in self.directory_modes().items()
                 if self.baseline_modes.get(name) != mode}
        return {"state": "publishing", "directory": self.directory.name,
                "files": changed, "directory_modes": modes}

    def promote(self, receipt, fail_after=None):
        self.backups.mkdir(exist_ok=True)
        for ordinal, name in enumerate(receipt["files"]):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid publication path")
            staged = self.data / relative
            live = self.db.settings.data_dir / relative
            backup = self.backups / relative
            if staged.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                # Never follow a live ancestor symlink outside the data root.
                if not live.parent.resolve().is_relative_to(self.db.settings.data_dir.resolve()):
                    raise ValueError("Publication path leaves the data root")
                if (live.exists() or live.is_symlink()) and not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    # Retain the old inode without removing the live name: the
                    # subsequent replace is one atomic old-to-new publication.
                    os.link(live, backup, follow_symlinks=False)
                    sync_directory(backup.parent)
                os.replace(staged, live)
                sync_directory(staged.parent)
                sync_directory(live.parent)
            elif not live.is_file():
                raise FileNotFoundError(f"Missing publication output: {name}")
            if ordinal == 0:
                failpoint("mid_promotion", fail_after)
        for name, mode in sorted(receipt.get("directory_modes", {}).items(), reverse=True):
            directory = self.db.settings.data_dir / name
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(mode)
            sync_directory(directory)

    def discard(self):
        if self.directory.exists():
            remove_tree(self.directory)


def failpoint(phase, fail_after):
    if fail_after == phase:
        raise RuntimeError("forced failure after " + phase)


def finish(db, run_id, commit, fail_after=None):
    receipt = commit["publication"]
    publication = Publication(db, publication_root(db) / receipt["directory"])
    publication.promote(receipt, fail_after)
    failpoint("after_promotion", fail_after)
    commit = {**commit, "publication": {**receipt, "state": "done"}}
    now = utcnow()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET commit_json=?,status='CLEAN_AND_FINALIZED',"
            "updated_at=?,completed_at=? WHERE run_id=?",
            (canonical_json(commit), now, now, run_id),
        )
    publication.discard()


def recover(db):
    """Called under publication_lock at startup and before a new finalization."""
    with db.connection() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='character_creation_runs'").fetchone():
            return
        rows = conn.execute(
            "SELECT run_id,commit_json FROM character_creation_runs "
            "WHERE status IN ('PUBLISHING','CLEAN_AND_FINALIZED')"
        ).fetchall()
    for row in rows:
        commit = json.loads(row["commit_json"] or "{}")
        receipt = commit.get("publication")
        if not receipt:
            continue
        directory = receipt["directory"]
        if Path(directory).name != directory or directory in {".", ".."}:
            raise ValueError("Invalid publication directory")
        if receipt["state"] == "publishing":
            finish(db, row["run_id"], commit)
        else:
            Publication(db, publication_root(db) / directory).discard()
    # The lock excludes an in-flight stage. Anything left without a publishing
    # record was interrupted before commit and owns no live files or rows.
    root = publication_root(db)
    for directory in root.iterdir():
        if directory.is_dir():
            remove_tree(directory)
