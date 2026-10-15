"""One evented free-interaction budget shared by ordinary doors and weapon grabs.

The existing once-per-turn receipt is an integer and replays through the reducer;
the existing turn-start reset removes it. No state changes until a consumer claims it.
"""
SCOPE = 'system:object_interaction'
FLAG = 'once_per_turn:' + SCOPE


def used(actor):
    """Whether this actor has spent its free object interaction this turn."""
    return actor.turn_flags.get(FLAG) == actor.turns_started


def claim(engine, actor, source):
    """Record the same persisted receipt regardless of which interaction used it."""
    if used(actor):
        raise ValueError('Your free object interaction has already been used this turn.')
    actor.turn_flags[FLAG] = int(actor.turns_started)
    engine._append_event('ONCE_PER_TURN_CLAIMED', source, actor_id=actor.entity_id,
                         payload={'scope': SCOPE, 'turns_started': int(actor.turns_started)})
