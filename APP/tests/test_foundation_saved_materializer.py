"""Saved Foundation mechanics cross review persistence and materialization.

All stores and source records are synthetic. The Foundation projection, review
issuer, immutable copy, publication and reload are real; unrelated Path/action
projections and the external compiler are isolated test doubles.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil

from app.core import Database, Settings
from factory_authoring import final_character_materializer as m
from non_sphere_authority import foundation_mechanics as fm
from security.approval_challenges import ApprovalChallengeService
from security.integrity import create_test_integrity_service
from security.local_identity import DeterministicTestPrincipalProvider
from tests.foundation_catalog_edit_support import edit_catalog
from tests.test_foundation_saved_mechanics import mandate_catalog, IDENTITY


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def workspace_with_foundation(tmp_path, record):
    workspace = tmp_path / 'source'
    mechanics = fm.resolve_initial_foundation_mechanics(record, ['tianxia.path.qi_cultivation'])
    foundation = fm.installed_foundation_state(mechanics, IDENTITY, 'event.foundation.saved')
    foundation.update({
        'display_name': record['display_name'], 'record_hash': 'b' * 64,
        'source_packet_ids': ['packet.foundation.saved'], 'mechanical_projection': True,
        'acquisition_event_id': 'event.foundation.saved', 'mechanics_schema': mechanics['schema'],
        'mechanics': mechanics,
    })
    ledger = {'character': {'paths': [{'path_id': 'tianxia.path.qi_cultivation', 'effective_cl': 5}]},
              'foundation': foundation}
    write(workspace / 'Build/Character_Master_Ledger.json', ledger)
    write(workspace / m._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE, ledger)
    write(workspace / 'Build/Foundation_Detail_Ledger.json', {
        'schema_version': 'TianxiaFoundry.CharacterGMFoundation.v1', 'foundation': foundation})
    source = record['source']
    write(workspace / 'Command_2/Rules_Selection_Packets.json', {
        'schema_version': 'TianxiaFoundry.RulesSelectionPackets.v2', 'packets': [{
            'packet_id': 'packet.foundation.saved', 'record_id': IDENTITY,
            'display_name': record['display_name'], 'target_cl': 5,
            'advancement_kind': 'foundation_acquisition', 'event_id': 'event.foundation.saved',
            'record_hash': 'b' * 64,
            'content_binding': {'pack_id': 'tianxia.non_sphere.authority',
                               'pack_version': '0.4C-mechanics.1', 'record_hash': 'b' * 64},
            'full_description': record['summary'], 'short_description': record['summary'],
            'source_evidence': [{
                'source_id': 'source.' + source['artifact_sha256'][:24],
                'source_path': source['artifact'], 'source_hash': source['artifact_sha256'],
                'source_anchor': 'foundation:' + IDENTITY}],
        }]})
    m._recompute_workspace_receipts(workspace)
    return workspace, deepcopy(mechanics)


def isolate_other_projections(monkeypatch, record, arts, composite):
    fixed = {
        'schema': 'HF05ZVK-R1F.AuthoritativeFoundationRuntimeCatalog.v1',
        'status': 'AUTHORITATIVE_30_ONLY', 'foundations': [{
            'foundation_id': IDENTITY, 'name': record['display_name'],
            'profile': {'grade': 'Heaven', 'default_stage': 'Awakened', 'typical_role': 'Synthetic chassis.'},
            'overview': {'summary': 'Synthetic Foundation overview.'},
            'resource': {'name': 'Edict Seal', 'starting': '0', 'maximum': '1', 'gain': 'Synthetic trigger.'},
            'features': {stage: [{'name': 'Synthetic benefit', 'effect': 'Synthetic effect.',
                                  'type': 'No Action / Triggered'}]
                         for stage in ('awakened', 'refined', 'perfected', 'integrated')},
            'compatibility': {'legal_spheres': [], 'does_not_grant': []},
            'risks': {key: [] for key in ('burdens', 'hidden_injuries', 'strains', 'deviations')},
            'repair_practices': [], 'foundation_challenges': [],
        }],
    }

    def fixed_authority(path, digest):
        assert (path, digest) == (m._PACKET_FOUNDATION_SOURCE_PATH, m._PACKET_FOUNDATION_SOURCE_SHA256)
        return fixed

    monkeypatch.setattr(m, '_bridge_fixed_factory_json', fixed_authority)
    monkeypatch.setattr(m.CompositeControllerAuthoring, 'validate_overlay',
                        lambda *args, **kwargs: deepcopy(composite))
    monkeypatch.setattr(m, 'constructed_immortal_art_binding', lambda *args: deepcopy(arts))
    monkeypatch.setattr(m, 'translate_constructed_immortal_arts', lambda *args: {'binding': deepcopy(arts)})
    monkeypatch.setattr(m, '_verify_immortal_action_projection', lambda *args: {'equal': True})
    monkeypatch.setattr(m, '_build_runtime_controller', lambda *args, **kwargs: {})
    monkeypatch.setattr(m, '_recompute_checkpoints', lambda *args: 0)
    for name in (
        '_project_modern_path_fields_for_compiler', '_project_method_for_compiler',
        '_project_modern_ability_generation_for_compiler', '_project_background_origin_allocations_for_compiler',
        '_project_background_origin_insight_for_compiler', '_project_background_equipment_for_compiler',
        '_project_modern_resource_for_compiler', '_project_modern_hp_for_compiler',
        '_project_modern_core_saves_for_compiler', '_project_modern_ac_for_compiler',
        '_project_modern_speed_for_compiler', '_project_modern_initiative_for_compiler',
        '_project_modern_realm_for_compiler', '_promote_materialized_command4_ledger',
    ):
        monkeypatch.setattr(m, name, lambda *args, **kwargs: {})

    def packet_bridge(workspace, _corpus):
        packet = workspace / 'Command_2/Rules_Selection_Packets.json'
        return {'modern_provenance_sha256': m.sha256_file(packet),
                'modern_provenance_path': 'Command_2/Rules_Selection_Packets.json',
                'native_registry_sha256': m.sha256_file(packet),
                'native_registry_packet_ids': ['packet.foundation.saved'],
                'native_registry_packet_count': 1, 'pruned_packet_ids': []}

    monkeypatch.setattr(m, '_bridge_rules_packet_registry', packet_bridge)
    monkeypatch.setattr(m, '_assert_production_pins', lambda *args: None)
    monkeypatch.setattr(m, '_corpus_pin', lambda *args: 'c' * 64)
    monkeypatch.setattr(m, '_load_compiler_module', lambda *args: None)

    def compiler(*, compiler_path, corpus, workspace):
        # This synthetic workspace needs no external compiler or model server.
        # The real Foundation projection must already have run in the copy.
        foundation = json.loads((workspace / 'Build/Character_Master_Ledger.json').read_text())['foundation']
        assert foundation['mechanics']['hp_maximum_modifiers']
        write(workspace / 'Compiler_Output/synthetic.json', foundation)
        return {'execution_mode': 'pinned_subprocess', 'returncode': 0, 'corpus_sha256': 'c' * 64}

    def compiler_output(workspace):
        assert (workspace / 'Compiler_Output/synthetic.json').is_file()

    monkeypatch.setattr(m, '_run_pinned_compiler_after_manual_lineage_gate', compiler)
    monkeypatch.setattr(m, '_validate_compiler_output', compiler_output)


def test_saved_foundation_survives_catalog_edit_through_review_and_finalize(tmp_path, monkeypatch, mandate_catalog):
    # Owner ask: a catalog prose/hash edit cannot strand an in-flight Factory workspace.
    mandate_catalog['summary'] = 'Synthetic Foundation summary.'
    source, saved = workspace_with_foundation(tmp_path, mandate_catalog)
    source_hash = m._workspace_sha256(source)
    composite_root = tmp_path / 'composite'
    write(composite_root / 'synthetic.json', {'fixture': 'composite'})
    composite = {
        'overlay_id': 'composite.saved.foundation', 'artifact_sha256': 'd' * 64,
        'overlay_tree_sha256': 'f' * 64, 'manifest': {},
        'artifact': {
            'project_id': 'project.saved.foundation', 'base_candidate_sha256': 'a' * 64,
            'projection_id': 'projection.saved.foundation', 'source_workspace_sha256': source_hash},
    }
    arts_core = {'schema_version': 'TianxiaFoundry.ConstructedImmortalArtBinding.v1', 'arts': [{
        'immortal_art_id': 'tianxia.constructed.immortal_art.synthetic', 'name': 'Synthetic Art',
        'cl_created': 15, 'action_id': 'action.synthetic.art',
        'art_sha256': '1' * 64, 'action_sha256': '2' * 64}]}
    arts = {**arts_core, 'binding_sha256': m.sha256_json(arts_core)}
    isolate_other_projections(monkeypatch, mandate_catalog, arts, composite)
    prose_edit = deepcopy(mandate_catalog)
    prose_edit['semantic_surfaces']['gm_and_counterplay'] = 'Revised catalog commentary.'
    monkeypatch.setattr(fm, 'verified_foundation_records', lambda: {IDENTITY: prose_edit})
    # Isolate the mechanics-equality failure first (same packet source hash).
    # Then exercise a full catalog-file hash edit through the service below.
    probe = tmp_path / 'prose-only-copy'
    shutil.copytree(source, probe)
    assert m._project_foundation_for_compiler(probe)['projected_foundation']['mechanics'] == saved
    changed = edit_catalog(monkeypatch)[IDENTITY]
    assert changed['source']['artifact_sha256'] != saved['initial_state']['source']['artifact_sha256']
    assert fm.resolve_initial_foundation_mechanics(changed, ['tianxia.path.qi_cultivation']) != saved

    # Use the real approval/issuer/persisted-review store, with a deterministic local principal.
    binding = m._reviewed_binding_from_evidence(
        project_id='project.saved.foundation', candidate_sha256='a' * 64,
        projection_id='projection.saved.foundation', source_workspace_sha256=source_hash,
        composite_validated=composite, composite_overlay_files_tree_sha256=m._tree_hash(composite_root),
        composite_overlay_root=composite_root, constructed_immortal_arts=arts)
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / 'approval-data')
    db = Database(settings)
    db.migrate()
    integrity = create_test_integrity_service()
    challenges = ApprovalChallengeService(
        db, principal_provider=DeterministicTestPrincipalProvider(), integrity=integrity)
    parameters = m._review_approval_parameters(binding)
    challenge = challenges.issue(**{key: value for key, value in parameters.items()
                                    if key != 'evidence_context'})['challenge']
    evidence = challenges.consume(
        challenge_id=challenge['challenge_id'], nonce=challenge['nonce'], **parameters)
    issuer = m.FinalCharacterReviewIssuer(tmp_path / 'reviews', db, integrity, binding)
    record = issuer.issue_from_evidence(evidence['evidence_id'])
    assert issuer.review_authority.load_record(record['record_id']) == record

    materializer = m.FinalCharacterMaterializer(issuer.review_authority)
    # Keep the isolated compiler/corpus inside this test's own sandbox.
    materializer._compiler_path = tmp_path / 'synthetic-compiler'
    materializer._corpus_path = tmp_path / 'synthetic-corpus'
    result = materializer.materialize(source, composite_root, tmp_path / 'output',
                                     review_record_id=record['record_id'])
    final = Path(result['output_path'])
    projected = json.loads((final / 'Build/Character_Master_Ledger.json').read_text())['foundation']
    assert projected['mechanics'] == saved
    assert projected['foundation_resource']['current'] == 0
    assert result['receipt']['foundation_projection']['projected_foundation']['mechanics'] == saved
    assert m._workspace_sha256(source) == source_hash
    assert json.loads((source / 'Build/Character_Master_Ledger.json').read_text())['foundation']['mechanics'] == saved
    assert issuer.review_authority.load_record(record['record_id']) == record
