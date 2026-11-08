"""Prone's stand-up rule survives each producer's deadline and table reloads."""
from types import SimpleNamespace

import pytest

from combat import falling, posture
from combat.ext import barrage_hits, sniper_lines, warleader_commands
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, duel, script
from tests import test_tabletop_hunt6 as table_support
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, on_hold


def apply_prone(engine, actor, site, runtime_prone):
    """Exercise the production condition producers, with only their inputs supplied."""
    if site == 'falling':
        script(engine, [1])
        falling.displace(engine, actor, 3, 'test:forced_fall', intent=engine._active_intent)
    elif site == 'warleader_commands':
        warleader_commands._force_prone(engine, actor)
    elif site == 'character_runtime_adapter':
        # Carry the actual portable producer's condition into the native table,
        # rather than asking its sealed, minimal runtime to build native menus.
        engine._apply_condition(actor, runtime_prone.condition_id, runtime_prone.source_definition_id,
                                RIGHT, expires_on=runtime_prone.expires_on, data=runtime_prone.data)
    else:
        ctx = SimpleNamespace(engine=engine, actor=engine.state.actors[RIGHT],
            source=sniper_lines.PUSH_SHOT,
            typed={'modifier': {'id': sniper_lines.PUSH_SHOT}},
            damage_cache={'barrage_blowback': True}, rider=lambda text: None)
        blocked = Position(x=0, y=0)
        if site == 'sniper_lines':
            sniper_lines.push_shot_into_an_object(ctx, actor, blocked, 5)
        else:
            assert site == 'barrage_hits'
            barrage_hits._blowback_collision(ctx, actor, blocked, 5)


@pytest.mark.parametrize('site', ['falling', 'sniper_lines', 'warleader_commands',
                                 'character_runtime_adapter', 'barrage_hits'])
@pytest.mark.parametrize('stand_when', ['midturn', 'next_turn'])
def test_every_prone_producer_offers_standing_and_auto_stands_after_reload(
        tmp_path, monkeypatch, site, stand_when, runtime_prone):
    original_sheet = table_support.sheet
    def speed_twenty(*args, **kwargs):
        document = original_sheet(*args, **kwargs)
        document['ability_scores_and_statistics']['speed']['walking_ft'] = 20
        return document
    monkeypatch.setattr(table_support, 'sheet', speed_twenty)
    combat, table, mid = table_support.table_fight(tmp_path, [])
    on_hold(monkeypatch, lambda engine: apply_prone(engine, engine.state.actors[LEFT], site, runtime_prone))
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert len(posture.prone_conditions(actor)) == 1
    assert actor.position.z == 0 and loaded.engine._effective_speed(actor) == 20
    if site == 'falling':
        assert any(ev.payload.get('fall_distance_ft') == 15 for ev in loaded.engine.events)
    menu = table.state(mid)['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'] == posture.SOURCE)
    assert 'Stand up' in group['label'] and '10 feet' in group['label']

    if stand_when == 'midturn':
        assert act(table, mid, posture.SOURCE)['status'] == 'COMMITTED'
    else:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        for _ in range(3):
            if table.state(mid)['menu']['actor_id'] == LEFT:
                break
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
        assert table.state(mid)['menu']['actor_id'] == LEFT
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert not posture.prone_conditions(actor)
    assert not any(c.condition_id.endswith('.prone') for c in actor.conditions.values())
    assert actor.movement_remaining_ft == 10
    stood = [ev for ev in loaded.engine.events if ev.event_type == 'STOOD_UP' and ev.actor_id == LEFT]
    assert len(stood) == 1 and stood[0].payload['cost_ft'] == 10
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('condition_id', ['condition:typed.prone', 'condition:core.prone'])
@pytest.mark.parametrize('expiry', [None, 'UNTIL_REMOVED', 'STAND_UP', 'END_OF_HOLDER_NEXT_TURN'])
def test_prone_rule_not_deadline_controls_standing(condition_id, expiry):
    engine = duel([])
    actor = engine.state.actors[ME]
    actor.speed_ft = actor.movement_remaining_ft = 20
    engine._apply_condition(actor, condition_id, 'test:prone', ME, expires_on=expiry)
    assert posture.standing_cost(engine, actor) == 10
    assert posture.stand_up(engine, actor)
    assert not actor.conditions and actor.movement_remaining_ft == 10


def test_stand_up_deadline_does_not_make_an_unrelated_condition_prone():
    engine = duel([])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, 'condition:typed.test_other', 'test:other', ME, expires_on='STAND_UP')
    assert not posture.prone_conditions(actor)
    assert posture.standing_cost(engine, actor) is None
    assert not posture.stand_up(engine, actor)
    assert len(actor.conditions) == 1


def test_inline_stand_rule_and_suppressed_prone_use_shared_condition_reader():
    engine = duel([])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, 'condition:typed.test_posture', 'test:inline', ME,
        expires_on=None, data={'rule': {'ends_on_stand_up': True}})
    engine._apply_condition(actor, 'condition:typed.prone', 'test:suppressed', ME,
        expires_on='STAND_UP', data={'suppressed': True})
    assert [c.condition_id for c in posture.prone_conditions(actor)] == ['condition:typed.test_posture']
    assert posture.stand_up(engine, actor)
    assert [c.condition_id for c in actor.conditions.values()] == ['condition:typed.prone']


def test_core_alias_is_removed_only_once(monkeypatch):
    from combat import typed_executor
    engine = duel([])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, 'condition:core.prone', 'test:alias', ME, expires_on=None)
    rules = dict(typed_executor.rules())
    rules['condition_id_aliases'] = {**rules.get('condition_id_aliases', {}), 'condition:core.prone': 'prone'}
    monkeypatch.setattr(typed_executor, 'rules', lambda: rules)
    assert len(posture.prone_conditions(actor)) == 1
    assert posture.stand_up(engine, actor)
    assert not actor.conditions


# Reuse the existing sealed adapter fixture, without running its unrelated tests.
from tests.test_c3ar_runtime_executability import (  # noqa: E402
    runtime_package, adapter, bundle, runtime_engine, req,
)


@pytest.fixture(scope='session')
def runtime_prone(bundle):
    """The real portable Dirty Trick producer's condition, before native admission."""
    engine = runtime_engine(bundle, seed='seed-10')
    engine.execute_action(req('action:scoundrel.dirty_trick', target_id='dummy:target', option_ids=('PRONE',)))
    return next(c for c in engine.state.actors['dummy:target'].conditions.values()
                if c.condition_id == 'condition:core.prone')


@pytest.mark.parametrize('stand_when', ['midturn', 'next_turn'])
def test_actual_character_runtime_dirty_trick_can_stand(runtime_prone, stand_when):
    engine = duel([])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, runtime_prone.condition_id, runtime_prone.source_definition_id,
                            FOE, expires_on=runtime_prone.expires_on, data=runtime_prone.data)
    actor.speed_ft = actor.movement_remaining_ft = 20
    if stand_when == 'midturn':
        assert any(c.source_definition_id == posture.SOURCE and '10 feet' in c.display_name
                   for c in engine.legal_candidates())
        assert posture.stand_up(engine, actor)
    else:
        engine._system_start_turn()
    assert not posture.prone_conditions(actor) and actor.movement_remaining_ft == 10
