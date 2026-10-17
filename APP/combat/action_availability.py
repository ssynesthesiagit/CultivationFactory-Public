"""Read-only button explanations for TabletopService and connected sheets.

Costs and restrictions use the engine's public availability query. A batch shares
one isolated candidate pass, with the same per-source reasons. Older callers
without the query retain the quote/payment fallback and neutral unknown reason.
"""
from .alternative_payments import options, shortfall
from .resource_labels import exhausted_uses_reason, resource_name
from . import loadout


UNKNOWN_REASON = "Unavailable now: this action has no legal option under the current combat rules."


def describe(engine, menu):
    if engine is None or not menu or not menu.get("manual"):
        return {}
    actor = engine.state.actors.get(menu.get("actor_id"))
    if actor is None:
        return {}
    available = {g.get("source_definition_id") for g in menu.get("actions") or []}
    available.update(g["alias_of"] for g in menu.get("actions") or [] if g.get("alias_of"))
    selected = {family: loadout.active_action(family, config, loadout.chosen(actor, family))
                for family, config in loadout.families(engine).get(actor.entity_id, [])}
    pending = []
    for button_action in engine.action_catalog.values():
        source = button_action.source_definition_id
        action = engine.action_catalog.get(selected.get(source)) or button_action
        if action.owner_id != actor.entity_id or source in available or action.source_definition_id in available:
            continue
        pending.append((source, action))
    batch_query = getattr(engine, "action_availabilities", None)
    query = getattr(engine, "action_availability", None)
    answers = (batch_query(actor.entity_id, [action.source_definition_id for _, action in pending])
               if batch_query is not None and pending else {})
    reasons = {}
    for source, action in pending:
        if batch_query is not None or query is not None:
            answer = (answers[action.source_definition_id] if batch_query is not None
                      else query(actor.entity_id, action.source_definition_id))
            if answer["available"]:
                continue
            if answer.get("reason"):
                reasons[f"act:{source}"] = answer["reason"]
                continue
        economy = str(getattr(action.economy, "value", action.economy))
        spent = {"ACTION": actor.action_available, "BONUS_ACTION": actor.bonus_action_available,
                 "REACTION": actor.reaction_available}.get(economy) is False
        if spent:
            name = {"ACTION": "action", "BONUS_ACTION": "bonus action", "REACTION": "reaction"}[economy]
            reason = f"Used: your {name} is spent; it returns at the start of your next turn."
        else:
            costs = engine.effective_costs(actor, action.source_definition_id, action.costs)
            missing = shortfall(actor, costs)
            if missing and not options(engine, actor, action.source_definition_id, costs):
                from .alternative_payments import totals
                required = totals(costs)
                parts = []
                for resource in missing:
                    if resource.startswith("resource:uses."):
                        # Compiled uses counters initialize for each fight; rest/day
                        # limits are once per fight under the owner's combat ruling.
                        parts.append(exhausted_uses_reason())
                    else:
                        parts.append(f"Not enough {resource_name(resource)} (needs {required[resource]}, you have {actor.resources.get(resource, 0)})")
                reason = "; ".join(parts) + "."
            else:
                reason = UNKNOWN_REASON
        reasons[f"act:{source}"] = reason
    return reasons
