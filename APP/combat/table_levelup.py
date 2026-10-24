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
from character_creation.feature_choices import menu as feature_menu, resolve as resolve_feature_choices
from . import table_advance as ta
from . import table_foundation

ROOT = Path(__file__).resolve().parents[1]


def reject(message: str) -> None:
    raise FoundryError("TABLETOP_LEVEL_NOT_LEGAL", message, status_code=409)


@lru_cache(maxsize=1)
def source() -> NonSphereAuthorityService:
    return NonSphereAuthorityService(root_dir=ROOT)


ACCESS_KINDS = ("primary_method", "phb", "gm")


def _stage2(record: dict[str, Any]) -> dict[str, Any]:
    return record["compatibility"]["factory"]["stage2_authority"]


def _add_record(add: dict[str, Any]) -> dict[str, Any]:
    # method_id is the Primary Method validated at commit; replay checks it instead of re-reading authority state.
    return {"path_id": add["path_id"], "access": add["access"], "source_id": add["source_id"],
            "confirmed": bool(add.get("confirmed")), **({"method_id": add["method_id"]} if add.get("method_id") else {})}


def _level_add(level: dict[str, Any]) -> dict[str, Any] | None:
    return level.get("add_path") or None


def _choice_add(choices: dict[str, Any]) -> dict[str, Any] | None:
    if not choices.get("add_path_id"):
        return None
    return {"path_id": choices["add_path_id"], "access": choices.get("add_access") or "",
            "source_id": choices.get("add_source_id") or "", "confirmed": bool(choices.get("add_confirmed"))}


def _is_path_key(key: str) -> bool:
    return key in published_path_records() and key.count(".") == 2


def _recorded_primary_method(sheet: dict[str, Any], fallback: str = "") -> str:
    from .table_method import primary_id
    return primary_id(sheet, fallback)


def _primary_method_view(method_id: str) -> dict[str, str] | None:
    """The recorded Primary Method as the level view shows it: display name plus the id the client sends back."""
    if not method_id:
        return None
    method = source().methods.get(method_id) or {}
    return {"id": method_id, "name": str(method.get("name") or method_id)}


def _add_problem(sheet: dict[str, Any], add: dict[str, Any], cl: int, method_id: str = "") -> str:
    """Why this Path cannot be added at this level, or an empty string when it can."""
    pid = add["path_id"]
    if not _is_path_key(pid):
        return "That Path is not a published Path."
    if pid in ta.known(sheet)["paths"]:
        return "The character already possesses this Path."
    access = add.get("access")
    if access not in ACCESS_KINDS:
        return "Record the access source for the new Path: Primary Method grant, PHB source, or GM override."
    if not str(add.get("source_id") or "").strip():
        return "Name the access source for the new Path."
    recorded = str(add.get("method_id") or _recorded_primary_method(sheet, method_id))
    if access == "primary_method" and (not recorded or add["source_id"] != recorded):
        return "The Primary Method grant does not match this character's recorded Primary Method."
    if access == "primary_method" and (sheet.get("method") or {}).get("table_acquired") and not add.get("method_id"):
        from non_sphere_authority.service import COMPACT_TO_CANONICAL
        grants = source().methods[recorded]["explicit_ap_grants"]
        if pid not in {COMPACT_TO_CANONICAL[g["path_id"]] for g in grants if g["grants_attainment_points"]}:
            return "Your Primary Method does not grant future advancement to this Path."
    if access == "gm" and not add.get("confirmed"):
        return "Ask the Game Master to confirm the GM override for the new Path."
    if not 2 <= cl <= 20:
        return "A Path can only be added at cultivation level 2 through 20."
    return ""


def _grant_path(out: dict[str, Any], pid: str, cl: int) -> None:
    current = list(ta.known(out)["paths"])
    if pid in current:
        return
    identity = out.setdefault("identity", {})
    identity["path_ids"] = current + [pid]
    if isinstance(identity.get("paths"), list):
        identity["paths"].append({"path_id": pid, "effective_cl": cl})
    block = out.get("path_and_subpath")
    if isinstance(block, dict) and isinstance(block.get("path_record_ids"), list):
        block["path_record_ids"] = current + [pid]


