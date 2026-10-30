"""Recorded acquisitions and formation answers remain independently removable."""
from app.models import TabletopAdvanceRemoveRequest
from combat.ext import formations
from combat.gate5_service import CombatService
from non_sphere_authority.service import NonSphereAuthorityService
from tests.test_formation_training_choices import blank, install, PID, SPHERE, TRAINING, ROOT
from tests.test_mgr_t14_heavenly_source import SOURCE, installation


def test_acquisition_and_choice_removal_are_distinct_on_cold_read(tmp_path, monkeypatch):
    monkeypatch.setattr(NonSphereAuthorityService, "_build_background_route_authority", lambda self: {})
    doc = blank(cl=15)
    doc["spheres_and_talents"].update(sphere_record_ids=[SPHERE],
        automatic_sphere_component_record_ids=[TRAINING, formations.BASE_SET])
    _, table = install(tmp_path, doc)
    table.acquire_feature(PID, SOURCE, installation("Refined"))
    table.add_advancement(PID, "feature", TRAINING, feature_choices={TRAINING: "nourishing_cycle"})
    added = table.advancement(PID)["added"]
    acquisition, = added["acquisitions"]
    assert (acquisition["name"], acquisition["attainment"], acquisition["reference"]) == (
        "Heavenly Body", "Refined", installation()["reference"])
    request = TabletopAdvanceRemoveRequest(kind="feature", record_id="0")
    table.remove_advancement(PID, request.kind, request.record_id)
    assert len(table.buttons.get(PID)["advancement"]["features"]) == 1
    assert not table.buttons.get(PID)["advancement"]["feature_choices"]
    assert CombatService(ROOT, tmp_path)._factory_owner_sheet(PID)["foundation"]["stage"] == "Refined"
    request = TabletopAdvanceRemoveRequest(kind="acquisition", record_id=SOURCE)
    table.remove_advancement(PID, request.kind, request.record_id)
    cold = CombatService(ROOT, tmp_path)._factory_owner_sheet(PID)
    assert not cold.get("feature_access")
    assert not cold.get("foundation")


def test_unreadable_acquisition_is_removable_from_grow(tmp_path, monkeypatch):
    monkeypatch.setattr(NonSphereAuthorityService, "_build_background_route_authority", lambda self: {})
    _, table = install(tmp_path, blank(cl=15))
    table.acquire_feature(PID, SOURCE, installation("Refined"))
    saved = table.buttons.get(PID)["advancement"]
    saved["features"][0]["source"]["authority"] = "invalid"
    table.buttons.save_advancement(PID, saved)
    recovery = table.advancement(PID)
    assert "Heavenly Body" in recovery["recovery_error"]
    assert recovery["added"]["acquisitions"][0]["id"] == SOURCE
    table.remove_advancement(PID, "acquisition", SOURCE)
    assert not CombatService(ROOT, tmp_path)._factory_owner_sheet(PID).get("foundation")
