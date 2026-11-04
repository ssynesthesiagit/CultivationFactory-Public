"""The clean-import proof installs every exact pack version the project locked.

A fresh install ships only the current pack versions, but a project locks the
versions that were current when it was created.  Those sealed packs are still
installed in the producer, so the clean root receives their rows verbatim and
re-verifies the seal; a lock the producer no longer holds fails closed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings
from catalog.service import BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION
from character_creation.production_release import carry_over_retained_pack_locks
from content_packs.membership import verify_pack_seal
from security.integrity import IntegrityService

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "project.retained-pack-test"


def _databases(catalog_environment, tmp_path: Path) -> tuple[Database, Database]:
    producer_settings = Settings.from_env(ROOT, tmp_path / "producer")
    producer_settings.ensure_dirs()
    producer = Database(producer_settings)
    with catalog_environment["db"].connection() as source, producer.connection() as target:
        source.backup(target)
    clean_settings = Settings.from_env(ROOT, tmp_path / "clean")
    clean_settings.ensure_dirs()
    clean = Database(clean_settings)
    clean.migrate()
    # The real clean import copies the producer's data directory (including
    # its integrity key) before importing; mirror that so seals verify.
    for settings in (producer_settings, clean_settings):
        shutil.rmtree(settings.security_dir, ignore_errors=True)
        shutil.copytree(catalog_environment["settings"].security_dir, settings.security_dir)
    return producer, clean


def _lock(producer: Database, *, pack_hash: str | None = None) -> dict:
    with producer.connection() as conn:
        pack = dict(conn.execute(
            "SELECT pack_id, version, pack_hash FROM content_packs WHERE pack_id=? AND version=?",
            (BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION),
        ).fetchone())
    with producer.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,target_factory_version,
                 target_candidate_schema_version,target_gm_screen_version,quality_target,project_json,
                 compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (PROJECT_ID, "Retained pack test", "draft", 1, "2026-09-13T00:00:00Z", "2026-09-13T00:00:00Z",
             "test", "test", "test", "standard", "{}", "NOT_ATTEMPTED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"),
        )
        conn.execute(
            "INSERT INTO project_content_locks(project_id,pack_id,version,pack_hash,locked_at) VALUES(?,?,?,?,?)",
            (PROJECT_ID, pack["pack_id"], pack["version"], pack_hash or pack["pack_hash"], "2026-09-13T00:00:00Z"),
        )
    return pack


def test_locked_pack_is_carried_verbatim_and_its_seal_verifies(catalog_environment, tmp_path: Path) -> None:
    producer, clean = _databases(catalog_environment, tmp_path)
    pack = _lock(producer)
    with producer.connection() as conn:
        expected = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE pack_id=? AND {column}=?", (pack["pack_id"], pack["version"])).fetchone()[0]
            for table, column in (("catalog_records", "pack_version"), ("content_pack_record_membership", "pack_version"), ("content_pack_install_receipts", "version"))
        }
    carried = carry_over_retained_pack_locks(producer, clean, PROJECT_ID)
    assert [row["version"] for row in carried] == [pack["version"]]
    assert carried[0]["records"] == expected["catalog_records"] > 0
    assert carried[0]["content_pack_record_membership"] == expected["content_pack_record_membership"]
    assert carried[0]["content_pack_install_receipts"] == expected["content_pack_install_receipts"] == 1
    assert carried[0]["dependencies"] > 0 and carried[0]["validations"] == expected["catalog_records"]
    with clean.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM catalog_records WHERE pack_id=? AND pack_version=?", (pack["pack_id"], pack["version"])).fetchone()[0] == expected["catalog_records"]
        assert conn.execute(
            "SELECT COUNT(*) FROM catalog_dependencies d JOIN catalog_records r ON r.row_id=d.source_row_id WHERE r.pack_id=? AND r.pack_version=?",
            (pack["pack_id"], pack["version"]),
        ).fetchone()[0] == carried[0]["dependencies"]
        verify_pack_seal(conn, pack_id=pack["pack_id"], version=pack["version"], expected_pack_hash=pack["pack_hash"], integrity=IntegrityService.for_database(clean))
    # A second proof pass finds the pack installed and copies nothing.
    assert carry_over_retained_pack_locks(producer, clean, PROJECT_ID) == []


def test_lock_the_producer_no_longer_holds_fails_closed(catalog_environment, tmp_path: Path) -> None:
    producer, clean = _databases(catalog_environment, tmp_path)
    _lock(producer, pack_hash="f" * 64)
    with pytest.raises(FoundryError) as error:
        carry_over_retained_pack_locks(producer, clean, PROJECT_ID)
    assert error.value.code == "CG1_CLEAN_IMPORT_PACK_LOCK_UNAVAILABLE"
    with clean.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM content_packs").fetchone()[0] == 0
