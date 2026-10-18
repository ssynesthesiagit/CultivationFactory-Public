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


def test_explicit_journey_resolution_drops_timed_continuation_but_keeps_scene_use():
    old_guard = {"modifier": "{}", "remaining": 6, "expiry_kind": "rounds", "repeat": {}}
    actor = {"bundle": {"typed_passives": []}, "source_states": {
        KEY: {"scene_used": 1, "guards": [old_guard], "conditions": [{"condition": "{}"}]}}}
    session = SimpleNamespace(state={"actors": {"target": actor}})
    creature = SimpleNamespace(conditions={}, modifiers={}, turn_flags={})
    engine = SimpleNamespace(state=SimpleNamespace(actors={}, round_number=1))
    settled(session, "target", engine, creature, True)
    state = actor["source_states"][KEY]
    assert state["scene_used"] == 1
    assert state["guards"] == []
    assert state["conditions"] == []
