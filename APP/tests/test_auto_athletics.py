"""Athletics sphere automation, lane AUTO8 (round 24, branch int/r25x2-fix).

Every test here compiles a real character with the printed talent, runs it through the real
engine (Gate4ControllerEngine) and reads what the table did: the Speed it reports, the Cover it
offers, the condition it applies, the die it rolls. Each test fails on the typing this lane
replaced -- a talent that produced no action and no rider-typed effect, or a printed clause that
was a GM line.

Ownership and the printed text live in combat/ext/athletics.py (the plug-in),
combat/rules/feature_blocks.d/auto8-athletics.json (its passive rows) and
authority/typed_mechanics/reviewed_final.d/auto8-athletics.json (what the compiler reads).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import ext, motion, posture
from combat.directional_cover import cover_bonus
from combat.ext import forged_exhaustion, hold_still
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.flight import profile
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.auto8"
FOCUS = "resource:core.martial_focus"
SPHERE = "tianxia.sphere.athletics"
MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
SHORT_AXE_KIT = KIT
# "an appropriate polearm, rope, chain, whip, or tether item" (Helicopter Descent).
POLEARM_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang",
                                           "name": "Qiang (Spear)", "quantity": 1}]}}
ROPE_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.sheng_biao",
                                        "name": "Sheng Biao (Rope Dart)", "quantity": 1}]}}

AFTERIMAGE_TALENT = "TAL_ATHLETICS_AFTERIMAGE"
COORDINATED = "ATHLETICS_BASE_COORDINATED_MOVEMENT"
COURT = "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS"
DIZZYING = "TAL_ATHLETICS_DIZZYING_TUMBLE"
FLASH = "TAL_ATHLETICS_FLASH_STEP"
HEAVEN = "TAL_ATHLETICS_HEAVEN_TREADING_BODY"
HELICOPTER = "TAL_ATHLETICS_HELICOPTER_DESCENT"
MOVING = "TAL_ATHLETICS_MOVING_TARGET"
RAPID = "TAL_ATHLETICS_RAPID_MOTION"
SPARROWS = "TAL_ATHLETICS_SPARROW_S_PATH"
SPEED_BOOST = "TAL_ATHLETICS_SPEED_BOOST"
SWIFT = "TAL_ATHLETICS_SWIFT_MOVEMENT"
UNIMPEDED = "TAL_ATHLETICS_UNIMPEDED_POSITIONING"
UNIMPEDED_FOCUS = "TAL_ATHLETICS_MOBILITY"
WINGS = "TAL_ATHLETICS_POWERFUL_WINGS"


# ------------------------------------------------------------------------------------------------------- harness
def _sheet(talents, cl=10, walking_ft=30, extra_spheres=(), kit=KIT):
    spheres = [SPHERE, *extra_spheres]
    bases = [key for key, mech in MECH.items() if mech.get("sphere_id") in spheres and mech.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 80}, "speed": {"walking_ft": walking_ft},
            "technique_save_dc": 16, "technique_attack_bonus": 8},
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [kit],
        "spheres_and_talents": {"sphere_record_ids": spheres, "learned_talent_record_ids": list(talents),
                                "automatic_sphere_component_record_ids": bases},
    }


def _bundle(talents, **kw):
    return compile_character(_sheet(talents, **kw), actor_id=ME)


def _engine(talents, *, cl=10, walking_ft=30, foes=((4, 6),), speed_focus=1, kit=KIT):
    bundle = _bundle(talents, cl=cl, walking_ft=walking_ft, kit=kit)
    keys = [f"actor:factory.auto8.n{index}" for index in range(2, len(foes) + 1)]
    others = [compile_character(_sheet([], cl=cl), actor_id=key) for key in keys]
    teams = {ME: "team:a", AN: "team:b"}
    places = {ME: {"x": 3, "y": 6}, AN: {"x": foes[0][0], "y": foes[0][1]}}
    roster = [ME, AN]
    for index, (other, spot) in enumerate(zip(others, foes[1:]), start=2):
        key = f"actor:factory.auto8.n{index}"
        teams[key], places[key] = "team:b", {"x": spot[0], "y": spot[1]}
        roster.append(key)
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO8", typed_bundles=(bundle, *others),
                                   roster_setup={"primary_actor_ids": roster, "team_by_actor": teams,
                                                 "starting_positions": places})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me = engine.state.actors[ME]
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    me.resources[FOCUS] = speed_focus
    for key in keys:
        engine.state.actors[key].armor_class = -50
    engine.state.actors[AN].armor_class = -50
    return engine


def _me(engine):
    return engine.state.actors[ME]


def _foe(engine):
    return engine.state.actors[AN]


def _legal(engine):
    return sorted({candidate.display_name for candidate in engine.legal_candidates()})


def _use(engine, name, target=AN, destination=None):
    candidates = engine.legal_candidates()
    matches = [candidate for candidate in candidates if candidate.display_name == name]
    if not matches and name.startswith("Move to "):
        x, y = (int(value) for value in name.split()[-1].split(","))
        matches = [candidate for candidate in candidates
                   if candidate.destination is not None and candidate.destination.x == x and candidate.destination.y == y]
    assert matches, f"{name!r} is not a legal action; legal: {_legal(engine)}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto8-{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME,
                                       target_ids=candidate.target_ids or ((target,) if target and candidate.destination is None else ()),
                                       destination=destination or candidate.destination))
    return engine.events[before:]


def _walk(engine, x, y):
    _use(engine, f"Move to {x},{y}")
    return hold_still.moved_ft(engine, _me(engine))


def _give_turn(engine, actor_id=AN):
    """Hand the fight's turn to another fighter, exactly as ``end_turn`` would."""
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine._append_event("TURN_ENDED", "test", actor_id=ME)
    engine._system_start_turn()


def _end_turn(engine):
    """End this fighter's own turn through its legal candidate, so ``turn_end`` hooks run with an accepted intent."""
    candidate = next(candidate for candidate in engine.legal_candidates() if candidate.display_name == "End turn")
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="auto8-end-turn", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids or ()))
    return engine.events[before:]


def _scripted_d20(monkeypatch, wanted_for):
    """Test-only dice: ``wanted_for(actor_id, reason)`` -> the natural to show, or None; adjudication stays real."""
    from combat.gate2_rolls import DeterministicRollAuthority

    real_d20 = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        wanted = wanted_for(kwargs.get("actor_id"), str(kwargs.get("reason") or ""))
        while True:
            roll = real_d20(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)


def _next_turn(engine):
    """A fresh Action for this fighter inside the same fight (the printed trigger is 'during your turn')."""
    me = _me(engine)
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    me.movement_remaining_ft = engine._effective_speed(me)


def _passives(talents, feature, **kw):
    return [row for row in _bundle(talents, **kw)["typed_passives"]
            if row.get("feature_id") == feature and row.get("block") == "athletics"]


# ============================================================== already-automated passives, now typed as FULL
def test_coordinated_movement_returns_focus_for_a_dash_action_but_not_a_bonus_action_dash():
    """Whenever you take the Dash or Disengage Action as your Action, regain Martial Focus. This does not trigger
    when taking Dash or Disengage as a Bonus Action." It compiled no typed effect at all before this lane."""
    engine = _engine([COORDINATED, RAPID], speed_focus=0)
    _use(engine, "Dash")
    assert _me(engine).resources[FOCUS] == 1, "Dashing as your Action must regain Martial Focus"

    engine = _engine([COORDINATED, RAPID], speed_focus=0)
    _use(engine, "Rapid Motion: Dash")
    assert _me(engine).resources[FOCUS] == 0, "a Bonus Action Dash must not regain Martial Focus"


def test_swift_movement_and_unimpeded_positioning_apply_only_while_focus_is_held():
    """While holding Martial Focus, increase all movement Speeds by 10 feet" / "ignore nonmagical difficult terrain"."""
    engine = _engine([SWIFT, UNIMPEDED], speed_focus=1)
    assert engine._effective_speed(_me(engine)) == 40
    assert motion.ignores_difficult(engine, _me(engine)) is True
    _me(engine).resources[FOCUS] = 0
    assert engine._effective_speed(_me(engine)) == 30
    assert motion.ignores_difficult(engine, _me(engine)) is False


def test_mobility_makes_an_opportunity_attack_against_leaving_reach_disadvantage():
    """Opportunity attacks made against you for leaving a creature's reach have Disadvantage."""
    from combat.motion import attack_mode

    engine = _engine([UNIMPEDED_FOCUS])
    engine._typed_oa_attacker = AN
    assert attack_mode(engine, _foe(engine), _me(engine), melee=True, source="test") == "DISADVANTAGE"
    engine._typed_oa_attacker = None
    assert attack_mode(engine, _foe(engine), _me(engine), melee=True, source="test") is None


