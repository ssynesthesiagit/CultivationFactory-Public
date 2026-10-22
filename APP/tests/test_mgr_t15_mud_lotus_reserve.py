"""Mud Lotus Reserve: native source acquisition and causal CP accounting.

The causal cases request the real versioned Stage2 acquisition producer. The
relation cases separately reuse an existing classified-pressure fixture. Neither
is a substitute for complete creation-to-table/source-classification acceptance.
"""
import hashlib
import json

import pytest

from character_creation.path_attainment import native_path_progressions
from non_sphere_authority.foundation_mechanics import (
    FOUNDATION_MECHANICS_PACK_VERSION, installed_foundation_state,
)
from projector.foundation_mechanics import validate_initial_foundation_mechanics
from tests.h1_support import ROOT
from tests.test_creation_training_r4 import _real_creation_intent
from tests.test_initial_method_versions import _initial_method_events
from tests.test_rec1_p1cr5_owner_authority import _private_scope


IDENTITY = 'mud_lotus_dantian_v0_2A'
SOURCE = 'foundation.' + IDENTITY + '.mud_lotus_reserve'
DIGEST = 'a40624d6fbcfd45eff7769250b7dd82155b2faa5077d9640561f81208a7e35de'


def test_exact_complete_printed_reserve_source():
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(texts[SOURCE].encode()).hexdigest() == DIGEST


@pytest.mark.parametrize('target_cl', [5, 9])
def test_native_installation_adds_exactly_pb_cp_and_replays_without_duplication(
        catalog_environment, target_cl):
    creator, project, run, intent, _ = _real_creation_intent(
        catalog_environment, target_cl=target_cl)
    offered = run['request']['delegated_choice_envelope']['allowed_choice_ids_by_slot']
    assert IDENTITY in offered.get('foundation_choice', ()), 'The native request must offer this exact Foundation.'
    paths = ['tianxia.path.qi_cultivation']
    stage2, events, state = _initial_method_events(
        creator, project, run, intent, 'METHOD-001', paths)
    proposal = {
        'project_id': project['project_id'], 'proposal_id': 'mud-lotus-reserve-causal',
        'expected_project_revision': project['revision'], 'idempotency_key': 'mud-lotus-reserve',
        'created_at': '2026-10-15T00:00:00+00:00',
    }
    cache = {}
    with _private_scope(stage2, run['request'], run['run_id'], set(paths)), creator.db.connection() as conn:
        record = stage2._resolve_record_after_proof(conn, project['project_id'], IDENTITY)
        assert record['content_binding']['pack_version'] == FOUNDATION_MECHANICS_PACK_VERSION
        stage2._assert_record_after_proof(conn, project['project_id'], record)
        path_records = [stage2._resolve_record_after_proof(conn, project['project_id'], paths[0])]
        for cl in range(2, target_cl + 1):
            entries = native_path_progressions(path_records, cl)
            feature = path_records[0]['compatibility']['factory']['stage2_authority'][
                'progression_by_cl'][str(cl)]['feature_record_ids'][0]
            if cl == 2:
                channel = events[-1]['legal_channel']
            choices = [{'kind': 'level_advance', 'record_id': feature, 'effective_cl': cl,
                        'acquisition_channel': channel,
                        'parameters': {'native_path_progressions': entries}}]
            if cl == 5:
                choices.append({'kind': 'foundation_acquisition', 'record_id': IDENTITY,
                                'effective_cl': cl, 'acquisition_channel': 'foundation-selection',
                                'parameters': {'stage': 'Awakened'}})
            for choice in choices:
                event, state, blockers = stage2._choice_event(
                    conn=conn, row=proposal, project=project, state=state, choice=choice,
                    index=len(events), sequence=len(events) + 1,
                    previous_hash=events[-1]['event_hash'], generic_prefix=events,
                    record_cache=cache)
                assert not blockers, (choice, blockers)
                assert event is not None
                events.append(event)
    pb = 2 + (target_cl - 1) // 4
    cp = state['resources']['tianxia.resource.qi']
    assert cp['foundation_delta'] == pb
    assert all(r['foundation_delta'] == 0 for key, r in state['resources'].items()
               if key != 'tianxia.resource.qi')
    validated = validate_initial_foundation_mechanics(record, events)
    assert validated['stage'] == 'Awakened'
    acquisition = next(e for e in events if e['advancement']['kind'] == 'foundation_acquisition')
    mechanics = acquisition['advancement']['calculation']['outputs']['initial_foundation_mechanics']
    installed = installed_foundation_state(mechanics, IDENTITY, acquisition['event_id'])
    assert installed['resource']['current'] == 0
    assert installed['resource']['maximum'] == 1
    for _ in range(2):
        rebuilt, _, _ = stage2._rows(json.loads(json.dumps(events)), project['project_id'])
        assert rebuilt['resources'] == state['resources']
        assert rebuilt['resources']['tianxia.resource.qi']['foundation_delta'] == pb


@pytest.mark.parametrize('current_relation,expected', [
    ('ALLY', 'NORMAL'), ('NEUTRAL', 'NORMAL'), ('ENEMY', 'ADVANTAGE'),
])
@pytest.mark.parametrize('same_team', [False, True])
def test_reserve_hostility_follows_committed_relations_and_cold_replay(
        tmp_path, current_relation, expected, same_team):
    """Isolated table regression using the existing classified-pressure fixture.

    This fixture does not certify native source acquisition/classification;
    the separate causal tests cover acquisition, and whole acceptance still
    requires the missing production classification producer.
    """
    from tests.test_a2_foundations3 import setup, use
    from tests.worker2_support import OWNER, ALLY, FOE, turn, reload

    combat, table, mid = setup(tmp_path, 'lotus', initial=0)
    engine = reload(tmp_path, mid)
    if not same_team:
        combat.change_relations(mid, change={
            'kind': 'ACTOR_SIDE', 'subject': ALLY,
            'other': engine.state.actors[FOE].team_id,
        }, expected_state_version=engine.state.state_version)
    # The fixture's friendly pressure is explicitly any-creature, so the real
    # table can commit it for all diplomacy states without changing targeting.
    engine = reload(tmp_path, mid)
    combat.change_relations(mid, change={
        'kind': 'ACTOR_RELATION', 'subject': ALLY, 'other': OWNER,
        'relation': current_relation,
    }, expected_state_version=engine.state.state_version)
    turn(table, mid, ALLY)
    use(combat, table, mid, 'Friendly Poison pressure', OWNER)
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert save.actor_id == OWNER and save.payload['mode'] == expected
