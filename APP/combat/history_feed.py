from __future__ import annotations

from typing import Any, Iterable


def _fallback_name(stable_id: str | None) -> str:
    if not stable_id:
        return "Unknown"
    tail = stable_id.split(":")[-1]
    return tail.replace("_", " ").replace(".", " ").title()


def _name(stable_id: str | None, names: dict[str, str]) -> str:
    if not stable_id:
        return "System"
    return names.get(stable_id) or _fallback_name(stable_id)


def _actor_name(actor_id: str | None, actor_names: dict[str, str]) -> str:
    if not actor_id:
        return "System"
    return actor_names.get(actor_id) or _fallback_name(actor_id)


def _target_names(target_ids: Iterable[str], actor_names: dict[str, str]) -> str:
    return ", ".join(_actor_name(actor_id, actor_names) for actor_id in target_ids)


def _roll_text(roll: dict[str, Any]) -> str:
    expression = str(roll.get("expression") or "Recorded roll")
    dice = roll.get("dice")
    faces = f" [{', '.join(str(value) for value in dice)}]" if isinstance(dice, (list, tuple)) and dice else ""
    modifier = roll.get("modifier")
    total = roll.get("total")
    parts = [f"{expression}{faces}"]
    if isinstance(modifier, int):
        parts.append(f"modifier {'+' if modifier >= 0 else '−'}{abs(modifier)}")
    if isinstance(total, int):
        parts.append(f"total {total}")
    return " · ".join(parts)


def _position(state: dict[str, Any] | None, actor_id: str | None) -> dict[str, int] | None:
    if not state or not actor_id:
        return None
    actors = state.get("actors") or {}
    actor = actors.get(actor_id) if isinstance(actors, dict) else next(
        (row for row in actors if row.get("entity_id") == actor_id), None
    )
    return actor.get("position") if actor else None


def _pos_text(position: dict[str, Any] | None) -> str:
    if not position:
        return "unknown cell"
    return f"({position.get('x')}, {position.get('y')})"


