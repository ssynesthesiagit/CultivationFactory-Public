from combat.history_feed import concealed_condition_instances


def test_history_formatter_conceals_private_and_history_markers_without_engine():
    actor = {
        "entity_id": "actor-1",
        "conditions": {
            "private": {
                "instance_id": "private",
                "condition_id": "condition:source.consequence",
                "source_definition_id": "procedure:test",
                "source_actor_id": "actor-2",
                "target_id": "actor-1",
                "applied_sequence": 1,
                "data": {"source_audience": '["actor-2"]'},
            },
            "history": {
                "instance_id": "history",
                "condition_id": "condition:source.procedure_history",
                "source_definition_id": "procedure:test",
                "source_actor_id": "actor-2",
                "target_id": "actor-1",
                "applied_sequence": 2,
                "data": {},
            },
        },
    }
    hidden = concealed_condition_instances({"actors": {"actor-1": actor}})
    assert {"private", "history"} <= hidden
