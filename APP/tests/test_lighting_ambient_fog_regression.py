"""An ambient change must change what a creature can see on the very next read.

Fog perception is cached per match under the saved state_version. The change is a recorded AMBIENT_SET event, which
advances that version, so the next read recomputes the fog. The check is against a cold service loading the saved
fight, so a stale in-memory answer cannot pass.
"""
import hashlib

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document

DAY = ambient_light("day")
NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}}


def _cold(combat, tmp_path):
    return TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)


def _own_fog(table, mid):
    return table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))["fog_perception"][OWNER]


def test_an_ambient_edit_changes_the_fog_on_the_next_read(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    before = _own_fog(table, mid)

    table.set_match_ambient(mid, {"time_of_day": "night"})

    after = _own_fog(table, mid)
    cold = _own_fog(_cold(combat, tmp_path), mid)
    assert after == cold, "the live read must match a cold reload of the saved fight"
    assert after != before, "day to night must change what a creature without Darkvision sees"


def test_an_ambient_edit_keeps_the_sealed_arena_and_survives_a_cold_reload(tmp_path):
    # Arena_Battlefield.json is an immutable saved input: its sha256 is checked on every load. An ambient edit must not
    # rewrite it (that made the saved fight unloadable), and the override must still apply after a cold reload.
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    arena = combat._match_dir(mid) / "Arena_Battlefield.json"
    sealed = hashlib.sha256(arena.read_bytes()).hexdigest()

    table.set_match_ambient(mid, {"time_of_day": "night"})

    assert hashlib.sha256(arena.read_bytes()).hexdigest() == sealed
    cold = _cold(combat, tmp_path)
    assert cold.combat._load_session(mid).engine.state.ambient_override["time_of_day"] == "night"
    assert _own_fog(cold, mid) == _own_fog(table, mid)


def test_night_to_day_restores_the_visibility_in_the_other_direction(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    before = _own_fog(table, mid)

    table.set_match_ambient(mid, {"time_of_day": "day"})

    after = _own_fog(table, mid)
    cold = _own_fog(_cold(combat, tmp_path), mid)
    assert after == cold
    assert after != before
