from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from combat.canonical import canonical_bytes
from combat.gate3_models import Gate3MatchLock
from combat.gate3_storage import (
    R66_PRE_WINDOWS_STORAGE_GATE3_STORAGE_SHA256,
    Gate3MatchStore,
    Gate3Persistence,
    _match_lock_deterministic_hash,
    decode_match_directory_name,
    encode_match_directory_name,
)
from combat.gate5_service import CombatService

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_WINDOWS = re.compile(r'[<>:"/\\|?*]|[\x00-\x1f]')


def code(exc: BaseException) -> str | None:
    return getattr(getattr(exc, "diagnostic", None), "code", None)


def test_match_directory_codec_is_reversible_and_windows_safe() -> None:
    logical = "match:0123456789abcdef01234567"
    component = encode_match_directory_name(logical)
    assert component.startswith("m1_")
    assert decode_match_directory_name(component) == logical
    assert not FORBIDDEN_WINDOWS.search(component)
    assert not component.endswith((".", " "))
    assert component.split(".", 1)[0].upper() not in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}


def test_new_match_uses_encoded_directory_but_preserves_logical_identity(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed="R66-WINDOWS-PATH-NEW")
    assert session.match_id.startswith("match:")
    assert session.store.match_dir.name == encode_match_directory_name(session.match_id)
    assert ":" not in session.store.match_dir.name
    lock = Gate3MatchLock.model_validate_json(session.store.match_lock_path.read_text(encoding="utf-8"))
    assert lock.match_id == session.match_id
    listed = persistence.list_matches()
    assert len(listed) == 1
    assert listed[0]["match_id"] == session.match_id
    assert listed[0]["storage_layout"] == "ENCODED"
    assert listed[0]["manifest_available"] is True
    assert listed[0]["status"] == "ACTIVE"
    assert listed[0]["state_version"] == session.engine.state.state_version
    assert listed[0]["last_event_sequence"] == session.engine.state.event_sequence


