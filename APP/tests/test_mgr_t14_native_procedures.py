"""Native source-procedure boundaries shared by the seven assigned rows.

These tests acquire real source rows and use public journey/controller intents.
They never inject ownership, conditions, event receipts or random results into
persisted state. Only the fixture's dice transport is controlled.
"""
import json
import pytest

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


@pytest.mark.parametrize('demon', [0, 1])
def test_native_mantle_continues_and_settles_its_real_meal_at_exact_travel_expiry(tmp_path, monkeypatch, demon):
    from tests.test_mgr_t14_hunger_meals import A, CP, IMP, game, journey_activity
    from fractions import Fraction
    from combat.journey_activity import load, replay_record
    from combat.ext.hunger_riders import MANTLE as HELD
    cold, jid, command = game(tmp_path, monkeypatch)
    benefits = ['Thick Hide', 'Beast Strength'] if demon else ['Thick Hide']
    command('record_essence_portion', portion(demon_beast=demon, benefits=benefits))
    refine(command)
    command('refine_reward', {'reward': 'free_mantle'})
    native = load(cold().journeys.load(jid))
    name = 'Digestive Mantle: Demon-Beast Course' if demon else 'Digestive Mantle: Thick Hide'
    candidate = next(c for c in native.legal_candidates() if c.display_name == name)
    state = journey_activity(cold, jid, A, {'candidate_id': candidate.candidate_id})
    committed = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ACTIVITY_COMMITTED')
    actor = replay_record(committed).actors[A]
    held = next(c for c in actor.conditions.values() if c.condition_id == HELD)
    assert held.data['meal_source']['portion_id'] == 'portion-1' and actor.resources[SAT] == 0
    assert len(held.data['benefits']) == 1 + demon
    state = command('native_activity_end')
    rows = state['actors'][A]['source_states']['hunger.mantle_continuation']
    main = next(row for row in rows if row['kind'] == 'condition' and json.loads(row['instance'])['condition_id'] == HELD)
    deadline = Fraction(*main['deadline'])
    session = cold().journeys.load(jid)
    remaining = deadline - session.clock()
    assert remaining.denominator == 1 and remaining > 1
    before_cp = state['actors'][A]['resources'][CP]
    state = command('wait', {'seconds': int(remaining) - 1})
    cold_actor = load(cold().journeys.load(jid)).state.actors[A]
    assert any(c.condition_id == HELD for c in cold_actor.conditions.values())
    assert cold_actor.resources[IMP] == 0 and cold_actor.resources[CP] == before_cp
    state = command('wait', {'seconds': 1})
    expiry = next(e for e in reversed(state['events']) if e['kind'] == 'NATIVE_ELAPSED_EFFECTS_COMMITTED')
    replayed = replay_record(expiry)
    assert replayed.actors[A].resources[IMP] == demon
    assert not any(c.condition_id == HELD for c in replayed.actors[A].conditions.values())
    assert any(row['runtime_instance_id'] != row['instance_id'] for row in expiry['timer_references'])
    after = load(cold().journeys.load(jid)).state.actors[A]
    assert not any(c.condition_id == HELD for c in after.conditions.values())
    assert after.resources[IMP] == demon and after.resources[CP] == before_cp and after.resources[SAT] == 0
    assert not state['actors'][A]['travel_uses'][KEY]['charges']
    assert cold().journey_state(jid) == state
