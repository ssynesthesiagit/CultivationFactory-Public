"""Owned Meat Shield explanations at the table choice boundary."""
from tests.hunt19_support import fight, send, reload, LEFT


def test_meat_shield_edge_explains_cover_cost_and_limit(tmp_path):
    combat, table, mid = fight(tmp_path, ['TAL_BEASTMASTERY_MEAT_SHIELD'], rider=True)
    sender = send(table, mid, 'Meat Shield')
    first = sender([])
    assert first['status'] == 'REACTION_REQUIRED'
    prompt = first['reaction']
    # Hunt10b's cover-direction name (round22 merge bb8f59ad) is retained
    # through prompt-ui's explicit choice-name presentation (f9685b35).
    assert prompt['reaction'] == 'Meat Shield: choose cover direction'
    assert 'Total Cover' in prompt['summary'] and 'cannot target you' in prompt['summary']
    assert 'Defensive Rider' in prompt['limits'] and 'until' in prompt['limits']
    assert prompt['cost'] == 'Bonus Action already spent; no resource cost'
    assert prompt['rules'] and 'Total Cover' in prompt['rules']
    assert all('attacks' in o['description'] for o in prompt['choice']['options'])
    result = sender([{**prompt['context'], 'selection': 'USE', 'option_ids': ['N']}])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    held = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == 'condition:typed.meat_shield')
    assert held.data['edge'] == 'N'


def test_meat_shield_ai_decides_edge_without_prompt(tmp_path, monkeypatch):
    from combat import ext
    ext.effects()
    hooks = list(ext._HOOKS['ai_candidate_allowed'])
    def choose_action(engine, actor, candidate, action):
        if actor.entity_id == LEFT and candidate.kind in ('ACTION', 'BONUS_ACTION'):
            return False if action is None or action.display_name != 'Meat Shield' else None
    monkeypatch.setitem(ext._HOOKS, 'ai_candidate_allowed', [*hooks, choose_action])
    compiler_hooks = list(ext._HOOKS['compile_action'])
    def prioritize(action, info):
        if action.display_name == 'Meat Shield':
            return action.model_copy(update={'parameters': {**action.parameters, 'expected_damage': 1000}})
    monkeypatch.setitem(ext._HOOKS, 'compile_action', [*compiler_hooks, prioritize])
    combat, table, mid = fight(tmp_path, ['TAL_BEASTMASTERY_MEAT_SHIELD'], rider=True, mode='LOCAL_AUTO', ask=False)
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.meat_shield' for c in engine.state.actors[LEFT].conditions.values())
