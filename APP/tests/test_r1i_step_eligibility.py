"""The shared step allowance uses the same effective Speed as ordinary movement."""
import pytest

from combat.ext.movement_steps import immediate_step_budget
from tests.test_riders_lane1 import _claw_engine, ME


@pytest.mark.parametrize("condition", ["condition:core.grappled", "condition:typed.grappled",
    "condition:typed.restrained", "condition:typed.paralyzed", "condition:typed.pinned"])
def test_immediate_step_does_not_override_immobilization(condition):
    engine = _claw_engine()
    owner = engine.state.actors[ME]
    engine._apply_condition(owner, condition, "test:immobilized", ME, expires_on="UNTIL_REMOVED")
    assert immediate_step_budget(engine, owner, 5) == 0


@pytest.mark.parametrize("speed,expected", [(0, 0), (3, 3), (30, 5)])
def test_immediate_step_caps_allowance_by_effective_speed(speed, expected):
    engine = _claw_engine()
    owner = engine.state.actors[ME]
    engine._add_modifier(owner, "test:speed", "speed_ft", "ADD", speed - owner.speed_ft,
                         "self", expires_on="UNTIL_REMOVED")
    assert immediate_step_budget(engine, owner, 5) == expected
