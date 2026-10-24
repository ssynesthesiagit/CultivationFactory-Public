from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

def compile_once_stage1_first(
    self: Any,
    run: dict[str, Any],
    plan: dict[str, Any],
    index: int,
    *,
    prior_attempt_id: str | None = None,
    accepted_final_plan: dict[str, Any] | None = None,
    final_plan: dict[str, Any] | None = None,
    candidate_gm_authority: dict[str, Any] | None = None,
    candidate_action_authoring: dict[str, Any] | None = None,
    _timing_sink: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile one isolated candidate with the frozen Stage 1 boundary first.

    The delegated final grant plan is materialized before Stage 1 so the frozen
    compile sees the accepted catalog authority. Exact Method materialization is
    a separate server-owned native mutation after Stage 1 and before Stage 2.
    The remainder of the production compilation path is intentionally identical
    to ``CharacterCreationExecutionService._compile_once``.
    """

    from . import service as _service

    compile_timings: dict[str, Any] = (
        _timing_sink if isinstance(_timing_sink, dict) else {}
    )

    def finish_timing(phase: str, started: float) -> None:
        compile_timings[phase] = _service._elapsed_ms(
            started,
            _service.time.perf_counter(),
        )

    choice_snapshot = self._require_frozen_choice_snapshot(run)
    # Keep the stage1-first adapter behaviorally identical to the central
    # compiler: descriptive server-owned fields are materialized in the
    # scratch database before Stage 1/Stage 2 outputs are compared with live
    # finalization.
    plan = self._execution_descriptive_fields(run, plan)
    with _service.tempfile.TemporaryDirectory(
        prefix=f"cg1-scratch-{index}-",
        ignore_cleanup_errors=True,
    ) as td:
        root = Path(td)
        data = root / "data"
        phase_started = _service.time.perf_counter()
        self._snapshot_data(data, hash_tree=False)
        self._snapshot_external_security(data)
        finish_timing("snapshot_copy_hash", phase_started)
        source_settings = self.db.settings
        settings = _service.Settings(
            root_dir=source_settings.root_dir,
            data_dir=data,
            db_path=data / source_settings.db_path.name,
            inbox_dir=data / "inbox",
            exports_dir=data / "exports",
            packs_dir=data / "content_packs",
            vendor_dir=data / "vendor",
            logs_dir=data / "logs",
            backups_dir=data / "backups",
            security_dir=data / "security",
            factory_zip=source_settings.factory_zip,
            fixture_path=source_settings.fixture_path,
        )
        phase_started = _service.time.perf_counter()
        scratch_db = _service.Database(settings)
        scratch_db.migrate()
        self._prepare_scratch_compilation_run(run, scratch_db, scratch_root=root)
        services = self._scratch_services(scratch_db)
        finish_timing("scratch_db_migrate_service_creation", phase_started)
        stage1 = services["stage1"]
        phase_started = _service.time.perf_counter()
        self._materialize_descriptive_fields(
            run,
            plan,
            scratch_db,
            phase="scratch_compile",
        )
        if accepted_final_plan is not None:
            self._materialize_delegated_final_grant_plan(
                run,
                accepted_final_plan,
                scratch_db,
                phase="scratch_compile",
            )
        finish_timing("descriptive_grant_materialization", phase_started)

        stage1_response = plan["stage1_response"]
        response_text = (
            stage1_response
            if isinstance(stage1_response, str)
            else _service.canonical_json(stage1_response)
        )
        phase_started = _service.time.perf_counter()
        attempt = stage1.validate_response(
            run["request"]["stage1_prompt"]["prompt_id"],
            response_text,
            prior_attempt_id=self._stage1_prior_attempt_id(
                scratch_db,
                run["request"]["stage1_prompt"].get("prompt_id"),
                prior_attempt_id,
            ),
        )
        validation = attempt.get("validation") or {}
        if (
            validation.get("valid") is False
            or validation.get("errors")
            or validation.get("blockers")
        ):
            raise _service.FoundryError(
                "CG1_STAGE1_INVALID",
                "Stage 1 validation rejected the plan.",
                details=validation,
            )
        stage1_commit = stage1.approve_and_commit(
            attempt.get("attempt_id"),
            self.owner_principal,
        )
        finish_timing("stage1_validate_commit", phase_started)

        phase_started = _service.time.perf_counter()
        method_access_receipt = self._materialize_method_hard_lock(
            run,
            scratch_db,
            phase="scratch_compile",
            plan=plan,
        )
        finish_timing("method_lock", phase_started)
        phase_started = _service.time.perf_counter()
        constructed_arts_receipt = self._materialize_constructed_arts(
            run,
            scratch_db,
            phase="scratch_compile",
            plan=plan,
        )
        finish_timing("constructed_arts", phase_started)
        delegated_path_ids = self._delegated_path_ids_from_canonical_intent(
            plan.get("canonical_selection_intent"),
        )
        path_authority_handoff: dict[str, Any] = {}

        def build_scratch_projection_inside_stage2_scope() -> Any:
            self._issue_initial_catalog_provenance(
                run,
                frozen_snapshot=choice_snapshot,
                phase="scratch_compile",
                authority_db=scratch_db,
                _finalization_authority=_service._SERVER_SCRATCH_COMPILATION_AUTHORITY,
                accepted_final_plan=accepted_final_plan,
            )
            projection = self._build_character_creation_projection(
                services["projections"],
                services["stage2"],
                run["project_id"],
                choice_snapshot,
            )
            if services.get("production_release") is not None:
                path_authority_handoff["value"] = self._capture_character_creation_path_authority(
                    services["stage2"],
                    delegated_path_ids,
                )
            return projection

        phase_started = _service.time.perf_counter()
        stage2_validation, stage2_commit, projection = self._stage2_commit(
            services["stage2"],
            deepcopy(plan["stage2_proposal"]),
            self.owner_principal,
            creation_run=run,
            phase="scratch_compile",
            delegated_path_ids=delegated_path_ids,
            after_commit=build_scratch_projection_inside_stage2_scope,
            _timing_sink=compile_timings,
        )
        finish_timing("stage2_commit_projection", phase_started)
        phase_started = _service.time.perf_counter()
        sheet = self._invoke(
            services["character_sheets"],
            ("build", "build_sheet", "sheet", "current"),
            run["project_id"],
        )
        finish_timing("character_sheet_build", phase_started)
        candidate_capsule = None
        if services.get("production_release") is not None:
            # The approved Factory workspace is compared with the reproduced
            # post-Stage-2 project.  Admit it here, immediately before the
            # ordinary release validator reads it, rather than against the
            # initial copied project at the start of the scratch run.
            self._materialize_candidate_gm_authority(
                run,
                scratch_db,
                services,
                final_plan=final_plan,
                authority=candidate_gm_authority,
            )

            def capture_candidate_workspace(factory_authoring: dict[str, Any]) -> None:
                nonlocal candidate_capsule
                phase_started = _service.time.perf_counter()
                if candidate_action_authoring is not None:
                    from .candidate_action_authoring import complete_candidate_action_workspace

                    factory_authoring = complete_candidate_action_workspace(
                        self, run, scratch_db, root, factory_authoring, candidate_action_authoring,
                    )
                else:
                    from .candidate_action_authoring import complete_forced_candidate_actions

                    factory_authoring = complete_forced_candidate_actions(
                        self, run, scratch_db, root, factory_authoring,
                    )
                candidate_capsule = self.candidate_gm.capture(
                    run=run,
                    root_db=self.db,
                    scratch_db=scratch_db,
                    scratch_root=root,
                    sheet=sheet,
                    projection=projection,
                    stage2_validation=stage2_validation,
                    stage2_commit=stage2_commit,
                    stage2_service=services.get("stage2"),
                    final_plan=final_plan,
                    factory_authoring=factory_authoring,
                )
                finish_timing("gm_candidate_context_capture", phase_started)

            release_kwargs = {
                "output_root": root / "release",
                "register": False,
                "output_profile": deepcopy(plan.get("output_profile") or {}),
                "_timing_sink": compile_timings,
            }
            if candidate_gm_authority is None:
                # Capture a candidate only while GM authoring is still open.
                # Once the owner has approved a capsule, a rebuild reproduces
                # that candidate; capturing again would replace the current
                # capsule pointer and orphan the approved authority.
                release_kwargs["_candidate_authoring_callback"] = capture_candidate_workspace
            if path_authority_handoff.get("value") is not None:
                release_kwargs["_character_creation_path_authority"] = path_authority_handoff["value"]
            phase_started = _service.time.perf_counter()
            try:
                release = services["production_release"].compile(
                    run["project_id"],
                    **release_kwargs,
                )
            except _service.FoundryError as exc:
                if candidate_capsule is None:
                    raise
                details = deepcopy(exc.details) if isinstance(exc.details, dict) else {
                    "original_details": deepcopy(exc.details)
                }
                details["gm_candidate_capsule"] = deepcopy(candidate_capsule)
                raise _service.FoundryError(
                    exc.code,
                    exc.message,
                    details=details,
                    status_code=exc.status_code,
                ) from exc
            finish_timing("production_release", phase_started)
            authoring = release["factory_authoring"]
            gm = release["command5"]
            gm_result = release["consumer"]
            portable = {
                "package_sha256": release["portable_audit"].get("sha256"),
                "audit": release["portable_audit"],
                "clean_import": release["clean_import"],
                "release_identity": release["production_artifact_identity"],
            }
            stable_release = services["production_release"]._stable(release)
        else:
            authoring = self._invoke(
                services["factory_authoring"],
                ("build",),
                run["project_id"],
            )
            gm = self._invoke(
                services["gm_exports"],
                ("export",),
                run["project_id"],
            )
            gm_result = self._invoke(
                services["gm_consumer"],
                ("verify", "consume", "import_package"),
                gm,
            )
            portable = self._invoke(
                services["portable_characters"],
                ("build_for_project", "build_verified", "export", "verified_status"),
                run["project_id"],
            )

        combat = None
        if bool((plan.get("output_profile") or {}).get("combat_ready")):
            phase_started = _service.time.perf_counter()
            if services.get("production_release") is not None:
                combat = _service._production_release_combat_receipt(release)
            else:
                combat = self._invoke(
                    services["combat_readiness"],
                    ("compile", "build", "verify"),
                    run["project_id"],
                )
            finish_timing("optional_combat", phase_started)
        phase_started = _service.time.perf_counter()
        artifacts = {
            "stage1": stage1_commit,
            "stage2_validation": stage2_validation,
            "stage2": stage2_commit,
            "method_access": method_access_receipt,
            "constructed_arts": constructed_arts_receipt,
            "ledger": projection,
            "projection": projection,
            "character_sheet": sheet,
            "factory_authoring": authoring,
            "gm_model": gm,
            "gm_consumer": gm_result,
            "portable_character": portable,
            "combat": combat,
        }
        identity_artifacts = artifacts
        if services.get("production_release") is not None:
            identity_artifacts = {
                **artifacts,
                "factory_authoring": stable_release["factory_authoring"],
                "gm_model": stable_release["command5"],
                "gm_consumer": stable_release["consumer"],
                "portable_character": {
                    "package_sha256": stable_release["portable_audit"].get("sha256"),
                    "audit": stable_release["portable_audit"],
                    "clean_import": stable_release["clean_import"],
                    "release_identity": release["production_artifact_identity"],
                },
            }
        identities = {
            key: _service.sha256_json(self._identity_payload(value, _surface=key))
            for key, value in identity_artifacts.items()
            if value is not None
        }
        preview = {
            "identity": deepcopy(plan.get("owner_descriptive_fields") or {}),
            "target_cl": plan.get("target_cl"),
            "compiled": deepcopy(artifacts),
            "readiness": {
                key: {
                    "service": key,
                    "identity": identities.get(key),
                    "verification_status": "VERIFIED",
                    "receipt": deepcopy(artifacts.get(key)),
                }
                for key in _service.REQUIRED_SURFACES
            },
            "uncertainties": deepcopy(plan.get("uncertainties") or []),
            "fallbacks": deepcopy(plan.get("fallbacks") or []),
        }
        if combat is not None:
            preview["readiness"]["combat"] = {
                "service": "combat_readiness",
                "identity": identities["combat"],
                "verification_status": "VERIFIED",
                "receipt": deepcopy(combat),
            }
        candidate_identity = _service.sha256_json(
            {
                "plan_sha256": _service.sha256_json(plan),
                "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
                "identities": identities,
            }
        )
        finish_timing("identity_preview_construction", phase_started)
        return {
            "schema": "TianxiaFoundry.CompiledCharacterCandidate.v3",
            "candidate_identity": candidate_identity,
            "typed_choice_snapshot": deepcopy(choice_snapshot),
            "identities": identities,
            "preview": preview,
            "artifacts": artifacts,
            "_timings": _service._compile_timing_receipt(compile_timings),
        }
