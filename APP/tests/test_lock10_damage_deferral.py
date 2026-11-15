"""Held Harm's remaining-damage contract, independent of its rider-lane port."""
from dataclasses import FrozenInstanceError

import pytest

from combat import ext
from combat.damage_context import AttackDamage
from combat.ext import needle
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT
from tests.r10_fixup_support import answer

SOURCE = "test:held_harm"
POOL = "condition:typed.test_held_harm"


@pytest.mark.parametrize("typed", [True, False])
def test_hold_only_combined_remaining_damage_before_temporary_hp(monkeypatch, typed):
    e = duel([])
    target = e.state.actors[ME if typed else FOE]
    e._grant_temp_hp(target, 10, "test:temporary", target.entity_id)
    hp = target.current_hp
    install(monkeypatch, "final_damage", lambda *args: {"amount": 7})
    ext._HOOKS["final_damage"].append(lambda *args: {"amount": 4})
    seen = []
    def hold(engine, target, packet, intent):
        seen.append(packet.amount)
        return 3
    install(monkeypatch, "damage_deferral", hold)
    e._commit_damage(target, 20, "UNTYPED", "test:incoming", ME, None, reaction_depth=3)
    assert seen == [4] and target.temporary_hp == 9 and target.current_hp == hp


def test_hp_floor_and_prior_pool_limit_later_deferral(monkeypatch):
    e = duel([])
    target = e.state.actors[ME]
    install(monkeypatch, "final_damage", lambda *args: {"hp_floor": target.current_hp - 5})
    seen = []
    def first(engine, target, packet, intent):
        seen.append(packet.amount)
        return 3
    def second(engine, target, packet, intent):
        seen.append(packet.amount)
        return packet.amount
    install(monkeypatch, "damage_deferral", first)
    ext._HOOKS["damage_deferral"].extend([second, lambda *a: pytest.fail("no damage remains")])
    hp = target.current_hp
    e._commit_damage(target, 100, "UNTYPED", "test:incoming", FOE, None, reaction_depth=3)
    assert seen == [5, 2] and target.current_hp == hp


def test_immutable_confirmed_attack_context_and_nested_nonattack(monkeypatch):
    e = duel([])
    target = e.state.actors[ME]
    provenance = AttackDamage("test:attack", FOE, ME, 2, "roll:test", 19, 30, False)
    seen = []
    def observe(engine, target, packet, intent):
        seen.append(packet.attack)
        with pytest.raises(FrozenInstanceError):
            packet.amount = 999
        if packet.attack:
            engine._commit_damage(target, 1, "UNTYPED", "test:other", FOE, None, reaction_depth=3)
            assert engine.damage_context() == provenance
        return None
    install(monkeypatch, "damage_deferral", observe)
    e._commit_damage(target, 1, "UNTYPED", "test:attack", FOE, None, reaction_depth=3, attack_context=provenance)
    assert seen == [provenance, None] and e.damage_context() is None


@pytest.mark.parametrize("reply", [-1, True, 6, {"amount": 2}, 1.5])
def test_bad_pool_reply_rolls_back_pool_and_damage(monkeypatch, reply):
    e = duel([])
    def bad(engine, target, packet, intent):
        engine._apply_condition(target, POOL, SOURCE, target.entity_id, expires_on="END_OF_CURRENT_TURN")
        return reply
    install(monkeypatch, "damage_deferral", bad)
    before = e.state.model_dump(mode="json")
    with pytest.raises(ValueError, match="damage_deferral"):
        with e._transaction("test:damage", "test:damage", FOE):
            e._commit_damage(e.state.actors[ME], 5, "UNTYPED", "test:incoming", FOE, None, reaction_depth=3)
    assert e.state.model_dump(mode="json") == before


@pytest.mark.parametrize("use", [True, False])
def test_held_harm_choice_rolls_back_then_records_pool_and_reloads(monkeypatch, tmp_path, use):
    combat, table, mid = table_fight(tmp_path, [], ask=True)
    def hold(engine, target, packet, intent):
        if packet.source_id != "test:incoming" or target.entity_id != LEFT:
            return None
        picked = needle.ask(engine, intent, "HELD_HARM", target, "choice:needle.lock10_hold", ["hold"],
            labels={"hold": "Hold back 4 damage until the end of your turn"}, name="Held Harm",
            prompt="Hold back these 4 damage until the end of your turn? No action or cost.",
            target_id=LEFT, automatic=False, allow_decline=True)
        if not picked:
            return None
        engine._apply_condition(target, POOL, SOURCE, LEFT, expires_on="END_OF_CURRENT_TURN", data={"held": packet.amount})
        ext.note(engine, SOURCE, target, "Held Harm: 4 damage held until the end of your turn.")
        return packet.amount
    install(monkeypatch, "damage_deferral", hold)
    install(monkeypatch, "final_damage", lambda *a: {"amount": 4})
    on_hold(monkeypatch, lambda engine: engine._commit_damage(engine.state.actors[LEFT], 9, "UNTYPED",
        "test:incoming", LEFT, engine._active_intent, reaction_depth=3))
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    def send(answers=()):
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    paused = send()
    assert paused["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(paused["reaction"], use=use)])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[LEFT]
    pools = [c for c in target.conditions.values() if c.condition_id == POOL]
    assert len(pools) == int(use)
    if use:
        assert pools[0].data == {"held": 4}
    assert target.current_hp == before["actors"][LEFT]["current_hp"] - (0 if use else 4)
    assert loaded.mechanical.replay()["status"] == "PASS"
