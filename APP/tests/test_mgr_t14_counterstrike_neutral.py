"""Neutral creatures remain legal perceivable Counterstrike triggers."""
import pytest

from tests.test_mgr_t14_counterstrike_phases import BASE, REACTION, prepare
from tests.worker2_support import fixture, candidate, turn, reload, OWNER, FOE


@pytest.mark.parametrize('use', [False, True])
def test_neutral_speech_offers_a_manual_counterstrike_before_finishing(tmp_path, use):
    from combat.relations import relation, NEUTRAL

    combat, table, mid = fixture(tmp_path, [BASE], cl=6,
        foe_position={'x': 3, 'y': 5}, team_overrides={FOE: 'team:neutral'}, extra_foes=1)
    prepare(combat, table, mid, 'speech')
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert relation(engine, engine.state.actors[OWNER], engine.state.actors[FOE]) == NEUTRAL
    seq = engine.state.event_sequence
    selected = candidate(combat, mid, 'Speak audibly')
    answers, prompts = [], []
    for _ in range(10):
        menu = table.state(mid)['menu']
        result = table.act(mid, selected.candidate_id, menu['decision_id'], menu['state_version'], 0,
            answers, source_choices={'system:combat.speak': {'text': 'I am passing through.'}})
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        assert prompt['context']['reaction_source_id'] == REACTION
        assert prompt['context']['reactor_id'] == OWNER
        answers.append({**prompt['context'], 'selection': 'USE' if use else 'DECLINE'})
    else:
        raise AssertionError('Neutral speech did not finish')
    assert len(prompts) == 1
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > seq]
    began = next(e for e in events if e.event_type == 'SPEECH_BEGUN')
    finished = next(e for e in events if e.event_type == 'SPEECH_FINISHED')
    attacks = [e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(attacks) == int(use)
    if use:
        assert attacks[0].target_ids == (FOE,)
        assert began.sequence < attacks[0].sequence < finished.sequence
    else:
        assert any(c.condition_id == 'condition:typed.prepared_action'
                   for c in engine.state.actors[OWNER].conditions.values())
