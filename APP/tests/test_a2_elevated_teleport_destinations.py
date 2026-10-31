"""Authored elevated-base terrain must not hide landings or rope anchors."""
import pytest

from combat.candidate_knowledge import query
from combat.ext.needle import cell_id
from combat.ext.teleport_steps import destinations
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOE, ROPE, ROPE_SWING, SWING,
    answer_for, engine_of, find, passive_fixture, play, table_fight,
)


def elevated_map(height):
    # An authored tree uses a thin cross-shaped sight blocker but a solid
    # movement cell. Look diagonally at its clear top, not through either arm;
    # a full-cell crate instead hides its exact top from a viewer below it.
    # Rasterization must preserve the absolute BLOCKED span (20, 20 + height).
    return {
        "display_name": "Raised canopy",
        "width_squares": 12, "height_squares": 8, "walls": [],
        "trees": [{"x": 8, "y": 4, "size": 1, "height_ft": height,
                   "base_altitude_ft": 20, "occluder": "centerline"}],
        "starts": {"team1": [[1, 3]], "team2": [[10, 7]]},
    }


def choose_cell(wanted, seen):
    def answer(prompt):
        options = [row["id"] for row in (prompt.get("choice") or {}).get("options") or []]
        if any(option.startswith("cell:") for option in options):
            assert wanted in options, "the player must be offered the elevated endpoint"
            seen.append(prompt)
            return {**prompt["context"], "selection": "USE", "option_ids": [wanted]}
        return answer_for(prompt)
    return answer


@pytest.mark.parametrize("height, level", [(10, 6), (11, 7)])
def test_authored_elevated_platform_flash_step_for_player_and_ai(tmp_path, height, level):
    combat, table, mid = table_fight(
        tmp_path, [FLASH_STEP, "TAL_ATHLETICS_SPEED_BOOST"], map_doc=elevated_map(height),
        bundle_transform=passive_fixture("TAL_ATHLETICS_SPEED_BOOST", "speed_boost",
                                        action_extra_ft=10, boost_ft=50),
        where={FIGHTER: {"x": 1, "y": 3}, FOE: {"x": 10, "y": 7}})
    engine = engine_of(combat, mid)
    actor = engine.state.actors[FIGHTER]
    landing = Position(x=8, y=4, z=level)
    assert engine.grid.terrain_spans["BLOCKED"][8, 4] == [(20, 20 + height)]
    assert engine.grid.placement_legal(landing, footprint=engine._footprint(actor),
                                       occupied_cells=engine._occupied_cells_except(FIGHTER))
    assert engine._line_of_sight_actor_to_cell(actor, landing), "fixture landing must be visible"
    assert landing in destinations(engine, actor, 40)
    # Both canonical menus and the AI's observed-knowledge menu retain this
    # legal choice. No model/embedding client is involved in generating either.
    for observed in (False, True):
        if observed:
            with query(engine):
                candidates = engine.legal_candidates()
        else:
            candidates = engine.legal_candidates()
        assert any("flash_step" in row.source_definition_id and row.destination == landing
                   for row in candidates)
    prompts = []
    play(table, mid, find(table, mid, "flash_step"),
         answer=choose_cell(cell_id(landing), prompts))
    assert prompts, "the manual owner chooses the landing"
    assert engine_of(combat, mid).state.actors[FIGHTER].position == landing


@pytest.mark.parametrize("height, level", [(10, 6), (11, 7)])
def test_authored_elevated_platform_rope_anchor_offered_and_persisted(tmp_path, height, level):
    combat, table, mid = table_fight(
        tmp_path, [ROPE_SWING], kit=ROPE, map_doc=elevated_map(height),
        where={FIGHTER: {"x": 1, "y": 3}, FOE: {"x": 10, "y": 7}})
    anchor = Position(x=8, y=4, z=level)
    prompts = []
    play(table, mid, find(table, mid, ROPE_SWING),
         answer=choose_cell(cell_id(anchor), prompts))
    assert prompts, "the manual owner chooses the anchor"
    actor = engine_of(combat, mid).state.actors[FIGHTER]
    swing = next(condition for condition in actor.conditions.values() if condition.condition_id == SWING)
    assert swing.data["anchor"] == [8, 4, level]


@pytest.mark.parametrize("roof_height, ceiling", [(None, 7), (40, 8)])
def test_absolute_top_survives_overlapping_infinite_column_and_roof(roof_height, ceiling):
    # A merged thickness index loses the finite height when an infinite column
    # shares the cell. The constructor's independent spans retain the real top.
    regions = [
        {"terrain_type": "BLOCKED", "cells": [{"x": 2, "y": 2}], "movement_cost": 1,
         "base_altitude_ft": 20, "height_ft": 11},
        {"terrain_type": "BLOCKED", "cells": [{"x": 2, "y": 2}], "movement_cost": 1},
    ]
    roofs = [] if roof_height is None else [
        {"id": "high-roof", "height_ft": roof_height, "cells": [{"x": 3, "y": 3}]}]
    grid = SquareGrid({
        "width_squares": 6, "height_squares": 6, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": regions, "roof_surfaces": roofs,
    })
    assert grid.terrain_heights["BLOCKED"][2, 2] is None
    assert grid.altitude_ceiling_z == ceiling
