"""Spear sphere core mechanics (worker martial, 2026-09-28, "automate every aspect before another playtest").
Mo Ruo owns almost all of this sphere; Wen Yaoxue, Nixian Weave, Chen Lan and Lingfeng the Ember Artisan share a
handful of records.

Spear Thrust, Dragon-Spear Charge, Flowers in the Storm and Intercepting Thrust all read "make one attack with
an approved Spear weapon" (or "make an attack using an approved Spear weapon") -- the same shape Wen Xue's
Sabers work found for "make one saber attack" (combat/ext/wenxue_sabers.py): it does not match
factory_authoring.typed_structure.weapon_delivery's regex (which wants "melee weapon attack"/"weapon attack",
not "an approved Spear weapon attack"), so none of these ever got the character's real weapon dice --
confirmed against the built authority (``weapon_delivery`` is null on all four). Fixed the same way: an
``attach_spear_weapon`` effect placed just before each "attack" effect in reviewed_final.d/martial.json's own
effects/options lists, so ``run_effects``'s shared Context has ``ctx.typed["weapon"]`` set before the "attack"
effect (whose on_hit already carries a plain ``{"type": "damage", "weapon_damage": true}``) resolves it.

Spear Guard's damage-reduction reaction needs no weapon of its own (it reduces an incoming hit, not delivering
one) and is untouched by this file.
"""

from __future__ import annotations

from typing import Any

from . import effect
from .weapon_hits import available_weapons

SPEAR_WORDS = ("spear", "pike", "lance", "trident")


def spear_weapons(ctx: Any) -> dict[str, Any]:
    """One action per approved weapon; technique and thrown variants share its identity."""
    return available_weapons(ctx.engine, ctx.actor, SPEAR_WORDS)


def choose_spear(ctx: Any, *, require_ready: bool = False) -> Any:
    from . import needle

    from ..weapon_delivery import ready_weapons
    weapons = ready_weapons(ctx.engine, ctx.actor, SPEAR_WORDS) if require_ready else spear_weapons(ctx)
    from .move_attack import movement_row, legal_weapons
    movement = movement_row(ctx.action)
    if movement is not None and movement.get("weapon_words") and ctx.target is not None:
        legal = legal_weapons(ctx.engine, ctx.actor, ctx.target, ctx.action, movement)
        weapons = {key: weapon for key, weapon in weapons.items() if key in legal}
    if not weapons:
        ctx.rider("No approved Spear weapon found.")
        return None
    choices = list(weapons)
    picked = choices if len(choices) == 1 else needle.ask(
        ctx.engine, ctx.intent, f"SPEAR_WEAPON:{ctx.source}", ctx.actor, "choice:needle.spear_weapon", choices,
        labels={key: action.display_name for key, action in weapons.items()},
        prompt=f"{ctx.action.display_name}: choose the approved Spear weapon", preferred=choices[:1])
    return weapons.get(picked[0]) if picked else None


@effect("bind_spear_weapon")
def bind_spear_weapon(ctx: Any, effect_row: dict[str, Any]) -> None:
    weapon = choose_spear(ctx)
    # Empty binding must not silently broaden the bonus when no weapon exists.
    ctx.damage_cache["_on_hit_weapon_id"] = weapon.source_definition_id.split("#", 1)[0] if weapon else "NO_WEAPON"


@effect("attach_spear_weapon")
def attach_spear_weapon(ctx: Any, effect_row: dict[str, Any]) -> None:
    if ctx.typed.get("weapon"):
        return  # already resolved
    action = choose_spear(ctx, require_ready=bool(effect_row.get("require_ready")))
    if action is None:
        ctx.rider("No approved Spear weapon found to deliver this Spear attack's damage.")
        return
    ctx.typed["weapon"] = action.parameters["typed"]["weapon"]
    ctx.typed["weapon_source_id"] = action.source_definition_id.split("#", 1)[0]
