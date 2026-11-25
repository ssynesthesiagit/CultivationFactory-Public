"""The same buff does not stack across copies of one Concentration technique (owner ruling 2026-09-29: "they can hold any
number of the same spells as long as they arent the same stacking buff or something").

A fighter may hold a technique more than once (combat/concentration.py): each copy has its own slot, zone and effects. When
a newer copy puts an effect that lasts as long as its Concentration on a creature that already has an older copy's same
effect -- the same modifier field (a "+2 AC while you concentrate"), or the same condition with the same rule -- the older
copy's is taken off that creature (a MODIFIER_REMOVED / CONDITION_REMOVED event, reason SUPERSEDED), so the creature has one,
not two. The older copy stays held for anything else it does: other creatures, its area. The engine's own typed modifiers
(typed_executor._modifier) already refresh a same-source modifier; this covers the rest, conditions among them.

Replays derive the same result: the supersession is evented like any other removal.
"""

from __future__ import annotations

from typing import Any

from . import hook


@hook("event")
def one_of_a_kind(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("MODIFIER_APPLIED", "CONDITION_APPLIED"):
        return
    from .. import concentration

    concentration.supersede(engine, engine.events[-1])
