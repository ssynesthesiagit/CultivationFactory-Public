"""Deterministic, source-backed semantic inputs for Factory catalog records.

This module is intentionally small and data-owned.  It projects only typed
catalog fields into the DCC semantic contract; names, summaries, descriptions,
source text, embeddings, and generated prose never participate in a semantic
row or its source-fact commitment.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from app.core import sha256_json

from .contracts import (
    fail,
    require_digest,
    require_identifier,
)
from .factory_catalog_adapter import (
    REVIEWED_SEMANTIC_OVERLAY_SCHEMA,
    SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA,
    SOURCE_RIGHTS_RECEIPT_SCHEMA,
    _MAX_RECORDS,
    _choice_kind,
    _catalog_validator,
    _validate_catalog_record,
    build_reviewed_semantic_overlay,
    seal_source_rights_receipt,
)
from .semantic_admission import PROFILE_REGISTRY_SCHEMA, build_semantic_profile_registry


FACTORY_SEMANTIC_LIBRARY_V1_SCHEMA = "TianxiaFoundry.FactorySemanticLibrary.v1"
FACTORY_SEMANTIC_LIBRARY_V1_VERSION = 1
FACTORY_SEMANTIC_ADAPTER_V1_SHA256 = sha256_json(
    {
        "schema": FACTORY_SEMANTIC_LIBRARY_V1_SCHEMA,
        "version": FACTORY_SEMANTIC_LIBRARY_V1_VERSION,
        "projection": "typed-catalogue-fields-only",
    }
)

FACTORY_SEMANTIC_LIBRARY_SCHEMA = "TianxiaFoundry.FactorySemanticLibrary.v2"
FACTORY_SEMANTIC_LIBRARY_VERSION = 2

# This digest identifies the stable projection protocol, not a trust root.
# It is deliberately independent of process state and source ordering.
FACTORY_SEMANTIC_ADAPTER_SHA256 = sha256_json(
    {
        "schema": FACTORY_SEMANTIC_LIBRARY_SCHEMA,
        "version": FACTORY_SEMANTIC_LIBRARY_VERSION,
        "projection": "typed-catalogue-fields-only",
    }
)

_RIGHTS_USE = "DCC_SEMANTIC_PUBLICATION"
_THEME_CONTENT_TYPES = frozenset({"sphere", "path"})
_ROLE_CORE_KINDS = frozenset({"path", "method", "foundation", "background", "origin"})
_CAPABILITY_PROGRESSION_KINDS = frozenset({"path", "method", "foundation", "milestone"})

# These are the only raw-projection fields that can enter a source fact.  The
# values are copied as typed values; no text in them is interpreted for
# semantics.  ``minimum_cl`` is retained where Factory emits it in the typed
# raw record, while the semantic progression itself comes from legality below.
_TYPED_RAW_FIELDS: dict[str, tuple[str, ...]] = {
    "talent": ("owning_canonical_sphere_id", "access_category", "realm_band", "minimum_cl"),
    "insight": (
        "owning_canonical_sphere_id",
        "owning_canonical_sphere_ids",
        "path_affinities",
        "body_roles",
        "spirit_roles",
        "action_types",
        "resources",
        "rest_cadence",
        "category",
        "minimum_cl",
    ),
    "method": ("resource_shape_key", "foundation_shape_key", "breakthrough_shape_key"),
    "milestone": ("feature_kind", "granted_at_cl", "minimum_cl", "shared_rule_id"),
    "background": ("sphere_ids", "talent_ids", "origin_insight_ids"),
    "sphere": ("canonical_sphere_id",),
    "path": ("canonical_id", "resource_id"),
    "foundation": ("foundation_id", "minimum_cl"),
    "subpath": ("canonical_id", "owning_path_id", "option_type", "minimum_cl", "linked_procedure_module_ids"),
    "tradition": ("canonical_id", "owning_path_id", "option_type", "minimum_cl", "linked_procedure_module_ids"),
    "background_sphere": ("backgrounds",),
    "background_talent": ("sphere_id", "backgrounds"),
    "item": (
        "item_id",
        "record_type",
        "type",
        "grade",
        "primary_material",
        "sphere_influences",
        "set_membership",
        "attunement",
    ),
}


def _raw_projection_views(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    compatibility = record.get("compatibility")
    factory = compatibility.get("factory") if isinstance(compatibility, Mapping) else None
    raw_projection = factory.get("raw_projection") if isinstance(factory, Mapping) else None
    if not isinstance(raw_projection, Mapping):
        return ()
    raw_record = raw_projection.get("raw_record")
    if isinstance(raw_record, Mapping):
        return (raw_projection, raw_record)
    return (raw_projection,)


def _copy_typed_value(value: Any, *, path: str) -> Any:
    """Copy a typed value into canonical order without parsing its contents."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return deepcopy(value)
    if isinstance(value, Mapping):
        return {str(key): _copy_typed_value(value[key], path=f"{path}.{key}") for key in sorted(value, key=str)}
    if isinstance(value, list):
        rows = [_copy_typed_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
        # Typed arrays in the supported catalog are sets of IDs or scalar
        # values.  Canonical sorting makes reordered source arrays inert while
        # preserving their exact typed content.
        try:
            return sorted(rows, key=lambda item: sha256_json(item))
        except (TypeError, ValueError):
            return rows
    fail("DCC_SCHEMA_TYPE", f"{path} contains an unsupported typed value.")


def _typed_raw_fields(record: Mapping[str, Any], *, choice_kind: str | None) -> dict[str, Any]:
    content_type = record["content_type"]
    fields = _TYPED_RAW_FIELDS.get(content_type, ())
    # Canonical content types such as ``cultivation_insight`` and
    # ``path_feature`` resolve to the stable semantic kind names above.
    if not fields and choice_kind in _TYPED_RAW_FIELDS:
        fields = _TYPED_RAW_FIELDS[choice_kind]
    views = _raw_projection_views(record)
    result: dict[str, Any] = {}
    for field in fields:
        for view in views:
            lookup_field = "linked_procedure_modules" if field == "linked_procedure_module_ids" else field
            if lookup_field in view:
                value = view[lookup_field]
                if field == "linked_procedure_module_ids":
                    if not isinstance(value, list):
                        fail("DCC_SCHEMA_TYPE", f"{record['record_id']}.raw_projection.linked_procedure_modules must be an array.")
                    ids: list[str] = []
                    for index, row in enumerate(value):
                        if not isinstance(row, Mapping):
                            fail("DCC_SCHEMA_TYPE", f"{record['record_id']}.raw_projection.linked_procedure_modules[{index}] must be an object.")
                        ids.append(require_identifier(row.get("canonical_id"), path=f"{record['record_id']}.raw_projection.linked_procedure_modules[{index}].canonical_id"))
                    if len(ids) != len(set(ids)):
                        fail("DCC_SCHEMA_DUPLICATE", f"{record['record_id']}.raw_projection.linked_procedure_modules must be duplicate-free.")
                    value = sorted(ids)
                result[field] = _copy_typed_value(value, path=f"{record['record_id']}.raw_projection.{field}")
                break
    return result


def _prerequisite_target_ids(record: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    for index, prerequisite in enumerate(record["legality"]["prerequisites"]):
        if isinstance(prerequisite, Mapping) and isinstance(prerequisite.get("target_id"), str):
            values.add(prerequisite["target_id"])
    return sorted(values)


def source_projection_for_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact whitelisted source-fact projection for one record."""

    choice_kind = _choice_kind(record)
    legality = record["legality"]
    return {
        "record_id": record["record_id"],
        "content_type": record["content_type"],
        "source": {
            "source_id": record["source"]["source_id"],
            "source_hash": record["source"]["source_hash"],
        },
        "legality": {
            "minimum_cl": legality["minimum_cl"],
            "acquisition_channels": sorted(legality["acquisition_channels"]),
            "prerequisite_target_ids": _prerequisite_target_ids(record),
        },
        "dependencies": sorted(record.get("dependencies", [])),
        "raw_projection": _typed_raw_fields(record, choice_kind=choice_kind),
    }


def _typed_constraint_ids(record: Mapping[str, Any]) -> set[str]:
    return set(record.get("dependencies", [])) | set(_prerequisite_target_ids(record))


def _semantic_fragment(record: Mapping[str, Any], *, choice_kind: str | None, theme_ids: set[str]) -> dict[str, Any]:
    constraints = _typed_constraint_ids(record)
    themes = set()
    if record["content_type"] in _THEME_CONTENT_TYPES and record["record_id"] in theme_ids:
        themes.add(record["record_id"])
    themes.update(constraints & theme_ids)
    constraint_count = len(constraints)
    if constraint_count == 0:
        complexity_band = "simple"
        complexity_factors: list[str] = []
    elif constraint_count <= 2:
        complexity_band = "moderate"
        complexity_factors = ["typed_constraint_count"]
    else:
        complexity_band = "complex"
        complexity_factors = ["typed_constraint_count"]
    minimum_cl = record["legality"]["minimum_cl"]
    if minimum_cl is None:
        minimum_cl = 1
    role = "core_identity" if choice_kind in _ROLE_CORE_KINDS else "specialist"
    capability = "progression" if choice_kind in _CAPABILITY_PROGRESSION_KINDS else "selection"
    return {
        "theme_tags": sorted(themes),
        "role_tags": [role],
        "capability_families": [capability],
        "combat_functions": [],
        "resource_loop": {"consumes": [], "produces": [], "cadence": "not_applicable", "setup": "none"},
        "progression": {
            "minimum_cl": minimum_cl,
            "identity_online_cl": minimum_cl,
            "signature_cl": minimum_cl,
            "late_progression_tags": [],
        },
        "synergy_edges": [],
        "redundancy_groups": [],
        "tradeoffs": [],
        "complexity": {"band": complexity_band, "factors": complexity_factors},
    }


def _active_source_rights_trust(rights_authority_sha256: str) -> dict[str, Any]:
    unsigned = {
        "schema": SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA,
        "version": 1,
        "status": "ACTIVE",
        "active_rights_authority_sha256": rights_authority_sha256,
        "revoked_rights_authority_sha256s": [],
    }
    return {**unsigned, "manifest_sha256": sha256_json(unsigned)}


def build_factory_semantic_library(
    catalog_records: Sequence[Mapping[str, Any]],
    *,
    rights_authority_id: str,
    rights_authority_sha256: str,
) -> dict[str, Any]:
    """Build deterministic registry, overlay, and active rights trust inputs.

    The supplied authority is an owner-controlled sealed descriptor: only its
    identifier and digest are carried into receipts and the active trust
    payload.  This function never writes authority files or activates a
    publication candidate.
    """

    require_identifier(rights_authority_id, path="rights_authority_id")
    require_digest(rights_authority_sha256, path="rights_authority_sha256")
    if not isinstance(catalog_records, Sequence) or isinstance(catalog_records, (str, bytes, bytearray)):
        fail("DCC_SCHEMA_TYPE", "Factory semantic library records must be a bounded sequence.")
    if len(catalog_records) > _MAX_RECORDS:
        fail("DCC_SCHEMA_LIMIT", "Factory semantic library records exceeds its item limit.", details={"maximum": _MAX_RECORDS})
    validator = _catalog_validator()
    records = [_validate_catalog_record(raw, validator, index=index) for index, raw in enumerate(catalog_records)]
    records.sort(key=lambda row: row["record_id"])
    if len({row["record_id"] for row in records}) != len(records):
        fail("DCC_CONTENT_DUPLICATE_CHOICE_ID", "Factory semantic library record IDs must be unique.")

    theme_ids = {
        row["record_id"]
        for row in records
        if row["content_type"] in _THEME_CONTENT_TYPES
    }
    facts: list[dict[str, Any]] = []
    receipts_by_source: dict[tuple[str, str], dict[str, Any]] = {}
    overlay_rows: list[dict[str, Any]] = []
    derived_complexity = False
    for record in records:
        choice_id = record["record_id"]
        choice_kind = _choice_kind(record)
        if choice_kind is None:
            fail(
                "DCC_FACTORY_CONTENT_TYPE_UNSUPPORTED",
                "Factory semantic library records must use a supported selectable content type.",
                details={"record_id": choice_id, "content_type": record["content_type"]},
            )
        source_projection = source_projection_for_record(record)
        source_fact_id = f"fact.record.{choice_id}"
        facts.append(
            {
                "source_fact_id": source_fact_id,
                "status": "VERIFIED",
                "source_projection_sha256": sha256_json(source_projection),
            }
        )
        source_pair = (record["source"]["source_id"], record["source"]["source_hash"])
        receipt = receipts_by_source.get(source_pair)
        if receipt is None:
            source_digest = sha256_json({"source_id": source_pair[0], "source_hash": source_pair[1]})
            receipt = seal_source_rights_receipt(
                {
                    "schema": SOURCE_RIGHTS_RECEIPT_SCHEMA,
                    "receipt_id": f"rights.source.{source_digest[:24]}",
                    "status": "VERIFIED",
                    "source_id": source_pair[0],
                    "source_hash": source_pair[1],
                    "allowed_uses": [_RIGHTS_USE],
                    "rights_authority_id": rights_authority_id,
                    "rights_authority_sha256": rights_authority_sha256,
                }
            )
            receipts_by_source[source_pair] = receipt
        fragment = _semantic_fragment(record, choice_kind=choice_kind, theme_ids=theme_ids)
        derived_complexity = derived_complexity or bool(fragment["complexity"]["factors"])
        overlay_rows.append(
            {
                "choice_id": choice_id,
                "choice_record_sha256": record["record_hash"],
                "source_rights_receipt_id": receipt["receipt_id"],
                "profile_ids": [],
                "source_fact_ids": [source_fact_id],
                "semantics": fragment,
            }
        )

    vocabulary = {
        "theme_tags": sorted(theme_ids),
        "role_tags": ["core_identity", "specialist"],
        "capability_families": ["progression", "selection"],
        "combat_functions": [],
        "resource_families": [],
        "late_progression_tags": [],
        "complexity_factors": ["typed_constraint_count"] if derived_complexity else [],
        "tradeoff_codes": [],
    }
    registry = build_semantic_profile_registry(
        {
            "schema": PROFILE_REGISTRY_SCHEMA,
            "version": 1,
            "adapter_version_sha256": FACTORY_SEMANTIC_ADAPTER_SHA256,
            "vocabularies": vocabulary,
            "profiles": [],
        }
    )
    overlay = build_reviewed_semantic_overlay(
        {
            "schema": REVIEWED_SEMANTIC_OVERLAY_SCHEMA,
            "version": 1,
            "semantic_profile_registry_sha256": registry["registry_sha256"],
            "source_facts": facts,
            "source_rights_receipts": list(receipts_by_source.values()),
            "records": overlay_rows,
        }
    )
    trust = _active_source_rights_trust(rights_authority_sha256)
    return {"registry": registry, "overlay": overlay, "source_rights_trust": trust}


__all__ = [
    "FACTORY_SEMANTIC_ADAPTER_V1_SHA256",
    "FACTORY_SEMANTIC_ADAPTER_SHA256",
    "FACTORY_SEMANTIC_LIBRARY_V1_SCHEMA",
    "FACTORY_SEMANTIC_LIBRARY_V1_VERSION",
    "FACTORY_SEMANTIC_LIBRARY_SCHEMA",
    "FACTORY_SEMANTIC_LIBRARY_VERSION",
    "build_factory_semantic_library",
    "source_projection_for_record",
]
