"""Treasure weapon enchantments beyond plain on-hit damage (forged-worker 2026-09-29; combat/factory_compiler.py
_enchantment_on_hit builds the effects below from the printed enchantment text, one per treasure on a live character's
current.zip). Moonless-Yin's no-healing rider and Frost-Meridian's Speed penalty reuse existing effect types
(healing_reduction, speed); this file adds the one genuinely new shape: a bonus that only applies while the target is
already in a printed state (Dream-Piercing Inscription: "hits a creature that is Charmed, Frightened, Unconscious, or
affected by a Dreams Sphere effect"). The table does not track creature type at all (Beast-Hunter, Ghost-Slaying and
similar "hits a Beast" / "hits an Undead" inscriptions stay GM-only riders for that reason, not this one)."""

from __future__ import annotations

from typing import Any

from . import effect


@effect("conditional_damage")
def _conditional_damage(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Bonus on-hit damage gated on the target already bearing one of ``when_target_condition`` (condition ids end in
    the printed name, e.g. "condition:typed.charmed" -> "charmed"). Delegates the actual roll and commit to
    block_damage so it rolls, types and resists exactly like any other on-hit damage effect."""
    target = ctx.target
    wanted = set(effect_row.get("when_target_condition") or ())
    if target is None or not wanted:
        return
    if not any(condition.condition_id.rsplit(".", 1)[-1] in wanted for condition in target.conditions.values()):
        return
    from .. import typed_executor

    typed_executor.block_damage(ctx, {**effect_row, "type": "damage"})
