"""Transactional subset selection before technique target reactions.

Consumers use before_target_reactions(ctx), normally an opted-in effect plus
the existing choice transport. They may replace ctx.targets with a unique
subset of the already filtered live ActorState objects, never widen eligibility.
An eligible_recipients provider can first resolve an opted-in multi-target
action's legal pool from its initial menu aim; the provider owns eligibility.
Every target reaction, save and effect receives that final action-local roster.
No provider means no work. No transient roster is written into saved state.
"""


def apply(ctx):
    from . import ext
    if not ext.has('before_target_reactions') and not ext.has('eligible_recipients'):
        return
    # An owning provider may supply the legal pool for a multi-target action
    # whose menu candidate names only its initial aim. Resolve it before any
    # subset selector or target-specific reaction sees the roster.
    pools = [pool for pool in ext.run_strict('eligible_recipients', ctx) if pool is not None]
    if len(pools) > 1:
        raise ext.CheckpointError('Only one provider may own the recipient pool')
    if pools:
        pool = pools[0]
        if (not isinstance(pool, list) or any(ctx.engine.state.actors.get(getattr(actor, 'entity_id', None)) is not actor
                or not actor.active or actor.entity_id in ctx.missed_target_ids for actor in pool)
                or len({actor.entity_id for actor in pool}) != len(pool)):
            raise ext.CheckpointError('Recipient pools must contain unique eligible live creatures')
        ctx.targets = pool
    eligible = {actor.entity_id: actor for actor in ctx.targets}
    if ext.run_checkpoint('before_target_reactions', ctx):
        raise ext.CheckpointError('Recipient choice hooks must return None')
    if (not isinstance(ctx.targets, list) or any(eligible.get(getattr(actor, 'entity_id', None)) is not actor
            or not actor.active for actor in ctx.targets)
            or len({actor.entity_id for actor in ctx.targets}) != len(ctx.targets)):
        raise ext.CheckpointError('Recipient choices must be a unique subset of eligible creatures')
    ctx.target = ctx.targets[0] if len(ctx.targets) == 1 else None
