"""Life sphere, the Pulse abilities (typing pass 2026-09-28, the RIDERS_ONLY talents of Life).

Restorative Mend ("When you use Mend the Pulse or Borrowed Breath, you may also use Purify the Pulse on the same target as
part of the same Action. You must pay the CP cost of Purify the Pulse normally.") compiles to a variant of Mend the Pulse and
of Borrowed Breath that costs Purify's 1 CP more and runs ``purify_one`` after the healing: Purify the Pulse's own removal,
"one disease or one of the following conditions: Blinded; Deafened; Paralyzed; Poisoned" (LIFE_BASE_PURIFY_THE_PULSE). The
printed rule lets the user choose which one. New choose_treatment rows ask the player; old saved rows retain the
original worst-first automatic order below. There is no disease in the engine, so a target with none of the four conditions loses nothing (the healing still
lands and the CP is still spent, exactly as a Purify aimed at a creature with nothing to purify would).

Deep Root Restoration, Life-Seal Reach and Mend the Pulse's scaling need nothing here: they are typed data
(authority/typed_mechanics/reviewed_final.d/riders_life.json) that the compiler reads, Life-Seal Reach through its
``range_ft_by_cl`` and ``target_requires_mark`` fields (combat/factory_compiler.py _reach_fields)."""

from __future__ import annotations

from typing import Any

from . import effect
from ..typed_executor import CONDITION_PREFIX, _default_subject

# The four conditions Purify the Pulse removes, the worst for its bearer first: a Paralyzed creature cannot act at all, a
# Blinded one cannot see what it fights, Poisoned takes rolls from it, and Deafened costs it least.
PURIFY_ORDER = ("paralyzed", "blinded", "poisoned", "deafened")


@effect("purify_one")
def purify_one(ctx: Any, effect_row: dict[str, Any]) -> None:
    """End one of the conditions Purify the Pulse removes on the subject (the first it bears, in PURIFY_ORDER)."""
    if effect_row.get("choose_treatment"):
        from dataclasses import replace
        from .life_treatment import choose_purification
        from ..typed_executor import run_effects

        for subject in _default_subject(ctx, effect_row, harmful=False):
            if subject is not None and subject.active:
                sub = replace(ctx, target=subject, targets=[subject])
                run_effects(sub, choose_purification(sub, effect_row.get("purify_options") or [], name="Restorative Mend"))
        return
    for subject in _default_subject(ctx, effect_row, harmful=False):
        if subject is None or not subject.active:
            continue
        held = {condition.condition_id for condition in subject.conditions.values()}
        for name in PURIFY_ORDER:
            if CONDITION_PREFIX + name in held:
                ctx.engine._remove_condition(subject, CONDITION_PREFIX + name, ctx.source)
                break
