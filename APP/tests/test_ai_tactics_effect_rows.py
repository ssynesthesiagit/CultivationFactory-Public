"""Regression: the Tricky planner must read real effect rows whose nested keys hold plain settings.

The reviewed Battlefield Beheading Line data stores `on_success: "suppress"` on an end_effect row. The planner's
effect walker used to call `.get` on that string, so every turn for a creature holding the talent failed to build
its menu (the empty-menu symptom behind the h52 and auto2 turn-start failures).
"""
from combat.ai_tactics import _effects


def test_effect_walk_skips_plain_setting_values_and_keeps_nested_rows():
    rows = [{"type": "end_effect", "on_success": "suppress", "select": "beneficial"},
            {"type": "save", "on_fail": [{"type": "damage"}], "on_success": [{"type": "half_damage"}]}]
    assert [row["type"] for row in _effects(rows)] == ["end_effect", "save", "damage", "half_damage"]


def test_effect_walk_handles_a_missing_or_empty_nested_key():
    assert [row["type"] for row in _effects([{"type": "attack", "on_hit": None}])] == ["attack"]
