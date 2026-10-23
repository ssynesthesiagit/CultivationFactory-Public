"""Sphere typing review sw-blacksmith (Blacksmith, Blood, Brute): every corrected mechanic is compiled and used in a real engine.

Each case here failed on the typing this review replaced (bar a few controls that pin what was already right: the Crimson Wave save, the CL 5-10 dice,
Shift Weight out of reach, the Bloodied test itself): Forge Marks placed on a hostile creature (the "workpiece" is not the foe),
a Blood Thread that dealt only the Proficiency Bonus (no 1d8 to 4d8, and the bonus on every hit, not on a Bloodied target), Bloodied-only
saving throws that hit every creature at the start of every turn (with an unsaved 2d8 and a heal for allies), zones saved at cast time for
a creature that "starts its turn inside", damage dice that ignored the Cultivation Level table, a Heartblood Rebirth that neither held the
user at 1 HP nor stopped dying, a Heaven-Crashing Throw with no saving throw, a Hand That Repositioned Heaven with an extra 6d10 and no
use limit, a Court of the Moving Mountain that cost the user 10 feet of Speed, a Shift Weight that answered other creatures' misses, and a
Vital Transfusion that hurt only its own user (and was aimed at the enemy).
The text each one answers is in authority/typed_mechanics/rules_text.json; the corrections are in reviewed_final.d/review_sw-blacksmith.json
(and life.json for Blood Thread, ironclad.json for Read the Flaw, which earlier reviews had already touched, and the DeepSeek trigger overlay
for Shift Weight's subject). The Bloodied gate is combat/ext/blood_bloodied.py, Vital Transfusion's transfer combat/ext/blood_transfusion.py.
"""
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import combat.factory_compiler as fc
from combat import reaction_triggers, trigger_overlay, typed_reactions
from combat.flight import profile
from combat.ext import blood_bloodied
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX, bears_mark
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME, ALLY = "actor:factory.probe", "actor:factory.probe_ally"
QI, FOCUS = "resource:core.qi", "resource:core.martial_focus"
FAILS, PASSES = 40, -5  # the foe's saves total 0 to 24: a save against DC 40 is always failed, against DC -5 always passed
BLACKSMITH, BLOOD, BRUTE = "tianxia.sphere.blacksmith", "tianxia.sphere.blood", "tianxia.sphere.brute"
SMITH_BASE = ["BLACKSMITH_BASE_HAMMER_THE_MARK", "BLACKSMITH_BASE_SET_THE_WORKPIECE", "BLACKSMITH_BASE_READ_THE_FLAW"]
BLOOD_BASE = ["BLOOD_BASE_BLOOD_THREAD"]
BRUTE_BASE = ["BRUTE_BASE_BRUTAL_SHOVE", "BRUTE_BASE_BRUTE_MANEUVERS", "BRUTE_BASE_IMPACT_COLLISION", "BRUTE_BASE_SPECIAL_ATTACKS"]
FORGE_MARK, BLOOD_THREAD = "Forge Mark", "Blood Thread"
REVIEW_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-blacksmith.json"
LIFE_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/life.json"
IRONCLAD_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/ironclad.json"
OVERLAY_FILE = trigger_overlay.DEEPSEEK_PATH  # the file the trigger classifier reads
MECH = json.loads(Path(fc.TYPED_AUTHORITY).read_text())["mechanics"]

SMITH = "tianxia.talent.blacksmith."
FURNACE_COURT = SMITH + "furnace_court_of_the_thousandfold_temper"
LIVING_FORGE = SMITH + "incarnation_of_the_living_forge"
TWO_BEAT = SMITH + "two_beat_temper"
CRIMSON_COURT = "tianxia.talent.blood.crimson_court"
BLOOD_EMPEROR = "tianxia.talent.blood.blood_emperor_incarnation"
RIVERS = "tianxia.talent.blood.rivers_run_red"
SCARLET_MIST = "tianxia.talent.blood.scarlet_mist_form"
REBIRTH = "tianxia.talent.blood.heartblood_rebirth"
CRIMSON_WAVE = "tianxia.talent.blood.crimson_wave"
HEAVEN_CRASHING = "TAL_BRUTE_HEAVEN_CRASHING_THROW"
THE_HAND = "TAL_BRUTE_THE_HAND_THAT_REPOSITIONED_HEAVEN"
MOVING_MOUNTAIN = "TAL_BRUTE_COURT_OF_THE_MOVING_MOUNTAIN"
SHIFT_WEIGHT = "TAL_BRUTE_SHIFT_WEIGHT"
HAND_CREATURE = "The Hand That Repositioned Heaven: Creature"


# ---------------------------------------------------------------- helpers

def bundle(sphere, talents, base=(), cl=10, dc=FAILS, actor=ME):
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    sheet = {**SHEET, "equipment": [], "identity": {**SHEET["identity"], "cultivation_level": cl}, "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "learned_talent_record_ids": list(talents),
                                     "automatic_sphere_component_record_ids": list(base)}}
    return compile_character(sheet, actor_id=actor)


