"""Placed line/cone geometry composes with existing three-dimensional areas."""
from pathlib import Path

import pytest

from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import Position
from combat.typed_executor import aim_gives_direction, in_area


@pytest.mark.parametrize('shape', ['line', 'cone'])
def test_placed_shape_measures_from_an_elevated_aim_in_three_dimensions(shape):
    engine = Gate2Engine(Path(__file__).resolve().parents[1], match_seed='R25-PLACED-HEIGHT')
    vertex = Position(x=3, y=6, z=0)
    aim = Position(x=3, y=6, z=3)
    area = {'shape': shape, 'size_ft': 10, 'width_ft': 5, 'placed': True}
    assert aim_gives_direction(area, vertex, aim)
    assert in_area(engine, vertex, aim, Position(x=3, y=6, z=4), area)
    assert not in_area(engine, vertex, aim, Position(x=3, y=6, z=2), area)
    assert not in_area(engine, vertex, aim, Position(x=3, y=6, z=6), area)
    assert not in_area(engine, vertex, aim, Position(x=4, y=6, z=4), area)
    assert not aim_gives_direction(area, aim, aim)
