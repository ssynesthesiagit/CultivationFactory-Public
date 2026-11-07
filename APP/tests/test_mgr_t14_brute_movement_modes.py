"""Native grip/size contests and existing movement stay usable after rebuilding Disarm."""
import pytest

from combat.ext.brute_shove import MANEUVERS
from combat.ext.creature_passage import NAMED
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle, turn
from tests.cw2_service_support import add_action, seal
from tests.test_mgr_t14_brute_disarm import KIT, pick, contest, prepare
from tests.h1_support import sheet


def size_sheet(size):
    doc = sheet([], kit=KIT)
    # The native growth effect cannot shrink Medium to Small. A Small creature
    # must have Small size on its actual character sheet before compilation.
    doc["identity"]["size"] = "Small" if size == "Small" else "Medium"
    return doc


@pytest.mark.parametrize("size,mode", [("Small", "DISADVANTAGE"), ("Medium", "NORMAL"), ("Large", "ADVANTAGE")])
def test_disarm_defender_size_modes_are_relative_categories(tmp_path, size, mode):
    def setup(bundles):
        prepare(False)(bundles)
        add_action(bundles[2], "Set defender size", [{"type": "size_change", "size": size,
            "applies_to": "self", "expires_on": "UNTIL_REMOVED"}], target="SELF")
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, ally_position={"x": 1, "y": 6}, bundle_transform=setup,
        foe_sheet=size_sheet(size))
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Set defender size").candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    from combat.dynamic_size import current_category
    assert current_category(before, before.state.actors[FOE]) == size
    settle(table, mid, pick(before))
    result = contest(reload(tmp_path, mid))
    assert result["target"]["mode"] == mode
    assert result["actor"]["mode"] == "NORMAL"


@pytest.mark.parametrize("hands,mode", [(1, "NORMAL"), (2, "DISADVANTAGE")])
def test_disarm_actual_grip_occupancy_controls_attack_mode(tmp_path, hands, mode):
    from combat.ext.scoundrel_riders import held_possessions
    from combat.ext.hand_occupancy import occupancy
    # Paired Emei Piercers physically occupy both hands; the ordinary Dao rests
    # in one. Use actual native equipment, not inferred Two-Handed attack needs.
    weapon = "emei_ci" if hands == 2 else "dao"
    single = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon." + weapon, "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=single,
        foe_position={"x": 4, "y": 5}, bundle_transform=prepare(False))
    e = reload(tmp_path, mid)
    item = held_possessions(e, e.state.actors[FOE])[0]
    assert sum("weapon:" + item["weapon_action"] in tokens
               for tokens in occupancy(e, e.state.actors[FOE]).values()) == hands
    settle(table, mid, pick(e))
    assert contest(reload(tmp_path, mid))["actor"]["mode"] == mode


@pytest.mark.parametrize("bonus", [False, True])
def test_existing_overrun_real_move_once_double_cost_free_end_and_expiry(tmp_path, bonus):
    def setup(bundles):
        bundles[0]["skills"] = {"Athletics": 100}
        bundles[2]["skills"] = {"Athletics": -100}
        for bundle in bundles:
            seal(bundle)
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, ally_position={"x": 1, "y": 6}, bundle_transform=setup)
    before = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, "Overrun (Bonus Action)" if bonus else "Overrun", target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].action_available is bonus
    assert e.state.actors[OWNER].bonus_action_available is (not bonus)
    assert e.state.actors[FOE].current_hp == before.state.actors[FOE].current_hp
    assert any(c.condition_id == NAMED for c in e.state.actors[OWNER].conditions.values())
    assert not any(c.kind.value == "MOVE" and c.destination == e.state.actors[FOE].position
                   for c in e.legal_candidates())
    settle(table, mid, next(c.candidate_id for c in e.legal_candidates()
                           if c.kind.value == "MOVE" and (c.destination.x, c.destination.y) == (3, 5)))
    from combat.movement_routes import explicit_candidate, parse_waypoints
    e = reload(tmp_path, mid)
    movement = e.state.actors[OWNER].movement_remaining_ft
    path = [{"x": x, "y": 5} for x in (3, 4, 5)]
    move = explicit_candidate(e, OWNER, parse_waypoints(path))
    menu = table.state(mid)["menu"]
    result = table.commit_move_path(mid, move.candidate_id, menu["decision_id"], menu["state_version"], OWNER, path)
    assert result["status"] == "COMMITTED", result
    e = reload(tmp_path, mid)
    assert (e.state.actors[OWNER].position.x, e.state.actors[OWNER].position.y) == (5, 5)
    assert movement - e.state.actors[OWNER].movement_remaining_ft == 15
    from combat.ext.creature_passage import named_through
    assert named_through(e, e.state.actors[OWNER], e.state.actors[FOE]) is None
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert not any(c.condition_id == NAMED for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())


def test_existing_shove_aside_prompts_for_non_away_legal_destination(tmp_path):
    def setup(bundles):
        bundles[2]["skills"] = {"Athletics": -100, "Acrobatics": -100}
        for bundle in bundles:
            seal(bundle)
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, ally_position={"x": 1, "y": 6}, bundle_transform=setup)
    cid = candidate(combat, mid, "Shove Aside", target=FOE).candidate_id
    prompts = settle(table, mid, cid, {"choice:needle.shove_aside": "cell:2,5",
                                     "choice:needle.brute_contest_skill": "Acrobatics"})
    e = reload(tmp_path, mid)
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) == (2, 5)
    check = next(event.payload for event in reversed(e.events)
                 if event.event_type == "CHECK_ROLLED" and event.payload.get("contest") == "shove")
    assert check["actor"]["mode"] == "DISADVANTAGE"
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.shove_aside")
    offered = {o["id"] for o in prompt["choice"]["options"]}
    assert "cell:2,5" in offered and "cell:4,5" not in offered and "cell:3,6" not in offered


@pytest.mark.parametrize("size,mode", [("Small", "ADVANTAGE"), ("Medium", "NORMAL"), ("Large", "DISADVANTAGE")])
def test_overrun_actor_size_modes_include_small_vs_medium(tmp_path, size, mode):
    def setup(bundles):
        bundles[2]["skills"] = {"Athletics": 100}
        add_action(bundles[2], "Set defender size", [{"type": "size_change", "size": size,
            "applies_to": "self", "expires_on": "UNTIL_REMOVED"}], target="SELF")
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, ally_position={"x": 1, "y": 6}, bundle_transform=setup,
        foe_sheet=size_sheet(size))
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Set defender size").candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    from combat.dynamic_size import current_category
    assert current_category(before, before.state.actors[FOE]) == size
    settle(table, mid, candidate(combat, mid, "Overrun", target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    result = next(event.payload for event in reversed(e.events)
                  if event.event_type == "CHECK_ROLLED" and event.payload.get("contest") == "overrun")
    assert result["actor"]["mode"] == mode
    assert result["target"]["mode"] == "NORMAL"
    assert result["success"] is False
    assert not any(c.condition_id == NAMED for c in e.state.actors[OWNER].conditions.values())
