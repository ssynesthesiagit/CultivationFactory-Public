"""One transient consequence queue per confirmed hit.

Shared by typed_executor, packet/event delivery and mixed on-hit producers.
The existing AttackDamage.roll_id is the only membership key. A ChoicePause
discards the transaction; service resume executes the original intent again,
rebuilding these queues, rather than serializing callables into fight state.
"""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import sys
from typing import Any


@dataclass
class Settlement:
    collecting: bool = True
    draining: bool = False
    consequences: deque = field(default_factory=deque)
    floors: dict = field(default_factory=dict)
    victory_scope: Any = None


@contextmanager
def scope(engine):
    previous = getattr(engine, "_hit_settlements", None)
    if previous is None:
        engine._hit_settlements = {}
    before = set(engine._hit_settlements)
    try:
        yield
    finally:
        error = sys.exc_info()
        for key in reversed(list(engine._hit_settlements)):
            if key not in before:
                entry = engine._hit_settlements.pop(key)
                entry.victory_scope.__exit__(*error)
        if previous is None:
            del engine._hit_settlements


def begin(engine, attack):
    if attack is not None and hasattr(engine, "_hit_settlements") and attack.roll_id not in engine._hit_settlements:
        entry = Settlement(victory_scope=engine.victory_deferred())
        entry.victory_scope.__enter__()
        engine._hit_settlements[attack.roll_id] = entry


_PACKET = object()


def current(engine, attack=_PACKET):
    entries = getattr(engine, "_hit_settlements", None)
    if not entries:
        return None
    if attack is _PACKET:
        attack = engine.damage_context()
    return entries.get(attack.roll_id) if attack is not None else None


def defer(engine, attack, work):
    """Queue one after-damage part; outside a collecting hit the caller runs it."""
    entry = current(engine, attack)
    if entry is None or not entry.collecting:
        return False
    entry.consequences.append(work)
    return True


def consequence(ctx, work):
    """Submit a Python tail to the same FIFO used by typed consequences.

    Shared by block_attack and mixed combat/ext producers; standalone callers
    keep their synchronous behavior.
    """
    if not defer(ctx.engine, ctx.attack_damage_context, work):
        work()


def collect_effects(ctx, effects, dispatch, resume):
    """Split a typed batch at its dispatch boundary, not inside its operations.

    Used by typed_executor for built-ins and plug-in effects alike. Damage
    producers run during collection; each uninterrupted remaining block is one
    continuation, entered with its original Context and its own scopes intact.
    Marks are collection producers because mark_applied can add hit damage;
    block_mark retains its direct-call declaration/placement contract.
    """
    entry = current(ctx.engine, ctx.attack_damage_context)
    if entry is None or not entry.collecting:
        dispatch(effects)
        return
    from . import ext

    def producer(row):
        if not isinstance(row, dict):
            return False
        if row.get("deferred"):
            return True  # registration, not this hit's consequence
        if row.get("type") == "save":
            return False  # the save owns its entire outcome branch
        return (row.get("type") in {"damage", "extra_damage", "mark"}
                or ext.effect_hit_damage(row.get("type"))
                or any(producer(child) for child in row.get("effects", [])))

    pending = []
    for row in effects:
        if producer(row):
            if pending:
                consequence(ctx, lambda rows=pending: resume(rows))
                pending = []
            dispatch([row])
        else:
            pending.append(row)
    if pending:
        consequence(ctx, lambda rows=pending: resume(rows))


def after_damage(engine, work):
    """Defer a packet notification, preserving its explicit packet frame."""
    entry = current(engine)
    if entry is None or entry.draining:
        return False
    attributes = ("_damage_packet_context", "_damage_packet_label", "_pending_damage_context",
                  "_pending_damage_scratch", "_pending_damage_answers",
                  "_typed_pending_damage_type", "_typed_damage_packet")
    frame = {key: getattr(engine, key, None) for key in attributes}

    def deliver():
        previous = {key: getattr(engine, key, None) for key in attributes}
        try:
            for key, value in frame.items():
                setattr(engine, key, value)
            work()
        finally:
            for key, value in previous.items():
                setattr(engine, key, value)
    entry.consequences.append(deliver)
    return True


def drain(engine, attack):
    entry = current(engine, attack)
    if entry is None:
        return
    entry.collecting = False
    entry.draining = True
    try:
        while entry.consequences:
            entry.consequences.popleft()()
    finally:
        entry.draining = False


def finish(engine, attack):
    if attack is not None:
        entry = getattr(engine, "_hit_settlements", {}).pop(attack.roll_id, None)
        if entry is not None:
            entry.victory_scope.__exit__(None, None, None)


def floor(engine, callback, target, amount, *args):
    """An optional lethal-hit floor is offered once, and retained for its hit.

    Per-packet defenses have already resolved. Nonlethal packets do not consume
    an offer. Declines are retained as well, without re-asking on later packets.
    Outside a hit, preserve the ordinary per-packet callback contract.
    """
    entry = current(engine)
    key = (callback, target.entity_id)
    if entry is not None and key in entry.floors:
        return entry.floors[key]
    answer = callback(engine, target, amount, *args)
    if entry is not None and amount >= target.current_hp + target.temporary_hp:
        entry.floors[key] = answer
    return answer
