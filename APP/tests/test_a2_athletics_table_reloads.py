"""A2R23 review regressions: real table commits and fresh service reloads."""
import pytest

from combat import flight, motion, zones
from combat.action_text import describe_action
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from tests.test_a2r23_athletics_map import (
    BREATH, FIGHTER, FLASH_STEP, FOCUS, FOE, ONE_BREATH, ROPE, ROPE_SWING,
    SWING, act, engine_of, events, find, move_to, play, table_fight,
)


KEEP = {"display_name": "Review keep", "width_squares": 12, "height_squares": 8,
        "walls": [{"shape": "rect", "points": [[2, 2], [6, 6]], "filled": False,
                   "blocks": "sight_and_movement", "height_ft": 20}],
        "roofs": {"enabled": True, "height_ft": 20},
        "starts": {"team1": [[4, 4]], "team2": [[4, 5]]}}


def setup(bundles, *, fly=0, climb=0):
    """Seal test setup actions/statistics in genesis; never edit saved state."""
    bundle = next(row for row in bundles if row["actor_id"] == FIGHTER)
    bundle["actor_template"]["fly_speed_ft"] = fly
    bundle["actor_template"]["climb_speed_ft"] = climb
    for key, effects in (
        ("restrain", [{"type": "condition", "condition": "restrained", "applies_to": "self"}]),
        ("clear_afterimage", [{"type": "remove_condition", "condition": motion.AFTERIMAGE,
                               "applies_to": "self"}]),
    ):
        action = ActionDefinition(
            source_definition_id="action:test.review." + key, display_name=key,
            owner_id=FIGHTER, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"free_primary": True, "typed": {"effects": effects, "numbers": {},
                                                        "riders": [], "duration": {"kind": "instant"}}})
        bundle["action_catalog"].append(action.model_dump(mode="json"))
        bundle["actor_template"]["action_ids"].append(action.source_definition_id)


def fresh(combat, mid):
    # _load_session creates a new persistent engine from the on-disk journal.
    return engine_of(combat, mid)


@pytest.mark.parametrize("weapons", [("gong_jian",), ("jian", "fu", "qiang")])
def test_f1_every_native_weapon_delivery_remains_reachable_and_shares_receipt(tmp_path, weapons):
    kit = {"items": [{"item_id": "tianxia.mortal.weapon." + name, "quantity": 1} for name in weapons]}
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH], kit=kit)
    play(table, mid, find(table, mid, ONE_BREATH))
    engine = fresh(combat, mid)
    actions = engine.action_catalog
    native = {row.source_definition_id for row in actions.values()
              if row.owner_id == FIGHTER and row.economy == EconomyKind.ACTION
              and ("#" not in row.source_definition_id or row.source_definition_id.endswith("#thrown"))
              and (row.parameters.get("typed") or {}).get("weapon")
              and any(effect.get("type") == "attack" for effect in
                      (row.parameters.get("typed") or {}).get("effects") or [])}
    strikes = [row for row in actions.values() if row.owner_id == FIGHTER
               and (row.parameters.get("typed") or {}).get("one_breath_strike")
               and (row.parameters.get("typed") or {}).get("delivered_by")]
    assert {row.parameters["typed"]["delivered_by"] for row in strikes} == native
    for row in strikes:
        delivered = actions[row.parameters["typed"]["delivered_by"]].parameters["typed"]
        original = next(effect for effect in delivered["effects"] if effect.get("type") == "attack")
        attack = row.parameters["typed"]["effects"][0]
        assert attack.get("attack_kind") == original.get("attack_kind")
        assert attack.get("on_hit") == original.get("on_hit")
        assert attack["count"] == 1
        assert row.parameters["typed"]["numbers"] == delivered.get("numbers", {})
        assert row.costs == actions[row.parameters["typed"]["delivered_by"]].costs
    assert sum("one_breath_unarmed" in row.source_definition_id for row in strikes) == 1
    groups = table.state(mid)["menu"]["actions"]
    reachable = {group["source_definition_id"] for group in groups if group["options"]}
    native_legal = native & reachable
    legal_strikes = [row for row in strikes if row.parameters["typed"]["delivered_by"] in native_legal]
    assert native_legal and legal_strikes
    assert {row.source_definition_id for row in legal_strikes} <= reachable
    # Carried weapons and improvised objects retain native hand/possession gates.
    # Every delivery exists, and every currently legal native delivery is reachable.
    play(table, mid, find(table, mid, legal_strikes[0].source_definition_id, target=FOE))
    assert str(fresh(combat, mid).state.actors[FIGHTER].turn_flags["athletics_one_breath_strike"]) == "1"
    assert not any("one_breath_strike" in group["source_definition_id"] or
                   "one_breath_unarmed" in group["source_definition_id"]
                   for group in table.state(mid)["menu"]["actions"])


