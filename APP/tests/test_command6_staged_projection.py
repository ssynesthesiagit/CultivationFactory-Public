"""Command 6 consumes staged projection bytes without publishing database paths."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app.core import sha256_file
from character_sheet.service import CharacterSheetService
from factory_authoring.command5_profile import CHARACTER_GM_PROFILE, CharacterGMCommand5Profile
from portable_character.service import PortableCharacterPackageService
from projector.service import ProjectionService
from projector.verification import ProjectionVerifier
from project_store.service import ProjectStore


def test_command6_packages_staged_projection_before_publication(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    live = tmp_path / "live"
    name = "Character_Master_Ledger.json"
    relative = Path("projects/p/projections/v1/generated") / name
    staged = stage / relative
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"staged ledger")
    published = live / relative
    assert not published.exists()

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE projection_runs (
            projection_id TEXT, project_id TEXT, project_revision INTEGER,
            content_lock_hash TEXT, event_head_hash TEXT, status TEXT,
            command5_status TEXT, command6_status TEXT, diagnostics_json TEXT,
            created_at TEXT
        );
        CREATE TABLE projection_artifacts (
            projection_id TEXT, artifact_name TEXT, path TEXT, sha256 TEXT,
            bytes INTEGER, media_type TEXT
        );
        INSERT INTO projection_runs VALUES ('v1','p',1,'lock','head','READY',
                                             'NOT_RUN','NOT_RUN','[]','now');
    """)
    conn.execute("INSERT INTO projection_artifacts VALUES (?,?,?,?,?,?)",
                 ("v1", name, str(published), sha256_file(staged), staged.stat().st_size, "application/json"))

    class DB:
        settings = SimpleNamespace(data_dir=stage, exports_dir=tmp_path)

        @contextmanager
        def connection(self):
            yield conn

    db = DB()
    projection = object.__new__(ProjectionService)
    projection.db = db
    projection.projects = SimpleNamespace(get_project=lambda _: {})
    verifier = object.__new__(ProjectionVerifier)
    verifier.db = db
    verifier.factory_root = tmp_path
    verifier.gm_screen_root = tmp_path
    verifier.projections = projection

    candidate = tmp_path / "candidate.zip"
    candidate.write_bytes(b"candidate")
    sheet = tmp_path / "sheet.json"
    sheet.write_bytes(b"sheet")
    monkeypatch.setattr(CharacterGMCommand5Profile, "select_profile",
                        lambda self, profile: ({"profile_id": CHARACTER_GM_PROFILE}, "profile-hash"))
    monkeypatch.setattr(ProjectStore, "export_project",
                        lambda self, project_id, filename: (tmp_path / filename).write_bytes(b"export"))
    monkeypatch.setattr(PortableCharacterPackageService, "canonicalize_project_export",
                        lambda source, target: target.write_bytes(source.read_bytes()))
    monkeypatch.setattr(CharacterSheetService, "sheet",
                        lambda self, project_id: {"sheet_artifact": {"path": str(sheet)}})

    class PackageHandoffReached(Exception):
        pass

    def build(**kwargs):
        assert kwargs["projection_artifacts"] == {name: staged.resolve()}
        assert kwargs["projection_artifacts"][name].read_bytes() == b"staged ledger"
        assert kwargs["owner_sheet_path"].read_bytes() == b"sheet"
        raise PackageHandoffReached

    monkeypatch.setattr(PortableCharacterPackageService, "build", build)
    with pytest.raises(PackageHandoffReached):
        verifier.command6(
            "p", command5_report={"status": "GM_MODEL_CANDIDATE_READY",
                                   "candidate_zip": str(candidate), "candidate_sha256": sha256_file(candidate)},
            workspace=tmp_path, output_dir=tmp_path / "output", build_profile=CHARACTER_GM_PROFILE,
        )
    assert conn.execute("SELECT path FROM projection_artifacts").fetchone()[0] == str(published)
    assert not published.exists()
    conn.close()
