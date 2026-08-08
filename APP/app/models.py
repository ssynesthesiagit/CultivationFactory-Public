from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackLockRequest(StrictModel):
    pack_id: str
    version: str


class CreateProjectRequest(StrictModel):
    working_name: str = Field(min_length=1, max_length=240)
    pack_locks: list[PackLockRequest]
    quality_target: str = "rival/boss"
    user_locks: list[dict[str, Any]] = Field(default_factory=list)
    source_evidence: list[dict[str, Any]] = Field(default_factory=list)


class ExactEvidenceRecordRequest(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=500)
    authority_type: str = Field(min_length=1, max_length=120)
    canonical_content_id: str = Field(min_length=1, max_length=500)
    predicate_id: str = Field(min_length=1, max_length=500)
    source_record_id: str = Field(min_length=1, max_length=1000)
    source_hash: str = Field(pattern="^[0-9a-f]{64}$")


class CharacterSheetCreateRequest(StrictModel):
    working_name: str = Field(default="", max_length=240)
    concept: str = Field(default="", max_length=12000)
    target_cl: int = Field(default=15, ge=1, le=20)
    power_band: str = Field(default="rival/boss", min_length=1, max_length=100)
    source_reference: str | None = Field(default=None, max_length=2000)
    creation_mode: str = Field(default="quick", pattern="^(quick|detailed)$")
    generation_route: str = Field(default="player", pattern="^(player|ai_bootstrap)$")
    ability_scores: dict[str, int | None] = Field(default_factory=dict)
    selections: dict[str, list[str]] = Field(default_factory=dict)
    sphere_priority_ids: list[str] = Field(default_factory=list)
    talent_priority_ids: list[str] = Field(default_factory=list)
    method_planning_mode: str | None = Field(default=None, pattern="^(AUTO|PREFERENCE|EXACT|HARD_LOCK)$")
    method_preference_id: str | None = Field(default=None, min_length=1, max_length=100)
    method_route_choice: str | None = Field(default=None, min_length=1, max_length=100)
    method_learning_note: str | None = Field(default=None, max_length=500)
    canonical_sphere_ids: list[str] | None = None
    sphere_free_talent_grants: dict[str, str] | None = None
    ordinary_talent_ids: list[str] | None = None
    evidence_ids: list[ExactEvidenceRecordRequest] = Field(default_factory=list)
    background_route_ids: dict[str, Any] = Field(default_factory=dict)


class CanonicalCatalogChoiceLockRequest(StrictModel):
    acquired_sphere_ids: list[str]
    free_talent_grants: dict[str, str]
    ordinary_talent_ids: list[str]


class NS1RStateUpdateRequest(StrictModel):
    state: dict[str, Any]


class NS1RPrimaryMethodRequest(StrictModel):
    method_id: str = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list)


class NS1RTargetCLRequest(StrictModel):
    target_cl: int = Field(ge=1, le=20)


class NS1RAccessSourcesRequest(StrictModel):
    evidence_ids: list[str] = Field(default_factory=list)


class NS1RPathAttainmentRequest(StrictModel):
    path_id: str = Field(min_length=1, max_length=200)
    attainment: int = Field(ge=0, le=20)
    operation_mode: str = Field(pattern="^(ADMINISTRATIVE_PRESERVATION|MIGRATION_PRESERVATION)$")
    source_record_id: str = Field(min_length=1, max_length=500)


class NS1RAPAllocationRequest(StrictModel):
    allocations: dict[str, int] = Field(min_length=1)
    evidence_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=500)


class NS1RResourceRequest(StrictModel):
    path_id: str = Field(min_length=1, max_length=200)
    current: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)


class NS1RSubpathRequest(StrictModel):
    path_id: str = Field(min_length=1, max_length=200)
    selection_id: str = Field(min_length=1, max_length=240)
    evidence_ids: list[str] = Field(default_factory=list)


class NS1RFoundationRequest(StrictModel):
    foundation_id: str | None = Field(default=None, max_length=240)


class NS1RCompatibilityRequest(StrictModel):
    method_id: str = Field(min_length=1, max_length=100)
    foundation_id: str = Field(min_length=1, max_length=240)
    active_path_ids: list[str] = Field(default_factory=list)


