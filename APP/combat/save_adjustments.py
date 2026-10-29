"""Phased, numeric post-roll saves, shared by ordinary saves and life_state.

Providers own eligibility, payment and consent. The core preserves the original
die, and death saves retain their natural-1/20 rules regardless of bonuses.
"""
from . import ext


def payable(engine, actor, resource_id, amount, *, source_id):
    """Read-only affordability including the shared prior-event resource veto."""
    return actor.resources.get(resource_id, 0) >= amount and False not in ext.run_strict(
        'cost_available', engine, actor, resource_id, amount, {'source_id': source_id})


def declared_outcome(engine, target, roll):
    """Read-only: the forced outcome already attached to this exact roll, or None.

    A forced save is recorded at draw time (d20 rewrite) and only consumed by
    save_result_outcome after the adjustments. Entity-level overrides are not
    read here: they can outlive the roll that set them.
    """
    forced = (getattr(engine, '_d20_forced_native_saves', None) or {}).get(roll.roll_id)
    if forced and forced.get('target_id') == target.entity_id and forced.get('outcome') in ('success', 'failure'):
        return forced['outcome']
    return None


def adjust(engine, target, ability, dc, roll, source_id, *, context=None, phase=None):
    """Apply optional bonuses before outcome, then failed-save timing bonuses.

    None is the default-inert reply. Providers return a nonnegative integer;
    they must not change the roll or declare success themselves. The after_failure
    window follows the effective outcome: a forced success never opens it, and a
    forced failure opens it even when the numeric total passes.
    """
    context = dict(engine.d20_context() if context is None else context)
    phases = (phase,) if phase is not None else ('before_outcome', 'after_failure')
    declared = declared_outcome(engine, target, roll)
    for phase in phases:
        if phase not in ('before_outcome', 'after_failure'):
            raise ValueError('unknown save adjustment phase')
        if context.get('automatic_failure'):
            break
        if phase == 'after_failure' and (declared == 'success' or (roll.total >= dc and declared != 'failure')):
            break
        for bonus in ext.run_strict('save_roll_adjustment', engine, target, ability,
                                    dc, roll, source_id, phase, context):
            if type(bonus) is not int or bonus < 0:
                raise ValueError('save_roll_adjustment requires a nonnegative integer')
            roll = roll.model_copy(update={'modifier': roll.modifier + bonus,
                                          'total': roll.total + bonus})
    return roll
