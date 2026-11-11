"""Shared transient record of what is delivering the damage being committed right now.

A printed trigger often limits *where the damage came from* rather than how much of it
there is: "damage from a trap, a collapse, falling stone, burst crystal, mining hazard, or
source-stone discharge" (Source sphere's Mine-Shelter Reflex), "damage from a stone, crystal,
sand, earth, or mineral environmental hazard" (Source Skin). The table's generic "when you take
damage" rows cannot see that, so the damage site states it and the row reads it back.

The frame is one transient engine attribute, ``_typed_pending_damage_source``, held on the
engine for exactly as long as the commit runs and restored on the way out. Nothing is
journalled, stored in a condition, or written into a saved fight: a fight saved before this
seam existed loads and replays identically, and damage committed by engine-internal code that
never opened a frame simply answers "" here (a row with a printed source limit stays off
rather than firing blind).

The frame is a small mapping with four fields:

``identity``
    the delivering catalog id -- exactly what ``combat/typed_executor.py`` already knows as
    ``Context.damage_source``.
``hazard``
    the general class of hazard doing the delivering, chosen by the delivery site:
    :data:`TRAP` (a mechanism set to harm a creature), :data:`FALLING` (a fall), or
    :data:`AREA` (a standing area, with ``area`` naming it). These classes are deliberately
    coarse: they say what kind of event the world produced, never which ability did it, so a
    new trap form, a new area or a new fall site needs no change here.
``area``
    the zone id of the area delivering the damage, when there is one: a standing area, or a trap's own
    mechanism (combat/ext/trap.py names the trap's zone here too, because one trap can fire again for
    a second creature and is one delivery however many times it throws).
``event``
    which single activation of that hazard is delivering the damage right now: a name built from how
    many events the fight had journalled when that delivery began and, after it, which activation
    begun there (see :func:`_next_serial`). Every site that opens a frame *with* a hazard class gets one,
    and the commits that belong to that activation carry it. One springing of one tripwire is one
    activation and a later springing of the same wire is another, so "the same triggering damage" can
    mean the springing and not the mechanism -- and, because the fight's journal is saved with the fight
    and only grows, the name still tells those two apart after a table commit and reload, when a name
    from nothing but an in-memory counter would restart and repeat.

**Continuing, or a new delivery.** A commit only inherits the hazard around it when it is part of
*that* delivery: the typed executor passes the identity its own ``Context.typed["source"]`` carries,
which is the very string the delivery site opened the frame with (a trap's ``trap:<zone id>``, an
area's own trigger id), so the area's own damage and a trap's own dart keep their provenance. Anything
else that commits inside the frame is its own source -- a Reaction's returned damage, a talent fired
by an area's trigger -- and starts a new delivery with no hazard at all, so "damage from a trap"
never answers damage that merely happened while a trap was resolving.

Consumers: ``combat/typed_executor.py`` (typed damage rows and typed attacks open the frame
with the delivering action's own identity), ``combat/falling.py`` (a fall, which commits
outside the typed executor), ``combat/zones.py`` (an area's own trigger and move-through
effects), ``combat/ext/trap.py`` (a trap, whose Dart Mechanism resolves a native attack
outside the typed executor), and readers of a printed source limit --
``combat/ext/source_sphere.py``'s two guard Reactions and the shared Resistance that hangs on
one of them.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

#: The transient engine attribute the frame lives on. Documented in combat/ext/__init__.py.
ATTR = "_typed_pending_damage_source"

#: The transient counter that separates two activations begun inside one commit chain. Never journalled
#: and never stored in a fight; the reload-stable half of an activation's name is the journal length (see
#: :func:`_next_serial`).
SERIAL_ATTR = "_typed_delivery_serial"

#: General hazard classes a delivery site may declare.
TRAP = "trap"
FALLING = "falling"
AREA = "area"

_EMPTY: dict[str, str] = {"identity": "", "hazard": "", "area": "", "event": ""}
_MISSING = object()


def _next_serial(engine: Any) -> str:
    """One new activation name, as a string (a transient frame never holds anything else).

    "<how many events the fight had journalled when this delivery began>.<which activation begun here>".
    The first half is what makes the name survive a table commit. The fight's journal is written to disk
    with the fight and read back when it is loaded (combat/gate4_persistence.py restores ``engine.events``
    from the stored events), and it only ever grows, so an activation begun before a commit names a
    shorter journal than any activation begun after it. A mark that outlived that commit therefore can
    never be read as naming the activation that came after it, which an engine-only counter restarting at
    zero did allow: the first hazard a freshly loaded engine delivered was "1", exactly like a springing
    paid for before the save.

    The second half separates two activations begun inside one commit chain with nothing journalled
    between them. Neither half is stored anywhere but the frame that carries it.
    """
    journalled = len(getattr(engine, "events", ()) or ())
    number = int(getattr(engine, SERIAL_ATTR, 0) or 0) + 1
    setattr(engine, SERIAL_ATTR, number)
    return f"{journalled}.{number}"


def open_frame(engine: Any, identity: str | None = None, *, hazard: str | None = None,
               area: str | None = None, continues: str | None = None) -> Any:
    """State what is delivering the damage; returns the token :func:`close_frame` puts back.

    A ``hazard`` means a delivery site is starting a delivery: it gets a fresh ``event`` number, so
    this springing of a trap is never the last one. Without a ``hazard`` this is a commit inside
    whatever is already being delivered, and it continues that delivery only when it says so -- by
    naming it in ``identity`` or in ``continues`` (the typed executor passes the source its own
    ``Context.typed`` carries, which is the string the site opened the frame with). A commit naming
    some other source is a delivery of its own and inherits no hazard, no area and no event.

    Only the fields given are set on a continuing commit, so an area's own damage keeps the area it
    belongs to. ``close_frame`` restores the whole previous frame, including when the commit raised,
    so a nested delivery never leaks into the one still resolving. Sites that do not need a ``with``
    block (a long existing commit in ``combat/typed_executor.py``) use these two functions directly.
    """
    previous = getattr(engine, ATTR, _MISSING)
    outer = {**_EMPTY, **previous} if isinstance(previous, dict) else dict(_EMPTY)
    if hazard is not None:
        frame = {"identity": str(identity or ""), "hazard": str(hazard), "area": str(area or ""),
                 "event": _next_serial(engine)}
    elif outer["hazard"] and not {str(identity or ""), str(continues or "")} & {outer["identity"]}:
        # Some other source's damage, committed while a hazard was resolving (a Reaction's own
        # return, a talent an area's trigger fired): its own delivery, with no hazard behind it.
        frame = {"identity": str(identity or ""), "hazard": "", "area": "", "event": ""}
    else:
        frame = dict(outer)
        if identity is not None:
            frame["identity"] = str(identity)
        if area is not None:
            frame["area"] = str(area)
    setattr(engine, ATTR, frame)
    return previous


def close_frame(engine: Any, token: Any) -> None:
    """Put back the frame :func:`open_frame` replaced."""
    if token is _MISSING:
        try:
            delattr(engine, ATTR)
        except AttributeError:  # pragma: no cover - another site already unwound it
            pass
    else:
        setattr(engine, ATTR, token)


@contextmanager
def delivering(engine: Any, identity: str | None = None, *, hazard: str | None = None, area: str | None = None) -> Iterator[None]:
    """State what is delivering the damage for the duration of the block, then put it back."""
    token = open_frame(engine, identity, hazard=hazard, area=area)
    try:
        yield
    finally:
        close_frame(engine, token)


def key(engine: Any) -> tuple[str, str]:
    """One stable name for the delivery committing right now: its hazard class and the thing doing the
    delivering (its area's zone id where there is one, else the delivering id). Two activations of the
    same trap or the same area share it; a second trap does not. Use :func:`event` when the printed
    rule names one triggering damage rather than the thing doing the damage."""
    current = frame(engine)
    return current["hazard"], current["area"] or current["identity"]


def event(engine: Any) -> str:
    """Which single activation of the hazard is delivering the damage right now ("" when none is).

    One springing of a tripwire, one fall, one crossing of a standing area's own trigger: each is its
    own event, and every commit that belongs to it carries the same number, so a later springing of the
    same wire is a different event however identical the two look."""
    return frame(engine)["event"]


def frame(engine: Any) -> dict[str, str]:
    """The whole delivery frame right now (empty fields when nothing is being delivered)."""
    current = getattr(engine, ATTR, None)
    return {**_EMPTY, **current} if isinstance(current, dict) else dict(_EMPTY)


def identity(engine: Any) -> str:
    """The catalog id delivering the damage being committed right now ("" when none is)."""
    return frame(engine)["identity"]


def hazard(engine: Any) -> str:
    """The hazard class delivering the damage right now: :data:`TRAP`, :data:`FALLING`,
    :data:`AREA`, or "" for a delivery that is none of those."""
    return frame(engine)["hazard"]


def area(engine: Any) -> str:
    """The zone id of the standing area delivering the damage right now ("" when none is)."""
    return frame(engine)["area"]