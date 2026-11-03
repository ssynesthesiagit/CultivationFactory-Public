"""Effects declared in response to a technique but applied after it resolves.

``after_technique`` wraps ``effects``. During a technique declaration it records those rows, the reactor's numbers, and
the triggering intent on an evented condition on the technique user. ``technique_used`` consumes the condition after
that exact use finishes. It never treats a subsequent use as completion of a countered technique. Without a pending
technique (ordinary movement/healing/attack checkpoints), the rows run immediately.

Yang's Force the Rising explicitly marks after the triggering event, and Meridian Overcompletion explicitly does not
interrupt it. This extension keeps those effects out of the pending technique's saves and damage.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

PREFIX = "condition:typed.after_technique."


@effect("after_technique")
def defer(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    pending = getattr(ctx.engine, "_typed_pending_technique", None) or {}
    if not pending or ctx.target is None or pending.get("actor") != ctx.target.entity_id:
        run_effects(ctx, row.get("effects") or [])
        return
    intent = ctx.intent or getattr(ctx.engine, "_active_intent", None)
    if intent is None:
        # A direct declaration callback is not evidence that the technique completed.
        return
    condition_id = PREFIX + str(ctx.engine.state.event_sequence + 1)
    ctx.engine._apply_condition(ctx.target, condition_id, ctx.source, ctx.actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"intent_id": intent.intent_id, "effects": copy.deepcopy(row.get("effects") or []),
                                      "numbers": dict(ctx.numbers)})


@hook("technique_used")
def finish(ctx: Any) -> None:
    from ..typed_executor import run_effects
    from ..typed_reactions import _generic_context

    for held in list(ctx.actor.conditions.values()):
        if not held.condition_id.startswith(PREFIX) or (held.data or {}).get("intent_id") != getattr(ctx.intent, "intent_id", None):
            continue
        data = held.data or {}
        owner = ctx.engine.state.actors.get(held.source_actor_id)
        ctx.engine._remove_condition(ctx.actor, held.condition_id, "system:after_technique.completed")
        if owner is None or not owner.active:
            continue
        inner = _generic_context(ctx.engine, owner, ctx.actor, {"feature_id": held.source_definition_id,
                                  "effects": data.get("effects") or [], "numbers": data.get("numbers") or {}}, ctx.intent)
        run_effects(inner, data.get("effects") or [])
