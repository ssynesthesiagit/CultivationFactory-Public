"""Sphere typing review sw-beastmastery (Beastmastery, Beauty, Berserker): every corrected mechanic is compiled and used in a real engine.

Each case here failed on the typing this review replaced. Lines the text gives to a later moment were typed as an effect of using the
ability: Court of the Unbroken Warpath, One Rider One Beast, Court of Fang and Rein's "Move Without Opportunity Attacks" and the Procession
each handed the caster 5 to 10 feet of movement it never gets, and Beauty That Judges took 6 Psychic hit points at the cast. Buffs went to the
wrong creature or in the wrong amount: War-God Incarnation dealt its own 2d10 to the caster and gave none of the printed Resistance (it was
aimed at a hostile creature within 5 feet), the Procession gave its "twice your Proficiency Bonus" of temporary hit points to the caster and
the ally one Proficiency Bonus, made its save at the moment of casting instead of when a creature starts its turn there, and Court of Fang and
Rein was a choose-one that gave the ally Speed and the caster nothing. Effects gated on a save or an earlier hit were unconditional: Heavy
Swing stunned on every failed save, Leg-Smasher rolled a Strength save to knock Prone instead of halving Speed, Unbearable Splendor denied
reactions for the whole minute of the Charm as well as until the end of the turn. Branches and dice were wrong: Great Beast Charge had no
5-foot push on a passed save, World-Breaking Rampage saved with Strength where the text lets the target choose Strength or Dexterity, The Blow
Heaven Refused to Receive pushed twice (60 feet) and left its Advantage on the caster after the attack roll, Reaper's Momentum made two attack
rolls and took nothing off the first, Bloody Counter struck without dealing damage. Pack Attack, a line about Tame Creatures' attacks, put an
Advantage row on the Great Beast Charge. The text each one answers is in authority/typed_mechanics/rules_text.json; the corrections are in
reviewed_final.d/review_sw-beastmastery.json. Every attack roll here is made to hit (a natural 1 gets a fresh seed); the foe's saves total 0 to
24, so DC 40 always fails and DC -5 always passes.
"""
import copy
import json
from pathlib import Path

import pytest

