"""Native defaults are independent of the global milestone representative."""
from copy import deepcopy
import itertools

import pytest

from app.core import FoundryError, canonical_json
from character_creation.path_attainment import (
    CANONICAL_PATH_IDS, INITIAL_PATH_ATTAINMENT_POLICY,
    equal_initial_path_attainment, initial_path_attainment_vector,
    native_path_progressions, factory_support_blocker,
)
from character_creation.service import CharacterCreationExecutionService
from non_sphere_authority.service import CANONICAL_TO_COMPACT, _TRUSTED_CHARACTER_CREATION_PROGRESS_REBIND
from tests.test_ns1r_non_sphere_authority import authority, insert_project


def policy_request():
    return {"server_owned_authority": {"initial_path_attainment_policy": deepcopy(INITIAL_PATH_ATTAINMENT_POLICY)}}


def stored_native(db, project_id):
    with db.transaction() as conn:
        return tuple(conn.execute("SELECT state_json,state_hash FROM non_sphere_character_states WHERE project_id=?", (project_id,)).fetchone())


@pytest.mark.parametrize("selected", [list(pair) for pair in itertools.combinations(CANONICAL_PATH_IDS, 2)] + [list(CANONICAL_PATH_IDS)])
def test_equal_native_initialization_preserved_for_every_path_combination(authority, selected):
    service, db = authority
    project_id = "equal-native-combination"
    insert_project(db, project_id, target_cl=15)
    vector = initial_path_attainment_vector(selected, 15)
    service.initialize_for_project(project_id, target_cl=15, path_ids=selected, path_attainment_by_id={path_id: vector[path_id] for path_id in selected})
    method_id = next(mid for mid, method in service.methods.items() if {
        row['path_id'] for row in method.get('explicit_ap_grants') or [] if row.get('grants_attainment_points')
    } == {CANONICAL_TO_COMPACT[path_id] for path_id in selected})
    before = stored_native(db, project_id)
    arguments = dict(method_id=method_id, selected_path_ids=selected,
                     progression_by_cl={cl: selected[0] for cl in range(1, 16)},
                     target_cl=15, _equal_initial_attainment=True)
    with pytest.raises(FoundryError, match="trusted character creation"):
        service.rebind_initial_path_progression(project_id, **arguments)
    for _ in range(2):
        receipt = service.rebind_initial_path_progression(project_id, **arguments, _creation_authority=_TRUSTED_CHARACTER_CREATION_PROGRESS_REBIND)
        assert receipt['schema'].endswith('.v2')
        assert receipt['path_attainment_by_id'] == vector
        assert receipt['rebound'] is False
        assert stored_native(db, project_id) == before


@pytest.mark.parametrize("locked_count", [0, 1])
def test_equal_mode_completes_only_deferred_initial_paths(authority, locked_count):
    service, db = authority
    body, _, spirit = CANONICAL_PATH_IDS
    selected = [body, spirit]
    locked = selected[:locked_count]
    project_id = 'equal-deferred-paths'
    insert_project(db, project_id, target_cl=15)
    service.initialize_for_project(project_id, target_cl=15, path_ids=locked, path_attainment_by_id={p: 15 for p in locked})
    receipt = service.rebind_initial_path_progression(project_id, method_id='METHOD-087', selected_path_ids=selected, progression_by_cl={cl: body for cl in range(1, 16)}, target_cl=15, _equal_initial_attainment=True, _creation_authority=_TRUSTED_CHARACTER_CREATION_PROGRESS_REBIND)
    assert receipt['path_attainment_by_id'] == initial_path_attainment_vector(selected, 15)
    state = service.get_state(project_id)
    assert len(state['ap_transaction_history']) == 1
    transaction = state['ap_transaction_history'][0]
    assert transaction['kind'] == 'INITIALIZATION'
    assert transaction['attainment_points_allocated'] == transaction['ap_spent'] == 30
    before = stored_native(db, project_id)
    service.rebind_initial_path_progression(project_id, method_id='METHOD-087', selected_path_ids=selected, progression_by_cl={cl: body for cl in range(1, 16)}, target_cl=15, _equal_initial_attainment=True, _creation_authority=_TRUSTED_CHARACTER_CREATION_PROGRESS_REBIND)
    assert stored_native(db, project_id) == before


