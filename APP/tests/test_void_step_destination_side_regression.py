"""An occupied far-side landing must never recover through the wall to departure."""
from dataclasses import replace

from combat.ext import teleport_steps
from combat.ext import void_touched_cultivator as void
from combat.typed_executor import teleport_subject
from tests.void_family_support import acquired, bundle, step_action, step_context
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload


def test_occupied_destination_with_no_far_side_space_stays_at_departure(acquired, tmp_path, monkeypatch):
    service, project = acquired

    def wall(arena):
        arena["terrain_regions"].append({
            "region_id": "test.wall", "terrain_type": "BLOCKED", "movement_cost": 0,
            "description": "Ordinary stone wall and blocked far-side alternatives",
            "cells": [{"x": x, "y": y} for x in range(4, 8) for y in range(4, 9)
                      if (x, y) != (5, 6)]})

    # The landing was surveyed earlier; this isolates post-selection recovery
    # from the separate destination-knowledge rule.
    monkeypatch.setattr(void, "precisely_known", lambda engine, actor, cell: (cell.x, cell.y) == (5, 6))
    real_ask = teleport_steps.ask_destination

    def occupied_after_choice(ctx, reach, **kwargs):
        result = real_ask(ctx, reach, **kwargs)
        if result.square is not None and void.family_source(ctx.action) == void.VOID_STEP:
            # Native evented arrival AFTER the player selects the legal square.
            foe = ctx.engine.state.actors[FOE]
            action = ctx.action.model_copy(update={"parameters": {"typed": {"source": "test.arrival"}}})
            teleport_subject(replace(ctx, actor=foe, action=action, typed={}), foe, result.square)
        return result

    monkeypatch.setattr(teleport_steps, "ask_destination", occupied_after_choice)
    combat, table, mid = fixture(
        tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 15, "y": 10}, FOE: {"x": 15, "y": 12}},
        battlefield_transform=wall, seed="VOID-STEP-DESTINATION-SIDE")
    before = reload(tmp_path, mid)
    original = before.state.actors[OWNER].position
    qi = before.state.actors[OWNER].resources["resource:core.qi"]
    settle(table, mid, candidate(combat, mid, "Void Step", at=(5, 6)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:5,6"]})
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (5, 6)
    assert engine.state.actors[OWNER].position == original
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == qi - 2
    assert not engine.state.actors[OWNER].bonus_action_available
