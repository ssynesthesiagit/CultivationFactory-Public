"""Focused tests for the local DCC semantic publication workflow."""

from __future__ import annotations

import errno
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import character_creation.creative_controller.dcc_semantic_publication as publication_module
import character_creation.creative_controller.factory_catalog_adapter as catalog_adapter_module
import character_creation.creative_controller.semantic_admission as admission_module
from character_creation.creative_controller.contracts import CreativeControllerError
from character_creation.creative_controller.dcc_semantic_publication import (
    DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA,
    DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA,
    _OBJECT_KINDS,
    _EXPECTED_FAMILY_COUNTS,
    _EXPECTED_RECORD_COUNT,
    _mkdir_storage,
    _load_dcc_source_rights_authority_at,
    _load_dcc_source_rights_authority_v3_at,
    _read_catalogue,
    _reopen_publication_artifacts,
    _validate_publication_receipt,
    _prove_source_scope,
    _write_object,
    reopen_dcc_semantic_publication,
    load_dcc_source_rights_authority,
    publish_dcc_semantic_library,
)
from character_creation.creative_controller.factory_catalog_adapter import _choice_kind


LIVE_DB_ENV = "CULTIVATION_FACTORY_LIVE_DB"
V1_RECEIPT_SHA256 = "ce16e04c7e2b63854508185487444567a0cf45c3520092984ad6f059ba33c758"
V2_RECEIPT_SHA256 = "ea2bcb4eabcfc1530f0ab73fc660417312bebda81f62a6f49b59f6ef677e5ff1"
V3_RECORD_COUNT = 4473
V3_METHOD_COUNT = 102
LEGACY_METHOD_SOURCE = (
    "source.23ade2d12c1f574fd738d869",
    "23ade2d12c1f574fd738d869db341aec76cc6d7150f925e87aa06f639fa6afac",
)
REGISTRY_METHOD_SOURCE = (
    "source.42dcf28fceff3f18120940f4",
    "42dcf28fceff3f18120940f4f427be36bdcfaab0d40415e098899a313c2df503",
)
PRODUCTION_AUTHORITY = Path(__file__).resolve().parents[1] / "authority"


def _live_database() -> Path:
    value = os.environ.get(LIVE_DB_ENV)
    if not value:
        pytest.skip(f"set {LIVE_DB_ENV} to run the opt-in live publication test")
    path = Path(value)
    if not path.is_file():
        pytest.skip("configured live fixture is not accessible")
    return path


def _copy_authority(tmp_path: Path) -> Path:
    target = tmp_path / "authority"
    shutil.copytree(PRODUCTION_AUTHORITY, target)
    return target


def _restore_published_receipt(authority: Path, receipt_sha256: str, *, active_pointer: bool) -> Path:
    objects = authority / "dcc_semantics" / "objects"
    found = publication_module._find_receipt_object_by_internal_digest(objects, receipt_sha256)
    assert found is not None
    receipt, receipt_payload = found
    entries = {row["kind"]: row["sha256"] for row in receipt["objects"]}
    (authority / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json").write_bytes(
        (objects / f"{entries['new_source_rights_trust']}.json").read_bytes()
    )
    (authority / "Tianxia_DCC_Semantic_Authority_Trust_v1.json").write_bytes(
        (objects / f"{entries['new_semantic_trust']}.json").read_bytes()
    )
    pointer_path = authority / "Tianxia_DCC_Semantic_Publication_Active_v1.json"
    if active_pointer:
        pointer = publication_module._make_active_publication_pointer(
            receipt,
            hashlib.sha256(receipt_payload).hexdigest(),
        )
        pointer_path.write_bytes(publication_module._canonical_json_bytes(pointer))
    elif pointer_path.exists() or pointer_path.is_symlink():
        pointer_path.unlink()
    return authority


def _copy_v1_authority(tmp_path: Path) -> Path:
    return _restore_published_receipt(_copy_authority(tmp_path), V1_RECEIPT_SHA256, active_pointer=False)


def _copy_v2_authority(tmp_path: Path) -> Path:
    return _restore_published_receipt(_copy_authority(tmp_path), V2_RECEIPT_SHA256, active_pointer=True)


