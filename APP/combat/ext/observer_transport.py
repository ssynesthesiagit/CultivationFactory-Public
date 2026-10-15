"""Private condition history projection for the public observer contract."""
from . import hook
from ..observer_information import READING


@hook('presentation_hidden_conditions')
def active_private_readings(engine,actor):
    return [iid for iid,c in actor.conditions.items() if c.condition_id==READING]


@hook('presentation_hidden_history_conditions')
def historical_privacy(events):
    hidden=[]
    for event in events:
        kind=event.get('event_type') if isinstance(event,dict) else event.event_type
        payload=event.get('payload',{}) if isinstance(event,dict) else event.payload
        if kind=='SOURCE_PRIVACY_RECORDED':hidden.extend(payload.get('private_condition_ids',[]))
    return hidden or None
