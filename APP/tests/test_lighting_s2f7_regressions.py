"""LIGHTS2F7 regressions for the F6 review (blocking findings 1 and 2).

1. A mid-fight ambient edit changed history: the override was laid over the arena only in the live load, so replay and
   verify (which read the sealed arena) evaluated recorded events under a different light. Fix: every arena reader sees
   the override (combat/gate3_storage.load_arena), and an edit after recorded events is refused with 409.
2. Ambient_Override.json sat outside the saved-fight integrity checks: a corrupt file was silently ignored. Fix: the
   override is validated whenever the arena is loaded, and an invalid one fails the load.
"""
import pytest

from combat.gate3_storage import load_arena
from combat.saved_fight_format import UnsupportedSavedFight
from combat.tabletop import TabletopError
from tests.auto11_service_support import play
from tests.lighting_support import ambient_light, fight, light, map_document

DAY = ambient_light("day")


def test_a_pre_fight_ambient_edit_is_what_every_arena_reader_sees(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document)
    table.set_match_ambient(mid, {"time_of_day": "night"})

    arena = load_arena(combat._match_dir(mid))

    assert arena["tabletop"]["ambient"]["time_of_day"] == "night", \
        "replay, verify and cold reload read the arena through load_arena; they must see the override"


def test_an_ambient_edit_is_refused_once_the_fight_has_recorded_events(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document)
    play(table, mid, table.state(mid)["menu"]["end_turn"], answer=None)
    override = combat._match_dir(mid) / "Ambient_Override.json"

    with pytest.raises(TabletopError) as refused:
        table.set_match_ambient(mid, {"time_of_day": "night"})

    assert refused.value.code == "TABLETOP_AMBIENT_LOCKED"
    assert refused.value.status_code == 409
    assert not override.exists(), "a refused edit must not persist anything"
    assert load_arena(combat._match_dir(mid))["tabletop"]["ambient"]["time_of_day"] == "day"


def test_a_corrupt_ambient_override_fails_the_load_instead_of_being_ignored(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, _table, mid = fight(tmp_path, document)
    (combat._match_dir(mid) / "Ambient_Override.json").write_text('{"time_of_day": "noon"}', encoding="utf-8")

    with pytest.raises(UnsupportedSavedFight):
        load_arena(combat._match_dir(mid))
