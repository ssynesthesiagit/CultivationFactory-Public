"""Elapsed-time information procedures through the native journey command seam.

Travel decisions specify question/check choices as structured parameters. The
scene owner supplies external facts at creation; the acting player chooses what
to examine. Only the reader receives a knowledge property; public events carry
no answer. No combat turn or free rest is manufactured by an examination.
"""
from copy import deepcopy
from . import hook
from .knowledge_readings import QUESTIONS,LABELS,KINDS,questions_for,higher_realm,answer_value,QI,TRACE,VESSEL,VENOM,METAL,SKY
from .weather_knowledge import weather_answers
from ..encounter_sources import facts
from ..journey import require


def owned(session, aid, source):
    return any((a.get('parameters',{}).get('typed') or {}).get('source')==source
        for a in session.state['actors'][aid]['bundle']['action_catalog'])


def reading_action(session, aid, source):
    return next((a for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('source')==source
        and a.get('parameters',{}).get('typed',{}).get('numbers',{}).get('ability_mods')),None)


def source_cl(session,aid,source):
    return next((a.get('parameters',{}).get('typed',{}).get('numbers',{}).get('cl')
        for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('source')==source),None)


def check_choices(session, aid, source, subject):
    if source==QI:
        return ['cultivation']
    choices=['INT:Arcana','INT:Investigation','WIS:Insight','cultivation'] if source==TRACE else [
        a+':'+skill for a in ('INT','WIS','CHA') for skill in ('Arcana','Insight','Investigation','Medicine')]
    typed=(reading_action(session,aid,source) or {}).get('parameters',{}).get('typed',{})
    tools=facts(session,subject).get('trace.tools' if source==TRACE else 'vessel.tools',{}).get('value',{})
    for item in session.state['actors'][aid]['bundle'].get('carrying',{}).get('items',[]):
        name=item.get('name','');normalized=name.replace('’',"'").casefold()
        rank=typed.get('reading_tool_proficiencies',{}).get(normalized,0)
        if source==TRACE and normalized not in {"calligrapher's supplies","painter's supplies"} or source==VESSEL and not rank:
            continue
        choices.extend(ability+':'+name for ability in tools.get(item.get('key'),[]))
    return choices


def native_value(session, aid, subject, key):
    from ..native_scene import engine_for
    from .knowledge_readings import native_fact
    from types import SimpleNamespace
    engine=engine_for(session)
    return native_fact(SimpleNamespace(engine=engine,actor=engine.state.actors[aid]),subject,key)


def kind_at(session,subject,source):
    from ..native_scene import engine_for
    from .knowledge_readings import subject_kind
    return subject_kind(engine_for(session),subject,source)


def targets(session, aid, source):
    from ..native_scene import engine_for
    from .knowledge_readings import eligible
    engine=engine_for(session);actor=engine.state.actors[aid]
    actions=[a for a in engine.action_catalog.values() if a.owner_id==aid
        and a.parameters.get('typed',{}).get('source')==source
        and any(e.get('type')=='knowledge_reading' for e in a.parameters.get('typed',{}).get('effects',[]))
        and not a.parameters.get('typed',{}).get('reading_internal')]
    for subject in [*engine.state.actors,*engine.state.objects]:
        objects=subject in engine.state.objects
        action=next((a for a in actions if bool(a.parameters.get('typed',{}).get('reading_object'))==objects),None)
        if action is not None and eligible(engine,actor,action,subject):yield subject


