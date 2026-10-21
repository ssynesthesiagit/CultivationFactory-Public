"""Public native regression for mixed-payment follow-ups and shared quote guards."""
import pytest

from tests.test_second_furnace_native import (
    OWNER, FOE, f, game, fight, turn, play, choose_seed, engine, verify,
)


def test_earned_devil_qi_mixed_journey_payment_can_resolve_both_followups(tmp_path, monkeypatch):
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=18, seed='f16-mixed-followups')
    mid = fight(cold, jid, maximum_rounds=1)
    turn(cold, tmp_path, mid, OWNER)
    play(cold, tmp_path, mid, 'Force Mantle', select=choose_seed)
    assert engine(cold, mid).state.actors[OWNER].resources[f.DEVIL] == 2
    for _ in range(4):
        if engine(cold, mid).state.terminal_result:
            break
        play(cold, tmp_path, mid, end=True)
    assert engine(cold, mid).state.terminal_result
    verify(cold, mid)
    state = cold().journey_state(jid)
    cold().journey_resume(jid, state['revision'])

    menu = cold().journey_menu(jid, OWNER)
    payment = next(row for row in menu['options'] if row['kind'] == 'furnace_engine'
                   and row['payload'] == {'payment': 'seed:core:1'})
    cold().journey_act(jid, menu['revision'], OWNER, payment['kind'], payment['payload'])
    before = cold().journey_state(jid)
    native = before['actors'][OWNER]['source_states'][f.PARENT]
    assert native['core_motion_pending'] == native['seed_reinforcement_pending'] == 1
    # Neither another actor nor an unrelated command can skip an earned choice.
    for aid in (OWNER, FOE):
        with pytest.raises(ValueError, match='before continuing'):
            cold().journey_act(jid, before['revision'], aid, 'wait', {'seconds': 1})
        assert cold().journey_state(jid) == before

    for kind, benefit in (('furnace_core_motion', 'temp_hp'),
                          ('furnace_seed_reinforcement', 'advantage')):
        menu = cold().journey_menu(jid, OWNER)
        option = next(row for row in menu['options'] if row['kind'] == kind
                      and row['payload'] == {'benefit': benefit})
        if benefit == 'temp_hp':
            assert 'Gain 8 Temporary Hit Points' in option['label']
        cold().journey_act(jid, menu['revision'], OWNER, kind, option['payload'])

    saved = cold().journey_state(jid)
    actor = saved['actors'][OWNER]
    native = actor['source_states'][f.PARENT]
    assert not native.get('core_motion_pending')
    assert not native.get('seed_reinforcement_pending')
    assert actor['encounter_snapshot']['temporary_hp'] == 8
    assert any(row['kind'] == 'seed_advantage' for row in native['continuation_conditions'])
    assert sum(row['kind'] == 'FURNACE_MOTION' for row in saved['events']) == 1
    assert sum(row['kind'] == 'SEED_FED_REINFORCEMENT' for row in saved['events']) == 1
    resumed = fight(cold, jid, maximum_rounds=1)
    assert f.condition(engine(cold, resumed).state.actors[OWNER],
                       'condition:typed.second_furnace_advantage')
    verify(cold, resumed)


@pytest.mark.parametrize('answers,expected', [([], True), ([True], True), ([False], False)])
def test_resource_quote_contract_preserves_default_and_explicit_denials(monkeypatch, answers, expected):
    from combat import resource_availability
    monkeypatch.setattr(resource_availability.ext, 'run_strict', lambda *args: answers)
    assert resource_availability.permits(None, None, 'test:source', [(f.QI, 1)]) is expected


@pytest.mark.parametrize('answer', [0, 1, 'yes', {}])
def test_resource_quote_contract_rejects_non_boolean_answers(monkeypatch, answer):
    from combat import resource_availability
    monkeypatch.setattr(resource_availability.ext, 'run_strict', lambda *args: [answer])
    with pytest.raises(ValueError, match='bool or None'):
        resource_availability.permits(None, None, 'test:source', [(f.QI, 1)])


def test_furnace_resource_gates_are_inert_for_a_native_nonowner(tmp_path, monkeypatch):
    from combat.ext.furnace_runtime import devil_expenditure, resource_availability_quote
    cold, jid, _, _ = game(tmp_path, monkeypatch, cl=3, seed='f16-nonowner')
    mid = fight(cold, jid)
    saved = engine(cold, mid)
    nonowner = saved.state.actors[FOE]
    for resource in (f.QI, f.DEVIL):
        assert devil_expenditure(saved, nonowner, resource, 1, 'test:source') is None
        assert resource_availability_quote(saved, nonowner, resource, 1, 'test:source') is None
    verify(cold, mid)


def test_resource_gate_contracts_document_provider_and_purity():
    from pathlib import Path
    contract = (Path(__file__).resolve().parents[1] / 'combat/ext/__init__.py').read_text()
    for point in ('resource_quote_allowed', 'resource_spend_allowed'):
        assert point + '(engine, actor, resource_id, amount, source_id) -> bool | None' in contract
    assert 'furnace_runtime' in contract
    assert 'Quotes must not mutate state or request decisions' in contract
