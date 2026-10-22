"""Manual table quotes retain native routes, vetoes and fresh commit authority."""
from types import SimpleNamespace

import pytest

from combat import ext, menu_rank
from combat.gate2_engine import Gate2Engine
from combat.tabletop_service import TabletopError
from tests.worker2_support import fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: (_ for _ in ()).throw(AssertionError('No model calls')),
        prefetch=lambda *a, **kw: None))


def test_table_quotes_skip_move_candidates_and_resolve_exact_route(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED5')
    normal = table.state(mid)
    native_moves = normal['menu']['moves']
    assert native_moves
    created = []
    original = Gate2Engine._candidate
    def count(self, kind, *a, **kw):
        if kind == 'MOVE':
            created.append(kw.get('destination'))
        return original(self, kind, *a, **kw)
    monkeypatch.setattr(Gate2Engine, '_candidate', count)
    compact = table.state(mid, compact_moves=True)
    assert created == [], 'manual grid must not materialize movement candidates'
    menu = compact['menu']
    assert menu['moves'] == []
    expected = {(m['destination']['x'], m['destination']['y'], m['destination'].get('z', 0),
                 m['cost_ft'], m['movement_mode'], bool(m.get('can_jump_down')),
                 bool(m.get('hazard_exposure'))) for m in native_moves}
    assert {tuple(row) for row in menu['movement_grid']} == expected
    assert table.state(mid, compact_moves=True) == compact
    # Compact/native caches cannot poison one another in either direction.
    assert table.state(mid) == normal
    # Ordinary characters can also quote a jump followed by a fall. Use a
    # supported walking destination for the persisted endpoint assertion.
    chosen = next(m for m in native_moves if m['movement_mode'] == 'walk'
                  and m['destination'].get('z', 0) == 0)
    quote = table.preview_destination(mid, menu['decision_id'], menu['state_version'],
                                     menu['actor_id'], chosen['destination'], chosen['movement_mode'])
    assert quote['candidate']['canonical_path'] == chosen['path']
    result = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
                       menu['state_version'], menu['actor_id'], chosen['path'],
                       compact['last_sequence'], chosen['movement_mode'], defer_menu=True)
    assert result['status'] == 'COMMITTED'
    with pytest.raises(TabletopError):
        table.preview_destination(mid, menu['decision_id'], menu['state_version'],
                                  menu['actor_id'], chosen['destination'], chosen['movement_mode'])
    assert combat._load_session(mid).engine.state.actors[menu['actor_id']].position.model_dump(mode='json') == chosen['destination']


def test_compact_grid_preserves_plugin_movement_vetoes(tmp_path, monkeypatch):
    ext._load()
    def deny_east(engine, actor, candidate, action):
        if candidate.kind == 'MOVE' and candidate.destination.x > actor.position.x:
            return False
    monkeypatch.setitem(ext._HOOKS, 'candidate_allowed', [*ext._HOOKS.get('candidate_allowed', ()), deny_east])
    _, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED5-veto')
    full = table.state(mid)['menu']['moves']
    compact = table.state(mid, compact_moves=True)['menu']['movement_grid']
    assert {(m['destination']['x'], m['destination']['y'], m['destination'].get('z', 0)) for m in full} == {
        tuple(row[:3]) for row in compact}


def test_text_pool_retains_all_printed_text():
    from combat.table_text_pool import pack
    text = 'Move 10 feet, then choose one creature. ' * 20
    state = {'a': text, 'b': [text, {'short': 'kept'}], 'none': None, 'flag': False}
    pooled = pack(state)
    assert pooled['table_texts'] == [text]
    assert pooled['a'] == pooled['b'][0] == {'$table_text': 0}
    assert state['a'] == text


