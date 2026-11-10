"""C15 compatibility helpers for native pre-damage critical resolution.

lowest and own_rows retain their public signatures. expanded reports the native
final result without rolling dice or committing damage. Deferred C15 feature
rows remain inert until their own eligibility/acceptance work is completed.
"""
from __future__ import annotations

from typing import Any

from . import hook

BLOCK = "critical_range"

# These C15 additions need critical status set before the engine rolls damage.
# Also exclude rows compiled into older saved fights: removing feature-block data
# alone would leave their separate-damage workaround active after reload.
# AUTO1 2026-10-04: Sword Saint Incarnation left this list. gate2_engine resolves
# the threshold through critical_attacks.lowest before the damage roll, which is
# the ordering the exclusion was waiting for, and no feature_blocks row existed for
# it, so no saved fight carries a separate-damage workaround to double up.
DEFERRED_FEATURES = frozenset({
    "TAL_DUAL_WIELDING_CRITICAL_FOLLOW_UP",
})


def lowest(ctx: Any, target: Any) -> int:
    """Compatibility query; same native threshold, no post-hit work."""
    from ..critical_attacks import lowest as native_lowest
    return native_lowest(ctx.engine, ctx.actor, target, (getattr(ctx, "attack_spec", None) or {}), typed_ctx=ctx)


def expanded(ctx: Any, target: Any, attack_event: Any) -> bool:
    """Read the finalized widened critical by roll id; never deal a second packet."""
    roll_id = (attack_event.payload or {}).get("roll_id")
    if int((attack_event.payload or {}).get("natural_result") or 0) >= 20:
        return False
    return any(event.event_type == "ATTACK_CRITICAL_RESOLVED"
               and event.actor_id == ctx.actor.entity_id and target.entity_id in event.target_ids
               and event.payload.get("roll_id") == roll_id and event.payload.get("critical") is True
               for event in reversed(ctx.engine.events))


# ------------------------------------------------------------------------------------------------- feature-block rows
@hook("compile_block")
def _compile(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, **{key: value for key, value in spec.items() if key not in {"block", "resource", "why"}}, "keeps_compiling": True}]


def _weapon_fits(ctx: Any, wanted: str | None) -> bool:
    if not wanted:
        return True
    effect = getattr(ctx, "attack_effect", None) or {}
    unarmed = effect.get("attack_kind") == "unarmed" or ".natural." in str(ctx.source)
    if wanted == "unarmed":
        return unarmed
    if wanted == "unarmed_or_blade":
        if unarmed:
            return True
        from .integrated_weapons import in_group

        # Integration variants seal a concrete eligible weapon selection. The
        # weapon stays integrated when its ordinary attack profile is selected.
        source = ctx.typed.get("source")
        return in_group(ctx.typed, "blade") and any(
            action.owner_id == ctx.actor.entity_id and "#integrated_" in action.source_definition_id
            and ((action.parameters or {}).get("typed") or {}).get("source") == source
            for action in ctx.engine.action_catalog.values())
    return False


@hook("critical_range")
def own_rows(ctx: Any, target: Any) -> int | None:
    best = None
    for row in getattr(ctx.engine, "typed_passive_rows", {}).get(ctx.actor.entity_id, []):
        if row.get("block") != BLOCK:
            continue
        if row.get("feature_id") in DEFERRED_FEATURES:
            if row.get('feature_id') != 'TAL_DUAL_WIELDING_CRITICAL_FOLLOW_UP' or not row.get('auto94'):
                continue
            from .qualifying_pairs import qualifying_pair
            if (not qualifying_pair(ctx.engine, ctx.actor) or ctx.typed.get('opportunity_of')
                    or ctx.typed.get('reaction_attack') or ctx.engine.state.current_actor_id != ctx.actor.entity_id):
                continue
        if row.get("pair_role") and ctx.typed.get("pair_role") != row["pair_role"]:
            continue
        if row.get("while_state"):
            from .states import active

            if active(ctx.engine, ctx.actor, row["while_state"]) is None:
                continue
        if not _weapon_fits(ctx, row.get("weapons")):
            continue
        value = int(row.get("lowest") or 20)
        best = value if best is None else min(best, value)
    return best