def engine(b, foe_at=(4, 6), ally_at=None, seed="SW-BLACKSMITH"):
    """The caster at (3, 6) on team a and the early Book 1 foe (55 HP) on team b, optionally with an ally; it is the caster's turn."""
    ids = [ME, AN] + ([ALLY] if ally_at else [])
    teams = {ME: "team:a", AN: "team:b", **({ALLY: "team:a"} if ally_at else {})}
    cells = {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}, **({ALLY: {"x": ally_at[0], "y": ally_at[1]}} if ally_at else {})}
    bundles = (copy.deepcopy(b),) + ((bundle(None, [], actor=ALLY),) if ally_at else ())
    e = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                              roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": cells})
    e.state.current_slot_index = e.state.initiative_order.index(ME)
    e.state.current_actor_id = ME
    e._system_start_turn()
    return e


def use(e, name, near=None):
    """Use the action called `name` (or 'name at <cell>' nearest `near`), with every attack roll made to hit."""
    picks = [c for c in e.legal_candidates() if c.display_name == name or c.display_name.startswith(name + " at ")]
    assert picks, f"{name} is not offered: " + ", ".join(sorted({c.display_name for c in e.legal_candidates()})[:40])
    if near is not None:
        picks.sort(key=lambda c: 0 if c.destination is None else abs(c.destination.x - near[0]) + abs(c.destination.y - near[1]))
    c = picks[0]
    typed = e.action_catalog[c.source_definition_id].parameters.get("typed")
    if isinstance(typed, dict) and isinstance(typed.get("numbers"), dict):
        typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}
    e.execute_intent(ActionIntent(intent_id=name, decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                  actor_id=ME, target_ids=c.target_ids, destination=c.destination))
    return c


def offered(e):
    return {c.display_name for c in e.legal_candidates()}


def next_turn(e):
    """End the current turn and let the next creature start theirs; returns whose turn it now is."""
    end = next(c for c in e.legal_candidates() if c.display_name == "End turn")
    e.execute_intent(ActionIntent(intent_id="end", decision_id=end.decision_id, candidate_id=end.candidate_id, state_version=end.state_version,
                                  actor_id=e.state.current_actor_id, target_ids=end.target_ids, destination=end.destination))
    return e.state.current_actor_id


def conditions(actor):
    return sorted((c.condition_id.removeprefix(CONDITION_PREFIX), c.expires_on) for c in actor.conditions.values())


def modifiers(actor):
    return sorted((m.target_field, m.value, m.expires_on) for m in actor.modifiers.values())


class Cast:
    """One ability used once by the caster against the foe, and what it did to the caster and the foe."""

    def __init__(self, sphere, base, talents, action, *, cl=10, foe_at=(4, 6), ally_at=None, dc=FAILS, foe_hp=None, foe_now=None,
                 ally_hp=None, focus=None, clear_hazards=False):
        b = bundle(sphere, list(talents), base=base, cl=cl, dc=dc)
        for attempt in range(12):  # a natural 1 misses whatever the attack bonus and a natural 20 doubles the dice, which says nothing about the typing: next seed
            self.engine = engine(b, foe_at=foe_at, ally_at=ally_at, seed=f"SW-BLACKSMITH-{attempt}")
            if clear_hazards:
                self.engine.grid.qi_hazard = frozenset()
            if foe_hp:
                self.foe.maximum_hp = self.foe.current_hp = foe_hp
            if foe_now is not None:  # a foe already hurt: the Bloodied checks
                self.foe.current_hp = foe_now
            if ally_hp is not None:
                self.ally.current_hp = ally_hp
            if focus is not None:
                self.me.resource_maximums[FOCUS] = max(self.me.resource_maximums.get(FOCUS, 0), focus)
                self.me.resources[FOCUS] = focus
            self.move0, self.foe0, self.hp0, self.n0 = self.me.movement_remaining_ft, self.cell(self.foe), self.foe.current_hp, len(self.engine.events)
            self.speed0 = self.engine._effective_speed(self.me)
            self.candidate = use(self.engine, action, near=foe_at)
            if not [x for x in self.engine.events[self.n0:] if x.event_type == "ATTACK_ROLLED" and x.payload.get("natural_result") in (1, 20)]:
                return
        raise AssertionError(f"{action}: twelve seeds in a row rolled a natural 1 or a natural 20")

    @staticmethod
    def cell(actor):
        return actor.position.x, actor.position.y

    @property
    def me(self):
        return self.engine.state.actors[ME]

    @property
    def foe(self):
        return self.engine.state.actors[AN]

    @property
    def ally(self):
        return self.engine.state.actors[ALLY]

    @property
    def pb(self):
        return int(self.engine.action_catalog[self.candidate.source_definition_id].parameters["typed"]["numbers"]["pb"])

    @property
    def moved(self):  # Speed the caster gained (or spent) by using the ability
        return self.me.movement_remaining_ft - self.move0

    @property
    def granted(self):  # feet of movement the ability handed out (MOVEMENT_GRANTED events)
        return sum(int(x.payload.get("distance_ft") or 0) for x in self.engine.events[self.n0:] if x.event_type == "MOVEMENT_GRANTED")

    @property
    def foe_damage(self):
        return self.hp0 - self.foe.current_hp

    @property
    def foe_conditions(self):
        return {name for name, _ in conditions(self.foe)}

    @property
    def foe_modifiers(self):
        return modifiers(self.foe)

    @property
    def me_modifiers(self):
        return modifiers(self.me)

    def dice(self):
        return [x.payload["expression"] for x in self.engine.events[self.n0:] if x.event_type == "DAMAGE_ROLLED"]

    def rolled(self):
        return sum(int(x.payload["total"]) for x in self.engine.events[self.n0:] if x.event_type == "DAMAGE_ROLLED")

    def committed(self):
        """The HP each separate blow took from the foe, in order."""
        return [int(x.payload["hp_damage"]) for x in self.engine.events[self.n0:] if x.event_type == "DAMAGE_COMMITTED" and AN in x.target_ids]

    def saves(self):
        return [x for x in self.engine.events[self.n0:] if x.event_type == "SAVE_ROLLED"]

    def next_turn(self):
        return next_turn(self.engine)

    def advance_to(self, actor_id):
        """Pass turns until `actor_id`'s turn has just started (the initiative order depends on the seed)."""
        for _ in range(8):
            if self.engine.state.current_actor_id == actor_id:
                return
            self.next_turn()
        raise AssertionError(f"never reached the turn of {actor_id}")


