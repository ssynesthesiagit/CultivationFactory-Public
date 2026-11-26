from pathlib import Path

from app.core import Database, Settings
from character_creation.finalization import publication_lock, publication_root, recover


ROOT = Path(__file__).resolve().parents[1]


def test_recover_does_not_decode_finalized_history(tmp_path):
    db = Database(Settings.from_env(ROOT, tmp_path / "data"))
    with db.connection() as conn:
        conn.execute("CREATE TABLE character_creation_runs (run_id TEXT, status TEXT, commit_json TEXT)")
        conn.execute("INSERT INTO character_creation_runs VALUES ('done', 'CLEAN_AND_FINALIZED', 'not json')")
    with publication_lock(db):
        leftover = publication_root(db) / "leftover"
        leftover.mkdir()
        (leftover / "file").write_text("stale")
        recover(db)
        assert not leftover.exists()


def test_completed_migrate_does_not_count_legacy_rows(tmp_path, monkeypatch):
    db = Database(Settings.from_env(ROOT, tmp_path / "data"))
    db.migrate()
    statements = []
    connect = db.connect

    def traced_connect():
        conn = connect()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(db, "connect", traced_connect)
    db.migrate()
    assert statements
    assert not any("contract_status NOT IN" in sql for sql in statements)
