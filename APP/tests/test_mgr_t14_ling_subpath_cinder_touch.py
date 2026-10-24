"""Native acquisition baseline only; this does not certify Revealing Ember delivery."""
import json
import hashlib
from pathlib import Path

import pytest

from app.api import create_app
from combat.factory_compiler import compile_character


ROOT = Path(__file__).resolve().parents[1]
SUBPATH = "tianxia.subpath.qi.cinder_heart_cultivator"
FEATURE = SUBPATH + ".feature.cinder_touch"
PROFILE = ROOT / "projector/contracts/C2AR1_Stage_Aware_Validation_Profile.json"
CONTRACT = ROOT / "projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json"
KNOWN_EXPECTED = "2c752f3b48d6dd9db17860855d33402d380a706520d9a74a2f6e2e416b326419"
KNOWN_ACTUAL = "83f1c49137c64ad6dafabc1885b6c8ddaa5d93d905d769627c32d94032380541"


class KnownCinderAcquisitionBlocker(Exception):
    """Only the recorded validation-profile mismatch, never an acquisition pass."""


def _check_acquisition_status(run):
    assert run["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
    if run["status"] == "NEEDS_REVIEW":
        blockers = run["blockers"]
        if (len(blockers) == 1
                and blockers[0].get("code") == "PROJECTION_AUTHORITY_IDENTITY_MISMATCH"
                and blockers[0].get("details") == {
                    "authority": "validation_profile", "path": str(PROFILE)}
                and json.loads(CONTRACT.read_text())["validation_profile"]["sha256"] == KNOWN_EXPECTED
                and hashlib.sha256(PROFILE.read_bytes()).hexdigest() == KNOWN_ACTUAL):
            raise KnownCinderAcquisitionBlocker(
                "Recorded validation_profile identity mismatch; Cinder acquisition unverified")
        assert [b["code"] for b in blockers] == ["COMMAND6_CHARACTER_GM_CONSUMER_FAILED"]
        assert blockers[0]["details"]["consumer_report"]["harness_run"]["skipped"] is True


@pytest.mark.xfail(strict=True, raises=KnownCinderAcquisitionBlocker,
                  reason="Pre-existing sealed validation_profile mismatch; remove quarantine when repaired")
def test_native_cinder_touch_acquisition_baseline(catalog_environment, monkeypatch):
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE", "/nonexistent/cinder-touch-browser-forbidden")
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
    assert "FIRE" in bundle["actor_template"]["damage_resistances"]
    print("Native CL3 Cinder Touch acquired; Fire resistance compiled. "
          "No table execution, Revealing Ember, or whole-record certification claimed.")


def _recorded_blocked_run():
    return {"status": "NEEDS_REVIEW", "blockers": [{
        "code": "PROJECTION_AUTHORITY_IDENTITY_MISMATCH",
        "details": {"authority": "validation_profile", "path": str(PROFILE)}}]}


@pytest.fixture
def recorded_profile(tmp_path, monkeypatch):
    """Exercise quarantine policy independently of future sealed-profile repairs."""
    profile = tmp_path / "validation_profile.json"
    contract = tmp_path / "projection_contract.json"
    profile.write_bytes(b'{"recorded": true}')
    contract.write_text(json.dumps({"validation_profile": {"sha256": KNOWN_EXPECTED}}))
    monkeypatch.setitem(globals(), "PROFILE", profile)
    monkeypatch.setitem(globals(), "CONTRACT", contract)
    monkeypatch.setitem(globals(), "KNOWN_ACTUAL", hashlib.sha256(profile.read_bytes()).hexdigest())


def test_quarantine_matches_only_recorded_failure(recorded_profile):
    with pytest.raises(KnownCinderAcquisitionBlocker):
        _check_acquisition_status(_recorded_blocked_run())


@pytest.mark.parametrize("change", [
    "authority", "path", "code", "extra", "status", "expected", "actual", "details",
])
def test_quarantine_rejects_unrelated_blockers(change, recorded_profile):
    run = _recorded_blocked_run()
    blocker = run["blockers"][0]
    if change in {"authority", "path"}:
        blocker["details"][change] = "unrelated"
    elif change == "code":
        blocker["code"] = "UNRELATED_FAILURE"
    elif change == "extra":
        run["blockers"].append({"code": "UNRELATED_FAILURE"})
    elif change == "status":
        run["status"] = "FAILED"
    elif change == "expected":
        CONTRACT.write_text(json.dumps({"validation_profile": {"sha256": "different"}}))
    elif change == "details":
        blocker["details"]["unrelated"] = "additional diagnostic"
    else:
        PROFILE.write_bytes(b'{"repaired": true}')
    with pytest.raises(AssertionError):
        _check_acquisition_status(run)


def test_quarantine_exposes_unexpected_success():
    _check_acquisition_status({"status": "READY_FOR_REVIEW"})
    mark, = test_native_cinder_touch_acquisition_baseline.pytestmark
    assert mark.name == "xfail"
    assert mark.kwargs["strict"] is True
    assert mark.kwargs["raises"] is KnownCinderAcquisitionBlocker


@pytest.mark.parametrize("skipped", [False, None])
def test_consumer_failure_is_not_the_quarantined_profile_failure(skipped):
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
