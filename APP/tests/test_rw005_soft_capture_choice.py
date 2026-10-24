"""RW005 B5-P1: Soft Capture's Strength-or-Dexterity save belongs to the caught creature.

Printed rule (Sphere Compendium, record TAL_FLOWING_RIVER_SOFT_CAPTURE, …85Spheres.md:31712): "When your
Flowing Response succeeds against a creature within reach, the triggering creature makes a Strength or Dexterity
saving throw, choosing which, against your Cultivation Save DC."

The compiled rider save is "STR_OR_DEX" with no target_choice flag, so combat/typed_executor.py's unflagged
selector answered it with the target's better ability -- the engine choosing for the target. combat/ext/
soft_capture_save.py now asks the subject through the ordinary choice transport; these tests drive the real fight
(attacker's miss receipt, the response succeeding, the checkpoint, the save and its consequence).
"""
import json

import pytest

from combat import typed_executor as te, typed_reactions as tr
from combat.ext import flowing_river, soft_capture_save
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, turn, reload
from tests.h1_support import ROOT, sheet
from tests.test_zones import SHEET

P = "TAL_FLOWING_RIVER_"
RESPONSE = P + "FLOWING_RESPONSE"
SOFT = P + "SOFT_CAPTURE"
HAND = P + "HAND_ON_THE_WRIST"
SPEAR = P + "RIVER_TAKES_THE_SPEAR"
CIRCLE = P + "CIRCULAR_THROW"
SAVE_CHOICE = "choice:needle.save_choice"
STEP = "choice:needle.river_step"
ME = "actor:factory.rw005"
WORSE_DEX = {"STR": 20, "DEX": -20}


def _miss(bundle):
    """The attacker's weapon attack always misses; Flowing Response succeeds on that receipt."""
    if bundle["actor_template"]["entity_id"] != RIGHT:
        return
    for action in bundle["action_catalog"]:
        if action["display_name"] == "Cause":
            action.update(resolution_kind="ATTACK", range_ft=None, reach_ft=5, attack_bonus=-100,
                          damage=None, damage_type="BLUDGEONING")
            action["parameters"] = {"attack_kind": "weapon", "free_primary": True}


def _scores(bundle, actor_id, scores):
    if bundle["actor_template"]["entity_id"] == actor_id:
        bundle["actor_template"]["saving_throws"].update(scores)


def _setup(tmp_path, talents=(SOFT,), *, cause=None, scores=None, save_dc=1):
    """A real table: Keeper (LEFT) owns Flowing Response and the given talents, Visitor (RIGHT) attacks."""
    def edit(bundle):
        if cause is None:
            _miss(bundle)
        for actor_id, values in (scores or {}).items():
            _scores(bundle, actor_id, values)
    return fight(tmp_path, [RESPONSE, *talents], left_score=14, spheres=["tianxia.sphere.flowing_river"],
                 left_save_dc=save_dc, cause_save_dc=save_dc,
                 cause=cause if cause is not None else [{"type": "attack", "attack_kind": "melee", "no_damage": True}],
                 bundle_edit=edit)


def _settle(send, pick=None, limit=12):
    """Answer the fight's questions through the real table, recording each prompt."""
    answers, prompts = [], []
    for _ in range(limit):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        if not prompt.get("choice"):
            answers.append({**prompt["context"], "selection": "USE", "option_ids": []})
            continue
        options = [option["id"] for option in prompt["choice"]["options"]]
        chosen = pick(prompt) if pick else options[:1]
        answers.append({**prompt["context"], "selection": "USE" if chosen else "DECLINE", "option_ids": chosen})
    raise AssertionError("too many questions")


def _arm(table, mid, talent="Soft Capture"):
    """Pick the Response talent the owner uses ("Flowing Response: <talent>" is a free toggle)."""
    assert act(table, mid, f"Flowing Response: {talent}")["status"] == "COMMITTED"


def _save_pick(option_id, step=()):
    def pick(prompt):
        source = prompt["context"]["reaction_source_id"]
        if source == SAVE_CHOICE:
            return [option_id]
        if source == STEP:
            return list(step)
        return [option["id"] for option in prompt["choice"]["options"]][:1]
    return pick


