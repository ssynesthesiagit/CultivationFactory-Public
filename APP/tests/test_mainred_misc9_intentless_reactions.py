"""Reaction attacks and teleports may happen outside any table intent (MAINREDMISC9).

Synthetic engine and actors only; no private fixtures, no live services.
"""
from types import SimpleNamespace as NS

from combat import ext
from combat.attack_declaration import intercepted
from combat.ext import afterimage_attacks
from combat import movement_receipts

RECEIPT = {"source_id": "test:decoy", "recipient_object_id": "object:decoy",
           "condition_instance_id": "condition:decoy.1"}


class FakeEngine:
    def __init__(self):
        self.state = NS(objects={"object:decoy": object()}, map_images={}, match_id="m1",
                        round_number=2, current_actor_id="caster", current_slot_index=0)
        self.events = []
        self.action_catalog = {}
        self.grid = NS(distance_ft=lambda a, b: 10)

    def _append_event(self, event_type, source_id, **kwargs):
        self.events.append({"event_type": event_type, "source_id": source_id, **kwargs})
        return NS(sequence=len(self.events))


def test_intercept_without_intent_writes_receipt_with_null_intent_and_caches(monkeypatch):
    ext.effects()
    calls = []

    def provider(engine, attacker, target, source, intent, index):
        calls.append(intent)
        return dict(RECEIPT)

    monkeypatch.setitem(ext._HOOKS, "attack_target_interception", [provider])
    engine = FakeEngine()
    actor, target = NS(entity_id="reactor"), NS(entity_id="foe")
    spec = {}
    assert intercepted(engine, actor, target, "test:reaction", None, 1, spec=spec) is True
    assert len(engine.events) == 1
    event = engine.events[0]
    assert event["payload"]["kind"] == "attack_target_intercepted"
    assert event["payload"]["intent_id"] == ""  # the published empty causal id (main's test_attack_declaration_no_intent)
    assert event["payload"]["recipient_object_id"] == "object:decoy"
    # A second declaration with the same key reuses the cached answer: no new roll, no new row.
    assert intercepted(engine, actor, target, "test:reaction", None, 1, spec=spec) is True
    assert len(calls) == 1 and len(engine.events) == 1


def test_intercept_without_intent_abstains_and_writes_nothing(monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_target_interception", [lambda *args: None])
    engine = FakeEngine()
    spec = {}
    assert intercepted(engine, NS(entity_id="reactor"), NS(entity_id="foe"), "test:reaction", None, 1, spec=spec) is False
    assert engine.events == []


def test_afterimage_provider_accepts_reaction_attack_without_intent(monkeypatch):
    ext.effects()
    condition = NS(instance_id="condition:image.1", source_definition_id="test:afterimage",
                   data={"label": "Afterimage"})
    owner = NS(entity_id="foe", display_name="Foe", conditions={"condition:image.1": condition})
    attacker = NS(entity_id="reactor", display_name="Reactor")
    image = NS(object_id="object:image.1", component={"condition_instance_id": "condition:image.1"})
    destroyed = []

    class Roller:
        def roll(self, spec, **kwargs):
            return NS(total=1, roll_id="roll:1")

    engine = FakeEngine()
    engine.roller = Roller()
    engine._record_roll = lambda roll: None
    monkeypatch.setattr(afterimage_attacks, "perceived_image", lambda engine, viewer, target: image)
    monkeypatch.setattr(afterimage_attacks, "destroy_image",
                        lambda engine, object_id, source, actor_id, intent_id: destroyed.append(intent_id) or True)
    receipt = afterimage_attacks.intercept_attack(engine, attacker, owner, "test:reaction", None, 1)
    assert receipt is not None
    assert receipt["recipient_object_id"] == "object:image.1"
    assert destroyed == [""]
    assert engine.events[0]["payload"]["intent_id"] == ""


def test_teleport_from_trigger_without_intent_publishes_empty_intent_receipt(monkeypatch):
    ext.effects()
    receipts = []
    monkeypatch.setitem(ext._HOOKS, "committed_teleport_receipt",
                        [lambda engine, receipt: receipts.append(dict(receipt))])
    engine = FakeEngine()
    ctx = NS(engine=engine, intent=None, source="test:trigger", action=None, actor=NS(entity_id="caster"))
    subject = NS(entity_id="ally")
    previous, destination = NS(x=0, y=0, z=0), NS(x=2, y=0, z=0)
    movement_receipts.teleport_committed(ctx, subject, previous, destination, NS(sequence=7),
                                         movement_context="WILLING", unwilling=False, forced=False)
    assert len(receipts) == 1
    assert receipts[0]["intent_id"] == ""
    assert receipts[0]["receipt_id"] == "m1:movement:7"
    assert receipts[0]["distance_ft"] == 10
    assert receipts[0]["willing"] == 1
