"""Hammer Rebuke's results (owner playtest 2026-09-29: all three "Failed Save: Choose one" results landed at once, and
"cannot make opportunity attacks" was typed as reaction_denied, which took every Reaction away).

The failed-save pick is a free player toggle kept until changed ("Hammer Rebuke: <choice>"), the same shape as
combat/ext/bodyb_choices.py; the built-in AI takes Disadvantage on its next attack. "Cannot make opportunity attacks"
is the no_opportunity_attacks condition (combat/typed_reactions.py wants_opportunity_attack reads it); the successful
save's "against you" limits it to the blacksmith (data "against").
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

HAMMER_REBUKE = "tianxia.talent.blacksmith.hammer_rebuke"
CHOICE = "condition:typed.hammer_rebuke_choice"
NO_OPPORTUNITY = "condition:typed.no_opportunity_attacks"
UNTIL = "START_OF_TARGET_NEXT_TURN"

OPTIONS: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("disadvantage", "Disadvantage on its next attack", [
        {"type": "disadvantage", "applies_to": "target", "on": "the next attack roll it makes", "expires_on": UNTIL,
         "evidence": "it has Disadvantage on the next attack roll it makes with the triggering weapon or limb before the start of its next turn"}]),
    ("no_oa", "No opportunity attacks", [{"type": "hammer_rebuke_no_oa"}]),
    ("slow", "Speed -10 feet", [
        {"type": "speed", "applies_to": "target", "flat": -10, "expires_on": UNTIL,
         "evidence": "its Speed is reduced by 10 feet until the start of its next turn"}]),
]


@hook("compile_actions")
def choice_actions(info: dict[str, Any]) -> list[Any] | None:
    if HAMMER_REBUKE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.hammer_rebuke.{key}", display_name=f"Hammer Rebuke: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "hammer_rebuke_pick", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True}) for key, label, _effects in OPTIONS]


@effect("hammer_rebuke_pick")
def pick(ctx: Any, eff: dict[str, Any]) -> None:
    choice = str(eff.get("choice"))
    label = next((label for key, label, _ in OPTIONS if key == choice), choice)
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": choice, "label": f"Hammer Rebuke: {label}"})


@effect("hammer_rebuke_choice")
def choice(ctx: Any, eff: dict[str, Any]) -> None:
    """The failed save's branch, run against the creature that failed (block_save's per-subject Context)."""
    if ctx.target is None or not ctx.target.active:
        return
    chosen = next((c.data.get("choice") for c in ctx.actor.conditions.values() if c.condition_id == CHOICE), None)
    branch = next((effects for key, _label, effects in OPTIONS if key == chosen), OPTIONS[0][2])
    from ..typed_executor import run_effects

    run_effects(ctx, branch)


@effect("hammer_rebuke_no_oa")
def no_opportunity(ctx: Any, eff: dict[str, Any]) -> None:
    """It cannot make opportunity attacks until the start of its next turn; "against you" (the successful save) only
    spares the blacksmith."""
    if ctx.target is None or not ctx.target.active:
        return
    from ..typed_executor import stated_expiry

    against = ctx.actor.entity_id if eff.get("against_you") else None
    # Hammer Rebuke is a Reaction, so this lands on the target's own turn: the target's next turn, not the sealed engine's
    # START_OF_TARGET_NEXT_TURN (which ends with the blacksmith's turn, ahead of it).
    ctx.engine._apply_condition(ctx.target, NO_OPPORTUNITY, ctx.source, ctx.actor.entity_id,
                                expires_on=stated_expiry(ctx, {"expires_on": UNTIL}, ctx.target, condition=True),
                                data={"against": against, "label": "No opportunity attacks" + (" against the blacksmith" if against else "")})
