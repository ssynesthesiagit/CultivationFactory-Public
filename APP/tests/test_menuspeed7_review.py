"""F3: compact HTTP material movement and native hazard disclosure, offline."""
import json
from pathlib import Path
import subprocess

import httpx
import pytest

from app.api import create_app
from app.core import Settings
from combat.gate5_service import CombatService
from tests.async_support import run_asgi
from tests.auto8f1_table_support import OWNER, reload_identical
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics import game, SHARK, GLIDE


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')


@pytest.mark.parametrize('owns', [True, False])
def test_compact_http_material_preview_commit_reload(tmp_path, owns):
    service, _, mid = game(tmp_path, [SHARK, GLIDE] if owns else [], material='soil', ask=False)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            url = f'/api/tabletop/matches/{mid}'
            state = await client.get(url + '/state', params={'compact': 'true'})
            assert state.status_code == 200, state.text
            menu = state.json()['menu']
            assert menu['lazy'] and menu['moves'] == []
            grid = menu['movement_grid']
            rows = ([row for row in grid] if isinstance(grid, list) else
                    [[x, y, z, cost, mode, drop] for z, cost, mode, drop, cells in grid['layers']
                     for x, y in zip(cells[::2], cells[1::2])])
            offered = [row for row in rows if row[:3] == [4, 6, 0] and row[4] == 'swim']
            assert bool(offered) == owns
            if owns:
                assert offered[0][3] == 10  # Soil is difficult terrain.
            body = dict(decision_id=menu['decision_id'], state_version=menu['state_version'],
                        actor_id=OWNER, destination={'x': 4, 'y': 6, 'z': 0}, movement_mode='swim')
            preview = await client.post(url + '/movement-destination/preview', json=body)
            if not owns:
                assert preview.status_code == 422
                # Rejection belongs to owned capability validation, not the HTTP enum.
                assert 'no longer available' in preview.text, preview.text
                return
            assert preview.status_code == 200, preview.text
            quote = preview.json()['candidate']
            assert quote['metadata']['movement_mode'] == 'swim'
            assert quote['movement_cost_ft'] == 10
            assert quote['canonical_path'][-1] == body['destination']
            commit = await client.post(url + '/movement-path/commit', json={
                key: value for key, value in {**body, 'candidate_id': quote['candidate_id'],
                    'waypoints': quote['canonical_path']}.items() if key != 'destination'})
            assert commit.status_code == 200, commit.text
            assert commit.json()['status'] == 'COMMITTED'
            fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
            assert fresh.state.actors[OWNER].position.model_dump(mode='json') == body['destination']
            receipt = next(e for e in reversed(fresh.events) if e.event_type == 'MOVEMENT_COMMITTED')
            assert receipt.payload['movement_mode'] == 'swim' and receipt.payload['cost_ft'] == 10
            reload_identical(service, mid, tmp_path)

    run_asgi(exercise())


def test_checked_compact_hazard_is_disclosed_before_confirmation(tmp_path):
    _, table, mid = game(tmp_path, [], ask=False, arena_update={'terrain_regions': [{
        'region_id': 'visible-hazard', 'terrain_type': 'QI_HAZARD', 'movement_cost': 1,
        'cells': [{'x': 4, 'y': 6}]}]})
    state = table.state(mid, lazy=True, fog=True, fog_view='own', fog_actor_ids=(OWNER,))
    menu = state['menu']
    quote = table.preview_destination(mid, menu['decision_id'], menu['state_version'], OWNER,
                                      {'x': 4, 'y': 6, 'z': 0}, 'walk')
    assert quote['candidate']['metadata']['hazard_exposure'] is True
    # Use the compact row's price/mode without introducing a hazard flag.
    eager = table.state(mid)['menu']
    native = next(m for m in eager['moves'] if m['destination'] == {'x': 4, 'y': 6, 'z': 0}
                  and m['movement_mode'] == 'walk')
    assert native['hazard_exposure'] is True
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', 'tests/menuspeed7_review.mjs'], cwd=app,
        input=json.dumps(dict(state=state, quote=quote, native=native)),
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
