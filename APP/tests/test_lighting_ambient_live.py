"""A recorded light change advances the fight's state_version, so the next read sees the new light (no manual cache drop)."""
from combat.lighting import ambient
from tests.lighting_support import ambient_light, fight, light, map_document


def test_a_recorded_light_change_is_seen_on_the_next_read(tmp_path):
    document = map_document(20, 12, ambient=ambient_light("day"), lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document)
    version = combat._load_session(mid).engine.state.state_version

    table.set_match_ambient(mid, {"time_of_day": "night"})

    engine = combat._load_session(mid).engine
    assert engine.state.state_version > version
    assert ambient(engine)["time_of_day"] == "night"
