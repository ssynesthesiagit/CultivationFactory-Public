from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, StrictInt, StrictBool
from combat.limits import MAX_FIGHTERS_PER_SIDE


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
    gear_preference_ids: list[str] = Field(default_factory=list, max_length=6)
    # Seeded autogeneration: the seed alone makes every build choice, no AI.
    autogen_seed: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    canonical_sphere_ids: list[str] | None = None
    sphere_free_talent_grants: dict[str, str] | None = None
    ordinary_talent_ids: list[str] | None = None
    evidence_ids: list[ExactEvidenceRecordRequest] = Field(default_factory=list)
    background_route_ids: dict[str, Any] = Field(default_factory=dict)


class OwnerItemSpecRequest(StrictModel):
    """An item the owner makes on the Items tab (owner 2026-09-24)."""

    kind: str = Field(pattern="^(weapon|armour|wondrous|consumable)$")
    chassis_id: str | None = Field(default=None, max_length=200)
    grade: str | None = Field(default=None, max_length=40)
    material_id: str | None = Field(default=None, max_length=200)
    enchantment_ids: list[str] = Field(default_factory=list, max_length=12)
    enhancement_ids: list[str] = Field(default_factory=list, max_length=12)
    item_name: str | None = Field(default=None, max_length=200)
    custom_id: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=200)


class CustomItemsImportRequest(StrictModel):
    """Custom wondrous items or consumables: made on the Items tab or imported (e.g. written by an AI GM)."""

    items: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    source: str = Field(default="owner", max_length=40)


class OwnerItemChoicesRequest(StrictModel):
    kind: str = Field(pattern="^(weapon|armour)$")
    chassis_id: str = Field(min_length=1, max_length=200)
    grade: str = Field(min_length=1, max_length=40)
    material_id: str | None = Field(default=None, max_length=200)
    chosen_ids: list[str] = Field(default_factory=list, max_length=12)


class QuickBuildItemRequest(StrictModel):
    """One Quick Build character: a seed (no AI) or the local AI (owner 2026-09-24)."""

    route: str = Field(default="seeded", pattern="^(seeded|local_ai)$")
    seed: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    concept: str = Field(default="", max_length=2000)


class QuickBuildRequest(StrictModel):
    items: list[QuickBuildItemRequest] = Field(min_length=1, max_length=12)
    target_cl: int = Field(default=5, ge=1, le=20)
    power_band: str = Field(default="rival/boss", min_length=1, max_length=100)
    finalize: bool = True


class CharacterBuilderMethodCompatibilityRequest(StrictModel):
    """Canonical Path requirements for the owner compatibility check."""

    selected_path_ids: list[str] = Field(default_factory=list, max_length=3)


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
    provider_id: str = Field(default="deepseek", pattern="^(openai|deepseek|custom|local|lemonade|agent)$")
    endpoint: str | None = Field(default=None, max_length=2048)
    model: str = Field(default="deepseek-v4-flash", min_length=1, max_length=100)
    thinking_mode: str = Field(default="disabled", pattern="^(enabled|disabled)$")
    max_output_tokens: int = Field(default=16384, ge=512, le=32768)
    timeout_seconds: int = Field(default=120, ge=10, le=300)
    # The agent bridge makes no HTTP call, so it waits for an agent answer
    # instead of a provider timeout.  Absent means "keep the saved value".
    agent_wait_seconds: int | None = Field(default=None, ge=10, le=3600)
    data_sharing_acknowledged: bool = False
    acknowledged_by: str | None = Field(default=None, max_length=200)


class AIAgentClaimRequest(StrictModel):
    agent_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
    lease_seconds: int | None = Field(default=None, ge=30, le=3600)


class AIAgentAnswerRequest(StrictModel):
    agent_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
    agent_model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:+/~-]{0,99}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_text: str = Field(min_length=1)


class AIAgentRejectRequest(StrictModel):
    agent_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
    reason: str = Field(min_length=1, max_length=500)


class LocalAIDetectRequest(StrictModel):
    """Optional bounded port override used by deterministic local probes/tests."""

    ports: list[int] | None = Field(default=None, min_length=1, max_length=20)


