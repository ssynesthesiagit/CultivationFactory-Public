from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import Database, Settings, canonical_json, sha256_bytes, sha256_file
from catalog.service import CatalogService
from character_creation import CharacterCreationExecutionService
from character_creation.current_fixture import (
    W5_PROJECT_ID,
    W5_PROJECT_NAME,
    complete_plan,
    create_fresh_project,
)
from character_creation.production_release import CharacterProductionReleaseAdapter
from character_sheet import CharacterSheetService
from factory_authoring import FactoryAuthoringWorkspaceService
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from project_store.service import ProjectStore
from projector.service import ProjectionService
from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
from stage1.service import Stage1ClipboardService
from stage2 import Stage2AdvancementService
from tests.r4v_harness import ENV_KEY_HEX, ENV_KEY_ID, provision_external_test_key
from vendor_adapter.service import FactoryAdapter

MODES = ("MANUAL_CHAT", "STANDARD_API", "AUTO_FINALIZE_WHEN_CLEAN")
FIXED_UTC = "2026-07-29T04:00:00Z"
GM_RELATIVE = Path("gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip")
GM_SHA256 = "c281c80e96c718a2c629b65c762b1c053a82eff7201d018a6acca1110c1c0f8f"
W5_INTEGRITY_KEY_HEX = "1b60725f509e0b81c300d96650be7c24bdde4129187782039496ed006b6b3fd0"  #gitleaks:allow -- inert deterministic test fixture
W5_INTEGRITY_KEY_ID = "integrity-key-v1:dda7276707b50670c22d46f3b05d82359c70040a039bb09f7faf0c6247d10216"  #gitleaks:allow -- hash-derived fixture identifier


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def copy_artifact(source: str | Path | None, target: Path) -> dict[str, Any] | None:
    if not source:
        return None
    source_path = Path(source)
    if not source_path.is_file():
        return {"source": str(source_path), "copied": False, "reason": "not-a-file"}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return {
        "source_name": source_path.name,
        "retained_path": target.as_posix(),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "copied": True,
    }


class ExactProductionProvider:
    def __init__(self, plan: dict[str, Any]):
        self.plan = deepcopy(plan)

    def status(self) -> dict[str, Any]:
        return {
            "ready": True,
            "provider_id": "deepseek",
            "credential_source": "fixture-no-secret",
        }

    def complete_json(self, *, prompt_text: str, system_message: str, purpose: str) -> dict[str, Any]:
        request = json.loads(prompt_text)["complete_request"]
        value = deepcopy(self.plan)
        value["request_sha256"] = request["request_sha256"]
        response_text = canonical_json(value)
        return {
            "provider_id": "deepseek",
            "purpose": purpose,
            "model": "deepseek-chat",
            "request_sha256": sha256_bytes(prompt_text.encode("utf-8")),
            "response_sha256": sha256_bytes(canonical_json({"content": response_text}).encode("utf-8")),
            "completion_sha256": sha256_bytes(response_text.encode("utf-8")),
            "response_text": response_text,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "value": value,
        }


def build_service(db: Database, provider: ExactProductionProvider) -> tuple[CharacterCreationExecutionService, str]:
    principal = ProcessPrincipalProvider().current_principal()
    bound = BoundPrincipalProvider(principal)
    service = CharacterCreationExecutionService(
        db,
        stage1=Stage1ClipboardService(db),
        provider=provider,
        project_store=ProjectStore(db),
        stage2=Stage2AdvancementService(db, principal_provider=bound),
        character_sheets=CharacterSheetService(db),
        gm_exports=GMCharacterExportService(db),
        portable_characters=PortableCharacterPackageService(db),
        factory_authoring=FactoryAuthoringWorkspaceService(db),
        projections=ProjectionService(db),
        production_release=CharacterProductionReleaseAdapter(db),
        owner_principal=principal.principal_id,
    )
    return service, principal.principal_id


