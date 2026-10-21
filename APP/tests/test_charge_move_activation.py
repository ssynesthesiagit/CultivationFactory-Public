"""Public synthetic table fights for granted move-before-attack activation."""
import json
import zipfile
from pathlib import Path

import pytest

from combat import ext, targeting
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.ext import move_attack
from combat.target_knowledge import Knowledge
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
CHARGE = "TAL_SPEAR_DRAGON_SPEAR_CHARGE"
FLOWERS = "TAL_SPEAR_FLOWERS_IN_THE_STORM"
LEFT, FOE, BLOCKER = (FACTORY_ACTOR_PREFIX + name for name in ("charger", "target", "blocker"))
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.duan_cha",
                                "name": "Duan Cha (Short Trident)", "quantity": 1}]}}


@pytest.fixture(autouse=True)
def deterministic_hits_and_failed_saves(monkeypatch):
    ext._load()
    def rewrite(engine, roll, intent):
        return {"source_id": "test:charge-roll", "operation": "replace",
                "natural_result": 19 if roll.actor_id == LEFT else 1}
    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", ()), rewrite])


def fixture(tmp_path, *, distance=15, blocker=False, corridor=False, wall=False, rough=False,
            talents=None, save_success=False, second_blocker=False, kit=None, cl=5):
    names = ["charger", "target"] + (["blocker"] if blocker else []) + (["blocker2"] if second_blocker else [])
    for name in names:
        document = sheet((talents or [CHARGE]) if name == "charger" else [], cl=cl,
                         kit=kit or KIT, primary="Stamina", score=14)
        document["identity"]["display_name"] = name.title()
        stats = document["ability_scores_and_statistics"]
        stats["technique_attack_bonus"] = 40
        stats["hit_points"]["maximum"] = 500
        if name != "charger":
            for ability in stats["abilities"]:
                ability.update(score=110 if save_success else 1, modifier=50 if save_success else -5)
        folder = tmp_path / "portable_characters" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    walls = ([{"shape": "rect", "points": [[0, 0], [12, 1]], "filled": True},
              {"shape": "rect", "points": [[0, 2], [12, 6]], "filled": True}] if corridor else [])
    if wall:
        walls.append({"shape": "rect", "points": [[3, 0], [4, 6]], "filled": True})
    combat.tabletop_maps.save({"display_name": "Charge yard", "width_squares": 12, "height_squares": 6,
        "walls": walls, "terrain": [{"type": "DIFFICULT", "cells": [[2, 1], [3, 1]]}] if rough else [],
        "starts": {"team1": [[1, 1]], "team2": [[1 + distance // 5, 1]] + ([[2, 1]] if blocker else [])
                   + ([[4, 1]] if second_blocker else [])}})
    mid = combat.create_factory_match(project_ids=["charger"], opponent_actor_ids=[FOE] + ([BLOCKER] if blocker else [])
        + ([FACTORY_ACTOR_PREFIX + "blocker2"] if second_blocker else []),
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


def opening_candidate(engine):
    return next((c for c in engine.legal_candidates()
                 if "#one_opening" in c.source_definition_id and c.target_ids == (FOE,)), None)


def cast(combat, table, mid, *, attack_cell="cell:3,1", finish_cell=None, save_choice="Knock Prone", candidate=None):
    state = table.state(mid)
    candidate = candidate or charge_candidate(combat._load_session(mid).engine)
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
            assert candidate.display_name in str(prompt)
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
            minimum = int(prompt.get("choice", {}).get("minimum", 1))
            answer["option_ids"] = ids[:minimum] if minimum > 1 else [picked]
        answers.append(answer)
        # Pauses are transactional, including the earlier move and CP payment.
        assert combat._load_session(mid).engine.state.actors[LEFT].position.x == 1
    pytest.fail("Charge did not settle")


def test_melee_movement_attack_cannot_borrow_a_ranged_only_weapon_profile():
    from types import SimpleNamespace
    action = SimpleNamespace(parameters={"typed": {"effects": [
        {"type": "move_then_attack", "distance_ft": "speed"},
        {"type": "attack", "attack_kind": "cultivation_melee"}]}})
    ranged = SimpleNamespace(parameters={"typed": {
        "range_ft": 20, "weapon": {"attack_delivery": "ranged"}}})
    melee = SimpleNamespace(parameters={"typed": {
        "range_ft": None, "weapon": {"attack_delivery": "melee"}}})
    assert not move_attack.weapon_matches_attack(action, ranged)
    assert move_attack.weapon_matches_attack(action, melee)


def test_charge_uses_the_bound_weapons_reach_not_a_fixed_five_foot_gate(tmp_path):
    long_spear = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang",
                                            "name": "Qiang (Spear)", "quantity": 1}]}}
    combat, _, mid = fixture(tmp_path, distance=40, kit=long_spear)
    engine = cold(tmp_path, mid)
    assert charge_candidate(engine) is not None  # 30-foot movement + 10-foot weapon reach


