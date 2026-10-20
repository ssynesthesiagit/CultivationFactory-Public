from combat.history_feed import format_history_feed


def test_passive_event_without_a_readable_breakdown_is_not_player_facing() -> None:
    rows = format_history_feed(
        [{
            "sequence": 1000,
            "event_type": "PASSIVE_TRIGGERED",
            "source_definition_id": "ability:athletics.rapid_motion",
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
    assert rows == []
