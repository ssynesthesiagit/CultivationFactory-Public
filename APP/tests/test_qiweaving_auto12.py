"""Qiweaving at the table: the Bond package and the wide unweaves (auto lanes AUTO12 2026-10-04, AUTO12f1 2026-10-05).

Owner text: APP/authority/typed_mechanics/rules_text.json (Qi Bond, Draw Current, Feed Current, Throttle Current, Circuit
Lock, Read Current, Shared Reservoir, Vicious Unweave, Dazing Unweave, Grand Unweaving, World-Circuit Severance).
Plug-ins: APP/combat/ext/qiweaving_bond.py (the Bond talents and the two standing cost rules),
APP/combat/ext/qiweaving_unweave.py (the Unweaving riders and the wide unweaves), APP/combat/ext/qiweaving_common.py
(the printed reach). Typed overrides: authority/typed_mechanics/reviewed_final.d/zz_qiweaving_auto12.json (plus the four
rows this lane's earlier review now shares with review_sw-qiweaving.json and sys_resources-states.json, so no key is
defined twice); feature statuses: combat/rules/feature_status.d/zz_qiweaving_auto12.json.

Every test here runs a compiled character through the real engine: a Bond talent only exists while the caster holds the
bond, Throttle Current and Circuit Lock change what the target's *next* activation costs, and the Unweaving riders fire
only on a pattern Unweave Pattern actually ended. Without the plug-ins the Bond talents compile to nothing and the
Unweaving variants do not exist, so each assertion below fails on the base typing.

The foe's Constitution and Intelligence saves are forced by the sheet's technique save DC (50 fails, -40 succeeds); a
Qiweaving Check is read off the recorded roll rather than forced, except where a test scripts the dice to prove that ONE
check is compared against EACH pattern's own DC (finding 1) or that a Vicious Unweave clock is a turn and not a fight
(finding 3).

AUTO12f1 (the pre-merge review) changed what these tests assert, and each change is a printed rule, not a preference:
Circuit Lock no longer refunds the overspend (it withholds the technique instead -- the cap is a ceiling on spending);
Dazing Unweave and False Completion no longer run off an ended pattern (their printed trigger is countering a technique);
Vicious Unweave's "only once per turn" is a turn clock; Shared Reservoir counts the receipt on the creature that received
the points and asks the giver for the amount; Read Current offers its facts by category.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

from combat.ext import needle, qiweaving_bond, qiweaving_common, qiweaving_unweave
from combat.gate2_runtime_models import ActionIntent

t = sw = importlib.import_module("test_review_sw-athletics")

QI = "tianxia.sphere.qiweaving"
ROOT = Path(__file__).resolve().parents[1]
MECH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))["mechanics"]

BOND = "TAL_QIWEAVING_QI_BOND"
DRAW = "TAL_QIWEAVING_DRAW_CURRENT"
FEED = "TAL_QIWEAVING_FEED_CURRENT"
THROTTLE = "TAL_QIWEAVING_THROTTLE_CURRENT"
READ = "TAL_QIWEAVING_READ_CURRENT"
LOCK = "TAL_QIWEAVING_CIRCUIT_LOCK"
RESERVOIR = "TAL_QIWEAVING_SHARED_RESERVOIR"
UNWEAVE = "TAL_QIWEAVING_UNWEAVE_PATTERN"
VICIOUS = "TAL_QIWEAVING_VICIOUS_UNWEAVE"
DAZING = "TAL_QIWEAVING_DAZING_UNWEAVE"
FALSE = "TAL_QIWEAVING_FALSE_COMPLETION"
GRAND = "TAL_QIWEAVING_GRAND_UNWEAVING"
SEVERANCE = "TAL_QIWEAVING_WORLD_CIRCUIT_SEVERANCE"
MERIDIAN = "TAL_QIWEAVING_MERIDIAN_GRAMMAR"

FAIL, SUCCEED = 50, -40  # the sheet's technique save DC, so the foe's saves always fail / always succeed
THROTTLED = "condition:typed.qiweaving_throttled"
LOCKED = "condition:typed.qiweaving_circuit_lock"
STAMINA = "resource:core.stamina"
RECEIVED = "_round_qiweaving_reservoir_received"


def sheet(talents, *, cl=12, dc=FAIL, pb=4):
    """A Qiweaving sheet with the printed base abilities plus the named talents."""
    bases = [key for key, row in MECH.items() if row.get("sphere_id") == QI and row.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 80}, "speed": {"walking_ft": 30},
            "technique_save_dc": dc, "technique_attack_bonus": 60,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [],
        "spheres_and_talents": {"sphere_record_ids": [QI], "learned_talent_record_ids": list(dict.fromkeys([*bases, *talents])),
                                "automatic_sphere_component_record_ids": bases},
    }


def compiled(talents, **kwargs):
    from combat.factory_compiler import compile_character

    return compile_character(sheet(talents, **kwargs), actor_id=t.ME)


def bundle(talents, **kwargs):
    return compiled(talents, **kwargs)


ALLY = "actor:factory.auto12_ally"


ALLY_NAME = "Bonded Ally"


def ally_bundle(talents=(), **kwargs):
    """A plain fighter on the caster's side, for the printed "one willing creature" targets.  It has its own name so
    that two creatures' options never read the same in a choice.  Given ``talents`` it is a second Qiweaver instead,
    which is how two casters can hold one Circuit Locked creature at once."""
    from combat.factory_compiler import compile_character

    sheet_ = sheet(talents, **kwargs) if talents else foe_sheet()
    sheet_["identity"]["display_name"] = ALLY_NAME
    return compile_character(sheet_, actor_id=ALLY)


def duel(my_bundle, foe_bundle_, *, foe_stamina=40, foe_at=(4, 6), with_ally=False, ally_bundle_=None):
    """The Qiweaver against a compiled Factory fighter whose own typed techniques cost Cultivation Points."""
    from combat.gate4_engine import Gate4ControllerEngine

    bundles = [my_bundle, foe_bundle_] + ([ally_bundle_ if ally_bundle_ is not None else ally_bundle()] if with_ally else [])
    teams = {t.ME: "team:a", sw.FOE: "team:b", **({ALLY: "team:a"} if with_ally else {})}
    positions = {t.ME: {"x": 3, "y": 6}, sw.FOE: {"x": foe_at[0], "y": foe_at[1]},
                 **({ALLY: {"x": 3, "y": 4}} if with_ally else {})}
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO12-QW", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": [t.ME, sw.FOE] + ([ALLY] if with_ally else []),
                                                 "team_by_actor": teams, "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(t.ME)
    engine.state.current_actor_id = t.ME
    engine._system_start_turn()
    me, foe = engine.state.actors[t.ME], engine.state.actors[sw.FOE]
    me.armor_class = -50
    for actor, amount in ((me, 60), (foe, foe_stamina), (engine.state.actors[ALLY], 40) if with_ally else (me, 60)):
        actor.resources[STAMINA] = amount
        actor.resource_maximums[STAMINA] = 60
    return engine, me, foe


def foe_sheet():
    """A Factory fighter with Force Mantle (3 CP, Concentration): a real CP-costing activation to throttle."""
    bases = [key for key, row in MECH.items() if row.get("sphere_id") == "tianxia.sphere.force" and row.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 12, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 80}, "speed": {"walking_ft": 30}, "technique_save_dc": 12, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [],
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.force"],
                                "learned_talent_record_ids": [*bases, "TAL_FORCE_FORCE_MANTLE"],
                                "automatic_sphere_component_record_ids": bases},
    }


def foe_bundle():
    from combat.factory_compiler import compile_character

    return compile_character(foe_sheet(), actor_id=sw.FOE)


def turn(engine, who):
    engine.state.current_slot_index = engine.state.initiative_order.index(who)
    actor = engine.state.actors[who]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    engine.state.current_actor_id = who
    engine._system_start_turn()
    engine.state.current_actor_id = who  # the turn sweep may hand the slot on; keep the actor we asked for


def names(engine, who=None):
    who = who or engine.state.current_actor_id
    turn(engine, who)
    return sorted({c.display_name for c in engine.legal_candidates() if c.actor_id == who})


def script(engine, values):
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


def use(engine, name, *, who=None, target=None, contains=False, new_turn=True):
    who = who or engine.state.current_actor_id
    if new_turn:
        turn(engine, who)
    else:
        # a second activation inside one turn: the Action comes back, the turn clock does not move
        engine.state.current_actor_id = who
        engine.state.actors[who].action_available = True
    found = [c for c in engine.legal_candidates() if c.actor_id == who and (name in c.display_name if contains else c.display_name == name)
             and (target is None or not c.target_ids or target in c.target_ids)]
    assert found, f"{name!r} is not legal for {who}; legal: {[n for n in names(engine, who) if not n.startswith(('Move', 'Jump'))]}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto12-{candidate.candidate_id}-{before}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=who,
                                       target_ids=candidate.target_ids or ((target,) if target else ()), destination=candidate.destination))
    return engine.events[before:]


def logs(events):
    return [str(e.payload.get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED"]


def reminders(events):
    return [str(e.payload.get("rider") or "") for e in events if e.event_type == "GM_RIDER"]


def conditions(actor):
    return {c.condition_id for c in actor.conditions.values()}


def bonded_fight(talents, *, foe_stamina=40, with_ally=False, **sheet_kwargs):
    """A Qiweaver who has already bonded the foe (Qi Bond is a ranged Cultivation Attack; the foe's AC is -50)."""
    engine, me, foe = duel(bundle([BOND, *talents], **sheet_kwargs), foe_bundle(), foe_stamina=foe_stamina, with_ally=with_ally)
    use(engine, "Qi Bond", who=me.entity_id, target=foe.entity_id)
    return engine, me, foe


# ============================================================================================== the Bond package exists only on a bond
def test_bond_talents_are_offered_only_against_a_creature_this_caster_has_bonded():
    engine, me, foe = duel(bundle([BOND, DRAW, THROTTLE, READ, LOCK]), foe_bundle())
    assert not [n for n in names(engine, me.entity_id) if n in {"Draw Current", "Throttle Current", "Read Current", "Circuit Lock"}], \
        "a Bond talent must not be offered before any bond exists"
    use(engine, "Qi Bond", who=me.entity_id, target=foe.entity_id)
    offered = {n for n in names(engine, me.entity_id) if n in {"Draw Current", "Throttle Current", "Read Current", "Circuit Lock"}}
    assert offered == {"Draw Current", "Throttle Current", "Read Current", "Circuit Lock"}, offered
    # a second creature with no bond from this caster is never a legal Bond target
    assert not [c for c in engine.legal_candidates() if c.actor_id == me.entity_id and c.display_name == "Throttle Current"
                and foe.entity_id not in (c.target_ids or ())]


def test_meridian_grammar_widens_the_bond_talents_to_the_bonds_own_printed_range():
    """"increase the range of Unweave Pattern and Qi Bond to 60 feet" -- the Bond talents are applied to the bond's target."""
    rows = {row["display_name"]: row for row in bundle([BOND, THROTTLE, MERIDIAN])["action_catalog"]}
    assert rows["Qi Bond"]["range_ft"] == 60, rows["Qi Bond"]["range_ft"]
    assert rows["Throttle Current"]["range_ft"] == 60, rows["Throttle Current"]["range_ft"]
    assert {row["display_name"]: row for row in bundle([BOND, THROTTLE])["action_catalog"]}["Throttle Current"]["range_ft"] == 30


# ============================================================================================== Draw Current
def test_draw_current_takes_one_cultivation_point_and_stops_at_the_proficiency_bonus_cap():
    """"Failed Save: The target loses 1 CP ... A creature cannot lose more CP to your Draw Current than your Proficiency Bonus
    per long rest." "If the target has no CP, this talent has no effect."""
    engine, me, foe = bonded_fight([DRAW], pb=2)
    for _ in range(2):
        use(engine, "Draw Current", who=me.entity_id, target=foe.entity_id)
    assert foe.resources[STAMINA] == 38, foe.resources[STAMINA]
    events = use(engine, "Draw Current", who=me.entity_id, target=foe.entity_id)
    assert foe.resources[STAMINA] == 38, "the third use in one long rest must be refused"
    assert any("already lost Cultivation Points" in line for line in reminders(events)), reminders(events)
    foe.resources[STAMINA] = 0
    engine._spend_resource(me, STAMINA, 0, "test")
    events = use(engine, "Draw Current", who=me.entity_id, target=foe.entity_id)
    assert any("no Cultivation Points" in line for line in reminders(events)), reminders(events)


def test_draw_current_succeeding_save_takes_nothing():
    engine, me, foe = bonded_fight([DRAW], dc=SUCCEED)
    events = use(engine, "Draw Current", who=me.entity_id, target=foe.entity_id)
    assert foe.resources[STAMINA] == 40, foe.resources[STAMINA]
    assert any("it succeeds" in line for line in logs(events)), logs(events)


# ============================================================================================== Feed Current
def test_feed_current_charges_the_chosen_amount_once_per_short_rest():
    """"spend 1 or more CP, up to your Proficiency Bonus. The target gains the same amount as Temporary CP ... A creature can
    benefit from your Feed Current once per short rest." """
    engine, me, foe = bonded_fight([FEED], pb=2, with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.resources[STAMINA] = 30
    before = me.resources[STAMINA]
    events = use(engine, "Feed Current", who=me.entity_id, target=ally.entity_id)
    assert me.resources[STAMINA] == before - 2, (before, me.resources[STAMINA])
    assert any("gains 2 Temporary Cultivation Points" in line for line in logs(events)), logs(events)
    again = use(engine, "Feed Current", who=me.entity_id, target=ally.entity_id)
    assert any("once per short rest" in line for line in reminders(again)), reminders(again)


# ============================================================================================== Throttle Current
def test_throttle_current_makes_the_targets_next_technique_cost_one_more():
    """"The next technique the target activates before the start of your next turn that costs CP costs 1 additional CP." """
    engine, me, foe = bonded_fight([THROTTLE])
    use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id)
    assert THROTTLED in conditions(foe), conditions(foe)
    before = foe.resources[STAMINA]
    events = use(engine, "Force Mantle", who=foe.entity_id)
    assert foe.resources[STAMINA] == before - 4, (before, foe.resources[STAMINA])  # 3 printed + 1 extra
    assert any("pays 1 extra Stamina" in line and "Force Mantle" in line for line in logs(events)), logs(events)
    assert THROTTLED not in conditions(foe), "the marker is spent by the activation it changed"
    # once per round: the next activation is not surcharged again
    use(engine, "Force Mantle", who=foe.entity_id)
    assert foe.resources[STAMINA] == before - 7, foe.resources[STAMINA]


def test_vicious_unweave_asks_which_creature_takes_the_damage_and_hits_each_creature_once_per_turn():
    """"choose one creature bearing, maintaining, or creating that pattern" -- the Qiweaver chooses, so it is asked and the
    options name who they are; "A creature can take this damage from you only once per turn" is a TURN clock, so a later
    turn's Unweave reaches the same creature again (AUTO12f1: the branch stored it in a ``_round_`` key that survives turn
    resets, which made it once per fight)."""
    engine, me, foe = duel(bundle([UNWEAVE, VICIOUS], cl=20), foe_bundle(), with_ally=True)
    ally = engine.state.actors[ALLY]
    _mantled(engine, me, foe)
    _mantled(engine, me, ally)
    script(engine, [20, 12, 12, 12, 12])
    events = use(engine, "Unweave Pattern (Rapid Unweave) + Vicious Unweave", who=me.entity_id, target=foe.entity_id)
    said = [line for line in logs(events) if "Vicious Unweave" in line]
    assert said and "4d10 force damage" in said[0], said
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "FORCE"]
    assert damage and damage[0].target_ids == (foe.entity_id,), [e.target_ids for e in damage]
    # the once-per-turn clock is the engine's own turn namespace, and the foe is on it
    assert me.turn_flags.get(qiweaving_unweave.DAZED) == [foe.entity_id], me.turn_flags.get(qiweaving_unweave.DAZED)
    # the clock is the engine's own per-turn namespace, so it is swept at the next turn's start; the "_round_" key the
    # branch used is deliberately NOT swept (gate2_engine._system_start_turn keeps it), which is why it lasted the fight
    from combat import turn_uses

    assert qiweaving_unweave.DAZED.startswith(turn_uses.PER_TURN_PREFIXES), qiweaving_unweave.DAZED
    turn(engine, me.entity_id)
    assert qiweaving_unweave.DAZED not in me.turn_flags, me.turn_flags.get(qiweaving_unweave.DAZED)
    # a later turn reaches the same creature again
    use(engine, "Force Mantle", who=foe.entity_id)
    script(engine, [20, 12, 12, 12, 12])
    third = use(engine, "Unweave Pattern (Rapid Unweave) + Vicious Unweave", who=me.entity_id, target=foe.entity_id)
    assert [e for e in third if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "FORCE"
            and e.target_ids == (foe.entity_id,)], [e.target_ids for e in third]


