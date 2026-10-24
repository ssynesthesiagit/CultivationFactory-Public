"""AUTO67 (automation lane, 2026-10-05) and AUTO67f1 (its pre-merge review fixes): the Gravity sphere's printed flight, falling,
descent and post-Shove lines.

Every test compiles a real Gravity fighter, runs it through the live engine (Gate4ControllerEngine) and asserts the printed
effect.  They fail on the typing this lane replaced: the untyped "N CP or Stamina" costs, the Flight Suppression area that
saved nothing, the flight and falling riders, Weight-Borrowing Throw and Falling Hammer, which changed nothing.

The AUTO67f1 cases are the review's seven findings, each answered at the level it showed: Reverse Gravity Step's Duration (a
condition with the engine's own expiry, checked after a real end of turn and across a table commit + fresh reload), Flight
Suppression's Hover exception and its "a creature flying" trigger, the real 30-foot protection distance, Local Down's surcharge
confined to its own area, Falling Hammer's 10-foot threshold, Weight-Borrowing Throw's direction (every legal square, plus
"Knock it Prone", asked of the player and of the AI) and Gravity Sense's identifying/resisting gate.

Overrides: authority/typed_mechanics/reviewed_final.d/auto67_gravity.json (+ in-place edits of review_sw-gravity.json,
gravity_canvas.json, riders_c2.json, riders_c12.json); feature rows: combat/rules/feature_blocks.d/riders_c2.json;
plug-ins: combat/ext/gravity.py (with combat/ext/descent_steps.py shared with Axe-Kick Descent, and the new shared
combat/ext/forced_destination.py used by Orbit-Breaking Guard and Weight-Borrowing Throw).
Engine seams: combat/flight.py reads two recorded capability keys, ``fly_speed_percent`` and ``fly_speed_zero``.
"""

import json
import zipfile
from pathlib import Path

import pytest

from combat import ext, falling
from combat.ext import ability_source
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_auto_lane1 as L1
from tests.h1_support import script

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.auto67"
FOE = AN
FLY = "condition:typed.test_fly"
NO_FLY = "condition:typed.gravity_no_flight"
HALVED = "condition:typed.gravity_fly_speed_halved"
DIFFICULT = "condition:typed.gravity_difficult_terrain"
REVERSED = "condition:typed.gravity_reverse_step"
WS = "TAL_GRAVITY_WEIGHT_SHIFT_BASE"
LIGHT, HEAVY = "condition:typed.state.body_lightening", "condition:typed.state.body_heavying"


def _sheet(mids, *, cl=15, dc=16, weapon="tianxia.mortal.weapon.fu", pb=4):
    sheet = L1._sheet(mids[0], cl=cl, dc=dc)
    sheet["identity"]["proficiency_bonus"] = pb
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(mids)
    sheet["path_and_subpath"] = {"path_record_ids": ["tianxia.path.body_refining"]}
    sheet["identity"]["path"] = "Body Refining"
    sheet["ability_scores_and_statistics"]["primary_resource"] = {"name": "Stamina", "maximum": 30}
    if weapon:
        sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon, "name": weapon, "quantity": 1}]}}]
    return sheet


def _bundle(mids, actor_id=ME, ask=False, **kw):
    return compile_character(_sheet(mids, **kw), actor_id=actor_id,
                            reaction_plan={"ask": True} if ask else None)


def _fight(mids, *, cl=15, dc=16, me_at=(3, 6), foe_at=(4, 6), ask=False, battlefield=None, **kw):
    """ME (team a) against the sample foe An Eui (team b), already on ME's turn. ``ask=True`` compiles ME with the
    Ask me reaction plan, so its own decisions are put to the player rather than answered for it."""
    bundle = _bundle(mids, cl=cl, dc=dc, ask=ask, **kw)
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO67", typed_bundles=(bundle,), battlefield=battlefield,
                                   roster_setup={"primary_actor_ids": [ME, FOE],
                                                 "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]},
                                                                         FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    from tests.hunt24_support import finish_direct_setup

    finish_direct_setup(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
    engine.state.actors[FOE].armor_class = -50
    _ready(engine, ME)
    return engine


def _ready(engine, actor_id=ME):
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    actor.movement_remaining_ft = engine._effective_speed(actor)
    return actor


def _act(engine, name, target=None, actor_id=ME, destination=None):
    matches = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id
               and (target is None or target in (c.target_ids or ()))]
    assert matches, f"{name!r} is not legal for {actor_id}; legal: {sorted({c.display_name for c in engine.legal_candidates()})}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto67-{name}-{before}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=(target,) if target else (candidate.target_ids or ()),
                                       destination=destination or candidate.destination))
    return engine.events[before:]


def _move_name(engine, at):
    """The walking candidate that ends on ``at`` (its label carries the feet it costs)."""
    names = sorted({c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Move to ")})
    return next(n for n in names if n.split(" at ")[0] == f"Move to {at[0]},{at[1]}")


def _area(engine, prefix, at=None):
    """The name of an area's point-targeted candidate: "Gravity Well at 8,6"."""
    names = sorted({c.display_name for c in engine.legal_candidates() if c.display_name.startswith(prefix)})
    assert names, f"{prefix!r} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates()})[:20]}"
    if at is not None:
        pick = next((n for n in names if n.split(" at ")[-1].split(" ")[0] == f"{at[0]},{at[1]}"), None)
        assert pick, f"{prefix!r} has no candidate at {at}; it offers {names[:8]}"
        return pick
    return names[0]


def _answers(engine, picks, silent=()):
    """Answer each extension choice whose id matches a key of ``picks``; decline everything else. Returns the questions asked. An
    exact id wins over a partial one, and the longest partial key wins over a shorter one, so a menu named after another
    (``gravity_weight_borrowing_move`` against ``gravity_weight_borrowing``) is never answered with the other menu's options.
    An id matching ``silent`` is not answered *at all* -- the provider returns no decision, which is the "nobody is there to
    answer" case, and so the plugin's own documented fallback chooses for itself (needle.ask's first offered option). That is a
    different event from declining, which is an answer."""
    from combat.gate2_runtime_models import ReactionDecision

    asked = []
    ranked = sorted(picks, key=len, reverse=True)
    left = tuple(silent)

    def provider(request):
        asked.append(request)
        options = list(request.get("legal_option_ids") or ())
        source = request["reaction_source_id"]
        if any(name in source for name in left):
            return None, None
        for key in [key for key in picks if key == source] + [key for key in ranked if key in source]:
            pick = picks[key]
            chosen = pick(options) if callable(pick) else pick
            if chosen is None:
                break
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE",
                                    option_ids=tuple(chosen)), None
        spec = request.get("extension_choice") or {}
        if spec and not spec.get("allow_decline", True):
            count = max(1, int(spec.get("minimum_selections") or 1))
            chosen = list(spec.get("preferred_option_ids") or options)[:count]
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE",
                                    option_ids=tuple(chosen)), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None

    engine.set_reaction_provider(provider)
    return asked


def _of(events, event_type):
    return [e.payload or {} for e in events if e.event_type == event_type]


