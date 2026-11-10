"""A previously published projection can be sealed from a staging workspace."""
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace

from app.core import sha256_file
from character_creation.candidate_gm import CandidateGMCapsuleStore, _REQUIRED_PROJECTION_ARTIFACTS


def test_candidate_snapshot_uses_staged_copy_when_live_artifacts_exist(tmp_path):
    stage = tmp_path / "stage"
    live = tmp_path / "live"
    relative = "projects/p/projections/v1/generated"
    staged_dir = stage / relative
    live_dir = live / relative
    staged_dir.mkdir(parents=True)
    live_dir.mkdir(parents=True)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE projection_runs (
            project_id TEXT, projection_id TEXT, status TEXT, project_revision INTEGER,
            event_head_hash TEXT, content_lock_hash TEXT
        );
        CREATE TABLE projection_artifacts (
            projection_id TEXT, artifact_name TEXT, path TEXT, sha256 TEXT,
            bytes INTEGER, media_type TEXT
        );
        INSERT INTO projection_runs VALUES ('p', 'v1', 'READY', 1, 'head', 'lock');
    """)
    expected = {}
    for name in _REQUIRED_PROJECTION_ARTIFACTS:
        staged = staged_dir / name
        staged.write_bytes(b'{"workspace":true}')
        published = live_dir / name
        published.write_bytes(b'{"workspace":false}')
        expected[name] = staged.read_bytes()
        conn.execute("INSERT INTO projection_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                     ("v1", name, str(published), sha256_file(staged),
                      staged.stat().st_size, "application/json"))

    class DB:
        settings = SimpleNamespace(data_dir=stage)

        @contextmanager
        def connection(self):
            yield conn

    store = object.__new__(CandidateGMCapsuleStore)
    identity, artifacts = store._projection_snapshot(
        DB(), "p", {"projection_id": "v1", "project_revision": 1}
    )
    assert artifacts == expected
    assert identity["projection_id"] == "v1"
    assert all((live_dir / name).read_bytes() == b'{"workspace":false}' for name in expected)
    conn.close()
