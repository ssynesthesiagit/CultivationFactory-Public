"""SOL203: AI decision speed without changing answers.

Preview views of one engine share one grid raster index per epoch, but a state
change or any grid edit still invalidates it, and a view or clone never
mutates the grid snapshot another engine relies on. ext.any_false keeps run()'s
subscriber order, full evaluation and error policy.
"""
from copy import copy, deepcopy

import pytest

from combat import area_projection, ext, typed_executor, zones
from combat.gate2_runtime_models import Position
from tests.h1_support import ME, duel


def _view(engine):
    """The same shallow projection area_knowledge.preview_engine builds for each candidate area."""
    view = copy(engine)
    view.state = engine.state.model_copy()
    return view


def _counted(monkeypatch):
    native = typed_executor.area_cells
    calls = []

    def counted(*args):
        calls.append(args)
        return native(*args)
    monkeypatch.setattr(typed_executor, 'area_cells', counted)
    return native, calls


def test_preview_views_share_one_index_per_epoch(monkeypatch):
    engine = duel([])
    native, calls = _counted(monkeypatch)
    vertex, aim = engine.state.actors[ME].position, Position(x=5, y=5)
    spec = {'shape': 'sphere', 'size_ft': 15}
    first = zones._cells(_view(engine), aim, spec, vertex)
    # A fresh view per candidate used to snapshot (deepcopy) the grid again and recompute.
    for _ in range(5):
        assert zones._cells(_view(engine), aim, dict(spec), vertex) is first
    assert len(calls) == 1
    assert first == native(engine, vertex, aim, {'shape': 'sphere', 'size_ft': 15, 'width_ft': None, 'spreads': False})


def test_shared_index_is_invalidated_by_a_state_change_and_by_terrain_edits(monkeypatch):
    engine = duel([])
    native, calls = _counted(monkeypatch)
    vertex, aim = Position(x=3, y=5), Position(x=5, y=5)
    area = {'shape': 'sphere', 'size_ft': 15}
    before = area_projection.cells(_view(engine), vertex, aim, area)
    # A recorded state change: a new epoch never inherits the old answers.
    engine.state.state_version += 1
    after_version = area_projection.cells(_view(engine), vertex, aim, area)
    assert after_version == before and len(calls) == 2
    engine.state.event_sequence += 1
    area_projection.cells(_view(engine), vertex, aim, area)
    assert len(calls) == 3
    # An unrecorded in-place wall edit at the same epoch is still seen by every view.
    engine.grid.blocked.add((4, 5))
    walled = area_projection.cells(_view(engine), vertex, aim, area)
    assert len(calls) == 4
    assert walled == native(engine, vertex, aim, area) != before


def test_a_view_or_clone_never_mutates_the_shared_grid_snapshot(monkeypatch):
    engine = duel([])
    vertex, aim = Position(x=3, y=5), Position(x=5, y=5)
    area = {'shape': 'sphere', 'size_ft': 15}
    original = area_projection.cells(engine, vertex, aim, area)
    shared = engine._area_projection_index
    snapshot = deepcopy(shared.grid_snapshot)
    assert shared.grid_snapshot is not vars(engine.grid)
    # A clone edits its own terrain; the original's grid, snapshot and answers are untouched.
    clone = deepcopy(engine)
    clone.grid.blocked.add((4, 5))
    clone_cells = area_projection.cells(clone, vertex, aim, area)
    assert clone_cells == typed_executor.area_cells(clone, vertex, aim, area) != original
    assert (4, 5) not in engine.grid.blocked
    # Native roof query objects are represented by their complete data snapshot.
    semantic = area_projection.geometry_data(engine.grid)
    assert shared.grid_snapshot == snapshot == semantic
    assert set(snapshot) == set(vars(engine.grid)) - {'_centerline_sight_cache'}
    assert area_projection.cells(_view(engine), vertex, aim, area) is original
    assert engine._area_projection_index is shared
    # A view shares the grid object: its edit is an edit of the real grid and invalidates for everyone,
    # while the old snapshot stays exactly what it recorded.
    view = _view(engine)
    view.grid.blocked.add((4, 5))
    assert area_projection.cells(engine, vertex, aim, area) == typed_executor.area_cells(engine, vertex, aim, area) != original
    assert shared.grid_snapshot == snapshot
    view.grid.blocked.discard((4, 5))
    assert area_projection.cells(engine, vertex, aim, area) == original


