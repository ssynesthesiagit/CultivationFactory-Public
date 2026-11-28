"""F10R review pins: owner guard on the owner-only facts route.

Blocking 1: POST /api/tabletop/matches/{match_id}/facts had no test for refusal. TabletopService.record_fact is owner/GM
only, so an unauthenticated, wrong-token, or foreign-origin request must be refused before any fact is recorded.
Blocking 2: the guard is the app-wide mutation middleware in app/api.py (loopback_security). The test proves the facts route
and the feature route answer through that same guard (same CSRF_TOKEN_REQUIRED code) and that nothing is written on refusal.

In-process ASGI only: no socket, model server, browser or GUI.
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
    fact_document, advance, cold)


def test_owner_facts_route_refuses_unauthenticated_and_foreign_requests(tmp_path):
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
            feature_url = f'/api/tabletop/characters/{PROJECT}/features'
            acquired = await client.post(feature_url, headers=headers, json={'feature_id': READ, 'source': ACCESS})
            assert acquired.status_code == 200, acquired.text
            owner = s._factory_owner_sheet(PROJECT)
            docs = [owner, sheet([MIND_SPIKE], cl=6), sheet([], cl=6)]
            bundles = [compile_character(doc, actor_id=actor, reaction_plan={'ask': True})
                       for actor, doc in zip((ME, FOE, ALLY), docs)]
            mid = s._finish_factory_match(bundles, [ME, FOE, ALLY],
                {ME: 'team:a', FOE: 'team:b', ALLY: 'team:a'},
                {ME: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 7}},
                s.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME, ALLY], [FOE],
                control_modes={actor: 'MANUAL' for actor in (ME, FOE, ALLY)},
                match_seed='HTTP-FACTS-GUARD', display_name='Guard branch', maximum_rounds=20)['match_id']
            advance(s, t, mid, ME)
            doc = fact_document(s, mid)
            before = cold(tmp_path, mid)
            version = before.state.state_version
            facts_before = [e for e in before.events if e.event_type == 'TABLE_FACT_RECORDED']
            url = f'/api/tabletop/matches/{mid}/facts'
            body = {'document': doc, 'expected_state_version': version}

            # Unauthenticated: no token at all.
            anon = await client.post(url, json=body)
            assert anon.status_code == 403, anon.text
            assert anon.json()['error']['code'] == 'CSRF_TOKEN_REQUIRED'

            # Wrong token (an old or forged session token).
            forged = await client.post(url, headers={'x-foundry-token': 'not-the-session-token'}, json=body)
            assert forged.status_code == 403, forged.text
            assert forged.json()['error']['code'] == 'CSRF_TOKEN_REQUIRED'

            # Foreign origin with a valid token is still refused.
            foreign = await client.post(url, headers={**headers, 'origin': 'https://evil.example'}, json=body)
            assert foreign.status_code == 403, foreign.text
            assert foreign.json()['error']['code'] == 'ORIGIN_REJECTED'

            # Same guard as the feature route: identical refusal code for an unauthenticated feature POST.
            feature_anon = await client.post(feature_url, json={'feature_id': READ, 'source': ACCESS})
            assert feature_anon.status_code == 403
            assert feature_anon.json()['error']['code'] == 'CSRF_TOKEN_REQUIRED'

            # Nothing was recorded by any refused request.
            after = cold(tmp_path, mid)
            assert after.state.state_version == version
            facts_after = [e for e in after.events if e.event_type == 'TABLE_FACT_RECORDED']
            assert len(facts_after) == len(facts_before)

            # The owner session still records it.
            recorded = await client.post(url, headers=headers, json=body)
            assert recorded.status_code == 200, recorded.text
            return mid

    mid = run_asgi(exercise())
    assert package.is_file()
    assert len([e for e in cold(tmp_path, mid).events if e.event_type == 'TABLE_FACT_RECORDED']) == 1
