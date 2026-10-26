"""Shared replay-stable trigger names and strike scopes for plug-ins inside one resolution.

Some behaviour cannot be decided once and forgotten: a question asked *before* a roll has to be
enforced *after* it, and a talent whose price is asked for twice in one action has to charge the
first occurrence and the second separately.  Both need an id for "this time", and it has to be the
same id every time the table runs the action -- once on the discarded probe engine that asks the
question and once on the real engine that commits the answer.

``engine.state.event_sequence`` is *not* that id.  It is appended to as the fight runs, and the two
passes can reach a checkpoint with a different count (a question answered from the transport's cache
skips the events an unanswered pass produced), which is how a recorded answer used to stop matching
its own checkpoint and a decline silently became a payment.

``resolution`` is the open resolution's own id -- ``engine._transaction_id``, the engine sets it for
the length of one accepted action and clears it afterwards, and it is derived from the state the
action starts in, so both passes of one action get the same string.  ``bucket`` hands back a map of
counters for that resolution, rebuilt from nothing when the resolution changes, so nothing a plug-in
counts can survive into the next action; ``next_occurrence`` returns 0, 1, 2 ... for how many times
a named bucket has been reached in this resolution.

Nothing here is stored in fight state or affects a rule; it names a moment.

Consumers: ``kindled_responses`` (which attack of a resolution a response family's answer belongs to)
and ``paid_option`` (which occurrence of a talent's price a checkpoint belongs to).
"""

from __future__ import annotations

from typing import Any
from contextlib import contextmanager

from . import hook

#: engine transient, never fight state: {"resolution": <transaction id>, "counts": {bucket: n}}
ATTRIBUTE = "_trigger_occurrence_counts"


def current_strike(engine: Any) -> dict | None:
    """Current typed strike, including its actual recipient and local scratch data."""
    return getattr(engine, '_trigger_strike', None)


@contextmanager
def strike_scope(engine: Any, actor: Any, target: Any):
    """Scope one attack attempt through its roll, reactions and all follow-up effects.

    Nested attacks get fresh scratch data and restore their parent even on exceptions.
    Consumers: Kindled Responses arbitration and Complete Aim recipient selection.
    No events, RNG or persistent state change; non-consumers remain inert.
    """
    parent = current_strike(engine)
    engine._trigger_strike = {'actor': actor, 'target': target, 'scratch': {}}
    try:
        yield engine._trigger_strike
    finally:
        engine._trigger_strike = parent


@hook("state_event")
def reset_on_intent(engine: Any, event: Any) -> None:
    """A retry on the same engine starts counting again even after a rollback.

    A failed transaction restores fight state, but transient attributes are not
    rolled back. INTENT_ACCEPTED marks each fresh traversal, including retries
    of the same transaction id. Engines that never count occurrences are inert.
    """
    if event.event_type == "INTENT_ACCEPTED" and hasattr(engine, ATTRIBUTE):
        setattr(engine, ATTRIBUTE, {})


def resolution(engine: Any) -> str:
    """The id of the resolution now resolving, or "" when nothing is resolving."""
    return str(getattr(engine, "_transaction_id", "") or "")


def bucket(engine: Any) -> dict[str, int]:
    """The counters of the resolution now resolving, fresh whenever the resolution changes."""
    current = resolution(engine)
    counts = getattr(engine, ATTRIBUTE, None)
    if not isinstance(counts, dict) or counts.get("resolution") != current:
        counts = {"resolution": current, "next": {}}
        setattr(engine, ATTRIBUTE, counts)
    return counts["next"]


def next_occurrence(engine: Any, name: str) -> int:
    """How many times ``name`` has already been reached in this resolution; 0 for the first time.

    Replay-stable: the same action run twice from the same state counts the same occurrences in the
    same order, because it asks the same questions in the same places.
    """
    counts = bucket(engine)
    seen = int(counts.get(name) or 0)
    counts[name] = seen + 1
    return seen