def _held(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _fly_speed(engine, actor):
    from combat import flight

    return flight.profile(engine, actor).speed_ft


def _make_flyer(engine, *, hover=False):
    """Give the foe a Fly Speed the way Wind-Borne Body does: recorded capability data on a condition."""
    foe = engine.state.actors[FOE]
    foe.fly_speed_ft, foe.hover = 30, hover
    return foe


def _drop(engine, actor, steps=2):
    """Launch ``actor`` ``steps`` five-foot steps up and let the engine's own fall settle it."""
    before = actor.current_hp
    falling.displace(engine, actor, steps, "test:auto67.launch")
    return before - actor.current_hp


# ------------------------------------------------------------------------------------------------ typed costs
@pytest.mark.parametrize("ability,talent,cost", [("Local Down", "tianxia.talent.gravity.local_down", 6),
                                                 ("Flight Suppression", "TAL_GRAVITY_FLIGHT_SUPPRESSION", 5),
                                                 ("Reverse Gravity Step", "tianxia.talent.gravity.reverse_gravity_step", 2)])
def test_printed_technique_costs_are_charged(ability, talent, cost):
    """"Cost: 6 CP or Stamina." typed as a cost, not as free text: the printed price is what the table charges."""
    engine = _fight([WS, talent])
    stamina = engine.state.actors[ME].resources["resource:core.stamina"]
    _act(engine, _area(engine, ability, (4, 6) if ability != "Reverse Gravity Step" else None))
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina - cost


def test_falling_star_calamity_prints_its_cost_as_a_cost_not_as_free_text():
    """"Cost: 15 CP or Stamina" is a typed cost (the table charges it), and "Use Limit: Once per week" is the printed once-per-fight
    ruling the compiler already enforces. A Ritual Procedure compiles no fight action on any sphere, so this one is a data check."""
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    record = authority["mechanics"]["tianxia.talent.gravity.falling_star_calamity"]
    assert [[part["resource"] for part in way] for way in record["cost"]] == [["cp"], ["stamina"]]
    assert [way[0]["amount"] for way in record["cost"]] == [15, 15]
    assert "once per week" in str(record["use_limit"])


# ------------------------------------------------------------------------------------------------ flight
def test_flight_suppression_grounds_a_flying_creature_that_fails_its_turn_start_save():
    """"A creature flying inside the area makes a Strength saving throw at the start of each of its turns. Failed Save: Its Fly
    Speed becomes 0" -- and "A creature without Hover falls when its Fly Speed becomes 0": the Fly Speed is 0, so the engine's own
    fall check drops a creature that cannot Hover."""
    engine = _fight(["TAL_GRAVITY_FLIGHT_SUPPRESSION"], dc=50)
    foe = _make_flyer(engine)
    _act(engine, _area(engine, "Flight Suppression", (4, 6)))
    _ready(engine, FOE)
    falling.displace(engine, foe, 3, "test:auto67.launch")  # airborne at z=3, flying
    engine._system_start_turn()
    assert _held(foe, NO_FLY), "the failed save left no grounded condition"
    assert _fly_speed(engine, foe) == 0
    assert foe.position.z == 0  # the engine's own fall check dropped a creature that cannot Hover


def test_flight_suppression_keeps_a_hovering_creature_up_when_it_fails_the_save():
    """The same failed save only removes the Fly Speed, never Hover: "A creature without Hover falls" is the printed exception,
    so a creature that can Hover stays aloft and aloft is where it is."""
    engine = _fight(["TAL_GRAVITY_FLIGHT_SUPPRESSION"], dc=50)
    foe = _make_flyer(engine, hover=True)
    _act(engine, _area(engine, "Flight Suppression", (4, 6)))
    _ready(engine, FOE)
    falling.displace(engine, foe, 3, "test:auto67.launch")  # airborne at z=3
    engine._system_start_turn()
    assert _held(foe, NO_FLY) and _fly_speed(engine, foe) == 0
    assert foe.position.z == 3, "a creature that can Hover was dropped because its Fly Speed was 0"


def test_flight_suppression_halves_the_fly_speed_of_a_creature_that_saves():
    """"Successful Save: Its Fly Speed is halved until the start of its next turn" (combat/flight.py's fly_speed_percent)."""
    engine = _fight(["TAL_GRAVITY_FLIGHT_SUPPRESSION"], dc=3)
    foe = _make_flyer(engine, hover=True)
    _act(engine, _area(engine, "Flight Suppression", (4, 6)))
    _ready(engine, FOE)
    falling.displace(engine, foe, 3, "test:auto67.launch")  # airborne at z=3
    script(engine, [20])  # the Strength saving throw the printed turn-start line asks for
    engine._system_start_turn()
    assert _held(foe, HALVED) and _fly_speed(engine, foe) == 15
    assert foe.position.z == 3  # only its Fly Speed changed: it still hovers where it was


def test_flight_suppression_never_asks_a_creature_that_is_not_flying():
    """The printed save is for a creature flying inside the area: an ordinary walking creature is untouched, and neither is a
    creature with a Fly Speed still standing on the ground."""
    engine = _fight(["TAL_GRAVITY_FLIGHT_SUPPRESSION"], dc=50)
    foe = engine.state.actors[FOE]
    _act(engine, _area(engine, "Flight Suppression", (4, 6)))
    _ready(engine, FOE)
    engine._system_start_turn()
    assert not _held(foe, NO_FLY) and not _held(foe, HALVED)
    grounded = _fight(["TAL_GRAVITY_FLIGHT_SUPPRESSION"], dc=50)
    flyer = _make_flyer(grounded)  # a Fly Speed of 30, but standing on the ground at z=0
    _act(grounded, _area(grounded, "Flight Suppression", (4, 6)))
    _ready(grounded, FOE)
    grounded._system_start_turn()
    assert not _held(flyer, NO_FLY) and not _held(flyer, HALVED), "a grounded flyer was asked to save as if it were flying"


def test_a_gravity_domain_stops_a_hostile_creature_from_flying():
    """"Hostile creatures cannot fly unless they can Hover" inside the Domain."""
    hostile = _fight(["tianxia.talent.gravity.gravity_domain"])
    _make_flyer(hostile)
    foe = hostile.state.actors[FOE]
    _act(hostile, _area(hostile, "Gravity Domain"))
    _ready(hostile, FOE)
    assert _fly_speed(hostile, foe) == 0
    hovering = _fight(["tianxia.talent.gravity.gravity_domain"])
    flyer = _make_flyer(hovering, hover=True)
    _act(hovering, _area(hovering, "Gravity Domain"))
    _ready(hovering, FOE)
    assert _fly_speed(hovering, flyer) == 30  # it can Hover, so it keeps its Fly Speed


def test_weight_of_the_mountain_drops_a_flying_creature_that_fails_the_save():
    """"A flying creature that fails the save falls if it cannot Hover": the weight holds it (Speed 0), so the engine's own fall
    check drops it."""
    engine = _fight(["TAL_GRAVITY_WEIGHT_OF_THE_MOUNTAIN"], dc=50)
    foe = _make_flyer(engine)
    falling.displace(engine, foe, 1, "test:auto67.launch")  # airborne at z=1
    _act(engine, "Weight of the Mountain", FOE)
    assert _held(foe, "condition:typed.restrained") and _fly_speed(engine, foe) == 0
    falling.settle(engine, "test:auto67.settle")
    assert foe.position.z == 0


def test_heaven_s_weight_keeps_both_outcomes_from_flying():
    """"it cannot fly": a creature that fails is held for the minute, and one that saves cannot fly until the start of its next turn."""
    engine = _fight(["tianxia.talent.gravity.heaven_s_weight"], dc=50)
    foe = _make_flyer(engine, hover=True)
    _act(engine, "Heaven’s Weight", FOE)
    assert _held(foe, "condition:typed.restrained") and _fly_speed(engine, foe) == 0
    other = _fight(["tianxia.talent.gravity.heaven_s_weight"], dc=3)
    saved = _make_flyer(other, hover=True)
    script(other, [20])  # the target saves
    _act(other, "Heaven’s Weight", FOE)
    assert _held(saved, NO_FLY) and _fly_speed(other, saved) == 0


# ------------------------------------------------------------------------------------------------ falling
def test_gravitic_armor_makes_a_fall_free_while_it_is_on():
    """"You are immune to ordinary falling damage" while Gravitic Armor is active."""
    engine = _fight([WS, "tianxia.talent.gravity.gravitic_armor"])
    _act(engine, "Gravitic Armor")
    assert _drop(engine, engine.state.actors[ME]) == 0  # the armored fighter takes no falling damage


def test_gravitic_armor_off_lets_the_fall_hurt():
    engine = _fight([WS, "tianxia.talent.gravity.gravitic_armor"])
    assert _drop(engine, engine.state.actors[ME]) > 0


def test_moon_weight_incarnation_makes_a_fall_free():
    """"You are immune to ordinary falling damage" for the minute it lasts."""
    engine = _fight([WS, "tianxia.talent.gravity.moon_weight_incarnation"])
    _act(engine, "Moon-Weight Incarnation")
    assert _drop(engine, engine.state.actors[ME]) == 0


def test_body_lightening_reduces_falling_damage_by_five_times_proficiency_bonus():
    """"You reduce any falling damage you take by an amount equal to 5 times your Proficiency Bonus"."""
    plain = _fight([WS])
    hurt = _drop(plain, plain.state.actors[ME], steps=4)
    engine = _fight([WS])
    _act(engine, "Weight Shift: Body Lightening")
    softened = _drop(engine, engine.state.actors[ME], steps=4)
    assert softened == max(0, hurt - 5 * engine.state.actors[ME].proficiency_bonus)


def test_feather_body_ignores_a_thirty_foot_drop_and_stands_for_five_feet():
    """"You ignore the first 30 feet of falling" and "You may stand from Prone by spending only 5 feet of movement"."""
    engine = _fight([WS, "tianxia.talent.gravity.feather_body"])
    assert _drop(engine, engine.state.actors[ME]) > 0  # without the mode the drop hurts
    _act(engine, "Weight Shift: Body Lightening")
    assert _drop(engine, engine.state.actors[ME]) == 0
    from combat import posture

    me = _ready(engine)
    engine._apply_condition(me, "condition:typed.prone", "test:auto67.prone", ME, expires_on="STAND_UP")
    assert posture.standing_cost(engine, me) == 5  # the printed 5 feet, against the ordinary half-Speed cost


@pytest.mark.parametrize("steps,feet", [(3, 15), (4, 20), (5, 25), (6, 30)])
def test_feather_body_ignores_a_drop_of_twenty_or_thirty_feet(steps, feet):
    """The printed distance is 30 feet, not the engine's 10-foot damage step: every drop up to and including 30 feet is free,
    and the test really drops that far (one five-foot step per ``steps``)."""
    engine = _fight([WS, "tianxia.talent.gravity.feather_body"], dc=50)
    me = engine.state.actors[ME]
    assert _drop(engine, me) > 0, f"a {feet}-foot drop should hurt without the mode"
    _act(engine, "Weight Shift: Body Lightening")
    assert _drop(engine, me, steps=steps) == 0, f"a {feet}-foot drop was not free"


def test_feather_body_long_fall_excludes_the_first_thirty_feet():
    """The printed first thirty feet are excluded before Body Lightening's ordinary reduction."""
    engine = _fight([WS, "tianxia.talent.gravity.feather_body"], pb=2)
    me = engine.state.actors[ME]
    _act(engine, "Weight Shift: Body Lightening")
    script(engine, [6] * 12)
    assert _drop(engine, me, steps=12) == 18 - 10  # sixty feet, measured as thirty: 3d6, then 5 x PB


def test_reverse_gravity_step_costs_two_and_keeps_this_turns_drop_free():
    """"Cost: 2 CP or Stamina ... avoid ordinary falling damage during this movement ... At the end of the turn, normal gravity
    returns"."""
    engine = _fight(["tianxia.talent.gravity.reverse_gravity_step"])
    stamina = engine.state.actors[ME].resources["resource:core.stamina"]
    _act(engine, "Reverse Gravity Step")
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina - 2
    assert _drop(engine, engine.state.actors[ME]) == 0  # this turn's own drop is free
    _ready(engine, FOE)
    assert _drop(engine, engine.state.actors[FOE]) > 0  # nobody else is protected


def test_reverse_gravity_step_ends_with_the_turn_that_cast_it():
    """"At the end of the turn, normal gravity returns." The same actor, the same step, after a real end of turn: the protection is
    gone rather than lasting the rest of the fight."""
    engine = _fight(["tianxia.talent.gravity.reverse_gravity_step"])
    _act(engine, "Reverse Gravity Step")
    me = engine.state.actors[ME]
    assert _held(me, REVERSED) and _drop(engine, me) == 0
    engine.end_turn()  # the foe's turn; the printed Duration is still running out at the end of ME's turn
    engine.end_turn()
    assert not _held(me, REVERSED), "normal gravity did not return at the end of the turn that cast it"
    assert _drop(engine, me) > 0, "the fighter is still immune to falling damage"


def test_reverse_gravity_step_never_protects_a_fighter_that_did_not_cast_it():
    """The plug-in is inert for anyone without the talent: two ordinary fighters drop for full damage."""
    engine = _fight([WS])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert _drop(engine, me) > 0 and not _held(me, REVERSED)
    _ready(engine, FOE)
    assert _drop(engine, foe) > 0 and not _held(foe, REVERSED)


# ------------------------------------------------------------------------------------------------ descent riders
def test_falling_hammer_adds_force_dice_to_a_melee_hit_after_a_descent():
    """"When you fall or descend at least 10 feet before hitting a creature with a melee attack on the same turn ... add an extra
    1d6 Force damage" (2d6 at CL 11) and needs no mode on."""
    engine = _fight([WS, "TAL_GRAVITY_FALLING_HAMMER"], cl=15, dc=50)
    _answers(engine, {"gravity_weighted_strike": ["heavying:stamina"]})
    me = engine.state.actors[ME]
    _drop(engine, me)  # the 10-foot descent the printed trigger names
    script(engine, [10] + [6] * 12)  # the protected fall rolls no dice; make the melee hit deterministic
    events = _act(engine, "Fu (Short Axe) attack", FOE)
    rolled = [p for p in _of(events, "DAMAGE_ROLLED") if p.get("expression", "").startswith(("1d6", "2d6"))]
    assert rolled, "no Heavying Blow damage: the descent did not open Weighted Strike"
    assert me.resources["resource:core.stamina"] == 29  # one point paid, exactly as printed


def test_falling_hammer_needs_a_descent():
    """No descent this turn: Weighted Strike stays behind its printed trigger."""
    engine = _fight([WS, "TAL_GRAVITY_FALLING_HAMMER"], dc=50)
    _answers(engine, {})
    events = _act(engine, "Fu (Short Axe) attack", FOE)
    assert not [p for p in _of(events, "DAMAGE_ROLLED") if p.get("expression", "").endswith("d6")]


def test_falling_hammer_needs_ten_feet_of_descent_not_a_five_foot_step():
    """"When you fall or descend at least 10 feet": a five-foot step down is a descent, but not the printed one, so Weighted
    Strike stays closed. (Axe-Kick Descent's broader "descend from a higher space" trigger is its own and is unchanged.)"""
    engine = _fight([WS, "TAL_GRAVITY_FALLING_HAMMER"], dc=50)
    _answers(engine, {"gravity_weighted_strike": ["heavying:stamina"]})
    me = engine.state.actors[ME]
    assert _drop(engine, me, steps=1) == 0  # a five-foot descent: no falling damage, and no print below
    assert me.turn_flags.get("gravity_round_descent") is None, "a five-foot step stamped the ten-foot descent"
    events = _act(engine, "Fu (Short Axe) attack", FOE)
    assert not [p for p in _of(events, "DAMAGE_ROLLED") if p.get("expression", "").startswith(("1d6", "2d6"))]


@pytest.mark.parametrize("steps,feet", [(4, 20), (5, 25), (6, 30)])
def test_falling_hammer_leaves_a_descent_of_thirty_feet_or_less_free(steps, feet):
    """"You take no falling damage from the first 30 feet of the descent": the test drops that far, not the engine's 10-foot
    damage step."""
    engine = _fight([WS, "TAL_GRAVITY_FALLING_HAMMER"])
    me = engine.state.actors[ME]
    assert _drop(engine, me, steps=steps) == 0, f"a {feet}-foot descent was not free"


def test_falling_hammer_long_descent_excludes_the_first_thirty_feet():
    """A sixty-foot descent rolls only the three dice belonging to its unprotected thirty feet."""
    engine = _fight([WS, "TAL_GRAVITY_FALLING_HAMMER"])
    script(engine, [6] * 12)
    assert _drop(engine, engine.state.actors[ME], steps=12) == 18


# ------------------------------------------------------------------------------------------------ after a Shove
def test_weight_borrowing_throw_puts_the_target_on_the_square_the_player_picks():
    """"you may spend 1 CP or Stamina to move the target 5 feet in any horizontal direction or knock it Prone": every open square
    within 5 feet is offered, so a sideways square beside the shover is a choice, not only away and toward."""
    engine = _fight([WS, "tianxia.talent.gravity.weight_borrowing_throw"], foe_at=(4, 6), me_at=(3, 6))
    _act(engine, "Weight Shift: Body Heavying")
    stamina = engine.state.actors[ME].resources["resource:core.stamina"]
    asked = _answers(engine, {"gravity_weight_borrowing_move": ["cell:4,7"],
                              "gravity_weight_borrowing": ["stamina"]})
    start = len(engine.events)
    _act(engine, "Shove: Push 5 ft", FOE)
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina - 1
    question = next(r for r in asked if "gravity_weight_borrowing_move" in r["reaction_source_id"])
    assert question.get("legal_option_ids"), "the direction was not asked"
    assert "prone" in question["legal_option_ids"], "the printed 'or knock it Prone' is missing"
    assert {"cell:4,5", "cell:4,7"} <= set(question["legal_option_ids"]), \
        f"sideways squares were not offered: {question['legal_option_ids']}"
    paid = next(index for index, event in enumerate(engine.events[start:], start) if event.event_type == "RESOURCE_SPENT")
    thrown = [e for e in engine.events[paid + 1:]
              if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE and (e.payload or {}).get("forced")]
    assert thrown and thrown[0].payload["destination"] == {"x": 4, "y": 7}, \
        f"the chosen sideways square was not used: {[(e.payload or {}).get('destination') for e in thrown]}"
    assert thrown[0].payload["path"] == [{"x": 4, "y": 6}, {"x": 4, "y": 7}], \
        f"the throw did not walk a forced route: {thrown[0].payload['path']}"


def test_weight_borrowing_throw_can_knock_the_target_prone():
    """"or knock it Prone": the second half of the printed choice is a real option, not text."""
    engine = _fight([WS, "tianxia.talent.gravity.weight_borrowing_throw"])
    _act(engine, "Weight Shift: Body Heavying")
    _answers(engine, {"gravity_weight_borrowing_move": ["prone"], "gravity_weight_borrowing": ["stamina"]})
    _act(engine, "Shove: Push 5 ft", FOE)
    assert _held(engine.state.actors[FOE], "condition:typed.prone")


def test_weight_borrowing_throw_needs_body_heavying():
    """The printed trigger is "while Body Heavying is active"."""
    engine = _fight([WS, "tianxia.talent.gravity.weight_borrowing_throw"])
    asked = _answers(engine, {"gravity_weight_borrowing": ["stamina"]})
    _act(engine, "Shove: Push 5 ft", FOE)
    assert not [r for r in asked if "weight_borrowing" in r["reaction_source_id"]]


def test_weight_borrowing_throw_moves_a_grappled_creature_ten_feet():
    """"If the target is already Grappled by you, increase the movement to 10 feet": the squares within 10 feet are offered."""
    engine = _fight([WS, "tianxia.talent.gravity.weight_borrowing_throw"])
    _act(engine, "Weight Shift: Body Heavying")
    _answers(engine, {})
    script(engine, [1])  # the Grapple's contest save fails: the throw holds
    _act(engine, "Grapple", FOE)
    _ready(engine)
    foe = engine.state.actors[FOE]
    assert _held(foe, "condition:typed.grappled")
    asked = _answers(engine, {"gravity_weight_borrowing_move": ["cell:5,6"],
                              "gravity_weight_borrowing": ["stamina"]})
    script(engine, [1])  # the Shove's contest save fails: the throw holds
    start = len(engine.events)
    _act(engine, "Shove: Push 5 ft", FOE)
    question = next(r for r in asked if "gravity_weight_borrowing_move" in r["reaction_source_id"])
    assert {"cell:5,5", "cell:5,7", "cell:5,6"} <= set(question["legal_option_ids"]), \
        f"the printed 10 feet were not offered: {question['legal_option_ids']}"
    paid = next(index for index, event in enumerate(engine.events[start:], start) if event.event_type == "RESOURCE_SPENT")
    thrown = [e for e in engine.events[paid + 1:]
              if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE and (e.payload or {}).get("forced")]
    assert thrown and thrown[0].payload["destination"] == {"x": 5, "y": 6}, \
        f"the chosen 10-foot square was not used: {[(e.payload or {}).get('destination') for e in thrown]}"
    assert thrown[0].payload["path"] == [{"x": 4, "y": 6}, {"x": 5, "y": 6}], \
        f"a 10-foot throw must walk two five-foot steps: {thrown[0].payload['path']}"


# ------------------------------------------------------------------------------------------------ senses and areas
GRAVITY_TECHNIQUE = "tianxia.talent.gravity.black_star_grip"
SENSE = "tianxia.talent.gravity.gravity_sense"
PRISON = "tianxia.talent.gravity.event_horizon_prison"
WALLER = "actor:factory.auto67_waller"
GATE_NUMBERS = {"pb": 4, "key_mod": 2}


def _gate_ctx(engine, creature, numbers=None):
    """A Context for the teleport gate a creature walks through (tests/test_riders_c2.py's shape)."""
    from combat import typed_executor

    return typed_executor.Context(engine, creature, next(iter(engine.action_catalog.values())), None,
                                  {"numbers": dict(numbers or GATE_NUMBERS)}, [creature], creature, {})


def _imprisoned(mids):
    """ME (owning ``mids``) inside an Event Horizon Prison cast by another creature, which is the only check this table asks
    a creature to resist a Gravity effect with."""
    bundle = _bundle(mids, cl=17)
    waller = compile_character(_sheet([PRISON], cl=17), actor_id=WALLER)
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO67-PRISON", typed_bundles=(bundle, waller),
                                   roster_setup={"primary_actor_ids": [ME, WALLER],
                                                 "team_by_actor": {ME: "team:a", WALLER: "team:b"},
                                                 "starting_positions": {ME: {"x": 6, "y": 6},
                                                                         WALLER: {"x": 0, "y": 6}}})
    from tests.hunt24_support import finish_direct_setup

    finish_direct_setup(engine)
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
    _ready(engine, WALLER)
    _act(engine, _area(engine, "Event Horizon Prison", (6, 6)), actor_id=WALLER)
    _ready(engine, ME)
    return engine


