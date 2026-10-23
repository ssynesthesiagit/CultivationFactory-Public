"""Return the Mountain uses Flowing Response's committed attack at table level."""
import json
from pathlib import Path

from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, turn
from tests.hunt15_support import reload as load_engine
from tests.test_auto2_flowing_river import P, FOCUS, settle, decline_steps

RETURN = P + "RETURN_THE_MOUNTAIN_TO_THE_MOUNTAIN"
BEND = P + "BEND_THE_BLADE"
RESPONSE = P + "FLOWING_RESPONSE"
TARGET_CHOICE = "choice:needle.river_bend_target"


def _sheet_ac(doc, actor_id):
    if actor_id in (LEFT, RIGHT):
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 200


def _attack_bonus(value):
    def edit(bundle):
        for action in bundle["action_catalog"]:
            if action.get("owner_id") == RIGHT and ".weapon." in action.get("source_definition_id", ""):
                typed = action.setdefault("parameters", {}).setdefault("typed", {})
                typed.setdefault("numbers", {})["attack_bonus"] = value
                action["attack_bonus"] = value
    return edit


def _fight(tmp_path, *, bonus, wall=False, owner=True, positions=None):
    def arena(data):
        if wall:
            data["terrain_regions"] = [{"region_id": "return-mountain-sealed-wall",
                "terrain_type": "BLOCKED", "movement_cost": 0,
                "cells": [{"x": 6, "y": y} for y in range(15)]}]
    talents = [RESPONSE, BEND, *([RETURN] if owner else [])]
    return fight(tmp_path, talents, left_score=50, sheet_edit=_sheet_ac,
                 bundle_edit=_attack_bonus(bonus), spheres=["tianxia.sphere.flowing_river"],
                 positions=positions or {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, ALLY: {"x": 9, "y": 6}},
                 arena_edit=arena, ally=())


def _choose_return(table, match_id):
    turn(table, match_id, LEFT)
    settle(lambda answers: act(table, match_id, "Flowing Response: Return the Mountain to the Mountain", answers),
           decline_steps)


def _attack(table, match_id, answers=(), *, target_id=LEFT):
    try:
        return act(table, match_id, ".weapon.bi_shou", answers, target_id=target_id)
    except Exception as exc:
        raise AssertionError(f"table attack failed: {exc!r}; details={getattr(exc, '__dict__', {})!r}") from exc


def test_return_mountain_reuses_attack_roll_for_target_beyond_melee_reach(tmp_path):
    combat, table, match_id = _fight(tmp_path, bonus=100)
    engine = load_engine(combat, match_id)
    assert "Flowing Response: Return the Mountain to the Mountain" in {
        row.display_name for row in engine.action_catalog.values()
    }
    _choose_return(table, match_id)
    turn(table, match_id, RIGHT)
    before = load_engine(combat, match_id)
    focus_before = before.state.actors[LEFT].resources[FOCUS]
    ally_hp = before.state.actors[ALLY].current_hp
    assert before._distance_actor_to_actor(before.state.actors[LEFT], before.state.actors[ALLY]) == 30
    assert before._distance_actor_to_actor(before.state.actors[RIGHT], before.state.actors[ALLY]) > 5

    def pick(prompt):
        if prompt["context"].get("reaction_source_id") == TARGET_CHOICE:
            return [ALLY]
        return decline_steps(prompt)

    _, prompts = settle(lambda answers: _attack(table, match_id, answers), pick)
    target_prompt = next(p for p in prompts if p["context"].get("reaction_source_id") == TARGET_CHOICE)
    after = load_engine(combat, match_id)
    redirected = [e for e in after.events if e.event_type == "PASSIVE_TRIGGERED"
                  and e.source_definition_id == "passive:" + RETURN]
    assert len(redirected) == 1 and redirected[0].target_ids == (RIGHT, ALLY)
    assert redirected[0].payload["hit"] is True
    assert ALLY in [o["id"] for o in target_prompt["choice"]["options"]]
    assert after.state.actors[LEFT].resources[FOCUS] == focus_before - 1
    assert after.state.actors[ALLY].current_hp < ally_hp
    assert len([e for e in after.events if e.event_type == "ATTACK_ROLLED"]) == len(
        [e for e in before.events if e.event_type == "ATTACK_ROLLED"]) + 1


def test_return_mountain_miss_damage_and_total_cover_filter_survive_reload(tmp_path):
    combat, table, match_id = _fight(tmp_path, bonus=-100, wall=True)
    _choose_return(table, match_id)
    turn(table, match_id, RIGHT)
    before = load_engine(combat, match_id)
    focus_before = before.state.actors[LEFT].resources[FOCUS]
    attacker_hp = before.state.actors[RIGHT].current_hp

    def pick(prompt):
        if prompt["context"].get("reaction_source_id") == TARGET_CHOICE:
            return [RIGHT]
        return decline_steps(prompt)

    _, prompts = settle(lambda answers: _attack(table, match_id, answers), pick)
    target_prompt = next(p for p in prompts if p["context"].get("reaction_source_id") == TARGET_CHOICE)
    after = load_engine(combat, match_id)
    missed = [e for e in after.events if e.event_type == "PASSIVE_TRIGGERED"
              and e.source_definition_id == "passive:" + RETURN]
    assert len(missed) == 1 and missed[0].target_ids == (RIGHT, RIGHT)
    assert missed[0].payload["hit"] is False
    assert ALLY not in [o["id"] for o in target_prompt["choice"]["options"]]
    assert after.state.actors[LEFT].resources[FOCUS] == focus_before - 1
    assert after.state.actors[RIGHT].current_hp == attacker_hp - 4


def test_return_mountain_decline_and_nonowner_preserve_focus_and_options(tmp_path):
    combat, table, match_id = _fight(tmp_path / "decline", bonus=-100)
    _choose_return(table, match_id)
    turn(table, match_id, RIGHT)
    before = load_engine(combat, match_id)
    focus_before = before.state.actors[LEFT].resources[FOCUS]

    def decline(prompt):
        if prompt["context"].get("reaction_source_id") == TARGET_CHOICE:
            return []
        return decline_steps(prompt)

    settle(lambda answers: _attack(table, match_id, answers), decline)
    after = load_engine(combat, match_id)
    assert after.state.actors[LEFT].resources[FOCUS] == focus_before
    assert not any(e.source_definition_id == "passive:" + RETURN for e in after.events)

    nonowner, _, nonowner_id = _fight(tmp_path / "nonowner", bonus=-100, owner=False)
    names = {row.display_name for row in load_engine(nonowner, nonowner_id).action_catalog.values()}
    assert "Flowing Response: Return the Mountain to the Mountain" not in names


def test_ai_uses_owned_return_mountain_and_compiled_record_is_reconciled(tmp_path):
    combat, table, match_id = _fight(tmp_path, bonus=-100)
    turn(table, match_id, LEFT)
    turn(table, match_id, RIGHT)
    combat.set_controller_mode(match_id, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    result = _attack(table, match_id)
    assert result["status"] == "COMMITTED", result
    after = load_engine(combat, match_id)
    assert any(e.source_definition_id == "passive:" + RETURN for e in after.events)

    authority_path = Path(__file__).parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    record = json.loads(authority_path.read_text())["mechanics"][RETURN]
    assert record["coverage"] == "FULL" and record["riders"] == []
    assert record["effects"][0]["on_miss"][0]["formula"] == "pb"
    assert record["effects"][0]["on_miss"][0]["damage_types"] == ["bludgeoning"]
