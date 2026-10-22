"""F22: preserve main's effect-ray rules and non-GM fog isolation, offline."""
from fractions import Fraction
from pathlib import Path
import subprocess
from types import SimpleNamespace

from combat.effect_cover import rays
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.space import SurfacePoint

APP = Path(__file__).resolve().parents[1]


def _grid(*, blocked=(), roofs=()):
    return SquareGrid({
        "width_squares": 10, "height_squares": 10, "square_size_ft": 5,
        "starting_positions": {},
        "terrain_regions": [{
            "terrain_type": "BLOCKED", "movement_cost": 1,
            "cells": [{"x": x, "y": y} for x, y in blocked],
        }] if blocked else [],
        "roof_surfaces": list(roofs),
    })


def _clear(grid, start, end):
    return bool(list(rays(SimpleNamespace(grid=grid), [start], [end], purpose="effect")))


def test_effect_origin_blocked_cell_remains_exempt_like_main():
    # Main scans ray[1:], not the origin's physical span.
    grid = _grid(blocked=[(1, 1)])
    assert _clear(grid, Position(x=1, y=1), Position(x=5, y=1)) is True
    # Only the origin is exempt: an intervening or destination blocker still stops it.
    assert _clear(grid, Position(x=0, y=1), Position(x=5, y=1)) is False
    assert _clear(grid, Position(x=5, y=1), Position(x=1, y=1)) is False


def test_effect_roof_blocked_for_grid_and_surface_endpoints_like_main():
    grid = _grid(roofs=[{"id": "roof", "height_ft": 10,
                        "cells": [{"x": 4, "y": 4}]}])
    # Fractional XY coordinates force the surface-ended route through rays().
    for x in (4, Fraction(17, 4)):
        low, high = SurfacePoint(x, 4, 0), SurfacePoint(x, 4, 3)
        assert _clear(grid, low, high) is False
        assert _clear(grid, high, low) is False
        assert _clear(grid, SurfacePoint(x, 4, 3), SurfacePoint(x, 4, 4)) is True


def test_effect_grazing_blocked_cell_is_clear_like_main():
    # The diagonal touches only this cell's bounding-box corner. Main's
    # raster is (0,0), (1,1), (2,2); the candidate box is not a physical hit.
    grid = _grid(blocked=[(1, 0)])
    assert _clear(grid, Position(x=0, y=0), Position(x=2, y=2)) is True
    assert _clear(grid, Position(x=2, y=2), Position(x=0, y=0)) is True


def test_non_gm_unseen_fog_node_regressions():
    result = subprocess.run(
        ["node", "--test", "tests/loslines3f22_fog.test.mjs"],
        cwd=APP, text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
