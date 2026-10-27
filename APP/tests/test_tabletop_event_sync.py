"""The public event cursor is shared by manual and automatic commit writers."""
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import act, table_match


def assert_sequences(response, after):
    sequences = [row['sequence'] for row in response['events']]
    assert sequences, 'the committed turn has visible events'
    assert all(type(sequence) is int and sequence > after for sequence in sequences)
    assert sequences == sorted(set(sequences))
    assert sequences == [row['event_sequence'] for row in response['events']]
    assert response['last_sequence'] >= sequences[-1]
    assert type(response['state_version']) is int


def test_committed_turn_feed_sequences_survive_service_reload(tmp_path):
    combat, table, mid = table_match(tmp_path)
    after = table.events(mid, 0)['last_sequence']
    act(table, mid, 'end')
    response = table.events(mid, after)
    assert_sequences(response, after)
    reloaded = TabletopService(combat, tmp_path).events(mid, after)
    assert reloaded == response
    assert table.events(mid, response['last_sequence'])['events'] == []


def test_auto_step_feed_uses_the_same_monotonic_cursor(tmp_path):
    from tests.test_hunt5_player_choices import FOE, fixture

    combat, table, mid, *_ = fixture(tmp_path, 'AIR_BASE_GATHER_CURRENT')
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    after = table.events(mid, 0)['last_sequence']
    result = table.auto_step(mid, after, [])
    assert result['status'] == 'COMMITTED'
    assert_sequences(result['events'], after)
    assert table.events(mid, after) == result['events']


def test_model_seat_commits_advance_the_public_event_cursor(tmp_path):
    from tests.test_agent_seats import raw_state, runner_for
    from tests.test_hunt5_player_choices import FOE, PLAYER, fixture

    _, table, mid, *_ = fixture(tmp_path, 'AIR_BASE_GATHER_CURRENT')
    runner, fake = runner_for(tmp_path, table)
    runner.set_seat(mid, FOE, 'MODEL', 'fake')
    after = raw_state(runner, mid)['last_sequence']
    assert runner.drive(mid, max_steps=1) == 1
    state = raw_state(runner, mid)
    assert state['menu']['actor_id'] == PLAYER
    response = table.events(mid, after)
    assert_sequences(response, after)
    assert response['last_sequence'] == state['last_sequence']
    assert response['state_version'] == state['menu']['state_version']
    assert len(fake.prompts) == 1