@pytest.mark.skipif(os.name == "nt", reason="POSIX legacy match:<digest> directories cannot be represented on native Windows")
def test_exact_posix_legacy_directory_is_dual_read_without_migration(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    persistence = Gate3Persistence(ROOT, userdata)
    created = persistence.create_match(match_seed="R66-LEGACY-DUAL-READ")
    logical = created.match_id
    encoded = created.store.match_dir
    legacy = encoded.parent / logical
    encoded.rename(legacy)

    loaded = persistence.load_match(logical)
    assert loaded.match_id == logical
    assert loaded.store.match_dir == legacy
    assert loaded.store.storage_layout == "LEGACY_POSIX"
    assert not encoded.exists()
    assert persistence.list_matches()[0]["match_id"] == logical
    assert persistence.list_matches()[0]["storage_layout"] == "LEGACY_POSIX"


def test_legacy_match_bound_to_exact_r66_parent_storage_file_remains_loadable(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    persistence = Gate3Persistence(ROOT, userdata)
    created = persistence.create_match(match_seed="R66-OLD-CONTENT-BINDING")
    lock_doc = json.loads(created.store.match_lock_path.read_text(encoding="utf-8"))
    for row in lock_doc["content_identities"]:
        if row.get("relative_path") == "combat/gate3_storage.py":
            row["sha256"] = R66_PRE_WINDOWS_STORAGE_GATE3_STORAGE_SHA256
            break
    else:  # pragma: no cover
        raise AssertionError("storage identity missing")
    lock_doc["deterministic_payload_sha256"] = _match_lock_deterministic_hash(lock_doc)
    created.store.match_lock_path.write_bytes(canonical_bytes(lock_doc) + b"\n")
    loaded = persistence.load_match(created.match_id)
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.skipif(os.name == "nt", reason="POSIX legacy match:<digest> directories cannot be represented on native Windows")
def test_encoded_and_legacy_copies_fail_closed_without_overwrite(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    persistence = Gate3Persistence(ROOT, userdata)
    created = persistence.create_match(match_seed="R66-STORAGE-COLLISION")
    legacy = created.store.match_dir.parent / created.match_id
    legacy.mkdir()
    with pytest.raises(Exception) as caught:
        Gate3MatchStore(userdata, created.match_id)
    assert code(caught.value) == "MATCH_STORAGE_IDENTITY_COLLISION"
    assert created.store.match_dir.is_dir()
    assert legacy.is_dir()


def test_casefold_alias_fails_closed(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    match_id = "match:0123456789abcdef01234567"
    matches = userdata / "Combat" / "Matches"
    matches.mkdir(parents=True)
    alias = encode_match_directory_name(match_id).swapcase()
    (matches / alias).mkdir()
    with pytest.raises(Exception) as caught:
        Gate3MatchStore(userdata, match_id)
    assert code(caught.value) == "MATCH_STORAGE_IDENTITY_COLLISION"


def test_gate5_metadata_uses_same_centralized_mapping(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    service = CombatService(ROOT, userdata)
    encounter_id = service.catalog()["encounters"][0]["stable_id"]
    match = service.create_match(
        encounter_id=encounter_id,
        display_name="R6.6 Windows path mapping",
        match_seed="R66-GATE5-PATH-MAPPING",
        control_modes={},
    )
    logical = match["match_id"]
    mapped = Gate3MatchStore(userdata, logical).match_dir
    assert service._match_dir(logical) == mapped
    assert (mapped / "FactoryIntegration.json").is_file()
    assert not (userdata / "Combat" / "Matches" / logical).exists()

# Native build wrapper input-policy tests are platform-neutral by design; the
# actual build remains a native-Windows-only operation.
import hashlib
import importlib.util
import zipfile

_VERIFIER_PATH = ROOT / "packaging/windows_portable/verify_native_build_inputs.py"
_SPEC = importlib.util.spec_from_file_location("r66_native_input_verifier", _VERIFIER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verifier)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(root: Path, excluded: set[str] | None = None) -> None:
    excluded = excluded or set()
    rows = []
    for path in sorted(row for row in root.rglob("*") if row.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "SHA256SUMS.txt" or relative in excluded:
            continue
        rows.append(f"{_sha(path)}  {relative}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _native_input_fixture(tmp_path: Path) -> tuple[Path, dict]:
    package = tmp_path / "NativeBuild"
    source = package / "Source"
    source.mkdir(parents=True)
    (source / "source.txt").write_text("sealed source\n", encoding="utf-8")
    _write_manifest(source)
    (package / "README.md").write_text("sealed wrapper\n", encoding="utf-8")
    inputs = package / "Inputs"
    wheels = inputs / "PrivateRuntimeWheels"
    wheels.mkdir(parents=True)
    factory = inputs / "Factory.zip"
    foundation = inputs / "Foundation.zip"
    for path, member in ((factory, "factory.txt"), (foundation, "foundation.txt")):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member, member.encode())
    wheel = wheels / "example-1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel payload")
    policy = {
        "schema": verifier.POLICY_SCHEMA,
        "source": {"root": "Source", "manifest_sha256": _sha(source / "SHA256SUMS.txt")},
        "external_inputs": [
            {"path": "Inputs/Factory.zip", "kind": "zip", "sha256": _sha(factory)},
            {"path": "Inputs/Foundation.zip", "kind": "zip", "sha256": _sha(foundation)},
            {"path": "Inputs/PrivateRuntimeWheels/example-1.0-py3-none-any.whl", "kind": "wheel", "sha256": _sha(wheel)},
        ],
    }
    (package / "EXTERNAL_INPUT_POLICY.json").write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    external = {row["path"] for row in policy["external_inputs"]}
    _write_manifest(package, external)
    return package, policy


def test_native_wrapper_valid_documented_inputs_reach_build_ready_state(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    report = verifier.verify_package(package)
    assert report["status"] == "PASS"
    assert report["ready_for_build"] is True
    assert report["zip_count"] == 2
    assert report["wheel_count"] == 1


def test_native_wrapper_rejects_unexpected_extra_file(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    (package / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(verifier.InputVerificationError, match="coverage mismatch"):
        verifier.verify_package(package)


def test_native_wrapper_rejects_wrong_zip_hash(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    with (package / "Inputs/Factory.zip").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(verifier.InputVerificationError, match="external input SHA-256 mismatch"):
        verifier.verify_package(package)


def test_native_wrapper_rejects_wrong_wheel_hash(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    (package / "Inputs/PrivateRuntimeWheels/example-1.0-py3-none-any.whl").write_bytes(b"wrong")
    with pytest.raises(verifier.InputVerificationError, match="external input SHA-256 mismatch"):
        verifier.verify_package(package)


def test_native_wrapper_rejects_missing_wheel(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    (package / "Inputs/PrivateRuntimeWheels/example-1.0-py3-none-any.whl").unlink()
    with pytest.raises(verifier.InputVerificationError, match="required external inputs are missing"):
        verifier.verify_package(package)


def test_native_wrapper_rejects_windows_unsafe_policy_path_without_creating_invalid_ntfs_name() -> None:
    with pytest.raises(verifier.InputVerificationError, match="Windows-unsafe"):
        verifier.validate_relative_path("Inputs/PrivateRuntimeWheels/bad:name.whl")


def test_native_wrapper_rejects_casefold_collision_in_declared_policy(tmp_path: Path) -> None:
    package, policy = _native_input_fixture(tmp_path)
    policy["external_inputs"].append(
        {
            "path": "inputs/factory.zip",
            "kind": "zip",
            "sha256": policy["external_inputs"][0]["sha256"],
        }
    )
    (package / "EXTERNAL_INPUT_POLICY.json").write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(verifier.InputVerificationError, match="case-fold/NFC external-input collision"):
        verifier.verify_package(package)


@pytest.mark.skipif(os.name == "nt", reason="ordinary Windows filesystems cannot materialize two case-only aliases")
def test_native_wrapper_rejects_casefold_filesystem_collision_on_case_sensitive_host(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    (package / "Case.txt").write_text("one", encoding="utf-8")
    (package / "case.txt").write_text("two", encoding="utf-8")
    with pytest.raises(verifier.InputVerificationError, match="case-fold/NFC filesystem collision"):
        verifier.verify_package(package)


def test_native_wrapper_report_outside_package_allows_verify_only_then_repeat_verification(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    report = tmp_path / "verification-output" / "NativeBuildInputVerification.json"
    result = subprocess.run(
        [
            sys.executable,
            str(_VERIFIER_PATH),
            "--package-root",
            str(package),
            "--report",
            str(report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert report.is_file()
    assert verifier.verify_package(package)["ready_for_build"] is True


def test_native_wrapper_does_not_ignore_same_named_report_inside_sealed_root(tmp_path: Path) -> None:
    package, _ = _native_input_fixture(tmp_path)
    (package / "NativeBuildInputVerification.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(verifier.InputVerificationError, match="coverage mismatch"):
        verifier.verify_package(package)


def test_canonical_native_wrapper_places_verification_report_outside_sealed_root() -> None:
    wrapper = (ROOT / "packaging/windows_portable/BUILD_ON_NATIVE_WINDOWS.ps1").read_text(encoding="utf-8")
    assert "[IO.Path]::GetTempPath()" in wrapper
    assert 'Join-Path $Root "NativeBuildInputVerification.json"' not in wrapper
    assert "--report $VerificationReport" in wrapper
    assert "Verification report path resolves inside the sealed package root" in wrapper


def test_pinned_wheel_inventory_matches_lock_and_is_unique() -> None:
    inventory = json.loads((ROOT / "packaging/windows_portable/R6_6_PRIVATE_RUNTIME_WHEEL_INVENTORY.json").read_text(encoding="utf-8"))
    rows = inventory["wheels"]
    assert len(rows) == 9
    assert len({row["filename"].casefold() for row in rows}) == len(rows)
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in rows)
    lock = (ROOT / "packaging/windows_portable/requirements-private-runtime-wheelhouse-r66.lock.txt").read_text(encoding="utf-8")
    normalized = lock.replace("-", "_").casefold()
    for row in rows:
        distribution, version = row["filename"].split("-")[:2]
        assert f"{distribution.replace('-', '_').casefold()}=={version}" in normalized
