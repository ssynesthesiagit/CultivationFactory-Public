"""Shared pure reaction-range helper.

reach(engine, actor, feature_id, base_ft) adds strict nonnegative replies from
reaction_range_bonus. Consumers: typed_reactions generic eligibility and
void_riders custom benefit reactions. No reply preserves the original distance.
"""
from . import run_strict


def reach(engine, actor, feature_id, base_ft):
    answers = run_strict('reaction_range_bonus', engine, actor, feature_id)
    if any(type(value) is not int or value < 0 for value in answers):
        raise ValueError('reaction_range_bonus requires a nonnegative integer')
    return int(base_ft) + sum(answers) if answers else base_ft
