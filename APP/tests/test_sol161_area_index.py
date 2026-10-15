"""Exact raster order, full-input invalidation and bounded transient storage."""
from copy import deepcopy
from types import SimpleNamespace

from combat import area_projection, typed_executor, zones
from combat.canonical import canonical_bytes
from combat.gate2_runtime_models import Position
from tests.h1_support import ME, duel


def test_zone_raster_reuses_equivalent_specs_and_preserves_native_order(monkeypatch):
    engine = duel([])
    vertex = engine.state.actors[ME].position
    aim = Position(x=5, y=5)
    spec = {'shape': 'sphere', 'size_ft': 15, 'spreads': True}
    native = typed_executor.area_cells
    calls = []
    def counted(*args):
        calls.append(1)
        return native(*args)
    monkeypatch.setattr(typed_executor, 'area_cells', counted)
    before = canonical_bytes(engine.state.model_dump(mode='json'))
    first = zones._cells(engine, aim, spec, vertex)
    assert zones._cells(engine, aim, dict(spec), vertex) is first
    assert len(calls) == 1
    assert first == native(engine, vertex, aim, {'shape':'sphere', 'size_ft':15,
        'width_ft':None, 'spreads':True})
    assert canonical_bytes(engine.state.model_dump(mode='json')) == before
    copied = deepcopy(engine)
    assert copied._area_projection_index is None
    assert zones._cells(copied, aim, spec, vertex) == first
    assert len(calls) == 2
    assert '_area_projection_index' not in engine.state.model_dump(mode='json')


def test_raster_detects_all_unversioned_grid_fields_spec_and_origins():
    engine = duel([])
    vertex = Position(x=3, y=5)
    aim = Position(x=5, y=5)
    area = {'shape':'sphere', 'size_ft':15, 'spreads':True}
    def exact():
        cached = area_projection.cells(engine,vertex,aim,area)
        assert cached == typed_executor.area_cells(engine,vertex,aim,area)
        return engine._area_projection_index
    previous = exact()
    for change in (
        lambda: engine.grid.blocked.add((6,5)),
        lambda: engine.grid.terrain_heights.update({'BLOCKED':{(6,5):5}}),
        lambda: engine.grid.terrain_spans.update({'BLOCKED':{(6,5):[(5,10)]}}),
        lambda: setattr(engine.grid, 'finite_heights', True),
        lambda: setattr(engine.grid, 'square_size_ft', 10),
        lambda: setattr(engine.grid, 'width', engine.grid.width-1),
        lambda: setattr(engine.grid, 'height', engine.grid.height-1),
        lambda: setattr(engine.state, 'state_version', engine.state.state_version+1),
        lambda: setattr(engine.state, 'event_sequence', engine.state.event_sequence+1),
    ):
        change()
        current = exact()
        assert current is not previous
        previous = current
    for shape in ('cube','line','cone','sphere'):
        area.update(shape=shape, width_ft=10, placed=True, size_ft=20)
        exact()
    aim = Position(x=6,y=6,z=1)
    exact()
    vertex = Position(x=4,y=5,z=2)
    exact()


def test_raster_index_is_bounded_and_unknown_grid_attributes_fall_back(monkeypatch):
    engine = duel([])
    vertex = engine.state.actors[ME].position
    area = {'shape':'sphere','size_ft':5}
    monkeypatch.setattr(area_projection, 'MAX_ENTRIES', 2)
    monkeypatch.setattr(area_projection, 'MAX_CELLS', 10)
    for x in range(3,8):
        aim = Position(x=x,y=5)
        assert area_projection.cells(engine,vertex,aim,area) == typed_executor.area_cells(engine,vertex,aim,area)
        index = engine._area_projection_index
        assert len(index.entries) <= 2 and index.cell_count <= 10
    # A future provider/custom grid attribute outside the supported data
    # contract must never be guessed or silently ignored by the signature.
    engine.grid.unknown_provider = object()
    assert area_projection.cells(engine,vertex,aim,area) == typed_executor.area_cells(engine,vertex,aim,area)


def test_grid_only_geometry_consumers_need_no_fight_state():
    engine = SimpleNamespace(grid=duel([]).grid)
    origin = Position(x=5,y=5)
    area = {'shape':'sphere','size_ft':10}
    assert area_projection.cells(engine,origin,origin,area) == typed_executor.area_cells(engine,origin,origin,area)


def test_geometry_key_covers_every_native_area_field():
    import ast, inspect, textwrap
    fields = set()
    for name in ('in_area','area_cells','placed_at_aim','_line_ray','_ray_offsets'):
        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(typed_executor,name))))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'area'
                    and node.func.attr == 'get' and node.args and isinstance(node.args[0], ast.Constant)):
                fields.add(node.args[0].value)
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == 'area' and isinstance(node.slice, ast.Constant)):
                fields.add(node.slice.value)
    assert fields <= area_projection.GEOMETRY_FIELDS, fields-area_projection.GEOMETRY_FIELDS


def test_membership_preserves_native_early_rejection_before_width_parsing():
    from combat import read_queries, spatial_areas
    engine = duel([])
    actor = engine.state.actors[ME]
    vertex, aim = Position(x=5,y=5), Position(x=6,y=5)
    area = {'shape':'line','size_ft':1,'width_ft':'not a number'}
    @read_queries.pure
    def query(e):
        assert not spatial_areas.actor_in_area(e,actor,vertex,aim,area)
    query(engine)