def test_gravity_sense_adds_two_to_a_check_made_to_resist_a_gravity_effect():
    """"+2 bonus to Cultivation Checks made to identify or resist Gravity effects": it answers the opposed Cultivation Check a
    creature makes to teleport out of an Event Horizon Prison."""
    engine = _imprisoned([WS, SENSE])
    me = engine.state.actors[ME]
    start = len(engine.events)
    verdicts = ext.run("teleport_gate", _gate_ctx(engine, me), me.position, Position(x=6, y=1))
    check = next(p for p in _of(engine.events[start:], "CHECK_ROLLED"))
    assert check["check"] == "Cultivation Check (opposed)"
    assert check["actor"]["modifier"] == GATE_NUMBERS["pb"] + GATE_NUMBERS["key_mod"] + 2, \
        f"Gravity Sense's +2 did not answer the resisting check: {check['actor']['modifier']}"
    assert verdicts == [False], "the contested teleport was not vetoed"
    plain = _imprisoned([WS])
    prisoner = plain.state.actors[ME]
    start = len(plain.events)
    ext.run("teleport_gate", _gate_ctx(plain, prisoner), prisoner.position, Position(x=6, y=1))
    check = next(p for p in _of(plain.events[start:], "CHECK_ROLLED"))
    assert check["actor"]["modifier"] == GATE_NUMBERS["pb"] + GATE_NUMBERS["key_mod"], \
        "without the talent the resisting check still got +2"


