"""Shared duration API for typed_executor, barrage_hits, needle, needle_feint, needle_footwork, shield_faces,
docket_senses and docket_terrain.

``until_round`` preserves the docket senses/aura round clock: callers store its integer in condition data and remove the
condition at the holder's turn start. It does not replace the slot-aware expiry tokens below or manage Concentration;
docket_senses handles Concentration before consulting this helper.

Expiry names for "until the start / end of <that creature's> next turn" (hunt 2026-09-29, bug 1: effect-level durations were
ignored -- Thunder That Answers First's "cannot take Reactions until the end of its next turn" ended with the turn it was
cast in, World as Canvas's "Speed reduced by 10 feet until the start of its next turn" never ended).

The sealed engine (gate2) can name only the creature a condition or modifier is filed under: START_OF_SOURCE_NEXT_TURN and
END_OF_SOURCE_TURN_AT:N are the applier's turns, END_OF_HOLDER_NEXT_TURN ends at the holder's next turn end -- this turn's,
when the holder is the one acting. "Until the start of its next turn" on an enemy has no exact name (combat/unmaking.py
approximates it with the applier's turn), and a Reaction's user is not the one whose turn it is. So typed_executor's
effect_expiry() names those two more, and the engine, which leaves a name it does not know alone, keeps them until the hooks
below take them off:

  START_OF_TURN_AT:<actor id>:<N>   -- ends when that creature starts its Nth turn
  END_OF_TURN_AT:<actor id>:<N>     -- ends when that creature's Nth turn ends

tabik_ninpo's Vanishing Posture uses token() with the current actor's turn counter
to end on the triggering turn, including off-turn Opportunity Attacks.

N is the creature's turn counter (ActorState.turns_started) plus one when the effect was applied, so "its next turn" is
the same turn whether or not it is the one acting.

Durations counted in rounds (expiry-clock fix 2026-09-28: "for 1 minute" on anything but a Concentration technique had no
clock -- conditions fell back to the end of the holder's next turn, modifiers stayed for the fight) take one more name:

  START_OF_SLOT_AT:<round>:<slot>   -- ends when the turn slot <slot> of round <round> starts (or is already past)

The standard is shared rules data: 1 round is one full round, 1 minute is 10 rounds, 1 hour is 600 rounds and 1 day is 14400.
Explicit scene kinds last the fight. The name is the round the effect ends in, counted from the round it was applied in, and the
slot of the turn it was applied in, so it ends at the same place in the turn order that many rounds later -- on the
applier's own turn when it acted on its own, on the triggering creature's slot for a Reaction. The engine's fixed initiative
order makes the slot a stable place.

An AREA can be given the same turn-anchored clock through its trigger_profile instead of a round count, because
``ZoneState.duration_rounds`` is compared against the round number (combat/zones.py on_turn_start) and so answers "until the
start of your next turn" only when the owner has already taken its turn this round:

  end_after_owner_turn: <N>   -- ends at the END of the owner's Nth turn. A typed zone's "until_end_of_your_next_turn"
                                  (combat/zones.py place_zone); swept below on turn_end.
  start_of_owner_turn: <N>    -- ends at the START of the owner's Nth turn. next_owner_turn() below writes it, for a
                                  printed "until the start of your next turn" a plug-in lays the area down itself: the
                                  Living Wax Form's bright candlelight (combat/ext/wax_reactions.py).

Both hold one integer turn counter, so they survive a table commit and a reload, and neither a float nor an object. A zone
with neither keeps its ordinary round-count clock.

Nothing is stored beyond the name: what has come due is worked out from the counters (the turn counters, the round number and
slot the engine already keeps) at every turn boundary, so a replayed fight expires them at the same points. Hooks exist only
under the Gate 4 engine (combat/gate4_engine.py); a bare Gate2Engine keeps the names until the fight ends.

Two families of name, one question
----------------------------------
``due`` above only reads the three names this module's own sweep can bring down. The sealed engine keeps three more of its
own (gate2_engine._expire_typed_for_checkpoint) and removes those itself, with no help from here:

  START_OF_SOURCE_NEXT_TURN   -- the start of the applier's next turn
  END_OF_HOLDER_NEXT_TURN     -- the end of the affected creature's next turn
  END_OF_SOURCE_TURN_AT:<N>   -- the end of the applier's Nth turn (the applier's turns are the ones that count)

:func:`engine_due` is the single public question to ask about any expiry name a fight has already stored -- ``due`` for the
names this module sweeps, :func:`native_due` for the engine's own -- so a caller reading a name back out of a saved fight
never has to know which family it came from. It answers "would this name come down at this checkpoint", which is the only
question a turn name can answer at all: unlike a round name, a turn name cannot be ordered against the table's clock
without predicting whose turn it is and whether that creature is still acting. Callers read it at the same checkpoints the
engine sweeps at and pass the checkpoint's own name ("START_OF_TURN" / "END_OF_TURN", the strings :func:`sweep` is given),
``source_id``/``holder_id`` being the stored row's own two ids, which is how the engine identifies the creature a name is
waiting for. ``due``'s ``ending_id`` remains the ``turn_end`` hook's argument: the sweep runs while the ending creature is
still the current one, so a name waiting for that very turn end is not due until it is named. Both are strict and both are
inert: a name neither family knows is never due, and nothing here stores, orders or removes anything.
"""

