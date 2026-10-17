"""Source calculator and imported-sheet table regressions for Oath-Skin Frame.

The imported fixture is source-bound but is not a complete creator release.
The separate causal test proves native acquisition; do not mistake the fixture
for end-to-end acquisition/materializer acceptance.
"""
from copy import deepcopy
import hashlib
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext import oath_skin_frame as frame
from combat.factory_compiler import compile_character
from combat import table_advance
from app.core import FoundryError
from combat.tabletop import TabletopError
from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics,
    resolve_foundation_stage_mechanics, verified_foundation_records,
)
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, turn, candidate, settle, sealed_native_attack

PATHS = ['tianxia.path.body_refining']


def source_sheet(identity=frame.FOUNDATION):
    source = verified_foundation_records()[identity]
    mechanics = resolve_initial_foundation_mechanics(source, PATHS)
    event_id = 'import:' + canonical_sha256(mechanics)
    foundation = installed_foundation_state(mechanics, identity, event_id)
    foundation.update(mechanical_projection=True, acquisition_event_id=event_id,
                      mechanics=mechanics, source_packet_ids=['import:' + canonical_sha256(source)])
    document = sheet([], cl=15, name='Oath bearer')
    document['foundation'] = foundation
    hp = document['ability_scores_and_statistics']['hit_points']
    hp['maximum'] += frame.hp_value(mechanics, document['identity']['proficiency_bonus'])
    return document


