"""Strict, deterministic contracts for the Stage A creative controller.

The controller deliberately keeps its contract layer small.  It uses the
Factory's existing canonical JSON and SHA-256 implementation, but never
imports a provider, a database, or a production character-creation service.
"""

from __future__ import annotations

from copy import deepcopy
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json


HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX24 = re.compile(r"^[0-9a-f]{24}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")

INTENT_SCHEMA = "TianxiaFoundry.CreativeIntent.v1"
CREATIVE_CONTROLLER_STATE_SCHEMA = "TianxiaFoundry.CreativeControllerState.v1"


class CreativeControllerError(FoundryError):
    """A fail-closed, transport-independent Stage A error."""


def fail(code: str, message: str, *, details: Any = None, status_code: int = 400) -> None:
    raise CreativeControllerError(code, message, details=details, status_code=status_code)


def canonical_bytes(value: Any) -> bytes:
    """Return the exact UTF-8 bytes used by Factory semantic hashes."""

    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Hash a JSON value using the existing Factory canonical convention."""

    return sha256_bytes(canonical_bytes(value))


def without_hash(value: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    """Copy an object while omitting exactly its self-hash field."""

    if not isinstance(value, Mapping):
        fail("DCC_SCHEMA_TYPE", "A self-hashed value must be an object.")
    result = dict(value)
    result.pop(hash_field, None)
    return result


def self_hash(value: Mapping[str, Any], hash_field: str) -> str:
    return sha256_json(without_hash(value, hash_field))


def seal(value: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    """Return a fresh self-hashed mapping; the input is never modified."""

    unsigned = without_hash(value, hash_field)
    unsigned[hash_field] = sha256_json(unsigned)
    return unsigned


def validate_self_hash(value: Mapping[str, Any], hash_field: str, *, code: str = "DCC_SELF_HASH_INVALID") -> None:
    if not isinstance(value, Mapping):
        fail(code, f"{hash_field} must seal an object.")
    actual = value.get(hash_field)
    if not isinstance(actual, str) or not HEX64.fullmatch(actual):
        fail(code, f"{hash_field} must be a lowercase SHA-256 digest.")
    expected = self_hash(value, hash_field)
    if actual != expected:
        fail(code, f"{hash_field} does not match the canonical object.", details={"expected": expected, "actual": actual})


def normalized_text(value: str) -> str:
    """The only text normalization used by bounded preference lists."""

    if not isinstance(value, str):
        fail("DCC_SCHEMA_TYPE", "Normalized text must be a string.")
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def require_exact_keys(value: Mapping[str, Any], required: Iterable[str], optional: Iterable[str] = (), *, path: str = "object") -> None:
    """Reject missing and unknown keys at a contract boundary."""

    if not isinstance(value, Mapping):
        fail("DCC_SCHEMA_TYPE", f"{path} must be an object.")
    required_set = set(required)
    optional_set = set(optional)
    actual = set(value)
    missing = sorted(required_set - actual)
    unknown = sorted(actual - required_set - optional_set, key=str)
    if missing or unknown:
        fail(
            "DCC_SCHEMA_UNKNOWN_FIELD" if unknown else "DCC_SCHEMA_MISSING_FIELD",
            f"{path} must have the exact contract keys.",
            details={"missing": missing, "unknown": unknown},
        )


def require_type(value: Any, expected: type | tuple[type, ...], *, path: str) -> Any:
    # bool is an int subclass, but never represents an integer contract value.
    expected_types = (expected,) if isinstance(expected, type) else expected
    if int in expected_types and isinstance(value, bool):
        fail("DCC_SCHEMA_TYPE", f"{path} must be an integer.")
    if not isinstance(value, expected):
        fail("DCC_SCHEMA_TYPE", f"{path} has the wrong type.", details={"expected": str(expected)})
    return value


def require_string(value: Any, *, path: str, nonempty: bool = True, max_length: int | None = None) -> str:
    result = require_type(value, str, path=path)
    if nonempty and not result:
        fail("DCC_SCHEMA_VALUE", f"{path} must not be empty.")
    if max_length is not None and len(result) > max_length:
        fail("DCC_SCHEMA_LIMIT", f"{path} exceeds its length limit.", details={"maximum": max_length})
    return result


def require_digest(value: Any, *, path: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    result = require_string(value, path=path)
    if not HEX64.fullmatch(result):
        fail("DCC_SCHEMA_VALUE", f"{path} must be a lowercase SHA-256 digest.")
    return result


def require_identifier(value: Any, *, path: str, prefix: str | None = None) -> str:
    result = require_string(value, path=path)
    if prefix is not None:
        if not result.startswith(prefix) or not HEX24.fullmatch(result[len(prefix):]):
            fail("DCC_SCHEMA_VALUE", f"{path} must be a 24-hex opaque {prefix} identifier.")
    elif not _ID.fullmatch(result):
        fail("DCC_SCHEMA_VALUE", f"{path} must be a lowercase opaque identifier.")
    return result


def require_enum(value: Any, choices: Iterable[str], *, path: str) -> str:
    result = require_string(value, path=path)
    allowed = set(choices)
    if result not in allowed:
        fail("DCC_SCHEMA_ENUM", f"{path} contains an unsupported vocabulary value.", details={"value": result, "allowed": sorted(allowed)})
    return result


def require_list(value: Any, *, path: str, max_length: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        fail("DCC_SCHEMA_TYPE", f"{path} must be an array.")
    if max_length is not None and len(value) > max_length:
        fail("DCC_SCHEMA_LIMIT", f"{path} exceeds its item limit.", details={"maximum": max_length})
    return value


def require_unique_text_list(value: Any, *, path: str, max_length: int = 12, max_item_length: int = 120) -> list[str]:
    rows = require_list(value, path=path, max_length=max_length)
    result: list[str] = []
    normalized: set[str] = set()
    for index, item in enumerate(rows):
        text = require_string(item, path=f"{path}[{index}]", max_length=max_item_length)
        key = normalized_text(text)
        if key in normalized:
            fail("DCC_SCHEMA_DUPLICATE", f"{path} must be duplicate-free after Unicode normalization.", details={"index": index})
        normalized.add(key)
        result.append(text)
    return result


def require_digest_list(value: Any, *, path: str) -> list[str]:
    rows = require_list(value, path=path)
    result = [require_digest(item, path=f"{path}[{index}]") for index, item in enumerate(rows)]
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must not contain duplicate digests.")
    return [item for item in result if item is not None]


class IdentifierRegistry:
    """Collision guard for shortened, content-derived identifiers."""

    def __init__(self) -> None:
        self._full_digests: dict[tuple[str, str], str] = {}

    def register(self, prefix: str, full_digest: str, *, shortened_id: str | None = None) -> str:
        if not isinstance(prefix, str) or not prefix.endswith("."):
            fail("DCC_SCHEMA_VALUE", "An identifier namespace must end with a dot.")
        if not isinstance(full_digest, str) or not HEX64.fullmatch(full_digest):
            fail("DCC_SCHEMA_VALUE", "An identifier derivation must be a lowercase SHA-256 digest.")
        identifier = shortened_id or f"{prefix}{full_digest[:24]}"
        require_identifier(identifier, path="identifier", prefix=prefix)
        key = (prefix, identifier)
        previous = self._full_digests.get(key)
        if previous is not None and previous != full_digest:
            fail(
                "DCC_ID_TRUNCATION_COLLISION",
                "A shortened identifier maps to more than one full derivation digest.",
                details={"identifier": identifier, "existing_full_digest": previous, "incoming_full_digest": full_digest},
                status_code=409,
            )
        self._full_digests[key] = full_digest
        return identifier

    def full_digest_for(self, identifier: str) -> str | None:
        if not isinstance(identifier, str):
            return None
        prefix = identifier.rsplit(".", 1)[0] + "." if "." in identifier else ""
        return self._full_digests.get((prefix, identifier))


def register_truncation_collision_guard(registry: IdentifierRegistry, prefix: str, full_digest: str, *, shortened_id: str | None = None) -> str:
    return registry.register(prefix, full_digest, shortened_id=shortened_id)


def domain_digest(domain: str, payload: Any) -> str:
    require_string(domain, path="domain")
    return sha256_bytes(canonical_bytes({"domain": domain, "payload": payload}))


def derive_identifier(prefix: str, domain: str, payload: Any, *, registry: IdentifierRegistry | None = None) -> tuple[str, str]:
    full_digest = domain_digest(domain, payload)
    identifier = f"{prefix}{full_digest[:24]}"
    (registry or IdentifierRegistry()).register(prefix, full_digest, shortened_id=identifier)
    return identifier, full_digest


def derive_intent_identifier(intent_without_ids: Mapping[str, Any], *, registry: IdentifierRegistry | None = None) -> tuple[str, str, str]:
    seed = domain_digest("dcc.intent.seed.v1", intent_without_ids)
    identifier, full_digest = derive_identifier("dcc.intent.", "dcc.intent.id.v1", {"intent_seed_sha256": seed}, registry=registry)
    return identifier, full_digest, seed


def derive_intent_id(intent_without_ids: Mapping[str, Any]) -> str:
    return derive_intent_identifier(intent_without_ids)[0]


def derive_controller_identifier(run_id: str, request_sha256: str, controller_version_sha256: str, selected_ai_identity_sha256: str, *, registry: IdentifierRegistry | None = None) -> tuple[str, str]:
    require_digest(selected_ai_identity_sha256, path="selected_ai_identity_sha256")
    payload = {"run_id": run_id, "request_sha256": request_sha256, "controller_version_sha256": controller_version_sha256, "selected_ai_identity_sha256": selected_ai_identity_sha256}
    return derive_identifier(
        "dcc.controller.",
        "dcc.controller.id.v1",
        payload,
        registry=registry,
    )


def derive_controller_id(run_id: str, request_sha256: str, controller_version_sha256: str, selected_ai_identity_sha256: str) -> str:
    return derive_controller_identifier(run_id, request_sha256, controller_version_sha256, selected_ai_identity_sha256)[0]


def derive_manifest_context_digest(binding: Mapping[str, Any], manifest_kind: str, decision_scope: str, page_request: Mapping[str, Any]) -> str:
    return domain_digest(
        "dcc.manifest.context.v1",
        {"binding": binding, "manifest_kind": manifest_kind, "decision_scope": decision_scope, "page_request": page_request},
    )


def derive_manifest_identifier(manifest_context_sha256: str, ordered_legal_plan_sha256s: Sequence[str], *, registry: IdentifierRegistry | None = None) -> tuple[str, str]:
    return derive_identifier(
        "dcc.manifest.",
        "dcc.manifest.id.v1",
        {"manifest_context_sha256": manifest_context_sha256, "ordered_legal_plan_sha256s": list(ordered_legal_plan_sha256s)},
        registry=registry,
    )


def derive_manifest_id(manifest_context_sha256: str, ordered_legal_plan_sha256s: Sequence[str]) -> str:
    return derive_manifest_identifier(manifest_context_sha256, ordered_legal_plan_sha256s)[0]


def derive_option_identifier(manifest_context_sha256: str, legal_plan_sha256: str, manifest_kind: str, decision_scope: str, *, registry: IdentifierRegistry | None = None) -> tuple[str, str]:
    return derive_identifier(
        "dcc.opt.",
        "dcc.option.id.v1",
        {"manifest_context_sha256": manifest_context_sha256, "legal_plan_sha256": legal_plan_sha256, "manifest_kind": manifest_kind, "decision_scope": decision_scope},
        registry=registry,
    )


def derive_option_id(manifest_context_sha256: str, legal_plan_sha256: str, manifest_kind: str, decision_scope: str) -> str:
    return derive_option_identifier(manifest_context_sha256, legal_plan_sha256, manifest_kind, decision_scope)[0]


def derive_continuation_identifier(manifest_context_sha256: str, next_page_index: int, already_visible_plan_sha256s: Sequence[str], ranked_view_sha256: str, *, registry: IdentifierRegistry | None = None) -> tuple[str, str]:
    return derive_identifier(
        "dcc.more.",
        "dcc.continuation.id.v1",
        {"manifest_context_sha256": manifest_context_sha256, "next_page_index": next_page_index, "already_visible_plan_sha256s": list(already_visible_plan_sha256s), "ranked_view_sha256": ranked_view_sha256},
        registry=registry,
    )


def derive_continuation_id(manifest_context_sha256: str, next_page_index: int, already_visible_plan_sha256s: Sequence[str], ranked_view_sha256: str) -> str:
    return derive_continuation_identifier(manifest_context_sha256, next_page_index, already_visible_plan_sha256s, ranked_view_sha256)[0]


def derive_event_identifier(controller_id: str, ordinal: int, previous_event_sha256: str | None, event_type: str, subject_sha256: str, *, registry: IdentifierRegistry | None = None) -> tuple[str, str]:
    return derive_identifier(
        "dcc.event.",
        "dcc.event.id.v1",
        {"controller_id": controller_id, "ordinal": ordinal, "previous_event_sha256": previous_event_sha256, "event_type": event_type, "subject_sha256": subject_sha256},
        registry=registry,
    )


def derive_event_id(controller_id: str, ordinal: int, previous_event_sha256: str | None, event_type: str, subject_sha256: str) -> str:
    return derive_event_identifier(controller_id, ordinal, previous_event_sha256, event_type, subject_sha256)[0]


def _validate_list_fields(creative: Mapping[str, Any], fields: Sequence[str], *, path: str) -> None:
    for field in fields:
        require_unique_text_list(creative[field], path=f"{path}.{field}")


def validate_creative_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached CreativeIntent.v1 projection."""

    require_exact_keys(
        intent,
        {"schema", "intent_id", "intent_revision", "binding", "source", "identity", "creative", "controlled_preferences", "activation", "intent_sha256"},
        path="intent",
    )
    if intent.get("schema") != INTENT_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "intent.schema is not CreativeIntent.v1.")
    require_identifier(intent["intent_id"], path="intent.intent_id", prefix="dcc.intent.")
    revision = require_type(intent["intent_revision"], int, path="intent.intent_revision")
    if revision < 1:
        fail("DCC_SCHEMA_VALUE", "intent.intent_revision must be positive.")

    binding = intent["binding"]
    require_exact_keys(binding, {"project_id", "project_revision", "request_sha256", "content_snapshot_sha256", "content_lock_hash", "character_state_sha256"}, path="intent.binding")
    require_string(binding["project_id"], path="intent.binding.project_id")
    if require_type(binding["project_revision"], int, path="intent.binding.project_revision") < 0:
        fail("DCC_SCHEMA_VALUE", "intent.binding.project_revision cannot be negative.")
    for key in ("request_sha256", "content_snapshot_sha256", "content_lock_hash", "character_state_sha256"):
        require_digest(binding[key], path=f"intent.binding.{key}")

    source = intent["source"]
    require_exact_keys(source, {"kind", "provider_id", "provider_response_sha256"}, path="intent.source")
    require_enum(source["kind"], {"provider", "owner", "owner_edited_provider"}, path="intent.source.kind")
    require_string(source["provider_id"], path="intent.source.provider_id")
    require_digest(source["provider_response_sha256"], path="intent.source.provider_response_sha256")

    identity = intent["identity"]
    require_exact_keys(identity, {"suggested_name", "suggested_title", "one_sentence_concept"}, path="intent.identity")
    require_string(identity["suggested_name"], path="intent.identity.suggested_name", max_length=240)
    require_string(identity["suggested_title"], path="intent.identity.suggested_title", max_length=120)
    require_string(identity["one_sentence_concept"], path="intent.identity.one_sentence_concept", max_length=2000)

    creative = intent["creative"]
    creative_keys = {"theme_terms", "narrative_cues", "combat_fantasy", "desired_roles", "priority_order", "desired_synergies", "acceptable_tradeoffs", "avoidances", "complexity_preference", "visual_cues"}
    require_exact_keys(creative, creative_keys, path="intent.creative")
    _validate_list_fields(creative, ("theme_terms", "narrative_cues", "desired_roles", "priority_order", "desired_synergies", "acceptable_tradeoffs", "avoidances", "visual_cues"), path="intent.creative")
    require_string(creative["combat_fantasy"], path="intent.creative.combat_fantasy", max_length=2000)
    require_enum(creative["complexity_preference"], {"simple", "moderate", "complex"}, path="intent.creative.complexity_preference")

    preferences = intent["controlled_preferences"]
    require_exact_keys(preferences, {"must_include", "must_exclude", "soft_prefer", "soft_avoid"}, path="intent.controlled_preferences")
    total_preferences = 0
    for field in ("must_include", "must_exclude", "soft_prefer", "soft_avoid"):
        rows = require_list(preferences[field], path=f"intent.controlled_preferences.{field}", max_length=16)
        total_preferences += len(rows)
        for index, predicate in enumerate(rows):
            require_exact_keys(predicate, {"kind", "value"}, path=f"intent.controlled_preferences.{field}[{index}]")
            require_enum(predicate["kind"], {"role_tag", "theme_tag", "capability_family", "tradeoff_code", "complexity_band"}, path=f"intent.controlled_preferences.{field}[{index}].kind")
            require_string(predicate["value"], path=f"intent.controlled_preferences.{field}[{index}].value", max_length=120)
    if total_preferences > 16:
        fail("DCC_SCHEMA_LIMIT", "controlled_preferences contains too many entries.")

    activation = intent["activation"]
    require_exact_keys(activation, {"mode", "status", "authorized_by", "active_fields"}, path="intent.activation")
    require_enum(activation["mode"], {"AI_DIRECTOR", "OWNER_CURATED"}, path="intent.activation.mode")
    require_enum(activation["status"], {"ACTIVE", "SUPERSEDED", "DRAFT"}, path="intent.activation.status")
    require_string(activation["authorized_by"], path="intent.activation.authorized_by")
    active_fields = require_list(activation["active_fields"], path="intent.activation.active_fields")
    for index, field in enumerate(active_fields):
        require_enum(field, {"identity", "creative", "controlled_preferences"}, path=f"intent.activation.active_fields[{index}]")
    if len(active_fields) != len(set(active_fields)):
        fail("DCC_SCHEMA_DUPLICATE", "intent.activation.active_fields must be unique.")

    validate_self_hash(intent, "intent_sha256", code="DCC_INTENT_HASH_INVALID")
    unsigned = without_hash(intent, "intent_sha256")
    unsigned.pop("intent_id", None)
    expected_id, _, _ = derive_intent_identifier(unsigned)
    if intent["intent_id"] != expected_id:
        fail("DCC_INTENT_ID_INVALID", "intent.intent_id does not match its deterministic seed.")
    return deepcopy(dict(intent))


