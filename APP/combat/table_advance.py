"""Changing a finished character at the table (owner 2026-09-27: "the character sheets be updated with new spheres etc
so when the player is playing theres a way to interact with the sheets"; ruling: rules-checked, with a GM override).

What the table adds is kept beside the character (combat/tabletop.py ButtonStore, "advancement") and laid over its
sealed sheet wherever the sheet is read (combat/gate5_service.py _factory_owner_sheet), so the table sheet, combat and
the roster all see the same character; the Factory package is never rewritten. A Sphere is legal when one of the
character's Paths can learn it (factory_authoring/path_access.py); a talent when its Sphere is known and its typed
prerequisites hold (the canonical catalog's clauses: CL, Realm, Sphere, talent and Path requirements). What the catalog
cannot judge is left to the GM. The GM override adds anything anyway, and the addition is marked as a GM grant.
Forged Techniques are built and checked by character_creation/constructed_arts/forged_technique.py.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.core import FoundryError
from character_builder.service import CharacterBuilderService, POINT_BUY_BUDGET, POINT_BUY_COSTS
from stage2 import ability_changes
from stage2.ability_changes import ability_change_rule, published_path_records, published_records
from stage2.formulas import evaluate_formula
from projector import path_feature_statistics

SCHEMA = "TianxiaTableAdvancement.v1"
_REALMS = (("Mortal", 1), ("Foundation", 5), ("Core Formation", 10), ("Nascent Soul", 15), ("Immortal", 20))


ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
REASONS = ("gm_respec", "level_increase")
POINT_BUY_COST = POINT_BUY_COSTS
# Stable rule ID in Tianxia_Core_Character_Baseline_Authority_Pack_R1.json.
_UNARMORED_AC_RULE_ID = "tianxia.core.unarmored_ac.owner_r1"


@lru_cache(maxsize=1)
def _path_statistic_formulas() -> dict[str, Any]:
    """Read the sealed Path AC authority once, not on every sheet overlay."""
    return path_feature_statistics.load_path_feature_statistic_formulas(Path(__file__).resolve().parents[1])


def level_increase_rule(sheet: dict[str, Any]) -> dict[str, Any]:
    identity = sheet.get("identity") or {}
    paths = identity.get("path_ids") or (sheet.get("path_and_subpath") or {}).get("path_record_ids") or []
    if not paths and identity.get("path_id"):
        paths = [identity["path_id"]]
    return ability_change_rule(paths)




def build_kinds() -> tuple[str, ...]:
    """The table-side build-choice kinds the plug-ins register (combat/ext registry); each kind keeps its own row list."""
    from .ext import build_choice_kinds

    return build_choice_kinds()


BREAKTHROUGH_CLS = (5, 10, 15, 20)  # Realm thresholds a successful breakthrough can be recorded at


def empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "spheres": [], "talents": [], "forged": [], "manuals": [], "abilities": [], "levels": [],
            "insights": [], "immortal_arts": [], "method_changes": [], "breakthroughs": [], "feature_uses": [],
            **{kind: [] for kind in build_kinds()}}


def normalized(document: Any) -> dict[str, Any]:
    out = empty()
    if isinstance(document, dict):
        for key in ("spheres", "talents", "forged", "manuals", "levels", "insights", "immortal_arts", "method_changes",
                    "breakthroughs", "feature_uses", *build_kinds()):
            out[key] = [row for row in document.get(key) or [] if isinstance(row, dict)]
        out["abilities"] = [_ability_entry(row) for row in document.get("abilities") or [] if isinstance(row, dict)]
    return out


def _ability_entry(row: dict[str, Any]) -> dict[str, Any]:
    """{"type": "ability", "changes": {...}, "reason": "gm_respec" | "level_increase", "cl": int, "note": str, "gm": bool}.
    A gm_respec's changes are the six new scores; a level_increase's changes are the bounded deltas."""
    raw = row.get("changes") if isinstance(row.get("changes"), dict) else {}
    changes: dict[str, int | None] = {}
    for ability in ABILITIES:
        if ability in raw:
            value = raw[ability]
            changes[ability] = int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    return {"type": "ability", "changes": changes, "reason": str(row.get("reason") or ""), "cl": int(row.get("cl") or 0),
            "note": str(row.get("note") or "")[:240], "gm": bool(row.get("gm")), "at": str(row.get("at") or ""),
            **({"insight_rule": copy.deepcopy(row["insight_rule"])} if row.get("reason") == "insight_selection" else {})}


def ability_modifier(score: int) -> int:
    return (int(score) - 10) // 2


def current_scores(sheet: dict[str, Any]) -> dict[str, int]:
    rows = (sheet.get("ability_scores_and_statistics") or {}).get("abilities") or []
    return {str(row["ability"]): int(row["score"]) for row in rows
            if isinstance(row, dict) and row.get("ability") in ABILITIES and isinstance(row.get("score"), int)}


def default_spread(key_ability: str) -> dict[str, int]:
    """The optimized starting spread: 15/14/13/12/10/8 with the key ability first, then CON, DEX, WIS, INT, CHA, STR.
    It spends exactly the 27 points (9+7+5+4+2+0) and is the preview's starting point."""
    key = str(key_ability or "").upper()
    order = [key] if key in ABILITIES else []
    order += [a for a in ("CON", "DEX", "WIS", "INT", "CHA", "STR") if a not in order]
    return dict(zip(order, (15, 14, 13, 12, 10, 8)))


