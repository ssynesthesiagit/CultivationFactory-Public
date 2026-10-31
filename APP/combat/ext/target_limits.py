"""Per-target use limits (owner 2026-09-29: "i want everything we can automated"; BLOCKED_SYSTEMS.md).

"Use Limit: Once per creature per long rest" (Soul Sunder, Quivering Gate Strike), "Once per creature per short rest"
(Meridian-Cutting Strike, Meridian-Wrenching Lock), "Limit: Once per target per scene" (Hammer the Core Out of Rhythm, Essence
Rot), "Once per creature per scene" (Hold the Departing Soul).  Owner ruling 2026-09-29: a scene, day, week or rest limit is one
use per fight -- and a *per-creature* limit is one use per creature per fight.  The compiler used to read every one of them as
one use per fight for the whole ability, so a second foe could never be met with it.

How it is carried.  The compiler still gives the ability a "resource:uses.<ability>" cost (combat/factory_compiler.py
``_fight_limited``); for a per-target limit ``per_target_counters`` (called where the compiler finishes its resources) widens that
counter to ``PER_TARGET_USES``, so the counter itself never runs out and ``resource_maximums`` says which counters are per-target.
The limit is then kept here, in the fight's own state: a condition on the user ("condition:typed.target_uses") lists, for each
per-target counter, the creatures it has been used on.

- ``candidate_allowed``: a use aimed at a creature already on the list is not offered.
- ``technique_used``: a use that ran (hit or miss: the use is spent when it is made) puts its targets on the list.
  Using a per-creature limit **on yourself** counts: you are one of the creatures it is printed per, and an
  ally-or-self ability aimed at you is a chosen target, not a bystander.  A user who merely happens to stand
  inside their own area is not a chosen target, so an area use is not recorded against them.
- ``note_use(engine, actor, counter, subject, source)``: the same, for a plug-in whose limit is not an action's cost (a reaction or a
  passive trigger keyed by its own counter name).
- ``used_on(actor, counter, subject)``: whether the list already holds that creature.

A limit whose area names no single creature (an action that hits everyone in an area) is recorded but not gated, as nothing
printed says which of them the user "chose".

**Both printed word orders** (hunt 76).  The records disagree with themselves about where the creature goes:
"Once per creature per long rest" (Soul Sunder) and "Once per long rest per creature" (Kindle the Wounded Breath)
print the same limit.  ``PER_TARGET`` accepts either, so every record whose printed line names a creature or a
target hands this one model the same limit and none of them compiles down to one use for the whole fight.
"""

from __future__ import annotations

import re
from typing import Any

from . import hook

NAME = "target_uses"
PER_TARGET_USES = 99  # what a per-target counter starts at: enough that the count itself never stops a use
USES = "resource:uses."

# The printed limit, as combat/factory_compiler.py ``_fight_limited`` reads it (lower case, "text:" and underscores
# removed).  The creature may be named before the rest ("once per creature per long rest") or after it ("once per
# long rest per creature"): the two are the same printed limit, so both word orders are read here.  A limit that
# names no creature at all ("once per long rest", "once per item per scene") is not a per-creature limit and is
# left to the compiler's fight-wide counter.
_PER_CREATURE = r"(?:target|creature)"
_PER_WHEN = r"(?:scene|combat|fight|encounter|day|week|short rest|long rest)"
PER_TARGET = re.compile(rf"\bonce per (?:{_PER_CREATURE} per { _PER_WHEN }|{ _PER_WHEN } per { _PER_CREATURE })\b")

# Which rest the printed limit recharges on, for the reason the player is shown.  Anything a fight is shorter than
# (a scene, a day, a week) is reported as coming back after the fight, which is what it does.
RECHARGE = {"short rest": "a Short Rest", "long rest": "a Long Rest"}


def recharge_label(limit: str) -> str:
    """How long the printed limit lasts, in the words a player reads: "a Short Rest", "a Long Rest" or
    "the end of this fight"."""
    text = str(limit or "").lower().replace("_", " ")
    for printed, plain in RECHARGE.items():
        if printed in text:
            return plain
    return "the end of this fight"


_LIMIT_LINE = re.compile(r"^\s*(?:use )?limit\s*:\s*(.+)$", re.I | re.M)


def printed_limit(mechanic_id: str) -> str:
    """The "Use Limit:" line the owner printed for an ability, read from authority/typed_mechanics/rules_text.json
    (the same cached access combat/ext/alchemy_riders.py uses). The player's own sheet is what the reason quotes."""
    from ..factory_compiler import _rules_text

    found = _LIMIT_LINE.search(_rules_text().get(mechanic_id) or "")
    return found.group(1).strip() if found else ""


def recharge_for(counter: str) -> str:
    """When the printed limit behind ``counter`` comes back, in the words a player reads."""
    return recharge_label(printed_limit(mechanic_key(counter)))


def condition_id() -> str:
    from ..typed_executor import CONDITION_PREFIX

    return CONDITION_PREFIX + NAME


def per_target_limit(mechanic: dict[str, Any]) -> bool:
    limit = str(mechanic.get("use_limit") or "").lower().removeprefix("text:").replace("_", " ")
    return bool(PER_TARGET.search(limit))