def _reference_any_false(point, *args, **kwargs):
    """The pre-SOL203 implementation, verbatim: every answer goes through run()."""
    return any(result is False for result in ext.run(point, *args, **kwargs))


def _subscribers(seen):
    def veto(*args, **kwargs):
        seen.append(('veto', args, kwargs))
        return False

    def allow(*args, **kwargs):
        seen.append(('allow', args, kwargs))
        return True

    def silent(*args, **kwargs):
        seen.append(('silent', args, kwargs))
        return None

    def broken(*args, **kwargs):
        seen.append(('broken', args, kwargs))
        raise RuntimeError('observational subscriber failure')

    def positional_only(a):  # rejects any keyword: a forwarded dispatch-control flag would make it raise
        seen.append(('positional_only', (a,), {}))
        return False
    return {'veto': veto, 'allow': allow, 'silent': silent, 'broken': broken, 'positional_only': positional_only}


def _observe(monkeypatch, implementation, order, nested, *args, **kwargs):
    seen, logged = [], []
    subs = _subscribers(seen)
    monkeypatch.setattr(ext, '_log', lambda point, function, exc, a: logged.append((point, function.__name__, type(exc).__name__)))
    monkeypatch.setitem(ext._HOOKS, 'sol203_probe', [subs[name] for name in order])
    monkeypatch.setitem(ext._NESTED_HOOKS, 'sol203_probe', {subs[name] for name in nested})
    try:
        answer = ('ok', implementation('sol203_probe', *args, **kwargs))
    except BaseException as exc:  # noqa: BLE001 -- compared, not swallowed
        answer = ('raised', type(exc).__name__)
    return answer, seen, logged


SETS = [
    ['veto', 'broken', 'allow'],
    ['allow', 'silent'],
    [],
    ['broken'],
    ['silent', 'positional_only', 'allow', 'veto'],
    ['positional_only', 'broken', 'silent'],
]
CALLS = [
    ((1,), {}),
    ((1,), {'_nested_only': True}),
    ((1,), {'_with_handlers': True}),
    ((1,), {'_transform_last': True}),
    ((1,), {'_nested_only': True, '_with_handlers': True}),
]


@pytest.mark.parametrize('order', SETS)
@pytest.mark.parametrize('call', CALLS)
def test_any_false_matches_the_run_based_implementation(monkeypatch, order, call):
    ext._load()
    args, kwargs = call
    nested = order[::2]
    new = _observe(monkeypatch, ext.any_false, order, nested, *args, **kwargs)
    old = _observe(monkeypatch, _reference_any_false, order, nested, *args, **kwargs)
    # Same answer, same subscribers called in the same order with the same arguments, same logged failures.
    assert new == old


def _controller_pause():
    return ext.ControllerPause('wait')


def _checkpoint_error():
    return ext.CheckpointError('checkpoint')


def _reaction_required():
    from combat.gate5_service import _ReactionRequired
    return _ReactionRequired.__new__(_ReactionRequired)


@pytest.mark.parametrize('make', [_controller_pause, _checkpoint_error, _reaction_required])
@pytest.mark.parametrize('call', CALLS[:2])
def test_any_false_propagates_the_same_control_exceptions_as_run(monkeypatch, make, call):
    ext._load()
    exc = make()
    seen, results = [], []

    def before(*args, **kwargs):
        seen.append('before')
        return None

    def raises(*args, **kwargs):
        seen.append('raises')
        raise exc

    def after(*args, **kwargs):
        seen.append('after')
        return False
    logged = []
    monkeypatch.setattr(ext, '_log', lambda *a: logged.append(a))
    monkeypatch.setitem(ext._HOOKS, 'sol203_probe', [before, raises, after])
    monkeypatch.setitem(ext._NESTED_HOOKS, 'sol203_probe', {before, raises, after})
    args, kwargs = call
    for implementation in (ext.any_false, _reference_any_false):
        seen.clear()
        with pytest.raises(type(exc)):
            implementation('sol203_probe', *args, **kwargs)
        results.append(list(seen))
    assert results[0] == results[1] == ['before', 'raises']
    assert logged == []


def test_any_false_follows_a_replaced_run(monkeypatch):
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'sol203_probe', [lambda *a: True])
    monkeypatch.setattr(ext, 'run', lambda point, *a, **k: [False])
    assert ext.any_false('sol203_probe') is True
