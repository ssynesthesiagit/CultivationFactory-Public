"""Lengthening a push or a pull (rider lane C14, 2026-09-30; BLOCKED_CENSUS.md row 30). Shared helper module: answers the
``forced_movement_bonus`` hook (documented in combat/ext/__init__.py) from feature-block rows, so a new talent needs only data.

typed_executor.block_forced_movement adds every answer to the printed distance before the "up to" choice
(forced_movement_distance), the size limits' own checks, the moved creature's reactions and the reductions
(forced_movement_reduction) -- so a lengthened push is still reduced, resisted and stopped by walls the ordinary way.

Rows (combat/rules/feature_blocks.d/*.json, block "forced_movement_bonus"; compiled as the character's passive rows, the
talent's own typed rows keep compiling):
  {"block": "forced_movement_bonus", "ft": 5, "abilities": ["<mechanic id>"], "max_size_larger": 1}
        the owner's own push or pull made with one of those abilities (Weighted Links: Chain Lash, "if the target is no more than
        one size larger than you": typed_executor.size_width for both)
  {"block": "forced_movement_bonus", "ft": 10, "area": true, "who": "hostile", "pusher": "owner", "sphere": "<sphere id>",
   "option": "<option label>"}
        a creature standing in an area this feature made (the area's own source ability is the row's feature), hostile to the
        area's creator when "who" is "hostile"; moved by the creator itself with an ability of that sphere ("pusher": "owner",
        Gravity Domain: "Forced movement caused by your Gravity talents increases by 10 feet") or by anyone (Storm Without
        Direction's No Fixed Direction: "When a hostile creature is pushed or pulled in the area"); "option": only when the area
        was made with that option of the ability.
Inert: no row on the pusher or on any area's creator answers nothing.
"""
from __future__ import annotations

from typing import Any

from . import hook

BLOCK = "forced_movement_bonus"


@hook("compile_block")
def _compile(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, **{key: value for key, value in spec.items() if key not in {"block", "resource", "why"}}, "keeps_compiling": True}]


def _rows(engine: Any, actor_id: str) -> list[dict[str, Any]]:
    from ..typed_reactions import _rows as rows

    return rows(engine, actor_id, BLOCK)


def _own(ctx: Any, subject: Any, row: dict[str, Any], effect: dict[str, Any]) -> bool:
    from ..typed_executor import size_width
    from .ability_source import mechanic_of

    if mechanic_of(ctx.action).split("#")[0] not in set(row.get("abilities") or ()):
        return False
    if row.get("max_size_larger") is not None:
        return size_width(ctx, subject, "subject", effect) <= size_width(ctx, ctx.actor, "actor", effect) + int(row["max_size_larger"])
    return True


def _area(ctx: Any, subject: Any, zone: Any, owner: Any, row: dict[str, Any]) -> bool:
    if row.get("who") == "hostile" and subject.team_id == owner.team_id:
        return False
    if row.get("pusher") == "owner" and ctx.actor.entity_id != owner.entity_id:
        return False
    if row.get("sphere") and str(ctx.typed.get("sphere") or "") != str(row["sphere"]):
        return False
    if row.get("option"):
        action = ctx.engine.action_catalog.get(zone.source_definition_id)
        label = str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("option_label")) or "")
        if label.lower() != str(row["option"]).lower():
            return False
    return True


@hook("forced_movement_bonus")
def bonus(ctx: Any, subject: Any, effect: dict[str, Any]) -> int | None:
    from .. import zones
    from .ability_source import mechanic_at

    engine = ctx.engine
    if not any(_rows(engine, actor_id) for actor_id in engine.state.actors):
        return None  # nobody in this fight has such a talent
    total = sum(int(row.get("ft") or 0) for row in _rows(engine, ctx.actor.entity_id) if not row.get("area") and _own(ctx, subject, row, effect))
    for zone in zones.typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or engine.state.zones.get(zone.zone_id) is not zone or not engine._footprint_intersects(subject, zone.affected_cells):
            continue
        made_by = mechanic_at(engine, zone.source_definition_id).split("#")[0]
        total += sum(int(row.get("ft") or 0) for row in _rows(engine, owner.entity_id)
                     if row.get("area") and row.get("feature_id") == made_by and _area(ctx, subject, zone, owner, row))
    return total or None
