"""Reservoir Core Refinement's second Golden Core recovery and mandatory cost.

Printed authority: insight.reservoir-core-refinement in rules_text.json.
Golden Core's action and Perfected start-of-turn trigger use the same general
scene_recovery_limit / scene_recovery_used hooks. The second use restores the
ordinary (or Perfected) amount before adding one Exhaustion level, protected
until the scene ends by forged_exhaustion's public scene_locked_levels API.
No ownership row means no change to any creature's recovery allowance.
"""
from typing import Any

from . import hook, note
from .passive_rows import row_of
from .qi_path import GOLDEN
from .forged_exhaustion import level, locked_level, set_level

FEATURE = "insight.reservoir-core-refinement"
BLOCK = "reservoir_refinement"


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "kind": BLOCK}]


@hook("scene_recovery_limit")
def limit(engine: Any, actor: Any, feature: str) -> int | None:
    if feature == GOLDEN and row_of(engine, actor.entity_id, BLOCK, BLOCK) is not None:
        return 2
    return None


@hook("scene_recovery_used")
def aftermath(engine: Any, actor: Any, feature: str, use_number: int) -> None:
    if feature != GOLDEN or use_number != 2 or row_of(engine, actor.entity_id, BLOCK, BLOCK) is None:
        return
    set_level(engine, actor, level(actor) + 1, FEATURE,
              scene_locked_levels=locked_level(engine, actor) + 1)
    note(engine, FEATURE, actor, f"Reservoir Core Refinement: {actor.display_name}'s second Golden Core Reservoir use "
         "restores Qi, then gives one Exhaustion level (−2 to d20 Tests and −5 feet Speed). "
         "This level cannot be prevented, transferred or removed before the scene ends.")
