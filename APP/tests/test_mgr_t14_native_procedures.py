"""Native source-procedure boundaries shared by the seven assigned rows.

These tests acquire real source rows and use public journey/controller intents.
They never inject ownership, conditions, event receipts or random results into
persisted state. Only the fixture's dice transport is controlled.
"""
from tests.test_mgr_t14_hunger_meals import (
    A as MEAL_OWNER, KEY, SAT, game as meal_game, portion, refine,
)


def test_native_refinement_hunger_check_keeps_actual_exhaustion_penalty(tmp_path, monkeypatch):
    import json
    from combat.journey_activity import replay_record
    from tests.test_mgr_t14_hunger_meals import CP
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
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    replayed = replay_record(committed)
    before = json.loads(committed['pre_state'])['actors'][MEAL_OWNER]
    assert replayed.actors[MEAL_OWNER].resources[CP] == before['resources'][CP] - 1
    assert replayed.actors[MEAL_OWNER].action_available == before['action_available']
    assert replayed.actors[MEAL_OWNER].turns_started == before['turns_started']
    assert state['seconds'] == 600, 'The ten-minute ritual grants no extra round or turn.'
    assert state['actors'][MEAL_OWNER]['resources'] == replayed.actors[MEAL_OWNER].resources
    assert cold().journey_state(jid) == state
