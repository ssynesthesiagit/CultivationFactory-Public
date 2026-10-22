"""Areas laid down at the point the user aims at (hunt 68, fix-up MMX31).

A printed Range longer than a line's or cone's own length is a *placement* range:
Earthbind Line is "Range: 60 feet ... Area: 20-foot line on a solid or earthen surface",
so the user picks a point up to 60 feet away and the 20-foot line starts there
(``combat/factory_compiler.py`` ``_aimed_area`` marks that area ``placed``).

This module owns the one case the printed rules leave open: what happens when the chosen
point is the caster's own square. A line and a cone are paths -- they need a direction to
run in -- and a point on the caster's own square gives none, with no printed rule saying
which way a line laid down under your own feet should run. Rather than invent a direction
or silently spend the action, the aim is not offered as a choice at all, so the action is
refused before any Stamina, CP, action or turn is spent. ``combat/typed_executor.py``
``aim_gives_direction`` is the shared decision; the geometry there, the table's preview and
the persistent zones all agree because they all read the same answer.

Inert for everything else: an older or unmarked area without ``placed``, an action with
no destination, an area other than a line or cone, and any aim point other than the
caster's own square retain their previous candidates. Older saved actions without the
placement marker keep their original directionless-zone fallback.
"""
from __future__ import annotations

from typing import Any

from . import hook


@hook("candidate_allowed")
def a_line_aimed_at_its_user_own_square(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Leave out an aim a line or cone has no direction to run in from. None keeps every other choice."""
    from .. import typed_executor

    destination = getattr(candidate, "destination", None)
    if destination is None:
        return None
    area = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("area") or {}
    if not area.get("placed"):
        return None
    return None if typed_executor.aim_gives_direction(area, actor.position, destination) else False