from __future__ import annotations

from typing import Any

from . import hook, run

START_AT = "START_OF_TURN_AT"
END_AT = "END_OF_TURN_AT"
SLOT_AT = "START_OF_SLOT_AT"
# The three names gate2_engine._expire_typed_for_checkpoint removes itself, named here so a caller reading one back out
# of a save does not have to spell them. The third is a prefix: its number is its own turn.
NATIVE_SOURCE_START = "START_OF_SOURCE_NEXT_TURN"
NATIVE_HOLDER_END = "END_OF_HOLDER_NEXT_TURN"
NATIVE_SOURCE_TURN = "END_OF_SOURCE_TURN_AT"
_EXPIRATION = "system:combat.expiration"  # gate2_engine.SYSTEM_EXPIRATION, the source its own expiries are filed under
_SKIPPED = "expiry_round_skipped:"


def custom_turn_due(actor: Any, deadline: int, storage: dict, key: str, *, nominal: bool = False) -> bool:
    """Custom expiry clocks used by zone, suppression and temporary-flag plug-ins.

    Call once at the deadline's boundary, with nominal=True only from the
    nominal_slot_boundary hook. Each live record has its own key and integer
    skipped-slot offset in persisted runtime storage; real turns never change
    that offset. The key includes the deadline and is retired when due. Actor
    flag keys contain _round_ so revival cannot reset a pending deadline.
    """
    clock = f"custom_expiry_round_skipped:{key}:{int(deadline)}"
    skipped = int(storage.get(clock, 0)) + int(nominal)
    if int(actor.turns_started) + skipped >= int(deadline):
        storage.pop(clock, None)
        return True
    if nominal:
        storage[clock] = skipped
    return False


def stored_token_due(engine: Any, name: Any, storage: dict, key: str, *,
                     actor: Any = None, checkpoint: str | None = None, ending_id: str | None = None) -> bool:
    """Read a custom stored token (placed zones/summon records), including omissions.

    Nominal subscribers pass actor/checkpoint; ordinary readers omit both.
    Storage is the record's persisted runtime dictionary, never a global clock.
    """
    parsed = parse(name)
    clock = f"custom_token_round_skipped:{key}:{name}"
    if parsed and actor is not None and parsed[1] == actor.entity_id and checkpoint == (
            "START_OF_TURN" if parsed[0] == "start" else "END_OF_TURN"):
        storage[clock] = int(storage.get(clock, 0)) + 1
    ended = actor.entity_id if checkpoint == "END_OF_TURN" else ending_id
    result = due(engine, name, ended, skipped=int(storage.get(clock, 0)))
    if result:
        storage.pop(clock, None)
    return result


def expiry_key(row: Any) -> str:
    """Stable deadline identity; fresh lifetimes never inherit old skipped slots."""
    return _SKIPPED + str(getattr(row, "instance_id", None) or row.modifier_id)


def skipped_expiry_slots(holder: Any, row: Any) -> int:
    """Shared Gate2/native and extension expiry clock, separate from creature turns.

    Only counted deadlines gain an integer offset per omitted anchor slot. The
    runtime-control snapshot already persists holder.turn_flags; _round_ retains
    this offset through revival/turn resets. No effect token or schema changes.
    """
    return int(holder.turn_flags.get(expiry_key(row), 0))


