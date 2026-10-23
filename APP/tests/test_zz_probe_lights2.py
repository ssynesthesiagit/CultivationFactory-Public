from combat.gate5_service import CombatService
from combat.saved_fight_format import UnsupportedSavedFight
from combat.tabletop_service import TabletopService
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document

DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}}


def test_probe(tmp_path):
    document = map_document(20, 12, ambient=ambient_light("day"), lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    reasons = []
    try:
        table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))
        reasons.append("read1 ok")
    except UnsupportedSavedFight as exc:
        reasons.append("read1 " + exc.reason)
    try:
        table.set_match_ambient(mid, {"time_of_day": "night"})
        reasons.append("set ok")
    except Exception as exc:
        reasons.append("set " + repr(exc)[:300] + " " + str(getattr(exc, "reason", "")))
    try:
        CombatService(combat.source_root, tmp_path)._load_session(mid)
        reasons.append("cold ok")
    except UnsupportedSavedFight as exc:
        reasons.append("cold " + exc.reason)
    assert False, " || ".join(reasons)
