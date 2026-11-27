"""Behaviour pin for Swift Movement (TAL_ATHLETICS_SWIFT_MOVEMENT).

Swift Movement adds 10 feet to Speed while Martial Focus is held; walking reads it directly and every other movement Speed gets it once through the all-Speeds bonus. The printed clause and its source hash are not quoted anywhere in the public tests.
"""
from combat.flight import profile
from tests.test_auto_athletics import FOCUS, SWIFT, _engine, _me


def test_swift_movement_adds_ten_feet_only_while_focus_is_held():
    engine = _engine([SWIFT], speed_focus=1)
    held = engine._effective_speed(_me(engine))
    _me(engine).resources[FOCUS] = 0
    spent = engine._effective_speed(_me(engine))
    assert held - spent == 10


def test_swift_movement_adds_ten_feet_once_to_a_non_walking_speed_too():
    engine = _engine([SWIFT], speed_focus=1)
    _me(engine).fly_speed_ft = 20
    walk_held, fly_held = engine._effective_speed(_me(engine)), profile(engine, _me(engine)).speed_ft
    assert fly_held == 30, "a 20-foot Fly Speed gains the 10 feet while Focus is held"
    _me(engine).resources[FOCUS] = 0
    assert walk_held - engine._effective_speed(_me(engine)) == 10
    assert fly_held - profile(engine, _me(engine)).speed_ft == 10