def test_afterimage_appears_after_twenty_feet_and_ends_at_the_start_of_its_owners_next_turn():
    """When you move more than 20 feet during your turn, leave one visible afterimage until the start of your next
    turn. An attacker that can see it rolls a d2, and on a 1 the afterimage is destroyed instead."""
    from combat import motion

    has_afterimage, strike_afterimage = motion.has_afterimage, motion.strike_afterimage

    engine = _engine([AFTERIMAGE_TALENT])
    assert _walk(engine, 5, 3) == 15
    assert not has_afterimage(_me(engine)), "15 feet has not earned the printed afterimage"
    assert _walk(engine, 7, 1) > 20
    assert has_afterimage(_me(engine))
    afterimage = next(value for value in _me(engine).conditions.values() if value.condition_id == motion.AFTERIMAGE)
    assert afterimage.expires_on == "START_OF_SOURCE_NEXT_TURN", "it lasts until the start of your next turn"
    strike_afterimage(engine, _me(engine), "passive:TAL_ATHLETICS_AFTERIMAGE")
    assert not has_afterimage(_me(engine)), "the printed afterimage is destroyed when it is struck"
    motion.after_move(engine, _me(engine), 25)
    assert not has_afterimage(_me(engine)), "the same turn's threshold does not recreate a destroyed image"


def test_rapid_motion_grants_a_bonus_action_dash():
    """Dash as a Bonus Action" compiled a granted button; this pins the button and its reach."""
    bundle = _bundle([RAPID])
    row = next(row for row in bundle["action_catalog"] if row["display_name"] == "Rapid Motion: Dash")
    assert row["economy"] == "BONUS_ACTION"
    assert row["parameters"]["typed"]["effects"][0]["distance_ft"] == "speed"


# ============================================================================================== Moving Target
def test_moving_target_gives_half_cover_after_twenty_feet_and_three_quarters_for_focus():
    """Moving Target: Half Cover against ranged attacks after more than 20 feet of movement this turn; at 40 feet,
    spending Martial Focus makes it Three-Quarters Cover instead."""
    engine = _engine([MOVING], walking_ft=50)
    assert ext.run("cover", engine, _foe(engine), _me(engine)) == []
    _walk(engine, 5, 3)
    assert ext.run("cover", engine, _foe(engine), _me(engine)) == []  # 15 feet is not enough
    assert _walk(engine, 7, 1) > 20
    assert ext.run("cover", engine, _foe(engine), _me(engine)) == [2]
    assert _walk(engine, 11, 1) >= 40
    assert "Moving Target: Three-Quarters Cover" in _legal(engine)
    events = _use(engine, "Moving Target: Three-Quarters Cover")
    assert _me(engine).resources[FOCUS] == 0
    assert [event.event_type for event in events].count("RESOURCE_SPENT") == 1
    assert ext.run("cover", engine, _foe(engine), _me(engine)) == [5]
    assert "Moving Target: Three-Quarters Cover" not in _legal(engine), "the printed upgrade is once per turn"


def test_moving_target_cover_ends_at_the_start_of_its_owners_next_turn():
    engine = _engine([MOVING], walking_ft=50)
    _walk(engine, 5, 3)
    _walk(engine, 7, 1)
    assert ext.run("cover", engine, _foe(engine), _me(engine)) == [2]
    engine.state.round_number += 1
    engine._append_event("TURN_ENDED", "test", actor_id=ME)
    engine._append_event("TURN_STARTED", "test", actor_id=ME)
    assert ext.run("cover", engine, _foe(engine), _me(engine)) == []


def test_a_second_purchase_of_moving_target_covers_melee_attacks_too():
    """Second Purchase: Take Moving Target a second time. Its cover applies against melee attacks as well."""
    import combat.ext.athletics as athletics

    melee = {"purpose": "attack", "ranged": False}
    ranged = {"purpose": "attack", "ranged": True}
    # A one-purchase fighter gets nothing against a melee ray; two purchases do.
    engine = _engine([MOVING])
    _walk(engine, 5, 3)
    _walk(engine, 7, 1)
    assert athletics.moving_target_melee(engine, _foe(engine), _me(engine), melee) is None
    assert athletics.moving_target_melee(engine, _foe(engine), _me(engine), ranged) is None
    engine.typed_passive_rows[ME] = [row for row in engine.typed_passive_rows[ME]
                                     if not (row.get("kind") == "moving_target" and row.get("block") == "athletics")]
    engine.typed_passive_rows[ME].append({"feature_id": MOVING, "block": "athletics", "kind": "moving_target",
                                          "purchases": 2, "numbers": {"save_dc": 16}})
    assert athletics.moving_target_melee(engine, _foe(engine), _me(engine), melee) == 2
    assert athletics.moving_target_melee(engine, _foe(engine), _me(engine), ranged) is None


# ====================================================================================== Heaven-Treading Body
def test_heaven_treading_body_grants_flight_hover_terrain_and_no_falling_damage():
    """Gain: Fly Speed equal to land Speed; Hover; ignore nonmagical difficult terrain; ... reduce falling damage
    to 0." None of these lines was automated before this lane."""
    engine = _engine([HEAVEN, SWIFT])
    capability = profile(engine, _me(engine))
    assert capability.speed_ft == engine._effective_speed(_me(engine)) and capability.hover is True
    assert motion.ignores_difficult(engine, _me(engine)) is True
    from combat.ext import athletics

    fall = type("Fall", (), {"actor_id": ME, "distance_ft": 200, "cause": "test"})()
    assert athletics.heaven_no_fall_damage(engine, _me(engine), 20, fall, None) == {"amount": 0, "land_prone": False}
    assert athletics.heaven_no_fall_damage(engine, _foe(engine), 20, fall, None) is None


def test_sparrows_path_grants_fly_speed_equal_to_half_the_base_land_speed():
    engine = _engine([SPARROWS], walking_ft=40)
    capability = profile(engine, _me(engine))
    assert capability.speed_ft == 20 and capability.hover is False


def test_powerful_wings_hover_only_while_the_fighter_has_its_own_flight():
    """If you possess a Fly Speed through physical wings, you may Hover." """
    engine = _engine([WINGS])
    assert profile(engine, _me(engine)).hover is False, "no wings, no Hover"
    engine = _engine([WINGS, SPARROWS])
    assert profile(engine, _me(engine)).hover is True
    engine = _engine([WINGS])
    engine._apply_condition(_me(engine), "condition:typed.featherfall", "test", ME, expires_on="END_OF_CURRENT_TURN",
                            data={"fall_speed_ft": 60, "fall_damage_immune": 1})
    assert profile(engine, _me(engine)).hover is False, "a borrowed safe descent is not physical wings"


# ================================================================================= Court of Ten Thousand Steps
def test_court_of_ten_thousand_steps_applies_every_clause_the_table_can_run():
    """For the duration: increase all movement Speeds by 20 feet; ignore nonmagical difficult terrain; stand from
    Prone without spending movement; move through allied spaces normally; ... once per turn after moving at least
    20 feet, regain Martial Focus; once per turn when a hostile creature misses you, move 5 feet without provoking
    Opportunity Attacks." Every clause after the Speed was a GM line before this lane."""
    import combat.ext.athletics as athletics

    engine = _engine([COURT], cl=15)
    before = engine._effective_speed(_me(engine))
    _use(engine, "Court of Ten Thousand Steps", target=None)
    assert engine._effective_speed(_me(engine)) == before + 20
    # Nonowning providers may return [] and registration order is not a contract.
    reasons = [row for result in ext.run("speed_explanation", engine, _me(engine)) for row in result]
    assert [row for row in reasons if row.get("source_id") == COURT] == [
        {"label": "Court of Ten Thousand Steps", "delta_ft": 20, "source_id": COURT}]
    assert motion.ignores_difficult(engine, _me(engine)) is True, "nonmagical difficult terrain is ignored"

    engine._apply_condition(_me(engine), "condition:core.prone", "test", ME, expires_on="STAND_UP")
    assert posture.standing_cost(engine, _me(engine)) == 0, "standing from Prone costs no movement"

    _me(engine).resources[FOCUS] = 0
    assert _walk(engine, 5, 3) == 15
    assert _me(engine).resources[FOCUS] == 0, "15 feet has not earned the printed Focus back"
    assert _walk(engine, 5, 0) >= 30
    assert _me(engine).resources[FOCUS] == 1, "moving at least 20 feet regains Martial Focus once per turn"