def test_flight_prices_each_destination_once_and_preserves_actual_edge_surcharges(monkeypatch):
    from combat import flight, motion
    from contextlib import contextmanager
    from tests.h1_support import ME, duel
    from tests.test_lock10_flight_movement import grant
    engine = duel([])
    actor = engine.state.actors[ME]
    grant(engine, actor, speed=30)
    actor.movement_remaining_ft = 15
    ext._load()
    def uphill(engine, actor, previous, destination, mode):
        return 5 if destination.z > previous.z else 0
    monkeypatch.setitem(ext._HOOKS, 'movement_elevation_surcharge', [uphill])
    original = flight.step_cost
    calls = []
    reprices = []
    native_repriced = motion.repriced
    @contextmanager
    def counted_repricing(*args, **kwargs):
        reprices.append(1)
        with native_repriced(*args, **kwargs):
            yield
    def counted(*args, **kwargs):
        calls.append((args[2], args[3]))
        return original(*args, **kwargs)
    monkeypatch.setattr(flight, 'step_cost', counted)
    monkeypatch.setattr(motion, 'repriced', counted_repricing)
    routes = flight.reachable(engine, actor, mode='fly')
    assert routes
    assert all(previous == destination for previous, destination in calls)
    assert len({destination for _, destination in calls}) == len(calls)
    assert len(reprices) <= len(calls) + 1, 'terrain repricing must scale with squares, not incoming edges'
    for path, cost, _ in routes.values():
        assert sum(original(engine, actor, a, b, 'fly') for a, b in zip(path, path[1:])) == cost


def test_background_warming_skips_stale_and_automatic_boundaries():
    from collections import OrderedDict
    import threading
    from combat.movement_menu import active
    from combat.tabletop_service import TabletopService
    table = object.__new__(TabletopService)
    table._warm_guard = threading.Lock()
    table._warm_running = True
    table._warm_requests = OrderedDict([('stale', 1), ('auto', 2), ('human', 2)])
    engine = SimpleNamespace(state=SimpleNamespace(state_version=2, terminal_result=None, current_actor_id='owner'))
    seen = []
    table.combat = SimpleNamespace(
        _load_session=lambda mid: SimpleNamespace(match_id=mid, engine=engine),
        _read_metadata=lambda mid, session: {'match': mid},
        _mode_for_actor=lambda metadata, session, actor: 'LOCAL_AUTO' if metadata['match'] == 'auto' else 'MANUAL',
        decision=lambda mid, **kw: seen.append((mid, active(), kw['table_header'])))
    table._warm_menus()
    assert seen == [('human', True, True)]
    assert not table._warm_running and not table._warm_requests


def test_commit_warming_schedules_one_worker_without_inline_enumeration(monkeypatch):
    from collections import OrderedDict
    import threading
    from combat.tabletop_service import TabletopService
    table = object.__new__(TabletopService)
    table.prewarm_menus = True
    table._warm_guard = threading.Lock()
    table._warm_running = False
    table._warm_requests = OrderedDict()
    started = []
    class Thread:
        def __init__(self, **kwargs):
            assert kwargs['daemon']
        def start(self):
            started.append(1)
    monkeypatch.setattr(threading, 'Thread', Thread)
    for version in range(20):
        table._schedule_menu('fight', {'state': {'menu_pending': {'state_version': version}}})
    assert started == [1]
    assert table._warm_requests == {'fight': 19}
    table._warm_running = False
    def unavailable(self):
        raise RuntimeError('no worker available')
    monkeypatch.setattr(Thread, 'start', unavailable)
    table._schedule_menu('fight', {'state': {'menu_pending': {'state_version': 20}}})
    assert not table._warm_running


