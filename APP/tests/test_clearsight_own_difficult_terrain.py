"""Clearsight protects its holder from talent-created Darkness terrain."""
import pytest

from combat import flight, senses, zones
from combat.ext import docket_senses
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_darkness_and_stealth import DARKNESS_KIT, ME, MELD_SOURCE, ROOT, _do
from tests.test_zones import SHEET


@pytest.mark.parametrize("shape", ["Pure Darkness", "plain Darkness"], ids=["shaped", "bare"])
def test_clearsight_own_thick_darkness_step_cost(shape):
    # Adapt the existing Darkness table fixture's kit and Meld grant to a
    # synthetic engine, with both creatures standing in the same area.
    sheet = {**SHEET, "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.dark"],
        "learned_talent_record_ids": DARKNESS_KIT + ["TAL_DARK_CLEARSIGHT", "TAL_DARK_THICK_DARKNESS"],
    }}
    engine = Gate4ControllerEngine(
        ROOT, match_seed="CLEAR-TERRAIN",
        typed_bundles=(compile_character(sheet, actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 5, "y": 6}}},
    )
    caster, foe = engine.state.actors[ME], engine.state.actors[AN]
    docket_senses.meld_set(type("Grant", (), {"engine": engine, "actor": caster, "source": MELD_SOURCE})(),
                           {"talent": "TAL_DARK_CLEARSIGHT", "name": "Clearsight", "concentration": False})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _do(engine, f"Shape Darkness: {shape}")
    _do(engine, "Darkness", at=(4, 6))
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["difficult"] == "all"
    assert zone.trigger_profile["talents"] == (["Pure Darkness"] if shape == "Pure Darkness" else [])
    assert "Thick Darkness" in zone.trigger_profile["modified_by"]

    def cost(actor):
        destination = Position(x=actor.position.x, y=actor.position.y + 1)
        assert (destination.x, destination.y) in {(cell.x, cell.y) for cell in zone.affected_cells}
        return flight.step_cost(engine, actor, actor.position, destination, "walk",
                                engine._hostile_difficult_cells(actor))

    assert senses.meld_active(engine, caster, "TAL_DARK_CLEARSIGHT")
    assert not zones.zone_is_difficult(engine, zone, caster)
    assert zones.zone_is_difficult(engine, zone, foe)
    assert cost(caster) == 5
    assert cost(foe) == 10
