"""Encumbered's native condition lifecycle, independent of any movement talent.

Inventory changes use carry.refresh; direct typed condition applications must
replace the already-granted allowance too. Both use the same live Speed and
movement_budget.speed_changed contract, including cold event replay.
"""
from . import hook
from ..carry import ENCUMBERED
from ..movement_budget import speed_changed
from ..read_queries import fresh_reads


@hook('state_event')
def encumbered_applied(engine, event):
    if event.event_type != 'CONDITION_APPLIED' or event.payload.get('condition_id') != ENCUMBERED:
        return
    for actor_id in event.target_ids:
        actor = engine.state.actors.get(actor_id)
        if actor is None:
            continue
        previous = actor.model_copy(update={'conditions': {
            iid: condition for iid, condition in actor.conditions.items()
            if iid != event.payload.get('instance_id')}})
        with fresh_reads():
            change = engine._effective_speed(actor) - engine._effective_speed(previous)
        # A real over-capacity load was already capped before the condition
        # landed: this difference is zero and refresh owns its prior-load delta.
        speed_changed(engine, actor, change, event.source_definition_id, reason='load')
