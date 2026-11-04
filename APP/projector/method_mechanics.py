"""Project an initially activated Method from authenticated causal evidence."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core import FoundryError, canonical_json
from non_sphere_authority.method_mechanics import METHOD_MECHANICS_SCHEMA


def validate_initial_method_mechanics(
    root_dir: Path,
    record: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Retain legacy acquisition-only semantics; require new activation proof."""
    authority = ((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
    mechanics = authority.get("method_mechanics")
    activations = [event for event in events if (event.get("advancement") or {}).get("kind") == "method_activation"]
    if mechanics is None and not activations:
        return None

    def invalid(reason: str) -> None:
        raise FoundryError(
            "PROJECTION_METHOD_MECHANICS_INVALID",
            "Initial Method mechanics require the exact source record and causal activation.",
            details={"method_id": record.get("record_id"), "reason": reason},
        )

    if not isinstance(mechanics, dict) or mechanics.get("schema") != METHOD_MECHANICS_SCHEMA:
        invalid("unsupported_authority")
    # Derive the installed version independently; a self-consistent rehash of
    # supplied modifiers cannot become mechanical authority.
    from non_sphere_authority.service import project_locked_method_catalog_records_from_authority

    expected = next((row for row in project_locked_method_catalog_records_from_authority(
        root_dir / "non_sphere_authority/authority", project_root=root_dir, mechanical=True,
    ) if row["record_id"] == record.get("record_id")), None)
    if expected is None or canonical_json(record) != canonical_json(expected):
        invalid("source_record_mismatch")
    acquisitions = [event for event in events if (event.get("advancement") or {}).get("kind") == "method_acquisition"]
    levels = [event for event in events if (event.get("advancement") or {}).get("kind") == "level_advance"]
    if len(activations) != 1 or len(acquisitions) != 1 or not levels:
        invalid("activation_or_acquisition_count")
    activation, acquisition = activations[0], acquisitions[0]
    advancement = activation.get("advancement") or {}
    calculation = advancement.get("calculation") or {}
    if (
        (activation.get("subject") or {}).get("record_id") != record["record_id"]
        or (acquisition.get("subject") or {}).get("record_id") != record["record_id"]
        or activation.get("legal_channel") != "method-activation"
        or advancement.get("target_cl") != 1
        or advancement.get("details") != {}
        or calculation.get("rule_id") != authority["rule_id"]
        or calculation.get("outputs") != {}
        or not (acquisition["sequence"] < activation["sequence"] < min(event["sequence"] for event in levels))
    ):
        invalid("activation_order_or_binding")
    return {
        "state": "active",
        "status": "active",
        "mechanical_projection": True,
        "activation_event_id": activation["event_id"],
        "acquisition_event_id": acquisition["event_id"],
        "mechanics": deepcopy(mechanics),
    }


def project_initial_method_mechanics(
    root_dir: Path,
    record: dict[str, Any],
    events: list[dict[str, Any]],
    packet_by_event: dict[str, str],
) -> dict[str, Any] | None:
    """Require actual projection packets in addition to source/causal validity."""
    validated = validate_initial_method_mechanics(root_dir, record, events)
    if validated is None:
        return None
    acquisition_id = validated.pop("acquisition_event_id")
    activation_id = validated["activation_event_id"]
    if acquisition_id not in packet_by_event or activation_id not in packet_by_event:
        raise FoundryError(
            "PROJECTION_METHOD_MECHANICS_INVALID",
            "Initial Method mechanics require acquisition and activation source packets.",
            details={"method_id": record.get("record_id"), "reason": "activation_order_or_binding"},
        )
    return {**validated, "source_packet_ids": [packet_by_event[acquisition_id], packet_by_event[activation_id]]}
