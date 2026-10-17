"""Shared weapon queries for docket_maneuvers, bodya_berserker and ice_fracture.

The maneuver compiler uses all eligible attacks; Advancing Carnage uses the first
melee/unarmed/natural entry. Preserve input order and return the original action,
typed payload and attack-effect references without mutating them. Classification
and exclusions describe the existing compiled-action contract, not new rules.
This module registers no hooks or effects and keeps no actor state.
"""
from __future__ import annotations

from typing import Any


def strike_identity(action: Any) -> str:
    """Persistent compiled weapon/natural/unarmed identity across delivery variants.

    Ice coatings use this identity rather than a delivery action. Compiler modifiers
    name their parent with variant_of/option_of; thrown, maneuver and offhand actions
    share the base action before '#'. Distinct weapons (including two copies of one
    item type) retain their distinct base IDs; never collapse by implement/item ID.
    This is a query only and does not change attack eligibility or targeting.
    """
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    source = typed.get('variant_of') or typed.get('option_of') or getattr(action, 'source_definition_id', '')
    return str(source).split('#', 1)[0]


def _kind(row: Any, typed: dict[str, Any], attack: dict[str, Any]) -> str:
    if ".natural." in row.source_definition_id:
        return "natural"
    if str(attack.get("attack_kind") or "") == "unarmed" or typed.get("unarmed_option"):
        return "unarmed"
    if row.source_definition_id.endswith("#thrown"):
        return "thrown"
    return "ranged" if int(typed.get("range_ft") or 0) > 5 else "melee"


def weapon_attacks(actions: list[Any], actor_id: str) -> list[tuple[Any, dict[str, Any], dict[str, Any], str]]:
    """Return owned base hostile ACTION attacks as (action, typed, attack, kind)."""
    out = []
    for row in actions:
        typed = (row.parameters or {}).get("typed") or {}
        economy = getattr(row.economy, "value", row.economy)
        attack = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
        base_id = row.source_definition_id.split("#")[0]
        if (row.owner_id != actor_id or economy != "ACTION" or row.target_kind != "HOSTILE_ENTITY" or attack is None or typed.get("variant_of")
                or ("#" in row.source_definition_id and not row.source_definition_id.endswith("#thrown"))
                or str(typed.get("source") or "").startswith("improvised") or not (typed.get("weapon") or typed.get("unarmed_option"))
                or row.parameters.get("requires_held_weapon") or base_id.endswith((".wall_attack",))):
            continue
        out.append((row, typed, attack, _kind(row, typed, attack)))
    return out
