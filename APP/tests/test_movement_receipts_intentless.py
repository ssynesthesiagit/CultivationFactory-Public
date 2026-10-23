"""A teleport committed outside a table intent publishes its receipt with an empty intent id."""
from types import SimpleNamespace as NS

from combat import movement_receipts


def _pos(x, y, z=0):
    return NS(x=x, y=y, z=z)


def test_teleport_committed_without_a_table_intent_publishes_an_empty_intent_id(monkeypatch):
    published = []
    monkeypatch.setattr(movement_receipts.ext, "has", lambda name: name == "committed_teleport_receipt")
    monkeypatch.setattr(movement_receipts.ext, "run_strict",
                        lambda name, engine, receipt: published.append((name, receipt)))
    actor = NS(entity_id="actor:caster")
    engine = NS(state=NS(match_id="m1", round_number=2, current_actor_id="actor:caster", current_slot_index=0),
                grid=NS(distance_ft=lambda a, b: 30))
    ctx = NS(engine=engine, intent=None, source="src.trigger", action=None, actor=actor)
    movement_receipts.teleport_committed(ctx, NS(entity_id="actor:caster"), _pos(1, 1), _pos(4, 1), NS(sequence=7),
                                         movement_context="WILLING", unwilling=False, forced=None,
                                         settlement_source_id="src.trigger", settlement_feature_id="feat.trigger")
    assert len(published) == 1
    name, receipt = published[0]
    assert name == "committed_teleport_receipt"
    assert receipt["intent_id"] == ""
    assert receipt["receipt_id"] == "m1:movement:7"
    assert receipt["source_definition_id"] == "src.trigger" and receipt["source_feature_id"] == "feat.trigger"
    assert receipt["self_teleport"] == 1 and receipt["distance_ft"] == 30
