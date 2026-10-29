from __future__ import annotations

from typing import Any, Iterable
from .history_text import duration_clause, expiry_text, history_name, modifier_text, passive_text, rider_text
from .condition_names import condition_label
from .ext.retained_updates import is_retained_update


def concealed_condition_instances(state: dict[str, Any] | None) -> set[str]:
    """Condition instance ids hidden from the viewer-facing prose feed.

    Uses the same ``presentation_hidden_conditions`` hook as the condition list
    (gate5_service.presentation), so a concealed row is absent from both.
    Display only: the rules state is not changed.
    """
    from .ext import run as run_hooks
    from .gate2_runtime_models import ActorState

    hidden: set[str] = set()
    actors = (state or {}).get("actors") or {}
    rows = actors.values() if isinstance(actors, dict) else actors
    for actor in rows:
        actor_state = {key: value for key, value in (actor or {}).items() if key in ActorState.model_fields}
        if not actor_state:
            continue
        for answer in run_hooks("presentation_hidden_conditions", None, ActorState.model_validate(actor_state)):
            hidden.update(str(instance_id) for instance_id in (answer or ()))
    return hidden



# Items and the load (owner 2026-09-27, combat/carry.py): said plainly, not as conditions.
_CARRY = (".dropped_item", ".encumbered", ".unburdened")

# Records that open a new action. A damage roll is committed by the action that declared it, so
# nothing still queued from an earlier action can belong to this one. Used only to bound the
# rider-attribution queue; these events are otherwise formatted as usual.
_ACTION_BOUNDARIES = frozenset({
    "TURN_STARTED", "ROUND_STARTED", "ACTION_DECLARED", "ATTACK_DECLARED", "INTENT_ACCEPTED",
})


def _carry_line(condition_id: Any, applied: bool, who: str, source: str) -> str:
    kind = str(condition_id).rsplit(".", 1)[-1]
    thing = str(source or "").removeprefix("Drop ").removeprefix("Pick up ") or "an item"
    if kind == "dropped_item":
        return f"{who} dropped {thing}; it lies at their feet." if applied else f"{who} picked up {thing}."
    if kind == "encumbered":
        return (f"{who} is over their carrying capacity: Speed at most 5 ft from their next turn." if applied
                else f"{who} is no longer over their carrying capacity.")
    return (f"{who} is back under their carrying capacity: their own Speed from their next turn." if applied
            else f"{who} is over their carrying capacity again.")

_STEALTH = (".hidden", ".zone_effect", ".shaping", ".augments")


def _stealth_line(payload: dict[str, Any], applied: bool, who: str) -> str | None:
    """Hiding, what an area does to those inside, and an area's chosen talents (owner 2026-09-27; combat/stealth.py,
    combat/zones.py). None when there is nothing worth a line (leaving an area)."""
    kind = str(payload.get("condition_id") or "").rsplit(".", 1)[-1]
    data = (payload.get("gate3_condition_after") or {}).get("data") or {}
    if kind == "hidden":
        if applied:
            return f"{who} is hidden (Stealth {data['stealth_total']})." if data.get("stealth_total") is not None else f"{who} is hidden."
        return {"found": f"{who} has been found.", "attacked": f"{who} attacked and is no longer hidden.",
                "seen": f"{who} stepped into view and is no longer hidden."}.get(str(payload.get("reason") or ""), f"{who} is no longer hidden.")
    if kind == "augments":
        return f"{who}'s next {data.get('family_name') or 'use'}: {data.get('label') or 'no augments'}." if applied else None
    if kind == "shaping":
        return f"{who} will shape their {data.get('zone_name') or 'area'}: {data.get('label') or 'plain'}." if applied else None
    if kind == "zone_effect" and applied and data.get("name"):
        # w4-spirit 2026-09-28: pre-existing syntax error here (an f-string nested inside an f-string reusing the
        # same quote character three levels deep, which not even Python 3.12's relaxed f-string grammar accepts)
        # broke every import of combat/gate5_service.py -> combat/history_feed.py, including char_fight.py and
        # verify.sh's AI round-robin. Fixed by building the optional ": <reading>" suffix separately.
        reading = data.get("reading")
        suffix = f": {reading}" if reading else ""
        return f"{who} is inside {data['name']}{suffix}"
    return None


def _all_strikes_intercepted(events: list[dict[str, Any]], actor_id: str | None, source_id: str | None, intent_id: str | None) -> bool:
    """True when this use's strikes were all intercepted: at least one receipt and no strike rolled against a creature."""
    def same_use(e: dict[str, Any]) -> bool:
        return e.get("actor_id") == actor_id and e.get("trigger_or_intent_id") == intent_id
    intercepted = any(same_use(e) and e.get("event_type") == "PASSIVE_TRIGGERED"
                      and (e.get("payload") or {}).get("kind") == "attack_target_intercepted"
                      and (e.get("payload") or {}).get("attack_source_id") == source_id for e in events)
    struck = any(same_use(e) and e.get("event_type") == "ATTACK_ROLLED" and e.get("source_definition_id") == source_id
                 for e in events)
    return intercepted and not struck


def _name(stable_id: str | None, names: dict[str, str]) -> str:
    return history_name(stable_id, names)


_MARK_CONDITION_PREFIX = "condition:typed.mark."

#: The recorded default behaviours a creature or fighter falls back on, in the words of the printed
#: rule (owner 2026-09-30: say what it does, who it affects and why; no code names).
_COMPANION_DEFAULTS = {
    "DODGE": "{actor} was not commanded this round, so it takes the Dodge action.",
    "DODGE_AND_HOLD": "{actor} received no command, so it holds its ground and takes the Dodge action.",
    # The engine applies this one by itself at the start of the companion's turn when the fighter it
    # guards is out of the fight (gate2_engine._cui_guard_and_rescue_default), so the line names that
    # and not a choice the player never made.
    "GUARD_AND_RESCUE": "The fighter {actor} guards is out of the fight, so it has no orders this round: "
                        "it moves toward its most wounded ally and takes the Dodge action.",
}


def _mark_name_from_condition(condition_id: str | None) -> str | None:
    """The printed mark name for a ``condition:typed.mark.<slug>.<owner>`` condition id (owner
    2026-09-26), read back from its slug (e.g. "dream_seed" -> "Dream Seed") -- good enough for the
    fight feed without threading the original display name through the condition record itself."""
    if not condition_id or not condition_id.startswith(_MARK_CONDITION_PREFIX):
        return None
    # Slugs contain underscores, never dots; everything after the first dot
    # belongs to the owner, whose Factory id itself can contain several dots.
    slug = condition_id[len(_MARK_CONDITION_PREFIX):].partition(".")[0]
    return slug.replace("_", " ").title() or None