# ---------------------------------------------------------------- Blacksmith

# "Place 1 Forge Mark on it" -- the current workpiece, which is the smith's own (no creature is a workpiece): every Forge Mark row was aimed
# at "target", so the smith marked the hostile creature next to them, and the actions were not offered at all with nobody in reach.
# Incarnation enables optional marks; casting it alone places none.
# The service regression exercises its separate once-turn free-mark action.
FORGE_MARK_CASES = [
    pytest.param("Hammer the Mark", [], 10, True, id="hammer-the-mark"),
    pytest.param("Set the Workpiece", [], 10, False, id="set-the-workpiece"),
    pytest.param("Read the Flaw", [], 10, False, id="read-the-flaw"),
    pytest.param("Hammer the Mark", [TWO_BEAT], 10, True, id="two-beat-temper"),
    pytest.param("Furnace Court of the Thousandfold Temper", [FURNACE_COURT], 10, True, id="furnace-court"),
    pytest.param("Incarnation of the Living Forge", [LIVING_FORGE], 15, False, id="incarnation-of-the-living-forge"),
]


@pytest.mark.parametrize("foe_at", [pytest.param((4, 6), id="foe-adjacent"), pytest.param((12, 6), id="foe-far-away")])
@pytest.mark.parametrize("action,talents,cl,smith_holds_it", FORGE_MARK_CASES)
def test_forge_marks_go_on_the_smiths_workpiece_never_on_the_foe(action, talents, cl, smith_holds_it, foe_at):
    w = Cast(BLACKSMITH, SMITH_BASE, talents, action, cl=cl, foe_at=foe_at)
    assert not bears_mark(w.foe, ME, FORGE_MARK)
    assert bears_mark(w.me, ME, FORGE_MARK) == smith_holds_it


# ---------------------------------------------------------------- Blood

# owner/qi-armor-5 MOD1 (merge 5c892c64, owner edit 6904d30f):
# Blood Thread adds the Path key modifier once; this fixture's CON 14 gives +2.
@pytest.mark.parametrize("cl,dice", [pytest.param(1, "1d8+2", id="cl1"), pytest.param(4, "1d8+2", id="cl4"),
                                     pytest.param(5, "2d8+2", id="cl5"), pytest.param(10, "2d8+2", id="cl10"),
                                     pytest.param(11, "3d8+2", id="cl11"), pytest.param(16, "3d8+2", id="cl16"),
                                     pytest.param(17, "4d8+2", id="cl17"), pytest.param(20, "4d8+2", id="cl20")])
def test_blood_thread_deals_the_printed_dice_for_the_cultivation_level(cl, dice):
    # "The damage is 1d8 at CL 1-4, 2d8 at CL 5-10, 3d8 at CL 11-16, and 4d8 at CL 17-20": the typing had no dice at all, only the Proficiency Bonus
    w = Cast(BLOOD, BLOOD_BASE, [], "Blood Thread", cl=cl, foe_at=(8, 6), foe_hp=500)
    assert w.dice() == [dice]
    assert w.committed() == [w.rolled()]  # the foe is healthy: no Proficiency Bonus on top


@pytest.mark.parametrize("now,extra", [pytest.param(500, False, id="healthy"), pytest.param(251, False, id="one-hit-above-half"),
                                       pytest.param(250, True, id="exactly-half"), pytest.param(40, True, id="badly-hurt")])
