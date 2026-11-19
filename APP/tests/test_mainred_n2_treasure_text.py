"""Generated treasure controls preserve compiled printed evidence."""
from hashlib import sha256

import pytest

from combat.ext.treasure_enchantments import PRINTED, flame_actions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.tabletop import auto_buttons
from tests.test_auto17_blacksmith import _sheet
from tests.test_a2_treasure_enchantments import kit, ROWS


def test_toggle_description_from_compiled_evidence():
    evidence = "Synthetic printed enchantment evidence."
    base = ActionDefinition(
        source_definition_id="action:typed.test.weapon", display_name="Test treasure attack",
        owner_id="actor:weapon", economy="ACTION", resolution_kind="TYPED",
        target_kind="HOSTILE_ENTITY",
        parameters={"typed": {"weapon": {"damage": {"count": 1, "sides": 4}},
                    "effects": [{"type": "attack", "on_hit": [
                        {"type": "treasure_flame_damage", "item": "test-item", "evidence": evidence}]}]}})
    actions = flame_actions({"actions": [base], "actor_id": "actor:weapon", "numbers": {}})
    buttons = auto_buttons({"action_catalog": [a.model_dump(mode="json") for a in actions]}, {})
    toggle = next(b for b in buttons if b["label"] == "Extinguish Test treasure")
    assert toggle["description"] == evidence


def test_stock_toggle_has_printed_rules():
    text = ROWS["flame_vein_inscription"]["text"]
    if sha256(text.encode()).hexdigest() != PRINTED["flame_vein_inscription"]:
        pytest.skip("Stock text is not the reviewed printed authority in this copy")
    sheet = _sheet([], spheres=())
    sheet["equipment"] = [kit("flame_vein_inscription")]
    weapon = compile_character(sheet, actor_id="actor:weapon")
    buttons = auto_buttons(weapon, {"cultivation_level": 10})
    toggle = next(b for b in buttons if b["label"] == "Extinguish Test treasure")
    assert "Bonus Action" in toggle["description"]
    assert "1d4 fire damage" in toggle["description"]
