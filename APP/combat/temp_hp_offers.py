"""General opt-in additions to positive Temporary HP offers before interception."""


def offered_bonus(engine, subject, amount, source_id=None, source_actor_id=None, *, consume, original_amount=None, offer_cap=None):
    from . import ext
    total = 0
    for answer in (ext.run_checkpoint('temp_hp_offered_bonus', engine, subject, amount,
                                     source_id, source_actor_id, consume=consume) if amount > 0 else ()):
        if answer is None:
            continue
        if type(answer) is not int or answer < 0:
            raise ext.CheckpointError('Temporary HP offer bonuses must be nonnegative integers')
        total += answer
    actor = engine.state.actors.get(source_actor_id)
    if actor is not None and offer_cap != 0:
        from .support_values import offered_bonus as support_bonus
        total += support_bonus(engine, actor, subject, source_id, 'temporary_hp',
                               amount if original_amount is None else original_amount, consume=consume)
    return total