def test_blood_thread_adds_the_proficiency_bonus_only_to_a_target_that_was_bloodied(now, extra):
    # "If the target is Bloodied, add your Proficiency Bonus to one damage roll": the bonus was added on every hit, and the printed test is made
    # before the hit's own damage (the bonus is part of that roll), so a hit that carries the foe across half its HP does not earn it (3d8 is at least 3)
    w = Cast(BLOOD, BLOOD_BASE, [], "Blood Thread", cl=15, foe_at=(8, 6), foe_hp=500, foe_now=now)
    assert w.committed() == [w.rolled()] + ([w.pb] if extra else [])


def test_blood_thread_lasts_until_the_start_of_the_casters_next_turn():
    # "apply Blood Thread until the start of your next turn": the mark was typed until_removed
    w = Cast(BLOOD, BLOOD_BASE, [], "Blood Thread", cl=15, foe_at=(8, 6), foe_hp=500)
    assert [expires for name, expires in conditions(w.foe) if name.startswith("mark.blood_thread")] == ["START_OF_MARKER_NEXT_TURN"]


def test_the_bloodied_test_reads_the_hp_before_the_attack_damage_only_when_asked_to():
    creature = SimpleNamespace(active=True, maximum_hp=100, current_hp=51)
    assert not blood_bloodied.is_bloodied(creature) and blood_bloodied.is_bloodied(creature, hp=50)
    assert blood_bloodied.is_bloodied(SimpleNamespace(active=True, maximum_hp=100, current_hp=50))
    assert not blood_bloodied.is_bloodied(SimpleNamespace(active=False, maximum_hp=100, current_hp=10))  # a dead or out creature is not "Bloodied"
    assert not blood_bloodied.is_bloodied(None)


def test_crimson_court_makes_only_a_bloodied_enemy_save_when_it_starts_its_turn_and_never_at_cast_or_for_healthy_ones():
    # "When a Bloodied enemy starts its turn inside, it makes a Constitution saving throw": an unsaved 2d8 to every creature, ally healing included
    w = Cast(BLOOD, BLOOD_BASE, [CRIMSON_COURT], "Crimson Court", cl=10, foe_hp=500)
    assert not w.saves() and w.foe_damage == 0
    assert w.next_turn() == AN and not w.saves() and w.foe_damage == 0  # healthy: nothing happens
    assert ("damage_resistance", "NECROTIC", "CONCENTRATION_END") in w.me_modifiers  # "You and Allies gain Resistance to Necrotic damage"


def test_crimson_court_failed_save_deals_2d8_and_stops_healing_until_its_next_turn():
    w = Cast(BLOOD, BLOOD_BASE, [CRIMSON_COURT], "Crimson Court", cl=10, foe_hp=500, foe_now=250, dc=FAILS)
    assert w.next_turn() == AN and len(w.saves()) == 1
    assert 2 <= w.foe_damage <= 16 and [m for m in w.foe_modifiers if m[0] == "healing_reduction"]


def test_crimson_court_passed_save_takes_half_damage_and_keeps_healing():
    w = Cast(BLOOD, BLOOD_BASE, [CRIMSON_COURT], "Crimson Court", cl=10, foe_hp=500, foe_now=250, dc=PASSES)
    assert w.next_turn() == AN and len(w.saves()) == 1
    assert 1 <= w.foe_damage <= 8 and not [m for m in w.foe_modifiers if m[0] == "healing_reduction"]


def test_crimson_court_does_not_heal_allies_for_the_proficiency_bonus_at_the_start_of_their_turns():
    # "receive additional healing equal to your Proficiency Bonus once per turn" adds to healing an ally receives; it heals nobody by itself
    w = Cast(BLOOD, BLOOD_BASE, [CRIMSON_COURT], "Crimson Court", cl=10, foe_hp=500, ally_at=(2, 6), ally_hp=10)
    w.advance_to(ALLY)
    assert w.ally.current_hp == 10


def test_blood_emperor_incarnation_saves_only_for_bloodied_enemies_starting_their_turns_and_marks_nobody_at_cast():
    # "When a Bloodied enemy starts its turn within 20 feet, it makes a Constitution saving throw. Failed Save: Take 4d8 Necrotic damage"
    w = Cast(BLOOD, BLOOD_BASE, [BLOOD_EMPEROR], "Blood Emperor Incarnation", cl=17, foe_hp=500)
    assert not w.saves() and w.foe_damage == 0 and not bears_mark(w.foe, ME, BLOOD_THREAD)
    assert {"BLUDGEONING", "PIERCING", "SLASHING", "NECROTIC"} <= {m[1] for m in w.me_modifiers if m[0] == "damage_resistance"}
    assert w.next_turn() == AN and not w.saves() and w.foe_damage == 0  # a healthy enemy is left alone


