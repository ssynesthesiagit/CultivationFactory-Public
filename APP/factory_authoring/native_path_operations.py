"""Source slices for native features with several independently timed operations.

These are mechanics bindings, not acquired records or executable action grants.
The complete authenticated parent remains attached so a slice cannot discard
shared restrictions, upgrades, asset limits, or authority comparisons.
"""
from __future__ import annotations

from copy import deepcopy
import re
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, sha256_bytes, sha256_json
from factory_authoring.native_path_mechanics import native_path_binding

_PREFIX = "tianxia.path.spirit_awakening.feature."
# Heading boundaries are from the current canonical Spirit chapter. Costs and
# other mechanics are extracted verbatim below, never inferred from the names.
_SPECS = {
    _PREFIX + "spiritual_sense": (
        ("perceive", "Spiritual Sense", None, "## Read the Spirit", "passive", None),
        ("read_the_spirit", "Read the Spirit", "## Read the Spirit", None, "action", "Action"),
    ),
    _PREFIX + "soul_vessel": (
        ("create_vessel", "Create or Replace the Soul Vessel", "## Create or Replace the Vessel", "## Create a Vessel Imprint", "procedure", "10 minutes"),
        ("create_imprint", "Create a Vessel Imprint", "## Create a Vessel Imprint", "### Vessel Ward", "action", "Action"),
        ("vessel_ward", "Vessel Ward", "### Vessel Ward", "### Sympathetic Rite at CL13", "reaction", "Reaction"),
    ),
    _PREFIX + "spiritual_exorcism": (
        ("battlefield", "Battlefield Exorcism", "## Battlefield Exorcism", "## Deep Exorcism Rite", "action", "Action"),
        ("deep_rite", "Deep Exorcism Rite", "## Deep Exorcism Rite", None, "procedure", "10 minutes"),
    ),
}
_LABEL = re.compile(r"^\*\*(Action Type|Time|Cost):\*\*\s*(.*?)\s*$")


def _invalid(record_id: str, message: str) -> FoundryError:
    return FoundryError("COMMAND4_NATIVE_OPERATION_SOURCE_INVALID", message, details={"record_id": record_id})


def _boundary(lines: list[str], heading: str | None, default: int, record_id: str) -> int:
    if heading is None:
        return default
    matches = [i for i, line in enumerate(lines) if line == heading]
    if len(matches) != 1:
        raise _invalid(record_id, "A native operation heading must occur exactly once in its authenticated source.")
    return matches[0]


def native_operation_bindings(root_dir: Path, record_id: str) -> list[dict[str, Any]]:
    """Partition known mixed features while retaining their complete source.

    An unrecognized parent has no operation adapter. A recognized parent with
    changed headings or timing fails closed rather than producing fewer rows.
    No default resource cost, duration, CL, or execution readiness is assigned.
    """
    specs = _SPECS.get(record_id)
    if specs is None:
        return []
    parent = native_path_binding(root_dir, record_id)
    if parent is None:
        raise _invalid(record_id, "The native operation has no authenticated parent feature.")
    source = parent["full_description"]
    lines = source.splitlines()
    covered_activations: set[int] = set()
    result = []
    for slug, name, start, end, kind, timing in specs:
        first = _boundary(lines, start, 0, record_id)
        stop = _boundary(lines, end, len(lines), record_id)
        if first >= stop:
            raise _invalid(record_id, "Native operation source boundaries must be ordered and nonempty.")
        labels: dict[str, list[str]] = {}
        activations = []
        for index in range(first, stop):
            match = _LABEL.fullmatch(lines[index])
            if match:
                label, value = match.groups()
                labels.setdefault(label, []).append(value)
                if label in {"Action Type", "Time"}:
                    activations.append(index)
        if kind == "passive":
            if activations or "Spiritual Sense is always active unless suppressed." not in lines[first:stop]:
                raise _invalid(record_id, "The passive operation must retain its explicit always-active source rule.")
        else:
            expected_label = "Time" if kind == "procedure" else "Action Type"
            if len(activations) != 1 or labels.get(expected_label) != [timing]:
                raise _invalid(record_id, "Each native operation must retain exactly its printed activation timing.")
        if covered_activations.intersection(activations):
            raise _invalid(record_id, "A printed activation cannot belong to two operations.")
        covered_activations.update(activations)
        if len(labels.get("Cost", [])) > 1:
            raise _invalid(record_id, "A native operation cannot merge independently printed costs.")
        text = "\n".join(lines[first:stop]).strip()
        result.append({
            "schema_version": "TianxiaFoundry.NativePathOperationBinding.v1",
            "operation_id": record_id + ".operation." + slug,
            "parent_record_id": record_id,
            "name": name,
            "action_type": kind,
            "printed_timing": timing,
            "printed_cost": next(iter(labels.get("Cost", [])), None),
            "source_line_start": first + 1,
            "source_line_end": stop,
            "operation_rules_text": text,
            "operation_rules_sha256": sha256_bytes(text.encode("utf-8")),
            "parent_binding": deepcopy(parent),
            "parent_binding_sha256": sha256_json(parent),
            "grants_acquisition": False,
            "execution_authority": False,
        })
    all_activations = {
        i for i, line in enumerate(lines)
        if (match := _LABEL.fullmatch(line)) and match.group(1) in {"Action Type", "Time"}
    }
    if all_activations != covered_activations:
        raise _invalid(record_id, "Every printed activation in a mixed native feature must remain represented.")
    return result


