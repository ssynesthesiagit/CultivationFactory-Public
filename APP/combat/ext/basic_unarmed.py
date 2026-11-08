"""Shared damaging Unarmed Strike, compiled before basic-action modifiers and weapon delivery.

Returns no additions when an owned, free, unrestricted strike already deals at least as much.
Attack counts and passive riders come from the compiler seam; this module owns only this option.
"""

from __future__ import annotations

import copy
from typing import Any

from . import hook
from ..gate2_runtime_models import ActionDefinition, EconomyKind


def strike_payload(numbers, pb, mods, count, on_hit):
    """Shared damaging Unarmed Strike packet for ordinary attacks and Athletics' bonus strike.

    Keep ability damage, proficiency and compiled unarmed hit riders together.
    Callers choose their own economy and attack count; this grants no action.
    """
    from ..factory_compiler import unarmed_strike_weapon

    strength = mods.get("STR", 0)
    return {"effects": [{"type": "attack", "attack_kind": "unarmed", "count": count,
                         "on_hit": [{"type": "damage", "weapon_damage": True}, *copy.deepcopy(on_hit)]}],
            "numbers": {**numbers, "attack_bonus": pb + strength}, "weapon": unarmed_strike_weapon(strength),
            "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": "unarmed_strike"}


@hook("compile_basic_actions")
def compile_basic_actions(info: dict[str, Any]) -> list[ActionDefinition]:
    """Add the missing Damage option without changing creatures with a better basic strike."""
    from ..factory_compiler import unarmed_strike_weapon

    profile = info["attack_profiles"]["unarmed"]
    return _basic_unarmed_strike(info["actions"], info["short"], info["actor_id"], info["numbers"],
                                info["pb"], info["mods"], info["attack_count"], profile["on_hit"],
                                profile["expected_extra_damage"], unarmed_strike_weapon)


def _plain_unarmed_attack(action: ActionDefinition, actor_id: str) -> bool:
    """An unarmed attack the fighter can always make with the Attack action: its own, free, unconditional and damaging --
    a natural weapon's or the Iron Fist sphere's strike. A paid or special technique delivered as an unarmed strike (Empty
    Palm Scripture, Batter), a modifier's variant or a reaction does not take the basic Unarmed Strike's place."""
    typed = (action.parameters or {}).get("typed") or {}
    if (action.owner_id != actor_id or action.economy != EconomyKind.ACTION or action.costs or "#" in action.source_definition_id
            or not typed.get("attack_action") or not typed.get("weapon") or typed.get("modifier") or typed.get("variant_of")
            or any("requires_" in str(key) or str(key).startswith("blocked_by_")
                   for mapping in (action.parameters or {}, typed) for key in mapping)):
        return False
    return any(isinstance(effect, dict) and effect.get("type") == "attack" and effect.get("attack_kind") == "unarmed"
               and any(isinstance(hit, dict) and hit.get("type") == "damage" and hit.get("weapon_damage") for hit in effect.get("on_hit") or [])
               for effect in typed.get("effects") or [])


def _basic_unarmed_strike(actions: list[ActionDefinition], short: str, actor_id: str, numbers: dict[str, int], pb: int,
                          mods: dict[str, int], attacks: int, extra_hits: list[dict[str, Any]], extra_average: int, weapon_payload: Any) -> list[ActionDefinition]:
    """Hunt 53: the 2024 Unarmed Strike's Damage option, which every creature has -- an attack (proficient, Strength) that
    deals 1 + Strength modifier Bludgeoning damage, one per attack of the Attack action, with the on-hit passives that ride
    unarmed strikes. Its Grapple and Shove options are ``_unarmed_options``. Not added when a plain unarmed attack
    (``_plain_unarmed_attack``: a natural weapon, Iron Fist) already deals at least as much: that attack is how the fighter
    strikes unarmed. Named ``.natural.`` so the talents that change "your Unarmed Strike" (``_core_modifier_pass``) and the
    special unarmed attacks (``_bind_unarmed_strikes``) use it like a natural weapon's attack."""
    strength = mods.get("STR", 0)
    expected = attacks * max(0, 1 + strength) + extra_average
    if any(_plain_unarmed_attack(row, actor_id) and int(row.parameters.get("expected_damage") or 0) >= expected for row in actions):
        return []
    typed = {**strike_payload(numbers, pb, mods, attacks, extra_hits), "attack_action": True}
    return [ActionDefinition(source_definition_id=f"action:typed.{short}.natural.unarmed_strike", display_name="Unarmed Strike",
                             owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                             range_ft=5, parameters={"typed": typed, "expected_damage": expected})]
