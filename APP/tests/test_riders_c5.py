"""Rider lane C5 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones left"):
the printed lines of partly automated abilities that were only shown to the GM as riders, for Unmaking, Imbuement, Weather,
Sabers, Blood, Dreams and Harvesting & Gathering. Every ability is compiled on a real character and run through the engine.
C5_OLD=1 swaps in the base typing (2f68a85c); the typing tests then fail, and the plug-in tests fail on the base code.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c5.json (and entries edited in place in the other reviewed files);
plug-ins: combat/ext/unmaking_channels.py, combat/ext/unmaking_forms.py; combat/unmaking.py extended.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import combat.factory_compiler as compiler
from combat import unmaking

try:  # absent on the base code: those tests then fail instead of the whole module failing to collect
    from combat.ext import unmaking_channels
except ImportError:  # pragma: no cover
    unmaking_channels = None
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from tests import test_auto_lane4 as L4

t = L4.t
ROOT = Path(__file__).resolve().parents[1]
ME, AN = t.ME, t.AN
BASE = "2f68a85c"
UNMAKING = "tianxia.sphere.unmaking"
IRON_FIST = "tianxia.sphere.iron_fist"
STRAIN = unmaking.STRAIN
DAO = {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}
DART = {"item_id": "tianxia.mortal.weapon.fei_biao", "name": "Fei Biao", "quantity": 1}


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C5_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


def _authority():
    return json.loads(Path(compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


# ------------------------------------------------------------------------------------------------------------ harness
def _sheet(talents, items=(), spheres=(UNMAKING,), cl=10, dc=16):
    sheet = t._sheet(spheres[0], list(talents), {"starting_kit": {"items": list(items)}} if items else {}, cl=cl, dc=dc)
    mechanics = t._mechanics()
    for sphere in spheres[1:]:
        sheet["spheres_and_talents"]["sphere_record_ids"].append(sphere)
        sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] += [
            key for key, row in mechanics.items() if row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return sheet


def _fight(talents, items=(), spheres=(UNMAKING,), cl=10, dc=16, foe_hp=400, sure_hit=True):
    bundle = compile_character(_sheet(talents, items, spheres, cl, dc), actor_id=ME)
    engine = t._engine(bundle, foe_hp=foe_hp, sure_hit=sure_hit)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _use(engine, name, target=AN):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == ME
             and (target is None or not c.target_ids or target in c.target_ids)]
    assert found, f"{name!r} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates() if not c.display_name.startswith('Move')})}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]


def _legal(engine):
    t._ready(engine)
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == ME}


def _answers(engine, picks):
    """Immediate engine choice provider, not table pause/answer/commit/reload evidence.
    ``picks`` maps a choice id's last part ("unmaking_cost") to a function of the offered option ids
    returning the ones picked (None declines). Unlisted choices take the first option. Returns the requests seen."""
    requests = []

    def provider(request):
        if not str(request["reaction_source_id"]).startswith("choice:needle."):  # the foe's own reactions: not used
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None
        requests.append(request)
        options = list(request["legal_option_ids"])
        pick = picks.get(str(request["reaction_source_id"]).split(".")[-1])
        chosen = pick(options) if pick else options[:1]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or ())), None

    engine.set_reaction_provider(provider)
    return requests


def _kind(options, kind):
    return [next(option for option in options if option.split(":")[1] == kind)]


def _damage(events, suffix=None, target=AN):
    return sum(int(e.payload.get("hp_damage") or 0) + int(e.payload.get("temporary_hp_absorbed") or 0) for e in events
               if e.event_type == "DAMAGE_COMMITTED" and target in (e.target_ids or ()) and (suffix is None or str(e.source_definition_id).endswith(suffix)))


def _conditions(actor, prefix):
    return [c for c in actor.conditions.values() if c.condition_id.startswith(prefix)]


def _stance_damage(events, owner, target, source_suffix, name, count, sides, damage_type):
    """Check LOG1's automated notice and the actual attributed bonus packet."""
    notices = [e for e in events if e.event_type == "PASSIVE_TRIGGERED"
               and str(e.source_definition_id).endswith(source_suffix)]
    (notice,) = notices
    assert notice.actor_id == owner.entity_id and notice.target_ids == (target.entity_id,)
    assert notice.payload["text"] == (
        f"{owner.display_name}'s {name} adds +{count}d{sides} "
        f"{'Ruin' if damage_type == 'FORCE' else 'slashing'} damage to the hit on {target.display_name}.")
    packets = [e for e in events if e.payload.get("display_source_id") == notice.source_definition_id]
    (rolled,) = [e for e in packets if e.event_type == "DAMAGE_ROLLED"]
    (committed,) = [e for e in packets if e.event_type == "DAMAGE_COMMITTED"]
    critical = any(e.payload.get("critical") for e in events if e.event_type == "DAMAGE_ROLLED")
    assert rolled.payload["expression"] == f"{count * (2 if critical else 1)}d{sides}+0"
    assert len(rolled.payload["dice"]) == count * (2 if critical else 1)
    assert rolled.payload["total"] == sum(rolled.payload["dice"])
    assert committed.actor_id == owner.entity_id and committed.target_ids == (target.entity_id,)
    assert committed.payload["damage_type"] == damage_type
    assert committed.payload["rolled_or_pending_damage"] == rolled.payload["total"]
    assert committed.payload["hp_damage"] + committed.payload["temporary_hp_absorbed"] == rolled.payload["total"]


def _no_stance_damage(events, source_suffix):
    assert not [e for e in events if
                (e.event_type == "PASSIVE_TRIGGERED" and str(e.source_definition_id).endswith(source_suffix))
                or str(e.payload.get("display_source_id", "")).endswith(source_suffix)]


# ================================================================================================================ Unmaking
UNMAKING_FULL = ["TAL_UNMAKING_BITTER_RELEASE", "TAL_UNMAKING_BLACK_STAR_VESSEL", "TAL_UNMAKING_BLACK_VEIN_PALM", "TAL_UNMAKING_BLACK_VEIN_STEP",
                 "TAL_UNMAKING_CRACK_THE_NAME_OF_THE_TOOL", "TAL_UNMAKING_EXECUTION_THROUGH_THE_FAULT",
                 "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY", "TAL_UNMAKING_HOLLOW_THE_ARMOR", "TAL_UNMAKING_LAST_INCH_CONTROL", "TAL_UNMAKING_MERIDIAN_RUIN_SHOCK",
                 "TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_RUIN_SHEATH_METHOD", "TAL_UNMAKING_RUIN_WAVE", "TAL_UNMAKING_SECOND_RUIN_FORM_BLACK_PALM_VESSEL",
                 "TAL_UNMAKING_THIRD_RUIN_FORM_SEVERING_WAVE", "TAL_UNMAKING_UNBOUND_TRACE", "TAL_UNMAKING_WEAPON_PAYS_FIRST"]


def test_unmaking_lines_the_table_now_runs_are_no_longer_gm_riders():
    mechanics = _authority()
    # AUTO84 removed the old GM summaries for the executed strain, surge and healing lock.
    fourth = "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY"
    expected = {key: "FULL" for key in UNMAKING_FULL}
    assert {key: mechanics[key]["coverage"] for key in UNMAKING_FULL} == expected
    assert mechanics[fourth]["riders"] == []
    stance = next(e for e in mechanics[fourth]["effects"] if e["type"] == "stance")
    assert stance["rounds"] == 10
    assert stance["on_end"][0]["type"] == "healing_reduction"
    assert stance["on_end"][0]["duration"] == "until_end_of_your_next_turn"
    assert mechanics["TAL_UNMAKING_BLACK_TRACE"]["riders"] == []
    crack = next(o for o in mechanics["TAL_UNMAKING_BLACK_TRACE"]["options"] if o["label"] == "Crack")
    assert crack["effects"][0]["on_hit"][0]["bonus_if_kind"] == {"kinds": ["construct"], "formula": "pb"}
    assert mechanics["TAL_UNMAKING_WOUND_THAT_REFUSES"]["riders"] == []


def test_ruin_channel_on_a_weapon_cracks_it_and_the_ai_does_not_break_it():
    """"After the attack resolves, choose one cost: the Channel gains 1 Crack if it is an External Channel ..."; "An ordinary
    weapon ... can hold 2 Crack safely. At 3 Crack, it breaks". The table used to charge 1 Black Vein Strain whatever the Channel."""
    engine, me, foe = _fight([], items=[DAO])
    for count in (1, 2):
        _use(engine, "Ruin Channel", None)
        events = _use(engine, "Dao (Saber / Broadsword) attack")
        assert _damage(events, ".ruin_channel") > 0
        assert me.resources[STRAIN] == 0 and list(unmaking_channels.cracked_channels(me).values()) == [count]
    _use(engine, "Ruin Channel", None)
    events = _use(engine, "Dao (Saber / Broadsword) attack")
    assert _damage(events, ".cost", target=ME) > 0  # a third Crack would break it: the built-in AI pays 1d6 + PB instead
    assert list(unmaking_channels.cracked_channels(me).values()) == [2] and "Dao (Saber / Broadsword) attack" in _legal(engine)


def test_ruin_channel_third_crack_when_chosen_breaks_the_weapon_for_the_fight():
    engine, me, foe = _fight([], items=[DAO])
    _answers(engine, {"unmaking_cost": lambda options: _kind(options, "crack")})
    for _ in range(3):
        _use(engine, "Ruin Channel", None)
        _use(engine, "Dao (Saber / Broadsword) attack")
    assert _conditions(me, unmaking_channels.BROKEN) and not unmaking_channels.cracked_channels(me)
    assert "Dao (Saber / Broadsword) attack" not in _legal(engine)


def test_ruin_channel_player_may_pay_self_damage_instead_and_an_unarmed_strike_gives_strain():
    engine, me, foe = _fight([], items=[DAO])
    _answers(engine, {"unmaking_cost": lambda options: _kind(options, "self")})
    _use(engine, "Ruin Channel", None)
    events = _use(engine, "Dao (Saber / Broadsword) attack")
    assert _damage(events, ".cost", target=ME) >= 1 + 4 and not unmaking_channels.cracked_channels(me) and me.resources[STRAIN] == 0
    engine, me, foe = _fight([], spheres=(UNMAKING, IRON_FIST))
    _use(engine, "Ruin Channel", None)
    _use(engine, "Unarmed Strike (Iron Fist)")
    assert me.resources[STRAIN] == 1  # an Internal Channel


def test_a_ruin_channel_hit_can_overdraw():
    """Ruin Channel: "You may Overdraw when a Ruin Channel attack hits." The Overdraw toggle did nothing on a Channel hit."""
    engine, me, foe = _fight([], items=[DAO])
    _use(engine, "Overdraw: ready", None)
    _use(engine, "Ruin Channel", None)
    events = _use(engine, "Dao (Saber / Broadsword) attack")
    assert _damage(events, ".overdraw") > 0 and me.turn_flags.get("overdrawn")


def test_unbound_trace_asks_its_price_after_the_attack_even_on_a_miss():
    """"After the attack resolves, whether it hits or misses, choose one: gain 1 Black Vein Strain; take 1d6 + PB Ruin
    self-damage; one ... External Channel gains 1 Crack." Only the Strain was typed, and only on the option's own row."""
    engine, me, foe = _fight([], items=[DAO], sure_hit=False)
    foe.armor_class = 99
    requests = _answers(engine, {"unmaking_cost": lambda options: _kind(options, "crack")})
    _use(engine, "Black Trace: Sting, Unbound Trace")
    offered = requests[-1]["legal_option_ids"]
    assert [option.split(":")[1] for option in offered] == ["strain", "self", "crack"]
    assert list(unmaking_channels.cracked_channels(me).values()) == [1] and me.resources[STRAIN] == 0


