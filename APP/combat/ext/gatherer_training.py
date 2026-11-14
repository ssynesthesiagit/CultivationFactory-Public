"""Training and Tools source adapter for the public table acquisition contract.

Only this record's proficiency, conditional bonus talent and starting kit live
here. No Clean Harvest, Lots or other training record behavior is changed.
The existing trusted local GM input adjudicates an artisan tool's suitability;
the decision is bound to that tool and saved privately with the sphere row.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import hook
from ..tabletop import TabletopError

SOURCE = "HARVESTING_GATHERING_BASE_TRAINING_AND_TOOLS"
SPHERE = "tianxia.sphere.harvesting_gathering"
TEXT_SHA256 = "b15e67d14069042cfe5a276087fb60272bb4f60572e71d5a54c13bbf08d79c23"
KIT_ID = "tianxia.source.harvesting_gathering.basic_gatherer_kit"
CONTENTS = ("small sickle", "pruning knife", "digging hook", "cord", "waxed paper",
            "cloth wraps", "small jars", "simple gloves", "field ledger")
SKILLS = {"Nature": "INT", "Survival": "WIS", "Medicine": "WIS"}
TOOLS = ("Herbalism Kit", "Land Vehicles")
ARTISANS = ("Woodcarver’s Tools", "Mason’s Tools", "Cartographer’s Tools")


def _refuse(message):
    raise TabletopError("TABLETOP_TRAINING_CHOICE_INVALID", message, 409)


def _key(name):
    return str(name).replace("’", "'").casefold().strip()


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _text_matches():
    text = json.loads((Path(__file__).resolve().parents[2] / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]
    return hashlib.sha256(text.encode()).hexdigest() == TEXT_SHA256


def _source():
    if not _text_matches():
        _refuse("Training and Tools has changed; review its learning choices before continuing.")
    return {"record_id": SOURCE, "text_sha256": TEXT_SHA256}


def _trained(sheet, name):
    proficiency = sheet.get("proficiencies") or {}
    background = (sheet.get("background_origin") or {}).get("background") or {}
    values = [*proficiency.get("skills", []), *proficiency.get("tools", []),
              *background.get("skill_proficiencies", []), *background.get("tool_proficiencies", [])]
    if any(_key(value) == _key(name) for value in values):
        return True
    for row in _json((sheet.get("ability_scores_and_statistics") or {}).get("skills")) or []:
        if _key(row.get("skill")) == _key(name):
            from ..ability_checks import proficiency_rank

            rank = proficiency_rank(row)
            if rank is not None:
                return rank > 0
            if row.get("proficient") is True:
                return True
            _refuse(f"Record whether {name} is already proficient before choosing it; its total alone does not say.")
    return False


def _bonus_options(sheet, talents):
    from .. import table_advance

    have = table_advance.known(sheet)
    have["spheres"].add(SPHERE)
    return [row for row in talents
            if row.get("owning_canonical_sphere_id") == SPHERE
            and row.get("section_realm", row.get("realm_band")) == "Mortal"
            and not row.get("background_only") and not row.get("automatic_grant")
            and row.get("canonical_talent_id") not in have["talents"]
            and table_advance.talent_status(row, have)["legal"]]


def _recorded(sheet):
    proficiency = sheet.get("proficiencies") or {}
    background = (sheet.get("background_origin") or {}).get("background") or {}
    names = [value for group in (proficiency.get("skills"), proficiency.get("tools"),
                                 background.get("skill_proficiencies"), background.get("tool_proficiencies"))
             for value in (group or []) if isinstance(value, str) and value.strip()]
    # A skill row can record a held tool that no list names; _trained reads those rows, so the menu must name them too.
    skills = _json((sheet.get("ability_scores_and_statistics") or {}).get("skills")) or []
    names += [row["skill"] for row in skills if isinstance(row, dict) and isinstance(row.get("skill"), str)
              and row["skill"].strip()]
    return names


def _aliases(sheet):
    """Every spelling the form may send for a proficiency, mapped to its canonical name.

    The browser looks names up here instead of comparing them itself, so case and apostrophe rules live in one place.
    """
    out = {}
    for name in (*SKILLS, *TOOLS, *ARTISANS, *_recorded(sheet)):
        # Keyed by _key, the same rule _trained uses, so any spelling or case the browser sends maps to one name.
        out.setdefault(_key(name), name)
    return out


def _already_held(sheet):
    """Which proficiencies the sheet already has: the listed ones plus any custom artisan's tool it records.

    This is the menu's hint; the save re-checks each name with _trained, which decides the bonus.
    """
    held, seen = [], set()
    for name in (*SKILLS, *TOOLS, *ARTISANS, *_recorded(sheet)):
        if _key(name) in seen:
            continue
        seen.add(_key(name))
        try:
            if _trained(sheet, name):
                held.append(name)
        except TabletopError:
            continue  # an ambiguous skill row is refused when the choice is saved
    return held


def _unresolved(sheet):
    """Proficiencies whose skill row does not record whether the character has them.

    The save refuses these (_trained), so the Grow form must not offer Learn for them until the sheet is fixed.
    """
    out = []
    for name in (*SKILLS, *TOOLS, *ARTISANS):
        try:
            _trained(sheet, name)
        except TabletopError:
            out.append(name)
    return out


def _kit_menus(background_id, path_ids):
    """Closed kit choices per Path and per Path kit option (option_a printed kit, option_b coin), as Grow lists them.

    A choice with no pick uses its first option, so the form sends an explicit index for each menu it shows.
    """
    from app.core import FoundryError
    from factory_authoring.starting_kits import PATH_OPTIONS, choice_menus

    if not background_id:
        return {}
    menus = {}
    for path_id in path_ids:
        for option in PATH_OPTIONS:
            try:
                menus.setdefault(path_id, {})[option] = choice_menus(background_id, path_id, option)
            except (FoundryError, KeyError):
                continue  # a Path without that kit option offers no kit choices
    return menus


@hook("source_learning_options")
def learning_options(sheet, talents):
    from .. import table_advance

    background = (sheet.get("background_origin") or {}).get("background") or {}
    kit_menus = _kit_menus(background.get("background_id") or "", list(table_advance.known(sheet)["paths"]))
    return {"source_id": SOURCE, "sphere_id": SPHERE, "name": "Training and Tools",
            "prompt": "Choose one proficiency when you learn Harvesting and Gathering. If you already have it, choose one eligible Mortal Realm bonus talent.",
            "proficiencies": [*SKILLS, *TOOLS, *ARTISANS],
            "standard_proficiencies": [*SKILLS, *TOOLS],
            "proficiency_aliases": _aliases(sheet),
            "kit_contents": list(CONTENTS),
            "already_proficient": _already_held(sheet),
            "unresolved_proficiencies": _unresolved(sheet),
            "other_artisan_tool": "The GM must name an appropriate artisan’s tool and explain why it is appropriate.",
            "bonus_talents": [{"id": row["canonical_talent_id"], "name": row["display_name"]}
                              for row in _bonus_options(sheet, talents)],
            "background_id": background.get("background_id") or "",
            "path_ids": list(table_advance.known(sheet)["paths"]),
            "kit_menus": kit_menus,
            "equipment_assigned": any(isinstance(row, dict) and bool(row.get("starting_kit")) for row in sheet.get("equipment") or []),
            "path_options": sorted({option for menus in kit_menus.values() for option in menus}),
            "equipment": "A basic gatherer’s kit is included only when class or background starting equipment is assigned."}


def _assignment(sheet, assignment):
    """Assign actual printed equipment, never accept an 'equipment approved' flag."""
    from app.core import FoundryError
    from factory_authoring.starting_kits import resolve_starting_kit
    from ..table_advance import known

    if not isinstance(assignment, dict) or set(assignment) - {"by", "background_id", "path_id", "path_option", "picks"}:
        _refuse("Provide the class or background equipment assignment, not an approval flag.")
    if assignment.get("by") not in {"class", "background"}:
        _refuse("Starting equipment must be assigned by class or background.")
    background = (sheet.get("background_origin") or {}).get("background") or {}
    if assignment.get("background_id") != background.get("background_id") or not background.get("background_id"):
        _refuse("The equipment background must match this character’s recorded background.")
    if assignment.get("path_id") not in known(sheet)["paths"]:
        _refuse("The equipment class must match one of this character’s Paths.")
    existing = next((row for row in sheet.get("equipment") or [] if isinstance(row, dict) and row.get("starting_kit")), None)
    if existing is not None:
        # The class or background kit is already on the sheet: the printed gatherer's kit is added to that same kit,
        # once, without re-resolving it. The kit items are never rebuilt from the picks.
        if any(row.get("item_id") == KIT_ID for row in existing["starting_kit"].get("items") or []):
            _refuse("The basic gatherer’s kit is already in this character’s starting equipment.")
        return {"by": assignment["by"], "kit_item": _kit_item()}
    try:
        kit = resolve_starting_kit(assignment["background_id"], assignment["path_id"],
                                  path_option=assignment.get("path_option", "option_a"),
                                  picks=assignment.get("picks"),
                                  seed=hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest())
    except FoundryError as exc:
        _refuse(exc.message)
    # One kit is printed. Its plural contents have no printed numerical count:
    # preserve them as collective descriptions inside that one inventory item.
    kit["items"].append(_kit_item())
    return {"by": assignment["by"], "starting_kit": kit}


def _kit_item():
    return {"item_id": KIT_ID, "name": "Basic gatherer’s kit", "quantity": 1,
            "source": SOURCE, "source_reference": _source(), "contents": list(CONTENTS),
            "printed": "A basic gatherer’s kit includes " + ", ".join(CONTENTS) + "."}


_LEARNING_KEYS = frozenset({"proficiency", "artisan_ruling", "bonus_talent_id", "equipment_assignment"})


@hook("prepare_source_learning")
def prepare_learning(sheet, sphere_id, choice, talents, gm):
    if sphere_id != SPHERE:
        return None
    # Only the actual learning moment establishes "already proficient".
    # An installed Sphere without a historical choice cannot use proficiency
    # acquired later to manufacture a retroactive bonus talent or free kit.
    if SPHERE in (sheet.get("spheres_and_talents") or {}).get("sphere_record_ids", []):
        _refuse("Training and Tools must be chosen when the Sphere is learned; it cannot be granted again later.")
    # Learning this Sphere grants its proficiency, so a plain Learn must not silently
    # skip the choice: it could never be made later (the retroactive refusal above).
    if not isinstance(choice, dict):
        _refuse("Training and Tools needs a proficiency choice when Harvesting and Gathering is learned.")
    unknown = set(choice) - _LEARNING_KEYS
    if unknown:
        _refuse("Training and Tools has no choice named " + ", ".join(sorted(unknown)) + ".")
    if "proficiency" not in choice:
        _refuse("Training and Tools needs a proficiency choice when Harvesting and Gathering is learned.")
    name = choice.get("proficiency")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        _refuse("Choose one proficiency for Training and Tools.")
    standard = next((value for value in (*SKILLS, *TOOLS) if _key(value) == _key(name)), None)
    ruling = choice.get("artisan_ruling")
    if standard is None:
        if not gm or not isinstance(ruling, dict) or set(ruling) != {"tool", "reason"}:
            _refuse("The GM must name the appropriate artisan’s tool and explain its use for gathering.")
        if ruling["tool"] != name or not isinstance(ruling["reason"], str) or not 1 <= len(ruling["reason"].strip()) <= 1000:
            _refuse("The GM’s suitability decision must name this exact artisan’s tool and give a reason.")
        # Store the spelling the sheet already holds (or the trimmed text), so "weaver's tools" saves as "Weaver’s Tools".
        name = _aliases(sheet).get(_key(name), name.strip())
    else:
        name = standard
        if ruling is not None:
            _refuse("A GM artisan-tool ruling applies only to the selected artisan’s tool.")
    already = _trained(sheet, name)
    bonus = choice.get("bonus_talent_id")
    if already:
        if not isinstance(bonus, str) or bonus not in {row["canonical_talent_id"] for row in _bonus_options(sheet, talents)}:
            _refuse("Choose exactly one unlearned Mortal Realm Harvesting and Gathering talent whose prerequisites you meet.")
    elif bonus is not None:
        _refuse("A bonus talent is granted only if you already have the chosen proficiency.")
    # An assigned sheet already holds its class or background kit. The gatherer's kit can only be added by this Learn,
    # and the Sphere can never be learned twice, so a Learn without an equipment choice would drop the kit for good.
    assigned = any(isinstance(row, dict) and row.get("starting_kit") for row in sheet.get("equipment") or [])
    if assigned and "equipment_assignment" not in choice:
        _refuse("Choose the class or background starting equipment so the basic gatherer’s kit is added; it cannot be added later.")
    out = {"source": _source(), "proficiency": name, "already_proficient": int(already)}
    if ruling is not None:
        out["artisan_ruling"] = {"tool": name, "reason": ruling["reason"]}
    if bonus is not None:
        out["bonus_talent_id"] = bonus
    if "equipment_assignment" in choice:
        out["equipment_assignment"] = _assignment(sheet, choice["equipment_assignment"])
    return out


@hook("project_source_learning")
def project_learning(sheet, row):
    learning = row.get("learning") or {}
    if row.get("id") != SPHERE or (learning.get("source") or {}).get("record_id") != SOURCE:
        return None
    # A saved choice whose printed text no longer matches this build is read-only: it is not projected onto the
    # sheet, so the sheet still loads, and the saved row stays for the owner to delete. New saves are refused (_source).
    if learning["source"] != {"record_id": SOURCE, "text_sha256": TEXT_SHA256} or not _text_matches():
        return copy.deepcopy(sheet)
    out = copy.deepcopy(sheet)
    name = learning["proficiency"]
    out.setdefault("spheres_and_talents", {})
    if not learning["already_proficient"]:
        profs = out.setdefault("proficiencies", {})
        group = "skills" if name in SKILLS else "tools"
        values = profs.setdefault(group, [])
        if not any(_key(value) == _key(name) for value in values):
            values.append(name)
        if name in SKILLS:
            stats = out.setdefault("ability_scores_and_statistics", {})
            rows = _json(stats.get("skills")) or []
            stats["skills"] = rows
            old = next((value for value in rows if _key(value.get("skill")) == _key(name)), None)
            ability = SKILLS[name]
            modifier = next((int(value["modifier"]) for value in _json(stats.get("abilities")) or [] if value.get("ability") == ability), 0)
            if old is None:
                old = {"skill": name, "ability": ability, "bonus": modifier}
                rows.append(old)
            if not (old.get("proficient") is True or old.get("proficiency_multiplier", 0) > 0 or old.get("proficiency") in {"proficient", "expertise"}):
                old.update(bonus=int(old.get("bonus", modifier)) + int(out["identity"]["proficiency_bonus"]),
                           proficient=True, proficiency="proficient", proficiency_multiplier=1)
    bonus = learning.get("bonus_talent_id")
    learned = out["spheres_and_talents"].setdefault("learned_talent_record_ids", [])
    if bonus and bonus not in learned:
        learned.append(bonus)
    assignment = learning.get("equipment_assignment")
    if assignment:
        kit = next((value["starting_kit"] for value in out.get("equipment") or []
                    if isinstance(value, dict) and value.get("starting_kit")), None)
        if "kit_item" in assignment:
            # Added to the kit already on the sheet; a second projection finds the item and adds nothing.
            items = kit.setdefault("items", []) if kit is not None else None
            if items is not None and not any(row.get("item_id") == KIT_ID for row in items):
                items.append(copy.deepcopy(assignment["kit_item"]))
        elif kit is None:
            out.setdefault("equipment", []).append(copy.deepcopy(assignment))
    return out
