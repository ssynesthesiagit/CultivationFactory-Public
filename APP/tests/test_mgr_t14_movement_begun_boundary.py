"""MOVEMENT_BEGUN is observed only after the first step is validated and affordable."""
from combat.gate2_runtime_models import Position
from combat.movement_steps import checkpoint
from tests.worker2_support import fixture, OWNER


def test_route_attempt_does_not_emit_movement_begun_before_first_step_validation(tmp_path, monkeypatch):
    combat, _, mid = fixture(tmp_path, [])
    engine = combat._load_session(mid).engine
    mover = engine.state.actors[OWNER]
    previous = mover.position
    nxt = Position(x=previous.x + 1, y=previous.y)
    calls = []

    # An invalid first step (blocked or over budget) exits after this route
    # checkpoint and before movement_attempt; it must not start preparations.
    monkeypatch.setattr('combat.activity_phases.begin',
                        lambda *args, **kwargs: calls.append((args, kwargs)) or True)
    checkpoint(engine, mover, previous, nxt, None, travelled_ft=0, remaining_ft=5,
               point='movement_route_attempt', destination=nxt, allowance_ft=0, mode='walk')
    assert calls == []

    # Once the caller has established that the first step is legal and paid
    # for, the normal pre-entry checkpoint publishes the real beginning.
    checkpoint(engine, mover, previous, nxt, None, travelled_ft=0, remaining_ft=0,
               point='movement_attempt', destination=nxt, allowance_ft=5, mode='walk')
    assert len(calls) == 1
    assert calls[0][0][2] == 'MOVEMENT_BEGUN'
