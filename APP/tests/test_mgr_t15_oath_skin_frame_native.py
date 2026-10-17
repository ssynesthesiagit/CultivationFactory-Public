"""Causal native-acquisition calculator path for Oath-Skin Frame.

Kept separate from the public-runnable regressions because it reaches private
creation-authority fixtures. It proves the calculator, not a fixture overlay.
"""
import pytest

from combat.ext import oath_skin_frame as frame
from tests.h1_support import sheet
from tests.worker2_support import reload
from tests.test_mgr_t15_oath_skin_frame import OWNER, _hex_owner  # noqa: F401  (hex owner for source-event routing)
from tests.test_mgr_t15_oath_skin_frame import PATHS, evidence, record, table_fixture


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
