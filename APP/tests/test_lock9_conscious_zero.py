"""Conscious-survival lifecycle contracts; these are not full ability ports.

The two source-backed providers below exercise the Indomitable and General's
Soul-Standard conscious-until-next-turn clauses on real compiled characters.
The latter's restricted healing/free Standard/Command clauses remain rider work.
"""
import pytest

from combat import ext, typed_executor as te
from combat.ext import life_state
from combat.ext.effect_durations import token
from combat.gate5_service import CombatService
from tests.h1_support import duel, ME, FOE, ROOT, script
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import answer

INDOMITABLE = 'TAL_GUARDIAN_INDOMITABLE'
GENERAL = 'tianxia.talent.warleader.general_s_soul_standard'
WINDOW = 'condition:typed.test_conscious_window'


def source_provider(monkeypatch, source, *, ask=False):
    """Representative lifecycle consumer, deliberately scoped to one printed clause."""
    def choose(engine, target, damage_source, intent):
        if target.entity_id != LEFT:
            return None
        if ask:
            from combat.ext.needle import ask as choose_option
            if not choose_option(engine, intent, 'ZERO_HP:survival', target, 'choice:needle.survival_test', ['remain'],
                                 prompt=f'{target.display_name} reached 0 HP. Remain conscious until the end of your next turn?',
                                 name='Indomitable' if source == INDOMITABLE else 'General’s Soul-Standard',
                                 labels={'remain': 'Remain conscious at 0 HP'}, allow_decline=True, default='decline'):
                return None
        engine._apply_condition(target, WINDOW, source, target.entity_id,
                                expires_on=token('end', target.entity_id, target.turns_started + 1),
                                data={'label': 'Conscious at 0 HP until the end of your next turn'})
        return 'CONSCIOUS'
    install(monkeypatch, 'zero_hp', choose)
    def expire(engine, event_type, kwargs):
        if event_type == 'CONDITION_REMOVED' and kwargs.get('payload', {}).get('condition_id') == WINDOW:
            for actor_id in kwargs.get('target_ids', ()):
                life_state.fall_unconscious(engine, engine.state.actors[actor_id], source)
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), expire])
    monkeypatch.setitem(ext._NESTED_HOOKS, 'event', {*ext._NESTED_HOOKS.get('event', set()), expire})


def wound(engine, target_id=LEFT):
    target = engine.state.actors[target_id]
    engine._commit_damage(target, max(0, target.current_hp - 5), 'FORCE', 'test:wound', RIGHT, None, reaction_depth=0)
    engine._start_concentration(target, 'test:concentration')
    script(engine, [20] * 8)
    engine._commit_damage(target, 5, 'FORCE', 'test:drop', RIGHT, engine._active_intent, reaction_depth=0)


@pytest.mark.parametrize('source', [INDOMITABLE, GENERAL])
def test_two_printed_conscious_windows_commit_reload_turn_and_expire(monkeypatch, tmp_path, source):
    combat, table, mid = table_fight(tmp_path, [source], ally_talents=[])
    source_provider(monkeypatch, source)
    on_hold(monkeypatch, wound)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[LEFT]
    assert target.active and target.current_hp == 0 and target.life_state == 'CONSCIOUS'
    assert target.concentration and target.movement_remaining_ft > 0 and target.action_available
    assert not any(c.condition_id == life_state.UNCONSCIOUS for c in target.conditions.values())
    assert {'MOVE', 'ACTION'} <= {str(c.kind) for c in loaded.engine.legal_candidates()}
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert table.state(mid)  # presentation model accepts the new state
    # This lifecycle check walks; integrated flight also offers jumps that land
    # below their airborne destination before the transaction finishes.
    move = next(c for c in loaded.engine.legal_candidates() if c.kind == 'MOVE' and not c.destination.z)
    current = table.state(mid)
    assert table.act(mid, move.candidate_id, move.decision_id, move.state_version, current['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position == move.destination
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert act(table, mid, 'system:combat.dodge')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[LEFT].action_available
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    for _ in range(5):
        if table.state(mid)['menu']['actor_id'] == LEFT:
            break
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[LEFT]
    assert target.life_state == 'CONSCIOUS' and target.action_available and target.reaction_available
    assert target.movement_remaining_ft > 0 and target.concentration
    assert not any(e.event_type == 'CHECK_ROLLED' and e.payload.get('skill') == 'Death Saving Throw'
                   and e.actor_id == LEFT for e in loaded.engine.events)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[LEFT]
    assert target.life_state == 'DYING' and not target.action_available and not target.reaction_available
    assert target.movement_remaining_ft == 0 and target.concentration is None
    assert any(c.condition_id == life_state.UNCONSCIOUS for c in target.conditions.values())
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_player_survival_choice_rolls_back_until_answered(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [INDOMITABLE], ally_talents=[])
    source_provider(monkeypatch, INDOMITABLE, ask=True)
    on_hold(monkeypatch, wound)
    state = table.state(mid)
    menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == HOLD)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    first = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert first['status'] == 'REACTION_REQUIRED'
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode='json') == before
    result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [answer(first['reaction'])])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].life_state == 'CONSCIOUS'
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_conscious_override_precedes_existing_dying_fallback(monkeypatch):
    e = duel(['TAL_BERSERKER_DEATHLESS'])
    target = e.state.actors[ME]
    install(monkeypatch, 'zero_hp', lambda *a: 'CONSCIOUS')
    target.action_available = False
    target.movement_remaining_ft = 7
    e._commit_damage(target, target.current_hp, 'FORCE', 'test:drop', FOE, None, reaction_depth=0)
    assert target.life_state == 'CONSCIOUS' and not target.action_available and target.movement_remaining_ft == 7
    assert not any(c.condition_id == life_state.UNCONSCIOUS for c in target.conditions.values())


