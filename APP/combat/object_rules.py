"""Destructible objects and structures: what one is, and what damage does to it (owner 2026-09-29, task O: "destructible
objects and structures per D&D 5.5e -- object AC/HP by material and size, damage thresholds, what they can't be affected by
-- placeable on the map, attackable, with the abilities whose text damages objects using them").

Pure rules, no engine: the tables are combat/rules/objects.json (2024 DMG object AC by material and hit points by size; its
"source" and "*_note" keys say where each number comes from), the owner's own numbers ride on the placement, and the order
damage is worked out in is the owner's (Body Refining R8: "Double damage applies once, after Resistance, Immunity, Damage
Threshold and other modifiers"; the Sphere Compendium's glossary: Damage Threshold is the 2024 meaning, immune to all damage
unless one instance of it is at least the threshold).

    one instance = every packet one attack or effect deals to the object, added up
    1  Damage Threshold     under it, the instance does nothing (an ability may reduce it or ignore it, for that instance only)
    2  Immunity             a packet of an immune kind (Poison and Psychic for every object) does nothing
    3  Resistance           half, rounded down; Vulnerability doubles
    4  "double damage"      once, however many abilities say so (a "one additional die" is rolled by the ability, before 1)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).resolve().parent / "rules" / "objects.json"
_CACHE: dict[str, Any] = {}


def rules() -> dict[str, Any]:
    stamp = RULES_PATH.stat().st_mtime_ns
    if _CACHE.get("stamp") != stamp:
        _CACHE.update(stamp=stamp, data=json.loads(RULES_PATH.read_text(encoding="utf-8")))
    return _CACHE["data"]


def presets() -> dict[str, dict[str, Any]]:
    return rules()["presets"]


def simple_door_state(row: dict[str, Any]) -> dict[str, Any] | None:
    """Explicit interaction metadata shared by tabletop, objects and Thread.

    Only a door explicitly designated simple has an interaction state. All
    three flags must be whole integer 0/1; missing state is never unlocked.
    This describes the attached door, not permission to move it as a loose item.
    """
    keys = ("door_open", "door_locked", "door_jammed")
    if (row.get("kind") != "door" or row.get("interaction") != "simple_door"
            or any(type(row.get(k)) is not int or row[k] not in (0, 1) for k in keys)):
        return None
    return {"interaction": "simple_door", **{k: row[k] for k in keys}}


def _kinds(values: Any) -> tuple[str, ...]:
    return tuple(sorted({str(value).upper() for value in values or [] if str(value).strip()}))


def stats(row: dict[str, Any]) -> dict[str, Any]:
    """The numbers of one placed object. ``row`` is a map row: {"kind", "material", "size", "resilient", "ac", "hp", "threshold",
    "blocks", "unattended", "immune", "vulnerable", "resist", "name"}; anything it leaves out comes from its preset and the tables."""
    table = rules()
    preset = presets().get(str(row.get("kind") or ""), presets()["custom"])
    material = str(row.get("material") or preset["material"]).lower()
    size = str(row.get("size") or preset["size"]).lower()
    resilient = bool(preset.get("resilient", True) if row.get("resilient") is None else row.get("resilient"))
    ac = int(row["ac"]) if row.get("ac") else int(table["materials"].get(material, table["materials"]["wood"]))
    hp = int(row["hp"]) if row.get("hp") else int(table["sizes"].get(size, table["sizes"]["medium"])["resilient" if resilient else "fragile"])
    return {"kind": str(row.get("kind") or "custom"), "name": str(row.get("name") or preset["name"]), "material": material, "size": size,
            "resilient": resilient, "ac": ac, "hp": hp,
            "threshold": int(row["threshold"]) if row.get("threshold") else (int(preset["threshold"]) if preset.get("threshold") else None),
            "blocks": bool(preset.get("blocks") if row.get("blocks") is None else row.get("blocks")),
            "structure": bool(preset.get("structure")),
            "unattended": True if row.get("unattended") is None else bool(row.get("unattended")),
            "immune": _kinds([*table["immune"], *(row.get("immune") or [])]),
            "vulnerable": _kinds([*(preset.get("vulnerable") or []), *(row.get("vulnerable") or [])]),
            "resist": _kinds(row.get("resist")),
            "flammable": material in table["flammable"]}


def sight(kind: Any) -> dict[str, str]:
    """Sight shape and stroke kind of one placed object kind (owner 2026-10-23: "plus symbols should be default
    for most objects so you can see what the object is and it still blocks the sight").

    Every blocking object is seen through the shared centre plus: one horizontal and one vertical segment through
    the middle of each of its squares, so its art stays readable. A kind that really fills its square says
    ``"occluder": "cell"`` in combat/rules/objects.json (doors, gates, wall sections and the wall-like barriers) and
    keeps full-square sight. ``"sight": "door"`` marks the kinds that read as part of a wall line, so the table draws
    their rule stroke; everything else is scenery art. Display names are never read.
    """
    preset = presets().get(str(kind or ""), presets()["custom"])
    occluder = preset.get("occluder", "centerline")
    if occluder not in {"cell", "centerline"}:
        raise ValueError(f"Object sight shape must be cell or centerline: {kind}")
    return {"occluder": occluder, "sight_class": preset.get("sight", "object")}


def footprint(row: dict[str, Any]) -> str:
    """How much floor one placed object covers (objects.json "footprint_note"): "tiny", "small", "medium" or "large".
    A door, gate or window set in a wall fills its opening ("large"). Look and placement only; no rule reads it."""
    if row.get("mount_axis"):
        return "large"
    preset = presets().get(str(row.get("kind") or ""), presets()["custom"])
    size = str(row.get("size") or preset["size"]).lower()
    if preset.get("footprint") and size == preset["size"]:  # a placement that resizes the object resizes its footprint too
        size = preset["footprint"]
    return size if size in rules()["footprint_fill"] else "medium"


def fill(row: dict[str, Any]) -> int:
    return int(rules()["footprint_fill"][footprint(row)])


def square_problem(rows: list[dict[str, Any]]) -> str | None:
    """Why these objects cannot all stand in one 5-foot square, in plain words, or None when they fit."""
    capacity = int(rules()["square_capacity"])
    if len(rows) < 2 or sum(fill(row) for row in rows) <= capacity:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        name = stats(row)["name"].lower()
        counts[name] = counts.get(name, 0) + 1
    names = [name if count == 1 else f"{count} {name if name.endswith('s') else name + 's'}" for name, count in counts.items()]
    listed = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
    return (f"Too much in one 5-foot square ({listed}). A square holds up to 4 tiny objects, 2 small ones, 1 small and 2 tiny, "
            "or 1 medium or large object on its own. Move one to another square.")


def editor_defaults() -> dict[str, Any]:
    """Durability lookup for map previews, resolved by the table's own stats function.

    Keep resolution in Python: the client selects a preset and optional material,
    size and sturdiness entries, then applies placement HP/AC overrides.
    """
    return {
        "presets": {kind: {**{key: value for key, value in stats({"kind": kind}).items()
                              if key in ("hp", "ac", "size", "resilient", "threshold")},
                           "footprint": footprint({"kind": kind}), "sight": sight(kind),
                           "blocks": bool(preset.get("blocks")),
                           "name": preset["name"], "description": preset.get("description", ""), "group": preset.get("group", "decor")}
                    for kind, preset in presets().items()},
        "materials": {material: stats({"material": material})["ac"] for material in rules()["materials"]},
        "sizes": {size: {str(int(resilient)): stats({"size": size, "resilient": resilient})["hp"]
                         for resilient in (False, True)} for size in rules()["sizes"]},
        "groups": rules().get("groups", {}),
        "footprint_fill": dict(rules()["footprint_fill"]),
        "square_capacity": int(rules()["square_capacity"]),
    }


def label(obj: Any) -> str:
    """Its name on the table and in the log."""
    return str((getattr(obj, "component", None) or {}).get("name") or str(getattr(obj, "object_kind", "") or "Object").replace("_", " ").title())


def has_tag(obj: Any, tag: str) -> bool:
    """A word an ability's text names: "wooden", "stone", "structure", "unattended", "barrier", ...."""
    component = getattr(obj, "component", None) or {}
    tag = tag.lower()
    if tag == "unattended":
        return bool(obj.unattended)
    if tag == "wooden":
        return component.get("material") == "wood"
    if tag == "structure":
        return bool(component.get("structure"))
    if tag == "flammable":
        return bool(obj.flammable)
    if tag == "fragile":  # Explicit map classification takes precedence over the brittle-material fallback.
        if isinstance(component.get("fragile"), bool):
            return component["fragile"]
        return component.get("material") in ("glass", "crystal", "ice")
    if isinstance(component.get(tag), bool):
        return component[tag]
    return component.get("material") == tag or component.get("kind") == tag or getattr(obj, "object_kind", None) == tag


def work_out(packets: list[tuple[int, str]], obj: Any, *, ignore_threshold: bool = False, reduce_threshold: int = 0,
             ignore_resistance: bool = False, multiplier: int = 1, ignore_resistance_types: tuple[str, ...] = (),
             extra_resist_types: tuple[str, ...] = (), extra_vulnerable_types: tuple[str, ...] = ()) -> dict[str, Any]:
    """What one instance of damage (its packets, ``(amount, TYPE)``) does to the object, in the order above. Returns
    {"total": hit points lost, "notes": plain-word reasons, "packets": [(amount taken, TYPE)]}.

    ``extra_resist_types`` is the general seam for a Resistance that is not the object's own material
    (combat/ext/objects.deal collects it from the ``object_damage_defenses`` plug-in hook, e.g. Stand Against the
    Calamity's "structures inside gain Resistance to all damage"). Those types share this function's ordinary
    resistance: the same halving, the same rounding down, the same plain-word note, and the same suppression by
    ``ignore_resistance`` / ``ignore_resistance_types``. No plug-in special case lives here."""
    # Projected Vulnerability shares native doubling, after threshold/immunity,
    # and never modifies the object material or persisted component.
    component = getattr(obj, "component", None) or {}
    notes: list[str] = []
    instance = sum(max(0, int(amount)) for amount, _kind in packets)
    threshold = getattr(obj, "damage_threshold", None)
    if threshold and not ignore_threshold:
        effective = max(0, int(threshold) - max(0, int(reduce_threshold)))
        if effective != int(threshold):
            notes.append(f"Damage Threshold {threshold} cut to {effective} for this attack")
        if instance < effective:
            return {"total": 0, "packets": [], "notes": [*notes, f"{instance} damage is under its Damage Threshold of {effective}: no effect"]}
    elif threshold and ignore_threshold:
        notes.append(f"ignored its Damage Threshold of {threshold}")
    immune, vulnerable = set(getattr(obj, "damage_immunities", ()) or ()), {str(kind).upper() for kind in component.get("vulnerable") or []}
    vulnerable |= {str(kind).upper() for kind in extra_vulnerable_types}
    resist = {str(kind).upper() for kind in component.get("resist") or []} | {str(kind).upper() for kind in extra_resist_types or ()}
    taken: list[tuple[int, str]] = []
    for amount, kind in packets:
        kind = str(kind).upper()
        amount = max(0, int(amount))
        if kind in immune:
            if amount:
                notes.append(f"immune to {kind.lower()} damage")
            continue
        if kind in resist and not ignore_resistance and kind not in ignore_resistance_types:
            amount //= 2
            notes.append(f"resists {kind.lower()} damage")
        if kind in vulnerable:
            amount *= 2
            notes.append(f"vulnerable to {kind.lower()} damage")
        taken.append((amount, kind))
    if multiplier > 1 and any(amount for amount, _kind in taken):
        taken = [(amount * multiplier, kind) for amount, kind in taken]
        notes.append("double damage" if multiplier == 2 else f"x{multiplier} damage")
    return {"total": sum(amount for amount, _kind in taken), "packets": taken, "notes": notes}