def test_bitter_release_doubles_against_an_impaired_target():
    """"If the target is Bloodied, impaired, ... increase the added damage by twice your Proficiency Bonus": a target with 3 or
    more Black Vein Strain has an Impaired channel."""
    engine, me, foe = _fight(["TAL_UNMAKING_BITTER_RELEASE"])
    foe.resources[STRAIN], foe.resource_maximums[STRAIN] = 3, 6
    _use(engine, "Overdraw: ready", None)
    events = _use(engine, "Black Trace: Sting")
    overdraw_roll = next(r for r in engine.rolls if str(r.reason).startswith("OVERDRAW:"))
    assert _damage(events, ".overdraw") == overdraw_roll.total + 2 * 4


def test_black_star_vessel_backlash_is_suffered_its_ruin_ignores_resistance_and_a_second_backlash_ends_it():
    engine = L4._duel([], subject_sphere=UNMAKING, attacker_talents=["TAL_UNMAKING_BLACK_STAR_VESSEL"], attacker_sphere=UNMAKING, cl=15)
    me, foe = engine.state.actors[ME], engine.state.actors[L4.SUBJ]  # a Factory foe: its Resistance is the table's own
    foe.armor_class, foe.maximum_hp = -50, 400
    foe.current_hp = 400
    _use(engine, "Black Star Vessel: Arm", None)
    me.resources[STRAIN] = 5
    engine._gain_resource(me, STRAIN, 1, "test")
    assert me.resources[STRAIN] == 6 and _conditions(me, unmaking.BLACK_STAR_ACTIVE)
    assert any(str(r.reason).startswith("RUIN_BACKLASH") for r in engine.rolls)  # "the triggering Ruin Backlash" is suffered
    engine._add_modifier(foe, "test:resist", "damage_resistance", "ADD", "FORCE", "ALWAYS", expires_on="UNTIL_REMOVED")
    events = _use(engine, "Black Trace: Sting", L4.SUBJ)
    trace = next(e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith("TAL_UNMAKING_BLACK_TRACE#opt1"))
    assert trace.payload["reduced_to"] == trace.payload["rolled_or_pending_damage"]  # no Resistance halving
    me.current_hp = 5
    me.turns_started += 1  # the end of its next turn
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    assert not _conditions(me, unmaking.BLACK_STAR_ACTIVE)
    assert me.current_hp == 1 and me.resources[STRAIN] == 6  # the AI keeps 1 HP: Strain becomes 6, one level of Exhaustion
    assert any("exhaustion" in c.condition_id for c in me.conditions.values())


def test_black_vein_step_denies_opportunity_attacks_from_the_damaged_and_grants_an_unarmed_strike_for_a_strain():
    """"This movement does not provoke Opportunity Attacks from creatures damaged by that talent. If you end this movement
    adjacent to a creature damaged by the talent, you may gain 1 additional Black Vein Strain to make one unarmed strike"."""
    from combat import ext

    engine, me, foe = _fight(["TAL_UNMAKING_BLACK_VEIN_STEP"], cl=5)
    assert "Black-Vein Step: unarmed strike" not in _legal(engine)
    _use(engine, "Overdraw: ready", None)
    strain = me.resources[STRAIN]
    _use(engine, "Black Trace: Sting")
    assert ext.any_false("opportunity_allowed", engine, foe, me)  # the damaged foe cannot answer the free 10 feet
    # Spend the granted movement through actual engine candidates, ending adjacent again.
    for x, y in ((3, 5), (3, 6)):
        candidate = next(c for c in engine.legal_candidates() if c.destination is not None and c.destination.x == x
                         and c.destination.y == y and c.kind.value == "MOVE")
        engine.execute_intent(ActionIntent(intent_id=f"step-{x}-{y}", decision_id=candidate.decision_id,
                              candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                              actor_id=ME, destination=candidate.destination))
    assert not ext.any_false("opportunity_allowed", engine, foe, me)  # past the free 10 feet it can
    events = _use(engine, "Black-Vein Step: unarmed strike")
    assert me.resources[STRAIN] == strain + 2  # the Overdraw's, then the strike's
    assert any(e.event_type == "ATTACK_ROLLED" for e in events)
    assert "Black-Vein Step: unarmed strike" not in _legal(engine)  # once


def test_execution_through_the_fault_is_the_players_choice_over_a_normal_overdraw():
    engine, me, foe = _fight(["TAL_UNMAKING_EXECUTION_THROUGH_THE_FAULT"])
    foe.current_hp = 150  # Bloodied (of 400)
    requests = _answers(engine, {"execution": lambda options: ["overdraw"]})
    _use(engine, "Overdraw: ready", None)
    events = _use(engine, "Black Trace: Sting")
    assert requests and requests[0]["reaction_source_id"].endswith("execution")
    assert _damage(events, ".overdraw") > 0 and not _damage(events, ".execution_through_the_fault")
    engine, me, foe = _fight(["TAL_UNMAKING_EXECUTION_THROUGH_THE_FAULT"])
    foe.current_hp = 150
    _use(engine, "Overdraw: ready", None)
    events = _use(engine, "Black Trace: Sting")
    assert _damage(events, ".execution_through_the_fault") > 0  # the AI takes it


def test_last_inch_control_is_optional_for_a_player():
    engine, me, foe = _fight(["TAL_UNMAKING_LAST_INCH_CONTROL"], items=[DAO])
    _answers(engine, {"last_inch_control": lambda options: ["strain"], "unmaking_cost": lambda options: _kind(options, "strain")})
    _use(engine, "Black Trace: Sting, Unbound Trace")
    assert me.resources[STRAIN] == 1 and not [e for e in engine.events if e.event_type == "CHECK_ROLLED"]


def test_wound_that_refuses_lasts_until_the_end_of_your_next_turn_on_a_target_already_denied():
    engine, me, foe = _fight(["TAL_UNMAKING_WOUND_THAT_REFUSES"])
    _use(engine, "Black Trace: Sting")
    assert [m.expires_on for m in foe.modifiers.values() if m.source_definition_id == f"wound_that_refuses:{ME}"] == ["START_OF_SOURCE_NEXT_TURN"]
    engine, me, foe = _fight(["TAL_UNMAKING_WOUND_THAT_REFUSES"])
    _use(engine, "Black Trace: Fray")  # Fray's own denial lands first
    assert [m.expires_on for m in foe.modifiers.values() if m.source_definition_id == f"wound_that_refuses:{ME}"] == [
        f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"]


def _summoned(actor):
    actor.summon = {"owner": "actor:test.summoner", "group": "g", "source": "s", "status": "present", "concentration": False,
                    "commanded": False, "command": "free", "command_range_ft": 60}


def test_crack_the_name_of_the_tool_asks_its_price_and_a_success_still_costs_the_next_attack():
    engine, me, foe = _fight(["TAL_UNMAKING_CRACK_THE_NAME_OF_THE_TOOL"], dc=-40)
    _summoned(foe)
    requests = _answers(engine, {"unmaking_cost": lambda options: _kind(options, "self")})
    events = _use(engine, "Black Trace: Sting")
    assert [r["legal_option_ids"] for r in requests if r["reaction_source_id"].endswith("unmaking_cost")] == [["0:strain", "1:self"]]
    assert _damage(events, ".cost", target=ME) >= 2 and me.resources[STRAIN] == 0
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in foe.modifiers.values())  # the successful save


def test_shred_the_temporary_shape_adds_damage_to_a_summoned_creature_for_a_cp():
    engine, me, foe = _fight(["TAL_UNMAKING_SHRED_THE_TEMPORARY_SHAPE"], cl=5)
    _summoned(foe)
    qi = me.resources["resource:core.qi"] if "resource:core.qi" in me.resources else me.resources["resource:core.stamina"]
    events = _use(engine, "Black Trace: Sting")
    assert _damage(events, ".shred_the_temporary_shape") >= 3 + 4
    left = me.resources["resource:core.qi"] if "resource:core.qi" in me.resources else me.resources["resource:core.stamina"]
    assert left == qi - 1
    engine, me, foe = _fight(["TAL_UNMAKING_SHRED_THE_TEMPORARY_SHAPE"], cl=5)
    assert not _damage(_use(engine, "Black Trace: Sting"), ".shred_the_temporary_shape")  # not a summoned creature


def test_meridian_ruin_shock_on_an_internal_channel_hit():
    engine, me, foe = _fight(["TAL_UNMAKING_MERIDIAN_RUIN_SHOCK"], spheres=(UNMAKING, IRON_FIST), dc=50)
    _use(engine, "Ruin Channel", None)
    _use(engine, "Unarmed Strike (Iron Fist)")
    held = {c.condition_id for c in foe.conditions.values()}
    assert {"condition:typed.no_cp_regain", "condition:typed.reaction_denied", "condition:typed.concentration_mode"} <= held
    assert me.resources[STRAIN] == 2  # the Channel's own, then Meridian Ruin Shock's


def test_ruin_needle_rides_a_dart_hit_and_cracks_the_dart():
    engine, me, foe = _fight(["TAL_UNMAKING_RUIN_NEEDLE"], items=[DART])
    _answers(engine, {"ruin_needle": lambda options: ["cp"], "unmaking_cost": lambda options: _kind(options, "self")})
    _use(engine, "Ruin Channel", None)
    _use(engine, "Fei Biao (Flying Dart) attack")
    assert any(c.condition_id == "condition:typed.no_cp_regain" for c in foe.conditions.values())
    assert list(unmaking_channels.cracked_channels(me).values()) == [1]  # the needle's own Crack (its price was paid in HP)


def test_ruin_sheath_method_keeps_the_channel_a_turn_longer_and_offers_crack_or_strain_when_it_fizzles():
    engine, me, foe = _fight(["TAL_UNMAKING_RUIN_SHEATH_METHOD"], items=[DAO])
    _use(engine, "Ruin Channel", None)
    (charge,) = _conditions(me, unmaking.CHANNEL)
    assert charge.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}"
    _answers(engine, {"unmaking_cost": lambda options: _kind(options, "strain")})
    L4._new_turn(engine, ME)  # the start of its next turn: an ordinary Ruin Channel ends here
    assert _conditions(me, unmaking.CHANNEL)
    hp = me.current_hp
    _use(engine, "End turn", None)  # the end of its next turn: it fizzles, and the player picks the Strain
    assert not _conditions(me, unmaking.CHANNEL) and me.resources[STRAIN] == 1 and me.current_hp == hp


def test_weapon_pays_first_takes_twice_pb_instead_of_a_crack_once_per_turn():
    engine, me, foe = _fight(["TAL_UNMAKING_WEAPON_PAYS_FIRST"], items=[DAO])
    _answers(engine, {"weapon_pays_first": lambda options: ["pay"]})
    _use(engine, "Ruin Channel", None)
    events = _use(engine, "Dao (Saber / Broadsword) attack")
    assert _damage(events, ".weapon_pays_first", target=ME) == 8 and not unmaking_channels.cracked_channels(me)


def test_devouring_dregs_can_remove_a_crack_from_the_weapon_used():
    engine, me, foe = _fight(["TAL_UNMAKING_DEVOURING_DREGS"], items=[DAO], cl=5)
    _answers(engine, {"devouring_dregs": lambda options: ["crack"], "unmaking_cost": lambda options: _kind(options, "crack")})
    _use(engine, "Ruin Channel", None)
    _use(engine, "Dao (Saber / Broadsword) attack")
    assert list(unmaking_channels.cracked_channels(me).values()) == [1]
    me.resources[STRAIN] = 1
    foe.current_hp = 1
    _use(engine, "Overdraw: ready", None)
    _use(engine, "Ruin Channel", None)
    _use(engine, "Dao (Saber / Broadsword) attack")
    assert not foe.active and me.resources[STRAIN] >= 1  # the Crack was removed instead of the Strain


