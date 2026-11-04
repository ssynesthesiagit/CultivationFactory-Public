"""Sphere typing review sw-verdant_growth (Verdant Growth, Void, Warleader): every corrected mechanic is compiled and used in a real engine.

Each case here failed on the typing this review replaced: a damage die rolled twice, a Standard typed as an Action that made the enemy roll a
phantom save, Hollowed handed out on the wrong branch of a save (or on the cast itself), damage dice that ignored the Cultivation Level
table, a temporary-HP grant of CL instead of 2 x CL, an aura that gave the caster a free `movement` effect, a reaction that cost nothing.
The text each one answers is in authority/typed_mechanics/rules_text.json; the corrections are in reviewed_final.d/review_sw-verdant_growth.json
(and martial.json for Fortifying Phalanx, which an earlier review had already touched).
"""
import copy
import json
import re
import statistics
from pathlib import Path

import pytest

import combat.factory_compiler as fc
from combat import typed_reactions
from combat.ext import warleader
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME, ALLY = "actor:factory.probe", "actor:factory.probe_ally"
QI = "resource:core.qi"
FAILS, PASSES = 40, -5  # the foe's saves total 0 to 24: a save against DC 40 is always failed, against DC -5 always passed
VG, VOID, WL = "tianxia.sphere.verdant_growth", "tianxia.sphere.void", "tianxia.sphere.warleader"
VG_BASE = ["TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"]
VOID_BASE = ["TAL_VOID_VOID_NEEDLE"]
WL_BASE = ["WARLEADER_BASE_SET_THE_STANDARD"]
REVIEW_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-verdant_growth.json"
MARTIAL_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/martial.json"
FORTIFYING_PHALANX = "tianxia.talent.warleader.fortifying_phalanx"


# ---------------------------------------------------------------- helpers

