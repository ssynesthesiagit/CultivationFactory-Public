from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from common import CLASSIFICATIONS, StageRecorder, read_json, runtime_versions, sha256_file, utc_now, write_json


MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 180 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--fallback-stage", default="dependency_setup")
    parser.add_argument("--seed-timings", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    started = time.perf_counter()
    timing_path = output / "stage-timings.json"
    timings = StageRecorder(
        timing_path,
        seed_ndjson=args.seed_timings if not timing_path.is_file() else None,
    )
    classification_path = output / "classification.json"
    if not classification_path.is_file():
        write_json(
            classification_path,
            {
                "schema": "Tianxia.CI1P1.FailureClassification.v1",
                "tier": args.tier,
                "classified_at_utc": utc_now(),
                "classification": "INFRASTRUCTURE_BLOCKER",
                "failing_stage": args.fallback_stage,
                "command": None,
                "exit_code": None,
                "runner_os": os.environ.get("RUNNER_OS") or sys.platform,
                "product_assertion_reached": False,
                "note": "The tier runner did not produce a classification; workflow setup or runner infrastructure failed first.",
            },
        )
    if not (output / "runtime-versions.json").is_file():
        write_json(output / "runtime-versions.json", runtime_versions(args.node))
    timings.record(
        stage="artifact_packaging",
        command="ci/finalize_artifacts.py",
        started_at_utc=started_at,
        ended_at_utc=utc_now(),
        elapsed_seconds=time.perf_counter() - started,
        status="PASS",
        exit_code=0,
    )
    records = []
    total_bytes = 0
    oversized = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "artifact-index.json":
            continue
        relative = path.relative_to(output).as_posix()
        size = path.stat().st_size
        total_bytes += size
        if size > MAX_FILE_BYTES:
            oversized.append({"path": relative, "bytes": size})
        records.append({"path": relative, "bytes": size, "sha256": sha256_file(path)})
    classification = read_json(classification_path)
    if classification.get("classification") not in CLASSIFICATIONS:
        raise AssertionError(f"Unknown classification: {classification.get('classification')}")
    index = {
        "schema": "Tianxia.CI1P1.ArtifactIndex.v1",
        "tier": args.tier,
        "generated_at_utc": utc_now(),
        "classification": classification["classification"],
        "bounded": False,
        "file_count": len(records),
        "total_bytes": total_bytes,
        "artifact_index_bytes": 0,
        "total_uploaded_bytes": total_bytes,
        "maximum_file_bytes": MAX_FILE_BYTES,
        "maximum_total_bytes": MAX_TOTAL_BYTES,
        "oversized": oversized,
        "records": records,
        "excluded": ["credentials", "API keys", "production UserData", "personal saves", "secret-bearing environment dumps"],
    }
    index_path = output / "artifact-index.json"
    for _ in range(4):
        write_json(index_path, index)
        index_bytes = index_path.stat().st_size
        total_uploaded_bytes = total_bytes + index_bytes
        bounded = not oversized and total_uploaded_bytes <= MAX_TOTAL_BYTES
        updated = dict(index)
        updated["artifact_index_bytes"] = index_bytes
        updated["total_uploaded_bytes"] = total_uploaded_bytes
        updated["bounded"] = bounded
        if updated == index:
            break
        index = updated
    write_json(index_path, index)
    bounded = bool(index["bounded"])
    print(json.dumps({"classification": classification["classification"], "bounded": bounded, "file_count": len(records), "total_bytes": total_bytes, "total_uploaded_bytes": index["total_uploaded_bytes"]}, sort_keys=True))
    return 0 if bounded else 1


if __name__ == "__main__":
    raise SystemExit(main())
