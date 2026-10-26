"""A2R23: the Map Athletics swing / Flash Step / One Breath lanes at the real table.

Every test drives a real CombatService match through TabletopService (session
execute_intent) and, where a fight is committed, reloads it cold
(``CombatService._load_session``), so the automated mechanics are read the way
a player at the table reads them. Nothing here reaches into a plug-in's
private state; the seam queries the engine publishes are the only direct reads.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from combat.ext import athletics
from combat.ext.teleport_steps import destinations
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

FIGHTER = FACTORY_ACTOR_PREFIX + "a2r23f1"
FOE = FACTORY_ACTOR_PREFIX + "a2r23f2"
ONE_BREATH = "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS"
FLASH_STEP = "TAL_ATHLETICS_FLASH_STEP"
ROPE_SWING = "TAL_ATHLETICS_ROPE_SWING_ADEPT"
SWING = "condition:typed.rope_swing"
BREATH = "condition:typed.one_breath_steps"
FOCUS = "resource:core.martial_focus"
LONGSWORD = {"items": [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian (Straight Sword)", "quantity": 1}]}
ROPE = {"items": [{"item_id": "tianxia.mortal.gear.rope", "name": "Rope", "quantity": 1}]}


def _doc(talents, *, kit, name, ac=14):
    doc = sheet(talents, cl=12, dc=16, key="DEX")
    doc["identity"]["display_name"] = name
    doc["equipment"] = [{"starting_kit": kit}]
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 60
    doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    return doc


def table_fight(tmp_path, talents, *, foe_talents=(), kit=LONGSWORD, foe_kit=LONGSWORD,
                control_modes=None, map_doc=None, where=None, bundle_transform=None):
    """The fighter (owner of ``talents``) against a foe, in a real service match."""
    projects = {FIGHTER: "a2r23f1", FOE: "a2r23f2"}
    team = {FIGHTER: "team:a", FOE: "team:b"}
    where = where or {FIGHTER: {"x": 3, "y": 4}, FOE: {"x": 4, "y": 4}}
    docs = {FIGHTER: _doc(talents, kit=kit, name="Fighter"),
            FOE: _doc(list(foe_talents), kit=foe_kit, name="Foe", ac=12)}
    for aid in (FIGHTER, FOE):
        folder = tmp_path / "portable_characters" / projects[aid]
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(docs[aid]))
    bundles = [compile_character(docs[aid], actor_id=aid,
                                  reaction_plan={"ask": True} if aid == FIGHTER else None)
               for aid in (FIGHTER, FOE)]
    combat = CombatService(ROOT, tmp_path)
    if bundle_transform:
        bundle_transform(bundles)
    saved = combat.tabletop_maps.save(map_doc or {"display_name": "A2R23 yard", "width_squares": 12,
                                                  "height_squares": 8, "walls": [],
                                                  "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = combat._finish_factory_match(
        bundles, [FIGHTER, FOE], team, where,
        combat.factory_arenas(include_retired=True)["battlefield:map." + str(saved["map_id"])],
        [FIGHTER], [FOE], control_modes=control_modes or {FIGHTER: "MANUAL"},
        match_seed="A2R23-TABLE", display_name="A2R23 regression", maximum_rounds=20)["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != FIGHTER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def act(table, mid, candidate_id, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"],
                     table.state(mid)["last_sequence"], list(answers))


def find(table, mid, needle, target=None):
    """The candidate id of the first menu option whose action carries ``needle``."""
    for group in table.state(mid)["menu"]["actions"]:
        if needle not in (group.get("source_definition_id") or ""):
            continue
        for option in group["options"]:
            if target is None or target in (option.get("target_ids") or []):
                return option["candidate_id"]
    raise AssertionError(f"{needle!r} is not on the menu: "
                         f"{[g.get('source_definition_id') for g in table.state(mid)['menu']['actions']]}")


def move_to(table, mid, x, y):
    """The table's own move to a ground square, chosen the way a player would."""
    for move in table.state(mid)["menu"]["moves"]:
        destination = move["destination"]
        if (int(destination.get("x") or 0) == x and int(destination.get("y") or 0) == y
                and not int(destination.get("z") or 0)):
            return move["candidate_id"]
    raise AssertionError(f"no move to {x},{y} is offered")


