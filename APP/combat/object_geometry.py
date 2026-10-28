"""Pure object cells shared by candidate targeting, objects, areas and collisions.

Providers use the documented object_target_cells extension query. Objects without
an explicit provider retain their historical anchor, including its serialization.

Shared helper `actor_distance_ft` is the object analogue of the engine's
`_distance_actor_to_actor`: the feet from a creature to an object's own occupied
squares, nearest square first. Consumers: Talismans' Remote Activation measures a
formula's printed reach from the talisman to an object target with it. Any later reach
or targeting consumer that must treat an object like a creature's body (a displaced or
wide object is reached at its nearest square, never only at its anchor) uses it too.
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


def actor_distance_ft(engine, actor, obj):
    """Feet from a creature to an object's own occupied squares; pure, never mutates state.

    The object analogue of ``Gate2Engine._distance_actor_to_actor``, with the same cell/volume choice:
    the nearest occupied square decides, so a wide or displaced object is reached from its edge and a
    creature above or below it keeps the vertical distance. An object with no geometry provider keeps
    its historical anchor through ``target_cells``.
    """
    cells = target_cells(engine, obj)
    overlap = any(cell.z for cell in cells)
    actor_cells = engine._actor_volume(actor) if actor.position.z or overlap else engine._actor_cells(actor)
    return int(engine.grid.distance_between_cell_sets_ft(actor_cells, cells))


def diagonal_swept_cells(engine, obj, dx, dy):
    """The two full (x, y) footprints an object passes through while stepping diagonally by (dx, dy).

    A diagonal step is legal only when the object could have occupied both intermediate
    placements, exactly as ``Grid._step_legal`` requires for a creature: neither the
    destination footprint nor the two cells beside the *anchor* describe a wide object's
    route. A 2-by-2 bench anchored at (3, 8) moving southeast sweeps (5, 8), which appears in
    neither the destination nor the anchor's two side cells, so a blocker there is otherwise
    missed and the illegal displacement is committed.

    Returns the union of both side footprints, or ``None`` when either placement leaves the
    battlefield (an out-of-bounds rectangle raises in ``target_cells``). Pure: it never
    mutates state, and the caller decides what is blocked. The object's own current cells are
    NOT removed -- a rectangle legitimately sweeps over itself -- so a caller testing for
    obstacles should exclude them the same way it excludes them from a blocked-cell set.
    """
    swept: set[tuple[int, int]] = set()
    for side_x, side_y in ((dx, 0), (0, dy)):
        side = obj.model_copy(update={"position": Position(x=obj.position.x + side_x,
                                                           y=obj.position.y + side_y,
                                                           z=obj.position.z)})
        try:
            cells = target_cells(engine, side)
        except ValueError:
            return None
        swept.update((cell.x, cell.y) for cell in cells)
    return swept
