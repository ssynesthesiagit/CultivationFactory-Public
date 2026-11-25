"""Walls (owner 2026-09-27: "theres a lava wall, maybe a sand wall? theres various walls, those should be able to be
placed and block los when applicable as well as movement"). combat/zones.py wall_cells / sync_walls,
combat/rules/terrain.json "walls"."""

from pathlib import Path

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
OWNER = "actor:factory.waller"


def _engine(sphere: str, talents: list[str]) -> Gate4ControllerEngine:
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    bundle = compile_character(sheet, actor_id=OWNER)
    return Gate4ControllerEngine(ROOT, match_seed="WALLS", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                     "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})


def _raise(engine: Gate4ControllerEngine, name: str, at: tuple[int, int]) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith(name) and c.destination is not None and (c.destination.x, c.destination.y) == at)
    engine.execute_intent(ActionIntent(intent_id="wall", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=OWNER, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_a_lava_wall_stands_across_the_line_and_blocks_movement_and_sight():
    engine = _engine("tianxia.sphere.magma", ["TAL_MAGMA_LAVA_WALL"])
    _raise(engine, "Lava Wall", (8, 6))
    [wall] = zones.typed_zones(engine)
    cells = {(cell.x, cell.y) for cell in wall.affected_cells}
    assert cells == {(8, y) for y in range(2, 10)}  # 40 feet long, across the line from the caster at (3,6)
    assert wall.trigger_profile["visual"]["material"] == "lava" and wall.trigger_profile["wall"]["blocks_movement"]
    assert cells <= engine.grid.blocked
    assert not engine.grid.line_of_sight(Position(x=3, y=6), Position(x=14, y=6))
    foe = engine.state.actors[AN]
    engine.state.current_actor_id = AN
    foe.movement_remaining_ft = 30
    assert not any(c.destination.x <= 8 and 2 <= c.destination.y <= 9 for c in engine._movement_candidates(foe)
                   if c.destination is not None and (c.destination.x, c.destination.y) in cells)


def test_a_wall_of_smoke_hides_can_be_walked_through_gives_disadvantage_through_it_and_ends_with_its_concentration():
    engine = _engine("tianxia.sphere.magma", ["TAL_MAGMA_LAVA_WALL"])
    _raise(engine, "Lava Wall", (8, 6))
    [wall] = zones.typed_zones(engine)
    wall.trigger_profile["wall"] = {"obscures": "all"}
    wall.trigger_profile["wall"].pop("leaves", None)
    zones.sync_walls(engine)
    cells = {(cell.x, cell.y) for cell in wall.affected_cells}
    assert not cells & engine.grid.blocked and not cells & engine.grid.opaque  # walk through it; attacks are still possible
    me, foe = engine.state.actors[OWNER], engine.state.actors[AN]
    assert zones.attack_mode(engine, me, foe) == "DISADVANTAGE" and zones.attack_mode(engine, foe, me) == "DISADVANTAGE"
    wall.trigger_profile["wall"] = {"obscures": "hostile"}  # Monsoon Wall: only its creator's foes can't see through
    assert zones.attack_mode(engine, me, foe) is None and zones.attack_mode(engine, foe, me) == "DISADVANTAGE"
    engine._end_concentration(engine.state.actors[OWNER], "TEST")
    assert zones.attack_mode(engine, foe, me) is None


def test_a_saved_fight_gets_its_walls_back_when_the_grid_is_rebuilt():
    engine = _engine("tianxia.sphere.magma", ["TAL_MAGMA_LAVA_WALL"])
    _raise(engine, "Lava Wall", (8, 6))
    base = engine._wall_base
    engine.grid.blocked, engine.grid.opaque = set(base[0]), set(base[1])  # a fresh grid from the map, as on load
    del engine._wall_base
    zones.sync_walls(engine)
    assert (8, 6) in engine.grid.blocked


def test_a_dune_wall_costs_four_times_the_movement():
    engine = _engine("tianxia.sphere.sand", ["TAL_SAND_DUNE_WALL"])
    _raise(engine, "Dune Wall", (8, 6))
    assert engine.grid.base_movement_cost[(8, 6)] == 4 and (8, 6) in engine.grid.cover and (8, 6) not in engine.grid.blocked


def test_a_talent_that_shapes_an_area_as_a_wall_offers_that_wall():
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.smoke"],
                                              "learned_talent_record_ids": ["SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_WALL_OF_SMOKE"]}}
    catalog = compile_character(sheet, actor_id=OWNER)["action_catalog"]
    rows = [row if isinstance(row, dict) else row.model_dump() for row in (catalog.values() if isinstance(catalog, dict) else catalog)]
    [wall] = [row for row in rows if row["display_name"] == "Smoke Veil + Wall of Smoke"]
    spec = wall["parameters"]["typed"]["zone_spec"]
    assert wall["target_kind"] == "CELL" and spec["wall"] == {"obscures": "all", "thick_ft": 10, "length_ft": 30}
    assert spec["visual"]["material"] == "smoke" and not spec["centered_on_self"]


