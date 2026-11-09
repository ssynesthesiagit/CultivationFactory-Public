"""Black Sea Leviathan Womb Subpath (subpaths worker 2026-09-28: "make sure all the talents and class abilities
... is applied").

Pressure of Recognition  once per turn, after a Qi-powered feature of yours damages or forcibly moves a hostile
                         creature, place one Depth Mark on it. (The printed Grapple/Restrain/Speed-reduction-only
                         triggers without damage or forced movement are GM-adjudicated -- the table has no
                         generic "applied one of these five specific effects" scan.)
Spend Depth              once per turn, when a Qi-powered feature of yours affects a Depth-Marked creature, spend
                         1 Inner-Sea Depth: choose one (a free player choice, kept until changed) -- 2d8 (4d8 at
                         CL17) Cold or Force damage; pull 10 feet; Speed -15 until the start of your next turn;
                         deny Reactions until the start of its next turn; or Temporary HP equal to twice PB.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

INNER_SEA_AWAKENING = "tianxia.subpath.qi.black_sea_leviathan_womb.feature.inner_sea_awakening"
QI = "resource:core.qi"
DEPTH = "resource:named.inner_sea_depth"
DEPTH_MARK = "Depth Mark"
CHOICE = "condition:typed.spend_depth_choice"
OPTIONS = {"damage": "Cold or Force Damage", "pull": "Pull 10 Feet", "speed": "Speed -15",
           "reactions": "Deny Reactions", "temp_hp": "Temporary Hit Points"}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "black_sea_leviathan_womb" and row.get("kind") == "inner_sea_awakening"]


@hook("compile_block")
def leviathan_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "black_sea_leviathan_womb":
        return None
    return [{**row, "block": "black_sea_leviathan_womb", "kind": spec.get("kind")}]


@hook("compile_actions")
def spend_depth_choices(info: dict[str, Any]) -> list[Any] | None:
    if INNER_SEA_AWAKENING not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.spend_depth.{key}", display_name=f"Spend Depth: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "spend_depth_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in OPTIONS.items()]


@effect("spend_depth_choice")
def spend_depth_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Spend Depth: {OPTIONS.get(str(eff.get('choice')), '')}"})


def _qualifying_targets(engine: Any, actor: Any, ctx: Any) -> list[Any]:
    """Targets this activation damaged or forcibly moved (the two most common of the printed five verbs)."""
    hit_ids = {event.target_ids[0] for event in engine.events[-30:]
               if event.actor_id == actor.entity_id and event.target_ids
               and event.event_type in ("DAMAGE_COMMITTED", "MOVEMENT_COMMITTED") and event.source_definition_id == ctx.action.source_definition_id}
    return [target for target in ctx.targets if target.entity_id in hit_ids]


@hook("technique_used")
def leviathan_womb(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _rows(engine, actor) or QI not in actor.resources:
        return
    paid = sum(int(amount) for resource, amount in (ctx.action.costs or ()) if resource == QI)
    if paid < 1 or not ctx.targets:
        return
    from .. import typed_executor

    targets = _qualifying_targets(engine, actor, ctx)
    marked = [target for target in targets if typed_executor.bears_mark(target, actor.entity_id, DEPTH_MARK)]
    if marked and not actor.turn_flags.get("spend_depth") and actor.resources.get(DEPTH, 0) >= 1:
        actor.turn_flags["spend_depth"] = True
        engine._spend_resource(actor, DEPTH, 1, f"passive:{INNER_SEA_AWAKENING}")
        choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "damage")
        target = marked[0]
        sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
        cl = int(ctx.numbers.get("cl") or 1)
        if choice == "damage":
            typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4 if cl >= 17 else 2, "sides": 8},
                                              "damage_types": ["cold", "force"], "evidence": "Spend Depth: Cold or Force damage"}])
        elif choice == "pull":
            typed_executor.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "toward",
                                              "evidence": "Spend Depth: pull it 10 feet"}])
        elif choice == "speed":
            typed_executor.run_effects(sub, [{"type": "speed", "applies_to": "target", "flat": -15,
                                              "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Spend Depth: Speed -15"}])
        elif choice == "reactions":
            typed_executor.run_effects(sub, [{"type": "condition", "condition": "reaction_denied", "applies_to": "target",
                                              "expires_on": "START_OF_TARGET_NEXT_TURN", "evidence": "Spend Depth: deny Reactions"}])
        else:
            typed_executor.run_effects(sub, [{"type": "temp_hp", "applies_to": "self", "flat": 0, "formula": "double_pb",
                                              "evidence": "Spend Depth: Temporary Hit Points equal to twice Proficiency Bonus"}])
    if targets and not actor.turn_flags.get("pressure_of_recognition"):
        actor.turn_flags["pressure_of_recognition"] = True
        sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [targets[0]], targets[0], {})
        typed_executor.run_effects(sub, [{"type": "mark", "mark": DEPTH_MARK, "applies_to": "target",
                                          "duration": {"kind": "until_removed"}, "evidence": "Pressure of Recognition: place one Depth Mark"}])
