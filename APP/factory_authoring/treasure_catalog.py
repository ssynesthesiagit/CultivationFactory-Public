"""Wondrous Treasures (Item Book Ch. 4) and consumables (Ch. 5) bought from the treasure budget.

One budget per character (draft §4): CL treasure budget x Background wealth
tier.  The signature weapon is bought first, then the Path's armour; a tenth of
the budget is kept for consumables and the rest buys Wondrous Treasures.  Only
one treasure may sit at the Realm's signature grade, and the weapon, the armour
and the Wondrous Treasures together fit the character's four Attunement slots.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from app.core import FoundryError

APP_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = "authority/Tianxia_Treasure_Catalog_Authority_R1.json"
AUTHORITY_SHA256 = "d4996083324fc04b196484935dfd3314748806f21337036947e71d460939ec6b"
CONSUMABLE_SHARE = 0.1
ATTUNEMENT_SLOTS = 4
MAX_WONDROUS = 4
MAX_CONSUMABLE_BATCHES = 4


def _invalid(message: str, **details: Any) -> FoundryError:
    return FoundryError("TREASURE_CATALOG_INVALID", message, details=details or None)


@lru_cache(maxsize=1)
def authority() -> dict[str, Any]:
    path = APP_ROOT / AUTHORITY_PATH
    if path.is_symlink() or not path.is_file():
        raise _invalid("The treasure catalog authority file is missing.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != AUTHORITY_SHA256:
        raise _invalid("The treasure catalog authority does not match its pin.")
    return json.loads(data.decode("utf-8"))


def _by_id(kind: str, key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in authority()[kind]}


def treasure_plan(target_cl: int, background_id: str, path_id: str) -> dict[str, Any] | None:
    """How the budget splits for this character, or None below the first treasure CL."""
    from factory_authoring.treasure_armor import armor_grade, chassis_options
    from factory_authoring.treasure_weapons import weapon_grade

    weapon = weapon_grade(target_cl, background_id)
    if weapon is None:
        return None
    armor = armor_grade(target_cl, background_id) if chassis_options(path_id) else None
    budget = weapon["budget_gt"]
    consumable_budget = round(budget * CONSUMABLE_SHARE, 2)
    spent = weapon["appraisal_gt"] + (armor["appraisal_gt"] if armor else 0)
    cap = weapon["realm_cap"]
    return {
        "budget_gt": budget,
        "realm_cap": cap,
        "weapon_grade": weapon["grade"],
        "armor_grade": armor["grade"] if armor else None,
        "signature_used": weapon["grade"] == cap or bool(armor and armor["grade"] == cap),
        "attunement_used": 1 + (1 if armor else 0),
        "wondrous_budget_gt": round(max(0.0, budget - spent - consumable_budget), 2),
        "consumable_budget_gt": consumable_budget,
    }


def wondrous_options(plan: dict[str, Any], chosen_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Wondrous Treasures still affordable, below the signature grade if it is taken, and attunable."""
    if len(chosen_ids) >= MAX_WONDROUS:
        return []
    rows = _by_id("wondrous", "treasure_id")
    chosen = [rows[value] for value in chosen_ids]
    order = authority()["grade_order"]
    cap = plan["realm_cap"]
    signature = plan["signature_used"] or any(row["grade"] == cap for row in chosen)
    remaining = plan["wondrous_budget_gt"] - sum(row["value_gt"] for row in chosen)
    slots = ATTUNEMENT_SLOTS - plan["attunement_used"] - sum(row["attunement_slots"] for row in chosen)
    return [
        row for row in authority()["wondrous"]
        if row["treasure_id"] not in chosen_ids
        and row["value_gt"] <= remaining
        and row["attunement_slots"] <= slots
        and order.index(row["grade"]) <= order.index(cap)
        and not (signature and row["grade"] == cap)
    ]


def consumable_options(plan: dict[str, Any], chosen_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Consumable batches still affordable at or below the Realm's grade."""
    if len(chosen_ids) >= MAX_CONSUMABLE_BATCHES:
        return []
    rows = _by_id("consumables", "consumable_id")
    order = authority()["grade_order"]
    remaining = plan["consumable_budget_gt"] - sum(rows[value]["batch_price_gt"] for value in chosen_ids)
    return [
        row for row in authority()["consumables"]
        if row["consumable_id"] not in chosen_ids
        and row["batch_price_gt"] <= remaining
        and order.index(row["grade"]) <= order.index(plan["realm_cap"])
    ]


def resolve_treasure_catalog(
    *,
    target_cl: int,
    background_id: str,
    path_id: str,
    wondrous_ids: Sequence[str],
    consumable_ids: Sequence[str],
) -> dict[str, Any]:
    """Validate the purchases in order and compile the Wondrous Treasures and consumable batches."""
    plan = treasure_plan(target_cl, background_id, path_id)
    if plan is None:
        raise _invalid("This character has no treasure budget at its CL.", target_cl=target_cl)
    for kind, ids, options, key in (
        ("wondrous", wondrous_ids, wondrous_options, "treasure_id"),
        ("consumable", consumable_ids, consumable_options, "consumable_id"),
    ):
        chosen: list[str] = []
        for value in ids:
            if value not in {row[key] for row in options(plan, chosen)}:
                raise _invalid(f"A {kind} purchase is not legal within the treasure budget.", id=value)
            chosen.append(value)
    wondrous = [_by_id("wondrous", "treasure_id")[value] for value in wondrous_ids]
    consumables = [_by_id("consumables", "consumable_id")[value] for value in consumable_ids]
    return {
        "schema_version": "TianxiaFoundry.ResolvedTreasureCatalogPurchases.v1",
        "plan": plan,
        "wondrous": [
            {key: row[key] for key in ("treasure_id", "name", "item_type", "grade", "attunement_slots", "family", "value_gt", "text")}
            for row in wondrous
        ],
        "consumables": [
            {key: row[key] for key in ("consumable_id", "name", "family", "grade", "activation", "batch_quantity", "batch_unit", "batch_price_gt", "text")}
            for row in consumables
        ],
        "wondrous_value_gt": sum(row["value_gt"] for row in wondrous),
        "consumable_value_gt": sum(row["batch_price_gt"] for row in consumables),
        "authority_sha256": AUTHORITY_SHA256,
    }
