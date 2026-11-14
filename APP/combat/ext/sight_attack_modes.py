"""Reviewed defenses that penalize only an attacker relying on sight."""
from . import hook


@hook("attack_mode")
def sight_defense(ctx, target):
    from .. import senses, typed_executor

    if senses.perceives_without_sight(ctx.engine, ctx.actor, target):
        return None
    return next((rule["attacked_with_if_sight"] for rule in typed_executor.condition_rules(target)
                 if rule.get("attacked_with_if_sight")), None)
