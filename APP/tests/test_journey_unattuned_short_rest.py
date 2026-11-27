"""Short Rest uses the carried HP pair after a Constitution amulet is unattuned."""

import pytest

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.body_refining_support import QI, ROOT, install, sheet


def test_short_rest_after_unattuning_constitution_amulet_replays(tmp_path):
    hero, foe = "abcdef12", "abcdef34"
    aid, bid = (FACTORY_ACTOR_PREFIX + project for project in (hero, foe))
    wearer = sheet(cl=10, paths=[QI])
    wearer["identity"]["display_name"] = "Amulet wearer"
    wearer["ability_scores_and_statistics"]["hit_points"] = {"maximum": 60, "build_state_current": 55}
    amulet = {
        "name": "Amulet of Vital Health (+2)", "body_slot": "Neck", "attunement_slots": 1,
        "ability_enhancement": {"ability": "CON", "bonus": 2},
    }
    wearer["equipment"] = [{"starting_kit": {
        "items": [], "resolved_treasure_purchases": {"wondrous": [amulet]},
    }}]
    install(tmp_path, wearer, pid=hero)
    install(tmp_path, sheet(paths=[QI]), pid=foe)

    def cold():
        return CombatService(ROOT, tmp_path)

    def hp(state):
        snapshot = state["actors"][aid]["encounter_snapshot"]
        return snapshot["current_hp"], snapshot["maximum_hp"]

    combat = cold()
    combat.tabletop_maps.save({"map_id": "rest-clearing", "display_name": "Rest clearing",
        "width_squares": 10, "height_squares": 10, "objects": [], "starts": {"team1": [[2, 2]]}})
    scene = {"arena_id": "battlefield:map.rest-clearing",
             "positions": {aid: {"x": 2, "y": 2}, bid: {"x": 7, "y": 7}},
             "base_paces": {aid: 1800, bid: 1800}}
    journey = combat.create_journey(project_ids=[hero, foe], **scene)
    jid = journey["journey_id"]
    fight = combat.journey_start_combat(jid, journey["revision"], {aid: "team:a", bid: "team:b"},
                                         maximum_rounds=1)
    mid = fight["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(6):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        menu = table.state(mid)["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    else:
        pytest.fail("The one-round encounter did not finish")

    resumed = combat.journey_resume(jid, combat.journey_state(jid)["revision"])
    assert hp(resumed) == (65, 70)
    combat.journey_act(jid, resumed["revision"], aid, "finish")
    ButtonStore(tmp_path / "tabletop_buttons").save_attunement(hero, [])

    following = cold().create_journey(project_ids=[hero, foe], **scene)
    jid = following["journey_id"]
    assert hp(following) == (55, 60)
    rested = cold().journey_act(jid, following["revision"], aid, "short_rest")
    assert rested["seconds"] == following["seconds"] + 3600
    assert any(event["kind"] == "ENCOUNTER_SHORT_REST" for event in rested["events"])
    assert hp(rested) == hp(cold().journey_state(jid)) == (55, 60)
    # Replay verifies the full saved state, including the restored HP pair.
    assert cold().journey_replay(jid)["status"] == "PASS"