def test_equal_mode_cannot_rewrite_a_split_initial_ledger(authority):
    service, db = authority
    body, _, spirit = CANONICAL_PATH_IDS
    project_id = "equal-does-not-promote-retained-split"
    insert_project(db, project_id, target_cl=15)
    service.initialize_for_project(project_id, target_cl=15, path_ids=[body, spirit], path_attainment_by_id={body: 10, spirit: 5})
    before = stored_native(db, project_id)
    with pytest.raises(FoundryError) as caught:
        service.rebind_initial_path_progression(project_id, method_id='METHOD-087', selected_path_ids=[body, spirit], progression_by_cl={cl: body for cl in range(1, 16)}, target_cl=15, _equal_initial_attainment=True, _creation_authority=_TRUSTED_CHARACTER_CREATION_PROGRESS_REBIND)
    assert caught.value.code == 'NS1R_INITIAL_CREATION_PROGRESS_REBIND_CONFLICT'
    assert stored_native(db, project_id) == before


def test_legacy_rebind_retains_its_original_split_representation(authority):
    service, db = authority
    body, qi, spirit = CANONICAL_PATH_IDS
    project_id = 'legacy-split-rebind'
    insert_project(db, project_id, target_cl=5)
    service.initialize_for_project(project_id, target_cl=5, path_ids=[qi], path_attainment_by_id={qi: 5})
    receipt = service.rebind_initial_path_progression(project_id, method_id='METHOD-081', selected_path_ids=[body, qi], progression_by_cl={1: body, 2: qi, 3: qi, 4: qi, 5: qi}, target_cl=5, _creation_authority=_TRUSTED_CHARACTER_CREATION_PROGRESS_REBIND)
    assert receipt['schema'].endswith('.v1')
    assert receipt['path_attainment_by_id'] == {body: 1, qi: 4, spirit: 0}
    assert receipt['rebound'] is True


def test_policy_is_covered_by_request_hash():
    request = policy_request()
    original = CharacterCreationExecutionService.request_payload_sha256(request)
    del request['server_owned_authority']['initial_path_attainment_policy']
    assert CharacterCreationExecutionService.request_payload_sha256(request) != original


def test_subpath_menu_uses_native_levels_instead_of_global_representative_counts():
    from character_creation.creative_controller.linear_menus import final_path_attainment
    body, _, spirit = CANONICAL_PATH_IDS
    request = policy_request()
    request['frozen_owner_target_cl'] = 15
    committed = {'by_slot': {'path_choice': [body, spirit]}, 'bounded': {'path_progression_by_cl': {str(cl): body for cl in range(1, 16)}}}
    assert final_path_attainment(request, {}, committed) == {body: 15, spirit: 15}
    del request['server_owned_authority']['initial_path_attainment_policy']
    assert final_path_attainment(request, {}, committed) == {body: 15, spirit: 0}


def test_legacy_request_is_not_promoted_and_policy_types_are_exact():
    assert equal_initial_path_attainment({}) is False
    request = policy_request()
    assert equal_initial_path_attainment(request) is True
    request['server_owned_authority']['initial_path_attainment_policy']['unselected_path_level'] = False
    with pytest.raises(FoundryError):
        equal_initial_path_attainment(request)


def test_native_art_attainment_counts_each_path_once_per_global_level():
    body, _, spirit = CANONICAL_PATH_IDS
    records = [{"record_id": path_id, "compatibility": {"factory": {"stage2_authority": {
        "progression_by_cl": {str(cl): {"feature_record_ids": [path_id + '.feature.' + str(cl)]} for cl in range(1, 19)},
    }}}} for path_id in (body, spirit)]
    rows = [{"kind": "level_advance", "effective_cl": cl, "record_id": body + '.feature.' + str(cl), "parameters": {"native_path_progressions": native_path_progressions(records, cl)}} for cl in range(1, 19)]
    for path_id in (body, spirit):
        assert CharacterCreationExecutionService._immortal_path_cl_at(path_id=path_id, point_cl=15, rows=rows, path_authorities={}) == 15
        assert CharacterCreationExecutionService._immortal_path_cl_at(path_id=path_id, point_cl=18, rows=rows, path_authorities={}) == 18
    rows[0]['parameters']['native_path_progressions'].append(deepcopy(rows[0]['parameters']['native_path_progressions'][0]))
    assert CharacterCreationExecutionService._immortal_path_cl_at(path_id=body, point_cl=18, rows=rows, path_authorities={}) == 17


def test_factory_support_is_distinct_from_response_validation():
    assert factory_support_blocker({'blockers': [{'code': 'CG1_IMMORTAL_ART_AUTHORITY_MISSING'}]})
    assert not factory_support_blocker({'blockers': [{'code': 'CG1_RESPONSE_SCHEMA_INVALID'}]})


