"""Shared creation-time durability query for typed walls and bound objects.

Bonuses are frozen into the evented HP at creation; previews, damage, reload and
repairs do not reapply them. Default inert, strict nonnegative integer replies.
"""
from . import run_strict


def creation_bonus(ctx, kind):
    total = 0
    for bonus in run_strict('created_durability_bonus', ctx, kind):
        if type(bonus) is not int or bonus < 0:
            raise ValueError('Creation durability bonuses must be nonnegative integers')
        total += bonus
    return total
