"""Pure, per-reactor exceptions to Disengage; default preserves its protection."""
from . import ext


def disengage_protects(engine, reactor, mover):
    return bool(mover.turn_flags.get('disengaged')) and not ext.any_false(
        'disengage_protection', engine, reactor, mover)
