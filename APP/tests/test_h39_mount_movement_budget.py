"""A controlled mount's movement remains spent after its rider remounts."""

import copy
import json
import zipfile
from pathlib import Path

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET


RIDER_PROJECT = "h39-rider"
RIDER = FACTORY_ACTOR_PREFIX + RIDER_PROJECT


def _commit(table, match_id, state, candidate_id):
    menu = state["menu"]
    result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    return result["state"]


def _action(menu, label):
    match = next((option["candidate_id"] for group in menu["actions"] for option in group["options"]
                  if group["label"] == label or option["label"] == label), None)
    assert match, f"{label} not offered; actions: {[group['label'] for group in menu['actions']]}"
    return match


def test_remount_cannot_restore_controlled_mount_movement(tmp_path):
    sheet = copy.deepcopy(SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": ["tianxia.sphere.beastmastery"],
        "learned_talent_record_ids": [],
        "automatic_sphere_component_record_ids": ["BEASTMASTERY_BASE_RIDER_PACKAGE"],
    }
    folder = tmp_path / "portable_characters" / RIDER_PROJECT
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))

    root = Path(__file__).resolve().parents[1]
    combat = CombatService(root, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat.tabletop_maps.save({
        "display_name": "H39 mount movement budget", "width_squares": 24, "height_squares": 14,
        "walls": [], "starts": {"team1": [[4, 4]], "team2": [[20, 10]]},
    })
    match_id = combat.create_factory_match(
        project_ids=[RIDER_PROJECT], control_modes={RIDER: "MANUAL"},
        arena_id="battlefield:map.h39-mount-movement-budget", match_seed="H39-MOUNT-BUDGET",
    )["match_id"]

    state = table.state(match_id)
    for _ in range(8):
        if state["menu"].get("actor_id") == RIDER:
            break
        state = table.auto_step(match_id, state["last_sequence"])["state"]
    assert state["menu"]["actor_id"] == RIDER

    move = next(option for option in state["menu"]["moves"] if option["destination"] == {"x": 10, "y": 4})
    state = _commit(table, match_id, state, move["candidate_id"])
    state = table.state(match_id)
    state = _commit(table, match_id, state, _action(state["menu"], "Dismount"))
    state = table.state(match_id)
    state = _commit(table, match_id, state, _action(state["menu"], "Mount"))

    # Reload after committed table actions, then check the mount's complete same-turn budget.
    fresh = CombatService(root, tmp_path)._load_session(match_id)
    rider = fresh.engine.state.actors[RIDER]
    assert rider.movement_remaining_ft == 30, "Remount restored the 30 feet already spent with this mount"
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