def retain_mode_artifacts(
    mode_root: Path,
    *,
    run: dict[str, Any],
    plan: dict[str, Any],
    request_name: str,
    request_zip: bytes,
    preference: dict[str, Any],
    factory_zip: Path,
    catalog: dict[str, Any],
    project: dict[str, Any],
    principal_id: str,
) -> dict[str, Any]:
    outputs = run["outputs"]
    mode_root.mkdir(parents=True, exist_ok=True)
    (mode_root / request_name).write_bytes(request_zip)
    write_json(mode_root / "plan-response.json", plan)
    write_json(mode_root / "stage1-normalized-response.json", plan["stage1_response"])
    write_json(mode_root / "stage2-proposal-and-choices.json", plan["stage2_proposal"])
    write_json(mode_root / "execution-mode-preference.json", preference)
    write_json(mode_root / "approval-and-final-receipt.json", {
        "stage1_approval": outputs["stage1"].get("approval"),
        "stage1_commit": outputs["stage1"].get("commit"),
        "stage2_receipt": outputs["stage2"].get("receipt"),
        "canonical_commit": run["commit"],
        "auto_finalize_opt_in": run.get("auto_finalize_opt_in"),
    })
    write_json(mode_root / "authority-inventory.json", {
        "schema": "Tianxia.W5P1AuthorityInventory.v1",
        "project_id": W5_PROJECT_ID,
        "project_name": W5_PROJECT_NAME,
        "factory": {"path": factory_zip.name, "sha256": sha256_file(factory_zip)},
        "catalog_build_id": catalog.get("catalog_build_id"),
        "content_lock": project["project"]["content_lock"],
        "owner_principal_source": "ProcessPrincipalProvider.current_principal",
        "owner_principal_id": principal_id,
        "owner_principal_hash": run["commit"]["approved_by_sha256"],
        "fixture_integrity_key_id": W5_INTEGRITY_KEY_ID,
        "gm_consumer": {"path": GM_RELATIVE.as_posix(), "sha256": sha256_file(ROOT / GM_RELATIVE)},
    })
    write_json(mode_root / "factory-commands-1-through-4-receipt.json", outputs["gm_model"]["character_gm_command4"])
    write_json(mode_root / "command5-result.json", outputs["gm_model"])
    write_json(mode_root / "character-sheet.json", outputs["character_sheet"])
    write_json(mode_root / "exact-gm-consumer.json", outputs["gm_consumer"])
    write_json(mode_root / "portable-audit.json", outputs["portable_character"]["audit"])
    write_json(mode_root / "portable-clean-import-and-reimport.json", outputs["portable_character"]["clean_import"])
    write_json(mode_root / "portable-registration.json", outputs["portable_character"]["registration"])
    write_json(mode_root / "gm-export.json", outputs["portable_character"]["gm_export"])

    copied: dict[str, Any] = {}
    request_path = mode_root / request_name
    copied["complete_manual_request_zip"] = {
        "retained_path": request_path.as_posix(),
        "bytes": request_path.stat().st_size,
        "sha256": sha256_file(request_path),
        "copied": True,
    }
    copied["command5_candidate"] = copy_artifact(
        outputs["gm_model"].get("candidate_zip"), mode_root / "artifacts" / "command5-candidate.zip"
    )
    copied["gm_model"] = copy_artifact(
        outputs["gm_model"].get("gm_model_path"), mode_root / "artifacts" / "Tianxia_GM_Character_Model_v1.json"
    )
    copied["gm_view_model"] = copy_artifact(
        outputs["gm_model"].get("gm_view_model_path"), mode_root / "artifacts" / "Tianxia_GM_Character_View_Model_v2.json"
    )
    copied["gm_build_manifest"] = copy_artifact(
        outputs["gm_model"].get("build_manifest_path"), mode_root / "artifacts" / "PACKAGE_MANIFEST.json"
    )
    copied["gm_deep_audit"] = copy_artifact(
        outputs["gm_model"].get("deep_audit_path"), mode_root / "artifacts" / "C2B3_Character_GM_Deep_Audit.json"
    )
    copied["character_sheet_artifact"] = copy_artifact(
        (outputs["character_sheet"].get("sheet_artifact") or {}).get("path"),
        mode_root / "artifacts" / "Character_Sheet.json",
    )
    copied["ordinary_portable_character"] = copy_artifact(
        outputs["gm_consumer"].get("package_path"), mode_root / "artifacts" / "W5_Current_Ordinary_Character.zip"
    )
    copied["gm_export_package"] = copy_artifact(
        outputs["portable_character"]["gm_export"].get("path"),
        mode_root / "artifacts" / "W5_Current_GM_Export.zip",
    )
    write_json(mode_root / "retained-artifact-inventory.json", copied)
    return copied


def mode_result(
    mode: str,
    *,
    run: dict[str, Any],
    preference: dict[str, Any],
    copied: dict[str, Any],
    status_before_owner_action: str,
    recovered_from_completed_commit: bool = False,
) -> dict[str, Any]:
    package = copied["ordinary_portable_character"]
    return {
        "mode": mode,
        "project_id": W5_PROJECT_ID,
        "status_before_owner_action": status_before_owner_action,
        "final_status": run["status"],
        "auto_finalize_default_off": True,
        "auto_finalize_explicit_opt_in": bool(run.get("auto_finalize_opt_in")),
        "persistent_preference": preference,
        "owner_principal_hash": run["commit"]["approved_by_sha256"],
        "request_sha256": run["request"]["request_sha256"],
        "candidate_identity": run["dry_run"]["candidate_identity"],
        "independent_scratch_builds": run["dry_run"]["independent_compilations"],
        "portable_package_sha256": package["sha256"],
        "release_identity": outputs_release_identity(run),
        "commit": run["commit"],
        "recovered_from_completed_commit": recovered_from_completed_commit,
    }


