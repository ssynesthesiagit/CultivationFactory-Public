"""Regression checks for the terrain-patch engine used by Magma Glob."""

from combat import typed_executor, zones
from tests.test_auto_docket import AN, ME, _ctx, _fight, _sheet


def test_obsidian_patch_is_difficult_only_for_hostiles():
    # Owner asks that the cooled Glob patch obey Obsidian Terrain's hostile-only difficulty.
    engine = _fight(_sheet([]), foe_at=(10, 6))
    typed_executor.run_effects(_ctx(engine), [{"type": "terrain_patch", "terrain": "obsidian terrain", "radius_ft": 5}])
    assert (10, 6) in zones.difficult_cells(engine, engine.state.actors[AN])
    assert (10, 6) not in zones.difficult_cells(engine, engine.state.actors[ME])
