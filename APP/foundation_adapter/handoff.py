from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


EXPECTED_HANDOFF_SHA256 = "df80217c64c0808190c85531095e5e78aa96ff6808be369915f36fbb4189771c"
HANDOFF_ROOT = "Tianxia_Foundation_FactoryApp_Handoff_v1_0"
MANIFEST_PATH = "FOUNDATION_APP_HANDOFF_MANIFEST.json"
CHECKSUM_PATH = "SHA256SUMS.txt"
MAX_HANDOFF_ARCHIVE_BYTES = 16 * 1024 * 1024

CATALOG_PATHS = {
    "families": "04_CATALOG/Tianxia_Foundation_Families_v2.json",
    "expressions": "04_CATALOG/Tianxia_Foundation_Expressions_v2.json",
    "selection_index": "04_CATALOG/Tianxia_Foundation_Selection_Index_v2.json",
    "readable_projection": "04_CATALOG/Tianxia_Foundation_Readable_Projection_v2.json",
    "legacy_alias_map": "04_CATALOG/Tianxia_Foundation_Legacy_Alias_Map_v2.json",
}

_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


class FoundationHandoffError(ValueError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, *, path: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundationHandoffError("HANDOFF_JSON_INVALID", f"Invalid UTF-8 JSON at {path}.", path=path) from exc
    if not isinstance(value, dict):
        raise FoundationHandoffError("HANDOFF_JSON_ROOT_NOT_OBJECT", f"Expected an object at {path}.", path=path)
    return value


@dataclass(frozen=True)
class SourceBlob:
    logical_name: str
    handoff_path: str
    data: bytes
    sha256: str


@dataclass(frozen=True)
class FoundationHandoff:
    archive_path: Path
    archive_sha256: str
    root: str
    manifest: dict[str, Any]
    manifest_sha256: str
    checksum_manifest_sha256: str
    source_blobs: dict[str, SourceBlob]
    families_catalog: dict[str, Any]
    expressions_catalog: dict[str, Any]
    selection_index: dict[str, Any]
    readable_projection: dict[str, Any]
    legacy_alias_map: dict[str, Any]


def _safe_member_names(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise FoundationHandoffError("HANDOFF_UNSAFE_PATH", "The handoff contains an unsafe path.", path=name)
        if name in seen:
            raise FoundationHandoffError("HANDOFF_DUPLICATE_MEMBER", "The handoff contains a duplicate ZIP member.", path=name)
        seen.add(name)
        if not info.is_dir():
            names.append(name)
    return names


def _parse_checksum_manifest(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FoundationHandoffError("HANDOFF_CHECKSUMS_ENCODING", "SHA256SUMS.txt is not UTF-8.") from exc
    result: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not _HASH_RE.fullmatch(parts[0]) or not parts[1]:
            raise FoundationHandoffError(
                "HANDOFF_CHECKSUM_LINE_INVALID",
                "SHA256SUMS.txt contains an invalid row.",
                line=line_number,
            )
        if parts[1] in result:
            raise FoundationHandoffError("HANDOFF_CHECKSUM_DUPLICATE_PATH", "SHA256SUMS.txt repeats a path.", path=parts[1])
        result[parts[1]] = parts[0]
    return result


def load_foundation_handoff(
    archive_path: Path,
    *,
    expected_archive_sha256: str | None = EXPECTED_HANDOFF_SHA256,
) -> FoundationHandoff:
    """Load and cryptographically verify the immutable Foundation handoff.

    The outer digest, ZIP CRC, package manifest, checksum manifest, byte sizes,
    and every declared member hash are verified before any catalog object is
    returned to the adapter.
    """

    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise FoundationHandoffError("HANDOFF_NOT_FOUND", "Foundation handoff ZIP does not exist.", path=str(archive_path))
    archive_size = archive_path.stat().st_size
    if archive_size > MAX_HANDOFF_ARCHIVE_BYTES:
        raise FoundationHandoffError(
            "HANDOFF_ARCHIVE_TOO_LARGE",
            "Foundation handoff ZIP exceeds the bounded adapter input size.",
            bytes=archive_size,
            maximum_bytes=MAX_HANDOFF_ARCHIVE_BYTES,
        )
    archive_bytes = archive_path.read_bytes()
    archive_sha256 = _sha256(archive_bytes)
    if expected_archive_sha256 is not None and archive_sha256 != expected_archive_sha256.lower():
        raise FoundationHandoffError(
            "HANDOFF_ARCHIVE_HASH_MISMATCH",
            "Foundation handoff ZIP does not match the trusted digest.",
            expected=expected_archive_sha256.lower(),
            actual=archive_sha256,
        )

    try:
        # Parse the same immutable bytes whose outer digest was verified.  Do
        # not re-open the caller-controlled path after hashing it.
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise FoundationHandoffError("HANDOFF_ZIP_INVALID", "Foundation handoff is not a valid ZIP archive.") from exc
    with archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise FoundationHandoffError("HANDOFF_ZIP_CRC_FAILED", "Foundation handoff failed CRC validation.", path=bad_member)
        member_names = _safe_member_names(archive)
        roots = {PurePosixPath(name).parts[0] for name in member_names}
        if roots != {HANDOFF_ROOT}:
            raise FoundationHandoffError("HANDOFF_ROOT_MISMATCH", "Foundation handoff has an unexpected root.", roots=sorted(roots))

        def read(relative_path: str) -> bytes:
            member = f"{HANDOFF_ROOT}/{relative_path}"
            try:
                return archive.read(member)
            except KeyError as exc:
                raise FoundationHandoffError("HANDOFF_REQUIRED_FILE_MISSING", "Foundation handoff is missing a required file.", path=relative_path) from exc

        manifest_bytes = read(MANIFEST_PATH)
        checksum_bytes = read(CHECKSUM_PATH)
        manifest = _json(manifest_bytes, path=MANIFEST_PATH)
        if manifest.get("schema") != "Tianxia.FoundationFactoryAppHandoffManifest.v1":
            raise FoundationHandoffError("HANDOFF_MANIFEST_SCHEMA_UNSUPPORTED", "Unsupported Foundation handoff manifest schema.")
        if manifest.get("catalog") != "FOUNDATION46_RC2":
            raise FoundationHandoffError("HANDOFF_CATALOG_ID_UNSUPPORTED", "Unsupported Foundation catalog identity.")

        checksums = _parse_checksum_manifest(checksum_bytes)
        actual_relative = {
            str(PurePosixPath(name).relative_to(HANDOFF_ROOT))
            for name in member_names
        }
        expected_checksum_paths = actual_relative - {CHECKSUM_PATH}
        if set(checksums) != expected_checksum_paths:
            raise FoundationHandoffError(
                "HANDOFF_CHECKSUM_COVERAGE_MISMATCH",
                "SHA256SUMS.txt does not cover every non-checksum member exactly once.",
                missing=sorted(expected_checksum_paths - set(checksums)),
                unexpected=sorted(set(checksums) - expected_checksum_paths),
            )
        for relative_path, expected_hash in checksums.items():
            actual_hash = _sha256(read(relative_path))
            if actual_hash != expected_hash:
                raise FoundationHandoffError(
                    "HANDOFF_MEMBER_HASH_MISMATCH",
                    "A handoff member does not match SHA256SUMS.txt.",
                    path=relative_path,
                    expected=expected_hash,
                    actual=actual_hash,
                )

        manifest_files = manifest.get("files")
        if not isinstance(manifest_files, list):
            raise FoundationHandoffError("HANDOFF_MANIFEST_FILES_INVALID", "Handoff manifest files must be an array.")
        declared: dict[str, dict[str, Any]] = {}
        for row in manifest_files:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise FoundationHandoffError("HANDOFF_MANIFEST_FILE_ROW_INVALID", "Handoff manifest contains an invalid file row.")
            if row["path"] in declared:
                raise FoundationHandoffError("HANDOFF_MANIFEST_DUPLICATE_PATH", "Handoff manifest repeats a file path.", path=row["path"])
            declared[row["path"]] = row
        expected_manifest_paths = actual_relative - {MANIFEST_PATH, CHECKSUM_PATH}
        if set(declared) != expected_manifest_paths:
            raise FoundationHandoffError(
                "HANDOFF_MANIFEST_COVERAGE_MISMATCH",
                "Handoff manifest does not cover every payload member exactly once.",
                missing=sorted(expected_manifest_paths - set(declared)),
                unexpected=sorted(set(declared) - expected_manifest_paths),
            )
        for relative_path, row in declared.items():
            payload = read(relative_path)
            if row.get("bytes") != len(payload) or row.get("sha256") != _sha256(payload):
                raise FoundationHandoffError(
                    "HANDOFF_MANIFEST_FILE_IDENTITY_MISMATCH",
                    "A handoff manifest file row does not match its payload.",
                    path=relative_path,
                )

        blobs: dict[str, SourceBlob] = {}
        parsed: dict[str, dict[str, Any]] = {}
        for logical_name, relative_path in CATALOG_PATHS.items():
            data = read(relative_path)
            blobs[logical_name] = SourceBlob(logical_name, relative_path, data, _sha256(data))
            parsed[logical_name] = _json(data, path=relative_path)

    return FoundationHandoff(
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        root=HANDOFF_ROOT,
        manifest=manifest,
        manifest_sha256=_sha256(manifest_bytes),
        checksum_manifest_sha256=_sha256(checksum_bytes),
        source_blobs=blobs,
        families_catalog=parsed["families"],
        expressions_catalog=parsed["expressions"],
        selection_index=parsed["selection_index"],
        readable_projection=parsed["readable_projection"],
        legacy_alias_map=parsed["legacy_alias_map"],
    )
