"""Painting a tabletop map with materials (owner 2026-09-28: "id like a map editor mode so i can make maps with the
materials and save them"; ruling: look and rules). combat/tabletop.py normalize_map / to_battlefield, combat/zones.py
map_zones."""

from pathlib import Path

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop import normalize_map, to_battlefield
from tests.test_zones import OWNER, SHEET

ROOT = Path(__file__).resolve().parents[1]


def _map() -> dict:
    return normalize_map({
        "display_name": "Glass Court", "width_squares": 20, "height_squares": 14,
        "materials": [
            {"material": "floor:grass", "cells": [[1, 1], [2, 1], [3, 1]]},
            {"material": "floor:marble", "cells": [[3, 1], [4, 1]]},              # (3, 1) is marble now
            {"material": "terrain:shattered glass terrain", "cells": [[8, 6], [9, 6], [10, 6], [99, 99]]},
            {"material": "terrain:no such terrain", "cells": [[5, 5]]},
            {"material": "floor:not-a-style", "cells": [[6, 6]]},
        ],
        "terrain_numbers": {"save_dc": 15, "pb": 3},
        "starts": {"team1": [[3, 6]], "team2": [[14, 6]]},
    })


def test_a_map_keeps_known_materials_one_floor_and_one_terrain_per_square():
    document = _map()
    assert document["materials"] == [
        {"material": "floor:grass", "cells": [[1, 1], [2, 1]]},
        {"material": "floor:marble", "cells": [[3, 1], [4, 1]]},
        {"material": "terrain:shattered glass terrain", "cells": [[8, 6], [9, 6], [10, 6]]},
    ]
    assert document["terrain_numbers"] == {"save_dc": 15, "pb": 3}
    arena = to_battlefield(document)
    assert arena["map_terrain"] == [{"terrain": "shattered glass terrain", "cells": [[8, 6], [9, 6], [10, 6]],
                                    "natural_haze": False, "save_dc": 15, "pb": 3}]
    assert arena["tabletop"]["floors"] == [{"style": "grass", "cells": [[1, 1], [2, 1]]}, {"style": "marble", "cells": [[3, 1], [4, 1]]}]


def test_painted_terrain_is_part_of_the_fight_from_its_start_and_works_for_everyone():
    arena = to_battlefield(_map())
    bundle = compile_character(SHEET, actor_id=OWNER)
    engine = Gate4ControllerEngine(ROOT, match_seed="MAPTERRAIN", typed_bundles=(bundle,), battlefield=arena,
                                   roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                                 "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    [zone] = zones.typed_zones(engine)
    assert zone.owner_id == zones.MAP_OWNER and zone.trigger_profile["name"] == "Shattered Glass Terrain"
    me, foe = engine.state.actors[OWNER], engine.state.actors[AN]
    assert (9, 6) in zones.difficult_cells(engine, me) and (9, 6) in zones.difficult_cells(engine, foe)  # no side
    hp = foe.current_hp
    start, foe.position = foe.position, Position(x=9, y=6)
    zones.on_moved(engine, foe, start, foe.position)  # moving through Shattered Glass: the map's PB 3 slashing
    assert foe.current_hp == hp - 3


def _grove() -> dict:
    return normalize_map({
        "display_name": "Bamboo Grove", "width_squares": 20, "height_squares": 14, "display": {"blend": 0.6},
        "trees": [{"x": 5, "y": 5, "size": 1, "seed": 7}, {"x": 10, "y": 3, "size": 2}, {"x": 19, "y": 13, "size": 2}, {"x": "no"}],
        "materials": [{"material": "terrain:bamboo thicket", "cells": [[12, 8], [13, 8]]}],
        "starts": {"team1": [[3, 6]], "team2": [[14, 6]]},
    })


def test_trees_block_with_their_trunks_and_the_table_draws_them_with_blended_floors():
    """Owner 2026-09-28: "trees as an option both bamboo patches and larger trees", "a way to blend the different
    terrains together"."""
    document = _grove()
    assert [(tree["x"], tree["y"], tree["size"]) for tree in document["trees"]] == [(5, 5, 1), (10, 3, 2)]  # the 2x2 at the corner would leave the map
    assert document["display"]["blend"] == 0.6 and normalize_map({"display_name": "Old"})["display"]["blend"] == 0.0
    arena = to_battlefield(document)
    solid = [region for region in arena["terrain_regions"] if region["terrain_type"] == "BLOCKED"]
    assert {(cell["x"], cell["y"]) for region in solid for cell in region["cells"]} == {(5, 5), (10, 3), (11, 3), (10, 4), (11, 4)}
    assert all(region["occluder"] == "centerline" for region in solid)
    assert arena["tabletop"]["display"]["blend_pct"] == 60
    assert [(tree["x"], tree["y"], tree["size"]) for tree in arena["tabletop"]["trees"]] == [(5, 5, 1), (10, 3, 2)]


def test_bamboo_is_difficult_for_everyone_and_lightly_obscured():
    arena = to_battlefield(_grove())
    engine = Gate4ControllerEngine(ROOT, match_seed="BAMBOO", typed_bundles=(compile_character(SHEET, actor_id=OWNER),), battlefield=arena,
                                   roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                                 "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["name"] == "Bamboo Thicket" and zone.trigger_profile["obscured"] == "light"
    for actor in (engine.state.actors[OWNER], engine.state.actors[AN]):
        assert (12, 8) in zones.difficult_cells(engine, actor)
