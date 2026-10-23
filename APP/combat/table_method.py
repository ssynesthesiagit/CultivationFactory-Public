"""Primary Method lifecycle for Grow, not a second ability implementation.

Uses the verified Method registry/compiler and compatibility resolver shared with
creation. Changes are replayed between table levels; Known Methods never supply
math. The table overlay is the single commit/undo boundary (no authority DB write).
"""
from __future__ import annotations

import copy
from typing import Any

from app.core import FoundryError
from non_sphere_authority.method_mechanics import compile_method_mechanics
from non_sphere_authority.service import COMPACT_TO_CANONICAL
from stage2.formulas import evaluate_formula
from . import table_advance as ta

SOURCES = ("teacher", "scripture", "inheritance", "sect permission", "ruin", "item", "failure route", "gm")
OPPORTUNITIES = ("downtime training", "sect instruction", "scripture study", "Foundation repair",
                 "breakthrough preparation", "recovery", "campaign milestone")


def reject(message: str) -> None:
    raise FoundryError("TABLETOP_METHOD_NOT_LEGAL", message, status_code=409)


def primary_id(sheet: dict[str, Any], fallback: str = "") -> str:
    method = sheet.get("method") or {}
    if fallback and not method.get("table_acquired"):
        return fallback  # Existing creation-authority state, until Grow records its own transition.
    if method.get("state") in ("active", "acquired") and method.get("record_id"):
        return str(method["record_id"])
    identity, cultivation = sheet.get("identity") or {}, sheet.get("cultivation") or {}
    value = identity.get("primary_method_id") or cultivation.get("primary_method_id") or cultivation.get("primary_method")
    return str((value.get("method_id") if isinstance(value, dict) else value) or fallback or "")


def _source():
    from .table_levelup import source
    return source()


def status(sheet: dict[str, Any], method: dict[str, Any]) -> dict[str, Any]:
    """Only authored restrictions block; a lost future AP route is NOT incompatibility."""
    authority = _source()
    mid = method["method_id"]
    foundation = sheet.get("foundation") or {}
    fid = foundation.get("foundation_id") or foundation.get("record_id")
    paths = ta.known(sheet)["paths"]
    reasons = []
    constraints = (sheet.get("method_foundation_compatibility") or {}).get(mid) or {}
    allowed = set(method.get("compatible_foundation_ids") or []) | set(constraints.get("compatible_foundation_ids") or [])
    accepts = foundation.get("compatible_method_ids") or []
    if fid and ((allowed and fid not in allowed) or (accepts and mid not in accepts)):
        reasons.append("This Method does not support your Foundation, " + str(foundation.get("display_name") or "the current Foundation") + ".")
    if fid in authority.foundations:
        # The creation resolver treats a missing future AP route as incompatible.
        # On a switch, historical attainment is explicitly retained, not a new AP
        # request. Score only expressions the new Method actually routes to.
        grants = {COMPACT_TO_CANONICAL[g["path_id"]] for g in method["explicit_ap_grants"] if g["grants_attainment_points"]}
        result = authority.resolve_compatibility(mid, fid, [p for p in paths if p in grants])
        if result["state"] == "INCOMPATIBLE":
            reasons.append("This Method is incompatible with your Foundation, " +
                           str(foundation.get("display_name") or authority.foundations[fid]["display_name"]) + ".")
    incompatible = method.get("incompatibilities") or {}
    if isinstance(incompatible, dict):
        forbidden_paths = method.get("incompatible_path_ids") or incompatible.get("path_ids") or []
        forbidden_foundations = method.get("incompatible_foundation_ids") or incompatible.get("foundation_ids") or []
    else:
        forbidden_paths = method.get("incompatible_path_ids") or []
        forbidden_foundations = method.get("incompatible_foundation_ids") or []
    blocked = [p for p in paths if p in forbidden_paths or p in {COMPACT_TO_CANONICAL.get(x) for x in forbidden_paths}]
    if blocked:
        reasons.append("This Method conflicts with your active Paths: " +
                       ", ".join(p.rsplit(".", 1)[-1].replace("_", " ").title() for p in blocked) + ".")
    if fid and fid in forbidden_foundations:
        reasons.append("This Method explicitly excludes your Foundation.")
    return {"legal": not reasons, "reasons": list(dict.fromkeys(reasons))}


