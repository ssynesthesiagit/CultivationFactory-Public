"""Mass Tame and Lookout (Beastmastery, Tamer; rider lane C10, 2026-09-30).

Owner text (authority/typed_mechanics/rules_text.json):
  Mass Tame -- "When using Beast Tamer, target creatures up to your Proficiency Bonus within range. Each target saves separately.
    Your Tamer capacity still applies."
  Lookout -- "While within 30 feet of your Beast Allies, you and those allies use the highest Passive Perception score among the
    group."

How it runs
  * Mass Tame: the owner's Beast Tamer action (compile_action) wraps its save in the shared ``extra_targets`` effect
    (combat/ext/extra_targets.py): the aimed creature and up to Proficiency Bonus - 1 more hostile creatures within Beast Tamer's
    30 feet, picked by the player (bounded choice), each making its own Charisma save; the harm-ends-it rule
    (beastmastery_riders.py) binds each one. "Your Tamer capacity still applies" stays with the GM (the table does not count
    temporary Tame Creatures).
  * Lookout (feature block "beastmastery_tamer", kind "lookout"): the owner and its Beast Allies on the map (its tamed beasts and its
    mount, summons.py "tamer" / "rider") that are within 30 feet of it share the highest passive Perception among them
    (``passive_perception_override``, read by Hidden Eye Assassinate and traps). Members' scores are their own baselines (10 +
    Perception, + passive bonuses), so the override never feeds on itself.
"""

from __future__ import annotations

import copy
from typing import Any

from . import hook

MASS_TAME = "TAL_BEASTMASTERY_MASS_TAME"
BEAST_TAMER = "TAL_BEASTMASTERY_BEAST_TAMER"
ENDURING = "TAL_BEASTMASTERY_ENDURING_CONTROL"
BLOCK = "beastmastery_tamer"
ALLY_SOURCES = ("tamer", "rider")


@hook("compile_action")
def tamer_reviewed_fields(action: Any, info: dict[str, Any]) -> Any | None:
    """Apply reviewed duration and non-Beast save data to new Beast Tamer packets.

    Historical sealed packets have no new save flag and retain their old path.
    Enduring Control changes the native counted clock, including the exact
    harm-ending ledger; it does not change command authority or Tamer capacity.
    """
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get('source') != BEAST_TAMER:
        return None
    updated = dict(typed)
    mechanics = info.get('mechanics') or {}
    if ENDURING in (info.get('owned_ids') or []):
        duration = (mechanics.get(ENDURING, {}).get('modifier') or {}).get('duration')
        if duration:
            updated['duration'] = copy.deepcopy(duration)
    for row in mechanics.get(BEAST_TAMER, {}).get('effects') or []:
        if row.get('type') == 'save' and row.get('nonbeast_bonus'):
            updated['beast_tamer_nonbeast_bonus'] = int(row['nonbeast_bonus'])
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': updated}}) if updated != typed else None


@hook('save')
def nonbeast_tamer_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Printed +2 only for an explicitly classified non-Beast on new packets."""
    bonus = ctx.typed.get('beast_tamer_nonbeast_bonus')
    if not bonus or ability != 'CHA' or ctx.typed.get('source') != BEAST_TAMER:
        return None
    from ..creature_types import types_for
    from .creature_kinds import matches
    if types_for(subject) and not matches(subject, ['beast']):
        return {'bonus': int(bonus)}
    return None


@hook("compile_action")
def mass_tame(action: Any, info: dict[str, Any]) -> Any | None:
    typed = (action.parameters or {}).get("typed") or {}
    if MASS_TAME not in (info.get("owned_ids") or []) or typed.get("source") != BEAST_TAMER or typed.get("mass_tame"):
        return None
    wrapped = {"type": "extra_targets", "count": "pb", "who": "hostile", "sight": False, "range_ft": int(action.range_ft or 30),
               "evidence": "When using Beast Tamer, target creatures up to your Proficiency Bonus within range. Each target saves separately.",
               "effects": copy.deepcopy(typed.get("effects") or [])}
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "effects": [wrapped], "mass_tame": True}}})


@hook("compile_block")
def tamer_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}] if block == BLOCK else None


def _baseline(engine: Any, creature: Any) -> int:
    from . import run
    from ..ability_checks import ability_modifier
    from .eye_common import skill

    return 10 + skill(engine, creature, "Perception", ability_modifier(creature, "WIS")) + sum(
        int(value) for value in run("passive_perception", engine, creature) if isinstance(value, int))


def _group(engine: Any, owner: Any) -> list[Any]:
    """The Lookout owner and its Beast Allies within 30 feet of it."""
    beasts = [other for other in engine.state.actors.values() if other.active and other.summon
              and other.summon.get("owner") == owner.entity_id and other.summon.get("source") in ALLY_SOURCES
              and other.summon.get("status", "present") == "present" and engine._distance_actor_to_actor(owner, other) <= 30]
    return [owner, *beasts] if beasts else []


@hook("passive_perception_override")
def lookout(engine: Any, creature: Any, observed: Any, baseline: int) -> int | None:
    from .passive_rows import row_of

    owner = creature
    if creature.summon and creature.summon.get("source") in ALLY_SOURCES:
        owner = engine.state.actors.get(str(creature.summon.get("owner") or ""))
    if owner is None or not owner.active or row_of(engine, owner.entity_id, BLOCK, "lookout") is None:
        return None
    group = _group(engine, owner)
    if creature not in group:
        return None
    best = max(_baseline(engine, member) for member in group)
    return best if best > baseline else None


@hook("attack_mode")
def pack_attack(ctx: Any, target: Any) -> str | None:
    """Pack Attack: another conscious Beast Ally threatens the attacked creature.

    Ownership uses the existing Tamer/Rider summon provenance, including bonded
    beasts represented as Beast Allies. The attacker cannot provide its own
    assistance. Unrelated summons and ordinary allies do not qualify.
    """
    from .passive_rows import row_of
    from .needle import incapacitated

    beast = ctx.actor
    if not beast.summon or beast.summon.get("source") not in ALLY_SOURCES:
        return None
    owner = ctx.engine.state.actors.get(str(beast.summon.get("owner") or ""))
    if owner is None or row_of(ctx.engine, owner.entity_id, BLOCK, "pack_attack") is None:
        return None
    for partner in ctx.engine.state.actors.values():
        if (partner.entity_id != beast.entity_id and partner.active and partner.team_id == beast.team_id
                and partner.summon
                and partner.summon.get("source") in ALLY_SOURCES
                and partner.summon.get("status", "present") == "present"
                and not incapacitated(partner)
                and ctx.engine._distance_actor_to_actor(partner, target) <= 5):
            return "ADVANTAGE"
    return None
