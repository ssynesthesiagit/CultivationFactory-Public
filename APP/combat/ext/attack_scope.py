"""Resolved typed attack provenance shared by Diagnosis, equipment, next-attack damage and Intercession and Hidden Strike.

The executor opens one scope per roll. Nested reactions get their own scope;
returning or unwinding restores the parent. No fight state or events are added.
Only the roll ID string is copied to an owning condition when needed.
Intercession adds its own transient owner annotation when its modifier is
consumed, then transfers that annotation to the Context's roll cache on exit.
No annotation survives the scope or enters saved state.
Owning plug-ins may keep namespaced scratch readings in the frame and copy them
to their Context in attack_roll_finished; the frame is never fight state.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from . import hook, run

_CURRENT = ContextVar("resolved_typed_attack", default=None)


def current(engine):
    """Return this engine's active attack, or None outside typed resolution."""
    frame = _CURRENT.get()
    return frame if frame is not None and frame["engine"] is engine else None


def retarget(engine, previous, target):
    """Keep the active typed roll frame bound to a same-roll cover recipient."""
    from dataclasses import replace
    frame = current(engine)
    if frame is None or frame['target_id'] != previous.entity_id:
        return
    ctx = frame['context']
    snapshots = ctx.damage_cache.get('_marks_at_hit', {})
    if previous.entity_id in snapshots:
        from ..typed_executor import bears_mark
        snapshots[target.entity_id] = {name: bears_mark(target, ctx.actor.entity_id, name)
                                       for name in snapshots[previous.entity_id]}
    frame['target_id'] = target.entity_id
    frame['context'] = replace(ctx, target=target, targets=[target])


@contextmanager
def resolving(ctx, target, effect):
    frame = {"engine": ctx.engine, "actor_id": ctx.actor.entity_id,
             "target_id": target.entity_id, "source": ctx.source,
             "effect": effect, "roll_id": "", "context": ctx}
    token = _CURRENT.set(frame)
    try:
        yield frame
    finally:
        try:
            run("attack_roll_finished", frame['context'], ctx.engine.state.actors[frame['target_id']], effect, frame["roll_id"])
        finally:
            _CURRENT.reset(token)


@hook("event")
def record_roll(engine, event_type, kwargs):
    if event_type == "ATTACK_ROLLED":
        capture_roll(engine, kwargs)


def capture_roll(engine, kwargs):
    """Bind the actual event to its scope, independent of hook import order."""
    frame = current(engine)
    if frame is None:
        return None
    payload = kwargs.get("payload") or {}
    if (kwargs.get("actor_id") == frame["actor_id"]
            and tuple(kwargs.get("target_ids") or ()) == (frame["target_id"],)
            and str(payload.get("reason") or "").rsplit(":", 1)[0] == "ATTACK:" + frame["source"]):
        frame["roll_id"] = str(payload["roll_id"])
        return frame
    return None
