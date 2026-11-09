"""Shared helper: a real descent (fall, jump down, drop in elevation), remembered for the turn.

Users: ``axe_kick_descent.py`` (Axe-Kick Descent), ``gravity.py`` (Falling Hammer). Both print the same
trigger -- "when you fall at least 10 feet, jump down, or descend from a higher space ... before the end of
the turn" -- so the reading of a committed movement, the turn stamp and the spend live here once.

``descent_ft(payload)`` is the one reading of a MOVEMENT_COMMITTED payload: the feet of vertical drop it
records (the fall the engine rolled, otherwise the difference between where the movement started and where
it ended), or ``None`` when it does not descend at all. ``dropped(payload, minimum_ft=...)`` asks about that
number, so each ability keeps its own printed threshold: Axe-Kick Descent's "jump down, or descend from a
higher space" answers for any drop (``minimum_ft=0``), while Falling Hammer's "fall or descend at least 10
feet" passes ``minimum_ft=FALL_FT``. ``stamp`` leaves the turn stamp (and clears an earlier spend) on the
mover; ``held`` is the pure query a rider asks before it runs; ``spend`` records that the descent paid for
one hit. Only integer turn flags are written, so they roll back with the transaction and survive a table
commit.
"""

from __future__ import annotations

from typing import Any

FALL_FT = 10  # the printed "fall at least 10 feet" these riders share


def turn_stamp(engine: Any) -> int:
    """The turn a descent stamp belongs to; matches falling's fall_round_number convention."""
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


def descent_ft(payload: dict[str, Any]) -> int | None:
    """The feet of vertical drop one committed movement records, or ``None`` when it does not descend."""
    fell = int(payload.get("fall_distance_ft") or 0)
    if fell > 0:
        return fell
    path = payload.get("path") or []
    start = path[0] if path else None
    if not start:
        return None
    ends = [path[-1]] if len(path) >= 2 else []
    ends.append(payload.get("destination"))
    drops = [int(start.get("z") or 0) - int((end or {}).get("z") or 0) for end in ends]
    return max(drops) * 5 if max(drops, default=0) > 0 else None


def dropped(payload: dict[str, Any], *, minimum_ft: int = 0) -> bool:
    """Whether the committed movement descends at least ``minimum_ft`` feet (any drop by default)."""
    feet = descent_ft(payload)
    return feet is not None and feet >= int(minimum_ft)


def stamp(engine: Any, mover: Any, flag: str, spent: str | None = None) -> None:
    """Leave this turn's descent stamp on ``mover``; a fresh descent clears an earlier spend."""
    mover.turn_flags[flag] = turn_stamp(engine)
    if spent:
        mover.turn_flags.pop(spent, None)


def held(engine: Any, actor: Any, flag: str, spent: str | None = None) -> bool:
    """Whether this turn holds a descent the actor has not already spent."""
    current = turn_stamp(engine)
    return actor.turn_flags.get(flag) == current and (spent is None or actor.turn_flags.get(spent) != current)


def spend(engine: Any, actor: Any, flag: str, spent: str) -> None:
    """Record that this turn's descent paid for one hit."""
    actor.turn_flags[spent] = turn_stamp(engine)
