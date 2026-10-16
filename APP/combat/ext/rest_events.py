"""Short rests on the existing native journey clock, outside bound combat.

JourneySession.command calls journey_command; JourneySession.menu calls
journey_options. This producer validates an explicit empty-payload short_rest,
advances that session's elapsed clock by one hour (the game's existing
services.factory_dm_v0.gameplay short-rest qualification), then strictly calls
journey_short_rest(session, actor_id). A subscriber owns its own recovery;
this producer invents no resource pool, HP recovery, permission or side clock.
Water Return consumes this notification to remove the resting recipient's
Restorative Waters ledger from its supported encounter snapshot. With no
subscriber, only elapsed time and the ordinary rest event change. Automatic
seats never start a rest merely because this explicit option exists.
"""
from . import hook, run_strict
from ..journey import require


@hook('journey_options')
def short_rest_option(session, actor_id):
    actor = session.state['actors'][actor_id]
    if session.state['phase'] != 'travel' or actor['incapacitated']:
        return None
    return [{'id': 'short_rest', 'kind': 'short_rest', 'payload': {}, 'auto_select': 0,
             'label': f'{actor["name"]}: complete a one-hour Short Rest; renew supported short-rest uses. No CP cost.'}]


@hook('journey_command')
def complete_short_rest(session, actor_id, kind, payload):
    if kind != 'short_rest':
        return None
    require(not payload, 'A Short Rest takes one hour; it has no instant shortcut.')
    require(not session.state['actors'][actor_id]['incapacitated'], 'An incapacitated creature cannot start this rest.')
    session.tick(3600)
    run_strict('journey_short_rest', session, actor_id)
    session.emit('SHORT_REST', actor_id,
                 text=f'{session.state["actors"][actor_id]["name"]} finishes a one-hour Short Rest.')
    return True
