from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document

DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}}


def _try(label, fn, log):
    try:
        out = fn()
        log.append(label + ": ok")
        return out
    except Exception as exc:
        log.append(label + ": " + type(exc).__name__ + " " + str(exc)[:160])
        return None


def test_probe_day(tmp_path):
    log = []
    document = map_document(20, 12, ambient=ambient_light("day"), lights=[light(8, 6)])
    res = _try("fight", lambda: fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS), log)
    if res:
        combat, table, mid = res
        _try("read_own", lambda: table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,)), log)
        _try("read_all", lambda: table.state(mid, fog=True), log)
        _try("set", lambda: table.set_match_ambient(mid, {"time_of_day": "night"}), log)
    assert False, " || ".join(log)
