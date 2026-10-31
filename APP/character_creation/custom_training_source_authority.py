"""Project-scoped, owner-confirmed custom training-source authority.

This module intentionally does not choose a source or call a provider.  It
normalizes an already owner-confirmed envelope and builds the immutable record
that the project-lock and Stage-2 boundaries can authenticate later.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from app.core import (
    CATALOG_GM_COMPATIBILITY_VERSION,
    FACTORY_VERSION,
    FoundryError,
    canonical_json,
    sha256_bytes,
    sha256_json,
)
from contracts.canonical import canonical_record_hash


CUSTOM_TRAINING_SOURCE_SCHEMA = "TianxiaFoundry.ProjectCustomTrainingSource.v1"
CUSTOM_TRAINING_SOURCE_RECORD_SCHEMA = "TianxiaFoundry.RulesCatalogRecord.v1"
CUSTOM_TRAINING_SOURCE_PACK_ID = "tianxia.project.user_directive.training_source"
CUSTOM_TRAINING_SOURCE_PACK_VERSION = "1"
USER_DIRECTIVE_SOURCE_PATH = "USER_DIRECTIVE_CURRENT_CONVERSATION"
CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION = "project_custom_training_source_seal"
CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE = "project_custom_training_source"

CUSTOM_TRAINING_SOURCE_ROUTES = frozenset(
    {
        "selected_ai_custom_training_source",
        "owner_supplied_custom_training_source",
    }
)
CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE = {
    "new_sphere": "sphere",
    "known_sphere_talent": "talent",
    "recorded_art": "recorded_art",
}

_ENVELOPE_KEYS = frozenset(
    {
        "route_id",
        "owner_confirmation_id",
        "display_name",
        "summary",
        "source_text",
        "source_anchor",
        "access_mode",
        "training_types",
        "target_record_ids",
    }
)
_NORMALIZED_KEYS = frozenset(
    {
        "schema",
        "route_id",
        "owner_confirmation_id",
        "display_name",
        "summary",
        "source_path",
        "source_text",
        "source_text_sha256",
        "source_anchor",
        "access_mode",
        "training_types",
        "target_record_ids",
    }
)
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_OWNER_CONFIRMATION_LENGTH = 200
_MAX_DISPLAY_NAME_LENGTH = 300
_MAX_SUMMARY_LENGTH = 8000
_MAX_SOURCE_TEXT_BYTES = 65536
_MAX_SOURCE_ANCHOR_LENGTH = 512
_MAX_ACCESS_MODE_LENGTH = 200
_MAX_TRAINING_TYPE_LENGTH = 80
_MAX_RECORD_ID_LENGTH = 200


def _invalid(message: str, *, field: str | None = None, value: Any = None) -> FoundryError:
    details: dict[str, Any] = {"schema": CUSTOM_TRAINING_SOURCE_SCHEMA}
    if field is not None:
        details["field"] = field
    if value is not None and not isinstance(value, (bytes, bytearray)):
        details["value"] = value
    return FoundryError("CUSTOM_TRAINING_SOURCE_INPUT_INVALID", message, details=details)


def _clean_text(value: Any, *, field: str, max_length: int, max_bytes: int | None = None) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid("A required text field must be a non-empty trimmed string.", field=field)
    if len(value) > max_length:
        raise _invalid("A text field exceeds its bounded length.", field=field)
    encoded = value.encode("utf-8")
    if max_bytes is not None and len(encoded) > max_bytes:
        raise _invalid("A text field exceeds its bounded byte length.", field=field)
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise _invalid("Control characters are not allowed in source authority text.", field=field)
    return value


def _clean_identifier(value: Any, *, field: str, max_length: int) -> str:
    cleaned = _clean_text(value, field=field, max_length=max_length)
    if not _SOURCE_ID_RE.fullmatch(cleaned):
        raise _invalid("An identifier contains unsupported characters.", field=field)
    return cleaned


def _clean_unique_list(value: Any, *, field: str, max_length: int, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise _invalid("A bounded authority list must be a JSON array.", field=field)
    if not value and not allow_empty:
        raise _invalid("A bounded authority list must not be empty.", field=field)
    result: list[str] = []
    for index, item in enumerate(value):
        try:
            clean = _clean_identifier(item, field=f"{field}[{index}]", max_length=max_length)
        except FoundryError:
            raise
        if clean in result:
            raise _invalid("Authority list entries must be unique.", field=field)
        result.append(clean)
    return sorted(result)


def _source_identity(normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact fields that determine all server-owned identities."""
    return {
        "route_id": normalized["route_id"],
        "owner_confirmation_id": normalized["owner_confirmation_id"],
        "display_name": normalized["display_name"],
        "summary": normalized["summary"],
        "source_text": normalized["source_text"],
        "source_anchor": normalized["source_anchor"],
        "access_mode": normalized["access_mode"],
        "training_types": list(normalized["training_types"]),
        "target_record_ids": list(normalized["target_record_ids"]),
    }


