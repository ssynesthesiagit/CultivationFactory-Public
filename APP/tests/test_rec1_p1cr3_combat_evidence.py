from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.core import FoundryError, sha256_file, sha256_json
from character_creation.production_release import (
    COMBAT_EVIDENCE_SCHEMA,
    CharacterProductionReleaseAdapter,
    _COMBAT_REQUIRED_FIELDS,
)
from character_creation.service import CharacterCreationExecutionService


def _status_fields() -> dict[str, object]:
    return {
        "combat": "NOT_ATTEMPTED",
        "combat_execution": "NOT_ATTEMPTED",
        "combat_runtime": "NOT_CLAIMED",
        "combat_sheet": "NOT_CLAIMED",
        "combat_ready_semantics": "NOT_CLAIMED",
        "encounter": "NOT_ATTEMPTED",
        "controller_selection": "NOT_ATTEMPTED",
        "encounter_setup_required": True,
        "current_resource_requirements": {
            "current_qi_required": False,
            "current_martial_focus_required": False,
        },
        "current_qi_required": False,
        "current_martial_focus_required": False,
        "opponent_team_completion_required": True,
        "battlefield_choice": "NOT_ATTEMPTED",
        "battlefield_owner_choice_committed": False,
        "token_placement": "NOT_ATTEMPTED",
        "token_placement_committed": False,
        "initiative": "NOT_ATTEMPTED",
        "initiative_attempted": False,
    }


def _coherent_combat_proof() -> dict:
    statuses = _status_fields()
    sheet = CharacterProductionReleaseAdapter._combat_raw(
        {"readiness": statuses, "combat_readiness": statuses}
    )
    command5 = CharacterProductionReleaseAdapter._combat_raw(
        {
            "report": {"combat_execution": "NOT_ATTEMPTED", **statuses},
            "model": {
                "metadata": {"combat_execution": "NOT_ATTEMPTED"},
                "capability_readiness": statuses,
                "actions": [{"capabilities": {"combat_execution": "UNSUPPORTED"}}],
            },
            "view": {
                "metadata": {"combat_execution": "NOT_ATTEMPTED"},
                "capability_readiness": statuses,
                "actions": [{"capabilities": {"combat_execution": "NOT_APPLICABLE"}}],
            },
        }
    )
    package = CharacterProductionReleaseAdapter._combat_raw(
        {"readiness": statuses, "manifest": statuses}
    )
    clean_import = CharacterProductionReleaseAdapter._combat_raw(
        {"readiness": statuses, **statuses}
    )
    installed = copy.deepcopy(package)
    reopened = copy.deepcopy(sheet)
    layers = {
        "producer_sheet": sheet,
        "producer_command5": command5,
        "package": package,
        "clean_import": clean_import,
        "installed": installed,
        "reopened_sheet": reopened,
    }
    presence = {
        name: all(field in CharacterProductionReleaseAdapter._combat_semantics(raw) for field in _COMBAT_REQUIRED_FIELDS)
        for name, raw in layers.items()
    }
    output_profile = CharacterProductionReleaseAdapter._combat_raw(
        {"output_profile": {"combat_ready": False, "profile_id": "CHARACTER_GM_MODEL"}}
    )
    command5_layer_status = CharacterProductionReleaseAdapter._layer_combat_execution_status(command5, layer="command5")
    package_layer_status = CharacterProductionReleaseAdapter._layer_combat_execution_status(package, layer="package")
    producer = {
        "output_profile_requested": False,
        "output_profile": output_profile,
        "character_sheet": sheet,
        "command5": command5,
    }
    equalities = {
        "producer_sheet_reopened_sheet_status_equal": True,
        "producer_command5_package_combat_execution_equal": True,
        "producer_command5_package_combat_surfaces_equal": True,
        "package_installed_audit_status_equal": True,
        "package_import_status_equal": True,
        "package_clean_import_installed_readiness_equal": True,
        "package_reopened_sheet_combat_semantics_equal": True,
        "all_corresponding_combat_semantics_equal": True,
        "evidence_schema_complete": True,
        "no_false_combat_ready": True,
    }
    raw_sections = {
        "producer": producer,
        "producer_output_profile": output_profile,
        "producer_sheet": sheet,
        "producer_command5": command5,
        "package": package,
        "clean_import": clean_import,
        "installed": installed,
        "reopened_sheet": reopened,
    }
    return {
        "schema_version": COMBAT_EVIDENCE_SCHEMA,
        "producer": producer,
        "package": package,
        "clean_import": {
            "import_report": clean_import,
            "installed_audit": installed,
            "reopened_sheet": reopened,
        },
        "raw_evidence_hashes": {name: sha256_json(raw) for name, raw in raw_sections.items()},
        "semantic_projections": {
            name: CharacterProductionReleaseAdapter._combat_semantics(raw)
            for name, raw in raw_sections.items()
            if name != "producer"
        },
        "layer_status": {
            "producer_command5": command5_layer_status,
            "package": package_layer_status,
        },
        "schema_presence": presence,
        "equalities": equalities,
        "equality": True,
    }