class NS1RBackgroundValidationRequest(StrictModel):
    background_id: str = Field(min_length=1, max_length=240)
    selected_route_ids: dict[str, Any] = Field(default_factory=dict)


class NS1RMigrationPreviewRequest(StrictModel):
    legacy: dict[str, Any] = Field(default_factory=dict)


class CanonicalCreatorProjectionRequest(StrictModel):
    target_cl: int = Field(default=1, ge=1, le=20)
    acquired_sphere_ids: list[str] = Field(default_factory=list)
    background_sphere_ids: list[str] = Field(default_factory=list)
    free_talent_grants: dict[str, str] = Field(default_factory=dict)
    ordinary_talent_ids: list[str] = Field(default_factory=list)
    existing_talent_ids: list[str] = Field(default_factory=list)
    path_ids: list[str] = Field(default_factory=list)
    subpath_or_tradition_ids: list[str] = Field(default_factory=list)
    method_ids: list[str] = Field(default_factory=list)
    foundation_or_feature_ids: list[str] = Field(default_factory=list)
    character_feature_ids: list[str] = Field(default_factory=list)
    structural_authority_ids: list[str] = Field(default_factory=list)
    equipment_evidence_ids: list[str] = Field(default_factory=list)
    acquisition_evidence_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    character_id: str | None = None


class DraftEventRequest(StrictModel):
    event_type: str
    effective_point: dict[str, Any]
    actor_type: str = "human"
    actor_identifier: str | None = None
    content_pack_references: list[dict[str, Any]] = Field(default_factory=list)
    stable_rule_ids: list[str] = Field(default_factory=list)
    acquisition_channel: str | None = None
    prerequisite_evidence: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    superseded_event_reference: str | None = None
    rationale: str = ""
    planner_response_id: str | None = None


class ApproveRequest(StrictModel):
    approved_by: str = Field(min_length=1, max_length=200)


class HumanTrustApproval(StrictModel):
    archive_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)
    confirmation: str = Field(min_length=1, max_length=200)


class PackageRequest(StrictModel):
    package_name: str
    human_trust: HumanTrustApproval | None = None
    challenge_id: str | None = None
    nonce: str | None = None


class PackageChallengeRequest(StrictModel):
    package_name: str
    ttl_seconds: int = Field(default=300, ge=1, le=900)


class FoundationHandoffPrepareRequest(StrictModel):
    package_name: str
    output_name: str = "Tianxia_Foundation46_RC2_ContentPack_v1_0_0.zip"
    authorize_stage_repairs: bool = False


class ExportRequest(StrictModel):
    filename: str | None = None


class OwnerArtifactStageRequest(StrictModel):
    artifact_kind: str = Field(pattern="^(chat_request|project_backup|completed_character|gm_character|combat_package)$")
    project_id: str | None = Field(default=None, max_length=240)
    prompt_id: str | None = Field(default=None, max_length=240)
    match_id: str | None = Field(default=None, max_length=240)
    filename: str | None = Field(default=None, max_length=240)


class OwnerArtifactSaveAsRequest(StrictModel):
    artifact_id: str = Field(min_length=8, max_length=160)
    destination_path: str = Field(min_length=1, max_length=4096)
    overwrite: bool = False


class MigrationPreviewRequest(StrictModel):
    pack_id: str
    target_version: str


class PackStateRequest(StrictModel):
    actor: str | None = Field(default=None, max_length=200)
    superseded_by: str | None = None
    challenge_id: str | None = None
    nonce: str | None = None


class PackStateChallengeRequest(StrictModel):
    state: str = Field(pattern="^(published|superseded|retired|uninstalled)$")
    superseded_by: str | None = None
    ttl_seconds: int = Field(default=300, ge=1, le=900)


class ConfigureVendorRequest(StrictModel):
    factory_zip_path: str
    fixture_path: str | None = None


class ProjectionBuildRequest(StrictModel):
    force: bool = False


class Stage1UserLocksRequest(StrictModel):
    locks: list[dict[str, Any]] = Field(min_length=1, max_length=50)


