"""Wind-Body Step is spent by the first actual difficult-climb roll.

Exercise native movement intents and real check dispatch, including a failed
attempt and Advantage cancelled by Disadvantage. No live services are used.
"""
import pytest

from combat import roof_movement
from combat.ext.foundations1 import WIND_STEP
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_roof_movement import climb_intent, condition, engine_at_wall


@pytest.mark.parametrize("bonus,success", [(100, True), (-100, False)])
@pytest.mark.parametrize("disadvantage", [False, True])
def test_first_difficult_climb_spends_wind_body_step(bonus, success, disadvantage):
    engine, actor = engine_at_wall(climb_check="slippery", engine_type=Gate4ControllerEngine)
    actor.skills = {"Athletics": bonus}
    # The fixture holds a benefit already granted by Momentum Step. Its native
    # grant, ownership, cost and expiry are covered by test_a2_r11_foundations.
    condition(actor, WIND_STEP, expires_on="END_OF_CURRENT_TURN")
    if disadvantage:
        condition(actor, "condition:typed.test_climb_disadvantage",
                  data={"rule": {"check_mode": {"Athletics": "DISADVANTAGE"}}})
    start_turn = (engine.state.round_number, engine.state.current_actor_id)
    destination = actor.position.model_copy(update={"z": 1})
    assert roof_movement.needs_check(engine, actor, actor.position, destination)
    # Read-only mode previews must not spend the next-check benefit.
    roof_movement.profile(engine, actor)
    assert any(c.condition_id == WIND_STEP for c in actor.conditions.values())

    engine.execute_intent(climb_intent(engine, actor))
    first = next(e for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED")
    assert first.payload["actor"]["mode"] == ("NORMAL" if disadvantage else "ADVANTAGE")
    assert first.payload["success"] is success
    assert not any(c.condition_id == WIND_STEP for c in actor.conditions.values())
    assert first.payload["skill"] == first.payload["check"] == "Athletics"
    assert first.payload["ability"] == "STR"

    engine.execute_intent(climb_intent(engine, actor))
    second = next(e for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED")
    assert second is not first
    assert second.payload["actor"]["mode"] == ("DISADVANTAGE" if disadvantage else "NORMAL")
    assert (engine.state.round_number, engine.state.current_actor_id) == start_turn
