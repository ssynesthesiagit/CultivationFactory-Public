#!/usr/bin/env python3
"""Build the treasure-weapon authority from Item Book R1 Chapter 2.

Chapter 2 builds a cultivation weapon in order: legal weapon chassis (2A),
Primary Material (2B), finished grade and Refinement Bonus, enchantments within
the grade's capacity (2C), final entry.  This builder extracts every material
and enchantment with its exact line span and section hash, binds each chassis
to the Mortal equipment catalog, and records the grade table and the CL
treasure budget (owner-approved draft EQUIPMENT_AND_TREASURE_DRAFT_2026-09-22 §4).

The Item Book states chassis limits in each enchantment's rules text rather
than as a field; the four enchantments whose text limits the chassis are
pinned in ``CHASSIS_REQUIREMENTS`` (checked against the text below).  Material
opposition ("Air and teleportation effects unless stabilized") is pinned as
keywords in ``OPPOSED_KEYWORDS``; the Factory adds no stabilizing Secondary
Material, so an opposed enchantment is never offered.

Usage:
  python build_treasure_weapon_authority.py --factory-root <HF2 root> --output authority/Tianxia_Treasure_Weapon_Authority_R1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ITEM_BOOK = "09_RULES/Items/Tianxia_ItemBook_R1.md"
CATALOG_PATH = "authority/Tianxia_Mundane_Equipment_Catalog_R1.json"
SCHEMA = "TianxiaFoundry.TreasureWeaponAuthority.v1"

GRADES = ("Spiritual", "Saint", "Sovereign", "Imperial")
# Item Book Chapter 2A Step 3 and the Commercial Appraisal base values.
GRADE_TABLE = {
    "Spiritual": {"refinement_bonus": 1, "enchantment_capacity": 1, "appraisal_gt": 200},
    "Saint": {"refinement_bonus": 2, "enchantment_capacity": 3, "appraisal_gt": 2000},
    "Sovereign": {"refinement_bonus": 4, "enchantment_capacity": 6, "appraisal_gt": 20000},
    "Imperial": {"refinement_bonus": 6, "enchantment_capacity": 10, "appraisal_gt": 100000},
}
MATERIAL_CEILING = {"Mortal": "Spiritual", "Spiritual": "Saint", "Saint": "Sovereign", "Sovereign": "Imperial", "Imperial": "Immortal", "Immortal": "Bespoke"}
# Realm signature grade caps (Item Book Ch. 9, draft §4).
REALM_CAP_BY_CL = [(1, None), (5, "Saint"), (10, "Sovereign"), (15, "Imperial")]
# Draft §4 centre-line treasure budget in Gold Taels.
BUDGET_BY_CL = [(1, 0), (5, 2400), (8, 4400), (10, 4200), (13, 24200), (15, 24200), (18, 142000), (20, 142000)]

# Enchantments whose rules text limits the chassis (quoted phrase must appear).
CHASSIS_REQUIREMENTS = {
    "Returning Inscription": {"any_of": ["Thrown"], "phrase": "thrown attack"},
    "Pursuing-Star Inscription": {"any_of": ["Ranged", "Thrown"], "with_enchantments": ["Returning Inscription", "Flying Sword Command"], "phrase": "lacks a ranged attack"},
    "Long-Reach Inscription": {"any_of": ["Melee"], "phrase": "If the weapon is a melee weapon"},
    "Thousand-Li Pursuit Inscription": {"any_of": ["Ranged", "Thrown"], "with_enchantments": ["Flying Sword Command"], "phrase": "can be applied only to a ranged weapon"},
}
# Material opposition, as keywords matched against an enchantment's name and Sphere Influences.
OPPOSED_KEYWORDS = {
    "Black Iron": ["Air", "Space"],
    "Spirit-Beast Bone": ["Fire", "Flame"],
    "Cloudwood": ["Weight", "Mountain", "Earth"],
    "White Jade Composite": ["Thunder", "Lightning"],
    "Storm Iron": ["Ice", "Frost"],
    "Moon Silver": ["Solar", "Sun", "Yang"],
    "Sun Copper": ["Yin", "Cold", "Frost", "Ice", "Moon"],
    "River Jade": ["Weight", "Mountain"],
    "Thunderwood": ["Rot", "Drain", "Corrosion", "Decay"],
    "Frost Jade": ["Fire", "Flame"],
    "Spirit Bamboo": ["Weight", "Mountain"],
    "Mountain-Root Jade": ["Air", "Teleportation", "Space", "Cloud"],
    "Star Silver": ["Dark", "Shadow", "Moonless"],
    "Ghost Iron": ["Radiant", "Sun"],
    "Phoenix-Ash Steel": ["Deep Yin", "Moonless", "Yin"],
    "Voidglass Alloy": ["Thunder", "Lightning"],
    "Blood Jade": ["Purification", "Radiant"],
    "Deepsea Cold Iron": ["Fire", "Flame"],
    "Soul Jade": ["Devouring"],
    "Heaven-Splitting Stone": ["Illusion", "Mirror"],
    "Cloud-Void Crystal": ["Weight", "Mountain"],
    "Demon-Heart Iron": ["Radiant", "Purification"],
    "Mirror-Sea Silver": ["Thunder", "Lightning"],
    "Phoenix-Blood Scarlet Gold": ["Deep Yin", "Moonless", "Yin"],
    "Immortal-Tear Verdant Gold": ["Devouring"],
    "Feathered Celestial Green Gold": ["Weight", "Mountain"],
    "Primordial Mother-Weight Essence": ["Air", "Space"],
    "Enlightenment Tree Heartwood": ["Devouring", "Corruption"],
    "World-Heart Crystal": ["Devouring"],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _entries(lines: list[str], start: int, end: int, first_field: str) -> list[dict]:
    rows = []
    i = start
    while i < end:
        if lines[i].startswith("## ") and i + 1 < end and lines[i + 1].startswith(f"**{first_field}:**"):
            name = lines[i][3:].strip()
            j = i + 1
            fields: dict[str, str] = {}
            body: list[str] = []
            while j < end and not lines[j].startswith("## ") and not lines[j].startswith("# ") and lines[j].strip() != "---":
                m = re.match(r"\*\*([A-Za-z ]+):\*\*\s*(.*)", lines[j])
                if m and not body:
                    fields[m.group(1).lower().replace(" ", "_")] = m.group(2).strip()
                elif lines[j].strip():
                    body.append(lines[j].rstrip())
                j += 1
            # Section = heading through the last non-blank body line.
            last = j - 1
            while last > i and not lines[last].strip():
                last -= 1
            section = "\n".join(lines[i:last + 1])
            rows.append({
                "name": name,
                "fields": fields,
                "text": "\n".join(body).strip(),
                "source": {"line_start": i + 1, "line_end": last + 1, "section_sha256": sha256_bytes(section.encode("utf-8"))},
            })
            i = j
        else:
            i += 1
    return rows


def chassis_tags(item: dict) -> list[str]:
    family = str(item.get("weapon_family") or "")
    properties = str(item.get("properties") or "")
    tags = str(item.get("tags") or "")
    group = family.split("/")[0].strip()
    result = {"Any"}
    result.add("Ranged" if group == "Projectile" or "Ammunition" in properties else "Melee")
    if group in {"Short", "Long", "Soft", "Projectile"}:
        result.add(group)
    for word, tag in (("Thrown", "Thrown"), ("Ammunition", "Ammunition"), ("Reach", "Reach"), ("Heavy", "Heavy")):
        if word in properties:
            result.add(tag)
    if "Hidden" in tags or "Concealed" in properties:
        result.add("Concealable")
    if "Light" in properties or "Paired" in properties:
        result.add("Paired")
    if any(word in properties + " " + tags for word in ("Armor-Breaking", "Sword-Breaker", "Heavy-Headed", "Smash")):
        result.add("Armor-Breaking")
    return sorted(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factory-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    book_path = Path(args.factory_root) / ITEM_BOOK
    raw = book_path.read_bytes()
    lines = raw.decode("utf-8").split("\n")

    def index_of(prefix: str) -> int:
        return next(i for i, line in enumerate(lines) if line.startswith(prefix))

    mat_start, mat_end = index_of("# Mortal Materials"), index_of("# Material and Enchantment Examples")
    ench_start = index_of("# +1 Enchantments")
    ench_end = next((i for i, line in enumerate(lines) if i > ench_start and line.startswith("## Chapter 3")), len(lines))

    materials = []
    for row in _entries(lines, mat_start, mat_end, "Material Grade"):
        f = row["fields"]
        grade = f["material_grade"]
        if grade not in MATERIAL_CEILING:
            raise SystemExit(f"unknown material grade {grade!r} for {row['name']}")
        prop = re.match(r"\*\*Material Property\s*[—-]\s*([^.*]+)\.\*\*\s*(.*)", row["text"], re.S)
        if prop is None:
            raise SystemExit(f"material property missing for {row['name']}")
        opposed = f.get("opposed_enchantments", "None")
        if opposed != "None" and row["name"] not in OPPOSED_KEYWORDS:
            raise SystemExit(f"material {row['name']} has opposition {opposed!r} but no pinned keywords")
        materials.append({
            "material_id": f"tianxia.treasure.material.{slug(row['name'])}",
            "name": row["name"],
            "grade": grade,
            "normal_ceiling": MATERIAL_CEILING[grade],
            "affinities": [a.strip() for a in f.get("affinities", "").split(",") if a.strip()],
            "preferred_enchantments": f.get("preferred_enchantments", ""),
            "opposed_text": opposed,
            "opposed_keywords": OPPOSED_KEYWORDS.get(row["name"], []),
            "property_name": prop.group(1).strip(),
            "property_text": row["text"],
            "source": row["source"],
        })

    enchantments = []
    skipped_immortal: list[str] = []
    for row in _entries(lines, ench_start, ench_end, "Minimum Grade"):
        f = row["fields"]
        if f["minimum_grade"].strip() == "Immortal Artifact":
            # Immortal Artifacts are never created or bought (Item Book Ch. 1).
            skipped_immortal.append(row["name"])
            continue
        grade = f["minimum_grade"].replace(" Treasure", "").strip()
        bonus = re.search(r"\+(\d+)", f["equivalent_bonus"])
        if grade not in GRADES or bonus is None:
            raise SystemExit(f"bad enchantment fields for {row['name']}: {f}")
        requirement = CHASSIS_REQUIREMENTS.get(row["name"])
        if requirement and requirement["phrase"].lower() not in row["text"].lower():
            raise SystemExit(f"pinned chassis requirement phrase not in the text of {row['name']}")
        enchantments.append({
            "enchantment_id": f"tianxia.treasure.enchantment.{slug(row['name'])}",
            "name": row["name"],
            "minimum_grade": grade,
            "equivalent_bonus": int(bonus.group(1)),
            "family": f.get("family", ""),
            "sphere_influences": [a.strip() for a in f.get("sphere_influences", "").split(",") if a.strip()],
            "preferred_materials": f.get("preferred_materials", ""),
            "prerequisite": f.get("prerequisite") or None,
            "chassis_requirement": {key: value for key, value in (requirement or {}).items() if key != "phrase"} or None,
            "text": row["text"],
            "source": row["source"],
        })
    missing = set(CHASSIS_REQUIREMENTS) - {e["name"] for e in enchantments}
    if missing:
        raise SystemExit(f"pinned chassis requirements name unknown enchantments: {missing}")

    catalog_file = APP / CATALOG_PATH
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    chassis = [
        {"item_id": item["item_id"], "name": item["name"], "damage": item.get("damage"), "properties": item.get("properties"),
         "weapon_family": item.get("weapon_family"), "compatibility_tags": chassis_tags(item)}
        for item in catalog["items"]
        if item["category"] == "weapon" and item.get("source") == "item_book_r1"
    ]
    if len(chassis) != 32:
        raise SystemExit(f"expected the 32 Item Book weapon profiles, found {len(chassis)}")

    authority = {
        "schema_version": SCHEMA,
        "sources": {
            "item_book": {"path": ITEM_BOOK, "sha256": sha256_bytes(raw)},
            "catalog": {"path": CATALOG_PATH, "sha256": sha256_bytes(catalog_file.read_bytes())},
            "budget": "docs/plans/EQUIPMENT_AND_TREASURE_DRAFT_2026-09-22.md §4",
        },
        "grades": GRADE_TABLE,
        "grade_order": list(GRADES),
        "realm_cap_by_cl": REALM_CAP_BY_CL,
        "budget_gt_by_cl": BUDGET_BY_CL,
        "counts": {"chassis": len(chassis), "materials": len(materials), "enchantments": len(enchantments), "immortal_artifact_enchantments_excluded": len(skipped_immortal)},
        "chassis": chassis,
        "materials": materials,
        "enchantments": enchantments,
    }
    Path(args.output).write_text(json.dumps(authority, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(authority["counts"]), sha256_bytes(Path(args.output).read_bytes()))


if __name__ == "__main__":
    main()