def _catch_up_entry(record: dict[str, Any], cl: int) -> dict[str, Any]:
    """A Path added at cl takes its core features from CL1 through cl."""
    ids: list[str] = []
    for level in range(1, cl + 1):
        for key in native_path_progressions([record], level)[0]["automatic_feature_record_ids"]:
            if key not in ids:
                ids.append(key)
    return {**native_path_progressions([record], cl)[0], "automatic_feature_record_ids": ids}


def authority(sheet: dict[str, Any], cl: int, add: str = "") -> dict[str, Any]:
    paths = list(dict.fromkeys(ta.known(sheet)["paths"] + ([add] if add else [])))
    records = [published_path_records()[key] for key in paths if key in published_path_records()]
    if not paths or len(records) != len(paths) or not 2 <= cl <= 20:
        reject("Level up needs a published Path and a next cultivation level from 2 through 20.")
    entries = [_catch_up_entry(record, cl) if pid == add else native_path_progressions([record], cl)[0]
               for pid, record in zip(paths, records)]
    entries.sort(key=lambda entry: entry["path_id"])
    milestones: list[dict[str, Any]] = []
    seen: set = set()
    for pid, record in zip(paths, records):
        for row in _stage2(record)["required_milestones"]:
            if row["cl"] == cl or (pid == add and row["feature_kind"] == "subpath_selection" and row["cl"] <= cl):
                # One ASI/Insight per character level, however many Paths share it.
                key = ("advancement", cl) if row["feature_kind"] == "advancement_choice" else (pid, row["feature_kind"], row["cl"])
                if key not in seen:
                    seen.add(key)
                    milestones.append(row)
    # The representative Stage 2 record publishes the free talent capacity.
    # Native records may omit it; the published Stage 2 pack supplies it.
    capacities = {row["stage2_authority"]["level_talent_capacity"]
                  for row in published_records().values()
                  if "level_talent_capacity" in row.get("stage2_authority", {})}
    if len(capacities) != 1:
        reject("The published number of level talents is unavailable.")
    return {"entries": entries, "milestones": milestones, "talent_count": capacities.pop(),
            "path_records": records}


def _published_known(sheet: dict[str, Any]) -> dict[str, Any]:
    """What the sheet already has, including owned Subpaths and Insights, so an existing record counts as a prerequisite on load."""
    from . import table_growth
    have = ta.known(sheet)
    have["subpaths"] = set(_subpaths(sheet).values())
    have["insights"] = set(table_growth.insight_ids(sheet))
    return have


KNOWN_KEYS = ("talents", "spheres", "paths", "subpaths", "insights")


def _subpaths(sheet: dict[str, Any]) -> dict[str, str]:
    block = sheet.get("path_and_subpath") or {}
    ids = list(block.get("subpath_record_ids") or [])
    ids += [block[key] for key in ("subpath_record_id", "tradition_record_id") if block.get(key)]
    return {source().subpaths[key]["owning_path_id"]: key for key in ids if key in source().subpaths}


