"""Bounded provider adapter for Command 4 action authoring.

This module deliberately sits beside the deterministic Command 4 producer.  A
provider may resolve only explicitly missing, source-backed presentation
fields, but it cannot choose the executable identity, resource transactions,
or source authority.  The sealed workspace and ``command4_actions`` projection
remain the only source of those values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ai_provider.service import (
    COMMAND4_ACTION_AUTHORING_PURPOSE,
    LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
    MAX_LOCAL_RESPONSE_SCHEMA_BYTES,
)
from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json
from canonical_catalog.service import CanonicalCatalogAuthorityService
from factory_authoring.command4_actions import (
    ACTION_CANDIDATES_SCHEMA,
    _canonical_action_type,
    _parse_explicit_fields,
    _resource_projection_from_description,
    _validate_prepared_recipe_shape,
)
from factory_authoring.service import FactoryAuthoringWorkspaceService
from factory_authoring.native_path_mechanics import validate_native_path_candidate
from factory_authoring.native_path_operations import validate_native_operation_candidate, validate_operation_acquisition
from factory_authoring.immortal_art_mechanics import validate_immortal_action_candidate
from factory_authoring.forged_action_mechanics import validate_forged_action_candidate
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


COMMAND4_PROVIDER_RESPONSE_SCHEMA = "TianxiaFoundry.Command4ProviderAuthoringResponse.v4"
COMMAND4_PROVIDER_RESPONSE_SCHEMA_NAME = "TianxiaFoundry_Command4ProviderAuthoring_v4"
COMMAND4_SURFACE_SCHEMA = "TianxiaFoundry.Command4ProviderCompleteActionSurface.v1"
COMMAND4_EVIDENCE_SCHEMA = "TianxiaFoundry.Command4ProviderAuthoringEvidence.v1"
COMMAND4_OVERLAY_SCHEMA = "TianxiaFoundry.Command4ProviderOverlayManifest.v1"
COMMAND4_DETERMINISTIC_CHOICE_REQUIRED = "COMMAND4_DETERMINISTIC_CHOICE_REQUIRED"
COMMAND4_DETERMINISTIC_PROVIDER_ID = "server_deterministic"
COMMAND4_DETERMINISTIC_RESOLUTION_MODE = "deterministic_closed_world"
COMMAND4_MAX_REQUEST_BYTES = 65_536
COMMAND4_LOCAL_PROVIDER_IDS = frozenset({"local", "lemonade"})
# A harness-held agent may author Command 4 actions through the same provider
# contract as a local model; the local-only set still governs local-runtime
# identity and wire-format behavior.
COMMAND4_AUTHORING_PROVIDER_IDS = COMMAND4_LOCAL_PROVIDER_IDS | {"agent"}
_LEGACY_SIGNATURE_LOADOUT_CONTRACT = "10–14 distinct action records; procedures are not eligible; choose only supplied IDs."
# A provider can select this token only when the server proves that the
# sealed source has no substantive, field-specific span.  It is deliberately
# not a free-form value and never becomes provider evidence.
COMMAND4_NOT_APPLICABLE_QUOTE = "__COMMAND4_NOT_APPLICABLE__"
COMMAND4_SYSTEM_MESSAGE = (
    "You are a bounded Command 4 source-authoring adapter. Return exactly one JSON object "
    "matching the contract in the user prompt. Use only supplied records and exact source "
    "evidence; never invent mechanics, quantities, resources, state, IDs, or action types."
)

_DETERMINISTIC_PROVENANCE = {
    "provider_id": COMMAND4_DETERMINISTIC_PROVIDER_ID,
    "purpose": COMMAND4_ACTION_AUTHORING_PURPOSE,
    "finish_reason": "stop",
    "resolution_mode": COMMAND4_DETERMINISTIC_RESOLUTION_MODE,
    "provider_calls": 0,
    "model": None,
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
}

# This is the complete execution surface vocabulary.  The provider receives
# only the subset marked missing and non-derived below; the server supplies all
# known, classified, and derived values when it assembles the surface.
COMMAND4_EXECUTION_FIELDS = (
    "action_id",
    "name",
    "bucket",
    "action_type",
    "timing",
    "cost",
    "range",
    "target",
    "roll_save_check",
    "effect",
    "failure",
    "duration",
    "limit",
    "counterplay",
    "source_packet_ids",
    "resource_costs",
    "resource_gains",
    "resource_requirements",
)
_DERIVED_FIELDS = frozenset({
    "action_id",
    "source_packet_ids",
    "resource_costs",
    "resource_gains",
    "resource_requirements",
})
# Classification is sealed by the candidate/source projection.  It is not a
# provider-authorable field even when a legacy candidate's ``missing_fields``
# list contains it (the retained ritual record is one such example).
_SERVER_CLASSIFICATION_FIELDS = frozenset({"bucket", "action_type"})
_LOCKED_SOURCE_FIELD = "unambiguous_locked_mechanics_source"
_SERVER_RESOLVED_MISSING_FIELDS = frozenset({_LOCKED_SOURCE_FIELD})
_LOCKED_SOURCE_KEYS = frozenset({"path", "anchor", "sha256"})
_SEMANTIC_SOURCE_ANCHOR_RE = re.compile(
    r"^\s*(?P<sphere>Sphere\s+of\s+[^:]+):lines:(?P<start>[0-9]+)-(?P<end>[0-9]+):"
    r"(?P<slug>[A-Za-z0-9][A-Za-z0-9_.-]*)\s*$",
    re.IGNORECASE,
)
_PACKET_SOURCE_ANCHOR_RE = re.compile(r"^line:(?P<line>[0-9]+):column:(?P<column>[0-9]+)$", re.IGNORECASE)
_TOP_LEVEL_HEADING_RE = re.compile(r"^#(?!#)\s+(?P<title>.+?)\s*$")
_MARKDOWN_HEADING_RE = re.compile(r"^#{2,6}\s+(?P<title>.+?)\s*$")
_PROVIDER_AUTHORABLE_FIELDS = tuple(
    field
    for field in COMMAND4_EXECUTION_FIELDS
    if field not in _DERIVED_FIELDS and field not in _SERVER_CLASSIFICATION_FIELDS
)
# Field Formula's parser has only one partial effect/failure projection even
# though its sealed source defines three per-use modes.  Those two fields are
# therefore reviewed overrides, but only for this exact source commitment.
_REVIEWED_FORCED_PROVIDER_FIELDS: dict[str, tuple[str, frozenset[str]]] = {
    # These labelled saves otherwise put scaling (and Grace's entire mode)
    # in the parser's failure field. Preserve each complete mode contract.
    "TAL_KARMA_SETTLE_MINOR_ACCOUNT": (
        "494fffd040e4b8db000ec4d5eceecf953e9cb15dcd0b1ddf6141d7e0be0fc879",
        frozenset({"effect", "failure"}),
    ),
    "TAL_ALCHEMY_NUMBING_POWDER": (
        "7410240deb7b440bb63d5e6d633b0272fca7ac0b87cddb2ccc3cc0ed15debb54",
        frozenset({"effect", "failure"}),
    ),
    "ALCHEMY_BASE_FIELD_FORMULA": (
        "8e74850e4b8e4065b64ef032a69713d9e483ef166f93328cbb8ccaf912a8d2e7",
        frozenset({"effect", "failure"}),
    ),
    # Furnace Vent has a parser-partial area target and no deterministic
    # timing/range/roll/duration/limit/counterplay projection.  Keep its
    # Action classification and effect/failure source projection server-owned;
    # only this exact source-bound domain may complete the omitted fields.
    "TAL_ALCHEMY_FURNACE_VENT": (
        "0dc890f26e0857f5b7091cba1ac8b6df38c23209aef863aea56d6fd852d215a9",
        frozenset({"timing", "range", "target", "roll_save_check", "duration", "limit", "counterplay"}),
    ),
    # The recipe's Ingredient/Refinement costs are provenance metadata.  The
    # action profile completes only its source-bound combat mechanics and
    # leaves the prepared-pill transaction to the strict resource projector.
    "TAL_ALCHEMY_EXPLOSIVE_PILL": (
        "6c0625ca5f9e2e3fcc2e52f41c57f97932bebdf09f746e112ef9fe32463036ed",
        frozenset({"target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay"}),
    ),
    # Choking Smoke's parser retains only the coarse area/effect fragments;
    # this exact source-bound profile supplies the complete single action
    # mechanics while preserving the server-owned Action/range projection.
    "TAL_ALCHEMY_CHOKING_SMOKE_PELLET": (
        "c3097ea2607ae545815658dd7b1798f8228532f1f19e443ff75d9190171e036c",
        frozenset({"timing", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay"}),
    ),
    # Binding Dregs already has complete source-backed effect/failure text;
    # complete only its omitted presentation fields and retain the strict
    # CP/Reagent action transaction projection.
    "TAL_ALCHEMY_BINDING_DREGS": (
        "b394ca3206e62880b1a9c1e98f8630ffd94a4e708084fbddb24ab2fdd0279cd4",
        frozenset({"timing", "target", "roll_save_check", "duration", "limit", "counterplay"}),
    ),
}
_PACKET_AUTHORITIES = frozenset({"source_quote", "bounded_interpretation", "not_applicable"})
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_QUOTE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']+|[0-9]+")
_MIN_SUBSTANTIVE_QUOTE_CHARS = 5
_MIN_SUBSTANTIVE_QUOTE_TOKENS = 2
_NON_SUBSTANTIVE_SOURCE_QUOTE_PHRASES = frozenset({
    "source text",
    "some text",
    "placeholder",
    "placeholder text",
    "example text",
    "generic text",
    "lorem ipsum",
    "unknown",
    "n/a",
    "not applicable",
})
_STRICT_ACTION_LABEL_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)?(?:\*\*)?"
    r"(?P<label>Canonical\s+Action\s+Type|Action\s+Type)"
    r"(?:\*\*)?\s*(?::|-)(?:\*\*)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_STRICT_ROUTING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*>]\s*)?(?:\*\*)?Factory\s+Routing"
    r"(?:\*\*)?\s*(?::|-)(?:\*\*)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_SAFE_RECEIPT_KEYS = (
    "provider_id",
    "purpose",
    "model",
    "finish_reason",
)
_SAFE_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_SAFE_PERFORMANCE_KEYS = ("duration_ms", "duration_seconds", "completion_tokens_per_second")
_SAFE_PROVIDER_TIMING_KEYS = frozenset({
    "cache_hits",
    "cache_misses",
    "completion_tokens_per_second",
    "eval_count",
    "eval_duration",
    "load_duration",
    "predicted_ms",
    "predicted_n",
    "predicted_per_second",
    "predicted_per_token_ms",
    "prompt_eval_count",
    "prompt_eval_duration",
    "prompt_ms",
    "prompt_n",
    "prompt_per_second",
    "prompt_per_token_ms",
    "sample_count",
    "sample_duration",
    "total_duration",
})
_SAFE_PROVIDER_DIAGNOSTIC_KEYS = frozenset({
    "purpose",
    "reason",
    "finish_reason",
    "response_sha256",
    "completion_sha256",
    "completion_bytes",
    "expected_request_sha256",
    "actual_request_sha256",
})
_SAFE_CONTRACT_REASON_CODES = frozenset({
    "invalid_json",
    "missing_content",
    "finish_reason_not_stop",
    "tool_calls_present",
    "response_not_object",
    "response_shape_invalid",
    "response_schema_validation_failed",
    "other",
})
_SAFE_FINISH_REASONS = frozenset({
    "stop",
    "length",
    "max_tokens",
    "max_output_tokens",
    "content_filter",
    "tool_calls",
    "function_call",
    "error",
    "end_turn",
})


def _json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH_RE.fullmatch(value))


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0 or value > 1_000_000_000_000:
        return None
    if isinstance(value, float) and not value.is_integer():
        return round(value, 6)
    return int(value)


def _safe_reason_code(value: Any) -> str:
    return value if isinstance(value, str) and value in _SAFE_CONTRACT_REASON_CODES else "other"


def _safe_finish_reason(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in _SAFE_FINISH_REASONS else "other"


def _safe_receipt(provider_result: Mapping[str, Any], *, request_sha256: str, response_sha256: str | None) -> dict[str, Any]:
    """Project a provider result into a receipt with no headers/credentials."""

    receipt: dict[str, Any] = {
        "schema": COMMAND4_EVIDENCE_SCHEMA,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "completion_sha256": response_sha256,
    }
    for key in _SAFE_RECEIPT_KEYS:
        if key in provider_result and isinstance(provider_result[key], (str, int, float, type(None))):
            if key == "finish_reason":
                safe_finish_reason = _safe_finish_reason(provider_result[key])
                if safe_finish_reason is not None:
                    receipt[key] = safe_finish_reason
            else:
                receipt[key] = provider_result[key]
    for source_key, receipt_key in (
        ("request_sha256", "provider_request_sha256"),
        ("response_sha256", "provider_response_sha256"),
        ("completion_sha256", "provider_completion_sha256"),
    ):
        supplied = provider_result.get(source_key)
        if _is_hash(supplied):
            receipt[receipt_key] = supplied
    usage = provider_result.get("usage")
    if isinstance(usage, Mapping):
        receipt["usage"] = {key: _safe_number(usage.get(key)) for key in _SAFE_USAGE_KEYS}
    performance = provider_result.get("performance")
    if isinstance(performance, Mapping):
        receipt["performance"] = {key: _safe_number(performance.get(key)) for key in _SAFE_PERFORMANCE_KEYS}
    timings = provider_result.get("timings")
    if isinstance(timings, Mapping):
        phases = timings.get("phases_ms")
        receipt["timings"] = {
            "schema": timings.get("schema") if isinstance(timings.get("schema"), str) else None,
            "phases_ms": {
                str(key): _safe_number(value)
                for key, value in phases.items()
                if isinstance(key, str) and _safe_number(value) is not None
            } if isinstance(phases, Mapping) else {},
            "provider_reported": {
                str(key): _safe_number(value)
                for key, value in (timings.get("provider_reported") or {}).items()
                if key in _SAFE_PROVIDER_TIMING_KEYS and _safe_number(value) is not None
            } if isinstance(timings.get("provider_reported"), Mapping) else {},
        }
    return receipt


def _safe_provider_diagnostics(value: Any) -> dict[str, Any]:
    """Keep only bounded contract-failure diagnostics from the transport."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in _SAFE_PROVIDER_DIAGNOSTIC_KEYS:
        item = value.get(key)
        if key in {"response_sha256", "completion_sha256", "expected_request_sha256", "actual_request_sha256"}:
            if _is_hash(item):
                result[key] = item
        elif key == "completion_bytes":
            safe = _safe_number(item)
            if isinstance(safe, int):
                result[key] = safe
        elif key == "reason":
            result[key] = _safe_reason_code(item)
        elif key == "finish_reason":
            safe_finish_reason = _safe_finish_reason(item)
            if safe_finish_reason is not None:
                result[key] = safe_finish_reason
        elif key == "purpose" and isinstance(item, str):
            result[key] = item[:120]
    for key in ("validator", "schema_name"):
        item = value.get(key)
        if isinstance(item, str) and item:
            result[key] = item[:120]
    for key in ("instance_path", "schema_path"):
        item = value.get(key)
        if isinstance(item, list) and all(isinstance(part, str) for part in item):
            result[key] = [part[:80] for part in item[:12]]
    usage = value.get("usage")
    if isinstance(usage, Mapping):
        result["usage"] = {key: _safe_number(usage.get(key)) for key in _SAFE_USAGE_KEYS}
    performance = value.get("performance")
    if isinstance(performance, Mapping):
        result["performance"] = {key: _safe_number(performance.get(key)) for key in _SAFE_PERFORMANCE_KEYS}
    timings = value.get("timings")
    if isinstance(timings, Mapping):
        phases = timings.get("phases_ms")
        provider_reported = timings.get("provider_reported")
        result["timings"] = {
            "schema": timings.get("schema") if isinstance(timings.get("schema"), str) else None,
            "phases_ms": {
                str(key): _safe_number(item)
                for key, item in phases.items()
                if isinstance(key, str) and _safe_number(item) is not None
            } if isinstance(phases, Mapping) else {},
            "provider_reported": {
                str(key): _safe_number(item)
                for key, item in provider_reported.items()
                if key in _SAFE_PROVIDER_TIMING_KEYS and _safe_number(item) is not None
            } if isinstance(provider_reported, Mapping) else {},
        }
    return result


def _workspace_file_hashes(root: Path, *, include_checksums: bool = False) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and (include_checksums or path.relative_to(root).as_posix() != "SHA256SUMS.txt")
    }


