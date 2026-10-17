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
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable

SCHEMA = "TianxiaTableAdvancement.v1"
_REALMS = (("Mortal", 1), ("Foundation", 5), ("Core Formation", 10), ("Nascent Soul", 15), ("Immortal", 20))


ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
REASONS = ("gm_respec", "level_increase")
# Starting point-buy (character_builder/service.py validate_point_buy): scores 8-15 for 27 points.
POINT_BUY_BUDGET = 27
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
# Level increase (stage2/service.py ability_score_change; C1A typed authority ability_change): CL, budget, deltas, cap.
LEVEL_INCREASE = {"allowed_cls": (4,), "budget": 2, "deltas": (1, 2), "cap": 20}


def empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "spheres": [], "talents": [], "forged": [], "manuals": [], "abilities": []}


def normalized(document: Any) -> dict[str, Any]:
    out = empty()
    if isinstance(document, dict):
        for key in ("spheres", "talents", "forged", "manuals"):
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
            "note": str(row.get("note") or "")[:240], "gm": bool(row.get("gm")), "at": str(row.get("at") or "")}


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


def ability_status(entry: dict[str, Any], sheet: dict[str, Any]) -> dict[str, Any]:
    """{"legal", "gm", "reasons"} for one ability entry against the character as it stands now."""
    reasons: list[str] = []
    changes = entry.get("changes") or {}
    scores = current_scores(sheet)
    cl = int((sheet.get("identity") or {}).get("cultivation_level") or 1)
    if not changes or any(value is None for value in changes.values()):
        return {"legal": False, "gm": False, "reasons": ["every changed ability needs a whole-number score"]}
    if entry.get("reason") == "gm_respec":
        if set(changes) != set(ABILITIES):
            reasons.append("a respec sets all six scores")
        elif any(value not in POINT_BUY_COST for value in changes.values()):
            reasons.append("point-buy scores are 8 through 15")
        else:
            spent = sum(POINT_BUY_COST[value] for value in changes.values())
            if spent != POINT_BUY_BUDGET:
                reasons.append(f"point-buy spends {spent} of {POINT_BUY_BUDGET} points")
    elif entry.get("reason") == "level_increase":
        at = int(entry.get("cl") or 0)
        if at not in LEVEL_INCREASE["allowed_cls"]:
            reasons.append("an ability increase is taken at CL " + ", ".join(str(c) for c in LEVEL_INCREASE["allowed_cls"]))
        elif at != cl:
            reasons.append(f"the ability increase must be recorded at CL {at}; the character is currently CL {cl}")
        if len(scores) != len(ABILITIES):
            reasons.append("the character's ability scores are not established")
        spent = sum(changes.values())
        if spent != LEVEL_INCREASE["budget"] or any(value not in LEVEL_INCREASE["deltas"] for value in changes.values()):
            reasons.append(f"an ability increase spends exactly {LEVEL_INCREASE['budget']} points, +1 or +2 each")
        elif any(scores.get(a, 0) + v > LEVEL_INCREASE["cap"] for a, v in changes.items()):
            reasons.append(f"a score cannot pass {LEVEL_INCREASE['cap']}")
    else:
        reasons.append("choose a respec or a level increase")
    return {"legal": not reasons, "gm": False, "reasons": reasons}


def _trace_delta(node: Any, delta: dict[str, int]) -> int:
    """How much a SafeFormulaTrace node moves when each ability modifier moves by delta (stage2/formulas.py ops): an
    ability_modifier leaf moves by its ability's change, an add sums its terms, a constant does not move."""
    if not isinstance(node, dict):
        return 0
    if node.get("op") == "ability_modifier":
        return int(delta.get(node.get("ability"), 0))
    if node.get("op") == "add":
        return sum(_trace_delta(term, delta) for term in node.get("terms") or [])
    return 0


def _bump(obj: Any, field: str, delta: int) -> None:
    """Move a stored total by delta; a formula trace that states it moves with it."""
    if not delta or not isinstance(obj, dict) or not isinstance(obj.get(field), int) or isinstance(obj.get(field), bool):
        return
    obj[field] += delta
    trace = obj.get("formula_trace")
    if isinstance(trace, dict) and isinstance(trace.get("root"), dict) and isinstance(trace["root"].get("value"), int):
        trace["root"]["value"] += delta


