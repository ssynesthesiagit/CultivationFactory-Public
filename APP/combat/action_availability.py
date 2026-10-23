"""Read-only button explanations for TabletopService and connected sheets.

Costs and restrictions use the engine's public availability query. A batch shares
one isolated candidate pass, with the same per-source reasons. Shared object
actions use exact source/target queries. Older callers
without the query retain the quote/payment fallback and neutral unknown reason.
"""
from .alternative_payments import options, shortfall
from .resource_labels import exhausted_uses_reason, resource_name
from . import loadout


UNKNOWN_REASON = "Unavailable now: this action has no legal option under the current combat rules."


def describe(engine, menu, *, presentation=None):
    """Explain every disabled projected action, even without an engine diagnosis.

    The issued projection is authoritative about availability. An independent
    query can disagree (for example after a final menu filter); never leave that
    disabled button without words. This does not grant or remove any option.
    """
    reasons = _describe(engine, menu)
    fallback = {
        "historical_mode": "Unavailable while viewing an earlier turn.",
        "match_paused": "The fight is paused. Resume it before taking an action.",
        "actor_inactive": "This fighter cannot act while inactive.",
        "not_current_actor": "Wait for this fighter's turn.",
    }
    for actor in (presentation or {}).get("actors") or []:
        for row in actor.get("action_availability") or []:
            if row.get("legal_now"):
                continue
            reason = next((fallback[code] for code in row.get("disabled_reason_codes") or []
                           if code in fallback), UNKNOWN_REASON)
            reasons.setdefault("act:" + row["action_definition_id"], reason)
    return reasons


def _describe(engine, menu):
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
        shared_object_action = (action.owner_id == "*" and source.startswith("system:")
                                and str(getattr(action.target_kind, "value", action.target_kind)) == "OBJECT"
                                and (action.parameters or {}).get("player_only") is True)
        if (not shared_object_action and action.owner_id != actor.entity_id) \
                or (not shared_object_action and (source in available or action.source_definition_id in available)):
            continue
        scopes = tuple(engine.state.objects) if shared_object_action else (None,)
        pending.append((source, action, scopes, shared_object_action))
    batch_query = getattr(engine, "action_availabilities", None)
    query = getattr(engine, "action_availability", None)
    target_query = getattr(engine, "action_target_availability", None)
    target_batch = getattr(engine, "action_target_availabilities", None)
    batch_sources = [action.source_definition_id for _, action, scopes, _ in pending
                     if scopes == (None,)]
    answers = batch_query(actor.entity_id, batch_sources) if batch_query is not None and batch_sources else {}
    target_pairs = [(action.source_definition_id, object_id)
                    for _, action, scopes, _ in pending
                    if scopes != (None,) for object_id in scopes]
    target_answers = (target_batch(actor.entity_id, target_pairs)
                      if target_batch is not None and target_pairs else {})
    reasons = {}
    for source, action, scopes, shared_object_action in pending:
        if shared_object_action and target_batch is not None:
            answers_for_scope = {object_id: target_answers[(action.source_definition_id, object_id)]
                                 for object_id in scopes}
        elif shared_object_action and target_query is not None:
            answers_for_scope = {
                object_id: target_query(actor.entity_id, action.source_definition_id, object_id)
                for object_id in scopes
            }
        elif batch_query is not None or query is not None:
            answer = (answers[action.source_definition_id] if batch_query is not None
                      else query(actor.entity_id, action.source_definition_id))
            answers_for_scope = {object_id: answer for object_id in scopes}
        else:
            answers_for_scope = {}
        if answers_for_scope:
            for object_id, answer in answers_for_scope.items():
                if answer["available"] or not answer.get("reason"):
                    continue
                key = f"act:{source}:{object_id}" if object_id is not None else f"act:{source}"
                reasons[key] = answer["reason"]
            # Targeted answers are authoritative for this object. Do not fall back
            # to a source-wide answer, which could belong to another object.
            if shared_object_action and (target_batch is not None or target_query is not None):
                continue
            answer = next(iter(answers_for_scope.values()))
            if answer["available"]:
                continue
            if answer.get("reason"):
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
        for object_id in scopes:
            key = f"act:{source}:{object_id}" if object_id is not None else f"act:{source}"
            reasons[key] = reason
    return reasons