def _reject_recursive_nonregular(root: Path, *, code: str, message: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise FoundryError(code, message)
    try:
        entries = sorted(root.rglob("*"))
    except OSError as exc:
        raise FoundryError(code, message) from exc
    for path in entries:
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise FoundryError(code, message, details={"path": str(path.relative_to(root))})


def _workspace_sha256(root: Path) -> str:
    # FactoryAuthoringWorkspaceService seals the pointer hash after writing
    # SHA256SUMS.txt, so the pointer identity includes that ledger.  The
    # detached ledger itself still lists every other file only.
    return sha256_json(_workspace_file_hashes(root, include_checksums=True))


def _verify_workspace_checksums(root: Path) -> None:
    sums_path = root / "SHA256SUMS.txt"
    if sums_path.is_symlink() or not sums_path.is_file():
        raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_MISSING", "The sealed Factory workspace checksum ledger is missing.")

    def read_ledger(path: Path, label: str) -> dict[str, str]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", f"The {label} checksum ledger cannot be read.") from exc
        declared: dict[str, str] = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", f"The {label} checksum ledger is malformed.")
            digest, relative = parts
            relative = relative.lstrip("*").strip()
            relative_path = Path(relative)
            if (
                not _is_hash(digest)
                or not relative
                or relative in declared
                or relative_path.is_absolute()
                or ".." in relative_path.parts
            ):
                raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", f"The {label} checksum ledger contains an invalid entry.")
            declared[relative] = digest.lower()
        return declared

    declared = read_ledger(sums_path, "sealed workspace")
    build_root = root / "Build"
    build_ledger = build_root / "SHA256SUMS.txt"
    build_present = build_root.exists() or build_root.is_symlink()
    if build_present and (build_root.is_symlink() or not build_root.is_dir()):
        raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", "The Build directory is not regular.")
    if build_present and build_ledger.is_symlink():
        raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", "The Build checksum ledger is not a regular file.")
    if build_present and not build_ledger.is_file():
        raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_MISSING", "The Build checksum ledger is missing.")
    has_build_ledger = build_present
    # A materialized candidate deliberately owns Build/ through its nested
    # ledger.  Legacy sealed roots have no nested ledger and retain the
    # historical whole-tree root-ledger contract.
    actual = {
        name: digest
        for name, digest in _workspace_file_hashes(root).items()
        if not has_build_ledger or not name.startswith("Build/")
    }
    if declared != actual:
        raise FoundryError(
            "COMMAND4_WORKSPACE_CHECKSUMS_STALE",
            "The sealed Factory workspace checksum ledger does not match its files.",
            details={"missing": sorted(set(actual) - set(declared)), "extra": sorted(set(declared) - set(actual))},
        )
    if has_build_ledger:
        build_declared = read_ledger(build_ledger, "Build")
        build_actual = _workspace_file_hashes(build_root)
        if build_declared != build_actual:
            raise FoundryError(
                "COMMAND4_WORKSPACE_CHECKSUMS_STALE",
                "The Build checksum ledger does not match its files.",
                details={"missing": sorted(set(build_actual) - set(build_declared)), "extra": sorted(set(build_declared) - set(build_actual))},
            )
        Command4ProviderAuthoring._validate_build_package_manifest(build_root)


def _canonical_wire_payload(
    prompt_text: str,
    system_message: str,
    settings: Mapping[str, Any] | None = None,
    *,
    temperature: float | int | None = None,
    response_schema: Mapping[str, Any] | None = None,
    response_schema_name: str = COMMAND4_PROVIDER_RESPONSE_SCHEMA_NAME,
    response_schema_max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Mirror the canonical ``AIProviderService.complete_json`` request body."""

    settings = settings if isinstance(settings, Mapping) else {}
    provider_id = str(settings.get("provider_id") or "command4")
    model = str(settings.get("model") or "command4-authoring")
    max_tokens = settings.get("max_output_tokens")
    if type(max_tokens) is not int or max_tokens <= 0:
        max_tokens = LOCAL_COMMAND4_MAX_OUTPUT_TOKENS
    # ``agent`` is bounded by the same Command 4 ceiling as the local profiles:
    # AIProviderService.complete_json gives the agent bridge this purpose's
    # budget, so the expected request hash must be computed from the same value.
    if provider_id in {"local", "lemonade", "command4", "agent"}:
        max_tokens = min(max_tokens, LOCAL_COMMAND4_MAX_OUTPUT_TOKENS)
    else:
        max_tokens = min(max_tokens, 8192)
    if response_schema is not None and response_schema_max_output_tokens is not None:
        max_tokens = min(max_tokens, response_schema_max_output_tokens)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt_text},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "stream": False,
    }
    if response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema_name,
                "strict": True,
                "schema": deepcopy(dict(response_schema)),
            },
        }
    if temperature is not None:
        payload["temperature"] = temperature
    if provider_id in {"local", "lemonade"}:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload["cache_prompt"] = True
    if provider_id == "deepseek":
        payload["thinking"] = {"type": settings.get("thinking_mode") or "disabled"}
    return payload


def canonical_command4_wire_bytes(
    prompt_text: str,
    *,
    system_message: str = COMMAND4_SYSTEM_MESSAGE,
    settings: Mapping[str, Any] | None = None,
    temperature: float | int | None = 0,
    response_schema: Mapping[str, Any] | None = None,
    response_schema_name: str = COMMAND4_PROVIDER_RESPONSE_SCHEMA_NAME,
    response_schema_max_output_tokens: int | None = None,
) -> bytes:
    """Return the exact UTF-8 body measured by the provider transport."""

    return _json_bytes(
        _canonical_wire_payload(
            prompt_text,
            system_message,
            settings,
            temperature=temperature,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            response_schema_max_output_tokens=response_schema_max_output_tokens,
        )
    )


def _provider_settings(provider: Any) -> Mapping[str, Any] | None:
    getter = getattr(provider, "_settings", None)
    if not callable(getter):
        return None
    try:
        value = getter()
    except Exception:  # pragma: no cover - a test double may not expose settings
        return None
    return value if isinstance(value, Mapping) else None


def _candidate_action_type(candidate: Mapping[str, Any]) -> str | None:
    allowed = {"action", "bonus_action", "reaction", "passive", "procedure"}
    value = candidate.get("action_type")
    candidate_type = str(value) if value in allowed else None
    description = candidate.get("full_description")
    if not isinstance(description, str):
        return candidate_type

    # The shared parser intentionally recognizes only the compact action
    # vocabulary and therefore folds an unrecognized ``Canonical Action
    # Type`` line into the preceding value.  Read these two labels separately
    # here so the retained ritual procedure remains deterministic, while
    # conflicting/duplicate labels fail closed rather than being normalized.
    label_values: dict[str, list[str]] = {"action": [], "canonical": [], "routing": []}
    for line in description.splitlines():
        match = _STRICT_ACTION_LABEL_RE.match(line)
        if match:
            key = "canonical" if match.group("label").casefold().startswith("canonical") else "action"
            value_text = match.group("value").strip()
            if value_text:
                label_values[key].append(value_text)
            continue
        match = _STRICT_ROUTING_RE.match(line)
        if match and match.group("value").strip():
            label_values["routing"].append(match.group("value").strip())

    if any(len(values) > 1 for values in label_values.values()):
        return None
    action_label = _canonical_action_type(label_values["action"][0]) if label_values["action"] else None
    canonical_label = _canonical_action_type(label_values["canonical"][0]) if label_values["canonical"] else None
    routing = label_values["routing"][0].casefold() if label_values["routing"] else None
    if label_values["action"] and action_label is None:
        return None
    if label_values["canonical"] and canonical_label is None:
        return None
    if action_label is not None and canonical_label is not None and action_label != canonical_label:
        return None
    labeled_type = action_label or canonical_label
    if candidate_type is not None and labeled_type is not None and candidate_type != labeled_type:
        return None
    if labeled_type == "procedure" and routing is not None and routing != "procedure_ledger_not_combat_action":
        return None
    if labeled_type is not None:
        return labeled_type
    if candidate_type is not None:
        # A candidate row already sealed with a canonical type remains usable
        # when its source has no type labels; no untrusted text is promoted.
        return candidate_type

    parsed = _parse_explicit_fields(description)
    parsed_value = parsed.get("action_type") or parsed.get("bucket")
    if isinstance(parsed_value, str) and "\n" not in parsed_value:
        return _canonical_action_type(parsed_value)
    return None


def _candidate_runtime_kind(candidate: Mapping[str, Any]) -> str:
    return "procedure" if _candidate_action_type(candidate) == "procedure" else "action"


def _validate_sealed_ready_candidate(
    candidate: Mapping[str, Any],
    surface_row: Mapping[str, Any],
    *,
    runtime_kind: str,
) -> None:
    """Bind a ready candidate to its already-sealed executable projection."""

    record_id = candidate.get("record_id")
    if surface_row.get("record_id") != record_id:
        raise FoundryError(
            "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
            "A sealed ready surface row has a different record identity than its candidate.",
            details={"record_id": record_id},
        )
    expected_runtime_kind = _candidate_runtime_kind(candidate)
    if runtime_kind != expected_runtime_kind:
        raise FoundryError(
            "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
            "A sealed ready surface row has the wrong runtime kind for its candidate.",
            details={"record_id": record_id, "runtime_kind": runtime_kind},
        )
    if "runtime_kind" in surface_row and surface_row.get("runtime_kind") != expected_runtime_kind:
        raise FoundryError(
            "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
            "A sealed ready surface row has a different runtime kind than its candidate.",
            details={"record_id": record_id},
        )
    for field in COMMAND4_EXECUTION_FIELDS:
        expected = _candidate_value(candidate, field)
        if field not in surface_row or surface_row.get(field) != expected:
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                "A sealed ready surface row does not exactly match its candidate execution projection.",
                details={"record_id": record_id, "field": field},
            )
    expected_packet_ids = _candidate_value(candidate, "source_packet_ids")
    for alias in ("source_packet_ids", "source_rule_ids"):
        if alias in surface_row and surface_row.get(alias) != expected_packet_ids:
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                "A sealed ready surface row has a different source packet projection than its candidate.",
                details={"record_id": record_id, "field": alias},
            )
    expected_source_hash = _hash_text(_candidate_source(candidate))
    if "source_text_sha256" in surface_row and surface_row.get("source_text_sha256") != expected_source_hash:
        raise FoundryError(
            "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
            "A sealed ready surface row has a different source text commitment than its candidate.",
            details={"record_id": record_id},
        )
    for value in (
        candidate.get("executable"),
        candidate.get("execution_authority"),
        surface_row.get("executable"),
        surface_row.get("execution_authority"),
    ):
        if value is not None and value is not True:
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                "A sealed ready candidate or surface row is not executable.",
                details={"record_id": record_id},
            )


def _signature_loadout_projection(
    candidates: list[Mapping[str, Any]],
    *,
    error_code: str,
) -> tuple[list[str], int, int]:
    """Derive the closed-world signature-loadout domain and its bounds.

    The eligible IDs are intentionally derived from the sealed candidate rows
    at every boundary that consumes this projection.  A provider may choose a
    subset when there are enough eligible actions, but a small domain is not a
    reason to ask for impossible padding: every eligible action is required
    exactly once when fewer than ten exist.  A procedure-only workspace keeps
    the existing empty-loadout contract (zero-to-zero) while still rejecting
    every invented ID through the empty enum below.
    """

    if not isinstance(candidates, list):
        raise FoundryError(
            error_code,
            "The sealed signature-loadout candidate domain must be a list.",
        )
    eligible_ids: list[str] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise FoundryError(
                error_code,
                "The sealed signature-loadout candidate domain contains a non-object row.",
            )
        record_id = candidate.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise FoundryError(
                error_code,
                "Eligible signature-loadout action records need nonblank IDs.",
            )
        action_type = _candidate_action_type(candidate)
        if action_type == "procedure":
            continue
        if action_type in {"passive", "basic"}:
            continue
        if action_type not in {"action", "bonus_action", "reaction"}:
            raise FoundryError(
                error_code,
                "Every signature-loadout candidate must have a validated action classification.",
                details={"record_id": record_id},
            )
        if record_id in seen_ids:
            raise FoundryError(
                error_code,
                "Eligible signature-loadout action IDs must be unique.",
                details={"record_id": record_id},
            )
        seen_ids.add(record_id)
        eligible_ids.append(record_id)

    eligible_count = len(eligible_ids)
    if eligible_count < 10:
        return eligible_ids, eligible_count, eligible_count
    return eligible_ids, 10, min(14, eligible_count)


def _reviewed_forced_provider_fields(record_id: Any, source_text: Any) -> frozenset[str]:
    if not isinstance(record_id, str):
        return frozenset()
    spec = _REVIEWED_FORCED_PROVIDER_FIELDS.get(record_id)
    if spec is None:
        return frozenset()
    if not isinstance(source_text, str) or _hash_text(source_text) != spec[0]:
        raise FoundryError(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
            "A reviewed override record is not bound to the sealed candidate source text.",
            details={"record_id": record_id},
        )
    return spec[1]


def _provider_authorable_fields(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    """Return missing fields plus exact reviewed override positions."""

    forced_fields = _reviewed_forced_provider_fields(
        candidate.get("record_id"),
        candidate.get("full_description"),
    )
    missing = candidate.get("missing_fields")
    if not isinstance(missing, (list, tuple, set, frozenset)):
        return ()
    missing_fields = {value for value in missing if isinstance(value, str)}
    return tuple(
        field
        for field in _PROVIDER_AUTHORABLE_FIELDS
        if (field in missing_fields or field in forced_fields)
        and (field in forced_fields or not _projection_is_resolved(_candidate_value(candidate, field)))
    )


def _projection_is_resolved(value: Any) -> bool:
    """Treat only meaningful candidate projections as server-resolved values."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        # A typed container is a present server projection even when empty;
        # it must never be delegated as though it were an absent scalar.
        return True
    return True


def _candidate_value(candidate: Mapping[str, Any], field: str) -> Any:
    if field == "name":
        return deepcopy(candidate.get("name"))
    if field in {"action_type", "bucket"}:
        return deepcopy(_candidate_action_type(candidate))
    if field == "action_id" and isinstance(candidate.get("record_id"), str):
        return f"action.{sha256_json({'record_id': candidate['record_id']})[:24]}"
    if field in {"resource_costs", "resource_gains", "resource_requirements"}:
        resources, _ = _strict_resource_projection(candidate)
        return deepcopy(resources.get(field) if resources is not None else None)
    return deepcopy(candidate.get(field))


def _locked_source_mapping(candidate: Mapping[str, Any]) -> dict[str, str] | None:
    """Validate the shape of a sealed source mapping.

    Shape validation is deliberately separate from the authority check below:
    a locked source is not trusted merely because its path, anchor, and digest
    look plausible.  The class-level proof resolves it against Command 2 and
    the exact extracted source bytes.
    """

    needs_locked_source = _LOCKED_SOURCE_FIELD in (candidate.get("missing_fields") or [])
    source = candidate.get("source")
    if source is None:
        if needs_locked_source:
            raise _response_error(
                "COMMAND4_LOCKED_SOURCE_INVALID",
                "A locked-source candidate must carry one sealed source mapping.",
                details={"record_id": candidate.get("record_id")},
            )
        return None
    if not isinstance(source, Mapping) or set(source) != _LOCKED_SOURCE_KEYS:
        raise _response_error(
            "COMMAND4_LOCKED_SOURCE_INVALID",
            "A locked source mapping must contain exactly path, anchor, and sha256.",
            details={"record_id": candidate.get("record_id")},
        )
    path = source.get("path")
    anchor = source.get("anchor")
    digest = source.get("sha256")
    source_path = Path(path) if isinstance(path, str) else None
    if (
        source_path is None
        or not path.strip()
        or source_path.is_absolute()
        or ".." in source_path.parts
        or not isinstance(anchor, str)
        or not anchor.strip()
        or not _is_hash(digest)
    ):
        raise _response_error(
            "COMMAND4_LOCKED_SOURCE_INVALID",
            "A sealed locked source mapping must use a relative path, nonblank anchor, and lower-case SHA-256.",
            details={"record_id": candidate.get("record_id")},
        )
    packet_ids = candidate.get("source_packet_ids")
    if needs_locked_source and (
        not isinstance(packet_ids, list)
        or not packet_ids
        or any(not isinstance(packet_id, str) or not packet_id.strip() for packet_id in packet_ids)
        or len(packet_ids) != len(set(packet_ids))
    ):
        raise _response_error(
            "COMMAND4_LOCKED_SOURCE_INVALID",
            "A locked source mapping must bind one or more unique nonblank source packet IDs.",
            details={"record_id": candidate.get("record_id")},
        )
    return {"path": path, "anchor": anchor, "sha256": digest} if _LOCKED_SOURCE_FIELD in (candidate.get("missing_fields") or []) else None


def _locked_source_proof(candidate: Mapping[str, Any]) -> dict[str, str] | None:
    """Backward-compatible name for the structural mapping check.

    Actual authority is only returned by
    :meth:`Command4ProviderAuthoring._resolve_locked_source_proof`.
    """

    return _locked_source_mapping(candidate)


def _normalize_source_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _candidate_source(candidate: Mapping[str, Any]) -> str:
    source = candidate.get("full_description")
    return source if isinstance(source, str) else ""


_FIELD_RELEVANCE_RULES = {
    "name": "A name is server-owned from the sealed candidate and is not provider-authorable.",
    "timing": "Use only the sealed timing/procedure span selected for this candidate.",
    "cost": "Cost is server-owned from one standalone Cost line and is not provider-authorable.",
    "range": "Use only the sealed explicit Range/Reach/Distance span; a trigger distance is not a range.",
    "target": "Use only the sealed target-selection or studied-subject span; an outcome mention is not a target.",
    "roll_save_check": "Use only the sealed attack, saving-throw, roll, or check resolution span.",
    "effect": "Use only the sealed substantive action-result or operation span.",
    "failure": "Use only the sealed explicit failure, failed-save, miss, or no-effect outcome span.",
    "duration": "Use only the sealed duration/persistence span, not a periodic effect or trigger.",
    "limit": "Use only the sealed usage-limit span; action economy and periodic effects are not use limits.",
    "counterplay": "Use only the sealed defense, resistance, prevention, or ending constraint span.",
}


def _source_quote_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _SOURCE_QUOTE_TOKEN_RE.findall(value))


def _is_substantive_source_quote(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    tokens = _source_quote_tokens(stripped)
    return (
        len(stripped) >= _MIN_SUBSTANTIVE_QUOTE_CHARS
        and len(tokens) >= _MIN_SUBSTANTIVE_QUOTE_TOKENS
        and any(len(token) >= 2 for token in tokens)
        and " ".join(tokens) not in _NON_SUBSTANTIVE_SOURCE_QUOTE_PHRASES
    )


# Synthetic/unit fixtures may carry an explicit, source-visible cue.  This is
# deliberately narrower than classifying arbitrary prose: production records
# below use the sealed identity table and never rely on keyword absence.
_EXPLICIT_FIELD_CUE_RE = re.compile(
    r"^\s*(?:narrative\s+)?(?P<label>timing|trigger|time|range|reach|distance|target|"
    r"roll|save|check|effect|failure|duration|limit|limits|use\s+limit|counterplay)\s+"
    r"(?:cue|signal|note)\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_EXPLICIT_NA_RE = re.compile(
    r"^\s*Command4\s+reviewed\s+N/?A\s*:\s*(?P<field>[A-Za-z_]+)\s*$",
    re.IGNORECASE,
)
_EXPLICIT_FIELD_LABELS = {
    "timing": "timing",
    "trigger": "timing",
    "time": "timing",
    "range": "range",
    "reach": "range",
    "distance": "range",
    "target": "target",
    "roll": "roll_save_check",
    "save": "roll_save_check",
    "check": "roll_save_check",
    "effect": "effect",
    "failure": "failure",
    "duration": "duration",
    "limit": "limit",
    "limits": "limit",
    "use limit": "limit",
    "counterplay": "counterplay",
}


def _explicit_source_domain(source_text: str, field: str) -> tuple[str, ...]:
    """Read only explicit fixture cue spans; arbitrary prose is not enough."""

    options: list[str] = []
    for raw_line in source_text.splitlines():
        match = _EXPLICIT_FIELD_CUE_RE.fullmatch(raw_line.strip())
        if match is None:
            continue
        label = " ".join(match.group("label").casefold().split())
        if _EXPLICIT_FIELD_LABELS.get(label) != field:
            continue
        value = match.group("value").strip()
        if _is_substantive_source_quote(value) and value in source_text and value not in options:
            options.append(value)
    return tuple(options)


def _explicit_source_na_fields(source_text: str) -> frozenset[str]:
    fields: set[str] = set()
    for raw_line in source_text.splitlines():
        match = _EXPLICIT_NA_RE.fullmatch(raw_line.strip())
        if match is None:
            continue
        field = match.group("field").casefold()
        if field in _PROVIDER_AUTHORABLE_FIELDS:
            fields.add(field)
    return frozenset(fields)


# These are the reviewed source spans for the retained 17-record Command 4
# ledger. ``None`` is an explicit reviewed N/A disposition, never a fallback
# for an unrecognized source.  The legacy table below is retained as historical
# source context; the option-record table immediately after it is authoritative.
_REVIEWED_PRODUCTION_DOMAIN_SPECS: dict[str, tuple[str, dict[str, tuple[str, ...] | None]]] = {
    "ASH_BASE_ASHFALL": (
        "1f9fe69af95ab5cf41b275cd79c24635871dd33fa5be4fac12cbf47c9a3c7634",
        {
            "roll_save_check": None,
            "effect": (
                "Create an area of falling cinders and settled residue.",
                "The area becomes Ash Terrain.",
            ),
            "failure": None,
            "limit": None,
            "counterplay": None,
        },
    ),
    "ASH_BASE_CINDER_BRAND": (
        "6f17676124438f4eff5d288279919e1d7450a2425045e6c7f81ee0f45da98a6e",
        {
            "target": None,
            "roll_save_check": ("Make a ranged Cultivation Attack.",),
            "effect": (
                "Release a streak of clinging ash.",
                "Hit: Deal Fire, Necrotic, or Psychic damage and apply Ashen Brand.",
            ),
            "failure": None,
            "duration": None,
            "limit": ("Once per turn when Cinder Brand hits, choose one:",),
            "counterplay": None,
        },
    ),
    "ASH_TAL_CINDER_BURST": (
        "1dd0635393fe935ea12f2856a09276b3a2788758dff05d086a9d221c8cd665eb",
        {
            "range": None,
            "roll_save_check": ("Creatures inside make Constitution saving throws.",),
            "duration": None,
            "limit": None,
            "counterplay": ("Successful Save: Take half damage.",),
        },
    ),
    "TAL_SCOUNDREL_DIRTY_TRICK": (
        "1022fc11c9db4a2710b5c4370487bcb7e8cbc5aff5c457ab946dd25d6b3fcd1b",
        {
            "target": ("Attempt an underhanded maneuver against one creature you can physically hinder.",),
            "roll_save_check": ("Make a Scoundrel Check against the target.",),
            "failure": None,
            "duration": ("until the start of your next turn",),
            "limit": None,
            "counterplay": (
                "the target or an adjacent creature can normally take the Utilize action to end that physical hindrance early.",
            ),
        },
    ),
    "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE": (
        "339e46f5a0baf77f804dd991e0660dbe1782abb1bbd67238a574f908e08c9786",
        {
            "roll_save_check": None,
            "effect": (
                "Reveal one plausible Tiny mundane object that you prepared or acquired before the current scene and could reasonably have concealed on your person.",
            ),
            "failure": None,
            "duration": (
                "It remains after being revealed until it is used, lost, destroyed, or discarded.",
            ),
            "counterplay": (
                "The object cannot be magical, alchemical, poisonous, unusually valuable,",
            ),
        },
    ),
    "TAL_SCOUNDREL_STEAL": (
        "f60a20a5e931ce1de79f7e78ae511cda6e661c0aacd0918b5ef5db285aa909da",
        {
            "target": ("Choose one accessible object.",),
            "roll_save_check": ("Make a Scoundrel Check against the creature.",),
            "failure": None,
            "duration": None,
            "limit": None,
            "counterplay": (
                "Steal does not automatically activate, identify, attune to, or safely handle the object.",
            ),
        },
    ),
    "tianxia.talent.ash.read_the_ruins": (
        "8315b63ed24b49110861fd2a5f81cc2cd8a5e61de4cad9bb2ea9ec85fefc4e91",
        {
            "timing": ("Timing Detail: Ritual",),
            "target": ("Study ash, soot, cinders, cremation residue, or burned remains.",),
            "roll_save_check": None,
            "effect": ("Learn broad information:",),
            "failure": None,
            "duration": ("Time: 10 minutes",),
            "limit": None,
            "counterplay": None,
        },
    ),
    "tianxia.talent.ash.ashen_step": (
        "5e3353e98061a6513847795649776cdc50a9efaf74ccd343c02ffd9f19675826",
        {
            "target": None,
            "roll_save_check": None,
            "effect": ("Dissolve into cinders and reform in one visible unoccupied space.",),
            "failure": None,
            "duration": None,
            "limit": None,
            "counterplay": ("cannot pass through sealed barriers",),
        },
    ),
    "tianxia.talent.ash.ash_ward": (
        "4c1aa338431a6b2812759897fc837c0d5680fe9db675a9e06c688c0e295d9fc0",
        {
            "range": None,
            "target": ("the protected creature",),
            "roll_save_check": None,
            "effect": ("Reduce the triggering damage:",),
            "failure": None,
            "duration": None,
            "limit": None,
            "counterplay": None,
        },
    ),
    "tianxia.talent.ash.remnant_harvest": (
        "496a8969c2391cd7128cb2650fde71023ede93a6e981713e48dfda754cbf1ff2",
        {
            "target": ("Consume one Remnant you created.",),
            "roll_save_check": None,
            "effect": (
                "reduce the CP cost of your next Ash talent before the end of your turn by 1, minimum 1;",
                "gain Temporary HP equal to your Proficiency Bonus;",
            ),
            "failure": None,
            "duration": ("before the end of your turn",),
            "limit": None,
            "counterplay": ("without provoking opportunity attacks",),
        },
    ),
    "tianxia.talent.ash.ash_form": (
        "1cd5e8c2dc64ee39a30fa8b954b8d50d4cb7e92971289b82834bbf0efa90bbf4",
        {
            "range": None,
            "target": None,
            "roll_save_check": None,
            "effect": ("Become a drifting cinder-body.",),
            "failure": None,
            "limit": None,
            "counterplay": ("Ash Form does not allow movement through solid barriers.",),
        },
    ),
    "ASH_TAL_RUINOUS_ASH": (
        "0627ec11fe5b85bb51d24636cf4e58e7502cfcf6ac08d946c6d8826d96ab7286",
        {
            "target": ("Choose one object, Barrier, structure section, Formation Anchor, or Construct.",),
            "roll_save_check": ("Make a ranged Cultivation Attack if the target is mobile or actively defended.",),
            "effect": ("Deal Fire or Necrotic damage.",),
            "failure": None,
            "duration": None,
            "limit": None,
            "counterplay": None,
        },
    ),
    "ASH_TAL_ASHEN_BURIAL": (
        "6c35bb5f68cf5ad35b522baad6b121e5f40f19b56eecabb173259f95b8ff6115",
        {
            "target": ("Choose one creature touching the ground.",),
            "roll_save_check": ("The target makes a Strength saving throw.",),
            "limit": None,
            "counterplay": (
                "Repeat the saving throw at the end of each turn, ending the effect on a success.",
            ),
        },
    ),
    "tianxia.talent.ash.ashen_wasteland": (
        "77ed96ee14da21984577f860f5c018023ea210fc71b447f9e60cafa3ef5bdd5b",
        {
            "roll_save_check": ("makes a Constitution saving throw.",),
            "limit": ("A creature takes this damage only once per turn.",),
            "counterplay": ("Successful Save: Take half damage.",),
        },
    ),
    "tianxia.talent.ash.ash_clone": (
        "e4ae23726631bab09dfe35f6aeb84478071f8a5cf6dc935a37563d349f05a61f",
        {
            "target": None,
            "roll_save_check": ("Attack: Your Cultivation Attack Modifier",),
            "effect": ("Create one humanoid cinder figure.",),
            "failure": None,
            "limit": None,
            "counterplay": None,
        },
    ),
    "ASH_TAL_CREMATION_PRISON": (
        "a20bfca204cc0b9713f18cb1a175dd39ab6ce6cee0b630f4f9a1f851d227358d",
        {
            "target": ("Choose one creature.",),
            "roll_save_check": ("The target makes a Constitution saving throw.",),
            "limit": None,
            "counterplay": (
                "repeat the saving throw at the end of each turn, ending the effect on a success.",
            ),
        },
    ),
    "tianxia.talent.ash.ash_sovereign_incarnation": (
        "92f7280c7b193576a1424dbad6f718f2bc546c2f31cf2fda364fcf8259b97ff1",
        {
            "range": None,
            "target": None,
            "roll_save_check": None,
            "effect": ("Become a sovereign cinder-body.",),
            "failure": None,
            "counterplay": ("Immunity to Smothered;",),
        },
    ),
}


def _source_quote_span(start: int, end: int | None = None) -> dict[str, Any]:
    return {"authority": "source_quote", "span": (start, end if end is not None else start)}


def _source_quote_literal(value: str) -> dict[str, Any]:
    return {"authority": "source_quote", "value": value}


def _bounded_span(value: str, start: int, end: int | None = None) -> dict[str, Any]:
    return {
        "authority": "bounded_interpretation",
        "provider_value": value,
        "span": (start, end if end is not None else start),
    }


def _not_applicable() -> dict[str, Any]:
    return {"authority": "not_applicable"}


# Unlike the old keyword-derived table, this table names complete, reviewed
# source blocks or an explicit server-reviewed normalization for every live
# provider-authorable slot.  Span coordinates are 1-based source line ranges;
# the immutable candidate hash below makes the coordinates fail closed if the
# sealed text changes.
_S = _source_quote_span
_L = _source_quote_literal
_B = _bounded_span
_N = _not_applicable

_REVIEWED_PRODUCTION_DOMAIN_OPTION_SPECS: dict[
    str, tuple[str, dict[str, tuple[dict[str, Any], ...]]]
] = {
    "TAL_KARMA_INVOKE_THE_LEDGER": (
        "3429b70c531666a34539adb7bdf28d9adeb17b8a8f01a71c1f439ffd2bf65f81",
        {
            "roll_save_check": (_N(),),
            "effect": (_S(8, 12),),
            "failure": (_N(),),
            "duration": (_L("before the end of your next turn"),),
            "limit": (_S(11),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_KARMA_LEDGER_EYE": (
        "ca71501bac6ec242e054cbe91a999537f840a7cd69e5577abc19c9820d18f1fa",
        {
            "roll_save_check": (_N(),),
            "effect": (_S(8, 17),),
            "failure": (_N(),),
            "duration": (_B("The selected questions are answered as this action resolves.", 8, 17),),
            "limit": (_S(17),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_KARMA_RECORD_THE_DEED": (
        "832b87621c4107293dade5e46b9c80a4677dd84e2451de8363a5ec6d6b127c4d",
        {
            "target": (_S(9),),
            "roll_save_check": (_N(),),
            "effect": (_S(8, 26),),
            "failure": (_N(),),
            "duration": (_B("Instantaneous placement of one Karmic Imprint; this does not set the Imprint's lifetime.", 8, 9),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_KARMA_SETTLE_MINOR_ACCOUNT": (
        "494fffd040e4b8db000ec4d5eceecf953e9cb15dcd0b1ddf6141d7e0be0fc879",
        {
            "roll_save_check": (_S(9),),
            "effect": (_S(8, 13),),
            "failure": (_B("Debt uses its printed successful-save result; Grace specifies no activation failure.", 9, 12),),
            "duration": (_B("Debt's Reaction restriction lasts until the start of the target's next turn; Grace grants Temporary HP and immediately ends one listed minor effect.", 10, 12),),
            "limit": (_N(),),
            "counterplay": (_S(11),),
        },
    ),
    "tianxia.talent.karma.witness_seal": (
        "8145d4adcac8aca2bb7941f9f3065498d48384c7f5852722836637ca75821f15",
        {
            "range": (_L("within 60 feet"),),
            "target": (_S(5),),
            "roll_save_check": (_N(),),
            "effect": (_S(8, 10),),
            "failure": (_N(),),
            "limit": (_N(),),
            "counterplay": (_N(),),
        },
    ),
    "tianxia.talent.karma.minor_oath": (
        "5b4508bad308fd1f1f05886ce4252e4b36460c138b50f310da4cd35781245a4a",
        {
            "target": (_S(11),),
            "roll_save_check": (_N(),),
            "effect": (_S(11, 24),),
            "failure": (_N(),),
            "limit": (_S(24),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_ALCHEMY_NUMBING_POWDER": (
        "7410240deb7b440bb63d5e6d633b0272fca7ac0b87cddb2ccc3cc0ed15debb54",
        {
            "target": (_L("one creature within range"),),
            "roll_save_check": (_L("The target makes a Constitution saving throw."),),
            "effect": (_S(10, 12),),
            "failure": (_S(11),),
            "duration": (_L("until the start of your next turn"),),
            "limit": (_N(),),
            "counterplay": (_S(11),),
        },
    ),
    "TAL_ATHLETICS_BODY_BEYOND_DISTANCE": (
        "115053c7e4dd98ddcf1ddb491f47cc7bbad6d18dc6fa5488484ca2cb6f5f97e6",
        {
            "range": (_B("Self", 8, 14),),
            "target": (_B("You, with up to one willing creature of your size or smaller carried as described.", 8, 14),),
            "roll_save_check": (_N(),),
            "effect": (_S(8, 14),),
            "failure": (_N(),),
            "counterplay": (_S(14),),
        },
    ),
    "ALCHEMY_BASE_FIELD_FORMULA": (
        _REVIEWED_FORCED_PROVIDER_FIELDS["ALCHEMY_BASE_FIELD_FORMULA"][0],
        {
            # One option carries the complete mode contract.  Splitting the
            # source into provider-selectable mode rows would allow mixing
            # target/effect/save branches that the runtime must choose
            # atomically at use time.
            "target": (_B(
                "Medicinal Smoke: choose yourself or one ally within range; "
                "Numbing Smoke: choose a point within range, filling a 5-foot-radius Sphere "
                "and selecting each hostile creature of your choice in it; "
                "Corrosive Dregs: choose one creature or one 5-foot space within range, "
                "with the target or each hostile creature of your choice in that space.",
                9,
                20,
            ),),
            "roll_save_check": (_B(
                "Medicinal Smoke: no saving throw is specified; "
                "Numbing Smoke: Constitution saving throw; "
                "Corrosive Dregs: Dexterity saving throw.",
                9,
                20,
            ),),
            "effect": (_B(
                "Medicinal Smoke: the target gains Temporary HP equal to 1d6 plus the Alchemy "
                "key ability modifier and may immediately repeat one saving throw against Poisoned; "
                "Numbing Smoke: the creature takes Poison damage equal to 1d6 plus the modifier "
                "and cannot take Reactions until the start of your next turn; "
                "Corrosive Dregs: the creature takes Acid damage equal to 1d6 plus the modifier, "
                "is covered in unstable residue until the start of your next turn, and the first "
                "damage before then adds Acid damage equal to your Proficiency Bonus. "
                "Medicinal Temporary HP and both damage tracks increase to 2d6 at CL 5, 3d6 at CL 11, "
                "and 4d6 at CL 17.",
                9,
                23,
            ),),
            "failure": (_B(
                "Medicinal Smoke resolves without a saving throw; Numbing Smoke failed save: "
                "Poison damage and no Reactions until the start of your next turn, successful save: "
                "half damage and no Reaction loss; Corrosive Dregs failed save: Acid damage and "
                "unstable residue with the first-damage rider, successful save: half damage and no residue.",
                9,
                23,
            ),),
            "duration": (_B(
                "Medicinal Smoke grants Temporary HP and an immediate repeat-save benefit; "
                "Numbing Smoke denies Reactions until the start of your next turn; "
                "Corrosive Dregs leaves unstable residue until the start of your next turn, "
                "with its first-damage rider applying before then.",
                9,
                23,
            ),),
            "limit": (_N(),),
            "counterplay": (_B(
                "Medicinal Smoke permits an immediate repeat saving throw against Poisoned; "
                "a successful Numbing Smoke save halves damage and avoids Reaction loss; "
                "a successful Corrosive Dregs save halves damage and avoids residue.",
                9,
                23,
            ),),
        },
    ),
    "TAL_ALCHEMY_FURNACE_VENT": (
        _REVIEWED_FORCED_PROVIDER_FIELDS["TAL_ALCHEMY_FURNACE_VENT"][0],
        {
            "timing": (_B(
                "Action; resolved as a Field Formula.",
                2,
                5,
            ),),
            "range": (_B(
                "Self (15-foot cone).",
                7,
            ),),
            "target": (_B(
                "Each creature in the 15-foot cone.",
                7,
                9,
            ),),
            "roll_save_check": (_B(
                "Constitution saving throw.",
                9,
            ),),
            "duration": (_B(
                "Damage resolves immediately; Disadvantage lasts until the start of your next turn.",
                10,
                11,
            ),),
            "limit": (_N(),),
            "counterplay": (_B(
                "A successful save halves damage and avoids Disadvantage; the next Constitution saving throw rider lasts until the start of your next turn.",
                10,
                12,
            ),),
        },
    ),
    "TAL_ALCHEMY_EXPLOSIVE_PILL": (
        _REVIEWED_FORCED_PROVIDER_FIELDS["TAL_ALCHEMY_EXPLOSIVE_PILL"][0],
        {
            "target": (_B(
                "Each creature in the 10-foot-radius Sphere within 60 feet.",
                11,
                13,
            ),),
            "roll_save_check": (_B(
                "Dexterity saving throw.",
                13,
            ),),
            "effect": (_B(
                "The creature takes damage of the Acid, Cold, Fire, Lightning, or Poison type chosen "
                "when the pill is refined; damage scales by CL: 4d6 at CL 5-10, 6d6 at CL 11-16, "
                "and 8d6 at CL 17-20.",
                13,
                19,
            ),),
            "failure": (_B(
                "On a failed save, the creature takes the chosen damage; a successful save deals half damage.",
                13,
                16,
            ),),
            "duration": (_B(
                "The damage is resolved immediately; no ongoing duration is specified.",
                13,
                19,
            ),),
            "limit": (_N(),),
            "counterplay": (_B(
                "A successful Dexterity saving throw halves the damage.",
                13,
                16,
            ),),
        },
    ),
    "TAL_ALCHEMY_CHOKING_SMOKE_PELLET": (
        _REVIEWED_FORCED_PROVIDER_FIELDS["TAL_ALCHEMY_CHOKING_SMOKE_PELLET"][0],
        {
            "timing": (_B(
                "Action; resolved as a Field Formula.",
                3,
                7,
            ),),
            "target": (_B(
                "Each hostile creature of your choice in the 10-foot-radius Sphere.",
                9,
                11,
            ),),
            "roll_save_check": (_B(
                "Constitution saving throw.",
                11,
            ),),
            "effect": (_B(
                "The creature takes 2d6 Poison damage, cannot speak above a hoarse whisper, and cannot "
                "supply Verbal components until the start of your next turn. At CL 11, the damage becomes "
                "3d6; at CL 17, it becomes 4d6.",
                11,
                14,
            ),),
            "failure": (_B(
                "A successful save deals half damage and imposes no speech restriction.",
                12,
                13,
            ),),
            "duration": (_B(
                "Damage resolves immediately; speech and Verbal-component restrictions last until the start "
                "of your next turn.",
                12,
                13,
            ),),
            "limit": (_N(),),
            "counterplay": (_B(
                "Creatures that do not breathe have Advantage on this save unless the GM decides the formula "
                "attacks their spiritual circulation instead.",
                15,
            ),),
        },
    ),
    "TAL_ALCHEMY_BINDING_DREGS": (
        _REVIEWED_FORCED_PROVIDER_FIELDS["TAL_ALCHEMY_BINDING_DREGS"][0],
        {
            "timing": (_B(
                "Action; resolved as a Field Formula.",
                2,
                6,
            ),),
            "target": (_B(
                "Choose one creature within 30 feet.",
                7,
                9,
            ),),
            "roll_save_check": (_B(
                "Strength saving throw.",
                9,
            ),),
            "duration": (_B(
                "Speed reduction and any Dash prohibition last until the start of your next turn.",
                10,
                11,
            ),),
            "limit": (_N(),),
            "counterplay": (_B(
                "A successful Strength save reduces Speed by only 5 feet and avoids the solid-surface Dash prohibition.",
                9,
                11,
            ),),
        },
    ),
    "AIR_BASE_GATHER_CURRENT": (
        "69096b851ff5d37d3a5c66c0c04799e34d9ee31a083383c83bf2e6e3ef8ab75e",
        {
            "target": (_S(8),),
            "roll_save_check": (_N(),),
            "effect": (_S(9, 14),),
            "failure": (_N(),),
            "limit": (_S(15),),
            "counterplay": (_N(),),
        },
    ),
    "AIR_BASE_WIND_LASH": (
        "f187b597d2db0f580a39d34fd664611ce580ae950fcc103ce162b05eb96976d6",
        {
            "roll_save_check": (_S(9),),
            "effect": (_S(8, 16),),
            "failure": (_B("On a miss, the attack deals no hit damage and applies no Wind Lash Vector effect.", 9),),
            "duration": (_L("until the start of your next turn"),),
            "limit": (_S(17),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_AIR_ARROW_TURNING_BREATH": (
        "e839ca78d13adddee5a15c631636c7a49274624f1622461689b3c8af419431d4",
        {
            "range": (_L("within 30 feet"),),
            "target": (_S(4),),
            "roll_save_check": (_S(6),),
            "failure": (_B("A failed Air Check leaves the triggering attack unchanged.", 6, 8),),
            "duration": (_B(
                "The reaction resolves during the triggering attack; no continuing duration is printed.",
                6,
                8,
            ),),
            "limit": (_S(9),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_AIR_FEATHER_FALL_BREATH": (
        "152438f4fb50943718e517ea13483aec047d99759d496dfca282465b68c3d50e",
        {
            "range": (_L("within 30 feet"),),
            "target": (_S(4),),
            "roll_save_check": (_N(),),
            "effect": (_S(6),),
            "failure": (_N(),),
            "duration": (_B(
                "The fall-distance reduction applies to the triggering fall; no continuing duration is printed.",
                6,
                7,
            ),),
            "limit": (_S(7),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_SCOUNDREL_BOB_AND_WEAVE": (
        "94f1ec7c548e35998cd019714cefc76908ae7822679cc4562fbcd8fc6521a54e",
        {
            "roll_save_check": (_N(),),
            "effect": (_S(9),),
            "failure": (_N(),),
            "limit": (_S(10),),
            "counterplay": (_S(10),),
        },
    ),
    "TAL_AIR_DOWNBURST_SEAL": (
        "a461d27587bfc9a162371db9725bfb03ffa8fb3df336a07da3fcdad9b15c9e55",
        {
            "roll_save_check": (_S(9),),
            "duration": (_B(
                "Damage, forced movement, and the Prone result resolve immediately; no continuing duration is printed.",
                9,
                11,
            ),),
            "limit": (_N(),),
            "counterplay": (_S(11),),
        },
    ),
    "TAL_AIR_UPDRAFT_GATE": (
        "32c0452b142c6b28473dc825a44e91f8ea528dfe3ad606151c68d443f84019d7",
        {
            "target": (_S(9),),
            "roll_save_check": (_S(9),),
            "limit": (_N(),),
            "counterplay": (_S(10, 12),),
        },
    ),
    "TAL_AIR_WIND_WALL": (
        "f09d464ae7d303a9396b3638d5e966fd51c792783e262ea33bb7e5cea5d68e68",
        {
            "target": (_S(8),),
            "roll_save_check": (_S(10),),
            "effect": (_S(9),),
            "failure": (_S(10),),
            "limit": (_S(11),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_AIR_SKY_ROAD": (
        "3d8ff8ac3ffcd8705e623a84c3d26532fc4efeabfb450b76f9178a5554b6115f",
        {
            "target": (_S(9),),
            "roll_save_check": (_S(9),),
            "effect": (_S(9),),
            "failure": (_S(9),),
            "limit": (_S(8),),
            "counterplay": (_N(),),
        },
    ),
    "TAL_AIR_TURN_THE_HUNDRED_ARROWS": (
        "1b2e933b7571b46ef1d80c6995d8821e4f2f886d175407333d8e61cb9f6f49c3",
        {
            "range": (_B(
                "No standalone range is printed; the reaction is limited by its trigger inside one of your Air Currents.",
                5,
            ),),
            "target": (_S(7),),
            "roll_save_check": (_N(),),
            "effect": (_S(7, 8),),
            "failure": (_N(),),
            "duration": (_B(
                "The reaction applies to the triggering attacks; projectile movement ends when each projectile falls harmlessly or sticks.",
                7,
                8,
            ),),
            "limit": (_N(),),
            "counterplay": (_S(8),),
        },
    ),
    "TAL_AIR_BREATHLESS_CHAMBER": (
        "0cf8ffa2ac129fcbb2649bcd3ceee2cbd83eb3c73851916e950e0d76f0f4be58",
        {
            "roll_save_check": (_S(10),),
            "limit": (_S(13),),
            "counterplay": (_S(10, 13),),
        },
    ),
    "TAL_AIR_COURT_OF_THE_FOUR_WINDS": (
        "61b04f75c40a82a14614bcb64c4e3c03f43742539baedb4c8403afe071494084",
        {
            "roll_save_check": (_N(),),
            "effect": (_S(10, 18),),
            "failure": (_N(),),
            "counterplay": (_S(19),),
        },
    ),
    "TAL_AIR_CYCLONE_PRISON": (
        "fba54e450d01656d99759f2726666106025c1b5fb33f6150b2f395acbde1df34",
        {
            "roll_save_check": (_S(10),),
            "limit": (_N(),),
            "counterplay": (_S(13),),
        },
    ),
    "TAL_AIR_EMPTY_LUNG_EDICT": (
        "335cfa6c781cbf6cb336d8a2450630de525b8eee43d7a4679584bb672ed7b1a9",
        {
            "roll_save_check": (_S(10),),
            "duration": (_S(11, 12),),
            "counterplay": (_S(13),),
        },
    ),
    "TAL_AIR_HEAVEN_SPLITTING_GALE": (
        "e6a51cf5f8a71738607862489ee0ef4888391397985a53a7171dbcfba9fb28ce",
        {
            "roll_save_check": (_S(9),),
            "duration": (_S(10, 11),),
            "limit": (_S(12),),
            "counterplay": (_S(11),),
        },
    ),
    "TAL_AIR_TEN_THOUSAND_ARROW_REVERSAL": (
        "1f6934002d33111f32623c8a48c24a71809ac9190fd3d7260c7c69b1b165e41a",
        {
            "range": (_B(
                "No standalone range is printed; the reaction is limited by its trigger in a 60-foot-radius area you can see.",
                5,
            ),),
            "target": (_S(9),),
            "roll_save_check": (_S(8),),
            "duration": (_B(
                "The negation and any harmless projectile movement apply to the triggering volley when this reaction resolves.",
                9,
            ),),
            "counterplay": (_S(10, 11),),
        },
    ),
    "TAL_AIR_STORM_WITHOUT_DIRECTION": (
        "132d17b8a0857fa1aba0213d7d34c0c2372d5ef2c68ab60a5e60f7b9e7fac1cb",
        {
            "roll_save_check": (_S(13),),
            "effect": (_S(10, 15),),
            "failure": (_S(13),),
            "limit": (_S(10),),
            "counterplay": (_S(10),),
        },
    ),
    "TAL_SCOUNDREL_COURT_OF_TEN_THOUSAND_EMPTY_SLEEVES": (
        "dd774d7f113d491e20411264b84d84dd4c7b2bd78b7081fac76eb877a7e8f73a",
        {
            "range": (_B(
                "No standalone range is printed; the activation's area is the printed 30-foot Emanation.",
                6,
            ),),
            "roll_save_check": (_N(),),
            "effect": (_S(10, 18),),
            "failure": (_N(),),
            "counterplay": (_S(19),),
        },
    ),
    "TAL_AIR_SKY_SOVEREIGN_INCARNATION": (
        "ccbe69b3882bc97a0ed35096bf69194acf495a4c2e4b283bd0607f99f33d170a",
        {
            "range": (_B(
                "No standalone activation range is printed; the transformation's listed effects retain their own ranges.",
                12,
                17,
            ),),
            "target": (_S(15, 17),),
            "roll_save_check": (_S(15),),
            "effect": (_S(9, 17),),
            "failure": (_S(15),),
            "counterplay": (_S(18),),
        },
    ),
    "TAL_SCOUNDREL_EMPTY_HANDED_THEFT_OF_HEAVEN": (
        "3942f51185e4799fbf8e6e2a5b200f81163cbff72907d569b99ca0ccadff8245",
        {
            "range": (_B(
                "No standalone range is printed; the reaction is limited by its trigger inside your Empty-Sleeve Hand range.",
                5,
            ),),
            "target": (_S(5),),
            "roll_save_check": (_S(8),),
            "duration": (_L("until the end of your next turn"),),
            "counterplay": (_S(17),),
        },
    ),
    "TAL_AIR_WHEN_HEAVEN_EXHALES": (
        "e3fb23b948c30b94d4f952c2476becba6fddd20ce4cb513628df3ed4f906af33",
        {
            "roll_save_check": (_S(13, 17),),
            "effect": (_S(12, 19),),
            "failure": (_S(13, 17),),
            "counterplay": (_S(20),),
        },
    ),
    "TAL_SCOUNDREL_EVERYTHING_IN_THE_WRONG_PLACE": (
        "dd1879ccce41981bb8e63723625c2baef5ef38872f51773636135af49437f64e",
        {
            "range": (_B(
                "No standalone range is printed; the activation's area is the printed 30-foot Emanation.",
                5,
            ),),
            "roll_save_check": (_S(9),),
            "duration": (_L("until the end of your next turn"),),
            "counterplay": (_S(17, 18),),
        },
    ),
    "TAL_SCOUNDREL_SOVEREIGN_OF_TEN_THOUSAND_EMPTY_SLEEVES": (
        "34761c3c5a0155fe0913ba1d4e987a1f039f15c05f5de47b6a2c7de9af5b996a",
        {
            "range": (_B(
                "No standalone activation range is printed; the transformation's listed effects retain their own ranges.",
                11,
                18,
            ),),
            "target": (_S(9),),
            "roll_save_check": (_N(),),
            "effect": (_S(10, 18),),
            "failure": (_N(),),
            "counterplay": (_S(19),),
        },
    ),
    "ASH_BASE_ASHFALL": (
        "1f9fe69af95ab5cf41b275cd79c24635871dd33fa5be4fac12cbf47c9a3c7634",
        {
            "roll_save_check": (_N(),),
            "effect": (_S(9, 14),),
            "failure": (_N(),),
            "limit": (_N(),),
            "counterplay": (_N(),),
        },
    ),
    "ASH_BASE_CINDER_BRAND": (
        "6f17676124438f4eff5d288279919e1d7450a2425045e6c7f81ee0f45da98a6e",
        {
            "target": (_B("Target of the ranged Cultivation Attack", 8, 9),),
            "roll_save_check": (_S(8),),
            "effect": (_S(7, 20),),
            "failure": (_B("On a miss, no effect", 8, 9),),
            "duration": (_B("Instantaneous; listed rider durations apply as stated", 9, 20),),
            "limit": (_S(16, 20),),
            "counterplay": (_N(),),
        },
    ),
    "ASH_TAL_CINDER_BURST": (
        "1dd0635393fe935ea12f2856a09276b3a2788758dff05d086a9d221c8cd665eb",
        {
            "range": (_B("Self (15-foot cone)", 4),),
            "roll_save_check": (_S(6),),
            "duration": (_B(
                "Instantaneous; failed-save reaction denial lasts until start of next turn",
                7, 8,
            ),),
            "limit": (_N(),),
            "counterplay": (_S(8),),
        },
    ),
    "TAL_SCOUNDREL_DIRTY_TRICK": (
        "1022fc11c9db4a2710b5c4370487bcb7e8cbc5aff5c457ab946dd25d6b3fcd1b",
        {
            "target": (_S(7),),
            "roll_save_check": (_S(9),),
            "failure": (_B("On a failed check, no listed success result applies.", 9, 10),),
            "duration": (_L("until the start of your next turn"),),
            "limit": (_N(),),
            "counterplay": (_S(19),),
        },
    ),
    "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE": (
        "339e46f5a0baf77f804dd991e0660dbe1782abb1bbd67238a574f908e08c9786",
        {
            "roll_save_check": (_N(),),
            "effect": (_S(8, 12),),
            "failure": (_N(),),
            "duration": (_S(10),),
            "counterplay": (_S(11, 12),),
        },
    ),
    "TAL_SCOUNDREL_STEAL": (
        "f60a20a5e931ce1de79f7e78ae511cda6e661c0aacd0918b5ef5db285aa909da",
        {
            "target": (_S(7),),
            "roll_save_check": (_S(8, 13),),
            "failure": (_B("On a failed check, no listed success result applies.", 14, 15),),
            "duration": (_B("Instantaneous", 7, 21),),
            "limit": (_N(),),
            "counterplay": (_S(21),),
        },
    ),
    "tianxia.talent.ash.read_the_ruins": (
        "8315b63ed24b49110861fd2a5f81cc2cd8a5e61de4cad9bb2ea9ec85fefc4e91",
        {
            "timing": (_S(4),),
            "target": (_S(8),),
            "roll_save_check": (_N(),),
            "effect": (_S(9, 15),),
            "failure": (_N(),),
            "duration": (_S(5),),
            "limit": (_S(16),),
            "counterplay": (_S(16),),
        },
    ),
    "tianxia.talent.ash.ashen_step": (
        "5e3353e98061a6513847795649776cdc50a9efaf74ccd343c02ffd9f19675826",
        {
            "target": (_B("One visible unoccupied space within range", 6),),
            "roll_save_check": (_N(),),
            "effect": (_S(6, 13),),
            "failure": (_N(),),
            "duration": (_B("Instantaneous", 6),),
            "limit": (_N(),),
            "counterplay": (_S(7, 12),),
        },
    ),
    "tianxia.talent.ash.ash_ward": (
        "4c1aa338431a6b2812759897fc837c0d5680fe9db675a9e06c688c0e295d9fc0",
        {
            "range": (_B("Within 30 feet", 4),),
            "target": (_B("You or an ally within 30 feet", 4),),
            "roll_save_check": (_N(),),
            "effect": (_S(6, 13),),
            "failure": (_N(),),
            "duration": (_B("Instantaneous", 6, 13),),
            "limit": (_N(),),
            "counterplay": (_N(),),
        },
    ),
    "tianxia.talent.ash.remnant_harvest": (
        "496a8969c2391cd7128cb2650fde71023ede93a6e981713e48dfda754cbf1ff2",
        {
            "target": (_S(7),),
            "roll_save_check": (_N(),),
            "effect": (_S(8, 13),),
            "failure": (_N(),),
            "duration": (_B("Instantaneous with listed rider durations as stated", 8, 13),),
            "limit": (_N(),),
            "counterplay": (_N(),),
        },
    ),
    "tianxia.talent.ash.ash_form": (
        "1cd5e8c2dc64ee39a30fa8b954b8d50d4cb7e92971289b82834bbf0efa90bbf4",
        {
            "range": (_B("Self", 7),),
            "target": (_B("Self", 7),),
            "roll_save_check": (_N(),),
            "effect": (_S(7, 14),),
            "failure": (_N(),),
            "limit": (_N(),),
            "counterplay": (_S(15),),
        },
    ),
    "ASH_TAL_RUINOUS_ASH": (
        "0627ec11fe5b85bb51d24636cf4e58e7502cfcf6ac08d946c6d8826d96ab7286",
        {
            "target": (_S(7),),
            "roll_save_check": (_S(8),),
            "effect": (_S(9, 18),),
            "failure": (_B("On a miss, no damage or Remnant is created", 8, 18),),
            "duration": (_B("Instantaneous", 9, 18),),
            "limit": (_N(),),
            "counterplay": (_S(16),),
        },
    ),
    "ASH_TAL_ASHEN_BURIAL": (
        "6c35bb5f68cf5ad35b522baad6b121e5f40f19b56eecabb173259f95b8ff6115",
        {
            "target": (_S(8),),
            "roll_save_check": (_S(9),),
            "limit": (_N(),),
            "counterplay": (_S(10),),
        },
    ),
    "tianxia.talent.ash.ashen_wasteland": (
        "77ed96ee14da21984577f860f5c018023ea210fc71b447f9e60cafa3ef5bdd5b",
        {
            "roll_save_check": (_S(10, 12),),
            "limit": (_S(17),),
            "counterplay": (_S(12),),
        },
    ),
    "tianxia.talent.ash.ash_clone": (
        "e4ae23726631bab09dfe35f6aeb84478071f8a5cf6dc935a37563d349f05a61f",
        {
            "target": (_B("One humanoid cinder figure created within 30 feet", 5, 8),),
            "roll_save_check": (_S(24, 26),),
            "effect": (_S(8, 27),),
            "failure": (_B("On a failed Cinder Strike, no damage is dealt", 24, 27),),
            "limit": (_S(16, 23),),
            "counterplay": (_N(),),
        },
    ),
    "ASH_TAL_CREMATION_PRISON": (
        "a20bfca204cc0b9713f18cb1a175dd39ab6ce6cee0b630f4f9a1f851d227358d",
        {
            "target": (_S(8),),
            "roll_save_check": (_S(9),),
            "limit": (_N(),),
            "counterplay": (_S(10, 17),),
        },
    ),
    "tianxia.talent.ash.ash_sovereign_incarnation": (
        "92f7280c7b193576a1424dbad6f718f2bc546c2f31cf2fda364fcf8259b97ff1",
        {
            "range": (_B("Self", 8),),
            "target": (_B("Self", 8),),
            "roll_save_check": (_N(),),
            "effect": (_S(8, 18),),
            "failure": (_N(),),
            "counterplay": (_N(),),
        },
    ),
}

# Keep the documented symbol name bound to the strict option records so
# callers/tests cannot accidentally inspect the superseded bare-string table.
_REVIEWED_PRODUCTION_DOMAIN_SPECS = _REVIEWED_PRODUCTION_DOMAIN_OPTION_SPECS


def _reviewed_production_source_binding(record_id: Any, source_text: Any) -> bool:
    """Verify the exact source commitment for a reviewed production row."""

    if not isinstance(record_id, str):
        return False
    spec = _REVIEWED_PRODUCTION_DOMAIN_SPECS.get(record_id)
    if spec is None:
        return False
    expected_hash = spec[0]
    if not _is_hash(expected_hash) or not isinstance(source_text, str) or _hash_text(source_text) != expected_hash:
        raise FoundryError(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
            "The reviewed field domain is not bound to the sealed candidate source text.",
            details={"record_id": record_id},
        )
    return True


def _domain_record(
    options: tuple[Any, ...],
    *,
    kind: str,
) -> dict[str, Any]:
    option_records: list[dict[str, Any]] = []
    for option in options:
        if isinstance(option, Mapping):
            record = deepcopy(dict(option))
        else:
            record = {
                "provider_value": str(option),
                "authority": "source_quote",
                "evidence": str(option),
            }
        if set(record) != {"provider_value", "authority", "evidence"}:
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "A provider field option must contain only provider value, authority, and evidence.",
            )
        option_records.append(record)
    if not option_records and kind == "server_proven_not_applicable":
        option_records = [{
            "provider_value": COMMAND4_NOT_APPLICABLE_QUOTE,
            "authority": "not_applicable",
            "evidence": None,
        }]
    authorities = [record["authority"] for record in option_records]
    unique_authorities = list(dict.fromkeys(authorities))
    values = [record["provider_value"] for record in option_records]
    return {
        "options": values,
        "option_records": option_records,
        "kind": kind,
        "allowed_authorities": unique_authorities,
        "source_quote": "source_quote" in unique_authorities,
        "not_applicable": unique_authorities == ["not_applicable"],
        "bounded_interpretation": "bounded_interpretation" in unique_authorities,
    }


_OPTION_TOKEN_RE = re.compile(r"^c4opt_[A-Za-z0-9_-]{16}$")


def _provider_option_token(
    record_id: str,
    field: str,
    source_text_sha256: str,
    option_record: Mapping[str, Any],
) -> str:
    """Derive one opaque, collision-resistant token for a sealed option."""

    if not isinstance(record_id, str) or not record_id.strip() or not isinstance(field, str) or not field.strip():
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_TOKEN_INVALID",
            "An option token requires a nonblank sealed record and field identity.",
        )
    if not _is_hash(source_text_sha256):
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_TOKEN_INVALID",
            "An option token requires a lower-case source-text hash.",
            details={"record_id": record_id, "field": field},
        )
    if not isinstance(option_record, Mapping) or set(option_record) != {"provider_value", "authority", "evidence"}:
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_TOKEN_INVALID",
            "An option token requires one exact option record.",
            details={"record_id": record_id, "field": field},
        )
    commitment = {
        "record_id": record_id,
        "field": field,
        "source_text_sha256": source_text_sha256,
        "option_record": deepcopy(dict(option_record)),
    }
    digest = hashlib.sha256(canonical_json(commitment).encode("utf-8")).digest()
    # Twelve digest bytes provide 96 bits of commitment while URL-safe base64
    # keeps the provider-facing token short and portable.  The full canonical
    # option record remains the server-side binding and is re-derived on use.
    encoded = base64.urlsafe_b64encode(digest[:12]).decode("ascii").rstrip("=")
    return "c4opt_" + encoded


def _domain_with_selection_tokens(
    candidate: Mapping[str, Any],
    field: str,
    domain: Mapping[str, Any],
) -> dict[str, Any]:
    record_id = candidate.get("record_id")
    source_hash = _hash_text(_candidate_source(candidate))
    option_records = domain.get("option_records")
    options = domain.get("options")
    if (
        not isinstance(record_id, str)
        or not isinstance(options, list)
        or not isinstance(option_records, list)
        or not options
        or [record.get("provider_value") for record in option_records if isinstance(record, Mapping)] != options
    ):
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
            "A provider field domain cannot be tokenized without aligned option records.",
            details={"record_id": record_id, "field": field},
        )
    tokens = [
        _provider_option_token(record_id, field, source_hash, option_record)
        for option_record in option_records
    ]
    if len(tokens) != len(set(tokens)):
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_TOKEN_COLLISION",
            "Distinct options in one field produced the same opaque token.",
            details={"record_id": record_id, "field": field},
        )
    result = deepcopy(dict(domain))
    result["selection_tokens"] = tokens
    result["token_to_option"] = {
        token: deepcopy(option_record)
        for token, option_record in zip(tokens, option_records)
    }
    result["prompt_options"] = [
        {"token": token, "value": option_record["provider_value"]}
        for token, option_record in zip(tokens, option_records)
    ]
    return result


def _reviewed_production_domain(candidate: Mapping[str, Any], field: str) -> dict[str, Any] | None:
    record_id = candidate.get("record_id")
    spec = _REVIEWED_PRODUCTION_DOMAIN_SPECS.get(record_id)
    if spec is None:
        return None
    expected_hash, fields = spec
    source_text = _candidate_source(candidate)
    if _hash_text(source_text) != expected_hash:
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
            "The reviewed field domain is not bound to the sealed candidate source text.",
            details={"record_id": record_id, "field": field},
        )
    if field not in fields:
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_MISSING",
            "The reviewed field domain does not cover this provider-authorable field.",
            details={"record_id": record_id, "field": field},
        )
    option_specs = fields[field]
    if not isinstance(option_specs, tuple) or not option_specs:
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
            "A reviewed field domain must contain one or more explicit option records.",
            details={"record_id": record_id, "field": field},
        )
    lines = source_text.splitlines()
    option_records: list[dict[str, Any]] = []
    for option_spec in option_specs:
        if not isinstance(option_spec, Mapping):
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "A reviewed field option is not a structured option record.",
                details={"record_id": record_id, "field": field},
            )
        authority = option_spec.get("authority")
        if authority == "not_applicable":
            if set(option_spec) != {"authority"}:
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "An N/A option cannot carry provider text or source evidence.",
                    details={"record_id": record_id, "field": field},
                )
            option_records.append({
                "provider_value": COMMAND4_NOT_APPLICABLE_QUOTE,
                "authority": "not_applicable",
                "evidence": None,
            })
            continue
        if authority not in {"source_quote", "bounded_interpretation"}:
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "A reviewed field option has an unsupported authority.",
                details={"record_id": record_id, "field": field},
            )
        span = option_spec.get("span")
        if span is not None:
            if (
                not isinstance(span, tuple)
                or len(span) != 2
                or any(type(value) is not int or value < 1 for value in span)
                or span[0] > span[1]
                or span[1] > len(lines)
            ):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A reviewed source option has an invalid line span.",
                    details={"record_id": record_id, "field": field},
                )
            evidence = "\n".join(lines[span[0] - 1:span[1]])
        else:
            evidence = option_spec.get("value")
            if not isinstance(evidence, str):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A reviewed source option must name an exact source span.",
                    details={"record_id": record_id, "field": field},
                )
        if not evidence.strip() or evidence not in source_text or not _is_substantive_source_quote(evidence):
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "A reviewed source option must use a substantive exact source span.",
                details={"record_id": record_id, "field": field},
            )
        provider_value = evidence if authority == "source_quote" else option_spec.get("provider_value")
        if not isinstance(provider_value, str) or not provider_value.strip():
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "A bounded reviewed option must have a nonblank normalized value.",
                details={"record_id": record_id, "field": field},
            )
        option_records.append({
            "provider_value": provider_value,
            "authority": authority,
            "evidence": evidence,
        })
    values = [record["provider_value"] for record in option_records]
    if len(values) != len(set(values)):
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
            "A reviewed field domain must contain distinct provider values.",
            details={"record_id": record_id, "field": field},
        )
    if field in {"range", "target", "effect", "duration"} and all(
        record["authority"] == "not_applicable" for record in option_records
    ):
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
            "An executable range, target, effect, or duration cannot be reviewed N/A.",
            details={"record_id": record_id, "field": field},
        )
    if field == "failure" and all(record["authority"] == "not_applicable" for record in option_records):
        roll_specs = fields.get("roll_save_check")
        if not isinstance(roll_specs, tuple) or not roll_specs or not all(
            isinstance(record, Mapping) and record.get("authority") == "not_applicable"
            for record in roll_specs
        ):
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "Failure may be N/A only when the reviewed candidate has no resolution roll.",
                details={"record_id": record_id, "field": field},
            )
    authorities = {record["authority"] for record in option_records}
    kind = (
        "server_proven_not_applicable"
        if authorities == {"not_applicable"}
        else "bounded_interpretation"
        if authorities == {"bounded_interpretation"}
        else "source_quote"
        if authorities == {"source_quote"}
        else "mixed_reviewed_options"
    )
    return _domain_record(tuple(option_records), kind=kind)