def bundle(sphere, talents, cl=10, dc=FAILS, actor=ME):
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    identity = {**SHEET["identity"], "cultivation_level": cl}
    sheet = {**SHEET, "equipment": [], "identity": identity, "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=actor)


def action_names(b):
    return [row["display_name"] for row in b["action_catalog"]]


def engine(b, foe_at=(4, 6), ally_at=None, seed="SW-VG"):
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

    def __init__(self, sphere, base, talents, action, *, cl=10, foe_at=(4, 6), ally_at=None, dc=FAILS, foe_hp=None, hp=None, ally_hp=None,
                 prepare=None):
        b = bundle(sphere, list(base) + list(talents), cl=cl, dc=dc)
        for attempt in range(12):  # a natural 1 misses whatever the attack bonus, which says nothing about the typing: fresh fight, next seed
            self.engine = engine(b, foe_at=foe_at, ally_at=ally_at, seed=f"SW-VG-{attempt}")
            if prepare is not None:
                prepare(self.engine)
            if foe_hp:
                self.foe.maximum_hp = self.foe.current_hp = foe_hp
            if hp is not None:
                self.me.current_hp = hp
            if ally_hp is not None:
                self.ally.current_hp = ally_hp
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
    def foe_damage(self):
        return self.hp0 - self.foe.current_hp

    @property
    def foe_conditions(self):
        return {name for name, _ in conditions(self.foe)}

    @property
    def foe_modifiers(self):
        return modifiers(self.foe)

    def events(self, kind):
        return [x for x in self.engine.events[self.n0:] if x.event_type == kind]

    def dice(self):
        return [x.payload["expression"] for x in self.events("DAMAGE_ROLLED")]

    def riders(self):
        return [x.payload["rider"] for x in self.events("GM_RIDER")]

    def saves(self):
        return self.events("SAVE_ROLLED")

    def attacks(self):
        return self.events("ATTACK_ROLLED")

    def expires(self, name):
        return [expires for cond, expires in conditions(self.foe) if cond == name]

    def next_turn(self):
        return next_turn(self.engine)

    def advance_to(self, actor_id):
        """Pass turns until `actor_id`'s turn has just started (the initiative order depends on the seed)."""
        for _ in range(8):
            if self.engine.state.current_actor_id == actor_id:
                return
            self.next_turn()
        raise AssertionError(f"never reached the turn of {actor_id}")


def vg(name):
    return f"TAL_VERDANT_GROWTH_{name}"


def void(name):
    return f"TAL_VOID_{name}"


def wl(name):
    return f"tianxia.talent.warleader.{name}"


INCARNATION = "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree"
GROWTH_MARK = "mark.growth_mark." + ME
SAVE_DC_PARAMS = [pytest.param(FAILS, id="failed-save"), pytest.param(PASSES, id="passed-save")]


def rider_texts(engine_, since):
    return [x.payload["rider"] for x in engine_.events[since:] if x.event_type == "GM_RIDER"]


# ---------------------------------------------------------------- Verdant Growth

def growth_marks(count):
    """Rider lane C16: Growth Marks are counted now; place ``count`` of the caster's on the foe (an engine-level test setup)."""
    def prepare(engine_):
        from combat.ext import verdant_chassis

        verdant_chassis.place(engine_, engine_.state.actors[ME], engine_.state.actors[AN], count, "test")
    return prepare


@pytest.mark.parametrize("dc", SAVE_DC_PARAMS)
def test_bramble_refusal_rolls_its_damage_die_once_and_adds_disadvantage_only_on_a_failed_save(dc):
    """The 1d8 sat in the failed-save branch and again on the ability itself: a failed save rolled it twice. Rider lane C16: Bramble
    Refusal answers a marked creature's melee attack as it is declared (combat/ext/verdant_chassis.py; it spends the printed Growth
    Mark and no Reaction) -- the die is still rolled once, and Disadvantage comes only from a failed save."""
    from combat.ext import verdant_chassis

    w = Cast(VG, VG_BASE, [vg("BRAMBLE_REFUSAL")], "Seed-Thorn Strike", dc=dc)
    n, hp = len(w.engine.events), w.foe.current_hp
    assert verdant_chassis.marks(w.foe, w.me) == 1  # Seed-Thorn Strike's Growth Mark
    answer = verdant_chassis.bramble_refusal(w.engine, w.foe, w.me, None, {"range_ft": 5, "effect": {"attack_kind": "melee"}})
    rolled = [x for x in w.engine.events[n:] if x.event_type == "DAMAGE_ROLLED"]
    assert [x.payload["expression"] for x in rolled] == ["1d8+0"]
    assert hp - w.foe.current_hp == rolled[0].payload["total"]
    assert (answer == {"mode": "DISADVANTAGE"}) == (dc == FAILS) and verdant_chassis.marks(w.foe, w.me) == 0


@pytest.mark.parametrize("dc,stopped", [(FAILS, True), (PASSES, False)], ids=["failed-save", "passed-save"])
def test_root_snare_step_ends_the_foes_movement_on_a_failed_save_and_slows_it_by_10_on_a_passed_one(dc, stopped):
    """"Failed Save: Its movement ends after the current 5-foot step. Successful Save: Its Speed is reduced by 10 feet until the end of
    the turn." Rider lane C16: it answers a marked creature's own move of 10 feet or more (it spends the Growth Mark, no Reaction)."""
    w = Cast(VG, VG_BASE, [vg("ROOT_SNARE_STEP")], "Seed-Thorn Strike", dc=dc, foe_at=(9, 6))
    w.advance_to(AN)
    w.foe.movement_remaining_ft = 30
    n = len(w.engine.events)
    destination = next(c for c in w.engine.legal_candidates() if c.display_name == "Move to 9,8")
    from combat.gate2_runtime_models import ActionIntent

    w.engine.execute_intent(ActionIntent(intent_id="snare", decision_id=destination.decision_id, candidate_id=destination.candidate_id,
                                         state_version=destination.state_version, actor_id=AN, destination=destination.destination))
    assert any(x.event_type == "SAVE_ROLLED" for x in w.engine.events[n:])
    if stopped:
        # AUTO36 moved the failure boundary to the five-foot step: the route stops at the triggering step and the
        # unspent movement is kept for a later move this turn, rather than being deleted (printed text: "Its movement
        # ends after the current 5-foot step"). This 30-foot budget spent 10 feet before the failed save.
        assert w.foe.movement_remaining_ft == 20
        committed = next(x for x in w.engine.events[n:] if x.event_type == "MOVEMENT_COMMITTED")
        stops = [i for i in committed.payload["interruptions"] if i.get("stop")
                 and i["source_id"] == "TAL_VERDANT_GROWTH_ROOT_SNARE_STEP"]
        assert stops and committed.payload["cost_ft"] == 10
    else:
        assert [(field, value) for field, value, _ in w.foe_modifiers if field == "speed_ft"] == [("speed_ft", -10)]


@pytest.mark.parametrize("dc,held", [(FAILS, "restrained"), (PASSES, "grappled")], ids=["failed-save", "passed-save"])
def test_thousand_root_prison_holds_the_foe_and_deals_no_damage_of_its_own(dc, held):
    """The 4d10 belongs to the teleport-only line; it was rolled on the cast (twice on a failed save). "Target: One creature with at least
    3 of your Growth Marks" (rider lane C16: counted now)."""
    w = Cast(VG, VG_BASE, [vg("THOUSAND_ROOT_PRISON")], "Thousand-Root Prison", cl=17, foe_at=(5, 6), dc=dc, prepare=growth_marks(3))
    assert w.dice() == [] and w.foe_damage == 0
    assert held in w.foe_conditions


def test_the_seed_that_remembers_the_forest_restrains_nobody_when_it_is_cast():
    """It restrains only an enemy at 0 HP with three Growth Marks, on its own turn: not everything in the area at once."""
    w = Cast(VG, VG_BASE, [vg("THE_SEED_THAT_REMEMBERS_THE_FOREST")], "The Seed That Remembers the Forest", cl=17, ally_at=(2, 6))
    assert w.foe_conditions == set() and w.foe_damage == 0


def test_verdant_incarnation_gives_reach_not_free_movement_and_marks_nobody():
    w = Cast(VG, [], [INCARNATION], "Verdant Incarnation: Body Becomes the Ancient Tree", cl=17)
    assert w.moved == 0 and w.foe_conditions == set()


@pytest.mark.parametrize("cl,dice", [(1, "1d6+2"), (3, "1d6+2"), (4, "1d6+2"), (5, "2d6+2"), (10, "2d6+2"),
                                   (11, "3d6+2"), (16, "3d6+2"), (17, "4d6+2"), (20, "4d6+2")])
def test_seed_thorn_strike_follows_its_damage_table_and_its_growth_mark_ends(cl, dice):
    """Keep the full level table and mark expiry; the owner adds the Path key modifier (+2 here)."""
    w = Cast(VG, VG_BASE, [], "Seed-Thorn Strike", cl=cl)
    assert w.dice() == [dice]
    assert w.expires(GROWTH_MARK) == ["END_OF_MARKER_NEXT_TURN"]


@pytest.mark.parametrize("cl", [10, 17])
def test_spring_after_calamity_grants_twice_cl_temporary_hp(cl):
    b = bundle(VG, [vg("SPRING_AFTER_CALAMITY")], cl=cl)
    e = engine(b, foe_at=(9, 6), ally_at=(4, 6), seed="SP")
    e.state.actors[ALLY].current_hp = 10
    use(e, "Spring After Calamity: Temporary HP", near=(4, 6))
    assert e.state.actors[ALLY].temporary_hp == 2 * cl


def graft_with_orchard(option):
    """Graft the Wound Shut modified by Orchard of Bitter Medicine, used on the poisoned ally: (engine, ally)."""
    b = bundle(VG, VG_BASE + [vg("GRAFT_THE_WOUND_SHUT"), vg("ORCHARD_OF_BITTER_MEDICINE")], cl=10)
    e = engine(b, foe_at=(9, 6), ally_at=(4, 6), seed="GR")
    me, ally = e.state.actors[ME], e.state.actors[ALLY]
    me.current_hp = ally.current_hp = 20
    e._apply_condition(ally, CONDITION_PREFIX + "poisoned", "test", AN, expires_on="UNTIL_REMOVED")
    name = f"Graft the Wound Shut + Orchard of Bitter Medicine: {option}"
    c = next(c for c in e.legal_candidates() if c.display_name == name and c.target_ids == (ALLY,))
    e.execute_intent(ActionIntent(intent_id=name, decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                  actor_id=ME, target_ids=c.target_ids, destination=c.destination))
    return e, ally


def test_orchard_of_bitter_medicine_end_poisoned_ends_poisoned():
    """"The target ends the Poisoned condition" was typed as applying Poisoned: a second one on the ally."""
    _, ally = graft_with_orchard("End Poisoned")
    assert conditions(ally) == []


def test_orchard_of_bitter_medicine_remove_growth_mark_grants_twice_pb_temporary_hp():
    _, ally = graft_with_orchard("Remove Growth Mark")
    assert ally.temporary_hp == 8  # twice the Proficiency Bonus of 4 at CL 10


# ---------------------------------------------------------------- Warleader

STANDARDS = {"ironclad_line": "Ironclad Line", "coordinated_reflexes": "Coordinated Reflexes", "militant_will": "Militant Will",
             "fortifying_phalanx": "Fortifying Phalanx"}


@pytest.mark.parametrize("key,title", sorted(STANDARDS.items()))
def test_a_standard_that_is_active_while_set_is_an_aura_not_an_action(key, title):
    """The named Bonus Action selects this Standard; its benefits require the active Standard, never a phantom save."""
    b = bundle(WL, WL_BASE + [wl(key)], cl=17)
    names = action_names(b)
    assert "Set the Standard" in names and title in names
    row = next(r for r in b["action_catalog"] if r["display_name"] == title)
    assert row["parameters"]["typed"]["effects"] == [{"type": "warleader_standard", "standard": key,
                                                        "applies_to": "self", "evidence": f"Set the Standard: {title}."}]
    e = engine(b, ally_at=(2, 6))
    me, ally = e.state.actors[ME], e.state.actors[ALLY]
    assert warleader.standard_of(me) is None
    n = len(e.events)
    use(e, title)
    assert warleader.standard_of(me)["standard"] == key
    assert not [event for event in e.events[n:] if event.event_type == "SAVE_ROLLED"]
    assert not [m for m in ally.modifiers.values() if m.target_field == "damage_resistance"]
    e._expire_typed_for_checkpoint("START_OF_TURN", ME)
    assert warleader.standard_of(me) is None


@pytest.mark.parametrize("cl", [10, 17])
def test_legion_unending_grants_twice_cl_temporary_hp(cl):
    bases = WL_BASE + ["WARLEADER_BASE_MOMENTUM_MARKS", "WARLEADER_BASE_COMMAND_RESPONSES"]
    e = engine(bundle(WL, bases + [wl("legion_unending")], cl=cl), ally_at=(2, 6), seed="LU")
    me, ally = e.state.actors[ME], e.state.actors[ALLY]
    me.reaction_available, ally.current_hp = True, 5
    use(e, "Legion Unending")
    e._gain_resource(me, warleader.MOMENTUM, 1, "test")
    # Enough damage to drop the ally, but the printed 2 x CL shield would keep it up.
    typed_reactions.on_damage(e, ally, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert ally.temporary_hp == 2 * cl
    assert me.resources[warleader.MOMENTUM] == 0 and not me.reaction_available
    e._expire_typed_for_checkpoint("START_OF_TURN", ME)
    assert ally.temporary_hp == 0


# ---------------------------------------------------------------- Void

def test_hollow_touch_hollows_on_a_failed_save_and_only_denies_temporary_hp_on_a_passed_one():
    failed = Cast(VOID, VOID_BASE, [void("HOLLOW_TOUCH")], "Hollow Touch", cl=17, dc=FAILS)
    assert failed.expires("hollowed") == ["START_OF_SOURCE_NEXT_TURN"]
    passed = Cast(VOID, VOID_BASE, [void("HOLLOW_TOUCH")], "Hollow Touch", cl=17, dc=PASSES)
    assert "hollowed" not in passed.foe_conditions and "no_temp_hp" in passed.foe_conditions


def test_heaven_emptying_lance_hollows_for_a_minute_on_a_failed_save_and_until_the_next_turn_on_a_passed_one():
    failed = Cast(VOID, VOID_BASE, [void("HEAVEN_EMPTYING_LANCE")], "Heaven-Emptying Lance", cl=17, dc=FAILS)
    assert [token.startswith("START_OF_SLOT_AT:") for token in failed.expires("hollowed")] == [True]
    passed = Cast(VOID, VOID_BASE, [void("HEAVEN_EMPTYING_LANCE")], "Heaven-Emptying Lance", cl=17, dc=PASSES)
    assert passed.expires("hollowed") == ["START_OF_SOURCE_NEXT_TURN"]


def test_void_meridian_seal_hollows_for_the_concentration_on_a_failed_save_and_until_the_next_turn_on_a_passed_one():
    failed = Cast(VOID, VOID_BASE, [void("VOID_MERIDIAN_SEAL")], "Void Meridian Seal", cl=17, dc=FAILS)
    assert failed.expires("hollowed") == ["CONCENTRATION_END"]
    passed = Cast(VOID, VOID_BASE, [void("VOID_MERIDIAN_SEAL")], "Void Meridian Seal", cl=17, dc=PASSES)
    assert passed.expires("hollowed") == ["START_OF_SOURCE_NEXT_TURN"]


def test_void_prison_hollows_on_a_passed_save_and_cages_on_a_failed_one():
    """"Successful Save: the target is Hollowed until the start of your next turn; Failed Save: it is held in the cage."""
    failed = Cast(VOID, VOID_BASE, [void("VOID_PRISON")], "Void Prison", cl=17, dc=FAILS)
    assert "hollowed" not in failed.foe_conditions
    passed = Cast(VOID, VOID_BASE, [void("VOID_PRISON")], "Void Prison", cl=17, dc=PASSES)
    assert passed.expires("hollowed") == ["START_OF_SOURCE_NEXT_TURN"]


@pytest.mark.parametrize("cl,dice", [(5, "5d8+0"), (11, "7d8+0"), (17, "9d8+0")])
def test_unmake_barrier_follows_its_damage_table(cl, dice):
    assert Cast(VOID, VOID_BASE, [void("UNMAKE_BARRIER")], "Unmake Barrier", cl=cl, foe_hp=500).dice() == [dice]


@pytest.mark.parametrize("cl,dice", [(5, "3d6+0"), (11, "5d6+0"), (17, "7d6+0")])
def test_void_field_follows_its_damage_table_and_hollows_on_a_failed_save(cl, dice):
    w = Cast(VOID, VOID_BASE, [void("VOID_FIELD")], "Void Field", cl=cl, foe_hp=500, dc=FAILS)
    assert not w.dice() and not w.saves() and not w.foe_conditions
    w.advance_to(AN)  # Printed damage occurs on entry/start, not creation.
    assert w.dice() == [dice] and "hollowed" in w.foe_conditions


def test_void_field_only_denies_temporary_hp_on_a_passed_save():
    w = Cast(VOID, VOID_BASE, [void("VOID_FIELD")], "Void Field", cl=11, foe_hp=500, dc=PASSES)
    assert not w.dice() and not w.saves() and not w.foe_conditions
    w.advance_to(AN)
    assert "hollowed" not in w.foe_conditions and "no_temp_hp" in w.foe_conditions


def void_ward_reductions(cl, seeds=30):
    b, out = bundle(VOID, VOID_BASE + [void("VOID_WARD")], cl=cl), []
    for seed in range(seeds):
        e = engine(b, ally_at=(2, 6), seed=f"VW{seed}")
        e.state.actors[ME].reaction_available = True
        out.append(40 - typed_reactions.on_damage(e, e.state.actors[ALLY], 40, 0, source_definition_id="action:test.attack", source_actor_id=AN))
    return out


def test_void_ward_reduction_follows_the_dice_table():
    """1d8 at CL 1-10, 2d8 at 11-16, 3d8 at 17+ (plus the key-ability modifier): it was a flat 1d8 at every level (14 at most)."""
    low, high = void_ward_reductions(5), void_ward_reductions(17)
    assert max(low) <= 14
    # rider lane C4 2026-09-30: the Proficiency Bonus is added only "If the triggering effect is a Cultivation Attack, area talent, ...
    # Force, Necrotic or Psychic damage, or an effect from a creature that is Hollowed"; this untyped test damage is none of those, so
    # the reductions are 3d8 + key modifier (mean 15.5; 1d8 + key would be 6.5) rather than the earlier unconditional + PB (mean > 16).
    assert max(high) > 14 and statistics.mean(high) > 12


@pytest.mark.parametrize("cl,dice", [(5, "2d8+0"), (11, "3d8+0"), (17, "4d8+0")])
def test_ten_thousand_empty_needles_deals_void_needle_damage(cl, dice):
    """The attack carried no damage at all: it hit and did nothing."""
    w = Cast(VOID, VOID_BASE, [void("TEN_THOUSAND_EMPTY_NEEDLES")], "Ten-Thousand Empty Needles", cl=cl, foe_hp=500)
    assert w.dice() == [dice] and w.foe_damage > 0


def test_void_sovereign_incarnation_hollows_nobody_when_it_is_cast():
    w = Cast(VOID, VOID_BASE, [void("VOID_SOVEREIGN_INCARNATION")], "Void-Sovereign Incarnation", cl=17)
    assert w.foe_conditions == set()


def test_void_shell_makes_no_attack_and_deals_no_damage():
    """Its reprisal (Force damage when a creature hits you in melee) was typed as an attack the Bonus Action makes."""
    w = Cast(VOID, VOID_BASE, [void("VOID_SHELL")], "Void Shell", cl=17)
    assert w.attacks() == [] and w.foe_damage == 0


def test_hollow_path_step_costs_two_qi_and_names_its_teleport():
    e = engine(bundle(VOID, VOID_BASE + [void("HOLLOW_PATH_STEP")], cl=17), seed="HPS")
    me, foe = e.state.actors[ME], e.state.actors[AN]
    me.reaction_available = True
    qi, n = me.resources[QI], len(e.events)
    start = (me.position.x, me.position.y)
    typed_reactions.on_attack_missed(e, foe, me, {"range_ft": None}, None)
    assert me.resources[QI] == qi - 2 and not me.reaction_available
    # rider lane C4 2026-09-30: the Empty Step now happens (combat/ext/teleport_steps.py) instead of a "place the creature" GM line.
    assert (me.position.x, me.position.y) != start and "Teleport up to 20 feet: place the creature on the map." not in rider_texts(e, n)


@pytest.mark.parametrize("talent", ["BARRIER_EMPTYING_NEEDLE", "BARRIER_GNAW"])
def test_barrier_talents_leave_void_needle_damage_on_creatures_alone(talent):
    """Both add damage only when Void Needle damages a temporary Barrier (or object): they added it to every hit on a creature."""
    plain = Cast(VOID, VOID_BASE, [], "Void Needle: Empty Vitality", cl=17, foe_hp=500)
    w = Cast(VOID, VOID_BASE, [void(talent)], "Void Needle: Empty Vitality", cl=17, foe_hp=500)
    assert w.dice() == plain.dice() and w.foe_damage == plain.foe_damage


def test_erode_technique_prevents_invisible_instead_of_granting_it():
    """"Prevent Invisible from that effect": the reaction's default option gave the enemy the Invisible condition.

    Printed trigger: "A creature within 60 feet gains Temporary HP, damage reduction, an AC bonus, a Speed bonus,
    Resistance, Invisible, or a cost reduction from an ordinary temporary effect". The gain itself is the event
    (H203FIX1: a plain HP regain no longer opens Erode), so this applies the Invisible benefit the enemy receives.
    """
    e = engine(bundle(VOID, VOID_BASE + [void("ERODE_TECHNIQUE")], cl=17), ally_at=(2, 6), seed="ET")
    me, foe, ally = e.state.actors[ME], e.state.actors[AN], e.state.actors[ALLY]
    me.reaction_available = True
    n = len(e.events)
    e._apply_condition(foe, "condition:typed.invisible", "test:veil", AN, expires_on="START_OF_SOURCE_NEXT_TURN")
    assert not me.reaction_available and me.resources[QI] == 29
    names = {name for name, _ in conditions(foe)}
    assert "invisible" not in names and "benefit_suppressed" in names
    assert not [r for r in rider_texts(e, n) if "not in the rules file" in r]
    # the erosion is for enemies' benefits: an ally's Invisible is left alone and does not use the reaction
    me.reaction_available = True
    e._apply_condition(ally, "condition:typed.invisible", "test:veil", ALLY, expires_on="START_OF_SOURCE_NEXT_TURN")
    assert me.reaction_available and me.resources[QI] == 29 and "invisible" in {name for name, _ in conditions(ally)}


# ---------------------------------------------------------------- the data itself

def test_every_correction_in_the_review_file_is_applied_to_its_current_rules_text():
    review = json.loads(REVIEW_FILE.read_text())["mechanics"]
    authority = json.loads(Path(fc.TYPED_AUTHORITY).read_text())["mechanics"]
    # Every entry names the reviewer who wrote it. AUTO36 re-reviewed Root-Snare Step when it moved the failure
    # boundary, so the guard accepts each reviewer this file actually uses instead of only the original two.
    # A2VOID (fe81e364) re-typed TAL_VOID_VOID_SOVEREIGN_INCARNATION after sw-verdant_growth; it is a named reviewer too.
    reviewers = ("sys-resources-states ", "sw-verdant_growth ", "AUTO36", "A2VOID ")
    assert len(review) >= 25
    for key, entry in review.items():
        assert any(entry["reviewed_by"].startswith(name) for name in reviewers) and re.fullmatch(r"[0-9a-f]{64}", entry["text_sha256"]), key
        assert authority[key]["typing_status"] == "reviewed_final", key  # a text edit that changes the hash would silently drop the correction
        assert authority[key]["source"]["text_sha256"] == entry["text_sha256"], key


def test_fortifying_phalanx_keeps_its_earlier_review_entry_with_this_reviews_correction():
    """A key may appear in one reviewed_final file only: the entry is edited in martial.json, not repeated in the review file."""
    entry = json.loads(MARTIAL_FILE.read_text())["mechanics"][FORTIFYING_PHALANX]
    authority = json.loads(Path(fc.TYPED_AUTHORITY).read_text())["mechanics"][FORTIFYING_PHALANX]
    assert entry["reviewed_by"].startswith("sys-resources-states ") and entry["activation"]["economy"] == "bonus_action"
    assert entry["effects"] == [{"type": "warleader_standard", "standard": "fortifying_phalanx", "applies_to": "self",
                                 "evidence": "Set the Standard: Fortifying Phalanx."}]
    assert authority["typing_status"] == "reviewed_final" and authority["source"]["text_sha256"] == entry["text_sha256"]
    assert FORTIFYING_PHALANX not in json.loads(REVIEW_FILE.read_text())["mechanics"]
