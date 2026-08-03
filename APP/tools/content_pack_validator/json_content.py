from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Iterator

from .constants import (
    DEFAULT_CONTENT_FILES,
    EXECUTABLE_SUFFIXES,
    FORBIDDEN_RUNTIME_KEYS,
    FORBIDDEN_RUNTIME_PREFIXES,
    MACRO_SUFFIXES,
)
from .models import Diagnostic, Severity, ValidationContext
from .source import PackSource


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _walk_json(value[key], f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_json(item, f"{path}[{index}]")


def validate_declarative_file_safety(context: ValidationContext) -> None:
    for entry in context.inventory:
        suffix = PurePosixPath(entry.logical_path).suffix.casefold()
        if suffix in EXECUTABLE_SUFFIXES:
            context.add(
                Diagnostic(
                    code="EXECUTABLE_CONTENT_FILE",
                    severity=Severity.ERROR,
                    subsystem="declarative_safety",
                    message="Executable or script content is forbidden in declarative packs.",
                    path=entry.logical_path,
                    recommended_action="Express content through candidate JSON contracts and supported primitive IDs.",
                )
            )
        elif suffix in MACRO_SUFFIXES:
            context.add(
                Diagnostic(
                    code="MACRO_ENABLED_FILE",
                    severity=Severity.ERROR,
                    subsystem="declarative_safety",
                    message="Macro-enabled document content is forbidden in declarative packs.",
                    path=entry.logical_path,
                )
            )


def parse_json_files(context: ValidationContext, source: PackSource) -> None:
    for entry in sorted(context.inventory, key=lambda row: row.logical_path):
        path = entry.logical_path
        if not path.casefold().endswith(".json"):
            continue
        try:
            raw = source.read_bytes(path)
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            context.add(
                Diagnostic(
                    code="JSON_READ_FAILED",
                    severity=Severity.ERROR,
                    subsystem="json",
                    message="A JSON payload could not be read.",
                    path=path,
                    details={"error_type": type(exc).__name__},
                )
            )
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            context.add(
                Diagnostic(
                    code="JSON_ENCODING_INVALID",
                    severity=Severity.ERROR,
                    subsystem="json",
                    message="JSON files must be UTF-8 encoded.",
                    path=path,
                    details={"byte_offset": exc.start},
                )
            )
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            context.add(
                Diagnostic(
                    code="JSON_MALFORMED",
                    severity=Severity.ERROR,
                    subsystem="json",
                    message="A JSON payload is malformed.",
                    path=path,
                    details={"column": exc.colno, "line": exc.lineno, "message": exc.msg},
                    recommended_action="Correct the JSON syntax and regenerate checksums.",
                )
            )
            continue
        context.parsed_json[path] = value
        _scan_runtime_references(context, path, value)


def _scan_runtime_references(context: ValidationContext, path: str, value: Any) -> None:
    for field_path, node in _walk_json(value):
        if isinstance(node, dict):
            for key in sorted(node):
                if key.casefold() in FORBIDDEN_RUNTIME_KEYS:
                    context.add(
                        Diagnostic(
                            code="ARBITRARY_RUNTIME_REFERENCE",
                            severity=Severity.ERROR,
                            subsystem="declarative_safety",
                            message="A forbidden runtime module, activation, or script key is present.",
                            path=path,
                            field_path=f"{field_path}.{key}",
                            recommended_action="Replace runtime code references with declarative primitive IDs.",
                        )
                    )
        elif isinstance(node, str) and node.strip().casefold().startswith(FORBIDDEN_RUNTIME_PREFIXES):
            context.add(
                Diagnostic(
                    code="ARBITRARY_RUNTIME_INSTRUCTION",
                    severity=Severity.ERROR,
                    subsystem="declarative_safety",
                    message="A string contains a forbidden dynamic runtime instruction.",
                    path=path,
                    field_path=field_path,
                )
            )


def bind_known_documents(context: ValidationContext) -> None:
    context.manifest = _as_object(context.parsed_json.get("pack.json"))
    context.records = _extract_list(context, DEFAULT_CONTENT_FILES["records"], "records")
    context.advancement_rules = _extract_list(context, DEFAULT_CONTENT_FILES["advancement"], "rules")
    context.character_sheet_rules = _extract_list(context, DEFAULT_CONTENT_FILES["character_sheet"], "rules")
    context.gm_display_rules = _extract_list(context, DEFAULT_CONTENT_FILES["gm_display"], "rules")
    context.combat_definitions = _extract_list(context, DEFAULT_CONTENT_FILES["combat"], "definitions")
    creature_doc = context.parsed_json.get(DEFAULT_CONTENT_FILES["creatures"])
    if isinstance(creature_doc, dict):
        creatures = creature_doc.get("creatures", [])
        companions = creature_doc.get("companions", [])
        context.creatures = [row for row in creatures if isinstance(row, dict)] + [row for row in companions if isinstance(row, dict)]
    context.controller_policies = _extract_list(context, DEFAULT_CONTENT_FILES["policies"], "policies")
    context.validation_cases = _extract_list(context, DEFAULT_CONTENT_FILES["tests"], "cases")


def _as_object(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _extract_list(context: ValidationContext, path: str, key: str) -> list[dict[str, Any]]:
    document = context.parsed_json.get(path)
    if not isinstance(document, dict):
        return []
    rows = document.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]