def test_court_of_ten_thousand_steps_moves_five_feet_after_a_hostile_miss(monkeypatch):
    """"once per turn when a hostile creature misses you, move 5 feet without provoking Opportunity Attacks."

    The move is real: the owner is not the creature whose turn it is, so it cannot come out of the active
    actor's movement menu, and the next turn's reset would have taken the allowance back."""
    import combat.ext.athletics as athletics

    engine = _engine([COURT], cl=15)
    _use(engine, "Court of Ten Thousand Steps", target=None)
    _scripted_d20(monkeypatch, lambda actor_id, reason: 1 if reason.startswith("ATTACK") else None)
    _me(engine).movement_remaining_ft = 0
    start = _me(engine).position
    _give_turn(engine)
    assert engine.state.current_actor_id == AN, "the owner's turn is over: this is an enemy turn"
    calls = _cell_answers(engine)
    strike = _attack(engine)
    assert "ATTACK_ROLLED" in [event.event_type for event in strike], "the hostile creature's attack missed"
    assert calls, f"the owner was not asked where to step: {calls}"
    assert _me(engine).position != start, "the owner really moved"
    assert engine.grid.distance_ft(_me(engine).position, start) <= 5, "the printed distance is 5 feet"
    assert _me(engine).movement_remaining_ft == 0, "the step came from the printed benefit, not the owner's budget"
    assert athletics.court_clauses_republished is not None


def test_court_of_ten_thousand_steps_offers_no_step_when_the_player_declines(monkeypatch):
    import combat.ext.athletics as athletics

    engine = _engine([COURT], cl=15)
    _use(engine, "Court of Ten Thousand Steps", target=None)
    _scripted_d20(monkeypatch, lambda actor_id, reason: 1 if reason.startswith("ATTACK") else None)
    start = _me(engine).position
    _give_turn(engine)
    _cell_answers(engine, decline=True)
    _attack(engine)
    assert _me(engine).position == start, "a player may decline the printed step"
    assert athletics.court_step_after_a_miss is not None


def _cell_answers(engine, decline=False):
    """Answer Court's 5-foot destination with a legal square other than where the fighter already stands."""
    from combat.gate2_runtime_models import ReactionDecision

    calls = []

    def choose(request):
        calls.append(request)
        if decline:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        mover = engine.state.actors[request["reactor_id"]]
        options = [option for option in request["legal_option_ids"] if option != f"cell:{mover.position.x},{mover.position.y}"]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(options[-1] if options else request["legal_option_ids"][0],)), None

    engine.set_reaction_provider(choose)
    return calls


def _attack(engine, actor_id=AN):
    """Have ``actor_id`` make its best melee attack on this fighter, and return the events it produced."""
    engine.state.current_actor_id = actor_id
    engine._active_intent = None
    candidates = engine.legal_candidates()
    attacker = engine.state.actors[actor_id]
    best = max((candidate for candidate in candidates if candidate.target_ids and ME in candidate.target_ids),
               key=lambda candidate: candidate.display_name.startswith("Attack"), default=None)
    if best is None:
        best = next((candidate for candidate in candidates if candidate.target_ids and ME in candidate.target_ids), None)
    assert best is not None, f"{attacker.display_name} has no attack: {_legal(engine)}"
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto8-strike-{actor_id}", decision_id=best.decision_id,
                                       candidate_id=best.candidate_id, state_version=best.state_version,
                                       actor_id=actor_id, target_ids=(ME,), destination=best.destination))
    return engine.events[before:]


