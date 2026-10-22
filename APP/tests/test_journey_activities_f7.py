"""Actual Duty work qualifies Merit recovery through committed journey commands."""
import pytest

from tests.test_journey_activities_native import (
    A, B, LEARN, DUTY, MERIT, BASE_REQUESTS, game, inst, work, ledger,
    catalog, controlling_source_base,
)


def prepare(tmp_path, monkeypatch, catalog, steps):
    cold, jid, act, world = game(tmp_path, monkeypatch, catalog)
    inst(world)
    act('long_rest')
    act('sect_role', {'role': 'Lecture Scribe', 'duty': 'copy records'})
    for _ in range(4):
        act('sect_petition', {'institution': 'hall', 'request': BASE_REQUESTS[0].text})
    world(LEARN, 'duty_plan', 'roster', {
        'obligation': 'copy the roster', 'institution': 'hall',
        'steps': [{'task': 'copy roster section', 'seconds': seconds} for seconds in steps],
    })
    act('sect_duty', {'scope': 'roster'})
    return cold, jid, act, world


@pytest.mark.parametrize('steps,good,expected', [
    ([600], 1, 4), ([300, 300], 1, 4), ([601], 1, 4),
    ([599], 1, 0), ([600], 0, 0),
])
def test_actual_duty_work_recovers_merit_without_separate_activity(
        tmp_path, monkeypatch, catalog, steps, good, expected):
    cold, jid, act, world = prepare(tmp_path, monkeypatch, catalog, steps)
    for step, seconds in enumerate(steps):
        state = work(act, DUTY, {'step': step}, seconds)
    duty = ledger(state)['duty']
    assert sum(row['worked_seconds'] for row in duty['completed']) == sum(steps)
    assert all(row['rest'] == state['actors'][A]['long_rests'] for row in duty['completed'])
    assert ledger(cold().journey_state(jid))['duty'] == duty
    assert 'recovery_work' not in ledger(state) and not duty['rewarded']
    assert not any(e['kind'] == 'ACTIVITY_STARTED' and e['activity']['source'] != DUTY
                   for e in state['events'])
    other = state['actors'][B]['resources'].copy()
    # Re-read current institutional facts, rather than trusting duty admission.
    inst(world, good=good)
    state = act('long_rest')
    assert state['actors'][A]['resources'][MERIT] == expected
    assert state['actors'][B]['resources'] == other
    assert len([e for e in state['events'] if e['kind'] == 'MERIT_RECOVERED']) == int(expected > 0)
    if expected:
        act('sect_petition', {'institution': 'hall', 'request': BASE_REQUESTS[0].text})
    state = act('long_rest')
    assert state['actors'][A]['resources'][MERIT] == max(0, expected - 1)
    assert len([e for e in state['events'] if e['kind'] == 'MERIT_RECOVERED']) == int(expected > 0)
    assert cold().journey_state(jid) == state
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_sub_ten_minute_away_duty_work_recovers_one_merit(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = prepare(tmp_path, monkeypatch, catalog, [60])
    context = {'away_from_all_institutions': 1, 'evidence': 'travel away from every hall'}
    world(LEARN, 'recovery_context', 'travel', context)
    inst(world, present=0, good=0)
    work(act, DUTY, {'step': 0}, 60)
    state = act('long_rest')
    assert state['actors'][A]['resources'][MERIT] == 1
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_duty_work_does_not_combine_across_long_rests(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = prepare(tmp_path, monkeypatch, catalog, [300, 300])
    work(act, DUTY, {'step': 0}, 300)
    assert act('long_rest')['actors'][A]['resources'][MERIT] == 0
    work(act, DUTY, {'step': 1}, 300)
    state = act('long_rest')
    assert state['actors'][A]['resources'][MERIT] == 0
    assert not any(e['kind'] == 'MERIT_RECOVERED' for e in state['events'])
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_unfinished_duty_work_after_ten_minutes_qualifies_recovery(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = prepare(tmp_path, monkeypatch, catalog, [1800])
    act('activity_start', {'source': DUTY, 'parameters': {'step': 0}})
    act('activity_work', {'seconds': 600})
    state = act('long_rest')
    assert ledger(state)['duty']['completed'] == []
    assert state['actors'][A]['resources'][MERIT] == 4
    assert ledger(state).get('duty_work') == []
    assert cold().journey_verify(jid)['status'] == 'PASS'


def test_unfinished_duty_work_does_not_qualify_recovery(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = prepare(tmp_path, monkeypatch, catalog, [600])
    act('activity_start', {'source': DUTY, 'parameters': {'step': 0}})
    act('activity_work', {'seconds': 599})
    state = act('long_rest')
    assert ledger(state)['duty']['completed'] == []
    assert state['actors'][A]['resources'][MERIT] == 0
    assert cold().journey_verify(jid)['status'] == 'PASS'
