"""Foundation acquisition for table growth, using creation's verified authority.

No Foundation rules are implemented here: the pinned registry and initial
mechanics resolver supply stages, supported expressions, formulas and features.
Level records store only the player's choice; sheet/combat projection is rebuilt
from that authority. Characters without a table-acquired Foundation are inert.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from non_sphere_authority import foundation_mechanics as fm
from stage2.formulas import evaluate_formula
from . import table_advance as ta


@lru_cache(maxsize=512)
def initial_mechanics(foundation_id: str, paths: tuple[str, ...], stage: str) -> dict[str, Any]:
    """Immutable source result, cached by the complete choice (never character state)."""
    return fm.resolve_initial_foundation_mechanics(fm.verified_foundation_records()[foundation_id], list(paths), stage=stage)


def possessed(sheet: dict[str, Any]) -> bool:
    foundation = sheet.get("foundation") or {}
    return bool(foundation.get("record_id") or foundation.get("foundation_id"))


def available(sheet: dict[str, Any], cl: int) -> bool:
    return cl >= fm.INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"] and not possessed(sheet)


def status(record: dict[str, Any], paths: list[str], method_id: str, authority: Any) -> dict[str, Any]:
    """Use the builder's Path containment and the existing Method resolver."""
    from non_sphere_authority.service import COMPACT_TO_CANONICAL
    reasons = []
    supported = {COMPACT_TO_CANONICAL[p] for p in record["compatible_path_ids"]}
    unsupported = [p for p in paths if p not in supported]
    if unsupported:
        names = [p.rsplit(".", 1)[-1].replace("_", " ").title() for p in unsupported]
        reasons.append("This Foundation does not support your active Paths: " + ", ".join(names) + ".")
    if method_id:
        method = authority.methods.get(method_id)
        if method is None:
            reasons.append("Your Primary Method is not in the published registry. Resolve it before choosing a Foundation.")
        else:
            allowed = method.get("compatible_foundation_ids") or []
            accepts = record.get("compatible_method_ids") or []
            result = authority.resolve_compatibility(method_id, record["foundation_id"], paths)
            if ((allowed and record["foundation_id"] not in allowed) or (accepts and method_id not in accepts)
                    or result["state"] == "INCOMPATIBLE"):
                reasons.append("This Foundation is incompatible with your Primary Method, " + method["name"] + ".")
    return {"legal": not reasons, "reasons": reasons}