def test_charge_is_offered_at_fifteen_feet_without_granting_movement_to_flowers(tmp_path):
    combat, _, mid = fixture(tmp_path, talents=[CHARGE, FLOWERS])
    engine = cold(tmp_path, mid)
    assert charge_candidate(engine) is not None
    flowers = next(a for a in engine.action_catalog.values()
                   if a.owner_id == LEFT and FLOWERS in a.source_definition_id)
    # Flowers is a self-targeted recipient picker, not a move-before-attack
    # action. Its existing activation/recipient policy is outside this fix.
    assert move_attack.movement_row(flowers) is None
    assert move_attack.activation_geometry(engine, engine.state.actors[LEFT],
                                           engine.state.actors[FOE], flowers) is None


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
    action = next(a for a in before.action_catalog.values() if a.owner_id == LEFT and CHARGE in a.source_definition_id)
    weapon = next(iter(move_attack.legal_weapons(before, actor, before.state.actors[FOE], action,
                                                move_attack.movement_row(action)).values()))
    weapon_bonus = weapon.parameters["typed"]["numbers"]["attack_bonus"]
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
    assert attacks[0].payload["modifier"] == weapon_bonus != 40
    assert engine.state.actors[FOE].reaction_available, "leaving its reach must not provoke"
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[FOE].position.x == 4, "failed save chooses Prone instead of also pushing"
    moves = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == LEFT]
    assert len(moves) >= 2
    assert not any(e.event_type == "OPPORTUNITY_ATTACK_DECLARED" for e in engine.events)


def test_two_hostile_blockers_cannot_borrow_the_single_passage_permission(tmp_path):
    combat, _, mid = fixture(tmp_path, distance=30, blocker=True, second_blocker=True, corridor=True)
    assert charge_candidate(cold(tmp_path, mid)) is None


def test_spent_ordinary_movement_does_not_reduce_the_talents_own_grant(tmp_path):
    combat, table, mid = fixture(tmp_path)
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE"
                and c.destination and (c.destination.x, c.destination.y) == (1, 2))
    assert table.act(mid, move.candidate_id, move.decision_id, move.state_version,
                     state["last_sequence"])["status"] == "COMMITTED"
    remaining = cold(tmp_path, mid).state.actors[LEFT].movement_remaining_ft
    assert remaining == 25
    cast(combat, table, mid)
    assert cold(tmp_path, mid).state.actors[LEFT].movement_remaining_ft == remaining