def execute_mode(mode: str, work_root: Path, output_root: Path) -> dict[str, Any]:
    mode_work = work_root / mode.lower()
    if mode_work.exists():
        raise RuntimeError(f"Refusing to reuse non-clean fixture workspace: {mode_work}")
    data = mode_work / "OwnerTestData"
    data.mkdir(parents=True)
    settings = Settings.from_env(ROOT, data)
    provision_external_test_key(data)
    db = Database(settings)
    db.migrate()
    factory_zip = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
    configured = FactoryAdapter(db).configure(factory_zip)
    catalog = CatalogService(db).rebuild_core(Path(configured["factory_root"]))
    created = create_fresh_project(db, project_id=W5_PROJECT_ID)
    if created["project_id"] != W5_PROJECT_ID:
        raise RuntimeError("The W5 fixture did not retain its new source-aligned project identity.")
    plan = complete_plan(db, W5_PROJECT_ID)
    service, principal_id = build_service(db, ExactProductionProvider(plan))
    run = service.start(
        W5_PROJECT_ID,
        execution_mode=mode,
        idempotency_key="w5.p1.current.production",
    )
    request_name, request_zip = service.complete_request_zip(run["run_id"])
    bound_plan = deepcopy(plan)
    bound_plan["request_sha256"] = run["request"]["request_sha256"]
    plan_text = canonical_json(bound_plan)
    plan = bound_plan
    if mode == "MANUAL_CHAT":
        run = service.submit_manual(
            run["run_id"],
            response_text=plan_text,
            request_sha256=run["request"]["request_sha256"],
        )
    if run["status"] != "READY_FOR_REVIEW":
        raise RuntimeError(canonical_json({
            "mode": mode, "status": run["status"], "blockers": run["blockers"], "warnings": run["warnings"]
        }))
    status_before_owner_action = run["status"]
    if mode == "AUTO_FINALIZE_WHEN_CLEAN":
        run = service.create_auto_finalize_opt_in(run["run_id"])
    else:
        run = service.finalize(run["run_id"])
    if run["status"] != "CLEAN_AND_FINALIZED":
        raise RuntimeError(f"{mode} did not finalize: {run['status']}")
    preference = service.preference(W5_PROJECT_ID)
    if not preference["explicit"] or preference["execution_mode"] != mode:
        raise RuntimeError(f"{mode} preference was not durably persisted.")
    project = ProjectStore(db).get_project(W5_PROJECT_ID)
    copied = retain_mode_artifacts(
        output_root / mode.lower(),
        run=run,
        plan=plan,
        request_name=request_name,
        request_zip=request_zip,
        preference=preference,
        factory_zip=factory_zip,
        catalog=catalog,
        project=project,
        principal_id=principal_id,
    )
    return mode_result(
        mode,
        run=run,
        preference=preference,
        copied=copied,
        status_before_owner_action=status_before_owner_action,
    )


def recover_completed_mode(mode: str, work_root: Path, output_root: Path) -> dict[str, Any]:
    mode_work = work_root / mode.lower()
    data = mode_work / "OwnerTestData"
    if not data.is_dir():
        raise RuntimeError(f"No completed W5 mode workspace is available to recover: {mode_work}")
    db = Database(Settings.from_env(ROOT, data))
    plan = complete_plan(db, W5_PROJECT_ID)
    service, _ = build_service(db, ExactProductionProvider(plan))
    completed = [
        item for item in service.list(W5_PROJECT_ID)
        if item["execution_mode"] == mode and item["status"] == "CLEAN_AND_FINALIZED"
    ]
    if len(completed) != 1:
        raise RuntimeError(f"Expected exactly one completed {mode} commit to recover, found {len(completed)}.")
    run = service.get(completed[0]["run_id"])
    plan = deepcopy(plan)
    plan["request_sha256"] = run["request"]["request_sha256"]
    request_name, request_zip = service.complete_request_zip(run["run_id"])
    preference = service.preference(W5_PROJECT_ID)
    if not preference["explicit"] or preference["execution_mode"] != mode:
        raise RuntimeError(f"{mode} completed preference is not durably persisted.")
    latest_build = CatalogService(db).status().get("latest_build")
    if not latest_build:
        raise RuntimeError(f"{mode} completed workspace has no catalog build.")
    project = ProjectStore(db).get_project(W5_PROJECT_ID)
    copied = retain_mode_artifacts(
        output_root / mode.lower(),
        run=run,
        plan=plan,
        request_name=request_name,
        request_zip=request_zip,
        preference=preference,
        factory_zip=ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip",
        catalog={"catalog_build_id": latest_build["build_id"]},
        project=project,
        principal_id=run["commit"]["approved_by"],
    )
    return mode_result(
        mode,
        run=run,
        preference=preference,
        copied=copied,
        status_before_owner_action="READY_FOR_REVIEW",
        recovered_from_completed_commit=True,
    )


