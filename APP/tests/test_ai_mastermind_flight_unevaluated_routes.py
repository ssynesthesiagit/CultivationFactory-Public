"""Regressions: an expired flight annotation is unevaluated, never a proven fall or veto."""
from combat.work_budget import WorkBudget
from combat import flight_decision
from combat.gate4_controller import _UNEVALUATED_PRICE, _flight_move_value, _unsafe_flight_route
from combat.gate2_runtime_models import CandidateKind, LegalCandidate, Position
from tests.ai_tiers_native_support import OWNER, fight


def _move(cid, facts, *, cost=10):
    return LegalCandidate(candidate_id=cid, decision_id="d", state_version=1, actor_id="a",
                          source_definition_id="test:move", display_name="Move",
                          kind=CandidateKind.MOVE, movement_cost_ft=cost,
                          destination=Position(x=1, y=0, z=1),
                          metadata={"flight_tactics": facts})


UNEVALUATED = {"evaluated": False, "fall_required": False, "path_requires_fall": False, "path_blocked": False}
CURRENT = {"altitude_ft": 10, "supported": False, "attack_target_ids": []}


def test_unevaluated_move_is_not_an_unsafe_route():
    c = _move("m", {"current": CURRENT, "flight_ending": False, "destination": dict(UNEVALUATED)})
    assert not _unsafe_flight_route(c)
    # Priced as unevaluated (_UNEVALUATED_PRICE), not as the -3000 proven-fall veto.
    assert _flight_move_value(c) == _UNEVALUATED_PRICE


def test_unevaluated_move_never_ends_flight_or_gets_descent_priority():
    from combat.gate4_controller import _flight_descent
    c = _move("m", {"current": CURRENT, "flight_ending": True, "destination": dict(UNEVALUATED)})
    assert not _flight_descent(c)
    assert _flight_move_value(c) > -3000


def test_route_safety_exhausted_rows_are_unevaluated_not_lethal(tmp_path, monkeypatch):
    # Real native engine: an exhausted budget checks no square, so no fall or block verdict.
    def forbidden(*args):
        raise AssertionError("an exhausted budget must not query a square")
    monkeypatch.setattr(flight_decision, "_position_safety", forbidden)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               flight=True, foe_at={"x": 3, "y": 7})
    engine = session.engine
    actor = engine.state.actors[OWNER]
    p, q = Position(x=3, y=6, z=10), Position(x=4, y=6, z=10)
    rows = flight_decision._route_safety(engine, actor, [("r", q, (p, q), True)], budget=WorkBudget(0))
    assert rows["r"]["evaluated"] is False
    assert not any(rows["r"][k] for k in ("fall_required", "path_requires_fall", "path_blocked"))


def _measured(cid, *, cost=10):
    facts = {"current": CURRENT, "flight_ending": False,
             "destination": {"evaluated": True, "fall_required": False, "path_requires_fall": False,
                             "path_blocked": False, "supported": False, "altitude_ft": 10,
                             "attack_target_ids": [], "melee_threat_ids": [], "nearest_hostile_ft": None}}
    return _move(cid, facts, cost=cost)


def test_unmeasured_route_never_outranks_a_measured_route_without_progress():
    # Regression: the unmeasured price used to be -40, above a measured no-progress move (-42),
    # so the controller could prefer a route it never checked for falls.
    unmeasured = _move("u", {"current": CURRENT, "flight_ending": False, "destination": dict(UNEVALUATED)})
    measured = _measured("m")
    assert _flight_move_value(unmeasured) < _flight_move_value(measured)


def test_unmeasured_route_stays_choosable_and_is_not_vetoed():
    # The price is a ranking, not a veto: the native menu keeps every legal option.
    unmeasured = _move("u", {"current": CURRENT, "flight_ending": False, "destination": dict(UNEVALUATED)})
    assert not _unsafe_flight_route(unmeasured)
    assert _flight_move_value(unmeasured) > -3000