def ability_status(entry: dict[str, Any], sheet: dict[str, Any], *,
                   earned_bonuses: dict[str, int] | None = None,
                   require_current_cl: bool = True) -> dict[str, Any]:
    """{"legal", "gm", "reasons"} for one entry against its preceding scores.

    New increases must match the current CL. Revalidating persisted growth after
    a history replay checks its recorded opportunity instead, not a new acquisition.
    """
    reasons: list[str] = []
    changes = entry.get("changes") or {}
    scores = current_scores(sheet)
    cl = int((sheet.get("identity") or {}).get("cultivation_level") or 1)
    if not changes or any(value is None for value in changes.values()):
        return {"legal": False, "gm": False, "reasons": ["every changed ability needs a whole-number score"]}
    if entry.get("reason") == "gm_respec":
        if set(changes) != set(ABILITIES):
            reasons.append("a respec sets all six scores")
        else:
            try:
                CharacterBuilderService.validate_point_buy(changes)
            except FoundryError as exc:
                reasons.append(str(exc))
            if any(not isinstance(value, int) or isinstance(value, bool) or not 8 <= value <= 15 for value in changes.values()):
                reasons.append("a respec base score must be between 8 and 15")
            bonuses = respec_bonuses(sheet) if earned_bonuses is None else earned_bonuses
            cap = int(level_increase_rule(sheet).get("cap", 20))
            if any(not 1 <= int(changes[a]) + bonuses.get(a, 0) <= cap for a in ABILITIES):
                reasons.append(f"resulting scores, including earned increases, must be between 1 and the published cap of {cap}")
    elif entry.get("reason") == "level_increase":
        at = int(entry.get("cl") or 0)
        if require_current_cl and at != cl:
            reasons.append(f"the ability increase must be recorded at CL {at}; the character is currently CL {cl}")
        reasons.extend(row["message"] for row in ability_changes.validate_ability_change(
            scores if len(scores) == len(ABILITIES) else {}, changes, at, level_increase_rule(sheet)))
    elif entry.get("reason") == "insight_selection":
        rule = entry.get("insight_rule") or {}
        at = int(entry.get("cl") or 0)
        if at not in level_increase_rule(sheet).get("allowed_cls", []) or (require_current_cl and at != cl):
            reasons.append("This level does not offer an Insight selection.")
        if (len(changes) != 1 or any(a not in rule.get("allowed_abilities", []) or n != rule.get("amount")
                                    for a, n in changes.items())
                or any(scores.get(a, 0) + n > rule.get("cap", 20) for a, n in changes.items())):
            reasons.append("Choose the Insight's published ability increase below its score limit.")
    else:
        reasons.append("choose a respec or a level increase")
    return {"legal": not reasons, "gm": False, "reasons": reasons}


def _formula_context(sheet: dict[str, Any], scores: dict[str, int]) -> dict[str, Any]:
    identity = sheet.get("identity") or {}
    return {"cl": int(identity.get("cultivation_level") or 1),
            "pb": int(identity.get("proficiency_bonus") or 2), "ability_scores": scores,
            "ability_modifiers": {a: ability_modifier(v) for a, v in scores.items()}}


def _formula_root(formula: dict[str, Any]) -> dict[str, Any]:
    """Recover executable AST from a stored SafeFormula or SafeFormulaTrace."""
    node = copy.deepcopy(formula.get("root", formula))
    def restore(value: Any) -> None:
        if not isinstance(value, dict):
            return
        if value.get("op") == "clamp" and "value_node" in value:
            value["value"] = value.pop("value_node")
        for child in value.values():
            if isinstance(child, list):
                for term in child:
                    restore(term)
            elif isinstance(child, dict):
                restore(child)
    restore(node)
    return node


@lru_cache(maxsize=1)
def _published_formulas() -> dict[str, dict[str, Any]]:
    """Resolve the formula IDs retained by projected Path resource definitions."""
    found = {}
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("formula_id") and isinstance(value.get("root"), dict):
                found[value["formula_id"]] = value
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(published_records())
    visit(published_path_records())
    return found


def _recompute_resources(block: dict[str, Any], old_context: dict[str, Any], context: dict[str, Any]) -> None:
    """Re-evaluate each stored pool's formula components; preserve its deficit.

    Projected definitions retain formula IDs and authority_components rather
    than ASTs. Resolve those IDs from published authority, not from a Path-name
    switch. A directly stored base_formula/trace is also supported.
    """
    primary = block.get("primary_resource")
    if not isinstance(primary, dict):
        return
    definitions = [row for row in primary.get("definitions") or [] if isinstance(row, dict)]
    for pool in definitions or [primary]:
        components = pool.get("authority_components") or []
        terms = components or [pool]
        moved = 0
        for term in terms:
            formula = term.get("base_formula") or term.get("formula_trace") or _published_formulas().get(term.get("formula_id"))
            if not isinstance(formula, dict):
                continue
            root = _formula_root(formula)
            before = evaluate_formula(root, old_context).value
            after = evaluate_formula(root, context)
            moved += after.value - before
            if term is not pool and isinstance(term.get("value"), int):
                term["value"] = after.value
            if term.get("formula_trace"):
                term["formula_trace"] = after.trace
        max_field = "max" if "max" in pool else "maximum"
        current_field = "current" if "current" in pool else "build_state_current"
        if isinstance(pool.get(max_field), int):
            prior_max = pool[max_field]
            pool[max_field] = max(0, prior_max + moved)
            if isinstance(pool.get(current_field), int):
                pool[current_field] = max(0, pool[max_field] - max(0, prior_max - pool[current_field]))
    if definitions:
        selected = next((row for row in definitions if
                         (primary.get("resource_id") and row.get("resource_id") == primary["resource_id"])
                         or (primary.get("name") and row.get("name") == primary["name"])), None)
        if selected:
            primary["maximum"] = selected.get("max", selected.get("maximum"))
            primary["build_state_current"] = selected.get("current", selected.get("build_state_current"))



