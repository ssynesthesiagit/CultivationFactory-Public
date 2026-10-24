"""Production route binding and append-only persistence for new DCC runs.

This module is deliberately a substrate only.  It does not import the
provider, invoke the shadow controller, or select any creative option.  The
next DCC slice can consume the immutable request binding and event chain that
this module records.
"""

from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy
from typing import Any, Mapping

from app.core import Database, FoundryError, canonical_json, sha256_json, utcnow
from app.validation_cache import ValidationResultCache
from .dcc_semantic_publication import (
    dcc_publication_storage_key,
    load_active_dcc_semantic_publication,
    reopen_dcc_semantic_publication,
)


LEGACY_FULL_PLAN = "LEGACY_FULL_PLAN"
DETERMINISTIC_CREATIVE_CONTROLLER = "DETERMINISTIC_CREATIVE_CONTROLLER"
CONTROLLER_ROUTE_MODES = frozenset({LEGACY_FULL_PLAN, DETERMINISTIC_CREATIVE_CONTROLLER})

ROUTE_BINDING_V1_SCHEMA = "TianxiaFoundry.ControllerRouteBinding.v1"
ROUTE_BINDING_V1_VERSION = 1
# Keep the historical names stable for callers that build/replay V1 rows.
ROUTE_BINDING_SCHEMA = ROUTE_BINDING_V1_SCHEMA
ROUTE_PROJECTION_SCHEMA = "TianxiaFoundry.ControllerRouteProjection.v1"
ROUTE_STATUS_SCHEMA = "TianxiaFoundry.ControllerRouteStatus.v1"
EVENT_SCHEMA = "TianxiaFoundry.ControllerRunEvent.v1"
STATE_SCHEMA = "TianxiaFoundry.ControllerRouteState.v1"
ROUTE_BINDING_VERSION = ROUTE_BINDING_V1_VERSION
ACTIVE_ROUTE_BINDING_SCHEMA = "TianxiaFoundry.ControllerRouteBinding.v2"
ACTIVE_ROUTE_BINDING_VERSION = 2
ACTIVATION_POLICY_INACTIVE = "INACTIVE"
ACTIVATION_POLICY_ACTIVE = "ACTIVE"
CONTROLLER_STATE_INACTIVE = "INACTIVE"
CONTROLLER_STATE_AUTHORITY_FROZEN = "AUTHORITY_FROZEN"
SELECTED_AI_UNAVAILABLE = "UNAVAILABLE_WITHOUT_PROVIDER_INVOCATION"
SELECTED_AI_SEEDED = "SEEDED_NO_AI_IDENTITY"
SELECTED_AI_STATIC = "AVAILABLE_STATIC"

# These are explicit contract identities, not Python source-file hashes.  A
# future semantics slice can intentionally bump either contract and thereby
# make the route binding materially different.
_LEGACY_CONTROLLER_CONTRACT_VERSION = "TianxiaFoundry.DeterministicCreativeControllerContract.v1"
_LEGACY_OPERATOR_CONTRACT_VERSION = "TianxiaFoundry.CharacterCreationOperatorContract.v1"
_LEGACY_CONTROLLER_CONTRACT_VERSION_SHA256 = sha256_json(
    {
        "schema": "TianxiaFoundry.DeterministicCreativeControllerContract.v1",
        "version": 1,
        "activation": "inactive-gate-only",
        "provider_invocation": False,
    }
)
_LEGACY_OPERATOR_CONTRACT_VERSION_SHA256 = sha256_json(
    {
        "schema": "TianxiaFoundry.CharacterCreationOperatorContract.v1",
        "version": 1,
        "route_selection": "owner-requested",
        "activation": "inactive-gate-only",
    }
)
CONTROLLER_CONTRACT_VERSION = "TianxiaFoundry.DeterministicCreativeControllerContract.v2"
OPERATOR_CONTRACT_VERSION = "TianxiaFoundry.CharacterCreationOperatorContract.v2"
CONTROLLER_CONTRACT_VERSION_SHA256 = sha256_json(
    {
        "schema": CONTROLLER_CONTRACT_VERSION,
        "version": 2,
        "activation": "authority-frozen",
        "provider_invocation": False,
        "publication_binding": "dcc-semantic-v2",
    }
)
OPERATOR_CONTRACT_VERSION_SHA256 = sha256_json(
    {
        "schema": OPERATOR_CONTRACT_VERSION,
        "version": 2,
        "route_selection": "owner-requested",
        "activation": "authority-frozen",
        "publication_binding": "dcc-semantic-v2",
    }
)
# Names matching the Stage A shadow binding make the current seam easy to consume.
CONTROLLER_VERSION_SHA256 = CONTROLLER_CONTRACT_VERSION_SHA256
OPERATOR_CONTRACT_SHA256 = OPERATOR_CONTRACT_VERSION_SHA256

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,119}$")
_UNSET = object()
# Runs and repository instances may share one exact historical publication.
# Keep only its small validated identity here, so status reads never copy the
# complete semantic catalogue merely to compare four receipt hashes.
_publication_identities = ValidationResultCache(limit=4)

_ROUTE_BINDING_KEYS = {
    "schema",
    "version",
    "route_mode",
    "activation_policy",
    "controller_version",
    "controller_version_sha256",
    "operator_contract_version",
    "operator_contract_sha256",
    "selected_ai_identity_sha256",
    "selected_ai_identity_state",
    "binding_sha256",
}
_ACTIVE_ROUTE_BINDING_KEYS = _ROUTE_BINDING_KEYS | {
    "publication_receipt_sha256",
    "content_snapshot_sha256",
    "semantic_authority_bundle_sha256",
    "source_rights_authority_sha256",
}
_EVENT_KEYS = {
    "schema",
    "event_id",
    "run_id",
    "project_id",
    "route_binding_sha256",
    "ordinal",
    "event_type",
    "previous_event_sha256",
    "subject_sha256",
    "state_sha256_before",
    "state_sha256_after",
    "payload",
    "created_at",
    "event_sha256",
}


