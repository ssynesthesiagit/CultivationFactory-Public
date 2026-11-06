"""Shared compiled weapon queries for Needle Vacuum and One Opening variants.

Variants use the original melee Attack action only, never another variant.
"""
from typing import Any


def melee_weapon_attack(action: Any) -> bool:
    source = str(action.source_definition_id)
    typed = (action.parameters or {}).get("typed") or {}
    return (".weapon." in source and "#" not in source and typed.get("weapon") is not None and typed.get("range_ft") is None
            and any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []))
