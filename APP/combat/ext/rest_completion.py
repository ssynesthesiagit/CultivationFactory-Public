"""Verified rest-completion transport for source-owned effects.

This effect reports an already completed rest; it neither grants a rest during
combat nor decides whether elapsed time qualifies. Rest adapters may place it
in their authoritative typed action, which journals and replays the receipt.
"""
from . import effect, run_strict


@effect("rest_completed")
def rest_completed(ctx, eff):
    """Notify source-specific consumers after a verified short/long rest."""
    kind = str(eff.get("kind") or "")
    if kind not in ("short", "long"):
        raise ValueError("A completed rest must be short or long")
    rest_id = eff.get("rest_id")
    if not isinstance(rest_id, str) or not rest_id:
        raise ValueError("A completed rest needs its authoritative rest receipt id")
    key = f"_round_completed_rest:{kind}:{rest_id}"
    if ctx.actor.turn_flags.get(key) == 1:
        return  # Transport retries cannot clear immunity earned after that rest.
    ctx.actor.turn_flags[key] = 1
    # PASSIVE_TRIGGERED is a current-format receipt type. Keep the exact rest
    # marker in primitive payload fields instead of adding a locked reducer event.
    ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
                             payload={"rest_completed":1,"kind":kind,"rest_id":rest_id,
                                      "source_actor_id":ctx.actor.entity_id,
                                      "log":f"{ctx.actor.display_name} has completed a {kind} rest."})
    run_strict("rest_completed", ctx.engine, ctx.actor, kind)
