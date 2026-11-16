"""Regression tests for Guard-Cutting Parry's zero-damage 5-foot move (LEDGERGCPARRY1).

Built on tests/test_t17_sabers_guard_cutting_parry.py's synthetic table setup (hunt15_support):
- reducing a melee weapon hit to 0 offers choice:needle.zero_damage_move (preferred square
  farthest from the attacker, ties by cheaper path, lower y, lower x) and exempts only
  the attacker from Opportunity Attacks;
- leaving damage > 0 offers no move choice;
- declining the choice keeps the defender on its square;
- another hostile in reach still gets its Opportunity Attack;
- parrying an Opportunity Attack to 0 during the defender's own walk lands on a legal,
  unoccupied square without continuing the old walk path;
- compile_blocks rejects invalid zero_damage_move specs.
"""
from __future__ import annotations

import copy
import pytest

from combat import typed_reactions
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests import hunt15_support
from tests.hunt15_support import ALLY, LEFT, RIGHT, act, fight, reload, turn

PARRY = "tianxia.talent.sabers.guard_cutting_parry"
MAUL = {"items": [{"item_id": "tianxia.mortal.weapon.da_chui", "name": "Da Chui (Maul)", "quantity": 1}]}
DUAN_JIAN = {"items": [{"item_id": "tianxia.mortal.weapon.duan_jian", "name": "Duan Jian", "quantity": 1}]}


def _reductions(engine, after=0):
    return [event for event in engine.events
            if event.event_type == "REACTION_RESOLVED" and event.sequence > after
            and event.source_definition_id == PARRY]


def _attacks_by(engine, actor_id, after=0):
    return [event for event in engine.events
            if event.event_type == "ATTACK_ROLLED" and event.sequence > after
            and event.actor_id == actor_id]


def _moves_by(engine, actor_id, after=0):
    return [event for event in engine.events
            if event.event_type == "MOVEMENT_COMMITTED" and event.sequence > after
            and event.actor_id == actor_id]


def _resolve_step(table, mid, *, label=None, target=RIGHT, candidate_id=None, decline_zero_move=False):
    """Submit an attack or move and answer reaction/choice prompts deterministically."""
    prompts = []
    answers = []
    menu = None
    last_seq = None
    if candidate_id is not None:
        state = table.state(mid)
        menu = state["menu"]
        last_seq = state["last_sequence"]
    for _ in range(12):
        if candidate_id is None:
            result = act(table, mid, label, answers, target_id=target)
        else:
            result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], last_seq, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        source_id = prompt["context"]["reaction_source_id"]
        choice = prompt.get("choice") or {}
        options = [option["id"] for option in choice.get("options") or []]
        if source_id == "choice:needle.zero_damage_move":
            if decline_zero_move:
                answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
            else:
                preferred = choice.get("preferred") or options[:1]
                answers.append({**prompt["context"], "selection": "USE", "option_ids": list(preferred)})
        elif options:
            pick = "skip" if "skip" in options else options[0]
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [pick]})
        else:
            answers.append({**prompt["context"], "selection": "USE", "option_ids": []})
    raise AssertionError("too many reaction prompts")


def _attack_label(table, mid):
    return next(group["label"] for group in table.state(mid)["menu"]["actions"]
                if group["label"].endswith(" attack"))


def _trigger_zero_damage_parry(combat, table, mid, *, decline_zero_move=False, rounds=9):
    """Swing until Guard-Cutting Parry reduces a melee weapon hit to 0."""
    for _ in range(rounds):
        turn(table, mid, LEFT)
        engine_before = combat._load_session(mid).engine
        marker = max((event.sequence for event in engine_before.events), default=0)
        label = _attack_label(table, mid)
        _, prompts = _resolve_step(table, mid, label=label, target=RIGHT, decline_zero_move=decline_zero_move)
        engine = reload(combat, mid)
        parries = _reductions(engine, marker)
        if parries and parries[-1].payload["pending_after"] == 0:
            return engine, marker, prompts, parries[-1]
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("Guard-Cutting Parry did not reduce a hit to 0 within rounds")


