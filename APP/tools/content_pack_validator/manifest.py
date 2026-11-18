from __future__ import annotations

import re
from typing import Any

from .constants import DEFAULT_CONTENT_FILES, KNOWN_SCHEMA_VERSIONS, PACK_ID_PATTERN, SHA256_PATTERN
from .models import Diagnostic, Severity, ValidationContext, ValidationOptions
from .semver import Version, satisfies, validate_range

_PACK_ID = re.compile(PACK_ID_PATTERN)
_SHA256 = re.compile(SHA256_PATTERN)


def validate_manifest(context: ValidationContext, options: ValidationOptions) -> None:
    manifest = context.manifest
    if manifest is None:
        return
    pack_id = manifest.get("pack_id")
    if not isinstance(pack_id, str) or not _PACK_ID.fullmatch(pack_id):
        context.add(
            Diagnostic(
                code="PACK_ID_INVALID",
                severity=Severity.ERROR,
                subsystem="manifest",
                message="pack_id is not a stable lowercase dotted identifier.",
                path="pack.json",
                field_path="$.pack_id",
                details={"value": pack_id},
            )
        )
    version = manifest.get("version")
    try:
        Version.parse(version)
    except (TypeError, ValueError):
        context.add(
            Diagnostic(
                code="PACK_VERSION_INVALID",
                severity=Severity.ERROR,
                subsystem="manifest",
                message="The pack version is not valid semantic versioning.",
                path="pack.json",
                field_path="$.version",
                details={"value": version},
            )
        )
    source = manifest.get("source_identity")
    _validate_source_binding(context, source, "pack.json", "$.source_identity", None)
    declared_schema_versions = manifest.get("schema_versions", {})
    if isinstance(declared_schema_versions, dict):
        for key, value in sorted(declared_schema_versions.items()):
            known = {item for versions in KNOWN_SCHEMA_VERSIONS.values() for item in versions}
            if value not in known:
                context.add(
                    Diagnostic(
                        code="MANIFEST_SCHEMA_VERSION_UNKNOWN",
                        severity=Severity.ERROR,
                        subsystem="manifest",
                        message="pack.json references an unknown candidate schema version.",
                        path="pack.json",
                        field_path=f"$.schema_versions.{key}",
                        details={"declared": value},
                    )
                )
    _validate_dependencies(context, manifest.get("dependencies", []), pack_id)
    _validate_compatibility(context, manifest.get("compatibility", {}), options)
    _validate_inventory(context, manifest.get("record_inventory", []))
    _validate_lifecycle(context, manifest.get("lifecycle", {}), pack_id)
    _validate_optional_files(context, manifest.get("optional_files", []), options)


def _validate_dependencies(context: ValidationContext, dependencies: Any, pack_id: Any) -> None:
    if not isinstance(dependencies, list):
        return
    seen: set[str] = set()
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            continue
        dep_id = dependency.get("pack_id")
        version_range = dependency.get("version_range")
        if dep_id in seen:
            context.add(
                Diagnostic(
                    code="DEPENDENCY_DUPLICATE",
                    severity=Severity.ERROR,
                    subsystem="dependencies",
                    message="The same pack dependency is declared more than once.",
                    path="pack.json",
                    field_path=f"$.dependencies[{index}]",
                    details={"pack_id": dep_id},
                )
            )
        if isinstance(dep_id, str):
            seen.add(dep_id)
        if dep_id == pack_id:
            context.add(
                Diagnostic(
                    code="DEPENDENCY_CYCLE_SELF",
                    severity=Severity.ERROR,
                    subsystem="dependencies",
                    message="A content pack cannot depend on itself.",
                    path="pack.json",
                    field_path=f"$.dependencies[{index}].pack_id",
                    details={"pack_id": dep_id},
                )
            )
        try:
            validate_range(version_range)
        except (TypeError, ValueError) as exc:
            context.add(
                Diagnostic(
                    code="DEPENDENCY_VERSION_RANGE_INVALID",
                    severity=Severity.ERROR,
                    subsystem="dependencies",
                    message="A dependency version range is invalid.",
                    path="pack.json",
                    field_path=f"$.dependencies[{index}].version_range",
                    details={"value": version_range, "reason": str(exc)},
                )
            )


