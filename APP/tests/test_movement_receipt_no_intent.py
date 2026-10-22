"""Teleports committed outside a table intent still publish a causal receipt."""
from types import SimpleNamespace

from combat import movement_receipts


def test_teleport_without_an_intent_publishes_an_empty_causal_id(monkeypatch):
    """A trigger's teleport has no Context.intent; the landing must not fail with AttributeError."""
    receipts = []
    monkeypatch.setattr(movement_receipts.ext, "has", lambda name: True)
    monkeypatch.setattr(movement_receipts.ext, "run_strict",
                        lambda name, engine, receipt: receipts.append(receipt))
    position = SimpleNamespace(x=3, y=6, z=0)
    ctx = SimpleNamespace(
        engine=SimpleNamespace(
            state=SimpleNamespace(match_id="match:test", round_number=2, current_actor_id="actor:owner",
                                  current_slot_index=0),
            grid=SimpleNamespace(distance_ft=lambda previous, destination: 10)),
        intent=None, source="action:test.trigger_teleport",
        action=SimpleNamespace(parameters={"typed": {"source": "action:test.trigger_teleport"}}),
        actor=SimpleNamespace(entity_id="actor:owner"))
    subject = SimpleNamespace(entity_id="actor:owner")
    movement_event = SimpleNamespace(sequence=4)

    movement_receipts.teleport_committed(
        ctx, subject, position, SimpleNamespace(x=4, y=6, z=0), movement_event,
        movement_context="WILLING", unwilling=False, forced=False)

    assert len(receipts) == 1
    assert receipts[0]["intent_id"] == ""
    assert receipts[0]["receipt_id"] == "match:test:movement:4"
