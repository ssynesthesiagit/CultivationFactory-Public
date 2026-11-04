"""Exact, source-checked flight and Expertise conversions for the rider census.

Only whole residual rider strings are retired. A fixed self-flight grant must
be a standalone, unconditional line in an active ability's own benefit list;
summon statistics, selected alternatives, relative speeds and qualified flight
remain untouched. Expertise names one skill and is a permanent build benefit,
so every later sentence under its heading must prove it is a separate benefit:
prose that could limit the grant leaves it a rider. The orchestrating converter
owns printed-text and input-mechanic hash binding.
"""
from __future__ import annotations

import copy
import re
from typing import Any


_ABILITIES = {
    "strength": "STR", "dexterity": "DEX", "constitution": "CON",
    "intelligence": "INT", "wisdom": "WIS", "charisma": "CHA",
}
_SKILLS = {
    "Acrobatics": "DEX", "Animal Handling": "WIS", "Arcana": "INT",
    "Athletics": "STR", "Deception": "CHA", "History": "INT",
    "Insight": "WIS", "Intimidation": "CHA", "Investigation": "INT",
    "Medicine": "WIS", "Nature": "INT", "Perception": "WIS",
    "Performance": "CHA", "Persuasion": "CHA", "Religion": "INT",
    "Sleight of Hand": "DEX", "Stealth": "DEX", "Survival": "WIS",
}
_EXPERTISE = re.compile(
    r"Gain Expertise in (Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) "
    r"\(([^()]+)\)\.", re.I,
)
_FLIGHT = re.compile(
    r"(?:(?:you )?gain (?:a )?)?Fly(?: Speed)?(?: of)? (?P<feet>[1-9]\d*) feet"
    r"(?:,? and|,| with) (?:can )?Hover[.;]?", re.I,
)
_FLIGHT_WRAPPERS = (
    re.compile(r"^blocked: flight/altitude\s*--\s*", re.I),
    re.compile(r"\s*\((?:the GM's|blocked: flight/altitude|the table does not model flight)\)\.?$", re.I),
)
_BENEFIT_START = re.compile(
    r"(?:for the duration(?:,? (?:you )?gain)?|gain(?: the following benefits)?|"
    r"you transform into [^.]+\. gain):$", re.I,
)
# Trailing prose that names the grant, points back at it with "this bonus" or a
# bare "it", or names the skill the grant covers, is talking about the grant
# itself: it can restrict the Expertise instead of adding a separate benefit.
# Skill/rank terminology and an untrained or unproficient outcome also refer
# to the grant, even without its name ("your skill rank becomes untrained").
# A later sentence cannot be resolved back to what it refers to, so it fails
# closed and the grant stays a rider.
_GRANT_REFERENCE = re.compile(
    r"\b(?:expertises?|bonus(?:es)?|benefits?|proficienc(?:y|ies)|this|these|those|such|"
    r"it|its|them|their|skills?|ranks?|untrained|unproficient)\b", re.I)
# Independence must be shown by the sentence's own words. A triggered rule has
# to carry an effect of its own after its trigger, and a stated limit has to
# name what it stops from happening, so a sentence that only restricts the grant
# is refused. A trailing sentence opening with a state ("While mounted, ...") is
# refused on purpose: a state qualifies an existing grant, so it leaves the
# grant a rider.
# Each word list is one non-capturing group with a boundary on both sides. An
# interpolated bare alternation ("treat|gain|...") splits into whole branches of
# the enclosing pattern instead: only the first branch keeps its trigger, the
# rest match anywhere in the sentence, and each matches inside a longer word
# ("unaffected", "unchanged"). The optional suffix keeps the ordinary inflections
# of one word ("prevents", "removed", "succeeding") counted as that same word.
_ANY_FORM = r"(?:s|es|ed|d|ing|led|ped)?\b"
_EFFECT_OF_ITS_OWN = (
    r"\b(?:treat|gain|create|summon|heal|restore|add|become|ignore|count|choose|make|set|"
    r"reduce|increase|reroll|re-roll|bypass|succeed|fail)" + _ANY_FORM)
_NAMED_OUTCOME = (
    r"\b(?:allow|prevent|stop|ignore|bypass|cancel|remove|change|affect|succeed|fail|"
    r"automatically|instead of|as if)" + _ANY_FORM)
_INDEPENDENT_TRIGGERED = re.compile(
    rf"^(?:when|whenever|after|before|if|on)\b[^,]*,.*{_EFFECT_OF_ITS_OWN}", re.I)
_INDEPENDENT_LIMIT = re.compile(
    rf"\b(?:does not|do not|cannot|can't|never)\b[^.]*{_NAMED_OUTCOME}", re.I)


def _line(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lstrip("-• "))


def _flight_line(text: str) -> re.Match[str] | None:
    return _FLIGHT.fullmatch(_line(text))


def _printed_self_flights(source_text: str) -> dict[int, str]:
    """Only an unqualified line under a self-benefit header proves ownership."""
    found: dict[int, str] = {}
    previous = ""
    prefix: list[str] = []
    for raw in source_text.splitlines():
        line = _line(raw)
        if not line:
            continue
        match = _flight_line(line)
        if match and _BENEFIT_START.search(previous):
            # Retain all preceding context, so an intervening heading cannot
            # turn a selected/conditional grant or a summon stat block into a
            # self benefit. Reject conservatively when ownership is ambiguous.
            if not re.search(r"\b(?:if|when|choose|on a|failed save|successful save|while|"
                             r"summon|summoned|conjure|conjured|creature|target|ally|allies)\b",
                             " ".join(prefix), re.I):
                found[int(match["feet"])] = line
        previous = line
        prefix.append(line)
    return found


