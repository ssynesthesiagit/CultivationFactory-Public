"""Abyssal Depths: Liquid Body's activation marker, used by its conditional weapon resistance.

The movement and illegal-space clauses remain riders. Ordinary holds are source-qualified;
unknown or non-ordinary bindings are never inferred to be physical from their condition name.
Only this ability's compiled action can apply the marker; no global state or engine patching.
"""

from typing import Any

from . import effect, hook
from .physical_holds import end_hold, ordinary, source

DEEP = "tianxia.subpath.qi.abyssal_depths_cultivator.feature.deep_s_embrace"
MOON = "tianxia.subpath.qi.abyssal_depths_cultivator.feature.moon_s_pull"
PULL = "choice:abyssal.moon_pull"
LIQUID = "condition:typed.abyssal_liquid_body"
CHOICE = "choice:abyssal.end_physical_hold"
ESCAPE = "choice:abyssal.escape_hold"
NETTED = "condition:typed.netted"


@hook("choice_options")
def pull_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id != PULL or not context.get("moon_pull"):
        return None
    return {"option_ids": ["15", "10", "5", "0"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": True, "automatic_use": True}


@hook("forced_movement_distance")
def moon_pull(ctx, subject, eff, maximum_ft):
    """The failed-save pull is up to 15 feet; its caster owns that choice."""
    if (ctx.action.parameters.get("typed", {}).get("source") != MOON
            or not eff.get("choose_distance") or maximum_ft != 15):
        return None
    intent = ctx.intent or getattr(ctx.engine, "_active_intent", None)
    decision = ctx.engine._reaction_decision(
        # The same caster may hold several copies, including overlapping ones.
        # Their stable trigger sequences prevent one answer from serving two saves.
        intent, f"ABYSSAL_PULL:{ctx.source}:{subject.entity_id}:{ctx.engine.state.event_sequence}",
        ctx.actor.entity_id, PULL,
        context={"actor_id": ctx.actor.entity_id, "target_id": subject.entity_id,
                 "moon_pull": 1, "name": "Moon’s Pull", "feature_id": MOON,
                 "labels": {str(ft): f"Pull {ft} feet" for ft in (15, 10, 5, 0)},
                 "prompt": f"Moon’s Pull: {subject.display_name} failed its Strength save against "
                           f"{ctx.action.display_name}; choose how far to pull it toward the field’s center."})
    if decision is not None and decision.selection == "DECLINE":
        return 0
    return int(decision.option_ids[0]) if decision is not None else maximum_ft


@hook("linked_hold_tracking")
def track_linked_holds(engine, actor, topic):
    if topic != "physical_pin":
        return None
    return any(action.owner_id == actor.entity_id and
               (action.parameters.get("typed") or {}).get("source") == DEEP and
               any(row.get("linked_holds") for row in (action.parameters["typed"].get("effects") or []))
               for action in engine.action_catalog.values()) or None


@hook("hold_tracking")
def track_net_holds(engine, actor):
    return any(action.owner_id == actor.entity_id and
               (action.parameters.get("typed") or {}).get("source") == DEEP and
               any(row.get("net_holds") for row in (action.parameters["typed"].get("effects") or []))
               for action in engine.action_catalog.values()) or None


def _net_active(actor):
    return any(c.condition_id == LIQUID and c.data.get("net_holds") == 1 for c in actor.conditions.values())


def _active(actor: Any) -> int | None:
    return next((int(c.data["hold_cl"]) for c in actor.conditions.values()
                 if c.condition_id == LIQUID and "hold_cl" in c.data), None)


@hook("choice_options")
def hold_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id not in {CHOICE, ESCAPE} or not context.get("abyssal_holds"):
        return None
    return {"option_ids": context["abyssal_holds"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": False, "automatic_use": True}


@hook("escape_grips")
def choose_escape_hold(ctx, grips):
    if not any(c.condition_id == LIQUID and c.data.get("individual_escape") == 1
               for c in ctx.actor.conditions.values()):
        return None
    cl = _active(ctx.actor)
    if any(c.condition_id == NETTED for c in grips.values()):
        return None  # Trap owns its linked net selection, including after Liquid Body expires.
    if cl is None or len(grips) < 2 or not any(physical and level is not None and level >= cl
                               for physical, level in (source(ctx.engine, grip) for grip in grips.values())):
        return None
    ordered = sorted(grips, key=lambda key: liquid_escape(ctx.engine, ctx.actor, [grips[key]]) != "ADVANTAGE")
    decision = ctx.engine._reaction_decision(
        ctx.intent, f"ABYSSAL_ESCAPE:{ctx.source}:{ctx.actor.entity_id}", ctx.actor.entity_id, ESCAPE,
        context={"actor_id": ctx.actor.entity_id, "target_id": ctx.actor.entity_id,
                 "abyssal_holds": ordered,
                 "labels": {key: f"{c.condition_id.removeprefix('condition:typed.').title()} from "
                                 f"{getattr(ctx.engine.state.actors.get(c.source_actor_id), 'display_name', c.source_actor_id)}: "
                                 f"{getattr(ctx.engine.action_catalog.get(c.source_definition_id), 'display_name', c.source_definition_id)} "
                                 f"({'ordinary physical' if source(ctx.engine, c)[0] else 'other binding'})"
                            for key, c in grips.items()},
                 "prompt": f"Deep’s Embrace: {ctx.action.display_name} by {ctx.actor.display_name}; choose the hold affecting them to escape."})
    # AI prefers a qualifying ordinary hold; players may choose any offered hold.
    return list(decision.option_ids) if decision is not None else [ordered[0]]


@hook("condition_attempt")
def prevent_lower_hold(ctx, subject, eff):
    if eff.get("tracking") == "physical_pin" and not any(
            c.condition_id == LIQUID and c.data.get("linked_holds") == 1 for c in subject.conditions.values()):
        return None
    if str(ctx.typed.get("source") or "").startswith("trap:") and not _net_active(subject):
        return None  # old saved Liquid Body bundles do not gain the new net integration
    cl = _active(subject)
    source_cl = ctx.numbers.get("cl")
    if cl is not None and source_cl is not None and int(source_cl) < cl and ordinary(ctx.typed, eff):
        return False
    return None


@hook("escape_mode")
@hook("escape_save_mode")
def liquid_escape(engine, actor, grips):
    if any(c.condition_id == NETTED for c in grips) and not _net_active(actor):
        return None
    cl = _active(actor)
    # The core escape Action tests/ends all supplied grips together. Never let an ordinary
    # grip grant Advantage to an unrelated magical hold in that same aggregate roll.
    if cl is not None and grips and all(physical and level is not None and level >= cl
                                       for physical, level in (source(engine, grip) for grip in grips)):
        return "ADVANTAGE"
    return None


@effect("abyssal_liquid_body")
def liquid_body(ctx: Any, eff: dict[str, Any]) -> None:
    if ctx.typed.get("source") != DEEP:
        return
    ctx.engine._remove_condition(ctx.actor, LIQUID, ctx.source)
    ctx.engine._apply_condition(ctx.actor, LIQUID, ctx.source, ctx.actor.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Deep’s Embrace: Liquid Body",
                                      **({"linked_holds": 1} if eff.get("linked_holds") else {}),
                                      **({"net_holds": 1} if eff.get("net_holds") else {}),
                                      **({"individual_escape": 1} if eff.get("individual_escape") else {}),
                                      **({"hold_cl": int(ctx.numbers["cl"])} if eff.get("physical_holds") else {})})
    if not eff.get("physical_holds"):
        return  # old saved action bundles retain their earlier behavior
    eligible = {}
    for key, condition in ctx.actor.conditions.items():
        if condition.condition_id not in {"condition:typed.grappled", "condition:typed.restrained"}:
            continue  # a net's bookkeeping marker is not a second player-owned hold
        physical, level = source(ctx.engine, condition)
        if physical and level is not None and level < int(ctx.numbers["cl"]):
            eligible[key] = condition
    if not eligible:
        return
    decision = ctx.engine._reaction_decision(
        ctx.intent, f"ABYSSAL_HOLD:{ctx.source}:{ctx.actor.entity_id}", ctx.actor.entity_id, CHOICE,
        context={"actor_id": ctx.actor.entity_id, "target_id": ctx.actor.entity_id,
                 "abyssal_holds": list(eligible),
                 "labels": {key: f"{c.condition_id.removeprefix('condition:typed.').title()} from "
                                 f"{getattr(ctx.engine.state.actors.get(c.source_actor_id), 'display_name', c.source_actor_id)} "
                                 f"(CL {source(ctx.engine, c)[1]})"
                            for key, c in eligible.items()},
                 "prompt": f"Deep’s Embrace: activating Liquid Body on {ctx.actor.display_name}; choose one ordinary physical hold to end."})
    key = decision.option_ids[0] if decision is not None else next(iter(eligible))
    end_hold(ctx, key)
