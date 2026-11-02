"""RULER1 (owner feedback desk FD-17): the map ruler's length always equals the engine's distance.

The ruler is a client-only module (APP/static/tabletop/ruler.js), so its own regressions run under
``node --test``; that suite is started from here so the queue admits it like any other test.
The second test recomputes the same paths through combat/gate2_grid.py, which is what the engine's
reach and range checks use, and is the check that keeps the two rulers from ever disagreeing.
No repository history, owner data or browser is used, so both run on public CI."""
import json
import subprocess
from pathlib import Path

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position

ROOT = Path(__file__).resolve().parents[1]


def _position(cell):
    return Position(x=int(cell["x"]), y=int(cell["y"]), z=int(cell.get("z", 0)))


def _grid(square_size_ft):
    return SquareGrid({"width_squares": 20, "height_squares": 20, "square_size_ft": square_size_ft,
                       "starting_positions": {}, "terrain_regions": []})


def test_map_ruler_client_regressions():
    result = subprocess.run(["node", "--test", "static/tabletop/ruler.test.mjs"],
                            cwd=ROOT, text=True, capture_output=True, timeout=120)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]


def test_ruler_feet_match_the_engine_distance():
    paths = [
        ({"x": 0, "y": 0}, {"x": 4, "y": 0}, 5),
        ({"x": 0, "y": 0}, {"x": 3, "y": 3}, 5),
        ({"x": 1, "y": 1}, {"x": 4, "y": 5}, 5),
        ({"x": 5, "y": 5}, {"x": 2, "y": 3}, 5),
        ({"x": 2, "y": 2}, {"x": 2, "y": 2}, 5),
        ({"x": 0, "y": 0, "z": 0}, {"x": 2, "y": 2, "z": 3}, 5),
        ({"x": 0, "y": 0, "z": 5}, {"x": 0, "y": 0}, 5),
        ({"x": 0, "y": 0}, {"x": 3, "y": 4}, 10),
    ]
    engine = []
    for start, end, size in paths:
        grid = _grid(size)
        engine.append(grid.distance_between_cell_sets_ft((_position(start),), (_position(end),)))
    script = (
        "import {rulerMeasure} from './static/tabletop/ruler.js';"
        "const paths = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(paths.map(([a, b, size]) => rulerMeasure(a, b, size).feet)));"
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(paths)],
                            cwd=ROOT, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == engine, "the map ruler and the engine disagree about distance"
