"""Data-owned rolled condition lifetimes and explicit ability damage bonuses."""
from collections.abc import Mapping

from . import effect, hook


@effect('rolled_condition_rounds')
def apply(ctx, row):
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import run_effects
    from .effect_durations import round_token

    target = ctx.target
    if target is None or not target.active:
        return
    # One duration roll per activation, shared by all failed-save recipients.
    key = ('rolled_condition_rounds', row['condition'], ctx.source)
    if key not in ctx.damage_cache:
        roll = ctx.engine.roller.roll(DiceSpec.model_validate(row['duration_dice']),
            actor_id=ctx.actor.entity_id, reason='CONDITION_DURATION')
        ctx.engine._record_roll(roll)
        ctx.damage_cache[key] = max(1, int(roll.total))
    run_effects(ctx, [{'type': 'condition', 'condition': row['condition'], 'applies_to': 'target',
        'expires_on': round_token(ctx.engine, ctx.damage_cache[key]), 'evidence': row.get('evidence', '')}])


@hook('damage_roll_bonus')
def explicit_ability_bonus(ctx, row, kinds):
    # The contract passes None for the one dice an ordinary attack sequence shares
    # (see ext/__init__.py: "effect is None for attack-sequence dice"); a character
    # without this row is inert. Only a caller-supplied damage row opts in.
    if not isinstance(row, Mapping) or not row.get('damage_ability'):
        return None
    from ..ability_checks import ability_modifier
    # Prefer an actual score; never borrow saving-throw proficiency.
    ability = str(row['damage_ability']).upper()
    score = getattr(ctx.actor, {'STR': 'strength_score', 'DEX': 'dexterity_score'}.get(ability, ''), None)
    return ((int(score) - 10) // 2 if score is not None else
            ability_modifier(ctx.actor, ability, numbers=ctx.numbers, fallback=0))
