"""Public synthetic table fights for granted move-before-attack activation."""
import json
import zipfile
from pathlib import Path

import pytest

from combat import ext
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.ext import move_attack
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
CHARGE = "TAL_SPEAR_DRAGON_SPEAR_CHARGE"
FLOWERS = "TAL_SPEAR_FLOWERS_IN_THE_STORM"
LEFT, FOE, BLOCKER = (FACTORY_ACTOR_PREFIX + name for name in ("charger", "target", "blocker"))
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang",
                                  "name": "Qiang (Spear)", "quantity": 1}]}}


@pytest.fixture(autouse=True)
def deterministic_hits_and_failed_saves(monkeypatch):
    ext._load()
    def rewrite(engine, roll, intent):
        return {"source_id": "test:charge-roll", "operation": "replace",
                "natural_result": 19 if roll.actor_id == LEFT else 1}
    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", ()), rewrite])


def fixture(tmp_path, *, distance=15, blocker=False, corridor=False, wall=False, rough=False,
            talents=None):
    names = ["charger", "target"] + (["blocker"] if blocker else [])
    for name in names:
        document = sheet((talents or [CHARGE, FLOWERS]) if name == "charger" else [], cl=17 if talents else 5,
                         kit=KIT, primary="Stamina", score=14)
        document["identity"]["display_name"] = name.title()
        stats = document["ability_scores_and_statistics"]
        stats["technique_attack_bonus"] = 40
        stats["hit_points"]["maximum"] = 500
        if name != "charger":
            for ability in stats["abilities"]:
                ability.update(score=1, modifier=-5)
        folder = tmp_path / "portable_characters" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    walls = ([{"shape": "rect", "points": [[0, 0], [12, 1]], "filled": True},
              {"shape": "rect", "points": [[0, 2], [12, 4]], "filled": True}] if corridor else [])
    if wall:
        walls.append({"shape": "rect", "points": [[3, 0], [4, 4]], "filled": True})
    combat.tabletop_maps.save({"display_name": "Charge yard", "width_squares": 12, "height_squares": 4,
        "walls": walls, "terrain": [{"type": "DIFFICULT", "cells": [[2, 1], [3, 1]]}] if rough else [],
        "starts": {"team1": [[1, 1]], "team2": [[1 + distance // 5, 1]] + ([[2, 1]] if blocker else [])}})
    mid = combat.create_factory_match(project_ids=["charger"], opponent_actor_ids=[FOE] + ([BLOCKER] if blocker else []),
        control_modes={FACTORY_ACTOR_PREFIX + name: "MANUAL" for name in names},
        arena_id="battlefield:map.charge-yard", match_seed="CHARGEMOVE1")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        state = table.state(mid)
        if state["menu"]["actor_id"] == LEFT:
            break
        menu = state["menu"]
        engine = combat._load_session(mid).engine
        end = next(c for c in engine.legal_candidates() if c.kind.value == "END_TURN")
        result = table.act(mid, end.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED", result
    else:
        pytest.fail("charger turn never began")
    return combat, table, mid


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def charge_candidate(engine):
    return next((c for c in engine.legal_candidates()
                 if CHARGE in c.source_definition_id and c.target_ids == (FOE,)), None)


def cast(combat, table, mid, *, attack_cell="cell:3,1", finish_cell=None, save_choice="Knock Prone"):
    state = table.state(mid)
    candidate = charge_candidate(combat._load_session(mid).engine)
    assert candidate is not None
    answers, prompts = [], []
    for _ in range(15):
        result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]; prompts.append(prompt)
        source = prompt["context"]["reaction_source_id"]
        options = prompt.get("choice", {}).get("options", [])
        ids = [o["id"] for o in options]
        if source.endswith("move_attack_attack"):
            picked = attack_cell
            assert "Dragon-Spear Charge" in str(prompt)
            assert "Target" in str(prompt)
        elif source.endswith("move_attack_finish"):
            picked = finish_cell or attack_cell
        elif options:
            picked = next((o["id"] for o in options if save_choice.lower() in o["label"].lower()), ids[0])
        else:
            picked = None
        assert picked is None or picked in ids, (source, picked, options)
        answer = {**prompt["context"], "selection": "USE"}
        if picked is not None:
            answer["option_ids"] = [picked]
        answers.append(answer)
        # Pauses are transactional, including the earlier move and CP payment.
        assert combat._load_session(mid).engine.state.actors[LEFT].position.x == 1
    pytest.fail("Charge did not settle")


def test_charge_is_offered_at_fifteen_feet_but_flowers_is_not(tmp_path):
    combat, _, mid = fixture(tmp_path)
    engine = cold(tmp_path, mid)
    assert charge_candidate(engine) is not None
    assert not any(FLOWERS in c.source_definition_id for c in engine.legal_candidates())


@pytest.mark.parametrize("distance,wall", [(40, False), (15, True)])
def test_charge_is_not_offered_beyond_its_grant_or_through_a_sealed_wall(tmp_path, distance, wall):
    combat, _, mid = fixture(tmp_path, distance=distance, wall=wall)
    engine = cold(tmp_path, mid)
    assert charge_candidate(engine) is None


def test_charge_moves_attacks_and_finishes_movement_through_commit_and_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path)
    before = cold(tmp_path, mid)
    actor = before.state.actors[LEFT]
    movement, stamina = actor.movement_remaining_ft, actor.resources["resource:core.stamina"]
    cast(combat, table, mid, finish_cell="cell:6,1")
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[LEFT]
    assert (actor.position.x, actor.position.y) == (6, 1)
    assert actor.movement_remaining_ft == movement
    assert actor.resources["resource:core.stamina"] == stamina - 3
    assert not actor.action_available
    assert engine.state.actors[FOE].current_hp < 500
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and CHARGE in e.source_definition_id]
    assert len(attacks) == 1
    assert engine.state.actors[FOE].reaction_available, "leaving its reach must not provoke"
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[FOE].position.x == 4, "failed save chooses Prone instead of also pushing"
    moves = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == LEFT]
    assert len(moves) >= 2
    assert not any(e.event_type == "OPPORTUNITY_ATTACK_DECLARED" for e in engine.events)


def test_one_hostile_space_is_double_cost_and_rough_ground_is_ignored(tmp_path):
    combat, table, mid = fixture(tmp_path, blocker=True, corridor=True, rough=True)
    engine = cold(tmp_path, mid)
    actor, target = engine.state.actors[LEFT], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and CHARGE in a.source_definition_id)
    row = move_attack.movement_row(action)
    weapon = next(iter(move_attack.legal_weapons(engine, actor, target, action, row).values()))
    options = move_attack.attack_routes(engine, actor, target, action, row, weapon)
    destination = next(p for p in options if (p.x, p.y) == (3, 1))
    path, cost, through = options[destination]
    assert cost == 15  # hostile square 10, ordinary square 5 (not 20 for the rough map)
    assert BLOCKER in through
    cast(combat, table, mid)
    loaded = cold(tmp_path, mid)
    receipt = next(e for e in loaded.events if e.event_type == "MOVEMENT_COMMITTED"
                   and e.actor_id == LEFT and CHARGE in e.source_definition_id)
    assert receipt.payload["granted_cost_ft"] == 15
    assert receipt.payload["cost_ft"] == 0
    assert loaded.state.actors[BLOCKER].reaction_available
    assert loaded.state.actors[FOE].current_hp < 500
    assert not any(e.event_type == "OPPORTUNITY_ATTACK_DECLARED" for e in loaded.events)


@pytest.mark.parametrize("tier", [None, "TRICKY"])
def test_automatic_seats_choose_and_execute_charge_as_the_best_play(tmp_path, tier):
    combat, table, mid = fixture(tmp_path)
    kwargs = {"ai_tier": tier} if tier else {}
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO", **kwargs)
    context = combat.ai_decision_context(combat._load_session(mid))
    assert any(CHARGE in c.source_definition_id for c in context.legal_candidates)
    choice = combat.controller.choose_primary_action(context)
    selected = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert CHARGE in selected.source_definition_id, (selected.display_name, choice.record)
    state = table.state(mid)
    result = table.auto_step(mid, state["last_sequence"])
    assert result["status"] == "COMMITTED", result
    loaded = cold(tmp_path, mid)
    assert loaded.state.actors[LEFT].position.x > 1
    assert loaded.state.actors[FOE].current_hp < 500
    assert any(e.event_type == "ATTACK_ROLLED" and CHARGE in e.source_definition_id for e in loaded.events)
