"""Pure ASI allocation checks shared by Stage 2 and table growth.

Both callers validate with the same published ability_change rule data; the
helpers invent no advancement opportunities. Stage 2 retains its original
reducer: even blocked allocations recalculate a well-formed candidate before
returning the unchanged prior state.
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


@lru_cache(maxsize=1)
def published_path_records() -> dict[str, Any]:
    """The native source-bound Path/feature records also consumed by Stage 2.

    Unlike old proof packs, current installs retain native ns1r formula IDs.
    Root-only authority loading is read-only and never opens a project store.
    """
    from non_sphere_authority.service import NonSphereAuthorityService

    source = NonSphereAuthorityService(root_dir=Path(__file__).resolve().parents[1])
    records = {}
    for path_id in source.path_profiles:
        record = source.project_locked_path_catalog_record(path_id)
        records[path_id] = record
        for feature in record["compatibility"]["factory"]["stage2_authority"].get("features") or []:
            if feature.get("feature_kind") == "advancement_choice":
                feature_id = feature["canonical_id"]
                records[feature_id] = source.project_locked_path_feature_catalog_record(path_id, feature_id)
    return records


def ability_change_rule(path_ids: list[str]) -> dict[str, Any]:
    """Return the same source-bound allocation authority used by Stage 2."""
    rules = []
    for record_id, record in published_path_records().items():
        rule = record["compatibility"]["factory"]["stage2_authority"].get("ability_change")
        if rule and (not path_ids or any(record_id.startswith(path_id + ".") for path_id in path_ids)):
            rules.append(rule)
    if not rules:
        return {}
    # The normal allocation budget/increments/cap are shared; collect every
    # printed opportunity if separate feature rows describe different CLs.
    result = dict(rules[0])
    result["allowed_cls"] = sorted({cl for rule in rules for cl in rule["allowed_cls"]})
    return result


def ability_change_scores(scores: dict[str, int], deltas: Any) -> dict[str, int] | None:
    """Candidate scores for Stage 2 and table ASI validation, or None for malformed
    deltas. Budget, level and cap blockers must not prevent Stage 2 from
    recalculating a well-formed candidate before rejecting the event.
    """
    if not isinstance(deltas, dict) or any(
        k not in scores or not isinstance(v, int) or isinstance(v, bool)
        for k, v in (deltas or {}).items()
    ):
        return None
    return {a: scores[a] + int(deltas.get(a, 0)) for a in scores}


def validate_ability_change(scores: dict[str, int], deltas: Any, cl: int,
                            rule: dict[str, Any], pointer: str = "") -> list[dict[str, Any]]:
    """Shared blockers for a bounded ASI, without persistence or recalculation."""
    blockers = []
    if not scores:
        blockers.append(_block("ABILITY_SCORES_NOT_ESTABLISHED", pointer, "An ability change requires a causal starting-score event."))
    if cl not in rule.get("allowed_cls", []):
        blockers.append(_block("ABILITY_CHANGE_AT_ILLEGAL_CL", pointer, "The published advancement record does not authorize an ability change at this CL.", allowed_cls=rule.get("allowed_cls", []), cl=cl))
    new_scores = ability_change_scores(scores, deltas)
    if new_scores is None:
        blockers.append(_block("ARBITRARY_ABILITY_SCORE_DELTA", pointer, "Ability changes require a bounded published delta allocation."))
    else:
        positive = sum(max(0, v) for v in deltas.values())
        if positive != int(rule.get("budget", 2)) or any(v not in rule.get("allowed_deltas", [1, 2]) for v in deltas.values()):
            blockers.append(_block("ARBITRARY_ABILITY_SCORE_DELTA", pointer, "The supplied deltas do not match the published ASI allocation budget or allowed increments.", deltas=deltas, rule=rule))
        cap = int(rule.get("cap", 20))
        if any(v > cap for v in new_scores.values()):
            blockers.append(_block("ABILITY_SCORE_CAP_EXCEEDED", pointer, "A resulting ability score exceeds the published cap.", cap=cap, scores=new_scores))
    return blockers
