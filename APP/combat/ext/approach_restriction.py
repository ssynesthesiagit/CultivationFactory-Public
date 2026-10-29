"""The approach restriction's one deliberate gap: a voluntary teleport closer.

Owner 2026-10-05 (AUTO16f1 review, finding 3): "cannot willingly move closer to you" is a
restriction on the holder's own choices, so a teleport the holder chooses and that lands it
closer is a voluntary approach like any other step. combat/voluntary_movement.py filters
physical paths, which is all Frightened needs -- its printed rule is about steps -- but a printed
"cannot willingly move closer" (Name-Striking Tone's Kept at Distance, World-Transfixing Point,
Sever the Battle Line, Consume Fear) is worded without that limit.

This module closes the gap through the engine's existing ``teleport_check`` seam, and only for the
rules that need no sight: a creature holding Kept at Distance cannot teleport itself next to the
creature that kept it there, while Frightened's step rule is untouched. A creature with no such
condition is never queried, so saved fights, AI fights and every other creature behave exactly as
before. Forced displacement is not a teleport and never reaches here.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .placed import note
from ..voluntary_movement import unconditional_sources


@hook("teleport_check")
def approach_restriction(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    """A voluntary teleport that would land the holder next to a source of an unconditional
    ``no_approach`` condition fails, and says so in plain words. Nothing else changes."""
    sources = unconditional_sources(engine, actor)
    if not sources:
        return None
    for source in sources:
        before = engine._distance_actor_to_actor(actor, source, actor_position=start)
        after = engine._distance_actor_to_actor(actor, source, actor_position=destination)
        if after < before:
            note(engine, "condition:typed.no_approach", actor,
                 f"Kept at Distance: {actor.display_name} cannot teleport closer to {source.display_name}.")
            return False
    return None