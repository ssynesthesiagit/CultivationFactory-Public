from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import canonical_json_bytes
from .constants import CANDIDATE_STATUS, TOOL_SCHEMA_VERSION


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True, order=True)
class Diagnostic:
    sort_key: tuple[Any, ...] = field(init=False, repr=False, compare=True)
    code: str = field(compare=False)
    severity: Severity = field(compare=False)
    subsystem: str = field(compare=False)
    message: str = field(compare=False)
    path: str | None = field(default=None, compare=False)
    record_id: str | None = field(default=None, compare=False)
    field_path: str | None = field(default=None, compare=False)
    details: Mapping[str, Any] = field(default_factory=dict, compare=False)
    retry_safe: bool = field(default=True, compare=False)
    recommended_action: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sort_key",
            (
                self.severity.value,
                self.subsystem,
                self.code,
                self.path or "",
                self.record_id or "",
                self.field_path or "",
                self.message,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "subsystem": self.subsystem,
            "message": self.message,
            "retry_safe": self.retry_safe,
        }
        if self.path is not None:
            result["path"] = self.path
        if self.record_id is not None:
            result["record_id"] = self.record_id
        if self.field_path is not None:
            result["field_path"] = self.field_path
        if self.details:
            result["details"] = dict(sorted(self.details.items()))
        if self.recommended_action is not None:
            result["recommended_action"] = self.recommended_action
        return result


@dataclass(frozen=True)
class FileInventoryEntry:
    logical_path: str
    size_bytes: int
    sha256: str
    source_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_path": self.logical_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_path": self.source_path,
        }


@dataclass
class ValidationArtifacts:
    validation_report: dict[str, Any]
    human_report: str
    capability_matrix: dict[str, Any]
    dependency_graph: dict[str, Any]
    unsupported_primitives: dict[str, Any]
    source_binding_report: dict[str, Any]
    checksum_inventory: dict[str, Any]
    verdict: dict[str, Any]

    def machine_files(self) -> dict[str, bytes]:
        return {
            "validation_report.json": canonical_json_bytes(self.validation_report),
            "validation_report.txt": self.human_report.encode("utf-8"),
            "record_capability_matrix.json": canonical_json_bytes(self.capability_matrix),
            "dependency_graph.json": canonical_json_bytes(self.dependency_graph),
            "unsupported_primitives.json": canonical_json_bytes(self.unsupported_primitives),
            "source_binding_report.json": canonical_json_bytes(self.source_binding_report),
            "checksum_inventory.json": canonical_json_bytes(self.checksum_inventory),
            "verdict.json": canonical_json_bytes(self.verdict),
        }


@dataclass
class ValidationResult:
    verdict: str
    diagnostics: list[Diagnostic]
    artifacts: ValidationArtifacts
    input_kind: str
    input_identity: str
    input_preserved: bool

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


@dataclass(frozen=True)
class ValidationOptions:
    primitive_registry: Path | None = None
    factory_version: str | None = None
    compiler_version: str | None = None
    engine_version: str | None = None
    maximum_file_count: int = 100_000
    maximum_uncompressed_bytes: int = 512 * 1024 * 1024
    maximum_single_file_bytes: int = 64 * 1024 * 1024
    strict_unknown_files: bool = False
    include_info_diagnostics: bool = True


@dataclass
class ValidationContext:
    input_path: Path
    input_kind: str
    input_identity_before: str
    input_identity_after: str | None = None
    pack_root: str = ""
    inventory: list[FileInventoryEntry] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    parsed_json: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    advancement_rules: list[dict[str, Any]] = field(default_factory=list)
    character_sheet_rules: list[dict[str, Any]] = field(default_factory=list)
    gm_display_rules: list[dict[str, Any]] = field(default_factory=list)
    combat_definitions: list[dict[str, Any]] = field(default_factory=list)
    creatures: list[dict[str, Any]] = field(default_factory=list)
    controller_policies: list[dict[str, Any]] = field(default_factory=list)
    validation_cases: list[dict[str, Any]] = field(default_factory=list)
    primitive_ids: set[str] = field(default_factory=set)
    primitive_registry_identity: str | None = None
    primitive_registry_schema_version: str | None = None
    unsupported_primitive_references: list[dict[str, Any]] = field(default_factory=list)
    checksum_rows: dict[str, str] = field(default_factory=dict)
    checksum_exact: bool = False

    def add(self, diagnostic: Diagnostic) -> None:
        self.diagnostics.append(diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.diagnostics.extend(diagnostics)

    def ordered_diagnostics(self, include_info: bool = True) -> list[Diagnostic]:
        rows = self.diagnostics
        if not include_info:
            rows = [row for row in rows if row.severity is not Severity.INFO]
        return sorted(rows)

    def has_errors(self) -> bool:
        return any(row.severity is Severity.ERROR for row in self.diagnostics)

    def report_header(self) -> dict[str, Any]:
        return {
            "schema_version": TOOL_SCHEMA_VERSION,
            "candidate_status": CANDIDATE_STATUS,
            "input_kind": self.input_kind,
            "input_identity": self.input_identity_before,
            "pack_root": self.pack_root,
        }
