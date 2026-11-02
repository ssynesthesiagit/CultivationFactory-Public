"""Cold menu work bounds and cached/native equivalence without model calls."""
from types import SimpleNamespace

import pytest

from combat import ext, menu_rank
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import Position
from combat.read_queries import candidate_pass
from combat.ext import movement_safety
from tests.h1_support import ME, FOE, duel, ROOT


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: (_ for _ in ()).throw(AssertionError('No live model')),
        prefetch=lambda *a, **kw: None))


def test_movement_speed_checked_once_per_origin_and_revision(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    candidate = SimpleNamespace(kind=SimpleNamespace(value='MOVE'), destination=Position(x=2, y=3))
    calls = []
    monkeypatch.setattr(engine, '_effective_speed', lambda a: calls.append(a.position) or a.speed_ft)
    with candidate_pass(engine):
        for _ in range(100):
            assert movement_safety.movement_allowed(engine, actor, candidate, None) is None
        assert len(calls) == 1
        actor.position = actor.position.model_copy(update={'z': 1})
        movement_safety.movement_allowed(engine, actor, candidate, None)
        assert len(calls) == 2
        actor.speed_ft = 0
        engine.state.state_version += 1
        assert movement_safety.movement_allowed(engine, actor, candidate, None) is False
        assert len(calls) == 3
    actor.speed_ft = 30
    assert movement_safety.movement_allowed(engine, actor, candidate, None) is None
    assert len(calls) == 4


def test_opportunity_distances_scale_with_cells_not_incoming_edges(monkeypatch):
    engine = duel([])
    actor, hostile = engine.state.actors[ME], engine.state.actors[FOE]
    points = [Position(x=3, y=y, z=z) for y in (4, 5, 6) for z in (0, 1)]
    edges = [(a, b) for a in points for b in points if a != b]
    expected = [engine.opportunity_eligible(actor, a, b, reactors=(hostile,)) for a, b in edges]
    calls = []
    original = Gate2Engine._distance_actor_to_actor
    def distance(self, *args, **kwargs):
        calls.append(kwargs.get('actor_position'))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Gate2Engine, '_distance_actor_to_actor', distance)
    cache = {}
    actual = [engine.opportunity_eligible(actor, a, b, reactors=(hostile,), cache=cache) for a, b in edges]
    assert actual == expected
    # Some actual leave-reach edges also query defensive rules. Count only
    # the footprint distances whose explicit projected position we optimized.
    assert len([p for p in calls if p is not None]) <= len(points)


def test_table_cached_and_fresh_options_equal_across_committed_states(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import fixture
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED6-equivalence')
    for _ in range(3):
        cached = table.state(mid, compact_moves=True)
        assert cached == table.state(mid, compact_moves=True)
        fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid, compact_moves=True)
        assert cached == fresh
        native = table.state(mid)['menu']
        compact = cached['menu']
        assert compact['actions'] == native['actions']
        # main's route quote carries the known-hazard column as the seventh
        # element; compact reads expose the same row unchanged so the client
        # can warn on it.
        assert {tuple(row) for row in compact['movement_grid']} == {
            (m['destination']['x'], m['destination']['y'], m['destination'].get('z', 0),
             m['cost_ft'], m['movement_mode'], bool(m.get('can_jump_down')),
             bool(m.get('hazard_exposure'))) for m in native['moves']}
        result = table.act(mid, compact['end_turn'], compact['decision_id'], compact['state_version'],
                           cached['last_sequence'], defer_menu=True)
        assert result['status'] == 'COMMITTED'


def test_preparation_starts_before_committed_presentation(tmp_path, monkeypatch):
    from tests.worker2_support import fixture
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED6-preparation')
    before = table.state(mid, compact_moves=True)
    order = []
    monkeypatch.setattr(table, '_schedule_menu', lambda mid, result: order.append(('prepare', result['state']['menu_pending']['state_version'])))
    original = combat.presentation
    def presentation(*args, **kwargs):
        if not kwargs.get('include_candidates', True):
            order.append(('present', kwargs['session'].engine.state.state_version))
        return original(*args, **kwargs)
    monkeypatch.setattr(combat, 'presentation', presentation)
    menu = before['menu']
    result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], before['last_sequence'], defer_menu=True)
    version = result['state']['menu_pending']['state_version']
    assert order == [('prepare', version), ('present', version)]


def test_foreground_joins_background_build_without_duplicate_enumeration(tmp_path, monkeypatch):
    import threading
    from combat.tabletop_service import _menu_build_lock
    from tests.worker2_support import fixture
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED6-join')
    combat._derived.clear()
    entered, release = threading.Event(), threading.Event()
    original = combat.decision
    def decision(*args, **kwargs):
        if threading.current_thread().name == 'test-warm':
            entered.set()
            assert release.wait(20)
        return original(*args, **kwargs)
    monkeypatch.setattr(combat, 'decision', decision)
    version = combat._load_session(mid).engine.state.state_version
    table._warm_requests[mid] = version
    table._warm_running = True
    warmer = threading.Thread(target=table._warm_menus, name='test-warm')
    warmer.start()
    try:
        assert entered.wait(20)
        assert not _menu_build_lock(mid).acquire(blocking=False)
    finally:
        release.set()
        warmer.join(20)
    assert not warmer.is_alive()
    # Warming populated the exact compact cache; a foreground query can no
    # longer invoke native generation for this state.
    monkeypatch.setattr(Gate2Engine, '_generate_legal_candidates',
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('duplicate build')))
    assert table.state(mid, lazy=True)['menu']['actions']
