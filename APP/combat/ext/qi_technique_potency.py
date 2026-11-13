"""Qi Technique Potency allocation across mixed weapon/technique damage packets."""
from __future__ import annotations

from typing import Any

from . import hook

POTENCY = "tianxia.path.qi_cultivation.feature.qi_technique_potency"
_PACKET = "_potency_packet"



@hook("damage_packet_selection")
def choose_potency_packet(ctx: Any, target: Any, packet_kinds: tuple[str, ...]) -> None:
    """Choose the single mixed-delivery packet that receives activation potency.

    No potency means no decision. A single delivery needs no prompt; mixed
    deliveries ask the owning player, while automatic actors use the first
    available packet without consulting hidden target state.
    """
    cache = ctx.damage_cache
    # The compiler attaches this number only to qualifying Qi activations; its presence
    # is the provenance marker, independent of the source ID namespace.
    if (not int(ctx.numbers.get("potency") or 0) or cache.get("_potency_used") or not packet_kinds):
        return
    if _PACKET in cache:
        return
    if len(packet_kinds) == 1:
        cache[_PACKET] = packet_kinds[0]
        return

    from .needle import CHOICE, ask, checkpoint_id

    action_name = str(getattr(ctx.action, "display_name", None) or "the technique")
    options = list(packet_kinds)
    labels = {
        "weapon": "Add Qi Technique Potency to the weapon damage roll",
        "technique": "Add Qi Technique Potency to the technique damage roll",
    }
    selected = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "qi_technique_potency", ctx.actor.entity_id, target.entity_id),
        ctx.actor, CHOICE + "qi_technique_potency", options, labels=labels,
        allow_decline=False, automatic=True, default="first", target_id=target.entity_id,
        name="Qi Technique Potency",
        prompt=(f"Qi Technique Potency: {action_name} hits {target.display_name}. "
                "Choose whether to add your Qi Cultivation key ability modifier to the weapon damage "
                "or technique damage roll."),
        prompt_context={"source_definition_id": POTENCY, "action_name": action_name,
                        "action_actor_id": ctx.actor.entity_id, "affected_id": target.entity_id})
    if selected:
        cache[_PACKET] = selected[0]


@hook("damage_packet_selection")
def apply_weapon_potency(ctx: Any, target: Any, packet_kinds: tuple[str, ...]) -> None:
    """Apply the selected weapon packet's flat bonus at its confirmed-hit boundary."""
    if (not int(ctx.numbers.get("potency") or 0)
            or ctx.damage_cache.get(_PACKET) != "weapon" or ctx.damage_cache.get("_potency_used")):
        return
    spec = ctx.attack_defense_spec
    held = spec.get("damage") if spec else None
    if held is None or getattr(held, "count", 0) <= 0 or getattr(held, "sides", 0) < 1:
        return
    from ..typed_executor import take_activation_bonus

    bonus = take_activation_bonus(ctx, "potency")
    if bonus:
        spec["damage"] = held.model_copy(update={"modifier": held.modifier + bonus})
