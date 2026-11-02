"""F10 regressions for lighting sight geometry and scalar field projection."""
from combat import lighting, senses
from combat.gate2_runtime_models import Position
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload


POSITIONS = {OWNER: {"x": 1, "y": 1}, ALLY: {"x": 1, "y": 6}, FOE: {"x": 6, "y": 1}}


def test_ground_light_passes_under_elevated_blocking_span(tmp_path):
    elevated = {"material": "terrain:stone", "terrain_type": "BLOCKED",
                "cells": [{"x": 4, "y": 1}], "base_altitude_ft": 10, "height_ft": 5}
    doc = map_document(12, 8, ambient=ambient_light("night"), lights=[light(2, 1)], materials=[elevated])
    _, _, match_id = fight(tmp_path, doc, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, match_id)

    assert lighting.base(engine, 6, 1) == lighting.BRIGHT


def test_no_light_data_preserves_existing_airborne_creature_sight(tmp_path):
    doc = map_document(12, 8)
    _, _, match_id = fight(tmp_path, doc, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, match_id)
    viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    viewer.position = Position(x=1, y=1, z=1)
    target.position = Position(x=6, y=1, z=2)

    assert not lighting.declared(engine)
    assert senses.physical_sight(engine, viewer, target)
    assert senses.perceives(engine, viewer, target)


def test_perceived_field_is_scalar_answer_for_each_map_cell_altitude(tmp_path):
    doc = map_document(12, 8, ambient=ambient_light("night"))
    _, _, match_id = fight(tmp_path, doc, senses=[{"sense": "darkvision", "range_ft": 20}],
                           positions=POSITIONS)
    engine = reload(tmp_path, match_id)
    viewer = engine.state.actors[OWNER]
    viewer.position = Position(x=1, y=1, z=4)

    field = lighting.seen_field(engine, viewer)
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            assert field[(x, y)] == lighting.seen_level(engine, viewer, Position(x=x, y=y, z=0))