def test_gravity_sense_gives_no_bonus_to_an_offensive_check():
    """The printed bonus is for identifying or resisting a Gravity effect, so the caster's own Gravity-sphere check keeps its
    printed total (review finding 7: this used to add +2 to any Gravity-sphere check)."""
    engine = _fight([WS, GRAVITY_TECHNIQUE, SENSE])
    me = engine.state.actors[ME]
    numbers = {"pb": me.proficiency_bonus, "key_mod": 2}
    ability_source.cultivation_check(engine, me, numbers, 40,
                                     next(aid for aid in me.action_ids if "black_star_grip" in aid), "Cultivation Check")
    assert engine.rolls[-1].modifier == numbers["pb"] + numbers["key_mod"], \
        f"an ability check of the Gravity sphere was given the identifying/resisting bonus: {engine.rolls[-1].modifier}"


def test_gravity_sense_is_inert_without_the_talent():
    """A fighter without Gravity Sense keeps the printed Cultivation Check total."""
    engine = _fight([WS, GRAVITY_TECHNIQUE])
    me = engine.state.actors[ME]
    numbers = {"pb": me.proficiency_bonus, "key_mod": 2}
    ability_source.cultivation_check(engine, me, numbers, 40,
                                     next(aid for aid in me.action_ids if "black_star_grip" in aid), "Cultivation Check")
    assert engine.rolls[-1].modifier == numbers["pb"] + numbers["key_mod"]


def test_local_down_makes_the_ground_difficult_for_a_creature_that_saves():
    """"Successful Save: The creature holds position but treats the area as difficult terrain until the start of its next turn":
    each walking step inside the area then costs twice as much."""
    engine = _fight(["tianxia.talent.gravity.local_down"], dc=3)
    script(engine, [20])  # the creature saves
    _act(engine, _area(engine, "Local Down", (4, 6)))
    foe = _ready(engine, FOE)
    assert _held(foe, DIFFICULT)
    from combat import movement_costs

    # Each walking step costs one extra foot, which is what the engine's own movement menu charges (movement_costs.surcharge).
    assert movement_costs.surcharge(engine, foe) == engine.grid.square_size_ft
    plain = _fight(["tianxia.talent.gravity.local_down"], dc=3)
    assert movement_costs.surcharge(plain, plain.state.actors[FOE]) == 0  # no area, no surcharge
    engine._system_start_turn()  # the start of its next turn
    assert not _held(foe, DIFFICULT)