def outputs_release_identity(run: dict[str, Any]) -> str:
    return str(run["outputs"]["portable_character"]["release_identity"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--resume-completed",
        action="store_true",
        help="Recover an already committed mode after an evidence-runner failure; clean runs remain the default.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=MODES,
        help="Run a named subset only for clean sealed-source reproduction; the default acceptance gate runs all modes.",
    )
    args = parser.parse_args()
    selected_modes = tuple(args.modes or MODES)
    if len(set(selected_modes)) != len(selected_modes):
        parser.error("--modes cannot contain duplicate execution modes.")
    work_root = args.work_root.resolve()
    output_root = args.output_root.resolve()
    source_root = ROOT.resolve()
    for root in (work_root, output_root):
        if root == source_root or source_root in root.parents:
            raise RuntimeError("W5 fixture work and evidence roots must be outside the source tree.")
    work_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    if sha256_file(ROOT / GM_RELATIVE) != GM_SHA256:
        raise RuntimeError("The current exact GM consumer authority is not aligned.")

    controlled_environment = {
        "TIANXIA_DETERMINISTIC_UTC": FIXED_UTC,
        ENV_KEY_HEX: W5_INTEGRITY_KEY_HEX,
        ENV_KEY_ID: W5_INTEGRITY_KEY_ID,
    }
    prior_environment = {key: os.environ.get(key) for key in controlled_environment}
    os.environ.update(controlled_environment)
    try:
        results = []
        for mode in selected_modes:
            result = (
                recover_completed_mode(mode, work_root, output_root)
                if args.resume_completed and (work_root / mode.lower()).exists()
                else execute_mode(mode, work_root, output_root)
            )
            write_json(output_root / mode.lower() / "mode-result.json", result)
            results.append(result)
    finally:
        for key, previous in prior_environment.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

    comparable = {
        key: sorted({result[key] for result in results})
        for key in ("project_id", "owner_principal_hash", "request_sha256", "candidate_identity",
                    "portable_package_sha256", "release_identity")
    }
    mismatched = {key: values for key, values in comparable.items() if len(values) != 1}
    if mismatched:
        raise RuntimeError(canonical_json({"W5_MODE_IDENTITY_DIVERGENCE": mismatched}))
    if any(result["independent_scratch_builds"] != 2 for result in results):
        raise RuntimeError("Every W5 mode must retain two independent scratch compilations.")
    if "AUTO_FINALIZE_WHEN_CLEAN" in selected_modes:
        auto_result = results[selected_modes.index("AUTO_FINALIZE_WHEN_CLEAN")]
        if not auto_result["auto_finalize_explicit_opt_in"] or not auto_result["auto_finalize_default_off"]:
            raise RuntimeError("Auto-Finalize was not explicitly and durably opted in from a clean review state.")

    report = {
        "schema": "Tianxia.W5P1CurrentIntegratedWindowsOwnerTestFixture.v1",
        "status": (
            "W5_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST_FIXTURE_READY"
            if selected_modes == MODES
            else "W5_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST_REPRODUCTION_READY"
        ),
        "scope": "W5-P1_ONLY",
        "selected_modes": list(selected_modes),
        "all_modes_exercised": selected_modes == MODES,
        "project_id": W5_PROJECT_ID,
        "project_name": W5_PROJECT_NAME,
        "fresh_current_character_builder_project": True,
        "historical_project_reconstructed": False,
        "deterministic_clock": FIXED_UTC,
        "gm_consumer_sha256": GM_SHA256,
        "modes": results,
        "stable_identities": {key: values[0] for key, values in comparable.items()},
        "combat_readiness": "NOT_REQUESTED_OR_CLAIMED_FOR_THIS_NEW_ORDINARY_IDENTITY",
        "c3d_p2": "NOT_STARTED",
    }
    write_json(output_root / "W5_P1_FIXTURE_ACCEPTANCE.json", report)
    write_json(output_root / "stable-identities.json", report["stable_identities"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
