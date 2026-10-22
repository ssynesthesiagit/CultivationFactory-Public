"""H22-36/H22-50 progress regressions, intended for the R22 integration.

Run with lock/round6 2115669c and hunt10a c09da302 combined. Round 21
still fails these checks; this lane does not change saved-fight locks.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.gate4_context import build_decision_context
from tests.test_c2_review import table_fixture, until_turn, action, send, auto_send, reload
from tests.test_riders_c2 import _sheet, ME, ATK, ALLY


@pytest.mark.parametrize("slowdown", [-10, -15])
def test_low_base_speed_slowdown_with_swift_movement_cannot_stall_ai(tmp_path, slowdown):
    def configure(bundles):
        for b in bundles:
            if b["actor_id"] == ME:
                b["actor_template"]["speed_ft"] = 5
                src = "test:hunt22.slowdown"
                b["actor_template"]["action_ids"].append(src)
                b["action_catalog"].append({
                    "source_definition_id": src, "display_name": "Test slowdown", "owner_id": ME,
                    "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "SELF",
                    "parameters": {"typed": {"source": src, "numbers": {}, "duration": {"kind": "instant"},
                        "effects": [{"type": "speed", "flat": slowdown, "applies_to": "self", "duration": "until_end_of_turn"},
                                    {"type": "movement", "distance_ft": 15, "applies_to": "self"}], "riders": []}}})
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid = table_fixture(tmp_path, {
        ME: _sheet(["TAL_ATHLETICS_SWIFT_MOVEMENT"]),
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (8, 6), ALLY: (3, 7)}, seed="H22-SPEED", configure=configure)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Test slowdown"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert actor.resources["resource:core.martial_focus"] == 1
    assert actor.movement_remaining_ft > 0
    # R6 suppresses genuine effective Speed 0. If Astra later corrects the
    # additive Speed arithmetic, normal positive-Speed movement must progress.
    speed = engine._effective_speed(actor)
    if speed <= 0:
        assert not table.state(mid)["menu"]["moves"]
        assert not any(c.kind.value == "MOVE" for c in build_decision_context(
            engine, combat.policies.for_actor(ME)[0], for_ai=True).legal_candidates)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    for _ in range(12):
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
        engine = reload(tmp_path, mid)
        if engine.state.current_actor_id != ME:
            break
    assert engine.state.current_actor_id != ME
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME and e.payload.get("interrupted")
                   and e.payload.get("cost_ft") == 0 for e in engine.events)


@pytest.mark.parametrize("auto", [False, True])
def test_positive_speed_interrupted_destination_is_not_reoffered(tmp_path, monkeypatch, auto):
    from combat import ext
    from tests.test_lock2_persistence import table_match

    def transient_block(engine, event_type, kwargs):
        actor = engine.state.actors.get(kwargs.get("actor_id"))
        if actor is None:
            return
        if event_type == "REACTION_WINDOW_OPENED" and (kwargs.get("payload") or {}).get("checkpoint") == "LEAVE_REACH":
            engine._apply_condition(actor, "condition:typed.prone", "test:hunt22.block", actor.entity_id,
                                    expires_on="UNTIL_REMOVED")
        elif event_type == "MOVEMENT_COMMITTED":
            engine._remove_condition(actor, "condition:typed.prone", "test:hunt22.block")
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [transient_block, *ext._HOOKS["event"]])
    combat, table, mid = table_match(tmp_path)
    menu = table.state(mid)["menu"]
    actor_id = menu["actor_id"]
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[actor_id]
    foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    move = next(c for c in menu["moves"] if
                max(abs(c["destination"]["x"] - foe.position.x), abs(c["destination"]["y"] - foe.position.y)) > 1 and
                max(abs(c["destination"]["x"] - actor.position.x), abs(c["destination"]["y"] - actor.position.y)) == 1)
    result = auto_send(combat, table, mid, move["candidate_id"]) if auto else send(table, mid, move["candidate_id"])
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[actor_id].position == actor.position
    assert engine._effective_speed(engine.state.actors[actor_id]) > 0
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("interrupted") and e.payload.get("cost_ft") == 0
               for e in engine.events)
    assert not any(c["destination"] == move["destination"] for c in table.state(mid)["menu"]["moves"])
    context = build_decision_context(engine, combat.policies.for_actor(actor_id)[0], for_ai=True)
    assert not any(c.kind.value == "MOVE" and c.destination.model_dump(mode="json") == move["destination"]
                   for c in context.legal_candidates)