def _bump(obj: Any, field: str, delta: int) -> None:
    """Move a stored total by delta; a formula trace that states it moves with it."""
    if not delta or not isinstance(obj, dict) or not isinstance(obj.get(field), int) or isinstance(obj.get(field), bool):
        return
    obj[field] += delta
    trace = obj.get("formula_trace")
    if isinstance(trace, dict) and isinstance(trace.get("root"), dict) and isinstance(trace["root"].get("value"), int):
        trace["root"]["value"] += delta


def unrelated_ac_bonus(sheet: dict[str, Any]) -> int:
    """AC residual outside authenticated Path bonuses, for level/score reprojection.

    Both table_levelup and recompute_from_abilities use this. Modern provenance
    identifies folded bonuses; legacy sheets use the same authority matching as
    armour.sheet_ac_bonuses, including its bounded folded-bonus convention.
    """
    from .armour import sheet_ac_bonuses
    armor = (sheet.get("ability_scores_and_statistics") or {}).get("armor_class") or {}
    if not isinstance(armor, dict):
        return 0
    delta = int(armor.get("value") or armor.get("base_value") or 10) - int(armor.get("base_value") or armor.get("value") or 10)
    generation = armor.get("generation")
    if isinstance(generation, dict) and "calculation_feature_id" in generation:
        return delta - sum(int(r.get("bonus") or 0) for r in generation.get("always_on_bonuses") or [])
    # Clearing only the totals lets the public resolver report authenticated
    # applicable bonuses; don't infer a Path bonus from the residual itself.
    bare = copy.deepcopy(sheet)
    ac = bare["ability_scores_and_statistics"]["armor_class"]
    ac["value"] = ac.get("base_value") or ac.get("value") or 10
    mods = {a: ability_modifier(n) for a, n in current_scores(sheet).items()}
    applicable, _ = sheet_ac_bonuses(bare, {}, mods, [])
    return delta - min(max(0, delta), applicable)


def recompute_from_abilities(sheet: dict[str, Any], old_scores: dict[str, int], new_scores: dict[str, int]) -> dict[str, Any]:
    """The sheet with every score-derived number moved from old_scores to new_scores. Each stored total moves by the change
    in the modifier it uses: initiative, skills and saving throws by their ability; the technique attack bonus and save DC
    by the key ability; armor class by DEX when its calculation names Dexterity; hit point maximum by the CON modifier
    change times CL (and current HP too when it was at maximum). The input sheet is not changed.

    This is arithmetic, not an acquisition route: apply() validates the entire
    growth history before calling it once with the resulting final scores.
    """
    residual_ac = unrelated_ac_bonus(sheet)
    out = copy.deepcopy(sheet)
    block = out.setdefault("ability_scores_and_statistics", {})
    cl = int((out.get("identity") or {}).get("cultivation_level") or 1)
    delta = {a: ability_modifier(new_scores[a]) - ability_modifier(old_scores[a]) for a in ABILITIES if a in old_scores and a in new_scores}
    rows = [row for row in block.get("abilities") or [] if isinstance(row, dict)]
    known_rows = {row.get("ability") for row in rows}
    for row in rows:
        if row.get("ability") in new_scores:
            row["score"], row["modifier"] = new_scores[row["ability"]], ability_modifier(new_scores[row["ability"]])
    block["abilities"] = rows + [{"ability": a, "score": new_scores[a], "modifier": ability_modifier(new_scores[a])}
                                 for a in ABILITIES if a in new_scores and a not in known_rows]
    key = str((out.get("identity") or {}).get("key_ability") or "").upper()
    _bump(block.get("initiative"), "bonus", delta.get((block.get("initiative") or {}).get("ability"), 0))
    armor = block.get("armor_class")
    if isinstance(armor, dict):
        # Armor class: its SafeFormulaTrace root moves by the ability terms it names (DEX unarmored, or a Path's CON + PB).
        trace_root = (armor.get("formula_trace") or {}).get("root") if isinstance(armor.get("formula_trace"), dict) else None
        moved = 0
        if isinstance(trace_root, dict):
            result = evaluate_formula(_formula_root(trace_root), _formula_context(out, new_scores))
            moved = result.value - evaluate_formula(_formula_root(trace_root), _formula_context(out, old_scores)).value
            armor["formula_trace"] = result.trace
        for field in ("value", "base_value"):
            if moved and isinstance(armor.get(field), int):
                armor[field] += moved
        # Re-evaluate every eligible calculation, not just the former winner.
        # The generation record supplies the legal alternatives; typed authority
        # supplies their formulas and any winner-dependent always-on bonuses.
        generation = armor.get("generation")
        if isinstance(generation, dict) and isinstance(generation.get("alternatives_considered"), list):
            try:
                formulas = _path_statistic_formulas()
                options = generation["alternatives_considered"]
                owned_ids = {row.get("calculation_id") for row in options}
                owned_ids.update(row.get("rule_id") for row in [
                    *(generation.get("always_on_bonuses") or []),
                    *(generation.get("conditional_bonus_sources") or []),
                ])
                owned_rules = [row for row in formulas.get("rules") or [] if row.get("rule_id") in owned_ids]
                by_id = {row["rule_id"]: row for row in owned_rules}
                baseline = next((row for row in options
                                 if row.get("calculation_id") == _UNARMORED_AC_RULE_ID), None)
                if baseline is None:
                    raise ValueError("The unarmored AC rule is missing from the recorded alternatives.")
                baseline_rule = by_id.get(baseline["calculation_id"]) or {
                    "rule_id": baseline["calculation_id"],
                    "formula": {"formula_id": "table.unarmored_baseline", "root": {"op": "add", "terms": [
                        {"op": "constant", "value": 10},
                        {"op": "ability_modifier", "ability": "DEX"},
                    ]}},
                }
                context = _formula_context(out, new_scores)
                result = evaluate_formula(baseline_rule["formula"]["root"], context)
                # The projection resolver keeps inactive owned bonuses as
                # conditional sources, so a later score reset can restore them.
                resolved = path_feature_statistics.resolve_armor_class(
                    {"rules": owned_rules}, [row.get("feature_id") for row in owned_rules],
                    baseline_rule=baseline_rule, baseline_value=result.value,
                    baseline_trace=result.trace, context=context)
                armor.update(base_value=resolved["ac_base"], value=resolved["ac_active"] + residual_ac,
                             formula_trace=resolved["ac_generation"]["trace"],
                             generation=resolved["ac_generation"])
            except (FoundryError, KeyError, TypeError, ValueError) as exc:
                raise FoundryError(
                    "TABLE_ADVANCE_ARMOR_CLASS_RECALCULATION_FAILED",
                    "Could not recalculate Armor Class after changing ability scores. No score change was applied.",
                    status_code=409,
                    details={"cause": str(exc)},
                ) from exc
    _bump(block, "technique_attack_bonus", delta.get(key, 0))
    _bump(block, "technique_save_dc", delta.get(key, 0))
    hp = block.get("hit_points")
    if isinstance(hp, dict) and delta.get("CON"):
        con = delta["CON"]
        gain = con * cl
        was_full = hp.get("build_state_current") == hp.get("maximum")
        _bump(hp, "maximum", gain)
        if was_full:
            _bump(hp, "build_state_current", gain)
        # Each level's HP gain moves by the CON change; the running maximum moves by that change times the level count.
        levels = (hp.get("progression") or {}).get("levels") or []
        for index, level in enumerate(levels, start=1):
            if isinstance(level, dict):
                _bump(level, "gain", con)
                _bump(level, "maximum", con * index)
    for skill in block.get("skills") or []:
        if isinstance(skill, dict):
            _bump(skill, "bonus", delta.get(skill.get("ability"), 0))
    _recompute_resources(block, _formula_context(out, old_scores), _formula_context(out, new_scores))
    saves = block.get("saving_throws")
    if isinstance(saves, dict):
        for ability in delta:
            if isinstance(saves.get(ability), int):
                saves[ability] += delta[ability]
    elif isinstance(saves, list):
        for row in saves:
            if isinstance(row, dict):
                _bump(row, "bonus", delta.get(row.get("ability"), 0))
    # Missing totals must include explicitly declared proficiency, not merely
    # fall back to raw modifiers when compilation reads the adjusted sheet.
    declared = block.get("saving_throw_proficiencies") or []
    if isinstance(declared, str):
        declared = json.loads(declared) if declared.startswith("[") else []
    if declared and (saves is None or isinstance(saves, dict)):
        totals = block.setdefault("saving_throws", {}) if saves is not None else {}
        pb = int((out.get("identity") or {}).get("proficiency_bonus") or 2)
        for ability in ABILITIES:
            if ability not in totals and ability in new_scores:
                totals[ability] = ability_modifier(new_scores[ability]) + (pb if ability in declared else 0)
        block["saving_throws"] = totals
    out.setdefault("table_advancement", {}).setdefault("ability_recomputes", []).append(
        {"old": dict(old_scores), "new": dict(new_scores), "modifier_delta": {a: v for a, v in delta.items() if v}})
    return out


