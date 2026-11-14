"""Precommit copies exactly the existing rollback scope, using synthetic data."""
from contextlib import closing
import sqlite3
from types import SimpleNamespace

from character_creation.service import CharacterCreationExecutionService


def test_precommit_omits_preserved_stores_without_changing_restore(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    service = object.__new__(CharacterCreationExecutionService)
    service.db = SimpleNamespace(settings=SimpleNamespace(
        data_dir=live, db_path=live / "foundry.sqlite3", backups_dir=live / "backups",
    ))
    preserved = service._restore_preserved_names()
    store_files = []
    for name in preserved:
        path = live / name
        if "." not in name:
            path.mkdir()
            path = path / "state.json"
        path.write_text("before")
        store_files.append(path)
    (live / "projects").mkdir()
    owned = live / "projects" / "state.json"
    owned.write_text("approved-before")
    (live / "backups").mkdir()
    (live / "backups" / "unrelated.bak").write_bytes(b"keep")
    with closing(sqlite3.connect(service.db.settings.db_path)) as conn:
        conn.execute("CREATE TABLE example (value TEXT)")
        conn.execute("INSERT INTO example VALUES ('before')")
        conn.commit()

    full = tmp_path / "scratch-input"
    lean = tmp_path / "precommit"
    service._snapshot_data(full, hash_tree=False)
    service._snapshot_data(lean, hash_tree=False, exclude=preserved)

    assert all((full / name).exists() for name in preserved)
    assert not any((lean / name).exists() for name in preserved)
    assert not (full / "backups").exists()
    assert not (lean / "backups").exists()
    assert service._tree_hashes(full, preserved) == service._tree_hashes(lean)

    for path in store_files:
        path.write_text("changed-during-finalize")
    owned.write_text("unapproved-live-output")
    with closing(sqlite3.connect(service.db.settings.db_path)) as conn:
        conn.execute("INSERT INTO example VALUES ('unapproved')")
        conn.commit()

    service._restore_data(lean)

    assert all(path.read_text() == "changed-during-finalize" for path in store_files)
    assert owned.read_text() == "approved-before"
    assert (live / "backups" / "unrelated.bak").read_bytes() == b"keep"
    with closing(sqlite3.connect(service.db.settings.db_path)) as conn:
        assert conn.execute("SELECT value FROM example").fetchall() == [("before",)]
    excluded = service._snapshot_excluded_names() | preserved
    assert service._tree_hashes(live, excluded) == service._tree_hashes(lean)