def test_local_down_does_not_charge_a_creature_that_left_the_area():
    """The printed rule limits the difficult ground to that area: a saver that walks out of the sphere (or is moved out of it)
    walks at its ordinary cost again, even though the condition has not expired."""
    engine = _fight(["tianxia.talent.gravity.local_down"], dc=3)
    script(engine, [20])
    _act(engine, _area(engine, "Local Down", (4, 6)))
    foe = _ready(engine, FOE)
    from combat import movement_costs

    assert movement_costs.surcharge(engine, foe) == engine.grid.square_size_ft
    foe.position = Position(x=0, y=0)  # it has walked clear of the 20-foot area
    assert _held(foe, DIFFICULT), "the condition should still be there; only the area it names is gone"
    assert movement_costs.surcharge(engine, foe) == 0, "difficult terrain followed the creature out of the area"


def test_local_down_is_inert_for_a_creature_it_never_touched():
    """A creature that never made the save pays nothing, and neither does a plain fighter in the same fight."""
    engine = _fight(["tianxia.talent.gravity.local_down"], dc=3)
    script(engine, [20])
    _act(engine, _area(engine, "Local Down", (4, 6)))
    from combat import movement_costs

    away = _fight([WS])
    assert movement_costs.surcharge(away, away.state.actors[ME]) == 0
    assert not _held(away.state.actors[ME], DIFFICULT)


# ------------------------------------------------------------------------------------------------ Ask me and the saved table
BORROW = "tianxia.talent.gravity.weight_borrowing_throw"


def test_weight_borrowing_throw_asks_the_player_and_names_what_is_being_asked_about():
    """A player is asked the printed direction (Ask me / manual control), and the prompt names the ability, the action that
    triggered it and the creature it moves."""
    engine = _fight([WS, BORROW], ask=True, foe_at=(4, 6), me_at=(3, 6))
    _act(engine, "Weight Shift: Body Heavying")
    asked = _answers(engine, {"gravity_weight_borrowing_move": ["cell:4,7"], "gravity_weight_borrowing": ["stamina"]})
    _act(engine, "Shove: Push 5 ft", FOE)
    foe_name = engine.state.actors[FOE].display_name
    payment = next(r for r in asked if r["reaction_source_id"].endswith("gravity_weight_borrowing"))
    assert "Weight-Borrowing Throw" in payment["choice_trigger"]["prompt"]
    assert "Shove" in payment["choice_trigger"]["prompt"], "the trigger did not name the action that caused it"
    assert foe_name in payment["choice_trigger"]["prompt"], "the trigger did not name the creature affected"
    direction = next(r for r in asked if r["reaction_source_id"].endswith("gravity_weight_borrowing_move"))
    prompt = direction["choice_trigger"]["prompt"]
    for phrase in ("Weight-Borrowing Throw", "Shove", foe_name):
        assert phrase in prompt, f"{phrase!r} is missing from the direction prompt: {prompt!r}"
    assert direction["choice_trigger"]["name"] == "Weight-Borrowing Throw"
    assert not [i for i in direction["choice_trigger"]["labels"] if "condition:typed" in str(i)], \
        "an internal id reached the player's menu"


def test_weight_borrowing_throw_pays_nothing_and_raises_nothing_when_nobody_answers():
    """An AI fighter answers for itself. Nobody answering the printed "you may spend 1" means it does not pay: nothing is charged,
    and the only forced move in the fight is the Shove's own."""
    engine = _fight([WS, BORROW], foe_at=(4, 6), me_at=(3, 6))
    _act(engine, "Weight Shift: Body Heavying")
    stamina = engine.state.actors[ME].resources["resource:core.stamina"]
    start = len(engine.events)
    _act(engine, "Shove: Push 5 ft", FOE)
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina, "the AI was charged for a printed may"
    assert not [e for e in engine.events[start:] if e.event_type == "RESOURCE_SPENT"
                and str(e.source_definition_id or "").startswith("passive:tianxia.talent.gravity.weight_borrowing_throw")], \
        "the printed cost was charged without an answer"
    shove_only = _fight([WS], foe_at=(4, 6), me_at=(3, 6))
    _act(shove_only, "Weight Shift: Body Heavying")
    plain = len(shove_only.events)
    _act(shove_only, "Shove: Push 5 ft", FOE)
    assert [e.payload.get("destination") for e in engine.events[start:] if e.event_type == "MOVEMENT_COMMITTED"] == \
        [e.payload.get("destination") for e in shove_only.events[plain:] if e.event_type == "MOVEMENT_COMMITTED"], \
        "an un-paid throw moved the target"


def test_the_automatic_answer_to_the_throws_direction_is_always_a_legal_square():
    """What an AI fighter does with the same question (the shared forced-destination helper's documented fallback): the first square
    it was offered, which is by construction an open one on the creature's own level, reached by a legal forced route.

    The fighter *pays* and then leaves the direction unanswered -- a printed "you may spend 1" nobody answers is a decline
    (the test below), but a paid throw whose direction nobody answers takes the helper's fallback. The throw is identified by
    the movement that follows its own RESOURCE_SPENT, so the Shove's own five feet (which lands among these very squares, and
    moved last) can never be mistaken for it."""
    from combat.ext import forced_destination

    engine = _fight([WS, BORROW], foe_at=(4, 6), me_at=(3, 6))
    _act(engine, "Weight Shift: Body Heavying")
    foe = engine.state.actors[FOE]
    cells = forced_destination.routes(engine, foe, 5)
    assert cells and all(cell.z == foe.position.z for cell in cells), cells
    first_offered = next(iter(cells))
    stood_at = {"x": foe.position.x, "y": foe.position.y, "z": foe.position.z}
    stamina = engine.state.actors[ME].resources["resource:core.stamina"]
    start = len(engine.events)
    asked = _answers(engine, {"gravity_weight_borrowing": ["stamina"]}, silent=("gravity_weight_borrowing_move",))
    _act(engine, "Shove: Push 5 ft", FOE)  # the fighter pays; the direction is left to the helper's fallback
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina - 1, \
        "the printed cost was not paid, so this fight never bought a throw to move anything"
    question = next(r for r in asked if "gravity_weight_borrowing_move" in r["reaction_source_id"])
    offered = list(question["legal_option_ids"])
    assert offered, "the direction was never put to anyone, so nothing could answer it"
    assert offered[0] == f"cell:{first_offered.x},{first_offered.y}", \
        f"the documented fallback is the first square offered; the menu led with {offered[0]}"
    paid = next(index for index, event in enumerate(engine.events[start:], start) if event.event_type == "RESOURCE_SPENT")
    thrown = [e for e in engine.events[paid + 1:]
              if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE and (e.payload or {}).get("forced")]
    assert thrown, "a paid throw moved nothing, so the automatic answer never executed"
    landed = Position.model_validate(thrown[0].payload["destination"])
    assert landed == first_offered, \
        f"the AI answered a square it was never offered, or not the fallback: {landed} is not {first_offered}"
    assert thrown[0].payload["path"] == [{"x": stood_at["x"], "y": stood_at["y"]},
                                          {"x": landed.x, "y": landed.y}], \
        f"the automatic answer did not walk a legal forced route: {thrown[0].payload['path']}"
    others = [e for e in engine.events[start:] if e.event_type == "MOVEMENT_COMMITTED"
              and e.actor_id == FOE and (e.payload or {}).get("forced") and e is not thrown[0]]
    assert not [e for e in others if Position.model_validate(e.payload["destination"]) == first_offered], \
        "the Shove's own push, not the throw, landed on the fallback square"


def test_a_creature_without_weight_borrowing_throw_is_never_asked_about_it():
    """Checklist 3: the plug-in is inert. The same Shove with Body Heavying on and no talent raises no question at all."""
    engine = _fight([WS], foe_at=(4, 6), me_at=(3, 6), ask=True)
    _act(engine, "Weight Shift: Body Heavying")
    asked = _answers(engine, {})
    _act(engine, "Shove: Push 5 ft", FOE)
    assert not [r for r in asked if "weight_borrowing" in r["reaction_source_id"]]


# ------------------------------------------------------------------- the forced path a purchased throw is carried by
# AUTO67r1f1: the throw used to place the target with a single footprint step (combat/ext/needle.step_to), which skipped every
# forced-movement defense, reaction and per-step checkpoint, ran its own reduction hooks without the documented scope, offered no
# square at all above ground level, and read walking terrain costs. These cases drive a real throw at each of those.
DEFENDER = "actor:factory.auto67_defender"
STORE = "tianxia.subpath.body.returning_heaven_momentum_body.feature.store_the_collision"
VG = "TAL_VERDANT_GROWTH_"


