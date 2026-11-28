"""Both supported weapon-distance encodings survive binding talent attacks."""
import pytest

from combat import factory_compiler as fc
from combat.ext.docket_maneuvers import maneuvers
from combat.gate2_runtime_models import ActionDefinition, EconomyKind

OWNER = "actor:reach"
BATTER = "TAL_BERSERKER_BATTER"


def weapon(range_ft, reach_ft, *, ranged=False):
    return ActionDefinition(
        source_definition_id="test:weapon", display_name="Test reach weapon attack",
        owner_id=OWNER, economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="HOSTILE_ENTITY", range_ft=range_ft, reach_ft=reach_ft,
        parameters={"expected_damage": 5, "typed": {
            "source": "test:item", "range_ft": 60 if ranged else None,
            "numbers": {"attack_bonus": 6},
            "weapon": {"damage": {"count": 1, "sides": 8, "modifier": 2}},
            "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1,
                         "on_hit": [{"type": "damage", "weapon_damage": True}]}]}})


@pytest.mark.parametrize("range_ft,reach_ft,expected", [(10, None, 10), (None, 10, 10), (5, 10, 10)])
def test_generic_with_weapon_binding_uses_reach_then_legacy_range(range_ft, reach_ft, expected):
    base = weapon(range_ft, reach_ft)
    technique = base.model_copy(update={"source_definition_id": "test:technique",
        "range_ft": 5, "reach_ft": None, "parameters": {"typed": {
            "source": "test:technique", "effects": [{"type": "attack", "on_hit": []}]}}})
    kinds = [{"action_id": base.source_definition_id, "melee": True, "ranged": False, "thrown": False}]
    bound = fc._deliver_with_weapons([base, technique], kinds,
        {"test:technique": {"weapon_delivery": {"kind": "melee"}}}, [])[-1]
    assert bound.range_ft == expected
    assert bound.parameters["typed"]["delivered_by"] == base.source_definition_id


@pytest.mark.parametrize("range_ft,reach_ft", [(10, None), (None, 10)])
def test_batter_modifier_variants_inherit_weapon_distance(range_ft, reach_ft, monkeypatch):
    # Exercise the real maneuver builder; the synthetic modifier only captures
    # the generic row handed to apply_modifiers, before any talent changes it.
    seen = []
    def modifier_rows(built, *args, **kwargs):
        seen.extend(row["range_ft"] for row in built.values())
        return []
    monkeypatch.setattr(fc, "apply_modifiers", modifier_rows)
    result = maneuvers({
        "actions": [weapon(range_ft, reach_ft)], "actor_id": OWNER,
        "mechanics": {"test:modifier": {"modifier": {"targets": ["Batter"]}}},
        "owned": [BATTER, "test:modifier"], "automated": [], "spheres": [],
        "primary": "qi", "pools": {}, "foundation_resource": None, "numbers": {},
    })
    assert result and seen == [10]


def test_advancing_carnage_is_one_attack_with_the_same_physical_weapon():
    from combat.ext.bodya_berserker import _grant_bonus_attack, ADVANCING_CARNAGE
    base = weapon(10, None)
    base.parameters["typed"]["effects"][0].update(count=2, count_by_cl=[[11, 20, 3]])
    result = _grant_bonus_attack({"owned": [ADVANCING_CARNAGE], "actions": [base], "actor_id": OWNER})
    clone = result["actions"][0]
    typed = clone.parameters["typed"]
    assert typed["weapon_source_id"] == base.source_definition_id
    assert typed["effects"][0]["count"] == 1 and "count_by_cl" not in typed["effects"][0]
    assert base.parameters["typed"]["effects"][0]["count"] == 2


def test_ranged_binding_keeps_range_instead_of_a_melee_reach():
    from combat.ext.weapon_actions import delivery_range_ft
    assert delivery_range_ft(weapon(120, 5, ranged=True)) == 120
