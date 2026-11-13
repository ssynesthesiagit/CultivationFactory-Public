"""One glanceable Combat log entry per action (owner 2026-11-13, FEEDSUMMARY1).

``format_history_feed`` gives every display row a ``brief``: the action it belongs to and what it
adds to that action's one-line summary. The table (static/tabletop/feed-presentation.js
``foldSummary``) joins consecutive rows of one group into one entry, extending the entry already on
screen when more rows of its group arrive, so an action whose rows reach the table in two fetches
still ends as one entry. "All events" shows the rows themselves, unchanged.

A group is the engine's transaction id: every record one action wrote -- with the reactions,
redirections and riders inside it -- or one turn change wrote, shares it. The words come from the
event kind and the recorded names only (there is no per-ability wording here), and nothing is
recalculated: each clause reads its own row's payload, and a row with no shorter form keeps its
detailed line. A record the feed has no breakdown for is its own entry, with its existing line.

Brief kinds: ``head`` (who used which ability on whom), ``turn`` (a turn header), ``clause`` (one
sentence of what happened) and ``quiet`` (nothing new: the row stays in the entry's detailed lines).
The entry says what happened, never what a rule would do: a GM reminder is quiet.
"""
from __future__ import annotations

import re
from typing import Any, Callable

# Already said elsewhere: a damage roll (its commit says what landed), a new round (the turn header
# says it), the end of a turn, and once-per-turn bookkeeping.
_QUIET = frozenset({"DAMAGE_ROLLED", "ROUND_STARTED", "TURN_ENDED", "ONCE_PER_TURN_CLAIMED"})
_MODE = {"ADVANTAGE": " with Advantage", "DISADVANTAGE": " with Disadvantage"}
# The outcomes a clause names its cause for (with a plainly named condition): damage, healing, temporary HP.
_CAUSED = frozenset({"DAMAGE_COMMITTED", "HEALING_APPLIED", "TEMP_HP_GRANTED"})


def _sentence(text: str) -> str:
    text = text.strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def brief(event: dict[str, Any], event_type: str, payload: dict[str, Any], roll: dict[str, Any] | None,
          summary: str, detailed: bool, *, actor: str, targets: str, source: str, cause: Any,
          actor_names: dict[str, str], label: Callable[[Any], str],
          speakers: dict[str, dict[str, Any]], condition: str | None = None) -> dict[str, Any]:
    """This row's part of its action's summary.

    ``speakers`` maps a group to the ability use its rows are read against (its headline), so a
    clause leaves out a name the headline already says. It only lives for one call of
    format_history_feed: rows that arrive in a later fetch name everyone, which reads the same.
    ``cause`` is the id of what the record says caused this row (None when it records none), and
    ``source`` that cause's name. ``condition`` is the recorded name of the condition a CONDITION_*
    row is about, when its line is the plain applied/removed one.
    """
    sequence = event.get("sequence")
    if not detailed:
        return {"group": f"event:{sequence}", "kind": "clause", "text": summary}
    group = str(event.get("transaction_id") or f"event:{sequence}")
    actor_id = event.get("actor_id")
    target_ids = [str(target) for target in event.get("target_ids") or []]
    if event_type == "INTENT_ACCEPTED":
        speakers[group] = {"actor_id": actor_id, "target_ids": frozenset(target_ids), "ability": source, "cause": cause}
        aimed = ", ".join(actor_names[target] for target in target_ids if target != actor_id and target in actor_names)
        return {"group": group, "kind": "head", "actor": actor, "ability": source, "targets": aimed}
    if event_type == "TURN_STARTED":
        speakers.pop(group, None)
        number = payload.get("round")
        return {"group": group, "kind": "turn",
                "text": f"Round {number} · {actor}'s turn" if type(number) is int else f"{actor}'s turn"}
    if event_type in _QUIET:
        return {"group": group, "kind": "quiet"}
    speaker = speakers.get(group) or {}
    subject = "" if actor_id is not None and actor_id == speaker.get("actor_id") else f"{actor} "
    aimed = "" if frozenset(target_ids) == speaker.get("target_ids") else targets
    ability = str(speaker.get("ability") or "")
    text = _clause(event_type, payload, roll, summary, subject=subject, actor=actor, aimed=aimed, targets=targets,
                   actor_names=actor_names, label=label, ability=ability, condition=condition)
    if not text:
        return {"group": group, "kind": "quiet"}
    # What caused a damage, healing, temporary-HP or condition outcome is named first, from the record: never
    # when the record holds no cause, when the cause is the headline's own ability, or when the condition is
    # itself the cause (Dodge's Dodge).
    caused = event_type in _CAUSED or (event_type == "CONDITION_APPLIED" and condition)
    if caused and cause and cause != speaker.get("cause") and condition != source:
        text = f"{source}: {text}"
    return {"group": group, "kind": "clause", "text": _sentence(text)}


