"""One height seam: the default self-teleport query walks the standing levels Gate4's menu walks.

A raised square is a landing only when falling.can_stand accepts it (a solid top or roof), never free air.
The default query and the canonical menu must agree on every raised landing.
"""
from combat import falling
from combat.ext.teleport_steps import destinations, standing_levels
from combat.gate2_runtime_models import Position
from tests.test_a2_elevated_teleport_destinations import elevated_map
from tests.test_a2_teleport_standable_squares import WHERE
from tests.test_a2r23_athletics_map import FIGHTER, engine_of, table_fight

TOP = Position(x=8, y=4, z=6)   # the authored tree's clear top: base 20 ft + height 10 ft


def test_default_query_offers_the_supported_raised_top_and_no_free_air(tmp_path):
    combat, table, mid = table_fight(tmp_path, [], map_doc=elevated_map(10), where=WHERE)
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert set(standing_levels(engine)) == set(range(engine.grid.altitude_ceiling_z + 1))
    assert falling.can_stand(engine, fighter, TOP)
    cells = destinations(engine, fighter, 200)
    assert TOP in cells, "a supported raised top is a landing for the default query"
    assert all(falling.can_stand(engine, fighter, cell) for cell in cells if cell.z), "no free air offered"
