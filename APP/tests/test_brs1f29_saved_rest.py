"""Saved-journey rests use the live engine ending path, including its subscribers."""
import json

import pytest

from combat import ext
from combat.ext.journey_setup import encounter_snapshot
from combat.gate2_runtime_models import ConditionInstance
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.body_refining_support import ROOT, sheet

A, B = "actor:factory.student", "actor:factory.companion"
MARKER = "condition:typed.br_variant_temp"
PERMANENT = "condition:test.permanent"
SPOTS = {A: {"x": 3, "y": 6}, B: {"x": 8, "y": 6}}


def saved_journey(tmp_path, monkeypatch):
    arena = {"stable_id": "rest:test", "display_name": "Rest test clearing",
             "width_squares": 20, "height_squares": 20,
             "square_size_ft": 5, "starting_positions": {}, "terrain_regions": []}
    monkeypatch.setattr(CombatService, "_factory_owner_sheet",
                        lambda self, pid: sheet(spheres=["tianxia.sphere.flowers"] if pid == "student" else []))
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self: {"scene": arena})

    def cold():
        return CombatService(ROOT, tmp_path)

    state = cold().create_journey(project_ids=["student", "companion"], arena_id="scene",
                                  positions=SPOTS, base_paces={A: 5, B: 5})
    jid = state["journey_id"]
    session = cold().journeys.load(jid)
    conditions = {}
    for iid, cid, expiry in (("rest", MARKER, "UNTIL_SHORT_REST"),
                             ("permanent", PERMANENT, "UNTIL_REMOVED")):
        condition = ConditionInstance(instance_id=iid, condition_id=cid,
            source_definition_id="tianxia.brvariant.flowers.blooming-body",
            source_actor_id=A, target_id=A, applied_sequence=0, expires_on=expiry)
        conditions[iid] = condition.model_dump_json()
    session.state["actors"][A]["encounter_snapshot"] = {
        "current_hp": 10, "maximum_hp": 40, "temporary_hp": 2,
        "active": 1, "life_state": "", "conditions": conditions}
    cold().journeys.save(session)
    mid = cold().journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"},
                                      maximum_rounds=1, positions=SPOTS)["match_id"]
    for _ in range(6):
        fresh = cold()
        if fresh._load_session(mid).engine.state.terminal_result is not None:
            break
        table = TabletopService(fresh, tmp_path)
        menu = table.state(mid)["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    else:
        pytest.fail("The one-round encounter did not finish")
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound["revision"])
    assert any(json.loads(row)["condition_id"] == MARKER
               for row in resumed["actors"][A]["encounter_snapshot"]["conditions"].values())
    return cold, jid, mid


def rest_events(state):
    return [json.loads(encoded) for event in state["events"]
            if event["kind"] == "ENCOUNTER_SHORT_REST" for encoded in event["combat_events"]]


def test_saved_rest_cold_reload_records_the_same_expiry_and_subscribers_as_live(tmp_path, monkeypatch):
    cold, jid, mid = saved_journey(tmp_path, monkeypatch)
    ext.load_plug_ins()
    seen = []

    def subscriber(engine, event_type, kwargs):
        if event_type == "CONDITION_REMOVED" and kwargs.get("payload", {}).get("checkpoint") == "SHORT_REST":
            seen.append(kwargs["ended_effect"]["condition_id"])
            # A real subscriber consequence, not just observing that a row disappeared.
            engine._grant_temp_hp(engine.state.actors[A], 7, "test:rest_subscriber", A)

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), subscriber])
    live = cold()._load_session(mid).engine
    terminal = live.state.model_dump(mode="json")
    start = len(live.events)
    live.short_rest(A)
    expected = [event.model_dump(mode="json") for event in live.events[start:]]
    assert seen == [MARKER]
    seen.clear()

    before = cold().journey_state(jid)
    cold().journey_act(jid, before["revision"], A, "short_rest")
    after = cold().journey_state(jid)  # no warm engine/session survives
    assert rest_events(after) == expected, "saved rests must record the live engine's expiry events"
    assert seen == [MARKER], "saved rests must run ordinary ending subscribers"
    snapshot = after["actors"][A]["encounter_snapshot"]
    assert snapshot == encounter_snapshot(live.state.actors[A])
    assert snapshot["temporary_hp"] == 7
    assert any(json.loads(row)["condition_id"] == PERMANENT for row in snapshot["conditions"].values())
    assert not any(json.loads(row)["condition_id"] == MARKER for row in snapshot["conditions"].values())
    assert after["seconds"] == before["seconds"] + 3600
    assert cold()._load_session(mid).engine.state.model_dump(mode="json") == terminal, "terminal fights stay immutable"
    assert cold().journey_replay(jid)["status"] == "PASS"

    # Resting again, or carrying the survivor to another journey, cannot re-end an old marker.
    cold().journey_act(jid, after["revision"], A, "short_rest")
    twice = cold().journey_state(jid)
    assert rest_events(twice) == expected
    assert cold().journey_replay(jid)["status"] == "PASS"
    cold().journey_act(jid, twice["revision"], A, "finish")
    newer = cold().create_journey(project_ids=["student", "companion"], arena_id="scene",
                                  positions=SPOTS, base_paces={A: 5, B: 5})
    cold().journey_act(newer["journey_id"], newer["revision"], A, "short_rest")
    assert not rest_events(cold().journey_state(newer["journey_id"]))
    assert cold().journey_replay(newer["journey_id"])["status"] == "PASS"


def test_failed_rest_subscriber_does_not_save_a_partial_rest(tmp_path, monkeypatch):
    cold, jid, mid = saved_journey(tmp_path, monkeypatch)
    ext.load_plug_ins()

    def fail(engine, event_type, kwargs):
        if event_type == "CONDITION_REMOVED" and kwargs.get("payload", {}).get("checkpoint") == "SHORT_REST":
            raise ValueError("rest subscriber refused")

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", ()), fail])
    before = cold().journey_state(jid)
    terminal = cold()._load_session(mid).engine.state.model_dump(mode="json")
    with pytest.raises(ValueError, match="rest subscriber refused"):
        cold().journey_act(jid, before["revision"], A, "short_rest")
    assert cold().journey_state(jid) == before
    assert cold()._load_session(mid).engine.state.model_dump(mode="json") == terminal
