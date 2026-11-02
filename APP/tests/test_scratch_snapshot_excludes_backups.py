"""Scratch and precommit snapshots must not stage the pre-migration backups.

On 2026-09-04 the owner's live data root held a 4.6 GB ``backups/`` directory
next to a 2.1 GB database.  ``_snapshot_data`` copied both into the service's
RAM-backed /tmp for every scratch compile, and the clean-import proof copied
the scratch again, so a single compile could stage more than 13 GB inside a
12 GB memory cgroup.  These tests pin the exclusion and prove restore leaves
the live backups untouched while the post-restore tree comparison ignores it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from character_creation.service import CharacterCreationExecutionService as Service


def _settings(data: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=data,
        db_path=data / "foundry.sqlite3",
        backups_dir=data / "backups",
        security_dir=data / "security",
    )


def _live_root(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    (data / "backups" / "pre_migration_001.sqlite3").write_bytes(b"x" * 1024)
    (data / "exports").mkdir()
    (data / "exports" / "kept.txt").write_text("kept", encoding="utf-8")
    with sqlite3.connect(data / "foundry.sqlite3") as conn:
        conn.execute("CREATE TABLE t(v)")
        conn.execute("INSERT INTO t VALUES (1)")
    return data


def test_snapshot_skips_backups_and_restore_leaves_live_backups_alone(tmp_path: Path) -> None:
    data = _live_root(tmp_path)
    # Use the real restore helpers, including quarantine cleanup and database replacement.
    fake = object.__new__(Service)
    fake.db = SimpleNamespace(settings=_settings(data))

    snapshot = tmp_path / "snap"
    before = Service._snapshot_data(fake, snapshot)
    assert not (snapshot / "backups").exists()
    assert (snapshot / "exports" / "kept.txt").is_file()
    assert (snapshot / "foundry.sqlite3").is_file()
    assert all(not key.startswith("backups/") for key in before)

    # Mutate live, then restore: exports come back, backups are untouched.
    (data / "exports" / "kept.txt").write_text("changed", encoding="utf-8")
    (data / "backups" / "pre_migration_002.sqlite3").write_bytes(b"y")
    with sqlite3.connect(data / "foundry.sqlite3") as conn:
        conn.execute("UPDATE t SET v=2")
    Service._restore_data(fake, snapshot)
    assert (data / "exports" / "kept.txt").read_text(encoding="utf-8") == "kept"
    assert (data / "backups" / "pre_migration_001.sqlite3").is_file()
    assert (data / "backups" / "pre_migration_002.sqlite3").is_file()
    with sqlite3.connect(data / "foundry.sqlite3") as conn:
        assert conn.execute("SELECT v FROM t").fetchall() == [(1,)]
    after = Service._tree_hashes(data, fake._snapshot_excluded_names())
    assert after == before


def test_external_backups_dir_is_not_excluded_by_name(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    settings = _settings(data)
    settings.backups_dir = tmp_path / "elsewhere"
    fake = SimpleNamespace(db=SimpleNamespace(settings=settings))
    assert Service._snapshot_excluded_names(fake) == frozenset()


def test_snapshot_without_tree_hash_copies_everything_but_skips_hashing(tmp_path: Path) -> None:
    data = _live_root(tmp_path)
    fake = SimpleNamespace(db=SimpleNamespace(settings=_settings(data)))
    fake._backup_database = lambda source, target: Service._backup_database(fake, source, target)
    fake._snapshot_excluded_names = lambda: Service._snapshot_excluded_names(fake)

    def _never_hash(*_args, **_kwargs):
        raise AssertionError("scratch snapshot must not hash the copied tree")

    fake._tree_hashes = _never_hash
    snapshot = tmp_path / "snap"
    assert Service._snapshot_data(fake, snapshot, hash_tree=False) == {}
    assert not (snapshot / "backups").exists()
    assert (snapshot / "exports" / "kept.txt").read_text(encoding="utf-8") == "kept"
    with sqlite3.connect(snapshot / "foundry.sqlite3") as conn:
        assert conn.execute("SELECT v FROM t").fetchall() == [(1,)]
