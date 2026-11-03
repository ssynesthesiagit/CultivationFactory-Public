"""Numbers a hand-written combat block reads from its feature's typed record instead of keeping a second copy.

Owner 2026-09-30 (Qi Armor +3 -> +5): a number the owner changes in the printed text (authority/typed_mechanics/
owner_text_edits.json) is changed once and every consumer follows it. Used by:

- combat/typed_reactions.py ``compile_blocks``: a combat/rules/feature_blocks.json value written as "typed" (``ac`` of a
  hit_ac block; ``cost`` of a hit_ac, save_rescue or damage_reduction block);
- combat/character_runtime_adapter.py: the portable runtime's Qi Armor reaction parameters.

Each reader returns None when the record does not state the number exactly once (no record, no such effect, two different
values, a cost with alternatives), so a caller never guesses; tests/test_owner_text_edits.py checks every "typed" value in
feature_blocks resolves against the built authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AUTHORITY_PATH = Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
_CACHE: dict[str, Any] = {}


def authority_mechanics() -> dict[str, dict[str, Any]]:
    """The built typed authority's records (cached until the file changes)."""
    mtime = AUTHORITY_PATH.stat().st_mtime_ns if AUTHORITY_PATH.is_file() else None
    if _CACHE.get("mtime") != mtime:
        mechanics = (json.loads(AUTHORITY_PATH.read_text(encoding="utf-8")).get("mechanics") or {}) if mtime is not None else {}
        _CACHE.update(mtime=mtime, mechanics=mechanics)
    return _CACHE["mechanics"]


def ac_bonus(record: dict[str, Any] | None) -> int | None:
    """The flat AC bonus the ability gives its user: its top-level self ac_bonus effects, all stating the same number."""
    values = {effect.get("flat") for effect in (record or {}).get("effects") or []
              if isinstance(effect, dict) and effect.get("type") == "ac_bonus" and effect.get("applies_to", "self") == "self"}
    value = values.pop() if len(values) == 1 else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def cost(record: dict[str, Any] | None, resource: str) -> int | None:
    """The ability's printed cost in ``resource`` ("qi", "stamina"...): one way to pay, one amount of that resource."""
    alternatives = (record or {}).get("cost") or []
    if len(alternatives) != 1:
        return None
    parts = [part for part in alternatives[0] or [] if isinstance(part, dict) and str(part.get("resource") or "").lower() == resource.lower()]
    if len(parts) != 1 or parts[0].get("amount_formula"):
        return None
    amount = parts[0].get("amount")
    return amount if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0 else None


def typed_number(record: dict[str, Any] | None, field: str, *, resource: str = "") -> int | None:
    """``field`` of a feature block ("ac" or "cost") as the typed record states it; None when it does not state it once."""
    if field == "ac":
        return ac_bonus(record)
    if field == "cost":
        return cost(record, resource) if resource else None
    return None


def required_ac_reaction(record_id: str, resource: str) -> dict[str, int]:
    """Cost and AC for historical reaction profiles; fail closed on ambiguous authority.

    Legacy runtime content and its generated mechanics lock share this reader.
    Values come from the same built record used by Factory and portable fighters.
    """
    record = authority_mechanics().get(record_id)
    amount, bonus = cost(record, resource), ac_bonus(record)
    if amount is None or bonus is None:
        raise ValueError('The reaction needs a clear resource cost and Armor Class bonus in its rules.')
    return {'cost': amount, 'ac_bonus': bonus}
