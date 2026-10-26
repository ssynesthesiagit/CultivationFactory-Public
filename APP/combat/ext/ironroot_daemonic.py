"""Lingfeng Ironroot: Daemonic Cultivation mechanics that need a hook instead of an ordinary typed effect
(worker ironroot, 2026-09-28).

Demon Bone Regeneration ("While Demon Seed is active, at the start of your turn, you may spend 1 Devoured
Essence. Regain HP equal to 1d8 + your Daemonic key ability modifier.") has no start-of-turn action economy in
this system -- it is an optional choice at a fixed timing point. The transactional turn_start_choice hook
asks manual owners before any payment or healing, even when another actor's AI turn starts their turn.
AI owners spend automatically when injured, Demon Seed is active, and one Essence is available.

Keyed off a feature_blocks.d marker (combat/rules/feature_blocks.d/ironroot.json, block "ironroot_demon_bone_regen")
compiled through the compile_block hook, so only a character who actually owns
TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION gets this -- other characters are unaffected.
"""

from __future__ import annotations

from typing import Any

from . import hook
from ..gate2_runtime_models import ActionDefinition, EconomyKind

BLOCK = "ironroot_demon_bone_regen"
DEVOURED_ESSENCE = "resource:named.devoured_essence"
DEMON_SEED_STANCE = "condition:typed.stance.demon_seed"


@hook("compile_block")
def compile_demon_bone_regen(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]):
    if block != BLOCK:
        return None
    return [{**row, "pb": int(numbers.get("pb") or 0), "cl": int(numbers.get("cl") or 1), "key_mod": int(numbers.get("key_mod") or 0),
             **({"a2_cl_gate": True, "choice_owner": True} if spec.get("a2_cl_gate") else {})}]


def _row(engine: Any, actor: Any) -> dict[str, Any] | None:
    return next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("block") == BLOCK), None)


@hook("turn_start_choice")
def demon_bone_regeneration(engine: Any, actor: Any) -> None:
    row = _row(engine, actor)
    if row is not None and row.get("a2_cl_gate") and int(row.get("cl") or 0) < 10:
        return
    if row is None or not actor.active or actor.current_hp <= 0 or actor.current_hp >= actor.maximum_hp:
        return
    if actor.resources.get(DEVOURED_ESSENCE, 0) < 1:
        return
    if not any(c.condition_id == DEMON_SEED_STANCE for c in actor.conditions.values()):
        return  # "While Demon Seed is active"
    from .spend_choice import choose_spend

    if not choose_spend(engine, {**row, "name": "Demon Bone Regeneration", "resource_id": DEVOURED_ESSENCE, "ask": True},
        actor, "DEMON_BONE_REGENERATION", 1, 1,
        {"actor_id": actor.entity_id, "source_id": row["feature_id"], "pool_name": "Devoured Essence",
         "choice_id": "choice:spend.demon_bone_regeneration",
         "cost": "1 Devoured Essence; no Action or Reaction",
         "payment_note": "Choosing Spend uses one stored Essence and heals you now; passing keeps your Essence.",
         "labels": {"1": f"Spend 1 Devoured Essence: {actor.display_name} regains 1d8 + {int(row.get('key_mod') or 0)} HP"},
         "prompt": f"Demon Bone Regeneration: {actor.display_name}'s turn starts while Demon Seed is active. "
                   f"Spend 1 Devoured Essence to regain 1d8 + {int(row.get('key_mod') or 0)} HP now, or pass."}):
        return
    from ..typed_executor import Context, run_effects

    numbers = {"pb": int(row.get("pb") or 0), "cl": int(row.get("cl") or 1), "key_mod": int(row.get("key_mod") or 0)}
    action = ActionDefinition(source_definition_id=f"action:typed.{row['feature_id']}.turn_start", display_name="Demon Bone Regeneration",
                              owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
                              parameters={"typed": {"numbers": numbers}})
    typed = {"numbers": numbers, "source": row["feature_id"]}
    ctx = Context(engine, actor, action, None, typed, [actor], actor)
    run_effects(ctx, [
        {"type": "spend_resource", "applies_to": "self", "resource_id": DEVOURED_ESSENCE, "flat": 1, "formula": "none",
         "evidence": "spend 1 Devoured Essence"},
        {"type": "healing", "applies_to": "self", "regeneration": True,
         "dice": {"count": 1, "sides": 8, "bonus_formula": "key_ability_modifier"},
         "flat": 0, "formula": "none", "evidence": "Regain HP equal to 1d8 + your Daemonic key ability modifier"},
    ])
