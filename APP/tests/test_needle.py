"""The Piercing Needle (task F, 2026-09-29): Feint, Exploits, Footwork, Court and Sovereign. combat/ext/needle.py,
needle_feint.py, needle_footwork.py."""

from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.needle"
FOCUS = "resource:core.martial_focus"
BASE = ["TAL_FENCING_FEINT"]


def _engine(talents, *, foe_at=(4, 6), seed="NEEDLE", me_at=(3, 6), extra=()):
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.the_piercing_needle"],
                                     "learned_talent_record_ids": [*BASE, *talents, *extra]}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    _turn(engine, ME)
    return engine, bundle


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _names(engine):
    return [getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog]


def _do(engine, name, *, actor=ME):
    candidate = next(c for c in engine.legal_candidates()
                     if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name and c.actor_id == actor)
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def _feint_marks(actor):
    return [m for m in actor.modifiers.values() if m.target_field == "attack_mode_vs" and str(m.source_definition_id).startswith("needle:feint:")]


def _said(engine, text):
    return [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and text in str((e.payload or {}).get("trigger", ""))]


def test_feint_gives_advantage_against_that_enemy_until_the_end_of_the_next_turn():
    engine, _ = _engine([])
    me = engine.state.actors[ME]
    _do(engine, "Feint")
    marks = _feint_marks(me)
    assert len(marks) == 1 and marks[0].value == f"ADVANTAGE:{AN}"
    assert marks[0].expires_on == f"END_OF_TURN_AT:{ME}:{me.turns_started + 1}"
    assert _said(engine, "Feints")


# ---------------------------------------------------------------------------------------------------- Exploits and their cost
from tests import test_auto_lane4 as L4  # noqa: E402

t = L4.t

NEEDLE = "tianxia.sphere.the_piercing_needle"


def _fencer(talents, **kwargs):
    """ME (the Needle fencer) beside SUBJ (a plain typed fighter); the dice are the seeded roller's until ``L4._script`` says otherwise."""
    engine = L4._duel([], attacker_sphere=NEEDLE, attacker_talents=[*BASE, *talents], attacker_kit={"starting_kit": KIT}, **kwargs)
    return engine, engine.state.actors[L4.ME], engine.state.actors[L4.SUBJ]


def _attack(engine, name=None):
    return L4._use(engine, name or "Bi Shou (Dagger) attack")


def test_an_exploit_that_costs_martial_focus_expends_it_when_it_lands():
    engine, me, foe = _fencer(["TAL_FENCING_FACE_STRIKE", "TAL_FENCING_EXPERT_FEINT"])
    L4._script(engine, [15, 12, 4, 4, 4, 4, 4, 4])
    L4._use(engine, "Feint (Bonus Action)")
    _attack(engine)
    assert me.resources[FOCUS] == 0
    assert _said(engine, "expends Martial Focus (Exploit: Face Strike)")
    assert _said(engine, "applies Exploit: Face Strike")


def test_an_exploit_that_costs_martial_focus_is_not_applied_without_it():
    engine, me, foe = _fencer(["TAL_FENCING_FACE_STRIKE", "TAL_FENCING_EXPERT_FEINT"])
    me.resources[FOCUS] = 0
    L4._use(engine, "Feint (Bonus Action)")
    _attack(engine)
    assert not _said(engine, "applies Exploit")


# ---------------------------------------------------------------------------------------------------- a team fight: allies, several foes
FENCER = L4.ME
ALLY, FOE1, FOE2 = "actor:factory.ally", "actor:factory.foe1", "actor:factory.foe2"


def _team(talents, *, allies=0, foes=2, foe_sphere=None, positions=None, kit=True):
    """FENCER (the fencer) with ``allies`` friends against ``foes`` typed Brutes, all with weapons. ``positions`` overrides cells."""
    mine = compile_character(t._sheet(NEEDLE, [*BASE, *talents], {"starting_kit": KIT}), actor_id=FENCER)
    ids = [ALLY] * allies + [FOE1, FOE2][:foes]
    bundles, teams = [mine], {FENCER: "team:a"}
    where = {FENCER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE1: {"x": 4, "y": 6}, FOE2: {"x": 4, "y": 7}}
    for actor_id in ids:
        bundles.append(compile_character(t._sheet(L4.BRUTE, [], {"starting_kit": KIT}), actor_id=actor_id))
        teams[actor_id] = "team:a" if actor_id == ALLY else "team:b"
    where.update({key: {"x": x, "y": y} for key, (x, y) in (positions or {}).items()})
    engine = Gate4ControllerEngine(ROOT, match_seed="NEEDLE-TEAM", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": [FENCER, *ids], "team_by_actor": teams,
                                                 "starting_positions": {key: where[key] for key in [FENCER, *ids]}})
    L4._new_turn(engine, FENCER)
    t._ready(engine)
    return engine


