"""Native Hearthfire camp procedures on the existing Journey transaction API.

The family owns its camp, invitations, rest receipts and sanctuary declarations.
It consumes compiled acquisition rows; it never grants a feature or a generic
inventory/fact/actor service. Commands are source scoped, revision checked, and
cold loaded by JourneyStore. UI/API callers use journey_menu/journey_act.
"""
from copy import deepcopy
from . import hook
from .qi_hearthfire import HEARTH, RECOVERY, CARRY, BLOCK
from .qi_hearthfire_sanctuary import PAVILION, WELCOME, RECOVERY_LABELS, CAUSES, PENALTIES
from ..journey import require, integer
from ..gate2_runtime_models import Position
from ..canonical import canonical_sha256

LEVELS={HEARTH:3,RECOVERY:6,PAVILION:10,CARRY:14,WELCOME:18}
QI='resource:core.qi'


def owned(session,aid,source):
    return next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives',())
                 if r.get('block')==BLOCK and r.get('feature_id')==source
                 and int(r['numbers']['cl'])>=LEVELS[source]),None)


def family(actor):
    return actor.setdefault('hearthfire',{})


def active_camps(session,aid=None):
    from .qi_hearthfire_persistence import family_state
    now=session.clock();out=[]
    for owner in session.state['actors']:
        c=family_state(session,owner).get('camp',{})
        if (aid is None or owner==aid) and owned(session,owner,HEARTH) and c.get('until',0)>now and not c.get('destroyed') and not c.get('suppressed') and c.get('scene',session.state['battlefield'].get('stable_id'))==session.state['battlefield'].get('stable_id'):
            out.append((owner,c))
    return out


def contains(session,camp,aid,radius=15,center=None):
    p=Position.model_validate(session.state['actors'][aid]['position'])
    c=Position.model_validate(center or camp['position'])
    return session.grid.distance_ft(p,c)<=radius


def eligible(session,aid,*,recovery=False):
    return [(o,c) for o,c in active_camps(session) if aid in c['invited'] and contains(session,c,aid)
            and (not recovery or owned(session,o,RECOVERY))]


def export(session):
    """Seal actual committed camp state into the next native encounter genesis."""
    now=session.clock()
    camps=[]
    from .qi_hearthfire_persistence import family_state
    for owner in session.state['actors']:
        c=family_state(session,owner).get('camp',{})
        if not c or c.get('destroyed') or c.get('until',0)<=now:
            continue
        row=deepcopy(c);row['remaining']=max(0,int(c['until']-now));row['owner']=owner
        if row.get('pavilion'):
            row['pavilion']['remaining']=max(0,int(row['pavilion']['until']-now))
        camps.append(row)
    from .qi_hearthfire_persistence import persist,hydrate
    for aid,a in session.state['actors'].items():
        hydrate(session,aid)
        f=a.get('hearthfire',{})
        persist(session,aid)
        if not camps and not f:
            continue
        a['bundle']['hearthfire_setup']={'camps':deepcopy([c for c in camps if c['owner']==aid]),
            'recipient':deepcopy({k:v for k,v in f.items() if k!='camp'}),'long_rests':a['long_rests']}
        a['bundle'].pop('bundle_sha256',None)
        a['bundle']['bundle_sha256']=canonical_sha256(a['bundle'])


