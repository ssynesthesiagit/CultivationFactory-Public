"""Native source-procedure boundaries shared by the seven assigned rows.

These tests acquire real source rows and use public journey/controller intents.
They never inject ownership, conditions, event receipts or random results into
persisted state. Only the fixture's dice transport is controlled.
"""
from combat.journey_activity import load, replay_record
from tests.test_mgr_t14_spiritual_state import (
    A, B, SPIKE, WINGS, game as spirit_game, activity_act, spirit_acquisition,
)
from tests.test_mgr_t14_hunger_meals import (
    A as MEAL_OWNER, KEY, SAT, REFINE, game as meal_game, portion, refine,
)


def test_native_closed_contexts_keep_distinct_identity_and_roll_receipts(tmp_path, monkeypatch):
    cold, _, _, jid = spirit_game(tmp_path, monkeypatch, [SPIKE, WINGS], activity=True)
    state = cold().journey_state(jid)
    state = cold().journey_world_fact(jid, state['revision'], {
        'source': 'system:journey.activity', 'subject': A, 'kind': 'relations', 'scope': jid,
        'value': {'actors': {min(A, B): {max(A, B): 'ENEMY'}}}, 'expires_at': 86400, 'readers': [A, B]})
    records = []
    for _ in range(2):
        native = load(cold().journeys.load(jid))
        strike = next(c for c in native.legal_candidates() if c.display_name == 'Mind Spike' and c.target_ids == (B,))
        state, _ = activity_act(cold, jid, A, strike.candidate_id)
        committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
        replayed = replay_record(committed)
        assert load(cold().journeys.load(jid)).state.model_dump(mode='json') == replayed.model_dump(mode='json')
        records.append((replayed.match_id, {roll['roll_id'] for roll in committed['rolls']}))
        state = cold().journey_act(jid, state['revision'], A, 'native_activity_end', {})
        assert cold().journey_state(jid) == state
    assert records[0][0] != records[1][0], 'A later native context must not reuse the previous match identity.'
    assert records[0][1] and records[1][1] and records[0][1].isdisjoint(records[1][1]), 'Committed d20/damage receipts must not repeat after closing native activity.'


def test_native_refinement_hunger_check_keeps_actual_exhaustion_penalty(tmp_path, monkeypatch):
    cold, jid, command = meal_game(tmp_path, monkeypatch, natural=6)
    command('travel_exhaustion', {'levels': 1, 'ordinary': True})
    state = cold().journey_state(jid)
    assert state['actors'][MEAL_OWNER]['exhaustion'] == 1
    command('record_essence_portion', portion())
    state = refine(command)
    event = next(e for e in reversed(state['events']) if e['kind'] == 'MEAL_REFINED')
    assert event['dc'] == 12 and event['roll']['total'] == 10
    assert event['margin'] == -2 and state['actors'][MEAL_OWNER]['resources'][SAT] == 0
    assert not state['actors'][MEAL_OWNER]['travel_uses'][KEY]['portions']
    assert cold().journey_state(jid) == state
