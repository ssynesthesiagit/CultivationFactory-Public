"""Restful Dream: paid ten-minute willing-touch ritual and completed-rest delivery."""
from copy import deepcopy
from . import hook
from ..journey import require
from ..fact_consent_admission import read
from .journey_effects import effects, end, minor_eligible
from .journey_rolls import roll
from ..journey_decisions import autonomous

SOURCE = 'DREAMS_BASE_RESTFUL_DREAM'
KEY = 'dreams:restful_dream'
CP = 'resource:core.qi'


@hook('compile_passives')
def seal(rows, info):
    if SOURCE not in info['owned_ids']: return None
    return [*rows, {'block':'restful_dream_journey','feature_id':SOURCE,'pb':int(info['numbers']['pb'])}]


def owned(session, aid):
    return next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives',()) if r.get('block')=='restful_dream_journey'),None)


def ledger(session, aid):
    return session.state['actors'][aid].setdefault('source_states',{}).setdefault(KEY,{})


def touch(session, aid, target):
    if target not in session.state['actors']: return False
    if target == aid: return True
    from ..gate2_runtime_models import Position
    a=Position.model_validate(session.state['actors'][aid]['position'])
    b=Position.model_validate(session.state['actors'][target]['position'])
    return session.grid.distance_cells(a,b)<=1 and session.grid.line_of_physical_transmission(a,b)


@hook('compile_bundle')
def cp_pools(bundle, info):
    if not any(r.get('block')=='restful_dream_journey' for r in bundle.get('typed_passives',())): return None
    bundle=deepcopy(bundle)
    bundle['restful_dream_pools']=['resource:core.'+name.lower() for name in bundle.get('powering',{}).get('pools',())]
    bundle['restful_dream_default_pool']='resource:core.'+info['primary']
    return bundle


def payer(session,aid,parameters):
    bundle=session.state['actors'][aid]['bundle']
    pool=parameters.get('pool',bundle.get('restful_dream_default_pool',CP))
    require(pool in bundle.get('restful_dream_pools',[CP]), 'Choose one of this caster’s actual CP pools.')
    return pool


@hook('fact_admission_schema')
def consent_schema(session, source, subject, kind):
    if source == SOURCE and kind == 'willing' and any(owned(session,aid) for aid in session.state['actors']):
        return {'value_type':'flag','maximum_seconds':3600,'description':'Willing to receive this caster’s touched ten-minute Restful Dream ritual.'}


def validate(session, aid, row):
    target = row['parameters']['target']
    require(owned(session,aid) and target in session.state['actors'] and touch(session,aid,target), 'The ritual needs one touched creature throughout its procedure.')
    receipt = read(session,SOURCE,target,'willing',aid,aid)
    require(receipt and receipt['value']==1, 'The target must explicitly consent to this caster’s ritual.')


@hook('activity_spec')
def ritual(session, aid, source, parameters):
    if source != SOURCE: return None
    require(set(parameters) in ({'target'},{'target','pool'}), 'Choose one touched willing creature.')
    validate(session,aid,{'parameters':parameters})
    require(session.state['actors'][aid]['resources'].get(payer(session,aid,parameters),0)>=1,'Restful Dream costs 1 CP.')
    return {'seconds':600,'label':'Restful Dream (10-minute ritual, 1 cultivation point from your Path resource)'}


@hook('activity_started')
def pay(session, aid, row):
    if row['source']==SOURCE:
        session.spend_resource(aid,payer(session,aid,row['parameters']),1,SOURCE)
        session.emit('RITUAL_PAID',aid,source=SOURCE,cp=1,pool=payer(session,aid,row['parameters']),target=row['parameters']['target'])


@hook('activity_validate')
def still_valid(session, aid, row):
    if row['source']==SOURCE: validate(session,aid,row)


@hook('activity_finished')
def bind_rest(session, aid, row):
    if row['source']!=SOURCE:return
    target = row['parameters']['target']
    data = ledger(session,target)
    data['pending'] = {'caster':aid,'pb':owned(session,aid)['pb'],
                       'short_rest':session.state['actors'][target].get('short_rests',0)}
    session.emit('RESTFUL_DREAM_BOUND',aid,source=SOURCE,target=target)


