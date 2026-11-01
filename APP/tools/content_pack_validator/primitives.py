from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .canonical import sha256_bytes
from .constants import CANDIDATE_STATUS, DEFAULT_CONTENT_FILES, KNOWN_SCHEMA_VERSIONS
from .models import Diagnostic, Severity, ValidationContext
from .schema_validation import schema_root


def load_and_validate_primitive_registry(context: ValidationContext, registry_path: Path | None) -> None:
    references = list(_primitive_references(context))
    if registry_path is None:
        if references:
            context.add(
                Diagnostic(
                    code="PRIMITIVE_REGISTRY_REQUIRED",
                    severity=Severity.ERROR,
                    subsystem="primitives",
                    message="Mechanical primitive references exist, but no primitive registry was supplied.",
                    details={"reference_count": len(references)},
                    recommended_action="Run the validator with --primitive-registry pointing to an authenticated registry file.",
                )
            )
            context.unsupported_primitive_references = sorted(references, key=_reference_key)
        return
    try:
        raw = registry_path.read_bytes()
    except OSError as exc:
        context.add(
            Diagnostic(
                code="PRIMITIVE_REGISTRY_READ_FAILED",
                severity=Severity.ERROR,
                subsystem="primitives",
                message="The supplied primitive registry could not be read.",
                path=registry_path.name,
                details={"error_type": type(exc).__name__},
            )
        )
        return
    context.primitive_registry_identity = sha256_bytes(raw)
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        context.add(
            Diagnostic(
                code="PRIMITIVE_REGISTRY_JSON_INVALID",
                severity=Severity.ERROR,
                subsystem="primitives",
                message="The supplied primitive registry is not valid UTF-8 JSON.",
                path=registry_path.name,
                details={"error_type": type(exc).__name__},
            )
        )
        return
    if isinstance(document, dict):
        context.primitive_registry_schema_version = document.get("schema_version")
    _validate_registry_schema(context, registry_path.name, document)
    primitives = document.get("primitives", []) if isinstance(document, dict) else []
    ids: set[str] = set()
    duplicates: set[str] = set()
    for row in primitives if isinstance(primitives, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("primitive_id"), str):
            continue
        primitive_id = row["primitive_id"]
        if primitive_id in ids:
            duplicates.add(primitive_id)
        ids.add(primitive_id)
    for primitive_id in sorted(duplicates):
        context.add(
            Diagnostic(
                code="PRIMITIVE_REGISTRY_ID_DUPLICATE",
                severity=Severity.ERROR,
                subsystem="primitives",
                message="The primitive registry contains a duplicate primitive ID.",
                path=registry_path.name,
                record_id=primitive_id,
            )
        )
    context.primitive_ids = ids
    unsupported: list[dict[str, Any]] = []
    for reference in references:
        primitive_id = reference["primitive_id"]
        if primitive_id not in ids:
            unsupported.append(reference)
            context.add(
                Diagnostic(
                    code="PRIMITIVE_UNKNOWN",
                    severity=Severity.ERROR,
                    subsystem="primitives",
                    message="A content definition references a primitive absent from the supplied registry.",
                    path=reference["path"],
                    record_id=reference.get("record_id"),
                    field_path=reference.get("field_path"),
                    details={"primitive_id": primitive_id},
                    recommended_action="Add the primitive through a separately reviewed engine checkpoint or correct the reference.",
                )
            )
    context.unsupported_primitive_references = sorted(unsupported, key=_reference_key)


def _validate_registry_schema(context: ValidationContext, path: str, document: Any) -> None:
    if not isinstance(document, dict):
        context.add(
            Diagnostic(
                code="PRIMITIVE_REGISTRY_TYPE_INVALID",
                severity=Severity.ERROR,
                subsystem="primitives",
                message="The primitive registry must be a JSON object.",
                path=path,
            )
        )
        return
    if document.get("schema_version") not in KNOWN_SCHEMA_VERSIONS["primitive_registry"]:
        context.add(
            Diagnostic(
                code="PRIMITIVE_REGISTRY_SCHEMA_UNKNOWN",
                severity=Severity.ERROR,
                subsystem="primitives",
                message="The primitive registry declares an unsupported schema version.",
                path=path,
                details={"declared": document.get("schema_version")},
            )
        )
        return
    try:
        from jsonschema import Draft202012Validator
        schema = json.loads((schema_root() / "primitive_registry.schema.v1.json").read_text(encoding="utf-8"))
    except (ImportError, OSError, json.JSONDecodeError):
        return
    for error in sorted(Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.absolute_path)):
        field_path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        context.add(
            Diagnostic(
                code="PRIMITIVE_REGISTRY_SCHEMA_FAILED",
                severity=Severity.ERROR,
                subsystem="primitives",
                message=error.message,
                path=path,
                field_path=field_path,
            )
        )


def _primitive_references(context: ValidationContext) -> Iterable[dict[str, Any]]:
    groups = (
        (context.combat_definitions, DEFAULT_CONTENT_FILES["combat"], "definitions", "definition_id"),
        (context.controller_policies, DEFAULT_CONTENT_FILES["policies"], "policies", "policy_id"),
    )
    for rows, path, key, identity_key in groups:
        for index, row in enumerate(rows):
            primitive_ids = row.get("primitive_ids")
            if not isinstance(primitive_ids, list):
                continue
            for primitive_index, primitive_id in enumerate(primitive_ids):
                if isinstance(primitive_id, str):
                    yield {
                        "primitive_id": primitive_id,
                        "path": path,
                        "record_id": row.get("record_id") or row.get(identity_key),
                        "field_path": f"$.{key}[{index}].primitive_ids[{primitive_index}]",
                    }


def _reference_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("primitive_id", "")),
        str(row.get("path", "")),
        str(row.get("record_id", "")),
        str(row.get("field_path", "")),
    )
