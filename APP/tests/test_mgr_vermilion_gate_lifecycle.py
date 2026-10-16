"""A stationary Gate belongs to its journey, never to a fresh clock epoch."""
import json

import pytest

from tests.test_mgr_vermilion_gate_native import (
    A, B, C, PARENT, ROOT, STAMINA, CombatService, game, reload,
    stable_native_journey_identity,
)


@pytest.mark.parametrize('elapsed', [0, 59])
def test_finished_journey_retires_gate_before_cold_new_journey_combat(
    tmp_path, monkeypatch, elapsed,
):
    combat, _, _, jid = game(tmp_path, start_combat=False)
    state = combat.journey_state(jid)
    original_balance = state['actors'][A]['resources'][STAMINA]
    state = combat.journey_act(jid, state['revision'], A, 'gate_activate', {'allies': []})
    posts = json.loads(state['actors'][A]['source_states'][PARENT]['gate'])['posts']
    if elapsed:
        state = combat.journey_act(jid, state['revision'], A, 'wait', {'seconds': elapsed})
    # Finish before expiry, through a different creature's real command. Every
    # owner's scene-bound effect must be retired, not just the command actor's.
    combat = CombatService(ROOT, tmp_path)
    state = combat.journey_act(jid, state['revision'], B, 'finish', {})
    assert state['phase'] == 'finished'
    assert 'gate' not in state['actors'][A]['source_states'][PARENT]
    assert all(state['runtime_objects'][pid]['destroyed'] for pid in posts)
    ended = [e for e in state['events'] if e['kind'] == 'GATE_ENDED']
    assert len(ended) == 1 and ended[0]['actor_id'] == A
    assert ended[0]['reason'] == 'JOURNEY_FINISHED'
    combat = CombatService(ROOT, tmp_path)
    assert combat.journey_state(jid) == state

    monkeypatch.setattr('combat.journey.secrets.token_hex', lambda n: 'd' * 24)
    state = combat.create_journey(
        project_ids=['guardian', 'traveller', 'companion'],
        arena_id=state['battlefield']['stable_id'],
        positions={A: {'x': 3, 'y': 6}, B: {'x': 6, 'y': 6}, C: {'x': 3, 'y': 5}},
        base_paces={A: 100, B: 100, C: 100},
        control_modes={A: 'MANUAL', B: 'MANUAL', C: 'MANUAL'},
    )
    new_jid = state['journey_id']
    assert state['seconds'] == 0
    assert 'gate' not in state['actors'][A]['source_states'][PARENT]
    assert state['actors'][A]['source_states'][PARENT]['earned_level'] == 18
    assert state['actors'][A]['resources'][STAMINA] == original_balance - 7
    assert not set(posts).intersection(state.get('runtime_objects', {}))
    combat = CombatService(ROOT, tmp_path)
    assert combat.journey_state(new_jid) == state
    # The ordinary entry path used to raise KeyError for the old post IDs.
    mid = combat.journey_start_combat(
        new_jid, state['revision'], {A: 'team:a', B: 'team:b', C: 'team:a'},
    )['match_id']
    engine = reload(tmp_path, mid)
    assert '_round_closed_gate' not in engine.state.actors[A].turn_flags
    assert not set(posts).intersection(engine.state.objects)
    assert engine.state.actors[A].resources[STAMINA] == original_balance - 7
