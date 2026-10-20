"""Cloud Shroud outside combat through the shared native scene resolver.

The existing Weather Sign save/effect provider is the only implementation of
creature mechanics. Real source-turn end commands repeat saves; sixty elapsed
seconds end the actual concentration copy/condition. Object responses also run
through the same native object resolver and stay physical after weather ends.
"""
from . import hook
from .weather_knowledge import SHROUD


@hook('journey_native_checkpoint')
def checkpoint(session,engine,aid):
    import json
    rows={key:{**row,'expires_at':max(0,row['expires_at']-int(session.clock()))}
        for key,row in session.state.get('weather_shroud_deadlines',{}).items()
        if row['subject_id']==aid or row['owner_id']==aid}
    return {'weather_remaining':json.dumps(rows,sort_keys=True)}


@hook('journey_native_restored')
def restore_clocks(session,engine):
    import json
    for outside in session.state['actors'].values():
        rows=json.loads(outside.get('encounter_snapshot',{}).get('weather_remaining','{}'))
        if rows:session.state.setdefault('weather_shroud_deadlines',{}).update({key:{**row,
            'expires_at':int(session.clock())+row['expires_at']} for key,row in rows.items()})


@hook('journey_native_resumed')
def resume_clocks(session,engine):
    """Only effects surviving the terminal fight receive an elapsed deadline."""
    from .weather_shroud import SHROUD as CONDITION
    rows={}
    def add(key,subject,owner,source,sequence,data):
        remaining=max(0,(int(data['expiry_round'])-engine.state.round_number)*6)
        if data['expiry_round']==engine.state.round_number and data.get('expiry_slot',0)>engine.state.current_slot_index:
            remaining=6
        rows[key]={'expires_at':int(session.clock())+remaining,'subject_id':subject,'owner_id':owner,
            'source_id':source,'started_sequence':sequence}
    for actor in engine.state.actors.values():
        for key,c in actor.conditions.items():
            if c.condition_id==CONDITION and 'expiry_round' in c.data:
                add(key,actor.entity_id,c.source_actor_id,c.source_definition_id,c.data.get('concentration_started_sequence',0) or 0,c.data)
    for key,obj in engine.state.objects.items():
        shroud=obj.component.get('cloud_shroud')
        if shroud:add(key,key,shroud['owner_id'],shroud['source_id'],shroud['started_sequence'],shroud)
    session.state['weather_shroud_deadlines']=rows
    expire(session,engine,int(session.clock()),int(session.clock()))


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
    from ..concentration import end_copy,copies
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
        present=(held is not None and held.condition_id==CONDITION
            or shroud is not None and shroud['started_sequence']==row['started_sequence']
            or owner is not None and row['started_sequence'] in copies(owner,row['source_id']))
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
