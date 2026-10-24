"""Teleport receipts for effects resolved without an action intent.

Ongoing and derived effects (ability_source, area_safety, ...) build a Context
with intent=None. Landing such a teleport must publish its committed-motion
receipt with an empty intent_id instead of raising AttributeError. Synthetic
fixture only: no engine, no saved fight, no private data.
"""
from types import SimpleNamespace

import combat.ext as ext
import combat.movement_receipts as movement_receipts
from combat.gate2_runtime_models import Position


class _Grid:
    def distance_ft(self, a, b):
        return 5 * (abs(a.x - b.x) + abs(a.y - b.y))


def _engine():
    state = SimpleNamespace(match_id="match:test", round_number=2,
                            current_actor_id="actor:owner", current_slot_index=0)
    return SimpleNamespace(state=state, grid=_Grid())


def _ctx(intent):
    owner = SimpleNamespace(entity_id="actor:owner", display_name="Owner")
    action = SimpleNamespace(parameters={"typed": {"source": "TAL_ORIGIN_STEP"}}, display_name="Step")
    return SimpleNamespace(engine=_engine(), actor=owner, source="passive:test.origin",
                           action=action, intent=intent)


def test_teleport_receipt_without_intent_has_empty_intent_id(monkeypatch):
    published = []
    monkeypatch.setattr(movement_receipts.ext, "has", lambda point: True)
    monkeypatch.setattr(movement_receipts.ext, "run_strict",
                        lambda point, engine, receipt: published.append((point, receipt)))
    ctx = _ctx(intent=None)
    subject = SimpleNamespace(entity_id="actor:owner")
    event = SimpleNamespace(sequence=7)

    movement_receipts.teleport_committed(
        ctx, subject, Position(x=1, y=1), Position(x=3, y=1), event,
        movement_context="WILLING", unwilling=False, forced=None)

    assert len(published) == 1
    point, receipt = published[0]
    assert point == "committed_teleport_receipt"
    assert receipt["intent_id"] == ""
    assert receipt["receipt_id"] == "match:test:movement:7"
    assert receipt["source_feature_id"] == "TAL_ORIGIN_STEP"
    assert receipt["distance_ft"] == 10
    assert receipt["willing"] == receipt["self_teleport"] == 1
    assert all(type(v) in (int, str) for v in receipt.values())


def test_teleport_receipt_with_intent_keeps_intent_id(monkeypatch):
    published = []
    monkeypatch.setattr(movement_receipts.ext, "has", lambda point: True)
    monkeypatch.setattr(movement_receipts.ext, "run_strict",
                        lambda point, engine, receipt: published.append(receipt))
    intent = SimpleNamespace(intent_id="intent:42")
    movement_receipts.teleport_committed(
        _ctx(intent), SimpleNamespace(entity_id="actor:owner"), Position(x=1, y=1),
        Position(x=1, y=3), SimpleNamespace(sequence=8),
        movement_context="WILLING", unwilling=False, forced=None)
    assert published[0]["intent_id"] == "intent:42"
