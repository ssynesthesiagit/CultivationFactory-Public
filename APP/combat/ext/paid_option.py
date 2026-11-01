"""A talent that rides a reaction and costs something of its own (riders lane 2, 2026-09-29: Yang's Force Completion "Cost: 2 CP",
Furnace Backlash "Cost: 1 CP", The Action Becomes More Real, Radiant Overpressure ...).

A reaction that a named modifier changes (combat/factory_compiler._attach_reaction_modifiers) got the modifier's effects added to what it
does, and the modifier's own cost was never charged -- the printed "Cost: 2 CP" only appeared as a rider.  The compiler now wraps such a
modifier's effects in

    {"type": "paid_option", "talent": "<id>", "name": "<talent name>", "ways": [[{"resource_id": ..., "amount": n}, ...], ...],
     "effects": [...]}

``ways`` are the distinct ways the talent may be paid (a printed "2 CP or expend Martial Focus" is two): when the reaction fires, the
player can choose an affordable payment or decline through the extension choice transport. Without a choice provider, the first
affordable way is the automatic default. A user who cannot pay gets the reaction without the talent. Nothing is spent on decline.

Deterministic and evented: the payment is the engine's own ``_spend_resource``.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

CHOICE = "choice:paid_option."


@hook("choice_options")
def options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if not choice_id.startswith(CHOICE) or "payment_options" not in context:
        return None
    return {"option_ids": context["payment_options"], "minimum_selections": 1, "maximum_selections": 1,
            "allow_decline": True, "automatic_use": True}


@effect("paid_option")
def run(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    actor = ctx.actor
    affordable = {str(index): paid for index, paid in enumerate(row.get("ways") or [[]])
                  if all(actor.resources.get(part["resource_id"], 0) >= int(part["amount"]) for part in paid)}
    if not affordable:
        return
    talent = str(row.get("talent") or ctx.source)
    limit = row.get("limit")
    flag = f"paid_option_round:{talent}" if limit == "once_per_round" else f"paid_option_turn:{talent}"
    current = ctx.engine.state.actors.get(ctx.engine.state.current_actor_id)
    stamp = ctx.engine.state.round_number if limit == "once_per_round" else (
        f"{ctx.engine.state.round_number}:{current.entity_id}:{current.turns_started}" if current else str(actor.turns_started))
    if limit in ("once_per_turn", "once_per_round") and actor.turn_flags.get(flag) == stamp:
        return
    selected = next(iter(affordable))
    accepted = next((i for i in range(len(ctx.engine.events) - 1, -1, -1)
                     if ctx.engine.events[i].event_type == "INTENT_ACCEPTED"), 0)
    attack = next((e for e in reversed(ctx.engine.events[accepted:]) if e.event_type == "ATTACK_ROLLED"
                   and e.actor_id == actor.entity_id), None)
    action = ctx.engine.action_catalog.get(attack.source_definition_id if attack else ctx.engine.events[accepted].source_definition_id) if ctx.engine.events else None
    triggering = action.display_name if action else next((r.get("name") for r in
        (getattr(ctx.engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
        if attack and r.get("feature_id") == attack.source_definition_id), ctx.action.display_name)
    intent = ctx.intent or getattr(ctx.engine, "_active_intent", None)
    if intent is not None and hasattr(ctx.engine, "_gate4_reaction_cache"):
        # The checkpoint identifies *what is being paid for*, not how many events the fight has
        # recorded so far. Keying it on ``state.event_sequence`` made the same question carry a
        # different id on the replay that commits than on the pass where the player answered it,
        # so a recorded answer silently stopped matching and the payment fell back to its automatic
        # default -- a decline was charged for. Talent + payer + the creature it affects + the action
        # that triggered it is stable across those replays. The occurrence number then tells two
        # activations of the same talent off the same action apart, because an action definition is
        # not one triggering event: without it a USE answered for the first creature authorized
        # payment for the second, and a DECLINE answered for the first suppressed the second.
        # trigger_occurrence counts per resolution, which both passes of one action enter at 0.
        from . import trigger_occurrence

        target_id = ctx.target.entity_id if ctx.target else actor.entity_id
        trigger = str(attack.source_definition_id if attack else ctx.source)
        occurrence = trigger_occurrence.next_occurrence(
            ctx.engine, f"paid_option:{talent}:{actor.entity_id}:{target_id}:{trigger}")
        checkpoint = f"PAID_OPTION:{talent}:{actor.entity_id}:{target_id}:{trigger}:{occurrence}"
        decision = ctx.engine._reaction_decision(intent, checkpoint, actor.entity_id,
                                                CHOICE + talent, context={"payment_options": list(affordable), "actor_id": intent.actor_id,
                                                                         "target_id": target_id,
                                                                         "name": row.get("name") or talent, "feature_id": talent,
                                                                         "labels": {key: ", ".join(f"{part['amount']} {part['resource_id'].rsplit('.', 1)[-1].replace('_', ' ')}" for part in parts) or "No cost"
                                                                                     for key, parts in affordable.items()},
                                                                         "prompt": f"{row.get('name') or talent} after {triggering} affects "
                                                                                    f"{ctx.target.display_name if ctx.target else actor.display_name}: choose payment or decline",
                                                                         "payments": affordable})
        if decision is not None:
            if decision.selection == "DECLINE":
                return
            selected = decision.option_ids[0]
    way = affordable[selected]
    for part in way:
        ctx.engine._spend_resource(actor, part["resource_id"], int(part["amount"]), str(row.get("talent") or ctx.source))
    if limit in ("once_per_turn", "once_per_round"):
        actor.turn_flags[flag] = stamp
    run_effects(ctx, row.get("effects") or [])