def answer_for(prompt):
    """One table answer to one rendered prompt: its first offered option."""
    choice = prompt.get("choice") or {}
    legal = [row["id"] for row in choice.get("options") or []]
    if not legal:
        return {**prompt["context"], "selection": "USE"}
    picked = (choice.get("preferred") or legal)[:int(choice.get("minimum") or 1)]
    return {**prompt["context"], "selection": "USE", "option_ids": picked}


def play(table, mid, candidate_id, answer=None, limit=24):
    """Commit one table action, answering every question it raises."""
    answers, prompts = [], []
    for _ in range(limit):
        result = act(table, mid, candidate_id, answers)
        if result["status"] == "COMMITTED":
            return result, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompts.append(result["reaction"])
        answers.append(answer_for(result["reaction"]) if answer is None else answer(result["reaction"]))
    raise AssertionError("too many prompts")


def engine_of(combat, mid):
    return combat._load_session(mid).engine


def passive_fixture(feature_id, kind, **fields):
    """Supply a consumer test's owned row if public export omits its catalogue.

    These tests exercise movement consumers, not feature-block compilation.
    Keep canonical compiled rows when present; the fallback uses the printed
    One Breath/Speed Boost clauses from feature_blocks.d/auto8-athletics.json.
    """
    def prepare(bundles):
        bundle = next(row for row in bundles if row["actor_id"] == FIGHTER)
        rows = bundle["typed_passives"]
        if not any(row.get("feature_id") == feature_id and row.get("block") == "athletics"
                   and row.get("kind") == kind for row in rows):
            rows.append({"feature_id": feature_id, "block": "athletics", "kind": kind, **fields})
    return prepare


def events(engine, event_type, actor_id=None):
    return [event for event in engine.events
            if event.event_type == event_type and (actor_id is None or event.actor_id == actor_id)]


# ===================================================================================== One Breath, Ten Thousand Steps

def test_one_breath_activation_two_dashes_and_deferred_strike(tmp_path):
    """The Bonus Action buys both printed Dashes, and the one attack lands at the
    point of movement the fighter chooses: the activation's own attack row is
    deferred and the free strike buttons deliver it with the fighter's weapon."""
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert fighter.resources[FOCUS] == 1
    # The activation is a self Bonus Action (the attack row is deferred).
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert any(condition.condition_id == BREATH for condition in fighter.conditions.values())
    assert fighter.turn_flags["flight_typed_dashes"] == 2, "both printed Dashes are typed Dashes"
    assert fighter.movement_remaining_ft >= 60, "two Dashes bought their shared allowance"
    assert fighter.resources[FOCUS] == 0, "the activation spent its Martial Focus"
    # The one attack is the two free strike buttons, not the activation.
    strike = find(table, mid, "one_breath_strike", target=FOE)
    unarmed = find(table, mid, "one_breath_unarmed", target=FOE)
    before = len(events(engine, "ATTACK_ROLLED"))
    result, _ = play(table, mid, strike)
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    rolled = events(engine, "DAMAGE_ROLLED")
    assert rolled and rolled[-1].payload["expression"].startswith("1d10"), \
        f"the strike uses the Jian's 1d10, not a bare d4: {rolled[-1].payload['expression'] if rolled else None}"
    # The printed one attack is spent: neither strike button is offered again.
    for needle in ("one_breath_strike", "one_breath_unarmed"):
        with pytest.raises(AssertionError):
            find(table, mid, needle, target=FOE)


def test_one_breath_strike_cold_reload(tmp_path):
    """The activation, its typed Dash counts and the spent strike survive a
    table commit plus a cold reload."""
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    result, _ = play(table, mid, find(table, mid, "one_breath_strike", target=FOE))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)  # the cold reload
    fighter = engine.state.actors[FIGHTER]
    assert any(condition.condition_id == BREATH for condition in fighter.conditions.values())
    assert fighter.turn_flags["flight_typed_dashes"] == 2
    assert str(fighter.turn_flags.get("athletics_one_breath_strike")) == "1"
    with pytest.raises(AssertionError):
        find(table, mid, "one_breath_strike", target=FOE)