def transfer_expiry_clock(holder: Any, previous: Any, recipient: Any, replacement: Any, *,
                          skipped_slots: int | None = None) -> None:
    """Continue one lifetime across replacement/movement (or copy if original remains).

    Used by condition bookkeeping, Verdant extension, Radiance spreading and
    effect_transfer. Call after installing the replacement, before another slot.
    New/renewed effects must not call this. Only existing integer offsets move;
    unstamped legacy fights gain no flags. Removal retires the old identity.
    A caller that already ended the old row must supply its previously captured
    skipped_slots; a genuine ending clears that row's persisted clock.
    """
    skipped = skipped_expiry_slots(holder, previous) if skipped_slots is None else int(skipped_slots)
    if skipped:
        recipient.turn_flags[expiry_key(replacement)] = skipped
    if (getattr(previous, "instance_id", None) or previous.modifier_id) not in (
            holder.conditions if hasattr(previous, "instance_id") else holder.modifiers):
        holder.turn_flags.pop(expiry_key(previous), None)


def continuing_expiry(holder: Any, previous: Any, name: str | None, source_actor_id: str, *,
                      skipped_slots: int | None = None) -> str | None:
    """Keep a consumed implicit source clock anchored when the applier changes.

    Condition replacements and Second Ruin Form's derived modifier use this.
    Unstamped lifetimes keep their original names; explicit tokens already name
    their anchor. The replacement's source attribution remains unchanged.
    """
    if previous is None:
        return name
    skipped = skipped_expiry_slots(holder, previous) if skipped_slots is None else int(skipped_slots)
    if not skipped or previous.source_actor_id == source_actor_id:
        return name
    if str(name or "").startswith(NATIVE_SOURCE_TURN + ":"):
        number = name.rsplit(":", 1)[1]
        return token("end", previous.source_actor_id, int(number)) if number.isdigit() else name
    if name in ("START_OF_MARKER_NEXT_TURN", "END_OF_MARKER_NEXT_TURN"):
        return token("start" if name.startswith("START") else "end", previous.source_actor_id,
                     int((previous.data or {}).get("marker_turn") or 0) + 1)
    return name


def apply_condition_preserving_clock(engine: Any, holder: Any, previous: Any,
                                     condition_id: str, source_id: str, source_actor_id: str,
                                     *, expires_on: str | None, data: dict | None = None,
                                     previous_holder: Any = None, skipped_slots: int | None = None) -> None:
    """Apply an explicitly lifetime-preserving replacement through normal events.

    Arguments after previous mirror _apply_condition. previous=None means a
    genuinely fresh/renewed lifetime. previous_holder supports a copied mark.
    If removal precedes this call, capture skipped_expiry_slots before removing
    the original and pass it as skipped_slots. This preserves existing removal
    event attribution and choice order without keeping a dead row's clock.
    Otherwise snapshot the still-live clock before application callbacks run.
    Immunity or an application subscriber removing the new row transfers nothing.
    """
    applied_sequence = engine.state.event_sequence + 1
    before = set(holder.conditions)
    origin = previous_holder if previous_holder is not None else holder
    if previous is None:
        skipped = 0
    else:
        skipped = skipped_expiry_slots(origin, previous) if skipped_slots is None else int(skipped_slots)
    expires_on = continuing_expiry(origin, previous, expires_on, source_actor_id, skipped_slots=skipped)
    engine._apply_condition(holder, condition_id, source_id, source_actor_id, expires_on=expires_on, data=data)
    replacement = next((row for iid, row in holder.conditions.items() if iid not in before
                        and row.applied_sequence == applied_sequence and row.condition_id == condition_id
                        and row.source_definition_id == source_id and row.source_actor_id == source_actor_id), None)
    if previous is not None and replacement is not None:
        transfer_expiry_clock(origin, previous, holder, replacement, skipped_slots=skipped)


