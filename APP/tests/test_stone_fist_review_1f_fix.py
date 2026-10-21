"""Regressions for mixed damage callbacks and explicit Journey effect resolution."""
from types import SimpleNamespace

from combat.attack_components import collect, scope, callbacks
from combat.ext.dreamweaver import REFUGE_ON, refuge_resistance_components
from combat.ext.stone_fist_journey import KEY, settled


def test_dream_refuge_resists_only_non_force_psychic_portions():
    target = SimpleNamespace(entity_id="target", conditions={
        "refuge": SimpleNamespace(condition_id=REFUGE_ON)})
    engine = object()
    parts = collect(8, "BLUDGEONING", [{"amount": 20, "damage_type": "FORCE"}])
    with scope(engine, target, parts):
        refuge_resistance_components(engine, target, parts, "attack", "attacker")
    assert [part["amount"] for part in parts] == [4, 20]


def test_component_settlement_composes_other_plugins_scalar_defense(monkeypatch):
    from combat import ext

    calls = []
    def scalar(engine, target, amount, kind, source, actor):
        calls.append("scalar")
        return 2
    def components(engine, target, parts, source, actor):
        calls.append("components")
        parts[1]["amount"] -= 1

    scalar.__module__ = "tests.scalar_provider"
    components.__module__ = "tests.component_provider"
    monkeypatch.setattr(ext, "callbacks", lambda point: {
        "incoming_damage": (scalar,), "incoming_damage_components": (components,),
    }[point])
    parts = collect(4, "BLUDGEONING", [{"amount": 4, "damage_type": "FORCE"}])
    target = SimpleNamespace(entity_id="target")
    remaining = callbacks("incoming_damage", object(), target, 8, "BLUDGEONING", "source", "actor", parts)
    assert calls == ["scalar", "components"]
    assert [part["amount"] for part in parts] == [2, 3]
    assert remaining == 5


def test_explicit_journey_resolution_drops_timed_continuation_but_keeps_scene_use():
    old_guard = {"modifier": "{}", "remaining": 6, "expiry_kind": "rounds", "repeat": {}}
    actor = {"bundle": {"typed_passives": []}, "source_states": {
        KEY: {"scene_used": 1, "guards": [old_guard], "conditions": [{"condition": "{}"}]}}}
    session = SimpleNamespace(state={"actors": {"target": actor}})
    creature = SimpleNamespace(conditions={}, modifiers={}, turn_flags={})
    engine = SimpleNamespace(state=SimpleNamespace(actors={}, zones={}, round_number=1))
    settled(session, "target", engine, creature, True)
    state = actor["source_states"][KEY]
    assert state["scene_used"] == 1  # retained until journey_scene_end, not encounter effect cleanup
    assert state["guards"] == []
    assert state["conditions"] == []
