"""Public object landing geometry used by transfer_object's explicit radius.

Objects occupy their own footprint (one cell by default), never the controller's
body. This query is read-only; perception and line of effect are the shared table
policies. Creature teleport restrictions and movement routes do not apply.
"""
from __future__ import annotations
from typing import Any


def destinations(engine: Any, viewer: Any, feet: int, *, footprint: Any = None) -> list[Any]:
    """Unoccupied ground placements within range that the controller perceives.

    Explicit footprints may be supplied for larger modeled objects. A carried
    object without footprint metadata occupies one cell, including Tiny objects.
    All creature bodies, including the viewer's, block an unoccupied landing.
    """
    from .gate2_runtime_models import Position
    from .senses import perceives_cell
    from .targeting import line_of_effect
    occupied = {cell for actor in engine.state.actors.values() if actor.active
                for cell in engine.grid.footprint_cells(actor.position, engine._footprint(actor))}
    reach = max(0, int(feet)) // engine.grid.square_size_ft
    cells = []
    for y in range(max(0, viewer.position.y-reach), min(engine.grid.height, viewer.position.y+reach+1)):
        for x in range(max(0, viewer.position.x-reach), min(engine.grid.width, viewer.position.x+reach+1)):
            cell = Position(x=x, y=y)
            if (engine.grid.distance_ft(viewer.position, cell) <= feet
                    and engine.grid.placement_legal(cell, footprint=footprint, occupied_cells=occupied)
                    and perceives_cell(engine, viewer, cell)
                    and line_of_effect(engine, viewer, destination=cell)):
                cells.append(cell)
    return cells
