"""Name the action a Reaction is answering, for the question the table is asked.

A triggered question has to say three things: which ability is asking, which action set it off, and
which creature is affected.  The first and third come from the row and the context; the second is the
part a printed phrase can only guess at ("the melee attack that missed you").  This module is the
shared reader for it.

``creature(ctx)`` is the creature the question is about: the explicit ``triggering_source_id`` the
reaction machinery records when it has one (the protective rows, where ``ctx.target`` is the ally
being shielded), otherwise ``ctx.target``, which is the creature the reaction was answered against.

``action_name(ctx, default="")`` is that creature's action in flight: the candidate the table
accepted for it this transaction (``engine._active_action_source_id``, the same accepted action
``combat/ext/ability_lockout.triggering`` and ``combat/ext/reaction_targets.choose_target`` read),
falling back to an attack that creature rolled *inside the resolution being answered right now*
(read from the engine's open transaction, see :func:`_in_flight_attack`).  Both are owner-checked
against that creature, so an ability's own turn (whose ``ctx.target`` is the creature it acted on,
not the one acting) is left alone, and the fallback is scoped to one resolution, so an earlier
attack of the same creature can never be named as the current one.  ``default`` -- normally the
row's own printed phrase -- is returned when no action of that creature is in flight, which is every
question asked outside a resolution.

A row without a ``trigger`` is not inert here: both callers read the action that is really in
flight whatever the row says, because a question that misnames its own trigger is worse than one
that repeats a printed phrase.  ``trigger`` only decides whether the row's own words are kept
beside it.

``described(ctx, phrase, label=, with_creature=)`` composes the one phrase a question should use:
the row's own printed ``trigger``, the ability whose reaction answered, and the action that creature
actually used, most specific last and each dropped when it repeats an earlier part.

Used by ``combat/ext/teleport_steps.reaction_teleport`` (Blink Guard and every other hop a
Reaction grants) and ``combat/ext/rider_step.step`` (the optional steps a Reaction grants).  Pure
reads of the engine's own counters and catalog: no state, no events, no dice, no choices, so a
question asked outside any action is unchanged.
"""

from __future__ import annotations

from typing import Any


def creature(ctx: Any) -> Any | None:
    """The creature this Reaction is about, or None when the question names nobody else."""
    typed = getattr(ctx, "typed", None) or {}
    source = typed.get("triggering_source_id")
    actors = getattr(getattr(ctx, "engine", None), "state", None)
    found = getattr(actors, "actors", {}).get(source) if source else None
    if found is None:
        target = getattr(ctx, "target", None)
        found = target if target is not None and target is not getattr(ctx, "actor", None) else None
    return found


def _in_flight_attack(engine: Any, who: Any) -> str:
    """The attack ``who`` has rolled *in the resolution being answered right now*, if any.

    Scoped to the engine's open transaction (``engine._transaction_id``, which the engine sets for the
    length of a resolution and clears afterwards).  An attack from an earlier turn, an earlier action
    of the same creature, or a fight the table loaded from a save belongs to a different transaction
    and is never offered, so a question can only ever name the action that is actually set off this
    moment.  Empty when nothing is resolving, or when the creature in question has not attacked in
    this resolution -- an ability's own turn then keeps its own printed words.
    """
    transaction = str(getattr(engine, "_transaction_id", "") or "")
    if not transaction:
        return ""
    for event in reversed(engine.events):
        if (event.event_type == "ATTACK_ROLLED" and event.actor_id == who.entity_id
                and str(getattr(event, "transaction_id", "") or "") == transaction):
            return event.source_definition_id
    return ""


def action_name(ctx: Any, default: str = "") -> str:
    """The name of the action ``creature(ctx)`` is using right now, in the words the table pressed."""
    engine = getattr(ctx, "engine", None)
    who = creature(ctx)
    if engine is None or who is None:
        return default  # no other creature is named, so nothing is answering an action
    catalog = getattr(engine, "action_catalog", {}) or {}
    pending = str(getattr(engine, "_active_action_source_id", "") or "")
    candidates = [pending] if pending else []
    candidates.append(_in_flight_attack(engine, who))
    for source_id in candidates:
        if not source_id:
            continue
        action = catalog.get(source_id)
        if action is None or getattr(action, "owner_id", None) != who.entity_id:
            continue
        name = str(getattr(action, "display_name", "") or "").strip()
        if name:
            return name
    return default


def described(ctx: Any, phrase: str = "", *, label: str = "", with_creature: bool = False) -> str:
    """One phrase for what set this question off, most specific last.

    Three sources, each dropped when it repeats one already there: the row's own printed ``trigger``, the
    ability whose reaction answered (``ctx.action``, skipped when the question already shows it as its own
    label), and the action that creature actually used, read by :func:`action_name`.  So a row that names its
    printed reaction reads "Turn the Blade Aside (Fu (Short Axe))", one that does not reads "Sever the
    Standard", and ``with_creature`` prefixes the action with its user's name for a question that names no
    other creature ("Mo Ruo's Sever the Standard").  Empty when nothing is in flight, and the caller keeps its
    own words.
    """
    action = action_name(ctx)
    named = f"{creature(ctx).display_name}'s {action}" if action and with_creature and creature(ctx) is not None else action
    answer = str(getattr(getattr(ctx, "action", None), "display_name", "") or "").strip()
    parts: list[str] = []
    for part in (str(phrase or "").strip(), answer if answer not in str(label or "") else "", named):
        if part and not any(part in kept for kept in parts):
            parts.append(part)
    if len(parts) < 2:
        return parts[0] if parts else ""
    return f"{parts[0]} ({', '.join(parts[1:])})"