"""Movement bookkeeping belongs only to Patient Mountain owners."""
from combat.ext import earth_responses as earth
from tests.test_riders_lane9 import _earth_fight, ME


def test_nonowner_movement_leaves_flags_unchanged():
    engine = _earth_fight([])
    actor = engine.state.actors[ME]
    before = dict(actor.turn_flags)
    earth.earth_events(engine, "MOVEMENT_COMMITTED", {
        "actor_id": ME, "payload": {"path": [{"x": x, "y": 6} for x in range(3, 8)]},
    })
    assert actor.turn_flags == before


def test_patient_mountain_tracks_before_activation_and_shrinks_after_half_speed():
    engine = _earth_fight(["INCARNATION_OF_THE_PATIENT_MOUNTAIN"])
    actor = engine.state.actors[ME]
    earth.earth_events(engine, "MOVEMENT_COMMITTED", {
        "actor_id": ME, "payload": {"path": [{"x": x, "y": 6} for x in range(3, 8)]},
    })
    assert actor.turn_flags["earth_moved_ft"] == 20
    assert actor.turn_flags["earth_moved_turn"] == actor.turns_started
    engine._apply_condition(actor, earth.INCARNATION, "test", ME, expires_on="UNTIL_REMOVED")
    assert earth.foundation_cells(engine, actor) == earth._cells_of(engine, actor)
    actor.turns_started += 1
    assert len(earth.foundation_cells(engine, actor)) > len(earth._cells_of(engine, actor))
