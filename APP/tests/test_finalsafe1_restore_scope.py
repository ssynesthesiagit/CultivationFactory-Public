"""A failed finalize must roll back finalize-owned state only (FINALSAFE1).

Match and table stores are written by play and table code, not by finalize, so
a rollback must keep them byte-identical.  Character, project, and database
state stays part of the precommit restore.  Synthetic data root, no vendor.
"""

import shutil
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from character_creation.service import CharacterCreationExecutionService


def _service(data: Path):
    service = object.__new__(CharacterCreationExecutionService)
    service.db = SimpleNamespace(settings=SimpleNamespace(
        data_dir=data, db_path=data / "foundry.sqlite3", backups_dir=data / "backups",
    ))
    return service


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _data_root(root: Path, marker: str) -> Path:
    (root / "security").mkdir(parents=True)
    (root / "security" / "key.bin").write_bytes(b"key-" + marker.encode())
    locked = root / "factory_final_character" / "project" / "snapshots" / "command4"
    locked.mkdir(parents=True)
    (locked / "Workspace_Manifest.json").write_text(marker)
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)  # The Factory seals snapshots read-only.
    (root / "projects").mkdir()
    (root / "projects" / "p.json").write_text(marker)
    (root / "portable_characters" / "p").mkdir(parents=True)
    (root / "portable_characters" / "p" / "current.zip").write_bytes(b"zip-" + marker.encode())
    (root / "tabletop_auto_tokens").mkdir()
    (root / "tabletop_auto_tokens" / "p.json").write_text(marker)
    (root / "Combat" / "Matches" / "m1").mkdir(parents=True)
    (root / "Combat" / "Matches" / "m1" / "match.json").write_text(marker)
    (root / "tabletop_buttons").mkdir()
    (root / "tabletop_buttons" / "p.json").write_text(marker)
    (root / "foundry.sqlite3").write_bytes(b"db-" + marker.encode())
    return root


def _unlock(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)


def _edit_match_and_table_after_snapshot(live: Path) -> dict[str, bytes]:
    """Simulate match/table writes that land while finalize runs."""
    (live / "Combat" / "Matches" / "m1" / "match.json").write_text("match-edited-during-finalize")
    (live / "Combat" / "Matches" / "m1" / "turn.json").write_text("new-turn")
    (live / "tabletop_buttons" / "p.json").write_text("button-moved-during-finalize")
    (live / "tabletop_buttons" / "q.json").write_text("new-button")
    return {
        "Combat/Matches/m1/match.json": b"match-edited-during-finalize",
        "Combat/Matches/m1/turn.json": b"new-turn",
        "tabletop_buttons/p.json": b"button-moved-during-finalize",
        "tabletop_buttons/q.json": b"new-button",
    }


def test_match_and_table_edits_survive_a_forced_failed_restore(tmp_path, monkeypatch):
    live = _data_root(tmp_path / "live", "base")
    snapshot = _data_root(tmp_path / "snap", "base")
    try:
        edited = _edit_match_and_table_after_snapshot(live)
        before = _tree(live)
        real_copytree = shutil.copytree

        def failing_copytree(src, dst, *args, **kwargs):
            if Path(src).name == "projects":
                raise OSError("disk full")
            return real_copytree(src, dst, *args, **kwargs)

        monkeypatch.setattr(shutil, "copytree", failing_copytree)
        with pytest.raises(OSError):
            _service(live)._restore_data(snapshot)
        assert _tree(live) == before
        for rel, data in edited.items():
            assert (live / rel).read_bytes() == data
    finally:
        _unlock(tmp_path)


def test_character_project_and_database_state_is_still_rolled_back(tmp_path):
    live = _data_root(tmp_path / "live", "base")
    snapshot = _data_root(tmp_path / "snap", "base")
    try:
        (live / "projects" / "p.json").write_text("project-written-by-finalize")
        (live / "portable_characters" / "p" / "current.zip").write_bytes(b"zip-finalize")
        (live / "tabletop_auto_tokens" / "p.json").write_text("auto-token-status")
        (live / "foundry.sqlite3").write_bytes(b"db-finalize")
        _edit_match_and_table_after_snapshot(live)

        _service(live)._restore_data(snapshot)

        assert (live / "projects" / "p.json").read_text() == "base"
        assert (live / "portable_characters" / "p" / "current.zip").read_bytes() == b"zip-base"
        assert (live / "tabletop_auto_tokens" / "p.json").read_text() == "base"
        assert (live / "foundry.sqlite3").read_bytes() == b"db-base"
    finally:
        _unlock(tmp_path)


def test_successful_restore_leaves_no_quarantine_and_changes_nothing_else(tmp_path):
    live = _data_root(tmp_path / "live", "base")
    snapshot = _data_root(tmp_path / "snap", "base")
    try:
        edited = _edit_match_and_table_after_snapshot(live)
        before_preserved = {
            rel: data for rel, data in _tree(live).items()
            if rel.split("/")[0] in {"Combat", "tabletop_buttons"}
        }
        snapshot_tree = _tree(snapshot)

        _service(live)._restore_data(snapshot)

        after = _tree(live)
        # Preserved stores keep their post-edit bytes; the rest matches the snapshot.
        for rel, data in before_preserved.items():
            assert after[rel] == data
        for rel, data in edited.items():
            assert after[rel] == data
        expected_other = {
            rel: data for rel, data in snapshot_tree.items()
            if rel.split("/")[0] not in {"Combat", "tabletop_buttons"}
        }
        assert {rel: data for rel, data in after.items() if rel.split("/")[0] not in {"Combat", "tabletop_buttons"}} == expected_other
        # Quarantine is removed, and nothing extra appears beside the data root.
        assert not list(tmp_path.glob(".live-restore-quarantine-*"))
        assert sorted(p.name for p in tmp_path.iterdir()) == ["live", "snap"]
    finally:
        _unlock(tmp_path)
