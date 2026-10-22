"""Living Painting review round (F10R): the Serpent's printed-text and header wording match the swim capability.

Pure text checks on repository files; no fight, no model, no network.
"""
import json
from pathlib import Path

import combat.ext.painting_forms as painting_forms

APP = Path(__file__).resolve().parents[1]
SERPENT_RIDER = "The Serpent acts immediately after your turn and Dodges unless commanded"


def test_module_header_no_longer_says_swim_speed_is_unmodeled():
    doc = painting_forms.__doc__
    assert "Not modeled here" not in doc
    assert "Swim Speed (40 feet)" in doc
    assert "authored on the battlefield map" in doc


def test_serpent_rider_text_states_swim_only_in_authored_water():
    path = APP / "authority/typed_mechanics/reviewed_final.d/sys_menus-forms.json"
    riders = json.loads(path.read_text(encoding="utf-8"))["mechanics"][
        "tianxia.subpath.qi.painting_cultivator.feature.living_painting"]["options"]
    serpent = [r for opt in riders for r in opt.get("riders", []) if r.startswith(SERPENT_RIDER)]
    assert len(serpent) == 1
    assert "Swim Speed works only through water squares authored on the map" in serpent[0]
    assert "Climb and Swim Speeds are not on the map" not in serpent[0]


def test_player_text_for_serpent_rider_matches_the_reviewed_rider():
    path = APP / "authority/typed_mechanics/player_text.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    keys = [k for k in rows if k.startswith(SERPENT_RIDER)]
    assert len(keys) == 1
    assert "Swim Speed works only through water squares authored on the map" in keys[0]
    assert "Swim Speeds are not on the map" not in keys[0]
    assert "Swim Speed works only through water squares" in rows[keys[0]]
    assert "Resolve its Climb and Swim Speeds by hand" not in rows[keys[0]]
