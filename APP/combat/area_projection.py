"""Exact grid-only area raster index for zones and spreading area membership.

The underlying typed area raster reads grid geometry and its explicit area/origin
arguments, never actors, resources or ability ownership. Index the semantic grid
snapshot (including unrecorded terrain edits), complete area specification and
state/event epoch. Results retain their original order and frozen Positions.
The bounded derived index is discarded on engine deepcopy and is never saved.
Unknown grid implementations or non-data attributes use the original query.
Derived sight memo entries are not terrain inputs and cannot invalidate rasters.
"""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock

from .gate2_grid import SquareGrid
from .gate2_runtime_models import Position
from .space import point
from .roof_geometry import RoofGeometry, RoofSurface

MAX_CELLS = 262144
MAX_ENTRIES = 1024
MAX_SHARED = 8
# Engines that share one grid object at one state/event epoch (an engine and its
# area_knowledge.preview_engine views, built per candidate area) share one index,
# so the grid snapshot is validated and copied once per epoch, not once per view.
# Keyed by the full signature and still checked against the complete grid
# snapshot, exactly like the per-engine index; never saved, never deep-copied.
_SHARED = OrderedDict()
_LOCK = RLock()
GEOMETRY_FIELDS = frozenset({'shape', 'size_ft', 'width_ft', 'height_ft', 'placed', 'spreads', 'include_origin'})


def geometry_data(grid):
    """All grid inputs, excluding only SquareGrid's documented sight memo.

    Populating/evicting this cache does not change geometry. Keep every other
    field, including future/unknown fields, so unrecorded edits still invalidate
    and non-data providers still fall back to the uncached reference.
    """
    data = {key: value for key, value in vars(grid).items() if key != '_centerline_sight_cache'}
    # Native roofs are pure geometry too. Snapshot all of their query inputs,
    # including the cell index and heights, so in-place edits invalidate both
    # raster and spreading indexes. Custom providers still take the reference
    # path; never drop an unknown input to make a cache eligible.
    roof = data.get('roof_geometry')
    if type(roof) is RoofGeometry:
        data['roof_geometry'] = dict(vars(roof))
    return data


MAX_PASS_INDEXES = 8


def geometry_inputs(grid):
    """Every object geometry_data reads, as (owner, field, value) triples.

    Mirrors geometry_data: all grid fields except the sight memo, plus a
    native roof's fields. validated_index holds these values for its pass,
    so comparing their ids can never match a recycled, different object.
    """
    fields = vars(grid)
    inputs = tuple(('grid', key, value) for key, value in fields.items() if key != '_centerline_sight_cache')
    roof = fields.get('roof_geometry')
    if type(roof) is RoofGeometry:
        inputs += tuple(('roof', key, value) for key, value in vars(roof).items())
    return inputs


def validated_index(engine, grid, name, epoch, resolve):
    """Validate a grid-snapshot index once per read-only candidate pass.

    resolve() is the full check (complete geometry_data snapshot comparison).
    Outside read_queries.candidate_pass, and for any other engine or preview
    view, every call runs it, exactly as before. Inside the pass, a resolved
    index is reused only for the same grid object, epoch and identical input
    objects for every geometry_data field. Temporary in-pass projections
    reassign grid fields (motion.terrain_for/repriced, zones.sync_walls), so
    they take the full check again and never borrow another geometry's index.
    The pure-pass contract excludes in-place edits during the pass; the
    pass cache is discarded after the pass, so the next pass observes them.
    """
    from .read_queries import enumeration_cache
    cache = enumeration_cache(engine)
    if cache is None:
        return resolve()
    inputs = geometry_inputs(grid)
    key = (id(grid), epoch, tuple((owner, field, id(value)) for owner, field, value in inputs))
    slots = cache.get(('validated_grid_index', name))
    if slots is None:
        slots = cache[('validated_grid_index', name)] = OrderedDict()
    hit = slots.get(key)
    if hit is not None:
        slots.move_to_end(key)
        return hit[2]
    index = resolve()
    # Holding the grid and every input keeps their ids unique while cached.
    slots[key] = (grid, inputs, index)
    while len(slots) > MAX_PASS_INDEXES:
        slots.popitem(last=False)
    return index