def _release_fixture(tmp_path: Path, *, combat: dict | None = None) -> dict:
    package = tmp_path / "completed-character.zip"
    package.write_bytes(b"coherent-completed-package")
    package_sha = sha256_file(package)
    audit = {
        "valid": True,
        "path": str(package),
        "sha256": package_sha,
        "bytes": package.stat().st_size,
        "entry_count": 0,
        "checksum_count": 0,
        "member_inventory": [],
        "member_inventory_sha256": sha256_json([]),
        "checksum_manifest": {},
        "crc_validation": {},
    }
    proof = {
        "schema": "TianxiaFoundry.CharacterProductionCompletionProof.v1",
        "package": {
            "path": str(package),
            "filename": package.name,
            "bytes": package.stat().st_size,
            "sha256": package_sha,
            "member_inventory": [],
            "checksum_manifest": {},
            "crc_validation": {},
        },
        "clean_import": {
            "first_status": "IMPORTED",
            "second_status": "ALREADY_INSTALLED_IDENTICAL",
            "identical_reimport": True,
        },
        "character_sheet": {
            "producer_semantic_hash": "sheet",
            "reopened_semantic_hash": "sheet",
            "semantic_equal": True,
        },
        "gm": {
            "producer_model_sha256": "producer-model",
            "package_semantic_hash": "gm",
            "installed_semantic_hash": "gm",
            "package_sha256": package_sha,
            "installed_package_path": str(package),
            "semantic_equal": True,
            "source_conversion": {"valid": True},
            "equalities": {"package_installed_bytes_equal": True},
        },
        "consumer": {
            "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            "status_equal": True,
        },
        "combat": combat or _coherent_combat_proof(),
    }
    return {
        "command6": {"portable_character_zip": str(package)},
        "portable_zip_sha256": package_sha,
        "portable_audit": audit,
        "consumer": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
        "clean_import": {
            "first": {"status": "IMPORTED"},
            "second": {"status": "ALREADY_INSTALLED_IDENTICAL"},
        },
        "registration": {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
        "completion_proof": proof,
    }


def _reseal_attacker_controllable_combat_evidence(combat: dict) -> None:
    raw_sections = {
        "producer": combat["producer"],
        "producer_output_profile": combat["producer"]["output_profile"],
        "producer_sheet": combat["producer"]["character_sheet"],
        "producer_command5": combat["producer"]["command5"],
        "package": combat["package"],
        "clean_import": combat["clean_import"]["import_report"],
        "installed": combat["clean_import"]["installed_audit"],
        "reopened_sheet": combat["clean_import"]["reopened_sheet"],
    }
    combat["raw_evidence_hashes"] = {
        name: sha256_json(value)
        for name, value in raw_sections.items()
    }
    combat["semantic_projections"] = {
        name: CharacterProductionReleaseAdapter._combat_semantics(value)
        for name, value in raw_sections.items()
        if name != "producer"
    }
    layers = {
        name: value
        for name, value in raw_sections.items()
        if name not in {"producer", "producer_output_profile"}
    }
    combat["schema_presence"] = {
        name: all(
            field in CharacterProductionReleaseAdapter._combat_semantics(value)
            for field in _COMBAT_REQUIRED_FIELDS
        )
        for name, value in layers.items()
    }
    combat["layer_status"] = {
        "producer_command5": CharacterProductionReleaseAdapter._layer_combat_execution_status(
            raw_sections["producer_command5"],
            layer="command5",
        ),
        "package": CharacterProductionReleaseAdapter._layer_combat_execution_status(
            raw_sections["package"],
            layer="package",
        ),
    }
    combat["equalities"] = {key: True for key in combat["equalities"]}
    combat["equality"] = True


def _mutate_raw_field_occurrence(raw: dict, *, field: str, path: str, value: object | None, remove: bool = False) -> None:
    bucket = raw["fields"][field]
    if remove:
        raw["occurrences"] = [row for row in raw["occurrences"] if row.get("path") != path]
        bucket["occurrences"] = [row for row in bucket["occurrences"] if row.get("path") != path]
    else:
        changed = 0
        for row in raw["occurrences"]:
            if row.get("path") == path:
                row["value"] = copy.deepcopy(value)
                changed += 1
        for row in bucket["occurrences"]:
            if row.get("path") == path:
                row["value"] = copy.deepcopy(value)
                changed += 1
        assert changed == 2
    unique: dict[str, object] = {}
    for row in bucket["occurrences"]:
        encoded = json.dumps(row["value"], sort_keys=True, separators=(",", ":"))
        unique.setdefault(encoded, copy.deepcopy(row["value"]))
    bucket["values"] = [unique[key] for key in sorted(unique)]
    raw["surface_values"][field] = copy.deepcopy(bucket["values"])
    raw[field] = copy.deepcopy(
        bucket["values"][0]
        if len(bucket["values"]) == 1
        else bucket["values"]
        if bucket["values"]
        else None
    )


def _assert_gate_passes_or_fails(tmp_path: Path, release: dict, monkeypatch) -> None:
    audit = release["portable_audit"]
    monkeypatch.setattr(
        "portable_character.service.PortableCharacterPackageService.audit",
        staticmethod(lambda _path: audit),
    )
    CharacterCreationExecutionService._assert_completed_release_gate({"_production_release": release})


def test_coherent_combat_evidence_passes_and_hashes_cover_all_layers(tmp_path, monkeypatch):
    release = _release_fixture(tmp_path)
    _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert set(release["completion_proof"]["combat"]["raw_evidence_hashes"]) == {
        "producer",
        "producer_output_profile",
        "producer_sheet",
        "producer_command5",
        "package",
        "clean_import",
        "installed",
        "reopened_sheet",
    }


@pytest.mark.parametrize(
    ("surface", "replacement"),
    [
        ("encounter", "ENCOUNTER_MUTATED"),
        ("controller_selection", "CONTROLLER_MUTATED"),
        ("combat_runtime", "RUNTIME_MUTATED"),
    ],
)
def test_combat_surface_mutations_fail_even_when_raw_hashes_are_recomputed(tmp_path, monkeypatch, surface, replacement):
    combat = _coherent_combat_proof()
    mutated = copy.deepcopy(combat)
    package = mutated["package"]
    package["surface_values"][surface] = [replacement]
    package["fields"][surface]["values"] = [replacement]
    package["fields"][surface]["occurrences"][0]["value"] = replacement
    mutated["raw_evidence_hashes"]["package"] = sha256_json(package)
    mutated["semantic_projections"]["package"] = CharacterProductionReleaseAdapter._combat_semantics(package)
    release = _release_fixture(tmp_path, combat=mutated)
    with pytest.raises(FoundryError) as exc:
        _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_command5_combat_execution_divergence_fails_after_resealing_evidence(tmp_path, monkeypatch):
    combat = _coherent_combat_proof()
    mutated = copy.deepcopy(combat)
    command5 = mutated["producer"]["command5"]
    command5["surface_values"]["combat_execution"] = ["COMMAND5_DIVERGED"]
    command5["fields"]["combat_execution"]["values"] = ["COMMAND5_DIVERGED"]
    command5["fields"]["combat_execution"]["occurrences"][0]["value"] = "COMMAND5_DIVERGED"
    mutated["raw_evidence_hashes"]["producer"] = sha256_json(mutated["producer"])
    mutated["raw_evidence_hashes"]["producer_command5"] = sha256_json(command5)
    mutated["semantic_projections"]["producer_command5"] = CharacterProductionReleaseAdapter._combat_semantics(command5)
    release = _release_fixture(tmp_path, combat=mutated)
    with pytest.raises(FoundryError) as exc:
        _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_actual_command5_report_status_mutation_fails_after_full_attacker_reseal(tmp_path, monkeypatch):
    combat = _coherent_combat_proof()
    command5 = combat["producer"]["command5"]
    _mutate_raw_field_occurrence(
        command5,
        field="combat_execution",
        path="report.combat_execution",
        value="REPORT_DIVERGED",
    )
    _reseal_attacker_controllable_combat_evidence(combat)
    release = _release_fixture(tmp_path, combat=combat)
    with pytest.raises(FoundryError) as exc:
        _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_command5_report_status_omission_fails_after_full_attacker_reseal(tmp_path, monkeypatch):
    combat = _coherent_combat_proof()
    _mutate_raw_field_occurrence(
        combat["producer"]["command5"],
        field="combat_execution",
        path="report.combat_execution",
        value=None,
        remove=True,
    )
    _reseal_attacker_controllable_combat_evidence(combat)
    release = _release_fixture(tmp_path, combat=combat)
    with pytest.raises(FoundryError) as exc:
        _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_command5_internal_metadata_conflict_fails_after_full_attacker_reseal(tmp_path, monkeypatch):
    combat = _coherent_combat_proof()
    _mutate_raw_field_occurrence(
        combat["producer"]["command5"],
        field="combat_execution",
        path="model.metadata.combat_execution",
        value="MODEL_METADATA_CONFLICT",
    )
    _reseal_attacker_controllable_combat_evidence(combat)
    release = _release_fixture(tmp_path, combat=combat)
    with pytest.raises(FoundryError) as exc:
        _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"


def test_raw_evidence_hash_tampering_fails_closed(tmp_path, monkeypatch):
    combat = _coherent_combat_proof()
    combat["raw_evidence_hashes"]["package"] = "0" * 64
    release = _release_fixture(tmp_path, combat=combat)
    with pytest.raises(FoundryError) as exc:
        _assert_gate_passes_or_fails(tmp_path, release, monkeypatch)
    assert exc.value.code == "CG1_COMPLETED_PACKAGE_GATE_FAILED"
