"""Equipment second-pass regressions through journalled service transactions."""
from copy import deepcopy
from importlib import import_module

import pytest

from combat.gate5_service import CombatService
from combat import posture

support = import_module("tests.test_review_sw-equipment")
T = support.T
AREA = "action:test.a2equipment.area"
PREPARE = "action:test.a2equipment.prone"
ZONE = "action:test.a2equipment.zone"


def area_action(bundle, *, ability="dex", dc=100, area=True, nested=False,
                split=False, caster=support.ATTACKER):
    if bundle["actor_id"] != caster:
        return
    damage = {"type": "damage", "applies_to": "target", "flat": 40,
              "damage_types": ["force"]}
    save = {"type": "save", "ability": ability,
            "applies_to": "enemies_in_area" if area else "target",
            "on_fail": [damage], "on_success": [deepcopy(damage)]}
    if split:
        save["on_fail"] = [{**damage, "flat": 1, "damage_types": ["cold"]}, damage]
    effects = [save]
    if nested:
        # A later unsaved packet in the same area action is not the save's damage.
        effects.append(deepcopy(damage))
    typed = {"numbers": {"cl": 18, "pb": 6, "save_dc": dc},
             "effects": effects, "duration": {"kind": "instant"}, "riders": []}
    if area:
        typed["area"] = {"shape": "sphere", "size_ft": 30}
    if caster == support.DEFENDER:
        typed["area"].update(include_self=True, recipients="all")
        save["applies_to"] = "creatures_in_area"
    support._bundle_action(bundle, AREA, "Equipment test blast",
                           {"expected_damage": 40, "typed": typed},
                           target_kind="SELF" if area else "HOSTILE_ENTITY",
                           range_ft=None if area else 60)
    support._seal(bundle)


def reaction_receipts(engine):
    return [e for e in engine.events if e.event_type == "REACTION_RESOLVED"
            and e.source_definition_id == T + "iron_rain_readiness"]


@pytest.mark.parametrize("use", [True, False])
def test_iron_rain_combines_with_halo_table_reload_replay(tmp_path, use):
    """Both printed reductions apply, with one paid response to the area save."""
    halo = "action:test.a2equipment.halo"

    def prepare(bundle):
        area_action(bundle)
        if bundle["actor_id"] == support.ATTACKER:
            bundle["actor_template"]["creature_types"] = ["Undead"]
        else:
            support._bundle_action(bundle, halo, "Halo of the Merciful Sovereign",
                                   {"typed": {"numbers": {"pb": 6}, "riders": [],
                                    "duration": {"kind": "rounds", "amount": 10},
                                    "effects": [{"type": "radiance_state", "kind": "merciful_halo",
                                                 "label": "Halo of the Merciful Sovereign",
                                                 "applies_to": "self"}]}},
                                   target_kind="SELF", range_ft=None)
        support._seal(bundle)

    combat, table, mid = support._table(tmp_path, ["iron_rain_readiness"],
                                     prepare=prepare, turn=support.DEFENDER)
    support._commit(combat, table, mid, halo, actor=support.DEFENDER)
    from combat.ext.radiance_states import states
    from combat.ext.creature_kinds import is_unclean
    before = support._reload(tmp_path, mid)
    defender = before.state.actors[support.DEFENDER]
    assert states(defender, "merciful_halo")
    assert is_unclean(before.state.actors[support.ATTACKER])
    prompts = support._commit(combat, table, mid, AREA,
                              answer=lambda p: ["use"] if use else None)
    engine = support._reload(tmp_path, mid)  # fresh service + mechanical replay PASS
    actor = engine.state.actors[support.DEFENDER]
    receipts = reaction_receipts(engine)
    assert len(prompts) == 1
    assert len(receipts) == int(use)
    reduction = next((r.total for r in engine.rolls
                      if r.reason == f"DAMAGE_REDUCTION:{T}iron_rain_readiness"), 0)
    expected = max(0, 40 - 6 - reduction)
    assert support._packets(engine, AREA)[0].payload["hp_damage"] == expected
    assert defender.current_hp - actor.current_hp == expected
    assert actor.resources["resource:core.qi"] == defender.resources["resource:core.qi"] - 2 * int(use)
    assert actor.reaction_available == (not use)


