from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, sha256_file
from character_sheet.service import CharacterSheetService
from factory_authoring.service import FactoryAuthoringWorkspaceService
from gm_export.service import GMCharacterExportService

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
EXPECTED_SHEET_SHA256 = "1258491740010cee4db25055bc24889c2ac26e14faf9d222bcef95426650800d"
EXPECTED_WORKSPACE_ID = "8c50a7f0f82f03f3f6b10974c31443a78d2adf7309effccd7222d1d4c2caabc6"
EXPECTED_WORKSPACE_SHA256 = "aec44b9b1b9ebd5bae7e8a737bc811e7bf3b0951e4d79dce788089335db9f1e4"
EXPECTED_ADVANCEMENT_HASHES = {
    "Character_Master_Ledger.json": "a0abf32f57cdc5780e86a281e8f1a3c533c7019294c9426a069e4f91fe6fda97",
    "Rules_Selection_Packets.json": "7257a45dad5c24a667bd6984f4ece14b53f12db4eeb18e40ebc46a828196d071",
    "Projection_Provenance_Map.json": "2f306c14a4143ca967cc0cf5e516d74e9b52459c0db716749284d87c574a40b4",
    "Projection_Coverage_Report.json": "879b04f36ba8e6d9b95101341ed292b93f52c96b637856bdcb9aef79db5ccf91",
    "Projection_Diagnostics.json": "1e8401c7396c99df95098d4eb533ee90da49c9f0083508cf711b8364bf1451f3",
}


def _roots() -> list[Path]:
    values = [value for value in os.getenv("TIANXIA_C2B2_DATA_ROOTS", "").split(os.pathsep) if value]
    if len(values) < 2:
        pytest.skip("Two C2B.2 clean data roots are not configured")
    return [Path(value) for value in values[:2]]


def _artifact_dir() -> Path:
    value = os.getenv("TIANXIA_C2B2_ADVANCEMENT_ARTIFACT_DIR")
    if not value:
        pytest.skip("C2A-R.1 advancement artifact directory is not configured")
    return Path(value)


def _service(data_root: Path) -> FactoryAuthoringWorkspaceService:
    return FactoryAuthoringWorkspaceService(Database(Settings.from_env(ROOT, data_root)))


def _sheet_snapshot(data_root: Path) -> dict:
    return CharacterSheetService(Database(Settings.from_env(ROOT, data_root))).sheet(PROJECT_ID)["owner_character_sheet"]


def test_c2b2_sealed_profiles_and_scope():
    service = _service(Path("/tmp/c2b2-contract-only"))
    profile, profile_sha = service._authoring_profile()
    workspace, workspace_sha = service._workspace_profile()
    assert profile_sha == "a4ec1c621193981d2a82d2085f1c04ec1337326a48990c67427e2cfd04ca6320"
    assert workspace_sha == "d1d12b1aefd7d97abc9356ed68892fe129a0be74b6a5948928b135e10d52f5af"
    assert profile["authority_classification"] == "OWNER_RATIFIED_GM_AUTHORING"
    assert profile["scope"]["mechanical_authority"] is False
    assert profile["scope"]["execution_authority"] is False
    assert workspace["legacy_boundaries"]["pinned_command4_executable_status"] == "NOT_RUN"
    assert workspace["legacy_boundaries"]["legacy_command5_eligible"] is False


