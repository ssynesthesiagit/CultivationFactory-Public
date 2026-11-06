"""Trap and zone-driven strikes carry no declared intent; interception and teleports must not crash on that.

Synthetic fakes only: the checkpoints receive intent=None, as they do when a trap spring or zone effect
runs an attack without a declared intent. Such records store intent_id "" (main's empty value for no intent).
"""
from types import SimpleNamespace

import pytest

from combat import attack_declaration, attack_completion, ext, movement_receipts, paid_relocation, typed_executor
from combat.ext import afterimage_attacks


class FakeEngine:
    def __init__(self):
        self.state = SimpleNamespace(objects={"object:test.marker": object()}, map_images={})
        self.events = []
        self.action_catalog = {}

    def _append_event(self, event_type, source_id, **kwargs):
        self.events.append((event_type, source_id, kwargs))


def entity(entity_id):
    return SimpleNamespace(entity_id=entity_id)


RECEIPT = {"source_id": "passive:test.marker", "recipient_object_id": "object:test.marker",
           "condition_instance_id": "condition:test.marker"}


def test_intentless_receipt_is_recorded_with_empty_intent(monkeypatch):
    engine = FakeEngine()
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_target_interception", [lambda *args: RECEIPT])
    spec = {}
    actor, target = entity("actor:test.attacker"), entity("actor:test.target")
    assert attack_declaration.intercepted(engine, actor, target, "action:test.trap_strike", None, 1, spec=spec) is True
    (event_type, source_id, kwargs), = engine.events
    assert event_type == "PASSIVE_TRIGGERED" and source_id == "passive:test.marker"
    assert kwargs["payload"]["kind"] == "attack_target_intercepted"
    assert kwargs["payload"]["intent_id"] == ""
    assert kwargs["payload"]["original_target_id"] == "actor:test.target"
    # The cached decision for the same intentless key replays without a second event.
    assert attack_declaration.intercepted(engine, actor, target, "action:test.trap_strike", None, 1, spec=spec) is True
    assert len(engine.events) == 1


def test_afterimage_interception_without_intent_does_not_crash(monkeypatch):
    engine = FakeEngine()
    condition = SimpleNamespace(instance_id="condition:test.afterimage", source_definition_id="passive:test.afterimage",
                                data={"label": "Afterimage"})
    target = SimpleNamespace(entity_id="actor:test.target", display_name="Target", conditions={condition.instance_id: condition})
    attacker = SimpleNamespace(entity_id="actor:test.attacker", display_name="Attacker")
    image = SimpleNamespace(object_id="object:test.image", component={"condition_instance_id": condition.instance_id})
    monkeypatch.setattr(afterimage_attacks, "perceived_image", lambda *args: image)
    engine.roller = SimpleNamespace(roll=lambda *args, **kwargs: SimpleNamespace(roll_id="roll:test", total=2))
    engine._record_roll = lambda roll: None
    # A roll of 2 does not destroy the image, so the hook returns None without touching state.
    assert afterimage_attacks.intercept_attack(engine, attacker, target, "action:test.trap_strike", None, 1) is None
    (event_type, _, kwargs), = engine.events
    assert event_type == "PASSIVE_TRIGGERED" and kwargs["payload"]["kind"] == "afterimage_targeting"
    assert kwargs["payload"]["intent_id"] == ""


def test_teleport_receipt_without_intent_publishes_empty_intent(monkeypatch):
    def point(x):
        return SimpleNamespace(x=x, y=0, z=0)
    engine = SimpleNamespace(
        state=SimpleNamespace(match_id="match:test", round_number=1, current_actor_id="actor:test.attacker", current_slot_index=0),
        grid=SimpleNamespace(distance_ft=lambda previous, destination: 5))
    ctx = SimpleNamespace(engine=engine, intent=None, source="action:test.trap_strike", action=None,
                          actor=entity("actor:test.attacker"))
    received = []
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "committed_teleport_receipt", [lambda eng, receipt: received.append(receipt)])
    movement_receipts.teleport_committed(ctx, entity("actor:test.target"), point(0), point(5), SimpleNamespace(sequence=7),
                                         movement_context="WILLING", unwilling=False, forced=False,
                                         settlement_source_id="passive:test.marker", settlement_feature_id="feature:test.marker")
    (receipt,) = received
    assert receipt["intent_id"] == "" and receipt["source_definition_id"] == "passive:test.marker"


class _Reached(Exception):
    pass


def test_untyped_strike_chain_reaches_the_attack_roll(monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_sequence_start", [])
    monkeypatch.setattr(paid_relocation, "preserve_pending", lambda *args: None)
    monkeypatch.setattr(attack_completion, "can_continue", lambda *args: True)

    def stop_at_roll(*args, **kwargs):
        raise _Reached()
    monkeypatch.setattr(typed_executor, "resolve_attack_damage", stop_at_roll)
    ctx = typed_executor.Context(engine=FakeEngine(), actor=entity("actor:test.attacker"), action=None,
                                 intent=None, typed=None, targets=[])
    with pytest.raises(_Reached):
        typed_executor._block_attack_in_chain(ctx, {})
