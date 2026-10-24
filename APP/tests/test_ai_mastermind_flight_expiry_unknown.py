"""AIUP2F5 regressions: an expired flight-annotation deadline is unknown, never a forced landing.

Fakes only: the offline client replaces every model call; the fight is synthetic.
"""
from combat import flight_decision, menu_rank
from combat.falling import supported
from combat.gate4_controller import _flight_descent
from combat.target_knowledge import actors_for
from tests.ai_tiers_native_support import OWNER, context_for, fight
from tests.test_ai_mastermind import Offline


def _airborne_flier(tmp_path, monkeypatch):
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               flight=True, foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    engine = session.engine
    actor = engine.state.actors[OWNER]
    assert not supported(engine, actor), "fixture must be airborne for the flight forecast to matter"
    return engine, actor, context


def test_expired_deadline_does_not_end_flight_or_force_descent(tmp_path, monkeypatch):
    engine, actor, context = _airborne_flier(tmp_path, monkeypatch)
    rows = flight_decision.annotate(engine, context.legal_candidates, OWNER,
                                    actors_for(engine, actor), deadline=0)
    moves = [c for c in rows if c.kind == "MOVE"]
    assert moves
    for candidate in moves:
        facts = candidate.metadata["flight_tactics"]
        assert facts["flight_ending"] is False
        assert not _flight_descent(candidate)


def test_skipped_refinement_marks_whole_row_unevaluated(tmp_path, monkeypatch):
    engine, actor, context = _airborne_flier(tmp_path, monkeypatch)

    def measured_safe(view, actor, moves, *, deadline=None):
        # Route safety measured before the deadline says "no fall, no block".
        return {c.candidate_id: {"evaluated": True, "fall_required": False,
                                 "path_requires_fall": False, "path_blocked": False}
                for c in moves}
    monkeypatch.setattr(flight_decision, "_movement_safety", measured_safe)
    rows = flight_decision.annotate(engine, context.legal_candidates, OWNER,
                                    actors_for(engine, actor), deadline=0)
    moves = [c for c in rows if c.kind == "MOVE"]
    assert moves
    for candidate in moves:
        destination = candidate.metadata["flight_tactics"]["destination"]
        assert destination["evaluated"] is False
