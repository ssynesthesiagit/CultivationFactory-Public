"""Bind new-fight exploration policy in the existing genesis event."""
from . import hook
from ..ai_search import KEY, VERSION, saved_policy


@hook('match_start')
def record_search_policy(engine):
    for event in engine.events:
        if event.event_type == 'MATCH_CREATED':
            event.payload[KEY] = VERSION
            return


@hook('target_observation_refresh')
def renew_search_observations(engine):
    """Search orders sightings against travel, including an unchanged square."""
    return True if saved_policy(engine.events) == VERSION else None
