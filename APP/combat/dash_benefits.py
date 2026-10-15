"""A Dash can be taken while its movement benefit is denied.

General native/typed Dash checkpoint, separate from cannot-take-Dash legality.
No subscriber changes no movement, flight accounting or native Dash flags.
"""
from . import ext

def allowed(engine,actor,source):
    replies=ext.run_checkpoint('dash_benefit_allowed',engine,actor,source)
    if any(type(reply) is not bool for reply in replies):
        raise ext.CheckpointError('dash_benefit_allowed requires bool or None')
    return not any(reply is False for reply in replies)
