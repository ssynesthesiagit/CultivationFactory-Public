"""Native roof inputs must not disable exact raster/spread memoization."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from combat import area_projection, spatial_areas, spread_areas, typed_executor
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position


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
