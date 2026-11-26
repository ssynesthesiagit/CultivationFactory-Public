"""An effect that depends on how big its subject is next to its source (riders lane 2, 2026-09-29: Yang's Force Completion, "If the target is
more than one size larger than the source, it makes a Strength saving throw. On a successful save, it is not pushed").

    {"type": "size_gate", "larger_by": 1, "if_larger": [...], "otherwise": [...]}

For each subject of the activation (its target, else its targets): when the subject is more than ``larger_by`` sizes larger than the actor
(the source of the effect), the ``if_larger`` effects run for it; otherwise the ``otherwise`` ones do.  A size is one step of the grid's
footprint (Medium 1 square, Large 2, Huge 3, Gargantuan 4), the same measure the Grapple and Shove rules use.
"""

from __future__ import annotations

from typing import Any

from . import effect


@effect("size_gate")
def run(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import Context, run_effects

    gap = int(row.get("larger_by") if row.get("larger_by") is not None else 1)
    subjects = [ctx.target] if ctx.target is not None else list(ctx.targets)
    for subject in subjects:
        if subject is None or not subject.active:
            continue
        bigger = ctx.engine._footprint(subject).width_cells > ctx.engine._footprint(ctx.actor).width_cells + gap
        nested = row.get("if_larger") if bigger else row.get("otherwise")
        if nested:
            run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache), nested)