@pytest.mark.parametrize("case", ["use", "decline", "success", "con", "single", "unowned"])
def test_iron_rain_failed_area_save_service_reload(tmp_path, case):
    combat, table, mid = support._table(
        tmp_path, [] if case == "unowned" else ["iron_rain_readiness"],
        prepare=lambda b: area_action(b, ability="con" if case == "con" else "dex",
                                    dc=1 if case == "success" else 100,
                                    area=case != "single"))
    before = support._reload(tmp_path, mid).state.actors[support.DEFENDER]
    prompts = support._commit(combat, table, mid, AREA,
                              answer=lambda p: ["use"] if case != "decline" else None)
    engine = support._reload(tmp_path, mid)
    actor = engine.state.actors[support.DEFENDER]
    packets = support._packets(engine, AREA)
    assert len(packets) == 1
    receipts = reaction_receipts(engine)
    if case == "use":
        assert len(receipts) == 1
        reduction = receipts[0].payload["reduction"]
        rolled = next(r for r in engine.rolls
                      if r.reason == f"DAMAGE_REDUCTION:{T}iron_rain_readiness")
        assert len(rolled.dice) == 2 and all(1 <= die <= 8 for die in rolled.dice)
        assert rolled.modifier == actor.proficiency_bonus
        assert reduction == sum(rolled.dice) + actor.proficiency_bonus
        assert packets[0].payload["hp_damage"] == 40 - reduction
        assert actor.resources["resource:core.qi"] == before.resources["resource:core.qi"] - 2
        assert not actor.reaction_available
        assert prompts and "Iron Rain Readiness" in str(prompts)
        assert "Equipment test blast" in str(prompts)
    else:
        assert not receipts
        assert packets[0].payload["hp_damage"] == 40
        assert actor.resources == before.resources
        assert actor.reaction_available
    assert engine.damage_context() is None
    from combat.save_context import damage_save
    assert damage_save(combat._load_session(mid).engine, support.DEFENDER, AREA, support.ATTACKER) is None


def test_iron_rain_reduction_does_not_leak_to_later_area_damage(tmp_path):
    combat, table, mid = support._table(tmp_path, ["iron_rain_readiness"],
                                     prepare=lambda b: area_action(b, nested=True))
    support._commit(combat, table, mid, AREA, answer=lambda p: ["use"])
    engine = support._reload(tmp_path, mid)
    packets = support._packets(engine, AREA)
    assert len(packets) == 2
    assert packets[0].payload["hp_damage"] < 40
    assert packets[1].payload["hp_damage"] == 40
    assert len(reaction_receipts(engine)) == 1


@pytest.mark.parametrize("case", ["split", "split_decline", "legacy", "ai", "own_turn"])
def test_iron_rain_scope_and_control_service_reload(tmp_path, case):
    def prepare(bundle):
        area_action(bundle, split=case.startswith("split"),
                    caster=support.DEFENDER if case == "own_turn" else support.ATTACKER)
        if case == "legacy" and bundle["actor_id"] == support.DEFENDER:
            bundle["typed_passives"][:] = [r for r in bundle["typed_passives"]
                                          if r.get("kind") != "iron_rain_area"]
            support._seal(bundle)
    combat, table, mid = support._table(tmp_path, ["iron_rain_readiness"], prepare=prepare,
                        turn=support.DEFENDER if case == "own_turn" else support.ATTACKER)
    if case == "ai":
        combat.set_controller_mode(mid, actor_id=support.DEFENDER, controller_mode="LOCAL_AUTO")
    prompts = support._commit(combat, table, mid, AREA,
              actor=support.DEFENDER if case == "own_turn" else support.ATTACKER,
              answer=lambda p: None if case == "split_decline" else ["use"])
    engine = support._reload(tmp_path, mid)
    packets = [e for e in support._packets(engine, AREA) if support.DEFENDER in e.target_ids]
    receipts = reaction_receipts(engine)
    if case in {"legacy", "split_decline"}:
        assert not receipts
        assert sum(p.payload["hp_damage"] for p in packets) == (41 if case == "split_decline" else 40)
        if case == "split_decline":
            assert len(prompts) == 1, "declining one save's guard must not re-ask for its second damage component"
    else:
        assert len(receipts) == 1
        reduction_roll = next(r for r in engine.rolls
                              if r.reason == f"DAMAGE_REDUCTION:{T}iron_rain_readiness")
        assert sum(p.payload["hp_damage"] for p in packets) == (41 if case == "split" else 40) - reduction_roll.total
        assert engine.state.actors[support.DEFENDER].resources["resource:core.qi"] == 58
        if case == "ai":
            assert not prompts, "the AI defender decides automatically on the player's turn"


def prone_action(bundle):
    if bundle["actor_id"] != support.DEFENDER:
        return
    support._bundle_action(bundle, PREPARE, "Lie down",
                           {"typed": {"numbers": {}, "riders": [],
                            "duration": {"kind": "instant"},
                            "effects": [{"type": "condition", "condition": "prone",
                                         "applies_to": "self"}]}},
                           target_kind="SELF", range_ft=None)
    support._seal(bundle)


def standing_area(bundle):
    if bundle["actor_id"] != support.ATTACKER:
        return
    save = {"type": "save", "ability": "dex", "applies_to": "target",
            "on_fail": [{"type": "damage", "applies_to": "target", "flat": 40,
                         "damage_types": ["force"]}], "on_success": []}
    spec = {"name": "Equipment test hazard", "shape": "sphere", "size_ft": 30,
            "duration": {"kind": "rounds", "amount": 2},
            "triggers": [{"id": "trigger:test.a2equipment.zone",
                          "name": "Hazard at turn start", "on": ["start"], "who": "hostile",
                          "effects": [save]}]}
    support._bundle_action(bundle, ZONE, "Equipment test hazard",
                           {"typed": {"numbers": {"cl": 18, "pb": 6, "save_dc": 100},
                                      "effects": [], "zone_spec": spec,
                                      "duration": {"kind": "instant"}, "riders": []}},
                           target_kind="SELF", range_ft=None)
    support._seal(bundle)