def _dedupe_features(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    kept, dropped, seen = [], [], set()
    for row in rows:
        key = row.get("shared_rule_id") or row["canonical_id"]
        if key in seen:
            # The first-listed copy is kept; both Paths describe the same rule.
            dropped.append(f"{row['display_name']} is granted once; the duplicate from another Path is not added again.")
            continue
        seen.add(key)
        kept.append(row)
    return kept, dropped


def _held_shared_keys(sheet: dict[str, Any], add: str) -> set[str]:
    """Shared rule keys already granted by the Paths the character holds, other than the Path being added."""
    granted = set((sheet.get("path_and_subpath") or {}).get("path_feature_record_ids") or [])
    keys: set[str] = set()
    for pid in ta.known(sheet)["paths"]:
        if pid == add or pid not in published_path_records():
            continue
        for row in _stage2(published_path_records()[pid])["features"]:
            if row["canonical_id"] in granted:
                keys.add(row.get("shared_rule_id") or row["canonical_id"])
    return keys


def _feature_rows(sheet: dict[str, Any], cl: int, selected: dict[str, str], add: str = "",
                  notes: list[str] | None = None) -> list[dict[str, Any]]:
    plan = authority(sheet, cl, add)
    held = _held_shared_keys(sheet, add)
    rows = []
    for entry in plan["entries"]:
        by_id = {row["canonical_id"]: row for row in _stage2(published_path_records()[entry["path_id"]])["features"]}
        fresh = [by_id[key] for key in entry["automatic_feature_record_ids"]]
        if entry["path_id"] == add:
            # A Path added later catches up on core features; one shared rule another Path already granted is not granted twice.
            for row in fresh:
                key = row.get("shared_rule_id") or row["canonical_id"]
                if key in held and notes is not None:
                    notes.append(f"{row['display_name']} is granted once; the copy from the added Path is not added again.")
            fresh = [row for row in fresh if (row.get("shared_rule_id") or row["canonical_id"]) not in held]
        rows += fresh
    for key in selected.values():
        subpath = source().subpaths[key]
        if subpath["owning_path_id"] == add:
            rows += [row for row in subpath["feature_progression"] if row["granted_at_cl"] <= cl]
        else:
            rows += [row for row in subpath["feature_progression"] if row["granted_at_cl"] == cl]
    kept, dropped = _dedupe_features(rows)
    if notes is not None:
        notes.extend(dropped)
    return kept


def advance_sheet(sheet: dict[str, Any], levels: list[dict[str, Any]], *, preview: bool = False, primary_method_id: str = "") -> dict[str, Any]:
    """Reproject level-derived values from the sealed baseline; no saved totals.

    Formula components preserve fixed equipment/Method/Foundation additions and
    resource deficits. HP uses the same fixed later-level formula as Stage 2.
    """
    if not levels:
        return sheet
    out = copy.deepcopy(sheet)
    scores = ta.current_scores(out)
    for level in levels:
        residual_ac = ta.unrelated_ac_bonus(out)
        old = ta._formula_context(out, scores)
        cl = level.get("cl")
        if type(cl) is not int or cl != old["cl"] + 1:
            reject("Recorded levels must follow one another without gaps.")
        add = _level_add(level)
        if add:
            # Access is required to commit; a preview may still show the Path's options.
            problem = "" if preview else _add_problem(out, add, cl, primary_method_id)
            if problem:
                reject(problem)
            _grant_path(out, add["path_id"], cl)
        pid = add["path_id"] if add else ""
        plan = authority(out, cl, pid)
        selected = _subpaths(out)
        selected.update(level.get("subpaths") or {})
        if any(key not in source().subpaths or source().subpaths[key]["owning_path_id"] not in ta.known(out)["paths"]
               for key in selected.values()):
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
        # Every possessed Path carries the same level; the sheet reads this vector for attainment.
        identity.setdefault("path_levels", {})
        if isinstance(identity["path_levels"], dict):
            for owned in ta.known(out)["paths"]:
                identity["path_levels"][owned] = cl
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
        notes: list[str] = []
        rows = _feature_rows(out, cl, selected, pid, notes)
        # Replay of a stored level: a level written before the choice existed has no pick, so it is not required here.
        # prepare() still requires every pick for a new level before it is saved.
        build = {} if preview else resolve_feature_choices(rows, level.get("feature_choices") or {}, required=False)
        paths.setdefault("duplicate_feature_notes", []).extend(notes)
        paths.setdefault("feature_build_choices", {}).update(build)
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
        paths.setdefault("path_progression_entries_by_cl", {})[str(cl)] = [e["path_id"] for e in plan["entries"]]
        for key in ("path_levels", "path_attainment"):
            if isinstance(paths.get(key), dict):
                for owned in ta.known(out)["paths"]:
                    paths[key][owned] = cl
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
            armor.update(base_value=resolved["ac_base"], value=resolved["ac_active"] + residual_ac,
                         formula_trace=resolved["ac_generation"]["trace"], generation=resolved["ac_generation"])
        if level.get("foundation"):
            table_foundation.install(out, level["foundation"], cl, source())
        table_foundation.project(out)
    return out


def _level_view(cl: int, selected: dict[str, str], feature_choices: dict[str, str], add: dict[str, Any] | None) -> dict[str, Any]:
    return {"cl": cl, "subpaths": selected, "feature_choices": feature_choices,
            **({"add_path": _add_record(add)} if add and add.get("path_id") else {})}


def pending_feature_choices(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Owned features that take a build pick but have none recorded (gained before the pick existed). The options are
    the level-up ones; the pick is recorded through the table's feature-pick action (TabletopService.set_feature_picks)."""
    from character_creation.feature_choices import contracts
    paths = sheet.get("path_and_subpath") or {}
    built = paths.get("feature_build_choices") or {}
    owned = [{"canonical_id": key, "display_name": key.rsplit(".", 1)[-1].replace("_", " ").title()}
             for key in paths.get("path_feature_record_ids") or [] if key in contracts() and key not in built]
    return feature_menu(owned)


def menu(sheet: dict[str, Any], talents: list[dict[str, Any]], saved: dict[str, Any],
         insights: list[dict[str, Any]] = (), add: dict[str, Any] | None = None, *, primary_method_id: str = "") -> dict[str, Any]:
    history = [{key: value for key, value in row.items() if key not in ("before", "after_key")} for row in saved["levels"]]
    cl = ta.known(sheet)["cl"] + 1
    if cl > 20:
        return {"available": False, "reason": "Cultivation level 20 is the highest published level.", "history": history}
    add_error = _add_problem(sheet, add, cl, primary_method_id) if add and add.get("path_id") else ""
    pid = add["path_id"] if add and _is_path_key(add.get("path_id") or "") and add["path_id"] not in ta.known(sheet)["paths"] else ""
    try:
        plan = authority(sheet, cl, pid)
    except FoundryError as exc:
        return {"available": False, "reason": exc.message, "history": history}
    preview = ta.memorized(advance_sheet(sheet, [_level_view(cl, {}, {}, add if pid else None)], preview=True))
    have = _published_known(preview)
    choices = [{"id": row["canonical_talent_id"], "name": row["display_name"],
                "sphere_id": row.get("owning_canonical_sphere_id"),
                "sphere": row.get("owning_canonical_sphere_name") or str(row.get("owning_canonical_sphere_id") or "").split(".")[-1].title(),
                "summary": row.get("short_description") or row.get("full_description") or "",
                "constraints": row.get("typed_constraints") or [],
                "clauses": row.get("prerequisite_clauses") or [],
                "unresolved": str(row.get("prerequisite_evaluation_status") or "").startswith("UNRESOLVED"),
                **ta.talent_status(row, have)} for row in talents
               if row.get("canonical_talent_id") not in have["talents"]
               and row.get("owning_canonical_sphere_id") in have["spheres"]
               and not row.get("automatic_grant") and not row.get("background_only")]
    subpaths = []
    for milestone in plan["milestones"]:
        if milestone["feature_kind"] == "subpath_selection":
            owner = milestone["path_id"]
            # An added Path's Subpath catches up through this level; any other Path's Subpath lands at this level only.
            due = (lambda f: f["granted_at_cl"] <= cl) if owner == pid else (lambda f: f["granted_at_cl"] == cl)
            subpaths.append({"path_id": owner, "name": published_path_records()[owner]["display_name"],
                "options": [{"id": row["canonical_id"], "name": row["display_name"],
                             "minimum_cl": row["minimum_cl"], "legal": cl >= row["minimum_cl"],
                             "requires_confirmation": bool(row["access"].get("access_source_record_required")
                                                           or row["prerequisites"].get("explicit")),
                             "access": row["access"]["canonical_category"],
                             "features": [f["display_name"] for f in row["feature_progression"] if due(f)],
                             "feature_rows": [{"id": f["canonical_id"], "name": f["display_name"],
                                 "text": (f.get("source") or {}).get("excerpt") or ""}
                                 for f in row["feature_progression"] if due(f)],
                             "build_choices": feature_menu(
                                 [f for f in row["feature_progression"] if due(f)])}
                            for row in source().subpath_catalog(owner)["records"]]})
    notes: list[str] = []
    _feature_rows(sheet, cl, _subpaths(sheet), pid, notes)
    advancement = [row for row in plan["milestones"] if row["feature_kind"] == "advancement_choice"]
    insight_options = insight_menu(preview, insights) if advancement else []
    return {"available": True, "reason": "", "cl": cl, "history": history,
            "feature_choices": feature_menu(_feature_rows(sheet, cl, _subpaths(sheet), pid)),
            "pending_feature_choices": pending_feature_choices(sheet),
            "scores": ta.current_scores(preview), "key_ability": have["key_ability"],
            "known": {key: sorted(have[key]) for key in KNOWN_KEYS},
            "owned_features": (preview.get("path_and_subpath") or {}).get("path_feature_record_ids") or [],
            "resource_formulas": resource_formula_roots(preview), "ac_residual": ta.unrelated_ac_bonus(preview),
            "features": [{"id": r["canonical_id"], "name": r["display_name"],
                          "text": r.get("effective_rules_text") or r.get("source_rules_text") or ""}
                         for r in _feature_rows(sheet, cl, _subpaths(sheet), pid)],
            "talent_count": plan["talent_count"], "talents": choices, "subpaths": subpaths,
            "add_error": add_error, "add_path": _add_record(add) if pid else None,
            "primary_method": _primary_method_view(_recorded_primary_method(sheet, primary_method_id)),
            "add_candidates": [{"id": key, "name": record["display_name"]}
                               for key, record in sorted(published_path_records().items())
                               if _is_path_key(key) and key not in ta.known(sheet)["paths"]],
            "foundation": table_foundation.menu(sheet, cl, ta.known(preview)["paths"],
                                                _recorded_primary_method(sheet, primary_method_id), source()),
            "duplicate_notes": notes,
            
            "advancement_choice": bool(advancement), "ability_rule": ta.level_increase_rule(preview),
            "insights": insight_options,
            "before_statistics": {"hp": sheet["ability_scores_and_statistics"].get("hit_points"),
                                  "ac": sheet["ability_scores_and_statistics"].get("armor_class"),
                                  "resource": sheet["ability_scores_and_statistics"].get("primary_resource")},
            "statistics": {"hp": preview["ability_scores_and_statistics"].get("hit_points"),
                           "resource": preview["ability_scores_and_statistics"].get("primary_resource"),
                           "ac": preview["ability_scores_and_statistics"].get("armor_class"),
                           "pb": have["pb"]}}


def insight_menu(sheet: dict[str, Any], insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stage 2 acquisition data plus campaign status for local draft filtering."""
    from . import table_growth
    from stage2.insight_authority import compile_insight_stage2_authority
    result = []
    resource = sheet["ability_scores_and_statistics"].get("primary_resource") or {}
    resources = {str(r.get("name") or "").lower() for r in resource.get("definitions") or []}
    resources.add(str(resource.get("name") or "").lower())
    for record in insights:
        key = record["canonical_insight_id"]
        rule = compile_insight_stage2_authority(record, key)
        status = table_growth.insight_status(record, sheet)
        choice_options = [{"id": v, "name": v.title(), "summary": "Use your " + v.title() + " pool."}
                          for v in sorted(resources & {"qi", "stamina", "resonance"})] if key in table_growth.choice_rules() else []
        result.append({"id": key, "name": record["display_name"], "summary": record.get("full_description") or "",
            "ability_rule": rule["ability_change"], "requirements": rule["typed_prerequisites"],
            "minimum_cl": rule["minimum_cl"], "maximum": rule["repeatability"]["maximum"],
            "known_count": table_growth.insight_ids(sheet).count(key),
            "choice_options": choice_options, "selectable": bool(record.get("selectable")),
            **status})
    return result


def resource_formula_roots(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose the selected pool's same safe formula components for local previews."""
    primary = sheet["ability_scores_and_statistics"].get("primary_resource") or {}
    definitions = primary.get("definitions") or []
    selected = next((r for r in definitions if (primary.get("resource_id") and r.get("resource_id") == primary["resource_id"])
                     or (primary.get("name") and r.get("name") == primary["name"])), primary)
    roots = []
    for term in selected.get("authority_components") or [selected]:
        formula = term.get("base_formula") or term.get("formula_trace") or ta._published_formulas().get(term.get("formula_id"))
        if isinstance(formula, dict):
            roots.append(ta._formula_root(formula))
    return roots


def planning_menu(sheet: dict[str, Any], talents: list[dict[str, Any]], saved: dict[str, Any],
                  insights: list[dict[str, Any]], *, primary_method_id: str = "") -> dict[str, Any]:
    """Load the bounded CL2–20 planning database once; no request per pick.

    Templates include all candidates, acquisition constraints and Subpath
    progressions. The browser filters against earlier draft gains; prepare()
    remains authoritative and rechecks every level before the single commit.
    """
    result = menu(sheet, talents, saved, insights, primary_method_id=primary_method_id)
    if not result["available"]:
        return result
    # Every Path the character could add now, with its Subpath and feature choices, before any access is recorded.
    result["add_templates"] = {}
    for candidate in result["add_candidates"]:
        view = menu(sheet, talents, saved, insights, {"path_id": candidate["id"], "access": "", "source_id": ""},
                    primary_method_id=primary_method_id)
        result["add_templates"][candidate["id"]] = {
            "subpaths": view["subpaths"], "feature_choices": view["feature_choices"], "features": view["features"],
            "foundation_options": table_foundation.menu(sheet,
                max(result["cl"], table_foundation.fm.INITIAL_FOUNDATION_MECHANICS_POLICY["acquisition_cl"]),
                list(dict.fromkeys(ta.known(sheet)["paths"] + [candidate["id"]])),
                _recorded_primary_method(sheet, primary_method_id), source())}
    templates = []
    future = sheet
    for cl in range(ta.known(sheet)["cl"] + 1, 21):
        templates.append(menu(future, talents, saved, insights, primary_method_id=primary_method_id))
        future = advance_sheet(future, [{"cl": cl}], preview=True)
    have = _published_known(sheet)
    result["planning"] = templates
    result["ac_rules"] = ta._path_statistic_formulas()["rules"]
    import json
    pack = json.loads((ROOT / "authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json").read_text())
    result["ac_baseline"] = next(r["formula"]["root"] for r in pack["rules"] if r["rule_id"] == ta._UNARMORED_AC_RULE_ID)
    result["known"] = {key: sorted(have[key]) for key in KNOWN_KEYS}
    # Candidate Paths are included so a pending add's Subpath keeps its later-level rows in every planned level.
    offered = set(have["paths"]) | {c["id"] for c in result["add_candidates"]}
    result["subpath_progressions"] = {
        key: [{"cl": cl, "features": [{"id": f["canonical_id"], "name": f["display_name"],
                       "text": (f.get("source") or {}).get("excerpt") or ""}
                      for f in row["feature_progression"] if f["granted_at_cl"] == cl],
               "build_choices": feature_menu([f for f in row["feature_progression"] if f["granted_at_cl"] == cl])}
              for cl in sorted({f["granted_at_cl"] for f in row["feature_progression"]})]
        for key, row in source().subpaths.items() if row["owning_path_id"] in offered}
    return result


def prepare(sheet: dict[str, Any], saved: dict[str, Any], choices: dict[str, Any],
            talents: list[dict[str, Any]], insights: list[dict[str, Any]] = (), *, primary_method_id: str = "") -> dict[str, Any]:
    """Build one atomic acquisition. Caller must project before saving."""
    primary_method_id = _recorded_primary_method(sheet, primary_method_id)
    add = _choice_add(choices)
    options = menu(sheet, talents, saved, insights, add, primary_method_id=primary_method_id)
    if not options["available"]:
        reject(options["reason"])
    if options["add_error"]:
        reject(options["add_error"])
    if add and add["access"] == "primary_method":
        add["method_id"] = primary_method_id
    pid = add["path_id"] if add else ""
    if choices.get("cl") != options["cl"]:
        reject("The character changed. Reload Level up and review the next level.")
    cl = options["cl"]
    foundation = table_foundation.selection(sheet, cl, choices,
        list(dict.fromkeys(ta.known(sheet)["paths"] + ([pid] if pid else []))),
        _recorded_primary_method(sheet, primary_method_id), source())
    selected = choices.get("subpaths") or {}
    if set(selected) != {row["path_id"] for row in options["subpaths"]}:
        reject("Choose exactly one Subpath for each Path offered at this level.")
    for group in options["subpaths"]:
        row = next((r for r in group["options"] if r["id"] == selected[group["path_id"]]), None)
        if row is None or not row["legal"]:
            reject("Choose a Subpath belonging to the offered Path and available at this cultivation level.")
        if row["requires_confirmation"] and not choices.get("access_confirmed"):
            reject("Ask the Game Master to confirm access to the selected Subpath.")
    features = _feature_rows(sheet, cl, {**_subpaths(sheet), **selected}, pid)
    feature_choices = choices.get("feature_choices") or {}
    resolve_feature_choices(features, feature_choices)
    picked = choices.get("talent_ids") or []
    if len(picked) != options["talent_count"] or len(set(picked)) != len(picked):
        reject(f"Choose exactly {options['talent_count']} new level talent.")
    by_id = {r["id"]: r for r in options["talents"]}
    if any(key not in by_id or not by_id[key]["legal"] for key in picked):
        reject("Choose a legal, unlearned talent from a Sphere you know.")
    out = copy.deepcopy(saved)
    before = {key: copy.deepcopy(value) for key, value in saved.items() if key != "levels"}
    row = {"cl": cl, "subpaths": dict(selected), "access_confirmed": bool(choices.get("access_confirmed")),
           "feature_choices": dict(feature_choices),
           "at": ta.now(), "source": "level",
           "path_progression_by_cl": {str(cl): authority(sheet, cl, pid)["entries"][0]["path_id"]},
           "path_progression_entries_by_cl": {str(cl): [e["path_id"] for e in authority(sheet, cl, pid)["entries"]]},
           **({"add_path": _add_record(add)} if pid else {}),
           **({"foundation": foundation} if foundation else {})}
    out["talents"] += [{"id": key, "cl": cl, "source": "level", "gm": False, "at": row["at"]} for key in picked]
    if options["advancement_choice"]:
        if choices.get("advancement") == "ability":
            entry = {"reason": "level_increase", "cl": cl, "changes": choices.get("changes") or {}, "at": row["at"]}
            preview = advance_sheet(sheet, [_level_view(cl, selected, feature_choices, add)], primary_method_id=primary_method_id)
            status = ta.ability_status(entry, preview)
            if not status["legal"]:
                reject("; ".join(status["reasons"]))
            out["abilities"].append(ta._ability_entry(entry))
        elif choices.get("advancement") == "insight":
            from . import table_growth
            from stage2.insight_authority import compile_insight_stage2_authority
            record = next((r for r in insights if r["canonical_insight_id"] == choices.get("insight_id")), None)
            if record is None:
                reject("Choose an Insight from the offered list.")
            preview = ta.memorized(advance_sheet(sheet, [_level_view(cl, selected, feature_choices, add)], primary_method_id=primary_method_id))
            preview.setdefault("spheres_and_talents", {}).setdefault("learned_talent_record_ids", []).extend(picked)
            status = table_growth.insight_status(record, preview, choice=choices.get("insight_choice") or "")
            if not status["legal"] and not (status["gm"] and choices.get("access_confirmed")):
                reject("; ".join(status["reasons"]))
            rule = compile_insight_stage2_authority(record, record["canonical_insight_id"])["ability_change"]
            ability = choices.get("insight_ability")
            changes = {ability: rule["amount"]} if rule and ability in rule["allowed_abilities"] else {}
            if not changes or ta.current_scores(preview)[ability] + rule["amount"] > rule["cap"]:
                reject("Choose one of this Insight's listed ability increases below its score limit.")
            if choices.get("changes"):
                reject("An Insight replaces the normal ability-score increase.")
            out["insights"].append({"id": record["canonical_insight_id"], "name": record["display_name"],
                "text": record.get("full_description") or "", "cl": cl, "source": "level", "note": "Level up",
                "choice": choices.get("insight_choice") or "", "parameters": status["parameters"],
                "gm": status["gm"], "at": row["at"]})
            out["abilities"].append(ta._ability_entry({"reason": "insight_selection", "changes": changes, "cl": cl,
                "insight_rule": rule, "at": row["at"]}))
        else:
            reject("Choose ability scores or a Cultivation Insight.")
    elif choices.get("advancement") or choices.get("changes") or choices.get("insight_id"):
        reject("This level does not offer an ability-score or Insight selection.")
    row["features"] = [{"id": r["canonical_id"], "name": r["display_name"]}
                       for r in _feature_rows(sheet, cl, {**_subpaths(sheet), **selected}, pid)]
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
