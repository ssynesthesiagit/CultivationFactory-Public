"""AIWALK1F2 regressions: walk forecast ordering must not override native flight order.

Review finding 1: walk_attack_order returned a full cost/gain permutation for every
decision with forecast metadata, which bypassed the controller's flight branch.
"""
from combat import ext
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from tests.h1_support import ME
from tests.test_aiwalk1 import walking_duel


def _ai_context(engine, policy):
    ext._load()
    return build_decision_context(engine, policy, for_ai=True)


def test_flight_decision_leaves_movement_order_to_flight_branch():
    """Without the fix the walk permutation was returned here, so the flight guard never ran."""
    engine, policy = walking_duel()
    context = _ai_context(engine, policy)
    moves = tuple(c for c in context.legal_candidates if c.kind == 'MOVE')
    assert any(c.metadata.get('walk_attack') for c in moves)
    flying = tuple(c.model_copy(update={'metadata': {**c.metadata,
        'flight_tactics': {'destination': {}, 'current': {}}}}) for c in context.legal_candidates)
    flight_context = context.model_copy(update={'legal_candidates': flying})
    flight_moves = tuple(c for c in flying if c.kind == 'MOVE')
    assert ext.run_strict('ai_movement_order', flight_context, flight_moves) == []


def test_slice_path_leaves_flight_movement_order_to_flight_branch(monkeypatch):
    """AIWALK1F3 optional 2: CF_COMBAT_AI_SLICES_1_2=1 must not replace flight order either.

    Without the guard the slice ranking returned a personal-knowledge permutation for
    a flight decision, so the flight branch's score-before-truncate never ran.
    """
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    engine, policy = walking_duel()
    context = _ai_context(engine, policy)
    assert context.own_knowledge is not None, 'slice path must be reachable for this regression'
    flying = tuple(c.model_copy(update={'metadata': {**c.metadata,
        'flight_tactics': {'destination': {}, 'current': {}}}}) for c in context.legal_candidates)
    flight_context = context.model_copy(update={'legal_candidates': flying})
    flight_moves = tuple(c for c in flying if c.kind == 'MOVE')
    assert ext.run_strict('ai_movement_order', flight_context, flight_moves) == []


def test_walk_order_moves_only_forecast_rows_and_keeps_native_order_for_rest():
    engine, policy = walking_duel()
    context = _ai_context(engine, policy)
    moves = tuple(c for c in context.legal_candidates if c.kind == 'MOVE')
    # Present rows in reverse id order so a sort-everything implementation is visible.
    rows = tuple(sorted(moves, key=lambda c: c.candidate_id, reverse=True))
    assert len(rows) >= 3
    order = ext.run_strict('ai_movement_order', context, rows)[0]
    assert set(order) == {c.candidate_id for c in rows} and len(order) == len(rows)
    forecast = [c.candidate_id for c in rows if c.metadata.get('walk_attack')]
    rest = [c.candidate_id for c in rows if not c.metadata.get('walk_attack')]
    assert list(order) == forecast + rest
    assert rest == sorted(rest, reverse=True), 'non-forecast rows must keep native order'
