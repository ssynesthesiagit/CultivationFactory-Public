"""Review fixes at the real HTTP boundary; no live models or browser launches."""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from combat import menu_rank
from combat.gate5_service import CombatService
from tests.async_support import run_asgi
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics import game, OWNER, SHARK, GLIDE


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda *a: pytest.fail('No live embedding requests'),
        prefetch=lambda *a, **kw: None))


def application(tmp_path):
    from app.api import create_app
    from app.core import Settings
    # Full HTTP app startup needs its production migrations. Some cleared
    # snapshots omit those assets; report the missing dependency directly
    # instead of starting an empty database and failing later with SQL errors.
    for name in ('001_initial.sql', '010_optional_ai_provider.sql'):
        migration = ROOT / 'migrations' / name
        if not migration.is_file():
            raise FileNotFoundError(f'HTTP fixture requires app migration: {migration}')
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    app.state.agent_seats.table.prewarm_menus = False
    return app


def unpack_state(raw):
    """HTTP API clients expand the lossless string pool before using identities."""
    texts = raw.get('table_texts', [])
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'$table_text'}:
                return texts[value['$table_text']]
            return {k: expand(v) for k, v in value.items() if k != 'table_texts'}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value
    return expand(raw)


def test_native_swim_preview_commit_and_reload_over_http(tmp_path):
    _, _, mid = game(tmp_path, [SHARK, GLIDE], material='soil', ask=False)
    app = application(tmp_path)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            prefix = f'/api/tabletop/matches/{mid}'
            state = unpack_state((await client.get(prefix + '/state?compact=true')).json())
            menu = state['menu']
            assert any(layer[2] == 'swim' for layer in menu['movement_grid']['layers'])
            binding = {k: menu[k] for k in ('actor_id', 'decision_id', 'state_version')}
            request = {**binding, 'destination': {'x': 5, 'y': 6, 'z': 0}, 'movement_mode': 'swim'}
            # Transport accepts general modes; native authority rejects unavailable ones.
            denied = await client.post(prefix + '/movement-destination/preview', headers=headers,
                                       json={**request, 'movement_mode': 'unowned-mode'})
            assert denied.status_code == 422
            assert denied.json()['error']['code'] == 'TABLETOP_ROUTE_INVALID', denied.text
            quoted = await client.post(prefix + '/movement-destination/preview', headers=headers, json=request)
            assert quoted.status_code == 200, quoted.text
            candidate = quoted.json()['candidate']
            assert candidate['movement_cost_ft'] == 15
            committed = await client.post(prefix + '/movement-path/commit', headers=headers,
                json={**binding, 'candidate_id': candidate['candidate_id'],
                      'movement_mode': 'swim', 'waypoints': candidate['canonical_path'],
                      'after': state['last_sequence']})
            assert committed.status_code == 200, committed.text
            assert committed.json()['status'] == 'COMMITTED'
            stale = await client.post(prefix + '/movement-destination/preview', headers=headers, json=request)
            assert stale.status_code == 409
    run_asgi(exercise())
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    position = cold.state.actors[OWNER].position
    assert (position.x, position.y, position.z) == (5, 6, 0)
    event = next(e for e in reversed(cold.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    assert event.payload['cost_ft'] == 15
    assert event.payload['movement_mode'] == 'swim'


def test_swim_is_not_granted_by_accepting_transport_mode(tmp_path):
    _, _, mid = game(tmp_path, [], material='soil', ask=False)
    app = application(tmp_path)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            prefix = f'/api/tabletop/matches/{mid}'
            menu = unpack_state((await client.get(prefix + '/state?compact=true')).json())['menu']
            assert all(layer[2] != 'swim' for layer in menu['movement_grid']['layers'])
            response = await client.post(prefix + '/movement-destination/preview',
                headers={'x-foundry-token': token}, json={
                    **{k: menu[k] for k in ('actor_id', 'decision_id', 'state_version')},
                    'movement_mode': 'swim', 'destination': {'x': 5, 'y': 6, 'z': 0}})
            assert response.status_code == 422
            assert response.json()['error']['code'] == 'TABLETOP_ROUTE_INVALID', response.text
    run_asgi(exercise())


def test_known_hazard_survives_service_projection_and_browser_decoding(tmp_path):
    _, table, mid = game(tmp_path, [], ask=False, arena_update={'terrain_regions': [{
        'region_id': 'known-danger', 'terrain_type': 'QI_HAZARD', 'movement_cost': 1,
        'cells': [{'x': 4, 'y': 6}]}]})
    native = table.state(mid)['menu']['moves']
    expected = {(m['destination']['x'], m['destination']['y'], m['destination'].get('z', 0),
                 m['cost_ft'], m['movement_mode'], bool(m.get('can_jump_down')),
                 bool(m.get('hazard_exposure'))) for m in native}
    assert any(row[-1] for row in expected)
    compact = table.state(mid, compact_moves=True)['menu']
    assert {tuple(row) for row in compact['movement_grid']} == expected
    from combat.movement_menu import pack_grid
    grid = pack_grid(compact['movement_grid'])
    root = Path(__file__).resolve().parents[1]
    script = """
import {expandMovementGrid} from './static/tabletop/movement-grid.js';
import {slotRows} from './static/tabletop/ranked-menu.js';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const menu = expandMovementGrid({movement_grid: JSON.parse(input)});
console.log(JSON.stringify({rows: menu.moves.map(m => [m.destination.x, m.destination.y,
  m.destination.z, m.cost_ft, m.movement_mode, m.can_jump_down, m.hazard_exposure]),
  warnings: slotRows(menu).Movement.filter(row => row.detail.includes('known hazard')).length}));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(grid),
                            cwd=root, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert {tuple(row) for row in decoded['rows']} == expected
    assert decoded['warnings'] == sum(row[-1] for row in expected)


def test_offline_client_regressions():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop('MENUSPEED5_BROWSER_URL', None)
    result = subprocess.run(['node', '--test', '--test-isolation=none',
                             'tests/menuspeed5_grid.test.mjs', 'tests/menuspeed5_browser.test.mjs'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=60)
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
