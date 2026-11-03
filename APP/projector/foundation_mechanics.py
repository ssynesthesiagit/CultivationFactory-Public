"""Validate initial Foundation effects from the installed source and causal events."""
from copy import deepcopy

from app.core import FoundryError, canonical_json
from non_sphere_authority.foundation_mechanics import (
    initial_foundation_mechanics_for_record, installed_foundation_state,
)


def validate_initial_foundation_mechanics(record, events):
    authority = ((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
    acquisitions = [event for event in events if (event.get("advancement") or {}).get("kind") == "foundation_acquisition"]

    def invalid(reason):
        raise FoundryError("PROJECTION_FOUNDATION_MECHANICS_INVALID", "Initial Foundation mechanics require exact source and causal installation evidence.", details={"record_id": record.get("record_id"), "reason": reason}, status_code=409)

    if authority.get("initial_foundation_mechanics") is None:
        from non_sphere_authority.foundation_mechanics import FOUNDATION_MECHANICS_PACK_VERSION
        if (record.get("content_binding") or {}).get("pack_version") == FOUNDATION_MECHANICS_PACK_VERSION:
            invalid("missing_installed_authority")
        if any(((event.get("advancement") or {}).get("calculation") or {}).get("outputs", {}).get("initial_foundation_mechanics") is not None for event in acquisitions):
            invalid("legacy_authority_cannot_install_mechanics")
        return None
    if len(acquisitions) != 1:
        invalid("acquisition_count")
    acquisition = acquisitions[0]
    adv = acquisition["advancement"]
    prior = [event for event in events if event["sequence"] < acquisition["sequence"]]
    paths = [(event.get("subject") or {}).get("record_id") for event in prior if (event.get("advancement") or {}).get("kind") == "path_acquisition"]
    levels = [event["advancement"]["target_cl"] for event in prior if (event.get("advancement") or {}).get("kind") == "level_advance"]
    if (
        (acquisition.get("subject") or {}).get("record_id") != record["record_id"]
        or acquisition.get("legal_channel") != "foundation-selection"
        or adv.get("target_cl") != 5 or levels != [1, 2, 3, 4, 5]
        or set(adv.get("details") or {}) - {"stage"}
        or (adv.get("calculation") or {}).get("rule_id") != authority["rule_id"]
        or any((event.get("advancement") or {}).get("kind") in {"foundation_expression", "foundation_stage"} for event in events)
    ):
        invalid("installation_timing_or_binding")
    mechanics = initial_foundation_mechanics_for_record(record, paths, stage=(adv.get("details") or {}).get("stage"))
    actual = (adv.get("calculation") or {}).get("outputs") or {}
    if canonical_json(actual.get("initial_foundation_mechanics")) != canonical_json(mechanics):
        invalid("installed_state_differs_from_source")
    # Validate the source contribution in the real calculator's outputs;
    # never calculate an alternate character total for the sheet.
    from stage2.service import _formula_value, _pb
    # A build-state pool may rise only as far as its maximum rose in the same
    # event (level advance, Method/Foundation/equipment modifier); any larger
    # rise is a refill, which no source may grant.
    previous_maximum: dict[str, int] = {}
    for event in sorted(events, key=lambda row: row["sequence"]):
        advancement = event.get("advancement") or {}
        output = (advancement.get("calculation") or {}).get("outputs") or {}
        resources_after = output.get("resources_after") or {}
        if event["sequence"] < acquisition["sequence"]:
            for resource_id, resource in resources_after.items():
                previous_maximum[resource_id] = int(resource.get("maximum", 0))
            continue
        context = {"pb": _pb(advancement["target_cl"])}
        hp = output.get("hp_after")
        if hp is not None:
            expected = sum(_formula_value(modifier["formula"], context)[0] for modifier in mechanics["hp_maximum_modifiers"])
            if hp.get("foundation_delta") != expected:
                invalid("hp_source_contribution")
        for resource_id, resource in resources_after.items():
            expected = sum(_formula_value(modifier["formula"], context)[0] for modifier in mechanics["resource_modifiers"] if modifier["resource_id"] == resource_id)
            maximum = int(resource.get("maximum", 0))
            allowed_rise = max(0, maximum - previous_maximum.get(resource_id, maximum))
            if resource.get("foundation_delta") != expected or resource.get("current") - resource.get("current_before") > allowed_rise:
                invalid("pool_source_contribution_or_refill")
            previous_maximum[resource_id] = maximum
    return {
        **installed_foundation_state(mechanics, record["record_id"], acquisition["event_id"]),
        "mechanical_projection": True, "acquisition_event_id": acquisition["event_id"],
        "mechanics": deepcopy(mechanics),
    }


def project_initial_foundation_mechanics(record, events, packet_by_event):
    result = validate_initial_foundation_mechanics(record, events)
    if result is None:
        return None
    event_id = result["acquisition_event_id"]
    if event_id not in packet_by_event:
        raise FoundryError("PROJECTION_FOUNDATION_MECHANICS_INVALID", "Foundation installation requires its actual source packet.", status_code=409)
    result["source_packet_ids"] = [packet_by_event[event_id]]
    return result
