"""Native radius reuse preserves original geometry, bounds and overrides."""
from collections import OrderedDict
from copy import deepcopy

import pytest
from pydantic import ValidationError

from combat import gate2_grid as memo
from combat.ext.grid_radius_cache import cells_in_radius
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position


def _grid(width=8, height=6):
    return SquareGrid({"width_squares": width, "height_squares": height, "square_size_ft": 5,
                       "starting_positions": {}, "terrain_regions": []})


@pytest.fixture
def empty_cache(monkeypatch):
    monkeypatch.setattr(memo, "_CACHE", OrderedDict())
    monkeypatch.setattr(memo, "_CELL_COUNT", 0)


@pytest.mark.parametrize("radius", [-1, 0, 1, 3, 20])
def test_every_radius_result_matches_locked_grid_including_order(radius, empty_cache):
    grid = _grid()
    for x in range(10):
        for y in range(8):
            center = Position(x=x, y=y)
            expected = memo.scan_radius(grid.width, grid.height, {(x, y)}, radius)
            actual = cells_in_radius(grid, center, radius)
            assert actual == expected
            assert [p.model_dump(mode="json") for p in actual] == [p.model_dump(mode="json") for p in expected]
            assert cells_in_radius(grid, center, radius) is actual


def test_scan_reused_across_engines_and_terrain_but_bounds_invalidate(empty_cache, monkeypatch):
    original = memo._radius_regions
    scans = []

    def counted(width, height, centers, radius):
        scans.append(1)
        return original(width, height, centers, radius)

    monkeypatch.setattr(memo, "_radius_regions", counted)
    grid, fresh = _grid(), _grid()
    center = Position(x=4, y=3)
    cells = cells_in_radius(grid, center, 2)
    grid.blocked.add((4, 3))
    assert cells_in_radius(grid, center, 2) is cells
    assert cells_in_radius(fresh, center, 2) is cells
    assert len(scans) == 1
    clone = deepcopy(grid)
    clone.width = 5
    expected = original(clone.width, clone.height, {(center.x, center.y)}, 2)
    assert cells_in_radius(clone, center, 2) == expected
    assert len(scans) == 2
    assert cells_in_radius(grid, center, 2) is cells
    with pytest.raises(ValidationError):
        cells[0].x = 999  # cached Positions are frozen


def test_cell_and_entry_budgets_bound_process_cache(empty_cache, monkeypatch):
    monkeypatch.setattr(memo, "_ENTRY_LIMIT", 3)
    monkeypatch.setattr(memo, "_CELL_LIMIT", 10)
    grid = _grid()
    for x in range(8):
        cells_in_radius(grid, Position(x=x, y=3), 1)
        assert len(memo._CACHE) <= 3
        assert memo._CELL_COUNT == sum(len(cells) for cells in memo._CACHE.values()) <= 10
    cells_in_radius(grid, Position(x=3, y=3), 100)  # too large to retain
    assert memo._CELL_COUNT <= 10
    for x in range(8):
        cells_in_radius(grid, Position(x=x, y=3), 0)
    assert len(memo._CACHE) == 3


def test_subclass_and_existing_instance_override_are_preserved(empty_cache):
    class CustomGrid(SquareGrid):
        def cells_in_radius_of_cells(self, centers, radius):
            return ()

    custom = CustomGrid({"width_squares": 1, "height_squares": 1, "square_size_ft": 5,
                         "starting_positions": {}, "terrain_regions": []})
    assert cells_in_radius(custom, Position(x=0, y=0), 1) == ()
    assert "cells_in_radius" not in custom.__dict__
    grid = _grid()
    override = lambda *args: ()
    grid.cells_in_radius = override
    assert cells_in_radius(grid, Position(x=0, y=0), 1) == ()
    assert grid.cells_in_radius is override
    assert not memo._CACHE