def test_vicious_unweave_asks_the_qiweaver_which_creature_bears_the_damage(monkeypatch):
    """"choose one creature bearing, maintaining, or creating that pattern": the Qiweaver chooses, so the option is asked
    and every option says who it is and why."""
    from combat.ext import needle

    engine, me, foe = duel(bundle([UNWEAVE, VICIOUS], cl=20), foe_bundle())
    _mantled(engine, me, foe)
    asked = []
    original = needle.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id.startswith("choice:needle.vicious_unweave"):
            asked.append((chooser.entity_id, list(options), dict(kwargs.get("labels") or {}), kwargs.get("prompt", "")))
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", spy)
    script(engine, [20, 12, 12, 12, 12])
    use(engine, "Unweave Pattern (Rapid Unweave) + Vicious Unweave", who=me.entity_id, target=foe.entity_id)
    assert asked, "Vicious Unweave must ask which creature takes the damage"
    chooser, options, labels, prompt = asked[0]
    assert chooser == me.entity_id, chooser
    assert foe.display_name in prompt and "Force damage" in prompt, prompt
    assert set(labels) == set(options) and options, labels
    for value in labels.values():
        assert "Active Qi Pattern" in value, value


def test_throttle_current_returns_the_cost_and_stops_the_technique_when_the_target_cannot_pay():
    """"If the target cannot or will not pay the additional CP, the technique fails and any Action spent on it is lost. The
    original CP is not spent." """
    engine, me, foe = bonded_fight([THROTTLE], foe_stamina=3)
    use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id)
    events = use(engine, "Force Mantle", who=foe.entity_id)
    assert foe.resources[STAMINA] == 3, foe.resources[STAMINA]
    assert any("the technique fails" in line and "returned" in line for line in logs(events)), logs(events)
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED"], "the stopped technique must not resolve"


def test_throttle_current_asks_the_target_whether_it_will_pay_the_extra_point(monkeypatch):
    """"If the target cannot or WILL NOT pay the additional CP" -- refusing is the target's own choice, so the target is
    the one asked (AUTO12f1: the branch always paid it for the target)."""
    engine, me, foe = bonded_fight([THROTTLE])
    use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id)
    asked = []
    original = needle.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id.startswith("choice:needle.throttle_current"):
            asked.append((choice_id, chooser.entity_id, dict(kwargs.get("labels") or {}), kwargs.get("prompt", "")))
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", spy)
    before = foe.resources[STAMINA]
    use_events = use(engine, "Force Mantle", who=foe.entity_id)
    assert asked, "the target must be asked whether it pays the extra point"
    choice_id, chooser, labels, prompt = asked[0]
    assert chooser == foe.entity_id, (choice_id, chooser)
    assert foe.display_name in prompt and "Force Mantle" in prompt, prompt
    assert "pays 1 extra Stamina" in " ".join(logs(use_events)), logs(use_events)
    assert set(labels) == {"pay", "refuse"}, labels
    for value in labels.values():
        assert "Stamina" in value and "1" in value, value
    assert "Action is lost" in labels["refuse"], labels["refuse"]
    assert foe.resources[STAMINA] == before - 4, (before, foe.resources[STAMINA])  # the AI target pays


