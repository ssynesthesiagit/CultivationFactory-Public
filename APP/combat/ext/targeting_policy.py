"""Bind the global owner targeting policy in genesis for saved-fight replay.

This is a general rules policy, not an ability. The existing MATCH_CREATED
event carries its integers; no extra event, roll, state field or expiry is added.
The persistence loaders replace constructor events with saved events, so a load
never substitutes today's settings for a fight's recorded settings.
"""
from . import hook
from .. import targeting


@hook('match_start')
def record_targeting_policy(engine):
    for event in engine.events:
        if event.event_type == 'MATCH_CREATED':
            from ..knowledge_policy import KEY, VERSION
            event.payload[KEY] = VERSION
            event.payload['targeting_policy'] = {key: targeting.rules().get(key, 0) for key in targeting.POLICY_KEYS}
            return
