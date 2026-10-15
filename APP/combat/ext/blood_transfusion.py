"""Blood sphere: Vital Transfusion (sweep sw-blacksmith 2026-09-29).

"You take self-damage up to the maximum shown on the Vital Transfusion Maximum table ... Roll the listed dice when you
activate the talent, then choose how much self-damage to take, up to the rolled maximum. This self-damage ignores Resistance
and Immunity; cannot be reduced; cannot be transferred; cannot be paid with Temporary HP; cannot reduce you below 1 HP. One
living creature you touch regains HP equal to the self-damage taken."

The typing was one ``damage`` row aimed at the user (1d8 + key modifier at every Cultivation Level, no table): the compiler
read it as an attack on a hostile creature, so the user hurt only itself and nobody regained anything. ``transfuse`` does what
is printed. It rolls the maximum for the user's CL (``dice_by_cl``), then asks manual owners how much self-damage to take.
AI owners choose as much as the touched creature can use, no more than the roll and no more than leaves the user 1 HP.
The selected amount comes off the user's HP
directly -- past resistance, immunity, reductions, reactions and Temporary HP, as printed -- and the touched creature regains
it through the ordinary healing path (block_healing: a "cannot regain HP" effect still applies). Both changes are in the
events a saved fight replays (DAMAGE_COMMITTED ``remaining_hp``, HEALING_APPLIED ``after``). A user who was concentrating
makes the usual Constitution check for the damage taken, since nothing printed exempts it.

Touching yourself is not a transfusion (net nothing), and a creature that is down cannot be touched back up by it: the
talent then does nothing and says so as a GM line.
"""

from __future__ import annotations

from typing import Any

from . import effect
from ..typed_executor import _effect_dice, _roll, block_healing


@effect("transfuse")
def transfuse(ctx: Any, eff: dict[str, Any]) -> None:
    """Roll a maximum, choose the payment, then self-damage and heal atomically."""
    actor = ctx.actor
    touched = ctx.target if ctx.target is not None else (ctx.targets[0] if ctx.targets else None)
    if touched is None or touched is actor or not touched.active:
        ctx.rider("Vital Transfusion needs another living creature to touch: nothing happens.")
        return
    rolled = _roll(ctx, ctx.dice(_effect_dice(ctx, eff), flat=int(eff.get("flat") or 0), formula=eff.get("formula")), "TRANSFUSION")
    maximum = min(rolled, actor.current_hp - 1)
    if maximum <= 0:
        return
    from .spend_choice import choose_spend

    amount = choose_spend(ctx.engine,
        {"feature_id": str(ctx.typed.get("source")), "name": "Vital Transfusion", "resource_id": "hp", "ask": True},
        actor, "VITAL_TRANSFUSION", maximum, min(maximum, touched.maximum_hp - touched.current_hp),
        {"source_id": ctx.source, "actor_id": actor.entity_id, "target_id": touched.entity_id, "pool_name": "HP",
         "choice_id": "choice:spend.vital_transfusion",
         "cost": f"Action; choose 0–{maximum} self-damage (leaves you at least 1 HP)",
         "payment_note": "Your chosen self-damage and the healing happen together when you confirm; passing takes 0 HP.",
         "labels": {str(n): f"Take {n} self-damage; {touched.display_name} regains up to {n} HP" for n in range(1, maximum + 1)},
         "prompt": f"Vital Transfusion: {actor.display_name} touches {touched.display_name}. Rolled maximum: {rolled}. "
                   f"Choose up to {maximum} self-damage to heal that creature by the same amount, or pass to take 0. "
                   "This damage bypasses Temporary HP and all damage reductions; it leaves you at least 1 HP."})
    if amount <= 0:
        return
    actor.current_hp -= amount
    ctx.engine._append_event("DAMAGE_COMMITTED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={
        "rolled_or_pending_damage": rolled, "reduced_to": amount, "temporary_hp_absorbed": 0, "hp_damage": amount,
        "damage_type": "SELF", "remaining_hp": actor.current_hp})
    if actor.concentration is not None and actor.active:
        ctx.engine._concentration_check(actor, amount)
    block_healing(ctx, {"type": "healing", "applies_to": "target", "flat": amount})
