from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, sha256_file
from character_sheet.service import CharacterSheetService
from gm_export.service import GMCharacterExportService


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
EXPECTED_SHEET_SHA256 = "1258491740010cee4db25055bc24889c2ac26e14faf9d222bcef95426650800d"
EXPECTED_ADVANCEMENT_HASHES = {
    "Character_Master_Ledger.json": "a0abf32f57cdc5780e86a281e8f1a3c533c7019294c9426a069e4f91fe6fda97",
    "Rules_Selection_Packets.json": "7257a45dad5c24a667bd6984f4ece14b53f12db4eeb18e40ebc46a828196d071",
    "Projection_Provenance_Map.json": "2f306c14a4143ca967cc0cf5e516d74e9b52459c0db716749284d87c574a40b4",
    "Projection_Coverage_Report.json": "879b04f36ba8e6d9b95101341ed292b93f52c96b637856bdcb9aef79db5ccf91",
    "Projection_Diagnostics.json": "1e8401c7396c99df95098d4eb533ee90da49c9f0083508cf711b8364bf1451f3",
}


def _artifact_dir() -> Path:
    value = os.getenv("TIANXIA_C2B1_ARTIFACT_DIR")
    if not value:
        pytest.skip("C2B.1 advancement artifact directory not configured")
    return Path(value)


def _runtime_roots() -> list[Path]:
    values = [value for value in os.getenv("TIANXIA_C2B1_DATA_ROOTS", "").split(os.pathsep) if value]
    if len(values) < 2:
        pytest.skip("Two C2B.1 clean-import data roots are not configured")
    return [Path(value) for value in values[:2]]


def _artifacts() -> tuple[dict, dict]:
    root = _artifact_dir()
    ledger = json.loads((root / "Character_Master_Ledger.json").read_text(encoding="utf-8"))
    packets = json.loads((root / "Rules_Selection_Packets.json").read_text(encoding="utf-8"))
    return ledger, packets


def test_c2b1_contracts_are_checksum_and_internal_seal_bound(tmp_path):
    service = CharacterSheetService(Database(Settings.from_env(ROOT, tmp_path / "data")))
    display, display_sha = service._display_contract()
    profile, profile_sha = service._readiness_profile()
    assert display["readiness_stage"] == "CHARACTER_SHEET_READY"
    assert display_sha == "2eac06ec88406a871fe3899ab97e2e65054f1ebd4e90a35750ef3ba5503ec8b3"
    assert profile["stage_semantics"] == {
        "advancement": "ADVANCEMENT_READY",
        "character_sheet": "CHARACTER_SHEET_READY",
        "gm_screen": "NOT_ATTEMPTED",
        "combat": "NOT_ATTEMPTED",
    }
    assert profile_sha == "bcf99ed72499d0970ce23d3df81a88102dcc923e6b6ecc54dea5422b4c5d9459"


def test_c2b1_selected_record_coverage_background_separation_and_cinder_touch(tmp_path):
    ledger, packets = _artifacts()
    service = CharacterSheetService(Database(Settings.from_env(ROOT, tmp_path / "data")))
    contract, contract_sha = service._display_contract()
    cards, by_id = service._build_record_cards(ledger, packets, contract, contract_sha)
    assert len(cards) == 25
    assert len({card["record_id"] for card in cards}) == 25
    assert by_id["TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"]["section"] == "background_talent"
    assert by_id["tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"]["display_name"] == "Cinder Touch"
    assert all(card["capabilities"]["character_sheet"] == "SUPPORTED" for card in cards)
    for card in cards:
        if card["capabilities"]["combat_execution"] not in {"SUPPORTED", "NOT_APPLICABLE"}:
            assert card["display_only_not_execution_authority"] is True
            assert "not yet typed" in card["combat_execution_note"]


