"""Immutable content snapshots and deterministic content transitions.

This is a shadow authority layer.  It records commitments and dependency
edges supplied by a caller; it does not read the Factory catalogue or update
the mutable latest-snapshot pointer.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.core import sha256_json

from .contracts import (
    HEX64,
    CreativeControllerError,
    fail,
    require_digest,
    require_enum,
    require_exact_keys,
    require_identifier,
    require_list,
    require_string,
    require_type,
    self_hash,
    validate_self_hash,
    without_hash,
)


SNAPSHOT_SCHEMA = "TianxiaFoundry.FactoryContentSnapshot.v1"
CHANGE_SET_SCHEMA = "TianxiaFoundry.ContentChangeSet.v1"
MIGRATION_RECEIPT_SCHEMA = "TianxiaFoundry.CharacterContentMigrationReceipt.v1"

LIFECYCLES = {"ACTIVE", "RETIRED", "QUARANTINED"}
CHOICE_KINDS = {"path", "method", "foundation", "background", "origin", "sphere", "talent", "insight", "milestone", "item", "action"}
CHANGE_CLASSES = {"DISPLAY", "MECHANICS", "SEMANTICS", "AUTHORITY", "DEPENDENCIES", "LIFECYCLE"}
MIGRATION_RESULTS = {"MIGRATED", "BLOCKED"}
REQUIRED_MIGRATION_SURFACES = frozenset({"actions", "final_package"})


def _digest(value: Any, path: str) -> str:
    result = require_digest(value, path=path)
    assert result is not None
    return result


def _sorted_unique_strings(values: Iterable[str], *, path: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        fail("DCC_SCHEMA_TYPE", f"{path} must be an array.")
    result = [require_string(value, path=f"{path}[{index}]") for index, value in enumerate(values)]
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} contains duplicate identifiers.")
    return tuple(sorted(result))


@dataclass(frozen=True)
class ContentRecordCommitment:
    """A typed record commitment admitted into one snapshot.

    ``dependency_ids`` is an in-memory graph projection.  It is not copied
    into the normative record commitment; the snapshot binds the full graph
    through ``dependency_graph_sha256``.
    """

    choice_id: str
    choice_kind: str
    lifecycle: str
    eligible_for_new_builds: bool
    choice_record_sha256: str
    typed_authority_sha256: str
    choice_semantics_sha256: str
    source_rights_receipt_sha256: str
    dependency_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.choice_id, path="record.choice_id")
        require_enum(self.choice_kind, CHOICE_KINDS, path="record.choice_kind")
        require_enum(self.lifecycle, LIFECYCLES, path="record.lifecycle")
        if not isinstance(self.eligible_for_new_builds, bool):
            fail("DCC_SCHEMA_TYPE", "record.eligible_for_new_builds must be a boolean.")
        if self.eligible_for_new_builds is not (self.lifecycle == "ACTIVE"):
            fail("DCC_CONTENT_LIFECYCLE_INVALID", "eligibility must exactly match lifecycle.")
        for field in ("choice_record_sha256", "typed_authority_sha256", "choice_semantics_sha256", "source_rights_receipt_sha256"):
            _digest(getattr(self, field), f"record.{field}")
        dependencies = _sorted_unique_strings(self.dependency_ids, path="record.dependency_ids")
        if self.choice_id in dependencies:
            fail("DCC_DEPENDENCY_CYCLE", "A content record cannot depend on itself.")
        object.__setattr__(self, "dependency_ids", dependencies)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ContentRecordCommitment":
        require_exact_keys(
            value,
            {"choice_id", "choice_kind", "lifecycle", "eligible_for_new_builds", "choice_record_sha256", "typed_authority_sha256", "choice_semantics_sha256", "source_rights_receipt_sha256"},
            {"dependency_ids"},
            path="content.record",
        )
        dependencies = value.get("dependency_ids", ())
        if not isinstance(dependencies, (list, tuple)):
            fail("DCC_SCHEMA_TYPE", "content.record.dependency_ids must be an array.")
        return cls(
            choice_id=value["choice_id"],
            choice_kind=value["choice_kind"],
            lifecycle=value["lifecycle"],
            eligible_for_new_builds=value["eligible_for_new_builds"],
            choice_record_sha256=value["choice_record_sha256"],
            typed_authority_sha256=value["typed_authority_sha256"],
            choice_semantics_sha256=value["choice_semantics_sha256"],
            source_rights_receipt_sha256=value["source_rights_receipt_sha256"],
            dependency_ids=tuple(dependencies),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "choice_id": self.choice_id,
            "choice_kind": self.choice_kind,
            "lifecycle": self.lifecycle,
            "eligible_for_new_builds": self.eligible_for_new_builds,
            "choice_record_sha256": self.choice_record_sha256,
            "typed_authority_sha256": self.typed_authority_sha256,
            "choice_semantics_sha256": self.choice_semantics_sha256,
            "source_rights_receipt_sha256": self.source_rights_receipt_sha256,
        }


def _normalise_record(value: ContentRecordCommitment | Mapping[str, Any]) -> ContentRecordCommitment:
    return value if isinstance(value, ContentRecordCommitment) else ContentRecordCommitment.from_mapping(value)


def _normalise_edges(edges: Any, *, record_ids: set[str] | None = None) -> tuple[tuple[str, str], ...]:
    """Normalize ``(dependent, dependency)`` edges in stable order."""

    if edges is None:
        return ()
    raw: list[tuple[Any, Any]] = []
    if isinstance(edges, Mapping):
        for dependent, dependencies in edges.items():
            if not isinstance(dependencies, (list, tuple, set, frozenset)):
                fail("DCC_SCHEMA_TYPE", "dependency graph values must be arrays.")
            raw.extend((dependent, dependency) for dependency in dependencies)
    elif isinstance(edges, (list, tuple, set, frozenset)):
        for edge in edges:
            if isinstance(edge, Mapping):
                require_exact_keys(edge, {"dependent_choice_id", "dependency_choice_id"}, path="dependency edge")
                raw.append((edge["dependent_choice_id"], edge["dependency_choice_id"]))
            elif isinstance(edge, (list, tuple)) and len(edge) == 2:
                raw.append((edge[0], edge[1]))
            else:
                fail("DCC_SCHEMA_TYPE", "dependency edges must be pairs or typed edge objects.")
    else:
        fail("DCC_SCHEMA_TYPE", "dependency graph must be an object or array.")
    normalized = {
        (require_string(dependent, path="dependency.dependent_choice_id"), require_string(dependency, path="dependency.dependency_choice_id"))
        for dependent, dependency in raw
    }
    for dependent, dependency in normalized:
        if dependent == dependency:
            fail("DCC_DEPENDENCY_CYCLE", "A dependency graph cannot contain a self-edge.")
        if record_ids is not None and (dependent not in record_ids or dependency not in record_ids):
            fail("DCC_DEPENDENCY_TARGET_UNKNOWN", "Every dependency target must be a snapshot record.", details={"dependent": dependent, "dependency": dependency})
    ordered = tuple(sorted(normalized))
    _assert_acyclic(ordered)
    return ordered


def _assert_acyclic(edges: Sequence[tuple[str, str]]) -> None:
    prerequisites: dict[str, set[str]] = {}
    for dependent, dependency in edges:
        prerequisites.setdefault(dependent, set()).add(dependency)
        prerequisites.setdefault(dependency, set())
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            fail("DCC_DEPENDENCY_CYCLE", "The content dependency graph contains a forbidden cycle.", details={"choice_id": node})
        if node in visited:
            return
        visiting.add(node)
        for dependency in sorted(prerequisites.get(node, ())):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(prerequisites):
        visit(node)


def _edge_hash(edges: Sequence[tuple[str, str]]) -> str:
    return sha256_json([{"dependent_choice_id": dependent, "dependency_choice_id": dependency} for dependent, dependency in edges])


@dataclass(frozen=True)
class FactoryContentSnapshot:
    schema: str
    snapshot_revision: int
    parent_content_snapshot_sha256: str | None
    admission_status: str
    catalogue_schema_versions: tuple[tuple[str, int], ...]
    rules_authority_sha256: str
    required_compiler_profile_sha256: str
    records: tuple[ContentRecordCommitment, ...]
    catalogue_set_sha256: str
    active_record_set_sha256: str
    choice_semantics_set_sha256: str
    dependency_graph_sha256: str
    lifecycle_ledger_sha256: str
    content_object_set_sha256: str
    content_resolver_binding_sha256: str
    content_snapshot_sha256: str
    dependency_edges: tuple[tuple[str, str], ...] = ()
    vocabulary_authority_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema != SNAPSHOT_SCHEMA:
            fail("DCC_SCHEMA_VALUE", "Unsupported content snapshot schema.")
        if not isinstance(self.snapshot_revision, int) or isinstance(self.snapshot_revision, bool) or self.snapshot_revision < 1:
            fail("DCC_SCHEMA_VALUE", "snapshot_revision must be a positive integer.")
        if self.parent_content_snapshot_sha256 is not None:
            _digest(self.parent_content_snapshot_sha256, "parent_content_snapshot_sha256")
        require_enum(self.admission_status, {"ADMITTED"}, path="admission_status")
        schema_versions = dict(self.catalogue_schema_versions)
        if len(schema_versions) != len(self.catalogue_schema_versions) or any(not isinstance(key, str) for key in schema_versions):
            fail("DCC_SCHEMA_VALUE", "catalogue schema names must be unique strings.")
        if any(not isinstance(version, int) or isinstance(version, bool) or version < 1 for version in schema_versions.values()):
            fail("DCC_SCHEMA_VALUE", "catalogue schema versions must be positive integers.")
        object.__setattr__(self, "catalogue_schema_versions", tuple(sorted(schema_versions.items())))
        for field in ("rules_authority_sha256", "required_compiler_profile_sha256", "catalogue_set_sha256", "active_record_set_sha256", "choice_semantics_set_sha256", "dependency_graph_sha256", "lifecycle_ledger_sha256", "content_object_set_sha256", "content_resolver_binding_sha256", "content_snapshot_sha256"):
            _digest(getattr(self, field), field)
        records = tuple(sorted(self.records, key=lambda row: row.choice_id))
        if len({row.choice_id for row in records}) != len(records):
            fail("DCC_CONTENT_DUPLICATE_CHOICE_ID", "A snapshot cannot contain duplicate choice IDs.")
        object.__setattr__(self, "records", records)
        edges = _normalise_edges(self.dependency_edges, record_ids={row.choice_id for row in records})
        _assert_acyclic(edges)
        object.__setattr__(self, "dependency_edges", edges)
        if self.vocabulary_authority_sha256 is None:
            object.__setattr__(self, "vocabulary_authority_sha256", sha256_json({"schema": "TianxiaFoundry.CreativeVocabularyAuthority.v1", "version": 1, "vocabularies": {}, "adapter_version_sha256": None}))
        _digest(self.vocabulary_authority_sha256, "vocabulary_authority_sha256")

    @property
    def sha256(self) -> str:
        return self.content_snapshot_sha256

    @property
    def active_choice_ids(self) -> tuple[str, ...]:
        return tuple(row.choice_id for row in self.records if row.lifecycle == "ACTIVE")

    def record_by_id(self) -> dict[str, ContentRecordCommitment]:
        return {row.choice_id: row for row in self.records}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "snapshot_revision": self.snapshot_revision,
            "parent_content_snapshot_sha256": self.parent_content_snapshot_sha256,
            "admission_status": self.admission_status,
            "catalogue_schema_versions": dict(self.catalogue_schema_versions),
            "rules_authority_sha256": self.rules_authority_sha256,
            "required_compiler_profile_sha256": self.required_compiler_profile_sha256,
            "records": [row.to_dict() for row in self.records],
            "catalogue_set_sha256": self.catalogue_set_sha256,
            "active_record_set_sha256": self.active_record_set_sha256,
            "choice_semantics_set_sha256": self.choice_semantics_set_sha256,
            "dependency_graph_sha256": self.dependency_graph_sha256,
            "lifecycle_ledger_sha256": self.lifecycle_ledger_sha256,
            "content_object_set_sha256": self.content_object_set_sha256,
            "content_resolver_binding_sha256": self.content_resolver_binding_sha256,
            "dependency_edges": [{"dependent_choice_id": dependent, "dependency_choice_id": dependency} for dependent, dependency in self.dependency_edges],
            "vocabulary_authority_sha256": self.vocabulary_authority_sha256,
            "content_snapshot_sha256": self.content_snapshot_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FactoryContentSnapshot":
        require_exact_keys(
            value,
            {"schema", "snapshot_revision", "parent_content_snapshot_sha256", "admission_status", "catalogue_schema_versions", "rules_authority_sha256", "required_compiler_profile_sha256", "records", "catalogue_set_sha256", "active_record_set_sha256", "choice_semantics_set_sha256", "dependency_graph_sha256", "lifecycle_ledger_sha256", "content_object_set_sha256", "content_resolver_binding_sha256", "dependency_edges", "vocabulary_authority_sha256", "content_snapshot_sha256"},
            path="content snapshot",
        )
        schema_versions = value["catalogue_schema_versions"]
        if not isinstance(schema_versions, Mapping):
            fail("DCC_SCHEMA_TYPE", "catalogue_schema_versions must be an object.")
        raw_records = require_list(value["records"], path="content snapshot.records")
        records = tuple(ContentRecordCommitment.from_mapping(row) for row in raw_records)
        snapshot = cls(
            schema=value["schema"],
            snapshot_revision=value["snapshot_revision"],
            parent_content_snapshot_sha256=value["parent_content_snapshot_sha256"],
            admission_status=value["admission_status"],
            catalogue_schema_versions=tuple(schema_versions.items()),
            rules_authority_sha256=value["rules_authority_sha256"],
            required_compiler_profile_sha256=value["required_compiler_profile_sha256"],
            records=records,
            catalogue_set_sha256=value["catalogue_set_sha256"],
            active_record_set_sha256=value["active_record_set_sha256"],
            choice_semantics_set_sha256=value["choice_semantics_set_sha256"],
            dependency_graph_sha256=value["dependency_graph_sha256"],
            lifecycle_ledger_sha256=value["lifecycle_ledger_sha256"],
            content_object_set_sha256=value["content_object_set_sha256"],
            content_resolver_binding_sha256=value["content_resolver_binding_sha256"],
            content_snapshot_sha256=value["content_snapshot_sha256"],
            dependency_edges=_normalise_edges(value["dependency_edges"], record_ids={row.choice_id for row in records}),
            vocabulary_authority_sha256=value["vocabulary_authority_sha256"],
        )
        validate_content_snapshot(snapshot)
        return snapshot


def _coerce_snapshot(value: FactoryContentSnapshot | Mapping[str, Any]) -> FactoryContentSnapshot:
    return value if isinstance(value, FactoryContentSnapshot) else FactoryContentSnapshot.from_mapping(value)


def _assert_parent_transition(parent: FactoryContentSnapshot | None, records: Sequence[ContentRecordCommitment], revision: int) -> None:
    if parent is None:
        if revision != 1:
            fail("DCC_SNAPSHOT_REVISION_INVALID", "The root content snapshot must have revision 1.")
        return
    if revision != parent.snapshot_revision + 1:
        fail("DCC_SNAPSHOT_REVISION_INVALID", "A child snapshot must be parent revision plus one.", details={"parent": parent.snapshot_revision, "incoming": revision})
    incoming = {row.choice_id: row for row in records}
    previous = parent.record_by_id()
    missing = sorted(set(previous) - set(incoming))
    if missing:
        fail("DCC_CONTENT_RECORD_REMOVAL", "Historical records must be retained as RETIRED or QUARANTINED.", details={"choice_ids": missing})
    for choice_id, old in previous.items():
        new = incoming[choice_id]
        if old.choice_kind != new.choice_kind:
            fail("DCC_CONTENT_KIND_CHANGE", "A conceptual kind change requires a new canonical choice ID.", details={"choice_id": choice_id})
        if old.lifecycle == "QUARANTINED" and new.lifecycle != "QUARANTINED":
            fail("DCC_CONTENT_QUARANTINE_RESTORE", "Quarantined content cannot be silently restored.", details={"choice_id": choice_id})


def build_content_snapshot(
    records: Sequence[ContentRecordCommitment | Mapping[str, Any]],
    *,
    catalogue_schema_versions: Mapping[str, int],
    rules_authority_sha256: str,
    required_compiler_profile_sha256: str,
    parent: FactoryContentSnapshot | Mapping[str, Any] | None = None,
    snapshot_revision: int | None = None,
    dependency_edges: Any = None,
    vocabulary_authority_sha256: str | None = None,
    content_resolver_binding: Mapping[str, Any] | None = None,
) -> FactoryContentSnapshot:
    """Build a new immutable admitted snapshot without mutating ``parent``."""

    normalized_records = tuple(sorted((_normalise_record(row) for row in records), key=lambda row: row.choice_id))
    if not normalized_records:
        fail("DCC_CONTENT_EMPTY", "An admitted snapshot must contain at least one typed record.")
    record_ids = {row.choice_id for row in normalized_records}
    if len(record_ids) != len(normalized_records):
        fail("DCC_CONTENT_DUPLICATE_CHOICE_ID", "A snapshot cannot contain duplicate choice IDs.")
    graph_input = dependency_edges
    if graph_input is None:
        graph_input = {row.choice_id: row.dependency_ids for row in normalized_records}
    edges = _normalise_edges(graph_input, record_ids=record_ids)
    parent_snapshot = _coerce_snapshot(parent) if parent is not None else None
    revision = snapshot_revision if snapshot_revision is not None else (parent_snapshot.snapshot_revision + 1 if parent_snapshot else 1)
    if not isinstance(revision, int) or isinstance(revision, bool):
        fail("DCC_SCHEMA_TYPE", "snapshot_revision must be an integer.")
    _assert_parent_transition(parent_snapshot, normalized_records, revision)
    if parent_snapshot is not None:
        previous_ids = set(parent_snapshot.record_by_id())
        for row in normalized_records:
            if row.choice_id not in previous_ids and row.lifecycle != "ACTIVE":
                fail("DCC_CONTENT_ADDITION_INVALID", "A newly added record must enter an admitted snapshot as ACTIVE.", details={"choice_id": row.choice_id})

    schema_versions = dict(catalogue_schema_versions)
    if not schema_versions:
        fail("DCC_CONTENT_SCHEMA_VERSIONS_EMPTY", "Every snapshot must bind at least one catalogue schema version.")
    for name, version in schema_versions.items():
        require_string(name, path="catalogue_schema_versions.name")
        require_type(version, int, path=f"catalogue_schema_versions.{name}")
        if version < 1:
            fail("DCC_SCHEMA_VALUE", "Catalogue schema versions must be positive.")
    _digest(rules_authority_sha256, "rules_authority_sha256")
    _digest(required_compiler_profile_sha256, "required_compiler_profile_sha256")
    if vocabulary_authority_sha256 is None:
        vocabulary_authority_sha256 = sha256_json({"schema": "TianxiaFoundry.CreativeVocabularyAuthority.v1", "version": 1, "vocabularies": {}, "adapter_version_sha256": None})
    _digest(vocabulary_authority_sha256, "vocabulary_authority_sha256")

    record_dicts = [row.to_dict() for row in normalized_records]
    active_records = [row.to_dict() for row in normalized_records if row.lifecycle == "ACTIVE"]
    catalogue_set_sha256 = sha256_json({
        "catalogue_schema_versions": dict(sorted(schema_versions.items())),
        # Keep semantic projections in their separate set commitment.  This
        # record commitment subset is therefore safe for ChoiceSemantics to
        # bind without creating a hash cycle.
        "active_record_commitments": [
            {key: row[key] for key in ("choice_id", "choice_kind", "choice_record_sha256", "typed_authority_sha256", "source_rights_receipt_sha256")}
            for row in active_records
        ],
    })
    active_record_set_sha256 = sha256_json(active_records)
    choice_semantics_set_sha256 = sha256_json([row["choice_semantics_sha256"] for row in active_records])
    dependency_graph_sha256 = _edge_hash(edges)
    lifecycle_ledger_sha256 = sha256_json([
        {"choice_id": row["choice_id"], "lifecycle": row["lifecycle"], "eligible_for_new_builds": row["eligible_for_new_builds"]}
        for row in record_dicts
    ])
    content_object_set_sha256 = sha256_json([
        {
            "choice_id": row["choice_id"],
            "choice_record_sha256": row["choice_record_sha256"],
            "typed_authority_sha256": row["typed_authority_sha256"],
            "choice_semantics_sha256": row["choice_semantics_sha256"],
            "source_rights_receipt_sha256": row["source_rights_receipt_sha256"],
        }
        for row in record_dicts
    ])
    resolver_payload = content_resolver_binding or {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_revision": revision,
        "content_object_set_sha256": content_object_set_sha256,
    }
    content_resolver_binding_sha256 = sha256_json(resolver_payload)
    unsigned = {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_revision": revision,
        "parent_content_snapshot_sha256": parent_snapshot.content_snapshot_sha256 if parent_snapshot else None,
        "admission_status": "ADMITTED",
        "catalogue_schema_versions": dict(sorted(schema_versions.items())),
        "rules_authority_sha256": rules_authority_sha256,
        "required_compiler_profile_sha256": required_compiler_profile_sha256,
        "records": record_dicts,
        "catalogue_set_sha256": catalogue_set_sha256,
        "active_record_set_sha256": active_record_set_sha256,
        "choice_semantics_set_sha256": choice_semantics_set_sha256,
        "dependency_graph_sha256": dependency_graph_sha256,
        "lifecycle_ledger_sha256": lifecycle_ledger_sha256,
        "content_object_set_sha256": content_object_set_sha256,
        "content_resolver_binding_sha256": content_resolver_binding_sha256,
        "dependency_edges": [{"dependent_choice_id": dependent, "dependency_choice_id": dependency} for dependent, dependency in edges],
        "vocabulary_authority_sha256": vocabulary_authority_sha256,
    }
    snapshot_hash = sha256_json(unsigned)
    return FactoryContentSnapshot(
        schema=SNAPSHOT_SCHEMA,
        snapshot_revision=revision,
        parent_content_snapshot_sha256=unsigned["parent_content_snapshot_sha256"],
        admission_status="ADMITTED",
        catalogue_schema_versions=tuple(sorted(schema_versions.items())),
        rules_authority_sha256=rules_authority_sha256,
        required_compiler_profile_sha256=required_compiler_profile_sha256,
        records=normalized_records,
        catalogue_set_sha256=catalogue_set_sha256,
        active_record_set_sha256=active_record_set_sha256,
        choice_semantics_set_sha256=choice_semantics_set_sha256,
        dependency_graph_sha256=dependency_graph_sha256,
        lifecycle_ledger_sha256=lifecycle_ledger_sha256,
        content_object_set_sha256=content_object_set_sha256,
        content_resolver_binding_sha256=content_resolver_binding_sha256,
        content_snapshot_sha256=snapshot_hash,
        dependency_edges=edges,
        vocabulary_authority_sha256=vocabulary_authority_sha256,
    )


def validate_content_snapshot(snapshot: FactoryContentSnapshot | Mapping[str, Any]) -> FactoryContentSnapshot:
    value = _coerce_snapshot(snapshot)
    object_value = value.to_dict()
    if object_value["parent_content_snapshot_sha256"] is not None:
        _digest(object_value["parent_content_snapshot_sha256"], "parent_content_snapshot_sha256")
    expected = sha256_json(without_hash(object_value, "content_snapshot_sha256"))
    if expected != value.content_snapshot_sha256:
        fail("DCC_CONTENT_SNAPSHOT_HASH_INVALID", "content_snapshot_sha256 does not match the immutable snapshot.")
    records = [row.to_dict() for row in value.records]
    active_records = [row for row in records if row["lifecycle"] == "ACTIVE"]
    expected_catalogue = sha256_json({
        "catalogue_schema_versions": dict(value.catalogue_schema_versions),
        "active_record_commitments": [
            {key: row[key] for key in ("choice_id", "choice_kind", "choice_record_sha256", "typed_authority_sha256", "source_rights_receipt_sha256")}
            for row in active_records
        ],
    })
    expected_active_records = sha256_json(active_records)
    expected_semantics = sha256_json([row["choice_semantics_sha256"] for row in active_records])
    expected_lifecycle = sha256_json([{key: row[key] for key in ("choice_id", "lifecycle", "eligible_for_new_builds")} for row in records])
    expected_objects = sha256_json([{key: row[key] for key in ("choice_id", "choice_record_sha256", "typed_authority_sha256", "choice_semantics_sha256", "source_rights_receipt_sha256")} for row in records])
    if value.catalogue_set_sha256 != expected_catalogue or value.active_record_set_sha256 != expected_active_records or value.choice_semantics_set_sha256 != expected_semantics:
        fail("DCC_CONTENT_COMMITMENT_INVALID", "A snapshot derived record commitment does not match its records.")
    if value.lifecycle_ledger_sha256 != expected_lifecycle or value.content_object_set_sha256 != expected_objects:
        fail("DCC_CONTENT_COMMITMENT_INVALID", "A snapshot lifecycle or object commitment does not match its records.")
    if value.dependency_graph_sha256 != _edge_hash(value.dependency_edges):
        fail("DCC_CONTENT_DEPENDENCY_HASH_INVALID", "The in-memory dependency graph does not match its commitment.")
    for row in value.records:
        if row.eligible_for_new_builds is not (row.lifecycle == "ACTIVE"):
            fail("DCC_CONTENT_LIFECYCLE_INVALID", "Record eligibility does not match lifecycle.")
    return value


def affected_dependency_closure(changed_choice_ids: Iterable[str], dependency_edges: Any) -> tuple[str, ...]:
    """Return changed records plus every transitive dependent in stable order."""

    normalized_changed = {require_string(choice_id, path="changed_choice_ids[]") for choice_id in changed_choice_ids}
    edges = _normalise_edges(dependency_edges)
    reverse: dict[str, set[str]] = {}
    for dependent, dependency in edges:
        reverse.setdefault(dependency, set()).add(dependent)
    closure = set(normalized_changed)
    queue = sorted(normalized_changed)
    while queue:
        dependency = queue.pop(0)
        for dependent in sorted(reverse.get(dependency, ())):
            if dependent not in closure:
                closure.add(dependent)
                queue.append(dependent)
        queue.sort()
    return tuple(sorted(closure))


def _global_change(from_snapshot: FactoryContentSnapshot, to_snapshot: FactoryContentSnapshot, kind: str, from_value: Any, to_value: Any) -> dict[str, Any]:
    return {"kind": kind, "from_sha256": sha256_json(from_value) if not isinstance(from_value, str) else from_value, "to_sha256": sha256_json(to_value) if not isinstance(to_value, str) else to_value}


@dataclass(frozen=True)
class ContentChangeSet:
    value: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deepcopy(self.value))
        require_exact_keys(self.value, {"schema", "from_content_snapshot_sha256", "to_content_snapshot_sha256", "added", "retired", "restored", "changed", "global_changes", "affected_choice_ids", "affected_dependency_closure_sha256", "content_change_set_sha256"}, path="content change set")
        if self.value["schema"] != CHANGE_SET_SCHEMA:
            fail("DCC_SCHEMA_VALUE", "Unsupported ContentChangeSet schema.")
        _digest(self.value["from_content_snapshot_sha256"], "content change set.from_content_snapshot_sha256")
        _digest(self.value["to_content_snapshot_sha256"], "content change set.to_content_snapshot_sha256")
        _digest(self.value["affected_dependency_closure_sha256"], "content change set.affected_dependency_closure_sha256")
        added = require_list(self.value["added"], path="content change set.added")
        for index, row in enumerate(added):
            require_exact_keys(row, {"choice_id", "choice_record_sha256"}, path=f"content change set.added[{index}]")
            require_string(row["choice_id"], path=f"content change set.added[{index}].choice_id")
            _digest(row["choice_record_sha256"], f"content change set.added[{index}].choice_record_sha256")
        retired = require_list(self.value["retired"], path="content change set.retired")
        for index, row in enumerate(retired):
            require_exact_keys(row, {"choice_id", "last_active_record_sha256", "replacement_choice_ids"}, path=f"content change set.retired[{index}]")
            require_string(row["choice_id"], path=f"content change set.retired[{index}].choice_id")
            _digest(row["last_active_record_sha256"], f"content change set.retired[{index}].last_active_record_sha256")
            _sorted_unique_strings(row["replacement_choice_ids"], path=f"content change set.retired[{index}].replacement_choice_ids")
        restored = require_list(self.value["restored"], path="content change set.restored")
        for index, row in enumerate(restored):
            require_exact_keys(row, {"choice_id", "restored_record_sha256"}, path=f"content change set.restored[{index}]")
            require_string(row["choice_id"], path=f"content change set.restored[{index}].choice_id")
            _digest(row["restored_record_sha256"], f"content change set.restored[{index}].restored_record_sha256")
        changed = require_list(self.value["changed"], path="content change set.changed")
        for index, row in enumerate(changed):
            require_exact_keys(row, {"choice_id", "from_choice_record_sha256", "to_choice_record_sha256", "change_classes", "migration_compatibility"}, path=f"content change set.changed[{index}]")
            require_string(row["choice_id"], path=f"content change set.changed[{index}].choice_id")
            _digest(row["from_choice_record_sha256"], f"content change set.changed[{index}].from_choice_record_sha256")
            _digest(row["to_choice_record_sha256"], f"content change set.changed[{index}].to_choice_record_sha256")
            classes = _sorted_unique_strings(row["change_classes"], path=f"content change set.changed[{index}].change_classes")
            if any(item not in CHANGE_CLASSES for item in classes):
                fail("DCC_SCHEMA_ENUM", "content change set has an unsupported change class.")
            require_enum(row["migration_compatibility"], {"UNCHANGED_BEHAVIOR", "REVALIDATE", "REPLACEMENT_REQUIRED"}, path=f"content change set.changed[{index}].migration_compatibility")
        globals_ = require_list(self.value["global_changes"], path="content change set.global_changes")
        for index, row in enumerate(globals_):
            require_exact_keys(row, {"kind", "from_sha256", "to_sha256"}, path=f"content change set.global_changes[{index}]")
            require_enum(row["kind"], {"RULES_AUTHORITY", "CATALOGUE_SCHEMA", "SEMANTICS_ADAPTER", "COMPILER_PROFILE"}, path=f"content change set.global_changes[{index}].kind")
            _digest(row["from_sha256"], f"content change set.global_changes[{index}].from_sha256")
            _digest(row["to_sha256"], f"content change set.global_changes[{index}].to_sha256")
        affected = _sorted_unique_strings(self.value["affected_choice_ids"], path="content change set.affected_choice_ids")
        if list(affected) != self.value["affected_choice_ids"]:
            fail("DCC_SCHEMA_ORDER", "affected_choice_ids must be sorted canonically.")
        if self.value["affected_dependency_closure_sha256"] != sha256_json(list(affected)):
            fail("DCC_CONTENT_CLOSURE_HASH_INVALID", "The affected dependency closure does not match its sealed digest.")
        validate_self_hash(self.value, "content_change_set_sha256", code="DCC_CONTENT_CHANGE_SET_HASH_INVALID")

    @property
    def sha256(self) -> str:
        return self.value["content_change_set_sha256"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.value)


def _coerce_change_set(value: ContentChangeSet | Mapping[str, Any]) -> ContentChangeSet:
    return value if isinstance(value, ContentChangeSet) else ContentChangeSet(value)


def build_content_change_set(
    from_snapshot: FactoryContentSnapshot | Mapping[str, Any],
    to_snapshot: FactoryContentSnapshot | Mapping[str, Any],
    *,
    change_class_overrides: Mapping[str, Sequence[str]] | None = None,
) -> ContentChangeSet:
    old = validate_content_snapshot(from_snapshot)
    new = validate_content_snapshot(to_snapshot)
    if new.parent_content_snapshot_sha256 != old.content_snapshot_sha256:
        fail("DCC_CONTENT_PARENT_BINDING", "The child change set must name the exact parent snapshot.")
    before = old.record_by_id()
    after = new.record_by_id()
    added = [
        {"choice_id": choice_id, "choice_record_sha256": after[choice_id].choice_record_sha256}
        for choice_id in sorted(set(after) - set(before))
    ]
    retired = [
        {"choice_id": choice_id, "last_active_record_sha256": before[choice_id].choice_record_sha256, "replacement_choice_ids": []}
        for choice_id in sorted(set(before) & set(after))
        if before[choice_id].lifecycle == "ACTIVE" and after[choice_id].lifecycle in {"RETIRED", "QUARANTINED"}
    ]
    restored = [
        {"choice_id": choice_id, "restored_record_sha256": after[choice_id].choice_record_sha256}
        for choice_id in sorted(set(before) & set(after))
        if before[choice_id].lifecycle == "RETIRED" and after[choice_id].lifecycle == "ACTIVE"
    ]
    overrides = change_class_overrides or {}
    changed: list[dict[str, Any]] = []
    old_edges = set(old.dependency_edges)
    new_edges = set(new.dependency_edges)
    for choice_id in sorted(set(before) & set(after)):
        old_row, new_row = before[choice_id], after[choice_id]
        classes: set[str] = set()
        # Derived classes are normative facts of the two record commitments.
        # Caller overrides can add a stricter classification, but can never
        # replace or erase a class proved by the changed bytes.
        if old_row.choice_record_sha256 != new_row.choice_record_sha256:
            classes.add("DISPLAY")
        if old_row.typed_authority_sha256 != new_row.typed_authority_sha256:
            classes.add("MECHANICS")
        if old_row.choice_semantics_sha256 != new_row.choice_semantics_sha256:
            classes.add("SEMANTICS")
        if old_row.source_rights_receipt_sha256 != new_row.source_rights_receipt_sha256:
            classes.add("AUTHORITY")
        if old_row.lifecycle != new_row.lifecycle:
            classes.add("LIFECYCLE")
        if choice_id in overrides:
            classes.update(require_enum(item, CHANGE_CLASSES, path=f"change_class_overrides.{choice_id}[]") for item in overrides[choice_id])
        old_record_edges = {(dependent, dependency) for dependent, dependency in old_edges if dependent == choice_id or dependency == choice_id}
        new_record_edges = {(dependent, dependency) for dependent, dependency in new_edges if dependent == choice_id or dependency == choice_id}
        if old_record_edges != new_record_edges:
            classes.add("DEPENDENCIES")
        if not classes:
            continue
        if classes <= {"DISPLAY", "LIFECYCLE"}:
            compatibility = "UNCHANGED_BEHAVIOR"
        elif "MECHANICS" in classes or "AUTHORITY" in classes or "DEPENDENCIES" in classes:
            compatibility = "REPLACEMENT_REQUIRED" if old_row.choice_kind != new_row.choice_kind else "REVALIDATE"
        else:
            compatibility = "REVALIDATE"
        changed.append({
            "choice_id": choice_id,
            "from_choice_record_sha256": old_row.choice_record_sha256,
            "to_choice_record_sha256": new_row.choice_record_sha256,
            "change_classes": sorted(classes),
            "migration_compatibility": compatibility,
        })

    globals_: list[dict[str, Any]] = []
    if old.rules_authority_sha256 != new.rules_authority_sha256:
        globals_.append(_global_change(old, new, "RULES_AUTHORITY", old.rules_authority_sha256, new.rules_authority_sha256))
    if old.required_compiler_profile_sha256 != new.required_compiler_profile_sha256:
        globals_.append(_global_change(old, new, "COMPILER_PROFILE", old.required_compiler_profile_sha256, new.required_compiler_profile_sha256))
    if dict(old.catalogue_schema_versions) != dict(new.catalogue_schema_versions):
        globals_.append(_global_change(old, new, "CATALOGUE_SCHEMA", dict(old.catalogue_schema_versions), dict(new.catalogue_schema_versions)))
    if (old.choice_semantics_set_sha256 != new.choice_semantics_set_sha256 or old.vocabulary_authority_sha256 != new.vocabulary_authority_sha256) and not any("SEMANTICS" in row["change_classes"] for row in changed):
        globals_.append(_global_change(old, new, "SEMANTICS_ADAPTER", old.choice_semantics_set_sha256, new.choice_semantics_set_sha256))
    base_ids = {row["choice_id"] for row in added} | {row["choice_id"] for row in retired} | {row["choice_id"] for row in restored} | {row["choice_id"] for row in changed}
    if globals_:
        affected = set(new.active_choice_ids)
    else:
        affected = set(affected_dependency_closure(base_ids, new.dependency_edges))
    closure = tuple(sorted(affected))
    unsigned = {
        "schema": CHANGE_SET_SCHEMA,
        "from_content_snapshot_sha256": old.content_snapshot_sha256,
        "to_content_snapshot_sha256": new.content_snapshot_sha256,
        "added": added,
        "retired": retired,
        "restored": restored,
        "changed": changed,
        "global_changes": sorted(globals_, key=lambda row: (row["kind"], row["from_sha256"], row["to_sha256"])),
        "affected_choice_ids": list(closure),
        "affected_dependency_closure_sha256": sha256_json(list(closure)),
    }
    return ContentChangeSet({**unsigned, "content_change_set_sha256": sha256_json(unsigned)})


@dataclass(frozen=True)
class MigrationReceipt:
    value: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deepcopy(self.value))
        require_exact_keys(self.value, {"schema", "character_id", "from_character_revision_sha256", "from_content_snapshot_sha256", "to_content_snapshot_sha256", "content_change_set_sha256", "migration_policy_sha256", "migration_intent_sha256", "selected_ai_identity_sha256", "affected_dependency_closure_sha256", "closure_handled_choice_ids", "preserved_choice_ids", "replacement_choice_events", "regenerated_surfaces", "validation_receipt_sha256s", "to_character_revision_sha256", "result", "migration_receipt_sha256"}, path="migration receipt")
        if self.value["schema"] != MIGRATION_RECEIPT_SCHEMA:
            fail("DCC_SCHEMA_VALUE", "Unsupported migration receipt schema.")
        for field in ("from_character_revision_sha256", "from_content_snapshot_sha256", "to_content_snapshot_sha256", "content_change_set_sha256", "migration_policy_sha256", "migration_intent_sha256", "selected_ai_identity_sha256", "affected_dependency_closure_sha256"):
            _digest(self.value[field], f"migration receipt.{field}")
        require_digest(self.value["to_character_revision_sha256"], path="migration receipt.to_character_revision_sha256", allow_none=True)
        require_enum(self.value["result"], MIGRATION_RESULTS, path="migration receipt.result")
        if self.value["result"] == "BLOCKED" and self.value["to_character_revision_sha256"] is not None:
            fail("DCC_MIGRATION_SOURCE_MUTATION", "A blocked migration cannot produce a target revision.")
        if self.value["result"] == "MIGRATED" and self.value["to_character_revision_sha256"] in {None, self.value["from_character_revision_sha256"]}:
            fail("DCC_MIGRATION_SOURCE_MUTATION", "A migrated character must have a distinct target revision hash.")
        handled = _sorted_unique_strings(self.value["closure_handled_choice_ids"], path="migration receipt.closure_handled_choice_ids")
        if list(handled) != self.value["closure_handled_choice_ids"]:
            fail("DCC_SCHEMA_ORDER", "closure_handled_choice_ids must be sorted canonically.")
        preserved = _sorted_unique_strings(self.value["preserved_choice_ids"], path="migration receipt.preserved_choice_ids")
        if list(preserved) != self.value["preserved_choice_ids"]:
            fail("DCC_SCHEMA_ORDER", "preserved_choice_ids must be sorted canonically.")
        if not set(preserved).issubset(set(handled)):
            fail("DCC_MIGRATION_CLOSURE_INVALID", "Preserved choices must be part of the handled dependency closure.")
        replacement_events = _sorted_unique_strings(self.value["replacement_choice_events"], path="migration receipt.replacement_choice_events")
        if list(replacement_events) != self.value["replacement_choice_events"]:
            fail("DCC_SCHEMA_ORDER", "replacement_choice_events must be sorted canonically.")
        for index, event_id in enumerate(replacement_events):
            require_identifier(event_id, path=f"migration receipt.replacement_choice_events[{index}]", prefix="dcc.event.")
        normalized_surfaces = _sorted_unique_strings(self.value["regenerated_surfaces"], path="migration receipt.regenerated_surfaces")
        if list(normalized_surfaces) != self.value["regenerated_surfaces"]:
            fail("DCC_SCHEMA_ORDER", "regenerated_surfaces must be sorted canonically.")
        receipts = self.value["validation_receipt_sha256s"]
        if not isinstance(receipts, list):
            fail("DCC_SCHEMA_TYPE", "migration receipt.validation_receipt_sha256s must be an array.")
        for index, receipt in enumerate(receipts):
            _digest(receipt, f"migration receipt.validation_receipt_sha256s[{index}]")
        surfaces = set(normalized_surfaces)
        if self.value["result"] == "BLOCKED":
            if handled or preserved or replacement_events or surfaces or receipts:
                fail("DCC_MIGRATION_EVIDENCE_ON_BLOCKED", "A blocked migration cannot claim closure, replacement, regeneration, or validation evidence.")
        else:
            if not handled:
                fail("DCC_MIGRATION_CLOSURE_INVALID", "A migrated character must include validated closure handling evidence.")
            if not preserved and not replacement_events:
                fail("DCC_MIGRATION_CLOSURE_INVALID", "A migrated character must prove preservation or replacement handling.")
            if not REQUIRED_MIGRATION_SURFACES.issubset(surfaces):
                fail("DCC_MIGRATION_SURFACES_INVALID", "A migrated character must regenerate every required downstream surface.", details={"required": sorted(REQUIRED_MIGRATION_SURFACES), "actual": sorted(surfaces)})
            if not receipts:
                fail("DCC_MIGRATION_VALIDATION_REQUIRED", "A migrated character must include nonempty validation receipts.")
        validate_self_hash(self.value, "migration_receipt_sha256", code="DCC_MIGRATION_RECEIPT_HASH_INVALID")

    @property
    def sha256(self) -> str:
        return self.value["migration_receipt_sha256"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.value)


def build_migration_receipt(
    *,
    character_id: str,
    from_character_revision_sha256: str,
    from_snapshot: FactoryContentSnapshot | Mapping[str, Any],
    to_snapshot: FactoryContentSnapshot | Mapping[str, Any],
    change_set: ContentChangeSet | Mapping[str, Any],
    migration_policy_sha256: str,
    migration_intent_sha256: str,
    selected_ai_identity_sha256: str,
    closure_handled_choice_ids: Iterable[str] = (),
    preserved_choice_ids: Iterable[str] = (),
    replacement_choice_events: Iterable[str] = (),
    regenerated_surfaces: Iterable[str] = (),
    validation_receipt_sha256s: Iterable[str] = (),
    to_character_revision_sha256: str | None = None,
    result: str = "MIGRATED",
) -> MigrationReceipt:
    old = validate_content_snapshot(from_snapshot)
    new = validate_content_snapshot(to_snapshot)
    changes = _coerce_change_set(change_set)
    if changes.value["from_content_snapshot_sha256"] != old.content_snapshot_sha256 or changes.value["to_content_snapshot_sha256"] != new.content_snapshot_sha256:
        fail("DCC_MIGRATION_BINDING", "The migration receipt must bind the exact content change set.")
    require_identifier(character_id, path="migration receipt.character_id")
    from_revision = _digest(from_character_revision_sha256, "from_character_revision_sha256")
    _digest(migration_policy_sha256, "migration_policy_sha256")
    _digest(migration_intent_sha256, "migration_intent_sha256")
    _digest(selected_ai_identity_sha256, "selected_ai_identity_sha256")
    closure = changes.value["affected_choice_ids"]
    handled = _sorted_unique_strings(closure_handled_choice_ids, path="closure_handled_choice_ids")
    preserved = _sorted_unique_strings(preserved_choice_ids, path="preserved_choice_ids")
    replacement = _sorted_unique_strings(replacement_choice_events, path="replacement_choice_events")
    surfaces = _sorted_unique_strings(regenerated_surfaces, path="regenerated_surfaces")
    receipts = tuple(sorted(_digest(item, f"validation_receipt_sha256s[{index}]") for index, item in enumerate(validation_receipt_sha256s)))
    require_enum(result, MIGRATION_RESULTS, path="result")
    if result == "MIGRATED":
        if old.content_snapshot_sha256 == new.content_snapshot_sha256:
            fail("DCC_MIGRATION_TARGET_INVALID", "A migrated character must bind a distinct target content snapshot.")
        if list(handled) != list(closure):
            fail("DCC_MIGRATION_CLOSURE_INVALID", "A migrated character must account for every affected dependency-closure choice.", details={"expected": closure, "actual": list(handled)})
        if not set(preserved).issubset(set(closure)):
            fail("DCC_MIGRATION_CLOSURE_INVALID", "Preserved choices must be within the affected dependency closure.")
        unresolved = len(set(closure) - set(preserved))
        if unresolved and len(replacement) < unresolved:
            fail("DCC_MIGRATION_CLOSURE_INVALID", "Replacement events do not cover every non-preserved closure choice.", details={"unpreserved_choice_count": unresolved, "replacement_event_count": len(replacement)})
        if not REQUIRED_MIGRATION_SURFACES.issubset(set(surfaces)):
            fail("DCC_MIGRATION_SURFACES_INVALID", "A migrated character must regenerate every required downstream surface.", details={"required": sorted(REQUIRED_MIGRATION_SURFACES), "actual": list(surfaces)})
        if not receipts:
            fail("DCC_MIGRATION_VALIDATION_REQUIRED", "A migrated character must include nonempty validation receipts.")
    elif handled or preserved or replacement or surfaces or receipts:
        fail("DCC_MIGRATION_EVIDENCE_ON_BLOCKED", "A blocked migration cannot claim closure, replacement, regeneration, or validation evidence.")
    unsigned = {
        "schema": MIGRATION_RECEIPT_SCHEMA,
        "character_id": character_id,
        "from_character_revision_sha256": from_revision,
        "from_content_snapshot_sha256": old.content_snapshot_sha256,
        "to_content_snapshot_sha256": new.content_snapshot_sha256,
        "content_change_set_sha256": changes.sha256,
        "migration_policy_sha256": migration_policy_sha256,
        "migration_intent_sha256": migration_intent_sha256,
        "selected_ai_identity_sha256": selected_ai_identity_sha256,
        "affected_dependency_closure_sha256": changes.value["affected_dependency_closure_sha256"],
        "closure_handled_choice_ids": list(handled),
        "preserved_choice_ids": list(preserved),
        "replacement_choice_events": list(replacement),
        "regenerated_surfaces": list(surfaces),
        "validation_receipt_sha256s": list(receipts),
        "to_character_revision_sha256": to_character_revision_sha256,
        "result": result,
    }
    return MigrationReceipt({**unsigned, "migration_receipt_sha256": sha256_json(unsigned)})


def _coerce_migration_receipt(value: MigrationReceipt | Mapping[str, Any]) -> MigrationReceipt:
    # Reconstruct even an existing instance: the frozen dataclass does not
    # freeze its public ``value`` mapping, so callers can mutate it after
    # construction.  The migration boundary must validate a detached copy.
    detached = value.to_dict() if isinstance(value, MigrationReceipt) else value
    return MigrationReceipt(detached)


def migrate_character_revision(
    source_revision: Mapping[str, Any],
    *,
    target_snapshot_sha256: str,
    from_snapshot: FactoryContentSnapshot | Mapping[str, Any] | None = None,
    to_snapshot: FactoryContentSnapshot | Mapping[str, Any] | None = None,
    change_set: ContentChangeSet | Mapping[str, Any] | None = None,
    migration_receipt: MigrationReceipt | Mapping[str, Any] | None = None,
    result: str = "MIGRATED",
) -> dict[str, Any]:
    """Return a detached revision projection; never update ``source_revision``.

    This helper is intentionally a small shadow seam.  MIGRATED projections
    require the exact validated source/target snapshots and deterministic
    change set; the production materializer remains outside Stage A.
    """

    if not isinstance(source_revision, Mapping):
        fail("DCC_SCHEMA_TYPE", "source_revision must be an object.")
    _digest(target_snapshot_sha256, "target_snapshot_sha256")
    copied = deepcopy(dict(source_revision))
    if result == "BLOCKED":
        return {"source_revision": deepcopy(dict(source_revision)), "target_revision": None, "result": "BLOCKED"}
    if result != "MIGRATED":
        fail("DCC_SCHEMA_ENUM", "Unsupported migration result.")
    source_snapshot_sha256 = source_revision.get("content_snapshot_sha256")
    if source_snapshot_sha256 is None:
        fail("DCC_MIGRATION_SOURCE_INVALID", "A migrated revision must identify its source content snapshot.")
    _digest(source_snapshot_sha256, "source_revision.content_snapshot_sha256")
    if source_snapshot_sha256 == target_snapshot_sha256:
        fail("DCC_MIGRATION_TARGET_INVALID", "A migrated revision must bind a distinct target content snapshot.")
    if from_snapshot is None or to_snapshot is None or change_set is None:
        fail(
            "DCC_MIGRATION_CONTEXT_REQUIRED",
            "A migrated revision requires the exact source and target snapshots and their ContentChangeSet.",
        )
    old_snapshot = validate_content_snapshot(from_snapshot)
    new_snapshot = validate_content_snapshot(to_snapshot)
    if old_snapshot.content_snapshot_sha256 != source_snapshot_sha256:
        fail("DCC_MIGRATION_CONTEXT_BINDING", "The supplied source snapshot does not match the source revision.")
    if new_snapshot.content_snapshot_sha256 != target_snapshot_sha256:
        fail("DCC_MIGRATION_CONTEXT_BINDING", "The supplied target snapshot does not match the requested target.")
    supplied_change_set = _coerce_change_set(change_set)
    expected_change_set = build_content_change_set(old_snapshot, new_snapshot)
    if supplied_change_set.to_dict() != expected_change_set.to_dict():
        fail(
            "DCC_MIGRATION_CHANGE_SET_INVALID",
            "The supplied ContentChangeSet is not the exact deterministic transition for the snapshots.",
            details={
                "expected_content_change_set_sha256": expected_change_set.sha256,
                "actual_content_change_set_sha256": supplied_change_set.sha256,
            },
        )
    if migration_receipt is None:
        fail("DCC_MIGRATION_RECEIPT_REQUIRED", "A migrated revision requires a validated MigrationReceipt.")
    receipt = _coerce_migration_receipt(migration_receipt)
    if receipt.value["result"] != "MIGRATED":
        fail("DCC_MIGRATION_RECEIPT_INVALID", "A migrated revision requires a MIGRATED MigrationReceipt.")
    declared_source_revision_sha256 = source_revision.get("character_revision_sha256")
    if declared_source_revision_sha256 is None:
        source_revision_sha256 = sha256_json(copied)
    else:
        _digest(declared_source_revision_sha256, "source_revision.character_revision_sha256")
        expected_source_revision_sha256 = sha256_json(without_hash(copied, "character_revision_sha256"))
        if declared_source_revision_sha256 != expected_source_revision_sha256:
            fail("DCC_MIGRATION_SOURCE_INVALID", "The source revision self-hash is invalid.")
        source_revision_sha256 = declared_source_revision_sha256
    if receipt.value["from_character_revision_sha256"] != source_revision_sha256:
        fail("DCC_MIGRATION_RECEIPT_BINDING", "The migration receipt is not bound to the exact source revision.")
    expected_receipt_binding = {
        "from_content_snapshot_sha256": old_snapshot.content_snapshot_sha256,
        "to_content_snapshot_sha256": new_snapshot.content_snapshot_sha256,
        "content_change_set_sha256": expected_change_set.sha256,
        "affected_dependency_closure_sha256": expected_change_set.value["affected_dependency_closure_sha256"],
        "closure_handled_choice_ids": expected_change_set.value["affected_choice_ids"],
    }
    actual_receipt_binding = {field: receipt.value[field] for field in expected_receipt_binding}
    if actual_receipt_binding != expected_receipt_binding:
        fail(
            "DCC_MIGRATION_RECEIPT_BINDING",
            "The migration receipt is not bound to the exact snapshots and deterministic content transition.",
            details={"expected": expected_receipt_binding, "actual": actual_receipt_binding},
        )
    target = deepcopy(dict(source_revision))
    target.pop("character_revision_sha256", None)
    target["content_snapshot_sha256"] = target_snapshot_sha256
    target["source_revision_sha256"] = source_revision_sha256
    target_revision_sha256 = sha256_json(target)
    if receipt.value["to_character_revision_sha256"] != target_revision_sha256:
        fail("DCC_MIGRATION_RECEIPT_BINDING", "The migration receipt target revision does not match the detached target projection.")
    target["character_revision_sha256"] = target_revision_sha256
    return {"source_revision": deepcopy(dict(source_revision)), "target_revision": target, "result": "MIGRATED"}


def valid_content_snapshot(value: FactoryContentSnapshot | Mapping[str, Any]) -> bool:
    try:
        validate_content_snapshot(value)
    except CreativeControllerError:
        return False
    return True


def valid_content_change_set(value: ContentChangeSet | Mapping[str, Any]) -> bool:
    try:
        _coerce_change_set(value)
    except CreativeControllerError:
        return False
    return True
