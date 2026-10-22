"""A mount carried by its rider resolves the terrain it is carried through (hunt 83 #1).

Ash Terrain: "a hostile creature moving more than 10 feet through it for the first time on a turn
makes a Constitution saving throw" (APP/combat/rules/terrain.json). Molten Terrain: "a creature
entering it for the first time on a turn ... makes a Dexterity saving throw". The Rider Package's
steed is a creature in its own right, so a mounted pair walking through either resolves it for both
halves. The mount's half of the move is recorded here, not patched at runtime.
"""

import pytest

from combat.ext import mounts
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.gate2_runtime_models import Position
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

RIDER = "actor:factory.mmx65-rider"
FOE = "actor:factory.mmx65-foe"


def _commit(table, match_id, label, *, move=None, square=None):
    """Take one table action through the ordinary button path, answering any reaction it opens.

    ``square`` is the cell a printed area is aimed at. Since SQUAREPICK1 (938f1759) the menu
    offers one "choose a square" row and the cell arrives as a second-stage map choice.
    """
    state = table.state(match_id)
    menu = state["menu"]
    candidate = move["candidate_id"] if move is not None else menu["end_turn"]
    answers = []
    for _ in range(16):
        result = table.act(match_id, candidate, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        choice = prompt.get("choice") or {}
        spatial = [option for option in choice.get("options", []) if option.get("cell")]
        if square is not None and spatial:
            wanted = [option for option in spatial if option["cell"].get("x") == square["x"]
                      and option["cell"].get("y") == square["y"]
                      and int(option["cell"].get("z") or 0) == int(square.get("z") or 0)]
            assert wanted, f"{square} is not one of the offered squares: {spatial[:6]}"
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [wanted[0]["id"]]})
            continue
        answer = {**prompt["context"], "selection": "USE"}
        if choice:
            answer["option_ids"] = [choice["options"][0]["id"]]
        answers.append(answer)
    assert result["status"] == "COMMITTED", result
    return result


