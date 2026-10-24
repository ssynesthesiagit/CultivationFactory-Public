from __future__ import annotations

import re
from typing import Iterable

from .models import Diagnostic, FileInventoryEntry, Severity, ValidationContext
from .source import PackSource

_ROW = re.compile(r"^([0-9a-fA-F]{64})[ \t]+\*?(.+)$")


def validate_checksums(context: ValidationContext, source: PackSource) -> None:
    if not source.exists("SHA256SUMS.txt"):
        context.add(
            Diagnostic(
                code="CHECKSUM_MANIFEST_MISSING",
                severity=Severity.ERROR,
                subsystem="checksums",
                message="The pack does not contain SHA256SUMS.txt at its logical root.",
                path="SHA256SUMS.txt",
                recommended_action="Create a SHA-256 manifest covering every payload file except the manifest itself.",
            )
        )
        return
    try:
        text = source.read_bytes("SHA256SUMS.txt").decode("utf-8-sig")
    except UnicodeDecodeError:
        context.add(
            Diagnostic(
                code="CHECKSUM_MANIFEST_ENCODING_INVALID",
                severity=Severity.ERROR,
                subsystem="checksums",
                message="SHA256SUMS.txt must be UTF-8 text.",
                path="SHA256SUMS.txt",
            )
        )
        return
    declared: dict[str, str] = {}
    malformed = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = _ROW.fullmatch(line)
        if not match:
            malformed = True
            context.add(
                Diagnostic(
                    code="CHECKSUM_ROW_MALFORMED",
                    severity=Severity.ERROR,
                    subsystem="checksums",
                    message="A checksum row is malformed.",
                    path="SHA256SUMS.txt",
                    field_path=f"line:{line_number}",
                    details={"row": line},
                    recommended_action="Use '<64 lowercase hex>  <relative path>' rows.",
                )
            )
            continue
        digest, logical_path = match.group(1).lower(), match.group(2)
        if logical_path in declared:
            malformed = True
            context.add(
                Diagnostic(
                    code="CHECKSUM_PATH_DUPLICATE",
                    severity=Severity.ERROR,
                    subsystem="checksums",
                    message="A payload path is declared more than once in SHA256SUMS.txt.",
                    path=logical_path,
                    field_path=f"line:{line_number}",
                )
            )
            continue
        if logical_path == "SHA256SUMS.txt":
            malformed = True
            context.add(
                Diagnostic(
                    code="CHECKSUM_MANIFEST_SELF_DECLARED",
                    severity=Severity.ERROR,
                    subsystem="checksums",
                    message="SHA256SUMS.txt must not declare itself.",
                    path=logical_path,
                )
            )
            continue
        declared[logical_path] = digest
    context.checksum_rows = dict(sorted(declared.items()))
    actual_rows = {entry.logical_path: entry for entry in source.inventory if entry.logical_path != "SHA256SUMS.txt"}
    for path in sorted(set(actual_rows) - set(declared)):
        context.add(
            Diagnostic(
                code="CHECKSUM_PAYLOAD_UNDECLARED",
                severity=Severity.ERROR,
                subsystem="checksums",
                message="A payload file is not declared in SHA256SUMS.txt.",
                path=path,
                recommended_action="Add the exact file hash to SHA256SUMS.txt or remove the payload.",
            )
        )
    for path in sorted(set(declared) - set(actual_rows)):
        context.add(
            Diagnostic(
                code="CHECKSUM_DECLARATION_MISSING_FILE",
                severity=Severity.ERROR,
                subsystem="checksums",
                message="SHA256SUMS.txt declares a file that is absent from the pack.",
                path=path,
                details={"declared_sha256": declared[path]},
            )
        )
    mismatch = False
    for path in sorted(set(declared) & set(actual_rows)):
        actual = actual_rows[path].sha256
        expected = declared[path]
        if actual != expected:
            mismatch = True
            context.add(
                Diagnostic(
                    code="CHECKSUM_MISMATCH",
                    severity=Severity.ERROR,
                    subsystem="checksums",
                    message="A payload file does not match its declared SHA-256.",
                    path=path,
                    details={"actual_sha256": actual, "declared_sha256": expected},
                    recommended_action="Restore the declared bytes or regenerate the pack manifest from reviewed content.",
                )
            )
    context.checksum_exact = not (
        malformed
        or mismatch
        or set(actual_rows) != set(declared)
    )
    if context.checksum_exact:
        context.add(
            Diagnostic(
                code="CHECKSUM_COVERAGE_EXACT",
                severity=Severity.INFO,
                subsystem="checksums",
                message="SHA256SUMS.txt exactly covers every payload file.",
                path="SHA256SUMS.txt",
                details={"payload_count": len(actual_rows)},
            )
        )


def checksum_inventory(context: ValidationContext) -> dict[str, object]:
    rows = []
    declared = context.checksum_rows
    for entry in sorted(context.inventory, key=lambda row: row.logical_path):
        if entry.logical_path == "SHA256SUMS.txt":
            declaration = "MANIFEST_EXCLUDED"
        elif entry.logical_path in declared:
            declaration = "MATCH" if declared[entry.logical_path] == entry.sha256 else "MISMATCH"
        else:
            declaration = "UNDECLARED"
        rows.append({**entry.to_dict(), "declaration_status": declaration})
    for path in sorted(set(declared) - {entry.logical_path for entry in context.inventory}):
        rows.append(
            {
                "logical_path": path,
                "sha256": None,
                "size_bytes": None,
                "source_path": None,
                "declared_sha256": declared[path],
                "declaration_status": "MISSING_FILE",
            }
        )
    return {
        **context.report_header(),
        "checksum_algorithm": "SHA-256",
        "exact_coverage": context.checksum_exact,
        "entries": rows,
    }
