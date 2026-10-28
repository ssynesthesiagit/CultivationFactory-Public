"""Public regression: a Shape talent's family does not depend on readable prose.

MUTUALKO1F13 finding 2: the compiler used to classify an area talent by the
"### Numbing Darkness - Darkness" heading in its own private copy of
rules_text.json. On the public export the printed prose is scrambled, so the
heading vanished and the legal "Shape Darkness: Numbing Darkness" option
silently disappeared. The compiler now reads the live printed-rules file and
takes the family from the typed record's catalog tags, so a redacted heading
still offers the option.

This uses only synthetic rules prose and the public real-sheet fixture, so it
runs on the scrambled public copy where the bug appeared.
"""
import json

from combat import factory_compiler, option_text, status_text
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from tests.option_tooltip_support import OWNER, sheet


def test_shape_option_survives_a_synthetic_printed_rules_file(tmp_path, monkeypatch):
    # The export also scrambles typed description prose, which used to be the
    # only evidence that a lasting area is a zone. Keep the typed area and
    # duration and remove the prose, exactly as the public copy does.
    monkeypatch.setattr(factory_compiler, "_texts", lambda mechanic: "")
    rules = {
        # The public export replaces the printed heading with this marker. The typed
        # record's tags still say the talent belongs to Darkness, and its typed
        # area and duration still make it a zone, so the option stands.
        "TAL_DARK_NUMBING_DARKNESS": "[text redacted: public export]",
        "printed_option:Numbing Darkness": (
            "###### Numbing Darkness\nApply Numbing Darkness to the selected area."),
    }
    path = tmp_path / "synthetic-rules.json"
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", path)
    option_text._names.cache_clear()
    try:
        compiled = compile_character(sheet(), actor_id=OWNER)
        labels = [button["label"] for button in auto_buttons(compiled, {"cultivation_level": 10})]
        assert "Shape Darkness: Numbing Darkness" in labels
    finally:
        option_text._names.cache_clear()
