"""Speed-hook provenance shared by Afflictions, Iron Fist, mounts and movement diagnostics.

An int-compatible result keeps mechanical consumers unchanged. Its transient
sources are (source ID, readable name, signed feet) tuples, never saved state.
"""


def effective_speed(engine, actor):
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

    key = ('effective_speed', id(actor), point(actor.position))
    return shared_query(engine, key, lambda: _effective_speed(engine, actor), refs=(actor,))


def _effective_speed(engine, actor):
    from .gate2_engine import Gate2Engine
    from . import ext, motion

    speed = Gate2Engine._effective_speed(engine, actor)
    if speed <= 0:
        return speed
    speed += motion.speed_bonus(engine, actor) + sum(int(value) for value in ext.run("speed", engine, actor))
    if any(modifier.target_field == "speed_halved" and not modifier.consumed
           for modifier in actor.modifiers.values()):
        speed //= 2
    return speed


class SpeedContribution(int):
    def __new__(cls, sources):
        sources = tuple(sources)
        result = super().__new__(cls, sum(delta for _, _, delta in sources))
        result.sources = sources
        return result