def _aim(engine, name, cell, actor_id=ME):
    t._ready(engine)
    for candidate in engine.legal_candidates():
        label = getattr(engine.action_catalog.get(candidate.source_definition_id), "display_name", "")
        if label == name and candidate.actor_id == actor_id and candidate.destination and (candidate.destination.x, candidate.destination.y) == cell:
            before = len(engine.events)
            engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                               candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                               target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
            return engine.events[before:]
    raise AssertionError(f"{name!r} at {cell} is not legal")


def test_ruin_wave_price_is_paid_once_after_it_resolves_even_when_every_creature_saves():
    """"After resolving the technique, choose one: gain 1 Black Vein Strain; take 2d6 + PB; one External Channel gains 1 Crack."
    The Strain was typed inside the failed-save branch: once per creature that failed, and never when all saved."""
    engine, me, foe = _fight(["TAL_UNMAKING_RUIN_WAVE"], items=[DAO], cl=5, dc=-40)
    requests = _answers(engine, {})
    _aim(engine, "Ruin Wave", (8, 6))
    offered = [r["legal_option_ids"] for r in requests if r["reaction_source_id"].endswith("unmaking_cost")]
    assert len(offered) == 1 and [o.split(":")[1] for o in offered[0]] == ["strain", "self", "crack"]
    assert me.resources[STRAIN] == 1


def test_ruin_wave_overdraws_only_a_creature_that_failed_its_save():
    engine, me, foe = _fight(["TAL_UNMAKING_RUIN_WAVE"], cl=5, dc=-40)
    _use(engine, "Overdraw: ready", None)
    events = _aim(engine, "Ruin Wave", (8, 6))
    assert not _damage(events, ".overdraw")  # it saved
    engine, me, foe = _fight(["TAL_UNMAKING_RUIN_WAVE"], cl=5, dc=50)
    _use(engine, "Overdraw: ready", None)
    assert _damage(_aim(engine, "Ruin Wave", (8, 6)), ".overdraw") > 0


def test_severing_wave_denies_cp_overdraws_every_failed_target_then_backlash():
    engine, me, foe = _fight(["TAL_UNMAKING_THIRD_RUIN_FORM_SEVERING_WAVE"], cl=10, dc=50)
    _use(engine, "Overdraw: ready", None)
    events = _aim(engine, "Third Ruin Form: Severing Wave", (8, 6))
    assert any(c.condition_id == "condition:typed.no_cp_regain" for c in foe.conditions.values())
    assert _damage(events, ".overdraw") > 0
    assert sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH")) >= 1


def test_star_sundering_cut_adds_8d10_to_a_summoned_creature_and_destroys_the_channel():
    engine, me, foe = _fight(["TAL_UNMAKING_SIXTH_RUIN_FORM_STAR_SUNDERING_CUT"], items=[DAO], cl=15, dc=50)
    # Owner 2026-10-01 friendly fire (LUNA27): the cutter stands in its own
    # "Each creature in the line" and takes 16d10 too. Keep it standing so the
    # printed after-cut costs (the broken channel) still apply to it.
    me.maximum_hp = me.current_hp = 400
    _summoned(foe)
    events = _aim(engine, "Sixth Ruin Form: Star-Sundering Cut", (8, 6))
    assert any(r.reason.startswith("DAMAGE") and "8d10" in str(r.expression) for r in engine.rolls)
    assert _damage(events) > 0
    assert any(c.condition_id == "condition:typed.no_cp_regain" for c in foe.conditions.values())
    assert _conditions(me, unmaking_channels.BROKEN) and "Dao (Saber / Broadsword) attack" not in _legal(engine)


def test_unbody_the_false_vessel_targets_only_summoned_creatures_and_strikes_the_sustainer():
    from tests import test_auto_lane1 as L1

    bundle = compile_character(_sheet(["TAL_UNMAKING_UNBODY_THE_FALSE_VESSEL"], cl=15, dc=50), actor_id=L1.ME)
    engine = L1._engine(bundle, allies=(L1._ally_bundle(),))
    me, foe, ally = engine.state.actors[L1.ME], engine.state.actors[AN], engine.state.actors[L1.ALLY]
    foe.maximum_hp = 400
    foe.current_hp = 400
    assert "Unbody the False Vessel" not in {c.display_name for c in engine.legal_candidates() if c.actor_id == L1.ME}
    _summoned(foe)
    foe.summon = {**foe.summon, "owner": L1.ALLY}  # its sustainer: visible, within 120 feet
    hp = ally.current_hp
    events = L1._use(engine, "Unbody the False Vessel", AN)
    assert _damage(events, target=AN) > 0 and me.resources[STRAIN] == 2  # the AI's price: 2 Black Vein Strain
    assert ally.current_hp < hp  # Proficiency Bonus d10 to the sustaining creature


def test_the_moment_nothing_answers_sets_strain_suffers_two_backlashes_and_locks_out_other_unmaking():
    engine, me, foe = _fight(["tianxia.talent.unmaking.the_moment_nothing_answers", "TAL_UNMAKING_RUIN_WAVE"], cl=17, dc=50)
    me.resources["resource:core.qi"] = me.resource_maximums["resource:core.qi"] = 30
    _use(engine, "The Moment Nothing Answers")
    assert me.resources[STRAIN] == 6
    assert sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH")) == 2
    legal = _legal(engine)
    assert "Black Trace: Sting" in legal and not {name for name in legal if name.startswith("Ruin Wave") or name == "Ruin Channel"}


def test_hollowing_field_upkeep_at_the_end_of_each_turn_and_backlash_when_damage_breaks_it():
    engine, me, foe = _fight(["TAL_UNMAKING_HOLLOWING_FIELD"], cl=10)
    _answers(engine, {"unmaking_cost": lambda options: _kind(options, "strain")})
    _aim(engine, "Hollowing Field", (10, 6))
    assert me.concentration is not None
    _use(engine, "End turn", None)
    assert me.resources[STRAIN] == 1
    before = sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH"))
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH")) == before + 1


def test_domain_of_collapse_healing_lock_concentration_save_upkeep_and_double_backlash():
    engine, me, foe = _fight(["TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE"], cl=15, dc=50)
    requests = _answers(engine, {"unmaking_cost": lambda options: [o for o in options if o.endswith(":max_hp_loss")]})
    _use(engine, "Fifth Ruin Form: Domain of Collapse", None)
    assert me.concentration is not None
    _use(engine, "Black Trace: Sting")
    assert any(m.target_field == "healing_reduction" and m.expires_on == "END_OF_CURRENT_TURN" for m in foe.modifiers.values())
    _use(engine, "End turn", None)
    offered = [r["legal_option_ids"] for r in requests if r["reaction_source_id"].endswith("unmaking_cost")]
    assert [o.split(":")[1] for o in offered[-1]] == ["strain", "self", "max_hp_loss"]  # no weapon to destroy
    assert any(int(c.data.get("lost") or 0) == 10 for c in me.conditions.values())
    before = sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH"))
    engine._end_concentration(me, "FAILED_DAMAGE_CHECK")
    assert sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH")) == before + 2


def test_domain_of_collapse_makes_a_hostile_starting_concentration_inside_save():
    from combat.ext import unmaking_forms

    engine, me, foe = _fight(["TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE"], cl=15, dc=50)
    _use(engine, "Fifth Ruin Form: Domain of Collapse", None)
    focus = next(action for action in engine.action_catalog.values() if action.owner_id == ME)
    concentrating = focus.model_copy(update={"parameters": {**focus.parameters, "typed": {"duration": {"concentration": True}}}})
    hp = foe.current_hp
    unmaking_forms.domain_concentration_save(engine, foe, concentrating)
    assert foe.current_hp < hp


def test_fourth_ruin_form_strain_each_turn_surge_after_backlash_retaliation_and_no_healing_when_it_ends():
    engine = L4._duel([], subject_sphere=UNMAKING, subject_kit={"starting_kit": {"items": [DAO]}},
                      attacker_talents=["TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY"], attacker_sphere=UNMAKING,
                      attacker_kit={"starting_kit": {"items": [DAO]}}, cl=10)
    me, foe = engine.state.actors[ME], engine.state.actors[L4.SUBJ]
    foe.armor_class, foe.maximum_hp = -50, 400
    foe.current_hp = 400
    _use(engine, "Fourth Ruin Form: Black-Vein Body", None)
    events = _use(engine, "Dao (Saber / Broadsword) attack", L4.SUBJ)
    # LOG1 (round22 merge 13) reports automated stance damage as PASSIVE_TRIGGERED,
    # not a GM instruction, and attributes the bonus packet to the owning form.
    source = "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY"
    _stance_damage(events, me, foe, source, "Fourth Ruin Form", 3, 10, "FORCE")
    _no_stance_damage(_use(engine, "Dao (Saber / Broadsword) attack", L4.SUBJ), source)
    _use(engine, "End turn", None)
    assert me.resources[STRAIN] == 1  # "At the end of each of your turns, gain 1 Black Vein Strain"
    me.resources[STRAIN] = 6
    unmaking.after_strain_gained(engine, me, "test")
    from combat import stances

    assert any((c.data or {}).get("surge") for c in stances.active(me))
    # a creature that hits the form with a melee attack takes PB Ruin damage
    L4._new_turn(engine, L4.SUBJ)
    me.armor_class = -50
    foe_side = next(c for c in engine.legal_candidates() if c.actor_id == L4.SUBJ and c.display_name.endswith(" attack") and ME in (c.target_ids or ()))
    hp = foe.current_hp
    engine.execute_intent(ActionIntent(intent_id="retaliate", decision_id=foe_side.decision_id, candidate_id=foe_side.candidate_id,
                                       state_version=foe_side.state_version, actor_id=L4.SUBJ, target_ids=foe_side.target_ids))
    assert foe.current_hp <= hp - 4
    L4._new_turn(engine, ME)
    # The printed backlash upgrade is real 4d10 damage, once on this new turn.
    events = _use(engine, "Dao (Saber / Broadsword) attack", L4.SUBJ)
    # LOG1's notice retains the base rider label; the packet carries surged dice.
    (surge_roll,) = [e for e in events if e.event_type == "DAMAGE_ROLLED"
                    and str(e.payload.get("display_source_id", "")).endswith(source)]
    critical = any(e.payload.get("critical") for e in events if e.event_type == "DAMAGE_ROLLED")
    assert surge_roll.payload["expression"] == f"{8 if critical else 4}d10+0"
    (surge_damage,) = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
                      and str(e.payload.get("display_source_id", "")).endswith(source)]
    assert surge_damage.payload["damage_type"] == "FORCE"
    assert surge_damage.payload["hp_damage"] == surge_roll.payload["total"]
    _no_stance_damage(_use(engine, "Dao (Saber / Broadsword) attack", L4.SUBJ), source)
    (form,) = stances.active(me)
    me.turns_started = int(form.expires_on.split(":")[1])
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    assert not stances.active(me)
    assert any(m.target_field == "healing_reduction" for m in me.modifiers.values())  # "When the form ends, you cannot regain HP"


