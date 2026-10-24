"""BRS1F21 regressions: zone-gated Body Refining riders read the real zones the engine makes, and a
free-use grant carries its printed variant title (never the internal authority id).

Zones are shaped the way their producers write them: ash_core and the terrain producers put the
typed terrain name in ``trigger_profile["terrain"]`` ("ash terrain", "fire terrain", "shallow sand terrain")
and the element in ``trigger_profile["visual"]["material"]``.
"""
from types import SimpleNamespace

from combat import zones
from combat.ext import air_currents, br_variants as bv, free_uses
from combat.gate2_runtime_models import Position, ZoneState
from factory_authoring import body_refining_variants as authority
from tests.body_refining_support import sheet
from tests.test_auto_support import ME, _engine
from combat.factory_compiler import compile_character


def _area(engine, me, zone_id, profile, owner):
    cells = tuple(Position(x=cell[0], y=cell[1])
                  for cell in engine.grid.footprint_cells(me.position, engine._footprint(me.entity_id)))
    engine.state.zones[zone_id] = ZoneState(
        zone_id=zone_id, source_definition_id="test:" + zone_id, owner_id=owner.entity_id, center=me.position,
        radius_cells=0, affected_cells=cells, concentration_link=False, duration_rounds=None,
        created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "difficult": None, "triggers": [], "inside": [], "numbers": {},
                         **profile})
    zones.sync_inside(engine, "test:" + zone_id)
    return engine.state.zones[zone_id]


def _world(sphere_id):
    bundle = compile_character(sheet(spheres=[sphere_id]), actor_id=ME)
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    foe = next(actor for actor in engine.state.actors.values() if actor is not me)
    return engine, me, foe


def test_ash_terrain_satisfies_the_ash_zone_gate():
    engine, me, foe = _world("tianxia.sphere.ash")
    assert not bv._zone(engine, me, "ash")
    _area(engine, me, "zone:test.ash", {"name": "Ash Terrain", "terrain": ["ash terrain"],
                                         "visual": {"material": "ash"}}, foe)
    assert bv._zone(engine, me, "ash")


def test_ash_painted_on_the_map_satisfies_the_ash_zone_gate():
    """BRS1F21R: terrain painted on the tabletop map (battlefield_document["map_terrain"], read by zones.map_zones)
    is real Ash ground too, not only zones the engine stores in engine.state.zones."""
    engine, me, foe = _world("tianxia.sphere.ash")
    engine.battlefield_document = {"map_terrain": [{"terrain": "ash terrain", "cells": [[me.position.x, me.position.y]]}]}
    engine.__dict__.pop("_map_zones", None)
    assert not engine.state.zones
    assert bv._zone(engine, me, "ash")


def test_fire_terrain_satisfies_the_fire_zone_gate():
    engine, me, foe = _world("tianxia.sphere.fire")
    _area(engine, me, "zone:test.fire", {"name": "Fire Terrain", "terrain": ["fire terrain"],
                                          "visual": {"material": "fire"}}, foe)
    assert bv._zone(engine, me, "fire")


def test_sand_terrain_gate_is_owner_scoped_sand_terrain():
    engine, me, foe = _world("tianxia.sphere.sand")
    _area(engine, me, "zone:test.sand.foe", {"name": "Sand", "terrain": ["shallow sand terrain"],
                                              "visual": {"material": "sand"}}, foe)
    assert bv._zone(engine, me, "sand") and not bv._zone(engine, me, "sand:own")
    _area(engine, me, "zone:test.sand.own", {"name": "Sand", "terrain": ["shallow sand terrain"],
                                              "visual": {"material": "sand"}}, me)
    assert bv._zone(engine, me, "sand:own")


def test_a_sandstone_name_is_not_sand_terrain():
    engine, me, foe = _world("tianxia.sphere.sand")
    _area(engine, me, "zone:test.hall", {"name": "Sandstone Hall", "visual": {"material": "stone"}}, me)
    assert not bv._zone(engine, me, "sand:own")


def test_own_air_current_satisfies_the_current_gate(monkeypatch):
    engine, me, foe = _world("tianxia.sphere.air")
    zone = _area(engine, me, "zone:test.current", {"name": "Air Current", "terrain": [], "visual": {"material": "wind"}}, me)
    assert not bv._zone(engine, me, "current:own")
    monkeypatch.setattr(air_currents, "currents", lambda eng, owner: [zone] if owner is me else [])
    assert bv._zone(engine, me, "current:own")
    assert not bv._zone(engine, foe, "current:own")


def test_free_use_grant_carries_its_printed_variant_title_not_the_authority_id():
    """The funding prompt names the printed variant (its picker label), never the internal authority id."""
    from combat.ext import free_uses as fu
    from combat.ext.br_variants import _free_use_declarations
    from tests.test_body_refining_riders import sphere, variants

    _rows, bundle = variants(sphere("tianxia.sphere.air", talents=["AIR_BASE_GATHER_CURRENT"]))
    free = [action for action in bundle["action_catalog"] if "Gather Current" in action["display_name"]
            and action["display_name"].endswith("(free)")]
    grant = free[0]["parameters"]["free_use"]
    assert grant.get("title"), "the grant carries the printed title"
    assert "tianxia.brvariant" not in grant["title"] and not grant["title"].startswith("br_variant:")
    assert fu.grant_label(grant) == grant["title"]
    assert "tianxia.brvariant" not in fu.grant_label(grant)
    assert grant["title"] == authority.variant(grant["state"].split(":", 1)[1])["picker_label"]
