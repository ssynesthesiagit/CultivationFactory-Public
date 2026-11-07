"""Printed Fly Speed and Hover are granted as typed flight, never as walking Speed.

Each row prints a Fly Speed (and, where the text says so, Hover) for a stated
duration. Before the typed-data fix these rows were typed as a walking "speed"
or "movement" effect, so the Speed number rose and no flight existed. Each case
casts the ability through the engine and checks the flight it grants, the Hover
it prints, and that walking Speed is unchanged. World Beneath the Black Sea also
prints a Swim Speed; this table has no swim-speed system, so the swim grant is
recorded on the condition for the sheet and the Game Master, and the test checks
it survived.
"""
import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.flight import profile
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50):
    sphere = AUTH[key]["sphere_id"]
    bases = [k for k, v in AUTH.items() if v.get("sphere_id") == sphere and v.get("kind") == "base_ability"]
    sheet = {**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}],
             "identity": {**SHEET["identity"], "cultivation_level": cl},
             "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc,
                                                       "technique_attack_bonus": 40, "primary_resource": {"name": "Qi", "maximum": 100}},
             "spheres_and_talents": {"sphere_record_ids": [sphere],
                                     "learned_talent_record_ids": list(dict.fromkeys([*bases, key]))}}
    return compile_character(sheet, actor_id=ME)


def _cast(engine, name):
    wanted = name.lower()
    found = [c for c in engine.legal_candidates() if c.display_name.lower().startswith(wanted)]
    assert found, (name, sorted({c.display_name for c in engine.legal_candidates()}))
    c = found[0]
    engine.execute_intent(ActionIntent(intent_id="flight", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=ME, target_ids=c.target_ids,
                                       destination=c.destination))


# (typed key, cl, cast name, printed Fly Speed, printed Hover)
# Self flight grants the engine can cast as one candidate. The area grants that
# read "allies" (Festival, Garden), the storm that also reads a saving throw and
# needs a saber-family weapon (Saber Tempest), the out-of-combat ritual (Wind Walk)
# and the passive charge rider (Calamity Tempering) are cast through the real table
# in test_printed_fly_speed_service.py or checked on the typed record below.
SELF_ROWS = [
    ("TAL_SCOUNDREL_SOVEREIGN_OF_TEN_THOUSAND_EMPTY_SLEEVES", 20, "Sovereign of Ten Thousand Empty Sleeves", 40, True),
    ("tianxia.talent.blood.scarlet_mist_form", 15, "Scarlet Mist Form", 30, True),
    ("tianxia.subpath.qi.black_sea_leviathan_womb.feature.world_beneath_the_black_sea", 18, "World Beneath the Black Sea", 60, True),
    ("tianxia.subpath.qi.dust_cultivator.feature.primordial_dust", 18, "Primordial Dust", 40, True),
    ("tianxia.subpath.qi.heaven_thunder_storm_soul.feature.living_heavenly_tribulation", 18, "Living Heavenly Tribulation", 60, True),
    ("tianxia.subpath.qi.kite_cultivator.feature.ride_the_kite", 14, "Ride the Kite", 40, False),
    ("tianxia.subpath.qi.paper_cultivator.feature.folded_arsenal", 6, "Folded Arsenal", 20, False),
    ("tianxia.subpath.qi.storm_soul_cultivator.feature.eye_of_the_storm", 18, "Eye of the Storm", 60, True),
    ("tianxia.subpath.qi.storm_soul_cultivator.feature.zephyr_s_step", 14, "Zephyr", 50, True),
    ("tianxia.subpath.qi.void_touched_cultivator.feature.law_of_nonexistence", 18, "Law of Nonexistence", 60, True),
    ("tianxia.subpath.qi.yin_yang_cultivator.feature.ultimate_unity", 18, "Ultimate Unity", 40, True),
    ("TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION", 15, "Spear-Sovereign Incarnation", 40, True),
    ("tianxia.subpath.qi.saber_wind_cultivator.feature.saber_tempest_sovereign", 18, "Saber Tempest Sovereign", 60, True),
]


@pytest.mark.parametrize("key,cl,name,fly,hover", SELF_ROWS, ids=[row[2] for row in SELF_ROWS])
def test_printed_fly_speed_is_flight_and_walking_speed_is_unchanged(key, cl, name, fly, hover):
    engine = _engine(copy.deepcopy(_compiled(key, cl)), foe_at=(4, 6))
    me = engine.state.actors[ME]
    walking = engine._effective_speed(me)
    # A delivery that can fell the sparring foe (Saber Tempest's save)
    # would end the match before the caster's own flight grant resolves,
    # so the foe stands for the cast and the grant is observed directly.
    foe = engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 100000
    _cast(engine, name)
    assert engine._effective_speed(me) == walking
    flight = profile(engine, me)
    assert flight.speed_ft == fly and flight.hover is hover


def test_world_beneath_the_black_sea_records_the_printed_swim_speed():
    engine = _engine(copy.deepcopy(_compiled(
        "tianxia.subpath.qi.black_sea_leviathan_womb.feature.world_beneath_the_black_sea", 18)), foe_at=(4, 6))
    me = engine.state.actors[ME]
    _cast(engine, "World Beneath the Black Sea")
    swim = [c for c in me.conditions.values() if c.condition_id.endswith("black_sea_flight")]
    assert swim and swim[0].data.get("swim_speed_ft") == 60
    assert swim[0].data.get("fly_speed_ft") == 60 and swim[0].data.get("flight_hover") == 1


# Rows the engine cannot cast as one combat candidate: Wind Walk is an
# out-of-combat ritual and Calamity Tempering is a passive whose Fly Speed
# rides a spent Storm charge. The typed record still has to carry the printed
# flight as a timed condition -- and no walking "speed" effect reading the
# same printed line -- or the grant would again be walking Speed.
DATA_ROWS = [
    ("tianxia.subpath.qi.cloud_walker.feature.wind_walk", "cloud_walker_wind_walk_flight", 40, True),
    ("tianxia.subpath.qi.tribulation_vessel.feature.calamity_tempering",
     "tribulation_vessel_calamity_tempering_flight", 30, False),
]


@pytest.mark.parametrize("key,condition,fly,hover", DATA_ROWS,
                         ids=[key.split(".")[-1] for key, *_ in DATA_ROWS])
def test_ritual_and_passive_fly_speed_is_typed_as_a_flight_condition(key, condition, fly, hover):
    effects = AUTH[key]["effects"]
    flights = [e for e in effects if e.get("type") == "condition" and e.get("condition") == condition]
    assert flights, (key, [e.get("type") for e in effects])
    data = flights[0]["condition_data"]
    assert data["fly_speed_ft"] == fly and bool(data.get("flight_hover")) is hover
    # No row may still read the printed Fly Speed as a walking Speed.
    assert not [e for e in effects if e.get("type") == "speed"
                and "fly" in str(e.get("evidence", "")).lower()]