def _answers(engine, table):
    """A player answering the Needle choices: ``table`` maps a choice id (suffix after "choice:needle.") to the option ids to pick
    (a tuple), None to decline, or a function of the request. Returns the requests seen."""
    from combat.gate2_runtime_models import ReactionDecision

    seen = []

    def provider(request):
        seen.append(request)
        key = request["reaction_source_id"].split("choice:needle.")[-1]
        spec = request["extension_choice"]
        pick = table[key] if key in table else (spec.get("preferred_option_ids") or spec["option_ids"])[:spec["maximum_selections"]]  # unlisted: the default
        pick = pick(request) if callable(pick) else pick
        base = dict(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"])
        if pick is None:
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        return ReactionDecision(**base, selection="USE", option_ids=tuple(pick)), None

    engine.set_reaction_provider(provider)
    return seen


def _modes(engine):
    return [(e.actor_id, (e.payload or {}).get("mode")) for e in engine.events if e.event_type == "ATTACK_ROLLED"]


# ---------------------------------------------------------------------------------------------------- Feint
def test_a_second_feint_replaces_the_one_still_unspent():
    engine, _ = _engine(["TAL_FENCING_EXPERT_FEINT"])
    _do(engine, "Feint")
    _do(engine, "Feint (Bonus Action)")
    assert len(_feint_marks(engine.state.actors[ME])) == 1


def test_a_feint_can_aid_an_ally_instead_and_lasts_until_the_start_of_the_fencers_next_turn():
    engine = _team([], allies=1, foes=1)
    seen = _answers(engine, {"feint_aid": (ALLY,)})
    L4._use(engine, "Feint")
    ally, me = engine.state.actors[ALLY], engine.state.actors[FENCER]
    assert seen and ALLY in seen[0]["legal_option_ids"] and FENCER in seen[0]["legal_option_ids"]
    assert not _feint_marks(me)
    marks = _feint_marks(ally)
    assert len(marks) == 1 and marks[0].value == f"ADVANTAGE:{FOE1}" and marks[0].expires_on.startswith("START_OF_TURN_AT:")


def test_a_feint_with_nobody_to_ask_aids_the_fencer_when_no_ally_stands_at_the_enemy():
    engine = _team([], allies=1, foes=1, positions={ALLY: (9, 9)})
    L4._use(engine, "Feint")
    assert _feint_marks(engine.state.actors[FENCER]) and not _feint_marks(engine.state.actors[ALLY])


def test_expert_feint_is_a_bonus_action_and_three_step_feint_reaches_a_second_enemy():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_THREE_STEP_FEINT"])
    me = engine.state.actors[FENCER]
    L4._use(engine, "Feint (Bonus Action)")
    assert not me.bonus_action_available and me.action_available
    assert sorted(m.value for m in _feint_marks(me)) == [f"ADVANTAGE:{FOE1}", f"ADVANTAGE:{FOE2}"]


def test_three_step_feint_is_only_for_the_bonus_action_feint():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_THREE_STEP_FEINT"])
    L4._use(engine, "Feint")
    assert len(_feint_marks(engine.state.actors[FENCER])) == 1


def test_greater_feint_makes_the_enemy_save_and_gives_every_creature_a_first_attack_with_advantage():
    engine = _team(["TAL_FENCING_GREATER_FEINT"], allies=1, foes=1)
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    L4._script(engine, [1])  # the foe's Wisdom save: a 1
    seen = _answers(engine, {"greater_feint": ("greater_feint",)})
    L4._use(engine, "Feint")
    assert me.resources[FOCUS] == 0
    assert [c for c in foe.conditions.values() if c.condition_id.endswith("needle_greater_feint")]
    assert _said(engine, "is fooled")
    # each creature's first attack roll against it has Advantage, once each
    L4._new_turn(engine, ALLY)
    a = engine.state.actors[ALLY]
    a.action_available = True
    L4._script(engine, [10, 10, 4, 4, 4, 4])
    from combat.ext import needle_feint

    class C:  # a bare attack context: only the engine and actor are read
        pass
    ctx = C(); ctx.engine, ctx.actor = engine, a
    assert needle_feint.feint_attack_mode(ctx, foe) == "ADVANTAGE"
    assert needle_feint.feint_attack_mode(ctx, foe) is None  # the second attack roll by the same creature
    ctx.actor = me
    assert needle_feint.feint_attack_mode(ctx, foe) == "ADVANTAGE"  # another creature gets its own first


def test_greater_feint_saved_against_gives_nothing_but_still_expends_the_focus():
    engine = _team(["TAL_FENCING_GREATER_FEINT"], foes=1)
    _answers(engine, {"greater_feint": ("greater_feint",)})
    L4._script(engine, [20])
    L4._use(engine, "Feint")
    foe = engine.state.actors[FOE1]
    assert engine.state.actors[FENCER].resources[FOCUS] == 0
    assert not [c for c in foe.conditions.values() if c.condition_id.endswith("needle_greater_feint")]


def test_greater_feint_is_declinable_and_costs_nothing_when_declined():
    engine = _team(["TAL_FENCING_GREATER_FEINT"], foes=1)
    _answers(engine, {"greater_feint": None})
    L4._use(engine, "Feint")
    assert engine.state.actors[FENCER].resources[FOCUS] == 1


def test_fatal_opening_a_natural_19_with_your_own_feints_advantage_adds_the_critical_dice():
    engine = _team(["TAL_FENCING_FATAL_OPENING", "TAL_FENCING_EXPERT_FEINT"], foes=1)
    _answers(engine, {"exploit": None})
    L4._use(engine, "Feint (Bonus Action)")
    L4._script(engine, [19, 5, 3, 3, 3, 3, 3])  # advantage: 19 and 5; then the damage dice
    L4._use(engine, "Bi Shou (Dagger) attack")
    rolls = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == FENCER]
    assert len(rolls) == 1 and rolls[0].payload["critical"]
    assert len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == FENCER]) == 1


def test_fatal_opening_does_not_apply_without_the_feints_advantage():
    engine = _team(["TAL_FENCING_FATAL_OPENING"], foes=1)
    L4._script(engine, [19, 3, 3, 3, 3, 3])
    L4._use(engine, "Bi Shou (Dagger) attack")
    rolls = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == FENCER]
    assert len(rolls) == 1 and not rolls[0].payload["critical"]


def test_group_cover_puts_disadvantage_on_the_attackers_neighbours_against_the_fencer():
    engine = _team(["TAL_FENCING_GROUP_COVER"], foes=2, positions={FOE1: (4, 6), FOE2: (5, 6)})
    me = engine.state.actors[FENCER]
    engine._append_event("ATTACK_ROLLED", "test:attack", actor_id=FOE1, target_ids=(FENCER,), payload={"mode": "NORMAL"})
    cover = [c for c in me.conditions.values() if c.condition_id.endswith("needle_group_cover")]
    assert cover and (cover[0].data or {}).get("affected") == [FOE2]
    from combat.ext import needle_feint

    class C:
        pass
    ctx = C(); ctx.engine, ctx.actor = engine, engine.state.actors[FOE2]
    assert needle_feint.feint_attack_mode(ctx, me) == "DISADVANTAGE"
    ctx.actor = engine.state.actors[FOE1]
    assert needle_feint.feint_attack_mode(ctx, me) is None  # only the attacker's neighbours


def test_group_cover_with_no_neighbours_puts_nothing_on_the_fencer():
    engine = _team(["TAL_FENCING_GROUP_COVER"], foes=2, positions={FOE1: (4, 6), FOE2: (9, 9)})
    engine._append_event("ATTACK_ROLLED", "test:attack", actor_id=FOE1, target_ids=(FENCER,), payload={"mode": "NORMAL"})
    assert not [c for c in engine.state.actors[FENCER].conditions.values() if c.condition_id.endswith("needle_group_cover")]


