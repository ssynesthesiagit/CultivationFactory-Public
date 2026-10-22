"""Occupied-screen client fog regressions; offline Node and software canvas only."""
from pathlib import Path
import subprocess

import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.terrain_occlusion import sight_geometry
from tests.test_loslines2 import node

APP = Path(__file__).resolve().parents[1]


def run_fog_regressions(check):
    return subprocess.run(['node', '--test',
        '--test-name-pattern=LOSLINES3F[23]:', str(check)], cwd=APP,
        text=True, capture_output=True, timeout=90)


def test_occupied_screen_production_board_fog():
    result = run_fog_regressions(APP/'tests/fog_mask.test.mjs')
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('cells', [
    [(4, 4)], [(4, 4), (4, 5), (4, 6)], [(4, 4), (6, 4)],
])
def test_bound_screen_client_outward_fog_matches_server(cells):
    grid = SquareGrid({'width_squares':10, 'height_squares':10, 'square_size_ft':5,
        'starting_positions':{}, 'terrain_regions':[{'terrain_type':'SIGHT_BLOCKED',
        'movement_cost':1, 'height_ft':10, 'cells':[{'x':x, 'y':y} for x,y in cells]}]})
    visible = node("""
import {readFileSync} from 'node:fs';
import {blockerSegments,visibilityPolygons,fogPointVisible} from './static/tabletop/fog_polygon.js';
const geometry=JSON.parse(readFileSync(0,'utf8'));
const polygons=visibilityPolygons([{x:4.5,y:4.5}],blockerSegments({sources:geometry.lines}),10,10);
console.log(JSON.stringify(Array.from({length:10},(_,y)=>Array.from({length:10},(_,x)=>
  fogPointVisible(x+.5,y+.5,10,10,[],polygons)))));
""", sight_geometry(grid))
    # Target cells inside the same screen have their own endpoint exemption on
    # the server. This regression compares the surrounding ground in the review.
    differences = [(x,y) for y in range(10) for x in range(10) if (x,y) not in cells
        and visible[y][x] != grid.line_of_sight(Position(x=4,y=4),Position(x=x,y=y))]
    assert not differences, differences