def menu(sheet: dict[str, Any], cl: int, paths: list[str], method_id: str, authority: Any) -> dict[str, Any] | None:
    if not available(sheet, cl):
        return None
    rows = []
    primary = sheet["ability_scores_and_statistics"].get("primary_resource") or {}
    selected_pool = next((p for p in primary.get("definitions") or [] if p.get("name") == primary.get("name")), primary)
    resource_id = primary.get("resource_id") or selected_pool.get("resource_id")
    for key, record in fm.verified_foundation_records().items():
        check = status(record, paths, method_id, authority)
        previews = {}
        if check["legal"]:
            for stage in record["stage"].split(" or "):
                mechanics = initial_mechanics(key, tuple(paths), stage)
                previews[stage] = {
                    "hp": [m["formula"]["root"] for m in mechanics["hp_maximum_modifiers"]],
                    "resource": [m["formula"]["root"] for m in mechanics["resource_modifiers"]
                                 if m["resource_id"] == resource_id]}
        rows.append({"id": key, "name": record["display_name"], "summary": record["summary"],
                     "stage_options": record["stage"].split(" or "), "preview_by_stage": previews, **check})
    return {"options": rows, "acquisition_cl": fm.INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"]}


def selection(sheet: dict[str, Any], cl: int, choices: dict[str, Any], paths: list[str],
              method_id: str, authority: Any) -> dict[str, str] | None:
    from .table_levelup import reject
    key, stage = choices.get("foundation_id"), choices.get("foundation_initial_stage")
    if not key:
        if stage:
            reject("Choose a Foundation before choosing its initial stage.")
        return None  # Not yet is an explicit deferral, not a grant.
    if cl < fm.INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"]:
        reject(f"A Foundation can be chosen at cultivation level {fm.INITIAL_FOUNDATION_MECHANICS_POLICY['acquisition_cl']} or later.")
    if possessed(sheet):
        reject("The character already has a Foundation.")
    record = fm.verified_foundation_records().get(key) if isinstance(key, str) else None
    if record is None:
        reject("Choose an Orthodox Foundation from the published list, or Not yet.")
    check = status(record, paths, method_id, authority)
    if not check["legal"]:
        reject("; ".join(check["reasons"]))
    options = fm.initial_foundation_options(record, paths)
    if stage is None and options["default_stage"] is None:
        reject("Choose one of this Foundation's published initial stages.")
    if stage is not None and stage not in options["stage_options"]:
        reject("Choose one of this Foundation's published initial stages.")
    initial = fm.resolve_initial_foundation_state(record, paths, stage=stage)
    return {"id": key, "stage": initial["stage"], "name": record["display_name"], "method_id": method_id}


def install(sheet: dict[str, Any], choice: dict[str, Any], cl: int, authority: Any) -> None:
    """Revalidate the saved choice at its acquisition level before projection."""
    checked = selection(sheet, cl, {"foundation_id": choice["id"], "foundation_initial_stage": choice["stage"]},
                        ta.known(sheet)["paths"], choice.get("method_id") or "", authority)
    record = fm.verified_foundation_records()[checked["id"]]
    mechanics = copy.deepcopy(initial_mechanics(checked["id"], tuple(ta.known(sheet)["paths"]), checked["stage"]))
    # The table overlay now has a Foundation, even when the sealed baseline explicitly had none.
    if isinstance(sheet.get("explicit_none_systems"), dict):
        sheet["explicit_none_systems"].pop("foundation", None)
    sheet["foundation"] = {
        **fm.installed_foundation_state(mechanics, checked["id"], f"table.level.{cl}.foundation"),
        "display_name": record["display_name"], "summary": record["summary"],
        "mechanics": mechanics, "mechanical_projection": True, "table_acquired": True, "acquisition_cl": cl,
    }


def project(sheet: dict[str, Any]) -> None:
    """Apply source formulas once, preserving deficits exactly as creation does.

    Resource formulas join the existing table calculator's authority components
    so future level/score changes use that same evaluator. HP is a flat
    contribution replaced as proficiency changes, never a per-level HP gain.
    """
    foundation = sheet.get("foundation") or {}
    if not foundation.get("table_acquired"):
        return
    record = fm.verified_foundation_records()[foundation["foundation_id"]]
    mechanics = copy.deepcopy(initial_mechanics(record["foundation_id"], tuple(ta.known(sheet)["paths"]), foundation["stage"]))
    foundation["mechanics"] = mechanics
    for field in ("active_expression_path_ids", "unsupported_active_path_ids", "dormant_expression_path_ids"):
        foundation[field] = mechanics["initial_state"][field]
    context = ta._formula_context(sheet, ta.current_scores(sheet))
    block = sheet["ability_scores_and_statistics"]
    hp = block["hit_points"]
    total = sum(evaluate_formula(m["formula"]["root"], context).value for m in mechanics["hp_maximum_modifiers"])
    delta = total - int(hp.get("table_foundation_delta") or 0)
    ta._bump(hp, "maximum", delta)
    ta._bump(hp, "build_state_current", delta)
    hp["table_foundation_delta"] = total
    primary = block.get("primary_resource") or {}
    pools = primary.get("definitions") or [primary]
    for pool in pools:
        modifiers = [m for m in mechanics["resource_modifiers"] if m["resource_id"] == pool.get("resource_id")]
        if not modifiers:
            continue
        components = pool.setdefault("authority_components", [])
        if not components:
            # Preserve the existing Path formula before adding a Foundation term.
            components.append({k: copy.deepcopy(pool[k]) for k in ("base_formula", "formula_trace", "formula_id") if k in pool})
        old = sum(int(c.get("value") or 0) for c in components if c.get("role") == "table_foundation")
        components[:] = [c for c in components if c.get("role") != "table_foundation"]
        added = []
        for modifier in modifiers:
            formula = modifier["formula"]
            added.append({"role": "table_foundation", "record_id": record["foundation_id"],
                          "base_formula": copy.deepcopy(formula),
                          "value": evaluate_formula(formula["root"], context).value})
        components.extend(added)
        change = sum(c["value"] for c in added) - old
        maximum = "max" if "max" in pool else "maximum"
        current = "current" if "current" in pool else "build_state_current"
        ta._bump(pool, maximum, change)
        ta._bump(pool, current, change)
    # Synchronize the displayed selected pool without re-evaluating any formula.
    ta._recompute_resources(block, context, context)
