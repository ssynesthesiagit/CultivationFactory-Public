"""BRS1F15R blocking finding: Night-Bound Body's Frightened-save Advantage has its printed gate.

The print gates all three Night-Bound bullets on "While standing inside Dim Light or your Darkness".
Clause 5 (Advantage on saving throws against Frightened) was compiled with when=["always"], so a Dark
Body Refiner in Bright Light, or with no light at all, gained Advantage it does not have. The test
drives the real engine light and zone path and fails on the unfixed data.
"""
from combat import zones
from combat.gate2_runtime_models import Position, ZoneState
from combat.ext import br_variants as bv
from tests.test_auto_support import ME, _engine
from combat.factory_compiler import compile_character
from tests.body_refining_support import sheet


def _dark_engine():
    bundle = compile_character(sheet(spheres=["tianxia.sphere.dark"]), actor_id=ME)
    return _engine(bundle)


def _area(engine, zone_id, profile, owner):
    me = engine.state.actors[ME]
    cells = tuple(Position(x=c[0], y=c[1])
                  for c in engine.grid.footprint_cells(me.position, engine._footprint(me.entity_id)))
    engine.state.zones[zone_id] = ZoneState(
        zone_id=zone_id, source_definition_id="test:" + zone_id, owner_id=owner.entity_id, center=me.position,
        radius_cells=0, affected_cells=cells, concentration_link=False, duration_rounds=None,
        created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "difficult": None, "triggers": [], "inside": [], "numbers": {},
                         **profile})
    zones.sync_inside(engine, "test:" + zone_id)


def _frightened_modes(engine):
    me = engine.state.actors[ME]
    ctx = type("Ctx", (), {"engine": engine})()
    result = bv.rider_saves(ctx, me, "WIS", {"frightened"})
    return result["modes"] if result else []


def test_night_bound_frightened_save_advantage_needs_dim_light_or_own_darkness():
    engine = _dark_engine()
    me = engine.state.actors[ME]
    foe = next(actor for actor in engine.state.actors.values() if actor is not me)

    # No light at all: the printed gate is not met, so no Advantage (the unfixed data granted it).
    assert _frightened_modes(engine) == []

    # Bright Light is not Dim Light: still no Advantage.
    _area(engine, "zone:test.bright", {"name": "Sunlight",
          "visual": {"material": "radiance", "light": {"radius_ft": 20, "level": "bright"}}}, foe)
    assert _frightened_modes(engine) == []
    zones.remove(engine, engine.state.zones["zone:test.bright"], "test")

    # Dim Light grants it.
    _area(engine, "zone:test.dim", {"name": "Candlelight",
          "visual": {"material": "wax", "light": {"radius_ft": 10, "level": "dim"}}}, foe)
    assert _frightened_modes(engine) == ["ADVANTAGE"]
    zones.remove(engine, engine.state.zones["zone:test.dim"], "test")

    # The creature's own Darkness also grants it.
    _area(engine, "zone:test.dark", {"name": "Night's Darkness",
          "visual": {"material": "darkness", "darkness": True}}, me)
    assert _frightened_modes(engine) == ["ADVANTAGE"]
