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
from tests.glass_refraction_support import declare


# create_app executes this real migration set. Declare the actual dependencies
# so the public exporter fails closed when its private-material ledger excludes
# them; never synthesize/copy a schema to hide an unavailable runtime input.
APP_MIGRATIONS = (
    'migrations/001_initial.sql',
    'migrations/002_runtime_contract_reconciliation.sql',
    'migrations/003_deterministic_projection.sql',
    'migrations/004_stage1_clipboard_bridge.sql',
    'migrations/005_stage1_blueprint_intent.sql',
    'migrations/006_project_scoped_foundation_replacements.sql',
    'migrations/007_content_pack_trust_receipts.sql',
    'migrations/008_content_pack_lifecycle_events.sql',
    'migrations/009_retained_content_pack_lifecycle_audit.sql',
    'migrations/010_optional_ai_provider.sql',
    'migrations/011_api_provider_selection.sql',
    'migrations/011_stage2_advancement_ledger.sql',
    'migrations/012_phase4a_hf1_rules_causality.sql',
    'migrations/013_phase4a_hf2_trust_boundary.sql',
    'migrations/014_phase4a_hf2_recovery_r2.sql',
    'migrations/015_phase4a_hf2_recovery_r3.sql',
    'migrations/016_phase4a_hf2_recovery_r4.sql',
    'migrations/017_phase4a_hf2_r5_clock_authority.sql',
    'migrations/018_character_builder_ephemeral_lifecycle.sql',
    'migrations/019_ns1r_non_sphere_authority.sql',
    'migrations/020_ns1r_r2_bound_evidence.sql',
    'migrations/021_cg1_character_creation_runs.sql',
    'migrations/022_cg1_owner_workflow.sql',
    'migrations/023_cg1_delegated_choice_authority.sql',
    'migrations/024_rec1_p1cr2_workflow_recovery.sql',
    'migrations/025_rec1_p1cr3_attempt_history.sql',
    'migrations/026_rec1_p1cr4_recovery_retention.sql',
    'migrations/027_rec1_p1cr5_local_provider_correction.sql',
    'migrations/028_rec1_p1cr5_recovery_chooser_index.sql',
    'migrations/029_dcc_run_route_and_events.sql',
    'migrations/030_project_locked_records_by_reference.sql',
    'migrations/031_dcc_walk_state.sql',
    'migrations/032_project_permanent_deletion.sql',
    'migrations/033_project_deletion_requests.sql',
    'migrations/034_project_deletion_recovery.sql',
    'migrations/034_project_library_summary.sql',
    'migrations/035_library_source_revision.sql',
)


def test_http_authorization_and_durable_owner_choice(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    root = Path(__file__).resolve().parents[1]
    missing = [path for path in APP_MIGRATIONS if not (root / path).is_file()]
    if missing:
        pytest.skip('public export omits app migrations: ' + ', '.join(missing))
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    app = create_app(Settings.from_env(root, tmp_path))
    app.state.agent_seats.background = False

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            url = f'/api/tabletop/matches/{mid}/source-inputs'
            form = (await client.get(url)).json()
            payload = {'source_id': SOURCE, 'actor_id': OWNER, 'expected_state_version': form['state_version'],
                       'values': {'scene': 'Major combat',
                                  'reason': 'The accused speaks the truth in the decisive tribunal.'}}
            assert (await client.post(url, json=payload)).status_code == 403
            token = (await client.get('/api/session')).json()['token']
            result = await client.post(url, json=payload, headers={'x-foundry-token': token})
            assert result.status_code == 200, result.text
            # A committed declaration moves the fight on. The stale replay is
            # refused with its own code, so a form can re-read the current
            # bearer/turn and let the owner confirm again instead of looping.
            stale = await client.post(url, json=payload, headers={'x-foundry-token': token})
            assert stale.status_code == 409, stale.text
            assert stale.json()['error']['code'] == 'TABLETOP_STALE'
            fresh = (await client.get(url)).json()
            assert fresh['state_version'] != form['state_version']
            recovered = await client.post(url, json={**payload, 'expected_state_version': fresh['state_version']},
                                          headers={'x-foundry-token': token})
            assert recovered.status_code == 200, recovered.text
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
