"""Shared helpers for plug-ins that key off a character's own compiled passive rows (a feature_blocks.d entry with a "block" of
its own and a "kind"; the shape combat/ext/eye_common.py's ``has`` reads for the Hidden Eye). No hook is registered here."""

from __future__ import annotations

from typing import Any


def row_of(engine: Any, actor_id: str, block: str, kind: str) -> dict[str, Any] | None:
    """The actor's compiled passive row of this block and kind, or None (the actor does not have the feature)."""
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
                 if row.get("block") == block and row.get("kind") == kind), None)


def known_level(engine: Any, creature: Any) -> int | None:
    """A creature's Cultivation Level when it is a compiled Factory character (its bundle records it); None when this table does
    not track one (a monster is not given a CR here)."""
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == creature.entity_id and bundle.get("cl") is not None:
            return int(bundle["cl"])
    return None


def melee_or_thrown(ctx: Any) -> bool:
    """A typed weapon attack made in melee (any reach) or thrown -- not one fired from a bow or sling (its typed ``range_ft`` is
    its shooting range; a melee weapon carries none)."""
    return str(ctx.action.source_definition_id).endswith("#thrown") or not (ctx.typed.get("range_ft") or ctx.typed.get("long_range_ft"))
