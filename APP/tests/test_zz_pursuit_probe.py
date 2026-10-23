from tests.test_mgr_t15_pursuit_horizon import *  # noqa
from tests.test_mgr_t15_pursuit_horizon import fight, move, turn, chase_events, OWNER, FOE, PURSUIT


def test_probe(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    engine, prompts = move(tmp_path, mid, 7)
    engine, prompts = move(tmp_path, mid, 8, pending=True)
    lines = []
    for e in engine.events[-80:]:
        if e.event_type in ('INTENT_ACCEPTED','TURN_STARTED','STATE_SNAPSHOT'):
            continue
        lines.append(f"{e.sequence} {e.event_type} src={e.source_definition_id} actor={e.actor_id} payload={str(e.payload)[:300]}")
    raise AssertionError("PROBE\n" + "\n".join(lines) + "\nPROMPTS " + str([p.get('choice', {}).get('name') if isinstance(p, dict) else p for p in prompts])[:500])