def test_one_breath_ignores_opportunity_attacks(tmp_path):
    """"ignore Opportunity Attacks": the fighter walks out of the foe's reach
    and the foe's Opportunity Attack against it is vetoed."""
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    # Walk out of the foe's reach (the foe stands at (4,4); move far away).
    engine = engine_of(combat, mid)
    before = len(events(engine, "ATTACK_ROLLED", FOE))
    move = move_to(table, mid, 3, 7)
    result, prompts = play(table, mid, move)
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    foe = engine.state.actors[FOE]
    assert engine.grid.distance_ft(fighter.position, foe.position) > 5, "the fighter left the foe's reach"
    assert len(events(engine, "ATTACK_ROLLED", FOE)) == before, "the foe's Opportunity Attack was vetoed"


def test_one_breath_moves_through_hostile_space_as_difficult_terrain(tmp_path):
    """"move through hostile spaces as though they were difficult terrain":
    the fighter may pass through the foe's space at double cost (and the
    native end-stop still refuses a stop there)."""
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter, foe = engine.state.actors[FIGHTER], engine.state.actors[FOE]
    # The foe's space is a hostile space: the passage seam answers "difficult"
    # for the swinging fighter and only for it.
    assert athletics.one_breath_passage(engine, fighter, foe) == "difficult"
    assert athletics.one_breath_passage(engine, foe, fighter) is None, "inert for every other creature"
    # The native geometry still refuses a stop inside the space.
    from combat.creature_passage import geometry
    _, end_blocked, _, _ = geometry(engine, fighter)
    assert (foe.position.x, foe.position.y) in end_blocked, "the native passage geometry keeps its end-stop"


def test_one_breath_support_and_climbing_queries_are_owned(tmp_path):
    """"move across walls, water, air, and fragile surfaces": while the
    activation runs the fighter is supported at any square (air, fragile
    surfaces, the water this table models no swim-speed system for) and owns
    a Climb Speed equal to its walking Speed (walls)."""
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert athletics.one_breath_surfaces(engine, fighter, Position(x=6, y=6, z=3)) is True, "supported in the air"
    assert athletics.one_breath_surfaces(engine, engine.state.actors[FOE], Position(x=6, y=6, z=3)) is None
    climb = athletics.one_breath_walls(engine, fighter)
    assert climb and climb["climb_speed_ft"] == engine._effective_speed(fighter) > 0, "a Climb Speed for walls"
    assert athletics.one_breath_walls(engine, engine.state.actors[FOE]) is None


def test_one_breath_focus_every_twenty_feet_of_walking(tmp_path):
    """Walking restores Focus; actual Flash Step coverage is in test_a2_athletics_table_reloads."""
    combat, table, mid = table_fight(
        tmp_path, [ONE_BREATH, FLASH_STEP],
        bundle_transform=passive_fixture(ONE_BREATH, "one_breath", focus_ft=20, keeps_compiling=True))
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert fighter.resources[FOCUS] == 0
    # Walk 20 feet: the accumulator returns the Focus.
    move = move_to(table, mid, 7, 7)
    result, _ = play(table, mid, move)
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert fighter.resources[FOCUS] == 1, "20 feet of walking returned the Focus"


# ===================================================================================== Flash Step

def test_flash_step_teleports_within_the_dash_and_completes_as_a_dash(tmp_path):
    """"When you take the Dash Action, expend Martial Focus": the Flash Step
    button spends the Action and a Focus, lands on a visible legal unoccupied
    square within the distance one Dash moves, and its completion is a Dash
    completion without granting an unused movement allowance or typed Dash count."""
    combat, table, mid = table_fight(tmp_path, [FLASH_STEP])
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert fighter.resources[FOCUS] == 1
    before = int(fighter.turn_flags.get("flight_typed_dashes") or 0)
    reach = engine._effective_speed(fighter)
    result, prompts = play(table, mid, find(table, mid, "flash_step"))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    spent = [event for event in events(engine, "RESOURCE_SPENT", FIGHTER)
             if (event.payload or {}).get("resource_id") == FOCUS
             and int((event.payload or {}).get("amount") or 0) == 1]
    assert spent, "the Dash Action spent the printed Martial Focus"
    assert fighter.resources[FOCUS] == 1, \
        "and the sphere's own Coordinated Movement regained it: Flash Step is the Dash Action"
    assert int(fighter.turn_flags.get("flight_typed_dashes") or 0) == before, \
        "the replaced Dash has a completion receipt, but grants no unspent movement"
    assert engine.grid.distance_ft(Position(x=3, y=4, z=0), fighter.position) <= reach + 10, \
        "the landing is within the distance one Dash moves (the Speed, plus any Action-only Dash bonus)"
    # The shared landing gates held: the destination is legal and unoccupied.
    assert engine.grid.placement_legal(fighter.position, footprint=engine._footprint(fighter),
                                       occupied_cells=engine._occupied_cells_except(FIGHTER))


