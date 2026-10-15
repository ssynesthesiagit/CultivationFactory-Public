"""Real capstone surface traversal and height-aware destination labels."""

from combat import falling
from combat.gate2_runtime_models import Position
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOE, ONE_BREATH, engine_of, events, find, play, table_fight,
)
from tests.test_a2r23f_review import KEEP, route


def test_f5_climb_wall_then_cross_roof_edge_air_and_fragile_rubble_at_table(tmp_path):
    arena = {**KEEP, "terrain": [{"type": "DIFFICULT", "look": "broken_tiles", "cells": [[3, 4]]}]}
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH], map_doc=arena,
        where={FIGHTER: {"x": 1, "y": 4}, FOE: {"x": 9, "y": 7}})
    play(table, mid, find(table, mid, ONE_BREATH))
    path = ([{"x": 1, "y": 4, "z": z} for z in range(5)] +
            [{"x": x, "y": 4, "z": 4} for x in range(2, 8)])
    route(table, mid, path, mode="climb")
    engine = engine_of(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert actor.position == Position(x=7, y=4, z=4)
    assert engine.grid.roof_at(7, 4) is None, "the final space is beyond the roof in open air"
    assert falling.supported(engine, actor)
    move = events(engine, "MOVEMENT_COMMITTED", FIGHTER)[-1]
    assert len(move.payload["path"]) == len(path)
    assert move.payload["movement_mode"] == "climb"


def test_f6_elevated_destinations_at_same_xy_have_distinct_labels(tmp_path):
    combat, table, mid = table_fight(tmp_path, [FLASH_STEP], map_doc=KEEP,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 9, "y": 7}})
    engine = engine_of(combat, mid)
    options = [row for row in engine.legal_candidates() if "flash_step" in row.source_definition_id
               and row.destination is not None]
    by_xy = {}
    for option in options:
        by_xy.setdefault((option.destination.x, option.destination.y), []).append(option)
    pairs = [rows for rows in by_xy.values() if len({row.destination.z for row in rows}) > 1]
    assert pairs, "fixture must offer different heights at the same coordinates"
    assert all(len({row.display_name for row in rows}) == len(rows) for rows in pairs)
    for rows in pairs:
        for row in rows:
            height = "ground" if row.destination.z == 0 else f"{row.destination.z * 5} ft up"
            assert row.display_name == f"Flash Step to {row.destination.x},{row.destination.y} ({height})"
    menu = table.state(mid)["menu"]
    labels = {option["candidate_id"]: option["label"]
              for group in menu["actions"] for option in group["options"]}
    assert all(labels[row.candidate_id] == row.display_name for row in options)


def test_f6_single_height_destinations_keep_current_labels(tmp_path):
    combat, table, mid = table_fight(tmp_path, [FLASH_STEP],
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 9, "y": 7}})
    engine = engine_of(combat, mid)
    options = [row for row in engine.legal_candidates() if "flash_step" in row.source_definition_id
               and row.destination is not None]
    assert options
    assert all(row.destination.z == 0 for row in options)
    assert all(row.display_name == f"Flash Step to {row.destination.x},{row.destination.y}" for row in options)