@pytest.mark.parametrize("dc,low,high", [pytest.param(FAILS, 4, 32, id="failed-4d8"), pytest.param(PASSES, 2, 16, id="passed-half")])
def test_blood_emperor_crimson_aura_deals_4d8_to_a_bloodied_enemy_and_half_on_a_save(dc, low, high):
    w = Cast(BLOOD, BLOOD_BASE, [BLOOD_EMPEROR], "Blood Emperor Incarnation", cl=17, foe_hp=500, foe_now=250, dc=dc)
    assert not w.saves() and w.foe_damage == 0  # even a Bloodied enemy saves when its turn starts, not when the Incarnation is taken
    assert w.next_turn() == AN and len(w.saves()) == 1 and low <= w.foe_damage <= high


def test_scarlet_mist_form_marks_nobody_when_taken_and_keeps_its_resistances_and_flight():
    # "apply Blood Thread automatically to one creature whose space you move through": it was applied to a target at once
    w = Cast(BLOOD, BLOOD_BASE, [SCARLET_MIST], "Scarlet Mist Form", cl=15)
    assert not bears_mark(w.foe, ME, BLOOD_THREAD)
    assert {"BLUDGEONING", "PIERCING", "SLASHING"} <= {m[1] for m in w.me_modifiers if m[0] == "damage_resistance"}
    fly = profile(w.engine, w.me)
    assert fly.speed_ft == 30 and fly.hover is True  # "Fly Speed 30 feet and Hover"
    assert w.engine._effective_speed(w.me) == w.speed0  # walking Speed is not raised


@pytest.mark.parametrize("cl,dice", [pytest.param(5, "4d6+0", id="cl5"), pytest.param(10, "4d6+0", id="cl10"), pytest.param(11, "6d6+0", id="cl11"),
                                     pytest.param(16, "6d6+0", id="cl16"), pytest.param(17, "8d6+0", id="cl17")])
def test_crimson_wave_damage_follows_the_cultivation_level_table(cl, dice):
    # "CL 5-10: 4d6, CL 11-16: 6d6, CL 17-20: 8d6": one flat number at every level
    assert Cast(BLOOD, BLOOD_BASE, [CRIMSON_WAVE], "Crimson Wave", cl=cl, foe_hp=500, dc=FAILS).dice() == [dice]


def test_crimson_wave_deals_half_on_a_passed_save():
    failed = Cast(BLOOD, BLOOD_BASE, [CRIMSON_WAVE], "Crimson Wave", cl=17, foe_hp=500, dc=FAILS)
    passed = Cast(BLOOD, BLOOD_BASE, [CRIMSON_WAVE], "Crimson Wave", cl=17, foe_hp=500, dc=PASSES)
    assert failed.foe_damage == failed.rolled() and 0 < passed.foe_damage <= 24 and passed.foe_damage == passed.rolled() // 2


def _rebirth(hp=10, qi=20, cl=15):
    e = engine(bundle(BLOOD, [REBIRTH], cl=cl))
    me = e.state.actors[ME]
    me.resource_maximums[QI] = max(me.resource_maximums.get(QI, 0), qi)
    me.resources[QI] = qi
    me.current_hp = hp
    return e, me


def test_heartblood_rebirth_holds_the_user_at_1_hp_in_a_cocoon_instead_of_dying():
    # "Trigger: You would die ... return with 1 HP ... gain 2d10 Temporary HP": the reaction did not stop the killing blow
    e, me = _rebirth(hp=10)
    pending = typed_reactions.on_damage(e, me, 999, 0, source_actor_id=AN)
    assert pending == 9  # only the damage that leaves 1 HP is dealt
    e._commit_damage(me, pending, "TEST", "system:test.lethal", AN, None, reaction_depth=0)
    assert me.current_hp == 1 and me.active
    assert [expires for name, expires in conditions(me) if name == "incapacitated"] == ["START_OF_SOURCE_NEXT_TURN"]  # "Until the start of your next turn"
    # "At the start of your next turn: ... regain CP equal to your Proficiency Bonus; gain 2d10 Temporary HP" (rider lane C5: they came at once)
    assert me.temporary_hp == 0 and me.resources[QI] == 20 - 10
    for _ in range(8):
        if next_turn(e) == ME:
            break
    assert 2 <= me.temporary_hp <= 20
    assert me.resources[QI] == 20 - 10 + SHEET["identity"]["proficiency_bonus"]  # 10 CP paid, then "regain CP equal to your Proficiency Bonus"


def test_heartblood_rebirth_does_not_add_15_to_armor_class():
    # "AC becomes 15": it was typed as a +15 bonus to the cocoon's Armor Class
    e, me = _rebirth(hp=10)
    e._commit_damage(me, typed_reactions.on_damage(e, me, 999, 0, source_actor_id=AN), "TEST", "system:test.lethal", AN, None, reaction_depth=0)
    assert me.armor_class + e._ac_modifier(me) == 15  # rider lane C5: "AC becomes 15" now runs, as a set


@pytest.mark.parametrize("dc,low,high,poisoned", [pytest.param(FAILS, 8, 64, True, id="failed-8d8-and-poisoned"),
                                                  pytest.param(PASSES, 4, 32, False, id="passed-half")])
