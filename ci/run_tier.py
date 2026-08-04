from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from common import (
    APP_ROOT,
    BASELINE_PATH,
    CLASSIFICATIONS,
    REPOSITORY_ROOT,
    StageRecorder,
    read_json,
    run_logged_command,
    runtime_versions,
    utc_now,
    write_json,
)


EXPECTED_CATALOG_COMMITMENT = "b53d36b6da5f3d8ead46e01cd07bbfc0f80e35043e7f3ef0f2e11d5fb79e35df"


@dataclass(frozen=True)
class CommandStage:
    name: str
    command: Sequence[str]
    timeout_seconds: int


def pytest_command(output: Path, report_name: str, tests: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--tb=short",
        "--basetemp=" + str(output / "pytest-tmp"),
        f"--junitxml={output / 'junit' / report_name}",
        *tests,
    ]


def fast_stages(output: Path, node: str) -> list[CommandStage]:
    run_a = output / "catalog" / "run-a"
    run_b = output / "catalog" / "run-b"
    for target in (run_a, run_b):
        if target.exists():
            raise RuntimeError(f"CI output root must be clean: {target}")
    compiler = APP_ROOT / "catalog_authority" / "cat3" / "compiler.py"
    verifier = APP_ROOT / "catalog_authority" / "cat3" / "verify_determinism.py"
    matrices = APP_ROOT / "catalog_authority" / "cat3" / "generate_acceptance_matrices.py"
    focused = (
        "tests/test_combat_battle_history.py",
        "tests/test_windows_portable_packaging.py",
    )
    return [
        CommandStage(
            "source_verification",
            [sys.executable, str(REPOSITORY_ROOT / "ci" / "verify_source.py"), "--output", str(output / "source-verification.json")],
            300,
        ),
        CommandStage("python_compile", [sys.executable, "-m", "compileall", "-q", str(APP_ROOT)], 300),
        CommandStage(
            "javascript_syntax",
            [sys.executable, str(REPOSITORY_ROOT / "ci" / "check_javascript.py"), "--node", node, "--output", str(output / "javascript-syntax.json")],
            120,
        ),
        CommandStage(
            "json_schema_validation",
            [sys.executable, str(REPOSITORY_ROOT / "ci" / "validate_json_schemas.py"), "--output", str(output / "json-schema-validation.json")],
            300,
        ),
        CommandStage("catalog_compile_a", [sys.executable, str(compiler), "--source-root", str(APP_ROOT), "--output-root", str(run_a)], 600),
        CommandStage("catalog_compile_b", [sys.executable, str(compiler), "--source-root", str(APP_ROOT), "--output-root", str(run_b)], 600),
        CommandStage(
            "catalog_comparison",
            [
                sys.executable,
                str(verifier),
                "--source-root",
                str(APP_ROOT),
                "--run-a",
                str(run_a),
                "--run-b",
                str(run_b),
                "--report",
                str(output / "catalog-determinism.json"),
            ],
            300,
        ),
        CommandStage(
            "prerequisite_scope_matrices",
            [sys.executable, str(matrices), "--source-root", str(APP_ROOT), "--output-root", str(output / "catalog" / "acceptance")],
            300,
        ),
        CommandStage("focused_tests", pytest_command(output, "fast-focused.xml", focused), 900),
        CommandStage(
            "ci_contract",
            [sys.executable, "-m", "unittest", "discover", "-s", str(REPOSITORY_ROOT / "ci" / "tests"), "-v"],
            180,
        ),
    ]


def integration_stages(output: Path) -> list[CommandStage]:
    return [
        CommandStage(
            "source_verification",
            [sys.executable, str(REPOSITORY_ROOT / "ci" / "verify_source.py"), "--output", str(output / "source-verification.json")],
            300,
        ),
        CommandStage(
            "project_persistence",
            pytest_command(output, "project-persistence.xml", ("tests/test_cat3_p1r_persistence.py",)),
            900,
        ),
        CommandStage(
            "frozen_choices_and_finalization",
            pytest_command(
                output,
                "frozen-choices-finalization.xml",
                ("tests/test_cg1_character_creation_modes.py", "tests/test_w5_production_receipt_identity.py"),
            ),
            900,
        ),
        CommandStage(
            "portable_export_clean_import_gm",
            pytest_command(
                output,
                "portable-gm-chain.xml",
                (
                    "tests/test_c2ar1_owner_projection.py",
                    "tests/test_c2b2_gm_tactical_authoring_workspace.py",
                    "tests/test_c2b3_stage_aware_command5.py",
                    "tests/test_c2c1_command6_portable_character.py",
                    "tests/test_windows_portable_packaging.py",
                ),
            ),
            1800,
        ),
        CommandStage(
            "strict_pack_locks_and_historical_fixtures",
            pytest_command(
                output,
                "pack-locks-history.xml",
                ("tests/test_c3d_p1_portable_live_combat.py", "tests/test_c3d_p1r_historical_compatibility.py"),
            ),
            1800,
        ),
        CommandStage(
            "real_production_services",
            pytest_command(output, "real-production-services.xml", ("tests/test_w5_p1r_r1_production_endpoints.py",)),
            1800,
        ),
    ]


