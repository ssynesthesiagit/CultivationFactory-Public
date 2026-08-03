from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(source_root: Path, evidence_root: Path) -> dict[str, Any]:
    failures: list[str] = []
    pack_path = source_root / "catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json"
    map_path = source_root / "catalog/typed_authority/C1A_Exact_Source_Map_v1.json"
    pack = _load(pack_path)
    source_map = _load(map_path)
    if len(pack.get("records", [])) != 27:
        failures.append("typed authority pack must contain exactly 27 records")
    if len(source_map.get("records", [])) != 27:
        failures.append("source map must contain exactly 27 records")
    if pack.get("pack_id") != source_map.get("pack_id"):
        failures.append("pack/source-map pack_id mismatch")
    map_records = source_map.get("records", {})
    if isinstance(map_records, dict):
        iterable = map_records.items()
    else:
        iterable = ((row.get("record_id"), row) for row in map_records)
    for record_id, row in iterable:
        if not record_id or not isinstance(row, dict) or not row.get("anchor") or not row.get("path") or not row.get("source_hash"):
            failures.append(f"source map record {record_id!r} lacks anchor/path/source_hash")
    validation = _load(evidence_root / "STAGE1_STAGE2/validation.json")
    blocker_list = validation.get("blockers") or validation.get("blocker_report", {}).get("blockers", [])
    if validation.get("valid") is not True or blocker_list:
        failures.append("clean proof proposal is not valid with zero blockers")
    rebuild = _load(evidence_root / "SUCCESS/deterministic_rebuild_comparison.json")
    rebuild_checks = {key: value for key, value in rebuild.items() if key.endswith("_equal") or key.endswith("_both")}
    if not rebuild_checks or not all(value is True for value in rebuild_checks.values()):
        failures.append("deterministic rebuild comparison failed")
    imports = _load(evidence_root / "IMPORTS/two_clean_import_comparison.json")
    if imports.get("all_mechanical_hashes_identical") is not True:
        failures.append("two clean imports did not reproduce the same mechanical state")
    invalid = _load(evidence_root / "FAILURE_PATHS/invalid_route_summary.json")
    if invalid.get("all_expected_blockers_present") is not True or invalid.get("all_cases_rejected") is not True:
        failures.append("invalid-route fail-closed matrix failed")
    route_matrix = _load(evidence_root / "FAILURE_PATHS/creation_route_completion_matrix.json")
    if route_matrix.get("passed") is not True:
        failures.append("exact-one creation-route completion matrix failed")
    mismatch = _load(evidence_root / "FAILURE_PATHS/invalid_mismatched_ai_bootstrap_pair.json")
    if mismatch.get("valid") is not False or mismatch.get("expected_present") is not True:
        failures.append("mismatched AI-bootstrap pair was not rejected")
    non_ai = _load(evidence_root / "FAILURE_PATHS/invalid_ai_bootstrap_on_non_ai_project.json")
    if non_ai.get("valid") is not False or non_ai.get("expected_present") is not True:
        failures.append("AI-bootstrap use on a non-AI project was not rejected")
    source_verification = _load(evidence_root / "DIAGNOSTICS/exact_source_map_verification.json")
    if source_verification.get("passed") is not True:
        failures.append("exact source-map/hash/anchor verification failed")
    wrong_nonce = _load(evidence_root / "FAILURE_PATHS/failed_challenge_no_mutation.json")
    if wrong_nonce.get("code") != "APPROVAL_CHALLENGE_NONCE_INVALID" or wrong_nonce.get("project_visible_state_equal") is not True:
        failures.append("wrong-nonce rollback evidence failed")
    crash = _load(evidence_root / "FAILURE_PATHS/simulated_crash_atomic_rollback.json")
    if crash.get("code") != "STAGE2_ATOMIC_COMMIT_ROLLED_BACK" or crash.get("project_visible_state_equal") is not True:
        failures.append("simulated exception rollback evidence failed")
    timeout = _load(evidence_root / "HARD_TIMEOUT/hard_timeout_rollback_report.json")
    if timeout.get("project_visible_snapshot_byte_identical") is not True:
        failures.append("hard-timeout mutation evidence failed")
    timeout_recursive = _load(evidence_root / "HARD_TIMEOUT/recursive_project_directory_hashes.json")
    if timeout_recursive.get("canonical_project_directory_byte_identical") is not True:
        failures.append("hard-timeout recursive canonical project-directory hashes changed")
    stale1 = _load(evidence_root / "FAILURE_PATHS/stale_challenge_rejection_1.json")
    stale2 = _load(evidence_root / "FAILURE_PATHS/stale_challenge_rejection_2.json")
    if stale1.get("code") != "APPROVAL_CHALLENGE_PROCESS_EPOCH_CHANGED" or stale2.get("code") != "APPROVAL_CHALLENGE_INVALIDATED":
        failures.append("stale challenge was not permanently rejected")
    return {
        "schema_version": "TianxiaFoundry.C1A1CheckpointValidation.v1",
        "source_root": str(source_root),
        "evidence_root": str(evidence_root),
        "typed_authority_pack_sha256": _sha256(pack_path),
        "exact_source_map_sha256": _sha256(map_path),
        "failures": failures,
        "passed": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.source_root.resolve(), args.evidence_root.resolve())
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
