"""The centre plus is the default sight blocker for map scenery; only square-filling kinds keep a whole square.

Owner 2026-10-23: "plus symbols should be default for most objects so you can see what the object is and it still
blocks the sight." One answer per kind: combat/scenery_sight.py terrain_occluder for painted scenery,
combat/object_rules.py sight for placed objects (combat/rules/objects.json says which kinds are the exception).
The engine then reads the same resolved shape from the source it is given, so the map editor, the table and the
fight cannot disagree.
"""
from __future__ import annotations

from combat import object_rules
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.scenery_sight import SQUARE_FILLING_LOOKS, terrain_occluder
from combat.sight_lines import cross_segments
from combat.tabletop import normalize_map, to_battlefield
from combat.terrain_occlusion import CELL_POLICY, CROSS_POLICY, sight_geometry

BASE = {'display_name': 'plus', 'width_squares': 8, 'height_squares': 8}


def grid_for(terrain, policy=CROSS_POLICY):
    grid = SquareGrid(to_battlefield(normalize_map(dict(BASE, terrain=terrain))))
    grid.bind_occluder_policy(policy)
    return grid


def visible(grid, a, b):
    return grid.line_of_sight(Position(x=a[0], y=a[1]), Position(x=b[0], y=b[1]))


ROCK = [{'type': 'SIMPLE_COVER', 'cells': [[3, 3]], 'look': 'boulder', 'height_ft': 10}]


def test_painted_boulder_blocks_through_its_centre_plus_not_its_whole_square():
    arena = to_battlefield(normalize_map(dict(BASE, terrain=ROCK)))
    region = next(row for row in arena['terrain_regions'] if row['region_id'].startswith('terrain.sight'))
    assert (region['occluder'], region['sight_class']) == ('centerline', 'terrain')
    # The centre row is hidden by the plus; a corner-clipping ray a whole square would have hidden stays clear.
    assert not visible(grid_for(ROCK), (1, 3), (6, 3))
    assert not visible(grid_for(ROCK, CELL_POLICY), (0, 0), (3, 4))
    assert visible(grid_for(ROCK), (0, 0), (3, 4))


def test_square_filling_scenery_looks_keep_the_whole_square():
    assert terrain_occluder({'look': 'low_wall'}) == 'cell'
    assert terrain_occluder({'look': 'palisade'}) == 'cell'
    assert terrain_occluder({'look': 'crag'}) == 'cell'
    assert terrain_occluder({'look': 'cliff_edge'}) == 'cell'
    assert terrain_occluder({'look': 'boulder'}) == 'centerline'
    assert terrain_occluder({'look': 'pillar_rubble'}) == 'centerline'
    assert {'low_wall', 'palisade', 'crag', 'cliff_edge'} == set(SQUARE_FILLING_LOOKS)
    low_wall = grid_for([{'type': 'SIMPLE_COVER', 'cells': [[3, 3]], 'look': 'low_wall', 'height_ft': 10}])
    assert not visible(low_wall, (0, 0), (3, 4))


def test_object_kinds_choose_the_plus_or_a_whole_square():
    for kind in ('pillar', 'statue', 'crate', 'boulder_pile', 'war_brazier', 'stone_lantern', 'cart', 'bookcase'):
        assert object_rules.sight(kind) == {'occluder': 'centerline', 'sight_class': 'object'}, kind
    for kind in ('wall_section', 'palisade_section', 'sandbag_wall', 'fence_section', 'barricade'):
        assert object_rules.sight(kind) == {'occluder': 'cell', 'sight_class': 'object'}, kind
    for kind in ('door', 'gate'):
        assert object_rules.sight(kind) == {'occluder': 'cell', 'sight_class': 'door'}, kind
    assert object_rules.sight(None) == {'occluder': 'centerline', 'sight_class': 'object'}


def test_a_placed_boulder_blocks_sight_with_its_plus_and_a_door_with_its_square():
    from combat import zones
    from tests.h1_support import duel

    engine = duel([])
    for object_id, kind, name, x, y in (('object:boulder', 'boulder_pile', 'Boulder pile', 3, 3),
                                        ('object:door', 'door', 'Wooden door', 6, 3)):
        engine.state.objects[object_id] = RuntimeObjectState(
            object_id=object_id, object_kind=kind, position=Position(x=x, y=y), unattended=True, flammable=False,
            ac=15, current_hp=10, maximum_hp=10, height_ft=10,
            component={'kind': kind, 'name': name, 'blocks': True})
    zones.sync_walls(engine)
    sources = {row['name']: row for row in engine.grid.sight_line_sources}
    rock, door = sources['Boulder pile'], sources['Wooden door']
    assert rock['tag'] == 'object'
    assert rock['segments'] == cross_segments([(3, 3)])
    assert door['tag'] == 'door'
    assert door['cells'] == [(6, 3)]
    assert len(door['segments']) > 2, 'a door keeps its centre run and end caps'
    # Movement is untouched by the sight shape.
    assert {(3, 3), (6, 3)} <= engine.grid.blocked
    assert engine.grid.line_of_sight(Position(x=2, y=3), Position(x=4, y=3)) is False
    assert engine.grid.line_of_sight(Position(x=5, y=3), Position(x=7, y=3)) is False


def test_centre_plus_spans_are_named_by_the_region_that_made_them():
    boulder = grid_for([{'type': 'SIMPLE_COVER', 'cells': [[3, 3]], 'look': 'boulder', 'height_ft': 10}])
    volumes = [row for row in sight_geometry(boulder)['volumes'] if row['mode'] == 'centerline']
    assert volumes and all(row['tag'] == 'terrain' and row['name'] for row in volumes)
    assert cross_segments([(3, 3)]) == [((6, 7), (8, 7)), ((7, 6), (7, 8))]