class Stage1ResponseRequest(StrictModel):
    response_text: str = Field(min_length=1, max_length=2_000_000)
    prior_attempt_id: str | None = None


class Stage1ApproveCommitRequest(StrictModel):
    approved_by: str = Field(min_length=1, max_length=200)


class AIProviderConfigureRequest(StrictModel):
    enabled: bool = False
    provider_id: str = Field(default="deepseek", pattern="^(openai|deepseek|custom)$")
    endpoint: str | None = Field(default=None, max_length=2048)
    model: str = Field(default="deepseek-v4-flash", min_length=1, max_length=100)
    thinking_mode: str = Field(default="disabled", pattern="^(enabled|disabled)$")
    max_output_tokens: int = Field(default=16384, ge=512, le=32768)
    timeout_seconds: int = Field(default=120, ge=10, le=300)
    data_sharing_acknowledged: bool = False
    acknowledged_by: str | None = Field(default=None, max_length=200)


class AIProviderKeyRequest(StrictModel):
    api_key: str = Field(min_length=8, max_length=512)


class AIProviderRunRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")


class Stage2ChoiceRequest(StrictModel):
    kind: str
    effective_cl: int = Field(ge=0, le=20)
    record_id: str | None = None
    acquisition_channel: str = Field(min_length=1, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason_code: str | None = None
    reason: str | None = None


class Stage2ProposalRequest(StrictModel):
    schema_version: str = "TianxiaFoundry.Stage2AdvancementProposal.v2"
    expected_project_revision: int = Field(ge=0)
    expected_content_lock_hash: str = Field(pattern="^[a-f0-9]{64}$")
    target_cl: int = Field(ge=1, le=20)
    idempotency_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    choices: list[Stage2ChoiceRequest] = Field(min_length=1, max_length=300)


class Stage2ApproveRequest(StrictModel):
    approved_by: str | None = Field(default=None, max_length=200)
    challenge_id: str | None = None
    nonce: str | None = None


class ApprovalChallengeRequest(StrictModel):
    ttl_seconds: int = Field(default=300, ge=1, le=900)


class Stage2CommitRequest(StrictModel):
    confirm_atomic_commit: bool = True


class CombatResourceInitializationRequest(StrictModel):
    qi_current: int | None = None
    martial_focus_current: int | None = None
    provenance_kind: str | None = Field(default=None, max_length=80)
    provenance_id: str | None = Field(default=None, max_length=240)


class CombatDraftParticipantRequest(CombatResourceInitializationRequest):
    candidate_entry_id: str = Field(min_length=1, max_length=500)
    team_id: str | None = Field(default=None, max_length=240)


class CombatPreEncounterDraftPreviewRequest(StrictModel):
    participants: list[CombatDraftParticipantRequest] = Field(default_factory=list, max_length=32)
    battlefield_id: str | None = Field(default=None, max_length=500)
    battlefield_provenance_kind: str | None = Field(default=None, max_length=80)
    battlefield_provenance_id: str | None = Field(default=None, max_length=240)


class CombatPreEncounterDraftDiscardRequest(StrictModel):
    draft_id: str = Field(min_length=1, max_length=500)



class CombatFightParticipantRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=240)
    team_id: str = Field(min_length=1, max_length=240)
    qi_current: int = Field(default=0, ge=0, le=10000)
    martial_focus_current: int | None = Field(default=None, ge=0, le=10000)
    stamina_current: int = Field(default=0, ge=0, le=10000)
    resonance_current: int = Field(default=0, ge=0, le=10000)
    controller_mode: str = Field(default="MANUAL", pattern="^(MANUAL|SUGGESTED|LOCAL_AUTO|MANUAL_AI_BRIDGE|API_AUTO)$")
    token_asset_id: str | None = Field(default=None, max_length=500)
    footprint_width: int = Field(default=1, ge=1, le=20)
    footprint_height: int = Field(default=1, ge=1, le=20)
    placement: dict[str, int] | None = None


