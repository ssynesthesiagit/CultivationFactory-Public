"""Wondrous equipment shared by the compiler and table loadout."""

from .ability_scores import base_scores, effective_score


def given_item_key(index, item):
    """Retain an item's inventory key when earlier belongings are left behind."""
    return (item or {}).get("_equipment_key") or f"given.{index}"


def wondrous_equipment(kit, owner_items):
    """Stable inventory keys and carried treasure records, from either acquisition path."""
    purchases = kit.get("resolved_treasure_purchases") or {}
    for index, row in enumerate(purchases.get("wondrous") or []):
        if isinstance(row, dict) and not row.get("_left"):
            yield f"wondrous.{index}", row
    for index, item in enumerate(owner_items or []):
        if (item or {}).get("kind") == "wondrous":
            yield given_item_key(index, item), item["record"]


def project_ability_equipment(sheet, treasures, worn):
    """Project immediate combat statistics, leaving the underlying build unchanged."""
    bonuses = {}
    for key, row in treasures:
        bonus = row.get("ability_enhancement")
        if key in worn and bonus:
            bonuses.setdefault(bonus["ability"], []).append(bonus["bonus"])
    if not bonuses:
        return sheet
    base = base_scores(sheet)
    scores = {ability: effective_score(score, bonuses.get(ability, ())) for ability, score in base.items()}
    if scores == base:
        return sheet
    from .table_advance import recompute_from_abilities

    return recompute_from_abilities(sheet, base, scores, equipment=True)
