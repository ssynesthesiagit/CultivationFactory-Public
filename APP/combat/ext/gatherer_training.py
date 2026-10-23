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


def _source():
    text = json.loads((Path(__file__).resolve().parents[2] / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]
    if hashlib.sha256(text.encode()).hexdigest() != TEXT_SHA256:
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


def _already_held(sheet):
    """Which proficiencies the sheet already has: the listed ones plus any custom artisan's tool it records.

    This is the menu's hint; the save re-checks each name with _trained, which decides the bonus.
    """
    proficiency = sheet.get("proficiencies") or {}
    background = (sheet.get("background_origin") or {}).get("background") or {}
    recorded = [value for group in (proficiency.get("skills"), proficiency.get("tools"),
                                    background.get("skill_proficiencies"), background.get("tool_proficiencies"))
                for value in (group or []) if isinstance(value, str) and value.strip()]
    held, seen = [], set()
    for name in (*SKILLS, *TOOLS, *ARTISANS, *recorded):
        if _key(name) in seen:
            continue
        seen.add(_key(name))
        try:
            if _trained(sheet, name):
                held.append(name)
        except TabletopError:
            continue  # an ambiguous skill row is refused when the choice is saved
    return held


def _kit_menus(background_id, path_ids):
    """Closed kit choices per Path (background then Path menus), as the Grow form lists them.

    Option A is the default kit and always resolves; a choice with no pick uses its first
    option, so the form sends an explicit index for each menu it shows.
    """
    from app.core import FoundryError
    from factory_authoring.starting_kits import choice_menus

    if not background_id:
        return {}
    menus = {}
    for path_id in path_ids:
        try:
            menus[path_id] = choice_menus(background_id, path_id)
        except (FoundryError, KeyError):
            continue  # a Path without a starting kit offers no kit choices
    return menus


@hook("source_learning_options")
def learning_options(sheet, talents):
    from .. import table_advance

    background = (sheet.get("background_origin") or {}).get("background") or {}
    return {"source_id": SOURCE, "sphere_id": SPHERE, "name": "Training and Tools",
            "prompt": "Choose one proficiency when you learn Harvesting and Gathering. If you already have it, choose one eligible Mortal Realm bonus talent.",
            "proficiencies": [*SKILLS, *TOOLS, *ARTISANS],
            "already_proficient": _already_held(sheet),
            "other_artisan_tool": "The GM must name an appropriate artisan’s tool and explain why it is appropriate.",
            "bonus_talents": [{"id": row["canonical_talent_id"], "name": row["display_name"]}
                              for row in _bonus_options(sheet, talents)],
            "background_id": background.get("background_id") or "",
            "path_ids": list(table_advance.known(sheet)["paths"]),
            "kit_menus": _kit_menus(background.get("background_id") or "", list(table_advance.known(sheet)["paths"])),
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
    if any(row.get("starting_kit") for row in sheet.get("equipment") or []):
        _refuse("Starting equipment has already been assigned to this character.")
    background = (sheet.get("background_origin") or {}).get("background") or {}
    if assignment.get("background_id") != background.get("background_id") or not background.get("background_id"):
        _refuse("The equipment background must match this character’s recorded background.")
    if assignment.get("path_id") not in known(sheet)["paths"]:
        _refuse("The equipment class must match one of this character’s Paths.")
    try:
        kit = resolve_starting_kit(assignment["background_id"], assignment["path_id"],
                                  path_option=assignment.get("path_option", "option_a"),
                                  picks=assignment.get("picks"),
                                  seed=hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest())
    except FoundryError as exc:
        _refuse(exc.message)
    # One kit is printed. Its plural contents have no printed numerical count:
    # preserve them as collective descriptions inside that one inventory item.
    kit["items"].append({"item_id": KIT_ID, "name": "Basic gatherer’s kit", "quantity": 1,
                         "source": SOURCE, "source_reference": _source(), "contents": list(CONTENTS),
                         "printed": "A basic gatherer’s kit includes " + ", ".join(CONTENTS) + "."})
    return {"by": assignment["by"], "starting_kit": kit}


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
        name = name.strip()
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
    out = {"source": _source(), "proficiency": name, "already_proficient": int(already)}
    if ruling is not None:
        out["artisan_ruling"] = copy.deepcopy(ruling)
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
    if learning["source"] != _source():
        _refuse("The saved Training and Tools choice belongs to a different source version.")
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
    if assignment and not any(value.get("starting_kit") for value in out.get("equipment") or []):
        out.setdefault("equipment", []).append(copy.deepcopy(assignment))
    return out