def test_a_lava_wall_leaves_obsidian_terrain_when_it_ends():
    engine = _engine("tianxia.sphere.magma", ["TAL_MAGMA_LAVA_WALL"])
    _raise(engine, "Lava Wall", (8, 6))
    [wall] = zones.typed_zones(engine)
    engine._end_concentration(engine.state.actors[OWNER], "TEST")
    [left] = zones.typed_zones(engine)
    assert left.trigger_profile["name"] == "Obsidian Terrain" and left.affected_cells == wall.affected_cells
    assert left.duration_rounds == 10 and left.trigger_profile["difficult"] == "hostile" and not left.trigger_profile.get("wall")
    assert (8, 6) not in engine.grid.blocked


def test_a_large_creature_forces_through_a_dune_wall_and_a_puzzle_wall_opens_for_a_turn():
    engine = _engine("tianxia.sphere.sand", ["TAL_SAND_DUNE_WALL"])
    _raise(engine, "Dune Wall", (8, 6))
    [wall] = zones.typed_zones(engine)
    wall.trigger_profile["numbers"] = {**wall.trigger_profile["numbers"], "save_dc": -50}  # the check succeeds
    me = engine.state.actors[OWNER]
    me.position = Position(x=7, y=6)
    engine._system_start_turn()  # a fresh turn: raising the wall used the Action
    offered = lambda: [c for c in engine.legal_candidates() if c.display_name == "Force through the wall"]  # noqa: E731
    assert not offered()  # a Medium creature wades through instead
    medium = engine._footprint
    engine._footprint = lambda actor_id: medium(actor_id).model_copy(update={"width_cells": 2}) if actor_id == OWNER else medium(actor_id)
    [force] = offered()
    engine.execute_intent(ActionIntent(intent_id="force", decision_id=force.decision_id, candidate_id=force.candidate_id,
                                       state_version=force.state_version, actor_id=OWNER, target_ids=force.target_ids))
    assert Position(x=8, y=6) not in wall.affected_cells and len(wall.affected_cells) == 5  # that section collapsed
    # Puzzle Wall: the same wall as a puzzle opens the section until the start of the creature's next turn.
    wall.trigger_profile["wall"] = {"blocks_movement": True, "breach": {"ability": "INT", "skill": "Investigation", "result": "opening"}}
    zones.sync_walls(engine)
    assert (8, 5) in engine.grid.blocked
    zones.breach(engine, me, wall, Position(x=8, y=5))
    assert (8, 5) not in engine.grid.blocked and (8, 4) in engine.grid.blocked
    zones.on_turn_start(engine, me)
    assert (8, 5) in engine.grid.blocked


def test_wall_sizes_and_entering_a_wind_wall():
    from combat.factory_compiler import compile_character

    def spec(sphere, talent, cl):
        sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": cl},
                 "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": [talent]}}
        catalog = compile_character(sheet, actor_id=OWNER)["action_catalog"]
        rows = [row if isinstance(row, dict) else row.model_dump() for row in (catalog.values() if isinstance(catalog, dict) else catalog)]
        return next(row["parameters"]["typed"]["zone_spec"] for row in rows if (row["parameters"].get("typed") or {}).get("zone_spec", {}).get("wall"))

    assert spec("tianxia.sphere.earth", "TAL_EARTH_HUMBLE_WALL", 4)["size_ft"] == 10
    assert spec("tianxia.sphere.earth", "TAL_EARTH_HUMBLE_WALL", 12)["size_ft"] == 20  # four sections at CL 11
    assert spec("tianxia.sphere.earth", "TAL_EARTH_RAISE_THE_LOAD_BEARING_WALL", 10)["size_ft"] == 30  # six sections
    wind = spec("tianxia.sphere.air", "TAL_AIR_WIND_WALL", 10)
    # "A creature that enters the wall for the first time on a turn or starts its turn there" (Air review, sw-air).
    assert wind["triggers"] and wind["triggers"][0]["on"] == ["enter", "start"] and wind["triggers"][0]["effects"][0]["type"] == "save"
    force = spec("tianxia.sphere.force", "TAL_FORCE_FORCE_WALL", 10)
    assert force["wall"]["blocks_movement"] and force["wall"]["see_through"]
