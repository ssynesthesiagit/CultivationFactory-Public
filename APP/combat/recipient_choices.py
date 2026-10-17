"""Transactional subset selection before technique target reactions.

Consumers use before_target_reactions(ctx), normally an opted-in effect plus
the existing choice transport. They may replace ctx.targets with a unique
subset of the already filtered live ActorState objects, never widen eligibility.
Every target reaction, save and effect receives that final action-local roster.
No provider means no work. No transient roster is written into saved state.
"""


def apply(ctx):
    from . import ext
    if not ext.has('before_target_reactions'):
        return
    eligible = {actor.entity_id: actor for actor in ctx.targets}
    if ext.run_checkpoint('before_target_reactions', ctx):
        raise ext.CheckpointError('Recipient choice hooks must return None')
    if (not isinstance(ctx.targets, list) or any(eligible.get(getattr(actor, 'entity_id', None)) is not actor
            or not actor.active for actor in ctx.targets)
            or len({actor.entity_id for actor in ctx.targets}) != len(ctx.targets)):
        raise ext.CheckpointError('Recipient choices must be a unique subset of eligible creatures')
    ctx.target = ctx.targets[0] if len(ctx.targets) == 1 else None
