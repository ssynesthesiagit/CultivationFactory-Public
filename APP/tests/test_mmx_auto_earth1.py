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
                            a Strength or Dexterity saving throw, or failed to move its owner or an
                            ally against its will (the shove_failed hook for a lost contest, and the
                            shared forced_movement_reduced seam for a push that ended at 0 feet).
                            Only a creature the table can show took part in the same hostile action
                            may receive it (earth_responses._contributed: a Warleader Standard that
                            commands the actor, or the same hostile formation), and the mark lands
                            through the native mark_apply path, so Mule-Shoulder Method can refuse it.
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
from tests.auto_worker1_support import (ALLY, LEFT, RIGHT, act, action_sender, cell_send, fight,
                                        reload, resolve, settle, turn)

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))["mechanics"]

HUMBLE_WALL = "TAL_EARTH_HUMBLE_WALL"
WEIGHT_SEAL = "TAL_EARTH_WEIGHT_SEAL_STRIKE"
GROUND_SCORE = "TAL_EARTH_THE_GROUND_KEEPS_SCORE"
LOAD_BEARING = "TAL_EARTH_LOAD_BEARING_BACK"
DEEP_ROOT = "TAL_EARTH_DEEP_ROOT_STANCE"
MULE = "TAL_EARTH_MULE_SHOULDER_METHOD"
BRUTE_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
STANDARD = "WARLEADER_BASE_SET_THE_STANDARD"
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
    """Finding 2: the lost-contest clause is answered by the shove_failed hook, so the row keeps exactly one
    unmodelled clause (the owner's own choice of participant, which the table cannot check).

    Counted, not quoted: the public mirror scrambles the prose of these rows, so a test that reads the
    words passes or fails on the mirror's copy instead of on the fix."""
    row = AUTH[GROUND_SCORE]
    assert len(row["riders"]) == 1, len(row["riders"])
    assert [effect["type"] for effect in row["effects"]] == ["rider"], row["effects"]
    assert {effect["origin"] for effect in row["effects"]} == {"reviewed"}


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
    result = send([])
    assert "Weight-Seal" not in str(result)
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30


def score_fight(tmp_path, **kwargs):
    kwargs.setdefault("witness_talents", [STANDARD])
    return fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK, AC_BONUS], **kwargs)


def contribute(table, mid):
    """Give the witness the table's proof that it took part in the coming hostile action.

    Finding 1: "The new target must have contributed to the same hostile action ... commanding the
    attacker". Set the Standard is the witness's own Warleader Standard; it commands the attacker
    (combat/ext/warleader.commanded) and lasts until the start of the witness's next turn, so it is
    still running when the attacker acts."""
    turn(table, mid, WITNESS)
    assert act(table, mid, "Set the Standard")["status"] == "COMMITTED"


def test_ground_keeps_score_moves_the_mark_after_a_miss(tmp_path):
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)
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

    def refuse_witness(point, *args, **kwargs):
        # condition_application_attempt(engine, target, condition_id, source_id, source_actor_id);
        # other strict checkpoints keep their own arity, so only this point is answered.
        if (point == "condition_application_attempt" and len(args) >= 4
                and args[1].entity_id == WITNESS and "burden" in str(args[2]).lower()):
            return [False]
        return real(point, *args, **kwargs)

    monkeypatch.setattr(ext, "run_checkpoint", refuse_witness)
    combat, table, mid = score_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)
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
    contribute(table, mid)
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
                                cause=[STR_SAVE], cause_target="SELF", witness_talents=[STANDARD])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)
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


def test_ground_keeps_score_will_not_move_a_mark_between_two_surfaces(tmp_path):
    """The new target must touch the same continuous surface, so a platform and the floor never pair."""
    combat, table, mid = score_fight(
        tmp_path, arena_edit=raised_arena,
        positions={LEFT: {"x": 3, "y": 6, "z": 2}, RIGHT: {"x": 4, "y": 6, "z": 2}},
        witness_position={"x": 7, "y": 6, "z": 0})
    engine = reload(combat, mid)
    left, right, witness = (engine.state.actors[KEY] for KEY in (LEFT, RIGHT, WITNESS))
    assert contact.connected(engine, left, right)          # one platform is one surface
    assert not contact.connected(engine, right, witness)   # the floor beside it is another
    assert earth._score_candidates(engine, left, right) == []


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
    """A raised platform and the floor are two surfaces, so the pair is refused before any hit."""
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT_SEAL], left_score=30, left_attack_bonus=100,
                               extra_witness=True, arena_edit=raised_arena,
                               positions={LEFT: {"x": 3, "y": 6, "z": 2}, RIGHT: {"x": 4, "y": 6, "z": 2}},
                               witness_position={"x": 7, "y": 6, "z": 0})
    engine = reload(combat, mid)
    left, right, witness = (engine.state.actors[KEY] for KEY in (LEFT, RIGHT, WITNESS))
    assert contact.connected(engine, left, right)          # one platform is one surface
    assert not contact.connected(engine, left, witness)    # the floor beside it is another


