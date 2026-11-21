"""CONCSAVE1: one Concentration save per damaging attack, against its combined attached damage.

combat/attached_concentration.py, combat/ext/attached_concentration.py, gate2_engine._commit_damage_packet.
Separate attacks and standalone damage keep their own saves.
"""

import pytest

from combat import concentration
from combat.damage_context import AttackDamage
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_docket import DARK, ME, ROOT, _my_turn, _sheet


def _engine():
    sheet = _sheet([*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_CLEARSIGHT"])
    sheet = {**sheet, "identity": {**sheet["identity"], "cultivation_level": 5}}
    engine = Gate4ControllerEngine(ROOT, match_seed="CONCSAVE1", typed_bundles=(compile_character(sheet, actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    _my_turn(engine)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


@pytest.fixture
def saves(monkeypatch):
    """Record every Concentration save as (target, damage the save is judged against)."""
    engine, me, foe = _engine()
    calls = []
    original = engine._concentration_check

    def spy(actor, hp_damage, **kwargs):
        calls.append((actor.entity_id, hp_damage, kwargs.get("damage_source_id")))
        return original(actor, hp_damage, **kwargs)

    monkeypatch.setattr(engine, "_concentration_check", spy)
    engine._start_concentration(foe, "action:held_by_foe")
    return engine, me, foe, calls


def _packet(roll_id, source="action:water_lash", amount=None):
    return AttackDamage(source_id=source, attacker_id=ME, target_id=AN, attack_index=1, roll_id=roll_id,
                        natural_result=15, total=15, critical=False)


def _attack(engine, me, foe, roll_id, packets, source="action:water_lash"):
    """Commit each attached packet of one hit, then the attack's final rider, as the typed executor does."""
    for damage_type, amount in packets:
        attack = AttackDamage(source_id=source, attacker_id=me.entity_id, target_id=foe.entity_id, attack_index=1,
                              roll_id=roll_id, natural_result=15, total=15, critical=False,
                              component="rider" if damage_type != "SLASHING" else "primary")
        engine._commit_damage(foe, amount, damage_type, source, me.entity_id, None, reaction_depth=0,
                              attack_context=attack)
    engine._run_final_riders("attack_damage_final", engine, me, foe,
                             AttackDamage(source_id=source, attacker_id=me.entity_id, target_id=foe.entity_id,
                                          attack_index=1, roll_id=roll_id, natural_result=15, total=15, critical=False),
                             None)


def test_one_hit_with_two_attached_packets_makes_one_save_for_the_combined_damage(saves):
    engine, me, foe, calls = saves
    _attack(engine, me, foe, "roll:one", [("SLASHING", 6), ("COLD", 5)])
    assert len(calls) == 1
    assert calls[0][0] == foe.entity_id
    assert calls[0][1] == 11  # the save's DC comes from the combined damage, not the first packet


def test_the_save_waits_until_the_attack_is_complete(saves):
    engine, me, foe, calls = saves
    attack = AttackDamage(source_id="action:water_lash", attacker_id=me.entity_id, target_id=foe.entity_id,
                          attack_index=1, roll_id="roll:wait", natural_result=15, total=15, critical=False)
    engine._commit_damage(foe, 6, "SLASHING", "action:water_lash", me.entity_id, None, reaction_depth=0,
                          attack_context=attack)
    assert calls == []  # the first packet alone does not judge the save
    engine._run_final_riders("attack_damage_final", engine, me, foe, attack, None)
    assert len(calls) == 1 and calls[0][1] == 6


def test_separate_attacks_still_make_their_own_saves(saves):
    engine, me, foe, calls = saves
    _attack(engine, me, foe, "roll:first", [("SLASHING", 4)])
    _attack(engine, me, foe, "roll:second", [("SLASHING", 4)])
    assert [c[1] for c in calls] == [4, 4]


def test_standalone_damage_keeps_its_own_save(saves):
    engine, me, foe, calls = saves
    engine._commit_damage(foe, 6, "FIRE", "trap:dart", me.entity_id, None, reaction_depth=0)
    engine._commit_damage(foe, 5, "FIRE", "trap:dart", me.entity_id, None, reaction_depth=0)
    assert [c[1] for c in calls] == [6, 5]


def test_a_concentration_begun_after_the_damage_is_not_judged_by_it(saves):
    engine, me, foe, calls = saves
    attack = AttackDamage(source_id="action:water_lash", attacker_id=me.entity_id, target_id=foe.entity_id,
                          attack_index=1, roll_id="roll:late", natural_result=15, total=15, critical=False)
    engine._commit_damage(foe, 6, "SLASHING", "action:water_lash", me.entity_id, None, reaction_depth=0,
                          attack_context=attack)
    engine._end_concentration(foe, "FAILED_DAMAGE_CHECK")
    engine._start_concentration(foe, "action:begun_later")
    engine._run_final_riders("attack_damage_final", engine, me, foe, attack, None)
    assert calls == []
    assert concentration.sources(foe) == ["action:begun_later"]
