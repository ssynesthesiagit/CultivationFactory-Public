"""Physical performance delivery shared by Sound techniques and map authoring.

Maps explicitly declare connected solid contact surfaces or liquid volumes in
five-foot cells. Solid cells name the standing surface altitude, not a texture
or an inferred universal floor. Liquid cells name occupied volumes. A missing
declaration is unknown. Blocked cells explicitly suppress vibration; removing
one also disconnects transmission through it. Geometry is sealed with the map.
"""
from collections import deque


def normalize_media(rows, width, height):
    """Validate owner map geometry without silently dropping any cells."""
    if not isinstance(rows, list):
        raise ValueError('Resonant media must be a list of solid surfaces or liquid volumes.')
    result, ids = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('material') not in {'solid', 'liquid'}:
            raise ValueError('Each resonant medium needs a solid or liquid material.')
        key = row.get('id')
        if not isinstance(key, str) or not key.strip() or key in ids:
            raise ValueError('Each resonant medium needs a unique name.')
        ids.add(key)
        cells = []
        declared = row.get('cells', [])
        if not isinstance(declared, list):
            raise ValueError('Resonant medium cells must be a list of grid coordinates.')
        for cell in declared:
            if (not isinstance(cell, dict) or set(cell) - {'x', 'y', 'z'}
                    or any(type(cell.get(k, 0)) is not int for k in ('x', 'y', 'z'))
                    or 'x' not in cell or 'y' not in cell
                    or not 0 <= cell['x'] < width or not 0 <= cell['y'] < height
                    or cell.get('z', 0) < 0):
                raise ValueError('Resonant cells need whole grid coordinates inside the map.')
            cells.append((cell['x'], cell['y'], cell.get('z', 0)))
        if not cells or len(cells) != len(set(cells)):
            raise ValueError('A resonant medium needs nonduplicated physical cells.')
        blocked = row.get('blocked_cells', [])
        if not isinstance(blocked, list):
            raise ValueError('Vibration blockers must be a list of medium cells.')
        blocked_keys = []
        for cell in blocked:
            if (not isinstance(cell, dict) or set(cell) - {'x', 'y', 'z'}
                    or any(type(cell.get(k, 0)) is not int for k in ('x', 'y', 'z'))
                    or 'x' not in cell or 'y' not in cell):
                raise ValueError('Vibration blockers need whole grid coordinates.')
            point = (cell['x'], cell['y'], cell.get('z', 0))
            if point not in cells or point in blocked_keys:
                raise ValueError('Each vibration blocker must name one existing medium cell.')
            blocked_keys.append(point)
        encode = lambda points: [dict(x=x, y=y, z=z) for x, y, z in sorted(points)]
        result.append({'id': key, 'material': row['material'], 'cells': encode(cells),
                       **({'blocked_cells': encode(blocked_keys)} if blocked_keys else {})})
    return result


def connected_performance(engine, performer, recipient):
    """Whether this performance enters a shared, unblocked physical medium.

    Both endpoints must touch the same connected component now. Querying has no
    effects and consumes no uses. Movement naturally changes contact; sealed map
    geometry and native conditions survive commit/reload without cached receipts.
    """
    from .typed_executor import condition_rules
    from .falling import supported
    if any(rule.get('vibration_blocked') for actor in (performer, recipient)
           for rule in condition_rules(actor)):
        return False
    for row in engine.grid.resonant_media:
        cells = {(c['x'], c['y'], c['z']) for c in row['cells']}
        cells -= {(c['x'], c['y'], c['z']) for c in row.get('blocked_cells', [])}
        def contacts(actor):
            if row['material'] == 'solid':
                if not supported(engine, actor):
                    return set()
                return {(x, y, actor.position.z) for x, y in engine._actor_cells(actor)} & cells
            return set(engine._actor_volume(actor)) & cells
        starts, ends = contacts(performer), contacts(recipient)
        if not starts or not ends:
            continue
        pending, seen = deque(starts), set(starts)
        while pending:
            point = pending.popleft()
            if point in ends:
                return True
            x, y, z = point
            for neighbor in ((x+1,y,z),(x-1,y,z),(x,y+1,z),(x,y-1,z),(x,y,z+1),(x,y,z-1)):
                if neighbor in cells and neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
    return False


def receives_performance(engine, performer, recipient, source=''):
    """Audible performance, otherwise explicitly conducted physical vibration."""
    from .speech import can_hear_from
    return can_hear_from(engine, performer, recipient, source) or connected_performance(engine, performer, recipient)
