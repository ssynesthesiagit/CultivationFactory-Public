"""Shared bounds-safe positions for extension placement and movement scans.

Used by Smoke Veil, Ash Core, Banner, Falling Tree, Exorcist, Magma Crust,
Mercy Flayer, Seraphic Molter, Thread the Object, Trap, Vessel and Vermilion Gate. Bounds are
checked on integers before constructing the validated Position; callers still
check blocked squares, occupancy, footprints and movement rules themselves.
"""
from ..gate2_runtime_models import Position


def map_position(engine, x: int, y: int, *, z: int = 0):
    """Return a Position inside the battlefield, or None; never clamp an aim."""
    if not engine.grid.in_bounds((x, y)):
        return None
    return Position(x=x, y=y, z=z)


def offset_positions(engine, origin, offsets):
    """Yield in-map positions in the supplied offset order (ground level)."""
    for dx, dy in offsets:
        position = map_position(engine, origin.x + dx, origin.y + dy)
        if position is not None:
            yield position
