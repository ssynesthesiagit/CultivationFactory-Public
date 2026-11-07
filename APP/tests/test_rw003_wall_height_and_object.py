"""RW003 packet P2: a wall terrain rule can carry a printed height and object stats.

Blackglass Rampart (TAL_MAGMA_BLACKGLASS_RAMPART) prints four connected 5-foot panels,
10 feet high and 1 foot thick, each with AC 16, HP 5 x CL, Vulnerability to Thunder and
Immunity to Poison/Psychic, providing Cover normally. Before this packet the compiler
carried the terrain rule's "object" block only for walls that already compiled, and
"height_ft" was dropped entirely; Blackglass itself never compiled to a wall because its
printed text names its sections "panels" (combat/factory_compiler.py _zone_spec).

This is data plumbing only. The PB-Slashing traversal rider (P3) and Terraced Ascent
(P4) are later lanes and are deliberately not exercised here.
"""

from pathlib import Path

from combat import zones
from combat.ext import docket_walls
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.zones import terrain_rules
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.rw003_wall_height"


def _sheet(talents: list[str], sphere: str) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}


def _fight(sheet: dict, me_at=(3, 6), foe_at=(14, 6)) -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(
        ROOT, match_seed="RW003-WALL-HEIGHT",
        typed_bundles=(compile_character(sheet, actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _cast(engine: Gate4ControllerEngine, name: str, at: tuple[int, int]) -> object:
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == name
                     and c.destination is not None and (c.destination.x, c.destination.y) == at)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=candidate.actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return next(zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("wall"))


def _blackglass() -> Gate4ControllerEngine:
    return _fight(_sheet(["TAL_MAGMA_BLACKGLASS_RAMPART"], "tianxia.sphere.magma"))


def test_blackglass_compiles_to_a_wall_with_ten_foot_height_and_printed_object_stats():
    engine = _blackglass()
    zone = _cast(engine, "Blackglass Rampart", (6, 6))
    wall = zone.trigger_profile["wall"]

    assert wall["height_ft"] == 10
    assert wall["length_ft"] == 20 and wall["thick_ft"] == 1
    assert wall["cover"] is True
    assert wall["object"]["ac"] == "16"
    assert wall["object"]["hp"] == "5*cl"
    assert wall["object"]["scope"] == "section"
    assert wall["object"]["vulnerable"] == ["THUNDER"]
    assert wall["object"]["immune"] == ["POISON", "PSYCHIC"]

    cl = int(zone.trigger_profile["numbers"]["cl"])
    assert docket_walls.stats(zone) == {"ac": 16, "hp": 5 * cl, "scope": "section",
                                        "immune": ["POISON", "PSYCHIC"], "vulnerable": ["THUNDER"],
                                        "resist_mundane": []}


def test_blackglass_ten_foot_height_reaches_the_grid_as_a_zero_to_ten_foot_span():
    engine = _blackglass()
    zone = _cast(engine, "Blackglass Rampart", (6, 6))
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}

    # combat/zones.py sync_walls records the wall's vertical band from its "height_ft"; a
    # creature standing on the ground occupies 0..5 ft, inside the 0..10 ft band.
    for cell in cells:
        assert engine.grid.terrain_heights["SIMPLE_COVER"][cell] == 10
        assert (0, 10) in engine.grid.terrain_spans["SIMPLE_COVER"][cell]
    ground = engine.state.actors[ME]
    assert all(0 <= z * 5 < 10 for x, y, z in engine._actor_volume(ground))
    # The entry is cover-only data (no blocks_movement), so its squares are cover, not impassable.
    assert cells <= set(engine.grid.cover)


def test_a_wall_with_no_height_compiles_without_a_height_key_or_none():
    engine = _fight(_sheet(["TAL_EARTH_HUMBLE_WALL"], "tianxia.sphere.earth"))
    zone = _cast(engine, "Humble Wall", (4, 6))  # 5-ft range
    wall = zone.trigger_profile["wall"]
    printed = terrain_rules()["walls"]["humble wall"]

    assert "height_ft" not in wall
    assert all(value is not None for value in wall.values())
    # Exactly the terrain rule's fields plus the CL-worked length (15 ft at CL 10): nothing new.
    assert wall == {"cover": printed["cover"], "move_cost": printed["move_cost"], "thick_ft": printed["thick_ft"],
                    "length_ft": 15, "object": printed["object"]}
    assert docket_walls.stats(zone) == {"ac": 12, "hp": 10 + int(zone.trigger_profile["numbers"]["cl"]),
                                        "scope": "section", "immune": ["POISON", "PSYCHIC"],
                                        "vulnerable": [], "resist_mundane": []}
    # No accidental height on the grid either: the cover layer records an unbounded span.
    for cell in {(cell.x, cell.y) for cell in zone.affected_cells}:
        assert engine.grid.terrain_heights["SIMPLE_COVER"][cell] is None
        assert (0, None) in engine.grid.terrain_spans["SIMPLE_COVER"][cell]
