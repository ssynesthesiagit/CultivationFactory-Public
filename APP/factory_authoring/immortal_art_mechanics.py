"""Command4 source projection of authenticated constructed Immortal Arts."""
from __future__ import annotations

from typing import Any, Mapping

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_json
from project_store.service import ProjectStore


def immortal_action_text(art: Mapping[str, Any]) -> str:
    """Render compiled mechanics only; embedded native source costs stay out."""
    action = art.get("action_surface")
    if not isinstance(action, Mapping) or action.get("gm_review_required") or art.get("gm_review_required"):
        raise FoundryError("COMMAND4_IMMORTAL_MECHANICS_UNRESOLVED", "The Immortal Art needs a complete compiled action and any required GM review.")
    factors = action.get("factor_application")
    effective = factors.get("effective_effect") if isinstance(factors, Mapping) else None
    if not isinstance(effective, Mapping) or not effective:
        raise FoundryError("COMMAND4_IMMORTAL_MECHANICS_UNRESOLVED", "The Immortal Art has no compiled effective factor result.")
    cost = action.get("resource_cost")
    resource = action.get("resource_name")
    if type(cost) is not int or cost < 0 or cost != art.get("activation_cp") or resource not in {"Stamina", "Resonance", "Qi"}:
        raise FoundryError("COMMAND4_IMMORTAL_MECHANICS_UNRESOLVED", "The compiled Immortal Art cost is not an exact native resource amount.")
    activation = action.get("activation")
    bucket = {"Action": "action", "Bonus Action": "bonus_action", "Reaction": "reaction"}.get(activation)
    if bucket is None:
        raise FoundryError("COMMAND4_IMMORTAL_MECHANICS_UNRESOLVED", "The compiled Immortal Art activation is unsupported.")

    def text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (Mapping, list)):
            return canonical_json(value)
        return "" if value is None else str(value)

    fields = [
        ("Action Type", activation),
        ("Factory Combat Bucket", bucket),
        ("Factory Routing", "combat_action_row"),
        ("Timing", action.get("trigger") if bucket == "reaction" else activation),
        ("Cost", f"{cost} {resource}"),
        ("Range", action.get("range")),
        ("Area", action.get("area")),
        ("Target", action.get("target")),
        ("Roll/Save/Check", action.get("save_or_check")),
        ("DC Basis", action.get("dc_basis")),
        # The effective result retains the source effect and each added factor
        # under distinct typed keys. Do not drop or add the package twice.
        ("Effect", effective),
        ("Failure", action.get("failure")),
        ("Duration", action.get("duration")),
        ("Limit", action.get("limits")),
        ("Counterplay", action.get("counterplay")),
        ("Cleanup", action.get("cleanup")),
        ("Normalized Procedure", action.get("normalized_procedure")),
        ("Source Dependencies", (art.get("source") or {}).get("source_dependencies")),
    ]
    destruction = factors.get("destruction_factor")
    if isinstance(destruction, Mapping):
        fields.insert(9, ("Effective Damage", destruction.get("effective_damage_expression")))
        fields.append(("Successful Save Damage", destruction.get("successful_save")))
    return "\n".join([f"# {art['display_name']}", *[f"{label}: {text(value)}" for label, value in fields if text(value)]])


def load_immortal_action_binding(db: Database, project_id: str, record_id: str) -> dict[str, Any] | None:
    """Resolve the exact project lock and recompile against installed sources."""
    if not record_id.startswith("tianxia.constructed.immortal_art."):
        return None
    projects = ProjectStore(db)
    with db.connection() as conn:
        record = projects._resolve_locked_record(conn, project_id, record_id)
        if not isinstance(record, dict):
            raise FoundryError("COMMAND4_IMMORTAL_SOURCE_MISSING", "The Immortal Art has no immutable record in this project.", details={"record_id": record_id})
        projects._assert_constructed_art_snapshot_record(conn, project_id, record)
    art = record["compatibility"]["factory"]["constructed_art"]["art"]
    if art.get("owner_project_id") != project_id:
        raise FoundryError("COMMAND4_IMMORTAL_OWNER_MISMATCH", "The Immortal Art belongs to a different project.", details={"record_id": record_id})
    source = record["source"]
    description = immortal_action_text(art)
    return {
        "authority": "rederived_project_locked_immortal_art",
        "project_id": project_id,
        "record_id": record_id,
        "record_hash": record["record_hash"],
        "record_sha256": sha256_json(record),
        "action_surface_sha256": sha256_json(art["action_surface"]),
        "name": record["display_name"],
        "source": {"path": source["path"], "anchor": source["anchor"], "sha256": source["source_hash"]},
        "full_description": description,
        "source_text_sha256": sha256_bytes(description.encode("utf-8")),
        "grants_acquisition": False,
    }


def validate_immortal_action_candidate(db: Database, project_id: str, candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    supplied = candidate.get("constructed_immortal_source_binding")
    if supplied is None:
        return None
    record_id = candidate.get("record_id")
    if not isinstance(record_id, str):
        raise FoundryError("COMMAND4_IMMORTAL_SOURCE_INVALID", "A constructed candidate requires an exact record ID.")
    expected = load_immortal_action_binding(db, project_id, record_id)
    if expected is None or supplied != expected or any(candidate.get(key) != expected[key] for key in ("record_hash", "source", "name", "full_description")):
        raise FoundryError("COMMAND4_IMMORTAL_SOURCE_INVALID", "The candidate differs from its independently recompiled project-locked Immortal Art.", details={"record_id": record_id})
    return expected
