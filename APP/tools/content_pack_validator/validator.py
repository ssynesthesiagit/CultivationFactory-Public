from __future__ import annotations

from pathlib import Path

from .capabilities import validate_records_and_capabilities
from .checksums import validate_checksums
from .json_content import (
    bind_known_documents,
    parse_json_files,
    validate_declarative_file_safety,
)
from .manifest import validate_all_source_bindings, validate_manifest
from .models import (
    Diagnostic,
    Severity,
    ValidationContext,
    ValidationOptions,
    ValidationResult,
)
from .primitives import load_and_validate_primitive_registry
from .reports import build_artifacts
from .schema_validation import validate_candidate_schemas
from .source import input_identity, open_pack_source


def validate_content_pack(
    input_path: str | Path,
    options: ValidationOptions | None = None,
) -> ValidationResult:
    options = options or ValidationOptions()
    path = Path(input_path).resolve()
    before = input_identity(path)
    with open_pack_source(path, options) as source:
        context = ValidationContext(
            input_path=path,
            input_kind=source.input_kind,
            input_identity_before=before,
            pack_root=source.pack_root,
            inventory=list(source.inventory),
        )
        context.extend(source.diagnostics)
        validate_declarative_file_safety(context)
        validate_checksums(context, source)
        parse_json_files(context, source)
        bind_known_documents(context)
        validate_candidate_schemas(context)
        validate_manifest(context, options)
        validate_all_source_bindings(context)
        validate_records_and_capabilities(context)
        load_and_validate_primitive_registry(context, options.primitive_registry)
    after = input_identity(path)
    context.input_identity_after = after
    if after != before:
        context.add(
            Diagnostic(
                code="INPUT_MUTATED_DURING_VALIDATION",
                severity=Severity.ERROR,
                subsystem="input_preservation",
                message="The input identity changed during validation.",
                details={"before": before, "after": after},
                retry_safe=False,
                recommended_action="Restore the original pack and rerun in a stable read-only workspace.",
            )
        )
    else:
        context.add(
            Diagnostic(
                code="INPUT_BYTE_PRESERVATION_CONFIRMED",
                severity=Severity.INFO,
                subsystem="input_preservation",
                message="The input pack remained byte-identical throughout validation.",
                details={"identity": before},
            )
        )
    artifacts = build_artifacts(context, include_info=options.include_info_diagnostics)
    verdict = artifacts.verdict["verdict"]
    return ValidationResult(
        verdict=verdict,
        diagnostics=context.ordered_diagnostics(include_info=options.include_info_diagnostics),
        artifacts=artifacts,
        input_kind=context.input_kind,
        input_identity=before,
        input_preserved=before == after,
    )
