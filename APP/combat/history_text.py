"""Read-only battle-log vocabulary used by history_feed and the history service.

Names come from saved display names or compiled authority; outcomes and clocks
come only from recorded events. No rules are executed by this presentation API.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def _vocabulary() -> dict[str, str]:
    document = json.loads((Path(__file__).resolve().parents[1] / "authority" /
                           "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    names = {key: row["name"].title() if row["name"].isupper() else row["name"]
             for key, row in document["mechanics"].items() if row.get("name")}
    for row in document.get("resources", {}).values():
        if row.get("name"):
            names[re.sub(r"[^a-z0-9]+", "_", row["name"].lower()).strip("_")] = row["name"]
    return names


#: Engine-owned sources whose own id reads as a code name, and the plain words a player reads
#: instead (owner 2026-09-30: no internal ids or unexplained jargon in a player-facing line).  The
#: values are the reason the effect happened, not a label for it, because they are read inside
#: "X applied Dodge to X (<here>)".  Add an entry here rather than special-casing a caller.
SYSTEM_SOURCE_NAMES = {
    "system:combat.summon_default": "it was not commanded",
    "system:combat.companion_default": "it Dodges automatically",
    "system:combat.summon_duration": "its 1 minute of summoning",
}


def history_name(stable_id: str | None, names: dict[str, str]) -> str:
    """Resolve a display name without exposing namespaces, hashes or option IDs."""
    if not stable_id:
        return "System"
    if not any(character in stable_id for character in (":", ".", "_", "#", "+")):
        return stable_id
    if stable_id in names and names[stable_id] != stable_id:
        return names[stable_id]
    if stable_id in SYSTEM_SOURCE_NAMES:
        return SYSTEM_SOURCE_NAMES[stable_id]
    if stable_id.startswith("resource:uses."):
        return history_name(stable_id[len("resource:uses."):], names) + " uses"
    clean = stable_id.split("#", 1)[0].split("+", 1)[0]
    vocabulary = _vocabulary()
    if clean in vocabulary:
        return vocabulary[clean]
    for piece in reversed(clean.split(".")):
        if piece in vocabulary:
            return vocabulary[piece]
    # Slugs carry names for core conditions, named pools, legacy talents, marks.
    tail = clean.split(":")[-1].split(".")[-1]
    if tail in vocabulary:
        return vocabulary[tail]
    if re.fullmatch(r"[a-fA-F0-9-]{8,}|\d+", tail):
        return "Unnamed effect"
    tail = re.sub(r"^(?:TAL|BASE|PATH)_", "", tail)
    return tail.replace("_", " ").title() or "Unnamed effect"


def passive_text(payload: dict[str, Any], actor: str, source: str,
                 targets: list[str], names: dict[str, str]) -> str | None:
    """Describe shared recorded passive outcomes, never calculate a new result.

    Redirected-roll records list the attacker then the new defender. AC recheck
    records belong to the defender and list the attacker. Other trigger strings
    are plug-in prose or definition IDs, resolved through the shared vocabulary.
    """
    if type(payload.get("save_bonus")) is int:
        bonus = payload["save_bonus"]
        ability = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
                   "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}.get(str(payload.get("ability", "")).upper(), "")
        affected = f" for {', '.join(targets)}" if targets and targets != [actor] else ""
        return (f"{actor}'s {source}: {'+' if bonus >= 0 else ''}{bonus} "
                f"to this {ability + ' ' if ability else ''}saving throw{affected}.")
    if isinstance(payload.get("ac_bonus"), int) and isinstance(payload.get("new_ac"), int):
        bonus = payload["ac_bonus"]
        against = payload.get("against")
        kind = f" {against}" if against in ("melee", "ranged") else ""
        outcome = "; the attack misses" if payload.get("hit_after_recheck") is False else ""
        attacker = f" from {', '.join(targets)}" if targets else ""
        return (f"{actor}'s {source}: AC {'+' if bonus >= 0 else ''}{bonus} against the{kind} attack"
                f"{attacker}, now AC {payload['new_ac']}{outcome}.")
    if (len(targets) == 2 and isinstance(payload.get("total"), int)
            and isinstance(payload.get("ac"), int) and isinstance(payload.get("hit"), bool)):
        attacker, defender = targets
        result = "Hit" if payload["hit"] else "Miss"
        return (f"{actor} used {source}: {attacker}'s attack now targets {defender}; "
                f"attack total {payload['total']} against AC {payload['ac']} — {result}.")
    trigger = str(payload.get("trigger") or "")
    if not trigger:
        return None
    if trigger.startswith(actor + " ") and trigger.endswith("."):
        return trigger  # older Needle helpers recorded complete prose as a trigger
    if trigger in names or re.match(r"^(?:action|passive|condition|resource):|^tianxia\.|^[A-Z]+_(?:TAL|BASE|PATH)_|^(?:TAL|BASE|PATH)_", trigger):
        trigger = history_name(trigger, names)
    weapon = payload.get("with")
    using = f" using {history_name(str(weapon), names)}" if weapon else ""
    affected = f" against {', '.join(targets)}" if targets else ""
    return f"{actor} triggered {trigger}{using}{affected}."


# Commentary about the typing itself, never a rule the GM still has to apply: it names
# the table, a person, a source file, a screen control, or a decision already made
# for the GM.
_TYPING_COMMENTARY = re.compile(r"\b(?:audit|coordinator|worker|simplified|not automated|"
                                r"(?:the|this) table|implemented|implementation|adjudication|printed riders|"
                                r"locked engine|interpreter|pre-cost seam|provenance/benefit hook|"
                                r"button|UI|toggle|panel|tooltip)\b|"
                                r"combat[/.]|\.py\b|Action Type:|\bblocked\s*:|\bthe GM's\b|"
                                r"\bthe GM must resolve this additional effect\b|\bthe GM applies it\b", re.I)
# A printed rule may require a GM-set DC. The bare word is never commentary.
_SOURCE_REF = re.compile(r"\(?\b(?:combat|factory_authoring|tools|tests)/[\w./-]+(?:\.py)?\)?|\b[\w-]+\.py\b")

# A dash note appended to a rule: "... as an Action to end it -- the GM's."
_DASH_NOTE = re.compile(r"\s+--\s+")


def _without_commentary_brackets(text: str) -> str:
    """Drop brackets that only talk about the table, keeping the rule around them.

    A rule often ends in a bracket about how the table records it ("...while it
    remains within 120 feet (no readout on this table; GM adjudicates)."). The
    bracket is commentary, but the sentence in front of it is the rule, so the
    bracket is removed on its own instead of taking the whole line with it.
    """

    def drop(match: re.Match[str]) -> str:
        return " " if _TYPING_COMMENTARY.search(match.group(1)) else match.group(0)

    for _ in range(4):  # a bracket inside a bracket, however deep, is still a bracket
        stripped = re.sub(r"\(([^()]*)\)", drop, text)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split())


def _without_commentary_tail(sentence: str) -> str:
    """Cut a trailing typing note off a rule instead of dropping the whole sentence.

    Riders qualify a rule with a dash note about the table ("an unwilling one makes
    a Charisma save as an Action to end it -- the GM's."). The note is commentary,
    but the rule it is attached to is still a rule, so the note is removed on its
    own. A semicolon can also link a note between two rules ("A -- the table does it
    -- B"), so every note but the one in front is removed while the rules survive.
    """
    pieces = _DASH_NOTE.split(sentence)
    if len(pieces) == 1:
        return sentence
    kept = [piece for piece in pieces[:-1] if not _TYPING_COMMENTARY.search(piece)]
    if _TYPING_COMMENTARY.search(pieces[-1]):
        if not kept:  # the sentence was nothing but the note
            return ""
        # The dropped note carried the sentence's full stop, so the rule in front of
        # it has to end on one too, or the next sentence runs into it.
        rule = kept[-1].rstrip()
        if not rule.endswith((".", "!", "?")):
            kept[-1] = rule.rstrip(":") + "."
    else:
        kept.append(pieces[-1])
    return " -- ".join(piece for piece in kept if piece.strip())


def rider_text(payload: dict[str, Any], actor: str, source: str, targets: str) -> str | None:
    """Separate manual reminders from copied cards and implementation commentary.

    Raw events retain the full evidence. Do not truncate a rule mid-sentence, never
    discard a recovered rule for being long, and never infer whether an unflagged
    rider is applied: legacy producers use the same event for manual rules,
    completed outcomes and mixtures of the two, so keep reminders conditional and
    let neither a missing flag nor a partial feed instruct the GM to apply a
    completed effect again. Return None when nothing but commentary survives: a
    line that names no effect tells the GM nothing, so the caller drops the row
    instead of printing an empty one.
    """
    from .player_text import display_text, explain_cp, log_plain

    text = str(payload.get("rider_display_text", payload.get("rider")) or "")
    # Preserve the legacy "reminder / copied card" boundary before resolving a
    # complete authoring block. Raw journal payloads remain untouched.
    if not (payload.get("automated") is True or payload.get("adjudication_text") is True) and re.search(r"\s+/\s+#{2,}", text):
        text = re.split(r"\s+/\s+#{2,}", text, maxsplit=1)[0]
    text = display_text(text)
    if payload.get("automated") is True:
        return log_plain(text)
    # Some plug-ins record completed outcomes and explicit adjudication rules,
    # not an unapplied reminder. Keep that distinction in event structure so
    # ordinary words such as "GM" never decide whether a clause is discarded.
    if payload.get("adjudication_text") is True:
        return log_plain(text)
    # A compiled base action with no chosen augments cannot ask the GM to apply
    # the optional augment copied from its source card. Unknown legacy profiles
    # stay conditional; explicit completed/manual records above keep their text.
    if "selected_augments" in payload and not payload["selected_augments"]:
        text = re.split(r"\bAugments?\s*[-—:]", text, maxsplit=1, flags=re.I)[0]
    sections = [section for section in re.split(r"#{2,}", text) if section.strip()]
    text = sections[0] if sections else ""
    reminders = []
    for clause in re.split(r"\s+/\s+", text):
        clause = re.sub(r"\bRule reminder:\s*", "", clause)
        # An area header alone is targeting geometry, never a leftover effect.
        if re.fullmatch(r"\d+[- ]foot(?:[- ](?:radius|long|wide|high))?\s+(?:sphere|cone|line|cube|square|burst|emanation)\.?", clause, re.I):
            continue
        clause = log_plain(_without_commentary_brackets(clause))
        clause = re.sub(r"\s*\(the GM's\)", "", clause, flags=re.I)
        clause = _SOURCE_REF.sub("", clause)
        clause = re.sub(r"\s{2,}", " ", re.sub(r"\s+([,.;:])", r"\1", clause)).strip(" /,;: ")
        # Judgement belongs to the sentence that makes it: one typing note dropped
        # from the end of a rule must not cost the rule its text.
        kept = []
        for sentence in re.split(r"(?<=[.;])\s+", clause):
            sentence = _without_commentary_tail(sentence)
            if sentence and not _TYPING_COMMENTARY.search(sentence):
                kept.append(sentence)
        clause = " ".join(part.strip(" ,/") for part in kept).strip(" ;,/")
        clause = re.sub(r"\bRule reminder:\s*", "", clause)
        if clause:
            clause = explain_cp(clause)
            reminders.append(clause.rstrip(". ") + ".")
    reminder = " ".join(dict.fromkeys(reminders))
    # No length cutoff: a long reminder is usually several short rules, and dropping
    # it would hide a real instruction. A copied card is already cut at its first
    # heading above, and a card that is all one block is a data problem, not a reason
    # to lose a rule the GM still has to apply.
    if not reminder:
        return None
    affected = f" on {targets}" if targets else ""
    return (f"{actor}'s {source}{affected}: additional effect reminder. "
            "Resolve only effects that the recorded outcomes have not already applied. "
            f"Rule reminder: {reminder}")


def expiry_text(name: Any, actor_names: dict[str, str], source_actor: str, holder: str) -> str | None:
    """Translate recorded expiry tokens; never promise a printed duration not run.

    Returns None when the record carries no expiry clock this vocabulary can read.
    Callers then leave the duration out entirely: a duration is stated once, on the
    line that recorded it, and the player log never shows bookkeeping about a field
    the engine did not fill in.
    """
    token = str(name or "")
    fixed = {
        "END_OF_CURRENT_TURN": "until this turn ends",
        "START_OF_SELF_NEXT_TURN": "until the source or affected creature next starts a turn",
        "START_OF_TARGET_NEXT_TURN": "until the source or affected creature next starts a turn",
        "START_OF_SOURCE_NEXT_TURN": f"until {source_actor}'s next turn starts",
        "END_OF_HOLDER_NEXT_TURN": f"until {holder}'s next turn ends",
        "START_OF_MARKER_NEXT_TURN": f"until {source_actor}'s next turn starts",
        "END_OF_MARKER_NEXT_TURN": f"until {source_actor}'s next turn ends",
        "UNTIL_REMOVED": "until removed",
        "CONSUMED": "until used",
        "CONCENTRATION_END": "until concentration ends",
        "STAND_UP": "until standing up",
        "SOURCE_EFFECT_END": "until the source effect ends",
    }
    if token in fixed:
        return fixed[token]
    match = re.fullmatch(r"(START|END)_OF_TURN_AT:(.+):(\d+)", token)
    if match:
        edge, who, turn = match.groups()
        return f"until {actor_names.get(who, 'the affected creature')}'s turn {turn} {'starts' if edge == 'START' else 'ends'}"
    match = re.fullmatch(r"START_OF_SLOT_AT:(\d+):(\d+)", token)
    if match:
        return f"until round {match[1]}, turn {int(match[2]) + 1} starts"
    match = re.fullmatch(r"END_OF_SOURCE_TURN_AT:(\d+)", token)
    if match:
        return f"until {source_actor}'s turn {match[1]} ends"
    return None


_FIELDS = {
    "armor_class": "AC", "armor_class_vs_ranged": "AC against ranged attacks",
    "armor_class_vs_melee": "AC against melee attacks", "speed_ft": "Speed",
    "attack_roll": "attack rolls", "damage_roll": "damage rolls",
    "attack_mode": "attack rolls", "incoming_attack_mode": "attacks against them",
    "attack_mode_vs": "attack rolls",
    "saving_throw": "saving throws", "save_roll": "saving throws",
    "damage_resistance": "resistance to", "damage_immunity": "immunity to",
    "damage_vulnerability": "vulnerability to", "condition_immunity": "immunity to",
    "healing_reduction": "healing received", "speed_halved": "Speed",
    "speed_multiplier": "Speed", "damage_resistance_next": "resistance to the next damage of type",
    "resistance_suppressed": "resistance ignored for",
    "next_qualifying_attack_damage": "next qualifying attack's damage",
}


def duration_clause(duration: str | None) -> str:
    """One trailing duration clause, or nothing when the record carries no clock.

    A duration belongs to the line that recorded it. When nothing was recorded the
    sentence simply omits it, so the player never sees a second, contradictory
    duration claim or bookkeeping about an unfilled field.
    """
    return f"; {duration}" if duration else ""


# The roll modes an attack stamps on itself: what combat/typed_executor.add_strike_mode()
# records on the attacker for the attack being resolved (a target that is out of sight, a
# dodging target, a reach the weapon does not cover). Only "attack_mode" is that record.
# The other two roll-mode fields look similar but mean the opposite, and wording them as
# an attack's own roll would tell the player the wrong thing:
#   * "incoming_attack_mode" (Guardian Spirit Posture, Gu Brute) is defensive -- it
#     changes attacks made *against* the holder, not the holder's own attack roll.
#   * "attack_mode_vs" (Vex) is the holder's own next attack roll, but only against one
#     named creature, so dropping the named target would promise an unrestricted benefit.
# Both keep their own wording below: "attacks against them", and the named target.
_OWN_ROLL_MODE_FIELDS = ("attack_mode",)
_ROLL_MODES = ("ADVANTAGE", "DISADVANTAGE")


def _is_own_roll_mode(record: dict[str, Any]) -> bool:
    """True when a record is the attacker's own roll mode, not an effect on them.

    An attack's own modifiers are stamped on the attacker by the attack itself, with
    the ability as the modifier's source. Naming that ability as the cause read as
    "Bite penalised its own wolf": the roll mode belongs to the attack, so it is
    attributed to the attack rather than to the ability acting on its own user.
    A modifier on any *other* creature is a real effect and keeps its source, and a
    defensive or target-restricted roll mode keeps its direction and its target.
    """
    if str(record.get("target_field") or "") not in _OWN_ROLL_MODE_FIELDS:
        return False
    owner = str(record.get("source_actor_id") or "")
    return bool(owner) and owner == str(record.get("target_id") or "")


def _own_roll_clause(record: dict[str, Any]) -> str | None:
    """Plain wording for a creature's own attack roll mode, or None when unreadable."""
    value = str(record.get("value") or "").split(":", 1)[0].strip().upper()
    operation = str(record.get("operation") or "").strip().upper()
    mode = value if value in _ROLL_MODES else operation if operation in _ROLL_MODES else ""
    return f"is made with {mode.capitalize()} on the attack roll" if mode else None


def modifier_text(payload: dict[str, Any], source: str, who: str, duration: str | None,
                  actor_names: dict[str, str] | None = None) -> str | None:
    """Recorded modifier semantics, scope and recipient; markers are not bonuses.

Internal on-hit/watch records are plumbing for subsequent effects, not a second
effect on the character; those rows stay in raw events, outside the visible log.
"""
    field = str(payload.get("target_field") or "")
    if field.startswith("typed_") or field == "suppressed_condition":
        return None
    label = _FIELDS.get(field)
    value = payload.get("value")
    operation = payload.get("operation")
    if label is None:
        return f"{source} affects {who}{duration_clause(duration)}."
    if _is_own_roll_mode(payload):
        # The attack's own roll mode, checked before the effect chain so every
        # recorded shape of it (a bare mode, a named cause such as
        # "DISADVANTAGE:blinded", an Advantage) is worded the same way.
        clause = _own_roll_clause(payload)
        if clause:
            return f"{who}'s {source} {clause}{duration_clause(duration)}."
    units = " feet" if field == "speed_ft" else ""
    if payload.get("applies_to") == "NEXT_ATTACK":
        label = {"attack_mode": "their next attack roll",
                 "incoming_attack_mode": "the next attack roll against them",
                 "attack_mode_vs": "their next attack roll",
                 "attack_roll": "their next attack roll"}.get(field, label)
    if field == "speed_halved":
        effect = "Speed halved"
    elif operation in ("ADVANTAGE", "DISADVANTAGE"):
        effect = f"{operation.lower()} on {label}"
    elif field == "speed_multiplier":
        effect = f"Speed multiplied by {value}" if isinstance(value, int) else "Speed multiplier not described in this record"
    elif field == "healing_reduction" and str(value).removeprefix("next:") in ("half", "none"):
        once = "next healing" if str(value).startswith("next:") else "healing received"
        effect = f"{once} {'halved' if str(value).endswith('half') else 'prevented'}"
    elif field == "healing_reduction" and re.fullmatch(r"(?:next:)?minus:\d+", str(value)):
        once = "next healing" if str(value).startswith("next:") else "healing received"
        effect = f"{once} reduced by {str(value).rsplit(':', 1)[-1]} hit points"
    elif field == "attack_mode_vs" and re.fullmatch(r"(?:ADVANTAGE|DISADVANTAGE):.+", str(value)):
        mode, _, target = str(value).partition(":")
        rolls = "their next attack roll" if payload.get("applies_to") == "NEXT_ATTACK" else "attack rolls"
        effect = f"{mode.lower()} on {rolls} against {(actor_names or {}).get(target, 'the affected creature')}"
    elif isinstance(value, int):
        change = f"{'+' if value >= 0 else ''}{value}{units}"
        effect = f"{label} {change}" if operation == "ADD" else f"{label} becomes {value}{units}" if operation == "SET" else f"{label} changes by {value}{units}"
    elif value in ("ADVANTAGE", "DISADVANTAGE"):
        effect = f"{str(value).lower()} on {label}"
    elif field.startswith("damage_") or field in ("condition_immunity", "resistance_suppressed"):
        effect = f"{label} {history_name(str(value), {})}"
    elif operation == "SUBTRACT_DIE" and re.fullmatch(r"\d+d\d+", str(value)):
        effect = f"subtract {value} from {label}"
    else:
        return f"{source} affects {who}'s {label}{duration_clause(duration)}."
    return f"{who}: {effect} from {source}{duration_clause(duration)}."
