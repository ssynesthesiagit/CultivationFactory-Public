"""Physician's Pulse's diagnosis (the Blood sphere's examination).

Physician's Pulse (Action, Touch, 1 CP) prints: "Examine one willing living creature.
Learn whether it is affected by: ordinary bleeding; poison; disease; internal injury;
unusual blood loss; foreign bloodline contamination; ordinary exhaustion; one obvious
bodily curse or transformation." Every one of those lines was a GM rider, so the button
examined nobody and printed a reminder.

This answers the printed categories the table actually keeps state for, by reading the
examined creature's live conditions, and says plainly which ones it found (and that it
found none when it found none):

    ordinary bleeding      a Bleeding condition
    poison                 a Poisoned condition
    disease                a Sickened condition (the Disease sphere's own printed ailment)
    ordinary exhaustion    an Exhaustion condition, with its level

Nothing here removes anything: the printed "Physician's Pulse provides diagnosis, not
automatic removal" is a limitation the table enforces, so it is the ability's description
and not a GM reminder.

The four printed categories the table has no state for -- internal injury, unusual blood loss,
foreign bloodline contamination, and an obvious bodily curse or transformation -- stay an honest
GM line: nothing in combat/rules/typed_conditions.json tracks any of them, so inventing a match
would be reporting a diagnosis the engine cannot support. Ordinary Bleeding is not unusual blood
loss; only a tracker for the latter would be. Coagulate, Blood Mending and the rest of the Blood
sphere still end Bleeding on their own.

Inert for anyone without the talent: the effect only runs from this talent's own typed row.
"""

from __future__ import annotations

from typing import Any

from . import effect, note

# The printed category, the condition names that answer it, and the words the player reads.
CATEGORIES = (
    ("ordinary bleeding", ("bleeding",), "ordinary bleeding"),
    ("poison", ("poisoned",), "poison"),
    ("disease", ("sickened",), "disease"),
    ("ordinary exhaustion", ("exhaustion",), "exhaustion"),
)


def _named(creature: Any) -> set[str]:
    """Every condition name the creature carries, read through the engine's own condition names."""
    from ..condition_names import condition_key

    return {condition_key(condition.condition_id) for condition in creature.conditions.values()}


def findings(creature: Any) -> list[str]:
    """The printed categories this creature is affected by, in the printed order."""
    from .forged_exhaustion import level as exhaustion_level

    names = _named(creature)
    found = []
    for _category, keys, label in CATEGORIES:
        if not names & set(keys):
            continue
        found.append(f"{label} (level {exhaustion_level(creature)})" if keys[0] == "exhaustion" else label)
    return found


@effect("diagnosis")
def diagnosis(ctx: Any, eff: dict[str, Any]) -> None:
    """"Examine one willing living creature. Learn whether it is affected by: ..." -- one readable line naming what
    the table can see on it. It never removes or changes anything."""
    target = ctx.target if ctx.target is not None else (list(ctx.targets) or [None])[0]
    if target is None or not target.active:
        return
    found = findings(target)
    body = ", ".join(found) if found else "none of the ailments this examination can see"
    note(ctx.engine, ctx.source, ctx.actor,
         f"Physician's Pulse: your examination of {target.display_name} shows {body}.",
         targets=(target,), diagnosis=found)