def normalize_custom_training_source(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one owner-confirmed route-neutral custom source envelope.

    The returned mapping is newly allocated and contains no caller-controlled
    identity, hash, authority, grant, or execution fields.
    """
    if not isinstance(envelope, Mapping):
        raise _invalid("The custom training-source envelope must be an object.")
    if set(envelope) != set(_ENVELOPE_KEYS):
        raise _invalid(
            "The custom training-source envelope must contain exactly the reviewed fields.",
            field="envelope",
        )

    route_id = envelope.get("route_id")
    if not isinstance(route_id, str) or route_id not in CUSTOM_TRAINING_SOURCE_ROUTES:
        raise _invalid("The route is not part of the reviewed custom-source contract.", field="route_id")
    owner_confirmation_id = _clean_identifier(
        envelope.get("owner_confirmation_id"),
        field="owner_confirmation_id",
        max_length=_MAX_OWNER_CONFIRMATION_LENGTH,
    )
    display_name = _clean_text(
        envelope.get("display_name"),
        field="display_name",
        max_length=_MAX_DISPLAY_NAME_LENGTH,
    )
    summary = _clean_text(
        envelope.get("summary"),
        field="summary",
        max_length=_MAX_SUMMARY_LENGTH,
    )
    source_text = _clean_text(
        envelope.get("source_text"),
        field="source_text",
        max_length=_MAX_SOURCE_TEXT_BYTES,
        max_bytes=_MAX_SOURCE_TEXT_BYTES,
    )
    source_anchor = _clean_text(
        envelope.get("source_anchor"),
        field="source_anchor",
        max_length=_MAX_SOURCE_ANCHOR_LENGTH,
    )
    if any(ord(char) < 32 for char in source_anchor):
        raise _invalid("Control characters are not allowed in a source anchor.", field="source_anchor")
    access_mode = _clean_identifier(
        envelope.get("access_mode"),
        field="access_mode",
        max_length=_MAX_ACCESS_MODE_LENGTH,
    )
    training_types = _clean_unique_list(
        envelope.get("training_types"),
        field="training_types",
        max_length=_MAX_TRAINING_TYPE_LENGTH,
    )
    unsupported_types = [item for item in training_types if item not in CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE]
    if unsupported_types:
        raise _invalid("Training types are not part of the supported Stage-2 target contract.", field="training_types", value=unsupported_types)
    target_record_ids = _clean_unique_list(
        envelope.get("target_record_ids"),
        field="target_record_ids",
        max_length=_MAX_RECORD_ID_LENGTH,
    )

    return {
        "schema": CUSTOM_TRAINING_SOURCE_SCHEMA,
        "route_id": str(route_id),
        "owner_confirmation_id": owner_confirmation_id,
        "display_name": display_name,
        "summary": summary,
        "source_path": USER_DIRECTIVE_SOURCE_PATH,
        "source_text": source_text,
        "source_text_sha256": sha256_bytes(source_text.encode("utf-8")),
        "source_anchor": source_anchor,
        "access_mode": access_mode,
        "training_types": training_types,
        "target_record_ids": target_record_ids,
    }


def _identities(normalized: Mapping[str, Any]) -> dict[str, str]:
    identity_hash = sha256_json(_source_identity(normalized))
    record_id = f"tianxia.custom.training_source.{identity_hash[:40]}"
    source_id = f"source.user_directive.{identity_hash[:40]}"
    rule_id = f"tianxia.custom.training_source.{identity_hash[:24]}.access.v1"
    pack_hash = sha256_json(
        {
            "schema": CUSTOM_TRAINING_SOURCE_SCHEMA,
            "pack_id": CUSTOM_TRAINING_SOURCE_PACK_ID,
            "pack_version": CUSTOM_TRAINING_SOURCE_PACK_VERSION,
            "identity_hash": identity_hash,
            "record_id": record_id,
        }
    )
    return {
        "identity_hash": identity_hash,
        "record_id": record_id,
        "source_id": source_id,
        "rule_id": rule_id,
        "pack_hash": pack_hash,
    }


def build_custom_training_source_record(normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Build the complete schema-v1 record from normalized values."""
    if set(normalized) == set(_ENVELOPE_KEYS):
        normalized = normalize_custom_training_source(normalized)
    elif set(normalized) == set(_NORMALIZED_KEYS):
        if (
            normalized.get("schema") != CUSTOM_TRAINING_SOURCE_SCHEMA
            or normalized.get("source_path") != USER_DIRECTIVE_SOURCE_PATH
            or not isinstance(normalized.get("source_text"), str)
            or normalized.get("source_text_sha256") != sha256_bytes(normalized["source_text"].encode("utf-8"))
        ):
            raise _invalid("The normalized source authority has an invalid source commitment.", field="normalized")
        normalized = normalize_custom_training_source(
            {
                "route_id": normalized["route_id"],
                "owner_confirmation_id": normalized["owner_confirmation_id"],
                "display_name": normalized["display_name"],
                "summary": normalized["summary"],
                "source_text": normalized["source_text"],
                "source_anchor": normalized["source_anchor"],
                "access_mode": normalized["access_mode"],
                "training_types": normalized["training_types"],
                "target_record_ids": normalized["target_record_ids"],
            }
        )
    else:
        raise _invalid("The source builder requires exactly the normalized contract fields.", field="normalized")
    ids = _identities(normalized)
    stage2_authority = {
        "authority_complete": True,
        "allowed_kinds": ["training_source_access"],
        "allowed_channels": ["user-directive-custom-training-source"],
        "rule_id": ids["rule_id"],
        "training_source_access": {
            "mode": "requires_access_event",
            "access_modes": [normalized["access_mode"]],
            "training_types": list(normalized["training_types"]),
            "target_record_ids": list(normalized["target_record_ids"]),
        },
    }
    custom_contract = {
        "schema": CUSTOM_TRAINING_SOURCE_SCHEMA,
        "route_id": normalized["route_id"],
        "owner_confirmation_id": normalized["owner_confirmation_id"],
        "source_id": ids["source_id"],
        "source_hash": normalized["source_text_sha256"],
        "rule_id": ids["rule_id"],
        "pack_id": CUSTOM_TRAINING_SOURCE_PACK_ID,
        "pack_version": CUSTOM_TRAINING_SOURCE_PACK_VERSION,
        "pack_hash": ids["pack_hash"],
        "access_mode": normalized["access_mode"],
        "training_types": list(normalized["training_types"]),
        "target_record_ids": list(normalized["target_record_ids"]),
    }
    record: dict[str, Any] = {
        "schema_version": CUSTOM_TRAINING_SOURCE_RECORD_SCHEMA,
        "record_id": ids["record_id"],
        "content_type": "source_document",
        "display_name": normalized["display_name"],
        "aliases": [],
        "tags": ["custom-design", "training-source", "user-directive"],
        "publication": {
            "status": "published",
            "published_version": CUSTOM_TRAINING_SOURCE_PACK_VERSION,
            "replaced_by": None,
        },
        "content_binding": {
            "pack_id": CUSTOM_TRAINING_SOURCE_PACK_ID,
            "pack_version": CUSTOM_TRAINING_SOURCE_PACK_VERSION,
            "pack_hash": ids["pack_hash"],
        },
        "source": {
            "source_id": ids["source_id"],
            "path": USER_DIRECTIVE_SOURCE_PATH,
            "anchor": normalized["source_anchor"],
            "source_hash": normalized["source_text_sha256"],
            "source_text": normalized["source_text"],
        },
        "summary": normalized["summary"],
        "legality": {
            "acquisition_channels": ["user-directive-custom-training-source"],
            "prerequisites": [],
            "incompatibilities": [],
            "minimum_cl": None,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": [],
        "grants": [],
        "execution_templates": [],
        "display_projection": {
            "short_description": normalized["summary"][:500],
            "full_description": normalized["summary"],
            "surfaces": ["rules_catalog"],
            "sort_key": normalized["display_name"].casefold(),
        },
        "compatibility": {
            "factory": {
                "producer": FACTORY_VERSION,
                "authority_classification": "user_directive",
                "selected_authority": True,
                "display_only_not_execution_authority": True,
                "mechanical_authority": False,
                "unresolved_normalization_notes": [],
                "retained_prerequisites": [],
                "retained_grants": [],
                "custom_design": True,
                "custom_training_source": custom_contract,
                "stage2_authority": stage2_authority,
            },
            "gm_screen": {
                "consumer": CATALOG_GM_COMPATIBILITY_VERSION,
                "projection_status": "catalog-only-phase2r",
            },
        },
        "revision_history": [
            {
                "version": CUSTOM_TRAINING_SOURCE_PACK_VERSION,
                "summary": "Owner-confirmed user-directive custom training source.",
                "previous_record_hash": None,
            }
        ],
        "regression_tests": [
            {
                "test_id": f"{ids['record_id']}.source-hash-equality",
                "kind": "source-hash-equality",
                "input": {"source_path": USER_DIRECTIVE_SOURCE_PATH},
                "expected": {"source_hash": normalized["source_text_sha256"]},
            }
        ],
    }
    record["record_hash"] = canonical_record_hash(record)
    return record


def validate_custom_training_source_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate a persisted custom record and return its sealed contract."""
    if not isinstance(record, Mapping):
        raise FoundryError("CUSTOM_TRAINING_SOURCE_RECORD_INVALID", "The persisted custom training source is not an object.")
    try:
        factory = record["compatibility"]["factory"]
        contract = factory["custom_training_source"]
        source = record["source"]
        stage2 = factory["stage2_authority"]
    except (KeyError, TypeError):
        raise FoundryError("CUSTOM_TRAINING_SOURCE_RECORD_INVALID", "The persisted custom training source is missing its reviewed authority surfaces.")
    if not isinstance(factory, Mapping) or not isinstance(contract, Mapping) or not isinstance(source, Mapping) or not isinstance(stage2, Mapping):
        raise FoundryError("CUSTOM_TRAINING_SOURCE_RECORD_INVALID", "The persisted custom training source authority surfaces are malformed.")
    try:
        expected = build_custom_training_source_record(
            {
                "route_id": contract["route_id"],
                "owner_confirmation_id": contract["owner_confirmation_id"],
                "display_name": record["display_name"],
                "summary": record["summary"],
                "source_text": source["source_text"],
                "source_anchor": source["anchor"],
                "access_mode": contract["access_mode"],
                "training_types": contract["training_types"],
                "target_record_ids": contract["target_record_ids"],
            }
        )
    except (FoundryError, KeyError, TypeError) as exc:
        if isinstance(exc, FoundryError):
            raise FoundryError("CUSTOM_TRAINING_SOURCE_RECORD_INVALID", "The persisted custom training source does not satisfy its normalized contract.", details=exc.details) from exc
        raise FoundryError("CUSTOM_TRAINING_SOURCE_RECORD_INVALID", "The persisted custom training source cannot be normalized.") from exc
    if canonical_json(record) != canonical_json(expected):
        raise FoundryError(
            "CUSTOM_TRAINING_SOURCE_RECORD_INVALID",
            "The persisted custom training source bytes diverge from its deterministic normalized record.",
            details={"record_id": record.get("record_id")},
        )
    return deepcopy(expected["compatibility"]["factory"]["custom_training_source"])


__all__ = [
    "CUSTOM_TRAINING_SOURCE_PACK_ID",
    "CUSTOM_TRAINING_SOURCE_PACK_VERSION",
    "CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION",
    "CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE",
    "CUSTOM_TRAINING_SOURCE_RECORD_SCHEMA",
    "CUSTOM_TRAINING_SOURCE_ROUTES",
    "CUSTOM_TRAINING_SOURCE_SCHEMA",
    "CUSTOM_TRAINING_TYPE_TO_CONTENT_TYPE",
    "USER_DIRECTIVE_SOURCE_PATH",
    "build_custom_training_source_record",
    "normalize_custom_training_source",
    "validate_custom_training_source_record",
]
