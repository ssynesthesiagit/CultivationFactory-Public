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


def _rank(row: dict[str, Any]) -> int | None:
    from ..ability_checks import proficiency_rank

    return proficiency_rank(row)


@hook("compile_skill_bonuses")
def compile_expertise(info: dict[str, Any]) -> dict[str, Any] | None:
    """Upgrade only printed Expertise, preserving independent skill adjustments.

    Explicit rank replaces the proficiency component of the final sheet total.
    Legacy totals without rank remain unchanged, with a diagnostic; their
    unknown proficiency component and independent adjustments are not guessed.
    """
    grants: dict[str, tuple[str, str]] = {}
    source_skills: dict[str, set[str]] = {}
    handled = []
    for source in info["owned_ids"]:
        mechanic = info["mechanics"].get(source) or {}
        effects = mechanic.get("effects") or []
        owned = [row for row in effects if isinstance(row, dict) and row.get("type") == "general_skill_expertise"]
        for row in owned:
            grants.setdefault(str(row["skill"]), (str(row["ability"]), source))
            source_skills.setdefault(source, set()).add(str(row["skill"]))
        if owned and len(owned) == len(effects) and not mechanic.get("riders") and not mechanic.get("modifier"):
            handled.append(source)
    if not grants:
        return None
    rows = copy.deepcopy(info["skills"])
    by_name = {str(row.get("skill")).casefold(): row for row in rows if isinstance(row, dict)}
    notes = []
    unresolved = set()
    pb = int(info["pb"])
    for skill, (ability, source) in sorted(grants.items()):
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
            notes.append(f"{skill}: Expertise needs an explicit proficiency rank to preserve independent adjustments. The legacy sheet total is unchanged; verify this skill's proficiency rank and bonus on the character sheet.")
            continue
        if isinstance(old, str):
            try:
                old = int(old)
            except ValueError:
                pass
        if type(old) is not int:
            unresolved.add(skill)
            notes.append(f"{skill}: Expertise needs an integer skill total to preserve independent adjustments. The listed total is unchanged; verify this skill's bonus on the character sheet.")
            continue
        bonus = old + (2 - rank) * pb
        row.update(skill=skill, bonus=bonus, proficiency="expertise", proficiency_multiplier=2, expertise=True,
                   expertise_source=source)
    return {"skills": [by_name[skill.casefold()] for skill in sorted(grants) if skill not in unresolved], "notes": notes,
            "handled_features": [source for source in handled if not source_skills[source] & unresolved]}