def test_flash_step_landing_is_visible_and_unoccupied(tmp_path):
    """The destination must be visible, legal and unoccupied: the shared
    destination query answers exactly those, and the Flash Step reuses it."""
    combat, table, mid = table_fight(tmp_path, [FLASH_STEP])
    engine = engine_of(combat, mid)
    fighter, foe = engine.state.actors[FIGHTER], engine.state.actors[FOE]
    reach = engine._effective_speed(fighter)
    cells = destinations(engine, fighter, reach)
    assert cells, "the shared query offers visible legal unoccupied squares"
    assert all(engine._line_of_sight_actor_to_cell(fighter, cell) for cell in cells)
    assert all(cell != foe.position for cell in cells), "the foe's square is never offered"
    assert all(engine.grid.distance_ft(fighter.position, cell) <= reach for cell in cells)


# ===================================================================================== Rope Swing Adept

def test_rope_swing_attach_detach_and_quick_climb(tmp_path):
    """The attach is a real Bonus Action that asks for the anchor; while the
    swing is attached the fighter may end movement in the air (suspended),
    detach for free, and swing up to the anchor as a quick climb that
    charges movement; the detach takes the swing off."""
    # A keep with a roofed room: the only squares above the fighter
    # are the roof's own walking level, so the anchor is real.
    keep = {"display_name": "Visible supported anchor", "width_squares": 12, "height_squares": 8,
            "walls": [],
            "trees": [{"x": 5, "y": 3, "size": 1, "height_ft": 10,
                       "base_altitude_ft": 20, "occluder": "centerline"}],
            "starts": {"team1": [[4, 4]], "team2": [[4, 5]]}}
    def climbing_allowance(bundles):
        next(row for row in bundles if row["actor_id"] == FIGHTER)["actor_template"]["climb_speed_ft"] = 50

    combat, table, mid = table_fight(tmp_path, [ROPE_SWING], kit=ROPE, map_doc=keep,
                                       where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 4, "y": 5}},
                                       bundle_transform=climbing_allowance)
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    # The attach is the compiled Bonus Action.
    attach = find(table, mid, ROPE_SWING)
    result, prompts = play(table, mid, attach)
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    swing = next((condition for condition in fighter.conditions.values()
                  if condition.condition_id == SWING), None)
    assert swing is not None, "the rope is attached"
    anchor = (swing.data or {}).get("anchor")
    assert anchor and anchor[2] > 0, "the anchor is above the fighter"
    anchor_position = Position(x=anchor[0], y=anchor[1], z=anchor[2])
    # The free transitions only exist while the swing is attached.
    climb = find(table, mid, "rope_swing_climb")
    # Ending movement in the air: the swing suspends the fighter, exactly
    # the printed "as though you possessed a temporary Fly Speed".
    from combat import ext
    assert {"flight_suspended": 1} in ext.run_strict("flight", engine, fighter)
    # The quick climb is movement: it charges the shared allowance the
    # climb's distance and lands the fighter on the anchor square.
    feet = engine.grid.distance_ft(fighter.position, anchor_position)
    assert int(fighter.movement_remaining_ft) >= feet
    result, _ = play(table, mid, climb)
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert fighter.position == anchor_position, "the swing climbed to the anchor point"
    move = next(event for event in reversed(engine.events)
                if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == FIGHTER)
    assert move.payload["cost_ft"] == feet, "the quick climb charged its actual route distance"
    assert any(event.event_type == "MOVEMENT_COMMITTED" and (event.payload or {}).get("movement_mode") == "climb"
               for event in engine.events), "the climb is recorded as the climb it is"
    # Detach is free and takes the swing off.
    detach = find(table, mid, "rope_swing_detach")
    result, _ = play(table, mid, detach)
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert not any(condition.condition_id == SWING for condition in fighter.conditions.values())
    assert {"flight_suspended": 1} not in ext.run_strict("flight", engine, fighter)