class LocalAISelectRequest(StrictModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=100)
    provider_id: str = Field(default="local", pattern="^(local|lemonade)$")


class LocalAIManagedSelectRequest(StrictModel):
    model: str = Field(default="Qwen3-4B-GGUF", min_length=1, max_length=100)


class LocalAIPrepareRequest(StrictModel):
    model: str = Field(default="Qwen3-4B-GGUF", min_length=1, max_length=100)


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


class FinalCharacterApprovalChallengeRequest(StrictModel):
    """Only the bounded lifetime is caller-controlled for final review."""

    ttl_seconds: int = Field(default=300, ge=1, le=900)


class FinalCharacterApproveRequest(StrictModel):
    """Consume one server-issued final-character challenge."""

    challenge_id: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")
    nonce: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")


class FinalCharacterMaterializeRequest(StrictModel):
    """Select only a persisted server-issued review record."""

    review_record_id: str = Field(pattern=r"^final-review\.[0-9a-f]{64}$")


class GMAuthoringRatificationChallengeRequest(StrictModel):
    """Issue an exact-byte owner challenge for the current GM receipt."""

    ttl_seconds: int = Field(default=300, ge=1, le=900)


class GMAuthoringRatificationRequest(StrictModel):
    """Consume a server-issued GM ratification challenge."""

    receipt_id: str = Field(min_length=1, max_length=240, pattern=r"^gm-receipt\.[0-9a-f]{64}$")
    challenge_id: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")
    nonce: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")


class CandidateGMAuthoringApprovalChallengeRequest(StrictModel):
    """Issue an exact-byte owner challenge for a captured GM candidate."""

    ttl_seconds: int = Field(default=300, ge=1, le=900)


class CandidateGMAuthoringApprovalRequest(StrictModel):
    """Consume a server-issued candidate GM approval challenge."""

    challenge_id: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")
    nonce: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._:-]+$")


# Descriptive aliases keep the transport names discoverable to callers while
# retaining one strict schema definition for each mutating operation.
FinalCharacterApprovalRequest = FinalCharacterApproveRequest
FinalCharacterMaterializationRequest = FinalCharacterMaterializeRequest


class CustomTrainingSourceEnvelopeRequest(StrictModel):
    """The exact owner-authored custom training-source boundary.

    Semantic normalization remains in ``custom_training_source_authority``;
    this model only rejects malformed transport types and unknown fields before
    the request reaches that authority.
    """

    route_id: Literal[
        "selected_ai_custom_training_source",
        "owner_supplied_custom_training_source",
    ]
    owner_confirmation_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=8000)
    source_text: str = Field(min_length=1, max_length=65536)
    source_anchor: str = Field(min_length=1, max_length=512)
    access_mode: str = Field(min_length=1, max_length=200)
    training_types: list[str] = Field(min_length=1, max_length=3)
    target_record_ids: list[str] = Field(min_length=1, max_length=50)


class CustomTrainingSourceChallengeRequest(CustomTrainingSourceEnvelopeRequest):
    ttl_seconds: int = Field(default=300, ge=1, le=900)


class CustomTrainingSourceApprovalRequest(CustomTrainingSourceEnvelopeRequest):
    challenge_id: str = Field(min_length=1, max_length=240)
    nonce: str = Field(min_length=1, max_length=512)


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



class JourneyCreateRequest(StrictModel):
    project_ids: list[str] = Field(min_length=1, max_length=2 * MAX_FIGHTERS_PER_SIDE)
    arena_id: str
    positions: dict[str, dict[str, StrictInt]]
    base_paces: dict[str, StrictInt]
    loaded_paces: dict[str, StrictInt] | None = None
    control_modes: dict[str, Literal['MANUAL', 'LOCAL_AUTO']] | None = None


class JourneyActionRequest(StrictModel):
    revision: StrictInt = Field(ge=0)
    actor_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JourneyAutoRequest(StrictModel):
    revision: StrictInt = Field(ge=0)
    actor_id: str
    option_id: str | None = None


