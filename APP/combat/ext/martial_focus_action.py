"""Owner ruling: regain Martial Focus as an Action.

One generic catalog action, system:martial_focus.regain. Any actor holding a Martial Focus pool may spend
its Action to restore exactly 1 Focus while below maximum. While Focus is held the action is refused, and the
compact menu's header explains that with source_unavailable. Uses existing match_start, additional_actions,
candidate_allowed, candidate_unavailability, source_unavailable hooks and one typed effect; adds no hook point.
"""
from . import effect, hook, note

REGAIN = 'system:martial_focus.regain'
FOCUS = 'resource:core.martial_focus'
HELD = 'You already hold Martial Focus.'
NO_POOL = 'You have no Martial Focus to regain.'


def _has_pool(actor) -> bool:
    return actor.resource_maximums.get(FOCUS, 0) > 0


def _below_max(actor) -> bool:
    return actor.resources.get(FOCUS, 0) < actor.resource_maximums.get(FOCUS, 0)


@hook('match_start')
def install_regain(engine):
    from ..gate2_runtime_models import ActionDefinition
    # The initial roster during saved-fight reconstruction can differ from the
    # loaded state. Install the definition independently; offer_regain gates actors.
    engine.action_catalog[REGAIN] = ActionDefinition(
        source_definition_id=REGAIN, display_name='Regain Martial Focus', owner_id='*',
        economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={
            'typed': {'effects': [{'type': 'martial_focus_regain'}], 'numbers': {}, 'riders': []},
            'description': 'Spend your Action to regain 1 Martial Focus. You must be below your maximum.'})


@hook('additional_actions')
def offer_regain(engine, actor):
    if REGAIN not in engine.action_catalog or not actor.active or not _has_pool(actor):
        return []
    return [REGAIN]


@hook('candidate_allowed')
def regain_allowed(engine, actor, candidate, action):
    if action is None or action.source_definition_id != REGAIN:
        return None
    return bool(_has_pool(actor) and _below_max(actor))


@hook('candidate_unavailability')
def regain_refused(engine, actor, candidate, action):
    if action is None or action.source_definition_id != REGAIN:
        return None
    if not _has_pool(actor):
        return NO_POOL
    return None if _below_max(actor) else HELD


@hook('source_unavailable')
def regain_header_refused(engine, actor, action):
    # A compact-menu header is offered before candidate_allowed runs; this source-wide refusal explains it.
    if action is None or action.source_definition_id != REGAIN:
        return None
    if not _has_pool(actor):
        return NO_POOL
    return None if _below_max(actor) else HELD


@effect('martial_focus_regain')
def regain(ctx, row):
    engine, actor = ctx.engine, ctx.actor
    if not _has_pool(actor) or not _below_max(actor):
        ctx.rider(HELD if _has_pool(actor) else NO_POOL)
        return
    before = actor.resources.get(FOCUS, 0)
    engine._gain_resource(actor, FOCUS, 1, ctx.source)
    if actor.resources.get(FOCUS, 0) > before:
        note(engine, ctx.source, actor, f'{actor.display_name} regains 1 Martial Focus with an Action.')
