"""Restricted source acquisition -> compiled table -> cold mechanical replay.

The test authority transport seals the actual canonical source records; access,
AP awards and selection use the public committed authority-event API. No passive
rows or ownership/trigger receipts are injected into a fight bundle.
"""
import pytest
from app.core import FoundryError
from non_sphere_authority.service import NonSphereAuthorityService
from tests.test_ns1r_non_sphere_authority import authority, insert_project
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER
from combat.ext import mgr_reserve_mercurial_cultivator_mercurial_qi as m

QI_PATH = 'tianxia.path.qi_cultivation'
PARENT = m.PREFIX.removesuffix('.feature.')


def test_native_restricted_acquisition_to_paid_table_progression(authority, tmp_path):
    source, db = authority
    pid = 'mercurial-native'
    insert_project(db, pid, target_cl=18)
    source.initialize_for_project(pid, target_cl=18, path_ids=[QI_PATH], method_id='METHOD-001')
    evidence = ap_award(db, source, pid, 'METHOD-001', 18, 17)
    source.allocate_advancement(pid, {QI_PATH: 17}, evidence_id=evidence, idempotency_key='mercurial.cl18')
    with pytest.raises(FoundryError) as denied:
        source.select_subpath(pid, QI_PATH, PARENT)
    assert denied.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
    access = commit_authority_event(db, source, pid, 'subpath_access', {'selection_id': PARENT})
    state = source.select_subpath(pid, QI_PATH, PARENT, access_source_records=[access])
    cold = NonSphereAuthorityService(db).get_state(pid)
    # Validation's operation label is freshly derived on get_state; retained
    # acquisition and advancement authority must remain exactly the same.
    assert cold['paths'] == state['paths']
    assert cold['access_source_records'] == state['access_source_records']
    path = next(p for p in cold['paths'] if p['path_id'] == QI_PATH)
    selected = source.subpaths[path['subpath_or_tradition_id']]
    granted = [r['canonical_id'] for r in selected['feature_progression'] if r['granted_at_cl'] <= path['attainment']]
    assert set(granted) == {m.PREFIX + name for name in m.LEVELS}
    path_grants = [r['canonical_id'] for r in source.path_profiles[QI_PATH]['features']
                   if r.get('minimum_cl', 1) <= path['attainment']]
    combat, table, mid = fixture(tmp_path / 'fight', [*path_grants, *granted], cl=path['attainment'])
    engine = reload(tmp_path / 'fight', mid)
    assert {r['kind'] for r in engine.typed_passive_rows[OWNER] if r.get('block') == m.BLOCK} == set(m.LEVELS)
    before = engine.state.actors[OWNER].resources[m.QI]
    settle(table, mid, candidate(combat, mid, 'Prima Materia').candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Liquid Form').candidate_id)
    assert reload(tmp_path / 'fight', mid).state.actors[OWNER].resources[m.QI] == before - 8


def test_real_builder_acquisition_materializes_all_five_and_plays_capstone(catalog_environment, tmp_path, monkeypatch):
    """The real builder acquires all five features and the capstone plays on the table.

    Limit of this test: no browser is configured, so a run that stops at
    NEEDS_REVIEW with exactly COMMAND6_CHARACTER_GM_CONSUMER_FAILED (a skipped
    browser harness) is accepted here, and only that single blocker is accepted.
    Native acquisition, owner-sheet materialization and table play still run after
    it. Reaching READY_FOR_REVIEW needs the rendered browser verification, which
    this test does not perform and does not prove.
    """
    from app.api import create_app
    from combat.factory_compiler import compile_character
    # The materializer's Command 6 browser boundary must fail before launching
    # any executable; this test covers native acquisition, sheet materialization
    # and table play, not the rendered browser pass.
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE', str(tmp_path / 'BROWSER_FORBIDDEN'))
    app = create_app(catalog_environment['settings'])
    builder = app.state.character_builder
    project = builder.create_project(working_name='Mercurial native CL18', concept='Mutable Qi defense and mobility',
        source_reference=None, target_cl=18, power_band='rival/boss', creation_mode='quick',
        generation_route='ai_bootstrap', ability_scores={}, autogen_seed='MGR-MERCURIAL-NATIVE-18',
        selections={'path_choice': [QI_PATH], 'subpath_choice': [PARENT]}, method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run = app.state.character_creation.start(project['project_id'], execution_mode='STANDARD_API',
        idempotency_key='mgr-mercurial-native-build', controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    if run['status'] != 'READY_FOR_REVIEW':
        assert run['status'] == 'NEEDS_REVIEW'
        assert len(run['blockers']) == 1 and run['blockers'][0]['code'] == 'COMMAND6_CHARACTER_GM_CONSUMER_FAILED'
        browser = run['blockers'][0]['details']['consumer_report']['harness_run']
        assert browser['skipped'] is True and browser['exit_code'] is None
    candidate_doc = app.state.character_creation.load_candidate_gm_context(run['run_id'])
    owner_sheet = candidate_doc['owner_character_sheet']
    compiled = compile_character(owner_sheet, actor_id=OWNER, reaction_plan={'ask': True})
    rows = [r for r in compiled['typed_passives'] if r.get('block') == m.BLOCK]
    assert {r['kind'] for r in rows} == set(m.LEVELS)
    combat, table, mid = fixture(tmp_path / 'materialized-fight', [], cl=18, owner_bundle=compiled)
    before = reload(tmp_path / 'materialized-fight', mid).state.actors[OWNER].resources[m.QI]
    settle(table, mid, candidate(combat, mid, 'Prima Materia').candidate_id)
    engine = reload(tmp_path / 'materialized-fight', mid)
    assert m.held(engine.state.actors[OWNER], 'prima_materia')
    assert engine.state.actors[OWNER].resources[m.QI] == before - 8