def nominal_slot(engine: Any, actor: Any) -> None:
    """Scheduler-only expiry boundaries; never deliver creature turn hooks.

    Count each existing deadline separately, so a newly applied effect on a dead
    body waits its own full duration. A revived actor resumes its actual counter
    while existing effects retain only the skipped slots they already consumed.
    """
    for holder in engine.state.actors.values():
        rows = list(holder.conditions.values()) + list(holder.modifiers.values())
        live_keys = {expiry_key(row) for row in rows}
        for key in list(holder.turn_flags):
            if key.startswith(_SKIPPED) and key not in live_keys:
                holder.turn_flags.pop(key)
        for row in rows:
            parsed = parse(row.expires_on)
            anchored = (parsed is not None and parsed[1] == actor.entity_id) or (
                (str(row.expires_on or "").startswith(NATIVE_SOURCE_TURN + ":") or
                 row.expires_on in ("START_OF_MARKER_NEXT_TURN", "END_OF_MARKER_NEXT_TURN"))
                and row.source_actor_id == actor.entity_id)
            if anchored:
                key = expiry_key(row)
                holder.turn_flags[key] = skipped_expiry_slots(holder, row) + 1
    for zone in engine.state.zones.values():
        if zone.active and zone.owner_id == actor.entity_id and any(
                key in zone.trigger_profile for key in ("start_of_owner_turn", "end_after_owner_turn")):
            zone.per_turn_triggered[_SKIPPED] = int(zone.per_turn_triggered.get(_SKIPPED, 0)) + 1
    for checkpoint, edge in (("START_OF_TURN", "start"), ("END_OF_TURN", "end")):
        engine._expire_for_checkpoint(checkpoint, actor.entity_id, nominal=True)
        sweep(engine, actor, checkpoint, ending_id=actor.entity_id if edge == "end" else None)
        for holder in engine.state.actors.values():
            for row in list(holder.conditions.values()):
                if row.source_actor_id != actor.entity_id or row.expires_on != (
                        "START_OF_MARKER_NEXT_TURN" if edge == "start" else "END_OF_MARKER_NEXT_TURN"):
                    continue
                if actor.turns_started + skipped_expiry_slots(holder, row) > int((row.data or {}).get("marker_turn") or 0):
                    engine._remove_condition_instance(holder, row.instance_id, "system:typed.mark_expiry",
                                                      expected=row, expiring=True)
        _end_owned_zones(engine, actor, edge)
        if edge == "start":
            from .. import zones
            zones.expire_owned_zones(engine, actor)
            zones.close_openings(engine, actor)
        run("nominal_slot_boundary", engine, actor, checkpoint)
        if engine.state.terminal_result is not None:
            return


def until_round(engine: Any, duration: dict[str, Any]) -> int | None:
    """Docket deadline: next round for turns, shared counted units, None for explicit fight-long durations.

    Preserve the existing default/minimum of one for missing or nonpositive amounts. This is a round counter query,
    not an expiry token: its consumers perform their own turn-start removal and Concentration checks.
    """
    kind, amount = str(duration.get("kind") or ""), int(duration.get("amount") or 1)
    now = engine.state.round_number
    if kind in ("until_start_of_next_turn", "until_end_of_next_turn", "turn"):
        return now + 1
    from ..typed_executor import duration_round_count

    counted = duration_round_count(kind, amount)
    return now + counted if counted is not None else None


def token(edge: str, actor_id: str, turn: int) -> str:
    """The expiry name for the start ("start") or end (anything else) of ``actor_id``'s turn number ``turn``."""
    return f"{START_AT if edge == 'start' else END_AT}:{actor_id}:{int(turn)}"


def holder_next_turn(actor: Any, edge: str = "start") -> str:
    """The expiry name for "until the start (or end) of the affected creature's next turn".

    The general answer to a printed duration that waits on the *holder's* next turn, for any plug-in putting
    the effect on a condition or modifier directly (``engine._apply_condition(..., expires_on=...)``).

    Do not spell such a duration as the engine's own ``START_OF_TARGET_NEXT_TURN`` / ``END_OF_TARGET_NEXT_TURN``:
    ``_expire_for_checkpoint`` sweeps those at the start of the *applier's* next turn or the holder's, whichever
    comes first, so a restriction put on during the holder's own turn -- a zone that fires as its turn starts, a
    Reaction, an entry trigger -- ended with the applier's turn instead of waiting for the holder's next one
    (bug 3, tests/test_expiry_names.py). This names the holder's own turn counter explicitly, so an intervening
    turn of the caster's cannot take it off early, and a table commit and reload keep the same integer clock.
    """
    return token(edge, actor.entity_id, int(getattr(actor, "turns_started", 0) or 0) + 1)


