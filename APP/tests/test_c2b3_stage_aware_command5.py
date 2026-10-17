from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, sha256_file
from character_sheet.service import CharacterSheetService
from factory_authoring.command5_profile import (
    CHARACTER_GM_PROFILE,
    GM_CANDIDATE_READY,
    LEGACY_PROFILE,
    CharacterGMCommand5Profile,
)
from gm_export.service import GMCharacterExportService
from projector.verification import ProjectionVerifier

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
EXPECTED = {
    "candidate_sha256": "ead334664e8b5581ac189bcf855dee2143e1aadd10133a4528897e6e806b85b4",
    "gm_model_sha256": "1aff701c69b655330180ad7b23ad7cad3f7723d4ae73c4d324e4782fbbff542c",
    "gm_view_model_sha256": "7a864ceded3fd2243f8eb537b05987b032d2a6197b76abb85eb022aed47f0283",
    "deep_audit_sha256": "c7ffec9e57941e403b313900aab009ea02529abfabc78907fcf6a019db83b7fd",
    "build_manifest_sha256": "0b09a29c2f76c1887b97ae7640d97fe624ecec4b014a6e7addedc9943e41ddfa",
}


def _roots() -> list[Path]:
    values = [Path(value) for value in os.getenv("TIANXIA_C2B3_DATA_ROOTS", "").split(os.pathsep) if value]
    if len(values) < 2:
        pytest.skip("Two C2B.3 clean data roots are not configured")
    return values[:2]


def _factory() -> Path:
    value = os.getenv("TIANXIA_C2B3_FACTORY_ROOT")
    if not value:
        pytest.skip("Pinned Factory root is not configured")
    return Path(value)


def _fixture() -> Path:
    value = os.getenv("TIANXIA_C2B3_WORKSPACE_FIXTURE")
    if not value:
        pytest.skip("C2B.2 workspace fixture is not configured")
    return Path(value)


def _db(root: Path) -> Database:
    db = Database(Settings.from_env(ROOT, root)); db.migrate(); return db


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    rows = []
    for index, data_root in enumerate(_roots()):
        db = _db(data_root)
        output = tmp_path_factory.mktemp(f"c2b3-build-{index}")
        report = ProjectionVerifier(db, factory_root=_factory()).command5(
            PROJECT_ID,
            source_fixture=_fixture(),
            output_root=output,
            build_profile=CHARACTER_GM_PROFILE,
        )
        rows.append((db, report))
    return rows


def test_c2b3_sealed_profiles_default_legacy_and_unknown_rejection():
    service = CharacterGMCommand5Profile(_db(_roots()[0]), factory_root=_factory())
    contract, digest = service.build_profiles()
    assert digest == "a13e7de169aa9833a8a4fede0878651c8a32d59da9c0eceb1344d65f9b9c69af"
    assert contract["default_profile_id"] == LEGACY_PROFILE
    assert service.select_profile(None)[0]["profile_id"] == LEGACY_PROFILE
    assert service.select_profile(CHARACTER_GM_PROFILE)[0]["profile_id"] == CHARACTER_GM_PROFILE
    with pytest.raises(FoundryError) as exc:
        service.select_profile("UNKNOWN_PROFILE")
    assert exc.value.code == "FACTORY_BUILD_PROFILE_UNKNOWN"


def test_c2b3_character_gm_command4_passes_and_legacy_remains_blocked():
    result = CharacterGMCommand5Profile(_db(_roots()[0]), factory_root=_factory()).validate_command4(PROJECT_ID)
    assert result["valid"] is True
    assert result["character_gm_command4_status"] == "CHARACTER_GM_COMMAND_4_PROFILE_PASS"
    assert result["legacy_full_command4_status"] == "BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE"
    assert result["command5_invoked"] is False and result["command6_invoked"] is False