@hook('journey_options')
def camp_options(session,aid):
    if session.state['phase']!='travel':
        return
    from .qi_hearthfire_persistence import family_state
    a=session.state['actors'][aid];out=[]
    def add(kind,label,payload=None):
        out.append({'id':kind+':'+str(len(out)),'kind':kind,'payload':payload or {},'label':label})
    if owned(session,aid,HEARTH) and not a['incapacitated'] and a['resources'].get(QI,0)>=1:
        # Every legal location remains available. The owner then supplies its
        # invitations/host through the same structured command form.
        here=Position.model_validate(a['position'])
        for x in range(max(0,here.x-6),min(session.grid.width,here.x+7)):
            for y in range(max(0,here.y-6),min(session.grid.height,here.y+7)):
                p=Position(x=x,y=y)
                if session.grid.distance_ft(here,p)<=30 and session.grid.placement_legal(p,occupied_cells=set()):
                    add('hearth_kindle',f'Kindled Hearth: create or empower a contained flame at ({x}, {y}) for 8 hours; Action, 1 Qi.',
                        {'position':p.model_dump(mode='json'),'invited':[aid],'host':aid})
    camps=active_camps(session,aid)
    if camps and owned(session,aid,PAVILION) and a['resources'].get(QI,0)>=4:
        add('hearth_pavilion','Hearthward Pavilion: spend 10 minutes and 4 Qi to create a fixed 20-foot sanctuary for 8 hours.')
    if eligible(session,aid,recovery=True):
        add('hearth_short_rest',f'{a["name"]}: complete a one-hour short rest inside the Hearth aura.')
    f=family_state(session,aid)
    if f.get('recovery_ready') and a['travel_uses'].get(RECOVERY)!=a['long_rests'] and not snapshot_recovered(a):
        for benefit,label in recovery_choices({**a,'hearthfire':f}).items():
            add('hearth_recovery',f'Homefire Recovery for {a["name"]}: {label}; once per long rest, no action or Qi.',{'benefit':benefit})
    if camps:
        add('hearth_invite','Kindled Hearth: designate protected guests for this Hearth.',{'invited':camps[0][1]['invited']})
    if camps:
        guests=[{'id':who,'label':person['name']} for who,person in session.state['actors'].items()]
        for option in out:
            if option['kind'] in ('hearth_kindle','hearth_invite'):
                option['fields']={'invited':{'type':'multiple_creatures','options':guests},
                    **({'host':{'type':'creature','options':guests}} if option['kind']=='hearth_kindle' else {})}
        for kind,label,fields in [
            ('hearth_shelter','Civic Shelter: record ordinary people and the real physical space available; no food, beds or space are created.',
             {'people':'nonnegative_integer','capacity':'nonnegative_integer','record_id':'source_record','authority':'GM','expires_at':'future_scene_seconds'}),
            ('hearth_permit_weather','Weatherward: choose which ordinary rain, snow, wind, dust, ash, smoke and insects may enter.',
             {'permitted':['rain','snow','wind','dust','ash','smoke','insects']}),
            ('hearth_scene_end','Record the end of the meaningful scene; this does not complete a rest or recover Qi.',
             {'reason':'nonempty_text','authority':'GM'})]:
            out.append({'id':kind,'kind':kind,'label':label,'payload':{},'fields':fields,'auto_select':0})
    if active_camps(session):
        out.extend([{'id':kind,'kind':kind,'label':label,'payload':{},'fields':fields,'auto_select':0} for kind,label,fields in [
            ('hearth_hardship','Record this creature’s sourced environmental hardship or Exhaustion; no inferred anatomy or source tags.',
             {'cause':list(dict.fromkeys(CAUSES+PENALTIES)),'ordinary':'boolean','source_cl':'nonnegative_integer',
              'levels':'nonnegative_integer','record_id':'source_record','authority':'GM','expires_at':'future_scene_seconds','visibility':['public','subject']}),
            ('hearth_weather','Resolve a sourced environmental delivery against Weatherward; attacks, creatures, techniques and poison gas pass normally.',
             {'owner':'creature','phenomenon':['rain','snow','wind','dust','ash','smoke','insects','cold','heat','poison_gas'],
              'ordinary':'boolean','source_cl':'nonnegative_integer','delivery':['environment','attack','creature','technique'],
              'authority':'GM','record_id':'source_record','expires_at':'future_scene_seconds'}),
            ('hearth_speak','Speak inside a Private Hearth; the native utterance is delivered only to listeners who can understand it.',
             {'text':'spoken_words','expires_at':'future_scene_seconds'}),
            ('hearth_listen','Private Hearth: determine whether you understand speech inside a Pavilion; no private speech content is revealed.',
             {'owner':'creature','speaker':'creature','method':['auditory','check','telepathy','nonauditory','cultivation_effect'],
              'effect_source_cl':'nonnegative_integer','speech_record_id':'source_record'})]])
    return out or None


