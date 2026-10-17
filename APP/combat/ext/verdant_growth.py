"""Verdant Growth riders (rider lane C2, 2026-09-30).  Rules text: the owner's Sphere Compendium, "Sphere of Verdant Growth".

Only the lines that do not need the sphere's chassis live here.  The chassis -- Living Claims, Growth Mark counting and the Verdant
Responses -- and the talents built on it are combat/ext/verdant_chassis.py (rider lane C16).

  Thousand-Root Prison  successful ``MOVEMENT_COMMITTED`` teleport: "If the target teleports, the roots tear away and the effect ends, but the target takes 4d10
                        Piercing damage" -- the teleport goes ahead; the Restrained the prison put on it ends and the roots deal the damage.
"""

from __future__ import annotations

from typing import Any

from . import hook

PRISON = "TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON"
HOLDS = ("condition:typed.restrained", "condition:typed.grappled")


@hook("event")
def prison_tears(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Tear once per prison only after movement succeeds; authorization is pure."""
    if event_type != "MOVEMENT_COMMITTED" or not (kwargs.get("payload") or {}).get("teleport"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None:
        return
    torn = set()
    for condition in list(actor.conditions.values()):
        if condition.condition_id not in HOLDS:
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        if (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) != PRISON:
            continue
        caster = engine.state.actors.get(condition.source_actor_id)
        engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)
        key = (condition.source_actor_id, condition.source_definition_id)
        if caster is None or key in torn:
            continue
        torn.add(key)
        from .. import typed_executor as te

        typed = {**((action.parameters or {}).get("typed") or {}), "effects": []}
        te.run_effects(te.Context(engine, caster, action, None, typed, [actor], actor, {}),
                       [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 10}, "damage_types": ["piercing"],
                         "evidence": "Thousand-Root Prison: the roots tear away as it teleports, 4d10 Piercing"}])
