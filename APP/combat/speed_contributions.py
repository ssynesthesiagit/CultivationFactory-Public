"""Walking compatibility and transient provenance for movement_speeds.

Consumers: Gate2/Gate4, carry, mounts, Afflictions, Iron Fist and movement
diagnostics. Speed hooks answer only their own contribution. The thread-local
guard lets their nested capability reads omit hooks without hiding another
thread's composition. No provenance or guard state is saved.
"""
import threading

_LOCAL = threading.local()


def _composing():
    """Creatures this thread is composing walking Speed for."""
    keys = getattr(_LOCAL, 'keys', None)
    if keys is None:
        keys = _LOCAL.keys = set()
    return keys


def effective_speed(engine, actor, *, include_all_movement_bonus=True, prior_overloaded=None):
    """Plain-integer walking API; transient provenance never enters capability data."""
    from .movement_speeds import speed
    return int(speed(engine, actor, 'walk', include_all_movement_bonus=include_all_movement_bonus,
                     prior_overloaded=prior_overloaded))


class SpeedContribution(int):
    def __new__(cls, sources):
        sources = tuple(sources)
        result = super().__new__(cls, sum(delta for _, _, delta in sources))
        result.sources = sources
        return result


class SpeedReading(int):
    """Composed Speed and transient provenance; keyed_zero marks a keyed-only stop."""
    def __new__(cls, feet, sources=(), *, keyed_zero=False):
        result = super().__new__(cls, feet)
        result.sources = tuple(sources)
        result.keyed_zero = keyed_zero
        return result