def recovery_choices(actor):
    result=dict(RECOVERY_LABELS)
    f=actor.get('hearthfire',{})
    if actor['exhaustion']>0 and f.get('travel_exhaustion_levels',0)>0:
        result['exhaustion:travel']='End one level of Exhaustion from committed travel exposure'
    for i,row in enumerate(f.get('hardships',[])):
        if row['until']<=f.get('clock',0):continue
        if row['cause'] in CAUSES and row.get('levels',0)>0:
            result['exhaustion:'+str(i)]='End one level of Exhaustion caused by '+row['cause'].replace('_',' ')
        if row['cause'] in PENALTIES and row['ordinary']:
            result['penalty:'+str(i)]='End an ordinary '+row['cause'].replace('_',' ')+' penalty'
    return result


@hook('journey_command')
def camp_command(session,aid,kind,payload):
    if not kind.startswith('hearth_'):
        return
    actors=session.state['actors'];a=actors[aid]
    from .qi_hearthfire_persistence import hydrate
    for who in actors:hydrate(session,who)
    if not any(owned(session,owner,HEARTH) for owner in actors):
        return
    require(not a['incapacitated'],'An incapacitated creature cannot perform this Hearthfire procedure.')
    if kind=='hearth_kindle':
        row=owned(session,aid,HEARTH)
        require(row is not None,'Kindled Hearth requires its acquired Qi subpath feature.')
        require(set(payload)=={'position','invited','host'},'Choose a Hearth location, host and invited creatures.')
        pos=Position.model_validate(payload['position']);here=Position.model_validate(a['position'])
        require(session.grid.distance_ft(here,pos)<=30 and session.grid.placement_legal(pos,occupied_cells=set()),'Choose a legal Hearth location within 30 feet.')
        invited=payload['invited']
        require(isinstance(invited,list) and len(set(invited))==len(invited) and set(invited)<=set(actors)
                and payload['host'] in actors,'Choose represented guests and host.')
        from ..journey_assets import JourneyAssetContext
        from .qi_hearthfire import create_hearth_object,retire_hearth_object
        from ..gate2_runtime_models import RuntimeObjectState
        world=JourneyAssetContext(session)
        old=family(a).get('camp',{}).get('native_object')
        if old:
            obj=world.state.objects.get(old['object_id']) or RuntimeObjectState.model_validate(old)
            retire_hearth_object(world,obj,HEARTH,aid)
        pay(a,1)
        obj=create_hearth_object(world,world.state.actors[aid],HEARTH,row['numbers'],pos)
        family(a)['camp']={'position':pos.model_dump(mode='json'),'invited':list(invited),'host':payload['host'],
            'until':int(session.clock())+28800,'scene':session.state['battlefield'].get('stable_id',''),'source_cl':int(row['numbers']['cl']),
            'hp':3*int(row['numbers']['cl']),'native_object':obj.model_dump(mode='json'),'ac':13,'bright_ft':15,'dim_ft':30,
            'source':HEARTH,'number':session.state['revision']+1}
        session.emit('HEARTH_KINDLED',aid,source=HEARTH,qi_cost=1,camp=deepcopy(family(a)['camp']),
                     text=f'{a["name"]} kindles one Hearth for 8 hours, replacing any previous Hearth.')
    elif kind=='hearth_invite':
        camps=active_camps(session,aid)
        require(camps and set(payload)=={'invited'} and isinstance(payload['invited'],list)
                and set(payload['invited'])<=set(actors),'Choose guests of your active Hearth.')
        camps[0][1]['invited']=list(dict.fromkeys(payload['invited']))
        session.emit('HEARTH_INVITATIONS',aid,source=HEARTH,invited=camps[0][1]['invited'])
    elif kind=='hearth_pavilion':
        camps=active_camps(session,aid)
        require(not payload and owned(session,aid,PAVILION) and camps,'Hearthward Pavilion requires its acquired feature and an active Kindled Hearth.')
        camp=camps[0][1]
        require(camp['until']>=session.clock()+600,'The Hearth must remain active throughout the ten-minute ritual.')
        pay(a,4);session.tick(600)
        camp=family(a)['camp']
        camp['pavilion']={'position':dict(camp['position']),'until':int(session.clock())+28800,
                           'physical_capacity':0,'permitted_weather':[]}
        session.emit('HEARTH_PAVILION',aid,source=PAVILION,qi_cost=4,ritual_seconds=600,
                     text=f'{a["name"]} completes Hearthward Pavilion: a fixed 20-foot-radius, 20-foot-high sanctuary for 8 hours.')
    elif kind=='hearth_short_rest':
        camps=eligible(session,aid,recovery=True)
        require(not payload and camps,'Complete the short rest inside an active Homefire Recovery aura.')
        require(any(c['until']>=session.clock()+3600 for _,c in camps),'The Hearth must last through the completed rest.')
        session.tick(3600)
        # A rest is a committed interval, not leaving/reentering or a menu read.
        family(a)['travel_exhaustion_levels']=min(a['exhaustion'],sum(int(e.get('levels',0)) for e in session.state['events'] if e.get('actor_id')==aid and e.get('kind')=='TRAVEL_EXHAUSTION'))
        family(a)['recovery_ready']=max(int(owned(session,o,RECOVERY)['numbers']['pb']) for o,c in camps)
        session.emit('HEARTH_SHORT_REST',aid,source=RECOVERY,duration_seconds=3600)
    elif kind=='hearth_recovery':
        f=family(a)
        require(set(payload)=={'benefit'} and f.get('recovery_ready') and a['travel_uses'].get(RECOVERY)!=a['long_rests']
                and not snapshot_recovered(a) and payload['benefit'] in recovery_choices(a),'Choose one available Homefire Recovery benefit, once per long rest.')
        benefit=payload['benefit'];pb=int(f['recovery_ready'])
        f['recovery_rest']=a['long_rests'];a['travel_uses'][RECOVERY]=a['long_rests'];f.pop('recovery_ready',None)
        if benefit=='temp_hp':f['temporary_hp']=max(f.get('temporary_hp',0),2*pb)
        elif benefit=='heal':
            maximum=a['bundle']['actor_template']['maximum_hp']
            snap=a.get('encounter_snapshot')
            if snap is not None and snap['current_hp']>0:
                snap['current_hp']=min(snap['maximum_hp'],snap['current_hp']+2*pb)
            else:f['hp']=min(maximum,f.get('hp',maximum)+2*pb)
        elif benefit=='fear':f['fear_scene']=session.state.get('hearth_scene',0)+2
        elif benefit=='exhaustion:travel':
            a['exhaustion']-=1;f['travel_exhaustion_levels']-=1
        else:
            typ,index=benefit.split(':');row=f['hardships'][int(index)]
            if typ=='exhaustion':
                row['levels']-=1;a['exhaustion']=max(0,a['exhaustion']-1)
            else:row['until']=int(session.clock())
        session.emit('HOMEFIRE_RECOVERY',aid,source=RECOVERY,benefit=benefit,amount=2*pb)
    elif kind=='hearth_hardship':
        # A source-specific GM input form: facts have an authority, subject,
        # source record, expiry and visibility. Unknown causes are rejected.
        required={'cause','ordinary','source_cl','levels','record_id','authority','expires_at','visibility'}
        require(set(payload)==required and payload['authority']=='GM' and payload['visibility'] in ('public','subject')
                and isinstance(payload['record_id'],str) and payload['record_id'].strip()
                and payload['cause'] in set(CAUSES+PENALTIES) and type(payload['ordinary']) is bool
                and integer(payload['source_cl']) and integer(payload['levels']) and integer(payload['expires_at'])
                and payload['expires_at']>session.clock(),'Record a typed, sourced, unexpired GM environmental hardship for this creature.')
        f=family(a);records=f.setdefault('hardships',[])
        require(not any(r['record_id']==payload['record_id'] for r in records),'This environmental source has already been recorded.')
        row={**payload,'actor_id':aid,'source':RECOVERY,'until':payload['expires_at']}
        immune=bool(eligible(session,aid)) and payload['ordinary'] and payload['cause'] in ('cold','rain','damp')
        if not immune:
            records.append(row)
            if payload['levels']:
                require(a['exhaustion']+payload['levels']<6,'Resolve lethal Exhaustion in combat before continuing.')
                a['exhaustion']+=payload['levels']
        session.emit('HEARTH_ENVIRONMENT',aid,source=RECOVERY,record_id=payload['record_id'],immune=int(immune),visibility=payload['visibility'])
    elif kind=='hearth_shelter':
        camps=active_camps(session,aid)
        require(camps and camps[0][1].get('pavilion') and set(payload)=={'people','capacity','authority','record_id','expires_at'}
                and payload['authority']=='GM' and integer(payload['people']) and integer(payload['capacity'])
                and integer(payload['expires_at']) and payload['expires_at']>session.clock()
                and isinstance(payload['record_id'],str) and payload['record_id'].strip(),
                'Record the actual physical capacity and ordinary people sheltered, with GM source and expiry.')
        camp=camps[0][1];p=camp['pavilion']
        require(p['until']>session.clock() and payload['people']<=min(payload['capacity'],10*camp['source_cl']),
                'Civic Shelter needs real space and shelters at most ten people per Qi Cultivation CL.')
        p.update(physical_capacity=payload['capacity'],people=payload['people'],space_record=dict(payload))
        session.emit('CIVIC_SHELTER',aid,source=PAVILION,people=payload['people'],capacity=payload['capacity'],record_id=payload['record_id'])
    elif kind=='hearth_permit_weather':
        camps=active_camps(session,aid)
        kinds=('rain','snow','wind','dust','ash','smoke','insects')
        require(camps and camps[0][1].get('pavilion') and set(payload)=={'permitted'}
                and isinstance(payload['permitted'],list) and set(payload['permitted'])<=set(kinds),
                'Choose which ordinary weather may enter your active Pavilion.')
        camps[0][1]['pavilion']['permitted_weather']=list(dict.fromkeys(payload['permitted']))
        session.emit('WEATHERWARD_PERMISSION',aid,source=PAVILION,permitted=payload['permitted'])
    elif kind=='hearth_weather':
        required={'owner','phenomenon','ordinary','source_cl','delivery','authority','record_id','expires_at'}
        require(set(payload)==required and payload['owner'] in actors and payload['authority']=='GM'
                and payload['phenomenon'] in ('rain','snow','wind','dust','ash','smoke','insects','cold','heat','poison_gas')
                and type(payload['ordinary']) is bool and integer(payload['source_cl'])
                and payload['delivery'] in ('environment','attack','creature','technique')
                and isinstance(payload['record_id'],str) and payload['record_id'].strip()
                and integer(payload['expires_at']) and payload['expires_at']>session.clock(),
                'Record an unexpired, source-scoped GM environmental delivery.')
        camps=active_camps(session,payload['owner'])
        require(camps,'Choose an active Kindled Hearth.')
        c=camps[0][1];p=c.get('pavilion',{})
        blocked=bool(p.get('until',0)>session.clock() and contains(session,c,aid,20,p['position'])
            and payload['ordinary'] and payload['delivery']=='environment'
            and payload['source_cl']<c['source_cl'] and payload['phenomenon'] in ('rain','snow','wind','dust','ash','smoke','insects')
            and payload['phenomenon'] not in p['permitted_weather'])
        family(a)['weather_result']={'record_id':payload['record_id'],'blocked':int(blocked),
                                     'source':PAVILION,'until':payload['expires_at']}
        # Wind/rain never douse the cultivated flame, even without a Pavilion.
        session.emit('WEATHERWARD_DELIVERY',aid,source=PAVILION,record_id=payload['record_id'],blocked=int(blocked),
                     extinguished=0,delivery=payload['delivery'],phenomenon=payload['phenomenon'])
    elif kind=='hearth_speak':
        require(set(payload)=={'text','expires_at'} and isinstance(payload['text'],str) and 0<len(payload['text'])<=1000
                and integer(payload['expires_at']) and payload['expires_at']>session.clock(),
                'Enter the words this creature actually speaks and their source expiry.')
        wards=[(o,c) for o,c in active_camps(session) if c.get('pavilion',{}).get('until',0)>session.clock()
               and contains(session,c,aid,20,c['pavilion']['position'])]
        require(wards,'The speaker must be inside an active Hearthward Pavilion.')
        owner,camp=wards[0]
        record='speech:'+session.state['journey_id']+':'+str(session.state['revision']+1)
        family(a).setdefault('speech_events',{})[record]={'speaker':aid,'authority_actor_id':aid,'owner':owner,
            'source':PAVILION,'seconds':int(session.clock()),'expires_at':payload['expires_at'],'text':payload['text']}
        session.emit('HEARTH_SPEECH',aid,source=PAVILION,record_id=record,authority_actor_id=aid,
                     expires_at=payload['expires_at'],text='Words spoken inside the Private Hearth; content is observer-scoped.')
    elif kind=='hearth_listen':
        required={'owner','speaker','method','effect_source_cl','speech_record_id'}
        require(set(payload)==required and payload['owner'] in actors and payload['speaker'] in actors
                and payload['method'] in ('auditory','telepathy','nonauditory','cultivation_effect','check')
                and integer(payload['effect_source_cl']) and isinstance(payload['speech_record_id'],str)
                and payload['speech_record_id'].strip(), 'Choose a represented speaker and the native information method.')
        speech=family(actors[payload['speaker']]).get('speech_events',{}).get(payload['speech_record_id'])
        require(speech is not None and speech['owner']==payload['owner'] and speech['authority_actor_id']==payload['speaker']
                and speech['expires_at']>session.clock() and speech['seconds']==session.clock(),
                'Private Hearth requires this speaker’s actual unexpired native speech event at the current delivery time.')
        camps=active_camps(session,payload['owner'])
        require(camps,'Choose an active Pavilion.')
        c=camps[0][1];p=c.get('pavilion',{})
        require(p.get('until',0)>session.clock() and contains(session,c,payload['speaker'],20,p['position']),
                'The speaker must be inside the active Pavilion.')
        heard=contains(session,c,aid,20,p['position'])
        method=payload['method']
        # These methods require real native abilities; narration cannot grant them.
        source_actions=a['bundle'].get('action_catalog',[])
        if method in ('telepathy','nonauditory','cultivation_effect'):
            require(any(((r.get('parameters') or {}).get('typed') or {}).get('communication_method')==method
                        and int((((r.get('parameters') or {}).get('typed') or {}).get('numbers') or {}).get('cl',0))>=payload['effect_source_cl']
                        for r in source_actions), 'Use a genuinely acquired nonauditory or communication effect.')
            heard=heard or method in ('telepathy','nonauditory') or payload['effect_source_cl']>c['source_cl']
        roll=None
        if not heard and method=='check':
            from ..gate2_rolls import DeterministicRollAuthority
            roller=DeterministicRollAuthority(session.state['journey_id']+':private-hearth:'+str(session.state['revision']))
            bonus=int(a['bundle'].get('hearthfire_checks',{}).get('perception',0))
            roll=roller.d20(modifier=bonus,actor_id=aid,reason='PRIVATE_HEARTH')
            dc=int(owned(session,payload['owner'],PAVILION)['numbers']['save_dc'])
            heard=roll.total>=dc
        family(a)['private_hearth_result']={'record_id':payload['speech_record_id'],'understood':int(heard),
            'owner_id':payload['owner'],'source':PAVILION,'expires_at':speech['expires_at'],
            **({'words':speech['text']} if heard else {})}
        # Store the information result, never expose the private speech content.
        session.emit('PRIVATE_HEARTH_INFORMATION',aid,source=PAVILION,record_id=payload['speech_record_id'],
                     understood=int(heard),method=method,**({'roll':roll.model_dump(mode='json')} if roll else {}))
    elif kind=='hearth_scene_end':
        require(set(payload)=={'reason','authority'} and payload['authority']=='GM' and isinstance(payload['reason'],str)
                and payload['reason'].strip(),'The GM must state why the meaningful scene ended.')
        session.state['hearth_scene']=session.state.get('hearth_scene',0)+1
        for other in actors.values():
            for action in other['bundle'].get('action_catalog',()):
                if ((action.get('parameters') or {}).get('typed') or {}).get('source')==WELCOME:
                    for pool,amount in action.get('costs',()):
                        if pool.startswith('resource:uses.'):
                            other['resources'][pool]=amount
            f=other.get('hearthfire',{})
            if f.get('fear_scene',999)<=session.state['hearth_scene']:
                f.pop('fear_scene',None)
                snapshot=other.get('encounter_snapshot')
                if snapshot:
                    import json
                    snapshot['conditions']={k:v for k,v in snapshot['conditions'].items()
                        if json.loads(v).get('condition_id')!='condition:typed.homefire_courage'}
        session.emit('HEARTH_SCENE_ENDED',aid,source=HEARTH,reason=payload['reason'])
    else:
        return
    export(session)
    return True


