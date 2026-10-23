"""SHEETNEST (owner 2026-10-13): "something's very wrong with this layout, it's been moved around and doesn't even
make sense anymore" -- a Fragrance + Blossom character's sheet showed "Blossom: Medicinal Blossom (1 CP)" and the
Fragrance talent rows with no parent ability row at all, and the quick bar dropped Cultivate Blossom from ACTIONS.

Cultivate Blossom's own pickers already carried `parent` (BLOSSOMBAR, c2e6ddba). The general seam they use
(option-groups.js groupOptionRows, driven by a sheet/menu button's `parent`) never covered the older "+ talent" and
"+ augment" rows (combat/tabletop.py _shape_button, _augment_button) that Darkness, Fragrance and every other sphere
with talents/augments rely on: those only carried `variant_of`, so they never structurally nested under their
ability. This checks every sphere-talent/augment row carries `parent` naming its true ability, with Darkness as the
working control the owner named as the reference behaviour.
"""
from combat.ext import blossom
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from tests.h1_support import sheet as make_sheet

FRAGRANT_VEIL = "TAL_FLOWERS_FRAGRANT_VEIL"
LINGERING_FRAGRANCE = "TAL_FLOWERS_LINGERING_FRAGRANCE"
CALMING_PERFUME = "TAL_FLOWERS_CALMING_PERFUME"
LAYERED_BOUQUET = "TAL_FLOWERS_LAYERED_BOUQUET"
NUMBING_DARKNESS = "TAL_DARK_NUMBING_DARKNESS"
PURE_DARKNESS = "TAL_DARK_PURE_DARKNESS"


def _buttons(talents):
    document = make_sheet(talents, cl=17, dc=50, primary="Qi")
    bundle = compile_character(document, actor_id="actor:factory.sheetnest")
    return {b["id"]: b for b in auto_buttons(bundle, {"cultivation_level": 17})}


def _base(buttons, suffix):
    return next(b for b_id, b in buttons.items() if b_id.endswith(suffix) and "shape" not in b_id and "toggle" not in b_id)


def test_fragrance_and_blossom_rows_carry_their_ability_as_parent():
    buttons = _buttons([blossom.THORN, blossom.SEED, FRAGRANT_VEIL, LINGERING_FRAGRANCE, CALMING_PERFUME, LAYERED_BOUQUET])
    fragrance = _base(buttons, "FLOWERS_BASE_FRAGRANCE")
    cultivate = _base(buttons, "blossom.cultivate")
    assert "parent" not in fragrance
    assert "parent" not in cultivate
    fragrance_children = [b for b in buttons.values() if b.get("shape") or b.get("augment")]
    assert fragrance_children, "Fragrance must still generate talent/augment rows"
    for row in fragrance_children:
        assert row["parent"] == fragrance["combat"]["source_definition_id"], row["label"]
    blossom_children = [b for b_id, b in buttons.items() if b_id.endswith((".blossom.pick.medicinal", ".blossom.pick.seed",
                        ".blossom.pick.thorned", ".blossom.seed.piercing", ".blossom.seed.poison", ".blossom.cultivate_bloom"))]
    assert len(blossom_children) == 6
    for row in blossom_children:
        assert row["parent"] == cultivate["combat"]["source_definition_id"], row["label"]


def test_darkness_control_also_carries_parent_on_its_augment_row():
    # Darkness is the owner's reference for correct behaviour: its "+ Persistent Darkness" augment row must nest
    # under "Darkness" the same general way Blossom's pickers nest under "Cultivate Blossom".
    buttons = _buttons([NUMBING_DARKNESS, PURE_DARKNESS])
    darkness = _base(buttons, "DARK_BASE_DARKNESS")
    assert "parent" not in darkness
    augments = [b for b in buttons.values() if b.get("augment") and b.get("variant_of") == f"act:{darkness['combat']['source_definition_id']}"]
    assert augments, "Darkness must still generate its Persistent Darkness augment row"
    for row in augments:
        assert row["parent"] == darkness["combat"]["source_definition_id"], row["label"]
