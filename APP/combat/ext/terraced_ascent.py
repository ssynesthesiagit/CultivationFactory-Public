"""Terraced Ascent: the printed Earth creation as one lasting run, not free movement.

The record prints a creation ("Create stairs, ramps, terraces, footholds, or a
compacted slope across a solid surface") that covers "up to eight 5-foot
spaces" and may "ascend or descend up to 30 feet total". The reviewed record
carries that as a zone with eight connected cubes and an explicit `rise_ft`;
this module clips the constructed run to the printed maximum and records the
creation kind and ascent limit on the zone's own profile.

P4a scope: the fight gets the lasting structure. Walking up or down it is not
automated here -- no height is added to the grid (`zones.add_height`), and no
climb cost, movement surcharge or standing burden is charged. A later lane
(A1-P4b) owns elevation movement.

The engine's ground plane is solid on every in-bounds square (`falling._supported`
answers True at z == 0), so this map does not represent unsupported/empty-air
cells. This module therefore judges no surface: it neither rejects a creation
nor claims the record's freestanding-bridge rider.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from . import hook

CELL_LIMIT = 8          # "The structure covers up to eight 5-foot spaces."
RISE_FT_MAX = 30        # "It may ascend or descend up to 30 feet total."
SEED = "terraced_ascent"


def creation(typed: dict[str, Any]) -> dict[str, Any] | None:
    """The zone effect this module owns: a creation that names its ascent limit.

    Keyed on the reviewed data, not an ability id: a generic area has no
    `rise_ft` and this module stays inert for it.
    """
    for effect in typed.get("effects") or ():
        if isinstance(effect, dict) and effect.get("type") == "zone" and effect.get("rise_ft") is not None:
            return effect
    return None


def rise_ft(effect: dict[str, Any]) -> int:
    """The printed ascent limit, clamped to 30 feet. Never inferred from shape."""
    declared = effect.get("rise_ft")
    try:
        asked = RISE_FT_MAX if declared is None else int(declared)
    except (TypeError, ValueError):
        asked = RISE_FT_MAX
    return min(max(asked, 0), RISE_FT_MAX)


def contiguous(cells: Iterable[Any], center: Any, limit: int = CELL_LIMIT) -> tuple[Any, ...]:
    """At most `limit` face-connected squares, grown from the square nearest the aim point.

    A run the compiler already builds inside the limit is returned unchanged (in
    its own order). A longer or split candidate is clipped by breadth-first
    growth, so every square kept touches one kept before it; the rest are
    dropped rather than invented into a shape the printed text does not give.
    """
    ordered = tuple(cells)
    if len(ordered) <= limit:
        return ordered
    by_cell = {(cell.x, cell.y): cell for cell in ordered}
    seed = min(ordered, key=lambda cell: (abs(cell.x - center.x) + abs(cell.y - center.y), cell.y, cell.x))
    keep: list[Any] = []
    seen = {(seed.x, seed.y)}
    queue = deque([seed])
    while queue and len(keep) < limit:
        cell = queue.popleft()
        keep.append(cell)
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            neighbour = by_cell.get((cell.x + dx, cell.y + dy))
            if neighbour is not None and (neighbour.x, neighbour.y) not in seen:
                seen.add((neighbour.x, neighbour.y))
                queue.append(neighbour)
    kept = {(cell.x, cell.y) for cell in keep}
    return tuple(cell for cell in ordered if (cell.x, cell.y) in kept)


@hook("zone_creation_profile")
def terraced_ascent(zone, ctx):
    effect = creation(ctx.typed or {})
    if effect is None:
        return None
    profile = dict(zone.trigger_profile)
    profile["creation_kind"] = "ascent"
    profile["rise_ft"] = rise_ft(effect)
    return zone.model_copy(update={"trigger_profile": profile,
                                   "affected_cells": contiguous(zone.affected_cells, zone.center)})
