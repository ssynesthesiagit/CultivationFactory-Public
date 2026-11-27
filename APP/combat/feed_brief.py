"""One glanceable Combat log entry per action (owner 2026-11-13, FEEDSUMMARY1).

``format_history_feed`` gives every display row a ``brief``: the action it belongs to and what it
adds to that action's compact summary. The table (static/tabletop/feed-presentation.js
``foldSummary``) joins consecutive rows of one group into one entry, extending the entry already on
screen when more rows of its group arrive, so an action whose rows reach the table in two fetches
still ends as one entry. "All events" shows the rows themselves, unchanged.

A group is the engine's transaction id: every record one action wrote -- with the reactions,
redirections and riders inside it -- or one turn change wrote, shares it. The words come from the
event kind and the recorded names only (there is no per-ability wording here), and nothing is
recalculated: only recorded outcomes add clauses. Whether a row has a detailed breakdown
does not determine its group or whether it can report an outcome.

Brief kinds: ``head`` (who used which ability on whom), ``turn`` (a turn header), ``clause`` (one
sentence of what happened) and ``quiet`` (nothing new: the row stays in the entry's detailed lines).
The entry says what happened, never what a rule would do: a GM reminder is quiet.
"""
from __future__ import annotations

from typing import Any, Callable
from .history_text import reaction_words

_MODE = {"ADVANTAGE": " with Advantage", "DISADVANTAGE": " with Disadvantage"}
# The outcomes a clause names its cause for (with a plainly named condition): damage, healing, temporary HP.
_DAMAGE = frozenset({"DAMAGE_COMMITTED", "UNAVOIDABLE_DAMAGE_COMMITTED"})
_CAUSED = _DAMAGE | {"HEALING_APPLIED", "TEMP_HP_GRANTED"}


