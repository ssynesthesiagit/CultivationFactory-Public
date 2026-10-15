"""Actual typed attack results finish opted-in physical-item use receipts.

No pending source-owned item checkpoint means no behavior or event. Object
attack adapters finish through the same public helper at their actual roll.
"""
from . import hook


@hook('attack_result')
def item_attack_result(ctx, target, hit, critical):
    from ..item_uses import complete_attack
    complete_attack(ctx, ctx.attack_result, hit, critical)
