"""Source-recorded journey checks using native deterministic dice.

The table owner supplies a source DC/context through fact_consent_admission's
world path. The named creature resolves that actual check once. A player/model
cannot choose its own DC or turn a subjective declaration into a mechanical
check. Modifiers come from the journey's immutable native sheet projection.
"""
from . import hook,query
from ..journey import require,integer
from ..gate2_rolls import DeterministicRollAuthority

SOURCE='world:journey_check'


def validate(session,aid,payload):
    require(set(payload)=={'ability','skill','dc','reason','context'},'Declare the ability, skill, source DC, reason and context.')
    ability=payload['ability'];skill=payload['skill'];context=payload['context']
    require(ability in ('STR','DEX','CON','INT','WIS','CHA') and isinstance(skill,str)
            and integer(payload['dc']) and isinstance(payload['reason'],str) and payload['reason'].strip()
            and isinstance(context,dict),'Checks need a known ability, explicit source DC and a source reason.')
    require(set(context)<= {'purpose','region_id','route_kind'} and all(isinstance(v,str) for v in context.values()),'Unknown journey check context.')
    if 'route_kind' in context:
        require(context.get('purpose')=='navigation' and context['route_kind'] in ('river','canal','flood','delta','swamp','coastline','water_route'),
                'Record an actual river, canal, flood, delta, swamp, coastline or water route for a navigation check.')
    if 'region_id' in context:
        require(any(r['id']==context['region_id'] for r in session.grid.route_regions),'Choose a mapped route region.')
    bundle=session.state['actors'][aid]['bundle']
    modifier=bundle.get('skills',{}).get(skill,bundle.get('journey_check_modifiers',{}).get(ability))
    require(type(modifier) is int,'This sheet has no recorded modifier for that check.')
    return modifier


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source==SOURCE and kind=='ability_check':
        return {'authority':'table_owner','value_type':'document','maximum_seconds':86400,
                'description':'A GM calls for one source-defined ability check; the creature owns its response.'}


@hook('world_fact_declared')
def requested(session,record):
    if record['source']==SOURCE:
        require(record['kind']=='ability_check','Unknown world check kind.')
        validate(session,record['subject'],record['value'])


def pending(session,aid):
    from ..fact_consent_admission import KEY,read
    result=[]
    done={e.get('check_receipt_id') for e in session.state['events'] if e['kind']=='CHECK_ROLLED'}
    for record in session.state.get(KEY,()):
        if record['source']!=SOURCE or record['subject']!=aid or record['receipt_id'] in done:continue
        current=read(session,SOURCE,aid,'ability_check',record['scope'],aid)
        if current and current['receipt_id']==record['receipt_id']:result.append(current)
    return result


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return None
    return [{'id':'check:'+r['receipt_id'],'kind':'ability_check','payload':{'check_id':r['receipt_id']},
        'label':r['value']['reason']+': '+r['value']['ability']+' ('+r['value']['skill']+'), source DC '+str(r['value']['dc'])+'.'}
        for r in pending(session,aid)] or None


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind!='ability_check':return None
    require(set(payload)=={'check_id'},'Resolve one actual GM-recorded check; actors cannot supply a DC.')
    record=next((r for r in pending(session,aid) if r['receipt_id']==payload['check_id']),None)
    require(record is not None,'That check is not pending for this creature.')
    spec=record['value'];modifier=validate(session,aid,spec)
    require(not session.state['actors'][aid]['incapacitated'],'An incapacitated creature cannot attempt this check.')
    modes=[r for r in query('journey_check_mode',session,aid,spec['ability'],spec['skill'],spec['context']) if r]
    require(all(r in ('ADVANTAGE','DISADVANTAGE') for r in modes),'Check modes must be Advantage or Disadvantage.')
    mode='NORMAL' if len(set(modes))!=1 else modes[0]
    roller=DeterministicRollAuthority(session.state['journey_id'],counter=session.state.get('roll_counter',0))
    roll=roller.d20(modifier=modifier,actor_id=aid,reason=spec['reason'],mode=mode)
    session.state['roll_counter']=roller.counter
    session.emit('CHECK_ROLLED',aid,roll=roll.model_dump(mode='json'),ability=spec['ability'],skill=spec['skill'],
        context=spec['context'],dc=spec['dc'],success=int(roll.total>=spec['dc']),check_receipt_id=record['receipt_id'])
    return True
