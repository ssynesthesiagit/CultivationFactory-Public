"""Hold Position's evented once-per-turn receipt, shared by every seat.

The ordinary per-turn reset and reducer own this integer receipt. Hold remains
available on each new turn; accepting it never spends an Action or ends a turn.
"""
SOURCE = 'system:combat.hold_position'
FLAG = 'once_per_turn:' + SOURCE


def used(actor):
    return actor.turn_flags.get(FLAG) == actor.turns_started


def claim(engine, actor):
    if used(actor):
        raise ValueError('Hold Position has already been used this turn.')
    actor.turn_flags[FLAG] = int(actor.turns_started)
    engine._append_event('ONCE_PER_TURN_CLAIMED', SOURCE, actor_id=actor.entity_id,
        payload={'scope': SOURCE, 'turns_started': int(actor.turns_started)})