def _defender_bundle(mids, *, actor_id=DEFENDER, cl=17, dc=16, ask=False):
    """A second Factory fighter owning exactly ``mids``: the creature the purchased throw is aimed at."""
    from tests.h1_support import sheet as factory_sheet

    document = factory_sheet(list(mids), cl=cl, dc=dc, primary="Stamina")
    document["identity"]["display_name"] = "Defender"
    document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    return compile_character(document, actor_id=actor_id, reaction_plan={"ask": True} if ask else None)


def _duel(mids, defender_mids=(), *, me_at=(3, 6), foe_at=(4, 6), ask_defender=False, battlefield=None, cl=17):
    """ME (team a, owning ``mids``) against DEFENDER (team b, owning ``defender_mids``), already on ME's turn, so the
    defender's own forced-movement abilities answer whatever the purchased throw does to it."""
    bundles = [_bundle(mids, cl=cl, dc=16)]
    if defender_mids:
        bundles.append(_defender_bundle(defender_mids, ask=ask_defender))
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO67-THROW", typed_bundles=tuple(bundles), battlefield=battlefield,
                                   roster_setup={"primary_actor_ids": [ME, DEFENDER],
                                                 "team_by_actor": {ME: "team:a", DEFENDER: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]},
                                                                         DEFENDER: {"x": foe_at[0], "y": foe_at[1]}}})
    from tests.hunt24_support import finish_direct_setup

    finish_direct_setup(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
    _ready(engine, ME)
    return engine


def _throw(engine, picks, *, defender=DEFENDER, grapple=False):
    """Body Heavying on, then a real Shove of ``defender`` and the purchased throw. ``picks`` answers the questions."""
    _act(engine, "Weight Shift: Body Heavying")
    if grapple:
        _answers(engine, {})
        script(engine, [1])  # the Grapple's contest save fails: the throw is 10 feet
        _act(engine, "Grapple", defender)
        _ready(engine)
        script(engine, [1])  # the Shove's contest save fails: the throw lands
    asked = _answers(engine, picks)
    start = len(engine.events)
    _act(engine, "Shove: Push 5 ft", defender)
    return asked, engine.events[start:]


def _paid_index(events):
    """Where the printed 1 CP or Stamina was charged for the throw, or None when nobody paid."""
    return next((index for index, event in enumerate(events)
                 if event.event_type == "RESOURCE_SPENT"
                 and str(event.source_definition_id or "").startswith("passive:tianxia.talent.gravity.weight_borrowing_throw")), None)


def _thrown(events, defender=DEFENDER):
    """The purchased throw's own movement, or ``[]`` when a defense stopped it: the first forced MOVEMENT_COMMITTED recorded
    after the printed 1 Stamina was paid for the throw. The throw resolves inside the Shove's own "after the save" moment, so it
    is recorded before the native push of that Shove."""
    paid = _paid_index(events)
    assert paid is not None, f"the printed cost was never paid: {[(e.event_type, e.source_definition_id) for e in events]}"
    return [e.payload for e in events[paid + 1:]
            if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == defender and (e.payload or {}).get("forced")][:1]


def test_a_thrown_creature_can_store_the_collision():
    """Review finding 1: Store the Collision ("You would be pushed, pulled, thrown ... Reaction and 1 Stamina, 15 feet less") is a
    defender's own defense against the purchased throw, not only against the Shove that bought it. The prompt names the ability, the
    action and the creature, and the throw is stopped by it."""
    engine = _duel([WS, BORROW], [STORE], ask_defender=True)
    foe = engine.state.actors[DEFENDER]
    stamina = foe.resources["resource:core.stamina"]
    asked, events = _throw(engine, {"store_the_collision_move": ["store"],
                                    "gravity_weight_borrowing_move": ["cell:4,7"],
                                    "gravity_weight_borrowing": ["stamina"]})
    window = next(r for r in asked if "store_the_collision_move" in r["reaction_source_id"])
    prompt = window["choice_trigger"]["prompt"]
    for phrase in ("Store the Collision", "Shove", foe.display_name):
        assert phrase in prompt, f"{phrase!r} is missing from the printed question: {prompt!r}"
    assert (foe.position.x, foe.position.y) != (4, 7), \
        f"Store the Collision did not stop the chosen square: {foe.position}"
    assert not [e.payload for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == DEFENDER
                and (e.payload or {}).get("destination") == {"x": 4, "y": 7}], "the chosen square was used anyway"
    assert foe.resources["resource:core.stamina"] == stamina - 1 and not foe.reaction_available, \
        "the printed Reaction and 1 Stamina were not paid"


def test_willow_bend_defense_reduces_a_purchased_throw_to_nothing():
    """Review finding 1: Willow-Bend Defense ("When you are pushed, pulled ... while touching a Living Medium, reduce the forced
    movement by 10 feet. If this reduces the movement to 0, place 1 Growth Mark on the creature ... that caused it") answers the
    throw, and its zero-distance Growth Mark is the printed reward."""
    from combat.ext import verdant_chassis

    engine = _duel([WS, BORROW], [VG + "WILLOW_BEND_DEFENSE", VG + "SEED_POUCH_METHOD"])
    foe, me = engine.state.actors[DEFENDER], engine.state.actors[ME]
    asked, events = _throw(engine, {"gravity_weight_borrowing_move": ["cell:4,7"],
                                    "gravity_weight_borrowing": ["stamina"]})
    question = next(r for r in asked if "gravity_weight_borrowing_move" in r["reaction_source_id"])
    assert "cell:4,7" in question["legal_option_ids"], \
        "a creature that shortens the movement offered no direction at all, so 'or knock it Prone' became the only option"
    assert _thrown(events) == [], "a 5-foot throw was not reduced to nothing by 10 feet"
    assert verdant_chassis.marks(me, foe) >= 1, \
        "the zero-distance Growth Mark was not placed on the creature that caused it"


def test_a_native_forced_movement_defense_shortens_the_purchased_throw():
    """Review finding 1: the ordinary forced_moved reaction (the engine's own FORCED_MOVEMENT checkpoint, armed by a typed
    "reduce that movement by N feet" row) answers the throw exactly as it answers a typed Shove: a 10-foot throw to a square two
    steps away is walked one step, and its receipt names the distance before and after."""
    engine = _duel([WS, BORROW], ["tianxia.talent.gravity.black_star_grip"])
    row = {"block": "generic", "feature_id": "AUTO67_TEST_BRACE", "name": "Brace against being thrown", "kind": "forced_moved",
           "costs": [], "numbers": {"pb": 4},
           "effects": [{"type": "forced_movement", "distance_ft": 5, "flat": 0, "applies_to": "self",
                        "evidence": "reduce that movement by 5 feet"}]}
    engine.typed_reaction_rows[DEFENDER] = [*(engine.typed_reaction_rows.get(DEFENDER) or []), row]
    engine.typed_actor_ids = {*engine.typed_actor_ids, DEFENDER}
    _asked, events = _throw(engine, {"gravity_weight_borrowing_move": ["cell:6,6"],
                                     "gravity_weight_borrowing": ["stamina"]}, grapple=True)
    paid = _paid_index(events)
    receipt = [e.payload for e in events[paid + 1:]
               if e.event_type == "REACTION_RESOLVED" and (e.payload or {}).get("checkpoint") == "FORCED_MOVEMENT"]
    assert receipt, "the native forced-movement checkpoint was never offered to the thrown creature"
    assert (receipt[0]["distance_before"], receipt[0]["distance_after"]) == (10, 5), receipt[0]
    walked = _thrown(events)
    assert walked and walked[0]["path"] == [{"x": 4, "y": 6}, {"x": 5, "y": 6}], \
        f"the throw was not shortened to the five feet the reaction left: {walked[0]['path'] if walked else None}"


def test_a_throw_reaches_a_creature_that_is_off_the_ground_and_keeps_its_height():
    """Review finding 2: "in any horizontal direction" is a choice at the target's own height. A hovering creature is offered
    squares at that height, and lands on the one it picked instead of dropping to the floor."""
    engine = _fight([WS, BORROW], foe_at=(4, 6), me_at=(3, 6))
    foe = _make_flyer(engine, hover=True)
    foe.position = foe.position.model_copy(update={"z": 1})
    _act(engine, "Weight Shift: Body Heavying")
    asked = _answers(engine, {"gravity_weight_borrowing_move": ["cell:5,7"],
                             "gravity_weight_borrowing": ["stamina"]})
    start = len(engine.events)
    _act(engine, "Shove: Push 5 ft", FOE)
    assert foe.position.z == 1, "the hovering creature was not still off the ground when the Shove resolved"
    question = next(r for r in asked if "gravity_weight_borrowing_move" in r["reaction_source_id"])
    assert "cell:5,7" in question["legal_option_ids"], f"no sideways square at that height was offered: {question['legal_option_ids']}"
    thrown = _thrown(engine.events[start:], FOE)
    assert thrown[0]["destination"] == {"x": 5, "y": 7, "z": 1}, \
        f"the elevated target lost its height: {[m['destination'] for m in thrown]}"
    assert thrown[0]["path"] == [{"x": 4, "y": 6, "z": 1}, {"x": 5, "y": 7, "z": 1}], thrown[0]["path"]


def test_a_throw_can_use_a_square_that_walking_would_never_reach():
    """Review finding 3: forced displacement spends no walking movement, so difficult ground does not shorten the printed reach.
    The Mist Courtyard's difficult square costs 10 feet to walk into, and is still a legal five-foot destination."""
    from combat.ext import needle

    document = json.loads((ROOT / "combat/rules/arenas/Mist_Courtyard.json").read_bytes())
    document.pop("retired", None)  # this is a sealed historical mechanics fixture
    difficult = {(entry["x"], entry["y"]) for region in document["terrain_regions"] if int(region.get("movement_cost") or 1) > 1
                 for entry in region["cells"]}
    assert difficult, "the built-in arena no longer has any costly ground"
    engine = _fight([WS, BORROW], me_at=(11, 12), foe_at=(12, 12), battlefield=document)
    foe = engine.state.actors[FOE]
    walked = {(cell.x, cell.y) for cell in needle.free_cells(engine, foe, 5)}
    assert difficult and not (difficult & walked), \
        f"this arena no longer costs more to walk into than to step into: {difficult & walked}"
    _act(engine, "Weight Shift: Body Heavying")
    asked = _answers(engine, {"gravity_weight_borrowing_move": ["cell:12,13"],
                             "gravity_weight_borrowing": ["stamina"]})
    start = len(engine.events)
    _act(engine, "Shove: Push 5 ft", FOE)
    question = next(r for r in asked if "gravity_weight_borrowing_move" in r["reaction_source_id"])
    assert "cell:12,13" in question["legal_option_ids"], \
        f"walking terrain cost the printed reach: {question['legal_option_ids']}"
    thrown = _thrown(engine.events[start:], FOE)
    assert thrown[0]["destination"] == {"x": 12, "y": 13}, \
        f"the chosen difficult square was not used: {[m['destination'] for m in thrown]}"


ORBIT = ["tianxia.talent.gravity.orbit_breaking_guard", "tianxia.talent.gravity.orbiting_guard",
         "tianxia.talent.gravity.gravitic_armor"]


def _orbit_duel(me_at=(3, 6), foe_at=(4, 6)):
    """ME (the attacker, team a) against DEFENDER (the Orbiting Guard, team b), already on ME's turn. The guard's printed pull of
    the attacker is the other user of the shared forced-destination helper."""
    engine = _duel([WS], ORBIT, me_at=me_at, foe_at=foe_at)
    engine.state.actors[DEFENDER].armor_class = 30  # so the printed "a creature misses you" trigger can answer at all
    _ready(engine, DEFENDER)
    _act(engine, "Orbiting Guard", actor_id=DEFENDER)
    _ready(engine, ME)
    return engine


def test_orbit_breaking_guard_pulls_an_airborne_attacker_along_the_native_forced_path():
    """Review findings 1 and 2 reach the other user of the shared helper: "Move the attacker 10 feet to an unoccupied space adjacent
    to you" is a forced move, so it is offered at the attacker's own height, keeps it, and is carried out by the engine's forced
    path (a recorded route) rather than a single footprint step."""
    engine = _orbit_duel()
    me = engine.state.actors[ME]
    me.fly_speed_ft, me.hover = 30, True  # a hovering attacker, so it is still off the ground when the miss is answered
    me.position = me.position.model_copy(update={"z": 1})
    asked = _answers(engine, {"gravity_orbit_breaking": ["pull"], "gravity_orbit_breaking_space": ["cell:4,7"]})
    script(engine, [1])  # the attacker's melee attack misses, so the printed trigger answers
    start = len(engine.events)
    _act(engine, "Fu (Short Axe) attack", DEFENDER)
    question = next((r for r in asked if "gravity_orbit_breaking_space" in r["reaction_source_id"]), None)
    assert question is not None, f"the guard was never asked where the attacker goes: {[r['reaction_source_id'] for r in asked]}"
    assert "cell:4,7" in question["legal_option_ids"], \
        f"an airborne attacker was offered no space next to the guard: {question['legal_option_ids']}"
    pulled = [e.payload for e in engine.events[start:]
              if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME and (e.payload or {}).get("forced")]
    assert pulled, "the guard did not move the attacker by a forced path"
    assert pulled[0]["destination"] == {"x": 4, "y": 7, "z": 1}, pulled[0]["destination"]
    assert pulled[0]["path"][-1] == {"x": 4, "y": 7, "z": 1} and len(pulled[0]["path"]) > 1, pulled[0]["path"]
    assert (me.position.x, me.position.y, me.position.z) == (4, 7, 1)


def test_orbit_breaking_guards_pull_is_reduced_by_the_attackers_own_defense():
    """Review finding 1: the pulled attacker's own reduction runs against this forced move too. Anchor Stance ("While Body Heavying
    is active, forced movement affecting you is 10 feet shorter") is exactly 10 feet, and the guard's printed pull is 10."""
    engine = _duel([WS, "TAL_GRAVITY_ANCHOR_STANCE"], ORBIT, me_at=(3, 6), foe_at=(4, 6))
    engine.state.actors[DEFENDER].armor_class = 30
    _ready(engine, DEFENDER)
    _act(engine, "Orbiting Guard", actor_id=DEFENDER)
    _ready(engine, ME)
    _act(engine, "Weight Shift: Body Heavying")
    asked = _answers(engine, {"gravity_orbit_breaking": ["pull"], "gravity_orbit_breaking_space": ["cell:4,7"]})
    script(engine, [1])  # the attacker's melee attack misses, so the printed trigger answers
    start = len(engine.events)
    _act(engine, "Fu (Short Axe) attack", DEFENDER)
    assert [r for r in asked if "orbit_breaking_space" in r["reaction_source_id"]], "the guard never asked where the attacker goes"
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (3, 6), \
        "the attacker was pulled 10 feet despite its own Anchor Stance"
    assert not [e.payload for e in engine.events[start:]
                if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME and (e.payload or {}).get("forced")], \
        "the attacker was pulled 10 feet despite its own Anchor Stance"


# ------------------------------------------------------------------------------------------------ the real table
def _table(tmp_path, mids, *, rival_mids=(), seed="AUTO67-TABLE", ask_rival=False):
    """Two Factory fighters on the real persisted table, both MANUAL: the Gravity fighter's own decisions are the player's, and the
    rival (``rival_mids``) owns whatever it needs to answer being thrown."""
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet as factory_sheet

    ids = [FACTORY_ACTOR_PREFIX + "auto67-gravity", FACTORY_ACTOR_PREFIX + "auto67-rival"]
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
    documents = [factory_sheet(list(mids), cl=17, dc=16, primary="Stamina", kit=kit),
                 factory_sheet(list(rival_mids), cl=17, dc=16, primary="Stamina")]
    for actor_id, document in zip(ids, documents):
        document["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    match_id = combat._finish_factory_match(
        [compile_character(document, actor_id=actor_id,
                           reaction_plan={"ask": True} if (index == 0 or (ask_rival and index == 1)) else None)
         for index, (actor_id, document) in enumerate(zip(ids, documents))], ids,
        {actor_id: ("team:a" if index == 0 else "team:b") for index, actor_id in enumerate(ids)},
        {actor_id: {"x": 3 + index, "y": 6} for index, actor_id in enumerate(ids)},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ids[0]], ids[1:],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed=seed,
        display_name="AUTO67f1 table", maximum_rounds=15)["match_id"]
    for _ in range(20):
        if table.state(match_id)["menu"]["actor_id"] == ids[0]:
            break
        _table_send(table, match_id, table.state(match_id)["menu"]["end_turn"])
    else:
        raise AssertionError("the Gravity fighter did not receive the opening turn")
    return combat, table, match_id, ids[0]


