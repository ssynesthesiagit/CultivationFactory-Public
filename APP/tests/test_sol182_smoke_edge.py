"""Smoke Veil edge regressions through the real Pillar Arena table and disk."""
import copy
import importlib
import json
from types import SimpleNamespace

import pytest

from combat.ext import smoke_veil
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests import test_auto43r1f1_smoke_table as t


EDGE_POINTS = [(0, 7), (19, 7), (10, 0), (10, 13),
               (0, 0), (19, 0), (0, 13), (19, 13)]


def _edge_fight(tmp_path, at, cl, *, no_room=False):
    x, y = at
    owner_at = {"x": max(1, min(18, x)), "y": max(1, min(12, y))}
    secondary = FACTORY_ACTOR_PREFIX + "r1f1-second"
    positions = {t.OWNER: owner_at, t.FOE: {"x": 3, "y": 10}, secondary: {"x": 16, "y": 2}}
    arena = None
    if no_room:
        arena = copy.deepcopy(CombatService(t.ROOT, tmp_path).factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"])
        free = {at, *((p["x"], p["y"]) for p in positions.values())}
        arena["terrain_regions"] = [{"region_id": "sol182-no-room", "terrain_type": "BLOCKED",
                                     "movement_cost": 0, "description": "Solid arena walls",
                                     "cells": [{"x": cx, "y": cy} for cx in range(20) for cy in range(14)
                                               if (cx, cy) not in free]}]
    return t._fight(tmp_path, [t.SECOND], cl=cl, positions=positions, arena=arena)


@pytest.mark.parametrize("at", EDGE_POINTS, ids=["west", "east", "north", "south", "nw", "ne", "sw", "se"])
@pytest.mark.parametrize("cl,area_cells", [(4, 1), (5, 4)])
def test_second_veil_at_every_edge_and_corner_commits_and_reloads(tmp_path, at, cl, area_cells):
    combat, table, mid = _edge_fight(tmp_path, at, cl)
    prompts = t._asked_for(table, mid, t._veil_candidate(table, mid, at={"x": at[0], "y": at[1]}), take=True)
    assert prompts and "Second Veil" in prompts[0]["moment"]
    session = combat._load_session(mid)
    engine = session.engine
    assert smoke_veil.whole_cube_placement(engine)
    first, = [z for z in smoke_veil.veils(engine, engine.state.actors[t.OWNER]) if not z.trigger_profile.get("second_veil")]
    extra, = [z for z in smoke_veil.veils(engine, engine.state.actors[t.OWNER]) if z.trigger_profile.get("second_veil")]
    assert len(extra.affected_cells) == area_cells
    assert engine.grid.distance_ft(first.center, extra.center) <= 30
    # Check every offered square, not merely the option selected for this commit.
    half = 0 if cl == 4 else 1
    for option in prompts[0]["choice"]["options"]:
        from combat.ext.needle import position_of
        cell = position_of(option["id"])
        footprint = {(cell.x + dx, cell.y + dy) for dx in range(-half, 1) for dy in range(-half, 1)}
        assert all(engine.grid.in_bounds(p) for p in footprint)
        assert not footprint & set(engine.grid.blocked)
    saved = extra.model_dump(mode="json")
    fresh = CombatService(t.ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.zones[extra.zone_id].model_dump(mode="json") == saved
    assert smoke_veil.whole_cube_placement(fresh.engine)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_no_room_leaves_only_the_original_veil_and_explains_why_after_reload(tmp_path):
    combat, table, mid = _edge_fight(tmp_path, (0, 0), 5, no_room=True)
    t._commit(table, mid, t._veil_candidate(table, mid, at={"x": 0, "y": 0}), take=True)
    fresh = CombatService(t.ROOT, tmp_path)._load_session(mid)
    assert len(smoke_veil.veils(fresh.engine, fresh.engine.state.actors[t.OWNER])) == 1
    text = " ".join(e.payload.get("rider", "") for e in fresh.engine.events if e.event_type == "GM_RIDER")
    assert "Second Veil: no second 10-foot cube of smoke is created" in text
    assert "unblocked space within 30 feet" in text and "whole cube inside the battlefield" in text
    assert fresh.verify()["status"] == fresh.mechanical.replay()["status"] == "PASS"


def test_unstamped_fight_keeps_the_old_clipped_cube_options():
    s = importlib.import_module("tests.test_auto43_smoke_veil")
    engine, actor, _ = s._fight([s.SECOND], cl=5)
    for event in engine.events:
        event.payload.pop("smoke_cube_placement_policy", None)
    veil = SimpleNamespace(center=actor.position.model_copy(update={"x": 10, "y": 0}))
    ctx = SimpleNamespace(engine=engine, actor=actor)
    old = smoke_veil._free_squares(ctx, veil, 30, 10)
    assert any(p.y == 0 for p in old)
    next(e for e in engine.events if e.event_type == "MATCH_CREATED").payload["smoke_cube_placement_policy"] = 1
    new = smoke_veil._free_squares(ctx, veil, 30, 10)
    assert all(p.y >= 1 for p in new)


def test_the_three_earth_riders_name_the_ability_beneficiary_and_duration():
    earth = importlib.import_module("tests.test_review_sw-earth")
    _, engine, _, _ = earth.fight("TAL_EARTH_OX_BEARING_FOUNDATION", cl=5,
                                extras=("TAL_EARTH_DEEP_ROOT_STANCE",))
    earth.cast(engine, "Deep Root Stance")
    text = " ".join(e.payload.get("rider", "") for e in engine.events if e.event_type == "GM_RIDER")
    assert "Typed before as" not in text
    assert "Deep Root Stance: until the start of your next turn" in text
    assert "Ox-Bearing Foundation:" in text and "you reduce damage taken by the chosen willing ally" in text
    assert "the chosen willing ally" in text and "gains Advantage on ability checks and saving throws" in text
    assert "same surface" in text and "costs no extra resource" in text
    assert "Advantage on being moved or knocked Prone" not in text
