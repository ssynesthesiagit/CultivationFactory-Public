"""Native pre-damage critical policy and scoped compatibility for typed providers."""
from contextlib import contextmanager
from . import ext


def hits(natural, total, armor_class, threshold=20):
    """The shared current/replacement attack outcome; natural 1 always misses."""
    return natural != 1 and (natural >= threshold or total >= armor_class)


@contextmanager
def typed_scope(ctx, target, spec, effect):
    engine = ctx.engine
    previous = getattr(engine, '_typed_critical_scope', None)
    old_spec, old_effect = getattr(ctx, 'attack_spec', None), getattr(ctx, 'attack_effect', None)
    engine._typed_critical_scope = (ctx, target, spec)
    ctx.attack_spec, ctx.attack_effect = spec, effect
    try:
        yield
    finally:
        ctx.attack_spec, ctx.attack_effect = old_spec, old_effect
        engine._typed_critical_scope = previous


def lowest(engine, attacker, target, spec, *, typed_ctx=None):
    answers = ext.run_strict('attack_critical_range', engine, attacker, target, spec)
    frame = getattr(engine, '_typed_critical_scope', None)
    if typed_ctx is None and frame and frame[0].actor is attacker and frame[1] is target and frame[2] is spec:
        typed_ctx = frame[0]
    if typed_ctx is not None:
        answers += ext.run_strict('critical_range', typed_ctx, target)
    if any(type(answer) is not int or not 2 <= answer <= 20 for answer in answers):
        raise ValueError('critical range requires an integer from 2 through 20')
    return min([20, *answers])


def qualifies(engine, attacker, target, spec, roll, intent, threshold):
    """Query additional critical causes only after a confirmed hit; never makes a hit."""
    answers = ext.run_strict('attack_critical_qualification', engine, attacker, target, spec, roll, intent)
    if any(type(answer) is not bool for answer in answers):
        raise ValueError('attack_critical_qualification requires a boolean')
    return (roll.natural_result or 0) >= threshold or any(answers)


def resolve(engine, attacker, target, spec, roll, intent, source, threshold, *, qualified=None):
    critical = qualifies(engine, attacker, target, spec, roll, intent, threshold) if qualified is None else qualified
    cancelled = False
    if critical:
        for answer in ext.iter_strict('critical_cancel', engine, attacker, target, spec, roll, intent):
            if type(answer) is not bool:
                raise ValueError('critical_cancel requires a boolean')
            if answer:
                cancelled = True
                critical = False
                break
    if threshold != 20 or cancelled or critical and (roll.natural_result or 0) < threshold:
        engine._append_event('ATTACK_CRITICAL_RESOLVED', source, actor_id=attacker.entity_id,
                             target_ids=(target.entity_id,), payload={'roll_id': roll.roll_id,
                             'critical_threshold': threshold, 'critical': critical, 'cancelled': cancelled})
    spec['resolved_critical_cancelled'] = cancelled
    # A recipient-specific die belongs to this confirmed hit, after critical
    # prevention and before the original damage is rolled. Providers receive
    # the settled critical result; native critical doubling still owns the roll.
    from .gate2_runtime_models import DiceSpec
    for replacement in ext.iter_strict('confirmed_hit_damage_dice', engine, attacker, target, spec, intent, source, critical):
        if not isinstance(replacement, DiceSpec):
            raise ValueError('Confirmed hit damage requires a DiceSpec replacement')
        spec['damage'] = replacement
    # Consent belongs to the confirmed hit, before its damage roll and defenses.
    bonuses = ext.run_strict('confirmed_hit_roll_bonus', engine, attacker, target, spec, intent, source)
    if any(type(value) is not int for value in bonuses):
        raise ValueError('confirmed_hit_roll_bonus requires an integer')
    # Mixed-size bonus dice join the same packet after critical conversion.
    # Providers roll/record their own dice; defenses and Concentration see the
    # combined damage once. Without a provider the predecessor stream is unchanged.
    extra = ext.run_strict('confirmed_hit_damage_bonus', engine, attacker, target, spec, intent, source, critical)
    if any(type(value) is not int for value in extra):
        raise ValueError('confirmed_hit_damage_bonus requires an integer')
    bonuses += extra
    if bonuses and spec.get('damage') is not None:
        dice = spec['damage']
        spec['damage'] = dice.model_copy(update={'modifier': dice.modifier + sum(bonuses)})
    return critical