def next_owner_turn(actor: Any) -> int:
    """The turn counter for "until the start of your next turn" on an area this creature just laid down.

    Written into ``ZoneState.trigger_profile['start_of_owner_turn']`` by the caller that places the area; the sweep in
    turn_started below takes it off at the start of that turn. The round-count clock a zone carries instead
    (``duration_rounds``, combat/zones.py on_turn_start) answers the same printed sentence only when the owner has already
    taken its turn this round, so an area made before the owner's own slot outlives its own turn start by one round.
    """
    return int(getattr(actor, "turns_started", 0) or 0) + 1


def parse(name: Any) -> tuple[str, str, int] | None:
    """(edge, actor id, turn number) of one of these names, or None. An actor id may hold colons: the number is the last part."""
    text = str(name or "")
    for edge, prefix in (("start", START_AT + ":"), ("end", END_AT + ":")):
        if text.startswith(prefix):
            actor_id, _, number = text[len(prefix):].rpartition(":")
            if actor_id and number.isdigit():
                return edge, actor_id, int(number)
    return None


def round_token(engine: Any, rounds: int) -> str:
    """The expiry name for ``rounds`` full rounds from now: the same slot of the turn order, that many rounds later."""
    state = engine.state
    return f"{SLOT_AT}:{int(state.round_number) + max(1, int(rounds))}:{int(state.current_slot_index)}"


def parse_round(name: Any) -> tuple[int, int] | None:
    """(round, slot) of one of the round names, or None."""
    text = str(name or "")
    if text.startswith(SLOT_AT + ":"):
        number, _, slot = text[len(SLOT_AT) + 1:].partition(":")
        if number.isdigit() and slot.isdigit():
            return int(number), int(slot)
    return None


def due(engine: Any, name: Any, ending_id: str | None = None, *, skipped: int = 0) -> bool:
    """Whether the turn the name waits for has come. ``ending_id``: the creature whose turn is ending right now (the "turn_end"
    hook fires while it is still the acting one, its turn counter unchanged)."""
    clock = parse_round(name)
    if clock is not None:
        return (int(engine.state.round_number), int(engine.state.current_slot_index)) >= clock
    row = parse(name)
    if row is None:
        return False
    edge, actor_id, turn = row
    creature = engine.state.actors.get(actor_id)
    if creature is None:
        return False
    started = int(creature.turns_started) + skipped
    if edge == "start":
        return started >= turn
    if started != turn:
        return started > turn
    return engine.state.current_actor_id != actor_id or ending_id == actor_id  # its Nth turn is over, or is over now


def native_due(engine: Any, name: Any, checkpoint: str, *, source_id: str | None = None,
               holder_id: str | None = None) -> bool:
    """Whether the ENGINE's own expiry sweep brings ``name`` down at ``checkpoint``, mirroring
    ``gate2_engine._expire_typed_for_checkpoint`` clause for clause.

    The engine files each of the three names under the creature it is waiting for -- the applier for
    ``START_OF_SOURCE_NEXT_TURN`` and ``END_OF_SOURCE_TURN_AT:<n>``, the affected creature for ``END_OF_HOLDER_NEXT_TURN``
    -- and only removes it on a boundary where that creature is the one whose turn is starting or ending, which is what
    ``engine.state.current_actor_id`` already names at both of the engine's checkpoints. So the caller passes the stored
    row's own ``source_id``/``holder_id`` and gets the engine's own answer back.

    ``checkpoint`` is the boundary's name ("START_OF_TURN" / "END_OF_TURN"), not the hook's: a ``START_OF_SOURCE_NEXT_TURN``
    name is due at a turn start and never at a turn end, which is the whole of what distinguishes one from the other. Any
    other value, and any name outside the three, is not due -- inert by default, like every other query here.
    """
    text = str(name or "")
    current = engine.state.current_actor_id
    if not text or current is None:
        return False
    if checkpoint == "START_OF_TURN":
        # The start of the applier's next turn, and nothing else (the engine's own second clause).
        return text == NATIVE_SOURCE_START and source_id is not None and source_id == current
    if checkpoint != "END_OF_TURN":
        return False
    if text == NATIVE_HOLDER_END:
        # The end of the affected creature's next turn, on that creature's own boundary.
        return holder_id is not None and holder_id == current
    if text.startswith(NATIVE_SOURCE_TURN + ":"):
        # The end of the applier's Nth turn: the applier's own turn counter, counted the engine's way.
        number = text[len(NATIVE_SOURCE_TURN) + 1:]
        creature = engine.state.actors.get(str(source_id or ""))
        if not number.isdigit() or creature is None or source_id != current:
            return False
        return int(creature.turns_started) >= int(number)
    return False