def test_second_ruin_form_unarmed_strikes_may_deal_ruin_and_a_backlash_locks_healing_until_it_ends():
    from combat import ext, stances

    engine, me, foe = _fight(["TAL_UNMAKING_SECOND_RUIN_FORM_BLACK_PALM_VESSEL"], spheres=(UNMAKING, IRON_FIST), cl=5)
    _use(engine, "Second Ruin Form: Black Palm Vessel", None)
    strike = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Unarmed Strike (Iron Fist)")
    from combat.typed_executor import Context

    ctx = Context(engine, me, strike, None, dict(strike.parameters["typed"]), [foe], foe, {})
    assert ext.run("attack_damage_types", ctx, {"attack_kind": "unarmed"}, ["BLUDGEONING"]) == [["BLUDGEONING", "FORCE"]]
    me.resources[STRAIN] = 6
    unmaking.after_strain_gained(engine, me, "test")
    (form,) = stances.active(me)
    assert any(m.target_field == "healing_reduction" and m.expires_on == form.expires_on for m in me.modifiers.values())


def _object_fight(talents, items=(), cl=10, dc=16, objects=None):
    from tests import test_sysv2_objects as O

    bundle = compile_character(_sheet(talents, items, cl=cl, dc=dc), actor_id=O.ME)
    engine = O.fight(bundle, objects=objects or [{"id": 1, "kind": "door", "x": 4, "y": 6}], foe=(14, 6))
    return O, engine, engine.state.actors[O.ME]


def test_dissolve_the_seam_checks_against_the_objects_dc_and_deals_8d10_or_half_with_a_price():
    O, engine, me = _object_fight(["TAL_UNMAKING_DISSOLVE_THE_SEAM"], cl=5)
    assert not [c for c in engine.legal_candidates() if c.display_name == "Dissolve the Seam" and AN in (c.target_ids or ())]
    O.force_d20(engine, 20, 20)
    events = O.use(engine, "Dissolve the Seam", "object:map.1")
    check = next(e for e in events if e.event_type == "CHECK_ROLLED")
    assert check.payload["dc"] == 13 and check.payload["success"] is True and check.payload["skill"] == "Unmaking Check"  # an ordinary object
    assert O.lost(engine, "object:map.1", events) > 0
    O, engine, me = _object_fight(["TAL_UNMAKING_DISSOLVE_THE_SEAM"], cl=5)
    O.force_d20(engine, 1, 1)
    events = O.use(engine, "Dissolve the Seam", "object:map.1")
    assert next(e for e in events if e.event_type == "CHECK_ROLLED").payload["success"] is False
    assert me.resources[STRAIN] == 1  # no weapon to Crack: the Strain


def test_black_trace_at_an_object_adds_the_crack_bonus_and_unbound_still_asks_its_price():
    O, engine, me = _object_fight([], items=[DAO])
    O.force_d20(engine, 15, 15)
    events = O.use(engine, "Black Trace: Sting, Unbound Trace", "object:map.1")
    assert O.lost(engine, "object:map.1", events) > 0
    assert me.resources[STRAIN] == 1 or unmaking_channels.cracked_channels(me) or _damage(events, ".cost", target=O.ME)


def test_crack_on_a_weapon_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    bundle = compile_character(_sheet([], items=[DAO]), actor_id=ME)
    session = persistence.create_match(match_seed="C5-CRACK", typed_bundles=(bundle,),
                                       roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    _answers(session.engine, {"unmaking_cost": lambda options: _kind(options, "crack")})
    c = next(c for c in session.engine.legal_candidates() if c.display_name == "Black Trace: Sting, Unbound Trace")
    session.submit_intent(ActionIntent(intent_id="trace", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=ME, target_ids=c.target_ids), primary_decision_record=None,
                          reaction_provider=session.engine._gate4_reaction_provider)
    assert unmaking_channels.cracked_channels(session.engine.state.actors[ME])
    loaded = persistence.load_match(session.match_id)
    me = loaded.engine.state.actors[ME]
    (crack,) = _conditions(me, unmaking_channels.CRACK)
    assert crack.data["count"] == 1 and isinstance(crack.data["weapon"], str)
    assert unmaking_channels.cracked_channels(me) == unmaking_channels.cracked_channels(session.engine.state.actors[ME])


def test_sever_the_mountains_memory_targets_an_object_only_and_backlashes_on_a_failure():
    O, engine, me = _object_fight(["TAL_UNMAKING_SEVER_THE_MOUNTAIN_S_MEMORY"], cl=15)
    offered = [c for c in engine.legal_candidates() if c.display_name == "Sever the Mountain’s Memory"]
    assert offered and all((c.metadata or {}).get("object_target") for c in offered)
    O.force_d20(engine, 1, 1)
    events = O.use(engine, "Sever the Mountain’s Memory", "object:map.1")
    assert O.lost(engine, "object:map.1", events) > 0  # half damage
    assert sum(1 for r in engine.rolls if str(r.reason).startswith("RUIN_BACKLASH")) == 1


# ================================================================================================================ Imbuement
IMB = "tianxia.talent.imbuement."


def _imbuer(talents, cl=10, dc=16, ally_items=()):
    """ME (an Imbuement cultivator with ``talents``) beside an ally (who may carry ``ally_items``) and the foe."""
    from tests import test_auto_lane1 as L1

    sheet = L1._sheet(IMB + talents[0], cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [IMB + name for name in talents]
    bundle = compile_character(sheet, actor_id=L1.ME)
    ally_sheet = t._sheet(None, [], {"starting_kit": {"items": list(ally_items)}} if ally_items else {})
    ally = compile_character(ally_sheet, actor_id=L1.ALLY)
    engine = L1._engine(bundle, allies=(ally,))
    return L1, engine, engine.state.actors[L1.ME], engine.state.actors[L1.ALLY], engine.state.actors[AN]


def _cast_as(L1, engine, name, target):
    L1._ready(engine)
    found = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == L1.ME
             and (target is None or tuple(c.target_ids or ()) == (target,))]
    assert found, f"{name!r} on {target} is not legal"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=L1.ME,
                                       target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]


def _cast_paying(L1, engine, name, target):
    """``_cast_as``, with the player confirming the first alternative payment offered (Crimson Sacrifice: lock round 7's
    payment_substitution asks before paying HP). Test-only answer for that one choice; other questions get no answer."""
    from combat.gate2_runtime_models import ReactionDecision

    def provider(request):
        if request.get("reaction_source_id") != "choice:alternative_payment":
            return None, None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=tuple(request["legal_option_ids"][:1])), None

    had = getattr(engine, "_gate4_reaction_provider", None)
    engine._gate4_reaction_provider = provider
    try:
        return _cast_as(L1, engine, name, target)
    finally:
        engine._gate4_reaction_provider = had


def test_imbuement_each_known_option_is_its_own_mandate_not_every_talent_at_once():
    """"Choose one Imbue talent you know and apply its listed effect": the compiler merged every talent's effects into one
    Place Mandate (and the Fray options into one Fray Mandate, whatever the save)."""
    L1, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "quicken_and_slow"])
    names = {c.display_name for c in engine.legal_candidates() if c.actor_id == L1.ME}
    assert {"Place Mandate: Clarify", "Place Mandate: Quicken", "Fray Mandate: Cloud", "Fray Mandate: Slow"} <= names
    assert "Place Mandate" not in names and "Fray Mandate" not in names
    speed = ally.movement_remaining_ft
    _cast_as(L1, engine, "Place Mandate: Quicken", L1.ALLY)
    assert any(m.target_field.startswith("speed") and int(m.value) == 15 for m in ally.modifiers.values() if str(m.value).lstrip("-").isdigit())
    assert not any(c.condition_id == "condition:typed.check_mode" for c in ally.conditions.values())  # Clarify did not ride along
    del speed


def test_fray_mandate_needs_a_failed_wisdom_save_and_a_repeat_save_ends_it():
    L1, engine, me, ally, foe = _imbuer(["quicken_and_slow"], dc=-40)
    _cast_as(L1, engine, "Fray Mandate: Slow", AN)
    assert not any(m.source_definition_id.endswith("mandate.fray.slow") for m in foe.modifiers.values())  # it saved
    L1, engine, me, ally, foe = _imbuer(["quicken_and_slow"], dc=50)
    _cast_as(L1, engine, "Fray Mandate: Slow", AN)
    slowed = [m for m in foe.modifiers.values() if m.source_definition_id.endswith("mandate.fray.slow")]
    assert slowed and any(c.condition_id == "condition:typed.fray_mandate" for c in foe.conditions.values())
    for condition in foe.conditions.values():
        if condition.condition_id == "condition:typed.fray_mandate":
            condition.data["repeat_save"]["dc"] = -40  # the next repeat save succeeds
    L4._new_turn(engine, AN)
    engine._expire_typed_for_checkpoint("END_OF_TURN", AN)
    from combat import ext

    ext.run("turn_end", engine, foe)
    assert not any(m.source_definition_id.endswith("mandate.fray.slow") for m in foe.modifiers.values())


def test_mandate_load_ends_the_oldest_mandate_unless_layered():
    L1, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "quicken_and_slow"])
    _cast_as(L1, engine, "Place Mandate: Quicken", L1.ALLY)
    _cast_as(L1, engine, "Place Mandate: Clarify", L1.ALLY)
    assert not any(m.source_definition_id.endswith("mandate.imbue.quicken") for m in ally.modifiers.values())
    L1, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "quicken_and_slow", "layered_mandate"])
    _cast_as(L1, engine, "Place Mandate: Quicken", L1.ALLY)
    _cast_as(L1, engine, "Place Mandate: Clarify", L1.ALLY)
    assert any(m.source_definition_id.endswith("mandate.imbue.quicken") for m in ally.modifiers.values())


def test_clarify_asks_which_ability_and_fortify_picks_the_weakest_save_for_the_ai():
    L1, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "fortify_and_expose", "layered_mandate"])
    _answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    _cast_as(L1, engine, "Place Mandate: Clarify", L1.ALLY)
    from combat.typed_executor import check_mode

    assert check_mode(ally, "WIS") == "ADVANTAGE" and check_mode(ally, "INT") == "NORMAL"
    engine.set_reaction_provider(None) if hasattr(engine, "set_reaction_provider") else None
    L1b, engine, me, ally, foe = _imbuer(["fortify_and_expose"])
    ally.saving_throws["CHA"] = -5
    _cast_as(L1b, engine, "Place Mandate: Fortify", L1b.ALLY)
    bonus = [c for c in ally.conditions.values() if c.condition_id == "condition:typed.save_bonus"]
    assert bonus and bonus[0].data["rule"]["save_bonus"]["abilities"] == ["CHA"]


def test_weapon_mandates_ride_the_chosen_weapons_attacks():
    """Sharpen: "once per turn, the Vessel deals extra damage equal to your Proficiency Bonus"; Temper: "+half your PB to attack and
    damage rolls"; Elemental Mantle: "once per turn ... an extra 1d6 damage of the chosen type (2d6 at CL 5)".

    Sharpen is printed as "Choose one:" of three effects, so the extra damage is asked for rather than always on (AUTO20
    2026-10-04: the printed "Choose one" became a `mandate_choice`; this test picks the Proficiency Bonus damage explicitly).
    """
    from combat import ext
    from combat.typed_executor import Context

    L1, engine, me, ally, foe = _imbuer(["sharpen_and_dull", "tempered_equipment", "elemental_mantle", "layered_mandate", "qi_written_mandate"],
                                        ally_items=[DAO])
    weapon = next(a for a in engine.action_catalog.values() if a.owner_id == L1.ALLY and a.display_name == "Dao (Saber / Broadsword) attack")
    # The printed Mandates also permit natural weapons and unarmed strikes.
    # Choose the Dao explicitly rather than relying on the default sort order.
    _answers(engine, {"mandate_vessel": lambda options: [weapon.source_definition_id],
                      "mandate_choice": lambda options: ["damage"] if "damage" in options else options[:1]})
    for name in ("Place Mandate: Sharpen", "Place Mandate: Temper (weapon)", "Place Mandate: Elemental Mantle"):
        _cast_as(L1, engine, name, L1.ALLY)
    from combat.ext.imbuement_mandates import VESSEL
    assert {c.data['weapon'] for c in ally.conditions.values() if c.condition_id == VESSEL} == {weapon.source_definition_id}
    ctx = Context(engine, ally, weapon, None, dict(weapon.parameters["typed"]), [foe], foe, {})
    assert sum(ext.run("attack_bonus", ctx, ally)) == 2
    assert sum(v for v in ext.run("attack_damage_bonus", ctx, foe, {}) if v) == 4 + 2  # Sharpen's PB once, Temper's half PB
    assert sum(v for v in ext.run("attack_damage_bonus", ctx, foe, {}) if v) == 2  # Sharpen only once per turn
    hp = foe.current_hp
    ext.run("after_hit", ctx, foe, "weapon")
    assert foe.current_hp < hp and any(str(r.reason).endswith(":vessel") for r in engine.rolls)


