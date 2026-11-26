"""The parser typed 'your key ability modifier' as mod:your, and the engine
hid it by reading every mod: as the key modifier.
"""
import json
from pathlib import Path

import pytest

from combat.typed_executor import Context
from factory_authoring.typed_mechanics import _formula


def test_parser_only_types_key_ability_modifiers():
    for phrase in ("key ability modifier", "your key ability modifier",
                   "Metal key ability modifier", "your Metal key ability modifier"):
        assert _formula(phrase) == "key_ability_modifier"
    for phrase in ("your modifier", "Strength modifier", "your Strength modifier"):
        assert _formula(phrase) == "text:" + phrase.lower()


@pytest.mark.parametrize("row,count,sides", [
    ("tianxia.talent.ink.painted_beast", 2, 6),
    ("tianxia.talent.ink.ten_thousand_illustrated_soldiers", 4, 8),
    ("TAL_METAL_COMMAND_THE_HIDDEN_BLADE", 3, 8),
])
@pytest.mark.parametrize("key_mod", [-2, 4])
def test_catalog_damage_dice_keep_key_modifier(row, count, sides, key_mod):
    path = Path(__file__).resolve().parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
    mechanics = json.loads(path.read_text())["mechanics"]
    dice = mechanics[row]["effects"][0]["on_hit"][0]["dice"]
    assert dice["bonus_formula"] == "key_ability_modifier"
    ctx = Context(None, None, None, None, {"numbers": {"key_mod": key_mod}}, [])
    result = ctx.dice(dice)
    assert (result.count, result.sides, result.modifier) == (count, sides, key_mod)
