from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


INVENTORY_NAME = "SHA256SUMS.txt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    return all(part not in {"", ".", ".."} for part in PurePosixPath(value).parts)


def application_records(application: Path) -> dict[str, dict[str, Any]]:
    application = application.resolve()
    inventory = application / INVENTORY_NAME
    return {
        path.relative_to(application).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(application.rglob("*"), key=lambda item: item.relative_to(application).as_posix())
        if path.is_file() and path != inventory
    }


def generate(application: Path) -> None:
    records = application_records(application)
    lines = [f"{record['sha256']}  {relative}" for relative, record in records.items()]
    (application / INVENTORY_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify(application: Path) -> dict[str, Any]:
    application = application.resolve()
    inventory = application / INVENTORY_NAME
    if not inventory.is_file():
        raise RuntimeError(f"missing {INVENTORY_NAME}")
    declared: dict[str, str] = {}
    declared_order: list[str] = []
    for number, line in enumerate(inventory.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if len(line) < 67 or line[64:66] != "  ":
            raise RuntimeError(f"malformed checksum record at line {number}")
        digest, relative = line[:64].lower(), line[66:]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError(f"malformed SHA-256 at line {number}")
        if relative in declared or not safe_relative_path(relative):
            raise RuntimeError(f"unsafe or duplicate checksum path: {relative}")
        declared[relative] = digest
        declared_order.append(relative)
    actual = application_records(application)
    missing = sorted(set(declared) - set(actual))
    unexpected = sorted(set(actual) - set(declared))
    hash_mismatches = [
        {
            "path": relative,
            "declared_sha256": declared[relative],
            "actual_sha256": actual[relative]["sha256"],
        }
        for relative in sorted(set(declared).intersection(actual))
        if declared[relative] != actual[relative]["sha256"]
    ]
    version_relative = "VERSION.json"
    version = {
        "present": version_relative in actual,
        "declared_sha256": declared.get(version_relative),
        "actual_sha256": actual.get(version_relative, {}).get("sha256"),
    }
    version["matches"] = bool(
        version["present"] and version["declared_sha256"] == version["actual_sha256"]
    )
    sorted_paths = declared_order == sorted(declared_order)
    status = "PASS" if not missing and not unexpected and not hash_mismatches and sorted_paths and version["matches"] else "FAIL"
    return {
        "schema": "Tianxia.WIN1P1R2R2.ApplicationChecksumVerification.v1",
        "status": status,
        "application_root": str(application),
        "inventory": INVENTORY_NAME,
        "inventory_excludes_itself": INVENTORY_NAME not in declared,
        "deterministic_path_order": sorted_paths,
        "declared_count": len(declared),
        "actual_count": len(actual),
        "checked_count": len(set(declared).intersection(actual)),
        "missing_count": len(missing),
        "unexpected_count": len(unexpected),
        "hash_mismatch_count": len(hash_mismatches),
        "missing": missing,
        "unexpected": unexpected,
        "hash_mismatches": hash_mismatches,
        "version_json": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.generate:
            generate(args.application)
        report = verify(args.application)
    except Exception as exc:
        report = {
            "schema": "Tianxia.WIN1P1R2R2.ApplicationChecksumVerification.v1",
            "status": "FAIL",
            "error": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
