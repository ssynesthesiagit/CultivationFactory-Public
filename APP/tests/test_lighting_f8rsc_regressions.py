"""Regressions for the two LIGHTS1F8RSC sight/light mismatches."""
from combat import lighting, senses
from combat.gate2_runtime_models import Position, ZoneState
from combat.footprints import native_actor_footprint
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload


NIGHT = ambient_light("night")
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 9, "y": 6}}


def test_centerline_terrain_blocks_light_and_sight_through_the_same_geometry(tmp_path):
    material = {"material": "terrain:bamboo thicket", "cells": [[4, 2]],
                "height_ft": 20, "occluder": "centerline"}
    document = map_document(12, 8, ambient=NIGHT, lights=[light(2, 2)], materials=[material])
    _, _, mid = fight(tmp_path, document, senses=[], positions=POSITIONS)
    engine = reload(tmp_path, mid)
    viewer = engine.state.actors[OWNER]

    assert lighting.base(engine, 6, 2) == lighting.DARK
    assert not senses.perceives_cell(engine, viewer, Position(x=6, y=2, z=0))

    clear_document = map_document(12, 8, ambient=NIGHT, lights=[light(2, 2)])
    _, _, clear_mid = fight(tmp_path / "clear", clear_document, senses=[], positions=POSITIONS)
    clear_engine = reload(tmp_path / "clear", clear_mid)
    assert lighting.base(clear_engine, 6, 2) == lighting.BRIGHT
    assert senses.perceives_cell(clear_engine, clear_engine.state.actors[OWNER], Position(x=6, y=2, z=0))


def test_airborne_darkvision_field_projects_to_ground_like_scalar_query(tmp_path, monkeypatch):
    document = map_document(12, 8, ambient=NIGHT)
    _, _, mid = fight(tmp_path, document, senses=[{"sense": "darkvision", "range_ft": 10}],
                      positions=POSITIONS)
    engine = reload(tmp_path, mid)
    viewer = engine.state.actors[OWNER]
    viewer.position = Position(x=2, y=2, z=4)

    ground = lighting.seen_level(engine, viewer, Position(x=2, y=2, z=0))
    field = lighting.seen_field(engine, viewer)
    assert ground == lighting.DARK
    assert field[(2, 2)] == ground
    assert lighting.seen_level(engine, viewer, Position(x=2, y=2, z=4)) == lighting.DIM

    # A distant Pure Darkness area switches the field to scalar resolution without changing this ground answer.
    zone = ZoneState(zone_id="test:pure-darkness", source_definition_id="test:pure-darkness", owner_id=FOE,
                     center=Position(x=9, y=6), radius_cells=1,
                     affected_cells=(Position(x=9, y=6),), concentration_link=False, created_round=0,
                     trigger_profile={"talents": ["Pure Darkness"],
                                      "visual": {"darkness": True, "ordinary": True, "magical": False}})
    monkeypatch.setattr("combat.zones.typed_zones", lambda _engine: [zone])
    monkeypatch.setattr("combat.zones.heavy_zones", lambda _engine: (zone,))
    monkeypatch.setattr("combat.zones._heavy", lambda _engine: [zone])
    assert lighting.seen_level(engine, viewer, Position(x=2, y=2, z=0)) == ground
    assert lighting.seen_field(engine, viewer)[(2, 2)] == ground
