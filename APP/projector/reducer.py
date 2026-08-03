from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.core import FoundryError, sha256_json
from contracts.canonical import canonical_event_hash
from contracts.registry import SchemaRegistry

ZERO_HASH = "0" * 64
ALLOWED_TARGETS = {"ledger", "rules_selection_packets"}
ALLOWED_OPS = {"set", "append", "merge"}


def _tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise FoundryError("PROJECTION_POINTER_INVALID", "Projection JSON Pointer must be empty or start with '/'.", details={"pointer": pointer})
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _set_pointer(document: Any, pointer: str, value: Any) -> Any:
    tokens = _tokens(pointer)
    if not tokens:
        return deepcopy(value)
    if not isinstance(document, (dict, list)):
        document = {}
    cur = document
    for index, token in enumerate(tokens[:-1]):
        next_token = tokens[index + 1]
        if isinstance(cur, dict):
            if token not in cur:
                cur[token] = [] if next_token == "-" or next_token.isdigit() else {}
            cur = cur[token]
        elif isinstance(cur, list):
            if not token.isdigit():
                raise FoundryError("PROJECTION_POINTER_INVALID", "Array projection pointer requires an integer index.", details={"pointer": pointer})
            idx = int(token)
            while len(cur) <= idx:
                cur.append({})
            cur = cur[idx]
        else:
            raise FoundryError("PROJECTION_POINTER_COLLISION", "Projection pointer traverses a scalar value.", details={"pointer": pointer})
    last = tokens[-1]
    if isinstance(cur, dict):
        cur[last] = deepcopy(value)
    elif isinstance(cur, list):
        if last == "-":
            cur.append(deepcopy(value))
        elif last.isdigit():
            idx = int(last)
            while len(cur) <= idx:
                cur.append(None)
            cur[idx] = deepcopy(value)
        else:
            raise FoundryError("PROJECTION_POINTER_INVALID", "Array projection pointer requires '-' or an integer index.", details={"pointer": pointer})
    else:
        raise FoundryError("PROJECTION_POINTER_COLLISION", "Projection pointer targets a scalar parent.", details={"pointer": pointer})
    return document


def _get_pointer(document: Any, pointer: str) -> Any:
    cur = document
    for token in _tokens(pointer):
        if isinstance(cur, dict) and token in cur:
            cur = cur[token]
        elif isinstance(cur, list) and token.isdigit() and int(token) < len(cur):
            cur = cur[int(token)]
        else:
            raise FoundryError("PROJECTION_POINTER_MISSING", "Projection merge/append target does not exist.", details={"pointer": pointer})
    return cur


def _leaf_pointers(value: Any, pointer: str) -> list[str]:
    if isinstance(value, dict):
        if not value:
            return [pointer]
        result: list[str] = []
        for key in sorted(value):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            result.extend(_leaf_pointers(value[key], pointer + "/" + escaped))
        return result
    if isinstance(value, list):
        if not value:
            return [pointer]
        result: list[str] = []
        for index, item in enumerate(value):
            result.extend(_leaf_pointers(item, pointer + f"/{index}"))
        return result
    return [pointer]


@dataclass
class ReducedProjectionState:
    ledger: dict[str, Any] = field(default_factory=dict)
    rules_selection_packets: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    operations_applied: int = 0
    event_ids: list[str] = field(default_factory=list)
    selected_record_ids: list[str] = field(default_factory=list)
    event_schema_version: str = "TianxiaFoundry.AdvancementEvent.v1"
    readiness: dict[str, Any] = field(default_factory=dict)
    capability_coverage: list[dict[str, Any]] = field(default_factory=list)
    validation_profile: dict[str, Any] = field(default_factory=dict)
    project_display_contract: dict[str, Any] | None = None
    typed_choice_snapshot: dict[str, Any] | None = None


