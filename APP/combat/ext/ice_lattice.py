"""Ice's Lattice Space (owner 2026-09-28, "automate every aspect before another playtest", wave 3).

Shared API for ice_second_pass: counted_spaces lists cap-counted individual zones;
lattice_limit quotes their printed cap. scholar_space supplies the Insight's
optional additional space after one Crystallize Path creation.

The Ice sphere's core resource is a set of individually-tracked 5-foot "Lattice Spaces" a cultivator
places on the battlefield (Tianxia_Sphere_Compendium's Ice "Lattice Limit"/"Lattice Spaces" sections):
capped at Proficiency Bonus + Key Ability modifier (minimum 3), each destructible on its own, each lasting
until dismissed/destroyed/1 minute. combat/zones.py's ``create()`` places one ZONE per activation covering
however many cells an area's shape works out to (Darkness, Ashfall) -- not a set of N separately-tracked,
separately-destructible small zones, which is what "Create a number of Lattice Spaces equal to your
Proficiency Bonus" (Avalanche Writing) needs. This module's ``lattice_spaces`` effect type does that:
one ZoneState per space, each 5 feet, tagged so the sphere's own cap (mirroring
combat/ext/elements_marks.py's mark_caps, but for zones instead of marks -- no existing block does this)
can find and enforce them.

Of the fielded characters' seven Lattice-Space-named records (Avalanche Writing, Crystal Weather Script,
Frost-Sheathed Guard, Frozen Meridian Bind, Frozen River Reversal, Frozen Trajectory Seal, Immortal Winter
Crucible):

- Avalanche Writing is the only one that actually CREATES Lattice Spaces in its own printed text; retyped
  here to use ``lattice_spaces`` (cap-exempt, per its own "do not count against your Lattice Limit").
- Immortal Winter Crucible references Lattice Spaces it created (creating one extra whenever it creates
  any; dealing damage when one it made is destroyed; ending half of them when the stance ends) but the
  previous typing had none of that -- instead an unconditional flat "deal Proficiency Bonus damage to a
  hostile creature" effect with no trigger at all, free damage every time the stance's other effects ran.
  Removed; GM-run riders explain why (no hook fires on a specific zone's destruction yet, and "whenever you
  create Lattice Spaces, create one more" would need this module's own Avalanche-Writing-style effect to
  read a stance flag it does not carry).
- Crystal Weather Script, Frost-Sheathed Guard, and Frozen River Reversal do not create or require a
  Lattice Space at all despite the "Lattice" tag/theme in their printed text (checked against
  Tianxia_Sphere_Compendium directly) -- left untouched.
- Frozen Meridian Bind's own trigger ("you spend a Fracture Mark with Catch Step and the target is on or
  adjacent to one of your Lattice Spaces") sits on top of the Fracture-Mark Response menu (Catch Step,
  Shatter Space, ...), a separate reactive framework this task does not own; its own save/spend_mark body
  was already reasonably typed and is left alone, with the Lattice-adjacency precondition GM-confirmed.
- Frozen Trajectory Seal does not mention Lattice Spaces in its own printed text (only in nearby talents);
  left untouched.
"""

from __future__ import annotations

from typing import Any

from . import effect


def lattice_limit(numbers: dict[str, Any]) -> int:
    """"You can maintain a number of 5-foot Lattice Spaces equal to your Proficiency Bonus + your Key
    Ability modifier, minimum 3" (Ice's Lattice Limit)."""
    return max(3, int(numbers.get("pb") or 0) + int(numbers.get("key_mod") or 0))


def counted_spaces(engine: Any, owner_id: str) -> list[Any]:
    return sorted((zone for zone in engine.state.zones.values() if zone.active and zone.owner_id == owner_id
                  and zone.trigger_profile.get("lattice_space") and not zone.trigger_profile.get("lattice_cap_exempt")),
                 key=lambda zone: zone.created_round)


