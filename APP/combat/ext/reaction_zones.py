"""Named-zone line requirements for reactions, including Blind the Line.

The trigger compiler supplies the printed zone name. Geometry uses the actual
attacker and attacked creature, never the observer-to-attacker line.
"""
from typing import Any

from . import hook


@hook("reaction_geometry_allowed")
def zone_line_allowed(engine: Any, reactor: Any, source: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    name = row.get("requires_zone_los")
    if not name:
        return None
    if source is None or subject is None:
        return False
    from .. import zones

    ray = set(engine.grid.ray_cells(source.position, subject.position))
    return any(zone.owner_id == reactor.entity_id and
               str(zone.trigger_profile.get("name") or "").casefold() == str(name).casefold() and
               any((cell.x, cell.y) in ray for cell in zone.affected_cells)
               for zone in zones.typed_zones(engine))
