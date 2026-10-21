"""Regression: a forced push with no intent of its own must not crash the Guardian at the Gate hooks.

Before the fix, ``gate_before_step`` and ``shelter_native_reaction`` read ``intent.intent_id`` directly, so a push
whose resolution Context carried ``intent=None`` raised ``AttributeError`` and aborted the movement with a
CheckpointError. The fix resolves a missing intent to the engine's active intent (or None) before use.
"""
from tests.test_riders_c7 import ALLY, STAMINA, _gate, _shoved


def test_shelter_behind_the_gate_push_with_no_intent_resolves_without_crashing():
    engine, me, foe = _gate(["shelter_behind_the_gate"], with_ally=True, foe_at=(4, 3))
    ally = engine.state.actors[ALLY]
    _shoved(engine, foe, ally, 20)  # no intent on the push's Context; must not raise
    assert (ally.position.x, ally.position.y) == (2, 5) and me.resources[STAMINA] == 59


def test_intent_helper_falls_back_to_active_then_none():
    from combat.ext import vermilion_gate as vg

    class Engine:
        _active_intent = None

    class Intent:
        intent_id = "explicit"

    eng = Engine()
    assert vg._intent_or_active(eng, None) is None
    assert vg._intent_key(eng, None) == "None"
    assert vg._intent_key(eng, Intent()) == "explicit"
    eng._active_intent = Intent()
    assert vg._intent_key(eng, None) == "explicit"
