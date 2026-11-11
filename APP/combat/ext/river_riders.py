"""Opt-in Flowing River riders bound to the compiled owner's typing.

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
def declaration(ctx: Any, spec: dict[str, Any]) -> None:
    pass  # passive declaration, consumed by the compile hook below


@hook("compile_actions")
def compile_riders(info: dict[str, Any]) -> None:
    for key in info["owned_ids"]:
        for spec in (info["mechanics"].get(key) or {}).get("effects") or []:
            if spec.get("type") == "rider_response_fail":
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
