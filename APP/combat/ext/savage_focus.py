"""Savage (Berserker, Focus): "When you reduce an eligible creature to 0 HP with a melee or thrown weapon attack, use a Bonus
Action to regain Martial Focus. The creature must have CR at least half your CL, rounded down, minimum CR 1/2."

A melee or thrown weapon hit (or an Unarmed Strike) that leaves the target at 0 HP opens a Bonus Action for the rest of the
turn (the engine's ``requires_turn_flag`` gate, as Advancing Carnage does), offered only while the fighter does not already hold
Martial Focus. The creature's Cultivation Level stands in for its CR when it is a compiled character; a creature whose CR this
table does not track counts, and the action's rider asks the GM to confirm it.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .mind_hidden_eye import FOCUS
from .passive_rows import known_level, melee_or_thrown, row_of

SAVAGE = "TAL_BERSERKER_SAVAGE"
FLAG = "savage_ready"


@hook("compile_block")
def savage_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "kill_focus":
        return None
    return [{**row, "block": "kill_focus", "kind": spec.get("kind"), "min_cr": max(0.5, int(numbers.get("cl") or 1) // 2)}]


@hook("after_hit")
def savage_kill(ctx: Any, target: Any, kind: str) -> None:
    row = row_of(ctx.engine, ctx.actor.entity_id, "kill_focus", "savage")
    if row is None or (target.active and target.current_hp > 0):
        return
    if not (kind == "unarmed" or (kind == "weapon" and melee_or_thrown(ctx))):
        return
    level = known_level(ctx.engine, target)
    if level is not None and level < float(row["min_cr"]):
        return
    ctx.actor.turn_flags[FLAG] = True


@hook("compile_actions")
def savage_action(info: dict[str, Any]) -> list[Any] | None:
    if SAVAGE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.savage", display_name="Savage: Regain Martial Focus",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "gain_resource", "resource_id": FOCUS, "applies_to": "self", "flat": 1, "formula": "none"}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"},
                              "riders": ["Savage: the creature must have CR at least half your CL (rounded down, minimum 1/2); "
                                         "this table checks it only for a creature with a known Cultivation Level -- confirm any other."]},
                    "expected_damage": 0, "requires_turn_flag": FLAG})]


@hook("candidate_allowed")
def savage_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not str(getattr(action, "source_definition_id", "")).endswith(".savage"):
        return None
    return actor.resources.get(FOCUS, 0) < 1  # already holds it: nothing to regain
