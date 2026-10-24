from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
import shutil
import threading
import time
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from character_creation.path_attainment import factory_support_blocker

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)
_COMBAT_AC_FAILURES: set[tuple[str, str]] = set()
_COMBAT_AC_FAILURES_LOCK = threading.Lock()

from app.core import (
    APP_STATUS,
    APP_VERSION,
    EXPECTED_GM_SCREEN_HASH,
    GM_SCREEN_VERSION,
    Database,
    FoundryError,
    Settings,
    canonical_json,
    configure_timing_logger,
    resolve_inside,
    sha256_file,
    sha256_json,
    utcnow,
)
from app.static_build import BUILD_HEADER, StaticBuild
from app.models import (
    JourneyCreateRequest, JourneyActionRequest, CombatWorldFactRequest, JourneyAutoRequest, JourneyCombatRequest, JourneyResumeRequest,
    JourneyWorldFactRequest, JourneySceneEndRequest,
    TabletopSeatRequest,
    TabletopPlaybackRequest,
    TabletopActRequest,
    TabletopSettingsRequest,
    TabletopCompositionRequest,
    TabletopRoutePreviewRequest,
    TabletopDestinationRequest,
    TabletopRouteCommitRequest,
    TabletopButtonsRequest,
    TabletopMapRequest,
    TabletopTeamPresetRequest,
    TabletopPoweringRequest,
    TabletopReactionsRequest,
    TabletopSpheresRequest,
    TabletopSummonsRequest,
    TabletopAbilityRequest,
    TabletopLevelRequest,
    TabletopMethodRequest,
    TabletopInsightRequest,
    TabletopImmortalArtRequest,
    TabletopAdvanceRequest,
    TabletopAdvanceRemoveRequest,
    TabletopAttunementRequest,
    TabletopEquipmentRequest,
    TabletopForgeRequest,
    TabletopNameRequest,
    TabletopTokenGenerateRequest,
    TabletopTokenRequest,
    TabletopStepRequest,
    AIAgentAnswerRequest,
    AIAgentClaimRequest,
    AIAgentRejectRequest,
    AIProviderConfigureRequest,
    AIProviderKeyRequest,
    AIProviderRunRequest,
    LocalAIDetectRequest,
    LocalAISelectRequest,
    LocalAIManagedSelectRequest,
    LocalAIPrepareRequest,
    ApproveRequest,
    ConfigureVendorRequest,
    CreateProjectRequest,
    CharacterSheetCreateRequest,
    CharacterBuilderMethodCompatibilityRequest,
    CanonicalCatalogChoiceLockRequest,
    NS1RStateUpdateRequest,
    NS1RPrimaryMethodRequest,
    NS1RTargetCLRequest,
    NS1RAccessSourcesRequest,
    NS1RPathAttainmentRequest,
    NS1RAPAllocationRequest,
    NS1RResourceRequest,
    NS1RSubpathRequest,
    NS1RFoundationRequest,
    NS1RCompatibilityRequest,
    NS1RBackgroundValidationRequest,
    NS1RMigrationPreviewRequest,
    CanonicalCreatorProjectionRequest,
    DraftEventRequest,
    ExportRequest,
    OwnerArtifactStageRequest,
    OwnerArtifactSaveAsRequest,
    FoundationHandoffPrepareRequest,
    MigrationPreviewRequest,
    PackageRequest,
    PackageChallengeRequest,
    PackStateRequest,
    PackStateChallengeRequest,
    ProjectionBuildRequest,
    Stage1UserLocksRequest,
    Stage1ResponseRequest,
    Stage1ApproveCommitRequest,
    Stage2ProposalRequest,
    Stage2ApproveRequest,
    ApprovalChallengeRequest,
    CustomTrainingSourceChallengeRequest,
    CustomTrainingSourceApprovalRequest,
    Stage2CommitRequest,
    FinalCharacterApprovalChallengeRequest,
    FinalCharacterApproveRequest,
    FinalCharacterMaterializeRequest,
    GMAuthoringRatificationChallengeRequest,
    GMAuthoringRatificationRequest,
    CandidateGMAuthoringApprovalChallengeRequest,
    CandidateGMAuthoringApprovalRequest,
    CombatResourceInitializationRequest,
    CombatPreEncounterDraftPreviewRequest,
    CombatPreEncounterDraftDiscardRequest,
    CombatCreateMatchRequest,
    CombatFactoryMatchRequest,
    QuickBuildRequest,
    OwnerItemSpecRequest,
    OwnerItemChoicesRequest,
    CustomItemsImportRequest,
    CombatControllerModeRequest,
    CombatFightPreflightRequest,
    CombatFightCreateRequest,
    CombatVisualUploadRequest,
    CombatPreviewRequest,
    CombatIntentSubmitRequest,
    CombatLocalRunRequest,
    CombatAIIntentValidateRequest,
    CombatAIIntentExecuteRequest,
    CharacterCreationStartRequest,
    CharacterCreationManualResponseRequest,
    CharacterCreationDecisionResolutionRequest,
    CharacterCreationDescriptiveFieldsRequest,
    CharacterCreationPreferenceRequest,
    CharacterCreationReviseRequest,
    CharacterCreationEditBriefPrepareRequest,
    CharacterCreationEditBriefSubmitRequest,
)
from catalog.service import CatalogService
from canonical_catalog import CanonicalCatalogAuthorityService
from character_builder.service import CharacterBuilderService
from character_library_archive import CharacterLibraryArchiveService
from project_store.deletion_queue import ProjectDeletionQueue, hidden_project_ids, project_matches
from character_sheet import CharacterSheetService
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from portable_character.service import MAX_ARCHIVE_BYTES
from factory_authoring import FactoryAuthoringWorkspaceService, FinalCharacterWorkflowService
from content_packs.service import ContentPackManager
from project_store.service import ProjectStore
from projector.service import ProjectionService, ARTIFACT_MEDIA
from vendor_adapter.service import FactoryAdapter
from contracts.registry import SchemaRegistry
from stage1.service import Stage1ClipboardService
from stage2.service import PROPOSAL_V2, Stage2AdvancementService
from security.local_identity import BoundPrincipalProvider, PrincipalProvider, ProcessPrincipalProvider
from security.integrity import IntegrityService
from ai_provider.service import AIProviderService
from character_creation import CharacterCreationExecutionService
from character_creation.service import (
    GM_CANDIDATE_AUTHORING_NEXT_ACTION,
    gm_candidate_authoring_gate,
    gm_candidate_authoring_gate_blocker,
)
from character_creation.delegated_choice_authority import legal_slot_replacement_ids
from character_creation.owner_decision_authority import enrich_milestone_details
from creation_training_authority import canonical_background_package_ids
from character_creation.production_release import CharacterProductionReleaseAdapter
from foundation_adapter import (
    FoundationHandoffError,
    build_foundation_pack_plan,
    load_foundation_handoff,
    load_pinned_core_foundation_authorities,
    write_deterministic_foundation_pack,
)
from combat.gate5_service import DEFAULT_FACTORY_ARENA, CombatService, CombatServiceError
from product_bootstrap import NATIVE_WINDOWS_STATUS, ProductReadinessService
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import PATH_DISPLAY_NAMES


_LOOPBACK_ORIGIN_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}
_FINAL_CHARACTER_ROUTE_MARKER = "/factory-workspace/final-character/"
_ABSOLUTE_PATH_IN_ERROR = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^/\s\"'<>]+/)*[^/\s\"'<>]+(?:/[^\s\"'<>]*)?")
_WINDOWS_PATH_IN_ERROR = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'<>]+")


def _is_final_character_route(request: Request) -> bool:
    return request.url.path.startswith("/api/characters/") and _FINAL_CHARACTER_ROUTE_MARKER in request.url.path


def _redact_final_character_error_value(value: Any) -> Any:
    """Remove server filesystem paths from a final-character API error."""

    if isinstance(value, dict):
        return {
            _redact_final_character_error_value(key) if isinstance(key, str) else key: _redact_final_character_error_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_final_character_error_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_final_character_error_value(item) for item in value)
    if not isinstance(value, str):
        return value
    if value == "/":
        return "<server-path>"
    redacted = _WINDOWS_PATH_IN_ERROR.sub("<server-path>", value)
    return _ABSOLUTE_PATH_IN_ERROR.sub("<server-path>", redacted)


