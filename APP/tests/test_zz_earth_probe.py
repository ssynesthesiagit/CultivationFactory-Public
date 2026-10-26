"""Temporary diagnostic probe for MMXAUTO-EARTH1F8 (deleted after the run)."""
import pytest

import combat.surface_contact as contact
from combat.ext import earth_responses as earth
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, fight, reload, turn

WITNESS = "actor:factory.auto111-witness"
MARK = {"type": "mark", "mark": "Burden Mark", "applies_to": "target", "duration": {"kind": "until_removed"}}
AC_BONUS = {"type": "ac_bonus", "flat": 1000, "applies_to": "self", "duration": "until_removed"}
GROUND_SCORE = "TAL_EARTH_THE_GROUND_KEEPS_SCORE"
DEEP_ROOT = "TAL_EARTH_DEEP_ROOT_STANCE"
STANDARD = "WARLEADER_BASE_SET_THE_STANDARD"
BRUTE_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
RAISED = [{"region_id": "raised-floor", "terrain_type": "BLOCKED", "movement_cost": 0, "height_ft": 10,
           "cells": [{"x": x, "y": y} for x in range(2, 7) for y in range(4, 9)]}]


def raised_arena(arena):
    arena["terrain_regions"] = [dict(r) for r in RAISED]


def board(engine):
    return {aid: (a.position.x, a.position.y, a.position.z, a.team_id)
            for aid, a in engine.state.actors.items() if a.active}


def groups(table, mid):
    menu = table.state(mid)["menu"]
    return [(g["label"], str(g.get("source_definition_id"))[-24:],
             [[o.get("target_ids") for o in g["options"]]])
            for g in menu["actions"]]


def test_probe_surfaces(tmp_path):
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK, AC_BONUS],
                               witness_talents=[STANDARD], arena_edit=raised_arena,
                               positions={LEFT: {"x": 3, "y": 6, "z": 2}, RIGHT: {"x": 4, "y": 6, "z": 2}},
                               witness_position={"x": 7, "y": 6, "z": 0})
    engine = reload(combat, mid)
    left, right, witness = (engine.state.actors[k] for k in (LEFT, RIGHT, WITNESS))
    assert False, (board(engine), contact.connected(engine, left, right),
                   contact.connected(engine, right, witness),
                   [a.entity_id for a in earth._score_candidates(engine, left, right)])


def test_probe_shove_enemy(tmp_path):
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK],
                               right_talents=[BRUTE_SHOVE], right_spheres=["tianxia.sphere.brute"],
                               witness_talents=[STANDARD])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, WITNESS)
    assert act(table, mid, "Set the Standard")["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert False, (board(engine), groups(table, mid))


def test_probe_deep_root(tmp_path):
    combat, table, mid = fight(tmp_path, [GROUND_SCORE, DEEP_ROOT], extra_witness=True, prepare=[MARK],
                               right_talents=[BRUTE_SHOVE], right_spheres=["tianxia.sphere.brute"],
                               witness_talents=[STANDARD])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, WITNESS)
    assert act(table, mid, "Set the Standard")["status"] == "COMMITTED"
    turn(table, mid, LEFT)
    assert False, (table.state(mid)["menu"]["actor_id"], groups(table, mid))
