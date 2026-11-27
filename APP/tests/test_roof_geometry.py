"""Roof geometry and JS-authored-region parity, without a running application."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from combat.effect_cover import rays
from combat.footprints import ActorFootprintDefinition
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.roof_coverage import roof_regions
from combat.map_heights import walking_height_ft
from combat.roof_geometry import surfaces_for_map
from combat.tabletop import TabletopError, battlefield_as_map, normalize_map, to_battlefield, wall_cells

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("roof_top_ft, standing_ft", [(17, 15), (12, 10), (13, 15), (15, 15), (10, 10)])
def test_walking_height_rounds_roof_top_to_nearest_five_ties_up(roof_top_ft, standing_ft):
    assert walking_height_ft(roof_top_ft) == standing_ft


def roof_grid(*, kind=None, opened=False, cells=None):
    surface = {"id": "test-roof", "height_ft": 10,
               "cells": [{"x": x, "y": y} for x, y in
                         (cells if cells is not None else [(x, y) for x in range(3, 8) for y in range(3, 8)])]}
    if kind:
        surface["openings"] = [{"x": 5, "y": 5, "kind": kind, "open": opened}]
    return SquareGrid({"width_squares": 12, "height_squares": 12, "square_size_ft": 5,
                       "starting_positions": {}, "terrain_regions": [], "roof_surfaces": [surface]})


def building(*, wall_height=None, roofs=None):
    wall = {"shape": "rect", "points": [[3, 3], [8, 8]], "filled": False}
    if wall_height is not None:
        wall["height_ft"] = wall_height
    return normalize_map({"display_name": "Roof geometry building", "width_squares": 12,
                          "height_squares": 12, "walls": [wall], "roofs": roofs,
                          "background": {"style": "wood"}})


def test_support_is_exact_feet_height_and_landing_touches_top():
    grid = roof_grid()
    assert grid.roof_height_at(5, 5) == 10
    assert grid.roof_height_at(0, 0) is None
    assert grid.roof_supported(Position(x=5, y=5, z=2))
    assert not grid.roof_supported(Position(x=5, y=5, z=3))
    assert not grid.roof_supported(Position(x=5, y=5, z=1))
    assert grid.volume_step_legal(Position(x=5, y=5, z=3), Position(x=5, y=5, z=2))
    assert grid.volume_step_legal(Position(x=5, y=5, z=2), Position(x=6, y=5, z=2))


def test_thin_roof_blocks_both_directions_and_diagonal_eave_cutting():
    grid = roof_grid()
    below, above = Position(x=5, y=5, z=1), Position(x=5, y=5, z=2)
    assert grid.volume_legal(below) and grid.volume_legal(above)
    assert not grid.volume_step_legal(below, above)
    assert not grid.volume_step_legal(above, below)
    assert not grid.volume_step_legal(Position(x=2, y=5, z=1), Position(x=3, y=5, z=2))
    # Climbing completes outside the eave, then steps sideways at roof height.
    assert grid.volume_step_legal(Position(x=2, y=5, z=1), Position(x=2, y=5, z=2))
    assert grid.volume_step_legal(Position(x=2, y=5, z=2), Position(x=3, y=5, z=2))


def test_body_cannot_straddle_roof_or_fit_large_creature_through_single_cell_hole():
    grid = roof_grid(kind="trapdoor", opened=True)
    large = ActorFootprintDefinition.rectangle(2, 2, footprint_id="test:large", source_definition_id="test:roof")
    assert not grid.volume_legal(Position(x=5, y=5, z=1), footprint=large)
    assert grid.volume_legal(Position(x=5, y=5, z=2), footprint=large)
    assert grid.roof_supported(Position(x=5, y=5, z=2), footprint=large)
    assert not grid.roof_supported(Position(x=5, y=5, z=2))
    assert not grid.volume_step_legal(Position(x=5, y=5, z=1), Position(x=5, y=5, z=2), footprint=large)
    huge = ActorFootprintDefinition.rectangle(3, 3, footprint_id="test:huge", source_definition_id="test:roof")
    assert not grid.placement_legal(Position(x=4, y=4), footprint=huge)


@pytest.mark.parametrize("kind,opened,visible,passable", [
    ("trapdoor", False, False, False), ("trapdoor", True, True, True),
    ("skylight", False, True, False), ("skylight", True, True, True),
])
def test_opening_movement_sight_effect_and_support_are_independent(kind, opened, visible, passable):
    from combat.typed_executor import _clear_line
    grid = roof_grid(kind=kind, opened=opened)
    below, roof = Position(x=5, y=5, z=1), Position(x=5, y=5, z=2)
    engine = SimpleNamespace(grid=grid, _obscured_cells=lambda: set())
    assert grid.line_of_sight(below, roof) is visible
    assert grid.line_of_sight(roof, below) is visible
    assert grid.volume_step_legal(below, roof) is passable
    assert grid.volume_step_legal(roof, below) is passable
    assert bool(list(rays(engine, (below,), (roof,), purpose="effect"))) is passable
    assert _clear_line(engine, below, roof) is passable
    assert grid.roof_supported(roof) is (not opened)
    # An opening elsewhere is not permission to pass through solid roof cells.
    assert not grid.volume_step_legal(Position(x=6, y=5, z=1), Position(x=6, y=5, z=2))


def test_height_aware_sight_cover_and_roof_only_area_barrier():
    from combat.typed_executor import _clear_line
    grid = roof_grid()
    low, top = Position(x=0, y=5), Position(x=3, y=5, z=2)
    assert grid.line_of_sight(low, top)
    assert grid.cover_bonus(low, top) == 2
    assert grid.cover_bonus(Position(x=0, y=5, z=2), top) == 0
    assert grid.line_of_sight(Position(x=2, y=5, z=2), Position(x=9, y=5, z=2))
    assert not grid.line_of_sight(Position(x=5, y=5), Position(x=5, y=5, z=2))
    engine = SimpleNamespace(grid=grid)
    assert not _clear_line(engine, Position(x=5, y=5), Position(x=5, y=5, z=2))


@pytest.mark.parametrize("wall_height,settings,expected,walking", [
    (None, None, 15, 15), (12, None, 17, 15), (20, {"height_ft": 15}, 15, 15),
    (20, {"height_ft": 15, "regions": [{"x": 4, "y": 4, "height_ft": 25}]}, 25, 25),
])
def test_roof_height_default_and_override_precedence(wall_height, settings, expected, walking):
    # Sight uses the exact roof top; standing and climbing use it rounded to 5 ft.
    arena = to_battlefield(building(wall_height=wall_height, roofs=settings))
    grid = SquareGrid(arena)
    assert grid.roof_surfaces[0].height_ft == expected
    assert grid.roof_height_at(5, 5) == walking
    assert grid.roof_supported(Position(x=5, y=5, z=walking // 5))


def test_missing_heights_only_change_authored_roof_wall_cells():
    doc = building()
    doc["walls"].append({"id": "continuation", "shape": "line", "points": [[8, 5], [11, 5]],
                         "filled": False, "blocks": "sight_and_movement"})
    doc["trees"] = [{"x": 3, "y": 5, "size": 1, "seed": 1, "occluder": "centerline"}]
    arena = to_battlefield(doc)
    grid = SquareGrid(arena)
    assert grid.terrain_at((8, 5, 2), "BLOCKED"), "building boundary wall runs to its 15-ft roof top"
    assert not grid.terrain_at((8, 5, 3), "BLOCKED"), "building boundary wall stops at roof height"
    assert grid.terrain_at((10, 5, 20), "BLOCKED"), "outdoor continuation stays unlimited"
    tree = next(r for r in arena["terrain_regions"] if r["region_id"] == "tree.height.1")
    # The scenery catalog records a 30-ft broadleaf trunk. Gritty-realism LoS:
    # the tree blocks below its own top, not up to infinity or the 15-ft roof.
    height = tree.get("height_ft")
    assert height == 30
    assert grid.terrain_at((3, 5, 5), "BLOCKED"), "tree still blocks at 25 ft, above the roof"
    assert not grid.terrain_at((3, 5, 20), "BLOCKED"), "100 ft is above the recorded 30-ft tree"
    # Legacy engine records with no recorded height keep their unbounded span.
    unbounded = deepcopy(arena)
    next(r for r in unbounded["terrain_regions"] if r["region_id"] == tree["region_id"]).pop("height_ft")
    assert SquareGrid(unbounded).terrain_at((3, 5, 20), "BLOCKED")


def test_authored_roofs_survive_open_doors_and_suppressions_and_roundtrip_floor_data():
    doc = building(roofs={"height_ft": 15, "climb_check": "slippery"})
    doc["objects"] = [{"id": "entry", "kind": "door", "x": 3, "y": 5}]
    before = surfaces_for_map(doc, wall_cells)
    changed = deepcopy(doc)
    changed["objects"][0].update(door_open=1, destroyed=True, suppressed=True)
    assert surfaces_for_map(changed, wall_cells) == before
    arena = to_battlefield(doc)
    assert arena["map_objects"][0]["height_ft"] == 15
    assert SquareGrid(arena).roof_at(5, 5).climb_check == "slippery"
    assert surfaces_for_map(battlefield_as_map(arena), wall_cells) == before


@pytest.mark.parametrize("height", [True, -5, 2.5])
def test_invalid_roof_height_is_readable_and_never_silently_rounded(height):
    with pytest.raises(TabletopError, match="whole number of feet"):
        building(roofs={"height_ft": height})


def test_opening_normalization_is_bounded_and_missing_state_is_closed():
    doc = building(roofs={"openings": [None, {"x": 5, "y": 5, "kind": "trapdoor"},
                                       {"x": 5, "y": 5, "kind": "skylight", "open": True},
                                       {"x": 999, "y": 5, "kind": "trapdoor"}]})
    assert doc["roofs"]["openings"] == [{"x": 5, "y": 5, "kind": "trapdoor", "open": False}]
    assert surfaces_for_map(building(roofs={"enabled": False}), wall_cells) == []
    assert surfaces_for_map(building(roofs={"regions": [{"x": 5, "y": 5, "enabled": False}]}), wall_cells) == []


def test_python_roof_inference_matches_production_javascript_on_all_builtin_maps():
    docs = [normalize_map(json.loads(path.read_text())) for path in sorted((ROOT / "combat/maps").glob("*.json"))]
    assert docs, "the repository's built-in maps must be present"
    docs.append(building(wall_height=12))
    code = """
      import {detectRoofRegions} from './static/tabletop/roof-regions.js?v=rel6-2';
      let input=''; for await (const chunk of process.stdin) input += chunk;
      const result=JSON.parse(input).map(doc=>detectRoofRegions({...doc,
        width:doc.width_squares,height:doc.height_squares,
        floors:doc.materials.filter(r=>r.material.startsWith('floor:')).map(r=>({style:r.material.slice(6),cells:r.cells}))
      }).map(r=>({id:`${r.x},${r.y}`,cells:[...r.cells].sort((a,b)=>a[1]-b[1]||a[0]-b[0]),footprint:[...r.footprint].sort((a,b)=>a[1]-b[1]||a[0]-b[0]),wall_height_ft:r.wall_height_ft})));
      process.stdout.write(JSON.stringify(result));
    """
    result = subprocess.run(["node", "--input-type=module", "-e", code], input=json.dumps(docs),
                            cwd=ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    expected = [[{"id": f"{r['x']},{r['y']}", "cells": [list(c) for c in sorted(r["cells"], key=lambda c: (c[1], c[0]))],
                  "footprint": [list(c) for c in sorted(r["footprint"], key=lambda c: (c[1], c[0]))],
                  "wall_height_ft": r["wall_height_ft"]} for r in roof_regions(doc, wall_cells)] for doc in docs]
    assert json.loads(result.stdout) == expected
