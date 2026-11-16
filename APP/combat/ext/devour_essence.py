"""Daemonic Cultivation: Devour Essence (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until its
only the non-combat ones left"). Printed (Sphere Compendium, Daemonic Cultivation):

  "Timing Detail: Bonus Action or Reaction. Range: 30 feet. Use Devour Essence when one of the following happens within range: a hostile
  creature is reduced to 0 HP; a creature fails a saving throw against one of your Daemonic talents; you score a Critical Hit; a creature
  bearing your demonic mark takes damage; an ongoing summoned, possessed, spirit, fiendish, undead, or demonic effect ends. Gain 1 Devoured
  Essence. You can use Devour Essence once per round. If the triggering creature is at least your Realm or has a CR/level equal to at
  least half your CL, you may instead gain 2 Devoured Essence, but you also gain 1 Corruption."

The generic reaction row used to answer only the first trigger and always spent the Reaction. This module owns the whole ability (its
typed entry keeps no effects, so no generic row is compiled): each of the first four moments, within 30 feet of the owner, offers it once
per round -- on the owner's own turn it spends the Bonus Action (the Reaction when the Bonus Action is gone), off its turn the Reaction.
The owner is asked (the built-in AI always takes it). When the triggering creature is a compiled character whose Cultivation Level is in
your Realm or above, or at least half your CL, the choice adds "2 Devoured Essence and 1 Corruption" (a creature without a known level is
the GM's). The ending of a summoned/possessed/spirit effect is the GM's.

Ownership: the compiled feature row (block ``devour_essence``, combat/rules/feature_blocks.d/riders_c13.json). Inert without it.
Hooks: compile_block, event (damage), attack_result (critical hits), after_save_resolved (failed saves). None added to the framework.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import hook, note

BLOCK = "devour_essence"
FEATURE = "TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE"
ESSENCE = "resource:named.devoured_essence"
CORRUPTION = "resource:named.corruption"
DAEMONIC = "tianxia.sphere.daemonic_cultivation"
REACH_FT = 30
_REALMS = ((1, 4), (5, 9), (10, 14), (15, 19), (20, 20))   # core rules 1.2


@hook("compile_block")
def devour_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "cl": int(numbers.get("cl") or 1)}]


def _row(engine: Any, actor: Any) -> dict[str, Any] | None:
    return next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("block") == BLOCK), None)


def _realm(cl: int) -> int:
    return next((index for index, (low, high) in enumerate(_REALMS) if low <= cl <= high), len(_REALMS) - 1)


def _economy(engine: Any, owner: Any) -> str | None:
    from ..typed_executor import condition_rules

    rules = condition_rules(owner)
    if not owner.active or any(rule.get("no_actions") for rule in rules):
        return None
    if engine.state.current_actor_id == owner.entity_id and owner.bonus_action_available:
        return "bonus"
    if owner.reaction_available and not any(rule.get("no_reactions") for rule in rules):
        return "reaction"
    return None


def offer(engine: Any, owner: Any, creature: Any, why: str) -> None:
    """One trigger seen by the owner of Devour Essence: once per round, within 30 feet, asked."""
    row = _row(engine, owner)
    if row is None or creature is None or owner.turn_flags.get("_round_devour_essence") == engine.state.round_number:
        return
    if creature.entity_id != owner.entity_id and engine.grid.distance_ft(owner.position, creature.position) > REACH_FT:
        return
    economy = _economy(engine, owner)
    if economy is None or ESSENCE not in owner.resources:
        return
    from .passive_rows import known_level
    from .rider_choices import pick

    cl = int(row.get("cl") or 1)
    level = known_level(engine, creature) if creature.entity_id != owner.entity_id else None
    big = level is not None and (_realm(level) >= _realm(cl) or 2 * level >= cl) and CORRUPTION in owner.resources
    cost = "your Bonus Action" if economy == "bonus" else "your Reaction"
    labels = {"one": f"Gain 1 Devoured Essence ({cost})"}
    if big:
        labels["two"] = f"Gain 2 Devoured Essence and 1 Corruption ({cost}; {creature.display_name} is a match for your Realm)"
    chosen = pick(engine, owner, "devour_essence", "Devour Essence", list(labels), subject=creature, labels=labels, preferred=["one"],
                  trigger=why)
    if not chosen:
        return
    with activation(engine, owner, FEATURE):
        owner.turn_flags["_round_devour_essence"] = engine.state.round_number
        if economy == "bonus":
            owner.bonus_action_available = False
        else:
            owner.reaction_available = False
        gained = 2 if chosen[0] == "two" else 1
        engine._gain_resource(owner, ESSENCE, gained, FEATURE)
        if gained == 2:
            engine._gain_resource(owner, CORRUPTION, 1, FEATURE)
        note(engine, FEATURE, owner, f"Devour Essence ({'Bonus Action' if economy == 'bonus' else 'Reaction'}): {owner.display_name} gains "
                                     f"{gained} Devoured Essence{' and 1 Corruption' if gained == 2 else ''} -- {why}.", (creature,))


def _owners(engine: Any) -> list[Any]:
    return [actor for actor in engine.state.actors.values() if actor.active and _row(engine, actor) is not None]


@hook("event", nested=True)
def damage_seen(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    owners = _owners(engine)
    if not owners:
        return
    payload = kwargs.get("payload") or {}
    from ..typed_executor import bears_mark

    for target_id in kwargs.get("target_ids") or ():
        creature = engine.state.actors.get(target_id)
        if creature is None:
            continue
        for owner in owners:
            if creature.team_id != owner.team_id and int(payload.get("remaining_hp", 1) or 0) <= 0 and int(payload.get("hp_damage") or 0) > 0:
                offer(engine, owner, creature, f"{creature.display_name} is reduced to 0 HP")
            elif int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) > 0 and creature.active \
                    and bears_mark(creature, owner.entity_id, "Demon Mark"):
                offer(engine, owner, creature, f"{creature.display_name}, bearing your Demon Mark, takes damage")


@hook("attack_result")
def critical_seen(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    if critical and hit and _row(ctx.engine, ctx.actor) is not None:
        offer(ctx.engine, ctx.actor, target, f"you score a Critical Hit against {target.display_name}")


@hook("after_save_resolved")
def failed_save_seen(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if failed and subject is not None and (ctx.typed or {}).get("sphere") == DAEMONIC and _row(ctx.engine, ctx.actor) is not None:
        offer(ctx.engine, ctx.actor, subject, f"{subject.display_name} fails a saving throw against your {ctx.action.display_name}")
