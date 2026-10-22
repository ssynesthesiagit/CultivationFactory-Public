"""Opt-in nested subscribers see resource/damage cascades in deterministic order."""
import pytest

from combat import ext
from combat.ext import ControllerPause
from combat.gate5_service import CombatService
from tests.test_auto_tabik import _engine, ME
from tests.test_lock2_persistence import table_match, ROOT, act
from tests.test_lock_choices import install


def subscribe(monkeypatch, *functions):
    install(monkeypatch, 'event', functions[0])
    monkeypatch.setitem(ext._HOOKS, 'event', list(functions))
    monkeypatch.setitem(ext._NESTED_HOOKS, 'event', set(functions[1:]))


def test_nested_order_and_legacy_subscribers_are_unchanged(monkeypatch):
    order = []
    def ordinary(engine, kind, kwargs):
        order.append(('ordinary', kind))
        if kind == 'TEST_ROOT':
            engine._append_event('TEST_CHILD', 'test:cascade')
    def nested(engine, kind, kwargs):
        order.append(('nested', kind))
    subscribe(monkeypatch, ordinary, nested)
    engine, _ = _engine([])
    order.clear()
    engine._append_event('TEST_ROOT', 'test:cascade')
    assert order == [('ordinary', 'TEST_ROOT'), ('nested', 'TEST_CHILD'), ('nested', 'TEST_ROOT')]


def test_nested_cascade_is_bounded_and_cleanup_survives_pause(monkeypatch):
    def ordinary(*args):
        return None
    def recursive(engine, kind, kwargs):
        if kind == 'TEST_LOOP':
            engine._append_event(kind, 'test:loop')
        if kind == 'TEST_PAUSE':
            raise ControllerPause('choose')
    subscribe(monkeypatch, ordinary, recursive)
    engine, _ = _engine([])
    n = len(engine.events)
    engine._append_event('TEST_LOOP', 'test:loop')
    events = engine.events[n:]
    assert len([e for e in events if e.event_type == 'TEST_LOOP']) == 9
    assert len([e for e in events if e.event_type == 'GM_RIDER']) == 1
    assert engine._ext_event_depth == 0
    before = engine.state.model_dump(mode='json')
    with pytest.raises(ControllerPause):
        with engine._transaction('test:pause', 'test:pause', ME):
            engine._append_event('TEST_PAUSE', 'test:pause')
    assert engine.state.model_dump(mode='json') == before
    assert engine._ext_event_depth == 0


def test_explicit_prefight_suppression_still_blocks_all_subscribers(monkeypatch):
    seen = []
    def subscriber(engine, kind, kwargs):
        seen.append(kind)
    subscribe(monkeypatch, subscriber, subscriber)
    engine, _ = _engine([])
    seen.clear()
    engine._ext_in_event = True
    engine._append_event('TEST_PREFIGHT', 'test:prefight')
    assert seen == []
    assert engine.events[-1].event_type == 'TEST_PREFIGHT'
    assert engine._ext_in_event is True
    engine._ext_in_event = False
    engine._append_event('TEST_NORMAL', 'test:prefight')
    assert seen == ['TEST_NORMAL', 'TEST_NORMAL']


def test_nested_spend_damage_control_break_crosses_table_commit_and_reload(monkeypatch, tmp_path):
    condition = 'condition:typed.test_control'
    def initialise(engine):
        for actor in engine.state.actors.values():
            if not actor.turn_flags.get('_round_test_control_created'):
                actor.turn_flags['_round_test_control_created'] = 1
                engine._apply_condition(actor, condition, 'test:control', actor.entity_id, expires_on='UNTIL_REMOVED')
    install(monkeypatch, 'match_start', initialise)
    def ordinary(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED':
            engine._spend_resource(engine.state.actors[kwargs['actor_id']], 'resource:core.stamina', 1, 'test:spend')
    def damage(engine, kind, kwargs):
        if kind == 'RESOURCE_SPENT' and kwargs['payload']['resource_id'] == 'resource:core.stamina':
            actor = engine.state.actors[kwargs['actor_id']]
            engine._commit_damage(actor, 1, 'UNTYPED', 'test:damage', actor.entity_id, None, reaction_depth=3)
    def control(engine, kind, kwargs):
        if kind == 'DAMAGE_COMMITTED':
            for target in kwargs['target_ids']:
                engine._remove_condition(engine.state.actors[target], condition, 'test:break')
    subscribe(monkeypatch, ordinary, damage, control)
    combat, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)['menu']['actor_id']
    before = combat._load_session(mid).engine.state.actors[actor_id]
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[actor_id]
    assert actor.resources['resource:core.stamina'] == before.resources['resource:core.stamina'] - 1
    assert actor.current_hp == before.current_hp - 1
    assert not any(c.condition_id == condition for c in actor.conditions.values())
    assert len([e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED']) == 1
    assert loaded.mechanical.replay()['status'] == 'PASS'
