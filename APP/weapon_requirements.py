"""Shared weapon data queries for creation, docket maneuvers and weapon delivery.

No combat runtime, plug-in registry or actor state is imported here. Maneuver
ownership is the docket's original rule; delivery kinds and families are the
compiler's original checks. Ammunition identities are shared with its plug-in.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from authority_records import Authority

APP = Path(__file__).resolve().parent
RULES = APP / "combat/rules/weapon_requirements.json"
RULES_SHA256 = "1a0c0b5dde7ceef3fb920a623b665a97d2dd414f5e513aea2d8a556099717999"


@lru_cache(maxsize=1)
def _rules():
    data = RULES.read_bytes()
    if hashlib.sha256(data).hexdigest() != RULES_SHA256:
        raise ValueError("Weapon requirement data does not match its pin.")
    return json.loads(data)


def maneuver_specs():
    """Return independent specs, retaining the docket's tuple-valued fields."""
    specs = deepcopy(_rules()["maneuvers"])
    for spec in specs:
        for field in ("records", "kinds"):
            spec[field] = tuple(spec[field])
    return tuple(specs)


def owns_maneuver(spec, info):
    """The docket ownership rule, also used by starting equipment planning."""
    owned = set(info["owned"])
    if owned & set(spec["records"]):
        return True
    return bool(spec.get("sphere_grants", True)) and spec["sphere"] in set(info.get("spheres") or ())


@lru_cache(maxsize=1)
def _mechanics(path, mtime, size):
    return Authority(json.loads(Path(path).read_text(encoding="utf-8"))).records()


def owned_weapon_requirements(owned=(), spheres=(), *, mechanics=None):
    """One alternative-kind requirement per owned maneuver or delivered talent.

    Different abilities are separate requirements, not a union that lets a melee
    talent hide an unusable ranged talent. An unarmed alternative needs no item.
    """
    info = {"owned": owned, "spheres": spheres}
    requirements = [{"name": spec["name"], "kinds": list(spec["kinds"])}
                    for spec in maneuver_specs() if owns_maneuver(spec, info)]
    if mechanics is None:
        path = APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
        stat = path.stat()
        mechanics = _mechanics(str(path), stat.st_mtime_ns, stat.st_size)
    for record_id in sorted(set(owned)):
        row = mechanics.get(record_id) or {}
        delivery = row.get("weapon_delivery") or (row.get("range") or {}).get("weapon_delivery")
        if delivery:
            requirements.append({"name": row.get("name") or record_id, "delivery": deepcopy(delivery)})
    return requirements


def weapon_delivery_flags(item):
    """Catalog delivery flags, shared with the compiler's weapon-kind records."""
    properties = str(item.get("properties") or "")
    ranged = bool(re.search(r"(?:Thrown|Range) (\d+)/(\d+)", properties))
    weapon_class = str(item.get("proficiency_class") or "").lower()
    melee_kind = str(item.get("attack_kind") or "").lower() == "melee"
    also_thrown = ranged and "thrown" in properties.lower() and (
        "melee" in weapon_class or (not weapon_class and melee_kind))
    return {"melee": not ranged or bool(also_thrown), "ranged": ranged,
            "thrown": ranged and "thrown" in properties.lower()}


def fits_delivery_kind(weapon, delivery):
    kind = delivery.get("kind") or "any"
    return not (kind == "melee" and not weapon["melee"] or
                kind == "ranged" and not weapon["ranged"] or
                kind == "thrown" and not weapon["thrown"])


def source_weapon_family(item):
    """Reviewed source families, shared with the source-family combat hook."""
    return next((family for family, field_value in _rules()["source_families"].items()
                 if item.get("weapon_family") == field_value), None)


def fits_delivery_family(weapon, delivery):
    """Default family query; source-defined families require their catalog field."""
    family = delivery.get("family")
    if not family:
        return True
    if family in _rules()["source_families"]:
        return source_weapon_family(weapon) == family
    return any(word in weapon["name"].lower()
               for word in _rules()["delivery_family_words"].get(family, (family,)))


def item_fits_requirement(item, requirement):
    if item.get("category") != "weapon":
        return False
    flags = weapon_delivery_flags(item)
    if "delivery" in requirement:
        weapon = {**item, **flags}
        return fits_delivery_kind(weapon, requirement["delivery"]) and fits_delivery_family(weapon, requirement["delivery"])
    return any(flags.get(kind, False) for kind in requirement["kinds"])


def ammunition_kinds():
    """Return (item_id, label) pairs for the ammunition plug-in's stock pools."""
    return tuple(tuple(identity) for identity in _rules()["ammunition"].values())


def ammunition_requirement(item):
    """The ammunition plug-in's catalog classification, without combat state."""
    properties = str(item.get("properties") or "")
    if not re.search(r"\bAmmunition\b", properties, re.I):
        return None
    explicit = re.search(r"Ammunition\s*\([^)]*;\s*(Arrow|Bolt|Needle)\s*\)", properties, re.I)
    kind = explicit.group(1).lower() if explicit else ""
    if not kind:
        family = str(item.get("weapon_family") or "").lower()
        name = str(item.get("name") or item.get("item_id") or "").lower()
        if "pellet" in family or "sling" in family or "sling" in name:
            kind = "bullet"
        elif "crossbow" in family or "crossbow" in name:
            kind = "bolt"
        elif "bow" in family or "bow" in name:
            kind = "arrow"
    if kind not in _rules()["ammunition"]:
        return None
    item_id, label = _rules()["ammunition"][kind]
    return {"item_id": item_id, "label": label}