# ---------------------------------------------------------------------------------------------------- Court and Sovereign
def _use_as(engine, actor_id, name):
    """L4._use, for any creature (the foes' attacks on the fencer)."""
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    engine.state.current_actor_id = actor_id
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id)
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def _domain(engine, name):
    return [c for c in engine.state.actors[FENCER].conditions.values() if c.condition_id.endswith(name)]


def _court(engine):
    L4._use(engine, "Court of Measured Openings")
    return _domain(engine, "needle_court")


def test_court_of_measured_openings_is_a_timed_state_of_ten_rounds_that_takes_the_bonus_action():
    engine = _team(["TAL_FENCING_COURT_OF_MEASURED_OPENINGS"], foes=1)
    me = engine.state.actors[FENCER]
    (court,) = _court(engine)
    assert not me.bonus_action_available and me.resources[FOCUS] == 0
    assert court.expires_on == f"START_OF_SLOT_AT:{engine.state.round_number + 10}:1"  # 1 minute = 10 rounds


def test_court_ends_the_moment_the_fencer_is_incapacitated():
    engine = _team(["TAL_FENCING_COURT_OF_MEASURED_OPENINGS"], foes=1)
    assert _court(engine)
    me = engine.state.actors[FENCER]
    engine._apply_condition(me, "condition:core.incapacitated", "test:stun", FOE1, expires_on="UNTIL_REMOVED")
    assert not _domain(engine, "needle_court")
    assert _said(engine, "Incapacitated")


def test_court_gives_one_feint_a_turn_with_no_action_and_the_second_is_not_offered():
    engine = _team(["TAL_FENCING_COURT_OF_MEASURED_OPENINGS"], foes=1)
    _court(engine)
    me = engine.state.actors[FENCER]
    L4._use(engine, "Feint (Court of Measured Openings, no Action)")
    assert me.action_available and _feint_marks(me)
    assert "Feint (Court of Measured Openings, no Action)" not in {c.display_name for c in engine.legal_candidates()}


def test_without_court_the_free_feint_is_not_offered():
    engine = _team(["TAL_FENCING_COURT_OF_MEASURED_OPENINGS"], foes=1)
    assert "Feint (Court of Measured Openings, no Action)" not in {c.display_name for c in engine.legal_candidates()}


def test_court_feints_a_hostile_in_reach_that_misses_the_fencer_with_no_action():
    engine = _team(["TAL_FENCING_COURT_OF_MEASURED_OPENINGS"], foes=1)
    _court(engine)
    me = engine.state.actors[FENCER]
    L4._new_turn(engine, FOE1)
    L4._script(engine, [1, 1])  # the foe's natural 1
    _use_as(engine, FOE1, "Bi Shou (Dagger) attack")
    assert _feint_marks(me) and me.action_available
    assert _said(engine, "Feints with no Action")


# ---------------------------------------------------------------------------------------------------- Footwork, Crane-Wing, Lunge
def _cell(x, y):
    return f"cell:{x},{y}"


def _step_to(x, y):
    return lambda request: (_cell(x, y),)


def _distance(engine, a, b):
    return engine.grid.distance_ft(engine.state.actors[a].position, engine.state.actors[b].position)


def test_footwork_on_the_fencers_own_turn_is_a_free_step_that_spends_martial_focus():
    engine = _team(["TAL_FENCING_FOOTWORK"], foes=1)
    me = engine.state.actors[FENCER]
    _answers(engine, {"footwork": _step_to(1, 6)})
    events = L4._use(engine, "Footwork")
    assert me.position.x == 1 and me.position.y == 6 and me.resources[FOCUS] == 0
    assert me.action_available and me.bonus_action_available and me.reaction_available
    assert not [e for e in events if "opportunity" in str(e.source_definition_id).lower()]
    assert _said(engine, "uses Footwork to 1,6")


def test_footwork_is_not_offered_without_martial_focus():
    engine = _team(["TAL_FENCING_FOOTWORK"], foes=1)
    engine.state.actors[FENCER].resources[FOCUS] = 0
    assert "Footwork" not in {c.display_name for c in engine.legal_candidates()}


def test_footwork_can_be_declined_and_then_costs_nothing():
    engine = _team(["TAL_FENCING_FOOTWORK"], foes=1)
    _answers(engine, {"footwork": None})
    L4._use(engine, "Footwork")
    assert engine.state.actors[FENCER].resources[FOCUS] == 1


def _defender_duel(talents, *, at=(4, 6), foe_at=(3, 6), **kwargs):
    """SUBJ (the fencer) is attacked by ME (a Brute with a dagger)."""
    engine = L4._duel([*BASE, *talents], subject_sphere=NEEDLE, subject_kit={"starting_kit": KIT}, attacker_kit={"starting_kit": KIT}, **kwargs)
    subj, attacker = engine.state.actors[L4.SUBJ], engine.state.actors[L4.ME]
    subj.position = Position(x=at[0], y=at[1])
    attacker.position = Position(x=foe_at[0], y=foe_at[1])
    return engine, subj, attacker


def test_footwork_before_an_attack_steps_out_of_reach_and_the_attack_misses():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    _answers(engine, {"footwork": _step_to(6, 6)})
    hp = subj.current_hp
    L4._script(engine, [19, 6, 6, 6])
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert subj.position.x == 6 and subj.resources[FOCUS] == 0 and subj.current_hp == hp
    assert _said(engine, "uses Footwork")


def test_footwork_before_an_attack_that_stays_within_reach_gives_the_attack_disadvantage():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    _answers(engine, {"footwork": _step_to(4, 6)})  # stay put
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert ("DISADVANTAGE" in [mode for _, mode in _modes(engine)]) and subj.resources[FOCUS] == 0


def test_footwork_declined_before_an_attack_leaves_the_roll_alone_and_keeps_the_focus():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    _answers(engine, {"footwork": None})
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert subj.resources[FOCUS] == 1 and "DISADVANTAGE" not in [mode for _, mode in _modes(engine)]


def test_footwork_needs_the_fencer_to_be_free_to_move():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    engine._apply_condition(subj, "condition:core.incapacitated", "test", L4.ME, expires_on="UNTIL_REMOVED")
    seen = _answers(engine, {})
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert not [r for r in seen if r["reaction_source_id"].endswith("footwork")]