def test_rivers_run_red_acts_when_a_creature_starts_its_turn_inside_not_when_cast(dc, low, high, poisoned):
    # "When a creature enters for the first time on a turn or starts its turn inside, it makes a Constitution saving throw": saved at cast time
    w = Cast(BLOOD, BLOOD_BASE, [RIVERS], "Rivers Run Red", cl=15, foe_at=(12, 6), foe_hp=500, dc=dc)
    assert not w.saves() and w.foe_damage == 0 and not w.foe_conditions
    assert w.next_turn() == AN and len(w.saves()) == 1 and low <= w.foe_damage <= high and ("poisoned" in w.foe_conditions) == poisoned


VITAL_TRANSFUSION = "tianxia.talent.blood.vital_transfusion"


class Transfusion:
    """Vital Transfusion used once by the caster on the ally beside them (or on themselves), the foe out of reach across the map:
    what each creature's HP did. `concentrating`: the caster holds Crimson Court first (the check the self-damage asks for)."""

    def __init__(self, cl=10, *, ally_missing=30, me_hp=None, temp=0, on=ALLY, concentrating=False):
        talents = ([CRIMSON_COURT] if concentrating else []) + [VITAL_TRANSFUSION]
        self.engine = engine(bundle(BLOOD, talents, base=BLOOD_BASE, cl=cl, dc=FAILS), foe_at=(12, 6), ally_at=(3, 7))
        if concentrating:
            use(self.engine, "Crimson Court")
            assert self.me.concentration is not None
            for _ in range(8):  # back to the caster's turn: the initiative order depends on the seed
                next_turn(self.engine)
                if self.engine.state.current_actor_id == ME:
                    break
            assert self.engine.state.current_actor_id == ME and self.me.concentration is not None
        self.ally.current_hp = self.ally.maximum_hp - ally_missing
        if me_hp is not None:
            self.me.current_hp = me_hp
        self.me.temporary_hp = temp
        self.before = SimpleNamespace(me=self.me.current_hp, ally=self.ally.current_hp, foe=self.foe.current_hp)
        offers = [c for c in self.engine.legal_candidates() if c.display_name == "Vital Transfusion"]
        self.aimed_at = sorted(i for c in offers for i in c.target_ids)
        picks = [c for c in offers if c.target_ids == (on,)]
        assert picks, f"Vital Transfusion cannot be aimed at {on}: offered at {self.aimed_at}"
        c = picks[0]
        self.n0 = len(self.engine.events)
        self.engine.execute_intent(ActionIntent(intent_id="vt", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                                actor_id=ME, target_ids=c.target_ids, destination=c.destination))

    me = property(lambda self: self.engine.state.actors[ME])
    ally = property(lambda self: self.engine.state.actors[ALLY])
    foe = property(lambda self: self.engine.state.actors[AN])
    lost = property(lambda self: self.before.me - self.me.current_hp)  # HP the caster gave up
    healed = property(lambda self: self.ally.current_hp - self.before.ally)  # HP the ally regained

    def events(self, event_type):
        return [x for x in self.engine.events[self.n0:] if x.event_type == event_type]

    def dice(self):
        return [x.payload["expression"] for x in self.events("DAMAGE_ROLLED")]

    def rolled(self):
        return sum(int(x.payload["total"]) for x in self.events("DAMAGE_ROLLED"))

    def checks(self):  # the Constitution saves for keeping concentration
        return [x for x in self.events("SAVE_ROLLED") if "combat.concentration" in x.payload["reason"]]


@pytest.mark.parametrize("cl,dice", [pytest.param(4, "1d8+2", id="cl4"), pytest.param(5, "2d8+2", id="cl5"), pytest.param(10, "2d8+2", id="cl10"),
                                     pytest.param(11, "3d8+2", id="cl11"), pytest.param(17, "4d8+2", id="cl17")])
def test_vital_transfusion_moves_the_rolled_hp_from_the_user_to_the_touched_ally(cl, dice):
    # "Up to 1d8 + your key ability modifier" ... "4d8" by CL; "One living creature you touch regains HP equal to the self-damage taken".
    # It was one self-damage row, 1d8 + key modifier at every level, aimed at the enemy by the compiler: the user hurt only itself.
    w = Transfusion(cl, ally_missing=59)
    assert w.aimed_at == sorted([ME, ALLY])  # a creature you touch (or yourself): never the enemy
    assert w.dice() == [dice]
    assert 0 < w.rolled() == w.lost == w.healed
    assert w.foe.current_hp == w.before.foe


def test_vital_transfusion_takes_only_what_the_touched_creature_can_use():
    # "choose how much self-damage to take, up to the rolled maximum": the ally is 3 HP short and the roll is 2d8+2 (at least 4)
    w = Transfusion(10, ally_missing=3)
    assert w.rolled() >= 4 and w.lost == 3 and w.healed == 3 and w.ally.current_hp == w.ally.maximum_hp