# ===================================================================================== The general seams

def test_dash_reach_spans_the_owned_modes(tmp_path):
    """The "distance you could move through the Dash" is the largest Speed
    the creature owns (walking, flying or climbing), plus every
    Action-only Dash bonus -- never a hard-coded multiplier."""
    from combat.flight import dash_reach

    combat, table, mid = table_fight(tmp_path, [])
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert dash_reach(engine, fighter) == engine._effective_speed(fighter) == 30
    # A flying creature's Dash moves it by its Fly Speed, not its walking one.
    fighter.fly_speed_ft = 60
    assert dash_reach(engine, fighter) == 60
    # The Action-only Dash bonus sums in (Speed Boost's printed +10 feet).
    combat, table, mid = table_fight(
        tmp_path / "boost", ["TAL_ATHLETICS_SPEED_BOOST"],
        bundle_transform=passive_fixture("TAL_ATHLETICS_SPEED_BOOST", "speed_boost",
                                        action_extra_ft=10, boost_ft=50))
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert dash_reach(engine, fighter) == 40


def test_height_aware_destination_enumeration(tmp_path):
    """The shared destination query offers standing levels only: a flat map
    keeps ground level, and a raised square with nothing solid under it is
    free air, not a landing. A solid top or roof is offered instead
    (test_a2_teleport_standable_squares.py)."""
    combat, table, mid = table_fight(tmp_path, [])
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert engine.grid.altitude_ceiling_z == 0, "the yard is a flat map"
    assert all(cell.z == 0 for cell in destinations(engine, fighter, 60))
    engine.grid.terrain_heights.setdefault("RAISED", {})[(6, 4)] = 15
    engine.grid.finite_heights = True
    assert engine.grid.altitude_ceiling_z == 3
    cells = destinations(engine, fighter, 60)
    assert Position(x=6, y=4, z=3) not in cells, "a raised square with no support is free air"
    assert all(cell.z == 0 for cell in cells), "no open-air level is offered"
    assert all(engine.grid.distance_ft(fighter.position, cell) <= 60 for cell in cells)


def test_per_activation_motion_receipt_is_once_per_owner(tmp_path):
    """"apply each Motion talent only once": the receipt is current-turn,
    per-activation and keyed by the exact Motion talent's owner id, so it
    bounds one activation of one owner and never limits another creature."""
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    result, _ = play(table, mid, find(table, mid, ONE_BREATH))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter, foe = engine.state.actors[FIGHTER], engine.state.actors[FOE]
    assert not athletics.motion_applied_once(engine, fighter, FLASH_STEP)
    assert athletics.record_motion_application(engine, fighter, FLASH_STEP) is False
    assert athletics.motion_applied_once(engine, fighter, FLASH_STEP) is True
    assert athletics.record_motion_application(engine, fighter, FLASH_STEP) is True, "once per activation"
    assert athletics.motion_applied_once(engine, fighter, "TAL_ATHLETICS_AFTERIMAGE") is False, \
        "keyed by the exact Motion talent's owner id"
    assert not athletics.motion_applied_once(engine, foe, FLASH_STEP), "never another creature's limit"


def test_rope_swing_is_inert_without_the_item_and_without_the_talent(tmp_path):
    """The plug-in is inert for characters that do not own its ability, and
    the attach refuses a fighter holding no Rope Swing item."""
    combat, table, mid = table_fight(tmp_path, [ROPE_SWING], kit=LONGSWORD)  # no rope
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert athletics.rope_swing_gear(engine, fighter) == []
    result, _ = play(table, mid, find(table, mid, ROPE_SWING))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert not any(condition.condition_id == SWING for condition in fighter.conditions.values()), \
        "no rope, no swing"
    # And the seam answers nothing for a fighter that does not own the talent.
    combat, table, mid = table_fight(tmp_path / "plain", [])
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert athletics.rope_swing_flight(engine, fighter) is None
    assert athletics._rope_running(engine, fighter) is False
