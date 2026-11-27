"""Explicit swimming terrain and capabilities shared by native movement.

WATER terrain represents water that must be swum, rather than shallow ground.
A Swim Speed waives the normal extra foot per foot, not difficult terrain.
Flight and jumps above the water do not swim. No WATER regions means no change.
"""
from .movement_speeds import has_swim_speed


def in_water(engine, actor, destination):
    """Whether the ground footprint enters authored WATER."""
    water = engine.grid.terrain_spans.get('WATER')
    return bool(water and not destination.z and any(
        any(bottom == 0 and (top is None or top > 0) for bottom, top in water.get((x, y), ()))
        for x, y in engine._actor_cells(actor, destination)))


def surcharge(engine, actor, previous, destination, mode):
    return (engine.grid.square_size_ft
            if mode == 'walk' and in_water(engine, actor, destination) and not has_swim_speed(engine, actor)
            else 0)
