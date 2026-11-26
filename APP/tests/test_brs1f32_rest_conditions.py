"""Saved rests preserve permanent effects through native ending subscribers."""
import json

from combat.ext import journey_setup
from combat.gate2_runtime_models import ConditionInstance
from tests.test_brs1f14r_short_rest_boundary import session_with
from tests.test_brs1f29_saved_rest import A, saved_journey


def test_saved_rest_preserves_permanent_condition_bytes():
    conditions = {
        iid: ConditionInstance(
            instance_id=iid, condition_id="condition:test." + iid,
            source_definition_id="test:rest", source_actor_id="actor:a",
            target_id="actor:a", applied_sequence=0, expires_on=expiry,
            data={"label": iid})
        for iid, expiry in (("rest", "UNTIL_SHORT_REST"),
                            ("permanent", "UNTIL_REMOVED"),
                            ("indefinite", None))
    }
    snapshot = {
        "current_hp": 10, "maximum_hp": 40, "temporary_hp": 0,
        "active": 1, "life_state": "", "death_saves": {"ok": 0, "bad": 0},
        "conditions": {iid: json.dumps(row.model_dump(mode="json", exclude_none=True), sort_keys=True)
                       for iid, row in conditions.items()},
    }
    session = session_with(snapshot)
    journey_setup.end_rest_scoped_conditions(session, "actor:a")
    after = session.state["actors"]["actor:a"]["encounter_snapshot"]
    assert after["conditions"] == {
        iid: row for iid, row in snapshot["conditions"].items() if iid != "rest"
    }, session.state["events"]
    events = [json.loads(row) for row in session.state["events"][-1]["combat_events"]]
    assert [(event["payload"]["instance_id"], event["payload"]["condition_id"])
            for event in events if event["event_type"] == "CONDITION_REMOVED"] == [
                ("rest", "condition:test.rest")]


def test_unidentified_removal_never_matches_an_absent_joint_lock_link():
    """Legacy/native events with no instance cannot end unrelated conditions."""
    permanent = ConditionInstance(
        instance_id="permanent", condition_id="condition:test.permanent",
        source_definition_id="test:rest", source_actor_id="actor:a",
        target_id="actor:a", applied_sequence=0, expires_on="UNTIL_REMOVED")
    snapshot = {
        "current_hp": 10, "maximum_hp": 40, "temporary_hp": 0,
        "active": 1, "life_state": "", "death_saves": {"ok": 0, "bad": 0},
        "conditions": {"permanent": permanent.model_dump_json()},
    }
    session = session_with(snapshot)
    engine = session.encounter_loader("test:saved-encounter")
    actor = engine.state.actors["actor:a"]
    journey_setup.restore_encounter(actor, snapshot, merge_conditions=False)
    engine._append_event("CONDITION_REMOVED", "test:rest", target_ids=(actor.entity_id,),
                         payload={"condition_id": "condition:test.other"})
    assert actor.conditions == {"permanent": permanent}


def test_identified_grapple_removal_ends_only_its_linked_joint_lock():
    snapshot = {
        "current_hp": 10, "maximum_hp": 40, "temporary_hp": 0,
        "active": 1, "life_state": "", "death_saves": {"ok": 0, "bad": 0},
        "conditions": {},
    }
    engine = session_with(snapshot).encounter_loader("test:saved-encounter")
    actor = engine.state.actors["actor:a"]
    for iid, cid, data in (
        ("grip", "condition:typed.grappled", {}),
        ("lock", "condition:typed.restrained", {"joint_lock_grip": "grip"}),
        ("other", "condition:typed.restrained", {"joint_lock_grip": "other-grip"}),
        ("permanent", "condition:test.permanent", {}),
    ):
        actor.conditions[iid] = ConditionInstance(
            instance_id=iid, condition_id=cid, source_definition_id="test:rest",
            source_actor_id=actor.entity_id, target_id=actor.entity_id,
            applied_sequence=0, expires_on="UNTIL_REMOVED", data=data)
    engine._remove_condition_instance(actor, "grip", "test:rest", payload={"checkpoint": "TEST"})
    assert set(actor.conditions) == {"other", "permanent"}
    removal = next(event for event in engine.events if event.event_type == "CONDITION_REMOVED"
                   and event.payload.get("checkpoint") == "TEST")
    assert removal.payload == {"checkpoint": "TEST", "instance_id": "grip",
                               "condition_id": "condition:typed.grappled"}


def test_permanent_condition_survives_saved_journey_rests_and_replay(tmp_path, monkeypatch):
    cold, jid, _mid = saved_journey(tmp_path, monkeypatch)
    before = cold().journey_state(jid)
    permanent = before["actors"][A]["encounter_snapshot"]["conditions"]["permanent"]
    for _ in range(2):
        cold().journey_act(jid, before["revision"], A, "short_rest")
        before = cold().journey_state(jid)
        assert before["actors"][A]["encounter_snapshot"]["conditions"] == {"permanent": permanent}
        assert cold().journey_replay(jid)["status"] == "PASS"
