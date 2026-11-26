"""Shared fixed-flight and named-skill Expertise handlers for converted riders.

general_flight applies only an explicit typed self-flight row. Native flight
owns paths, shared movement, opportunity attacks, altitude, Hover and falling;
ordinary walking speed never changes. Named Expertise is resolved only when a
new character bundle is compiled, using the generic compile_skill_bonuses hook.
Neither handler reads live authority for an old saved fight.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .condition_ownership import remove_instance


FLIGHT_CONDITION = "condition:typed.general_flight"


@effect("general_flight")
def grant_flight(ctx: Any, row: dict[str, Any]) -> None:
    """Explicit fixed self-flight, evented and bounded by the owning ability."""
    from ..typed_executor import effect_expiry

    speed = row.get("speed_ft")
    if type(speed) is not int or speed <= 0 or row.get("applies_to") != "self":
        raise ValueError("A fixed flight grant requires positive integer feet and a self recipient")
    duration = row.get("duration") or {}
    if (not isinstance(duration, dict) or duration.get("kind") not in {"rounds", "minutes", "hours", "days"}
            or type(duration.get("amount")) is not int or duration["amount"] <= 0):
        raise ValueError("A fixed flight grant requires a positive counted duration")
    expires = effect_expiry(ctx, row, ctx.actor, condition=True)
    if not expires:
        raise ValueError("A fixed flight grant requires a finite ability duration")
    # A second copy of this source refreshes it; another active flight source
    # remains independent and may outlast this one.
    previous = [instance for instance, held in ctx.actor.conditions.items()
                if held.condition_id == FLIGHT_CONDITION and held.source_actor_id == ctx.actor.entity_id
                and held.source_definition_id == ctx.source]
    # Install before retiring the old instance: condition-removal events settle
    # native falling immediately, so a refresh must never open a flight gap.
    ctx.engine._apply_condition(ctx.actor, FLIGHT_CONDITION, ctx.source, ctx.actor.entity_id,
                               expires_on=expires,
                               data={"fly_speed_ft": speed, "flight_hover": int(bool(row.get("hover"))),
                                     "label": f"Fly Speed {speed} feet" + ("; Hover" if row.get("hover") else "")})
    for instance in previous:
        remove_instance(ctx.engine, ctx.actor, instance, ctx.source)


CANONICAL_SKILLS = {
    "acrobatics": ("Acrobatics", "DEX"),
    "animal handling": ("Animal Handling", "WIS"),
    "arcana": ("Arcana", "INT"),
    "athletics": ("Athletics", "STR"),
    "deception": ("Deception", "CHA"),
    "history": ("History", "INT"),
    "insight": ("Insight", "WIS"),
    "intimidation": ("Intimidation", "CHA"),
    "investigation": ("Investigation", "INT"),
    "medicine": ("Medicine", "WIS"),
    "nature": ("Nature", "INT"),
    "perception": ("Perception", "WIS"),
    "performance": ("Performance", "CHA"),
    "persuasion": ("Persuasion", "CHA"),
    "religion": ("Religion", "INT"),
    "sleight of hand": ("Sleight of Hand", "DEX"),
    "stealth": ("Stealth", "DEX"),
    "survival": ("Survival", "WIS"),
}
_GRANT_KEYS = {"type", "skill", "ability", "evidence", "origin", "rank", "increment_per_copy", "max_rank"}


def _rank(row: dict[str, Any]) -> int | None:
    from ..ability_checks import proficiency_rank

    return proficiency_rank(row)


def _parse_skill_grant(row: dict[str, Any], source: str, copies: int) -> dict[str, Any]:
    kind = row.get("type")
    raw_skill = row.get("skill")
    canonical = CANONICAL_SKILLS.get(raw_skill.casefold()) if isinstance(raw_skill, str) else None
    if canonical is None or row.get("ability") != canonical[1]:
        raise ValueError(f"{source}: skill grant requires a canonical skill and ability")
    skill, ability = canonical
    if kind == "general_skill_expertise":
        return {"skill": skill, "ability": ability, "source": source, "kind": "floor", "rank": 2}
    if set(row) - _GRANT_KEYS:
        raise ValueError(f"{source}: unsupported general_skill_grant fields")
    has_rank = "rank" in row
    has_inc = "increment_per_copy" in row or "max_rank" in row
    if has_rank == has_inc:
        raise ValueError(f"{source}: general_skill_grant requires either rank or increment_per_copy with max_rank")
    if has_rank:
        rank = row.get("rank")
        if type(rank) is not int or rank not in (1, 2):
            raise ValueError(f"{source}: general_skill_grant rank must be integer 1 or 2")
        return {"skill": skill, "ability": ability, "source": source, "kind": "floor", "rank": rank}
    inc = row.get("increment_per_copy")
    cap = row.get("max_rank")
    if type(inc) is not int or inc <= 0 or type(cap) is not int or cap not in (1, 2):
        raise ValueError(f"{source}: general_skill_grant requires positive integer increment_per_copy and max_rank 1 or 2")
    return {"skill": skill, "ability": ability, "source": source, "kind": "increment",
            "increment_per_copy": inc, "max_rank": cap, "copies": copies}


def _grant_target_rank(input_rank: int, grant: dict[str, Any]) -> int:
    if grant["kind"] == "floor":
        return max(input_rank, grant["rank"])
    clamped = min(grant["max_rank"], input_rank + grant["increment_per_copy"] * grant["copies"])
    return max(input_rank, clamped)


def _grant_reaches_expertise(input_rank: int, grant: dict[str, Any]) -> bool:
    if grant["kind"] == "floor":
        return grant["rank"] >= 2
    return min(grant["max_rank"], input_rank + grant["increment_per_copy"] * grant["copies"]) >= 2


@hook("compile_skill_bonuses")
def compile_expertise(info: dict[str, Any]) -> dict[str, Any] | None:
    """Apply typed skill proficiency/Expertise grants, preserving independent adjustments.

    Explicit rank replaces the proficiency component of the final sheet total.
    Legacy totals without rank remain unchanged, with a diagnostic; their
    unknown proficiency component and independent adjustments are not guessed.
    """
    grants: dict[str, list[dict[str, Any]]] = {}
    source_skills: dict[str, set[str]] = {}
    handled = []
    owned_ids = list(dict.fromkeys(info.get("owned_ids") or ()))
    learned = ((info.get("owner_sheet") or {}).get("spheres_and_talents") or {}).get("learned_talent_record_ids") or ()
    mechanics = info.get("mechanics") or {}
    for source in owned_ids:
        mechanic = mechanics.get(source) or {}
        effects = mechanic.get("effects") or []
        owned = [row for row in effects if isinstance(row, dict)
                 and row.get("type") in {"general_skill_expertise", "general_skill_grant"}]
        if not owned:
            continue
        copies = max(1, sum(1 for item in learned if item == source))
        for row in owned:
            grant = _parse_skill_grant(row, source, copies)
            grants.setdefault(grant["skill"], []).append(grant)
            source_skills.setdefault(source, set()).add(grant["skill"])
        if len(owned) == len(effects) and not mechanic.get("riders") and not mechanic.get("modifier"):
            handled.append(source)
    if not grants:
        return None
    rows = copy.deepcopy(info["skills"])
    by_name = {str(row.get("skill")).casefold(): row for row in rows if isinstance(row, dict)}
    notes = []
    unresolved = set()
    pb = int(info["pb"])
    for skill in sorted(grants):
        skill_grants = grants[skill]
        ability = skill_grants[0]["ability"]
        modifier = int(info["mods"].get(ability, 0))
        row = by_name.get(skill.casefold())
        if row is None:
            row = {"skill": skill, "bonus": modifier, "proficiency_multiplier": 0}
            rows.append(row)
            by_name[skill.casefold()] = row
        old = row.get("bonus")
        rank = _rank(row)
        if rank is None:
            unresolved.add(skill)
            notes.append(f"{skill}: Skill grants and Expertise need an explicit proficiency rank to preserve independent adjustments. The legacy sheet total is unchanged; verify this skill's proficiency rank and bonus on the character sheet.")
            continue
        if isinstance(old, str):
            try:
                old = int(old)
            except ValueError:
                pass
        if type(old) is not int:
            unresolved.add(skill)
            notes.append(f"{skill}: Skill grants and Expertise need an integer skill total to preserve independent adjustments. The listed total is unchanged; verify this skill's bonus on the character sheet.")
            continue
        target = max(_grant_target_rank(rank, grant) for grant in skill_grants)
        bonus = old + (target - rank) * pb
        if target >= 2:
            expertise_sources = [grant["source"] for grant in skill_grants if _grant_reaches_expertise(rank, grant)]
            row.update(skill=skill, bonus=bonus, proficiency="expertise", proficiency_multiplier=2, expertise=True)
            if expertise_sources:
                row["expertise_source"] = expertise_sources[0]
        else:
            row.pop("expertise", None)
            row.pop("expertise_source", None)
            row.update(skill=skill, bonus=bonus, proficiency="proficient", proficiency_multiplier=1)
    return {"skills": [by_name[skill.casefold()] for skill in sorted(grants) if skill not in unresolved], "notes": notes,
            "handled_features": [source for source in handled if not source_skills[source] & unresolved]}