def _error(code: str, message: str, *, details: Any = None, status_code: int = 400) -> None:
    raise FoundryError(code, message, details=details, status_code=status_code)


def _require_digest(value: Any, *, field: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        _error("DCC_ROUTE_BINDING_INVALID", f"{field} must be a lowercase SHA-256 digest.")
    return value


def normalize_controller_route(value: Any = None) -> str:
    """Resolve the compatibility default without accepting aliases."""

    if value is None:
        return LEGACY_FULL_PLAN
    if not isinstance(value, str) or value not in CONTROLLER_ROUTE_MODES:
        _error(
            "CG1_CONTROLLER_ROUTE_INVALID",
            "controller_route must be LEGACY_FULL_PLAN or DETERMINISTIC_CREATIVE_CONTROLLER.",
            details={"value": value, "allowed": sorted(CONTROLLER_ROUTE_MODES)},
            status_code=422,
        )
    return value


def _static_provider_identity(provider: Any) -> tuple[str | None, str]:
    """Read a saved provider identity without invoking provider transport.

    ``selected_ai_identity`` is the explicit read-only seam implemented by the
    provider service.  The fallback attributes keep the small route substrate
    usable by legacy/test provider records; status, completion, endpoint, and
    transport methods are never called here.
    """

    if provider is None:
        return None, SELECTED_AI_UNAVAILABLE
    reader = getattr(provider, "selected_ai_identity", None)
    if callable(reader):
        try:
            selected = reader()
        except FoundryError:
            return None, SELECTED_AI_UNAVAILABLE
        if isinstance(selected, Mapping):
            selected_ai_identity = selected.get("selected_ai_identity_sha256")
            if selected_ai_identity is None:
                selected_ai_identity = selected.get("identity_sha256")
            identity_state = selected.get("selected_ai_identity_state", selected.get("state"))
            if identity_state == SELECTED_AI_UNAVAILABLE:
                return None, SELECTED_AI_UNAVAILABLE
            if identity_state == SELECTED_AI_STATIC and isinstance(selected_ai_identity, str) and _HEX64.fullmatch(selected_ai_identity):
                return selected_ai_identity, SELECTED_AI_STATIC
            if selected_ai_identity is not None or identity_state is not None:
                return None, SELECTED_AI_UNAVAILABLE
    attrs: dict[str, Any] = {}
    try:
        raw = vars(provider)
        if isinstance(raw, dict):
            attrs.update(raw)
    except TypeError:
        pass
    # Class attributes are also static and do not invoke descriptors.
    for key in (
        "selected_ai_identity_sha256",
        "ai_identity_sha256",
        "provider_identity_sha256",
    ):
        value = attrs.get(key, provider.__class__.__dict__.get(key))
        if isinstance(value, str) and _HEX64.fullmatch(value):
            return value, SELECTED_AI_STATIC
    provider_id = attrs.get("provider_id")
    if not isinstance(provider_id, str):
        provider_id = provider.__class__.__dict__.get("provider_id")
    model = attrs.get("model")
    if not isinstance(model, str):
        model = provider.__class__.__dict__.get("model")
    if isinstance(provider_id, str) and provider_id.strip():
        identity = {"provider_id": provider_id.strip()}
        if isinstance(model, str) and model.strip():
            identity["model"] = model.strip()
        return sha256_json(identity), SELECTED_AI_STATIC
    return None, SELECTED_AI_UNAVAILABLE


def build_controller_route_binding(
    route_mode: Any = None,
    *,
    provider: Any = None,
    activation_policy: str = ACTIVATION_POLICY_INACTIVE,
    selected_ai_identity_sha256: str | None | object = _UNSET,
) -> dict[str, Any]:
    """Build a canonical, self-hashed route binding for a new request."""

    mode = normalize_controller_route(route_mode)
    if activation_policy != ACTIVATION_POLICY_INACTIVE:
        _error(
            "CG1_CONTROLLER_ROUTE_ACTIVATION_FORBIDDEN",
            "The DCC route is an inactive substrate in this slice.",
            status_code=409,
        )
    if selected_ai_identity_sha256 is _UNSET:
        selected_ai_identity, identity_state = _static_provider_identity(provider)
    else:
        selected_ai_identity = selected_ai_identity_sha256
        identity_state = SELECTED_AI_STATIC if selected_ai_identity is not None else SELECTED_AI_UNAVAILABLE
    if selected_ai_identity is not None:
        _require_digest(selected_ai_identity, field="selected_ai_identity_sha256")
    unsigned = {
        "schema": ROUTE_BINDING_V1_SCHEMA,
        "version": ROUTE_BINDING_V1_VERSION,
        "route_mode": mode,
        "activation_policy": ACTIVATION_POLICY_INACTIVE,
        "controller_version": _LEGACY_CONTROLLER_CONTRACT_VERSION,
        "controller_version_sha256": _LEGACY_CONTROLLER_CONTRACT_VERSION_SHA256,
        "operator_contract_version": _LEGACY_OPERATOR_CONTRACT_VERSION,
        "operator_contract_sha256": _LEGACY_OPERATOR_CONTRACT_VERSION_SHA256,
        "selected_ai_identity_sha256": selected_ai_identity,
        "selected_ai_identity_state": identity_state,
    }
    return {**unsigned, "binding_sha256": sha256_json(unsigned)}


# Short aliases for callers that use the packet's terminology.
build_route_binding = build_controller_route_binding


def build_active_controller_route_binding(*, provider: Any = None, seeded: bool = False) -> dict[str, Any]:
    """Build a validated-publication authority-bound binding for a DCC run.

    Seeded walks skip the selected-AI reader because each step is derived from
    their owner-locked seed. The publication loader remains fixed; callers
    cannot provide trust digests or a replacement publication.
    """

    if seeded:
        selected_ai_identity, identity_state = None, SELECTED_AI_SEEDED
    else:
        selected_ai_identity, identity_state = _static_provider_identity(provider)
    if not seeded and (selected_ai_identity is None or identity_state != SELECTED_AI_STATIC):
        _error(
            "DCC_SELECTED_AI_UNAVAILABLE",
            "The selected AI is unavailable without invoking provider status or transport.",
            status_code=409,
        )
    try:
        publication = load_active_dcc_semantic_publication()
    except FoundryError as exc:
        _error(
            "DCC_ROUTE_PUBLICATION_UNAVAILABLE",
            "The active DCC semantic publication could not be bound.",
            details={"source_code": exc.code},
            status_code=409,
        )
    profile = publication.get("profile") if isinstance(publication, Mapping) else None
    if getattr(profile, "name", None) not in {"v2", "v3"}:
        _error("DCC_ROUTE_PUBLICATION_INVALID", "The active DCC semantic publication is not a supported validated publication profile.", status_code=409)
    receipt = publication.get("publication_receipt") if isinstance(publication, Mapping) else None
    if not isinstance(receipt, Mapping):
        _error("DCC_ROUTE_PUBLICATION_INVALID", "The active DCC semantic publication has no validated receipt.", status_code=409)
    publication_fields = {
        "publication_receipt_sha256": receipt.get("receipt_sha256"),
        "content_snapshot_sha256": receipt.get("content_snapshot_sha256"),
        "semantic_authority_bundle_sha256": receipt.get("semantic_authority_bundle_sha256"),
        "source_rights_authority_sha256": receipt.get("source_rights_authority_sha256"),
    }
    for field, value in publication_fields.items():
        _require_digest(value, field=field)
    unsigned = {
        "schema": ACTIVE_ROUTE_BINDING_SCHEMA,
        "version": ACTIVE_ROUTE_BINDING_VERSION,
        "route_mode": DETERMINISTIC_CREATIVE_CONTROLLER,
        "activation_policy": ACTIVATION_POLICY_ACTIVE,
        "controller_version": CONTROLLER_CONTRACT_VERSION,
        "controller_version_sha256": CONTROLLER_CONTRACT_VERSION_SHA256,
        "operator_contract_version": OPERATOR_CONTRACT_VERSION,
        "operator_contract_sha256": OPERATOR_CONTRACT_VERSION_SHA256,
        "selected_ai_identity_sha256": selected_ai_identity,
        "selected_ai_identity_state": identity_state,
        **publication_fields,
    }
    return validate_controller_route_binding({**unsigned, "binding_sha256": sha256_json(unsigned)})


build_authority_bound_route_binding = build_active_controller_route_binding


def validate_controller_route_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a persisted/request route binding and return a copy."""

    if not isinstance(value, Mapping):
        _error("DCC_ROUTE_BINDING_INVALID", "controller route binding must be an object.")
    schema = value.get("schema")
    version = value.get("version")
    active = (schema, version) == (ACTIVE_ROUTE_BINDING_SCHEMA, ACTIVE_ROUTE_BINDING_VERSION)
    legacy = (schema, version) == (ROUTE_BINDING_V1_SCHEMA, ROUTE_BINDING_V1_VERSION)
    expected_keys = _ACTIVE_ROUTE_BINDING_KEYS if active else _ROUTE_BINDING_KEYS
    actual_keys = set(value)
    missing = sorted(expected_keys - actual_keys)
    unknown = sorted(actual_keys - expected_keys, key=str)
    if missing or unknown:
        _error(
            "DCC_ROUTE_BINDING_INVALID",
            "controller route binding has an unexpected shape.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    if not active and not legacy:
        _error("DCC_ROUTE_BINDING_INVALID", "Unsupported controller route binding version.")
    if result["route_mode"] not in CONTROLLER_ROUTE_MODES or (active and result["route_mode"] != DETERMINISTIC_CREATIVE_CONTROLLER):
        _error("DCC_ROUTE_BINDING_INVALID", "Unsupported controller route mode.")
    expected_policy = ACTIVATION_POLICY_ACTIVE if active else ACTIVATION_POLICY_INACTIVE
    if result["activation_policy"] != expected_policy:
        _error("DCC_ROUTE_BINDING_INVALID", "The persisted controller route is not behind the inactive gate.")
    expected_controller_version = CONTROLLER_CONTRACT_VERSION if active else _LEGACY_CONTROLLER_CONTRACT_VERSION
    expected_controller_digest = CONTROLLER_CONTRACT_VERSION_SHA256 if active else _LEGACY_CONTROLLER_CONTRACT_VERSION_SHA256
    expected_operator_version = OPERATOR_CONTRACT_VERSION if active else _LEGACY_OPERATOR_CONTRACT_VERSION
    expected_operator_digest = OPERATOR_CONTRACT_VERSION_SHA256 if active else _LEGACY_OPERATOR_CONTRACT_VERSION_SHA256
    if result["controller_version"] != expected_controller_version:
        _error("DCC_ROUTE_BINDING_INVALID", "Unsupported controller contract version.")
    if result["operator_contract_version"] != expected_operator_version:
        _error("DCC_ROUTE_BINDING_INVALID", "Unsupported operator contract version.")
    _require_digest(result["controller_version_sha256"], field="controller_version_sha256")
    _require_digest(result["operator_contract_sha256"], field="operator_contract_sha256")
    if result["controller_version_sha256"] != expected_controller_digest:
        _error("DCC_ROUTE_BINDING_INVALID", "The controller contract digest is stale.")
    if result["operator_contract_sha256"] != expected_operator_digest:
        _error("DCC_ROUTE_BINDING_INVALID", "The operator contract digest is stale.")
    identity = result["selected_ai_identity_sha256"]
    state = result["selected_ai_identity_state"]
    if active and state == SELECTED_AI_SEEDED and identity is None:
        # Seeded Quick Build answers each step locally and carries no model identity.
        pass
    elif active:
        # An authority-bound run cannot be created or reopened without a
        # concrete saved provider/model identity.  Only the historical V1
        # inactive substrate may carry an unavailable identity.
        if state != SELECTED_AI_STATIC:
            _error("DCC_ROUTE_BINDING_INVALID", "An active DCC binding requires a static selected-AI identity.")
        _require_digest(identity, field="selected_ai_identity_sha256")
    elif state == SELECTED_AI_UNAVAILABLE:
        if identity is not None:
            _error("DCC_ROUTE_BINDING_INVALID", "Unavailable AI identity must be explicitly null.")
    elif state == SELECTED_AI_STATIC:
        _require_digest(identity, field="selected_ai_identity_sha256")
    else:
        _error("DCC_ROUTE_BINDING_INVALID", "Unsupported selected-AI identity state.")
    if active:
        for field in (
            "controller_version_sha256",
            "operator_contract_sha256",
            "publication_receipt_sha256",
            "content_snapshot_sha256",
            "semantic_authority_bundle_sha256",
            "source_rights_authority_sha256",
        ):
            _require_digest(result[field], field=field)
    expected = sha256_json({key: result[key] for key in sorted(expected_keys - {"binding_sha256"})})
    if result["binding_sha256"] != expected:
        _error(
            "DCC_ROUTE_BINDING_HASH_INVALID",
            "The controller route binding self-hash does not match.",
            details={"expected": expected, "actual": result["binding_sha256"]},
            status_code=409,
        )
    return result


validate_route_binding = validate_controller_route_binding


def route_binding_sha256(value: Mapping[str, Any]) -> str:
    return validate_controller_route_binding(value)["binding_sha256"]


def _controller_state_for_binding(binding: Mapping[str, Any]) -> str:
    return (
        CONTROLLER_STATE_AUTHORITY_FROZEN
        if binding.get("schema") == ACTIVE_ROUTE_BINDING_SCHEMA
        else CONTROLLER_STATE_INACTIVE
    )


def initial_route_state_sha256(*, run_id: str, project_id: str, binding: Mapping[str, Any]) -> str:
    bound = validate_controller_route_binding(binding)
    return sha256_json(
        {
            "schema": STATE_SCHEMA,
            "run_id": run_id,
            "project_id": project_id,
            "route_mode": bound["route_mode"],
            "activation_policy": bound["activation_policy"],
            "binding_sha256": bound["binding_sha256"],
            "state": _controller_state_for_binding(bound),
        }
    )


def _check_payload(value: Any, *, path: str = "event.payload") -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        _error("DCC_CONTROLLER_EVENT_INVALID", "Controller events cannot contain byte payloads.")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in {
                "request",
                "request_bytes",
                "request_payload",
                "complete_request",
                "prompt_bytes",
                "response_bytes",
                "private_evidence",
                "option_mappings",
            }:
                _error(
                    "DCC_CONTROLLER_EVENT_PRIVATE_DATA",
                    "Controller events cannot persist request bytes or private option evidence.",
                    details={"field": f"{path}.{key}"},
                )
            _check_payload(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _check_payload(child, path=f"{path}[{index}]")
    try:
        canonical_json(value)
    except (TypeError, ValueError, OverflowError) as exc:
        _error("DCC_CONTROLLER_EVENT_INVALID", "Controller event payload is not canonical JSON.")
        raise AssertionError("unreachable") from exc


def _event_id(*, run_id: str, ordinal: int, previous_event_sha256: str | None, event_type: str, subject_sha256: str) -> str:
    digest = sha256_json(
        {
            "domain": "dcc.controller.event.id.v1",
            "run_id": run_id,
            "ordinal": ordinal,
            "previous_event_sha256": previous_event_sha256,
            "event_type": event_type,
            "subject_sha256": subject_sha256,
        }
    )
    return f"dcc.event.{digest[:24]}"


def build_controller_event(
    *,
    run_id: str,
    project_id: str,
    route_binding_sha256: str,
    ordinal: int,
    event_type: str,
    previous_event_sha256: str | None,
    subject_sha256: str,
    state_sha256_before: str,
    state_sha256_after: str,
    payload: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one immutable event without touching the database."""

    for field, value in (
        ("run_id", run_id),
        ("project_id", project_id),
        ("event_type", event_type),
        ("created_at", created_at or utcnow()),
    ):
        if not isinstance(value, str) or not value.strip():
            _error("DCC_CONTROLLER_EVENT_INVALID", f"{field} must be a non-empty string.")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        _error("DCC_CONTROLLER_EVENT_INVALID", "event ordinal must be a positive integer.")
    if not _EVENT_TYPE.fullmatch(event_type):
        _error("DCC_CONTROLLER_EVENT_INVALID", "event_type has an unsupported shape.")
    _require_digest(route_binding_sha256, field="route_binding_sha256")
    _require_digest(previous_event_sha256, field="previous_event_sha256", allow_none=True)
    _require_digest(subject_sha256, field="subject_sha256")
    _require_digest(state_sha256_before, field="state_sha256_before")
    _require_digest(state_sha256_after, field="state_sha256_after")
    event_payload = deepcopy(dict(payload or {}))
    _check_payload(event_payload)
    timestamp = created_at or utcnow()
    unsigned = {
        "schema": EVENT_SCHEMA,
        "event_id": _event_id(
            run_id=run_id,
            ordinal=ordinal,
            previous_event_sha256=previous_event_sha256,
            event_type=event_type,
            subject_sha256=subject_sha256,
        ),
        "run_id": run_id,
        "project_id": project_id,
        "route_binding_sha256": route_binding_sha256,
        "ordinal": ordinal,
        "event_type": event_type,
        "previous_event_sha256": previous_event_sha256,
        "subject_sha256": subject_sha256,
        "state_sha256_before": state_sha256_before,
        "state_sha256_after": state_sha256_after,
        "payload": event_payload,
        "created_at": timestamp,
    }
    return {**unsigned, "event_sha256": sha256_json(unsigned)}


build_event = build_controller_event


def validate_controller_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error("DCC_CONTROLLER_EVENT_INVALID", "Controller event must be an object.")
    actual_keys = set(value)
    missing = sorted(_EVENT_KEYS - actual_keys)
    unknown = sorted(actual_keys - _EVENT_KEYS, key=str)
    if missing or unknown:
        _error(
            "DCC_CONTROLLER_EVENT_INVALID",
            "Controller event has an unexpected shape.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    if result["schema"] != EVENT_SCHEMA:
        _error("DCC_CONTROLLER_EVENT_INVALID", "Unsupported controller event schema.")
    if not isinstance(result["event_id"], str) or not result["event_id"].startswith("dcc.event."):
        _error("DCC_CONTROLLER_EVENT_INVALID", "event_id is invalid.")
    if not isinstance(result["run_id"], str) or not result["run_id"].strip():
        _error("DCC_CONTROLLER_EVENT_INVALID", "event.run_id is invalid.")
    if not isinstance(result["project_id"], str) or not result["project_id"].strip():
        _error("DCC_CONTROLLER_EVENT_INVALID", "event.project_id is invalid.")
    if not isinstance(result["ordinal"], int) or isinstance(result["ordinal"], bool) or result["ordinal"] < 1:
        _error("DCC_CONTROLLER_EVENT_INVALID", "event.ordinal is invalid.")
    if not isinstance(result["event_type"], str) or not _EVENT_TYPE.fullmatch(result["event_type"]):
        _error("DCC_CONTROLLER_EVENT_INVALID", "event.event_type is invalid.")
    _require_digest(result["route_binding_sha256"], field="route_binding_sha256")
    _require_digest(result["previous_event_sha256"], field="previous_event_sha256", allow_none=True)
    for field in ("subject_sha256", "state_sha256_before", "state_sha256_after"):
        _require_digest(result[field], field=field)
    if not isinstance(result["payload"], Mapping):
        _error("DCC_CONTROLLER_EVENT_INVALID", "event.payload must be an object.")
    _check_payload(result["payload"])
    if not isinstance(result["created_at"], str) or not result["created_at"].strip():
        _error("DCC_CONTROLLER_EVENT_INVALID", "event.created_at is invalid.")
    expected_id = _event_id(
        run_id=result["run_id"],
        ordinal=result["ordinal"],
        previous_event_sha256=result["previous_event_sha256"],
        event_type=result["event_type"],
        subject_sha256=result["subject_sha256"],
    )
    if result["event_id"] != expected_id:
        _error("DCC_CONTROLLER_EVENT_ID_INVALID", "event_id is not derived from the event identity.")
    expected_hash = sha256_json({key: result[key] for key in sorted(_EVENT_KEYS - {"event_sha256"})})
    if result["event_sha256"] != expected_hash:
        _error(
            "DCC_CONTROLLER_EVENT_HASH_INVALID",
            "The controller event self-hash does not match.",
            details={"expected": expected_hash, "actual": result["event_sha256"]},
            status_code=409,
        )
    return result


validate_event = validate_controller_event


def verify_controller_event_chain(
    events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    route_binding_sha256: str | None = None,
) -> dict[str, Any]:
    normalized = [validate_controller_event(item) for item in events]
    if not normalized:
        return {"event_count": 0, "event_head_sha256": None, "state_sha256": None}
    first = normalized[0]
    expected_binding = route_binding_sha256 or first["route_binding_sha256"]
    _require_digest(expected_binding, field="route_binding_sha256")
    previous_event_sha256: str | None = None
    previous_state_sha256: str | None = None
    for expected_ordinal, event in enumerate(normalized, start=1):
        if event["ordinal"] != expected_ordinal:
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "Controller event ordinals must be contiguous.", status_code=409)
        if event["route_binding_sha256"] != expected_binding:
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "Controller event binding changed mid-stream.", status_code=409)
        if event["previous_event_sha256"] != previous_event_sha256:
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "Controller event previous hash is stale.", status_code=409)
        if previous_state_sha256 is not None and event["state_sha256_before"] != previous_state_sha256:
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "Controller event state-before hash is stale.", status_code=409)
        previous_event_sha256 = event["event_sha256"]
        previous_state_sha256 = event["state_sha256_after"]
    if any(
        event["run_id"] != first["run_id"] or event["project_id"] != first["project_id"]
        for event in normalized
    ):
        _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "Controller event identity changed mid-stream.", status_code=409)
    return {
        "event_count": len(normalized),
        "event_head_sha256": previous_event_sha256,
        "state_sha256": previous_state_sha256,
        "run_id": first["run_id"],
        "project_id": first["project_id"],
        "route_binding_sha256": expected_binding,
    }


