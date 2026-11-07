"""Needle-Catching Reversal - Guard (lane 5, 2026-09-29): "When Parry and Riposte reduces the triggering attack's damage to 0,
regain Martial Focus after resolving the retaliatory attack."

The ``hit_absorbed`` hook (combat/ext/__init__.py; typed_reactions.on_damage) says when a hit-kind reaction has taken a melee
hit's damage down to 0 and which reactions reduced it. If Parry and Riposte was one of them, the fencer owning this talent
gets the Martial Focus back (one point, the amount Parry and Riposte spends), unless it already holds it.

Parry and Riposte's retaliatory attack is made by combat/ext/needle.py parry_riposte (task F 2026-09-29); it runs first, so the
Focus comes back after it is resolved.
Ownership at fight time is the "needle_catching" passive row (combat/rules/feature_blocks.d/auto_lane5.json).
"""

from __future__ import annotations

from typing import Any

from . import hook

PARRY_AND_RIPOSTE = "TAL_FENCING_PARRY_AND_RIPOSTE"
FOCUS = "resource:core.martial_focus"


@hook("compile_block")
def needle_catching_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "needle_catching"}] if block == "needle_catching" else None


@hook("hit_absorbed")
def needle_catching_reversal(engine: Any, target: Any, attacker: Any, reduced_by: list[str]) -> None:
    if not any(str(feature).split("#")[0] == PARRY_AND_RIPOSTE for feature in reduced_by or ()):
        return
    from .attack_reduction import follow_up_scope
    guard_source = next(str(f) for f in reduced_by if str(f).split("#")[0] == PARRY_AND_RIPOSTE)
    with follow_up_scope(engine, target, getattr(attacker, "entity_id", None), guard_source):
        from .needle import parry_riposte

        parry_riposte(engine, target, attacker, reduced_by)  # "regain Martial Focus after resolving the retaliatory attack": the riposte first
        if not any(row.get("block") == "needle_catching" for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])):
            return
        if FOCUS not in target.resources or target.resources.get(FOCUS, 0) >= 1:
            return  # no Martial Focus to regain (or it is already held: it is a one-point resource)
        engine._gain_resource(target, FOCUS, 1, "passive:TAL_FENCING_NEEDLE_CATCHING_REVERSAL")
        engine._append_event("PASSIVE_TRIGGERED", "passive:TAL_FENCING_NEEDLE_CATCHING_REVERSAL", actor_id=target.entity_id,
                             target_ids=(attacker.entity_id,) if attacker is not None else (),
                             payload={"trigger": f"Needle-Catching Reversal: Parry and Riposte took the hit to 0 damage, {target.display_name} regains Martial Focus."})