def memorized(sheet: dict[str, Any]) -> dict[str, Any]:
    """Every talent in the character's manuals is known (owner 2026-09-27: "lets assume the manual is all memorized for
    these characters and the ones i make"): a training source's manual collection adds its talents to the learned ones
    once the character's CL reaches each one's minimum. The input sheet is not changed."""
    cl = int((sheet.get("identity") or {}).get("cultivation_level") or 1)
    block = sheet.get("spheres_and_talents") or {}
    have = set(block.get("learned_talent_record_ids") or []) | set(block.get("automatic_sphere_component_record_ids") or [])
    added: list[str] = []
    for source in sheet.get("training_sources") or []:
        contents = (source or {}).get("contents") or {}
        bindings = ((contents.get("manual_collection") or {}).get("content_record_bindings")) or []
        details = contents.get("recorded_art_details") or []
        for index, binding in enumerate(bindings):
            record_id = (binding or {}).get("record_id")
            minimum = int(((details[index] if index < len(details) else {}) or {}).get("minimum_cl") or 1)
            if record_id and record_id not in have and record_id not in added and cl >= minimum:
                added.append(record_id)
    if not added:
        return sheet
    out = copy.deepcopy(sheet)
    learned = out.setdefault("spheres_and_talents", {}).setdefault("learned_talent_record_ids", [])
    learned.extend(added)
    out["memorized_from_manuals"] = added
    return out


def manual_source(row: dict[str, Any]) -> dict[str, Any]:
    """A manual the table gave the character, shaped like the Factory's training sources so the sheet lists it."""
    talents = [str(talent) for talent in row.get("talents") or [] if talent]
    return {"name": row.get("name") or "Manual", "type": "manual", "source_id": row.get("id"), "gained_at_cl": row.get("cl"),
            "table_granted": True, "gm": bool(row.get("gm")),
            "contents": {"manual_collection": {"collection_id": row.get("id"), "content_record_bindings": [{"record_id": talent} for talent in talents]},
                         "recorded_art_details": [{"record_id": talent, "minimum_cl": 1} for talent in talents], "recorded_arts": talents}}


