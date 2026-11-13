"""Stock-built action buttons must retain their printed rules provenance."""
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from tests.test_auto17_blacksmith import _sheet, FIELD_REPAIR
from tests.test_a2_treasure_enchantments import kit


def test_generated_buttons_have_printed_rules():
    smith = compile_character(_sheet([FIELD_REPAIR]), actor_id="actor:smith")
    buttons = auto_buttons(smith, {"cultivation_level": 10})
    repair = [b for b in buttons if b["label"].startswith("Confirm damaged equipment: Field Repair")]
    assert len(repair) == 2
    for button in repair:
        assert button["description"]
        assert "Reaction" in button["description"]
        assert "Forge Mark" in button["description"]

    sheet = _sheet([], spheres=())
    sheet["equipment"] = [kit("flame_vein_inscription")]
    weapon = compile_character(sheet, actor_id="actor:weapon")
    buttons = auto_buttons(weapon, {"cultivation_level": 10})
    toggle = next(b for b in buttons if b["label"] == "Extinguish Test treasure")
    assert toggle["description"]
    assert "Bonus Action" in toggle["description"]
    assert "1d4 fire damage" in toggle["description"]
