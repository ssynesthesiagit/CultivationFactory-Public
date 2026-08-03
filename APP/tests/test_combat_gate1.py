from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from combat.canonical import canonical_bytes, sha256_file
from combat.diagnostics import CombatGate1Error
from combat.gate1 import build_gate1
from combat.models import BattlefieldDefinition, EncounterDefinition, FidelityDisposition
from combat.pack_loader import load_installation_records, load_pack
from combat.packaging import build_deterministic_zip, rewrite_manifest_payload_hash
from combat.registry import compile_registry

ROOT = Path(__file__).resolve().parents[1]
GATE1_ROOT = ROOT / "combat_gate1"


def _rebuild_character_pack(gate_root: Path) -> None:
    source = gate_root / "pack_sources" / "tianxia.character_content.mvp"
    rewrite_manifest_payload_hash(source)
    artifact = gate_root / "packs" / "character_content.zip"
    build_deterministic_zip(source, artifact)
    records_path = gate_root / "installation_records.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    for record in records["installations"]:
        if record["pack_id"] == "tianxia.character_content.mvp":
            record["artifact_size"] = artifact.stat().st_size
            record["artifact_sha256"] = sha256_file(artifact)
    records_path.write_bytes(canonical_bytes(records) + b"\n")


def _load_registry(gate_root: Path):
    records = load_installation_records(gate_root / "installation_records.json")
    packs = tuple(load_pack(gate_root / "packs" / record.artifact_filename, record) for record in records)
    return compile_registry(packs)


def test_gate1_compiles_exact_vertical_slice_deterministically(tmp_path: Path) -> None:
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    first = build_gate1(GATE1_ROOT, first_output)
    second = build_gate1(GATE1_ROOT, second_output)

    assert len(first.registry.packs) == 5
    assert {pack.manifest.family.value for pack in first.registry.packs.values()} == {
        "CORE_RULES", "CHARACTER_CONTENT", "CREATURE_CONTENT", "BATTLEFIELD", "ENCOUNTER"
    }
    assert first.registry.snapshot.snapshot_sha256 == second.registry.snapshot.snapshot_sha256
    assert (first_output / "Registry_Snapshot.json").read_bytes() == (second_output / "Registry_Snapshot.json").read_bytes()
    assert {key: value.projection_sha256 for key, value in first.projections.items()} == {
        key: value.projection_sha256 for key, value in second.projections.items()
    }
    assert {key: value.doctrine_sha256 for key, value in first.doctrines.items()} == {
        key: value.doctrine_sha256 for key, value in second.doctrines.items()
    }


def test_registry_is_independent_of_pack_load_order() -> None:
    records = load_installation_records(GATE1_ROOT / "installation_records.json")
    packs = tuple(load_pack(GATE1_ROOT / "packs" / record.artifact_filename, record) for record in records)
    forward = compile_registry(packs)
    reverse = compile_registry(reversed(packs))
    assert canonical_bytes(forward.snapshot.model_dump(mode="json")) == canonical_bytes(reverse.snapshot.model_dump(mode="json"))


def test_four_projections_have_exact_fidelity_coverage_and_no_material_deferment() -> None:
    result = build_gate1(GATE1_ROOT)
    expected = {
        "character_mapping:an_eui_early_book1_cl5",
        "character_mapping:lee_jia_early_book1_cl5",
        "character_mapping:ling_qi_early_outer_sect_cl5",
        "character_mapping:bai_meizhen_early_outer_sect_cl5",
    }
    assert set(result.projections) == expected
    assert len(result.doctrines) == 4
    for projection in result.projections.values():
        rows = projection.projection.mechanic_fidelity
        projected_ids = {
            item["stable_id"]
            for bucket in (
                projection.projection.resources,
                projection.projection.actions,
                projection.projection.reactions,
                projection.projection.passives,
                projection.projection.condition_immunities,
                projection.projection.equipment_effects,
                projection.projection.path_effects,
                projection.projection.subpath_effects,
                projection.projection.foundation_effects,
                projection.projection.spheres,
                projection.projection.talents,
                projection.projection.companions,
            )
            for item in bucket
        }
        assert {row.definition_id for row in rows} == projected_ids
        assert all(row.disposition != FidelityDisposition.MVP_DEFERRED_UNSUPPORTED for row in rows)


