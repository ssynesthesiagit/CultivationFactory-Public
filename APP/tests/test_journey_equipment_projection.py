"""Checks in a cold journey use the gear selected when the build was last compiled."""
import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT, sheet


def test_mantis_acquisition_reprojects_check_after_preparing_to_unattune(tmp_path):
    project = "a1b2c3d4"
    actor = FACTORY_ACTOR_PREFIX + project
    belt = {"name": "Test belt", "body_slot": "Waist", "attunement_slots": 1,
            "ability_enhancement": {"ability": "STR", "bonus": 2}}
    doc = sheet([], cl=10, score=20, primary="Stamina")
    doc["identity"]["path"] = "Body Refining"
    doc["equipment"] = [{"starting_kit": {"items": [], "resolved_treasure_purchases": {"wondrous": [belt]}}}]
    package = tmp_path / "portable_characters" / project
    package.mkdir(parents=True)
    with zipfile.ZipFile(package / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))

    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"map_id": "gear-check", "display_name": "Training yard",
        "width_squares": 10, "height_squares": 10, "objects": [], "starts": {"team1": [[2, 2]]}})
    journey = service.create_journey(project_ids=[project], arena_id="battlefield:map.gear-check",
        positions={actor: {"x": 2, "y": 2}}, base_paces={actor: 1800})
    jid = journey["journey_id"]

    def check(label):
        cold = CombatService(ROOT, tmp_path)
        state = cold.journey_state(jid)
        state = cold.journey_world_fact(jid, state["revision"], {
            "source": "journey:noncombat_check", "subject": actor, "kind": "request", "scope": label,
            "value": {"purpose": "Move a stone", "ability": "STR", "skill": "", "dc": 15,
                      "sect_context": 0, "role": "", "duty": "", "institution": "", "recovery": ""},
            "expires_at": state["seconds"] + 60, "readers": [actor]})
        state = cold.journey_act(jid, state["revision"], actor, "check_start", {"scope": label, "merit": 0})
        roll = next(e["roll"] for e in reversed(state["events"]) if e["kind"] == "JOURNEY_CHECK_ROLLED")
        cold.journey_act(jid, state["revision"], actor, "check_settle", {"merit": 0})
        return roll["total"] - roll["natural_result"]

    assert check("before") == 6
    ButtonStore(tmp_path / "tabletop_buttons").save_attunement(project, [])
    state = service.journey_state(jid)
    service.journey_acquire_source(jid, state["revision"], actor, "tianxia.subpath.body.mantis_style",
                                   {"operation": "select"})
    assert check("after") == 5
