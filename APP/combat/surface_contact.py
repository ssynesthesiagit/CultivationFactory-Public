"""Pure contact/connection query over the table's solid surface geometry.

The arena floor is one continuous surface. Elevated support connects through
contiguous finite BLOCKED columns or solid cells of one native roof at the same
contact plane. Open apertures and separate roof components do not connect.
Drum and Earth's contact benefits share this query; no ability policy lives here.
Floating creatures never acquire contact from projected x/y alone.
"""
from .falling import supported
from .read_queries import pure


@pure
def connected(engine, first, second):
    if not supported(engine, first) or not supported(engine, second):
        return False
    z = first.position.z
    if z != second.position.z:
        return False
    if not z:
        return True
    first_cells = set(engine._actor_cells(first))
    second_cells = set(engine._actor_cells(second))
    for roof in engine.grid.roof_surfaces:
        if roof.walk_ft != z * 5:
            continue
        solid = roof.cells - roof.open_cells
        if _path(engine.grid, first_cells & solid, second_cells & solid, solid.__contains__):
            return True
    starts = {(x, y) for x, y in engine._actor_cells(first)
              if engine.grid.terrain_at((x, y, z - 1), 'BLOCKED')}
    ends = {(x, y) for x, y in engine._actor_cells(second)
            if engine.grid.terrain_at((x, y, z - 1), 'BLOCKED')}
    return _path(engine.grid, starts, ends,
                 lambda cell: engine.grid.terrain_at((*cell, z - 1), 'BLOCKED'))


def _path(grid, starts, ends, solid_at):
    """Four-neighbor path over one support component, excluding open cells."""
    if not starts or not ends:
        return False
    seen, pending = set(starts), list(starts)
    while pending:
        x, y = pending.pop()
        if (x, y) in ends:
            return True
        for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            if ((nx, ny) not in seen and 0 <= nx < grid.width and 0 <= ny < grid.height
                    and solid_at((nx, ny))):
                seen.add((nx, ny))
                pending.append((nx, ny))
    return False
