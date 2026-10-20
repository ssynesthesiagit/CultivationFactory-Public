"""Bounded pure volume derivations shared by space and spatial_areas.

Only explicit integer anchors and frozen native footprints are indexed. Actor
state, grid terrain, recipients and ability ownership never enter these caches.
Engine callers resolve the current footprint first, so transforms, projections
and replacement footprint authority automatically use different inputs.
"""
from collections import OrderedDict
from threading import RLock

from .footprints import ActorFootprintDefinition
from .gate2_runtime_models import Position
from .space import position as _native_position

MAX_ENTRIES = 1024
MAX_VOLUME_CELLS = 65536
MAX_POSITION_VOLUME = 64
_volumes = OrderedDict()
_position_volumes = OrderedDict()
_volume_cells = 0
_lock = RLock()
_FOOTPRINT_FIELDS = frozenset({'schema_name', 'footprint_id', 'anchor_semantics', 'width_cells',
                              'height_cells', 'occupied_relative_cells', 'source_definition_id'})


def volume(anchor, footprint, native):
    """Return native ordered integer cells for an exact immutable footprint.

    The retained footprint prevents identity recycling. Unsupported/custom
    footprints use native evaluation; no guess about their mutable inputs is
    made. Entries and total cells are bounded independently of actor count.
    """
    global _volume_cells
    if (type(footprint) is not ActorFootprintDefinition
            or type(anchor) is not tuple or len(anchor) != 3
            or type(anchor[0]) is not int or type(anchor[1]) is not int or type(anchor[2]) is not int):
        return native(anchor, footprint)
    key = (native, ActorFootprintDefinition.occupied_cells, id(footprint), anchor)
    with _lock:
        hit = _volumes.get(key)
        if hit is not None:
            _volumes.move_to_end(key)
            return hit[1]
        # Frozen models can still be made invalid with model_copy(update=...).
        # Check the whole supported immutable shape before retaining a new
        # footprint; future mutable/schema extensions safely use the native path.
        if (frozenset(ActorFootprintDefinition.model_fields) != _FOOTPRINT_FIELDS
                or frozenset(Position.model_fields) != {'x', 'y', 'z'}
                or type(footprint.occupied_relative_cells) is not tuple
                or not all(type(cell) is Position for cell in footprint.occupied_relative_cells)):
            return native(anchor, footprint)
        result = native(anchor, footprint)
        if len(result) > MAX_VOLUME_CELLS:
            return result
        while _volumes and (len(_volumes) >= MAX_ENTRIES
                            or _volume_cells + len(result) > MAX_VOLUME_CELLS):
            _, (_, old) = _volumes.popitem(last=False)
            _volume_cells -= len(old)
        _volumes[key] = (footprint, result)
        _volume_cells += len(result)
        return result


def positions(cells, native):
    """Share frozen Positions only for a complete bounded integer-cell tuple.

    Native volume computation has already resolved every footprint/state input.
    Sharing these immutable values survives cloning safely and cannot change
    saved state; unusually large or non-native cell sequences compute afresh.
    """
    if native is _native_position and type(cells) is tuple and len(cells) <= MAX_POSITION_VOLUME:
        with _lock:
            hit = _position_volumes.get(id(cells))
            if hit is not None:
                _position_volumes.move_to_end(id(cells))
                return hit[1]
            if all(type(cell) is tuple and len(cell) == 3
                   and all(type(n) is int for n in cell) for cell in cells):
                result = tuple(native(cell) for cell in cells)
                # Keep the immutable tuple alive so its identity cannot recycle.
                _position_volumes[id(cells)] = (cells, result)
                while len(_position_volumes) > MAX_ENTRIES:
                    _position_volumes.popitem(last=False)
                return result
    return tuple(native(cell) for cell in cells)
