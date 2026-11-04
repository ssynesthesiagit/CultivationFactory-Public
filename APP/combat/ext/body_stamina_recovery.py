"""Generic Body Stamina recovery; scene/suppression stay with the shared seam.

Body practitioners (including Hundred-Venom) use the printed rest quotas and
actual interruption events. This module owns recovery only, never scene records
or suppression facts, and has no dependency on a family plug-in.
"""
from . import hook
from .body_modes_scene_resources import STAMINA, bundle_of, profiles

AUTHORITY = 'system:body_stamina_recovery'

RECOVERY='body_recover_stamina'


def recovery_state(session,aid):
    return session.state['actors'][aid].setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault(
        'recovery',{'short_rests':0,'cultivation_sessions':0})


def stamina_maximum(actor):
    return next((int(p['maximum']) for p in actor['bundle']['actor_template']['resources'] if p['resource_id']==STAMINA),0)


@hook('journey_options')
def recovery_options(session,aid):
    actor=session.state['actors'][aid]
    if not profiles(actor['bundle']) or actor['incapacitated']:return
    from fractions import Fraction
    state=actor.get('source_states',{}).get(AUTHORITY,{}).get('recovery',{});activity=state.get('activity')
    out=[]
    if activity:
        if not activity.get('interrupted'):
            remaining=max(Fraction(0),Fraction(activity['deadline_num'],activity['deadline_den'])-session.clock())
            if remaining:
                seconds=(remaining.numerator+remaining.denominator-1)//remaining.denominator
                out.append({'id':'body.recovery.wait','kind':'wait','payload':{'seconds':seconds},'auto_select':0,
                    'label':f"{actor['name']}: continue the {activity['name']} for {seconds} seconds; acting or entering combat interrupts it."})
            else:
                out.append({'id':'body.recovery.finish','kind':RECOVERY,'payload':{'phase':'finish'},'auto_select':0,
                    'label':f"{actor['name']}: finish the uninterrupted {activity['name']} and recover Stamina (no scene reset)."})
        out.append({'id':'body.recovery.cancel','kind':RECOVERY,'payload':{'phase':'cancel'},'auto_select':0,
                    'label':f"{actor['name']}: end the {activity['name']} without recovering Stamina."})
        return out
    for mode,name,seconds,key,limit in (('short_rest','one-hour Short Rest',3600,'short_rests',2),
                                       ('cultivation_session','two-hour Cultivation Session',7200,'cultivation_sessions',1)):
        if state.get(key,0)<limit:
            amount=stamina_maximum(actor)//2 if mode=='short_rest' else stamina_maximum(actor)
            out.append({'id':'body.recovery.'+mode,'kind':RECOVERY,'payload':{'phase':'start','mode':mode},'auto_select':0,
                'label':f"{actor['name']}: begin a {name}; recover {'up to ' if mode=='short_rest' else 'all missing '}{amount if mode=='short_rest' else ''} Stamina after uninterrupted time; {limit-state.get(key,0)} uses before a Long Rest."})
    return out or None


@hook('journey_command')
def recover_stamina(session,aid,kind,payload):
    if kind!=RECOVERY:return
    from ..journey import require
    actor=session.state['actors'][aid]
    require(profiles(actor['bundle']) and not actor['incapacitated'],'Only a conscious enrolled Body practitioner may recover Stamina.')
    require(payload.get('phase') in ('start','finish','cancel'),'Choose whether to start, finish or cancel recovery.')
    state=recovery_state(session,aid)
    if payload['phase']=='start':
        require(set(payload)=={'phase','mode'} and payload['mode'] in ('short_rest','cultivation_session') and not state.get('activity'),
                'Choose one recovery procedure; finish or cancel an existing one first.')
        mode=payload['mode'];key='short_rests' if mode=='short_rest' else 'cultivation_sessions';limit=2 if mode=='short_rest' else 1
        require(state.get(key,0)<limit,'This recovery has no uses left before a Long Rest.')
        deadline=session.clock()+(3600 if mode=='short_rest' else 7200)
        state['activity']={'mode':mode,'name':'Short Rest' if mode=='short_rest' else 'Cultivation Session',
            'deadline_num':deadline.numerator,'deadline_den':deadline.denominator,'interrupted':0}
        session.emit('BODY_RECOVERY_STARTED',aid,mode=mode,deadline_num=deadline.numerator,deadline_den=deadline.denominator)
    else:
        require(set(payload)=={'phase'} and state.get('activity'),'There is no recovery in progress.')
        activity=state['activity']
        if payload['phase']=='finish':
            from fractions import Fraction
            require(not activity['interrupted'] and session.clock()>=Fraction(activity['deadline_num'],activity['deadline_den']),
                    'The printed uninterrupted recovery time has not completed.')
            maximum=stamina_maximum(actor);before=actor['resources'].get(STAMINA,0)
            amount=maximum//2 if activity['mode']=='short_rest' else maximum
            actor['resources'][STAMINA]=min(maximum,before+amount)
            key='short_rests' if activity['mode']=='short_rest' else 'cultivation_sessions'
            state[key]=state.get(key,0)+1
            session.emit('RESOURCE_GAINED',aid,source=AUTHORITY,resource_id=STAMINA,amount=actor['resources'][STAMINA]-before)
            session.emit('BODY_RECOVERY_COMPLETED',aid,mode=activity['mode'])
        else:session.emit('BODY_RECOVERY_CANCELLED',aid,mode=activity['mode'])
        state.pop('activity')
    return True