class EffectiveStateReducer:
    """Reduce validated canonical events into deterministic projector inputs.

    Normal production events are expected to project through locked catalog grants and
    execution templates. Phase 3A additionally supports one narrowly scoped, audited
    ``migration.projection_operations`` form for reconstructing the Factory golden
    fixture. This form is canonical-event data, not an independently authored ledger.
    """

    def __init__(self, registry: SchemaRegistry):
        self.registry = registry

    @staticmethod
    def _operation_provenance(event: dict[str, Any], record: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event["event_id"],
            "event_hash": event["event_hash"],
            "sequence": event["sequence"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
            "content_binding": deepcopy(event["content_binding"]),
            "source_evidence": deepcopy(event["source_evidence"]),
            "projection_operation": {"target": operation["target"], "op": operation["op"], "path": operation["path"]},
            "source_kind": operation.get("source_kind", "event_migration_projection"),
        }

    def _validate_v1_chain(self, events: list[dict[str, Any]]) -> None:
        previous = ZERO_HASH
        for expected, event in enumerate(events, start=1):
            report = self.registry.report(event, "TianxiaFoundry.AdvancementEvent.v1")
            if not report["valid"]:
                raise FoundryError("PROJECTION_EVENT_SCHEMA_INVALID", "An event failed canonical validation before projection.", details={"event_id": event.get("event_id"), "diagnostics": report["diagnostics"]})
            if event["sequence"] != expected:
                raise FoundryError("PROJECTION_EVENT_SEQUENCE_INVALID", "Projection requires a gap-free event sequence.", details={"expected": expected, "actual": event["sequence"]})
            if event["previous_event_hash"] != previous:
                raise FoundryError("PROJECTION_EVENT_CHAIN_BROKEN", "Projection event hash chain is broken.", details={"sequence": expected})
            computed = canonical_event_hash(event)
            if computed != event["event_hash"]:
                raise FoundryError("PROJECTION_EVENT_HASH_MISMATCH", "Projection event bytes do not match their canonical hash.", details={"sequence": expected})
            previous = event["event_hash"]

    @staticmethod
    def _validate_binding(event: dict[str, Any], record: dict[str, Any], project: dict[str, Any]) -> None:
        binding = event["content_binding"]
        record_binding = record["content_binding"]
        if binding["record_hash"] != record["record_hash"] or binding["pack_id"] != record_binding["pack_id"] or binding["pack_version"] != record_binding["pack_version"] or binding["pack_hash"] != record_binding["pack_hash"]:
            raise FoundryError("PROJECTION_CONTENT_BINDING_MISMATCH", "Event content binding does not match the locked record snapshot.", details={"event_id": event["event_id"], "record_id": record["record_id"]})
        locks = {(x["pack_id"], x["version"], x["content_hash"]) for x in project["content_lock"]["packs"]}
        if (binding["pack_id"], binding["pack_version"], binding["pack_hash"]) not in locks:
            raise FoundryError("PROJECTION_UNLOCKED_CONTENT", "Event references a content version outside the canonical project lock.", details={"event_id": event["event_id"], "binding": binding})

    @staticmethod
    def _validate_operation(operation: dict[str, Any], event: dict[str, Any]) -> None:
        if not isinstance(operation, dict):
            raise FoundryError("PROJECTION_OPERATION_INVALID", "Projection operation must be an object.", details={"event_id": event["event_id"]})
        if operation.get("target") not in ALLOWED_TARGETS:
            raise FoundryError("PROJECTION_TARGET_INVALID", "Projection operation target is not allowed.", details={"event_id": event["event_id"], "target": operation.get("target")})
        if operation.get("op") not in ALLOWED_OPS:
            raise FoundryError("PROJECTION_OPERATION_INVALID", "Projection operation type is not allowed.", details={"event_id": event["event_id"], "op": operation.get("op")})
        if not isinstance(operation.get("path"), str):
            raise FoundryError("PROJECTION_POINTER_INVALID", "Projection operation requires a JSON Pointer string.", details={"event_id": event["event_id"]})
        _tokens(operation["path"])
        if "value" not in operation:
            raise FoundryError("PROJECTION_VALUE_MISSING", "Projection operation requires a value.", details={"event_id": event["event_id"], "path": operation["path"]})

    def reduce(self, *, project: dict[str, Any], events: list[dict[str, Any]], locked_records: dict[str, dict[str, Any]], choice_snapshot: dict[str, Any] | None = None) -> ReducedProjectionState:
        versions = {event.get("schema_version") for event in events}
        if len(versions) != 1:
            raise FoundryError("PROJECTION_EVENT_SCHEMA_MIXED", "Projection rejects mixed canonical event schema streams.", details={"schema_versions": sorted(str(x) for x in versions)})
        version = next(iter(versions), None)
        if version == "TianxiaFoundry.AdvancementEvent.v3":
            from projector.v3_bridge import reduce_v3
            return reduce_v3(root_dir=self.registry.root_dir, registry=self.registry, project=project, events=events, locked_records=locked_records, choice_snapshot=choice_snapshot, state_type=ReducedProjectionState)
        if version != "TianxiaFoundry.AdvancementEvent.v1":
            raise FoundryError("PROJECTION_EVENT_SCHEMA_UNSUPPORTED", "Projection does not support this homogeneous event schema.", details={"schema_version": version})
        self._validate_v1_chain(events)
        state = ReducedProjectionState()
        for event in events:
            record_id = event["subject"]["record_id"]
            record = locked_records.get(record_id)
            if record is None:
                raise FoundryError("PROJECTION_LOCKED_RECORD_MISSING", "Projection cannot resolve an event's locked catalog record.", details={"event_id": event["event_id"], "record_id": record_id})
            record_report = self.registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
            if not record_report["valid"]:
                raise FoundryError("PROJECTION_RECORD_SCHEMA_INVALID", "A locked catalog record failed canonical validation.", details={"record_id": record_id, "diagnostics": record_report["diagnostics"]})
            authority = record.get("compatibility", {}).get("factory", {}).get("authority_classification")
            if authority in {"unresolved", "reference-only", "deprecated"}:
                raise FoundryError("PROJECTION_RECORD_NOT_SELECTABLE", "An unresolved, reference-only, or deprecated record cannot supply projected mechanics.", details={"record_id": record_id, "authority": authority})
            publication = record.get("publication", {}).get("status")
            fixture_authority = "golden-fixture-authority" in record.get("tags", [])
            if publication != "published" and not fixture_authority:
                raise FoundryError("PROJECTION_RECORD_NOT_PUBLISHED", "Only published content or the audited golden-fixture authority may supply projection operations.", details={"record_id": record_id, "publication": publication})
            self._validate_binding(event, record, project)
            state.event_ids.append(event["event_id"])
            if record_id not in state.selected_record_ids:
                state.selected_record_ids.append(record_id)
            migration = event.get("migration") or {}
            operations = migration.get("projection_operations") or []
            if operations and migration.get("operation") not in {"projection", "fixture_projection", "golden_fixture_reconstruction"}:
                raise FoundryError("PROJECTION_MIGRATION_OPERATION_INVALID", "Structured projection operations require an authorized migration operation.", details={"event_id": event["event_id"], "operation": migration.get("operation")})
            for operation in operations:
                self._validate_operation(operation, event)
                target_name = operation["target"]
                document = state.ledger if target_name == "ledger" else state.rules_selection_packets
                op = operation["op"]
                pointer = operation["path"]
                value = deepcopy(operation["value"])
                if op == "set":
                    new_document = _set_pointer(document, pointer, value)
                    if target_name == "ledger":
                        state.ledger = new_document
                    else:
                        state.rules_selection_packets = new_document
                elif op == "append":
                    target = _get_pointer(document, pointer)
                    if not isinstance(target, list):
                        raise FoundryError("PROJECTION_APPEND_TARGET_INVALID", "Append operation requires an existing array.", details={"event_id": event["event_id"], "path": pointer})
                    target.append(value)
                elif op == "merge":
                    target = _get_pointer(document, pointer)
                    if not isinstance(target, dict) or not isinstance(value, dict):
                        raise FoundryError("PROJECTION_MERGE_TARGET_INVALID", "Merge operation requires object target and value.", details={"event_id": event["event_id"], "path": pointer})
                    for key, item in value.items():
                        target[key] = deepcopy(item)
                provenance = self._operation_provenance(event, record, operation)
                base = pointer
                for leaf in _leaf_pointers(value, base):
                    key = f"/{target_name}{leaf}" if leaf else f"/{target_name}"
                    state.provenance[key] = deepcopy(provenance)
                state.operations_applied += 1
        state.selected_record_ids.sort()
        return state

    @staticmethod
    def projection_input_hash(project: dict[str, Any], events: list[dict[str, Any]], locked_records: dict[str, dict[str, Any]]) -> str:
        return sha256_json({
            "project": project,
            "events": events,
            "locked_records": {key: locked_records[key] for key in sorted(locked_records)},
        })
