"""Automation push, lane 4 (passive abilities that were GM-only lines; owner 2026-09-29): every ability typed here is compiled
on a real character and run through the engine. The dice are scripted (``_script``) so a save or a critical hit lands exactly
where the case needs it.  Overrides: authority/typed_mechanics/reviewed_final.d/auto_lane4.json; plug-ins
combat/ext/lane4_*.py; labels combat/rules/feature_blocks.d/auto_lane4.json and feature_status.d/auto_lane4.json.
"""

import importlib
import json
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

import combat.factory_compiler as factory_compiler  # noqa: E402
from combat.factory_compiler import compile_character  # noqa: E402
from combat.gate2_runtime_models import ActionIntent  # noqa: E402
from combat.gate4_engine import Gate4ControllerEngine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ME = t.ME
SUBJ = "actor:factory.subject"
BRUTE = "tianxia.sphere.brute"
SHOVE_PRONE, GRAPPLE = "Shove: Prone", "Grapple"
BASE_DC = 8 + 4 + 3  # 8 + Proficiency Bonus + Strength modifier of the sheet the tests use


# ------------------------------------------------------------------------------------------------------- harness


def _sphere_of(mechanic_id):
    return t._mechanics()[mechanic_id]["sphere_id"]


def _script(engine, values):
    """The next dice this engine rolls come from ``values`` (in order); after that the seeded roller carries on."""
    queue = list(values)
    roller = engine.roller
    original = roller._die

    def _die(sides):
        if queue:
            counter = roller.counter
            roller.counter += 1
            return min(int(queue.pop(0)), sides), counter
        return original(sides)

    roller._die = _die
    return queue


