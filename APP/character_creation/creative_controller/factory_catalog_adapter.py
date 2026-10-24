"""Inactive publication compiler from Factory catalog authority to DCC semantics.

This module is deliberately data-driven.  It maps Factory content *types* to
the controller's stable choice kinds, but it has no branches for named game
systems, spheres, classes, or resources.  Chakra, Gu, and future systems use
the same reviewed semantic overlay contract as existing content.

Compilation creates a candidate for owner review.  It neither changes the
Factory trust manifest nor admits content into the live controller route.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from app.core import sha256_json
from contracts.canonical import canonical_record_hash

from .contracts import (
    fail,
    require_digest,
    require_exact_keys,
    require_identifier,
    require_list,
    require_string,
    require_type,
    validate_self_hash,
)
from .semantic_admission import (
    SEMANTIC_AUTHORITY_BUNDLE_SCHEMA,
    SEMANTIC_RECORD_AUTHORITY_SCHEMA,
    TYPED_SEMANTIC_RECORD_SCHEMA,
    build_semantic_authority_bundle,
    seal_typed_semantic_record,
    validate_semantic_authority_bundle,
    validate_semantic_profile_registry,
    validate_typed_semantic_record,
    _merge_fragments,
    _normalize_semantic_fragment,
    _resolved_profiles,
    _validate_fragment_vocabulary,
)


REVIEWED_SEMANTIC_OVERLAY_SCHEMA = "TianxiaFoundry.ReviewedSemanticOverlay.v1"
SOURCE_RIGHTS_RECEIPT_SCHEMA = "TianxiaFoundry.SourceRightsReceipt.v1"
SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA = "TianxiaFoundry.SourceRightsAuthorityTrustManifest.v1"
NON_CHOICE_DEPENDENCY_AUTHORITY_SCHEMA = "TianxiaFoundry.DCCNonChoiceDependencyAuthority.v1"
FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_SCHEMA = "TianxiaFoundry.DCCCatalogPublicationCandidate.v1"
FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_VERSION = 1
FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA = "TianxiaFoundry.DCCCatalogPublicationCandidate.v2"
FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION = 2
FACTORY_RULES_CATALOGUE_SCHEMA = "TianxiaFoundry.RulesCatalogRecord"
FACTORY_RULES_CATALOGUE_VERSION = 1

_CATALOG_RECORD_SCHEMA = "TianxiaFoundry.RulesCatalogRecord.v1"
_CONTENT_KIND = {
    "path": "path",
    "cultivation_method": "method",
    "foundation": "foundation",
    "background": "background",
    "origin_insight": "origin",
    "sphere": "sphere",
    "talent": "talent",
    "cultivation_insight": "insight",
    "path_feature": "milestone",
    "background_sphere": "sphere",
    "background_talent": "talent",
    "item": "item",
    "subpath": "path",
    "tradition": "path",
}
_OVERLAY_ROW_KEYS = {
    "choice_id",
    "choice_record_sha256",
    "source_rights_receipt_id",
    "profile_ids",
    "source_fact_ids",
    "semantics",
}
_SOURCE_FACT_KEYS = {"source_fact_id", "status", "source_projection_sha256"}
_FACT_STATUSES = {"VERIFIED", "DRAFT", "REVOKED"}
_RIGHTS_RECEIPT_KEYS = {
    "schema",
    "receipt_id",
    "status",
    "source_id",
    "source_hash",
    "allowed_uses",
    "rights_authority_id",
    "rights_authority_sha256",
    "receipt_sha256",
}
_RIGHTS_STATUSES = {"VERIFIED", "REVOKED"}
_RIGHTS_USE = "DCC_SEMANTIC_PUBLICATION"
_MAX_RECORDS = 8192
_MAX_FACTS = 16384
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "Rules_Catalog_Record.schema.json"
_SOURCE_RIGHTS_TRUST_PATH = Path(__file__).resolve().parents[2] / "authority" / "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json"
_NON_CHOICE_DEPENDENCY_AUTHORITY_PATH = (
    Path(__file__).resolve().parents[2]
    / "authority"
    / "Tianxia_DCC_NonChoice_Dependency_Authority_v1.json"
)
_NON_CHOICE_BINDING_KEYS = {
    "record_id",
    "content_type",
    "record_hash",
    "source_id",
    "source_hash",
    "non_choice_dependency_ids",
}


def _factory_raw_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the typed raw-record envelope without interpreting free text."""

    factory = (
        record.get("compatibility", {}).get("factory", {})
        if isinstance(record.get("compatibility"), Mapping)
        else {}
    )
    raw_projection = factory.get("raw_projection", {}) if isinstance(factory, Mapping) else {}
    if not isinstance(raw_projection, Mapping):
        return {}
    raw_record = raw_projection.get("raw_record")
    # Dependency omission authority is deliberately narrower than semantic
    # fact projection: only the explicitly typed raw_record envelope can
    # prove an automatic background route or path-feature shared rule.  Other
    # open-ended raw_projection keys are never allowed to suppress an
    # unresolved dependency.
    return raw_record if isinstance(raw_record, Mapping) else {}


def _typed_non_choice_dependency_ids(record: Mapping[str, Any]) -> set[str]:
    """Return structurally declared procedure dependencies from typed data.

    Factory exposes these modules as a typed list on content records.  Their
    canonical IDs are retained in the semantic source projection, but they
    are not selectable records in the admitted family set.  Only IDs present
    in that exact typed list receive this non-choice treatment; arbitrary
    dependency strings remain unresolved and block admission.
    """

    raw = _factory_raw_record(record)
    modules = raw.get("linked_procedure_modules")
    if not isinstance(modules, list):
        return set()
    result: set[str] = set()
    for index, module in enumerate(modules):
        if not isinstance(module, Mapping):
            fail("DCC_SCHEMA_TYPE", f"Factory raw projection linked_procedure_modules[{index}] must be an object.")
        result.add(require_identifier(module.get("canonical_id"), path=f"Factory raw projection linked_procedure_modules[{index}].canonical_id"))
    return result


