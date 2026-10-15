"""Source-bound training benefits on the table's native acquisition transaction.

Uses learning_choices/learning_receipt/learning_projection. Receipts capture the
pre-learning proficiency test once; replay projects grants, never re-tests it.
The sealed input sheet remains unchanged. No combat ownership is fabricated.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import hook
from .. import table_advance
from ..ability_checks import proficiency_rank
from ..tabletop import TabletopError

S = "tianxia.sphere."
ROWS = {
    S + "alchemy": "ALCHEMY_BASE_ALCHEMY_TRAINING",
    S + "jester": "JESTER_BASE_JESTER_TRAINING",
    S + "life": "LIFE_BASE_LIFE_INITIATION",
    S + "source": "SOURCE_BASE_SOURCE_TRAINING",
    S + "spear": "SPEAR_BASE_SPEAR_TRAINING",
}
SKILLS = ("Performance", "Deception", "Acrobatics")
SPEARS = ("spear", "pike", "lance", "trident")
TOOL = "alchemist's supplies"


def sequence(value):
    """Decode sheet list fields; shared with Life Initiation's Medicine compiler."""
    return json.loads(value) if isinstance(value, str) else value or []


def proficiencies(sheet):
    """Explicit ranks and printed grants, never guessed from a numeric bonus.

    Weapon grants use the same public rules as the compiler (Path classes and
    owned group grants), so a Martial Path counts before learning Spear.
    """
    from ..factory_compiler import weapon_group_proficient
    stats = sheet.get("ability_scores_and_statistics") or {}
    skills = {r["skill"] for r in sequence(stats.get("skills"))
              if isinstance(r, dict) and (proficiency_rank(r) or 0) >= 1}
    tools = set(sequence(stats.get("tool_proficiencies")))
    for row in (sheet.get("background_and_origin") or {}).values():
        if isinstance(row, dict):
            tools.update(row.get("tool_proficiencies") or [])
            tools.update(row.get("tool_expertise") or [])
            if row.get("selected_tool") and row.get("result") in ("proficiency", "proficient", "expertise"):
                tools.add(row["selected_tool"])
    tools = {str(t).replace("’", "'").casefold().removeprefix("the ") for t in tools}
    have = table_advance.known(sheet)
    # A public weapon-proficiency query is shared with native compilation.
    group = weapon_group_proficient(sheet, list(have["talents"]), "spear")
    explicit = set(sequence(stats.get("weapon_proficiencies")))
    return skills, tools, set(SPEARS) if group else explicit.intersection(SPEARS)


def talent_choices(sheet, sphere_id, talents, *, mortal=False, tag=None, prior=()):
    have = table_advance.known(sheet)
    have["spheres"].add(sphere_id)
    have["talents"].update(table_advance.base_ability_index().get(sphere_id, []))
    have["talents"].update(prior)
    result = []
    for row in talents:
        if (row.get("owning_canonical_sphere_id") != sphere_id
                or row.get("canonical_talent_id") in have["talents"]
                or row.get("background_only") or row.get("automatic_grant")
                or (mortal and row.get("realm_band") != "Mortal")
                or (tag and tag not in (row.get("tags") or []))):
            continue
        if table_advance.talent_status(row, have)["legal"]:
            result.append({"id": row["canonical_talent_id"], "name": row["display_name"]})
    return result


@hook("learning_choices")
def choices(sheet, sphere_id, talents, draft=None):
    if sphere_id not in ROWS:
        return None
    skills, tools, weapons = proficiencies(sheet)
    result = []
    prior = []
    def talent(key, label, **filters):
        options = talent_choices(sheet, sphere_id, talents, prior=prior, **filters)
        result.append({"id": key, "label": label, "options": options})
        selected = (draft or {}).get(key)
        if selected in {o["id"] for o in options}:
            prior.append(selected)
    # PHB, Training / Learning a New Sphere: the normal free first talent
    # is separate from a conditional already-proficient bonus. Source repeats
    # that normal benefit; Jester restricts its normal choice to a Punchline.
    if sphere_id not in (S + "jester", S + "source"):
        talent("free", "New Sphere: choose its normal free first talent")
    if sphere_id == S + "alchemy" and TOOL in tools:
        talent("bonus", "Alchemy Training: choose a bonus Mortal Realm Alchemy talent (free)", mortal=True)
    elif sphere_id == S + "spear" and set(SPEARS) <= weapons:
        talent("bonus", "Spear Training: choose a bonus Spear talent (free)")
    elif sphere_id == S + "jester":
        if set(SKILLS) <= skills:
            talent("bonus", "Jester Training: choose a bonus Jester talent (free)")
        else:
            result.append({"id": "skill", "label": "Jester Training: choose a skill proficiency",
                           "options": [{"id": n, "name": n} for n in SKILLS]})
        talent("punchline", "Jester Training: choose a Mortal Realm Punchline talent (free)", mortal=True, tag="Punchline")
    elif sphere_id == S + "source":
        talent("free", "Source Training: choose a Source talent (free)")
    return result


