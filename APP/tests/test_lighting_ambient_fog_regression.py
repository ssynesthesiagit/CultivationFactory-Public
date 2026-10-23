"""Finding 1 (LIGHTS2): an ambient edit must change what a creature can see on the very next read.

Fog perception is cached per match under the saved state_version, which set_match_ambient does not advance. The setter
must discard the fog answer as well as the light answer. The check is against a cold service loading the saved fight,
so a stale in-memory answer cannot pass.
"""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document

DAY = ambient_light("day")
NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}}


def _own_fog(table, mid):
    return table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))["fog_perception"][OWNER]


def test_an_ambient_edit_changes_the_fog_on_the_next_read(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    before = _own_fog(table, mid)

    table.set_match_ambient(mid, {"time_of_day": "night"})

    after = _own_fog(table, mid)
    cold = _own_fog(TabletopService(CombatService(ROOT, tmp_path), tmp_path), mid)
    assert after == cold, "the live read must match a cold reload of the saved fight"
    assert after != before, "day to night must change what a creature without Darkvision sees"


def test_night_to_day_restores_the_visibility_in_the_other_direction(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    before = _own_fog(table, mid)

    table.set_match_ambient(mid, {"time_of_day": "day"})

    after = _own_fog(table, mid)
    cold = _own_fog(TabletopService(CombatService(ROOT, tmp_path), tmp_path), mid)
    assert after == cold
    assert after != before
