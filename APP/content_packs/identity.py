from __future__ import annotations

import json
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from app.core import canonical_json, sha256_bytes, sha256_json


IDENTITY_SCHEMA = "TianxiaFoundry.ContentPackPayloadIdentity.v3"
PACK_HASH_SENTINEL = "<CONTENT_PACK_HASH>"
MANIFEST_HASH_SENTINEL = "<MANIFEST_CONTRACT_HASH>"
DERIVED_SHA256_SENTINEL = "<DERIVED_SHA256>"
DERIVED_BYTES_SENTINEL = "<DERIVED_BYTES>"
WINDOWS_RESERVED_BASENAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def normalize_payload_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Payload paths must be non-empty portable POSIX relative paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or not path.parts:
        raise ValueError("Payload paths must remain inside the Content Pack root.")
    normalized = path.as_posix()
    if normalized != value:
        raise ValueError("Payload paths must already be canonical POSIX paths.")
    for segment in path.parts:
        if unicodedata.normalize("NFC", segment) != segment:
            raise ValueError("Payload path segments must use canonical NFC Unicode.")
        if segment.endswith((" ", ".")):
            raise ValueError("Payload path segments may not end in a space or dot on Windows.")
        if any(ord(char) < 32 or ord(char) == 127 for char in segment):
            raise ValueError("Payload path segments may not contain control characters.")
        basename = segment.split(".", 1)[0].upper()
        if basename in WINDOWS_RESERVED_BASENAMES:
            raise ValueError("Payload path segments may not use Windows reserved device names.")
    return normalized


def normalized_record_bytes(raw: bytes) -> tuple[bytes, str, str]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Rules Catalog records must be JSON objects.")
    record_id = value.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("Rules Catalog records require record_id.")
    normalized = json.loads(canonical_json(value))
    normalized.pop("record_hash", None)
    binding = normalized.get("content_binding")
    if not isinstance(binding, dict):
        raise ValueError("Rules Catalog records require content_binding.")
    binding["pack_hash"] = PACK_HASH_SENTINEL
    encoded = canonical_json(normalized).encode("utf-8")
    return encoded, record_id, sha256_bytes(encoded)


def normalized_manifest_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic, non-circular Content Pack manifest contract.

    ``pack.json`` is intentionally outside ``files[]`` because its exact bytes
    contain the final content hash.  The payload identity must nevertheless
    commit the declarations that tell consumers how to interpret that payload.
    We therefore retain every manifest field while normalizing only values that
    are mechanically derived from the payload or from this contract itself.

    In particular, record/source/test/migration/replacement paths, stable IDs,
    content types, compatibility, lifecycle state, dependencies, conflicts and
    revision semantics all remain in the contract.  Changing any one of those
    declarations changes both ``manifest_contract_hash`` and ``content_hash``.
    """
    if not isinstance(manifest, dict):
        raise ValueError("Content Pack manifest contract must be a JSON object.")
    normalized = json.loads(canonical_json(manifest))

    def visit(value: Any) -> Any:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "content_hash":
                result[key] = PACK_HASH_SENTINEL
            elif key == "manifest_contract_hash":
                result[key] = MANIFEST_HASH_SENTINEL
            elif key == "sha256":
                result[key] = DERIVED_SHA256_SENTINEL
            elif key == "bytes":
                result[key] = DERIVED_BYTES_SENTINEL
            else:
                result[key] = visit(item)
        return result

    return visit(normalized)


def compute_manifest_contract_hash(manifest: dict[str, Any]) -> str:
    return sha256_json(normalized_manifest_contract(manifest))


def compute_payload_identity(
    *,
    pack_id: str,
    version: str,
    payload: dict[str, bytes],
    record_paths: set[str],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compute a non-circular identity that commits payload and manifest.

    Final record bytes embed both the pack hash and a record hash derived from
    it.  For the pack identity only those two derived fields are normalized;
    every other semantic record field remains committed.  Exact final bytes are
    independently checked by each manifest file SHA and by the archive SHA.
    The normalized manifest contract binds all semantic envelope declarations
    without folding its derived hashes back into themselves.
    """
    if manifest.get("pack_id") != pack_id or manifest.get("version") != version:
        raise ValueError("Manifest pack_id/version must match the payload identity request.")
    entries: list[dict[str, Any]] = []
    records: list[dict[str, str]] = []
    for raw_path in sorted(payload):
        path = normalize_payload_path(raw_path)
        raw = payload[raw_path]
        if path in record_paths:
            semantic, record_id, semantic_hash = normalized_record_bytes(raw)
            entries.append({
                "path": path,
                "kind": "rules_catalog_record",
                "semantic_bytes": len(semantic),
                "semantic_sha256": semantic_hash,
            })
            records.append({"record_id": record_id, "path": path, "semantic_sha256": semantic_hash})
        else:
            entries.append({
                "path": path,
                "kind": "opaque_payload",
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            })
    payload_files_hash = sha256_json(entries)
    record_set_hash = sha256_json(sorted(records, key=lambda row: (row["record_id"], row["path"])))
    manifest_contract_hash = compute_manifest_contract_hash(manifest)
    content_hash = sha256_json({
        "schema_version": IDENTITY_SCHEMA,
        "pack_id": pack_id,
        "version": version,
        "payload_files_hash": payload_files_hash,
        "record_set_hash": record_set_hash,
        "manifest_contract_hash": manifest_contract_hash,
    })
    return {
        "schema_version": IDENTITY_SCHEMA,
        "pack_id": pack_id,
        "version": version,
        "payload_files_hash": payload_files_hash,
        "record_set_hash": record_set_hash,
        "manifest_contract_hash": manifest_contract_hash,
        "content_hash": content_hash,
        "entries": entries,
        "records": sorted(records, key=lambda row: (row["record_id"], row["path"])),
    }
