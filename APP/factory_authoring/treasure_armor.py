"""Treasure armour built by Item Book R1 Chapter 3.

Order (Chapter 3A): armour or shield profile -> Primary Material -> finished
grade (Refinement Bonus to AC, enhancement capacity) -> enhancements -> final
entry.  The server sets the finished grade from what the treasure budget leaves
after the signature weapon; only one treasure may sit at the Realm's signature
grade (draft §4), so armour stays below it when the weapon already holds it.
The profile must be one the character's Path equips: armour no heavier than
the Path kit's printed armour, and a shield only where the Path kit prints one.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core import FoundryError

APP_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = "authority/Tianxia_Treasure_Armor_Authority_R1.json"
AUTHORITY_SHA256 = "6e6d9bf65fa8d7906e1ac72c4289ea608fe1cabc64b9d234a62cb2ee04875d0c"
# Share of what the weapon leaves that the armour may take.
ARMOR_BUDGET_SHARE = 0.6
CATEGORY_ORDER = ("light", "medium", "heavy")
# See treasure_weapons.CAPACITY_RULES_CURRENT: rules 2 adds Heaven-Mark Violet
# Gold's "+1 enchantment capacity"; records keep their built version.
MATERIAL_CAPACITY_BONUS = {"tianxia.treasure.armor_material.heaven_mark_violet_gold": 1}


def material_capacity_bonus(material_id: str, capacity_rules: int) -> int:
    return MATERIAL_CAPACITY_BONUS.get(material_id, 0) if capacity_rules >= 2 else 0


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("TREASURE_ARMOR_INVALID", message, details=details or None)


@lru_cache(maxsize=1)
def authority() -> dict[str, Any]:
    path = APP_ROOT / AUTHORITY_PATH
    if path.is_symlink() or not path.is_file():
        raise _invalid("The treasure-armour authority file is missing.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != AUTHORITY_SHA256:
        raise _invalid("The treasure-armour authority does not match its pin.")
    return json.loads(data.decode("utf-8"))


def _by_id(kind: str, key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in authority()[kind]}


def _matches(chassis: Mapping[str, Any], predicates: Sequence[str]) -> bool:
    category = chassis["armor_category"]
    tags = set(chassis["construction_tags"])
    for predicate in predicates:
        if predicate == "shield" and category == "shield":
            return True
        if predicate == "stealth" and category != "shield" and chassis.get("stealth") == "Disadvantage":
            return True
        kind, _, values = predicate.partition(":")
        if kind == "cat" and category in values.split("|"):
            return True
        if kind == "tag" and tags & set(values.split("|")):
            return True
    return False


def armor_grade(target_cl: int, background_id: str) -> dict[str, Any] | None:
    """The finished grade for this character's armour, or None when nothing is affordable."""
    from factory_authoring.treasure_weapons import weapon_grade

    weapon = weapon_grade(target_cl, background_id)
    if weapon is None:
        return None
    data = authority()
    order = data["grade_order"]
    allowed = order[: order.index(weapon["realm_cap"]) + 1]
    if weapon["grade"] == weapon["realm_cap"]:
        allowed = allowed[:-1]
    remaining = weapon["budget_gt"] - weapon["appraisal_gt"]
    affordable = [grade for grade in allowed if data["grades"][grade]["appraisal_gt"] <= remaining * ARMOR_BUDGET_SHARE]
    if not affordable:
        return None
    grade = affordable[-1]
    return {"grade": grade, "realm_cap": weapon["realm_cap"], "budget_gt": weapon["budget_gt"],
            "weapon_value_gt": weapon["appraisal_gt"], **data["grades"][grade]}


def chassis_options(path_id: str) -> list[dict[str, Any]]:
    """Profiles the Path equips: no heavier than its kit armour; the Shield only if its kit prints one."""
    from factory_authoring.starting_kits import path_kit_item_ids

    printed = path_kit_item_ids(path_id)
    rows = authority()["chassis"]
    printed_categories = [row["armor_category"] for row in rows if row["item_id"] in printed and row["armor_category"] in CATEGORY_ORDER]
    heaviest = max((CATEGORY_ORDER.index(category) for category in printed_categories), default=-1)
    has_shield = any(row["item_id"] in printed and row["armor_category"] == "shield" for row in rows)
    return [
        row for row in rows
        if (row["armor_category"] == "shield" and has_shield)
        or (row["armor_category"] in CATEGORY_ORDER and CATEGORY_ORDER.index(row["armor_category"]) <= heaviest)
    ]


