"""Ground-compatible altitude, range, sight and volumetric occupancy."""
import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.space import volume
from tests.h1_support import ME, FOE, duel


def grid(kind="BLOCKED", **region):
    return SquareGrid({"width_squares": 8, "height_squares": 8, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": [{"terrain_type": kind, "cells": [{"x": 3, "y": 3}],
                                                       "movement_cost": 1, **region}]})


def test_missing_altitude_and_object_height_preserve_old_serialization():
    old = {"x": 1, "y": 2}
    assert Position.model_validate(old).z == 0
    assert Position.model_validate(old).model_dump(mode="json") == old
    assert Position(x=1, y=2, z=3).model_dump(mode="json") == {**old, "z": 3}
    obj = RuntimeObjectState(object_id="test:object", object_kind="box", position=Position(**old), unattended=True, flammable=False)
    assert "height_ft" not in obj.model_dump(mode="json")
    assert "z" not in obj.model_dump(mode="json")["position"]
    with pytest.raises(ValueError):
        Position(x=0, y=0, z=-1)


def test_three_dimensional_chebyshev_distance():
    g = grid()
    assert g.distance_ft(Position(x=0, y=0), Position(x=1, y=1, z=2)) == 10
    assert g.distance_between_cell_sets_ft([(0, 0, 1)], [(1, 1, 3)]) == 10
    e = duel([])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    target.position = actor.position.model_copy(update={"z": 2})
    assert e._distance_actor_to_actor(actor, target) == 10
    assert e._distance_actor_to_cell(actor, target.position) == 10


@pytest.mark.parametrize("kind", ["BLOCKED", "SIGHT_BLOCKED"])
def test_default_wall_is_unlimited_but_explicit_height_can_be_seen_over(kind):
    low, high = Position(x=2, y=3), Position(x=4, y=3)
    assert not grid(kind).line_of_sight(low, high)
    start, end = low.model_copy(update={"z": 4}), high.model_copy(update={"z": 4})
    assert not grid(kind).line_of_sight(start, end)
    assert grid(kind, height_ft=10).line_of_sight(start, end)
    assert not grid(kind, height_ft=10).line_of_sight(low, high)


def test_cover_height_and_vertical_diagonal_side_collision():
    start, end = Position(x=2, y=3, z=3), Position(x=4, y=3, z=3)
    assert grid("SIMPLE_COVER").cover_bonus(start, end) == 2
    assert grid("SIMPLE_COVER", height_ft=10).cover_bonus(start, end) == 0
    g = grid(height_ft=5)
    assert g.volume_legal(Position(x=3, y=3, z=1))
    # Crossing diagonally up must not clip the blocked lower side square.
    assert not g.volume_step_legal(Position(x=2, y=3), Position(x=3, y=3, z=1))
    assert g.volume_step_legal(Position(x=2, y=3, z=1), Position(x=3, y=3, z=2))


def test_same_square_different_altitudes_are_distinct_occupied_volumes():
    e = duel([])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    target.position = actor.position.model_copy(update={"z": 1})
    assert not set(e._actor_volume(actor)) & set(e._actor_volume(target))
    assert not e._vertical_overlap(actor, target)
    e._assert_invariants()
    target.position = actor.position
    with pytest.raises(ValueError, match="occupied footprint"):
        e._assert_invariants()


def test_large_creature_height_matches_its_footprint():
    class Large:
        def occupied_cells(self, anchor):
            return tuple((anchor[0]+x, anchor[1]+y) for x in range(2) for y in range(2))
    cells = set(volume(Position(x=0, y=0, z=2), Large()))
    assert len(cells) == 8 and {cell[2] for cell in cells} == {2, 3}
