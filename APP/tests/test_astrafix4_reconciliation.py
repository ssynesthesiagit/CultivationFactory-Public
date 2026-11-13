from pathlib import Path

import pytest

from app.core import Database, Settings
from migration import service

ROOT = Path(__file__).resolve().parents[1]


def test_reconciliation_retries_after_ddl_and_does_not_repeat_quarantine(tmp_path, monkeypatch):
    db = Database(Settings.from_env(ROOT, tmp_path / "data"))
    db.migrate()
    with db.transaction() as conn:
        conn.execute("INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,manifest_json,installed_at) VALUES('p','1','h','active','test','{}','now')")
        conn.execute("""INSERT INTO catalog_records(record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,source_path,source_anchor,source_hash,record_hash,data_json)
                     VALUES('bad','test','Bad','p','1','test','published','x','x','h','h','{}')""")
    original = service._canonicalize_catalog
    def interrupted(conn, registry, inventory):
        original(conn, registry, inventory)
        raise RuntimeError("interrupted after quarantine")
    monkeypatch.setattr(service, "_canonicalize_catalog", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        db.migrate()
    monkeypatch.setattr(service, "_canonicalize_catalog", original)
    for _ in range(3):
        db.migrate()
    with db.connection() as conn:
        assert conn.execute("SELECT contract_status FROM catalog_records").fetchone()[0] == "quarantined"
        assert conn.execute("SELECT count(*) FROM contract_quarantine").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM contract_migration_runs").fetchone()[0] == 1
