"""Authenticated HTTP declarations and actual journey/rest/encounter carry.

This deliberately does not claim source-acquired Perfected advancement.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.foundation_combat import held, pool
from combat.ext.glass_heart_refraction import SOURCE
from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_state, verified_foundation_records
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, settle, turn
from tests.test_a2_foundations_two import table_fixture
from tests.test_mgr_t15_glass_refraction import declare


def test_http_authorization_and_durable_owner_choice(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    app = create_app(Settings.from_env(Path(__file__).resolve().parents[1], tmp_path))
    app.state.agent_seats.background = False

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            url = f'/api/tabletop/matches/{mid}/source-inputs'
            form = (await client.get(url)).json()
            payload = {'source_id': SOURCE, 'actor_id': OWNER, 'expected_state_version': form['state_version'],
                       'values': {'scene': 'Major combat', 'clarity': 'Yes',
                                  'reason': 'The accused speaks the truth in the decisive tribunal.'}}
            assert (await client.post(url, json=payload)).status_code == 403
            token = (await client.get('/api/session')).json()['token']
            result = await client.post(url, json=payload, headers={'x-foundry-token': token})
            assert result.status_code == 200, result.text
            assert (await client.post(url, json=payload, headers={'x-foundry-token': token})).status_code == 422
    run_asgi(exercise())
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'TABLE_FACT_RECORDED' for e in engine.events)
    assert any(SOURCE in c.source_definition_id for c in engine.legal_candidates())


def test_actual_recipient_long_rest_resets_carried_use(tmp_path):
    root = Path(__file__).resolve().parents[1]
    doc = sheet([], cl=15)
    initial = resolve_initial_foundation_state(verified_foundation_records()['glass_heart_meridian_v0_2A'],
        ['tianxia.path.qi_cultivation'], stage='Awakened')
    doc['foundation'] = {**initial, 'stage': 'Perfected'}
    docs = [doc, sheet([], cl=15), sheet([], cl=15)]
    ids = [OWNER, ALLY, FOE]
    for d, aid in zip(docs, ids):
        package = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.') / 'current.zip'
        package.parent.mkdir(parents=True)
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(d))
    bundles = [compile_character(d, actor_id=aid, reaction_plan={'ask': True}) for d, aid in zip(docs, ids)]
    combat = CombatService(root, tmp_path)
    table = TabletopService(combat, tmp_path)
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}}
    teams = {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    state = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        positions, {aid: 1000 for aid in ids}, {aid: 'MANUAL' for aid in ids})
    jid = state['journey_id']
    mid = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=12)['match_id']
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if (a.parameters.get('typed') or {}).get('source') == SOURCE)
    use_id = next(rid for rid, _ in action.costs if rid.startswith('resource:uses.'))
    declare(combat, table, mid)
    settle(table, mid, candidate(combat, mid, 'Perfected — Glass Heart Refraction').candidate_id)
    for _ in range(45):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    else:
        pytest.fail('The twelve-round encounter did not reach its terminal result.')
    engine = reload(tmp_path, mid)
    assert not held(engine.state.actors[OWNER], 'glass_refraction')
    assert engine.state.actors[OWNER].resources[use_id] == 0
    state = combat.journey_state(jid)
    combat.journey_resume(jid, state['revision'])
    state = combat.journey_state(jid)
    cp = state['actors'][OWNER]['resources']['resource:core.qi']
    seconds = state['seconds']
    combat.journey_act(jid, state['revision'], ALLY, 'long_rest', {})
    state = combat.journey_state(jid)
    assert state['actors'][OWNER]['resources'][use_id] == 0
    combat.journey_act(jid, state['revision'], OWNER, 'long_rest', {})
    state = combat.journey_state(jid)
    assert state['seconds'] - seconds == 57600
    assert state['actors'][OWNER]['resources'][use_id] == 1
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == cp
    assert state['actors'][OWNER]['resources'][pool('glass')] == 0
    mid = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=12)['match_id']
    turn(table, mid, OWNER)
    declare(combat, table, mid, scene='Emotionally decisive scene')
    settle(table, mid, candidate(combat, mid, 'Perfected — Glass Heart Refraction').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert held(owner, 'glass_refraction')
    assert owner.resources[use_id] == 0
    assert owner.resources['resource:core.qi'] == cp - 2
