"""Immutable source-byte reuse must still give every caller its own records."""

from copy import deepcopy
import json

import pytest

from app.core import FoundryError, canonical_json
from catalog.service import _normalize_record
from contracts.canonical import canonical_record_hash, normalize_core_catalog_record
from project_store.service import ProjectStore, project_lock_proof_cache_scope
from tests.test_locked_records_by_reference import _insert_locked, _seed_project


def _record(record_id="test.memo.record", content_type="talent"):
    projection = _normalize_record(
        record_id=record_id, content_type=content_type, display_name="Memo 火",
        source_path="synthetic.md", source_hash="a" * 64,
        raw={"nested": ["original", {"value": -0.0}]},
        summary="Synthetic record ownership test", acquisition_channels=["grant-only"],
    )
    return normalize_core_catalog_record(projection, pack_hash="b" * 64)


def _seed(db, record, project_id="project-1"):
    with db.transaction() as conn:
        _seed_project(conn, project_id)
        _insert_locked(conn, project_id, record["record_id"], record["record_hash"], canonical_json(record))


@pytest.mark.parametrize("prefetch", [False, True])
def test_plain_record_cold_and_warm_returns_remain_independent(fresh_db, prefetch):
    expected = _record()
    _seed(fresh_db, expected)
    store = ProjectStore(fresh_db)
    with project_lock_proof_cache_scope(), fresh_db.connection() as conn:
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            ("project-1", expected["record_id"]),
        ).fetchone() if prefetch else None

        def resolve():
            return store._resolve_locked_record_after_proof(
                conn, "project-1", expected["record_id"], prefetched_row=row,
            )

        first = resolve()
        assert first == expected
        first["tags"].append("caller-only")
        first["content_binding"]["pack_hash"] = "changed"
        second = resolve()
        assert second == expected
        second["compatibility"]["factory"]["raw_projection"]["raw_record"]["nested"].append("second caller")
        third = resolve()
        assert third == expected
        assert third is not second and third is not first


def test_transformed_projection_keeps_types_and_separates_versions(fresh_db, monkeypatch):
    source = _record("test.foundation", "foundation")
    _seed(fresh_db, source)
    store = ProjectStore(fresh_db)
    calls = []
    projected = {"display_name": "Typed projection", "retained_tuple": (1, {"values": [2]})}

    def project(conn, project_id, record_id, *, authority_service=None, version=None):
        calls.append(version)
        return {**deepcopy(projected), "version": version}

    monkeypatch.setattr(store, "_resolve_project_locked_foundation_after_proof", project)
    with project_lock_proof_cache_scope(), fresh_db.connection() as conn:
        def resolve(version):
            return store._resolve_locked_record_after_proof(
                conn, "project-1", source["record_id"], foundation_version=version,
            )

        first = resolve("v1")
        first["retained_tuple"][1]["values"].append("caller-only")
        second = resolve("v1")
        assert isinstance(second["retained_tuple"], tuple)
        assert second == {**projected, "version": "v1"}
        assert resolve("v2") == {**projected, "version": "v2"}
        assert calls == ["v1", "v2"]


def test_record_memo_is_project_scoped_and_ends_with_the_operation(fresh_db):
    first = _record()
    second = deepcopy(first)
    second["display_name"] = "A different project's record"
    second["record_hash"] = canonical_record_hash(second)
    _seed(fresh_db, first, "project-a")
    _seed(fresh_db, second, "project-b")
    store = ProjectStore(fresh_db)
    with project_lock_proof_cache_scope(), fresh_db.connection() as conn:
        for project_id, expected in [("project-a", first), ("project-b", second), ("project-a", first)]:
            assert store._resolve_locked_record_after_proof(conn, project_id, first["record_id"]) == expected

    # Deliberate out-of-band corruption in the disposable database must be
    # inspected again after the operation finishes; no process-wide trust cache.
    with fresh_db.transaction() as conn:
        conn.execute("UPDATE locked_record_blobs SET record_json=? WHERE record_hash=?",
                     (json.dumps(first, indent=2), first["record_hash"]))
    with project_lock_proof_cache_scope(), fresh_db.connection() as conn:
        with pytest.raises(FoundryError) as error:
            store._resolve_locked_record_after_proof(conn, "project-a", first["record_id"])
        assert error.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"


def test_malformed_or_invalid_plain_records_are_not_memoized(fresh_db):
    record = _record()
    record["display_name"] = 17
    record["record_hash"] = canonical_record_hash(record)
    _seed(fresh_db, record)
    store = ProjectStore(fresh_db)
    with project_lock_proof_cache_scope(), fresh_db.connection() as conn:
        for _ in range(2):
            with pytest.raises(FoundryError) as error:
                store._resolve_locked_record_after_proof(conn, "project-1", record["record_id"])
            assert error.value.code == "CANONICAL_SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize("prefetch", [False, True])
def test_same_hash_reinsert_cannot_hide_changed_bytes_in_an_active_scope(fresh_db, prefetch):
    record = _record()
    _seed(fresh_db, record)
    store = ProjectStore(fresh_db)
    with project_lock_proof_cache_scope(), fresh_db.transaction() as conn:
        assert store._resolve_locked_record_after_proof(conn, "project-1", record["record_id"]) == record
        # Migration 030 stores a same-hash reinsert's mismatched bytes as an
        # override. It must not be mistaken for the earlier verified input.
        _insert_locked(conn, "project-1", record["record_id"], record["record_hash"], json.dumps(record, indent=2))
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            ("project-1", record["record_id"]),
        ).fetchone() if prefetch else None
        with pytest.raises(FoundryError) as error:
            store._resolve_locked_record_after_proof(
                conn, "project-1", record["record_id"], prefetched_row=row,
            )
        assert error.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"