def overlay_key(document: Any) -> str:
    return hashlib.sha256(json.dumps(normalized(document), sort_keys=True).encode("utf-8")).hexdigest()[:16]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def known(sheet: dict[str, Any]) -> dict[str, Any]:
    """What a sheet (with the table's additions laid over it) already has."""
    identity = sheet.get("identity") or {}
    paths_block = sheet.get("path_and_subpath") or {}
    block = sheet.get("spheres_and_talents") or {}
    talents = set(block.get("learned_talent_record_ids") or []) | set(block.get("automatic_sphere_component_record_ids") or [])
    if block.get("background_talent_record_id"):
        talents.add(block["background_talent_record_id"])
    paths = list(identity.get("path_ids") or paths_block.get("path_record_ids") or [])
    return {"cl": int(identity.get("cultivation_level") if identity.get("cultivation_level") is not None else 1), "pb": int(identity.get("proficiency_bonus") or 2),
            "key_ability": str(identity.get("key_ability") or "CON").upper(), "paths": paths,
            "path_id": paths_block.get("path_record_id") or (paths[0] if paths else None),
            "spheres": set(block.get("sphere_record_ids") or []), "talents": talents,
            "forged": [row for row in sheet.get("forged_techniques") or [] if isinstance(row, dict)]}


def realm_of(cl: int) -> str:
    return [name for name, least in _REALMS if cl >= least][-1] if cl >= 1 else "Mortal"