def _saves(engine, actor_id):
    return [event.payload for event in engine.events
            if event.event_type == "SAVE_ROLLED" and event.actor_id == actor_id]


@pytest.mark.parametrize("mode", ["MANUAL", "MANUAL_AI_BRIDGE"])
def test_caught_creature_is_asked_for_strength_or_dexterity(tmp_path, mode):
    """(a) the attacker reaches a checkpoint; the offered answers are exactly its two abilities."""
    combat, table, mid = _setup(tmp_path)
    _arm(table, mid)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode=mode)
    turn(table, mid, RIGHT)
    snapshot = combat._load_session(mid).engine.state.model_dump(mode="json")

    def pure_send(answers):
        result = act(table, mid, "Cause", answers, target_id=LEFT)
        if result["status"] == "REACTION_REQUIRED":
            assert combat._load_session(mid).engine.state.model_dump(mode="json") == snapshot, \
                "asking the caught creature must not change the fight"
        return result

    _, prompts = _settle(pure_send, _save_pick("STR"))
    offered = [prompt for prompt in prompts if prompt["context"]["reaction_source_id"] == SAVE_CHOICE]
    assert len(offered) == 1, "Soft Capture offers its save choice exactly once"
    prompt = offered[0]
    assert prompt["context"]["reactor_id"] == RIGHT, "the caught creature answers, not the responder"
    assert prompt["context"]["checkpoint"].startswith("NEEDLE:soft_capture_save_choice:")
    assert prompt["context"]["checkpoint"].split(":")[1] == "soft_capture_save_choice"
    assert f":{RESPONSE}:{RIGHT}" in prompt["context"]["checkpoint"], "scoped to the response source and subject"
    assert [(option["id"], option["label"]) for option in prompt["choice"]["options"]] == [
        ("STR", "Strength saving throw (+2)"), ("DEX", "Dexterity saving throw (+2)")]
    assert prompt["choice"]["minimum"] == 1 and prompt["choice"]["maximum"] == 1
    assert prompt["choice"]["allow_decline"] is False, "the printed rule gives the target no way to skip the choice"
    text = json.dumps(prompt)
    for words in ("Soft Capture", "Flowing Response", "Visitor", "costs no action or resource", "Grappled"):
        assert words in text, words
    engine = reload(combat, mid)
    assert _saves(engine, RIGHT)[0]["reason"].endswith(":STR") and not any(
        condition.condition_id == "condition:typed.grappled"
        for condition in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("option,modifier,success,grappled", [
    ("STR", 20, True, False), ("DEX", -20, False, True)])
def test_chosen_ability_is_the_one_the_save_uses(tmp_path, option, modifier, success, grappled):
    """(b) the answer decides: the same fight rolls and resolves differently for Strength and for Dexterity."""
    combat, table, mid = _setup(tmp_path, scores={RIGHT: WORSE_DEX})
    _arm(table, mid)
    turn(table, mid, RIGHT)
    _, prompts = _settle(lambda answers: act(table, mid, "Cause", answers, target_id=LEFT), _save_pick(option))
    assert any(prompt["context"]["reaction_source_id"] == SAVE_CHOICE for prompt in prompts)
    engine = reload(combat, mid)
    save = _saves(engine, RIGHT)[0]
    assert save["modifier"] == modifier and save["reason"].endswith(":" + option)
    assert save["success"] is success
    holds = any(condition.condition_id == "condition:typed.grappled"
                for condition in engine.state.actors[RIGHT].conditions.values())
    assert holds is grappled


def _bare_fight(talents=(RESPONSE, SOFT)):
    """An engine with no choice transport at all (a saved old fight, or a fight nobody answers)."""
    bundle = compile_character({**SHEET, "equipment": [],
                                "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.flowing_river"],
                                                        "learned_talent_record_ids": list(talents)}},
                               actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="RW005", typed_bundles=(bundle,), roster_setup={
        "primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    row = next(row for row in bundle["typed_reactions"] if row.get("feature_id") == RESPONSE)
    return engine, engine.state.actors[ME], engine.state.actors[AN], row


def test_no_transport_keeps_the_better_ability_fallback(tmp_path):
    """(c) with nobody to answer, nothing changes: the executor's better-ability selector still decides."""
    from dataclasses import replace

    engine, keeper, attacker, row = _bare_fight()
    attacker.saving_throws.update(STR=9, DEX=-9)
    effects = flowing_river._riding(engine, keeper)[SOFT]
    context = tr._generic_context(engine, keeper, attacker, row, None)
    # Exactly what _succeed seals for the chosen talent before running its rider effects.
    te.run_effects(replace(context, typed={**context.typed, "_rider_response_talent": SOFT}), effects)
    save = _saves(engine, AN)[0]
    assert save["modifier"] == 9 and save["reason"].endswith(":STR"), "strength is the better saving throw"


def test_enrollment_follows_the_owner_and_nothing_else():
    """(a) the reactor probe enrolls the fight that owns Soft Capture; a fight without it enrolls nobody."""
    engine = _bare_fight()[0]
    assert set(soft_capture_save.potential_savers(engine)) == {ME, AN}, "any participant may be the one caught"
    assert soft_capture_save.potential_savers(_bare_fight(talents=(RESPONSE,))[0]) == (), "no owner, no cost"


@pytest.mark.parametrize("talent", ["Hand on the Wrist", "River Takes the Spear", "Circular Throw"])
def test_other_flowing_response_talents_offer_no_save_choice(tmp_path, talent):
    """(d) only Soft Capture asks: its sibling Response talents raise no such checkpoint."""
    combat, table, mid = _setup(tmp_path, talents=(HAND, SPEAR, CIRCLE), scores={RIGHT: WORSE_DEX})
    _arm(table, mid, talent)
    turn(table, mid, RIGHT)
    _, prompts = _settle(lambda answers: act(table, mid, "Cause", answers, target_id=LEFT),
                         lambda prompt: [] if prompt["context"]["reaction_source_id"] in (SAVE_CHOICE, STEP) else
                         [option["id"] for option in prompt["choice"]["options"]][:1])
    assert not any(prompt["context"]["reaction_source_id"] == SAVE_CHOICE for prompt in prompts)
    reload(combat, mid)


def test_unrelated_strength_or_dexterity_save_is_not_asked(tmp_path):
    """(d) an ordinary STR-or-DEX save, with no Soft Capture rider behind it, keeps the better-ability fallback."""
    cause = [{"type": "save", "ability": "STR_OR_DEX", "on_fail": [], "on_success": []}]
    combat, table, mid = _setup(tmp_path, cause=cause, scores={LEFT: WORSE_DEX})
    turn(table, mid, RIGHT)

    def answer_worse(prompt):
        offered = {option["id"] for option in (prompt.get("choice") or {}).get("options", [])}
        return ["DEX"] if {"STR", "DEX"} <= offered else [
            option["id"] for option in (prompt.get("choice") or {}).get("options", [])][:1]
    _, prompts = _settle(lambda answers: act(table, mid, "Cause", answers, target_id=LEFT), answer_worse)
    assert not any(prompt["context"]["reaction_source_id"] == SAVE_CHOICE for prompt in prompts)
    save = _saves(reload(combat, mid), LEFT)[0]
    assert save["modifier"] == 20 and save["reason"].endswith(":STR"), "the engine still takes the better ability"


def test_a_character_without_the_talent_is_unchanged(tmp_path):
    """(e) no Soft Capture owner: the same fight runs with no save-choice checkpoint at all."""
    combat, table, mid = _setup(tmp_path, talents=(HAND,), scores={RIGHT: WORSE_DEX})
    _arm(table, mid, "Hand on the Wrist")
    turn(table, mid, RIGHT)
    _, prompts = _settle(lambda answers: act(table, mid, "Cause", answers, target_id=LEFT),
                         lambda prompt: [] if prompt["context"]["reaction_source_id"] == STEP else
                         [option["id"] for option in prompt["choice"]["options"]][:1])
    assert not any(prompt["context"]["reaction_source_id"] == SAVE_CHOICE for prompt in prompts)
    engine = reload(combat, mid)
    assert not _saves(engine, RIGHT)
    assert any(event.event_type == "PASSIVE_TRIGGERED" and event.source_definition_id == "passive:" + RESPONSE
               for event in engine.events), "the response itself still resolves"
