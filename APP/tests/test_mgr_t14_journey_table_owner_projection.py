"""Table-owner journey entry points: the projection and the real endpoints.

The scene boundary and the world-fact input are table-owner inputs. Their
answers must be the journey projection every other journey route returns (no
replay genesis, no command journal), and the HTTP surface must reach them, so
a printed once-per-scene limit can refresh in play.
"""
import ast
from pathlib import Path

import httpx
import pytest

from combat import ext
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t16_athletics_travel import game, scene, SOURCE, A, B

APP = Path(__file__).resolve().parents[1]
KIND = 'journey_light'
WORLD_FACT_ROUTE = '/api/combat/journeys/{journey_id}/world-facts'
END_SCENE_ROUTE = '/api/combat/journeys/{journey_id}/end-scene'


@ext.hook('fact_admission_schema')
def journey_light_schema(session, source, subject, kind):
    """A table-owner fact kind, so the world-fact path has one admitting schema."""
    if kind != KIND:
        return None
    return {'value_type': 'flag', 'maximum_seconds': 60, 'authority': 'table_owner',
            'description': 'The table owner records whether the road is lit.'}


def _world_payload(state):
    return {'source': 'tianxia.path.body_refining', 'subject': A, 'kind': KIND,
            'scope': state['journey_id'], 'value': 1,
            'expires_at': int(state['seconds']) + 30, 'readers': []}


def _assert_projection(state):
    assert 'replay_base' not in state
    assert 'command_journal' not in state
    return state


def test_end_scene_returns_the_journey_projection(tmp_path, monkeypatch):
    cold, jid, unused = game(tmp_path, monkeypatch)
    before = cold().journey_state(jid)
    ended = _assert_projection(cold().journey_end_scene(jid, before['revision'],
                                                       'The road turns; the scene changes.'))
    assert ended == cold().journey_state(jid)
    assert ended['scene_number'] == 1 and ended['scene_id'].endswith(':scene:1')
    assert ended['events'][-1]['kind'] == 'SCENE_ENDED'
    assert ended['events'][-1]['authority'] == 'table_owner'


def test_world_fact_returns_the_journey_projection(tmp_path, monkeypatch):
    cold, jid, unused = game(tmp_path, monkeypatch)
    before = cold().journey_state(jid)
    recorded = _assert_projection(cold().journey_world_fact(jid, before['revision'],
                                                             _world_payload(before)))
    assert recorded == cold().journey_state(jid)
    assert recorded['events'][-1]['kind'] == 'WORLD_FACT_DECLARED'


def _post_routes():
    """The POST routes the API module registers, by path."""
    tree = ast.parse((APP / 'app/api.py').read_text())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == 'post'):
                found[decorator.args[0].value] = node
    return found


def test_the_documented_journey_endpoints_are_wired():
    """The documented table-owner endpoints are real routes on the real service."""
    routes = _post_routes()
    for path, service in ((WORLD_FACT_ROUTE, 'journey_world_fact'),
                          (END_SCENE_ROUTE, 'journey_end_scene')):
        handler = routes.get(path)
        assert handler is not None, f'{path} must be a real POST route'
        called = {node.func.attr for node in ast.walk(handler)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == 'combat'}
        assert service in called, f'{path} must call combat.{service}'


def test_http_end_scene_and_world_fact_endpoints(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import FoundryError, Settings
    from tests.async_support import run_asgi

    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
                        sheet([SOURCE] if pid == 'traveller' else [], cl=15, name=pid))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': scene()})
    try:
        app = create_app(Settings.from_env(ROOT, tmp_path))
    except FoundryError as exc:
        if exc.code != 'NS1R_BACKGROUND_ROUTE_AUTHORITY_AMBIGUOUS':
            raise
        # The published copy ships scrambled background bullet text, so the
        # application cannot be built there. The routes are proved statically
        # above; the round trip runs where the application can be built.
        pytest.skip('the published copy cannot build the application (scrambled background bullet text)')

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            created = await client.post('/api/combat/journeys', headers=headers,
                    json={'project_ids': ['traveller', 'companion'], 'arena_id': 'scene',
                          'positions': {A: {'x': 0, 'y': 1}, B: {'x': 0, 'y': 2}},
                          'base_paces': {A: 5, B: 5}})
            assert created.status_code == 200, created.text
            state = created.json()
            jid = state['journey_id']
            ended = await client.post(f'/api/combat/journeys/{jid}/end-scene', headers=headers,
                    json={'revision': state['revision'],
                          'reason': 'The road turns; the scene changes.'})
            assert ended.status_code == 200, ended.text
            body = _assert_projection(ended.json())
            assert body == (await client.get(f'/api/combat/journeys/{jid}')).json()
            assert body['scene_number'] == 1
            fact = await client.post(f'/api/combat/journeys/{jid}/world-facts', headers=headers,
                    json={'revision': body['revision'], 'payload': _world_payload(body)})
            assert fact.status_code == 200, fact.text
            recorded = _assert_projection(fact.json())
            assert recorded == (await client.get(f'/api/combat/journeys/{jid}')).json()
            stale = await client.post(f'/api/combat/journeys/{jid}/end-scene', headers=headers,
                    json={'revision': state['revision'], 'reason': 'A stale revision changes nothing.'})
            assert stale.status_code == 400

    run_asgi(exercise())


def test_end_scene_needs_a_reason_and_a_fresh_revision(tmp_path, monkeypatch):
    cold, jid, unused = game(tmp_path, monkeypatch)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        cold().journey_end_scene(jid, before['revision'], '   ')
    with pytest.raises(ValueError):
        cold().journey_end_scene(jid, before['revision'] + 5, 'A stale revision changes nothing.')
    assert cold().journey_state(jid) == before
