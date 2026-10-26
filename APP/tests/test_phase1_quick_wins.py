"""Phase 1 lightening guards: hashing, caches, and read-boundary auditing.

Each test pins the behaviour that makes one Phase 1 change safe rather than
merely fast: the digest must not move, a cache must still notice a changed
file, and a read must not write.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import string
from pathlib import Path

import pytest

import contracts.registry as registry_module
from app.core import (
    Settings,
    canonical_json,
    clear_sha256_file_cache,
    sha256_file,
    sha256_file_cached,
    sha256_json,
)
from contracts.registry import SchemaRegistry, clear_schema_registry_cache
from project_store.service import (
    CANONICAL_VALIDATION_AUDIT_ENV,
    ProjectStore,
)

APP_ROOT = Path(__file__).resolve().parents[1]


def _legacy_sha256_json(value):
    """The chunked implementation P1-1 replaced."""

    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256()
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def _sample_values():
    random.seed(11)
    return [
        {},
        [],
        "",
        0,
        -0.0,
        1e300,
        3.14159,
        True,
        None,
        {"b": 1, "a": 2, "é": "中文", "z": [1, 2, {"k": None}]},
        {"escapes": 'quote" backslash\\ newline\n tab\t emoji \U0001f600'},
        {"big": 2 ** 80, "negative": -(2 ** 80), "floats": [0.1, 0.2, 1 / 3]},
        [{"n%d" % i: {"v": i, "s": "x" * i} for i in range(40)}],
        {"deep": {"a": {"b": {"c": {"d": [1, {"e": "f"}]}}}}},
        {"".join(random.choices(string.printable, k=8)): random.random() for _ in range(200)},
    ]


@pytest.mark.parametrize("value", _sample_values())
def test_sha256_json_digest_is_unchanged_by_the_one_shot_encode(value) -> None:
    assert sha256_json(value) == _legacy_sha256_json(value)


def test_sha256_json_matches_a_plain_digest_of_the_canonical_encoding() -> None:
    value = {"z": [1, 2, 3], "a": {"b": "é"}}
    expected = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    assert sha256_json(value) == expected


def test_schema_registry_compiles_once_per_unchanged_schema_directory() -> None:
    clear_schema_registry_cache()
    first = SchemaRegistry(APP_ROOT)
    compiled_after_first = len(registry_module._COMPILED_CACHE)
    second = SchemaRegistry(APP_ROOT)

    assert compiled_after_first == 1
    assert len(registry_module._COMPILED_CACHE) == 1
    assert first.versions() == second.versions()
    assert first.status() == second.status()
    version = first.versions()[0]
    assert first.schema(version) is second.schema(version)


def test_schema_registry_recompiles_when_a_schema_file_changes(tmp_path: Path) -> None:
    clear_schema_registry_cache()
    root = tmp_path / "root"
    schemas = root / "schemas"
    schemas.mkdir(parents=True)
    for filename in SchemaRegistry.VERSION_TO_FILE.values():
        source = APP_ROOT / "schemas" / filename
        (schemas / filename).write_bytes(source.read_bytes())

    SchemaRegistry(root)
    assert len(registry_module._COMPILED_CACHE) == 1

    target_version, target_file = next(iter(SchemaRegistry.VERSION_TO_FILE.items()))
    schema = json.loads((schemas / target_file).read_text(encoding="utf-8"))
    schema["title"] = "changed for this test"
    (schemas / target_file).write_text(json.dumps(schema), encoding="utf-8")
    os.utime(schemas / target_file, ns=(0, 10 ** 9))

    rebuilt = SchemaRegistry(root)
    assert len(registry_module._COMPILED_CACHE) == 2
    assert rebuilt.schema(target_version)["title"] == "changed for this test"


def test_sha256_file_cache_returns_the_same_digest_and_notices_a_rewrite(tmp_path: Path) -> None:
    clear_sha256_file_cache()
    path = tmp_path / "archive.bin"
    path.write_bytes(b"first contents")

    first = sha256_file_cached(path)
    assert first == sha256_file(path)
    assert sha256_file_cached(path) == first

    path.write_bytes(b"second contents which is longer")
    os.utime(path, ns=(0, 2 * 10 ** 9))
    second = sha256_file_cached(path)
    assert second == sha256_file(path)
    assert second != first


def test_read_boundaries_never_record_a_successful_validation() -> None:
    for boundary in (
        "project_get",
        "project_export",
        "event_export",
        "event_timeline",
        "record_export",
        "custom_training_source_snapshot",
        "locked_record_reconstruct",
        "non_sphere_path_locked_record_reconstruct",
        "some_future_thing_reconstruct",
    ):
        assert ProjectStore._should_record_validation(boundary, valid=True) is False


def test_read_boundary_failures_are_still_recorded() -> None:
    assert ProjectStore._should_record_validation("project_get", valid=False) is True
    assert ProjectStore._should_record_validation("locked_record_reconstruct", valid=False) is True


def test_write_boundaries_record_only_when_the_owner_opts_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CANONICAL_VALIDATION_AUDIT_ENV, raising=False)
    for boundary in ("project_create", "stage1_user_lock_append", "event_commit_before_insert"):
        assert ProjectStore._should_record_validation(boundary, valid=True) is False

    monkeypatch.setenv(CANONICAL_VALIDATION_AUDIT_ENV, "1")
    for boundary in ("project_create", "stage1_user_lock_append", "event_commit_before_insert"):
        assert ProjectStore._should_record_validation(boundary, valid=True) is True
    # Even opted in, a read must not write.
    assert ProjectStore._should_record_validation("project_get", valid=True) is False


def _audit_probe_store(tmp_path: Path):
    """A real store over a real migrated database, with validation stubbed.

    Only the schema verdict is stubbed.  ``_validate_or_raise`` and the audit
    insert it decides to make are the genuine implementations writing to the
    genuine table.
    """

    from app.core import Database

    # ``conftest`` rebinds ``Settings.from_env`` to require both roots.
    settings = Settings.from_env(APP_ROOT, tmp_path)
    database = Database(settings)
    database.migrate()
    store = ProjectStore(database)
    return database, store


def _audit_rows(database) -> int:
    with database.connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM canonical_object_validations").fetchone()[0]


def test_a_successful_read_boundary_writes_no_audit_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CANONICAL_VALIDATION_AUDIT_ENV, raising=False)
    database, store = _audit_probe_store(tmp_path)
    monkeypatch.setattr(
        store.registry,
        "report",
        lambda obj: {"schema_version": "TianxiaFoundry.CharacterProject.v1", "valid": True, "diagnostics": []},
    )
    before = _audit_rows(database)

    with database.connection() as conn:
        for _ in range(3):
            store._validate_or_raise(
                {"any": "document"},
                boundary="project_get",
                family="character_project",
                key="probe",
                conn=conn,
            )

    assert _audit_rows(database) == before


def test_a_failing_read_boundary_still_records_and_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import FoundryError

    monkeypatch.delenv(CANONICAL_VALIDATION_AUDIT_ENV, raising=False)
    database, store = _audit_probe_store(tmp_path)
    monkeypatch.setattr(
        store.registry,
        "report",
        lambda obj: {
            "schema_version": "TianxiaFoundry.CharacterProject.v1",
            "valid": False,
            "diagnostics": [{"pointer": "/x", "message": "bad"}],
        },
    )
    before = _audit_rows(database)

    with database.connection() as conn:
        with pytest.raises(FoundryError) as raised:
            store._validate_or_raise(
                {"any": "document"},
                boundary="project_get",
                family="character_project",
                key="probe",
                conn=conn,
            )

    assert raised.value.code == "CANONICAL_SCHEMA_VALIDATION_FAILED"
    assert _audit_rows(database) == before + 1
