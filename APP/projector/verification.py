from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.authorities import GM_SCREEN_SHA256
from app.core import Database, FoundryError, canonical_json, sha256_file, utcnow
from app.runtime import helper_python_executable
from projector.service import ProjectionService


def _windows_browser() -> Path | None:
    if os.name != "nt":
        return None
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _run(command: list[str], *, cwd: Path, timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    # The pinned Factory launches some of its own Python helpers by the bare
    # command name ``python``.  Windows Store aliases are not a usable runtime,
    # so expose the interpreter that is already running the Foundry at the
    # front of PATH without modifying the copied vendor toolchain.
    interpreter = helper_python_executable()
    interpreter_dir = str(interpreter.parent)
    if os.name == "nt":
        python3_shim = interpreter.with_name("python3.exe")
        if not python3_shim.exists():
            shutil.copy2(interpreter, python3_shim)
    env = {
        **os.environ,
        "PATH": interpreter_dir + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONUTF8": "1",
    }
    runtime_shims = Path(__file__).resolve().parents[1] / "vendor_adapter" / "runtime_shims"
    env["PYTHONPATH"] = str(runtime_shims) + os.pathsep + os.environ.get("PYTHONPATH", "")
    browser = _windows_browser()
    if browser:
        env["TIANXIA_BROWSER_EXECUTABLE"] = str(browser)
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _files_are_byte_identical(left: Path, right: Path) -> bool:
    """Compare two files without loading a candidate ZIP into memory."""
    if not left.is_file() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_file, right.open("rb") as right_file:
        while True:
            left_chunk = left_file.read(1024 * 1024)
            right_chunk = right_file.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


class ProjectionVerifier:
    def __init__(self, db: Database, *, factory_root: Path, gm_screen_root: Path | None = None):
        self.db = db
        self.factory_root = factory_root.resolve()
        self.gm_screen_root = gm_screen_root.resolve() if gm_screen_root else None
        self.projections = ProjectionService(db, factory_root=self.factory_root)

    def _latest(self, project_id: str) -> tuple[str, Path]:
        status = self.projections.status(project_id)
        if not status.get("eligible_for_command5"):
            raise FoundryError("PROJECTION_NOT_COMMAND5_ELIGIBLE", "Only a sealed READY projection may enter Command 5.", details=status)
        generated = Path(next(x["path"] for x in status["artifacts"] if x["artifact_name"] == "Character_Master_Ledger.json")).parent
        return status["projection_id"], generated

    def command5(
        self,
        project_id: str,
        *,
        source_fixture: Path,
        output_root: Path,
        build_profile: str | None = None,
    ) -> dict[str, Any]:
        # Profile omission intentionally preserves the exact historical default.
        # The explicit Character/GM branch reuses this existing Command 5 entry
        # point and never weakens the pinned full-execution path below.
        if build_profile is not None:
            from factory_authoring.command5_profile import (
                CHARACTER_GM_PROFILE,
                LEGACY_PROFILE,
                CharacterGMCommand5Profile,
            )
            profile_service = CharacterGMCommand5Profile(self.db, factory_root=self.factory_root)
            selected, _contract_sha = profile_service.select_profile(build_profile)
            if selected.get("profile_id") == CHARACTER_GM_PROFILE:
                return profile_service.command5(project_id, output_root=output_root)
            if selected.get("profile_id") != LEGACY_PROFILE:
                raise FoundryError(
                    "FACTORY_BUILD_PROFILE_UNKNOWN",
                    "The requested Factory build profile is not supported.",
                    details={"requested": build_profile},
                )
        projection_id, generated = self._latest(project_id)
        workspace = output_root / "workspace"
        candidate = output_root / "candidate.zip"
        if output_root.exists():
            shutil.rmtree(output_root)
        shutil.copytree(source_fixture, workspace)
        build = workspace / "Build"
        if build.exists():
            shutil.rmtree(build)
        build.mkdir()
        shutil.copy2(generated / "Character_Master_Ledger.json", workspace / "Character_Master_Ledger.json")
        command2 = workspace / "Command_2"
        command2.mkdir(exist_ok=True)
        shutil.copy2(generated / "Rules_Selection_Packets.json", command2 / "Rules_Selection_Packets.json")
        tool = self.factory_root / "07_TOOLS" / "run_command5.py"
        result = _run([str(helper_python_executable()), str(tool), "--factory-root", str(self.factory_root), "--workspace", str(workspace), "--candidate", str(candidate)], cwd=self.factory_root, timeout=600)
        if candidate.is_file():
            candidate_zip = candidate
        else:
            candidate_zips = sorted(candidate.rglob("*.zip")) if candidate.exists() else []
            candidate_zip = candidate_zips[-1] if candidate_zips else None
        status = "COMMAND_5_GM_SCREEN_CANDIDATE_READY" if result["exit_code"] == 0 and candidate_zip else "COMMAND_5_FAILED"
        report = {
            "schema_version": "TianxiaFoundry.Command5ProjectionVerification.v1",
            "project_id": project_id,
            "projection_id": projection_id,
            "status": status,
            "run": result,
            "workspace": str(workspace),
            "candidate_directory": str(candidate),
            "candidate_zip": str(candidate_zip) if candidate_zip else None,
            "candidate_sha256": sha256_file(candidate_zip) if candidate_zip else None,
        }
        with self.db.transaction() as conn:
            conn.execute("UPDATE projection_runs SET command5_status=?,candidate_sha256=?,diagnostics_json=? WHERE projection_id=?", (status, report["candidate_sha256"], canonical_json([] if result["exit_code"] == 0 else [{"code": "COMMAND5_FAILED", "stderr": result["stderr"]}]), projection_id))
            conn.execute("UPDATE projects SET compile_status=? WHERE project_id=?", (status, project_id))
        return report

    def command6(self, project_id: str, *, command5_report: dict[str, Any], workspace: Path, output_dir: Path, build_profile: str | None = None) -> dict[str, Any]:
        projection_id, _generated = self._latest(project_id)
        if build_profile is not None:
            from factory_authoring.command5_profile import CHARACTER_GM_PROFILE, LEGACY_PROFILE, CharacterGMCommand5Profile
            selected, profile_contract_sha = CharacterGMCommand5Profile(self.db, factory_root=self.factory_root).select_profile(build_profile)
            if selected.get("profile_id") == CHARACTER_GM_PROFILE:
                from portable_character.service import PortableCharacterPackageService
                from project_store.service import ProjectStore
                candidate_zip = command5_report.get("candidate_zip")
                candidate_sha = command5_report.get("candidate_sha256")
                candidate = Path(candidate_zip).resolve() if candidate_zip else None
                diagnostics: list[dict[str, Any]] = []
                if command5_report.get("status") != "GM_MODEL_CANDIDATE_READY":
                    diagnostics.append({"code": "CHARACTER_GM_COMMAND5_REQUIRED", "status": command5_report.get("status")})
                if not candidate or not candidate.is_file():
                    diagnostics.append({"code": "CHARACTER_GM_CANDIDATE_MISSING"})
                elif candidate_sha != sha256_file(candidate):
                    diagnostics.append({"code": "CHARACTER_GM_CANDIDATE_HASH_MISMATCH", "expected": candidate_sha, "actual": sha256_file(candidate)})
                if not self.gm_screen_root:
                    diagnostics.append({"code": "BUNDLED_GM_SCREEN_REQUIRED"})
                if diagnostics:
                    raise FoundryError("COMMAND6_CHARACTER_GM_PREFLIGHT_FAILED", "The Character/GM Command 6 preflight failed.", details=diagnostics)
                output_zip = (output_dir if output_dir.suffix.lower() == ".zip" else output_dir / "C1A_Clean_Fire_Qi_Proof_Character.zip").resolve()
                output_zip.parent.mkdir(parents=True, exist_ok=True)
                project_export_path = output_zip.parent / f"{project_id}.tianxia-project.zip"
                raw_project_export = self.db.settings.exports_dir / (project_export_path.stem + ".raw.zip")
                ProjectStore(self.db).export_project(project_id, filename=raw_project_export.name)
                PortableCharacterPackageService.canonicalize_project_export(raw_project_export, project_export_path)
                raw_project_export.unlink(missing_ok=True)
                consumer_identity = {
                    "package_sha256": GM_SCREEN_SHA256,
                    "consumer": "HF05ZUI-R2K.3-HF3-W1",
                    "importer": "app.js packageFileInput + pako",
                    "renderer": "r2i-phase2e.js 18-tab renderer",
                }
                projection_status = self.projections.status(project_id)
                projection_artifacts = {row["artifact_name"]: Path(row["path"]) for row in projection_status.get("artifacts", [])}
                from character_sheet.service import CharacterSheetService
                owner_sheet_path = Path(CharacterSheetService(self.db).sheet(project_id)["sheet_artifact"]["path"])
                package = PortableCharacterPackageService.build(
                    candidate_zip=candidate, project_export=project_export_path, output_zip=output_zip,
                    consumer_identity=consumer_identity, command6_identity={"status": "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS", "build_profile": CHARACTER_GM_PROFILE},
                    projection_artifacts=projection_artifacts, owner_sheet_path=owner_sheet_path,
                )
                harness = Path(__file__).resolve().parents[1] / "gm_export" / "exact_consumer_harness.py"
                # Chromium's Windows FileReader cannot open a package whose
                # fully-qualified path crosses the legacy MAX_PATH boundary,
                # even though Python can build, audit, and hash that same
                # artifact.  The production output remains at output_zip;
                # give the exact browser consumer a byte-identical short-path
                # copy so the verification tests the package contents rather
                # than the host staging path.
                with tempfile.TemporaryDirectory(prefix="tianxia-gm-consumer-") as harness_temp:
                    harness_package = Path(harness_temp) / output_zip.name
                    harness_report_path = Path(harness_temp) / "Exact_Bundled_GM_Source_Consumer_Report.json"
                    shutil.copy2(output_zip, harness_package)
                    harness_run = _run([str(helper_python_executable()), str(harness), "--package", str(harness_package), "--consumer-root", str(self.gm_screen_root), "--output", str(harness_report_path)], cwd=Path(__file__).resolve().parents[1], timeout=120)
                    consumer_report = json.loads(harness_report_path.read_text(encoding="utf-8")) if harness_report_path.is_file() else {"status": "GM_SCREEN_SOURCE_CONSUMER_FAILED", "harness_run": harness_run}
                    if consumer_report:
                        consumer_report["package_path"] = str(output_zip)
                        consumer_report["harness_package_path"] = str(harness_package)
                        consumer_report["harness_package_path_strategy"] = "BYTE_IDENTICAL_SHORT_PATH_COPY"
                consumer_report["harness_run"] = harness_run
                status = "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS" if harness_run.get("exit_code") == 0 and consumer_report.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED" else "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_FAILED"
                report = {
                    "schema_version": "TianxiaFoundry.Command6CharacterGMVerification.v1",
                    "project_id": project_id, "projection_id": projection_id, "status": status,
                    "build_profile": CHARACTER_GM_PROFILE, "build_profile_contract_sha256": profile_contract_sha,
                    "candidate_zip": str(candidate), "candidate_sha256": candidate_sha,
                    "candidate_unchanged": sha256_file(candidate) == candidate_sha,
                    "portable_character_zip": str(output_zip), "portable_character_sha256": package.get("sha256"),
                    "portable_package_audit": package, "consumer_report": consumer_report,
                    "gm_screen_source_consumer_status": consumer_report.get("status"),
                    "factory_clean_import_status": "PENDING_SEPARATE_CLEAN_IMPORT_PROOF",
                    "gm_export_available": False,
                    "native_or_interactive_acceptance": "NOT_RUN",
                    "combat": "NOT_ATTEMPTED", "command5_rerun": False,
                    "legacy_full_execution_acceptance": "DIAGNOSTIC_NOT_CLAIMED",
                }
                with self.db.transaction() as conn:
                    conn.execute("UPDATE projection_runs SET command6_status=? WHERE projection_id=?", (status, projection_id))
                    conn.execute("UPDATE projects SET consumer_verification_status=? WHERE project_id=?", (status, project_id))
                if status != "COMMAND_6_CHARACTER_GM_SOURCE_CONSUMER_PASS":
                    output_zip.unlink(missing_ok=True)
                    raise FoundryError("COMMAND6_CHARACTER_GM_CONSUMER_FAILED", "The exact bundled GM Screen source consumer rejected the portable package.", details=report)
                return report
            if selected.get("profile_id") != LEGACY_PROFILE:
                raise FoundryError("FACTORY_BUILD_PROFILE_UNKNOWN", "The requested Factory build profile is not supported.", details={"requested": build_profile})
        candidate_zip = command5_report.get("candidate_zip")
        if command5_report.get("status") != "COMMAND_5_GM_SCREEN_CANDIDATE_READY" or not candidate_zip:
            raise FoundryError("COMMAND5_REQUIRED", "Command 6 requires a successful Command 5 candidate.")
        candidate_path = Path(candidate_zip).resolve()
        expected_candidate_sha256 = command5_report.get("candidate_sha256")
        tool = self.factory_root / "07_TOOLS" / "run_command6.py"
        output_zip = (output_dir if output_dir.suffix.lower() == ".zip" else output_dir / "released.zip").resolve()
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        command = [str(helper_python_executable()), str(tool), "--factory-root", str(self.factory_root), "--workspace", str(workspace), "--candidate", str(candidate_path), "--output", str(output_zip)]
        if self.gm_screen_root:
            command += ["--gm-screen", str(self.gm_screen_root)]

        diagnostics: list[dict[str, Any]] = []
        candidate_exists_before = candidate_path.is_file()
        candidate_sha256_before = sha256_file(candidate_path) if candidate_exists_before else None
        candidate_bytes_before = candidate_path.stat().st_size if candidate_exists_before else None
        command5_candidate_hash_matches = (
            isinstance(expected_candidate_sha256, str)
            and len(expected_candidate_sha256) == 64
            and expected_candidate_sha256 == candidate_sha256_before
        )
        distinct_output_path = candidate_path != output_zip
        output_path_is_usable = not output_zip.exists() or output_zip.is_file()

        if not candidate_exists_before:
            diagnostics.append({"code": "COMMAND5_CANDIDATE_MISSING", "path": str(candidate_path)})
        if not command5_candidate_hash_matches:
            diagnostics.append(
                {
                    "code": "COMMAND5_CANDIDATE_HASH_MISMATCH",
                    "expected_sha256": expected_candidate_sha256,
                    "actual_sha256": candidate_sha256_before,
                }
            )
        if not distinct_output_path:
            diagnostics.append({"code": "COMMAND6_OUTPUT_ALIASES_CANDIDATE", "path": str(output_zip)})
        if not output_path_is_usable:
            diagnostics.append({"code": "COMMAND6_OUTPUT_PATH_IS_NOT_A_FILE", "path": str(output_zip)})

        preflight_passed = not diagnostics
        if preflight_passed:
            # A previous run must never be accepted as evidence for this run.
            if output_zip.exists():
                output_zip.unlink()
            result = _run(command, cwd=self.factory_root, timeout=600)
        else:
            result = {
                "command": command,
                "cwd": str(self.factory_root),
                "exit_code": None,
                "duration_seconds": 0.0,
                "stdout": "",
                "stderr": "Command 6 skipped because candidate-integrity preflight failed.",
                "skipped": True,
            }

        candidate_exists_after = candidate_path.is_file()
        candidate_sha256_after = sha256_file(candidate_path) if candidate_exists_after else None
        candidate_bytes_after = candidate_path.stat().st_size if candidate_exists_after else None
        candidate_unchanged = (
            candidate_exists_before
            and candidate_exists_after
            and candidate_sha256_before == candidate_sha256_after
            and candidate_bytes_before == candidate_bytes_after
        )
        released_zip_exists = output_zip.is_file()
        released_sha256 = sha256_file(output_zip) if released_zip_exists else None
        released_bytes = output_zip.stat().st_size if released_zip_exists else None
        byte_identical_candidate_release = (
            candidate_unchanged
            and released_zip_exists
            and candidate_sha256_before == released_sha256
            and candidate_bytes_before == released_bytes
            and _files_are_byte_identical(candidate_path, output_zip)
        )

        if preflight_passed and result["exit_code"] != 0:
            diagnostics.append({"code": "COMMAND6_VENDOR_TOOL_FAILED", "exit_code": result["exit_code"], "stderr": result["stderr"]})
        if preflight_passed and not candidate_unchanged:
            diagnostics.append(
                {
                    "code": "COMMAND5_CANDIDATE_MUTATED_DURING_COMMAND6",
                    "sha256_before": candidate_sha256_before,
                    "sha256_after": candidate_sha256_after,
                    "bytes_before": candidate_bytes_before,
                    "bytes_after": candidate_bytes_after,
                }
            )
        if preflight_passed and not released_zip_exists:
            diagnostics.append({"code": "COMMAND6_RELEASED_ZIP_MISSING", "path": str(output_zip)})
        if preflight_passed and released_zip_exists and not byte_identical_candidate_release:
            diagnostics.append(
                {
                    "code": "COMMAND6_RELEASE_NOT_BYTE_IDENTICAL_TO_CANDIDATE",
                    "candidate_sha256": candidate_sha256_before,
                    "released_sha256": released_sha256,
                    "candidate_bytes": candidate_bytes_before,
                    "released_bytes": released_bytes,
                }
            )

        causal_checks_passed = (
            preflight_passed
            and result["exit_code"] == 0
            and command5_candidate_hash_matches
            and candidate_unchanged
            and released_zip_exists
            and byte_identical_candidate_release
        )
        status = (
            "SIMULATED_CONSUMER_PASS_REAL_GMSCREEN_ACCEPTANCE_REQUIRED"
            if causal_checks_passed
            else "COMMAND_6_SIMULATION_FAILED"
        )
        report = {
            "schema_version": "TianxiaFoundry.Command6ProjectionVerification.v2",
            "project_id": project_id,
            "projection_id": projection_id,
            "status": status,
            "run": result,
            "candidate_zip": str(candidate_path),
            "expected_command5_candidate_sha256": expected_candidate_sha256,
            "candidate_sha256": candidate_sha256_before,
            "candidate_sha256_before": candidate_sha256_before,
            "candidate_sha256_after": candidate_sha256_after,
            "candidate_bytes": candidate_bytes_before,
            "candidate_bytes_before": candidate_bytes_before,
            "candidate_bytes_after": candidate_bytes_after,
            "command5_candidate_hash_matches": command5_candidate_hash_matches,
            "candidate_unchanged": candidate_unchanged,
            "output_zip": str(output_zip),
            "released_zip_exists": released_zip_exists,
            "released_sha256": released_sha256,
            "released_bytes": released_bytes,
            "byte_identical_candidate_release": byte_identical_candidate_release,
            "causal_checks_passed": causal_checks_passed,
            "diagnostics": diagnostics,
            "real_installed_gm_screen_acceptance": False,
        }
        with self.db.transaction() as conn:
            conn.execute("UPDATE projection_runs SET command6_status=? WHERE projection_id=?", (status, projection_id))
            conn.execute("UPDATE projects SET consumer_verification_status=? WHERE project_id=?", (status, project_id))
        return report
