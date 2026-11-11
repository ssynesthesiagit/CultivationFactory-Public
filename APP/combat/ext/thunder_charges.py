"""Adamant Thunderbolt Body's Thunder Charge record (rider lane C7, 2026-09-30).

Printed record (Body Refining Subpath Compendium, "Thunder Charges"): maximum equals Proficiency Bonus, "Gain no more than 1
per round" -- the normal gain limit is one total Charge per round across all normal triggers; a Charge a feature says "can
exceed the normal gain limit" (Thunder Runs Through Bone) ignores the round limit but never the maximum.

Public helper (shared by the Adamant Thunderbolt features; no other module's private state is read):
  melee_attack(ctx) -> bool
      whether the typed attack now resolving (ctx.attack_effect) is a melee attack (also used by flesh_crucible.py).
  gain(engine, actor, source, *, normal=True) -> bool
      adds one Thunder Charge through combat/ext/subpath_pools.gain (maximum PB; a normal gain is once per round across
      every trigger, recorded as an integer turn flag that survives commit/reload). Returns whether a Charge was stored.

Miss generation belongs to unbroken_bolt.py for native and typed attacks. The helpers here are used by C7's other Thunder
Charge features and honor that same journal-based normal gain limit.
"""

from __future__ import annotations

from typing import Any

RESOURCE = "resource:named.thunder_charge"
BLOCK = "path_rider"


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def gain(engine: Any, actor: Any, source: str, *, normal: bool = True) -> bool:
    """One Thunder Charge through the shared Subpath pool rules (combat/ext/subpath_pools.py: maximum PB, one normal gain a round)."""
    from .subpath_pools import gain as pool_gain
    from .unbroken_bolt import owns, normal_gain_used

    if normal and owns(engine, actor) and normal_gain_used(engine, actor):
        return False
    return bool(pool_gain(engine, actor, RESOURCE, source, normal=normal))


_MELEE_KINDS = {"unarmed", "cultivation_melee", "melee", "melee weapon", "natural_weapon", "saber"}


def melee_attack(ctx: Any) -> bool:
    """Whether the typed attack now resolving is a melee attack: its kind says so, or it is a weapon/other attack aimed
    within 5 feet or through a Reach weapon (a thrown or ranged kind never is)."""
    from ..typed_executor import ranged_attack_now

    kind = str((ctx.attack_effect or {}).get("attack_kind") or "").lower()
    if "ranged" in kind or "thrown" in kind:
        return False
    if kind in _MELEE_KINDS:
        return True
    return not ranged_attack_now(ctx) or "reach" in str((ctx.typed.get("weapon") or {}).get("properties") or "").lower()


# Miss generation is owned by unbroken_bolt.py for both native and typed attacks.
