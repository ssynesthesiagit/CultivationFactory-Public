import pytest

from combat.lighting_override import normalize_ambient_override


def test_match_ambient_override_normalizes_time_and_levels():
    assert normalize_ambient_override(
        {"time_of_day": "night", "level": "dark", "indoor_level": "dim"}
    ) == {"time_of_day": "night", "level": 0, "indoor_level": 1}


def test_match_ambient_override_derives_missing_level_from_time():
    assert normalize_ambient_override({"time_of_day": "dusk"}) == {
        "time_of_day": "dusk", "level": 1
    }


@pytest.mark.parametrize("value", [
    {"time_of_day": "noon"},
    {"time_of_day": "night", "level": "brightish"},
    {"time_of_day": "night", "indoor_level": 4},
])
def test_match_ambient_override_rejects_invalid_settings(value):
    with pytest.raises(ValueError):
        normalize_ambient_override(value)
