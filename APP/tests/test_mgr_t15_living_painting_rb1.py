"""Living Painting review round (F10R, RB1): the Serpent's printed-text and header wording match the swim capability.

Pure text checks on repository files; no fight, no model, no network.
"""
import json
from pathlib import Path

import combat.ext.painting_forms as painting_forms

APP = Path(__file__).resolve().parents[1]
SERPENT = "The Serpent acts immediately after your turn"
NEW = "its Swim Speed works only through water squares authored on the map"
OLD = "Climb and Swim Speeds are not on the map"


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _serpent_texts(relpath):
    doc = json.loads((APP / relpath).read_text(encoding="utf-8"))
    return [s for s in _strings(doc) if SERPENT in s]


def test_module_header_states_the_swim_capability_not_unmodeled():
    doc = painting_forms.__doc__
    assert "Not modeled here" not in doc
    assert "Swim Speed (40 feet)" in doc
    assert "authored on the battlefield map" in doc


def test_reviewed_serpent_rider_states_swim_only_in_authored_water():
    texts = _serpent_texts("authority/typed_mechanics/reviewed_final.d/sys_menus-forms.json")
    assert texts, "Serpent rider text not found"
    assert all(OLD not in s for s in texts)
    assert any(NEW in s for s in texts)


def test_player_text_serpent_rider_matches_the_reviewed_wording():
    texts = _serpent_texts("authority/typed_mechanics/player_text.json")
    assert texts, "Serpent player text not found"
    assert all(OLD not in s and "Resolve its Climb and Swim Speeds by hand" not in s for s in texts)
    assert any(NEW in s for s in texts)