def table_fixture(tmp_path, document=None, *, twins=False, seed='OATH-FRAME-SOURCE'):
    document = document or source_sheet()
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    def hostile_attack(bundles):
        if twins:
            bundles[1] = compile_character(document, actor_id=ALLY)
        sealed_native_attack(bundles[2], 'Hostile blow', count=1, sides=4, modifier=12,
                             attack_bonus=50, range_ft=5)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle,
        foe_position={'x': 3, 'y': 5}, seed=seed, bundle_transform=hostile_attack)
    # The real portable-sheet reader, rather than a test-only overlay reader,
    # supplies future table builds after durable source-event delivery.
    with zipfile.ZipFile(tmp_path / 'portable_characters' / OWNER.removeprefix('actor:factory.') / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    return document, combat, table, mid


def evidence(kind):
    rows = []
    if kind == 'integrated':
        for index, name in enumerate(('protect_without_controlling', 'accept_protection', 'clarify_oath')):
            rows.append({'kind': name, 'source_reference': f'campaign:guardian-trial/scene-{index + 1}',
                         'description': f'The GM records the completed {name.replace("_", " ")} stabilization.'})
    return {'source_reference': 'campaign:guardian-trial/source-effect',
            'story_effect': 'The GM records the actual Foundation ' + kind.replace('_', ' ') + ' story effect.',
            'stabilizations': rows}


def record(table, mid, kind, *, acquisition=None, actor=OWNER, evidence_document=None, event_id=None):
    engine = table.combat._load_session(mid).engine
    row = frame.owned_row(engine, OWNER)
    return table.record_source_event(mid, {
        'event_id': event_id or f'{mid}:{kind}:{engine.state.state_version}',
        'actor_id': actor, 'source_id': frame.FRAME,
        'acquisition_id': acquisition or row['acquisition_id'], 'kind': kind,
        'data': {'source_sha256': frame.HASH}}, evidence_document or evidence(kind), engine.state.state_version)


def test_imported_frame_contribution_is_recomputed_from_authenticated_mechanics():
    document = source_sheet()
    hp = document['ability_scores_and_statistics']['hit_points']
    expected = frame.hp_value(document['foundation']['mechanics'], document['identity']['proficiency_bonus'])
    hp['source_contributions'][frame.FRAME] = 999
    bundle = compile_character(document, actor_id=OWNER)
    row = next(row for row in bundle['typed_passives'] if row.get('block') == frame.BLOCK)
    assert row['amount'] == expected


@pytest.mark.parametrize('stage,multiple', [('Latent', 0), ('Common Expression', 1),
    ('Awakened', 1), ('Integrated', 2), ('Refined', 2), ('Perfected', 2)])
def test_printed_stage_formula_is_cumulative(stage, multiple):
    source = verified_foundation_records()[frame.FOUNDATION]
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[frame.FRAME]
    assert hashlib.sha256(text.encode()).hexdigest() == frame.HASH
    mechanics = resolve_foundation_stage_mechanics(source, PATHS, stage=stage)
    assert frame.hp_value(mechanics, 4) == multiple * 4
    # A calculator accepting attained stages never authorizes initial acquisition.
    if stage != 'Awakened':
        with pytest.raises(FoundryError):
            resolve_initial_foundation_mechanics(source, PATHS, stage=stage)


@pytest.mark.parametrize('kind', ['fully_severed', 'replaced'])
def test_native_committed_severance_clamps_without_healing_and_cold_replays(tmp_path, kind):
    document, combat, table, mid = table_fixture(tmp_path)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Hostile blow', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    before = engine.state.actors[OWNER]
    maximum, current = before.maximum_hp, before.current_hp
    assert 0 < current < maximum - document['identity']['proficiency_bonus']
    amount = frame.owned_row(engine, OWNER)['amount']
    assert amount == document['identity']['proficiency_bonus']
    record(table, mid, kind)
    after = reload(tmp_path, mid).state.actors[OWNER]
    assert after.maximum_hp == maximum - amount
    assert after.current_hp == min(current, after.maximum_hp)
    assert after.action_available == before.action_available
    table.synchronize_source_events(mid)
    table.synchronize_source_events(mid)
    saved = table.buttons.get(OWNER.removeprefix('actor:factory.'))['advancement']
    assert len(saved['source_events']) == 1
    updated = combat._factory_owner_sheet(OWNER.removeprefix('actor:factory.'))
    assert updated['ability_scores_and_statistics']['hit_points']['maximum'] == maximum - amount
    assert table_advance.apply(updated, saved) == updated
    # A stale acquisition cannot change a later acquisition of the same source.
    replacement = deepcopy(document)
    replacement['foundation']['event_id'] = replacement['foundation']['acquisition_event_id'] = 'new-acquisition'
    assert table_advance.apply(replacement, saved) == replacement
    with pytest.raises(TabletopError, match='fully severed'):
        record(table, mid, 'available')
    assert combat.verify(mid)['status'] == 'PASS'
    assert combat.replay(mid)['status'] == 'PASS'
    journal = json.dumps([e.model_dump(mode='json') for e in reload(tmp_path, mid).events])
    assert 'guardian-trial' not in journal
    assert list((tmp_path / 'source_event_evidence').glob('*.json'))


def test_native_integration_and_suppression_change_future_sheet_not_running_scene(tmp_path):
    document, combat, table, mid = table_fixture(tmp_path)
    maximum = reload(tmp_path, mid).state.actors[OWNER].maximum_hp
    record(table, mid, 'integrated')
    record(table, mid, 'suppressed')
    record(table, mid, 'ordinary_dispel')
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == maximum
    saved = table.buttons.get(OWNER.removeprefix('actor:factory.'))['advancement']
    unavailable = combat._factory_owner_sheet(OWNER.removeprefix('actor:factory.'))
    pb = document['identity']['proficiency_bonus']
    assert unavailable['foundation']['stage'] == 'Integrated'
    assert unavailable['ability_scores_and_statistics']['hit_points']['maximum'] == maximum - pb
    _, _, _, unavailable_mid = table_fixture(tmp_path / 'unavailable', unavailable)
    assert reload(tmp_path / 'unavailable', unavailable_mid).state.actors[OWNER].maximum_hp == maximum - pb
    record(table, mid, 'available')
    saved = table.buttons.get(OWNER.removeprefix('actor:factory.'))['advancement']
    integrated = combat._factory_owner_sheet(OWNER.removeprefix('actor:factory.'))
    assert integrated['ability_scores_and_statistics']['hit_points']['maximum'] == maximum + pb
    assert table_advance.apply(integrated, saved) == integrated
    for _ in range(3):
        bundle = compile_character(integrated, actor_id=OWNER)
        assert bundle['actor_template']['maximum_hp'] == maximum + pb
    _, _, _, integrated_mid = table_fixture(tmp_path / 'integrated', integrated)
    assert reload(tmp_path / 'integrated', integrated_mid).state.actors[OWNER].maximum_hp == maximum + pb
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == maximum
    # Full severance removes the frozen scene contribution, not its deferred rider.
    record(table, mid, 'fully_severed')
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == maximum - pb
    assert combat.verify(mid)['status'] == 'PASS'
    assert combat.replay(mid)['status'] == 'PASS'


def test_source_events_require_owned_acquisition_and_actual_private_route(tmp_path):
    _, _, table, mid = table_fixture(tmp_path)
    with pytest.raises(TabletopError, match='current acquired'):
        record(table, mid, 'fully_severed', acquisition='old-acquisition')
    with pytest.raises(TabletopError, match='current acquired'):
        record(table, mid, 'fully_severed', actor=FOE)
    bad = evidence('integrated')
    bad['stabilizations'] = []
    with pytest.raises(TabletopError, match='three completed'):
        record(table, mid, 'integrated', evidence_document=bad)
    assert not list((tmp_path / 'source_event_evidence').glob('*.json'))
    record(table, mid, 'suppressed')
    with pytest.raises(TabletopError, match='not fully suppressed'):
        record(table, mid, 'integrated')


def test_frame_reader_does_not_withdraw_another_passive_hp_bonus():
    source = verified_foundation_records()[frame.FOUNDATION]
    mechanics = resolve_initial_foundation_mechanics(source, PATHS)
    extra = deepcopy(mechanics['hp_maximum_modifiers'][0])
    extra['feature_name'] = 'Another passive'
    mechanics['hp_maximum_modifiers'].append(extra)
    assert frame.hp_value(mechanics, 4) == 4


def test_scene_story_events_do_not_cross_between_two_imported_bearers(tmp_path):
    _, _, table, mid = table_fixture(tmp_path, twins=True)
    engine = reload(tmp_path, mid)
    hp = engine.state.actors[OWNER].maximum_hp
    record(table, mid, 'fully_severed', actor=ALLY)
    record(table, mid, 'integrated')
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].maximum_hp == hp
    assert after.state.actors[ALLY].maximum_hp == hp - 4