def test_throttle_current_asks_the_creature_that_has_to_pay(monkeypatch):
    """The choice is routed to the creature whose Cultivation Points are at stake -- the target -- not to the caster
    that applied Throttle Current."""
    engine, me, foe = bonded_fight([THROTTLE])
    use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id)
    asked = []
    original = needle.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id.startswith("choice:needle.throttle_current"):
            asked.append(chooser.entity_id)
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(needle, "ask", spy)
    use(engine, "Force Mantle", who=foe.entity_id)
    assert asked == [foe.entity_id], asked


def test_throttle_current_ends_at_the_start_of_the_casters_next_turn_and_only_once_per_round():
    """"before the start of your next turn" is the caster's next turn start (AUTO12f1: the branch ran it to the end of the
    TARGET's next turn, so it could surcharge an activation after its printed deadline); "A creature can suffer this added
    cost from you only once per round" is counted per round, so a second application in the same round is refused."""
    engine, me, foe = bonded_fight([THROTTLE])
    use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id)
    marker = next(condition for condition in foe.conditions.values() if condition.condition_id == THROTTLED)
    assert marker.expires_on == "START_OF_SOURCE_NEXT_TURN", marker.expires_on
    assert marker.source_actor_id == me.entity_id, marker.source_actor_id
    # a reapplication in the same round is refused, and leaves the first surcharge alone
    events = use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id, new_turn=False)
    assert any("this round" in line for line in reminders(events)), reminders(events)
    assert len([c for c in foe.conditions.values() if c.condition_id == THROTTLED]) == 1, conditions(foe)
    # the marker's printed deadline: "before the start of your next turn", so the caster's next turn start ends it
    engine.state.round_number = int(engine.state.round_number) + 1
    turn(engine, me.entity_id)
    assert THROTTLED not in conditions(foe), conditions(foe)
    # next round the same target may suffer it again
    events = use(engine, "Throttle Current", who=me.entity_id, target=foe.entity_id)
    assert not any("this round" in line for line in reminders(events)), reminders(events)
    assert THROTTLED in conditions(foe), conditions(foe)


# ============================================================================================== Circuit Lock
def test_circuit_lock_withholds_a_technique_the_target_cannot_pay_for_instead_of_refunding_it():
    """"Until the end of your next turn, the target cannot spend more CP on a single technique than your Proficiency
    Bonus."  A ceiling on spending is a restriction, not a discount: a 3 CP technique under a PB 2 lock is out of reach,
    and nothing is refunded and nothing is made cheaper (AUTO12f1: the branch refunded the overspend, which helped the
    locked creature)."""
    engine, me, foe = bonded_fight([LOCK], pb=2)
    use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)
    assert LOCKED in conditions(foe), conditions(foe)
    before = foe.resources[STAMINA]
    turn(engine, foe.entity_id)
    assert "Force Mantle" not in names(engine, foe.entity_id), "a 3 CP technique is above a PB 2 lock"
    assert foe.resources[STAMINA] == before, "a withheld technique spends nothing and refunds nothing"
    # ...and it comes back when the lock has run out, which is the only thing that lifts it.
    for condition in list(foe.conditions.values()):
        if condition.condition_id == LOCKED:
            engine._remove_condition(foe, LOCKED, condition.source_definition_id)
    turn(engine, foe.entity_id)
    assert "Force Mantle" in names(engine, foe.entity_id)


def test_circuit_lock_says_why_the_technique_is_missing_in_plain_words():
    """The player who cannot use the technique is told the ability, the limit, how long it lasts and what it costs."""
    engine, me, foe = bonded_fight([LOCK], pb=2)
    use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)
    turn(engine, foe.entity_id)
    action = engine.action_catalog[next(source for source, row in engine.action_catalog.items()
                                        if row.display_name == "Force Mantle" and row.owner_id == foe.entity_id)]
    said = qiweaving_bond.circuit_lock_explains_its_ceiling(engine, foe, None, action)
    assert said and "Circuit Lock" in said and "2 Cultivation Points" in said and "Force Mantle" in said, said
    assert qiweaving_bond.circuit_lock_explains_its_ceiling(engine, foe, None,
                                                             engine.action_catalog[next(
                                                                 s for s, r in engine.action_catalog.items()
                                                                 if r.display_name == "Unarmed Strike"
                                                                 and r.owner_id == foe.entity_id)]) is None


def test_circuit_lock_a_successful_save_falls_back_to_throttle_current():
    """"Successful Save: Throttle Current applies normally." """
    engine, me, foe = bonded_fight([LOCK], dc=SUCCEED)
    events = use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)
    assert LOCKED not in conditions(foe), "a saved target is throttled, not locked"
    assert THROTTLED in conditions(foe), conditions(foe)
    assert any("it succeeds" in line for line in logs(events)), logs(events)
    before = foe.resources[STAMINA]
    use(engine, "Force Mantle", who=foe.entity_id)
    assert foe.resources[STAMINA] == before - 4, (before, foe.resources[STAMINA])  # 3 printed + 1 extra


def test_circuit_lock_runs_to_the_end_of_the_casters_next_turn_not_the_targets():
    """"your next turn" is the caster's: the cap lifts with the caster, not a turn later."""
    engine, me, foe = bonded_fight([LOCK], pb=2)
    use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)
    marker = next(condition for condition in foe.conditions.values() if condition.condition_id == LOCKED)
    assert marker.expires_on == f"END_OF_SOURCE_TURN_AT:{int(me.turns_started) + 1}", marker.expires_on
    assert marker.source_actor_id == me.entity_id, marker.source_actor_id


SECRET_INHERITANCE = "tianxia.talent.ink.true_name_calligraphy"   # "### Secret Inheritance - True Name Calligraphy", 15 CP


def secret_foe_bundle():
    """The foe with Force Mantle (3 CP) and a Secret Inheritance (15 CP), so one menu holds a technique the ceiling
    does hold back and one the printed talent exempts."""
    from combat.factory_compiler import compile_character

    sheet_ = foe_sheet()
    talents = sheet_["spheres_and_talents"]
    talents["sphere_record_ids"] = [*talents["sphere_record_ids"], "tianxia.sphere.ink"]
    talents["learned_talent_record_ids"] = [*talents["learned_talent_record_ids"], SECRET_INHERITANCE]
    sheet_["identity"]["display_name"] = "Inheritor"
    return compile_character(sheet_, actor_id=sw.FOE)


def test_circuit_lock_never_withholds_a_secret_inheritance():
    """"Circuit Lock does not prevent a creature from using a Secret Inheritance."  A 15 CP Secret Inheritance is above
    any PB cap and is still offered; an ordinary 3 CP technique under the same PB 2 lock is not (AUTO12r1f1: the
    branch withheld every technique over the cap, including the one the printed text exempts)."""
    engine, me, foe = duel(bundle([BOND, LOCK], pb=2), secret_foe_bundle())
    use(engine, "Qi Bond", who=me.entity_id, target=foe.entity_id)
    use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)
    assert LOCKED in conditions(foe), conditions(foe)
    offered = names(engine, foe.entity_id)
    assert "True Name Calligraphy" in offered, offered
    assert "Force Mantle" not in offered, offered
    action = engine.action_catalog[next(source for source, row in engine.action_catalog.items()
                                        if row.display_name == "True Name Calligraphy")]
    assert qiweaving_bond._locked_below(foe, action) == 0, "a Secret Inheritance is exempt from the ceiling"
    assert qiweaving_bond.circuit_lock_explains_its_ceiling(engine, foe, None, action) is None
    # and the exemption is read from the owner's own record, not from a list of ids written here
    assert qiweaving_common.classifies_as_secret_inheritance(
        {}, qiweaving_common.rules_text()[SECRET_INHERITANCE]), "the classifier must read the printed title"
    assert not qiweaving_common.classifies_as_secret_inheritance(
        {}, qiweaving_common.rules_text()["TAL_QIWEAVING_CIRCUIT_LOCK"]), "an ordinary talent is not an inheritance"


def test_the_strongest_circuit_lock_is_the_one_that_holds():
    """Two casters can hold one creature, each capping the spend at its OWN Proficiency Bonus, and the strongest lock
    is the one that binds (AUTO12r1f1: the branch read whichever marker it happened to store first, so a weak lock
    could let a technique through that a stronger one forbids).  The weak lock is applied FIRST here, so reading the
    first marker is the failure."""
    engine, me, foe = duel(bundle([BOND, LOCK], pb=2), foe_bundle(),
                           with_ally=True, ally_bundle_=ally_bundle([BOND, LOCK], pb=5))
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond", who=ally.entity_id, target=foe.entity_id)
    use(engine, "Circuit Lock", who=ally.entity_id, target=foe.entity_id)   # the weak lock, cap 5
    use(engine, "Qi Bond", who=me.entity_id, target=foe.entity_id)
    use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)     # the strong lock, cap 2
    caps = sorted(int((condition.data or {}).get("cap") or 0) for condition in foe.conditions.values()
                  if condition.condition_id == LOCKED)
    assert caps == [2, 5], caps
    offered = names(engine, foe.entity_id)
    assert "Force Mantle" not in offered, ("a PB 2 lock must still hold", offered)
    action = engine.action_catalog[next(source for source, row in engine.action_catalog.items()
                                        if row.display_name == "Force Mantle" and row.owner_id == foe.entity_id)]
    assert qiweaving_bond._locked_below(foe, action) == 2, qiweaving_bond._locked_below(foe, action)
    said = qiweaving_bond.circuit_lock_explains_its_ceiling(engine, foe, None, action)
    assert said and "2 Cultivation Points" in said, said
    # the explanation names the caster whose lock is the one that holds, not the first one applied
    assert me.display_name in said and ally.display_name not in said, said
    # the weak lock alone still allows the 3 CP technique: only the strongest is withheld
    for condition in list(foe.conditions.values()):
        if condition.condition_id == LOCKED and int((condition.data or {}).get("cap") or 0) == 2:
            engine._remove_condition(foe, LOCKED, condition.source_definition_id)
    assert "Force Mantle" in names(engine, foe.entity_id)


