from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*]|[\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
POLICY_SCHEMA = "TianxiaFactory.R6_6.NativeBuildExternalInputPolicy.v2"


class InputVerificationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_relative_path(value: str) -> str:
    if not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise InputVerificationError(f"unsafe relative path: {value!r}")
    pure = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise InputVerificationError(f"unsafe relative path: {value!r}")
    for part in pure.parts:
        if part.endswith((".", " ")) or WINDOWS_FORBIDDEN_RE.search(part):
            raise InputVerificationError(f"Windows-unsafe path component: {part!r}")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED:
            raise InputVerificationError(f"Windows-reserved path component: {part!r}")
        if unicodedata.normalize("NFC", part) != part:
            raise InputVerificationError(f"non-NFC path component: {part!r}")
    return pure.as_posix()


def parse_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise InputVerificationError(f"missing checksum manifest: {path}")
    declared: dict[str, str] = {}
    folded: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise InputVerificationError(f"malformed checksum line {line_number}: {line!r}")
        digest, relative = match.groups()
        relative = validate_relative_path(relative)
        if relative in declared:
            raise InputVerificationError(f"duplicate checksum path: {relative}")
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in folded:
            raise InputVerificationError(f"case-fold/NFC checksum collision: {folded[key]} vs {relative}")
        folded[key] = relative
        declared[relative] = digest
    return declared


def load_policy(root: Path) -> dict[str, Any]:
    path = root / "EXTERNAL_INPUT_POLICY.json"
    if not path.is_file():
        raise InputVerificationError("missing EXTERNAL_INPUT_POLICY.json")
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InputVerificationError("invalid EXTERNAL_INPUT_POLICY.json") from exc
    if policy.get("schema") != POLICY_SCHEMA:
        raise InputVerificationError("unsupported external-input policy schema")
    source = policy.get("source") or {}
    validate_relative_path(str(source.get("root") or ""))
    if not HASH_RE.fullmatch(str(source.get("manifest_sha256") or "")):
        raise InputVerificationError("invalid sealed source manifest hash")
    rows = policy.get("external_inputs")
    if not isinstance(rows, list) or not rows:
        raise InputVerificationError("external input policy is empty")
    seen: set[str] = set()
    folded: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InputVerificationError("external input row is not an object")
        relative = validate_relative_path(str(row.get("path") or ""))
        digest = str(row.get("sha256") or "")
        kind = row.get("kind")
        if not HASH_RE.fullmatch(digest) or kind not in {"zip", "wheel"}:
            raise InputVerificationError(f"invalid external input policy row: {relative}")
        if relative in seen:
            raise InputVerificationError(f"duplicate external input path: {relative}")
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in folded:
            raise InputVerificationError(f"case-fold/NFC external-input collision: {folded[key]} vs {relative}")
        seen.add(relative)
        folded[key] = relative
        if kind == "zip" and not relative.lower().endswith(".zip"):
            raise InputVerificationError(f"ZIP policy path has wrong extension: {relative}")
        if kind == "wheel" and not relative.lower().endswith(".whl"):
            raise InputVerificationError(f"wheel policy path has wrong extension: {relative}")
    return policy


def _inventory(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    folded: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InputVerificationError(f"symbolic links are not permitted: {path}")
        if not path.is_file():
            continue
        relative = validate_relative_path(path.relative_to(root).as_posix())
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in folded:
            raise InputVerificationError(f"case-fold/NFC filesystem collision: {folded[key]} vs {relative}")
        folded[key] = relative
        files[relative] = path
    return files


def verify_package(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    policy = load_policy(root)
    declared = parse_manifest(root / "SHA256SUMS.txt")
    external_rows = {row["path"]: row for row in policy["external_inputs"]}
    files = _inventory(root)
    actual_sealed = set(files) - {"SHA256SUMS.txt"} - set(external_rows)
    if actual_sealed != set(declared):
        missing = sorted(set(declared) - actual_sealed)
        extra = sorted(actual_sealed - set(declared))
        raise InputVerificationError(f"sealed package checksum coverage mismatch; missing={missing}, extra={extra}")
    for relative, expected in declared.items():
        actual = sha256_file(files[relative])
        if actual != expected:
            raise InputVerificationError(f"sealed package checksum mismatch: {relative}")

    source = policy["source"]
    source_root = root / source["root"]
    source_manifest = source_root / "SHA256SUMS.txt"
    if sha256_file(source_manifest) != source["manifest_sha256"]:
        raise InputVerificationError("sealed source manifest identity mismatch")
    source_declared = parse_manifest(source_manifest)
    source_files = _inventory(source_root)
    source_actual = set(source_files) - {"SHA256SUMS.txt"}
    if source_actual != set(source_declared):
        raise InputVerificationError("sealed source checksum coverage mismatch")
    for relative, expected in source_declared.items():
        if sha256_file(source_files[relative]) != expected:
            raise InputVerificationError(f"sealed source checksum mismatch: {relative}")

    missing_external = sorted(set(external_rows) - set(files))
    if missing_external:
        raise InputVerificationError(f"required external inputs are missing: {missing_external}")
    for relative, row in external_rows.items():
        path = files[relative]
        if sha256_file(path) != row["sha256"]:
            raise InputVerificationError(f"external input SHA-256 mismatch: {relative}")
        if row["kind"] == "zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    bad = archive.testzip()
                    if bad is not None:
                        raise InputVerificationError(f"external ZIP CRC failure in {relative}: {bad}")
            except zipfile.BadZipFile as exc:
                raise InputVerificationError(f"external input is not a valid ZIP: {relative}") from exc
    return {
        "schema": "TianxiaFactory.R6_6.NativeBuildInputVerification.v2",
        "status": "PASS",
        "ready_for_build": True,
        "sealed_file_count": len(declared),
        "external_input_count": len(external_rows),
        "wheel_count": sum(row["kind"] == "wheel" for row in external_rows.values()),
        "zip_count": sum(row["kind"] == "zip" for row in external_rows.values()),
        "source_manifest_sha256": source["manifest_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = verify_package(args.package_root)
    except Exception as exc:
        report = {
            "schema": "TianxiaFactory.R6_6.NativeBuildInputVerification.v2",
            "status": "FAIL",
            "ready_for_build": False,
            "error": str(exc),
        }
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 1
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
