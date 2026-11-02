"""Findings 2 and 6 (LIGHTS2): the editor's lighting settings survive save, reopen and a time-of-day change.

normalize_map is the one place a saved map is written, so these checks run the real save path on real documents.
"""
from combat.tabletop import normalize_map
from tests.lighting_support import ambient_light, map_document

NIGHT = ambient_light("night")


def test_the_preview_toggle_survives_save_and_reopen():
    saved = normalize_map(map_document(20, 12, ambient=NIGHT) | {"display": {"run_ambient": True}})
    assert saved["display"]["run_ambient"] is True
    reopened = normalize_map(saved)
    assert reopened["display"]["run_ambient"] is True


def test_the_preview_toggle_is_off_unless_the_map_turns_it_on():
    assert normalize_map(map_document(20, 12, ambient=NIGHT))["display"]["run_ambient"] is False


def test_a_night_map_saved_then_changed_to_day_plays_day_after_a_save():
    saved = normalize_map(map_document(20, 12, ambient=NIGHT))
    assert saved["ambient"]["level"] == 0
    # The editor's time-of-day change drops the derived level (ambient_edit.js withTimeOfDay), then saves again.
    changed = dict(saved)
    changed["ambient"] = {"time_of_day": "day"}
    again = normalize_map(changed)
    assert again["ambient"] == {"time_of_day": "day", "level": 2}
