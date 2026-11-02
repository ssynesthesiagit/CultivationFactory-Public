"""Exact-input general rider supplements shared by the converter and authority builder.

The ordinary parser, reviews and owner-text carry run first. A supplement applies
only to the exact text AND the complete mechanic that its converter inspected.
Later reviews therefore invalidate a supplement instead of being overwritten.
This is build-time data handling; old saved fight bundles are never recompiled.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "TianxiaFoundry.GeneralRiderPatterns.v1"
FIELDS = frozenset(("effects", "options", "modifier", "riders", "activation", "range", "area",
                    "cost", "use_limit", "duration", "target", "after", "weapon_delivery",
                    "min_cp_cost", "reaction_target"))


def digest(value: object) -> str:
    """Stable complete-input fingerprint, shared with generated conversion receipts."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def coverage(mechanic: dict) -> str:
    """Preserve the report's top-level structural metric; not a semantic proof."""
    typed = bool(mechanic.get("effects") or mechanic.get("options")
                 or (mechanic.get("modifier") or {}).get("effects")
                 or (mechanic.get("modifier") or {}).get("options"))
    return ("FULL" if not mechanic.get("riders") else "CORE_WITH_RIDERS") if typed else "RIDERS_ONLY"


def apply(data: dict, supplement: dict) -> dict[str, str]:
    """Apply valid rows in place, returning explicit admissions/rejections.

    Malformed authored data fails the build. Stale but well-formed rows remain
    unapplied, preserving the complete original mechanic and its visible riders.
    """
    if supplement.get("schema") != SCHEMA or not isinstance(supplement.get("mechanics"), dict):
        raise ValueError("Invalid general rider supplement schema")
    outcomes: dict[str, str] = {}
    for key, row in sorted(supplement["mechanics"].items()):
        if not isinstance(row, dict) or not isinstance(row.get("set"), dict) or not isinstance(row.get("remove", []), list):
            raise ValueError(f"Invalid general rider conversion: {key}")
        changed = set(row["set"]) | set(row.get("remove", []))
        if not changed <= FIELDS or set(row["set"]) & set(row.get("remove", [])):
            raise ValueError(f"Unsupported general rider override fields: {key}")
        mechanic = data["mechanics"].get(key)
        if mechanic is None:
            outcomes[key] = "unknown_mechanic"
            continue
        text_hash = (mechanic.get("source") or {}).get("text_sha256")
        if not text_hash or row.get("text_sha256") != text_hash:
            outcomes[key] = "stale_text"
            continue
        if row.get("input_sha256") != digest(mechanic):
            outcomes[key] = "changed_typing"
            continue
        candidate = copy.deepcopy(mechanic)
        candidate.update(copy.deepcopy(row["set"]))
        for field in row.get("remove", []):
            candidate.pop(field, None)
        candidate["coverage"] = coverage(candidate)
        if row.get("output_sha256") != digest(candidate):
            raise ValueError(f"General rider output fingerprint mismatch: {key}")
        data["mechanics"][key] = candidate
        outcomes[key] = "applied"
    return outcomes


def apply_file(data: dict, path: Path) -> dict[str, str]:
    """Optional final authority pass; an absent supplement changes no bytes."""
    if not path.is_file():
        return {}
    outcomes = apply(data, json.loads(path.read_text(encoding="utf-8")))
    for key, status in outcomes.items():
        if status != "applied":
            print(f"general rider: {key} skipped ({status}; rerun convert_rider_patterns.py)", file=sys.stderr)
    print(f"general riders: applied {sum(v == 'applied' for v in outcomes.values())} of {len(outcomes)} exact-input rows", file=sys.stderr)
    return outcomes
