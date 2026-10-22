"""A reaction attack declared outside any table intent gets a receipt keyed with an empty intent id.

Synthetic stubs only: no saved fights, no live services.
"""
from types import SimpleNamespace as NS

from combat import attack_declaration


RECIPIENT = "obj:afterimage-1"


def _engine(events):
    def append_event(kind, source_id, **kwargs):
        events.append((kind, source_id, kwargs))
    return NS(state=NS(objects={RECIPIENT: object()}, map_images={}), _append_event=append_event)


def test_intentless_attack_gets_its_interception_receipt_and_keeps_it_on_repeat(monkeypatch):
    calls = []
    receipt = {"source_id": "src.afterimage", "recipient_object_id": RECIPIENT, "condition_instance_id": "cond.1"}

    def run_checkpoint(point, engine, actor, target, source, intent, index):
        calls.append((point, source, intent, index))
        return [receipt]

    monkeypatch.setattr(attack_declaration.ext, "run_checkpoint", run_checkpoint)
    events = []
    engine = _engine(events)
    actor = NS(entity_id="actor:slip")
    target = NS(entity_id="actor:foe")
    spec = {}

    assert attack_declaration.intercepted(engine, actor, target, "src.slip_and_strike", None, spec=spec) is True

    # The receipt is accepted without a table intent and the event carries an empty intent id.
    assert len(events) == 1
    kind, source_id, kwargs = events[0]
    assert kind == "PASSIVE_TRIGGERED" and source_id == "src.afterimage"
    assert kwargs["target_ids"] == (RECIPIENT,)
    assert kwargs["payload"]["kind"] == "attack_target_intercepted"
    assert kwargs["payload"]["intent_id"] is None
    assert kwargs["payload"]["original_target_id"] == "actor:foe"
    assert kwargs["payload"]["attack_source_id"] == "src.slip_and_strike"
    assert kwargs["payload"]["attack_index"] == 1
    assert spec["target_interception"]["key"] == ("actor:slip", "actor:foe", "src.slip_and_strike", None, 1)

    # A repeat call with the same key reuses the stored answer: no second provider call, no second event.
    assert attack_declaration.intercepted(engine, actor, target, "src.slip_and_strike", None, spec=spec) is True
    assert len(calls) == 1
    assert len(events) == 1
