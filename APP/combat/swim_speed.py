"""Swim Speed: the one published per-creature lookup for "can this creature swim?".

Several printed riders turn on a creature having Swim Speed -- "Hostile creatures without Swim Speed
treat the area as Difficult Terrain" (Water, Flood the Battlefield) is the one that reached this
round. The runtime models carry only walking, flying and climbing speed (gate2_runtime_models.py), so
before this module there was nowhere for such a rider to read, and a lane that needed one had to
either invent an actor field or decline the whole clause.

``swim_speed_ft(engine, actor)`` is that read: a pure per-creature query returning the creature's Swim
Speed in feet, or 0 when it has none. It answers from the ``swim_speed`` plug-in hook documented in
combat/ext/__init__.py, so an ability that grants Swim Speed supplies the number and no core actor
model changes.

This is a general seam, not a Flood special case: it takes no ability id, reads no Flood state, and
returns the same answer for every caller. With no subscriber every creature reports no Swim Speed,
which is exactly today's behaviour for every existing ability.

Shared by: the Water Flood the Battlefield rider (combat/ext/water_flood.py) and any future ability
whose printed text turns on a creature having Swim Speed.
"""

from __future__ import annotations

from typing import Any

from . import ext


def swim_speed_ft(engine: Any, actor: Any) -> int:
    """This creature's Swim Speed in feet; 0 when it has none.

    Pure query, no state read or write, default-inert: the largest value any ``swim_speed`` subscriber
    reports for this creature, and 0 when nobody answers or nothing usable is reported. A negative or
    unparseable answer is treated as "no Swim Speed" rather than guessed into a number.
    """
    if actor is None:
        return 0
    best = 0
    for value in ext.run('swim_speed', engine, actor):
        try:
            feet = int(value)
        except (TypeError, ValueError):
            continue
        if feet > best:
            best = feet
    return best


def can_swim(engine: Any, actor: Any) -> bool:
    """Whether this creature has any Swim Speed at all. The usual form of a "without Swim Speed" rider."""
    return swim_speed_ft(engine, actor) > 0