verify_event_chain = verify_controller_event_chain


def _row_value(row: sqlite3.Row | Mapping[str, Any], key: str) -> Any:
    return row[key]


def _route_publication_storage_key() -> tuple[Any, ...]:
    """Preserve the route diagnostic if its publication storage disappears."""
    try:
        return dcc_publication_storage_key()
    except FoundryError as exc:
        _error(
            "DCC_ROUTE_PUBLICATION_TAMPERED",
            "The pinned DCC semantic publication could not be reopened.",
            details={"source_code": exc.code}, status_code=409,
        )


class ControllerRoutePersistence:
    """Transactional route binding and append-only event repository."""

    binding_table = "dcc_controller_run_bindings"
    event_table = "dcc_controller_events"

    def __init__(self, db: Database):
        self.db = db
        self._active_publication_validation_cache = ValidationResultCache(limit=4)
        self._projection_validations = ValidationResultCache(limit=16)

    def _validate_active_publication_binding(self, binding: Mapping[str, Any]) -> None:
        """Revalidate the exact historical publication pinned by one binding."""

        if binding.get("schema") != ACTIVE_ROUTE_BINDING_SCHEMA:
            return
        cache_key = (tuple(binding[key] for key in sorted(_ACTIVE_ROUTE_BINDING_KEYS)),
                     _route_publication_storage_key())
        self._active_publication_validation_cache.get_or_compute(
            cache_key, lambda: self._validate_active_publication_uncached(binding),
            still_current=lambda: _route_publication_storage_key() == cache_key[1],
        )

    def _validate_active_publication_uncached(self, binding: Mapping[str, Any]) -> None:
        receipt_sha256 = binding["publication_receipt_sha256"]
        key = (receipt_sha256, _route_publication_storage_key(), reopen_dcc_semantic_publication)

        def read_identity() -> dict[str, Any]:
            reopened = reopen_dcc_semantic_publication(receipt_sha256)
            return {"profile": reopened.get("profile") if isinstance(reopened, Mapping) else None,
                    "publication_receipt": reopened.get("publication_receipt") if isinstance(reopened, Mapping) else None}

        try:
            publication = _publication_identities.get_or_compute(
                key, read_identity,
                still_current=lambda: _route_publication_storage_key() == key[1],
            )
        except FoundryError as exc:
            _error(
                "DCC_ROUTE_PUBLICATION_TAMPERED",
                "The pinned DCC semantic publication could not be reopened.",
                details={"source_code": exc.code},
                status_code=409,
            )
        profile = publication.get("profile") if isinstance(publication, Mapping) else None
        receipt = publication.get("publication_receipt") if isinstance(publication, Mapping) else None
        if getattr(profile, "name", None) not in {"v2", "v3"} or not isinstance(receipt, Mapping):
            _error(
                "DCC_ROUTE_PUBLICATION_TAMPERED",
                "The pinned DCC semantic publication is not a validated publication receipt.",
                status_code=409,
            )
        expected = {
            "publication_receipt_sha256": receipt.get("receipt_sha256"),
            "content_snapshot_sha256": receipt.get("content_snapshot_sha256"),
            "semantic_authority_bundle_sha256": receipt.get("semantic_authority_bundle_sha256"),
            "source_rights_authority_sha256": receipt.get("source_rights_authority_sha256"),
        }
        if any(expected[field] != binding[field] for field in expected):
            _error(
                "DCC_ROUTE_PUBLICATION_TAMPERED",
                "The pinned DCC route identities do not match its historical publication receipt.",
                status_code=409,
            )

    @staticmethod
    def _decode_json(raw: Any, *, code: str, label: str) -> dict[str, Any]:
        if not isinstance(raw, str):
            _error(code, f"Persisted {label} is not text.", status_code=500)
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            _error(code, f"Persisted {label} is not valid JSON.", status_code=500)
            raise AssertionError("unreachable") from exc
        if not isinstance(value, dict):
            _error(code, f"Persisted {label} must be an object.", status_code=500)
        return value

    def _binding_row(self, conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
        return conn.execute(
            f"SELECT * FROM {self.binding_table} WHERE run_id=?",
            (run_id,),
        ).fetchone()

    def _read_projection(self, conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
        row = self._binding_row(conn, run_id)
        if row is None:
            return None
        binding = validate_controller_route_binding(
            self._decode_json(row["binding_json"], code="DCC_ROUTE_BINDING_TAMPERED", label="route binding")
        )
        self._validate_active_publication_binding(binding)
        rows = conn.execute(
            f"SELECT * FROM {self.event_table} WHERE run_id=? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        # Every persisted column is part of the key: changed JSON, rehashed
        # edits, event append/delete and denormalized-column tampering all miss.
        key = (tuple(row), tuple(tuple(item) for item in rows))
        return self._projection_validations.get_or_compute(
            key, lambda: self._validate_projection_rows(run_id, row, rows, binding),
        )

    def _validate_projection_rows(self, run_id: str, row: sqlite3.Row, rows: list[sqlite3.Row], binding: Mapping[str, Any]) -> dict[str, Any]:
        if (
            row["binding_json"] != canonical_json(binding)
            or row["state"] != "INACTIVE"
            or row["route_mode"] != binding["route_mode"]
            or row["binding_sha256"] != binding["binding_sha256"]
            or not _HEX64.fullmatch(str(row["request_sha256"]))
        ):
            _error("DCC_ROUTE_BINDING_TAMPERED", "Persisted route binding columns disagree with its sealed JSON.", status_code=409)
        events: list[dict[str, Any]] = []
        for event_row in rows:
            event = validate_controller_event(
                self._decode_json(event_row["event_json"], code="DCC_CONTROLLER_EVENT_TAMPERED", label="controller event")
            )
            if (
                event_row["event_json"] != canonical_json(event)
                or event_row["event_id"] != event["event_id"]
                or event_row["project_id"] != event["project_id"]
                or event_row["route_binding_sha256"] != event["route_binding_sha256"]
                or event_row["ordinal"] != event["ordinal"]
                or event_row["event_type"] != event["event_type"]
                or event_row["previous_event_sha256"] != event["previous_event_sha256"]
                or event_row["subject_sha256"] != event["subject_sha256"]
                or event_row["state_sha256_before"] != event["state_sha256_before"]
                or event_row["state_sha256_after"] != event["state_sha256_after"]
                or event_row["event_sha256"] != event["event_sha256"]
                or event_row["created_at"] != event["created_at"]
            ):
                _error("DCC_CONTROLLER_EVENT_TAMPERED", "Persisted controller event columns disagree with its sealed JSON.", status_code=409)
            events.append(event)
        chain = verify_controller_event_chain(events, route_binding_sha256=binding["binding_sha256"])
        if not events:
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "A bound controller run must have an initial event.", status_code=409)
        if (
            any(event["run_id"] != run_id or event["project_id"] != row["project_id"] for event in events)
            or chain["event_head_sha256"] != events[-1]["event_sha256"]
        ):
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "Persisted controller events do not belong to the run.", status_code=409)
        expected_state = _controller_state_for_binding(binding)
        expected_state_hash = initial_route_state_sha256(run_id=run_id, project_id=row["project_id"], binding=binding)
        first_event = events[0]
        if (
            first_event["event_type"] != "ROUTE_BOUND"
            or first_event["subject_sha256"] != binding["binding_sha256"]
            or first_event["state_sha256_before"] != expected_state_hash
            or first_event["state_sha256_after"] != expected_state_hash
            or first_event["payload"] != {"route_mode": binding["route_mode"], "state": expected_state}
        ):
            _error("DCC_CONTROLLER_EVENT_CHAIN_INVALID", "The initial controller event does not bind the route state.", status_code=409)
        return {
            "schema": ROUTE_PROJECTION_SCHEMA,
            "run_id": run_id,
            "project_id": row["project_id"],
            "request_sha256": row["request_sha256"],
            "route_mode": binding["route_mode"],
            "mode": binding["route_mode"],
            "activation_policy": binding["activation_policy"],
            "state": expected_state,
            "binding": binding,
            "binding_sha256": binding["binding_sha256"],
            "events": events,
            "event_count": chain["event_count"],
            "event_head_sha256": chain["event_head_sha256"],
            "state_sha256": chain["state_sha256"],
            "created_at": row["created_at"],
        }

    def bind_new_run(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        project_id: str,
        request_sha256: str,
        binding: Mapping[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Insert the DCC binding and initial event on the caller transaction."""

        bound = validate_controller_route_binding(binding)
        _require_digest(request_sha256, field="request_sha256")
        if bound["route_mode"] == LEGACY_FULL_PLAN:
            return None
        run = conn.execute(
            "SELECT project_id FROM character_creation_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if run is None or run["project_id"] != project_id:
            _error("DCC_ROUTE_BINDING_RUN_MISSING", "A controller route can only bind an inserted character run.", status_code=409)
        self._validate_active_publication_binding(bound)
        timestamp = created_at or utcnow()
        derived_state = _controller_state_for_binding(bound)
        try:
            conn.execute(
                f"INSERT INTO {self.binding_table}(run_id,project_id,route_mode,binding_json,binding_sha256,request_sha256,state,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    project_id,
                    bound["route_mode"],
                    canonical_json(bound),
                    bound["binding_sha256"],
                    request_sha256,
                    # Migration 029 keeps its historical storage sentinel;
                    # projection derives AUTHORITY_FROZEN for V2 bindings.
                    "INACTIVE",
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _error("DCC_ROUTE_BINDING_PERSISTENCE_FAILED", "The immutable controller route binding could not be inserted.", status_code=409)
            raise AssertionError("unreachable") from exc
        state_hash = initial_route_state_sha256(run_id=run_id, project_id=project_id, binding=bound)
        event = build_controller_event(
            run_id=run_id,
            project_id=project_id,
            route_binding_sha256=bound["binding_sha256"],
            ordinal=1,
            event_type="ROUTE_BOUND",
            previous_event_sha256=None,
            subject_sha256=bound["binding_sha256"],
            state_sha256_before=state_hash,
            state_sha256_after=state_hash,
            payload={"route_mode": bound["route_mode"], "state": derived_state},
            created_at=timestamp,
        )
        try:
            conn.execute(
                f"INSERT INTO {self.event_table}(event_id,run_id,project_id,route_binding_sha256,ordinal,event_type,previous_event_sha256,subject_sha256,state_sha256_before,state_sha256_after,event_json,event_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event["event_id"],
                    run_id,
                    project_id,
                    bound["binding_sha256"],
                    event["ordinal"],
                    event["event_type"],
                    event["previous_event_sha256"],
                    event["subject_sha256"],
                    event["state_sha256_before"],
                    event["state_sha256_after"],
                    canonical_json(event),
                    event["event_sha256"],
                    event["created_at"],
                ),
            )
        except sqlite3.IntegrityError as exc:
            _error("DCC_ROUTE_EVENT_PERSISTENCE_FAILED", "The initial controller event could not be inserted.", status_code=409)
            raise AssertionError("unreachable") from exc
        return {
            "run_id": run_id,
            "project_id": project_id,
            "route_mode": bound["route_mode"],
            "binding_sha256": bound["binding_sha256"],
            "event_count": 1,
            "event_head_sha256": event["event_sha256"],
            "state": derived_state,
        }

    # Alias that reads naturally at the service boundary.
    bind_run = bind_new_run

    def projection(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            return self._read_projection(conn, run_id)

    load_projection = projection
    get_projection = projection

    def status(self, run_id: str) -> dict[str, Any] | None:
        projection = self.projection(run_id)
        if projection is None:
            return None
        status = {
            "schema": ROUTE_STATUS_SCHEMA,
            "run_id": projection["run_id"],
            "project_id": projection["project_id"],
            "mode": projection["route_mode"],
            "route_mode": projection["route_mode"],
            "state": projection["state"],
            "activation_policy": projection["activation_policy"],
            "request_sha256": projection["request_sha256"],
            "binding_sha256": projection["binding_sha256"],
            "event_count": projection["event_count"],
            "event_head_sha256": projection["event_head_sha256"],
        }
        binding = projection["binding"]
        # The bounded V1 status shape is part of the historical API contract.
        # Publication and selected-AI identities are only exposed for the
        # versioned authority-bound V2 binding.
        if binding.get("schema") == ACTIVE_ROUTE_BINDING_SCHEMA:
            for field in (
                "publication_receipt_sha256",
                "content_snapshot_sha256",
                "semantic_authority_bundle_sha256",
                "source_rights_authority_sha256",
                "selected_ai_identity_sha256",
                "selected_ai_identity_state",
            ):
                status[field] = binding[field]
        return status

    route_status = status

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        subject_sha256: str,
        state_sha256_before: str,
        state_sha256_after: str,
        payload: Mapping[str, Any] | None = None,
        expected_event_head_sha256: str | None | object = _UNSET,
        expected_ordinal: int | object = _UNSET,
        expected_binding_sha256: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """Append one event under strict head/ordinal compare-and-swap."""

        if expected_event_head_sha256 is _UNSET or expected_ordinal is _UNSET:
            _error(
                "DCC_CONTROLLER_EVENT_CAS_REQUIRED",
                "Appending a controller event requires an exact expected head and ordinal.",
                status_code=409,
            )
        if not isinstance(expected_ordinal, int) or isinstance(expected_ordinal, bool) or expected_ordinal < 1:
            _error("DCC_CONTROLLER_EVENT_CAS_INVALID", "expected_ordinal must be a positive integer.", status_code=409)
        if expected_event_head_sha256 is not None:
            _require_digest(expected_event_head_sha256, field="expected_event_head_sha256")
        with self.db.transaction() as conn:
            projection = self._read_projection(conn, run_id)
            if projection is None:
                _error("DCC_ROUTE_BINDING_NOT_FOUND", "No DCC controller route is bound to this run.", status_code=404)
            if expected_binding_sha256 is not None and expected_binding_sha256 != projection["binding_sha256"]:
                _error("DCC_CONTROLLER_EVENT_STALE", "The controller route binding is stale.", status_code=409)
            if (
                expected_ordinal != projection["event_count"] + 1
                or expected_event_head_sha256 != projection["event_head_sha256"]
                or state_sha256_before != projection["state_sha256"]
            ):
                _error(
                    "DCC_CONTROLLER_EVENT_STALE",
                    "The controller event head changed; reload before appending.",
                    details={
                        "expected_ordinal": expected_ordinal,
                        "actual_ordinal": projection["event_count"] + 1,
                        "expected_event_head_sha256": expected_event_head_sha256,
                        "actual_event_head_sha256": projection["event_head_sha256"],
                        "expected_state_sha256_before": state_sha256_before,
                        "actual_state_sha256": projection["state_sha256"],
                    },
                    status_code=409,
                )
            event = build_controller_event(
                run_id=run_id,
                project_id=projection["project_id"],
                route_binding_sha256=projection["binding_sha256"],
                ordinal=expected_ordinal,
                event_type=event_type,
                previous_event_sha256=projection["event_head_sha256"],
                subject_sha256=subject_sha256,
                state_sha256_before=state_sha256_before,
                state_sha256_after=state_sha256_after,
                payload=payload,
                created_at=created_at,
            )
            try:
                conn.execute(
                    f"INSERT INTO {self.event_table}(event_id,run_id,project_id,route_binding_sha256,ordinal,event_type,previous_event_sha256,subject_sha256,state_sha256_before,state_sha256_after,event_json,event_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event["event_id"],
                        event["run_id"],
                        event["project_id"],
                        event["route_binding_sha256"],
                        event["ordinal"],
                        event["event_type"],
                        event["previous_event_sha256"],
                        event["subject_sha256"],
                        event["state_sha256_before"],
                        event["state_sha256_after"],
                        canonical_json(event),
                        event["event_sha256"],
                        event["created_at"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                _error("DCC_CONTROLLER_EVENT_PERSISTENCE_FAILED", "The controller event append conflicted with another writer.", status_code=409)
                raise AssertionError("unreachable") from exc
        return event

    append_controller_event = append_event


__all__ = [
    "LEGACY_FULL_PLAN",
    "DETERMINISTIC_CREATIVE_CONTROLLER",
    "CONTROLLER_ROUTE_MODES",
    "ROUTE_BINDING_V1_SCHEMA",
    "ROUTE_BINDING_V1_VERSION",
    "ROUTE_BINDING_SCHEMA",
    "ACTIVE_ROUTE_BINDING_SCHEMA",
    "ACTIVE_ROUTE_BINDING_VERSION",
    "ROUTE_PROJECTION_SCHEMA",
    "ROUTE_STATUS_SCHEMA",
    "EVENT_SCHEMA",
    "STATE_SCHEMA",
    "ACTIVATION_POLICY_INACTIVE",
    "ACTIVATION_POLICY_ACTIVE",
    "CONTROLLER_STATE_INACTIVE",
    "CONTROLLER_STATE_AUTHORITY_FROZEN",
    "SELECTED_AI_UNAVAILABLE",
    "SELECTED_AI_STATIC",
    "CONTROLLER_CONTRACT_VERSION",
    "OPERATOR_CONTRACT_VERSION",
    "CONTROLLER_CONTRACT_VERSION_SHA256",
    "OPERATOR_CONTRACT_VERSION_SHA256",
    "CONTROLLER_VERSION_SHA256",
    "OPERATOR_CONTRACT_SHA256",
    "normalize_controller_route",
    "build_controller_route_binding",
    "build_route_binding",
    "build_active_controller_route_binding",
    "build_authority_bound_route_binding",
    "validate_controller_route_binding",
    "validate_route_binding",
    "route_binding_sha256",
    "initial_route_state_sha256",
    "build_controller_event",
    "build_event",
    "validate_controller_event",
    "validate_event",
    "verify_controller_event_chain",
    "verify_event_chain",
    "ControllerRoutePersistence",
]