def _validate_compatibility(context: ValidationContext, compatibility: Any, options: ValidationOptions) -> None:
    if not isinstance(compatibility, dict):
        return
    actual_versions = {
        "factory": options.factory_version,
        "compiler": options.compiler_version,
        "engine": options.engine_version,
    }
    for component, expression in sorted(compatibility.items()):
        try:
            validate_range(expression)
        except (TypeError, ValueError) as exc:
            context.add(
                Diagnostic(
                    code="COMPATIBILITY_RANGE_INVALID",
                    severity=Severity.ERROR,
                    subsystem="manifest",
                    message="A declared compatibility range is invalid.",
                    path="pack.json",
                    field_path=f"$.compatibility.{component}",
                    details={"value": expression, "reason": str(exc)},
                )
            )
            continue
        actual = actual_versions.get(component)
        if actual is not None:
            try:
                compatible = satisfies(actual, expression)
            except ValueError as exc:
                compatible = False
            if not compatible:
                context.add(
                    Diagnostic(
                        code="COMPATIBILITY_VERSION_MISMATCH",
                        severity=Severity.ERROR,
                        subsystem="manifest",
                        message="The supplied environment version is outside the pack's declared compatibility range.",
                        path="pack.json",
                        field_path=f"$.compatibility.{component}",
                        details={"actual_version": actual, "required_range": expression},
                    )
                )


def _validate_inventory(context: ValidationContext, inventory: Any) -> None:
    if not isinstance(inventory, list):
        return
    actual_counts = {
        DEFAULT_CONTENT_FILES["records"]: len(context.records),
        DEFAULT_CONTENT_FILES["advancement"]: len(context.advancement_rules),
        DEFAULT_CONTENT_FILES["character_sheet"]: len(context.character_sheet_rules),
        DEFAULT_CONTENT_FILES["gm_display"]: len(context.gm_display_rules),
        DEFAULT_CONTENT_FILES["combat"]: len(context.combat_definitions),
        DEFAULT_CONTENT_FILES["creatures"]: len(context.creatures),
        DEFAULT_CONTENT_FILES["policies"]: len(context.controller_policies),
        DEFAULT_CONTENT_FILES["tests"]: len(context.validation_cases),
    }
    seen: set[str] = set()
    for index, row in enumerate(inventory):
        if not isinstance(row, dict):
            continue
        path = row.get("path")
        if path in seen:
            context.add(
                Diagnostic(
                    code="RECORD_INVENTORY_PATH_DUPLICATE",
                    severity=Severity.ERROR,
                    subsystem="manifest",
                    message="record_inventory contains a duplicate path.",
                    path="pack.json",
                    field_path=f"$.record_inventory[{index}].path",
                    details={"declared_path": path},
                )
            )
        if isinstance(path, str):
            seen.add(path)
        if path not in {entry.logical_path for entry in context.inventory}:
            context.add(
                Diagnostic(
                    code="MANIFEST_DECLARED_FILE_MISSING",
                    severity=Severity.ERROR,
                    subsystem="manifest",
                    message="record_inventory declares a file that is absent from the pack.",
                    path=str(path),
                    field_path=f"$.record_inventory[{index}]",
                )
            )
            continue
        expected = row.get("count")
        actual = actual_counts.get(path)
        if actual is not None and expected != actual:
            context.add(
                Diagnostic(
                    code="RECORD_INVENTORY_COUNT_MISMATCH",
                    severity=Severity.ERROR,
                    subsystem="manifest",
                    message="record_inventory count does not match the parsed document.",
                    path=str(path),
                    details={"actual_count": actual, "declared_count": expected},
                )
            )


def _validate_lifecycle(context: ValidationContext, lifecycle: Any, pack_id: Any) -> None:
    if not isinstance(lifecycle, dict):
        return
    replaces = lifecycle.get("replaces", [])
    supersedes = lifecycle.get("supersedes", [])
    overlap = sorted(set(replaces if isinstance(replaces, list) else []) & set(supersedes if isinstance(supersedes, list) else []))
    if overlap:
        context.add(
            Diagnostic(
                code="LIFECYCLE_REPLACEMENT_CONFLICT",
                severity=Severity.ERROR,
                subsystem="manifest",
                message="The same pack identity is declared in both replaces and supersedes.",
                path="pack.json",
                field_path="$.lifecycle",
                details={"pack_ids": overlap},
            )
        )
    for field, values in (("replaces", replaces), ("supersedes", supersedes)):
        if isinstance(values, list) and pack_id in values:
            context.add(
                Diagnostic(
                    code="LIFECYCLE_SELF_REFERENCE",
                    severity=Severity.ERROR,
                    subsystem="manifest",
                    message="A pack cannot replace or supersede itself.",
                    path="pack.json",
                    field_path=f"$.lifecycle.{field}",
                    details={"pack_id": pack_id},
                )
            )


