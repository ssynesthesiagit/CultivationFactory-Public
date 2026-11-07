"""Lock round 26 item 3: the general native repeat-save resolution seam (Dreams finding 2), through
CombatService, persisted execute_intent, cold reload and mechanical replay.

Minimal test hooks stand in for a plug-in such as Lucid Escape (auto/dreams); no ability ID enters core.
"""
from contextlib import contextmanager

import pytest

from combat.gate2_runtime_models import ActionDefinition
from tests.test_auto_docket import ME
from tests.test_lock26_movement_concentration_seams import _execute, _match
from tests.test_lock_choices import install

CONDITION = "condition:typed.frightened"


def _actions(info):
    return [ActionDefinition(source_definition_id="action:test.lock26.dread", display_name="Lock26 Dread",
        owner_id=info["actor_id"], economy="NONE", resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"source": "test:lock26.dread", "numbers": {**info["numbers"], "save_dc": 30},
            "duration": {"kind": "rounds", "amount": 10},
            "effects": [{"type": "condition", "condition": "frightened", "applies_to": "self",
                         "repeat_save": {"ability": "WIS", "when": "end"}}]}})]


def _setup(tmp_path, monkeypatch, failed, scope=None):
    install(monkeypatch, "compile_actions", _actions)
    install(monkeypatch, "repeat_save_failed", failed)
    if scope is not None:
        install(monkeypatch, "repeat_save_scope", scope)
    mid, session = _match(tmp_path, "LOCK26-REPEAT")
    session = _execute(tmp_path, mid, lambda c: c.source_definition_id == "action:test.lock26.dread")
    me = session.engine.state.actors[ME]
    [row] = [c for c in me.conditions.values() if c.condition_id == CONDITION]
    assert row.data["repeat_save"]["dc"] == 30  # WIS +2 cannot reach DC 30: the native save fails
    return mid, row.instance_id


def test_failed_repeat_save_can_be_settled_as_success_with_deferred_results_after_removal(tmp_path, monkeypatch):
    seen, order = [], []

    def failed(engine, resolution):
        seen.append({k: resolution[k] for k in ("holder_id", "instance_id", "condition_id", "source_definition_id",
                                                 "source_actor_id", "ability", "dc", "named", "checkpoint", "success")})
        seen[-1]["failed_total"] = resolution["roll"].total
        return {"result": "SUCCESS", "settled_by": "test:lock26.rescue"}

    def scope(engine, resolution):
        @contextmanager
        def bounded():
            order.append("enter")
            yield
            # Deferred result: runs after the native exact-instance removal (Lucid's move_after).
            order.append(("exit", resolution["success"], resolution["instance_id"] in engine.state.actors[ME].conditions))
            engine._append_event("PASSIVE_TRIGGERED", "test:lock26.rescue", actor_id=ME, payload={"log": "deferred"})
        return bounded()

    mid, iid = _setup(tmp_path, monkeypatch, failed, scope)
    session = _execute(tmp_path, mid)  # END_TURN: the native end-of-turn repeat save
    assert len(seen) == 1
    assert seen[0] == {"holder_id": ME, "instance_id": iid, "condition_id": CONDITION,
                       "source_definition_id": "action:test.lock26.dread", "source_actor_id": ME, "ability": "WIS",
                       "dc": 30, "named": ("frightened",), "checkpoint": "END_OF_TURN", "success": False,
                       "failed_total": seen[0]["failed_total"]}
    assert seen[0]["failed_total"] < 30
    assert order == ["enter", ("exit", True, False)]
    me = session.engine.state.actors[ME]
    assert iid not in me.conditions
    events = session.engine.events
    removed = next(i for i, e in enumerate(events) if e.event_type == "CONDITION_REMOVED" and e.payload.get("instance_id") == iid)
    assert events[removed].payload == {"instance_id": iid, "condition_id": CONDITION, "checkpoint": "END_OF_TURN",
                                       "repeat_save": True, "settled_by": "test:lock26.rescue"}
    deferred = next(i for i, e in enumerate(events) if e.source_definition_id == "test:lock26.rescue" and e.event_type == "PASSIVE_TRIGGERED")
    assert deferred > removed
    # The native failed die is preserved, not rewritten.
    assert any(r.actor_id == ME and r.total == seen[0]["failed_total"] for r in session.engine.rolls)


def test_failed_repeat_save_without_an_owner_keeps_the_condition(tmp_path, monkeypatch):
    calls = []
    mid, iid = _setup(tmp_path, monkeypatch, lambda engine, resolution: calls.append(resolution["instance_id"]))
    session = _execute(tmp_path, mid)
    assert calls == [iid]
    # Its 10-round duration outlasts this checkpoint, so only the failed repeat save could have ended it.
    assert not any(e.event_type == "CONDITION_REMOVED" and e.payload.get("instance_id") == iid for e in session.engine.events)
    from combat.gate5_service import CombatService
    from tests.test_auto_docket import ROOT
    cold = CombatService(ROOT, tmp_path)._load_session(mid)  # _execute already cold-loaded and replayed; check again here
    assert cold.engine.state.actors[ME].conditions[iid].condition_id == CONDITION
    assert cold.mechanical.replay()["status"] == "PASS"
    assert cold.engine.state.actors[ME].conditions[iid].condition_id == CONDITION


def test_repeat_save_scope_unwinds_on_errors_and_commits_nothing(tmp_path, monkeypatch):
    order = []

    def scope(engine, resolution):
        @contextmanager
        def bounded():
            order.append("enter")
            try:
                yield
            finally:
                order.append("exit")
        return bounded()

    mid, iid = _setup(tmp_path, monkeypatch, lambda engine, resolution: {"result": "MAYBE"}, scope)
    from combat.gate5_service import CombatService
    from tests.test_auto_docket import ROOT
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.state_version
    with pytest.raises(Exception):
        _execute(tmp_path, mid)
    assert order == ["enter", "exit"]
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state.state_version == before and iid in cold.engine.state.actors[ME].conditions
    assert cold.mechanical.replay()["status"] == "PASS"
