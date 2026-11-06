"""The light a creature stands in, read from the light-shedding areas on the fight table.

An area that sheds light records it in its visual profile as
``{"level": "dim" | "bright", "radius_ft": N}``: combat/factory_compiler.py ``_zone_visual`` compiles it from the
printed "Dim Light in a 20-foot radius", and a plug-in writes the same shape when it makes the light itself
(combat/ext/wax_reactions.py ``_light``). ``level(engine, actor)`` answers the light where the creature stands:
Bright Light from an area that covers it, otherwise Dim Light, otherwise ``None`` -- Bright Light is not dim
where it reaches.

Shared helper module (consumer: combat/ext/br_variants.py, for the printed "While standing inside Dim Light or
your Darkness" condition). The map's arenas carry no ambient light, so a creature outside every light-shedding
area stands in no light the table knows, and a condition asking for Dim Light stays unmet there.
"""
from __future__ import annotations

from typing import Any


def _shed(zone: Any) -> str:
    """The light an area gives off ("" when it sheds none; a Darkness area has no light)."""
    light = ((zone.trigger_profile or {}).get("visual") or {}).get("light")
    if isinstance(light, dict):
        light = light.get("level")
    return str(light or "").strip().lower()


def level(engine: Any, actor: Any) -> str | None:
    """``"bright"``, ``"dim"`` or ``None``: the light where ``actor`` stands."""
    from .. import zones

    shed = {_shed(zone) for zone in zones.typed_zones(engine) if zones.actor_inside_zone(engine, actor, zone)}
    return "bright" if "bright" in shed else "dim" if "dim" in shed else None
