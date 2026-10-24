"""Punishment Aegis's hit trigger, including no-damage native attacks.

This base predates ext/protection.py. The small owning consumer below models its
printed CL1–4 PB Psychic retaliation, without shipping a second ability compiler.
"""
import pytest

from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act

PUNISHMENT = 'tianxia.talent.protection.punishment'
WARD = 'condition:test.punishment_aegis'
ATTACK = 'test:native-hit'


def punishment(ctx, target, kind):
    ward = next((c for c in target.conditions.values() if c.condition_id == WARD), None)
    if ward is None:
        return
    caster = ctx.engine.state.actors[ward.source_actor_id]
    ctx.engine._commit_damage(ctx.actor, caster.proficiency_bonus, 'PSYCHIC', PUNISHMENT,
                             caster.entity_id, ctx.intent, reaction_depth=1)


@pytest.mark.parametrize('case', ['no_damage', 'zero_damage', 'damage', 'defended_miss', 'rolled_miss', 'unowned'])
def test_punishment_consumer_observes_only_confirmed_hits_and_replays(monkeypatch, tmp_path, case):
    service, table, mid = table_match(tmp_path)
    initial = service._load_session(mid).engine
    attacker_id = initial.state.current_actor_id
    defender_id = next(a for a in initial.state.actors if a != attacker_id)
    hp_before = initial.state.actors[attacker_id].current_hp
    install(monkeypatch, 'after_hit', punishment)
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:fixed-roll',
        'operation': 'replace', 'natural_result': 10})
    if case == 'zero_damage':
        install(monkeypatch, 'final_damage', lambda e, t, amount, dtype, source, *args:
                {'amount': 0} if source == ATTACK else None)
    def attack(engine, event_type, kwargs):
        if event_type != 'HOLD_POSITION_COMMITTED':
            return
        actor, target = engine.state.actors[attacker_id], engine.state.actors[defender_id]
        if case != 'unowned':
            engine._apply_condition(target, WARD, PUNISHMENT, defender_id,
                                    expires_on='START_OF_SOURCE_NEXT_TURN')
        if case == 'defended_miss':
            engine._add_modifier(target, 'test:melee-defense', 'armor_class_vs_melee', 'ADD', 100,
                                 'SELF', expires_on='START_OF_SELF_NEXT_TURN')
        engine._resolve_attack_spec(actor, target,
            {'attack_bonus': -100 if case == 'rolled_miss' else 30, 'reach_ft': 5,
             'damage': None if case == 'no_damage' else DiceSpec(count=1, sides=4), 'damage_type': 'BLUDGEONING'},
            engine._active_intent, source_definition_id=ATTACK)
    install(monkeypatch, 'event', attack)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    punishments = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == PUNISHMENT]
    expected = case not in ('defended_miss', 'rolled_miss', 'unowned')
    assert len(punishments) == int(expected)
    assert loaded.engine.state.actors[attacker_id].current_hp == hp_before - (initial.state.actors[defender_id].proficiency_bonus if expected else 0)
    if case == 'defended_miss':
        roll = next(e for e in loaded.engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == ATTACK)
        assert roll.payload['provisional_hit'] is True
        assert not any(e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == ATTACK for e in loaded.engine.events)
    if case == 'no_damage':
        assert not any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == ATTACK for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'