def test_court_never_lends_or_takes_another_characters_terrain_condition():
    """F1: Court's clauses used the shared ``condition:typed.ignore_difficult`` id, so every other holder of that
    condition (Great Beast Charge, Thousand-Mile Legs, the Jade Sovereign) inherited free standing, and losing the
    stance took their terrain benefit away. Court now has its own condition id."""
    import combat.ext.athletics as athletics

    engine = _engine([COURT], cl=15, foes=((4, 6), (9, 9)))
    other = engine.state.actors["actor:factory.auto8.n2"]
    # Great Beast Charge's own shape: a Beastmastery rider's condition, not Court's.
    engine._apply_condition(other, "condition:typed.ignore_difficult", "TAL_BEASTMASTERY_GREAT_BEAST_CHARGE",
                            other.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Great Beast Charge: difficult terrain ignored"})
    assert motion.ignores_difficult(engine, other) is True
    assert ext.run("stand_cost", engine, other, 15) == [], "another talent's condition is not a free stand"

    _use(engine, "Court of Ten Thousand Steps", target=None)
    _me(engine).movement_remaining_ft = 0
    assert athletics.COURT_CLAUSES == "condition:typed.court_of_steps", "Court owns its condition id"
    assert athletics.COURT_CLAUSES != "condition:typed.ignore_difficult"
    assert ext.run("stand_cost", engine, _me(engine), 15) == [0], "Court's own stance grants the free stand"
    assert motion.ignores_difficult(engine, other) is True, "Court's stance never touches another creature's condition"
    athletics.court_ends_incapacitated(engine, _me(engine), {"actor_id": ME})
    assert motion.ignores_difficult(engine, other) is True, "ending the stance never takes another condition away"
    assert [condition.condition_id for condition in other.conditions.values()] == ["condition:typed.ignore_difficult"]


def test_court_clauses_are_republished_for_a_stance_a_saved_fight_already_held():
    """A fight stored while the stance was running carries no clause condition of this lane's shape; the printed
    clauses belong to the stance, so they come back at the next turn boundary."""
    import combat.ext.athletics as athletics

    engine = _engine([COURT], cl=15)
    _use(engine, "Court of Ten Thousand Steps", target=None)
    for instance_id in [key for key, condition in _me(engine).conditions.items()
                        if condition.condition_id == athletics.COURT_CLAUSES]:
        del _me(engine).conditions[instance_id]
    assert motion.ignores_difficult(engine, _me(engine)) is False
    athletics.court_clauses_republished(engine, _me(engine))
    assert motion.ignores_difficult(engine, _me(engine)) is True
    assert ext.run("stand_cost", engine, _me(engine), 15) == [0]


def test_court_regains_focus_on_one_continuous_twenty_foot_route():
    """F6: ``turn_moved_ft`` counts committed routes, and a route is committed only when it finishes, so one
    uninterrupted 20-foot walk looked like 5 feet at every checkpoint and never earned the printed Focus."""
    engine = _engine([COURT], cl=15, walking_ft=40, foes=((3, 13),))
    _use(engine, "Court of Ten Thousand Steps", target=None)
    _me(engine).resources[FOCUS] = 0
    assert _walk(engine, 3, 2) >= 20, "one uninterrupted route of at least 20 feet"
    assert _me(engine).resources[FOCUS] == 1, "one continuous 20-foot route regains Martial Focus once"


def test_court_focus_is_not_spent_by_a_turn_that_starts_with_the_focus_already_held():
    """F6: the once-per-turn benefit is not spent by a fighter who was already holding Martial Focus."""
    engine = _engine([COURT], cl=15, walking_ft=60, foes=((3, 13),))
    _use(engine, "Court of Ten Thousand Steps", target=None)
    _me(engine).resources[FOCUS] = 1  # the fighter already holds it: regaining means nothing
    assert _walk(engine, 3, 2) >= 20
    assert _me(engine).resources[FOCUS] == 1, "nothing to regain"
    _me(engine).resources[FOCUS] = 0
    assert _walk(engine, 3, 6) >= 20, "a second 20 feet of movement in the same turn"
    assert _me(engine).resources[FOCUS] == 1, "the unused once-per-turn benefit is still there"


def test_court_of_ten_thousand_steps_is_offered_once_per_short_rest():
    """"Use Limit: Once per short rest". A fight holds no rest, so the compiled use counter is the whole limit: this
    is what the base authority's GM line ("the GM ... tracks the once per short rest use limit") asked for, and it
    is enforced by the compiler's own ``resource:uses.<action>`` cost rather than by anything in this plug-in."""
    engine = _engine([COURT], cl=15)
    counter = next((key for key in _me(engine).resources if key.startswith("resource:uses.")
                    and COURT in key), None)
    assert counter, "the printed use limit compiles to a use counter"
    assert _me(engine).resource_maximums[counter] == 1
    assert "Court of Ten Thousand Steps" in _legal(engine)
    _use(engine, "Court of Ten Thousand Steps", target=None)
    assert _me(engine).resources[counter] == 0
    _next_turn(engine)
    assert "Court of Ten Thousand Steps" not in _legal(engine), "and it is not offered a second time"


def test_court_of_ten_thousand_steps_ends_when_its_owner_becomes_incapacitated():
    import combat.ext.athletics as athletics

    engine = _engine([COURT], cl=15)
    _use(engine, "Court of Ten Thousand Steps", target=None)
    assert any("court" in condition.condition_id for condition in _me(engine).conditions.values())
    athletics.court_ends_incapacitated(engine, _me(engine), {"actor_id": ME})
    assert not any("court" in condition.condition_id for condition in _me(engine).conditions.values())


# =============================================================================================== Speed Boost
def test_speed_boost_adds_ten_feet_to_a_dash_action_and_fifty_for_constitution_rounds():  # noqa: E501
    """When taking Dash or Disengage as an Action, move an additional 10 feet" and "expend Martial Focus to increase
    all movement Speeds by 50 feet for rounds equal to your Constitution modifier, minimum 1 round"."""
    engine = _engine([SPEED_BOOST], walking_ft=30)
    remaining = _me(engine).movement_remaining_ft
    _use(engine, "Dash")
    assert _me(engine).movement_remaining_ft == remaining + engine._effective_speed(_me(engine)) + 10

    engine = _engine([SPEED_BOOST], walking_ft=30)
    base = engine._effective_speed(_me(engine))
    events = _use(engine, "Speed Boost: +50 feet of Speed")
    assert _me(engine).resources[FOCUS] == 0
    assert engine._effective_speed(_me(engine)) == base + 50
    assert "Speed Boost: +50 feet of Speed" not in _legal(engine), "once per round"
    assert [event.event_type for event in events].count("RESOURCE_SPENT") == 1


def test_speed_boost_leaves_one_level_of_exhaustion_when_it_ends():
    import combat.ext.athletics as athletics

    engine = _engine([SPEED_BOOST])
    _use(engine, "Speed Boost: +50 feet of Speed")
    row = next(condition for condition in _me(engine).conditions.values() if condition.condition_id == "condition:typed.speed_boost")
    assert int(row.data["con_mod"]) == 3  # Constitution 16 -> +3 rounds
    athletics.speed_boost_exhaustion(engine, _me(engine), row)
    assert forged_exhaustion.level(_me(engine)) == 1


def test_speed_boost_cannot_start_above_two_levels_of_exhaustion():
    engine = _engine([SPEED_BOOST])
    forged_exhaustion.add(engine, _me(engine), 3, "test")
    assert "Speed Boost: +50 feet of Speed" not in _legal(engine)
    forged_exhaustion.set_level(engine, _me(engine), 2, "test")
    assert "Speed Boost: +50 feet of Speed" in _legal(engine)


# ================================================================================================ Flash Step
def test_flash_step_spends_focus_and_teleports_to_a_visible_legal_unoccupied_square():
    engine = _engine([FLASH])
    _me(engine).resources[FOCUS] = 0
    squares = [candidate for candidate in engine.legal_candidates() if candidate.display_name.startswith("Flash Step to ")]
    assert not squares, "without Martial Focus there is nothing to spend"
    _me(engine).resources[FOCUS] = 1
    squares = [candidate for candidate in engine.legal_candidates() if candidate.display_name.startswith("Flash Step to ")]
    assert squares, "Flash Step must offer its visible, legal, unoccupied destinations"
    far = max(squares, key=lambda candidate: candidate.destination.x)
    events = _use(engine, far.display_name)
    assert _me(engine).position == far.destination
    assert _me(engine).resources[FOCUS] == 0
    committed = next(event for event in events if event.event_type == "MOVEMENT_COMMITTED")
    assert committed.payload.get("teleport") is True, committed.payload


# ========================================================================================== Dizzying Tumble
def _tumble_engine():
    """This fighter stands between two hostiles, so leaving the square beside them names more than one creature."""
    return _engine([DIZZYING], walking_ft=40, foes=((4, 6), (2, 6)))


def test_dizzying_tumble_costs_ten_feet_and_rolls_a_wisdom_save_when_leaving_a_hostile():
    """When you exit a space adjacent to a hostile creature, spend 10 feet of movement to force that creature to make
    a Wisdom saving throw. Failed Save: The creature has Disadvantage on attack rolls until the end of your next turn."
    Driven through a real move, not the hook, so the printed choice and the printed cost are both on the path."""
    engine = _tumble_engine()
    me, foe = _me(engine), _foe(engine)
    before = me.movement_remaining_ft
    calls = _answers(engine, AN)
    _walk(engine, 3, 9)
    asked = _asked_for(calls, DIZZYING)
    assert asked, f"the fighter was not asked which creature to Dizzy: {calls}"
    assert sorted(asked[0]["legal_option_ids"]) == sorted([AN, "actor:factory.auto8.n2"])
    walked = hold_still.moved_ft(engine, me)
    assert before - me.movement_remaining_ft == walked + 10, "the walked distance plus the printed 10 foot cost"
    saves = [event for event in engine.events if event.event_type == "SAVE_ROLLED" and event.actor_id == AN]
    assert saves, "the chosen creature must make the printed Wisdom saving throw"
    assert json.dumps(saves[-1].payload).count("WIS") == 1, saves[-1].payload
    assert not any(condition.condition_id == "condition:typed.dizzy"
                   for condition in engine.state.actors["actor:factory.auto8.n2"].conditions.values())


def test_dizzying_tumble_can_be_declined_and_costs_nothing_when_declined():
    """F4: spending 10 feet of the player's own movement is their decision."""
    from combat.gate2_runtime_models import ReactionDecision

    engine = _tumble_engine()
    me = _me(engine)
    before = me.movement_remaining_ft
    engine.set_reaction_provider(lambda request: (ReactionDecision(
        checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
        reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None))
    _walk(engine, 3, 9)
    assert before - me.movement_remaining_ft == hold_still.moved_ft(engine, me), "a declined tumble costs nothing"
    assert not [event for event in engine.events if event.event_type == "SAVE_ROLLED"]


def test_dizzying_tumble_immunity_belongs_to_the_tumbler_who_saved():
    """F4: "immune to your Dizzying Tumble" is per caster, and an already-immune creature costs no movement."""
    engine = _tumble_engine()
    me, foe, ally = _me(engine), _foe(engine), engine.state.actors["actor:factory.auto8.n2"]
    engine._roll_save = lambda target, ability, dc, source_id, extra_mode=None: type("Roll", (), {"total": 1})()
    engine._apply_condition(foe, "condition:typed.dizzying_tumble_immune", DIZZYING, ally.entity_id,
                            expires_on="UNTIL_REMOVED", data={"against": ally.entity_id, "label": "immune"})
    before = me.movement_remaining_ft
    _answers(engine, AN)
    _walk(engine, 3, 9)
    assert any(condition.condition_id == "condition:typed.dizzy" for condition in foe.conditions.values()), \
        "another fighter's save does not protect it from this fighter's tumble"
    assert before - me.movement_remaining_ft == hold_still.moved_ft(engine, me) + 10

    # The same creature saved against this fighter: nothing is spent and nothing is rolled.
    engine = _tumble_engine()
    me, foe = _me(engine), _foe(engine)
    engine._apply_condition(foe, "condition:typed.dizzying_tumble_immune", DIZZYING, ME,
                            expires_on="UNTIL_REMOVED", data={"against": ME, "label": "immune"})
    before = me.movement_remaining_ft
    _answers(engine, AN)
    _walk(engine, 3, 9)
    assert before - me.movement_remaining_ft == hold_still.moved_ft(engine, me), "an immune creature costs no movement"
    assert not [event for event in engine.events if event.event_type == "SAVE_ROLLED"]


def test_dizzying_tumble_leaves_a_successful_save_immune(monkeypatch):
    """"Successful Save: It becomes immune to your Dizzying Tumble until you complete a short or long rest."""
    _scripted_d20(monkeypatch, lambda actor_id, reason: 20 if reason.startswith("SAVE:") else None)
    engine = _tumble_engine()
    me, foe = _me(engine), _foe(engine)
    _answers(engine, AN)
    _walk(engine, 3, 9)
    immune = [condition for condition in foe.conditions.values()
              if condition.condition_id == "condition:typed.dizzying_tumble_immune"]
    assert immune and immune[0].data["against"] == ME, "the immunity names the tumbler who earned it"
    assert not [condition for condition in foe.conditions.values() if condition.condition_id == "condition:typed.dizzy"]


# ================================================================ the coverage report counts this lane's typing
@pytest.mark.parametrize("mechanic", [COORDINATED, AFTERIMAGE_TALENT, UNIMPEDED, RAPID, COURT, MOVING, HEAVEN, SPARROWS,
                                      WINGS, HELICOPTER, FLASH, SPEED_BOOST, DIZZYING])
def test_every_athletics_mechanic_this_lane_owns_is_typed_with_no_gm_rider(mechanic):
    """The printed effect resolves in the engine, so the authority record carries effects and no GM line."""
    record = MECH[mechanic]
    assert record["effects"] or record.get("options"), f"{mechanic} has no typed effect"
    assert not record.get("riders"), f"{mechanic} still hands the player to the GM: {record.get('riders')}"


def test_dizzying_tumble_leaves_the_creature_dizzy_on_a_failed_save():
    """"Failed Save: The creature has Disadvantage on attack rolls until the end of your next turn." """
    from combat.typed_executor import condition_rules

    engine = _tumble_engine()
    me, foe = _me(engine), _foe(engine)
    engine._roll_save = lambda target, ability, dc, source_id, extra_mode=None: type("Roll", (), {"total": 1})()
    _answers(engine, AN)
    _walk(engine, 3, 9)
    dizzy = next((condition for condition in foe.conditions.values() if condition.condition_id == "condition:typed.dizzy"), None)
    # "until the end of *your* next turn" is the tumbler's turn. This assertion used to pin the holder's clock,
    # which ran the Disadvantage from the creature that was tumbled; the printed line is the tumbler's.
    assert dizzy is not None and dizzy.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"

    rows = {row.get("attacks_have") for row in condition_rules(foe)}
    assert "DISADVANTAGE" in rows, "its attacks are Disadvantage while Dizzy"


def test_dizzying_tumbles_dizzy_ends_at_the_tumblers_next_turn_end_not_the_targets():
    """The printed clock is the tumbler's: the Dizzy creature's own turn must neither end it early nor keep it."""
    engine = _tumble_engine()
    me, foe = _me(engine), _foe(engine)
    engine._roll_save = lambda target, ability, dc, source_id, extra_mode=None: type("Roll", (), {"total": 1})()
    _answers(engine, AN)
    _walk(engine, 3, 9)
    assert any(condition.condition_id == "condition:typed.dizzy" for condition in foe.conditions.values())

    _give_turn(engine, AN)  # the tumbled creature's whole turn comes and goes
    assert any(condition.condition_id == "condition:typed.dizzy" for condition in foe.conditions.values()), \
        "the Dizzy creature's own turn end must not end it"

    _give_turn(engine, ME)  # and the tumbler's next turn does
    _end_own_turn(engine)
    assert not [condition for condition in foe.conditions.values() if condition.condition_id == "condition:typed.dizzy"], \
        "it ends at the end of the tumbler's next turn, as printed"


def _end_own_turn(engine, actor_id=ME):
    """End ``actor_id``'s own turn through its legal candidate, so the printed turn end really runs."""
    _give_turn(engine, actor_id)
    candidate = next(candidate for candidate in engine.legal_candidates() if candidate.display_name == "End turn")
    engine.execute_intent(ActionIntent(intent_id="auto8-end-turn", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids or ()))


def test_helicopter_descent_records_a_capped_upright_descent_paid_with_focus_and_the_reaction():
    """"For rounds equal to your Proficiency Bonus: fall no faster than 60 feet per round; take no falling damage if you
    land before the effect ends; land on your feet." """
    import combat.ext.athletics as athletics
    from combat.falling import settings

    engine = _engine([HELICOPTER, SPARROWS], kit=POLEARM_KIT)
    me = _me(engine)
    me.position = Position(x=3, y=6, z=3)
    assert athletics.helicopter_gear(engine, me), "the printed polearm is in hand"
    _end_turn(engine)
    held = next(condition for condition in me.conditions.values()
                if condition.condition_id == "condition:typed.helicopter_descent")
    assert held.data["fall_speed_ft"] == 60 and held.data["fall_damage_immune"] == 1
    assert held.data["fall_lands_upright"] == 1
    assert me.resources[FOCUS] == 0, "the printed Martial Focus is spent"
    assert not me.reaction_available, "the printed Reaction is spent"
    assert settings(me) == (60, True, True), "combat/falling.py reads exactly this recorded data"


def test_helicopter_descent_needs_the_printed_polearm_rope_chain_whip_or_tether():
    """F10: "while wielding an appropriate polearm, rope, chain, whip, or tether item" was never checked, so a
    short axe bought the descent."""
    import combat.ext.athletics as athletics

    engine = _engine([HELICOPTER, SPARROWS], kit=SHORT_AXE_KIT)
    me = _me(engine)
    me.position = Position(x=3, y=6, z=3)
    assert athletics.helicopter_gear(engine, me) == [], "a short axe is none of the printed items"
    _end_turn(engine)
    assert not [c for c in me.conditions.values() if c.condition_id == "condition:typed.helicopter_descent"]
    assert me.resources[FOCUS] == 1 and me.reaction_available, "nothing was spent or offered"


def test_helicopter_descent_lets_the_player_decline_its_reaction_and_focus():
    """F10: the question offers "spend your Reaction and Martial Focus", so the player must be able to say no."""
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine([HELICOPTER, SPARROWS], kit=POLEARM_KIT)
    me = _me(engine)
    me.position = Position(x=3, y=6, z=3)
    asked = []

    def decline(request):
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine.set_reaction_provider(decline)
    _end_turn(engine)
    assert asked, "the printed question must be asked"
    assert asked[0]["extension_choice"]["allow_decline"] is True
    assert not [c for c in me.conditions.values() if c.condition_id == "condition:typed.helicopter_descent"]
    assert me.resources[FOCUS] == 1 and me.reaction_available, "a declined question spends nothing"


def test_helicopter_descent_is_not_offered_on_the_ground():
    import combat.ext.athletics as athletics

    engine = _engine([HELICOPTER, SPARROWS], kit=POLEARM_KIT)
    athletics.helicopter_descent(engine, _me(engine))
    assert not _me(engine).conditions, "it needs the printed end of a turn in the air"
    assert _me(engine).resources[FOCUS] == 1


def test_a_fighter_without_an_athletics_row_is_untouched_by_every_hook():
    """Nothing here fires for a character that owns none of these talents (checklist: plug-ins are inert for non-owners)."""
    import combat.ext.athletics as athletics

    engine = _engine([])
    me = _me(engine)
    assert athletics.rows_of(engine, me) == {}
    assert not athletics._court(engine, me)
    assert athletics._moving_target(engine, me) == 0
    assert ext.run("cover", engine, _foe(engine), me) == []
    assert profile(engine, me).speed_ft == 0 and profile(engine, me).hover is False
    assert sum(int(value) for value in ext.run("speed", engine, me)) == 0
    assert athletics.helicopter_descent(engine, me) is None
    assert athletics.heaven_no_fall_damage(engine, me, 20, None, None) is None
    assert [row for reply in ext.run("speed_explanation", engine, me) for row in reply] == []
    assert [row for reply in ext.run("ability_check_mode", engine, me, "STR", "Athletics", None) for row in reply] == []
    assert [row for reply in ext.run("opportunity_allowed", engine, _foe(engine), me) for row in reply] == []
    assert [row for reply in ext.run("jump_bonus_ft", engine, me) for row in reply] == []
    assert [row for reply in ext.run("jump_ability", engine, me) for row in reply] == []
    assert athletics.meridian_threading(engine, me, "ACTION", "system:combat.dash") is None
    assert athletics.one_breath_focus(engine, me, me.position, me.position, None) is None
    assert athletics.flowing_pursuit_no_oa(engine, _foe(engine), me) is None
    assert athletics.athletics_jump_bonus_ft(engine, me) is None
    assert athletics.mighty_conditioning_jump(engine, me) is None
    assert athletics.meridian_check_mode(engine, me, "STR", "Athletics", None) is None
    assert athletics.meridian_free_stand(engine, me, 15) is None
    assert athletics._pursuit_target(engine, me, {"close_ft": 20}) is None
    assert not any(condition.condition_id.startswith("condition:typed.meridian")
                   for condition in me.conditions.values())


# ================================================================================ Meridian-Threading Dash
MERIDIAN = "TAL_ATHLETICS_MERIDIAN_THREADING_DASH"
PURSUIT = "TAL_ATHLETICS_FLOWING_PURSUIT"
ONE_BREATH = "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS"
VAULTER = "TAL_ATHLETICS_POLEARM_VAULTER"
MIGHTY = "TAL_ATHLETICS_MIGHTY_CONDITIONING"
GRAPPLED = "condition:typed.grappled"


def _answers(engine, wanted):
    """Answer this fighter's first choice whose options include ``wanted``; record every question asked."""
    from combat.gate2_runtime_models import ReactionDecision

    calls = []

    def choose(request):
        calls.append(request)
        options = list(request["legal_option_ids"])
        option = wanted if wanted in options else (options[0] if options else "")
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(option,)), None

    engine.set_reaction_provider(choose)
    return calls


def _asked_for(calls, feature):
    """The requests whose Needle choice carried this printed feature id (combat/ext/needle.py _options)."""
    return [request for request in calls
            if (request.get("choice_trigger") or {}).get("feature_id") == feature
            or (request.get("extension_choice") or {}).get("feature_id") == feature]


def test_meridian_threading_dash_free_step_when_coordinated_movement_restores_focus():
    """When Coordinated Movement restores Martial Focus, choose one: move 10 feet without provoking Opportunity
    Attacks. Every line of this talent was a GM line before this lane."""
    import combat.ext.athletics as athletics

    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0)
    calls = _answers(engine, "step")
    _use(engine, "Dash")
    assert _me(engine).resources[FOCUS] == 1, "Coordinated Movement still restores the Focus"
    assert _me(engine).turn_flags["oa_free_ft"] == 10, "the printed 10 feet cost no movement and no Opportunity Attacks"
    assert _asked_for(calls, MERIDIAN), f"the printed choice was not asked: {calls}"
    assert not [row for row in _passives([MERIDIAN], MERIDIAN) if row.get("kind") != "meridian_threading"]
    assert athletics.MERIDIAN_OPTIONS == ("step", "stand", "grapple", "check")


