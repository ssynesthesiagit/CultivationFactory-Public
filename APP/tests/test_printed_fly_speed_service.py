"""Printed Fly Speed and Hover, held through a real table cast and cold reload.

The engine-level cast (test_printed_fly_speed_typed.py) drives a single
self-flight candidate straight through the engine. These rows print a
delivery the engine cannot cast as one self candidate: an area whose
flight reads "allies" (Festival, Garden of Infinite Blossoms), and a
storm that also reads a saving throw and needs a saber-family weapon
(Saber Tempest Sovereign). They are cast through the real CombatService
and TabletopService and checked after a cold reload of the saved fight.
Primordial Dust is the plain self-flight subpath feature cast the same
way. Wind Walk (an out-of-combat ritual) and Calamity Tempering (a
passive charge rider) are checked on the typed record instead.
"""
import pytest

from combat.flight import profile
from tests.worker2_support import OWNER, ALLY, candidate, fixture, reload, settle


def _team_flight(engine, fly, hover):
    """Any combatant on the caster's team holding the printed flight."""
    for actor in engine.state.actors.values():
        if actor.team_id != engine.state.actors[OWNER].team_id:
            continue
        if profile(engine, actor).speed_ft == fly and profile(engine, actor).hover is hover:
            return actor
    return None


@pytest.mark.parametrize("key,cl,name,fly,hover,kit", [
    # (typed key, cl, cast name, printed Fly Speed, printed Hover, weapon kit)
    ("tianxia.subpath.qi.dust_cultivator.feature.primordial_dust", 18, "Primordial Dust", 40, True, None),
    ("tianxia.subpath.qi.kite_cultivator.feature.festival_of_the_heavenly_sky", 18, "Festival of the Heavenly Sky", 30, True, None),
    ("TAL_FLOWERS_GARDEN_OF_INFINITE_BLOSSOMS", 15, "Garden of Infinite Blossoms", 30, False, None),
], ids=["Primordial Dust", "Festival of the Heavenly Sky", "Garden of Infinite Blossoms"])
def test_printed_fly_speed_survives_a_table_cast_and_reload(tmp_path, key, cl, name, fly, hover, kit):
    combat, table, mid = fixture(tmp_path, [key], cl=cl, owner_speed=30, owner_kit=kit)
    settle(table, mid, candidate(combat, mid, name).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 30
    # A self grant lands on the caster; an "allies" grant lands on a teammate.
    if _team_flight(engine, fly, hover) is None:
        holder = "owner" if profile(engine, engine.state.actors[OWNER]).speed_ft == fly else "ally"
        raise AssertionError(f"no {holder} holds Fly Speed {fly} / Hover {hover} after casting {name}")
