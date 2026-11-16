"""One activation's chosen-target Resistance bypass; no retained fight state.

Shared helper bypass_scope is used by fire_sphere (White-Hot Focus) and
this module's typed Incinerating Lance choice.

The typed choice runs before the damage/save blocks. Each block opens a bounded
scope, restored on player pauses, errors and nested effects. Immunity remains
the native defense reader's responsibility.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id

CHOICE = "choice:activation_resistance.target"
SLOT = "activation_resistance_choice"
_active: ContextVar[tuple] = ContextVar("activation_resistance", default=())


@contextmanager
def bypass_scope(ctx: Any, target_id: str, damage_types: list[str]):
    """Public packet scope used by typed choices and activation-bound benefits."""
    record = (ctx.engine, ctx.actor.entity_id, str(ctx.typed.get("source") or ""),
              target_id, frozenset(str(kind).upper() for kind in damage_types))
    token = _active.set((*_active.get(), record))
    try:
        yield
    finally:
        _active.reset(token)


@effect("activation_resistance_choice")
def choose_target(ctx: Any, row: dict[str, Any]) -> None:
    kinds = row.get("damage_types")
    if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or not k for k in kinds):
        raise ValueError("activation_resistance_choice requires named damage_types")
    # Resolve from this accepted action's own recipients, never the live roster.
    from ..target_knowledge import knowledge
    known = {subject.entity_id for subject in ctx.targets
             if (observed := knowledge(ctx.engine, ctx.actor, subject)) is not None and observed.mode == "DIRECT"}
    roster = [actor for actor in ctx.targets if actor.active and actor.entity_id in known]
    if not roster:
        return
    ids = [actor.entity_id for actor in roster]
    preferred = [actor.entity_id for actor in roster if actor.team_id != ctx.actor.team_id] or ids
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ACTIVATION_RESISTANCE", ctx.source),
                 ctx.actor, CHOICE, ids, labels={actor.entity_id: actor.display_name for actor in roster},
                 preferred=preferred[:1], name=ctx.action.display_name,
                 prompt=f"{ctx.action.display_name}: choose one affected creature. This use ignores its "
                        f"Resistance to {' and '.join(k.title() for k in kinds)} damage.",
                 target_id=preferred[0])
    if picked and picked[0] in ids:
        ctx.damage_cache[SLOT] = {"target_id": picked[0], "damage_types": list(kinds), "source": ctx.source}


@hook("choice_options")
def target_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id != CHOICE or not (context or {}).get("needle_options"):
        return None
    return {"option_ids": list(context["needle_options"]), "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": False, "automatic_use": True,
            "preferred_option_ids": list(context.get("preferred") or [])}


@hook("effect_resolution_scope")
def chosen_scope(ctx: Any, row: dict[str, Any]):
    chosen = ctx.damage_cache.get(SLOT)
    if chosen and chosen.get("source") == ctx.source:
        return bypass_scope(ctx, chosen["target_id"], chosen["damage_types"])
    return None


@hook("resistance_ignored")
def chosen_resistance(engine, kind, typed, source_actor_id, target=None):
    if target is None:
        return None
    for owner_engine, owner, source, chosen, kinds in reversed(_active.get()):
        if (owner_engine is engine and owner == source_actor_id and source
                and source == str((typed or {}).get("source") or "")
                and chosen == target.entity_id and str(kind).upper() in kinds):
            return True
    return None
