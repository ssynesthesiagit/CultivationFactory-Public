from combat.history_feed import concealed_condition_instances


def test_history_formatter_conceals_private_and_history_markers_without_engine():
    actor = {
        "entity_id": "actor-1",
        "display_name": "Keeper",
        "team_id": "allies",
        "primary_combatant": True,
        "armor_class": 10,
        "maximum_hp": 10,
        "current_hp": 10,
        "position": {"x": 0, "y": 0},
        "speed_ft": 30,
        "movement_remaining_ft": 30,
        "initiative_bonus": 0,
        "dexterity_score": 10,
        "proficiency_bonus": 2,
        "saving_throws": {},
        "resources": {},
        "resource_maximums": {},
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
                "data": {"source_audience": '["actor-1"]'},
            },
        },
    }
    hidden = concealed_condition_instances({"actors": {"actor-1": actor}})
    assert {"private", "history"} <= hidden

    # The retained event, not a discarded hook-argument copy, must carry privacy
    # through both application and an ordinary native condition-data update.
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ActorState, CombatEvent
    from combat.ext.source_procedures import private_history

    subject = ActorState.model_validate(actor)
    engine = SimpleNamespace(state=SimpleNamespace(actors={"actor-1": subject}))
    for event_type in ("CONDITION_APPLIED", "CONDITION_UPDATED"):
        for key, audience in (("private", ["actor-2"]), ("history", ["actor-1"])):
            payload = {"instance_id": key, "condition_id": subject.conditions[key].condition_id}
            event = CombatEvent(sequence=1, state_version=0, event_type=event_type,
                source_definition_id="procedure:test", trigger_or_intent_id="test",
                transaction_id="test", actor_id="actor-2", target_ids=("actor-1",), payload=payload)
            private_history(engine, event_type, {"originating_event": event, "payload": dict(payload)})
            assert event.payload["audience_actor_ids"] == audience
            assert event.payload.get("history_hidden", False) == (key == "history")
