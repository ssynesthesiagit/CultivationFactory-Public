"""Pure object cells shared by candidate targeting, objects, areas and collisions.

Providers use the documented object_target_cells extension query. Objects without
an explicit provider retain their historical anchor, including its serialization.
"""
from . import ext
from .gate2_runtime_models import Position


def target_cells(engine, obj):
    """Return one deterministic, nonempty occupied-cell tuple; never mutate state."""
    answers = ext.run_strict("object_target_cells", engine, obj)
    if not answers:
        return (obj.position,)
    if len(answers) != 1:
        raise ValueError("object_target_cells requires one geometry owner")
    cells = tuple(answers[0])
    if not cells or any(not isinstance(cell, Position) or not engine.grid.in_bounds((cell.x, cell.y))
                        for cell in cells):
        raise ValueError("object_target_cells requires nonempty in-bounds Positions")
    keys = {(cell.x, cell.y, cell.z) for cell in cells}
    if len(keys) != len(cells):
        raise ValueError("object_target_cells requires distinct cells")
    return tuple(sorted(cells, key=lambda cell: (cell.x, cell.y, cell.z)))