def verify_catalog(output: Path) -> None:
    report = read_json(output / "catalog-determinism.json")
    actual = report.get("registry_commitment_sha256")
    if report.get("result") != "PASS" or actual != EXPECTED_CATALOG_COMMITMENT:
        raise AssertionError(
            f"Catalog commitment mismatch: expected {EXPECTED_CATALOG_COMMITMENT}, actual {actual}"
        )
    write_json(
        output / "commitments.json",
        {
            "schema": "Tianxia.CI1P1.Commitments.v1",
            "source_tree_sha256": read_json(BASELINE_PATH)["application_source"]["source_tree_commitment_sha256"],
            "catalog_registry_sha256": actual,
            "determinism_report": "catalog-determinism.json",
        },
    )


def classify_failure(stage: str, exit_code: int) -> str:
    if exit_code in (126, 127):
        return "HARNESS_FAILURE"
    if exit_code in (-9, -15, 124, 137):
        return "INFRASTRUCTURE_BLOCKER"
    if stage == "ci_contract":
        return "HARNESS_FAILURE"
    if stage in {
        "focused_tests",
        "rendered_browser",
        "project_persistence",
        "frozen_choices_and_finalization",
        "portable_export_clean_import_gm",
        "strict_pack_locks_and_historical_fixtures",
        "real_production_services",
    }:
        if exit_code in (3, 4, 5):
            return "HARNESS_FAILURE"
        if exit_code == 2:
            return "INFRASTRUCTURE_BLOCKER"
    return "PRODUCT_FAILURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tier", choices=("fast", "integration"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", default=shutil.which("node") or "node")
    parser.add_argument("--seed-timings", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "logs").mkdir(exist_ok=True)
    (output / "junit").mkdir(exist_ok=True)
    os.environ.setdefault("PYTHONUTF8", "1")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(APP_ROOT)
    environment["PYTHONPYCACHEPREFIX"] = str(output / "pycache")
    environment["TIANXIA_VERIFIED_NODE"] = args.node
    recorder = StageRecorder(output / "stage-timings.json", seed_ndjson=args.seed_timings)
    stages = fast_stages(output, args.node) if args.tier == "fast" else integration_stages(output)
    classification = "PASS"
    failed_stage = None
    failed_command = None
    failed_exit_code = None
    for spec in stages:
        exit_code = run_logged_command(
            recorder=recorder,
            stage=spec.name,
            command=spec.command,
            cwd=APP_ROOT if spec.name not in {"source_verification", "javascript_syntax", "json_schema_validation", "ci_contract"} else REPOSITORY_ROOT,
            log_path=output / "logs" / f"{spec.name}.log",
            env=environment,
            timeout_seconds=spec.timeout_seconds,
        )
        if exit_code:
            classification = classify_failure(spec.name, exit_code)
            failed_stage = spec.name
            failed_command = list(spec.command)
            failed_exit_code = exit_code
            break
        if args.tier == "fast" and spec.name == "catalog_comparison":
            try:
                with recorder.measure("registry_commitment", "verify exact accepted CAT3 registry commitment"):
                    verify_catalog(output)
            except Exception as exc:
                classification = "PRODUCT_FAILURE"
                failed_stage = "registry_commitment"
                failed_command = ["verify_catalog"]
                failed_exit_code = 1
                (output / "logs" / "registry_commitment.log").write_text(str(exc) + "\n", encoding="utf-8")
                break
    if classification == "PASS" and args.tier == "integration":
        baseline = read_json(BASELINE_PATH)
        write_json(
            output / "commitments.json",
            {
                "schema": "Tianxia.CI1P1.Commitments.v1",
                "source_tree_sha256": baseline["application_source"]["source_tree_commitment_sha256"],
                "catalog_registry_sha256": baseline["catalog"]["registry_commitment_sha256"],
            },
        )
    classification_report = {
        "schema": "Tianxia.CI1P1.FailureClassification.v1",
        "tier": args.tier,
        "classified_at_utc": utc_now(),
        "classification": classification,
        "failing_stage": failed_stage,
        "command": failed_command,
        "exit_code": failed_exit_code,
        "runner_os": os.environ.get("RUNNER_OS") or sys.platform,
        "product_assertion_reached": classification == "PRODUCT_FAILURE",
    }
    write_json(output / "classification.json", classification_report)
    write_json(output / "runtime-versions.json", runtime_versions(args.node))
    write_json(
        output / "summary.json",
        {
            "schema": "Tianxia.CI1P1.WorkflowSummary.v1",
            "tier": args.tier,
            "status": classification,
            "completed_at_utc": utc_now(),
            "classification": classification_report,
            "stage_timings": "stage-timings.json",
            "runtime_versions": "runtime-versions.json",
            "commitments": "commitments.json",
        },
    )
    print(json.dumps(classification_report, sort_keys=True))
    if classification not in CLASSIFICATIONS:
        raise AssertionError(classification)
    return 0 if classification == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