def test_sovereign_uses_footwork_once_a_round_without_expending_martial_focus():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    engine._apply_condition(subj, "condition:typed.needle_sovereign", "test", L4.SUBJ, expires_on="UNTIL_REMOVED")
    _answers(engine, {"footwork": _step_to(4, 6)})
    from combat.ext import needle_footwork as nf

    assert nf.can_footwork(engine, subj)
    subj.resources[FOCUS] = 0
    assert nf.can_footwork(engine, subj)  # free with none held
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert subj.resources[FOCUS] == 0 and _said(engine, "without expending Martial Focus")
    assert not nf.can_footwork(engine, subj)  # the round's free one is used and none is held


def test_court_regains_martial_focus_after_a_footwork_once_a_round():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK", "TAL_FENCING_COURT_OF_MEASURED_OPENINGS"])
    engine._apply_condition(subj, "condition:typed.needle_court", "test", L4.SUBJ, expires_on="UNTIL_REMOVED")
    _answers(engine, {"footwork": _step_to(4, 6)})
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert subj.resources[FOCUS] == 1 and _said(engine, "Court of Measured Openings: Footwork")


def test_crane_wing_advance_reaches_fifteen_feet_where_footwork_reaches_ten():
    for talents, far in ((["TAL_FENCING_FOOTWORK", "TAL_FENCING_CRANE_WING_ADVANCE"], True), (["TAL_FENCING_FOOTWORK"], False)):
        engine = _team(talents, foes=1, positions={FOE1: (9, 9)})
        seen = _answers(engine, {"footwork": _step_to(3, 6)})
        L4._use(engine, "Footwork")
        options = seen[0]["legal_option_ids"]
        assert (_cell(6, 6) in options) is far  # 15 feet
        assert _cell(5, 6) in options and _cell(7, 6) not in options  # 10 feet always; 20 never


def test_crane_wing_advance_stops_opportunity_attacks_from_a_creature_the_step_ends_beside():
    from combat.ext import needle_footwork as nf

    engine = _team(["TAL_FENCING_FOOTWORK", "TAL_FENCING_CRANE_WING_ADVANCE"], foes=1, positions={FOE1: (7, 6)})
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    _answers(engine, {"footwork": _step_to(6, 6)})
    L4._use(engine, "Footwork")
    assert nf.crane_wing_no_opportunity(engine, foe, me) is False
    L4._new_turn(engine, FOE1)
    assert nf.crane_wing_no_opportunity(engine, foe, me) is None  # only the rest of that turn


# ---------------------------------------------------------------------------------------------------- the Exploits' own effects
def _pin(engine, **naturals):
    """Fix the natural d20 of every roll whose reason starts with a key (ATTACK, SAVE, ...), whatever else was scripted."""
    roller = engine.roller
    original = roller.d20

    def d20(*, modifier, actor_id, reason, mode="NORMAL"):
        for prefix, value in naturals.items():
            if reason.startswith(prefix):
                die = roller._die

                def pinned(sides, value=value):
                    counter = roller.counter
                    roller.counter += 1
                    return min(value, sides), counter

                roller._die = pinned
                try:
                    return original(modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
                finally:
                    roller._die = die
        return original(modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)

    roller.d20 = d20


def _land_exploit(exploit_id, *, allies=0, save=1, foes=1, extra=(), positions=None, answers=None, prepare=None):
    """The fencer Feints (Bonus Action) and hits with the dagger, choosing ``exploit_id``; the foe's save is the natural ``save``."""
    engine = _team(["TAL_FENCING_EXPERT_FEINT", exploit_id, *extra], allies=allies, foes=foes, positions=positions)
    _pin(engine, ATTACK=15, SAVE=save)
    _answers(engine, {"exploit": (exploit_id,), **(answers or {})})
    if prepare:
        prepare(engine)
    L4._use(engine, "Feint (Bonus Action)")
    L4._use(engine, "Bi Shou (Dagger) attack")
    return engine, engine.state.actors[FENCER], engine.state.actors[FOE1]


def _bears(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id.endswith(name)]


def test_arm_strike_a_failed_save_costs_the_target_two_on_attack_rolls_for_pb_rounds():
    engine, me, foe = _land_exploit("TAL_FENCING_ARM_STRIKE")
    (found,) = _bears(foe, "needle_arm_strike") or [None]
    assert found is not None and found.expires_on.startswith("START_OF_SLOT_AT:")


def test_soul_strike_a_failed_wisdom_save_puts_minus_two_on_the_targets_saves():
    engine, me, foe = _land_exploit("TAL_FENCING_SOUL_STRIKE")
    assert _bears(foe, "needle_soul_strike")


def test_soul_strike_a_passed_save_does_nothing():
    engine, me, foe = _land_exploit("TAL_FENCING_SOUL_STRIKE", save=20)
    assert not _bears(foe, "needle_soul_strike")


def test_shadow_strike_gives_a_temporary_exhaustion_level_and_slows_the_target():
    engine, me, foe = _land_exploit("TAL_FENCING_SHADOW_STRIKE")
    assert _bears(foe, "needle_shadow_strike")
    assert engine._effective_speed(foe) < foe.speed_ft


def test_two_soul_strikes_from_one_fencer_refresh_rather_than_stack():
    engine, me, foe = _land_exploit("TAL_FENCING_SOUL_STRIKE")
    from combat.typed_executor import Context, run_effects

    ctx = Context(engine, me, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4, "save_dc": 30}}, [foe], foe, {})
    run_effects(ctx, [{"type": "needle_condition", "key": "soul_strike", "label": "again"}])
    assert len(_bears(foe, "needle_soul_strike")) == 1


def test_bleed_air_a_failed_save_starts_a_choking_clock_that_ends_when_the_target_is_at_full_hit_points():
    engine, me, foe = _land_exploit("TAL_FENCING_BLEED_AIR")
    (found,) = _bears(foe, "needle_bleed_air")
    assert found.data["begins_round"] >= engine.state.round_number + 1
    foe.current_hp = foe.maximum_hp  # restored to its Hit Point maximum
    L4._new_turn(engine, FOE1)
    assert not _bears(foe, "needle_bleed_air")


def test_bleed_air_choking_takes_the_target_to_zero_after_its_constitution_modifier_in_rounds():
    engine, me, foe = _land_exploit("TAL_FENCING_BLEED_AIR")
    (found,) = _bears(foe, "needle_bleed_air")
    engine.state.round_number = int(found.data["begins_round"])
    L4._new_turn(engine, FOE1)
    (found,) = _bears(foe, "needle_bleed_air")
    assert "dies_round" in found.data
    engine.state.round_number = int(found.data["dies_round"])
    L4._new_turn(engine, FOE1)
    assert foe.current_hp == 0 and not _bears(foe, "needle_bleed_air")


