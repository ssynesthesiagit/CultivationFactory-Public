"""A lasting ability's effect footprint must not multiply its light after a table reload."""
import pytest

from combat import lighting
from tests.lighting_support import ambient_light, map_arena, map_document
from tests.worker2_support import OWNER, candidate, fixture, reload, settle


@pytest.mark.parametrize(
    "mechanic,name,primary,bright,dim",
    [
        ("tianxia.tradition.spirit.halo_eater.feature.crown_of_borrowed_light",
         "Crown of Borrowed Light", "Resonance", 20, 40),
        ("TAL_YANG_COMPLETING_FLAME_MANTLE", "Completing Flame Mantle", "Qi", 10, 20),
    ],
)
def test_ability_light_has_one_origin_and_printed_boundaries_after_reload(tmp_path, mechanic, name, primary, bright, dim):
    arena = map_arena(tmp_path, map_document(24, 16, ambient=ambient_light("night")))
    combat, table, mid = fixture(tmp_path, [mechanic], primary=primary, battlefield=arena)
    settle(table, mid, candidate(combat, mid, name).candidate_id)
    engine = reload(tmp_path, mid)
    sources = lighting.sources(engine)
    assert len(sources) == 1
    source = sources[0]
    actor = engine.state.actors[OWNER]
    x, y = actor.position.x, actor.position.y
    assert source.cells == frozenset({(x, y)})
    assert (source.bright_ft, source.dim_ft) == (bright, dim)
    assert [lighting.base(engine, x + dx // 5, y) for dx in (bright, bright + 5, dim, dim + 5)] == [
        lighting.BRIGHT, lighting.DIM, lighting.DIM, lighting.DARK]