def test_f1_thrown_delivery_is_a_distinct_reachable_attack_beyond_melee(tmp_path):
    map_doc = {"display_name": "Throw range", "width_squares": 12, "height_squares": 12,
               "starts": {"team1": [[4, 4]], "team2": [[4, 10]]}}
    kit = {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 1}]}
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH], kit=kit, map_doc=map_doc,
                                      where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 4, "y": 10}})
    play(table, mid, find(table, mid, ONE_BREATH))
    engine = fresh(combat, mid)
    thrown = [row for row in engine.action_catalog.values()
              if row.owner_id == FIGHTER and
              (row.parameters.get("typed") or {}).get("one_breath_strike") and
              str((row.parameters.get("typed") or {}).get("delivered_by", "")).endswith("#thrown")]
    assert len(thrown) == 1
    assert thrown[0].display_name.endswith("Thrown")
    play(table, mid, find(table, mid, thrown[0].source_definition_id, target=FOE))
    assert str(fresh(combat, mid).state.actors[FIGHTER].turn_flags["athletics_one_breath_strike"]) == "1"


def test_one_breath_excludes_talent_delivery_and_labels_native_choices(tmp_path):
    volley = "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY"
    kit = {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "quantity": 1}]}
    distant = {"display_name": "Beyond Volley", "width_squares": 35, "height_squares": 6,
               "starts": {"team1": [[1, 2]], "team2": [[28, 2]]}}
    combat, table, mid = table_fight(
        tmp_path, [ONE_BREATH, volley], kit=kit, map_doc=distant,
        where={FIGHTER: {"x": 1, "y": 2}, FOE: {"x": 28, "y": 2}})
    play(table, mid, find(table, mid, ONE_BREATH))
    actions = [row for row in fresh(combat, mid).action_catalog.values()
               if row.owner_id == FIGHTER and (row.parameters.get("typed") or {}).get("one_breath_strike")]
    assert actions
    assert all("thousand_spark" not in str((row.parameters.get("typed") or {}).get("delivered_by", "")).lower()
               for row in actions)
    assert len({row.display_name for row in actions}) == len(actions)
    assert all("one weapon attack or Unarmed Strike" in describe_action(row.model_dump(mode="json"))
               for row in actions)
    # The creature is 130 feet away: beyond Thousand-Spark Volley's 120-foot
    # limit, while still within this bow's ordinary 150-foot range. Only its
    # ordinary native attack is granted by One Breath.
    bow_strike = next(row for row in actions
                      if str((row.parameters.get("typed") or {}).get("delivered_by", "")).endswith("gong_jian"))
    assert find(table, mid, bow_strike.source_definition_id, target=FOE)
    assert not any("VOLLEY" in group.get("source_definition_id", "").upper() and
                   any(FOE in option.get("target_ids", []) for option in group.get("options", []))
                   for group in table.state(mid)["menu"]["actions"])


