"""Speed-hook provenance shared by Afflictions, Iron Fist, mounts and movement diagnostics.

An int-compatible result keeps mechanical consumers unchanged. Its transient
sources are (source ID, readable name, signed feet) tuples, never saved state.

A ``speed`` provider answers its own ability only. Asking for the same
creature's composed Speed from inside one would re-enter Gate4's
``_effective_speed`` (flight/climb profiles read it). ``_composing()`` (thread-local) contains
that: the nested read returns the base Speed, motion and carrying restriction
without running the Speed hooks again, so composition terminates.
"""

import threading

from . import ext

_LOCAL = threading.local()


def _composing():
    """Creatures this thread is composing Speed for (thread-local: one thread's guard never hides another's)."""
    keys = getattr(_LOCAL, 'keys', None)
    if keys is None:
        keys = _LOCAL.keys = set()
    return keys


def effective_speed(engine, actor, *, include_all_movement_bonus=True):
    """Compose Speed for Gate4 and mounted base-engine genesis.

    Keep the base immobilization/adjustments, then motion and plug-in bonuses,
    then final halving. Mounts also uses this for the creature carrying a rider,
    so genesis and later turns apply the same contributions exactly once.

    Within one read-only query frame the answer is shared for one unchanged
    projected creature and square. The AI's promotion of every reachable square
    asks this question repeatedly for the same projection, and every plug-in
    Speed hook plus zone lookup would otherwise rerun each time. Held objects
    keep their identity alive; outside a frame every call computes afresh.
    """
    from .read_queries import shared_query
    from .space import point

    # A nested read made from inside a Speed hook answers less (no hook contributions); it gets its own key.
    reentry = (id(engine), getattr(actor, 'entity_id', None)) in _composing()
    key = ('effective_speed', id(actor), point(actor.position), include_all_movement_bonus, reentry)
    return shared_query(engine, key,
                        lambda: _effective_speed(engine, actor, include_all_movement_bonus=include_all_movement_bonus),
                        refs=(actor,))


def _effective_speed(engine, actor, *, include_all_movement_bonus=True):
    from .gate2_engine import Gate2Engine
    from . import motion

    key = (id(engine), getattr(actor, 'entity_id', None))
    # Thread-local guard: a second thread composing the same creature is not a reentrant read.
    reentered = key in _composing()
    if not reentered:
        _composing().add(key)
    try:
        speed = Gate2Engine._base_speed(engine, actor)
        if speed <= 0:
            return speed
        speed += motion.speed_bonus(engine, actor)
        if not reentered:
            speed += sum(int(value) for value in ext.run("speed", engine, actor))
        if not include_all_movement_bonus:
            # Invariant: all-Speeds bonus rows reach `speed` only through motion.speed_bonus. The
            # reentered read skips the `speed` hooks, so subtracting all_bonus here is exact only while
            # motion.speed_bonus stays the sole carrier of that bonus.
            # General pure projection: remove bonuses already contributed through
            # the walking readers before applying final restrictions. Consumers
            # can isolate their contribution without mutating resources or rows.
            from .movement_speeds import all_bonus
            speed -= all_bonus(engine, actor)
        if any(modifier.target_field == "speed_halved" and not modifier.consumed
               for modifier in actor.modifiers.values()):
            speed //= 2
        from .carry import speed_limit
        return speed_limit(engine, actor, speed)
    finally:
        if not reentered:
            _composing().discard(key)


class SpeedContribution(int):
    def __new__(cls, sources):
        sources = tuple(sources)
        result = super().__new__(cls, sum(delta for _, _, delta in sources))
        result.sources = sources
        return result
