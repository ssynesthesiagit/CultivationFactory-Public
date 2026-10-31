"""Shared compass wording for tracking rows that tell their owner where a creature is.

The bearing itself is plain geometry and every tracking ability prints the same idea, so both consumers read
it here instead of each carrying its own copy:

  * combat/ext/smoke_tracking.py -- Follow the Soot (``condition:typed.smoke_follow_soot``) and the extended
    Soot-Scent Trail result (``condition:typed.smoke_trace``), through ``status_description``;
  * combat/ext/smoke_sound_residual.py -- Smoke Mirror Trail (``condition:typed.mirror_trail``), through its
    ``status_description`` card and its private ``observer_information`` fact for the owner's own view.

Nothing here reads or writes fight state: every answer is derived from the two creatures' current positions,
so it is still right after a table commit, a cold reload and the target moving.
"""
from __future__ import annotations

from typing import Any

#: The reach the Smoke and Soot tracking lines print for their direction knowledge.
TRACKING_REACH_FT = 120


def compass(owner: Any, target: Any) -> str:
    """The eight-way bearing of ``target`` seen from ``owner``; ``here`` for the same square."""
    dx = target.position.x - owner.position.x
    dy = target.position.y - owner.position.y
    north_south = "north" if dy < 0 else "south" if dy > 0 else ""
    east_west = "west" if dx < 0 else "east" if dx > 0 else ""
    return "-".join(part for part in (north_south, east_west) if part) or "here"


def within_reach(engine: Any, owner: Any, target: Any,
                 reach_ft: int = TRACKING_REACH_FT) -> str | None:
    """The bearing while the target is inside ``reach_ft``; None outside it.

    The printed tracking lines all say the knowledge holds only "while it remains within 120
    feet", so a caller presents no bearing at all outside the reach rather than a stale one.
    The tracked creature's distance is not part of what these lines grant, so it is never
    returned: a caller that needs to say why it has no answer names the printed reach instead.
    """
    if int(engine._distance_actor_to_actor(owner, target)) > reach_ft:
        return None
    return compass(owner, target)
