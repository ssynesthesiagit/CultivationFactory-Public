"""Public synthetic table coverage of the printed Ancestral Resonance scene pool."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_bloodstrike1 import FEATURE, POOL, CHOICE, setup, use, strike_rolls
from tests.worker2_support import OWNER, ALLY, FOE, reload, turn


@pytest.mark.parametrize("pb", [2, 4, 6])
def test_compiler_registers_empty_scene_pool_at_printed_maximum(pb):
    document = sheet([FEATURE], cl=3)
    document["identity"]["proficiency_bonus"] = pb
    bundle = compile_character(document, actor_id=OWNER)
    pool, = [r for r in bundle["actor_template"]["resources"] if r["resource_id"] == POOL]
    assert pool["initial"] == 0
    assert pool["maximum"] == pb
    other = compile_character(sheet([], cl=3), actor_id=OWNER)
    assert all(r["resource_id"] != POOL for r in other["actor_template"]["resources"])


def test_earn_pay_recover_once_per_turn_and_cap_through_table_reload(tmp_path):
    # With no sheet preset, the ordinary construction prompt records a lineage.
    combat, table, mid = setup(tmp_path, resonance=0, bloodline_lineage=None)
    use(combat, table, mid, "Lineage affinity damage", target=OWNER)
    use(combat, table, mid, "Lineage affinity damage", target=ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0
    # No free turn-start regeneration, nor gain from non-affinity damage.
    use(combat, table, mid, "Mundane strike", target=FOE)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0
    use(combat, table, mid, "Lineage affinity damage", target=FOE)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    use(combat, table, mid, "Lineage affinity damage", target=FOE)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    prompts = use(combat, table, mid, "Qi strike", target=FOE)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert len(strike_rolls(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOL] == 0
    # All state above was committed/reloaded. A later turn can earn again;
    # repeated gains stop at the printed PB maximum.
    maximum = engine.state.actors[OWNER].resource_maximums[POOL]
    for index in range(maximum + 1):
        turn(table, mid, ALLY)
        turn(table, mid, OWNER)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == min(index, maximum)
        use(combat, table, mid, "Lineage affinity damage", target=FOE)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == min(index + 1, maximum)