class JourneyCombatRequest(StrictModel):
    revision: StrictInt = Field(ge=0)
    teams: dict[str, str]
    positions: dict[str, dict[str, StrictInt]] | None = None
    maximum_rounds: StrictInt = Field(default=20, ge=1, le=100)


class JourneyResumeRequest(StrictModel):
    revision: StrictInt = Field(ge=0)
    effect_resolutions: dict[str, str] = Field(default_factory=dict,
        description="Explicit GM confirmation that the creature's untransferable encounter effects ended; "
                    "map each creature ID to a nonempty reason. Does not grant healing or resource recovery.")


class CombatFactoryMatchRequest(StrictModel):
    """A test fight with finished Factory characters (owner 2026-09-24)."""

    project_ids: list[str] = Field(min_length=1, max_length=MAX_FIGHTERS_PER_SIDE)
    opponent_actor_ids: list[str] | None = Field(default=None, max_length=MAX_FIGHTERS_PER_SIDE)
    neutral_actor_ids: list[str] | None = None
    control_modes: dict[str, str] | None = None
    match_seed: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=240)
    arena_id: str | None = Field(default=None, max_length=200)
    # Buffs each fighter cast before the fight (owner 2026-09-29), by actor or project id; a fighter left out gets the
    # AI's best two (combat/prefight.py).
    prefight: dict[str, list[str]] | None = None


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
    participants: list[CombatFightParticipantRequest] = Field(min_length=1, max_length=2 * MAX_FIGHTERS_PER_SIDE)
    team_names: dict[str, str] = Field(default_factory=dict)


class CombatFightCreateRequest(CombatFightPreflightRequest):
    preflight_commitment: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=200)
    owner_confirmed: bool


class CombatControllerModeRequest(StrictModel):
    ai_tier: Literal["TRICKY", "MASTERMIND"] | None = None
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
    reactions: list[dict[str, Any]] = Field(default_factory=list, max_length=40)

class CharacterCreationStartRequest(StrictModel):
    required_forged_design_ids: list[str] | None = Field(default=None, max_length=2)
    execution_mode: str = Field(pattern="^(MANUAL_CHAT|STANDARD_API|AUTO_FINALIZE_WHEN_CLEAN)$")
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    combat_ready: bool = False
    # Omitted requests retain the legacy full-plan route.  The DCC route is
    # only pinned here; its inactive activation gate is enforced server-side.
    controller_route: Literal[
        "LEGACY_FULL_PLAN",
        "DETERMINISTIC_CREATIVE_CONTROLLER",
    ] = "LEGACY_FULL_PLAN"

class CharacterCreationManualResponseRequest(StrictModel):
    response_text: str = Field(min_length=1, max_length=2_000_000)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_attempt_id: str | None = None

class CharacterCreationDecisionResolutionRequest(StrictModel):
    decision_id: str = Field(min_length=16, max_length=200)
    field: str = Field(min_length=1, max_length=240)
    slot_id: str | None = Field(default=None, max_length=120)
    # Decisions are typed operations over the immutable response projection.
    # ``replace_slot_value`` is the compatibility default for existing owner
    # clients; multi-value slots must provide an explicit target or use add /
    # remove / list replacement semantics server-side.
    operation: str = Field(
        default="replace_slot_value",
        pattern=r"^(replace_slot_value|replace_slot_list|add_slot_value|remove_slot_value|set_field|set_milestone_choice)$",
    )
    target_value: Any = None
    value: Any
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

class CharacterCreationDescriptiveFieldsRequest(StrictModel):
    name: str | None = Field(default=None, max_length=240)
    title: str | None = Field(default=None, max_length=120)
    concept: str | None = Field(default=None, max_length=12000)

class CharacterCreationPreferenceRequest(StrictModel):
    execution_mode: str = Field(pattern="^(MANUAL_CHAT|STANDARD_API|AUTO_FINALIZE_WHEN_CLEAN)$")

class CharacterCreationReviseRequest(StrictModel):
    owner_notes: str = Field(default="", max_length=4000)


