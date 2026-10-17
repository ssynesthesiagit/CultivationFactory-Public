"""Boundary Walker (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "17. Boundary Walker"). No Spheres 5e or D&D 5.5e counterpart.

What runs here: Walk the Border's "Opportunity Attacks against you have Disadvantage" -- while the user holds the Walk the Border
state (the typed ``state`` row of the ability, combat/ext/states.py), an Opportunity Attack declared against it (a Factory or a
native one: its source is an opportunity attack) is rolled with Disadvantage (the before_attack checkpoint, typed and legacy
paths). Inert for anyone without the state.

Not here (see the lane report): everything that needs a meaningful threshold on the map (Threshold Step, Mark the Door, Deny
Passage, Border Strike) -- the map does not model doors, gates, ward edges and which side of them a square is on -- and Gate of No
Return's exile (the engine has no temporary removal from the battlefield: an off-map primary combatant counts as defeated).
"""

from __future__ import annotations

from typing import Any

from . import hook

WALK_THE_BORDER = "walk_the_border"


@hook("before_attack")
def border_blurs_opportunity(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if defender is None or "opportunity" not in str(context.get("source_id") or "").lower():
        return None
    from . import states

    if states.active(engine, defender, WALK_THE_BORDER) is None:
        return None
    return {"mode": "DISADVANTAGE"}
