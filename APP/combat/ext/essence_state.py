"""Recorded essence provenance and explicit restoration for predatory Insights.

Used by qi_devourer, and available to soul/clone/summon providers. Ordinary
creatures have genuine essence. Constructs, illusions, projected clones,
disposable summons and refund bodies require an explicit independent source.
The essence_profile effect records those source facts as integers/strings in
an evented condition; it grants no ability. restore_essence is reserved for a
Source Rule explicitly rebuilding consumed life-force, spirit or cultivation;
ordinary healing/revival never calls it. It clears consumption receipts only.
"""
from . import effect
from ..typed_executor import _default_subject

PROFILE = "condition:typed.essence_profile"
DEPLETED = "condition:typed.essence_consumed."
EXCLUDED = {"construct", "illusion", "projected_clone", "disposable_body", "refund_body"}


def profile(actor):
    """Authoritative represented essence facts, never guessed from names."""
    recorded = next((c.data for c in actor.conditions.values() if c.condition_id == PROFILE), {})
    types = {str(t).lower().rsplit(":", 1)[-1] for t in actor.creature_types}
    # Being summoned alone is not being a disposable body: a real companion
    # may possess ordinary independent life-force. Require represented facts.
    summon = actor.summon or {}
    excluded = (bool(types & EXCLUDED) or recorded.get("kind") in EXCLUDED
                or summon.get("disposable") == 1 or summon.get("essence_kind") in EXCLUDED)
    genuine = recorded.get("genuine", 1) == 1 and (not excluded or recorded.get("independent", 0) == 1)
    return {**recorded, "genuine": int(genuine)}


@effect("essence_profile", harmful=False)
def record_profile(ctx, row):
    """Explicit source-authored provenance; no creature's name implies a soul."""
    data = {k: row[k] for k in ("kind", "genuine", "independent") if k in row}
    if any(type(v) not in (int, str) for v in data.values()):
        raise ValueError("essence provenance must contain integers and strings")
    for target in _default_subject(ctx, row, harmful=False):
        ctx.engine._remove_condition(target, PROFILE, ctx.source)
        ctx.engine._apply_condition(target, PROFILE, ctx.source, ctx.actor.entity_id,
            expires_on="UNTIL_REMOVED", data={**data, "label": "Recorded cultivated essence provenance"})


@effect("restore_essence", harmful=False)
def restore(ctx, row):
    """Only explicitly fully rebuilt essence refreshes consumption eligibility."""
    if row.get("fully_rebuilt") != 1:
        raise ValueError("essence restoration requires an explicit fully rebuilt source rule")
    for target in _default_subject(ctx, row, harmful=False):
        for condition in list(target.conditions.values()):
            if condition.condition_id.startswith(DEPLETED):
                ctx.engine._remove_condition(target, condition.condition_id, ctx.source)
