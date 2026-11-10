from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, canonical_json, sha256_file
from factory_authoring.command5_profile import CharacterGMCommand5Profile
from portable_character.service import (
    GM_MODEL_NAME,
    GM_VIEW_NAME,
    PortableCharacterPackageService,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
EXPECTED_CANDIDATE = "ead334664e8b5581ac189bcf855dee2143e1aadd10133a4528897e6e806b85b4"
EXPECTED_CONSUMER = "fd541c8c5526d19ecaaca1ab3088023ac379341fe100e381ad285e0f2ec32490"


def _env_path(name: str) -> Path:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    path = Path(value)
    if not path.exists():
        pytest.skip(f"{name} does not exist")
    return path


def _package() -> Path:
    return _env_path("TIANXIA_C2C1_PORTABLE_ZIP")


def test_c2c1_portable_package_is_exactly_covered_and_source_bound():
    audit = PortableCharacterPackageService.audit(_package())
    manifest = audit["manifest"]
    assert audit["valid"] is True
    assert audit["checksum_count"] == audit["entry_count"] - 1
    assert manifest["project_id"] == EXPECTED_PROJECT_ID
    assert manifest["build_profile"] == "CHARACTER_GM_MODEL"
    assert manifest["source_command5_candidate_sha256"] == EXPECTED_CANDIDATE
    assert manifest["consumer"]["package_sha256"] == EXPECTED_CONSUMER
    assert manifest["native_or_interactive_acceptance"] == "NOT_RUN"
    assert manifest["combat_execution"] == "NOT_ATTEMPTED"


def test_c2c1_root_models_are_display_containers_and_exact_sources_are_preserved():
    with zipfile.ZipFile(_package()) as zf:
        model = json.loads(zf.read(GM_MODEL_NAME))
        view = json.loads(zf.read(GM_VIEW_NAME))
        source_model = json.loads(zf.read(f"source/C2B3_{GM_MODEL_NAME}"))
        source_view = json.loads(zf.read(f"source/C2B3_{GM_VIEW_NAME}"))
    assert model["metadata"]["display_normalization_only"] is True
    assert view["metadata"]["display_normalization_only"] is True
    assert model["equipment_resources_states"]["equipment"] == []
    assert isinstance(model["equipment_resources_states"]["resources"], list)
    assert source_model["metadata"]["consumer_verification"] == "NOT_ATTEMPTED"
    assert source_view["metadata"]["consumer_verification"] == "NOT_ATTEMPTED"


def test_c2c1_package_has_no_combat_sheet_or_false_native_claim():
    with zipfile.ZipFile(_package()) as zf:
        names = zf.namelist()
        readiness = json.loads(zf.read("READINESS.json"))
    assert not any("Combat_Sheet" in name or name.startswith("combat/") for name in names)
    assert readiness["gm_screen"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
    assert readiness["native_or_interactive_acceptance"] == "NOT_RUN"
    assert readiness["combat"] == "NOT_ATTEMPTED_OR_CAPABILITY_BLOCKED"
    assert readiness["cpk1_schemas_registered"] is False


def test_c2c1_two_forced_builds_are_byte_identical():
    second = _env_path("TIANXIA_C2C1_PORTABLE_ZIP_SECOND")
    assert sha256_file(_package()) == sha256_file(second)


def test_c2c1_exact_consumer_reports_match_and_save_reload():
    one = json.loads(_env_path("TIANXIA_C2C1_CONSUMER_REPORT").read_text())
    two = json.loads(_env_path("TIANXIA_C2C1_CONSUMER_REPORT_SECOND").read_text())
    assert one["status"] == two["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"
    assert one["semantic_hash"] == two["semantic_hash"]
    assert one["save_reload_semantic_equivalence"] is True
    assert len(one["tabs"]) == 18
    assert one["no_object_object"] is True
    assert one["console_or_page_errors"] == []


def test_c2c1_two_clean_import_reports_reproduce_package_and_sheet():
    reports = [json.loads(_env_path(name).read_text()) for name in (
        "TIANXIA_C2C1_CLEAN_IMPORT_ONE", "TIANXIA_C2C1_CLEAN_IMPORT_TWO"
    )]
    package_hash = sha256_file(_package())
    for report in reports:
        assert report["first"]["status"] == "IMPORTED"
        assert report["second"]["status"] == "ALREADY_INSTALLED_IDENTICAL"
        assert report["first"]["package_sha256"] == package_hash
        assert report["sheet"]["build_status"] == "CHARACTER_SHEET_READY"
        assert report["sheet"]["readiness"]["gm_screen"] == "GM_READY_SOURCE_VERIFIED"
        assert report["export"]["sha256"] == package_hash


def test_c2c1_member_tampering_fails_closed(tmp_path):
    with zipfile.ZipFile(_package()) as source:
        files = {info.filename: source.read(info.filename) for info in source.infolist() if not info.is_dir()}
    files[GM_MODEL_NAME] += b"\n"
    target = tmp_path / "tampered.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    with pytest.raises(FoundryError) as exc:
        PortableCharacterPackageService.audit(target)
    assert exc.value.code == "PORTABLE_CHARACTER_MEMBER_HASH_MISMATCH"


@pytest.mark.parametrize("names,code", [
    (["../escape"], "PORTABLE_CHARACTER_UNSAFE_PATH"),
    (["A.json", "a.JSON"], "PORTABLE_CHARACTER_PATH_COLLISION"),
    (["caf\u00e9.json", "cafe\u0301.json"], "PORTABLE_CHARACTER_PATH_COLLISION"),
])
def test_c2c1_archive_paths_fail_closed(tmp_path, names, code):
    target = tmp_path / "bad.zip"
    with zipfile.ZipFile(target, "w") as zf:
        for name in names:
            zf.writestr(name, b"x")
    with pytest.raises(FoundryError) as exc:
        PortableCharacterPackageService.audit(target)
    assert exc.value.code == code


def test_c2c1_symlink_fails_before_payload_interpretation(tmp_path):
    target = tmp_path / "link.zip"
    with zipfile.ZipFile(target, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, b"target")
    with pytest.raises(FoundryError) as exc:
        PortableCharacterPackageService.audit(target)
    assert exc.value.code == "PORTABLE_CHARACTER_SPECIAL_FILE"


def test_c2c1_unknown_profile_is_rejected(fresh_db):
    factory = _env_path("TIANXIA_C2C1_FACTORY_ROOT")
    service = CharacterGMCommand5Profile(fresh_db, factory_root=factory)
    with pytest.raises(FoundryError) as exc:
        service.select_profile("UNKNOWN_PROFILE")
    assert exc.value.code == "FACTORY_BUILD_PROFILE_UNKNOWN"


def test_c2c1_stale_pointer_cannot_retain_verified_status(fresh_db, tmp_path):
    project_id = EXPECTED_PROJECT_ID
    root = fresh_db.settings.data_dir / "portable_characters" / project_id
    root.mkdir(parents=True)
    package = root / "current.zip"
    package.write_bytes(_package().read_bytes())
    pointer = {
        "project_id": project_id,
        "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
        "package_path": str(package),
        "package_sha256": "0" * 64,
    }
    (root / "current.json").write_text(canonical_json(pointer))
    status = PortableCharacterPackageService(fresh_db).verified_status(project_id)
    assert status["status"] == "STALE"
    assert status["reason"] == "VERIFIED_PACKAGE_MISSING_OR_HASH_MISMATCH"


def test_c2c1_owner_ui_explains_single_zip_and_pending_boundaries():
    source = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "either the Factory or the bundled GM Screen" in source
    assert "Native owner acceptance remains pending" in source
    assert "Combat pending" in source
