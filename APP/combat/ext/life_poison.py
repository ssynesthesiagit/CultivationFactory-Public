"""Poison sphere: enforce the printed "target must already carry a Dose Mark/Toxin Burden from you"
requirements that the compiler does not otherwise gate (owner 2026-09-28, "automate every aspect before
another playtest"). Ingrain the Toxin ("Target: One creature with at least 2 Dose Marks from you") and
Deepen the Burden ("When a creature has at least 2 Dose Marks from you") would otherwise be free,
unconditional debuffs against any target: combat/typed_executor.py's block_spend_mark tries to spend a
named mark and, finding none, simply does nothing rather than failing the action, so without this gate a
fighter could use either ability on an unmarked creature and still get the save-and-debuff for free.

Counted marks and the exact two-mark gate are supplied by stacking_marks.py.
This older gate additionally checks the source owner and the prerequisite mark kind.
"""

from __future__ import annotations

from typing import Any

from . import hook

REQUIRES_DOSE_MARK = {"POISON_BASE_INGRAIN_THE_TOXIN", "tianxia.talent.poison.deepen_the_burden"}
REQUIRES_DOSE_OR_BURDEN = {"tianxia.talent.poison.five_venom_formula"}
REQUIRES_TOXIN_BURDEN = {"tianxia.talent.poison.lingering_meridian_venom"}


@hook("candidate_allowed")
def _requires_prior_mark(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not candidate.target_ids:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    source = typed.get("source") or typed.get("option_of")
    if source not in REQUIRES_DOSE_MARK and source not in REQUIRES_DOSE_OR_BURDEN and source not in REQUIRES_TOXIN_BURDEN:
        return None
    target = engine.state.actors.get(candidate.target_ids[0])
    if target is None:
        return None
    from ..typed_executor import bears_mark

    if source in REQUIRES_DOSE_MARK:
        return bears_mark(target, actor.entity_id, "Dose Mark")
    if source in REQUIRES_TOXIN_BURDEN:
        return bears_mark(target, actor.entity_id, "Toxin Burden")
    return bears_mark(target, actor.entity_id, "Dose Mark") or bears_mark(target, actor.entity_id, "Toxin Burden")
