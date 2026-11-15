"""Real installed-sheet HTTP acquisition -> compile -> table -> cold replay.

In-process ASGI only: no network socket, model server, browser or GUI.
"""
import json
import zipfile

import httpx

from app.api import create_app
from app.core import Settings
from combat.factory_compiler import compile_character
from tests.async_support import run_asgi
from tests.test_riders_c8 import sheet, MIND_SPIKE
from tests.test_seamfix_trad_fate_read_thread import (
    ROOT, PROJECT, ME, FOE, ALLY, PATH, ACCESS, READ,
    fact_document, advance, use, cold)


def test_owner_http_acquisition_and_observation_reach_native_answer(tmp_path):
    original = sheet([], cl=6)
    original['path_and_subpath']['path_record_ids'] = [PATH]
    package = tmp_path / 'portable_characters' / PROJECT / 'current.zip'
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(original))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    s = app.state.combat
    t = app.state.agent_seats.table

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            url = f'/api/tabletop/characters/{PROJECT}/features'
            request = {'feature_id': READ, 'source': ACCESS}
            denied = await client.post(url, json=request)
            assert denied.status_code in (401, 403)
            invalid = await client.post(url, headers=headers,
                json={**request, 'source': {**ACCESS, 'classification': 'Ordinary'}})
            assert invalid.status_code == 422
            acquired = await client.post(url, headers=headers, json=request)
            assert acquired.status_code == 200, acquired.text
            owner = s._factory_owner_sheet(PROJECT)
            assert owner['feature_access'][READ] == ACCESS
            assert not owner.get('spheres_and_talents', {}).get('sphere_record_ids')
            docs = [owner, sheet([MIND_SPIKE], cl=6), sheet([], cl=6)]
            bundles = [compile_character(doc, actor_id=actor, reaction_plan={'ask': True})
                       for actor, doc in zip((ME, FOE, ALLY), docs)]
            mid = s._finish_factory_match(bundles, [ME, FOE, ALLY],
                {ME: 'team:a', FOE: 'team:b', ALLY: 'team:a'},
                {ME: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 7}},
                s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME, ALLY], [FOE],
                control_modes={actor: 'MANUAL' for actor in (ME, FOE, ALLY)},
                match_seed='HTTP-THREAD', display_name='Recorded branch', maximum_rounds=20)['match_id']
            advance(s, t, mid, ME)
            doc = fact_document(s, mid)
            version = cold(tmp_path, mid).state.state_version
            url = f'/api/tabletop/matches/{mid}/facts'
            bad = await client.post(url, headers=headers,
                json={'document': {**doc, 'horizon': 'distant future'}, 'expected_state_version': version})
            assert bad.status_code == 422
            recorded = await client.post(url, headers=headers,
                json={'document': doc, 'expected_state_version': version})
            assert recorded.status_code == 200, recorded.text
            stale = await client.post(url, headers=headers,
                json={'document': doc, 'expected_state_version': version})
            assert stale.status_code == 409
            use(s, t, mid, 'Read the Thread', picks=('danger',))
            e = cold(tmp_path, mid)
            assert any(ev.event_type == 'OBSERVATION_ANSWERED' and ev.payload['success'] for ev in e.events)
            assert any('exposed approach' in row.get('summary', '').lower() for row in t.events(mid, 0)['events'])
            return mid

    mid = run_asgi(exercise())
    assert package.is_file()
    assert cold(tmp_path, mid).state.actors[ME].resources['resource:core.resonance'] == 57
