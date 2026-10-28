"""Pure conversions from exact rider text to reviewed typed effects.

Used by the rider conversion CLI and synthetic conversion tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys

from factory_authoring.rider_pattern_overlay import SCHEMA, FIELDS, coverage, digest


def conversions(baseline: dict, texts: dict[str, str]) -> dict:
    """Plan source-checked rider conversions without mutating the baseline."""
    from factory_authoring.rider_patterns_flight_skills import convert as flight_skills
    from factory_authoring.rider_patterns_save_movement import convert as save_movement
    from factory_authoring.rider_patterns_limits import convert as limits

    rows = {}
    for key, original in sorted(baseline["mechanics"].items()):
        if original.get("coverage") == "FULL":
            continue
        text = texts.get(key) or texts.get(original.get("split_of")) or ""
        text_sha = (original.get("source") or {}).get("text_sha256")
        if not text or not text_sha:
            continue
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != text_sha:
            print(f"general rider: {key} skipped (printed text differs from the typed source)", file=sys.stderr)
            continue
        updated, receipts = copy.deepcopy(original), []
        rider_indices = list(range(len(original.get("riders") or [])))
        for convert in (flight_skills, save_movement, limits):
            prior_riders = updated.get("riders") or []
            updated, matched = convert(updated, text)
            removed = set()
            for receipt in matched:
                pointer = re.fullmatch(r"/riders/(\d+)", receipt.get("path", ""))
                index = int(pointer[1]) if pointer else -1
                if (index < 0 or index >= len(prior_riders) or index in removed
                        or receipt.get("rider") != prior_riders[index]):
                    raise ValueError(f"Converter returned an invalid rider receipt: {key}")
                # Each recipe sees the previous recipe's shortened rider list.
                # Receipts always point into the complete original mechanic.
                receipts.append({**receipt, "path": f"/riders/{rider_indices[index]}"})
                removed.add(index)
            if (updated.get("riders") or []) != [value for i, value in enumerate(prior_riders) if i not in removed]:
                raise ValueError(f"Converter changed riders without exact receipts: {key}")
            rider_indices = [value for i, value in enumerate(rider_indices) if i not in removed]
        if not receipts:
            continue
        updated["coverage"] = coverage(updated)
        changed = {field for field in set(original) | set(updated)
                   if field not in original or field not in updated or original[field] != updated[field]}
        if changed - FIELDS - {"coverage"}:
            raise ValueError(f"Converter changed identity/provenance: {key}")
        rows[key] = {
            "text_sha256": original["source"]["text_sha256"],
            "input_sha256": digest(original),
            "output_sha256": digest(updated),
            "set": {field: updated[field] for field in sorted(changed & FIELDS) if field in updated},
            "remove": sorted(field for field in changed & FIELDS if field not in updated),
            "matches": receipts,
        }
    return {"schema": SCHEMA, "baseline_sha256": digest(baseline), "mechanics": rows}


def encode(data: dict) -> str:
    """Encode a conversion supplement deterministically."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
