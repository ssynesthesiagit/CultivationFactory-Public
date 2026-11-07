"""Generic mark-count caps (owner 2026-09-28, "automate every aspect before another playtest").

Several sphere marks are printed with an explicit ceiling on how many the character can maintain at
once ("You can have a number of Faultline Marks active at one time equal to your Proficiency Bonus";
"You can maintain a number of Waning Marks equal to your Proficiency Bonus"). combat/typed_executor.py's
block_mark already enforces a cap when it exists (it ends the oldest instance past the limit): it reads
the cap from ``typed_reactions._rows(engine, owner, "mark_caps")``, keyed by the mark's own name in
lower case. Nothing populated that block until now, so Faultline Mark and Waning Mark were both
unbounded -- a character could hold as many as they could apply, contrary to the printed limit (a
"missing cost/limit" bug per the wave 2 brief).

combat/rules/feature_blocks.d/elements.json marks the feature that states the limit (Faultline Marks,
Mark Limit) with ``{"block": "mark_caps", "caps": {"<mark name lower case>": "pb"}}``; this module's
compile_block hook resolves "pb"/"key_mod" against the character's own numbers so block_mark sees a
plain integer.
"""

from __future__ import annotations

from typing import Any

from . import hook


def _resolve(value: Any, numbers: dict[str, Any]) -> int:
    if isinstance(value, str):
        return int(numbers.get(value, 0) or 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "mark_caps":
        return None
    caps = {str(name).lower(): _resolve(value, numbers) for name, value in (spec.get("caps") or {}).items()}
    if not caps:
        return None
    return [{**row, "caps": caps}]
