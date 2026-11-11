"""Accomplice chooses one participant, not every nearby ally."""
import pytest

from combat import ext
from tests.hunt19_support import fight, send, reload, LEFT
from tests.test_lock2_persistence import act

KEY = 'TAL_BEASTMASTERY_ACCOMPLICE'


def benefits(engine):
    return [(actor.entity_id, mod) for actor in engine.state.actors.values() for mod in actor.modifiers.values()
            if mod.source_definition_id.endswith(KEY) and mod.target_field == 'attack_mode']


@pytest.mark.parametrize('condition', ['incapacitated', 'stunned', 'paralyzed'])
def test_incapacitated_beast_can_receive_but_cannot_give_help_after_reload(tmp_path, monkeypatch, condition):
    from combat.ext.beastmastery_riders import accomplice_partners
    from combat.ext.needle import incapacitated

    combat, table, mid = fight(tmp_path, [KEY], rider=True)
    ext.effects()
    def disable_beasts(engine, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == LEFT:
            for beast in accomplice_partners(engine, engine.state.actors[LEFT]):
                engine._apply_condition(beast, 'condition:typed.' + condition, 'test:accomplice', LEFT,
                                        expires_on='UNTIL_REMOVED', data={'label': condition.title()})
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS['event'], disable_beasts])
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    beasts = accomplice_partners(engine, engine.state.actors[LEFT])
    assert beasts and all(incapacitated(beast) for beast in beasts)
    sender = send(table, mid, 'Accomplice')
    first = sender([])
    assert first['status'] == 'REACTION_REQUIRED'
    prompt = first['reaction']
    options = prompt['choice']['options']
    assert {o['id'] for o in options} == {'help:' + beast.entity_id for beast in beasts}
    result = sender([{**prompt['context'], 'selection': 'USE', 'option_ids': [options[0]['id']]}])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert all(incapacitated(engine.state.actors[beast.entity_id]) for beast in beasts)
    rows = benefits(engine)
    assert len(rows) == 1 and rows[0][0] == options[0]['id'].removeprefix('help:')
    assert not any(actor == LEFT for actor, _ in rows)


@pytest.mark.parametrize('invalid', ['incapacitated_helper', 'incapacitated_owner', 'unknown_selection'])
def test_accomplice_revalidates_helper_when_resolving_selection(tmp_path, monkeypatch, invalid):
    from types import SimpleNamespace
    from combat.ext import beastmastery_riders, needle

    combat, table, mid = fight(tmp_path, [KEY], rider=True)
    engine = reload(combat, tmp_path, mid)
    owner = engine.state.actors[LEFT]
    beast = beastmastery_riders.accomplice_partners(engine, owner)[0]
    def stale_choice(*args, **kwargs):
        if invalid == 'unknown_selection':
            return ['receive:missing-beast']
        helper = beast if invalid == 'incapacitated_helper' else owner
        engine._apply_condition(helper, 'condition:typed.incapacitated', 'test:accomplice', LEFT,
                                expires_on='UNTIL_REMOVED', data={})
        return [('receive:' if helper is beast else 'help:') + beast.entity_id]
    monkeypatch.setattr(needle, 'ask', stale_choice)
    ctx = SimpleNamespace(typed={'source': KEY}, engine=engine, actor=owner, intent=None, source=KEY)
    assert beastmastery_riders.accomplice_recipient(ctx, {'recipient_choice': 'accomplice'}) == []


@pytest.mark.parametrize('direction', ['help', 'receive'])
def test_accomplice_asks_for_one_beast_and_one_direction(tmp_path, direction):
    combat, table, mid = fight(tmp_path, [KEY], rider=True)
    sender = send(table, mid, 'Accomplice')
    first = sender([])
    assert first['status'] == 'REACTION_REQUIRED'
    prompt = first['reaction']
    assert 'Accomplice' in prompt['reaction'] and 'Advantage' in prompt['summary']
    options = prompt['choice']['options']
    assert len(options) == 4  # Wolf or Warhorse, helping the beast or being helped.
    chosen = next(o for o in options if o['id'].startswith(direction + ':') and 'wolf' in o['id'])
    result = sender([{**prompt['context'], 'selection': 'USE', 'option_ids': [chosen['id']]}])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    rows = benefits(engine)
    assert len(rows) == 1
    assert rows[0][0] == (LEFT if direction == 'receive' else chosen['id'].removeprefix('help:'))
    assert rows[0][1].applies_to == 'NEXT_ATTACK' and rows[0][1].expires_on == 'END_OF_CURRENT_TURN'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert benefits(reload(combat, tmp_path, mid)) == []


def test_accomplice_ai_selects_one_recipient_without_prompt(tmp_path, monkeypatch):
    ext.effects()
    hooks = list(ext._HOOKS.get('ai_candidate_allowed', []))
    # Constrain the AI's action to the bug trigger, not its recipient decision.
    def choose_action(engine, actor, candidate, action):
        if actor.entity_id == LEFT and candidate.kind == 'ACTION':
            return False if action is None or action.display_name != 'Accomplice' else None
    monkeypatch.setitem(ext._HOOKS, 'ai_candidate_allowed', [*hooks, choose_action])
    compiler_hooks = list(ext._HOOKS['compile_action'])
    def prioritize(action, info):
        if action.display_name == 'Accomplice':
            return action.model_copy(update={'parameters': {**action.parameters, 'expected_damage': 1000}})
    monkeypatch.setitem(ext._HOOKS, 'compile_action', [*compiler_hooks, prioritize])
    combat, table, mid = fight(tmp_path, [KEY], rider=True, mode='LOCAL_AUTO', ask=False)
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED'
    assert len(benefits(reload(combat, tmp_path, mid))) == 1