def _validate_optional_files(context: ValidationContext, optional_files: Any, options: ValidationOptions) -> None:
    if not isinstance(optional_files, list):
        optional_files = []
    known = {"pack.json", "SHA256SUMS.txt"} | set(DEFAULT_CONTENT_FILES.values())
    actual = {entry.logical_path for entry in context.inventory}
    undeclared_unknown = sorted(actual - known - set(optional_files))
    for path in undeclared_unknown:
        severity = Severity.ERROR if options.strict_unknown_files else Severity.WARNING
        context.add(
            Diagnostic(
                code="UNKNOWN_OPTIONAL_FILE",
                severity=severity,
                subsystem="manifest",
                message="The pack contains a checksum-covered file not recognized by the candidate layout.",
                path=path,
                recommended_action="Declare the path in optional_files or remove it before strict promotion review.",
            )
        )
    for path in sorted(set(optional_files) - actual):
        context.add(
            Diagnostic(
                code="OPTIONAL_FILE_DECLARED_BUT_ABSENT",
                severity=Severity.WARNING,
                subsystem="manifest",
                message="pack.json lists an optional file that is not present.",
                path=path,
            )
        )


def _validate_source_binding(context: ValidationContext, source: Any, path: str, field_path: str, record_id: str | None) -> bool:
    if not isinstance(source, dict):
        context.add(
            Diagnostic(
                code="SOURCE_BINDING_INVALID",
                severity=Severity.ERROR,
                subsystem="source_binding",
                message="A required source binding is absent or not an object.",
                path=path,
                record_id=record_id,
                field_path=field_path,
            )
        )
        return False
    required = ("source_id", "source_version", "source_sha256", "anchor")
    missing = [key for key in required if not source.get(key)]
    if missing:
        context.add(
            Diagnostic(
                code="SOURCE_BINDING_INCOMPLETE",
                severity=Severity.ERROR,
                subsystem="source_binding",
                message="A source binding omits required identity fields.",
                path=path,
                record_id=record_id,
                field_path=field_path,
                details={"missing_fields": missing},
            )
        )
        return False
    digest = source.get("source_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        context.add(
            Diagnostic(
                code="SOURCE_HASH_INVALID",
                severity=Severity.ERROR,
                subsystem="source_binding",
                message="source_sha256 is not a lowercase SHA-256 digest.",
                path=path,
                record_id=record_id,
                field_path=f"{field_path}.source_sha256",
            )
        )
        return False
    source_path = source.get("source_path")
    if source_path is not None:
        inventory = {entry.logical_path: entry for entry in context.inventory}
        if source_path not in inventory:
            context.add(
                Diagnostic(
                    code="SOURCE_PATH_MISSING",
                    severity=Severity.ERROR,
                    subsystem="source_binding",
                    message="The source binding names a pack-local source file that is absent.",
                    path=str(source_path),
                    record_id=record_id,
                    field_path=f"{field_path}.source_path",
                )
            )
            return False
        if inventory[source_path].sha256 != digest:
            context.add(
                Diagnostic(
                    code="SOURCE_PATH_HASH_MISMATCH",
                    severity=Severity.ERROR,
                    subsystem="source_binding",
                    message="The pack-local source file does not match source_sha256.",
                    path=str(source_path),
                    record_id=record_id,
                    details={"actual_sha256": inventory[source_path].sha256, "declared_sha256": digest},
                )
            )
            return False
    return True


def validate_all_source_bindings(context: ValidationContext) -> None:
    for index, record in enumerate(context.records):
        _validate_source_binding(context, record.get("source_binding"), DEFAULT_CONTENT_FILES["records"], f"$.records[{index}].source_binding", record.get("record_id"))
    groups = (
        (context.advancement_rules, DEFAULT_CONTENT_FILES["advancement"], "rules"),
        (context.character_sheet_rules, DEFAULT_CONTENT_FILES["character_sheet"], "rules"),
        (context.gm_display_rules, DEFAULT_CONTENT_FILES["gm_display"], "rules"),
        (context.combat_definitions, DEFAULT_CONTENT_FILES["combat"], "definitions"),
        (context.controller_policies, DEFAULT_CONTENT_FILES["policies"], "policies"),
    )
    for rows, path, key in groups:
        for index, row in enumerate(rows):
            _validate_source_binding(context, row.get("source_binding"), path, f"$.{key}[{index}].source_binding", row.get("record_id") or row.get("policy_id") or row.get("definition_id"))
    creature_document = context.parsed_json.get(DEFAULT_CONTENT_FILES["creatures"])
    if isinstance(creature_document, dict):
        for key in ("creatures", "companions"):
            for index, row in enumerate(creature_document.get(key, [])):
                if isinstance(row, dict):
                    _validate_source_binding(context, row.get("source_binding"), DEFAULT_CONTENT_FILES["creatures"], f"$.{key}[{index}].source_binding", row.get("creature_id"))