def test_meridian_threading_dash_stands_from_prone_without_spending_movement():
    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0)
    _answers(engine, "stand")
    engine._apply_condition(_me(engine), "condition:typed.prone", "test", AN, expires_on="STAND_UP", data={})
    events = _use(engine, "Dash")
    assert not [c for c in _me(engine).conditions.values() if c.condition_id == "condition:typed.prone"]
    stood = [event for event in events if event.event_type == "STOOD_UP"]
    assert stood, "combat.posture.stand_up recorded the stand"
    assert stood[0].payload["cost_ft"] == 0, f"{stood[0].payload}: the printed stand costs no movement"
    # F9: the printed benefit is the one stand. A second stand is not free, and no standing pill is left behind.
    assert ext.run("stand_cost", engine, _me(engine), 15) == [], "one stand, not a standing entitlement"
    assert not [c for c in _me(engine).conditions.values() if c.condition_id == "condition:typed.meridian_free_stand"]


def test_meridian_threading_dash_ends_one_grapple():
    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0)
    _answers(engine, "grapple")
    engine._apply_condition(_me(engine), GRAPPLED, "combat:grapple", AN, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 15, "by": AN})
    events = _use(engine, "Dash")
    assert not [c for c in _me(engine).conditions.values() if c.condition_id == GRAPPLED], "the printed hold ended"
    assert "CONDITION_REMOVED" in [event.event_type for event in events]