def _freeze(value):
    if value is None or type(value) in (bool, int, float, str):
        return type(value), value
    if isinstance(value, Position):
        return 'position', _freeze(value.model_dump(mode='json'))
    if type(value) is RoofSurface:
        return 'roof_surface', _freeze(vars(value))
    if type(value) is dict:
        return 'dict', frozenset((_freeze(k), _freeze(v)) for k, v in value.items())
    if type(value) in (tuple, list):
        return type(value), tuple(_freeze(v) for v in value)
    if type(value) in (set, frozenset):
        return type(value), frozenset(_freeze(v) for v in value)
    raise TypeError('Grid geometry contains a non-data value')


def spec_key(area):
    """Complete immutable area key, shared by raster and volume membership."""
    return _freeze(area)


def geometry_key(area):
    """Normalized inputs of in_area/area_cells, excluding recipient/effect data.

    GEOMETRY_FIELDS is the shared native geometry contract. A regression guard
    requires every area field read by those native functions to be listed here;
    extend this key when extending native geometry. Recipient filters and zone
    damage/duration/provenance select effects, not geometric membership.
    """
    shape = area.get('shape') or 'sphere'
    # Do not eagerly parse numeric inputs: native geometry can reject an
    # out-of-range point before consulting its width. Preserve that order.
    return (_freeze(shape), _freeze(area.get('size_ft') or 0),
            _freeze(area.get('width_ft') or 5) if shape == 'line' else None,
            bool(area.get('placed')) if shape in ('line', 'cone') else False,
            bool(area.get('spreads')),
            _freeze(area.get('height_ft')) if shape == 'cylinder' else None,
            bool(area.get('include_origin')) if shape == 'cone' else False)


class _Index:
    def __init__(self, signature, grid_data):
        _freeze(grid_data)  # validate the pure-data contract once, not per cell query
        self.signature = signature
        self.grid_snapshot = deepcopy(grid_data)
        self.entries = OrderedDict()
        self.cell_count = 0

    def __deepcopy__(self, memo):
        # Preview/reaction clones reconstruct derived geometry, not a second
        # copy of a potentially large raster cache. Their saved state is exact.
        return None


def cells(engine, vertex, aim, area):
    """Return the original typed raster's immutable tuple in identical order.

    Shared by zones._cells and spatial_areas.reaches. No cells are synthesized,
    omitted or reordered. The key deliberately includes all grid/spec fields so
    future data fields cannot silently inherit an older geometry answer.
    """
    from . import typed_executor
    grid = engine.grid
    if type(grid) is not SquareGrid:
        return typed_executor.area_cells(engine, vertex, aim, area)
    try:
        state = getattr(engine, 'state', None)
        epoch = (id(grid), getattr(state, 'state_version', None), getattr(state, 'event_sequence', None),
                 typed_executor.area_cells, typed_executor.in_area, typed_executor._clear_line)
        key = (point(vertex), point(aim), spec_key(area))
        def resolve():
            # The field types follow from validated_index's identical inputs.
            signature = (*epoch[:3], tuple((k,type(v)) for k,v in geometry_data(grid).items()), *epoch[3:])
            return _current_index(engine, grid, signature)
        with _LOCK:
            index = validated_index(engine, grid, 'area_projection', epoch, resolve)
            if key in index.entries:
                index.entries.move_to_end(key)
                return index.entries[key]
    except TypeError:
        return typed_executor.area_cells(engine, vertex, aim, area)
    result = typed_executor.area_cells(engine, vertex, aim, area)
    if len(result) > MAX_CELLS:
        return result
    with _LOCK:
        while index.entries and (len(index.entries) >= MAX_ENTRIES or
                                 index.cell_count + len(result) > MAX_CELLS):
            _, old = index.entries.popitem(last=False)
            index.cell_count -= len(old)
        index.entries[key] = result
        index.cell_count += len(result)
    return result


def _current_index(engine, grid, signature):
    """This engine's valid index, else a valid shared one for the same grid/epoch, else a fresh one."""
    data = geometry_data(grid)
    index = engine.__dict__.get('_area_projection_index')
    # Built-in container equality checks every field without re-walking
    # thousands of scalar coordinates in Python. Snapshot all fields only
    # on a miss/change, including unrecorded in-place terrain mutations.
    if index is not None and index.signature == signature and data == index.grid_snapshot:
        return index
    index = _SHARED.get(signature)
    if index is None or data != index.grid_snapshot:
        index = _Index(signature, data)
        _SHARED[signature] = index
        while len(_SHARED) > MAX_SHARED:
            _SHARED.popitem(last=False)
    _SHARED.move_to_end(signature)
    engine.__dict__['_area_projection_index'] = index
    return index