class CharacterCreationEditBriefPrepareRequest(StrictModel):
    owner_notes: str = Field(default="", max_length=4000)
    brief: dict[str, Any] = Field(default_factory=dict)
    user_locks: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class CharacterCreationEditBriefSubmitRequest(StrictModel):
    edit_id: str = Field(min_length=8, max_length=200)


# Tabletop (owner 2026-09-25): human-played combat on a MapTool-style table.
class TabletopSettingsRequest(StrictModel):
    sources: list[str] = Field(min_length=1, max_length=64)
    actor_id: str = Field(default="", max_length=240)
    request_id: str = Field(default="", max_length=80)


class TabletopBreakthroughRequest(StrictModel):
    """A successful breakthrough recorded at the table, at a Realm level (strict integer)."""
    cl: StrictInt


class TabletopFeatureUseRequest(StrictModel):
    """A Path feature the table has seen this character use (closes a printed build-choice window).

    Only a GM records a use that happened away from this table, so ``gm`` must be set."""
    feature_id: str = Field(min_length=1, max_length=160)
    gm: bool = False


class TabletopGoldenCoreRequest(StrictModel):
    """A Golden Core Form. The slot is a strict integer and is never coerced."""
    form: str = Field(default="", max_length=40)
    slot: StrictInt


class TabletopSeatRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=240)
    control: str = Field(pattern="^(MANUAL|AI|MODEL)$")
    provider_id: str | None = Field(default=None, min_length=1, max_length=80)
    style: str | None = Field(default=None, pattern="^(choices|full)$")


class TabletopCompositionRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=240)
    decision_id: str = Field(min_length=1, max_length=240)
    state_version: int = Field(ge=0)
    sources: list[str] = Field(min_length=1, max_length=64)
    source_definition_id: str = Field(min_length=1, max_length=240)
    request_id: str = Field(pattern="^[a-zA-Z0-9_-]{1,80}$")


class TabletopMenuRead(StrictModel):
    """The arguments of the client's own table read (GET .../state), repeated so a free choice answers with that state."""
    fog: StrictBool = False
    fog_view: str | None = Field(default=None, max_length=40)
    fog_actor_ids: list[str] = Field(default_factory=list, max_length=64)
    compact: StrictBool = False


