"""Default-inert settlement of actual typed activation damage.

Public settle_activation(ctx) is called once after effects, before post-use
consumers. Explicit typed.qi_powered is an authored activation classification;
payment, names and damage types never establish it. The journal window proves
actual recipients and prevents an unrelated nested source borrowing the event.
No technique_resolution_enabled subscriber means no event or behavior change.
"""
from . import ext


def settle_activation(ctx):
    if not any(ext.run_strict('technique_resolution_enabled',ctx)):
        return None
    start = getattr(ctx,'technique_event_start',None)
    if type(start) is not int:
        return None
    own_events = [event for event in ctx.engine.events[start:]
                  if event.source_definition_id==ctx.source and event.actor_id==ctx.actor.entity_id]
    packets = [event for event in own_events
               if event.event_type=='DAMAGE_COMMITTED' and event.actor_id==ctx.actor.entity_id
               and event.source_definition_id==ctx.source
               and int(event.payload.get('hp_damage') or 0)+int(event.payload.get('temporary_hp_absorbed') or 0)>0]
    receipt = {'activation_id':str(ctx.intent.intent_id),'owner_id':ctx.actor.entity_id,
               'source_id':ctx.source,'qi_powered':int(ctx.typed.get('qi_powered') is True),
               'effect_origin':[{'event_sequence':event.sequence,'event_type':event.event_type,'target_ids':list(event.target_ids)}
                    for event in own_events if event.event_type in ('DAMAGE_COMMITTED','CONDITION_APPLIED','MODIFIER_APPLIED','ZONE_CREATED','MOVEMENT_COMMITTED','OBJECT_UPDATED')],
               'damage_origin':[{'event_sequence':event.sequence,'target_ids':list(event.target_ids),
                   'amount':int(event.payload.get('hp_damage') or 0)+int(event.payload.get('temporary_hp_absorbed') or 0)}
                   for event in packets]}
    ctx.engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=ctx.actor.entity_id,
        payload={'activation_settlement':receipt})
    ext.run_strict('technique_resolved',ctx,receipt)
    return receipt
