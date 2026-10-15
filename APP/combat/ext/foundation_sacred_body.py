"""Ancient Desolate Sacred Body (Foundation) -- Saint-Body Rebuke (owner 2026-09-28: "make sure all the ... foundations
... is applied"). It had compiled as a free reaction applying all three of its riders at once, and as an Iron Fist
variant besides.

Saint-Body Rebuke: after it hits a hostile creature within 5 feet with an unarmed strike or a melee weapon, 1 Golden
Sea Pulse from an earlier event: + PB + Constitution modifier damage of the attack's type, then the chosen rider
("Saint-Body Rebuke: <rider>", a free choice kept until changed; No Reactions unless chosen otherwise; "off" keeps the
Pulse): push 5 feet (no more than one size larger), no Reactions against you until the start of your next turn, or
Advantage on your next Saint-Body Frame resistance roll against that creature before the start of your next turn.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

REBUKE = "foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke"
PULSE = "resource:foundation.golden_sea_pulse"
CHOICE = "condition:typed.saint_body_rebuke_choice"
FRAME = "condition:typed.saint_body_frame_advantage"
OPTIONS = {"reactions": "No Reactions", "push": "Push 5 ft", "frame": "Frame Advantage", "off": "off"}
_BODY = {"forced_movement", "prone", "grappled", "restrained", "poisoned", "exhaustion"}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == "sacred_body"]


@hook("compile_block")
def sacred_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "sacred_body":
        return None
    return [{**row, "block": "sacred_body", "kind": spec.get("kind")}]


@hook("compile_actions")
def rebuke_choices(info: dict[str, Any]) -> list[Any] | None:
    if REBUKE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.saint_body_rebuke.{key}", display_name=f"Saint-Body Rebuke: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "saint_body_rebuke_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in OPTIONS.items()]


@effect("saint_body_rebuke_choice")
def rebuke_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Saint-Body Rebuke: {OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("after_hit")
def rebuke(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _rows(engine, actor) or not target.active or target.team_id == actor.team_id or kind not in ("unarmed", "weapon"):
        return
    ranged = ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5
    if ranged or engine._distance_actor_to_actor(actor, target) > 5 or actor.resources.get(PULSE, 0) < 1:
        return
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "reactions")
    if choice == "off":
        return
    engine._spend_resource(actor, PULSE, 1, f"passive:{REBUKE}")
    dealt = next((event for event in reversed(engine.events[-30:]) if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    kind_ = str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")
    bonus = int(ctx.numbers.get("pb") or 2) + (int(actor.saving_throws.get("CON", 0)) if actor.saving_throws else 0)
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{REBUKE}", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"trigger": "Saint-Body Rebuke"})
    typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": bonus,
                                      **({"damage_types": [kind_.lower()]} if kind_ and kind_ != "UNTYPED" else {}),
                                      "evidence": "Add damage equal to your Proficiency Bonus + your Constitution modifier."}])
    if not target.active:
        return
    if choice == "push":
        if engine._footprint(target).width_cells <= engine._footprint(actor).width_cells + 1:
            typed_executor.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away",
                                              "evidence": "push the target 5 feet if it is no more than one size larger than you"}])
    elif choice == "frame":
        engine._apply_condition(actor, FRAME, f"passive:{REBUKE}", actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"against": target.entity_id, "label": f"Advantage on the next Saint-Body Frame roll against {target.display_name}"})
    else:
        typed_executor.run_effects(sub, [{"type": "deny_reactions_against", "applies_to": "target",
                                          "evidence": "the target cannot take Reactions against you until the start of your next turn"}])


@hook("save")
def frame_advantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability or "").upper()[:3] not in ("STR", "CON") or not _BODY & {str(row).lower() for row in named or ()}:
        return None
    held = [iid for iid, c in subject.conditions.items() if c.condition_id == FRAME and (c.data or {}).get("against") == ctx.actor.entity_id]
    if not held:
        return None
    condition = subject.conditions.pop(held[0])
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": FRAME, "instance_id": held[0], "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["ADVANTAGE"]}
