"""Solid contact and conduction shared by Court Hearing and future tremor queries.

No sight or movement permission is granted. Terrain intervals and solid roofs
form connected material; the native arena floor is one continuous component.
Recorded climbing grips and exact-foot support surfaces provide contact. Scene
authors may supply explicit surface_contacts ({x, y, feet}) in condition data.
All results are derived; graph objects are never stored in fight state.
"""
from .read_queries import pure, memo


def overlaps(a, b):
    return not ((a[1] is not None and a[1] < b[0]) or (b[1] is not None and b[1] < a[0]))


def graph(engine):
    spans, roofs = engine.grid.terrain_spans, engine.grid.roof_geometry.surfaces
    def build():
        columns = {}
        for cell in engine.grid.blocked:
            columns[cell] = list(spans.get('BLOCKED', {}).get(cell, [(0, engine.grid.terrain_heights.get('BLOCKED', {}).get(cell))]))
        for roof in roofs:
            for x, y in roof.cells:
                if roof.solid_at(x, y):
                    columns.setdefault((x, y), []).append((roof.height_ft, roof.height_ft))
        nodes = [(None, (-1, 0))]
        by_cell = {}
        for cell, intervals in sorted(columns.items()):
            merged = []
            for low, high in sorted(intervals, key=lambda p: p[0]):
                if merged and overlaps(merged[-1], (low, high)):
                    old = merged[-1]
                    merged[-1] = (old[0], None if old[1] is None or high is None else max(old[1], high))
                else:
                    merged.append((low, high))
            for interval in merged:
                by_cell.setdefault(cell, []).append(len(nodes)); nodes.append((cell, interval))
        parent = list(range(len(nodes)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        def join(a, b):
            parent[root(a)] = root(b)
        for index, (cell, interval) in enumerate(nodes[1:], 1):
            if interval[0] <= 0:
                join(index, 0)
            x, y = cell
            for neighbour in ((x + 1, y), (x, y + 1)):
                for other in by_cell.get(neighbour, []):
                    if overlaps(interval, nodes[other][1]):
                        join(index, other)
        return spans, roofs, nodes, by_cell, [root(i) for i in range(len(nodes))]
    return memo(engine, ('contact_geometry', id(spans), id(roofs)), build)


def samples(engine, actor):
    from .falling import supported
    from .roof_movement import can_hold
    from .typed_executor import condition_rules
    rules = condition_rules(actor, engine=engine)
    if any(row.get('incorporeal') or row.get('no_physical_contact') for row in rules):
        return []
    result = []
    if supported(engine, actor):
        for x, y in engine._actor_cells(actor):
            feet = actor.position.z * 5
            supported_roofs = [r.height_ft for r in engine.grid.roof_geometry.surfaces
                if r.walk_ft == feet and r.solid_at(x, y)]
            finite_tops = [high for low, high in engine.grid.terrain_spans.get('BLOCKED', {}).get((x, y), [])
                           if high is not None and feet - 5 < high <= feet]
            contact = max([*supported_roofs, *finite_tops], default=feet)
            result.append(((x, y), (contact, contact)))
    if can_hold(engine, actor):
        for x, y, z in engine._actor_volume(actor):
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if engine.grid.in_bounds((nx, ny)):
                    result.append(((nx, ny), (z * 5, (z + 1) * 5)))
    for condition in actor.conditions.values():
        for point in condition.data.get('surface_contacts', []):
            if all(type(point.get(k)) is int for k in ('x', 'y', 'feet')) and engine.grid.in_bounds((point['x'], point['y'])):
                result.append(((point['x'], point['y']), (point['feet'], point['feet'])))
    return result


def components(engine, actor):
    spans, roofs, nodes, by_cell, labels = graph(engine)
    found = set()
    for cell, interval in samples(engine, actor):
        if interval[0] <= 0 <= interval[1]:
            found.add(labels[0])
        for index in by_cell.get(cell, []):
            if overlaps(interval, nodes[index][1]):
                found.add(labels[index])
    return found


@pure
def conducts(engine, first, second):
    return bool(components(engine, first) & components(engine, second))


@pure
def touches_cells(engine, actor, cells):
    for cell, interval in samples(engine, actor):
        for x, y, z in cells:
            if cell != (x, y):
                continue
            if engine.grid.terrain_at((x, y, z), 'BLOCKED'):
                bounds = (z * 5, (z + 1) * 5)
            else:
                roofs = [r.height_ft for r in engine.grid.roof_geometry.surfaces if r.walk_ft == z * 5 and r.solid_at(x, y)]
                tops = [top for low, top in engine.grid.terrain_spans.get('BLOCKED', {}).get((x, y), [])
                        if top is not None and z * 5 - 5 < top <= z * 5]
                height = max([*roofs, *tops], default=z * 5)
                bounds = (height, height)
            if overlaps(interval, bounds):
                return True
    return False
