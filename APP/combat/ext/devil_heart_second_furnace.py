"""Devil Heart, Second Furnace Subpath (subpaths worker 2026-09-28: "make sure all the talents and class abilities
... is applied"). Reuses combat/ext/qi_path.py's Golden Core Efficiency refund-after-resolution pattern (the cost
was already paid when the feature was used; this table has no "reduce a cost before it is paid" hook).

Demon Seed Overdraw  once per turn, when you pay at least 1 Qi for a Qi feature: refund Proficiency Bonus Qi (never
                     below 0), gain 1 Corruption, then gain 1 Devil Qi and choose one Seed-Fed Reinforcement
                     (Temporary HP = PB; move 5 feet; move your Domain Armament up to 10 feet -- GM-adjudicated,
                     since the table does not expose a generic "move a summoned Domain Armament" hook here; or
                     Advantage on an Intimidation or Cultivation Check before the end of your next turn), a free
                     player choice kept until changed. The printed exclusion list (Legendary/artifact/Secret-Law/
                     Immortal Art/permanent-transformation/etc.) is GM-adjudicated.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

DEMON_SEED_OVERDRAW = "tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw"
QI = "resource:core.qi"
CORRUPTION = "resource:named.corruption"
DEVIL_QI = "resource:named.devil_qi"
CHOICE = "condition:typed.demon_seed_overdraw_choice"
OPTIONS = {"temp_hp": "Temporary Hit Points", "move": "Move 5 Feet", "armament": "Move Domain Armament", "advantage": "Advantage on a Check"}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "devil_heart_second_furnace" and row.get("kind") == "demon_seed_overdraw"]


@hook("compile_block")
def devil_heart_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "devil_heart_second_furnace":
        return None
    return [{**row, "block": "devil_heart_second_furnace", "kind": spec.get("kind")}]


@hook("compile_actions")
def demon_seed_choices(info: dict[str, Any]) -> list[Any] | None:
    if DEMON_SEED_OVERDRAW not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.demon_seed_overdraw.{key}", display_name=f"Seed-Fed Reinforcement: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "demon_seed_overdraw_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in OPTIONS.items()]


@effect("demon_seed_overdraw_choice")
def demon_seed_overdraw_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Seed-Fed Reinforcement: {OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("technique_used")
def demon_seed_overdraw(ctx: Any) -> None:
    actor = ctx.actor
    if not _rows(ctx.engine, actor) or actor.turn_flags.get("demon_seed_overdraw"):
        return
    paid = sum(int(amount) for resource, amount in (ctx.action.costs or ()) if resource == QI)
    if paid < 1 or QI not in actor.resources:
        return
    actor.turn_flags["demon_seed_overdraw"] = True
    engine = ctx.engine
    pb = int(ctx.numbers.get("pb") or 2)
    from ..technique_costs import refund
    refund(engine, actor, ctx.source, ctx.action.costs, QI, min(pb, paid), f"passive:{DEMON_SEED_OVERDRAW}")
    if CORRUPTION in actor.resources:
        engine._gain_resource(actor, CORRUPTION, 1, f"passive:{DEMON_SEED_OVERDRAW}")
    if DEVIL_QI not in actor.resources:
        return
    engine._gain_resource(actor, DEVIL_QI, 1, f"passive:{DEMON_SEED_OVERDRAW}")
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "temp_hp")
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [actor], actor, {})
    if choice == "temp_hp":
        typed_executor.run_effects(sub, [{"type": "temp_hp", "applies_to": "self", "flat": 0, "formula": "pb",
                                          "evidence": "Seed-Fed Reinforcement: Temporary Hit Points equal to PB"}])
    elif choice == "move":
        typed_executor.run_effects(sub, [{"type": "movement", "applies_to": "self", "distance_ft": 5,
                                          "evidence": "Seed-Fed Reinforcement: move 5 feet without provoking"}])
    elif choice == "advantage":
        typed_executor.run_effects(sub, [{"type": "advantage", "applies_to": "self", "on": "one Intimidation or Cultivation Check",
                                          "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                          "evidence": "Seed-Fed Reinforcement: Advantage on one Intimidation or Cultivation Check"}])
    else:
        sub.rider("Seed-Fed Reinforcement: move your Domain Armament up to 10 feet (GM-adjudicated positioning).")