import combat.factory_compiler as fc
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX, mark_condition_id
from tests.test_auto_tabik import FOE, ME as TABIK, _foe_attack, _turn
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME, ALLY = "actor:factory.probe", "actor:factory.probe_ally"
FAILS, PASSES = 40, -5  # the foe's saves total 0 to 24: a save against DC 40 is always failed, against DC -5 always passed
BERSERKER, BEAUTY, BEASTMASTERY = "tianxia.sphere.berserker", "tianxia.sphere.beauty", "tianxia.sphere.beastmastery"
REVIEW_FILE = ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-beastmastery.json"
WAR_GOD, WARPATH, RAMPAGE = "TAL_BERSERKER_WAR_GOD_INCARNATION", "TAL_BERSERKER_COURT_OF_THE_UNBROKEN_WARPATH", "TAL_BERSERKER_WORLD_BREAKING_RAMPAGE"
BLOW = "tianxia.talent.berserker.the_blow_heaven_refused_to_receive"
LEG_SMASHER, HEAVY_SWING, REAPER = "TAL_BERSERKER_LEG_SMASHER", "TAL_BERSERKER_HEAVY_SWING", "TAL_BERSERKER_REAPER_S_MOMENTUM"
BLOODY_COUNTER = "TAL_BERSERKER_BLOODY_COUNTER"
SPLENDOR, JUDGES = "tianxia.talent.beauty.unbearable_splendor", "tianxia.talent.beauty.beauty_that_judges"
PROCESSION, FANG_AND_REIN = "TAL_BEASTMASTERY_TEN_THOUSAND_BEAST_PROCESSION", "TAL_BEASTMASTERY_COURT_OF_FANG_AND_REIN"
ONE_RIDER, GREAT_CHARGE, PACK_ATTACK = "TAL_BEASTMASTERY_ONE_RIDER_ONE_BEAST", "TAL_BEASTMASTERY_GREAT_BEAST_CHARGE", "tianxia.talent.beastmastery.pack_attack"
ALL_BUT_PSYCHIC = {"ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "RADIANT", "SLASHING", "THUNDER"}


# ---------------------------------------------------------------- helpers

def bundle(sphere, talents, dc=FAILS, actor=ME):
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    sheet = {**SHEET, "equipment": [], "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=actor)


def engine(b, foe_at=(4, 6), ally_at=None, seed="SW-BM"):
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
    """One ability used once by the caster against the foe, and what it did to the caster, the ally and the foe."""

    def __init__(self, sphere, talents, action, *, foe_at=(4, 6), ally_at=None, dc=FAILS, foe_hp=None, required_mark=None):
        b = bundle(sphere, talents, dc=dc)
        for attempt in range(12):  # a natural 1 misses whatever the attack bonus, which says nothing about the typing: fresh fight, next seed
            self.engine = engine(b, foe_at=foe_at, ally_at=ally_at, seed=f"SW-BM-{attempt}")
            if foe_hp:
                self.foe.maximum_hp = self.foe.current_hp = foe_hp
            if required_mark:
                self.engine._apply_condition(self.foe, mark_condition_id(required_mark, ME),
                                             'test:target_preparation', ME, expires_on='UNTIL_REMOVED')
            self.move0, self.hp0, self.me_hp0, self.n0 = self.me.movement_remaining_ft, self.foe.current_hp, self.me.current_hp, len(self.engine.events)
            use(self.engine, action, near=foe_at)
            if not [x for x in self.events if x.event_type == "ATTACK_ROLLED" and x.payload.get("natural_result") == 1]:
                return
        raise AssertionError(f"{action}: twelve seeds in a row rolled a natural 1")

    @staticmethod
    def cell(actor):
        return actor.position.x, actor.position.y

    @property
    def events(self):
        return self.engine.events[self.n0:]

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
        return sum(int(x.payload.get("distance_ft") or 0) for x in self.events if x.event_type == "MOVEMENT_GRANTED")

    @property
    def foe_cell(self):
        return self.cell(self.foe)

    @property
    def foe_damage(self):
        return self.hp0 - self.foe.current_hp

    @property
    def foe_conditions(self):
        return {name for name, _ in conditions(self.foe)}

    def saves(self):
        return [x for x in self.events if x.event_type == "SAVE_ROLLED"]

    def attack_rolls(self):
        return [x.payload for x in self.events if x.event_type == "ATTACK_ROLLED"]

    def next_turn(self):
        return next_turn(self.engine)

    def advance_to(self, actor_id):
        """Pass turns until `actor_id`'s turn has just started (the initiative order depends on the seed)."""
        for _ in range(8):
            if self.engine.state.current_actor_id == actor_id:
                return
            self.next_turn()
        raise AssertionError(f"never reached the turn of {actor_id}")


# ---------------------------------------------------------------- the review file

def test_every_corrected_mechanic_was_applied_by_the_builder_not_skipped():
    # The builder skips an entry whose text hash no longer matches the printed text (it only prints a line on stderr)
    review = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))["mechanics"]
    mechanics = json.loads(Path(fc.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]
    assert review and {key for key in review if mechanics[key].get("typing_status") != "reviewed_final"} == set()


# ---------------------------------------------------------------- Berserker

def test_war_god_incarnation_is_a_bonus_action_for_the_berserker_that_grants_resistance_and_hurts_nobody():
    w = Cast(BERSERKER, [WAR_GOD], "War-God Incarnation")
    resisted = {value for field, value, _ in modifiers(w.me) if field == "damage_resistance"}
    assert resisted == ALL_BUT_PSYCHIC  # "gain Resistance to all damage except Psychic"
    assert w.me.current_hp == w.me_hp0 and w.granted == 0  # "+2d10" is Batter damage, and the 10 feet a reaction to damage
    assert w.foe_damage == 0 and not conditions(w.foe)


def test_court_of_the_unbroken_warpath_is_a_reaction_line_that_moves_nobody_when_used():
    w = Cast(BERSERKER, [WARPATH], "Court of the Unbroken Warpath")
    assert w.granted == 0 and w.moved == 0


def test_world_breaking_rampage_saves_with_the_better_of_strength_and_dexterity():
    w = Cast(BERSERKER, [RAMPAGE], "World-Breaking Rampage")
    better = max(("STR", "DEX"), key=lambda ability: w.foe.saving_throws[ability])
    assert better != "STR"  # the early foe's Dexterity save is the better of the two, so a typed "STR" is the wrong die
    # The reviewed area affects all creatures inside, including the caster.
    saves = w.saves()
    assert {row.actor_id for row in saves} == {w.me.entity_id, w.foe.entity_id}
    for actor in (w.me, w.foe):
        chosen = max(("STR", "DEX"), key=lambda ability: actor.saving_throws[ability])
        assert [row.payload["reason"].rsplit(":", 1)[1]
                for row in saves if row.actor_id == actor.entity_id] == [chosen]


def test_the_blow_heaven_refused_to_receive_stuns_and_throws_thirty_feet_on_a_failed_save_and_denies_reactions_on_a_passed_one():
    failed = Cast(BERSERKER, [BLOW], "The Blow Heaven Refused to Receive", foe_hp=900, dc=FAILS)
    assert failed.foe_damage >= 12  # 12d10 Force
    assert "stunned" in failed.foe_conditions and failed.foe_cell == (4 + 30 // 5, 6)  # "pushed 30 feet": one push, not two
    assert not [m for m in modifiers(failed.me) if m[0] == "attack_mode"]  # the Advantage is for the attack roll, and spent on it
    passed = Cast(BERSERKER, [BLOW], "The Blow Heaven Refused to Receive", foe_hp=900, dc=PASSES)
    assert passed.foe_damage >= 12 and "stunned" not in passed.foe_conditions and passed.foe_cell == (4, 6)
    assert "reaction_denied" in passed.foe_conditions


def test_the_blow_heaven_refused_to_receive_is_once_per_week_so_a_fight_gets_one_use():
    # "Use Limit: Once per week" was only the text `text:once per week`, which the compiler never enforces (it counts uses for once-per-rest limits)
    row = next(r for r in bundle(BERSERKER, [BLOW])["action_catalog"] if r["display_name"] == "The Blow Heaven Refused to Receive")
    assert any(str(cost[0]).startswith("resource:uses.action:") for cost in row["costs"])
    w = Cast(BERSERKER, [BLOW], "The Blow Heaven Refused to Receive", foe_hp=900, dc=PASSES)  # a passed save leaves the foe in reach
    w.me.resources["resource:core.martial_focus"] = w.me.resource_maximums["resource:core.martial_focus"]  # Focus is not what stops a second use
    w.next_turn()
    w.advance_to(ME)
    assert "The Blow Heaven Refused to Receive" not in {c.display_name for c in w.engine.legal_candidates()}


def test_leg_smasher_halves_the_speed_of_the_creature_it_hits_and_does_not_knock_it_prone():
    w = Cast(BERSERKER, [LEG_SMASHER], "Batter + Leg-Smasher", foe_hp=900)
    assert w.engine._effective_speed(w.foe) == 15  # 30 halved until the start of your next turn
    assert "prone" not in w.foe_conditions and not w.saves()


def test_heavy_swing_denies_reactions_on_a_failed_save_and_only_stuns_a_creature_that_was_already_battered():
    w = Cast(BERSERKER, [HEAVY_SWING], "Batter + Heavy Swing", foe_hp=900, dc=FAILS)
    assert "reaction_denied" in w.foe_conditions and "stunned" not in w.foe_conditions
    assert w.engine._effective_speed(w.foe) == 30


def test_reapers_momentum_is_five_off_the_one_batter_attack_roll():
    plain = Cast(BERSERKER, [], "Batter", foe_hp=900)
    reaper = Cast(BERSERKER, [REAPER], "Batter + Reaper’s Momentum", foe_hp=900)
    assert len(plain.attack_rolls()) == len(reaper.attack_rolls()) == 1  # the second attack is a rider, not a second roll in the same turn
    assert plain.attack_rolls()[0]["modifier"] - reaper.attack_rolls()[0]["modifier"] == 5


def _duel(seed):
    """A berserker with Bloody Counter against a weaponed foe whose armor is nothing; it is the foe's turn."""
    mine = compile_character({**SHEET, "equipment": [{"starting_kit": KIT}],
                              "spheres_and_talents": {"sphere_record_ids": [BERSERKER], "learned_talent_record_ids": [BLOODY_COUNTER]}}, actor_id=TABIK)
    theirs = compile_character({**SHEET, "equipment": [{"starting_kit": KIT}], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}, actor_id=FOE)
    e = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(mine, theirs),
                              roster_setup={"primary_actor_ids": [TABIK, FOE], "team_by_actor": {TABIK: "team:a", FOE: "team:b"},
                                            "starting_positions": {TABIK: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    e.state.actors[FOE].armor_class = 1
    _turn(e, FOE)
    return e


def test_bloody_counter_strikes_back_with_the_weapon_and_the_attacker_takes_the_damage():
    for attempt in range(12):
        e = _duel(f"BLOODY-{attempt}")
        n0 = len(e.events)
        _foe_attack(e, 60)
        counter = [x for x in e.events[n0:] if x.event_type == "ATTACK_ROLLED" and x.actor_id == TABIK]
        assert counter, "the reaction did not answer the attack"
        if counter[0].payload.get("natural_result") != 1:  # a natural 1 misses whatever the bonus: next seed
            break
    else:
        raise AssertionError("twelve seeds in a row rolled a natural 1")
    struck = [x for x in e.events[n0:] if x.event_type == "DAMAGE_ROLLED" and x.actor_id == TABIK]
    assert struck and e.state.actors[FOE].current_hp < e.state.actors[FOE].maximum_hp


# ---------------------------------------------------------------- Beauty

def test_unbearable_splendor_charms_and_denies_reactions_until_the_end_of_the_targets_turn_only():
    w = Cast(BEAUTY, [SPLENDOR], "Unbearable Splendor", dc=FAILS, required_mark='Beauty Mark')
    mark = mark_condition_id('Beauty Mark', ME).removeprefix(CONDITION_PREFIX)
    assert w.foe_conditions == {mark, "charmed", "reaction_denied", "bar"} and w.foe_damage == 0
    overwhelmed = [c for c in w.foe.conditions.values() if c.data.get("bar", {}).get("one_activity")]
    assert len(overwhelmed) == 1 and overwhelmed[0].data["label"] == "Overwhelmed by Splendor"
    denials = [expiry for name, expiry in conditions(w.foe) if name == "reaction_denied"]
    assert len(denials) == 1 and denials[0].startswith("END_OF_TURN_AT:")  # one turn's worth, not the minute of the Charm as well
    assert overwhelmed[0].expires_on == denials[0]
    assert Cast(BEAUTY, [SPLENDOR], "Unbearable Splendor", dc=PASSES, required_mark='Beauty Mark').foe_conditions == {mark}


def test_beauty_that_judges_charms_on_a_failed_save_and_does_no_damage_when_cast():
    w = Cast(BEAUTY, [JUDGES], "Beauty That Judges", dc=FAILS, required_mark='Beauty Mark')
    assert "charmed" in w.foe_conditions and w.foe_damage == 0  # the Psychic damage is a later trigger (a rider), not the cast
    mark = mark_condition_id('Beauty Mark', ME).removeprefix(CONDITION_PREFIX)
    assert Cast(BEAUTY, [JUDGES], "Beauty That Judges", dc=PASSES, required_mark='Beauty Mark').foe_conditions == {mark}


# ---------------------------------------------------------------- Beastmastery

def test_ten_thousand_beast_procession_buffs_the_ally_and_frightens_the_foe_when_it_starts_its_turn():
    w = Cast(BEASTMASTERY, [PROCESSION], "Ten-Thousand-Beast Procession", ally_at=(3, 7), foe_hp=500)
    speeds = [m for m in modifiers(w.ally) if m[0] == "speed_ft"]
    assert speeds and speeds[0][1] == 10  # "+10 feet of Speed" to the allies, not the caster
    assert w.ally.temporary_hp == 2 * w.me.proficiency_bonus and w.me.temporary_hp == 0  # "twice your Proficiency Bonus", for the allies
    assert not [m for m in modifiers(w.me) if m[0] == "speed_ft"] and w.granted == 0
    assert not w.saves() and "frightened" not in w.foe_conditions  # the save is made by a creature that starts its turn in the area
    w.advance_to(AN)
    assert len(w.saves()) == 1 and "frightened" in w.foe_conditions


def test_court_of_fang_and_rein_gives_the_caster_and_an_ally_ten_feet_of_speed_and_nothing_else():
    w = Cast(BEASTMASTERY, [FANG_AND_REIN], "Court of Fang and Rein", ally_at=(3, 7))
    for actor in (w.me, w.ally):
        assert [m[1] for m in modifiers(actor) if m[0] == "speed_ft"] == [10]
    assert w.me.temporary_hp == w.ally.temporary_hp == 0 and w.granted == 0


def test_one_rider_one_beast_gives_ac_and_dexterity_save_advantage_and_no_free_movement():
    w = Cast(BEASTMASTERY, [ONE_RIDER], "One Rider, One Beast")
    assert [m[1] for m in modifiers(w.me) if m[0] == "armor_class"] == [2]
    assert "save_against" in {name for name, _ in conditions(w.me)}
    assert w.granted == 0 and w.moved == 0  # "when the mount is hit, move 5 feet" is a reaction line


def test_great_beast_charge_is_the_mounted_pairs_action_and_no_longer_a_lone_attack():
    """"You and your mount move up to the mount's Speed": the charge is the mounted rider's action (combat/ext/mounts.py, tests/test_mounts.py:
    its passed-save push of 5 feet, its failed-save push of 15 feet or Prone, and no Pack Attack row are checked there), so a sheet
    with no mount is no longer given the closing attack as a stand-alone action."""
    b = bundle(BEASTMASTERY, [GREAT_CHARGE, PACK_ATTACK])
    assert "Great Beast Charge" not in {r["display_name"] for r in b["action_catalog"]}