def _actor_name(actor_id: str | None, actor_names: dict[str, str]) -> str:
    if not actor_id:
        return "System"
    return actor_names.get(actor_id) or "Unknown creature"


def _target_names(target_ids: Iterable[str], actor_names: dict[str, str]) -> str:
    return ", ".join(_actor_name(actor_id, actor_names) for actor_id in target_ids)


def _object_name(record: dict[str, Any]) -> str:
    return str((record.get("component") or {}).get("name") or str(record.get("object_kind") or "Object").replace("_", " ").title())


def _object_line(payload: dict[str, Any], actor: str, actor_id: str | None, source: str, source_id: str | None) -> str:
    """A map object (combat/ext/objects.py) placed, damaged or destroyed, in plain words. The record is the object after the
    event; "damage" (when an attack or effect dealt some) says what happened to it."""
    record = payload.get("object") or {}
    name, damage = _object_name(record), payload.get("damage")
    left, most = record.get("current_hp"), record.get("maximum_hp")
    if not isinstance(damage, dict):
        if actor_id is None:
            return f"{name} stands on the map (AC {record.get('ac')}, {most} hit points)."
        return f"{name} was changed by {source}: {left} of {most} hit points."
    notes = f" ({'; '.join(str(note) for note in damage.get('notes') or [])})" if damage.get("notes") else ""
    taken = int(damage.get("taken") or 0)
    if not taken:
        return f"{actor}'s {source} did nothing to {name}{notes}."
    kinds = str(damage.get("kinds") or "").strip()
    text = f"{actor}'s {source} dealt {taken}{f' {kinds}' if kinds else ''} damage to {name}{notes}"
    if record.get("destroyed"):
        return f"{text}; {name} is destroyed{' and its square is open' if damage.get('opened') else ''}."
    return f"{text}; {left} of {most} hit points left."


def _roll_text(roll: dict[str, Any], ability: str | None = None) -> str:
    expression = str(roll.get("expression") or "Recorded roll")
    dice = roll.get("dice")
    faces = f" [{', '.join(str(value) for value in dice)}]" if isinstance(dice, (list, tuple)) and dice else ""
    modifier = roll.get("modifier")
    total = roll.get("total")
    parts = [f"{expression}{faces}"]
    if isinstance(modifier, int):
        name = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}.get(ability or "")
        parts.append(f"modifier {'+' if modifier >= 0 else '−'}{abs(modifier)}" + (f" ({name})" if name else ""))
    if isinstance(total, int):
        parts.append(f"total {total}")
    from .roll_reasons import text
    explanation = text(roll.get('mode', 'NORMAL'), roll.get('mode_sources') or [])
    return " · ".join(parts) + (' — ' + explanation if explanation else '')


def _named_causes(names: Iterable[str]) -> str:
    """The reducers that took points off one packet, once each, in the order they resolved.

    A damage packet can be answered by more than one reaction (Bone Armor after Stamina Guard, a
    bystander's guard after the target's own), so they are all named. An unnamed reducer adds
    nothing rather than printing a blank or a code (owner 2026-09-30: no internal names).
    """
    seen = [name for name in dict.fromkeys(str(n).strip() for n in names) if name]
    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]
    return f"{', '.join(seen[:-1])} and {seen[-1]}"


def _packet_reduction(event: dict[str, Any], source: str) -> list[str]:
    """What one recorded reaction took off the damage packet it was resolving.

    Only the ``DAMAGE_APPLICATION`` checkpoint counts: the same REACTION_RESOLVED event type also
    carries attack-roll guards (``ATTACK_HIT_BEFORE_DAMAGE``) and saving-throw bonuses
    (``SAVE_RESULT_BEFORE_DECLARED``), which change no damage packet and must not be named as if
    they had. A reaction that resolved without reducing anything adds no cause.
    """
    payload = event.get("payload") or {}
    if payload.get("checkpoint") != "DAMAGE_APPLICATION" or type(payload.get("reduction")) is not int:
        return []
    if payload["reduction"] <= 0:
        return []
    return [source] if source else []


def _damage_gap(payload: dict[str, Any], reduced_by: Iterable[str] = ()) -> str:
    """Why a rolled damage number is smaller than the Hit Points it actually took.

    The commit payload already records the whole chain -- what was rolled, what survived every
    reduction, and what the target's temporary Hit Points swallowed (combat/gate2_engine.py, the
    DAMAGE_COMMITTED payload) -- but the feed showed only ``hp_damage``. A packet that lost 34
    points to a temporary Hit Point therefore read as "8d8 ... total 38" followed by "dealt 4",
    with no printed basis and no mitigation clause in the ability. Anything that explains a gap
    is shown; an ordinary packet that dealt everything it rolled reads exactly as before, and so
    does a record rolled out before these keys were stored.

    ``reduced_by`` names what actually took the points off this packet -- the reactions that
    resolved against it (see ``_packet_reduction``). A packet reduced to nothing
    used to read "dealt 0 piercing (8 rolled, reduced from 8 to 0)", which names no cause at all:
    the reader had to find the reaction line above it and assume that was the cause. Every
    recorded reducer is now named on the line it reduced, in the words its own event used.
    """
    rolled = payload.get("rolled_or_pending_damage")
    reduced_to = payload.get("reduced_to")
    absorbed = payload.get("temporary_hp_absorbed")
    if type(rolled) is not int:
        return ""
    notes = []
    if type(reduced_to) is int and 0 <= reduced_to < rolled:
        causes = _named_causes(reduced_by)
        notes.append(f"reduced from {rolled} to {reduced_to}{f' by {causes}' if causes else ''}")
    if type(absorbed) is int and absorbed > 0:
        notes.append(f"{absorbed} of it absorbed by temporary Hit Points")
    return f" ({rolled} rolled, {' and '.join(notes)})" if notes else ""


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