def mechanic_key(resource_id: str) -> str:
    """The ability a use counter belongs to: "resource:uses.<key>" (a modifier's) or "resource:uses.action:typed.<short>.<key>"."""
    rest = resource_id.removeprefix(USES)
    return rest.split(".", 2)[2] if rest.startswith("action:typed.") and rest.count(".") >= 2 else rest


def per_target_counters(resources: list[Any], mechanics: dict[str, Any]) -> list[Any]:
    """The compiled resources with each per-target limit's use counter widened (the compiler calls this last)."""
    from ..gate2_runtime_models import ResourceDefinition

    out = []
    for row in resources:
        if row.resource_id.startswith(USES) and per_target_limit(mechanics.get(mechanic_key(row.resource_id)) or {}):
            row = ResourceDefinition(resource_id=row.resource_id, initial=PER_TARGET_USES, maximum=PER_TARGET_USES)
        out.append(row)
    return out


def is_per_target(actor: Any, resource_id: str) -> bool:
    return resource_id.startswith(USES) and int(actor.resource_maximums.get(resource_id) or 0) == PER_TARGET_USES


def _ledger(actor: Any) -> tuple[str | None, dict[str, list[str]]]:
    for iid, condition in actor.conditions.items():
        if condition.condition_id == condition_id():
            return iid, {key: list(value) for key, value in ((condition.data or {}).get("used") or {}).items()}
    return None, {}


def used_on(actor: Any, counter: str, subject: Any) -> bool:
    return getattr(subject, "entity_id", subject) in _ledger(actor)[1].get(counter, [])


def _label(engine: Any, used: dict[str, list[str]], names: dict[str, str]) -> str:
    """The plain sentence the player's sheet shows for a recorded use.

    Each recorded use is described in its own sentence, naming the creature, the ability **and that ability's own**
    recharge: two abilities with different printed limits (Kindle the Wounded Breath's Short Rest, Soul Sunder's
    Long Rest) must not be explained by one shared rest, so the recharge is read per counter.  ``mechanic_key``
    (an ability id) is deliberately *not* the fallback for the ability's name: a missing display name is left out
    rather than shown as an id.
    """
    parts = []
    for counter, ids in used.items():
        who = ", ".join(engine.state.actors[i].display_name if i in engine.state.actors else i for i in ids)
        ability = names.get(counter)
        said = f"Already used on {who}"
        if ability:
            said += f" with {ability}"
        parts.append(f"{said}; comes back after {recharge_for(counter)}.")
    return " ".join(parts)


def note_use(engine: Any, actor: Any, counter: str, subject: Any, source: str, name: str | None = None) -> None:
    """Put ``subject`` on the list of creatures ``counter`` has been used on (state changes only through the engine's evented calls)."""
    subject_id = getattr(subject, "entity_id", subject)
    iid, used = _ledger(actor)
    if subject_id in used.get(counter, []):
        return
    used[counter] = [*used.get(counter, []), subject_id]
    names = {**(next((c.data or {} for c in actor.conditions.values() if c.condition_id == condition_id()), {}).get("names") or {}),
             **({counter: name} if name else {})}
    if iid is not None:
        del actor.conditions[iid]
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition_id(), "instance_id": iid})
    engine._apply_condition(actor, condition_id(), source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"used": used, "names": names, "label": _label(engine, used, names)})


def _counters(actor: Any, action: Any) -> list[str]:
    return [resource for resource, _amount in getattr(action, "costs", ()) or () if is_per_target(actor, resource)]


@hook("candidate_allowed")
def not_twice_on_one_creature(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    counters = _counters(actor, action)
    if not counters or not getattr(candidate, "target_ids", None):
        return None
    return not any(used_on(actor, counter, target_id) for counter in counters for target_id in candidate.target_ids)


def _subjects(ctx: Any) -> list[Any]:
    """The creatures this use was actually made on, for the ledger.

    You are one of them whenever the use was aimed at you, because a printed "once per creature" is spent on you
    just as it is spent on anyone else:

    * an **ally-or-self** ability whose candidate you chose yourself -- combat/typed_executor.py keeps an
      explicitly selected self recipient on those, so you are a real target here (Kindle the Wounded Breath);
    * a **self-only** ability, where you are the only creature it can ever be used on.

    An **area** is different: it names no single creature, and standing inside your own cone or sphere is not
    choosing yourself, so the user is not recorded against it (unchanged behaviour).
    """
    chosen = list(ctx.targets or ([ctx.target] if ctx.target is not None else []))
    area = ((getattr(ctx, "typed", None) or {}).get("area") or {})
    if area.get("size_ft"):
        return [subject for subject in chosen if subject is not ctx.actor]
    if ctx.actor in chosen or str(getattr(ctx.action, "target_kind", "")) == "SELF":
        return chosen or [ctx.actor]
    return chosen


@hook("technique_used")
def spent_on_these_creatures(ctx: Any) -> None:
    counters = _counters(ctx.actor, ctx.action)
    for counter in counters:
        for subject in _subjects(ctx):
            if subject is not None:
                note_use(ctx.engine, ctx.actor, counter, subject, ctx.source, ctx.action.display_name)