def test_healing_above_zero_clears_state_without_economy_refund(monkeypatch):
    e = duel([])
    target = e.state.actors[ME]
    install(monkeypatch, 'zero_hp', lambda *a: 'CONSCIOUS')
    e._commit_damage(target, target.current_hp, 'FORCE', 'test:drop', FOE, None, reaction_depth=0)
    target.action_available = False
    action = next(iter(e.action_catalog.values()))
    te.block_healing(te.Context(e, target, action, None, {}, [target], target), {'flat': 4, 'applies_to': 'target'})
    assert target.current_hp == 4 and target.life_state is None and target.active and not target.action_available


def test_damage_failures_and_explicit_final_defeat_still_apply(monkeypatch):
    e = duel([])
    target = e.state.actors[ME]
    install(monkeypatch, 'zero_hp', lambda *a: 'CONSCIOUS')
    e._commit_damage(target, target.current_hp, 'FORCE', 'test:drop', FOE, None, reaction_depth=0)
    e._commit_damage(target, 1, 'FORCE', 'test:more', FOE, None, reaction_depth=0)
    assert target.active and target.life_state == 'CONSCIOUS'
    assert target.turn_flags[life_state.RECORD]['bad'] == 1
    life_state.fall_unconscious(e, target, 'test:expired')
    assert target.life_state == 'DYING' and target.turn_flags[life_state.RECORD]['bad'] == 1
    e._defeat(target, 'test:final', final=True)
    assert not target.active and target.life_state is None


def test_conflicting_survival_providers_rollback(monkeypatch):
    e = duel([])
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'zero_hp', [lambda *a: 'CONSCIOUS', lambda *a: 'DYING'])
    before = e.state.model_dump(mode='json')
    with pytest.raises(ValueError, match='one zero_hp plugin'):
        with e._transaction('test:damage', 'test:drop', ME):
            target = e.state.actors[ME]
            e._commit_damage(target, target.current_hp, 'FORCE', 'test:drop', FOE, None, reaction_depth=0)
    assert e.state.model_dump(mode='json') == before


def test_conscious_at_zero_is_not_immunity_to_death(monkeypatch):
    e = duel([])
    target = e.state.actors[ME]
    install(monkeypatch, 'zero_hp', lambda *a: 'CONSCIOUS')
    e._commit_damage(target, target.current_hp, 'FORCE', 'test:drop', FOE, None, reaction_depth=0)
    for _ in range(3):
        e._commit_damage(target, 1, 'FORCE', 'test:more', FOE, None, reaction_depth=0)
    assert not target.active and target.life_state is None
    assert any(e.event_type == 'ENTITY_DEFEATED' and e.actor_id == ME for e in e.events)


def test_expired_survival_does_not_destabilize_an_already_stable_creature(monkeypatch):
    e = duel([])
    target = e.state.actors[ME]
    install(monkeypatch, 'zero_hp', lambda *a: 'CONSCIOUS')
    e._commit_damage(target, target.current_hp, 'FORCE', 'test:drop', FOE, None, reaction_depth=0)
    e._set_life_state(target, 'STABLE', 'test:stabilize')
    life_state.fall_unconscious(e, target, 'test:expired')
    assert target.life_state == 'STABLE'