def _empty_inactive_authority(tmp_path: Path) -> Path:
    target = _copy_v1_authority(tmp_path)
    shutil.rmtree(target / "dcc_semantics")
    _set_inactive(target / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json", semantic=False)
    _set_inactive(target / "Tianxia_DCC_Semantic_Authority_Trust_v1.json", semantic=True)
    return target


def _seal_trust(path: Path, *, semantic: bool, active_digest: str) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    active_key = "active_authority_bundle_sha256" if semantic else "active_rights_authority_sha256"
    unsigned = {
        key: value[key]
        for key in value
        if key != "manifest_sha256"
    }
    unsigned["status"] = "ACTIVE"
    unsigned[active_key] = active_digest
    value = {**unsigned, "manifest_sha256": hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def _set_inactive(path: Path, *, semantic: bool) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    active_key = "active_authority_bundle_sha256" if semantic else "active_rights_authority_sha256"
    unsigned = {
        key: value[key]
        for key in value
        if key != "manifest_sha256"
    }
    unsigned["status"] = "INACTIVE"
    unsigned[active_key] = None
    value = {**unsigned, "manifest_sha256": hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def _publish_v2(*args: object, **kwargs: object) -> dict[str, object]:
    """Keep the historical V2 activation tests explicit as the default moves to V3."""

    kwargs["_profile"] = publication_module._PROFILE_V2
    return publish_dcc_semantic_library(*args, **kwargs)  # type: ignore[arg-type, return-value]


def _v3_receipt(authority: dict[str, object], *, family_counts: dict[str, int] | None = None) -> dict[str, object]:
    counts = dict(authority["family_counts"]) if family_counts is None else dict(family_counts)  # type: ignore[arg-type]
    unsigned: dict[str, object] = {
        "schema": DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA,
        "version": 3,
        "mode": "DRY_RUN",
        "status": "READY",
        "record_count": sum(counts.values()),
        "family_counts": counts,
        "database_sha256": "0" * 64,
        "canonical_record_set_sha256": "0" * 64,
        "source_rights_authority_sha256": authority["authority_sha256"],
        "semantic_authority_bundle_sha256": "0" * 64,
        "content_snapshot_sha256": "0" * 64,
        "semantic_admission_receipt_sha256": "0" * 64,
        "old_source_rights_manifest_sha256": "0" * 64,
        "new_source_rights_manifest_sha256": "0" * 64,
        "old_semantic_manifest_sha256": "0" * 64,
        "new_semantic_manifest_sha256": "0" * 64,
        "objects": [{"kind": kind, "sha256": "0" * 64} for kind in _OBJECT_KINDS],
        "predecessor_receipt_sha256": None,
    }
    return {**unsigned, "receipt_sha256": publication_module.sha256_json(unsigned)}


def _materialize_dry_plan(authority: Path, plan: dict[str, object]) -> tuple[dict[str, object], str]:
    objects = authority / "dcc_semantics" / "objects"
    objects.mkdir(parents=True)
    for payload in plan["payloads"].values():  # type: ignore[union-attr]
        payload_bytes = payload  # type: ignore[assignment]
        (objects / f"{hashlib.sha256(payload_bytes).hexdigest()}.json").write_bytes(payload_bytes)
    receipt = plan["publication_receipt"]  # type: ignore[assignment]
    receipt_payload = publication_module._canonical_json_bytes(receipt)
    receipt_digest = hashlib.sha256(receipt_payload).hexdigest()
    (objects / f"{receipt_digest}.json").write_bytes(receipt_payload)
    return receipt, receipt_digest  # type: ignore[return-value]


def _object_payloads(authority: Path, receipt: dict[str, object]) -> dict[str, bytes]:
    objects = authority / "dcc_semantics" / "objects"
    return {
        row["kind"]: (objects / f"{row['sha256']}.json").read_bytes()
        for row in receipt["objects"]  # type: ignore[index]
    }


def _filesystem_snapshot(root: Path) -> dict[str, tuple[str, str]]:
    snapshot: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", "")
        elif path.is_file():
            snapshot[relative] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            snapshot[relative] = ("other", "")
    return snapshot


def _mutate_revoked(path: Path, *, semantic: bool) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    revoked_key = "revoked_authority_bundle_sha256s" if semantic else "revoked_rights_authority_sha256s"
    unsigned = {key: value[key] for key in value if key != "manifest_sha256"}
    unsigned[revoked_key] = sorted(set(unsigned[revoked_key]) | {"0" * 64})
    value = {**unsigned, "manifest_sha256": hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


@pytest.mark.parametrize(
    ("content_type", "expected_kind"),
    (
        ("background_sphere", "sphere"),
        ("background_talent", "talent"),
        ("subpath", "path"),
        ("tradition", "path"),
        ("item", "item"),
    ),
)
def test_v2_choice_kind_mapping_is_structural_and_unknowns_fail_closed(content_type: str, expected_kind: str) -> None:
    assert _choice_kind({"content_type": content_type}) == expected_kind
    assert _choice_kind({"content_type": "unknown_future_family"}) is None
    assert _choice_kind({"content_type": "action"}) is None


def test_fixed_source_rights_descriptor_is_public_safe_and_sealed() -> None:
    authority = load_dcc_source_rights_authority()
    assert set(authority) == {"schema", "version", "authority_id", "allowed_uses", "source_bindings", "authority_sha256"}
    assert authority["allowed_uses"] == ["DCC_SEMANTIC_PUBLICATION"]
    assert len(authority["source_bindings"]) == 12
    assert all(set(row) == {"source_id", "source_hash"} for row in authority["source_bindings"])


def test_v3_source_rights_descriptor_is_sealed_and_replaces_legacy_method_binding() -> None:
    v2 = load_dcc_source_rights_authority()
    v3 = _load_dcc_source_rights_authority_v3_at(PRODUCTION_AUTHORITY)
    assert set(v3) == {"schema", "version", "authority_id", "allowed_uses", "source_bindings", "family_counts", "authority_sha256"}
    assert v3["schema"] == DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA
    assert v3["version"] == 3
    assert v3["authority_id"] == "tianxia.dcc.source-rights.v3"
    v2_bindings = {(row["source_id"], row["source_hash"]) for row in v2["source_bindings"]}
    v3_bindings = {(row["source_id"], row["source_hash"]) for row in v3["source_bindings"]}
    assert v3_bindings == (v2_bindings - {LEGACY_METHOD_SOURCE}) | {REGISTRY_METHOD_SOURCE}
    assert len(v3_bindings) == len(v2_bindings) == 12
    assert list(v3["family_counts"]) == sorted(v3["family_counts"])
    assert sum(v3["family_counts"].values()) == V3_RECORD_COUNT
    assert v3["family_counts"]["cultivation_method"] == V3_METHOD_COUNT


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    (
        (lambda value: value["family_counts"].update({"background": "31"}), "DCC_SCHEMA_TYPE"),
        (lambda value: value["family_counts"].update({"future_family": 0}), "DCC_SCHEMA_UNKNOWN_FIELD"),
        (lambda value: value.__setitem__("family_counts", dict(reversed(list(value["family_counts"].items())))), "DCC_SOURCE_RIGHTS_AUTHORITY_NONCANONICAL"),
    ),
)
def test_v3_descriptor_count_contract_rejects_invalid_or_noncanonical_maps(
    tmp_path: Path,
    mutate: object,
    expected_code: str,
) -> None:
    authority = _copy_authority(tmp_path)
    descriptor_path = authority / "Tianxia_DCC_Source_Rights_Authority_v3.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    mutate(descriptor)  # type: ignore[operator]
    descriptor_path.write_bytes((json.dumps(descriptor, separators=(",", ":")) + "\n").encode())
    with pytest.raises(CreativeControllerError) as error:
        _load_dcc_source_rights_authority_v3_at(authority)
    assert error.value.code == expected_code


def test_v3_receipt_count_must_sum_and_match_stored_descriptor() -> None:
    descriptor = _load_dcc_source_rights_authority_v3_at(PRODUCTION_AUTHORITY)
    receipt = _v3_receipt(descriptor)
    assert _validate_publication_receipt(receipt, descriptor=descriptor)["record_count"] == V3_RECORD_COUNT

    wrong_total = dict(receipt)
    wrong_total["record_count"] = V3_RECORD_COUNT - 1
    wrong_total["receipt_sha256"] = publication_module.sha256_json({key: wrong_total[key] for key in wrong_total if key != "receipt_sha256"})
    with pytest.raises(CreativeControllerError) as error:
        _validate_publication_receipt(wrong_total, descriptor=descriptor)
    assert error.value.code == "DCC_PUBLICATION_RECEIPT_INVALID"

    mismatched_descriptor = json.loads(json.dumps(descriptor))
    mismatched_descriptor["family_counts"]["background"] += 1
    with pytest.raises(CreativeControllerError) as error:
        _validate_publication_receipt(receipt, descriptor=mismatched_descriptor)
    assert error.value.code == "DCC_PUBLICATION_RECEIPT_BINDING_INVALID"


def test_v3_detached_descriptor_and_count_tamper_is_rejected(tmp_path: Path) -> None:
    database = _live_database()
    source_authority = _empty_inactive_authority(tmp_path / "source")
    plan = publication_module._build_plan(database, source_authority, profile=publication_module._PROFILE_V3)

    descriptor_authority = tmp_path / "descriptor-tamper"
    shutil.copytree(source_authority, descriptor_authority)
    receipt, _ = _materialize_dry_plan(descriptor_authority, plan)
    descriptor_entry = next(row for row in receipt["objects"] if row["kind"] == "source_rights_authority")
    objects = descriptor_authority / "dcc_semantics" / "objects"
    descriptor = json.loads((objects / f"{descriptor_entry['sha256']}.json").read_text(encoding="utf-8"))
    descriptor["family_counts"]["background"] += 1
    descriptor["authority_sha256"] = publication_module.sha256_json(
        {key: descriptor[key] for key in descriptor if key != "authority_sha256"}
    )
    descriptor_payload = publication_module._canonical_json_bytes(descriptor)
    descriptor_digest = hashlib.sha256(descriptor_payload).hexdigest()
    (objects / f"{descriptor_digest}.json").write_bytes(descriptor_payload)
    tampered_receipt = json.loads(json.dumps(receipt))
    for row in tampered_receipt["objects"]:
        if row["kind"] == "source_rights_authority":
            row["sha256"] = descriptor_digest
    tampered_receipt["receipt_sha256"] = publication_module.sha256_json(
        {key: tampered_receipt[key] for key in tampered_receipt if key != "receipt_sha256"}
    )
    tampered_payload = publication_module._canonical_json_bytes(tampered_receipt)
    tampered_digest = hashlib.sha256(tampered_payload).hexdigest()
    (objects / f"{tampered_digest}.json").write_bytes(tampered_payload)
    with pytest.raises(CreativeControllerError) as error:
        reopen_dcc_semantic_publication(tampered_receipt["receipt_sha256"], test_authority_root=descriptor_authority)
    assert error.value.code in {"DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "DCC_PUBLICATION_OBJECT_BINDING_INVALID"}

    count_authority = tmp_path / "count-tamper"
    shutil.copytree(source_authority, count_authority)
    receipt, _ = _materialize_dry_plan(count_authority, plan)
    tampered_receipt = json.loads(json.dumps(receipt))
    tampered_receipt["family_counts"]["background"] += 1
    tampered_receipt["record_count"] += 1
    tampered_receipt["receipt_sha256"] = publication_module.sha256_json(
        {key: tampered_receipt[key] for key in tampered_receipt if key != "receipt_sha256"}
    )
    tampered_payload = publication_module._canonical_json_bytes(tampered_receipt)
    tampered_digest = hashlib.sha256(tampered_payload).hexdigest()
    (count_authority / "dcc_semantics" / "objects" / f"{tampered_digest}.json").write_bytes(tampered_payload)
    with pytest.raises(CreativeControllerError) as error:
        reopen_dcc_semantic_publication(tampered_receipt["receipt_sha256"], test_authority_root=count_authority)
    assert error.value.code == "DCC_PUBLICATION_RECEIPT_BINDING_INVALID"


def test_v3_publish_requires_exact_active_v2_predecessor_before_writes(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v2_authority(tmp_path)
    before = _filesystem_snapshot(authority)
    with pytest.raises(CreativeControllerError) as error:
        publish_dcc_semantic_library(
            database,
            publish=True,
            test_authority_root=authority,
        )
    assert error.value.code == "DCC_PUBLICATION_PREDECESSOR_REQUIRED"
    assert _filesystem_snapshot(authority) == before

    with pytest.raises(CreativeControllerError) as error:
        publish_dcc_semantic_library(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
        )
    assert error.value.code == "DCC_PUBLICATION_PREDECESSOR_INVALID"
    assert _filesystem_snapshot(authority) == before


def test_v3_isolated_v2_successor_reopens_both_profiles_and_retries_idempotently(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v2_authority(tmp_path)
    first = publish_dcc_semantic_library(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V2_RECEIPT_SHA256,
    )
    second = publish_dcc_semantic_library(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V2_RECEIPT_SHA256,
    )
    assert first["summary"]["status"] == "PUBLISHED"
    assert first["summary"]["record_count"] == V3_RECORD_COUNT
    assert first["publication_receipt"]["predecessor_receipt_sha256"] == V2_RECEIPT_SHA256
    assert second["publication_receipt"] == first["publication_receipt"]

    previous_root = publication_module._AUTHORITY_ROOT
    publication_module._AUTHORITY_ROOT = authority
    try:
        active = publication_module.load_active_dcc_semantic_publication()
    finally:
        publication_module._AUTHORITY_ROOT = previous_root
    historical_v2 = reopen_dcc_semantic_publication(V2_RECEIPT_SHA256, test_authority_root=authority)
    historical_v3 = reopen_dcc_semantic_publication(
        first["publication_receipt"]["receipt_sha256"],
        test_authority_root=authority,
    )
    assert active["profile"].name == "v3"
    assert active["publication_receipt"] == first["publication_receipt"]
    assert historical_v2["profile"].name == "v2"
    assert historical_v3["profile"].name == "v3"


def test_source_outside_fixed_descriptor_is_blocked() -> None:
    authority = load_dcc_source_rights_authority()
    records = [{"source": row} for row in authority["source_bindings"]]
    records.append({"source": {"source_id": "source.outside", "source_hash": "0" * 64}})
    with pytest.raises(CreativeControllerError) as error:
        _prove_source_scope(records, authority)
    assert error.value.code == "DCC_SOURCE_RIGHTS_AUTHORITY_SCOPE_INVALID"


def test_trust_injection_helpers_are_not_public_exports() -> None:
    assert "_compile_factory_catalog_publication" not in catalog_adapter_module.__all__
    assert "_admit_typed_semantics" not in admission_module.__all__


def test_object_install_is_atomic_no_replace_on_race(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    payload = b'{"payload":"expected"}\n'
    digest = hashlib.sha256(payload).hexdigest()
    target = objects / f"{digest}.json"

    def competing_link(_source: str, destination: str, *, follow_symlinks: bool) -> None:
        del follow_symlinks
        Path(destination).write_bytes(b"competing-bytes")
        raise FileExistsError(errno.EEXIST, "competing install")

    monkeypatch.setattr(publication_module.os, "link", competing_link)
    with pytest.raises(CreativeControllerError) as error:
        _write_object(objects, payload, digest)
    assert error.value.code == "DCC_PUBLICATION_OBJECT_COLLISION"
    assert target.read_bytes() == b"competing-bytes"
    assert not list(objects.glob(".dcc-object-*.tmp"))

    matching_payload = b'{"payload":"matching"}\n'
    matching_digest = hashlib.sha256(matching_payload).hexdigest()

    def matching_link(_source: str, destination: str, *, follow_symlinks: bool) -> None:
        del follow_symlinks
        Path(destination).write_bytes(matching_payload)
        raise FileExistsError(errno.EEXIST, "matching competing install")

    monkeypatch.setattr(publication_module.os, "link", matching_link)
    _write_object(objects, matching_payload, matching_digest)
    assert (objects / f"{matching_digest}.json").read_bytes() == matching_payload


def test_storage_directory_creation_fsyncs_each_parent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = tmp_path / "dcc_semantics"
    objects = storage / "objects"
    synced: list[Path] = []
    monkeypatch.setattr(publication_module, "_fsync_directory", synced.append)

    _mkdir_storage(storage, objects)
    assert synced == [tmp_path, storage]

    # Existing storage must not cause spurious directory creation/fsync work.
    _mkdir_storage(storage, objects)
    assert synced == [tmp_path, storage]


def test_malformed_or_hash_corrupt_descriptor_fails_closed(tmp_path: Path) -> None:
    authority = _copy_authority(tmp_path)
    descriptor_path = authority / "Tianxia_DCC_Source_Rights_Authority_v2.json"
    descriptor_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CreativeControllerError) as error:
        _load_dcc_source_rights_authority_at(authority)
    assert error.value.code == "DCC_SOURCE_RIGHTS_AUTHORITY_UNAVAILABLE"

    authority = _copy_authority(tmp_path / "hash-corrupt")
    descriptor_path = authority / "Tianxia_DCC_Source_Rights_Authority_v2.json"
    value = json.loads(descriptor_path.read_text(encoding="utf-8"))
    value["authority_sha256"] = "0" * 64
    descriptor_path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.raises(CreativeControllerError) as error:
        _load_dcc_source_rights_authority_at(authority)
    assert error.value.code == "DCC_SOURCE_RIGHTS_AUTHORITY_HASH_INVALID"


def test_conflicting_active_rights_authority_refuses_replacement(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_authority(tmp_path)
    _seal_trust(authority / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json", semantic=False, active_digest="f" * 64)
    with pytest.raises(CreativeControllerError) as error:
        publish_dcc_semantic_library(database, test_authority_root=authority)
    assert error.value.code == "DCC_SOURCE_RIGHTS_AUTHORITY_CONFLICT"


def test_conflicting_active_semantic_authority_refuses_replacement(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_authority(tmp_path)
    _seal_trust(authority / "Tianxia_DCC_Semantic_Authority_Trust_v1.json", semantic=True, active_digest="f" * 64)
    with pytest.raises(CreativeControllerError) as error:
        publish_dcc_semantic_library(database, test_authority_root=authority)
    assert error.value.code == "DCC_SEMANTIC_AUTHORITY_CONFLICT"


def test_live_dry_run_is_ready_without_writes() -> None:
    database = _live_database()
    trust_paths = [
        PRODUCTION_AUTHORITY / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json",
        PRODUCTION_AUTHORITY / "Tianxia_DCC_Semantic_Authority_Trust_v1.json",
    ]
    before_trust = [path.read_bytes() for path in trust_paths]
    before_database = hashlib.sha256(database.read_bytes()).hexdigest()
    before_authority = _filesystem_snapshot(PRODUCTION_AUTHORITY)
    result = publish_dcc_semantic_library(database)
    assert result["summary"]["status"] == "READY"
    assert result["summary"]["candidate_status"] == "READY_FOR_OWNER_REVIEW"
    assert result["summary"]["diagnostic_count"] == 0
    assert result["source_rights_authority"]["schema"] == DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA
    assert result["source_rights_authority"]["authority_id"] == "tianxia.dcc.source-rights.v3"
    assert result["publication_receipt"]["schema"] == DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA
    assert result["publication_receipt"]["version"] == 3
    assert result["publication_receipt"]["predecessor_receipt_sha256"] is None
    assert result["summary"]["record_count"] == V3_RECORD_COUNT
    assert result["summary"]["family_counts"]["cultivation_method"] == V3_METHOD_COUNT
    assert len(result["candidate"]["typed_records"]) == V3_RECORD_COUNT
    assert sum(row["choice_kind"] == "item" for row in result["candidate"]["typed_records"]) == _EXPECTED_FAMILY_COUNTS["item"]
    method_ids = sorted(row["choice_id"] for row in result["candidate"]["typed_records"] if row["choice_kind"] == "method")
    assert method_ids == [f"METHOD-{index:03d}" for index in range(1, V3_METHOD_COUNT + 1)]
    typed_ids = {row["choice_id"] for row in result["candidate"]["typed_records"]}
    assert set(result["semantic_admission_receipt"]["active_choice_ids"]) <= typed_ids
    assert before_trust == [path.read_bytes() for path in trust_paths]
    assert result["summary"]["database_sha256"] == before_database
    assert before_database == hashlib.sha256(database.read_bytes()).hexdigest()
    assert before_authority == _filesystem_snapshot(PRODUCTION_AUTHORITY)
    assert (PRODUCTION_AUTHORITY / "dcc_semantics").is_dir()
    assert not (PRODUCTION_AUTHORITY / ".publish.lock").exists()
    assert not list(PRODUCTION_AUTHORITY.glob(".dcc-*"))


def test_v3_live_dry_run_accepts_explicit_predecessor_without_activation() -> None:
    database = _live_database()
    result = publish_dcc_semantic_library(
        database,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    assert result["publication_receipt"]["schema"] == DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA
    assert result["publication_receipt"]["predecessor_receipt_sha256"] == V1_RECEIPT_SHA256


def test_v3_catalogue_overlay_replaces_methods_and_preserves_every_non_method_record() -> None:
    database = _live_database()
    v2_records, _, _ = _read_catalogue(database, publication_module._PROFILE_V2)
    v3_records, v3_counts, _ = _read_catalogue(database, publication_module._PROFILE_V3)

    v2_non_methods = {
        row["record_id"]: publication_module._canonical_json_bytes(row)
        for row in v2_records
        if row["content_type"] != "cultivation_method"
    }
    v3_non_methods = {
        row["record_id"]: publication_module._canonical_json_bytes(row)
        for row in v3_records
        if row["content_type"] != "cultivation_method"
    }
    methods = [row for row in v3_records if row["content_type"] == "cultivation_method"]
    assert v3_non_methods == v2_non_methods
    assert len(v3_records) == V3_RECORD_COUNT
    assert v3_counts["cultivation_method"] == V3_METHOD_COUNT
    assert sorted(row["record_id"] for row in methods) == [f"METHOD-{index:03d}" for index in range(1, 103)]
    assert {(row["source"]["source_id"], row["source"]["source_hash"]) for row in methods} == {REGISTRY_METHOD_SOURCE}
    assert len({row["record_id"] for row in v3_records}) == len(v3_records)


@pytest.mark.parametrize(
    ("records", "expected_code"),
    (
        (
            [
                {"record_id": "METHOD-001", "content_type": "cultivation_method"},
                {"record_id": "METHOD-001", "content_type": "cultivation_method"},
            ],
            "DCC_PUBLICATION_CATALOGUE_DUPLICATE_RECORD_ID",
        ),
        (
            [
                {"record_id": "METHOD-001", "content_type": "cultivation_method"},
                {"record_id": "METHOD-001", "content_type": "talent"},
            ],
            "DCC_PUBLICATION_CATALOGUE_RECORD_ID_COLLISION",
        ),
    ),
)
def test_v3_catalogue_overlay_rejects_duplicate_and_cross_family_ids(
    records: list[dict[str, str]],
    expected_code: str,
) -> None:
    with pytest.raises(CreativeControllerError) as error:
        publication_module._validate_v3_catalogue_record_ids(records)
    assert error.value.code == expected_code


def test_publish_rechecks_database_and_authority_inputs_after_lock_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _live_database()
    authority = _copy_v2_authority(tmp_path)
    plan = publication_module._build_plan(
        database,
        authority,
        profile=publication_module._PROFILE_V3,
        predecessor_receipt_sha256=V2_RECEIPT_SHA256,
    )
    before = _filesystem_snapshot(authority)
    real_build_plan = publication_module._build_plan
    real_sha256_file = publication_module.sha256_file
    real_lock = publication_module._publication_lock
    monkeypatch.setattr(publication_module, "_build_plan", lambda *_args, **_kwargs: plan)

    def changed_database(path: Path) -> str:
        digest = real_sha256_file(path)
        return "f" * 64 if Path(path) == database else digest

    monkeypatch.setattr(publication_module, "sha256_file", changed_database)
    with pytest.raises(CreativeControllerError) as error:
        publish_dcc_semantic_library(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V2_RECEIPT_SHA256,
        )
    assert error.value.code == "DCC_PUBLICATION_DATABASE_CHANGED"
    assert _filesystem_snapshot(authority) == before

    monkeypatch.setattr(publication_module, "sha256_file", real_sha256_file)
    descriptor_path = authority / "Tianxia_DCC_Source_Rights_Authority_v3.json"
    descriptor_bytes = descriptor_path.read_bytes()

    @contextmanager
    def changed_authority(storage: Path, lock_path: Path):
        with real_lock(storage, lock_path):
            descriptor_path.write_bytes(descriptor_bytes + b" ")
            try:
                yield
            finally:
                descriptor_path.write_bytes(descriptor_bytes)

    monkeypatch.setattr(publication_module, "_publication_lock", changed_authority)
    with pytest.raises(CreativeControllerError) as error:
        publish_dcc_semantic_library(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V2_RECEIPT_SHA256,
        )
    assert error.value.code == "DCC_PUBLICATION_AUTHORITY_CHANGED"
    assert _filesystem_snapshot(authority) == before
    monkeypatch.setattr(publication_module, "_build_plan", real_build_plan)


def test_isolated_dry_run_creates_no_storage_or_lock(tmp_path: Path) -> None:
    database = _live_database()
    authority = _empty_inactive_authority(tmp_path)
    before = _filesystem_snapshot(authority)
    result = publish_dcc_semantic_library(database, test_authority_root=authority)
    assert result["summary"]["status"] == "READY"
    assert _filesystem_snapshot(authority) == before
    assert not (authority / "dcc_semantics").exists()
    assert not list(authority.glob(".dcc-*"))


def test_immutable_catalogue_query_succeeds_without_writable_sqlite_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _live_database()
    no_temp = tmp_path / "sqlite-temp"
    no_temp.mkdir()
    os.chmod(no_temp, 0o555)
    monkeypatch.setenv("SQLITE_TMPDIR", str(no_temp))
    monkeypatch.setenv("TMPDIR", str(no_temp))
    try:
        records, family_counts, database_sha256 = _read_catalogue(database)
        assert len(records) == _EXPECTED_RECORD_COUNT
        assert family_counts == _EXPECTED_FAMILY_COUNTS
        assert database_sha256 == hashlib.sha256(database.read_bytes()).hexdigest()
        assert not list(no_temp.iterdir())
    finally:
        os.chmod(no_temp, 0o755)


def test_isolated_publish_is_idempotent_and_objects_are_content_addressed(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v1_authority(tmp_path)
    production_objects = {
        path.name: path.read_bytes()
        for path in (PRODUCTION_AUTHORITY / "dcc_semantics" / "objects").glob("*.json")
    }
    first = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    objects = authority / "dcc_semantics" / "objects"
    first_objects = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in objects.glob("*.json")}
    assert len(first_objects) >= len(_OBJECT_KINDS) + 1
    assert all((objects / name).read_bytes() == payload for name, payload in production_objects.items())
    for path in objects.glob("*.json"):
        assert path.name == f"{hashlib.sha256(path.read_bytes()).hexdigest()}.json"
    collision_entry = first["publication_receipt"]["objects"][0]
    collision_target = objects / f"{collision_entry['sha256']}.json"
    original_bytes = collision_target.read_bytes()
    collision_target.write_bytes(original_bytes + b"corruption")
    with pytest.raises(CreativeControllerError) as error:
        _publish_v2(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
        )
    assert error.value.code == "DCC_PUBLICATION_OBJECT_COLLISION"
    collision_target.write_bytes(original_bytes)
    collision_target.unlink()
    collision_target.symlink_to(Path("/dev/null"))
    with pytest.raises(CreativeControllerError) as error:
        _publish_v2(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
        )
    assert error.value.code == "DCC_PUBLICATION_OBJECT_COLLISION"
    collision_target.unlink()
    collision_target.write_bytes(original_bytes)
    second = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    second_objects = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in objects.glob("*.json")}
    assert first["publication_receipt"] == second["publication_receipt"]
    assert first_objects == second_objects
    assert json.loads((authority / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json").read_text())["status"] == "ACTIVE"
    assert json.loads((authority / "Tianxia_DCC_Semantic_Authority_Trust_v1.json").read_text())["status"] == "ACTIVE"


def test_successor_predecessor_failures_leave_the_authority_tree_unchanged(tmp_path: Path) -> None:
    database = _live_database()

    authority = _copy_v1_authority(tmp_path / "missing")
    before = _filesystem_snapshot(authority)
    with pytest.raises(CreativeControllerError) as error:
        _publish_v2(database, publish=True, test_authority_root=authority)
    assert error.value.code == "DCC_PUBLICATION_PREDECESSOR_REQUIRED"
    assert _filesystem_snapshot(authority) == before

    authority = _copy_v1_authority(tmp_path / "wrong")
    before = _filesystem_snapshot(authority)
    with pytest.raises(CreativeControllerError) as error:
        _publish_v2(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256="0" * 64,
        )
    assert error.value.code == "DCC_PUBLICATION_PREDECESSOR_UNAVAILABLE"
    assert _filesystem_snapshot(authority) == before

    authority = _copy_v1_authority(tmp_path / "stale")
    _mutate_revoked(authority / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json", semantic=False)
    before = _filesystem_snapshot(authority)
    with pytest.raises(CreativeControllerError) as error:
        _publish_v2(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
        )
    assert error.value.code == "DCC_PUBLICATION_PREDECESSOR_STALE"
    assert _filesystem_snapshot(authority) == before


def test_successor_pointer_is_deterministic_and_v1_reopens_by_explicit_receipt(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v1_authority(tmp_path)
    result = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    pointer_path = authority / "Tianxia_DCC_Semantic_Publication_Active_v1.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["receipt_sha256"] == result["publication_receipt"]["receipt_sha256"]
    assert pointer["pointer_sha256"] == hashlib.sha256(
        json.dumps({key: pointer[key] for key in pointer if key != "pointer_sha256"}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    previous_root = publication_module._AUTHORITY_ROOT
    publication_module._AUTHORITY_ROOT = authority
    try:
        active = publication_module.load_active_dcc_semantic_publication()
    finally:
        publication_module._AUTHORITY_ROOT = previous_root
    assert active["profile"].name == "v2"
    assert active["publication_receipt"]["receipt_sha256"] == result["publication_receipt"]["receipt_sha256"]
    historical = reopen_dcc_semantic_publication(V1_RECEIPT_SHA256, test_authority_root=authority)
    assert historical["profile"].name == "v1"
    assert historical["publication_receipt"]["receipt_sha256"] == V1_RECEIPT_SHA256


def test_active_and_historical_reopen_reject_candidate_record_set_receipt_tamper(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v1_authority(tmp_path)
    result = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    receipt = result["publication_receipt"]
    objects = authority / "dcc_semantics" / "objects"
    candidate_entry = next(row for row in receipt["objects"] if row["kind"] == "candidate")
    tampered_candidate = json.loads((objects / f"{candidate_entry['sha256']}.json").read_text(encoding="utf-8"))
    tampered_candidate["canonical_record_set_sha256"] = hashlib.sha256(b"tampered-record-set").hexdigest()
    tampered_candidate["candidate_sha256"] = publication_module.sha256_json(
        {key: tampered_candidate[key] for key in tampered_candidate if key != "candidate_sha256"}
    )
    tampered_candidate_payload = publication_module._canonical_json_bytes(tampered_candidate)
    tampered_candidate_sha256 = hashlib.sha256(tampered_candidate_payload).hexdigest()
    (objects / f"{tampered_candidate_sha256}.json").write_bytes(tampered_candidate_payload)

    tampered_receipt = json.loads(json.dumps(receipt))
    for row in tampered_receipt["objects"]:
        if row["kind"] == "candidate":
            row["sha256"] = tampered_candidate_sha256
    tampered_receipt["receipt_sha256"] = publication_module.sha256_json(
        {key: tampered_receipt[key] for key in tampered_receipt if key != "receipt_sha256"}
    )
    tampered_receipt_payload = publication_module._canonical_json_bytes(tampered_receipt)
    tampered_receipt_sha256 = hashlib.sha256(tampered_receipt_payload).hexdigest()
    (objects / f"{tampered_receipt_sha256}.json").write_bytes(tampered_receipt_payload)

    pointer_path = authority / "Tianxia_DCC_Semantic_Publication_Active_v1.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["receipt_sha256"] = tampered_receipt["receipt_sha256"]
    pointer["receipt_object_sha256"] = tampered_receipt_sha256
    pointer["pointer_sha256"] = publication_module.sha256_json(
        {key: pointer[key] for key in pointer if key != "pointer_sha256"}
    )
    pointer_path.write_bytes(publication_module._canonical_json_bytes(pointer))

    previous_root = publication_module._AUTHORITY_ROOT
    publication_module._AUTHORITY_ROOT = authority
    try:
        with pytest.raises(CreativeControllerError) as error:
            publication_module.load_active_dcc_semantic_publication()
    finally:
        publication_module._AUTHORITY_ROOT = previous_root
    assert error.value.code == "DCC_PUBLICATION_RECEIPT_BINDING_INVALID"
    with pytest.raises(CreativeControllerError) as error:
        reopen_dcc_semantic_publication(tampered_receipt["receipt_sha256"], test_authority_root=authority)
    assert error.value.code == "DCC_PUBLICATION_RECEIPT_BINDING_INVALID"


def test_rights_activation_failure_leaves_semantic_inactive_and_resume_completes(tmp_path: Path) -> None:
    database = _live_database()
    authority = _empty_inactive_authority(tmp_path)

    def fail_after_rights(stage: str) -> None:
        if stage == "after_rights_activation":
            raise RuntimeError("test failure")

    with pytest.raises(RuntimeError, match="test failure"):
        _publish_v2(
            database,
            publish=True,
            test_authority_root=authority,
            _failure_hook=fail_after_rights,
        )
    assert json.loads((authority / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json").read_text())["status"] == "ACTIVE"
    assert json.loads((authority / "Tianxia_DCC_Semantic_Authority_Trust_v1.json").read_text())["status"] == "INACTIVE"
    resumed = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
    )
    assert resumed["summary"]["status"] == "PUBLISHED"


def test_successor_rights_activation_failure_preserves_v1_semantics_and_resumes(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v1_authority(tmp_path)
    rights_path = authority / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json"
    semantic_path = authority / "Tianxia_DCC_Semantic_Authority_Trust_v1.json"
    pointer_path = authority / "Tianxia_DCC_Semantic_Publication_Active_v1.json"
    v1_semantic_bytes = semantic_path.read_bytes()
    v1_semantic_hash = hashlib.sha256(v1_semantic_bytes).hexdigest()
    pointer_before = pointer_path.read_bytes() if pointer_path.exists() else None
    assert pointer_before is None

    preflight = _publish_v2(
        database,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    expected_receipt = dict(preflight["publication_receipt"])
    expected_receipt["mode"] = "PUBLISH"
    expected_receipt["status"] = "PUBLISHED"
    expected_receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            {key: expected_receipt[key] for key in expected_receipt if key != "receipt_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    def fail_after_rights(stage: str) -> None:
        if stage == "after_rights_activation":
            raise RuntimeError("test successor failure")

    with pytest.raises(RuntimeError, match="test successor failure"):
        _publish_v2(
            database,
            publish=True,
            test_authority_root=authority,
            expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
            _failure_hook=fail_after_rights,
        )

    rights = json.loads(rights_path.read_text(encoding="utf-8"))
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    assert rights["status"] == "ACTIVE"
    assert rights["active_rights_authority_sha256"] == preflight["source_rights_authority"]["authority_sha256"]
    assert semantic_path.read_bytes() == v1_semantic_bytes
    assert hashlib.sha256(semantic_path.read_bytes()).hexdigest() == v1_semantic_hash
    assert semantic["status"] == "ACTIVE"
    assert pointer_path.exists() is False

    objects = authority / "dcc_semantics" / "objects"
    for path in objects.glob("*.json"):
        assert path.name == f"{hashlib.sha256(path.read_bytes()).hexdigest()}.json"
    detached_successor = reopen_dcc_semantic_publication(
        expected_receipt["receipt_sha256"],
        test_authority_root=authority,
    )
    assert detached_successor["publication_receipt"] == expected_receipt

    resumed = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    assert resumed["summary"]["status"] == "PUBLISHED"
    assert resumed["publication_receipt"]["receipt_sha256"] == expected_receipt["receipt_sha256"]
    assert pointer_path.is_file()

    previous_root = publication_module._AUTHORITY_ROOT
    publication_module._AUTHORITY_ROOT = authority
    try:
        active = publication_module.load_active_dcc_semantic_publication()
    finally:
        publication_module._AUTHORITY_ROOT = previous_root
    assert active["profile"].name == "v2"
    assert active["publication_receipt"]["receipt_sha256"] == expected_receipt["receipt_sha256"]
    historical = reopen_dcc_semantic_publication(V1_RECEIPT_SHA256, test_authority_root=authority)
    assert historical["profile"].name == "v1"
    assert historical["publication_receipt"]["receipt_sha256"] == V1_RECEIPT_SHA256


def test_missing_corrupt_and_malformed_stored_objects_fail_during_reopen(tmp_path: Path) -> None:
    database = _live_database()
    authority = _copy_v1_authority(tmp_path)
    result = _publish_v2(
        database,
        publish=True,
        test_authority_root=authority,
        expected_predecessor_receipt_sha256=V1_RECEIPT_SHA256,
    )
    receipt = result["publication_receipt"]
    objects = authority / "dcc_semantics" / "objects"
    payloads = _object_payloads(authority, receipt)
    entry = receipt["objects"][0]
    target = objects / f"{entry['sha256']}.json"
    original_bytes = target.read_bytes()
    target.unlink()
    with pytest.raises(CreativeControllerError) as error:
        reopen_dcc_semantic_publication(receipt["receipt_sha256"], test_authority_root=authority)
    assert error.value.code == "DCC_PUBLICATION_OBJECT_UNAVAILABLE"
    target.write_bytes(original_bytes)

    target.write_bytes(b"not-json")
    with pytest.raises(CreativeControllerError) as error:
        reopen_dcc_semantic_publication(receipt["receipt_sha256"], test_authority_root=authority)
    assert error.value.code == "DCC_PUBLICATION_OBJECT_HASH_INVALID"
    target.write_bytes(original_bytes)

    malformed = b"{not-json"
    malformed_digest = hashlib.sha256(malformed).hexdigest()
    malformed_target = objects / f"{malformed_digest}.json"
    malformed_target.write_bytes(malformed)
    mutated_receipt = dict(receipt)
    mutated_receipt["objects"] = [
        {**row, "sha256": malformed_digest} if row["kind"] == "old_source_rights_trust" else row
        for row in receipt["objects"]
    ]
    with pytest.raises(CreativeControllerError) as error:
        _reopen_publication_artifacts(objects, receipt=mutated_receipt, expected_payloads=payloads)
    assert error.value.code == "DCC_PUBLICATION_OBJECT_INVALID"


def test_receipt_is_hash_only_public_safe() -> None:
    database = _live_database()
    receipt = publish_dcc_semantic_library(database)["publication_receipt"]
    text = json.dumps(receipt, sort_keys=True)
    assert "source_path" not in text
    assert "source_text" not in text
    assert "/tmp/" not in text
    assert "/home/" not in text


def test_cli_has_no_caller_selected_root_and_error_is_public_safe() -> None:
    cli = Path(__file__).resolve().parents[1] / "tools" / "publish_dcc_semantic_library.py"
    help_result = subprocess.run(
        [sys.executable, str(cli), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    assert "--authority-root" not in help_result.stdout
    assert "--output" not in help_result.stdout
    assert "--root" not in help_result.stdout
    assert "--expected-predecessor-receipt-sha256" in help_result.stdout
    error_result = subprocess.run(
        [sys.executable, str(cli), "--database", str(Path("missing-database.sqlite3"))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert error_result.returncode == 2
    assert json.loads(error_result.stdout) == {
        "code": "DCC_PUBLICATION_DATABASE_UNAVAILABLE",
        "status": "ERROR",
    }
    assert error_result.stderr == ""
