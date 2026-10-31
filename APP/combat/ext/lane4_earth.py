"""Mountain-Root Body's Dodge clause (auto-lane4 2026-09-29): "when you take the Dodge action, you may give one creature that
misses you before the start of your next turn one Burden Mark."

The strict ``after_miss_choice`` hook sees the attacker and the creature it
missed. When that creature holds the Dodge action (the core Dodge condition, which lasts to the start of its next turn -- the
printed window) and has this talent, its owner may give the attacker a Burden Mark: the same ``condition:typed.mark.burden_mark.<owner>``
Earthbind Line and Humble Wall place, so Burden the Blade and the rest read it. "One creature" per Dodge is a turn flag, which
the engine clears at the start of the Dodging creature's next turn. Declining leaves the allowance available. Only a hostile attacker is marked ("may": an ally that
happens to miss has nothing to gain from it).

The rest of the talent (three Foundation Spaces, being an origin point for Earth features, Resistance to falling and crushing
damage) needs the Foundation-Space geometry and a damage source the table does not model; those stay printed text.
"""

from __future__ import annotations

from typing import Any

from . import hook

BLOCK = "lane4_dodge"
KIND = "mountain_root_burden"
FLAG = "lane4_mountain_root_burden"


@hook("compile_block")
def lane4_dodge_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}]


@hook("after_miss_choice")
def mountain_root_burden(ctx: Any, target: Any, spec: dict[str, Any]) -> None:
    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or not attacker.active or attacker.team_id == target.team_id:
        return
    rows = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == KIND]
    if not rows or target.turn_flags.get(FLAG):
        return
    if not any(condition.condition_id == "condition:core.dodge" for condition in target.conditions.values()):
        return
    from ..typed_executor import Context, block_mark
    from .rider_choices import pick
    from .needle import numbers_of

    feature_id = rows[0]["feature_id"]
    chosen = pick(engine, target, "mountain_root_dodge", "Mountain-Root Body", ["MARK"], subject=attacker,
        preferred=["MARK"], labels={"MARK": "Give a Burden Mark; no Action or CP cost"},
        trigger=f"{ctx.action.display_name}: {attacker.display_name} misses while you Dodge; one creature per Dodge")
    if not chosen:
        return
    target.turn_flags[FLAG] = 1
    sub = Context(engine, target, ctx.action, ctx.intent, {"source": feature_id, "numbers": numbers_of(engine, target)},
                  [attacker], attacker, effect_source=feature_id)
    block_mark(sub, {"type": "mark", "mark": "Burden Mark", "applies_to": "target", "duration": {"kind": "until_removed"}})
    engine._append_event("PASSIVE_TRIGGERED", feature_id, actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                         payload={"feature_id": feature_id, "mark": "Burden Mark", "missed_by": attacker.entity_id})