@hook('journey_before_command')
def recovery_interruption(session,aid,kind,payload):
    # Only these kinds let interrupted recovery continue. New/story kinds default
    # to interrupting: an unlisted action must not silently preserve the bonus.
    quiet={'wait','declare_fact',RECOVERY,'incapacitated'}
    for subject,actor in session.state['actors'].items():
        state=actor.get('source_states',{}).get(AUTHORITY,{}).get('recovery',{})
        activity=state.get('activity')
        if not activity or activity.get('interrupted'):continue
        interrupt=(kind=='enter_combat' or subject==aid and (kind not in quiet or kind=='incapacitated' and payload.get('value')))
        if interrupt:
            activity['interrupted']=1
            session.emit('BODY_RECOVERY_INTERRUPTED',subject,mode=activity['mode'],trigger=kind)


@hook('journey_rest')
def full_rest_stamina(session,aid):
    actor=session.state['actors'][aid]
    if not profiles(actor['bundle']):return
    before=actor['resources'].get(STAMINA,0);actor['resources'][STAMINA]=stamina_maximum(actor)
    actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})['recovery']={'short_rests':0,'cultivation_sessions':0}
    session.emit('RESOURCE_GAINED',aid,source=AUTHORITY,resource_id=STAMINA,amount=actor['resources'][STAMINA]-before)


@hook('state_event')
def stamina_empty_exhaustion(engine,event):
    if event.event_type!='RESOURCE_SPENT' or event.payload.get('resource_id')!=STAMINA or int(event.payload.get('amount') or 0)<=0:return
    actor=engine.state.actors.get(event.actor_id)
    if actor is None or actor.resources.get(STAMINA)!=0 or not profiles(bundle_of(engine,actor)):return
    from .forged_exhaustion import add
    add(engine,actor,1,AUTHORITY)


@hook('fact_admission_schema')
def interruption_schema(session, source, subject, kind):
    if source != AUTHORITY or kind != 'recovery_interruption':
        return None
    if not profiles(session.state['actors'][subject]['bundle']):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'description': 'An actual interruption of an uninterrupted Body rest or cultivation session.'}


@hook('fact_admission_validate')
def validate_interruption(session, source, subject, kind, value):
    if source != AUTHORITY or kind != 'recovery_interruption':
        return None
    from ..journey import require, integer
    require(type(value.get('source_rule')) is str and bool(value['source_rule'].strip())
            and integer(value.get('source_cl')) and value.get('interrupted') == 1
            and type(value.get('reason')) is str and bool(value['reason'].strip()),
            'Record the actual interruption, its source rule, Source CL and reason.')
    return True


@hook('fact_admitted')
def admitted_interruption(session, fact):
    if (fact['source'], fact['kind']) != (AUTHORITY, 'recovery_interruption'):
        return
    aid = fact['subject']
    activity = recovery_state(session, aid).get('activity')
    if activity and not activity.get('interrupted'):
        activity['interrupted'] = 1
        session.emit('BODY_RECOVERY_INTERRUPTED', aid, mode=activity['mode'], receipt_id=fact['receipt_id'])


@hook('journey_acquired')
def acquisition_interrupts_recovery(session,aid,source,acquisition_id,userdata_root=None):
    recovery_interruption(session,aid,'source_acquired',{})


