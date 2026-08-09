from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core import (
    APP_STATUS,
    APP_VERSION,
    EXPECTED_GM_SCREEN_HASH,
    GM_SCREEN_VERSION,
    Database,
    FoundryError,
    Settings,
    canonical_json,
    resolve_inside,
    sha256_file,
    utcnow,
)
from app.models import (
    AIProviderConfigureRequest,
    AIProviderKeyRequest,
    AIProviderRunRequest,
    ApproveRequest,
    ConfigureVendorRequest,
    CreateProjectRequest,
    CharacterSheetCreateRequest,
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
    Stage2CommitRequest,
    CombatResourceInitializationRequest,
    CombatPreEncounterDraftPreviewRequest,
    CombatPreEncounterDraftDiscardRequest,
    CombatCreateMatchRequest,
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
    CharacterCreationDescriptiveFieldsRequest,
    CharacterCreationPreferenceRequest,
    CharacterCreationReviseRequest,
)
from catalog.service import CatalogService
from canonical_catalog import CanonicalCatalogAuthorityService
from character_builder.service import CharacterBuilderService
from character_sheet import CharacterSheetService
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from portable_character.service import MAX_ARCHIVE_BYTES
from factory_authoring import FactoryAuthoringWorkspaceService
from content_packs.service import ContentPackManager
from project_store.service import ProjectStore
from projector.service import ProjectionService, ARTIFACT_MEDIA
from vendor_adapter.service import FactoryAdapter
from contracts.registry import SchemaRegistry
from stage1.service import Stage1ClipboardService
from stage2.service import PROPOSAL_V2, Stage2AdvancementService
from security.local_identity import BoundPrincipalProvider, PrincipalProvider, ProcessPrincipalProvider
from ai_provider.service import AIProviderService
from character_creation import CharacterCreationExecutionService
from character_creation.production_release import CharacterProductionReleaseAdapter
from foundation_adapter import (
    FoundationHandoffError,
    build_foundation_pack_plan,
    load_foundation_handoff,
    load_pinned_core_foundation_authorities,
    write_deterministic_foundation_pack,
)
from combat.gate5_service import CombatService, CombatServiceError
from combat.pre_encounter import CombatantLibraryService
from product_bootstrap import NATIVE_WINDOWS_STATUS, ProductReadinessService
from non_sphere_authority import NonSphereAuthorityService


_LOOPBACK_ORIGIN_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}


