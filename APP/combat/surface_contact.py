"""Pure contact/connection query over the table's solid surface geometry.

The arena floor is one continuous surface. Elevated support is connected only
through contiguous finite BLOCKED columns at the same contact plane. Floating
creatures and separate platforms never acquire contact from projected x/y alone.
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
    starts = {(x, y) for x, y in engine._actor_cells(first)
              if engine.grid.terrain_at((x, y, z - 1), 'BLOCKED')}
    ends = {(x, y) for x, y in engine._actor_cells(second)
            if engine.grid.terrain_at((x, y, z - 1), 'BLOCKED')}
    seen, pending = set(starts), list(starts)
    while pending:
        x, y = pending.pop()
        if (x, y) in ends:
            return True
        for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            if ((nx, ny) not in seen and 0 <= nx < engine.grid.width and 0 <= ny < engine.grid.height
                    and engine.grid.terrain_at((nx, ny, z-1), 'BLOCKED')):
                seen.add((nx, ny)); pending.append((nx, ny))
    return False
