from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import (
    ACCEPTED_SOURCE_SUMS,
    APP_ROOT,
    BASELINE_PATH,
    REPOSITORY_ROOT,
    sha256_file,
    utc_now,
    write_json,
)


def load_inventory(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if len(line) < 67 or line[64:66] != "  ":
            raise ValueError(f"Malformed checksum record at line {number}")
        digest, relative = line[:64].lower(), line[66:].replace("\\", "/")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"Malformed SHA-256 at line {number}")
        if relative in records:
            raise ValueError(f"Duplicate checksum path: {relative}")
        candidate = (APP_ROOT / Path(relative)).resolve()
        if APP_ROOT.resolve() not in candidate.parents:
            raise ValueError(f"Unsafe checksum path: {relative}")
        records[relative] = digest
    return records


def verify() -> dict[str, Any]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    source = baseline["application_source"]
    inventory_commitment = sha256_file(ACCEPTED_SOURCE_SUMS)
    expected = load_inventory(ACCEPTED_SOURCE_SUMS)
    actual = {
        path.relative_to(APP_ROOT).as_posix(): path
        for path in APP_ROOT.rglob("*")
        if path.is_file()
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatches = []
    total_bytes = 0
    for relative, path in sorted(actual.items()):
        total_bytes += path.stat().st_size
        if relative in expected:
            digest = sha256_file(path)
            if digest != expected[relative]:
                mismatches.append(
                    {"path": relative, "expected_sha256": expected[relative], "actual_sha256": digest}
                )
    checks = {
        "checksum_inventory_commitment": inventory_commitment
        == source["source_tree_commitment_sha256"],
        "file_count": len(actual) == int(source["file_count"]),
        "total_bytes": total_bytes == int(source["total_bytes"]),
        "no_missing_files": not missing,
        "no_extra_files": not extra,
        "all_file_hashes": not mismatches,
    }
    return {
        "schema": "Tianxia.CI1P1.SourceVerification.v1",
        "verified_at_utc": utc_now(),
        "status": "PASS" if all(checks.values()) else "PRODUCT_FAILURE",
        "repository_root": str(REPOSITORY_ROOT),
        "application_directory": "APP",
        "source_tree_commitment_sha256": inventory_commitment,
        "catalog_registry_commitment_sha256": baseline["catalog"]["registry_commitment_sha256"],
        "file_count": len(actual),
        "total_bytes": total_bytes,
        "checks": checks,
        "missing": missing,
        "extra": extra,
        "hash_mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify()
    write_json(args.output.resolve(), report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
