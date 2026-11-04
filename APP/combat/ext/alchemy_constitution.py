"""Alchemical Constitution (Tianxia Insight): Advantage on saving
throws against Poison and alchemical backlash.

The printed advantage rides two engine routes, so it covers every
saving throw the table actually rolls against them:

* a save a typed ability forces -- the general ``defense`` row the
  feature block compiles (combat/rules/feature_blocks.d/
  a2_group_insights_1_residual.json), which pressure.save_advantage
  reads exactly as it reads legacy-tempered-organs' Poison save
  Advantage: the save's named set holds the Poisoned condition, the
  fixed Poison damage type, or a ``category:`` tag a producer
  classified (``save_categories``).
* a creature's own repeat save against a condition it still bears
  (combat/gate2_engine.py ``resolve_repeat_save`` rolls through
  ``_roll_save``, which asks the documented ``save_mode`` hook):
  the Poisoned condition's end-of-turn save is a saving throw
  against Poison too, so this plug-in answers ADVANTAGE for it.

Alchemical backlash itself is a failed-Alchemy-Check crafting hazard
(Sphere Compendium: "Natural 1. The ingredients are lost and you
suffer backlash. Take 1d6 Fire, Poison, Acid, or Force damage per
rarity tier"), rolled between Full Cultivation Sessions. No combat
save producer classifies one, so the ``category:alchemical_backlash``
name this Insight's row carries stays provenance-complete and inert
until a producer tags it; no save is broadened.

A character without the Insight owns no row, so the hook returns
early and every other creature's saves behave exactly as before.
"""
from __future__ import annotations

from typing import Any

from . import hook

INSIGHT = "insight.alchemical-constitution"

# The names a save against Poison carries: the Poisoned condition,
# fixed Poison damage, and the classified categories (a producer's
# save_categories tag). "Alchemical backlash" keeps its own name and
# its classified form, so a producer that classifies one qualifies.
AGAINST = frozenset({
    "poisoned", "poison", "damage:poison",
    "category:poison", "category:poisoned", "category:damage:poison",
    "alchemical_backlash", "category:alchemical_backlash",
})


def owned(engine: Any, actor: Any) -> bool:
    return any(row.get("feature_id") == INSIGHT
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ()))


@hook("save_mode")
def poison_backlash_advantage(engine: Any, subject: Any, ability: str, dc: int,
                              source_id: str, context: dict[str, Any]) -> str | None:
    """Advantage on a save against Poison (or a classified backlash):
    the save's named set -- the conditions and consequence tags the
    save is about -- names one of them."""
    if subject is None or not owned(engine, subject):
        return None
    named = {str(value).lower() for value in (context.get("named") or ())}
    return "ADVANTAGE" if named & AGAINST else None
