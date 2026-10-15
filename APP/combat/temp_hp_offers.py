"""General opt-in additions to positive Temporary HP offers before interception."""


def offered_bonus(engine, subject, amount, source_id=None, source_actor_id=None, *, consume):
    if amount <= 0:
        return 0
    from . import ext
    total = 0
    for answer in ext.run_checkpoint('temp_hp_offered_bonus', engine, subject, amount,
                                     source_id, source_actor_id, consume=consume):
        if answer is None:
            continue
        if type(answer) is not int or answer < 0:
            raise ext.CheckpointError('Temporary HP offer bonuses must be nonnegative integers')
        total += answer
    return total
