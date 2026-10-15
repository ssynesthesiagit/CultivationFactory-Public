"""Shared helper module (consumers: bodyb_choices.py). Opt-in Flowing River riders bound to the compiled owner's typing.

``rider_response_fail`` declares a menu for a creature within the user's reach
that failed a save against the Response talent currently resolving. Its row
is compiled as a passive; unrelated saves and mere Response successes do not
trigger it. Flowing River supplies the selected talent's provenance on its
resolution context. No additional Reaction, resource or turn limit is charged.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from . import effect, hook


@effect("rider_response_fail")
@effect("rider_named_dodge")
def declaration(ctx: Any, spec: dict[str, Any]) -> None:
    pass  # passive declaration, consumed by the compile hook below


@hook("compile_actions")
def compile_riders(info: dict[str, Any]) -> None:
    for key in info["owned_ids"]:
        for spec in (info["mechanics"].get(key) or {}).get("effects") or []:
            if spec.get("type") in {"rider_response_fail", "rider_named_dodge"}:
                info["passives"].append({"feature_id": key, "block": spec["type"],
                                         "spec": copy.deepcopy(spec), "numbers": dict(info["numbers"])})


@hook("after_save")
def failed_response(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    _failed_response(ctx, subject, failed, final=False)


@hook("save_final")
def final_failed_response(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    _failed_response(ctx, subject, failed, final=True)


def _failed_response(ctx: Any, subject: Any, failed: bool, *, final: bool) -> None:
    if not failed or not ctx.typed.get("_rider_response_talent"):
        return
    from .. import typed_reactions
    from . import rider_outcomes

    reach = (typed_reactions.physical_melee_reach(ctx.engine, ctx.actor) if final
             else typed_reactions.opportunity_reach(ctx.engine, ctx.actor))
    if ctx.engine._distance_actor_to_actor(ctx.actor, subject) > int(reach or 5):
        return
    for row in (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(ctx.actor.entity_id, []):
        if row.get("block") == "rider_response_fail" and bool(row["spec"].get("final_save")) == final:
            rider_outcomes.menu(replace(ctx, targets=[subject], target=subject), row["spec"]["menu"])


GUARD = "condition:typed.river_named_guard"


def named_guard(engine: Any, actor: Any) -> tuple[bool, str | None]:
    enabled = any(row.get("block") == "rider_named_dodge" for row in
                  (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))
    target = next((c.data.get("target") for c in actor.conditions.values() if c.condition_id == GUARD), None)
    return enabled, target


@hook("event")
def dodge_choice(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") != "condition:core.dodge":
        return
    from .. import stealth
    from . import needle

    for who in kwargs.get("target_ids") or ():
        actor = engine.state.actors[who]
        if not named_guard(engine, actor)[0]:
            continue
        condition = actor.conditions[(kwargs["payload"])["instance_id"]]
        action = engine.action_catalog.get(condition.source_definition_id)
        if action is None or action.resolution_kind != "DODGE":
            continue  # receiving Dodge from another feature is not taking the Dodge Action
        options = [other for other in engine.state.actors.values() if other.active and other is not actor
                   and stealth.sees(engine, actor, other)]
        engine._remove_condition(actor, GUARD, condition.source_definition_id)
        if not options:
            continue
        picked = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "turning_guard", who), actor,
                            needle.CHOICE + "turning_guard", [other.entity_id for other in options],
                            labels={other.entity_id: other.display_name for other in options}, minimum=1, maximum=1,
                            prompt="Turning Guard: choose one creature you can see")
        if picked:
            engine._apply_condition(actor, GUARD, condition.source_definition_id, who,
                                    expires_on="START_OF_SOURCE_NEXT_TURN", data={"target": picked[0], "label": "Turning Guard"})
