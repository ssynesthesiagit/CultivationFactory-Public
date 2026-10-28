"""Engine-integration proof for the owner's 2026-10-08 object catalog, through the real path the UI uses to run a
fight (the lead's addendum, recorded in /var/tmp/auto-audit/fix/SON198.notes: "make sure everything is tied into
the game engine as well"):

    editor-format map (combat.tabletop_maps.save, exactly what the map editor POSTs)
      -> a real fight (combat.gate5_service.CombatService.create_factory_match, the Factory playtest path
         the tabletop UI drives)
      -> real actions (combat.gate5_service.Gate4PersistentSession.mechanical.execute_intent, the same
         candidate/decision_id/state_version-checked call tabletop_service.TabletopService.act makes --
         *not* the bare engine's own .execute_intent, which skips the journal: see the probe in this file's
         own git history/report for why that distinction matters for a cold-reload proof)
      -> a cold reload (a brand new CombatService pointed at the same tmp_path, like
         tests/test_a11_save_recheck.py's own ``CombatService(ROOT, tmp_path)._load_session(mid)``)

one flag combination at a time: blocks+threshold (bronze_ding), blocks only (market_stall, destroyed),
threshold only (war_brazier, blocks=False), neither (prayer_wheel), structure+blocks (fence_section), the
engine's one openable kind both ways (door closed and open), map-painted Difficult Terrain (a real "Move"
candidate, MOVEMENT_COMMITTED.cost_ft doubled), and map-painted Simple Cover (Gate4ControllerEngine's own
_raw_cover_bonus_actor_to_actor, the function an attack roll's cover_bonus actually comes from).

Dice are forced the same way tests/test_sysv2_objects.py already established for this exact object/attack
system (13-19 is a hit that is never a critical; a natural 1 or 2 stays a clean miss): reused here, not
reinvented."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from combat import object_rules
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.test_factory_combat_compiler import SHEET
from tests.test_sysv2_objects import force_d20

ROOT = Path(__file__).resolve().parents[1]
LEFT = FACTORY_ACTOR_PREFIX + "left"
RIGHT = FACTORY_ACTOR_PREFIX + "right"
DIFFICULT_CELL = (6, 6)
COVER_CELL = (9, 2)

OBJECTS = [
    {"id": 1, "kind": "market_stall", "x": 8, "y": 4},                    # blocks, no threshold -- destroyed below
    {"id": 2, "kind": "bronze_ding", "x": 8, "y": 6},                     # blocks + threshold=5 (preset default)
    {"id": 3, "kind": "prayer_wheel", "x": 8, "y": 8},                    # neither flag
    {"id": 4, "kind": "war_brazier", "x": 8, "y": 10},                    # threshold=2, does not block
    {"id": 5, "kind": "fence_section", "x": 8, "y": 12},                  # structure + blocks
    {"id": 6, "kind": "door", "x": 8, "y": 14, "interaction": "simple_door", "door_open": 0, "door_locked": 0, "door_jammed": 0},
    {"id": 7, "kind": "door", "x": 12, "y": 14, "interaction": "simple_door", "door_open": 1, "door_locked": 0, "door_jammed": 0},
]


def _install(userdata: Path, project_id: str) -> None:
    folder = userdata / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(SHEET))


def start_fight(tmp_path):
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({
        "display_name": "SON198 Engine Yard", "width_squares": 20, "height_squares": 18,
        "starts": {"team1": [[3, 6]], "team2": [[17, 6]]},
        "terrain": [{"type": "DIFFICULT", "cells": [list(DIFFICULT_CELL)]},
                    {"type": "SIMPLE_COVER", "cells": [list(COVER_CELL)]}],
        "objects": OBJECTS,
    })
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[RIGHT],
                                       control_modes={LEFT: "MANUAL"}, arena_id=f"battlefield:map.{saved['map_id']}",
                                       match_seed="SON198-ENGINE")
    return combat, saved["map_id"], view["match_id"]


def advance_to_human(engine, session, cap=16):
    """End the AI's turns (never letting it wander off its start square) until it is the human's turn."""
    for _ in range(cap):
        if engine.state.current_actor_id == LEFT:
            return
        candidate = next(c for c in engine.legal_candidates()
                         if c.kind == CandidateKind.END_TURN and c.actor_id == engine.state.current_actor_id)
        run_candidate(engine, session, candidate.actor_id, candidate)
    raise AssertionError("the AI side never yielded the human's turn")


def run_candidate(engine, session, actor_id, candidate):
    before = len(engine.events)
    session.mechanical.execute_intent(ActionIntent(
        intent_id=f"son198:{candidate.kind}:{before}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
        target_ids=candidate.target_ids or (), destination=candidate.destination))
    return engine.events[before:]


def end_turn(engine, session):
    candidate = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN and c.actor_id == LEFT)
    run_candidate(engine, session, LEFT, candidate)


def attack_object(engine, session, object_id):
    """One "Attack an object" (the plain weapon swing, not a rider-cost variant) against ``object_id``,
    assuming the human's turn is already current. Returns the events it made."""
    candidate = next(c for c in engine.legal_candidates()
                     if c.actor_id == LEFT and object_id in (c.target_ids or ())
                     and "Attack an object" in c.display_name and "+" not in c.display_name)
    return run_candidate(engine, session, LEFT, candidate)


