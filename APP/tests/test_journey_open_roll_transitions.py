"""A journey-wide phase change must not strand another creature's roll."""
import pytest

from tests.test_journey_rolls import A, B, HEART, events, game, task


@pytest.mark.parametrize('transition', ['finish', 'enter_combat', 'start_combat'])
def test_other_creature_cannot_leave_travel_with_a_roll_open(tmp_path, monkeypatch, transition):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART])
    task(admit)
    act('roll_check', {'task': 'plea'})
    before = cold().journeys.load(jid).state
    with pytest.raises(ValueError, match='open roll'):
        if transition == 'start_combat':
            cold().journey_start_combat(jid, before['revision'], {A: 'one', B: 'two'})
        else:
            act(transition, aid=B)
    after = cold().journeys.load(jid).state
    assert after == before
    assert after['phase'] == 'travel' and after['actors'][A]['pending_roll']
    act('roll_decide', {'offer': ''})
    assert events(cold, jid, 'CHECK_RESOLVED')
    if transition != 'start_combat':
        assert act(transition, aid=B)['phase'] == ('finished' if transition == 'finish' else 'combat')