def test_meridian_threading_dash_ends_exactly_one_of_two_grapples():
    """F8: ``_remove_condition`` removes every instance of a condition id, so two grapplers lost both holds."""
    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0, foes=((4, 6), (5, 6)))
    ally = "actor:factory.auto8.n2"
    engine._apply_condition(_me(engine), GRAPPLED, "combat:grapple", AN, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 15, "by": AN})
    engine._apply_condition(_me(engine), GRAPPLED, "combat:grapple", ally, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 15, "by": ally})
    holds = {instance_id for instance_id, condition in _me(engine).conditions.items()
             if condition.condition_id == GRAPPLED}
    assert len(holds) == 2
    calls = _answers(engine, "grapple")
    _use(engine, "Dash")
    left = {instance_id for instance_id, condition in _me(engine).conditions.items()
            if condition.condition_id == GRAPPLED}
    assert len(left) == 1, f"exactly one hold ended, not both: {left | holds}"
    prompts = [request for request in calls if "meridian_grapple" in str(request.get("reaction_source_id") or "")]
    assert prompts, f"the fighter was not asked which hold to end: {calls}"
    assert len(prompts[0]["legal_option_ids"]) == 2, "both holds are on offer"


def test_meridian_threading_dash_gives_advantage_on_one_athletics_or_acrobatics_check():
    """gain Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check before the end of your next
    turn: the shared ability_check_mode seam every such check already reads."""
    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0)
    _answers(engine, "check")
    _use(engine, "Dash")
    held = [c for c in _me(engine).conditions.values() if c.condition_id == "condition:typed.meridian_check"]
    assert held and held[0].expires_on == "END_OF_HOLDER_NEXT_TURN"
    assert ext.run("ability_check_mode", engine, _me(engine), "STR", "Athletics", None) == ["ADVANTAGE"]
    assert ext.run("ability_check_mode", engine, _me(engine), "DEX", "Acrobatics", None) == []
    assert ext.run("ability_check_mode", engine, _me(engine), "WIS", "Insight", None) == [], "one printed check only"
    assert ext.run("ability_check_mode", engine, _foe(engine), "STR", "Athletics", None) == []


def test_meridian_threading_dash_does_not_fire_without_the_printed_focus_restoration():
    engine = _engine([COORDINATED, MERIDIAN], speed_focus=1)  # the Focus is already held, so nothing restores it
    calls = _answers(engine, "step")
    _use(engine, "Dodge")
    assert not _asked_for(calls, MERIDIAN), "an ordinary Action is not Coordinated Movement's trigger"
    assert _me(engine).turn_flags.get("oa_free_ft") is None


def test_meridian_threading_dash_survives_a_fellow_talents_own_dash_grant():
    """F7: the stamp was "this grant is the newest event", and Speed Boost's Dash grant ("move an additional 10
    feet") is recorded between Coordinated Movement's Focus and action_completed, so a character owning both talents
    lost the printed choice entirely."""
    import combat.ext.athletics as athletics

    calls_seen = []

    def build(talents):
        engine = _engine(talents, speed_focus=0)
        calls = _answers(engine, "step")
        calls_seen.append((engine, calls))
        return engine, calls

    plain, plain_calls = build([COORDINATED, MERIDIAN])
    _use(plain, "Dash")
    assert _me(plain).resources[FOCUS] == 1

    engine, calls = build([COORDINATED, MERIDIAN, SPEED_BOOST])
    before = _me(engine).movement_remaining_ft
    _use(engine, "Dash")
    assert _me(engine).movement_remaining_ft > before, "Speed Boost's own Dash grant still happens"
    assert _me(engine).resources[FOCUS] == 1, "Coordinated Movement still restores the Focus"
    assert _asked_for(calls, MERIDIAN), f"the printed choice was lost beside another talent's grant: {calls}"
    assert _me(engine).turn_flags["oa_free_ft"] == 10
    assert athletics.MERIDIAN_OPTIONS == ("step", "stand", "grapple", "check")


def test_meridian_threading_dash_is_not_offered_again_by_a_later_dash_that_restores_nothing():
    """R1 (independent review AUTO8r1): the stamp that recognises Coordinated Movement's Focus named only the
    fighter and the Action definition, and it was kept on the engine rather than in the fight, so it outlived the
    resolution that wrote it. A fighter who ended a turn still holding the Focus that Dash had restored left the
    stamp matching, and the next Dash -- in which ``motion.after_action`` correctly restores nothing -- was offered
    the printed choice a second time. A Focus that was never restored cannot award a benefit."""
    import combat.ext.athletics as athletics

    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0)
    calls = _answers(engine, "step")
    _use(engine, "Dash")
    assert _me(engine).resources[FOCUS] == 1, "the first Dash restored Martial Focus"
    assert _asked_for(calls, MERIDIAN), f"the printed choice was offered on the Dash that restored it: {calls}"
    assert athletics.used_this_turn(engine, _me(engine), "meridian_threading")

    # End that turn keeping the Focus, which is a thing a player may do, and take a later one.
    _end_turn(engine)
    _give_turn(engine, ME)
    engine.state.round_number += 1
    _next_turn(engine)
    assert _me(engine).resources[FOCUS] == 1, "the Focus was kept, so this next Dash restores nothing"
    assert not athletics.used_this_turn(engine, _me(engine), "meridian_threading"), \
        "the once-per-turn gate really has reset for the later turn"

    calls = _answers(engine, "step")
    _use(engine, "Dash")
    assert not _asked_for(calls, MERIDIAN), f"a Dash that restored no Focus was offered the choice again: {calls}"
    assert _me(engine).turn_flags.get("athletics_used:meridian_threading") is None, \
        "and nothing was marked as used by a grant that never happened"
    assert _me(engine).turn_flags.get("oa_free_ft") is None, "so no printed movement was granted either"


