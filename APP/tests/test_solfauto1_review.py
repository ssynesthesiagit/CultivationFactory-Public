"""SOLFAUTO1: real table choices, transaction rollback, journal replay and cold reload.

Synthetic affliction/save setup runs inside accepted Hold transactions, so replay
sees the same setup. No GUI or live userdata is used.
"""
import pytest

from combat import ext
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h48_table_support import OWNER, FOE, fixture, candidate, assert_reload_verify_replay
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.test_auto1_paths_a import MERIDIAN, TEMPERED, STAMINA, _meridian_fight


def cold(combat, mid, path):
    fresh = CombatService(combat.source_root, path)
    return fresh, TabletopService(fresh, path), fresh._load_session(mid).engine


def automatic_action(combat, source):
    """Choose one deterministic primary action; preserve the real reaction policy."""
    original = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            choice = next(c for c in context.legal_candidates if c.source_definition_id == source)
            return ManualControllerAdapter(lambda _: (choice.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = Controller()


@pytest.mark.parametrize('use,dc', [(False, 1), (True, 1), (True, 99)])
@pytest.mark.parametrize('name', ['poisoned', 'disease'])
def test_meridian_end_turn_choice_commit_reload(tmp_path, monkeypatch, use, dc, name):
    from combat.ext import needle
    from combat.ext.choice_costs import Payment

    original_ask = needle.ask
    quoted = []

    def capture_payment(*args, **kwargs):
        quoted.append(kwargs)
        return original_ask(*args, **kwargs)

    monkeypatch.setattr(needle, 'ask', capture_payment)
    combat, table, mid, send, commit = fixture(tmp_path, [], seed=f'SOLF-M-{use}-{dc}-{name}',
                                             path_features=[MERIDIAN], primary='Stamina')

    def afflict(engine):
        if engine.state.current_actor_id == OWNER:
            engine._apply_condition(engine.state.actors[OWNER], 'condition:typed.' + name,
                                    'test:affliction', FOE, expires_on='UNTIL_REMOVED',
                                    data={'origin_save': {'ability': 'CON', 'dc': dc},
                                          'repeat_save': {'ability': 'CON', 'dc': dc, 'when': 'start'}})

    on_hold(monkeypatch, afflict)
    commit(candidate(table, mid, 'Hold'))
    combat, table, engine = cold(combat, mid, tmp_path)
    before = engine.state.model_dump(mode='json')
    stamina = engine.state.actors[OWNER].resources[STAMINA]
    menu = table.state(mid)['menu']

    def end(answers=()):
        return table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, list(answers))

    result = end()
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['cost'] == '1 Stamina'
    assert quoted[-1].get('payment') == Payment(STAMINA, 1)
    assert quoted[-1].get('feature_id') == MERIDIAN
    assert 'No printed rule summary' not in prompt['summary']
    assert prompt['context']['reactor_id'] == OWNER
    assert 'Meridian Reinforcement' in prompt['trigger']
    assert 'poison or disease' in prompt['trigger'] and 'end of this turn' in prompt['trigger']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    # The pending prompt and uncommitted state survive an independent service load.
    combat, table, _ = cold(combat, mid, tmp_path)
    assert end()['reaction'] == prompt
    answer = {**prompt['context'], 'selection': 'USE' if use else 'DECLINE',
              'option_ids': [prompt['choice']['options'][0]['id']] if use else []}
    assert end([answer])['status'] == 'COMMITTED'
    assert_reload_verify_replay(combat, mid, tmp_path)
    _, _, engine = cold(combat, mid, tmp_path)
    actor = engine.state.actors[OWNER]
    assert actor.resources[STAMINA] == stamina - int(use)
    assert any(c.condition_id == 'condition:typed.' + name for c in actor.conditions.values()) == (not use or dc == 99)
    if use:
        stamp = actor.turn_flags['_round_meridian_reinforcement']
        assert type(stamp) is int and stamp == before['round_number']
        rolls = [r for r in engine.rolls if r.reason.startswith('SAVE:passive:meridian_reinforcement')]
        assert len(rolls) == 1 and rolls[0].mode == 'ADVANTAGE'


def test_meridian_compiled_passive_retains_display_name():
    from combat.ext.meridian_reinforcement import meridian_block

    row = meridian_block('meridian_reinforcement', {'name': 'Meridian Reinforcement'},
                         {'feature_id': MERIDIAN}, {})[0]
    assert row['name'] == 'Meridian Reinforcement'


def test_ai_meridian_decides_automatically(tmp_path, monkeypatch):
    combat, table, mid, send, commit = fixture(tmp_path, [], seed='SOLF-AI-M', path_features=[MERIDIAN], primary='Stamina')
    on_hold(monkeypatch, lambda engine: engine._apply_condition(
        engine.state.actors[OWNER], 'condition:typed.poisoned', 'test:poison', FOE,
        expires_on='UNTIL_REMOVED', data={'repeat_save': {'ability': 'CON', 'dc': 1, 'when': 'start'}}))
    commit(candidate(table, mid, 'Hold'))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine = combat._load_session(mid).engine
    end = next(c for c in engine.legal_candidates() if c.display_name == 'End turn')
    automatic_action(combat, end.source_definition_id)
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    assert_reload_verify_replay(combat, mid, tmp_path)
    assert not any(c.condition_id == 'condition:typed.poisoned'
                   for c in combat._load_session(mid).engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('data', [
    {'origin_save': {'ability': 'CON', 'dc': 1}},
    {'repeat_save': {'ability': 'CON', 'dc': 1}, 'ordinary_saves_cannot_remove': True},
    {'repeat_save': {'ability': 'CON', 'dc': 1, 'successes_required': 3}},
    {'repeat_save': {'ability': 'CON', 'dc': 1}, 'successes_required': 3, 'successes': 1},
])
def test_unknown_or_restricted_repeat_contract_is_not_spent_or_cured(data):
    engine, actor = _meridian_fight(dc=1)
    held = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.poisoned')
    held.data = data
    ext.run('turn_end', engine, actor)
    assert held.instance_id in actor.conditions and actor.resources[STAMINA] == 60


@pytest.mark.parametrize('disadvantage,mode', [(False, 'ADVANTAGE'), (True, 'NORMAL')])
def test_actual_paid_repeat_mode_and_cancellation(disadvantage, mode):
    engine, actor = _meridian_fight(dc=1)
    if disadvantage:
        engine._apply_condition(actor, 'condition:typed.test_save_penalty', 'test:penalty', actor.entity_id,
                                expires_on='UNTIL_REMOVED', data={'rule': {'save_mode': {'CON': 'DISADVANTAGE'}}})
    ext.run('turn_end', engine, actor)
    assert next(r for r in engine.rolls if r.reason.startswith('SAVE:passive:meridian_reinforcement')).mode == mode


def test_meridian_preserves_exhaustion_advantage_and_uncovered_progress():
    from combat.typed_reactions import rules
    engine, actor = _meridian_fight(dc=1)
    roll = engine._roll_save(actor, 'CON', 1, 'test:exertion', roll_context={'named': ['exhaustion']})
    assert roll.mode == 'ADVANTAGE'
    assert not any('multiple successful saves' in line or 'original effect would end' in line
                   for line in rules()['features'][MERIDIAN]['covers'])


