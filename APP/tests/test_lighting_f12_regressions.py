"""Creature sight and light propagation must not share endpoint-policy cache entries."""
import pytest

from combat import lighting
from tests.lighting_support import FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload


@pytest.mark.parametrize("first", ["sight", "light"])
def test_centerline_endpoint_cache_respects_both_policies_in_either_order(tmp_path, first):
    material = {"material": "terrain:bamboo thicket", "cells": [[4, 2]],
                "height_ft": 20, "occluder": "centerline"}
    document = map_document(12, 8, ambient=ambient_light("night"), lights=[light(2, 2)],
                            materials=[material])
    positions = {OWNER: {"x": 2, "y": 2, "z": 0}, FOE: {"x": 4, "y": 2, "z": 0}}
    _, _, match_id = fight(tmp_path, document, senses=[], positions=positions)
    engine = reload(tmp_path, match_id)
    start = engine.state.actors[OWNER].position
    end = engine.state.actors[FOE].position
    assert (4, 2) in engine.grid.centerline_cells

    # Setup may ask sight/light questions. Start cold once, then leave this
    # same grid/cache intact across both policies and their repeated queries.
    engine.grid._centerline_sight_cache.clear()
    order = ["sight", "light"] if first == "sight" else ["light", "sight"]
    for query in order * 2:
        if query == "sight":
            # A creature can see the near face of occupied endpoint terrain.
            assert engine.grid.line_of_sight(start, end)
        else:
            # Light cannot enter that terrain, even with identical endpoints.
            assert lighting.base(engine, end.x, end.y) == lighting.DARK
