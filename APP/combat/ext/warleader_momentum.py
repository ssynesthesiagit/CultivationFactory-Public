"""Momentum acquisition and lifecycle; Warleader remains its sole gain provider."""
from . import hook

SOURCE = 'WARLEADER_BASE_MOMENTUM_MARKS'
POOL = 'resource:named.momentum_mark'


@hook('compile_resources')
def acquire(info):
    if SOURCE not in info.get('owned_ids', ()) and 'tianxia.sphere.warleader' not in info.get('spheres', ()):
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=POOL, initial=0, maximum=int(info['pb']))]


@hook('state_event')
def end_combat(engine, event):
    if event.event_type != 'MATCH_ENDED':
        return
    for actor in engine.state.actors.values():
        remaining = int(actor.resources.get(POOL, 0))
        if remaining:
            engine._spend_resource(actor, POOL, remaining, SOURCE)