def test_c2b2_training_source_coverage_and_no_invented_lore():
    data = _roots()[0]
    service = _service(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    service._validate_profile(profile, workspace, _sheet_snapshot(data))
    covered = [rid for row in profile["training_sources"] for rid in row["record_ids"]]
    assert set(covered) == set(workspace["required_training_source_coverage"])
    assert len(covered) == len(set(covered))
    assert all(row["factory_source_type"] == "other" for row in profile["training_sources"])
    assert "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE" in next(row["record_ids"] for row in profile["training_sources"] if row["source_id"] == "gm.training.background.scoundrel")
    assert all(key not in row for row in profile["training_sources"] for key in ("teacher", "sect", "manual", "location", "historical_event"))


def test_c2b2_non_executable_composites_have_stable_ids_and_bindings():
    service = _service(_roots()[0]); profile, _ = service._authoring_profile()
    rows = profile["composite_playbooks"]
    assert len(rows) == 3
    assert len({row["playbook_id"] for row in rows}) == 3
    assert all(row["classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY" for row in rows)
    assert all(row["capability_status"] == "GM_GUIDANCE_ONLY" for row in rows)
    assert all(row["record_ids"] for row in rows)


def test_c2b2_unsupported_combo_claim_is_rejected():
    data = _roots()[0]; service = _service(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    invalid = copy.deepcopy(profile)
    invalid["composite_playbooks"][0]["grouping_note"] = "This is a guaranteed sequence and legal action script."
    with pytest.raises(FoundryError) as exc:
        service._validate_profile(invalid, workspace, _sheet_snapshot(data))
    assert exc.value.code == "GM_AUTHORING_PROFILE_BLOCKED"


def test_c2b2_dao_and_i_ching_are_owner_authoring_without_bonuses():
    profile, _ = _service(_roots()[0])._authoring_profile()
    dao = profile["dao_i_ching"]["dao"]; iching = profile["dao_i_ching"]["i_ching"]
    assert dao["authoring_id"] == "gm.dao.refinement_through_controlled_flame"
    assert iching["authoring_id"] == "gm.iching.hexagram_30_li"
    assert dao["mechanical_effects"] == [] and iching["mechanical_effects"] == []
    assert all(key not in dao and key not in iching for key in ("bonus", "penalty", "reroll", "resource_change"))


def test_c2b2_ai_profile_is_descriptive_and_not_registered_controller():
    profile, _ = _service(_roots()[0])._authoring_profile(); ai = profile["ai_behavior"]
    assert ai["not_executable_controller_policy"] is True
    assert ai["classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY"
    assert "decision_weights" not in ai and "target_scoring" not in ai and "legal_candidate" not in ai
    source = (ROOT / "factory_authoring/service.py").read_text(encoding="utf-8")
    assert "from combat" not in source and "controller_policy" not in source.split("_reject_executable_claims", 1)[0]


def test_c2b2_two_builds_and_two_clean_roots_are_byte_identical():
    results = []
    for data in _roots():
        service = _service(data)
        first = service.build(PROJECT_ID); second = service.build(PROJECT_ID)
        assert first["workspace_id"] == second["workspace_id"] == EXPECTED_WORKSPACE_ID
        assert first["workspace_sha256"] == second["workspace_sha256"] == EXPECTED_WORKSPACE_SHA256
        assert first["workspace_status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
        assert first["legacy_boundaries"]["pinned_command4_executable_status"] == "NOT_RUN"
        assert first["legacy_boundaries"]["legacy_command5_eligible"] is False
        assert first["readiness"]["gm_screen"] == "NOT_ATTEMPTED"
        assert first["readiness"]["combat"] == "NOT_ATTEMPTED"
        results.append((first["workspace_id"], first["workspace_sha256"], first["artifact_hashes"]))
    assert results[0] == results[1]


def test_c2b2_workspace_required_files_and_cross_file_statuses():
    result = _service(_roots()[0]).build(PROJECT_ID)
    root = Path(result["workspace_path"])
    profile, _ = _service(_roots()[0])._workspace_profile()
    assert set(result["artifact_hashes"]) == set(profile["required_artifacts"])
    manifest = json.loads((root / "Workspace_Manifest.json").read_text())
    assert manifest["workspace_status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
    assert manifest["legacy_boundaries"]["pinned_command4_executable_status"] == "NOT_RUN"
    command4 = json.loads((root / "Validation/Command_4.validation.json").read_text())
    assert command4["valid"] is True
    assert command4["legacy_pinned_command4_pass"] is False
    assert command4["executable_combat_not_attempted"] is True
    c2b2 = json.loads((root / "Validation/C2B2_Workspace.validation.json").read_text())
    assert c2b2["command5_invoked"] is False and c2b2["command6_invoked"] is False


def test_c2b2_negative_missing_training_duplicate_composite_and_unproven_statement():
    data = _roots()[0]; service = _service(data); snapshot = _sheet_snapshot(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    missing = copy.deepcopy(profile); missing["training_sources"] = missing["training_sources"][:-1]
    with pytest.raises(FoundryError): service._validate_profile(missing, workspace, snapshot)
    duplicate = copy.deepcopy(profile); duplicate["composite_playbooks"][1]["playbook_id"] = duplicate["composite_playbooks"][0]["playbook_id"]
    with pytest.raises(FoundryError): service._validate_profile(duplicate, workspace, snapshot)
    unproven = copy.deepcopy(profile); unproven["training_sources"][0]["summary"] = ""
    with pytest.raises(FoundryError): service._validate_profile(unproven, workspace, snapshot)


def test_c2b2_negative_dao_ai_and_executable_claims():
    data = _roots()[0]; service = _service(data); snapshot = _sheet_snapshot(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    no_dao = copy.deepcopy(profile); no_dao["dao_i_ching"].pop("dao")
    with pytest.raises(FoundryError): service._validate_profile(no_dao, workspace, snapshot)
    no_ai = copy.deepcopy(profile); no_ai.pop("ai_behavior")
    with pytest.raises(FoundryError): service._validate_profile(no_ai, workspace, snapshot)
    executable = copy.deepcopy(profile); executable["ai_behavior"]["decision_weights"] = {"attack": 100}
    with pytest.raises(FoundryError): service._validate_profile(executable, workspace, snapshot)


def test_c2b2_gm_export_remains_blocked_and_sheet_identity_is_preserved():
    data = _roots()[0]; db = Database(Settings.from_env(ROOT, data))
    _service(data).build(PROJECT_ID)
    sheet = CharacterSheetService(db).sheet(PROJECT_ID)
    assert sheet["build_status"] == "CHARACTER_SHEET_READY"
    assert sheet["sheet_artifact"]["sha256"] == EXPECTED_SHEET_SHA256
    assert sheet["readiness"] == {"advancement":"ADVANCEMENT_READY","character_sheet":"CHARACTER_SHEET_READY","gm_screen":"NOT_ATTEMPTED","combat":"NOT_ATTEMPTED"}
    assert sheet["factory_workspace"]["status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
    status = GMCharacterExportService(db).status(PROJECT_ID)
    assert status["available"] is False
    if sheet["factory_workspace"].get("command5") == "GM_MODEL_CANDIDATE_READY":
        assert any("consumer verification has not been attempted" in blocker.lower() for blocker in status["blockers"])
    else:
        assert any("Command 5 and Command 6 have not been run" in blocker for blocker in status["blockers"])


def test_c2b2_advancement_artifacts_and_canonical_sheet_remain_byte_identical():
    root = _artifact_dir()
    assert {name: sha256_file(root / name) for name in EXPECTED_ADVANCEMENT_HASHES} == EXPECTED_ADVANCEMENT_HASHES
    assert sha256_file(Path('/mnt/data/c2b1_work/Tianxia_Owner_Character_Sheet_v1.json')) == EXPECTED_SHEET_SHA256


def test_c2b2_ui_is_readable_and_exposes_no_false_export_readiness():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "Prepare Command 1–4 Workspace" in html
    assert "GM tactical authoring is complete" in js
    assert "GM Screen not verified" in js
    assert "Combat not typed" in js
    assert "Command 5 and Command 6 have not been run. GM export remains unavailable." in js
    assert "JSON.stringify(value, null, 2)" in js  # advanced fallback remains available, not normal presentation


def test_c2b2_cpk1_remains_isolated_candidate_and_unregistered():
    service_source = (ROOT / "factory_authoring/service.py").read_text(encoding="utf-8")
    api_source = (ROOT / "app/api.py").read_text(encoding="utf-8")
    assert "content_pack_validator" not in service_source
    assert "candidate_schemas" not in service_source
    assert "SchemaRegistry" in api_source  # existing production registry remains separate
    for path in (ROOT / "schemas/content_pack_candidate").glob("*.json"):
        assert "CANDIDATE_NON_AUTHORITATIVE" in path.read_text(encoding="utf-8")
    isolation = json.loads((ROOT / "docs/content_pack_validator/CPK1_INPUT_VERIFICATION_AND_PRESERVATION.json").read_text(encoding="utf-8"))
    assert isolation.get("candidate_status") == "CANDIDATE_NON_AUTHORITATIVE" or "CANDIDATE_NON_AUTHORITATIVE" in json.dumps(isolation)


def test_c2b2_no_command5_or_command6_invocation_in_new_service():
    source = (ROOT / "factory_authoring/service.py").read_text(encoding="utf-8")
    assert ".command5(" not in source
    assert ".command6(" not in source
    assert "GMCharacterExportService" not in source