@hook("learning_receipt")
def receipt(sheet, kind, record_id, selected, talents):
    if kind != "sphere" or record_id not in ROWS:
        return None
    if record_id in table_advance.known(sheet)["spheres"]:
        raise TabletopError("LEARNING_ALREADY_KNOWN", "This Sphere is already known; training is granted only once.", 409)
    if record_id == S + "jester" and any(r.get("skill") in SKILLS and proficiency_rank(r) is None
            for r in sequence((sheet.get("ability_scores_and_statistics") or {}).get("skills"))):
        raise TabletopError("LEARNING_PROFICIENCY_UNKNOWN", "Jester Training needs the recorded proficiency ranks for Performance, Deception and Acrobatics; numeric bonuses alone are not evidence.", 422)
    offered = choices(sheet, record_id, talents, selected)
    keys = {r["id"] for r in offered}
    if not keys <= set(selected):
        raise TabletopError("LEARNING_CHOICES_REQUIRED", "Choose each training benefit before learning this Sphere.", 422)
    selected = {k: v for k, v in selected.items() if k in keys}
    for row in offered:
        if selected[row["id"]] not in {o["id"] for o in row["options"]}:
            raise TabletopError("LEARNING_CHOICE_INVALID", row["label"] + ": that choice is not eligible.", 422)
    learned = [value for key, value in selected.items() if key != "skill"]
    if len(learned) != len(set(learned)):
        raise TabletopError("LEARNING_DUPLICATE_TALENT", "Choose distinct talents for separate training benefits.", 422)
    rules = json.loads((Path(__file__).resolve().parents[2] / "authority/typed_mechanics/rules_text.json").read_text())
    return {"source": ROWS[record_id], "source_sha256": hashlib.sha256(rules[ROWS[record_id]].encode()).hexdigest(),
            "choices": dict(selected), "conditional_bonus_earned": int("bonus" in selected),
            "before_sheet_sha256": hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest(),
            "sphere_id": record_id, "talents": learned, "skills": [selected["skill"]] if "skill" in selected else [],
            "tools": [TOOL] if record_id == S + "alchemy" else [],
            "weapons": list(SPEARS) if record_id == S + "spear" else [], "slot_cost": 0}


@hook("advancement_options")
def receipt_labels(options, sheet, talents):
    """Expose persisted learning benefits by printed names in the owner's Grow sheet."""
    if not any(ROWS.get(s["id"]) == r.get("source")
               for s in options["added"]["spheres"] for r in s.get("learning_receipts", [])):
        return options
    names = {r["canonical_talent_id"]: r["display_name"] for r in talents}
    out = copy.deepcopy(options)
    for sphere in out["added"]["spheres"]:
        labels = []
        for row in sphere.get("learning_receipts", []):
            if ROWS.get(sphere["id"]) != row.get("source"):
                continue
            labels.extend("Proficiency in " + n for n in row["skills"])
            labels.extend("Proficiency with " + n for n in row["tools"])
            if row["weapons"]:
                labels.append("Proficiency with spears, pikes, lances and tridents")
            for route, tid in row.get("choices", {}).items():
                if route != "skill":
                    labels.append(names.get(tid, "Previously learned talent") + (" (bonus talent, free)" if route == "bonus" else " (first talent, free)"))
        if labels:
            sphere["learning_benefit_labels"] = labels
    return out


@hook("learning_projection")
def project(sheet, advancement):
    receipts = [r for acquisition in advancement["spheres"] for r in acquisition.get("learning_receipts", [])
                if r.get("sphere_id") == acquisition.get("id") and ROWS.get(acquisition.get("id")) == r.get("source")]
    if not receipts:
        return sheet
    out = copy.deepcopy(sheet)
    block = out.setdefault("spheres_and_talents", {})
    learned = block.setdefault("learned_talent_record_ids", [])
    stats = out["ability_scores_and_statistics"]
    skills = sequence(stats.get("skills"))
    mods = {r["ability"]: int(r["modifier"]) for r in sequence(stats.get("abilities"))}
    pb = int(out["identity"]["proficiency_bonus"])
    for row in receipts:
        learned.extend(t for t in row["talents"] if t not in learned)
        for name in row["skills"]:
            existing = next((r for r in skills if r.get("skill") == name), None)
            if existing and (proficiency_rank(existing) or 0) >= 1:
                continue
            ability = "DEX" if name == "Acrobatics" else "CHA"
            bonus = int((existing or {}).get("bonus", mods.get(ability, 0))) + pb
            if existing:
                skills.remove(existing)
            skills.append({"skill": name, "bonus": bonus, "proficiency": "proficient", "proficiency_multiplier": 1})
        for key, values in (("tool_proficiencies", row["tools"]), ("weapon_proficiencies", row["weapons"])):
            target = sequence(stats.get(key))
            normalize = lambda s: str(s).replace("’", "'").casefold().removeprefix("the ")
            target.extend(value for value in values if normalize(value) not in {normalize(v) for v in target})
            stats[key] = target
    stats["skills"] = skills
    out["learning_receipts"] = copy.deepcopy(receipts)
    return out