def test_doctrines_bind_exact_projection_and_preserve_separate_dao_iching_components() -> None:
    result = build_gate1(GATE1_ROOT)
    by_character = {value.projection.character_id: value for value in result.projections.values()}
    for doctrine in result.doctrines.values():
        character_id = doctrine.doctrine.doctrine_id.split(":", 1)[1].removesuffix(".gate1")
        projection = by_character[character_id]
        assert doctrine.doctrine.source_projection_sha256 == projection.projection_sha256
        assert doctrine.doctrine.components.dao
        assert doctrine.doctrine.components.iching
        assert doctrine.doctrine.components.dao != doctrine.doctrine.components.iching


def test_battlefield_and_encounter_match_frozen_gate1_scope() -> None:
    result = build_gate1(GATE1_ROOT)
    battlefield = result.battlefield
    encounter = result.encounter
    assert isinstance(battlefield, BattlefieldDefinition)
    assert (battlefield.width_squares, battlefield.height_squares, battlefield.square_size_ft) == (20, 14, 5)
    assert sum(region.terrain_type == "QI_HAZARD" for region in battlefield.terrain_regions) == 1
    assert battlefield.information_model == "FULLY_VISIBLE"
    assert isinstance(encounter, EncounterDefinition)
    assert encounter.battlefield_id == battlefield.stable_id
    assert [list(team.participant_ids) for team in encounter.teams] == [
        ["character_mapping:an_eui_early_book1_cl5", "character_mapping:lee_jia_early_book1_cl5"],
        ["character_mapping:bai_meizhen_early_outer_sect_cl5", "character_mapping:ling_qi_early_outer_sect_cl5"],
    ]
    assert encounter.companion_owner == {
        "creature:bai_cui": "character_mapping:bai_meizhen_early_outer_sect_cl5"
    }


def test_data_value_update_recompiles_projection_without_engine_change(tmp_path: Path) -> None:
    gate = tmp_path / "gate1"
    shutil.copytree(GATE1_ROOT, gate)
    before = build_gate1(gate)
    content_path = gate / "pack_sources" / "tianxia.character_content.mvp" / "definitions" / "content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for definition in content["definitions"]:
        if definition["stable_id"] == "action:lee_jia.lightning_lash":
            definition["mechanics"]["damage"] = "2d8+5 lightning"
            break
    else:
        raise AssertionError("Lightning Lash definition not found")
    content_path.write_bytes(canonical_bytes(content) + b"\n")
    _rebuild_character_pack(gate)
    after = build_gate1(gate)
    mapping_id = "character_mapping:lee_jia_early_book1_cl5"
    assert before.registry.snapshot.snapshot_sha256 != after.registry.snapshot.snapshot_sha256
    assert before.projections[mapping_id].projection_sha256 != after.projections[mapping_id].projection_sha256
    assert "2d8+5 lightning" in {
        action["mechanics"].get("damage") for action in after.projections[mapping_id].projection.actions
    }


def test_artifact_identity_mismatch_returns_typed_diagnostic(tmp_path: Path) -> None:
    gate = tmp_path / "gate1"
    shutil.copytree(GATE1_ROOT, gate)
    artifact = gate / "packs" / "core_rules.zip"
    artifact.write_bytes(artifact.read_bytes() + b"ordinary-corruption")
    with pytest.raises(CombatGate1Error) as caught:
        build_gate1(gate)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "COMBAT_PACK_ARTIFACT_IDENTITY_MISMATCH"
    assert diagnostic.phase == "PACK_LOAD"
    assert diagnostic.recovery.value == "STOP"
    assert diagnostic.recommended_action