@hook('journey_options')
def options(session, aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:
        return []
    result=[]
    for source in QUESTIONS:
        if not owned(session,aid,source):
            continue
        for subject in targets(session,aid,source):
            result.append({'id':'examine:'+source+':'+subject,'kind':'information_reading','auto_select':0,
                'payload':{'source':source,'subject_id':subject,'questions':questions_for(source,kind_at(session,subject,source))[:2 if source==VESSEL else 1]},
                'label':'Examine a target; choose questions before confirming.',
                'questions':[{'id':q,'label':LABELS[q]} for q in questions_for(source,kind_at(session,subject,source))],
                'check_choices':check_choices(session,aid,source,subject),
                'modes':['Study','One minute examination'] if source==VESSEL else ['Study','Search'] if source==METAL else ['Examine']})
    if any(owned(session,other,QI) for other in session.state['actors']):
        result.append({'id':'nature_declaration','kind':'information_self_declaration','auto_select':0,
            'payload':{'unwilling':False,'concealing':False},'label':'Declare your willingness and whether you actively conceal your nature',
            'choices':{'unwilling':[False,True],'concealing':[False,True]}})
    if owned(session,aid,SKY):
        for mode,seconds in [('immediate',0),('careful',600)]:
            result.append({'id':'read_sky:'+mode,'kind':'information_weather','auto_select':0,
                'payload':{'mode':mode},'label':'Read the Sky: '+mode+' reading ('+str(seconds)+' seconds, no CP)'})
    return result


@hook('journey_properties')
def information(session, aid):
    from ..observer_information import readings_journey
    rows=readings_journey(session,aid)
    return {'information':rows} if rows else None


@hook('journey_native_actions')
def native_readings(session,aid):
    return [a['source_definition_id'] for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('source') in QUESTIONS]


@hook('journey_native_procedures')
def native_procedures(session,aid):
    return {a['source_definition_id']:60 for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('source')==VESSEL}


def native_examination(session,aid,payload):
    """Translate player-owned examination choices to real native source actions."""
    require(set(payload)<={'source','subject_id','questions','check','mode','internal','spend_cp','profile','steady_cp','replace_profile'},'Unknown examination parameter.')
    source=payload.get('source');subject=payload.get('subject_id');selected=payload.get('questions')
    require(source in QUESTIONS and owned(session,aid,source) and subject in list(targets(session,aid,source)),'Choose an owned examination and a reachable target.')
    paid=payload.get('spend_cp',False);internal=payload.get('internal',False);profile=payload.get('profile',False)
    require(type(paid) is bool and (not paid or source==VENOM),'Only Appraise the Venom can buy three facts.')
    require(type(internal) is bool and (not internal or source==VESSEL),'Only Read the Vessel has an internal-property mode.')
    require(type(profile) is bool and (not profile or source==VENOM),'Only Appraise the Venom creates an Antidote Profile.')
    count=2 if source==VESSEL else 3 if paid else 1
    require(isinstance(selected,list) and len(selected)==count and len(set(selected))==count and all(q in questions_for(source,kind_at(session,subject,source)) for q in selected),'Choose the printed number of different questions.')
    mode=payload.get('mode','Study' if source in {VESSEL,METAL} else 'Examine')
    allowed={'Study','One minute examination'} if source==VESSEL else {'Study','Search'} if source==METAL else {'Examine'}
    require(mode in allowed,'Choose this source’s printed examination mode.')
    from ..native_scene import engine_for,run_operation
    engine=engine_for(session);objects=subject in engine.state.objects
    actions=[a for a in engine.action_catalog.values() if a.owner_id==aid and a.source_definition_id in engine.state.actors[aid].action_ids
        and a.parameters.get('typed',{}).get('source')==source
        and not a.parameters.get('typed',{}).get('reading_inventory')
        and bool(a.parameters.get('typed',{}).get('reading_object'))==objects
        and bool(a.parameters.get('typed',{}).get('reading_internal'))==internal
        and (int(a.parameters.get('typed',{}).get('reading_count',1))==3)==paid
        and ('#search' in a.source_definition_id)==(source==METAL and mode=='Search')]
    require(len(actions)==1,'Choose this examination’s native target and mode.')
    choices={'choice:needle.reading_questions':selected}
    if source in {TRACE,VESSEL}:
        spec=payload.get('check','INT:Arcana')
        require(spec in check_choices(session,aid,source,subject),'Choose a printed check.')
        choices['choice:needle.reading_check']=[spec]
    amount=payload.get('steady_cp',0)
    require(type(amount) is int and amount>=0 and (source==QI or amount==0),'Only Hunger Checks use this CP spending.')
    if source==QI:
        typed=actions[0].parameters['typed']
        require(amount<=min(engine.state.actors[aid].proficiency_bonus,engine.state.actors[aid].resources.get(typed['reading_cp_pool'],0)),'Choose at most your Proficiency Bonus in available CP.')
    if source==QI:choices['choice:needle.reading_hunger_steady']=[str(amount)]
    if source==VENOM:
        choices['choice:needle.reading_profile']=['create'] if profile else []
        if payload.get('replace_profile') is not None:choices['choice:needle.antidote_profile_replace']=[str(payload['replace_profile'])]
    run_operation(session,aid,'procedure' if mode=='One minute examination' else 'action',
        {'action_id':actions[0].source_definition_id,'subject_id':subject,'choices':choices})
    return True


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in {'information_reading','information_weather','information_self_declaration'}:
        return None
    actor=session.state['actors'][aid]
    require(not actor['incapacitated'],'An incapacitated creature cannot examine a target.')
    if kind=='information_self_declaration':
        require(set(payload)=={'unwilling','concealing'} and all(type(v) is bool for v in payload.values()),'Declare your willingness and active concealment.')
        from ..fact_consent_admission import declare
        declared='unwilling_concealed' if payload['unwilling'] and payload['concealing'] else 'unwilling_open' if payload['unwilling'] else 'willing_concealed' if payload['concealing'] else 'open'
        declare(session,aid,{'source':QI,'subject':aid,'kind':'qi_nature','scope':'scene','value':declared,
            'expires_at':int(session.clock())+60,'readers':[other for other in session.state['actors'] if owned(session,other,QI)]})
        return True
    if kind=='information_weather':
        require(set(payload)=={'mode'} and payload['mode'] in {'immediate','careful'} and owned(session,aid,SKY),'Choose an owned weather reading.')
        careful=payload['mode']=='careful'
        if careful:
            session.tick(600)
        else:
            from .journey_turns import pay
            pay(session,aid,'action')
        answers=weather_answers(session,careful=careful,reader_cl=source_cl(session,aid,SKY))
        source=SKY;subject='scene';expires=None
    else:
        return native_examination(session,aid,payload)
    from ..observer_information import publish_journey
    publish_journey(session,aid,source,'answer',{'subject_id':subject,'answers':answers},expires_at=expires)
    return True


@hook('fact_admission_schema')
def qi_nature_schema(session,source,subject,kind):
    if session is None or source!=QI or kind!='qi_nature' or subject not in session.state['actors']:return None
    if hasattr(session,'engine'):
        from ..alternative_payments import owned as native_owned
        present=any(native_owned(session.engine,actor,QI) for actor in session.engine.state.actors.values())
    else:present=any(owned(session,aid,QI) for aid in session.state['actors'])
    if present:return {'value_type':'text','maximum_seconds':60,'description':'Your own willingness and active concealment for Taste the Qi.'}


@hook('fact_admission_validate')
def qi_nature_value(session,source,subject,kind,value):
    if source==QI and kind=='qi_nature':
        return value in ('open','unwilling_open','willing_concealed','unwilling_concealed')


@hook('journey_view')
def private_knowledge_view(state,viewer_id):
    from ..fact_consent_admission import KEY
    from ..observer_information import READING
    if KEY not in state and not any(a.get('observer_information') for a in state['actors'].values()):
        return None
    out=deepcopy(state)
    out.pop('replay_base',None);out.pop('command_journal',None)
    out.get('battlefield',{}).pop('encounter_sources',None)
    if KEY in out:
        out[KEY]=[r for r in out[KEY] if not r.get('private_to_table') and viewer_id in (r['subject'],*r['readers'])]
    import json
    for aid,actor in out['actors'].items():
        if aid!=viewer_id:
            actor.pop('observer_information',None)
            snapshot=actor.get('encounter_snapshot')
            if snapshot:
                snapshot['conditions']={key:value for key,value in snapshot.get('conditions',{}).items()
                    if json.loads(value).get('condition_id')!=READING}
    return out
