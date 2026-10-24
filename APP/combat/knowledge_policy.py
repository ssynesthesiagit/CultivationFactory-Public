"""Saved knowledge policy shared by AI restraint, mount guard and journal projection.

The creation event selects the policy. Loaders replace constructor events with
saved events. This does not change the observation schema or grant personal
knowledge from another creature; that requires a general observation seam.
"""
KEY = 'ai_knowledge_policy'
VERSION = 1


def saved_policy(events):
    for event in reversed(events):
        kind = event.event_type if hasattr(event, 'event_type') else event['event_type']
        payload = event.payload if hasattr(event, 'payload') else event.get('payload', {})
        if kind == 'MATCH_CREATED' and KEY in payload:
            value = payload[KEY]
            if type(value) is not int or value not in (0, VERSION):
                raise ValueError('Unknown saved AI knowledge policy')
            return value
    return 0


def enabled(engine):
    return saved_policy(engine.events) == VERSION


def roster(engine, viewer):
    """Known geometry when enabled; the full roster for the zero policy.

    The existing knowledge projection supplies located or remembered positions.
    Personal versus team observation storage requires a separate general seam.
    """
    if enabled(engine):
        from .target_knowledge import actors_for
        return actors_for(engine, viewer)
    return list(engine.state.actors.values())
