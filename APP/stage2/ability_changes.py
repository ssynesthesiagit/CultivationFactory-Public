"""Pure ASI allocation validation shared by Stage 2 and table growth.

The table reads the same published ability_change authority as Stage 2; this
module deliberately does not invent additional advancement opportunities.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from stage2.legacy_service import _block


@lru_cache(maxsize=1)
def published_records() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))["records"]


def ability_change_rule(path_ids: list[str]) -> dict[str, Any]:
    """Return the published allocation rule for the selected Path(s)."""
    records = published_records()
    rules = [row["stage2_authority"]["ability_change"] for record_id, row in records.items()
             if "ability_change" in row.get("stage2_authority", {})
             and (not path_ids or any(record_id.startswith(path_id + ".") for path_id in path_ids))]
    return dict(rules[0]) if rules else {}


def validate_ability_change(scores: dict[str, int], deltas: Any, cl: int,
                            rule: dict[str, Any], pointer: str = "") -> list[dict[str, Any]]:
    """Stage 2 blockers for a bounded ASI, without persistence or recalculation."""
    blockers = []
    if not scores:
        blockers.append(_block("ABILITY_SCORES_NOT_ESTABLISHED", pointer, "An ability change requires a causal starting-score event."))
    if cl not in rule.get("allowed_cls", []):
        blockers.append(_block("ABILITY_CHANGE_AT_ILLEGAL_CL", pointer, "The published advancement record does not authorize an ability change at this CL.", allowed_cls=rule.get("allowed_cls", []), cl=cl))
    if not isinstance(deltas, dict) or any(k not in scores or not isinstance(v, int) or isinstance(v, bool) for k, v in (deltas or {}).items()):
        blockers.append(_block("ARBITRARY_ABILITY_SCORE_DELTA", pointer, "Ability changes require a bounded published delta allocation."))
    else:
        positive = sum(max(0, v) for v in deltas.values())
        if positive != int(rule.get("budget", 2)) or any(v not in rule.get("allowed_deltas", [1, 2]) for v in deltas.values()):
            blockers.append(_block("ARBITRARY_ABILITY_SCORE_DELTA", pointer, "The supplied deltas do not match the published ASI allocation budget or allowed increments.", deltas=deltas, rule=rule))
        new_scores = {a: scores[a] + int(deltas.get(a, 0)) for a in scores}
        cap = int(rule.get("cap", 20))
        if any(v > cap for v in new_scores.values()):
            blockers.append(_block("ABILITY_SCORE_CAP_EXCEEDED", pointer, "A resulting ability score exceeds the published cap.", cap=cap, scores=new_scores))
    return blockers
