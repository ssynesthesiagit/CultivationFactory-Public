"""Explicit swimming terrain and capabilities shared by native movement.

WATER terrain represents water that must be swum, rather than shallow ground.
A Swim Speed waives the normal extra foot per foot, not difficult terrain.
Flight and jumps above the water do not swim. No WATER regions means no change.
"""
from . import ext


def speed(engine, actor):
    result = 0
    rows = [c.data for c in actor.conditions.values()]
    rows += ext.run_strict('swimming', engine, actor)
    for row in rows:
        value = row.get('swim_speed_ft', 0)
        if type(value) is not int or value < 0:
            raise ValueError('swim_speed_ft must be nonnegative integer feet')
        result = max(result, value)
    return result if engine._effective_speed(actor) > 0 else 0


def surcharge(engine, actor, previous, destination, mode):
    water = engine.grid.terrain_spans.get('WATER', {})
    if not water or mode != 'walk' or destination.z or speed(engine, actor):
        return 0
    return engine.grid.square_size_ft if any(
        (x, y) in water
        for x, y in engine._actor_cells(actor, destination)) else 0