def test_zero_damage_parry_moves_away_without_attacker_oa(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", DUAN_JIAN)
    combat, table, mid = fight(tmp_path / "zero-move", right=[PARRY], seed="ZDM1")
    start_pos = Position(x=4, y=6)
    attacker_pos = Position(x=3, y=6)
    engine, marker, prompts, _ = _trigger_zero_damage_parry(combat, table, mid, decline_zero_move=False)
    move_prompts = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.zero_damage_move"]
    assert len(move_prompts) == 1
    end_pos = engine.state.actors[RIGHT].position
    assert engine.grid.distance_ft(end_pos, attacker_pos) >= engine.grid.distance_ft(start_pos, attacker_pos) + 5
    assert _moves_by(engine, RIGHT, marker)
    # Only the triggering attack by LEFT occurred since marker; LEFT made no Opportunity Attack.
    assert len(_attacks_by(engine, LEFT, marker)) == 1
    assert engine.state.actors[LEFT].reaction_available is True
    assert not any(p["context"].get("reactor_id") == LEFT for p in prompts)


def test_damage_left_means_no_move(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", MAUL)
    combat, table, mid = fight(tmp_path / "dmg-left", right=[PARRY], seed="ZDM2")
    start_pos = Position(x=4, y=6)
    for _ in range(9):
        turn(table, mid, LEFT)
        engine_before = combat._load_session(mid).engine
        marker = max((event.sequence for event in engine_before.events), default=0)
        label = _attack_label(table, mid)
        _, prompts = _resolve_step(table, mid, label=label, target=RIGHT, decline_zero_move=True)
        engine = reload(combat, mid)
        parries = _reductions(engine, marker)
        if parries and parries[-1].payload["pending_after"] > 0:
            assert not any(p["context"]["reaction_source_id"] == "choice:needle.zero_damage_move" for p in prompts)
            assert engine.state.actors[RIGHT].position == start_pos
            assert not _moves_by(engine, RIGHT, marker)
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("Guard-Cutting Parry did not leave >0 damage within rounds")


def test_declining_keeps_the_square(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", DUAN_JIAN)
    combat, table, mid = fight(tmp_path / "decline", right=[PARRY], seed="ZDM3")
    start_pos = Position(x=4, y=6)
    engine, marker, prompts, _ = _trigger_zero_damage_parry(combat, table, mid, decline_zero_move=True)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.zero_damage_move" for p in prompts)
    assert engine.state.actors[RIGHT].position == start_pos
    assert not _moves_by(engine, RIGHT, marker)


def test_other_hostile_still_gets_its_opportunity_attack(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", DUAN_JIAN)
    real_arenas = CombatService.factory_arenas

    def _open_arenas(self, *, include_retired: bool = False):
        arenas = copy.deepcopy(real_arenas(self, include_retired=include_retired))
        arenas["battlefield:factory_pillar_arena"]["terrain_regions"] = []
        return arenas

    monkeypatch.setattr(CombatService, "factory_arenas", _open_arenas)
    combat, table, mid = fight(
        tmp_path / "other-oa",
        right=[PARRY],
        ally=[],
        seed="ZDM4",
        positions={LEFT: {"x": 4, "y": 5}, RIGHT: {"x": 5, "y": 5}, ALLY: {"x": 4, "y": 4}},
    )
    engine, marker, prompts, _ = _trigger_zero_damage_parry(combat, table, mid, decline_zero_move=False)
    move_prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.zero_damage_move")
    preferred_id = move_prompt["choice"]["preferred"][0]
    preferred_label = next(o["label"] for o in move_prompt["choice"]["options"] if o["id"] == preferred_id)
    assert preferred_label == "Move to (6, 4)"
    assert engine.state.actors[RIGHT].position == Position(x=6, y=4)
    assert len(_attacks_by(engine, ALLY, marker)) == 1
    assert engine.state.actors[ALLY].reaction_available is False
    assert len(_attacks_by(engine, LEFT, marker)) == 1
    assert engine.state.actors[LEFT].reaction_available is True


def test_parry_during_own_move_ends_on_a_legal_square(tmp_path, monkeypatch):
    monkeypatch.setattr(hunt15_support, "KIT", DUAN_JIAN)
    combat, table, mid = fight(
        tmp_path / "own-move",
        right=[PARRY],
        seed="ZDM5",
        positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}},
    )
    for _ in range(9):
        turn(table, mid, RIGHT)
        engine_now = combat._load_session(mid).engine
        if engine_now.state.actors[RIGHT].position != Position(x=4, y=6):
            back = next(m for m in table.state(mid)["menu"]["moves"]
                        if m["destination"]["x"] == 4 and m["destination"]["y"] == 6 and m["movement_mode"] == "walk")
            _resolve_step(table, mid, candidate_id=back["candidate_id"])
        marker = max((event.sequence for event in combat._load_session(mid).engine.events), default=0)
        walk = next(m for m in table.state(mid)["menu"]["moves"]
                    if m["destination"]["x"] == 7 and m["destination"]["y"] == 6 and m["movement_mode"] == "walk")
        _, prompts = _resolve_step(table, mid, candidate_id=walk["candidate_id"], decline_zero_move=False)
        engine = reload(combat, mid)
        parries = _reductions(engine, marker)
        if parries and parries[-1].payload["pending_after"] == 0:
            assert any(p["context"]["reaction_source_id"] == "choice:needle.zero_damage_move" for p in prompts)
            pos = engine.state.actors[RIGHT].position
            assert pos != Position(x=4, y=6)
            assert pos != Position(x=7, y=6)
            assert pos != engine.state.actors[LEFT].position
            assert engine.grid.placement_legal(pos, occupied_cells=[engine.state.actors[LEFT].position])
            assert engine.grid.distance_ft(pos, engine.state.actors[LEFT].position) > 5
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("OA + zero-damage parry did not trigger within rounds")


def test_compile_rejects_bad_zero_damage_move(monkeypatch):
    bad = {**typed_reactions.rules()["features"][PARRY], "zero_damage_move": {"distance_ft": 7, "no_oa_from": "attacker"}}
    monkeypatch.setitem(typed_reactions.rules()["features"], PARRY, bad)
    with pytest.raises(ValueError, match="zero_damage_move"):
        typed_reactions.compile_blocks([PARRY], pb=4, key_mod=2, saves={}, resource_ids={})
