"""Convert source-checked cadence riders to existing zone or reaction limits.

Shared by the rider converter and its source tests. The outer conversion chain
binds each receipt to the complete source-text and input-record hashes. Only a
complete sentence with an unambiguous, executable recipient is retired.
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


def _convert_recipient(mechanic: dict, source_text: str) -> tuple[dict, list[dict]]:
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


def _convert_reaction_round(mechanic: dict, source_text: str) -> tuple[dict, list[dict]]:
    """Limit a single generic reaction, not an action, option, or modifier.

    Sealed trigger qualifiers take precedence over use_limit in the compiler.
    Do not remove a rider if that seal would mask the new field, or if an
    explicit once value would override it. Modifier limits use a different
    owner-turn clock and cannot safely represent a calendar-round limit.
    """
    result = copy.deepcopy(mechanic)
    activation = mechanic.get("activation") or {}
    effects = mechanic.get("effects") or []
    qualifiers = activation.get("trigger_qualifiers")
    if (activation.get("economy") != "reaction" or not activation.get("trigger")
            or mechanic.get("modifier") or mechanic.get("options")
            or len(effects) != 1 or not isinstance(effects[0], dict)
            or effects[0].get("deferred")
            or mechanic.get("use_limit") not in (None, "", "none", "once_per_round")
            or mechanic.get("once") not in (None, "round")
            or (qualifiers is not None and (not isinstance(qualifiers, dict) or qualifiers.get("once") != "round"))):
        return result, []
    name = _normalize(str(mechanic.get("name") or ""))
    if not name:
        return result, []
    sentence = re.compile(r"(?:you (?:may|can) )?use " + re.escape(name)
                          + r" (?:only |at most )?once per round\.")
    def printed_sentence(rider: str) -> bool:
        # Do not match a suffix of a negation or qualification in the source.
        pattern = r"(?:^|(?<=[.!?])\s+)" + re.escape(_normalize(rider)) + r"(?=$|\s+)"
        return any(re.search(pattern, _normalize(line.lstrip(" -*•\t")))
                   for line in source_text.splitlines())

    matching = [i for i, rider in enumerate(mechanic.get("riders") or [])
                if isinstance(rider, str) and sentence.fullmatch(_normalize(rider))
                and printed_sentence(rider)]
    # Two identical limits are not a reliable one-to-one source receipt.
    if len(matching) != 1:
        return result, []
    from combat.reaction_triggers import classify_mechanic_all

    if not any(match.runnable for match in classify_mechanic_all(mechanic)):
        return result, []
    index = matching[0]
    rider = result["riders"].pop(index)
    behavior = ("verified_restatement" if mechanic.get("use_limit") == "once_per_round"
                or qualifiers and qualifiers.get("once") == "round" else "repaired_behavior")
    result["use_limit"] = "once_per_round"
    return result, [{
        "pattern": "reaction_round_limit", "rider": rider, "path": f"/riders/{index}",
        "effect_paths": ["/use_limit"],
        "engine_seam": "factory_compiler._generic_reaction -> typed_reactions._once_used/_spend_generic",
        "behavior": behavior,
    }]


def convert(mechanic: dict, source_text: str) -> tuple[dict, list[dict]]:
    """Plan limits independently while retaining original rider receipt indices."""
    result, receipts = _convert_recipient(mechanic, source_text)
    removed = {int(receipt["path"].rsplit("/", 1)[1]) for receipt in receipts}
    remaining = [index for index in range(len(mechanic.get("riders") or [])) if index not in removed]
    result, reaction_receipts = _convert_reaction_round(result, source_text)
    for receipt in reaction_receipts:
        index = int(receipt["path"].rsplit("/", 1)[1])
        receipts.append({**receipt, "path": f"/riders/{remaining[index]}"})
    return result, receipts
