"""Opt-in dependent physical holds, used by Wrestling Pin and Abyssal Depths.

A condition row with tracking/parent_condition lasts until one chosen same-source
parent hold ends. Untracked actors use the original condition row. Links are
string instance IDs; removal is evented and never ends the parent or unrelated holds.
"""

from . import hook, run

CHOICE = "choice:linked_hold.parent"


@hook("choice_options")
def parent_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id != CHOICE or not context.get("linked_hold_parents"):
        return None
    return {"option_ids": context["linked_hold_parents"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": False, "automatic_use": True}


@hook("condition_state")
def linked_state(ctx, subject, row):
    if not row.get("parent_condition") or not row.get("tracking"):
        return None
    if not any(run("linked_hold_tracking", ctx.engine, subject, row["tracking"])):
        return None
    parents = {key: c for key, c in subject.conditions.items()
               if c.condition_id == "condition:typed." + row["parent_condition"]
               and c.source_actor_id == ctx.actor.entity_id}
    if not parents:
        return False
    key = next(iter(parents))
    if len(parents) > 1:
        decision = ctx.engine._reaction_decision(
            ctx.intent, f"LINKED_HOLD:{ctx.source}:{subject.entity_id}", ctx.actor.entity_id, CHOICE,
            context={"actor_id": ctx.actor.entity_id, "target_id": subject.entity_id,
                     "linked_hold_parents": list(parents),
                     "labels": {iid: f"{getattr(ctx.engine.action_catalog.get(c.source_definition_id), 'display_name', 'Grapple')} (hold {index})"
                                for index, (iid, c) in enumerate(parents.items(), start=1)},
                     "prompt": f"{ctx.action.display_name}: choose the {row['parent_condition'].title()} on {subject.display_name} supporting this restraint."})
        key = decision.option_ids[0] if decision is not None else key
    return {"expires_on": "UNTIL_REMOVED", "data": {"parent_hold": key,
            "hold_kind": row["hold_kind"], "label": ctx.action.display_name}}


@hook("hold_source")
def linked_source(engine, condition):
    if not condition.data.get("parent_hold") or condition.data.get("hold_kind") != "ordinary_physical":
        return None
    action = engine.action_catalog.get(condition.source_definition_id)
    if action is None or action.owner_id != condition.source_actor_id:
        return False, None
    cl = (action.parameters.get("typed", {}).get("numbers") or {}).get("cl")
    return True, int(cl) if cl is not None else None


@hook("event")
def release_dependents(engine, event_type, kwargs):
    reconcile(engine)


@hook("turn_start")
@hook("turn_end")
def reconcile_turn(engine, actor):
    # Duration sweeps precede this hook. Their nested removals suppress event
    # hooks, so reconcile again before the next actor can act.
    reconcile(engine)


def reconcile(engine):
    """Release orphan links and descendants using persisted condition IDs only.

    Event checkpoints also recover parents removed inside another event hook;
    turn checkpoints cover the duration sweep inside the turn event guard.
    Unlinked conditions (including legacy holds) are never changed.
    """
    while True:
        live = {iid for actor in engine.state.actors.values() for iid in actor.conditions}
        children = [(actor, iid, c) for actor in engine.state.actors.values()
                    for iid, c in actor.conditions.items()
                    if c.data.get("parent_hold") and c.data["parent_hold"] not in live]
        if not children:
            break
        for actor, iid, condition in children:
            if actor.conditions.pop(iid, None) is None:
                continue  # a nested reconcile (the removal event's own hook) already released it: a parent with several holds
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id,
                                 actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                                 payload={"instance_id": iid, "condition_id": condition.condition_id,
                                          "reason": "PARENT_HOLD_ENDED"})