def test_lagging_reflex_still_tongue_and_seal_sense():
    L1, engine, me, ally, foe = _imbuer(["reflex_edict", "suppress_function", "layered_mandate", "qi_written_mandate"], dc=50)
    _cast_as(L1, engine, "Fray Mandate: Lagging Reflex", AN)
    _cast_as(L1, engine, "Fray Mandate: Still Tongue", AN)
    _answers(engine, {"mandate_choice": lambda options: ["deafened"]})
    _cast_as(L1, engine, "Fray Mandate: Seal Sense", AN)
    held = {c.condition_id for c in foe.conditions.values()}
    assert {"condition:typed.no_opportunity_attacks", "condition:typed.silenced", "condition:typed.deafened"} <= held


def test_harden_armor_grants_temporary_hp_each_turn_and_burden_slows():
    L1, engine, me, ally, foe = _imbuer(["harden_and_brittle", "lighten_and_burden", "layered_mandate"], dc=50)
    _cast_as(L1, engine, "Place Mandate: Harden (armor or shield)", L1.ALLY)
    L4._new_turn(engine, L1.ALLY)
    assert ally.temporary_hp == 4
    _cast_as(L1, engine, "Fray Mandate: Burden", AN)
    assert any(c.condition_id == "condition:typed.no_dash" for c in foe.conditions.values())


def test_court_of_ten_thousand_mandates_raises_the_load_and_gives_temporary_hp():
    L1, engine, me, ally, foe = _imbuer(["court_of_ten_thousand_mandates", "clarify_and_cloud", "quicken_and_slow"], cl=12)
    me.resources["resource:core.qi"] = 30
    _cast_as(L1, engine, "Court of Ten Thousand Mandates", None)
    from combat.ext import imbuement_mandates

    assert imbuement_mandates.load(engine, me, 4) == 5
    _cast_as(L1, engine, "Place Mandate: Quicken", L1.ALLY)
    _cast_as(L1, engine, "Place Mandate: Clarify", L1.ALLY)
    assert any(m.source_definition_id.endswith("mandate.imbue.quicken") for m in ally.modifiers.values())
    assert ally.temporary_hp == 2  # the key ability modifier


def test_guardian_shell_reduces_incoming_damage_once_per_round():
    from combat import ext

    L1, engine, me, ally, foe = _imbuer(["true_tempering_command", "tempered_equipment"], cl=12)
    _cast_as(L1, engine, "Place Mandate: Temper + Guardian Shell", L1.ALLY)
    assert sum(ext.run("damage_reduction", engine, ally, "SLASHING", {}, AN, applied=True)) == 4
    assert sum(ext.run("damage_reduction", engine, ally, "SLASHING", {}, AN, applied=True)) == 0
    assert ext.run("ac", engine, ally) and sum(ext.run("ac", engine, ally)) >= 2


def test_twin_fray_puts_two_fray_options_on_one_target_with_one_save():
    L1, engine, me, ally, foe = _imbuer(["twin_fray", "quicken_and_slow", "suppress_function"], dc=50)
    _answers(engine, {"twin_fray": lambda options: [o for o in options if o.endswith(".slow") or o.endswith(".still_tongue")]})
    events = _cast_as(L1, engine, "Fray Mandate: Twin Fray (2 CP)", AN)
    assert len([e for e in events if e.event_type == "SAVE_ROLLED"]) == 1
    assert any(c.condition_id == "condition:typed.silenced" for c in foe.conditions.values())
    assert any(m.source_definition_id.endswith("twin_fray") for m in foe.modifiers.values())  # Slow's halved Speed


def test_touch_carried_mandate_rides_a_hit_for_one_cp():
    from tests import test_auto_lane1 as L1

    sheet = t._sheet("tianxia.sphere.imbuement", [IMB + "touch_carried_mandate", IMB + "quicken_and_slow"], {"starting_kit": {"items": [DAO]}}, dc=50)
    engine = t._engine(compile_character(sheet, actor_id=ME))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    stamina = me.resources["resource:core.stamina"]
    _use(engine, "Dao (Saber / Broadsword) attack")
    assert me.resources["resource:core.stamina"] == stamina - 1
    assert any(c.condition_id == "condition:typed.fray_mandate" for c in foe.conditions.values())
    assert me.concentration is not None and me.concentration.source_definition_id.endswith("mandate.fray.slow")
    del L1


def test_counter_mandate_ends_another_cultivators_fray_on_you():
    engine = L4._duel([IMB + "quicken_and_slow"], subject_sphere="tianxia.sphere.imbuement", attacker_sphere="tianxia.sphere.imbuement",
                      attacker_talents=[IMB + "clarify_and_cloud"])
    me, foe = engine.state.actors[ME], engine.state.actors[L4.SUBJ]
    assert "Counter-Mandate: free an ally" not in _legal(engine)
    me.saving_throws["WIS"] = -30
    L4._new_turn(engine, L4.SUBJ)
    foe.action_available = True
    slow = next(c for c in engine.legal_candidates() if c.actor_id == L4.SUBJ and c.display_name == "Fray Mandate: Slow")
    engine.execute_intent(ActionIntent(intent_id="slow", decision_id=slow.decision_id, candidate_id=slow.candidate_id,
                                       state_version=slow.state_version, actor_id=L4.SUBJ, target_ids=slow.target_ids))
    assert any(m.source_definition_id.endswith("mandate.fray.slow") for m in me.modifiers.values())
    L4._new_turn(engine, ME)
    from tests import test_sysv2_objects as O

    O.force_d20(engine, 20, 20)
    events = _use(engine, "Counter-Mandate: free an ally", ME)
    assert next(e for e in events if e.event_type == "CHECK_ROLLED").payload["skill"] == "Imbuement Check"
    assert not any(m.source_definition_id.endswith("mandate.fray.slow") for m in me.modifiers.values())
    assert foe.concentration is None or not foe.concentration.source_definition_id.endswith("mandate.fray.slow")


def test_heavy_light_field_is_one_field_or_the_other():
    L1, engine, me, ally, foe = _imbuer(["heavy_light_field"], cl=12, dc=50)
    names = {c.display_name.split(" at ")[0] for c in engine.legal_candidates() if c.actor_id == L1.ME}
    assert {"Heavy-Light Field: Light Field", "Heavy-Light Field: Heavy Field"} <= names
    L1._ready(engine)
    heavy = next(c for c in engine.legal_candidates() if c.actor_id == L1.ME and c.display_name.startswith("Heavy-Light Field: Heavy Field")
                 and c.destination and (c.destination.x, c.destination.y) == (4, 6))
    engine.execute_intent(ActionIntent(intent_id="heavy", decision_id=heavy.decision_id, candidate_id=heavy.candidate_id,
                                       state_version=heavy.state_version, actor_id=L1.ME, target_ids=heavy.target_ids, destination=heavy.destination))
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert zone.trigger_profile.get("difficult") and not zone.trigger_profile.get("inside")
    from combat import zones

    zones.on_turn_start(engine, foe)
    assert any(c.condition_id == "condition:typed.no_dash" for c in foe.conditions.values())


def test_a_mandate_placed_on_yourself_lands_on_you():
    L1, engine, me, ally, foe = _imbuer(["clarify_and_cloud"])
    _answers(engine, {"mandate_choice": lambda options: ["CHA"]})
    _cast_as(L1, engine, "Place Mandate: Clarify", L1.ME)
    from combat.typed_executor import check_mode

    assert check_mode(me, "CHA") == "ADVANTAGE"


IMBUEMENT_FULL = ["IMBUEMENT_BASE_FRAY_MANDATE", "IMBUEMENT_BASE_COUNTER_MANDATE", IMB + "physique_and_weakness", IMB + "twin_fray", IMB + "touch_carried_mandate"]


def test_imbuement_lines_the_table_now_runs_are_no_longer_gm_riders():
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in IMBUEMENT_FULL} == {key: "FULL" for key in IMBUEMENT_FULL}
    assert [o["label"] for o in mechanics[IMB + "heavy_light_field"]["options"]] == ["Light Field", "Heavy Field"]
    assert all(e["type"] == "mandate_option" for e in mechanics[IMB + "quicken_and_slow"]["effects"])
    assert mechanics[IMB + "quicken_and_slow"].get("modifier") is None


# ================================================================================================================ Sabers
SAB = "tianxia.talent.sabers."
SABERS = "tianxia.sphere.sabers"
DUAN = {"item_id": "tianxia.mortal.weapon.duan_dao", "name": "Duan Dao", "quantity": 1}


