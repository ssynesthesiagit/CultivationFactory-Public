"""Sphere typing review sw-air (Air, Alchemy, Ash): every corrected mechanic is compiled and used in a real engine.

Each case here failed on the typing this review replaced: a `movement` effect aimed at somebody else that gave the caster free Speed,
blanket Disadvantage and Prone on options that only print a rider, saves cast at once for areas that act when a creature starts its turn,
damage dice that ignored the Cultivation Level table, an Explosive Pill with no range, reactions that cost nothing, and so on. The text
each one answers is in authority/typed_mechanics/rules_text.json; the corrections are in reviewed_final.d/review_sw-air.json (and life.json
for the three Alchemy keys another review had already touched, elements.json for the five Air Vectors an earlier review had already touched,
and combat/rules/summons.json for the Ash Clone). The Alchemy pills also answer one engine fact: a Bonus Action or Action the consumer takes
for itself compiles to a SELF action that passes no targets, so an effect aimed at "target" recovers nothing.
"""
import copy
import json
import re
import statistics
from pathlib import Path

import pytest

import combat.factory_compiler as fc
from combat import summons, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX
from tests import test_summons as summon_tests
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME, ALLY = "actor:factory.probe", "actor:factory.probe_ally"
QI, STOCK = "resource:core.qi", "resource:named.reagent_stock"
FAILS, PASSES = 40, -5  # the foe's saves total 0 to 24: a save against DC 40 is always failed, against DC -5 always passed
AIR, ALCHEMY, ASH = "tianxia.sphere.air", "tianxia.sphere.alchemy", "tianxia.sphere.ash"
AIR_BASE = ["AIR_BASE_GATHER_CURRENT", "AIR_BASE_WIND_LASH"]
ALCHEMY_BASE = ["ALCHEMY_BASE_FIELD_FORMULA"]
ASH_BASE = ["ASH_BASE_ASHFALL", "ASH_BASE_CINDER_BRAND"]
REVIEW_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-air.json"
ELEMENTS_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/elements.json"
ELEMENTS_KEYS = ["TAL_AIR_DRAWING_BREATH", "TAL_AIR_GALE_PUSH", "TAL_AIR_PRESSURE_BREAK", "TAL_AIR_BREATH_STEALING_PALM", "TAL_AIR_SKY_STEP"]
LIFE_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/life.json"
LIFE_KEYS = ["TAL_ALCHEMY_EXPLOSIVE_PILL", "tianxia.talent.alchemy.court_of_the_three_legged_cauldron", "TAL_ALCHEMY_PILL_OF_RESTORATION"]


# ---------------------------------------------------------------- helpers

