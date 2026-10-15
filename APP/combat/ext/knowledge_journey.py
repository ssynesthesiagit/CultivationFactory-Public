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
    target=session.state['actors'].get(subject)
    if target is None:
        return None
    snapshot=target.get('encounter_snapshot',{})
    if key=='qi.bloodied':
        maximum=target['bundle']['actor_template']['maximum_hp']
        return snapshot.get('current_hp',maximum)*2<=maximum
    import json
    rows=[json.loads(r) for r in snapshot.get('conditions',{}).values()]
    poisoned=any(r['condition_id'] in {'poisoned','condition:typed.poisoned'} for r in rows)
    if key=='poison.poisoned':
        return poisoned
    from ..typed_executor import mark_condition_id
    if key in {'poison.dose','poison.burden','poison.ingrained'}:
        name={'poison.dose':'Dose Mark','poison.burden':'Toxin Burden','poison.ingrained':'Ingrained Toxin'}[key]
        present=any(r['condition_id']==mark_condition_id(name,r['source_actor_id'])
            and (key!='poison.dose' or r['source_actor_id']==aid) for r in rows)
        return present if present or key=='poison.dose' else None
    if key=='poison.present' and poisoned:
        return True
    return None


def targets(session, aid, source):
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][aid]
    for subject,other in session.state['actors'].items():
        if session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(other['position'])) <= (5 if source==TRACE else 30) and session.grid.line_of_sight(Position.model_validate(actor['position']),Position.model_validate(other['position'])):
            kind=facts(session,subject).get('subject.kind',{}).get('value','creature')
            if kind in KINDS[source] or source==METAL and facts(session,subject).get('metal.bearing',{}).get('value') is True:
                yield subject
    for obj in session.state['battlefield'].get('map_objects',[]):
        subject='object:map.'+str(obj['id'])
        pos=Position(x=obj['x'],y=obj['y'])
        if session.grid.distance_ft(Position.model_validate(actor['position']),pos) <= (5 if source==TRACE else 30) and session.grid.line_of_sight(Position.model_validate(actor['position']),pos):
            kind=facts(session,subject).get('subject.kind',{}).get('value','object')
            material=obj.get('material')
            metal=(facts(session,subject).get('metal.bearing',{}).get('value') is True
                or material in {'iron','steel','iron or steel','copper','bronze','brass','gold','silver','mithral','adamantine'}
                or kind in {'ore','mineral'})
            if kind in KINDS[source] and (source!=METAL or metal):
                yield subject


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
                'payload':{'source':source,'subject_id':subject,'questions':questions_for(source,facts(session,subject).get('subject.kind',{}).get('value','creature' if subject in session.state['actors'] else 'object'))[:2 if source==VESSEL else 1]},
                'label':'Examine a target; choose questions before confirming.',
                'questions':[{'id':q,'label':LABELS[q]} for q in questions_for(source,facts(session,subject).get('subject.kind',{}).get('value','creature' if subject in session.state['actors'] else 'object'))],
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


