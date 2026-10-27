"""Table-owner journey entry points: the projection and the real endpoints.

The scene boundary and the world-fact input are table-owner inputs. Their
answers must be the journey projection every other journey route returns (no
replay genesis, no command journal), and the HTTP surface must reach them, so
a printed once-per-scene limit can refresh in play.
"""
import httpx
import pytest

from combat import ext
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t16_athletics_travel import game, scene, SOURCE, A, B

KIND = 'journey_light'


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


def test_http_end_scene_and_world_fact_endpoints(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi

    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
                        sheet([SOURCE] if pid == 'traveller' else [], cl=15, name=pid))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': scene()})
    app = create_app(Settings.from_env(ROOT, tmp_path))

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