def pay(actor,amount):
    require(actor['resources'].get(QI,0)>=amount,'Not enough Qi for this Hearthfire procedure.')
    actor['resources'][QI]-=amount


@hook('journey_elapsed')
def camp_elapsed(session,aid,before,seconds,moving):
    from .qi_hearthfire_persistence import hydrate
    hydrate(session,aid)
    f=session.state['actors'][aid].get('hearthfire')
    if f is None:return
    f['clock']=int(session.clock())
    camp=f.get('camp',{})
    if camp.get('native_object') and camp.get('until',0)<=session.clock():
        from ..journey_assets import JourneyAssetContext
        from ..gate2_runtime_models import RuntimeObjectState
        from .qi_hearthfire import retire_hearth_object
        world=JourneyAssetContext(session)
        obj=world.state.objects.get(camp['native_object']['object_id']) or RuntimeObjectState.model_validate(camp['native_object'])
        if not obj.destroyed:
            retire_hearth_object(world,obj,HEARTH,aid)
            camp['native_object']=world.state.objects[obj.object_id].model_dump(mode='json')
    export(session)


@hook('journey_rest')
def camp_long_rest(session,aid):
    f=session.state['actors'][aid].get('hearthfire')
    if f:
        f.pop('recovery_ready',None)
    snapshot=session.state['actors'][aid].get('encounter_snapshot')
    if snapshot:
        import json
        snapshot['conditions']={k:v for k,v in snapshot['conditions'].items()
            if json.loads(v).get('condition_id')!='condition:typed.homefire_recovered'}
    if f or snapshot:
        export(session)


