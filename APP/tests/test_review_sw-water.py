"""Sphere typing review, sweep batch sw-water (2026-09-28): the water, wax and weapons spheres against the owner's printed text.

Each test compiles a character with the corrected ability, runs it through the engine and asserts what the printed text says
happens; every one of them fails on the authority before the review (58231d8).  The corrections, by cause:

* an area that acts on a creature entering or starting its turn in it re-ran the effects of the moment it was made (Tidal Wave,
  Wave Burst, Flowing Current, Waxen City: ``cast_only`` effects are not what a later arrival meets -- combat/factory_compiler.py
  ``_zone_spec``);
* the printed header line was never typed, so an ability was free, reached 5 feet, or ended with the turn (Flood the Battlefield,
  Heaven-Falling Tsunami, Ocean-Sovereign Incarnation, When the Sea Forgets the Shore, and 24 wax abilities);
* a number or a subject was mistyped (Water Shield's dice by Cultivation Level, Restorative Waters, Ten Thousand Returning
  Streams, Waxen Shell, Living Wax Form, Adhesive Pool, White Wax Edict, Candle Procession, Guiding Candle, Living Current,
  Molten Snare, Weapon-Breaking Retort).
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

import combat.factory_compiler as factory_compiler
from combat import typed_reactions, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position
from tests.test_auto_support import ME, _engine
from tests.test_gravity_canvas import _cast, _events, _foes_turn, _speed_modifiers
from tests.test_zones import SHEET

FAILS, PASSES = 30, 1  # the foe's saving throw (a d20 + a small modifier) against this DC never / always succeeds
QI = "resource:core.qi"
REVIEW = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/reviewed_final.d/review_sw-water.json"


# ---- helpers ----------------------------------------------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _mechanics(path: str) -> dict:
    return json.loads(Path(path).read_text())["mechanics"]


def _authority() -> dict:
    return _mechanics(str(factory_compiler.TYPED_AUTHORITY))


@lru_cache(maxsize=None)
def _compiled(path: str, sphere: str, talents: tuple, cl: int, dc: int, equipment: str) -> dict:
    mechanics = _mechanics(path)
    sphere_id = "tianxia.sphere." + sphere
    base = [key for key, row in mechanics.items() if row.get("sphere_id") == sphere_id and row["kind"] == "base_ability"]
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    sheet = {**SHEET, "equipment": json.loads(equipment), "identity": {**SHEET["identity"], "cultivation_level": cl}, "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sphere_id], "automatic_sphere_component_record_ids": base,
                                     "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=ME)


def _bundle(sphere: str, talents=(), *, cl: int = 10, dc: int = FAILS, equipment=()) -> dict:
    return copy.deepcopy(_compiled(str(factory_compiler.TYPED_AUTHORITY), sphere, tuple(talents), cl, dc, json.dumps(list(equipment), sort_keys=True)))


def _fight(sphere: str, talents=(), *, foe_at=(4, 6), cl: int = 10, dc: int = FAILS, ally: bool = False, equipment=()):
    """The caster (x=3) and a foe -- or, with ``ally``, a second friendly creature -- ``foe_at``; five feet a square."""
    bundle = _bundle(sphere, talents, cl=cl, dc=dc, equipment=equipment)
    engine = _engine(bundle, foe_at=foe_at)
    if ally:
        engine.state.actors[AN].team_id = engine.state.actors[ME].team_id
    return bundle, engine


def _row(bundle: dict, prefix: str) -> dict:
    return next(row for row in bundle["action_catalog"] if row["display_name"].startswith(prefix))


def _do(engine, name: str, target=None, actor: str = ME) -> None:
    """Use the action called exactly ``name`` (on ``target`` when the candidates differ by target)."""
    candidates = [c for c in engine.legal_candidates() if c.display_name == name and (target is None or tuple(c.target_ids) == (target,))]
    assert candidates, f"{name!r} is not offered: {sorted({c.display_name for c in engine.legal_candidates()})[:12]}"
    candidate = candidates[0]
    engine.execute_intent(ActionIntent(intent_id="do", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _offered(engine, prefix: str) -> bool:
    return any(c.display_name.startswith(prefix) for c in engine.legal_candidates())


def _qi(engine) -> int:
    return engine.state.actors[ME].resources.get(QI, 0)


def _soaked(actor) -> bool:
    return any("mark.soaked" in condition.condition_id for condition in actor.conditions.values())


def _has(actor, name: str) -> bool:
    return any(condition.condition_id == f"condition:typed.{name}" for condition in actor.conditions.values())


def _rolls(engine, since: int, reason: str = "") -> list:
    return [event.payload for event in engine.events[since:] if event.event_type == "DAMAGE_ROLLED" and reason in str(event.payload.get("reason"))]


def _kinds(engine, since: int, *kinds: str) -> list:
    return [event for event in engine.events[since:] if event.event_type in kinds]


# ---- water: an area's cast-time effect is not what the next creature to arrive meets -------------------------------------------


def test_tidal_wave_costs_two_more_and_soaks():
    # "you may spend 2 additional CP to create a wave ... On a failed save, a creature takes 4d8 bludgeoning damage, is pushed 20 feet,
    # falls Prone, and becomes Soaked": the wave was free and its Soaked a line of text.
    _, engine = _fight("water", ["TAL_WATER_TIDAL_WAVE"], foe_at=(9, 6))
    foe, qi = engine.state.actors[AN], _qi(engine)
    _cast(engine, "Shape Current: Flowing Current + Tidal Wave")
    assert qi - _qi(engine) == 3  # Shape Current's 1 CP and the 2 additional CP
    assert foe.current_hp < foe.maximum_hp and _has(foe, "prone") and _soaked(foe)
    _, engine = _fight("water", ["TAL_WATER_TIDAL_WAVE"], foe_at=(9, 6), dc=PASSES)
    _cast(engine, "Shape Current: Flowing Current + Tidal Wave")
    assert _soaked(engine.state.actors[AN]) and not _has(engine.state.actors[AN], "prone")  # "On a successful save ... becomes Soaked"


def test_tidal_wave_breaks_once_not_again_at_the_foes_turn():
    # The wave is the moment it is made; the Current that stays is not a wave that strikes each creature that starts its turn in it.
    _, engine = _fight("water", ["TAL_WATER_TIDAL_WAVE"], foe_at=(9, 6))
    foe = engine.state.actors[AN]
    _cast(engine, "Shape Current: Flowing Current + Tidal Wave")
    after_cast = foe.current_hp
    assert after_cast < foe.maximum_hp
    _foes_turn(engine)
    assert foe.current_hp == after_cast


def test_flowing_current_pushes_when_it_is_made_not_again_at_the_foes_turn():
    # "When you create the Current, choose one creature in the area. It must succeed on a Strength saving throw or be pushed ...":
    # the save was re-run for the first hostile to start its turn there.
    _, engine = _fight("water", foe_at=(7, 6), dc=PASSES)
    _cast(engine, "Shape Current: Flowing Current")
    assert _kinds(engine, 0, "SAVE_ROLLED")
    since = len(engine.events)
    _foes_turn(engine)
    assert not _kinds(engine, since, "SAVE_ROLLED", "MOVEMENT_COMMITTED")


def test_wave_burst_bursts_when_it_is_made_not_again_at_the_foes_turn():
    # "Each creature of your choice in the area must succeed on a Strength saving throw or be pushed 10 feet away from the center
    # and become Soaked": one burst, made with the Current.
    _, engine = _fight("water", ["TAL_WATER_WAVE_BURST"], foe_at=(7, 6), dc=PASSES)
    _cast(engine, "Shape Current: Flowing Current + Wave Burst")
    assert _soaked(engine.state.actors[AN])
    since = len(engine.events)
    _foes_turn(engine)
    assert not _kinds(engine, since, "SAVE_ROLLED", "MOVEMENT_COMMITTED")


def test_whirlpool_prison_costs_two_more():
    # "When you create a Pressure Basin, you may spend 2 additional CP to make it a whirlpool."
    _, engine = _fight("water", ["TAL_WATER_WHIRLPOOL_PRISON"], foe_at=(7, 6))
    qi = _qi(engine)
    _cast(engine, "Shape Current: Pressure Basin + Whirlpool Prison")
    assert qi - _qi(engine) == 3


def test_whirlpool_prison_slows_only_on_a_success():
    # "On a failure, it is Restrained until the start of its next turn and suffers Drowning Pressure. On a success, its Speed is
    # reduced by 10 feet": the Speed reduction was a separate effect that hit both branches.
    _, engine = _fight("water", ["TAL_WATER_WHIRLPOOL_PRISON"], foe_at=(7, 6))
    _cast(engine, "Shape Current: Pressure Basin + Whirlpool Prison")
    _foes_turn(engine)  # the foe starts its turn in the whirlpool and fails
    foe = engine.state.actors[AN]
    assert _has(foe, "restrained")
    assert [value for value, _ in _speed_modifiers(foe)] == [-10]  # the Pressure Basin's own; the whirlpool's applies on a success
    _, engine = _fight("water", ["TAL_WATER_WHIRLPOOL_PRISON"], foe_at=(7, 6), dc=PASSES)
    _cast(engine, "Shape Current: Pressure Basin + Whirlpool Prison")
    _foes_turn(engine)
    foe = engine.state.actors[AN]
    assert not _has(foe, "restrained") and [value for value, _ in _speed_modifiers(foe)] == [-10]


def test_flood_the_battlefield_costs_three_and_floods_the_whole_domain():
    # "you may spend 3 CP as an action to flood it. ... Each makes a Strength saving throw. On a failure, a creature is knocked
    # Prone, moved 30 feet into a legal space, ... On a success, it is moved 10 feet and becomes Soaked."  Range 5, free, and
    # Soaked a condition that no Water talent reads.
    _, engine = _fight("water", ["TAL_WATER_FLOOD_THE_BATTLEFIELD"], foe_at=(9, 6))  # 30 feet away, inside the 60-foot Domain
    engine.grid.qi_hazard.clear()  # Measure the full forced distance on unobstructed ground.
    foe, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Flood the Battlefield")
    assert qi - _qi(engine) == 3
    assert _has(foe, "prone") and foe.position.x == 15  # moved 30 feet
    _, engine = _fight("water", ["TAL_WATER_FLOOD_THE_BATTLEFIELD"], foe_at=(9, 6), dc=PASSES)
    engine.grid.qi_hazard.clear()  # Measure the full forced distance on unobstructed ground.
    _do(engine, "Flood the Battlefield")
    foe = engine.state.actors[AN]
    assert _soaked(foe) and not _has(foe, "prone") and foe.position.x == 11  # moved 10 feet


def test_heaven_falling_tsunami_costs_five_once_per_long_rest_and_soaks():
    # "Cost: 5 CP  Uses: Once per long rest ... falls Prone, becomes Soaked, ..."
    _, engine = _fight("water", ["TAL_WATER_HEAVEN_FALLING_TSUNAMI"], foe_at=(12, 6))
    foe, qi = engine.state.actors[AN], _qi(engine)
    _cast(engine, "Heaven-Falling Tsunami")
    assert qi - _qi(engine) == 5
    assert foe.current_hp < foe.maximum_hp and _has(foe, "prone") and _soaked(foe)
    assert not _offered(engine, "Heaven-Falling Tsunami")


def test_ocean_sovereign_incarnation_costs_five_once_per_long_rest():
    # "Cost: 5 CP  Uses: Once per long rest": the cost was printed text, so the table charged nothing and it could be used again.
    _, engine = _fight("water", ["TAL_WATER_OCEAN_SOVEREIGN_INCARNATION"], foe_at=(9, 6))
    qi = _qi(engine)
    _do(engine, "Ocean-Sovereign Incarnation")
    assert qi - _qi(engine) == 5
    assert not _offered(engine, "Ocean-Sovereign Incarnation")


def test_when_the_sea_forgets_the_shore_costs_eight():
    _, engine = _fight("water", ["TAL_WATER_WHEN_THE_SEA_FORGETS_THE_SHORE"], foe_at=(9, 6))
    qi = _qi(engine)
    _do(engine, "When the Sea Forgets the Shore: The Sea Gives Back")
    assert qi - _qi(engine) == 8


# ---- water: numbers and subjects ----------------------------------------------------------------------------------------------


def test_water_shield_scales_with_cultivation_level_and_moves_nobody(tmp_path):
    # "Reduce the damage by 1d10 + your key ability modifier. At CL 11, 2d10 ... At CL 17, 3d10 ..."; "also move it 10 feet" is
    # the protected creature's move, not a push of the attacker and not free movement for the reactor.
    # Fresh Shield rows resolve actual attack/area packets at final_damage,
    # not the old generic on_damage reducer. Preserve all three CL boundaries
    # and the dry recipient's no-movement rule through real table commits.
    from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload
    from tests.test_auto38_water import prepare
    from tests.test_carry import KIT
    for cl, dice in ((10, "1d10"), (11, "2d10"), (17, "3d10")):
        data = tmp_path / str(cl)
        combat, table, mid = fixture(data, ["TAL_WATER_WATER_SHIELD"], cl=cl,
            foe_position={'x':3,'y':5}, foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}},
            bundle_transform=prepare)
        turn(table, mid, FOE)
        since = len(combat._load_session(mid).engine.events)
        settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id,
               {'choice:needle.water_shield':'use'})
        engine = reload(data, mid)
        expressions = [roll.expression for roll in engine.rolls if roll.reason == "WATER_SHIELD_REDUCTION"]
        assert len(expressions) == 1 and expressions[0].startswith(dice), (cl, expressions)
        assert not _kinds(engine, since, "MOVEMENT_GRANTED", "MOVEMENT_COMMITTED")
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99
        assert not engine.state.actors[OWNER].reaction_available


def test_restorative_waters_heals_more_at_higher_levels():
    # "regains Hit Points equal to 1d8 + your key ability modifier. At CL 11 ... 2d8 ... At CL 17 ... 3d8 ..." (a flat 1d8 before).
    for cl, dice in ((10, "1d8"), (11, "2d8"), (17, "3d8")):
        _, engine = _fight("water", ["TAL_WATER_RESTORATIVE_WATERS"], foe_at=(5, 6), cl=cl, ally=True)
        engine.state.actors[AN].current_hp = 15
        since = len(engine.events)
        _do(engine, "Return the Flow: Move an Ally + Restorative Waters", target=AN)
        rolls = [payload["expression"] for payload in _rolls(engine, since, "HEALING")]
        assert rolls and rolls[0].startswith(dice), (cl, rolls)
        assert engine.state.actors[AN].current_hp > 15


def test_ten_thousand_returning_streams_requires_two_ended_effects_and_moves_nobody():
    # Printed healing requires two ended effects inside Court of the Endless Tide.
    # Moving an ally, without a Domain or ending any effects, never qualifies.
    bundle, engine = _fight("water", ["TAL_WATER_TEN_THOUSAND_RETURNING_STREAMS"], foe_at=(5, 6), ally=True)
    engine.state.actors[AN].current_hp = 15
    since = len(engine.events)
    # The target is selected after choosing a real Water effect, not by the
    # action candidate. Without the Court, no effect can be converted at all.
    _do(engine, "Return the Flow: Move an Ally + Ten Thousand Returning Streams", target=ME)
    healed = [event.payload["offered"] for event in _kinds(engine, since, "HEALING_APPLIED")]
    assert healed == []
    assert not _kinds(engine, since, "MOVEMENT_GRANTED", "MOVEMENT_COMMITTED")


def test_living_current_grants_no_free_movement():
    # "Water Lash can originate from any Basin or Current you created within 60 feet" -- reach, not movement.
    _, engine = _fight("water", ["TAL_WATER_LIVING_CURRENT"], foe_at=(9, 6))
    since = len(engine.events)
    _do(engine, "Water Lash")
    assert not _kinds(engine, since, "MOVEMENT_GRANTED")


# ---- wax: the printed header line -- "Action. Range 60 feet. Cost 2 CP. Duration Concentration, up to 1 minute." -----------------
# The header was never typed for the sphere, so its abilities were free, reached 5 feet, and ended with the turn.


def _focused(engine, since: int = 0) -> bool:
    return bool(_kinds(engine, since, "CONCENTRATION_STARTED"))


def test_wax_cage_reaches_sixty_feet_costs_two_and_needs_concentration():
    _, engine = _fight("wax", ["TAL_WAX_WAX_CAGE"], foe_at=(14, 6))  # 55 feet
    foe, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Wax Cage", target=AN)
    assert qi - _qi(engine) == 2 and _has(foe, "restrained") and _focused(engine)
    _, engine = _fight("wax", ["TAL_WAX_WAX_CAGE"], foe_at=(16, 6))  # 65 feet: past "Range 60 feet"
    assert not _offered(engine, "Wax Cage")


def test_wax_tomb_reaches_sixty_feet_costs_three_and_needs_concentration():
    _, engine = _fight("wax", ["TAL_WAX_WAX_TOMB"], foe_at=(14, 6))
    foe, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Wax Tomb", target=AN)
    assert qi - _qi(engine) == 3 and _has(foe, "restrained") and _has(foe, "blinded") and _focused(engine)


def test_press_seal_reaches_thirty_feet_costs_one_and_slows_only_on_a_failed_save():
    # "Range 30 feet. Cost 1 CP. ... An unwilling creature ... makes a Dexterity saving throw. On a failure, the seal attaches. On a
    # success, the seal fails.  Clinging Seal. The sealed creature's Speed is reduced by 10 feet while the seal remains."
    _, engine = _fight("wax", foe_at=(9, 6))  # 30 feet
    foe, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Press Seal", target=AN)
    assert qi - _qi(engine) == 1 and [value for value, _ in _speed_modifiers(foe)] == [-10]
    _, engine = _fight("wax", foe_at=(10, 6))  # 35 feet
    assert not _offered(engine, "Press Seal")
    _, engine = _fight("wax", foe_at=(9, 6), dc=PASSES)
    _do(engine, "Press Seal", target=AN)
    assert not _speed_modifiers(engine.state.actors[AN])


def test_hundred_seal_conflagration_reaches_sixty_feet_and_costs_three():
    # "Action. Range 60 feet. Cost 3 CP. ... On a failure, it takes 4d8 fire damage and is pushed 10 feet away from the nearest ignited seal."
    # "You ignite any number of your Wax Seals within range. Choose up to three creatures bearing those seals or adjacent to those
    # seals": the seal goes on at Press Seal's 30 feet and the creature is 60 feet away when it is ignited.
    _, engine = _fight("wax", ["TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"], foe_at=(6, 6))
    foe = engine.state.actors[AN]
    assert not _offered(engine, "Hundred-Seal Conflagration")  # nothing sealed yet
    _do(engine, "Press Seal", target=AN)
    engine.state.actors[ME].action_available = True
    foe.position = Position(x=14, y=6)
    qi = _qi(engine)
    _do(engine, "Hundred-Seal Conflagration", target=AN)
    assert qi - _qi(engine) == 3 and foe.current_hp < foe.maximum_hp and foe.position.x == 14
    assert any("GM chooses the 10-foot push direction" in str(event.payload) for event in engine.events)


def test_mold_wax_soft_spread_lands_sixty_feet_away_costs_one_and_needs_concentration():
    _, engine = _fight("wax", foe_at=(14, 6))
    qi = _qi(engine)
    _cast(engine, "Mold Wax: Soft Spread")
    assert qi - _qi(engine) == 1 and _focused(engine)
    assert not _kinds(engine, 0, "SAVE_ROLLED")  # printed trigger is entry/start, not creation
    zones.on_turn_start(engine, engine.state.actors[AN])
    assert _kinds(engine, 0, "SAVE_ROLLED")


def test_court_of_ten_thousand_candles_is_centred_within_sixty_feet_costs_four_and_needs_concentration():
    _, engine = _fight("wax", ["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"], foe_at=(14, 6))
    qi = _qi(engine)
    _cast(engine, "Court of Ten Thousand Candles")
    [zone] = zones.typed_zones(engine)
    assert qi - _qi(engine) == 4 and _focused(engine) and abs(zone.center.x - 14) <= 1


def test_thousand_faced_wax_sovereign_costs_four():
    _, engine = _fight("wax", ["TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN"], foe_at=(14, 6))
    qi = _qi(engine)
    _do(engine, "Thousand-Faced Wax Sovereign")
    assert qi - _qi(engine) == 4


def test_sovereign_seal_of_the_chosen_shape_reaches_sixty_feet_costs_four_and_needs_concentration():
    _, engine = _fight("wax", ["TAL_WAX_SOVEREIGN_SEAL_OF_THE_CHOSEN_SHAPE"], foe_at=(14, 6))
    qi = _qi(engine)
    _do(engine, "Sovereign Seal of the Chosen Shape: Shape of Truth", target=AN)
    assert qi - _qi(engine) == 4 and _focused(engine) and _kinds(engine, 0, "SAVE_ROLLED")


def test_waxen_city_is_made_within_a_hundred_and_twenty_feet_costs_five_and_gives_its_temporary_hit_points_once():
    # "Cost 5 CP ... a 60-foot radius centered on a point you can see within 120 feet ... alcoves where allies gain temporary hit points
    # ... when they first enter": the alcove is not run again for every hostile creature that walks into the district.
    _, engine = _fight("wax", ["TAL_WAX_WAXEN_CITY_OF_ONE_BREATH"], foe_at=(19, 12), cl=15)
    foe, qi = engine.state.actors[AN], _qi(engine)
    _cast(engine, "Waxen City of One Breath", near=(3, 6))
    assert qi - _qi(engine) == 5 and _focused(engine)
    since, start = len(engine.events), Position(x=foe.position.x, y=foe.position.y)
    foe.position = Position(x=13, y=6)
    zones.on_moved(engine, foe, start, foe.position)
    assert not _kinds(engine, since, "PASSIVE_TRIGGERED", "TEMP_HP_GRANTED")


def test_white_wax_edict_costs_five_and_does_not_make_anyone_invisible():
    # "it must succeed on a Charisma saving throw or the attempt fails": becoming invisible is one of the attempts the Edict stops.
    _, engine = _fight("wax", ["TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"], foe_at=(6, 6), cl=15)
    foe, qi = engine.state.actors[AN], _qi(engine)
    _cast(engine, "White Wax Edict of Stillness")
    assert qi - _qi(engine) == 5 and _focused(engine) and not _has(foe, "invisible")


# ---- wax: whom it is for, and how much ----------------------------------------------------------------------------------------


def test_seal_wound_is_a_touch_that_gives_an_ally_one_d_six_plus_proficiency_temporary_hit_points():
    # "Action. Touch. Cost 1 CP. ... The target gains temporary hit points equal to 1d6 + your Proficiency Bonus."  A SELF action
    # before: it was free, and nobody else could be its target.
    _, engine = _fight("wax", ["TAL_WAX_SEAL_WOUND"], foe_at=(4, 6), ally=True)
    ally, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Seal Wound", target=AN)
    assert qi - _qi(engine) == 1 and 5 <= ally.temporary_hp <= 10  # 1d6 + 4


def test_waxen_shell_is_a_touch_that_gives_an_ally_proficiency_plus_key_modifier_temporary_hit_points():
    bundle, engine = _fight("wax", ["TAL_WAX_WAXEN_SHELL"], foe_at=(4, 6), ally=True)
    numbers = _row(bundle, "Waxen Shell")["parameters"]["typed"]["numbers"]
    ally, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Waxen Shell", target=AN)
    assert qi - _qi(engine) == 1 and ally.temporary_hp == numbers["pb"] + numbers["key_mod"]


def test_living_wax_form_set_body_gives_the_caster_twice_their_cultivation_level_temporary_hit_points():
    # "Set Body. You gain temporary hit points equal to twice your Cultivation Level. ... you reduce forced movement by 10 feet":
    # the reduction is not a push of the caster, so the form no longer needs a foe within 5 feet to be used.
    _, engine = _fight("wax", ["TAL_WAX_LIVING_WAX_FORM"], foe_at=(14, 6), cl=10)
    me, qi = engine.state.actors[ME], _qi(engine)
    _do(engine, "Living Wax Form: Set Body", target=ME)
    assert qi - _qi(engine) == 2 and me.temporary_hp == 20


def test_candle_procession_costs_one_and_guiding_candle_gives_no_free_movement():
    # "Allies ... may ignore the first 5 feet of Difficult Terrain" / "allies who can see the candle ignore nonmagical Difficult
    # Terrain": the allies' terrain, not feet of movement for the caster.
    _, engine = _fight("wax", ["TAL_WAX_CANDLE_PROCESSION", "TAL_WAX_GUIDING_CANDLE"], foe_at=(4, 6))
    qi, since = _qi(engine), len(engine.events)
    _do(engine, "Candle Procession")
    assert qi - _qi(engine) == 1
    _do(engine, "Guiding Candle")
    assert not _kinds(engine, since, "MOVEMENT_GRANTED")


def test_adhesive_pool_holds_a_creature_that_fails_its_strength_save():
    # "must succeed on a Strength saving throw or have its Speed reduced to 0 until the start of its next turn": the save had no
    # consequence before.
    _, engine = _fight("wax", ["TAL_WAX_ADHESIVE_POOL"], foe_at=(5, 6))
    _cast(engine, "Mold Wax: Soft Spread")
    assert not _speed_modifiers(engine.state.actors[AN])
    zones.on_turn_start(engine, engine.state.actors[AN])
    assert [value for value, _ in _speed_modifiers(engine.state.actors[AN])] == [-30]
    _, engine = _fight("wax", ["TAL_WAX_ADHESIVE_POOL"], foe_at=(5, 6), dc=PASSES)
    _cast(engine, "Mold Wax: Soft Spread")
    assert not _speed_modifiers(engine.state.actors[AN])


def test_molten_snare_burns_a_creature_that_moves_not_the_moment_the_wax_is_made():
    # "you may spend 1 CP ... the creature takes fire damage equal to your Proficiency Bonus whenever it moves willingly or is moved
    # through the wax": damage on movement (a table ruling), not at the failed save.
    _, engine = _fight("wax", ["TAL_WAX_WAX_CAGE", "TAL_WAX_MOLTEN_SNARE"], foe_at=(4, 6))
    foe, qi = engine.state.actors[AN], _qi(engine)
    _do(engine, "Wax Cage + Molten Snare", target=AN)
    assert qi - _qi(engine) == 3 and _has(foe, "restrained") and foe.current_hp == foe.maximum_hp


# ---- weapons -----------------------------------------------------------------------------------------------------------------


def _retort_fight(*, focus: int):
    """The foe (adjacent) attacks the caster and misses; the caster's Retort would hit the foe."""
    bundle, engine = _fight("weapons", ["tianxia.talent.weapons.weapon_breaking_retort"], foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    focus_id = next(resource for resource in me.resources if resource.endswith("martial_focus"))
    me.resources[focus_id] = focus
    engine._add_modifier(me, "test", "armor_class", "ADD", 30, "SELF", expires_on="START_OF_SELF_NEXT_TURN")  # the foe misses
    engine._add_modifier(foe, "test", "armor_class", "ADD", -20, "SELF", expires_on="START_OF_SELF_NEXT_TURN")  # the Retort hits
    attack = [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_miss": [],
               "on_hit": [{"type": "damage", "dice": {"count": 2, "sides": 6}, "damage_types": ["SLASHING"]}]}]
    strike = ActionDefinition(source_definition_id="action:typed.test.foe_strike", display_name="Foe strike", owner_id=AN, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                              parameters={"typed": {"effects": attack, "numbers": {"pb": 4, "save_dc": 15, "attack_bonus": 0, "cl": 10},
                                                    "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[strike.source_definition_id] = strike
    foe.action_ids = (*foe.action_ids, strike.source_definition_id)
    engine.state.current_actor_id = AN
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == strike.source_definition_id and c.target_ids == (ME,))
    engine.execute_intent(ActionIntent(intent_id="strike", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=AN, target_ids=candidate.target_ids))
    return engine, focus_id


def test_weapon_breaking_retort_expends_martial_focus_and_deals_its_damage_on_a_hit():
    # "When a creature misses you with a melee weapon attack, you may use your Reaction and expend Martial Focus to make one weapon
    # attack ... On a hit, deal normal damage."  The reaction cost nothing and its hit dealt nothing.
    engine, focus_id = _retort_fight(focus=1)
    assert engine.state.actors[ME].resources[focus_id] == 0
    assert engine.state.actors[AN].current_hp < engine.state.actors[AN].maximum_hp


def test_weapon_breaking_retort_needs_martial_focus_to_expend():
    engine, focus_id = _retort_fight(focus=0)
    assert engine.state.actors[ME].reaction_available and engine.state.actors[AN].current_hp == engine.state.actors[AN].maximum_hp


# ---- the built authority ------------------------------------------------------------------------------------------------------


def test_every_override_of_this_review_is_bound_to_its_text_and_reviewed_final_in_the_built_authority():
    review = json.loads(REVIEW.read_text())["mechanics"]
    authority = _authority()
    for key, entry in review.items():
        assert authority[key]["typing_status"] == "reviewed_final", key
        assert authority[key]["source"]["text_sha256"] == entry["text_sha256"], key
    # The builder skips its parser-duplicate cleanup on a reviewed_final mechanic, so these overrides carry the cleaned rows: no
    # Speed -10 beside Press Seal's save, and no temporary hit points without a recipient in the Court.
    assert [effect["type"] for effect in authority["TAL_WAX_PRESS_SEAL"]["effects"]] == ["save"]
    court = authority["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"]["effects"]
    assert all(effect.get("applies_to") for effect in court if effect["type"] == "temp_hp")
