"""Derived temporary openings shared by passage and future terrain destruction.

Providers return cells and exact integer-foot vertical intervals. Static map
data is never mutated; sync_walls reconstructs the original spans each time.
The combat grid projects horizontal geometry onto its existing five-foot cells.
"""
from copy import deepcopy


def subtract(rows, low, high):
    out = []
    for bottom, top in rows:
        if high <= bottom or (top is not None and low >= top):
            out.append((bottom, top))
            continue
        if bottom < low:
            out.append((bottom, low))
        if top is None or high < top:
            out.append((high, top))
    return out


def apply(engine, blocked, opaque, cover, heights, spans):
    from . import ext
    grid = engine.grid
    base = engine.__dict__.setdefault('_aperture_base_occluders', deepcopy(grid.occluder_spans))
    occluders = deepcopy(base)
    changed = False
    horizontal = []
    for provided in ext.run_strict('terrain_apertures', engine):
        if not isinstance(provided, list):
            raise ValueError('terrain_apertures requires a list of opening dictionaries')
        for row in provided:
            low, high = row.get('bottom_ft'), row.get('top_ft')
            if type(low) is not int or type(high) is not int or not 0 <= low < high:
                raise ValueError('An aperture needs nonnegative exact-foot bounds')
            if row.get('horizontal'):
                horizontal.append(row)
            for point in row.get('cells') or []:
                cell = tuple(point)
                if len(cell) != 2 or any(type(v) is not int for v in cell) or not grid.in_bounds(cell):
                    raise ValueError('An aperture cell must be an in-bounds integer pair')
                changed = True
                for kind, columns in (('BLOCKED', blocked), ('SIGHT_BLOCKED', opaque), ('SIMPLE_COVER', cover)):
                    if cell not in columns:
                        continue
                    prior = spans.setdefault(kind, {}).get(cell, [(0, heights.get(kind, {}).get(cell))])
                    left = subtract(prior, low, high)
                    if left:
                        spans[kind][cell] = left
                    else:
                        columns.discard(cell)
                        spans[kind].pop(cell, None)
                        heights.setdefault(kind, {}).pop(cell, None)
                cut = []
                for mode, bottom, top in occluders.get(cell, []):
                    cut.extend((mode, lo, hi) for lo, hi in subtract([(bottom, top)], low, high))
                occluders[cell] = cut
    original_roofs = engine.__dict__.setdefault('_aperture_base_roofs', grid.roof_geometry)
    grid.roof_geometry = original_roofs.with_apertures(horizontal) if horizontal else original_roofs
    grid.roof_surfaces = grid.roof_geometry.surfaces
    original_tops = engine.__dict__.setdefault('_aperture_base_roof_tops', dict(getattr(grid, 'roof_tops', {})))
    grid.roof_tops = {cell: top for cell, top in original_tops.items()
                     if not any(cell in {tuple(p) for p in row.get('cells', ())}
                                and row['bottom_ft'] <= top <= row['top_ft'] for row in horizontal)}
    grid.ground_open_cells = {tuple(cell) for row in horizontal if row['bottom_ft'] == 0
                              and row.get('ground') for cell in row['cells']}
    if changed or getattr(grid, '_aperture_had_openings', False):
        grid.occluder_spans = occluders
        grid._centerline_sight_cache.clear()
    grid._aperture_had_openings = changed


def light_transmits(engine, start, end):
    """Native geometric transmission plus source-owned light-path vetoes.

    A nonvisual sense permission never alters this light propagation query.
    Shared by passage projections and future represented light emitters.
    """
    from . import ext
    if not engine.grid.line_of_physical_transmission(start, end):
        return False
    replies = ext.run_strict('light_path_allowed', engine, start, end)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('light_path_allowed requires a boolean or None')
    return False not in replies
