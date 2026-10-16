"""Native inventory targets for the five appraisal rows, using existing carry."""
from . import hook,effect
from .knowledge_readings import QUESTIONS,source_of,choice,resolve,QI
from ..knowledge_inventory import options


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
    from .effect_durations import round_token
    from .retained_updates import record_instance_update
    for iid,row in session.state.get('knowledge_reading_deadlines',{}).items():
        actor=engine.state.actors[row['viewer_id']];held=actor.conditions.get(iid)
        remaining=row['expires_at']-int(session.clock())
        if held and remaining>0:
            held.expires_on=round_token(engine,(remaining+5)//6)
            record_instance_update(engine,actor,'condition',iid,held)