def _holds(constraint: dict[str, Any], have: dict[str, Any]) -> bool | None:
    """True/False for what the rules can judge; None for what only the GM can."""
    kind = constraint.get("kind")
    if kind == "minimum_cl":
        return have["cl"] >= int(constraint.get("value") or 0)
    if kind in ("owning_sphere", "sphere"):
        return constraint.get("target_id") in have["spheres"]
    if kind == "talent":
        return constraint.get("target_id") in have["talents"]
    if kind == "structural_authority":
        from .factory_compiler import TYPED_AUTHORITY
        target = constraint.get("target_id")
        if not isinstance(target, str) or not target:
            return None
        aliases = structural_component_ids(TYPED_AUTHORITY.stat().st_mtime)
        return True if target in have["talents"] or any(aliases.get(rid) == target for rid in have["talents"]) else None
    if kind == "path":
        return constraint.get("target_id") in have["paths"]
    if kind == "realm":
        want = str(constraint.get("value") or constraint.get("target_id") or "")
        order = [name.lower() for name, _ in _REALMS]
        mine = order.index(realm_of(have["cl"]).lower())
        normalized = want.lower().replace("_", " ").replace(".", " ")
        return next((mine >= index for index, name in enumerate(order)
                     if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", normalized)), None)
    return None


def talent_status(record: dict[str, Any], have: dict[str, Any]) -> dict[str, Any]:
    """{"legal": bool, "gm": bool, "reasons": [...]} for learning one catalog talent now."""
    constraints = [row for row in (record.get("typed_constraints") or record.get("typed_prerequisites") or [])
                   if isinstance(row, dict) and row.get("scope", "acquisition") == "acquisition"]
    reasons: list[str] = []
    gm = False
    names = {row.get("target_id"): row.get("display_name") or row.get("raw_text") for row in constraints}

    def held(row):
        from canonical_catalog.service import structural_realm_requirement
        minimum = structural_realm_requirement(row, record)
        return have["cl"] >= minimum if minimum is not None else _holds(row, have)

    def describe(row: dict[str, Any]) -> str:
        kind = row.get("kind")
        if kind == "minimum_cl":
            return f"needs CL {row.get('value')}"
        if kind in ("owning_sphere", "sphere"):
            return f"needs the {names.get(row.get('target_id')) or row.get('target_id')} Sphere"
        if kind == "talent":
            return f"needs {row.get('display_name') or row.get('raw_text') or row.get('target_id')}"
        return str(row.get("raw_text") or kind)

    for row in constraints:
        if row.get("alternative_id"):
            continue  # judged with its clause below
        result = held(row)
        if result is None:
            gm = True
            reasons.append(f"GM: {describe(row)}")
        elif not result:
            reasons.append(describe(row))
    for clause in record.get("prerequisite_clauses") or []:
        if not isinstance(clause, dict) or clause.get("scope", "acquisition") != "acquisition":
            continue
        verdicts = []
        for alternative in clause.get("alternatives") or []:
            rows = [row for row in constraints if row.get("alternative_id") == alternative.get("alternative_id")]
            results = [held(row) for row in rows]
            verdicts.append(None if None in results and False not in results else all(results) if rows else None)
        if True in verdicts:
            continue
        if None in verdicts:
            gm = True
            reasons.append(f"GM: {clause.get('body') or clause.get('raw_text')}")
        else:
            reasons.append(str(clause.get("body") or clause.get("raw_text") or "a prerequisite is not met"))
    if str(record.get("prerequisite_evaluation_status") or "").startswith("UNRESOLVED"):
        gm = True
        reasons.append(f"GM: {record.get('raw_prerequisite_text') or 'prerequisite the rules cannot check'}")
    hard = [reason for reason in reasons if not reason.startswith("GM: ")]
    return {"legal": not hard and not gm, "gm": gm and not hard, "reasons": reasons}


def sphere_status(sphere_id: str, have: dict[str, Any]) -> dict[str, Any]:
    from factory_authoring import path_access

    if have["cl"] < 1:
        return {"legal": False, "gm": False, "reasons": ["New-Sphere training requires Cultivation Level 1; level-0 Background grants use their own creation rule."]}
    if sphere_id in have["spheres"]:
        return {"legal": False, "gm": False, "reasons": ["already known"]}
    entry = path_access.access().get(sphere_id)
    if entry is None:
        return {"legal": False, "gm": True, "reasons": ["GM: this Sphere's Path access is not recorded"]}
    if not path_access.can_learn(sphere_id, have["paths"]):
        return {"legal": False, "gm": False, "reasons": [f"not open to {', '.join(path.split('.')[-1].replace('_', ' ').title() for path in have['paths']) or 'these Paths'}"]}
    return {"legal": True, "gm": False, "reasons": []}


@lru_cache(maxsize=2)
def structural_component_ids(mtime: float) -> dict[str, str]:
    """Exact same-Sphere structural names for acquired native base components.

    CAT3's structural targets use printed-name slugs; the combat authority uses
    runtime component IDs. Bind only a source-owned component's own exact name,
    never a substring, talent lookalike, or an unacquired Sphere.
    """
    from .factory_compiler import TYPED_AUTHORITY
    return {key: "tianxia.structural." + row["sphere_id"].removeprefix("tianxia.sphere.") + "."
            + re.sub(r"[^a-z0-9]+", "_", row["name"].casefold()).strip("_")
            for key, row in json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"].items()
            if row.get("kind") == "base_ability" and row.get("sphere_id") and row.get("name")}


@lru_cache(maxsize=2)
def _base_ability_index(mtime: float) -> dict[str, list[str]]:
    from .factory_compiler import TYPED_AUTHORITY

    index: dict[str, list[str]] = {}
    for key, row in json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"].items():
        if row.get("kind") == "base_ability" and row.get("sphere_id"):
            index.setdefault(row["sphere_id"], []).append(key)
    return {sphere: sorted(keys) for sphere, keys in index.items()}


def base_ability_index() -> dict[str, list[str]]:
    """Each Sphere's base abilities (read once per change of the typed authority)."""
    from .factory_compiler import TYPED_AUTHORITY

    return _base_ability_index(TYPED_AUTHORITY.stat().st_mtime)


def base_abilities(sphere_id: str, mechanics: dict[str, Any]) -> list[str]:
    """The automatic abilities a Sphere grants when it is learned."""
    return sorted(key for key, row in mechanics.items() if row.get("sphere_id") == sphere_id and row.get("kind") == "base_ability")


def _earned_ability_events(sheet: dict[str, Any]) -> list[tuple[int, dict[str, int]]]:
    """Creation and deduplicated sealed increases, with their recorded CL.

    Sealed selections are trusted producer data, not new acquisitions. Unknown
    legacy dates are treated as creation benefits, never as new opportunities.
    """
    events: list[tuple[int, dict[str, int]]] = []
    earned = {ability: 0 for ability in ABILITIES}
    background = (sheet.get("background_and_origin") or {}).get("background") or {}
    for ability, delta in (background.get("ability_score_change") or {}).items():
        if ability in earned and isinstance(delta, int) and not isinstance(delta, bool):
            earned[ability] += delta
    events.append((0, earned))
    history = sheet.get("advancement_history") or {}
    # A duplicate selection view may lack its enclosing level or appear before
    # the level view. Bind its date to the canonical event, not dict traversal.
    allocation_cls = {(key, row[key]): int(row["target_cl"])
                      for row in history.get("canonical_allocations") or []
                      if row.get("target_cl") is not None
                      for key in ("event_id", "event_hash", "packet_id") if row.get(key)}
    seen: set[tuple[str, Any]] = set()
    def visit(value: Any, cl: int = 0) -> None:
        if isinstance(value, dict):
            cl = int(value.get("target_cl") or value.get("effective_cl") or value.get("cl") or cl)
            # Selection events appear in multiple earned-feature views. Count a
            # persisted event only once, not once per deserialized Python object.
            kind = value.get("choice_kind") or value.get("advancement_kind") or value.get("kind")
            event = value.get("event") or {}
            marker = next(((key, event.get(key) or value.get(key)) for key in ("event_id", "event_hash", "packet_id")
                           if event.get(key) or value.get(key)), ("object", id(value)))
            deltas = value.get("deltas") or value.get("changes")
            if kind == "cultivation_insight_acquisition":
                # v3_bridge seals these fields on the selection itself; retain
                # the older nested format too. Missing amount means no grant.
                increase = value.get("ability_increase") or value
                deltas = {increase.get("ability"): increase.get("amount")}
            if kind in ("ability_score_change", "cultivation_insight_acquisition") and isinstance(deltas, dict):
                valid = {a: n for a, n in deltas.items()
                         if a in earned and isinstance(n, int) and not isinstance(n, bool)}
                if valid and marker not in seen:
                    seen.add(marker)
                    events.append((allocation_cls.get(marker, cl), valid))
            for child in value.values():
                visit(child, cl)
        elif isinstance(value, list):
            for child in value:
                visit(child, cl)
    visit(history)
    return events


def _earned_ability_deltas(sheet: dict[str, Any]) -> dict[str, int]:
    """All creation/sealed bonuses retained by a final-score reset preview."""
    return {a: sum(delta.get(a, 0) for _, delta in _earned_ability_events(sheet)) for a in ABILITIES}


def respec_bonuses(sheet: dict[str, Any], document: Any = None) -> dict[str, int]:
    """Earned increases retained by a base-score reset, for application, validation
    and the Grow preview. Pass the sealed sheet and the preceding table record;
    score resets never themselves grant another increase."""
    if document is None:
        return _earned_ability_deltas(sheet)
    return validate_ability_history(sheet, document)["bonuses"]


def recorded_ability_increase_cls(sheet: dict[str, Any], document: Any = None) -> list[int]:
    """Consumed sealed ASI/Insight and ordinary table opportunities.

    Explicit GM grants do not consume another level choice. This is shared by
    the history validator and the Grow preview, not copied into service routes.
    """
    recorded = [int(row["target_cl"]) for row in
                (sheet.get("advancement_history") or {}).get("canonical_allocations") or []
                if row.get("target_cl") is not None and row.get("advancement_kind") in {
                    "ability_score_change", "cultivation_insight_acquisition"}]
    recorded.extend(row["cl"] for row in normalized(document)["abilities"]
                    if row["reason"] in ("level_increase", "insight_selection") and not row["gm"])
    return recorded


def validate_ability_history(sheet: dict[str, Any], document: Any, *,
                             new_index: int | None = None) -> dict[str, Any]:
    """One chronological replay for Grow add/reset/remove/status and all overlays.

    Results contain statuses in storage-index order, final scores/bonuses and
    consumed levels. Replay is stable in CL order (storage order breaks ties),
    merging trusted sealed increases before table entries at the same CL.
    Only new_index is a new acquisition and must match the current CL.
    An explicit saved GM grant may violate rules, but malformed changes cannot
    be projected. Ordinary invalid entries make the whole history unacceptable;
    later resets never erase an earlier violation. No sheet or record is mutated.
    """
    from .table_method import replay
    table = normalized(document)
    sheet = replay(sheet, table["levels"], table["method_changes"])
    entries = normalized(document)["abilities"]
    rows = [{"index": index, **row, "status": {"legal": True, "gm": False, "reasons": []}}
            for index, row in enumerate(entries)]
    scores = current_scores(sheet)
    earned = dict.fromkeys(ABILITIES, 0)
    sealed = _earned_ability_events(sheet)
    # The install already contains every sealed increase. Reconstruct the
    # pre-increase scores so future sealed choices cannot taint earlier checks.
    for _, deltas in sealed:
        for a, delta in deltas.items():
            if a in scores:
                scores[a] -= delta
    events = [(cl, 0, i, deltas) for i, (cl, deltas) in enumerate(sealed)]
    events += [(row["cl"], 1, i, row) for i, row in enumerate(entries)]
    consumed = set(recorded_ability_increase_cls(sheet))
    cap = int(level_increase_rule(sheet).get("cap", 20))
    last_change: dict[str, int] = {}
    projectable = True
    for cl, source, index, value in sorted(events, key=lambda event: event[:3]):
        if source == 0:
            for a, delta in value.items():
                earned[a] += delta
                if a in scores:
                    scores[a] += delta
                    # A reset/increase can also invalidate a later sealed
                    # increase. Attribute that conflict to the table change;
                    # never silently discard the sealed benefit.
                    cause = last_change.get(a)
                    if cause is not None and not 1 <= scores[a] <= cap:
                        status = rows[cause]["status"]
                        message = f"a later recorded ability increase would exceed the published cap of {cap}"
                        if message not in status["reasons"]:
                            status["reasons"].append(message)
                        status["legal"] = False
            continue
        row = rows[index]
        preceding = {"identity": sheet.get("identity") or {},
                     "path_and_subpath": sheet.get("path_and_subpath") or {},
                     "ability_scores_and_statistics": {
                         "abilities": [{"ability": a, "score": n} for a, n in scores.items()]}}
        status = ability_status(value, preceding, earned_bonuses=earned,
                                require_current_cl=index == new_index)
        if value["reason"] in ("level_increase", "insight_selection"):
            if cl in consumed:
                status["reasons"].append(f"an ability increase was already recorded at CL {cl}")
                status["legal"] = False
            if not value["gm"]:
                consumed.add(cl)
        row["status"] = status
        changes = value["changes"]
        can_project = (len(scores) == len(ABILITIES) and bool(changes)
                       and all(type(n) is int for n in changes.values())
                       and value["reason"] in (*REASONS, "insight_selection")
                       and (value["reason"] != "gm_respec" or set(changes) == set(ABILITIES)))
        if not can_project:
            projectable = False
            continue
        if value["reason"] == "gm_respec":
            scores = {a: changes[a] + earned[a] for a in ABILITIES}
            last_change = dict.fromkeys(ABILITIES, index)
        else:
            for a, delta in changes.items():
                scores[a] += delta
                earned[a] += delta
                last_change[a] = index
    return {"legal": projectable and all(row["status"]["legal"] or row["gm"] for row in rows),
            "projectable": projectable, "entries": rows, "scores": scores,
            "bonuses": earned, "recorded_cls": recorded_ability_increase_cls(sheet, document)}


def require_ability_history(history: dict[str, Any]) -> None:
    """Reject a replay before any mutation or score-derived recomputation."""
    if not history["legal"]:
        reasons = [reason for row in history["entries"] if not row["gm"]
                   for reason in row["status"]["reasons"]]
        raise FoundryError("TABLETOP_ADVANCE_NOT_LEGAL",
                           "; ".join(reasons) or "This score change needs six whole-number ability scores.",
                           status_code=409)


def apply(sheet: dict[str, Any], document: Any, mechanics: dict[str, Any] | None = None) -> dict[str, Any]:
    """The sheet with the table's additions: learned Spheres (and their base abilities), learned talents and Forged
    Techniques. The input sheet is not changed."""
    table = normalized(document)
    if not any(table[key] for key in ("spheres", "talents", "forged", "manuals", "abilities", "levels", "insights", "immortal_arts", "method_changes")) \
            and not any(table[kind] for kind in build_kinds()):
        return sheet
    from .table_method import replay
    out = copy.deepcopy(replay(sheet, table["levels"], table["method_changes"]))
    block = out.setdefault("spheres_and_talents", {})
    spheres = list(block.get("sphere_record_ids") or [])
    automatic = list(block.get("automatic_sphere_component_record_ids") or [])
    learned = list(block.get("learned_talent_record_ids") or [])
    for row in table["spheres"]:
        if row.get("id") and row["id"] not in spheres:
            spheres.append(row["id"])
            granted = base_abilities(row["id"], mechanics) if mechanics is not None else base_ability_index().get(row["id"], [])
            automatic += [key for key in granted if key not in automatic]
    for row in table["talents"]:
        if row.get("id") and row["id"] not in learned:
            learned.append(row["id"])
    block.update({"sphere_record_ids": spheres, "automatic_sphere_component_record_ids": automatic, "learned_talent_record_ids": learned})
    existing_forged = out.get("forged_techniques")
    added_forged = [row["technique"] for row in table["forged"] if isinstance(row.get("technique"), dict)]
    if added_forged or not isinstance(existing_forged, dict):
        # A sealed "no technique" marker stays only while nothing is added; a list gains the table's techniques.
        out["forged_techniques"] = [*(existing_forged if isinstance(existing_forged, list) else []), *added_forged]
    # Manuals the table gave (owner 2026-09-27: "add cleaarsight to tabik damu, put it on a manual with a few other
    # things"): listed with the character's training sources; their talents are then known (memorized, below).
    out["training_sources"] = [*(out.get("training_sources") or []), *[manual_source(row) for row in table["manuals"]]]
    if table["abilities"]:
        history = validate_ability_history(sheet, table)
        require_ability_history(history)
        out = recompute_from_abilities(out, current_scores(sheet), history["scores"])
        reasons = {"gm_respec": "GM score reset", "level_increase": "level increase", "insight_selection": "Insight ability increase"}
        out["ability_scores_and_statistics"]["table_adjustment_note"] = "Ability scores adjusted at the table: " + "; ".join(
            f"{reasons.get(row['reason'], 'score change')} at cultivation level {row['cl']}" for row in table["abilities"]) + "."
    if table["insights"] or table["immortal_arts"]:
        from .table_growth import project
        project(out, table)
    # Build choices belong to their plug-in (combat/ext registry); each plug-in lays its own rows over the sheet.
    from .ext import build_choice
    for kind in build_kinds():
        if table[kind]:
            build_choice(kind).overlay(out, sheet, table[kind])
    out.setdefault("table_advancement", {})["applied"] = {"spheres": [row["id"] for row in table["spheres"]],
                                                         "talents": [row["id"] for row in table["talents"]],
                                                         "forged": [row["technique"].get("technique_id") for row in table["forged"]],
                                                         "manuals": [row.get("name") for row in table["manuals"]],
                                                         "abilities": [{"reason": row.get("reason"), "cl": row.get("cl")} for row in table["abilities"]],
                                                         "insights": [row["id"] for row in table["insights"]],
                                                         "immortal_arts": [row["art"]["art_id"] for row in table["immortal_arts"]]}
    if table["talents"]:
        # The CL each talent was added at, so the sheet's Abilities tab can badge table additions like
        # build ones (combat/tabletop.py sheet_library). Integers only, so it survives a table save/reload.
        out["table_advancement"]["talent_cls"] = {row["id"]: row.get("cl") for row in table["talents"] if row.get("id")}
    from .ext import transform
    out = transform("learning_projection", out, table)
    return out


def forge_request(sheet: dict[str, Any], design: dict[str, Any], talent_rows: Iterable[dict[str, Any]], *, project_id: str,
                  gm: bool = False, mechanics: dict[str, Any] | None = None) -> dict[str, Any]:
    """The Forge constructor's request for this character: its known Spheres and talents with their published source
    bindings (``talent_rows``: catalog records), and the owner's design. The GM override lifts the known-technique
    limit and lets a talent the character does not know supply an effect."""
    have = known(sheet)
    wanted = {design.get("primary_talent_id"), *(design.get("secondary_talent_ids") or [])}
    rows = []
    spheres: dict[str, str] = {}
    for record in talent_rows:  # canonical catalog talents (/api/catalog/canonical/talents)
        talent_id = record.get("canonical_talent_id")
        if talent_id not in have["talents"] and not (gm and talent_id in wanted):
            continue
        sphere_id = record.get("owning_canonical_sphere_id")
        source = record.get("source_reference") or {}
        if not sphere_id or not source.get("source_file_sha256") or not source.get("source_path"):
            continue
        spheres[sphere_id] = record.get("owning_canonical_sphere_name") or sphere_id.split(".")[-1].replace("_", " ").title()
        rows.append({"talent_id": talent_id, "sphere_id": sphere_id, "display_name": record.get("display_name") or talent_id,
                     "record_hash": str(record.get("record_commitment_sha256") or "")[:64],
                     "source": {"source_id": source.get("source_pack"), "path": source["source_path"], "anchor": source.get("source_anchor"),
                                "source_hash": source["source_file_sha256"]},
                     "published_text": str(record.get("full_description") or "")[:4000]})
    from character_creation.constructed_arts.sphere_effects import base_effect_rows
    from .factory_compiler import TYPED_AUTHORITY
    if mechanics is None:
        mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    printed = json.loads((TYPED_AUTHORITY.parent / "typed_mechanics" / "rules_text.json").read_bytes())
    bases = base_effect_rows(have["spheres"], mechanics, printed)
    rows.extend(bases)
    for row in bases:
        spheres.setdefault(row["sphere_id"], row["sphere_id"].split(".")[-1].replace("_", " ").title())
    return {"seed": f"table:{project_id}:{design.get('name') or ''}", "project_id": project_id, "cl": have["cl"], "pb": have["pb"],
            "path_id": have["path_id"] or "tianxia.path.qi_cultivation", "key_ability": have["key_ability"],
            "known_spheres": [{"sphere_id": key, "display_name": value} for key, value in sorted(spheres.items())],
            "known_talents": rows, "known_forged_technique_count": 0 if gm else len(have["forged"]),
            "concept": {"name": design.get("name"), "intent": design.get("intent"), "base_form": design.get("base_form"),
                        "primary_talent_id": design.get("primary_talent_id"),
                        "secondary_talent_ids": list(design.get("secondary_talent_ids") or []),
                        "augment_ids": list(design.get("augment_ids") or []), "drawback_ids": list(design.get("drawback_ids") or [])}}
