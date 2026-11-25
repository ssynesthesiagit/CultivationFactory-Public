from types import SimpleNamespace

from combat.history_feed import format_history_feed
from combat.tabletop_service import TabletopService


def test_disabled_action_reason_uses_current_turn_state():
    actor = SimpleNamespace(entity_id="actor:a", action_available=False, bonus_action_available=True,
                            reaction_available=True, resources={"resource:body.cp": 1}, conditions={})
    actions = {"action:spent": SimpleNamespace(owner_id=actor.entity_id, source_definition_id="action:spent",
                                               economy="ACTION", costs=(), parameters={})}
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}), action_catalog=actions)
    menu = {"manual": True, "actor_id": actor.entity_id, "actions": []}

    reasons = TabletopService._unavailable_reasons(engine, menu)

    assert reasons["act:action:spent"] == "Used: your action is spent; it returns at the start of your next turn."


def test_disabled_action_reason_reports_unaffordable_cp_when_turn_action_is_available():
    from tests.test_effect_durations import _fight
    engine, actor, _ = _fight()
    original = next(a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id)
    action = original.model_copy(update={"source_definition_id": "action:cp", "economy": "ACTION",
                                         "costs": (("resource:body.cp", 2),), "parameters": {}})
    # The native availability query follows the real action catalogue and ownership.
    engine.action_catalog["action:cp"] = action
    actor.action_ids += ("action:cp",)
    actor.resources["resource:body.cp"] = 1

    reasons = TabletopService._unavailable_reasons(engine, {"manual": True, "actor_id": actor.entity_id, "actions": []})

    assert reasons["act:action:cp"] == (
        "Requires 2 Cultivation Points (CP) (you have 1); no affordable alternative payment is available."
    )


def test_hidden_condition_bookkeeping_is_omitted_from_player_history():
    events = [{
        "event_type": "CONDITION_APPLIED", "actor_id": "a", "target_ids": ["a"],
        "source_definition_id": "action:typed.smoke.court", "sequence": 1,
        "payload": {"condition_id": "condition:typed.concentration_deadline",
                    "gate3_condition_after": {"data": {"hidden": True, "started_sequence": 7}}},
    }]

    rows = format_history_feed(events, [], pre_state=None, post_state={}, actor_names={"a": "Lingfeng Ironclad"},
                               definition_names={"action:typed.smoke.court": "Court of Hidden Witnesses"})

    assert rows == []


def test_hidden_condition_removal_is_omitted_with_and_without_snapshot_metadata():
    for payload in (
        {"condition_id": "condition:typed.concentration_deadline", "instance_id": "deadline"},
        {"condition_id": "condition:typed.concentration_deadline", "instance_id": "deadline",
         "gate3_condition_before": {"data": {"hidden": True}}},
    ):
        rows = format_history_feed([{
            "event_type": "CONDITION_REMOVED", "actor_id": "a", "target_ids": ["a"],
            "source_definition_id": "action:typed.smoke.court", "sequence": 2, "payload": payload,
        }], [], pre_state=None, post_state={}, actor_names={"a": "Lingfeng Ironclad"},
            definition_names={"action:typed.smoke.court": "Court of Hidden Witnesses"})
        assert rows == []


def test_transient_deadline_history_is_hidden_without_changing_replay_enrichment():
    from combat.gate3_reducer import enrich_committed_events
    from tests.test_effect_durations import _fight

    post, actor, _foe = _fight()
    events = enrich_committed_events([{
        "event_type": "CONDITION_APPLIED", "actor_id": actor.entity_id, "target_ids": [actor.entity_id],
        "source_definition_id": "action:typed.smoke.court", "sequence": 1,
        "payload": {"condition_id": "condition:typed.concentration_deadline", "instance_id": "deadline"},
    }], post_engine=post)
    # The saved-fight reducer is restored: transient data stays empty. The
    # plug-in's history adapter hides the timer without changing replay bytes.
    assert events[0]["payload"]["gate3_condition_after"]["data"] == {}
    assert format_history_feed(events, [], pre_state=None, post_state={}, actor_names={}, definition_names={}) == []


def test_deadline_plugin_removal_event_carries_the_removed_hidden_row():
    from combat.ext.concentration_duration import DEADLINE, remove
    from tests.test_effect_durations import _fight

    engine, actor, _foe = _fight()
    engine._apply_condition(actor, DEADLINE, "action:typed.smoke.court", actor.entity_id,
                            expires_on="UNTIL_REMOVED", data={"hidden": True, "started_sequence": 1})
    instance_id = next(iid for iid, row in actor.conditions.items() if row.condition_id == DEADLINE)
    remove(engine, actor, instance_id)
    event = next(event for event in reversed(engine.events) if event.event_type == "CONDITION_REMOVED")
    assert event.payload["gate3_condition_before"]["data"]["hidden"] is True