@hook('journey_short_rest')
def benefit(session, aid):
    data = session.state['actors'][aid].get('source_states',{}).get(KEY)
    if not data or 'pending' not in data:return
    pending = data.pop('pending')
    actor = session.state['actors'][aid]
    if data.get('benefit_rest',-1)==actor['long_rests']:
        session.emit('RESTFUL_DREAM_LIMIT',aid,source=SOURCE)
        return
    data['benefit_rest']=actor['long_rests']
    data['recovery_advantage']=1
    data['fear_effects']=[iid for iid,e in effects(session,aid).items() if e['category']=='frightened']
    data['minor_effects']=[iid for iid,e in effects(session,aid).items() if minor_eligible(e)]
    data['fear_choice']=int(bool(data['fear_effects']))
    data['minor_choice']=int(bool(data['minor_effects']))
    hp=2*pending['pb']
    data['temporary_hp']=max(data.get('temporary_hp',0),hp)
    if 'encounter_snapshot' in actor:
        actor['encounter_snapshot']['temporary_hp']=max(actor['encounter_snapshot']['temporary_hp'],hp)
    session.emit('RESTFUL_DREAM_REST_COMPLETED',aid,source=SOURCE,temporary_hp=hp,caster=pending['caster'])


@hook('journey_command')
def choose(session, aid, kind, payload):
    if kind!='restful_choice':return None
    require(set(payload)=={'choice','effect_id'},'Choose one Frightened save repeat, one eligible minor effect, or decline.')
    require(not session.state['actors'][aid]['incapacitated'], 'The recipient must be able to make this optional choice.')
    data=session.state['actors'][aid].get('source_states',{}).get(KEY,{})
    choice=payload['choice']
    require(choice in ('fear','minor') and data.get(choice+'_choice'), 'This optional post-rest choice is not available.')
    iid=payload['effect_id']
    if iid:
        effect=effects(session,aid).get(iid)
        require(effect is not None and iid in data.get(choice+'_effects',()),'Choose an actual effect present when this rest completed.')
        if choice=='minor':
            require(minor_eligible(effect), 'Only an explicitly ordinary/minor effect qualifies.')
            end(session,aid,iid,SOURCE)
        else:
            require(effect['category']=='frightened' and effect['save_ability'], 'Repeat an actual saving throw against Frightened.')
            from ..gate2_rolls import DeterministicRollAuthority
            roller=DeterministicRollAuthority(session.state['journey_id'],session.state.get('roll_counter',0))
            actor=session.state['actors'][aid]
            modifier=actor['bundle']['actor_template']['saving_throws'][effect['save_ability']]-2*actor['exhaustion']
            result=roller.d20(modifier=modifier,actor_id=aid,reason=SOURCE+':fear')
            session.state['roll_counter']=roller.counter
            session.emit('RESTFUL_DREAM_SAVE',aid,source=SOURCE,effect_id=iid,roll=result.model_dump(mode='json'),dc=effect['save_dc'])
            if result.total>=effect['save_dc']:end(session,aid,iid,SOURCE)
    data[choice+'_choice']=0
    return True