@pytest.mark.parametrize("name,position,arena,eligible,spots", [
    ("floor-within-30ft", {"x": 9, "y": 6}, "floor", True, None),
    ("floor-past-30ft", {"x": 10, "y": 6}, "floor", False, None),
    ("raised-same-platform", {"x": 6, "y": 6, "z": 2}, "raised", True,
     {LEFT: {"x": 3, "y": 6, "z": 2}, RIGHT: {"x": 4, "y": 6, "z": 2}}),
])
def test_ground_keeps_score_offers_only_creatures_on_the_bearer_surface_within_30_feet(
        tmp_path, name, position, arena, eligible, spots):
    edit = raised_arena if arena == "raised" else (lambda a: a.update(terrain_regions=[]))
    combat, table, mid = score_fight(tmp_path, arena_edit=edit, witness_position=position,
                                     **(dict(positions=spots) if spots else {}))
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)
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
    contribute(table, mid)
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


def shove_fight(tmp_path, **kwargs):
    """A fight where the marked creature can really push: the Brute chassis, driven through the table."""
    kwargs.setdefault("witness_talents", [STANDARD])
    return fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK],
                 right_talents=[BRUTE_SHOVE], right_spheres=["tianxia.sphere.brute"], **kwargs)


def decided(monkeypatch, *, success):
    """Decide the shove contest the way a die roll would, before the table resolves the action.

    Only the die is replaced: the action still runs through its own menu, its own branch and the
    engine's transaction, and the state has to survive a cold reload afterwards."""
    from combat.ext import brute_shove

    def contest(ctx, target, **kwargs):
        return {"success": success, "margin": 5 if success else -3,
                "mine": 15 if success else 9, "theirs": 10 if success else 12, "skill": "Athletics"}

    monkeypatch.setattr(brute_shove, "contest", contest)


def push_first(prompt):
    """Answer a shove's own questions (push, not prone); every other prompt takes its minimum."""
    choice = prompt.get("choice") or {}
    ids = [option["id"] for option in choice.get("options", [])]
    return ["push"] if "push" in ids else ids[:max(1, choice.get("minimum", 1))]


def test_ground_keeps_score_moves_the_mark_after_a_failed_contest_to_move_the_owner(tmp_path, monkeypatch):
    """Finding 4: the failed shove is driven through the table, committed, and cold-reloaded.

    The old regression mutated a reloaded engine off to the side, so it never committed anything and
    never exercised the table path at all."""
    combat, table, mid = shove_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)
    turn(table, mid, RIGHT)
    decided(monkeypatch, success=False)
    send = action_sender(combat, table, mid, BRUTE_SHOVE, target_id=LEFT)
    result, prompts = settle(send, choose=push_first)
    assert result["status"] == "COMMITTED", result
    assert any("The Ground Keeps Score" in str(prompt) for prompt in prompts), prompts
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_only_your_own_failed_move_moves_your_mark(tmp_path):
    """The gate: the mark moves only when the creature that failed to move is you or one of your allies.

    The marked creature is the owner's enemy and the bystander is its fellow enemy, so a failed attempt
    to move the bystander is neither of the printed subjects and the transfer query answers nobody
    (earth._score_owners is the only question ground_score_contest and ground_score_prevented ask)."""
    combat, table, mid = shove_fight(tmp_path)
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    keeper, rider, bystander = (engine.state.actors[key] for key in (LEFT, RIGHT, WITNESS))
    assert bears_mark(rider, LEFT, earth.MARK)
    assert bystander.team_id == rider.team_id != keeper.team_id
    assert [a.entity_id for a in earth._score_owners(engine, rider)] == [LEFT]
    assert earth._score_owners(engine, bystander) == []


