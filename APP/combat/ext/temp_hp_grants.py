"""Recorded Temporary HP identity for Bark-Back and other hit-triggered guards.

Queries use the settled attack's exact roll and existing grant/damage receipts.
No extra fight state, expiry tokens, engine patching or guessed grant identity.
Shared grant_at_hit helper is used by verdant_chassis.py for Bark-Back's guard.

advance_grant() is this module's one reader of *whose* Temporary Hit Points a pool
is: Temporary Hit Points do not stack, so a smaller or equal offer is rejected and
the creature keeps the grant it already held. held_grant() answers the same
question for a whole fight's receipts and is used by wax_footing.py and
refined_golden_bell.py (ending only its activation's remaining pool), so an older
saved fight and a hit-triggered guard can never disagree about which ability put
a pool there.

A grant may also carry its source effect's printed end. ``deadline_name`` turns
the engine expiry name into the persisted exact-turn token ``effect_durations.due``
can compare later, and ``grant_expired`` asks whether that end has passed. A
grant whose pool outlived its source (an instant "gain N Temporary HP" that lasts
until depleted) records no deadline and never expires by time.
"""


def advance_grant(current, payload, source, sequence):
    """The grant identity ``current`` becomes after one recorded ``TEMP_HP_GRANTED``.

    ``current`` is ``None`` or a ``(source_definition_id, pool it put there, sequence, expires)`` record,
    and the return value is the same shape. ``expires`` is the source effect's persisted exact-turn
    deadline (``deadline_name``), or ``None`` when the grant has no printed end. Only a receipt that
    actually raised the pool (``after > before``) establishes a new identity -- the engine keeps the
    larger pool (combat/gate2_engine.py ``_grant_temp_hp`` writes ``temporary_hp = max(before,
    offered)``), so a smaller or equal offer is rejected and the creature is still holding the grant it
    had. A receipt that emptied the pool leaves no grant at all; every other receipt leaves ``current``
    exactly as it was.
    """
    payload = payload or {}
    before, after = int(payload.get("before") or 0), int(payload.get("after") or 0)
    if after > before:
        return (str(source or ""), after, int(sequence), payload.get("expires"))
    if after < before and after == 0:
        return None
    return current


def deadline_name(engine, expires_on, *, source_actor_id, holder_id):
    """The persisted exact-turn name for a grant's printed end, or ``None`` when it has no clock.

    ``expires_on`` is an engine expiry name (``effect_expiry``). Names this module's turn-clock family
    already stores are kept as written; the sealed engine's own names are converted to that family here,
    while the source and holder turn counters are still current, so a later reader compares exact turns
    instead of re-answering "whose next turn is it now". ``UNTIL_REMOVED``, Concentration and any
    unknown name have no exact clock and answer ``None`` (the grant outlives nothing by time).
    """
    from .effect_durations import END_AT, START_AT, parse, parse_round

    name = str(expires_on or "")
    if not name or name in ("UNTIL_REMOVED", "CONCENTRATION_END"):
        return None
    if parse(name) is not None or parse_round(name) is not None:
        return name
    actors = engine.state.actors
    source = actors.get(str(source_actor_id or ""))
    holder = actors.get(str(holder_id or ""))
    if name == "END_OF_CURRENT_TURN":
        actor = actors.get(str(engine.state.current_actor_id or ""))
        return None if actor is None else f"{END_AT}:{actor.entity_id}:{int(actor.turns_started)}"
    if name == "START_OF_SOURCE_NEXT_TURN" and source is not None:
        return f"{START_AT}:{source.entity_id}:{int(source.turns_started) + 1}"
    if name == "END_OF_HOLDER_NEXT_TURN" and holder is not None:
        return f"{END_AT}:{holder.entity_id}:{int(holder.turns_started) + 1}"
    if name.startswith("END_OF_SOURCE_TURN_AT:"):
        number = name.rsplit(":", 1)[-1]
        return f"{END_AT}:{source.entity_id}:{int(number)}" if source is not None and number.isdigit() else None
    if name in ("START_OF_TARGET_NEXT_TURN", "END_OF_TARGET_NEXT_TURN") and holder is not None:
        edge = START_AT if name.startswith("START") else END_AT
        return f"{edge}:{holder.entity_id}:{int(holder.turns_started) + 1}"
    return None


def grant_expired(engine, deadline):
    """Whether a grant's recorded printed end has passed at the current boundary."""
    if not deadline:
        return False
    from .effect_durations import due

    return due(engine, deadline)


def held_grant(events, entity_id):
    """(source_definition_id, pool it put there, sequence, expires) of the grant ``entity_id`` holds, or None.

    One pass over the fight's own receipts, reading identity only: whose Temporary Hit Points a creature
    is holding is decided by ``advance_grant`` and nothing else. Used by wax_footing to recover a
    Living Wax Form grant from a fight saved before that lane's own record existed.
    """
    held = None
    for event in events:
        if event.event_type != "TEMP_HP_GRANTED" or entity_id not in (event.target_ids or ()):
            continue
        held = advance_grant(held, event.payload, event.source_definition_id, event.sequence)
    return held


def grant_at_hit(ctx, target):
    """Return (source, grant sequence, remaining at hit), or None if unproven.

    Call only from a confirmed after_hit notification. Damage from this attack
    may consume the last Temporary HP before notification; earlier damage may
    not. A later accepted replacement invalidates the old grant. Rejected/equal
    offers retain the existing grant, matching the engine's max(before, offered).
    Typed Context.attack_result and native/portable AttackNotice carry roll_id.
    """
    notice = getattr(ctx, "attack_notice", None)
    roll_id = notice.roll_id if notice else (getattr(ctx, "attack_result", None) or {}).get("roll_id")
    if not roll_id:
        return None
    held = None  # (source, pool it put there, sequence), the same shape advance_grant reads and writes
    remaining = 0
    at_hit = None
    for event in ctx.engine.events:
        if target.entity_id not in event.target_ids:
            continue
        payload = event.payload or {}
        if event.event_type == "ATTACK_ROLLED" and payload.get("roll_id") == roll_id:
            at_hit = (event.sequence, held, remaining)
        elif event.event_type == "TEMP_HP_GRANTED":
            held = advance_grant(held, payload, event.source_definition_id, event.sequence)
            remaining = int((payload or {}).get("after") or 0)
        elif event.event_type == "DAMAGE_COMMITTED":
            remaining = max(0, remaining - int(payload.get("temporary_hp_absorbed") or 0))
    if at_hit is None or at_hit[1] is None or at_hit[2] <= 0 or held != at_hit[1]:
        return None
    # The caller wants the grant's sequence to file the round it answered on, and how many points were left at the hit.
    return (at_hit[1][0], at_hit[1][2], at_hit[2])
