"""Passive statistics granted by acquired Path and Subpath features.

The sealed core baseline gives every character an unarmored AC of 10 + DEX
"with no other applicable AC calculation".  A Body Refiner's CL1 Unarmored
Defense (10 + CON + PB) is such an alternate calculation, and several Subpath
features add +1 AC while that calculation is in use.  These are typed here,
each anchored to its printed heading, so the ledger applies them instead of
reporting the baseline number for every Path.  The rules the owner amendment
states are preserved: one base calculation applies (the character chooses, so
the highest legal one is used), alternates replace rather than stack, explicit
bonuses apply after the calculation is chosen, and conditional bonuses are
named as pending execution rather than added.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.core import FoundryError, sha256_json
from stage2.formulas import FormulaError, evaluate_formula

STATISTIC_FORMULAS_SCHEMA = "TianxiaFoundry.PathFeatureStatisticFormulas.v1"
STATISTIC_FORMULAS_FILENAME = "Tianxia_Path_Feature_Statistic_Formulas_R1.json"
BASE_AC_CALCULATION = "base_ac_calculation"
AC_BONUS = "ac_bonus"
CONDITIONAL_AC_BONUS = "conditional_ac_bonus"
_KINDS = frozenset({BASE_AC_CALCULATION, AC_BONUS, CONDITIONAL_AC_BONUS})


def statistic_formulas_path(root_dir: Path) -> Path:
    return Path(root_dir) / "authority" / STATISTIC_FORMULAS_FILENAME


def load_path_feature_statistic_formulas(root_dir: Path) -> dict[str, Any]:
    """Read and verify the sealed statistic-formula authority."""

    path = statistic_formulas_path(root_dir)
    if not path.is_file():
        raise FoundryError("PROJECTION_STATISTIC_FORMULAS_MISSING", "The sealed Path feature statistic formulas are missing.", details={"path": str(path)})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise FoundryError("PROJECTION_STATISTIC_FORMULAS_INVALID", "The Path feature statistic formulas are unreadable.", details={"path": str(path), "error": str(exc)}) from exc
    if value.get("schema_version") != STATISTIC_FORMULAS_SCHEMA:
        raise FoundryError("PROJECTION_STATISTIC_FORMULAS_INVALID", "The Path feature statistic formulas declare an unsupported schema.", details={"path": str(path)})
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    if value.get("seal_sha256") != sha256_json(unsigned):
        raise FoundryError("PROJECTION_STATISTIC_FORMULAS_INVALID", "The Path feature statistic formulas failed their canonical seal.", details={"path": str(path)})
    for rule in value.get("rules") or []:
        if rule.get("kind") not in _KINDS or not isinstance(rule.get("feature_id"), str) or not isinstance(rule.get("rule_id"), str):
            raise FoundryError("PROJECTION_STATISTIC_FORMULAS_INVALID", "A Path feature statistic rule has an unsupported shape.", details={"rule_id": rule.get("rule_id")})
    return value


def resolve_armor_class(
    formulas: Mapping[str, Any],
    acquired_feature_ids: Iterable[str],
    *,
    baseline_rule: Mapping[str, Any],
    baseline_value: int,
    baseline_trace: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Choose the AC calculation and apply always-on bonuses.

    Returns ``ac_base`` (the chosen calculation), ``ac_active`` (with
    always-on bonuses), an ``ac_generation`` record naming the calculation,
    every alternate considered, every bonus applied, and every conditional
    source the character holds, plus ``applied_rules`` for provenance.
    """

    acquired = {value for value in acquired_feature_ids if isinstance(value, str) and value}
    rules = [rule for rule in formulas.get("rules") or [] if rule.get("feature_id") in acquired]
    calculations: list[dict[str, Any]] = [{
        "calculation_id": baseline_rule["rule_id"],
        "display_name": "Unarmored baseline",
        "formula_id": baseline_rule["formula"]["formula_id"],
        "value": int(baseline_value),
        "trace": deepcopy(dict(baseline_trace)),
        "feature_id": None,
    }]
    applied: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for rule in rules:
        if rule.get("kind") != BASE_AC_CALCULATION:
            continue
        try:
            result = evaluate_formula(rule["formula"]["root"], dict(context))
        except (FormulaError, KeyError, TypeError) as exc:
            raise FoundryError("PROJECTION_STATISTIC_FORMULA_INVALID", "A Path feature AC calculation could not be evaluated.", details={"rule_id": rule.get("rule_id"), "error": str(exc)}) from exc
        calculations.append({
            "calculation_id": rule["rule_id"],
            "display_name": rule.get("display_name") or rule["feature_id"],
            "formula_id": rule["formula"]["formula_id"],
            "value": int(result.value),
            "trace": result.trace,
            "feature_id": rule["feature_id"],
        })
    # The character chooses one base calculation; it cannot combine them.
    # Choose the highest, keeping the baseline on ties.
    chosen = max(calculations, key=lambda row: (row["value"], row["feature_id"] is None))
    if chosen["feature_id"] is not None:
        rule = next(rule for rule in rules if rule["rule_id"] == chosen["calculation_id"])
        applied.append((rule, chosen["trace"]))
    bonuses: list[dict[str, Any]] = []
    conditional: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("kind") == AC_BONUS:
            requires = rule.get("requires_base_calculation_feature_id")
            if requires is None or requires == chosen["feature_id"]:
                bonuses.append({"rule_id": rule["rule_id"], "feature_id": rule["feature_id"], "display_name": rule.get("display_name"), "bonus": int(rule.get("bonus") or 0)})
                applied.append((rule, None))
            else:
                conditional.append({"rule_id": rule["rule_id"], "feature_id": rule["feature_id"], "display_name": rule.get("display_name"), "condition": f"Requires the {requires} calculation."})
        elif rule.get("kind") == CONDITIONAL_AC_BONUS:
            conditional.append({"rule_id": rule["rule_id"], "feature_id": rule["feature_id"], "display_name": rule.get("display_name"), "condition": rule.get("condition"), "bonus": rule.get("bonus")})
    ac_base = chosen["value"]
    ac_active = ac_base + sum(row["bonus"] for row in bonuses)
    generation = {
        "calculation": "path_feature" if chosen["feature_id"] else "unarmored_base",
        "calculation_id": chosen["calculation_id"],
        "calculation_feature_id": chosen["feature_id"],
        "formula_id": chosen["formula_id"],
        "trace": chosen["trace"],
        "alternatives_considered": [{key: row[key] for key in ("calculation_id", "display_name", "value")} for row in calculations],
        "always_on_bonuses": bonuses,
        "conditional_bonuses_pending_execution": [row["feature_id"] for row in conditional],
        "conditional_bonus_sources": conditional,
        "rule": "One base AC calculation applies and alternates replace rather than stack; explicit bonuses apply after the calculation is chosen; conditional bonuses are not added here.",
    }
    return {"ac_base": ac_base, "ac_active": ac_active, "ac_generation": generation, "applied_rules": applied}


__all__ = [
    "STATISTIC_FORMULAS_SCHEMA",
    "STATISTIC_FORMULAS_FILENAME",
    "load_path_feature_statistic_formulas",
    "resolve_armor_class",
    "statistic_formulas_path",
]
