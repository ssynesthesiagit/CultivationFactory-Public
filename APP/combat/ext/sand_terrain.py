"""Sand Terrain queries shared by the Sand sphere plug-ins (rider lane C4, 2026-09-30). Used by combat/ext/sand_burial.py
and combat/ext/sand_riders.py; any plug-in may call these public helpers. Pure queries: no state, no events.

Sphere of Sand core rules: "Sand Terrain is a Sand-specific terrain state ... A square can hold only one strength of Sand
Terrain from you at a time: Shallow, Deep, or Storming. Shallow Sand Terrain is the default." and Glass Desert Judgment:
"Glass Terrain counts as Sand Terrain and a Sand Source for your Sand talents".

Sand Terrain a creature controls is a typed zone it owns whose ground is sand (combat/rules/terrain.json gives every named
Sand Terrain the visual material "sand"), or Glass Terrain left by one of its own Sand-sphere abilities. A zone's strength
comes from the terrain names it carries ("deep sand terrain", "storming sand terrain"); none named means Shallow.
"""
from __future__ import annotations

from typing import Any

SAND = "tianxia.sphere.sand"
_STRENGTHS = (("deep", "deep sand terrain"), ("storming", "storming sand terrain"), ("shallow", "shallow sand terrain"))


def _sand_source(engine: Any, zone: Any) -> bool:
    action = engine.action_catalog.get(zone.source_definition_id)
    return action is not None and ((action.parameters or {}).get("typed") or {}).get("sphere") == SAND


def is_sand(engine: Any, zone: Any) -> bool:
    """Whether a zone is Sand Terrain for its owner's Sand talents."""
    material = str((zone.trigger_profile.get("visual") or {}).get("material") or "")
    terrain = [str(name).lower() for name in zone.trigger_profile.get("terrain") or []]
    if material == "sand" or any(name.endswith("sand terrain") for name in terrain):
        return True
    return "glass terrain" in terrain and _sand_source(engine, zone)


def sand_zones(engine: Any, owner_id: str) -> list[Any]:
    """The Sand Terrain ``owner_id`` controls right now."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.owner_id == owner_id and is_sand(engine, zone)]


def strengths(zone: Any) -> set[str]:
    """{"shallow", "deep", "storming"}: the strengths a Sand Terrain zone has (Shallow when it names none)."""
    terrain = {str(name).lower() for name in zone.trigger_profile.get("terrain") or []}
    found = {strength for strength, name in _STRENGTHS if name in terrain}
    return found or {"shallow"}


def standing_in(engine: Any, owner_id: str, creature: Any, kinds: set[str] | None = None) -> bool:
    """Whether ``creature`` stands in Sand Terrain ``owner_id`` controls (of one of ``kinds``, when given)."""
    return any(engine._footprint_intersects(creature, zone.affected_cells) and (kinds is None or strengths(zone) & kinds)
               for zone in sand_zones(engine, owner_id))


def within_ft(engine: Any, owner_id: str, creature: Any, feet: int) -> bool:
    """Whether ``creature`` is within ``feet`` of a square of Sand Terrain ``owner_id`` controls (0 when standing in it)."""
    cells = engine._actor_cells(creature)
    return any(zone.affected_cells and engine.grid.distance_between_cell_sets_ft(cells, zone.affected_cells) <= feet
               for zone in sand_zones(engine, owner_id))


def touching_created_glass(engine: Any, creator_id: str, creature: Any) -> bool:
    """Footprint contact with active created Glass Terrain, from any sphere.

    The source action's sealed owner proves the creator, independently of current
    terrain control. Loose/held glass and other object contacts are not represented
    by this zone query; callers must retain that prerequisite limitation.
    """
    from .. import zones

    for zone in zones.typed_zones(engine):
        source = engine.action_catalog.get(zone.source_definition_id)
        if source is None or source.owner_id != creator_id:
            continue
        material = str((zone.trigger_profile.get("visual") or {}).get("material") or "").lower()
        terrain = {str(name).lower() for name in zone.trigger_profile.get("terrain") or []}
        if (material == "glass" or "glass terrain" in terrain) and engine._footprint_intersects(creature, zone.affected_cells):
            return True
    return False
