"""Unmaking talents that need a hook (owner 2026-09-28, Tabik Damu's kit; the rest is combat/unmaking.py):

  Black-Vein Palm   "Black-Vein Palm: <choice>", free choices kept until changed, pick what the next charged Internal
                    Channel hit does (no Reactions until chosen); the Constitution-save choice gives Disadvantage on the
                    target's next Constitution save before the end of its next turn (typed saves).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook


@hook("compile_actions")
def palm_choices(info: dict[str, Any]) -> list[Any] | None:
    if not any(row.get("block") == "unmaking" and row.get("kind") == "black_vein_palm" for row in info["passives"]):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..unmaking import PALM_OPTIONS

    labels = {"reactions": "No Reactions", "healing": "No Healing", "con_save": "Constitution Save Disadvantage"}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.black_vein_palm.{key}", display_name=f"Black-Vein Palm: {labels[key]}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "black_vein_palm_choice", "choice": key, "evidence": PALM_OPTIONS[key]}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key in labels]


@effect("black_vein_palm_choice")
def black_vein_palm_choice(ctx: Any, eff: dict[str, Any]) -> None:
    from ..unmaking import PALM_CHOICE

    ctx.engine._remove_condition(ctx.actor, PALM_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, PALM_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Black-Vein Palm: {eff.get('evidence')}"})


@hook("save")
def palm_con_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    from ..unmaking import PALM_CON

    if str(ability or "").upper()[:3] != "CON":
        return None
    held = [iid for iid, c in subject.conditions.items() if c.condition_id == PALM_CON]
    if not held:
        return None
    condition = subject.conditions.pop(held[0])
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": PALM_CON, "instance_id": held[0], "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}
