"""Native time-bearing Short Rest command and reusable rest completion notice.

This supplies no healing or resource recovery itself. Each Source Rule owns
its consumer. Existing journeys are unchanged until their controller submits
the explicit short_rest command; combat-phase commands still reject it.
"""
from . import hook, run_strict


@hook('journey_command')
def short_rest(session, actor_id, kind, payload):
    if kind != 'short_rest':
        return None
    from ..journey import require
    actor = session.state['actors'][actor_id]
    require(not payload, 'Short Rest takes one hour; it has no instant shortcut.')
    require(not actor['incapacitated'], 'An incapacitated creature cannot start this rest.')
    session.tick(3600)
    run_strict('journey_rest_completed', session, actor_id, 'short')
    session.emit('SHORT_REST', actor_id, text=f"{actor['name']} finishes a one-hour Short Rest.")
    return True