def test_successful_strength_save_pushes_only_five_feet(tmp_path):
    combat, table, mid = fixture(tmp_path, save_success=True)
    cast(combat, table, mid)
    engine = cold(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert target.position.x == 5
    assert not any(c.condition_id == "condition:typed.prone" for c in target.conditions.values())


def test_failed_strength_save_can_push_fifteen_feet_instead_of_prone(tmp_path):
    combat, table, mid = fixture(tmp_path)
    cast(combat, table, mid, save_choice="Push 15 feet away")
    engine = cold(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert target.position.x == 7, "15 feet away from the attacker at 3,1"
    assert not any(c.condition_id == "condition:typed.prone" for c in target.conditions.values())
    assert target.current_hp < 500


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
    long_spear = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang",
                                            "name": "Qiang (Spear)", "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, kit=long_spear)
    # Spend the ordinary Move allowance on real committed steps, returning to
    # the same 15-foot separation. Charge is now the best legal attack: the
    # held reach weapon cannot strike here without its independent grant.
    for y in (2, 1, 2, 1, 2, 1):
        state = table.state(mid)
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE"
                    and c.destination and (c.destination.x, c.destination.y) == (1, y))
        assert table.act(mid, move.candidate_id, move.decision_id, move.state_version,
                         state["last_sequence"])["status"] == "COMMITTED"
    assert cold(tmp_path, mid).state.actors[LEFT].movement_remaining_ft == 0
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


def test_existing_one_opening_uses_the_same_typed_native_movement_seam(tmp_path):
    talent = "TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN"
    combat, table, mid = fixture(tmp_path, talents=[talent], cl=17)
    engine = cold(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
                     if "#one_opening" in c.source_definition_id and c.target_ids == (FOE,))
    action = engine.action_catalog[candidate.source_definition_id]
    row = move_attack.movement_row(action)
    assert row["distance_ft"] == "speed" and row["no_oa"]
    assert not row["ignore_nonmagical_difficult"] and row["hostile_spaces"] == 0
    cast(combat, table, mid, candidate=candidate)
    loaded = cold(tmp_path, mid)
    assert loaded.state.actors[LEFT].position.x == 3
    assert loaded.state.actors[FOE].current_hp < 500
    assert loaded.state.actors[LEFT].resources["resource:core.martial_focus"] == 0
    assert not any("#one_opening" in c.source_definition_id for c in loaded.legal_candidates())


def test_one_opening_is_offered_at_twenty_feet_and_attacks_after_its_own_move(tmp_path):
    """The F4R reference fight: 20 ft apart, Speed 30, One Opening must be offered."""
    talent = "TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN"
    combat, table, mid = fixture(tmp_path, distance=20, talents=[talent], cl=17)
    engine = cold(tmp_path, mid)
    candidate = opening_candidate(engine)
    assert candidate is not None, "the variant's reviewed movement row must reach the menu"
    action = engine.action_catalog[candidate.source_definition_id]
    assert action.range_ft == 5, "the attack keeps the weapon's reach; the grant supplies the move"
    assert move_attack.activation_geometry(engine, engine.state.actors[LEFT],
                                           engine.state.actors[FOE], action) is True
    cast(combat, table, mid, attack_cell="cell:4,1", candidate=candidate)
    loaded = cold(tmp_path, mid)
    actor, target = loaded.state.actors[LEFT], loaded.state.actors[FOE]
    assert (actor.position.x, actor.position.y) == (4, 1)
    assert target.current_hp < 500
    assert actor.resources["resource:core.martial_focus"] == 0
    assert actor.turn_flags.get("_round_needle_one_opening")
    assert not any("#one_opening" in c.source_definition_id for c in loaded.legal_candidates())


def test_one_opening_checks_its_grant_for_a_remembered_square(tmp_path):
    """Remembered targets use the same grant; the hidden position is never read."""
    talent = "TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN"
    combat, _, mid = fixture(tmp_path, distance=15, talents=[talent], cl=17)
    engine = cold(tmp_path, mid)
    actor, target = engine.state.actors[LEFT], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and "#one_opening" in a.source_definition_id)
    remembered = Position(x=5, y=2)  # 25 ft away; a 30-ft grant still reaches an attack square
    assert targeting.in_range(engine, actor, target, action,
                              known=Knowledge("LAST_OBSERVED", remembered))
    far = Position(x=9, y=5)  # beyond Speed plus the weapon's reach
    assert not targeting.in_range(engine, actor, target, action,
                                  known=Knowledge("LAST_OBSERVED", far))