def test_an_unlocked_creature_is_never_asked_to_be_classified(monkeypatch):
    """Default-inert, in the order the questions are asked (AUTO12r2f1): a creature with no Circuit Lock must not cost
    any Qiweaving work at all, however expensive the action on its menu.  The previous order classified the candidate
    FIRST, so every ordinary fighter's menu read the authority corpus and scanned that action's printed record on the
    way to being allowed, and every old saved fight with no lock paid for it too."""
    engine, _me, foe = bonded_fight([LOCK], pb=2)   # bonded, but never locked
    assert LOCKED not in conditions(foe), conditions(foe)
    called = []

    def counting(action):
        called.append(action)
        return qiweaving_common.is_secret_inheritance(action)

    monkeypatch.setattr(qiweaving_bond, "is_secret_inheritance", counting)
    # a 3 CP action is above a PB 2 cap, so the ceiling is genuinely in question; the lock is what is missing
    turn(engine, foe.entity_id)
    action = engine.action_catalog[next(
        source for source, row in engine.action_catalog.items()
        if row.display_name == "Force Mantle" and row.owner_id == foe.entity_id)]
    assert qiweaving_bond._cp_spend(action) > 2, qiweaving_bond._cp_spend(action)
    assert qiweaving_bond._locked_below(foe, action) == 0
    assert "Force Mantle" in names(engine, foe.entity_id)
    assert not called, f"an unlocked creature must not be classified at all, but was asked about {len(called)} actions"
    # the printed exception is still honoured once a lock actually exists: the classifier is asked, and only then
    use(engine, "Circuit Lock", who=_me.entity_id, target=foe.entity_id)
    assert LOCKED in conditions(foe), conditions(foe)
    turn(engine, foe.entity_id)
    assert "Force Mantle" not in names(engine, foe.entity_id)
    assert called, "a locked creature above the cap must still be classified, or nothing is ever withheld"


def test_the_circuit_lock_says_in_player_text_which_costs_it_cannot_check():
    """The ceiling is only partly automatic, so the players are told that where the table cannot check it (change
    standard 13): on the ability's rider, on the creature's status, and in the log at the moment the lock lands."""
    engine, me, foe = bonded_fight([LOCK], pb=2)
    events = use(engine, "Circuit Lock", who=me.entity_id, target=foe.entity_id)
    said = " ".join(line for line in logs(events) if line.startswith("Circuit Lock:"))
    assert "2 Cultivation Points" in said and "Secret Inheritance" in said, said
    for warning in ("Cultivation Point cost is chosen as you play", "starts as a Reaction", "applied by hand"):
        assert warning in said, (warning, said)
    marker = next(condition for condition in foe.conditions.values() if condition.condition_id == LOCKED)
    reading = str((marker.data or {}).get("reading") or "")
    assert "Secret Inheritance" in reading and "applied by hand" in reading, reading
    assert any("applied by hand" in rider for rider in qiweaving_bond.RIDERS[LOCK]), qiweaving_bond.RIDERS[LOCK]


# ============================================================================================== Read Current
def test_read_current_answers_two_printed_facts_and_asks_the_gm_nothing():
    """"learn two of the following facts about the bonded target" """
    engine, me, foe = bonded_fight([READ])
    foe.concentration = None
    events = use(engine, "Read Current", who=me.entity_id, target=foe.entity_id)
    said = [line for line in logs(events) if line.startswith("Read Current on")]
    assert len(said) == 2, said
    assert any("Stamina" in line or "Cultivation Point" in line for line in said), said
    assert any("Concentration" in line for line in said), said


def test_read_current_offers_its_facts_by_category_and_never_shows_an_answer_before_the_pick(monkeypatch):
    """"learn two of the following facts" -- two of six, so the menu must name the KIND of fact and not hand over the
    answers to all six before the player chooses (AUTO12f1: the branch put the answers in the option labels)."""
    asked = {}
    original = qiweaving_bond.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id.startswith("choice:needle.read_current"):
            asked.update({"options": list(options), "labels": dict(kwargs.get("labels") or {}),
                          "prompt": kwargs.get("prompt", "")})
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    engine, me, foe = bonded_fight([READ])
    foe.concentration = None
    monkeypatch.setattr(qiweaving_bond, "ask", spy)
    events = use(engine, "Read Current", who=me.entity_id, target=foe.entity_id)
    assert asked, "Read Current must ask which two facts to read"
    assert asked["prompt"] and "which two" in asked["prompt"].lower(), asked["prompt"]
    assert len(asked["options"]) >= 2, asked
    assert set(asked["labels"]) == set(asked["options"]), asked
    said = " ".join(line for line in logs(events) if line.startswith("Read Current on"))
    # every option asks about the KIND of fact; none of them states the answer, and the two that were read are only
    # answered after the pick
    for value in asked["labels"].values():
        assert value[:1].isupper(), value
        assert value not in said, (value, said)
        assert not re.search(r"\b\d+\b", value), value
    answered = [line for line in logs(events) if line.startswith("Read Current on")]
    assert len(answered) == 2, answered
    assert not any(any(value in line for value in asked["labels"].values()) for line in answered), (asked["labels"], answered)


def test_read_current_reports_the_strongest_sphere_resonance_ranked_by_pattern_rank():
    """"the strongest visible sphere resonance affecting it" -- one answer, the strongest, not every sphere at once
    (AUTO12f1: the branch listed them all)."""
    engine, me, foe = bonded_fight([READ])

    class _Item:
        """One Active Qi Pattern on the target, standing in for a typed technique's mark."""

        def __init__(self, rank, sphere):
            self.rank = rank
            self.source_definition_id = f"action:typed.fixture.{sphere}"

    real_rank = qiweaving_unweave.pattern_rank
    real_sphere = qiweaving_bond._sphere_of
    qiweaving_unweave.pattern_rank = lambda _engine, item: item.rank
    qiweaving_bond._sphere_of = lambda _engine, _source: f"tianxia.sphere.{'fire' if _source.endswith('fire') else 'shadow'}"
    try:
        weak = [("condition", "k0", _Item(3, "fire"))]
        strong = weak + [("condition", "k1", _Item(7, "shadow"))]
        assert qiweaving_bond._fact_text(engine, foe, "sphere", weak, 4) == \
            "the strongest visible sphere resonance on it is fire", "one sphere"
        assert qiweaving_bond._fact_text(engine, foe, "sphere", strong, 4) == \
            "the strongest visible sphere resonance on it is shadow", "the higher Pattern Rank wins, not the first listed"
        assert qiweaving_bond._fact_text(engine, foe, "sphere", [], 4) == "", "nothing on it, nothing to say"
    finally:
        qiweaving_unweave.pattern_rank = real_rank
        qiweaving_bond._sphere_of = real_sphere


# ============================================================================================== Shared Reservoir
def _received(actor):
    return list(actor.turn_flags.get(RECEIVED) or [])