class CombatFightPreflightRequest(StrictModel):
    encounter_id: str = "encounter:mvp.cl5_2v2"
    display_name: str | None = Field(default=None, max_length=240)
    match_seed: str | None = Field(default=None, max_length=200)
    maximum_rounds: int = Field(default=20, ge=1, le=100)
    battlefield_id: str = Field(min_length=1, max_length=500)
    initiative_method: str = Field(default="DETERMINISTIC_ACCEPTED", pattern="^(DETERMINISTIC_ACCEPTED)$")
    grid_calibration: dict[str, Any] = Field(default_factory=dict)
    participants: list[CombatFightParticipantRequest] = Field(min_length=1, max_length=16)
    team_names: dict[str, str] = Field(default_factory=dict)


class CombatFightCreateRequest(CombatFightPreflightRequest):
    preflight_commitment: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=200)
    owner_confirmed: bool


class CombatControllerModeRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=240)
    controller_mode: str = Field(pattern="^(MANUAL|SUGGESTED|LOCAL_AUTO|MANUAL_AI_BRIDGE|API_AUTO)$")


class CombatCreateMatchRequest(StrictModel):
    encounter_id: str = "encounter:mvp.cl5_2v2"
    display_name: str | None = Field(default=None, max_length=240)
    match_seed: str | None = Field(default=None, max_length=200)
    control_modes: dict[str, str] = Field(default_factory=dict)
    maximum_rounds: int = Field(default=20, ge=1, le=100)


class CombatPixelRectRequest(StrictModel):
    x: int = Field(ge=0, le=100_000)
    y: int = Field(ge=0, le=100_000)
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)


class CombatVisualUploadRequest(StrictModel):
    original_filename: str = Field(default="combat-image", max_length=240)
    media_type: str = Field(default="", max_length=100)
    data_base64: str = Field(min_length=1, max_length=17_000_000)
    calibration_mode: str = Field(
        default="COVER_DECORATIVE",
        pattern="^(EXACT_PLAYABLE_RECT|COVER_DECORATIVE|CONTAIN_DECORATIVE)$",
    )
    playable_rect_pixels: CombatPixelRectRequest | None = None


class CombatPositionRequest(StrictModel):
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)


class CombatReactionDecisionRequest(StrictModel):
    checkpoint: str
    reactor_id: str
    reaction_source_id: str
    selection: str = Field(pattern="^(USE|DECLINE)$")
    spend: int = Field(default=0, ge=0, le=100)
    option_ids: list[str] = Field(default_factory=list, max_length=32)


class CombatIntentPayload(StrictModel):
    decision_id: str
    state_version: int = Field(ge=0)
    candidate_id: str
    actor_id: str
    target_ids: list[str] = Field(default_factory=list, max_length=32)
    destination: CombatPositionRequest | None = None
    option_ids: list[str] = Field(default_factory=list, max_length=32)


class CombatPreviewRequest(StrictModel):
    intent: CombatIntentPayload
    reaction_decisions: list[CombatReactionDecisionRequest] = Field(default_factory=list, max_length=16)


class CombatIntentSubmitRequest(CombatPreviewRequest):
    preview_id: str | None = Field(default=None, max_length=100)


class CombatLocalRunRequest(StrictModel):
    maximum_steps: int = Field(default=20, ge=1, le=100)


class CombatAIIntentValidateRequest(StrictModel):
    schema_name: str | None = Field(default=None, alias="schema")
    action_intent: CombatIntentPayload
    rationale: str | None = Field(default=None, max_length=1000)


class CombatAIIntentExecuteRequest(CombatAIIntentValidateRequest):
    validation_token: str = Field(min_length=8, max_length=100)

class CharacterCreationStartRequest(StrictModel):
    execution_mode: str = Field(pattern="^(MANUAL_CHAT|STANDARD_API|AUTO_FINALIZE_WHEN_CLEAN)$")
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")

class CharacterCreationManualResponseRequest(StrictModel):
    response_text: str = Field(min_length=1, max_length=2_000_000)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_attempt_id: str | None = None

class CharacterCreationPreferenceRequest(StrictModel):
    execution_mode: str = Field(pattern="^(MANUAL_CHAT|STANDARD_API|AUTO_FINALIZE_WHEN_CLEAN)$")

class CharacterCreationReviseRequest(StrictModel):
    owner_notes: str = Field(default="", max_length=4000)
