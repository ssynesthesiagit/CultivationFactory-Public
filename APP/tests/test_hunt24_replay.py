"""Selected unowned AI fight captured before the reduction/text fixes."""
import hashlib
import copy
from combat.canonical import canonical_bytes
from tests.hunt24_support import table_fight, A, D


def capture(tmp_path):
    svc, table, mid = table_fight(tmp_path)
    for aid in (A, D):
        svc.set_controller_mode(mid, actor_id=aid, controller_mode='LOCAL_AUTO')
    steps = 0
    for _ in range(8):
        state = table.state(mid)
        if state['menu'].get('terminal'):
            break
        result = table.auto_step(mid, state['last_sequence'], [])
        assert result['status'] == 'COMMITTED'
        steps += 1
    loaded = svc._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    events = [e.model_dump(mode='json') for e in loaded.engine.events]
    return steps, events


def test_unowned_ai_events_match_before_fix_capture(tmp_path):
    steps, events = capture(tmp_path)
    assert steps == 8
    # New 25.x service fights explicitly record the approved 2024 dying rule.
    # Pin the complete raw stream, including that new genesis field.
    assert hashlib.sha256(canonical_bytes(events)).hexdigest() == '659e837747c4f8db852c00d060fb4f73a8891e7f644343d7f9ee6e15583b544e'
    created = [event for event in events if event['event_type'] == 'MATCH_CREATED']
    assert len(created) == 1 and created[0]['payload']['rules'] == {'zero_hp': 'dying_2024'}
    # Prove this explicit field is the ONLY difference from the historical
    # b174bec5 capture: every other event byte, payload and ordering stays pinned.
    historical = copy.deepcopy(events)
    next(event for event in historical if event['event_type'] == 'MATCH_CREATED')['payload'].pop('rules')
    assert hashlib.sha256(canonical_bytes(historical)).hexdigest() == '14c238aa07f560ed4b6ff7d7968719cc4d209da3630532219d0b7fd663c568d8'
