"""SQLite transaction context managers do not release backup handles."""
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.core import Database, Settings
from character_creation.service import CharacterCreationExecutionService
import character_creation.service as creation


class BackupStopped(BaseException):
    pass


def tracking_connect(monkeypatch, *, target=None, fail_open=False, fail_backup=False):
    original = sqlite3.connect
    opened = []

    class Tracked(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            return super().close()

        def backup(self, *args, **kwargs):
            if fail_backup:
                raise BackupStopped("interrupted backup")
            return super().backup(*args, **kwargs)

    def connect(database, *args, **kwargs):
        if fail_open and Path(database) == target:
            raise sqlite3.OperationalError("destination unavailable")
        conn = original(database, *args, **kwargs, factory=Tracked)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    return opened, original


@pytest.mark.parametrize("mode", ["reflink", "fallback", "backup_interruption", "destination_failure"])
def test_creation_snapshot_closes_every_acquired_connection(tmp_path, monkeypatch, mode):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "copy.sqlite3"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE proof(value TEXT)")
        conn.execute("INSERT INTO proof VALUES ('snapshot input')")
        conn.commit()
    # A successful copy stands in for the platform-specific ioctl only. The
    # SQLite source, lock scope and fallback backup are actual connections.
    def reflink(src, dst):
        if mode == "reflink":
            shutil.copyfile(src, dst)
            return True
        return False

    monkeypatch.setattr(creation, "_reflink_file", reflink)
    opened, original = tracking_connect(
        monkeypatch, target=target,
        fail_open=mode == "destination_failure", fail_backup=mode == "backup_interruption",
    )
    try:
        if mode in {"backup_interruption", "destination_failure"}:
            error = BackupStopped if mode == "backup_interruption" else sqlite3.OperationalError
            with pytest.raises(error):
                CharacterCreationExecutionService._backup_database(None, source, target)
        else:
            CharacterCreationExecutionService._backup_database(None, source, target)
            with closing(original(target)) as copied:
                assert copied.execute("SELECT value FROM proof").fetchall() == [("snapshot input",)]
        assert len(opened) == (1 if mode in {"reflink", "destination_failure"} else 2)
        assert all(conn.closed for conn in opened)
    finally:
        for conn in opened:
            conn.close()


@pytest.mark.parametrize("failure", ["destination_open", "backup_interruption"])
def test_migration_backup_failure_closes_handles_before_retry(tmp_path, monkeypatch, failure):
    root = tmp_path / "app"
    migrations = root / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_probe.sql").write_text("CREATE TABLE migrated(value TEXT);", encoding="utf-8")
    db = Database(Settings.from_env(root, tmp_path / "data"))
    with closing(sqlite3.connect(db.settings.db_path)) as conn:
        conn.execute("CREATE TABLE existing(value TEXT)")
    opened, original = tracking_connect(monkeypatch, fail_backup=failure == "backup_interruption")
    tracking = sqlite3.connect

    def fail_destination(database, *args, **kwargs):
        if failure == "destination_open" and Path(database).parent == db.settings.backups_dir:
            raise sqlite3.OperationalError("destination unavailable")
        return tracking(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fail_destination)
    try:
        error = BackupStopped if failure == "backup_interruption" else sqlite3.OperationalError
        with pytest.raises(error):
            db.migrate()
        assert len(opened) >= 3  # normal migration handles plus raw backup source
        assert all(conn.closed for conn in opened)
        monkeypatch.setattr(sqlite3, "connect", original)
        db.migrate()
        with db.connection() as conn:
            assert conn.execute("SELECT name FROM sqlite_schema WHERE name='migrated'").fetchone()
    finally:
        for conn in opened:
            conn.close()