def recompute_from_abilities(sheet: dict[str, Any], old_scores: dict[str, int], new_scores: dict[str, int]) -> dict[str, Any]:
    """The sheet with every score-derived number moved from old_scores to new_scores. Each stored total moves by the change
    in the modifier it uses: initiative, skills and saving throws by their ability; the technique attack bonus and save DC
    by the key ability; armor class by DEX when its calculation names Dexterity; hit point maximum by the CON modifier
    change times CL (and current HP too when it was at maximum). The input sheet is not changed."""
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
    if not any(delta.values()):
        return out
    key = str((out.get("identity") or {}).get("key_ability") or "").upper()
    _bump(block.get("initiative"), "bonus", delta.get((block.get("initiative") or {}).get("ability"), 0))
    armor = block.get("armor_class")
    if isinstance(armor, dict):
        # Armor class: its SafeFormulaTrace root moves by the ability terms it names (DEX unarmored, or a Path's CON + PB).
        trace_root = (armor.get("formula_trace") or {}).get("root") if isinstance(armor.get("formula_trace"), dict) else None
        moved = _trace_delta(trace_root, delta)
        for field in ("value", "base_value"):
            if moved and isinstance(armor.get(field), int):
                armor[field] += moved
        if moved and isinstance(trace_root, dict) and isinstance(trace_root.get("value"), int):
            trace_root["value"] += moved
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
    saves = block.get("saving_throws")
    if isinstance(saves, dict):
        for ability in delta:
            if isinstance(saves.get(ability), int):
                saves[ability] += delta[ability]
    elif isinstance(saves, list):
        for row in saves:
            if isinstance(row, dict):
                _bump(row, "bonus", delta.get(row.get("ability"), 0))
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
    return {"cl": int(identity.get("cultivation_level") or 1), "pb": int(identity.get("proficiency_bonus") or 2),
            "key_ability": str(identity.get("key_ability") or "CON").upper(), "paths": paths,
            "path_id": paths_block.get("path_record_id") or (paths[0] if paths else None),
            "spheres": set(block.get("sphere_record_ids") or []), "talents": talents,
            "forged": [row for row in sheet.get("forged_techniques") or [] if isinstance(row, dict)]}


def realm_of(cl: int) -> str:
    return [name for name, least in _REALMS if cl >= least][-1]


def _holds(constraint: dict[str, Any], have: dict[str, Any]) -> bool | None:
    """True/False for what the rules can judge; None for what only the GM can."""
    kind = constraint.get("kind")
    if kind == "minimum_cl":
        return have["cl"] >= int(constraint.get("value") or 0)
    if kind in ("owning_sphere", "sphere"):
        return constraint.get("target_id") in have["spheres"]
    if kind == "talent":
        return constraint.get("target_id") in have["talents"]
    if kind == "path":
        return constraint.get("target_id") in have["paths"]
    if kind == "realm":
        want = str(constraint.get("value") or constraint.get("target_id") or "")
        order = [name.lower() for name, _ in _REALMS]
        mine = order.index(realm_of(have["cl"]).lower())
        return next((mine >= index for index, name in enumerate(order) if name in want.lower().replace("_", " ")), None)
    return None