def _fight(tmp_path, foe_talent, rider=True):
    """A fighter on one side, a foe owning ``foe_talent`` on the other, on an open yard. With ``rider``
    the fighter starts the fight on the Rider Package's steed."""
    rider_doc = sheet(["BEASTMASTERY_BASE_RIDER_PACKAGE"] if rider else [], cl=10)
    rider_doc["identity"]["display_name"] = "Rider"
    if rider:
        rider_doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = ["BEASTMASTERY_BASE_RIDER_PACKAGE"]
        rider_doc["spheres_and_talents"]["learned_talent_record_ids"] = []
    foe_doc = sheet([foe_talent], cl=10, dc=30)  # DC 30: neither the rider nor the warhorse passes
    foe_doc["identity"]["display_name"] = "Opponent"
    bundles = [compile_character(rider_doc, actor_id=RIDER, reaction_plan={"ask": True}),
               compile_character(foe_doc, actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    saved = combat.tabletop_maps.save({"display_name": "Carried terrain yard", "width_squares": 18,
                                       "height_squares": 12, "walls": [],
                                       "starts": {"team1": [[4, 4]], "team2": [[12, 4]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    match_id = combat._finish_factory_match(
        bundles, [RIDER, FOE], {RIDER: "team:factory", FOE: "team:opponents"},
        {RIDER: {"x": 4, "y": 4}, FOE: {"x": 12, "y": 4}}, arena, [RIDER], [FOE],
        control_modes={RIDER: "MANUAL", FOE: "MANUAL"}, match_seed="MMX65-" + foe_talent,
        display_name="Carried mount terrain", maximum_rounds=5)["match_id"]
    return combat, table, match_id


def _terrain_on_rider(tmp_path, foe_talent, ability_label, target):
    """The foe's terrain laid at ``target``, then the rider's turn, with the mount's id."""
    combat, table, match_id = _fight(tmp_path, foe_talent)
    for _ in range(6):
        if table.state(match_id)["menu"]["actor_id"] == FOE:
            break
        _commit(table, match_id, "end")
    group = next(g for g in table.state(match_id)["menu"]["actions"] if g["label"] == ability_label)
    # SQUAREPICK1 (938f1759): the area is aimed on the table, so the cell is a second-stage
    # map choice rather than one menu row per destination.
    _commit(table, match_id, ability_label, move=group["options"][0], square=target)
    for _ in range(6):
        if table.state(match_id)["menu"]["actor_id"] == RIDER:
            break
        _commit(table, match_id, "end")
    engine = combat._load_session(match_id).engine
    mount = mounts.mount_of(engine, engine.state.actors[RIDER])
    assert mount is not None, "the Rider Package starts the fight mounted"
    return combat, table, match_id, engine, mount


def _walk_to(table, match_id, x, y):
    move = next(o for o in table.state(match_id)["menu"]["moves"] if o["destination"] == {"x": x, "y": y})
    _commit(table, match_id, "move", move=move)
    return move


def _through(engine, since, moment, who):
    return [event for event in engine.events if event.sequence > since and event.event_type == "PASSIVE_TRIGGERED"
            and event.payload.get("moment") == moment and who in (event.target_ids or ())]


def test_carried_mount_walks_the_riders_route_through_ash_terrain_and_saves(tmp_path):
    """A mount carried fifteen feet through hostile Ash Terrain makes the save its rider makes.

    (4, 4) to (7, 4) is three five-foot squares, fifteen physical feet (the thirty the earlier
    report claimed is the difficult-terrain *cost* of the same walk, not its length)."""
    combat, table, match_id, engine, mount = _terrain_on_rider(
        tmp_path, "ASH_BASE_ASHFALL", "Ashfall", {"x": 7, "y": 4})
    since = engine.state.event_sequence
    _walk_to(table, match_id, 7, 4)
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    engine = reloaded.engine

    carried = [e for e in engine.events if e.sequence > since and e.event_type == "MOVEMENT_COMMITTED"
               and e.actor_id == mount.entity_id]
    assert len(carried) == 1, carried
    route = [(p["x"], p["y"]) for p in carried[0].payload["path"]]
    assert route == [(4, 4), (5, 4), (6, 4), (7, 4)], \
        f"the mount walked the rider's route square by square, not one hop: {route}"
    assert carried[0].payload.get("forced") is not True, \
        "a mount walking where its rider directed it moved by choice"

    assert _through(engine, since, "move_through", RIDER), "the rider resolved the terrain"
    assert _through(engine, since, "move_through", mount.entity_id), \
        "the mount was carried through the same fifteen feet and never resolved the terrain"
    saves = [e for e in engine.events if e.sequence > since and e.event_type == "SAVE_ROLLED"
             and e.actor_id in (RIDER, mount.entity_id)]
    assert {e.actor_id for e in saves} == {RIDER, mount.entity_id}, saves
    denied = [e for e in engine.events if e.sequence > since and e.event_type == "CONDITION_APPLIED"
              and "reaction_denied" in str(e.payload.get("condition_id"))]
    denied_targets = {target for e in denied for target in (e.target_ids or ())}
    assert denied_targets >= {RIDER, mount.entity_id}, \
        "Ash Terrain's failed Constitution save denies Reactions to the creature that walked through it"
    engine._assert_invariants()
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_carried_mount_at_exactly_ten_feet_of_ash_terrain_makes_no_save(tmp_path):
    """"more than 10 feet" is not "ten feet": the boundary is the ten-foot walk, and a pair
    carried two squares into the ash asks nothing.  The walk has to be the boundary itself --
    an earlier version of this test moved only one square (five feet) and so could not have
    failed however the threshold was read."""
    combat, table, match_id, engine, mount = _terrain_on_rider(
        tmp_path, "ASH_BASE_ASHFALL", "Ashfall", {"x": 7, "y": 4})
    since = engine.state.event_sequence
    _walk_to(table, match_id, 6, 4)  # exactly ten feet, all of it inside the area
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    engine = reloaded.engine
    assert engine.state.actors[mount.entity_id].position == Position(x=6, y=4), \
        "the pair really did walk the full ten feet"
    assert not _through(engine, since, "move_through", mount.entity_id), \
        "ten feet is not more than ten feet, so the mount's carry asks no save"
    assert not _through(engine, since, "move_through", RIDER), \
        "and the rider is not asked either: both halves read the same ten feet"
    engine._assert_invariants()
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_carried_mount_entering_molten_terrain_takes_damage_and_survives_reload(tmp_path):
    """The named hunt 83 case: a mount carried into Molten Terrain resolves it, half damage on the failed save."""
    combat, table, match_id, engine, mount = _terrain_on_rider(
        tmp_path, "TAL_MAGMA_LAVA_BURST", "Lava Burst", {"x": 9, "y": 4})
    since = engine.state.event_sequence
    before = {actor_id: combat._load_session(match_id).engine.state.actors[actor_id].current_hp
              for actor_id in (RIDER, mount.entity_id)}
    _walk_to(table, match_id, 6, 4)

    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    engine = reloaded.engine
    assert engine.state.actors[mount.entity_id].position == Position(x=6, y=4)
    assert mounts.mount_of(engine, engine.state.actors[RIDER]) is engine.state.actors[mount.entity_id], \
        "the pair is still mounted after the terrain resolves"
    entered = [e for e in engine.events if e.sequence > since and e.event_type == "SAVE_ROLLED"
               and e.actor_id in (RIDER, mount.entity_id)]
    assert {e.actor_id for e in entered} == {RIDER, mount.entity_id}, \
        "the Rider Package's steed halves damage on a failed save; it does not skip the save"
    for actor_id, hp in before.items():
        assert engine.state.actors[actor_id].current_hp < hp, f"{actor_id} walked into the lava unscathed"
    engine._assert_invariants()
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_a_fighter_who_owns_no_mount_resolves_the_terrain_exactly_as_before(tmp_path):
    """No mount, no new behaviour: a lone fighter walked through the same ash still saves once."""
    combat, table, match_id = _fight(tmp_path, "ASH_BASE_ASHFALL", rider=False)
    for _ in range(6):
        if table.state(match_id)["menu"]["actor_id"] == FOE:
            break
        _commit(table, match_id, "end")
    group = next(g for g in table.state(match_id)["menu"]["actions"] if g["label"] == "Ashfall")
    _commit(table, match_id, "Ashfall", move=group["options"][0], square={"x": 7, "y": 4})
    for _ in range(6):
        if table.state(match_id)["menu"]["actor_id"] == RIDER:
            break
        _commit(table, match_id, "end")
    since = combat._load_session(match_id).engine.state.event_sequence
    _walk_to(table, match_id, 7, 4)

    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    engine = reloaded.engine
    assert mounts.mount_of(engine, engine.state.actors[RIDER]) is None, "this fighter never mounted"
    assert [[(p["x"], p["y"]) for p in e.payload["path"]]
            for e in engine.events if e.sequence > since and e.event_type == "MOVEMENT_COMMITTED"
            and e.actor_id == RIDER] == [[(4, 4), (5, 4), (6, 4), (7, 4)]]
    assert len(_through(engine, since, "move_through", RIDER)) == 1, \
        "one walk through the ash resolves the terrain once, as before"
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"