@pytest.mark.parametrize("case", ["use", "decline", "unowned"])
def test_iron_rain_standing_area_save_service_reload(tmp_path, case):
    combat, table, mid = support._table(tmp_path, [] if case == "unowned" else ["iron_rain_readiness"],
                                     prepare=standing_area)
    support._commit(combat, table, mid, ZONE)
    # The area itself persists before the defender begins their turn in it.
    assert support._reload(tmp_path, mid).state.zones
    decisions, prompts = [], []
    for _ in range(8):
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], decisions)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result["status"]
        prompt = result["reaction"]
        prompts.append(prompt)
        decisions.append({**prompt["context"], "selection": "DECLINE" if case == "decline" else "USE",
                          "option_ids": [] if case == "decline" else ["use"]})
    else:
        raise AssertionError("the turn-start area guard did not finish")
    engine = support._reload(tmp_path, mid)
    packets = support._packets(engine, ZONE)
    assert len(packets) == 1, "the recorded area really delivered its save and damage"
    if case == "use":
        assert prompts and len(reaction_receipts(engine)) == 1
        assert packets[0].payload["hp_damage"] < 40
        assert engine.state.actors[support.DEFENDER].resources["resource:core.qi"] == 58
    else:
        assert not reaction_receipts(engine)
        assert packets[0].payload["hp_damage"] == 40
        assert engine.state.actors[support.DEFENDER].resources["resource:core.qi"] == 60


@pytest.mark.parametrize("owned", [True, False])
def test_breath_aligned_armor_standing_service_reload(tmp_path, owned):
    combat, table, mid = support._table(tmp_path, ["breath_aligned_armor"] if owned else [],
                                     prepare=prone_action, turn=support.DEFENDER)
    support._commit(combat, table, mid, PREPARE, actor=support.DEFENDER)
    session = CombatService(support.ROOT, tmp_path)._load_session(mid)
    actor = session.engine.state.actors[support.DEFENDER]
    cost = 5 if owned else 15
    assert posture.standing_cost(session.engine, actor) == cost
    before = actor.movement_remaining_ft
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.source_definition_id == posture.SOURCE)
    from combat.gate2_runtime_models import ActionIntent
    session.mechanical.execute_intent(ActionIntent(intent_id="intent:a2equipment.stand",
                                                  decision_id=candidate.decision_id,
                                                  state_version=session.engine.state.state_version,
                                                  actor_id=actor.entity_id,
                                                  candidate_id=candidate.candidate_id))
    engine = support._reload(tmp_path, mid)
    actor = engine.state.actors[support.DEFENDER]
    assert not posture.prone_conditions(actor)
    assert actor.movement_remaining_ft == before - cost


def test_iron_rain_map_area_save_service_reload(tmp_path):
    """Map hazards have an actual delivery action outside the action catalogue."""
    from combat.factory_compiler import compile_character
    from combat.tabletop_service import TabletopService
    bundles = []
    for aid in (support.ATTACKER, support.DEFENDER):
        sheet = support._sheet(["iron_rain_readiness"] if aid == support.DEFENDER else [], cl=18,
                               name="Area attacker" if aid == support.ATTACKER else "Iron Rain fighter")
        bundles.append(compile_character(sheet, actor_id=aid,
                                         reaction_plan={"mode": "ask", "ask": aid == support.DEFENDER}))
    combat = CombatService(support.ROOT, tmp_path)
    arena = deepcopy(combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"])
    arena["map_terrain"] = [{"terrain": "fire terrain", "cells": [[3, 6]],
                             "save_dc": 100, "pb": 40}]
    mid = combat._finish_factory_match(
        bundles, [support.ATTACKER, support.DEFENDER],
        {support.ATTACKER: "team:opponents", support.DEFENDER: "team:factory"},
        {support.ATTACKER: {"x": 8, "y": 6}, support.DEFENDER: {"x": 3, "y": 6}},
        arena, [support.DEFENDER], [support.ATTACKER],
        control_modes={support.ATTACKER: "MANUAL", support.DEFENDER: "MANUAL"},
        match_seed="AUTO68", display_name="Equipment map-area regression", maximum_rounds=6)["match_id"]
    table = TabletopService(combat, tmp_path)
    assert table.state(mid)["menu"]["actor_id"] == support.ATTACKER
    assert "system:battlefield.terrain" not in support._reload(tmp_path, mid).action_catalog
    decisions, prompts = [], []
    for _ in range(8):
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], decisions)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result["status"]
        prompt = result["reaction"]
        prompts.append(prompt)
        decisions.append({**prompt["context"], "selection": "USE", "option_ids": ["use"]})
    else:
        raise AssertionError("map-area defense did not finish")
    engine = support._reload(tmp_path, mid)
    packets = support._packets(engine, "system:battlefield.terrain")
    assert len(packets) == 1 and packets[0].payload["hp_damage"] < 40
    assert len(reaction_receipts(engine)) == 1
    assert engine.state.actors[support.DEFENDER].resources["resource:core.qi"] == 58
    assert "Map terrain" in str(prompts)
