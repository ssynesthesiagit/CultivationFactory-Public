"""Fresh schemas are atomic; databases with existing state retain recovery."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from app.core import Database, Settings, sha256_text


APP = Path(__file__).resolve().parents[1]


def _database(tmp_path, name, root=APP):
    return Database(Settings.from_env(root, tmp_path / name))


def _schema(db):
    with db.connection() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        )]


def _journals(db):
    with db.connection() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT version,script_sha256,status,next_statement_index,statement_count,error_json "
            "FROM schema_migration_journal ORDER BY version"
        )]


def test_fresh_schema_matches_incremental_migrations_and_reopens(tmp_path, monkeypatch):
    fresh = _database(tmp_path, "fresh")
    incremental = _database(tmp_path, "incremental")
    monkeypatch.setattr(incremental, "_initialize_empty_database", lambda migrations: False)
    incremental.migrate()
    fresh.migrate()
    assert _schema(fresh) == _schema(incremental)
    assert _journals(fresh) == _journals(incremental)
    with fresh.connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM schema_migration_journal WHERE backup_path IS NOT NULL").fetchone()[0] == 0
    assert not list(fresh.settings.backups_dir.iterdir())
    assert list(incremental.settings.backups_dir.iterdir())
    before = _schema(fresh), _journals(fresh)
    Database(fresh.settings).migrate()
    assert (_schema(fresh), _journals(fresh)) == before


def test_failed_fresh_schema_rolls_back_all_statements_and_can_retry(tmp_path):
    root = tmp_path / "app"
    migrations = root / "migrations"
    migrations.mkdir(parents=True)
    first = migrations / "001_initial.sql"
    second = migrations / "002_more.sql"
    first.write_text("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT);\nINSERT INTO sample VALUES(1,'first');\n")
    second.write_text("INSERT INTO missing_table VALUES(2);\n")
    db = _database(tmp_path, "atomic", root)
    with pytest.raises(sqlite3.OperationalError, match="missing_table"):
        db._initialize_empty_database([first, second])
    assert _schema(db) == []
    second.write_text("INSERT INTO sample VALUES(2,'second');\n")
    assert db._initialize_empty_database([first, second])
    with db.connection() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM sample ORDER BY id")] == [(1, "first"), (2, "second")]
    assert _journals(db)[1][1] == sha256_text(second.read_text())


def test_existing_data_uses_incremental_recovery_and_backup(tmp_path):
    root = tmp_path / "app"
    migrations = root / "migrations"
    migrations.mkdir(parents=True)
    path = migrations / "001_upgrade.sql"
    path.write_text("ALTER TABLE owner_state ADD COLUMN extra TEXT;\nINSERT INTO missing_table VALUES(2);\n")
    db = _database(tmp_path, "existing", root)
    with db.transaction() as conn:
        conn.execute("CREATE TABLE owner_state(id INTEGER PRIMARY KEY,value TEXT)")
        conn.execute("INSERT INTO owner_state VALUES(1,'keep this')")
    with pytest.raises(sqlite3.OperationalError, match="missing_table"):
        db.migrate()
    with db.connection() as conn:
        assert tuple(conn.execute("SELECT id,value FROM owner_state").fetchone()) == (1, "keep this")
        journal = conn.execute("SELECT * FROM schema_migration_journal").fetchone()
        assert journal["status"] == "failed"
        assert journal["next_statement_index"] == 1
        backup = Path(journal["backup_path"])
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT id,value FROM owner_state").fetchone() == (1, "keep this")
        assert [row[1] for row in conn.execute("PRAGMA table_info(owner_state)")] == ["id", "value"]


def test_two_fresh_initializers_converge_on_one_complete_schema(tmp_path):
    db = _database(tmp_path, "shared")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(Database(db.settings).migrate) for _ in range(2)]
        for future in futures:
            future.result()
    migrations = sorted((APP / "migrations").glob("*.sql"))
    assert len(_journals(db)) == len(migrations)
    assert all(row[2] == "applied" and row[3] == row[4] for row in _journals(db))


@pytest.mark.parametrize("statement", [
    "PRAGMA user_version=7;",
    "/* transaction control */ COMMIT;",
    "/* a multiline\ncomment */ VACUUM;",
    "\ufeff/* first */ -- second\nBEGIN IMMEDIATE;",
])
def test_connection_control_migration_keeps_incremental_path(tmp_path, statement):
    root = tmp_path / "app"
    root.mkdir()
    path = root / "migration.sql"
    path.write_text("CREATE TABLE must_not_leak(v TEXT);\n" + statement + "\n")
    db = _database(tmp_path, "pragma", root)
    assert not db._initialize_empty_database([path])
    assert _schema(db) == []
