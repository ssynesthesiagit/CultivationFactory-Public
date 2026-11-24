"""Concentration cleanup records the condition it removed."""
from types import SimpleNamespace

from combat import concentration
from tests.test_feed_summary import _feed, render


def test_concentration_cleanup_names_the_removed_condition():
    row = SimpleNamespace(source_definition_id="action:test.burst", expires_on="CONCENTRATION_END",
                          applied_sequence=2, condition_id="condition:typed.prone")
    target = SimpleNamespace(entity_id="t", conditions={"instance": row})
    actor = SimpleNamespace(entity_id="a", concentration=None, conditions={})
    events = []

    class Engine:
        state = SimpleNamespace(actors={"a": actor, "t": target})

        def _remove_condition_instance(self, holder, iid, source, *, actor_id, payload, expected):
            events.append({"sequence": 1, "event_type": "CONDITION_REMOVED", "actor_id": actor_id,
                           "target_ids": [holder.entity_id], "source_definition_id": source,
                           "transaction_id": "t1", "trigger_or_intent_id": "t1", "payload": payload})

    concentration.end_conditions(Engine(), actor, "action:test.burst", None, "FAILED_SAVE")
    rows = _feed(events, [])
    lines = [x["text"] for x in render([rows], detail=True)]
    assert not any("Unnamed effect" in line for line in lines), lines
    assert any("Prone" in line for line in lines), lines