def _command4_fixed_cat3_rows(
    *,
    catalog_service: Any | None = None,
) -> tuple[Mapping[str, Any], Path | None]:
    """Load the installed CAT3 base-authority rows through their fixed lock.

    Command 4 candidate rows are a sealed projection, not an authority for
    whether an automatic base component is executable.  That decision is
    available only from the authenticated CAT3 registry and its packaged
    source archive.  Keep this reader deliberately narrow: a malformed or
    unavailable fixed registry is an authoring blocker, never a reason to
    fall through to provider prose.
    """

    fixed_root = Path(__file__).resolve().parents[1]
    authority_path = fixed_root / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json"
    factory_zip = fixed_root / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
    using_default_service = catalog_service is None
    if catalog_service is None:
        for path in (authority_path, factory_zip):
            try:
                safe_file = path.is_file() and not path.is_symlink()
            except OSError as exc:
                raise FoundryError(
                    "COMMAND4_CAT3_AUTHORITY_INVALID",
                    "The fixed CAT3 authority path cannot be inspected.",
                ) from exc
            if not safe_file:
                raise FoundryError(
                    "COMMAND4_CAT3_AUTHORITY_INVALID",
                    "The fixed CAT3 authority and source archive must be regular non-symlink files.",
                )
        catalog_service = CanonicalCatalogAuthorityService(fixed_root)
    loader = getattr(catalog_service, "_load", None)
    if not callable(loader):
        raise FoundryError(
            "COMMAND4_CAT3_AUTHORITY_INVALID",
            "The fixed CAT3 authority reader is unavailable.",
        )
    try:
        authority = loader()
    except FoundryError as exc:
        raise FoundryError(
            "COMMAND4_CAT3_AUTHORITY_INVALID",
            "The authenticated CAT3 base authority could not be loaded.",
            details={"cause": getattr(exc, "code", type(exc).__name__)},
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise FoundryError(
            "COMMAND4_CAT3_AUTHORITY_INVALID",
            "The authenticated CAT3 base authority could not be loaded.",
            details={"cause": type(exc).__name__},
        ) from exc
    if not isinstance(authority, Mapping):
        raise FoundryError("COMMAND4_CAT3_AUTHORITY_INVALID", "The authenticated CAT3 authority is not an object.")
    rows = authority.get("base_package_source_rows_by_component")
    if not isinstance(rows, Mapping) or not rows:
        raise FoundryError(
            "COMMAND4_CAT3_AUTHORITY_INVALID",
            "The authenticated CAT3 authority has no base-component rows.",
        )
    normalized: dict[str, Mapping[str, Any]] = {}
    for key, entries in rows.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(entries, list) or len(entries) != 1:
            raise FoundryError(
                "COMMAND4_CAT3_AUTHORITY_INVALID",
                "Each CAT3 base-component identity must resolve to exactly one row.",
            )
        row = entries[0]
        if not isinstance(row, Mapping):
            raise FoundryError(
                "COMMAND4_CAT3_AUTHORITY_INVALID",
                "A CAT3 base-component authority row is not an object.",
            )
        row_ids = {row.get("base_ability_id"), row.get("candidate_record_id"), row.get("source_row_id")}
        if key not in row_ids:
            raise FoundryError(
                "COMMAND4_CAT3_AUTHORITY_INVALID",
                "A CAT3 base-component row does not bind its map identity.",
            )
        normalized[key] = row
    return normalized, (factory_zip if using_default_service else getattr(catalog_service, "factory_zip", None))


def _command4_packaged_source_hash(factory_zip: Path | None, relative_path: str) -> str:
    """Return one exact fixed-package member hash for a CAT3 source path."""

    if factory_zip is None:
        raise FoundryError(
            "COMMAND4_CAT3_AUTHORITY_INVALID",
            "The CAT3 source archive binding is unavailable.",
        )
    try:
        archive_path = Path(factory_zip)
        if archive_path.is_symlink() or not archive_path.is_file():
            raise FoundryError(
                "COMMAND4_CAT3_AUTHORITY_INVALID",
                "The CAT3 source archive must be a regular non-symlink file.",
            )
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise FoundryError(
                "COMMAND4_CAT3_AUTHORITY_INVALID",
                "A CAT3 source reference must be a safe relative path.",
            )
        suffix = relative.as_posix()
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                info for info in archive.infolist()
                if not info.is_dir()
                and (
                    info.filename.replace("\\", "/") == suffix
                    or info.filename.replace("\\", "/").endswith("/" + suffix)
                )
            ]
            if len(matches) != 1:
                raise FoundryError(
                    "COMMAND4_CAT3_AUTHORITY_INVALID",
                    "A CAT3 source reference must resolve to one packaged source member.",
                )
            info = matches[0]
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise FoundryError(
                    "COMMAND4_CAT3_AUTHORITY_INVALID",
                    "A CAT3 source member may not be a symlink.",
                )
            return hashlib.sha256(archive.read(info)).hexdigest()
    except FoundryError:
        raise
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FoundryError(
            "COMMAND4_CAT3_AUTHORITY_INVALID",
            "The CAT3 source archive cannot authenticate a source member.",
        ) from exc