def test_move_attack_numbers_never_write_into_the_shared_typed_parameters(monkeypatch):
    """Regression (CHARGEMOVE1F6): a weapon attack bonus written during move_then_attack must not persist in the
    action's shared parameters["typed"]; a later menu build or seat would otherwise see the leaked bonus."""
    from types import SimpleNamespace
    weapon = SimpleNamespace(parameters={"typed": {"numbers": {"attack_bonus": 7}}})
    shared_numbers = {"attack_bonus": 40, "save_dc": 20}
    shared = {"numbers": shared_numbers, "weapon_source_id": "weapon",
              "effects": [{"type": "move_then_attack", "weapon_attack": True}]}
    action = SimpleNamespace(parameters={"typed": shared})
    engine = SimpleNamespace(action_catalog={"weapon": weapon})
    # The caller hands the action's own shared dict in as ctx.typed (as _run_watched does).
    ctx = SimpleNamespace(engine=engine, actor=SimpleNamespace(), target=SimpleNamespace(), action=action,
                          typed=shared, numbers=dict(shared_numbers), source="charge", intent=None,
                          damage_cache={})
    shared_before = {"numbers": {"attack_bonus": 40, "save_dc": 20}, "weapon_source_id": "weapon",
                     "effects": shared["effects"]}
    monkeypatch.setattr(move_attack, "attack_action", lambda engine, actor, action, weapon=None: action)
    monkeypatch.setattr(move_attack, "allowance", lambda engine, actor, row: 0)
    monkeypatch.setattr(move_attack, "attack_routes", lambda *a, **k: [])
    monkeypatch.setattr(move_attack, "choose_route", lambda *a, **k: None)
    row = shared["effects"][0]
    move_attack.move(ctx, row)
    assert ctx.typed["numbers"]["attack_bonus"] == 7, "the weapon's bonus is applied to this activation"
    assert shared["numbers"] == {"attack_bonus": 40, "save_dc": 20}
    assert shared == shared_before
    assert ctx.typed is not shared, "the write is rebound on this activation, not made in place"


def test_charge_on_a_remembered_square_moves_and_strikes_it_when_the_target_has_left(tmp_path, monkeypatch):
    """Regression (CHARGEMOVE1F6 finding 1): a Charge offered from a remembered square must still move and attack
    that square after the hidden target has stepped away, instead of spending its cost on zero movement."""
    ext.effects()
    hidden = {}

    def hide_and_step_away(engine, actor):
        # A transition is previewed on one engine and committed on another; each
        # starts without the condition. Guard on this engine's own state, never
        # on a process-wide flag, or the committed engine silently skips it.
        if actor.entity_id != LEFT:
            return
        target = engine.state.actors[FOE]
        if any(c.condition_id == "condition:typed.invisible" for c in target.conditions.values()):
            return
        observed = target.position.model_copy()
        engine.state.observations[actor.team_id][FOE] = observed
        engine._apply_condition(target, "condition:typed.invisible", "test:charge-hide", FOE, expires_on="UNTIL_REMOVED")
        target.position = Position(x=observed.x, y=observed.y + 1)
        hidden.setdefault("observed", observed)

    monkeypatch.setitem(ext._HOOKS, "turn_start", [*ext._HOOKS.get("turn_start", ()), hide_and_step_away])
    combat, table, mid = fixture(tmp_path, distance=15, talents=[CHARGE])
    # The charger wins initiative, so its first turn began during match
    # creation, before turn_start hooks are dispatched. One full round brings
    # its next turn, where the remembered departure is installed.
    for _ in range(8):
        state = table.state(mid)
        if hidden and state["menu"]["actor_id"] == LEFT:
            break
        engine = combat._load_session(mid).engine
        end = next(c for c in engine.legal_candidates() if c.kind.value == "END_TURN")
        assert table.act(mid, end.candidate_id, end.decision_id, end.state_version,
                         state["last_sequence"])["status"] == "COMMITTED"
    else:
        pytest.fail("the remembered departure never happened on the charger's turn")
    charge = charge_candidate(combat._load_session(mid).engine)
    assert charge is not None and hidden, "the remembered square is offered"
    assert charge.destination == hidden["observed"]
    cast(combat, table, mid, attack_cell="cell:3,1", candidate=charge)

    after = cold(tmp_path, mid)
    assert after.state.actors[LEFT].position != Position(x=1, y=1), "Charge spent its cost and moved"
    attacks = [e for e in after.events if e.source_definition_id == charge.source_definition_id
               and e.event_type in ("ATTACK_ROLLED", "ATTACK_LOCATION_MISSED")]
    assert attacks, "the Charge strikes the remembered square"
