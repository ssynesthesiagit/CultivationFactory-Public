"""Real SQLite regressions for migration retry and WAL-safe recovery.

Removing these checks lets an interrupted row reconciliation become permanent,
or lets a successful restore retain newer WAL pages and lose the recovery copy.
The original core.py fails the retry and WAL cases (negative control).
"""
from __future__ import annotations

from contextlib import closing
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core import Database, FoundryError, Settings


def _database(tmp_path: Path) -> Database:
    root = tmp_path / "application"
    (root / "migrations").mkdir(parents=True)
    (root / "migrations" / "001.sql").write_text(
        "CREATE TABLE payload(value TEXT);\nINSERT INTO payload VALUES('before');\n",
        encoding="utf-8",
    )
    return Database(Settings.from_env(root, tmp_path / "data"))


def test_restart_retries_row_reconciliation_after_schema_committed(tmp_path):
    db = _database(tmp_path)
    module = types.ModuleType("migration.service")
    attempts = []

    def reconcile(database):
        attempts.append(database)
        if len(attempts) == 1:
            raise RuntimeError("interrupted row reconciliation")
        with database.connection() as conn:
            conn.execute("UPDATE payload SET value='reconciled'")

    module.reconcile_database = reconcile
    with patch.dict(sys.modules, {"migration.service": module}):
        with pytest.raises(RuntimeError, match="interrupted row reconciliation"):
            db.migrate()
        db.migrate()
    assert len(attempts) == 2
    with db.connection() as conn:
        assert [row[0] for row in conn.execute("SELECT value FROM payload")] == ["reconciled"]
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_current_schema_skips_ddl_but_preserves_reconciliation(tmp_path):
    db = _database(tmp_path)
    module = types.ModuleType("migration.service")
    module.reconcile_database = lambda database: None
    with patch.dict(sys.modules, {"migration.service": module}):
        db.migrate()
        with patch.object(module, "reconcile_database") as reconcile:
            db.migrate()
            reconcile.assert_called_once_with(db)
    with db.connection() as conn:
        assert [row[0] for row in conn.execute("SELECT value FROM payload")] == ["before"]


def _record_restore(db: Database, backup: Path, conn) -> None:
    conn.execute(
        "INSERT INTO schema_migration_journal(version,script_sha256,status,"
        "next_statement_index,statement_count,backup_path,started_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("recovery.sql", "hash", "failed", 0, 1, str(backup), "now", "now"),
    )


@pytest.mark.parametrize("keep_connection_open", [False, True])
def test_restore_uses_complete_sqlite_snapshots(tmp_path, keep_connection_open):
    db = _database(tmp_path)
    with db.connection() as conn:
        db._ensure_migration_journal(conn)
        conn.execute("CREATE TABLE payload(value TEXT)")
        conn.execute("INSERT INTO payload VALUES('before')")
    backup = db.settings.backups_dir / "recorded snapshot.sqlite3"
    with db.connection() as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    keeper = db.connect()
    try:
        _record_restore(db, backup, keeper)
        keeper.execute("INSERT INTO payload VALUES('after')")
        if not keep_connection_open:
            keeper.close()
        assert db.restore_migration_backup("recovery.sql") == backup
        with db.connection() as conn:
            assert [row[0] for row in conn.execute("SELECT value FROM payload")] == ["before"]
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        if keep_connection_open:
            assert [row[0] for row in keeper.execute("SELECT value FROM payload")] == ["before"]
        retained_files = list(db.settings.backups_dir.glob("failed_before_restore_*.sqlite3"))
        assert len(retained_files) == 1
        with closing(sqlite3.connect(retained_files[0])) as retained:
            assert [row[0] for row in retained.execute("SELECT value FROM payload")] == ["before", "after"]
            assert retained.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        keeper.close()


def test_missing_backup_leaves_database_untouched(tmp_path):
    db = _database(tmp_path)
    with db.connection() as conn:
        db._ensure_migration_journal(conn)
        conn.execute("CREATE TABLE payload(value TEXT)")
        conn.execute("INSERT INTO payload VALUES('before')")
        _record_restore(db, tmp_path / "missing.sqlite3", conn)
    with pytest.raises(FoundryError) as error:
        db.restore_migration_backup("recovery.sql")
    assert error.value.code == "MIGRATION_BACKUP_NOT_FOUND"
    with db.connection() as conn:
        assert [row[0] for row in conn.execute("SELECT value FROM payload")] == ["before"]
    assert not list(db.settings.backups_dir.glob("failed_before_restore_*.sqlite3"))


@pytest.mark.parametrize("contents", ["empty_file", "empty_database", "unrelated_database", "corrupt"])
def test_invalid_backup_cannot_replace_the_database(tmp_path, contents):
    db = _database(tmp_path)
    backup = db.settings.backups_dir / "invalid.sqlite3"
    if contents == "empty_file":
        backup.touch()
    elif contents == "corrupt":
        backup.write_bytes(b"not a SQLite database")
    else:
        with closing(sqlite3.connect(backup)) as source:
            source.execute("VACUUM")
            if contents == "unrelated_database":
                source.execute("CREATE TABLE unrelated(value TEXT)")
                source.commit()
    with db.connection() as conn:
        db._ensure_migration_journal(conn)
        conn.execute("CREATE TABLE payload(value TEXT)")
        conn.execute("INSERT INTO payload VALUES('before')")
        _record_restore(db, backup, conn)
    with pytest.raises(FoundryError) as error:
        db.restore_migration_backup("recovery.sql")
    assert error.value.code == "MIGRATION_BACKUP_INVALID"
    with db.connection() as conn:
        assert [row[0] for row in conn.execute("SELECT value FROM payload")] == ["before"]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not list(db.settings.backups_dir.glob("failed_before_restore_*.sqlite3"))