def _sentence(text: str) -> str:
    text = text.strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def brief(event: dict[str, Any], event_type: str, payload: dict[str, Any], roll: dict[str, Any] | None,
          summary: str, *, actor: str, targets: str, source: str, cause: Any,
          actor_names: dict[str, str], label: Callable[[Any], str], speakers: dict[str, dict[str, Any]],
          condition: str | None = None, condition_line: str | None = None) -> dict[str, Any]:
    """This row's part of its action's summary.

    ``speakers`` maps a group to the ability use its rows are read against (its headline), so a
    clause leaves out a name the headline already says. It only lives for one call of
    format_history_feed: rows that arrive in a later fetch name everyone, which reads the same.
    ``cause`` is the id of what the record says caused this row (None when it records none), and
    ``source`` that cause's name. ``condition`` is the recorded name of the condition a CONDITION_*
    row is about. ``condition_line`` is used instead for records that describe a condition
    outcome as a complete sentence (for example, the item retirement receipt).
    """
    sequence = event.get("sequence")
    group = str(event.get("transaction_id") or f"event:{sequence}")
    actor_id = event.get("actor_id")
    target_ids = [str(target) for target in event.get("target_ids") or []]
    if event_type == "INTENT_ACCEPTED":
        speakers[group] = {"actor_id": actor_id, "target_ids": frozenset(target_ids), "cause": cause}
        aimed = ", ".join(actor_names[target] for target in target_ids if target != actor_id and target in actor_names)
        return {"group": group, "kind": "head", "actor": actor, "ability": source, "targets": aimed}
    if event_type == "TURN_STARTED":
        speakers.pop(group, None)
        number = payload.get("round")
        return {"group": group, "kind": "turn",
                "text": f"Round {number} · {actor}'s turn" if type(number) is int else f"{actor}'s turn"}
    speaker = speakers.get(group) or {}
    subject = "" if actor_id is not None and actor_id == speaker.get("actor_id") else f"{actor} "
    aimed = "" if frozenset(target_ids) == speaker.get("target_ids") else targets
    text = _clause(event_type, payload, roll, summary, subject=subject, actor=actor, aimed=aimed, targets=targets,
                   source=source, actor_names=actor_names, label=label, condition=condition, condition_line=condition_line)
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
            subject: str, actor: str, aimed: str, targets: str, source: str, actor_names: dict[str, str],
            label: Callable[[Any], str], condition: str | None, condition_line: str | None) -> str:
    if event_type == "ATTACK_ROLLED":
        hit = payload.get("provisional_hit")
        if type(hit) is not bool:
            return ""
        verb = "hit" if hit else "missed"
        mode = _MODE.get(str((roll or {}).get("mode") or payload.get("mode") or ""), "")
        index = payload.get("attack_sequence_index")
        which = payload.get("attack_label") or (f"attack {index}" if type(index) is int and index > 1 else "")
        text = f"{subject}{verb}{f' {aimed}' if aimed else ''}{mode}"
        return f"{which}: {text}" if which else text
    if event_type == "ATTACK_LOCATION_MISSED":
        return summary  # The receipt supplies the words for the lost target or empty square.
    if event_type == "PASSIVE_TRIGGERED":
        if payload.get("kind") == "attack_target_intercepted":
            # No attack roll was made against the original creature.
            recipient = actor_names.get(payload.get("recipient_object_id")) or "a stand-in"
            original = actor_names.get(payload.get("original_target_id")) or "the original target"
            return f"{actor} hit {recipient} instead of {original}"
        if payload.get("miss_chance_percent") and payload.get("missed") is True:
            return f"{actor} missed because {targets or 'the target'} was hard to see"
        if payload.get("hit_after_correction") is True or payload.get("attack_outcome_replaced") == "miss_to_hit":
            return f"The attack hit after {source}"
    if event_type == "ATTACK_FORCED_MISS":
        return f"{source} made the attack miss"
    if event_type == "REACTION_RESOLVED":
        if payload.get("checkpoint") == "AFTER_ATTACK_ROLL_DEFENSES":
            return "The attack missed after defenses" if payload.get("hit_after_recheck") is False else ""
        words = reaction_words(payload, actor, targets, source)
        return words.rstrip(".") + "; the attack missed" if payload.get("hit_after_recheck") is False else words
    if event_type in {"SUMMONS_COMMANDED", "SUMMON_APPEARED"}:
        return summary
    if event_type == "SAVE_ROLLED":
        success, dc = payload.get("success"), payload.get("dc")
        if type(success) is not bool:
            return ""
        verb = "made" if success else "failed"
        return f"{actor} {verb} the save{f' (DC {dc})' if type(dc) is int else ''}"
    # SAVE_AUTO_FAILED documents the cause; the following SAVE_ROLLED owns the result.
    if event_type in _DAMAGE:
        amount = payload.get("hp_damage", payload.get("amount"))
        if type(amount) is not int:
            return ""
        kind = str(payload.get("damage_type") or "").replace("_", " ").lower()
        text = f"{subject}{'dealt ' if subject else ''}{amount} {f'{kind} ' if kind else ''}damage"
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
        if type(before) is int and type(after) is int and after > before:
            return f"{targets or actor} regained {after - before} HP ({after} HP now)"
    if event_type == "TEMP_HP_GRANTED":
        before, after = payload.get("before"), payload.get("after")
        # Temporary HP does not stack: an offer that left the pool as it was changed nothing.
        if type(after) is int and after != before:
            return f"{targets or actor} now has {after} temporary HP"
    if event_type in {"CONDITION_APPLIED", "CONDITION_REMOVED"}:
        if condition_line:
            return condition_line
        if condition:
            # Some receipts use a description as their pill label. Put the recipient before
            # it, rather than appending "to/from X" after a potentially complete sentence.
            who = targets or actor
            if event_type == "CONDITION_APPLIED":
                return f"{who} gained {condition}"
            return f"{who} lost {condition}"
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
            left = f" ({remaining} uses left)" if type(remaining) is int else ""
            return f"{subject}used {resource.removesuffix(' uses')}{left}"
        return f"{subject}spent {payload['amount']} {resource}{f' ({remaining} left)' if type(remaining) is int else ''}"
    if event_type == "RESOURCE_GAINED":
        amount = payload.get("amount", payload.get("gained"))
        if type(amount) is int:
            resource, remaining = label(payload.get("resource_id")), payload.get("current", payload.get("remaining"))
            return f"{subject}gained {amount} {resource}{f' ({remaining} now)' if type(remaining) is int else ''}"
    if event_type == "CONCENTRATION_ENDED":
        return f"{actor} stopped concentrating on {source}"
    if event_type == "ENTITY_DEFEATED":
        return summary  # history_feed resolves the recorded death markers for this defeat.
    if event_type == "LIFE_STATE_CHANGED":
        if payload.get("life_state") == "DYING":
            return f"{actor} dropped and is dying"
        if payload.get("life_state") == "STABLE":
            return f"{actor} is stable at 0 HP"
    if event_type == "OBJECT_UPDATED":
        obj, damage = payload.get("object") or {}, payload.get("damage")
        if isinstance(damage, dict) and type(damage.get("taken")) is int and damage["taken"] > 0:
            # Gear with a physical inventory identity has its own retirement receipt.
            # The object-update projection doesn't announce that same break a second time.
            name = targets or "The object"
            damage_kind = damage.get("kinds")
            text = f"{name} took {damage['taken']}{f' {damage_kind}' if damage_kind else ''} damage"
            if obj.get("destroyed") and "|" not in str(obj.get("object_id") or ""):
                return text + " and was destroyed"
            left = obj.get("current_hp")
            return text + (f" ({left} HP left)" if type(left) is int else "")
    return ""

