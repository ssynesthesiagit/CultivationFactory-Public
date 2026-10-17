"""Review regressions: recorded facts, AI decisions, and critical-hit knockouts."""
import pytest
from combat import ext
from combat.ext import life_state
from combat.ext.maximum_hp_riders import MEAL, MODIFY, FOCUS, STEW
from combat.ext.mind_hidden_eye import mark_analyzed, record_characteristic, known_characteristic
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, DiceSpec
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_lock8_maximum_hp import table, answer
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install


def critical_table(tmp_path, monkeypatch, *, known=False, wound=False, fatal=False, portable=False):
    left, right = 'actor:factory.left', 'actor:factory.right'
    def attacks(info):
        return [ActionDefinition(source_definition_id='test:critical:' + info['actor_id'],
            owner_id=info['actor_id'], display_name='Review strike', economy=EconomyKind.ACTION,
            resolution_kind='TYPED' if portable else 'ATTACK', target_kind='HOSTILE_ENTITY', range_ft=60, attack_bonus=100,
            damage=DiceSpec(count=1, sides=2, modifier=2000 if fatal else 10), damage_type='UNTYPED',
            parameters={'expected_damage': 100, 'typed': {'effects': [{'type': 'review_strike'}],
                'numbers': info['numbers']}} if portable else {})]
    if portable:
        def resolve(ctx, eff):
            from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
            CharacterCombatRuntimeEngine._resolve_character_attack(ctx.engine, ctx.actor, ctx.target,
                source_id=ctx.source, attack_bonus=100, damage=DiceSpec(count=1, sides=2, modifier=10),
                damage_type='UNTYPED', intent=ctx.intent, ranged=True)
        ext.effects(); monkeypatch.setitem(ext._EFFECTS, 'review_strike', resolve)
    install(monkeypatch, 'compile_actions', attacks)
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:critical_roll',
        'operation': 'replace', 'natural_result': 20})
    def prepare(engine, kind, kwargs):
        a, b = engine.state.actors[left], engine.state.actors[right]
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == left:
            mark_analyzed(engine, a, b, 'test:analyzed')
            engine._gain_resource(a, FOCUS, 1, 'test:focus')
            if known:
                record_characteristic(engine, a, b, 'maximum_hp', 'test:confirmed_prior_knowledge')
            if wound or fatal:
                engine._apply_condition(b, life_state.MODE, 'test:death_saves', right,
                    expires_on='UNTIL_REMOVED', data={'rule': {'death_save_mode': {'mode': 'ADVANTAGE'}}})
            if wound:
                engine._commit_damage(b, b.current_hp - 1, 'UNTYPED', 'test:prior_wound', left,
                                      None, reaction_depth=0)
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), prepare])
    service, ui, mid, left, right = table(tmp_path, [MODIFY], monkeypatch)
    turn(ui, mid, left)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return service, ui, mid, left, right


@pytest.mark.parametrize('known', [False, True])
def test_ai_modify_requires_recorded_characteristic(tmp_path, monkeypatch, known):
    service, ui, mid, left, right = critical_table(tmp_path, monkeypatch, known=known, portable=True)
    base = service._load_session(mid).engine.state.actors[right].maximum_hp
    service.set_controller_mode(mid, actor_id=left, controller_mode='LOCAL_AUTO')
    result = service.auto_step(mid)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    a, b = loaded.engine.state.actors[left], loaded.engine.state.actors[right]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id.startswith('test:critical:')
               for e in loaded.engine.events)
    assert b.maximum_hp == base - (10 if known else 0)
    assert a.resources[FOCUS] == (0 if known else 1)
    assert known_characteristic(b, left, 'maximum_hp') == known
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('confirmed', [False, True])
def test_ai_stew_does_not_invent_preparation(tmp_path, monkeypatch, confirmed):
    service, ui, mid, left, right = table(tmp_path, [MEAL], monkeypatch)
    base = service._load_session(mid).engine.state.actors[left].maximum_hp
    if confirmed:
        first = act(ui, mid, 'system:combat.fight_setup')
        assert first['status'] == 'REACTION_REQUIRED'
        assert answer(ui, mid, 'system:combat.fight_setup', first['reaction'], [left])['status'] == 'COMMITTED'
    for aid in (left, right):
        service.set_controller_mode(mid, actor_id=aid, controller_mode='LOCAL_AUTO')
    assert service.auto_step(mid)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid); a = loaded.engine.state.actors[left]
    assert a.maximum_hp == base + (2 * a.proficiency_bonus if confirmed else 0)
    assert any(c.condition_id == STEW for c in a.conditions.values()) == confirmed
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_damaging_critical_modifies_unconscious_target_reload_and_heal(tmp_path, monkeypatch):
    service, ui, mid, left, right = critical_table(tmp_path, monkeypatch, wound=True)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    first = act(ui, mid, 'test:critical:')
    assert first['status'] == 'REACTION_REQUIRED'
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    assert answer(ui, mid, 'test:critical:', first['reaction'], ['maximum_hp'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid); b = loaded.engine.state.actors[right]
    assert b.active and b.current_hp == 0 and b.life_state == 'DYING'
    assert not life_state.is_deceased(b)
    assert b.maximum_hp == before['actors'][right]['maximum_hp'] - 10
    assert known_characteristic(b, left, 'maximum_hp')
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    def heal(engine, kind, kwargs):
        if kind == 'TURN_ENDED' and kwargs.get('actor_id') == left:
            life_state.heal_to(engine, engine.state.actors[right], 10000, 'test:later_healing', left)
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), heal])
    assert act(ui, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid); b = loaded.engine.state.actors[right]
    assert b.active and b.life_state is None and b.current_hp == b.maximum_hp
    assert b.maximum_hp == before['actors'][right]['maximum_hp'] - 10
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_critical_instant_death_does_not_offer_modification_or_revive(tmp_path, monkeypatch):
    service, ui, mid, left, right = critical_table(tmp_path, monkeypatch, known=True, fatal=True)
    base = service._load_session(mid).engine.state.actors[right].maximum_hp
    assert act(ui, mid, 'test:critical:')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid); b = loaded.engine.state.actors[right]
    assert life_state.is_deceased(b) and not b.active and b.current_hp == 0
    assert b.maximum_hp == base and loaded.engine.state.actors[left].resources[FOCUS] == 1
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
