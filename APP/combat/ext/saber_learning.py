"""Saber-Line Method's durable learning choice and explicit weapon adjudication.

Uses table advancement's public learning hooks. Catalog IDs, never labels or
damage types, identify weapons. The printed examples already present in the
weapon authority qualify; other catalog weapons remain unknown until the local
GM explicitly adjudicates them. Source fingerprints invalidate stale rulings.
No item ownership or extra talent is granted by a profile permission.
"""
from __future__ import annotations

import copy
from typing import Any

from . import hook
from ..canonical import canonical_sha256
from ..tabletop import TabletopError
from factory_authoring.starting_kits import item_definition

METHOD = "SABERS_BASE_SABER_LINE_METHOD"
PREFIX = "tianxia.mortal.weapon."
PRINTED = {PREFIX + name for name in ("dao", "duan_dao", "hu_die_dao")}


def owns(sheet: dict[str, Any]) -> bool:
    from ..table_advance import known
    return METHOD in known(sheet)["talents"]


def weapon_stamp(item_id: str) -> str:
    item = item_definition(item_id)
    return canonical_sha256(item) if item and item_id.startswith(PREFIX) else ""


def saber_qualification(sheet: dict[str, Any], item_id: str) -> str:
    """Public exact-source query: saber, another adjudicated sphere, or unknown."""
    stamp = weapon_stamp(item_id)
    if not stamp:
        return "unknown"
    if item_id in PRINTED:
        return "sabers"
    for row in reversed(sheet.get("weapon_rulings") or []):
        if row.get("item_id") == item_id and row.get("item_sha256") == stamp and row.get("principal"):
            return str(row.get("sphere") or "unknown")
    return "unknown"


@hook("learning_options")
def learning_options(sheet: dict[str, Any]) -> list[dict[str, Any]] | None:
    if not owns(sheet):
        return None
    # Public catalog query; include every qualified item, carried or otherwise.
    from factory_authoring.starting_kits import _authorities
    selected = next((row for row in sheet.get("learning_choices") or [] if row.get("source_id") == METHOD), None)
    catalog = _authorities()[1]
    weapons = [{"item_id": key, "name": row["name"], "qualification": saber_qualification(sheet, key)}
               for key, row in catalog.items() if key.startswith(PREFIX)]
    notice = "" if selected else ("You have not chosen your Saber-Line Method weapon yet, so it gives you no proficiency. "
                                  "Choose one qualifying saber below. Choosing does not give you the weapon.")
    return [{"source_id": METHOD, "name": "Saber-Line Method", "selected": selected, "notice": notice,
             "description": "Choose one qualifying weapon to learn proficiency with, at no cost. This permanent learning choice does not give you the weapon. Sabers talents can use any qualifying saber you actually wield.",
             "options": [row for row in weapons if row["qualification"] == "sabers"],
             # Every non-printed weapon whose ruling is still unsealed stays correctable, whether it is
             # unknown, GM-ruled as Sabers, or GM-ruled as another sphere, so a mistaken classification can
             # be fixed. Printed examples never change, and a learned weapon seals its ruling and is omitted.
             "ambiguous": [row for row in weapons
                           if row["item_id"] not in PRINTED and
                           not any(choice.get("source_id") == METHOD and choice.get("item_id") == row["item_id"]
                                   for choice in sheet.get("learning_choices") or [])]}]


@hook("learning_select")
def select(info: dict[str, Any]) -> dict[str, Any] | None:
    if info["source_id"] != METHOD:
        return None
    sheet, item_id = info["sheet"], info["item_id"]
    if not owns(sheet):
        raise TabletopError("TABLETOP_LEARNING_NOT_OWNED", "Learn Sabers before choosing Saber-Line Method's weapon.", 409)
    stamp = weapon_stamp(item_id)
    if not stamp:
        raise TabletopError("TABLETOP_WEAPON_UNKNOWN", "Choose a weapon from the source catalog.", 400)
    saved = copy.deepcopy(info["saved"])
    sphere = info["gm_sphere"]
    if sphere:
        from ..table_advance import now
        if not info["gm"]:
            raise TabletopError("TABLETOP_GM_REQUIRED", "Only an explicit local GM decision can classify an ambiguous blade.", 403)
        if item_id in PRINTED or sphere not in {"sabers", "sword", "weapons", "axes", "other"}:
            raise TabletopError("TABLETOP_WEAPON_RULING_INVALID", "Choose a weapon sphere for an ambiguous weapon; printed saber examples already qualify.", 400)
        if any(row.get("item_id") == item_id for row in sheet.get("learning_choices") or []):
            raise TabletopError("TABLETOP_LEARNING_SEALED", "This weapon's qualification is sealed by a learning choice.", 409)
        saved["weapon_rulings"] = [row for row in saved["weapon_rulings"] if row.get("item_id") != item_id]
        saved["weapon_rulings"].append({"item_id": item_id, "item_sha256": stamp,
            "sphere": sphere, "principal": info["principal"], "at": now()})
        return saved
    if any(row.get("source_id") == METHOD for row in sheet.get("learning_choices") or []):
        raise TabletopError("TABLETOP_LEARNING_SEALED", "Saber-Line Method's weapon was already chosen when learned.", 409)
    if saber_qualification(sheet, item_id) != "sabers":
        raise TabletopError("TABLETOP_WEAPON_NOT_QUALIFIED", "This weapon has not been approved as a saber-profile weapon. Ask the GM to decide its sphere.", 409)
    saved["learning_choices"].append({"source_id": METHOD, "item_id": item_id, "item_sha256": stamp})
    return saved


@hook("weapon_proficiency_grant")
def proficiency(info: dict[str, Any]) -> list[str] | None:
    if info["source_id"] != METHOD or not owns(info["owner_sheet"]):
        return None
    sheet = info["owner_sheet"]
    choices = [row for row in sheet.get("learning_choices") or [] if row.get("source_id") == METHOD]
    if len(choices) != 1:
        return []
    row = choices[0]
    item_id = str(row.get("item_id") or "")
    return [item_id] if row.get("item_sha256") == weapon_stamp(item_id) and saber_qualification(sheet, item_id) == "sabers" else []


@hook("compile_weapon_traits")
def seal_profile(info: dict[str, Any]) -> dict[str, Any] | None:
    if METHOD not in info["owned_ids"]:
        return None
    return {"saber_profile": saber_qualification(info["owner_sheet"], info["weapon"]["item_id"])}


def saber_action(action: Any) -> bool:
    """Sabers-talent eligibility of one weapon action.

    A sealed profile (Saber-Line Method owners, via seal_profile) is authoritative; an unknown sealed profile
    never falls back to a name heuristic. A character without the Method has no sealed profile and keeps the
    eligibility that predates it: a printed example, or a weapon whose name holds a SABER_WORDS word
    (combat/ext/wenxue_sabers.py), so e.g. a Guandao Yanyuedao still works with Sabers talents.
    """
    typed = (action.parameters or {}).get("typed") or {}
    if not typed.get("weapon"):
        return False
    if "saber_profile" in typed:
        return typed["saber_profile"] == "sabers"
    from .wenxue_sabers import SABER_WORDS
    return typed.get("source") in PRINTED or any(word in str(action.display_name).lower() for word in SABER_WORDS)
