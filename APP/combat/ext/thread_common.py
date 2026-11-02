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
yourself or an anchor you control and the target."  The canonical source-owned marker identifies each connection. Its actual
source end and connected creature or object supply the same 3D cells to Listen,
physical mundane line objects and Snaring Crossing; no second line geometry is stored.

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
    for _, target, _, line in maintained_lines(engine, user):
        anchor = line_origin(engine, user, line)
        if anchor is not None:
            cells.update(engine.grid.effect_ray_cells(anchor.position, target.position))
    return cells


def cell_of(position: Any) -> tuple[int, int, int]:
    """The (x, y, z) cell a creature occupies -- the one spelling ``thread_line_cells`` answers in, so a caller
    compares a square against a line without deciding for itself which axes a thread occupies."""
    return position.x, position.y, position.z

def maintained_lines(engine, owner):
    """Public native line identities for Listen and later physical-line consumers.

    Creature lines use the one canonical Thread mark. Object producers may attach
    that same mark to its maintainer with an explicit connected_object_id. A
    destroyed object, foreign source or removed mark is never live.
    No name, team or attack damage implies a connection.
    """
    cid = mark_condition_id(owner.entity_id, 'Thread Line')
    rows = []
    for holder in engine.state.actors.values():
        for c in holder.conditions.values():
            if c.condition_id != cid or c.source_actor_id != owner.entity_id:
                continue
            oid = (c.data or {}).get('connected_object_id')
            target = engine.state.objects.get(oid) if oid else holder
            if target is None or (oid and target.destroyed):
                continue
            line_object_id = (c.data or {}).get('line_object_id')
            line_object = engine.state.objects.get(line_object_id)
            if line_object_id and (line_object is None or line_object.destroyed):
                continue
            rows.append((c.instance_id, target, holder, c))
    return rows



def line_origin(engine, owner, line):
    """Actual source end; unknown/revoked explicit anchors do not become owners."""
    aid = line.data.get('thread_anchor', owner.entity_id)
    anchor = engine.state.actors.get(aid) or engine.state.objects.get(aid)
    return None if anchor is None or getattr(anchor, 'destroyed', False) else anchor


def materialize_mundane_line(ctx, holder, line):
    """Native physical representation, shared by creature and object hit paths.

    General Thread Rules: visible mundane combat thread has the creator's
    Cultivation Save DC as AC and PB + key modifier HP (minimum one). Qi has
    different severing permissions and is not assigned invented mundane HP.
    The public marker is at the source end; no hidden target space is published.
    Flammability needs an explicit native stock fact; wire is not assumed to burn.
    """
    if line.data.get('thread_medium') != 'mundane' or line.data.get('line_object_id'):
        return
    from ..gate2_runtime_models import RuntimeObjectState
    anchor = line_origin(ctx.engine, ctx.actor, line)
    if anchor is None:
        return
    oid = 'object:thread_line:' + line.instance_id
    hp = max(1, int(ctx.numbers['pb']) + int(ctx.numbers['key_mod']))
    obj = RuntimeObjectState(object_id=oid, object_kind='THREAD_LINE', position=anchor.position,
        owner_id=ctx.actor.entity_id, unattended=False,
        flammable=line.data.get('thread_flammable') is True, ac=int(ctx.numbers['save_dc']),
        current_hp=hp, maximum_hp=hp, destroyed=False,
        component={'name': 'Thread Line', 'thread_line': 1, 'blocks': False,
            'line_id': line.instance_id, 'line_holder': holder.entity_id,
            'line_owner': ctx.actor.entity_id, 'created_by': ctx.source})
    ctx.engine._update_object(obj, ctx.source, ctx.actor.entity_id)
    ctx.engine._update_condition_data(holder, line, {**line.data, 'line_object_id': oid}, ctx.source)


def line_for_object(engine, obj):
    """Exact physical object → canonical owned mark; never a name-based match."""
    data = obj.component or {}
    if data.get('thread_line') != 1:
        return None
    holder = engine.state.actors.get(data.get('line_holder'))
    owner = engine.state.actors.get(data.get('line_owner'))
    line = holder.conditions.get(data.get('line_id')) if holder is not None else None
    if (line is None or owner is None or line.source_actor_id != owner.entity_id
            or line.condition_id != mark_condition_id(owner.entity_id, LINE)):
        return None
    target = engine.state.objects.get(line.data['connected_object_id']) if line.data.get('connected_object_id') else holder
    return owner, target, holder, line


def maintain_line(engine, holder, line, marker_turn, source):
    """Preserve one actual line's identity while renewing its recognized clock.

    Used by the native Tension Mastery chooser and read by Listen/geometry.
    Updating the marker stamp emits CONDITION_UPDATED, not a false line ending.
    """
    if (line.expires_on != 'END_OF_MARKER_NEXT_TURN' or holder.conditions.get(line.instance_id) is not line
            or line.condition_id != mark_condition_id(line.source_actor_id, LINE)):
        raise ValueError('Maintaining a line requires its live native marker clock.')
    engine._update_condition_data(holder, line, {**line.data, 'marker_turn': int(marker_turn)}, source)