def rope_table(tmp_path, *, hazard=False, climb=0):
    rope_map = {
        "display_name": "Supported rope anchor",
        "width_squares": 12, "height_squares": 8, "walls": [],
        "trees": [{"x": 5, "y": 3, "size": 1, "height_ft": 5,
                   "base_altitude_ft": 0, "occluder": "centerline"}],
        "starts": {"team1": [[4, 4]], "team2": [[4, 5]]},
    }
    def prepare(bundles):
        setup(bundles, climb=climb)
        if not hazard:
            return
        foe = next(bundle for bundle in bundles if bundle["actor_id"] == FOE)
        action = ActionDefinition(
            source_definition_id="action:test.review.hazard", display_name="Review hazard",
            owner_id=FOE, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"free_primary": True, "typed": {
                "effects": [{"type": "zone"}], "source": "test:review.hazard",
                "numbers": {"save_dc": 12, "pb": 2}, "riders": [],
                "duration": {"kind": "instant"}, "zone_spec": {
                    "name": "Review hazard", "cells": [{"x": 4, "y": 4, "z": z} for z in range(4)],
                    "duration": {"kind": "rounds", "amount": 2}, "terrain": [],
                    "move_through": {"min_ft": 0, "ability": "DEX", "on_fail": [
                        {"type": "damage", "applies_to": "target", "flat": 1,
                         "damage_types": ["bludgeoning"]}]}}}})
        foe["action_catalog"].append(action.model_dump(mode="json"))
        foe["actor_template"]["action_ids"].append(action.source_definition_id)
    combat, table, mid = table_fight(
        tmp_path, [ROPE_SWING], kit=ROPE, map_doc=rope_map,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 4, "y": 5}},
        control_modes={FIGHTER: "MANUAL", FOE: "MANUAL"}, bundle_transform=prepare)
    if hazard:
        play(table, mid, table.state(mid)["menu"]["end_turn"])
        play(table, mid, find(table, mid, "review.hazard"))
        play(table, mid, table.state(mid)["menu"]["end_turn"])
    def highest(prompt):
        choice = prompt["choice"]
        option = next(row for row in choice["options"] if row["id"] == "cell:5,3,1")
        return {**prompt["context"], "selection": "USE", "option_ids": [option["id"]]}
    play(table, mid, find(table, mid, ROPE_SWING), answer=highest)
    return combat, table, mid


def test_f2_rope_climb_cannot_spend_raw_feet_with_zero_speed(tmp_path):
    combat, table, mid = rope_table(tmp_path)
    play(table, mid, find(table, mid, "review.restrain"))
    before = fresh(combat, mid).state.actors[FIGHTER]
    assert before.movement_remaining_ft > 0
    play(table, mid, find(table, mid, "rope_swing_climb"))
    after = fresh(combat, mid).state.actors[FIGHTER]
    assert after.position == before.position
    assert after.movement_remaining_ft == before.movement_remaining_ft


def test_f2_rope_climb_opens_leave_reach_opportunity_attack(tmp_path):
    combat, table, mid = rope_table(tmp_path)
    before = len(events(fresh(combat, mid), "ATTACK_ROLLED", FOE))
    play(table, mid, find(table, mid, "rope_swing_climb"))
    engine = fresh(combat, mid)
    assert engine.state.actors[FIGHTER].position.z == 3
    assert len(events(engine, "ATTACK_ROLLED", FOE)) > before
    move = events(engine, "MOVEMENT_COMMITTED", FIGHTER)[-1]
    assert len(move.payload["path"]) == 4 and move.payload["cost_ft"] == 15


def test_f2_rope_climb_runs_hazard_and_willing_zone_checkpoints(tmp_path, monkeypatch):
    calls = []
    original = zones.on_step
    def observe(engine, actor, start, end, **kwargs):
        if actor.entity_id == FIGHTER:
            calls.append((start, end, kwargs.get("forced", False)))
        return original(engine, actor, start, end, **kwargs)
    monkeypatch.setattr(zones, "on_step", observe)
    combat, table, mid = rope_table(tmp_path, hazard=True)
    before = len(events(fresh(combat, mid), "SAVE_ROLLED", FIGHTER))
    play(table, mid, find(table, mid, "rope_swing_climb"))
    engine = fresh(combat, mid)
    assert calls and all(not forced for _, _, forced in calls)
    assert len(events(engine, "SAVE_ROLLED", FIGHTER)) > before


