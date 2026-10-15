"""Cloud Shroud outside combat through the shared native scene resolver.

The existing Weather Sign save/effect provider is the only implementation of
creature mechanics. Real source-turn end commands repeat saves; sixty elapsed
seconds end the actual concentration copy/condition. Object responses also run
through the same native object resolver and stay physical after weather ends.
"""
from . import hook
from .weather_knowledge import SHROUD


@hook('journey_native_actions')
def actions(session,aid):
    return [a['source_definition_id'] for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('source')==SHROUD]


@hook('journey_native_committed')
def clocks(session,engine,aid,action,before):
    if action.parameters.get('typed',{}).get('source')!=SHROUD:return
    from .weather_shroud import SHROUD as CONDITION
    deadlines=session.state.setdefault('weather_shroud_deadlines',{})
    expires=int(session.clock())+60
    for target in engine.state.actors.values():
        for iid,held in target.conditions.items():
            if held.condition_id==CONDITION and held.applied_sequence>before:
                deadlines[iid]={'expires_at':expires,'subject_id':target.entity_id,'owner_id':aid,
                    'source_id':held.source_definition_id,'started_sequence':held.data.get('concentration_started_sequence',0) or 0}
    for oid,obj in engine.state.objects.items():
        shroud=obj.component.get('cloud_shroud')
        if shroud and shroud['started_sequence']>before:
            deadlines[oid]={'expires_at':expires,'subject_id':oid,'owner_id':aid,
                'source_id':shroud['source_id'],'started_sequence':shroud['started_sequence']}


@hook('journey_native_elapsed')
def expire(session,engine,before,after):
    from ..concentration import end_copy
    from .condition_ownership import remove_instance
    from .weather_shroud import SHROUD as CONDITION
    deadlines=session.state.get('weather_shroud_deadlines',{})
    for key,row in list(deadlines.items()):
        if row['expires_at']>after:continue
        owner=engine.state.actors.get(row['owner_id'])
        subject=engine.state.actors.get(row['subject_id'])
        held=subject.conditions.get(key) if subject else None
        obj=engine.state.objects.get(row['subject_id'])
        shroud=obj.component.get('cloud_shroud') if obj else None
        present=held is not None and held.condition_id==CONDITION or shroud is not None and shroud['started_sequence']==row['started_sequence']
        if present:
            if owner and row['started_sequence']:end_copy(engine,owner,row['started_sequence'],'DURATION_ENDED')
            if held and key in subject.conditions:remove_instance(engine,subject,key,row['source_id'])
            if obj and engine.state.objects[obj.object_id].component.get('cloud_shroud')==shroud:
                component=dict(engine.state.objects[obj.object_id].component);component.pop('cloud_shroud',None)
                engine._update_object(engine.state.objects[obj.object_id].model_copy(update={'component':component}),row['source_id'],row['owner_id'])
            session.emit('WEATHER_SHROUD_EXPIRED',row['owner_id'],subject=row['subject_id'],expires_at=row['expires_at'])
        deadlines.pop(key,None)


@hook('journey_native_export')
def combat_clocks(session,engine):
    """Transfer actual remaining seconds to native round/slot duration clocks."""
    from .retained_updates import record_instance_update
    for key,row in session.state.get('weather_shroud_deadlines',{}).items():
        remaining=row['expires_at']-int(session.clock())
        if remaining<=0:continue
        target=engine.state.actors.get(row['subject_id'])
        held=target.conditions.get(key) if target else None
        if held:
            held.data={**held.data,'expiry_round':1+(remaining+5)//6,'expiry_slot':0}
            record_instance_update(engine,target,'condition',key,held)
        obj=engine.state.objects.get(row['subject_id'])
        if obj and obj.component.get('cloud_shroud',{}).get('started_sequence')==row['started_sequence']:
            component={**obj.component,'cloud_shroud':{**obj.component['cloud_shroud'],'expiry_round':1+(remaining+5)//6,'expiry_slot':0}}
            engine._update_object(obj.model_copy(update={'component':component}),row['source_id'],row['owner_id'])