def test_meridian_threading_dash_ends_the_hold_whose_holder_is_no_longer_in_the_fight():
    """R4 (independent review AUTO8r1): the holder was looked up in ``engine.state.actors`` and fell back to the
    raw ``source_actor_id`` string, so a hold recorded against a creature that is no longer in the fight was then
    read as if it were a creature (``creature.active``) and raised AttributeError -- after the condition had
    already been removed, which aborted the Action mid-resolution. The hold is still ended; only the log's subject
    goes unnamed, exactly as the choice's own label already promises."""
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine([COORDINATED, MERIDIAN], speed_focus=0)
    gone = "actor:factory.auto8.gone"
    engine._apply_condition(_me(engine), GRAPPLED, "combat:grapple", AN, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 15, "by": AN})
    engine._apply_condition(_me(engine), GRAPPLED, "combat:grapple", gone, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 15, "by": gone})
    named_hold = next(instance_id for instance_id, condition in _me(engine).conditions.items()
                      if condition.condition_id == GRAPPLED and condition.source_actor_id == AN)
    missing_hold = next(instance_id for instance_id, condition in _me(engine).conditions.items()
                       if condition.condition_id == GRAPPLED and condition.source_actor_id == gone)
    assert gone not in engine.state.actors, "the holder really is absent from the fight"

    prompts = []

    def choose(request):
        prompts.append(request)
        options = list(request["legal_option_ids"])
        picked = "grapple" if "grapple" in options else (
            missing_hold if missing_hold in options else options[0])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(picked,)), None

    engine.set_reaction_provider(choose)
    events = _use(engine, "Dash")  # must not raise

    left = {instance_id for instance_id, condition in _me(engine).conditions.items()
            if condition.condition_id == GRAPPLED}
    assert left == {named_hold}, f"exactly the selected hold ended: {left}"
    removed = [event for event in events
               if event.event_type == "CONDITION_REMOVED" and event.payload.get("instance_id") == missing_hold]
    assert removed, f"the unnamed hold is the one that was ended: {[e.payload for e in events]}"
    # The bug did not raise out of the action: the ext runner catches a failing hook, records a GM_RIDER and
    # abandons the rest of it. So the symptom is the *missing* completion, and that is what is asserted here.
    assert not [event for event in events if event.event_type == "GM_RIDER"], \
        f"a plug-in hook failed mid-resolution: {[e.payload for e in events if e.event_type == 'GM_RIDER']}"
    assert any("breaks free of the grapple" in str(event.payload.get("log") or "") for event in events), \
        f"and the printed benefit was reported in full: {[e.payload for e in events]}"
    assert any("meridian_grapple" in str(request.get("reaction_source_id") or "") for request in prompts), \
        "the fighter still chose between the two holds"
    assert _asked_for(prompts, MERIDIAN), "and was asked for the printed benefit first"


def test_courts_free_step_is_not_provoked_by_any_enemy_not_only_the_one_that_missed(monkeypatch):
    """R2 (independent review AUTO8r1): the printed clause is "move 5 feet without provoking Opportunity Attacks",
    without limiting that protection to the attacker, but only the attacker's id was handed to the shared
    granted-movement path. This fighter stands beside two enemies and steps out of *both* their reaches, so the
    second one -- which has its Reaction and would otherwise attack -- must be left with nothing to do."""
    import combat.ext.athletics as athletics
    from combat.gate2_runtime_models import ReactionDecision

    engine = _engine([COURT], cl=15, foes=((4, 6), (4, 7)))
    second = "actor:factory.auto8.n2"
    _use(engine, "Court of Ten Thousand Steps", target=None)
    _scripted_d20(monkeypatch, lambda actor_id, reason: 1 if reason.startswith("ATTACK") else None)
    _me(engine).movement_remaining_ft = 0
    _give_turn(engine)
    second_actor = engine.state.actors[second]
    second_actor.reaction_available = True
    assert engine.grid.distance_ft(second_actor.position, _me(engine).position) <= 5, \
        "the second enemy starts in reach, so the step leaves its reach"

    def step_out(request):
        """Take the square west of the fighter: out of reach of both enemies, one square."""
        options = [option for option in request["legal_option_ids"] if option.startswith("cell:")]
        away = f"cell:{_me(engine).position.x - 1},{_me(engine).position.y}"
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(away if away in options else options[-1],)), None

    engine.set_reaction_provider(step_out)
    _attack(engine)

    assert engine.grid.distance_ft(_me(engine).position, second_actor.position) > 5, \
        "the fighter really stepped out of the second enemy's reach"
    assert second_actor.reaction_available, "the second enemy still had its Reaction: it provoked nothing"
    assert not [event for event in engine.events if event.event_type == "REACTION_RESOLVED"
                and event.actor_id == second], "the second enemy made no Opportunity Attack"
    assert sorted(athletics._opportunity_reactors(engine, _me(engine))) == sorted([AN, second]), \
        "both enemies are the reactors the printed clause covers"


# ============================================================================================= Flowing Pursuit
def test_flowing_pursuit_asks_after_twenty_feet_closed_toward_one_creature():
    engine = _engine([PURSUIT], walking_ft=50, foes=((3, 13), (10, 10)))
    calls = _answers(engine, "ac")
    _walk(engine, 3, 8)  # straight at the foe, but only 10 feet
    _use(engine, "Dodge")
    assert not _asked_for(calls, PURSUIT), "10 feet has not closed the printed distance"
    _walk(engine, 3, 10)
    _next_turn(engine)
    _use(engine, "Dodge")
    assert _asked_for(calls, PURSUIT), f"the printed choice was not asked: {calls}"
    guard = next(c for c in _me(engine).conditions.values() if c.condition_id == "condition:typed.ac_against")
    assert guard.data == {"against": AN, "amount": 2,
                          "label": f"+2 Armor Class against {_foe(engine).display_name}"}
    assert guard.expires_on == "START_OF_SELF_NEXT_TURN", "the printed +2 AC lasts until the start of your next turn"
    answered = [reply for reply in ext.run("hit_response", engine, _foe(engine), _me(engine), {}, 14, 14, 15)
                if reply is not None]
    assert answered == [(17, False)], "that creature's attack now needs 17 to hit"


def test_flowing_pursuit_ignores_that_creatures_opportunity_attacks_for_the_rest_of_the_turn():
    engine = _engine([PURSUIT], walking_ft=50, foes=((3, 13), (10, 10)))
    _answers(engine, "no_oa")
    _walk(engine, 3, 10)
    _next_turn(engine)
    _use(engine, "Dodge")
    held = [c for c in _me(engine).conditions.values() if c.condition_id == "condition:typed.flowing_pursuit_no_oa"]
    assert held and held[0].data["against"] == AN
    assert ext.run("opportunity_allowed", engine, _foe(engine), _me(engine)) == [False], "that creature's OAs are ignored"
    ally = engine.state.actors["actor:factory.auto8.n2"]
    import combat.ext.athletics as athletics

    assert athletics.flowing_pursuit_no_oa(engine, ally, _me(engine)) is None, "only the creature moved toward"
    assert held[0].expires_on == "END_OF_CURRENT_TURN", "the printed benefit lasts the rest of that turn only"
    engine.end_turn()
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert athletics.flowing_pursuit_no_oa(engine, _foe(engine), _me(engine)) is None


