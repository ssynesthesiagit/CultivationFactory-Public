"""F23: a teleport or Flash Step landing must be a square the creature can stand on.

A free volume is not a place to stand. An aerial square is a landing only when
something carries the creature there (ground, a roof, a raised top, a carrying
medium) or a flight or hold keeps it up. That is the question falling.required
asks, so the enumerators ask it too. Labels never decide legality.
"""
import pytest

from combat import falling
from combat.candidate_knowledge import query
from combat.ext.teleport_steps import destinations
from combat.gate2_runtime_models import Position
from tests.test_a2_athletics_table_reloads import setup
from tests.test_a2_elevated_teleport_destinations import elevated_map
from tests.test_a2r23_athletics_map import (
    FIGHTER, FLASH_STEP, FOE, engine_of, passive_fixture, table_fight,
)

WHERE = {FIGHTER: {"x": 1, "y": 3}, FOE: {"x": 10, "y": 7}}
AIR_BESIDE_FIGHTER = Position(x=2, y=3, z=1)   # free air one level up, next to the fighter


def test_open_ground_offers_no_aerial_landing(tmp_path):
    # The walking fighter stands on a finite-height map. The open square beside
    # it one level up is free air: it must not be offered, and nothing above
    # open ground may be offered at all.
    combat, table, mid = table_fight(tmp_path, [], map_doc=elevated_map(10), where=WHERE)
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert engine.grid.finite_heights, "fixture: the map has standing levels to test"
    assert not falling.can_stand(engine, fighter, AIR_BESIDE_FIGHTER), "a walker cannot stand in free air"
    cells = destinations(engine, fighter, 200)
    assert AIR_BESIDE_FIGHTER not in cells
    for cell in cells:
        assert falling.can_stand(engine, fighter, cell), f"unsupported aerial landing offered: {cell}"


@pytest.mark.parametrize("height, level", [(10, 6), (11, 7)])
def test_raised_top_of_a_solid_column_is_offered(tmp_path, height, level):
    combat, table, mid = table_fight(tmp_path, [], map_doc=elevated_map(height), where=WHERE)
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    top = Position(x=8, y=4, z=level)
    assert falling.supported(engine, fighter, top), "the solid column carries its own top"
    assert top in destinations(engine, fighter, 40)


def test_flyer_may_hold_open_air(tmp_path):
    # Flight (and Hover/suspension) keeps a creature up, so the same open square is legal.
    combat, table, mid = table_fight(tmp_path, [], map_doc=elevated_map(10), where=WHERE,
                                     bundle_transform=lambda bundles: setup(bundles, fly=60))
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert falling.can_stand(engine, fighter, AIR_BESIDE_FIGHTER), "a flyer can hold open air"
    assert AIR_BESIDE_FIGHTER in destinations(engine, fighter, 40)


def test_prone_flyer_cannot_land_in_open_air(tmp_path):
    combat, table, mid = table_fight(tmp_path, [], map_doc=elevated_map(10), where=WHERE,
                                     bundle_transform=lambda bundles: setup(bundles, fly=60))
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    engine._apply_condition(fighter, "condition:core.prone", "test:prone", FOE, expires_on="UNTIL_REMOVED")
    assert falling.required(engine, fighter), "the flyer's posture makes its Fly Speed unable to keep it aloft"
    assert not falling.can_stand(engine, fighter, AIR_BESIDE_FIGHTER)
    assert AIR_BESIDE_FIGHTER not in destinations(engine, fighter, 40)


@pytest.mark.parametrize("observed", [False, True])
def test_flash_step_menu_offers_raised_top_not_open_air(tmp_path, observed):
    # Canonical and observed-knowledge menus both use the one standable-square rule.
    combat, table, mid = table_fight(
        tmp_path, [FLASH_STEP, "TAL_ATHLETICS_SPEED_BOOST"], map_doc=elevated_map(10), where=WHERE,
        bundle_transform=passive_fixture("TAL_ATHLETICS_SPEED_BOOST", "speed_boost",
                                        action_extra_ft=10, boost_ft=50))
    engine = engine_of(combat, mid)
    if observed:
        with query(engine):
            candidates = engine.legal_candidates()
    else:
        candidates = engine.legal_candidates()
    landings = [row.destination for row in candidates
                if "flash_step" in row.source_definition_id and row.destination is not None]
    assert Position(x=8, y=4, z=6) in landings, "the raised top stays a real choice"
    assert AIR_BESIDE_FIGHTER not in landings
