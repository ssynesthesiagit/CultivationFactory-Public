"""Shared pure reaction-range helper.

reach(engine, actor, feature_id, base_ft) adds strict nonnegative replies from
reaction_range_bonus. A target opts into the pure reaction_context_range
transform. Consumers: typed_reactions generic eligibility, d20_rewrite holder
eligibility, and void_riders custom benefit reactions (without a target).
context_reach applies only the new target-aware policy, preserving callers
that never consumed reaction_range_bonus before this seam existed.
No reply preserves the original distance.
"""
from . import run_strict


def reach(engine, actor, feature_id, base_ft, *, target=None):
    answers = run_strict('reaction_range_bonus', engine, actor, feature_id)
    if any(type(value) is not int or value < 0 for value in answers):
        raise ValueError('reaction_range_bonus requires a nonnegative integer')
    limit = int(base_ft) + sum(answers) if answers else base_ft
    if target is not None:
        limit = context_reach(engine, actor, target, feature_id, limit)
    return limit


def context_reach(engine, actor, target, feature_id, base_ft):
    """Target-aware reach without importing another caller's bonus policy."""
    from . import transform
    limit = transform('reaction_context_range', base_ft, engine, actor, target, feature_id)
    if limit != base_ft and (type(limit) is not int or limit < 0):
        raise ValueError('reaction_context_range requires a nonnegative integer')
    return limit