def engine_due(engine: Any, name: Any, checkpoint: str, *, source_id: str | None = None,
               holder_id: str | None = None, ending_id: str | None = None) -> bool:
    """Whether ANY of the engine's expiry families brings ``name`` down at this boundary -- the one question to ask
    about an expiry name a fight has already stored.

    :func:`due` for the three names this module's own sweep removes, :func:`native_due` for the three the sealed engine
    removes for itself. A caller reading a saved row's expiry back out does not know which family that save was written
    in -- a Forge Mark row carried across a save, for one -- so it asks this and gets the same answer the engine would
    have given, whichever family the name belongs to.

    ``ending_id`` is passed straight through to :func:`due` (the ``turn_end`` hook's creature, which a name waiting for
    that very turn end needs); ``source_id``/``holder_id`` go to :func:`native_due`. A name neither family knows is never
    due, so a row parked on ``UNTIL_REMOVED`` keeps standing and no caller has to special-case it.
    """
    # A stored row may have consumed nominal slots without real turns. The
    # read-back query means any matching stored deadline is due; sweep itself
    # always supplies the exact row's offset to avoid sharing a clock.
    offsets = [skipped_expiry_slots(holder, row) for holder in engine.state.actors.values()
               if holder_id is None or holder.entity_id == holder_id
               for row in (*holder.conditions.values(), *holder.modifiers.values())
               if row.expires_on == name and (source_id is None or row.source_actor_id == source_id)]
    skipped = max(offsets, default=0)
    if due(engine, name, ending_id, skipped=skipped):
        return True
    if checkpoint == "END_OF_TURN" and str(name or "").startswith(NATIVE_SOURCE_TURN + ":"):
        creature = engine.state.actors.get(source_id)
        number = str(name).rsplit(":", 1)[-1]
        if creature is not None and source_id == engine.state.current_actor_id and number.isdigit():
            return creature.turns_started + skipped >= int(number)
    return native_due(engine, name, checkpoint, source_id=source_id, holder_id=holder_id)


def sweep(engine: Any, actor: Any, checkpoint: str, ending_id: str | None = None) -> None:
    """Take off every condition and modifier whose name has come due, as the engine's own expiry does (same events)."""
    for holder in list(engine.state.actors.values()):
        for iid, condition in list(holder.conditions.items()):
            if due(engine, condition.expires_on, ending_id, skipped=skipped_expiry_slots(holder, condition)):
                engine._remove_condition_instance(holder, iid, _EXPIRATION, actor_id=actor.entity_id,
                    payload={"instance_id": iid, "condition_id": condition.condition_id, "checkpoint": checkpoint},
                    expected=condition, expiring=True)
        for mid, modifier in list(holder.modifiers.items()):
            if due(engine, modifier.expires_on, ending_id, skipped=skipped_expiry_slots(holder, modifier)):
                engine._remove_modifier_instance(holder, mid, _EXPIRATION, actor_id=actor.entity_id,
                    payload={"modifier_id": mid, "checkpoint": checkpoint}, expected=modifier, expiring=True)


@hook("turn_start")
def turn_started(engine: Any, actor: Any) -> None:
    sweep(engine, actor, "START_OF_TURN")
    _end_owned_zones(engine, actor, "start")


@hook("turn_end")
def turn_ended(engine: Any, actor: Any) -> None:
    sweep(engine, actor, "END_OF_TURN", ending_id=actor.entity_id)
    _end_owned_zones(engine, actor, "end")


def _end_owned_zones(engine: Any, actor: Any, edge: str) -> None:
    """The turn-anchored zone clocks (see the module docstring): an area that named the start or the end of its owner's Nth
    turn ends there. The end side is the one combat/zones.py writes for a typed "until the end of your next turn"; the start
    side is what a plug-in writes for a printed "until the start of your next turn" it places itself."""
    from .. import zones

    field = "start_of_owner_turn" if edge == "start" else "end_after_owner_turn"
    for zone in zones.typed_zones(engine):
        deadline = zone.trigger_profile.get(field)
        if zone.owner_id == actor.entity_id and deadline is not None and actor.turns_started + int(zone.per_turn_triggered.get(_SKIPPED, 0)) >= int(deadline):
            zones.remove(engine, zone, "DURATION_ENDED")