def test_unresolved_reference_returns_typed_diagnostic(tmp_path: Path) -> None:
    gate = tmp_path / "gate1"
    shutil.copytree(GATE1_ROOT, gate)
    content_path = gate / "pack_sources" / "tianxia.character_content.mvp" / "definitions" / "content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for definition in content["definitions"]:
        if definition["stable_id"] == "action:lee_jia.lightning_lash":
            definition["references"].append("condition:missing.stale_reference")
            definition["references"].sort()
            break
    content_path.write_bytes(canonical_bytes(content) + b"\n")
    _rebuild_character_pack(gate)
    with pytest.raises(CombatGate1Error) as caught:
        _load_registry(gate)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "COMBAT_UNRESOLVED_STABLE_ID"
    assert diagnostic.entity_id == "action:lee_jia.lightning_lash"
    assert diagnostic.source_definition == "condition:missing.stale_reference"


def test_gate1_contains_no_combat_resolution_runtime() -> None:
    combat_files = {path.name for path in (ROOT / "combat").glob("*.py")}
    assert "resolution.py" not in combat_files
    assert "roll_authority.py" not in combat_files
    assert "reaction_manager.py" not in combat_files
    assert "local_controller.py" not in combat_files


def test_exported_schemas_and_acceptance_report_are_present_and_passing() -> None:
    generated = GATE1_ROOT / "generated"
    report = json.loads((generated / "Gate1_Validation_Report.json").read_text(encoding="utf-8"))
    assert report["validation"]["status"] == "PASS"
    assert report["validation"]["registry_snapshot_sha256"] == build_gate1(GATE1_ROOT).registry.snapshot.snapshot_sha256
    assert len(report["validation"]["checks"]) >= 10
    schema_names = {path.name for path in (generated / "schemas").glob("*.schema.json")}
    assert schema_names == {
        "Pack_Manifest.schema.json",
        "Installation_Records.schema.json",
        "Definition_Document.schema.json",
        "Registry_Snapshot.schema.json",
        "Combat_Runtime_Projection.schema.json",
        "Tactical_Doctrine.schema.json",
        "Battlefield.schema.json",
        "Encounter.schema.json",
    }


def test_cli_build_is_reproducible(tmp_path: Path) -> None:
    from combat.cli import main
    from combat.schema_export import export_schemas
    from combat.validation import validate_gate1

    output = tmp_path / "compiled"
    result = build_gate1(GATE1_ROOT, output)
    export_schemas(output / "schemas")
    report = validate_gate1(result)
    (output / "Gate1_Validation_Report.json").write_bytes(canonical_bytes(report) + b"\n")
    assert (output / "Registry_Snapshot.json").read_bytes() == (GATE1_ROOT / "generated" / "Registry_Snapshot.json").read_bytes()
    assert (output / "Gate1_Validation_Report.json").read_bytes() == (GATE1_ROOT / "generated" / "Gate1_Validation_Report.json").read_bytes()


def test_stable_id_hidden_in_mechanical_parameters_must_resolve(tmp_path: Path) -> None:
    gate = tmp_path / "gate1"
    shutil.copytree(GATE1_ROOT, gate)
    content_path = gate / "pack_sources" / "tianxia.character_content.mvp" / "definitions" / "content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for definition in content["definitions"]:
        if definition["stable_id"] == "action:an_eui.ruin_tempered_armament_quick":
            definition["mechanics"]["creates"] = "condition:missing.stale_created_state"
            break
    content_path.write_bytes(canonical_bytes(content) + b"\n")
    _rebuild_character_pack(gate)
    with pytest.raises(CombatGate1Error) as caught:
        _load_registry(gate)
    assert caught.value.diagnostic.code == "COMBAT_UNRESOLVED_STABLE_ID"
    assert caught.value.diagnostic.source_definition == "condition:missing.stale_created_state"