def test_wrong_installed_foundation_cannot_receive_frame_events(tmp_path):
    document, _, table, mid = table_fixture(tmp_path, source_sheet('heaven_tyrant_body_v0_2D'))
    assert frame.owned_row(reload(tmp_path, mid), OWNER) is None
    with pytest.raises(TabletopError, match='current acquired'):
        record(table, mid, 'fully_severed', acquisition=document['foundation']['acquisition_event_id'])


def test_native_acquisition_causal_calculator_adds_one_pb_not_one_per_level(catalog_environment, tmp_path):
    from character_creation.path_attainment import native_path_progressions
    from tests.test_creation_training_r4 import _real_creation_intent
    from tests.test_initial_method_versions import _initial_method_events
    from tests.test_rec1_p1cr5_owner_authority import _private_scope
    from projector.foundation_mechanics import validate_initial_foundation_mechanics
    from projector.foundation_mechanics import project_initial_foundation_mechanics
    from projector.v3_bridge import _packet_id
    creator, project, run, selection, _ = _real_creation_intent(catalog_environment)
    stage2, events, state = _initial_method_events(creator, project, run, selection, 'METHOD-083', PATHS)
    proposal = {'project_id': project['project_id'], 'proposal_id': 'frame-native-acquisition',
                'expected_project_revision': project['revision'], 'idempotency_key': 'frame-native-acquisition',
                'created_at': '2026-10-15T00:00:00+00:00'}
    with _private_scope(stage2, run['request'], run['run_id'], set(PATHS)), creator.db.connection() as conn:
        path = stage2._resolve_record_after_proof(conn, project['project_id'], PATHS[0])
        record = stage2._resolve_record_after_proof(conn, project['project_id'], frame.FOUNDATION)
        cache = {}
        for cl in range(2, 10):
            feature = path['compatibility']['factory']['stage2_authority']['progression_by_cl'][str(cl)]['feature_record_ids'][0]
            choices = [{'kind': 'level_advance', 'record_id': feature, 'effective_cl': cl,
                        'acquisition_channel': events[-1]['legal_channel'] if cl == 2 else channel,
                        'parameters': {'native_path_progressions': native_path_progressions([path], cl)}}]
            channel = choices[0]['acquisition_channel']
            if cl == 5:
                choices.append({'kind': 'foundation_acquisition', 'record_id': frame.FOUNDATION,
                                'effective_cl': 5, 'acquisition_channel': 'foundation-selection',
                                'parameters': {'stage': 'Awakened'}})
            for choice in choices:
                event, state, blockers = stage2._choice_event(conn=conn, row=proposal, project=project,
                    state=state, choice=choice, index=len(events), sequence=len(events)+1,
                    previous_hash=events[-1]['event_hash'], generic_prefix=events, record_cache=cache)
                assert not blockers, blockers
                events.append(event)
    assert state['hp']['foundation_delta'] == 4
    gains = sum(e['advancement']['calculation']['outputs']['hp_after']['last_gain']
                for e in events if e['advancement']['kind'] == 'level_advance')
    assert state['hp']['total'] == gains + 4
    for _ in range(3):
        projected = validate_initial_foundation_mechanics(record, events)
        assert projected['stage'] == 'Awakened'
        replayed, _, _ = stage2._rows(events, project['project_id'])
        assert replayed['hp'] == state['hp']
    # Use the production projection and packet identity, not a hand-installed
    # mechanical success flag. The HP total comes from the causal calculator.
    document = sheet([], cl=9, name='Native acquired Oath bearer')
    document['foundation'] = project_initial_foundation_mechanics(record, events,
        {event['event_id']: _packet_id(event) for event in events})
    document['ability_scores_and_statistics']['hit_points']['maximum'] = state['hp']['total']
    document['identity']['proficiency_bonus'] = 4
    _, combat, table, mid = table_fixture(tmp_path / 'native-import', document)
    assert reload(tmp_path / 'native-import', mid).state.actors[OWNER].maximum_hp == state['hp']['total']
    record_event = {'event_id': 'native-acquired-integration', 'actor_id': OWNER,
        'source_id': frame.FRAME, 'acquisition_id': document['foundation']['acquisition_event_id'],
        'kind': 'integrated', 'data': {'source_sha256': frame.HASH}}
    table.record_source_event(mid, record_event, evidence('integrated'),
                             reload(tmp_path / 'native-import', mid).state.state_version)
    updated = combat._factory_owner_sheet(OWNER.removeprefix('actor:factory.'))
    assert updated['ability_scores_and_statistics']['hit_points']['maximum'] == state['hp']['total'] + 4
    assert reload(tmp_path / 'native-import', mid).state.actors[OWNER].maximum_hp == state['hp']['total']
    assert combat.replay(mid)['status'] == 'PASS'