def check(session, aid, spec, dc):
    """A real, deterministic elapsed-scene check with a durable roll result."""
    from ..journey import integer
    actor=session.state['actors'][aid];bundle=actor['bundle']
    numbers=next((a['parameters']['typed']['numbers'] for a in bundle['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('numbers',{}).get('ability_mods')), {})
    if spec=='cultivation':
        bonus=int(numbers.get('pb',0))+int(numbers.get('key_mod',0))
    else:
        require(isinstance(spec,str) and ':' in spec,'Choose an ability and skill for this check.')
        ability,skill=spec.split(':',1)
        require(ability in {'STR','DEX','CON','INT','WIS','CHA'},'Choose a printed check ability.')
        modifiers=numbers.get('ability_mods',{})
        bonus=int(bundle.get('skills',{}).get(skill,modifiers.get(ability,0)))
        standard={'Arcana':'INT','Investigation':'INT','Insight':'WIS','Medicine':'WIS'}
        if skill in bundle.get('skills',{}):
            bonus+=int(modifiers.get(ability,0))-int(modifiers.get(standard.get(skill,ability),0))
        elif skill not in standard:
            typed=next((a['parameters']['typed'] for a in bundle['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('reading_tool_proficiencies')), {})
            rank=typed.get('reading_tool_proficiencies',{}).get(skill.replace('’',"'").casefold(),0)
            bonus+=int(numbers.get('pb',0))*rank
    bonus+=getattr(session,'information_check_bonus',0)
    require(integer(dc),'The source must establish a check DC.')
    from .scene_checks import roll_check
    ability,skill=('','Cultivation') if spec=='cultivation' else spec.split(':',1)
    roll=roll_check(session,aid,{'id':'knowledge:'+str(session.state['revision']),
        'skill':skill,'ability':ability,'subject':getattr(session,'information_check_subject',aid),
        'purpose':'knowledge','dc':dc},bonus)
    session.last_information_check_total=roll.total
    return roll.total>=dc


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
        answers=weather_answers(session,careful=careful,reader_cl=int(actor['bundle'].get('cl',1)))
        source=SKY;subject='scene';expires=None
    else:
        require(set(payload)<={'source','subject_id','questions','check','mode','internal','spend_cp','profile','steady_cp','replace_profile'},'Unknown examination parameter.')
        source=payload.get('source');subject=payload.get('subject_id');selected=payload.get('questions')
        require(source in QUESTIONS and owned(session,aid,source) and subject in list(targets(session,aid,source)),'Choose an owned examination and a reachable target.')
        require(type(payload.get('profile',False)) is bool,'Choose whether to create an Antidote Profile.')
        require(source==QI or payload.get('steady_cp',0)==0,'Only Hunger Checks use this digestion spending.')
        paid=payload.get('spend_cp',False)
        require(type(paid) is bool and (not paid or source==VENOM),'Only Appraise the Venom can buy three facts.')
        count=2 if source==VESSEL else 3 if paid else 1
        require(isinstance(selected,list) and len(selected)==count and len(set(selected))==count and all(q in questions_for(source,facts(session,subject).get('subject.kind',{}).get('value','creature' if subject in session.state['actors'] else 'object')) for q in selected),'Choose the printed number of different questions.')
        internal=payload.get('internal',False)
        require(type(internal) is bool and (not internal or source==VESSEL),'Only Read the Vessel has an internal-property mode.')
        if internal:
            from ..gate2_runtime_models import Position
            other=session.state['actors'].get(subject)
            position=other['position'] if other else next({'x':o['x'],'y':o['y']} for o in session.state['battlefield'].get('map_objects',[]) if 'object:map.'+str(o['id'])==subject)
            require(session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(position))<=5,'Internal properties require touch.')
        if paid:
            pool=next((r['resource_id'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] in {'resource:core.qi','resource:core.stamina','resource:core.resonance'}),None)
            require(pool is not None and actor['resources'].get(pool,0)>=1,'Appraise the Venom requires 1 CP for three facts.')
            actor['resources'][pool]-=1
        session.information_check_bonus=0
        session.information_check_subject=subject
        data=facts(session,subject)
        if source==QI and subject in session.state['actors'] and any(k not in data for k in ('qi.unwilling','qi.concealing')):
            from ..fact_consent_admission import read
            declaration=read(session,QI,subject,'qi_nature','scene',aid)
            require(declaration is not None,'The target must declare its own willingness and active concealment before this reading.')
            value=declaration['value']
            data={**data,'qi.unwilling':{'value':value in {'unwilling_open','unwilling_concealed'}},
                'qi.concealing':{'value':value in {'willing_concealed','unwilling_concealed'}}}
        need=source==VESSEL or source==TRACE and (any(data.get('trace.'+k,{}).get('value') is True for k in ('concealed','hostile','high_realm')) or any(data.get(k,{}).get('access')=='concealed' or higher_realm(data.get(k,{}).get('cl'),actor['bundle'].get('cl')) for k in selected))
        success=True
        if need:
            dc=data.get('vessel.dc' if source==VESSEL else 'trace.dc',{}).get('value')
            spec=payload.get('check','INT:Arcana')
            allowed=next(r['check_choices'] for r in options(session,aid) if r['kind']=='information_reading' and r['payload']['source']==source and r['payload']['subject_id']==subject)
            require(spec in allowed,'Choose a printed check.')
            success=check(session,aid,spec,dc) if dc is not None else False
        contested=source==QI and data.get('qi.unwilling',{}).get('value') is True and data.get('qi.concealing',{}).get('value') is True
        if contested:
            # The defending save uses this native creature's compiled statistic.
            require(subject in session.state['actors'],'An opposed check requires a native creature.')
            defense=data.get('qi.defense',{}).get('value')
            require(defense in {'CON','CHA'},'The GM must choose the target’s Constitution or Charisma save.')
            target=session.state['actors'][subject]
            saves=target['bundle']['actor_template']['saving_throws']
            bonus=int(saves.get(defense,0))
            from .scene_checks import roll_d20
            roll=roll_d20(session,subject,'SAVE:Taste the Qi:'+defense,bonus)
            die=roll.natural_result
            session.emit('SOURCE_ACTION_ROLL',subject,roll=roll.model_dump(mode='json'))
            amount=payload.get('steady_cp',0)
            typed=reading_action(session,aid,QI)['parameters']['typed']
            pool=typed['reading_cp_pool']
            require(type(amount) is int and 0<=amount<=typed['numbers']['pb'] and amount<=actor['resources'].get(pool,0),'Choose up to your Proficiency Bonus in available CP before the Hunger Check.')
            if amount:
                actor['resources'][pool]-=amount
                session.emit('INFORMATION_RESOURCE_SPENT',aid,pool=pool,amount=amount,source_id=source)
            session.information_check_bonus=amount
            success=check(session,aid,'cultivation',die+bonus+1)
            if not success:
                selected=['qi.fallback']
        answers={}
        if source==VENOM:
            selected=['poison.present',*selected]
        for key in selected:
            fact=data.get(key,{})
            native=native_value(session,aid,subject,key)
            value=native if native is not None else fact.get('value','Unknown')
            if key in {'qi.suitable','metal.suitable'}:
                names=reading_action(session,aid,source)['parameters']['typed'].get('reading_known_talents',{})
                value={names[k]:result for k,result in fact.get('value',{}).items() if k in names} or 'Unknown: no known talent has a suitability fact.'
            if fact.get('access')=='concealed' and source not in {TRACE,VESSEL} and not contested:
                value='Unknown'
            if not success and key!='qi.fallback' or fact.get('access')=='internal' and not internal:
                value='Unknown'
            answers[LABELS.get(key,key)]=answer_value(value)
        if source==VESSEL and success and data.get('vessel.exceptional_threshold',{}).get('value') is not None and getattr(session,'last_information_check_total',-1)>=data['vessel.exceptional_threshold']['value']:
            answers.update({k.replace('_',' ').title():v for k,v in data.get('vessel.exceptional_facts',{}).get('value',{}).items()})
        if source==VENOM and payload.get('profile'):
            require(data.get('poison.present',{}).get('value') is True or data.get('subject.kind',{}).get('value')=='sample','An Antidote Profile needs a poison, poisoned target or sample.')
            from ..antidote_profiles import create_journey
            create_journey(session,aid,source,subject,answers,payload.get('replace_profile'))
        mode=payload.get('mode','Study')
        require(mode in {'Study','Search','One minute examination'},'Choose a printed examination mode.')
        require(mode!='One minute examination' or source==VESSEL,'Only Read the Vessel has this one-minute mode.')
        if mode=='One minute examination':
            session.tick(60)
        else:
            from .journey_turns import pay
            pay(session,aid,'bonus_action' if source==QI else 'action')
        expires=session.state['seconds']+60 if source==QI else None
    from ..observer_information import publish_journey
    publish_journey(session,aid,source,'answer',{'subject_id':subject,'answers':answers},expires_at=expires)
    return True


@hook('fact_admission_schema')
def qi_nature_schema(session,source,subject,kind):
    if source==QI and kind=='qi_nature' and subject in session.state['actors'] and any(owned(session,aid,QI) for aid in session.state['actors']):
        return {'value_type':'text','maximum_seconds':60,'description':'Your own willingness and active concealment for Taste the Qi.'}


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
