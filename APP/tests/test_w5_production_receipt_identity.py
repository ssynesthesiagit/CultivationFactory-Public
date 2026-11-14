from pathlib import Path

import pytest

from app.core import FoundryError, sha256_file
from character_creation.production_release import CharacterProductionReleaseAdapter
from character_creation.service import CharacterCreationExecutionService


def test_stable_production_authority_uses_factory_hash_not_isolated_copy_paths():
    common = {
        "factory_zip_hash": "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385",
        "factory_version": "HF05ZVK-R1H",
        "health": "READY",
    }
    manual = {
        **common,
        "copied_factory_zip": r"F:\fixture\manual\vendor\packages\factory.zip",
        "original_factory_zip": r"F:\source\BundledContent\factory.zip",
    }
    standard = {
        **common,
        "copied_factory_zip": r"F:\fixture\standard\vendor\packages\factory.zip",
        "original_factory_zip": r"G:\clean-source\BundledContent\factory.zip",
    }

    stable_manual = CharacterProductionReleaseAdapter._stable(manual)
    stable_standard = CharacterProductionReleaseAdapter._stable(standard)

    assert stable_manual == stable_standard == common
    assert CharacterProductionReleaseAdapter._stable(
        {**standard, "factory_zip_hash": "different-authority"}
    ) != stable_manual


def test_structure_aware_release_identity_retains_mechanics_but_ignores_consumer_runtime_ids():
    first = {
        "mechanics": {"path": "tianxia.sphere.air", "selected_id": "talent-a", "id": "mechanic-a"},
        "consumer": {"package_identity": {"id": "pkg-a"}, "selected_id": "pkg-a", "status": "VERIFIED"},
    }
    second = {
        "mechanics": {"path": "tianxia.sphere.dark", "selected_id": "talent-a", "id": "mechanic-a"},
        "consumer": {"package_identity": {"id": "pkg-b"}, "selected_id": "pkg-b", "status": "VERIFIED"},
    }
    assert CharacterProductionReleaseAdapter._stable(first) != CharacterProductionReleaseAdapter._stable(second)
    assert CharacterProductionReleaseAdapter._stable(first)["consumer"] == CharacterProductionReleaseAdapter._stable(second)["consumer"]


def test_nested_manifest_locations_and_members_remain_release_identity_bearing():
    first = {
        "portable_audit": {
            "manifest": {"package_path": "package-a", "files": [{"path": "member.json", "sha256": "a"}]},
        },
    }
    second = {
        "portable_audit": {
            "manifest": {"package_path": "package-b", "files": [{"path": "member.json", "sha256": "a"}]},
        },
    }
    third = {
        "portable_audit": {
            "manifest": {"package_path": "package-a", "files": [{"path": "member.json", "sha256": "b"}]},
        },
    }
    assert CharacterProductionReleaseAdapter._stable(first) != CharacterProductionReleaseAdapter._stable(second)
    assert CharacterProductionReleaseAdapter._stable(first) != CharacterProductionReleaseAdapter._stable(third)


def test_completed_release_gate_rejects_empty_receipt():
    with pytest.raises(FoundryError) as exc:
        CharacterCreationExecutionService._assert_completed_release_gate({})
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_completed_release_gate_rejects_tampered_physical_package(tmp_path: Path):
    package = tmp_path / "character.zip"
    package.write_bytes(b"original")
    expected_sha = sha256_file(package)
    release = {
        "command6": {"portable_character_zip": str(package)},
        "portable_zip_sha256": expected_sha,
        "portable_audit": {"valid": True, "sha256": expected_sha, "bytes": package.stat().st_size},
        "consumer": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
        "clean_import": {"first": {"status": "IMPORTED"}, "second": {"status": "ALREADY_INSTALLED_IDENTICAL"}},
        "registration": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
        "completion_proof": {
            "schema": "TianxiaFoundry.CharacterProductionCompletionProof.v1",
            "package": {"path": str(package), "filename": package.name, "bytes": package.stat().st_size, "sha256": expected_sha},
            "clean_import": {"first_status": "IMPORTED", "second_status": "ALREADY_INSTALLED_IDENTICAL", "identical_reimport": True},
            "character_sheet": {"producer_semantic_hash": "sheet", "reopened_semantic_hash": "sheet", "semantic_equal": True},
            "gm": {"package_semantic_hash": "gm", "imported_semantic_hash": "gm", "semantic_equal": True},
            "consumer": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "status_equal": True},
            "combat": {"status": "NOT_REQUESTED", "attempted": False, "equality": "NOT_APPLICABLE"},
        },
    }
    package.write_bytes(b"tampered")
    with pytest.raises(FoundryError) as exc:
        CharacterCreationExecutionService._assert_completed_release_gate({"_production_release": release})
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_completed_release_gate_rejects_different_installed_gm_artifact(tmp_path: Path, monkeypatch):
    package = tmp_path / "character.zip"
    installed = tmp_path / "installed-current.zip"
    package.write_bytes(b"original")
    installed.write_bytes(b"different-installed-artifact")
    package_sha = sha256_file(package)
    audit = {
        "valid": True,
        "sha256": package_sha,
        "bytes": package.stat().st_size,
        "entry_count": 0,
        "checksum_count": 0,
        "member_inventory_sha256": "inventory",
        "member_inventory": [],
        "checksum_manifest": {},
        "crc_validation": {},
    }
    monkeypatch.setattr("portable_character.service.PortableCharacterPackageService.audit", staticmethod(lambda _path: audit))
    release = {
        "command6": {"portable_character_zip": str(package)},
        "portable_zip_sha256": package_sha,
        "portable_audit": audit,
        "consumer": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
        "clean_import": {"first": {"status": "IMPORTED"}, "second": {"status": "ALREADY_INSTALLED_IDENTICAL"}},
        "registration": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
        "completion_proof": {
            "schema": "TianxiaFoundry.CharacterProductionCompletionProof.v1",
            "package": {"path": str(package), "filename": package.name, "bytes": package.stat().st_size, "sha256": package_sha, "member_inventory": [], "checksum_manifest": {}, "crc_validation": {}},
            "clean_import": {"first_status": "IMPORTED", "second_status": "ALREADY_INSTALLED_IDENTICAL", "identical_reimport": True},
            "character_sheet": {"producer_semantic_hash": "sheet", "reopened_semantic_hash": "sheet", "semantic_equal": True},
            "gm": {
                "producer_model_sha256": "producer",
                "package_semantic_hash": "package",
                "installed_semantic_hash": "package",
                "package_sha256": package_sha,
                "installed_package_path": str(installed),
                "semantic_equal": True,
                "source_conversion": {"valid": True},
                "equalities": {"package_installed_bytes_equal": True},
            },
            "consumer": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "status_equal": True},
            "combat": {"schema_version": "TianxiaFoundry.CharacterProductionCombatEvidence.v1", "equality": True, "raw_evidence_hashes": {"producer": "p"}, "equalities": {"x": True}},
        },
    }
    with pytest.raises(FoundryError) as exc:
        CharacterCreationExecutionService._assert_completed_release_gate({"_production_release": release})
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"
    assert "installed_gm_package" in (exc.value.details or {})