def _choice_snapshot_api_binding(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    value = snapshot or {}
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


def _character_creation_api_view(run: dict[str, Any]) -> dict[str, Any]:
    """Bound the owner UI payload without weakening the stored canonical run.

    Complete scratch receipts and the exact typed choice snapshot remain in the
    server-owned run. The browser receives stable identities and compact receipts;
    the full snapshot has a dedicated review/download endpoint.
    """
    result = {
        key: value
        for key, value in run.items()
        if key not in {"request", "dry_run", "outputs"}
    }
    request = dict(run.get("request") or {})
    request["typed_choice_snapshot"] = _choice_snapshot_api_binding(
        request.get("typed_choice_snapshot")
    )
    result["request"] = request
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
        "gm_consumer": {
            key: (outputs.get("gm_consumer") or {}).get(key)
            for key in (
                "status",
                "verdict",
                "consumer_status",
                "source_consumer_verified",
                "save_reload_semantic_equivalence",
                "all_tabs_nonempty",
                "exact_tab_order",
                "local_save_package_count",
                "selected_id",
                "semantic_hash",
                "console_or_page_errors",
                "browser_harness",
            )
        } if outputs.get("gm_consumer") else None,
        "portable_character": {
            "package_sha256": portable.get("package_sha256"),
            "clean_import": portable.get("clean_import"),
            "gm_export": portable.get("gm_export"),
            "release_identity": portable.get("release_identity"),
        } if portable else None,
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
        "combat": outputs.get("combat"),
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


def create_app(
    settings: Settings | None = None,
    *,
    ai_transport: Any = None,
    ai_secret_store: Any = None,
    principal_provider: PrincipalProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings)
    db.migrate()
    catalog = CatalogService(db)
    non_sphere_authority = NonSphereAuthorityService(db)
    canonical_catalog = CanonicalCatalogAuthorityService(
        settings.root_dir, evidence_resolver=non_sphere_authority.resolve_evidence,
    )
    source_principal_provider = principal_provider or ProcessPrincipalProvider()
    principal = source_principal_provider.current_principal()
    principal_provider = BoundPrincipalProvider(principal)
    packs = ContentPackManager(db, principal_provider=principal_provider)
    projects = ProjectStore(db)
    vendor = FactoryAdapter(db)
    projections = ProjectionService(db)
    schema_registry = SchemaRegistry(settings.root_dir)
    stage1 = Stage1ClipboardService(db)
    character_builder = CharacterBuilderService(db)
    character_sheets = CharacterSheetService(db)
    gm_exports = GMCharacterExportService(db)
    portable_characters = PortableCharacterPackageService(db)
    factory_authoring = FactoryAuthoringWorkspaceService(db)
    ai_provider = AIProviderService(db, transport=ai_transport, secret_store=ai_secret_store)
    stage2 = Stage2AdvancementService(db, principal_provider=principal_provider)
    character_creation = CharacterCreationExecutionService(
        db, stage1=stage1, provider=ai_provider, project_store=projects, stage2=stage2,
        character_sheets=character_sheets, gm_exports=gm_exports,
        portable_characters=portable_characters, factory_authoring=factory_authoring,
        projections=projections, production_release=CharacterProductionReleaseAdapter(db), owner_principal=principal.principal_id,
    )
    combat = CombatService(settings.root_dir, settings.data_dir, ai_provider=ai_provider)
    combatant_library = CombatantLibraryService(settings.root_dir, settings.data_dir)
    product_readiness = ProductReadinessService(db)
    session_token = secrets.token_urlsafe(32)
    staged_owner_artifacts: dict[str, dict[str, Any]] = {}

    app = FastAPI(
        title="Tianxia Character Foundry",
        version=APP_VERSION,
        description="Local Tianxia Factory with deterministic character workflows and the Gate 5 persistent hybrid-combat vertical slice.",
    )
    app.state.settings = settings
    app.state.db = db
    app.state.catalog = catalog
    app.state.canonical_catalog = canonical_catalog
    app.state.packs = packs
    app.state.projects = projects
    app.state.vendor = vendor
    app.state.projections = projections
    app.state.schema_registry = schema_registry
    app.state.stage1 = stage1
    app.state.character_builder = character_builder
    app.state.character_sheets = character_sheets
    app.state.gm_exports = gm_exports
    app.state.portable_characters = portable_characters
    app.state.factory_authoring = factory_authoring
    app.state.ai_provider = ai_provider
    app.state.character_creation = character_creation
    app.state.stage2 = stage2
    app.state.combat = combat
    app.state.combatant_library = combatant_library
    app.state.product_readiness = product_readiness
    app.state.non_sphere_authority = non_sphere_authority
    app.state.session_token = session_token
    app.state.principal = principal
    app.state.principal_provider = principal_provider

    app.state.character_builder_startup_cleanup = None
    app.state.character_builder_shutdown_cleanup = None

    @app.on_event("startup")
    def cleanup_abandoned_temporary_characters() -> None:
        app.state.character_builder_startup_cleanup = projects.cleanup_temporary_projects(
            reason="startup_after_interrupted_or_abandoned_builder"
        )

    @app.on_event("shutdown")
    def cleanup_unfinished_temporary_characters() -> None:
        app.state.character_builder_shutdown_cleanup = projects.cleanup_temporary_projects(
            reason="normal_factory_shutdown"
        )

    @app.middleware("http")
    async def loopback_security(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        allowed_hosts = {"127.0.0.1", "localhost", "[::1]", "testserver"}
        if host not in allowed_hosts:
            return JSONResponse(status_code=403, content={"error": {"code": "NON_LOOPBACK_HOST", "message": "Only loopback requests are accepted.", "details": {"host": host}}})
        origin = request.headers.get("origin")
        if origin and not _is_allowed_loopback_origin(origin):
            return JSONResponse(status_code=403, content={"error": {"code": "ORIGIN_REJECTED", "message": "Request origin is not permitted.", "details": {"origin": origin}}})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = request.headers.get("x-foundry-token")
            if token != session_token:
                return JSONResponse(status_code=403, content={"error": {"code": "CSRF_TOKEN_REQUIRED", "message": "A valid local session token is required for mutations.", "details": None}})
        return await call_next(request)

    @app.exception_handler(FoundryError)
    async def foundry_error_handler(_request: Request, exc: FoundryError):
        db.record_error(exc.code, exc.message, exc.details)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

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
    async def unexpected_error_handler(_request: Request, exc: Exception):
        db.record_error("UNEXPECTED_ERROR", str(exc))
        return JSONResponse(status_code=500, content={"error": {"code": "UNEXPECTED_ERROR", "message": "An unexpected local application error occurred.", "details": str(exc)}})

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

    @app.get("/api/characters")
    def characters_list() -> list[dict[str, Any]]:
        rows = character_sheets.list_characters()
        for row in rows:
            workflow = character_creation.recovery(str(row["project_id"]))
            row["workflow"] = workflow
            descriptive = ((workflow.get("active_run") or workflow.get("latest_run") or {}).get("owner_descriptive_fields") or {}).get("resolved") or {}
            proposed_name = ((descriptive.get("identity") or {}).get("name") if isinstance(descriptive, dict) else None)
            if proposed_name and row.get("name") in {None, "", "AI-proposed character"}:
                row["name"] = proposed_name
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
        return rows

    @app.get("/api/characters/{project_id}/sheet")
    def character_sheet_get(project_id: str) -> dict[str, Any]:
        result = character_sheets.sheet(project_id)
        result["workflow"] = character_creation.recovery(project_id)
        return result

    @app.get("/api/characters/{project_id}/factory-workspace/status")
    def character_factory_workspace_status(project_id: str) -> dict[str, Any]:
        return factory_authoring.status(project_id)

    @app.post("/api/characters/{project_id}/factory-workspace/build")
    def character_factory_workspace_build(project_id: str) -> dict[str, Any]:
        return factory_authoring.build(project_id)

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
        return combatant_library.inventory().model_dump(mode="json", by_alias=True)

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
        return combat.list_matches()

    @app.post("/api/combat/matches")
    def combat_match_create(body: CombatCreateMatchRequest) -> dict[str, Any]:
        return combat.create_match(**body.model_dump())

    @app.get("/api/combat/matches/{match_id}")
    def combat_match_get(match_id: str) -> dict[str, Any]:
        return combat.get_match(match_id)

    @app.get("/api/combat/matches/{match_id}/presentation")
    def combat_match_presentation(match_id: str, boundary: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
        return combat.presentation(match_id, boundary_index=boundary)

    @app.post("/api/combat/matches/{match_id}/controller-mode")
    def combat_match_controller_mode(match_id: str, body: CombatControllerModeRequest) -> dict[str, Any]:
        return combat.set_controller_mode(match_id, actor_id=body.actor_id, controller_mode=body.controller_mode)

    @app.post("/api/combat/matches/{match_id}/pause")
    def combat_match_pause(match_id: str) -> dict[str, Any]:
        return combat.pause(match_id)

    @app.post("/api/combat/matches/{match_id}/resume")
    def combat_match_resume(match_id: str) -> dict[str, Any]:
        return combat.resume(match_id)

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
    def combat_match_local_step(match_id: str) -> dict[str, Any]:
        return combat.local_step(match_id)

    @app.post("/api/combat/matches/{match_id}/auto-step")
    def combat_match_auto_step(match_id: str) -> dict[str, Any]:
        return combat.auto_step(match_id)

    @app.post("/api/combat/matches/{match_id}/provider-step")
    def combat_match_provider_step(match_id: str) -> dict[str, Any]:
        return combat.provider_step(match_id)

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

    @app.get("/api/character-builder/recovery")
    def character_builder_recovery() -> list[dict[str, Any]]:
        return character_creation.recoverable()

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
        )

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
        return projects.list_projects()

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
    def stage1_prompt_generate(project_id: str) -> dict[str, Any]:
        result = stage1.generate_prompt(project_id)
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
        elif kind in {"completed_character", "gm_character"}:
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
        inventory = combatant_library.inventory().model_dump(mode="json")
        expected = {"combatants": 4, "package_profile": "accepted_demo", "content_lock": "accepted", "tokens": 4, "battlefield": "accepted_demo", "controllers": "configured", "snapshot": "present"}
        candidates = inventory.get("candidates") or inventory.get("entries") or []
        mismatches = []
        if len(candidates) < 4:
            mismatches.append({"field": "combatants", "expected": 4, "actual": len(candidates)})
        return {"schema": "TianxiaFactory.AcceptedDemoPreflight.v1", "read_only": True, "writes_performed": 0, "expected": expected, "inventory_count": len(candidates), "mismatches": mismatches, "ready": not mismatches}

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
        return {"project_id": project_id, "runs": character_creation.list(project_id)}

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
        filename, payload = character_creation.complete_request_zip(run_id)
        receipt = character_creation.complete_request_save_receipt(run_id)
        return Response(content=payload, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Tianxia-Request-Payload-SHA256": receipt["request_payload_sha256"],
            "X-Tianxia-Content-Set-SHA256": receipt["content_set_sha256"],
            "X-Tianxia-Final-Zip-SHA256": receipt["final_zip_sha256"],
            "X-Tianxia-Run-Id": receipt["run_id"],
        })

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

    @app.post("/api/character-creation/runs/{run_id}/manual-response-file")
    async def character_creation_manual_response_file(
        run_id: str, request: Request, filename: str = Query(min_length=1, max_length=240),
    ) -> dict[str, Any]:
        payload = await request.body()
        return _character_creation_api_view(character_creation.submit_manual_file(run_id, filename=filename, payload=payload))

    @app.post("/api/character-creation/runs/{run_id}/descriptive-fields")
    def character_creation_descriptive_fields(run_id: str, body: CharacterCreationDescriptiveFieldsRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.accept_descriptive_fields(run_id, name=body.name, concept=body.concept))

    @app.post("/api/character-creation/runs/{run_id}/finalize")
    def character_creation_finalize(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.finalize(run_id))

    @app.post("/api/character-creation/runs/{run_id}/auto-finalize-opt-in")
    def character_creation_auto_finalize_opt_in(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.create_auto_finalize_opt_in(run_id))

    @app.post("/api/character-creation/runs/{run_id}/revise")
    def character_creation_revise(run_id: str, body: CharacterCreationReviseRequest) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.revise(run_id, owner_notes=body.owner_notes))

    @app.post("/api/character-creation/runs/{run_id}/cancel")
    def character_creation_cancel(run_id: str) -> dict[str, Any]:
        return _character_creation_api_view(character_creation.cancel(run_id))

    @app.get("/api/ai-provider")
    def ai_provider_status() -> dict[str, Any]:
        return ai_provider.status()

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

    static_dir = settings.root_dir / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app
