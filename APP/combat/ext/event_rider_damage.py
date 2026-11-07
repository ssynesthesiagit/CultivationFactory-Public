"""Shared GM fallback for event-origin damage awaiting consumer qualification.

Lightning Chains and timed damage states still use this path while their damage
and downstream consequences are unqualified. Black Sun now uses native damage
with bounded nested dispatch, so it no longer calls this helper.
"""
from typing import Any
from . import effect


def defer_damage(engine: Any, source: str, owner: str, subject: Any, description: str) -> None:
    action = engine.action_catalog.get(source)
    if action is None:
        action = next((a for a in engine.action_catalog.values()
                       if source in {str(((a.parameters or {}).get("typed") or {}).get("source") or ""),
                                     str(((a.parameters or {}).get("typed") or {}).get("option_of") or "")}), None)
    name = action.display_name if action is not None else "Triggered ability"
    engine._append_event("GM_RIDER", source, actor_id=owner, target_ids=(subject.entity_id,),
                         payload={"rider": f"{name}: GM resolves {description} on {subject.display_name}, including "
                                           "damage reactions and damage-triggered riders. Automation deferred: locked nested-event delivery."})


def run_event_effects(ctx: Any, rows: list[dict[str, Any]]) -> None:
    """Run event-origin rows with unqualified damage leaves replaced by GM notices."""
    from .. import typed_executor as te

    def transform(value):
        if isinstance(value, list):
            return [transform(item) for item in value]
        if isinstance(value, dict):
            if value.get("type") in {"damage", "half_damage", "arc_damage"}:
                return {"type": "rider_deferred_event_damage", "original": value}
            return {key: transform(item) for key, item in value.items()}
        return value
    te.run_effects(ctx, transform(rows))


@effect("rider_deferred_event_damage")
def deferred(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te
    original = spec["original"]
    dice = te._effect_dice(ctx, original) or {}
    count = int(dice.get("count") or 0)
    flat = int(original.get("flat") or 0) + ctx.formula(original.get("formula")) + int(dice.get("bonus") or 0) + ctx.formula(dice.get("bonus_formula"))
    expression = f"{count}d{int(dice.get('sides') or 0)} + {flat}" if count else str(flat)
    kinds = "/".join(original.get("damage_types") or ["printed"])
    for subject in te._default_subject(ctx, original, harmful=True):
        defer_damage(ctx.engine, ctx.source, ctx.actor.entity_id, subject, f"{expression} {kinds} damage")
