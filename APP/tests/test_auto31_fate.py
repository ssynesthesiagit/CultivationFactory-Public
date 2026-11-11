"""Incarnation flight and the next-check boon persist through real table actions."""
import pytest

from combat.flight import profile
from combat.gate5_service import CombatService
from combat.ext.fate_riders import BOON, SOVEREIGN
from tests.worker2_support import ROOT, OWNER, ALLY, fixture, candidate, act, end_turn

TALENT = 'TAL_FATE_FATE_SOVEREIGN_INCARNATION'


@pytest.mark.parametrize('owned', [True, False])
def test_sovereign_flight_commit_reload_and_inert_nonowner(tmp_path, owned):
    combat, table, mid = fixture(tmp_path, [TALENT] if owned else [], seed='AUTO31')
    if owned:
        cast = candidate(combat, mid, 'Fate-Sovereign Incarnation: Attack Penalty')
        assert act(table, mid, cast.candidate_id)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    flyer = profile(loaded.engine, loaded.engine.state.actors[OWNER])
    assert flyer.speed_ft == (40 if owned else 0)
    assert flyer.hover == owned
    if owned:
        start = loaded.engine.state.actors[OWNER].position
        move = next(c for c in loaded.engine.legal_candidates() if c.destination and c.destination.z == 1
                    and (c.destination.x, c.destination.y) == (start.x, start.y))
        assert act(table, mid, move.candidate_id)['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.engine.state.actors[OWNER].position.z == 1
        assert profile(loaded.engine, loaded.engine.state.actors[OWNER]).hover
        assert any(c.condition_id == SOVEREIGN and c.expires_on != 'UNTIL_REMOVED'
                   for c in loaded.engine.state.actors[OWNER].conditions.values())
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_sovereign_next_check_boon_choice_persists_and_is_consumed(tmp_path):
    combat, table, mid = fixture(tmp_path, [TALENT], ally_talents=['TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES'], seed='AUTO31-CHECK')
    cast = candidate(combat, mid, 'Fate-Sovereign Incarnation: No Reactions')
    assert act(table, mid, cast.candidate_id)['status'] == 'COMMITTED'
    prompts = []

    def send(cid):
        answers = []
        result = act(table, mid, cid)
        while result['status'] == 'REACTION_REQUIRED':
            context = result['reaction']['context']
            rid = context['reaction_source_id']
            prompts.append(rid)
            if rid == 'choice:needle.sovereign_ally':
                answer = {**context, 'selection': 'USE', 'option_ids': [ALLY]}
            elif rid == 'choice:needle.sovereign_boon':
                assert any(o['id'] == 'check' for o in result['reaction']['choice']['options'])
                answer = {**context, 'selection': 'USE', 'option_ids': ['check']}
            elif rid == 'choice:needle.eye_approach':
                answer = {**context, 'selection': 'USE',
                          'option_ids': [result['reaction']['choice']['options'][0]['id']]}
            else:
                assert rid == 'reaction:typed.TAL_FATE_TWIST_OF_FATE', rid
                answer = {**context, 'selection': 'DECLINE'}
            answers.append(answer)
            result = act(table, mid, cid, answers)
        assert result['status'] == 'COMMITTED'
        return result

    send(table.state(mid)['menu']['end_turn'])
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
        send(table.state(mid)['menu']['end_turn'])
    assert 'choice:needle.sovereign_boon' in prompts
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == BOON and c.data['boon'] == 'check'
               for c in loaded.engine.state.actors[ALLY].conditions.values())
    send(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != ALLY:
        send(table.state(mid)['menu']['end_turn'])
    search = candidate(combat, mid, 'Analyze')
    send(search.candidate_id)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [e for e in loaded.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == ALLY]
    assert rolls and rolls[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == BOON and c.data['boon'] == 'check'
                   for c in loaded.engine.state.actors[ALLY].conditions.values())
    assert loaded.mechanical.replay()['status'] == 'PASS'
