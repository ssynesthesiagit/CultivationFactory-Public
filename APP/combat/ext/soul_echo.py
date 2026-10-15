"""Soul-Echo Hearing's Action/check/choose-one procedure on admitted sources.

Occult facts and investigation DCs are scene authority, never invented from an
actor's name, alignment or hidden plans. A soul_echo source-object profile
declares dc and facts; creature profiles also declare creature_id. The native
creature route has 60-foot range; the investigated-place object route adds no
unprinted numeric range. All five questions remain available after success.
"""
from . import hook, effect
from .. import source_objects

FEATURE='TAL_SOUND_SOUL_ECHO_HEARING'
PROFILE='soul_echo'
QUESTIONS={
    'possession':'Whether the creature is possessed, bound to a spirit, or haunted',
    'coercion':'Whether magic or a spirit forced a spoken statement',
    'empowered_name':'Whether a name, title, vow, or mantra was recently used with power',
    'residual_spirit':'Whether a ghost, echo, or lingering scream remains here',
    'silence_origin':'Whether Silence comes from nature, magic, a spirit, or a Domain',
}
RESULT='condition:typed.soul_echo_knowledge'


def qualified(obj):
    data=source_objects.profile(obj,PROFILE)
    return data if not obj.destroyed and type(data.get('dc')) is int and data['dc']>=0 else None


def creature_source(engine,target_id):
    rows=[(obj,qualified(obj)) for obj in engine.state.objects.values()
          if qualified(obj) and qualified(obj).get('creature_id')==target_id]
    if len(rows)>1:
        raise ValueError('Soul-Echo Hearing needs one controlling investigation source for this creature')
    return rows[0] if rows else None


@hook('compile_action')
def creature_action(action,info):
    typed=(action.parameters or {}).get('typed') or {}
    if typed.get('source')!=FEATURE or FEATURE not in info['owned_ids']:
        return None
    typed={**typed,'effects':[{'type':'soul_echo_check'}],'riders':[],
           'coverage':'CORE_WITH_RIDERS'}
    typed.pop('gm_text',None)
    place=(action.parameters or {}).get('soul_echo_place')
    return action.model_copy(update={'target_kind':'OBJECT' if place else 'ANY_CREATURE',
        'range_ft':None if place else 60,'reach_ft':None,
        'display_name':'Soul-Echo Hearing: investigate '+('a place' if place else 'a creature'),
        'parameters':{**action.parameters,'typed':typed,'inert':False}})


@hook('compile_actions')
def place_action(info):
    out=[]
    if FEATURE not in info['owned_ids']:
        return None
    for action in info['actions']:
        typed=(action.parameters or {}).get('typed') or {}
        if typed.get('source')==FEATURE:
            out.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'.place',
                'display_name':'Soul-Echo Hearing: investigate a place','target_kind':'OBJECT','range_ft':None,
                'parameters':{**action.parameters,'soul_echo_place':1}}))
    return out or None


@hook('object_targets')
def place_targets(engine,actor,action):
    if not (getattr(action,'parameters',None) or {}).get('soul_echo_place'):
        return None
    return [obj.object_id for obj in engine.state.objects.values()
            if qualified(obj) and not qualified(obj).get('creature_id')]


@hook('candidate_allowed')
def check_source(engine,actor,candidate,action):
    typed=(getattr(action,'parameters',None) or {}).get('typed') or {}
    if typed.get('source')!=FEATURE:
        return None
    if (action.parameters or {}).get('soul_echo_place'):
        return all(t in engine.state.objects and qualified(engine.state.objects[t])
                   for t in candidate.target_ids)
    return None


@hook('technique_declared')
def needs_investigation_input(engine,actor,action,candidate,intent):
    typed=(action.parameters or {}).get('typed') or {}
    if typed.get('source')!=FEATURE or (action.parameters or {}).get('soul_echo_place'):
        return None
    if any(creature_source(engine,t) is None for t in candidate.target_ids):
        return {'cancel':True,'source_id':FEATURE,
            'label':'Soul-Echo Hearing needs a scene investigation DC for this creature before it can roll; no Action or resources are spent.'}


def investigate(ctx,obj,data,label):
    from .ability_source import cultivation_check_detail
    from .needle import ask,checkpoint_id
    roll,success=cultivation_check_detail(ctx.engine,ctx.actor,ctx.numbers,data['dc'],ctx.source,'Sound Check')
    if not success:
        return
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'SOUL_ECHO_FACT',obj.object_id,ctx.actor.entity_id),
        ctx.actor,'choice:needle.soul_echo_fact',list(QUESTIONS),labels=QUESTIONS,name='Soul-Echo Hearing',
        prompt=f'Soul-Echo Hearing: the Sound Check succeeded for {label}. Choose one question; this does not read thoughts or automatically reveal lies.')
    if picked:
        key=picked[0]
        value=(data.get('facts') or {}).get(key)
        if type(value) not in (int,str):
            ctx.rider('Soul-Echo Hearing: the admitted source does not establish the selected fact; no answer is inferred.')
            return
        ctx.engine._apply_condition(ctx.actor,RESULT,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'question':key,'value':str(value),'source_object':obj.object_id,
                  'label':f'Soul-Echo Hearing learned: {value}. Recorded information, not a combat bonus.'})


@effect('soul_echo_check')
def creature_check(ctx,row):
    if ctx.target is None:
        return
    source=creature_source(ctx.engine,ctx.target.entity_id)
    if source is None:
        raise ValueError('Soul-Echo Hearing requires an admitted investigation DC and source facts')
    investigate(ctx,*source,ctx.target.display_name)


@hook('object_action')
def place_check(engine,actor,action,obj,candidate,intent):
    if not (action.parameters or {}).get('soul_echo_place'):
        return None
    from ..typed_executor import Context
    data=qualified(obj)
    if data is None:
        raise ValueError('This place has no admitted Soul-Echo investigation source')
    ctx=Context(engine,actor,action,intent,action.parameters['typed'],[],None,{})
    investigate(ctx,obj,data,'the investigated place')
    return True