def _table_send(table, match_id, candidate_id, answers=()):
    state = table.state(match_id)
    return table.act(match_id, candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                     state["last_sequence"], list(answers))


def _table_press(table, match_id, label, answer=None):
    """Press the table button carrying ``label``, answering every question it puts to the player in turn. "End Turn" is the
    menu's own button rather than an action group. ``answer(question) -> option ids`` chooses among the printed options; the
    default takes the table's own first choice, so a committed turn never depends on a lucky die."""
    menu = table.state(match_id)["menu"]
    candidate_id = menu["end_turn"] if label == "End Turn" else next(
        option["candidate_id"] for group in menu["actions"] if label in group["label"] for option in group["options"])
    asked = []
    answers = []
    for _ in range(20):
        result = _table_send(table, match_id, candidate_id, answers)
        if result["status"] == "COMMITTED":
            return result, asked
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        asked.append(prompt)
        choice = prompt.get("choice") or {}
        picked = answer(prompt, choice) if answer else None
        reply = {**prompt["context"], "selection": "DECLINE"}
        if choice and (picked is None or picked is not False):
            reply.update(selection="USE", option_ids=list(picked or (choice.get("preferred")
                                                                     or [choice["options"][0]["id"]])[:1]))
        answers.append(reply)
    raise AssertionError("the table never committed the printed choice")