def destroy_object(engine, session, object_id, tries=8):
    force_d20(engine, 13, 19)
    move_adjacent_to(engine, session, object_id)
    for _ in range(tries):
        advance_to_human(engine, session)
        attack_object(engine, session, object_id)
        destroyed = engine.state.objects[object_id].destroyed
        end_turn(engine, session)
        if destroyed:
            return
    raise AssertionError(f"{object_id} was not destroyed in {tries} attacks")


def damage_object_once(engine, session, object_id, tries=8):
    """One hit that actually costs hit points -- a forced-hit attack roll still rolls its own damage dice, and a
    low roll can land under a Damage Threshold (correct per combat/object_rules.work_out); retried, never
    assumed, the same way destroy_object already retries for a full kill."""
    force_d20(engine, 13, 19)
    move_adjacent_to(engine, session, object_id)
    before_hp = engine.state.objects[object_id].current_hp
    for _ in range(tries):
        advance_to_human(engine, session)
        attack_object(engine, session, object_id)
        hp = engine.state.objects[object_id].current_hp
        end_turn(engine, session)
        if hp < before_hp:
            return
    raise AssertionError(f"{object_id} took no damage in {tries} hits")


def move_human_to(engine, session, at):
    advance_to_human(engine, session)
    # More than one candidate can reach the same destination (a plain walk and a pricier alternate route); the
    # cheapest one is the move a player actually wants, and the one Difficult Terrain's cost doubling is about.
    matches = [c for c in engine.legal_candidates()
              if c.actor_id == LEFT and c.kind == CandidateKind.MOVE
              and c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)]
    candidate = min(matches, key=lambda c: c.movement_cost_ft)
    events = run_candidate(engine, session, LEFT, candidate)
    end_turn(engine, session)
    return events


def move_adjacent_to(engine, session, object_id):
    """Into melee reach of a placed object (a weapon's "Attack an object" is 5ft reach here), picking whichever
    legal destination the engine's own pathing offers that lands next to it -- never a hand-picked cell, since
    several of the catalog's own kinds block the straight approach and the detour is the engine's to find."""
    obj = engine.state.objects[object_id].position
    here = engine.state.actors[LEFT].position
    if max(abs(here.x - obj.x), abs(here.y - obj.y)) <= 1:
        return []
    advance_to_human(engine, session)
    matches = [c for c in engine.legal_candidates()
              if c.actor_id == LEFT and c.kind == CandidateKind.MOVE and c.destination is not None
              and max(abs(c.destination.x - obj.x), abs(c.destination.y - obj.y)) <= 1]
    candidate = min(matches, key=lambda c: c.movement_cost_ft)
    events = run_candidate(engine, session, LEFT, candidate)
    end_turn(engine, session)
    return events