def material_options(grade: str, chassis_id: str) -> list[dict[str, Any]]:
    """Materials whose ceiling supports the grade and that the profile can physically hold (Chapter 3B)."""
    chassis = _by_id("chassis", "item_id")[chassis_id]
    order = authority()["grade_order"] + ["Immortal", "Bespoke"]
    return [
        row for row in authority()["materials"]
        if order.index(row["normal_ceiling"]) >= order.index(grade) and _matches(chassis, row["compatibility"])
    ]


def _opposed(material: Mapping[str, Any], enhancement: Mapping[str, Any]) -> bool:
    words = " ".join([enhancement["name"], enhancement.get("family", ""), *enhancement.get("sphere_influences", [])])
    return any(re.search(rf"\b{re.escape(keyword)}\b", words, re.I) for keyword in material.get("opposed_keywords", []))


def enhancement_options(
    chassis_id: str, material_id: str, grade: str, chosen_ids: Sequence[str], capacity_rules: int = 2,
) -> list[dict[str, Any]]:
    """Enhancements still legal for this armour and within its remaining capacity (Chapter 3C)."""
    data = authority()
    chassis = _by_id("chassis", "item_id")[chassis_id]
    material = _by_id("materials", "material_id")[material_id]
    enhancements = _by_id("enhancements", "enhancement_id")
    order = data["grade_order"]
    capacity = data["grades"][grade]["enchantment_capacity"] + material_capacity_bonus(material_id, capacity_rules)
    remaining = capacity - sum(enhancements[value]["equivalent_bonus"] for value in chosen_ids)
    return [
        row for row in data["enhancements"]
        if row["enhancement_id"] not in chosen_ids
        and row["equivalent_bonus"] <= remaining
        and order.index(row["minimum_grade"]) <= order.index(grade)
        and _matches(chassis, row["compatibility"])
        and not _opposed(material, row)
    ]


def resolve_treasure_armor(
    *,
    target_cl: int,
    background_id: str,
    path_id: str,
    chassis_id: str,
    material_id: str,
    enhancement_ids: Sequence[str],
    capacity_rules: int = 1,
) -> dict[str, Any]:
    """Validate the choices and compile the final armour entry (Chapter 3A Step 5)."""
    grade_info = armor_grade(target_cl, background_id)
    if grade_info is None:
        raise _invalid("This character has no treasure armour at its CL.", target_cl=target_cl)
    grade = grade_info["grade"]
    if chassis_id not in {row["item_id"] for row in chassis_options(path_id)}:
        raise _invalid("The Path does not equip this armour profile.", chassis_id=chassis_id, path_id=path_id)
    if material_id not in {row["material_id"] for row in material_options(grade, chassis_id)}:
        raise _invalid("The material cannot support this profile at the finished grade.", material_id=material_id, grade=grade)
    if len(set(enhancement_ids)) != len(enhancement_ids):
        raise _invalid("An enhancement is repeated.")
    chosen: list[str] = []
    for enhancement_id in enhancement_ids:
        if enhancement_id not in {row["enhancement_id"] for row in enhancement_options(chassis_id, material_id, grade, chosen, capacity_rules)}:
            raise _invalid("An enhancement is not legal for this armour.", enhancement_id=enhancement_id)
        chosen.append(enhancement_id)
    chassis = _by_id("chassis", "item_id")[chassis_id]
    material = _by_id("materials", "material_id")[material_id]
    enhancements = [_by_id("enhancements", "enhancement_id")[value] for value in chosen]
    total = sum(row["equivalent_bonus"] for row in enhancements)
    refinement = grade_info["refinement_bonus"]
    return {
        "schema_version": "TianxiaFoundry.ResolvedTreasureArmor.v1",
        "name": f"{material['name']} {chassis['name']} +{refinement}",
        "grade": grade,
        "grade_label": f"{grade} Treasure",
        "chassis": {key: chassis[key] for key in ("item_id", "name", "armor_category", "armor_class", "strength", "stealth", "weight", "construction_tags")},
        "material": {key: material[key] for key in ("material_id", "name", "grade", "affinities", "property_name", "property_text")},
        "refinement_bonus": refinement,
        "enchantment_capacity": grade_info["enchantment_capacity"] + material_capacity_bonus(material_id, capacity_rules),
        "enhancements": [
            {key: row[key] for key in ("enhancement_id", "name", "equivalent_bonus", "family", "text")}
            for row in enhancements
        ],
        "total_enchantment_value": total,
        "total_effective_bonus": refinement + total,
        "value_gt": grade_info["appraisal_gt"],
        "authority_sha256": AUTHORITY_SHA256,
    }