def _route_origin(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The square a movement record says the mover stood on first.

    ``path`` is "the whole route the mover actually stood on, as integer {x, y}
    squares" (combat/ext/__init__.py, "Movement record contract"), so its first
    square is the origin. A reader that never sees a pre-move state -- the table's
    incremental feed, combat/tabletop_service.py events() -- has no other way to
    name where a teleport came from, and used to print the literal "unknown cell"
    for every self-teleport. Nothing here is inferred: a record without a route
    simply has no origin to print. Default-inert for actors and abilities.
    """
    route = payload.get("path")
    first = route[0] if isinstance(route, list) and route else None
    return first if isinstance(first, dict) else None


# Why an area ended, said in the same plain words the rest of the feed uses. An unknown
# reason is left out rather than printed as a code (owner 2026-09-30: no internal names).
_ZONE_END_REASON = {
    "DURATION_ENDED": "its time was up",
    "REPLACED": "its creator made another one instead",
    "COLLAPSED": "it collapsed",
    "CONCENTRATION": "its creator stopped concentrating on it",
    "CONCENTRATION_ENDED": "its creator stopped concentrating on it",
    "CREATED_REPLACED": "its creator made another one instead",
    "DEFEATED": "its creator was defeated",
    "REMOVED": "it was taken away",
    "MATCH_ENDED": "the fight ended",
}


def _zone_name(zone: dict[str, Any], fallback: str) -> str:
    """An area's printed name, from the creation record the event carries."""
    return str((zone.get("trigger_profile") or {}).get("name") or zone.get("display_name") or fallback or "unnamed")


def _zone_where(zone: dict[str, Any]) -> str:
    """Where the area sits, in the same "(x, y)" the movement lines already use."""
    center = zone.get("center")
    return f" around {_pos_text(center)}" if isinstance(center, dict) and center else ""


def _zone_cover(zone: dict[str, Any]) -> str:
    cells = zone.get("affected_cells")
    count = len(cells) if isinstance(cells, (list, tuple)) else 0
    if count:
        return f" It covers {count} square{'s' if count != 1 else ''} of the ground."
    radius = zone.get("radius_cells")
    if isinstance(radius, int) and radius > 0:
        return f" It stretches {radius} square{'s' if radius != 1 else ''} from its centre."
    return ""


def _zone_life(zone: dict[str, Any]) -> str:
    """How long the area says it lasts, never promising more than its own record shows.

    ``duration_rounds`` is a ceiling and not a promise: an area can end sooner when its
    creator stops concentrating on it, when a newer one replaces it, or at a moment its
    own ability chooses. The CL 20 road seal (combat/ext/seal.py) carries no
    ``duration_rounds`` at all and is dropped at the end of its creator's next turn, so a
    record that states neither a duration nor a Concentration is not evidence of any
    lifetime -- the line then says nothing rather than "until the fight ends", which was
    a promise the record could not keep (owner 2026-10-03: a line must not say an area
    lasts longer than it does).  Concentration uses the same words the rules already
    print ("while you concentrate on it", combat/ext/karma_riders.py).
    """
    rounds = zone.get("duration_rounds")
    ceiling = f"up to {rounds} round{'s' if rounds != 1 else ''}" if isinstance(rounds, int) and rounds > 0 else ""
    if zone.get("concentration_link"):
        held = "only while its creator keeps concentrating on it"
        return f" It lasts {held}." if not ceiling else f" It lasts {ceiling}, and {held}."
    return f" It lasts {ceiling}." if ceiling else ""


def _state_zones(*states: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The areas a state snapshot knows about, read back by zone id."""
    found: dict[str, dict[str, Any]] = {}
    for state in states:
        rows = (state or {}).get("zones")
        for key, zone in (rows.items() if isinstance(rows, dict) else
                          ((row.get("zone_id"), row) for row in rows or [] if isinstance(row, dict))):
            if isinstance(zone, dict) and zone.get("zone_id"):
                found[str(zone["zone_id"])] = zone
    return found


def format_history_feed(
    events: Iterable[dict[str, Any]],
    rolls: Iterable[dict[str, Any]],
    *,
    pre_state: dict[str, Any] | None,
    post_state: dict[str, Any],
    actor_names: dict[str, str],
    definition_names: dict[str, str],
    action_profiles: dict[str, dict[str, Any]] | None = None,
    action_economies: dict[str, str] | None = None,
    concealed_condition_instance_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Format recorded mechanics without recalculating any outcome.

    Roll linkage is by recorded ``payload.roll_id`` only. State-dependent text
    reads the reducer-produced pre/post states. ``concealed_condition_instance_ids``
    filters only viewer prose; it never removes or rewrites authoritative events.
    Unknown or older records are surfaced visibly instead of being guessed.
    """
    roll_by_id = {str(row.get("roll_id")): row for row in rolls if row.get("roll_id")}
    events = list(events)
    # Pair reaction spending with its recorded payment, rather than guessing CP's pool.
    payments: dict[tuple[Any, Any], dict[str, Any]] = {}
    actor_states = (pre_state or {}).get("actors") or {}
    states = actor_states.values() if isinstance(actor_states, dict) else actor_states
    modifiers = {key: row for state in states for key, row in (state.get("modifiers") or {}).items()}
    # Which area is which: any area the caller's state still knows, then every creation
    # event in this window as it is read (see the ZONE_* branches below).
    zones: dict[str, dict[str, Any]] = _state_zones(pre_state, post_state)
    # A map object reads by its printed name ("Wooden door"), not "Map 1": its name is in the record its events carry.
    actor_names = {**{str(row["object"]["object_id"]): _object_name(row["object"]) for row in (event.get("payload") or {} for event in events)
                      if isinstance(row.get("object"), dict) and row["object"].get("object_id")}, **actor_names}
    rows: list[dict[str, Any]] = []
    previous_mode = None
    rescues: dict[Any, list[tuple[int, str]]] = {}  # save source id -> [(bonus, rescue name), ...] recorded before its SAVE_ROLLED
    # A rider's damage may be rolled under its name and committed under the parent ability's id.
    # Track every roll, including unnamed parent damage, by actor, targets and source.
    # Each commit closes that source's packet regardless of mitigation or explicit attribution.
    # Old commits have no roll id: infer a rider only for a single, amount-consistent roll.
    # Multiple rolls or transformed amounts without explicit attribution are ambiguous; keep
    # the recorded parent name instead of searching by amount for some earlier rider.
    rolled_damage: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    death_markers = {"condition:typed.death_finalized", "condition:typed.soul_lingering"}
    # What reduced the damage packet in flight, per creature, so the commit line can name it.
    # REACTION_WINDOW_OPENED opens the packet and DAMAGE_COMMITTED closes it; a reaction that
    # resolved against it lands in between. Purely read-side: nothing here changes an outcome.
    packet_reductions: dict[Any, list[str]] = {}
    dead_entities = {state.get("entity_id"): {row.get("condition_id")
                     for row in (state.get("conditions") or {}).values() if row.get("condition_id") in death_markers}
                     for state in states}
    for event in events:
        payload = event.get("payload") or {}
        from . import ext

        # Pure plug-in adapters supply display metadata for older saved records.
        # Persisted metadata wins; neither path recalculates fight outcomes.
        adapted = {}
        for metadata in ext.query("history_event_metadata", event, events):
            adapted.update(metadata)
        payload = {**adapted, **payload}
        if payload.get("history_hidden"):
            continue
        event_type = str(event.get("event_type") or "UNKNOWN_EVENT")
        condition_record = payload.get("gate3_condition_after") or payload.get("gate3_condition_before") or {}
        death_marker = payload.get("condition_id") or condition_record.get("condition_id")
        if death_marker in death_markers:
            for who in event.get("target_ids") or []:
                if event_type == "CONDITION_APPLIED":
                    dead_entities.setdefault(who, set()).add(death_marker)
                elif event_type == "CONDITION_REMOVED":
                    dead_entities.setdefault(who, set()).discard(death_marker)
        if is_retained_update(event_type, payload):
            continue  # Replay bookkeeping is not a new application by the caster.
        if event_type in _ACTION_BOUNDARIES:
            # A declared action, attack or turn is a fresh damage packet: nothing rolled under
            # the previous one can still be committed by this one.
            rolled_damage.clear()
        actor_id = event.get("actor_id")
        target_ids = list(event.get("target_ids") or [])
        source_id = event.get("source_definition_id")
        actor = _actor_name(actor_id, actor_names)
        targets = _target_names(target_ids, actor_names)
        source = payload.get("display_name") or _name(payload.get("display_source_id") or source_id, definition_names)
        roll_id = payload.get("roll_id")
        linked_roll = roll_by_id.get(str(roll_id)) if roll_id else None
        roll = linked_roll or (payload if payload.get("expression") else None)
        weapon = ((action_profiles or {}).get(source_id) or {}).get("weapon") or {}
        # The engine's primary attack damage records its critical-hit status;
        # separate effect rolls must not inherit the weapon's ability label.
        damage_ability = weapon.get("ability") if "critical" in payload and not payload.get("damage_label") else None
        detailed = True
        mode_record = None
        prior_mode, previous_mode = previous_mode, None
        if event_type in {"CHOICE_REQUIRED", "CHOICE_RESOLVED", "REACTION_WINDOW_OPENED"}:
            # A damage packet opens here, so anything remembered for this creature belonged to
            # the previous packet and must not be named on the next commit.
            if event_type == "REACTION_WINDOW_OPENED" and payload.get("checkpoint") == "DAMAGE_APPLICATION":
                for who in target_ids:
                    packet_reductions.pop(who, None)
            continue  # decision plumbing remains available in the saved/raw events
        if event_type == "REACTION_RESOLVED":
            # A reaction that took points off the packet in flight is named on the commit line.
            for who in target_ids:
                packet_reductions.setdefault(who, []).extend(_packet_reduction(event, source))

        if event_type == "REACTION_RESOLVED" and payload.get("checkpoint") == "SAVE_RESULT_BEFORE_DECLARED" and payload.get("source_save") \
                and type(payload.get("bonus")) is int:
            rescues.setdefault(payload["source_save"], []).append((payload["bonus"], source))
        if event_type == "ATTACK_RETARGETED":
            original = _actor_name(payload.get("original_target_id"), actor_names)
            attack = _name(payload.get("attack_source_id"), definition_names) if payload.get("attack_source_id") else "attack"
            summary = f"{source} redirected {actor}'s {attack} from {original} to {targets or 'an unrecorded target'}."
            if payload.get("cover_bonus") in (2, 5):
                summary += f" The new target has +{payload['cover_bonus']} AC from cover."
        elif event_type == 'TARGETS_OBSERVED':
            continue
        elif event_type == 'ATTACK_LOCATION_MISSED':
            summary = payload['text']
        elif event_type == "ATTACK_ROLLED" and roll:
            defense = payload.get("target_ac")
            outcome = payload.get("provisional_hit")
            outcome_text = "Hit" if outcome is True else "Miss" if outcome is False else "Outcome not recorded"
            defense_text = f" (AC {defense})" if isinstance(defense, int) else ""
            index = payload.get("attack_sequence_index")
            if payload.get("attack_label"):
                source += f" — {payload['attack_label']}"
            elif type(index) is int and index > 1:
                source += f" — additional attack {index}"
            summary = f"{actor} — {source} vs {targets or 'target'}{defense_text}: {_roll_text(roll)} — {outcome_text}."
        elif event_type == "SAVE_ROLLED" and roll:
            dc = payload.get("dc")
            success = payload.get("success")
            outcome_text = "Success" if success is True else "Failure" if success is False else "Outcome not recorded"
            dc_text = f" (DC {dc})" if isinstance(dc, int) else ""
            rescue = rescues.pop(source_id, None)
            if rescue and isinstance(roll.get("total"), int):
                pre_total = roll["total"] - sum(bonus for bonus, _ in rescue)
                added = ", ".join(f"+{bonus} {name}" for bonus, name in rescue)
                roll_text = f"total {pre_total}, {added} = {roll['total']}"
            else:
                roll_text = _roll_text(roll)
            summary = f"{actor} — save against {source}{dc_text}: {roll_text} — {outcome_text}."
        elif event_type == "DAMAGE_ROLLED" and roll:
            label = payload.get("damage_label")
            purpose = str(roll.get("reason") or payload.get("reason") or "").split(":", 1)[0]
            if purpose in {"HEALING", "TEMP_HP"}:
                benefit = "healing" if purpose == "HEALING" else "temporary HP"
                summary = f"{actor} — {source} {benefit}{f' for {targets}' if targets else ''}: {_roll_text(roll)}."
            elif label:
                expression = str(roll.get("expression") or "Recorded roll").removesuffix("+0")
                summary = f"{actor} — {label}: {expression} extra damage{f' against {targets}' if targets else ''}: {_roll_text(roll)}."
            else:
                # A damage effect named "... Damage" already carries the word.
                named = " damage" if not str(source).rstrip().lower().endswith("damage") else ""
                summary = f"{actor} — {source}{named}{f' against {targets}' if targets else ''}: {_roll_text(roll, damage_ability)}."
            rider_id = payload.get("display_source_id")
            key = (actor_id, tuple(target_ids), source_id)
            if purpose not in {"HEALING", "TEMP_HP"}:
                rolled_damage.setdefault(key, []).append(
                    {"name": label or (_name(rider_id, definition_names) if rider_id else None),
                     "amount": payload.get("adjusted_total", roll.get("total"))})
        elif event_type == "DAMAGE_COMMITTED":
            key = (actor_id, tuple(target_ids), source_id)
            queued = rolled_damage.pop(key, [])
            amount = payload.get("hp_damage")
            remaining = payload.get("remaining_hp")
            damage_type = str(payload.get("damage_type") or "damage").replace("_", " ").lower()
            # This commit closes the packet: the reactions that answered it are named here and
            # never reused, so a later packet cannot inherit this packet's cause.
            reduced_by = [name for who in target_ids for name in packet_reductions.pop(who, [])]
            if isinstance(amount, int):
                dealt_by = source
                rolled = queued[0] if len(queued) == 1 else None
                if rolled is not None:
                    if not payload.get("display_name") and not payload.get("display_source_id") \
                            and payload.get("rolled_or_pending_damage") == rolled.get("amount") \
                            and rolled.get("name") and rolled["name"] != source:
                        dealt_by = str(rolled["name"])
                summary = f"{actor} — {dealt_by} dealt {amount} {damage_type} to {targets or 'the target'}"
                summary += _damage_gap(payload, reduced_by)
                if isinstance(remaining, int):
                    summary += f"; {remaining} HP remained"
                summary += "."
            else:
                detailed = False
                summary = "Detailed breakdown was not recorded for this damage event."
        elif event_type == "MOVEMENT_ALLOWANCE_RESTORED":
            restored, remaining = payload.get("restored_ft"), payload.get("remaining_ft")
            if isinstance(restored, int) and isinstance(remaining, int):
                summary = (f"{actor} can move again: {restored} feet of unspent movement restored; "
                           f"{remaining} feet remain this turn.")
            else:
                summary = str(payload.get("log") or f"{actor} can move again this turn.")
        elif event_type == "MOVEMENT_COMMITTED":
            before = _position(pre_state, actor_id)
            after = _position(post_state, actor_id) or payload.get("destination")
            cost = payload.get("cost_ft")
            dragged_by = payload.get("dragged_by")
            if isinstance(dragged_by, str):
                summary = f"{actor} was dragged by {_name(dragged_by, actor_names)} to {_pos_text(after)}."
            elif payload.get("forced"):
                summary = f"{actor} was moved by force to {_pos_text(after)}."
            elif payload.get("teleport"):
                # A teleport spends no movement, so the recorded movement cost is always 0
                # (combat/typed_executor.py _teleport). Printing "(0 ft)" read as "it did not
                # move"; say plainly that it teleported and leave the distance out. The record's
                # own route names the square it left, so the sentence is never left with a
                # "from unknown cell"; an older record without one says only where it arrived.
                origin = _route_origin(payload)
                came_from = f" from {_pos_text(origin)}" if origin else ""
                summary = f"{actor} teleported{came_from} to {_pos_text(after)}."
            else:
                summary = f"{actor} moved from {_pos_text(before)} to {_pos_text(after)}"
                if isinstance(cost, int):
                    summary += f" ({cost} ft)"
                summary += "."
        elif event_type == "RESOURCE_SPENT":
            resource = _name(payload.get("resource_id"), definition_names)
            payments[(actor_id, source_id)] = payload
            if str(payload.get("resource_id") or "").startswith("resource:uses."):
                summary = f"{actor} used {resource.removesuffix(' uses')}; {payload.get('remaining', 'unknown')} uses remain in this fight."
            else:
                summary = f"{actor} spent {payload.get('amount', 'an unrecorded amount')} {resource} for {source}; {payload.get('remaining', 'unknown')} remained."
        elif event_type == "RESOURCE_GAINED":
            resource = _name(payload.get("resource_id"), definition_names)
            amount = payload.get("amount", payload.get("gained", "an unrecorded amount"))  # the engine records "gained"
            if type(amount) is int and amount <= 0:
                continue  # a gain that clamped to nothing (the pool was already full) is not a gain: saying
                           # "gained 0" told the player something happened when nothing did
            summary = f"{actor} gained {amount} {resource}; total {payload.get('current', payload.get('remaining', 'unknown'))}."
        elif event_type == "RESOURCE_EXPIRED":
            summary = f"{actor}'s {_name(payload.get('resource_id'), definition_names)} expired."
        elif event_type == "RESOURCE_TRIGGERED":
            summary = f"{actor} triggered {_name(payload.get('resource_id'), definition_names)} through {source}."
        elif event_type == "CONDITION_APPLIED":
            # Some effects conceal an applied condition until a later mechanical
            # reveal. The original receipt remains authoritative; this is only a
            # viewer-facing omission from the prose feed.
            if str(payload.get("instance_id") or "") in (concealed_condition_instance_ids or set()):
                continue
            record = payload.get("gate3_condition_after") or {}
            data = record.get("data") or {}
            if data.get("hidden"):
                continue
            duration = expiry_text(payload.get("expires_on", record.get("expires_on")), actor_names, actor, targets or actor)
            mark = _mark_name_from_condition(payload.get("condition_id"))
            if data.get("label") and data.get("points"):
                summary = f"{targets or actor}: {data['label']}."
            elif payload.get('condition_id') == 'condition:typed.size_change' and data.get('reading'):
                summary = f"{targets or actor}: {data.get('label', 'Size change')}. {data['reading']}"
            elif mark:
                summary = f"{actor} placed the {mark} mark on {targets or _actor_name(payload.get('target_id'), actor_names)}"
                if payload.get("expires_on", record.get("expires_on")) not in (None, "UNTIL_REMOVED"):
                    summary += f"; {duration}"
                summary += "."
                if data.get("label"):
                    summary += f" {data['label']}."
            elif str(payload.get("condition_id") or "").endswith(_CARRY):
                summary = _carry_line(payload.get("condition_id"), True, targets or actor, source)
            elif str(payload.get("condition_id") or "").endswith(_STEALTH):
                summary = _stealth_line(payload, True, targets or actor)
                if summary is None:
                    continue
            elif data.get("label") and not data.get("companion_of"):
                # A condition that recorded a player-facing label is *named* by that label, exactly as the
                # condition pills on the sheet already name it (owner 2026-10-04, MMX118: the log printed raw
                # condition ids because the label channel above was gated on a docket wall's "points"). The
                # branches above keep their own richer sentences; only the id fallback is left to reach here.
                # A label is a name, not a whole sentence: who applied it, what applied it and how long it
                # lasts are still said, in the same shape as the id branch below. Dropping them left players
                # unable to tell when a labelled condition ends or who put it there (MMX118f1 review #1).
                summary = (f"{actor} applied the {data['label']} condition to "
                           f"{targets or _actor_name(payload.get('target_id'), actor_names)} ({source}); {duration}.")
            else:
                condition = condition_label(payload.get("condition_id"))
                if data.get("companion_of"):
                    condition = {"condition:typed.no_temp_hp": "cannot gain temporary hit points",
                                 "condition:typed.no_invisible": "cannot become Invisible from ordinary temporary effects"}.get(payload.get("condition_id"), condition)
                    condition = f"{str(data['companion_of']).replace('_', ' ').title()}: {condition}"
                summary = f"{actor} applied {condition} to {targets or _actor_name(payload.get('target_id'), actor_names)} ({source}){duration_clause(duration)}."
        elif event_type == "FOOTPRINT_CHANGED":
            summary = str(payload["log"])
        elif event_type == "CONDITION_REMOVED":
            record = payload.get("gate3_condition_before") or payload.get("gate3_condition_after") or {}
            data = record.get("data") or {}
            if (record.get("data") or {}).get("hidden"):
                continue
            mark = _mark_name_from_condition(payload.get("condition_id"))
            if mark:
                summary = f"The {mark} was removed from {targets or actor}."
            elif str(payload.get("condition_id") or "").endswith(_CARRY):
                summary = _carry_line(payload.get("condition_id"), False, targets or actor, source)
            elif str(payload.get("condition_id") or "").endswith(_STEALTH):
                summary = _stealth_line(payload, False, targets or actor)
                if summary is None:
                    continue
            elif payload.get("reason") == "REPLACED":
                condition = data.get("label") or condition_label(payload.get("condition_id"))
                summary = f"{condition} on {targets or actor} was replaced by {source}."
            elif data.get("label"):
                # Named by the label the condition recorded, matching how it was applied and how the
                # sheet's condition pill reads (see CONDITION_APPLIED above).
                summary = f"{data['label']} was removed from {targets or actor}."
            else:
                condition = condition_label(payload.get("condition_id"))
                summary = f"{condition} was removed from {targets or actor}."
        elif event_type == "TEMP_HP_GRANTED":
            offered = payload.get("offered", payload.get("amount", payload.get("temporary_hp")))
            before, after = payload.get("before"), payload.get("after")
            summary = (f"{source} offered {targets or actor} "
                       f"{offered if offered is not None else 'an unrecorded amount of'} temporary HP")
            if isinstance(before, int) and isinstance(after, int) and after == before:
                summary += f"; it did not replace their existing {before} temporary HP (temporary HP does not stack)."
            elif isinstance(before, int) and isinstance(after, int):
                summary += f"; their pool changed from {before} to {after} temporary HP (temporary HP does not stack)."
            elif isinstance(after, int):
                summary += f"; their resulting pool is {after} temporary HP."
            else:
                summary += "; the resulting pool was not recorded."
        elif event_type == "REACTION_RESOLVED":
            reduction = payload.get("reduction")
            spend = payload.get("spend")
            # Owner 2026-09-25: generic reactions (combat/typed_reactions.py) read as "X used Y against Z".
            against = targets and targets != actor
            summary = f"{actor} used {source} against {targets}" if against else f"{actor} resolved {source}"
            if isinstance(reduction, int):
                before, after = payload.get("pending_before"), payload.get("pending_after")
                reduced = before - after if isinstance(before, int) and isinstance(after, int) else reduction
                summary += f"; Damage reduced by {reduced}"
            if isinstance(spend, int) and spend:
                payment = payments.get((actor_id, source_id), {})
                resource_id = payload.get("resource_id") or payment.get("resource_id")
                summary += f"; spent {spend} {_name(resource_id, definition_names) if resource_id else 'resource points (pool not recorded)'}"
            summary += "."
        elif event_type == "REACTION_DECLINED":
            summary = (f"{actor} could not make an opportunity attack: {payload['reason']}." if payload.get("reason")
                       else f"{actor} declined {source}.")
        elif event_type == "TURN_STARTED":
            summary = f"Turn started: {actor} (round {payload.get('round', post_state.get('round_number', '?'))})."
        elif event_type == "TURN_ENDED":
            summary = f"Turn ended: {actor}."
        elif event_type == "ROUND_STARTED":
            summary = f"Round {payload.get('round', post_state.get('round_number', '?'))} started."
        elif event_type == "OBJECT_UPDATED":
            summary = _object_line(payload, actor, actor_id, source, event.get("source_definition_id"))
        elif event_type == "ZONE_CREATED":
            zone = payload.get("zone") or {}
            if zone.get("zone_id"):
                zones[str(zone["zone_id"])] = zone  # so the matching end line can name it
            summary = (f"{actor} created the {_zone_name(zone, source)} area{_zone_where(zone)}."
                       f"{_zone_cover(zone)}{_zone_life(zone)}")
        elif event_type == "ZONE_REMOVED":
            # The removal record holds only the zone's id, so which area this was is read
            # back from its creation record (owner 2026-10-03: with two areas of one kind,
            # "the Smoke Veil zone ended" says nothing about which one).
            zone = zones.get(str(payload.get("zone_id"))) or {}
            owner = _actor_name(zone["owner_id"], actor_names) if zone.get("owner_id") else actor
            by = "" if owner == "System" else f" {owner} created"
            why = _ZONE_END_REASON.get(str(payload.get("reason") or ""))
            summary = (f"The {_zone_name(zone, source)} area{by}{_zone_where(zone)} ended"
                       f"{f' because {why}.' if why else '.'}")
        elif event_type == "SUMMON_APPEARED":
            summary = f"{targets or 'A summoned creature'} appeared, summoned by {actor} with {source}."
        elif event_type == "SUMMONS_COMMANDED":
            summary = f"{actor} commanded {targets or 'their summoned creatures'} with {source}."
        elif event_type == "ENTITY_DEFEATED":
            summary = (f"{targets or actor} died." if dead_entities.get(actor_id) else
                       f"{targets or actor} was defeated without being killed.")
        elif event_type == "SUMMON_DISMISSED" and payload.get("log"):
            summary = str(payload["log"])
        elif event_type == "MATCH_CREATED":
            summary = "Battle started."
        elif event_type == "MATCH_ENDED":
            summary = f"Match ended: {payload.get('reason', 'recorded terminal result')}."
        elif event_type == "HOLD_POSITION_COMMITTED":
            summary = f"{actor} held position."
        elif event_type == "INTENT_ACCEPTED":
            if str(source_id or "").startswith("system:"):
                continue
            # Say which turn slot the use spent, so "what spent my action?" is answerable from the log alone
            # (owner 2026-10-15). A use that spends no slot (No action, Free, Movement) keeps the plain line.
            from .action_economy import spend_clause
            spent = spend_clause((action_economies or {}).get(source_id, ""))
            summary = f"{actor} — {source} ({spent})." if spent else f"{actor} — {source}."
        elif event_type == "INITIATIVE_ROLLED" and roll:
            summary = f"{actor} rolled initiative: {_roll_text(roll)}."
        elif event_type == "CONCENTRATION_STARTED":
            summary = (f"{actor} keeps concentrating on {source}." if (payload or {}).get("reason") == "RESUMED"
                       else f"{actor} began concentrating on {source}.")
        elif event_type == "CONCENTRATION_ENDED":
            summary = f"{actor} stopped concentrating on {source}."
        elif event_type == "OPTIONAL_ACTION_DECLINED":
            summary = f"{actor} declined the optional {source} action."
        elif event_type == "MODIFIER_APPLIED":
            record = {**(payload.get("gate3_modifier_after") or {}), **payload}
            mode_record = record
            if record.get("modifier_id"):
                modifiers[record["modifier_id"]] = {**record, "source_definition_id": source_id}
            duration = expiry_text(record.get("expires_on"), actor_names, actor, targets or actor)
            summary = modifier_text(record, source, targets or actor, duration, actor_names)
            if summary is None:
                continue
        elif event_type == "MODIFIER_REMOVED":
            old = modifiers.pop(payload.get("modifier_id"), {})
            mode_record = old
            if str(old.get("target_field") or "").startswith("typed_"):
                continue
            ended_source = _name(old.get("source_definition_id"), definition_names) if old else source
            if str(source_id or "").startswith("system:") and not old:
                ended_source = "an earlier ability"
            summary = f"The effect of {ended_source} ended for {targets or actor}."
        elif event_type == "D20_REWRITTEN" and payload.get("original") and payload.get("result"):
            before, after = payload["original"], payload["result"]
            reason = str(after.get("reason") or before.get("reason") or "")
            kind = "saving throw" if reason.startswith("SAVE:") else "attack roll" if reason.startswith("ATTACK:") else "ability check" if reason.startswith("CHECK:") else "d20 roll"
            operation = {"reroll": "rerolled", "replace": "replaced", "bonus": "added a bonus to"}.get(payload.get("operation"), "changed")
            # The ability belongs to the creature that used it, which is not the one
            # whose roll was rewritten when an ally rerolls another's save. The
            # recorded user is the owner; without it the roll's own creature is named.
            user = _actor_name(payload.get("user_id"), actor_names) if payload.get("user_id") else None
            if user and user != actor:
                summary = (f"{user}'s {source} {operation} {actor}'s {kind}: {_roll_text(before)} → "
                           f"{_roll_text(after)}. The new result is used.")
            else:
                summary = f"{actor}'s {source} {operation} the {kind}: {_roll_text(before)} → {_roll_text(after)}. The new result is used."
        elif event_type == "COMPANION_DEFAULT_APPLIED":
            # An uncommanded creature Dodges automatically; the companion also holds its ground.
            summary = _COMPANION_DEFAULTS.get(str(payload.get("behavior") or ""),
                                               "{actor} took no action, so it takes the Dodge action.").format(actor=actor)
        elif event_type == "ONCE_PER_TURN_CLAIMED":
            # Owner 2026-10-02 (hunt DS12 #2): this used to fall through to the dead-placeholder
            # else. An internal once-per-turn guard changed nothing a player can see, so it is
            # hidden; an ability's claim says plainly that it is spent until the next turn.
            scope = str(payload.get("scope") or "")
            if scope.startswith(("_", "system:")):
                continue
            spent = source if source not in ("System", "Unnamed effect") else "an effect"
            summary = f"{actor} used {spent} this turn; it can happen again on their next turn."
        elif event_type == "AMBIENT_SET":
            # The table owner's light change (combat/match_ambient.py): said plainly, in the fight's own words.
            changed = payload.get("ambient") or {}
            names = {0: "dark", 1: "dim", 2: "bright"}
            roof = names.get(changed.get("indoor_level"))
            if changed.get("time_of_day") or changed.get("level") in names:
                what = changed.get("time_of_day") or names[changed["level"]]
                summary = f"The table owner set the light to {what}"
                summary += f"; under a roof it is {roof}." if roof else "."
            else:
                summary = f"The table owner set the light under a roof to {roof}."
        elif event_type == "EQUIPMENT_READINESS_SET":
            summary = str(payload.get("log") or "")
            if not summary:
                detailed = False
                continue
        elif event_type == "FIGHT_SETUP_COMPLETED":
            # Owner 2026-10-02 (hunt DS12 #2): the setup step records its own plain line.
            summary = str(payload.get("log") or "Fight setup is complete; the first turn begins.")
        # Typed Factory abilities (combat/typed_executor.py).
        elif event_type == "PASSIVE_TRIGGERED" and payload.get("text"):
            summary = str(payload["text"])  # a plug-in's plain line for something that happened (combat/ext/placed.py note)
        elif event_type == "PASSIVE_TRIGGERED" and payload.get("zone_id"):
            zone_name = _name(payload.get("trigger"), definition_names) if payload.get("trigger") else source
            moment = payload.get("moment")
            timing = {"start": "starts its turn in", "end": "ends its turn in", "enter": "enters"}.get(moment, "is affected by")
            summary = f"{targets or 'A creature'} {timing} {actor}'s {zone_name}; the area's effects resolve below."
        elif event_type == "PASSIVE_TRIGGERED" and payload.get("kind") == "attack_target_intercepted":
            # Generic line for any interception provider that wrote no sentence of its own: no creature was rolled
            # against, so the strike is narrated against the stand-in it actually hit.
            original = _name(payload.get("original_target_id"), actor_names) if payload.get("original_target_id") else "its target"
            summary = f"{actor}'s {source} struck a stand-in instead of {original}; no attack was made against {original}."
        elif event_type == "PASSIVE_TRIGGERED" and payload.get("log"):
            summary = str(payload["log"])  # a plug-in's own plain line (combat/ext note())
        elif event_type == "PASSIVE_TRIGGERED":
            summary = passive_text(payload, actor, source,
                                   [_actor_name(target, actor_names) for target in target_ids], definition_names)
            if summary is None:
                detailed = False
                summary = "Detailed breakdown was not recorded for this event."
        elif event_type == "GM_RIDER":
            if type(payload.get("completed_outcome_sequence")) is int and any(
                    e.get("sequence") == payload["completed_outcome_sequence"]
                    and e.get("event_type") in {"DAMAGE_COMMITTED", "MOVEMENT_GRANTED", "CONDITION_APPLIED"}
                    and e.get("actor_id") == actor_id
                    and e.get("trigger_or_intent_id") == event.get("trigger_or_intent_id")
                    and (e.get("event_type") == "MOVEMENT_GRANTED" or
                         set(target_ids).issubset(e.get("target_ids") or []))
                    and e.get("sequence", 0) < event.get("sequence", 0) for e in events):
                continue  # the recorded benefit already has its own outcome line
            # A "not automated" reminder is one line per use, so it stays whenever any strike of that use
            # resolved against a creature. It is hidden only when every strike was intercepted (its on-hit
            # effects never happened); the journal keeps it in full either way.
            if "not automated" in str(payload.get("rider_display_text") or payload.get("rider") or "") and _all_strikes_intercepted(
                    events, actor_id, source_id, event.get("trigger_or_intent_id")):
                continue
            profile = (action_profiles or {}).get(source_id)
            if profile is not None:
                payload = {"selected_augments": profile.get("augments") or [], **payload}
            summary = rider_text(payload, actor, source, targets)
            if not summary:
                continue  # typing commentary alone records no effect for the GM
        elif event_type == "MAXIMUM_HP_CHANGED":
            summary = str(payload.get('log') or f"{targets or actor}'s Hit Point maximum changed.")
        elif event_type == "STOOD_UP":
            summary = str(payload.get('log') or f'{actor} stands up.')
        elif event_type in {'ACTOR_SIDE_CHANGED', 'RELATION_CHANGED', 'SUMMON_DISMISSED'} and payload.get('log'):
            summary = str(payload['log'])
        elif event_type == "HEALING_APPLIED":
            summary = payload.get('blocked_log') or f"{actor}'s {source} healed {targets or actor} for {payload.get('offered', 'an unrecorded amount')}; HP {payload.get('before', '?')} → {payload.get('after', '?')}."
        elif event_type == "SAVE_AUTO_FAILED":
            summary = f"{actor} automatically failed the {payload.get('ability') or ''} save against {source} (condition)."
        elif event_type == "MOVEMENT_GRANTED" and payload.get('log'):
            summary = str(payload['log'])
        elif event_type == "MOVEMENT_GRANTED" and int(payload.get("distance_ft") or 0) < 0:
            summary = f"{actor} lost {-int(payload['distance_ft'])} ft of movement this turn ({source}: a heavier load)."
        elif event_type == "MOVEMENT_GRANTED":
            summary = f"{actor} gained {payload.get('distance_ft', 'extra')} ft of movement from {source}."
        elif event_type == "CHECK_ROLLED":
            # An explicit presentation identity never replaces mechanical
            # actor/target provenance in the journal or raw feed record.
            targets = (payload.get('check_metadata') or {}).get('opponent_display_name') or targets
            roll = payload.get("actor") or {}
            outcome = "success" if payload.get("success") else "failure"
            total = f"{roll.get('total', '?')} vs DC {payload.get('dc', '?')}"
            if payload.get("roll_kind") == "opposed_check" and payload.get("target"):
                opposing = payload["target"]
                outcome = "tie; the situation stays unchanged" if payload.get("tied") and "outcome_override" not in payload else outcome
                summary = (f"{actor} — {source} against {targets}: {_roll_text(roll)} "
                           f"against {_roll_text(opposing)} ({payload.get('against') or 'opposing check'}); {outcome}.")
            elif payload.get("roll_kind") == "dc_check":
                # A printed difficulty, not a defending die: "Sound Check 22 against its Save DC (15); success."
                recipient = f" for {targets}" if targets else ""
                summary = (f"{actor} — {source}{recipient}: {_roll_text(roll)} against {payload.get('dc', '?')} "
                           f"({payload.get('against') or 'the printed difficulty'}; "
                           f"{payload.get('check') or 'check'}); {outcome}.")
            elif payload.get("check") == "Stealth":
                summary = f"{actor} tried to hide: Stealth {total}, {outcome}."
            elif payload.get("check") == "Perception" and payload.get("by_sense"):
                summary = f"{actor} found {targets or 'someone hidden'} with its senses ({', '.join(payload['by_sense'])})."
            elif payload.get("check") == "Perception":
                summary = f"{actor} searched for {targets or 'someone hidden'}: Perception {total}, {'found' if payload.get('success') else 'not found'}."
            else:
                summary = f"{actor} made a check for {source}: {total}, {outcome}."
        else:
            detailed = False
            summary = "Detailed breakdown was not recorded for this event."

        # Several causes of Advantage/Disadvantage do not stack. Keep every raw
        # modifier event, but narrate adjacent equivalent mode records once.
        # Never combine additive modifiers, distinct sources/durations, opposing
        # modes, or records separated by an attack or any other event.
        if (mode_record and mode_record.get("target_field") == "attack_mode"
                and mode_record.get("operation") == "SET"
                and mode_record.get("value") in {"ADVANTAGE", "DISADVANTAGE"}):
            previous_mode = (event_type, actor_id, tuple(target_ids),
                mode_record.get("source_definition_id") or source_id,
                mode_record.get("target_id"), mode_record.get("value"),
                mode_record.get("applies_to"), mode_record.get("expires_on"),
                mode_record.get("expires_actor_id"), mode_record.get("expires_turn_count"),
                payload.get("reason"), payload.get("checkpoint"))
            if previous_mode == prior_mode:
                continue

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