@pytest.mark.parametrize("hp,lost", [pytest.param(4, 3, id="4-hp-gives-3"), pytest.param(1, 0, id="1-hp-gives-nothing")])
def test_vital_transfusion_leaves_the_user_at_1_hp_and_never_spends_temporary_hp(hp, lost):
    # "cannot reduce you below 1 HP", "cannot be paid with Temporary HP"
    w = Transfusion(10, ally_missing=50, me_hp=hp, temp=20)
    assert w.me.current_hp == hp - lost >= 1 and w.me.temporary_hp == 20 and w.lost == w.healed == lost
    assert all(x.payload["temporary_hp_absorbed"] == 0 for x in w.events("DAMAGE_COMMITTED"))


@pytest.mark.parametrize("on,ally_missing", [pytest.param(ME, 30, id="touching-yourself"), pytest.param(ALLY, 0, id="ally-at-full-hp")])
def test_vital_transfusion_costs_the_user_nothing_when_nobody_can_regain_hp(on, ally_missing):
    w = Transfusion(10, ally_missing=ally_missing, on=on)
    assert w.lost == 0 and w.healed == 0 and not w.events("DAMAGE_COMMITTED")


def test_vital_transfusion_asks_a_concentrating_user_for_the_usual_check_on_the_damage_taken():
    # nothing printed exempts the self-damage: a Constitution save against DC 10 or half of it, as for any HP damage
    w = Transfusion(15, ally_missing=59, concentrating=True)
    # the ally stands inside the caster's Crimson Court: "receive additional healing equal to your Proficiency Bonus once per turn" (rider lane C5)
    assert w.lost > 0 and w.healed == w.lost + SHEET["identity"]["proficiency_bonus"]
    (check,) = w.checks()
    assert check.payload["dc"] == max(10, w.lost // 2)


# ---------------------------------------------------------------- Brute

@pytest.mark.parametrize("dc", [pytest.param(FAILS, id="failed-save"), pytest.param(PASSES, id="passed-save")])
def test_heaven_crashing_throw_damage_and_prone_wait_for_the_dexterity_save(dc):
    # "the target ... make Dexterity saving throws. Failed Save: Take 8d10 ... and fall Prone. Successful Save: Take half damage and remain standing":
    # 8d10 and Prone were dealt on every hit with no save
    # Native forced steps now resolve crossed map hazards. Isolate this throw's
    # own save and damage from unrelated Pillar Arena hazard damage.
    w = Cast(BRUTE, BRUTE_BASE, [HEAVEN_CRASHING], "Heaven-Crashing Throw", cl=15, foe_hp=500, dc=dc, focus=3, clear_hazards=True)
    assert [x.payload["reason"].rsplit(":", 1)[-1] for x in w.saves()] == ["DEX"]  # the thrown target's own save (nobody else is near its landing)
    if dc == FAILS:
        assert 8 <= w.foe_damage <= 80 and "prone" in w.foe_conditions
    else:
        assert w.foe_damage <= 40 and "prone" not in w.foe_conditions


@pytest.mark.parametrize("dc,condition", [pytest.param(FAILS, "stunned", id="failed-save-stunned"),
                                          pytest.param(PASSES, "reaction_denied", id="passed-save-no-reactions")])
def test_the_hand_that_repositioned_heaven_stuns_or_denies_reactions_and_adds_no_extra_damage(dc, condition):
    # "move the target up to 100 feet ... the target makes a Constitution saving throw. Failed Save: Stunned ... Successful Save: Cannot take
    # Reactions": an unconditional 6d10 was dealt as well (the +6d10 is for a collision, and no damage is printed for the shove itself)
    w = Cast(BRUTE, BRUTE_BASE, [THE_HAND], HAND_CREATURE, cl=17, foe_hp=500, dc=dc, focus=3)
    assert condition in w.foe_conditions
    assert not [d for d in w.dice() if "6d10" in d] and w.foe_damage == 0
    assert ("stunned" in w.foe_conditions) == (dc == FAILS)


def test_the_hand_that_repositioned_heaven_is_once_in_a_long_rest_not_once_a_week_unenforced():
    # "Use Limit: Once per week": `text:once per week` is not a use limit the engine counts, so it could be used every turn
    w = Cast(BRUTE, BRUTE_BASE, [THE_HAND], HAND_CREATURE, cl=17, foe_hp=500, focus=3)
    assert w.next_turn() == AN
    w.advance_to(ME)
    w.foe.position = type(w.foe.position)(x=4, y=6)  # the shove threw it 100 feet away: put it back within reach
    assert w.me.resources[FOCUS] >= 1  # it is the use limit, not a lack of Martial Focus or of a target, that keeps it from being offered again
    assert HAND_CREATURE not in offered(w.engine)


def test_court_of_the_moving_mountain_does_not_slow_its_user():
    # "reduce forced movement affecting you by 10 feet": typed as -10 feet of the user's own Movement
    w = Cast(BRUTE, BRUTE_BASE, [MOVING_MOUNTAIN], "Court of the Moving Mountain", cl=15, focus=3, foe_at=(12, 6))
    assert w.moved == 0 and w.granted == 0


def _shift_weight_engine(foe_at=(4, 6), cl=15):
    e = engine(bundle(BRUTE, [SHIFT_WEIGHT], base=BRUTE_BASE, cl=cl), foe_at=foe_at)
    me = e.state.actors[ME]
    me.resource_maximums[FOCUS] = max(me.resource_maximums.get(FOCUS, 0), 3)
    me.resources[FOCUS] = 3
    me.reaction_available = True
    return e, me, e.state.actors[AN]


def test_shift_weight_answers_an_attack_against_the_user_that_misses_not_another_creatures():
    # "Trigger: A creature fails an attack roll ... against you": the overlay named "a creature" as its subject, so it waited for a miss against
    # somebody else (ally_missed) and never fired for the Brute
    assert reaction_triggers.classify_mechanic(MECH[SHIFT_WEIGHT]).kind == "missed"
    e, me, foe = _shift_weight_engine()
    foe.skills = {"Athletics": -100, "Acrobatics": -100}  # rider lane C16: the shove is the printed Brutal Shove contest
    before = len(e.events)
    typed_reactions.on_attack_missed(e, foe, me, {"range_ft": None}, None)
    assert not me.reaction_available and me.resources[FOCUS] == 2  # the reaction and one Martial Focus are spent
    assert any(ev.event_type == "CHECK_ROLLED" for ev in e.events[before:])  # "Shove the triggering creature": the Brutal Shove contest
    prone = any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values())
    assert prone or (foe.position.x, foe.position.y) != (4, 6)  # pushed away or knocked Prone (the shover's choice), then the margin