def test_stage2_resource_entry_point_uses_both_native_paths_without_refilling(monkeypatch):
    from types import SimpleNamespace
    import json
    from stage2.service import RulesCausalStage2Service, _INITIAL_CREATION_EXECUTION
    body, _, spirit = CANONICAL_PATH_IDS
    service = object.__new__(RulesCausalStage2Service)
    assert service._equal_initial_path_records(None, 'resource-test', {}) is None
    request = policy_request()
    request['request_sha256'] = CharacterCreationExecutionService.request_payload_sha256(request)
    class Connection:
        def execute(self, query, params):
            assert params == ('resource-run', 'resource-test')
            return self
        def fetchone(self):
            return {'request_json': json.dumps(request)}
    records = {}
    for path, pool in [(body, 'stamina'), (spirit, 'resonance')]:
        records[path] = {
            'record_id': path, 'record_hash': 'a' * 64,
            'source': {'source_id': 'fixture', 'source_hash': 'b' * 64, 'anchor': path},
            'content_binding': {'pack_id': 'fixture', 'pack_version': '1', 'pack_hash': 'c' * 64},
            'compatibility': {'factory': {'stage2_authority': {'resources': [{
                'resource_id': pool, 'base_formula': {'schema_version': 'TianxiaFoundry.SafeFormula.v1', 'formula_id': pool, 'root': {'op': 'cl'}},
            }]}}},
        }
    monkeypatch.setattr(service, '_validated_initial_creation_delegated_path_ids', lambda *args: frozenset(records))
    monkeypatch.setattr(service, '_resolve_record_after_proof', lambda conn, project, rid: records[rid])
    state = {'paths': [body, spirit], 'record_event_ids': {}, 'ability_scores': {}, 'ability_modifiers': {}}
    token = _INITIAL_CREATION_EXECUTION.set(SimpleNamespace(project_id='resource-test', run_id='resource-run', request_sha256=request['request_sha256']))
    try:
        for level in (15, 18):
            # Owner ruling 2026-09-23: a resource stays as full as it was when its
            # maximum grows; an existing deficit carries over (never a refill).
            pools, bindings, trace = service._resource_recalculation(Connection(), 'resource-test', state, cl=level, pb=5, path=records[body], current_resources={'stamina': {'current': 3, 'maximum': 10}, 'resonance': {'current': 4, 'maximum': 10}})
            assert {k: (v['maximum'], v['current']) for k, v in pools.items()} == {'stamina': (level, level - 7), 'resonance': (level, level - 6)}
            assert {b['record_id'] for b in bindings} == {body, spirit}
        request['server_owned_authority']['unexpected'] = 'changed-after-freeze'
        with pytest.raises(FoundryError) as caught:
            service._equal_initial_path_records(Connection(), 'resource-test', state)
        assert caught.value.code == 'CG1_PATH_ATTAINMENT_AUTHORITY_INVALID'
    finally:
        _INITIAL_CREATION_EXECUTION.reset(token)


def test_stage2_proposal_schema_preserves_exact_native_entry_shape():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).parents[1] / 'schemas/Stage2_Advancement_Proposal_v2.schema.json').read_text())
    validator = Draft202012Validator(schema['properties']['choices']['items']['properties']['parameters'])
    body = CANONICAL_PATH_IDS[0]
    source = {'path_id': body, 'source_path': 'pinned/path.md', 'source_hash': 'a' * 64, 'authority_snapshot_hash': 'b' * 64}
    parameters = {'native_path_progressions': [{'path_id': body, 'cl': 15, 'automatic_feature_record_ids': [body + '.feature.15'], 'source': source}]}
    from stage2.service import KIND_PARAMETER_KEYS
    assert set(parameters) <= KIND_PARAMETER_KEYS['level_advance']
    assert all(not (set(parameters) & keys) for kind, keys in KIND_PARAMETER_KEYS.items() if kind != 'level_advance')
    assert not list(validator.iter_errors(parameters))
    for field, value in [('cl', True), ('path_id', 'invented'), ('unverified_override', True)]:
        invalid = deepcopy(parameters)
        invalid['native_path_progressions'][0][field] = value
        assert list(validator.iter_errors(invalid))
    invalid = deepcopy(parameters)
    invalid['native_path_progressions'][0]['source'].pop('source_hash')
    assert list(validator.iter_errors(invalid))
    invalid = deepcopy(parameters)
    invalid['native_path_progressions'] *= 2
    assert list(validator.iter_errors(invalid))