def test_bleed_air_needs_a_target_below_its_hit_point_maximum():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_BLEED_AIR"], foes=1)
    from combat.ext import needle

    assert not needle._legal(engine, engine.state.actors[FENCER], engine.state.actors[FOE1], {"id": "TAL_FENCING_BLEED_AIR"})
    engine.state.actors[FOE1].current_hp -= 1
    assert needle._legal(engine, engine.state.actors[FENCER], engine.state.actors[FOE1], {"id": "TAL_FENCING_BLEED_AIR"})


def test_empty_hand_open_meridian_stops_healing_and_cultivation_resource_recovery():
    engine, me, foe = _land_exploit("TAL_FENCING_EMPTY_HAND_OPEN_MERIDIAN")
    assert foe.conditions and [c for c in foe.conditions.values() if "heal" in c.condition_id or "no_cp" in c.condition_id]


def test_to_the_hilt_removes_the_targets_resistance_for_half_pb_rounds():
    engine, me, foe = _land_exploit("TAL_FENCING_TO_THE_HILT")
    assert [m for m in list(foe.modifiers.values()) + list(foe.conditions.values())
            if "resistance" in str(getattr(m, "target_field", "")) + str(getattr(m, "condition_id", ""))]


def test_wide_open_gives_an_ally_advantage_on_the_next_attack_until_the_fencers_next_turn():
    engine, me, foe = _land_exploit("TAL_FENCING_WIDE_OPEN", allies=1)
    ally = engine.state.actors[ALLY]
    marks = [m for m in ally.modifiers.values() if m.target_field == "attack_mode_vs" and m.value == f"ADVANTAGE:{FOE1}"
             and not str(m.source_definition_id).startswith("needle:feint:")]
    assert len(marks) == 1 and marks[0].expires_on.startswith("START_OF_TURN_AT:")


def test_wide_open_is_not_offered_when_there_is_no_ally_to_grant_it_to():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_WIDE_OPEN"], foes=1)
    from combat.ext import needle

    assert not needle._legal(engine, engine.state.actors[FENCER], engine.state.actors[FOE1], {"id": "TAL_FENCING_WIDE_OPEN"})


def test_repositioning_strike_moves_the_target_five_feet_within_reach_and_the_fencer_chooses_where():
    engine, me, foe = _land_exploit("TAL_FENCING_REPOSITIONING_STRIKE", answers={"reposition": _step_to(4, 5)})
    assert (foe.position.x, foe.position.y) == (4, 5)
    assert _said(engine, "Repositioning Strike")


def test_returning_point_lets_the_fencer_step_five_feet_after_an_exploit_once_a_turn():
    engine, me, foe = _land_exploit("TAL_FENCING_ARM_STRIKE", extra=("TAL_FENCING_RETURNING_POINT",), answers={"returning_point": _step_to(2, 6)})
    assert (me.position.x, me.position.y) == (2, 6)
    assert me.turn_flags.get("needle_returning_point")


def test_a_second_exploit_the_same_round_is_not_applied():
    engine, me, foe = _land_exploit("TAL_FENCING_ARM_STRIKE")
    before = len(_said(engine, "applies Exploit"))
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert len(_said(engine, "applies Exploit")) == before == 1


def test_sovereign_applies_an_exploit_up_to_twice_a_round_but_once_to_an_attack():
    engine = _team(["TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SOUL_STRIKE"], allies=1, foes=1, positions={ALLY: (5, 6)})
    _pin(engine, ATTACK=15, SAVE=1)
    me = engine.state.actors[FENCER]
    engine._apply_condition(me, "condition:typed.needle_sovereign", "test", FENCER, expires_on="UNTIL_REMOVED")
    _answers(engine, {})
    for _ in range(3):  # an ally beside the target lets every hit qualify
        me.action_available = True
        L4._use(engine, "Bi Shou (Dagger) attack")
    assert len(_said(engine, "applies Exploit")) == 2  # twice a round, not three times; and never two on one attack


def test_without_sovereign_only_one_exploit_lands_a_round():
    engine = _team(["TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SOUL_STRIKE"], allies=1, foes=1, positions={ALLY: (5, 6)})
    _pin(engine, ATTACK=15, SAVE=1)
    me = engine.state.actors[FENCER]
    _answers(engine, {})
    for _ in range(2):
        me.action_available = True
        L4._use(engine, "Bi Shou (Dagger) attack")
    assert len(_said(engine, "applies Exploit")) == 1


def test_court_lets_two_different_exploits_land_on_one_attack_without_expending_focus_for_it():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE"], foes=1)
    _pin(engine, ATTACK=15, SAVE=1)
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    engine._apply_condition(me, "condition:typed.needle_court", "test", FENCER, expires_on="UNTIL_REMOVED")
    _answers(engine, {"exploit": ("TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE")})
    L4._use(engine, "Feint (Bonus Action)")
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert _bears(foe, "needle_arm_strike") and _bears(foe, "needle_shadow_strike")
    assert me.resources[FOCUS] == 1  # Court paid the second


def test_skewer_two_different_exploits_on_one_attack_cost_one_martial_focus():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE", "TAL_FENCING_SKEWER"], foes=1)
    _pin(engine, ATTACK=15, SAVE=1)
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    _answers(engine, {"exploit": ("TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE")})
    L4._use(engine, "Feint (Bonus Action)")
    L4._use(engine, "Bi Shou (Dagger) attack")
    assert _bears(foe, "needle_arm_strike") and _bears(foe, "needle_shadow_strike") and me.resources[FOCUS] == 0
    assert _said(engine, "Skewer: two Exploits on one attack")