def test_c2b3_two_clean_roots_and_forced_builds_are_deterministic(builds):
    summaries = []
    for _db_value, report in builds:
        assert report["status"] == GM_CANDIDATE_READY
        summaries.append({key: report[key] for key in EXPECTED})
    assert summaries[0] == summaries[1] == EXPECTED


def test_c2b3_gm_model_schema_tabs_arrays_and_background_talent(builds):
    report = builds[0][1]
    model = json.loads(Path(report["gm_model_path"]).read_text(encoding="utf-8"))
    view = json.loads(Path(report["build"]).joinpath("Tianxia_GM_Character_View_Model_v2.json").read_text(encoding="utf-8"))
    assert model["schema_version"] == "Tianxia_GM_Character_Model_v1"
    assert view["schema_version"] == "Tianxia_GM_Character_View_Model_v2"
    assert model["metadata"]["build_profile"] == CHARACTER_GM_PROFILE
    assert model["metadata"]["consumer_verification"] == "NOT_ATTEMPTED"
    assert len(model["leveling_ledger"]) == 5
    assert model["spheres_talents"]["background_talent_record_id"] == "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"
    assert "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE" not in model["spheres_talents"]["learned_talent_record_ids"]
    assert len(model["actions"]) == len(view["actions"]) == 13
    assert len(model["composites"]) == len(view["composites"]) == 3
    assert "[object Object]" not in json.dumps(model)


def test_c2b3_display_only_capability_and_false_combat_claims_are_absent(builds):
    model = json.loads(Path(builds[0][1]["gm_model_path"]).read_text(encoding="utf-8"))
    assert all(row["display_only_not_execution_authority"] is True for row in model["actions"])
    assert all(row["classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY" for row in model["composites"])
    assert model["capability_readiness"]["combat"] == "NOT_ATTEMPTED"
    assert model["diagnostics"]["combat_execution_pending"] is True
    assert model["ai_behavior"]["not_executable_controller_policy"] is True


def test_c2b3_gm_export_remains_blocked_and_command6_not_run(builds):
    db = builds[0][0]
    sheet = CharacterSheetService(db).sheet(PROJECT_ID, compact=True)
    status = GMCharacterExportService(db).status(PROJECT_ID)
    assert sheet["factory_workspace"]["command5"] == GM_CANDIDATE_READY
    assert sheet["factory_workspace"]["command6"] == "NOT_RUN"
    assert sheet["readiness"]["gm_screen"] == "NOT_ATTEMPTED"
    assert status["available"] is False
    assert any("consumer verification has not been attempted" in row.lower() for row in status["blockers"])


def test_c2b3_stale_model_is_detected_without_enabling_export(builds):
    db = builds[0][0]
    service = CharacterGMCommand5Profile(db, factory_root=_factory())
    current = service.status(PROJECT_ID)
    model = Path(current["gm_model_path"])
    before = model.read_bytes()
    try:
        model.write_bytes(before + b"\n")
        stale = service.status(PROJECT_ID)
        assert stale["status"] == "STALE"
        assert stale["gm_export_available"] is False
    finally:
        model.write_bytes(before)
    assert service.status(PROJECT_ID)["status"] == GM_CANDIDATE_READY


def test_c2b3_legacy_default_source_path_and_cpk1_isolation():
    verifier = (ROOT / "projector/verification.py").read_text(encoding="utf-8")
    profile = (ROOT / "factory_authoring/command5_profile.py").read_text(encoding="utf-8")
    assert "if build_profile is not None" in verifier
    assert "run_command5.py" in verifier
    assert "command6(" not in profile
    assert "content_pack_validator" not in profile
    for path in (ROOT / "schemas/content_pack_candidate").glob("*.json"):
        assert "CANDIDATE_NON_AUTHORITATIVE" in path.read_text(encoding="utf-8")


def test_c2b3_ui_exposes_candidate_pending_consumer_and_export_block():
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "GM model candidate are sealed" in js
    assert "GM Screen consumer verification has not been attempted" in js
    assert "export remains unavailable" in js
    assert "Combat not typed" in js or "combat execution remains untyped" in js