def test_flowing_pursuit_jump_option_reaches_five_feet_higher_through_the_documented_jump_seam():
    """add 5 feet to one jump: combat/flight.py jump_score reads the documented jump_bonus_ft seam, and this fighter's
    choice is what feeds it. A two-cell approach has no run-up, so the printed +5 feet is one whole extra step."""
    import combat.ext.athletics as athletics
    from combat.flight import jump_score, jump_steps

    approach = (Position(x=6, y=6, z=0), Position(x=5, y=6, z=0))
    plain = _engine([], walking_ft=50)
    assert jump_steps(plain, _me(plain), approach) == max(0, 3 + (_me(plain).strength_score - 10) // 2) // 10

    engine = _engine([PURSUIT], walking_ft=50, foes=((3, 13), (10, 10)))
    _answers(engine, "jump")
    _walk(engine, 3, 10)
    _next_turn(engine)
    _use(engine, "Dodge")
    assert jump_score(engine, _me(engine)) == (_me(engine).strength_score, 5)
    reach = max(0, 3 + (_me(engine).strength_score - 10) // 2)
    assert jump_steps(engine, _me(engine), approach) == (reach + 5) // 10 > jump_steps(plain, _me(plain), approach)
    ally = engine.state.actors["actor:factory.auto8.n2"]
    assert jump_score(engine, ally) == (ally.strength_score, 0), "another fighter's jump is untouched"
    assert athletics.athletics_jump_bonus_ft is not None


def test_flowing_pursuit_jump_bonus_is_one_jump_and_is_spent_by_that_jump():
    """F9: the printed benefit is "+5 feet to *one* jump"; it was a standing condition that every later jump of the
    turn could use, and nothing consumed it on execution."""
    import combat.ext.athletics as athletics
    from combat.flight import jump_score

    engine = _engine([PURSUIT], walking_ft=50, foes=((3, 13), (10, 10)))
    _answers(engine, "jump")
    _walk(engine, 3, 10)
    _next_turn(engine)
    _use(engine, "Dodge")
    assert jump_score(engine, _me(engine))[1] == 5
    first = _jump_candidates(engine)
    assert first, "the printed bonus must reach the real jump menu"
    _use(engine, max(first, key=lambda candidate: candidate.destination.z).display_name)
    assert jump_score(engine, _me(engine))[1] == 0, "'one jump' is one jump"
    assert not athletics.athletics_jump_bonus_ft(engine, _me(engine))
    assert not [c for c in _me(engine).conditions.values() if c.condition_id == athletics.PURSUIT_JUMP]
    # Quoting the menu never spends it: a second menu is built and read, not consumed.
    _next_turn(engine)
    assert jump_score(engine, _me(engine))[1] == 0, "it lasted the rest of that turn only"


# =========================================================== One Breath, Ten Thousand Steps (Focus per 20 feet)
def test_one_breath_returns_martial_focus_for_every_twenty_feet_you_move():
    engine = _engine([ONE_BREATH], cl=15, walking_ft=50)
    _use(engine, "One Breath, Ten Thousand Steps")
    assert _me(engine).resources[FOCUS] == 0, "the printed Martial Focus is the cost"
    assert _walk(engine, 4, 7) == 10
    assert _me(engine).resources[FOCUS] == 0, "ten feet is not yet twenty"
    assert _walk(engine, 6, 7) >= 20
    assert _me(engine).resources[FOCUS] == 1, "the printed Focus returns at every 20 feet"


# =============================================================================================== Jump queries
def test_polearm_vaulter_buys_five_feet_of_jump_height_with_a_bonus_action_and_martial_focus():
    from combat.flight import jump_score

    engine = _engine([VAULTER], kit=POLEARM_KIT)
    assert jump_score(engine, _me(engine)) == (_me(engine).strength_score, 0)
    assert "Polearm Vaulter: jump 5 feet higher" in _legal(engine)
    events = _use(engine, "Polearm Vaulter: jump 5 feet higher", target=None)
    assert _me(engine).resources[FOCUS] == 0, "the printed Martial Focus is spent"
    assert [event.event_type for event in events].count("RESOURCE_SPENT") == 1
    assert jump_score(engine, _me(engine)) == (_me(engine).strength_score, 5)
    assert "Polearm Vaulter: jump 5 feet higher" not in _legal(engine), "one purchase buys one jump"


def _scored_engine(talents, *, str_score=16, dex_score=16, walking_ft=50, kit=KIT, cl=10):
    """This fighter with its own Strength and Dexterity scores, its turn open."""
    sheet = _sheet(talents, cl=cl, walking_ft=walking_ft, kit=kit)
    sheet["ability_scores_and_statistics"]["abilities"] = [
        {"ability": ability, "score": str_score if ability == "STR" else dex_score if ability == "DEX" else 16,
         "modifier": ((str_score if ability == "STR" else dex_score if ability == "DEX" else 16) - 10) // 2}
        for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    bundle = compile_character(sheet, actor_id=ME)
    keys = ["actor:factory.auto8.n2"]
    others = [compile_character(_sheet([], cl=cl), actor_id=key) for key in keys]
    teams = {ME: "team:a", AN: "team:b", **{key: "team:b" for key in keys}}
    places = {ME: {"x": 3, "y": 6}, AN: {"x": 12, "y": 12}, keys[0]: {"x": 13, "y": 12}}
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO8", typed_bundles=(bundle, *others),
                                   roster_setup={"primary_actor_ids": [ME, AN, *keys], "team_by_actor": teams,
                                                 "starting_positions": places})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me = engine.state.actors[ME]
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    me.resources[FOCUS] = 1
    return engine


def _jump_candidates(engine):
    return [candidate for candidate in engine.legal_candidates() if candidate.display_name.startswith("Jump to ")]


def test_mighty_conditioning_measures_jumps_with_the_better_of_strength_and_dexterity():
    """You may use Dexterity instead of Strength when determining jump distance or height."""
    from combat.flight import jump_score

    assert _passives([MIGHTY], MIGHTY), "the Mighty Conditioning row compiled"
    plain = _engine([])
    assert jump_score(plain, _me(plain)) == (_me(plain).strength_score, 0), "no row, no change"
    strong = _engine([MIGHTY])
    assert jump_score(strong, _me(strong))[0] == _me(strong).strength_score, "Strength is the better score here"
    engine = _scored_engine([MIGHTY], str_score=8, dex_score=18)
    actor = _me(engine)
    assert actor.strength_score == 8 and actor.dexterity_score == 18
    assert jump_score(engine, actor) == (18, 0), "Dexterity measures the jump when it is the better score"


def test_mighty_conditioning_reaches_the_legal_jump_menu_with_dexterity_alone():
    """F3: the 14-score ascent gate used the original Strength, so a STR 8 / DEX 18 fighter had no jump candidates
    at all. The gate is measured with the score that measures the jump."""
    plain = _scored_engine([], str_score=8, dex_score=18)
    assert not _jump_candidates(plain), "Strength 8 alone cannot start a high jump"
    engine = _scored_engine([MIGHTY], str_score=8, dex_score=18)
    assert _jump_candidates(engine), "Dexterity 18 answers the printed ascent gate"
    assert _jump_candidates(_engine([], walking_ft=50)), "a Strength 16 fighter still jumps exactly as before"


def test_mighty_conditioning_actually_jumps_with_dexterity_alone():
    """F3 asked for an executed jump, not only a menu: this fighter takes one of the destinations its own
    Dexterity bought and the fight records that jump.

    The map carries no altitude to land on, so the fighter settles back to the floor immediately afterwards; that
    is this table's inherited ground rule (an arena column without a height is open air at every level), identical
    for a Strength 16 fighter, so this test pins the jump itself rather than the resting altitude."""
    engine = _scored_engine([MIGHTY], str_score=8, dex_score=18)
    assert not _jump_candidates(_scored_engine([], str_score=8, dex_score=18)), \
        "the same fighter without the row cannot jump"
    candidates = _jump_candidates(engine)
    assert candidates, "Dexterity 18 reaches the jump menu"
    best = max(candidates, key=lambda candidate: candidate.destination.z)
    before = len(engine.events)
    _use(engine, best.display_name)
    committed = [event for event in engine.events[before:]
                 if event.event_type == "MOVEMENT_COMMITTED"
                 and (event.payload or {}).get("movement_mode") == "jump"]
    assert committed, f"the jump was a real jump: {[e.event_type for e in engine.events[before:]]}"
    assert committed[0].payload["destination"] == {"x": best.destination.x, "y": best.destination.y,
                                                   "z": best.destination.z}
    assert _me(engine).position.x == best.destination.x and _me(engine).position.y == best.destination.y


def test_polearm_vaulter_jump_reaches_the_menu_without_a_strength_score():
    """F3: "This increase does not depend on Strength, Dexterity, or remaining movement", so the flat bonus answers
    the ascent gate on its own."""
    from combat.flight import jump_score

    plain = _scored_engine([], str_score=8, dex_score=8)
    assert not _jump_candidates(plain), "Strength 8 alone cannot start a high jump"
    engine = _scored_engine([VAULTER], str_score=8, dex_score=8, kit=POLEARM_KIT)
    assert jump_score(engine, _me(engine)) == (8, 0)
    _use(engine, "Polearm Vaulter: jump 5 feet higher", target=None)
    assert jump_score(engine, _me(engine)) == (8, 5)
    assert _jump_candidates(engine), "the printed increase needs no Strength score to lift the fighter"


def test_a_fighter_without_athletics_jump_rows_jumps_exactly_as_before():
    from combat.flight import jump_score, jump_steps

    engine = _engine([], walking_ft=50)
    me = _me(engine)
    assert jump_score(engine, me) == (me.strength_score, 0)
    ground = (Position(x=3, y=6, z=0), Position(x=4, y=6, z=0))  # too short for a run-up: no running bonus
    assert jump_steps(engine, me, ground) == max(0, 3 + (me.strength_score - 10) // 2) // 10
