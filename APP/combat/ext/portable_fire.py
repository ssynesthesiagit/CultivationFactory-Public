"""Portable Fire attack bonuses, consumed by character_runtime_adapter's
character_damage_amount seam. Burning Weapon and Combustive Step contribute to
one primary attack packet; area activations and unowned fighters are untouched.
The portable action catalog still owns these two actions' activation/state.
"""
from __future__ import annotations

from typing import Any

from . import hook


@hook("character_damage_amount")
def attack_bonuses(amount: int, engine: Any, actor: Any, target: Any, source: str, intent: Any,
                   context: dict[str, Any]) -> int | None:
    if not context.get("attack"):
        return None
    burning = "action:fire.burning_weapon"
    step = "action:fire.combustive_step"
    if actor.concentration and actor.concentration.source_definition_id == burning:
        from ..gate2_runtime_models import DiceSpec

        engine._claim_once_per_turn(actor, burning)
        bonus = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=actor.entity_id,
                                   reason="BURNING_WEAPON_DAMAGE")
        engine._record_roll(bonus)
        amount += bonus.total
        engine._append_event("PASSIVE_TRIGGERED", burning, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                             payload={"added_fire_damage": bonus.total})
    combustive = next((row for row in actor.modifiers.values() if row.source_definition_id == step
                       and row.target_field == "next_qualifying_attack_damage"), None)
    if combustive is not None:
        amount += actor.proficiency_bonus
        actor.modifiers.pop(combustive.modifier_id, None)
        engine._append_event("MODIFIER_REMOVED", step, actor_id=actor.entity_id,
                             payload={"modifier_id": combustive.modifier_id, "reason": "CONSUMED"})
    return amount
