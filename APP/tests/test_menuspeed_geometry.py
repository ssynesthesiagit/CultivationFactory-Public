"""Native roof inputs must not disable exact raster/spread memoization."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import area_projection, spatial_areas, spread_areas, typed_executor
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield


def test_builtin_map_geometry_freezes_as_exact_data():
    maps = sorted((Path(__file__).resolve().parents[1] / 'combat' / 'maps').glob('builtin-*.json'))
    assert maps
    for path in maps:
        grid = SquareGrid(to_battlefield(normalize_map(json.loads(path.read_text(encoding='utf-8')))))
        data = area_projection.geometry_data(grid)
        # geometry_inputs includes the native roof object, represented by its
        # fields in geometry_data; all other inputs must themselves freeze.
        for owner, field, value in area_projection.geometry_inputs(grid):
            area_projection._freeze(data['roof_geometry'] if (owner, field) == ('grid', 'roof_geometry') else value)
        area_projection._freeze(data)
    grid.sight_line_bounds = [(Fraction(1, 3), Fraction(2, 3), Fraction(1), Fraction(2))]
    area_projection._freeze(area_projection.geometry_data(grid))
    key = area_projection._freeze(Fraction(1, 3))
    assert hash(key) == hash(area_projection._freeze(Fraction(2, 6)))
    assert key == area_projection._freeze(Fraction(2, 6))
    assert key != area_projection._freeze(Fraction(1, 3) + Fraction(1, 10**30))
    assert key != area_projection._freeze(float(Fraction(1, 3)))


@pytest.mark.parametrize('roofs', [[], [{'id': 'roof', 'height_ft': 10,
    'cells': [{'x': 3, 'y': 3}, {'x': 4, 'y': 3}]}]])
def test_native_roof_snapshot_caches_exact_geometry_and_observes_edits(roofs, monkeypatch):
    grid = SquareGrid({'width_squares': 8, 'height_squares': 8, 'square_size_ft': 5,
                      'starting_positions': {}, 'terrain_regions': [], 'roof_surfaces': roofs})
    grid.finite_heights = True
    engine = SimpleNamespace(grid=grid, state=SimpleNamespace(state_version=1, event_sequence=1))
    origin, target = Position(x=2, y=3, z=1), Position(x=5, y=3, z=1)
    area = {'shape': 'sphere', 'size_ft': 15, 'spreads': True}
    calls = []
    native = spread_areas._Search.__init__
    def counted(self, *args):
        calls.append(1)
        native(self, *args)
    monkeypatch.setattr(spread_areas._Search, '__init__', counted)
    def check():
        assert spatial_areas.reaches(engine, origin, origin, target, area) == (
            typed_executor.in_area(engine, origin, origin, target, area)
            and spatial_areas._spread_reaches(engine, origin, origin, target, area))
        raster = area_projection.cells(engine, origin, origin, area)
        assert raster == typed_executor.area_cells(engine, origin, origin, area)
        return engine._spread_area_index, engine._area_projection_index, raster
    first_spread, first_raster, cells = check()
    snapshot = deepcopy(area_projection.geometry_data(grid))
    for _ in range(5):
        spread, raster, again = check()
        assert spread is first_spread and raster is first_raster and again is cells
    assert len(calls) == 1
    assert area_projection.geometry_data(grid) == snapshot
    if roofs:
        # Query indexes are inputs too: an unversioned edit must invalidate.
        roof = grid.roof_geometry
        roof.by_cell[(4, 3)] = (replace(roof.surfaces[0], walk_ft=5),)
        spread, raster, _ = check()
        assert spread is not first_spread and raster is not first_raster
        assert first_spread.snapshot == snapshot
        assert first_raster.grid_snapshot == snapshot
    # Unknown provider fields never become invisible to snapshot validation.
    grid.roof_geometry.custom_provider = object()
    with pytest.raises(TypeError):
        area_projection.spec_key(area_projection.geometry_data(grid))
