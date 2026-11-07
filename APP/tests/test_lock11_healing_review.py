"""Zero-HP outcomes and strict failures at actual event/turn-start boundaries."""
import pytest

from combat import ext
from combat.ext import life_state as life
from combat.ext.bodya_body_refining import CTE
from combat.gate5_service import CombatService, CombatServiceError
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, script
from tests.test_lock2_persistence import act
from tests.test_lock9_healing_interception import install, MARK

DEATHLESS = 'TAL_BERSERKER_DEATHLESS'


def down(engine, actor):
    engine._commit_damage(actor, actor.current_hp, 'FORCE', 'test:injury', H.RIGHT, None, reaction_depth=0)
    assert actor.current_hp == 0 and actor.life_state == 'DYING'


def due(engine, actor):
    assert life.stabilize(engine, actor, 'test:recovery')
    engine._remove_condition(actor, life.RECOVERY, 'test:deadline')
    engine._apply_condition(actor, life.RECOVERY, 'test:recovery', actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'round': engine.state.round_number,
        'slot': engine.state.current_slot_index, 'label': 'Deathless stable recovery'})


def before_ally(combat, table, mid):
    for _ in range(3):
        state = combat._load_session(mid).engine.state
        order = state.initiative_order
        if order[(state.current_slot_index + 1) % len(order)] == H.ALLY:
            return
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('The ally never received its turn')


@pytest.mark.parametrize('kind', ['natural20', 'timed'])
@pytest.mark.parametrize('denied', [False, True])
def test_zero_hp_recovery_bookkeeping_matches_actual_healing(monkeypatch, tmp_path, kind, denied):
    combat, table, mid = H.table_fight(tmp_path, [DEATHLESS])
    target_id = H.LEFT if kind == 'natural20' else H.ALLY
    install(monkeypatch, lambda *args: 1 if denied else 0)
    def recover(engine):
        actor = engine.state.actors[target_id]
        down(engine, actor)
        if kind == 'natural20':
            life._set_record(actor, 1, 2)
            script(engine, [20])
            life.death_save(engine, actor)
        else:
            due(engine, actor)
    H.on_hold(monkeypatch, recover)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    if kind == 'timed':
        before_ally(combat, table, mid)
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[target_id]
    assert actor.current_hp == (0 if denied else 1)
    assert actor.life_state == (('DYING' if kind == 'natural20' else 'STABLE') if denied else None)
    assert actor.action_available is (not denied)
    assert actor.bonus_action_available is (not denied)
    assert actor.reaction_available is (not denied)
    assert actor.movement_remaining_ft == (0 if denied else loaded.engine._effective_speed(actor))
    if kind == 'natural20':
        assert life._record(actor) == ({'ok': 1, 'bad': 2} if denied else {'ok': 0, 'bad': 0})
    logs = ' '.join(str(e.payload.get('log', '')) for e in loaded.engine.events)
    if denied:
        assert 'regains no Hit Points' in logs
        assert 'and regains 1 Hit Point.' not in logs
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_heal_to_reports_partial_actual_restoration_through_table(monkeypatch, tmp_path):
    combat, table, mid = H.table_fight(tmp_path, [])
    install(monkeypatch, lambda *args: 2)
    def recover(engine):
        actor = engine.state.actors[H.LEFT]
        engine._commit_damage(actor, 10, 'FORCE', 'test:injury', H.RIGHT, None, reaction_depth=0)
        assert life.heal_to(engine, actor, 5, 'test:partial') == 3
    H.on_hold(monkeypatch, recover)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[H.LEFT].current_hp == 53
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('boundary', ['furnace_hp', 'furnace_temp_hp', 'turn_start'])
@pytest.mark.parametrize('raises', [False, True])
def test_strict_healing_failure_escapes_observational_boundary(monkeypatch, tmp_path, boundary, raises):
    real = H.sheet
    monkeypatch.setattr(H, 'sheet', lambda *args, **kw: real(*args, **kw, primary='Stamina'))
    combat, table, mid = H.table_fight(tmp_path, [CTE, DEATHLESS])
    if boundary.startswith('furnace'):
        assert H.answer_action(table, mid, 'core_tempering_expression.blood_furnace')['status'] == 'COMMITTED'
    seen = []
    def invalid(engine, target, amount, healer, source, kind):
        seen.append((source, kind))
        engine._apply_condition(target, MARK, 'test:invalid', H.LEFT, expires_on='UNTIL_REMOVED')
        engine._spend_resource(target, 'resource:core.stamina', 1, 'test:invalid')
        if raises:
            raise RuntimeError('broken healing provider')
        return -1
    def trigger(engine):
        if boundary == 'turn_start':
            actor = engine.state.actors[H.ALLY]
            down(engine, actor)
            due(engine, actor)
        else:
            actor = engine.state.actors[H.LEFT]
            if boundary == 'furnace_hp':
                engine._commit_damage(actor, 10, 'FORCE', 'test:injury', H.RIGHT, None, reaction_depth=0)
            engine._spend_resource(actor, 'resource:core.stamina', 1, CTE)
    H.on_hold(monkeypatch, trigger)
    action = H.HOLD
    if boundary == 'turn_start':
        assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
        before_ally(combat, table, mid)
        action = 'end'
    install(monkeypatch, invalid)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(CombatServiceError):
        act(table, mid, action)
    assert seen and seen[-1] == (('test:recovery', 'hp') if boundary == 'turn_start'
                                  else (CTE, 'temp_hp' if boundary == 'furnace_temp_hp' else 'hp'))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == before
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