def menu(sheet: dict[str, Any], saved: dict[str, Any], fallback: str = "") -> dict[str, Any]:
    authority = _source()
    current = primary_id(sheet, fallback)
    rows = []
    for mid, method in authority.methods.items():
        readable = method["owner_readable"]
        rows.append({"id": mid, "name": method["name"], "current": mid == current,
                     "summary": readable["full_description"], "resource": readable["resource_summary"],
                     "breakthrough": readable["breakthrough_summary"], "foundation": readable["foundation_summary"],
                     "future_ap": readable["ap_route_summary"], **status(sheet, method)})
    return {"primary": {"id": current, "name": (authority.methods.get(current) or {}).get("name", "No Primary Method")},
            "known": copy.deepcopy(sheet.get("known_methods") or []),
            "free_replacement": current == "METHOD-001" and not saved["method_changes"],
            "options": rows, "sources": list(SOURCES), "opportunities": list(OPPORTUNITIES),
            "history": [{k: v for k, v in row.items() if k not in ("before", "after_key")}
                        for row in saved["method_changes"]]}


def prepare(sheet: dict[str, Any], saved: dict[str, Any], choices: dict[str, Any], fallback: str = "") -> dict[str, Any]:
    authority = _source()
    mid = choices.get("method_id")
    method = authority.methods.get(mid)
    if method is None:
        reject("Choose a Method from the published list.")
    old = primary_id(sheet, fallback)
    if mid == old:
        reject("That Method is already Primary.")
    check = status(sheet, method)
    gm = bool(choices.get("gm"))
    if not check["legal"] and not gm:
        reject("; ".join(check["reasons"]) + " A Game Master may approve this as a GM grant.")
    free = old == "METHOD-001" and not saved["method_changes"]
    if choices.get("opportunity") not in OPPORTUNITIES or not choices.get("completed"):
        reject("Confirm a completed cultivation opportunity: downtime or story training, not combat, a short rest, or a daily loadout.")
    source = choices.get("source") or ""
    note = str(choices.get("note") or "").strip()
    if not free and (source not in SOURCES or not note):
        reject("Name the teacher, scripture, inheritance, sect permission, ruin, item, failure route, or GM permission for this change.")
    if source == "gm" and not gm:
        reject("Ask the Game Master to confirm the GM override.")
    row = {"from_method_id": old, "method_id": mid, "name": method["name"],
           "cl": ta.known(sheet)["cl"], "source": source if source in SOURCES else "starting sect replacement",
           "note": note, "opportunity": choices["opportunity"], "completed": True,
           "free_replacement": free, "gm": gm, "reasons": check["reasons"], "at": ta.now()}
    out = copy.deepcopy(saved)
    row["before"] = {k: copy.deepcopy(v) for k, v in saved.items() if k not in ("method_changes", "notes")}
    out["method_changes"].append(row)
    row["after_key"] = ta.overlay_key({k: v for k, v in out.items() if k != "method_changes"})
    return out


def undo(saved: dict[str, Any]) -> dict[str, Any]:
    if not saved["method_changes"]:
        reject("There is no Primary Method change to undo.")
    row = saved["method_changes"][-1]
    if row["after_key"] != ta.overlay_key({k: v for k, v in saved.items() if k != "method_changes"}):
        reject("Undo later levels or remove later campaign gains first. Undo will not discard them.")
    # Notes are not part of the Primary Method change; keep every note as it is now.
    return {**copy.deepcopy(row["before"]), "notes": copy.deepcopy(saved["notes"]),
            "method_changes": copy.deepcopy(saved["method_changes"][:-1])}


