"""Saved knowledge policy shared by AI restraint, mount guard and journal projection.

Only new fights opt in. Loaders replace constructor events with saved events;
continuations preserve the source policy. This does not change the observation
schema or grant personal knowledge from another creature (that is a lock round).
"""
KEY = 'ai_knowledge_policy'
VERSION = 1


def saved_policy(events):
    for event in reversed(events):
        kind = event.event_type if hasattr(event, 'event_type') else event['event_type']
        payload = event.payload if hasattr(event, 'payload') else event.get('payload', {})
        if kind in {'MATCH_CREATED', 'SAVED_FIGHT_CONTINUED'} and KEY in payload:
            value = payload[KEY]
            if type(value) is not int or value not in (0, VERSION):
                raise ValueError('Unknown saved AI knowledge policy')
            return value
    return 0


def enabled(engine):
    return saved_policy(engine.events) == VERSION


def roster(engine, viewer):
    """Known geometry for new fights; historical decision geometry otherwise.

    The existing knowledge projection supplies located or remembered positions.
    Personal versus team observation storage remains a separate compatibility task.
    """
    if enabled(engine):
        from .target_knowledge import actors_for
        return actors_for(engine, viewer)
    return list(engine.state.actors.values())
