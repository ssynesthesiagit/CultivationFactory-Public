"""Guided table advancement, using the creation Path/Stage 2 authority.

Only acquisition/projection belongs here. Features still execute through their
existing combat plug-ins. Levels share ButtonStore's growth document with
campaign gains; undo is last-in-first-out and refuses to discard later gains.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core import FoundryError
from character_creation.path_attainment import native_path_progressions
from non_sphere_authority.service import NonSphereAuthorityService
from stage2.ability_changes import published_path_records, published_records
from stage2.formulas import evaluate_formula
from stage2.legacy_service import _pb
from . import table_advance as ta

ROOT = Path(__file__).resolve().parents[1]


def reject(message: str) -> None:
    raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", message, status_code=409)


@lru_cache(maxsize=1)
def source() -> NonSphereAuthorityService:
    return NonSphereAuthorityService(root_dir=ROOT)


def authority(sheet: dict[str, Any], cl: int) -> dict[str, Any]:
    paths = ta.known(sheet)["paths"]
    records = [published_path_records()[key] for key in paths if key in published_path_records()]
    if not paths or len(records) != len(paths) or not 2 <= cl <= 20:
        reject("Level up needs a published Path and a next cultivation level from 2 through 20.")
    entries = native_path_progressions(records, cl)
    milestones = [row for record in records for row in
                  record["compatibility"]["factory"]["stage2_authority"]["required_milestones"]
                  if row["cl"] == cl]
    # The representative Stage 2 record publishes the free talent capacity.
    # Native records may omit it; the published Stage 2 pack supplies it.
    capacities = {row["stage2_authority"]["level_talent_capacity"]
                  for row in published_records().values()
                  if "level_talent_capacity" in row.get("stage2_authority", {})}
    if len(capacities) != 1:
        reject("The published number of level talents is unavailable.")
    return {"entries": entries, "milestones": milestones, "talent_count": capacities.pop(),
            "path_records": records}


def _subpaths(sheet: dict[str, Any]) -> dict[str, str]:
    block = sheet.get("path_and_subpath") or {}
    ids = list(block.get("subpath_record_ids") or [])
    ids += [block[key] for key in ("subpath_record_id", "tradition_record_id") if block.get(key)]
    return {source().subpaths[key]["owning_path_id"]: key for key in ids if key in source().subpaths}


def _feature_rows(sheet: dict[str, Any], cl: int, selected: dict[str, str]) -> list[dict[str, Any]]:
    plan = authority(sheet, cl)
    rows = []
    for entry in plan["entries"]:
        path_auth = published_path_records()[entry["path_id"]]["compatibility"]["factory"]["stage2_authority"]
        by_id = {row["canonical_id"]: row for row in path_auth["features"]}
        rows += [by_id[key] for key in entry["automatic_feature_record_ids"]]
    for key in selected.values():
        rows += [row for row in source().subpaths[key]["feature_progression"] if row["granted_at_cl"] == cl]
    return rows


def advance_sheet(sheet: dict[str, Any], levels: list[dict[str, Any]]) -> dict[str, Any]:
    """Reproject level-derived values from the sealed baseline; no saved totals.

    Formula components preserve fixed equipment/Method/Foundation additions and
    resource deficits. HP uses the same fixed later-level formula as Stage 2.
    """
    if not levels:
        return sheet
    out = copy.deepcopy(sheet)
    scores = ta.current_scores(out)
    for level in levels:
        old = ta._formula_context(out, scores)
        cl = level.get("cl")
        if type(cl) is not int or cl != old["cl"] + 1:
            reject("Recorded levels must follow one another without gaps.")
        plan = authority(out, cl)
        selected = _subpaths(out)
        selected.update(level.get("subpaths") or {})
        if any(key not in source().subpaths or source().subpaths[key]["owning_path_id"] != pid
               for pid, key in selected.items()):
            reject("A recorded Subpath does not belong to this Path.")
        identity = out.setdefault("identity", {})
        identity.update(cultivation_level=cl, proficiency_bonus=_pb(cl), realm=ta.realm_of(cl))
        for row in identity.get("paths") or []:
            if row.get("path_id") in ta.known(out)["paths"]:
                row["effective_cl"] = cl
                if "path_cl" in row:
                    row["path_cl"] = cl
                if "cultivation_level" in row:
                    row["cultivation_level"] = cl
        if isinstance(identity.get("path_levels"), dict):
            for pid in ta.known(out)["paths"]:
                identity["path_levels"][pid] = cl
        context = ta._formula_context(out, scores)
        block = out.setdefault("ability_scores_and_statistics", {})
        path_auths = [row["compatibility"]["factory"]["stage2_authority"] for row in plan["path_records"]]
        hp_auth = max(path_auths, key=lambda a: evaluate_formula(a["hp_level1_formula"]["root"], context).value)
        hp_result = evaluate_formula(hp_auth["hp_later_formula"]["root"], context)
        gain = max(1, hp_result.value)
        hp = block.setdefault("hit_points", {})
        hp["maximum"] = int(hp.get("maximum") or 0) + gain
        if isinstance(hp.get("build_state_current"), int):
            hp["build_state_current"] += gain
        hp.setdefault("progression", {}).setdefault("levels", []).append(
            {"cl": cl, "gain": gain, "maximum": hp["maximum"], "formula_trace": hp_result.trace})
        ta._recompute_resources(block, old, context)
        delta_pb = context["pb"] - old["pb"]
        if delta_pb:
            for field in ("technique_attack_bonus", "technique_save_dc"):
                ta._bump(block, field, delta_pb)
            for skill in block.get("skills") or []:
                if skill.get("proficient") or skill.get("proficiency"):
                    ta._bump(skill, "bonus", delta_pb * (2 if skill.get("expertise") else 1))
            declared = block.get("saving_throw_proficiencies") or []
            saves = block.get("saving_throws")
            if isinstance(saves, dict):
                for ability in declared:
                    if ability in saves:
                        saves[ability] += delta_pb
            elif isinstance(saves, list):
                for row in saves:
                    if row.get("proficient") or row.get("ability") in declared:
                        ta._bump(row, "bonus", delta_pb)
        paths = out.setdefault("path_and_subpath", {})
        paths["subpath_record_ids"] = list(selected.values())
        if len(selected) == 1:
            paths["subpath_record_id"] = next(iter(selected.values()))
        rows = _feature_rows(out, cl, selected)
        feature_ids = paths.setdefault("path_feature_record_ids", [])
        occurrences = paths.setdefault("earned_feature_occurrences", [])
        sections = out.setdefault("selected_record_sections", {}).setdefault("path_features", [])
        for row in rows:
            key = row["canonical_id"]
            if key not in feature_ids:
                feature_ids.append(key)
            occurrences.append({"feature_id": key, "effective_cl": cl, "acquisition_source": "level"})
            sections.append({"record_id": key, "display_name": row["display_name"], "acquisition_cl": cl,
                             "full_description": row.get("effective_rules_text") or row.get("source_rules_text")
                             or (row.get("source") or {}).get("excerpt") or ""})
        # Keep the native Path level vector and the creator's representative
        # path_progression_by_cl in the same shape as creation.
        paths.setdefault("path_progression_by_cl", {})[str(cl)] = plan["entries"][0]["path_id"]
        for key in ("path_levels", "path_attainment"):
            if isinstance(paths.get(key), dict):
                for pid in ta.known(out)["paths"]:
                    paths[key][pid] = cl
        armor = block.get("armor_class")
        if isinstance(armor, dict):
            # Existing AC alternatives and newly acquired passive AC features
            # are resolved by the same typed projector used during creation.
            import json
            from projector.path_feature_statistics import resolve_armor_class
            pack = json.loads((ROOT / "authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json").read_text())
            baseline = next(row for row in pack["rules"] if row["rule_id"] == ta._UNARMORED_AC_RULE_ID)
            result = evaluate_formula(baseline["formula"]["root"], context)
            resolved = resolve_armor_class(ta._path_statistic_formulas(), feature_ids,
                baseline_rule=baseline, baseline_value=result.value, baseline_trace=result.trace, context=context)
            armor.update(base_value=resolved["ac_base"], value=resolved["ac_active"],
                         formula_trace=resolved["ac_generation"]["trace"], generation=resolved["ac_generation"])
    return out


def menu(sheet: dict[str, Any], talents: list[dict[str, Any]], saved: dict[str, Any]) -> dict[str, Any]:
    history = [{key: value for key, value in row.items() if key not in ("before", "after_key")} for row in saved["levels"]]
    cl = ta.known(sheet)["cl"] + 1
    if cl > 20:
        return {"available": False, "reason": "Cultivation level 20 is the highest published level.", "history": history}
    try:
        plan = authority(sheet, cl)
    except FoundryError as exc:
        return {"available": False, "reason": exc.message, "history": history}
    preview = advance_sheet(sheet, [{"cl": cl}])
    have = ta.known(preview)
    choices = [{"id": row["canonical_talent_id"], "name": row["display_name"],
                "sphere_id": row.get("owning_canonical_sphere_id"),
                **ta.talent_status(row, have)} for row in talents
               if row.get("canonical_talent_id") not in have["talents"]
               and row.get("owning_canonical_sphere_id") in have["spheres"]
               and not row.get("automatic_grant") and not row.get("background_only")]
    subpaths = []
    for milestone in plan["milestones"]:
        if milestone["feature_kind"] == "subpath_selection":
            pid = milestone["path_id"]
            subpaths.append({"path_id": pid, "name": published_path_records()[pid]["display_name"],
                "options": [{"id": row["canonical_id"], "name": row["display_name"],
                             "minimum_cl": row["minimum_cl"], "legal": cl >= row["minimum_cl"],
                             "requires_confirmation": bool(row["access"].get("access_source_record_required")
                                                           or row["prerequisites"].get("explicit")),
                             "access": row["access"]["canonical_category"],
                             "features": [f["display_name"] for f in row["feature_progression"] if f["granted_at_cl"] == cl]}
                            for row in source().subpath_catalog(pid)["records"]]})
    advancement = [row for row in plan["milestones"] if row["feature_kind"] == "advancement_choice"]
    # GROW2 is not on this lane's main baseline. Keep this WIP fail-closed:
    # integrating campaign Insight acquisition and its level-selection +1 is
    # required before either milestone branch may be offered. Importing the
    # future module alone must not accidentally enable an incomplete wizard.
    blocked = ("Level selection of Insights needs the campaign Insight growth update and its level-selection integration. "
               "No level will be recorded until both choices are available.") if advancement else ""
    return {"available": not blocked, "reason": blocked, "cl": cl, "history": history,
            "features": [{"id": r["canonical_id"], "name": r["display_name"],
                          "text": r.get("effective_rules_text") or r.get("source_rules_text") or ""}
                         for r in _feature_rows(sheet, cl, _subpaths(sheet))],
            "talent_count": plan["talent_count"], "talents": choices, "subpaths": subpaths,
            "advancement_choice": bool(advancement), "ability_rule": ta.level_increase_rule(preview),
            "insights": [],
            "statistics": {"hp": preview["ability_scores_and_statistics"].get("hit_points"),
                           "resource": preview["ability_scores_and_statistics"].get("primary_resource"),
                           "pb": have["pb"]}}


def prepare(sheet: dict[str, Any], saved: dict[str, Any], choices: dict[str, Any],
            talents: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one atomic acquisition. Caller must project before saving."""
    options = menu(sheet, talents, saved)
    if not options["available"]:
        reject(options["reason"])
    if choices.get("cl") != options["cl"]:
        reject("The character changed. Reload Level up and review the next level.")
    cl = options["cl"]
    selected = choices.get("subpaths") or {}
    if set(selected) != {row["path_id"] for row in options["subpaths"]}:
        reject("Choose exactly one Subpath for each Path offered at this level.")
    for group in options["subpaths"]:
        row = next((r for r in group["options"] if r["id"] == selected[group["path_id"]]), None)
        if row is None or not row["legal"]:
            reject("Choose a Subpath belonging to the offered Path and available at this cultivation level.")
        if row["requires_confirmation"] and not choices.get("access_confirmed"):
            reject("Ask the Game Master to confirm access to the selected Subpath.")
    picked = choices.get("talent_ids") or []
    if len(picked) != options["talent_count"] or len(set(picked)) != len(picked):
        reject(f"Choose exactly {options['talent_count']} new level talent.")
    by_id = {r["id"]: r for r in options["talents"]}
    if any(key not in by_id or not by_id[key]["legal"] for key in picked):
        reject("Choose a legal, unlearned talent from a Sphere you know.")
    out = copy.deepcopy(saved)
    before = {key: copy.deepcopy(value) for key, value in saved.items() if key != "levels"}
    row = {"cl": cl, "subpaths": dict(selected), "access_confirmed": bool(choices.get("access_confirmed")),
           "at": ta.now(), "source": "level",
           "path_progression_by_cl": {str(cl): authority(sheet, cl)["entries"][0]["path_id"]}}
    out["talents"] += [{"id": key, "cl": cl, "source": "level", "gm": False, "at": row["at"]} for key in picked]
    if options["advancement_choice"]:
        # Both branches remain visible. GROW2's shared checker gates Insights.
        if choices.get("advancement") == "ability":
            entry = {"reason": "level_increase", "cl": cl, "changes": choices.get("changes") or {}, "at": row["at"]}
            preview = advance_sheet(sheet, [{"cl": cl, "subpaths": selected}])
            status = ta.ability_status(entry, preview)
            if not status["legal"]:
                reject("; ".join(status["reasons"]))
            out["abilities"].append(ta._ability_entry(entry))
        else:
            reject("Choose the ability-score branch; level Insight integration is not yet available.")
    elif choices.get("advancement") or choices.get("changes") or choices.get("insight_id"):
        reject("This level does not offer an ability-score or Insight selection.")
    row["features"] = [{"id": r["canonical_id"], "name": r["display_name"]}
                       for r in _feature_rows(sheet, cl, {**_subpaths(sheet), **selected})]
    row["talents"] = [{"id": key, "name": by_id[key]["name"]} for key in picked]
    row["before"] = before
    out["levels"].append(row)
    row["after_key"] = ta.overlay_key({key: value for key, value in out.items() if key != "levels"})
    return out


def undo(saved: dict[str, Any]) -> dict[str, Any]:
    if not saved["levels"]:
        reject("There is no table level to undo.")
    last = saved["levels"][-1]
    current = ta.overlay_key({key: value for key, value in saved.items() if key != "levels"})
    if current != last["after_key"]:
        reject("Remove the gains or score changes recorded after this level first. Undo will not discard campaign gains.")
    return {**copy.deepcopy(last["before"]), "levels": copy.deepcopy(saved["levels"][:-1])}
