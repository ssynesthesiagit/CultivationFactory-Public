"""The shared pre-defense attack component seam is strict and nesting-safe."""
import pytest

from combat import pending_damage
from combat.damage_context import AttackDamage
from tests.h1_support import duel, ME, FOE
from tests.test_lock_choices import install


def test_attached_damage_precedes_primary_hp_snapshot_and_restores_context(monkeypatch):
    engine = duel([])
    target = engine.state.actors[FOE]
    attack = AttackDamage('test:attack', ME, FOE, 1, 'test:roll', 10, 20, False)
    seen = []

    def attach(e, victim, amount, context):
        seen.append((amount, context))
        assert pending_damage.current(e) is None
        # A standalone context opened during this attack must not inherit its
        # attack provenance or recursively dispatch the primary callback.
        with pending_damage.scope(e, victim, 2, 'COLD', 'test:unrelated', ME) as unrelated:
            assert unrelated.source_id == 'test:unrelated'
        e._commit_damage(victim, 4, 'FIRE', 'test:attached', ME, None, reaction_depth=3)
        assert e.damage_context() is context
        assert pending_damage.current(e) is None

    install(monkeypatch, 'attack_packet_start', attach)
    snapshots = []
    def snapshot(e, victim, amount, dtype, source, attacker, intent):
        snapshots.append((source, pending_damage.current(e).hp_before))
    install(monkeypatch, 'final_damage', snapshot)
    hp = target.current_hp
    engine._commit_damage(target, 3, 'PIERCING', 'test:attack', ME, None,
                          reaction_depth=3, attack_context=attack)
    assert seen == [(3, attack)], 'standalone nested damage must not reenter the attack hook'
    assert target.current_hp == hp - 7
    assert snapshots == [('test:attached', hp), ('test:attack', hp - 4)]
    assert engine.damage_context() is None and pending_damage.current(engine) is None


def test_attack_packet_callback_failure_rolls_back_and_restores_context(monkeypatch):
    engine = duel([])
    target = engine.state.actors[FOE]
    attack = AttackDamage('test:attack', ME, FOE, 1, 'test:roll', 10, 20, False)

    def fail(e, victim, amount, context):
        e._commit_damage(victim, 4, 'FIRE', 'test:attached', ME, None, reaction_depth=3)
        raise ValueError('test:attached-failure')

    install(monkeypatch, 'attack_packet_start', fail)
    before = engine.state.model_dump(mode='json')
    with pytest.raises(ValueError, match='test:attached-failure'):
        with engine._transaction('test:attack', 'test:attack', ME):
            engine._commit_damage(target, 3, 'PIERCING', 'test:attack', ME, None,
                                  reaction_depth=3, attack_context=attack)
    assert engine.state.model_dump(mode='json') == before
    assert engine.damage_context() is None and pending_damage.current(engine) is None
