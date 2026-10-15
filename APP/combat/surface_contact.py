"""Solid-surface distance from sealed native terrain, shared by Earth responses.

Uses the engine's ground plane, finite columns, walls and roof slabs. It never
infers a material from an actor's name or treats open air as ground contact.
Distances measure the gap between occupied volumes in feet.
"""


def distance(engine, actor):
    from .falling import supported
    if supported(engine, actor):
        return 0
    square = engine.grid.square_size_ft
    cells = engine._actor_volume(actor)
    closest = min(z * square for x, y, z in cells)
    for x, y, z in cells:
        for (sx, sy), spans in engine.grid.terrain_spans.get('BLOCKED', {}).items():
            horizontal = max(max(0, abs(sx - x) - 1), max(0, abs(sy - y) - 1)) * square
            for bottom, top in spans:
                vertical = max(0, bottom - (z + 1) * square,
                               z * square - top if top is not None else 0)
                closest = min(closest, max(horizontal, vertical))
    return closest