def bundle(sphere, talents, cl=10, dc=FAILS, actor=ME, body=False):
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    identity = {**SHEET["identity"], "cultivation_level": cl}
    if body:  # a Body Refining character, whose CP pool is Stamina
        identity["path"], stats["primary_resource"] = "Body Refining", {"name": "Stamina", "maximum": 30}
    sheet = {**SHEET, "equipment": [], "identity": identity, "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=actor)


def action_names(b):
    return [row["display_name"] for row in b["action_catalog"]]


def engine(b, foe_at=(4, 6), ally_at=None, seed="SW-AIR"):
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

    def __init__(self, sphere, base, talents, action, *, cl=10, foe_at=(4, 6), ally_at=None, dc=FAILS, foe_hp=None, stock=None, hp=None,
                 pool=None, body=False):
        b = bundle(sphere, list(base) + list(talents), cl=cl, dc=dc, body=body)
        for attempt in range(12):  # a natural 1 misses whatever the attack bonus, which says nothing about the typing: fresh fight, next seed
            self.engine = engine(b, foe_at=foe_at, ally_at=ally_at, seed=f"SW-AIR-{attempt}")
            if foe_hp:
                self.foe.maximum_hp = self.foe.current_hp = foe_hp
            if stock is not None:
                self.me.resources[STOCK] = stock
            if hp is not None:
                self.me.current_hp = hp
            if pool is not None:  # (resource id, amount): start with less than a full pool so a recovery shows
                self.me.resources[pool[0]] = pool[1]
            self.move0, self.foe0, self.hp0, self.n0 = self.me.movement_remaining_ft, self.cell(self.foe), self.foe.current_hp, len(self.engine.events)
            use(self.engine, action, near=foe_at)
            if not [x for x in self.engine.events[self.n0:] if x.event_type == "ATTACK_ROLLED" and x.payload.get("natural_result") == 1]:
                return
        raise AssertionError(f"{action}: twelve seeds in a row rolled a natural 1")

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
    def moved(self):  # Speed the caster gained (or spent) by using the ability
        return self.me.movement_remaining_ft - self.move0

    @property
    def granted(self):  # feet of movement the ability handed out (MOVEMENT_GRANTED events)
        return sum(int(x.payload.get("distance_ft") or 0) for x in self.engine.events[self.n0:] if x.event_type == "MOVEMENT_GRANTED")

    @property
    def foe_cell(self):
        return self.cell(self.foe)

    @property
    def foe_damage(self):
        return self.hp0 - self.foe.current_hp

    @property
    def foe_conditions(self):
        return {name for name, _ in conditions(self.foe)}

    @property
    def foe_modifiers(self):
        return modifiers(self.foe)

    def foe_attack_mode(self):
        return [m for m in self.foe_modifiers if m[0] == "attack_mode"]

    def dice(self):
        return [x.payload["expression"] for x in self.engine.events[self.n0:] if x.event_type == "DAMAGE_ROLLED"]

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


# ---------------------------------------------------------------- Air

# Each of these typed a `movement` effect on somebody else's turn-to-come (an ally, a target, "your Wind Lash range becomes 300 feet"): the
# executor gives the *actor* the distance, so the caster gained 5 to 300 feet of free Speed. None of the printed texts moves the caster.
NO_FREE_MOVEMENT = [
    pytest.param(AIR, AIR_BASE, [], "Gather Current: Lift", 17, (5, 6), id="gather-current-lift"),
    pytest.param(AIR, AIR_BASE, ["TAL_AIR_WIND_SCRIPT_DELIVERY"], "Gather Current: Scatter", 17, (5, 6), id="wind-script-delivery"),
    pytest.param(AIR, AIR_BASE, [], "Wind Lash: Lift", 17, (4, 6), id="wind-lash-lift"),
    pytest.param(AIR, AIR_BASE, ["TAL_AIR_CYCLONE_PRISON"], "Cyclone Prison", 17, (5, 6), id="cyclone-prison"),
    pytest.param(AIR, AIR_BASE, ["TAL_AIR_DOWNBURST_SEAL"], "Downburst Seal", 17, (5, 6), id="downburst-seal"),
    pytest.param(AIR, AIR_BASE, ["TAL_AIR_HEAVEN_SPLITTING_GALE"], "Heaven-Splitting Gale", 17, (5, 6), id="heaven-splitting-gale"),
    pytest.param(AIR, AIR_BASE, ["TAL_AIR_SKY_SOVEREIGN_INCARNATION"], "Sky-Sovereign Incarnation", 17, (4, 6), id="sky-sovereign"),
    pytest.param(AIR, AIR_BASE, ["TAL_AIR_UPDRAFT_GATE"], "Updraft Gate", 17, (5, 6), id="updraft-gate"),
    pytest.param(ASH, ASH_BASE, [], "Cinder Brand: Move Remnant", 11, (5, 6), id="cinder-brand-move-remnant"),
]


@pytest.mark.parametrize("sphere,base,talents,action,cl,foe_at", NO_FREE_MOVEMENT)
def test_using_the_ability_gives_the_caster_no_free_speed(sphere, base, talents, action, cl, foe_at):
    assert Cast(sphere, base, talents, action, cl=cl, foe_at=foe_at).moved == 0


def test_wind_lash_pull_draws_the_target_toward_the_caster_and_push_still_pushes():
    assert Cast(AIR, AIR_BASE, [], "Wind Lash: Pull", cl=17, foe_at=(8, 6)).foe_cell == (7, 6)  # "pulled 5 feet toward you", not away
    assert Cast(AIR, AIR_BASE, [], "Wind Lash: Push", cl=17, foe_at=(4, 6)).foe_cell == (5, 6)


@pytest.mark.parametrize("dc,cell", [pytest.param(FAILS, (6, 6), id="failed-save-10-feet"), pytest.param(PASSES, (7, 6), id="passed-save-5-feet")])
def test_drawing_breath_pulls_the_target_toward_the_caster(dc, cell):
    # "Pull the target 10 feet directly toward you" / "Pull the target 5 feet": typed without a direction, so the target was blown away (to 10,6 / 9,6)
    assert Cast(AIR, AIR_BASE, ["TAL_AIR_DRAWING_BREATH"], "Wind Lash: Cut + Drawing Breath", cl=10, foe_at=(8, 6), dc=dc).foe_cell == cell


@pytest.mark.parametrize("talent,action,feet", [("TAL_AIR_GALE_PUSH", "Wind Lash: Cut + Gale Push", 10), ("TAL_AIR_PRESSURE_BREAK", "Wind Lash: Cut + Pressure Break", 20)])
def test_gale_push_and_pressure_break_only_knock_the_target_prone_when_it_collides_with_something(talent, action, feet):
    # Prone was typed on every failed save; the printed text gives it "if the target collides with a solid obstacle", and nothing is in the way here
    w = Cast(AIR, AIR_BASE, [talent], action, cl=10, foe_at=(4, 6), dc=FAILS)
    assert w.foe_cell == (4 + feet // 5, 6) and "prone" not in w.foe_conditions


def test_breath_stealing_palm_weakens_concentration_but_does_not_take_the_targets_reactions():
    # "cannot shout commands" was typed as a Reaction denial; the printed effects are the whisper, the commands and Concentration saves
    w = Cast(AIR, AIR_BASE, ["TAL_AIR_BREATH_STEALING_PALM"], "Wind Lash: Cut + Breath-Stealing Palm", cl=10, dc=FAILS)
    assert "concentration_mode" in w.foe_conditions and "reaction_denied" not in w.foe_conditions


@pytest.mark.parametrize("cl,feet", [(10, 10), (11, 20)])
def test_sky_step_moves_ten_feet_and_twenty_from_cultivation_level_11(cl, feet):
    # "up to 10 feet ... At CL 11, this movement increases to 20 feet": the movement was typed as 10 feet at every level
    assert Cast(AIR, AIR_BASE, ["TAL_AIR_SKY_STEP"], "Gather Current: Lift + Sky-Step", cl=cl, foe_at=(5, 6)).granted == feet


def test_wind_lash_scatter_moves_an_object_not_the_target():
    w = Cast(AIR, AIR_BASE, [], "Wind Lash: Scatter", cl=17)
    assert w.foe_cell == w.foe0 and w.foe_damage > 0


def test_cyclone_prison_restrains_on_a_failed_save_and_pushes_nobody():
    failed = Cast(AIR, AIR_BASE, ["TAL_AIR_CYCLONE_PRISON"], "Cyclone Prison", cl=17, foe_at=(5, 6), dc=FAILS)
    assert "restrained" in failed.foe_conditions and failed.foe_cell == (5, 6)  # the pull toward the centre is a rider, not a push away
    passed = Cast(AIR, AIR_BASE, ["TAL_AIR_CYCLONE_PRISON"], "Cyclone Prison", cl=17, foe_at=(5, 6), dc=PASSES)
    assert "restrained" not in passed.foe_conditions and passed.foe_cell == (5, 6)


def test_downburst_seal_hits_and_knocks_prone_on_a_failed_save_and_only_half_damage_on_a_passed_one():
    failed = Cast(AIR, AIR_BASE, ["TAL_AIR_DOWNBURST_SEAL"], "Downburst Seal", cl=17, foe_at=(5, 6), dc=FAILS)
    assert failed.foe_damage > 0 and "prone" in failed.foe_conditions
    passed = Cast(AIR, AIR_BASE, ["TAL_AIR_DOWNBURST_SEAL"], "Downburst Seal", cl=17, foe_at=(5, 6), dc=PASSES)
    assert 0 < passed.foe_damage < failed.foe_damage and "prone" not in passed.foe_conditions


@pytest.mark.parametrize("option", ["No Straight Line", "No Steady Foot", "No Safe Breath", "No Fixed Direction"])
def test_storm_without_direction_options_do_not_hand_out_blanket_disadvantage_or_prone(option):
    w = Cast(AIR, AIR_BASE, ["TAL_AIR_STORM_WITHOUT_DIRECTION"], f"Storm Without Direction: {option}", cl=17)
    assert not w.foe_attack_mode()  # the printed effect is a rider (the GM applies it to attacks that pass through the area)
    assert "prone" not in w.foe_conditions and not w.saves()  # No Steady Foot's save is about moving more than half Speed, not casting


def test_gather_current_turn_does_not_hinder_the_foe():
    w = Cast(AIR, AIR_BASE, [], "Gather Current: Turn", cl=17, foe_at=(5, 6))
    assert not w.foe_attack_mode()  # "the first ordinary Tiny projectile ... has Disadvantage": a rider


@pytest.mark.parametrize("talent,action", [("TAL_AIR_UPDRAFT_GATE", "Updraft Gate"), ("TAL_AIR_SKY_ROAD", "Sky Road")])
def test_updraft_gate_and_sky_road_do_nothing_to_creatures_when_cast(talent, action):
    w = Cast(AIR, AIR_BASE, [talent], action, cl=17, foe_at=(5, 6))
    assert w.foe_cell == (5, 6) and "prone" not in w.foe_conditions and not w.saves() and w.moved == 0


def test_breathless_chamber_acts_when_the_foe_starts_its_turn_not_when_cast():
    w = Cast(AIR, AIR_BASE, ["TAL_AIR_BREATHLESS_CHAMBER"], "Breathless Chamber", cl=17, foe_hp=500)
    assert not w.saves() and not w.foe_conditions
    assert w.next_turn() == AN and w.saves() and {"concentration_mode", "reaction_denied"} <= w.foe_conditions


def test_wind_wall_slows_when_the_foe_starts_its_turn_not_when_cast():
    w = Cast(AIR, AIR_BASE, ["TAL_AIR_WIND_WALL"], "Wind Wall", cl=17, foe_hp=500)
    assert not w.saves() and not w.foe_modifiers
    assert w.next_turn() == AN and [m for m in w.foe_modifiers if m[0] == "speed_ft" and m[1] == -10]


def test_vacuum_needle_adds_damage_and_blocks_healing_only_when_the_save_is_failed():
    for cl, extra in ((10, "1d8+0"), (11, "2d8+0")):
        failed = Cast(AIR, AIR_BASE, ["TAL_AIR_VACUUM_NEEDLE"], "Wind Lash: Cut", cl=cl, foe_at=(5, 6), dc=FAILS)
        # Wind Lash's automatic damage selection ties to bludgeoning; Cut is
        # the reaction-denial vector, not a selection of slashing damage.
        assert extra not in failed.dice() and not [m for m in failed.foe_modifiers if m[0] == "healing_reduction"], cl
        for dc, fails in ((FAILS, True), (PASSES, False)):
            e = engine(bundle(AIR, AIR_BASE + ["TAL_AIR_VACUUM_NEEDLE"], cl=cl, dc=dc), foe_at=(5, 6), seed="SW-AIR-0")
            e._add_modifier(e.state.actors[AN], "test:resist", "damage_resistance", "SET", "BLUDGEONING", "SELF", expires_on="UNTIL_REMOVED")
            start = len(e.events)
            use(e, "Wind Lash: Cut")
            assert (extra in [x.payload["expression"] for x in e.events[start:] if x.event_type == "DAMAGE_ROLLED"]) == fails
            assert (("healing_reduction", "none") in {m[:2] for m in modifiers(e.state.actors[AN])}) == fails


def test_cutting_wind_only_breaks_concentration_from_cultivation_level_11():
    for cl in (10, 11):
        e = engine(bundle(AIR, AIR_BASE + ["TAL_AIR_CUTTING_WIND"], cl=cl), foe_at=(5, 6), seed="SW-AIR-0")
        e._add_modifier(e.state.actors[AN], "test:resist", "damage_resistance", "SET", "BLUDGEONING", "SELF", expires_on="UNTIL_REMOVED")
        e._add_modifier(e.state.actors[AN], "test:save", "save_bonus", "ADD", 50, "CON", expires_on="UNTIL_REMOVED")
        e._start_concentration(e.state.actors[AN], "test:held")
        use(e, "Wind Lash: Cut")
        assert ("concentration_mode" in {c[0] for c in conditions(e.state.actors[AN])}) == (cl == 11)


def test_invisible_blade_current_is_not_a_second_wind_lash_that_ignores_its_own_condition():
    names = action_names(bundle(AIR, AIR_BASE + ["TAL_AIR_CUTTING_WIND", "TAL_AIR_INVISIBLE_BLADE_CURRENT"], cl=11))
    assert "Wind Lash: Cut" in names and not [n for n in names if "Invisible Blade" in n]


def _cloud_sleeve_penalties(cl, seeds=40):
    b = bundle(AIR, AIR_BASE + ["TAL_AIR_CLOUD_SLEEVE_GUARD"], cl=cl)
    seen = []
    for seed in range(seeds):
        e = engine(b, seed=f"CSG{seed}")
        use(e, "Gather Current: Lift", near=(8, 8))  # "While you have an active Air Current" (rider lane C9, 2026-09-30)
        e.state.actors[ME].reaction_available = True
        typed_reactions.on_attacked(e, e.state.actors[AN], e.state.actors[ME], {"attack_bonus": 20, "range_ft": None}, None)
        resolved = [x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == "TAL_AIR_CLOUD_SLEEVE_GUARD"]
        seen.append(resolved[-1].payload["attack_penalty"])
    return seen


def test_cloud_sleeve_guard_die_grows_from_d6_to_d8_at_cultivation_level_11():
    assert max(_cloud_sleeve_penalties(10)) <= 6  # 1d6
    assert 6 < max(_cloud_sleeve_penalties(11)) <= 8  # 1d8


# ---------------------------------------------------------------- Alchemy

@pytest.mark.parametrize("cl,dice", [pytest.param(3, "1d6+2", id="cl3-first-row"), pytest.param(5, "2d6+2", id="cl5"),
                                     pytest.param(11, "3d6+2", id="cl11"), pytest.param(17, "4d6+2", id="cl17")])
def test_field_formula_damage_follows_the_cultivation_level_table(cl, dice):
    assert dice in Cast(ALCHEMY, ALCHEMY_BASE, [], "Field Formula: Corrosive Dregs", cl=cl, foe_at=(5, 6), stock=3).dice()


def _backdraft(cl, stock, seed="BD"):
    e = engine(bundle(ALCHEMY, ALCHEMY_BASE + ["TAL_ALCHEMY_BACKDRAFT_FUMES"], cl=cl), seed=seed)
    me, foe = e.state.actors[ME], e.state.actors[AN]
    me.resources[STOCK], me.reaction_available = stock, True
    n0 = len(e.events)
    typed_reactions.on_attack_hit(e, foe, me, {"range_ft": None}, 20, 10, 15)  # the foe's attack hit the caster
    return e, [x.payload["expression"] for x in e.events[n0:] if x.event_type == "DAMAGE_ROLLED"]


@pytest.mark.parametrize("cl,dice", [(5, "2d6+2"), (11, "3d6+2"), (17, "4d6+2")])
def test_backdraft_fumes_costs_a_cp_and_a_reagent_stock_and_scales_with_level(cl, dice):
    e, rolled = _backdraft(cl, stock=3)
    me = e.state.actors[ME]
    assert rolled == [dice]
    assert (me.resources[QI], me.resources[STOCK], me.reaction_available) == (29, 2, False)


def test_backdraft_fumes_does_not_fire_without_a_reagent_stock():
    e, rolled = _backdraft(11, stock=0)
    me = e.state.actors[ME]
    assert not rolled and me.reaction_available and me.resources[QI] == 30 and e.state.actors[AN].current_hp == 55


def test_bitter_dregs_is_not_a_second_field_formula_that_costs_hit_points():
    b = bundle(ALCHEMY, ALCHEMY_BASE + ["TAL_ALCHEMY_BITTER_DREGS"], cl=11)
    assert "Bitter Dregs" not in action_names(b)  # no standalone formula or up-front HP cost
    e = engine(b)
    variants = [a for a in e.action_catalog.values() if a.owner_id == ME and " + Bitter Dregs" in a.display_name]
    assert len(variants) == 3 and all(a.display_name.startswith("Field Formula:") for a in variants)
    # Printed "may spend one Bitter Dregs instead of one Reagent Stock":
    # the variants are optional, costed alternatives; owning it is not a free bonus.
    assert all(dict(a.costs) == {QI:1, "resource:named.bitter_dreg":1} for a in variants)
    e._gain_resource(e.state.actors[ME], "resource:named.bitter_dreg", 1, "test:prepared_dregs")
    hp = e.state.actors[ME].current_hp
    use(e, "Field Formula: Numbing Smoke + Bitter Dregs", near=(4,6))
    assert e.state.actors[ME].current_hp == hp
    assert e.state.actors[ME].resources["resource:named.bitter_dreg"] == 0
    w = Cast(ALCHEMY, ALCHEMY_BASE, ["TAL_ALCHEMY_BITTER_DREGS"], "Field Formula: Corrosive Dregs", cl=11, foe_at=(5, 6), stock=3)
    assert w.me.current_hp == w.me.maximum_hp  # no printed HP cost


STAMINA = "resource:core.stamina"


def test_stamina_boiling_pill_restores_the_consumers_stamina_and_not_its_hit_points():
    # "Recover 2d6 + Proficiency Bonus Stamina" (PB 4): the old typing aimed it at a "target" a self-consumed pill never has, and healed HP instead
    w = Cast(ALCHEMY, ALCHEMY_BASE, ["TAL_ALCHEMY_STAMINA_BOILING_PILL"], "Stamina Boiling Pill", cl=11, foe_at=(9, 6), hp=30, pool=(STAMINA, 5), body=True)
    assert 5 + 2 + 4 <= w.me.resources[STAMINA] <= 5 + 12 + 4 and w.me.current_hp == 30


def test_qi_infusion_pill_restores_the_consumers_cp_once_per_short_rest():
    w = Cast(ALCHEMY, ALCHEMY_BASE, ["TAL_ALCHEMY_QI_INFUSION_PILL"], "Qi Infusion Pill", cl=10, foe_at=(9, 6), pool=(QI, 10))
    assert 10 + 2 + 4 <= w.me.resources[QI] <= 10 + 12 + 4  # 2d6 + Proficiency Bonus
    w.next_turn()
    w.advance_to(ME)  # the Bonus Action is back on the next turn, but "a creature can benefit from this recipe once per Short Rest"
    assert "Qi Infusion Pill" not in {c.display_name for c in w.engine.legal_candidates()}


def test_healing_pill_heals_the_hit_points_of_the_one_who_takes_it():
    w = Cast(ALCHEMY, ALCHEMY_BASE, ["TAL_ALCHEMY_HEALING_PILL"], "Healing Pill", cl=10, foe_at=(9, 6), hp=20)
    assert 20 + 2 * 1 + 2 <= w.me.current_hp <= 20 + 2 * 4 + 2  # 2d4 + 2


def test_pill_of_restoration_ends_the_consumers_poisoned_condition():
    e = engine(bundle(ALCHEMY, ALCHEMY_BASE + ["TAL_ALCHEMY_PILL_OF_RESTORATION", "TAL_ALCHEMY_POISON_PILL"]), foe_at=(9, 6))
    me = e.state.actors[ME]
    # Printed Restoration requires poison/alchemical causation, rather than an
    # unqualified tag. Keep the same cure assertion with a real recipe source.
    source = next(a.source_definition_id for a in e.action_catalog.values() if a.display_name == "Poison Pill: Venom Pill")
    e._apply_condition(me, CONDITION_PREFIX + "poisoned", source, AN, expires_on="UNTIL_REMOVED")
    assert "poisoned" in {name for name, _ in conditions(me)}
    use(e, "Pill of Restoration: End Poisoned")
    assert "poisoned" not in {name for name, _ in conditions(me)}


@pytest.mark.parametrize("foe_at", [(6, 6), (12, 6)])
def test_explosive_pill_can_be_thrown_at_a_foe_within_sixty_feet(foe_at):
    assert Cast(ALCHEMY, ALCHEMY_BASE, ["TAL_ALCHEMY_EXPLOSIVE_PILL"], "Explosive Pill", cl=11, foe_at=foe_at, stock=3).foe_damage > 0


COURT = "tianxia.talent.alchemy.court_of_the_three_legged_cauldron"
WORLD_WITHIN = "tianxia.talent.alchemy.world_within_the_furnace"


def test_cauldron_court_gives_an_ally_temporary_hp_when_their_turn_starts_not_when_cast():
    w = Cast(ALCHEMY, ALCHEMY_BASE, [COURT], "Court of the Three-Legged Cauldron", cl=17, foe_at=(4, 6), ally_at=(2, 6), stock=3)
    assert (w.ally.temporary_hp, w.foe.temporary_hp) == (0, 0)  # "allies that start their turns in the area": not the moment of casting
    w.advance_to(ALLY)
    assert w.ally.temporary_hp == 4 and w.foe.temporary_hp == 0  # Proficiency Bonus


@pytest.mark.parametrize("talent,action", [("tianxia.talent.alchemy.ten_thousand_dregs_field", "Ten Thousand Dregs Field"), (WORLD_WITHIN, "World Within the Furnace: Acid")])
def test_furnace_areas_hurt_the_foe_when_it_starts_its_turn_not_when_cast(talent, action):
    w = Cast(ALCHEMY, ALCHEMY_BASE, [talent], action, cl=17, foe_at=(4, 6), foe_hp=500, stock=3)
    assert not w.saves() and w.foe_damage == 0 and not w.foe_modifiers
    assert w.next_turn() == AN and w.saves() and w.foe_damage > 0


def test_world_within_the_furnace_gives_allies_temporary_hp_at_their_turn_start_only():
    w = Cast(ALCHEMY, ALCHEMY_BASE, [WORLD_WITHIN], "World Within the Furnace: Acid", cl=17, foe_at=(4, 6), ally_at=(2, 6), foe_hp=500, stock=3)
    assert w.ally.temporary_hp == 0 and w.foe.temporary_hp == 0
    w.advance_to(ALLY)
    assert w.ally.temporary_hp == 6 and w.foe.temporary_hp == 0  # Proficiency Bonus + key modifier


# ---------------------------------------------------------------- Ash

def test_ashen_step_teleports_and_gives_no_extra_movement():
    e = engine(bundle(ASH, ASH_BASE + ["tianxia.talent.ash.ashen_step"], cl=11), foe_at=(5, 6))
    me = e.state.actors[ME]
    steps = [c for c in e.legal_candidates() if c.display_name.startswith("Ashen Step to ")]
    assert steps
    far = max(steps, key=lambda c: abs(c.destination.x - 3) + abs(c.destination.y - 6))
    move0 = me.movement_remaining_ft
    e.execute_intent(ActionIntent(intent_id="step", decision_id=far.decision_id, candidate_id=far.candidate_id, state_version=far.state_version,
                                  actor_id=ME, target_ids=far.target_ids, destination=far.destination))
    assert (me.position.x, me.position.y) == (far.destination.x, far.destination.y) and me.movement_remaining_ft == move0


def test_ash_sovereign_incarnation_does_not_hit_anyone_when_cast():
    w = Cast(ASH, ASH_BASE, ["tianxia.talent.ash.ash_sovereign_incarnation"], "Ash-Sovereign Incarnation", cl=17)
    assert w.foe_damage == 0 and not w.saves()


@pytest.mark.parametrize("talent,action", [("tianxia.talent.ash.ashen_wasteland", "Ashen Wasteland"),
                                           ("tianxia.talent.ash.ashes_of_the_forgotten_age", "Ashes of the Forgotten Age")])
def test_ash_areas_burn_and_smother_the_foe_when_it_starts_its_turn_not_when_cast(talent, action):
    w = Cast(ASH, ASH_BASE, [talent], action, cl=17, foe_at=(4, 6), foe_hp=500)
    assert not w.saves() and w.foe_damage == 0 and not w.foe_conditions
    assert w.next_turn() == AN and w.saves() and w.foe_damage > 0 and "smothered" in w.foe_conditions


def test_world_after_the_fire_holds_its_healing_penalty_for_the_concentration_and_burns_at_turn_start():
    w = Cast(ASH, ASH_BASE, ["tianxia.talent.ash.world_after_the_fire"], "World After the Fire", cl=17, foe_at=(4, 6), foe_hp=500)
    assert not w.saves() and w.foe_damage == 0 and "smothered" not in w.foe_conditions
    assert ("healing_reduction", "minus:4", "CONCENTRATION_END") in w.foe_modifiers  # "until the end of the concentration", not the caster's next turn
    assert [expires for name, expires in conditions(w.foe) if name == "no_temp_hp"] == ["CONCENTRATION_END"]  # "cannot gain Temporary HP" (was left out)
    assert w.next_turn() == AN and w.saves() and w.foe_damage > 0 and "smothered" in w.foe_conditions


def test_cremation_prison_stops_healing_and_temporary_hp_for_the_concentration_on_a_failed_save():
    w = Cast(ASH, ASH_BASE, ["ASH_TAL_CREMATION_PRISON"], "Cremation Prison", cl=17, foe_at=(8, 6), dc=FAILS)
    assert ("healing_reduction", "half", "CONCENTRATION_END") in w.foe_modifiers
    assert ("no_temp_hp", "CONCENTRATION_END") in conditions(w.foe) and ("restrained", "CONCENTRATION_END") in conditions(w.foe)


def test_cremation_prison_only_denies_temporary_hp_until_the_foes_next_turn_on_a_passed_save():
    w = Cast(ASH, ASH_BASE, ["ASH_TAL_CREMATION_PRISON"], "Cremation Prison", cl=17, foe_at=(8, 6), dc=PASSES)
    assert not [m for m in w.foe_modifiers if m[0] == "healing_reduction"] and "restrained" not in w.foe_conditions
    assert [expires for name, expires in conditions(w.foe) if name == "no_temp_hp"][0].startswith("START_OF_TURN_AT:")


def test_ash_ward_reduction_follows_the_dice_table_and_adds_proficiency_bonus_only_as_a_rider():
    def reductions(cl, seeds=60):
        b, out = bundle(ASH, ASH_BASE + ["tianxia.talent.ash.ash_ward"], cl=cl), []
        for seed in range(seeds):
            e = engine(b, foe_at=(4, 6), ally_at=(2, 6), seed=f"AW{seed}")
            e.state.actors[ME].reaction_available = True
            out.append(40 - typed_reactions.on_damage(e, e.state.actors[ALLY], 40, 0, source_definition_id="action:test.attack", source_actor_id=AN))
        return out
    assert max(reductions(5)) <= 10  # 1d8 + key modifier 2, no unconditional Proficiency Bonus
    assert statistics.mean(reductions(17)) >= 13  # 3d8 + 2 averages 15.5 (the unconditional PB version topped out lower at 1d8)


def test_ash_clone_is_a_summon_with_a_command_action():
    e = summon_tests._engine(["tianxia.talent.ash.ash_clone"])
    clones = summons.owned_by(e, summon_tests.OWNER, "ash_clone")
    assert len(clones) == 1 and not clones[0].active and clones[0].summon["status"] == "waiting"
    summon_tests._turn_of(e, summon_tests.OWNER)
    summon_tests._use(e, summon_tests.OWNER, ".tianxia.talent.ash.ash_clone")
    assert clones[0].active and clones[0].summon["status"] == "present"
    assert any(c.source_definition_id.endswith(".command.ash_clone") for c in e.legal_candidates())


# ---------------------------------------------------------------- the data itself

def test_every_correction_in_the_review_file_is_applied_to_its_current_rules_text():
    review = json.loads(REVIEW_FILE.read_text())["mechanics"]
    authority = json.loads(Path(fc.TYPED_AUTHORITY).read_text())["mechanics"]
    assert len(review) >= 30
    for key, entry in review.items():
        assert entry["reviewed_by"].startswith("sw-air ") and re.fullmatch(r"[0-9a-f]{64}", entry["text_sha256"]), key
        assert authority[key]["typing_status"] == "reviewed_final", key  # a text edit that changes the hash would silently drop the correction
        assert authority[key]["source"]["text_sha256"] == entry["text_sha256"], key


@pytest.mark.parametrize("path,keys", [(ELEMENTS_FILE, ELEMENTS_KEYS), (LIFE_FILE, LIFE_KEYS)], ids=["elements", "life"])
def test_every_correction_in_the_other_reviews_files_is_applied_to_its_current_rules_text(path, keys):
    entries = json.loads(path.read_text())["mechanics"]
    authority = json.loads(Path(fc.TYPED_AUTHORITY).read_text())["mechanics"]
    for key in keys:
        assert authority[key]["typing_status"] == "reviewed_final", key
        assert authority[key]["source"]["text_sha256"] == entries[key]["text_sha256"], key
