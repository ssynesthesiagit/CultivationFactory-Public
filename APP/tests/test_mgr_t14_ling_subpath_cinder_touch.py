"""Native acquisition baseline only; this does not certify Revealing Ember delivery."""
import hashlib
import json
from pathlib import Path

import pytest

from app.api import create_app
from combat.factory_compiler import compile_character


ROOT = Path(__file__).resolve().parents[1]
SUBPATH = "tianxia.subpath.qi.cinder_heart_cultivator"
FEATURE = SUBPATH + ".feature.cinder_touch"
PROFILE = ROOT / "projector/contracts/C2AR1_Stage_Aware_Validation_Profile.json"
CONTRACT = ROOT / "projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json"


def _check_acquisition_status(run):
    assert run["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
    if run["status"] == "NEEDS_REVIEW":
        assert [b["code"] for b in run["blockers"]] == ["COMMAND6_CHARACTER_GM_CONSUMER_FAILED"]
        assert run["blockers"][0]["details"]["consumer_report"]["harness_run"]["skipped"] is True


def test_native_cinder_touch_acquisition_baseline(catalog_environment, monkeypatch):
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", "/nonexistent/cinder-touch-browser-forbidden")
    _record_native_acquisition(catalog_environment)


def _record_native_acquisition(catalog_environment):
    app = create_app(catalog_environment["settings"])
    builder = app.state.character_builder
    project = builder.create_project(
        working_name="Cinder Touch acquisition baseline", concept="Cinder Heart cultivator",
        source_reference=None, target_cl=3, power_band="rival/boss", creation_mode="detailed",
        generation_route="ai_bootstrap", ability_scores={}, autogen_seed="MGR-T14-CINDER-CL3",
        selections={"path_choice": ["tianxia.path.qi_cultivation"], "subpath_choice": [SUBPATH]},
        method_planning_mode="AUTO")
    builder.commit_normal_first_cycle_catalog_choices(project["project_id"])
    run = app.state.character_creation.start(
        project["project_id"], execution_mode="STANDARD_API", idempotency_key="mgr-t14-cinder-cl3",
        controller_route="DETERMINISTIC_CREATIVE_CONTROLLER")
    _check_acquisition_status(run)
    sheet = app.state.character_creation.load_candidate_gm_context(run["run_id"])["owner_character_sheet"]
    assert sheet["identity"]["cultivation_level"] == 3
    assert FEATURE in json.dumps(sheet["path_and_subpath"])
    bundle = compile_character(sheet, actor_id="actor:cinder-acquisition")
    # Cinder Touch's printed "Gain Resistance to Fire damage" is an always-on
    # defense passive; ActorTemplate.damage_resistances is a different field.
    defense = next(row for row in bundle["typed_passives"]
                   if row.get("feature_id") == FEATURE and row.get("kind") == "resistance")
    assert "FIRE" in defense["damage_types"]
    print("Native CL3 Cinder Touch acquired; Fire resistance compiled. "
          "No table execution, Revealing Ember, or whole-record certification claimed.")


def test_profile_identity_mismatch_is_not_an_acquisition_pass():
    """The sealed validation profile matches its contract, so this blocker is a real failure.

    It used to be counted as the quarantined profile mismatch even though the
    contract and the file agreed, which could hide an actual projection failure.
    """
    assert json.loads(CONTRACT.read_text())["validation_profile"]["sha256"] == hashlib.sha256(
        PROFILE.read_bytes()).hexdigest()
    run = {"status": "NEEDS_REVIEW", "blockers": [{
        "code": "PROJECTION_AUTHORITY_IDENTITY_MISMATCH",
        "details": {"authority": "validation_profile", "path": str(PROFILE)}}]}
    with pytest.raises(AssertionError):
        _check_acquisition_status(run)


@pytest.mark.parametrize("skipped", [False, None])
def test_consumer_failure_is_not_an_acquisition_pass(skipped):
    """A later acquisition failure must remain red after the profile is repaired."""
    run = {"status": "NEEDS_REVIEW", "blockers": [{
        "code": "COMMAND6_CHARACTER_GM_CONSUMER_FAILED",
        "details": {"consumer_report": {"harness_run": {"skipped": skipped}}}}]}
    with pytest.raises(AssertionError):
        _check_acquisition_status(run)


def test_skipped_consumer_continues_to_the_acquisition_assertions():
    """Retain the original skipped-browser path without marking acquisition passed."""
    _check_acquisition_status({"status": "NEEDS_REVIEW", "blockers": [{
        "code": "COMMAND6_CHARACTER_GM_CONSUMER_FAILED",
        "details": {"consumer_report": {"harness_run": {"skipped": True}}}}]})
