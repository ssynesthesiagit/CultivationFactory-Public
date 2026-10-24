"""MGR-T15 close Swift Movement, F14 review finding 1.

Lightning God flight (God Body + Wings + Sovereign) reads a walking-derived Fly Speed when live walking Speed
reaches or exceeds the printed 60-ft floor. That grant already holds the all-Speeds bonus, so it must declare that
provenance; otherwise Swift Movement's +10 is counted twice (walking 80 + Focus -> Fly 110 instead of 100).
"""
from combat import movement_speeds
from combat.factory_compiler import compile_character
from tests import test_auto_athletics as A
from tests import test_auto_lane1 as L
from tests import test_riders_lane1 as R

ME = L.ME
SWIFT, FOCUS = A.SWIFT, A.FOCUS
SPHERE = "tianxia.sphere.athletics"


def _flight_engine(*, walking_ft, focus):
    """Swift Movement + Lightning God Body + Wings + Sovereign on one sheet; the mantle is used before the Body
    (the Body spends the turn's bonus action the mantle needs), with a fresh turn between."""
    sheet = L._sheet(R.WINGS, cl=15, dc=50)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] += [R.SOVEREIGN, R.GOD_BODY, SWIFT]
    sheet["spheres_and_talents"]["sphere_record_ids"] += [SPHERE]
    bases = [k for k, m in L._mechanics().items() if m.get("sphere_id") == SPHERE and m.get("kind") == "base_ability"]
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] += bases
    sheet["ability_scores_and_statistics"]["speed"]["walking_ft"] = walking_ft
    engine = R._engine(compile_character(sheet, actor_id=ME), {})
    actor = engine.state.actors[ME]
    actor.resources[FOCUS] = focus
    R._use_on_self(engine, "Lightning Sovereign Incarnation")
    L._ready(engine)
    R._use_on_self(engine, "Lightning-God Body")
    actor.resources[FOCUS] = focus
    return engine, actor


def test_walking_derived_lightning_flight_counts_swift_once_when_walking_exceeds_the_printed_floor():
    """Walking 80 + Swift 10 + God Body 10 = live walking 100 (above the 60-ft grant). Fly Speed matches it;
    the grant must not add Swift again (that gave 110)."""
    engine, actor = _flight_engine(walking_ft=80, focus=1)
    walk = movement_speeds.speed(engine, actor, "walk")
    assert walk == 100
    assert movement_speeds.speed(engine, actor, "fly") == walk


def test_printed_sixty_foot_lightning_flight_adds_swift_once_when_walking_is_below_the_floor():
    """Walking 50 with Focus: the printed 60-ft grant wins and gets Swift's +10 once, so Fly is 70."""
    engine, actor = _flight_engine(walking_ft=30, focus=1)
    assert movement_speeds.speed(engine, actor, "walk") == 50
    assert movement_speeds.speed(engine, actor, "fly") == 70


def test_lightning_flight_at_the_printed_floor_counts_swift_once():
    """Walking 40 + God Body 10 + Swift 10 = live walking exactly 60, the printed floor. At a tie the walking
    total is the source (Wings: Fly equal to walking Speed), so Fly is 60 and Swift is not added again (not 70)."""
    engine, actor = _flight_engine(walking_ft=40, focus=1)
    walk = movement_speeds.speed(engine, actor, "walk")
    assert walk == 60
    assert movement_speeds.speed(engine, actor, "fly") == walk


def test_walking_derived_lightning_flight_without_focus_adds_no_swift_bonus():
    """Without Focus Swift is off: Fly stays at the live walking 90 (80 + God Body 10)."""
    engine, actor = _flight_engine(walking_ft=80, focus=0)
    assert movement_speeds.speed(engine, actor, "walk") == 90
    assert movement_speeds.speed(engine, actor, "fly") == 90