def _nearby_cells(engine: Any, center: Any, count: int) -> list[Any]:
    """``count`` grid cells at or around ``center`` (Avalanche Writing: "Each new space must be adjacent to
    the triggering creature's path, destination, or starting space" -- approximated as the creature's own
    space plus the nearest unoccupied ring around it; exact surface/adjacency legality per the sphere's
    placement rules is GM-confirmed, same simplification Glacier Wall's own object HP/AC already takes)."""
    from ..gate2_runtime_models import Position

    seen: set[tuple[int, int]] = set()
    cells: list[Any] = []
    ring = 0
    while len(cells) < count and ring <= 3:
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                point = (center.x + dx, center.y + dy)
                if point in seen or not engine.grid.in_bounds(point):
                    continue
                seen.add(point)
                cells.append(Position(x=point[0], y=point[1]))
                if len(cells) >= count:
                    break
            if len(cells) >= count:
                break
        ring += 1
    return cells


@effect("lattice_spaces")
def _lattice_spaces(ctx: Any, spec: dict[str, Any]) -> None:
    from ..gate2_runtime_models import ZoneState

    engine, actor = ctx.engine, ctx.actor
    cl = int(ctx.numbers.get("cl") or 1)
    by_cl = next((int(n) for low, high, n in spec.get("count_by_cl") or [] if low <= cl <= high), None)  # Crystallize Path (rider lane 9)
    count = by_cl if by_cl is not None else max(0, ctx.formula(spec.get("formula") or "pb") + int(spec.get("flat") or 0))
    if count > 0 and any(c.condition_id == "condition:typed.winter_crucible" for c in actor.conditions.values()):
        count += 1  # Immortal Winter Crucible: "whenever you create one or more Lattice Spaces, create one additional Lattice Space"
    if count <= 0:
        return
    cap_exempt = bool(spec.get("cap_exempt"))
    if not cap_exempt:
        existing = counted_spaces(engine, actor.entity_id)
        # Nascent Soul: Glacier Soul Takes Shape: "your Lattice Limit increases by your Proficiency Bonus" (combat/ext/ice_fracture.py rows)
        nascent = any(row.get("block") == "lane9_ice" and row.get("kind") == "nascent"
                      for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))
        over = len(existing) + count - lattice_limit(ctx.numbers) - (int(ctx.numbers.get("pb") or 0) if nascent else 0)
        for zone in existing[:max(0, over)]:
            from .. import zones

            zones.remove(engine, zone, "LATTICE_LIMIT")
    duration = spec.get("duration") or {}
    duration_rounds = {"one_round": 1, "until_start_of_next_turn": 1, "until_end_of_next_turn": 1, "one_minute": 10}.get(
        str(duration.get("kind") or ""), None)
    destination = getattr(ctx.intent, "destination", None)
    center = ctx.target.position if ctx.target is not None else destination if destination is not None else actor.position
    for cell in _nearby_cells(engine, center, count):
        zone_id = f"zone:lattice:{actor.entity_id}:{engine.state.event_sequence + 1}:{cell.x}:{cell.y}"
        zone = ZoneState(
            zone_id=zone_id, source_definition_id=ctx.source, owner_id=actor.entity_id, center=cell, radius_cells=0,
            affected_cells=(cell,), concentration_link=False, duration_rounds=duration_rounds, created_round=engine.state.round_number,
            trigger_profile={"kind": "TYPED", "name": "Lattice Space", "terrain": [], "difficult": None, "obscured": None,
                             "color": "#bfe8ff", "follows_owner": False, "shape": "sphere", "size_ft": 5, "triggers": [],
                             "move_through": None, "talents": [], "inside": [], "visual": {"material": "ice"},
                             "numbers": dict(ctx.numbers), "lattice_space": True, "lattice_cap_exempt": cap_exempt},
        )
        # Domain-created spaces end with their parent. Include the link in the
        # first snapshot, before recording creation or notifying subscribers.
        if spec.get("ends_with"):
            zone.trigger_profile["ends_with"] = str(spec["ends_with"])
        engine.state.zones[zone_id] = zone
        engine._append_event("ZONE_CREATED", ctx.source, actor_id=actor.entity_id, payload={"zone": zone.model_dump(mode="json")})
    if str(ctx.typed.get("source") or "") == "ICE_BASE_CRYSTALLIZE_PATH":
        from .ice_second_pass import scholar_space
        scholar_space(ctx)