def test_ground_keeps_score_needs_proof_that_the_new_target_took_part(tmp_path):
    """Finding 1: a bystander that took part in nothing is not offered, however close it stands.

    Before the fix the candidate list was position, team and surface only, so the nearest enemy was
    offered (and auto-picked) even though the printed rule asks for "another creature [that] must have
    contributed to the same hostile action"."""
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK, AC_BONUS])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    result = send([])
    assert result["status"] == "COMMITTED", result
    assert "The Ground Keeps Score" not in str(result)
    engine = reload(combat, mid)
    assert earth._score_candidates(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT]) == []
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_transferred_mark_can_be_refused_by_mule_shoulder_method(tmp_path):
    """Finding 2: the moved mark is a real mark, so a defense that refuses marks refuses this one.

    The transfer used to write the condition straight in (_apply_condition), which skips the mark_apply
    hook every other mark goes through; Mule-Shoulder Method answers that hook."""
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK, AC_BONUS],
                               witness_talents=[STANDARD, MULE])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", target_id=LEFT)
    prompt = send([])["reaction"]
    assert prompt["choice"]["options"][0]["id"] == WITNESS
    result = send([{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK)
    assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)


def test_ground_keeps_score_moves_the_mark_when_deep_root_stance_stops_a_push(tmp_path, monkeypatch):
    """Finding 3: a push the owner stops short is a creature failing to move it against its will.

    The printed clause names the outcome, not one contest. Deep Root Stance cuts the shove's push to 0
    feet at the shared forced-movement seam, so the mark moves even though no contest was lost."""
    combat, table, mid = fight(tmp_path, [GROUND_SCORE, DEEP_ROOT], extra_witness=True, prepare=[MARK],
                               right_talents=[BRUTE_SHOVE], right_spheres=["tianxia.sphere.brute"],
                               witness_talents=[STANDARD])
    turn(table, mid, LEFT)                       # take the stance on the owner's own turn
    assert act(table, mid, "Deep Root Stance")["status"] == "COMMITTED"
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    contribute(table, mid)                       # the Standard must be up when the shover acts
    before = [key for key, actor in reload(combat, mid).state.actors.items() if bears_mark(actor, LEFT, earth.MARK)]
    assert before == [RIGHT], before                 # a Burden Mark lasts until the end of the owner's next turn
    turn(table, mid, RIGHT)
    decided(monkeypatch, success=True)
    send = action_sender(combat, table, mid, BRUTE_SHOVE, target_id=LEFT)
    result = settle(send, choose=push_first)[0]
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    moved = (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y)
    holders = [key for key, actor in engine.state.actors.items() if bears_mark(actor, LEFT, earth.MARK)]
    candidates = [a.entity_id for a in earth._score_candidates(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])]
    assert (holders, moved) == ([WITNESS], (3, 6)), (before, holders, candidates, moved)  # the push moved nothing


# ---------------------------------------------------------------- Finding 1: capacity-neutral moves
def marks_on(engine, owner_id):
    """The creatures carrying the owner's Burden Mark, oldest placement first."""
    held = [condition for actor in engine.state.actors.values() for condition in actor.conditions.values()
            if condition.condition_id == earth._mark_id(owner_id)]
    held.sort(key=lambda condition: condition.applied_sequence)
    return [condition.target_id for condition in held]


def capacity_fight(tmp_path):
    """A fight where the owner already holds its whole Burden Mark limit: PB 2 marks, both on enemies.

    The fourth creature is an enemy ally of the marked one, so the mark that moves can sit in the oldest
    or in the newest slot of the limit."""
    return fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK], left_pb=2,
                 ally=[], ally_team="team:opponents",
                 positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}},
                 witness_position={"x": 3, "y": 7}, witness_talents=[STANDARD],
                 cause=[STR_SAVE], cause_target="SELF")