def _choice_snapshot_api_binding(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    value = snapshot if isinstance(snapshot, dict) else {}
    return {
        "schema": "TianxiaFoundry.TypedProjectChoiceSnapshotBinding.v1",
        "source_schema": value.get("schema"),
        "canonical_project_id": value.get("canonical_project_id"),
        "project_revision": value.get("project_revision"),
        "content_lock_hash": value.get("content_lock_hash"),
        "event_stream": value.get("event_stream"),
        "display_name_content": value.get("display_name_content"),
        "snapshot_sha256": value.get("snapshot_sha256"),
        "typed_lock_count": len(value.get("typed_locks") or []),
        "exact_snapshot_download_available": bool(value),
    }


_OWNER_PATH_NAMES = dict(PATH_DISPLAY_NAMES)
_OWNER_PROVENANCE_LABELS = {
    "owner": "Owner",
    "ai": "AI proposed",
    "automatic": "Automatic",
    "needs_owner": "Needs owner decision",
    "deferred": "Automatic",
    "unavailable": "Unavailable",
}
_OWNER_FREE_TALENT_ROUTES = frozenset({
    "free_sphere_talent_grant",
    "new_sphere_bonus_talent_acquisition",
    "ai_bootstrap_talent_acquisition",
    "sect_trial_talent_acquisition",
})
_OWNER_ORDINARY_TALENT_ROUTES = frozenset({
    "ordinary_learned_or_trained",
    "level_talent_acquisition",
    "talent_acquisition",
})


def _owner_record_name(row: Any) -> str | None:
    if isinstance(row, str):
        return row.strip() or None
    if not isinstance(row, dict):
        return None
    for key in ("display_name", "name", "canonical_name", "title", "label", "talent_name", "sphere_name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _owner_record_description(row: Any) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in (
        "full_description", "full_description_text", "player_rules_text",
        "one_line_description", "short_description", "description", "summary",
        "effect", "full_effect",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _owner_record_map(snapshot: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    sections = snapshot.get("selected_record_sections") or {}
    if not isinstance(sections, dict):
        return result
    for rows in sections.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_id = row.get("record_id")
            name = _owner_record_name(row)
            if isinstance(record_id, str) and name:
                result[record_id] = name
    return result


def _owner_choice_name(
    slot_id: str,
    choice_id: Any,
    *,
    choice_metadata: dict[str, Any],
    record_names: dict[str, str],
) -> str:
    if not isinstance(choice_id, str) or not choice_id:
        return "No proposal supplied"
    if choice_id in _OWNER_PATH_NAMES:
        return _OWNER_PATH_NAMES[choice_id]
    choices = choice_metadata.get(slot_id) or {}
    choices = choices if isinstance(choices, dict) else {}
    row = choices.get(choice_id)
    name = _owner_record_name(row)
    if name:
        return name
    return record_names.get(choice_id) or "Selected choice"


_OWNER_DECISION_SLOT_LABELS = {
    "path_choice": "a Path",
    "subpath_choice": "a Path-owned Subpath",
    "method_choice": "a Method",
    "foundation_choice": "a Foundation",
    "sphere_priorities": "a Sphere priority",
    "advancement_skeleton": "a Talent priority",
    "insight_priorities": "an Insight priority",
    "item_priorities": "an Item priority",
    "origin_insight_choice": "an Origin Insight",
    "background_choice": "a Background",
    "background_sphere_choice": "a Background Sphere",
    "background_talent_choice": "a Background Talent",
    "ordinary_talent_by_cl": "an ordinary Talent",
}

_OWNER_FIRST_SUBPATH_SELECTION_CL = 3


def _owner_subpath_decision_not_yet_due(
    *,
    request: dict[str, Any],
    final_plan: dict[str, Any],
    parsed_plan: dict[str, Any],
    selected_by_slot: dict[str, Any],
) -> bool:
    """Recognize the authenticated generic pre-Subpath milestone.

    A delegated CL1/CL2 response may deliberately defer ``subpath_choice``;
    that is a legal future milestone, not an owner decision.  Keep this gate
    narrow: preferred v3 delegated responses must carry the frozen Stage 1
    zero-minimum slot and the canonical response must be non-historical.  The
    latter preserves strict owner review for legacy/historical and fixture
    representations even when their target CL is small.
    """
    target_cl = final_plan.get("target_cl")
    if type(target_cl) is not int or not 0 < target_cl < _OWNER_FIRST_SUBPATH_SELECTION_CL:
        return False
    if request.get("schema") != "TianxiaFoundry.CharacterCreationPlanRequest.v3":
        return False
    if request.get("required_plan_schema") != "TianxiaFoundry.DelegatedSelectionIntentResponse.v1":
        return False
    if any(isinstance(value, str) and value for value in (selected_by_slot.get("subpath_choice") or [])):
        return False
    envelope = request.get("delegated_choice_envelope")
    if not isinstance(envelope, dict):
        return False
    stage1_envelope = request.get("stage1_prompt")
    stage1_envelope = stage1_envelope.get("envelope") if isinstance(stage1_envelope, dict) else None
    slots = stage1_envelope.get("decision_slots") if isinstance(stage1_envelope, dict) else None
    subpath_slot = next(
        (row for row in slots or [] if isinstance(row, dict) and row.get("slot_id") == "subpath_choice"),
        None,
    )
    if not isinstance(subpath_slot, dict) or subpath_slot.get("min_selections") != 0:
        return False
    canonical_intent = parsed_plan.get("canonical_selection_intent")
    if not isinstance(canonical_intent, dict) or canonical_intent.get("response_form") != "preferred":
        return False
    if canonical_intent.get("historical_stage2_rows"):
        return False
    stage1_response = parsed_plan.get("stage1_response")
    stage1_response = stage1_response if isinstance(stage1_response, dict) else {}
    response_payload = stage1_response.get("response_payload")
    response_payload = response_payload if isinstance(response_payload, dict) else {}
    subpath_decision = next(
        (
            row for row in response_payload.get("decisions") or []
            if isinstance(row, dict) and row.get("slot_id") == "subpath_choice"
        ),
        None,
    )
    return (
        isinstance(subpath_decision, dict)
        and subpath_decision.get("state") == "deferred_with_reason"
        and not subpath_decision.get("choice_ids")
    )


def _owner_decision_slot_id(details: Any) -> str | None:
    """Find the owner-facing choice slot named by a blocker field."""
    if not isinstance(details, dict):
        return None
    explicit = details.get("slot_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    field = details.get("field")
    if not isinstance(field, str):
        return None
    normalized = field.strip()
    candidates = sorted(_OWNER_DECISION_SLOT_LABELS, key=len, reverse=True)
    for slot_id in candidates:
        if normalized == slot_id or normalized.startswith(f"{slot_id}.") or f".{slot_id}." in f".{normalized}.":
            return slot_id
    return None


def _owner_progression_sort_key(value: Any) -> tuple[int, int | str]:
    """Order proposed progression by cultivation level, never text order."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return (1, str(value))
    return (0, numeric)


def _owner_decision_choice_ids(
    slot_id: str | None,
    details: dict[str, Any],
    *,
    choice_metadata: dict[str, Any],
    allowed_choice_ids_by_slot: dict[str, Any],
) -> list[Any]:
    """Return bounded-decision candidates without treating response IDs as owner text."""
    for key in (
        "allowed_choice_ids",
        "offered_choice_ids",
        "available_choice_ids",
        "available_path_ids",
        "allowed_path_ids",
    ):
        values = details.get(key)
        if isinstance(values, list):
            return values
    if slot_id:
        allowed = allowed_choice_ids_by_slot.get(slot_id)
        if isinstance(allowed, list):
            return allowed
        choices = choice_metadata.get(slot_id)
        if isinstance(choices, dict):
            return list(choices)
    for key in ("allowed_abilities", "required_abilities", "allowed_amounts"):
        values = details.get(key)
        if isinstance(values, list):
            return values
    return []


def _owner_decision_choices(
    slot_id: str | None,
    details: dict[str, Any] | None,
    *,
    choice_metadata: dict[str, Any],
    allowed_choice_ids_by_slot: dict[str, Any],
    record_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Project every legal alternative with its stable resolving value."""
    details = details if isinstance(details, dict) else {}
    typed_choices = None
    for key in ("legal_choices", "allowed_milestone_choices", "allowed_choices"):
        if isinstance(details.get(key), list):
            typed_choices = details[key]
            break
    choice_ids = _owner_decision_choice_ids(
        slot_id,
        details,
        choice_metadata=choice_metadata,
        allowed_choice_ids_by_slot=allowed_choice_ids_by_slot,
    ) if typed_choices is None else typed_choices
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    choices = choice_metadata.get(slot_id or "") if slot_id else {}
    choices = choices if isinstance(choices, dict) else {}
    for choice_id in choice_ids:
        choice_record = choice_id if isinstance(choice_id, dict) else {}
        stable_value = choice_record.get("value", choice_id) if isinstance(choice_record, dict) else choice_id
        if isinstance(stable_value, str) and slot_id:
            choice = choices.get(stable_value) or {}
            label = choice_record.get("name") or choice_record.get("label") or _owner_choice_name(slot_id, stable_value, choice_metadata=choice_metadata, record_names=record_names)
            description = choice_record.get("description") or _owner_record_description(choice)
        else:
            label = choice_record.get("name") or choice_record.get("label") or _owner_record_name(stable_value) or str(stable_value)
            description = choice_record.get("description")
        label = label.strip() if isinstance(label, str) else "Selected choice"
        stable_key = canonical_json(stable_value)
        if not label or stable_key in seen:
            continue
        seen.add(stable_key)
        option: dict[str, Any] = {
            "choice_id": choice_record.get("choice_id", stable_value),
            "value": deepcopy(stable_value),
            "name": label,
            "operation": choice_record.get("operation") or details.get("operation") or "replace_slot_value",
        }
        target_value = choice_record.get("target_value", details.get("target_value"))
        if target_value is not None:
            option["target_value"] = deepcopy(target_value)
        if description:
            option["description"] = description
        result.append(option)
    return result


def _owner_milestone_decision_details(
    details: dict[str, Any],
    *,
    envelope: dict[str, Any],
    proposal_bounded: dict[str, Any],
    proposal_acquisition: dict[str, Any],
    proposal_selected_by_slot: dict[str, Any] | None = None,
    choice_metadata: dict[str, Any],
    record_names: dict[str, str],
    authority_by_milestone: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add source-backed milestone controls to a real unresolved blocker.

    Stage 2 publishes the milestone's allowed event kinds, while the frozen
    Insight authority publishes each legal Insight/ability parameter.  This
    bridges those two authoritative surfaces into explicit owner operations;
    it never invents ASI deltas when the Path feature did not publish them.
    """
    enriched = enrich_milestone_details(
        details,
        envelope=envelope,
        proposal_bounded=proposal_bounded,
        proposal_acquisition=proposal_acquisition,
        proposal_selected_by_slot=proposal_selected_by_slot,
        authority_by_milestone=authority_by_milestone,
    )
    # Preserve the API's display-name resolver for historical envelopes whose
    # choice records did not carry a human-readable name.  The values and
    # legal set come from the shared authority builder above.
    for choice in enriched.get("legal_choices") or []:
        if not isinstance(choice, dict):
            continue
        value = choice.get("value") if isinstance(choice.get("value"), dict) else {}
        insight_id = value.get("insight_id")
        if isinstance(insight_id, str):
            ability = (value.get("parameters") or {}).get("ability")
            base = _owner_choice_name(
                "insight_priorities",
                insight_id,
                choice_metadata=choice_metadata,
                record_names=record_names,
            )
            choice["name"] = f"{base}{f' — {ability} +1' if ability else ''}"
    return enriched


def _owner_decision_id(
    run: dict[str, Any],
    *,
    field: str,
    slot_id: str | None,
    operation: str = "replace_slot_value",
    blocker_sha256: str | None = None,
) -> str:
    request = run.get("request") if isinstance(run.get("request"), dict) else {}
    response = run.get("response") if isinstance(run.get("response"), dict) else {}
    binding = {
        "run_id": run.get("run_id"),
        "field": field,
        "slot_id": slot_id,
        "operation": operation,
        "blocker_sha256": blocker_sha256,
        "request_sha256": request.get("request_sha256"),
        "response_sha256": response.get("response_sha256"),
        "content_lock_hash": request.get("content_lock_hash"),
    }
    return "cg1.decision." + sha256_json(binding)[:32]


def _owner_decision_item(
    *,
    slot_id: str | None,
    details: dict[str, Any] | None,
    message: str,
    proposed: Any,
    choice_metadata: dict[str, Any],
    allowed_choice_ids_by_slot: dict[str, Any],
    record_names: dict[str, str],
) -> dict[str, Any]:
    """Build the complete owner contract for one genuine unresolved decision."""
    details = details if isinstance(details, dict) else {}
    field = details.get("field") or slot_id or "owner decision"
    field = str(field)
    operation = str(details.get("operation") or details.get("decision_operation") or "replace_slot_value")
    choices = _owner_decision_choices(
        slot_id,
        details,
        choice_metadata=choice_metadata,
        allowed_choice_ids_by_slot=allowed_choice_ids_by_slot,
        record_names=record_names,
    )
    all_choice_ids = _owner_decision_choice_ids(
        slot_id,
        details,
        choice_metadata=choice_metadata,
        allowed_choice_ids_by_slot=allowed_choice_ids_by_slot,
    )
    total_choice_count = len({str(value) for value in all_choice_ids if value not in (None, "")})
    is_descriptive = field in {"identity.name", "concept"} or field.startswith("owner_descriptive_fields.")
    if is_descriptive:
        action = "Accept / Save identity wording"
        target_step = 4
        surface = "Character identity wording fields in Proposal review"
    elif choices:
        # A select is only honest when the same frozen values are accepted by
        # the bound resolver.  Keep this action local to the review card so the
        # owner is never sent back to replace a response that already contains
        # a legal proposal.
        action = "Apply decision and rebuild"
        target_step = 4
        surface = "This review card — the Factory will revalidate the selected legal value"
    else:
        action = "Replace Response (recovery)"
        target_step = 3
        surface = "AI route → response transfer — frozen authority published no direct legal value for this field"
    item: dict[str, Any] = {
        "title": "Choose " + _OWNER_DECISION_SLOT_LABELS.get(slot_id or "", field),
        "field": field,
        "message": message,
        "reason": message,
        "ai_proposed": proposed if proposed not in (None, "") else "No proposal supplied",
        "proposed": proposed if proposed not in (None, "") else "No proposal supplied",
        "legal_choices": choices,
        "legal_choice_count": total_choice_count or len(choices),
        "legal_choices_truncated": bool(total_choice_count and total_choice_count > len(choices)),
        "resolving_action": action,
        "resolution_surface": surface,
        "target_step": target_step,
        "control": {
            "type": "text" if is_descriptive else "select" if choices else "recovery",
            "apply_label": "Save identity wording" if is_descriptive else "Apply decision and rebuild",
        },
        "operation": operation,
        "blocker_sha256": sha256_json(details),
    }
    if not choices:
        item["legal_choices_note"] = "The frozen authority did not publish a direct owner choice list for this field."
        if not is_descriptive:
            item["recovery_action"] = "Replace Response"
    return item


def _owner_lock_value(run: dict[str, Any], field: str) -> Any:
    request = run.get("request") or {}
    request = request if isinstance(request, dict) else {}
    prompt = request.get("stage1_prompt") or {}
    prompt = prompt if isinstance(prompt, dict) else {}
    envelope = prompt.get("envelope") or {}
    envelope = envelope if isinstance(envelope, dict) else {}
    for row in envelope.get("user_locks") or []:
        if isinstance(row, dict) and row.get("field") == field:
            return row.get("value")
    return None


def _owner_card(
    row: Any,
    *,
    state: str | None = None,
    record_names: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Reduce a compiled record to useful owner-facing display data.

    The persisted Character Sheet remains authoritative.  Ordinary owner mode
    receives names, source-backed text, parent context, and progression
    values, while stable IDs and receipt trees remain technical evidence.
    """
    name = _owner_record_name(row)
    if not name:
        return None
    description = _owner_record_description(row)
    result: dict[str, Any] = {"name": name}
    if description:
        result["description"] = description
    if state:
        result["state"] = state
    if isinstance(row, dict):
        record_names = record_names or {}
        parent_id = (
            row.get("parent_sphere_id")
            or row.get("owning_canonical_sphere_id")
            or row.get("sphere_id")
        )
        parent = (
            row.get("parent_sphere_name")
            or row.get("owning_canonical_sphere_name")
            or row.get("sphere")
            or row.get("parent_sphere")
        )
        parent_name = _owner_record_name(parent) or (
            record_names.get(parent_id) if isinstance(parent_id, str) else None
        )
        if parent_name:
            result["sphere"] = parent_name
        acquisition = row.get("acquisition") if isinstance(row.get("acquisition"), dict) else {}
        acquired_cl = row.get("acquisition_cl")
        if acquired_cl is None:
            acquired_cl = row.get("gained_at_cl")
        if acquired_cl is None:
            acquired_cl = row.get("target_cl") if row.get("target_cl") is not None else row.get("effective_cl")
        if acquired_cl is None:
            acquired_cl = acquisition.get("target_cl") if acquisition.get("target_cl") is not None else acquisition.get("gained_at_cl")
        if isinstance(acquired_cl, int):
            result["cl"] = acquired_cl
        category = row.get("timing_or_category") or row.get("section") or row.get("subsection")
        if isinstance(category, str) and category.strip():
            result["category"] = category.strip()
    timing = row.get("timing_or_category") if isinstance(row, dict) else None
    if isinstance(timing, str) and timing.strip():
        result["timing"] = timing.strip()
    route = (
        row.get("acquisition_route") or row.get("acquisition_type")
        if isinstance(row, dict)
        else None
    )
    if route in _OWNER_FREE_TALENT_ROUTES:
        result["acquisition"] = "free"
    elif route in _OWNER_ORDINARY_TALENT_ROUTES:
        result["acquisition"] = "ordinary"
    return result


def _bounded_owner_scratch_sheet(compiled_sheet: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project the scratch Character Sheet into owner-readable fields only.

    Scratch compilation deliberately produces the same complete sheet service
    response used by the persisted character.  The response is much larger than
    an owner review needs, so this projection selects display names, player text,
    meaningful values, and explicit pending states while dropping IDs, hashes,
    source bindings, and technical receipts.
    """
    if not isinstance(compiled_sheet, dict):
        return None
    snapshot = compiled_sheet.get("owner_character_sheet")
    if not isinstance(snapshot, dict):
        return None
    identity = snapshot.get("identity") or compiled_sheet.get("identity") or {}
    if not isinstance(identity, dict):
        identity = {}
    path_surface = snapshot.get("path_and_subpath") or {}
    path_surface = path_surface if isinstance(path_surface, dict) else {}
    method = snapshot.get("method") or {}
    method = method if isinstance(method, dict) else {}
    sphere_surface = snapshot.get("spheres_and_talents") or {}
    sphere_surface = sphere_surface if isinstance(sphere_surface, dict) else {}
    sections = snapshot.get("selected_record_sections") or {}
    sections = sections if isinstance(sections, dict) else {}
    record_names = _owner_record_map(snapshot)

    # Sheet talent rows carry no Sphere link; the sheet service supplies the
    # catalog Sphere name per talent record for display grouping.
    talent_sphere_names = compiled_sheet.get("talent_sphere_names")
    talent_sphere_names = talent_sphere_names if isinstance(talent_sphere_names, dict) else {}

    def cards_for(*needles: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for section_name, section_rows in sections.items() if isinstance(sections, dict) else []:
            lowered = str(section_name).casefold()
            if not any(needle in lowered for needle in needles) or not isinstance(section_rows, list):
                continue
            for row in section_rows:
                card = _owner_card(row, record_names=record_names)
                if card:
                    if "sphere" not in card and isinstance(row, dict):
                        sphere_name = talent_sphere_names.get(row.get("record_id"))
                        if isinstance(sphere_name, str) and sphere_name:
                            card["sphere"] = sphere_name
                    rows.append(card)
        return rows

    def named_values(values: Any) -> list[str]:
        result: list[str] = []
        if not isinstance(values, list):
            return result
        for value in values:
            if isinstance(value, str):
                name = record_names.get(value) or _OWNER_PATH_NAMES.get(value)
                if name:
                    result.append(name)
            else:
                card = _owner_card(value, record_names=record_names)
                if card:
                    result.append(card["name"])
        return result

    paths: list[dict[str, Any]] = []
    for row in (path_surface.get("paths") or snapshot.get("path_selections") or []):
        if not isinstance(row, dict):
            continue
        path_id = row.get("path_id")
        name = _OWNER_PATH_NAMES.get(path_id) or _owner_record_name(row)
        if not name:
            continue
        paths.append({
            "name": name,
            "mode": "advancing" if row.get("advancing") or row.get("status") in {"ACTIVE", "ADVANCING"} else "dormant",
            "attainment": row.get("attainment") if row.get("attainment") is not None else "pending",
        })
    if not paths:
        # The delegated resolution is projected separately below.  Keep this
        # field explicit rather than inventing a level or claiming acquisition.
        paths = [{"name": name, "mode": "pending", "attainment": "pending"} for name in _OWNER_PATH_NAMES.values()]

    path_value = path_surface.get("path") if isinstance(path_surface, dict) else None
    subpath_value = path_surface.get("subpath") if isinstance(path_surface, dict) else None
    path_name = _owner_record_name(path_value)
    subpath_name = _owner_record_name(subpath_value)
    subpaths: list[dict[str, Any]] = []
    raw_subpaths = path_surface.get("subpaths") if isinstance(path_surface, dict) else None
    if not isinstance(raw_subpaths, list):
        raw_subpaths = []
    for row in raw_subpaths:
        if not isinstance(row, dict):
            continue
        subpath_id = row.get("subpath_id") or row.get("record_id")
        name_value = _owner_record_name(row)
        if not name_value and isinstance(subpath_id, str):
            name_value = record_names.get(subpath_id)
        if not name_value:
            continue
        owning_path_id = row.get("owning_path_id")
        if not isinstance(owning_path_id, str) or not owning_path_id:
            # A projected Subpath without an exact owner is not a usable
            # Path/Subpath association. Do not inherit the primary Path.
            continue
        subpaths.append({
            "name": name_value,
            "path_id": owning_path_id,
            "path": _OWNER_PATH_NAMES.get(owning_path_id, owning_path_id),
            "state": "acquired",
        })
    if not subpaths and subpath_name:
        owning_path_id = subpath_value.get("owning_path_id") if isinstance(subpath_value, dict) else None
        # A Subpath cannot inherit ownership from the primary display Path.
        # If the exact owner is absent, omit the association rather than
        # presenting a fabricated Path/Subpath binding to downstream UX.
        if isinstance(owning_path_id, str) and owning_path_id:
            subpaths.append({
                "name": subpath_name,
                "path_id": owning_path_id,
                "path": _OWNER_PATH_NAMES.get(owning_path_id, owning_path_id),
                "state": "acquired",
            })
    subpath_bindings = [
        {
            "subpath": row["name"],
            "path": row["path"],
            "path_id": row.get("path_id"),
            "state": row.get("state", "acquired"),
        }
        for row in subpaths
    ]
    method_name = _owner_record_name(method)

    ability_surface = snapshot.get("ability_scores_and_statistics") or {}
    ability_surface = ability_surface if isinstance(ability_surface, dict) else {}
    primary_resource = ability_surface.get("primary_resource") or {}
    resources: list[dict[str, Any]] = []
    if isinstance(primary_resource, dict):
        resource_name = _owner_record_name(primary_resource) or primary_resource.get("name")
        if isinstance(resource_name, str) and resource_name.strip():
            resources.append({
                "name": resource_name.strip(),
                "current": primary_resource.get("build_state_current") if primary_resource.get("build_state_current") is not None else "pending",
                "maximum": primary_resource.get("maximum") if primary_resource.get("maximum") is not None else "pending",
            })

    automatic = []
    for row in sphere_surface.get("automatic_sphere_components") or []:
        card = _owner_card(row, state="automatic", record_names=record_names)
        if card:
            automatic.append(card)
    talents = cards_for("talent")
    free_talents = [card for card in talents if card.get("acquisition") == "free"]
    ordinary_talents = [card for card in talents if card.get("acquisition") == "ordinary"]
    insights = cards_for("insight")
    # Sphere sections also carry the Sphere's automatic components (base
    # abilities such as Grave Sense or Steal), which the card projection marks
    # with their parent ``sphere``.  Only parentless cards are Spheres; the
    # components are already listed under ``automatic_components`` grouped by
    # their Sphere, so listing them here doubled them as "9 Spheres".
    spheres = [card for card in cards_for("sphere") if not card.get("sphere")]
    equipment = cards_for("equipment", "item")
    actions = cards_for("action", "feature")
    progression_by_cl: dict[int, dict[str, Any]] = {}

    def progression_bucket(cl: Any) -> dict[str, Any] | None:
        if not isinstance(cl, int) or cl < 1:
            return None
        return progression_by_cl.setdefault(
            cl,
            {"cl": cl, "spheres": [], "talents": [], "insights": [], "automatic_components": [], "features": []},
        )

    for key, rows in (
        ("spheres", spheres),
        ("talents", talents),
        ("insights", insights),
        ("automatic_components", automatic),
        ("features", actions),
    ):
        for card in rows:
            bucket = progression_bucket(card.get("cl"))
            if bucket is not None:
                bucket[key].append(card)
    advancement = snapshot.get("advancement_history") or {}
    if isinstance(advancement, dict):
        for level in advancement.get("levels") or []:
            if not isinstance(level, dict):
                continue
            cl = level.get("cl") or level.get("cultivation_level") or level.get("level")
            bucket = progression_bucket(cl)
            if bucket is not None and level.get("status"):
                bucket["status"] = str(level["status"])
    progression = [progression_by_cl[cl] for cl in sorted(progression_by_cl)]
    return {
        "identity": {
            "name": identity.get("display_name") or identity.get("name") or "Name pending owner review",
            "concept": identity.get("concept") or "Concept pending owner review",
            "cultivation_level": identity.get("cultivation_level") if identity.get("cultivation_level") is not None else "pending",
            "realm": identity.get("realm_display") or identity.get("realm") or "pending",
        },
        "paths": paths,
        "method": {"name": method_name or "Method pending validated compilation", "state": "acquired" if method_name else "pending"},
        "foundation": {"name": _owner_record_name(snapshot.get("foundation")) or "Foundation pending validated compilation", "state": "acquired" if snapshot.get("foundation") else "pending"},
        "tradition": {"name": subpath_name or "Subpath / Tradition pending", "state": "acquired" if subpath_name else "pending"},
        "subpaths": subpaths,
        "subpath_bindings": subpath_bindings,
        "resources": resources or [{"name": "Cultivation resources", "current": "pending", "maximum": "pending"}],
        "spheres": spheres,
        "talents": talents,
        "free_talents": free_talents,
        "ordinary_talents": ordinary_talents,
        "insights": insights,
        "equipment": equipment,
        "actions": actions,
        "automatic_components": automatic,
        "progression": progression,
        "ability_locks": [
            {"name": str(row.get("ability") or "Ability"), "value": row.get("score") if row.get("score") is not None else "pending"}
            for row in ability_surface.get("abilities") or []
            if isinstance(row, dict)
        ],
    }


def _owner_sphere_inventory(
    *,
    run: dict[str, Any],
    envelope: dict[str, Any],
    proposal_selected_by_slot: dict[str, Any],
    owner_locked_by_slot: dict[str, Any],
    proposal_acquisition: dict[str, Any],
    planning_sphere_ids: list[str],
    talent_authority: dict[str, Any],
    training_routes: dict[str, Any],
    scratch_sheet: dict[str, Any] | None,
    name: Any,
) -> dict[str, Any]:
    """One Sphere-centred inventory of a proposal, using the same frozen authority as the walk.

    The review used to show the Background triplet, the starting grant, level
    Talents, trained choices, and bonuses as unrelated groups, so an owner could
    not see which Spheres the character would actually hold, which requested
    Spheres never arrived, or which mandatory choice was still missing.  Every
    row here is labelled proposed unless the compiled scratch sheet lists the
    same Sphere; nothing is granted by this projection.  Missing mandatory
    steps come from the server blocker detail, not from a generic message.
    """

    requested_ids = [value for value in planning_sphere_ids if isinstance(value, str) and value]
    holdings: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    unassigned_talents: list[dict[str, Any]] = []

    def holding(sphere_id: str, *, source: str, cl: int | None = None, slot: int | None = None, display_slot: str = "sphere_priorities") -> dict[str, Any]:
        row = holdings.get(sphere_id)
        if row is None:
            row = {
                "sphere_id": sphere_id,
                "name": name(display_slot, sphere_id),
                "source": source,
                "cl": cl,
                "slot": slot,
                "requested": sphere_id in requested_ids,
                "state": "proposed",
                "talents": [],
            }
            holdings[sphere_id] = row
            order.append(sphere_id)
        return row

    def talent_sphere(record_id: str) -> str | None:
        authority = talent_authority.get(record_id) or {}
        sphere_id = authority.get("sphere_id") if isinstance(authority, dict) else None
        if not isinstance(sphere_id, str) or not sphere_id:
            route = training_routes.get(record_id) or {}
            sphere_id = route.get("owning_sphere_id") if isinstance(route, dict) else None
        return sphere_id if isinstance(sphere_id, str) and sphere_id else None

    def add_talent(sphere_id: str | None, record_id: str, *, source: str, cl: int | None = None, display_slot: str = "advancement_skeleton") -> None:
        talent = {"record_id": record_id, "name": name(display_slot, record_id), "source": source, "cl": cl}
        if sphere_id and sphere_id in holdings:
            holdings[sphere_id]["talents"].append(talent)
            return
        talent["sphere_id"] = sphere_id
        talent["sphere"] = name("sphere_priorities", sphere_id) if sphere_id else None
        unassigned_talents.append(talent)

    background_selected = {
        slot_id: [
            value for value in (owner_locked_by_slot.get(slot_id) or proposal_selected_by_slot.get(slot_id) or [])
            if isinstance(value, str) and value
        ]
        for slot_id in ("background_choice", "background_sphere_choice", "background_talent_choice")
    }
    canonical_spheres, canonical_talents = canonical_background_package_ids(
        background_selected,
        envelope.get("typed_choice_authority_by_slot"),
    )
    if canonical_spheres:
        for sphere_id in sorted(canonical_spheres):
            holding(sphere_id, source="Background")
            for talent_id in sorted(canonical_talents):
                add_talent(sphere_id, talent_id, source="Background Talent")
    else:
        for sphere_id in background_selected["background_sphere_choice"]:
            holding(sphere_id, source="Background (canonical relation unresolved)", display_slot="background_sphere_choice")
            for talent_id in background_selected["background_talent_choice"]:
                add_talent(sphere_id, talent_id, source="Background Talent", display_slot="background_talent_choice")

    for pair in proposal_acquisition.get("sphere_free_talent_pairs") or []:
        if not isinstance(pair, dict):
            continue
        sphere_id, talent_id = pair.get("sphere_id"), pair.get("talent_id")
        if isinstance(sphere_id, str) and sphere_id:
            holding(sphere_id, source="Starting grant", cl=1)
            if isinstance(talent_id, str) and talent_id:
                add_talent(sphere_id, talent_id, source="Starting free Talent", cl=1)

    trained_rows = [
        row for row in proposal_acquisition.get("trained_choices") or []
        if isinstance(row, dict) and isinstance(row.get("record_id"), str) and row.get("record_id")
    ]
    trained_rows.sort(key=lambda row: (row.get("cl") if type(row.get("cl")) is int else 0, row.get("slot") if type(row.get("slot")) is int else 0))
    for row in trained_rows:
        cl = row.get("cl") if type(row.get("cl")) is int else None
        slot = row.get("slot") if type(row.get("slot")) is int else None
        if row.get("choice_type") == "new_sphere":
            holding(row["record_id"], source="Training", cl=cl, slot=slot)
            bonus_id = row.get("bonus_talent_id")
            if isinstance(bonus_id, str) and bonus_id:
                add_talent(row["record_id"], bonus_id, source="New-Sphere bonus", cl=cl)
        else:
            add_talent(talent_sphere(row["record_id"]), row["record_id"], source="Trained", cl=cl)

    for cl, talent_id in enumerate(proposal_acquisition.get("ordinary_talent_ids") or [], start=1):
        if isinstance(talent_id, str) and talent_id:
            add_talent(talent_sphere(talent_id), talent_id, source="Free level Talent", cl=cl)

    validated_names = {
        str(card.get("name") or "").casefold()
        for card in ((scratch_sheet or {}).get("spheres") or [])
        if isinstance(card, dict) and card.get("name")
    }
    for row in holdings.values():
        if validated_names and str(row["name"]).casefold() in validated_names:
            row["state"] = "validated"

    missing: list[dict[str, Any]] = []
    for blocker in run.get("blockers") or []:
        if not isinstance(blocker, dict):
            continue
        details = blocker.get("details") if isinstance(blocker.get("details"), dict) else {}
        code = str(blocker.get("code") or "")
        if details.get("reason") == "no_legal_constructed_training_candidate":
            missing.append({
                "code": code,
                "step_id": details.get("step_id"),
                "summary": f"Constructed training CL {details.get('cl')} slot {details.get('slot')} has no legal option in this frozen request.",
                "detail": (
                    f"{details.get('new_sphere_routes_without_exact_training_authority')} of {details.get('new_sphere_route_count')} new-Sphere routes lack exact training authority; "
                    f"{details.get('known_sphere_talent_routes_unused')} known-Sphere Talent routes remain unused."
                ),
                "known_sphere_ids": list(details.get("known_sphere_ids") or []),
            })
        if details.get("reason") == "mandatory_acquisitions_incomplete":
            trained_missing = details.get("trained_choices_missing_by_cl") if isinstance(details.get("trained_choices_missing_by_cl"), dict) else {}
            ordinary_missing = details.get("ordinary_talent_missing_cls") if isinstance(details.get("ordinary_talent_missing_cls"), list) else []
            parts = []
            if trained_missing:
                parts.append("trained choices missing at CL " + ", ".join(f"{cl} ({count})" for cl, count in trained_missing.items()))
            if ordinary_missing:
                parts.append("free level Talents missing at CL " + ", ".join(str(cl) for cl in ordinary_missing))
            missing.append({
                "code": code,
                "step_id": details.get("next_step_id"),
                "summary": f"Mandatory acquisitions incomplete; next step {details.get('next_step_id')}.",
                "detail": "; ".join(parts) or "See the blocker detail.",
            })
        for issue in details.get("issues") or []:
            if isinstance(issue, dict) and issue.get("reason") == "COUNT_MISMATCH":
                missing.append({
                    "code": code,
                    "step_id": None,
                    "summary": f"{issue.get('field')}: {issue.get('actual_count')} of {issue.get('expected_count')} required.",
                    "detail": "The response carries fewer mandatory acquisitions than the frozen contract requires.",
                })

    holding_rows = [holdings[sphere_id] for sphere_id in order]
    talent_count = sum(len(row["talents"]) for row in holding_rows) + len(unassigned_talents)
    return {
        "requested": [
            {"sphere_id": sphere_id, "name": name("sphere_priorities", sphere_id), "acquired": sphere_id in holdings}
            for sphere_id in requested_ids
        ],
        "holdings": holding_rows,
        "requested_not_acquired": [
            {"sphere_id": sphere_id, "name": name("sphere_priorities", sphere_id)}
            for sphere_id in requested_ids
            if sphere_id not in holdings
        ],
        "unassigned_talents": unassigned_talents,
        "missing_mandatory": missing,
        "counts": {
            "spheres": len(holding_rows),
            "validated_spheres": sum(1 for row in holding_rows if row["state"] == "validated"),
            "talents": talent_count,
            "requested": len(requested_ids),
            "requested_not_acquired": sum(1 for sphere_id in requested_ids if sphere_id not in holdings),
            "missing_mandatory": len(missing),
        },
    }


def _invert_stamp(value: str) -> str:
    """Return a key that sorts an ISO-8601 stamp descending among its peers."""

    text = str(value or "")
    if not text:
        return "\uffff"
    # Invert every character so lexicographic ascending becomes newest-first.
    return "".join(chr(0x10FFFF - ord(ch)) for ch in text)


def _owner_view(run: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded server-derived projection consumed by owner panels."""
    status = str(run.get("status") or "UNKNOWN")
    # One-page review (owner request 2026-09-13): steps 5-8 are no longer
    # screens.  From READY_FOR_REVIEW onward the owner screen is step 4, the
    # single "Your character" page; finalized and blocked runs stay there too.
    stage = {
        "PREPARING_REQUEST": 3,
        "WAITING_FOR_RESPONSE": 3,
        "READY_FOR_REVIEW": 4,
        "NEEDS_REVIEW": 4,
        "CLEAN_AND_FINALIZED": 4,
        "REVISED": 3,
        "CANCELLED": 4,
    }.get(status, 1)
    request = run.get("request") or {}
    request = request if isinstance(request, dict) else {}
    final_plan = run.get("final_plan") or {}
    final_plan = final_plan if isinstance(final_plan, dict) else {}
    resolution = final_plan.get("resolution") if isinstance(final_plan, dict) else {}
    resolution = resolution if isinstance(resolution, dict) else {}
    envelope = request.get("delegated_choice_envelope") or {}
    envelope = envelope if isinstance(envelope, dict) else {}
    choice_metadata = envelope.get("choices_by_slot") or {}
    choice_metadata = choice_metadata if isinstance(choice_metadata, dict) else {}
    allowed_choice_ids_by_slot = envelope.get("allowed_choice_ids_by_slot") or {}
    allowed_choice_ids_by_slot = allowed_choice_ids_by_slot if isinstance(allowed_choice_ids_by_slot, dict) else {}
    dry_run = run.get("dry_run") or {}
    dry_run = dry_run if isinstance(dry_run, dict) else {}
    preview = dry_run.get("preview") or {}
    preview = preview if isinstance(preview, dict) else {}
    artifacts = dry_run.get("artifacts") or {}
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    compiled = preview.get("compiled") or {}
    compiled = compiled if isinstance(compiled, dict) else {}
    compiled_sheet = artifacts.get("character_sheet")
    if not isinstance(compiled_sheet, dict):
        compiled_sheet = compiled.get("character_sheet")
    scratch_sheet = _bounded_owner_scratch_sheet(compiled_sheet)
    record_names = _owner_record_map((compiled_sheet or {}).get("owner_character_sheet") or {}) if isinstance(compiled_sheet, dict) else {}
    validation = run.get("validation") if isinstance(run.get("validation"), dict) else {}
    proposal_projection = validation.get("proposal_projection") if isinstance(validation, dict) else {}
    proposal_projection = proposal_projection if isinstance(proposal_projection, dict) else {}

    def name(slot_id: str, value: Any) -> str:
        return _owner_choice_name(slot_id, value, choice_metadata=choice_metadata, record_names=record_names)

    selected_by_slot = resolution.get("selected_choices_by_slot") or {}
    selected_by_slot = selected_by_slot if isinstance(selected_by_slot, dict) else {}
    parsed_plan = (run.get("response") or {}).get("parsed_plan") or {}
    parsed_plan = parsed_plan if isinstance(parsed_plan, dict) else {}
    exact_response_text = (run.get("response") or {}).get("exact_response_text")
    if not parsed_plan and isinstance(exact_response_text, str) and exact_response_text:
        try:
            parsed_plan = json.loads(exact_response_text)
        except (TypeError, json.JSONDecodeError):
            parsed_plan = {}
    if isinstance(parsed_plan, dict) and parsed_plan:
        # Keep the visible proposal synchronized with prior owner resolutions.
        # The raw response remains immutable; this is only the owner-facing
        # overlay used to publish the next legal control.
        parsed_overlay = CharacterCreationExecutionService._apply_owner_resolutions(run, parsed_plan)
        proposal_projection = CharacterCreationExecutionService._proposal_projection(parsed_overlay)
    if not proposal_projection and isinstance(validation, dict):
        proposal_projection = validation.get("proposal_projection") if isinstance(validation.get("proposal_projection"), dict) else {}
    proposal_selected_by_slot = proposal_projection.get("selected_by_slot") if isinstance(proposal_projection.get("selected_by_slot"), dict) else {}
    if not selected_by_slot and proposal_selected_by_slot:
        selected_by_slot = deepcopy(proposal_selected_by_slot)
    canonical_intent = parsed_plan.get("canonical_selection_intent") or run.get("canonical_selection_intent") or {}
    canonical_intent = canonical_intent if isinstance(canonical_intent, dict) else {}
    planning_preferences = canonical_intent.get("planning_preferences_by_slot") or {}
    planning_preferences = planning_preferences if isinstance(planning_preferences, dict) else {}
    if not planning_preferences:
        planning_preferences = proposal_projection.get("planning_preferences_by_slot") if isinstance(proposal_projection.get("planning_preferences_by_slot"), dict) else {}
    # The owner may have frozen planning priorities before the Manual Chat
    # response exists.  Preserve those visible preferences in the candidate
    # view, while allowing a later AI response to add a planning-only slot
    # such as Items / Equipment without promoting it to acquisition.
    project_planning: dict[str, Any] = {}
    for lock in ((request.get("stage1_prompt") or {}).get("envelope") or {}).get("user_locks") or []:
        if isinstance(lock, dict) and lock.get("field") == "character_sheet.planning_preferences" and isinstance(lock.get("value"), dict):
            project_planning = lock["value"]
            break
    planning_slot_aliases = {
        "sphere_priority_ids": "sphere_priorities",
        "talent_priority_ids": "advancement_skeleton",
        "insight_priority_ids": "insight_priorities",
        "item_priority_ids": "item_priorities",
    }
    merged_planning: dict[str, list[str]] = {}
    for source_key, slot_id in planning_slot_aliases.items():
        values = project_planning.get(source_key) or []
        if isinstance(values, list):
            merged_planning[slot_id] = [value for value in values if isinstance(value, str) and value]
    for slot_id, values in planning_preferences.items():
        if isinstance(values, list):
            merged_planning[slot_id] = [value for value in values if isinstance(value, str) and value]
    planning_preferences = merged_planning
    owner_locked_by_slot = ((envelope.get("owner_locks") or {}).get("by_slot") or {})
    owner_planning_locks = ((envelope.get("owner_locks") or {}).get("planning_by_slot") or {})
    method_planning_lock = owner_planning_locks.get("method_choice")
    method_planning_lock = method_planning_lock if isinstance(method_planning_lock, dict) else {}
    method_planning_lock_ids = {
        value for value in method_planning_lock.get("choice_ids") or []
        if isinstance(value, str) and value
    }
    planning_owner_locked_ids = {
        slot_id: set(values)
        for source_key, slot_id in planning_slot_aliases.items()
        for values in [project_planning.get(source_key) or []]
        if isinstance(values, list)
    }

    def planning_rows(slot_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for choice_id in planning_preferences.get(slot_id) or []:
            if not isinstance(choice_id, str) or not choice_id:
                continue
            owner_locked = choice_id in (owner_locked_by_slot.get(slot_id) or []) or choice_id in planning_owner_locked_ids.get(slot_id, set())
            rows.append({
                "choice_id": choice_id,
                "name": name(slot_id, choice_id),
                "provenance": "Owner" if owner_locked else "AI proposed",
                "state": "planning_only",
                "planning_only": True,
                "note": "Planning only; this does not grant or acquire the choice.",
            })
        return rows

    planning_items = planning_rows("item_priorities")
    planning_spheres = planning_rows("sphere_priorities")
    planning_talents = planning_rows("advancement_skeleton")
    planning_insights = planning_rows("insight_priorities")
    authoritative_path_source: str | None = None
    authoritative_advancing_paths: set[str] = set()
    # The compiled actual state is strongest; a Method grant is the next
    # server-owned source.  A selected Path alone is legacy intent and cannot
    # override an explicitly present empty authoritative list.
    for field in ("actual_advancing_path_ids", "method_granted_path_ids", "selected_path_ids"):
        values = resolution.get(field)
        if isinstance(values, list):
            authoritative_path_source = field
            authoritative_advancing_paths = {
                value for value in values if isinstance(value, str) and value
            }
            break
    has_authoritative_path_state = authoritative_path_source is not None
    paths = [
        {
            "name": _OWNER_PATH_NAMES.get(path_id, name("path_choice", path_id)),
            "state": "advancing" if path_id in authoritative_advancing_paths else "dormant",
            "attainment": "pending",
            "provenance": "Owner" if path_id in (envelope.get("owner_locks") or {}).get("by_slot", {}).get("path_choice", []) else "AI proposed",
        }
        for path_id in _OWNER_PATH_NAMES
    ]
    if scratch_sheet and scratch_sheet.get("paths"):
        # Keep all three source-backed level-zero tracks visible, but prefer the
        # candidate's server-derived advancing/dormant state when available.
        by_name = {row.get("name"): row for row in scratch_sheet["paths"] if isinstance(row, dict)}
        for row in paths:
            candidate = by_name.get(row["name"])
            if candidate:
                if candidate.get("mode") in {"advancing", "dormant"} and not has_authoritative_path_state:
                    row["state"] = candidate["mode"]
                candidate_attainment = candidate.get("attainment")
                if candidate_attainment is not None:
                    row["attainment"] = candidate_attainment

    manual_correction = run.get("manual_ai_correction") if isinstance(run.get("manual_ai_correction"), dict) else {}
    manual_correction_required = bool(
        run.get("execution_mode") == "MANUAL_CHAT"
        and (
            manual_correction.get("required") is True
            or CharacterCreationExecutionService._manual_ai_correction_from_run(run) is not None
        )
    )
    local_correction_availability = (run.get("action_availability") or {}).get("retry_local_ai_correction")
    local_correction_available = isinstance(local_correction_availability, dict) and local_correction_availability.get("available") is True
    # The captured candidate is sound; only its GM guidance is provisional.
    # Name the GM candidate authoring path instead of a response replacement.
    gm_candidate_gate = gm_candidate_authoring_gate(run)
    if not manual_correction:
        manual_correction = {"required": manual_correction_required}
    provenance_rows = (
        []
        if manual_correction_required
        else (resolution.get("provenance") or []) if isinstance(resolution, dict) else []
    )
    # Rejected/unavailable candidate alternatives remain in the persisted
    # resolution evidence and developer diagnostics, but are not owner work.
    # Only actual blockers and unresolved owner rows below can create a review
    # decision; accepted rows remain visible in their resolved provenance group.
    provenance_rows = [
        row for row in provenance_rows
        if isinstance(row, dict)
        and str(row.get("status") or "").strip().lower() not in {"rejected", "unavailable"}
        and str(row.get("provenance") or "").strip().lower() != "unavailable"
    ]
    # Runs sealed before 2026-09-05 recorded a legally deferred Method as two
    # needs_owner rows (one "unresolved", one "deferred_or_typed_none").  When
    # the resolution itself says the Method was deferred, those rows describe
    # the same legal outcome as today's single "deferred" row: render them so.
    if isinstance(resolution, dict) and resolution.get("deferred_method") is True:
        normalized_rows = []
        for row in provenance_rows:
            if str(row.get("slot_id") or "") == "method_choice" and str(row.get("provenance") or "").strip().lower() == "needs_owner":
                if str(row.get("status") or "").strip().lower() == "unresolved":
                    continue
                row = {**row, "provenance": "deferred", "status": "deferred_or_typed_none"}
            normalized_rows.append(row)
        provenance_rows = normalized_rows
    provenance_groups = {label: [] for label in ("Owner", "AI proposed", "Automatic", "Needs owner decision")}
    for row in provenance_rows:
        if not isinstance(row, dict):
            continue
        provenance_key = str(row.get("provenance") or "needs_owner").strip().lower()
        label = _OWNER_PROVENANCE_LABELS.get(provenance_key, "Needs owner decision")
        if label == "Unavailable":
            label = "Needs owner decision"
        slot_id = str(row.get("slot_id") or "")
        choice_id = row.get("choice_id")
        status_key = str(row.get("status") or "").strip().lower()
        deferred = status_key == "deferred_or_typed_none"
        item = {
            "name": name(slot_id, choice_id) if choice_id else ("Method deferred (none selected at creation, which the rules allow)" if deferred and slot_id == "method_choice" else "Deferred" if deferred else "Unresolved choice"),
            "status": "resolved" if status_key == "accepted" or deferred else "needs_owner",
        }
        reason = row.get("reason")
        if isinstance(reason, str) and reason.strip():
            item["note"] = reason.strip().replace("_", " ")
        provenance_groups[label].append(item)
    for row in [*planning_spheres, *planning_talents, *planning_insights, *planning_items]:
        label = row["provenance"] if row["provenance"] in provenance_groups else "AI proposed"
        provenance_groups[label].append({
            "name": row["name"],
            "status": "planning_only",
            "note": row["note"],
        })
    if not provenance_groups["Owner"]:
        provenance_groups["Owner"].append({"name": "Target CL and locked brief", "status": "resolved"})

    selected_subpath_ids = [
        value for value in (selected_by_slot.get("subpath_choice") or [])
        if isinstance(value, str) and value
    ]
    owner_locked_subpaths = set(
        (envelope.get("owner_locks") or {}).get("by_slot", {}).get("subpath_choice") or []
    )
    subpath_rows: list[dict[str, Any]] = []
    for subpath_id in selected_subpath_ids:
        metadata = (choice_metadata.get("subpath_choice") or {}).get(subpath_id) or {}
        owning_path_id = metadata.get("owning_path_id")
        if not isinstance(owning_path_id, str) or not owning_path_id:
            # The owner-facing delegated preview must not turn a missing
            # explicit Subpath owner into a primary-Path association.
            continue
        subpath_rows.append({
            "choice_id": subpath_id,
            "name": name("subpath_choice", subpath_id),
            "path_id": owning_path_id,
            "path": _OWNER_PATH_NAMES.get(owning_path_id, owning_path_id),
            "provenance": "Owner" if subpath_id in owner_locked_subpaths else "AI proposed",
            "state": "selected",
        })
    if not subpath_rows and isinstance((scratch_sheet or {}).get("subpaths"), list):
        subpath_rows = [deepcopy(row) for row in scratch_sheet["subpaths"] if isinstance(row, dict)]
    subpath_bindings = [
        {
            "choice_id": row.get("choice_id"),
            "subpath": row.get("name") or "Subpath / Tradition pending",
            "path_id": row.get("path_id"),
            "path": row.get("path") or _OWNER_PATH_NAMES.get(row.get("path_id"), "Path pending"),
            "provenance": row.get("provenance", "AI proposed"),
            "state": row.get("state", "selected"),
        }
        for row in subpath_rows
    ]

    selected_method_id = resolution.get("method_id") or (
        proposal_selected_by_slot.get("method_choice") or [None]
    )[0]
    method_choice_metadata = (
        (choice_metadata.get("method_choice") or {}).get(selected_method_id)
        if isinstance(selected_method_id, str)
        else {}
    ) or {}
    method_access_metadata = (
        (envelope.get("path_method_authority") or {}).get("method_access_by_id") or {}
    ).get(selected_method_id, {}) if isinstance(selected_method_id, str) else {}
    method_access_metadata = method_access_metadata or method_choice_metadata.get("method_access") or method_choice_metadata
    direct_access = method_access_metadata.get("direct_access")
    if direct_access is None:
        direct_access = method_access_metadata.get("initial_creation_selectable")
    access_required = method_access_metadata.get("access_required")
    if access_required is None and direct_access is not None:
        access_required = not bool(direct_access)
    exact_lock_configurable = method_access_metadata.get("exact_lock_configurable")
    if exact_lock_configurable is None:
        exact_lock_configurable = method_access_metadata.get("exact_selection_available")

    descriptive = run.get("owner_descriptive_fields") or {}
    resolved = descriptive.get("resolved") or {}
    proposed = descriptive.get("proposed") or {}
    accepted = descriptive.get("accepted") or {}
    resolved_identity = resolved.get("identity") if isinstance(resolved, dict) else {}
    proposed_identity = proposed.get("identity") if isinstance(proposed, dict) else {}
    accepted_identity = accepted.get("identity") if isinstance(accepted, dict) else {}
    resolved_identity = resolved_identity if isinstance(resolved_identity, dict) else {}
    proposed_identity = proposed_identity if isinstance(proposed_identity, dict) else {}
    accepted_identity = accepted_identity if isinstance(accepted_identity, dict) else {}
    accepted_name = accepted_identity.get("name")
    accepted_concept = accepted.get("concept") if isinstance(accepted, dict) else None
    proposal_identity = proposal_projection.get("identity") if isinstance(proposal_projection.get("identity"), dict) else {}
    proposed_name = proposed_identity.get("name") or proposal_identity.get("name")
    proposed_concept = proposed.get("concept") if isinstance(proposed, dict) else None
    proposed_concept = proposed_concept or proposal_identity.get("concept")
    def nonblank_identity_text(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    accepted_title = nonblank_identity_text(accepted_identity.get("title"))
    resolved_title = nonblank_identity_text(resolved_identity.get("title"))
    proposed_title = nonblank_identity_text(proposed_identity.get("title")) or nonblank_identity_text(proposal_identity.get("title"))
    projected_title = accepted_title or resolved_title or proposed_title
    projected_title_provenance = (
        "Owner" if accepted_title else "AI proposed" if projected_title else "Needs owner decision"
    )
    proposal_bounded = proposal_projection.get("bounded_choices") if isinstance(proposal_projection.get("bounded_choices"), dict) else {}
    proposal_acquisition = proposal_projection.get("acquisition_intent") if isinstance(proposal_projection.get("acquisition_intent"), dict) else {}
    blockers: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    decision_keys: set[tuple[str, str | None]] = set()
    for row in ([] if manual_correction_required else run.get("blockers") or []):
        if not isinstance(row, dict):
            continue
        raw_details = row.get("details") if isinstance(row.get("details"), dict) else {}
        details = raw_details
        if isinstance(details.get("milestone"), dict) or details.get("milestone_id"):
            details = _owner_milestone_decision_details(
                details,
                envelope=envelope,
                proposal_bounded=proposal_bounded,
                proposal_acquisition=proposal_acquisition,
                proposal_selected_by_slot=proposal_selected_by_slot,
                choice_metadata=choice_metadata,
                record_names=record_names,
                authority_by_milestone=run.get("owner_decision_authority") if isinstance(run.get("owner_decision_authority"), dict) else {},
            )
        expected = details.get("expected") or details.get("required") or details.get("required_path_ids")
        proposed_value = details.get("proposed") or details.get("actual") or details.get("proposed_method_granted_path_ids")
        slot_id = _owner_decision_slot_id(details)
        if slot_id == "subpath_choice" and _owner_subpath_decision_not_yet_due(
            request=request,
            final_plan=final_plan,
            parsed_plan=parsed_plan,
            selected_by_slot=selected_by_slot,
        ):
            continue
        if proposed_value is None and isinstance(details.get("choice_id"), str):
            proposed_value = details["choice_id"]
        decision_details = deepcopy(details)
        operation = str(decision_details.get("operation") or decision_details.get("decision_operation") or "replace_slot_value")
        target_value = decision_details.get("target_value")
        if (
            slot_id
            and operation == "replace_slot_value"
            and target_value is None
            and isinstance(decision_details.get("choice_id"), str)
        ):
            # A prerequisite blocker names the invalid member of a multi-value
            # priority list.  Bind that exact value to the owner control so a
            # replacement preserves every unaffected priority.
            target_value = decision_details["choice_id"]
            decision_details["target_value"] = target_value
        decision_allowed_choice_ids_by_slot = allowed_choice_ids_by_slot
        if slot_id and operation == "replace_slot_value":
            legality_plan = {
                "target_cl": final_plan.get("target_cl")
                or request.get("target_cl")
                or (envelope.get("frozen_owner_target_cl") or {}).get("target_cl")
            }
            legal_ids = legal_slot_replacement_ids(
                envelope,
                legality_plan,
                proposal_selected_by_slot,
                slot_id,
                target_value=target_value,
            )
            # Do not let a broad raw-blocker list take precedence over the
            # frozen legality result when _owner_decision_choices reads the
            # detail object.  Projection and resolution must publish the same
            # candidate set.
            decision_details["allowed_choice_ids"] = legal_ids
            decision_allowed_choice_ids_by_slot = {
                **allowed_choice_ids_by_slot,
                slot_id: legal_ids,
            }
        blocker_proposed_display = proposed_value
        if isinstance(proposed_value, list):
            blocker_proposed_display = ", ".join(
                _OWNER_PATH_NAMES.get(value, str(value)) if isinstance(value, str) else str(value)
                for value in proposed_value
            )
        elif isinstance(proposed_value, str) and slot_id:
            blocker_proposed_display = _owner_choice_name(
                slot_id,
                proposed_value,
                choice_metadata=choice_metadata,
                record_names=record_names,
            )
        item = _owner_decision_item(
            slot_id=slot_id,
            details=decision_details,
            message=str(row.get("message") or "The candidate needs a correction before it can continue."),
            proposed=blocker_proposed_display,
            choice_metadata=choice_metadata,
            allowed_choice_ids_by_slot=decision_allowed_choice_ids_by_slot,
            record_names=record_names,
        )
        if type(details.get("effective_cl")) is int and details.get("ordinary_talent_index") is not None:
            item["title"] = f"Choose the ordinary Talent for CL{details['effective_cl']}"
            item["context"] = {
                "effective_cl": details["effective_cl"],
                "minimum_cl": details.get("minimum_cl"),
                "ordinary_talent_index": details.get("ordinary_talent_index"),
            }
        if expected is not None:
            item["expected"] = ", ".join(_OWNER_PATH_NAMES.get(value, str(value)) for value in expected) if isinstance(expected, list) else str(expected)
        item["operation"] = str(item.get("operation") or details.get("operation") or "replace_slot_value")
        item["decision_id"] = _owner_decision_id(
            run,
            field=str(item.get("field") or "owner decision"),
            slot_id=slot_id,
            operation=item["operation"],
            # Keep the ID bound to the persisted server blocker.  Milestone
            # controls enrich the owner projection, but must not make a
            # projected label/hash impossible for the resolver to reproduce.
            blocker_sha256=sha256_json(raw_details),
        )
        item["blocker_sha256"] = sha256_json(raw_details)
        item["slot_id"] = slot_id
        item["binding"] = {
            "run_id": run.get("run_id"),
            "request_sha256": request.get("request_sha256"),
            "response_sha256": (run.get("response") or {}).get("response_sha256"),
            "content_lock_hash": request.get("content_lock_hash"),
        }
        if proposed_value is not None and blocker_proposed_display not in (None, ""):
            item["proposed"] = blocker_proposed_display
            item["ai_proposed"] = blocker_proposed_display
        decision_key = (str(item.get("field") or "owner decision"), slot_id)
        if decision_key in decision_keys:
            continue
        decision_keys.add(decision_key)
        if factory_support_blocker(row):
            blockers.append({"code": row.get("code"), "title": "Factory source support required", "message": item.get("message"), "reason": item.get("reason"), "resolving_action": "Factory update required", "recovery_action": "Factory update required", "target_step": 4, "control": {"type": "blocked", "apply_label": "Factory update required"}})
            continue
        if gm_candidate_authoring_gate_blocker(row):
            blockers.append({
                "code": row.get("code"),
                "title": "GM guidance not written yet",
                "field": item.get("field"),
                "message": (
                    "Your character build is complete and sound. Before it can be finalized, the Factory "
                    "writes GM guidance for it (notes on how a Game Master runs this character at the table) "
                    "with your Local AI, and you approve that write-up. Nothing about the character changes."
                ),
                "reason": item.get("reason"),
                "boundary": row.get("boundary") or details.get("boundary"),
                "diagnostics": sorted({
                    str(entry.get("code")) for entry in details.get("diagnostics") or [] if isinstance(entry, dict)
                }),
                "resolving_action": "Author GM candidate",
                "resolution_surface": "Review draft → Review the staged GM guidance",
                "target_step": 4,
                "control": {"type": "gm_candidate_authoring", "apply_label": "Author GM candidate"},
                "recovery_action": "Author GM candidate",
            })
            continue
        if item.get("legal_choices") or item.get("control", {}).get("type") == "text":
            blockers.append(item)
            decisions.append(item)
        else:
            # A compilation/authority failure with no frozen legal alternative
            # is a blocker, not an imaginary owner decision.  It still names
            # the exact recovery action so the owner is never left with a
            # vague "decision needed" state.
            blockers.append({
                "title": "Build blocker — replace the response",
                "field": item.get("field"),
                "message": item.get("message"),
                "reason": item.get("reason"),
                "boundary": row.get("boundary") or details.get("boundary"),
                "resolving_action": "Replace Response (recovery)",
                "resolution_surface": "AI route → response transfer",
                "target_step": 3,
                "control": {"type": "recovery", "apply_label": "Replace Response"},
                "recovery_action": "Replace Response",
            })
    for row in provenance_rows:
        if isinstance(row, dict) and row.get("status") == "unresolved":
            slot_id = str(row.get("slot_id") or "choice")
            if slot_id == "subpath_choice" and _owner_subpath_decision_not_yet_due(
                request=request,
                final_plan=final_plan,
                parsed_plan=parsed_plan,
                selected_by_slot=selected_by_slot,
            ):
                continue
            unresolved_proposed_display = name(slot_id, row.get("choice_id")) if row.get("choice_id") else "No proposal"
            reason = row.get("reason")
            message = (
                str(reason).strip().replace("_", " ")
                if isinstance(reason, str) and reason.strip()
                else f"The response did not provide a legal selection for {_OWNER_DECISION_SLOT_LABELS.get(slot_id, 'the unresolved choice')}."
            )
            decision_details = {
                **row,
                "field": row.get("field") or slot_id,
                "slot_id": slot_id,
            }
            operation = str(decision_details.get("operation") or decision_details.get("decision_operation") or "replace_slot_value")
            target_value = decision_details.get("target_value")
            if (
                operation == "replace_slot_value"
                and target_value is None
                and isinstance(decision_details.get("choice_id"), str)
            ):
                target_value = decision_details["choice_id"]
                decision_details["target_value"] = target_value
            decision_allowed_choice_ids_by_slot = allowed_choice_ids_by_slot
            if operation == "replace_slot_value":
                legality_plan = {
                    "target_cl": final_plan.get("target_cl")
                    or request.get("target_cl")
                    or (envelope.get("frozen_owner_target_cl") or {}).get("target_cl")
                }
                legal_ids = legal_slot_replacement_ids(
                    envelope,
                    legality_plan,
                    proposal_selected_by_slot,
                    slot_id,
                    target_value=target_value,
                )
                decision_details["allowed_choice_ids"] = legal_ids
                decision_allowed_choice_ids_by_slot = {
                    **allowed_choice_ids_by_slot,
                    slot_id: legal_ids,
                }
            item = _owner_decision_item(
                slot_id=slot_id,
                details=decision_details,
                message=message,
                proposed=unresolved_proposed_display,
                choice_metadata=choice_metadata,
                allowed_choice_ids_by_slot=decision_allowed_choice_ids_by_slot,
                record_names=record_names,
            )
            item["expected"] = f"One legal selection for {_OWNER_DECISION_SLOT_LABELS.get(slot_id, 'the unresolved choice')}"
            item["operation"] = str(item.get("operation") or "replace_slot_value")
            item["decision_id"] = _owner_decision_id(
                run,
                field=str(item.get("field") or slot_id),
                slot_id=slot_id,
                operation=item["operation"],
                blocker_sha256=sha256_json({
                    **row,
                    "field": row.get("field") or slot_id,
                    "slot_id": slot_id,
                }),
            )
            item["slot_id"] = slot_id
            item["binding"] = {
                "run_id": run.get("run_id"),
                "request_sha256": request.get("request_sha256"),
                "response_sha256": (run.get("response") or {}).get("response_sha256"),
                "content_lock_hash": request.get("content_lock_hash"),
            }
            decision_key = (str(item.get("field") or slot_id), slot_id)
            if decision_key in decision_keys:
                continue
            decision_keys.add(decision_key)
            if factory_support_blocker(row):
                blockers.append({"code": row.get("code"), "title": "Factory source support required", "message": item.get("message"), "reason": item.get("reason"), "resolving_action": "Factory update required", "recovery_action": "Factory update required", "target_step": 4, "control": {"type": "blocked", "apply_label": "Factory update required"}})
                continue
            if item.get("legal_choices") or item.get("control", {}).get("type") == "text":
                decisions.append(item)
            else:
                blockers.append({
                    "title": "Unresolved provenance — replace the response",
                    "field": item.get("field"),
                    "message": item.get("message"),
                    "reason": item.get("reason"),
                    "resolving_action": "Replace Response (recovery)",
                    "resolution_surface": "AI route → response transfer",
                    "target_step": 3,
                    "control": {"type": "recovery", "apply_label": "Replace Response"},
                    "recovery_action": "Replace Response",
                })

    if manual_correction_required:
        error_count = int(manual_correction.get("error_count") or len(manual_correction.get("errors") or []))
        correction_errors = manual_correction.get("errors") or []
        bounded_correction = any(
            isinstance(error, dict)
            and (
                str(error.get("field") or "").startswith("bounded_choices.")
                or str(error.get("field") or "").startswith("acquisition_intent.")
            )
            for error in correction_errors
        )
        correction_label = "bounded mechanical response" if bounded_correction else "ordinary Talent progression"
        correction_reason = (
            "Response-authored bounded mechanical omissions or illegal selections are corrected by the same AI, not selected by the owner."
            if bounded_correction
            else "AI-authored progression legality failures are corrected by the AI, not selected by the owner."
        )
        blockers.append({
            "title": f"AI correction required — {correction_label}",
            "field": manual_correction.get("response_field") or "bounded_choices",
            "message": (
                f"The Manual Chat response has {error_count} response-authored mechanical correction(s). "
                "Download the correction packet, return it to the same chat, then use Replace Response."
            ),
            "reason": correction_reason,
            "correction_required": True,
            "corrections": deepcopy(correction_errors),
            "resolving_action": "Download AI correction packet, return it to the same chat, then Replace Response",
            "resolution_surface": "AI route → correction packet → response transfer",
            "target_step": 3,
            "control": {"type": "recovery", "apply_label": "Download AI correction packet"},
            "recovery_action": "Download AI correction packet",
        })

    def proposal_rows(slot_id: str, *, include_owner_locks: bool = False) -> list[dict[str, Any]]:
        locked = owner_locked_by_slot.get(slot_id) if include_owner_locks else []
        values = locked or proposal_selected_by_slot.get(slot_id) or []
        return [
            {
                "choice_id": choice_id,
                "name": name(slot_id, choice_id),
                "provenance": "Owner" if locked else "AI proposed",
                "state": "proposed",
            }
            for choice_id in values
            if isinstance(choice_id, str)
        ]

    proposal_path_rows = proposal_rows("path_choice")
    proposal_subpath_rows = proposal_rows("subpath_choice")
    proposal_progression = []
    progression_choice = proposal_bounded.get("path_progression_by_cl") if isinstance(proposal_bounded.get("path_progression_by_cl"), dict) else {}
    for cl, path_id in sorted(progression_choice.items(), key=lambda pair: _owner_progression_sort_key(pair[0])):
        proposal_progression.append({"cl": cl, "path_id": path_id, "path": name("path_choice", path_id), "provenance": "AI proposed"})
    training_contract = envelope.get("creation_training_contract") or {}
    training_routes = training_contract.get("records") if isinstance(training_contract, dict) else {}
    training_routes = training_routes if isinstance(training_routes, dict) else {}
    talent_authority = (envelope.get("typed_choice_authority_by_slot") or {}).get("advancement_skeleton") or {}
    talent_authority = talent_authority.get("stage2_authority_by_choice") if isinstance(talent_authority, dict) else {}
    talent_authority = talent_authority if isinstance(talent_authority, dict) else {}

    def proposed_talent_sphere(record_id: str) -> str | None:
        authority = talent_authority.get(record_id) or {}
        sphere_id = authority.get("sphere_id") if isinstance(authority, dict) else None
        return name("sphere_priorities", sphere_id) if isinstance(sphere_id, str) and sphere_id else None

    proposed_training = []
    proposed_bonuses = []
    for row in proposal_acquisition.get("trained_choices") or []:
        if not isinstance(row, dict):
            continue
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        new_sphere = row.get("choice_type") == "new_sphere"
        route = training_routes.get(record_id) or {}
        route = route if isinstance(route, dict) else {}
        sphere_id = record_id if new_sphere else route.get("owning_sphere_id")
        proposed_training.append({
            **deepcopy(row),
            "name": name("sphere_priorities" if new_sphere else "advancement_skeleton", record_id),
            "sphere": name("sphere_priorities", sphere_id) if sphere_id and not new_sphere else None,
            "state": "proposed",
        })
        if new_sphere and isinstance(row.get("bonus_talent_id"), str) and row["bonus_talent_id"]:
            proposed_bonuses.append({
                "record_id": row["bonus_talent_id"],
                "name": name("advancement_skeleton", row["bonus_talent_id"]),
                "sphere_id": sphere_id,
                "sphere": name("sphere_priorities", sphere_id),
                "cl": row.get("cl"),
                "slot": row.get("slot"),
                "state": "proposed",
            })
    proposal = {
        "available": bool(proposal_projection),
        "status": "parsed_proposal_not_compiled" if proposal_projection and not scratch_sheet else "compiled_candidate",
        "identity": deepcopy(proposal_identity),
        "paths": proposal_path_rows,
        "subpaths": proposal_subpath_rows,
        "method": {"choice_id": (proposal_selected_by_slot.get("method_choice") or [None])[0], "name": name("method_choice", (proposal_selected_by_slot.get("method_choice") or [None])[0]) if proposal_selected_by_slot.get("method_choice") else None},
        "foundation": {"choice_id": (proposal_selected_by_slot.get("foundation_choice") or [None])[0], "name": name("foundation_choice", (proposal_selected_by_slot.get("foundation_choice") or [None])[0]) if proposal_selected_by_slot.get("foundation_choice") else None},
        "background": proposal_rows("background_choice", include_owner_locks=True),
        "background_sphere": proposal_rows("background_sphere_choice", include_owner_locks=True),
        "background_talent": proposal_rows("background_talent_choice", include_owner_locks=True),
        "spheres": proposal_rows("sphere_priorities"),
        "talents": proposal_rows("advancement_skeleton"),
        "insights": proposal_rows("insight_priorities"),
        "items": proposal_rows("item_priorities"),
        "acquisitions": {
            "sphere_free_talent_pairs": [
                {"sphere": name("sphere_priorities", row.get("sphere_id")), "talent": name("advancement_skeleton", row.get("talent_id"))}
                for row in proposal_acquisition.get("sphere_free_talent_pairs") or []
                if isinstance(row, dict)
            ],
            "ordinary_talents": [name("advancement_skeleton", value) for value in proposal_acquisition.get("ordinary_talent_ids") or []],
            "level_talents": [
                {"record_id": value, "name": name("advancement_skeleton", value), "sphere": proposed_talent_sphere(value), "cl": cl, "state": "proposed"}
                for cl, value in enumerate(proposal_acquisition.get("ordinary_talent_ids") or [], start=1)
            ],
            "trained_choices": proposed_training,
            "new_sphere_bonus_talents": proposed_bonuses,
            "insight_occurrences": [
                {"insight": name("insight_priorities", row.get("insight_id")), "milestone_id": row.get("milestone_id"), "parameters": deepcopy(row.get("parameters") or {})}
                for row in proposal_acquisition.get("insight_occurrences") or []
                if isinstance(row, dict)
            ],
        },
        "ability_scores": deepcopy(proposal_bounded.get("ability_scores") or {}),
        "ability_score_changes": deepcopy(proposal_bounded.get("ability_score_changes_by_milestone_id") or {}),
        "progression": proposal_progression,
    }
    proposal["sphere_inventory"] = _owner_sphere_inventory(
        run=run,
        envelope=envelope,
        proposal_selected_by_slot=proposal_selected_by_slot,
        owner_locked_by_slot=owner_locked_by_slot if isinstance(owner_locked_by_slot, dict) else {},
        proposal_acquisition=proposal_acquisition if isinstance(proposal_acquisition, dict) else {},
        # The owner's wizard priorities are the binding request; a proposal may
        # only add to that list, never hide a requested Sphere from the review.
        planning_sphere_ids=list(dict.fromkeys([
            *[value for value in (project_planning.get("sphere_priority_ids") or []) if isinstance(value, str) and value],
            *(planning_preferences.get("sphere_priorities") or []),
        ])),
        talent_authority=talent_authority,
        training_routes=training_routes,
        scratch_sheet=scratch_sheet,
        name=name,
    )

    outputs = run.get("outputs") or {}
    outputs = outputs if isinstance(outputs, dict) else {}
    portable = outputs.get("portable_character") or {}
    gm_consumer = outputs.get("gm_consumer") or {}
    portable_audit = portable.get("audit") if isinstance(portable, dict) else None
    portable_audit = portable_audit if isinstance(portable_audit, dict) else {}
    portable_clean_import = portable.get("clean_import") if isinstance(portable, dict) else None
    portable_clean_import = portable_clean_import if isinstance(portable_clean_import, dict) else {}
    portable_first_import = portable_clean_import.get("first") if isinstance(portable_clean_import.get("first"), dict) else {}
    portable_second_import = portable_clean_import.get("second") if isinstance(portable_clean_import.get("second"), dict) else {}
    portable_verified = (
        bool(portable.get("package_sha256"))
        and portable_audit.get("sha256") == portable.get("package_sha256")
        and isinstance(portable_audit.get("bytes"), int)
        and portable_audit.get("crc_validation", {}).get("status") == "VALID"
        and portable_audit.get("checksum_manifest", {}).get("coverage_status") == "EXACT"
        and portable_first_import.get("status") in {"IMPORTED", "ALREADY_INSTALLED_IDENTICAL", "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"}
        and portable_second_import.get("status") in {"ALREADY_INSTALLED_IDENTICAL", "IMPORTED", "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"}
    )
    completed_available = status == "CLEAN_AND_FINALIZED" and portable_verified
    gm_available = gm_consumer.get("status") in {"GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "VERIFIED", "PASS"}
    selected_foundation_id = resolution.get("foundation_id") or (
        proposal_selected_by_slot.get("foundation_choice") or [None]
    )[0]
    return {
        "schema": "TianxiaFoundry.CharacterCreationOwnerView.v1",
        "display_state": {"status": status, "step": stage, "label": status.replace("_", " ").title()},
        "identity": {
            "name": accepted_name or proposed_name or (scratch_sheet or {}).get("identity", {}).get("name") or "Name pending owner review",
            "concept": accepted_concept or proposed_concept or (scratch_sheet or {}).get("identity", {}).get("concept") or "Concept pending owner review",
            "title": projected_title,
            "name_provenance": "Owner" if accepted_name else "AI proposed" if proposed_name else "Needs owner decision",
            "concept_provenance": "Owner" if accepted_concept else "AI proposed" if proposed_concept else "Needs owner decision",
            "title_provenance": projected_title_provenance,
            "target_cl": final_plan.get("target_cl") or (preview.get("target_cl") if isinstance(preview, dict) else None) or "pending",
            "power_band": _owner_lock_value(run, "power_band") or "pending",
        },
        "paths": paths,
        "method": {
            "name": name("method_choice", selected_method_id) if selected_method_id else "Method deferred (none at creation, which the rules allow)",
            "provenance": "Owner" if selected_method_id in (
                set(owner_locked_by_slot.get("method_choice") or []) | method_planning_lock_ids
            ) else "AI proposed" if selected_method_id else "Deferred",
            "planning_lock": {
                "choice_ids": sorted(method_planning_lock_ids),
                "mode": method_planning_lock.get("mode"),
                "planning_authority": method_planning_lock.get("planning_authority"),
                "acquisition_authority": method_planning_lock.get("acquisition_authority"),
                "access_authority": deepcopy(method_planning_lock.get("access_authority") or {}),
            } if method_planning_lock else None,
             "direct_access": direct_access,
             "access_required": access_required,
             "route_configurable": method_access_metadata.get("route_configurable"),
             "access_authorized": method_access_metadata.get("access_authorized"),
             "exact_access_record_present": method_access_metadata.get("exact_access_record_present"),
             "access_tier": method_access_metadata.get("access_tier"),
            "access_text": method_access_metadata.get("access_text") or method_access_metadata.get("owner_description") or "",
            "owner_route_options": deepcopy(method_access_metadata.get("owner_route_options") or []),
            "exact_selection_available": exact_lock_configurable,
            "exact_lock_configurable": exact_lock_configurable,
        },
        "foundation": {
            "name": name("foundation_choice", selected_foundation_id) if selected_foundation_id else "No Foundation proposal supplied",
            "provenance": "Owner" if selected_foundation_id in (owner_locked_by_slot.get("foundation_choice") or []) else "AI proposed" if selected_foundation_id else "Needs owner decision",
        },
        "tradition": {"name": name("subpath_choice", (selected_by_slot.get("subpath_choice") or [None])[0]) if (selected_by_slot.get("subpath_choice") or []) else "No Path-owned Subpath proposal supplied", "provenance": "Owner" if selected_by_slot.get("subpath_choice") else "Needs owner decision"},
        "subpaths": subpath_rows,
        "subpath_bindings": subpath_bindings,
        "planning_preferences": {
            "sphere_priorities": planning_spheres,
            "talent_priorities": planning_talents,
            "insight_priorities": planning_insights,
            "item_priorities": planning_items,
        },
        "planning_items": planning_items,
        "proposal": proposal,
        "provenance_groups": provenance_groups,
        "decisions": decisions,
        "blockers": blockers,
        "ai_correction_required": manual_correction_required,
        "review": {
            "status": "ai_correction_required" if manual_correction_required else "blocked" if decisions else "ready_for_owner_approval" if status == "READY_FOR_REVIEW" else "not_ready",
            "approval_required": status == "READY_FOR_REVIEW" and not decisions and not manual_correction_required,
            "summary": (
                "The Manual Chat response needs an AI correction packet. Return the corrected response to the same chat, then use Replace Response."
                if manual_correction_required
                else
                "The compiled proposal is clean. Review the source-backed proposal, then choose Finalize Character to accept it."
                if status == "READY_FOR_REVIEW" and not decisions
                else "Resolve each item above with the named action before continuing."
                if decisions
                else "The response has not reached compiled review."
            ),
            "resolving_action": "Download AI correction packet" if manual_correction_required else "Finalize Character" if status == "READY_FOR_REVIEW" and not decisions else "Review blockers",
        },
        "next_legal_action": {
            # Every post-build action is reachable from step 4 (plan Part A);
            # only the pre-build states still point at steps 1-3.
            "target_step": {
                "PREPARING_REQUEST": 3,
                "WAITING_FOR_RESPONSE": 3,
                "READY_FOR_REVIEW": 4,
                "NEEDS_REVIEW": 4,
                "CLEAN_AND_FINALIZED": 4,
                "REVISED": 3,
                "CANCELLED": 1,
            }.get(status, 1),
            "label": {
                "WAITING_FOR_RESPONSE": "Load one response",
                "PREPARING_REQUEST": "Open the AI route",
                "READY_FOR_REVIEW": "Resolve owner decision" if decisions else "Review and finalize proposal",
                 "NEEDS_REVIEW": "Download AI correction packet" if manual_correction_required else "Author GM candidate" if gm_candidate_gate else "Ask Local AI to Fix This" if local_correction_available else "Resolve owner decision" if decisions else "Resolve the review blocker",
                "CLEAN_AND_FINALIZED": "Open the saved Character Sheet on this page",
                "CANCELLED": "Start a deliberate new build",
                "REVISED": "Load the replacement response",
            }.get(status, "Describe a character"),
            "description": {
                "WAITING_FOR_RESPONSE": "The sealed request is ready for one matching Manual Chat response.",
                "PREPARING_REQUEST": "The Factory is preparing the complete-character route.",
                "READY_FOR_REVIEW": (
                    "Use the named owner decision control in review before finalization."
                    if decisions
                    else "The candidate is clean. Review the proposal, then choose Finalize Character to accept it."
                ),
                 "NEEDS_REVIEW": (
                     "Download the AI correction packet, return it to the same chat, then use Replace Response."
                     if manual_correction_required
                     else
                     GM_CANDIDATE_AUTHORING_NEXT_ACTION
                     if gm_candidate_gate
                     else
                     "Ask Local AI to Fix This sends the exact retained response and validator issue to the selected Local AI while keeping this request frozen."
                     if local_correction_available
                     else
                     "Use the named owner decision control in review before choosing the next legal action."
                     if decisions
                     else "Correct the item described in the review before choosing the next legal action."
                ),
                "CLEAN_AND_FINALIZED": "The persisted owner Character Sheet is ready to open.",
                "CANCELLED": "No canonical character mutation was committed.",
                "REVISED": "A linked replacement request is ready for its response.",
            }.get(status, "The brief and target CL are required before a build can start."),
        },
        "action_availability": {
            key: {"available": bool(value.get("available")), "reason": str(value.get("reason") or "")}
            for key, value in (run.get("action_availability") or {}).items()
            if isinstance(value, dict)
        },
        "export_availability": {
            "project_backup": {"available": bool(run.get("project_id")), "reason": "Available for the current project." if run.get("project_id") else "Create a project first."},
            "chat_request": {"available": bool(request.get("request_sha256")), "reason": "Available while a sealed request exists." if request.get("request_sha256") else "Prepare the AI route first."},
            "completed_character": {"available": completed_available, "reason": "Validated completed Character ZIP is available." if completed_available else "Available only after the server records a verified Finalize package."},
            "gm_package": {"available": gm_available, "reason": "GM package is separately verified." if gm_available else "GM-only verification remains a separate gate."},
        },
        "scratch_candidate": {
            "available": bool(scratch_sheet),
            "deterministic": dry_run.get("deterministic") is True,
            "independent_compilations": dry_run.get("independent_compilations") if dry_run else None,
            "sheet": scratch_sheet,
        },
        "diagnostics_available": True,
    }


def _bounded_diagnostic_summary(value: Any, *, section: str) -> dict[str, Any]:
    """Keep ordinary run responses bounded while retaining technical breadcrumbs.

    The complete evidence endpoint intentionally remains the full-fidelity
    boundary.  Diagnostics in the owner response carry hashes, counts, and
    the small values needed to explain a state, never the complete plan or
    validator receipt tree.
    """
    raw = value if isinstance(value, dict) else {}
    summary: dict[str, Any] = {
        "section": section,
        "present": bool(raw),
        "sha256": sha256_json(raw),
        "size_bytes": len(canonical_json(raw).encode("utf-8")),
        "top_level_keys": sorted(str(key) for key in raw)[:32],
        "full_evidence": "GET /api/character-creation/runs/{run_id}/evidence.json",
    }
    if section == "final_plan":
        resolution = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else {}
        selected = resolution.get("selected_choices_by_slot") if isinstance(resolution.get("selected_choices_by_slot"), dict) else {}
        summary.update({
            "target_cl": raw.get("target_cl"),
            "method_id": resolution.get("method_id"),
            "foundation_id": resolution.get("foundation_id"),
            "selected_path_count": len(resolution.get("selected_path_ids") or []),
            "actual_advancing_path_count": len(resolution.get("actual_advancing_path_ids") or []),
            "selected_choice_counts": {str(key): len(value) if isinstance(value, list) else 0 for key, value in selected.items()},
        })
    elif section == "validation":
        last_error = raw.get("last_submission_error") if isinstance(raw.get("last_submission_error"), dict) else {}
        summary.update({
            "valid": raw.get("valid"),
            "status": raw.get("status"),
            "error_count": len(raw.get("errors") or []),
            "blocker_count": len(raw.get("blockers") or []),
            "warning_count": len(raw.get("warnings") or []),
            "response_state": deepcopy(raw.get("response_state") or {}),
            "last_submission_error": {key: last_error.get(key) for key in ("code", "message", "category", "stage", "boundary", "json_parsed", "response_retained") if key in last_error},
        })
    elif section == "transport":
        summary.update({
            "provider_called": raw.get("provider_called"),
            "provider_id": raw.get("provider_id"),
            "execution_mode": raw.get("execution_mode"),
            "status": raw.get("status"),
            "fallback": raw.get("fallback"),
        })
    return summary


def _bounded_portable_output(portable: Any) -> dict[str, Any] | None:
    if not isinstance(portable, dict):
        return None
    audit = portable.get("audit") if isinstance(portable.get("audit"), dict) else {}
    clean = portable.get("clean_import") if isinstance(portable.get("clean_import"), dict) else {}
    first = clean.get("first") if isinstance(clean.get("first"), dict) else {}
    second = clean.get("second") if isinstance(clean.get("second"), dict) else {}
    gm_export = portable.get("gm_export") if isinstance(portable.get("gm_export"), dict) else {}
    return {
        "package_sha256": portable.get("package_sha256"),
        "release_identity": portable.get("release_identity"),
        "portable_verified": bool(
            portable.get("package_sha256")
            and audit.get("sha256") == portable.get("package_sha256")
            and audit.get("crc_validation", {}).get("status") == "VALID"
            and audit.get("checksum_manifest", {}).get("coverage_status") == "EXACT"
            and first.get("status") == "IMPORTED"
            and second.get("status") == "ALREADY_INSTALLED_IDENTICAL"
        ),
        "audit": {
            "bytes": audit.get("bytes"),
            "sha256": audit.get("sha256"),
            "entry_count": audit.get("entry_count"),
            "crc_status": audit.get("crc_validation", {}).get("status"),
            "checksum_coverage": audit.get("checksum_manifest", {}).get("coverage_status"),
        } if audit else None,
        "clean_import": {
            "first_status": first.get("status"),
            "second_status": second.get("status"),
            "character_sheet_semantic_equal": (clean.get("character_sheet") or {}).get("semantic_equal"),
            "gm_model_semantic_equal": (clean.get("gm_model") or {}).get("semantic_equal"),
            "consumer_status": (clean.get("consumer") or {}).get("status"),
        } if clean else None,
        "gm_export": {
            key: gm_export.get(key)
            for key in ("available", "status", "package_sha256", "sha256")
            if key in gm_export
        } if gm_export else None,
    }


def _bounded_gm_consumer_output(consumer: Any) -> dict[str, Any] | None:
    if not isinstance(consumer, dict):
        return None
    result = {
        key: consumer.get(key)
        for key in (
            "status", "verdict", "consumer_status", "source_consumer_verified",
            "save_reload_semantic_equivalence", "all_tabs_nonempty", "exact_tab_order",
            "local_save_package_count", "selected_id", "semantic_hash", "console_or_page_errors",
        )
        if key in consumer
    }
    harness = consumer.get("browser_harness")
    if isinstance(harness, dict):
        result["browser_harness"] = {
            key: harness.get(key)
            for key in ("status", "runtime_kind", "requested_executable", "resolved_executable", "screenshot_count", "console_errors", "page_errors", "failed_requests")
            if key in harness
        }
    return result


def _character_creation_api_view(run: dict[str, Any]) -> dict[str, Any]:
    """Bound the owner UI payload without weakening the stored canonical run.

    Complete scratch receipts and the exact typed choice snapshot remain in the
    server-owned run. The browser receives stable identities and compact receipts;
    the full snapshot has a dedicated review/download endpoint.
    """
    result = {
        key: value
        for key, value in run.items()
        if key not in {"request", "dry_run", "outputs", "final_plan", "response", "owner_decision_authority", "controller_route_status"}
    }
    request = dict(run.get("request") or {})
    result["request"] = {
        key: request.get(key)
        for key in ("schema", "project_id", "project_revision", "request_sha256", "content_lock_hash", "controller_route")
        if key in request
    }
    result["request"]["typed_choice_snapshot"] = _choice_snapshot_api_binding(request.get("typed_choice_snapshot"))
    # Public clients receive only route state and hashes.  The sealed version
    # binding and event bodies remain an internal recovery projection.
    route_status = run.get("controller_route_status")
    if isinstance(route_status, dict):
        result["controller_route_status"] = {
            key: route_status.get(key)
            for key in (
                "schema", "run_id", "project_id", "mode", "route_mode", "state",
                "activation_policy", "request_sha256", "binding_sha256",
                "event_count", "event_head_sha256", "controller_version_sha256",
                "operator_contract_sha256", "publication_receipt_sha256",
                "content_snapshot_sha256", "semantic_authority_bundle_sha256",
                "source_rights_authority_sha256", "selected_ai_identity_sha256",
                "selected_ai_identity_state",
            )
            if key in route_status
        }
        # The linear walk position is owner-facing progress: position and
        # state only, never menus, cues, IDs, or hashes.
        walk = route_status.get("walk")
        if isinstance(walk, dict):
            result["controller_route_status"]["walk"] = {
                key: walk.get(key) for key in ("state", "step_ordinal", "steps_estimate") if key in walk
            }
    result["response"] = {"response_sha256": (run.get("response") or {}).get("response_sha256")} if run.get("response") else {}
    dry = run.get("dry_run") or {}
    preview = dry.get("preview") or {}
    result["dry_run"] = {
        key: dry.get(key)
        for key in (
            "schema",
            "candidate_identity",
            "identities",
            "deterministic",
            "independent_compilations",
        )
        if key in dry
    }
    if dry:
        result["dry_run"]["typed_choice_snapshot"] = _choice_snapshot_api_binding(
            dry.get("typed_choice_snapshot")
        )
        result["dry_run"]["preview"] = {
            "identity": preview.get("identity"),
            "target_cl": preview.get("target_cl"),
            "uncertainties": preview.get("uncertainties") or [],
            "fallbacks": preview.get("fallbacks") or [],
            "readiness": {
                key: {
                    receipt_key: receipt.get(receipt_key)
                    for receipt_key in ("service", "identity", "verification_status")
                }
                for key, receipt in (preview.get("readiness") or {}).items()
                if isinstance(receipt, dict)
            },
        }
        # The owner view receives a bounded scratch-sheet projection below;
        # never send the compiled scratch receipt itself to the browser.
    outputs = run.get("outputs") or {}
    portable = outputs.get("portable_character") or {}
    catalog_evidence = outputs.get("catalog_acquisition_evidence") or {}
    result["outputs"] = {
        "projection": {
            key: (outputs.get("projection") or {}).get(key)
            for key in ("status", "projection_id", "input_hash", "event_head_hash", "content_lock_hash")
        } if outputs.get("projection") else None,
        "character_sheet": {
            key: (outputs.get("character_sheet") or {}).get(key)
            for key in ("build_status", "project_id", "projection_id")
        } if outputs.get("character_sheet") else None,
        "factory_authoring": {"produced": bool(outputs.get("factory_authoring"))},
        "gm_model": {"produced": bool(outputs.get("gm_model"))},
        "gm_consumer": _bounded_gm_consumer_output(outputs.get("gm_consumer")),
        "portable_character": _bounded_portable_output(portable),
        "catalog_acquisition_evidence": {
            key: catalog_evidence.get(key)
            for key in (
                "schema",
                "project_id",
                "character_id",
                "run_id",
                "candidate_identity",
                "typed_choice_snapshot_sha256",
                "issuance_route",
                "record_count",
            )
        } | {
            "records": [
                {
                    key: row.get(key)
                    for key in (
                        "evidence_id",
                        "authority_type",
                        "canonical_content_id",
                        "binding_type",
                        "binding_id",
                        "catalog_record_commitment_sha256",
                        "character_id",
                        "issuance_route",
                        "source_record_id",
                        "source_hash",
                        "evidence_hash",
                    )
                }
                for row in catalog_evidence.get("records") or []
                if isinstance(row, dict)
            ]
        } if catalog_evidence else None,
        "combat": _bounded_diagnostic_summary(outputs.get("combat"), section="combat") if outputs.get("combat") else None,
    }
    result["owner_view"] = _owner_view(run)
    result["next_legal_action"] = result["owner_view"]["next_legal_action"]["description"]
    result["diagnostics"] = {
        "request": {
            "request_sha256": request.get("request_sha256"),
            "content_lock_hash": request.get("content_lock_hash"),
            "typed_choice_snapshot": _choice_snapshot_api_binding(request.get("typed_choice_snapshot")),
        },
        "response": {"response_sha256": (run.get("response") or {}).get("response_sha256")},
        "final_plan": _bounded_diagnostic_summary(run.get("final_plan"), section="final_plan"),
        "validation": _bounded_diagnostic_summary(run.get("validation"), section="validation"),
        "transport": _bounded_diagnostic_summary(run.get("transport"), section="transport"),
        "full_evidence_endpoint": f"/api/character-creation/runs/{run.get('run_id')}/evidence.json",
    }
    return result


def _is_allowed_loopback_origin(origin: str) -> bool:
    """Accept only a parsed HTTP Origin whose hostname is exactly loopback."""
    try:
        parsed = urlsplit(origin)
        _ = parsed.port  # Force malformed ports to raise ValueError.
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in _LOOPBACK_ORIGIN_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
    )


def _request_timing_message(request: Request, status: int, elapsed_ms: float) -> str:
    """Return the bounded request-timing line without query or body data."""

    return (
        f"request method={request.method} path={request.url.path or '/'} "
        f"status={int(status)} ms={float(elapsed_ms):.3f}"
    )


_COMPLETED_CHARACTER_VERIFIED_STATUS = "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"


def _verified_completed_character_source(
    portable_characters: PortableCharacterPackageService,
    project_id: str,
) -> tuple[Path, dict[str, Any]]:
    """Return the current verified package without producing a new export."""
    try:
        result = portable_characters.verified_status(project_id)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise FoundryError(
            "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT",
            "The verified completed Character package is unavailable or no longer current.",
            status_code=409,
        ) from exc
    if not isinstance(result, dict) or result.get("status") != _COMPLETED_CHARACTER_VERIFIED_STATUS:
        raise FoundryError(
            "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT",
            "The verified completed Character package is unavailable or no longer current.",
            details={"project_id": project_id, "status": result.get("status") if isinstance(result, dict) else None},
            status_code=409,
        )
    if result.get("project_id") != project_id:
        raise FoundryError(
            "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT",
            "The verified completed Character package is unavailable or no longer current.",
            details={"project_id": project_id, "reason": "PROJECT_ID_MISMATCH"},
            status_code=409,
        )
    package_path = result.get("package_path")
    package_sha256 = result.get("package_sha256")
    audit = result.get("audit")
    if not isinstance(package_path, str) or not package_path.strip() or not isinstance(package_sha256, str) or not isinstance(audit, dict):
        raise FoundryError(
            "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT",
            "The verified completed Character package is unavailable or no longer current.",
            details={"project_id": project_id, "reason": "VERIFICATION_EVIDENCE_INCOMPLETE"},
            status_code=409,
        )
    try:
        source = Path(package_path).resolve()
        audit_path = Path(audit.get("path") or "").resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise FoundryError(
            "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT",
            "The verified completed Character package is unavailable or no longer current.",
            status_code=409,
        ) from exc
    try:
        current_sha256 = sha256_file(source) if source.is_file() else None
    except OSError:
        current_sha256 = None
    audit_manifest = audit.get("manifest")
    if (
        not source.is_file()
        or current_sha256 != package_sha256
        or audit.get("valid") is not True
        or audit.get("sha256") != package_sha256
        or audit_path != source
        or not isinstance(audit_manifest, dict)
        or audit_manifest.get("project_id") != project_id
    ):
        raise FoundryError(
            "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT",
            "The verified completed Character package is unavailable or no longer current.",
            details={"project_id": project_id, "reason": "PACKAGE_IDENTITY_MISMATCH"},
            status_code=409,
        )
    return source, result


def create_app(
    settings: Settings | None = None,
    *,
    ai_transport: Any = None,
    ai_secret_store: Any = None,
    principal_provider: PrincipalProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    timing_logger = configure_timing_logger(settings.logs_dir)
    db = Database(settings)
    db.migrate()
    # This existing additive schema setup normally runs in the provider
    # constructor. Finish it before snapshots so later construction cannot
    # invalidate the deletion backup's schema. It launches no provider work.
    from ai_provider.agent_bridge import AgentRequestBridge
    AgentRequestBridge(db).ensure_schema()
    # No publisher, cache warmer or HTTP handler exists yet. Process
    # synchronously here rather than in a later event alongside background work.
    deletion_queue = ProjectDeletionQueue(db)
    startup_deletions = deletion_queue.process_at_startup()
    catalog = CatalogService(db)
    non_sphere_authority = NonSphereAuthorityService(db)
    canonical_catalog = CanonicalCatalogAuthorityService(
        settings.root_dir, evidence_resolver=non_sphere_authority.resolve_evidence,
    )
    source_principal_provider = principal_provider or ProcessPrincipalProvider()
    principal = source_principal_provider.current_principal()
    principal_provider = BoundPrincipalProvider(principal)
    final_character_integrity = IntegrityService.for_database(db)
    packs = ContentPackManager(db, principal_provider=principal_provider)
    projects = ProjectStore(db, principal_provider=principal_provider)
    character_library_archives = CharacterLibraryArchiveService(db)
    vendor = FactoryAdapter(db)
    projections = ProjectionService(db)
    schema_registry = SchemaRegistry(settings.root_dir)
    stage1 = Stage1ClipboardService(db)
    character_builder = CharacterBuilderService(db)
    character_sheets = CharacterSheetService(db)
    gm_exports = GMCharacterExportService(db)
    portable_characters = PortableCharacterPackageService(db)
    final_character_workflow = FinalCharacterWorkflowService(
        db,
        principal_provider=principal_provider,
        integrity=final_character_integrity,
    )
    factory_authoring = FactoryAuthoringWorkspaceService(
        db,
        principal_provider=principal_provider,
        integrity=final_character_integrity,
        final_character_workflow=final_character_workflow,
    )
    ai_provider = AIProviderService(db, transport=ai_transport, secret_store=ai_secret_store)
    stage2 = Stage2AdvancementService(db, principal_provider=principal_provider)
    character_creation = CharacterCreationExecutionService(
        db, stage1=stage1, provider=ai_provider, project_store=projects, stage2=stage2,
        character_sheets=character_sheets, gm_exports=gm_exports,
        portable_characters=portable_characters, factory_authoring=factory_authoring,
        projections=projections, production_release=CharacterProductionReleaseAdapter(db), owner_principal=principal.principal_id,
        timing_logger=timing_logger,
    )
    combat = CombatService(settings.root_dir, settings.data_dir, ai_provider=ai_provider)
    combatant_library = combat.combatant_library  # one cached install audit for the whole app (same roots)

    def _warm_combatant_inventory() -> None:
        try:
            combatant_library.inventory()
        except Exception:  # noqa: BLE001 - a warm-up only; the request path reports real errors
            pass

    threading.Thread(target=_warm_combatant_inventory, name="combatant-inventory-warm", daemon=True).start()
    product_readiness = ProductReadinessService(db)
    session_token = secrets.token_urlsafe(32)
    staged_owner_artifacts: dict[str, dict[str, Any]] = {}

    app = FastAPI(
        title="Tianxia Character Foundry",
        version=APP_VERSION,
        description="Local Tianxia Factory with deterministic character workflows and the Gate 5 persistent hybrid-combat vertical slice.",
    )
    # Table snapshots contain repeated movement/perception data. Gzip keeps the
    # decoded JSON unchanged while reducing the bytes sent to the browser.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.state.settings = settings
    app.state.db = db
    app.state.project_deletion_queue = deletion_queue
    app.state.startup_deletions = startup_deletions
    app.state.catalog = catalog
    app.state.canonical_catalog = canonical_catalog
    app.state.packs = packs
    app.state.projects = projects
    app.state.character_library_archives = character_library_archives
    app.state.vendor = vendor
    app.state.projections = projections
    app.state.schema_registry = schema_registry
    app.state.stage1 = stage1
    app.state.character_builder = character_builder
    app.state.character_sheets = character_sheets
    app.state.gm_exports = gm_exports
    app.state.portable_characters = portable_characters
    app.state.factory_authoring = factory_authoring
    app.state.final_character_workflow = final_character_workflow
    app.state.ai_provider = ai_provider
    app.state.character_creation = character_creation
    # Quick Build: batches of seeded or Local AI characters (owner 2026-09-24).
    from character_creation.quick_build import QuickBuildQueue

    quick_builds = QuickBuildQueue(
        settings.data_dir / "quick_builds",
        create_project=character_builder.create_project,
        lock_choices=character_builder.commit_normal_first_cycle_catalog_choices,
        start_run=character_creation.start,
        finalize_run=character_creation.finalize,
    )
    app.state.quick_builds = quick_builds
    app.state.stage2 = stage2
    app.state.combat = combat
    app.state.combatant_library = combatant_library
    app.state.product_readiness = product_readiness
    app.state.non_sphere_authority = non_sphere_authority
    app.state.session_token = session_token
    app.state.principal = principal
    app.state.principal_provider = principal_provider
    app.state.timing_logger = timing_logger

    app.state.character_builder_startup_cleanup = None
    app.state.character_builder_shutdown_cleanup = None

    @app.on_event("startup")
    def cleanup_abandoned_temporary_characters() -> None:
        app.state.character_builder_startup_cleanup = projects.cleanup_temporary_projects(
            reason="startup_after_interrupted_or_abandoned_builder"
        )
        _schedule_library_summary_fill()

    @app.on_event("shutdown")
    def cleanup_unfinished_temporary_characters() -> None:
        ai_provider.stop_local_runtime()
        app.state.character_builder_shutdown_cleanup = projects.cleanup_temporary_projects(
            reason="normal_factory_shutdown"
        )

    @app.middleware("http")
    async def loopback_security(request: Request, call_next):
        started = time.perf_counter()
        response: Response | None = None
        try:
            host = request.headers.get("host", "").split(":", 1)[0].lower()
            allowed_hosts = {"127.0.0.1", "localhost", "[::1]", "testserver"}
            if host not in allowed_hosts:
                response = JSONResponse(status_code=403, content={"error": {"code": "NON_LOOPBACK_HOST", "message": "Only loopback requests are accepted.", "details": {"host": host}}})
                return response
            origin = request.headers.get("origin")
            if origin and not _is_allowed_loopback_origin(origin):
                response = JSONResponse(status_code=403, content={"error": {"code": "ORIGIN_REJECTED", "message": "Request origin is not permitted.", "details": {"origin": origin}}})
                return response
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                token = request.headers.get("x-foundry-token")
                if token != session_token:
                    response = JSONResponse(status_code=403, content={"error": {"code": "CSRF_TOKEN_REQUIRED", "message": "A valid local session token is required for mutations.", "details": None}})
                    return response
            response = await call_next(request)
            return response
        except Exception:
            # ServerErrorMiddleware may handle the exception outside this
            # middleware; retain a bounded 500 timing record and re-raise.
            raise
        finally:
            status = response.status_code if response is not None else 500
            elapsed_ms = (time.perf_counter() - started) * 1000
            # request.url.path deliberately excludes query strings.  The
            # formatter also JSON-escapes control characters before writing.
            timing_logger.info(_request_timing_message(request, status, elapsed_ms))

    @app.exception_handler(FoundryError)
    async def foundry_error_handler(request: Request, exc: FoundryError):
        db.record_error(exc.code, exc.message, exc.details)
        if not _is_final_character_route(request):
            return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": _redact_final_character_error_value(exc.message),
                    "details": _redact_final_character_error_value(exc.details),
                }
            },
        )

    @app.exception_handler(CombatServiceError)
    async def combat_error_handler(_request: Request, exc: CombatServiceError):
        db.record_error(exc.diagnostic.code, exc.diagnostic.message, exc.diagnostic.as_dict())
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "REQUEST_SCHEMA_INVALID", "message": "Request body or parameters failed schema validation.", "details": exc.errors()}},
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        db.record_error("UNEXPECTED_ERROR", str(exc))
        if _is_final_character_route(request):
            details = _redact_final_character_error_value(str(exc))
        else:
            details = str(exc)
        return JSONResponse(status_code=500, content={"error": {"code": "UNEXPECTED_ERROR", "message": "An unexpected local application error occurred.", "details": details}})

    @app.get("/api/session")
    def session() -> dict[str, Any]:
        return {"token": session_token, "bound_host": "127.0.0.1", "principal": principal.as_dict()}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        readiness = product_readiness.report()
        return {
            "ok": True,
            "process_live": True,
            "version": APP_VERSION,
            "status": readiness["status"],
            "clean_root_bootstrap_lineage_status": readiness.get("clean_root_bootstrap_lineage_status"),
            "declared_checkpoint_status": APP_STATUS,
            "data_directory": str(settings.data_dir),
            "database": str(settings.db_path),
            "bound_host": "127.0.0.1",
            "database_ready": readiness["database"]["ready"],
            "producer_corpus_ready": readiness["producer_corpus"]["ready"],
            "factory_adapter_ready": readiness["factory_adapter"].get("health") == "READY",
            "catalog_ready": int(readiness["catalog"].get("record_count") or 0) > 0,
            "canonical_catalog_ready": readiness.get("canonical_catalog_authority", {}).get("ready", False),
            "character_creation_ready": readiness["character_creation"]["ready"],
            "portable_import_ready": readiness["portable_import"]["ready"],
            "gm_consumer_ready": readiness["gm_consumer"]["ready"],
            "combat_runtime_ready": readiness["combat_runtime"]["ready"],
            "native_windows_status": NATIVE_WINDOWS_STATUS,
            "blocking_reasons": readiness["blocking_reasons"],
            "readiness": readiness,
        }

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        return {"foundry_version": APP_VERSION, "gm_screen_target": GM_SCREEN_VERSION, "gm_screen_hash": EXPECTED_GM_SCREEN_HASH}

    # Per-project list caches (smoke test 2026-09-25: /api/characters took 151 s and
    # /api/character-library 25 s, re-reading every project's multi-megabyte records on each
    # call, and the builder page asked three times at once).  A project's row is rebuilt only
    # when one of its cheap change markers moves: project revision/update time, lifecycle, its
    # newest build run, its newest projection, or its per-project data folders.
    _list_cache_lock = threading.Lock()      # the Character Sheets list
    _library_cache_lock = threading.Lock()   # the builder's character library
    _characters_row_cache: dict[str, tuple[Any, dict[str, Any]]] = {}
    _library_identity_cache: dict[str, tuple[Any, Any]] = {}
    _library_summary_fill_lock = threading.Lock()
    _library_summary_fills: set[str] = set()
    _library_summary_worker_lock = threading.Lock()
    _library_summary_worker_active = False
    _project_dirs = ("portable_characters", "factory_workspaces", "character_sheets", "factory_candidates", "projects")

    def _project_fingerprints(connection: Any = None, project_id: str | None = None) -> dict[str, tuple]:
        with (nullcontext(connection) if connection is not None else projects.db.connection()) as conn:
            rows = conn.execute(
                """SELECT p.project_id, p.updated_at, p.revision, l.updated_at, l.persistence_state,
                          (SELECT max(r.updated_at) FROM character_creation_runs r WHERE r.project_id = p.project_id),
                          (SELECT count(*) FROM character_creation_runs r WHERE r.project_id = p.project_id),
                          (SELECT max(pr.created_at) FROM projection_runs pr WHERE pr.project_id = p.project_id),
                          (SELECT revision FROM project_library_source_revision v WHERE v.project_id = p.project_id)
                   FROM projects p LEFT JOIN character_builder_project_lifecycle l ON l.project_id = p.project_id
                   WHERE NOT EXISTS (SELECT 1 FROM project_deletion_requests q
                       WHERE q.project_id=p.project_id AND q.status IN ('queued','failed'))"""
                + (" AND p.project_id=?" if project_id is not None else ""),
                (project_id,) if project_id is not None else (),
            ).fetchall()
        stamps: dict[str, tuple] = {}
        for row in rows:
            project_id = str(row[0])
            marks = []
            for folder in _project_dirs:
                path = settings.data_dir / folder / project_id
                try:
                    marks.append(path.stat().st_mtime_ns)
                except OSError:
                    marks.append(None)
            try:
                marks.append((settings.data_dir / "portable_characters" / project_id / "current.json").stat().st_mtime_ns)
            except OSError:
                marks.append(None)
            stamps[project_id] = (tuple(row[1:]), tuple(marks))
        return stamps

    def _library_source_revisions(connection: Any = None) -> dict[str, int]:
        """Durable per-project source versions, advanced by every writer.

        /api/character-library and /api/characters both project the same saved
        state, so a caller that joins them can tell which row was read from the
        newer source and refuse to let an older read overwrite it.
        """
        with (nullcontext(connection) if connection is not None else projects.db.connection()) as conn:
            rows = conn.execute("SELECT project_id,revision FROM project_library_source_revision").fetchall()
        return {str(row[0]): int(row[1] or 0) for row in rows}

    def _characters_row(project_id: str, source_revision: int) -> dict[str, Any]:
        row = character_sheets.list_row(project_id)
        # A list is a chooser surface.  The audited recovery projection opens every retained
        # run payload -- tens of megabytes per project -- purely so the Local-AI correction
        # action can be offered, and this list never offers it (audit_provider=False).
        workflow = character_creation.recovery(project_id, audit_provider=False)
        row["workflow"] = workflow
        descriptive = ((workflow.get("active_run") or workflow.get("latest_run") or {}).get("owner_descriptive_fields") or {}).get("resolved") or {}
        proposed_name = ((descriptive.get("identity") or {}).get("name") if isinstance(descriptive, dict) else None)
        if proposed_name and row.get("name") in {None, "", "AI-proposed character"}:
            row["name"] = proposed_name
        _add_portable_readiness(row)
        row["source_revision"] = source_revision
        return row

    @app.get("/api/characters")
    def characters_list() -> list[dict[str, Any]]:
        with _list_cache_lock:
            stamps = _project_fingerprints()
            revisions = _library_source_revisions()
            rows = []
            for project_id, stamp in stamps.items():
                cached = _characters_row_cache.get(project_id)
                if cached is None or cached[0] != stamp:
                    cached = (stamp, _characters_row(project_id, revisions.get(project_id, 0)))
                    _characters_row_cache[project_id] = cached
                rows.append(cached[1])  # read-only: the response encoder never mutates it
            for gone in set(_characters_row_cache) - set(stamps):
                _characters_row_cache.pop(gone, None)
        rows.sort(key=lambda item: (str(item.get("name") or "").casefold(), item["project_id"]))
        return rows

    def _add_portable_readiness(row: dict[str, Any]) -> None:
        verified = portable_characters.verified_status(str(row["project_id"]))
        if verified:
            row["portable_readiness"] = {
                "combat_sheet": verified.get("combat_sheet"),
                "combat_runtime": verified.get("combat_runtime"),
                "combat_ready_semantics": verified.get("combat_ready_semantics"),
                "encounter": verified.get("encounter", "NOT_ATTEMPTED"),
                "controller_selection": verified.get("controller_selection", "NOT_ATTEMPTED"),
                "encounter_setup_required": True,
                "current_qi_required": True,
                "current_martial_focus_required": True,
                "opponent_team_completion_required": True,
                "battlefield_owner_choice_committed": False,
                "token_placement_committed": False,
                "initiative_attempted": False,
            }

    def _library_identity_from_rows(conn: Any, project_id: str) -> tuple[dict[str, Any], str | None, str | None, dict[str, Any]]:
        """Extract card facts once, only when the durable summary is stale."""
        identity: dict[str, Any] = {"name": None, "title": None, "target_cl": None, "background": None, "paths": [], "last_worked_at": None}
        run = conn.execute(
            """SELECT COALESCE(json_extract(accepted_descriptive_fields_json, '$.identity.name'), json_extract(owner_descriptive_fields_json, '$.identity.name')) AS name,
                      COALESCE(json_extract(accepted_descriptive_fields_json, '$.identity.title'), json_extract(owner_descriptive_fields_json, '$.identity.title')) AS title,
                      updated_at,
                      (SELECT MAX(completed_at) FROM character_creation_runs finalized
                       WHERE finalized.project_id = ? AND finalized.status = 'CLEAN_AND_FINALIZED'
                         AND finalized.completed_at IS NOT NULL) AS completed_at
               FROM character_creation_runs WHERE project_id=? ORDER BY updated_at DESC LIMIT 1""",
            (project_id, project_id),
        ).fetchone()
        completed = run["completed_at"] if run and isinstance(run["completed_at"], str) and run["completed_at"] else None
        if run:
            identity["name"] = run["name"] if isinstance(run["name"], str) and run["name"].strip() else None
            identity["title"] = run["title"] if isinstance(run["title"], str) and run["title"].strip() else None
            identity["last_worked_at"] = run["updated_at"]
        lock_fields: dict[str, Any] = {}
        for row in conn.execute(
            """SELECT json_extract(l.value, '$.field') AS field, l.value AS lock_json
               FROM projects p, json_each(p.project_json, '$.user_locks') l
               WHERE p.project_id=? AND json_extract(l.value, '$.field') IN ('target_cl', 'character.identity.display_name', 'character_sheet.locked_choices')""",
            (project_id,),
        ):
            try:
                value = json.loads(row["lock_json"]).get("value")
            except (TypeError, ValueError):
                continue
            lock_fields[row["field"]] = value
            if row["field"] == "target_cl" and type(value) is int:
                identity["target_cl"] = value
            elif row["field"] == "character.identity.display_name" and isinstance(value, str) and value.strip() and not identity["name"]:
                identity["name"] = value.strip()
            elif row["field"] == "character_sheet.locked_choices" and isinstance(value, dict):
                background = value.get("background_choice")
                if isinstance(background, list) and background and isinstance(background[0], str):
                    identity["background"] = background[0].rsplit(".", 1)[-1].replace("_", " ").title()
                paths = value.get("path_choice")
                if isinstance(paths, list):
                    identity["paths"] = [
                        _OWNER_PATH_NAMES.get(path_id, path_id.rsplit(".", 1)[-1].replace("_", " ").title())
                        for path_id in paths if isinstance(path_id, str)
                    ]
        return identity, completed, run["updated_at"] if run else None, lock_fields

    def _library_cached_facts(stamps: dict[str, tuple]) -> tuple[dict[str, str], dict[str, Any]]:
        completed_at_by_project: dict[str, str] = {}
        identity_by_project: dict[str, Any] = {}
        with projects.db.connection() as conn:
            stored = {row["project_id"]: row for row in conn.execute("SELECT * FROM project_library_summary")}
        for project_id, stamp in stamps.items():
            row = stored.get(project_id)
            if row is None or row["fingerprint"] != canonical_json(stamp):
                continue
            identity = {
                "name": row["name"], "title": row["title"], "target_cl": row["target_cl"],
                "background": row["background"], "paths": json.loads(row["paths_json"] or "[]"),
                "last_worked_at": row["last_worked_at"],
            }
            cached = (stamp, {"completed_at": row["completed_at"], "identity": identity})
            _library_identity_cache[project_id] = cached
            if cached[1]["completed_at"]:
                completed_at_by_project[project_id] = cached[1]["completed_at"]
            identity_by_project[project_id] = cached
        return completed_at_by_project, identity_by_project

    def _fill_library_summary(project_id: str, stamp: tuple) -> None:
        """Fill one stale card summary; concurrent callers share the in-flight project."""
        with _library_summary_fill_lock:
            if project_id in _library_summary_fills:
                return
            _library_summary_fills.add(project_id)
        try:
            # WAL read snapshots leave the writer free during large JSON extraction.
            # A changed source is retried; never publish facts under another version.
            for _attempt in range(3):
                with projects.db.connection() as conn:
                    conn.execute("BEGIN")
                    stamp = _project_fingerprints(conn, project_id).get(project_id)
                    if stamp is None:
                        return
                    fingerprint = canonical_json(stamp)
                    current = conn.execute(
                        "SELECT fingerprint FROM project_library_summary WHERE project_id=?", (project_id,)
                    ).fetchone()
                    if current is not None and current["fingerprint"] == fingerprint:
                        return
                    identity, completed, last_worked, lock_fields = app.state.library_summary_identity_reader(conn, project_id)
                if _publish_library_summary(project_id, stamp, identity, completed, last_worked, lock_fields):
                    return
            # Leave it pending under sustained mutation; the next poll retries.
        finally:
            with _library_summary_fill_lock:
                _library_summary_fills.discard(project_id)

    def _publish_library_summary(project_id: str, stamp: tuple, identity: dict[str, Any],
                                 completed: str | None, last_worked: str | None, lock_fields: dict[str, Any]) -> bool:
        fingerprint = canonical_json(stamp)
        paths_json = canonical_json(identity["paths"])
        lock_fields_json = canonical_json(lock_fields)
        with projects.db.transaction() as conn:
            if _project_fingerprints(conn, project_id).get(project_id) != stamp:
                return False
            current = conn.execute(
                "SELECT fingerprint FROM project_library_summary WHERE project_id=?", (project_id,)
            ).fetchone()
            if current is not None and current["fingerprint"] == fingerprint:
                return True
            conn.execute(
                """INSERT INTO project_library_summary(
                           project_id,fingerprint,name,title,target_cl,background,paths_json,
                           completed_at,last_worked_at,user_lock_fields_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(project_id) DO UPDATE SET
                           fingerprint=excluded.fingerprint,name=excluded.name,title=excluded.title,
                           target_cl=excluded.target_cl,background=excluded.background,
                           paths_json=excluded.paths_json,completed_at=excluded.completed_at,
                           last_worked_at=excluded.last_worked_at,
                           user_lock_fields_json=excluded.user_lock_fields_json,updated_at=excluded.updated_at""",
                (project_id, fingerprint, identity["name"], identity["title"], identity["target_cl"],
                 identity["background"], paths_json, completed, last_worked,
                 lock_fields_json, utcnow()),
            )
        return True

    def _fill_missing_library_summaries() -> None:
        stamps = _project_fingerprints()
        with projects.db.connection() as conn:
            stored = {row["project_id"]: row["fingerprint"] for row in conn.execute(
                "SELECT project_id,fingerprint FROM project_library_summary"
            )}
        for project_id, stamp in stamps.items():
            if stored.get(project_id) != canonical_json(stamp):
                try:
                    _fill_library_summary(project_id, stamp)
                except Exception:  # noqa: BLE001 - request reads remain available; next startup retries
                    continue
                time.sleep(0.01)  # yield between projects so request threads get prompt CPU and DB access

    app.state.fill_missing_character_library_summaries = _fill_missing_library_summaries
    app.state.library_summary_identity_reader = _library_identity_from_rows

    def _schedule_library_summary_fill() -> None:
        nonlocal _library_summary_worker_active
        with _library_summary_worker_lock:
            if _library_summary_worker_active:
                return
            _library_summary_worker_active = True

        def run() -> None:
            nonlocal _library_summary_worker_active
            try:
                _fill_missing_library_summaries()
            finally:
                with _library_summary_worker_lock:
                    _library_summary_worker_active = False

        worker = threading.Thread(target=run, name="character-library-summary-fill", daemon=True)
        app.state.character_library_summary_fill_thread = worker
        worker.start()

    app.state.schedule_character_library_summary_fill = _schedule_library_summary_fill

    @app.get("/api/character-library")
    def character_library() -> list[dict[str, Any]]:
        archived_project_ids = character_library_archives.archived_project_ids()
        recoveries = {
            str(item.get("project_id")): item
            for item in character_creation.recoverable()
            if isinstance(item, dict) and item.get("project_id")
        }
        # The true completion time and card identity are read from durable summaries.
        # Missing or stale summaries are scheduled for background refresh so this
        # request can still return the lightweight project card immediately.
        with _library_cache_lock:
            stamps = _project_fingerprints()
            revisions = _library_source_revisions()
            with projects.db.connection() as conn:
                known_fingerprints = {
                    row["project_id"]: row["fingerprint"]
                    for row in conn.execute("SELECT project_id,fingerprint FROM project_library_summary")
                }
            if any(known_fingerprints.get(project_id) != canonical_json(stamp) for project_id, stamp in stamps.items()):
                _schedule_library_summary_fill()
            completed_at_by_project, identity_by_project = _library_cached_facts(stamps)
            for stale_project_id in set(_library_identity_cache) - set(stamps):
                _library_identity_cache.pop(stale_project_id, None)
            result: list[dict[str, Any]] = []
            for project in projects.list_projects():
                project_id = project.get("project_id")
                if not isinstance(project_id, str) or not project_id:
                    continue
                if project_id in archived_project_ids:
                    continue
                workflow = recoveries.get(project_id) or {
                    "schema": "TianxiaFoundry.CharacterCreationRecovery.v1",
                    "project_id": project_id,
                    "active": False,
                    "active_run": None,
                    "latest_run": None,
                }
                active_run = workflow.get("active_run") if isinstance(workflow, dict) else None
                latest_run = workflow.get("latest_run") if isinstance(workflow, dict) else None
                build_status = (
                    active_run.get("status")
                    if isinstance(active_run, dict) and active_run.get("status")
                    else latest_run.get("status")
                    if isinstance(latest_run, dict) and latest_run.get("status")
                    else project.get("compile_status") or project.get("status") or "NOT_STARTED"
                )
                cached = identity_by_project.get(project_id)
                if cached is not None and cached[1]["identity"] is not None:
                    identity = cached[1]["identity"]
                else:
                    # Normal first paint can precede the background summary fill.
                    identity = {"name": None, "title": None, "target_cl": None, "background": None, "paths": [], "last_worked_at": None}
                    if cached is not None:
                        cached[1]["identity"] = identity
                working_name = project.get("working_name")
                generic_name = working_name in (None, "", "AI-proposed character")
                result.append({
                    "project_id": project_id,
                    "summary_pending": cached is None and project_id in stamps,
                    "source_revision": revisions.get(project_id, 0),
                    "completed_at": completed_at_by_project.get(project_id),
                    "name": (identity["name"] if generic_name and identity["name"] else working_name) or project_id,
                    "working_name": working_name,
                    "title": identity["title"],
                    "background": identity["background"],
                    "paths": identity["paths"],
                    "last_worked_at": identity["last_worked_at"] or project.get("updated_at"),
                    "lifecycle": project.get("builder_lifecycle") or {},
                    "build_status": build_status,
                    "target_cl": identity["target_cl"],
                    "current_cl": None,
                    "path": ", ".join(identity["paths"]) or None,
                    "updated_at": project.get("updated_at"),
                    "can_export_gm": False,
                    "plain_summary": (
                        workflow.get("next_legal_action")
                        if isinstance(workflow, dict) and workflow.get("next_legal_action")
                        else "Open the character sheet to inspect this saved project."
                    ),
                    "workflow": workflow,
                })
        # Owner request 2026-09-13: finished characters lead by completion date
        # (newest first); characters still in progress follow by recency; every
        # abandoned draft falls to the bottom.  Name breaks ties so the order is
        # stable between identical timestamps.
        def _library_order(row: dict[str, Any]) -> tuple[int, int, str, str]:
            status = str(row.get("build_status") or "")
            stamp = str(row.get("completed_at") or row.get("last_worked_at") or row.get("updated_at") or "")
            if status == "CLEAN_AND_FINALIZED":
                tier = 0
            elif str((row.get("lifecycle") or {}).get("persistence_state") or "") == "temporary":
                tier = 1
            else:
                tier = 2
            return (tier, 0 if stamp else 1, _invert_stamp(stamp), str(row.get("name") or "").casefold())

        result.sort(key=_library_order)
        return result

    @app.get("/api/character-library/archived")
    def archived_character_library() -> list[dict[str, Any]]:
        hidden = hidden_project_ids(db)
        projects_by_id = {
            str(project.get("project_id")): project
            for project in projects.list_projects()
            if isinstance(project, dict) and project.get("project_id")
        }
        result = []
        for archived in character_library_archives.list_archived():
            if archived["project_id"] in hidden:
                continue
            project = projects_by_id.get(archived["project_id"])
            result.append({
                **(project or {"project_id": archived["project_id"]}),
                "archived_at": archived["archived_at"],
            })
        return result + deletion_queue.hidden_cards()

    @app.post("/api/character-library/{project_id}/archive")
    def archive_character_library_project(project_id: str) -> dict[str, Any]:
        return character_library_archives.archive(project_id)

    @app.post("/api/character-library/{project_id}/restore")
    def restore_character_library_project(project_id: str) -> dict[str, Any]:
        return character_library_archives.restore(project_id)

    @app.post("/api/character-library/{project_id}/delete-permanently")
    def delete_character_library_project(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("confirm_project_id") != project_id:
            raise FoundryError("PROJECT_DELETE_CONFIRMATION_REQUIRED", "Confirm the exact character project before deleting it.", status_code=400)
        return deletion_queue.request(project_id, requested_by=principal.principal_id, confirmation=body["confirm_project_id"])

    @app.post("/api/character-library/{project_id}/undo-delete")
    def undo_character_library_deletion(project_id: str) -> dict[str, Any]:
        return deletion_queue.undo(project_id)

    @app.get("/api/characters/{project_id}/sheet")
    def character_sheet_get(project_id: str) -> dict[str, Any]:
        result = character_sheets.sheet(project_id)
        result["workflow"] = character_creation.recovery(project_id)
        # Display the same growth record as the table without altering either
        # the authenticated projection or the sealed portable install.
        from combat import table_advance

        growth = table_advance.normalized(tabletop.buttons.get(project_id).get("advancement"))
        if any(growth[key] for key in growth if key != "schema"):
            for key in ("owner_character_sheet", "display_owner_character_sheet"):
                if isinstance(result.get(key), dict):
                    result[key] = table_advance.apply(result[key], growth)
            adjusted = result.get("display_owner_character_sheet") or result.get("owner_character_sheet") or {}
            sections = result.get("sections") or {}
            section = sections.get("abilities_statistics") or {}
            result["sections"] = {**sections, "abilities_statistics": {
                **section, "data": adjusted.get("ability_scores_and_statistics", {})}}
        display_sheet = result.get("display_owner_character_sheet")
        try:
            from combat.display_values import compiled_armor_class

            combat_ac = compiled_armor_class(project_id, tabletop)
        except Exception as exc:  # noqa: BLE001 -- keep sheet available but make unavailable AC explicit
            failure_key = (project_id, f"{type(exc).__name__}: {exc}")
            with _COMBAT_AC_FAILURES_LOCK:
                first_failure = failure_key not in _COMBAT_AC_FAILURES
                _COMBAT_AC_FAILURES.add(failure_key)
            if first_failure:
                logger.warning("Compiled AC unavailable for character %s: %s", project_id, exc)
            combat_ac = {"value": None, "tooltip": "AC from combat unavailable."}
        if isinstance(display_sheet, dict):
            display_stats = display_sheet.get("ability_scores_and_statistics")
            if isinstance(display_stats, dict):
                result["display_owner_character_sheet"] = {
                    **display_sheet, "ability_scores_and_statistics": {**display_stats, "combat_armor_class": combat_ac},
                }
        sections = result.get("sections") or {}
        abilities = sections.get("abilities_statistics") or {}
        data = dict(abilities.get("data") or {})
        data["combat_armor_class"] = combat_ac
        result["sections"] = {**sections, "abilities_statistics": {**abilities, "data": data}}
        try:  # manuals given at the table, shown beside the sealed ones (combat/tabletop_service.py table_manuals)
            result["table_manuals"] = tabletop.table_manuals(project_id)
        except Exception:  # noqa: BLE001 -- a display extra never blocks the sheet
            result["table_manuals"] = []
        return result

    @app.get("/api/characters/{project_id}/factory-workspace/status")
    def character_factory_workspace_status(project_id: str) -> dict[str, Any]:
        return factory_authoring.status(project_id)

    @app.post("/api/characters/{project_id}/factory-workspace/build")
    def character_factory_workspace_build(project_id: str) -> dict[str, Any]:
        return factory_authoring.build(project_id)

    @app.post("/api/characters/{project_id}/factory-workspace/command4-author")
    def character_factory_workspace_command4_author(project_id: str) -> dict[str, Any]:
        """Explicitly run the bounded local Command 4 authoring action."""
        return factory_authoring.author_command4(project_id, ai_provider)

    @app.post("/api/characters/{project_id}/factory-workspace/command5-rebind")
    def character_factory_workspace_command5_rebind(project_id: str) -> dict[str, Any]:
        """Recompile the candidate with its current server-owned Command 4 overlay."""
        with final_character_workflow._current_action(project_id) as (receipt, _):
            overlay = (
                settings.logs_dir / "factory_command4_authoring"
                / "command4_authoring_overlays" / receipt["overlay_id"]
            )
            result = CharacterProductionReleaseAdapter(db).compile(
                project_id,
                output_root=settings.logs_dir / "factory_command5_rebind" / project_id / receipt["receipt_id"],
                reviewed_overlay_root=overlay,
            )
            candidate = result["command5"]
            component = final_character_workflow.record_action_workspace(project_id, {
                "valid": True, "overlay_path": candidate["workspace"],
                "candidate_sha256": candidate["candidate_sha256"], "projection_id": candidate["projection_id"],
            })
            return {**result, "final_character_component": component}

    @app.post("/api/characters/{project_id}/factory-workspace/gm-author")
    def character_factory_workspace_gm_author(project_id: str) -> dict[str, Any]:
        """Explicitly invoke local model GM authoring; build/status remain provider-free."""
        return factory_authoring.author_gm_tactical(project_id, ai_provider)

    @app.post("/api/characters/{project_id}/factory-workspace/gm-author/ratification-challenge")
    def character_factory_workspace_gm_ratification_challenge(
        project_id: str,
        body: GMAuthoringRatificationChallengeRequest,
    ) -> dict[str, Any]:
        return factory_authoring.issue_gm_authoring_ratification_challenge(project_id, body.ttl_seconds)

    @app.post("/api/characters/{project_id}/factory-workspace/gm-author/ratify")
    def character_factory_workspace_gm_ratify(
        project_id: str,
        body: GMAuthoringRatificationRequest,
    ) -> dict[str, Any]:
        return factory_authoring.ratify_gm_authoring(project_id, body.receipt_id, body.challenge_id, body.nonce)

    @app.post("/api/characters/{project_id}/factory-workspace/composite-controller-author")
    def character_factory_workspace_composite_controller_author(project_id: str) -> dict[str, Any]:
        """Explicitly run one bounded local composite-controller proposal."""
        return factory_authoring.author_composite_controller(project_id, ai_provider)

    @app.get("/api/characters/{project_id}/factory-workspace/view")
    def character_factory_workspace_view(project_id: str) -> dict[str, Any]:
        return factory_authoring.view(project_id)

    @app.get("/api/characters/{project_id}/factory-workspace/final-character/preview")
    def character_factory_workspace_final_character_preview(project_id: str) -> dict[str, Any]:
        return final_character_workflow.preview_current_triplet(project_id)

    @app.post("/api/characters/{project_id}/factory-workspace/final-character/approval-challenge")
    def character_factory_workspace_final_character_approval_challenge(
        project_id: str,
        body: FinalCharacterApprovalChallengeRequest,
    ) -> dict[str, Any]:
        return final_character_workflow.issue_review_challenge(project_id, body.ttl_seconds)

    @app.post("/api/characters/{project_id}/factory-workspace/final-character/approve")
    def character_factory_workspace_final_character_approve(
        project_id: str,
        body: FinalCharacterApproveRequest,
    ) -> dict[str, Any]:
        return final_character_workflow.approve_current_triplet(project_id, body.challenge_id, body.nonce)

    @app.post("/api/characters/{project_id}/factory-workspace/final-character/materialize")
    def character_factory_workspace_final_character_materialize(
        project_id: str,
        body: FinalCharacterMaterializeRequest,
    ) -> dict[str, Any]:
        return final_character_workflow.materialize_current_triplet(project_id, body.review_record_id)

    @app.get("/api/characters/{project_id}/gm-export/status")
    def character_gm_export_status(project_id: str) -> dict[str, Any]:
        return gm_exports.status(project_id)

    @app.post("/api/characters/{project_id}/gm-export")
    def character_gm_export(project_id: str, body: ExportRequest) -> dict[str, Any]:
        result = gm_exports.export(project_id, filename=body.filename)
        result["download_url"] = f"/api/characters/{project_id}/gm-export/download?filename={result['filename']}"
        return result

    @app.get("/api/characters/{project_id}/gm-export/download")
    def character_gm_export_download(project_id: str, filename: str = Query(..., min_length=1, max_length=240)) -> FileResponse:
        character_sheets.sheet(project_id, compact=True)
        if Path(filename).name != filename or not filename.lower().endswith(".zip"):
            raise FoundryError("GM_CHARACTER_EXPORT_FILENAME_INVALID", "Use a plain .zip filename.")
        root = (settings.exports_dir / "CharacterBuilder" / "GM_Screen_Characters").resolve()
        path = resolve_inside(root, filename)
        if not path.is_file():
            raise FoundryError("GM_CHARACTER_EXPORT_NOT_FOUND", "That GM Screen export file was not found.", status_code=404)
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.get("/api/system/status")
    def system_status() -> dict[str, Any]:
        with db.connection() as conn:
            recent_errors = [dict(r) for r in conn.execute("SELECT created_at,code,message FROM recent_errors ORDER BY error_id DESC LIMIT 10")]
        readiness = product_readiness.report()
        inventory = combatant_library.inventory().model_dump(mode="json")
        return {
            "health": health(),
            "readiness": readiness,
            "build": readiness["build"],
            "project_store": readiness["project_store"],
            "producer_corpus": readiness["producer_corpus"],
            "factory_adapter": readiness["factory_adapter"],
            "catalog": readiness["catalog"],
            "canonical_catalog_authority": readiness.get("canonical_catalog_authority"),
            "gm_consumer": readiness["gm_consumer"],
            "combat_runtime": readiness["combat_runtime"],
            "combatant_library": {
                "status": inventory.get("status"),
                "accepted_count": inventory.get("accepted_count"),
                "blocked_count": inventory.get("blocked_count"),
                "live_encounter": "NOT_ATTEMPTED",
            },
            "native_windows": readiness["native_windows"],
            "ai_provider": ai_provider.status(),
            "combat": combat.status(),
            "installed_content_packs": packs.list(),
            "recent_errors": recent_errors,
            "directories": {
                "data": str(settings.data_dir),
                "database": str(settings.db_path),
                "inbox": str(settings.inbox_dir),
                "exports": str(settings.exports_dir),
                "logs": str(settings.logs_dir),
                "backups": str(settings.backups_dir),
            },
            "packaging": {
                "version": APP_VERSION,
                "status": readiness["status"],
                "declared_checkpoint_status": APP_STATUS,
            },
        }

    # ------------------------------------------------------------------
    # Gate 5 Factory combat integration. All mutation routes remain behind
    # the application's existing loopback + x-foundry-token middleware.
    # ------------------------------------------------------------------
    @app.get("/api/combat/status")
    def combat_status() -> dict[str, Any]:
        return combat.status()

    @app.get("/api/combat/candidates")
    def combat_candidates() -> dict[str, Any]:
        inventory = combatant_library.inventory().model_dump(mode="json", by_alias=True)
        hidden = hidden_project_ids(db)
        inventory["accepted_candidates"] = [row for row in inventory["accepted_candidates"] if row["character_project_id"] not in hidden]
        inventory["blocked_candidates"] = [row for row in inventory["blocked_candidates"] if row.get("project_id") not in hidden]
        inventory["accepted_count"] = len(inventory["accepted_candidates"])
        inventory["blocked_count"] = len(inventory["blocked_candidates"])
        from combat.canonical import canonical_sha256
        inventory.pop("inventory_commitment_sha256")
        inventory["inventory_commitment_sha256"] = canonical_sha256(inventory)
        return inventory

    @app.get("/api/combat/candidates/{entry_id}")
    def combat_candidate(entry_id: str) -> dict[str, Any]:
        return combatant_library.candidate(entry_id).model_dump(mode="json", by_alias=True)

    @app.post("/api/combat/candidates/{entry_id}/resource-validation")
    def combat_candidate_resource_validation(entry_id: str, body: CombatResourceInitializationRequest) -> dict[str, Any]:
        return combatant_library.validate_resource_initialization(
            entry_id,
            qi_current=body.qi_current,
            martial_focus_current=body.martial_focus_current,
            provenance_kind=body.provenance_kind,
            provenance_id=body.provenance_id,
        ).model_dump(mode="json", by_alias=True)

    @app.post("/api/combat/pre-encounter-drafts/preview")
    def combat_pre_encounter_draft_preview(body: CombatPreEncounterDraftPreviewRequest) -> dict[str, Any]:
        return combatant_library.preview_draft(
            participants=[row.model_dump(mode="json") for row in body.participants],
            battlefield_id=body.battlefield_id,
            battlefield_provenance_kind=body.battlefield_provenance_kind,
            battlefield_provenance_id=body.battlefield_provenance_id,
        ).model_dump(mode="json", by_alias=True)

    @app.post("/api/combat/pre-encounter-drafts/discard")
    def combat_pre_encounter_draft_discard(body: CombatPreEncounterDraftDiscardRequest) -> dict[str, Any]:
        return combatant_library.discard_draft(body.draft_id)



    @app.post("/api/combat/new-fight/preflight")
    def combat_new_fight_preflight(body: CombatFightPreflightRequest) -> dict[str, Any]:
        return combat.preflight_new_fight(body.model_dump(mode="json"))

    @app.post("/api/combat/new-fight/create")
    def combat_new_fight_create(body: CombatFightCreateRequest) -> dict[str, Any]:
        return combat.create_confirmed_fight(body.model_dump(mode="json"))

    @app.get("/api/combat/catalog")
    def combat_catalog() -> dict[str, Any]:
        return combat.catalog()

    @app.get("/api/combat/characters/{character_sheet_identity:path}")
    def combat_character_authority(character_sheet_identity: str) -> dict[str, Any]:
        return combat.character_authority(character_sheet_identity)

    @app.get("/api/combat/visual-assets")
    def combat_visual_assets() -> dict[str, Any]:
        return combat.visual_assets()

    @app.post("/api/combat/setup-visuals/background")
    def combat_visual_background_upload(body: CombatVisualUploadRequest) -> dict[str, Any]:
        return combat.save_visual_upload(
            kind="background",
            actor_id=None,
            original_filename=body.original_filename,
            declared_media_type=body.media_type,
            data_base64=body.data_base64,
            calibration_mode=body.calibration_mode,
            playable_rect_pixels=(body.playable_rect_pixels.model_dump() if body.playable_rect_pixels else None),
        )

    @app.delete("/api/combat/setup-visuals/background")
    def combat_visual_background_reset() -> dict[str, Any]:
        return combat.reset_visual_upload(kind="background")

    @app.post("/api/combat/setup-visuals/tokens/{actor_id}")
    def combat_visual_token_upload(actor_id: str, body: CombatVisualUploadRequest) -> dict[str, Any]:
        return combat.save_visual_upload(
            kind="token",
            actor_id=actor_id,
            original_filename=body.original_filename,
            declared_media_type=body.media_type,
            data_base64=body.data_base64,
            calibration_mode="COVER_DECORATIVE",
            playable_rect_pixels=None,
        )

    @app.delete("/api/combat/setup-visuals/tokens/{actor_id}")
    def combat_visual_token_reset(actor_id: str) -> dict[str, Any]:
        return combat.reset_visual_upload(kind="token", actor_id=actor_id)

    @app.get("/api/combat/setup-visuals/assets/{stored_name}")
    def combat_visual_profile_asset(stored_name: str) -> FileResponse:
        path = combat.visual_profile_asset_path(stored_name)
        media_type = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/combat/matches")
    def combat_matches() -> list[dict[str, Any]]:
        hidden = hidden_project_ids(db)
        if not hidden:
            return combat.list_matches()
        hidden_matches = {name for matches in project_matches(db, hidden).values() for name, _ in matches}
        # Bind directory names to logical IDs without loading a combat engine.
        from combat.gate3_storage import encode_match_directory_name
        return [row for row in combat.list_matches() if row["match_id"] not in hidden_matches
                and encode_match_directory_name(row["match_id"]) not in hidden_matches]

    @app.post("/api/combat/matches")
    def combat_match_create(body: CombatCreateMatchRequest) -> dict[str, Any]:
        return combat.create_match(**body.model_dump())

    @app.get("/api/combat/factory-characters")
    def combat_factory_characters() -> list[dict[str, Any]]:
        archived_project_ids = character_library_archives.archived_project_ids() | hidden_project_ids(db)
        rows = [row for row in combat.factory_characters() if row["project_id"] not in archived_project_ids]
        tokens = tabletop.token_urls([row["project_id"] for row in rows])  # the fighter picker's cards (read-only)
        return [{**row, "token_url": tokens[row["project_id"]]} if row["project_id"] in tokens else row for row in rows]

    @app.get("/api/combat/factory-arenas")
    def combat_factory_arenas() -> list[dict[str, Any]]:
        from combat.tabletop import arena_picker_name, arena_picker_order

        arenas = combat.factory_arenas()
        return [{"arena_id": key, "display_name": arena_picker_name(arenas[key]),
                 "description": arenas[key].get("description", "")}
                for key in sorted(arenas, key=lambda key: arena_picker_order(arenas[key]))]

    @app.post("/api/combat/factory-matches")
    def combat_factory_match_create(body: CombatFactoryMatchRequest) -> dict[str, Any]:
        return combat.create_factory_match(**body.model_dump())

    def journey_call(call):
        try:
            return call()
        except (ValueError, KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post('/api/combat/journeys')
    def journey_create(body: JourneyCreateRequest):
        return journey_call(lambda: combat.create_journey(**body.model_dump()))

    @app.get('/api/combat/journeys/{journey_id}')
    def journey_get(journey_id: str, viewer_id: str | None = None):
        return journey_call(lambda: combat.journey_state(journey_id, viewer_id))

    @app.get('/api/combat/journeys/{journey_id}/menu/{actor_id}')
    def journey_menu(journey_id: str, actor_id: str):
        return journey_call(lambda: combat.journey_menu(journey_id, actor_id))

    @app.post('/api/combat/journeys/{journey_id}/act')
    def journey_act(journey_id: str, body: JourneyActionRequest):
        return journey_call(lambda: combat.journey_act(journey_id, **body.model_dump()))

    @app.post('/api/combat/journeys/{journey_id}/world-facts')
    def journey_world_fact(journey_id: str, body: JourneyWorldFactRequest):
        return journey_call(lambda: combat.journey_world_fact(journey_id, **body.model_dump()))

    @app.post('/api/combat/journeys/{journey_id}/end-scene')
    def journey_end_scene(journey_id: str, body: JourneySceneEndRequest):
        return journey_call(lambda: combat.journey_end_scene(journey_id, **body.model_dump()))

    @app.post('/api/combat/matches/{match_id}/world-facts')
    def combat_world_fact(match_id: str, body: CombatWorldFactRequest):
        return journey_call(lambda: combat.world_fact(match_id, **body.model_dump()))

    @app.post('/api/combat/journeys/{journey_id}/auto-step')
    def journey_auto(journey_id: str, body: JourneyAutoRequest):
        return journey_call(lambda: combat.journey_auto_step(journey_id, **body.model_dump()))

    @app.post('/api/combat/journeys/{journey_id}/combat')
    def journey_combat(journey_id: str, body: JourneyCombatRequest):
        return journey_call(lambda: combat.journey_start_combat(journey_id, **body.model_dump()))

    @app.post('/api/combat/journeys/{journey_id}/resume')
    def journey_resume(journey_id: str, body: JourneyResumeRequest):
        return journey_call(lambda: combat.journey_resume(journey_id, **body.model_dump()))

    @app.get("/api/combat/factory-prefight/{project_id}")
    def combat_factory_prefight(project_id: str) -> dict[str, Any]:
        """The buffs a character may start a fight with, and the AI's picks (owner 2026-09-29)."""
        return combat.factory_prefight_options(project_id)

    @app.get("/api/combat/matches/{match_id}")
    def combat_match_get(match_id: str) -> dict[str, Any]:
        return combat.get_match(match_id)

    @app.get("/api/combat/matches/{match_id}/presentation")
    def combat_match_presentation(match_id: str, boundary: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
        return combat.presentation(match_id, boundary_index=boundary)

    @app.post("/api/combat/matches/{match_id}/controller-mode")
    def combat_match_controller_mode(match_id: str, body: CombatControllerModeRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.control(match_id, "controller", actor_id=body.actor_id,
                                                  controller_mode=body.controller_mode, ai_tier=body.ai_tier))

    @app.post("/api/combat/matches/{match_id}/pause")
    def combat_match_pause(match_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.control(match_id, "pause"))

    @app.post("/api/combat/matches/{match_id}/resume")
    def combat_match_resume(match_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.control(match_id, "resume"))

    @app.get("/api/combat/matches/{match_id}/decision")
    def combat_match_decision(match_id: str) -> dict[str, Any]:
        return combat.decision(match_id)

    @app.post("/api/combat/matches/{match_id}/preview")
    def combat_match_preview(match_id: str, body: CombatPreviewRequest) -> dict[str, Any]:
        payload = body.model_dump(mode="json")
        return combat.preview(match_id, payload["intent"], payload["reaction_decisions"])

    @app.post("/api/combat/matches/{match_id}/intent")
    def combat_match_intent(match_id: str, body: CombatIntentSubmitRequest) -> dict[str, Any]:
        payload = body.model_dump(mode="json")
        return combat.submit_intent(match_id, payload["intent"], payload["reaction_decisions"], payload["preview_id"])

    @app.post("/api/combat/matches/{match_id}/suggest")
    def combat_match_suggest(match_id: str) -> dict[str, Any]:
        return combat.suggest(match_id)

    @app.post("/api/combat/matches/{match_id}/local-step")
    def combat_match_local_step(match_id: str, body: TabletopStepRequest | None = None) -> dict[str, Any]:
        return combat.local_step(match_id, body.reactions if body else None)

    @app.post("/api/combat/matches/{match_id}/auto-step")
    def combat_match_auto_step(match_id: str, body: TabletopStepRequest | None = None) -> dict[str, Any]:
        return combat.auto_step(match_id, body.reactions if body else None)

    @app.post("/api/combat/matches/{match_id}/provider-step")
    def combat_match_provider_step(match_id: str, body: TabletopStepRequest | None = None) -> dict[str, Any]:
        return combat.provider_step(match_id, body.reactions if body else None)

    @app.post("/api/combat/matches/{match_id}/local-run")
    def combat_match_local_run(match_id: str, body: CombatLocalRunRequest) -> dict[str, Any]:
        return combat.local_run(match_id, maximum_steps=body.maximum_steps)

    @app.get("/api/combat/matches/{match_id}/dao-iching-audit")
    def combat_match_dao_iching_audit(match_id: str) -> dict[str, Any]:
        return combat.post_round_dao_iching_audit(match_id)

    @app.get("/api/combat/matches/{match_id}/final-summary")
    def combat_match_final_summary(match_id: str) -> dict[str, Any]:
        return combat.final_summary(match_id)

    @app.post("/api/combat/matches/{match_id}/snapshot")
    def combat_match_snapshot(match_id: str) -> dict[str, Any]:
        return combat.snapshot(match_id)

    @app.post("/api/combat/matches/{match_id}/verify")
    def combat_match_verify(match_id: str) -> dict[str, Any]:
        return combat.verify(match_id)

    @app.get("/api/combat/matches/{match_id}/replay")
    def combat_match_replay(match_id: str) -> dict[str, Any]:
        return combat.replay(match_id)

    @app.get("/api/combat/matches/{match_id}/history")
    def combat_match_history(match_id: str) -> dict[str, Any]:
        return combat.history(match_id)

    @app.get("/api/combat/matches/{match_id}/export")
    def combat_match_export(match_id: str) -> FileResponse:
        path = combat.export(match_id)
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.get("/api/combat/matches/{match_id}/visual-assets/{filename}")
    def combat_match_visual_asset(match_id: str, filename: str) -> FileResponse:
        path = combat.match_visual_asset_path(match_id, filename)
        media_type = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/combat/matches/{match_id}/ai-frame")
    def combat_match_ai_frame(match_id: str) -> dict[str, Any]:
        return combat.ai_frame(match_id)

    @app.post("/api/combat/matches/{match_id}/ai-intent/validate")
    def combat_match_ai_validate(match_id: str, body: CombatAIIntentValidateRequest) -> dict[str, Any]:
        return combat.ai_validate(match_id, body.action_intent.model_dump(mode="json"), body.rationale)

    @app.post("/api/combat/matches/{match_id}/ai-intent/execute")
    def combat_match_ai_execute(match_id: str, body: CombatAIIntentExecuteRequest) -> dict[str, Any]:
        return combat.ai_execute(
            match_id,
            body.action_intent.model_dump(mode="json"),
            body.validation_token,
            body.rationale,
            reactions=body.reactions,
        )

    @app.get("/api/schemas/status")
    def schema_status() -> dict[str, Any]:
        return schema_registry.status()

    @app.get("/api/schemas/{schema_version}")
    def schema_get(schema_version: str) -> dict[str, Any]:
        try:
            return schema_registry.schema(schema_version)
        except KeyError:
            raise FoundryError("UNKNOWN_SCHEMA_VERSION", "No pinned runtime schema has that version.", details={"schema_version": schema_version}, status_code=404)

    @app.post("/api/ai-stage-responses/validate")
    def ai_stage_response_validate(body: dict[str, Any]) -> dict[str, Any]:
        # Legacy generic AIClipboard.v1 contract gate only. Stage 1 v2 uses the
        # dedicated blueprint-intent endpoints and never drafts Advancement Events.
        report = schema_registry.report(body, "TianxiaFoundry.AIClipboard.v1")
        return {"accepted_for_event_drafting": False, "bridge_implemented": False, **report}

    @app.get("/api/catalog/validation")
    def catalog_validation() -> dict[str, Any]:
        return catalog.validate_all_canonical()

    @app.get("/api/factory/status")
    def factory_status() -> dict[str, Any]:
        return vendor.status()

    @app.post("/api/factory/configure")
    def factory_configure(body: ConfigureVendorRequest) -> dict[str, Any]:
        return vendor.configure(Path(body.factory_zip_path), Path(body.fixture_path) if body.fixture_path else None)

    @app.post("/api/factory/health-check")
    def factory_health_check() -> dict[str, Any]:
        return vendor.health_check()

    @app.get("/api/factory/runs")
    def factory_runs() -> list[dict[str, Any]]:
        return vendor.recent_runs()

    @app.get("/api/catalog/status")
    def catalog_status() -> dict[str, Any]:
        return catalog.status()

    @app.post("/api/catalog/rebuild")
    def catalog_rebuild() -> dict[str, Any]:
        status = vendor.status()
        if not status.get("configured") or status.get("health") != "READY":
            raise FoundryError("FACTORY_ADAPTER_NOT_READY", "Configure the pinned Factory before rebuilding the canonical catalog.")
        return catalog.rebuild_core(Path(status["factory_root"]))

    @app.get("/api/catalog/records")
    def catalog_records(
        q: str | None = None,
        content_type: str | None = None,
        authority: str | None = None,
        publication_state: str | None = None,
        pack_id: str | None = None,
        pack_version: str | None = None,
        minimum_cl_lte: int | None = None,
        include_test: bool = False,
        projection: str = Query("canonical", pattern="^(canonical|raw)$"),
        limit: int = Query(100, ge=1, le=2000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        if projection == "raw":
            return catalog.search(q=q, content_type=content_type, authority=authority, publication_state=publication_state, pack_id=pack_id, pack_version=pack_version, minimum_cl_lte=minimum_cl_lte, include_test=include_test, limit=min(limit, 500), offset=offset)
        normalized_type = str(content_type or "sphere").strip().casefold()
        if normalized_type in {"sphere", "spheres"}:
            collection = canonical_catalog.list_spheres(q=q)
            records = [
                {
                    "record_id": row["canonical_sphere_id"], "display_name": row["display_name"],
                    "content_type": "sphere", "authority": "canonical", "publication_state": "published",
                    "description": row["short_description"], "full_description": row.get("full_description") or row["short_description"],
                    "source_reference": row["source_reference"], "aliases": row["aliases"],
                    "source_pack": row["source_pack"], "talent_count": row["talent_count"],
                    "creator_disposition": row["creator_disposition"], "prerequisite_summary": row["prerequisite_summary"],
                    "stable_id": row["stable_id"], "automatic_base_abilities": row["automatic_base_abilities"],
                }
                for row in collection["records"]
            ]
        elif normalized_type in {"talent", "talents"}:
            collection = canonical_catalog.list_talents(q=q)
            records = [
                {
                    "record_id": row["canonical_talent_id"], "display_name": row["display_name"],
                    "content_type": "talent", "authority": "canonical", "publication_state": "published",
                    "description": row["short_description"], "full_description": row["full_description"],
                    "source_reference": row["source_reference"], "owning_canonical_sphere_id": row["owning_canonical_sphere_id"],
                    "owning_canonical_sphere_name": row["owning_canonical_sphere_name"],
                    "acquisition_route": row["acquisition_route"], "selection_disposition": row["selection_disposition"],
                    "prerequisite_evaluation_status": row["prerequisite_evaluation_status"],
                    "stable_id": row["canonical_talent_id"],
                }
                for row in collection["records"]
            ]
        else:
            records = []
        total = len(records)
        return {"schema": "TianxiaFactory.CanonicalCatalogSearch.v1", "projection": "canonical_owner_facing", "count": total, "offset": offset, "limit": limit, "records": records[offset:offset + limit]}

    @app.get("/api/catalog/dependencies/{record_id:path}")
    def catalog_dependencies(record_id: str) -> dict[str, Any]:
        return catalog.dependencies(record_id)

    @app.get("/api/catalog/reverse-dependencies/{record_id:path}")
    def catalog_reverse_dependencies(record_id: str) -> dict[str, Any]:
        return catalog.reverse_dependencies(record_id)

    @app.get("/api/catalog/records/{record_id:path}")
    def catalog_record(record_id: str, all_versions: bool = False, projection: str = Query("canonical", pattern="^(canonical|raw)$")) -> dict[str, Any]:
        if projection == "raw":
            return catalog.get(record_id, include_all_versions=all_versions)
        resolved_sphere = canonical_catalog.resolve_sphere_id(record_id)
        if resolved_sphere:
            return canonical_catalog.get_sphere(record_id)
        return canonical_catalog.get_talent(record_id)

    @app.get("/api/catalog/canonical/status")
    def canonical_catalog_status() -> dict[str, Any]:
        return canonical_catalog.status()

    @app.get("/api/catalog/canonical/spheres")
    def canonical_spheres(q: str | None = None) -> dict[str, Any]:
        return canonical_catalog.list_spheres(q=q)

    @app.get("/api/catalog/canonical/spheres/{sphere_id:path}")
    def canonical_sphere_detail(sphere_id: str) -> dict[str, Any]:
        return canonical_catalog.get_sphere(sphere_id)

    @app.get("/api/catalog/canonical/talents")
    def canonical_talents(sphere_id: str | None = None, q: str | None = None) -> dict[str, Any]:
        return canonical_catalog.list_talents(sphere_id=sphere_id, q=q)

    @app.get("/api/catalog/canonical/talents/{talent_id:path}")
    def canonical_talent_detail(talent_id: str) -> dict[str, Any]:
        return canonical_catalog.get_talent(talent_id)

    @app.post("/api/catalog/canonical/creator-projection")
    def canonical_creator_projection(body: CanonicalCreatorProjectionRequest) -> dict[str, Any]:
        return canonical_catalog.creator_projection(
            target_cl=body.target_cl,
            acquired_sphere_ids=body.acquired_sphere_ids,
            background_sphere_ids=body.background_sphere_ids,
            free_talent_grants=body.free_talent_grants,
            ordinary_talent_ids=body.ordinary_talent_ids,
            existing_talent_ids=body.existing_talent_ids,
            path_ids=body.path_ids,
            subpath_or_tradition_ids=body.subpath_or_tradition_ids,
            method_ids=body.method_ids,
            foundation_or_feature_ids=body.foundation_or_feature_ids,
            character_feature_ids=body.character_feature_ids,
            structural_authority_ids=body.structural_authority_ids,
            equipment_evidence_ids=body.equipment_evidence_ids,
            acquisition_evidence_ids=body.acquisition_evidence_ids,
            project_id=body.project_id,
            character_id=body.character_id,
        )

    @app.get("/api/catalog/canonical/diagnostics")
    def canonical_catalog_diagnostics() -> dict[str, Any]:
        return canonical_catalog.diagnostics()

    @app.get("/api/content-packs")
    def content_pack_list() -> list[dict[str, Any]]:
        return packs.list()

    @app.get("/api/inbox")
    def inbox() -> list[dict[str, Any]]:
        return [{"name": p.name, "bytes": p.stat().st_size} for p in sorted(settings.inbox_dir.iterdir()) if p.is_file()]

    @app.post("/api/foundation-packs/prepare")
    def foundation_pack_prepare(body: FoundationHandoffPrepareRequest) -> dict[str, Any]:
        """Convert the pinned Foundation handoff into a deterministic native pack.

        Preparation deliberately does not install or trust the result.  The
        caller must review the exact archive digest and make a separate,
        explicit human-trust install request.
        """

        source = resolve_inside(settings.inbox_dir, body.package_name)
        output = resolve_inside(settings.inbox_dir, body.output_name)
        if output.suffix.lower() != ".zip":
            raise FoundryError(
                "FOUNDATION_OUTPUT_MUST_BE_ZIP",
                "The prepared Foundation Content Pack output must use a .zip filename.",
                details={"output_name": body.output_name},
            )
        if source == output:
            raise FoundryError(
                "FOUNDATION_OUTPUT_MUST_BE_DISTINCT",
                "The prepared Content Pack output must be distinct from the immutable handoff input.",
                details={"package_name": body.package_name, "output_name": body.output_name},
            )
        if output.exists():
            raise FoundryError(
                "FOUNDATION_OUTPUT_EXISTS",
                "The requested Foundation Content Pack output already exists; existing inbox files are never overwritten.",
                details={"output_name": body.output_name},
                status_code=409,
            )

        temporary_paths: list[Path] = []
        try:
            handoff = load_foundation_handoff(source)
            authorities = load_pinned_core_foundation_authorities(db)
            plan = build_foundation_pack_plan(
                handoff,
                authorize_stage_repairs=body.authorize_stage_repairs,
                core_foundation_authorities=authorities,
            )

            # Both builds occur inside the inbox.  The requested output is only
            # published after exact-byte determinism and native validation pass.
            for label in ("first", "second"):
                descriptor, raw_path = tempfile.mkstemp(
                    prefix=f".foundation_{label}_",
                    suffix=".zip",
                    dir=settings.inbox_dir,
                )
                os.close(descriptor)
                path = Path(raw_path)
                path.unlink()
                temporary_paths.append(path)
            first, second = temporary_paths
            first_report = write_deterministic_foundation_pack(plan, first)
            second_report = write_deterministic_foundation_pack(plan, second)
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()
            if first_bytes != second_bytes:
                raise FoundryError(
                    "FOUNDATION_PACK_DETERMINISM_FAILED",
                    "Two clean Foundation Content Pack builds were not byte-identical.",
                    details={
                        "first_sha256": first_report["archive_sha256"],
                        "second_sha256": second_report["archive_sha256"],
                    },
                )

            validation = packs.validate(first)
            if not validation.get("valid"):
                raise FoundryError(
                    "FOUNDATION_NATIVE_PACK_VALIDATION_FAILED",
                    "The deterministic Foundation Content Pack failed native Content Pack validation.",
                    details={"issues": validation.get("issues", [])},
                )
            if validation.get("trust_state") != "quarantined" or validation.get("selectable") is not False:
                raise FoundryError(
                    "FOUNDATION_PREPARED_PACK_TRUST_STATE_INVALID",
                    "An uninstalled locally prepared Foundation pack must remain quarantined and unselectable pending exact human trust.",
                    details={
                        "trust_state": validation.get("trust_state"),
                        "selectable": validation.get("selectable"),
                    },
                )

            # Publish with an atomic no-replace hard link.  Rechecking via an
            # ordinary exists() call is not enough: a concurrent local request
            # could otherwise create the destination before os.replace and lose
            # its file.  Both paths are in the inbox and therefore on one volume.
            try:
                os.link(first, output)
            except FileExistsError as exc:
                raise FoundryError(
                    "FOUNDATION_OUTPUT_EXISTS",
                    "The requested Foundation Content Pack output appeared during preparation; it was not overwritten.",
                    details={"output_name": body.output_name},
                    status_code=409,
                ) from exc
            first.unlink()
            temporary_paths.remove(first)
            digest = first_report["archive_sha256"]
            semantic = plan.semantic_report
            replacement_count = len((plan.replacement_map or {}).get("replacements", []))
            return {
                "prepared": True,
                "output_name": output.name,
                "output_sha256": digest,
                "output_bytes": output.stat().st_size,
                "pack_id": plan.pack_id,
                "version": plan.version,
                "content_hash": first_report["content_hash"],
                "counts": semantic["counts"],
                "mechanic_counts": semantic["mechanic_counts"],
                "repair_count": len(semantic.get("repair_receipts", [])),
                "replacement_count": replacement_count,
                "deterministic_rebuild": {
                    "byte_identical": True,
                    "first_sha256": digest,
                    "second_sha256": second_report["archive_sha256"],
                },
                "native_validation": {
                    "valid": True,
                    "issue_count": len(validation.get("issues", [])),
                    "record_count": validation.get("record_count"),
                    "trust_state": validation.get("trust_state"),
                    "selectable": validation.get("selectable"),
                },
                "next_step_trust_instruction": {
                    "endpoint": "/api/content-packs/install",
                    "package_name": output.name,
                    "archive_sha256": digest,
                    "confirmation": "TRUST_LOCAL_CONTENT_PACK:" + digest,
                    "instruction": "Review this exact SHA-256, then install with a named human approver. Preparation itself grants no trust.",
                },
            }
        except FoundationHandoffError as exc:
            raise FoundryError(exc.code, str(exc), details=exc.details) from exc
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

    @app.post("/api/content-packs/validate")
    def content_pack_validate(body: PackageRequest) -> dict[str, Any]:
        return packs.validate(resolve_inside(settings.inbox_dir, body.package_name))

    @app.post("/api/content-packs/exact-trust-challenge")
    def content_pack_exact_trust_challenge(body: PackageChallengeRequest) -> dict[str, Any]:
        package = resolve_inside(settings.inbox_dir, body.package_name)
        return packs.issue_exact_trust_challenge(package, ttl_seconds=body.ttl_seconds)

    @app.post("/api/content-packs/install")
    def content_pack_install(body: PackageRequest) -> dict[str, Any]:
        package = resolve_inside(settings.inbox_dir, body.package_name)
        validation = packs.validate(package)
        if validation.get("valid") and validation.get("authority") == "quarantined" and body.human_trust is None:
            raise FoundryError(
                "PACK_INSTALL_TRUST_REQUIRED",
                "Unsigned local Content Packs require exact-archive human trust before installation. Validation alone never installs or grants authority.",
                details={"package_name": body.package_name, "archive_sha256": validation.get("package_identity", {}).get("archive_sha256")},
            )
        if body.human_trust is not None and (not body.challenge_id or not body.nonce):
            raise FoundryError("APPROVAL_CHALLENGE_REQUIRED", "Exact Content Pack trust requires a one-time server challenge.", status_code=409)
        return packs.install(
            package, human_trust=body.human_trust.model_dump() if body.human_trust else None,
            challenge_id=body.challenge_id, nonce=body.nonce,
        )

    @app.get("/api/content-packs/{pack_id}/{version}")
    def content_pack_inspect(pack_id: str, version: str) -> dict[str, Any]:
        return packs.inspect(pack_id, version)

    @app.post("/api/content-packs/{pack_id}/{version}/lifecycle-challenge")
    def content_pack_lifecycle_challenge(pack_id: str, version: str, body: PackStateChallengeRequest) -> dict[str, Any]:
        return packs.issue_lifecycle_challenge(pack_id, version, body.state, superseded_by=body.superseded_by, ttl_seconds=body.ttl_seconds)

    def _require_pack_challenge(body: PackStateRequest) -> None:
        if not body.challenge_id or not body.nonce:
            raise FoundryError("APPROVAL_CHALLENGE_REQUIRED", "Content Pack lifecycle authority requires a one-time server challenge.", status_code=409)

    @app.post("/api/content-packs/{pack_id}/{version}/publish")
    def content_pack_publish(pack_id: str, version: str, body: PackStateRequest) -> dict[str, Any]:
        _require_pack_challenge(body)
        return packs.set_state(pack_id, version, "published", actor=body.actor or principal.display_name, challenge_id=body.challenge_id, nonce=body.nonce)

    @app.post("/api/content-packs/{pack_id}/{version}/supersede")
    def content_pack_supersede(pack_id: str, version: str, body: PackStateRequest) -> dict[str, Any]:
        _require_pack_challenge(body)
        return packs.set_state(pack_id, version, "superseded", actor=body.actor or principal.display_name, superseded_by=body.superseded_by, challenge_id=body.challenge_id, nonce=body.nonce)

    @app.post("/api/content-packs/{pack_id}/{version}/retire")
    def content_pack_retire(pack_id: str, version: str, body: PackStateRequest) -> dict[str, Any]:
        _require_pack_challenge(body)
        return packs.set_state(pack_id, version, "retired", actor=body.actor or principal.display_name, challenge_id=body.challenge_id, nonce=body.nonce)

    @app.delete("/api/content-packs/{pack_id}/{version}")
    def content_pack_uninstall(pack_id: str, version: str, body: PackStateRequest) -> dict[str, Any]:
        _require_pack_challenge(body)
        return packs.uninstall(pack_id, version, actor=body.actor or principal.display_name, challenge_id=body.challenge_id, nonce=body.nonce)


    @app.get("/api/non-sphere/authority/status")
    def non_sphere_authority_status() -> dict[str, Any]:
        return non_sphere_authority.authority_status()

    @app.get("/api/non-sphere/paths")
    def non_sphere_paths() -> dict[str, Any]:
        return non_sphere_authority.path_catalog()

    @app.get("/api/non-sphere/methods")
    def non_sphere_methods(project_id: str | None = None) -> dict[str, Any]:
        state = non_sphere_authority.get_state(project_id) if project_id else None
        return non_sphere_authority.method_catalog(state)

    @app.get("/api/non-sphere/foundations")
    def non_sphere_foundations() -> dict[str, Any]:
        return non_sphere_authority.foundation_catalog()

    @app.get("/api/non-sphere/backgrounds")
    def non_sphere_backgrounds() -> dict[str, Any]:
        return non_sphere_authority.background_catalog()

    @app.get("/api/non-sphere/subpaths")
    def non_sphere_subpaths(path_id: str | None = None) -> dict[str, Any]:
        return non_sphere_authority.subpath_catalog(path_id)

    @app.get("/api/non-sphere/projects/{project_id}/state")
    def non_sphere_project_state(project_id: str) -> dict[str, Any]:
        return non_sphere_authority.get_state(project_id)

    @app.put("/api/non-sphere/projects/{project_id}/state")
    def non_sphere_project_state_put(project_id: str, body: NS1RStateUpdateRequest) -> dict[str, Any]:
        return non_sphere_authority.save_state(project_id, body.state)

    @app.post("/api/non-sphere/projects/{project_id}/primary-method")
    def non_sphere_primary_method(project_id: str, body: NS1RPrimaryMethodRequest) -> dict[str, Any]:
        return non_sphere_authority.set_primary_method(project_id, body.method_id, body.evidence_ids)

    @app.post("/api/non-sphere/projects/{project_id}/target-cl")
    def non_sphere_target_cl(project_id: str, body: NS1RTargetCLRequest) -> dict[str, Any]:
        return non_sphere_authority.set_target_cl(project_id, body.target_cl)

    @app.post("/api/non-sphere/projects/{project_id}/access-sources")
    def non_sphere_access_sources(project_id: str, body: NS1RAccessSourcesRequest) -> dict[str, Any]:
        return non_sphere_authority.set_access_sources(project_id, body.evidence_ids)

    @app.post("/api/non-sphere/projects/{project_id}/path-attainment")
    def non_sphere_path_attainment(project_id: str, body: NS1RPathAttainmentRequest) -> dict[str, Any]:
        return non_sphere_authority.set_path_attainment(
            project_id, body.path_id, body.attainment,
            operation_mode=body.operation_mode, source_record_id=body.source_record_id,
        )

    @app.post("/api/non-sphere/projects/{project_id}/advancement")
    def non_sphere_advancement(project_id: str, body: NS1RAPAllocationRequest) -> dict[str, Any]:
        return non_sphere_authority.allocate_advancement(
            project_id, body.allocations, evidence_id=body.evidence_id, idempotency_key=body.idempotency_key,
        )

    @app.post("/api/non-sphere/projects/{project_id}/resource")
    def non_sphere_resource(project_id: str, body: NS1RResourceRequest) -> dict[str, Any]:
        return non_sphere_authority.set_resource(project_id, body.path_id, current=body.current, maximum=body.maximum)

    @app.post("/api/non-sphere/projects/{project_id}/subpath")
    def non_sphere_subpath(project_id: str, body: NS1RSubpathRequest) -> dict[str, Any]:
        return non_sphere_authority.select_subpath(project_id, body.path_id, body.selection_id, body.evidence_ids)

    @app.post("/api/non-sphere/projects/{project_id}/foundation")
    def non_sphere_foundation(project_id: str, body: NS1RFoundationRequest) -> dict[str, Any]:
        return non_sphere_authority.select_foundation(project_id, body.foundation_id)

    @app.get("/api/non-sphere/projects/{project_id}/evidence")
    def non_sphere_project_evidence(project_id: str) -> dict[str, Any]:
        return non_sphere_authority.available_evidence(project_id)

    @app.get("/api/non-sphere/projects/{project_id}/ap-eligibility")
    def non_sphere_ap_eligibility(project_id: str, path_id: str | None = None) -> dict[str, Any]:
        return non_sphere_authority.ap_eligibility(project_id, path_id)

    @app.post("/api/non-sphere/compatibility/resolve")
    def non_sphere_compatibility(body: NS1RCompatibilityRequest) -> dict[str, Any]:
        return non_sphere_authority.resolve_compatibility(body.method_id, body.foundation_id, body.active_path_ids)

    @app.get("/api/non-sphere/projects/{project_id}/readiness")
    def non_sphere_readiness(project_id: str) -> dict[str, Any]:
        return non_sphere_authority.readiness(project_id)

    @app.post("/api/non-sphere/backgrounds/validate")
    def non_sphere_background_validate(body: NS1RBackgroundValidationRequest) -> dict[str, Any]:
        return non_sphere_authority.validate_background(body.background_id, selected_route_ids=body.selected_route_ids)

    @app.post("/api/non-sphere/migration/preview")
    def non_sphere_migration_preview(body: NS1RMigrationPreviewRequest) -> dict[str, Any]:
        return non_sphere_authority.migration_preview(body.legacy)

    @app.get("/api/character-builder/options")
    def character_builder_options() -> dict[str, Any]:
        return character_builder.options()

    @app.post("/api/character-builder/method-compatibility")
    def character_builder_method_compatibility(
        body: CharacterBuilderMethodCompatibilityRequest,
    ) -> dict[str, Any]:
        return character_builder.method_compatibility(body.selected_path_ids)

    @app.get("/api/character-builder/recovery")
    def character_builder_recovery() -> list[dict[str, Any]]:
        archived_project_ids = character_library_archives.archived_project_ids() | hidden_project_ids(db)
        return [
            item for item in character_creation.recoverable()
            if not isinstance(item, dict) or item.get("project_id") not in archived_project_ids
        ]

    @app.post("/api/character-builder/projects")
    def character_builder_create(body: CharacterSheetCreateRequest) -> dict[str, Any]:
        return character_builder.create_project(
            working_name=body.working_name,
            concept=body.concept,
            target_cl=body.target_cl,
            power_band=body.power_band,
            source_reference=body.source_reference,
            creation_mode=body.creation_mode,
            generation_route=body.generation_route,
            ability_scores=body.ability_scores,
            selections=body.selections,
            sphere_priority_ids=body.sphere_priority_ids,
            talent_priority_ids=body.talent_priority_ids,
            method_planning_mode=body.method_planning_mode,
            method_preference_id=body.method_preference_id,
            method_route_choice=body.method_route_choice,
            method_learning_note=body.method_learning_note,
            canonical_sphere_ids=body.canonical_sphere_ids,
            sphere_free_talent_grants=body.sphere_free_talent_grants,
            ordinary_talent_ids=body.ordinary_talent_ids,
            access_source_records=[row.model_dump() for row in body.evidence_ids],
            background_route_ids=body.background_route_ids,
            gear_preference_ids=body.gear_preference_ids,
            autogen_seed=body.autogen_seed,
        )

    # Items tab (owner 2026-09-24): make treasures and give them to characters.
    from factory_authoring import owner_items as owner_item_rules

    owner_item_store = owner_item_rules.OwnerItemStore(settings.data_dir / "owner_items")
    custom_item_library = owner_item_rules.CustomItemLibrary(settings.data_dir / "custom_items")

    @app.get("/api/items/custom")
    def items_custom() -> dict[str, Any]:
        return {"items": custom_item_library.items(), "instructions": owner_item_rules.CUSTOM_INSTRUCTIONS,
                "example": owner_item_rules.CUSTOM_EXAMPLE}

    @app.post("/api/items/custom")
    def items_custom_add(body: CustomItemsImportRequest) -> dict[str, Any]:
        added = custom_item_library.add(body.items, source=body.source)
        return {"added": added, "items": custom_item_library.items()}

    @app.delete("/api/items/custom/{custom_id}")
    def items_custom_remove(custom_id: str) -> dict[str, Any]:
        return {"items": custom_item_library.remove(custom_id)}

    @app.get("/api/items/catalog")
    def items_catalog() -> dict[str, Any]:
        return owner_item_rules.catalog()

    @app.post("/api/items/choices")
    def items_choices(body: OwnerItemChoicesRequest) -> dict[str, Any]:
        if body.kind == "weapon":
            return owner_item_rules.weapon_choices(body.chassis_id, body.grade, body.material_id, body.chosen_ids)
        return owner_item_rules.armour_choices(body.chassis_id, body.grade, body.material_id, body.chosen_ids)

    @app.post("/api/items/preview")
    def items_preview(body: OwnerItemSpecRequest) -> dict[str, Any]:
        return owner_item_rules.make_item(body.model_dump(), custom_item_library)

    @app.get("/api/items/characters")
    def items_characters() -> dict[str, Any]:
        finished = combat.factory_characters()
        finished_ids = {row["project_id"] for row in finished}
        archived = character_library_archives.archived_project_ids() | hidden_project_ids(db)
        # A light query on the projects table only: the full project list, or any
        # read of character_creation_runs columns (tens of MB of JSON per row),
        # takes seconds to minutes.  Quick Build knows the names it built.
        with db.connection() as conn:
            rows = conn.execute("SELECT project_id, working_name, created_at FROM projects ORDER BY created_at DESC").fetchall()
        quick_names = {item["project_id"]: item["name"] for batch in quick_builds.list(limit=200) for item in batch["items"]
                       if item.get("project_id") and item.get("name")}
        building = [
            {"project_id": row["project_id"], "display_name": quick_names.get(row["project_id"]) or row["working_name"] or row["project_id"][:8],
             "created_at": row["created_at"]}
            for row in rows
            if row["project_id"] not in finished_ids and row["project_id"] not in archived
        ]
        return {"finished": [row for row in finished if row["project_id"] not in archived], "building": building}

    @app.get("/api/items/owned/{project_id}")
    def items_owned(project_id: str) -> dict[str, Any]:
        return {"project_id": project_id, "items": owner_item_store.items(project_id)}

    @app.post("/api/items/owned/{project_id}")
    def items_give(project_id: str, body: OwnerItemSpecRequest) -> dict[str, Any]:
        entry = owner_item_store.give(project_id, body.model_dump(), custom_item_library)
        return {"project_id": project_id, "item": entry, "items": owner_item_store.items(project_id)}

    @app.delete("/api/items/owned/{project_id}/{item_uid}")
    def items_remove(project_id: str, item_uid: str) -> dict[str, Any]:
        return {"project_id": project_id, "items": owner_item_store.remove(project_id, item_uid)}

    @app.post("/api/items/owned/{project_id}/{item_uid}/equip")
    def items_equip(project_id: str, item_uid: str) -> dict[str, Any]:
        return {"project_id": project_id, "items": owner_item_store.equip(project_id, item_uid)}

    @app.get("/api/quick-builds")
    def quick_builds_list() -> dict[str, Any]:
        return {"batches": quick_builds.list()}

    @app.post("/api/quick-builds")
    def quick_builds_submit(body: QuickBuildRequest) -> dict[str, Any]:
        return quick_builds.submit(items=[row.model_dump() for row in body.items], target_cl=body.target_cl,
                                   power_band=body.power_band, finalize=body.finalize)

    @app.get("/api/character-builder/gear-catalog")
    def character_builder_gear_catalog() -> dict[str, Any]:
        """Weapons, armour and shields the owner may name as preferred gear."""
        from factory_authoring.starting_kits import gear_catalog

        return {"items": gear_catalog()}

    @app.post("/api/character-builder/projects/{project_id}/catalog-choice-lock")
    def character_builder_catalog_choice_lock(
        project_id: str, body: CanonicalCatalogChoiceLockRequest,
    ) -> dict[str, Any]:
        return character_builder.commit_catalog_choices(
            project_id,
            acquired_sphere_ids=body.acquired_sphere_ids,
            free_talent_grants=body.free_talent_grants,
            ordinary_talent_ids=body.ordinary_talent_ids,
        )

    @app.post("/api/character-builder/projects/{project_id}/normal-first-cycle-catalog-choice-lock")
    def character_builder_normal_first_cycle_catalog_choice_lock(project_id: str) -> dict[str, Any]:
        return character_builder.commit_normal_first_cycle_catalog_choices(project_id)

    @app.get("/api/character-builder/projects/{project_id}/lifecycle")
    def character_builder_lifecycle(project_id: str) -> dict[str, Any]:
        return projects.builder_lifecycle(project_id)

    @app.post("/api/character-builder/projects/{project_id}/save-draft")
    def character_builder_save_draft(project_id: str) -> dict[str, Any]:
        return projects.save_builder_draft(project_id)

    @app.delete("/api/character-builder/projects/{project_id}/temporary")
    def character_builder_discard_temporary(project_id: str) -> dict[str, Any]:
        return projects.discard_temporary_project(project_id, reason="owner_abandoned_or_started_over")

    @app.post("/api/projects")
    def project_create(body: CreateProjectRequest) -> dict[str, Any]:
        return projects.create_project(
            working_name=body.working_name,
            pack_locks=[x.model_dump() for x in body.pack_locks],
            quality_target=body.quality_target,
            user_locks=body.user_locks,
            source_evidence=body.source_evidence,
        )

    @app.get("/api/projects")
    def project_list() -> list[dict[str, Any]]:
        archived_project_ids = character_library_archives.archived_project_ids()
        return [
            project for project in projects.list_projects()
            if project.get("project_id") not in archived_project_ids
        ]

    @app.get("/api/projects/{project_id}")
    def project_get(project_id: str) -> dict[str, Any]:
        return projects.get_project(project_id)

    @app.get("/api/projects/{project_id}/canonical")
    def project_canonical(project_id: str) -> dict[str, Any]:
        return projects.get_project(project_id)["project"]

    @app.get("/api/projects/{project_id}/read-models")
    def project_read_models(project_id: str) -> dict[str, Any]:
        return projects.read_models(project_id)

    @app.get("/api/projects/{project_id}/content-locks")
    def project_locks(project_id: str) -> list[dict[str, Any]]:
        return projects.get_project(project_id)["content_locks"]

    def _custom_training_source_envelope(body: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
        values = body.model_dump()
        for key in exclude or set():
            values.pop(key, None)
        return values

    @app.get("/api/projects/{project_id}/manual-lineage-training-source")
    @app.get("/api/projects/{project_id}/manual-lineage-training-source/contract")
    def manual_lineage_training_source_contract(project_id: str) -> dict[str, Any]:
        """Read-only owner contract; it never chooses a route or calls AI."""
        return projects.custom_training_source_contract(project_id)

    @app.get("/api/projects/{project_id}/manual-lineage-training-source/targets")
    @app.get("/api/projects/{project_id}/manual-lineage-training-source/legal-targets")
    def manual_lineage_training_source_targets(
        project_id: str,
        training_type: str = Query(..., pattern="^(new_sphere|known_sphere_talent|recorded_art)$"),
        q: str | None = Query(default=None, max_length=200),
        limit: int = Query(default=50, ge=1, le=50),
    ) -> dict[str, Any]:
        return projects.search_custom_training_source_targets(
            project_id,
            training_type,
            query=q,
            limit=limit,
        )

    @app.post("/api/projects/{project_id}/manual-lineage-training-source/challenge")
    def manual_lineage_training_source_challenge(
        project_id: str,
        body: CustomTrainingSourceChallengeRequest,
    ) -> dict[str, Any]:
        envelope = _custom_training_source_envelope(body, exclude={"ttl_seconds"})
        issued = projects.issue_custom_training_source_challenge(
            project_id,
            envelope,
            ttl_seconds=body.ttl_seconds,
        )
        return {
            **issued,
            "status": "challenge_issued",
            "sealed": False,
            "owner_warning": "Review the exact source text and hashes before approval. Approval seals one immutable project record; a new candidate revision and regenerated review are still required.",
        }

    @app.post("/api/projects/{project_id}/manual-lineage-training-source/approve")
    def manual_lineage_training_source_approve(
        project_id: str,
        body: CustomTrainingSourceApprovalRequest,
    ) -> dict[str, Any]:
        envelope = _custom_training_source_envelope(body, exclude={"challenge_id", "nonce"})
        receipt = projects.approve_and_seal_custom_training_source(
            project_id,
            envelope,
            body.challenge_id,
            body.nonce,
        )
        return {
            **receipt,
            "sealed": True,
            "candidate_revision_required": True,
            "owner_message": "The exact source is sealed. Create a new candidate revision and regenerate candidate/binding review before Finalize.",
        }

    @app.get("/api/projects/{project_id}/catalog/effective")
    def project_effective_catalog(
        project_id: str,
        content_type: str | None = None,
        include_replaced: bool = False,
    ) -> dict[str, Any]:
        return catalog.effective_catalog(
            project_id,
            content_types={content_type} if content_type else None,
            include_replaced=include_replaced,
        )

    @app.get("/api/projects/{project_id}/events")
    def project_events(project_id: str) -> list[dict[str, Any]]:
        return projects.timeline(project_id)

    @app.post("/api/projects/{project_id}/draft-events")
    def project_append_draft(project_id: str, body: DraftEventRequest) -> dict[str, Any]:
        return projects.append_draft(project_id, body.model_dump())

    @app.post("/api/draft-events/{draft_id}/validate")
    def draft_validate(draft_id: str) -> dict[str, Any]:
        return projects.validate_draft(draft_id)

    @app.post("/api/draft-events/{draft_id}/approve")
    def draft_approve(draft_id: str, body: ApproveRequest) -> dict[str, Any]:
        return projects.approve_draft(draft_id, body.approved_by)

    @app.post("/api/draft-events/{draft_id}/commit")
    def draft_commit(draft_id: str) -> dict[str, Any]:
        return projects.commit_draft(draft_id)

    @app.post("/api/projects/{project_id}/replay")
    def project_replay(project_id: str) -> dict[str, Any]:
        return projects.replay(project_id)

    @app.get("/api/projects/{project_id}/event-chain")
    def project_chain(project_id: str) -> dict[str, Any]:
        return projects.verify_chain(project_id)

    @app.post("/api/projects/{project_id}/read-models/rebuild")
    def project_rebuild_read_models(project_id: str) -> dict[str, Any]:
        return projects.rebuild_read_models(project_id)

    @app.get("/api/projects/{project_id}/compatibility-projection")
    def compatibility_projection(project_id: str) -> dict[str, Any]:
        return projects.compatibility_projection_status(project_id)


    @app.post("/api/projects/{project_id}/stage1/user-locks")
    def stage1_user_locks(project_id: str, body: Stage1UserLocksRequest) -> dict[str, Any]:
        return projects.append_user_locks(project_id, body.locks)

    @app.post("/api/projects/{project_id}/stage1/prompt")
    def stage1_prompt_generate(project_id: str, insight_page: int | None = Query(None, ge=0)) -> dict[str, Any]:
        result = stage1.generate_prompt(project_id, insight_page=insight_page)
        # The prompt text already embeds the complete envelope. Returning the
        # envelope a second time doubled this owner-facing response to several
        # megabytes and could stall constrained browser bridges. The sealed
        # envelope remains available through Stage1ClipboardService/get_prompt.
        return {key: value for key, value in result.items() if key != "envelope"}

    @app.get("/api/stage1/prompts/{prompt_id}")
    def stage1_prompt_get(prompt_id: str) -> dict[str, Any]:
        return stage1.get_prompt(prompt_id)

    @app.post("/api/stage1/prompts/{prompt_id}/save-markdown")
    def stage1_prompt_save_markdown(prompt_id: str) -> dict[str, Any]:
        return stage1.save_prompt_file(prompt_id, zipped=False)

    @app.post("/api/stage1/prompts/{prompt_id}/save-zip")
    def stage1_prompt_save_zip(prompt_id: str) -> dict[str, Any]:
        return stage1.save_prompt_file(prompt_id, zipped=True)

    @app.post("/api/owner-artifacts/stage")
    def owner_artifact_stage(body: OwnerArtifactStageRequest) -> dict[str, Any]:
        kind = body.artifact_kind
        if kind == "chat_request":
            prompt_id = body.prompt_id
            if not prompt_id:
                if not body.project_id:
                    raise FoundryError("OWNER_ARTIFACT_PROJECT_REQUIRED", "Select a character project first.", status_code=409)
                prompt_id = stage1.prepare_prompt(body.project_id)["prompt_id"]
            prompt = stage1.get_prompt(prompt_id)
            if body.project_id and prompt["project_id"] != body.project_id:
                raise FoundryError("OWNER_ARTIFACT_PROJECT_PROMPT_MISMATCH", "The Stage 1 request does not belong to the selected project.", status_code=409)
            result = stage1.save_prompt_file(prompt_id, zipped=True, reuse_existing=True)
            source = Path(result["path"]).resolve()
        elif kind == "project_backup":
            if not body.project_id:
                raise FoundryError("OWNER_ARTIFACT_PROJECT_REQUIRED", "Select a character project first.", status_code=409)
            result = projects.export_project(body.project_id, body.filename)
            source = Path(result["path"]).resolve()
        elif kind == "completed_character":
            if not body.project_id:
                raise FoundryError("OWNER_ARTIFACT_PROJECT_REQUIRED", "Select a completed character first.", status_code=409)
            source, result = _verified_completed_character_source(portable_characters, body.project_id)
        elif kind == "gm_character":
            if not body.project_id:
                raise FoundryError("OWNER_ARTIFACT_PROJECT_REQUIRED", "Select a completed character first.", status_code=409)
            result = gm_exports.export(body.project_id, filename=body.filename)
            source = Path(result["path"]).resolve()
        else:
            if not body.match_id:
                raise FoundryError("OWNER_ARTIFACT_MATCH_REQUIRED", "Select a legal saved fight first.", status_code=409)
            verification = combat.verify(body.match_id)
            if verification.get("status") not in {"PASS", "VERIFIED", "READY"}:
                raise FoundryError("COMBAT_PACKAGE_NOT_LEGAL", "This fight is not currently legal for export.", details=verification, status_code=409)
            source = combat.export(body.match_id).resolve()
            result = {"match_id": body.match_id, "verification": verification}
        if not source.is_file():
            raise FoundryError("OWNER_ARTIFACT_STAGE_FAILED", "The requested artifact was not produced.", status_code=500)
        artifact_id = secrets.token_urlsafe(18)
        staged_owner_artifacts[artifact_id] = {"path": source, "kind": kind, "created_at": utcnow()}
        return {"artifact_id": artifact_id, "artifact_kind": kind, "filename": source.name, "path": str(source), "bytes": source.stat().st_size, "sha256": sha256_file(source), "ready_for_save_as": True, "source_result": result}

    @app.post("/api/owner-artifacts/save-as")
    def owner_artifact_save_as(body: OwnerArtifactSaveAsRequest) -> dict[str, Any]:
        staged = staged_owner_artifacts.get(body.artifact_id)
        if not staged:
            raise FoundryError("OWNER_ARTIFACT_NOT_STAGED", "Stage the artifact again before saving it.", status_code=404)
        source = Path(staged["path"]).resolve()
        if not source.is_file():
            raise FoundryError("OWNER_ARTIFACT_SOURCE_MISSING", "The staged artifact is no longer available.", status_code=409)
        destination = Path(body.destination_path).expanduser().resolve()
        if destination.suffix.lower() != ".zip":
            raise FoundryError("OWNER_SAVE_AS_EXTENSION", "Choose a .zip destination.", status_code=400)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not body.overwrite:
            raise FoundryError("OWNER_SAVE_AS_EXISTS", "A file already exists at that location. Choose another name or explicitly replace it.", details={"path": str(destination)}, status_code=409)
        temporary = destination.with_name(destination.name + ".tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        return {"saved": True, "artifact_id": body.artifact_id, "artifact_kind": staged["kind"], "path": str(destination), "filename": destination.name, "bytes": destination.stat().st_size, "sha256": sha256_file(destination)}

    @app.get("/api/combat/accepted-demo/preflight")
    def combat_accepted_demo_preflight() -> dict[str, Any]:
        catalog = combat.catalog()
        fighters = [row for row in catalog['projections'] if row.get('primary_combatant') and not row.get('installed_character')]
        return {"schema": "TianxiaFactory.AcceptedDemoPreflight.v1", "read_only": True, "writes_performed": 0,
                "expected": {"combatants": len(fighters)}, "inventory_count": len(fighters),
                "encounter": catalog['encounters'][0], "mismatches": [], "ready": len(fighters) >= 2}

    @app.post("/api/character-builder/exports/open-folder")
    def character_builder_open_exports_folder() -> dict[str, Any]:
        folder = (settings.exports_dir / "CharacterBuilder").resolve()
        folder.mkdir(parents=True, exist_ok=True)
        opened = False
        if os.name == "nt":
            try:
                os.startfile(str(folder))  # type: ignore[attr-defined]
                opened = True
            except OSError as exc:
                raise FoundryError("CHARACTER_BUILDER_OPEN_FOLDER_FAILED", "The export folder could not be opened.", details={"path": str(folder), "error": str(exc)}) from exc
        return {"path": str(folder), "opened": opened, "message": "Export folder opened." if opened else "The export folder path is shown; opening it automatically is available in the native Windows app."}

    @app.post("/api/stage1/prompts/{prompt_id}/responses/load-file")
    async def stage1_response_load_file(prompt_id: str, request: Request, filename: str = Query(..., min_length=1, max_length=240)) -> dict[str, Any]:
        stage1.get_prompt(prompt_id)
        return stage1.load_reply_file(filename, await request.body())

    @app.post("/api/stage1/prompts/{prompt_id}/responses/load-zip")
    async def stage1_response_load_zip(prompt_id: str, request: Request, filename: str = Query(..., min_length=1, max_length=240)) -> dict[str, Any]:
        stage1.get_prompt(prompt_id)
        return stage1.load_reply_zip(filename, await request.body())

    @app.post("/api/stage1/prompts/{prompt_id}/responses/validate")
    def stage1_response_validate(prompt_id: str, body: Stage1ResponseRequest) -> dict[str, Any]:
        return stage1.validate_response(prompt_id, body.response_text, prior_attempt_id=body.prior_attempt_id)

    @app.get("/api/stage1/attempts/{attempt_id}")
    def stage1_attempt_get(attempt_id: str) -> dict[str, Any]:
        return stage1._attempt_result(attempt_id)

    @app.post("/api/stage1/attempts/{attempt_id}/approve-commit")
    def stage1_approve_commit(attempt_id: str, body: Stage1ApproveCommitRequest) -> dict[str, Any]:
        return stage1.approve_and_commit(attempt_id, body.approved_by)

    @app.get("/api/projects/{project_id}/stage1/status")
    def stage1_project_status(project_id: str) -> dict[str, Any]:
        return stage1.project_status(project_id)

    @app.post("/api/projects/{project_id}/stage2/proposals")
    def stage2_proposal_create(project_id: str, body: Stage2ProposalRequest) -> dict[str, Any]:
        payload = body.model_dump()
        # Never infer a mechanical contract version.  Explicit v1 remains
        # available for legacy/migration callers, while new HF1 callers use v2.
        # Treating omission as v1 silently downgraded an otherwise v2-shaped
        # request into the weaker legacy compiler.
        if "schema_version" not in body.model_fields_set:
            raise FoundryError(
                "STAGE2_SCHEMA_VERSION_REQUIRED",
                "Stage 2 mechanical proposals must explicitly select the v2 HF1 contract.",
                status_code=422,
            )
        if body.schema_version != PROPOSAL_V2:
            raise FoundryError(
                "STAGE2_LEGACY_WRITE_DISABLED",
                "Legacy Stage 2 proposals are read-only; new mechanical proposals must use the v2 HF1 contract.",
                details={"supplied": body.schema_version, "required": PROPOSAL_V2},
                status_code=409,
            )
        payload["project_id"] = project_id
        return stage2.create_proposal(payload)

    @app.get("/api/projects/{project_id}/stage2/proposals")
    def stage2_proposal_list(project_id: str) -> list[dict[str, Any]]:
        return stage2.list_proposals(project_id)

    @app.get("/api/stage2/proposals/{proposal_id}")
    def stage2_proposal_get(proposal_id: str) -> dict[str, Any]:
        return stage2.get_proposal(proposal_id)

    @app.post("/api/stage2/proposals/{proposal_id}/validate")
    def stage2_proposal_validate(proposal_id: str) -> dict[str, Any]:
        return stage2.validate_proposal(proposal_id)

    @app.post("/api/stage2/proposals/{proposal_id}/approval-challenge")
    def stage2_proposal_approval_challenge(proposal_id: str, body: ApprovalChallengeRequest) -> dict[str, Any]:
        return stage2.issue_approval_challenge(proposal_id, ttl_seconds=body.ttl_seconds)

    @app.post("/api/stage2/proposals/{proposal_id}/approve")
    def stage2_proposal_approve(proposal_id: str, body: Stage2ApproveRequest) -> dict[str, Any]:
        if not body.challenge_id or not body.nonce:
            raise FoundryError("APPROVAL_CHALLENGE_REQUIRED", "Stage 2 approval requires a one-time exact-byte server challenge.", status_code=409)
        return stage2.approve_proposal(proposal_id, body.approved_by, challenge_id=body.challenge_id, nonce=body.nonce)

    @app.post("/api/stage2/proposals/{proposal_id}/commit")
    def stage2_proposal_commit(proposal_id: str, body: Stage2CommitRequest) -> dict[str, Any]:
        if not body.confirm_atomic_commit:
            raise FoundryError("STAGE2_ATOMIC_CONFIRMATION_REQUIRED", "Stage 2 commits are atomic and require explicit confirmation.")
        return stage2.commit_proposal(proposal_id)

    @app.get("/api/projects/{project_id}/stage2/status")
    def stage2_status(project_id: str) -> dict[str, Any]:
        return stage2.status(project_id)

    @app.post("/api/projects/{project_id}/stage2/rebuild")
    def stage2_rebuild(project_id: str) -> dict[str, Any]:
        return stage2.rebuild(project_id)

    @app.get("/api/projects/{project_id}/stage2/audit")
    def stage2_audit(project_id: str) -> dict[str, Any]:
        return stage2.audit(project_id)

    @app.get("/api/projects/{project_id}/stage2/ledger")
    def stage2_ledger(project_id: str) -> dict[str, Any]:
        return stage2.ledger(project_id)

    @app.get("/api/projects/{project_id}/stage2/artifacts/{artifact_name}")
    def stage2_artifact(project_id: str, artifact_name: str):
        media_type, data, _digest = stage2.artifact(project_id, artifact_name)
        return Response(content=data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{artifact_name}"'})

    @app.get("/api/projects/{project_id}/stage2/quarantine/{artifact_name}")
    def stage2_quarantine_artifact(project_id: str, artifact_name: str):
        media_type, data, _digest = stage2.quarantine_artifact(project_id, artifact_name)
        return Response(content=data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{artifact_name}"'})


    @app.post("/api/projects/{project_id}/character-creation/runs")
    def character_creation_start(project_id: str, body: CharacterCreationStartRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.start(project_id, **body.model_dump()))

    @app.get("/api/projects/{project_id}/character-creation/runs")
    def character_creation_list(project_id: str) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "runs": [_character_creation_api_view(run) for run in character_creation.list(project_id)],
        }

    @app.get("/api/projects/{project_id}/character-creation/recovery")
    def character_creation_recovery(project_id: str) -> dict[str, Any]:
        return character_creation.recovery(project_id)

    @app.get("/api/projects/{project_id}/character-creation/preference")
    def character_creation_preference(project_id: str) -> dict[str, Any]:
        return character_creation.preference(project_id)

    @app.put("/api/projects/{project_id}/character-creation/preference")
    def character_creation_set_preference(project_id: str, body: CharacterCreationPreferenceRequest) -> dict[str, Any]:
        return character_creation.set_preference(project_id, body.execution_mode)

    @app.get("/api/character-creation/runs/{run_id}")
    def character_creation_get(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.get(run_id))

    @app.post("/api/character-creation/runs/{run_id}/agent-acquisition-correction")
    def character_creation_agent_acquisition_correction(run_id: str) -> dict[str, Any]:
        """Open the guarded same-run agent correction for an acquisition refusal.

        A fresh authentic mailbox request is linked append-only to the run's
        frozen request, retained response and revision; the consumed original and
        the frozen envelope are never modified.
        """
        provider = getattr(character_creation, "provider", None) or app.state.ai_provider
        if provider is None:
            raise FoundryError(
                "CG1_AGENT_CORRECTION_UNAVAILABLE",
                "No provider is configured for this application instance.",
                status_code=409,
            )
        from character_creation import agent_acquisition_correction as correction

        if correction.load_link(character_creation.db, run_id) is not None:
            # A correction is already open: settle it (collect a late answer,
            # apply, or return the settled result) instead of rebuilding or
            # re-publishing evidence.
            return character_creation.advance_agent_acquisition_correction(run_id, provider)
        return character_creation.open_agent_acquisition_correction(run_id, provider)

    @app.get("/api/character-creation/runs/{run_id}/training-authority-supplement")
    def character_creation_training_authority_supplement(run_id: str, digest: str = Query(min_length=64, max_length=64)) -> dict[str, Any]:
        """Serve the run-bound frozen training authority declared by the prompt.

        Read-only and digest-addressed: the caller must present the digest the
        prompt declared, and the document is re-verified (address, binding,
        schema) before it is returned.
        """
        return character_creation.training_authority_supplement(run_id, digest)

    @app.get("/api/character-creation/runs/{run_id}/gm-candidate")
    def character_creation_gm_candidate(run_id: str) -> dict[str, Any]:
        return character_creation.candidate_gm_summary(run_id)

    @app.get("/api/character-creation/runs/{run_id}/gm-candidate/context")
    def character_creation_gm_candidate_context(run_id: str) -> dict[str, Any]:
        return character_creation.load_candidate_gm_context(run_id)

    @app.post("/api/character-creation/runs/{run_id}/gm-candidate/author")
    def character_creation_gm_candidate_author(run_id: str) -> dict[str, Any]:
        """Explicitly invoke local GM authoring for the captured candidate."""
        return character_creation.candidate_gm_author(run_id)

    @app.get("/api/character-creation/runs/{run_id}/gm-candidate/author/status")
    def character_creation_gm_candidate_author_status(run_id: str) -> dict[str, Any]:
        """Read candidate GM authoring status without a provider call."""
        return character_creation.candidate_gm_author_status(run_id)

    @app.get("/api/character-creation/runs/{run_id}/gm-candidate/author")
    def character_creation_gm_candidate_author_view(run_id: str) -> dict[str, Any]:
        """Read the authenticated candidate GM artifact without rebuilding it."""
        return character_creation.load_candidate_gm_authoring(run_id)

    @app.post("/api/character-creation/runs/{run_id}/gm-candidate/author/build")
    def character_creation_gm_candidate_author_build(run_id: str) -> dict[str, Any]:
        """Provider-free candidate GM review/build from its stored receipt."""
        return character_creation.build_candidate_gm_authoring(run_id)

    @app.post("/api/character-creation/runs/{run_id}/gm-candidate/approval-challenge")
    def character_creation_gm_candidate_approval_challenge(
        run_id: str,
        body: CandidateGMAuthoringApprovalChallengeRequest,
    ) -> dict[str, Any]:
        """Issue an exact-byte owner challenge for candidate GM promotion."""
        return character_creation.issue_candidate_gm_approval_challenge(
            run_id,
            body.ttl_seconds,
        )

    @app.post("/api/character-creation/runs/{run_id}/gm-candidate/approve")
    def character_creation_gm_candidate_approve(
        run_id: str,
        body: CandidateGMAuthoringApprovalRequest,
    ) -> dict[str, Any]:
        """Persist owner approval after consuming the server-issued challenge."""
        return character_creation.approve_candidate_gm(
            run_id,
            body.challenge_id,
            body.nonce,
        )

    @app.get("/api/character-creation/runs/{run_id}/typed-choice-snapshot")
    def character_creation_typed_choice_snapshot(run_id: str):
        run = character_creation.get(run_id)
        snapshot = (run.get("request") or {}).get("typed_choice_snapshot") or {}
        payload = canonical_json(snapshot).encode("utf-8") + b"\n"
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="TYPED_CHOICE_SNAPSHOT_{run_id}.json"'
            },
        )

    @app.get("/api/character-creation/runs/{run_id}/complete-request.zip")
    def character_creation_complete_request_zip(run_id: str):
        download = character_creation.complete_request_download(run_id)
        receipt = download["receipt"]
        return Response(content=download["payload"], media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{download["filename"]}"',
            "X-Tianxia-Request-Payload-SHA256": receipt["request_payload_sha256"],
            "X-Tianxia-Content-Set-SHA256": receipt["content_set_sha256"],
            "X-Tianxia-Final-Zip-SHA256": receipt["final_zip_sha256"],
            "X-Tianxia-Run-Id": receipt["run_id"],
        })

    @app.get("/api/character-creation/runs/{run_id}/manual-ai-correction.zip")
    def character_creation_manual_ai_correction_zip(run_id: str):
        filename, payload = character_creation.manual_ai_correction_zip(run_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Tianxia-Run-Id": run_id,
            },
        )

    @app.get("/api/character-creation/runs/{run_id}/complete-request-save-receipt")
    def character_creation_complete_request_save_receipt(run_id: str) -> dict[str, Any]:
        return character_creation.complete_request_save_receipt(run_id)

    @app.get("/api/character-creation/runs/{run_id}/evidence.json")
    def character_creation_evidence(run_id: str):
        payload = canonical_json(character_creation.evidence(run_id)).encode("utf-8") + b"\n"
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="CG1_BUILD_EVIDENCE_{run_id}.json"'},
        )

    @app.post("/api/character-creation/runs/{run_id}/manual-response")
    def character_creation_manual_response(run_id: str, body: CharacterCreationManualResponseRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.submit_manual(run_id, **body.model_dump()))

    @app.post("/api/character-creation/runs/{run_id}/replace-response")
    def character_creation_replace_response(run_id: str, body: CharacterCreationManualResponseRequest) -> dict[str, Any]:
        return _character_creation_api_view(
            character_creation.replace_response(
                run_id,
                response_text=body.response_text,
                request_sha256=body.request_sha256,
            )
        )

    @app.post("/api/character-creation/runs/{run_id}/retry-local-build")
    def character_creation_retry_local_build(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.retry_local_build(run_id))

    @app.post("/api/character-creation/runs/{run_id}/retry-local-ai-correction")
    def character_creation_retry_local_ai_correction(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.retry_local_ai_correction(run_id))

    @app.get("/api/projects/{project_id}/character-creation/controller/active")
    def character_creation_controller_active(project_id: str) -> dict[str, Any]:
        return character_creation.controller_active_run(project_id)

    @app.get("/api/character-creation/runs/{run_id}/controller/progress")
    def character_creation_controller_progress(run_id: str) -> dict[str, Any]:
        return character_creation.controller_walk_progress(run_id)

    @app.post("/api/character-creation/runs/{run_id}/controller/continue")
    def character_creation_controller_continue(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.continue_controller_walk(run_id))

    @app.post("/api/character-creation/runs/{run_id}/resolve-decision")
    def character_creation_resolve_decision(run_id: str, body: CharacterCreationDecisionResolutionRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.resolve_owner_decision(run_id, **body.model_dump()))

    @app.post("/api/character-creation/runs/{run_id}/manual-response-file")
    async def character_creation_manual_response_file(
        run_id: str, request: Request, filename: str = Query(min_length=1, max_length=240),
    ) -> dict[str, Any]:
        payload = await request.body()
        return _character_creation_api_view(character_creation.submit_manual_file(run_id, filename=filename, payload=payload))

    @app.post("/api/character-creation/runs/{run_id}/replace-response-file")
    async def character_creation_replace_response_file(
        run_id: str, request: Request, filename: str = Query(min_length=1, max_length=240),
    ) -> dict[str, Any]:
        payload = await request.body()
        return _character_creation_api_view(character_creation.replace_response_file(run_id, filename=filename, payload=payload))

    @app.post("/api/character-creation/runs/{run_id}/descriptive-fields")
    def character_creation_descriptive_fields(run_id: str, body: CharacterCreationDescriptiveFieldsRequest) -> dict[str, Any]:
        return _character_creation_api_view(
            character_creation.accept_descriptive_fields(
                run_id,
                name=body.name,
                title=body.title,
                concept=body.concept,
            )
        )

    @app.post("/api/character-creation/runs/{run_id}/finalize")
    def character_creation_finalize(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.finalize(run_id))

    @app.post("/api/character-creation/runs/{run_id}/auto-finalize-opt-in")
    def character_creation_auto_finalize_opt_in(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.create_auto_finalize_opt_in(run_id))

    @app.post("/api/character-creation/runs/{run_id}/revise")
    def character_creation_revise(run_id: str, body: CharacterCreationReviseRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.revise(run_id, owner_notes=body.owner_notes))

    @app.post("/api/character-creation/runs/{run_id}/edit-brief-create-new-request")
    def character_creation_edit_brief_create_new_request(run_id: str, body: CharacterCreationEditBriefSubmitRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.edit_brief_create_new_request(run_id, edit_id=body.edit_id))

    @app.post("/api/character-creation/runs/{run_id}/edit-brief/prepare")
    def character_creation_edit_brief_prepare(run_id: str, body: CharacterCreationEditBriefPrepareRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.prepare_edit_brief(run_id, **body.model_dump()))

    @app.post("/api/character-creation/runs/{run_id}/cancel")
    def character_creation_cancel(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.cancel(run_id))

    @app.get("/api/ai-provider")
    def ai_provider_status() -> dict[str, Any]:
        return ai_provider.status()

    @app.get("/api/local-ai/status")
    def local_ai_status() -> dict[str, Any]:
        return ai_provider.local_ai_status()

    @app.post("/api/local-ai/detect")
    def local_ai_detect(body: LocalAIDetectRequest) -> dict[str, Any]:
        return ai_provider.detect_local_ai(ports=body.ports)

    @app.post("/api/local-ai/select")
    def local_ai_select(body: LocalAISelectRequest) -> dict[str, Any]:
        return ai_provider.select_local_ai(
            endpoint=body.endpoint,
            model=body.model,
            provider_id=body.provider_id,
        )

    @app.post("/api/local-ai/managed/select")
    def local_ai_managed_select(body: LocalAIManagedSelectRequest) -> dict[str, Any]:
        return ai_provider.select_managed_local_ai(model=body.model)

    @app.post("/api/local-ai/managed/prepare")
    def local_ai_managed_prepare(body: LocalAIPrepareRequest) -> dict[str, Any]:
        return ai_provider.prepare_managed_local_ai(model=body.model)

    @app.post("/api/ai-provider/configure")
    def ai_provider_configure(body: AIProviderConfigureRequest) -> dict[str, Any]:
        return ai_provider.configure(**body.model_dump())

    @app.post("/api/ai-provider/key")
    def ai_provider_key_set(body: AIProviderKeyRequest) -> dict[str, Any]:
        return ai_provider.set_api_key(body.api_key)

    @app.delete("/api/ai-provider/key")
    def ai_provider_key_delete() -> dict[str, Any]:
        return ai_provider.delete_api_key()

    @app.post("/api/ai-provider/test")
    def ai_provider_test_connection() -> dict[str, Any]:
        return ai_provider.test_connection()

    @app.post("/api/stage1/prompts/{prompt_id}/ai-provider/run")
    def ai_provider_stage1_run(prompt_id: str, body: AIProviderRunRequest) -> dict[str, Any]:
        return ai_provider.run_stage1(prompt_id, idempotency_key=body.idempotency_key)

    @app.get("/api/ai-provider/runs/{run_id}")
    def ai_provider_run_get(run_id: str) -> dict[str, Any]:
        return ai_provider.get_run(run_id)

    # ---- Agent bridge: hand one authoring request to a harness-held agent ----
    # The agent receives exactly the OpenAI-compatible body the app would have
    # POSTed (system + user messages + response schema) and returns one JSON
    # object that the surface below validates through the same schema gate a
    # configured provider answer goes through.
    @app.get("/api/ai-provider/agent/status")
    def ai_provider_agent_status() -> dict[str, Any]:
        return ai_provider.agent_bridge_status()

    @app.get("/api/ai-provider/agent/requests")
    def ai_provider_agent_requests(
        state: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return ai_provider.agent_bridge.list_requests(state=state, limit=limit)

    @app.get("/api/ai-provider/agent/requests/{request_id}")
    def ai_provider_agent_request_get(request_id: str) -> dict[str, Any]:
        return ai_provider.agent_bridge.get(request_id)

    @app.post("/api/ai-provider/agent/requests/{request_id}/claim")
    def ai_provider_agent_request_claim(
        request_id: str,
        body: AIAgentClaimRequest,
    ) -> dict[str, Any]:
        return ai_provider.agent_bridge.claim(
            request_id,
            agent_id=body.agent_id,
            lease_seconds=body.lease_seconds,
        )

    @app.post("/api/ai-provider/agent/requests/{request_id}/answer")
    def ai_provider_agent_request_answer(
        request_id: str,
        body: AIAgentAnswerRequest,
    ) -> dict[str, Any]:
        return ai_provider.agent_bridge.answer(
            request_id,
            agent_id=body.agent_id,
            agent_model=body.agent_model,
            request_sha256=body.request_sha256,
            response_text=body.response_text,
            validator=lambda parsed, _request_id=request_id: ai_provider.agent_request_schema_errors(
                _request_id, parsed
            ),
        )

    @app.post("/api/ai-provider/agent/requests/{request_id}/reject")
    def ai_provider_agent_request_reject(
        request_id: str,
        body: AIAgentRejectRequest,
    ) -> dict[str, Any]:
        return ai_provider.agent_bridge.reject(
            request_id,
            agent_id=body.agent_id,
            reason=body.reason,
        )

    @app.get("/api/projects/{project_id}/ai-provider/runs")
    def ai_provider_runs_list(project_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return {"project_id": project_id, "runs": ai_provider.list_runs(project_id, limit=limit)}

    @app.get("/api/projects/{project_id}/projection/status")
    def projection_status(project_id: str) -> dict[str, Any]:
        return projections.status(project_id)

    @app.post("/api/projects/{project_id}/projection/build")
    def projection_build(project_id: str, body: ProjectionBuildRequest) -> dict[str, Any]:
        result = projections.build(project_id, force=body.force)
        result["builder_lifecycle"] = projects.mark_builder_completed(project_id, source="projection_build_completed")
        return result

    @app.get("/api/projects/{project_id}/projection/artifacts/{artifact_name}")
    def projection_artifact(project_id: str, artifact_name: str):
        path = projections.artifact(project_id, artifact_name)
        return FileResponse(path, media_type=ARTIFACT_MEDIA[artifact_name], filename=artifact_name)

    @app.post("/api/projects/{project_id}/migration/preview")
    def migration_preview(project_id: str, body: MigrationPreviewRequest) -> dict[str, Any]:
        return packs.preview_migration(project_id, body.pack_id, body.target_version)

    @app.post("/api/projects/{project_id}/export")
    def project_export(project_id: str, body: ExportRequest) -> dict[str, Any]:
        return projects.export_project(project_id, body.filename)

    @app.post("/api/projects/import")
    def project_import(body: PackageRequest) -> dict[str, Any]:
        return projects.import_project(resolve_inside(settings.inbox_dir, body.package_name))

    async def stage_portable_character_upload(request: Request) -> tuple[Path, dict[str, Any]]:
        original = request.headers.get("x-tianxia-filename", "character.zip")
        browser_name = Path(str(original).replace("\\", "/")).name
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", browser_name).strip("._-")[:96] or "character.zip"
        if not browser_name.lower().endswith(".zip") or not safe_stem.lower().endswith(".zip"):
            raise FoundryError("PORTABLE_CHARACTER_UPLOAD_EXTENSION", "Choose a .zip portable Character package.")
        declared_length = request.headers.get("content-length")
        if declared_length:
            try:
                if int(declared_length) > MAX_ARCHIVE_BYTES:
                    raise FoundryError("PORTABLE_CHARACTER_UPLOAD_TOO_LARGE", "The selected ZIP exceeds the 128 MB upload limit.")
            except ValueError:
                raise FoundryError("PORTABLE_CHARACTER_UPLOAD_LENGTH_INVALID", "The upload size header was invalid.")
        staging_root = settings.data_dir / "upload_staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        target = staging_root / f"{secrets.token_hex(16)}-{safe_stem}"
        total = 0
        try:
            with target.open("xb") as handle:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise FoundryError("PORTABLE_CHARACTER_UPLOAD_TOO_LARGE", "The selected ZIP exceeds the 128 MB upload limit.")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if total == 0:
                raise FoundryError("PORTABLE_CHARACTER_UPLOAD_EMPTY", "The selected ZIP was empty.")
            audit = portable_characters.audit(target)
            return target, audit
        except Exception:
            target.unlink(missing_ok=True)
            raise

    @app.post("/api/characters/portable-preview")
    async def portable_character_preview_upload(request: Request) -> dict[str, Any]:
        target, audit = await stage_portable_character_upload(request)
        try:
            result = portable_characters.preview_for_factory(target, audit=audit)
            result["package"]["filename"] = Path(request.headers.get("x-tianxia-filename", "character.zip")).name
            return result
        finally:
            target.unlink(missing_ok=True)

    @app.post("/api/characters/portable-import-upload")
    async def portable_character_import_upload(request: Request) -> dict[str, Any]:
        target, _audit = await stage_portable_character_upload(request)
        try:
            result = portable_characters.import_into_factory(target)
            result["owner_message"] = (
                "Already installed — identical package" if result.get("status") == "ALREADY_INSTALLED_IDENTICAL"
                else "Character imported successfully."
            )
            return result
        finally:
            target.unlink(missing_ok=True)

    @app.post("/api/characters/import-portable")
    def portable_character_import(body: PackageRequest) -> dict[str, Any]:
        return portable_characters.import_into_factory(resolve_inside(settings.inbox_dir, body.package_name))

    @app.get("/api/contracts")
    def service_contracts() -> dict[str, Any]:
        return json.loads((settings.root_dir / "contracts/Service_API_Contracts.json").read_text(encoding="utf-8"))

    # The opening gameplay slice is namespaced so the existing Character
    # Foundry root, session and creation routes remain unchanged.
    from opening_ui.integration import register_opening_routes

    # ------------------------------------------------------------------
    # Tabletop (owner 2026-09-25): a local MapTool/Roll20-style table for
    # human-played combat; the engine still decides every rule.
    # ------------------------------------------------------------------
    from combat.tabletop import TabletopError, battlefield_as_map
    from combat.tabletop_service import TabletopService

    tabletop = TabletopService(combat, settings.data_dir)
    tabletop.prewarm_menus = True
    from agent_seats import SeatRunner
    from agent_seats.providers import ProviderRegistry
    # Optional external registry keeps account-specific commands outside source.
    seats = SeatRunner(tabletop, registry=ProviderRegistry(os.environ.get("FACTORY_SEAT_PROVIDERS")))
    app.state.agent_seats = seats
    tabletop.canonical_catalog = canonical_catalog  # the Advance and Forge panels check the rules (owner 2026-09-27)

    # Per-deploy stamps on table pages and modules, and the build id every response carries (see app/static_build.py).
    static_build = StaticBuild(settings.root_dir)

    @app.middleware("http")
    async def tabletop_revalidate(request: Request, call_next):
        # Every HTTP request for a match counts; internal service calls do not pass through this boundary.
        parts = request.url.path.split("/")
        if len(parts) >= 5 and parts[1:4] == ["api", "tabletop", "matches"]:
            tabletop.record_request(parts[4])
        # The table's ES modules are served stamped with this deploy's build id, and browsers revalidate them
        # (a 304 when unchanged) so an update never runs half-stale code.
        served = static_build.response_for(request.url.path)
        if served is not None:
            return served
        response = await call_next(request)
        response.headers[BUILD_HEADER] = static_build.build
        if request.url.path.startswith("/static/tabletop/") or request.url.path.startswith("/tabletop") or request.url.path == "/play":
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    def _tabletop(call):
        try:
            return call()
        except TabletopError as exc:
            raise FoundryError(exc.code, str(exc), status_code=exc.status_code) from exc

    @app.get("/tabletop", include_in_schema=False)
    def tabletop_page() -> Response:
        return static_build.response_for("/tabletop")  # the middleware serves it first; this keeps the route honest

    @app.get("/play", include_in_schema=False)
    def mobile_play_page() -> FileResponse:
        # Independent player surface; all fight operations use the existing table API.
        return FileResponse(settings.root_dir / "static" / "play" / "play.html",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/tabletop/sheet", include_in_schema=False)
    def tabletop_sheet_page() -> FileResponse:
        return FileResponse(settings.root_dir / "static" / "tabletop" / "sheet.html")

    @app.get("/tabletop/maps", include_in_schema=False)
    def tabletop_map_editor_page() -> FileResponse:
        return FileResponse(settings.root_dir / "static" / "tabletop" / "mapeditor.html")

    @app.get("/api/tabletop/activity")
    def tabletop_activity() -> list[dict[str, Any]]:
        return _tabletop(tabletop.activity)

    @app.get("/api/tabletop/matches/{match_id}/state")
    def tabletop_state(match_id: str, fog: bool = Query(False), fog_view: str | None = Query(None),
                       fog_actor_ids: list[str] = Query(default=[]), compact: bool = Query(False),
                       remembered_ids: list[str] | None = Query(default=None)) -> dict[str, Any]:
        from combat.table_text_pool import pack
        # Bounded: at most 400 remembered ids, each a short creature id.
        ids = None if remembered_ids is None else tuple(i[:128] for i in remembered_ids[:400])
        def read():
            state = tabletop.state(match_id, fog=fog, fog_view=fog_view,
                                   fog_actor_ids=tuple(fog_actor_ids), compact_moves=compact, remembered_ids=ids, lazy=compact)
            return pack(state) if compact else state
        return _tabletop(read)

    @app.get('/api/tabletop/matches/{match_id}/action-options')
    def tabletop_action_options(match_id: str, source: str, decision_id: str, state_version: int) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.expand_action(match_id, source, decision_id, state_version))

    @app.get("/api/tabletop/providers")
    def tabletop_seat_providers() -> dict[str, Any]:
        return {"providers": seats.registry.public()}

    @app.post("/api/tabletop/matches/{match_id}/seat")
    def tabletop_set_seat(match_id: str, body: TabletopSeatRequest) -> dict[str, Any]:
        return _tabletop(lambda: seats.set_seat(match_id, body.actor_id, body.control, body.provider_id, body.style))

    @app.get("/api/tabletop/matches/{match_id}/seat-status")
    def tabletop_seat_status(match_id: str) -> dict[str, Any]:
        return _tabletop(lambda: seats.status(match_id))

    @app.post("/api/tabletop/matches/{match_id}/playback")
    def tabletop_playback(match_id: str, body: TabletopPlaybackRequest) -> dict[str, Any]:
        return _tabletop(lambda: seats.set_paused(match_id, body.paused))

    @app.get("/api/tabletop/matches/{match_id}/seat-decisions")
    def tabletop_seat_decisions(match_id: str, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
        return _tabletop(lambda: {"decisions": seats.decisions(match_id, limit)})

    @app.get("/api/tabletop/matches/{match_id}/events")
    def tabletop_events(match_id: str, after: int = Query(0, ge=0)) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.events(match_id, after))

    @app.get("/api/tabletop/matches/{match_id}/summary")
    def tabletop_summary(match_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.summary(match_id))

    @app.post("/api/tabletop/matches/{match_id}/settings")
    def tabletop_settings(match_id: str, body: TabletopSettingsRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_settings(match_id, body.actor_id, body.sources, body.request_id))

    @app.post("/api/tabletop/characters/{project_id}/settings")
    def tabletop_project_settings(project_id: str, body: TabletopSettingsRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_project_settings(project_id, body.sources))

    @app.post("/api/tabletop/matches/{match_id}/composition/preview")
    def tabletop_composition(match_id: str, body: TabletopCompositionRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.preview_composition(match_id, body.model_dump()))

    @app.post("/api/tabletop/matches/{match_id}/act")
    def tabletop_act(match_id: str, body: TabletopActRequest) -> dict[str, Any]:
        if body.composition is not None:
            return _tabletop(lambda: tabletop.commit_composition(match_id, body.composition.model_dump(),
                body.candidate_id, body.after, body.reactions, body.option_ids))
        read = body.menu_read.model_dump() if body.menu_read is not None else None
        def run():
            result = tabletop.act(match_id, body.candidate_id, body.decision_id, body.state_version, body.after, body.reactions,
                                  option_ids=body.option_ids, defer_menu=True, menu_read=read)
            state = result.get("state") if isinstance(result, dict) else None
            if read and read["compact"] and isinstance(state, dict) and state.get("menu"):
                # Encoded like the compact state read; the browser expands the response's table_texts.
                from combat.table_text_pool import pack
                packed = dict(pack(state))
                texts = packed.pop("table_texts", None)
                result = {**result, "state": packed, **({"table_texts": texts} if texts else {})}
            return result
        return _tabletop(run)

    @app.post('/api/tabletop/matches/{match_id}/placement/cancel')
    def tabletop_cancel_placement(match_id: str, body: TabletopActRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.cancel_placement(match_id, body.candidate_id,
                                                          body.decision_id, body.state_version,
                                                          body.pending_id))
    @app.post("/api/tabletop/matches/{match_id}/prepare")
    def tabletop_prepare(match_id: str, body: TabletopActRequest) -> dict[str, Any]:
        if body.composition is not None:
            return _tabletop(lambda: tabletop.prepare_composition(match_id, body.composition.model_dump(),
                body.candidate_id, body.option_ids, after=body.after, reactions=body.reactions))
        return _tabletop(lambda: tabletop.act(match_id, body.candidate_id, body.decision_id,
            body.state_version, body.after, body.reactions, option_ids=body.option_ids, prepare_only=True))

    @app.post('/api/tabletop/matches/{match_id}/movement-destination/preview')
    def tabletop_destination_preview(match_id: str, body: TabletopDestinationRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.preview_destination(match_id, body.decision_id, body.state_version,
            body.actor_id, body.destination, body.movement_mode))

    @app.post('/api/tabletop/matches/{match_id}/movement-path/preview')
    def tabletop_route_preview(match_id: str, body: TabletopRoutePreviewRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.preview_move_path(match_id, body.decision_id, body.state_version,
            body.actor_id, body.waypoints, body.movement_mode))

    @app.post('/api/tabletop/matches/{match_id}/movement-path/commit')
    def tabletop_route_commit(match_id: str, body: TabletopRouteCommitRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.commit_move_path(match_id, body.candidate_id, body.decision_id,
            body.state_version, body.actor_id, body.waypoints, body.after, body.movement_mode, body.reactions,
            defer_menu=True))

    @app.delete("/api/tabletop/matches/{match_id}")
    def tabletop_delete_match(match_id: str) -> dict[str, Any]:
        _tabletop(lambda: tabletop.delete_match(match_id))
        return {"deleted": match_id}

    @app.post("/api/tabletop/matches/{match_id}/automatic-run")
    def tabletop_automatic_run(match_id: str) -> dict[str, Any]:
        return _tabletop(lambda: seats.start(match_id))

    @app.post("/api/tabletop/matches/{match_id}/auto-step")
    def tabletop_auto_step(match_id: str, body: TabletopStepRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.auto_step(match_id, body.after, body.reactions, body.decision_id,
                                                   body.state_version, defer_menu=True))

    @app.get("/api/tabletop/team-presets")
    def tabletop_team_presets_list() -> dict[str, Any]:
        from combat.tabletop import TeamPresetStore

        return {"presets": TeamPresetStore(combat.userdata_root / "team_presets").list()}

    @app.post("/api/tabletop/team-presets")
    def tabletop_team_preset_save(body: TabletopTeamPresetRequest) -> dict[str, Any]:
        from combat.tabletop import TeamPresetStore

        return _tabletop(lambda: TeamPresetStore(combat.userdata_root / "team_presets").save(body.preset))

    @app.delete("/api/tabletop/team-presets/{name}")
    def tabletop_team_preset_delete(name: str) -> dict[str, Any]:
        from combat.tabletop import TeamPresetStore

        _tabletop(lambda: TeamPresetStore(combat.userdata_root / "team_presets").delete(name))
        return {"deleted": name}

    @app.get("/api/tabletop/saved-teams")
    def tabletop_saved_teams_list() -> dict[str, Any]:
        from combat.tabletop import SingleTeamPresetStore

        return {"teams": SingleTeamPresetStore(combat.userdata_root / "team_presets").list()}

    @app.post("/api/tabletop/saved-teams")
    def tabletop_saved_team_save(body: TabletopTeamPresetRequest) -> dict[str, Any]:
        from combat.tabletop import SingleTeamPresetStore

        return _tabletop(lambda: SingleTeamPresetStore(combat.userdata_root / "team_presets").save(body.preset))

    @app.delete("/api/tabletop/saved-teams/{name:path}")
    def tabletop_saved_team_delete(name: str) -> dict[str, Any]:
        from combat.tabletop import SingleTeamPresetStore

        _tabletop(lambda: SingleTeamPresetStore(combat.userdata_root / "team_presets").delete(name))
        return {"deleted": name}

    @app.get("/api/tabletop/maps")
    def tabletop_maps_list() -> dict[str, Any]:
        from combat.tabletop import arena_picker_name
        from combat.object_rules import editor_defaults

        maps = combat.tabletop_maps.list()
        builtin = [row for row in maps if row["builtin"]]
        builtin += [{"map_id": None, "arena_id": arena_id, "display_name": arena_picker_name(arena),
                    "width_squares": arena["width_squares"], "height_squares": arena["height_squares"], "builtin": True}
                   for arena_id, arena in combat.factory_arenas().items() if not arena_id.startswith("battlefield:map.")]
        return {"maps": [row for row in maps if not row["builtin"]], "builtin": builtin,
                "default_arena_id": DEFAULT_FACTORY_ARENA, "object_defaults": editor_defaults()}

    @app.get("/api/tabletop/maps/{map_id}")
    def tabletop_map_get(map_id: str) -> dict[str, Any]:
        return _tabletop(lambda: combat.tabletop_maps.get(map_id))

    @app.get("/api/tabletop/builtin-maps/{arena_id:path}")
    def tabletop_builtin_map(arena_id: str) -> dict[str, Any]:
        from combat.tabletop import MAP_PREFIX

        if arena_id.startswith(MAP_PREFIX):
            return _tabletop(lambda: combat.tabletop_maps.get(arena_id[len(MAP_PREFIX):]))
        arena = combat.factory_arenas().get(arena_id)
        if arena is None:
            raise FoundryError("MAP_NOT_FOUND", "Unknown arena.", status_code=404)
        return battlefield_as_map(arena)

    @app.post("/api/tabletop/maps")
    def tabletop_map_save(body: TabletopMapRequest) -> dict[str, Any]:
        return _tabletop(lambda: combat.tabletop_maps.save(body.map))

    @app.delete("/api/tabletop/maps/{map_id}")
    def tabletop_map_delete(map_id: str) -> dict[str, Any]:
        _tabletop(lambda: combat.tabletop_maps.delete(map_id))
        return {"deleted": map_id}

    @app.post("/api/tabletop/map-assets")
    async def tabletop_map_asset_upload(request: Request) -> dict[str, Any]:
        data = await request.body()
        name = _tabletop(lambda: combat.tabletop_maps.save_asset(data, request.headers.get("content-type", "")))
        return {"asset": name, "url": f"/api/tabletop/map-assets/{name}"}

    @app.get("/api/tabletop/map-assets/{name}")
    def tabletop_map_asset(name: str) -> FileResponse:
        path = _tabletop(lambda: combat.tabletop_maps.asset_path(name))
        media = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
        return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/names/generate")
    def generate_names(seed: str | None = None, dao: str | None = None, style: str | None = None, lean: str | None = None,
                       themes: str | None = None, count: int = 6) -> dict[str, Any]:
        """Seeded ancient-Chinese names by Dao type (owner 2026-09-27; factory_authoring/names.py). No seed draws a new
        one; the same seed and options always give the same names."""
        import secrets as _secrets

        from factory_authoring import names as _names

        chosen = (seed or "").strip()[:64] or "N-" + _secrets.token_hex(3).upper()
        rows = _names.suggestions(chosen, max(1, min(int(count), 12)), dao=dao, style=style, lean=lean,
                                  themes=_names.themes_for((themes or "").split(",")))
        return {"schema": "TianxiaFoundry.NameSuggestions.v1", "seed": chosen, "dao": _names.dao_key(dao), "names": rows,
                "daos": [{"key": key, "image": _names.data()["trigrams"][key]["image"]} for key in _names.TRIGRAMS],
                "styles": list(_names.data()["styles"])}

    @app.get("/api/tabletop/characters/{project_id}/sheet")
    def tabletop_character_sheet(project_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.sheet(project_id))

    @app.post("/api/tabletop/characters/{project_id}/buttons")
    def tabletop_character_buttons(project_id: str, body: TabletopButtonsRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_buttons(project_id, body.model_dump(mode="json")))

    @app.post("/api/tabletop/characters/{project_id}/reactions")
    def tabletop_character_reactions(project_id: str, body: TabletopReactionsRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_reactions(project_id, body.model_dump(mode="json")))

    @app.post("/api/tabletop/characters/{project_id}/spheres")
    def tabletop_character_spheres(project_id: str, body: TabletopSpheresRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_granted_spheres(project_id, body.granted_spheres))

    @app.get("/api/tabletop/characters/{project_id}/advancement")
    def tabletop_advancement(project_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.advancement(project_id, primary_method_id=_recorded_method(project_id)))

    @app.post("/api/tabletop/characters/{project_id}/learning-preview")
    def tabletop_learning_preview(project_id: str, body: TabletopAdvanceRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.learning_preview(project_id, body.record_id, body.learning_choices))

    @app.post("/api/tabletop/characters/{project_id}/advancement")
    def tabletop_advance(project_id: str, body: TabletopAdvanceRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.add_advancement(project_id, body.kind, body.record_id, gm=body.gm, source=body.source, learning_choices=body.learning_choices))

    @app.post("/api/tabletop/characters/{project_id}/advancement/method")
    def tabletop_method(project_id: str, body: TabletopMethodRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.change_method(project_id, body.model_dump(), primary_method_id=_recorded_method(project_id)))

    @app.post("/api/tabletop/characters/{project_id}/advancement/method/undo")
    def tabletop_method_undo(project_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.undo_method(project_id, primary_method_id=_recorded_method(project_id)))

    @app.post("/api/tabletop/characters/{project_id}/advancement/level")
    def tabletop_level(project_id: str, body: TabletopLevelRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.level_up(project_id, body.model_dump(), primary_method_id=_recorded_method(project_id)))

    def _recorded_method(project_id: str) -> str:
        # Grow overlays take precedence; the creation authority is only the initial fallback.
        from combat.table_method import primary_id
        sheet = combat._factory_owner_sheet(project_id)
        recorded = primary_id(sheet)
        if (sheet.get("method") or {}).get("table_acquired"):
            return recorded
        authority = getattr(app.state, "non_sphere_authority", None)
        if authority is None:
            return recorded
        try:
            state = authority.get_state(project_id, create_legacy_shell=False) or {}
        except FoundryError:
            # Portable installs may have no local creation project.
            return recorded
        return str(state.get("primary_method_id") or recorded)

    @app.post("/api/tabletop/characters/{project_id}/advancement/level/undo")
    def tabletop_level_undo(project_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.undo_level(project_id, primary_method_id=_recorded_method(project_id)))

    @app.post("/api/tabletop/characters/{project_id}/advancement/ability")
    def tabletop_advance_ability(project_id: str, body: TabletopAbilityRequest) -> dict[str, Any]:
        entry = {"type": "ability", "reason": body.reason, "changes": body.changes, "cl": body.cl, "note": body.note}
        return _tabletop(lambda: tabletop.add_ability(project_id, entry, gm=body.gm, primary_method_id=_recorded_method(project_id)))

    @app.post("/api/tabletop/characters/{project_id}/advancement/insight")
    def tabletop_advance_insight(project_id: str, body: TabletopInsightRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.add_insight(project_id, body.record_id, note=body.note, choice=body.choice, gm=body.gm))

    @app.post("/api/tabletop/characters/{project_id}/advancement/immortal-art")
    def tabletop_advance_immortal_art(project_id: str, body: TabletopImmortalArtRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.immortal_art(project_id, body.design.model_dump(), note=body.note,
                                                      proof=body.proof.model_dump() if body.proof else None, save=body.save))

    @app.post("/api/tabletop/characters/{project_id}/advancement/remove")
    def tabletop_advance_remove(project_id: str, body: TabletopAdvanceRemoveRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.remove_advancement(project_id, body.kind, body.record_id))

    @app.post("/api/tabletop/characters/{project_id}/forge")
    def tabletop_forge(project_id: str, body: TabletopForgeRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.forge(project_id, body.design.model_dump(), gm=body.gm, save=body.save, source=body.source))

    @app.get("/api/tabletop/summon-tokens/{kind}/{name}")
    def tabletop_summon_token(kind: str, name: str) -> FileResponse:
        path = _tabletop(lambda: tabletop.summon_token_path(kind, name))
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/tabletop/terrains")
    def tabletop_terrains() -> dict[str, Any]:
        """The named terrains a map may be painted with, and what each does in a fight (owner 2026-09-28, the map
        editor's Material brush; combat/rules/terrain.json). Also the ground catalog (combat/ground_text.py), so the
        editor's hover card describes a square in the same words the table does instead of guessing there.

        The wording is that same catalog's: ``terrain_reading`` is the one place a ground mechanic is
        described (OC13), so the brush can no longer drop the enter/start save the table's card keeps,
        nor assemble its own phrases from the rule's field names -- which is also where the latent
        ``rule["obscured"] + "ly obscured"`` misspelling of the heavy one lived."""
        from combat.ground_text import catalog as ground_catalog, terrain_reading
        from combat.zones import terrain_rules

        rows = []
        for name, rule in sorted((terrain_rules().get("terrains") or {}).items()):
            reading = terrain_reading(name, rule if isinstance(rule, dict) else {})
            rows.append({"name": name, "label": name.title(), "material": rule.get("material"), "color": rule.get("color"),
                         "difficult": rule.get("difficult"), "obscured": rule.get("obscured"), "move_through": rule.get("move_through"),
                         "does": " ".join(reading["lines"]), "reading": reading["lines"]})
        return {"schema": "TianxiaTabletopTerrains.v1", "terrains": rows, "ground": ground_catalog()}

    @app.get("/api/tabletop/conditions")
    def tabletop_conditions() -> dict[str, Any]:
        """What each condition does, for the table's hover (owner 2026-09-27; combat/condition_text.py)."""
        from combat.condition_text import all_conditions

        return {"schema": "TianxiaTabletopConditions.v1", "conditions": all_conditions()}

    @app.get("/api/tabletop/characters/{project_id}/token.png")
    def tabletop_token_image(project_id: str) -> FileResponse:
        path = _tabletop(lambda: tabletop.token_path(project_id))
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/api/tabletop/characters/{project_id}/token")
    def tabletop_token_save(project_id: str, body: TabletopTokenRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_token(project_id, body.data_base64, body.circle))

    @app.delete("/api/tabletop/characters/{project_id}/token")
    def tabletop_token_delete(project_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.delete_token(project_id))

    @app.post("/api/tabletop/characters/{project_id}/token/generate")
    def tabletop_token_generate(project_id: str, body: TabletopTokenGenerateRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.generate_token(project_id, body.look, body.seed, body.framing))

    @app.get("/api/tabletop/characters/{project_id}/picture.png")
    def tabletop_picture_image(project_id: str) -> FileResponse:
        path = _tabletop(lambda: tabletop.picture_path(project_id))
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/api/tabletop/characters/{project_id}/picture")
    def tabletop_picture_save(project_id: str, body: TabletopTokenRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_picture(project_id, body.data_base64))

    @app.delete("/api/tabletop/characters/{project_id}/picture")
    def tabletop_picture_delete(project_id: str) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.delete_picture(project_id))

    @app.post("/api/tabletop/characters/{project_id}/attunement")
    def tabletop_attunement(project_id: str, body: TabletopAttunementRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_attunement(project_id, body.attuned))

    @app.post("/api/tabletop/characters/{project_id}/equipment")
    def tabletop_equipment(project_id: str, body: TabletopEquipmentRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_left_behind(project_id, body.left_behind))

    @app.post("/api/tabletop/characters/{project_id}/name")
    def tabletop_character_name(project_id: str, body: TabletopNameRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_display_name(project_id, body.display_name))

    @app.post("/api/tabletop/characters/{project_id}/summons")
    def tabletop_character_summons(project_id: str, body: TabletopSummonsRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_summons(project_id, body.model_dump(mode="json")))

    @app.post("/api/tabletop/characters/{project_id}/powering")
    def tabletop_character_powering(project_id: str, body: TabletopPoweringRequest) -> dict[str, Any]:
        return _tabletop(lambda: tabletop.save_powering(project_id, body.model_dump(mode="json")))

    register_opening_routes(app, settings=settings, session_token=lambda: session_token)

    def _warm_list_caches() -> None:
        # Fill the per-project list caches once at startup so the first visit to the
        # builder or Character Sheets after a restart is not a multi-minute wait.
        for warm in (character_library, characters_list):
            try:
                warm()
            except Exception:  # noqa: BLE001 - a warm-up only; the request path reports real errors
                pass

    if os.environ.get("TIANXIA_WARM_LIST_CACHES") == "1":  # set by packaging/linux/run-factory.sh
        threading.Thread(target=_warm_list_caches, name="list-cache-warm", daemon=True).start()

    static_dir = settings.root_dir / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app
