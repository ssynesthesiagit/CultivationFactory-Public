"""Complete candidate actions in the existing isolated compilation boundary."""
from copy import deepcopy
import json
import time
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

from app.core import FoundryError, deterministic_replay, sha256_file, sha256_json


def _workspace_hashes(root: Path) -> dict[str, str]:
    paths = sorted(root.rglob("*"))
    if root.is_symlink() or any(path.is_symlink() for path in paths):
        raise FoundryError("CG1_GM_CANDIDATE_ACTION_COPY_CHANGED", "The validated action overlay contains a symbolic link.")
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in paths if path.is_file()}


def complete_candidate_action_workspace(
    service: Any, run: dict[str, Any], scratch_db: Any, scratch_root: Path,
    factory_authoring: Mapping[str, Any], expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Use the reproduced project's proofs, then copy the validated overlay."""
    from factory_authoring.command4_provider import Command4ProviderAuthoring
    from factory_authoring.service import FactoryAuthoringWorkspaceService
    from non_sphere_authority.foundation_mechanics import initial_foundation_record_version
    from non_sphere_authority.method_mechanics import initial_method_record_version

    candidate, _lock, _records = service.candidate_gm._project_snapshot(
        scratch_db, run["project_id"], label="candidate",
        method_version=initial_method_record_version(run["request"]),
        foundation_version=initial_foundation_record_version(run["request"]),
    )
    if candidate["metadata"] != expected["context"]["candidate_project"]:
        raise FoundryError(
            "CG1_GM_CANDIDATE_ACTION_REPLAY_CHANGED",
            "The isolated action-authoring replay differs from the captured candidate; no provider call was made.",
        )
    if factory_authoring.get("workspace_sha256") != expected["context"]["factory_workspace"]["workspace_sha256"]:
        raise FoundryError(
            "CG1_GM_CANDIDATE_ACTION_REPLAY_CHANGED",
            "The isolated action workspace differs from the captured workspace; no provider call was made.",
        )
    authoring = Command4ProviderAuthoring(workspace_service=FactoryAuthoringWorkspaceService(scratch_db))
    # Retain ordinary request/response evidence outside the disposable replay.
    output = service.candidate_gm_authoring._root(run["run_id"]) / "action_authoring" / expected["summary"]["capsule_id"]
    # When the sealed authority implies every choice, the provider-free
    # deterministic path builds the same response through the same schema,
    # validation, evidence and overlay checks; the model is asked only when a
    # real choice remains (build 32 spent 214 s on a forced answer and failed).
    from factory_authoring.command4_provider import COMMAND4_DETERMINISTIC_CHOICE_REQUIRED
    try:
        result = authoring.materialize_deterministic(run["project_id"], output)
    except FoundryError as exc:
        if exc.code != COMMAND4_DETERMINISTIC_CHOICE_REQUIRED:
            raise
        result = authoring.author(run["project_id"], service.provider, output)
    if result.get("valid") is not True or result.get("execution_authority") is not True:
        raise FoundryError("CG1_GM_CANDIDATE_ACTION_AUTHORING_INVALID", "Candidate action authoring did not validate.")
    source = Path(result["overlay_path"])
    destination = scratch_root / "authored_candidate_actions"
    # Command4 authoring has already checked this tree and its sealed base.
    # Capture only a byte-identical copy under the normal scratch boundary.
    before = _workspace_hashes(source)
    shutil.copytree(source, destination, symlinks=True)
    copied = _workspace_hashes(destination)
    after = _workspace_hashes(source)
    if before != copied or before != after:
        raise FoundryError("CG1_GM_CANDIDATE_ACTION_COPY_CHANGED", "The validated action overlay changed while copying it for capture.")
    return {
        "project_id": run["project_id"], "project_revision": candidate["metadata"]["project_revision"],
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "workspace_path": str(destination), "workspace_sha256": sha256_json(copied),
        "manifest_sha256": copied["Workspace_Manifest.json"], "artifact_hashes": copied,
    }


def complete_forced_candidate_actions(
    service: Any, run: dict[str, Any], scratch_db: Any, scratch_root: Path,
    factory_authoring: Mapping[str, Any],
) -> Mapping[str, Any]:
    """At the first capture, resolve open action slots whose answer is forced.

    When the sealed Command 4 domains imply every choice, the provider-free
    deterministic path writes the same validated overlay the later GM prepare
    step would, so the captured workspace is already complete and GM prepare
    skips its replay compile (7.8 min in build 32).  Anything that needs a
    real choice is left for the model exactly as before.
    """
    from factory_authoring.command4_provider import COMMAND4_DETERMINISTIC_CHOICE_REQUIRED, Command4ProviderAuthoring
    from factory_authoring.service import FactoryAuthoringWorkspaceService
    from non_sphere_authority.foundation_mechanics import initial_foundation_record_version
    from non_sphere_authority.method_mechanics import initial_method_record_version

    workspace = factory_authoring.get("workspace_path")
    surface_path = Path(workspace) / "Command_4/Complete_Action_Surface.json" if isinstance(workspace, str) else None
    if surface_path is None or not surface_path.is_file():
        return factory_authoring
    if not json.loads(surface_path.read_text()).get("unresolved"):
        return factory_authoring
    authoring = Command4ProviderAuthoring(workspace_service=FactoryAuthoringWorkspaceService(scratch_db))
    try:
        result = authoring.materialize_deterministic(run["project_id"], scratch_root / "forced_action_authoring")
    except FoundryError as exc:
        if exc.code == COMMAND4_DETERMINISTIC_CHOICE_REQUIRED:
            return factory_authoring
        raise
    if result.get("valid") is not True or result.get("execution_authority") is not True:
        raise FoundryError("CG1_GM_CANDIDATE_ACTION_AUTHORING_INVALID", "Forced candidate action authoring did not validate.")
    candidate, _lock, _records = service.candidate_gm._project_snapshot(
        scratch_db, run["project_id"], label="candidate",
        method_version=initial_method_record_version(run["request"]),
        foundation_version=initial_foundation_record_version(run["request"]),
    )
    source = Path(result["overlay_path"])
    destination = scratch_root / "authored_candidate_actions"
    before = _workspace_hashes(source)
    shutil.copytree(source, destination, symlinks=True)
    copied = _workspace_hashes(destination)
    after = _workspace_hashes(source)
    if before != copied or before != after:
        raise FoundryError("CG1_GM_CANDIDATE_ACTION_COPY_CHANGED", "The validated action overlay changed while copying it for capture.")
    return {
        "project_id": run["project_id"], "project_revision": candidate["metadata"]["project_revision"],
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "workspace_path": str(destination), "workspace_sha256": sha256_json(copied),
        "manifest_sha256": copied["Workspace_Manifest.json"], "artifact_hashes": copied,
    }


def prepare_candidate_actions(service: Any, run_id: str) -> None:
    """Run action authoring once before GM policy authoring when slots remain."""
    gm = service.candidate_gm_authoring
    phases: dict[str, Any] = {}
    started = time.perf_counter()

    def mark(name: str) -> None:
        nonlocal started
        phases[name] = round((time.perf_counter() - started) * 1000)
        started = time.perf_counter()

    try:
        _prepare_candidate_actions(service, gm, run_id, phases, mark)
    finally:
        record = getattr(service, "_record_stage_timings", None)
        if phases and callable(record):
            record(run_id, "gm_prepare_actions", phases)


def _prepare_candidate_actions(service: Any, gm: Any, run_id: str, phases: dict[str, Any], mark: Any) -> None:
    with gm._run_scope(run_id) as run_io:
        with run_io.exclusive_lock():
            capsule, parts = gm._capsule(run_id)
            if gm._load_existing(parts) is not None:
                return
            with tempfile.TemporaryDirectory(prefix="cg1-action-read-", dir="/var/tmp") as temporary:
                service.candidate_gm.materialize_factory_workspace(run_id, Path(temporary))
                surface = json.loads((Path(temporary) / "Command_4/Complete_Action_Surface.json").read_text())
                mark("materialize_workspace_read_surface")
                if not surface.get("unresolved"):
                    return
            run = service.get(run_id)
            # Model-written GM guidance is an optional step (owner ruling
            # 2026-09-13), so a build that already passed its gates may still
            # author it before finalize.  The recapture below runs in scratch.
            if run.get("status") not in {"NEEDS_REVIEW", "READY_FOR_REVIEW"}:
                raise FoundryError("CG1_GM_CANDIDATE_ACTION_STATE_INVALID", "Candidate actions require the captured review checkpoint.")
            plan, intent, _ = service._normalize_and_materialize_response(run, json.loads(capsule["exact_response_text"]))
            if intent is not None:
                run["canonical_selection_intent"] = intent.as_dict()
            final_plan = deepcopy(capsule["final_plan"])
            plan = service._plan_with_accepted_final_target(run, plan, final_plan)
            mark("normalize_response")
            with deterministic_replay(run["created_at"], run["request"]["request_sha256"]):
                compile_timings: dict[str, Any] = {}
                try:
                    try:
                        service._compile_once(
                            run, plan, 0, accepted_final_plan=final_plan, final_plan=final_plan,
                            candidate_action_authoring=capsule,
                            _timing_sink=compile_timings,
                        )
                    except FoundryError as exc:
                        # The normal provisional GM gate follows capture. It remains
                        # closed until the separately authored GM receipt is approved.
                        if exc.code != "CHARACTER_GM_COMMAND4_BLOCKED" or not isinstance(exc.details, Mapping) or not exc.details.get("gm_candidate_capsule"):
                            raise
                finally:
                    mark("recapture_compile")
                    phases.update({f"recapture_compile.{key}": value for key, value in compile_timings.items()})
            refreshed, _parts = gm._capsule(run_id)
            if refreshed["summary"]["capsule_id"] == capsule["summary"]["capsule_id"]:
                raise FoundryError("CG1_GM_CANDIDATE_ACTION_CAPTURE_MISSING", "The authored action workspace was not captured.")
