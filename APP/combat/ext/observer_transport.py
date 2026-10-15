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


@hook('state_event')
def retain_source_privacy(engine,event):
    """Record private source instances at their committed creation, before expiry."""
    if event.event_type!='CONDITION_APPLIED':return
    from ..observer_information import record_private_condition
    private={'condition:typed.thread_listen','condition:typed.adorn_memory','condition:typed.detected_thread','condition:typed.fact_consent_admission'}
    for aid in event.target_ids:
        holder=engine.state.actors.get(aid)
        if holder is None:continue
        for condition in holder.conditions.values():
            if condition.applied_sequence==event.sequence and condition.condition_id in private:
                record_private_condition(engine,holder,condition)
