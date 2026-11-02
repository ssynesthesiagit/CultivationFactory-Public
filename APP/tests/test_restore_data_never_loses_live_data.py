"""The finalize rollback must never destroy the live data root (incident 2026-09-24)."""

import os
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
    # The Factory seals final-character snapshots read-only.
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    (root / "projects").mkdir()
    (root / "projects" / "p.json").write_text(marker)
    (root / "foundry.sqlite3").write_bytes(b"db-" + marker.encode())
    return root


def _unlock(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)


def test_restore_replaces_read_only_live_trees_with_the_snapshot(tmp_path):
    live = _data_root(tmp_path / "live", "live")
    snapshot = _data_root(tmp_path / "snap", "snap")
    try:
        _service(live)._restore_data(snapshot)
        assert _tree(live) == _tree(snapshot)
        assert not list(tmp_path.glob(".live-restore-quarantine-*"))
    finally:
        _unlock(tmp_path)


def test_failed_restore_puts_every_live_entry_back(tmp_path, monkeypatch):
    live = _data_root(tmp_path / "live", "live")
    snapshot = _data_root(tmp_path / "snap", "snap")
    try:
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
        assert (live / "security" / "key.bin").read_bytes() == b"key-live"
    finally:
        _unlock(tmp_path)