def _clause(event_type: str, payload: dict[str, Any], roll: dict[str, Any] | None, summary: str, *,
            subject: str, actor: str, aimed: str, targets: str, actor_names: dict[str, str],
            label: Callable[[Any], str], ability: str, condition: str | None) -> str:
    if event_type == "ATTACK_ROLLED":
        hit = payload.get("provisional_hit")
        verb = "hit" if hit is True else "missed" if hit is False else "attacked"
        mode = _MODE.get(str((roll or {}).get("mode") or payload.get("mode") or ""), "")
        index = payload.get("attack_sequence_index")
        which = payload.get("attack_label") or (f"attack {index}" if type(index) is int and index > 1 else "")
        text = f"{subject}{verb}{f' {aimed}' if aimed else ''}{mode}"
        return f"{which}: {text}" if which else text
    if event_type == "SAVE_ROLLED":
        success, dc = payload.get("success"), payload.get("dc")
        verb = "made" if success is True else "failed" if success is False else "rolled"
        return f"{actor} {verb} the save{f' (DC {dc})' if type(dc) is int else ''}"
    if event_type == "SAVE_AUTO_FAILED":
        return f"{actor} automatically failed the save"
    if event_type == "DAMAGE_COMMITTED":
        kind = str(payload.get("damage_type") or "").replace("_", " ").lower()
        text = f"{subject}{'dealt ' if subject else ''}{payload['hp_damage']} {f'{kind} ' if kind else ''}damage"
        text += f" to {aimed}" if aimed else ""
        notes = ["critical hit"] if payload.get("critical") is True else []
        absorbed, remaining = payload.get("temporary_hp_absorbed"), payload.get("remaining_hp")
        if type(absorbed) is int and absorbed > 0:
            notes.append(f"{absorbed} taken by temporary HP")
        if type(remaining) is int:
            notes.append(f"{remaining} HP left")
        return text + (f" ({'; '.join(notes)})" if notes else "")
    if event_type == "HEALING_APPLIED" and not payload.get("blocked_log"):
        before, after = payload.get("before"), payload.get("after")
        change = f" ({before} → {after} HP)" if type(before) is int and type(after) is int else ""
        return f"{subject}healed{f' {aimed}' if aimed else ''} for {payload.get('offered', 'an unrecorded amount')}{change}"
    if event_type == "TEMP_HP_GRANTED":
        before, after = payload.get("before"), payload.get("after")
        if type(before) is int and type(after) is int:
            # Temporary HP does not stack: an offer that left the pool as it was changed nothing.
            return f"{targets or actor} now has {after} temporary HP" if after != before else ""
    if event_type == "CONDITION_APPLIED" and condition:
        return f"{subject}applied {condition}{f' to {aimed}' if aimed else ''}"
    if event_type == "CONDITION_REMOVED" and condition:
        return f"{condition} was removed{f' from {aimed}' if aimed else ''}"
    if event_type == "MOVEMENT_COMMITTED":
        distance = payload.get("distance_ft")
        far = f" {distance} ft" if type(distance) is int and distance > 0 else ""
        if isinstance(payload.get("dragged_by"), str):
            return f"{actor} was dragged{far} by {actor_names.get(payload['dragged_by']) or 'another creature'}"
        if payload.get("forced"):
            return f"{actor} was moved{far} by force"
        return f"{subject}teleported" if payload.get("teleport") else f"{subject}moved{far}"
    if event_type == "RESOURCE_SPENT" and type(payload.get("amount")) is int:
        resource, remaining = label(payload.get("resource_id")), payload.get("remaining")
        if str(payload.get("resource_id") or "").startswith("resource:uses."):
            return f"{subject}used {resource.removesuffix(' uses')} ({remaining} uses left)"
        return f"{subject}spent {payload['amount']} {resource}{f' ({remaining} left)' if remaining is not None else ''}"
    if event_type == "INITIATIVE_ROLLED" and roll and type(roll.get("total")) is int:
        return f"{actor} rolled {roll['total']} for initiative"
    if event_type == "GM_RIDER":
        return _rider(summary, ability) if payload.get("automated") is True else ""
    return summary


def _rider(text: str, ability: str) -> str:
    """An automated rider's line (something the engine did), without a leading "<name>:" the headline
    already names. A rider the engine did not apply is a reminder of a rule, not something that
    happened: it is quiet, and the entry's detailed lines keep it."""
    named = re.match(r"([^:.]{1,80}):\s+(.+)", text, re.S)
    if named and ability and named.group(1).strip() in ability:
        text = named.group(2)
    return text
