"""Verify exact recipient cadence riders against one explicit, live zone trigger.

Shared by the rider converter and its source tests. Native zone triggers already
deduplicate entry/start by recipient and turn. The conversion writes their
existing ``per_round`` field explicitly and removes only the complete matching
restatement. It adds no new damage or trigger and does not claim a previously
missing core effect has become automated.
"""
from __future__ import annotations

import copy
import re


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _damage(node: object) -> bool:
    if isinstance(node, dict):
        return node.get("type") == "damage" or any(_damage(v) for v in node.values())
    return isinstance(node, list) and any(_damage(v) for v in node)


def _independent_checkpoint(node: object) -> bool:
    """A zone's counter cannot govern a later condition tick or nested area."""
    if isinstance(node, dict):
        return (node.get("type") in {"ongoing", "zone", "summon"} or bool(node.get("deferred"))
                or any(node.get(key) for key in ("turn_start_effects", "turn_end_effects", "on_expire", "on_remove"))
                or any(_independent_checkpoint(value) for value in node.values()))
    return isinstance(node, list) and any(_independent_checkpoint(value) for value in node)


def convert(mechanic: dict, source_text: str) -> tuple[dict, list[dict]]:
    """Return safe typed zone-cadence restatements; leave ambiguous scopes intact."""
    result = copy.deepcopy(mechanic)
    if mechanic.get("options") or mechanic.get("modifier"):
        return result, []
    # One concentration-bound area cannot coexist with another cast by this
    # owner: native zone replacement supplies the scope the printed rider needs.
    if not (mechanic.get("duration") or {}).get("concentration"):
        return result, []
    zones = [(i, row) for i, row in enumerate(result.get("effects") or [])
             if isinstance(row, dict) and row.get("type") == "zone"]
    if len(zones) != 1:
        return result, []
    index, zone = zones[0]
    triggers = zone.get("triggers") or []
    if zone.get("deferred") or len(triggers) != 1:
        return result, []
    trigger = triggers[0]
    moments = set(trigger.get("on") or [])
    if (not moments or not moments <= {"enter", "start"} or not trigger.get("effects")
            or trigger.get("first_each_round") or trigger.get("once_per_creature")):
        return result, []
    if (_independent_checkpoint(trigger["effects"])
            or any(_damage(row) for i, row in enumerate(result.get("effects") or []) if i != index)):
        return result, []
    escaped_name = re.escape(_normalize(str(mechanic.get("name") or "")))
    damage = re.compile(r"a creature (?:takes|can take) (?:this )?damage(?: from (?:this aura|" + escaped_name +
                        r"))? only once per (turn|round)\.")
    affected = re.compile(r"a creature is affected(?: by this start-of-turn effect)?(?: only)? once per (turn|round)\.")
    receipts, kept = [], []
    source = _normalize(source_text)
    for rider_index, rider in enumerate(result.get("riders") or []):
        normalized = _normalize(rider) if isinstance(rider, str) else ""
        damage_match = damage.fullmatch(normalized)
        match = damage_match or affected.fullmatch(normalized)
        if (not match or normalized not in source or damage_match and not _damage(trigger["effects"])
                or trigger.get("per_round") and match[1] != "round"):
            kept.append(rider)
            continue
        per_round = match[1] == "round"
        behavior = "verified_restatement" if bool(trigger.get("per_round")) == per_round else "repaired_behavior"
        trigger["per_round"] = per_round
        receipts.append({
            "pattern": "recipient_rate_limit", "rider": rider,
            "path": f"/riders/{rider_index}",
            "effect_paths": [f"/effects/{index}/triggers/0/per_round"],
            "engine_seam": "factory_compiler._zone_abilities -> zones.fire_trigger/_run (per_round)",
            "behavior": behavior,
        })
    result["riders"] = kept
    return result, receipts