def talent_status(record: dict[str, Any], have: dict[str, Any]) -> dict[str, Any]:
    """{"legal": bool, "gm": bool, "reasons": [...]} for learning one catalog talent now."""
    constraints = [row for row in record.get("typed_constraints") or [] if isinstance(row, dict) and row.get("scope", "acquisition") == "acquisition"]
    reasons: list[str] = []
    gm = False
    names = {row.get("target_id"): row.get("display_name") or row.get("raw_text") for row in constraints}

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
        held = _holds(row, have)
        if held is None:
            gm = True
            reasons.append(f"GM: {describe(row)}")
        elif not held:
            reasons.append(describe(row))
    for clause in record.get("prerequisite_clauses") or []:
        if not isinstance(clause, dict) or clause.get("scope", "acquisition") != "acquisition":
            continue
        verdicts = []
        for alternative in clause.get("alternatives") or []:
            rows = [row for row in constraints if row.get("alternative_id") == alternative.get("alternative_id")]
            held = [_holds(row, have) for row in rows]
            verdicts.append(None if None in held and False not in held else all(held) if rows else None)
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

    if sphere_id in have["spheres"]:
        return {"legal": False, "gm": False, "reasons": ["already known"]}
    entry = path_access.access().get(sphere_id)
    if entry is None:
        return {"legal": False, "gm": True, "reasons": ["GM: this Sphere's Path access is not recorded"]}
    if not path_access.can_learn(sphere_id, have["paths"]):
        return {"legal": False, "gm": False, "reasons": [f"not open to {', '.join(path.split('.')[-1].replace('_', ' ').title() for path in have['paths']) or 'these Paths'}"]}
    return {"legal": True, "gm": False, "reasons": []}


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


def apply(sheet: dict[str, Any], document: Any, mechanics: dict[str, Any] | None = None) -> dict[str, Any]:
    """The sheet with the table's additions: learned Spheres (and their base abilities), learned talents and Forged
    Techniques. The input sheet is not changed."""
    table = normalized(document)
    if not (table["spheres"] or table["talents"] or table["forged"] or table["manuals"] or table["abilities"]):
        return sheet
    out = copy.deepcopy(sheet)
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
    out["forged_techniques"] = [*(out.get("forged_techniques") or []), *[row["technique"] for row in table["forged"] if isinstance(row.get("technique"), dict)]]
    # Manuals the table gave (owner 2026-09-27: "add cleaarsight to tabik damu, put it on a manual with a few other
    # things"): listed with the character's training sources; their talents are then known (memorized, below).
    out["training_sources"] = [*(out.get("training_sources") or []), *[manual_source(row) for row in table["manuals"]]]
    # Ability entries apply in the order they were made; each recomputes from the scores the entry before it left.
    for entry in table["abilities"]:
        scores = current_scores(out)
        changes = entry.get("changes") or {}
        if len(scores) != len(ABILITIES) or not changes or any(value is None for value in changes.values()):
            continue
        if entry.get("reason") == "gm_respec":
            if set(changes) != set(ABILITIES):
                continue
            new = {a: int(changes[a]) for a in ABILITIES}
        else:
            new = {a: scores[a] + int(changes.get(a, 0)) for a in ABILITIES}
        out = recompute_from_abilities(out, scores, new)
    out.setdefault("table_advancement", {})["applied"] = {"spheres": [row["id"] for row in table["spheres"]],
                                                         "talents": [row["id"] for row in table["talents"]],
                                                         "forged": [row["technique"].get("technique_id") for row in table["forged"]],
                                                         "manuals": [row.get("name") for row in table["manuals"]],
                                                         "abilities": [{"reason": row.get("reason"), "cl": row.get("cl")} for row in table["abilities"]]}
    return out


def forge_request(sheet: dict[str, Any], design: dict[str, Any], talent_rows: Iterable[dict[str, Any]], *, project_id: str,
                  gm: bool = False) -> dict[str, Any]:
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
    return {"seed": f"table:{project_id}:{design.get('name') or ''}", "project_id": project_id, "cl": have["cl"], "pb": have["pb"],
            "path_id": have["path_id"] or "tianxia.path.qi_cultivation", "key_ability": have["key_ability"],
            "known_spheres": [{"sphere_id": key, "display_name": value} for key, value in sorted(spheres.items())],
            "known_talents": rows, "known_forged_technique_count": 0 if gm else len(have["forged"]),
            "concept": {"name": design.get("name"), "intent": design.get("intent"), "base_form": design.get("base_form"),
                        "primary_talent_id": design.get("primary_talent_id"),
                        "secondary_talent_ids": list(design.get("secondary_talent_ids") or []),
                        "augment_ids": list(design.get("augment_ids") or []), "drawback_ids": list(design.get("drawback_ids") or [])}}
