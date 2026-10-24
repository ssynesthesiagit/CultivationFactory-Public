"""MGR-T15 close Swift Movement, F14 review finding 1.

Lightning God flight (Body + Wings + Sovereign) reads a walking-derived Fly Speed when live walking Speed
exceeds the printed 60-ft floor. That grant already holds the all-Speeds bonus, so it must declare that
provenance; otherwise Swift Movement's +10 is counted twice (walking 90 -> Fly 100).
"""
from combat import movement_speeds
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine  # noqa: F401  (engine built by test_riders_lane1._engine)
from tests import test_auto_athletics as A
from tests import test_riders_lane1 as R
from tests import test_auto_lane1 as L

SWIFT = A.SWIFT
FOCUS = A.FOCUS
WINGS, GOD_BODY, SOVEREIGN = R.WINGS, R.GOD_BODY, R.SOVEREIGN
ME = L.ME


def _lightning_engine(*, walking_ft, focus):
    talents = [SWIFT, WINGS, GOD_BODY, SOVEREIGN]
    sphere = L._mechanics()[WINGS]["sphere_id"]
    sheet = A._sheet(talents, cl=15, walking_ft=walking_ft, extra_spheres=[sphere])
    engine = R._engine(compile_character(sheet, actor_id=ME), {})
    me = engine.state.actors[ME]
    me.resources[FOCUS] = focus
    R._use_on_self(engine, "Lightning-God Body")
    R._use_on_self(engine, "Lightning Sovereign Incarnation")
    me.resources[FOCUS] = focus  # the states above must not change the Focus under test
    return engine, me


def test_walking_derived_lightning_flight_does_not_count_swift_twice_when_walking_exceeds_the_printed_floor():
    engine, me = _lightning_engine(walking_ft=80, focus=1)
    walk = movement_speeds.speed(engine, me, 'walk')
    assert walk > 60, 'the case under test must be walking-derived (live walking Speed above the 60-ft floor)'
    assert movement_speeds.speed(engine, me, 'fly') == walk


def test_printed_sixty_foot_flight_still_gets_the_all_speeds_bonus_once_when_walking_is_below_it():
    engine, me = _lightning_engine(walking_ft=30, focus=1)
    walk = movement_speeds.speed(engine, me, 'walk')
    assert walk < 60, 'the printed floor must win here'
    assert movement_speeds.speed(engine, me, 'fly') == 70  # 60 printed + Swift's 10 once while Focus is held


def test_walking_derived_lightning_flight_without_focus_adds_no_swift_bonus():
    engine, me = _lightning_engine(walking_ft=80, focus=0)
    assert movement_speeds.speed(engine, me, 'fly') == movement_speeds.speed(engine, me, 'walk')
