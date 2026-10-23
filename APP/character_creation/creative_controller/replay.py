"""Append-only event receipts and deterministic replay checks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.core import sha256_bytes, sha256_json

from .contracts import (
    CreativeControllerError,
    derive_event_identifier,
    fail,
    require_digest,
    require_enum,
    require_exact_keys,
    require_identifier,
    require_string,
    require_type,
    validate_self_hash,
)


EVENT_SCHEMA = "TianxiaFoundry.CreativeControllerEvent.v1"
REPLAY_SCHEMA = "TianxiaFoundry.ControllerReplayReceipt.v1"
EVENT_TYPES = {"INTENT_ACTIVATED", "MANIFEST_PUBLISHED", "CHOICE_ACCEPTED", "PLAN_APPLIED", "VALIDATION_BLOCKED", "SUPERSEDED", "CREATIVE_DIRECTOR_CHANGED", "CONTENT_REBASE_APPLIED", "CONTENT_REBASE_BLOCKED", "CONTENT_AUTHORITY_REVOKED"}
ACTORS = {"factory", "owner", "provider"}
RESULTS = {"APPLIED", "BLOCKED", "SUPERSEDED"}
BINDING_KEYS = {"project_revision", "content_snapshot_sha256", "request_sha256", "request_resolver_id", "request_resolver_binding_sha256", "content_lock_hash", "selected_ai_identity_sha256"}
PROVIDER_KEYS = {"provider_id", "model", "ai_identity_sha256", "request_sha256", "response_sha256"}


def _event_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, BINDING_KEYS, path="event.binding")
    require_type(value["project_revision"], int, path="event.binding.project_revision")
    if value["project_revision"] < 0:
        fail("DCC_SCHEMA_VALUE", "event.binding.project_revision cannot be negative.")
    for field in ("content_snapshot_sha256", "request_sha256", "request_resolver_binding_sha256", "content_lock_hash", "selected_ai_identity_sha256"):
        require_digest(value[field], path=f"event.binding.{field}")
    require_identifier(value["request_resolver_id"], path="event.binding.request_resolver_id", prefix="dcc.request.")
    return deepcopy(dict(value))


def _provider_provenance(value: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied = value or {"provider_id": None, "model": None, "ai_identity_sha256": None, "request_sha256": None, "response_sha256": None}
    require_exact_keys(supplied, PROVIDER_KEYS, path="event.provider_provenance")
    result = deepcopy(dict(supplied))
    for field in PROVIDER_KEYS:
        if field == "provider_id" or field == "model":
            if result[field] is not None:
                require_string(result[field], path=f"event.provider_provenance.{field}")
        else:
            require_digest(result[field], path=f"event.provider_provenance.{field}", allow_none=True)
    return result


def _check_no_request_bytes(value: Any, *, path: str = "event") -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        fail("DCC_EVENT_REQUEST_BYTES", "Events may reference request digests but cannot contain request bytes.")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in {"request", "request_bytes", "request_payload", "complete_request", "prompt_bytes", "response_bytes"}:
                fail("DCC_EVENT_REQUEST_BYTES", "Events may not contain complete request or response payload fields.", details={"field": f"{path}.{key}"})
            _check_no_request_bytes(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _check_no_request_bytes(child, path=f"{path}[{index}]")


@dataclass(frozen=True)
class ControllerEvent:
    value: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deepcopy(self.value))
        validate_event(self.value)

    @property
    def event_sha256(self) -> str:
        return self.value["event_sha256"]

    @property
    def event_id(self) -> str:
        return self.value["event_id"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.value)


def build_event(
    *,
    controller_id: str,
    ordinal: int,
    event_type: str,
    run_id: str,
    project_id: str,
    previous_event_sha256: str | None,
    subject_sha256: str,
    binding: Mapping[str, Any],
    state_sha256_before: str,
    state_sha256_after: str,
    actor: str = "factory",
    result: str = "APPLIED",
    provider_provenance: Mapping[str, Any] | None = None,
) -> ControllerEvent:
    require_identifier(controller_id, path="event.controller_id", prefix="dcc.controller.")
    require_type(ordinal, int, path="event.ordinal")
    if ordinal < 1:
        fail("DCC_EVENT_ORDINAL_INVALID", "Event ordinals start at one.")
    if previous_event_sha256 is not None:
        require_digest(previous_event_sha256, path="event.previous_event_sha256")
    require_enum(event_type, EVENT_TYPES, path="event.event_type")
    require_string(run_id, path="event.run_id")
    require_string(project_id, path="event.project_id")
    require_digest(subject_sha256, path="event.subject_sha256")
    bound = _event_binding(binding)
    require_digest(state_sha256_before, path="event.state_sha256_before")
    require_digest(state_sha256_after, path="event.state_sha256_after")
    require_enum(actor, ACTORS, path="event.actor")
    require_enum(result, RESULTS, path="event.result")
    provenance = _provider_provenance(provider_provenance)
    unsigned = {
        "schema": EVENT_SCHEMA,
        "event_id": "",
        "controller_id": controller_id,
        "ordinal": ordinal,
        "event_type": event_type,
        "run_id": run_id,
        "project_id": project_id,
        "previous_event_sha256": previous_event_sha256,
        "subject_sha256": subject_sha256,
        "binding": bound,
        "state_sha256_before": state_sha256_before,
        "state_sha256_after": state_sha256_after,
        "event_count_before": ordinal - 1,
        "event_count_after": ordinal,
        "actor": actor,
        "provider_provenance": provenance,
        "result": result,
    }
    event_id, _ = derive_event_identifier(controller_id, ordinal, previous_event_sha256, event_type, subject_sha256)
    unsigned["event_id"] = event_id
    unsigned["event_sha256"] = sha256_json(unsigned)
    _check_no_request_bytes(unsigned)
    return ControllerEvent(unsigned)


def validate_event(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, {"schema", "event_id", "controller_id", "ordinal", "event_type", "run_id", "project_id", "previous_event_sha256", "subject_sha256", "binding", "state_sha256_before", "state_sha256_after", "event_count_before", "event_count_after", "actor", "provider_provenance", "result", "event_sha256"}, path="event")
    if value["schema"] != EVENT_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported controller event schema.")
    require_identifier(value["event_id"], path="event.event_id", prefix="dcc.event.")
    require_identifier(value["controller_id"], path="event.controller_id", prefix="dcc.controller.")
    ordinal = require_type(value["ordinal"], int, path="event.ordinal")
    if ordinal < 1:
        fail("DCC_EVENT_ORDINAL_INVALID", "Event ordinals start at one.")
    require_enum(value["event_type"], EVENT_TYPES, path="event.event_type")
    require_string(value["run_id"], path="event.run_id")
    require_string(value["project_id"], path="event.project_id")
    require_digest(value["previous_event_sha256"], path="event.previous_event_sha256", allow_none=True)
    require_digest(value["subject_sha256"], path="event.subject_sha256")
    _event_binding(value["binding"])
    for field in ("state_sha256_before", "state_sha256_after"):
        require_digest(value[field], path=f"event.{field}")
    if value["event_count_before"] != ordinal - 1 or value["event_count_after"] != ordinal:
        fail("DCC_EVENT_COUNT_INVALID", "Event count fields must match ordinal.")
    require_enum(value["actor"], ACTORS, path="event.actor")
    _provider_provenance(value["provider_provenance"])
    require_enum(value["result"], RESULTS, path="event.result")
    expected_id, _ = derive_event_identifier(value["controller_id"], ordinal, value["previous_event_sha256"], value["event_type"], value["subject_sha256"])
    if value["event_id"] != expected_id:
        fail("DCC_EVENT_ID_INVALID", "event_id is not derived from the event identity tuple.")
    validate_self_hash(value, "event_sha256", code="DCC_EVENT_HASH_INVALID")
    _check_no_request_bytes(value)
    return deepcopy(dict(value))


def event_contains_complete_request_bytes(value: Mapping[str, Any]) -> bool:
    try:
        _check_no_request_bytes(value)
    except CreativeControllerError:
        return True
    return False


def verify_event_chain(events: Sequence[ControllerEvent | Mapping[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"event_count": 0, "event_head_sha256": None, "controller_id": None, "run_id": None, "project_id": None}
    normalized = [validate_event(row.value if isinstance(row, ControllerEvent) else row) for row in events]
    controller_id = normalized[0]["controller_id"]
    run_id = normalized[0]["run_id"]
    project_id = normalized[0]["project_id"]
    previous = None
    previous_event: dict[str, Any] | None = None
    binding = normalized[0]["binding"]
    for expected_ordinal, event in enumerate(normalized, start=1):
        if event["ordinal"] != expected_ordinal:
            fail("DCC_EVENT_CHAIN_INVALID", "Event ordinals must be contiguous.")
        if event["previous_event_sha256"] != previous:
            fail("DCC_EVENT_CHAIN_INVALID", "Event previous hash does not match the current chain head.")
        if event["controller_id"] != controller_id or event["run_id"] != run_id or event["project_id"] != project_id:
            fail("DCC_EVENT_CHAIN_INVALID", "Event chain identity changed mid-stream.")
        if event["binding"] != binding:
            fail("DCC_EVENT_CHAIN_INVALID", "Event binding changed mid-stream.")
        if previous_event is not None and event["state_sha256_before"] != previous_event["state_sha256_after"]:
            fail("DCC_EVENT_CHAIN_INVALID", "Event state-before hash does not match the prior state-after hash.")
        previous = event["event_sha256"]
        previous_event = event
    return {"event_count": len(normalized), "event_head_sha256": previous, "controller_id": controller_id, "run_id": run_id, "project_id": project_id}


def append_event(events: Sequence[ControllerEvent | Mapping[str, Any]], event: ControllerEvent | Mapping[str, Any]) -> tuple[ControllerEvent, ...]:
    current = tuple(events)
    if current:
        head = verify_event_chain(current)
        next_event = validate_event(event.value if isinstance(event, ControllerEvent) else event)
        if next_event["ordinal"] != head["event_count"] + 1 or next_event["previous_event_sha256"] != head["event_head_sha256"]:
            fail("DCC_EVENT_CHAIN_INVALID", "An appended event must extend the exact current chain head.")
    else:
        next_event = validate_event(event.value if isinstance(event, ControllerEvent) else event)
        if next_event["ordinal"] != 1 or next_event["previous_event_sha256"] is not None:
            fail("DCC_EVENT_CHAIN_INVALID", "The first event must start ordinal one with a null previous hash.")
    return tuple(ControllerEvent(row.value if isinstance(row, ControllerEvent) else row) for row in (*current, next_event))


@dataclass(frozen=True)
class ReplayReceipt:
    value: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deepcopy(self.value))
        require_exact_keys(self.value, {"schema", "run_id", "event_head_sha256", "replayed_event_count", "content_snapshot_sha256", "request_sha256", "request_resolver_id", "request_resolver_binding_sha256", "selected_ai_identity_sha256", "input_binding_sha256", "reconstructed_state_sha256", "reconstructed_manifest_sha256", "expected_state_sha256", "expected_manifest_sha256", "byte_identical", "validator_receipts", "replay_receipt_sha256"}, path="replay receipt")
        if self.value["schema"] != REPLAY_SCHEMA:
            fail("DCC_SCHEMA_VALUE", "Unsupported replay receipt schema.")
        require_digest(self.value["event_head_sha256"], path="replay receipt.event_head_sha256", allow_none=True)
        event_count = require_type(self.value["replayed_event_count"], int, path="replay receipt.replayed_event_count")
        if event_count < 0:
            fail("DCC_SCHEMA_VALUE", "replay receipt.replayed_event_count cannot be negative.")
        for field in ("content_snapshot_sha256", "request_sha256", "request_resolver_binding_sha256", "selected_ai_identity_sha256", "input_binding_sha256", "reconstructed_state_sha256", "expected_state_sha256"):
            require_digest(self.value[field], path=f"replay receipt.{field}")
        require_identifier(self.value["request_resolver_id"], path="replay receipt.request_resolver_id", prefix="dcc.request.")
        require_digest(self.value["reconstructed_manifest_sha256"], path="replay receipt.reconstructed_manifest_sha256", allow_none=True)
        require_digest(self.value["expected_manifest_sha256"], path="replay receipt.expected_manifest_sha256", allow_none=True)
        require_type(self.value["byte_identical"], bool, path="replay receipt.byte_identical")
        receipts = self.value["validator_receipts"]
        if not isinstance(receipts, list):
            fail("DCC_SCHEMA_TYPE", "replay receipt.validator_receipts must be an array.")
        for index, receipt in enumerate(receipts):
            require_digest(receipt, path=f"replay receipt.validator_receipts[{index}]")
        validate_self_hash(self.value, "replay_receipt_sha256", code="DCC_REPLAY_RECEIPT_HASH_INVALID")

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.value)


def build_replay_receipt(
    events: Sequence[ControllerEvent | Mapping[str, Any]],
    *,
    content_snapshot_sha256: str,
    request_sha256: str,
    request_resolver_id: str,
    request_resolver_binding_sha256: str,
    selected_ai_identity_sha256: str,
    input_binding_sha256: str,
    expected_state_sha256: str,
    expected_manifest_sha256: str | None = None,
    validator_receipts: Iterable[str] = (),
    request_bytes: bytes | None = None,
    resolved_inputs: Any | None = None,
    expected_manifest_bytes: bytes | None = None,
) -> ReplayReceipt:
    chain = verify_event_chain(events)
    for field, value in (("content_snapshot_sha256", content_snapshot_sha256), ("request_sha256", request_sha256), ("request_resolver_binding_sha256", request_resolver_binding_sha256), ("input_binding_sha256", input_binding_sha256), ("expected_state_sha256", expected_state_sha256)):
        require_digest(value, path=field)
    require_identifier(request_resolver_id, path="request_resolver_id", prefix="dcc.request.")
    require_digest(selected_ai_identity_sha256, path="selected_ai_identity_sha256")
    require_digest(expected_manifest_sha256, path="expected_manifest_sha256", allow_none=True)
    receipts = sorted({require_digest(value, path="validator_receipts[]") for value in validator_receipts})
    if request_bytes is None or not isinstance(request_bytes, bytes):
        fail("DCC_REQUEST_RESOLUTION_REQUIRED", "Replay requires the exact immutable request bytes.")
    if sha256_bytes(request_bytes) != request_sha256:
        fail("DCC_REQUEST_RESOLUTION_INVALID", "Resolved request bytes do not match the bound request digest.")
    if resolved_inputs is None:
        fail("DCC_REPLAY_INPUTS_REQUIRED", "Replay requires immutable resolved inputs for deterministic recomputation.")
    normalized = [row.value if isinstance(row, ControllerEvent) else row for row in events]
    if normalized:
        actual_binding = normalized[0]["binding"]
        if any(actual_binding[field] != value for field, value in (("content_snapshot_sha256", content_snapshot_sha256), ("request_sha256", request_sha256), ("request_resolver_id", request_resolver_id), ("request_resolver_binding_sha256", request_resolver_binding_sha256), ("selected_ai_identity_sha256", selected_ai_identity_sha256))):
            fail("DCC_REPLAY_BINDING_INVALID", "Replay inputs do not match the event chain binding.")
        from .shadow import ShadowInputs, run_shadow_controller
        if not isinstance(resolved_inputs, ShadowInputs):
            fail("DCC_REPLAY_INPUTS_INVALID", "Replay inputs must be immutable ShadowInputs.")
        replay_result = run_shadow_controller(resolved_inputs)
        resolved_binding = replay_result.artifact.manifest["binding"]
        if sha256_json(resolved_binding) != input_binding_sha256 or resolved_binding != {**actual_binding, **{key: resolved_binding[key] for key in ("catalogue_sha256", "catalogue_schema_version", "project_id", "canonical_project_sha256", "typed_choice_snapshot_sha256", "delegated_choice_envelope_sha256", "character_state_sha256", "intent_sha256", "operator_contract_sha256", "controller_version_sha256", "legal_compiler_version_sha256", "ranking_profile_sha256", "choice_semantics_set_sha256", "selected_ai_identity_sha256", "vocabulary_authority_sha256", "creative_predicate_menu_sha256", "creative_predicate_selection_receipt_sha256", "accepted_baseline_sha256", "owner_locks_sha256", "acquisition_history_sha256")}}:
            fail("DCC_REPLAY_BINDING_INVALID", "Resolved inputs do not reproduce the bound input binding.")
        recomputed_events = [event.to_dict() for event in replay_result.events]
        if recomputed_events != normalized:
            fail("DCC_REPLAY_EVENT_SUBJECT_INVALID", "Stored event subjects or state are not the deterministic recomputation.")
        reconstructed_state = replay_result.events[-1].value["state_sha256_after"]
        reconstructed_manifest = replay_result.artifact.manifest_sha256
        actual_manifest_bytes = replay_result.manifest_json.encode("utf-8")
        if expected_manifest_bytes is None or not isinstance(expected_manifest_bytes, bytes) or actual_manifest_bytes != expected_manifest_bytes:
            fail("DCC_REPLAY_MANIFEST_BYTES_INVALID", "Replay requires exact canonical manifest bytes.")
    else:
        fail("DCC_REPLAY_INPUTS_INVALID", "Replay requires a nonempty controller event chain.")
    byte_identical = reconstructed_state == expected_state_sha256 and reconstructed_manifest == expected_manifest_sha256
    if not byte_identical:
        fail("DCC_REPLAY_MISMATCH", "Replay did not reconstruct the expected state or manifest.", status_code=409)
    unsigned = {
        "schema": REPLAY_SCHEMA,
        "run_id": chain["run_id"] or "",
        "event_head_sha256": chain["event_head_sha256"],
        "replayed_event_count": chain["event_count"],
        "content_snapshot_sha256": content_snapshot_sha256,
        "request_sha256": request_sha256,
        "request_resolver_id": request_resolver_id,
        "request_resolver_binding_sha256": request_resolver_binding_sha256,
        "selected_ai_identity_sha256": selected_ai_identity_sha256,
        "input_binding_sha256": input_binding_sha256,
        "reconstructed_state_sha256": reconstructed_state,
        "reconstructed_manifest_sha256": reconstructed_manifest,
        "expected_state_sha256": expected_state_sha256,
        "expected_manifest_sha256": expected_manifest_sha256,
        "byte_identical": byte_identical,
        "validator_receipts": receipts,
    }
    return ReplayReceipt({**unsigned, "replay_receipt_sha256": sha256_json(unsigned)})


def replay_controller(*args: Any, **kwargs: Any) -> ReplayReceipt:
    return build_replay_receipt(*args, **kwargs)
