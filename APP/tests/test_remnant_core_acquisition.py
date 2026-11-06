"""Real causal Foundation installation/calculation followed by combat import.

Reuses pinned native creation helpers, not an installed successful receipt.
Dynamic compiler/rules inputs: authority/typed_mechanics/rules_text.json,
combat/rules/feature_blocks.d/remnant_core_reserve.json,
combat/rules/source_expressions/remnant_core_reserve.json,
non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json,
authority/typed_mechanics/reviewed_final.d/remnant_core_reserve.json.
"""
from copy import deepcopy
import json
import zipfile

from character_creation.path_attainment import native_path_progressions
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from projector.foundation_mechanics import project_initial_foundation_mechanics
from tests.test_creation_training_r4 import _real_creation_intent
from tests.test_initial_method_versions import _initial_method_events
from tests.test_rec1_p1cr5_owner_authority import _private_scope
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, candidate, reload, settle, turn

FID = 'ash_born_remnant_core_v0_2B'
CP = 'resource:core.qi'
SOURCE_INPUTS = (
    'APP/authority/typed_mechanics/rules_text.json',
    'APP/combat/rules/feature_blocks.d/remnant_core_reserve.json',
    'APP/combat/rules/source_expressions/remnant_core_reserve.json',
    'APP/authority/typed_mechanics/reviewed_final.d/remnant_core_reserve.json',
    'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
)


def test_native_install_maximum_is_exactly_pb_and_import_does_not_duplicate(catalog_environment, tmp_path):
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment)
    paths = ['tianxia.path.qi_cultivation']
    stage2, events, state = _initial_method_events(creator, project, run, intent, 'METHOD-001', paths)
    project_id = project['project_id']
    proposal = {'project_id': project_id, 'proposal_id': 'remnant-core-native',
                'expected_project_revision': project['revision'], 'idempotency_key': 'remnant-core-native',
                'created_at': '2026-09-07T00:00:00+00:00'}
    cache = {}
    with _private_scope(stage2, run['request'], run['run_id'], set(paths)), creator.db.connection() as conn:
        record = stage2._resolve_record_after_proof(conn, project_id, FID)
        stage2._assert_record_after_proof(conn, project_id, record)
        path = stage2._resolve_record_after_proof(conn, project_id, paths[0])
        for cl in range(2, 7):
            feature = path['compatibility']['factory']['stage2_authority']['progression_by_cl'][str(cl)]['feature_record_ids'][0]
            choices = [{'kind': 'level_advance', 'record_id': feature, 'effective_cl': cl,
                        'acquisition_channel': events[-1]['legal_channel'] if cl == 2 else channel,
                        'parameters': {'native_path_progressions': native_path_progressions([path], cl)}}]
            channel = choices[0]['acquisition_channel']
            if cl == 5:
                choices.append({'kind': 'foundation_acquisition', 'record_id': FID, 'effective_cl': cl,
                                'acquisition_channel': 'foundation-selection', 'parameters': {'stage': 'Integrated'}})
            for choice in choices:
                event, state, blockers = stage2._choice_event(conn=conn, row=proposal, project=project,
                    state=state, choice=choice, index=len(events), sequence=len(events) + 1,
                    previous_hash=events[-1]['event_hash'], generic_prefix=events, record_cache=cache)
                assert not blockers, (choice, blockers)
                assert event is not None
                events.append(event)
        pool = state['resources']['tianxia.resource.qi']
        assert pool['foundation_delta'] == 3
        again, _, _ = stage2._resource_recalculation(conn, project_id, state, cl=6, pb=3,
            path=path, current_resources={'tianxia.resource.qi': {**pool, 'current': 1}})
        assert again['tianxia.resource.qi']['maximum'] == pool['maximum']
        assert again['tianxia.resource.qi']['current'] == 1
        assert again['tianxia.resource.qi']['foundation_delta'] == 3
    replayed, _, _ = stage2._rows(events, project_id)
    assert replayed['resources'] == state['resources']
    projected = project_initial_foundation_mechanics(record, events,
        {event['event_id']: f"packet:initial:{index}" for index, event in enumerate(events)})
    assert projected['stage'] == 'Integrated'
    assert projected['resource']['current'] == 0
    doc = sheet([], cl=6)
    doc['identity']['proficiency_bonus'] = 3
    doc['foundation'] = projected
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = pool['maximum']
    first = compile_character(doc, actor_id=OWNER)
    assert first == compile_character(deepcopy(doc), actor_id=OWNER)
    resources = {row['resource_id']: row for row in first['actor_template']['resources']}
    assert resources[CP]['maximum'] == pool['maximum']
    assert resources['resource:foundation.remnant_cinder']['initial'] == 0
    # Commit a real action, then reconstruct through a fresh CombatService and
    # exact mechanical replay; rebuild/import must not add another PB or Cinder.
    # Install the real projected sheet as portable initial data, then use the
    # public importer/match constructor rather than injecting a combat bundle.
    for aid, document in ((OWNER, doc), (FOE, sheet([], cl=6))):
        directory = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        directory.mkdir(parents=True)
        with zipfile.ZipFile(directory / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat.create_factory_match(
        project_ids=[OWNER.removeprefix('actor:factory.')], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, match_seed='REMNANT-INSTALL')['match_id']
    assert combat._factory_owner_sheet(OWNER.removeprefix('actor:factory.'))['foundation'] == projected
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources == before.state.actors[OWNER].resources
    assert after.state.actors[OWNER].resource_maximums[CP] == pool['maximum']