def _duel(subject_talents, *, subject_sphere=None, subject_kit=None, attacker_talents=(), attacker_kit=None, attacker_sphere=BRUTE, cl=10):
    """ME (a Brute unless ``attacker_sphere`` says otherwise, so it has the unarmed Shove/Grapple options and a weapon) is on the
    move against SUBJ, who owns the talents."""
    subject_sphere = subject_sphere or (_sphere_of(subject_talents[0]) if subject_talents else None)
    mine = compile_character(t._sheet(attacker_sphere, list(attacker_talents), attacker_kit or {}, cl=cl), actor_id=ME)
    theirs = compile_character(t._sheet(subject_sphere, list(subject_talents), subject_kit or {}, cl=cl), actor_id=SUBJ)
    engine = Gate4ControllerEngine(ROOT, match_seed="LANE4", typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [ME, SUBJ], "team_by_actor": {ME: "team:a", SUBJ: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, SUBJ: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    t._ready(engine)
    return engine


def _use(engine, name):
    t._ready(engine)
    candidates = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == ME]
    assert candidates, f"{name!r} is not legal; legal: {sorted(c.display_name for c in engine.legal_candidates() if not c.display_name.startswith('Move'))}"
    candidate = candidates[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[before:]


def _saves(events):
    return [e.payload for e in events if e.event_type == "SAVE_ROLLED"]


def _has(actor, condition):
    return any(c.condition_id == f"condition:typed.{condition}" for c in actor.conditions.values())


def _new_turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


# ------------------------------------------------------------------------------------------------------- saves


def test_braced_body_adds_proficiency_bonus_to_one_push_save_until_the_next_turn():
    """Breath-Braced Body: +Proficiency Bonus to a Strength or Dexterity save against being pushed or knocked Prone, once until
    the start of your next turn (it was only a GM line, so the save was rolled bare)."""
    engine = _duel(["TAL_AIR_BREATH_BRACED_BODY"])
    _script(engine, [10, 10, 10, 10])
    first = _saves(_use(engine, SHOVE_PRONE))[0]
    assert first["dc"] == BASE_DC - 4  # +4 (Proficiency Bonus) folded into the roll
    assert _saves(_use(engine, SHOVE_PRONE))[0]["dc"] == BASE_DC  # spent until the start of SUBJ's next turn
    assert _saves(_use(engine, GRAPPLE))[0]["dc"] == BASE_DC  # a Grapple is neither a push nor a fall
    _new_turn(engine, SUBJ)
    _new_turn(engine, ME)
    assert _saves(_use(engine, SHOVE_PRONE))[0]["dc"] == BASE_DC - 4  # back after SUBJ's next turn began


def test_perfect_posture_turns_a_near_miss_into_a_success_for_proficiency_bonus_uses():
    """Perfect Posture: add 1d4 to a save against being knocked Prone or moved, after seeing the d20, Proficiency Bonus times."""
    engine = _duel(["tianxia.talent.beauty.perfect_posture"])
    subject = engine.state.actors[SUBJ]
    bonus = max(subject.saving_throws["STR"], subject.saving_throws["DEX"])
    near = BASE_DC - bonus - 2  # a d20 that fails the save by 2
    _script(engine, [near, 3])
    events = _use(engine, SHOVE_PRONE)
    assert not _has(subject, "prone")  # the d4 (3) covered the 2-point shortfall
    assert any(e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("d4") == 3 for e in events)
    # A failure the d4 cannot cover is not a use of the talent, and a d4 that comes up short is.
    _script(engine, [BASE_DC - bonus - 9])
    _use(engine, SHOVE_PRONE)
    assert _has(subject, "prone")
    used = sum(1 for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("d4"))
    assert used == 1
    engine._remove_condition(subject, "condition:typed.prone", "test")
    for _ in range(3):  # three more uses: Proficiency Bonus is 4
        _script(engine, [near, 4])
        _use(engine, SHOVE_PRONE)
        engine._remove_condition(subject, "condition:typed.prone", "test")
    _script(engine, [near, 4])
    _use(engine, SHOVE_PRONE)
    assert _has(subject, "prone")  # the fifth use does not exist
    assert sum(1 for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("d4")) == 4


def test_identify_rhythms_adds_half_proficiency_to_saves_against_an_analyzed_source():
    """Identify Rhythms: while you hold Martial Focus, +half Proficiency Bonus to saving throws against effects created by a
    creature you Analyzed."""
    from combat.ext.mind_hidden_eye import ANALYZED

    engine = _duel(["TAL_THE_HIDDEN_EYE_IDENTIFY_RHYTHMS"])
    subject, me = engine.state.actors[SUBJ], engine.state.actors[ME]
    _script(engine, [10, 10, 10])
    assert _saves(_use(engine, SHOVE_PRONE))[0]["dc"] == BASE_DC  # ME is not Analyzed
    engine._apply_condition(me, ANALYZED, "test", SUBJ, expires_on="UNTIL_REMOVED")
    subject.resources["resource:core.martial_focus"] = 0
    assert _saves(_use(engine, SHOVE_PRONE))[0]["dc"] == BASE_DC  # no Martial Focus
    subject.resources["resource:core.martial_focus"] = 1
    saved = _saves(_use(engine, SHOVE_PRONE))[0]
    assert saved["dc"] == BASE_DC
    assert saved["modifier"] == subject.saving_throws['STR'] + 2


# ------------------------------------------------------------------------------------------------ critical hits


def test_helmet_discipline_turns_one_critical_hit_into_a_normal_hit(monkeypatch):
    """Helmet Discipline: one critical hit against you becomes a normal hit, before damage is rolled (once until a long rest)."""
    from combat.ext import needle
    monkeypatch.setattr(needle, "ask", lambda *a, **kw: ["protected"])  # player confirms qualifying head protection
    engine = _duel(["tianxia.talent.equipment.helmet_discipline"], subject_sphere=None, attacker_kit=t.AXE_KIT)
    subject = engine.state.actors[SUBJ]
    axe = next(c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Fu (Short Axe) attack") and ":" not in c.display_name)
    hp = subject.current_hp
    _script(engine, [20, 6, 6])  # natural 20, then the doubled damage dice
    events = _use(engine, axe)
    committed = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED"][0]
    rolled = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"][0]
    assert not rolled["critical"] and len(rolled["dice"]) == 1
    assert committed["hp_damage"] == 6 + 3  # one d6 + Strength: the second (critical) d6 was turned back
    assert any(e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("critical_turned_normal") for e in events)
    assert subject.current_hp == hp - 9
    _script(engine, [20, 6, 6])  # the second critical hit is a critical hit
    again = [e.payload for e in _use(engine, axe) if e.event_type == "DAMAGE_COMMITTED"][0]
    assert again["hp_damage"] == 6 + 6 + 3


def _axe(engine):
    return next(c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Fu (Short Axe) attack") and ":" not in c.display_name)


def _hp_lost(events):
    return sum(e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED")


def test_find_gap_makes_a_natural_19_against_an_analyzed_creature_a_critical_hit():
    """Find Gap: attack rolls against creatures Analyzed by you score a Critical Hit on a 19 or 20 (critical = the damage dice
    are doubled). The engine crits on a natural 20 only, so the 19 was an ordinary hit."""
    from combat.ext.mind_hidden_eye import ANALYZED

    engine = _duel([], attacker_talents=["TAL_THE_HIDDEN_EYE_FIND_GAP"], attacker_sphere=_sphere_of("TAL_THE_HIDDEN_EYE_FIND_GAP"),
                   attacker_kit=t.AXE_KIT, subject_sphere=BRUTE)
    me, subject = engine.state.actors[ME], engine.state.actors[SUBJ]
    axe = _axe(engine)
    _script(engine, [19, 5, 4])  # the hit, then its d6 (5), then the second d6 (4) the crit adds
    plain = _use(engine, axe)
    assert _hp_lost(plain) == 5 + 3 and not [e for e in plain if e.event_type == "PASSIVE_TRIGGERED"]  # ME has not Analyzed SUBJ yet
    engine._apply_condition(subject, ANALYZED, "test", ME, expires_on="UNTIL_REMOVED")
    t._ready(engine)
    _script(engine, [19, 5, 4])
    crit = _use(engine, axe)
    assert _hp_lost(crit) == 5 + 3 + 4  # d6 + Strength, and the second d6
    assert len([e for e in crit if e.event_type == "DAMAGE_COMMITTED"]) == 1
    assert any(e.event_type == "DAMAGE_ROLLED" and e.payload.get("critical") for e in crit)
    t._ready(engine)
    _script(engine, [18, 5, 4])  # an 18 is an ordinary hit
    assert _hp_lost(_use(engine, axe)) == 5 + 3
    t._ready(engine)
    _script(engine, [20, 5, 4])  # a 20 is the engine's own crit: the plug-in adds nothing on top of it
    natural = _use(engine, axe)
    assert _hp_lost(natural) == 5 + 4 + 3 and not [e for e in natural if e.event_type == "PASSIVE_TRIGGERED"]


def test_physical_examination_adds_wisdom_medicine_as_an_analyze_check_option():
    """Physical Examination: "You may use Wisdom (Medicine) when attempting to Analyze a creature" -- a third check beside
    Investigation and Perception. Choose Medicine before rolling one d20, as the printed Analyze rule requires."""
    talent = "TAL_THE_HIDDEN_EYE_PHYSICAL_EXAMINATION"
    sphere = _sphere_of(talent)
    engine = _duel([], attacker_talents=[talent], attacker_sphere=sphere, subject_sphere=BRUTE)
    for bundle in engine.typed_bundle_documents:
        if bundle.get("actor_id") == ME:
            bundle.setdefault("skills", {})["Medicine"] = 30
    _script(engine, [20])
    events = _use(engine, "Analyze")
    assert "CHECK:analyze:medicine" in [getattr(roll, "reason", "") for roll in engine.rolls]
    assert [e.payload["success"] for e in events if e.event_type == "CHECK_ROLLED"] == [True]
    plain = _duel([], attacker_talents=[], attacker_sphere=sphere, subject_sphere=BRUTE)
    _script(plain, [1, 1, 20])
    events = _use(plain, "Analyze")
    assert "CHECK:analyze:medicine" not in [getattr(roll, "reason", "") for roll in plain.rolls]
    assert [e.payload["success"] for e in events if e.event_type == "CHECK_ROLLED"] == [False]  # no third check to take the 20


def _parry_duel(talents):
    """SUBJ (holding a staff and Martial Focus) is shot by ME from 30 feet."""
    bow_only = {"starting_kit": {"items": [t.BOW_KIT["starting_kit"]["items"][0]]}}
    staff = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gun", "name": "Gun", "quantity": 1}]}}
    engine = _duel(talents, subject_sphere=_sphere_of("TAL_FENCING_PARRY_ANYTHING"), attacker_kit=bow_only,
                   subject_kit=staff)
    subject = engine.state.actors[SUBJ]
    subject.position = type(subject.position)(x=9, y=6)
    subject.resources["resource:core.martial_focus"] = 1
    return engine, subject


def test_parry_anything_lets_parry_and_riposte_answer_a_ranged_weapon_hit():
    """Parry Anything: you may use Parry and Riposte when a ranged weapon attack or ranged spell attack hits you (the row was
    melee-only, so an arrow always landed whole)."""
    bow = "Gong Jian (Bow and Arrow) attack"
    engine, subject = _parry_duel(["TAL_FENCING_PARRY_AND_RIPOSTE"])
    _script(engine, [15, 6])
    assert _hp_lost(_use(engine, bow)) == 6 + 3  # no Parry Anything: the arrow lands whole
    assert subject.reaction_available
    engine, subject = _parry_duel(["TAL_FENCING_PARRY_AND_RIPOSTE", "TAL_FENCING_PARRY_ANYTHING"])
    _script(engine, [15, 2, 6])  # the hit, the parry's d8 (2 + Strength-or-Dexterity 3 = 5 off), the arrow's d8 (6 + 3 = 9)
    events = _use(engine, bow)
    assert _hp_lost(events) == 9 - 5
    assert not subject.reaction_available and subject.resources["resource:core.martial_focus"] == 0  # the Reaction and the Focus were spent


def test_mountain_root_body_gives_the_first_creature_that_misses_a_dodging_owner_a_burden_mark():
    """Mountain-Root Body: when you take the Dodge action, you may give one creature that misses you before the start of your
    next turn one Burden Mark."""
    from combat.typed_executor import bears_mark

    engine = _duel(["TAL_EARTH_MOUNTAIN_ROOT_BODY"], attacker_kit=t.AXE_KIT)
    me, subject = engine.state.actors[ME], engine.state.actors[SUBJ]
    axe = _axe(engine)
    _script(engine, [2])  # a miss, but SUBJ has not taken the Dodge action
    _use(engine, axe)
    assert not bears_mark(me, SUBJ, "Burden Mark")
    engine._apply_condition(subject, "condition:core.dodge", "test", SUBJ, expires_on="START_OF_SELF_NEXT_TURN")
    t._ready(engine)
    _script(engine, [20, 20, 4])  # a hit is no miss (Dodge gives the attacker Disadvantage: two d20s)
    _use(engine, axe)
    assert not bears_mark(me, SUBJ, "Burden Mark")
    t._ready(engine)
    _script(engine, [2])
    events = _use(engine, axe)
    assert bears_mark(me, SUBJ, "Burden Mark")
    assert any(e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("mark") == "Burden Mark" for e in events)
    engine._remove_condition(me, next(c.condition_id for c in me.conditions.values() if c.condition_id.startswith("condition:typed.mark.burden")), "test")
    t._ready(engine)
    _script(engine, [2])
    _use(engine, axe)
    assert not bears_mark(me, SUBJ, "Burden Mark")  # one creature (one miss) per Dodge
    _new_turn(engine, SUBJ)  # the Dodge ends at the start of SUBJ's next turn, and so does that "one"
    assert not any(c.condition_id == "condition:core.dodge" for c in subject.conditions.values()) and not subject.turn_flags.get("lane4_mountain_root_burden")


DUAL_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.duan_jian", "name": "Duan Jian", "quantity": 1},
                                       {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou", "quantity": 1}]}}


def test_combo_maneuvers_replaces_the_paired_strike_with_an_unarmed_grapple_or_shove():
    """Combo Maneuvers: when you would make your Paired Strike (the off-hand attack after the Attack action), replace it with one
    Unarmed Strike used only for its Grapple or Shove option."""
    talent = "TAL_DUAL_WIELDING_COMBO_MANEUVERS"
    engine = _duel([], attacker_talents=[talent], attacker_sphere=_sphere_of(talent), attacker_kit=DUAL_KIT, subject_sphere=BRUTE)
    me, subject = engine.state.actors[ME], engine.state.actors[SUBJ]
    subject.saving_throws = {key: -100 for key in subject.saving_throws}  # every save fails
    names = lambda: {c.display_name for c in engine.legal_candidates() if c.actor_id == ME}  # noqa: E731
    combo = "Combo Maneuvers: Shove: Prone (Bi Shou)"
    assert not any(name.startswith("Combo Maneuvers") for name in names())  # no Attack-action attack yet, so no Paired Strike to replace
    _use(engine, "Duan Jian (Short Sword) attack")
    assert {"Bi Shou (Dagger) off-hand attack", combo, "Combo Maneuvers: Shove: Push 5 ft (Bi Shou)"} <= names()
    assert "Combo Maneuvers: Grapple (Bi Shou)" not in names()  # Both weapons occupy the hands; Grapple needs a free hand.
    assert not any("(Duan Jian)" in name for name in names())  # the short sword is not Paired: it has no Paired Strike to replace
    events = _use(engine, combo)
    assert _saves(events) and _has(subject, "prone")
    assert not any(name.startswith("Combo Maneuvers") or name == "Bi Shou (Dagger) off-hand attack" for name in names())  # one or the other


# --------------------------------------------------------------------------------------------------------- Brute


def _brute_engine(talents, *, kit=None, foe_at=(4, 6)):
    bundle = t._bundle(BRUTE, talents, kit or {}, cl=10)
    engine = t._engine(bundle, foe_at=foe_at)
    foe = engine.state.actors[t.AN]
    for key in list(foe.saving_throws):
        foe.saving_throws[key] = -100  # every save the foe makes fails
    foe.skills = {"Athletics": -100, "Acrobatics": -100}  # and every Brutal Shove contest (the printed contest, rider lane C16)
    engine.state.actors[ME].position = type(foe.position)(x=foe.position.x - 1, y=foe.position.y)
    return engine, foe


def test_takedown_grapples_a_shoved_target_that_is_still_within_reach():
    """Takedown: after the shove succeeds, if the target remains within reach, attempt to Grapple it. (Brutal Shove pushes the
    target away, so it is still in reach when the push is cut short: the target stands at the edge of the map.)"""
    engine, foe = _brute_engine(["TAL_BRUTE_TAKEDOWN"], foe_at=(19, 6))
    assert "Brutal Shove + Takedown" in t._legal(engine)
    _use_t = t._use(engine, "Brutal Shove + Takedown")
    assert any(e.event_type == "SAVE_ROLLED" for e in _use_t)
    assert _has(foe, "grappled")
    assert _has(foe, "prone")


def test_takedown_makes_no_grapple_attempt_when_the_target_was_moved_out_of_reach():
    engine, foe = _brute_engine(["TAL_BRUTE_TAKEDOWN"], foe_at=(4, 6))
    # Native forced movement now resolves crossed hazards. Isolate the Grapple
    # save here; an unrelated Qi hazard save is not a Takedown attempt.
    engine.grid.qi_hazard = set()
    events = t._use(engine, "Brutal Shove + Takedown")
    assert not [e for e in events if e.event_type == "SAVE_ROLLED"]
    assert not _has(foe, "grappled")


def test_follow_through_offers_a_bonus_action_shove_after_a_melee_weapon_hit_that_damaged():
    """Follow-Through: after you damage a creature with a melee weapon attack, shove that creature as a Bonus Action."""
    engine, foe = _brute_engine(["TAL_BRUTE_FOLLOW_THROUGH"], kit=t.AXE_KIT)
    assert "Follow-Through: Brutal Shove" not in t._legal(engine)  # nobody was damaged yet
    t._use(engine, "Fu (Short Axe) attack")
    assert "Follow-Through: Brutal Shove" in t._legal(engine)
    me = engine.state.actors[ME]
    me.action_available = False
    events = t._use(engine, "Follow-Through: Brutal Shove")
    assert any(e.event_type == "CHECK_ROLLED" for e in events)  # the Brutal Shove contest (rider lane C16; was an attack roll)
    assert any(e.event_type == "MOVEMENT_COMMITTED" for e in events)  # the shove moved it
    assert not me.bonus_action_available
    assert "Follow-Through: Brutal Shove" not in t._legal(engine)
