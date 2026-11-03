"""Source-bound Flurry prerequisites and its one additional bonus strike.

Basic Attack provenance is shared compiler metadata. A miss or an actual
Grapple/Shove attempt still makes an Unarmed Strike; a reaction or a technique
does not take the Attack action. No action labels or global ownership caches.
The alternative damage clause remains a rider until an independent bonus
Unarmed Strike source has accurate, supported provenance and eligibility.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from ..gate2_runtime_models import EconomyKind

FLURRY = "TAL_IRON_FIST_IRON_FIST_FLURRY"
READY = "iron_flurry_ready"


@effect("iron_flurry")
def marker(ctx: Any, row: dict[str, Any]) -> None:
    pass  # captured from owned, hash-bound typing


@hook("maneuvers")
def compile_flurry(info: dict[str, Any]) -> None:
    mechanic = info["mechanics"].get(FLURRY) or {}
    if FLURRY not in info["owned"] or not any(r.get("type") == "iron_flurry" for r in mechanic.get("effects") or []):
        return
    for action in info["actions"]:
        action.parameters["iron_flurry"] = True
        typed = action.parameters.get("typed") or {}
        if (typed.get("modifier") or {}).get("id") == FLURRY:
            action.parameters["requires_turn_flag"] = READY
            # Extra Attack belongs to the Attack action, not the one bonus strike.
            for row in typed.get("effects") or []:
                if row.get("type") == "attack":
                    row["count"] = 1
                    row.pop("count_by_cl", None)


def attack_action(ctx: Any) -> bool:
    return bool(ctx.action.parameters.get("iron_flurry") and ctx.typed.get("attack_action")
                and ctx.action.economy == EconomyKind.ACTION and not ctx.typed.get("reaction_attack")
                and not ctx.typed.get("opportunity_of") and ctx.engine.state.current_actor_id == ctx.actor.entity_id)


@hook("attack_resolved")
def made_strike(ctx: Any, target: Any, hit: bool, row: dict[str, Any]) -> None:
    if attack_action(ctx) and row.get("attack_kind") == "unarmed":
        ctx.actor.turn_flags[READY] = 1  # a miss still made an Unarmed Strike


@hook("after_save")
def made_option(ctx: Any, target: Any, ability: str, named: set, failed: bool) -> None:
    if attack_action(ctx) and ctx.typed.get("unarmed_option") in ("grapple", "shove_push", "shove_prone"):
        ctx.actor.turn_flags[READY] = 1
