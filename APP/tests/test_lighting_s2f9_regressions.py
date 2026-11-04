"""LIGHTS2F9 regressions.

F8R2 finding 1: every saved map stores its own level, so a recorded "night" left the arena's Bright level in place.
The night tests fail on the F8R2 code (the level stays 2) and pass once a recorded time derives its own level.
F8R2 finding 2: the fight log printed the internal level encoding ("indoor level 1", "level 0").
"""
from combat import lighting
from combat.history_feed import format_history_feed
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, map_document
from tests.worker2_support import reload

DAY = ambient_light("day")
OUT_OF_THE_WAY = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}}
ROOF = [{"shape": "rect", "points": [[6, 3], [13, 9]], "blocks": "sight", "filled": False, "height_ft": 20}]


def test_a_recorded_night_makes_open_ground_dark_on_a_day_map(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=DAY), senses=[], positions=OUT_OF_THE_WAY)
    assert lighting.base(reload(tmp_path, mid), 3, 3) == lighting.BRIGHT

    table.set_match_ambient(mid, {"time_of_day": "night"})

    engine = reload(tmp_path, mid)
    assert lighting.ambient(engine)["level"] == lighting.DARK
    assert lighting.base(engine, 3, 3) == lighting.DARK, "open ground must be Dark once the GM says night"


def test_a_recorded_night_keeps_a_sealed_roof_at_the_arena_indoor_level(tmp_path):
    document = map_document(20, 14, ambient=ambient_light("day", indoor_level="dim"), walls=ROOF)
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)

    table.set_match_ambient(mid, {"time_of_day": "night"})

    engine = reload(tmp_path, mid)
    assert (9, 6) in lighting._roofed_cells(engine)
    assert lighting.base(engine, 9, 6) == lighting.DIM, "the roof keeps the arena's indoor level"
    assert lighting.base(engine, 3, 3) == lighting.DARK, "open ground under night is Dark"


def test_a_level_recorded_earlier_survives_a_later_time_change(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=DAY), senses=[], positions=OUT_OF_THE_WAY)
    table.set_match_ambient(mid, {"level": "dim"})

    table.set_match_ambient(mid, {"time_of_day": "night"})

    assert lighting.ambient(reload(tmp_path, mid))["level"] == lighting.DIM


def _feed_line(payload):
    event = {"event_type": "AMBIENT_SET", "actor_id": None, "target_ids": [], "sequence": 3,
             "source_definition_id": "system:table.ambient", "payload": {"ambient": payload}}
    rows = format_history_feed([event], [], pre_state=None, post_state={}, actor_names={}, definition_names={})
    return [row["summary"] for row in rows if str(row.get("summary", "")).startswith("The table owner")]


def test_the_fight_log_says_the_time_in_plain_words():
    assert _feed_line({"time_of_day": "night", "level": 0}) == ["The table owner set the light to night."]


def test_the_fight_log_names_the_roof_light_in_plain_words():
    assert _feed_line({"time_of_day": "night", "level": 0, "indoor_level": 1}) == [
        "The table owner set the light to night; under a roof it is dim."]


def test_the_fight_log_never_prints_the_level_encoding():
    for payload in ({"time_of_day": "dusk"}, {"level": 1}, {"indoor_level": 0}, {"level": 2, "indoor_level": 2}):
        for line in _feed_line(payload):
            assert "indoor level" not in line and "level 0" not in line and "level 1" not in line and "level 2" not in line


def test_the_map_editor_messages_use_plain_words_not_field_names():
    from combat.tabletop import TabletopError, normalize_map
    import pytest
    with pytest.raises(TabletopError) as refused:
        normalize_map({"width_squares": 10, "height_squares": 10,
                       "lights": [{"x": 1, "y": 1, "bright_ft": 40, "dim_ft": 20}]})
    assert "_ft" not in str(refused.value) and "radius" not in str(refused.value)
    with pytest.raises(TabletopError) as none_given:
        normalize_map({"width_squares": 10, "height_squares": 10, "lights": [{"x": 1, "y": 1}]})
    assert "_ft" not in str(none_given.value) and "radius" not in str(none_given.value)
