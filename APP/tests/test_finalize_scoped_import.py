"""A fresh import proof must not inherit unrelated live character or combat data."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from character_creation.production_release import CharacterProductionReleaseAdapter


def _write(root: Path, relative: str, contents: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)


def test_clean_import_keeps_current_authoring_and_reconstructs_character_state(tmp_path):
    source = tmp_path / "live"
    target = tmp_path / "proof"
    target.mkdir()
    retained = {
        "vendor/factory_adapter.json": b'{"authenticated":true}',
        "vendor/packages/pinned.zip": b"pinned factory archive",
        "security/integrity-key": b"synthetic test key",
        "content_packs/pinned/pack.json": b"retained content",
        "factory_candidates/character/current.json": b"current candidate evidence",
        "factory_workspaces/character/current.json": b"current workspace evidence",
        "factory_gm_authoring/character/receipts/current.json": b"current GM evidence",
        "factory_gm_authoring/character/artifacts/model.json": b"relative GM artifact",
    }
    unrelated = {
        "Combat/Matches/other/state.json": b"live combat",
        "logs/prior-build/large-history.bin": b"historical logs",
        "exports/prior-character.zip": b"prior export",
        "projects/character/project.json": b"must come from the portable package",
        "character_sheets/character/current.json": b"must be rebuilt",
        "portable_characters/character/current.zip": b"must be freshly imported",
        "portable_characters/other/current.zip": b"another installed character",
        "factory_candidates/other/current.json": b"other candidate",
        "factory_workspaces/other/current.json": b"other workspace",
        "factory_gm_authoring/other/receipts/current.json": b"other GM evidence",
        "foundry.sqlite3": b"must create an empty database",
        "foundry.sqlite3-wal": b"must not carry live transactions",
        "backups/old.sqlite3": b"historical database",
    }
    for path, contents in {**retained, **unrelated}.items():
        _write(source, path, contents)
    adapter = object.__new__(CharacterProductionReleaseAdapter)
    adapter.db = SimpleNamespace(settings=SimpleNamespace(data_dir=source))

    adapter._stage_clean_import_inputs("character", target)

    for path, contents in retained.items():
        assert (target / path).read_bytes() == contents
    assert all(not (target / path).exists() for path in unrelated)
    # The proof owns independent copies, including its authoring context.
    (target / "factory_candidates/character/current.json").write_bytes(b"proof changes")
    for path, contents in {**retained, **unrelated}.items():
        assert (source / path).read_bytes() == contents


def test_clean_import_rejects_a_project_path_outside_its_scope(tmp_path):
    adapter = object.__new__(CharacterProductionReleaseAdapter)
    adapter.db = SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path / "live"))
    with pytest.raises(FoundryError) as error:
        adapter._stage_clean_import_inputs("../other", tmp_path / "proof")
    assert error.value.code == "UNSAFE_FILENAME"
    assert not (tmp_path / "proof").exists()