def build_creative_intent(unsigned: Mapping[str, Any]) -> dict[str, Any]:
    """Construct a sealed intent from the object without generated IDs."""

    base = deepcopy(dict(unsigned))
    if "intent_id" in base or "intent_sha256" in base:
        fail("DCC_INTENT_BUILD_INPUT", "Intent construction accepts neither generated identity field.")
    identifier, _, _ = derive_intent_identifier(base)
    base["intent_id"] = identifier
    base["intent_sha256"] = sha256_json(base)
    return validate_creative_intent(base)


def intent_seed_sha256(intent: Mapping[str, Any]) -> str:
    valid = validate_creative_intent(intent)
    unsigned = without_hash(valid, "intent_sha256")
    unsigned.pop("intent_id", None)
    return domain_digest("dcc.intent.seed.v1", unsigned)


# The proposal calls these the standard Factory identifiers.  Keep aliases
# explicit so conformance tests can use either the descriptive or short name.
canonical_json_bytes = canonical_bytes
sha256_canonical = canonical_sha256
build_intent = build_creative_intent


@dataclass(frozen=True)
class BindingHashes:
    """Small immutable binding primitive used by shadow callers."""

    request_sha256: str
    content_snapshot_sha256: str
    content_lock_hash: str
    character_state_sha256: str

    def __post_init__(self) -> None:
        for field in ("request_sha256", "content_snapshot_sha256", "content_lock_hash", "character_state_sha256"):
            require_digest(getattr(self, field), path=field)
