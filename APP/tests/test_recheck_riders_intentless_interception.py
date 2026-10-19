"""Trap and zone-driven strikes carry no declared intent; interception must not crash on that.

Synthetic fakes only: the interception checkpoint receives intent=None, as it does
when a trap spring or zone effect runs an attack without a declared intent.
"""
from types import SimpleNamespace

from combat import attack_declaration, ext
from combat.ext import afterimage_attacks


class FakeEngine:
    def __init__(self):
        self.state = SimpleNamespace(objects={"object:test.marker": object()}, map_images={})
        self.events = []

    def _append_event(self, event_type, source_id, **kwargs):
        self.events.append((event_type, source_id, kwargs))


def entity(entity_id):
    return SimpleNamespace(entity_id=entity_id)


RECEIPT = {"source_id": "passive:test.marker", "recipient_object_id": "object:test.marker",
           "condition_instance_id": "condition:test.marker"}


def test_intentless_receipt_is_recorded_with_none_intent(monkeypatch):
    engine = FakeEngine()
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_target_interception", [lambda *args: RECEIPT])
    spec = {}
    actor, target = entity("actor:test.attacker"), entity("actor:test.target")
    assert attack_declaration.intercepted(engine, actor, target, "action:test.trap_strike", None, 1, spec=spec) is True
    (event_type, source_id, kwargs), = engine.events
    assert event_type == "PASSIVE_TRIGGERED" and source_id == "passive:test.marker"
    assert kwargs["payload"]["kind"] == "attack_target_intercepted"
    assert kwargs["payload"]["intent_id"] is None
    assert kwargs["payload"]["original_target_id"] == "actor:test.target"
    # The cached decision for the same intentless key replays without a second event.
    assert attack_declaration.intercepted(engine, actor, target, "action:test.trap_strike", None, 1, spec=spec) is True
    assert len(engine.events) == 1


def test_afterimage_interception_without_intent_does_not_crash(monkeypatch):
    engine = FakeEngine()
    condition = SimpleNamespace(instance_id="condition:test.afterimage", source_definition_id="passive:test.afterimage")
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
    assert kwargs["payload"]["intent_id"] is None
