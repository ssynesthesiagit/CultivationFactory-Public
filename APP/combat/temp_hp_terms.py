"""Pure Temporary HP term grouping shared by execution and AI support queries."""
from __future__ import annotations
import json
from typing import Any


def is_temp_hp_term(effect: dict[str, Any]) -> bool:
    """One term of a Temporary HP sum: an amount from a named formula (PB, CL, the key modifier) or from dice.
    Not a row that restates the whole printed amount ("text:...") and not a bare flat one (the alternatives
    of a realm table), which stay grants of their own."""
    formula = str(effect.get("formula") or "")
    return effect.get("type") == "temp_hp" and not effect.get("deferred") and (
        bool(effect.get("dice") or effect.get("dice_by_cl")) or (bool(formula) and formula != "none" and not formula.startswith("text:")))


def fold_temp_hp(effects: list[dict[str, Any]], anchor: dict[str, Any], folded: set[int], *, eligible) -> dict[str, Any]:
    """The typing splits "Temporary HP equal to your Proficiency Bonus + your Path key ability modifier" into a row
    per term, and the engine keeps only the largest grant, so Coagulate gave 4 where it printed 4 + 4 (hunt 3, bug 5).
    The anchor row carries every term of the same grant as ``parts`` and the other rows are skipped.  Rows that
    repeat one term (a model and a model_v2 row for the same "PB") count once."""
    if not is_temp_hp_term(anchor):
        return anchor
    terms: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for row in effects:
        if (isinstance(row, dict) and is_temp_hp_term(row) and row.get("applies_to") == anchor.get("applies_to")
                and row.get("modifier_once") == anchor.get("modifier_once") and eligible(row)):
            rows.append(row)
            terms.setdefault(json.dumps([row.get(key) for key in ("formula", "dice", "dice_by_cl", "flat")], sort_keys=True), row)
    if len(terms) < 2:
        return anchor
    folded.update(id(row) for row in rows)
    return {**anchor, "parts": list(terms.values())}