class TabletopActRequest(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    decision_id: str = Field(min_length=1, max_length=240)
    state_version: int = Field(ge=0)
    after: int = Field(default=0, ge=0)
    # Repeat explicit action selections unchanged when answering a saved Ask me prompt.
    option_ids: list[str] | None = None
    # Cancel only: the attempt id printed beside the aim's own Cancel guard (stale tabs).
    pending_id: str | None = None
    composition: TabletopCompositionRequest | None = None
    # Answers to the Ask me reaction prompts this action raised so far (step 16): ReactionDecision rows.
    reactions: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    # A free choice (an Options-panel setting) asks for its committed state with the menu, read as the client's own
    # state read would be, so an unchanged menu is updated in place without a second read.
    menu_read: TabletopMenuRead | None = None


class TabletopPlaybackRequest(StrictModel):
    paused: StrictBool


class TabletopDestinationRequest(StrictModel):
    decision_id: str = Field(min_length=1, max_length=240)
    state_version: int = Field(ge=0)
    actor_id: str = Field(min_length=1, max_length=240)
    destination: dict[str, StrictInt]
    # Native material routes publish additional modes (for example swim).
    # The engine validates ownership and exact-path legality, as for route previews.
    movement_mode: str = 'walk'


class TabletopRoutePreviewRequest(StrictModel):
    decision_id: str = Field(min_length=1, max_length=240)
    state_version: int = Field(ge=0)
    actor_id: str = Field(min_length=1, max_length=240)
    waypoints: list[dict[str, StrictInt]] = Field(min_length=2, max_length=1000)
    movement_mode: str = 'walk'


class TabletopRouteCommitRequest(TabletopRoutePreviewRequest):
    candidate_id: str = Field(min_length=1, max_length=120)
    after: int = Field(default=0, ge=0)
    reactions: list[dict[str, Any]] = Field(default_factory=list, max_length=40)


class TabletopStepRequest(StrictModel):
    after: int = Field(default=0, ge=0)
    reactions: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    decision_id: str | None = Field(default=None, min_length=1, max_length=240)
    state_version: int | None = Field(default=None, ge=0)


class TabletopMapRequest(StrictModel):
    map: dict[str, Any]


class TabletopTeamPresetRequest(StrictModel):
    preset: dict[str, Any]


class TabletopButtonsRequest(StrictModel):
    buttons: list[dict[str, Any]] = Field(default_factory=list, max_length=60)
    layout: dict[str, Any] = Field(default_factory=dict)


class TabletopNameRequest(StrictModel):
    """The name a finished character goes by at the table (owner 2026-09-27); empty restores the sheet's own."""

    display_name: str | None = Field(default=None, max_length=80)


class TabletopAbilityRequest(StrictModel):
    """An ability-score change at the table: reason gm_respec (all six scores, point-buy) or level_increase (deltas at CL 4+)."""

    reason: str = Field(pattern="^(gm_respec|level_increase)$")
    changes: dict[str, int] = Field(min_length=1, max_length=6)
    cl: int = Field(ge=1, le=20)
    note: str = Field(default="", max_length=240)
    gm: bool = False


class TabletopMethodRequest(StrictModel):
    """A completed campaign opportunity, not a combat/daily loadout switch."""
    method_id: str = Field(min_length=1, max_length=100)
    source: str = Field(default="", pattern="^(|teacher|scripture|inheritance|sect permission|ruin|item|failure route|gm)$")
    note: str = Field(default="", max_length=500)
    opportunity: str = Field(default="", max_length=100)
    completed: bool = False
    gm: bool = False
    save: bool = False


class TabletopLevelChoice(StrictModel):
    """Only choices, never authored statistics, for the next table level."""

    cl: int = Field(ge=2, le=20)
    talent_ids: list[str] = Field(default_factory=list, max_length=4)
    subpaths: dict[str, str] = Field(default_factory=dict, max_length=3)
    feature_choices: dict[str, str] = Field(default_factory=dict, max_length=40)
    access_confirmed: bool = False
    advancement: str = Field(default="", pattern="^(|ability|insight)$")
    changes: dict[str, int] = Field(default_factory=dict, max_length=6)
    insight_id: str = Field(default="", max_length=200)
    insight_ability: str = Field(default="", max_length=3)
    insight_choice: str = Field(default="", max_length=240)
    foundation_id: str = Field(default="", max_length=200)
    foundation_initial_stage: str | None = Field(default=None, max_length=80)
    add_path_id: str = Field(default="", max_length=200)
    add_access: str = Field(default="", pattern="^(|primary_method|phb|gm)$")
    add_source_id: str = Field(default="", max_length=200)
    add_confirmed: bool = False


class TabletopLevelRequest(TabletopLevelChoice):
    """One or several consecutive levels, committed atomically."""

    levels: list[TabletopLevelChoice] = Field(default_factory=list, max_length=19)


class TabletopAdvanceRequest(StrictModel):
    """Learn a Sphere or talent at the table (owner 2026-09-27); ``gm`` adds it past the rules, marked as a GM grant."""

    kind: str = Field(pattern="^(sphere|talent|forged)$")
    record_id: str = Field(min_length=1, max_length=200)
    gm: bool = False
    learning_choices: dict[str, str] = Field(default_factory=dict)
    source: str = Field(default="campaign", pattern="^(campaign|manual|jade tablet)$")


class TabletopAdvanceRemoveRequest(StrictModel):
    """Remove a recorded gain; adding abilities uses its separate validated route."""

    kind: str = Field(pattern="^(sphere|talent|forged|ability|insight|immortal_art)$")
    record_id: str = Field(min_length=1, max_length=200)


class TabletopInsightRequest(StrictModel):
    record_id: str = Field(min_length=1, max_length=200)
    note: str = Field(default="From play", min_length=1, max_length=240)
    choice: str = Field(default="", max_length=240)
    gm: bool = False


class TabletopImmortalArtDesign(StrictModel):
    name: str = Field(default="", max_length=80)
    source_record_id: str = Field(min_length=1, max_length=200)
    aspect_id: str | None = Field(default=None, max_length=200)
    factor_ids: list[str] = Field(default_factory=list, max_length=12)
    burdens: list[str] = Field(default_factory=list, max_length=12)


class TabletopImmortalArtProof(StrictModel):
    die: int = Field(ge=1, le=20, strict=True)
    research_hours: int = Field(ge=0, strict=True)
    materials_gp: int = Field(ge=0, strict=True)


class TabletopImmortalArtRequest(StrictModel):
    design: TabletopImmortalArtDesign
    note: str = Field(default="From play", min_length=1, max_length=240)
    proof: TabletopImmortalArtProof | None = None
    save: bool = False


class TabletopForgeDesign(StrictModel):
    """A Forged Technique design (PHB ch. 18): Base Form, Primary and Secondary Sphere Effects, Augments, Drawbacks."""

    name: str | None = Field(default=None, max_length=80)
    intent: str | None = Field(default=None, max_length=600)
    base_form: str = Field(min_length=1, max_length=40)
    primary_talent_id: str = Field(min_length=1, max_length=200)
    secondary_talent_ids: list[str] = Field(default_factory=list, max_length=4)
    augment_ids: list[str] = Field(default_factory=list, max_length=12)
    drawback_ids: list[str] = Field(default_factory=list, max_length=10)
    choices: dict[str, str] = Field(default_factory=dict)


class TabletopForgeRequest(StrictModel):
    design: TabletopForgeDesign
    gm: bool = False
    save: bool = False
    source: str = Field(default="campaign", pattern="^(campaign|manual|jade tablet)$")


class TabletopTokenRequest(StrictModel):
    """A circle token the sheet cropped (owner 2026-09-27): a PNG as base64 (a data URL is accepted)."""

    data_base64: str = Field(min_length=16, max_length=18_000_000)
    circle: dict[str, float] | None = None  # where the token's circle sat on the picture: {x, y, r} as fractions of its width


class TabletopTokenGenerateRequest(StrictModel):
    """Make a portrait with the owner's local Anima Studio: their own words for the look, and an optional seed."""

    look: str | None = Field(default=None, max_length=300)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    framing: str = Field(default="portrait", pattern="^(portrait|upper|full)$")


class TabletopAttunementRequest(StrictModel):
    """The treasures a character is attuned to (owner 2026-09-28), by the keys the sheet's Items tab lists; null returns
    to the creation plan."""

    attuned: list[str] | None = Field(default=None, max_length=20)


class TabletopEquipmentRequest(StrictModel):
    """Items the character leaves behind for its fights (owner 2026-09-27), by the keys the sheet lists."""

    left_behind: list[str] = Field(default_factory=list, max_length=200)


class TabletopSummonsRequest(StrictModel):
    """How many of each summoned creature a character brings, and a Tamer's beasts (owner 2026-09-27)."""

    counts: dict[str, int] = Field(default_factory=dict)
    beasts: list[str] | None = Field(default=None, max_length=10)


class TabletopSpheresRequest(StrictModel):
    """Spheres granted to a finished character for combat (owner 2026-09-26)."""

    granted_spheres: list[str] = Field(default_factory=list, max_length=20)


class TabletopReactionsRequest(StrictModel):
    """Which reactions a character uses, most important first, and which never (owner 2026-09-26);
    mode "auto" lets combat decide. ``hold`` is the first version's single held reaction."""

    mode: Literal["auto", "custom", "ask"] = "auto"
    order: list[str] = Field(default_factory=list, max_length=60)
    off: list[str] = Field(default_factory=list, max_length=60)
    hold: str | None = Field(default=None, max_length=240)
    # A "Choose one" reaction's picked option, by reaction id (step 14); kept in either mode.
    options: dict[str, int] = Field(default_factory=dict)


class TabletopPoweringRequest(StrictModel):
    """Which Path pool pays each choosable ability (owner 2026-09-25, Q19): action id -> pool name."""

    choices: dict[str, str] = Field(default_factory=dict, max_length=200)


class CombatWorldFactRequest(StrictModel):
    state_version: int = Field(ge=0)
    payload: dict[str, Any]
