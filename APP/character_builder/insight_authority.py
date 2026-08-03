from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


INSIGHT_AUTHORITY_TYPES = (
    "General",
    "Sphere",
    "Path",
    "Method",
    "Foundation",
    "Background-Origin",
    "Item-Equipment",
    "Special",
    "Unresolved",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def resolve_insight_occurrences(
    occurrences: list[dict[str, Any]], *, record_id: str
) -> dict[str, Any]:
    """Resolve duplicate source occurrences without inventing product IDs.

    A collision is safe only when exact source metadata identifies one current
    record and every other occurrence explicitly supersedes to that canonical
    ID. Anything else remains one quarantined canonical record.
    """
    normalized = []
    for occurrence in occurrences:
        raw = deepcopy(occurrence.get("raw_record") or {})
        source_reference = deepcopy(occurrence.get("source_reference") or {})
        normalized.append({"raw_record": raw, "source_reference": source_reference})
    if not normalized:
        raise ValueError("At least one Insight source occurrence is required.")

    active = [
        row for row in normalized
        if _text(row["raw_record"].get("superseded_by")) == ""
        and _text(row["raw_record"].get("execution_status")).casefold() != "superseded_source_record"
    ]
    superseded = [row for row in normalized if row not in active]
    exact_supersession = (
        len(active) == 1
        and all(_text(row["raw_record"].get("superseded_by")) == record_id for row in superseded)
    )
    resolved = len(normalized) == 1 or exact_supersession
    selected = active[0] if resolved and active else normalized[0]
    source_occurrences = [
        {
            **deepcopy(row["source_reference"]),
            "source_record_id": _text(row["raw_record"].get("record_id")) or record_id,
            "execution_status": _text(row["raw_record"].get("execution_status")),
            "superseded_by": _text(row["raw_record"].get("superseded_by")) or None,
        }
        for row in normalized
    ]
    return {
        "record_id": record_id,
        "raw_record": deepcopy(selected["raw_record"]),
        "source_reference": deepcopy(selected["source_reference"]),
        "source_occurrences": source_occurrences,
        "source_occurrence_count": len(source_occurrences),
        "collision_disposition": (
            "UNIQUE_CANONICAL_INSIGHT"
            if len(normalized) == 1
            else "CONSOLIDATED_EXPLICIT_SUPERSESSION"
            if exact_supersession
            else "UNRESOLVED_DUPLICATE_INSIGHT_ID"
        ),
        "resolved": resolved,
    }


def classify_insight_authority(
    raw_record: dict[str, Any], *, record_id: str, source_reference: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Classify one Insight from explicit source fields only.

    The ordering is deliberate: an explicit mechanical binding controls over a
    descriptive "general" label. Missing or conflicting source authority never
    inherits General.
    """
    raw = deepcopy(raw_record) if isinstance(raw_record, dict) else {}
    bindings: list[dict[str, str]] = []
    field_types = (
        ("sphere", "Sphere"),
        ("path", "Path"),
        ("method", "Method"),
        ("foundation", "Foundation"),
        ("background", "Background-Origin"),
        ("origin", "Background-Origin"),
        ("item", "Item-Equipment"),
        ("equipment", "Item-Equipment"),
    )
    for field, authority_type in field_types:
        value = raw.get(field)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if _text(item):
                bindings.append({"authority_type": authority_type, "field": field, "binding_id": _text(item), "binding_role": "controlling"})

    legal_paths = raw.get("legal_path_requirements")
    prerequisite_paths: list[str] = []
    if isinstance(legal_paths, list):
        for path_id in legal_paths:
            if _text(path_id):
                prerequisite_paths.append(_text(path_id))
                bindings.append({"authority_type": "Path", "field": "legal_path_requirements", "binding_id": _text(path_id), "binding_role": "prerequisite"})

    controlling = sorted({row["authority_type"] for row in bindings if row["binding_role"] == "controlling"})
    category = _text(raw.get("category"))
    source_family = _text(raw.get("source_family"))
    tags = {_text(tag).casefold() for tag in (raw.get("tags") or []) if _text(tag)}
    special = (
        _text(raw.get("spirit_relevance")).casefold() not in {"", "none"}
        or _text(raw.get("body_relevance")).casefold() not in {"", "none"}
        or "special" in category.casefold()
        or bool(tags & {"special", "forbidden", "daemonic", "covenant"})
    )

    if len(controlling) == 1:
        authority_type = controlling[0]
        controlling_fields = sorted({row["field"] for row in bindings if row["binding_role"] == "controlling"})
        reason = f"Explicit source binding controls: {', '.join(controlling_fields)}."
        code = "EXPLICIT_INSIGHT_BINDING"
    elif len(controlling) > 1:
        authority_type = "Unresolved"
        reason = f"Conflicting explicit source bindings require owner/source adjudication: {', '.join(controlling)}."
        code = "UNRESOLVED_INSIGHT_CLASSIFICATION"
    elif special:
        authority_type = "Special"
        reason = "Explicit source metadata marks a special, Spirit-facing, Body-facing, forbidden, daemonic, or covenant relationship."
        code = "EXPLICIT_SPECIAL_INSIGHT_METADATA"
    elif "general" in category.casefold() or "general" in source_family.casefold():
        authority_type = "General"
        reason = "The source explicitly labels this Insight General and supplies no stronger typed binding."
        code = "EXPLICIT_GENERAL_INSIGHT_METADATA"
    else:
        authority_type = "Unresolved"
        reason = "The source supplies no explicit typed binding or General classification."
        code = "UNRESOLVED_INSIGHT_CLASSIFICATION"

    source_payload = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": "TianxiaFoundry.InsightSourceAuthority.v1",
        "record_id": record_id,
        "authority_type": authority_type,
        "binding_records": bindings,
        "prerequisites": "; ".join(filter(None, [_text(raw.get("prerequisites")), f"Legal Paths: {', '.join(prerequisite_paths)}" if prerequisite_paths else ""])),
        "preference_only": True,
        "classification_code": code,
        "reason": reason,
        "source_reference": {
            "source_file": _text((source_reference or {}).get("source_file")) or _text(raw.get("source_file")),
            "source_status": _text((source_reference or {}).get("source_status")) or _text(raw.get("source_status")),
            "source_record_id": _text(raw.get("record_id")) or record_id,
            "source_record_sha256": hashlib.sha256(source_payload).hexdigest(),
            **({"source_file_sha256": _text(source_reference.get("source_file_sha256"))} if source_reference and _text(source_reference.get("source_file_sha256")) else {}),
            **({"source_anchor": _text(source_reference.get("source_anchor"))} if source_reference and _text(source_reference.get("source_anchor")) else {}),
        },
    }
