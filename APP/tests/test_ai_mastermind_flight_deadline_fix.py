"""Regressions: an expired flight annotation is unevaluated, never a proven fall or veto."""
from types import SimpleNamespace as NS

from combat import flight_decision
from combat.gate4_controller import _flight_move_value, _unsafe_flight_route
from combat.gate2_runtime_models import CandidateKind, LegalCandidate, Position


def _move(cid, facts, *, cost=10):
    return LegalCandidate(candidate_id=cid, decision_id="d", actor_id="a", kind=CandidateKind.MOVE,
                          movement_cost_ft=cost, destination=Position(x=1, y=0, z=1),
                          metadata={"flight_tactics": facts})


UNEVALUATED = {"evaluated": False, "fall_required": False, "path_requires_fall": False, "path_blocked": False}
CURRENT = {"altitude_ft": 10, "supported": False, "attack_target_ids": []}


def test_unevaluated_move_is_not_an_unsafe_route():
    c = _move("m", {"current": CURRENT, "flight_ending": False, "destination": dict(UNEVALUATED)})
    assert not _unsafe_flight_route(c)
    # Priced as unevaluated (-40), not as the -3000 proven-fall veto.
    assert _flight_move_value(c) == -40


def test_unevaluated_move_never_ends_flight_or_gets_descent_priority():
    from combat.gate4_controller import _flight_descent
    c = _move("m", {"current": CURRENT, "flight_ending": True, "destination": dict(UNEVALUATED)})
    assert not _flight_descent(c)
    assert _flight_move_value(c) > -3000


def test_route_safety_deadline_rows_are_unevaluated_not_lethal(monkeypatch):
    monkeypatch.setattr(flight_decision, "_position_safety", lambda *a: (_ for _ in ()).throw(AssertionError))
    p, q = Position(x=0, y=0, z=1), Position(x=1, y=0, z=1)
    import combat.candidate_knowledge as ck
    monkeypatch.setattr(ck, "perceived_ids", lambda _: frozenset())
    rows = flight_decision._route_safety(NS(), NS(), [("r", q, (p, q), True)], deadline=0)
    assert rows["r"]["evaluated"] is False
    assert not any(rows["r"][k] for k in ("fall_required", "path_requires_fall", "path_blocked"))
