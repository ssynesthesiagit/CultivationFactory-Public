"""Treasure weapons built by Item Book R1 Chapter 2.

Order (Chapter 2A): chassis -> Primary Material -> finished grade (Refinement
Bonus, enchantment capacity) -> enchantments -> final entry.  The finished grade
is set by the server from the CL treasure budget, the Background wealth
multiplier and the Realm cap (owner-approved draft §4; owner ruling 2026-09-24:
a CL15+ character carries at least a Saint weapon).  Chassis, material and
enchantments are closed menus the local model picks from.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core import FoundryError

APP_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = "authority/Tianxia_Treasure_Weapon_Authority_R1.json"
AUTHORITY_SHA256 = "b6087f4e729712f25917289ff5b913970052bce626e1b7a7845284a45934d52a"
# Share of the character's treasure budget the signature weapon may take.
WEAPON_BUDGET_SHARE = 0.6
# Owner ruling 2026-09-24: from Nascent Soul (CL15) the weapon is at least Saint.
SAINT_FLOOR_CL = 15
# Capacity rules version.  1: grade capacity only (the first kits).  2: a
# Primary Material that states "enchantment capacity increases by +1"
# (Heaven-Mark Violet Gold, Natural Dao Surface) adds it.  Records keep the
# version they were built with, so earlier kits re-derive unchanged.
CAPACITY_RULES_CURRENT = 2
MATERIAL_CAPACITY_BONUS = {"tianxia.treasure.material.heaven_mark_violet_gold": 1}


def material_capacity_bonus(material_id: str, capacity_rules: int) -> int:
    return MATERIAL_CAPACITY_BONUS.get(material_id, 0) if capacity_rules >= 2 else 0


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("TREASURE_WEAPON_INVALID", message, details=details or None)


@lru_cache(maxsize=1)
def authority() -> dict[str, Any]:
    path = APP_ROOT / AUTHORITY_PATH
    if path.is_symlink() or not path.is_file():
        raise _invalid("The treasure-weapon authority file is missing.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != AUTHORITY_SHA256:
        raise _invalid("The treasure-weapon authority does not match its pin.")
    return json.loads(data.decode("utf-8"))


def _by_id(kind: str, key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in authority()[kind]}


def _step(table: Sequence[Sequence[Any]], cl: int) -> Any:
    value = None
    for threshold, entry in table:
        if cl >= threshold:
            value = entry
    return value


def weapon_grade(target_cl: int, background_id: str) -> dict[str, Any] | None:
    """The finished grade for this character's signature weapon, or None below Foundation.

    The budget uses the Background wealth tier only; the kit's seeded fortune
    roll is keyed to the intent hash, which the walk cannot know yet.
    """
    from factory_authoring.starting_kits import background_kit, wealth_tier_multipliers

    data = authority()
    cap = _step(data["realm_cap_by_cl"], int(target_cl))
    if cap is None:
        return None
    tier = background_kit(background_id)["wealth_tier"]
    wealth = {"wealth_tier": tier, "multiplier": wealth_tier_multipliers()[tier]}
    budget = _step(data["budget_gt_by_cl"], int(target_cl)) * wealth["multiplier"]
    order = data["grade_order"]
    allowed = order[: order.index(cap) + 1]
    affordable = [grade for grade in allowed if data["grades"][grade]["appraisal_gt"] <= budget * WEAPON_BUDGET_SHARE]
    floor = "Saint" if int(target_cl) >= SAINT_FLOOR_CL else None
    grade = affordable[-1] if affordable else floor
    if floor is not None and order.index(grade) < order.index(floor):
        grade = floor
    if grade is None:
        return None
    return {"grade": grade, "realm_cap": cap, "budget_gt": round(budget, 2), "wealth": wealth, **data["grades"][grade]}


def chassis_options() -> list[dict[str, Any]]:
    return list(authority()["chassis"])


# Weapon Spheres whose Talents work only with certain weapons (Sphere
# Compendium R0I): Sabers "qualifying saber-profile weapons" (dao, duan dao,
# butterfly saber, cavalry or heavy saber); Sword shortswords, longswords and
# greatswords; Spear spears, pikes, lances and tridents; Axes; Chains chain
# weapons.  Dual Wielding needs a one-handed melee weapon (a Qualifying Pair)
# and its Paired Strike comes from the Light property.
_WEAPON = "tianxia.mortal.weapon."
SPHERE_WEAPON_CHASSIS: dict[str, frozenset[str]] = {
    "tianxia.sphere.sabers": frozenset(_WEAPON + name for name in ("dao", "duan_dao", "hu_die_dao", "guandao_yanyuedao")),
    "tianxia.sphere.sword": frozenset(_WEAPON + name for name in ("jian", "duan_jian")),
    "tianxia.sphere.spear": frozenset(_WEAPON + name for name in ("qiang", "mao", "cha_hu_cha", "duan_cha")),
    "tianxia.sphere.axes": frozenset({_WEAPON + "fu"}),
    "tianxia.sphere.chains": frozenset(_WEAPON + name for name in ("jie_bian", "liu_xing_chui")),
}
PAIRED_WEAPON_SPHERES = frozenset({"tianxia.sphere.dual_wielding"})


def _properties(row: Mapping[str, Any]) -> set[str]:
    return {part.strip().split(" ")[0] for part in str(row.get("properties") or "").split(",")}


def _one_handed_melee(row: Mapping[str, Any]) -> bool:
    return "Two-Handed" not in _properties(row) and not str(row.get("weapon_family", "")).startswith("Projectile")


def _path_trained(path_id: str | None) -> set[str] | None:
    """The weapon classes (simple, martial, exotic) a Path trains, from combat/rules/weapon_specials.json."""
    if not path_id:
        return None
    import json
    from pathlib import Path as _Path

    rules = json.loads((_Path(__file__).resolve().parents[1] / "combat" / "rules" / "weapon_specials.json").read_text(encoding="utf-8"))
    return set(((rules.get("proficiency") or {}).get("classes_by_path") or {}).get(path_id) or [])


def heavy_unfit(row: Mapping[str, Any], scores: Mapping[str, Any] | None) -> bool:
    """2024 Heavy: attacks have Disadvantage without Strength 13 (melee) or Dexterity 13 (ranged). Unknown scores fit."""
    if not scores or "Heavy" not in _properties(row):
        return False
    normalized = {str(key).upper()[:3]: value for key, value in scores.items()}
    ability = "DEX" if "Ammunition" in _properties(row) else "STR"
    try:
        return int(normalized.get(ability, 13)) < 13
    except (TypeError, ValueError):
        return False


def sphere_fit_chassis(known_sphere_ids: Sequence[str] | set[str], path_id: str | None = None,
                       scores: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """The weapons the character's weapon Spheres can use, best fit first.

    A treasure weapon their Sphere Talents cannot use is wasted.  With no
    weapon Sphere every weapon stays open.  With several, weapons more of them
    accept come first; with Dual Wielding only one-handed melee weapons count,
    Light ones first.  If no weapon satisfies both, the weapon Spheres win.  A Heavy weapon the character's
    ``scores`` would attack with at Disadvantage comes last (owner 2026-09-26: the picker ignored Heavy).
    """
    known = set(known_sphere_ids)
    rows = chassis_options()
    sets = [SPHERE_WEAPON_CHASSIS[sphere] for sphere in sorted(known) if sphere in SPHERE_WEAPON_CHASSIS]
    paired = bool(known & PAIRED_WEAPON_SPHERES)
    fitting = [row for row in rows if any(row["item_id"] in ids for ids in sets)] if sets else list(rows)
    trained = _path_trained(path_id)
    if not sets and trained is not None:
        # Owner 2026-09-26: with no weapon Sphere, a weapon the character's Path trains (13 finished characters got a
        # treasure weapon they could not use); every weapon only if none fits.
        from factory_authoring.starting_kits import _authorities

        catalog = _authorities()[1]
        fitting = [row for row in rows if (catalog.get(row["item_id"]) or {}).get("proficiency") in trained] or list(rows)
    if paired:
        fitting = [row for row in fitting if _one_handed_melee(row)] or fitting
    order = {row["item_id"]: index for index, row in enumerate(rows)}
    return sorted(fitting, key=lambda row: (
        heavy_unfit(row, scores),
        -sum(row["item_id"] in ids for ids in sets),
        0 if not paired or "Light" in _properties(row) else 1,
        order[row["item_id"]],
    ))


def material_options(grade: str) -> list[dict[str, Any]]:
    """Materials whose normal ceiling supports the finished grade (Chapter 2B)."""
    order = authority()["grade_order"] + ["Immortal", "Bespoke"]
    return [
        row for row in authority()["materials"]
        if row["normal_ceiling"] in order and order.index(row["normal_ceiling"]) >= order.index(grade)
    ]


def _opposed(material: Mapping[str, Any], enchantment: Mapping[str, Any]) -> bool:
    words = " ".join([enchantment["name"], *enchantment.get("sphere_influences", [])]).lower()
    return any(keyword.lower() in words for keyword in material.get("opposed_keywords", []))


def _chassis_ok(chassis: Mapping[str, Any], enchantment: Mapping[str, Any], chosen_names: set[str]) -> bool:
    requirement = enchantment.get("chassis_requirement")
    if not requirement:
        return True
    if set(requirement.get("any_of", [])) & set(chassis["compatibility_tags"]):
        return True
    return bool(set(requirement.get("with_enchantments", [])) & chosen_names)


def enchantment_options(
    chassis_id: str, material_id: str, grade: str, chosen_ids: Sequence[str], capacity_rules: int = CAPACITY_RULES_CURRENT,
) -> list[dict[str, Any]]:
    """Enchantments still legal for this weapon and within its remaining capacity (Chapter 2C)."""
    data = authority()
    chassis = _by_id("chassis", "item_id")[chassis_id]
    material = _by_id("materials", "material_id")[material_id]
    enchantments = _by_id("enchantments", "enchantment_id")
    order = data["grade_order"]
    chosen = [enchantments[value] for value in chosen_ids]
    capacity = data["grades"][grade]["enchantment_capacity"] + material_capacity_bonus(material_id, capacity_rules)
    remaining = capacity - sum(row["equivalent_bonus"] for row in chosen)
    chosen_names = {row["name"] for row in chosen}
    result = []
    for row in data["enchantments"]:
        if row["enchantment_id"] in chosen_ids or row["equivalent_bonus"] > remaining:
            continue
        if order.index(row["minimum_grade"]) > order.index(grade):
            continue
        if row.get("prerequisite") and row["prerequisite"] not in chosen_names:
            continue
        if _opposed(material, row) or not _chassis_ok(chassis, row, chosen_names):
            continue
        result.append(row)
    return result


def resolve_treasure_weapon(
    *,
    target_cl: int,
    background_id: str,
    chassis_id: str,
    material_id: str,
    enchantment_ids: Sequence[str],
    capacity_rules: int = 1,
) -> dict[str, Any]:
    """Validate the choices and compile the final weapon entry (Chapter 2A Step 5)."""
    grade_info = weapon_grade(target_cl, background_id)
    if grade_info is None:
        raise _invalid("This character has no treasure weapon at its CL.", target_cl=target_cl)
    grade = grade_info["grade"]
    chassis = _by_id("chassis", "item_id").get(chassis_id)
    material = _by_id("materials", "material_id").get(material_id)
    if chassis is None or material is None:
        raise _invalid("Unknown chassis or material.", chassis_id=chassis_id, material_id=material_id)
    if material_id not in {row["material_id"] for row in material_options(grade)}:
        raise _invalid("The material cannot support the finished grade.", material_id=material_id, grade=grade)
    if len(set(enchantment_ids)) != len(enchantment_ids):
        raise _invalid("An enchantment is repeated.")
    chosen: list[str] = []
    for enchantment_id in enchantment_ids:
        legal = {row["enchantment_id"] for row in enchantment_options(chassis_id, material_id, grade, chosen, capacity_rules)}
        if enchantment_id not in legal:
            raise _invalid("An enchantment is not legal for this weapon.", enchantment_id=enchantment_id)
        chosen.append(enchantment_id)
    enchantments = [_by_id("enchantments", "enchantment_id")[value] for value in chosen]
    total_enchantment = sum(row["equivalent_bonus"] for row in enchantments)
    refinement = grade_info["refinement_bonus"]
    base_name = chassis["name"].split(" (")[0]
    return {
        "schema_version": "TianxiaFoundry.ResolvedTreasureWeapon.v1",
        "name": f"{material['name']} {base_name} +{refinement}",
        "grade": grade,
        "grade_label": f"{grade} Treasure",
        "chassis": {key: chassis[key] for key in ("item_id", "name", "damage", "properties", "weapon_family")},
        "material": {key: material[key] for key in ("material_id", "name", "grade", "affinities", "property_name", "property_text")},
        "refinement_bonus": refinement,
        "enchantment_capacity": grade_info["enchantment_capacity"] + material_capacity_bonus(material_id, capacity_rules),
        "enchantments": [
            {key: row[key] for key in ("enchantment_id", "name", "equivalent_bonus", "family", "text")}
            for row in enchantments
        ],
        "total_enchantment_value": total_enchantment,
        "total_effective_bonus": refinement + total_enchantment,
        "value_gt": grade_info["appraisal_gt"],
        "budget": {key: grade_info[key] for key in ("realm_cap", "budget_gt", "wealth")},
        "authority_sha256": AUTHORITY_SHA256,
    }