def test_http_compact_state_destination_quote_and_commit(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    from tests.h1_support import ROOT
    _, _, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED5-HTTP')
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    app.state.agent_seats.table.prewarm_menus = False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            prefix = f'/api/tabletop/matches/{mid}'
            raw = (await client.get(prefix + '/state?compact=true')).json()
            texts = raw.get('table_texts', [])
            def expand(value):
                if isinstance(value, dict):
                    if set(value) == {'$table_text'}:
                        return texts[value['$table_text']]
                    return {k: expand(v) for k, v in value.items() if k != 'table_texts'}
                if isinstance(value, list):
                    return [expand(v) for v in value]
                return value
            state = expand(raw)
            menu = state['menu']
            assert menu['moves'] == []
            z, cost, mode, drop, hazard, cells = menu['movement_grid']['layers'][0]
            binding = {'decision_id': menu['decision_id'], 'state_version': menu['state_version'],
                       'actor_id': menu['actor_id']}
            headers = {'x-foundry-token': token}
            response = await client.post(prefix + '/movement-destination/preview', headers=headers,
                json={**binding, 'destination': {'x': cells[0], 'y': cells[1], 'z': z}, 'movement_mode': mode})
            assert response.status_code == 200, response.text
            candidate = response.json()['candidate']
            response = await client.post(prefix + '/movement-path/commit', headers=headers,
                json={**binding, 'candidate_id': candidate['candidate_id'],
                      'waypoints': candidate['canonical_path'], 'movement_mode': mode,
                      'after': state['last_sequence']})
            assert response.status_code == 200, response.text
            assert response.json()['status'] == 'COMMITTED'
            assert response.json()['state']['menu'] is None
    run_asgi(exercise())


def test_failed_move_boundaries_keep_native_progress_guard_and_paths(tmp_path, monkeypatch):
    from combat import movement_menu
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED5-progress')
    assert not movement_menu.native_routes_required(combat._load_session(mid))
    native = table.state(mid)['menu']['moves']
    monkeypatch.setattr(movement_menu, 'native_routes_required', lambda engine: True)
    menu = table.state(mid, compact_moves=True)['menu']
    assert 'movement_grid' not in menu
    assert menu['moves'] == native


def test_compact_ranking_keeps_every_option_without_rebuilding_ai_context(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '1')
    def forbidden(*args, **kwargs):
        raise AssertionError('compact ranking regenerated the native AI menu')
    monkeypatch.setattr(menu_rank, 'native_scores', forbidden)
    monkeypatch.setattr(menu_rank, 'sheet_goal', lambda *args: 'Protect your allies')
    monkeypatch.setattr(menu_rank, 'rank_ids', lambda query, rows, **kwargs: [row[0] for row in reversed(rows)])
    monkeypatch.setattr(menu_rank, 'prefetch_next_actor', lambda *args: None)
    actor = SimpleNamespace(entity_id='owner', current_hp=10, maximum_hp=10, display_name='Owner')
    engine = SimpleNamespace(state=SimpleNamespace(actors={'owner': actor}, current_actor_id='owner'))
    options = [{'candidate_id': f'option:{i}', 'target_ids': [], 'label': f'Choice {i}'} for i in range(10)]
    menu = {'manual': True, 'actor_id': 'owner', 'control_mode': 'SUGGESTED',
            'moves': [], 'movement_grid': [],
            'actions': [{'label': 'Act', 'economy': 'ACTION', 'options': options}]}
    menu_rank.rank_menu(menu, engine, combat=SimpleNamespace(), known={'owner'})
    assert [option['candidate_id'] for option in menu['actions'][0]['options']] == [
        f'option:{i}' for i in reversed(range(10))]


def test_lazy_veto_metadata_preserves_native_bulk_dictionary_queries():
    from combat.movement_menu import RouteQuote
    from combat.gate2_runtime_models import Position
    start, end = Position(x=1, y=1), Position(x=2, y=1)
    path = (start, end)
    full = {'compressed_path': [{'x': 1, 'y': 1}, {'x': 2, 'y': 1}],
            'reaction_exposure': [], 'hazard_exposure': False}
    reads = []
    def candidates(actor, *, intent):
        reads.append(intent.destination)
        return [SimpleNamespace(canonical_path=path, metadata=full)]
    engine = SimpleNamespace(grid=SimpleNamespace(roof_surfaces=[]), _movement_candidates=candidates)
    quote = RouteQuote(engine, SimpleNamespace(entity_id='owner'), end, path, 5, 'walk', False, False, None)
    assert quote.metadata.get('teleport') is None and reads == []
    assert quote.metadata.copy() == full
    assert len(quote.metadata) == len(full)
    assert dict(quote.metadata) == full
    assert quote.metadata == full
    assert not quote.metadata != full
    assert reads == [end], 'bulk readers should materialize the native quote once'
