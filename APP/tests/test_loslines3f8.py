"""LOSLINES3F8: occupied walk-through screens in the client fog agree with the server, cell for cell.

Engine rule (sight_lines.py near_endpoint): a viewer or a target inside an occupied SIGHT_BLOCKED screen
cell at that cell's height sees through its own cell only; any other cell of the same screen still blocks.
The ground fog (viewerSegments/rayVisible) and the airborne altitude mask (fog-altitude.js shadowsAt) must
apply the same exemption. The engine stays the authority; these tests compare the client masks to it.
"""
import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.tabletop import BAMBOO, normalize_map, to_battlefield
from combat.terrain_occlusion import sight_geometry
from tests.test_loslines2 import node

AIRBORNE_JS = """
import {readFileSync} from 'node:fs';
import {altitudeVisibilityPolygons} from './static/tabletop/fog-altitude.js';
import {fogPointVisible} from './static/tabletop/fog_polygon.js';
const {geometry,origin,z,w,h}=JSON.parse(readFileSync(0,'utf8'));
const polys=altitudeVisibilityPolygons([{position:{x:origin.x+.5,y:origin.y+.5,z}}],geometry,w,h)
  .filter(p=>p.surface_ft===0).map(({covered,...plane})=>plane);
console.log(JSON.stringify(Array.from({length:h},(_,y)=>Array.from({length:w},(_,x)=>fogPointVisible(x+.5,y+.5,w,h,[],polys)))));
"""

GROUND_JS = """
import {readFileSync} from 'node:fs';
import {blockerSegments,visibilityPolygons,fogPointVisible} from './static/tabletop/fog_polygon.js';
const {geometry,origin,w,h}=JSON.parse(readFileSync(0,'utf8'));
const polys=visibilityPolygons([{x:origin.x+.5,y:origin.y+.5}],blockerSegments({sources:geometry.lines}),w,h);
console.log(JSON.stringify(Array.from({length:h},(_,y)=>Array.from({length:w},(_,x)=>fogPointVisible(x+.5,y+.5,w,h,[],polys)))));
"""


def bamboo_grid(cells, height_ft=20, width=10, height=10):
    doc = normalize_map({'width_squares': width, 'height_squares': height,
                         'materials': [{'material': BAMBOO, 'cells': [list(c) for c in cells], 'height_ft': height_ft}]})
    return SquareGrid(to_battlefield(doc))


def mismatches(grid, viewer, z=None):
    """Client mask cells that disagree with grid.line_of_sight from the viewer's cell centre."""
    geometry = sight_geometry(grid)
    data = {'geometry': geometry, 'origin': {'x': viewer[0], 'y': viewer[1]}, 'w': grid.width, 'h': grid.height}
    if z is None:
        visible = node(GROUND_JS, data)
        origin = Position(x=viewer[0], y=viewer[1])
    else:
        visible = node(AIRBORNE_JS, {**data, 'z': z})
        origin = Position(x=viewer[0], y=viewer[1], z=z)
    return [(x, y) for y in range(grid.height) for x in range(grid.width)
            if visible[y][x] != grid.line_of_sight(origin, Position(x=x, y=y))]


@pytest.mark.parametrize('z', [1, 2, 3])
def test_airborne_viewer_inside_bamboo_screen_matches_engine(z):
    # Viewer rises inside an occupied 20-ft stem cell: its own cell is clear, the rest of the map is not.
    grid = bamboo_grid([(4, 4)])
    assert mismatches(grid, (4, 4), z) == []


@pytest.mark.parametrize('z', [1, 2])
def test_airborne_viewer_inside_multi_cell_screen_keeps_intervening_cells(z):
    # The screen's other cells still block: only the viewer's own cell is exempt.
    grid = bamboo_grid([(2, 4), (3, 4), (4, 4)])
    assert mismatches(grid, (2, 4), z) == []


@pytest.mark.parametrize('z', [1, 3])
def test_airborne_viewer_outside_screen_sees_occupied_target_cell(z):
    # Targets inside an occupied screen cell are visible (its near face), but the cell behind stays hidden.
    grid = bamboo_grid([(2, 4), (3, 4), (4, 4)])
    assert mismatches(grid, (0, 4), z) == []


def test_ground_viewer_inside_bamboo_screen_matches_engine():
    grid = bamboo_grid([(2, 4), (3, 4), (4, 4)])
    assert mismatches(grid, (2, 4)) == []
    assert mismatches(grid, (0, 4)) == []


def solid_grid(cells):
    return SquareGrid({'width_squares': 10, 'height_squares': 10, 'square_size_ft': 5, 'starting_positions': {},
                       'terrain_regions': [{'terrain_type': 'BLOCKED', 'movement_cost': 0, 'height_ft': 20,
                                            'cells': [{'x': x, 'y': y} for x, y in cells]}]})


@pytest.mark.parametrize('z', [None, 1, 2, 3])
def test_solid_wall_fog_differs_from_engine_only_on_the_barrier_face(z):
    # DOCUMENTED DIFFERENCE (MAINREDMISC7F2): the engine lets a creature target a solid BLOCKED
    # cell at its near face (sight_lines.py near_endpoint). The client draws a solid wall as its
    # lit edge and does not light that cell's interior. Targeting stays engine-authoritative
    # (fog_polygon.js header), so the only allowed mismatch is the front wall cell the viewer
    # faces. Any other mismatch (the cell behind, or a cell off the wall line) is a real fog bug.
    grid = solid_grid([(2, 4), (3, 4), (4, 4)])
    assert mismatches(grid, (0, 4), z) == [(2, 4)]
