import pytest

from combat.history_feed import format_history_feed


@pytest.mark.parametrize("source_id", ["ability:athletics.rapid_motion", "ability:test.unrelated_passive"])
def test_passive_event_without_a_readable_breakdown_keeps_visible_placeholder(source_id) -> None:
    rows = format_history_feed(
        [{
            "sequence": 1000,
            "event_type": "PASSIVE_TRIGGERED",
            "source_definition_id": source_id,
            "trigger_or_intent_id": "rapid-motion-dash",
            "transaction_id": "rapid-motion-dash",
            "actor_id": "runner",
            "target_ids": [],
            "payload": {},
        }],
        [],
        pre_state=None,
        post_state={"actors": {}},
        actor_names={"runner": "Runner"},
        definition_names={},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["summary"] == "Detailed breakdown was not recorded for this event."
    assert row["detailed_breakdown_recorded"] is False
    assert row["event_sequence"] == 1000
    assert row["source_definition_id"] == source_id
    assert row["raw"]["payload"] == {}