def cover_bonus_between(engine, a, b):
    """The +2/+5 an attack's cover_bonus comes from (combat/gate4_engine.py _raw_cover_bonus_actor_to_actor),
    read with the human and the foe synthetically stood either side of a cell -- a pure position calculation,
    not a committed move, so it needs no persistence of its own. The real actors are put back afterwards, so later
    assertions (and the cold-reload comparison) see the fight exactly as it was committed."""
    real_human, real_foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    human = real_human.model_copy(update={"position": Position(x=a[0], y=a[1])})
    foe = real_foe.model_copy(update={"position": Position(x=b[0], y=b[1])})
    engine.state.actors[LEFT], engine.state.actors[RIGHT] = human, foe
    try:
        return engine._raw_cover_bonus_actor_to_actor(human, foe)
    finally:
        engine.state.actors[LEFT], engine.state.actors[RIGHT] = real_human, real_foe


def assert_everything(engine, *, market_stall_destroyed, war_brazier_hp_below_default):
    """Every flag combination's engine state, called once live and once after a cold reload."""
    objects = engine.state.objects
    blocked = engine.grid.blocked

    market_stall = objects["object:map.1"]
    assert market_stall.destroyed is market_stall_destroyed
    if market_stall_destroyed:
        assert market_stall.current_hp == 0
        assert (8, 4) not in blocked, "a destroyed blocking object must open its square"
        assert engine.grid.line_of_sight(Position(x=6, y=4), Position(x=10, y=4)), "and stop blocking sight"

    ding_stats = object_rules.stats({"kind": "bronze_ding"})
    ding = objects["object:map.2"]
    assert (ding.ac, ding.current_hp, ding.damage_threshold) == (ding_stats["ac"], ding_stats["hp"], ding_stats["threshold"])
    assert not ding.destroyed and (8, 6) in blocked, "blocks + threshold: still standing, still fills its square"
    assert not engine.grid.line_of_sight(Position(x=6, y=6), Position(x=10, y=6)), "and still blocks sight"

    wheel_stats = object_rules.stats({"kind": "prayer_wheel"})
    wheel = objects["object:map.3"]
    assert (wheel.ac, wheel.current_hp) == (wheel_stats["ac"], wheel_stats["hp"])
    assert (8, 8) not in blocked, "neither flag: never blocks"
    assert engine.grid.line_of_sight(Position(x=6, y=8), Position(x=10, y=8))

    brazier_stats = object_rules.stats({"kind": "war_brazier"})
    brazier = objects["object:map.4"]
    assert brazier.damage_threshold == brazier_stats["threshold"] == 2
    assert (8, 10) not in blocked, "threshold only: a threshold never implies blocking"
    if war_brazier_hp_below_default:
        assert 0 <= brazier.current_hp < brazier_stats["hp"], "a hit clearing the threshold must cost real hit points"
    else:
        assert brazier.current_hp == brazier_stats["hp"]

    fence_stats = object_rules.stats({"kind": "fence_section"})
    fence = objects["object:map.5"]
    assert (fence.ac, fence.current_hp) == (fence_stats["ac"], fence_stats["hp"])
    assert fence.component["structure"] is True and fence.component["blocks"] is True
    assert (8, 12) in blocked, "structure + blocks: fills its square like a wall"
    assert not engine.grid.line_of_sight(Position(x=6, y=12), Position(x=10, y=12))

    closed_door, open_door = objects["object:map.6"], objects["object:map.7"]
    assert closed_door.component["door_open"] == 0 and (8, 14) in blocked, "a closed simple door blocks"
    assert open_door.component["door_open"] == 1 and (12, 14) not in blocked, "an open one does not"
    assert not engine.grid.line_of_sight(Position(x=6, y=14), Position(x=10, y=14))
    assert engine.grid.line_of_sight(Position(x=10, y=14), Position(x=14, y=14))

    assert engine.grid.base_movement_cost.get(DIFFICULT_CELL) == 2, "map-painted Difficult Terrain costs double"
    assert COVER_CELL in engine.grid.cover, "map-painted Simple Cover is still on the grid"
    assert cover_bonus_between(engine, (COVER_CELL[0] - 1, COVER_CELL[1]), (COVER_CELL[0] + 1, COVER_CELL[1])) == 2


