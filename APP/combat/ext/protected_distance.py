"""Explicit proximity limits relative to the creature a reaction protects."""

from typing import Any

from . import effect


@effect("if_near_protected")
def if_near_protected(ctx: Any, effect: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    protected = ctx.engine.state.actors.get(ctx.typed.get("protects")) or ctx.actor
    if ctx.target is not None and ctx.engine._distance_actor_to_actor(protected, ctx.target) <= int(effect["distance_ft"]):
        run_effects(ctx, effect.get("effects") or [])