def _crowd(talents, items=(DAO,), foes=2, cl=10, dc=16, foe_items=(DAO,)):
    """ME (a Sabers fighter) against ``foes`` Factory fighters standing east of it, all adjacent."""
    from combat.gate4_engine import Gate4ControllerEngine

    mine = compile_character(_sheet(talents, items, (SABERS,), cl, dc), actor_id=ME)
    theirs = [compile_character(t._sheet(SABERS, [], {"starting_kit": {"items": list(foe_items)}}), actor_id=f"actor:factory.foe{i}") for i in range(foes)]
    ids = [ME, *(b["actor_id"] for b in theirs)]
    spots = [(4, 6), (4, 7), (4, 5)]
    engine = Gate4ControllerEngine(ROOT, match_seed="C5SABER", typed_bundles=(mine, *theirs),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:b" for b in theirs}},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, **{b["actor_id"]: {"x": spots[i][0], "y": spots[i][1]} for i, b in enumerate(theirs)}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for b in theirs:
        foe = engine.state.actors[b["actor_id"]]
        foe.armor_class, foe.maximum_hp = -50, 300
        foe.current_hp = 300
    t._ready(engine)
    return engine, engine.state.actors[ME], [engine.state.actors[b["actor_id"]] for b in theirs]


def _gp(engine, creature):
    from combat.typed_executor import mark_condition_id

    return any(c.condition_id == mark_condition_id("Guard Pressured", ME) for c in creature.conditions.values())


def test_circle_cleaving_saber_attacks_every_creature_in_reach_once_and_pressures_one():
    engine, me, foes = _crowd([SAB + "circle_cleaving_saber"], foes=2)
    events = _use(engine, "Circle-Cleaving Saber", foes[0].entity_id)
    attacked = {tid for e in events if e.event_type == "ATTACK_ROLLED" for tid in e.target_ids}
    assert attacked == {f.entity_id for f in foes}
    assert sum(_gp(engine, f) for f in foes) == 1


def test_counter_slope_dao_steps_in_and_pressures_the_attacker_that_missed():
    engine, me, foes = _crowd([SAB + "counter_slope_dao"], foes=1)
    foe = foes[0]
    me.armor_class = 99
    stamina = me.resources["resource:core.stamina"]
    L4._new_turn(engine, foe.entity_id)
    foe.action_available = True
    swing = next(c for c in engine.legal_candidates() if c.actor_id == foe.entity_id and c.display_name == "Dao (Saber / Broadsword) attack")
    engine.execute_intent(ActionIntent(intent_id="miss", decision_id=swing.decision_id, candidate_id=swing.candidate_id,
                                       state_version=swing.state_version, actor_id=foe.entity_id, target_ids=swing.target_ids))
    assert me.resources["resource:core.stamina"] == stamina - 1 and _gp(engine, foe)


def test_hewing_entry_lets_the_user_pick_guard_pressured_over_prone():
    engine, me, foes = _crowd([SAB + "hewing_entry"], foes=1, dc=50)
    _answers(engine, {"effect_choices": lambda options: ["Guard Pressured"]})
    _use(engine, "Hewing Entry", foes[0].entity_id)
    assert _gp(engine, foes[0]) and not any(c.condition_id == "condition:typed.prone" for c in foes[0].conditions.values())


def test_short_saber_infighting_shoves_after_a_duan_dao_hit_only():
    engine, me, foes = _crowd([SAB + "short_saber_infighting"], items=(DAO, DUAN), foes=1, dc=50)
    for c in foes[0].saving_throws:
        foes[0].saving_throws[c] = -30
    _use(engine, "Dao (Saber / Broadsword) attack", foes[0].entity_id)
    assert not any(c.condition_id == "condition:typed.prone" for c in foes[0].conditions.values())
    _use(engine, "Duan Dao (Short Saber) attack", foes[0].entity_id)
    assert any(c.condition_id == "condition:typed.prone" for c in foes[0].conditions.values()) and _gp(engine, foes[0])


def test_army_line_chopping_field_lets_allies_through_the_cut_without_opportunity_attacks():
    from combat import ext

    engine, me, foes = _crowd([SAB + "army_line_chopping_field"], foes=1, cl=10, dc=50)
    me.resources["resource:core.stamina"] = 60
    _aim(engine, "Army-Line Chopping Field", (5, 6))
    foe = foes[0]
    assert any(c.condition_id == "condition:typed.cone_passage" for c in foe.conditions.values())
    assert ext.any_false("opportunity_allowed", engine, foe, me)  # ME stands in the cone's first square? no: ME is the vertex
    ally = me.model_copy(deep=True)
    ally.entity_id = "actor:c5.ally"
    ally.position = foe.position.model_copy(update={"x": 5})
    assert ext.any_false("opportunity_allowed", engine, foe, ally)
    ally.position = foe.position.model_copy(update={"x": 1})
    assert not ext.any_false("opportunity_allowed", engine, foe, ally)


def test_domain_of_the_unanswered_cut_tests_only_pressed_or_bloodied_foes():
    from combat import zones
    from combat.typed_executor import mark_condition_id

    engine, me, foes = _crowd([SAB + "domain_of_the_unanswered_cut"], foes=2, cl=17, dc=50)
    me.resources["resource:core.stamina"] = 60
    _use(engine, "Domain of the Unanswered Cut", None)
    pressed, calm = foes
    engine._apply_condition(pressed, mark_condition_id("Guard Pressured", ME), "test", ME, expires_on="UNTIL_REMOVED", data={"mark": "Guard Pressured"})
    zones.on_turn_start(engine, pressed)
    zones.on_turn_start(engine, calm)
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in pressed.conditions.values())
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in calm.conditions.values())


def test_execution_platform_presence_adds_1d8_to_a_prone_target_and_a_kill_ends_your_fear():
    engine, me, foes = _crowd([SAB + "execution_platform_presence"], foes=1, cl=12)
    me.resources["resource:core.stamina"] = 60
    _use(engine, "Execution Platform Presence", None)
    foe = foes[0]
    events = _use(engine, "Dao (Saber / Broadsword) attack", foe.entity_id)
    assert not any("+1d8 slashing damage" in str(e.payload) for e in events if e.event_type == "GM_RIDER")  # not Prone yet
    source = SAB + "execution_platform_presence"
    _no_stance_damage(events, source)
    engine._apply_condition(foe, "condition:typed.prone", "test", ME, expires_on="UNTIL_REMOVED")
    events = _use(engine, "Dao (Saber / Broadsword) attack", foe.entity_id)
    # LOG1 (round22 merge 13) moved automated notices to PASSIVE_TRIGGERED.
    _stance_damage(events, me, foe, source, "Execution Platform Presence", 1, 8, "SLASHING")
    _no_stance_damage(_use(engine, "Dao (Saber / Broadsword) attack", foe.entity_id), source)
    engine._apply_condition(me, "condition:typed.frightened", "test:fear", foe.entity_id, expires_on="UNTIL_REMOVED")
    foe.current_hp = 1
    _use(engine, "Dao (Saber / Broadsword) attack", foe.entity_id)
    assert not foe.active and not any(c.condition_id == "condition:typed.frightened" for c in me.conditions.values())


def test_saber_scare_asks_which_creature_to_affect():
    engine, me, foes = _crowd([SAB + "saber_scare"], foes=2, dc=50)
    requests = _answers(engine, {"saber_scare": lambda options: [foes[1].entity_id]})
    foes[0].current_hp = 1
    _use(engine, "Dao (Saber / Broadsword) attack", foes[0].entity_id)
    assert requests and any(c.condition_id == "condition:typed.reaction_denied" for c in foes[1].conditions.values())


def test_saber_scare_fires_on_a_critical_hit_that_leaves_the_target_alive(monkeypatch):
    """Printed trigger: "you reduce a creature to 0 HP with a Sabers talent OR score a critical hit with a
    saber". The critical branch is independent of damage dealt, so a Critical Hit on a surviving creature
    still frightens. DAMAGE_COMMITTED carries no critical flag, so the trigger is read from the settled
    attack_result instead of a damage event."""
    from combat import ext

    engine, me, foes = _crowd([SAB + "saber_scare"], foes=2, dc=50)
    ext.effects()

    def crit(engine, roll, intent):
        if roll.actor_id == ME and str(roll.reason).startswith("ATTACK:"):
            return {"source_id": "test:saber-critical", "operation": "replace", "natural_result": 20}
        return None

    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", []), crit])
    requests = _answers(engine, {"saber_scare": lambda options: [foes[1].entity_id]})
    _use(engine, "Dao (Saber / Broadsword) attack", foes[0].entity_id)
    assert foes[0].active and foes[0].current_hp > 0, "target survives: this exercises the critical branch, not the drop-to-0 branch"
    assert requests, "a critical saber hit must offer the printed choice of one hostile creature to frighten"
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in foes[1].conditions.values())


def _saber_multi_strike(engine, me, strikes):
    """Turn ME's own saber weapon attack into a ONE-activation multi-strike (``count``), so every strike
    shares a single intent and a single resolution cache -- the shape the Scare critical receipt is read in.

    The old implementation appended target ids to an activation-wide list, so a leak only shows up when
    several strikes resolve inside one activation; separate intents each build a fresh Context and would
    hide it. Returns the display name to use."""
    name = "Dao (Saber / Broadsword) attack"
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == me.entity_id and a.display_name == name)
    effects = (action.parameters or {}).get("typed", {}).get("effects") or []
    attack = next(e for e in effects if e.get("type") == "attack")
    attack["count"] = strikes
    return name


def test_saber_scare_critical_fires_once_per_strike_inside_one_multi_strike_activation(monkeypatch):
    """The printed trigger is about the attack that just resolved, so the receipt is this strike's own result.

    Every sequence below is ONE activation of a multi-strike (``count``): one intent, one resolution cache,
    several strikes -- the shape the old activation-wide list leaked into (a later ordinary blow against a
    creature a Critical Hit had already frightened offered Scare again). A Critical Hit followed by an
    ordinary blow must frighten once; the reverse order frightens once; a Critical, a miss and then an
    ordinary blow frighten only for the Critical; and two genuine Criticals each frighten once. The target
    survives every sequence, so only the critical branch can be firing.
    """
    from combat import ext

    def striking(naturals):
        queue = list(naturals)
        engine, me, foes = _crowd([SAB + "saber_scare"], foes=2, dc=50)
        ext.effects()

        def crit(engine, roll, intent):
            if roll.actor_id == ME and str(roll.reason).startswith("ATTACK:") and queue:
                return {"source_id": "test:saber-critical", "operation": "replace", "natural_result": queue.pop(0)}
            return None

        monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", []), crit])
        requests = _answers(engine, {"saber_scare": lambda options: [foes[1].entity_id]})
        name = _saber_multi_strike(engine, me, len(naturals))
        before = len(engine.events)
        _use(engine, name, foes[0].entity_id)
        events = engine.events[before:]
        assert len([e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == me.entity_id]) == len(naturals), \
            f"all {len(naturals)} strikes must resolve inside this one activation"
        assert not queue, f"every forced natural was consumed by that activation: {naturals}"
        assert foes[0].current_hp > 0 and foes[0].active, \
            "the struck creature survives, so only the critical branch can fire"
        saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == foes[1].entity_id]
        return requests, saves

    after_critical = striking([20, 10])
    assert len(after_critical[0]) == 1, \
        "the ordinary blow after a Critical Hit in the same activation must not offer Saber Scare again"
    assert len(after_critical[1]) == 1, "one qualifying Critical Hit means exactly one Wisdom save"

    after_ordinary = striking([10, 20])
    assert len(after_ordinary[0]) == 1, "a Critical Hit frightens even as the second blow of the activation"

    critical_miss_ordinary = striking([20, 1, 10])
    assert len(critical_miss_ordinary[0]) == 1, \
        "a miss and a later ordinary blow must not add Scare prompts after the Critical"

    two_criticals = striking([20, 20])
    assert len(two_criticals[0]) == 2, "two genuine Critical Hits each frighten"
    assert len(two_criticals[1]) == 2, "each qualifying Critical asks its own Wisdom save"


def test_forward_cut_asks_for_a_step_only_the_target_cannot_react_to():
    """Printed: "If the target is Guard Pressured, you may also move 5 feet after the hit without provoking
    Opportunity Attacks from that target." The step is a player decision, so it is asked with the creature it is
    free of, and its exemption is the step itself (gate2_engine resolves ignore_oa_from per reactor), not a
    turn-long or blanket waiver."""
    from combat.typed_executor import mark_condition_id

    engine, me, foes = _crowd([SAB + "forward_cut"], foes=2)
    engine._apply_condition(foes[0], mark_condition_id("Guard Pressured", me.entity_id), "test:guard-pressured", me.entity_id,
                            expires_on="UNTIL_REMOVED")
    requests = _answers(engine, {"rider_step": None})
    _use(engine, "Forward Cut", foes[0].entity_id)
    steps = [r for r in requests if str(r["reaction_source_id"]).endswith("rider_step")]
    assert steps, "the printed 5 feet is a player decision, so it must be asked"
    assert not me.turn_flags.get("oa_free_ft"), "the step must not waive every creature's Opportunity Attack"
    assert not me.turn_flags.get("spark_step_ignore_oa_from"), \
        "no turn-long exemption outlives the step: later movement provokes the original target again"


SABERS_FULL = [SAB + name for name in ("army_line_chopping_field", "battleline_shove_cut", "circle_cleaving_saber", "counter_slope_dao",
                                        "execution_platform_presence", "hewing_entry", "rider_s_passing_cut", "saber_scare", "short_saber_infighting",
                                        "ten_step_pursuit_doctrine", "wrap_the_head_return_the_edge")]