def _command4_complete_executable_projection(candidate: Mapping[str, Any]) -> bool:
    """Whether server-owned mechanics are already complete for this row."""

    missing = candidate.get("missing_fields")
    if not isinstance(missing, (list, tuple, set, frozenset)):
        raise FoundryError(
            "COMMAND4_CANDIDATE_CAT3_AUTHORITY_INVALID",
            "A CAT3-bound candidate has no valid missing-field projection.",
            details={"record_id": candidate.get("record_id")},
        )
    execution_missing = {
        value for value in missing
        if isinstance(value, str)
        and value not in _DERIVED_FIELDS
        and value not in _SERVER_CLASSIFICATION_FIELDS
        and value != _LOCKED_SOURCE_FIELD
    }
    if not execution_missing:
        return True
    record_id = candidate.get("record_id")
    reviewed_spec = _REVIEWED_PRODUCTION_DOMAIN_SPECS.get(record_id)
    if reviewed_spec is None:
        return False
    expected_hash, fields = reviewed_spec
    if not _is_hash(expected_hash) or not isinstance(fields, Mapping):
        raise FoundryError(
            "COMMAND4_CANDIDATE_CAT3_AUTHORITY_INVALID",
            "A reviewed executable domain is malformed.",
            details={"record_id": record_id},
        )
    actual_hash = _hash_text(_candidate_source(candidate))
    if actual_hash != expected_hash:
        raise FoundryError(
            "COMMAND4_CANDIDATE_CAT3_BINDING_INVALID",
            "A reviewed executable domain does not bind the CAT3 candidate source.",
            details={"record_id": record_id},
        )
    return execution_missing.issubset(set(fields))


def _command4_non_executable_base_record_ids(
    candidates: list[Mapping[str, Any]],
    *,
    catalog_service: Any | None = None,
) -> frozenset[str]:
    """Return only CAT3-proven non-selectable, non-executable base IDs.

    No record is identified by a name or prefix.  A matching candidate must
    bind the authenticated CAT3 row, the exact packaged source bytes, and its
    source text before its explicit classification may affect the provider
    domain.  Rows with a complete CAT3 projection or a complete reviewed
    executable domain remain in the Command 4 set.
    """

    rows, factory_zip = _command4_fixed_cat3_rows(catalog_service=catalog_service)
    source_hashes: dict[str, str] = {}
    excluded: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise FoundryError(
                "COMMAND4_CANDIDATE_CAT3_AUTHORITY_INVALID",
                "The candidate set contains a non-object row.",
            )
        record_id = candidate.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise FoundryError(
                "COMMAND4_CANDIDATE_CAT3_AUTHORITY_INVALID",
                "A CAT3 candidate identity must be nonblank.",
            )
        row = rows.get(record_id)
        if row is None:
            continue
        source = candidate.get("source")
        reviewed_source_bound = _reviewed_production_source_binding(record_id, _candidate_source(candidate))
        if source is None and reviewed_source_bound:
            # Reviewed production domains are independently committed to the
            # exact candidate source text.  Synthetic/legacy projections may
            # omit the CAT3 path mapping, but they still must prove that
            # commitment before the reviewed fields can keep the row in the
            # authoring set.  Unreviewed rows retain the strict CAT3 binding
            # requirement below.
            if _command4_complete_executable_projection(candidate):
                continue
        row_refs = row.get("source_refs")
        row_source_text = row.get("full_exact_source_text")
        row_name = row.get("display_name")
        if (
            not isinstance(source, Mapping)
            or set(source) != _LOCKED_SOURCE_KEYS
            or not isinstance(source.get("path"), str)
            or not isinstance(source.get("sha256"), str)
            or not _is_hash(source.get("sha256"))
            or not isinstance(row_refs, list)
            or not row_refs
            or any(not isinstance(reference, str) or not reference.strip() for reference in row_refs)
            or not isinstance(row_source_text, str)
            or not isinstance(row_name, str)
            or candidate.get("name") != row_name
            or _candidate_source(candidate) != row_source_text
        ):
            raise FoundryError(
                "COMMAND4_CANDIDATE_CAT3_BINDING_INVALID",
                "A CAT3 candidate must bind one exact source row and description.",
                details={"record_id": record_id},
            )
        source_path = source["path"]
        matching_refs = [
            reference for reference in row_refs
            if reference.partition(" :: ")[0] == source_path
            and reference.partition(" :: ")[2].strip()
        ]
        if (
            len(matching_refs) != 1
            or Path(source_path).is_absolute()
            or ".." in Path(source_path).parts
        ):
            raise FoundryError(
                "COMMAND4_CANDIDATE_CAT3_BINDING_INVALID",
                "A CAT3 candidate source path does not match its authenticated source reference.",
                details={"record_id": record_id},
            )
        if source_path not in source_hashes:
            source_hashes[source_path] = _command4_packaged_source_hash(factory_zip, source_path)
        if source["sha256"] != source_hashes[source_path]:
            raise FoundryError(
                "COMMAND4_CANDIDATE_CAT3_BINDING_INVALID",
                "A CAT3 candidate source hash does not match the fixed source archive.",
                details={"record_id": record_id},
            )
        if type(row.get("confirmed_selectable_talent")) is not bool or type(row.get("owner_selectable_output")) is not bool:
            raise FoundryError(
                "COMMAND4_CANDIDATE_CAT3_AUTHORITY_INVALID",
                "A CAT3 base row lacks explicit selectable-output booleans.",
                details={"record_id": record_id},
            )
        matrix = row.get("source_matrix")
        if (
            not isinstance(matrix, Mapping)
            or not isinstance(matrix.get("classification"), str)
            or not matrix.get("classification").strip()
            or matrix.get("current_projection_state") not in {"EMPTY", "PRESENT_INCOMPLETE", "PRESENT_COMPLETE"}
            or type(matrix.get("current_projection_component_count")) is not int
            or matrix.get("current_projection_component_count") < 0
        ):
            raise FoundryError(
                "COMMAND4_CAT3_AUTHORITY_INVALID",
                "A CAT3 base row lacks a valid projection-state authority.",
                details={"record_id": record_id},
            )
        if row.get("confirmed_selectable_talent") is not False or row.get("owner_selectable_output") is not False:
            continue
        if matrix.get("current_projection_state") == "PRESENT_COMPLETE":
            continue
        if _command4_complete_executable_projection(candidate):
            continue
        excluded.add(record_id)
    return frozenset(excluded)


def _provider_field_domain(
    candidate: Mapping[str, Any],
    field: str,
    parsed_fields: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a sealed, nonempty admissible domain for one provider field.

    Production candidate IDs use the reviewed identity table above.  Synthetic
    fixtures may opt into an explicit cue or explicit reviewed N/A marker;
    ordinary prose and absence are never authority.
    """

    reviewed = _reviewed_production_domain(candidate, field)
    if reviewed is not None:
        return _domain_with_selection_tokens(candidate, field, reviewed)
    source_text = _candidate_source(candidate)
    parsed = parsed_fields if isinstance(parsed_fields, Mapping) else _parse_explicit_fields(source_text)
    parsed_value = parsed.get(field) if isinstance(parsed, Mapping) else None
    if isinstance(parsed_value, str) and parsed_value.strip():
        return _domain_with_selection_tokens(
            candidate,
            field,
            _domain_record((parsed_value,), kind="deterministic_label"),
        )
    explicit = _explicit_source_domain(source_text, field)
    if explicit:
        return _domain_with_selection_tokens(
            candidate,
            field,
            _domain_record(explicit, kind="source_quote"),
        )
    if field in _explicit_source_na_fields(source_text):
        if field in {"range", "target", "effect", "duration"}:
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "An executable range, target, effect, or duration cannot be reviewed N/A.",
                details={"record_id": candidate.get("record_id"), "field": field},
            )
        if field == "failure" and _projection_is_resolved(_candidate_value(candidate, "roll_save_check")):
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                "Failure may be N/A only when the candidate has no resolution roll.",
                details={"record_id": candidate.get("record_id"), "field": field},
            )
        return _domain_with_selection_tokens(
            candidate,
            field,
            _domain_record((), kind="server_proven_not_applicable"),
        )
    raise _response_error(
        "COMMAND4_PROVIDER_FIELD_DOMAIN_MISSING",
        "No sealed field-specific source domain or reviewed N/A disposition exists.",
        details={"record_id": candidate.get("record_id"), "field": field},
    )


def _field_relevant_source_spans(source_text: str, field: str) -> tuple[str, ...]:
    """Return explicit fixture spans; production authority is identity-bound."""

    return _explicit_source_domain(source_text, field)


def _provider_field_default_quote(candidate: Mapping[str, Any], field: str) -> str:
    domain = _provider_field_domain(candidate, field)
    tokens = domain.get("selection_tokens")
    if not isinstance(tokens, list) or not tokens or not isinstance(tokens[0], str):
        raise _response_error(
            "COMMAND4_PROVIDER_FIELD_DEFAULT_INVALID",
            "A deterministic test response requires a nonempty tokenized field option list.",
            details={"record_id": candidate.get("record_id"), "field": field},
        )
    return tokens[0]


def _provider_field_domain_partition(candidates: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "source_quote_provider_field_count": 0,
        "not_applicable_provider_field_count": 0,
        "bounded_interpretation_provider_field_count": 0,
    }
    for candidate in candidates:
        for field in _provider_authorable_fields(candidate):
            domain = _provider_field_domain(candidate, field)
            authorities = domain.get("allowed_authorities")
            if authorities == ["source_quote"]:
                counts["source_quote_provider_field_count"] += 1
            elif authorities == ["not_applicable"]:
                counts["not_applicable_provider_field_count"] += 1
            elif authorities == ["bounded_interpretation"]:
                counts["bounded_interpretation_provider_field_count"] += 1
            else:
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A provider field domain has an unsupported authority partition.",
                    details={"record_id": candidate.get("record_id"), "field": field},
                )
    return counts


def _provider_field_partition(candidates: list[Mapping[str, Any]]) -> dict[str, int]:
    """Count provider fields by whether the sealed source labels them.

    The partition is derived only from the sealed candidate order and source
    text.  It intentionally does not expose field IDs or source text in
    receipts; the counts make the authoring boundary auditable without
    widening the provider contract.
    """

    total = 0
    deterministic = 0
    for candidate in candidates:
        parsed_fields = _parse_explicit_fields(_candidate_source(candidate))
        for field in _provider_authorable_fields(candidate):
            total += 1
            parsed_value = parsed_fields.get(field) if isinstance(parsed_fields, Mapping) else None
            if isinstance(parsed_value, str) and parsed_value.strip():
                deterministic += 1
    unlabeled = total - deterministic
    partition = {
        "total_provider_field_count": total,
        "deterministic_label_bound_field_count": deterministic,
        "unlabeled_provider_field_count": unlabeled,
    }
    if total != deterministic + unlabeled:
        raise FoundryError(
            "COMMAND4_PROVIDER_FIELD_PARTITION_INVALID",
            "The provider-field partition must account for every authorable field exactly once.",
            details=partition,
        )
    return partition


def build_command4_response_schema(prepared: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact per-workspace schema sent to the local provider.

    Only the conservative JSON-schema vocabulary accepted by the local runtime
    is used here.  The flat quote array is ordered by the sealed concatenation
    of candidate provider fields; the domain validator reconstructs all record
    and field identity server-side.
    """

    candidates = prepared.get("candidates")
    candidate_ids = prepared.get("candidate_ids")
    source_hashes = prepared.get("source_text_sha256_by_record_id")
    fields_by_id = prepared.get("provider_authorable_fields_by_record_id")
    domains_by_id = prepared.get("provider_field_domains_by_record_id")
    request_sha256 = prepared.get("request_sha256")
    source_workspace_sha256 = prepared.get("source_workspace_sha256")
    if (
        not isinstance(candidates, list)
        or not isinstance(candidate_ids, list)
        or len(candidates) != len(candidate_ids)
        or not isinstance(source_hashes, Mapping)
        or not isinstance(fields_by_id, Mapping)
        or not isinstance(domains_by_id, Mapping)
        or not _is_hash(request_sha256)
        or not _is_hash(source_workspace_sha256)
    ):
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
            "The prepared Command 4 authority is incomplete for dynamic response-schema construction.",
        )
    if any(not isinstance(record_id, str) or not record_id.strip() for record_id in candidate_ids):
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
            "The prepared candidate IDs must be unique nonblank strings.",
        )
    if len(candidate_ids) != len(set(candidate_ids)):
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
            "The prepared candidate IDs must be unique nonblank strings.",
        )
    if (
        set(source_hashes) != set(candidate_ids)
        or set(fields_by_id) != set(candidate_ids)
        or set(domains_by_id) != set(candidate_ids)
    ):
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
            "The prepared response-schema projections must cover exactly the sealed candidate IDs.",
        )

    total_provider_field_count = 0
    selection_tokens: list[str] = []
    quote_prefix_items: list[dict[str, Any]] = []
    for candidate, record_id in zip(candidates, candidate_ids):
        if not isinstance(candidate, Mapping) or candidate.get("record_id") != record_id:
            raise FoundryError(
                "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
                "The prepared response-schema candidate order is not sealed.",
            )
        source_text = _candidate_source(candidate)
        source_hash = source_hashes.get(record_id)
        if source_hash != _hash_text(source_text):
            raise FoundryError(
                "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
                "The prepared response-schema source hash is stale.",
            )
        expected_fields = list(_provider_authorable_fields(candidate))
        if fields_by_id.get(record_id) != expected_fields:
            raise FoundryError(
                "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
                "The prepared response-schema field projection is stale.",
            )
        domains = domains_by_id.get(record_id)
        if not isinstance(domains, Mapping) or set(domains) != set(expected_fields):
            raise FoundryError(
                "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
                "The prepared response-schema token domains are stale.",
                details={"record_id": record_id},
            )
        for field in expected_fields:
            domain = domains.get(field)
            tokens = domain.get("selection_tokens") if isinstance(domain, Mapping) else None
            if (
                not isinstance(tokens, list)
                or not tokens
                or any(not isinstance(token, str) or not _OPTION_TOKEN_RE.fullmatch(token) for token in tokens)
            ):
                raise FoundryError(
                    "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
                    "The prepared response-schema token domain is invalid.",
                    details={"record_id": record_id, "field": field},
                )
            selection_tokens.extend(tokens)
            quote_prefix_items.append({
                "type": "string",
                "minLength": 1,
                "enum": list(tokens),
            })
        total_provider_field_count += len(expected_fields)
    eligible_loadout_ids, loadout_min_items, loadout_max_items = _signature_loadout_projection(
        candidates,
        error_code="COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
    )
    if (
        "signature_loadout_eligible_record_ids" in prepared
        and prepared.get("signature_loadout_eligible_record_ids") != eligible_loadout_ids
    ) or (
        "signature_loadout_min_items" in prepared
        and prepared.get("signature_loadout_min_items") != loadout_min_items
    ) or (
        "signature_loadout_max_items" in prepared
        and prepared.get("signature_loadout_max_items") != loadout_max_items
    ):
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
            "The prepared signature-loadout domain is stale.",
            details={
                "eligible_action_count": len(eligible_loadout_ids),
                "min_items": loadout_min_items,
                "max_items": loadout_max_items,
            },
        )
    if len(selection_tokens) != len(set(selection_tokens)):
        raise FoundryError(
            "COMMAND4_PROVIDER_FIELD_TOKEN_COLLISION",
            "Opaque selection tokens must be globally unique across the sealed ledger.",
        )

    quotes_schema: dict[str, Any] = {
        "type": "array",
        "minItems": total_provider_field_count,
        "maxItems": total_provider_field_count,
    }
    if quote_prefix_items:
        # llama.cpp b10672's schema-to-grammar converter prefers ``items``
        # whenever both keywords are present.  The exact maxItems bound makes
        # prefixItems complete, so omit items for the nonempty tuple form.
        quotes_schema["prefixItems"] = quote_prefix_items
    # With no provider fields the exact minItems/maxItems of 0 already admit
    # only the empty array; ``items: false`` is equivalent but llama.cpp's
    # converter rejects it ("Unrecognized schema: false", build 25).
    if total_provider_field_count == 0:
        # Without ``items`` llama.cpp's converter emits a grammar for any
        # array and ignores maxItems 0: build 32's model wrote 16384 tokens of
        # quotes.  A constant empty array is the same domain and is enforced.
        quotes_schema = {"const": []}
    if prepared.get("fixed_quote_constants") is not None:
        fixed = prepared["fixed_quote_constants"]
        if any(len(item["enum"]) != 1 for item in quote_prefix_items) or fixed != [item["enum"][0] for item in quote_prefix_items]:
            raise FoundryError("COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID", "Fixed quotes must equal every sealed singleton field in order.")
        # An enum containing one entire array has exactly the same domain as
        # the complete tuple of singleton enums, with no repeated tuple keys.
        quotes_schema = {"enum": [list(fixed)]}

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "request_sha256",
            "source_workspace_sha256",
            "quotes",
            "signature_loadout_record_ids",
        ],
        "properties": {
            "schema": {"enum": [COMMAND4_PROVIDER_RESPONSE_SCHEMA]},
            "request_sha256": {"enum": [request_sha256]},
            "source_workspace_sha256": {"enum": [source_workspace_sha256]},
            "quotes": quotes_schema,
            "signature_loadout_record_ids": (
                # Fewer than 10 eligible actions: the validator requires every
                # one exactly once, so the answer is fixed.  A constant is
                # enforceable by llama.cpp; uniqueItems is not (a model repeated
                # an ID, build 26).
                {"const": list(eligible_loadout_ids)}
                if len(eligible_loadout_ids) < 10 and loadout_min_items == len(eligible_loadout_ids)
                else {
                    "type": "array",
                    "minItems": loadout_min_items,
                    "maxItems": loadout_max_items,
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": eligible_loadout_ids},
                }
            ),
        },
    }
    try:
        schema_bytes = _json_bytes(schema)
        Draft202012Validator.check_schema(schema)
    except (TypeError, ValueError, SchemaError) as exc:
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
            "The dynamic Command 4 response schema is invalid.",
        ) from exc
    if len(schema_bytes) > MAX_LOCAL_RESPONSE_SCHEMA_BYTES:
        raise FoundryError(
            "COMMAND4_RESPONSE_SCHEMA_TOO_LARGE",
            "The dynamic Command 4 response schema exceeded its bounded schema limit.",
            details={"schema_bytes": len(schema_bytes), "max_schema_bytes": MAX_LOCAL_RESPONSE_SCHEMA_BYTES},
            status_code=413,
        )
    return schema


def _validate_recipe_prepared_shape(candidate: Mapping[str, Any]) -> str | None:
    """Use the producer-owned, exact multi-Cost prepared-item grammar."""

    return _validate_prepared_recipe_shape(
        _candidate_source(candidate),
        expected_action_type=_candidate_action_type(candidate),
    )


