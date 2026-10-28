"""Drunken Fist Subpath riders (rider lane C7, 2026-09-30).

Heavenly Drunk, "Standing from Prone costs no movement": the native stand_cost
query returns zero while its state is active. The shared posture transition owns
the condition removal and STOOD_UP event, for turn starts and explicit standing.
Inert without the state. The walking_cost hook also implements "Crawl at your
full Speed" by waiving the extra crawl cost, without ignoring difficult terrain.
"""

from __future__ import annotations

from typing import Any

from . import hook

STATE = "heavenly_drunk"


@hook('walking_cost')
def normal_crawl(engine: Any, actor: Any, normal_extra: int) -> int | None:
    from .states import active
    if actor.active and active(engine, actor, STATE):
        return 0
    return None


@hook("stand_cost")
def free_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    from .states import active

    if actor.active and active(engine, actor, STATE):
        return 0
    return None


@hook("movement_pass_through")
def hostile_spaces_are_difficult(engine: Any, mover: Any, occupant: Any) -> bool | None:
    """Heavenly Drunk (tianxia.subpath.body.drunken_fist.feature.heavenly_drunk): while it is active, enemy-occupied spaces are difficult terrain you may pass through. Ending the move in an occupied space is still not allowed."""
    from ..relations import ENEMY, relation
    from .states import active

    if mover.active and occupant is not None and relation(engine, mover, occupant) == ENEMY and active(engine, mover, STATE):
        return True
    return None