def _clean_flight_rider(rider: str) -> str:
    text = _line(rider)
    for pattern in _FLIGHT_WRAPPERS:
        text = pattern.sub("", text)
    return text.rstrip(".")


def _names_the_grant(line: str, skill: str) -> bool:
    """True when a later sentence is about the Expertise, not a separate effect.

    Naming the skill the grant covers is naming the grant: "Animal Handling
    cannot be used while dismounted." limits the bonus, so it is not a separate
    benefit and the grant stays a rider.
    """
    if _GRANT_REFERENCE.search(line):
        return True
    return bool(re.search(rf"\b{re.escape(skill)}\b", line, re.I))


def _unconditional_expertise_lines(source_text: str) -> set[str]:
    """A permanent grant is the first substantive rule below its heading.

    A later branch that merely prints the same sentence is not an always-on
    benefit. Flavor headings are harmless; conditions and benefit menus are not.
    Every later sentence of the same ability must establish that it is an
    independent benefit: it may neither talk about the grant nor leave its own
    effect unstated. Unreadable, grant-referring or purely restricting prose may
    be a limitation, so the grant stays a rider.
    """
    lines: list[str] = []
    for raw in source_text.splitlines():
        line = _line(raw)
        if not line:
            continue
        if line.startswith("#"):
            if lines:
                break  # The next heading ends this ability's printed text.
            continue
        lines.append(line)
    grant = _EXPERTISE.fullmatch(lines[0]) if lines else None
    if grant is None:
        return set()
    skill = grant[2]
    for line in lines[1:]:
        if _names_the_grant(line, skill):
            return set()
        if _INDEPENDENT_TRIGGERED.match(line) or _INDEPENDENT_LIMIT.search(line):
            continue  # Its own triggered effect, or a stated limit: separate benefit.
        return set()
    return {lines[0].casefold()}


def _remove_obsolete_flight_rows(rows: list[Any], speed: int) -> list[Any]:
    """Drop only flat parser substitutes for the same exact flight line.

    Those rows either add walking movement or are deferred no-ops. More complex
    movement, differing speeds, and effects without exact evidence are retained.
    """
    result = []
    for row in rows:
        if not isinstance(row, dict):
            result.append(row)
            continue
        match = _flight_line(str(row.get("evidence") or ""))
        if (row.get("type") in {"movement", "speed"} and match
                and int(match["feet"]) == speed and row.get("applies_to") in (None, "self")
                and not any(row.get(key) for key in ("on_hit", "on_fail", "effects", "menu", "option"))):
            continue
        result.append(row)
    return result


def convert(mechanic: dict[str, Any], source_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return an independent mechanic and exact match receipts; never mutate input."""
    patched = copy.deepcopy(mechanic)
    matches: list[dict[str, Any]] = []
    riders = list(mechanic.get("riders") or [])
    remaining = []
    activation = mechanic.get("activation") or {}
    duration = mechanic.get("duration") or {}
    active = activation.get("economy") in {"action", "bonus_action"}
    timed = duration.get("kind") in {"rounds", "minutes", "hours", "days"} and type(duration.get("amount")) is int and duration["amount"] > 0
    flights = _printed_self_flights(source_text) if active and timed and not mechanic.get("options") else {}
    source_lines = _unconditional_expertise_lines(source_text)
    for index, rider in enumerate(riders):
        if not isinstance(rider, str):
            remaining.append(rider)
            continue
        flight = _flight_line(_clean_flight_rider(rider))
        if flight and int(flight["feet"]) in flights:
            speed = int(flight["feet"])
            row = {"type": "general_flight", "applies_to": "self", "speed_ft": speed,
                   "hover": True, "duration": copy.deepcopy(duration), "evidence": flights[speed]}
            patched["effects"] = _remove_obsolete_flight_rows(list(patched.get("effects") or []), speed)
            if not any(effect.get("type") == "general_flight" and effect.get("speed_ft") == speed
                       for effect in patched["effects"] if isinstance(effect, dict)):
                patched["effects"].append(row)
            matches.append({"pattern": "fixed_flight_hover", "rider": rider, "path": f"/riders/{index}",
                            "behavior": "new_behavior",
                            "engine_seam": "general_flight -> flight.profile / native flight movement"})
            continue
        expertise = _EXPERTISE.fullmatch(_line(rider))
        if (expertise and _line(rider).casefold() in source_lines
                and activation.get("economy") in {"passive", "no_action"} and not mechanic.get("cost")):
            ability = _ABILITIES[expertise[1].lower()]
            skill = next((name for name in _SKILLS if name.casefold() == expertise[2].casefold()), None)
            if skill and _SKILLS[skill] == ability:
                row = {"type": "general_skill_expertise", "skill": skill, "ability": ability,
                       "evidence": _line(rider)}
                patched.setdefault("effects", []).append(row)
                matches.append({"pattern": "fixed_skill_expertise", "rider": rider, "path": f"/riders/{index}",
                                "behavior": "new_behavior",
                                "engine_seam": "compile_skill_bonuses -> sealed bundle skill totals"})
                continue
        remaining.append(rider)
    patched["riders"] = remaining
    return patched, matches
