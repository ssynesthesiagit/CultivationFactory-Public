from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from . import service as _service


def compile_once_stage1_first(
    self: Any,
    run: dict[str, Any],
    plan: dict[str, Any],
    index: int,
    *,
    prior_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Compile one isolated candidate with the frozen Stage 1 boundary first.

    Exact Method materialization is a server-owned native mutation and advances
    the scratch project revision. It must therefore occur only after the frozen
    Stage 1 response is validated and committed, and before Stage 2/projection.
    The remainder of the production compilation path is intentionally identical
    to ``CharacterCreationExecutionService._compile_once``.
    """

    choice_snapshot = self._require_frozen_choice_snapshot(run)
    with _service.tempfile.TemporaryDirectory(
        prefix=f"cg1-scratch-{index}-",
        ignore_cleanup_errors=True,
    ) as td:
        root = Path(td)
        data = root / "data"
        self._snapshot_data(data)
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
        scratch_db = _service.Database(settings)
        scratch_db.migrate()
        services = self._scratch_services(scratch_db)
        stage1 = services["stage1"]

        stage1_response = plan["stage1_response"]
        response_text = (
            stage1_response
            if isinstance(stage1_response, str)
            else _service.canonical_json(stage1_response)
        )
        attempt = stage1.validate_response(
            run["request"]["stage1_prompt"]["prompt_id"],
            response_text,
            prior_attempt_id=prior_attempt_id,
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

        method_access_receipt = self._materialize_method_hard_lock(
            run,
            scratch_db,
            phase="scratch_compile",
        )
        stage2_validation, stage2_commit = self._stage2_commit(
            services["stage2"],
            deepcopy(plan["stage2_proposal"]),
            self.owner_principal,
            creation_run=run,
            phase="scratch_compile",
        )
        self._issue_initial_catalog_provenance(
            run,
            frozen_snapshot=choice_snapshot,
            phase="scratch_compile",
            authority_db=scratch_db,
            _finalization_authority=_service._SERVER_SCRATCH_COMPILATION_AUTHORITY,
        )
        projection = services["projections"].build(
            run["project_id"],
            choice_snapshot=deepcopy(choice_snapshot),
        )
        sheet = self._invoke(
            services["character_sheets"],
            ("build", "build_sheet", "sheet", "current"),
            run["project_id"],
        )
        if services.get("production_release") is not None:
            release = services["production_release"].compile(
                run["project_id"],
                output_root=root / "release",
                register=False,
            )
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
            combat = self._invoke(
                services["combat_readiness"],
                ("compile", "build", "verify"),
                run["project_id"],
            )
        artifacts = {
            "stage1": stage1_commit,
            "stage2_validation": stage2_validation,
            "stage2": stage2_commit,
            "method_access": method_access_receipt,
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
            key: _service.sha256_json(self._identity_payload(value))
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
        return {
            "schema": "TianxiaFoundry.CompiledCharacterCandidate.v3",
            "candidate_identity": candidate_identity,
            "typed_choice_snapshot": deepcopy(choice_snapshot),
            "identities": identities,
            "preview": preview,
            "artifacts": artifacts,
        }
