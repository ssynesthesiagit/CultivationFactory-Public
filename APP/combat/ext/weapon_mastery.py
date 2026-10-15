"""Shared per-turn limits for weapon masteries, keyed by compiled weapon metadata.

Nick (2024): the Light property's extra attack is part of the Attack action, "only once per turn". Every Nick off-hand
button, and every action compiled to take its place (typed.replaces_attack, e.g. Combo Maneuvers' Shove/Grapple in
place of the Paired Strike), shares that one use.

Cleave (2024): after a melee hit, one optional extra attack against a second creature; the owner picks the creature or
declines (typed_executor.block_cleave calls the optional_followup_target seam).
"""

from typing import Any

from . import hook


_NICK_USED = "weapon_mastery_nick_extra_attack_used"


def _is_nick_extra(action: Any) -> bool:
    """A Nick weapon's off-hand attack, or an action compiled to replace one (typed.replaces_attack provenance)."""
    typed = (getattr(action, "parameters", {}) or {}).get("typed") or {}
    replaced = typed.get("replaces_attack") or {}
    if replaced:
        source, mastery = str(replaced.get("source_definition_id") or ""), replaced.get("mastery")
    else:
        source, mastery = str(getattr(action, "source_definition_id", "")), typed.get("mastery")
    return "#offhand" in source and mastery == "Nick"


@hook("candidate_allowed")
def nick_extra_attack_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """All Nick off-hand buttons and their replacements share one Attack-action use during the actor's turn."""
    if _is_nick_extra(action) and actor.turn_flags.get(_NICK_USED):
        return False
    return None


@hook("technique_start")
def spend_nick_extra_attack(engine: Any, actor: Any, action: Any) -> None:
    """Spend the shared Nick use when its extra attack (or a replacement for it, attack roll or save) is made."""
    if _is_nick_extra(action):
        actor.turn_flags[_NICK_USED] = True
    return None


@hook("optional_followup_target")
def choose_cleave_target(ctx: Any, effect: dict[str, Any], eligible_targets: list[Any], preferred_target_id: str) -> str | None:
    """Ask for the optional Cleave target; None for any other effect that uses this seam."""
    if effect.get("type") != "cleave":
        return None
    from .needle import ask, checkpoint_id

    first = ctx.target
    options = [actor.entity_id for actor in eligible_targets]
    labels = {actor.entity_id: actor.display_name for actor in eligible_targets}
    picked = ask(
        ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "cleave", ctx.actor.entity_id, first.entity_id, ctx.source),
        ctx.actor, "choice:needle.cleave", options, labels=labels,
        prompt=(f"After your {ctx.action.display_name} hits {first.display_name}, use Cleave to make one extra attack "
                "against a different creature within 5 feet of it and within your reach? Cleave works once per turn; "
                "declining keeps it for a later hit this turn. It costs no extra action or resource."),
        preferred=[preferred_target_id], allow_decline=True, automatic=True,
        target_id=first.entity_id, name="Cleave", feature_id=ctx.source,
        prompt_context={"source_definition_id": ctx.source, "action_name": ctx.action.display_name,
                       "action_actor_id": ctx.actor.entity_id, "affected_id": first.entity_id})
    return picked[0] if picked else ""