def test_source_event_http_requires_real_owner_session_and_keeps_evidence_private(tmp_path):
    import httpx
    from app.api import create_app
    from app.core import Settings
    from tests.async_support import run_asgi
    _, combat, _, mid = table_fixture(tmp_path)
    engine = combat._load_session(mid).engine
    request = {'state_version': engine.state.state_version,
        'document': {'event_id': 'http-story-severance', 'actor_id': OWNER, 'source_id': frame.FRAME,
                     'acquisition_id': frame.owned_row(engine, OWNER)['acquisition_id'],
                     'kind': 'fully_severed', 'data': {'source_sha256': frame.HASH}},
        'evidence': evidence('fully_severed')}
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            path = f'/api/tabletop/matches/{mid}/source-events'
            refused = await client.post(path, json=request)
            assert refused.status_code == 403
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            committed = await client.post(path, json=request, headers=headers)
            assert committed.status_code == 200, committed.text
            assert 'guardian-trial' not in committed.text
            duplicate = await client.post(path, json=request, headers=headers)
            assert duplicate.status_code == 422
            synced = await client.post(path + '/synchronize', headers=headers)
            assert synced.status_code == 200, synced.text
    run_asgi(run())
    files = list((tmp_path / 'source_event_evidence').glob('*.json'))
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == 60
