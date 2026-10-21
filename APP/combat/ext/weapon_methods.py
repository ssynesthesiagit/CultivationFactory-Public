"""Breaking Method, built once from the owner's weapon-method data.

Used by combat/ext/weapons_sphere.py (``weapon_method_breaking`` builds the effect it hands the shared Weapon
Method execution, and Iron Against Iron recognises the same effect among the methods a hit actually ran) and by
the tests that assert on either. The method itself is not defined here: ``combat/rules/weapon_specials.json``
``weapon_methods.Breaking`` is the owner's row ("Add your proficiency bonus to the damage", ``<weapon_damage_type>``),
the same entry ``combat/factory_compiler.py`` reads for the weapon's own "+ Breaking" button. Editing that data
therefore changes ordinary Breaking, Break the Guard's paid use and Weapon-Breaking Retort together, and the
detector keeps recognising it, because both ask these functions for the same row.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

BREAKING = "Breaking"
DAMAGE_TYPE_TOKEN = "<weapon_damage_type>"
RULES = Path(__file__).resolve().parents[1] / "rules" / "weapon_specials.json"
_CACHE: dict[str, Any] = {}


def _weapon_file() -> dict[str, Any]:
    """combat/rules/weapon_specials.json, re-read when the owner edits it (as factory_compiler does for itself).

    Read whole, because the Weapon Methods live beside the weapon catalogue in the same file; the compiler's
    ``weapon_specials()`` returns only the ``weapons`` section.
    """
    mtime = RULES.stat().st_mtime_ns if RULES.exists() else None
    if _CACHE.get("mtime") != mtime:
        _CACHE.update(mtime=mtime, data=json.loads(RULES.read_text(encoding="utf-8")) if mtime is not None else {})
    return _CACHE["data"]


def breaking_method() -> dict[str, Any]:
    """The owner's Breaking Method as the weapon data holds it (no effects when that entry is missing)."""
    row = (_weapon_file().get("weapon_methods") or {}).get(BREAKING) or {}
    return copy.deepcopy(row)


def damage_types_of(weapon: dict[str, Any] | None) -> list[str]:
    """The damage types this hit's own weapon deals, upper-cased, in the data's own spelling."""
    weapon = weapon or {}
    kinds = weapon.get("damage_types") or ([weapon.get("damage_type")] if weapon.get("damage_type") else [])
    return [str(kind).strip().upper() for kind in kinds if str(kind or "").strip()]


def breaking_effects(damage_types: list[str], evidence: str | None = None) -> list[dict[str, Any]]:
    """The owner's Breaking effects for a weapon dealing ``damage_types``, ``<weapon_damage_type>`` filled in.

    Filled exactly as combat/factory_compiler.py fills it when it builds the weapon's own "+ Breaking" button,
    so the two are the same row. ``evidence`` (the rider's own printed sentence) is attached to the damage row.
    """
    kinds = damage_types_of({"damage_types": damage_types}) or ["UNTYPED"]
    effects = []
    for effect in breaking_method().get("effects") or []:
        if not isinstance(effect, dict):
            continue
        listed = [str(kind) for kind in effect.get("damage_types") or []]
        row = {**effect, "damage_types": kinds if DAMAGE_TYPE_TOKEN in listed else listed}
        if evidence and "evidence" not in row:
            row["evidence"] = evidence
        effects.append(row)
    return effects


def _plain(effect: Any) -> dict[str, Any]:
    """One effect without the prose a rider attached to it, so a row built here matches the compiler's."""
    return {key: value for key, value in dict(effect or {}).items() if key != "evidence"}


def used_breaking(effects: list[dict[str, Any]] | None, damage_types: list[str]) -> bool:
    """Whether these executed Weapon Method effects include Breaking Method for a weapon dealing ``damage_types``.

    Read against the owner's own row rather than repeating what Breaking says, so it follows an edit to
    combat/rules/weapon_specials.json. ``damage_types`` empty (a bare attack) answers False: a Weapon Method
    always names ``<weapon_damage_type>``. A weapon offering two damage types is matched against the compiler's
    per-type row as well as the whole list.
    """
    kinds = damage_types_of({"damage_types": damage_types})
    if not kinds:
        return False
    candidates = [breaking_effects([kind]) for kind in kinds]
    if len(kinds) > 1:
        candidates.append(breaking_effects(kinds))
    rows = [_plain(row) for row in effects or [] if isinstance(row, dict)]
    return any(_plain(effect) in rows for candidate in candidates for effect in candidate)