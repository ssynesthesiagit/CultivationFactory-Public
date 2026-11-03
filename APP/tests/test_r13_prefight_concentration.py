"""Unlimited concentration applies to the service's prefight selection at CL1."""
import copy
import json
import zipfile

from combat import concentration
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from tests.test_prefight import ROOT, SHEET


def test_two_concentrated_prefight_buffs_at_cl1_commit_and_reload(tmp_path):
    sheet = copy.deepcopy(SHEET)
    sheet["identity"]["cultivation_level"] = 1
    folder = tmp_path / "portable_characters" / "left"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    options = combat.factory_prefight_options("left")
    assert options["max_concentration"] == options["max"] == 2
    picks = [next(o["action_id"] for o in options["options"] if o["name"] == name)
             for name in ("Meld: Darkvision", "Meld: Clearsight")]
    owner = FACTORY_ACTOR_PREFIX + "left"
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[AN],
        control_modes={owner: "MANUAL", AN: "MANUAL"}, prefight={owner: picks},
        match_seed="R13-PREFIGHT")["match_id"]
    before = combat._load_session(mid)
    assert len(concentration.sources(before.engine.state.actors[owner])) == 2
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    hold = next(a for a in menu["actions"] if a["source_definition_id"] == "system:combat.hold_position")
    assert table.act(mid, hold["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    after = CombatService(ROOT, tmp_path)._load_session(mid)
    assert concentration.sources(after.engine.state.actors[owner]) == concentration.sources(before.engine.state.actors[owner])
    assert after.mechanical.replay()["status"] == "PASS"
