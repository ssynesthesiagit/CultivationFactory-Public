"""Explicit map-authored liquid and fragile surface geometry.

The map owner records real surface cells, not a creature's power to use them.
Tabletop normalization/sealing is the producer; source-owned traversal consumers
query covers(). These markers grant no flight, support, damage, object profile,
durability or movement permission by themselves. Destructible objects continue
to use the existing object/Anchor interfaces. No marker means no inferred water,
fragility or change to an ordinary map.
"""
KINDS = ('liquid', 'fragile')


def normalize(rows, width, height):
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError('Surface geometry must be a list of recorded surfaces.')
    result, ids = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'label', 'kind', 'cells'}:
            raise ValueError('Record each surface’s identity, readable label, kind and exact cells.')
        if (any(type(row[key]) is not str or not row[key].strip() or len(row[key]) > 240
                for key in ('id', 'label')) or row['id'] in ids or row['kind'] not in KINDS):
            raise ValueError('Use distinct surface identities, readable labels and liquid or fragile kind.')
        points = row['cells']
        if not isinstance(points, list) or not points:
            raise ValueError('A surface needs at least one actual map cell.')
        cells = set()
        for point in points:
            if (not isinstance(point, (list, tuple)) or len(point) != 3
                    or any(type(v) is not int for v in point)
                    or not (0 <= point[0] < width and 0 <= point[1] < height and point[2] >= 0)):
                raise ValueError('Surface cells use in-bounds whole x, y and nonnegative elevation in five-foot squares.')
            cells.add(tuple(point))
        ids.add(row['id'])
        result.append({**row, 'cells':[list(point) for point in sorted(cells)]})
    return result


def covers(engine, actor, position, kinds=KINDS):
    """Whether an explicitly recorded surface covers this actual footprint.

    Accepted battlefield documents are immutable. Cache their static geometry
    per engine; this does not persist a receipt or change mechanical state.
    Elevation is exact: water below an actor never supplies a surface in the air.
    """
    document = getattr(engine, 'battlefield_document', None) or {}
    cache = getattr(engine, '_map_surface_geometry', None)
    if cache is None or cache[0] is not document:
        cells = {kind:set() for kind in KINDS}
        for row in document.get('map_surfaces', []):
            cells[row['kind']].update(tuple(point) for point in row['cells'])
        cache = document, cells, {}
        engine._map_surface_geometry = cache
    key = tuple(sorted(kinds))
    if key not in cache[2]:
        cache[2][key] = frozenset().union(*(cache[1][kind] for kind in key))
    covered = cache[2][key]
    return bool(covered) and all((x, y, position.z) in covered
        for x, y in engine.grid.footprint_cells(position, engine._footprint(actor)))
