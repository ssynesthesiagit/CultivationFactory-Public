"""Items the owner makes and gives to characters (owner 2026-09-24: an Items tab).

Weapons and armour are made from the treasure authorities with the same legality
checks the build walk uses: the material must support the grade, and each
enchantment or enhancement must suit the base item and fit the grade's capacity.
The owner's gold budget does not apply to items the owner hands out, and any
armour profile may be given (the walk limits armour by Path kit).

Given items are kept as a plain JSON list per character under
``<data>/owner_items/<project_id>.json``, outside the sealed character package,
so they can be added or removed at any time, for a finished character or one
still being built.  The character sheet and the combat compiler read the list.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import uuid
from pathlib import Path
from typing import Any, Sequence

from app.core import FoundryError

from . import treasure_armor as armour_rules
from . import treasure_catalog as catalog_rules
from . import treasure_weapons as weapon_rules

SCHEMA = "TianxiaFoundry.OwnerItems.v1"
KINDS = ("weapon", "armour", "wondrous", "consumable")


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("OWNER_ITEM_INVALID", message, details=details or None, status_code=422)


def _grades(rules) -> list[dict[str, Any]]:
    data = rules.authority()
    return [{"grade": grade, **data["grades"][grade]} for grade in data["grade_order"]]


def catalog() -> dict[str, Any]:
    """Everything the Items tab can list or make."""
    weapons = weapon_rules.authority()
    armour = armour_rules.authority()
    treasures = catalog_rules.authority()
    return {
        "weapon": {"chassis": weapons["chassis"], "grades": _grades(weapon_rules), "materials": weapons["materials"],
                   "enchantments": weapons["enchantments"]},
        "armour": {"chassis": armour["chassis"], "grades": _grades(armour_rules), "materials": armour["materials"],
                   "enhancements": armour["enhancements"]},
        "wondrous": treasures["wondrous"],
        "consumables": treasures["consumables"],
    }


def weapon_choices(chassis_id: str, grade: str, material_id: str | None, chosen_ids: Sequence[str]) -> dict[str, Any]:
    """Materials for the grade and the enchantments still legal after the chosen ones (for the dropdowns)."""
    materials = weapon_rules.material_options(grade)
    material_id = material_id if any(row["material_id"] == material_id for row in materials) else (materials[0]["material_id"] if materials else None)
    enchantments = weapon_rules.enchantment_options(chassis_id, material_id, grade, list(chosen_ids)) if material_id else []
    return {"materials": materials, "material_id": material_id, "enchantments": enchantments}


def armour_choices(chassis_id: str, grade: str, material_id: str | None, chosen_ids: Sequence[str]) -> dict[str, Any]:
    materials = armour_rules.material_options(grade, chassis_id)
    material_id = material_id if any(row["material_id"] == material_id for row in materials) else (materials[0]["material_id"] if materials else None)
    enhancements = armour_rules.enhancement_options(chassis_id, material_id, grade, list(chosen_ids)) if material_id else []
    return {"materials": materials, "material_id": material_id, "enhancements": enhancements}


def make_weapon(*, chassis_id: str, grade: str, material_id: str, enchantment_ids: Sequence[str], name: str | None = None) -> dict[str, Any]:
    data = weapon_rules.authority()
    if grade not in data["grades"]:
        raise _invalid("Unknown grade.", grade=grade)
    chassis = next((row for row in data["chassis"] if row["item_id"] == chassis_id), None)
    material = next((row for row in weapon_rules.material_options(grade) if row["material_id"] == material_id), None)
    if chassis is None or material is None:
        raise _invalid("Choose a weapon and a material that supports the grade.", chassis_id=chassis_id, material_id=material_id)
    chosen: list[str] = []
    for enchantment_id in enchantment_ids:
        legal = {row["enchantment_id"] for row in weapon_rules.enchantment_options(chassis_id, material_id, grade, chosen)}
        if enchantment_id not in legal:
            raise _invalid("That enchantment does not suit this weapon, grade or remaining capacity.", enchantment_id=enchantment_id)
        chosen.append(enchantment_id)
    by_id = {row["enchantment_id"]: row for row in data["enchantments"]}
    enchantments = [by_id[value] for value in chosen]
    refinement = data["grades"][grade]["refinement_bonus"]
    base_name = chassis["name"].split(" (")[0]
    lead = enchantments[0]["name"].split(" Inscription")[0] if enchantments else material["name"]
    return {
        "schema_version": "TianxiaFoundry.ResolvedTreasureWeapon.v1",
        "name": (name or "").strip() or f"{lead} {base_name} +{refinement}",
        "grade": grade,
        "grade_label": f"{grade} Treasure",
        "chassis": {key: chassis[key] for key in ("item_id", "name", "damage", "properties", "weapon_family")},
        "material": {key: material[key] for key in ("material_id", "name", "grade", "affinities", "property_name", "property_text")},
        "refinement_bonus": refinement,
        "enchantment_capacity": data["grades"][grade]["enchantment_capacity"]
        + weapon_rules.material_capacity_bonus(material_id, weapon_rules.CAPACITY_RULES_CURRENT),
        "enchantments": [{key: row[key] for key in ("enchantment_id", "name", "equivalent_bonus", "family", "text")} for row in enchantments],
        "total_enchantment_value": sum(row["equivalent_bonus"] for row in enchantments),
        "value_gt": data["grades"][grade]["appraisal_gt"],
        "authority_sha256": weapon_rules.AUTHORITY_SHA256,
    }


def make_armour(*, chassis_id: str, grade: str, material_id: str, enhancement_ids: Sequence[str], name: str | None = None) -> dict[str, Any]:
    data = armour_rules.authority()
    if grade not in data["grades"]:
        raise _invalid("Unknown grade.", grade=grade)
    chassis = next((row for row in data["chassis"] if row["item_id"] == chassis_id), None)
    material = next((row for row in armour_rules.material_options(grade, chassis_id) if row["material_id"] == material_id), None) if chassis else None
    if chassis is None or material is None:
        raise _invalid("Choose an armour and a material that supports the grade.", chassis_id=chassis_id, material_id=material_id)
    chosen: list[str] = []
    for enhancement_id in enhancement_ids:
        legal = {row["enhancement_id"] for row in armour_rules.enhancement_options(chassis_id, material_id, grade, chosen)}
        if enhancement_id not in legal:
            raise _invalid("That enhancement does not suit this armour, grade or remaining capacity.", enhancement_id=enhancement_id)
        chosen.append(enhancement_id)
    by_id = {row["enhancement_id"]: row for row in data["enhancements"]}
    enhancements = [by_id[value] for value in chosen]
    refinement = data["grades"][grade]["refinement_bonus"]
    lead = enhancements[0]["name"] if enhancements else material["name"]
    return {
        "schema_version": "TianxiaFoundry.ResolvedTreasureArmor.v1",
        "name": (name or "").strip() or f"{lead} {chassis['name']} +{refinement}",
        "grade": grade,
        "grade_label": f"{grade} Treasure",
        "chassis": {key: chassis[key] for key in ("item_id", "name", "armor_category", "armor_class", "strength", "stealth", "weight", "construction_tags")},
        "material": {key: material[key] for key in ("material_id", "name", "grade", "affinities", "property_name", "property_text")},
        "refinement_bonus": refinement,
        "enchantment_capacity": data["grades"][grade]["enchantment_capacity"] + armour_rules.material_capacity_bonus(material_id, 2),
        "enhancements": [{key: row[key] for key in ("enhancement_id", "name", "equivalent_bonus", "family", "text")} for row in enhancements],
        "total_enchantment_value": sum(row["equivalent_bonus"] for row in enhancements),
        "value_gt": data["grades"][grade]["appraisal_gt"],
        "authority_sha256": armour_rules.AUTHORITY_SHA256,
    }


CUSTOM_SCHEMA = "TianxiaFoundry.CustomItem.v1"
CUSTOM_KINDS = ("wondrous", "consumable")
CUSTOM_GRADES = ("Mortal", "Spiritual", "Saint", "Sovereign", "Imperial")
CUSTOM_EXAMPLE = {
    "schema": CUSTOM_SCHEMA,
    "items": [{
        "kind": "wondrous",
        "name": "Cloud-Step Anklet",
        "item_type": "Anklet",
        "grade": "Spiritual",
        "attunement_slots": 1,
        "activation": "Bonus Action",
        "family": "Movement",
        "sphere_influences": ["Wind", "Movement"],
        "text": "Once per short rest, as a bonus action, you walk on air until the end of your turn. You fall if you end your turn in the air.",
    }],
}
CUSTOM_INSTRUCTIONS = (
    "Create new Tianxia treasures as JSON for the Cultivation Factory. Reply with one JSON object shaped exactly like the example: "
    '{"schema": "' + CUSTOM_SCHEMA + '", "items": [ ... ]}. Each item needs: kind ("wondrous" or "consumable"), name, '
    "item_type (Ring, Amulet, Talisman, Pill, Elixir, ...), grade (Mortal, Spiritual, Saint, Sovereign or Imperial), "
    "attunement_slots (0-3), activation (Action, Bonus Action, Reaction, Passive, ...), family (a short theme), "
    "sphere_influences (a few Sphere names, optional) and text (the full rules, plain sentences, at most 4000 characters). "
    "Write rules the way the Tianxia books do: exact numbers, uses per rest, ranges and durations. No other keys."
)


def normalize_custom(entry: dict[str, Any]) -> dict[str, Any]:
    """Validate one custom or imported item (open-ended on purpose: the text carries the rules)."""
    if not isinstance(entry, dict):
        raise _invalid("Each item must be a JSON object.")

    def text(key: str, limit: int, *, required: bool = False) -> str:
        value = " ".join(str(entry.get(key) or "").split()) if key != "text" else str(entry.get(key) or "").strip()
        if required and not value:
            raise _invalid(f"An item needs a {key.replace('_', ' ')}.", item=entry.get("name"))
        if len(value) > limit:
            raise _invalid(f"The {key.replace('_', ' ')} is longer than {limit} characters.", item=entry.get("name"))
        return value

    kind = entry.get("kind") or "wondrous"
    if kind not in CUSTOM_KINDS:
        raise _invalid("A custom item is wondrous or consumable.", item=entry.get("name"))
    grade = entry.get("grade") or "Spiritual"
    if grade not in CUSTOM_GRADES:
        raise _invalid(f"The grade must be one of {', '.join(CUSTOM_GRADES)}.", item=entry.get("name"))
    try:
        slots = int(entry.get("attunement_slots") or 0)
    except (TypeError, ValueError):
        raise _invalid("Attunement slots must be a number from 0 to 3.", item=entry.get("name")) from None
    if not 0 <= slots <= 3:
        raise _invalid("Attunement slots must be a number from 0 to 3.", item=entry.get("name"))
    influences = entry.get("sphere_influences") or []
    if not isinstance(influences, list) or len(influences) > 8:
        raise _invalid("Sphere influences must be a short list of names.", item=entry.get("name"))
    return {
        "schema_version": CUSTOM_SCHEMA, "kind": kind,
        "name": text("name", 120, required=True), "item_type": text("item_type", 60), "grade": grade,
        "attunement_slots": slots, "activation": text("activation", 60), "family": text("family", 80),
        "sphere_influences": [" ".join(str(value).split())[:40] for value in influences if str(value).strip()],
        "text": text("text", 4000, required=True),
    }


class CustomItemLibrary:
    """The owner's own wondrous items and consumables, made on the Items tab or imported (e.g. from an AI GM)."""

    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / "library.json"
        self._lock = threading.Lock()

    def items(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return list(json.loads(self.path.read_text(encoding="utf-8")).get("items") or [])

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema": CUSTOM_SCHEMA + ".library", "updated_at": _now(), "items": items},
                                        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def add(self, entries: Sequence[dict[str, Any]], *, source: str = "owner") -> list[dict[str, Any]]:
        if not entries or len(entries) > 100:
            raise _invalid("Add between 1 and 100 items at a time.")
        added = [{**normalize_custom(entry), "custom_id": "custom." + uuid.uuid4().hex[:12], "source": source[:40], "added_at": _now()}
                 for entry in entries]
        with self._lock:
            self._save(self.items() + added)
        return added

    def remove(self, custom_id: str) -> list[dict[str, Any]]:
        with self._lock:
            items = [row for row in self.items() if row["custom_id"] != custom_id]
            self._save(items)
        return items

    def get(self, custom_id: str) -> dict[str, Any]:
        row = next((row for row in self.items() if row["custom_id"] == custom_id), None)
        if row is None:
            raise _invalid("That custom item is not in your library.", custom_id=custom_id)
        return row


def parse_import(payload: Any) -> list[dict[str, Any]]:
    """Accept {"items": [...]}, a list, or one item object (as an AI might answer)."""
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    raise _invalid("Paste a JSON object with an items list, a list of items, or one item.")


def pick_listed(kind: str, name: str) -> dict[str, Any]:
    rows = catalog_rules.authority()["wondrous" if kind == "wondrous" else "consumables"]
    row = next((row for row in rows if row["name"] == name), None)
    if row is None:
        raise _invalid("That item is not in the treasure catalog.", kind=kind, name=name)
    return {**row, "schema_version": f"TianxiaFoundry.Owner{kind.title()}Item.v1"}


def make_item(spec: dict[str, Any], library: "CustomItemLibrary | None" = None) -> dict[str, Any]:
    kind = spec.get("kind")
    if spec.get("custom_id"):
        if library is None:
            raise _invalid("Custom items need the item library.")
        record = library.get(spec["custom_id"])
        return {"kind": record["kind"], "name": record["name"], "record": record}
    if kind == "weapon":
        record = make_weapon(chassis_id=spec.get("chassis_id", ""), grade=spec.get("grade", ""), material_id=spec.get("material_id", ""),
                             enchantment_ids=[value for value in spec.get("enchantment_ids") or [] if value], name=spec.get("name"))
    elif kind == "armour":
        record = make_armour(chassis_id=spec.get("chassis_id", ""), grade=spec.get("grade", ""), material_id=spec.get("material_id", ""),
                             enhancement_ids=[value for value in spec.get("enhancement_ids") or [] if value], name=spec.get("name"))
    elif kind in {"wondrous", "consumable"}:
        record = pick_listed(kind, spec.get("item_name", ""))
    else:
        raise _invalid("Choose weapon, armour, wondrous or consumable.", kind=kind)
    return {"kind": kind, "name": record["name"], "record": record}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class OwnerItemStore:
    """One plain JSON list of given items per character (project id)."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._lock = threading.Lock()

    def _path(self, project_id: str) -> Path:
        if not project_id or "/" in project_id or ".." in project_id:
            raise _invalid("Unknown character.", project_id=project_id)
        return self.directory / f"{project_id}.json"

    def items(self, project_id: str) -> list[dict[str, Any]]:
        path = self._path(project_id)
        if not path.is_file():
            return []
        return list(json.loads(path.read_text(encoding="utf-8")).get("items") or [])

    def _save(self, project_id: str, items: list[dict[str, Any]]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(project_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema": SCHEMA, "project_id": project_id, "updated_at": _now(), "items": items},
                                        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)

    def give(self, project_id: str, spec: dict[str, Any], library: "CustomItemLibrary | None" = None) -> dict[str, Any]:
        item = make_item(spec, library)
        entry = {"item_uid": "item." + uuid.uuid4().hex[:12], "given_at": _now(), **item}
        with self._lock:
            items = self.items(project_id)
            if item["kind"] == "armour":  # a character wears one armour: the newest is equipped
                for row in items:
                    if row["kind"] == "armour":
                        row["equipped"] = False
                entry["equipped"] = True
            items.append(entry)
            self._save(project_id, items)
        return entry

    def remove(self, project_id: str, item_uid: str) -> list[dict[str, Any]]:
        with self._lock:
            items = [row for row in self.items(project_id) if row["item_uid"] != item_uid]
            self._save(project_id, items)
        return items

    def equip(self, project_id: str, item_uid: str) -> list[dict[str, Any]]:
        with self._lock:
            items = self.items(project_id)
            target = next((row for row in items if row["item_uid"] == item_uid), None)
            if target is None or target["kind"] != "armour":
                raise _invalid("Only a given armour can be equipped.", item_uid=item_uid)
            for row in items:
                if row["kind"] == "armour":
                    row["equipped"] = row["item_uid"] == item_uid
            self._save(project_id, items)
        return items


def equipped_armour(items: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    return next((row["record"] for row in items if row.get("kind") == "armour" and row.get("equipped")), None)


def given_weapons(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row["record"] for row in items if row.get("kind") == "weapon"]