@pytest.mark.parametrize("first", ["right", "ally"])
def test_ground_keeps_score_move_at_the_mark_limit_ends_no_other_mark(tmp_path, first):
    """Finding 1: at the Burden Mark limit the moving mark takes back the slot it frees.

    Native placement ends the oldest mark to make room. With the moving mark oldest, that ended the very
    instance being moved and the transfer crashed the action; with another creature's mark oldest, the
    owner lost that one as well as the moving one, so a "move" cost two marks. Either way the move was
    not capacity-neutral."""
    combat, table, mid = capacity_fight(tmp_path)
    order = [RIGHT, ALLY] if first == "right" else [ALLY, RIGHT]
    for actor_id in order:
        assert act(table, mid, "Prepare", target_id=actor_id)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert marks_on(engine, LEFT) == order, marks_on(engine, LEFT)   # the limit is full, oldest first
    contribute(table, mid)
    turn(table, mid, RIGHT)
    result = act(table, mid, "Cause")
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert "The Ground Keeps Score" in str(prompt)
    result = act(table, mid, "Cause", [{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert marks_on(engine, LEFT) == [order[0], WITNESS], marks_on(engine, LEFT)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, earth.MARK) is (first == "ally")

def test_ground_keeps_score_refusal_at_the_mark_limit_ends_no_mark(tmp_path, monkeypatch):
    """Finding 1: a refused application cannot cost the owner a mark it never placed.

    The application checkpoint answers after native placement has already ended the oldest mark to make
    room, so the refusal used to leave the owner one mark short where nothing had happened at all."""
    from combat import ext
    real = ext.run_checkpoint

    def refuse_witness(point, *args, **kwargs):
        if (point == "condition_application_attempt" and len(args) >= 4
                and args[1].entity_id == WITNESS and "burden" in str(args[2]).lower()):
            return [False]
        return real(point, *args, **kwargs)

    monkeypatch.setattr(ext, "run_checkpoint", refuse_witness)
    combat, table, mid = capacity_fight(tmp_path)
    for actor_id in (ALLY, RIGHT):
        assert act(table, mid, "Prepare", target_id=actor_id)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert marks_on(engine, LEFT) == [ALLY, RIGHT]
    contribute(table, mid)
    turn(table, mid, RIGHT)
    result = act(table, mid, "Cause")
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    result = act(table, mid, "Cause", [{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert marks_on(engine, LEFT) == [ALLY, RIGHT], marks_on(engine, LEFT)
    assert not bears_mark(engine.state.actors[WITNESS], LEFT, earth.MARK)

# ------------------------------------------------------ Finding 2: only a real formation counts
ORDINARY_AREA = {"shape": "sphere", "size_ft": 10, "centered_on_self": True,
                 "duration": {"kind": "minutes", "amount": 1}, "name": "Ordinary rubble"}
SET_ARRAY = "FORMATIONS_BASE_SET_ARRAY"


def test_ground_keeps_score_rejects_a_bystander_inside_an_ordinary_area(tmp_path):
    """Finding 2: standing in an ordinary area with the marked creature is not joining a formation.

    The marked attacker leaves a 10-foot area (not a formation array) covering itself and an uninvolved
    creature of its own side; that creature commanded nothing, aided nothing and keeps no formation up."""
    from combat import zones

    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK],
                               cause=[{"type": "zone"}, STR_SAVE], cause_target="SELF",
                               cause_zone_spec=ORDINARY_AREA, witness_position={"x": 4, "y": 7})
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    keeper, rider, bystander = (engine.state.actors[key] for key in (LEFT, RIGHT, WITNESS))
    areas = [zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == RIGHT]
    assert areas, "the fixture must leave an ordinary area behind"
    assert all(zones.actor_inside_zone(engine, rider, zone)
               and zones.actor_inside_zone(engine, bystander, zone) for zone in areas)
    assert not earth._in_hostile_formation(engine, keeper, rider, bystander)
    assert earth._score_candidates(engine, keeper, rider) == []
    assert marks_on(engine, LEFT) == [RIGHT]

def test_ground_keeps_score_accepts_a_bystander_inside_a_real_formation(tmp_path):
    """Finding 2, the other half: a real formation array held by the owner's enemies still qualifies."""
    from combat.ext import formations

    def patterns(document, aid):
        if aid == RIGHT:
            document["spheres_and_talents"]["formation_patterns"] = ["Locking Gate"]

    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK],
                               cause=[STR_SAVE], cause_target="SELF", right_talents=[SET_ARRAY],
                               right_spheres=["tianxia.sphere.formations"], sheet_edit=patterns,
                               witness_position={"x": 4, "y": 7})
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    result = settle(cell_send(combat, table, mid, "Combat Array: Locking Gate", (4, 6)))[0]
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert formations.arrays(engine), "the fixture must set a real formation array"
    keeper, rider, bystander = (engine.state.actors[key] for key in (LEFT, RIGHT, WITNESS))
    assert earth._in_hostile_formation(engine, keeper, rider, bystander)
    result = act(table, mid, "Cause")
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert "The Ground Keeps Score" in str(prompt)
    result = act(table, mid, "Cause", [{**prompt["context"], "selection": "USE", "option_ids": [WITNESS]}])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert marks_on(engine, LEFT) == [WITNESS]