def test_sabers_coverage_discloses_full_source_limits():
    # AUTO92 full-source audit: the old FULL assertion omitted weapon/reach,
    # willingness, final trigger and historical pursuit clauses. Behavioral
    # tests above retain all original assertions.
    # AUTO127 adds Saber Scare: its one rider (read a recent damage event, which
    # has no critical flag, so a zero-damage Critical Hit was missed) is resolved
    # by reading the settled attack_result, so it is genuinely FULL now.
    # A2SABERS service/reload tests now verify weapon reach, exact recipients,
    # delivered saber identity, per-current-turn hit receipts and ally consent.
    mechanics = _authority()
    complete = {SAB + name for name in ("army_line_chopping_field", "battleline_shove_cut", "hewing_entry", "saber_scare", "circle_cleaving_saber", "execution_platform_presence")}
    assert {key: mechanics[key]["coverage"] for key in SABERS_FULL} == {
        key: "FULL" if key in complete else "CORE_WITH_RIDERS" for key in SABERS_FULL}


# ================================================================================================================ Blood
BL = "tianxia.talent.blood."
QI = "resource:core.qi"


def _bleeder(talents, cl=10, dc=16, qi=40):
    """ME (a Blood cultivator with ``talents``) beside an ally, the foe (500 HP) adjacent; ``qi`` CP to spend."""
    from tests import test_auto_lane1 as L1

    sheet = L1._sheet("BLOOD_BASE_BLOOD_THREAD", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [BL + name for name in talents]
    engine = L1._engine(compile_character(sheet, actor_id=L1.ME), allies=(compile_character(t._sheet(None, [], {}), actor_id=L1.ALLY),))
    me, ally, foe = engine.state.actors[L1.ME], engine.state.actors[L1.ALLY], engine.state.actors[AN]
    me.resource_maximums[QI] = qi
    me.resources[QI] = qi
    foe.maximum_hp = foe.current_hp = 500
    return L1, engine, me, ally, foe


def _thread(engine, owner, creature):
    from combat.typed_executor import mark_condition_id

    engine._apply_condition(creature, mark_condition_id("Blood Thread", owner.entity_id), "test", owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"mark": "Blood Thread"})


def _threaded(owner, creature):
    from combat.typed_executor import mark_condition_id

    return any(c.condition_id == mark_condition_id("Blood Thread", owner.entity_id) for c in creature.conditions.values())


def _offered(L1, engine, name, target):
    L1._ready(engine)
    return [c for c in engine.legal_candidates() if (c.display_name == name or c.display_name.startswith((name + " at ", name + " to "))) and c.actor_id == L1.ME
            and (target is None or tuple(c.target_ids or ()) == (target,))]


def _turn_of(engine, who):
    """End turns until ``who`` starts its turn."""
    for _ in range(4):
        if engine.state.current_actor_id == who and engine.events[-1].event_type != "TURN_ENDED":
            pass
        end = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        engine.execute_intent(ActionIntent(intent_id=f"end-{engine.state.event_sequence}", decision_id=end.decision_id, candidate_id=end.candidate_id,
                                           state_version=end.state_version, actor_id=engine.state.current_actor_id, target_ids=end.target_ids,
                                           destination=end.destination))
        if engine.state.current_actor_id == who:
            return
    raise AssertionError(f"{who} never started a turn")


def test_blood_thread_on_a_willing_ally_opens_coagulate_which_is_one_choice():
    """Blood Thread's "Willing Creature: Apply Blood Thread automatically. The Thread lasts for 1 minute"; Coagulate's "Target: One
    willing creature bearing your Blood Thread ... Choose one" -- it ran stabilize and three Temporary HP rows at once, on anyone."""
    L1, engine, me, ally, foe = _bleeder([])
    assert not _offered(L1, engine, "Coagulate: Temporary HP", L1.ALLY) and not _offered(L1, engine, "Coagulate", L1.ALLY)
    _cast_as(L1, engine, "Blood Thread: willing creature", L1.ALLY)
    assert _threaded(me, ally)
    _cast_as(L1, engine, "Coagulate: Temporary HP", L1.ALLY)
    assert ally.temporary_hp == 4 + 2  # Proficiency Bonus + key ability modifier (no die before CL 11)
    assert {"Coagulate: Stabilize", "Coagulate: End Bleeding"} <= {c.display_name for c in _offered(L1, engine, "Coagulate: Stabilize", L1.ALLY)
                                                                   + _offered(L1, engine, "Coagulate: End Bleeding", L1.ALLY)}


def test_blood_ward_adds_pb_when_the_protected_creature_is_bloodied_or_threaded():
    import copy

    from combat import typed_reactions

    L1, engine, me, ally, foe = _bleeder(["blood_ward"], cl=1)
    row = copy.deepcopy(next(r for r in typed_reactions._rows(engine, L1.ME, "generic") if r["name"] == "Blood Ward"))
    for effect in row["effects"]:
        effect["dice"], effect["dice_by_cl"] = None, None  # the table's 1d8 aside: key ability modifier (+2), and +PB (4) when it applies
    reduced = lambda: 100 - typed_reactions._generic_damage_reduction(engine, me, row, 100, protected=ally)[0]
    assert reduced() == 2
    _thread(engine, me, ally)
    assert reduced() == 6
    ally.conditions.clear()
    ally.current_hp = ally.maximum_hp // 2
    assert reduced() == 6


def test_blood_armor_costs_5_hp_that_temporary_hp_cannot_pay():
    L1, engine, me, ally, foe = _bleeder(["blood_armor"])
    me.current_hp = 5
    assert not _offered(L1, engine, "Blood Armor", None)
    me.current_hp, me.temporary_hp = 40, 10
    _cast_as(L1, engine, "Blood Armor", None)
    assert (me.current_hp, me.temporary_hp) == (35, 10)


def test_bloodletting_strike_is_asked_on_a_blood_thread_hit_and_bleeds_next_turn():
    """"Trigger: You hit with a melee attack or Blood Thread. Cost: 1 CP ... Failed Save: At the start of its next turn, it takes additional
    Necrotic damage equal to your Proficiency Bonus": it was a pre-paid Blood Thread variant whose save did nothing."""
    L1, engine, me, ally, foe = _bleeder(["bloodletting_strike"], dc=50)
    assert "Blood Thread + Bloodletting Strike" not in {c.display_name for c in engine.legal_candidates()}
    requests = _answers(engine, {})
    _cast_as(L1, engine, "Blood Thread", AN)
    assert [r["reaction_source_id"] for r in requests if r["reaction_source_id"].endswith("bloodletting")] and me.resources[QI] == 39
    (bleed,) = _conditions(foe, "condition:typed.bloodletting")
    assert bleed.data["burn"] == 4
    before = foe.current_hp
    _turn_of(engine, AN)
    assert before - foe.current_hp == 4


def test_blood_puppet_needs_a_bloodied_threaded_target_and_commands_it_each_turn():
    L1, engine, me, ally, foe = _bleeder(["blood_puppet"], dc=50)
    foe.current_hp = 200
    assert not _offered(L1, engine, "Blood Puppet", AN)
    _thread(engine, me, foe)
    foe.current_hp = 300
    assert not _offered(L1, engine, "Blood Puppet", AN)
    foe.current_hp = 200
    _cast_as(L1, engine, "Blood Puppet", AN)
    assert _conditions(foe, "condition:typed.blood_puppet")
    requests = _answers(engine, {"blood_puppet": lambda options: ["prone"]})
    _turn_of(engine, AN)
    assert any(r["reaction_source_id"].endswith("blood_puppet") for r in requests) and _conditions(foe, "condition:typed.prone")


def test_heart_seizing_grip_needs_your_thread_and_hurts_at_the_start_of_each_turn():
    """"Failed Save: Restrained ...; cannot take Reactions; take 3d8 Necrotic damage at the start of each turn": it dealt the 3d8 at once."""
    L1, engine, me, ally, foe = _bleeder(["heart_seizing_grip"], dc=50)
    assert not _offered(L1, engine, "Heart-Seizing Grip", AN)
    _thread(engine, me, foe)
    events = _cast_as(L1, engine, "Heart-Seizing Grip", AN)
    assert _damage(events) == 0 and _conditions(foe, "condition:typed.restrained") and _conditions(foe, "condition:typed.reaction_denied")
    before = foe.current_hp
    _turn_of(engine, AN)
    assert 3 <= before - foe.current_hp <= 24


def test_heart_seizing_grips_next_roll_replays_from_the_saved_events():
    """The Burn's roll for the holder's next turn is made as its turn ends; a fight rebuilt from its events must carry that roll."""
    from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events

    L1, engine, me, ally, foe = _bleeder(["heart_seizing_grip"], dc=50)
    _thread(engine, me, foe)
    _cast_as(L1, engine, "Heart-Seizing Grip", AN)
    _turn_of(engine, AN)
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    _turn_of(engine, L1.ME)
    replayed = Gate3EventReducer().apply_events(before, enrich_committed_events(engine.events[start:], post_engine=engine))
    live = {c.instance_id: c.data.get("burn") for c in _conditions(foe, "condition:typed.heart_seizing_grip")}
    assert live and {c.instance_id: c.data.get("burn") for c in replayed.actors[AN].conditions.values()
                     if c.condition_id == "condition:typed.heart_seizing_grip"} == live

def test_crimson_feast_is_asked_once_per_turn_and_heals_only_to_half():
    L1, engine, me, ally, foe = _bleeder(["crimson_feast"], cl=10)
    foe.current_hp = 240
    _thread(engine, me, foe)
    me.current_hp = 28
    requests = _answers(engine, {})
    _cast_as(L1, engine, "Blood Thread", AN)
    assert [r for r in requests if r["reaction_source_id"].endswith("crimson_feast")] and me.resources[QI] == 38
    assert me.current_hp == 30  # PB 4, but never above half of 60
    _cast_as(L1, engine, "Blood Thread", AN)
    assert len([r for r in requests if r["reaction_source_id"].endswith("crimson_feast")]) == 1


def test_crimson_sacrifice_in_open_the_veins_pays_cp_with_hp_and_the_save_can_bloody_you():
    from combat.ext import forged_exhaustion

    L1, engine, me, ally, foe = _bleeder(["open_the_veins", "heart_seizing_grip"], dc=50)
    _thread(engine, me, foe)
    _cast_as(L1, engine, "Crimson Sacrifice: pay all the CP you may with HP", None)
    _cast_as(L1, engine, "Open the Veins", None)
    _cast_paying(L1, engine, "Heart-Seizing Grip", AN)
    assert (me.resources[QI], me.current_hp) == (40, 60 - 6 * 4)  # 6 CP replaced at 4 HP each (at most 2 x PB = 8)
    _turn_of(engine, L1.ALLY)
    assert me.current_hp == 30 and forged_exhaustion.level(me) == 1  # failed its own DC: Bloodied, one level of Exhaustion


def test_heartblood_rebirth_returns_at_the_start_of_the_next_turn_with_ac_15_until_then():
    from combat import typed_reactions

    L1, engine, me, ally, foe = _bleeder(["heartblood_rebirth"], cl=15, qi=20)
    me.current_hp = 10
    engine._commit_damage(me, typed_reactions.on_damage(engine, me, 999, 0, source_actor_id=AN), "TEST", "system:test.lethal", AN, None, reaction_depth=0)
    assert (me.current_hp, me.temporary_hp, me.resources[QI]) == (1, 0, 10)
    assert me.armor_class + engine._ac_modifier(me) == 15 and engine._effective_speed(me) == 0
    resisted = {m.value for m in me.modifiers.values() if m.target_field == "damage_resistance"}
    assert "SLASHING" in resisted and "RADIANT" not in resisted and "PSYCHIC" not in resisted
    _turn_of(engine, L1.ME)
    assert me.resources[QI] == 14 and 2 <= me.temporary_hp <= 20 and me.armor_class + engine._ac_modifier(me) == 14