def test_reverse_gravity_steps_no_falling_damage_survives_a_table_commit_and_a_fresh_reload(tmp_path):
    """The recorded condition is integers and a name only, so a real table commit and a fresh service keep it: the engine's own
    falling reading still answers for the fighter after the fight has been written to disk and read back."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    _combat, table, match_id, gravity_id = _table(tmp_path, ["tianxia.talent.gravity.reverse_gravity_step"])
    _table_press(table, match_id, "Reverse Gravity Step")
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(match_id)
    actor = session.engine.state.actors[gravity_id]
    held = [c for c in actor.conditions.values() if c.condition_id == REVERSED]
    assert len(held) == 1, f"the printed Duration was not recorded on the fighter: {list(actor.conditions)}"
    assert held[0].expires_on == "END_OF_CURRENT_TURN", "the table would not know when normal gravity returns"
    assert falling.settings(actor)[1] is True, "the reloaded fighter is not reading as taking no falling damage"
    # The table's own presentation of the saved fight says what it does, in plain words.
    rows = next(a for a in TabletopService(fresh, tmp_path).state(match_id)["presentation"]["actors"]
                if a["entity_id"] == gravity_id)["conditions"]
    shown = next(row for row in rows if row["condition_id"] == REVERSED)
    label = str(shown.get("label") or shown.get("display_name") or "")
    assert "falling damage" in label and "condition:typed" not in label, f"the condition pill reads {label!r}"
    # And the expiry is still the engine's own: after a fresh reload, the end of the turn takes it off.
    _table_press(table, match_id, "End Turn")
    _table_press(table, match_id, "End Turn")
    actor = CombatService(ROOT, tmp_path)._load_session(match_id).engine.state.actors[gravity_id]
    assert not [c for c in actor.conditions.values() if c.condition_id == REVERSED], \
        "normal gravity did not return after the reload"
    assert falling.settings(actor)[1] is False


def test_the_table_asks_the_defender_about_a_purchased_throw_on_the_throwers_own_turn(tmp_path):
    """Checklist 7 and 9 at the level the review said it was missing: the real persisted table, both fighters MANUAL. Pressing
    Shove pauses the table three times on the Gravity fighter's own turn -- for its payment, for its direction, and for the rival's
    Store the Collision -- each question naming the ability, the action that caused it and the creature affected. Answering them
    commits, and a fresh service reads the result back off disk."""
    from combat.gate5_service import CombatService

    _combat, table, match_id, gravity_id = _table(tmp_path, [WS, BORROW], rival_mids=[STORE],
                                                 seed="AUTO67-THROW-T2", ask_rival=True)
    rival_id = match_id and "actor:factory.auto67-rival"
    _table_press(table, match_id, "Weight Shift: Body Heavying")

    def answer(prompt, choice):
        ids = [option["id"] for option in choice.get("options") or ()]
        if "store" in ids:
            return ["store"]
        return ["cell:4,7"] if "cell:4,7" in ids else None

    result, asked = _table_press(table, match_id, "Shove: Push 5 ft", answer)
    assert result["status"] == "COMMITTED"
    titles = [prompt["title"] for prompt in asked]
    assert titles == ["Weight-Borrowing Throw", "Weight-Borrowing Throw", "Store the Collision"], titles
    reactors = [prompt["reactor"] for prompt in asked]
    assert reactors[:2] == ["Gravity", "Gravity"] and reactors[2] == "Rival", reactors
    # Every printed question says which ability, which action and which creature.
    for prompt in asked:
        for phrase in (prompt["title"].split(":")[0], "Shove: Push 5 ft", "Rival"):
            assert phrase in prompt["trigger"], f"{phrase!r} is missing from {prompt['trigger']!r}"
    offered = [option["id"] for option in asked[1]["choice"]["options"]]
    assert "prone" in offered and {"cell:4,5", "cell:4,7"} <= set(offered), offered

    gravity, rival = (CombatService(ROOT, tmp_path)._load_session(match_id).engine.state.actors[a] for a in (gravity_id, rival_id))
    assert gravity.resources["resource:core.stamina"] == 29, "the printed 1 Stamina was not charged for the throw"
    assert rival.resources["resource:core.stamina"] == 29, "Store the Collision's printed 1 Stamina was not charged"
    assert not rival.reaction_available, "Store the Collision did not spend the printed Reaction"
    assert (rival.position.x, rival.position.y) != (4, 7), \
        f"the throw was committed to 4,7 anyway: {rival.position}"


# ------------------------------------------------------------------------------------------------ the claims the players read
def _record(mechanic_id):
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    return authority["mechanics"][mechanic_id]


def test_falling_hammers_first_thirty_feet_need_no_manual_rider():
    """The engine measures the protected distance, so no dice division is left as a ruling."""
    assert _record("TAL_GRAVITY_FALLING_HAMMER")["riders"] == []


def test_gravity_sense_keeps_an_honest_line_for_what_the_table_cannot_check():
    """The "+2 to identify or resist" bonus now answers only a check that resists a Gravity effect; the rider keeps the rest of
    the printed line visible instead of claiming a bonus the table does not grant."""
    riders = " ".join(_record("tianxia.talent.gravity.gravity_sense")["riders"])
    assert "sensing" in riders.lower() or "sense" in riders.lower()
    assert "identify" in riders.lower() or "spotting" in riders.lower()
    assert "ruling" in riders.lower(), riders


def test_the_printed_costs_of_every_gravity_technique_are_still_charged():
    """Checklist 11: the typing the lane added is still typed data, not free text, so no Gravity technique is free at the table."""
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    text = ""
    for mechanic_id in ("TAL_GRAVITY_FLIGHT_SUPPRESSION", "tianxia.talent.gravity.reverse_gravity_step",
                        "tianxia.talent.gravity.local_down", "tianxia.talent.gravity.meteoric_descent",
                        "tianxia.talent.gravity.falling_star_calamity"):
        cost = authority["mechanics"][mechanic_id]["cost"]
        assert [[part["resource"] for part in way] for way in cost] == [["cp"], ["stamina"]], (mechanic_id, cost)
        assert [way[0]["amount"] for way in cost][0] > 0, mechanic_id
        text += mechanic_id
    assert text  # the five printed prices this lane typed are all still typed


# ------------------------------------------------------------------------------------------------ the two flight capabilities
@pytest.mark.parametrize("data,hover,speed", [({"fly_speed_zero": 1}, False, 0),
                                              ({"fly_speed_zero": 1}, True, 0),
                                              ({"fly_speed_percent": 50}, False, 15),
                                              ({"fly_speed_zero": 1, "fly_speed_percent": 50}, True, 0),
                                              ({"flight_disabled": 1}, True, 0),
                                              ({}, True, 30)])
def test_the_engine_reads_the_gravity_flight_capabilities_its_way(data, hover, speed):
    """combat/flight.py's two Gravity additions: ``fly_speed_zero`` is "its Fly Speed becomes 0" (a creature that can Hover stays
    up), while the older ``flight_disabled`` remains "it cannot fly or hover at all"."""
    engine = _fight([WS])
    from combat import flight

    me = engine.state.actors[ME]
    me.fly_speed_ft, me.hover = 30, hover
    engine._apply_condition(me, "condition:typed.test_gravity_flight", "test:auto67.flight", ME, expires_on="UNTIL_REMOVED",
                            data=dict(data))
    profile = flight.profile(engine, me)
    assert profile.speed_ft == speed
    assert profile.hover is (hover and "flight_disabled" not in data), \
        f"Hover must survive a zeroed Fly Speed and go with flight_disabled: {profile}"
    if not speed:
        assert flight.step_allowed(engine, me, me.position, me.position.model_copy(update={"x": me.position.x + 1}),
                                  mode="fly") is False, "a creature with no Fly Speed was still allowed to fly a step"
