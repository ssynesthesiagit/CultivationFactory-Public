"""Shadowed Spaces: the squares that hold shadow (the Shadow sphere's core rules).

A 5-foot space is a **Shadowed Space** when it is

* one of the owner's **Shadow Anchors** (see combat/ext/shadow.py: `anchors`);
* in **Dim Light or Darkness**, as the lighting model resolves that square; or
* holding a **Cast Shadow** (see `_cast_shadow_cells`).

The light comes from combat/lighting.py. An absent or Bright map ambient level is Bright (spec
OQ-1), so a fight with no `battlefield_document`, or one that declares "bright" with no light
sources, contributes no Dim or Dark squares: only anchors and cast shadows are Shadowed Spaces.
Cast shadows fall only where a declared light source exists, so with no sources there are none.

Shared helper module (consumers: combat/ext/shadow.py -- Shadow Ward's Shadowed Space
Proficiency Bonus, Shadow Bind's target eligibility, Shadow Step's squares and the Shadow
Exchange and Shadowless Reversal landings). It only reads the fight: it never writes state,
never rolls and never changes a menu. combat/ext/shadow.py and this module import each other;
both imports are deferred inside functions, so there is no import cycle at load time.
"""

from __future__ import annotations

from typing import Any

from .. import lighting


def _anchor_cells(engine: Any, owner: Any) -> set[tuple[int, int]]:
    """The owner's Shadow Anchors, read from the Shadow sphere's own anchor helper."""
    from . import shadow

    return {(int(cell.x), int(cell.y)) for cell in shadow.anchors(engine, owner)}


def _dim_cells(engine: Any) -> set[tuple[int, int]]:
    """The squares the lighting model resolves as Dim Light or Darkness.

    The field carries only squares that differ from the map's ambient floor, so a Dim or Dark map is the floor
    everywhere except where a declared light or region lifts a square to Bright. Those lifted squares are not
    Shadowed Spaces: a torch-lit square on a Dim map is Bright, and a torch-lit square on a Dark map is Bright too.
    """
    floor = int(lighting.ambient(engine)["level"])
    levels = dict(lighting.field(engine) or {})
    # Darkness zones are applied after the physical field; include their cells as genuinely dark.
    from .. import zones
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        visual = profile.get("visual") or {}
        if zone.active and visual.get("darkness"):
            for cell in zone.affected_cells:
                levels[(int(cell.x), int(cell.y))] = lighting.DARK
    if floor >= lighting.BRIGHT:
        return {(int(x), int(y)) for (x, y), level in levels.items() if int(level) < lighting.BRIGHT}
    # Below bright light the whole map is in shadow except the squares that a declared source lifts to Bright.
    lifted = {(int(x), int(y)) for (x, y), level in levels.items() if int(level) >= lighting.BRIGHT}
    return {(x, y) for y in range(int(engine.grid.height)) for x in range(int(engine.grid.width))} - lifted


def _cast_shadow_cells(engine: Any) -> set[tuple[int, int]]:
    """The squares that hold a creature's or an object's Cast Shadow.

    A cast shadow lies on the side away from the light: the nearest declared light source
    gives the direction, and the shadow falls in the neighbouring square. No declared
    source means no known direction, so no cast shadow is claimed.
    """
    sources = [source for source in lighting.sources(engine) if source.cells and source.level is None]
    if not sources:
        return set()
    out: set[tuple[int, int]] = set()
    square = int(getattr(engine.grid, "square_size_ft", 5) or 5)
    actors = engine.state.actors
    detached_sources = {
        str(record.get("owner"))
        for lurk in actors.values()
        if lurk.active
        for record in [getattr(lurk, "summon", None) or {}]
        if record.get("group") == "shadow_lurk" and record.get("owner")
    }
    for creature in actors.values():
        if not creature.active or creature.entity_id in detached_sources:
            continue
        here = (int(creature.position.x), int(creature.position.y))
        best = None
        for source in sources:
            radius = source.dim_ft // square
            if radius <= 0:
                continue
            for (sx, sy) in source.cells:
                dx, dy = here[0] - sx, here[1] - sy
                distance = max(abs(dx), abs(dy))
                # Match lighting.field(): radius is quantized in whole squares and light stops at terrain.
                if distance > radius or not lighting._Disc(engine.grid, sx, sy).clear(*here):
                    continue
                if best is None or distance < best[0]:
                    best = (distance, sx, sy)
        if best is None or best[0] == 0:
            continue
        step_x = (1 if here[0] > best[1] else -1) if here[0] != best[1] else 0
        step_y = (1 if here[1] > best[2] else -1) if here[1] != best[2] else 0
        out.add((here[0] + step_x, here[1] + step_y))
    return out


def shadowed_cells(engine: Any, owner: Any) -> set[tuple[int, int]]:
    """Every square that is a Shadowed Space for the given owner.

    Derived from the lighting model alone: an absent ambient is Bright (OQ-1), so an undeclared
    map adds no Dim or Dark squares and the answer is only the owner's anchors and cast shadows.
    """
    cells = _anchor_cells(engine, owner)
    cells |= _dim_cells(engine)
    cells |= _cast_shadow_cells(engine)
    return cells


def is_shadowed(engine: Any, owner: Any, cell: Any) -> bool:
    """Whether the given cell is one of the owner's Shadowed Spaces."""
    if cell is None:
        return False
    return (int(cell.x), int(cell.y)) in shadowed_cells(engine, owner)
