"""Provider-free guided-controller probe on a scratch copy of production.

From ``APP/``::

    TMPDIR=/var/tmp ../.venv/bin/python tools/provider_free_guided_probe.py \
        --data-root /var/tmp/factory-probe/probe_data \
        --draft-project 00000000-0000-4000-8000-000000000001 \
        --target-cl 20 --method-mode AUTO --receipt /var/tmp/factory-probe/receipt.json

Use ``--finalize`` to opt into the real finalize, final-character review,
materialization, and GM export chain. Use ``--resume-run RUN_ID --finalize``
to continue that chain from an existing scratch run without another walk.
No model provider is called; the walk uses the first-option provider from the
provider-free controller tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

RECEIPT_SCHEMA = "TianxiaFoundry.ProviderFreeGuidedProbeReceipt.v1"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class ProbeSafetyError(ValueError):
    """A probe path is unsafe to use before any scratch write occurs."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def reject_live_path(path: str | Path, *, label: str) -> Path:
    """Resolve ``path`` and reject the live data root and descendants."""

    candidate = Path(path).expanduser().resolve(strict=False)
    live = (Path.home() / ".local" / "state" / "cultivation-factory").resolve(strict=False)
    if candidate == live or live in candidate.parents:
        raise ProbeSafetyError(f"{label} resolves into the live data root: {candidate}")
    return candidate


def _summary(result: Any) -> Any:
    if not isinstance(result, Mapping):
        return result
    keys = (
        "status", "project_id", "run_id", "final_revision", "review_record_id",
        "materialization_id", "binding_sha256", "output_tree_sha256", "path",
        "filename", "sha256", "bytes", "entry_count", "checksum_count",
        "exported", "provider_calls", "blockers", "details",
    )
    return {key: result[key] for key in keys if key in result}


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    secrets = tuple(secret for secret in secrets if secret)
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, Mapping):
        return {
            _redact(key, secrets) if isinstance(key, str) else key: _redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, secrets) for item in value)
    return value