def format_history_feed(
    events: Iterable[dict[str, Any]],
    rolls: Iterable[dict[str, Any]],
    *,
    pre_state: dict[str, Any] | None,
    post_state: dict[str, Any],
    actor_names: dict[str, str],
    definition_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Format recorded mechanics without recalculating any outcome.

    Roll linkage is by recorded ``payload.roll_id`` only. State-dependent text
    reads the reducer-produced pre/post states. Unknown or older records are
    surfaced visibly instead of being guessed.
    """
    roll_by_id = {str(row.get("roll_id")): row for row in rolls if row.get("roll_id")}
    rows: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        event_type = str(event.get("event_type") or "UNKNOWN_EVENT")
        actor_id = event.get("actor_id")
        target_ids = list(event.get("target_ids") or [])
        source_id = event.get("source_definition_id")
        actor = _actor_name(actor_id, actor_names)
        targets = _target_names(target_ids, actor_names)
        source = _name(source_id, definition_names)
        roll_id = payload.get("roll_id")
        linked_roll = roll_by_id.get(str(roll_id)) if roll_id else None
        roll = linked_roll or (payload if payload.get("expression") else None)
        detailed = True

        if event_type == "ATTACK_ROLLED" and roll:
            defense = payload.get("target_ac")
            outcome = payload.get("provisional_hit")
            outcome_text = "Hit" if outcome is True else "Miss" if outcome is False else "Outcome not recorded"
            defense_text = f" (AC {defense})" if isinstance(defense, int) else ""
            summary = f"{actor} — {source} vs {targets or 'target'}{defense_text}: {_roll_text(roll)} — {outcome_text}."
        elif event_type == "SAVE_ROLLED" and roll:
            dc = payload.get("dc")
            success = payload.get("success")
            outcome_text = "Success" if success is True else "Failure" if success is False else "Outcome not recorded"
            dc_text = f" (DC {dc})" if isinstance(dc, int) else ""
            summary = f"{actor} — save against {source}{dc_text}: {_roll_text(roll)} — {outcome_text}."
        elif event_type == "DAMAGE_ROLLED" and roll:
            summary = f"{actor} — {source} damage{f' against {targets}' if targets else ''}: {_roll_text(roll)}."
        elif event_type == "DAMAGE_COMMITTED":
            amount = payload.get("hp_damage")
            remaining = payload.get("remaining_hp")
            damage_type = str(payload.get("damage_type") or "damage").replace("_", " ").lower()
            if isinstance(amount, int):
                summary = f"{actor} — {source} dealt {amount} {damage_type} to {targets or 'the target'}"
                if isinstance(remaining, int):
                    summary += f"; {remaining} HP remained"
                summary += "."
            else:
                detailed = False
                summary = "Detailed breakdown was not recorded for this damage event."
        elif event_type == "MOVEMENT_COMMITTED":
            before = _position(pre_state, actor_id)
            after = _position(post_state, actor_id) or payload.get("destination")
            cost = payload.get("cost_ft")
            summary = f"{actor} moved from {_pos_text(before)} to {_pos_text(after)}"
            if isinstance(cost, int):
                summary += f" ({cost} ft)"
            summary += "."
        elif event_type == "RESOURCE_SPENT":
            resource = _name(payload.get("resource_id"), definition_names)
            summary = f"{actor} spent {payload.get('amount', 'an unrecorded amount')} {resource}; {payload.get('remaining', 'unknown')} remained."
        elif event_type == "RESOURCE_GAINED":
            resource = _name(payload.get("resource_id"), definition_names)
            summary = f"{actor} gained {payload.get('amount', 'an unrecorded amount')} {resource}; total {payload.get('current', payload.get('remaining', 'unknown'))}."
        elif event_type == "RESOURCE_EXPIRED":
            summary = f"{actor}'s {_name(payload.get('resource_id'), definition_names)} expired."
        elif event_type == "RESOURCE_TRIGGERED":
            summary = f"{actor} triggered {_name(payload.get('resource_id'), definition_names)} through {source}."
        elif event_type == "CONDITION_APPLIED":
            condition = _name(payload.get("condition_id"), definition_names)
            summary = f"{actor} applied {condition} to {targets or _actor_name(payload.get('target_id'), actor_names)}."
        elif event_type == "CONDITION_REMOVED":
            condition = _name(payload.get("condition_id"), definition_names)
            summary = f"{condition} was removed from {targets or actor}."
        elif event_type == "TEMP_HP_GRANTED":
            amount = payload.get("amount", payload.get("temporary_hp"))
            summary = f"{targets or actor} received {amount if amount is not None else 'unrecorded'} temporary HP from {source}."
        elif event_type == "REACTION_WINDOW_OPENED":
            summary = f"Reaction window opened for {actor}: {source}."
        elif event_type == "REACTION_RESOLVED":
            reduction = payload.get("reduction")
            spend = payload.get("spend")
            summary = f"{actor} resolved {source}"
            if isinstance(reduction, int):
                summary += f", reducing the pending amount by {reduction}"
            if isinstance(spend, int) and spend:
                summary += f" for a spend of {spend}"
            summary += "."
        elif event_type == "REACTION_DECLINED":
            summary = f"{actor} declined {source}."
        elif event_type == "TURN_STARTED":
            summary = f"Turn started: {actor} (round {payload.get('round', post_state.get('round_number', '?'))})."
        elif event_type == "TURN_ENDED":
            summary = f"Turn ended: {actor}."
        elif event_type == "ROUND_STARTED":
            summary = f"Round {payload.get('round', post_state.get('round_number', '?'))} started."
        elif event_type == "ZONE_CREATED":
            summary = f"{actor} created the {source} zone."
        elif event_type == "ZONE_REMOVED":
            summary = f"The {source} zone ended."
        elif event_type == "ENTITY_DEFEATED":
            summary = f"{targets or actor} became inactive through {source}."
        elif event_type == "MATCH_CREATED":
            summary = "Match created from the immutable genesis state."
        elif event_type == "MATCH_ENDED":
            summary = f"Match ended: {payload.get('reason', 'recorded terminal result')}."
        elif event_type == "HOLD_POSITION_COMMITTED":
            summary = f"{actor} held position."
        elif event_type == "INTENT_ACCEPTED":
            summary = f"{actor}'s {source} decision was accepted."
        elif event_type == "INITIATIVE_ROLLED" and roll:
            summary = f"{actor} rolled initiative: {_roll_text(roll)}."
        elif event_type == "CONCENTRATION_STARTED":
            summary = f"{actor} began concentrating on {source}."
        elif event_type == "CONCENTRATION_ENDED":
            summary = f"{actor} stopped concentrating on {source}."
        elif event_type == "OPTIONAL_ACTION_DECLINED":
            summary = f"{actor} declined the optional {source} action."
        elif event_type == "MODIFIER_APPLIED":
            summary = f"{source} applied a recorded modifier to {targets or actor}."
        elif event_type == "MODIFIER_REMOVED":
            summary = f"A modifier from {source} ended for {targets or actor}."
        elif event_type == "COMPANION_DEFAULT_APPLIED":
            summary = f"{actor} used the recorded companion default: {source}."
        else:
            detailed = False
            summary = "Detailed breakdown was not recorded for this event."

        rows.append({
            "event_sequence": event.get("sequence"),
            "event_type": event_type,
            "actor_id": actor_id,
            "target_ids": target_ids,
            "identity_scope": "SYSTEM" if not actor_id and not target_ids else "ACTOR_TARGET",
            "source_definition_id": source_id,
            "roll_id": roll_id,
            "summary": summary,
            "detailed_breakdown_recorded": detailed,
            "raw": event,
        })
    return rows
