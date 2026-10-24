"""Public regression: compiled Shape options follow the live printed rules file.

MUTUALKO1F13 finding 2: the compiler used to read its own private copy of
rules_text.json while the table read status_text.RULES_TEXT_PATH. On the public
export the printed prose is scrambled, so the compiler lost the
"### Numbing Darkness - Darkness" heading and silently stopped offering the
legal "Shape Darkness: Numbing Darkness" option. Both now read one file.

This uses only synthetic rules prose and the public real-sheet fixture, so it
runs on the scrambled public copy where the bug appeared.
"""
import json

from combat import option_text, status_text
from combat.factory_compiler import compile_character
from tests.option_tooltip_support import OWNER, sheet


def test_shape_option_survives_a_synthetic_printed_rules_file(tmp_path, monkeypatch):
    rules = {
        "TAL_DARK_NUMBING_DARKNESS": (
            "### Numbing Darkness - Darkness\nCreatures inside your Darkness have Disadvantage on "
            "Strength, Dexterity, and Constitution ability checks and saving throws."),
        "printed_option:Numbing Darkness": (
            "###### Numbing Darkness\nApply Numbing Darkness to the selected area."),
    }
    path = tmp_path / "synthetic-rules.json"
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", path)
    option_text._names.cache_clear()
    try:
        compiled = compile_character(sheet(), actor_id=OWNER)
        labels = [action["display_name"] for action in compiled["action_catalog"]]
        assert "Shape Darkness: Numbing Darkness" in labels
    finally:
        option_text._names.cache_clear()