def install(sheet: dict[str, Any], row: dict[str, Any]) -> None:
    """Replace Method formula components in every existing Path pool; never refill."""
    authority = _source()
    method = authority.methods[row["method_id"]]
    mechanics = compile_method_mechanics(method, authority.method_registry_commitment_sha256)
    old_method = sheet.get("method") or {}
    block = sheet["ability_scores_and_statistics"]
    primary = block.get("primary_resource") or {}
    context = ta._formula_context(sheet, ta.current_scores(sheet))
    for pool in primary.get("definitions") or [primary]:
        components = pool.get("authority_components") or []
        old_terms = [c for c in components if c.get("role") == "method_delta"]
        old = sum(int(c.get("value") or 0) for c in old_terms)
        # Legacy active projections may retain a base formula but no components.
        if not components and old_method.get("mechanical_projection"):
            old = sum(evaluate_formula(m["formula"]["root"], context).value
                      for m in (old_method.get("mechanics") or {}).get("resource_modifiers") or []
                      if m["resource_id"] == pool.get("resource_id"))
        if not components:
            components = [{k: copy.deepcopy(pool[k]) for k in ("base_formula", "formula_trace", "formula_id") if k in pool}]
        components = [c for c in components if c.get("role") != "method_delta"]
        added = [{"role": "method_delta", "record_id": row["method_id"], "base_formula": copy.deepcopy(m["formula"]),
                  "value": evaluate_formula(m["formula"]["root"], context).value}
                 for m in mechanics["resource_modifiers"] if m["resource_id"] == pool.get("resource_id")]
        pool["authority_components"] = components + added
        maximum = "max" if "max" in pool else "maximum"
        current = "current" if "current" in pool else "build_state_current"
        if type(pool.get(maximum)) is int:
            prior = pool[maximum]
            # Account for a prior negative modifier that saturated the maximum
            # at zero rather than turning that discarded negative value into a bonus.
            previous_terms = components + old_terms
            if previous_terms and all(type(c.get("value")) is int for c in previous_terms):
                raw = sum(c["value"] for c in previous_terms)
                if prior == 0 and raw < 0:
                    prior = raw
            pool[maximum] = max(0, prior - old + sum(c["value"] for c in added))
            if type(pool.get(current)) is int:
                pool[current] = min(pool[current], pool[maximum])
    ta._recompute_resources(block, context, context)
    known = {r["record_id"]: copy.deepcopy(r) for r in sheet.get("known_methods") or []}
    for mid in (row["from_method_id"], row["method_id"]):
        if mid:
            known[mid] = {"record_id": mid, "display_name": (authority.methods.get(mid) or {}).get("name", mid),
                          "state": "active" if mid == row["method_id"] else "inactive"}
    for mid, item in known.items():
        item["state"] = "active" if mid == row["method_id"] else "inactive"
    sheet["known_methods"] = list(known.values())
    sheet["method"] = {"record_id": row["method_id"], "display_name": method["name"], "state": "active", "status": "active",
                       "mechanical_projection": True, "mechanics": mechanics, "table_acquired": True,
                       "gm": row["gm"], "source": row["source"], "note": row["note"],
                       "resource_shape": method["source_text"]["resource_shape"],
                       "breakthrough_shape": method["source_text"]["breakthrough_shape"],
                       "foundation_shape": method["source_text"]["foundation_shape"],
                       "per_path_breakthrough_profiles": copy.deepcopy(method["per_path_breakthrough_profiles"])}
    from character_sheet.service import method_printed_entry
    sheet["method"]["printed_entry"] = method_printed_entry(sheet["method"])
    sheet.setdefault("identity", {})["primary_method_id"] = row["method_id"]
    cultivation = sheet.get("cultivation")
    if isinstance(cultivation, dict):
        cultivation["primary_method_id"] = row["method_id"]
        if "primary_method" in cultivation:
            cultivation["primary_method"] = row["method_id"]
    if isinstance(sheet.get("explicit_none_systems"), dict):
        sheet["explicit_none_systems"].pop("method", None)


def replay(sheet: dict[str, Any], levels: list[dict[str, Any]], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """General lifecycle seam: replay Method transitions at their recorded CL.

    Level grants retain their acquisition-time Primary Method for validation.
    A later switch cannot rewrite those grants or activate a dormant Path.
    """
    from .table_levelup import advance_sheet
    if not changes:
        return advance_sheet(sheet, levels)
    out = copy.deepcopy(sheet)
    pending = list(changes)
    def apply_here():
        while pending and pending[0]["cl"] == ta.known(out)["cl"]:
            install(out, pending.pop(0))
    apply_here()
    for level in levels:
        out = advance_sheet(out, [level])
        apply_here()
    if pending:
        reject("A recorded Method change does not match the character's cultivation history.")
    return out
