"""Living Painting review round (F16R): the Serpent's Climb Speed is native (40 feet), so its player text and typed rider must not say it is resolved by hand.

Source-only checks on public authority JSON and the climbing hook; no fight, no model, no network.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import combat.ext.painting_forms as painting_forms

APP = Path(__file__).resolve().parents[1]
TYPED = APP / "authority" / "typed_mechanics"


def _serpent_rider_text():
    data = json.loads((TYPED / "reviewed_final.d" / "sys_menus-forms.json").read_text(encoding="utf-8"))
    texts = [r for r in json.dumps(data).split('"') if "Serpent acts immediately" in r]
    assert len(texts) == 1, texts
    return texts[0]


def test_serpent_climb_speed_hook_is_40_feet():
    actor = SimpleNamespace(active=True, summon={"family": painting_forms.FAMILY, "group": "living_painting_serpent"})
    assert painting_forms.serpent_climbing(None, actor) == {"climb_speed_ft": 40}


def test_serpent_rider_states_climb_speed_as_native_not_off_map():
    rider = _serpent_rider_text()
    assert "Climb Speed is 40 feet" in rider
    assert "not on the map" not in rider
    assert "by hand" not in rider


def test_serpent_player_text_does_not_send_climb_speed_to_the_gm():
    for name in ("player_text.json", "owner_text_edits.json"):
        text = (TYPED / name).read_text(encoding="utf-8")
        assert "Its Climb Speed is 40 feet." in text or "its Climb Speed is 40 feet" in text, name
        assert "Climb Speed is resolved by hand" not in text, name
        assert "Resolve its Climb Speed by hand" not in text, name
