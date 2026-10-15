"""Daemonic Cultivation Insights (OPUS1 batch 4).

Demon-Slaying Demon   when the owner damages a fiend, demon, possessed creature, demonic beast, inner demon manifestation or
                      creature using Daemonic Cultivation: once per turn, Proficiency Bonus is added to that damage roll
                      (an attack's packet through confirmed_hit_roll_bonus, so fixed unarmed damage counts too; a typed
                      damage row through deal_bonus, only for qualifying recipients of that roll); when such
                      a creature drops to 0 Hit Points from the owner's damage (fresh_zero_hp), the owner chooses: lose 1
                      Corruption or gain 2 Devoured Essence (only the options its pools allow).

Who qualifies is read from printed creature labels (creature_kinds.matches: Fiend, Demon, Demonic Beast, Inner Demon,
Possessed, Possessing) or from the creature's own compiled Daemonic Cultivation actions; nothing is inferred from a name.
The row is sealed into block ``daemonic_insights`` (kind = Insight id); every hook returns at once without it.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

BLOCK = "daemonic_insights"
DEMON_SLAYING = "insight.demon-slaying-demon"
DAEMONIC = "tianxia.sphere.daemonic_cultivation"
ESSENCE = "resource:named.devoured_essence"
CORRUPTION = "resource:named.corruption"
KINDS = ("fiend", "demon", "demonic beast", "inner demon", "inner demon manifestation", "possessed", "possessing")
TURN_FLAG = "daemonic_insights:demon_slaying"
OUTCOMES = {
    DEMON_SLAYING: "Once per turn, add your Proficiency Bonus to one damage roll against a fiend, demon, possessed creature, "
                   "demonic beast, inner demon or Daemonic cultivator; when one drops to 0 Hit Points from your damage, lose 1 "
                   "Corruption or gain 2 Devoured Essence",
}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"])}]


def demonic(engine: Any, creature: Any) -> bool:
    """A fiend, demon, possessed creature, demonic beast, inner demon, or a creature that uses Daemonic Cultivation."""
    from .creature_kinds import matches

    if creature is None:
        return False
    if matches(creature, KINDS):
        return True
    return any(action.owner_id == creature.entity_id
               and (((action.parameters or {}).get("typed") or {}).get("sphere") == DAEMONIC)
               for action in (getattr(engine, "action_catalog", None) or {}).values())


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _bonus(engine: Any, owner: Any, target: Any) -> int | None:
    row = row_of(engine, owner.entity_id, BLOCK, DEMON_SLAYING)
    if row is None or owner.turn_flags.get(TURN_FLAG) == _stamp(engine):
        return None
    if target is None or target.team_id == owner.team_id or not demonic(engine, target):
        return None
    owner.turn_flags[TURN_FLAG] = _stamp(engine)
    note(engine, f"passive:{DEMON_SLAYING}", owner,
         f"Demon-Slaying Demon: {owner.display_name} adds {row['pb']} to this damage roll against "
         f"{target.display_name} (Proficiency Bonus, once per turn).", (target,))
    return int(row["pb"])


@hook("confirmed_hit_roll_bonus")
def demon_slaying_hit(engine: Any, attacker: Any, target: Any, spec: Any, intent: Any, source: Any) -> int | None:
    """An attack's own damage, fixed or rolled, after the hit is confirmed (misses never ask)."""
    return _bonus(engine, attacker, target)


@hook("damage_roll_resolved")
def demon_slaying_roll(ctx: Any, effect: Any, key: Any) -> None:
    """Track the executor's roll identity, including cached save-for-half deliveries."""
    if row_of(ctx.engine, ctx.actor.entity_id, BLOCK, DEMON_SLAYING) is not None:
        ctx.damage_cache["_demon_slaying_roll"] = key


@hook("effect_resolution_scope")
def demon_slaying_scope(ctx: Any, effect: Any) -> Any:
    """Nested effects cannot borrow the enclosing damage row's eligible roll."""
    if row_of(ctx.engine, ctx.actor.entity_id, BLOCK, DEMON_SLAYING) is None:
        return None
    from contextlib import contextmanager

    @contextmanager
    def scope():
        previous = ctx.damage_cache.pop("_demon_slaying_roll", None)
        try:
            yield
        finally:
            ctx.damage_cache.pop("_demon_slaying_roll", None)
            if previous is not None:
                ctx.damage_cache["_demon_slaying_roll"] = previous
    return scope()


@hook("deal_bonus")
def demon_slaying_damage(ctx: Any, subject: Any, amount: int) -> int | None:
    """Boost qualifying recipients of one roll before save division; other creatures keep the base amount."""
    if row_of(ctx.engine, ctx.actor.entity_id, BLOCK, DEMON_SLAYING) is None:
        return None
    if amount <= 0 or subject.team_id == ctx.actor.team_id or not demonic(ctx.engine, subject):
        return None
    key = ctx.damage_cache.get("_demon_slaying_roll")
    boosted = ctx.damage_cache.get("_demon_slaying_boosted", {})
    if key is not None and key in boosted:
        return int(boosted[key])
    bonus = _bonus(ctx.engine, ctx.actor, subject)
    if bonus and key is not None:
        ctx.damage_cache.setdefault("_demon_slaying_boosted", {})[key] = bonus
    return bonus


@hook("fresh_zero_hp")
def demon_slaying_feast(engine: Any, target: Any, attacker_id: Any, source_id: Any) -> None:
    owner = engine.state.actors.get(str(attacker_id or ""))
    if owner is None or not owner.active or row_of(engine, owner.entity_id, BLOCK, DEMON_SLAYING) is None:
        return
    if target.team_id == owner.team_id or not demonic(engine, target):
        return
    options = []
    if int(owner.resources.get(CORRUPTION, 0)) > 0:
        options.append("corruption")
    if ESSENCE in owner.resources and int(owner.resources[ESSENCE]) < int(owner.resource_maximums.get(ESSENCE, 10 ** 6)):
        options.append("essence")
    if not options:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, DEMON_SLAYING, target.entity_id), owner,
                 "choice:needle.daemonic_insights", options, name="Demon-Slaying Demon", feature_id=DEMON_SLAYING,
                 target_id=target.entity_id, labels={"corruption": "Reduce your Corruption by 1",
                                                     "essence": "Gain 2 Devoured Essence"},
                 prompt=(f"Demon-Slaying Demon: {target.display_name} dropped to 0 Hit Points from your damage. Choose one: "
                         f"reduce your Corruption by 1, or gain 2 Devoured Essence. No action or cost."))
    choice = (picked or options)[0]
    if choice == "corruption":
        engine._spend_resource(owner, CORRUPTION, 1, DEMON_SLAYING)
        note(engine, f"passive:{DEMON_SLAYING}", owner, f"Demon-Slaying Demon: {owner.display_name} loses 1 Corruption.")
    else:
        engine._gain_resource(owner, ESSENCE, 2, DEMON_SLAYING)
        note(engine, f"passive:{DEMON_SLAYING}", owner, f"Demon-Slaying Demon: {owner.display_name} gains 2 Devoured Essence.")
