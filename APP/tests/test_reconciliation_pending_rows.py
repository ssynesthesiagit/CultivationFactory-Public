"""Completed quarantine is not pending work; interrupted reconciliation still is.

These tests use the real migration service, schema registry and SQLite
transactions over a small database with the first two repository migrations.
"""
from pathlib import Path
import shutil

import pytest

from app.core import Database, Settings
from contracts.registry import SchemaRegistry
from migration import service


APP_ROOT = Path(__file__).resolve().parents[1]


def _legacy_database(tmp_path):
    root = tmp_path / "application"
    (root / "migrations").mkdir(parents=True)
    (root / "schemas").mkdir()
    for filename in SchemaRegistry.VERSION_TO_FILE.values():
        shutil.copyfile(APP_ROOT / "schemas" / filename, root / "schemas" / filename)
    shutil.copyfile(
        APP_ROOT / "migrations" / "001_initial.sql",
        root / "migrations" / "001_initial.sql",
    )
    db = Database(Settings.from_env(root, tmp_path / "data"))
    db.migrate()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,"
            "authority,manifest_json,installed_at) VALUES(?,?,?,?,?,?,?)",
            ("test.pack", "1", "hash", "installed", "core", "{}", "now"),
        )
        conn.execute(
            "INSERT INTO catalog_records(record_id,content_type,display_name,"
            "pack_id,pack_version,authority,publication_state,source_path,"
            "source_anchor,source_hash,record_hash,data_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("test.invalid", "talent", "Unresolved legacy row", "test.pack", "1",
             "core", "published", "test", "test", "source", "record", "{}"),
        )
    shutil.copyfile(
        APP_ROOT / "migrations" / "002_runtime_contract_reconciliation.sql",
        root / "migrations" / "002_runtime_contract_reconciliation.sql",
    )
    return db


def _snapshot(db):
    with db.connection() as conn:
        return {
            "status": conn.execute("SELECT contract_status FROM catalog_records").fetchone()[0],
            "quarantine": conn.execute("SELECT COUNT(*) FROM contract_quarantine").fetchone()[0],
            "runs": conn.execute("SELECT COUNT(*) FROM contract_migration_runs").fetchone()[0],
            "applied": conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
        }


def test_processed_quarantine_does_not_repeat_on_three_startups(tmp_path):
    db = _legacy_database(tmp_path)
    for _ in range(3):
        db.migrate()
        assert _snapshot(db) == {
            "status": "quarantined", "quarantine": 1, "runs": 1, "applied": 2,
        }


def test_interrupted_real_reconciliation_rolls_back_and_retries(tmp_path, monkeypatch):
    db = _legacy_database(tmp_path)
    original = service._canonicalize_catalog
    attempts = []

    def interrupt_after_catalog(*args):
        original(*args)
        attempts.append(None)
        if len(attempts) == 1:
            raise RuntimeError("interrupted after catalog reconciliation")

    monkeypatch.setattr(service, "_canonicalize_catalog", interrupt_after_catalog)
    with pytest.raises(RuntimeError, match="interrupted after catalog reconciliation"):
        db.migrate()
    assert _snapshot(db) == {
        "status": "legacy-unverified", "quarantine": 0, "runs": 0, "applied": 2,
    }
    db.migrate()
    assert len(attempts) == 2
    assert _snapshot(db) == {
        "status": "quarantined", "quarantine": 1, "runs": 1, "applied": 2,
    }
    db.migrate()
    assert len(attempts) == 2
    assert _snapshot(db) == {
        "status": "quarantined", "quarantine": 1, "runs": 1, "applied": 2,
    }