def _strict_resource_projection(candidate: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Project resources from the exact shared source grammar only."""

    source = _candidate_source(candidate)
    shape_error = _validate_recipe_prepared_shape(candidate)
    if shape_error is not None:
        return None, shape_error
    projection, error = _resource_projection_from_description(
        source,
        record_id=candidate.get("record_id"),
        display_name=candidate.get("name"),
        expected_action_type=_candidate_action_type(candidate),
    )
    if projection is None:
        return None, error
    return {
        "resource_costs": deepcopy(projection["resource_costs"]),
        "resource_gains": deepcopy(projection["resource_gains"]),
        "resource_requirements": deepcopy(projection["resource_requirements"]),
        "resource_cost_options": deepcopy(projection.get("resource_cost_options") or []),
    }, None


_UNAUTHORABLE_DOMAIN_CODES = frozenset({
    "COMMAND4_PROVIDER_FIELD_DOMAIN_MISSING",
    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
})


def _command4_unauthorable_record_ids(candidates: list[Mapping[str, Any]]) -> frozenset[str]:
    """Return unresolved rows the provider can never complete from sealed authority.

    Two sealed facts decide it, both server-owned and independent of any
    provider text:

    * the resource projection: the grammar deliberately leaves variable
      ("1 or more"), unparseable alternative, conditional, compound,
      unknown-resource and unlabelled costs untyped instead of inventing a
      resource identity (a parseable choice such as "2 CP or 2 Stamina" is
      typed with a default and options instead), and 62 compendium actions
      carry no Cost line at all;
    * the provider field domains: a missing field such as ``range`` on a
      self-targeted bonus action has no sealed source span and no reviewed
      N/A disposition, so no admissible answer exists for the provider.

    Such a row stays display-only and outside the provider domain instead of
    blocking the authoring of every other candidate for the whole character.
    Rows the sealed compile already promoted (no missing fields) and reviewed
    override records are never omitted here; they keep the strict validation.
    """

    excluded: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        record_id = candidate.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            continue
        if not candidate.get("missing_fields"):
            continue
        if record_id in _REVIEWED_FORCED_PROVIDER_FIELDS or record_id in _REVIEWED_PRODUCTION_DOMAIN_SPECS:
            continue
        _, error = _strict_resource_projection(candidate)
        if error is not None:
            excluded.add(record_id)
            continue
        parsed_fields = _parse_explicit_fields(_candidate_source(candidate))
        for field in _provider_authorable_fields(candidate):
            try:
                _provider_field_domain(candidate, field, parsed_fields)
            except FoundryError as exc:
                if exc.code in _UNAUTHORABLE_DOMAIN_CODES:
                    excluded.add(record_id)
                    break
                raise
    return frozenset(excluded)


# Backwards-compatible name for the first (cost-only) form of the exclusion.
_command4_unprojectable_cost_record_ids = _command4_unauthorable_record_ids


def _prompt_candidate(
    candidate: Mapping[str, Any],
    *,
    locked_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = _candidate_source(candidate)
    action_type = _candidate_action_type(candidate)
    runtime_kind = _candidate_runtime_kind(candidate)
    if _LOCKED_SOURCE_FIELD in (candidate.get("missing_fields") or []) and locked_source is None:
        raise _response_error(
            "COMMAND4_LOCKED_SOURCE_INVALID",
            "A locked source candidate must use an independently resolved sealed source proof.",
            details={"record_id": candidate.get("record_id")},
        )
    locked_classification = {
        "runtime_kind": runtime_kind,
        "action_type": action_type,
        "bucket": _candidate_value(candidate, "bucket"),
    }
    if locked_source is not None:
        locked_classification["locked_source"] = locked_source
    return {
        "record_id": candidate.get("record_id"),
        "source_text": source,
        "source_text_sha256": _hash_text(source),
        "locked_classification": locked_classification,
        "provider_authorable_fields": list(_provider_authorable_fields(candidate)),
    }


def _safe_prompt_candidate(
    candidate: Mapping[str, Any],
    *,
    locked_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = _prompt_candidate(candidate, locked_source=locked_source)
    if not isinstance(row.get("record_id"), str) or not row["record_id"].strip() or not row["source_text"]:
        raise FoundryError("COMMAND4_CANDIDATE_INVALID", "Every Command 4 candidate needs a nonblank record ID and source text.")
    missing = candidate.get("missing_fields")
    if missing is not None and (
        not isinstance(missing, list)
        or any(not isinstance(value, str) or not value.strip() for value in missing)
    ):
        raise FoundryError("COMMAND4_CANDIDATE_INVALID", "Candidate missing fields must be a list of nonblank field names.")
    if _candidate_action_type(candidate) is None:
        raise FoundryError("COMMAND4_CANDIDATE_ACTION_TYPE_INVALID", "Every Command 4 candidate needs a deterministic action type or procedure label.")
    return row


def _compact_fixed_quote_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep complete sources while avoiding redundant fixed-field values."""
    if len(_json_bytes(payload)) <= COMMAND4_MAX_REQUEST_BYTES // 2:
        return payload
    quotes: list[str] = []
    for row in payload["candidates"]:
        for field in row["provider_authorable_fields"]:
            options = row["provider_field_options"][field]
            if len(options) != 1:
                return payload
            quotes.append(options[0]["token"])
    return {
        "schema": "TianxiaFoundry.Command4ProviderAuthoringPrompt.v2",
        "project_id": payload["project_id"],
        "source_workspace_sha256": payload["source_workspace_sha256"],
        "candidate_source_sha256": payload["candidate_source_sha256"],
        "contract": {
            "response_top_level_keys": payload["contract"]["response_top_level_keys"],
            "quote_count": len(quotes),
            "signature_loadout": payload["contract"]["signature_loadout"],
            "signature_loadout_bounds": payload["contract"]["signature_loadout_bounds"],
            "rules": [
                "Copy response_constants.schema, request_sha256, and source_workspace_sha256 exactly.",
                "Copy quote_constants exactly into quotes. Every field has one sealed source-bound value; there is no field choice to make.",
                "Choose signature_loadout_record_ids using the full source_records table and the signature_loadout bounds. Preserve action/procedure classification.",
                "All source proofs, classifications, field mappings, and resource packets remain server-owned and are revalidated. Do not return or alter them.",
            ],
        },
        "quote_constants": quotes,
        "source_records": {
            "columns": ["record_id", "runtime_kind", "action_type", "source_text"],
            "rows": [[row["record_id"], row["locked_classification"]["runtime_kind"],
                      row["locked_classification"]["action_type"], row["source_text"]]
                     for row in payload["candidates"]],
        },
    }


def _validate_candidate_server_prerequisites(
    candidate: Mapping[str, Any],
    *,
    locked_source: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed before authoring when sealed execution prerequisites are incomplete."""

    record_id = candidate.get("record_id")
    action_id = _candidate_value(candidate, "action_id")
    if not isinstance(action_id, str) or not action_id.strip():
        raise FoundryError(
            "COMMAND4_CANDIDATE_DERIVED_INVALID",
            "Every Command 4 candidate needs a deterministic action ID.",
            details={"record_id": record_id, "field": "action_id"},
        )
    if candidate.get("action_id") != action_id:
        raise FoundryError(
            "COMMAND4_CANDIDATE_DERIVED_INVALID",
            "The candidate action ID does not match its deterministic record identity.",
            details={"record_id": record_id, "field": "action_id"},
        )
    packet_ids = candidate.get("source_packet_ids")
    if (
        not isinstance(packet_ids, list)
        or not packet_ids
        or any(not isinstance(value, str) or not value.strip() for value in packet_ids)
        or len(packet_ids) != len(set(packet_ids))
    ):
        raise FoundryError(
            "COMMAND4_CANDIDATE_DERIVED_INVALID",
            "Every Command 4 candidate needs nonblank unique source packet IDs.",
            details={"record_id": record_id, "field": "source_packet_ids"},
        )
    action_type = _candidate_action_type(candidate)
    if not isinstance(action_type, str) or not action_type.strip():
        raise FoundryError(
            "COMMAND4_CANDIDATE_CLASSIFICATION_INVALID",
            "Every Command 4 candidate needs a locked runtime classification.",
            details={"record_id": record_id},
        )
    resources, resource_error = _strict_resource_projection(candidate)
    if resources is None or resource_error is not None:
        raise FoundryError(
            "COMMAND4_RESOURCE_PROJECTION_INVALID",
            "Resource transactions require one exact standalone Cost line.",
            details={"record_id": record_id, "reason": resource_error},
        )
    _locked_source_mapping(candidate)
    if _LOCKED_SOURCE_FIELD in (candidate.get("missing_fields") or []) and locked_source is None:
        raise FoundryError(
            "COMMAND4_LOCKED_SOURCE_INVALID",
            "A locked source candidate must have an independently resolved sealed source proof.",
            details={"record_id": record_id},
        )

    missing = candidate.get("missing_fields")
    missing_fields = set(missing or [])
    known_execution = set(COMMAND4_EXECUTION_FIELDS)
    unsupported = missing_fields - known_execution - _SERVER_RESOLVED_MISSING_FIELDS
    if unsupported:
        raise FoundryError(
            "COMMAND4_CANDIDATE_SOURCE_AUTHORITY_MISSING",
            "A candidate with missing sealed source authority cannot be promoted by provider text.",
            details={"record_id": record_id, "missing_fields": sorted(unsupported)},
        )
    provider_authorable = set(_provider_authorable_fields(candidate))
    invalid_scalar_fields = {
        field
        for field in _PROVIDER_AUTHORABLE_FIELDS
        if _candidate_value(candidate, field) is not None and not isinstance(_candidate_value(candidate, field), str)
    }
    if invalid_scalar_fields:
        raise FoundryError(
            "COMMAND4_CANDIDATE_FIELDS_INVALID",
            "Provider-authorable candidate projections must be scalar text or absent.",
            details={"record_id": record_id, "fields": sorted(invalid_scalar_fields)},
        )
    unresolved = {
        field
        for field in _PROVIDER_AUTHORABLE_FIELDS
        if not _projection_is_resolved(_candidate_value(candidate, field))
    }
    if unresolved - provider_authorable:
        raise FoundryError(
            "COMMAND4_CANDIDATE_FIELDS_UNMARKED",
            "A null provider-authorable candidate field must be explicitly marked for source authoring.",
            details={"record_id": record_id, "fields": sorted(unresolved - provider_authorable)},
        )
    for field in _SERVER_CLASSIFICATION_FIELDS:
        value = _candidate_value(candidate, field)
        if not isinstance(value, str) or not value.strip():
            raise FoundryError(
                "COMMAND4_CANDIDATE_CLASSIFICATION_INVALID",
                "Locked classification fields must be server-resolved before provider authoring.",
                details={"record_id": record_id, "field": field},
            )


def _response_error(code: str, message: str, *, details: Any = None) -> FoundryError:
    return FoundryError(code, message, details=details)


def _raw_json_object(raw_response: str) -> bool:
    try:
        return isinstance(json.loads(raw_response), Mapping)
    except (TypeError, ValueError):
        return False


def _resolve_constructed_immortal_source_proof(
    db: Database,
    project_id: str,
    candidate: Mapping[str, Any],
    packets: Mapping[str, Mapping[str, Any]] | list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Re-derive one Immortal Art binding and its exact creation packet proof.

    The same proof is needed when the Factory workspace is first assembled and
    when a detached Command 4 workspace is later consumed.  Keep the
    validation here so neither caller can promote a copied binding dictionary
    without rechecking the project-locked record and acquisition evidence.
    """

    record_id = candidate.get("record_id")
    packet_ids = candidate.get("source_packet_ids")
    if (
        not isinstance(packet_ids, list)
        or not packet_ids
        or any(not isinstance(packet_id, str) or not packet_id.strip() for packet_id in packet_ids)
        or len(packet_ids) != len(set(packet_ids))
    ):
        raise FoundryError(
            "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH",
            "The Immortal Art must retain one or more unique creation packets.",
            details={"record_id": record_id},
        )

    packet_by_id: dict[str, Mapping[str, Any]] = {}
    if isinstance(packets, Mapping):
        packet_by_id = {
            str(packet_id): packet
            for packet_id, packet in packets.items()
            if isinstance(packet_id, str) and isinstance(packet, Mapping)
        }
    elif isinstance(packets, list):
        for packet in packets:
            if not isinstance(packet, Mapping):
                continue
            packet_id = packet.get("packet_id")
            if not isinstance(packet_id, str) or not packet_id.strip():
                continue
            if packet_id in packet_by_id:
                raise FoundryError(
                    "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH",
                    "The Immortal Art creation packet registry contains a duplicate packet ID.",
                    details={"record_id": record_id, "packet_id": packet_id},
                )
            packet_by_id[packet_id] = packet
    else:
        raise FoundryError(
            "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH",
            "The Immortal Art creation packet registry is unavailable.",
            details={"record_id": record_id},
        )

    # Keep the structural check adjacent to the authoritative validator.  A
    # plausible path/hash on a card is never enough to enter this proof path.
    _locked_source_mapping(candidate)
    constructed = validate_immortal_action_candidate(db, project_id, candidate)
    if not isinstance(constructed, Mapping):
        raise FoundryError(
            "COMMAND4_IMMORTAL_SOURCE_INVALID",
            "The Immortal Art lacks a rederived project-locked source binding.",
            details={"record_id": record_id},
        )
    source = constructed.get("source")
    if not isinstance(source, Mapping):
        raise FoundryError(
            "COMMAND4_IMMORTAL_SOURCE_INVALID",
            "The rederived Immortal Art source binding is malformed.",
            details={"record_id": record_id},
        )
    for packet_id in packet_ids:
        packet = packet_by_id.get(packet_id)
        if (
            not isinstance(packet, Mapping)
            or packet.get("record_id") != record_id
            or packet.get("record_hash") != candidate.get("record_hash")
            or packet.get("advancement_kind") != "immortal_art_creation"
        ):
            raise FoundryError(
                "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH",
                "The Immortal Art must retain its exact creation packet and record commitment.",
                details={"record_id": record_id, "packet_id": packet_id},
            )
        evidence = packet.get("source_evidence")
        if (
            not isinstance(evidence, list)
            or len(evidence) != 1
            or not isinstance(evidence[0], Mapping)
            or any(
                evidence[0].get(key) != source[field]
                for key, field in (
                    ("source_path", "path"),
                    ("source_hash", "sha256"),
                    ("source_anchor", "anchor"),
                )
            )
        ):
            raise FoundryError(
                "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH",
                "The creation packet must retain the Art's exact published-source identity.",
                details={"record_id": record_id, "packet_id": packet_id},
            )
    return {
        **deepcopy(dict(source)),
        "project_id": project_id,
        "source_packet_ids": list(packet_ids),
        "constructed_immortal_source_binding": deepcopy(dict(constructed)),
        "acquisition_packet_sha256": {
            packet_id: sha256_json(packet_by_id[packet_id])
            for packet_id in packet_ids
        },
    }


class Command4ProviderAuthoring:
    """Prepare and explicitly validate one bounded Command 4 authoring call."""

    max_request_bytes = COMMAND4_MAX_REQUEST_BYTES
    response_schema = COMMAND4_PROVIDER_RESPONSE_SCHEMA
    system_message = COMMAND4_SYSTEM_MESSAGE

    def __init__(
        self,
        db: Database | None = None,
        *,
        workspace_service: FactoryAuthoringWorkspaceService | Any | None = None,
        workspace_root: Path | None = None,
        source_root: Path | None = None,
        authority_db: Database | None = None,
    ) -> None:
        self.workspace_service = workspace_service
        if self.workspace_service is None and db is not None:
            self.workspace_service = FactoryAuthoringWorkspaceService(db)
        self._fixed_workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None
        self._explicit_source_root = Path(source_root).resolve() if source_root is not None else None
        # A detached (fixed-root) preparation still needs the authoritative
        # project store to re-verify Forge designs and Immortal Arts.
        self._authority_db = authority_db

    def _project_store_db(self) -> Any:
        return getattr(self.workspace_service, "db", None) or self._authority_db

    def _resolve_workspace(self, project_id: str) -> tuple[Path, dict[str, Any]]:
        if self.workspace_service is not None:
            status_method = getattr(self.workspace_service, "status", None)
            if not callable(status_method):
                raise FoundryError("COMMAND4_WORKSPACE_SERVICE_INVALID", "The Factory workspace service has no status reader.")
            status = status_method(project_id)
            if not isinstance(status, Mapping) or status.get("available") is not True:
                raise FoundryError("COMMAND4_WORKSPACE_NOT_READY", "The exact current sealed Factory workspace is not available.")
            root_value = status.get("workspace_path")
            if not isinstance(root_value, str) or not root_value:
                raise FoundryError("COMMAND4_WORKSPACE_PATH_INVALID", "The current Factory workspace pointer has no path.")
            root = Path(root_value).resolve()
            metadata = dict(status)
        elif self._fixed_workspace_root is not None:
            root = self._fixed_workspace_root
            metadata = {"available": True, "workspace_path": str(root)}
        else:
            raise FoundryError("COMMAND4_WORKSPACE_SERVICE_REQUIRED", "A sealed Factory workspace reader is required.")
        if not root.is_dir():
            raise FoundryError("COMMAND4_WORKSPACE_MISSING", "The current sealed Factory workspace directory is missing.")
        manifest_path = root / "Workspace_Manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The current Factory workspace manifest is invalid.") from exc
            if manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE":
                raise FoundryError("COMMAND4_WORKSPACE_STATUS_INVALID", "The Factory workspace is not sealed at the Command 1–4 boundary.")
        else:
            raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_MISSING", "The sealed Factory workspace manifest is missing.")
        sums_path = root / "SHA256SUMS.txt"
        if sums_path.is_file():
            _verify_workspace_checksums(root)
        else:
            raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_MISSING", "The sealed Factory workspace checksum ledger is missing.")
        calculated = _workspace_sha256(root)
        declared = metadata.get("workspace_sha256")
        if declared is not None and declared != calculated:
            raise FoundryError(
                "COMMAND4_WORKSPACE_STALE",
                "The current Factory workspace changed after it was sealed.",
                details={"declared": declared, "actual": calculated},
            )
        metadata["workspace_sha256"] = calculated
        metadata["workspace_path"] = str(root)
        return root, metadata

    @staticmethod
    def _load_candidate_surface_document(root: Path) -> dict[str, Any]:
        path = root / "Command_4" / "Complete_Action_Surface.json"
        if not path.is_file():
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_MISSING",
                "The sealed Command 4 complete action surface is missing.",
            )
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_INVALID",
                "The sealed Command 4 complete action surface is invalid.",
            ) from exc
        if not isinstance(document, Mapping) or document.get("schema_version") != "TianxiaFoundry.Command4CompleteActionSurface.v1":
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_SCHEMA_INVALID",
                "The sealed Command 4 complete action surface schema is unsupported.",
            )
        return deepcopy(dict(document))

    @staticmethod
    def _load_candidate_ledger(root: Path) -> list[dict[str, Any]]:
        document = Command4ProviderAuthoring._load_candidate_surface_document(root)
        rows = document.get("unresolved")
        if not isinstance(rows, list) or not rows:
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_INVALID",
                "The sealed Command 4 unresolved candidate ledger must be nonempty.",
            )
        ids: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_INVALID",
                    "The sealed Command 4 unresolved candidate ledger contains a non-object row.",
                )
            record_id = row.get("record_id")
            if not isinstance(record_id, str) or not record_id.strip() or record_id in ids:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_INVALID",
                    "The sealed Command 4 unresolved candidate IDs must be unique and nonblank.",
                )
            ids.add(record_id)
        return [deepcopy(dict(row)) for row in rows]

    def _trusted_source_roots(self, workspace_root: Path) -> tuple[Path, ...]:
        """Return only server-owned extracted roots (plus an explicit test root)."""

        roots: list[Path] = []
        if self._explicit_source_root is not None:
            roots.append(self._explicit_source_root)

        data_roots: list[Path] = []
        workspace_db = getattr(self.workspace_service, "db", None)
        settings = getattr(workspace_db, "settings", None)
        data_dir = getattr(settings, "data_dir", None)
        if isinstance(data_dir, (str, Path)) and str(data_dir):
            data_roots.append(Path(data_dir))
        current = workspace_root.resolve()
        for ancestor in (current, *current.parents):
            data_roots.append(ancestor)
        for data_root in data_roots:
            roots.append(data_root / "vendor" / "extracted")

        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            resolved = root.resolve()
            key = str(resolved)
            if key not in seen and resolved.is_dir():
                seen.add(key)
                unique.append(resolved)
        return tuple(unique)

    @staticmethod
    def _load_rules_packets(root: Path) -> dict[str, Mapping[str, Any]]:
        path = root / "Command_2" / "Rules_Selection_Packets.json"
        if not path.is_file():
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_PACKETS_MISSING",
                "The sealed Command 2 rules-selection packet authority is missing.",
            )
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_PACKETS_INVALID",
                "The sealed Command 2 rules-selection packet authority is invalid.",
            ) from exc
        if not isinstance(document, Mapping) or not isinstance(document.get("packets"), list) or not document["packets"]:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_PACKETS_INVALID",
                "The sealed Command 2 rules-selection packet authority has no packet list.",
            )
        packets: dict[str, Mapping[str, Any]] = {}
        for packet in document["packets"]:
            if not isinstance(packet, Mapping):
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKETS_INVALID",
                    "The sealed Command 2 packet list contains a non-object row.",
                )
            packet_id = packet.get("packet_id")
            if not isinstance(packet_id, str) or not packet_id.strip() or packet_id in packets:
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKETS_INVALID",
                    "The sealed Command 2 packet IDs must be unique and nonblank.",
                )
            packets[packet_id] = packet
        return packets

    @staticmethod
    def _source_file_matches(source_roots: tuple[Path, ...], relative_path: str) -> tuple[Path, ...]:
        relative = Path(relative_path)
        matches: list[Path] = []
        for source_root in source_roots:
            direct = (source_root / relative).resolve()
            try:
                direct.relative_to(source_root)
            except ValueError:
                continue
            if direct.is_file() and direct not in matches:
                matches.append(direct)
            # A package hash and extracted workflow directory may sit between
            # the trusted root and the relative source path.  Match the exact
            # suffix, never an arbitrary path outside the trusted root.
            for candidate in source_root.rglob(relative.name):
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                try:
                    suffix = resolved.relative_to(source_root).parts[-len(relative.parts):]
                except ValueError:
                    continue
                if tuple(suffix) == tuple(relative.parts) and resolved not in matches:
                    matches.append(resolved)
        return tuple(matches)

    @staticmethod
    def _source_heading(lines: list[str], line_number: int) -> tuple[str, int] | None:
        if line_number < 1 or line_number > len(lines):
            return None
        match = _TOP_LEVEL_HEADING_RE.fullmatch(lines[line_number - 1].rstrip())
        if match is None:
            return None
        return match.group("title").strip(), line_number

    def _resolve_locked_source_proof(
        self,
        root: Path,
        candidate: Mapping[str, Any],
        packets: Mapping[str, Mapping[str, Any]],
        source_roots: tuple[Path, ...],
        native_operation_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve one locked mapping against sealed packets and source bytes."""

        mapping = _locked_source_mapping(candidate)
        if mapping is None:
            return None
        record_id = candidate.get("record_id")
        packet_ids = candidate.get("source_packet_ids")
        if not isinstance(packet_ids, list) or not packet_ids:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_INVALID",
                "A locked source candidate must bind one or more source packets.",
                details={"record_id": record_id},
            )
        if candidate.get("native_operation_source_binding") is not None:
            operation = validate_native_operation_candidate(Path(__file__).resolve().parents[1], candidate)
            if native_operation_context is None:
                raise FoundryError("COMMAND4_NATIVE_OPERATION_CONTEXT_MISSING", "An operation requires independently verified project acquisition history.")
            parent = native_operation_context["parent_records"].get(operation["parent_record_id"])
            for packet_id in packet_ids:
                packet = packets.get(packet_id)
                event = native_operation_context["events"].get((packet or {}).get("event_id"))
                if not isinstance(packet, Mapping) or not isinstance(event, Mapping) or not isinstance(parent, Mapping):
                    raise FoundryError("COMMAND4_NATIVE_OPERATION_ACQUISITION_MISSING", "An operation must retain its actual parent acquisition event and locked record.")
                validate_operation_acquisition(candidate, packet, event, parent)
            return {
                **operation["parent_binding"]["source"],
                "source_packet_ids": list(packet_ids),
                "native_operation_source_binding": operation,
                "parent_record_id": operation["parent_record_id"],
                "verified_project_event_head": native_operation_context["event_head"],
                "acquisition_packet_sha256": {pid: sha256_json(packets[pid]) for pid in packet_ids},
            }
        if candidate.get("constructed_forged_source_binding") is not None:
            db = self._project_store_db()
            if db is None:
                raise FoundryError("COMMAND4_FORGED_SOURCE_CONTEXT_MISSING", "Forge verification requires the authoritative project store.")
            build_request = json.loads((root / "Command_1" / "Build_Request.json").read_text(encoding="utf-8"))
            project_id = build_request.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise FoundryError("COMMAND4_FORGED_SOURCE_CONTEXT_MISSING", "The sealed workspace has no project identity.")
            constructed = validate_forged_action_candidate(db, project_id, candidate)
            for packet_id in packet_ids:
                packet = packets.get(packet_id)
                if not isinstance(packet, Mapping) or packet.get("record_id") != record_id or packet.get("record_hash") != candidate.get("record_hash") or packet.get("advancement_kind") != "forged_technique_creation":
                    raise FoundryError("COMMAND4_FORGED_ACQUISITION_MISMATCH", "The Forge design must retain its exact creation packet and record commitment.", details={"record_id": record_id, "packet_id": packet_id})
                evidence = packet.get("source_evidence")
                source = constructed["source"]
                if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], Mapping) or any(evidence[0].get(key) != source[field] for key, field in (("source_path", "path"), ("source_hash", "sha256"), ("source_anchor", "anchor"))):
                    raise FoundryError("COMMAND4_FORGED_ACQUISITION_MISMATCH", "The creation packet must retain the Forge design's exact source identity.", details={"record_id": record_id, "packet_id": packet_id})
            return {**constructed["source"], "source_packet_ids": list(packet_ids), "constructed_forged_source_binding": constructed, "acquisition_packet_sha256": {pid: sha256_json(packets[pid]) for pid in packet_ids}}
        if candidate.get("constructed_immortal_source_binding") is not None:
            db = self._project_store_db()
            if db is None:
                raise FoundryError("COMMAND4_IMMORTAL_SOURCE_CONTEXT_MISSING", "Immortal Art verification requires the authoritative project store.")
            build_request = json.loads((root / "Command_1" / "Build_Request.json").read_text(encoding="utf-8"))
            project_id = build_request.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise FoundryError("COMMAND4_IMMORTAL_SOURCE_CONTEXT_MISSING", "The sealed workspace has no project identity.")
            return _resolve_constructed_immortal_source_proof(
                db,
                project_id,
                candidate,
                packets,
            )
        native = validate_native_path_candidate(Path(__file__).resolve().parents[1], candidate)
        if native is not None:
            # A level-event packet proves acquisition provenance, not a Sphere
            # heading. Preserve it while independently authenticating native
            # mechanics against the server-owned Path index.
            for packet_id in packet_ids:
                if not isinstance(packets.get(packet_id), Mapping):
                    raise FoundryError(
                        "COMMAND4_LOCKED_SOURCE_PACKET_MISSING",
                        "A native source candidate references an unknown acquisition packet.",
                        details={"record_id": record_id, "packet_id": packet_id},
                    )
            return {
                **native["source"],
                "source_packet_ids": list(packet_ids),
                "native_source_binding": native,
                "acquisition_packet_sha256": {pid: sha256_json(packets[pid]) for pid in packet_ids},
            }
        packet_evidence: list[dict[str, str]] = []
        for packet_id in packet_ids:
            packet = packets.get(packet_id)
            if not isinstance(packet, Mapping):
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKET_MISSING",
                    "A locked source candidate references an unknown sealed rules packet.",
                    details={"record_id": record_id, "packet_id": packet_id},
                )
            evidence = packet.get("source_evidence")
            if not isinstance(evidence, list) or len(evidence) != 1 or not isinstance(evidence[0], Mapping):
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKET_INVALID",
                    "Each locked source packet must carry exactly one source-evidence binding.",
                    details={"record_id": record_id, "packet_id": packet_id},
                )
            item = evidence[0]
            source_path = item.get("source_path")
            source_hash = item.get("source_hash")
            source_anchor = item.get("source_anchor")
            packet_anchor = _PACKET_SOURCE_ANCHOR_RE.fullmatch(source_anchor) if isinstance(source_anchor, str) else None
            if (
                source_path != mapping["path"]
                or source_hash != mapping["sha256"]
                or not _is_hash(source_hash)
                or packet_anchor is None
                or int(packet_anchor.group("column")) != 1
            ):
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKET_MISMATCH",
                    "A locked source packet does not bind the candidate's exact path, SHA, and line anchor.",
                    details={"record_id": record_id, "packet_id": packet_id},
                )
            packet_evidence.append({
                "source_path": source_path,
                "source_hash": source_hash,
                "source_anchor": source_anchor,
            })

        matches = self._source_file_matches(source_roots, mapping["path"])
        if not matches:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_FILE_MISSING",
                "The locked source file is not present under a trusted extracted source root.",
                details={"record_id": record_id, "path": mapping["path"]},
            )
        if len(matches) != 1:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_FILE_AMBIGUOUS",
                "The locked source path resolves to more than one trusted source file.",
                details={"record_id": record_id, "path": mapping["path"], "matches": [str(path) for path in matches]},
            )
        source_file = matches[0]
        try:
            source_bytes = source_file.read_bytes()
        except OSError as exc:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_FILE_INVALID",
                "The locked source file cannot be read.",
                details={"record_id": record_id},
            ) from exc
        actual_hash = sha256_bytes(source_bytes)
        if actual_hash != mapping["sha256"]:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_HASH_MISMATCH",
                "The locked source file bytes do not match the sealed candidate SHA.",
                details={"record_id": record_id, "expected": mapping["sha256"], "actual": actual_hash},
            )
        try:
            source_text = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_FILE_INVALID",
                "The locked source file is not valid UTF-8.",
                details={"record_id": record_id},
            ) from exc
        lines = source_text.splitlines()

        semantic = _SEMANTIC_SOURCE_ANCHOR_RE.fullmatch(mapping["anchor"])
        if semantic is None or int(semantic.group("start")) > int(semantic.group("end")):
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ANCHOR_INVALID",
                "The locked source must carry a semantic Sphere anchor and packet sphere heading.",
                details={"record_id": record_id},
            )
        semantic_sphere = semantic.group("sphere").strip()
        packet_spheres: list[tuple[str, int]] = []
        for evidence in packet_evidence:
            packet_anchor = _PACKET_SOURCE_ANCHOR_RE.fullmatch(evidence["source_anchor"])
            if packet_anchor is None:  # pragma: no cover - guarded while loading evidence
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKET_MISMATCH",
                    "A locked source packet has an invalid source anchor.",
                    details={"record_id": record_id},
                )
            sphere_line = int(packet_anchor.group("line"))
            sphere_heading = self._source_heading(lines, sphere_line)
            if sphere_heading is None:
                raise FoundryError(
                    "COMMAND4_LOCKED_SOURCE_PACKET_MISMATCH",
                    "A locked packet anchor must point to a top-level Sphere heading.",
                    details={"record_id": record_id},
                )
            packet_spheres.append((sphere_heading[0], sphere_line))
        sphere_title, sphere_line = packet_spheres[0]
        if any(
            _normalize_source_label(title) != _normalize_source_label(sphere_title)
            or line != sphere_line
            for title, line in packet_spheres[1:]
        ):
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_PACKET_MISMATCH",
                "All locked source packets must point to the same exact Sphere heading.",
                details={"record_id": record_id},
            )
        if _normalize_source_label(sphere_title) != _normalize_source_label(semantic_sphere):
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ANCHOR_MISMATCH",
                "The candidate semantic Sphere does not match the sealed packet heading.",
                details={"record_id": record_id},
            )
        candidate_source_lines = _candidate_source(candidate).splitlines()
        first_line = candidate_source_lines[0].rstrip() if candidate_source_lines else ""
        candidate_heading = _MARKDOWN_HEADING_RE.fullmatch(first_line)
        name = candidate.get("name")
        if candidate_heading is None or not isinstance(name, str) or not name.strip():
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ANCHOR_INVALID",
                "A locked candidate description must begin with its exact Markdown heading and name.",
                details={"record_id": record_id},
            )
        heading_text = candidate_heading.group("title").strip().rstrip("#").strip()
        semantic_slug = _normalize_source_label(semantic.group("slug"))
        if not (
            _normalize_source_label(heading_text) == semantic_slug
            and _normalize_source_label(name) == semantic_slug
        ):
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ANCHOR_MISMATCH",
                "The candidate name, heading, and semantic source slug do not agree.",
                details={"record_id": record_id},
            )

        next_sphere_line = len(lines) + 1
        for index in range(sphere_line, len(lines)):
            if index + 1 == sphere_line:
                continue
            if _TOP_LEVEL_HEADING_RE.fullmatch(lines[index].rstrip()):
                next_sphere_line = index + 1
                break
        heading_matches: list[int] = []
        for index in range(sphere_line, next_sphere_line - 1):
            heading = _MARKDOWN_HEADING_RE.fullmatch(lines[index].rstrip())
            if heading is not None and _normalize_source_label(heading.group("title").strip().rstrip("#").strip()) == semantic_slug:
                heading_matches.append(index + 1)
        if len(heading_matches) != 1:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ANCHOR_AMBIGUOUS",
                "The candidate heading must resolve uniquely within its sealed Sphere section.",
                details={"record_id": record_id, "matches": heading_matches},
            )
        if first_line != lines[heading_matches[0] - 1].rstrip():
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ANCHOR_MISMATCH",
                "The candidate description must begin with the exact sealed source heading.",
                details={"record_id": record_id},
            )
        resolved_anchor = f"line:{heading_matches[0]}:column:1"
        return {
            "path": mapping["path"],
            "anchor": mapping["anchor"],
            "sha256": mapping["sha256"],
            "source_packet_ids": list(packet_ids),
            "packet_source_evidence": deepcopy(packet_evidence),
            "resolved_anchor": resolved_anchor,
            "resolved_heading": lines[heading_matches[0] - 1].rstrip(),
        }

    def _locked_source_proofs(self, root: Path, candidates: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        locked = [candidate for candidate in candidates if _LOCKED_SOURCE_FIELD in (candidate.get("missing_fields") or [])]
        for candidate in candidates:
            _locked_source_mapping(candidate)
        if not locked:
            return {}
        packets = self._load_rules_packets(root)
        source_roots = self._trusted_source_roots(root)
        if not source_roots:
            raise FoundryError(
                "COMMAND4_LOCKED_SOURCE_ROOT_MISSING",
                "No trusted extracted source root is available for locked source resolution.",
            )
        operation_context = None
        operation_candidates = [row for row in candidates if row.get("native_operation_source_binding") is not None]
        if operation_candidates:
            from project_store.service import ProjectStore
            db = getattr(self.workspace_service, "db", None)
            if db is None:
                raise FoundryError("COMMAND4_NATIVE_OPERATION_CONTEXT_MISSING", "Native operations require the authoritative project store.")
            request = json.loads((root / "Command_1" / "Build_Request.json").read_text(encoding="utf-8"))
            projects = ProjectStore(db)
            project_id = request.get("project_id")
            project = projects.get_project(project_id)
            if project.get("revision") != request.get("project_revision"):
                raise FoundryError("COMMAND4_NATIVE_OPERATION_PROJECT_CHANGED", "The operation workspace must match the current project revision.")
            chain = projects.verify_chain(project_id)
            if chain.get("valid") is not True:
                raise FoundryError("COMMAND4_NATIVE_OPERATION_CHAIN_INVALID", "Native operation acquisition requires a valid project event chain.")
            parents = {validate_native_operation_candidate(Path(__file__).resolve().parents[1], row)["parent_record_id"] for row in operation_candidates}
            with db.connection() as conn:
                parent_records = {parent: projects._resolve_locked_record(conn, project_id, parent) for parent in parents}
            operation_context = {"events": {event["event_id"]: event for event in projects.timeline(project_id)}, "parent_records": parent_records, "event_head": chain["latest_event_hash"]}
        proofs: dict[str, dict[str, Any]] = {}
        for candidate in locked:
            record_id = candidate.get("record_id")
            if not isinstance(record_id, str):
                raise FoundryError("COMMAND4_LOCKED_SOURCE_INVALID", "A locked source candidate must have a record ID.")
            proof = self._resolve_locked_source_proof(root, candidate, packets, source_roots, native_operation_context=operation_context)
            if proof is not None:
                proofs[record_id] = proof
        return proofs

    def _load_candidates(self, root: Path) -> list[dict[str, Any]]:
        path = root / "Command_4" / "Action_Authoring_Candidates.json"
        if not path.is_file():
            raise FoundryError("COMMAND4_CANDIDATES_MISSING", "The sealed Command 4 candidate document is missing.")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FoundryError("COMMAND4_CANDIDATES_INVALID", "The sealed Command 4 candidate document is invalid.") from exc
        if not isinstance(document, Mapping) or document.get("schema_version") != ACTION_CANDIDATES_SCHEMA:
            raise FoundryError("COMMAND4_CANDIDATES_SCHEMA_INVALID", "The sealed Command 4 candidate schema is unsupported.")
        rows = document.get("candidates")
        if not isinstance(rows, list) or not rows:
            raise FoundryError("COMMAND4_CANDIDATES_EMPTY", "The sealed Command 4 candidate set is empty.")
        materialized = [deepcopy(dict(row)) for row in rows if isinstance(row, Mapping)]
        if len(materialized) != len(rows):
            raise FoundryError("COMMAND4_CANDIDATES_INVALID", "The sealed Command 4 candidate set contains a non-object row.")
        ids = [row.get("record_id") for row in materialized]
        if any(not isinstance(record_id, str) or not record_id.strip() for record_id in ids) or len(set(ids)) != len(ids):
            raise FoundryError("COMMAND4_CANDIDATES_INVALID", "The sealed Command 4 candidate IDs must be unique and nonblank.")
        for candidate in materialized:
            missing = candidate.get("missing_fields")
            if missing is not None and (
                not isinstance(missing, list)
                or any(not isinstance(value, str) or not value.strip() for value in missing)
            ):
                raise FoundryError(
                    "COMMAND4_CANDIDATE_INVALID",
                    "Candidate missing fields must be a list of nonblank field names.",
                    details={"record_id": candidate.get("record_id")},
                )
        surface_document = self._load_candidate_surface_document(root)
        ledger = self._load_candidate_ledger(root)
        ledger_ids = [str(row["record_id"]) for row in ledger]
        legacy_untyped_surface = "procedures" not in surface_document and "actions" in surface_document
        surface_has_ready_rows = any(
            isinstance(surface_document.get(key), list) and bool(surface_document.get(key))
            for key in ("actions", "procedures")
        )
        expected_unresolved_ids = (
            [
                str(row["record_id"])
                for row in materialized
                if row.get("missing_fields")
            ]
            if surface_has_ready_rows
            else ids
        )
        if ledger_ids != expected_unresolved_ids:
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                "The sealed unresolved ledger must be the exact ordered subset of candidates with missing fields.",
                details={"expected_unresolved_ids": expected_unresolved_ids, "ledger_ids": ledger_ids},
            )
        candidate_by_id = {str(row["record_id"]): row for row in materialized}
        for ledger_row in ledger:
            candidate = candidate_by_id.get(str(ledger_row["record_id"]))
            if candidate is None:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "The unresolved ledger contains a record absent from the candidate document.",
                    details={"record_id": ledger_row.get("record_id")},
                )
            expected_action_id = _candidate_value(candidate, "action_id")
            if ledger_row.get("action_id") != expected_action_id:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "The unresolved ledger action identity does not match its candidate.",
                    details={"record_id": candidate.get("record_id")},
                )
            candidate_missing = candidate.get("missing_fields") or []
            ledger_missing = ledger_row.get("missing_fields")
            if not isinstance(ledger_missing, list) or ledger_missing != candidate_missing:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "The unresolved ledger missing-field projection does not match its candidate.",
                    details={"record_id": candidate.get("record_id")},
                )

        excluded_base_ids = _command4_non_executable_base_record_ids(materialized)
        excluded_ids = excluded_base_ids | _command4_unauthorable_record_ids(materialized)
        unresolved_id_set = set(expected_unresolved_ids)
        ready_ids = [
            record_id
            for record_id in ids
            if record_id not in unresolved_id_set and record_id not in excluded_ids
        ]
        surface_rows: list[tuple[str, Mapping[str, Any]]] = []
        for key in ("actions", "procedures"):
            rows = surface_document.get(key, [])
            if not isinstance(rows, list):
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "The sealed complete action surface must contain an array for every ready runtime kind.",
                    details={"field": key},
                )
            for row in rows:
                if not isinstance(row, Mapping):
                    raise FoundryError(
                        "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                        "The sealed complete action surface contains a non-object ready row.",
                        details={"field": key},
                    )
                surface_rows.append((key, row))
        surface_ready_ids: list[str] = []
        surface_rows_by_id: dict[str, tuple[str, Mapping[str, Any], str]] = {}
        for container_key, row in surface_rows:
            record_id = row.get("record_id")
            if not isinstance(record_id, str) or not record_id.strip() or record_id in surface_rows_by_id:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "The sealed complete action surface ready IDs must be unique and nonblank.",
                    details={"record_id": record_id},
                )
            if record_id not in ready_ids:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "The sealed complete action surface contains an unresolved or unknown ready row.",
                    details={"record_id": record_id},
                )
            candidate = candidate_by_id[record_id]
            expected_runtime_kind = _candidate_runtime_kind(candidate)
            container_runtime_kind = "procedure" if container_key == "procedures" else "action"
            declared_runtime_kind = row.get("runtime_kind")
            runtime_kind = (
                declared_runtime_kind
                if isinstance(declared_runtime_kind, str)
                else expected_runtime_kind
            )
            if not legacy_untyped_surface and (
                expected_runtime_kind != container_runtime_kind
                or runtime_kind != container_runtime_kind
            ):
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "A typed ready surface row must be stored in its matching runtime-kind container.",
                    details={"record_id": record_id, "field": container_key},
                )
            surface_ready_ids.append(record_id)
            surface_rows_by_id[record_id] = (container_key, row, runtime_kind)
        if set(surface_ready_ids) != set(ready_ids):
            raise FoundryError(
                "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                "The sealed complete action surface must retain every ready candidate exactly once.",
                details={"expected_ready_ids": ready_ids, "surface_ready_ids": surface_ready_ids},
            )
        for key in ("actions", "procedures"):
            actual_ids = [
                record_id
                for record_id in surface_ready_ids
                if surface_rows_by_id[record_id][0] == key
            ]
            if legacy_untyped_surface:
                # The pre-typed producer emitted every executable row under
                # ``actions`` and omitted ``procedures``.  That absence is
                # the only compatibility marker; retain its full canonical
                # order while typed surfaces remain container-bound below.
                expected_ids = ready_ids if key == "actions" else []
            else:
                expected_runtime_kind = "procedure" if key == "procedures" else "action"
                expected_ids = [
                    record_id
                    for record_id in ready_ids
                    if _candidate_runtime_kind(candidate_by_id[record_id]) == expected_runtime_kind
                ]
            if actual_ids != expected_ids:
                raise FoundryError(
                    "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                    "Each typed ready surface array must retain its canonical filtered order.",
                    details={"field": key, "expected_ids": expected_ids, "actual_ids": actual_ids},
                )
        for record_id in ready_ids:
            _, surface_row, runtime_kind = surface_rows_by_id[record_id]
            _validate_sealed_ready_candidate(candidate_by_id[record_id], surface_row, runtime_kind=runtime_kind)

        # Keep the full candidate order: ready rows are already sealed and are
        # revalidated above, while unresolved rows continue through authoring.
        # The unresolved ledger remains the authority for its subset order.
        # Excluded rows (CAT3 non-executable bases and unauthorable rows) are
        # display-only and never reach the provider; resolve locked-source
        # proofs only for the rows that stay in the authoring set so an
        # excluded row's positional anchor cannot block every other candidate.
        locked_source_proofs = self._locked_source_proofs(
            root,
            [row for row in materialized if row["record_id"] not in excluded_ids],
        )
        for row in materialized:
            proof = locked_source_proofs.get(str(row["record_id"]))
            if row["record_id"] in excluded_ids:
                continue
            # Reviewed override records must prove their source commitment
            # before generic source/resource validation can short-circuit the
            # binding error (including a non-string full_description).
            _reviewed_forced_provider_fields(row.get("record_id"), row.get("full_description"))
            _safe_prompt_candidate(row, locked_source=proof)
            _validate_candidate_server_prerequisites(row, locked_source=proof)
        return [row for row in materialized if row["record_id"] not in excluded_ids]

    def prepare(self, project_id: str) -> dict[str, Any]:
        """Build a deterministic provider prompt without making a provider call."""

        if not isinstance(project_id, str) or not project_id.strip():
            raise FoundryError("COMMAND4_PROJECT_ID_INVALID", "A nonblank project ID is required.")
        root, metadata = self._resolve_workspace(project_id)
        candidates = self._load_candidates(root)
        signature_loadout_ids, signature_loadout_min_items, signature_loadout_max_items = _signature_loadout_projection(
            candidates,
            error_code="COMMAND4_SIGNATURE_LOADOUT_DOMAIN_INVALID",
        )
        locked_source_proofs = self._locked_source_proofs(root, candidates)
        provider_field_partition = _provider_field_partition(candidates)
        source_hashes = {
            str(row["record_id"]): _hash_text(_candidate_source(row))
            for row in candidates
        }
        provider_field_domains = {
            str(row["record_id"]): {
                field: _provider_field_domain(row, field)
                for field in _provider_authorable_fields(row)
            }
            for row in candidates
        }
        token_owners: dict[str, tuple[str, str]] = {}
        for record_id, domains in provider_field_domains.items():
            for field, domain in domains.items():
                tokens = domain.get("selection_tokens") if isinstance(domain, Mapping) else None
                if not isinstance(tokens, list) or any(
                    not isinstance(token, str) or not _OPTION_TOKEN_RE.fullmatch(token)
                    for token in tokens
                ):
                    raise FoundryError(
                        "COMMAND4_PROVIDER_FIELD_TOKEN_INVALID",
                        "Every provider field option must have a valid opaque selection token.",
                        details={"record_id": record_id, "field": field},
                    )
                for token in tokens:
                    if token in token_owners:
                        raise FoundryError(
                            "COMMAND4_PROVIDER_FIELD_TOKEN_COLLISION",
                            "Opaque selection tokens must be globally unique across the sealed ledger.",
                            details={"record_id": record_id, "field": field},
                        )
                    token_owners[token] = (record_id, field)
        provider_field_domain_bindings = {
            record_id: {
                "record_id": record_id,
                "source_text_sha256": source_hashes[record_id],
                "fields": {
                    field: list(domain["options"])
                    for field, domain in domains.items()
                },
                "option_records": {
                    field: deepcopy(domain["option_records"])
                    for field, domain in domains.items()
                },
                "selection_tokens": {
                    field: list(domain["selection_tokens"])
                    for field, domain in domains.items()
                },
                "token_to_option": {
                    field: deepcopy(domain["token_to_option"])
                    for field, domain in domains.items()
                },
            }
            for record_id, domains in provider_field_domains.items()
        }
        provider_field_domain_partition = _provider_field_domain_partition(candidates)
        prompt_candidates: list[dict[str, Any]] = []
        for row in candidates:
            record_id = str(row["record_id"])
            prompt_row = _safe_prompt_candidate(
                row,
                locked_source=locked_source_proofs.get(record_id),
            )
            prompt_row["provider_field_options"] = {
                field: deepcopy(provider_field_domains[record_id][field]["prompt_options"])
                for field in _provider_authorable_fields(row)
            }
            prompt_candidates.append(prompt_row)
        prompt_payload = {
            "schema": "TianxiaFoundry.Command4ProviderAuthoringPrompt.v1",
            "project_id": project_id,
            "source_workspace_sha256": metadata["workspace_sha256"],
            "candidate_source_sha256": sha256_json(source_hashes),
            "contract": {
                "response_top_level_keys": [
                    "schema",
                    "request_sha256",
                    "source_workspace_sha256",
                    "quotes",
                    "signature_loadout_record_ids",
                ],
                "quote_count": provider_field_partition["total_provider_field_count"],
                "quote_order": "Concatenate each candidate's provider_authorable_fields in the exact candidate list order; emit one quote per field, with no record or field names; empty rows contribute zero quotes.",
                "field_value": "Each quotes item must exactly equal one supplied opaque token for its sealed position; provider_field_options pairs each token with its exact allowed value, and the server maps tokens to source_quote/bounded_interpretation/not_applicable packets.",
                "provider_authorable_fields": "For each candidate, the listed provider_authorable_fields are the exact positions contributed to the flat quotes array; provider_field_options gives ordered token/value pairs for each position; an empty list contributes no quote.",
                "deterministic_label_binding": "Select only a supplied token: labelled fields have their exact parsed value, while unlabeled fields have a reviewed substantive same-record span or an explicit reviewed N/A token.",
                "field_relevance_rules": dict(_FIELD_RELEVANCE_RULES),
                "not_applicable_token": COMMAND4_NOT_APPLICABLE_QUOTE,
                "server_locked_fields": sorted(_SERVER_CLASSIFICATION_FIELDS),
                "server_derived_fields": sorted(_DERIVED_FIELDS),
                "signature_loadout": (
                    "Choose only distinct eligible action record IDs: 10–14 when available; all eligible actions "
                    "when fewer than 10, exactly once. Procedures, passive, and basic records are not eligible."
                ),
                "signature_loadout_bounds": {
                    "eligible_action_count": len(signature_loadout_ids),
                    "min_items": signature_loadout_min_items,
                    "max_items": signature_loadout_max_items,
                },
                "rules": [
                    "Copy response_constants.schema, request_sha256, and source_workspace_sha256 exactly into the matching response fields; use quote_count only to size quotes.",
                    "Return exactly response_constants.quote_count strings in quotes, in the concatenated candidate/field order; do not return records, record IDs, source hashes, or field names.",
                    "Every quote must be one exact supplied opaque token for its position; return the token, not its paired value or source mechanics.",
                    "The token is the only response identity; do not return source values, the not_applicable_token, record IDs, source hashes, field names, authority, or evidence.",
                    "Use a token only at the position where it is supplied; the server assigns field names and authority/evidence.",
                    "Known candidate fields, classification, IDs, source packets, and resources are server-assembled; never echo them.",
                    "Do not add state names, resources, numeric/dice/DC/CL quantities, or cross-record evidence.",
                    "Preserve the locked procedure classification; never return a procedure as an action.",
                ],
            },
            "candidates": prompt_candidates,
        }
        prompt_payload = _compact_fixed_quote_prompt(prompt_payload)
        # ``request_sha256`` is the hash of the immutable contract payload
        # before adding this small constants echo.  Including the hash inside
        # the bytes being hashed would be a cryptographic self-reference; the
        # provider receives the resulting value explicitly and the transport
        # still binds the final wire bytes separately via provider_request_sha256.
        request_sha256 = sha256_bytes(canonical_json(prompt_payload).encode("utf-8"))
        legacy_prompt_payload = deepcopy(prompt_payload)
        legacy_contract = legacy_prompt_payload.get("contract")
        if not isinstance(legacy_contract, Mapping):
            raise FoundryError(
                "COMMAND4_REQUEST_CONTRACT_INVALID",
                "The sealed Command 4 prompt contract cannot produce a legacy compatibility identity.",
            )
        legacy_contract["signature_loadout"] = _LEGACY_SIGNATURE_LOADOUT_CONTRACT
        legacy_contract.pop("signature_loadout_bounds", None)
        legacy_provider_request_sha256 = sha256_bytes(
            canonical_json(legacy_prompt_payload).encode("utf-8")
        )
        prompt_payload["response_constants"] = {
            "schema": self.response_schema,
            "request_sha256": request_sha256,
            "source_workspace_sha256": metadata["workspace_sha256"],
            "quote_count": provider_field_partition["total_provider_field_count"],
            "selection_token_prefix": "c4opt_",
            "not_applicable_token": COMMAND4_NOT_APPLICABLE_QUOTE,
        }
        prompt_text = canonical_json(prompt_payload)
        prepared_authority = {
            "candidates": candidates,
            "candidate_ids": [str(row["record_id"]) for row in candidates],
            "source_text_sha256_by_record_id": source_hashes,
            "provider_authorable_fields_by_record_id": {
                str(row["record_id"]): list(_provider_authorable_fields(row)) for row in candidates
            },
            "provider_field_domains_by_record_id": provider_field_domains,
            "provider_field_domain_bindings_by_record_id": provider_field_domain_bindings,
            "request_sha256": request_sha256,
            "source_workspace_sha256": metadata["workspace_sha256"],
            "signature_loadout_eligible_record_ids": list(signature_loadout_ids),
            "signature_loadout_min_items": signature_loadout_min_items,
            "signature_loadout_max_items": signature_loadout_max_items,
        }
        if "quote_constants" in prompt_payload:
            prepared_authority["fixed_quote_constants"] = prompt_payload["quote_constants"]
        response_schema = build_command4_response_schema(prepared_authority)
        request_bytes = canonical_command4_wire_bytes(
            prompt_text,
            system_message=self.system_message,
            temperature=0,
            response_schema=response_schema,
            response_schema_name=COMMAND4_PROVIDER_RESPONSE_SCHEMA_NAME,
            response_schema_max_output_tokens=LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
        )
        if len(request_bytes) > self.max_request_bytes:
            raise FoundryError(
                "COMMAND4_PROVIDER_REQUEST_TOO_LARGE",
                "The compact Command 4 authoring request exceeds its exact canonical wire cap.",
                details={"request_bytes": len(request_bytes), "max_request_bytes": self.max_request_bytes},
                status_code=413,
            )
        return {
            "project_id": project_id,
            "workspace_path": str(root),
            "source_workspace_sha256": metadata["workspace_sha256"],
            "source_text_sha256_by_record_id": source_hashes,
            "candidate_ids": [str(row["record_id"]) for row in candidates],
            "candidates": candidates,
            "provider_authorable_fields_by_record_id": {
                str(row["record_id"]): list(_provider_authorable_fields(row)) for row in candidates
            },
            "provider_field_domains_by_record_id": provider_field_domains,
            "provider_field_domain_bindings_by_record_id": provider_field_domain_bindings,
            "locked_source_proof_by_record_id": deepcopy(locked_source_proofs),
            "prompt_text": prompt_text,
            "system_message": self.system_message,
            "request_sha256": request_sha256,
            "legacy_provider_request_sha256": legacy_provider_request_sha256,
            "request_bytes": len(request_bytes),
            "max_request_bytes": self.max_request_bytes,
            "response_schema": response_schema,
            "response_schema_name": COMMAND4_PROVIDER_RESPONSE_SCHEMA_NAME,
            "response_schema_bytes": len(_json_bytes(response_schema)),
            "signature_loadout_eligible_record_ids": list(signature_loadout_ids),
            "signature_loadout_min_items": signature_loadout_min_items,
            "signature_loadout_max_items": signature_loadout_max_items,
            **provider_field_partition,
            **provider_field_domain_partition,
        }

    @staticmethod
    def _deterministic_response(prepared: Mapping[str, Any]) -> dict[str, Any]:
        """Build a response only when the sealed domains imply one choice.

        This gate is deliberately stricter than normal provider authoring.  It
        never selects among alternatives: every provider field must expose one
        opaque token and the signature loadout must require the complete
        eligible action set.  Diagnostics contain counts only so a failed
        deterministic attempt cannot turn source text into a new authority
        channel.
        """

        candidates = prepared.get("candidates")
        try:
            eligible_ids, loadout_min_items, loadout_max_items = _signature_loadout_projection(
                candidates,
                error_code=COMMAND4_DETERMINISTIC_CHOICE_REQUIRED,
            )
        except FoundryError:
            raise FoundryError(
                COMMAND4_DETERMINISTIC_CHOICE_REQUIRED,
                "The sealed signature-loadout domain cannot be resolved deterministically.",
                details={
                    "provider_field_count": 0,
                    "singleton_provider_field_count": 0,
                    "non_singleton_provider_field_count": 0,
                    "eligible_action_count": 0,
                    "signature_loadout_min_items": 0,
                    "signature_loadout_max_items": 0,
                },
            ) from None

        fields_by_id = prepared.get("provider_authorable_fields_by_record_id")
        domains_by_id = prepared.get("provider_field_domains_by_record_id")
        field_count = 0
        singleton_count = 0
        non_singleton_count = 0
        malformed_count = 0
        quotes: list[str] = []
        if not isinstance(fields_by_id, Mapping) or not isinstance(domains_by_id, Mapping) or not isinstance(candidates, list):
            malformed_count = 1
        else:
            for candidate in candidates:
                record_id = candidate.get("record_id") if isinstance(candidate, Mapping) else None
                fields = fields_by_id.get(record_id) if isinstance(record_id, str) else None
                domains = domains_by_id.get(record_id) if isinstance(record_id, str) else None
                if not isinstance(fields, list) or not isinstance(domains, Mapping):
                    malformed_count += 1
                    continue
                for field in fields:
                    field_count += 1
                    domain = domains.get(field)
                    tokens = domain.get("selection_tokens") if isinstance(domain, Mapping) else None
                    options = domain.get("options") if isinstance(domain, Mapping) else None
                    option_records = domain.get("option_records") if isinstance(domain, Mapping) else None
                    token_to_option = domain.get("token_to_option") if isinstance(domain, Mapping) else None
                    singleton = (
                        isinstance(tokens, list)
                        and len(tokens) == 1
                        and isinstance(tokens[0], str)
                        and _OPTION_TOKEN_RE.fullmatch(tokens[0]) is not None
                        and isinstance(options, list)
                        and len(options) == 1
                        and isinstance(option_records, list)
                        and len(option_records) == 1
                        and isinstance(token_to_option, Mapping)
                        and set(token_to_option) == {tokens[0]}
                    )
                    if not singleton:
                        non_singleton_count += 1
                        malformed_count += 1
                        continue
                    singleton_count += 1
                    quotes.append(tokens[0])

        schema = prepared.get("response_schema")
        loadout_schema = (
            schema.get("properties", {}).get("signature_loadout_record_ids")
            if isinstance(schema, Mapping) and isinstance(schema.get("properties"), Mapping)
            else None
        )
        loadout_items = loadout_schema.get("items") if isinstance(loadout_schema, Mapping) else None
        loadout_enum = loadout_items.get("enum") if isinstance(loadout_items, Mapping) else None
        metadata_matches = (
            prepared.get("signature_loadout_eligible_record_ids") == eligible_ids
            and prepared.get("signature_loadout_min_items") == loadout_min_items
            and prepared.get("signature_loadout_max_items") == loadout_max_items
        )
        schema_matches = (
            isinstance(loadout_schema, Mapping)
            and loadout_schema.get("minItems") == loadout_min_items
            and loadout_schema.get("maxItems") == loadout_max_items
            and loadout_enum == eligible_ids
        ) or (
            # The fixed complete loadout is published as a constant (build 26).
            isinstance(loadout_schema, Mapping)
            and loadout_schema.get("const") == list(eligible_ids)
        )
        loadout_is_singleton = (
            loadout_min_items == loadout_max_items == len(eligible_ids)
            and metadata_matches
            and schema_matches
        )
        diagnostics = {
            "provider_field_count": field_count,
            "singleton_provider_field_count": singleton_count,
            "non_singleton_provider_field_count": non_singleton_count,
            "malformed_provider_field_count": malformed_count,
            "eligible_action_count": len(eligible_ids),
            "signature_loadout_min_items": loadout_min_items,
            "signature_loadout_max_items": loadout_max_items,
        }
        if malformed_count or not loadout_is_singleton:
            raise FoundryError(
                COMMAND4_DETERMINISTIC_CHOICE_REQUIRED,
                "Every provider field and the complete signature loadout must be uniquely implied by the sealed authority.",
                details=diagnostics,
            )

        return {
            "schema": COMMAND4_PROVIDER_RESPONSE_SCHEMA,
            "request_sha256": prepared.get("request_sha256"),
            "source_workspace_sha256": prepared.get("source_workspace_sha256"),
            "quotes": quotes,
            "signature_loadout_record_ids": list(eligible_ids),
        }

    @staticmethod
    def _parse_provider_response(provider_result: Any) -> tuple[dict[str, Any], str | None]:
        if not isinstance(provider_result, Mapping):
            raise _response_error("COMMAND4_PROVIDER_RESPONSE_INVALID", "The provider result must be an object.")
        raw = provider_result.get("response_text")
        if not isinstance(raw, str) or not raw.strip():
            value = provider_result.get("value")
            if isinstance(value, Mapping):
                return deepcopy(dict(value)), canonical_json(value)
            raise _response_error("COMMAND4_PROVIDER_RESPONSE_INVALID", "The provider result has no JSON response text.")
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise _response_error("COMMAND4_PROVIDER_RESPONSE_INVALID", "The provider response is not valid JSON.") from exc
        if not isinstance(value, Mapping):
            raise _response_error("COMMAND4_PROVIDER_RESPONSE_INVALID", "The provider response must be one JSON object.")
        return deepcopy(dict(value)), raw

    @staticmethod
    def _validate_field_quote(
        quote: Any,
        source_text: str,
        *,
        field: str,
        record_id: str,
        parsed_fields: Mapping[str, str] | None = None,
        domain: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate one quote and expand it into a server-owned packet.

        Explicitly labelled values are deterministic parser output and must be
        echoed exactly.  Unlabelled fields must select a substantive substring
        from a source line carrying the requested field's signal.  A fixed
        N/A token is accepted only when no such source option exists; the
        server, never the provider, assigns its authority and evidence.
        """

        if isinstance(quote, Mapping):
            raise _response_error(
                "COMMAND4_FIELD_PACKET_INVALID",
                "Provider fields must be direct opaque selection-token strings; authority and evidence are server-owned.",
                details={"record_id": record_id, "field": field, "classification": "field_packet"},
            )
        if not isinstance(quote, str) or not quote.strip():
            raise _response_error(
                "COMMAND4_FIELD_UNRESOLVED",
                "A provider-authorable field must be one nonblank opaque selection token.",
                details={"record_id": record_id, "field": field, "classification": "blank_quote"},
            )
        selected_option: Mapping[str, Any] | None = None
        parsed_value = parsed_fields.get(field) if isinstance(parsed_fields, Mapping) else None
        reviewed_override = field in _reviewed_forced_provider_fields(record_id, source_text)
        if isinstance(domain, Mapping):
            options = domain.get("options")
            option_records = domain.get("option_records")
            selection_tokens = domain.get("selection_tokens")
            token_to_option = domain.get("token_to_option")
            if (
                not isinstance(options, list)
                or not options
                or not isinstance(option_records, list)
                or [record.get("provider_value") for record in option_records if isinstance(record, Mapping)] != options
                or not isinstance(selection_tokens, list)
                or len(selection_tokens) != len(option_records)
                or len(selection_tokens) != len(set(selection_tokens))
                or any(not isinstance(token, str) or not _OPTION_TOKEN_RE.fullmatch(token) for token in selection_tokens)
                or not isinstance(token_to_option, Mapping)
                or set(token_to_option) != set(selection_tokens)
                or any(
                    token_to_option.get(token) != option_record
                    for token, option_record in zip(selection_tokens, option_records)
                )
            ):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A sealed provider field domain must contain aligned option records and selection tokens.",
                    details={"record_id": record_id, "field": field},
                )
            selected_option = token_to_option.get(quote)
        if isinstance(parsed_value, str) and parsed_value and not reviewed_override:
            if selected_option is None or selected_option.get("provider_value") != parsed_value:
                raise _response_error(
                    "COMMAND4_FIELD_VALUE_MISMATCH",
                    "A provider quote for a deterministically labelled field must equal the exact parsed value.",
                    details={"record_id": record_id, "field": field, "classification": "deterministic_label_mismatch"},
                )
            if selected_option is not None and selected_option.get("authority") != "source_quote":
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A deterministic parsed field cannot use a normalized reviewed option.",
                    details={"record_id": record_id, "field": field},
                )
            if selected_option is not None:
                return {
                    "value": selected_option.get("provider_value"),
                    "authority": selected_option.get("authority"),
                    "evidence": selected_option.get("evidence"),
                }
            return {"value": quote, "authority": "source_quote", "evidence": quote}
        if (
            isinstance(domain, Mapping)
            and selected_option is None
            and quote == COMMAND4_NOT_APPLICABLE_QUOTE
        ):
            raise _response_error(
                "COMMAND4_FIELD_VALUE_MISMATCH",
                "The not-applicable token is not allowed without an explicit sealed disposition.",
                details={
                    "record_id": record_id,
                    "field": field,
                    "classification": "not_applicable_not_proven",
                },
            )
        if isinstance(domain, Mapping) and selected_option is None:
            raise _response_error(
                "COMMAND4_EVIDENCE_INVALID",
                "A provider quote must select one exact option from its sealed field domain.",
                details={"record_id": record_id, "field": field, "classification": "domain_option_mismatch"},
            )
        # A prepared response always supplies a sealed option record.  The
        # direct fixture path retains its explicit-cue behavior for backwards
        # compatibility, but never infers authority from arbitrary prose.
        if selected_option is not None:
            authority = selected_option.get("authority")
            evidence = selected_option.get("evidence")
            if authority == "not_applicable":
                return {"value": None, "authority": "not_applicable", "evidence": None}
            if authority not in {"source_quote", "bounded_interpretation"}:
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A sealed field option has an unsupported authority.",
                    details={"record_id": record_id, "field": field},
                )
            if (
                not isinstance(evidence, str)
                or not evidence.strip()
                or evidence not in source_text
                or not _is_substantive_source_quote(evidence)
            ):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A sealed field option must carry substantive exact source evidence.",
                    details={"record_id": record_id, "field": field},
                )
            if authority == "source_quote" and evidence != selected_option.get("provider_value"):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_INVALID",
                    "A source-quote option must use its evidence as the provider value.",
                    details={"record_id": record_id, "field": field},
                )
            return {"value": selected_option.get("provider_value"), "authority": authority, "evidence": evidence}
        relevant_spans = _field_relevant_source_spans(source_text, field)
        not_applicable_allowed = field in _explicit_source_na_fields(source_text) and not relevant_spans
        if quote == COMMAND4_NOT_APPLICABLE_QUOTE:
            if not not_applicable_allowed:
                raise _response_error(
                    "COMMAND4_FIELD_VALUE_MISMATCH",
                    "The not-applicable token is not allowed without an explicit sealed disposition.",
                    details={
                        "record_id": record_id,
                        "field": field,
                        "classification": "not_applicable_not_proven",
                    },
                )
            return {"value": None, "authority": "not_applicable", "evidence": None}
        if quote not in source_text:
            raise _response_error(
                "COMMAND4_EVIDENCE_INVALID",
                "A provider field quote must be an exact same-record source substring.",
                details={"record_id": record_id, "field": field, "classification": "source_substring_mismatch"},
            )
        if not _is_substantive_source_quote(quote) or not any(quote in span for span in relevant_spans):
            raise _response_error(
                "COMMAND4_EVIDENCE_INVALID",
                "An unlabeled provider quote must be a substantive span relevant to its sealed field.",
                details={"record_id": record_id, "field": field, "classification": "field_relevance_mismatch"},
            )
        return {"value": quote, "authority": "source_quote", "evidence": quote}

    @staticmethod
    def _validate_dynamic_response_schema(prepared: Mapping[str, Any], response: Mapping[str, Any]) -> None:
        schema = prepared.get("response_schema")
        if not isinstance(schema, dict):
            raise _response_error(
                "COMMAND4_RESPONSE_SCHEMA_BUILD_INVALID",
                "The prepared Command 4 response schema is missing.",
            )
        try:
            Draft202012Validator(schema).validate(response)
        except ValidationError as exc:
            validator = exc.validator if isinstance(exc.validator, str) else None
            raise _response_error(
                "COMMAND4_RESPONSE_SCHEMA_CONTRACT_INVALID",
                "The provider response failed the sealed Command 4 response schema.",
                details={
                    "classification": "dynamic_schema_validation_failed",
                    "validator": validator,
                },
            ) from None

    def _validate_response_bindings(self, prepared: Mapping[str, Any], response: Mapping[str, Any]) -> None:
        expected_top = {"schema", "request_sha256", "source_workspace_sha256", "quotes", "signature_loadout_record_ids"}
        if set(response) != expected_top:
            raise _response_error("COMMAND4_RESPONSE_KEYS_INVALID", "The Command 4 authoring response has unexpected top-level keys.")
        if response.get("schema") != self.response_schema:
            raise _response_error(
                "COMMAND4_RESPONSE_SCHEMA_INVALID",
                "The Command 4 authoring response schema is unsupported.",
                details={
                    "classification": "response_schema_mismatch",
                    "expected_schema": self.response_schema,
                    "request_sha256": prepared.get("request_sha256"),
                },
            )
        if response.get("request_sha256") != prepared.get("request_sha256"):
            raise _response_error("COMMAND4_REQUEST_HASH_MISMATCH", "The response is bound to a different authoring request.")
        if response.get("source_workspace_sha256") != prepared.get("source_workspace_sha256"):
            raise _response_error("COMMAND4_WORKSPACE_HASH_MISMATCH", "The response is bound to a different sealed workspace.")

    def _validate_response(self, prepared: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_response_bindings(prepared, response)
        expected_ids = [str(row["record_id"]) for row in prepared["candidates"]]
        if prepared.get("candidate_ids") != expected_ids:
            raise _response_error(
                "COMMAND4_CANDIDATE_LEDGER_MISMATCH",
                "The prepared candidate order is not bound to its sealed unresolved ledger.",
            )
        expected_source_hashes = prepared.get("source_text_sha256_by_record_id")
        expected_provider_fields = prepared.get("provider_authorable_fields_by_record_id")
        expected_domains = prepared.get("provider_field_domains_by_record_id")
        expected_domain_bindings = prepared.get("provider_field_domain_bindings_by_record_id")
        if (
            not isinstance(expected_source_hashes, Mapping)
            or not isinstance(expected_provider_fields, Mapping)
            or not isinstance(expected_domains, Mapping)
            or not isinstance(expected_domain_bindings, Mapping)
            or set(expected_source_hashes) != set(expected_ids)
            or set(expected_provider_fields) != set(expected_ids)
            or set(expected_domains) != set(expected_ids)
            or set(expected_domain_bindings) != set(expected_ids)
        ):
            raise _response_error(
                "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                "The prepared field-domain bindings do not cover the sealed candidate ledger.",
            )
        for candidate in prepared["candidates"]:
            record_id = str(candidate["record_id"])
            source_text = _candidate_source(candidate)
            expected_source_hash = expected_source_hashes.get(record_id)
            if expected_source_hash != _hash_text(source_text):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                    "The prepared field-domain source hash is stale.",
                    details={"record_id": record_id},
                )
            provider_fields = tuple(_provider_authorable_fields(candidate))
            bound_provider_fields = expected_provider_fields.get(record_id)
            if not isinstance(bound_provider_fields, list) or bound_provider_fields != list(provider_fields):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                    "The prepared provider-field projection is stale or incomplete.",
                    details={"record_id": record_id},
                )
            domains = expected_domains.get(record_id)
            binding = expected_domain_bindings.get(record_id)
            if (
                not isinstance(domains, Mapping)
                or set(domains) != set(provider_fields)
                or not isinstance(binding, Mapping)
                or binding.get("record_id") != record_id
                or binding.get("source_text_sha256") != expected_source_hash
                or set(binding.get("fields", {})) != set(provider_fields)
                or not isinstance(binding.get("option_records"), Mapping)
                or set(binding.get("option_records", {})) != set(provider_fields)
                or not isinstance(binding.get("selection_tokens"), Mapping)
                or set(binding.get("selection_tokens", {})) != set(provider_fields)
                or not isinstance(binding.get("token_to_option"), Mapping)
                or set(binding.get("token_to_option", {})) != set(provider_fields)
            ):
                raise _response_error(
                    "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                    "The prepared field-domain binding is stale or incomplete.",
                    details={"record_id": record_id},
                )
            for field in provider_fields:
                domain = domains.get(field)
                bound_options = binding.get("fields", {}).get(field)
                bound_option_records = binding["option_records"].get(field)
                bound_tokens = binding["selection_tokens"].get(field)
                bound_token_options = binding["token_to_option"].get(field)
                fresh_domain = _provider_field_domain(candidate, field)
                if not isinstance(domain, Mapping) or dict(domain) != fresh_domain:
                    raise _response_error(
                        "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                        "The prepared field domain does not equal the freshly sealed domain.",
                        details={"record_id": record_id, "field": field},
                    )
                if (
                    not isinstance(domain.get("options"), list)
                    or not domain["options"]
                    or not isinstance(domain.get("option_records"), list)
                    or [record.get("provider_value") for record in domain["option_records"] if isinstance(record, Mapping)]
                    != domain["options"]
                    or bound_options != domain["options"]
                    or bound_option_records != domain["option_records"]
                    or bound_options != fresh_domain["options"]
                    or bound_option_records != fresh_domain["option_records"]
                    or bound_tokens != fresh_domain["selection_tokens"]
                    or bound_token_options != fresh_domain["token_to_option"]
                ):
                    raise _response_error(
                        "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                        "The prepared field-domain option binding is stale or incomplete.",
                        details={"record_id": record_id, "field": field},
                    )
                option_records = domain["option_records"]
                if any(
                    not isinstance(record, Mapping)
                    or set(record) != {"provider_value", "authority", "evidence"}
                    or record.get("authority") not in _PACKET_AUTHORITIES
                    or (
                        record.get("authority") == "not_applicable"
                        and (
                            record.get("provider_value") != COMMAND4_NOT_APPLICABLE_QUOTE
                            or record.get("evidence") is not None
                        )
                    )
                    or (
                        record.get("authority") == "source_quote"
                        and (
                            record.get("provider_value") != record.get("evidence")
                            or not isinstance(record.get("evidence"), str)
                            or record.get("evidence") not in source_text
                        )
                    )
                    or (
                        record.get("authority") == "bounded_interpretation"
                        and (
                            not isinstance(record.get("provider_value"), str)
                            or not record.get("provider_value").strip()
                            or not isinstance(record.get("evidence"), str)
                            or not record.get("evidence").strip()
                            or record.get("evidence") not in source_text
                        )
                    )
                    for record in option_records
                ):
                    raise _response_error(
                        "COMMAND4_PROVIDER_FIELD_DOMAIN_BINDING_INVALID",
                        "A prepared field-domain option record is stale or not source-bound.",
                        details={"record_id": record_id, "field": field},
                    )
            missing = candidate.get("missing_fields")
            missing = {str(value) for value in missing} if isinstance(missing, (list, tuple, set, frozenset)) else set()
            non_provider_missing = missing - set(COMMAND4_EXECUTION_FIELDS) - _SERVER_RESOLVED_MISSING_FIELDS
            if non_provider_missing:
                raise _response_error(
                    "COMMAND4_CANDIDATE_SOURCE_AUTHORITY_MISSING",
                    "A candidate with missing sealed source authority cannot be promoted by provider text.",
                    details={"record_id": candidate.get("record_id"), "missing_fields": sorted(non_provider_missing)},
                )
            provider_authorable = set(_provider_authorable_fields(candidate))
            unmarked_nulls = {
                field
                for field in _PROVIDER_AUTHORABLE_FIELDS
                if not _projection_is_resolved(_candidate_value(candidate, field)) and field not in provider_authorable
            }
            if unmarked_nulls:
                raise _response_error(
                    "COMMAND4_CANDIDATE_FIELDS_UNMARKED",
                    "A null provider-authorable candidate field must be explicitly marked for source authoring.",
                    details={"record_id": candidate.get("record_id"), "fields": sorted(unmarked_nulls)},
                )
            resources, resource_error = _strict_resource_projection(candidate)
            if resource_error is not None or resources is None:
                raise _response_error(
                    "COMMAND4_RESOURCE_PROJECTION_INVALID",
                    "Resource transactions require one exact standalone Cost line.",
                    details={"record_id": candidate.get("record_id"), "reason": resource_error},
                )
        quotes = response.get("quotes")
        expected_quote_count = sum(
            len(_provider_authorable_fields(candidate))
            for candidate in prepared["candidates"]
        )
        if not isinstance(quotes, list) or len(quotes) != expected_quote_count:
            raise _response_error(
                "COMMAND4_QUOTE_SET_INVALID",
                "The response must contain exactly one flat quote for each sealed provider field position.",
                details={
                    "classification": "quote_count_mismatch",
                    "expected_count": expected_quote_count,
                    "actual_count": len(quotes) if isinstance(quotes, list) else 0,
                },
            )
        validated: list[dict[str, Any]] = []
        quote_position = 0
        for candidate in prepared["candidates"]:
            record_id = str(candidate["record_id"])
            source_text = _candidate_source(candidate)
            source_hash = _hash_text(source_text)
            provider_authorable = tuple(_provider_authorable_fields(candidate))
            normalized_fields: dict[str, Any] = {}
            parsed_fields = _parse_explicit_fields(source_text)
            for field in provider_authorable:
                quote = quotes[quote_position]
                quote_position += 1
                normalized_fields[field] = self._validate_field_quote(
                    quote,
                    source_text,
                    field=field,
                    record_id=record_id,
                    parsed_fields=parsed_fields,
                    domain=prepared["provider_field_domains_by_record_id"][record_id][field],
                )
            runtime_kind = _candidate_runtime_kind(candidate)
            expected_action_type = _candidate_action_type(candidate)
            validated.append({
                "record_id": record_id,
                "source_text_sha256": source_hash,
                "runtime_kind": runtime_kind,
                "action_type": expected_action_type,
                "fields": normalized_fields,
                "candidate": candidate,
            })
        if quote_position != len(quotes):
            raise _response_error(
                "COMMAND4_QUOTE_SET_INVALID",
                "The response contained quotes outside the sealed candidate/field ledger.",
                details={
                    "classification": "quote_count_mismatch",
                    "expected_count": quote_position,
                    "actual_count": len(quotes),
                },
            )
        loadout = response.get("signature_loadout_record_ids")
        try:
            action_ids, loadout_min_items, loadout_max_items = _signature_loadout_projection(
                [row["candidate"] for row in validated],
                error_code="COMMAND4_SIGNATURE_LOADOUT_INVALID",
            )
        except FoundryError as exc:
            raise _response_error(
                "COMMAND4_SIGNATURE_LOADOUT_INVALID",
                "The sealed signature-loadout action domain is invalid.",
                details={"cause": exc.code, "cause_details": exc.details},
            ) from None
        if (
            prepared.get("signature_loadout_eligible_record_ids", action_ids) != action_ids
            or prepared.get("signature_loadout_min_items", loadout_min_items) != loadout_min_items
            or prepared.get("signature_loadout_max_items", loadout_max_items) != loadout_max_items
        ):
            raise _response_error(
                "COMMAND4_SIGNATURE_LOADOUT_INVALID",
                "The prepared signature-loadout domain is stale.",
                details={
                    "eligible_action_count": len(action_ids),
                    "min_items": loadout_min_items,
                    "max_items": loadout_max_items,
                },
            )
        if (
            not isinstance(loadout, list)
            or any(not isinstance(value, str) or not value.strip() for value in loadout)
            or not loadout_min_items <= len(loadout) <= loadout_max_items
            or len(loadout) != len(set(loadout))
        ):
            raise _response_error(
                "COMMAND4_SIGNATURE_LOADOUT_INVALID",
                "The signature loadout does not satisfy the sealed eligible-action bounds.",
                details={
                    "eligible_action_count": len(action_ids),
                    "min_items": loadout_min_items,
                    "max_items": loadout_max_items,
                },
            )
        action_id_set = set(action_ids)
        loadout_set = set(loadout)
        if loadout_set - action_id_set:
            raise _response_error(
                "COMMAND4_SIGNATURE_LOADOUT_INVALID",
                "Signature loadout IDs must be validated non-procedure action records.",
                details={"unknown_record_ids": sorted(loadout_set - action_id_set)},
            )
        if len(action_ids) < 10 and loadout_set != action_id_set:
            raise _response_error(
                "COMMAND4_SIGNATURE_LOADOUT_INVALID",
                "When fewer than 10 actions are eligible, every eligible action must be selected exactly once.",
                details={
                    "eligible_action_count": len(action_ids),
                    "missing_record_ids": sorted(action_id_set - loadout_set),
                },
            )
        return {
            "records": validated,
            "signature_loadout_record_ids": list(loadout),
            "execution_authority": True,
        }

    @staticmethod
    def _surface(
        prepared: Mapping[str, Any],
        validated: Mapping[str, Any],
        response_sha256: str,
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        expected_ids = prepared.get("candidate_ids")
        records = validated.get("records")
        if (
            not isinstance(expected_ids, list)
            or any(not isinstance(record_id, str) or not record_id.strip() for record_id in expected_ids)
            or not isinstance(records, list)
            or len(records) != len(expected_ids)
            or any(not isinstance(row, Mapping) for row in records)
            or [row.get("record_id") for row in records if isinstance(row, Mapping)] != expected_ids
        ):
            raise _response_error(
                "COMMAND4_SURFACE_LEDGER_ORDER_INVALID",
                "The assembled surface must retain the exact sealed unresolved ledger order.",
            )
        actions: list[dict[str, Any]] = []
        procedures: list[dict[str, Any]] = []
        ledger_order: list[dict[str, Any]] = []
        for ledger_ordinal, row in enumerate(records, start=1):
            candidate = row["candidate"]
            if (
                not isinstance(candidate, Mapping)
                or candidate.get("record_id") != expected_ids[ledger_ordinal - 1]
                or row.get("runtime_kind") != _candidate_runtime_kind(candidate)
            ):
                raise _response_error(
                    "COMMAND4_SURFACE_LEDGER_ORDER_INVALID",
                    "A surface record is not bound to its sealed ledger ordinal.",
                    details={"ledger_ordinal": ledger_ordinal},
                )
            action = {
                key: (
                    _candidate_value(candidate, key)
                    if key in _DERIVED_FIELDS or key in _SERVER_CLASSIFICATION_FIELDS or key not in row["fields"]
                    else deepcopy(row["fields"][key]["value"])
                )
                for key in COMMAND4_EXECUTION_FIELDS
            }
            action.update({
                "record_id": candidate.get("record_id"),
                "runtime_kind": row["runtime_kind"],
                "source_text_sha256": row["source_text_sha256"],
                "source_rule_ids": deepcopy(candidate.get("source_packet_ids") or []),
                "state_arrays": [],
                "authoring_field_packets": deepcopy(row["fields"]),
                "ledger_ordinal": ledger_ordinal,
                "mechanics_source": deepcopy(
                    prepared.get("locked_source_proof_by_record_id", {}).get(str(candidate.get("record_id")))
                    or candidate.get("source")
                    or candidate.get("mechanics_source")
                ),
            })
            ledger_order.append({
                "ledger_ordinal": ledger_ordinal,
                "record_id": candidate.get("record_id"),
                "action_id": action.get("action_id"),
                "runtime_kind": row["runtime_kind"],
            })
            if row["runtime_kind"] == "procedure":
                procedures.append(action)
            else:
                actions.append(action)
        surface_provenance = {
            "workspace_sha256": prepared["source_workspace_sha256"],
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
            "source_text_sha256_by_record_id": deepcopy(prepared["source_text_sha256_by_record_id"]),
        }
        if provenance is not None:
            surface_provenance.update(deepcopy(dict(provenance)))
        return {
            "schema_version": COMMAND4_SURFACE_SCHEMA,
            "status": "COMMAND4_ACTION_AUTHORITY_READY",
            "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
            "mechanical_authority": True,
            "execution_authority": bool(validated.get("execution_authority")),
            "global_combat_readiness": False,
            "workspace_authority": "C2B2_INPUT_ONLY",
            "project_id": prepared["project_id"],
            "source_workspace_sha256": prepared["source_workspace_sha256"],
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
            "source_text_sha256_by_record_id": deepcopy(prepared["source_text_sha256_by_record_id"]),
            "actions": actions,
            "procedures": procedures,
            "ledger_order": ledger_order,
            "signature_loadout_record_ids": deepcopy(validated["signature_loadout_record_ids"]),
            "unresolved": [],
            "provenance": surface_provenance,
        }

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(value), encoding="utf-8", newline="\n")

    @staticmethod
    def _validate_build_package_manifest(build_root: Path) -> dict[str, Any]:
        package_path = build_root / "PACKAGE_MANIFEST.json"
        if package_path.is_symlink() or not package_path.is_file():
            raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build package manifest is missing or not regular.")
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build package manifest is invalid.") from exc
        if not isinstance(package, Mapping) or not isinstance(package.get("files"), list):
            raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build package manifest has no valid file inventory.")
        declared: dict[str, tuple[str, int]] = {}
        for row in package["files"]:
            if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes"}:
                raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build package manifest contains a malformed file row.")
            relative = row.get("path")
            relative_path = Path(relative) if isinstance(relative, str) else None
            byte_count = row.get("bytes")
            if (
                relative_path is None
                or not relative
                or relative != relative_path.as_posix()
                or "\\" in relative
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
                or not _is_hash(row.get("sha256"))
                or type(byte_count) is not int
                or byte_count < 0
            ):
                raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build package manifest contains an unsafe file row.")
            if relative in declared:
                raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build package manifest contains duplicate file rows.")
            declared[relative] = (str(row["sha256"]), byte_count)
        actual: dict[str, tuple[str, int]] = {}
        for path in sorted(build_root.rglob("*")):
            if path.is_symlink():
                raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The Build tree contains a symlink.")
            if not path.is_file():
                continue
            relative = path.relative_to(build_root).as_posix()
            if relative in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}:
                continue
            actual[relative] = (sha256_file(path), path.stat().st_size)
        if declared != actual:
            raise FoundryError(
                "COMMAND4_WORKSPACE_MANIFEST_INVALID",
                "The Build package manifest does not exactly cover its files.",
                details={"missing": sorted(set(actual) - set(declared)), "extra": sorted(set(declared) - set(actual))},
            )
        return deepcopy(dict(package))

    @staticmethod
    def _refresh_workspace_receipts(root: Path, *, package_before_surface: Mapping[str, Any] | None = None) -> None:
        """Refresh independent Build and root checksum receipts in a copy."""

        build_root = root / "Build"
        build_ledger = build_root / "SHA256SUMS.txt"
        has_build_ledger = build_ledger.exists() or build_ledger.is_symlink()
        if has_build_ledger:
            if (
                build_root.is_symlink()
                or not build_root.is_dir()
                or build_ledger.is_symlink()
                or not build_ledger.is_file()
            ):
                raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", "The Build receipt tree is not regular.")
            package = (
                deepcopy(dict(package_before_surface))
                if isinstance(package_before_surface, Mapping)
                else Command4ProviderAuthoring._validate_build_package_manifest(build_root)
            )
            package_path = build_root / "PACKAGE_MANIFEST.json"
            package_value = deepcopy(dict(package))
            build_files: list[dict[str, Any]] = []
            for path in sorted(build_root.rglob("*")):
                if path.relative_to(build_root).as_posix() in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}:
                    continue
                if path.is_symlink():
                    raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", "The Build receipt tree contains a non-regular entry.")
                if not path.is_file():
                    continue
                build_files.append({
                    "path": path.relative_to(build_root).as_posix(),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                })
            package_value["files"] = build_files
            Command4ProviderAuthoring._write_json(package_path, package_value)
            build_hashes = {
                path.relative_to(build_root).as_posix(): sha256_file(path)
                for path in sorted(build_root.rglob("*"))
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.relative_to(build_root).as_posix() != "SHA256SUMS.txt"
                )
            }
            build_ledger.write_text(
                "\n".join(f"{digest}  {name}" for name, digest in sorted(build_hashes.items())) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            root_hashes = {
                path.relative_to(root).as_posix(): sha256_file(path)
                for path in sorted(root.rglob("*"))
                if path.is_file()
                and not path.is_symlink()
                and path.relative_to(root).as_posix() != "SHA256SUMS.txt"
                and not path.relative_to(root).as_posix().startswith("Build/")
            }
        else:
            root_hashes = {
                path.relative_to(root).as_posix(): sha256_file(path)
                for path in sorted(root.rglob("*"))
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.relative_to(root).as_posix() != "SHA256SUMS.txt"
                )
            }
        (root / "SHA256SUMS.txt").write_text(
            "\n".join(f"{digest}  {name}" for name, digest in sorted(root_hashes.items())) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _verify_workspace_checksums(root)

    @staticmethod
    def _overlay_documents(
        prepared: Mapping[str, Any],
        provider_result: Mapping[str, Any],
        response_sha256: str,
        overlay_id: str,
        provenance: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        audit = {
            "schema": "TianxiaFoundry.Command4ProviderAudit.v1",
            "purpose": COMMAND4_ACTION_AUTHORING_PURPOSE,
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
            "source_workspace_sha256": prepared["source_workspace_sha256"],
            "provider_id": provider_result.get("provider_id"),
            "execution_authority": True,
            "global_combat_readiness": False,
        }
        validation = {
            "schema": COMMAND4_EVIDENCE_SCHEMA,
            "valid": True,
            "execution_authority": True,
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
        }
        manifest = {
            "schema": COMMAND4_OVERLAY_SCHEMA,
            "overlay_id": overlay_id,
            "source_workspace_sha256": prepared["source_workspace_sha256"],
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
            "scope": "Command 4 action-authoring execution surface only; no global combat readiness claim.",
        }
        if provenance is not None:
            values = deepcopy(dict(provenance))
            audit.update(values)
            validation.update(deepcopy(values))
            manifest.update(deepcopy(values))
        return audit, validation, manifest

    @staticmethod
    def _validate_existing_deterministic_overlay(
        target: Path,
        source: Path,
        prepared: Mapping[str, Any],
        surface: Mapping[str, Any],
        response_sha256: str,
        overlay_id: str,
        *,
        source_package: Mapping[str, Any] | None,
    ) -> None:
        code = "COMMAND4_DETERMINISTIC_PROVENANCE_INVALID"
        _reject_recursive_nonregular(
            target,
            code=code,
            message="The existing deterministic overlay must contain regular files only.",
        )
        try:
            _verify_workspace_checksums(target)
        except FoundryError as exc:
            raise FoundryError(code, "The existing deterministic overlay receipts do not verify.", details={"cause": exc.code}) from exc

        source_files = _workspace_file_hashes(source, include_checksums=True)
        target_files = _workspace_file_hashes(target, include_checksums=True)
        has_build = (source / "Build/SHA256SUMS.txt").is_file()
        changed = {
            "Command_4/Complete_Action_Surface.json",
            "Command_4/Provider_Action_Authoring_Audit.json",
            "Validation/Command4_Provider.validation.json",
            "Command4_Provider_Overlay_Manifest.json",
            "SHA256SUMS.txt",
        }
        if has_build:
            changed.update({
                "Build/Complete_Action_Surface.json",
                "Build/PACKAGE_MANIFEST.json",
                "Build/SHA256SUMS.txt",
            })
        expected_files = set(source_files) | changed
        if set(target_files) != expected_files:
            raise FoundryError(code, "The existing deterministic overlay file inventory is not source-bound.")
        for name, digest in source_files.items():
            if name not in changed and target_files.get(name) != digest:
                raise FoundryError(code, "The existing deterministic overlay changed a source-bound file.", details={"path": name})

        if has_build:
            source_package = source_package or Command4ProviderAuthoring._validate_build_package_manifest(source / "Build")
            target_package = Command4ProviderAuthoring._validate_build_package_manifest(target / "Build")
            source_metadata = {key: value for key, value in source_package.items() if key != "files"}
            target_metadata = {key: value for key, value in target_package.items() if key != "files"}
            if target_metadata != source_metadata:
                raise FoundryError(code, "The existing deterministic Build package metadata is not source-bound.")

        expected_audit, expected_validation, expected_manifest = Command4ProviderAuthoring._overlay_documents(
            prepared,
            {"provider_id": COMMAND4_DETERMINISTIC_PROVIDER_ID},
            response_sha256,
            overlay_id,
            _DETERMINISTIC_PROVENANCE,
        )
        for relative, expected in {
            "Command_4/Provider_Action_Authoring_Audit.json": expected_audit,
            "Validation/Command4_Provider.validation.json": expected_validation,
            "Command4_Provider_Overlay_Manifest.json": expected_manifest,
        }.items():
            path = target / relative
            if path.is_symlink() or not path.is_file():
                raise FoundryError(code, "The existing deterministic overlay receipt is missing or not regular.")
            try:
                actual = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise FoundryError(code, "The existing deterministic overlay receipt is unreadable.") from exc
            if actual != expected or path.read_bytes() != _json_bytes(expected):
                raise FoundryError(code, "The existing deterministic overlay receipt is not bound to this result.", details={"path": relative})

        expected_surface_bytes = _json_bytes(surface)
        surface_paths = ["Command_4/Complete_Action_Surface.json"]
        if has_build:
            surface_paths.append("Build/Complete_Action_Surface.json")
        for relative in surface_paths:
            path = target / relative
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected_surface_bytes:
                raise FoundryError(code, "The existing deterministic action surface is not bound to this result.", details={"path": relative})

    @staticmethod
    def _append_evidence(
        output_root: Path,
        prepared: Mapping[str, Any],
        provider_result: Mapping[str, Any] | None,
        *,
        raw_response: str | None,
        validation: Mapping[str, Any],
        persist_raw: bool = False,
        provider_diagnostics: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Path:
        root = Path(output_root).resolve()
        base = root / "command4_authoring_evidence" / str(prepared["request_sha256"])
        base.mkdir(parents=True, exist_ok=True)
        attempt = 1
        while (base / f"attempt-{attempt:03d}").exists():
            attempt += 1
        evidence = base / f"attempt-{attempt:03d}"
        evidence.mkdir()
        response_sha = sha256_bytes(raw_response.encode("utf-8")) if isinstance(raw_response, str) else None
        receipt = _safe_receipt(provider_result or {}, request_sha256=str(prepared["request_sha256"]), response_sha256=response_sha)
        safe_diagnostics = _safe_provider_diagnostics(provider_diagnostics)
        if safe_diagnostics:
            receipt["provider_diagnostics"] = safe_diagnostics
        if provenance is not None:
            if dict(provenance) != _DETERMINISTIC_PROVENANCE:
                raise FoundryError(
                    "COMMAND4_DETERMINISTIC_PROVENANCE_INVALID",
                    "Deterministic evidence must use the server-owned provenance marker.",
                )
            receipt.update(deepcopy(dict(provenance)))
        Command4ProviderAuthoring._write_json(evidence / "receipt.json", receipt)
        validation_payload = dict(validation)
        if provenance is not None:
            validation_payload.update(deepcopy(dict(provenance)))
        Command4ProviderAuthoring._write_json(evidence / "validation.json", validation_payload)
        prompt_receipt = {
            "schema": "TianxiaFoundry.Command4ProviderPromptReceipt.v1",
            "project_id": prepared["project_id"],
            "request_sha256": prepared["request_sha256"],
            "source_workspace_sha256": prepared["source_workspace_sha256"],
            "candidate_count": len(prepared.get("candidate_ids") or prepared.get("candidates") or []),
            "total_provider_field_count": prepared["total_provider_field_count"],
            "deterministic_label_bound_field_count": prepared["deterministic_label_bound_field_count"],
            "unlabeled_provider_field_count": prepared["unlabeled_provider_field_count"],
            "request_bytes": prepared["request_bytes"],
            **({"provider_request_sha256": prepared["provider_request_sha256"]} if prepared.get("provider_request_sha256") else {}),
        }
        if provenance is not None:
            prompt_receipt.update(deepcopy(dict(provenance)))
        Command4ProviderAuthoring._write_json(evidence / "prompt.json", prompt_receipt)
        response_summary = {
            "schema": "TianxiaFoundry.Command4ProviderResponseSummary.v1",
            "present": isinstance(raw_response, str),
            "response_sha256": response_sha,
            "response_bytes": len(raw_response.encode("utf-8")) if isinstance(raw_response, str) else 0,
            "raw_json_object": bool(isinstance(raw_response, str) and _raw_json_object(raw_response)),
        }
        if provenance is not None:
            response_summary.update(deepcopy(dict(provenance)))
        Command4ProviderAuthoring._write_json(evidence / "response_summary.json", response_summary)
        if persist_raw and isinstance(raw_response, str):
            (evidence / "raw_response.json").write_text(raw_response, encoding="utf-8", newline="\n")
        return evidence

    @staticmethod
    def _write_overlay(
        base_workspace: Path,
        output_root: Path,
        prepared: Mapping[str, Any],
        surface: Mapping[str, Any],
        provider_result: Mapping[str, Any],
        response_sha256: str,
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> Path:
        # Re-check the sealed base after the provider round-trip and before
        # creating any output.  A refreshed internal checksum ledger is not
        # enough: the workspace identity bound into the prompt must still be
        # exactly the one that was prepared.
        _reject_recursive_nonregular(
            base_workspace,
            code="COMMAND4_WORKSPACE_CHECKSUMS_INVALID",
            message="The sealed workspace must contain regular files only.",
        )
        _verify_workspace_checksums(base_workspace)
        source_package: Mapping[str, Any] | None = None
        if (base_workspace / "Build/SHA256SUMS.txt").is_file():
            source_package = Command4ProviderAuthoring._validate_build_package_manifest(base_workspace / "Build")
        expected_workspace_sha256 = prepared.get("source_workspace_sha256")
        actual_workspace_sha256 = _workspace_sha256(base_workspace)
        if actual_workspace_sha256 != expected_workspace_sha256:
            raise FoundryError(
                "COMMAND4_WORKSPACE_STALE",
                "The sealed Factory workspace changed before the authoring overlay could be written.",
                details={"expected": expected_workspace_sha256, "actual": actual_workspace_sha256},
            )
        if provenance is not None and dict(provenance) != _DETERMINISTIC_PROVENANCE:
            raise FoundryError(
                "COMMAND4_DETERMINISTIC_PROVENANCE_INVALID",
                "Deterministic overlays must use the server-owned provenance marker.",
            )
        overlay_identity = {
            "source_workspace_sha256": prepared["source_workspace_sha256"],
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
        }
        if provenance is not None:
            # Keep legacy provider overlay IDs stable while separating a
            # deterministic overlay with the same canonical response hashes.
            overlay_identity["resolution_mode"] = COMMAND4_DETERMINISTIC_RESOLUTION_MODE
        overlay_id = sha256_json(overlay_identity)
        overlays = Path(output_root).resolve() / "command4_authoring_overlays"
        overlays.mkdir(parents=True, exist_ok=True)
        target = overlays / overlay_id
        if target.exists() or target.is_symlink():
            if provenance is not None:
                Command4ProviderAuthoring._validate_existing_deterministic_overlay(
                    target,
                    base_workspace,
                    prepared,
                    surface,
                    response_sha256,
                    overlay_id,
                    source_package=source_package,
                )
            return target
        staging = overlays / f".{overlay_id}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        try:
            shutil.copytree(base_workspace, staging)
            copied_workspace_sha256 = _workspace_sha256(staging)
            current_workspace_sha256 = _workspace_sha256(base_workspace)
            if copied_workspace_sha256 != actual_workspace_sha256 or current_workspace_sha256 != expected_workspace_sha256:
                raise FoundryError(
                    "COMMAND4_WORKSPACE_COPY_INVALID",
                    "The copied Command 4 base workspace no longer matches its prepared sealed identity.",
                    details={
                        "expected": expected_workspace_sha256,
                        "actual": current_workspace_sha256,
                        "copied": copied_workspace_sha256,
                    },
                )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        command4 = staging / "Command_4"
        Command4ProviderAuthoring._write_json(command4 / "Complete_Action_Surface.json", surface)
        build_ledger = staging / "Build/SHA256SUMS.txt"
        if build_ledger.exists() or build_ledger.is_symlink():
            staged_package = Command4ProviderAuthoring._validate_build_package_manifest(staging / "Build")
            if source_package is None or staged_package != source_package:
                raise FoundryError("COMMAND4_WORKSPACE_MANIFEST_INVALID", "The copied Build package manifest is not source-bound.")
            build_surface = staging / "Build/Complete_Action_Surface.json"
            if build_surface.is_symlink() or (build_surface.exists() and not build_surface.is_file()):
                raise FoundryError("COMMAND4_WORKSPACE_CHECKSUMS_INVALID", "The Build action surface is not a regular file.")
            Command4ProviderAuthoring._write_json(build_surface, surface)
        audit, validation, manifest = Command4ProviderAuthoring._overlay_documents(
            prepared,
            provider_result,
            response_sha256,
            overlay_id,
            provenance,
        )
        Command4ProviderAuthoring._write_json(command4 / "Provider_Action_Authoring_Audit.json", audit)
        Command4ProviderAuthoring._write_json(staging / "Validation/Command4_Provider.validation.json", validation)
        Command4ProviderAuthoring._write_json(staging / "Command4_Provider_Overlay_Manifest.json", manifest)
        Command4ProviderAuthoring._refresh_workspace_receipts(staging, package_before_surface=source_package)
        staging.replace(target)
        return target

    def author(self, project_id: str, provider: Any, output_root: Path) -> dict[str, Any]:
        """Make one explicit provider call, validate it, and optionally overlay it."""

        prepared = self.prepare(project_id)
        settings = _provider_settings(provider)
        provider_id = settings.get("provider_id") if isinstance(settings, Mapping) else None
        if provider_id not in COMMAND4_AUTHORING_PROVIDER_IDS:
            raise FoundryError(
                "COMMAND4_PROVIDER_LOCAL_ONLY",
                "Command 4 action authoring is restricted to the configured local provider or the Agent bridge.",
                details={"provider_id": provider_id, "allowed_provider_ids": sorted(COMMAND4_AUTHORING_PROVIDER_IDS)},
            )
        exact_request = canonical_command4_wire_bytes(
            prepared["prompt_text"],
            system_message=prepared["system_message"],
            settings=settings,
            temperature=0,
            response_schema=prepared["response_schema"],
            response_schema_name=prepared["response_schema_name"],
            response_schema_max_output_tokens=LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
        )
        evidence_prepared = dict(prepared)
        evidence_prepared["request_bytes"] = len(exact_request)
        evidence_prepared["provider_request_sha256"] = sha256_bytes(exact_request)
        if len(exact_request) > self.max_request_bytes:
            validation = {"valid": False, "code": "COMMAND4_PROVIDER_REQUEST_TOO_LARGE", "request_bytes": len(exact_request), "max_request_bytes": self.max_request_bytes}
            evidence = self._append_evidence(Path(output_root), evidence_prepared, None, raw_response=None, validation=validation)
            raise FoundryError(validation["code"], "The exact Command 4 provider request exceeds its canonical wire cap.", details={**validation, "evidence": str(evidence)}, status_code=413)
        try:
            provider_result = provider.complete_json(
                prompt_text=prepared["prompt_text"],
                system_message=prepared["system_message"],
                purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
                max_request_bytes=self.max_request_bytes,
                temperature=0,
                expected_request_sha256=evidence_prepared["provider_request_sha256"],
                response_schema=prepared["response_schema"],
                response_schema_name=prepared["response_schema_name"],
                response_schema_max_output_tokens=LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:
            safe_diagnostics = _safe_provider_diagnostics(getattr(exc, "details", None))
            validation = {
                "valid": False,
                "code": getattr(exc, "code", "COMMAND4_PROVIDER_CALL_FAILED"),
                "message": "The Command 4 provider call failed before a valid response was received.",
            }
            if safe_diagnostics:
                validation["provider_diagnostics"] = safe_diagnostics
            evidence = self._append_evidence(
                Path(output_root),
                evidence_prepared,
                None,
                raw_response=None,
                validation=validation,
                provider_diagnostics=safe_diagnostics,
            )
            if isinstance(exc, FoundryError):
                raise FoundryError(
                    exc.code,
                    exc.message,
                    details={"evidence": str(evidence), "cause": safe_diagnostics},
                    status_code=exc.status_code,
                ) from exc
            raise FoundryError(validation["code"], "The Command 4 provider call failed.", details={"evidence": str(evidence)}) from exc
        try:
            value, raw_response = self._parse_provider_response(provider_result)
        except FoundryError as exc:
            raw_response = provider_result.get("response_text") if isinstance(provider_result, Mapping) and isinstance(provider_result.get("response_text"), str) else None
            evidence = self._append_evidence(Path(output_root), evidence_prepared, provider_result, raw_response=raw_response, validation={"valid": False, "code": exc.code, "message": exc.message, "details": exc.details})
            raise FoundryError(exc.code, exc.message, details={"evidence": str(evidence), "cause": exc.details}, status_code=exc.status_code) from exc
        response_sha256 = sha256_bytes(raw_response.encode("utf-8")) if isinstance(raw_response, str) else sha256_json(value)
        supplied_completion_hash = provider_result.get("completion_sha256") if isinstance(provider_result, Mapping) else None
        if supplied_completion_hash is not None and supplied_completion_hash != response_sha256:
            validation = {
                "valid": False,
                "code": "COMMAND4_COMPLETION_HASH_MISMATCH",
                "message": "The provider completion hash does not match the returned raw JSON content.",
                "response_sha256": response_sha256,
            }
            evidence = self._append_evidence(Path(output_root), evidence_prepared, provider_result, raw_response=raw_response, validation=validation)
            raise FoundryError(validation["code"], validation["message"], details={"evidence": str(evidence), "actual": response_sha256, "supplied": supplied_completion_hash})
        try:
            self._validate_response_bindings(prepared, value)
            self._validate_dynamic_response_schema(prepared, value)
            validated = self._validate_response(prepared, value)
        except FoundryError as exc:
            validation = {"valid": False, "code": exc.code, "message": exc.message, "details": exc.details}
            evidence = self._append_evidence(Path(output_root), evidence_prepared, provider_result, raw_response=raw_response, validation=validation)
            raise FoundryError(exc.code, exc.message, details={"evidence": str(evidence), "cause": exc.details}, status_code=exc.status_code) from exc
        validation = {"valid": True, "execution_authority": True, "records": len(validated["records"]), "response_sha256": response_sha256}
        evidence = self._append_evidence(Path(output_root), evidence_prepared, provider_result, raw_response=raw_response, validation=validation, persist_raw=True)
        surface = self._surface(prepared, validated, response_sha256)
        overlay = self._write_overlay(Path(prepared["workspace_path"]), Path(output_root), prepared, surface, provider_result, response_sha256)
        return {
            "valid": True,
            "execution_authority": True,
            "evidence_path": str(evidence),
            "overlay_path": str(overlay),
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
            "surface": surface,
        }

    def materialize_deterministic(self, project_id: str, output_root: Path) -> dict[str, Any]:
        """Materialize a response whose sealed choices are all singletons.

        This is a provider-free server operation, not an alternate authoring
        authority.  It constructs the same response shape as ``author`` and
        runs the same binding, schema, validation, surface, evidence, and
        overlay paths.  It is admitted only when no provider choice is needed.
        """

        prepared = self.prepare(project_id)
        response = self._deterministic_response(prepared)
        parsed_response, raw_response = self._parse_provider_response({"value": response})
        response_sha256 = sha256_bytes(raw_response.encode("utf-8"))
        self._validate_response_bindings(prepared, parsed_response)
        self._validate_dynamic_response_schema(prepared, parsed_response)
        validated = self._validate_response(prepared, parsed_response)
        provenance = deepcopy(_DETERMINISTIC_PROVENANCE)
        deterministic_result = deepcopy(provenance)
        validation = {
            "valid": True,
            "execution_authority": True,
            "records": len(validated["records"]),
            "response_sha256": response_sha256,
        }
        evidence = self._append_evidence(
            Path(output_root),
            prepared,
            deterministic_result,
            raw_response=raw_response,
            validation=validation,
            persist_raw=True,
            provenance=provenance,
        )
        surface = self._surface(prepared, validated, response_sha256, provenance=provenance)
        overlay = self._write_overlay(
            Path(prepared["workspace_path"]),
            Path(output_root),
            prepared,
            surface,
            deterministic_result,
            response_sha256,
            provenance=provenance,
        )
        return {
            "valid": True,
            "execution_authority": True,
            "provider_id": COMMAND4_DETERMINISTIC_PROVIDER_ID,
            "resolution_mode": COMMAND4_DETERMINISTIC_RESOLUTION_MODE,
            "provider_calls": 0,
            "model": None,
            "usage": deepcopy(provenance["usage"]),
            "evidence_path": str(evidence),
            "overlay_path": str(overlay),
            "request_sha256": prepared["request_sha256"],
            "response_sha256": response_sha256,
            "surface": surface,
        }


Command4ProviderAuthoringService = Command4ProviderAuthoring


__all__ = [
    "COMMAND4_AUTHORING_PROVIDER_IDS",
    "COMMAND4_EXECUTION_FIELDS",
    "COMMAND4_LOCAL_PROVIDER_IDS",
    "COMMAND4_MAX_REQUEST_BYTES",
    "COMMAND4_NOT_APPLICABLE_QUOTE",
    "COMMAND4_DETERMINISTIC_CHOICE_REQUIRED",
    "COMMAND4_DETERMINISTIC_PROVIDER_ID",
    "COMMAND4_DETERMINISTIC_RESOLUTION_MODE",
    "COMMAND4_PROVIDER_RESPONSE_SCHEMA",
    "COMMAND4_PROVIDER_RESPONSE_SCHEMA_NAME",
    "COMMAND4_SURFACE_SCHEMA",
    "COMMAND4_SYSTEM_MESSAGE",
    "Command4ProviderAuthoring",
    "Command4ProviderAuthoringService",
    "_field_relevant_source_spans",
    "_provider_field_default_quote",
    "_provider_field_domain",
    "_provider_field_domain_partition",
    "build_command4_response_schema",
    "canonical_command4_wire_bytes",
]
