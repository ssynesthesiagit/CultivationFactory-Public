"""The table header's decision identity is the one decision() and every legal row carry (AISTEPONCE1).

decision(table_header=True) reads (active_actor_id, decision_id, state_version, control_mode) from the engine without
enumerating. Runner prepare and auto_step bind their commands to it, so a stale write must never pass: the header must
name exactly the decision the full context (and its candidates) would name, in every phase of a turn.
"""
import pytest

from combat.gate2_runtime_models import TerminalResult
from tests.test_lock18_neutral_phases import AN, BAI, fight
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import HOLD, on_hold

IDENTITY = ("active_actor_id", "decision_id", "state_version")


def _identity(doc):
    return tuple(doc["context"][key] for key in IDENTITY) + (doc["control_mode"],)


def _same_identity(service, mid, session):
    engine = session.engine
    actor = engine.deciding_actor()
    rows = engine.legal_candidates()
    assert rows and {(row.actor_id, row.decision_id) for row in rows} == {(actor.entity_id, engine.decision_id(actor))}
    full = service.decision(mid, session=session)
    header = service.decision(mid, session=session, table_header=True)
    assert _identity(header) == _identity(full)
    assert full["context"]["active_actor_id"] == actor.entity_id
    return header


def test_normal_turn_header_is_the_decision(tmp_path):
    service, _, mid = fight(tmp_path)
    service.set_controller_mode(mid, actor_id=BAI, controller_mode="LOCAL_AUTO")
    header = _same_identity(service, mid, service._load_session(mid))
    assert "legal_candidates" not in header["context"], "an ordinary AI turn's header must not enumerate"


def test_inactive_turn_header_is_the_decision(tmp_path):
    service, _, mid = fight(tmp_path)
    service.set_controller_mode(mid, actor_id=BAI, controller_mode="LOCAL_AUTO")
    session = service._load_session(mid)
    engine = session.engine
    actor = engine.state.actors[BAI]
    engine._apply_condition(actor, "condition:test.stunned", "test:aisteponce1", BAI, expires_on="UNTIL_REMOVED",
                            data={"rule": {"no_actions": True}})
    assert {str(row.kind) for row in engine.legal_candidates()} <= {"END_TURN", "CandidateKind.END_TURN"}
    _same_identity(service, mid, session)


def test_setup_task_keeps_the_full_context_and_its_identity(monkeypatch, tmp_path):
    install(monkeypatch, "fight_setup_tasks",
            lambda engine: [{"actor_id": AN, "source_id": engine.state.actors[AN].action_ids[0]}])
    install(monkeypatch, "fight_setup", lambda engine, actor, source, intent: True)
    service, _, mid = fight(tmp_path)
    service.set_controller_mode(mid, actor_id=BAI, controller_mode="LOCAL_AUTO")
    session = service._load_session(mid)
    assert session.engine.state.setup_tasks
    assert "legal_candidates" in _same_identity(service, mid, session)["context"]


def test_pending_reaction_window_keeps_the_full_context_and_its_identity(monkeypatch, tmp_path):
    def pending(engine):
        actor, target = engine.state.actors[BAI], engine.state.actors[AN]
        engine._gain_resource(actor, "resource:bai_meizhen.moon_sea_radiance", 1, "test:followup")
        engine._open_follow_up_window(actor, target, "test:followup", engine._active_intent,
                                      ["action:bai_meizhen.moon_disc_descent"])
    on_hold(monkeypatch, pending)
    service, table, mid = fight(tmp_path)
    service.set_controller_mode(mid, actor_id=BAI, controller_mode="MANUAL")
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    service.set_controller_mode(mid, actor_id=BAI, controller_mode="LOCAL_AUTO")
    session = service._load_session(mid)
    assert session.engine.state.pending_resolution is not None
    assert "legal_candidates" in _same_identity(service, mid, session)["context"]


def test_terminal_raises_for_both(tmp_path):
    service, _, mid = fight(tmp_path)
    session = service._load_session(mid)
    session.engine.state.terminal_result = TerminalResult(kind="VICTORY", reason="test",
                                                          event_sequence=session.engine.state.event_sequence)
    assert session.engine.deciding_actor() is None
    for table_header in (False, True):
        with pytest.raises(Exception, match="no further decision context"):
            service.decision(mid, session=session, table_header=table_header)
