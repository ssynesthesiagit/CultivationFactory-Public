"""Synthetic, persisted portable Combustive Step fights and service intents."""
from combat.canonical import canonical_sha256, sha256_file
from combat.character_runtime_adapter import (
    CharacterRuntimeBundle, RuntimeResourceInitialization, SOURCE_ACTOR_ID, dummy_actor_template,
)
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, LegalCandidate
from combat.gate5_service import CombatService
from combat.placement_menu import cells
from combat.portable_runtime_authority import PortableRuntimeAuthority, runtime_actor_id
from tests.h1_support import ROOT


STEP = 'action:fire.combustive_step'


def _synthetic_bundle():
    """Validated portable bundle with no owner package data."""
    raw = CharacterRuntimeBundle.model_construct(
        source_combat_sheet_sha256='0' * 64, mechanics_lock_sha256='0' * 64,
        primitive_registry_sha256='0' * 64,
        actor_template=dummy_actor_template(SOURCE_ACTOR_ID, team_id='team:source_character'),
        action_catalog=(), reaction_parameters={}, passive_bindings=(), augment_bindings=(),
        primitive_bindings=(), support_matrix=(),
        resource_initialization=RuntimeResourceInitialization(qi_current=0, martial_focus_current=0,
            provenance_kind='TEST_FIXTURE', provenance_id='pytest:sol115'),
        bundle_sha256='',
    ).model_dump(mode='json', by_alias=True)
    raw.pop('bundle_sha256')
    raw['bundle_sha256'] = canonical_sha256(raw)
    return CharacterRuntimeBundle.model_validate(raw)


def portable_step_fight(tmp_path, *, seed='SOL115-SYNTHETIC'):
    """Save a 30-foot-Speed portable actor on the standard terrain grid."""
    package = tmp_path / 'synthetic.zip'
    package.write_bytes(b'synthetic source')
    digest = sha256_file(package)
    actor_id = runtime_actor_id('synthetic', digest)
    raw = _synthetic_bundle().model_dump(mode='json', by_alias=True)
    raw['actor_template']['action_ids'] = [STEP]
    raw['actor_template']['primary_combatant'] = True
    raw['actor_template']['resources'][0]['initial'] = 15
    raw['action_catalog'] = [ActionDefinition(source_definition_id=STEP, display_name='Step',
        owner_id=raw['actor_template']['entity_id'], economy='BONUS_ACTION',
        resolution_kind='C3AR_COMBUSTIVE_STEP', target_kind='CELL', range_ft=15,
        costs=(('resource:core.qi', 1),)).model_dump(mode='json')]
    raw.pop('bundle_sha256')
    raw['bundle_sha256'] = canonical_sha256(raw)
    authority = dict(runtime_actor_id=actor_id, candidate_entry_id='synthetic',
        project_id='synthetic', package_sha256=digest, project_revision=1,
        event_head_hash='0'*64, replay_state_hash='0'*64, content_lock_hash='0'*64,
        combat_sheet_id='synthetic', combat_sheet_commitment_sha256='0'*64,
        mechanics_lock_sha256=raw['mechanics_lock_sha256'],
        primitive_registry_sha256=raw['primitive_registry_sha256'],
        runtime_adapter_id=raw['adapter_id'], runtime_adapter_version=raw['adapter_version'],
        runtime_engine_version=raw['engine_version'], actor_template_commitment_sha256='0'*64,
        source_actor_id=raw['actor_template']['entity_id'], bundle=raw)
    authority = PortableRuntimeAuthority.model_construct(**authority).model_dump(mode='json', by_alias=True)
    authority.pop('authority_sha256', None)
    authority['authority_sha256'] = canonical_sha256(authority)
    service = CombatService(ROOT, tmp_path)
    mid = service.persistence.create_match(match_seed=seed,
        runtime_authority=authority, source_package=package,
        roster_setup={'primary_actor_ids': [actor_id, AN],
            'team_by_actor': {actor_id: 'a', AN: 'b'},
            'starting_positions': {actor_id: {'x': 13, 'y': 4}, AN: {'x': 13, 'y': 5}}}).match_id
    for participant in (actor_id, AN):
        service.set_controller_mode(mid, actor_id=participant, controller_mode='MANUAL')
    if service.decision(mid)['context']['active_actor_id'] != actor_id:
        context = service.decision(mid)['context']
        end = next(c for c in context['legal_candidates'] if c['kind'] == 'END_TURN')
        preview_commit(service, mid, intent_from_candidate(context, end))
    return service, mid, actor_id


def intent_from_candidate(context, candidate):
    return dict(decision_id=context['decision_id'], state_version=context['state_version'],
        candidate_id=candidate['candidate_id'], actor_id=candidate['actor_id'],
        target_ids=candidate.get('target_ids') or [], destination=candidate.get('destination'),
        option_ids=candidate.get('option_ids') or [])


def step_placements(engine, context):
    root = next(c for c in context['legal_candidates'] if c['source_definition_id'] == STEP)
    assert root['metadata']['placement_picker']
    return root, list(cells(engine, LegalCandidate.model_validate(root)))


def step_intent(context, root, destination):
    return {**intent_from_candidate(context, root),
            'placement_destination': destination.model_dump(mode='json')}


def preview_commit(service, mid, intent):
    reactions = []
    for _ in range(12):
        preview = service.preview(mid, intent, reactions)
        if preview['status'] != 'REACTION_REQUIRED':
            assert preview['status'] == 'PREVIEW_COMPLETE', preview
            return service.submit_intent(mid, intent, reactions, preview['preview_id'])
        reaction = preview['reaction_context']
        reactions.append({'checkpoint': reaction['checkpoint'], 'reactor_id': reaction['reactor_id'],
            'reaction_source_id': reaction['reaction_source_id'], 'selection': 'DECLINE', 'spend': 0, 'option_ids': []})
    raise AssertionError('reaction preview exceeded bounded checkpoints')
