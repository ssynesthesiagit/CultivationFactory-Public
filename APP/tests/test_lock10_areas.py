"""Occupied volumes follow the owner's 2026-09-27 round-area ruling.

Lock 20 clarifies that spheres, cylinders and emanations use centre-to-centre
Euclidean distance in three dimensions, in feet. Square blocks remain square.
"""
import pytest
from combat.gate2_runtime_models import Position, ZoneState
from combat.spatial_areas import actor_in_area, zone_contains
from combat.typed_executor import in_area, _area_targets
from tests.h1_support import ME, FOE, duel
from tests.test_lock10_space import grid


@pytest.mark.parametrize('shape', ['sphere', 'emanation', 'cylinder'])
def test_round_area_includes_radius_but_rejects_diagonals_outside_it(shape):
    e = duel([])
    center = Position(x=0,y=0,z=2)
    area = {'shape': shape, 'size_ft': 10}
    assert in_area(e, center, center, Position(x=0,y=0,z=4), area)
    assert in_area(e, center, center, Position(x=2,y=0,z=2), area)
    assert in_area(e, center, center, Position(x=1,y=1,z=3), area)
    assert not in_area(e, center, center, Position(x=2,y=2,z=2), area)
    assert not in_area(e, center, center, Position(x=2,y=2,z=4), area)
    assert not in_area(e, center, center, Position(x=0,y=0,z=5), area)


@pytest.mark.parametrize('shape', ['cube', 'square'])
def test_square_blocks_keep_negative_edge_and_exclude_positive_edge_in_3d(shape):
    e = duel([])
    center = Position(x=4,y=4,z=4)
    area = {'shape': shape, 'size_ft': 20}
    assert in_area(e, center, center, Position(x=2,y=2,z=2), area)
    assert in_area(e, center, center, Position(x=5,y=5,z=5), area)
    assert not in_area(e, center, center, Position(x=6,y=4,z=4), area)
    assert not in_area(e, center, center, Position(x=4,y=4,z=6), area)


def test_vertical_line_and_cone_have_direction_and_width():
    e = duel([])
    start, aim = Position(x=2,y=2), Position(x=2,y=2,z=4)
    assert in_area(e, start, aim, Position(x=2,y=2,z=6), {'shape':'line','size_ft':30})
    assert not in_area(e, start, aim, Position(x=3,y=2,z=6), {'shape':'line','size_ft':30})
    assert in_area(e, start, aim, Position(x=4,y=2,z=4), {'shape':'cone','size_ft':30})
    assert not in_area(e, start, aim, Position(x=5,y=2,z=4), {'shape':'cone','size_ft':30})


def test_area_sees_over_short_wall_but_not_unlimited_wall():
    e = duel([])
    origin, destination = Position(x=2,y=3,z=3), Position(x=4,y=3,z=3)
    area = {'shape':'sphere','size_ft':20}
    e.grid = grid()
    assert not in_area(e, origin, origin, destination, area)
    e.grid = grid(height_ft=10)
    assert in_area(e, origin, origin, destination, area)
    # A downward ray still hits the wall even when its origin is above it.
    assert not in_area(e, origin, origin, Position(x=3,y=3), area)


def test_zone_aura_membership_tracks_height_while_painted_terrain_stays_grounded():
    e = duel([])
    a = e.state.actors[ME]
    center = a.position
    z = ZoneState(zone_id='test:aura', source_definition_id='test:aura', owner_id=FOE,
        center=center, radius_cells=2, affected_cells=e.grid.cells_in_radius(center, 2),
        concentration_link=False, created_round=1,
        trigger_profile={'shape':'sphere','size_ft':10})
    assert zone_contains(e, a, z, at=center.model_copy(update={'z':2}))
    assert not zone_contains(e, a, z, at=center.model_copy(update={'z':3}))
    z.radius_cells = 0
    z.trigger_profile = {'kind':'map'}
    assert zone_contains(e, a, z)
    assert not zone_contains(e, a, z, at=center.model_copy(update={'z':1}))


@pytest.mark.parametrize('shape', ['cube', 'square'])
def test_saved_blocks_keep_recorded_columns_and_half_open_altitude(shape):
    """Owner 2026-09-27 keeps blocks square; saved footprints remain owned data."""
    e = duel([])
    actor = e.state.actors[ME]
    center = Position(x=4, y=4, z=3)
    zone = ZoneState(zone_id='test:saved-block', source_definition_id='test:block', owner_id=ME,
                     center=center, radius_cells=1,
                     affected_cells=(Position(x=5, y=5, z=3),),
                     concentration_link=False, created_round=1,
                     trigger_profile={'shape': shape, 'size_ft': 10})
    # The recorded legacy positive edge survives, with exactly two height cells.
    assert zone_contains(e, actor, zone, at=Position(x=5, y=5, z=2))
    assert zone_contains(e, actor, zone, at=Position(x=5, y=5, z=3))
    assert not zone_contains(e, actor, zone, at=Position(x=5, y=5, z=4))
    assert not zone_contains(e, actor, zone, at=center)


def test_target_selection_counts_altitude_and_large_creature_volume(monkeypatch):
    e = duel([])
    a, target = e.state.actors[ME], e.state.actors[FOE]
    target.position = a.position.model_copy(update={'z':3})
    area = {'shape':'sphere','size_ft':10}
    assert target not in _area_targets(e, a, a.position, area)
    monkeypatch.setattr(e, '_actor_volume', lambda who, at=None: ((a.position.x,a.position.y,2), (a.position.x,a.position.y,3)))
    assert actor_in_area(e, target, a.position, a.position, area)


def test_spreading_area_reaches_above_finite_wall():
    from combat.spatial_areas import reaches
    e = duel([])
    e.grid = grid(height_ft=5)
    origin = Position(x=2,y=3,z=1)
    assert reaches(e, origin, origin, Position(x=4,y=3,z=1), {'shape':'sphere','size_ft':10,'spreads':True})