def test_skewers_standing_second_pick_is_offered_as_the_default_second_exploit():
    engine = _team(["TAL_FENCING_EXPERT_FEINT", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE", "TAL_FENCING_SKEWER"], foes=1)
    _pin(engine, ATTACK=15, SAVE=1)
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    L4._use(engine, "Skewer: also Shadow Strike")
    seen = _answers(engine, {})
    L4._use(engine, "Feint (Bonus Action)")
    L4._use(engine, "Bi Shou (Dagger) attack")
    request = next(r for r in seen if r["reaction_source_id"].endswith("exploit"))
    assert "TAL_FENCING_SHADOW_STRIKE" in request["extension_choice"]["preferred_option_ids"]
    assert _bears(foe, "needle_shadow_strike")


# --------------------------------------------------------------------------------------------------------- Sovereign: Parry and Riposte
def _parried_by(*, sovereign, pending=1):
    """A foe's melee hit on a fencer with Parry and Riposte, through the real hit/damage checkpoints (tests/test_auto_lane5.py)."""
    from tests.test_auto_ironclad import ME as PARRIER, _bundle, _engine, _hit_then_damage

    engine = _engine(_bundle(["TAL_FENCING_PARRY_AND_RIPOSTE"], spheres=(NEEDLE,)))
    from combat.gate2_runtime_content import AN

    me, foe = engine.state.actors[PARRIER], engine.state.actors[AN]
    if sovereign:
        engine._apply_condition(me, "condition:typed.needle_sovereign", "test", PARRIER, expires_on="UNTIL_REMOVED")
    left = _hit_then_damage(engine, foe, me, pending)
    return me, left


def test_sovereign_regains_martial_focus_when_parry_and_riposte_reduces_the_damage_to_zero():
    me, left = _parried_by(sovereign=True)
    assert left == 0 and me.resources[FOCUS] == 1


def test_without_sovereign_the_parry_leaves_the_martial_focus_spent():
    me, left = _parried_by(sovereign=False)
    assert left == 0 and me.resources[FOCUS] == 0


# --------------------------------------------------------------------------------------------------------- Footwork before a Dexterity save
def _dex_effect(engine, attacker, subject, *, damage=20):
    """An effect from ``attacker`` that lets ``subject`` make a Dexterity save (the lock round's before_dex_save checkpoint)."""
    from combat.gate2_runtime_models import ActionIntent
    from combat.typed_executor import Context, block_save

    candidate = next(c for c in engine.legal_candidates() if c.kind == "END_TURN")
    intent = ActionIntent(intent_id="test:dex", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                          state_version=candidate.state_version, actor_id=attacker.entity_id)
    engine._active_intent = intent
    action = next(iter(engine.action_catalog.values())).model_copy(update={"range_ft": 5})
    ctx = Context(engine, attacker, action, intent, {"numbers": {"save_dc": 50}}, [subject], subject)
    block_save(ctx, {"ability": "DEX", "on_fail": [{"type": "damage", "flat": damage}], "on_success": [{"type": "half_damage"}]})


def test_footwork_before_a_dexterity_save_can_step_out_of_the_effect():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    _answers(engine, {"footwork": _step_to(6, 6)})
    hp, rolls = subj.current_hp, len(engine.rolls)
    _dex_effect(engine, attacker, subj)
    assert subj.position.x == 6 and subj.resources[FOCUS] == 0
    assert subj.current_hp == hp and len(engine.rolls) == rolls  # left the effect: no save, no damage


def test_footwork_before_a_dexterity_save_that_stays_in_the_effect_gives_advantage_on_the_save():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    _answers(engine, {"footwork": _step_to(4, 6)})  # stays put
    _dex_effect(engine, attacker, subj)
    assert engine.rolls[-1].mode == "ADVANTAGE" and subj.resources[FOCUS] == 0


def test_footwork_declined_before_a_dexterity_save_keeps_the_focus_and_rolls_normally():
    engine, subj, attacker = _defender_duel(["TAL_FENCING_FOOTWORK"])
    _answers(engine, {"footwork": None})
    _dex_effect(engine, attacker, subj)
    assert engine.rolls[-1].mode == "NORMAL" and subj.resources[FOCUS] == 1


def test_footwork_is_not_offered_for_an_allys_dexterity_effect():
    engine = _team(["TAL_FENCING_FOOTWORK"], allies=1, foes=1)
    seen = _answers(engine, {})
    _dex_effect(engine, engine.state.actors[ALLY], engine.state.actors[FENCER])
    assert not [r for r in seen if r["reaction_source_id"].endswith("footwork")]


# --------------------------------------------------------------------------------------------------------- Fencing Focus, Disarm
def _spend_focus(engine, actor):
    engine._spend_resource(actor, FOCUS, 1, "test")


def test_fencing_focus_after_a_feint_regains_martial_focus_with_a_bonus_action():
    engine = _team(["TAL_FENCING_FENCING_FOCUS"], foes=1)
    me = engine.state.actors[FENCER]
    _spend_focus(engine, me)
    _answers(engine, {})
    assert "Fencing Focus" not in _names(engine)  # not before a Feint
    L4._use(engine, "Feint")
    assert "Fencing Focus" in _names(engine)
    L4._use(engine, "Fencing Focus")
    assert me.resources[FOCUS] == 1 and not me.bonus_action_available


def test_fencing_focus_is_not_offered_while_martial_focus_is_held():
    engine = _team(["TAL_FENCING_FENCING_FOCUS"], foes=1)
    _answers(engine, {})
    L4._use(engine, "Feint")
    assert "Fencing Focus" not in _names(engine)


def test_a_won_disarm_lets_fencing_focus_regain_martial_focus():
    engine = _team(["TAL_FENCING_FENCING_FOCUS"], foes=1)
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    _spend_focus(engine, me)
    _pin(engine, ATTACK=20, SAVE=1, CHECK=20)
    _answers(engine, {})
    L4._use(engine, "Bi Shou (Dagger) attack: Disarm")
    assert [c for c in foe.conditions.values() if c.condition_id.endswith("disarmed")]
    me.bonus_action_available = True
    assert "Fencing Focus" in _names(engine)
    L4._use(engine, "Fencing Focus")
    assert me.resources[FOCUS] == 1


def test_sovereign_regains_martial_focus_when_a_disarm_is_won():
    engine = _team([], foes=1)
    me = engine.state.actors[FENCER]
    engine._apply_condition(me, "condition:typed.needle_sovereign", "test", FENCER, expires_on="UNTIL_REMOVED")
    _spend_focus(engine, me)
    _pin(engine, ATTACK=20, SAVE=1, CHECK=20)
    _answers(engine, {})
    L4._use(engine, "Bi Shou (Dagger) attack: Disarm")
    assert me.resources[FOCUS] == 1 and _said(engine, "a Disarm won")


# --------------------------------------------------------------------------------------------------------- Lunge
LUNGE_NAME = "Bi Shou (Dagger) attack: Lunge"


def test_lunge_is_offered_only_against_a_target_beyond_the_weapons_own_reach_while_holding_martial_focus():
    engine = _team(["TAL_FENCING_LUNGE"], foes=1, positions={FOE1: (5, 6)})  # 10 feet away
    assert LUNGE_NAME in _names(engine)
    engine.state.actors[FOE1].position = Position(x=4, y=6)  # 5 feet: the dagger reaches without it
    assert LUNGE_NAME not in _names(engine)
    engine.state.actors[FOE1].position = Position(x=5, y=6)
    _spend_focus(engine, engine.state.actors[FENCER])
    assert LUNGE_NAME not in _names(engine)  # "While holding Martial Focus"


def test_no_lunge_without_the_talent():
    engine = _team([], foes=1, positions={FOE1: (5, 6)})
    assert LUNGE_NAME not in _names(engine)


def test_a_lunge_reaches_ten_feet_and_puts_minus_two_on_attacks_within_five_feet_until_the_next_turn():
    engine = _team(["TAL_FENCING_LUNGE"], foes=1, positions={FOE1: (5, 6)})
    me, foe = engine.state.actors[FENCER], engine.state.actors[FOE1]
    _pin(engine, ATTACK=15)
    before = len(engine.events)
    L4._use(engine, LUNGE_NAME)
    assert [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED"], "the lunge attacked from ten feet"
    assert _bears(me, "needle_lunge") and _said(engine, "lunges: -2")
    foe.position = Position(x=4, y=6)  # now within five feet
    me.action_available = True
    L4._use(engine, "Bi Shou (Dagger) attack")
    rolls = [r for r in engine.rolls if r.reason.startswith("ATTACK") and r.actor_id == FENCER]
    assert rolls[-1].modifier == rolls[-2].modifier - 2  # the lunge's -2 against a target within 5 feet


def test_an_exploit_lands_on_a_lunge_hit_from_beyond_the_weapons_reach():
    engine = _team(["TAL_FENCING_LUNGE", "TAL_FENCING_ARM_STRIKE"], foes=1, allies=1, positions={FOE1: (5, 6), ALLY: (6, 6)})
    _pin(engine, ATTACK=15, SAVE=1)
    _answers(engine, {})
    L4._use(engine, LUNGE_NAME)
    assert _bears(engine.state.actors[FOE1], "needle_arm_strike")


# --------------------------------------------------------------------------------------------------------- Parry and Riposte's riposte
def _riposte(talents, *, pending=1, natural=20, sovereign=False, prepare=None):
    """A foe's melee hit on a fencer with Parry and Riposte plus ``talents``; returns (fencer, foe, damage left, events)."""
    from combat.gate2_runtime_content import AN
    from tests.test_auto_ironclad import ME as PARRIER, _bundle, _engine, _hit_then_damage

    engine = _engine(_bundle(["TAL_FENCING_PARRY_AND_RIPOSTE", *talents], spheres=(NEEDLE,)))
    me, foe = engine.state.actors[PARRIER], engine.state.actors[AN]
    if sovereign:
        engine._apply_condition(me, "condition:typed.needle_sovereign", "test", PARRIER, expires_on="UNTIL_REMOVED")
    _pin(engine, ATTACK=natural)
    if prepare:
        prepare(engine, me, foe)
    before = len(engine.events)
    left = _hit_then_damage(engine, foe, me, pending)
    return me, foe, left, engine.events[before:]


def _attacks_by(events, actor_id):
    return [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor_id]


def test_parry_and_riposte_ripostes_with_a_melee_attack_when_it_reduces_the_damage_to_zero():
    me, foe, left, events = _riposte([])
    assert left == 0 and _attacks_by(events, me.entity_id)
    assert not [e for e in events if e.event_type == "GM_RIDER" and "riposte" in str((e.payload or {}).get("rider", "")).lower()]


def test_parry_and_riposte_makes_no_riposte_when_damage_is_left():
    me, foe, left, events = _riposte([], pending=200)
    assert left > 0 and not _attacks_by(events, me.entity_id)


def test_the_riposte_may_apply_one_exploit_with_no_advantage_and_no_ally():
    me, foe, left, events = _riposte(["TAL_FENCING_ARM_STRIKE"])
    assert _attacks_by(events, me.entity_id) and _bears(foe, "needle_arm_strike")
    assert any("applies Exploit: Arm Strike" in str((e.payload or {}).get("trigger", "")) for e in events)


def test_the_riposte_applies_no_exploit_when_the_attack_roll_has_disadvantage():
    def blind(engine, me, foe):
        engine._apply_condition(me, "condition:typed.poisoned", "test", foe.entity_id, expires_on="UNTIL_REMOVED")

    me, foe, left, events = _riposte(["TAL_FENCING_ARM_STRIKE"], prepare=blind)
    attacks = _attacks_by(events, me.entity_id)
    assert attacks and (attacks[0].payload or {}).get("mode") == "DISADVANTAGE" and not _bears(foe, "needle_arm_strike")


def test_the_riposte_is_made_before_needle_catching_and_sovereign_return_the_martial_focus():
    """"regain Martial Focus after resolving the retaliatory attack": the riposte cannot spend the Focus it has not got back yet."""
    me, foe, left, events = _riposte(["TAL_FENCING_NEEDLE_CATCHING_REVERSAL", "TAL_FENCING_SOUL_STRIKE"])
    order = [e.event_type for e in events]
    assert order.index("ATTACK_ROLLED") < [i for i, e in enumerate(events) if e.event_type == "RESOURCE_GAINED"][-1]
    assert me.resources[FOCUS] == 1 and not _bears(foe, "needle_soul_strike")  # Soul Strike costs Focus the riposte did not hold


# ------------------------------------------------------------------------------------------------ Heart-Stopping Reversal
def _reversal(talents=(), *, lethal=True, prepare=None, foe_at=(4, 6)):
    """The foe's damage would take the fencer to 0 (Heart-Stopping Reversal: Reaction, Martial Focus, once per Long Rest).
    Returns (fencer, foe, damage that lands, Hit Points left, damage offered, events, engine)."""
    from combat import typed_reactions
    from tests.test_auto_ironclad import ME as HOLDER, _bundle, _engine

    engine = _engine(_bundle(["TAL_FENCING_PARRY_AND_RIPOSTE", "TAL_FENCING_HEART_STOPPING_REVERSAL", *talents], spheres=(NEEDLE,)),
                     foe_at=foe_at)
    me, foe = engine.state.actors[HOLDER], engine.state.actors[AN]
    _pin(engine, ATTACK=15)
    if prepare:
        prepare(engine, me, foe)
    me.reaction_available = True
    before = len(engine.events)
    pending = me.current_hp + me.temporary_hp + (50 if lethal else -1)
    landed = typed_reactions.on_damage(engine, me, pending, reaction_depth=0, source_definition_id="test:attack", source_actor_id=foe.entity_id)
    return me, foe, landed, me.current_hp + me.temporary_hp, pending, engine.events[before:], engine


def test_heart_stopping_reversal_leaves_the_fencer_at_one_hit_point_and_ripostes_for_a_martial_focus():
    me, foe, landed, hp, pending, events, _engine_ = _reversal()
    assert landed == hp - 1 and landed < pending  # the damage that lands stops one short of 0
    assert _attacks_by(events, me.entity_id), "the reversal attacks the creature that dealt the damage"
    assert me.resources[FOCUS] == 0 and not me.reaction_available


def test_heart_stopping_reversal_is_not_used_for_damage_that_leaves_the_fencer_standing():
    me, foe, landed, hp, pending, events, _engine_ = _reversal(lethal=False)
    assert landed == pending and not _attacks_by(events, me.entity_id)
    assert me.resources[FOCUS] == 1 and me.reaction_available


def test_heart_stopping_reversal_attacks_only_a_creature_within_reach():
    me, foe, landed, hp, pending, events, _engine_ = _reversal(foe_at=(9, 6))
    assert landed == hp - 1 and not _attacks_by(events, me.entity_id)  # still drops to 1 Hit Point; nothing in reach to attack


def _feinted(engine, me, foe):
    engine._add_modifier(me, "needle:feint:" + me.entity_id, "attack_mode_vs", "SET", f"ADVANTAGE:{foe.entity_id}", "NEXT_ATTACK", expires_on="UNTIL_REMOVED")


def test_heart_stopping_reversal_applies_an_exploit_that_does_not_count_against_the_round():
    from combat.ext import needle

    me, foe, landed, hp, pending, events, engine = _reversal(["TAL_FENCING_ARM_STRIKE"], prepare=_feinted)
    assert _bears(foe, "needle_arm_strike") and needle._uses(me, engine) == 0


def test_heart_stopping_reversals_exploit_is_applied_even_after_the_rounds_own_exploit():
    from combat.ext import needle

    def prepare(engine, me, foe):
        _feinted(engine, me, foe)
        needle._count_use(me, engine)  # the round's one Exploit is already spent

    me, foe, landed, hp, pending, events, engine = _reversal(["TAL_FENCING_ARM_STRIKE"], prepare=prepare)
    assert _bears(foe, "needle_arm_strike") and needle._uses(me, engine) == 1  # and it did not count a second time


def test_heart_stopping_reversals_exploit_still_needs_the_normal_advantage_or_ally():
    me, foe, landed, hp, pending, events, _engine_ = _reversal(["TAL_FENCING_ARM_STRIKE"])
    assert _attacks_by(events, me.entity_id) and not _bears(foe, "needle_arm_strike")  # the text waives only the once-per-round limit


# ------------------------------------------------------------------------------------------------ Needle Through Ten Thousand Guards
GUARDS = ["TAL_FENCING_NEEDLE_THROUGH_TEN_THOUSAND_GUARDS", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE"]


def _guards(talents=GUARDS, *, positions=None, foes=2, answers=None):
    engine = _team(talents, foes=foes, positions=positions)
    _pin(engine, ATTACK=20, SAVE=1)
    seen = _answers(engine, answers or {})
    events = L4._use(engine, "Needle Through Ten Thousand Guards")
    return engine, engine.state.actors[FENCER], seen, events


def test_needle_through_ten_thousand_guards_attacks_each_chosen_creature_with_advantage_and_a_different_exploit_each():
    engine, me, seen, events = _guards()
    attacks = _attacks_by(events, FENCER)
    assert {tuple(e.target_ids) for e in attacks} == {(FOE1,), (FOE2,)} and all((e.payload or {}).get("mode") == "ADVANTAGE" for e in attacks)
    applied = [str((e.payload or {}).get("trigger", "")) for e in events if "applies Exploit" in str((e.payload or {}).get("trigger", ""))]
    assert len(applied) == 2 and any("Arm Strike" in line for line in applied) and any("Shadow Strike" in line for line in applied)
    assert me.resources[FOCUS] == 0  # the one Martial Focus the talent costs


def test_the_exploits_it_applies_do_not_count_against_the_rounds_own_exploit():
    from combat.ext import needle

    engine, me, seen, events = _guards()
    assert needle._uses(me, engine) == 0


def test_with_only_one_exploit_known_only_one_attack_gets_it():
    engine, me, seen, events = _guards(["TAL_FENCING_NEEDLE_THROUGH_TEN_THOUSAND_GUARDS", "TAL_FENCING_ARM_STRIKE"])
    assert len(_attacks_by(events, FENCER)) == 2
    assert len([e for e in events if "applies Exploit" in str((e.payload or {}).get("trigger", ""))]) == 1


def test_the_chosen_creatures_are_capped_at_the_proficiency_bonus_and_only_they_are_attacked():
    engine, me, seen, events = _guards(answers={"guards_targets": lambda request: request["extension_choice"]["option_ids"][:1]})
    spec = next(r for r in seen if r["reaction_source_id"].endswith("guards_targets"))["extension_choice"]
    assert spec["maximum_selections"] == min(int(me.proficiency_bonus), 2) and len(_attacks_by(events, FENCER)) == 1


def test_the_movement_walks_to_a_hostile_beyond_reach_and_attacks_it_on_the_way():
    engine, me, seen, events = _guards(positions={FOE1: (8, 6), FOE2: (12, 6)})
    attacks = _attacks_by(events, FENCER)
    assert {tuple(e.target_ids) for e in attacks} >= {(FOE1,)}  # the foe 3 squares away is reached and attacked on the way
    assert [e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FENCER]
    assert not [e for e in events if e.actor_id == FENCER and "opportunity" in str(e.source_definition_id).lower()]  # the weapon action, not the Opportunity Attack


def test_without_the_talent_the_action_is_not_offered():
    engine = _team(["TAL_FENCING_ARM_STRIKE"])
    assert not [c for c in engine.legal_candidates() if c.display_name == "Needle Through Ten Thousand Guards"]