def test_every_catalog_flag_combination_through_the_real_fight_path_and_a_cold_reload(tmp_path):
    combat, _map_id, mid = start_fight(tmp_path)
    session = combat._load_session(mid)
    engine = session.engine

    # Objects exist from the very first decision (combat/ext/objects.py seed, fired by match_start/turn_start),
    # which the editor-format map -> real-service pipeline just proved end to end.
    assert set(engine.state.objects) == {f"object:map.{row['id']}" for row in OBJECTS}

    # Difficult Terrain through a real Move, from the human's own start square, before anything else moves it.
    move_human_to(engine, session, DIFFICULT_CELL)
    committed = next(e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
                     and e.actor_id == LEFT and e.payload.get("cost_ft") is not None)
    assert committed.payload["cost_ft"] == 20, "3 squares at 5ft, the last one Difficult (doubled): 5+5+10"
    assert tuple((engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y)) == DIFFICULT_CELL

    destroy_object(engine, session, "object:map.1")               # blocks, no threshold
    damage_object_once(engine, session, "object:map.4")           # threshold only: a real hit, not destroyed

    # The human's last committed square, read before any synthetic position is put in place (the cover check
    # below restores the actors, but the reload must be compared against what the fight actually committed).
    committed_position = engine.state.actors[LEFT].position
    assert_everything(engine, market_stall_destroyed=True, war_brazier_hp_below_default=True)

    # Cold reload: a brand new CombatService (no shared Python object with ``combat`` above) pointed at the
    # same userdata, the way tests/test_a11_save_recheck.py proves a table commit survives a server restart.
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert_everything(reloaded.engine, market_stall_destroyed=True, war_brazier_hp_below_default=True)
    assert reloaded.engine.state.actors[LEFT].position == committed_position


@pytest.mark.parametrize("door_open", [0, 1])
def test_a_simple_door_blocks_exactly_when_its_placement_says_closed_and_this_survives_reload(tmp_path, door_open):
    """The one openable kind in the catalog's engine, both ways, each cold reloaded on its own (the combined
    test above already carries one of each at once; this isolates the flag so a failure names which state)."""
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({
        "display_name": f"SON198 Door {door_open}", "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[2, 4]], "team2": [[9, 4]]},
        "objects": [{"id": 1, "kind": "door", "x": 5, "y": 4, "interaction": "simple_door",
                    "door_open": door_open, "door_locked": 0, "door_jammed": 0}],
    })
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[RIGHT], control_modes={LEFT: "MANUAL"},
                                       arena_id=f"battlefield:map.{saved['map_id']}", match_seed=f"SON198-DOOR-{door_open}")
    mid = view["match_id"]
    session = combat._load_session(mid)
    engine = session.engine
    advance_to_human(engine, session)  # the one real action in this test: forces objects.seed() through turn_start

    def check(engine):
        door = engine.state.objects["object:map.1"]
        assert door.component["door_open"] == door_open
        assert ((5, 4) in engine.grid.blocked) is (door_open == 0)
        assert engine.grid.line_of_sight(Position(x=3, y=4), Position(x=7, y=4)) is (door_open == 1)

    check(engine)
    check(CombatService(ROOT, tmp_path)._load_session(mid).engine)