def test_crimson_court_adds_pb_to_healing_once_per_turn():
    from combat.typed_executor import Context, block_healing

    L1, engine, me, ally, foe = _bleeder(["crimson_court"], cl=10)
    _cast_as(L1, engine, "Crimson Court", None)
    ally.current_hp = 10
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Crimson Court")
    heal = lambda: block_healing(Context(engine, me, action, None, {}, [ally], ally, {}), {"type": "healing", "applies_to": "target", "flat": 5})
    heal()
    assert ally.current_hp == 19
    heal()
    assert ally.current_hp == 24


def test_blood_emperor_incarnation_threads_and_drains_bloodied_foes_and_rolls_6d10_blood_threads():
    from combat import zones

    L1, engine, me, ally, foe = _bleeder(["blood_emperor_incarnation"], cl=17, dc=50)
    _cast_as(L1, engine, "Blood Emperor Incarnation", None)
    foe.current_hp, me.current_hp = 200, 20
    zones.on_turn_start(engine, foe)
    assert _threaded(me, foe) and me.current_hp == 20 + (200 - foe.current_hp) // 2
    engine.rolls.clear()
    _cast_as(L1, engine, "Blood Thread", AN)
    assert any(len(roll.dice) == 6 and roll.expression.startswith("6d10") for roll in engine.rolls)


def test_rivers_run_red_threads_bloodied_creatures_inside_and_blood_river_passage_lands_by_a_thread():
    from combat.ext import blood_riders

    L1, engine, me, ally, foe = _bleeder(["rivers_run_red", "blood_river_passage"], cl=15)
    assert not _offered(L1, engine, "Blood River Passage", None)
    _thread(engine, me, foe)
    spots = {(c.destination.x, c.destination.y) for c in _offered(L1, engine, "Blood River Passage", None)}
    assert spots and all(max(abs(x - 4), abs(y - 6)) <= 1 for x, y in spots)
    foe.conditions.clear()
    L1._ready(engine)
    rivers = min((c for c in engine.legal_candidates() if c.display_name.startswith("Rivers Run Red") and c.destination is not None),
                 key=lambda c: abs(c.destination.x - 4) + abs(c.destination.y - 6))
    engine.execute_intent(ActionIntent(intent_id="rivers", decision_id=rivers.decision_id, candidate_id=rivers.candidate_id, state_version=rivers.state_version,
                                       actor_id=L1.ME, target_ids=rivers.target_ids, destination=rivers.destination))
    foe.current_hp = 400
    assert not blood_riders.bears_thread(engine, me, foe)
    foe.current_hp = 200
    assert blood_riders.bears_thread(engine, me, foe)


def test_blood_mending_ends_bleeding_and_heals_a_creature_once():
    L1, engine, me, ally, foe = _bleeder(["blood_mending"])
    ally.current_hp = 10
    engine._apply_condition(ally, "condition:typed.bleeding", "test", AN, expires_on="UNTIL_REMOVED")
    _cast_as(L1, engine, "Blood Mending", L1.ALLY)
    assert ally.current_hp > 10 and not _conditions(ally, "condition:typed.bleeding")
    assert not _offered(L1, engine, "Blood Mending", L1.ALLY)


BLOOD_FULL = ["BLOOD_BASE_BLOOD_THREAD", "BLOOD_BASE_COAGULATE", *(BL + name for name in (
    "blood_armor", "blood_mending", "blood_ward", "bloodletting_strike", "crimson_feast", "crimson_wave", "heart_seizing_grip", "open_the_veins",
    "rivers_run_red"))]


def test_blood_lines_the_table_now_runs_are_no_longer_gm_riders():
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in BLOOD_FULL} == {key: "FULL" for key in BLOOD_FULL}


# ================================================================================================================ Dreams
DR = "tianxia.talent.dreams."


def _dreamer(talents, cl=10, dc=16, qi=40):
    """ME (a Dreams cultivator with ``talents``, full ids) beside an ally, the foe (500 HP) adjacent."""
    from tests import test_auto_lane1 as L1

    sheet = L1._sheet("DREAMS_BASE_DREAMSCAPE", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents)
    engine = L1._engine(compile_character(sheet, actor_id=L1.ME), allies=(compile_character(t._sheet(None, [], {}), actor_id=L1.ALLY),))
    me, ally, foe = engine.state.actors[L1.ME], engine.state.actors[L1.ALLY], engine.state.actors[AN]
    me.resource_maximums[QI] = qi
    me.resources[QI] = qi
    foe.maximum_hp = foe.current_hp = 500
    return L1, engine, me, ally, foe


def _seeded(owner, creature):
    from combat.typed_executor import mark_condition_id

    return any(c.condition_id == mark_condition_id("Dream Seed", owner.entity_id) for c in creature.conditions.values())


def _seed(engine, owner, creature):
    from combat.typed_executor import mark_condition_id

    engine._apply_condition(creature, mark_condition_id("Dream Seed", owner.entity_id), "test", owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"mark": "Dream Seed"})


def test_dream_seed_is_an_action_a_failed_save_plants_it_and_makes_the_target_drowsy():
    """The catalog kept Dream Seed only as its rules paragraph, so no Seed talent could ever be used; Drowsy did not exist."""
    L1, engine, me, ally, foe = _dreamer([], dc=50)
    speed = engine._effective_speed(foe)
    _cast_as(L1, engine, "Dream Seed", AN)
    assert _seeded(me, foe) and _conditions(foe, "condition:typed.drowsy") and engine._effective_speed(foe) == speed - 10
    assert any((c.data.get("rule") or {}).get("concentration_mode") == "DISADVANTAGE" for c in _conditions(foe, "condition:typed.concentration_mode"))
    _cast_as(L1, engine, "Dream Seed: willing creature", L1.ALLY)
    assert _seeded(me, ally) and not _conditions(ally, "condition:typed.drowsy")


def test_sleep_needs_a_seed_or_drowsy_target_and_the_sleeper_wakes_when_hurt():
    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_SLEEP"], dc=50)
    assert not _offered(L1, engine, "Sleep", AN)
    _seed(engine, me, foe)
    _cast_as(L1, engine, "Sleep", AN)
    assert _conditions(foe, "condition:typed.dream_sleep") and _conditions(foe, "condition:typed.prone")
    engine._commit_damage(foe, 5, "SLASHING", "system:test.hit", L1.ALLY, None, reaction_depth=0)
    assert not _conditions(foe, "condition:typed.dream_sleep") and _conditions(foe, "condition:typed.prone")


def test_dream_prison_keeps_its_prisoner_from_targeting_creatures_beyond_10_feet():
    from types import SimpleNamespace

    from combat import ext

    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_DREAM_PRISON"], dc=50)
    _seed(engine, me, foe)
    _cast_as(L1, engine, "Dream Prison", AN)
    near, far = (SimpleNamespace(target_ids=(who,), source_definition_id="action:test", destination=None) for who in (L1.ME, L1.ALLY))
    assert not ext.any_false("candidate_allowed", engine, foe, near, None)
    ally.position = ally.position.model_copy(update={"x": 10})
    assert ext.any_false("candidate_allowed", engine, foe, far, None)


def test_dream_needle_asks_for_one_of_its_four_riders_on_a_hit():
    """It applied the Dream Seed and the Frightened-save Disadvantage together on every hit, and never Drowsy."""
    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_DREAM_NEEDLE"])
    requests = _answers(engine, {"effect_choices": lambda options: [next(o for o in options if o.startswith("Drowsy"))]})
    _cast_as(L1, engine, "Dream Needle", AN)
    assert requests and _conditions(foe, "condition:typed.drowsy") and not _seeded(me, foe)


def test_court_of_the_half_waking_moon_tests_enemies_as_their_turns_start():
    from combat import zones

    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_COURT_HALF_WAKING_MOON"], dc=50)
    events = _cast_as(L1, engine, "Court of the Half-Waking Moon: Drowsy", None)
    assert not [e for e in events if e.event_type == "SAVE_ROLLED"] and not _conditions(foe, "condition:typed.drowsy")
    zones.on_turn_start(engine, foe)
    assert _conditions(foe, "condition:typed.drowsy")


def test_a_lucid_veil_dreamscape_makes_foes_drowsy_and_shelters_allies():
    from types import SimpleNamespace

    from combat import zones
    from combat.ext import dreams_core

    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_LUCID_VEIL"], cl=10, dc=50)
    _cast_as(L1, engine, "Shape Dreamscape: Lucid Veil", None)
    L1._ready(engine)
    scape = min((c for c in engine.legal_candidates() if c.display_name.startswith("Dreamscape") and c.destination is not None),
                key=lambda c: abs(c.destination.x - 4) + abs(c.destination.y - 6))
    engine.execute_intent(ActionIntent(intent_id="scape", decision_id=scape.decision_id, candidate_id=scape.candidate_id, state_version=scape.state_version,
                                       actor_id=L1.ME, target_ids=scape.target_ids, destination=scape.destination))
    zones.on_turn_start(engine, foe)
    assert _conditions(foe, "condition:typed.drowsy")
    assert dreams_core.sheltered(SimpleNamespace(engine=engine), ally, "WIS", {"frightened"}) == {"modes": ["ADVANTAGE"]}
    assert dreams_core.sheltered(SimpleNamespace(engine=engine), foe, "WIS", {"frightened"}) is None


def test_nightmare_chain_makes_its_target_drowsy_at_the_start_of_each_of_its_turns():
    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_NIGHTMARE_CHAIN"], dc=50)
    _seed(engine, me, foe)
    _cast_as(L1, engine, "Nightmare Chain", AN)
    assert not _conditions(foe, "condition:typed.drowsy")
    _turn_of(engine, AN)
    assert _conditions(foe, "condition:typed.drowsy")


def test_dream_sovereign_incarnation_rolls_6d10_needles_and_plants_a_seed_each_turn():
    L1, engine, me, ally, foe = _dreamer(["TAL_DREAM_DREAM_NEEDLE", DR + "dream_sovereign_incarnation"], cl=15)
    assert not any("+" in c.display_name and "Needle" in c.display_name for c in engine.legal_candidates())
    _cast_as(L1, engine, "Dream-Sovereign Incarnation", None)
    engine.rolls.clear()
    _cast_as(L1, engine, "Dream Needle", AN)
    assert any(roll.expression.startswith("6d10") for roll in engine.rolls)
    foe.conditions.clear()
    _turn_of(engine, L1.ME)
    assert _seeded(me, foe)


def test_gentle_awakening_ends_dream_sleep_on_a_willing_creature():
    L1, engine, me, ally, foe = _dreamer([DR + "gentle_awakening"])
    engine._apply_condition(ally, "condition:typed.dream_sleep", "test", AN, expires_on="UNTIL_REMOVED")
    _answers(engine, {"effect_choices": lambda options: ["End Dream Sleep"]})
    _cast_as(L1, engine, "Gentle Awakening", L1.ALLY)
    assert not _conditions(ally, "condition:typed.dream_sleep")


DREAMS_FULL = ["DREAMS_BASE_DREAM_SEED", "DREAMS_BASE_DROWSY_THOUGHT", "TAL_DREAM_HALF_WAKING_HAZE", "TAL_DREAM_DREAM_NEEDLE", "TAL_DREAM_DREAM_PRISON",
               "TAL_DREAM_FALSE_AWAKENING", "TAL_DREAM_NIGHTMARE_CHAIN", "TAL_DREAM_NIGHTMARE_GLIMPSE", DR + "world_of_dreams"]


def test_dreams_lines_the_table_now_runs_are_no_longer_gm_riders():
    mechanics = _authority()
    assert {key: mechanics[key]["coverage"] for key in DREAMS_FULL} == {key: "FULL" for key in DREAMS_FULL}
