"""Line Arrays placed at map edges commit and remain replayable after reload."""

import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet


OWNER = FACTORY_ACTOR_PREFIX + "h47-line-owner"
FOE = FACTORY_ACTOR_PREFIX + "h47-line-foe"
LINE_ARRAY = "tianxia.talent.formations.line_array"


@pytest.mark.parametrize("edge", [(2, 6), (3, 0)])
def test_line_array_edge_placement_commits_reloads_and_replays(tmp_path, edge):
    documents = [sheet([LINE_ARRAY], cl=17), sheet([], cl=17)]
    for actor_id, document in zip((OWNER, FOE), documents):
        folder = tmp_path / "portable_characters" / actor_id.rsplit(".", 1)[-1]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))

    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.save({
        "display_name": "H47 line edge test", "width_squares": 40, "height_squares": 20,
        "walls": [], "starts": {"team1": [[3, 6]], "team2": [[4, 6]]},
    })
    mid = combat._finish_factory_match(
        [compile_character(documents[0], actor_id=OWNER), compile_character(documents[1], actor_id=FOE)],
        [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas()["battlefield:map." + arena["map_id"]], [OWNER], [FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed=f"H47-LINE-{edge}",
        display_name="H47 line edge", maximum_rounds=10,
    )["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert _act(table, mid, "end")["status"] == "COMMITTED"

    state = table.state(mid)
    setup = next(o["candidate_id"] for group in state["menu"]["actions"]
                 if group["label"] == "Next array: shape it as a line" for o in group["options"])
    assert _act(table, mid, setup)["status"] == "COMMITTED"
    state = table.state(mid)
    placement = next(o["candidate_id"] for group in state["menu"]["actions"]
                     if group["label"] == "Combat Array: Killing Line (Cold)"
                     for o in group["options"] if o.get("destination") == {"x": edge[0], "y": edge[1]})
    assert _act(table, mid, placement)["status"] == "COMMITTED"

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"


def _act(table, mid, candidate_id):
    state = table.state(mid)
    menu = state["menu"]
    if candidate_id == "end":
        candidate_id = menu["end_turn"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])
