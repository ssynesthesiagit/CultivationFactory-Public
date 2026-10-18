"""Exact incremental volume spreading for spatial_areas.reaches.

Only native grid geometry and explicit area endpoints enter this derived index.
Actors, recipients and ability ownership do not. Every read checks the complete
semantic grid snapshot, including unrecorded wall/height edits. State/event
revisions also invalidate it. It is bounded, discarded on deepcopy and never
stored in fight state; unknown grids/data use the caller's reference search.
"""
from collections import OrderedDict, deque
from copy import deepcopy
from itertools import product
from threading import RLock

from .area_projection import geometry_data, geometry_key, spec_key
from .gate2_grid import SquareGrid
from .space import point, position

MAX_ENTRIES = 64
MAX_SHARED = 8
_SHARED = OrderedDict()
MAX_CELLS = 262144
_OFFSETS = tuple(d for d in product((-1, 0, 1), repeat=3) if any(d))
_LOCK = RLock()


class _Search:
    def __init__(self, start):
        self.queue = deque([start])
        self.seen = {start}
        self.reachable = {start}

    def reaches(self, engine, vertex, aim, area, target):
        from .typed_executor import in_area
        # Finish each popped node before stopping. A later creature resumes
        # exactly the same ordered BFS, including its original visited policy.
        while target not in self.reachable and self.queue:
            cell = self.queue.popleft()
            for delta in _OFFSETS:
                nxt = tuple(a + b for a, b in zip(cell, delta))
                if (nxt in self.seen or min(nxt) < 0
                        or nxt[0] >= engine.grid.width or nxt[1] >= engine.grid.height):
                    continue
                self.seen.add(nxt)
                if (in_area(engine, vertex, aim, position(nxt), area)
                        and engine.grid.volume_step_legal(cell, nxt)):
                    self.queue.append(nxt)
                    self.reachable.add(nxt)
        return target in self.reachable


class _Index:
    def __init__(self, signature, data):
        spec_key(data)  # Native, pure data only; refuse unknown mutable objects.
        self.signature = signature
        self.snapshot = deepcopy(data)
        self.entries = OrderedDict()
        self.lock = RLock()

    def __deepcopy__(self, memo):
        return None


def reaches(engine, vertex, aim, destination, area, reference):
    """Reuse a bounded BFS frontier; otherwise call the unchanged reference.

The caller checks native area membership and selects the 3D spreading path.
Read-only shallow knowledge projections may share the grid/epoch's index;
separate grids, recorded changes and any semantic grid edit cannot share it.
No engine function is wrapped or replaced. Failed searches are evicted.
"""
    from .typed_executor import in_area
    grid = engine.grid
    if type(grid) is not SquareGrid:
        return reference(engine, vertex, aim, destination, area)
    try:
        data = geometry_data(grid)
        state = getattr(engine, 'state', None)
        signature = (id(grid), getattr(state, 'state_version', None),
                     getattr(state, 'event_sequence', None), in_area,
                     SquareGrid.volume_step_legal, SquareGrid.volume_legal)
        key = (point(vertex), point(aim), geometry_key(area))
        with _LOCK:
            index = engine.__dict__.get('_spread_area_index')
            if index is None or index.signature != signature or index.snapshot != data:
                index = _SHARED.get(signature)
                if index is None or index.snapshot != data:
                    index = _Index(signature, data)
                    # Retain the grid identity to prevent reuse after collection.
                    index.grid = grid
                    _SHARED[signature] = index
                _SHARED.move_to_end(signature)
                while len(_SHARED) > MAX_SHARED:
                    _SHARED.popitem(last=False)
                engine.__dict__['_spread_area_index'] = index
    except TypeError:
        return reference(engine, vertex, aim, destination, area)
    with index.lock:
        search = index.entries.get(key)
        if search is None:
            search = _Search(point(aim))
            index.entries[key] = search
        index.entries.move_to_end(key)
        try:
            result = search.reaches(engine, vertex, aim, area, point(destination))
        except BaseException:
            index.entries.pop(key, None)
            raise
        # Account for rejected border cells too, not only accepted volume.
        while index.entries and (len(index.entries) > MAX_ENTRIES
                                 or sum(len(s.seen) for s in index.entries.values()) > MAX_CELLS):
            index.entries.popitem(last=False)
        return result
