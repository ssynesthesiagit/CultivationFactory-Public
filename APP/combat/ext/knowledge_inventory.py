"""Native inventory targets for the five appraisal rows, using existing carry."""
from . import hook,effect
from .knowledge_readings import QUESTIONS,source_of,choice,resolve,QI
from ..knowledge_inventory import options


@hook('journey_native_checkpoint')
def checkpoint(session,engine,aid):
    import json
    return {'knowledge_remaining':json.dumps({key:{**row,'expires_at':max(0,row['expires_at']-int(session.clock()))}
        for key,row in session.state.get('knowledge_reading_deadlines',{}).items() if row['viewer_id']==aid},sort_keys=True)}


@hook('journey_native_restored')
def restore_clock(session,engine):
    import json
    for actor in session.state['actors'].values():
        rows=json.loads(actor.get('encounter_snapshot',{}).get('knowledge_remaining','{}'))
        if rows:session.state.setdefault('knowledge_reading_deadlines',{}).update({key:{**row,
            'expires_at':int(session.clock())+row['expires_at']} for key,row in rows.items()})


@hook('journey_native_resumed')
def resume_clock(session,engine):
    from ..observer_information import READING
    from .effect_durations import parse,parse_round
    rows={}
    for actor in engine.state.actors.values():
        for key,c in actor.conditions.items():
            if c.condition_id!=READING or c.data.get('kind')!='answer' or source_of(engine.action_catalog.get(c.source_definition_id))!=QI:continue
            slot=parse_round(c.expires_on)
            turn=parse(c.expires_on)
            if slot:
                remaining=max(0,(slot[0]-engine.state.round_number)*6)
                if slot[0]==engine.state.round_number and slot[1]>engine.state.current_slot_index:remaining=6
            elif turn and turn[1] in engine.state.actors:
                # A surviving next-turn answer gets the remaining native
                # rounds in seconds, including an unfinished end boundary.
                anchor=engine.state.actors[turn[1]]
                remaining=max(0,turn[2]-anchor.turns_started)*6
                if turn[0]=='end' and turn[2]==anchor.turns_started:remaining=6
            else:continue
            rows[key]={'viewer_id':actor.entity_id,'expires_at':int(session.clock())+remaining}
    session.state['knowledge_reading_deadlines']=rows
    expire_qi(session,engine,int(session.clock()),int(session.clock()))


@hook('candidate_allowed')
def inventory_available(engine,actor,candidate,action):
    if (getattr(action,'parameters',None) or {}).get('typed',{}).get('reading_inventory'):
        return bool(options(engine,actor,action))


@effect('knowledge_inventory_reading')
def examine(ctx,row):
    offered=options(ctx.engine,ctx.actor,ctx.action)
    selected=choice(ctx,'inventory',list(offered),labels={k:r['name'] for k,r in offered.items()},
        prompt=ctx.action.display_name+': choose one actual visible or presented item. The examination costs the printed action and any quoted CP.')
    if not selected:return
    # Revalidate native quantity/location/exposure rather than trusting a label.
    item=options(ctx.engine,ctx.actor,ctx.action).get(selected[0])
    if item is None:raise ValueError('That inventory item is no longer reachable.')
    ctx.damage_cache['reading_inventory']=item
    resolve(ctx,item['owner_id'])


@hook('journey_native_actions')
def native_inventory_actions(session,aid):
    return [a['source_definition_id'] for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('reading_inventory')]


@hook('journey_native_committed')
def qi_clock(session,engine,aid,action,before):
    if source_of(action)!=QI:return
    from ..observer_information import READING
    for iid,c in engine.state.actors[aid].conditions.items():
        if c.condition_id==READING and c.applied_sequence>before:
            session.state.setdefault('knowledge_reading_deadlines',{})[iid]={'viewer_id':aid,'expires_at':int(session.clock())+60}


@hook('journey_native_elapsed')
def expire_qi(session,engine,before,after):
    from .condition_ownership import remove_instance
    for iid,row in list(session.state.get('knowledge_reading_deadlines',{}).items()):
        if row['expires_at']<=after:
            actor=engine.state.actors[row['viewer_id']]
            if iid in actor.conditions:remove_instance(engine,actor,iid,actor.conditions[iid].source_definition_id)
            session.state['knowledge_reading_deadlines'].pop(iid,None)


@hook('journey_native_export')
def combat_qi_clock(session,engine):
    from .effect_durations import SLOT_AT
    from .retained_updates import record_instance_update
    for iid,row in session.state.get('knowledge_reading_deadlines',{}).items():
        actor=engine.state.actors[row['viewer_id']];held=actor.conditions.get(iid)
        remaining=row['expires_at']-int(session.clock())
        if held and remaining>0:
            # Entry creates a new combat at round 1, slot 0. The retained
            # scene may carry a much later round/slot from an earlier fight.
            held.expires_on=f'{SLOT_AT}:{1+(remaining+5)//6}:0'
            record_instance_update(engine,actor,'condition',iid,held)
