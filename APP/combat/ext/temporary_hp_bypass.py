"""Shared packet allocation for typed damage rows with bypass_temporary_hp=True.

Used by Equal Measure Scripture's Impact Recompense. The ordinary damage row
retains save-for-half, targeting, critical and defense handling. A scope exists
only while that row is dispatched and is restored on a pause or exception.
"""
from contextlib import contextmanager
from . import hook

@contextmanager
def scope(ctx, row):
    from ..typed_executor import effect_subjects
    old = getattr(ctx.engine, "_temporary_hp_bypass", None)
    targets = frozenset(t.entity_id for t in effect_subjects(ctx, row, harmful=True))
    ctx.engine._temporary_hp_bypass = (targets, ctx.damage_source, ctx.actor.entity_id)
    try:
        yield
    finally:
        if old is None:
            ctx.engine.__dict__.pop("_temporary_hp_bypass", None)
        else:
            ctx.engine._temporary_hp_bypass = old

@hook("effect_resolution_scope")
def allocation_scope(ctx, row):
    if row.get("type") == "damage" and row.get("bypass_temporary_hp") is True:
        return scope(ctx, row)
    return None

@hook("damage_bypasses_temporary_hp")
def bypass(engine, target, amount, kind, source, actor_id):
    held = getattr(engine, "_temporary_hp_bypass", None)
    if amount > 0 and held and target.entity_id in held[0] and held[1:] == (source, actor_id):
        return True
    return None
