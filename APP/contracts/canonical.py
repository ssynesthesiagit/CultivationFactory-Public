from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

from app.core import (
    CANDIDATE_SCHEMA_VERSION,
    EXPECTED_FACTORY_HASH,
    FACTORY_VERSION,
    GM_SCREEN_VERSION,
    CATALOG_GM_COMPATIBILITY_VERSION,
    canonical_json,
    sha256_json,
)

ZERO_HASH = "0" * 64
GM_SCREEN_PATCH = "HF2"
GM_SCREEN_SAVE_SCHEMA = "HF05ZUI-R2I.compact-save.v2"


def _unique_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out


def _identifier(value: str, prefix: str = "id") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", ".", str(value)).strip(".")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"{prefix}.{cleaned}".strip(".")
    return cleaned[:200]


def canonical_record_hash(record: dict[str, Any]) -> str:
    return sha256_json({k: v for k, v in record.items() if k != "record_hash"})


def canonical_event_hash(event: dict[str, Any]) -> str:
    return sha256_json({k: v for k, v in event.items() if k != "event_hash"})


def canonical_project_hash(project: dict[str, Any]) -> str:
    return sha256_json(project)


def _normalise_prerequisites(raw: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    canonical: list[dict[str, Any]] = []
    retained: list[Any] = []
    allowed = {"requires", "one_of", "all_of", "not", "minimum", "maximum"}
    for item in values:
        if isinstance(item, dict):
            kind = item.get("kind")
            target = item.get("target_id") or item.get("record_id") or item.get("canonical_id") or item.get("id")
            operator = item.get("operator", "requires")
            if isinstance(kind, str) and isinstance(target, str) and operator in allowed:
                row = {"kind": _identifier(kind), "target_id": _identifier(target), "operator": operator}
                if "value" in item:
                    row["value"] = item["value"]
                canonical.append(row)
                continue
        retained.append(item)
    return canonical, retained


def _normalise_grants(raw: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    canonical: list[dict[str, Any]] = []
    retained: list[Any] = []
    operations = {"create", "add", "replace", "unlock", "modify", "permit"}
    for item in values:
        if isinstance(item, dict):
            grant_type = item.get("grant_type") or item.get("type") or item.get("kind")
            target = item.get("target_id") or item.get("record_id") or item.get("canonical_id") or item.get("id")
            operation = item.get("operation", "add")
            if isinstance(grant_type, str) and isinstance(target, str) and operation in operations:
                row: dict[str, Any] = {
                    "grant_type": _identifier(grant_type),
                    "target_id": _identifier(target),
                    "operation": operation,
                }
                if "value" in item:
                    row["value"] = item["value"]
                if isinstance(item.get("condition"), str):
                    row["condition"] = item["condition"]
                canonical.append(row)
                continue
        retained.append(item)
    return canonical, retained


def _execution_type(raw: dict[str, Any]) -> str:
    value = str(raw.get("template_type") or raw.get("record_type") or raw.get("type") or "").lower()
    allowed = {
        "action", "state", "resource", "modifier", "procedure", "passive_statistic",
        "permission", "companion", "item_projection",
    }
    if value in allowed:
        return value
    if any(key in raw for key in ("action_type", "timing", "target", "range", "resolution", "damage_or_effect")):
        return "action"
    if "resource" in value:
        return "resource"
    if "state" in value:
        return "state"
    if "modifier" in value:
        return "modifier"
    return "procedure"


def _normalise_execution(raw: Any, record_id: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        if any(k in raw for k in ("template_id", "action_id", "record_id", "type", "timing", "effect")):
            values: list[Any] = [raw]
        else:
            values = [{"template_id": key, "payload": value} for key, value in sorted(raw.items())]
    elif isinstance(raw, list):
        values = raw
    else:
        values = [raw]
    result: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if isinstance(value, dict):
            template_id = value.get("template_id") or value.get("action_id") or value.get("record_id") or value.get("id")
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else value
            row = {
                "template_id": _identifier(template_id or f"{record_id}.execution.{index + 1}"),
                "template_type": _execution_type(value),
                "payload": deepcopy(payload),
            }
            if isinstance(value.get("created_record_id_pattern"), str):
                row["created_record_id_pattern"] = value["created_record_id_pattern"]
        else:
            row = {
                "template_id": _identifier(f"{record_id}.execution.{index + 1}"),
                "template_type": "procedure",
                "payload": {"source_value": value},
            }
        result.append(row)
    return result


def normalize_core_catalog_record(projection: dict[str, Any], *, pack_hash: str) -> dict[str, Any]:
    """Convert an HF05ZVK source projection into the Phase 1 canonical catalog contract.

    Raw source material remains under compatibility.factory.raw_projection. It is never
    treated as executable merely because it was structurally ingested.
    """
    if projection.get("schema_version") == "TianxiaFoundry.RulesCatalogRecord.v1":
        record = deepcopy(projection)
        record["record_hash"] = canonical_record_hash(record)
        return record

    record_id = _identifier(projection["record_id"])
    content_type = _identifier(projection["content_type"])
    display_name = str(projection.get("display_name") or record_id)
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    source_hash = source.get("source_hash") or ZERO_HASH
    source_anchor = str(source.get("anchor") or f"record:{record_id}")
    authority = str(projection.get("authority") or "unresolved")
    selected_authority = bool(projection.get("selected_authority", True))
    notes = list(projection.get("unresolved_normalization_notes") or [])
    prereqs, retained_prereqs = _normalise_prerequisites(projection.get("prerequisites"))
    grants, retained_grants = _normalise_grants(projection.get("grants"))
    execution = _normalise_execution(projection.get("execution_records"), record_id)
    channels = _unique_strings(projection.get("acquisition_channels") or [])
    if not channels:
        channels = ["reference-only"]
        notes.append("No authoritative acquisition channel was present; record is non-selectable until normalized.")
    selectable_authority = authority in {"canonical", "published-extension", "test-only"}
    requested_publication = str(projection.get("publication_state") or "draft")
    complete_for_selection = selectable_authority and selected_authority and not notes and bool(channels)
    publication_status = "published" if requested_publication == "published" and complete_for_selection else (
        "validated" if requested_publication in {"published", "validated"} else "draft"
    )
    if authority in {"reference-only", "unresolved"}:
        publication_status = "validated" if requested_publication != "draft" else "draft"

    summary = str(projection.get("summary") or display_name)
    raw_compatibility = projection.get("compatibility") if isinstance(projection.get("compatibility"), dict) else {}
    canonical: dict[str, Any] = {
        "schema_version": "TianxiaFoundry.RulesCatalogRecord.v1",
        "record_id": record_id,
        "content_type": content_type,
        "display_name": display_name,
        "aliases": [],
        "tags": _unique_strings([authority, publication_status, "factory-ingested"]),
        "publication": {
            "status": publication_status,
            "published_version": str(projection.get("pack_version") or "0"),
            "replaced_by": projection.get("supersedes") if isinstance(projection.get("supersedes"), str) else None,
        },
        "content_binding": {
            "pack_id": _identifier(projection.get("pack_id") or "tianxia.core.factory"),
            "pack_version": str(projection.get("pack_version") or "0"),
            "pack_hash": pack_hash,
        },
        "source": {
            "source_id": _identifier(f"source.{source_hash[:24]}"),
            "path": str(source.get("path") or ""),
            "anchor": source_anchor,
            "source_hash": source_hash,
        },
        "summary": summary[:8000],
        "legality": {
            "acquisition_channels": [_identifier(channel, "channel") for channel in channels],
            "prerequisites": prereqs,
            "incompatibilities": [],
            "minimum_cl": projection.get("minimum_cl") if isinstance(projection.get("minimum_cl"), int) else None,
            "realm_rules": {"realm": projection.get("realm")} if projection.get("realm") else {},
            "source_cl": {},
            "suppression": {},
        },
        "dependencies": [_identifier(x) for x in _unique_strings(projection.get("dependencies") or [])],
        "grants": grants,
        "execution_templates": execution,
        "display_projection": {
            "short_description": (summary or display_name)[:500],
            "full_description": summary or display_name,
            "surfaces": ["rules_catalog"],
            "sort_key": display_name.casefold(),
        },
        "compatibility": {
            "factory": {
                "producer": FACTORY_VERSION,
                "authority_classification": authority,
                "selected_authority": selected_authority,
                "unresolved_normalization_notes": notes,
                "retained_prerequisites": retained_prereqs,
                "retained_grants": retained_grants,
                **({"stage2_authority": deepcopy(raw_compatibility.get("factory", {}).get("stage2_authority"))} if isinstance(raw_compatibility.get("factory"), dict) and isinstance(raw_compatibility.get("factory", {}).get("stage2_authority"), dict) else {}),
                "raw_compatibility": raw_compatibility,
                "raw_projection": deepcopy(projection),
            },
            "gm_screen": {"consumer": CATALOG_GM_COMPATIBILITY_VERSION, "projection_status": "catalog-only-phase2r"},
        },
        "revision_history": [
            {"version": str(projection.get("pack_version") or "0"), "summary": "Canonicalized from pinned Factory structured source projection.", "previous_record_hash": None}
        ],
        "regression_tests": [
            {
                "test_id": _identifier(f"{record_id}.provenance"),
                "kind": "source-hash-equality",
                "input": {"source_path": str(source.get("path") or "")},
                "expected": {"source_hash": source_hash},
            }
        ],
        "record_hash": ZERO_HASH,
    }
    # Path ownership is a first-class typed relation for Subpaths/Traditions.
    # Keep it on the canonical projection as well as inside the raw source
    # envelope so downstream consumers never have to recover ownership from a
    # live catalog or from dependency ordering.
    raw_record = projection.get("raw_record") if isinstance(projection.get("raw_record"), dict) else {}
    for owner_field in ("owning_path_id", "parent_path_id"):
        owner_value = projection.get(owner_field)
        if not isinstance(owner_value, str) or not owner_value:
            owner_value = raw_record.get(owner_field)
        if owner_field == "parent_path_id" and not isinstance(owner_value, str):
            owner_value = raw_record.get("owning_path_id")
        if isinstance(owner_value, str) and owner_value:
            canonical[owner_field] = owner_value
    canonical["record_hash"] = canonical_record_hash(canonical)
    return canonical


def _normalise_user_locks(values: list[dict[str, Any]] | None, revision: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, value in enumerate(values or []):
        if not isinstance(value, dict):
            continue
        result.append({
            "lock_id": _identifier(value.get("lock_id") or f"lock.{index + 1}"),
            "field": str(value.get("field") or value.get("path") or f"unclassified.{index + 1}"),
            "value": value.get("value"),
            "created_revision": int(value.get("created_revision", revision)),
            **({"source": str(value["source"])} if value.get("source") is not None else {}),
        })
    return result


def _normalise_source_inputs(values: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    allowed = {"file", "url", "user_directive", "builder_handoff", "source_excerpt"}
    for index, value in enumerate(values or []):
        if not isinstance(value, dict):
            continue
        digest = value.get("sha256") or value.get("source_hash")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            # Unhashed inputs are not admitted to the canonical durable document.
            continue
        kind = value.get("kind") if value.get("kind") in allowed else "source_excerpt"
        result.append({
            "evidence_id": _identifier(value.get("evidence_id") or value.get("source_id") or f"evidence.{index + 1}"),
            "kind": kind,
            "path_or_reference": str(value.get("path_or_reference") or value.get("source_path") or value.get("source_anchor") or ""),
            "sha256": digest,
            **({"notes": str(value["notes"])} if value.get("notes") is not None else {}),
        })
    return result


def canonical_project_document(
    *,
    project_id: str,
    name: str,
    revision: int,
    status: str,
    created_at: str,
    updated_at: str,
    catalog_build_id: str,
    pack_locks: list[dict[str, Any]],
    user_locks: list[dict[str, Any]] | None = None,
    source_inputs: list[dict[str, Any]] | None = None,
    event_count: int = 0,
    head_hash: str | None = None,
    active_stage: int | None = None,
    stage_commits: list[dict[str, Any]] | None = None,
    generated_artifacts: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    acceptance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    packs = [
        {"pack_id": _identifier(lock["pack_id"]), "version": str(lock["version"]), "content_hash": str(lock.get("content_hash") or lock.get("pack_hash"))}
        for lock in sorted(pack_locks, key=lambda x: (x["pack_id"], x["version"]))
    ]
    lock_hash = sha256_json({"catalog_build_id": catalog_build_id, "packs": packs})
    valid_statuses = {"draft", "stage_1", "stage_2", "stage_3", "stage_4", "compile_ready", "candidate_ready", "simulated", "final_release_ready", "blocked", "archived"}
    canonical = {
        "schema_version": "TianxiaFoundry.CharacterProject.v1",
        "project_id": _identifier(project_id),
        "name": name,
        "revision": int(revision),
        "status": status if status in valid_statuses else "draft",
        "active_stage": active_stage,
        "created_at": created_at,
        "updated_at": updated_at,
        "factory_target": {
            "producer": FACTORY_VERSION,
            "candidate_schema": CANDIDATE_SCHEMA_VERSION,
            "payload_sha256": EXPECTED_FACTORY_HASH,
        },
        "gm_screen_target": {
            "consumer": GM_SCREEN_VERSION,
            "patch": GM_SCREEN_PATCH,
            "save_schema": GM_SCREEN_SAVE_SCHEMA,
        },
        "content_lock": {"catalog_build_id": _identifier(catalog_build_id or "catalog.unbuilt"), "lock_hash": lock_hash, "packs": packs},
        "user_locks": _normalise_user_locks(user_locks, revision),
        "source_inputs": _normalise_source_inputs(source_inputs),
        "stage_commits": stage_commits or [],
        "event_stream": {"path": "events.json", "count": int(event_count), "head_hash": head_hash},
        "generated_artifacts": generated_artifacts or [],
        "candidates": candidates or [],
        "acceptance": acceptance or [],
        "backup_policy": {"enabled": True, "retention_count": 10},
    }
    return canonical


def normalise_effective_point(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and {"kind", "character_cl", "order"}.issubset(value):
        return deepcopy(value)
    value = value if isinstance(value, dict) else {}
    if isinstance(value.get("cl"), int):
        return {"kind": "level", "character_cl": max(0, min(30, value["cl"])), "order": int(value.get("order", 0))}
    label = str(value.get("timing") or value.get("label") or "administrative")
    return {"kind": "other", "character_cl": int(value.get("character_cl", 0) or 0), "order": int(value.get("order", 0) or 0), "label": label[:200]}


def _event_source_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    source = record["source"]
    row = {
        "source_id": source["source_id"],
        "source_hash": source["source_hash"],
        "source_anchor": source["anchor"],
    }
    if source.get("path") is not None:
        row["source_path"] = source.get("path", "")
    if source.get("line_ranges"):
        row["line_ranges"] = source["line_ranges"]
    return [row]


def canonical_event_from_draft(
    *,
    event_id: str,
    project_id: str,
    project_revision: int,
    sequence: int,
    draft: dict[str, Any],
    subject_record: dict[str, Any],
    catalog_build_id: str,
    previous_event_hash: str | None,
    state_before_hash: str,
    state_after_hash: str,
    created_at: str,
    idempotency_key: str,
    supersedes_event_ids: list[str] | None = None,
    canonical_event_type: str | None = None,
    migration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_type = canonical_event_type or str(draft.get("event_type"))
    rid = subject_record["record_id"]
    created: list[str] = []
    updated: list[str] = []
    retired: list[str] = []
    if event_type == "acquire":
        created = [rid]
    elif event_type in {"evolve", "replace"}:
        updated = [rid]
        retired = _unique_strings((draft.get("payload") or {}).get("replaces_record_ids") or [])
    elif event_type == "retire":
        retired = [rid]
    binding = subject_record["content_binding"]
    canonical: dict[str, Any] = {
        "schema_version": "TianxiaFoundry.AdvancementEvent.v1",
        "event_id": _identifier(event_id),
        "project_id": _identifier(project_id),
        "project_revision": int(project_revision),
        "sequence": int(sequence),
        "event_type": event_type,
        "effective_point": normalise_effective_point(draft.get("effective_point")),
        "legal_channel": _identifier(draft.get("legal_channel") or draft.get("acquisition_channel") or "administrative", "channel"),
        "subject": {"record_id": rid, "content_type": subject_record["content_type"], "display_name": subject_record["display_name"]},
        "content_binding": {
            "pack_id": binding["pack_id"],
            "pack_version": binding["pack_version"],
            "pack_hash": binding["pack_hash"],
            "record_hash": subject_record["record_hash"],
            "catalog_build_id": _identifier(catalog_build_id),
        },
        "source_evidence": _event_source_evidence(subject_record),
        "created_records": created,
        "updated_records": updated,
        "retired_records": retired,
        "planner_response_id": draft.get("planner_response_id"),
        "supersedes_event_ids": supersedes_event_ids or [],
        "migration": migration,
        "idempotency_key": _identifier(idempotency_key),
        "previous_event_hash": previous_event_hash,
        "state_before_hash": state_before_hash,
        "state_after_hash": state_after_hash,
        "event_hash": ZERO_HASH,
        "created_at": created_at,
    }
    canonical["event_hash"] = canonical_event_hash(canonical)
    return canonical
