"""Formation Thread Relay asks on a table Pulse, persists, and consumes one origin."""
import pytest

from combat.ext.formation_talents import RELAY
from combat.gate5_service import CombatService
from tests.worker2_support import ROOT, OWNER, ALLY, FOE, fixture, candidate, turn, act, end_turn

TALENT = 'tianxia.talent.formations.formation_thread_relay'


@pytest.mark.parametrize('accept,use', [(True, True), (True, False), (False, False)])
def test_relay_pulse_choice_commit_reload_and_remote_attack(tmp_path, accept, use):
    combat, table, mid = fixture(tmp_path, [TALENT], ally_talents=['TAL_DESTRUCTION_DESTRUCTIVE_BLAST'], seed='AUTO30')
    set_array = candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6))
    assert act(table, mid, set_array.candidate_id)['status'] == 'COMMITTED'
    end_turn(table, mid)
    turn(table, mid, OWNER)
    pulse = candidate(combat, mid, 'Pulse: Nourishing Cycle', target=ALLY)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    result = act(table, mid, pulse.candidate_id)
    assert result['status'] == 'REACTION_REQUIRED', result
    context = result['reaction']['context']
    assert context['reaction_source_id'] == 'choice:needle.formation_thread_relay'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    assert act(table, mid, pulse.candidate_id)['reaction'] == result['reaction']
    answer = {**context, 'selection': 'USE' if accept else 'DECLINE', 'option_ids': [ALLY] if accept else []}
    assert act(table, mid, pulse.candidate_id, [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id.startswith(RELAY + '.') for c in loaded.engine.state.actors[ALLY].conditions.values()) == accept
    end_turn(table, mid)
    turn(table, mid, ALLY)
    if use:
        remote = candidate(combat, mid, 'Destructive Blast', target=FOE, remote=True)
        position = combat._load_session(mid).engine.state.actors[ALLY].position
        assert act(table, mid, remote.candidate_id)['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.engine.state.actors[ALLY].position == position
        assert not any(c.condition_id.startswith(RELAY + '.') for c in loaded.engine.state.actors[ALLY].conditions.values())
    elif not accept:
        assert not any(c.metadata.get('effect_origin') for c in combat._load_session(mid).engine.legal_candidates())
    else:
        assert candidate(combat, mid, 'Destructive Blast', target=FOE, remote=True)
        end_turn(table, mid)
        turn(table, mid, OWNER)
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert not any(c.condition_id.startswith(RELAY + '.') for c in loaded.engine.state.actors[ALLY].conditions.values())
    assert loaded.mechanical.replay()['status'] == 'PASS'