def test_f2_rope_climb_retains_native_climb_allowance_after_walking_is_spent(tmp_path):
    combat, table, mid = rope_table(tmp_path, climb=60)
    route(table, mid, [{"x": x, "y": y} for x, y in
                     [(4, 4), (3, 4), (3, 3), (4, 3), (5, 3), (5, 4), (4, 4)]])
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert actor.movement_remaining_ft == 0
    assert flight.remaining(engine, actor, "climb") == 30
    play(table, mid, find(table, mid, "rope_swing_climb"))
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert actor.position == Position(x=4, y=4, z=3)
    assert flight.remaining(engine, actor, "climb") == 15


@pytest.mark.parametrize("decline", [False, True])
@pytest.mark.parametrize("boost", [False, True])
def test_f3_replaced_dash_does_not_create_fly_or_climb_allowance(tmp_path, decline, boost):
    talents = [FLASH_STEP, *(["TAL_ATHLETICS_SPEED_BOOST"] if boost else [])]
    combat, table, mid = table_fight(tmp_path, talents,
        bundle_transform=lambda bundles: setup(bundles, fly=60))
    before = fresh(combat, mid)
    actor = before.state.actors[FIGHTER]
    assert FIGHTER in before.typed_ask_reactors, {
        "modes": before.typed_control_modes,
        "inline": {aid: (row.parameters.get("typed") or {}).get("manual_inline_choice")
                   for aid, row in before.action_catalog.items() if "flash_step" in aid}}
    allowance = flight.remaining(before, actor, "fly")
    assert flight.dash_reach(before, actor) == 60 + (10 if boost else 0)
    start = actor.position
    answer = (lambda prompt: {**prompt["context"], "selection": "DECLINE"}) if decline else None
    _, prompts = play(table, mid, find(table, mid, "flash_step"), answer=answer)
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert flight.remaining(engine, actor, "fly") == allowance
    assert actor.movement_remaining_ft == 30
    assert not actor.turn_flags.get("flight_typed_dashes")
    assert prompts, "the manual owner must actually receive the landing decision"
    assert (actor.position == start) == decline, prompts


def route(table, mid, path, *, mode="walk"):
    menu = table.state(mid)["menu"]
    quote = table.preview_move_path(mid, menu["decision_id"], menu["state_version"], FIGHTER,
                                   path, movement_mode=mode)
    answers = []
    for _ in range(20):
        result = table.commit_move_path(mid, quote["candidate"]["candidate_id"], menu["decision_id"],
            menu["state_version"], FIGHTER, path, movement_mode=mode, reactions=answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    raise AssertionError("route did not commit")


def test_f4_afterimage_real_repeated_trigger_is_limited_after_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH, "TAL_ATHLETICS_AFTERIMAGE"],
                                   bundle_transform=setup)
    play(table, mid, find(table, mid, ONE_BREATH))
    route(table, mid, [{"x": x, "y": 4} for x in range(3, 9)])
    engine = fresh(combat, mid)
    assert motion.has_afterimage(engine.state.actors[FIGHTER])
    assert athletics_receipt(engine, "TAL_ATHLETICS_AFTERIMAGE")
    play(table, mid, find(table, mid, "review.clear_afterimage"))
    assert not motion.has_afterimage(fresh(combat, mid).state.actors[FIGHTER])
    route(table, mid, [{"x": 8, "y": 4}, {"x": 9, "y": 4}])
    assert not motion.has_afterimage(fresh(combat, mid).state.actors[FIGHTER])


def athletics_receipt(engine, owner):
    from combat.ext.athletics import motion_applied_once
    return motion_applied_once(engine, engine.state.actors[FIGHTER], owner)


def test_f4_flash_step_real_action_records_motion_after_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH, FLASH_STEP])
    play(table, mid, find(table, mid, ONE_BREATH))
    play(table, mid, move_to(table, mid, 7, 7))  # restore the Focus Flash Step pays
    play(table, mid, find(table, mid, "flash_step"))
    assert athletics_receipt(fresh(combat, mid), FLASH_STEP)


