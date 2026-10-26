"""Identical free effects share presentation, retaining independent grants."""
from types import SimpleNamespace
import pytest

from combat.ext import free_uses, states
from combat.gate2_runtime_models import ActionDefinition, EconomyKind


def compile_copies(*, second_range=None):
    action = ActionDefinition(source_definition_id='action:test.current',
        display_name='Test Current: Press', owner_id='actor:test',
        economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED',
        target_kind='CELL', range_ft=30,
        parameters={'typed': {'source': 'TEST_CURRENT', 'effects': []}})
    info = {'owned_ids': ['grant:a', 'grant:b'], 'actions': [action], 'mechanics': {}}
    for key, name in [('grant:a', 'court'), ('grant:b', 'incarnation')]:
        row = {'type': 'state', 'name': name,
               'free_use': [{'of': ['Test Current'], 'once': 'turn'}]}
        if key == 'grant:b' and second_range is not None:
            row['range_for'] = {'TEST_CURRENT': second_range}
        info['mechanics'][key] = {'effects': [row]}
    return free_uses._free_copies(info)


def test_identical_effect_is_one_row_with_both_grants(monkeypatch):
    rows = compile_copies()
    assert len(rows) == 1
    action = rows[0]
    rule = action.parameters['free_use']
    assert [g['state'] for g in rule['grants']] == ['court', 'incarnation']
    assert [g['key'] for g in rule['grants']] == ['grant:a:0', 'grant:b:1']
    engine = SimpleNamespace(state=SimpleNamespace(round_number=1))
    actor = SimpleNamespace(turn_flags={}, entity_id='actor:test', display_name='Test actor')
    active = {'court', 'incarnation'}
    monkeypatch.setattr(states, 'active', lambda e, a, name: {} if name in active else None)
    ctx = SimpleNamespace(engine=engine, actor=actor, action=action)
    assert free_uses._offered_while_the_state_lasts(engine, actor, None, action) is None
    free_uses._spend_the_free_use(ctx)
    assert actor.turn_flags == {'free_use_grant:a:0': True}
    assert free_uses._offered_while_the_state_lasts(engine, actor, None, action) is None
    free_uses._spend_the_free_use(ctx)
    assert actor.turn_flags['free_use_grant:b:1'] is True
    assert free_uses._offered_while_the_state_lasts(engine, actor, None, action) is False
    actor.turn_flags.clear()
    active.clear()
    assert free_uses._offered_while_the_state_lasts(engine, actor, None, action) is False
    active.add('incarnation')
    free_uses._spend_the_free_use(ctx)
    assert actor.turn_flags == {'free_use_grant:b:1': True}


def test_different_range_keeps_distinct_effect_rows():
    rows = compile_copies(second_range=60)
    assert len(rows) == 2
    assert [r.range_ft for r in rows] == [30, 60]


@pytest.mark.parametrize('reverse', [False, True])
def test_equal_range_ranged_and_unranged_grants_keep_their_own_gates(reverse):
    action = ActionDefinition(source_definition_id='action:test.current',
        display_name='Test Current', owner_id='actor:test', economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='CELL', range_ft=30,
        parameters={'typed': {'source': 'TEST_CURRENT', 'range_ft': 30, 'effects': []}})
    keys = ['plain', 'ranged'][::(-1 if reverse else 1)]
    rows = free_uses._free_copies({'owned_ids': keys, 'actions': [action], 'mechanics': {
        'plain': {'effects': [{'type': 'state', 'name': 'plain', 'free_use': [{'of': ['Test Current']}]}]},
        'ranged': {'effects': [{'type': 'state', 'name': 'ranged', 'range_for': {'TEST_CURRENT': 30},
                               'free_use': [{'of': ['Test Current']}]}]}}})
    assert len(rows) == 2
    by_state = {row.parameters['free_use']['state']: row for row in rows}
    assert 'state_range_rule' not in by_state['plain'].parameters
    assert by_state['ranged'].parameters['state_range_rule'] == {'states': ['ranged']}


@pytest.mark.parametrize('reverse', [False, True])
def test_free_copy_retains_inherited_range_states_not_grant_states(monkeypatch, reverse):
    action = ActionDefinition(source_definition_id='action:test.range',
        display_name='Test Current', owner_id='actor:test', economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='CELL', range_ft=60,
        parameters={'typed': {'source': 'TEST_CURRENT', 'range_ft': 60, 'effects': []},
                    'state_range_rule': {'state': 'range_court'}})
    keys = ['grant:a', 'grant:b'][::(-1 if reverse else 1)]
    rows = free_uses._free_copies({'owned_ids': keys, 'actions': [action], 'mechanics': {
        key: {'effects': [{'type': 'state', 'name': key,
                           'free_use': [{'of': ['Test Current']}]}]} for key in keys}})
    assert len(rows) == 1
    row = rows[0]
    assert row.parameters['state_range_rule'] == {'states': ['range_court']}
    actor = SimpleNamespace(turn_flags={}, conditions={})
    engine = SimpleNamespace(state=SimpleNamespace(round_number=1))
    active = {'grant:a', 'grant:b'}
    monkeypatch.setattr(states, 'active', lambda e, a, name: {'active': True} if name in active else None)
    assert states.state_range_candidates(engine, actor, None, row) is False
    active.add('range_court')
    assert states.state_range_candidates(engine, actor, None, row) is None
