"""Bounded payments shared by typed damage soaks, Blood transfusion and Daemonic regeneration.

The existing choice transport validates/journals the amount. Reaction identity
and checkpoint binding remain unchanged; the caller pays and resolves effects.
``choose_spend``'s trigger dict may carry ``action_name`` (who or what caused the
triggering damage) so the prompt names that instead of the generic fallback; without
it the source's catalog entry is used, as before.
"""
from . import hook


@hook("choice_options")
def options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if not choice_id.startswith(("reaction:typed.", "choice:spend.")) or "spend_options" not in context:
        return None
    return {"option_ids": context["spend_options"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": True, "automatic_use": True,
            "preferred_option_ids": [context["automatic_spend"]]}


@hook("decision_text")
def description(engine, context, printed_rules):
    trigger = context.get("choice_trigger") or {}
    if "spend_options" not in trigger:
        return None
    return {"cost": trigger["cost"], **({"trigger": trigger["prompt"]} if trigger.get("payment_note") else {}),
            **({"table_note": trigger["payment_note"]} if trigger.get("payment_note") else {})}


def choose_spend(engine, row, reactor, checkpoint, maximum, automatic, trigger):
    from ..typed_reactions import _asking, ask_key
    from ..decision_text import agrees, resource_name

    if not _asking(engine, reactor, row):
        return automatic
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return 0
    pool = trigger.get("pool_name") or resource_name(row["resource_id"])
    action = engine.action_catalog.get(trigger.get("source_id"))
    # A caller that knows what actually struck names it here; otherwise the catalog entry for the
    # feature, and only then the printed fallback.
    action_name = trigger.get("action_name") or (action.display_name if action else "the triggering damage")
    damage_source = (f"their own effect: {action_name}" if trigger.get("actor_id") == reactor.entity_id
                     else action_name)
    choices = [str(n) for n in range(1, maximum + 1)]
    context = {"spend_options": choices, "automatic_spend": str(max(1, automatic)),
               "payment_note": trigger.get("payment_note", ""),
               "labels": trigger.get("labels") or {n: f"Spend {n} {pool}" for n in choices},
               "cost": trigger.get("cost") or f"Reaction and your chosen amount (1–{maximum} {pool})",
               "feature_id": row["feature_id"], "name": row["name"],
               "actor_id": trigger.get("actor_id"), "target_id": trigger.get("target_id") or reactor.entity_id,
               "affected_id": trigger.get("target_id") or reactor.entity_id, "action_name": action_name,
               "source_definition_id": trigger.get("source_id"),
               "prompt": trigger.get("prompt") or (
                         f"{reactor.display_name} {agrees(reactor.display_name, 'is', 'are')} about to take {trigger['damage_amount']} damage from {damage_source}. "
                         f"{row['name']}: choose how much {pool} to spend, or pass.")}
    decision = engine._reaction_decision(intent, ask_key(checkpoint, engine), reactor.entity_id,
                                        trigger.get("choice_id") or "reaction:typed." + row["feature_id"], context=context)
    return int(decision.option_ids[0]) if decision is not None and decision.selection == "USE" else 0
