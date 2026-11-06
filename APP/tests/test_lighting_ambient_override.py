import pytest

from combat.match_ambient import normalize_ambient


def test_match_ambient_normalizes_time_and_levels():
    assert normalize_ambient({"time_of_day": "night", "level": "dark", "indoor_level": "dim"}) == {
        "time_of_day": "night", "level": 0, "indoor_level": 1}


def test_match_ambient_keeps_only_the_fields_the_gm_gave():
    assert normalize_ambient({"time_of_day": "dusk"}) == {"time_of_day": "dusk"}


@pytest.mark.parametrize("value", [
    {"time_of_day": "noon"},
    {"time_of_day": "night", "level": "brightish"},
    {"time_of_day": "night", "indoor_level": 4},
    {},
])
def test_match_ambient_rejects_invalid_settings(value):
    with pytest.raises(ValueError):
        normalize_ambient(value)
