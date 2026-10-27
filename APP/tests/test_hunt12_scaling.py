"""CL changes die count/sides without dropping the rest of the dice contract."""
from types import SimpleNamespace
import pytest
from combat.typed_executor import Context, _effect_dice
from tests.hunt12_support import ME, candidate, fight, reload, send

MARROW = "tianxia.subpath.body.bone_monarch.feature.marrow_regeneration"


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("cl,count", [(6, 2), (14, 3)])
def test_marrow_keeps_constitution_bonus_through_table_reload(tmp_path, auto, cl, count):
    combat, table, mid = fight(tmp_path, [MARROW], cl=cl)
    chosen = candidate(combat, mid, lambda c: c.display_name == "Marrow Regeneration")
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, chosen, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    rolls = [e.payload for e in engine.events if e.event_type == "DAMAGE_ROLLED"]
    assert len(rolls) == 1 and rolls[0]["expression"] == f"{count}d10+4"
    assert rolls[0]["total"] == sum(rolls[0]["dice"]) + 4


@pytest.mark.parametrize("bonus", [{"bonus": 3}, {"bonus_formula": "mod:metal"}])
def test_scaling_changes_only_count_and_sides(bonus):
    base = {"count": 1, "sides": 8, **bonus, "custom_metadata": "preserve"}
    effect = {"dice": base, "dice_by_cl": [[1, 4, 1, 8], [5, 20, 2, 8]]}
    assert _effect_dice(SimpleNamespace(numbers={"cl": 5}), effect) == {**base, "count": 2, "sides": 8}
    assert effect["dice"] == base


@pytest.mark.parametrize("cl,count", [(1, 1), (5, 2), (17, 4)])
@pytest.mark.parametrize("key_mod", [-1, 4])
def test_reviewed_needle_flick_keeps_its_sphere_bonus(cl, count, key_mod):
    from tests.h1_support import mechanics
    effect = mechanics()["TAL_METAL_NEEDLE_FLICK"]["effects"][0]["on_hit"][0]
    ctx = Context(None, None, None, None, {"numbers": {"cl": cl, "key_mod": key_mod}}, [])
    scaled = _effect_dice(ctx, effect)
    # R22 repair 5e7ab80e removed the duplicate dice bonus; the printed Metal
    # modifier remains in the effect formula and must survive every CL band.
    assert scaled["bonus_formula"] is None
    assert effect["formula"] == "key_ability_modifier"
    assert scaled["count"] == count
    assert scaled["sides"] == 8
    assert ctx.dice(scaled, formula=effect["formula"]).modifier == key_mod
