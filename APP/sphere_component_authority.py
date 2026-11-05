"""Canonical automatic-component packets for acquired CAT3 Spheres."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core import FoundryError, sha256_json


SCHEMA_VERSION = "TianxiaFoundry.SphereAutomaticComponentAuthority.v1"
_COMPONENT_FLAGS = {
    "automatic_grant": True,
    "owner_removable": False,
    "counts_as_talent_choice": False,
    "counts_as_advancement_talent": False,
    "counts_as_training_talent": False,
}


def _component_source(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("source_matrix_provenance")
    if isinstance(value, dict):
        source = value
    else:
        value = row.get("source_provenance")
        if isinstance(value, dict):
            source = value
        else:
            value = row.get("source_context")
            if isinstance(value, dict):
                source = value
            else:
                value = row.get("source_reference")
                if isinstance(value, dict):
                    source = value
                else:
                    value = row.get("source")
                    source = value if isinstance(value, dict) else {}
    # Keep the packet's source evidence identity, not compiler diagnostics or
    # QA prose (some historical diagnostics contain forbidden display tokens).
    identity_keys = {
        "path", "anchor", "source_hash", "source_path", "source_anchor",
        "source_file_sha256", "source_authority_sha256",
        "source_record_commitment_sha256", "source_matrix_record_commitment_sha256",
        "source_pack", "source_section", "source_version", "source_column",
        "source_line", "source_line_start", "source_line_end",
    }
    return {key: deepcopy(source[key]) for key in sorted(identity_keys) if key in source}


def _canonical_component(parent_sphere_id: str, row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_INVALID", "A Sphere automatic-component row is not an object.")
    component_id = row.get("runtime_component_id") or row.get("component_id") or row.get("base_ability_id") or row.get("candidate_record_id")
    if not isinstance(component_id, str) or not component_id:
        raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_ID_MISSING", "A Sphere automatic component lacks a stable runtime component ID.", details={"parent_sphere_id": parent_sphere_id})
    text = row.get("player_rules_text") or row.get("full_exact_source_text") or row.get("full_description") or row.get("effect")
    if not isinstance(text, str) or not text.strip():
        raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_TEXT_MISSING", "A Sphere automatic component lacks exact player-facing source text.", details={"parent_sphere_id": parent_sphere_id, "component_id": component_id})
    structured = row.get("source_component_structured_fields")
    if not isinstance(structured, dict):
        structured = row.get("structured_fields") if isinstance(row.get("structured_fields"), dict) else {}
    component: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "component_id": component_id,
        "parent_sphere_id": parent_sphere_id,
        "display_name": row.get("display_name") or row.get("source_component_name") or component_id,
        "player_rules_text": text,
        "structured_fields": deepcopy(structured),
        **deepcopy(_COMPONENT_FLAGS),
        "source": _component_source(row),
        "source_component_name": row.get("source_component_name") or row.get("display_name") or component_id,
        "source_record_id": row.get("source_row_id") or row.get("candidate_record_id") or component_id,
        "source_record_commitment_sha256": row.get("record_commitment_sha256") or row.get("source_record_commitment_sha256"),
    }
    owner_ruling = row.get("owner_ruling")
    if isinstance(owner_ruling, dict):
        component["owner_ruling"] = deepcopy(owner_ruling)
    if isinstance(row.get("owner_ruling_id"), str):
        component["owner_ruling_id"] = row["owner_ruling_id"]
    unsigned = {key: value for key, value in component.items() if key != "component_hash"}
    component["component_hash"] = sha256_json(unsigned)
    return component


def build_sphere_automatic_component_authority(
    parent_sphere_id: str,
    rows: list[dict[str, Any]],
    *,
    source_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        component = _canonical_component(parent_sphere_id, row)
        prior = by_id.get(component["component_id"])
        if prior is not None:
            if prior["component_hash"] != component["component_hash"]:
                raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_CONFLICT", "Duplicate Sphere component IDs have different authoritative bytes.", details={"parent_sphere_id": parent_sphere_id, "component_id": component["component_id"]})
            continue
        by_id[component["component_id"]] = component
        components.append(component)
    components.sort(key=lambda item: item["component_id"])
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "parent_sphere_id": parent_sphere_id,
        "component_ids": [item["component_id"] for item in components],
        "components": components,
        "source_identity": deepcopy(source_identity or {}),
    }
    return {**unsigned, "package_hash": sha256_json(unsigned)}


def _raw_component_rows(record: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = [record]
    raw_record = record.get("raw_record")
    if isinstance(raw_record, dict):
        candidates.append(raw_record)
    factory = (record.get("compatibility") or {}).get("factory")
    if isinstance(factory, dict):
        raw_projection = factory.get("raw_projection")
        if isinstance(raw_projection, dict):
            candidates.append(raw_projection)
            projected_raw_record = raw_projection.get("raw_record")
            if isinstance(projected_raw_record, dict):
                candidates.append(projected_raw_record)
    for candidate in candidates:
        packet = candidate.get("automatic_component_authority")
        if isinstance(packet, dict):
            rows = packet.get("components")
            return ([row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []), packet
    for candidate in candidates:
        for key in ("resolved_automatic_base_abilities", "automatic_base_abilities"):
            rows = candidate.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)], {}
    return [], {}


def normalize_sphere_automatic_components(record: dict[str, Any], *, acquisition_event: dict[str, Any] | None = None) -> dict[str, Any]:
    parent_sphere_id = str(record.get("record_id") or record.get("canonical_sphere_id") or "")
    if not parent_sphere_id:
        raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_PARENT_MISSING", "A Sphere automatic-component packet lacks its parent Sphere ID.")
    rows, supplied_packet = _raw_component_rows(record)
    source_identity = (
        deepcopy(supplied_packet.get("source_identity"))
        if isinstance(supplied_packet.get("source_identity"), dict)
        else record.get("source") if isinstance(record.get("source"), dict) else {}
    )
    packet = build_sphere_automatic_component_authority(parent_sphere_id, rows, source_identity=source_identity)
    supplied_hash = supplied_packet.get("package_hash") if isinstance(supplied_packet, dict) else None
    if isinstance(supplied_hash, str) and supplied_hash != packet["package_hash"]:
        raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_PACKET_HASH_INVALID", "The Sphere automatic-component packet does not match its canonical component bytes.", details={"parent_sphere_id": parent_sphere_id, "expected": supplied_hash, "actual": packet["package_hash"]})
    packet["parent_record_hash"] = record.get("record_hash")
    if acquisition_event:
        packet["acquisition"] = {
            "parent_event_id": acquisition_event.get("event_id"),
            "acquisition_cl": (acquisition_event.get("advancement") or {}).get("target_cl"),
            "legal_channel": acquisition_event.get("legal_channel"),
            "content_binding": deepcopy(acquisition_event.get("content_binding") or {}),
        }
    return packet


def attach_sphere_automatic_component_receipt(state: dict[str, Any], record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    packet = normalize_sphere_automatic_components(record, acquisition_event=event)
    receipts = state.setdefault("automatic_sphere_component_receipts", [])
    existing = next((row for row in receipts if row.get("parent_sphere_id") == packet["parent_sphere_id"]), None)
    if existing:
        if existing.get("package_hash") != packet.get("package_hash") or existing.get("parent_record_hash") != packet.get("parent_record_hash"):
            raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_CONFLICT", "The same acquired Sphere was presented with conflicting automatic-component authority.", details={"parent_sphere_id": packet["parent_sphere_id"]})
        return packet
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "parent_sphere_id": packet["parent_sphere_id"],
        "parent_record_hash": packet.get("parent_record_hash"),
        "package_hash": packet["package_hash"],
        "component_ids": deepcopy(packet["component_ids"]),
        "components": deepcopy(packet["components"]),
        "acquisition": deepcopy(packet.get("acquisition") or {}),
    }
    receipts.append(receipt)
    components = state.setdefault("automatic_sphere_components", [])
    by_id = {row.get("component_id"): row for row in components if isinstance(row, dict)}
    for component in receipt["components"]:
        prior = by_id.get(component["component_id"])
        if prior is not None and prior.get("component_hash") != component.get("component_hash"):
            raise FoundryError("SPHERE_AUTOMATIC_COMPONENT_CONFLICT", "A runtime Sphere component ID resolved to conflicting authority.", details={"component_id": component["component_id"]})
        if prior is None:
            components.append(deepcopy(component))
    receipts.sort(key=lambda row: row["parent_sphere_id"])
    components.sort(key=lambda row: row["component_id"])
    return packet


__all__ = [
    "SCHEMA_VERSION",
    "attach_sphere_automatic_component_receipt",
    "build_sphere_automatic_component_authority",
    "normalize_sphere_automatic_components",
]