def test_c2b1_display_contract_fail_closed_mutations(tmp_path):
    ledger, packets = _artifacts()
    service = CharacterSheetService(Database(Settings.from_env(ROOT, tmp_path / "data")))
    contract, contract_sha = service._display_contract()

    missing = json.loads(json.dumps(contract)); missing["rules"] = missing["rules"][:-1]
    with pytest.raises(FoundryError) as exc:
        service._build_record_cards(ledger, packets, missing, contract_sha)
    assert exc.value.code == "CHARACTER_SHEET_DISPLAY_MAPPING_MISSING"

    duplicate = json.loads(json.dumps(contract)); duplicate["rules"].append(dict(duplicate["rules"][0]))
    with pytest.raises(FoundryError) as exc:
        service._build_record_cards(ledger, packets, duplicate, contract_sha)
    assert exc.value.code == "CHARACTER_SHEET_DUPLICATE_DISPLAY_MAPPING"

    unproven = json.loads(json.dumps(contract)); unproven["rules"][0]["source"]["source_hash"] = ""
    with pytest.raises(FoundryError) as exc:
        service._build_record_cards(ledger, packets, unproven, contract_sha)
    assert exc.value.code == "CHARACTER_SHEET_DESCRIPTION_UNPROVEN"

    false_execution = json.loads(json.dumps(contract)); false_execution["rules"][0]["display_only_not_execution_authority"] = False
    with pytest.raises(FoundryError) as exc:
        service._build_record_cards(ledger, packets, false_execution, contract_sha)
    assert exc.value.code == "CHARACTER_SHEET_FALSE_EXECUTION_CLAIM"


