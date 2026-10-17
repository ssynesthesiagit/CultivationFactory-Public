"""Escape check resolver shared by grapples, bindings and granted escape options.

Callers supply the held instances and hazard scope, and retain their own removal
semantics. Modes, bonuses, evented roll, check floors and ally Auspice Release are
resolved once here. No state or ability-specific policy is stored by this helper.
"""
from __future__ import annotations

from typing import Any


def resolve_escape_check(ctx: Any, effect: dict[str, Any], dc: int,
                         grips: list[Any], against: tuple[str, ...] = (), *, check_name: str = "",
                         target_id: str | None = None, source_id: str | None = None,
                         source_actor_id: str | None = None, check_ability: str | None = None,
                         check_skill: str | None = None, escape_hooks: bool = True) -> bool:
    """Resolve one check; ctx.actor rolls and callers remove their own holds.

    Explicit check_ability/check_skill keywords use that check's unresolved modes
    and hazard scope. Omitted keywords retain legacy effect-based resolution.
    Optional metadata identifies a helped creature and the hold's origin; defaults
    preserve existing callers' roll scope and event payload exactly.
    Ordinary ability checks must set escape_hooks=False: benefits granted only
    for escaping a hold cannot contribute to those checks.
    """
    from . import floored, run
    from .scoped_checks import escape_modes
    from ..typed_executor import check_modes
    from copy import copy

    ability = check_ability
    skill = str(check_skill or ability) if ability else "Athletics or Acrobatics"
    modes = (check_modes(ctx.actor, str(ability), check_skill,
                         engine=ctx.engine, hazards=against) if ability else escape_modes(ctx.actor, effect, against, engine=ctx.engine))
    if escape_hooks:
        modes.update(mode for mode in run("escape_mode", ctx.engine, ctx.actor, grips)
                     if mode in ("ADVANTAGE", "DISADVANTAGE"))
    bonus_ctx = copy(ctx)
    bonus_ctx.escape_hazards = against
    modifier = int(effect.get("bonus", ctx.numbers.get("escape_bonus") or 0)) + sum(run("check_bonus", bonus_ctx, ctx.actor))
    target_id = ctx.actor.entity_id if target_id is None else target_id
    with ctx.engine.d20_scope({"kind": "check", "actor_id": ctx.actor.entity_id,
                               "target_id": target_id, "source_id": ctx.source if source_id is None else source_id,
                               "source_actor_id": ctx.actor.entity_id if source_actor_id is None else source_actor_id,
                               "skill": skill, "dc": dc, "reason": f"CHECK:{ctx.source}"}):
        roll = ctx.engine.roller.d20(modifier=modifier, actor_id=ctx.actor.entity_id,
                                     reason=f"CHECK:{ctx.source}", mode=modes.pop() if len(modes) == 1 else "NORMAL")
    ctx.engine._record_roll(roll)
    roll = floored(ctx.engine, ctx.actor, roll, dc)
    success = roll.total >= dc
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id,
                             target_ids=(target_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                      **({"ability": ability} if ability else {}),
                                      **({"check": check_name} if check_name else {})})
    return success