def test_helper_and_extension_loading_never_replace_grid_methods(empty_cache):
    from tests.test_darkness_and_stealth import _fight

    original = SquareGrid.cells_in_radius
    grid = _fight().grid  # real engine initialization invokes match_start hooks
    cells_in_radius(grid, Position(x=1, y=1), 2)
    assert grid.cells_in_radius.__func__ is original
    assert "cells_in_radius" not in grid.__dict__
    assert "cells_in_radius_of_cells" not in grid.__dict__


@pytest.mark.parametrize("centers", [[], [(0, 0)], [(9, 8)], [(-2, -1), (4, 3)],
                                      [(1, 1), (1, 1), (5, 5)]])
@pytest.mark.parametrize("radius", [-1, 0, 1, 3, 20])
def test_native_multi_center_scan_is_exact_and_order_independent(centers, radius, empty_cache):
    grid = _grid()
    expected = memo.scan_radius(grid.width, grid.height, centers, radius)
    actual = grid.cells_in_radius_of_cells(iter(centers), radius)
    assert actual == expected
    assert grid.cells_in_radius_of_cells(reversed(centers), radius) is actual


def test_native_candidates_reuse_geometry_without_adapter(empty_cache, monkeypatch):
    grid = _grid()
    expected = grid.cells_in_radius(Position(x=3, y=2), 2)
    def forbidden(*args):
        pytest.fail("a repeated native query rescanned the map")
    monkeypatch.setattr(memo, "_radius_regions", forbidden)
    assert grid.cells_in_radius(Position(x=3, y=2), 2) is expected
    assert _grid().cells_in_radius_of_cells([(3, 2)], 2) is expected


def test_large_center_sets_are_exact_but_not_retained(empty_cache):
    grid = _grid()
    centers = {(n, n) for n in range(memo._CENTER_LIMIT + 1)}
    assert grid.cells_in_radius_of_cells(centers, 1) == memo.scan_radius(8, 6, centers, 1)
    assert not memo._CACHE


def test_cold_radius_query_does_not_walk_uncovered_map_cells(empty_cache, monkeypatch):
    """A huge sparse map is cheap even with no warm cache; regression for hunt6/8."""
    import builtins
    visited = 0

    def bounded_range(*args):
        nonlocal visited
        result = builtins.range(*args)
        visited += len(result)
        assert visited < 100, 'cold radius query traversed the whole map'
        return result

    monkeypatch.setattr(memo, 'range', bounded_range, raising=False)
    actual = memo.radius_geometry(100_000, 100_000, [(50_000, 50_000)], 1)
    assert [(p.x, p.y) for p in actual] == [
        (x, y) for y in range(49_999, 50_002) for x in range(49_999, 50_002)]


def test_region_union_matches_independent_scan_for_overlaps_and_off_map_centers(empty_cache):
    import random
    randomizer = random.Random(4401)
    for _ in range(120):
        width, height = randomizer.randrange(1, 18), randomizer.randrange(1, 18)
        centers = [(randomizer.randrange(-10, 30), randomizer.randrange(-10, 30))
                   for _ in range(randomizer.randrange(0, 90))]
        radius = randomizer.randrange(-1, 14)
        assert memo.radius_geometry(width, height, centers, radius) == memo.scan_radius(width, height, centers, radius)


def test_overlapping_cold_keys_reuse_frozen_positions_with_a_separate_bound(empty_cache):
    memo._radius_position.cache_clear()
    first = memo.radius_geometry(8, 6, [(1, 1)], 1)
    second = memo.radius_geometry(8, 6, [(2, 1)], 1)
    assert next(p for p in first if (p.x, p.y) == (1, 1)) is next(p for p in second if (p.x, p.y) == (1, 1))
    # Eviction of geometry tuples must not bring back per-cell validation work.
    memo._CACHE.clear()
    memo._CELL_COUNT = 0
    before = memo._radius_position.cache_info().misses
    assert memo.radius_geometry(8, 6, [(1, 1)], 1) == first
    assert memo._radius_position.cache_info().misses == before
    for x in range(17000):
        memo._radius_position(x, 0)
    assert memo._radius_position.cache_info().currsize == 16384