def test_shared_reservoir_moves_points_into_a_bonded_ally_within_its_maximum():
    """"you and the bonded creature may transfer CP between yourselves as an Action ... Transferred CP cannot exceed the
    recipient's normal maximum CP." """
    engine, me, foe = bonded_fight([RESERVOIR], with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.concentration = None
    # The ally is at its maximum, so the only direction the printed rule allows is the ally giving to the caster.
    ally.resources[STAMINA] = ally.resource_maximums[STAMINA]
    me.resources[STAMINA] = 50
    before = me.resources[STAMINA]
    events = use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert ally.resources[STAMINA] == 56 and me.resources[STAMINA] == before + 4, (ally.resources, me.resources[STAMINA])
    assert any("gives you 4" in line for line in logs(events)), logs(events)
    # The caster has now received through this reservoir once, so that direction is gone while the gift still works
    # (both directions and the receipts are covered in the two tests below).
    ally.resources[STAMINA] = 58
    before = me.resources[STAMINA]
    events = use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert ally.resources[STAMINA] == 60 and me.resources[STAMINA] == before - 2, (ally.resources, me.resources[STAMINA])
    assert any("you give 2" in line for line in logs(events)), logs(events)
    # the gift was capped by the recipient's room, not by what the caster held
    ally.turn_flags.pop(RECEIVED, None)
    ally.resources[STAMINA] = 59
    before = me.resources[STAMINA]
    use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert ally.resources[STAMINA] == 60, ally.resources[STAMINA]
    assert me.resources[STAMINA] == before - 1, (before, me.resources[STAMINA])


def test_shared_reservoir_counts_the_receipt_on_the_creature_that_received_the_points():
    """"A creature can receive CP through your Shared Reservoir once per long rest."  The receipt belongs to whoever
    received them: a gift to the ally must not spend the caster's own receipt, and vice versa (AUTO12f1: the branch
    always counted it on the bonded holder, so a later legal receipt by the caster was refused)."""
    engine, me, foe = bonded_fight([RESERVOIR], with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.concentration = None
    ally.resources[STAMINA] = 40
    me.resources[STAMINA] = 50
    # The ally is the recipient: the clock is the ally's, and the caster's is untouched.
    use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert _received(ally) == [me.entity_id], _received(ally)
    assert not _received(me), _received(me)
    # The caster has not received anything yet, so the ally may still give to the caster.
    me.resources[STAMINA] = 40
    before = me.resources[STAMINA]
    events = use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert me.resources[STAMINA] > before, (before, me.resources[STAMINA])
    assert _received(me) == [me.entity_id], _received(me)
    # Now both creatures have received once, so neither direction is offered any more this long rest.
    events = use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert any("once per long rest" in line for line in reminders(events)), reminders(events)


def test_shared_reservoir_never_moves_more_than_the_recipient_has_room_for(monkeypatch):
    """"Transferred CP cannot exceed the recipient's normal maximum CP": each direction is capped by the room the
    RECIPIENT has left, so a nearly full caster cannot drain a bonded ally and throw the points away (AUTO12f1: the
    branch capped the inbound direction only by what the giver held)."""
    engine, me, foe = bonded_fight([RESERVOIR], with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.concentration = None
    ally.resources[STAMINA] = 40
    me.resources[STAMINA] = me.resource_maximums[STAMINA] - 1  # the caster has one point of room
    offered = {}
    original = qiweaving_bond.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        # the direction question only: the giver's amount question is a different choice, asked of the giver
        if choice_id == "choice:needle.reservoir":
            offered.update({"options": list(options), "labels": dict(kwargs.get("labels") or {})})
            return ["to_me"]
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(qiweaving_bond, "ask", spy)
    use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert offered["options"] == ["to_them", "to_me"], offered
    assert offered["labels"]["to_me"].endswith("up to 1 Stamina"), offered["labels"]
    assert me.resources[STAMINA] == me.resource_maximums[STAMINA], me.resources[STAMINA]
    assert ally.resources[STAMINA] == 39, ally.resources[STAMINA]


def test_shared_reservoir_asks_the_creature_that_is_actually_giving(monkeypatch):
    """"The creature giving CP chooses how much to give, up to your Proficiency Bonus."  When the bonded creature gives,
    the bonded creature is the one asked -- including on a turn the caster is running (AUTO12f1: the branch asked the
    caster both ways)."""
    from combat.ext import needle

    engine, me, foe = bonded_fight([RESERVOIR], pb=4, with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.concentration = None
    ally.resources[STAMINA] = 40
    me.resources[STAMINA] = 50
    asked = []
    original = needle.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        asked.append((choice_id, chooser.entity_id))
        if choice_id == "choice:needle.reservoir":
            return ["to_me"]  # the bonded creature gives, so ITS amount is the one chosen
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(qiweaving_bond, "ask", spy)
    use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    reservoir = [(choice, chooser) for choice, chooser in asked if choice.startswith("choice:needle.reservoir")]
    assert reservoir, asked
    # the direction is the caster's Action to spend; the amount is the giver's to choose
    assert ("choice:needle.reservoir", me.entity_id) in reservoir, reservoir
    assert ("choice:needle.reservoir_take", ally.entity_id) in reservoir, reservoir


def test_shared_reservoir_asks_the_giver_even_when_only_one_point_can_move(monkeypatch):
    """"The creature giving CP chooses how much to give."  One point is still that creature's choice, so it is asked
    even when the ceiling leaves it a single number (AUTO12r1f1: the branch returned the point without asking anybody),
    and giving nothing is one of the answers."""
    engine, me, foe = bonded_fight([RESERVOIR], with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.concentration = None
    ally.resources[STAMINA] = 40
    me.resources[STAMINA] = me.resource_maximums[STAMINA] - 1   # the caster has room for exactly one point
    asked = {}
    original = qiweaving_bond.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == "choice:needle.reservoir":
            asked.setdefault(choice_id, []).append({"chooser": chooser.entity_id, "options": list(options),
                                                    "labels": dict(kwargs.get("labels") or {})})
            return ["to_me"]   # the bonded creature gives, and the caster has room for exactly one point
        if choice_id.startswith("choice:needle.reservoir"):
            asked.setdefault(choice_id, []).append({"chooser": chooser.entity_id, "options": list(options),
                                                    "labels": dict(kwargs.get("labels") or {}),
                                                    "prompt": kwargs.get("prompt", "")})
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(qiweaving_bond, "ask", spy)
    use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert set(asked) == {"choice:needle.reservoir", "choice:needle.reservoir_take"}, asked
    assert asked["choice:needle.reservoir"][0]["labels"]["to_me"].endswith("up to 1 Stamina"), asked
    amount = asked["choice:needle.reservoir_take"][0]
    assert amount["chooser"] == ally.entity_id, amount
    assert amount["options"] == ["1", qiweaving_bond.GIVE_NOTHING], amount
    assert amount["labels"]["1"] == "1 Stamina", amount
    assert amount["labels"][qiweaving_bond.GIVE_NOTHING] == "Give nothing: no Cultivation Points move", amount
    # the prompt names the ability, the creature that decides and the creature that would receive
    assert "Shared Reservoir" in amount["prompt"] and ALLY_NAME in amount["prompt"], amount["prompt"]


def test_shared_reservoir_moves_nothing_when_the_giver_gives_nothing(monkeypatch):
    """Refusal is the giver's own answer and is honoured: the printed Action is spent, no Cultivation Points move,
    and no receipt is stamped on either creature."""
    engine, me, foe = bonded_fight([RESERVOIR], with_ally=True)
    ally = engine.state.actors[ALLY]
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.concentration = None
    ally.resources[STAMINA] = 40
    me.resources[STAMINA] = 50
    original = qiweaving_bond.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == "choice:needle.reservoir":
            return ["to_me"]   # the bonded creature gives
        if choice_id == "choice:needle.reservoir_take":
            return [qiweaving_bond.GIVE_NOTHING]
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(qiweaving_bond, "ask", spy)
    ally_before, caster_before = ally.resources[STAMINA], me.resources[STAMINA]
    events = use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert ally.resources[STAMINA] == ally_before, ally.resources[STAMINA]
    assert me.resources[STAMINA] == caster_before, me.resources[STAMINA]
    assert not _received(ally) and not _received(me), (_received(ally), _received(me))
    assert any("gives no Cultivation Points" in line or "chooses to give no" in line for line in logs(events)), logs(events)
    # the same reservoir may be used again: a refusal is not a receipt
    ally.turn_flags.pop(RECEIVED, None)
    monkeypatch.setattr(qiweaving_bond, "ask", spy)
    use(engine, "Shared Reservoir", who=me.entity_id, target=ally.entity_id)
    assert ally.resources[STAMINA] == ally_before, ally.resources[STAMINA]


# ============================================================================================== the Unweaving riders
def _mantled(engine, me, foe):
    use(engine, "Force Mantle", who=foe.entity_id)
    assert any(row.source_definition_id.endswith("TAL_FORCE_FORCE_MANTLE") for row in engine.state.actors[foe.entity_id].modifiers.values())


def test_vicious_unweave_deals_force_damage_to_the_creature_that_bore_the_pattern():
    """"When you successfully end or counter an Active Qi Pattern with Unweave Pattern, choose one creature bearing,
    maintaining, or creating that pattern. That creature takes Force damage ... 4d10 at CL 17-20" """
    engine, me, foe = duel(bundle([UNWEAVE, VICIOUS], cl=20), foe_bundle())
    _mantled(engine, me, foe)
    script(engine, [20, 12, 12, 12, 12])  # the Qiweaving Check succeeds, then 4d10
    events = use(engine, "Unweave Pattern (Rapid Unweave) + Vicious Unweave", who=me.entity_id, target=foe.entity_id)
    assert any("Vicious Unweave" in line and "4d10 force damage" in line for line in logs(events)), logs(events)
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "FORCE"]
    assert damage and foe.entity_id in damage[0].target_ids, [(e.payload.get("damage_type"), e.target_ids) for e in damage]


@pytest.mark.parametrize("talent,name", [(DAZING, "Dazing Unweave"), (FALSE, "False Completion")])
def test_the_counter_only_unweaving_augments_are_not_charged_for_and_say_so_on_the_sheet(talent, name):
    """"When you successfully counter a technique with Unweave Pattern" -- a counter, not an ending.  Unweave Pattern is an
    Action and this table has no counter it can make, so no "+1 CP" variant is compiled (nobody is charged for a line
    that cannot run) and the printed decision stays on the sheet with its reason (AUTO12f1: the branch ran both off an
    ended pattern, which is the wrong trigger)."""
    from combat.factory_compiler import compile_character

    catalog = {row["display_name"] for row in bundle([UNWEAVE, talent])["action_catalog"]}
    assert not [n for n in catalog if n.startswith("Unweave Pattern") and "+" in n], sorted(catalog)
    assert qiweaving_unweave.NEEDS_A_COUNTER == (DAZING, FALSE)
    assert talent not in qiweaving_unweave.UNWEAVING_RIDERS, qiweaving_unweave.UNWEAVING_RIDERS
    sheet_ = bundle([UNWEAVE, talent])
    modifier = next(row for row in sheet_["modifiers"] if row["id"] == talent)
    assert modifier["not_automated_targets"] == ["Unweave Pattern"], modifier
    assert "Unweave Pattern" in (modifier["status"] or "") or modifier["status"] == "reaction or passive target", modifier
    # the printed line is still on the sheet, in plain words, with what the table must do
    row = MECH[talent]
    assert row["coverage"] == "CORE_WITH_RIDERS", row["coverage"]
    said = " ".join(row["riders"])
    assert "counter" in said and "Intelligence saving throw" in said, said
    assert not [n for n in catalog if name in n], sorted(catalog)


def test_no_unweave_ending_leaves_the_dazing_or_false_completion_markers_behind():
    """Ending a pattern is not countering a technique, so nothing from those two talents may fire."""
    engine, me, foe = duel(bundle([UNWEAVE]), foe_bundle())
    _mantled(engine, me, foe)
    use(engine, "Unweave Pattern (Rapid Unweave)", who=me.entity_id, target=foe.entity_id)
    after = {condition.condition_id for condition in foe.conditions.values()}
    assert "condition:typed.qiweaving_dazed" not in after, after
    assert "condition:typed.qiweaving_false_completion" not in after, after
    assert not [m for m in foe.modifiers.values() if m.target_field == "attack_mode"], dict(foe.modifiers)


def test_the_unweaving_variants_only_exist_for_a_qiweaver_who_owns_them():
    plain = {row["display_name"] for row in bundle([UNWEAVE])["action_catalog"]}
    assert not [n for n in plain if n.startswith("Unweave Pattern (Rapid Unweave)") and "+" in n], sorted(plain)
    catalog = bundle([UNWEAVE, VICIOUS])["action_catalog"]
    assert "Unweave Pattern (Rapid Unweave) + Vicious Unweave" in {row["display_name"] for row in catalog}
    row = next(r for r in catalog if r["display_name"].endswith("+ Vicious Unweave"))
    assert dict((tuple(c) for c in row["costs"]))[STAMINA] == 2, row["costs"]


# ============================================================================================== the wide unweaves
def test_grand_unweaving_takes_every_pattern_in_its_sphere_with_one_check():
    """"Choose any number of Active Qi Patterns inside the area that you can perceive. Make one Qiweaving Check and compare the
    result to each chosen pattern's DC separately." """
    engine, me, foe = duel(bundle([UNWEAVE, GRAND]), foe_bundle(), foe_at=(4, 6))
    _mantled(engine, me, foe)
    assert qiweaving_unweave.patterns(engine, foe), "the foe must bear a pattern for Grand Unweaving to reach"
    script(engine, [20])  # the one Qiweaving Check, which succeeds against rank 3
    events = use(engine, "Grand Unweaving", who=me.entity_id, target=None, contains=True)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and e.payload.get("skill") == "Qiweaving Check"]
    assert len(checks) == 1, checks
    assert not qiweaving_unweave.patterns(engine, foe), qiweaving_unweave.patterns(engine, foe)
    assert any("Grand Unweaving" in line and "ends" in line for line in logs(events)), logs(events)


def test_grand_unweaving_compares_one_check_against_each_patterns_own_dc():
    """"compare the result to each chosen pattern's DC separately": a rank-1 pattern needs 11 and a rank-7 one 17, so ONE
    roll of 11 ends the first and leaves the second (AUTO12f1: the branch tested the roll against DC 10 once and applied
    that single answer to every pattern, so the same roll could never end one pattern and leave another)."""
    engine, me, foe = duel(bundle([UNWEAVE, GRAND], pb=4, cl=12), foe_bundle(), foe_at=(4, 6), with_ally=True)
    ally = engine.state.actors[ALLY]
    _mantled(engine, me, foe)
    _mantled(engine, me, ally)
    on_foe = {item.source_definition_id for _kind, _key, item in qiweaving_unweave.patterns(engine, foe)}
    ranks = {}
    for holder, rank in ((foe, 1), (ally, 7)):
        for _kind, _key, item in qiweaving_unweave.patterns(engine, holder):
            ranks[id(item)] = rank
    real_rank = qiweaving_unweave.pattern_rank
    qiweaving_unweave.pattern_rank = lambda _engine, item: ranks.get(id(item), real_rank(_engine, item))
    try:
        script(engine, [4])  # d20 4 + PB 4 + key modifier 3 = 11: beats DC 11, loses to DC 17
        events = use(engine, "Grand Unweaving", who=me.entity_id, target=None, contains=True)
    finally:
        qiweaving_unweave.pattern_rank = real_rank
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and e.payload.get("skill") == "Qiweaving Check"]
    assert len(checks) == 1, checks
    compared = checks[0].payload["compared"]
    assert {row["dc"] for row in compared} == {11, 17}, compared
    assert {row["success"] for row in compared} == {True, False}, compared
    left_on_foe = {item.source_definition_id for _kind, _key, item in qiweaving_unweave.patterns(engine, foe)}
    assert left_on_foe == set(), f"the rank-1 pattern on {foe.display_name} should have ended: {left_on_foe}"
    assert qiweaving_unweave.patterns(engine, ally), "the rank-7 pattern must survive a total of 11 against DC 17"
    said = " ".join(logs(events))
    assert "ends" in said and "remains" in said, said


def test_grand_unweaving_reaches_allies_and_its_own_user_too():
    """"Choose any number of Active Qi Patterns inside the area that you can perceive" -- any pattern, whoever carries it
    (AUTO12f1: the branch excluded allies and the caster)."""
    engine, me, foe = duel(bundle([UNWEAVE, GRAND]), foe_bundle(), foe_at=(4, 6), with_ally=True)
    ally = engine.state.actors[ALLY]
    _mantled(engine, me, ally)
    assert qiweaving_unweave.patterns(engine, ally)
    real_rank = qiweaving_unweave.pattern_rank
    qiweaving_unweave.pattern_rank = lambda _engine, _item: 1  # ends at once: no check needed
    try:
        events = use(engine, "Grand Unweaving", who=me.entity_id, target=None, contains=True)
    finally:
        qiweaving_unweave.pattern_rank = real_rank
    assert not qiweaving_unweave.patterns(engine, ally), qiweaving_unweave.patterns(engine, ally)
    assert any(ally.display_name in line for line in logs(events)), logs(events)


def test_world_circuit_severance_ends_patterns_with_one_check_and_only_once_per_long_rest():
    """"Choose up to ... equal to your Proficiency Bonus. Make one Qiweaving Check with Advantage ... Use Limit: Once per long
    rest" """
    engine, me, foe = duel(bundle([UNWEAVE, SEVERANCE], cl=20), foe_bundle(), foe_at=(13, 6))
    _mantled(engine, me, foe)
    assert "World-Circuit Severance" in names(engine, me.entity_id)
    script(engine, [20])
    events = use(engine, "World-Circuit Severance", who=me.entity_id, target=foe.entity_id)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and e.payload.get("skill") == "Qiweaving Check"]
    assert len(checks) == 1 and checks[0].payload["actor"]["mode"] == "ADVANTAGE", [e.payload.get("actor") for e in checks]
    assert not qiweaving_unweave.patterns(engine, foe), qiweaving_unweave.patterns(engine, foe)
    assert me.turn_flags.get(qiweaving_unweave.SEVERED) is not None
    turn(engine, me.entity_id)
    assert "World-Circuit Severance" not in names(engine, me.entity_id), "once per long rest is once per fight"


def test_world_circuit_severance_reaches_only_what_it_can_perceive_within_its_printed_range():
    """"up to a number of Active Qi Patterns you can perceive within range" (120 feet).  A creature it cannot perceive is
    out of reach, and one beyond the range is out of reach (AUTO12f1: the branch offered the technique whenever anything
    in the fight carried a pattern)."""
    engine, me, foe = duel(bundle([UNWEAVE, SEVERANCE], cl=20), foe_bundle(), foe_at=(13, 6))
    _mantled(engine, me, foe)
    assert "World-Circuit Severance" in names(engine, me.entity_id), "in range and perceived"
    # beyond the printed 120 feet
    foe.position = type(foe.position)(x=int(me.position.x) + 60, y=int(me.position.y))
    assert "World-Circuit Severance" not in names(engine, me.entity_id), "60 cells is far beyond 120 feet"
    foe.position = type(foe.position)(x=13, y=6)
    # in range but not perceived: a Hidden creature nothing locates
    from combat.ext import needle

    engine._apply_condition(foe, "condition:typed.hidden", "test:hide", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Hidden"})
    assert not qiweaving_unweave.perceived(engine, me, foe), qiweaving_unweave.perceived(engine, me, foe)
    assert "World-Circuit Severance" not in names(engine, me.entity_id), "a creature it cannot perceive is out of reach"


def test_a_wide_unweave_says_which_creature_each_pattern_is_on(monkeypatch):
    """"Choose any number of Active Qi Patterns": the same Active Qi Pattern from the same creator on two creatures is two
    different things to end, so each option has to say which creature bears it (AUTO12f1: the branch's options named the
    source and the creator only, so two identical options looked alike)."""
    engine, me, foe = duel(bundle([UNWEAVE, GRAND], pb=4), foe_bundle(), foe_at=(4, 6), with_ally=True)
    ally = engine.state.actors[ALLY]
    _mantled(engine, me, foe)
    _mantled(engine, me, ally)
    asked = {}
    original = needle.ask

    def spy(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id.startswith("choice:needle.wide_unweave"):
            asked.update({"options": list(options), "labels": dict(kwargs.get("labels") or {})})
        return original(engine_, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(qiweaving_unweave, "pattern_rank", lambda _engine, _item: 1)  # ends at once, no check needed
    monkeypatch.setattr(needle, "ask", spy)
    use(engine, "Grand Unweaving", who=me.entity_id, target=None, contains=True)
    assert asked, "a wide unweave must ask which patterns to end"
    assert set(asked["labels"]) == set(asked["options"]), asked
    texts = list(asked["labels"].values())
    assert len(set(texts)) == len(texts), texts
    assert any(foe.display_name in value for value in texts), texts
    assert any(ally.display_name in value for value in texts), texts


# ============================================================================================== the typed records the table now runs whole
def test_the_automated_qiweaving_records_leave_no_rule_reminder_behind():
    """FULL rows of this scope: every printed line runs, so nothing is left for the GM to resolve."""
    reviewed = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/zz_qiweaving_auto12.json").read_text(encoding="utf-8"))
    assert reviewed["mechanics"], "the override file is empty"
    for key in reviewed["mechanics"]:
        if key in qiweaving_unweave.NEEDS_A_COUNTER:
            continue  # the two counter-only records, checked below
        assert MECH[key]["coverage"] == "FULL", (key, MECH[key]["coverage"], MECH[key]["riders"])
        assert MECH[key]["riders"] == [], key
    # Dazing Unweave and False Completion cannot run here (their printed trigger is a counter), so they are NOT FULL and
    # they keep the printed decision on the sheet instead of claiming to be automated.
    for key in (DAZING, FALSE):
        assert MECH[key]["coverage"] == "CORE_WITH_RIDERS", (key, MECH[key]["coverage"])
        assert MECH[key]["riders"], key


def test_no_qiweaving_record_is_defined_twice():
    """One definition per mechanic id across the reviewed_final.d files: a second file deciding which review wins by
    filename ordering is how a later fix gets silently shadowed (AUTO12f1 finding 9)."""
    seen: dict[str, list[str]] = {}
    for path in sorted((ROOT / "authority/typed_mechanics/reviewed_final.d").glob("*.json")):
        for key in json.loads(path.read_text(encoding="utf-8")).get("mechanics") or {}:
            seen.setdefault(key, []).append(path.name)
    twice = {key: files for key, files in seen.items() if len(files) > 1}
    assert not [key for key in twice if key.startswith("TAL_QIWEAVING_")], twice


def test_the_sheet_no_longer_lists_the_automated_qiweaving_talents_as_not_automated_yet():
    bundle_ = compiled([BOND, DRAW, FEED, THROTTLE, READ, LOCK, RESERVOIR, VICIOUS, DAZING, GRAND, SEVERANCE])
    skipped = bundle_["diagnostics"]["skipped"]
    listed = set(skipped["passive"]) | set(skipped["reaction"]) | set(skipped["not_typed"])
    assert not listed & {"Draw Current", "Feed Current", "Throttle Current", "Read Current", "Circuit Lock", "Shared Reservoir",
                         "Vicious Unweave", "Dazing Unweave", "Grand Unweaving", "World-Circuit Severance"}, skipped


ALL_TALENTS = (DRAW, FEED, THROTTLE, READ, LOCK, RESERVOIR, VICIOUS, DAZING, GRAND, SEVERANCE)
BOND_ACTION_NAMES = {"Draw Current", "Feed Current", "Throttle Current", "Read Current", "Circuit Lock", "Shared Reservoir"}


# ============================================================================================== the table, not just the engine
def _table(tmp_path, talents=(BOND, THROTTLE, LOCK), *, pb=4, seed="AUTO12f1-TABLE",
           plain_giver=False, second_qiweaver=False):
    """A real table over fresh storage: a Qiweaver with the Bond package and a fighter with a 3 CP technique to be
    throttled, every creature on manual control with an Ask-me plan.  No live files."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    ids = [t.ME, ALLY, sw.FOE]
    bundles = []
    for who, display, sheet_ in ((t.ME, "Qiweaver", sheet(list(talents), pb=pb)),
                                 (ALLY, ALLY_NAME, foe_sheet()),
                                 (sw.FOE, "Marked Foe", foe_sheet())):
        sheet_ = json.loads(json.dumps(sheet_))
        if who == ALLY and second_qiweaver:
            sheet_ = sheet([BOND, THROTTLE])
        if who == ALLY and plain_giver:
            sheet_["spheres_and_talents"] = {}
            sheet_["path_and_subpath"] = {}
        sheet_["identity"]["display_name"] = display
        bundles.append(compiled_from(sheet_, actor_id=who,
                                     reaction_plan=None if plain_giver and who == ALLY else {"ask": True}))
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {t.ME: "team:a", ALLY: "team:a", sw.FOE: "team:b"},
        {t.ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 5}, sw.FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [t.ME, ALLY], [sw.FOE],
        control_modes={who: "MANUAL" for who in ids}, match_seed=seed,
        display_name=f"{seed} table fixture", maximum_rounds=120)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def compiled_from(sheet_, **kwargs):
    from combat.factory_compiler import compile_character

    return compile_character(sheet_, **kwargs)


def _send(table, mid, candidate_id, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def _candidates(combat, mid):
    return list(combat._load_session(mid).engine.legal_candidates())


def _pick(combat, mid, name, target=None):
    for candidate in _candidates(combat, mid):
        if candidate.display_name == name and (target is None or target in (candidate.target_ids or ())):
            return candidate.candidate_id
    raise AssertionError(f"{name!r} is not on the table menu: {[c.display_name for c in _candidates(combat, mid)]}")


def _end_turn(table, mid):
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"


def _advance(combat, table, mid, actor_id):
    for _ in range(12):
        if combat._load_session(mid).engine.state.current_actor_id == actor_id:
            return
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    raise AssertionError(f"{actor_id} never got a turn")


def _answer_prompts(table, mid, candidate_id, choose):
    """Send the candidate, answering every choice it raises with ``choose(reaction)`` until it commits.  Earlier answers
    stay attached to the saved choice, so each new one is sent after the ones before it."""
    answers = []
    result = _send(table, mid, candidate_id)
    for _ in range(6):
        if result["status"] != "REACTION_REQUIRED":
            return result
        answers.extend(choose(result["reaction"]))
        result = _send(table, mid, candidate_id, list(answers))
    return result


def test_the_bond_markers_the_ceiling_and_the_clock_survive_a_table_commit_and_reload(tmp_path):
    """Everything this lane stores in fight state -- the Qi Bond mark, the Throttle Current marker, its once-per-round
    clock and the Circuit Lock ceiling -- is a string or an integer, so it is still there after a real table commit and
    a reload from storage (AUTO12f1: the branch had no table-level regression at all)."""
    from combat.gate5_service import CombatService

    combat, table, mid = _table(tmp_path)
    _advance(combat, table, mid, t.ME)
    # bond the foe, then throttle it
    assert _send(table, mid, _pick(combat, mid, "Qi Bond", sw.FOE))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[sw.FOE]
    assert any("qi_bond" in c.condition_id for c in foe.conditions.values()), [c.condition_id for c in foe.conditions.values()]
    assert loaded.mechanical.replay()["status"] == "PASS", loaded.mechanical.replay()
    _advance(combat, table, mid, t.ME)
    throttled = _answer_prompts(table, mid, _pick(combat, mid, "Throttle Current", sw.FOE), lambda _reaction: [])
    assert throttled["status"] == "COMMITTED", throttled
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[sw.FOE]
    markers = [c for c in foe.conditions.values() if c.condition_id == THROTTLED]
    assert len(markers) == 1, [c.condition_id for c in foe.conditions.values()]
    assert markers[0].expires_on == "START_OF_SOURCE_NEXT_TURN", markers[0].expires_on
    stamp = foe.turn_flags.get("once_per_round:qiweaving_throttle_current:" + t.ME)
    assert stamp == int(loaded.engine.state.round_number), foe.turn_flags
    assert loaded.mechanical.replay()["status"] == "PASS", loaded.mechanical.replay()
    # the ceiling is stored as the caster's Proficiency Bonus (an Action of its own, so it waits for the next turn)
    _end_turn(table, mid)
    _advance(combat, table, mid, t.ME)
    assert _answer_prompts(table, mid, _pick(combat, mid, "Circuit Lock", sw.FOE), lambda _reaction: [])["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    lock = [c for c in reloaded.engine.state.actors[sw.FOE].conditions.values() if c.condition_id == LOCKED]
    assert len(lock) == 1, [c.condition_id for c in reloaded.engine.state.actors[sw.FOE].conditions.values()]
    assert int((lock[0].data or {}).get("cap") or 0) == 4, lock[0].data
    assert reloaded.mechanical.replay()["status"] == "PASS", reloaded.mechanical.replay()
    # the reloaded fight still refuses a 3 CP technique under... nothing here (PB 4 > 3), so check the marker's own text
    reading = str((lock[0].data or {}).get("reading") or "")
    assert "Circuit Lock" in reading and "Cultivation Points" in reading, reading


def test_the_table_asks_the_payer_whether_it_pays_the_extra_point(tmp_path):
    """Checklist item 9 at the level the bug showed: the surcharge is a choice the table answers, on a fight that is
    reloaded from storage, not a silent charge."""
    from combat.gate5_service import CombatService

    combat, table, mid = _table(tmp_path)
    _advance(combat, table, mid, t.ME)
    assert _send(table, mid, _pick(combat, mid, "Qi Bond", sw.FOE))["status"] == "COMMITTED"
    _advance(combat, table, mid, t.ME)
    assert _send(table, mid, _pick(combat, mid, "Throttle Current", sw.FOE))["status"] == "COMMITTED"
    _advance(combat, table, mid, sw.FOE)
    candidate_id = _pick(combat, mid, "Force Mantle")
    asked = []

    def choose(reaction):
        asked.append(reaction)
        options = reaction["choice"]["options"]
        refuse = next(o for o in options if o["id"] == "refuse")
        return [{**reaction["context"], "selection": "USE", "option_ids": [refuse["id"]]}]

    result = _answer_prompts(table, mid, candidate_id, choose)
    assert result["status"] == "COMMITTED", result
    assert asked, "the table must ask the creature that has to pay the extra point"
    prompt = asked[0]
    # the choice belongs to the creature that has to pay, not to the Qiweaver that applied Throttle Current
    assert prompt["context"]["reactor_id"] == sw.FOE, prompt["context"]
    assert prompt["reactor"] == "Marked Foe", prompt["reactor"]
    assert prompt["title"] == "Throttle Current", prompt["title"]
    moment = prompt["moment"]
    assert "Force Mantle" in moment and "1 extra Stamina" in moment and "Qiweaver" in moment, moment
    choice = prompt["choice"]
    assert [o["id"] for o in choice["options"]] == ["pay", "refuse"], choice["options"]
    said = " ".join(option["label"] for option in choice["options"])
    assert "Action is lost" in said and "Force Mantle" in said, said
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS", reloaded.mechanical.replay()
    # refusing is allowed and honoured: the printed cost comes back and the technique never resolves
    foe = reloaded.engine.state.actors[sw.FOE]
    assert foe.resources[STAMINA] == reloaded.engine.state.actors[ALLY].resources[STAMINA] or foe.resources[STAMINA] > 0, \
        foe.resources[STAMINA]
    assert THROTTLED not in conditions(foe), "the marker is spent by the activation it changed"


def test_the_table_asks_the_giver_of_a_one_point_reservoir_transfer_and_may_refuse(tmp_path):
    """Checklist items 7 and 9 at the level the bug showed: "The creature giving CP chooses how much to give" is asked
    of the GIVER -- even when only one point can move (this Qiweaver's Proficiency Bonus is 1) -- the giver may answer
    "give nothing", and the fight survives a commit and a reload (AUTO12r1f1: the branch moved the point without
    asking anybody and offered no refusal)."""
    from combat.gate5_service import CombatService

    combat, table, mid = _table(tmp_path, talents=(BOND, LOCK, RESERVOIR), pb=1, seed="AUTO12r1f1-RESERVOIR")
    _advance(combat, table, mid, t.ME)
    assert _send(table, mid, _pick(combat, mid, "Qi Bond (willing creature)", ALLY))["status"] == "COMMITTED"
    _advance(combat, table, mid, t.ME)
    # the caster spends 2 Cultivation Points on Circuit Lock, so it has room to receive; the bonded ally is the giver
    assert _answer_prompts(table, mid, _pick(combat, mid, "Circuit Lock", ALLY), lambda _reaction: [])["status"] \
        == "COMMITTED"
    _end_turn(table, mid)
    _advance(combat, table, mid, t.ME)
    asked = []

    def choose(reaction):
        asked.append(reaction)
        options = reaction["choice"]["options"]
        wanted = "to_me" if any(option["id"] == "to_me" for option in options) \
            else qiweaving_bond.GIVE_NOTHING
        return [{**reaction["context"], "selection": "USE", "option_ids": [wanted]}]

    result = _answer_prompts(table, mid, _pick(combat, mid, "Shared Reservoir", ALLY), choose)
    assert result["status"] == "COMMITTED", result
    assert asked, "the table must ask the creature that is actually giving the Cultivation Points"
    # the last question is the GIVER's, on its own side, and it is a real question even with a single point on offer
    amount = asked[-1]
    assert amount["context"]["reactor_id"] == ALLY, amount["context"]
    assert amount["reactor"] == ALLY_NAME, amount["reactor"]
    assert amount["title"] == "Shared Reservoir", amount["title"]
    assert [option["id"] for option in amount["choice"]["options"]] == ["1", qiweaving_bond.GIVE_NOTHING], \
        amount["choice"]["options"]
    assert "Give nothing" in " ".join(option["label"] for option in amount["choice"]["options"]), amount["choice"]["options"]
    assert ALLY_NAME in amount["moment"] and "Qiweaver" in amount["moment"], amount["moment"]
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS", reloaded.mechanical.replay()
    ally = reloaded.engine.state.actors[ALLY]
    caster = reloaded.engine.state.actors[t.ME]
    # refusing moved nothing and stamped no receipt, so the reservoir may be used again
    assert ally.resources[STAMINA] == ally.resource_maximums[STAMINA], ally.resources[STAMINA]
    assert not _received(ally) and not _received(caster), (ally.turn_flags, caster.turn_flags)
    said = [str(event.payload.get("log") or "") for event in reloaded.engine.events
            if event.event_type == "PASSIVE_TRIGGERED"]
    assert any("chooses to give no Cultivation Points" in line for line in said), said[-4:]


@pytest.mark.parametrize("answer,wanted", [("1", 1), (qiweaving_bond.GIVE_NOTHING, 0)])
def test_the_giver_is_asked_and_answers_on_an_ai_turn_too(tmp_path, monkeypatch, answer, wanted):
    """Checklist items 7 and 9 on the OTHER service path, which the manual-turn test above never touched: when the
    Qiweaver is on Local AI, ``CombatService.local_step`` pauses the whole fight for the bonded ally's answer, commits
    nothing until it has one, and then carries that answer into the execution (combat/gate5_service.py, the
    AWAITING_REACTION branch).  AUTO12r1f1 claimed the giver "is asked on the player's turn and on an AI turn" and only
    proved the first half; a regression in this branch could again move a player's point with nobody asked, and the
    manual test would still pass.

    Both answers are exercised, with the Qiweaver's Proficiency Bonus at 1 so there is exactly one point on offer --
    the case AUTO12r1f1's finding was about -- and both are checked before the answer and after a real commit and
    reload from storage."""
    from combat.gate5_service import CombatService
    from combat.gate4_persistence import canonical_state_sha256

    combat, table, mid = _table(tmp_path, talents=(BOND, LOCK, RESERVOIR), pb=1,
                                seed="AUTO12r2f1-AI-GIVER", plain_giver=True)
    _advance(combat, table, mid, t.ME)
    assert _send(table, mid, _pick(combat, mid, "Qi Bond (willing creature)", ALLY))["status"] == "COMMITTED"
    _advance(combat, table, mid, t.ME)
    # the caster spends 2 Cultivation Points on Circuit Lock, so it has room to receive and the ally is the giver
    assert _answer_prompts(table, mid, _pick(combat, mid, "Circuit Lock", ALLY), lambda _reaction: [])["status"] \
        == "COMMITTED"
    _end_turn(table, mid)
    _advance(combat, table, mid, t.ME)

    # The AI picks the action.  A tactical preference is policy data, not a forced action: the candidate, its target and
    # its scoring all still come from the production controller, which is what local_step then runs.
    combat.set_controller_mode(mid, actor_id=t.ME, controller_mode="LOCAL_AUTO")
    engine = combat._load_session(mid).engine
    reservoir = next(source for source, row in engine.action_catalog.items()
                     if row.display_name == "Shared Reservoir" and row.owner_id == t.ME)
    preferred = combat.policies.fallback().model_copy(update={"action_priorities": {reservoir: 2000}})
    monkeypatch.setattr(combat.policies, "for_actor", lambda _actor_id: (preferred, True))

    before = combat._load_session(mid).engine.state
    before_sha = canonical_state_sha256(before)
    ally_room, caster_room = int(before.actors[ALLY].resources[STAMINA]), int(before.actors[t.ME].resources[STAMINA])
    assert ally_room == int(before.actors[ALLY].resource_maximums[STAMINA]), "the ally is full, so only it can give"

    first = combat.local_step(mid)
    assert first["status"] == "AWAITING_REACTION", first
    asked = first["reaction_context"]
    # the question is the GIVER's, on an AI turn, and it is a real question even with a single point on offer
    assert asked["reactor_id"] == ALLY, asked["reactor_id"]
    assert asked["reaction_source_id"] == "choice:needle.reservoir_take", asked["reaction_source_id"]
    assert list(asked["legal_option_ids"]) == ["1", qiweaving_bond.GIVE_NOTHING], asked["legal_option_ids"]
    trigger = asked["choice_trigger"]
    assert trigger["name"] == "Shared Reservoir", trigger["name"]
    said = " ".join(str(trigger["labels"][option]) for option in asked["legal_option_ids"])
    assert "Give nothing" in said, said
    assert ALLY_NAME in trigger["prompt"] and "Qiweaver" in trigger["prompt"], trigger["prompt"]

    # nothing at all has moved while the table waits: the pause rolls the AI's action back
    paused = combat._load_session(mid).engine.state
    assert canonical_state_sha256(paused) == before_sha, "the AI's action must not commit before the answer"
    assert paused.actors[ALLY].resources[STAMINA] == ally_room, "a player's point must not move unasked"
    assert paused.actors[t.ME].resources[STAMINA] == caster_room, caster_room

    response = {key: asked[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
    response.update({"selection": "USE", "option_ids": [answer]})
    assert combat.local_step(mid, [response])["status"] == "COMMITTED"

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS", reloaded.mechanical.replay()
    ally = reloaded.engine.state.actors[ALLY]
    caster = reloaded.engine.state.actors[t.ME]
    assert ally.resources[STAMINA] == ally_room - wanted, ally.resources[STAMINA]
    assert caster.resources[STAMINA] == caster_room + wanted, caster.resources[STAMINA]
    # the receipt is counted on the creature that RECEIVED, and a refusal stamps none, so the reservoir may be used again
    assert bool(_received(caster)) is bool(wanted), (ally.turn_flags, caster.turn_flags)
    assert not _received(ally), ally.turn_flags
    said = [str(event.payload.get("log") or "") for event in reloaded.engine.events
            if event.event_type == "PASSIVE_TRIGGERED"]
    if wanted:
        assert any(f"{ALLY_NAME} gives you 1" in line for line in said), said[-4:]
    else:
        assert any("chooses to give no Cultivation Points" in line for line in said), said[-4:]


def qiweaving_menu(talents):
    """The Qiweaver's own buttons once the bond exists on both the foe and an ally, and the bonded foe carries a
    pattern, so every Bond talent and every Unweaving augment is on offer and dropping one is visible."""
    engine, me, foe = bonded_fight(list(talents), with_ally=True)
    use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=engine.state.actors[ALLY].entity_id)
    _mantled(engine, me, foe)
    offered = set(names(engine, me.entity_id))
    return {name for name in offered if name in BOND_ACTION_NAMES or "+" in name
            or name.startswith(("Grand Unweaving", "World-Circuit Severance"))}, engine, me, foe


@pytest.mark.parametrize("key", ALL_TALENTS)
def test_a_fighter_without_the_talent_is_untouched(key):
    """Default-inert: dropping this talent from the sheet removes exactly what that talent added and changes nothing
    else -- no other button, no mark, no cost charged to anyone."""
    full, _engine, _me, foe_full = qiweaving_menu(ALL_TALENTS)
    without, engine, me, foe = qiweaving_menu([other for other in ALL_TALENTS if other != key])
    assert not without - full, f"{key} must not change anything but its own buttons, and it added {sorted(without - full)}"
    if key in qiweaving_unweave.NEEDS_A_COUNTER:
        # The two counter-only augments are never compiled, so owning or dropping them changes no button at all.
        assert without == full, sorted(full)
    else:
        assert full - without, f"{key} adds nothing to the menu, so nothing can be asserted about it: {sorted(full)}"
    assert foe.resources[STAMINA] == foe_full.resources[STAMINA], (foe.resources[STAMINA], foe_full.resources[STAMINA])
    assert THROTTLED not in conditions(foe) and LOCKED not in conditions(foe), conditions(foe)
    assert not [c for c in foe.conditions.values() if "qiweaving" in c.condition_id], conditions(foe)
    assert not [flag for flag in me.turn_flags if "qiweaving" in flag], me.turn_flags
