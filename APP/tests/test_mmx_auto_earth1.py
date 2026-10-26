"""Earth sphere automation, round 1 (MMXAUTO-EARTH1, 2026-10-26).

Four Earth records that carried a GM rider now run on the table, and their
authority rows are typed without a top-level rider:

  * Humble Wall             the shared destructible-wall system already carries the
                            printed AC 12, hit points 10 + Cultivation Level, Poison and
                            Psychic immunity, cover, movement cost and length by level.
                            The 30-foot Projected Earth option is a NEEDS-SYSTEM gap (no typed legality source).
  * Weight-Seal Strike      "the same surface" is decided by the shared contact query
                            (combat/surface_contact.connected), not by a height test.
  * The Ground Keeps Score  a Burden Mark moves off a creature that missed an attack, failed
                            a Strength or Dexterity saving throw, or failed a Brutal Shove contest
                            to move its owner or an ally (shove_failed hook).
  * Load-Bearing Back       the compiled carrying capacity is doubled.

Every assertion is an id, a typed field or a number; no English prose is asserted.
"""
import json
from pathlib import Path

import pytest

import combat.surface_contact as contact
from combat.ext import docket_walls
from combat.ext import earth_responses as earth
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import (LEFT, RIGHT, act, action_sender, cell_send, fight,
                                        reload, resolve, turn)

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))["mechanics"]

HUMBLE_WALL = "TAL_EARTH_HUMBLE_WALL"
WEIGHT_SEAL = "TAL_EARTH_WEIGHT_SEAL_STRIKE"
GROUND_SCORE = "TAL_EARTH_THE_GROUND_KEEPS_SCORE"
LOAD_BEARING = "TAL_EARTH_LOAD_BEARING_BACK"
CLOD = "EARTH_BASE_WEIGHT_SEEKING_CLOD"
WITNESS = "actor:factory.auto111-witness"

MARK = {"type": "mark", "mark": "Burden Mark", "applies_to": "target", "duration": {"kind": "until_removed"}}
AC_BONUS = {"type": "ac_bonus", "flat": 1000, "applies_to": "self", "duration": "until_removed"}
STR_SAVE = {"type": "save", "ability": "str", "dc": 30, "applies_to": "self",
            "on_fail": [], "on_success": []}


def test_earth_records_are_typed_without_top_level_riders():
    for key in (WEIGHT_SEAL, LOAD_BEARING):
        row = AUTH[key]
        assert row["riders"] == [], key
        assert row["coverage"] == "FULL", key
        assert row["typing_status"] == "reviewed_final", key
        assert row["effects"], key


def test_humble_wall_is_not_labelled_full_while_its_range_option_is_unmodelled():
    """Finding 1: the unmodelled 30-foot option keeps the row out of FULL, and no GM decision is left in it."""
    row = AUTH[HUMBLE_WALL]
    assert row["typing_status"] == "reviewed_final"
    assert row["coverage"] != "FULL"
    assert "GM may resolve" not in row["range"]["gm_note"]
    assert row["range"]["gm_note"].startswith("NEEDS-SYSTEM"), row["range"]


def test_ground_keeps_score_contest_clause_is_typed_not_a_rider():
    """Finding 2: the failed-contest clause is answered by the shove_failed hook. The only remaining rider
    names the owner's choice of participant, which the table cannot check."""
    row = AUTH[GROUND_SCORE]
    assert len(row["riders"]) == 1, row["riders"]
    assert "contest" not in row["riders"][0], row["riders"]
    assert "shove_failed" in row["effects"][0]["evidence"], row["effects"][0]


def test_humble_wall_carries_its_printed_numbers(tmp_path):
    combat, table, mid = fight(tmp_path, [HUMBLE_WALL], spheres=["tianxia.sphere.earth"], cl=15)
    resolve(cell_send(table, mid, "Humble Wall", (4, 6)))
    engine = reload(combat, mid)
    zone = next(z for z in engine.state.zones.values()
                if z.active and z.source_definition_id.endswith(HUMBLE_WALL))
    stats = docket_walls.stats(zone)
    assert stats["ac"] == 12
    assert stats["hp"] == 25                       # 10 + Cultivation Level 15
    assert stats["immune"] == ["POISON", "PSYCHIC"]
    assert stats["scope"] == "section"
    rule = zone.trigger_profile["wall"]
    assert rule["cover"] is True
    assert rule["move_cost"] == 2
    assert rule["length_ft"] == 20                # four sections at Cultivation Level 11
    assert len(zone.affected_cells) == 4