def test_f4_sudden_flank_real_crossing_cannot_grant_again_after_reload(tmp_path):
    flank = "TAL_ATHLETICS_SUDDEN_FLANK"
    def prepare(bundles):
        setup(bundles)
        for bundle in bundles:
            score = 60 if bundle["actor_id"] == FIGHTER else 0
            bundle.setdefault("skills", {})["Acrobatics"] = score
            bundle["actor_template"].setdefault("skills", {})["Acrobatics"] = score
        owner = next(bundle for bundle in bundles if bundle["actor_id"] == FIGHTER)
        # Seal one extra test-only Tumble to exercise a repeated trigger in the
        # same activation. The ordinary first contest still pays its Action.
        native = next(ActionDefinition.model_validate(row) for row in owner["action_catalog"]
                      if row["source_definition_id"].endswith(".tumble.action"))
        extra = native.model_copy(deep=True, update={"source_definition_id": "action:test.review.extra_tumble",
                                                    "economy": EconomyKind.NONE})
        extra.parameters["free_primary"] = True
        owner["action_catalog"].append(extra.model_dump(mode="json"))
        owner["actor_template"]["action_ids"].append(extra.source_definition_id)
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH, flank], bundle_transform=prepare)
    play(table, mid, find(table, mid, ONE_BREATH))
    play(table, mid, find(table, mid, ".tumble.action", target=FOE))
    route(table, mid, [{"x": 3, "y": 4}, {"x": 4, "y": 4}, {"x": 5, "y": 4}])
    engine = fresh(combat, mid)
    assert athletics_receipt(engine, flank)
    grants = [event for event in events(engine, "MODIFIER_APPLIED", FIGHTER)
              if event.source_definition_id == flank]
    assert len(grants) == 1
    play(table, mid, find(table, mid, "one_breath_unarmed", target=FOE))
    play(table, mid, find(table, mid, "review.extra_tumble", target=FOE))
    route(table, mid, [{"x": 5, "y": 4}, {"x": 4, "y": 4}, {"x": 3, "y": 4}])
    engine = fresh(combat, mid)
    assert len([event for event in events(engine, "MODIFIER_APPLIED", FIGHTER)
                if event.source_definition_id == flank]) == 1


def test_f5_hostile_crossing_commits_double_cost_and_cannot_end_on_foe(tmp_path):
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH])
    play(table, mid, find(table, mid, ONE_BREATH))
    route(table, mid, [{"x": 3, "y": 4}, {"x": 4, "y": 4}, {"x": 5, "y": 4}])
    engine = fresh(combat, mid)
    event = events(engine, "MOVEMENT_COMMITTED", FIGHTER)[-1]
    assert event.payload["cost_ft"] == 15
    assert engine.state.actors[FIGHTER].position == Position(x=5, y=4)
    menu = table.state(mid)["menu"]
    with pytest.raises(Exception):
        table.preview_move_path(mid, menu["decision_id"], menu["state_version"], FIGHTER,
                                [{"x": 5, "y": 4}, {"x": 4, "y": 4}])


def test_f5_flash_step_actually_restores_focus_without_intervening_spaces(tmp_path):
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH, FLASH_STEP])
    play(table, mid, find(table, mid, ONE_BREATH))
    play(table, mid, move_to(table, mid, 7, 7))
    start = fresh(combat, mid).state.actors[FIGHTER].position
    def distant(prompt):
        options = prompt["choice"]["options"]
        chosen = next(row for row in options if row["id"] == "cell:3,7")
        return {**prompt["context"], "selection": "USE", "option_ids": [chosen["id"]]}
    _, prompts = play(table, mid, find(table, mid, "flash_step"), answer=distant)
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert actor.position == Position(x=3, y=7), prompts
    assert actor.resources[FOCUS] == 1
    event = events(engine, "MOVEMENT_COMMITTED", FIGHTER)[-1]
    assert event.payload.get("teleport") and len(event.payload["path"]) == 2
    assert Position(**event.payload["path"][0]) == start
