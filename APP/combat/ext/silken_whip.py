"""Silken Whip (Iron Cloth Cultivator CL3, auto/lane2 2026-09-29).

"Infuse Cloth -- Bonus Action, 1 Qi, 1 hour: the selected cloth becomes a Silken Whip. You may maintain one Silken Whip at a
time." and the profile: "Reach: 15 feet; Damage: 1d8 Bludgeoning, Slashing, or Force; Ability: Qi Cultivation key ability;
Attack Modifier: Cultivation Attack Modifier; Properties: Finesse. You are proficient with your Silken Whip. Its attacks are
Qi-powered."

- The override (authority/typed_mechanics/reviewed_final.d/auto_lane2.json) types "Infuse Cloth" as a condition on the user,
  "condition:typed.silken_whip" (until removed: an hour outlasts any fight).
- ``compile_actions`` adds the whip's attack: an Action, reach 15 feet, a Cultivation Attack (the Cultivation Attack Modifier)
  for 1d8 + the key ability modifier; the player chooses a printed damage type before each attack. Automatic choices use the first printed type, without inspecting hidden defenses.
- ``candidate_allowed``: Infuse Cloth is offered while no whip is up (one at a time); the attack only while one is.

Not run: the choice of which cloth (nothing on the table), the "Flexible" weapon group's own talents, and binding the whip as
the Domain Armament at CL9 (Domain Armament, combat/ext/qi_path.py, stays the projected one).
"""

from __future__ import annotations

from typing import Any

from . import hook

SILKEN = "tianxia.subpath.qi.iron_cloth_cultivator.feature.silken_whip"
WHIP = "condition:typed.silken_whip"
ATTACK = "silken_whip.attack"


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def has_whip(actor: Any) -> bool:
    return any(c.condition_id == WHIP for c in actor.conditions.values())


@hook("compile_actions")
def whip_attack(info: dict[str, Any]) -> list[Any] | None:
    if SILKEN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = info["numbers"]
    damage = {"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "formula": "key_ability_modifier",
              "damage_types": ["bludgeoning", "slashing", "force"], "evidence": "Damage: 1d8 Bludgeoning, Slashing, or Force; Ability: Qi Cultivation key ability"}
    typed = {"effects": [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": [damage], "on_miss": [],
                          "evidence": "Silken Whip attack: Cultivation Attack Modifier, reach 15 feet"}],
             "numbers": numbers, "duration": {"kind": "instant"}, "range_ft": 15, "riders": [], "source": ATTACK}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.silken_whip.attack", display_name="Silken Whip Attack",
                             owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                             range_ft=15, parameters={"typed": typed, "expected_damage": int(4.5 + int(numbers.get("key_mod") or 0))})]


@hook("candidate_allowed")
def whip_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = _typed(action).get("source") if action is not None else None
    if source == ATTACK:
        return has_whip(actor)
    if source == SILKEN:
        return not has_whip(actor)  # "You may maintain one Silken Whip at a time"
    return None


@hook('attack_damage_type_choice')
def whip_damage_choice(ctx,attack,target,kinds,attack_index):
    if ctx.typed.get('source') != ATTACK:return None
    from .needle import ask,checkpoint_id
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'silken_whip_type',str(attack_index)),ctx.actor,
                 'choice:needle.silken_whip_type',kinds,minimum=1,maximum=1,preferred=kinds[:1],
                 labels={k:k.title()+' damage' for k in kinds},prompt='Silken Whip: choose the damage type for this attack')
    return selected[0]