def test_c2b1_stale_display_contract_is_rejected(tmp_path):
    source = ROOT / "character_sheet/contracts/Tianxia_Fire_Qi_Character_Sheet_Display_Contract_R1.json"
    copied = tmp_path / source.name
    copied.write_bytes(source.read_bytes() + b"\n")
    copied.with_suffix(copied.suffix + ".sha256").write_text(
        (source.with_suffix(source.suffix + ".sha256")).read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(FoundryError) as exc:
        CharacterSheetService._verify_sealed_json(
            copied,
            expected_schema="TianxiaFoundry.CharacterSheetDisplayContract.v1",
            error_prefix="CHARACTER_SHEET_DISPLAY_CONTRACT",
        )
    assert exc.value.code == "CHARACTER_SHEET_DISPLAY_CONTRACT_STALE"


def test_c2b1_two_clean_imports_and_forced_builds_are_deterministic():
    hashes = []
    for data_root in _runtime_roots():
        service = CharacterSheetService(Database(Settings.from_env(ROOT, data_root)))
        first = service.sheet(PROJECT_ID)
        second = service.sheet(PROJECT_ID)
        assert first["build_status"] == "CHARACTER_SHEET_READY"
        assert first["readiness"] == {
            "advancement": "ADVANCEMENT_READY",
            "character_sheet": "CHARACTER_SHEET_READY",
            "gm_screen": "NOT_ATTEMPTED",
            "combat": "NOT_ATTEMPTED",
        }
        assert first["gm_export"]["available"] is False
        assert first["sheet_artifact"]["sha256"] == second["sheet_artifact"]["sha256"]
        assert first["sheet_artifact"]["sha256"] == EXPECTED_SHEET_SHA256
        snapshot = first["owner_character_sheet"]
        assert snapshot["identity"]["display_name"] == "C1A Clean Fire-Qi Proof"
        assert snapshot["ability_scores_and_statistics"]["armor_class"]["value"] == 13
        assert snapshot["ability_scores_and_statistics"]["initiative"]["bonus"] == 3
        assert snapshot["ability_scores_and_statistics"]["hit_points"]["maximum"] == 38
        assert snapshot["ability_scores_and_statistics"]["primary_resource"]["maximum"] == 15
        assert sum(len(rows) for rows in snapshot["selected_record_sections"].values()) == 25
        assert snapshot["explicit_none_systems"]["method"]["state"] == "none"
        assert snapshot["later_stage_status"]["gm_screen"]["status"] == "NOT_ATTEMPTED"
        assert snapshot["later_stage_status"]["combat"]["status"] == "NOT_ATTEMPTED"
        hashes.append(first["sheet_artifact"]["sha256"])
    assert len(set(hashes)) == 1


def test_c2b1_gm_export_gate_remains_closed_without_running_command5_or_6():
    data_root = _runtime_roots()[0]
    status = GMCharacterExportService(Database(Settings.from_env(ROOT, data_root))).status(PROJECT_ID)
    assert status["available"] is False
    assert status["sheet_build_status"] == "CHARACTER_SHEET_READY"
    assert any("GM tactical authoring" in blocker for blocker in status["blockers"])


def test_c2b1_advancement_artifacts_remain_byte_identical():
    root = _artifact_dir()
    assert {name: sha256_file(root / name) for name in EXPECTED_ADVANCEMENT_HASHES} == EXPECTED_ADVANCEMENT_HASHES


def test_c2b1_legacy_gm_compatibility_is_not_eligible_bit_alone():
    status = {"eligible_for_command5": True, "command5_status": "NOT_RUN"}
    stage_aware = {key: {"value": 1} for key in ("character", "core_stats", "background_origin", "path_selections", "spheres", "talents", "resources", "actions")}
    stage_aware["readiness"] = {"advancement": "ADVANCEMENT_READY"}
    assert CharacterSheetService._legacy_completed_gm_ready(stage_aware, status) is False

    incomplete_legacy = {"character": {"name": "Legacy"}}
    assert CharacterSheetService._legacy_completed_gm_ready(incomplete_legacy, status) is False

    complete_legacy = {key: {"value": 1} for key in ("character", "core_stats", "background_origin", "path_selections", "spheres", "talents", "resources", "actions")}
    assert CharacterSheetService._legacy_completed_gm_ready(complete_legacy, status) is True



def test_c2b1_pending_is_not_typed_none_and_false_later_stage_promotion_fails():
    data_root = _runtime_roots()[0]
    service = CharacterSheetService(Database(Settings.from_env(ROOT, data_root)))
    result = service.sheet(PROJECT_ID)
    snapshot = result["owner_character_sheet"]
    assert set(snapshot["explicit_none_systems"]) == {"method", "foundation", "manuals", "equipment", "forged_techniques"}
    assert snapshot["later_stage_status"]["gm_screen"]["status"] == "NOT_ATTEMPTED"
    assert snapshot["later_stage_status"]["combat"]["status"] == "NOT_ATTEMPTED"
    contract, _ = service._display_contract()
    profile, _ = service._readiness_profile()
    required = {rule["record_id"] for rule in contract["rules"]}
    invalid = copy.deepcopy(snapshot)
    invalid["later_stage_status"]["gm_screen"]["status"] = "none"
    with pytest.raises(FoundryError) as exc:
        service._validate_snapshot(invalid, required, profile)
    assert exc.value.code == "CHARACTER_SHEET_BUILD_BLOCKED"


def test_c2b1_failed_stale_build_does_not_promote_new_ready_artifact(tmp_path):
    data_root = _runtime_roots()[0]
    contracts = tmp_path / "contracts"; contracts.mkdir()
    for name in (
        "Tianxia_Fire_Qi_Character_Sheet_Display_Contract_R1.json",
        "Tianxia_Fire_Qi_Character_Sheet_Display_Contract_R1.json.sha256",
        "Tianxia_Character_Sheet_Readiness_Profile_R1.json",
        "Tianxia_Character_Sheet_Readiness_Profile_R1.json.sha256",
    ):
        shutil.copy2(ROOT / "character_sheet/contracts" / name, contracts / name)
    display = contracts / "Tianxia_Fire_Qi_Character_Sheet_Display_Contract_R1.json"
    display.write_bytes(display.read_bytes() + b"\n")

    class StaleContractService(CharacterSheetService):
        @property
        def _contracts_dir(self):
            return contracts

    artifact_root = data_root / "character_sheets" / PROJECT_ID
    before = sorted(path.name for path in artifact_root.iterdir()) if artifact_root.is_dir() else []
    with pytest.raises(FoundryError) as exc:
        StaleContractService(Database(Settings.from_env(ROOT, data_root))).sheet(PROJECT_ID)
    assert exc.value.code == "CHARACTER_SHEET_DISPLAY_CONTRACT_STALE"
    after = sorted(path.name for path in artifact_root.iterdir()) if artifact_root.is_dir() else []
    assert after == before

def test_c2b1_ui_has_readable_untruncated_nested_rendering():
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert ".slice(0, 100)" not in js
    assert ".slice(0, 80)" not in js
    assert "depth < 2" not in js.split("function appendReadableValue", 1)[1].split("function renderOwnerSheet", 1)[0]
    assert "sheet.provenance.advancement_projection" in js
    assert "sheet.provenance.character_sheet_projection" in js
    assert "Character Sheet complete; GM authoring and export have not been attempted." in js