@hook('journey_options')
def options(session, aid):
    if session.state['phase']!='travel':return None
    rows=[]
    actor=session.state['actors'][aid]
    from .journey_activities import current
    if owned(session,aid) and not actor['incapacitated'] and not current(session,aid):
        for target in session.state['actors']:
            receipt=read(session,SOURCE,target,'willing',aid,aid)
            if not (touch(session,aid,target) and receipt and receipt['value']==1):continue
            recipient=session.state['actors'][target]
            benefit=recipient.get('source_states',{}).get(KEY,{})
            # Keep every explicit ritual available. Autonomous seats should
            # neither replace a pending benefit nor pay for a used rest, and
            # must have enough consent time to finish the full procedure.
            automatic=(autonomous(session,aid) and 'pending' not in benefit
                and benefit.get('benefit_rest',-1)!=recipient['long_rests']
                and receipt['expires_at']>session.clock()+600)
            for pool in actor['bundle'].get('restful_dream_pools',[CP]):
                if actor['resources'].get(pool,0)<1:continue
                name=pool.rsplit('.',1)[-1].capitalize()
                rows.append({'id':SOURCE+':'+target+':'+pool,'kind':'activity_start','auto_select':int(automatic),
                    'payload':{'source':SOURCE,'parameters':{'target':target,'pool':pool}},
                    'label':'Restful Dream: 10-minute touched ritual on '+session.state['actors'][target]['name']+'; costs 1 '+name+' (cultivation point), benefits after their next Short Rest'})
    data=session.state['actors'][aid].get('source_states',{}).get(KEY,{})
    for choice in ('fear','minor'):
        if not data.get(choice+'_choice'):continue
        rows.append({'id':'restful:'+choice+':decline','kind':'restful_choice','auto_select':0,
                     'payload':{'choice':choice,'effect_id':''},'label':'Decline Restful Dream’s optional '+choice+' benefit'})
        for iid,effect in effects(session,aid).items():
            if iid not in data.get(choice+'_effects',()):continue
            if (choice=='fear' and effect['category']=='frightened') or (choice=='minor' and minor_eligible(effect)):
                rows.append({'id':'restful:'+choice+':'+iid,'kind':'restful_choice','auto_select':0,
                             'payload':{'choice':choice,'effect_id':iid},'label':'Restful Dream: '+('repeat the save against ' if choice=='fear' else 'end ')+effect['label']})
    for row in rows:
        if row['kind']=='restful_choice':row['auto_select'] = int(autonomous(session,aid))
    return rows


@hook('journey_check_profile')
def recovery_profile(session,aid,spec):
    data=session.state['actors'][aid].get('source_states',{}).get(KEY,{})
    if data.get('recovery_advantage') and spec['recovery'] in ('ordinary_exhaustion','stress','mental_fatigue'):
        return {'advantage':1}


@hook('journey_check_rolled')
def consume_recovery(session,aid,spec):
    if recovery_profile(session,aid,spec):ledger(session,aid)['recovery_advantage']=0


@hook('journey_combat_bundle')
def export(bundle,session,aid):
    data=session.state['actors'][aid].get('source_states',{}).get(KEY)
    if data is None:return None
    bundle=deepcopy(bundle);bundle['restful_dream_setup']=deepcopy(data)
    return bundle


@hook('match_initialize')
def combat_setup(engine):
    for bundle in engine.typed_bundle_documents:
        data=bundle.get('restful_dream_setup');actor=engine.state.actors.get(bundle['actor_id'])
        if data is not None and actor is not None:
            actor.temporary_hp=max(actor.temporary_hp,data.get('temporary_hp',0))


@hook('journey_encounter_settled')
def import_hp(session,aid,engine,creature):
    data=session.state['actors'][aid].get('source_states',{}).get(KEY)
    if data is not None:data['temporary_hp']=creature.temporary_hp


@hook('journey_before_command')
def optional_rest_decisions(session,aid,kind,payload):
    ids=session.state['actors'] if kind in ('enter_combat','finish') else (aid,)
    for target in ids:
        data=session.state['actors'][target].get('source_states',{}).get(KEY,{})
        if data.get('fear_choice') or data.get('minor_choice'):
            require(target==aid and kind=='restful_choice', 'Resolve the recipient’s optional Restful Dream choices at the completed rest before continuing.')


@hook('journey_auto_blocked')
def rest_choices_are_player_owned(session,aid):
    data=session.state['actors'][aid].get('source_states',{}).get(KEY,{})
    if not autonomous(session,aid) and (data.get('fear_choice') or data.get('minor_choice')):return True


@hook('journey_auto_priority')
def auto_priority(session,aid,option):
    if option['kind']=='restful_choice':
        return -100 if option['payload']['effect_id'] else -99
    if option['kind']=='activity_start' and option['payload']['source']==SOURCE:
        return -10


@hook('activity_command_interrupts')
def recipient_interruption(session,caster,row,aid,kind,payload):
    if row['source']!=SOURCE or row['parameters']['target']!=aid:return None
    if kind in ('move','incapacitated','long_rest','short_rest','finish','enter_combat'):return True
    if kind=='declare_fact' and payload.get('source')==SOURCE and payload.get('kind')=='willing' and payload.get('scope')==caster and payload.get('value')==0:return True