def _choice_kind(record: Mapping[str, Any]) -> str | None:
    """Resolve a selectable semantic kind from the structural content type.

    The stable families are retained in ``_CONTENT_KIND``.  Unknown content
    types remain unsupported even when they carry other authority metadata;
    no record IDs or display labels participate in this decision.
    """

    content_type = record.get("content_type")
    return _CONTENT_KIND.get(content_type)


def _unique_strings(value: Any, *, path: str, identifiers: bool = False, maximum: int = 256) -> list[str]:
    rows = require_list(value, path=path, max_length=maximum)
    normalized = [
        require_identifier(item, path=f"{path}[{index}]")
        if identifiers
        else require_string(item, path=f"{path}[{index}]", max_length=500)
        for index, item in enumerate(rows)
    ]
    if len(normalized) != len(set(normalized)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must be duplicate-free.")
    return sorted(normalized)


def load_factory_non_choice_dependency_authority() -> dict[str, Any]:
    """Load the sealed, source-bound authority for automatic dependencies.

    A typed raw projection can describe a dependency, but it cannot grant
    omission authority by itself.  Omission is allowed only when this fixed
    checked-in authority contains an exact record/source commitment and exact
    dependency member for the current canonical record.
    """

    try:
        value = json.loads(_NON_CHOICE_DEPENDENCY_AUTHORITY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(
            "DCC_NON_CHOICE_DEPENDENCY_AUTHORITY_UNAVAILABLE",
            "Factory non-choice dependency authority is unavailable.",
            details={"error_type": type(exc).__name__},
        )
    require_exact_keys(
        value,
        {"schema", "version", "bindings", "authority_sha256"},
        path="Factory non-choice dependency authority",
    )
    if value["schema"] != NON_CHOICE_DEPENDENCY_AUTHORITY_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported Factory non-choice dependency authority schema.")
    version = require_type(value["version"], int, path="Factory non-choice dependency authority.version")
    if version < 1:
        fail("DCC_SCHEMA_VALUE", "Factory non-choice dependency authority version must be positive.")
    bindings: list[dict[str, Any]] = []
    for index, raw in enumerate(
        require_list(value["bindings"], path="Factory non-choice dependency authority.bindings", max_length=_MAX_RECORDS)
    ):
        path = f"Factory non-choice dependency authority.bindings[{index}]"
        require_exact_keys(raw, _NON_CHOICE_BINDING_KEYS, path=path)
        content_type = require_string(raw["content_type"], path=f"{path}.content_type")
        if content_type not in {"background", "path_feature"}:
            fail(
                "DCC_NON_CHOICE_DEPENDENCY_AUTHORITY_INVALID",
                "Non-choice dependency authority contains an unsupported content family.",
                details={"content_type": content_type},
            )
        bindings.append(
            {
                "record_id": require_identifier(raw["record_id"], path=f"{path}.record_id"),
                "content_type": content_type,
                "record_hash": require_digest(raw["record_hash"], path=f"{path}.record_hash"),
                "source_id": require_identifier(raw["source_id"], path=f"{path}.source_id"),
                "source_hash": require_digest(raw["source_hash"], path=f"{path}.source_hash"),
                "non_choice_dependency_ids": _unique_strings(
                    raw["non_choice_dependency_ids"],
                    path=f"{path}.non_choice_dependency_ids",
                    identifiers=True,
                    maximum=_MAX_RECORDS,
                ),
            }
        )
    if bindings != sorted(bindings, key=lambda row: row["record_id"]):
        fail(
            "DCC_NON_CHOICE_DEPENDENCY_AUTHORITY_NONCANONICAL",
            "Factory non-choice dependency authority bindings must be canonically ordered.",
        )
    if len({row["record_id"] for row in bindings}) != len(bindings):
        fail(
            "DCC_NON_CHOICE_DEPENDENCY_AUTHORITY_DUPLICATE",
            "Factory non-choice dependency authority record IDs must be unique.",
        )
    validate_self_hash(
        value,
        "authority_sha256",
        code="DCC_NON_CHOICE_DEPENDENCY_AUTHORITY_HASH_INVALID",
    )
    canonical = {
        "schema": NON_CHOICE_DEPENDENCY_AUTHORITY_SCHEMA,
        "version": version,
        "bindings": bindings,
    }
    rebuilt = {**canonical, "authority_sha256": sha256_json(canonical)}
    if rebuilt != dict(value):
        fail(
            "DCC_NON_CHOICE_DEPENDENCY_AUTHORITY_NONCANONICAL",
            "Factory non-choice dependency authority must use canonical ordering.",
        )
    return deepcopy(rebuilt)


def _normalize_source_fact(raw: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    require_exact_keys(raw, _SOURCE_FACT_KEYS, path=path)
    status = require_string(raw["status"], path=f"{path}.status")
    if status not in _FACT_STATUSES:
        fail("DCC_SCHEMA_ENUM", f"{path}.status is unsupported.", details={"status": status})
    return {
        "source_fact_id": require_string(raw["source_fact_id"], path=f"{path}.source_fact_id", max_length=500),
        "status": status,
        "source_projection_sha256": require_digest(raw["source_projection_sha256"], path=f"{path}.source_projection_sha256"),
    }


def seal_source_rights_receipt(data: Mapping[str, Any]) -> dict[str, Any]:
    """Seal one explicit source-bound rights decision for DCC publication."""

    require_exact_keys(data, _RIGHTS_RECEIPT_KEYS - {"receipt_sha256"}, path="source rights receipt input")
    if data["schema"] != SOURCE_RIGHTS_RECEIPT_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported source rights receipt schema.")
    status = require_string(data["status"], path="source rights receipt.status")
    if status not in _RIGHTS_STATUSES:
        fail("DCC_SCHEMA_ENUM", "Unsupported source rights receipt status.")
    allowed_uses = _unique_strings(data["allowed_uses"], path="source rights receipt.allowed_uses", identifiers=True, maximum=16)
    unsigned = {
        "schema": SOURCE_RIGHTS_RECEIPT_SCHEMA,
        "receipt_id": require_identifier(data["receipt_id"], path="source rights receipt.receipt_id"),
        "status": status,
        "source_id": require_identifier(data["source_id"], path="source rights receipt.source_id"),
        "source_hash": require_digest(data["source_hash"], path="source rights receipt.source_hash"),
        "allowed_uses": allowed_uses,
        "rights_authority_id": require_identifier(data["rights_authority_id"], path="source rights receipt.rights_authority_id"),
        "rights_authority_sha256": require_digest(data["rights_authority_sha256"], path="source rights receipt.rights_authority_sha256"),
    }
    return {**unsigned, "receipt_sha256": sha256_json(unsigned)}


def validate_source_rights_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _RIGHTS_RECEIPT_KEYS, path="source rights receipt")
    validate_self_hash(value, "receipt_sha256", code="DCC_SOURCE_RIGHTS_RECEIPT_HASH_INVALID")
    rebuilt = seal_source_rights_receipt({key: value[key] for key in value if key != "receipt_sha256"})
    if rebuilt != dict(value):
        fail("DCC_SOURCE_RIGHTS_RECEIPT_NONCANONICAL", "Source rights receipt must use canonical ordering.")
    return deepcopy(rebuilt)


def load_factory_source_rights_authority_trust() -> dict[str, Any]:
    """Load the fixed, server-owned authority allowed to issue rights receipts."""

    try:
        value = json.loads(_SOURCE_RIGHTS_TRUST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail("DCC_SOURCE_RIGHTS_TRUST_UNAVAILABLE", "Factory source-rights trust manifest is unavailable.", details={"error_type": type(exc).__name__})
    require_exact_keys(
        value,
        {
            "schema",
            "version",
            "status",
            "active_rights_authority_sha256",
            "revoked_rights_authority_sha256s",
            "manifest_sha256",
        },
        path="Factory source-rights trust manifest",
    )
    validate_self_hash(value, "manifest_sha256", code="DCC_SOURCE_RIGHTS_TRUST_HASH_INVALID")
    if value["schema"] != SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA or value["version"] != 1:
        fail("DCC_SCHEMA_VALUE", "Unsupported Factory source-rights trust manifest schema/version.")
    status = require_string(value["status"], path="Factory source-rights trust manifest.status")
    if status not in {"ACTIVE", "INACTIVE"}:
        fail("DCC_SCHEMA_ENUM", "Unsupported Factory source-rights trust status.")
    revoked = _unique_strings(
        value["revoked_rights_authority_sha256s"],
        path="Factory source-rights trust manifest.revoked_rights_authority_sha256s",
        maximum=_MAX_RECORDS,
    )
    for index, digest in enumerate(revoked):
        require_digest(digest, path=f"Factory source-rights trust manifest.revoked_rights_authority_sha256s[{index}]")
    active = value["active_rights_authority_sha256"]
    if status == "INACTIVE":
        if active is not None:
            fail("DCC_SOURCE_RIGHTS_TRUST_INVALID", "An inactive source-rights trust manifest cannot name an active authority.")
    else:
        active = require_digest(active, path="Factory source-rights trust manifest.active_rights_authority_sha256")
        if active in revoked:
            fail("DCC_SOURCE_RIGHTS_AUTHORITY_REVOKED", "The active source-rights authority has been revoked.")
    canonical = {
        "schema": SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA,
        "version": 1,
        "status": status,
        "active_rights_authority_sha256": active,
        "revoked_rights_authority_sha256s": revoked,
    }
    rebuilt = {**canonical, "manifest_sha256": sha256_json(canonical)}
    if rebuilt != dict(value):
        fail("DCC_SOURCE_RIGHTS_TRUST_NONCANONICAL", "Factory source-rights trust manifest must be canonical.")
    return deepcopy(rebuilt)


def build_reviewed_semantic_overlay(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and self-hash one human-reviewed semantic publication input."""

    require_exact_keys(
        data,
        {"schema", "version", "semantic_profile_registry_sha256", "source_facts", "source_rights_receipts", "records"},
        path="reviewed semantic overlay input",
    )
    if data["schema"] != REVIEWED_SEMANTIC_OVERLAY_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported reviewed semantic overlay schema.")
    version = require_type(data["version"], int, path="reviewed semantic overlay.version")
    if version < 1:
        fail("DCC_SCHEMA_VALUE", "Reviewed semantic overlay version must be positive.")
    facts = [
        _normalize_source_fact(raw, path=f"reviewed semantic overlay.source_facts[{index}]")
        for index, raw in enumerate(require_list(data["source_facts"], path="reviewed semantic overlay.source_facts", max_length=_MAX_FACTS))
    ]
    facts.sort(key=lambda row: row["source_fact_id"])
    if len({row["source_fact_id"] for row in facts}) != len(facts):
        fail("DCC_SEMANTIC_SOURCE_FACT_DUPLICATE", "Reviewed semantic source-fact IDs must be unique.")
    receipts = [
        validate_source_rights_receipt(raw)
        for raw in require_list(data["source_rights_receipts"], path="reviewed semantic overlay.source_rights_receipts", max_length=_MAX_RECORDS)
    ]
    receipts.sort(key=lambda row: row["receipt_id"])
    if len({row["receipt_id"] for row in receipts}) != len(receipts):
        fail("DCC_SOURCE_RIGHTS_RECEIPT_DUPLICATE", "Source rights receipt IDs must be unique.")

    records: list[dict[str, Any]] = []
    for index, raw in enumerate(require_list(data["records"], path="reviewed semantic overlay.records", max_length=_MAX_RECORDS)):
        path = f"reviewed semantic overlay.records[{index}]"
        require_exact_keys(raw, _OVERLAY_ROW_KEYS, path=path)
        records.append(
            {
                "choice_id": require_identifier(raw["choice_id"], path=f"{path}.choice_id"),
                "choice_record_sha256": require_digest(raw["choice_record_sha256"], path=f"{path}.choice_record_sha256"),
                "source_rights_receipt_id": require_identifier(raw["source_rights_receipt_id"], path=f"{path}.source_rights_receipt_id"),
                "profile_ids": _unique_strings(raw["profile_ids"], path=f"{path}.profile_ids", identifiers=True, maximum=64),
                "source_fact_ids": _unique_strings(raw["source_fact_ids"], path=f"{path}.source_fact_ids", maximum=1024),
                "semantics": deepcopy(raw["semantics"]),
            }
        )
    records.sort(key=lambda row: row["choice_id"])
    if len({row["choice_id"] for row in records}) != len(records):
        fail("DCC_CONTENT_DUPLICATE_CHOICE_ID", "Reviewed semantic overlay choice IDs must be unique.")
    unsigned = {
        "schema": REVIEWED_SEMANTIC_OVERLAY_SCHEMA,
        "version": version,
        "semantic_profile_registry_sha256": require_digest(
            data["semantic_profile_registry_sha256"], path="reviewed semantic overlay.semantic_profile_registry_sha256"
        ),
        "source_facts": facts,
        "source_rights_receipts": receipts,
        "records": records,
    }
    return {**unsigned, "overlay_sha256": sha256_json(unsigned)}


def validate_reviewed_semantic_overlay(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(
        value,
        {"schema", "version", "semantic_profile_registry_sha256", "source_facts", "source_rights_receipts", "records", "overlay_sha256"},
        path="reviewed semantic overlay",
    )
    validate_self_hash(value, "overlay_sha256", code="DCC_REVIEWED_SEMANTIC_OVERLAY_HASH_INVALID")
    rebuilt = build_reviewed_semantic_overlay({key: value[key] for key in value if key != "overlay_sha256"})
    if rebuilt != dict(value):
        fail("DCC_REVIEWED_SEMANTIC_OVERLAY_NONCANONICAL", "Reviewed semantic overlay must use canonical ordering.")
    return deepcopy(rebuilt)


def _catalog_validator() -> Draft202012Validator:
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail("DCC_FACTORY_CATALOG_SCHEMA_UNAVAILABLE", "Factory catalog schema is unavailable.", details={"error_type": type(exc).__name__})
    return Draft202012Validator(schema)


def _validate_catalog_record(raw: Mapping[str, Any], validator: Draft202012Validator, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        fail("DCC_SCHEMA_TYPE", f"Factory catalog record[{index}] must be an object.")
    record = deepcopy(dict(raw))
    errors = sorted(validator.iter_errors(record), key=lambda error: tuple(str(part) for part in error.absolute_path))
    if errors:
        error = errors[0]
        fail(
            "DCC_FACTORY_CATALOG_RECORD_INVALID",
            "Factory catalog record does not satisfy the canonical schema.",
            details={"record_id": record.get("record_id"), "path": list(error.absolute_path), "message": error.message},
        )
    if record["schema_version"] != _CATALOG_RECORD_SCHEMA or record["record_hash"] != canonical_record_hash(record):
        fail(
            "DCC_FACTORY_CATALOG_RECORD_HASH_INVALID",
            "Factory catalog record hash does not match its canonical bytes.",
            details={"record_id": record.get("record_id")},
        )
    return record


def _authority_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    factory = record["compatibility"]["factory"]
    return {
        "schema_version": record["schema_version"],
        "record_id": record["record_id"],
        "content_type": record["content_type"],
        "publication": deepcopy(record["publication"]),
        "content_binding": deepcopy(record["content_binding"]),
        "source": {
            "source_id": record["source"]["source_id"],
            "source_hash": record["source"]["source_hash"],
            "anchor": record["source"]["anchor"],
        },
        "legality": deepcopy(record["legality"]),
        "dependencies": sorted(record.get("dependencies", [])),
        "grants": deepcopy(record["grants"]),
        "execution_templates": deepcopy(record["execution_templates"]),
        "stage2_authority": deepcopy(factory.get("stage2_authority")) if isinstance(factory, Mapping) else None,
    }


def _non_choice_dependency_ids(
    record: Mapping[str, Any],
    *,
    authority_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> set[str]:
    """Return exact sealed non-choice dependencies for one canonical record."""

    if authority_bindings is None:
        authority = load_factory_non_choice_dependency_authority()
        authority_bindings = {row["record_id"]: row for row in authority["bindings"]}
    binding = authority_bindings.get(record.get("record_id"))
    if not isinstance(binding, Mapping):
        return set()
    if (
        binding.get("content_type") != record.get("content_type")
        or binding.get("record_hash") != record.get("record_hash")
        or binding.get("source_id") != record.get("source", {}).get("source_id")
        or binding.get("source_hash") != record.get("source", {}).get("source_hash")
    ):
        return set()
    return set(binding["non_choice_dependency_ids"])


def _dependency_ids(
    record: Mapping[str, Any],
    *,
    selectable_record_ids: set[str] | None = None,
    non_choice_authority_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    result = set(record.get("dependencies", []))
    for prerequisite in record["legality"]["prerequisites"]:
        if prerequisite["operator"] in {"requires", "one_of", "all_of"}:
            result.add(prerequisite["target_id"])
    result.discard(record["record_id"])
    if selectable_record_ids is not None:
        non_choice = _non_choice_dependency_ids(record, authority_bindings=non_choice_authority_bindings)
        non_choice |= _typed_non_choice_dependency_ids(record)
        result = {dependency for dependency in result if dependency in selectable_record_ids or dependency not in non_choice}
    return sorted(result)


def _lifecycle(publication_status: str) -> str:
    return {"published": "ACTIVE", "deprecated": "RETIRED", "draft": "QUARANTINED", "validated": "QUARANTINED"}[publication_status]


def _semantic_evidence_ids(fragment: Mapping[str, Any]) -> set[str]:
    if not isinstance(fragment, Mapping):
        return set()
    result: set[str] = set()
    for collection in (fragment.get("synergy_edges", []), fragment.get("tradeoffs", [])):
        if isinstance(collection, list):
            for row in collection:
                if isinstance(row, Mapping) and isinstance(row.get("source_fact_ids"), list):
                    result.update(item for item in row["source_fact_ids"] if isinstance(item, str))
    return result


def _diagnostic(code: str, *, choice_id: str | None = None, values: Sequence[str] = ()) -> dict[str, Any]:
    return {"code": code, "choice_id": choice_id, "values": sorted(set(values))}


def _dependency_cycle_nodes(typed_records: Sequence[Mapping[str, Any]]) -> set[str]:
    graph = {row["choice_id"]: set(row["dependency_ids"]) for row in typed_records}
    visiting: list[str] = []
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(choice_id: str) -> None:
        if choice_id in visited:
            return
        if choice_id in visiting:
            cycle_nodes.update(visiting[visiting.index(choice_id) :])
            return
        visiting.append(choice_id)
        for dependency in sorted(graph.get(choice_id, ())):
            if dependency in graph:
                visit(dependency)
        visiting.pop()
        visited.add(choice_id)

    for choice_id in sorted(graph):
        visit(choice_id)
    return cycle_nodes


def _compile_factory_catalog_publication(
    catalog_records: Sequence[Mapping[str, Any]],
    semantic_profile_registry: Mapping[str, Any],
    reviewed_overlay: Mapping[str, Any],
    *,
    rights_trust: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile an immutable, inactive semantic authority publication candidate.

    Structural corruption raises immediately.  Review incompleteness returns a
    deterministic ``BLOCKED`` candidate with bounded diagnostics.
    """

    registry = validate_semantic_profile_registry(semantic_profile_registry)
    overlay = validate_reviewed_semantic_overlay(reviewed_overlay)
    rights_trust = (
        load_factory_source_rights_authority_trust()
        if rights_trust is None
        else deepcopy(dict(rights_trust))
    )
    non_choice_authority = load_factory_non_choice_dependency_authority()
    non_choice_authority_bindings = {
        row["record_id"]: row for row in non_choice_authority["bindings"]
    }
    if not isinstance(catalog_records, Sequence) or isinstance(catalog_records, (str, bytes, bytearray)):
        fail("DCC_SCHEMA_TYPE", "Factory catalog publication.records must be a bounded sequence.")
    if len(catalog_records) > _MAX_RECORDS:
        fail("DCC_SCHEMA_LIMIT", "Factory catalog publication.records exceeds its item limit.", details={"maximum": _MAX_RECORDS})
    raw_records = list(catalog_records)
    if not raw_records:
        fail("DCC_CONTENT_EMPTY", "Factory catalog publication requires at least one canonical record.")
    validator = _catalog_validator()
    records = [_validate_catalog_record(raw, validator, index=index) for index, raw in enumerate(raw_records)]
    records.sort(key=lambda row: row["record_id"])
    if len({row["record_id"] for row in records}) != len(records):
        fail("DCC_CONTENT_DUPLICATE_CHOICE_ID", "Factory catalog record IDs must be unique.")

    diagnostics: list[dict[str, Any]] = []
    active_rights_authority = rights_trust["active_rights_authority_sha256"]
    if rights_trust["status"] != "ACTIVE":
        diagnostics.append(_diagnostic("DCC_SOURCE_RIGHTS_AUTHORITY_UNPUBLISHED"))
    if overlay["semantic_profile_registry_sha256"] != registry["registry_sha256"]:
        diagnostics.append(_diagnostic("DCC_SEMANTIC_PROFILE_AUTHORITY_STALE"))
    fact_map = {row["source_fact_id"]: row for row in overlay["source_facts"]}
    receipt_map = {row["receipt_id"]: row for row in overlay["source_rights_receipts"]}
    profile_map = {row["profile_id"]: row for row in registry["profiles"]}
    resolved_profiles = _resolved_profiles(registry)
    for profile in registry["profiles"]:
        evidence = set(profile["source_fact_ids"]) | _semantic_evidence_ids(profile)
        missing = sorted(evidence - set(fact_map))
        unverified = sorted(fact for fact in evidence & set(fact_map) if fact_map[fact]["status"] != "VERIFIED")
        if missing:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_SOURCE_FACT_UNKNOWN", choice_id=profile["profile_id"], values=missing))
        if unverified:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_SOURCE_FACT_UNVERIFIED", choice_id=profile["profile_id"], values=unverified))

    overlay_map = {row["choice_id"]: row for row in overlay["records"]}
    record_ids = {row["record_id"] for row in records}
    selectable_record_ids = {row["record_id"] for row in records if _choice_kind(row) is not None}
    extra_overlay = sorted(set(overlay_map) - record_ids)
    for choice_id in extra_overlay:
        diagnostics.append(_diagnostic("DCC_REVIEWED_OVERLAY_ORPHAN", choice_id=choice_id))

    typed_records: list[dict[str, Any]] = []
    record_authorities: list[dict[str, Any]] = []
    used_receipt_ids: set[str] = set()
    for record in records:
        choice_id = record["record_id"]
        choice_kind = _choice_kind(record)
        if choice_kind is None:
            diagnostics.append(_diagnostic("DCC_FACTORY_CONTENT_TYPE_UNSUPPORTED", choice_id=choice_id, values=[record["content_type"]]))
            continue
        row = overlay_map.get(choice_id)
        if row is None:
            diagnostics.append(_diagnostic("DCC_REVIEWED_OVERLAY_MISSING", choice_id=choice_id))
            continue
        if row["choice_record_sha256"] != record["record_hash"]:
            diagnostics.append(_diagnostic("DCC_REVIEWED_OVERLAY_STALE", choice_id=choice_id))
            continue
        receipt = receipt_map.get(row["source_rights_receipt_id"])
        if receipt is None:
            diagnostics.append(_diagnostic("DCC_SOURCE_RIGHTS_RECEIPT_MISSING", choice_id=choice_id, values=[row["source_rights_receipt_id"]]))
            continue
        rights_failures: list[str] = []
        if receipt["status"] != "VERIFIED":
            rights_failures.append("status")
        if receipt["source_id"] != record["source"]["source_id"]:
            rights_failures.append("source_id")
        if receipt["source_hash"] != record["source"]["source_hash"]:
            rights_failures.append("source_hash")
        if _RIGHTS_USE not in receipt["allowed_uses"]:
            rights_failures.append("allowed_uses")
        if active_rights_authority is not None and receipt["rights_authority_sha256"] != active_rights_authority:
            rights_failures.append("rights_authority_sha256")
        if rights_failures:
            diagnostics.append(_diagnostic("DCC_SOURCE_RIGHTS_RECEIPT_INVALID", choice_id=choice_id, values=rights_failures))
            continue
        unknown_profiles = sorted(set(row["profile_ids"]) - set(profile_map))
        if unknown_profiles:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_PROFILE_UNKNOWN", choice_id=choice_id, values=unknown_profiles))
            continue
        evidence = set(row["source_fact_ids"]) | _semantic_evidence_ids(row["semantics"])
        missing = sorted(evidence - set(fact_map))
        unverified = sorted(fact for fact in evidence & set(fact_map) if fact_map[fact]["status"] != "VERIFIED")
        uncovered = sorted(_semantic_evidence_ids(row["semantics"]) - set(row["source_fact_ids"]))
        if missing:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_SOURCE_FACT_UNKNOWN", choice_id=choice_id, values=missing))
        if unverified:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_SOURCE_FACT_UNVERIFIED", choice_id=choice_id, values=unverified))
        if uncovered:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_EVIDENCE_UNBOUND", choice_id=choice_id, values=uncovered))
        if not row["source_fact_ids"]:
            diagnostics.append(_diagnostic("DCC_CHOICE_SEMANTICS_INCOMPLETE", choice_id=choice_id))
        if missing or unverified or uncovered or not row["source_fact_ids"]:
            continue

        projection = _authority_projection(record)
        typed = seal_typed_semantic_record(
            {
                "schema": TYPED_SEMANTIC_RECORD_SCHEMA,
                "choice_id": choice_id,
                "choice_kind": choice_kind,
                "lifecycle": _lifecycle(record["publication"]["status"]),
                "eligible_for_new_builds": record["publication"]["status"] == "published",
                "catalogue_schema": FACTORY_RULES_CATALOGUE_SCHEMA,
                "catalogue_schema_version": FACTORY_RULES_CATALOGUE_VERSION,
                "choice_record_sha256": record["record_hash"],
                "typed_authority_sha256": sha256_json(projection),
                "source_rights_receipt_sha256": receipt["receipt_sha256"],
                "profile_ids": row["profile_ids"],
                "source_fact_ids": row["source_fact_ids"],
                "semantics": row["semantics"],
                "dependency_ids": _dependency_ids(
                    record,
                    selectable_record_ids=selectable_record_ids,
                    non_choice_authority_bindings=non_choice_authority_bindings,
                ),
            }
        )
        record_fragment = _normalize_semantic_fragment(row["semantics"], path=f"reviewed semantic overlay record {choice_id}.semantics")
        merged = _merge_fragments(
            [*(resolved_profiles[profile_id]["semantics"] for profile_id in row["profile_ids"]), record_fragment],
            path=f"reviewed semantic overlay record {choice_id}",
        )
        _validate_fragment_vocabulary(merged, registry["vocabulary_authority"]["vocabularies"], path=f"reviewed semantic overlay record {choice_id}")
        required_scalars = (
            merged["resource_loop"]["cadence"],
            merged["resource_loop"]["setup"],
            merged["progression"]["minimum_cl"],
            merged["progression"]["identity_online_cl"],
            merged["progression"]["signature_cl"],
            merged["complexity"]["band"],
        )
        if any(value is None for value in required_scalars) or not merged["role_tags"] or not merged["capability_families"]:
            diagnostics.append(_diagnostic("DCC_CHOICE_SEMANTICS_INCOMPLETE", choice_id=choice_id))
            continue
        progression = merged["progression"]
        if not (progression["minimum_cl"] <= progression["identity_online_cl"] <= progression["signature_cl"]):
            diagnostics.append(_diagnostic("DCC_CHOICE_SEMANTICS_PROGRESSION_INVALID", choice_id=choice_id))
            continue
        semantic_targets = sorted({edge["target_choice_id"] for edge in merged["synergy_edges"]} - record_ids)
        if semantic_targets:
            diagnostics.append(_diagnostic("DCC_SEMANTIC_TARGET_UNRESOLVED", choice_id=choice_id, values=semantic_targets))
        typed_records.append(typed)
        used_receipt_ids.add(receipt["receipt_id"])
        authority_unsigned = {
            "schema": SEMANTIC_RECORD_AUTHORITY_SCHEMA,
            "status": "VERIFIED",
            "choice_id": typed["choice_id"],
            "choice_record_sha256": typed["choice_record_sha256"],
            "typed_authority_sha256": typed["typed_authority_sha256"],
            "source_rights_receipt_sha256": typed["source_rights_receipt_sha256"],
            "record_projection_sha256": typed["record_projection_sha256"],
            "profile_ids": typed["profile_ids"],
            "source_fact_ids": typed["source_fact_ids"],
        }
        record_authorities.append({**authority_unsigned, "authority_sha256": sha256_json(authority_unsigned)})

    typed_ids = {row["choice_id"] for row in typed_records}
    for typed in typed_records:
        unresolved = sorted(set(typed["dependency_ids"]) - typed_ids)
        if unresolved:
            diagnostics.append(_diagnostic("DCC_FACTORY_DEPENDENCY_UNRESOLVED", choice_id=typed["choice_id"], values=unresolved))
    for choice_id in sorted(_dependency_cycle_nodes(typed_records)):
        diagnostics.append(_diagnostic("DCC_FACTORY_DEPENDENCY_CYCLE", choice_id=choice_id))

    diagnostics.sort(key=lambda row: (row["code"], row["choice_id"] or "", row["values"]))
    status = "READY_FOR_OWNER_REVIEW" if not diagnostics and len(typed_records) == len(records) else "BLOCKED"
    authority_bundle = None
    if status == "READY_FOR_OWNER_REVIEW":
        authority_bundle = build_semantic_authority_bundle(
            {
                "schema": SEMANTIC_AUTHORITY_BUNDLE_SCHEMA,
                "version": overlay["version"],
                "semantic_profile_registry_sha256": registry["registry_sha256"],
                "source_facts": overlay["source_facts"],
                "record_authorities": record_authorities,
            }
        )
    record_set = [{"record_id": row["record_id"], "record_hash": row["record_hash"]} for row in records]
    unsigned = {
        "schema": FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA,
        "version": FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION,
        "status": status,
        "catalogue_schema": FACTORY_RULES_CATALOGUE_SCHEMA,
        "catalogue_schema_version": FACTORY_RULES_CATALOGUE_VERSION,
        "semantic_profile_registry_sha256": registry["registry_sha256"],
        "canonical_record_set_sha256": sha256_json(record_set),
        "reviewed_overlay_sha256": overlay["overlay_sha256"],
        "source_rights_authority_sha256": active_rights_authority,
        "source_rights_receipts": [receipt_map[receipt_id] for receipt_id in sorted(used_receipt_ids)],
        "typed_records": sorted(typed_records, key=lambda row: row["choice_id"]),
        "authority_bundle": authority_bundle,
        "diagnostics": diagnostics,
        "activation_policy": "INACTIVE_REQUIRES_OWNER_PUBLICATION",
    }
    return _validate_factory_catalog_publication_candidate(
        {**unsigned, "candidate_sha256": sha256_json(unsigned)},
        rights_trust=rights_trust,
    )


def compile_factory_catalog_publication(
    catalog_records: Sequence[Mapping[str, Any]],
    semantic_profile_registry: Mapping[str, Any],
    reviewed_overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile using the fixed production source-rights trust root.

    The publication workflow uses the private helper above with an in-memory
    proposed trust document during preflight.  Keeping this public wrapper
    trust-root-free preserves the existing fixed-trust runtime API.
    """

    return _compile_factory_catalog_publication(catalog_records, semantic_profile_registry, reviewed_overlay)


def _validate_factory_catalog_publication_candidate(
    value: Mapping[str, Any],
    *,
    rights_trust: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a detached publication candidate before review or storage."""

    required = {
        "schema",
        "version",
        "status",
        "catalogue_schema",
        "catalogue_schema_version",
        "semantic_profile_registry_sha256",
        "canonical_record_set_sha256",
        "reviewed_overlay_sha256",
        "source_rights_authority_sha256",
        "source_rights_receipts",
        "typed_records",
        "authority_bundle",
        "diagnostics",
        "activation_policy",
        "candidate_sha256",
    }
    require_exact_keys(value, required, path="Factory catalog publication candidate")
    validate_self_hash(value, "candidate_sha256", code="DCC_FACTORY_PUBLICATION_CANDIDATE_HASH_INVALID")
    if (value["schema"], value["version"]) not in {
        (FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_SCHEMA, FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_VERSION),
        (FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA, FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION),
    }:
        fail("DCC_SCHEMA_VALUE", "Unsupported Factory catalog publication candidate schema/version.")
    if value["catalogue_schema"] != FACTORY_RULES_CATALOGUE_SCHEMA or value["catalogue_schema_version"] != FACTORY_RULES_CATALOGUE_VERSION:
        fail("DCC_SCHEMA_VALUE", "Unsupported Factory catalogue binding.")
    for key in ("semantic_profile_registry_sha256", "canonical_record_set_sha256", "reviewed_overlay_sha256"):
        require_digest(value[key], path=f"Factory catalog publication candidate.{key}")
    rights_authority = require_digest(
        value["source_rights_authority_sha256"],
        path="Factory catalog publication candidate.source_rights_authority_sha256",
        allow_none=True,
    )
    if value["activation_policy"] != "INACTIVE_REQUIRES_OWNER_PUBLICATION":
        fail("DCC_FACTORY_PUBLICATION_ACTIVATION_INVALID", "A compiled publication candidate must remain inactive.")
    status = require_string(value["status"], path="Factory catalog publication candidate.status")
    if status not in {"READY_FOR_OWNER_REVIEW", "BLOCKED"}:
        fail("DCC_SCHEMA_ENUM", "Unsupported Factory catalog publication candidate status.")
    typed = [validate_typed_semantic_record(row) for row in require_list(value["typed_records"], path="Factory catalog publication candidate.typed_records", max_length=_MAX_RECORDS)]
    if typed != sorted(typed, key=lambda row: row["choice_id"]) or len({row["choice_id"] for row in typed}) != len(typed):
        fail("DCC_FACTORY_PUBLICATION_CANDIDATE_NONCANONICAL", "Candidate typed records must be unique and canonically ordered.")
    receipts = [
        validate_source_rights_receipt(row)
        for row in require_list(value["source_rights_receipts"], path="Factory catalog publication candidate.source_rights_receipts", max_length=_MAX_RECORDS)
    ]
    if receipts != sorted(receipts, key=lambda row: row["receipt_id"]) or len({row["receipt_id"] for row in receipts}) != len(receipts):
        fail("DCC_FACTORY_PUBLICATION_CANDIDATE_NONCANONICAL", "Candidate rights receipts must be unique and canonically ordered.")
    receipt_hashes = {row["receipt_sha256"] for row in receipts}
    typed_receipt_hashes = {row["source_rights_receipt_sha256"] for row in typed}
    if typed_receipt_hashes != receipt_hashes:
        fail(
            "DCC_FACTORY_PUBLICATION_CANDIDATE_RIGHTS_UNBOUND",
            "Candidate rights receipts must exactly match its typed record references.",
            details={"missing": sorted(typed_receipt_hashes - receipt_hashes), "orphan": sorted(receipt_hashes - typed_receipt_hashes)},
        )
    if rights_authority is not None and any(row["rights_authority_sha256"] != rights_authority for row in receipts):
        fail("DCC_FACTORY_PUBLICATION_CANDIDATE_RIGHTS_UNBOUND", "Candidate rights receipts do not bind its source-rights authority.")
    diagnostics = require_list(value["diagnostics"], path="Factory catalog publication candidate.diagnostics", max_length=_MAX_RECORDS * 4)
    for index, row in enumerate(diagnostics):
        require_exact_keys(row, {"code", "choice_id", "values"}, path=f"Factory catalog publication candidate.diagnostics[{index}]")
        require_identifier(row["code"], path=f"Factory catalog publication candidate.diagnostics[{index}].code")
        if row["choice_id"] is not None:
            require_identifier(row["choice_id"], path=f"Factory catalog publication candidate.diagnostics[{index}].choice_id")
        normalized_values = _unique_strings(row["values"], path=f"Factory catalog publication candidate.diagnostics[{index}].values", maximum=1024)
        if normalized_values != row["values"]:
            fail("DCC_FACTORY_PUBLICATION_CANDIDATE_NONCANONICAL", "Candidate diagnostic values must be canonically ordered.")
    if diagnostics != sorted(diagnostics, key=lambda row: (row["code"], row["choice_id"] or "", row["values"])):
        fail("DCC_FACTORY_PUBLICATION_CANDIDATE_NONCANONICAL", "Candidate diagnostics must be canonically ordered.")
    if status == "READY_FOR_OWNER_REVIEW":
        if diagnostics or value["authority_bundle"] is None or rights_authority is None:
            fail("DCC_FACTORY_PUBLICATION_CANDIDATE_INVALID", "A ready candidate requires an authority bundle and no diagnostics.")
        current_rights_trust = (
            load_factory_source_rights_authority_trust()
            if rights_trust is None
            else deepcopy(dict(rights_trust))
        )
        if current_rights_trust["status"] != "ACTIVE":
            fail("DCC_SOURCE_RIGHTS_AUTHORITY_UNPUBLISHED", "Factory has not published an active source-rights authority.")
        if rights_authority != current_rights_trust["active_rights_authority_sha256"]:
            fail("DCC_SOURCE_RIGHTS_AUTHORITY_TRUST_MISMATCH", "Candidate source-rights authority does not match the fixed Factory trust root.")
        bundle = validate_semantic_authority_bundle(value["authority_bundle"])
        if bundle["semantic_profile_registry_sha256"] != value["semantic_profile_registry_sha256"]:
            fail("DCC_FACTORY_PUBLICATION_CANDIDATE_AUTHORITY_UNBOUND", "Candidate authority bundle does not bind its profile registry.")
        authorities = {row["choice_id"]: row for row in bundle["record_authorities"]}
        expected_authorities: dict[str, dict[str, Any]] = {}
        for row in typed:
            unsigned_authority = {
                "schema": SEMANTIC_RECORD_AUTHORITY_SCHEMA,
                "status": "VERIFIED",
                "choice_id": row["choice_id"],
                "choice_record_sha256": row["choice_record_sha256"],
                "typed_authority_sha256": row["typed_authority_sha256"],
                "source_rights_receipt_sha256": row["source_rights_receipt_sha256"],
                "record_projection_sha256": row["record_projection_sha256"],
                "profile_ids": row["profile_ids"],
                "source_fact_ids": row["source_fact_ids"],
            }
            expected_authorities[row["choice_id"]] = {**unsigned_authority, "authority_sha256": sha256_json(unsigned_authority)}
        if authorities != expected_authorities:
            fail("DCC_FACTORY_PUBLICATION_CANDIDATE_AUTHORITY_UNBOUND", "Candidate authority bundle does not exactly bind its typed records.")
    elif value["authority_bundle"] is not None or not diagnostics:
        fail("DCC_FACTORY_PUBLICATION_CANDIDATE_INVALID", "A blocked candidate requires diagnostics and cannot carry an authority bundle.")
    return deepcopy(dict(value))


def validate_factory_catalog_publication_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate using the fixed production source-rights trust root."""

    return _validate_factory_catalog_publication_candidate(value)


__all__ = [
    "FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA",
    "FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION",
    "FACTORY_RULES_CATALOGUE_SCHEMA",
    "FACTORY_RULES_CATALOGUE_VERSION",
    "NON_CHOICE_DEPENDENCY_AUTHORITY_SCHEMA",
    "REVIEWED_SEMANTIC_OVERLAY_SCHEMA",
    "SOURCE_RIGHTS_RECEIPT_SCHEMA",
    "SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA",
    "build_reviewed_semantic_overlay",
    "compile_factory_catalog_publication",
    "load_factory_non_choice_dependency_authority",
    "load_factory_source_rights_authority_trust",
    "seal_source_rights_receipt",
    "validate_factory_catalog_publication_candidate",
    "validate_reviewed_semantic_overlay",
    "validate_source_rights_receipt",
]