def test_shift_weight_needs_the_attacker_within_reach_of_the_shove():
    e, me, foe = _shift_weight_engine(foe_at=(10, 6))  # 35 feet away: a ranged miss
    typed_reactions.on_attack_missed(e, foe, me, {"range_ft": 60}, None)
    assert me.reaction_available and me.resources[FOCUS] == 3 and (foe.position.x, foe.position.y) == (10, 6)


# ---------------------------------------------------------------- the data itself

def assert_built_in(key, entry):
    """A matching reviewed entry sets nonnull fields and removes explicitly null fields."""
    assert MECH[key]["typing_status"] == "reviewed_final", key  # a text edit that changes the hash would silently drop the correction
    assert MECH[key]["source"]["text_sha256"] == entry["text_sha256"], key
    for field, value in entry.items():
        if field not in ("text_sha256", "reviewed_by"):
            # MOD1's complete reviewed override (merge 5c892c64) supplies null
            # for absent fields. The builder removes these, rather than storing
            # null; require absence so stale inherited fields still fail here.
            if value is None:
                assert field not in MECH[key], (key, field)
            else:
                if field == "automation_coverage":
                    assert MECH[key]["coverage"] == value, (key, field)
                else:
                    assert MECH[key][field] == value, (key, field)


def test_every_correction_in_the_review_file_is_applied_to_its_current_rules_text():
    review = json.loads(REVIEW_FILE.read_text())["mechanics"]
    assert len(review) == 17
    for key, entry in review.items():
        assert entry["reviewed_by"].startswith("sweep sw-blacksmith ") and re.fullmatch(r"[0-9a-f]{64}", entry["text_sha256"]), key
        assert_built_in(key, entry)


@pytest.mark.parametrize("path,keys", [(LIFE_FILE, ["BLOOD_BASE_BLOOD_THREAD"]), (IRONCLAD_FILE, ["BLACKSMITH_BASE_READ_THE_FLAW"])],
                         ids=["life", "ironclad"])
def test_every_correction_in_the_earlier_reviews_files_is_applied_to_its_current_rules_text(path, keys):
    entries = json.loads(path.read_text())["mechanics"]
    for key in keys:
        assert_built_in(key, entries[key])


def test_the_printed_dice_tables_are_the_typed_ones():
    # Blood Thread: 1d8 / 2d8 / 3d8 / 4d8, Crimson Wave: 4d6 / 6d6 / 8d6 (the first attack row's damage carries the table)
    thread = MECH["BLOOD_BASE_BLOOD_THREAD"]["effects"][0]["on_hit"][0]
    assert thread["dice_by_cl"] == [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 20, 4, 8]]
    wave = json.dumps(MECH[CRIMSON_WAVE]["effects"])
    assert '"dice_by_cl": [[5, 10, 4, 6], [11, 16, 6, 6], [17, 20, 8, 6]]' in wave
    (transfusion,) = MECH[VITAL_TRANSFUSION]["effects"]  # Vital Transfusion Maximum: 1d8 / 2d8 / 3d8 / 4d8 + key modifier
    assert transfusion["dice_by_cl"] == [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 20, 4, 8]] and transfusion["formula"] == "key_ability_modifier"


def test_the_shift_weight_overlay_row_names_the_creature_attacked_as_you():
    rows = [json.loads(line) for line in OVERLAY_FILE.read_text().splitlines() if line.strip()]
    (row,) = [r for r in rows if r.get("mechanic_id") == SHIFT_WEIGHT]
    assert row["subject"] == "you"
