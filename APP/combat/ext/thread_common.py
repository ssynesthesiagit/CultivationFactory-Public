"""Shared Thread Sphere queries: Thread range, whether a Thread Line is still on a creature, and the squares
one of a user's Thread Lines runs through.

These are the Thread Sphere's own printed numbers and printed geometry read in ONE place, so every Thread
talent asks them the same way and none of them keeps a second, divergent copy (change standard, modularity 5:
shared logic goes in a named helper module that says who uses it).

Users:
  * combat/ext/thread_correction.py -- Puppet-Line Correction and Borrow the Ally's Arm, whose printed triggers
    are "a creature connected to your Thread Line" / "connected to one of your Thread Lines", and whose range the
    printed text leaves as "Thread range";
  * combat/ext/thread_lines.py -- Draw the Guard / Tighten the Wrist / Needle Guide / Meridian Snare / Meridian
    Stitch (every mark that hangs on a line), and Snaring Crossing, whose printed trigger is "A creature you can
    see moves across a space containing one of your Thread Lines".

Thread range is Draw the Line's own printed range -- "Range: Mundane 20 feet, Qi Thread 30 feet."  A Qi Thread of
the user's, which is the public ``QI_THREAD`` condition of combat/ext/thread_weaving.py, stretches it to 30 feet.

``thread_line_cells`` reads Draw the Line's own words for what a line IS: "you create a Thread Line between
yourself or an anchor you control and the target."  The table has no drawn-line object, so the squares a line
covers are read as the straight run from the Thread user (the anchor the printed text names first) to each
creature carrying their Thread Line mark.  That is the geometry Snaring Crossing crosses.

A line is a physical thing at a height, so its cells carry the third coordinate.  They come from the table's own
exact 3D traversal (``engine.grid.effect_ray_cells``, combat/gate2_grid.py), which includes both ends and enters
only the voxels a thread actually passes through.  Reading the same run without the height made a thread lying on
the ground snare a creature twenty feet above it -- a printed Reaction spent, and a walk stopped, on a crossing
that never happened.
"""

from __future__ import annotations

from typing import Any

MUNDANE_FT = 20
QI_FT = 30
LINE = "Thread Line"


def thread_range_ft(engine: Any, actor: Any) -> int:
    """"Thread range", for any Thread talent that names the range without repeating a number. 20 feet, or 30 while
    one of the user's Qi Threads is active."""
    from .thread_weaving import QI_THREAD

    return QI_FT if any(c.condition_id == QI_THREAD for c in actor.conditions.values()) else MUNDANE_FT


def mark_condition_id(owner_id: str, mark: str) -> str:
    """The condition id of the ``mark`` that ``owner_id`` placed (combat/typed_executor.mark_condition_id)."""
    from ..typed_executor import mark_condition_id as _mark_condition_id

    return _mark_condition_id(mark, owner_id)


def mark_held_by(holder: Any, owner_id: str, mark: str) -> str | None:
    """The condition id of ``mark`` that ``owner_id`` placed on ``holder``, when it still bears it; None otherwise.
    The one Thread mark lookup: Thread Line, Tightened Wrist, Draw the Guard, Needle Guide and Meridian Snare are
    all the same kind of mark, so every reader asks here."""
    condition_id = mark_condition_id(owner_id, mark)
    return condition_id if any(condition.condition_id == condition_id for condition in holder.conditions.values()) else None


def thread_line_held_by(engine: Any, holder: Any, user: Any) -> bool:
    """Whether ``holder`` still carries a Thread Line ``user`` placed -- the mark Draw the Line and Needle Guide put
    up. The shared "is it still connected by one of your lines" question every Thread talent that hangs on the line
    asks before it answers."""
    return mark_held_by(holder, user.entity_id, LINE) is not None


def thread_line_cells(engine: Any, user: Any) -> set[tuple[int, int, int]]:
    """The cells one of ``user``'s Thread Lines runs through, each at the height the thread is really at: the
    straight run from the user to every active creature carrying their Thread Line mark, unioned. Empty when the
    user has no line on the board.

    Draw the Line: "you create a Thread Line between yourself or an anchor you control and the target."  A step
    that leaves or enters one of these cells crosses that line (Snaring Crossing's printed moment).  Altitude is
    part of the cell, so a creature on a square above or below the thread is not on it -- the exact 3D traversal
    (``engine.grid.effect_ray_cells``) also keeps a thread that only clips a square's corner from counting it."""
    cells: set[tuple[int, int, int]] = set()
    for holder in engine.state.actors.values():
        if holder.active and holder.entity_id != user.entity_id and thread_line_held_by(engine, holder, user):
            cells.update(engine.grid.effect_ray_cells(user.position, holder.position))
    return cells


def cell_of(position: Any) -> tuple[int, int, int]:
    """The (x, y, z) cell a creature occupies -- the one spelling ``thread_line_cells`` answers in, so a caller
    compares a square against a line without deciding for itself which axes a thread occupies."""
    return position.x, position.y, position.z