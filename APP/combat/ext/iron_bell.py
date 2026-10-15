"""Bell-Ringing Body Shot's Meridian choice on Counter Palm's Unarmed hit.

The ordinary strike already runs the owned typed modifier and its preset menu.
Reaction strikes do not inherit those modifiers. ``maneuvers`` freezes the same
effects on the owner's natural actions; ``iron_bell_on_hit`` offers the printed
choose-one through Needle's public transport, then runs only that option from
the captured typing. This is separate from Counter Palm's optional Form choice:
Bell is a Meridian, and needs a hit on an already-Opened creature, not damage.
Old bundles without the capture are inert. No new persistent state is needed.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id

BELL = "TAL_IRON_FIST_BELL_RINGING_BODY_SHOT"
CHOICE = "choice:needle.iron_bell"


@hook("maneuvers")
def compile_bell(info: dict[str, Any]) -> None:
    if not {BELL, "TAL_IRON_FIST_COUNTER_PALM"} <= set(info["owned"]):
        return
    effects = (info["mechanics"][BELL].get("modifier") or {}).get("effects") or []
    for action in info["actions"]:
        if ".natural." in action.source_definition_id and "#" not in action.source_definition_id:
            action.parameters["iron_bell_effects"] = copy.deepcopy(effects)


@effect("iron_bell_on_hit")
def bell_on_hit(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import Context, bears_mark, opened_before, run_effects

    target = ctx.target
    if target is None:
        return
    effects = next((a.parameters["iron_bell_effects"] for a in ctx.engine.action_catalog.values()
                    if a.owner_id == ctx.actor.entity_id and "iron_bell_effects" in a.parameters), [])
    if not effects:
        return
    was = opened_before(ctx.engine, ctx.actor.entity_id, target.entity_id)
    if not (was if was is not None else bears_mark(target, ctx.actor.entity_id, "Opened")):
        return
    # Reuse the source's one existing menu and option effects. The reaction
    # answer applies to this hit alone; ordinary strike presets stay unchanged.
    nested = next((e["effects"] for e in effects if e.get("type") == "if_marked" and e.get("mark") == "Opened"), [])
    menu = next((e for e in nested if e.get("type") == "menu"), None)
    if menu is None:
        return
    from .menus import picks

    selected = ask(ctx.engine, ctx.intent,
                   checkpoint_id(ctx.engine, "Bell-Ringing Body Shot", ctx.actor.entity_id, target.entity_id),
                   ctx.actor, CHOICE, list(menu["options"]),
                   preferred=picks(ctx.engine, ctx.actor, menu["id"]), target_id=target.entity_id,
                   prompt=f"Bell-Ringing Body Shot after {ctx.action.display_name} hits {target.display_name}: choose one")
    if len(selected) != 1:
        return
    chosen = [{k: copy.deepcopy(v) for k, v in e.items() if k not in ("menu", "option")}
              for e in nested if e.get("menu") == menu["id"] and e.get("option") == selected[0]]
    sub = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
    run_effects(sub, chosen)
