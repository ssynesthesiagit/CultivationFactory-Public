"""The final checkpoint covers all damage packets, after defenses and before HP."""
import pytest

from combat import ext
from combat.gate5_service import CombatService
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock2_persistence import table_match, ROOT, act
from tests.test_lock_choices import install


@pytest.mark.parametrize('typed', [False, True])
def test_source_bound_floor_covers_intentless_damage_and_temporary_hp(monkeypatch, typed):
    seen = []
    def protect(engine, target, amount, kind, source, actor, intent):
        seen.append((amount, source, actor, intent))
        return {'hp_floor': 1} if source == 'test:merciful' else None
    install(monkeypatch, 'final_damage', protect)
    engine, _ = _engine([])
    target = engine.state.actors[ME if typed else AN]
    before = target.current_hp
    engine._grant_temp_hp(target, 5, 'test:temporary', target.entity_id)
    first = engine._commit_damage(target, 10000, 'UNTYPED', 'test:merciful', AN, None, reaction_depth=3)
    second = engine._commit_damage(target, 10000, 'UNTYPED', 'test:merciful', AN, None, reaction_depth=3)
    assert first == before - 1 and second == 0
    assert target.active and target.current_hp == 1 and target.temporary_hp == 0
    assert len(seen) == 2 and all(row[1:] == ('test:merciful', AN, None) for row in seen)
    engine._commit_damage(target, 10000, 'UNTYPED', 'test:other', AN, None, reaction_depth=3)
    assert target.current_hp == 0 and not target.active


@pytest.mark.parametrize('answer', [{'amount': -1}, {'amount': True}, {'amount': 10001}, {'hp_floor': -1}, {'hp_floor': True}])
def test_invalid_final_damage_answer_rolls_back(monkeypatch, answer):
    install(monkeypatch, 'final_damage', lambda *args: answer)
    engine, _ = _engine([])
    before = engine.state.model_dump(mode='json')
    with pytest.raises(ValueError, match='final_damage'):
        with engine._transaction('test:bad', 'test:bad', ME):
            engine._commit_damage(engine.state.actors[AN], 5, 'UNTYPED', 'test:bad', ME, None, reaction_depth=3)
    assert engine.state.model_dump(mode='json') == before


def test_floor_survives_real_table_commit_reload_and_replay(monkeypatch, tmp_path):
    install(monkeypatch, 'final_damage', lambda e, t, n, k, s, a, i: {'hp_floor': 1} if s == 'test:merciful' else None)
    def damage(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED':
            actor = engine.state.actors[kwargs['actor_id']]
            for _ in range(2):
                engine._commit_damage(actor, 10000, 'UNTYPED', 'test:merciful', actor.entity_id, None, reaction_depth=3)
    install(monkeypatch, 'event', damage)
    combat, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)['menu']['actor_id']
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[actor_id].current_hp == 1
    assert loaded.engine.state.actors[actor_id].active
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('typed', [False, True])
@pytest.mark.parametrize('defense,expected', [('damage_resistance', 5), ('damage_immunity', 0)])
def test_final_checkpoint_sees_defended_amount_even_when_defense_returns_zero(monkeypatch, typed, defense, expected):
    seen = []
    install(monkeypatch, 'final_damage', lambda e, t, n, *args: seen.append(n))
    engine, _ = _engine([])
    actor = engine.state.actors[ME if typed else AN]
    engine._add_modifier(actor, 'test:defense', defense, 'SET', 'FIRE', 'ALL', expires_on=None)
    before = actor.current_hp
    engine._commit_damage(actor, 10, 'FIRE', 'test:packet', AN, None, reaction_depth=3)
    assert seen == [expected]
    assert actor.current_hp == before - expected


def test_multiple_final_reductions_combine_without_healing_or_changing_plain_overkill(monkeypatch):
    install(monkeypatch, 'final_damage', lambda *args: {'amount': 4, 'hp_floor': 1})
    ext._HOOKS['final_damage'].append(lambda *args: {'amount': 2, 'hp_floor': 2})
    engine, _ = _engine([])
    actor = engine.state.actors[AN]
    actor.current_hp = 3
    assert engine._commit_damage(actor, 10, 'UNTYPED', 'test:packet', ME, None, reaction_depth=3) == 1
    assert actor.current_hp == 2
    actor.current_hp = 0
    assert engine._commit_damage(actor, 10, 'UNTYPED', 'test:packet', ME, None, reaction_depth=3) == 0
    assert actor.current_hp == 0
    install(monkeypatch, 'final_damage', lambda *args: None)
    engine, _ = _engine([])
    actor = engine.state.actors[AN]
    assert engine._commit_damage(actor, 10000, 'UNTYPED', 'test:plain', ME, None, reaction_depth=3) == 10000


def test_runtime_resistance_also_precedes_final_checkpoint(monkeypatch):
    seen = []
    install(monkeypatch, 'final_damage', lambda e, t, n, *args: seen.append(n))
    engine, _ = _engine([])
    actor = engine.state.actors[AN]
    engine.runtime_actor_ids = {AN}
    engine._ignore_resistance_sources = set()
    actor.damage_resistances = ('FIRE',)
    assert engine._commit_damage(actor, 10, 'FIRE', 'test:runtime', ME, None, reaction_depth=3) == 5
    assert seen == [5]