def test_weight_seal_applies_on_one_continuous_surface(tmp_path):
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT_SEAL], left_score=30, left_attack_bonus=100)
    engine = reload(combat, mid)
    assert contact.connected(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    send = action_sender(combat, table, mid, CLOD, target_id=RIGHT)
    prompt = send([])["reaction"]
    assert "Weight-Seal Strike" in str(prompt)
    assert send([{**prompt["context"], "selection": "USE", "option_ids": ["SPEED"]}])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 25


def test_weight_seal_reads_the_shared_contact_query(tmp_path, monkeypatch):
    """The printed rule is one continuous surface, so the shared query decides it."""
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT_SEAL], left_score=30, left_attack_bonus=100)
    asked = []
    real = contact.connected

    def spy(engine, first, second):
        answer = real(engine, first, second)
        asked.append((first.entity_id, second.entity_id, answer))
        return answer

    monkeypatch.setattr(contact, "connected", spy)
    send = action_sender(combat, table, mid, CLOD, target_id=RIGHT)
    prompt = send([])["reaction"]
    assert (LEFT, RIGHT, True) in asked
    assert "Weight-Seal Strike" in str(prompt)


def test_weight_seal_does_not_reach_across_surfaces(tmp_path, monkeypatch):
    """Two creatures that do not touch one surface are not on the same ground."""
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT_SEAL], left_score=30, left_attack_bonus=100)
    monkeypatch.setattr(contact, "connected", lambda engine, first, second: False)
    send = action_sender(combat, table, mid, CLOD, target_id=RIGHT)
    assert send([])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)


def score_fight(tmp_path, **kwargs):
    return fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK, AC_BONUS], **kwargs)