def validate_native_operation_binding(root_dir: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the whole adapter; matching hashes supplied by callers do not suffice."""
    parent_id = supplied.get("parent_record_id")
    if not isinstance(parent_id, str):
        raise _invalid("", "A native operation must identify its parent feature.")
    matches = [row for row in native_operation_bindings(root_dir, parent_id) if row["operation_id"] == supplied.get("operation_id")]
    if len(matches) != 1 or matches[0] != supplied:
        raise _invalid(parent_id, "The operation differs from its independently rederived source binding.")
    return matches[0]


def operation_action_text(binding: Mapping[str, Any]) -> str:
    """Add only the source-derived routing labels needed by the action parser."""
    text = binding["operation_rules_text"]
    if binding["action_type"] == "procedure":
        return "Action Type: Ritual Procedure\nFactory Routing: procedure_ledger_not_combat_action\nTiming: " + binding["printed_timing"] + "\n\n" + text
    if binding["action_type"] == "passive":
        return "Action Type: Passive\n\n" + text
    return text


def expand_native_operation_cards(root_dir: Path, card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project all operations from an acquired parent, preserving its identity."""
    bindings = native_operation_bindings(root_dir, str(card.get("record_id") or ""))
    if not bindings:
        return [deepcopy(dict(card))]
    parent = bindings[0]["parent_binding"]
    if card.get("full_description") != parent["full_description"] or card.get("display_name") != parent["name"] or card.get("source") != parent["source"]:
        raise _invalid(parent["record_id"], "The acquired parent card must match the operation adapter's authenticated source.")
    rows = []
    for binding in bindings:
        row = deepcopy(dict(card))
        row.pop("native_source_binding", None)
        row.update({
            "record_id": binding["operation_id"],
            "record_hash": sha256_json(binding),
            "display_name": binding["name"],
            "one_line_description": binding["name"] + " — operation of " + parent["name"],
            "full_description": operation_action_text(binding),
            "native_operation_source_binding": deepcopy(binding),
            "acquisition_parent_record_id": parent["record_id"],
            "acquisition_parent_record_hash": card.get("record_hash"),
            "_source_authority_error": {"code": "NATIVE_OPERATION_REQUIRES_PARENT_ACQUISITION_PROOF"},
        })
        rows.append(row)
    return rows


def validate_native_operation_candidate(root_dir: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    supplied = candidate.get("native_operation_source_binding")
    if not isinstance(supplied, dict):
        raise _invalid(str(candidate.get("record_id") or ""), "The native operation candidate has no source binding.")
    binding = validate_native_operation_binding(root_dir, supplied)
    expected = {
        "record_id": binding["operation_id"], "name": binding["name"],
        "record_hash": sha256_json(binding), "source": binding["parent_binding"]["source"],
        "full_description": operation_action_text(binding),
        "acquisition_parent_record_id": binding["parent_record_id"],
    }
    if any(candidate.get(key) != value for key, value in expected.items()):
        raise _invalid(binding["parent_record_id"], "The native operation candidate differs from its derived source and parent identity.")
    return binding


def validate_operation_acquisition(candidate: Mapping[str, Any], packet: Mapping[str, Any], event: Mapping[str, Any], locked_parent: Mapping[str, Any]) -> None:
    """Check a packet against an independently chain-verified acquisition event.

    The caller must obtain event and locked_parent from the authoritative project
    store. Equal-Path events may name another Path's representative feature.
    """
    parent_id = str(candidate.get("acquisition_parent_record_id") or "")
    expected_packet = f"packet.stage2.{event.get('sequence', 0):03d}.{str(event.get('event_hash') or '')[:16]}"
    advancement = event.get("advancement") or {}
    bindings = [row for row in advancement.get("authority_bindings") or [] if row.get("role") == "path_automatic_feature_authority" and row.get("record_id") == parent_id]
    if (
        locked_parent.get("record_id") != parent_id
        or locked_parent.get("record_hash") != candidate.get("acquisition_parent_record_hash")
        or len(bindings) != 1
        or bindings[0].get("record_hash") != locked_parent.get("record_hash")
        or advancement.get("kind") != "level_advance"
        or packet.get("packet_id") != expected_packet
        or any(packet.get(key) != event.get(key) for key in ("sequence", "event_id", "event_hash"))
        or packet.get("target_cl") != advancement.get("target_cl")
        or packet.get("advancement_kind") != advancement.get("kind")
        or packet.get("record_id") != (event.get("subject") or {}).get("record_id")
        or packet.get("record_hash") != (event.get("content_binding") or {}).get("record_hash")
    ):
        raise _invalid(parent_id, "The operation must retain the exact packet for an event that actually acquired its parent feature.")
