"""HTTP native commits retain desktop drafts until their deferred menu arrives.

No sockets or model servers: real ASGI routes feed the production desktop
controller/render/refresh path; the subsequent menu read is explicitly delayed.
"""
import httpx
import pytest

from app.api import create_app
from app.core import Settings
from combat import hold_position, posture
from combat.ext import blossom
from tests import test_a2_flowers as flowers
from tests.async_support import run_asgi
from tests.h1_support import ROOT
from tests.hunt12_support import ME, STAMINA, event_hook, reload
from tests.test_optionspeed1_f4_review import controller, request, selection


@pytest.mark.parametrize('native_source', [posture.SOURCE, hold_position.SOURCE])
def test_http_native_deferred_menu_preserves_draft_and_fresh_preview(tmp_path, monkeypatch, native_source):
    monkeypatch.setenv('CF_EMBED_MENU', '0')

    def prone_at_start(engine, event, data):
        if event == 'TURN_STARTED' and data.get('actor_id') == ME:
            engine._apply_condition(engine.state.actors[ME], 'condition:typed.prone',
                                    'test:deferred-prone', ME, expires_on='UNTIL_REMOVED')

    event_hook(monkeypatch, prone_at_start)
    combat, table, mid = flowers.scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM', blossom.SEED])
    state = table.state(mid)
    cid, spec = selection(state, 'blossom.pick.seed')
    native = next(g for g in state['menu']['actions'] if g['source_definition_id'] == native_source)
    native_payload = dict(candidate_id=native['options'][0]['candidate_id'],
                          decision_id=state['menu']['decision_id'], state_version=state['menu']['state_version'],
                          after=state['last_sequence'], reactions=[])
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False

    async def exchange():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            base = f'/api/tabletop/matches/{mid}'
            response = await client.post(f'{base}/act', headers=headers, json=native_payload)
            assert response.status_code == 200, response.text
            committed = response.json()
            assert committed['status'] == 'COMMITTED'
            assert committed['state']['menu'] is None
            assert committed['state']['menu_pending']
            response = await client.get(f'{base}/state')
            assert response.status_code == 200, response.text
            after = response.json()
            assert after['menu']['state_version'] > state['menu']['state_version']
            source = next(g['source_definition_id'] for g in after['menu']['actions']
                          if g['source_definition_id'].endswith('blossom.cultivate_bloom'))
            payload = request(after, source, spec['source'])
            response = await client.post(f'{base}/composition/preview', headers=headers, json=payload)
            assert response.status_code == 200, response.text
            preview = response.json()
            submitted = controller(dict(case='deferred-native', state=state, after=after,
                                        committed=committed, setting=cid, source=source,
                                        native=native_source, preview=preview))
            assert submitted['nativePayload'] == native_payload
            assert submitted['previewPayload'] == payload
            # Commit the exact fresh draft whose desktop preview was just checked.
            position = next(a['position'] for a in after['presentation']['actors'] if a['entity_id'] == ME)
            option = next(o for g in preview['menu']['actions'] for o in g['options']
                          if (o.get('destination') or (o.get('area') or {}).get('center')) == position)
            response = await client.post(f'{base}/act', headers=headers, json={
                'candidate_id': option['candidate_id'], 'composition': submitted['previewPayload'],
                'decision_id': preview['menu']['decision_id'], 'state_version': preview['menu']['state_version'],
                'after': after['last_sequence'], 'reactions': [],
            })
            assert response.status_code == 200, response.text
            assert response.json()['status'] == 'COMMITTED'

    before_cp = combat._load_session(mid).engine.state.actors[ME].resources[STAMINA]
    run_asgi(exchange())
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[ME]
    config = next(c.data for c in actor.conditions.values() if c.condition_id == blossom.SETUP)
    assert config['bloom'] == 'seed'
    assert actor.resources[STAMINA] == before_cp - 3
    if native_source == posture.SOURCE:
        assert not posture.prone_conditions(actor)
    else:
        assert hold_position.used(actor)