def test_ground_keeps_score_moves_the_mark_after_a_miss(tmp_path):
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    prompt = send([])["reaction"]
    assert "The Ground Keeps Score" in str(prompt)
    result = send([{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_keeps_the_mark_when_the_new_target_refuses_it(tmp_path, monkeypatch):
    """A refused application (the condition_application_attempt checkpoint says no) must not cost the bearer its mark."""
    from combat import ext
    real = ext.run_checkpoint

    def refuse_witness(point, engine, target, *args, **kwargs):
        if point == "condition_application_attempt" and target.entity_id == WITNESS:
            return [False]
        return real(point, engine, target, *args, **kwargs)

    monkeypatch.setattr(ext, "run_checkpoint", refuse_witness)
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    prompt = send([])["reaction"]
    result = send([{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_keeps_the_mark_when_the_owner_declines(tmp_path):
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    prompt = send([])["reaction"]
    result = send([{**prompt["context"], "selection": "DECLINE", "option_ids": []}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_moves_the_mark_after_a_failed_save(tmp_path):
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK],
                                cause=[STR_SAVE], cause_target="SELF")
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    result = act(table, mid, "Cause")
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert "The Ground Keeps Score" in str(prompt)
    result = act(table, mid, "Cause", [{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_needs_a_creature_to_move_the_mark_to(tmp_path):
    """With no other eligible creature the mark stays where it is."""
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], prepare=[MARK, AC_BONUS])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    assert send([])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)


def test_load_bearing_back_doubles_the_carrying_capacity():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    from tests.test_carry import KIT

    def capacity(talents):
        document = sheet(talents, cl=15, kit={"starting_kit": KIT})
        bundle = compile_character(document, actor_id="actor:factory.h15-left")
        return bundle["carrying"]["capacity_lb"]

    plain = capacity([])
    doubled = capacity([LOAD_BEARING])
    assert plain == 210
    assert doubled == plain * 2


RAISED = [{"region_id": "raised-floor", "terrain_type": "BLOCKED", "movement_cost": 0, "height_ft": 10,
           "cells": [{"x": x, "y": y} for x in range(2, 7) for y in range(4, 9)]}]


def raised_arena(arena):
    arena["terrain_regions"] = [dict(region) for region in RAISED]


def test_weight_seal_applies_to_a_pair_on_one_raised_platform(tmp_path):
    """Regression for the elevated case: the old height test refused every raised pair."""
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT_SEAL], left_score=30, left_attack_bonus=100,
                               arena_edit=raised_arena,
                               positions={LEFT: {"x": 3, "y": 6, "z": 2}, RIGHT: {"x": 4, "y": 6, "z": 2}})
    engine = reload(combat, mid)
    assert contact.connected(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    send = action_sender(combat, table, mid, CLOD, target_id=RIGHT)
    prompt = send([])["reaction"]
    assert "Weight-Seal Strike" in str(prompt)
    assert send([{**prompt["context"], "selection": "USE", "option_ids": ["SPEED"]}])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 25


def test_weight_seal_skips_a_floor_creature_beside_the_platform(tmp_path):
    """The same attacker on the platform, hitting a creature on the floor next to it, gets no prompt."""
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT_SEAL], left_score=30, left_attack_bonus=100,
                               extra_witness=True, arena_edit=raised_arena,
                               positions={LEFT: {"x": 3, "y": 6, "z": 2}, RIGHT: {"x": 4, "y": 6, "z": 2}},
                               witness_position={"x": 7, "y": 6, "z": 0})
    engine = reload(combat, mid)
    assert not contact.connected(engine, engine.state.actors[LEFT], engine.state.actors[WITNESS])
    send = action_sender(combat, table, mid, CLOD, target_id=WITNESS)
    result = send([])
    assert "Weight-Seal" not in str(result)
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert not any(c.condition_id == earth.WEIGHT_CHECK for c in engine.state.actors[WITNESS].conditions.values())


@pytest.mark.parametrize("name,position,arena,eligible", [
    ("floor-within-30ft", {"x": 9, "y": 6}, "floor", True),
    ("floor-past-30ft", {"x": 10, "y": 6}, "floor", False),
    ("raised-within-30ft", {"x": 9, "y": 6, "z": 2}, "raised", False),
])
def test_ground_keeps_score_offers_only_creatures_on_the_bearer_surface_within_30_feet(
        tmp_path, name, position, arena, eligible):
    edit = raised_arena if arena == "raised" else (lambda a: a.update(terrain_regions=[]))
    combat, table, mid = score_fight(tmp_path, arena_edit=edit, witness_position=position)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    result = send([])
    if eligible:
        prompt = result["reaction"]
        assert "The Ground Keeps Score" in str(prompt)
        result = send([{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
        assert result["status"] == "COMMITTED", result
        engine = reload(combat, mid)
        assert bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)
        assert not bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    else:
        assert "The Ground Keeps Score" not in str(result)
        assert result["status"] == "COMMITTED", result
        engine = reload(combat, mid)
        assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)
        assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)


def test_ground_keeps_score_explains_the_burden_mark_in_plain_words(tmp_path):
    """Checklist item 13: the prompt and the log line say what the Burden Mark does, not just its name."""
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    prompt = send([])["reaction"]
    text = str(prompt)
    assert "a weight marker" in text and "Earth Response" in text
    result = send([{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    logs = [x.payload.get("log", "") for x in engine.events
            if x.event_type == "PASSIVE_TRIGGERED" and x.source_definition_id == earth.SCORE]
    assert any("weight marker" in line and "moves from" in line for line in logs), logs


def _failed_shove(monkeypatch, engine, mover, target):
    """Drive the real Brutal Shove failure branch: the contest is decided as lost, nothing else is stubbed."""
    from combat.ext import brute_shove
    from combat.ext import ability_source  # noqa: F401  (imported so the hook plug-ins are loaded)

    def lost(ctx, target, **kwargs):
        return {"success": False, "margin": -3, "mine": 9, "theirs": 12, "skill": "Athletics"}

    monkeypatch.setattr(brute_shove, "contest", lost)
    ctx = type("Ctx", (), {})()
    ctx.engine, ctx.actor, ctx.source, ctx.rider = engine, mover, earth.SCORE, (lambda *a, **k: None)
    return brute_shove.shove(ctx, target, {"type": "brutal_shove", "success_branch": True, "on_success": [],
                                           "mode": "push_or_prone"})


def test_ground_keeps_score_moves_the_mark_after_a_failed_contest_to_move_the_owner(tmp_path, monkeypatch):
    """Finding 2: the marked creature fails a shove of its owner, so the mark moves to a creature that can take part."""
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    _failed_shove(monkeypatch, engine, engine.state.actors[RIGHT], engine.state.actors[LEFT])
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_keeps_the_mark_when_the_failed_shove_is_against_an_enemy(tmp_path, monkeypatch):
    """Finding 2 gate: a failed shove of a creature that is neither the owner nor on the owner's team moves no mark."""
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    foe = next(a for a in engine.state.actors.values()
               if a.active and a.entity_id not in (LEFT, RIGHT, WITNESS) and a.team_id != engine.state.actors[LEFT].team_id)
    _failed_shove(monkeypatch, engine, engine.state.actors[RIGHT], foe)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)