def _error(exc: BaseException, *, redactions: tuple[str, ...] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
    if isinstance(getattr(exc, "code", None), str):
        result["code"] = exc.code
    if getattr(exc, "details", None) is not None:
        result["details"] = exc.details
    return _redact(result, redactions)


def _write_receipt(path: str | Path, receipt: dict[str, Any]) -> Path:
    """Persist a sealed receipt only after rechecking its destination."""

    target = reject_live_path(path, label="receipt path")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = _sha256_json(unsigned)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(_canonical_json(receipt) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _phase(
    receipt: dict[str, Any],
    name: str,
    operation: Callable[[], Any],
    persist: Callable[[], None],
    *,
    redactions: tuple[str, ...] = (),
) -> Any | None:
    started = time.monotonic()
    running = {"phase": name, "status": "RUNNING"}
    receipt.setdefault("phases", []).append(running)
    persist()
    try:
        result = operation()
    except Exception as exc:
        error = _error(exc, redactions=redactions)
        running.update({"status": "BLOCKED", "error": error})
        receipt.update({"status": "BLOCKED", "error": {"phase": name, **error}})
        persist()
        return None
    summary = _redact(_summary(result), redactions)
    phase_status = _redact(result.get("status"), redactions) if isinstance(result, Mapping) else "COMPLETED"
    if not isinstance(phase_status, str) or not phase_status:
        phase_status = "COMPLETED"
    running.update({
        "status": phase_status,
        "duration_seconds": round(max(0.0, time.monotonic() - started), 3),
        "result": summary,
    })
    receipt[name] = summary
    persist()
    return result


def run_finalize_chain(
    service: Any,
    workflow: Any,
    gm_exports: Any,
    *,
    run_id: str,
    project_id: str,
    receipt: dict[str, Any],
    persist: Callable[[], None],
) -> bool:
    """Run real finalization and final-character consumer calls in order."""

    current = service.get(run_id)
    if isinstance(current, Mapping) and current.get("status") == "CLEAN_AND_FINALIZED":
        receipt["finalize"] = {"status": "ALREADY_FINALIZED", "run_id": run_id}
        receipt.setdefault("phases", []).append({"phase": "finalize", "status": "ALREADY_FINALIZED"})
        persist()
    elif _phase(receipt, "finalize", lambda: service.finalize(run_id), persist) is None:
        return False
    finalized = receipt.get("finalize") or {}
    if finalized.get("status") not in {"CLEAN_AND_FINALIZED", "ALREADY_FINALIZED"}:
        receipt.update({
            "status": "BLOCKED",
            "error": {
                "phase": "finalize",
                "code": "PROBE_FINALIZE_STATUS_UNEXPECTED",
                "message": "Finalize did not return CLEAN_AND_FINALIZED.",
                "details": finalized,
            },
        })
        persist()
        return False

    challenge = _phase(receipt, "review_challenge", lambda: workflow.issue_review_challenge(project_id), persist)
    if challenge is None:
        return False
    envelope = challenge.get("challenge") if isinstance(challenge, Mapping) else None
    if not isinstance(envelope, Mapping) or not all(isinstance(envelope.get(key), str) for key in ("challenge_id", "nonce")):
        receipt.update({
            "status": "BLOCKED",
            "error": {
                "phase": "review_challenge",
                "code": "PROBE_REVIEW_CHALLENGE_INVALID",
                "message": "The review service returned no usable challenge envelope.",
            },
        })
        persist()
        return False
    redactions = (envelope["nonce"],)

    approved = _phase(
        receipt,
        "approve",
        lambda: workflow.approve_current_triplet(project_id, envelope["challenge_id"], envelope["nonce"]),
        persist,
        redactions=redactions,
    )
    if approved is None:
        return False
    if not isinstance(approved, Mapping) or approved.get("status") != "APPROVED":
        receipt["phases"][-1]["status"] = "BLOCKED"
        receipt.update({
            "status": "BLOCKED",
            "error": {
                "phase": "approve",
                "code": "PROBE_REVIEW_APPROVAL_STATUS_UNEXPECTED",
                "message": "The review service did not approve the current triplet.",
                "details": receipt.get("approve"),
            },
        })
        persist()
        return False
    record_id = approved.get("review_record_id") if isinstance(approved, Mapping) else None
    if not isinstance(record_id, str) or not record_id:
        receipt.update({
            "status": "BLOCKED",
            "error": {
                "phase": "approve",
                "code": "PROBE_REVIEW_RECORD_INVALID",
                "message": "The review service returned no review record ID.",
            },
        })
        persist()
        return False

    materialized = _phase(
        receipt,
        "materialize",
        lambda: workflow.materialize_current_triplet(project_id, record_id),
        persist,
        redactions=redactions,
    )
    if materialized is None:
        return False
    if isinstance(materialized, Mapping) and materialized.get("status") not in {"MATERIALIZED", "ALREADY_MATERIALIZED"}:
        receipt.update({
            "status": "BLOCKED",
            "error": {
                "phase": "materialize",
                "code": "PROBE_MATERIALIZE_STATUS_UNEXPECTED",
                "message": "The materialization service returned an unexpected status.",
                "details": receipt.get("materialize"),
            },
        })
        persist()
        return False

    exported = _phase(
        receipt,
        "gm_export",
        lambda: gm_exports.export(project_id, filename=f"ASTRA_{project_id}_GM_Screen.zip"),
        persist,
        redactions=redactions,
    )
    if exported is None:
        return False
    if not isinstance(exported, Mapping) or exported.get("exported") is not True:
        receipt["phases"][-1]["status"] = "BLOCKED"
        receipt.update({
            "status": "BLOCKED",
            "error": {
                "phase": "gm_export",
                "code": "PROBE_GM_EXPORT_RESULT_UNEXPECTED",
                "message": "The GM export did not confirm an exported artifact.",
                "details": receipt.get("gm_export"),
            },
        })
        persist()
        return False
    receipt.update({"status": "EXPORTED", "error": None})
    persist()
    return True


def _run(args: argparse.Namespace, data_root: Path, resume_run: str | None, receipt: dict[str, Any], persist: Callable[[], None]) -> int:
    from app.core import Database, Settings
    from character_builder.service import CharacterBuilderService, _TRUSTED_INITIAL_CREATION_BOUNDARY
    from character_creation.creative_controller.route_persistence import DETERMINISTIC_CREATIVE_CONTROLLER
    from character_creation.production_release import CharacterProductionReleaseAdapter
    from character_creation.service import CharacterCreationExecutionService
    from character_sheet import CharacterSheetService
    from factory_authoring import FactoryAuthoringWorkspaceService, FinalCharacterWorkflowService
    from gm_export import GMCharacterExportService
    from non_sphere_authority import NonSphereAuthorityService
    from portable_character import PortableCharacterPackageService
    from project_store.service import ProjectStore
    from projector.service import ProjectionService
    from security.integrity import IntegrityService
    from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
    from stage1.service import Stage1ClipboardService
    from stage2 import Stage2AdvancementService
    from test_dcc_linear_s4 import _GoldenFirstProvider

    settings = Settings.from_env(HERE, data_root)
    for field in ("data_dir", "db_path", "inbox_dir", "exports_dir", "packs_dir", "vendor_dir", "logs_dir", "backups_dir", "security_dir"):
        reject_live_path(getattr(settings, field), label=f"settings.{field}")
    db = Database(settings)
    db.migrate()
    principal = ProcessPrincipalProvider().current_principal()
    bound = BoundPrincipalProvider(principal)
    integrity = IntegrityService.for_database(db)
    projects = ProjectStore(db, principal_provider=bound, integrity=integrity)
    gm_exports = GMCharacterExportService(db)
    workflow = FinalCharacterWorkflowService(db, principal_provider=bound, integrity=integrity)
    service = CharacterCreationExecutionService(
        db,
        stage1=Stage1ClipboardService(db), provider=_GoldenFirstProvider(), project_store=projects,
        stage2=Stage2AdvancementService(db, principal_provider=bound), character_sheets=CharacterSheetService(db),
        gm_exports=gm_exports, portable_characters=PortableCharacterPackageService(db),
        factory_authoring=FactoryAuthoringWorkspaceService(db, principal_provider=bound, integrity=integrity, final_character_workflow=workflow),
        projections=ProjectionService(db), production_release=CharacterProductionReleaseAdapter(db), owner_principal=principal.principal_id,
    )

    if resume_run is None:
        builder = CharacterBuilderService(db)
        draft = projects.get_project(args.draft_project)["project"]
        owner_locks = [
            lock for lock in draft.get("user_locks") or []
            if isinstance(lock, dict) and lock.get("created_revision") == 0 and not str(lock.get("lock_id") or "").startswith("lock.cg1.")
        ]
        for lock in owner_locks:
            if args.target_cl is not None and lock.get("field") == "target_cl":
                lock["value"] = args.target_cl
            if args.method_mode is not None and lock.get("field") == "character_sheet.method_planning_mode":
                lock["value"] = args.method_mode
        values = {lock["field"]: lock.get("value") for lock in owner_locks}
        locked = values.get("character_sheet.locked_choices") or {}
        created = projects.create_project(working_name=args.name, pack_locks=builder._resolved_pack_locks({}), user_locks=owner_locks)
        project_id = created["project"]["project_id"]
        receipt["project_id"] = project_id
        persist()
        authority = NonSphereAuthorityService(db)
        authority.initialize_for_project(
            project_id, target_cl=values.get("target_cl"), path_ids=locked.get("path_choice", []),
            method_id=(locked.get("method_choice") or [None])[0], foundation_id=(locked.get("foundation_choice") or [None])[0],
            background_id=(locked.get("background_choice") or [None])[0],
            access_source_records=values.get("character_sheet.non_sphere_access_sources") or [],
            path_attainment_by_id={path_id: values.get("target_cl") for path_id in locked.get("path_choice", [])},
            subpath_ids=locked.get("subpath_choice", []),
            background_route_ids=builder._resolved_background_routes(locked, {}, authority=authority),
            trusted_initial_creation=True, _initial_creation_authority=_TRUSTED_INITIAL_CREATION_BOUNDARY,
        )
        started = time.monotonic()
        result = service.start(project_id, execution_mode="STANDARD_API", idempotency_key=f"probe-{int(time.time())}", controller_route=DETERMINISTIC_CREATIVE_CONTROLLER)
        receipt.update({"run_id": result.get("run_id"), "status": result.get("status"), "walk": _summary(result)})
        receipt.setdefault("phases", []).append({"phase": "walk", "status": result.get("status"), "duration_seconds": round(time.monotonic() - started, 3), "result": _summary(result)})
        persist()
        run_id = result.get("run_id")
        print(f"project {project_id} run {run_id} status {result.get('status')} in {time.monotonic() - started:.0f}s")
        print("blockers:", json.dumps(result.get("blockers"), indent=1)[:3000])
        authority_view = (result.get("final_plan") or {}).get("catalog_response_authority") or {}
        for key in ("accepted_sphere_ids", "accepted_free_sphere_talent_ids", "accepted_ordinary_talent_ids", "accepted_method_id", "accepted_foundation_id"):
            print(f"{key}: {authority_view.get(key)}")
        print("walk:", {key: ((result.get("controller_route_status") or {}).get("walk") or {}).get(key) for key in ("state", "step_ordinal", "event_count")})
    else:
        result = service.get(resume_run)
        project_id = result.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ProbeSafetyError("The resumed run has no project ID.")
        run_id = resume_run
        receipt.update({"project_id": project_id, "run_id": run_id, "status": result.get("status"), "walk": _summary(result)})
        receipt.setdefault("phases", []).append({"phase": "resume", "status": result.get("status"), "result": _summary(result)})
        persist()
        print(f"project {project_id} run {run_id} status {result.get('status')} (resumed; no walk)")
        print("blockers:", json.dumps(result.get("blockers"), indent=1)[:3000])

    if not isinstance(run_id, str) or not run_id:
        raise ProbeSafetyError("The creation service returned no run ID.")
    if args.finalize:
        ok = run_finalize_chain(service, workflow, gm_exports, run_id=run_id, project_id=project_id, receipt=receipt, persist=persist)
        print("phases:", [(row.get("phase"), row.get("status")) for row in receipt.get("phases") or []])
        return 0 if ok else 1
    persist()
    return 0 if result.get("status") == "READY_FOR_REVIEW" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--draft-project")
    parser.add_argument("--resume-run")
    parser.add_argument("--target-cl", type=int)
    parser.add_argument("--method-mode")
    parser.add_argument("--name", default="ASTRA provider-free probe")
    parser.add_argument("--finalize", action="store_true", help="opt in to finalize, review, materialize, and export")
    parser.add_argument("--receipt", help="persist the JSON phase receipt at this path")
    args = parser.parse_args()
    if args.resume_run and args.draft_project:
        parser.error("--resume-run cannot be combined with --draft-project")
    if not args.resume_run and not args.draft_project:
        parser.error("--draft-project is required unless --resume-run is used")
    if args.resume_run and not args.finalize:
        parser.error("--resume-run requires --finalize")
    if args.resume_run and (args.target_cl is not None or args.method_mode is not None):
        parser.error("--target-cl and --method-mode apply only to a new walk")
    try:
        data_root = reject_live_path(args.data_root, label="data root")
        receipt_path = reject_live_path(args.receipt, label="receipt path") if args.receipt else None
        if args.resume_run and _RUN_ID.fullmatch(args.resume_run) is None:
            raise ProbeSafetyError(f"resume run ID is invalid: {args.resume_run!r}")
    except ProbeSafetyError as exc:
        print(json.dumps({"status": "BLOCKED", "error": _error(exc)}, sort_keys=True))
        return 2

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "probe": "provider_free_guided_probe",
        "data_root": str(data_root),
        "receipt_path": str(receipt_path) if receipt_path else None,
        "requested": {"draft_project": args.draft_project, "resume_run": args.resume_run, "target_cl": args.target_cl, "method_mode": args.method_mode, "finalize": bool(args.finalize), "name": args.name},
        "status": "STARTING",
        "phases": [],
        "error": None,
    }

    def persist() -> None:
        if receipt_path:
            _write_receipt(receipt_path, receipt)

    persist()
    try:
        return _run(args, data_root, args.resume_run, receipt, persist)
    except Exception as exc:
        phase = next((row.get("phase") for row in reversed(receipt.get("phases") or []) if row.get("status") == "RUNNING"), "setup")
        receipt.update({"status": "BLOCKED", "error": {"phase": phase, **_error(exc)}})
        persist()
        print("blocked:", json.dumps(receipt["error"], indent=1)[:6000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