@hook('journey_properties')
def camp_properties(session,aid):
    camps=[(o,c) for o,c in active_camps(session) if aid in c['invited'] and (contains(session,c,aid)
        or c.get('pavilion',{}).get('until',0)>session.clock() and contains(session,c,aid,20,c['pavilion']['position']))]
    if not camps:
        info=session.state['actors'][aid].get('hearthfire',{}).get('private_hearth_result')
        return {'hearth_private_information':info} if info and info.get('expires_at',0)>session.clock() else None
    pavilion=any(c.get('pavilion',{}).get('until',0)>session.clock()
                 and contains(session,c,aid,20,c['pavilion']['position']) for _,c in camps)
    return {'hearth_weather_discomfort_immune':1,'hearth_ac_bonus':int(pavilion),
            'hearth_frightened_advantage':1,'hearth_environmental_cold_advantage':1,
            'hearth_exposure_exhaustion_advantage':1,
            'hearth_charmed_advantage':int(pavilion),'hearth_smoke_advantage':int(pavilion),
            **({'hearth_private_information':a_info} if (a_info:=session.state['actors'][aid].get('hearthfire',{}).get('private_hearth_result')) else {})}


@hook('match_initialize')
def camp_combat_setup(engine):
    """Create the same native objects/zones from committed elapsed camp state."""
    from ..gate2_runtime_models import RuntimeObjectState, ZoneState
    from .placed import context
    from .. import zones
    from .qi_hearthfire_sanctuary import RECOVERED,FEAR,native_source_action
    initialized=False
    for bundle in engine.typed_bundle_documents:
        from .qi_hearthfire_persistence import setup_from_snapshot
        setup=bundle.get('hearthfire_setup') or setup_from_snapshot(bundle);aid=bundle['actor_id']
        if not setup or aid not in engine.state.actors:continue
        actor=engine.state.actors[aid];initialized=True
        f=setup['recipient']
        if f.get('temporary_hp',0):
            actor.temporary_hp=max(actor.temporary_hp,f['temporary_hp'])
        if f.get('recovery_rest')==setup['long_rests']:
            engine._apply_condition(actor,RECOVERED,RECOVERY,aid,expires_on='UNTIL_REMOVED',data={'label':'Homefire Recovery received until a long rest'})
        if 'fear_scene' in f:
            engine._apply_condition(actor,FEAR,RECOVERY,aid,expires_on='UNTIL_REMOVED',data={'through_next_scene':1})
        rows={r.get('feature_id'):r for r in bundle.get('typed_passives',()) if r.get('block')==BLOCK}
        for camp in setup['camps']:
            if camp['remaining']<=0 or HEARTH not in rows:continue
            oid=f'object:hearth.{aid}.camp.{camp["number"]}'
            obj=RuntimeObjectState(object_id=oid,object_kind='cultivation_asset',position=Position.model_validate(camp['position']),
                owner_id=aid,unattended=True,flammable=False,ac=13,current_hp=camp['hp'],maximum_hp=3*camp['source_cl'],
                damage_immunities=('FIRE','POISON','PSYCHIC'),component={'name':'Kindled Hearth','size':'Small','source_cl':camp['source_cl'],'bright_ft':15,'dim_ft':30})
            if camp.get('native_object'):
                obj=RuntimeObjectState.model_validate(camp['native_object'])
                oid=obj.object_id
            if camp.get('suppressed'):
                obj=obj.model_copy(update={'suppressed':True})
            engine._update_object(obj,HEARTH,aid)
            ctx=context(engine,actor,HEARTH,rows[HEARTH]['numbers'],action=native_source_action(engine,actor,HEARTH))
            # Prospective construction avoids manufacturing an action or an
            # activation receipt. These are the existing journey's objects.
            spec={'name':'Kindled Hearth','shape':'sphere','size_ft':15,'duration':{'kind':'rounds','amount':max(1,(camp['remaining']+5)//6)},
                'profile':{'hearth_object':oid,'chosen_recipients':camp['invited']},'inside':[],'triggers':[],
                'visual':{'material':'fire','light':{'radius_ft':15,'level':'bright','dim_radius_ft':30}}}
            z=zones.prospective_zone(ctx,spec,obj.position,zone_id=f'zone:hearth.camp.{aid}.{camp["number"]}')
            engine.state.zones[z.zone_id]=z
            engine._append_event('ZONE_CREATED',HEARTH,actor_id=aid,payload={'zone':z.model_dump(mode='json')})
            p=camp.get('pavilion')
            if p and p['remaining']>0 and PAVILION in rows:
                sub=context(engine,actor,PAVILION,rows[PAVILION]['numbers'],action=native_source_action(engine,actor,PAVILION))
                spec={'name':'Hearthward Pavilion','shape':'cylinder','size_ft':20,'height_ft':20,
                    'duration':{'kind':'rounds','amount':max(1,(p['remaining']+5)//6)},
                    'profile':{'pavilion':1,'hearth_anchor':oid,'hearth_zone':z.zone_id,'chosen_recipients':camp['invited'],
                               'civic_center':p['position'],'civic_capacity':min(p['physical_capacity'],10*camp['source_cl']),
                               'permitted_weather':p.get('permitted_weather',[])},'inside':[],'triggers':[]}
                ward=zones.prospective_zone(sub,spec,Position.model_validate(p['position']),zone_id='zone:pavilion.'+aid)
                engine.state.zones[ward.zone_id]=ward
                engine._append_event('ZONE_CREATED',PAVILION,actor_id=aid,payload={'zone':ward.model_dump(mode='json')})
    for bundle in engine.typed_bundle_documents:
        setup=bundle.get('hearthfire_setup')
        if not setup:continue
        result=setup['recipient'].get('private_hearth_result')
        viewer=engine.state.actors.get(bundle['actor_id'])
        owner=engine.state.actors.get((result or {}).get('owner_id',''))
        if result and viewer is not None and owner is not None:
            from ..observer_information import publish
            publish(engine,viewer,PAVILION,owner,'declaration',
                {'summary':'Private Hearth: '+('you understand the spoken words.' if result['understood'] else 'the speech remains indistinct.'),
                 'record_id':result['record_id'],**({'words':result['words']} if result['understood'] else {})},'UNTIL_REMOVED')
    return True if initialized else None


@hook('journey_state_changed')
def camp_encounter_entry(session,aid):
    if session.state['phase']!='combat':
        return
    f=session.state['actors'][aid].get('hearthfire')
    if f:
        # CombatService has already copied the sealed transfer into the new
        # encounter. A later resume must use the actual surviving temp HP,
        # never apply the same instantaneous recovery a second time.
        f.pop('temporary_hp',None)
        f.pop('hp',None)
        export(session)


def snapshot_recovered(actor):
    import json
    return any(json.loads(v).get('condition_id')=='condition:typed.homefire_recovered'
               for v in (actor.get('encounter_snapshot') or {}).get('conditions',{}).values())
