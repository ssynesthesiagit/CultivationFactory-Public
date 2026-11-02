from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import DEFAULT_CONTENT_FILES, KNOWN_SCHEMA_VERSIONS
from .models import Diagnostic, Severity, ValidationContext

_SCHEMA_FILES = {
    "pack.json": "pack.schema.v1.json",
    DEFAULT_CONTENT_FILES["records"]: "record_definitions.schema.v1.json",
    DEFAULT_CONTENT_FILES["advancement"]: "advancement_rules.schema.v1.json",
    DEFAULT_CONTENT_FILES["character_sheet"]: "character_sheet_rules.schema.v1.json",
    DEFAULT_CONTENT_FILES["gm_display"]: "gm_display_rules.schema.v1.json",
    DEFAULT_CONTENT_FILES["combat"]: "combat_definitions.schema.v1.json",
    DEFAULT_CONTENT_FILES["creatures"]: "creature_definitions.schema.v1.json",
    DEFAULT_CONTENT_FILES["policies"]: "controller_policies.schema.v1.json",
    DEFAULT_CONTENT_FILES["tests"]: "validation_cases.schema.v1.json",
}
_SCHEMA_KIND = {
    "pack.json": "manifest",
    DEFAULT_CONTENT_FILES["records"]: "records",
    DEFAULT_CONTENT_FILES["advancement"]: "advancement",
    DEFAULT_CONTENT_FILES["character_sheet"]: "character_sheet",
    DEFAULT_CONTENT_FILES["gm_display"]: "gm_display",
    DEFAULT_CONTENT_FILES["combat"]: "combat",
    DEFAULT_CONTENT_FILES["creatures"]: "creatures",
    DEFAULT_CONTENT_FILES["policies"]: "policies",
    DEFAULT_CONTENT_FILES["tests"]: "tests",
}


def schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "content_pack_candidate"


def validate_candidate_schemas(context: ValidationContext) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        context.add(
            Diagnostic(
                code="VALIDATOR_DEPENDENCY_MISSING",
                severity=Severity.ERROR,
                subsystem="schema",
                message="The jsonschema dependency required by the standalone validator is unavailable.",
                recommended_action="Install the existing Factory development requirements before running CPK-1.",
            )
        )
        return
    root = schema_root()
    for path, schema_name in sorted(_SCHEMA_FILES.items()):
        document = context.parsed_json.get(path)
        if document is None:
            if path == "pack.json":
                context.add(
                    Diagnostic(
                        code="MANIFEST_MISSING",
                        severity=Severity.ERROR,
                        subsystem="manifest",
                        message="The pack is missing pack.json at its logical root.",
                        path=path,
                    )
                )
            continue
        if not isinstance(document, dict):
            context.add(
                Diagnostic(
                    code="JSON_DOCUMENT_TYPE_INVALID",
                    severity=Severity.ERROR,
                    subsystem="schema",
                    message="A candidate content document must be a JSON object.",
                    path=path,
                )
            )
            continue
        kind = _SCHEMA_KIND[path]
        version = document.get("schema_version")
        if version not in KNOWN_SCHEMA_VERSIONS[kind]:
            context.add(
                Diagnostic(
                    code="SCHEMA_VERSION_UNKNOWN",
                    severity=Severity.ERROR,
                    subsystem="schema",
                    message="The document declares an unsupported candidate schema version.",
                    path=path,
                    field_path="$.schema_version",
                    details={"declared": version, "supported": sorted(KNOWN_SCHEMA_VERSIONS[kind])},
                )
            )
            continue
        schema_path = root / schema_name
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            context.add(
                Diagnostic(
                    code="CANDIDATE_SCHEMA_UNAVAILABLE",
                    severity=Severity.ERROR,
                    subsystem="schema",
                    message="The validator's isolated candidate schema could not be loaded.",
                    path=schema_path.name,
                    details={"error_type": type(exc).__name__},
                )
            )
            continue
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
        for error in errors:
            field_path = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path
            )
            context.add(
                Diagnostic(
                    code="SCHEMA_VALIDATION_FAILED",
                    severity=Severity.ERROR,
                    subsystem="schema",
                    message=error.message,
                    path=path,
                    field_path=field_path,
                    details={"validator": error.validator},
                    recommended_action="Conform the document to the isolated candidate schema and regenerate checksums.",
                )
            )
