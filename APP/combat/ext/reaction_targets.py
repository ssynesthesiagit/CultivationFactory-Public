"""Selectable recipients for typed condition reactions with a granted attack.

Typed reactions use choose_target before consent/payment. The condition_applied
hook dispatches rows whose typed `after` field names that moment. No owned row
with these opt-ins means no changed targets, prompts, costs or saved state.
"""
from . import hook


@hook("condition_applied")
def after_condition(ctx, name, subject):
    from ..typed_reactions import offer_condition_gained

    rows = [row for attribute in ("typed_reaction_rows", "typed_passive_rows")
            for actor_rows in (getattr(ctx.engine, attribute, {}) or {}).values() for row in actor_rows]
    if not any(row.get("after") == "condition_applied" and not row.get("held_back") for row in rows):
        return
    offer_condition_gained(ctx.engine, subject, ctx.actor, name, applied=True)


def choose_target(engine, reactor, row, checkpoint, source_actor, condition_name, *, affected=None):
    """Ask once for Use + target; AI uses the normal extension-choice controller.

    Targets are checked with the actual granted attack profile, not the reaction
    activation. Direct noninteractive engine calls pick the first legal target;
    interactive service calls use its provider and preserve no-answer/no-use.
    """
    from ..attack_declaration import can_target
    from ..choice_checkpoints import dynamic_choice
    from ..decision_text import resource_name
    from ..typed_reactions import _asking, ask_key, reaction_permitted_against, triggered_context

    ctx = triggered_context(engine, reactor, None, row)
    attacks = [e for e in row.get("effects") or [] if e.get("type") == "attack"]
    if not attacks:
        return None
    targets = [a for a in engine.state.actors.values() if a.entity_id != reactor.entity_id and
               reaction_permitted_against(engine, reactor, a) and
               all(can_target(engine, reactor, a, row["feature_id"], action=ctx.action,
                              typed_profile=ctx.typed, effect=e,
                              range_ft=ctx.action.range_ft if ctx.action.range_ft is not None else ctx.action.reach_ft)
                   for e in attacks)]
    intent = getattr(engine, "_active_intent", None)
    if not targets:
        return None
    if intent is None:
        return None if _asking(engine, reactor, row) else targets[0]
    ids = [a.entity_id for a in targets]
    action = engine.action_catalog.get(getattr(engine, "_active_action_source_id", None))
    action_name = action.display_name if action else "the triggering posture change"
    affected = affected or reactor
    costs = ([] if row.get("free") else ["one Reaction"]) + [
        f"{c['amount']} {resource_name(c['resource_id'])}" for c in row.get("costs") or [] if c.get("amount")]
    cost = "Costs " + " and ".join(costs) if costs else "Costs nothing"
    strike = "make one unarmed strike" if all(e.get("attack_kind") == "unarmed" for e in attacks) else "make a granted attack"
    when = "after" if checkpoint == "CONDITION_APPLIED" else "before"
    trigger = {"actor_id": getattr(source_actor, "entity_id", None), "target_id": affected.entity_id,
               "affected_id": affected.entity_id, "feature_id": row["feature_id"], "name": row["name"],
               "action_name": action_name, "source_definition_id": getattr(action, "source_definition_id", None),
               "labels": {a.entity_id: f"Attack {a.display_name}" for a in targets},
               "prompt": f"{row['name']}: {when} {affected.display_name} becomes {condition_name.title()} during "
                         f"{action_name}, choose a creature in reach and {strike} against it, or pass. {cost}."}
    _, decision = dynamic_choice(engine, intent, ask_key(checkpoint, engine), reactor.entity_id,
                                 "reaction:typed." + row["feature_id"], trigger,
                                 spec_override={"option_ids": ids, "minimum_selections": 1,
                                                "maximum_selections": 1, "allow_decline": True,
                                                "automatic_use": True})
    if decision is None or decision.selection != "USE":
        return None
    return next(a for a in targets if a.entity_id == decision.option_ids[0])
