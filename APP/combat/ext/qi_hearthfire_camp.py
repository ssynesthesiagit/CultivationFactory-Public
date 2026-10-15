"""Native Hearthfire camp procedures on the existing Journey transaction API.

The family owns its camp, invitations, rest receipts and sanctuary declarations.
It consumes compiled acquisition rows; it never grants a feature or a generic
inventory/fact/actor service. Commands are source scoped, revision checked, and
cold loaded by JourneyStore. UI/API callers use journey_menu/journey_act.
"""
from copy import deepcopy
from . import hook
from .qi_hearthfire import HEARTH, RECOVERY, CARRY, BLOCK,FEATURE_LEVELS
from .qi_hearthfire_sanctuary import PAVILION, WELCOME, RECOVERY_LABELS, CAUSES, PENALTIES
from ..journey import require, integer
from ..gate2_runtime_models import Position
from ..canonical import canonical_sha256

LEVELS=FEATURE_LEVELS
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
        live=session.state.get('runtime_objects',{}).get(c.get('native_object',{}).get('object_id'))
        if live and (live.get('destroyed') or not live.get('current_hp') or live.get('suppressed')):
            continue
        if (aid is None or owner==aid) and owned(session,owner,HEARTH) and c.get('until',0)>now and not c.get('destroyed') and not c.get('suppressed') and c.get('scene',session.state['battlefield'].get('stable_id'))==session.state['battlefield'].get('stable_id'):
            out.append((owner,c))
    return out


def contains(session,camp,aid,radius=15,center=None,*,shape='sphere',height=None):
    """Native volume membership; no cylinder is widened into a sphere."""
    if shape=='sphere' and radius==15 and camp.get('carry',{}).get('until',0)>session.clock():radius=20
    from types import SimpleNamespace
    from ..journey_assets import JourneyAssetContext
    from ..spatial_areas import positions_inside_zone
    from ..space import volume
    world=JourneyAssetContext(session)
    point=Position.model_validate(center or camp['position'])
    spec={'shape':shape,'size_ft':radius,**({'height_ft':height} if height is not None else {})}
    query=SimpleNamespace(center=point,radius_cells=radius//session.grid.square_size_ft,trigger_profile=spec,affected_cells=())
    actor=world.state.actors[aid]
    return positions_inside_zone(world,volume(actor.position,world.actor_footprints[aid]),query)


def pavilion_center(session,camp):
    return camp['position'] if camp.get('carry',{}).get('until',0)>session.clock() else camp['pavilion']['position']


def eligible(session,aid,*,recovery=False):
    return [(o,c) for o,c in active_camps(session) if (recovery or aid in c['invited']) and contains(session,c,aid)
            and (not recovery or owned(session,o,RECOVERY))]


def export(session):
    """Seal actual committed camp state into the next native encounter genesis."""
    now=session.clock()
    camps=[]
    from .qi_hearthfire_persistence import family_state
    for owner in session.state['actors']:
        c=family_state(session,owner).get('camp',{})
        if c.get('native_object'):
            live=session.state.get('runtime_objects',{}).get(c['native_object']['object_id'])
            if live and live!=c['native_object']:
                c={**c,'native_object':live,'hp':live.get('current_hp',0),
                   'destroyed':int(bool(live.get('destroyed') or not live.get('current_hp'))),
                   'suppressed':int(bool(live.get('suppressed')))}
        if not c or c.get('destroyed') or c.get('until',0)<=now or c.get('scene')!=session.state['battlefield'].get('stable_id',''):
            continue
        row=deepcopy(c)
        if (live:=session.state.get('runtime_objects',{}).get(c.get('native_object',{}).get('object_id'))) is not None:
            row['native_object']=deepcopy(live);row['hp']=live['current_hp']
        if row.get('carry'):
            row['carry']['remaining']=max(0,int(row['carry']['until']-now))
        row['remaining']=max(0,int(c['until']-now));row['owner']=owner
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
        if f.get('welcome'):
            f['welcome']['remaining']=max(0,int(f['welcome']['until']-now))
        a['bundle']['hearthfire_setup']={'camps':deepcopy([c for c in camps if c['owner']==aid]),
            'recipient':deepcopy({k:v for k,v in f.items() if k!='camp' and (k!='private_hearth_result' or v['expires_at']>now)}),'long_rests':a['long_rests']}
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
        from ..journey_assets import JourneyAssetContext
        from ..asset_anchor_runtime import legal_placement
        world=JourneyAssetContext(session)
        for x in range(max(0,here.x-6),min(session.grid.width,here.x+7)):
            for y in range(max(0,here.y-6),min(session.grid.height,here.y+7)):
                p=Position(x=x,y=y)
                if session.grid.distance_ft(here,p)<=30 and legal_placement(world,[p],5):
                    add('hearth_kindle',f'Kindled Hearth: create or empower a contained flame at ({x}, {y}) for 8 hours; Action, 1 Qi.',
                        {'position':p.model_dump(mode='json'),'invited':[aid],'host':aid})
    if owned(session,aid,HEARTH) and not a['incapacitated'] and a['resources'].get(QI,0)>=1:
        from ..journey_assets import JourneyAssetContext
        from .qi_hearthfire_items import empowerable
        for obj in JourneyAssetContext(session).state.objects.values():
            if empowerable(obj) and session.grid.distance_ft(Position.model_validate(a['position']),obj.position)<=30:
                add('hearth_kindle','Kindled Hearth: empower the existing '+str(obj.component.get('name','contained flame'))+' for 8 hours; Action, 1 Qi.',
                    {'position':obj.position.model_dump(mode='json'),'existing':obj.object_id,'invited':[aid],'host':aid})
    camps=active_camps(session,aid)
    if camps and owned(session,aid,PAVILION) and a['resources'].get(QI,0)>=4:
        add('hearth_pavilion','Hearthward Pavilion: spend 10 minutes and 4 Qi to create a fixed 20-foot sanctuary for 8 hours.')
    if camps and owned(session,aid,CARRY) and a['resources'].get(QI,0)>=4:
        add('hearth_carry','Carry the Hearth: choose its center for 1 minute; Bonus Action, 4 Qi.',{'center':aid,'damage_type':'FIRE'})
        out[-1].update(auto_select=0,fields={'center':{'type':'creature_or_domain_armament','options':carry_centers(session,aid,camps[0][1])},'damage_type':['FIRE','RADIANT']})
    if owned(session,aid,WELCOME) and a['resources'].get(QI,0)>=8 and a['travel_uses'].get(WELCOME)!=session.state.get('hearth_scene',0):
        add('hearth_welcome','Flame That Welcomes All: choose a 40-foot sanctuary and protected allies for 1 minute; Action, 8 Qi, Concentration, once per scene.',{'center':'self','invited':[aid]})
        out[-1].update(auto_select=0,fields={'center':['self',*(['hearth'] if camps else [])],'invited':list(session.state['actors'])})
    if family_state(session,aid).get('welcome',{}).get('until',0)>session.clock():
        add('hearth_end_welcome','End Concentration on Flame That Welcomes All; no action or Qi cost.')
    if eligible(session,aid,recovery=True):
        add('hearth_short_rest',f'{a["name"]}: complete a one-hour short rest inside the Hearth aura.')
    f=family_state(session,aid)
    if f.get('recovery_ready') and a['travel_uses'].get(RECOVERY)!=a['long_rests'] and not snapshot_recovered(a):
        for benefit,label in recovery_choices({**a,'hearthfire':f}).items():
            add('hearth_recovery',f'Homefire Recovery for {a["name"]}: {label}; once per long rest, no action or Qi.',{'benefit':benefit})
    if camps:
        add('hearth_invite','Kindled Hearth: designate protected guests for this Hearth.',{'invited':camps[0][1]['invited']})
    if any(o['kind'] in ('hearth_kindle','hearth_invite') for o in out):
        guests=[{'id':who,'label':person['name']} for who,person in session.state['actors'].items()]
        for option in out:
            if option['kind'] in ('hearth_kindle','hearth_invite'):
                option['fields']={'invited':{'type':'multiple_creatures','options':guests},
                    **({'host':{'type':'creature','options':guests}} if option['kind']=='hearth_kindle' else {})}
    if camps:
        for kind,label,fields in [
            ('hearth_shelter','Civic Shelter: record ordinary people and the real physical space available; no food, beds or space are created.',
             {'people':'nonnegative_integer','capacity':'nonnegative_integer','record_id':'source_record','authority':'GM','expires_at':'future_scene_seconds'}),
            ('hearth_permit_weather','Weatherward: choose which ordinary rain, snow, wind, dust, ash, smoke and insects may enter.',
             {'permitted':['rain','snow','wind','dust','ash','smoke','insects']}),
]:
            if kind in ('hearth_shelter','hearth_permit_weather') and not camps[0][1].get('pavilion',{}).get('until',0)>session.clock():continue
            out.append({'id':kind,'kind':kind,'label':label,'payload':{},'fields':fields,'auto_select':0})
    if active_camps(session):
        out.extend([{'id':kind,'kind':kind,'label':label,'payload':{},'fields':fields,'auto_select':0} for kind,label,fields in [
            ('hearth_hardship','Record this creature’s sourced environmental hardship or Exhaustion; no inferred anatomy or source tags.',
             {'cause':list(dict.fromkeys(CAUSES+PENALTIES)),'ordinary':'boolean','source_cl':'nonnegative_integer',
              'levels':'nonnegative_integer','penalty':{'speed_penalty_ft':'integer_1_to_30'},'record_id':'source_record','authority':'controller','expires_at':'future_scene_seconds','visibility':['public','subject']}),
            ('hearth_weather','Resolve a sourced environmental delivery against Weatherward; attacks, creatures, techniques and poison gas pass normally.',
             {'owner':'creature','phenomenon':['rain','snow','wind','dust','ash','smoke','insects','cold','heat','poison_gas'],
              'ordinary':'boolean','source_cl':'nonnegative_integer','delivery':['environment','attack','creature','technique'],
              'authority':'GM','record_id':'source_record','expires_at':'future_scene_seconds'}),
            ('hearth_speak','Speak inside a Private Hearth; the native utterance is delivered only to listeners who can understand it.',
             {'text':'spoken_words','expires_at':'future_scene_seconds','delivery':['speech','visible_gesture'],'recipients':'creatures'}),
            ('hearth_listen','Private Hearth: determine whether you understand speech inside a Pavilion; no private speech content is revealed.',
             {'owner':'creature','speaker':'creature','method':['auditory','check','telepathy','nonauditory','cultivation_effect'],
              'effect_source_cl':'nonnegative_integer','speech_record_id':'source_record'})]])
    for option in out:
        if option['kind'] in WORLD_COMMANDS:
            option['fields']={'record_id':'native_table_owner_source_record'}
            option['label']+=' Requires a live native table-owner declaration; no action or Qi cost.'
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
        if row['cause'] in PENALTIES and row['ordinary'] and row.get('condition_instance_id') in (actor.get('encounter_snapshot') or {}).get('conditions',{}):
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
    world_record=None
    if kind in WORLD_COMMANDS:
        payload,world_record=world_payload(session,aid,kind,payload)
    require(kind in WORLD_COMMANDS or not a['incapacitated'],'An incapacitated creature cannot perform this Hearthfire procedure.')
    if kind=='hearth_kindle':
        row=owned(session,aid,HEARTH)
        require(row is not None,'Kindled Hearth requires its acquired Qi subpath feature.')
        require(set(payload) in ({'position','invited','host'},{'position','invited','host','existing'}),'Choose a Hearth location, host and invited creatures.')
        pos=Position.model_validate(payload['position']);here=Position.model_validate(a['position'])
        require(session.grid.distance_ft(here,pos)<=30 and ('existing' in payload or session.grid.placement_legal(pos,occupied_cells=set())),'Choose a legal Hearth location within 30 feet.')
        invited=payload['invited']
        require(isinstance(invited,list) and len(set(invited))==len(invited) and set(invited)<=set(actors)
                and payload['host'] in actors,'Choose represented guests and host.')
        from ..journey_assets import JourneyAssetContext
        from .qi_hearthfire import create_hearth_object,retire_hearth_object
        from ..gate2_runtime_models import RuntimeObjectState
        world=JourneyAssetContext(session)
        existing=world.state.objects.get(payload.get('existing',''))
        if 'existing' in payload:
            from .qi_hearthfire_items import empowerable
            require(existing is not None and empowerable(existing) and existing.position==pos,'Choose the actual existing contained flame at its native location.')
        old_camp=family(a).get('camp',{});old=old_camp.get('native_object')
        if old:
            if old_camp.get('scene')==session.state['battlefield'].get('stable_id',''):
                obj=world.state.objects.get(old['object_id']) or RuntimeObjectState.model_validate(old)
                retire_hearth_object(world,obj,HEARTH,aid)
            else:
                from .qi_hearthfire import mundane_hearth_object,remember_hearth_item
                restored=mundane_hearth_object(RuntimeObjectState.model_validate(old))
                if restored is not None:remember_hearth_item(family(a),old_camp['scene'],restored)
                session.emit('HEARTH_OLD_SCENE_ENDED',aid,source=HEARTH,scene=old_camp.get('scene',''),object_id=old['object_id'])
        pay(a,1)
        if existing is not None:existing=world.state.objects.get(existing.object_id,existing)
        obj=create_hearth_object(world,world.state.actors[aid],HEARTH,row['numbers'],pos,existing=existing)
        family(a)['camp']={'position':pos.model_dump(mode='json'),'invited':list(invited),'host':payload['host'],
            'until':int(session.clock())+28800,'scene':session.state['battlefield'].get('stable_id',''),'source_cl':int(row['numbers']['cl']),
            'hp':3*int(row['numbers']['cl']),'empowered_real':int(existing is not None),'native_object':obj.model_dump(mode='json'),'ac':13,'bright_ft':15,'dim_ft':30,
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
        require(camp['until']>session.clock()+600,'The Hearth must remain active throughout the ten-minute ritual.')
        pay(a,4);session.tick(600)
        camp=family(a)['camp']
        camp['pavilion']={'position':dict(camp['position']),'until':int(session.clock())+28800,
                           'physical_capacity':0,'permitted_weather':[]}
        session.emit('HEARTH_PAVILION',aid,source=PAVILION,qi_cost=4,ritual_seconds=600,
                     text=f'{a["name"]} completes Hearthward Pavilion: a fixed 20-foot-radius, 20-foot-high sanctuary for 8 hours.')
    elif kind=='hearth_carry':
        camps=active_camps(session,aid)
        require(camps and owned(session,aid,CARRY) and set(payload)=={'center','damage_type'} and payload['damage_type'] in ('FIRE','RADIANT'),
                'Carry the Hearth needs its acquired feature, an active Hearth and one legal center.')
        camp=camps[0][1];center=payload['center']
        require(center in carry_centers(session,aid,camp),'Choose yourself, your manifested Domain Armament, or the actual item holder.')
        if center not in (aid,'domain_armament'):
            from ..fact_consent_admission import read
            consent=read(session,CARRY,center,'carry_hearth_consent',camp['native_object']['object_id'],aid)
            require(consent and consent['value']==1,'The real item holder must personally consent to carry this Hearth.')
        pay(a,4)
        camp['carry']={'center':center,'until':int(session.clock())+60,'damage_type':payload['damage_type']}
        sync_camp_carrier(session,aid,camp)
        session.emit('HEARTH_CARRIED',aid,source=CARRY,center=center,duration_seconds=60,qi_cost=4)
    elif kind=='hearth_welcome':
        row=owned(session,aid,WELCOME)
        require(row and set(payload)=={'center','invited'} and payload['center'] in ('self','hearth')
                and isinstance(payload['invited'],list) and len(payload['invited'])==len(set(payload['invited']))
                and set(payload['invited'])<=set(actors),'Choose this acquired sanctuary’s center and protected party members.')
        scene=session.state.get('hearth_scene',0)
        require(a['travel_uses'].get(WELCOME)!=scene,'Flame That Welcomes All is available once per meaningful scene.')
        camps=active_camps(session,aid)
        require(payload['center']=='self' or camps,'The selected Hearth must be active.')
        pay(a,8);a['travel_uses'][WELCOME]=scene
        for action in a['bundle'].get('action_catalog',()):
            if ((action.get('parameters') or {}).get('typed') or {}).get('source')==WELCOME:
                for pool,amount in action.get('costs',()):
                    if pool.startswith('resource:uses.'):
                        require(a['resources'].get(pool,0)>=amount,'This scene’s Flame That Welcomes All use is spent.')
                        a['resources'][pool]-=amount
                break
        position=a['position'] if payload['center']=='self' else camps[0][1]['position']
        field={'until':int(session.clock())+60,'position':dict(position),'center':payload['center'],
               'invited':list(payload['invited']),'scene':session.state['battlefield'].get('stable_id',''),
               'concentration':1,'source_cl':int(row['numbers']['cl']),'pb':int(row['numbers']['pb'])}
        family(a)['welcome']=field
        for target in field['invited']:
            if contains(session,field,target,40,shape='cylinder',height=40) and actors[target]['travel_uses'].get(RECOVERY)!=actors[target]['long_rests'] and not snapshot_recovered(actors[target]):
                family(actors[target])['recovery_ready']=field['pb']
        session.emit('HEARTH_WELCOME',aid,source=WELCOME,qi_cost=8,duration_seconds=60,concentration=1,
                     center=payload['center'],invited=field['invited'])
    elif kind=='hearth_end_welcome':
        require(not payload and family(a).get('welcome'),'You are not maintaining Flame That Welcomes All.')
        family(a).pop('welcome',None)
        session.emit('HEARTH_CONCENTRATION_ENDED',aid,source=WELCOME)
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
        elif benefit=='fear':
            f['fear_scene']=session.state.get('hearth_scene',0)+2;f['fear_boundaries']=2
        elif benefit=='exhaustion:travel':
            a['exhaustion']-=1;f['travel_exhaustion_levels']-=1
        else:
            typ,index=benefit.split(':');row=f['hardships'][int(index)]
            if typ=='exhaustion':
                row['levels']-=1;a['exhaustion']=max(0,a['exhaustion']-1)
            else:
                iid=row.get('condition_instance_id')
                require(iid is not None and iid in (a.get('encounter_snapshot') or {}).get('conditions',{}),
                        'The ordinary environmental penalty needs its committed native condition.')
                del a['encounter_snapshot']['conditions'][iid]
                row['until']=int(session.clock())
        session.emit('HOMEFIRE_RECOVERY',aid,source=RECOVERY,benefit=benefit,amount=2*pb)
    elif kind=='hearth_hardship':
        # A subject-controller input form: facts have an authority, subject,
        # source record, expiry and visibility. Unknown causes are rejected.
        required={'cause','ordinary','source_cl','levels','record_id','authority','expires_at','visibility'}
        require(set(payload) in (required,required|{'penalty'}) and payload['authority'] in ('controller','GM') and payload['visibility'] in ('public','subject')
                and isinstance(payload['record_id'],str) and payload['record_id'].strip()
                and payload['cause'] in set(CAUSES+PENALTIES) and type(payload['ordinary']) is bool
                and integer(payload['source_cl']) and integer(payload['levels']) and integer(payload['expires_at'])
                and payload['expires_at']>session.clock(),'Record this creature’s typed, sourced, unexpired environmental experience.')
        f=family(a);records=f.setdefault('hardships',[])
        require(not any(r['record_id']==payload['record_id'] for r in records),'This environmental source has already been recorded.')
        from ..fact_consent_admission import declare
        receipt=declare(session,aid,{'source':RECOVERY,'subject':aid,'kind':'environmental_history','scope':payload['record_id'],
            'value':{'cause':payload['cause'],'ordinary':int(payload['ordinary'])},'expires_at':payload['expires_at'],
            'readers':[owner for owner,_ in eligible(session,aid,recovery=True)]})
        row={**payload,'authority':aid,'world_receipt_id':world_record['receipt_id'],'receipt_id':receipt,'actor_id':aid,'source':RECOVERY,'until':payload['expires_at']}
        immune=payload['ordinary'] and (
            bool(eligible(session,aid)) and not payload['levels'] and not payload.get('penalty') and payload['cause'] in ('cold','rain','damp')
            or bool(welcome_fields(session,aid)) and payload['cause'] in ('cold','rain','damp','smoke','ordinary_smoke'))
        if not immune:
            if payload.get('penalty'):
                penalty=payload['penalty']
                require(set(penalty)=={'speed_penalty_ft'} and integer(penalty['speed_penalty_ft'],1)
                        and penalty['speed_penalty_ft']<=30,'Choose a concrete ordinary environmental Speed penalty from 1 through 30 feet.')
                from .qi_hearthfire_persistence import persist
                from ..gate2_runtime_models import ConditionInstance
                persist(session,aid)
                iid='condition:environment:'+receipt
                c=ConditionInstance(instance_id=iid,condition_id='condition:typed.hearth_environmental_penalty',
                    source_definition_id=RECOVERY,source_actor_id=aid,target_id=aid,applied_sequence=len(session.state['events'])+1,
                    expires_on='UNTIL_REMOVED',data={'environmental_cause':payload['cause'],'ordinary':int(payload['ordinary']),
                        'record_id':receipt,'speed_delta':-penalty['speed_penalty_ft'],
                        'label':payload['cause'].replace('_',' ').title()+': Speed reduced by '+str(penalty['speed_penalty_ft'])+' feet'})
                a['encounter_snapshot']['conditions'][iid]=c.model_dump_json()
                row['condition_instance_id']=iid
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
        p.update(physical_capacity=payload['capacity'],people=payload['people'],space_record={'receipt_id':world_record['receipt_id'],'expires_at':world_record['expires_at']})
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
        welcome_immune=payload['ordinary'] and payload['delivery']=='environment' and bool(welcome_fields(session,aid)) and payload['phenomenon'] in ('rain','snow','wind','ash','smoke','cold','heat')
        blocked=welcome_immune or bool(p.get('until',0)>session.clock() and contains(session,c,aid,20,pavilion_center(session,c),shape='cylinder',height=20)
            and payload['ordinary'] and payload['delivery']=='environment'
            and payload['source_cl']<c['source_cl'] and payload['phenomenon'] in ('rain','snow','wind','dust','ash','smoke','insects')
            and payload['phenomenon'] not in p['permitted_weather'])
        family(a)['weather_result']={'record_id':payload['record_id'],'blocked':int(blocked),
                                     'source':PAVILION,'until':payload['expires_at'],'world_receipt_id':world_record['receipt_id']}
        # Wind/rain never douse the cultivated flame, even without a Pavilion.
        session.emit('WEATHERWARD_DELIVERY',aid,source=PAVILION,record_id=payload['record_id'],blocked=int(blocked),
                     extinguished=0,delivery=payload['delivery'],phenomenon=payload['phenomenon'])
    elif kind=='hearth_speak':
        require(set(payload) in ({'text','expires_at'},{'text','expires_at','delivery','recipients'}) and isinstance(payload['text'],str) and 0<len(payload['text'])<=1000
                and integer(payload['expires_at']) and payload['expires_at']>session.clock(),
                'Enter the words this creature actually speaks and their source expiry.')
        wards=[(o,c) for o,c in active_camps(session) if c.get('pavilion',{}).get('until',0)>session.clock()
               and contains(session,c,aid,20,pavilion_center(session,c),shape='cylinder',height=20)]
        require(wards,'The speaker must be inside an active Hearthward Pavilion.')
        owner,camp=wards[0]
        delivery=payload.get('delivery','speech');recipients=payload.get('recipients',[])
        require(delivery in ('speech','visible_gesture') and isinstance(recipients,list)
                and len(recipients)==len(set(recipients)) and set(recipients)<=set(actors),'Choose the actual delivery method and its recipients.')
        from ..fact_consent_admission import declare
        scope='speech:'+session.state['journey_id']+':'+str(session.state['revision']+1)
        record=declare(session,aid,{'source':PAVILION,'subject':aid,'kind':'spoken_words','scope':scope,
            'value':payload['text'],'expires_at':payload['expires_at'],'readers':list(dict.fromkeys([owner,*recipients]))})
        family(a).setdefault('speech_events',{})[record]={'speaker':aid,'authority_actor_id':aid,'owner':owner,
            'source':PAVILION,'journey_id':session.state['journey_id'],'seconds':int(session.clock()),'expires_at':payload['expires_at'],'text':payload['text'],'delivery':delivery,'recipients':recipients}
        session.emit('HEARTH_SPEECH',aid,source=PAVILION,record_id=record,authority_actor_id=aid,
                     expires_at=payload['expires_at'],text='Words spoken inside the Private Hearth; content is observer-scoped.')
    elif kind=='hearth_listen':
        required={'owner','speaker','method','effect_source_cl','speech_record_id'}
        require(set(payload) in (required,required|{'effect_source_id'}) and payload['owner'] in actors and payload['speaker'] in actors
                and payload['method'] in ('auditory','telepathy','nonauditory','cultivation_effect','check')
                and integer(payload['effect_source_cl']) and isinstance(payload['speech_record_id'],str)
                and payload['speech_record_id'].strip(), 'Choose a represented speaker and the native information method.')
        speech=family(actors[payload['speaker']]).get('speech_events',{}).get(payload['speech_record_id'])
        require(speech is not None and speech.get('journey_id')==session.state['journey_id'] and speech['owner']==payload['owner'] and speech['authority_actor_id']==payload['speaker']
                and speech['expires_at']>session.clock() and speech['seconds']==session.clock(),
                'Private Hearth requires this speaker’s actual unexpired native speech event at the current delivery time.')
        camps=active_camps(session,payload['owner'])
        require(camps,'Choose an active Pavilion.')
        c=camps[0][1];p=c.get('pavilion',{})
        require(p.get('until',0)>session.clock() and contains(session,c,payload['speaker'],20,pavilion_center(session,c),shape='cylinder',height=20),
                'The speaker must be inside the active Pavilion.')
        heard=contains(session,c,aid,20,pavilion_center(session,c),shape='cylinder',height=20)
        method=payload['method']
        # These methods require real native abilities; narration cannot grant them.
        if method=='nonauditory':
            require(speech.get('delivery')=='visible_gesture' and aid in speech.get('recipients',())
                    and session.grid.line_of_sight(Position.model_validate(a['position']),Position.model_validate(actors[payload['speaker']]['position'])),
                    'The speaker must actually convey these words to you by a visible nonauditory method.')
            heard=True
        if method in ('telepathy','cultivation_effect'):
            # The shared observer producer seals Source CL when the real
            # acquired effect is activated. Client numbers cannot create one.
            sources=communication_sources(session,aid,method)
            if payload.get('effect_source_id'):
                sources=[r for r in sources if r['instance_id']==payload['effect_source_id']]
            require(len(sources)==1,'Choose one actual active communication effect from your native sources.')
            native_cl=sources[0]['source_cl']
            require(payload['effect_source_cl'] in (0,native_cl),'The communication effect uses its committed Source CL.')
            heard=heard or method=='telepathy' or native_cl>c['source_cl']
        roll=None
        if not heard and method=='check':
            from ..gate2_rolls import DeterministicRollAuthority
            roller=DeterministicRollAuthority(session.state['journey_id']+':private-hearth:'+str(session.state['revision']))
            bonus=int(a['bundle'].get('hearthfire_checks',{}).get('perception',0))
            roll=roller.d20(modifier=bonus,actor_id=aid,reason='PRIVATE_HEARTH')
            dc=int(owned(session,payload['owner'],PAVILION)['numbers']['save_dc'])
            heard=roll.total>=dc
        family(a)['private_hearth_result']={'record_id':payload['speech_record_id'],'understood':int(heard),
            'owner_id':payload['owner'],'source':PAVILION,'expires_at':speech['expires_at'],'remaining':int(speech['expires_at']-session.clock()),
            **({'words':speech['text']} if heard else {})}
        # Store the information result, never expose the private speech content.
        session.emit('PRIVATE_HEARTH_INFORMATION',aid,source=PAVILION,record_id=payload['speech_record_id'],
                     understood=int(heard),method=method,**({'roll':roll.model_dump(mode='json')} if roll else {}))
    elif kind=='hearth_scene_end':
        raise ValueError('Use the native table-owner End Scene operation; a creature command cannot declare a new meaningful scene.')
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
    if f.get('welcome',{}).get('until',0)<=session.clock():f.pop('welcome',None)
    camp=f.get('camp',{})
    if camp.get('carry'):
        if camp['carry']['until']<=session.clock():camp.pop('carry')
        else:sync_camp_carrier(session,aid,camp)
    if camp.get('native_object') and camp.get('until',0)<=session.clock():
        from ..journey_assets import JourneyAssetContext
        from ..gate2_runtime_models import RuntimeObjectState
        from .qi_hearthfire import retire_hearth_object
        world=JourneyAssetContext(session)
        obj=world.state.objects.get(camp['native_object']['object_id']) or RuntimeObjectState.model_validate(camp['native_object'])
        if not obj.destroyed or (obj.component or {}).get('hearth_original'):
            retire_hearth_object(world,obj,HEARTH,aid)
            camp['native_object']=world.state.objects[obj.object_id].model_dump(mode='json')
        if camp.get('empowered_real'):
            from .qi_hearthfire import remember_hearth_item
            remember_hearth_item(f,camp['scene'],world.state.objects[obj.object_id])
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
    from .qi_hearthfire_persistence import family_state
    welcomes=welcome_fields(session,aid)
    if welcomes:
        return {'hearth_ac_bonus':1,'hearth_fire_resistance':1,'hearth_cold_resistance':1,
                'hearth_weather_discomfort_immune':1,'hearth_environmental_immune':1,
                'hearth_charmed_advantage':1,'hearth_frightened_advantage':1,'hearth_possession_advantage':1,
                'hearth_environmental_advantage':1}
    camps=[(o,c) for o,c in active_camps(session) if (aid in c['invited'] and contains(session,c,aid))
        or c.get('pavilion',{}).get('until',0)>session.clock() and contains(session,c,aid,20,pavilion_center(session,c),shape='cylinder',height=20)]
    if not camps:
        info=family_state(session,aid).get('private_hearth_result')
        return {'hearth_private_information':info} if info and info.get('expires_at',0)>session.clock() else None
    pavilion=any(c.get('pavilion',{}).get('until',0)>session.clock()
                 and contains(session,c,aid,20,pavilion_center(session,c),shape='cylinder',height=20) for _,c in camps)
    return {'hearth_weather_discomfort_immune':1,'hearth_ac_bonus':int(pavilion),
            'hearth_frightened_advantage':1,'hearth_environmental_cold_advantage':1,
            'hearth_exposure_exhaustion_advantage':1,
            'hearth_charmed_advantage':int(pavilion),'hearth_smoke_advantage':int(pavilion),
            **({'hearth_private_information':a_info} if (a_info:=family_state(session,aid).get('private_hearth_result')) else {})}


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
        for residue in f.get('objects',{}).values():
            if residue['scene']==(getattr(engine,'battlefield_document',{}) or {}).get('stable_id',''):
                restored=RuntimeObjectState.model_validate(residue['object'])
                if engine.state.objects.get(restored.object_id)!=restored:engine._update_object(restored,HEARTH,aid)
        if f.get('temporary_hp',0):
            actor.temporary_hp=max(actor.temporary_hp,f['temporary_hp'])
        if f.get('recovery_rest')==setup['long_rests']:
            engine._apply_condition(actor,RECOVERED,RECOVERY,aid,expires_on='UNTIL_REMOVED',data={'label':'Homefire Recovery received until a long rest'})
        if 'fear_scene' in f:
            engine._apply_condition(actor,FEAR,RECOVERY,aid,expires_on='UNTIL_REMOVED',data={'through_next_scene':1})
        welcome_state=f.get('welcome')
        if welcome_state and welcome_state.get('remaining',0)>0:
            rows_by_id={r.get('feature_id'):r for r in bundle.get('typed_passives',()) if r.get('block')==BLOCK}
            if WELCOME in rows_by_id:
                sub=context(engine,actor,WELCOME,rows_by_id[WELCOME]['numbers'],action=native_source_action(engine,actor,WELCOME))
                engine._start_concentration(actor,WELCOME)
                spec={'name':'Flame That Welcomes All','shape':'cylinder','size_ft':40,'height_ft':40,
                    'duration':{'kind':'rounds','amount':max(1,(welcome_state['remaining']+5)//6),'concentration':True},
                    'follows_owner':welcome_state['center']=='self',
                    'profile':{'welcome':1,'chosen_recipients':welcome_state['invited'],'center_actor':aid if welcome_state['center']=='self' else ''},
                    'inside':[],'triggers':[]}
                ward=zones.prospective_zone(sub,spec,actor.position if welcome_state['center']=='self' else Position.model_validate(welcome_state['position']),zone_id='zone:welcome.travel.'+aid)
                engine.state.zones[ward.zone_id]=ward;actor.concentration.zone_id=ward.zone_id
                engine._append_event('ZONE_CREATED',WELCOME,actor_id=aid,payload={'zone':ward.model_dump(mode='json')})
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
            if engine.state.objects.get(obj.object_id)!=obj:engine._update_object(obj,HEARTH,aid)
            ctx=context(engine,actor,HEARTH,rows[HEARTH]['numbers'],action=native_source_action(engine,actor,HEARTH))
            # Prospective construction avoids manufacturing an action or an
            # activation receipt. These are the existing journey's objects.
            spec={'name':'Kindled Hearth','shape':'sphere','size_ft':20 if camp.get('carry',{}).get('remaining',0)>0 else 15,'duration':{'kind':'rounds','amount':max(1,(camp['remaining']+5)//6)},
                'profile':{'hearth_object':oid,'chosen_recipients':camp['invited'],
                    **({'hearth_carrier':aid if camp['carry']['center']=='domain_armament' else camp['carry']['center'],
                        'carry_armament':int(camp['carry']['center']=='domain_armament'),'hearth_initial_damage':camp['carry'].get('damage_type'),
                        'carry_until':actor.turns_started+(camp['carry']['remaining']+5)//6}
                       if camp.get('carry',{}).get('remaining',0)>0 else {})},'inside':[],'triggers':[],
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
                ward=zones.prospective_zone(sub,spec,Position.model_validate(camp['position'] if camp.get('carry',{}).get('remaining',0)>0 else p['position']),zone_id='zone:pavilion.'+aid)
                engine.state.zones[ward.zone_id]=ward
                engine._append_event('ZONE_CREATED',PAVILION,actor_id=aid,payload={'zone':ward.model_dump(mode='json')})
    for bundle in engine.typed_bundle_documents:
        setup=bundle.get('hearthfire_setup')
        if not setup:continue
        result=setup['recipient'].get('private_hearth_result')
        viewer=engine.state.actors.get(bundle['actor_id'])
        owner=engine.state.actors.get((result or {}).get('owner_id',''))
        if result and result.get('remaining',0)>0 and viewer is not None and owner is not None:
            from ..observer_information import publish
            from .effect_durations import token
            publish(engine,viewer,PAVILION,owner,'declaration',
                {'summary':'Private Hearth: '+('you understand the spoken words.' if result['understood'] else 'the speech remains indistinct.'),
                 'record_id':result['record_id'],**({'words':result['words']} if result['understood'] else {})},token('start',viewer.entity_id,viewer.turns_started+(result['remaining']+5)//6))
    return True if initialized else None


@hook('journey_state_changed')
def camp_encounter_entry(session,aid):
    if session.state['phase']=='travel':
        from .qi_hearthfire_persistence import hydrate
        f=hydrate(session,aid)
        if not f:return
        camp=f.get('camp',{})
        if camp.get('carry',{}).get('until',0)>session.clock():sync_camp_carrier(session,aid,camp)
        if f.get('welcome'):
            if session.state['actors'][aid]['incapacitated']:f.pop('welcome',None)
            elif f['welcome']['center']=='self':f['welcome']['position']=dict(session.state['actors'][aid]['position'])
            elif active_camps(session,aid):f['welcome']['position']=dict(active_camps(session,aid)[0][1]['position'])
        export(session)
        return
    if session.state['phase']!='combat':return
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


@hook('fact_admission_schema')
def hearth_fact_schema(session,source,subject,kind):
    if subject in session.state['actors'] and (source,kind) in set(WORLD_COMMANDS.values()) and any(owned(session,o,HEARTH) for o in session.state['actors']):
        return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
            'description':'Native world-owner environmental delivery or physical shelter facts; never creature consent or acquisition.'}
    if source==CARRY and kind=='carry_hearth_consent' and any(subject in carry_centers(session,o,c) for o,c in active_camps(session)):
        return {'value_type':'flag','maximum_seconds':60,'description':'Personally agree to carry this real empowered item for one minute.'}
    if source==PAVILION and kind=='spoken_words' and any(c.get('pavilion',{}).get('until',0)>session.clock()
        and contains(session,c,subject,20,pavilion_center(session,c),shape='cylinder',height=20) for _,c in active_camps(session)):
        return {'value_type':'text','maximum_seconds':28800,
                'description':'Words this creature actually speaks inside a Private Hearth; never a mechanical source or ownership claim.'}
    if source==RECOVERY and kind=='environmental_history' and any(owned(session,owner,HEARTH) for owner in session.state['actors']):
        return {'value_type':'document','maximum_seconds':28800,
                'description':'This creature’s source-scoped account of an environmental hardship; mechanical levels and penalties are separately committed native state.'}



def journey_creature(session,aid):
    import json
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    actor=session.state['actors'][aid]
    conditions={k:ConditionInstance.model_validate(json.loads(v)) for k,v in
                (actor.get('encounter_snapshot') or {}).get('conditions',{}).items()}
    return SimpleNamespace(entity_id=aid,position=Position.model_validate(actor['position']),conditions=conditions)


def carry_centers(session,aid,camp):
    from .qi_path import armament_condition
    from .qi_hearthfire_items import held_item
    from ..gate2_runtime_models import RuntimeObjectState
    result=[aid]
    if armament_condition(journey_creature(session,aid)) is not None:result.append('domain_armament')
    obj=RuntimeObjectState.model_validate(camp['native_object'])
    result.extend(other for other in session.state['actors'] if other!=aid and held_item(None,obj,journey_creature(session,other)))
    return result


def sync_camp_carrier(session,aid,camp):
    from .qi_path import armament_condition,armament_point
    from ..journey_assets import JourneyAssetContext
    center=camp['carry']['center']
    if center=='domain_armament':
        actor=journey_creature(session,aid)
        if armament_condition(actor) is None:return
        point=armament_point(actor);position=Position(x=point[0],y=point[1])
    else:position=Position.model_validate(session.state['actors'][center]['position'])
    camp['position']=position.model_dump(mode='json')
    world=JourneyAssetContext(session)
    obj=world.state.objects.get(camp['native_object']['object_id'])
    if obj is not None and not obj.destroyed and obj.position!=position:
        obj=obj.model_copy(update={'position':position})
        world._update_object(obj,CARRY,aid)
        camp['native_object']=obj.model_dump(mode='json')



def communication_sources(session,aid,method):
    """Read only authenticated native observer profiles; never infer from names."""
    from ..observer_information import SOURCE
    rows=[]
    for c in journey_creature(session,aid).conditions.values():
        p=c.data.get('information_profile') or {}
        if c.condition_id==SOURCE and 'communication.'+method in p.get('tags',()):
            rows.append({'instance_id':c.instance_id,'source_id':c.source_definition_id,'source_cl':int(p['source_cl'])})
    return rows



def welcome_fields(session,aid):
    from .qi_hearthfire_persistence import family_state
    return [(owner,w) for owner in session.state['actors']
        if owned(session,owner,WELCOME) and not session.state['actors'][owner]['incapacitated']
        and (w:=family_state(session,owner).get('welcome')) and w.get('concentration')
        and w['until']>session.clock() and w['scene']==session.state['battlefield'].get('stable_id','')
        and aid in w['invited'] and contains(session,w,aid,40,shape='cylinder',height=40)]


WORLD_COMMANDS={'hearth_shelter':(PAVILION,'physical_space'),
    'hearth_weather':(HEARTH,'weather_delivery'),'hearth_hardship':(RECOVERY,'environmental_hardship')}


def world_payload(session,aid,kind,payload):
    from ..fact_consent_admission import read
    require(set(payload)=={'record_id'} and type(payload['record_id']) is str and bool(payload['record_id'].strip()),
            'Use a live source record from the separate native table-owner input path; an authority label is not permission.')
    source,fact_kind=WORLD_COMMANDS[kind]
    record=read(session,source,aid,fact_kind,payload['record_id'],aid)
    require(record and record['authority']=='table_owner','The represented world fact needs its actual native table-owner declaration.')
    value=deepcopy(record['value'])
    if 'ordinary' in value:
        require(type(value['ordinary']) is int and value['ordinary'] in (0,1),'Ordinary weather must be a typed zero/one world fact.')
        value['ordinary']=bool(value['ordinary'])
    return {**value,'record_id':payload['record_id'],'authority':'GM','expires_at':record['expires_at']},record


@hook('journey_scene_end')
def hearth_scene_end(session,previous,current):
    if not any(owned(session,owner,HEARTH) for owner in session.state['actors']):return
    session.state['hearth_scene']=session.state.get('hearth_scene',0)+1
    import json
    for aid,actor in session.state['actors'].items():
        from .qi_hearthfire_persistence import hydrate
        hydrate(session,aid)
        for action in actor['bundle'].get('action_catalog',()):
            if ((action.get('parameters') or {}).get('typed') or {}).get('source')==WELCOME:
                for pool,amount in action.get('costs',()):
                    if pool.startswith('resource:uses.'):actor['resources'][pool]=amount
        f=actor.get('hearthfire',{})
        snapshot=actor.get('encounter_snapshot')
        has_fear=snapshot and any(json.loads(v).get('condition_id')=='condition:typed.homefire_courage' for v in snapshot['conditions'].values())
        if 'fear_scene' in f or 'fear_boundaries' in f or has_fear:
            f=family(actor);f['fear_boundaries']=max(0,int(f.get('fear_boundaries',2))-1)
        if f.get('fear_boundaries',999)<=0:
            f.pop('fear_scene',None);f.pop('fear_boundaries',None)
            snapshot=actor.get('encounter_snapshot')
            if snapshot:snapshot['conditions']={k:v for k,v in snapshot['conditions'].items()
                if json.loads(v).get('condition_id')!='condition:typed.homefire_courage'}
    export(session)



@hook('journey_combat_bundle')
def camp_fresh_bundle(bundle,session,aid):
    """Pure source projection at the owner's real pre-genesis boundary."""
    from .qi_hearthfire_persistence import family_state
    f=deepcopy(family_state(session,aid))
    if not f and 'hearthfire_setup' not in bundle:return
    now=int(session.clock());camp=f.pop('camp',None);camps=[]
    if camp and not camp.get('destroyed') and camp.get('until',0)>now and camp.get('scene')==session.state['battlefield'].get('stable_id',''):
        row=deepcopy(camp);row['owner']=aid;row['remaining']=max(0,int(row['until']-now))
        live=session.state.get('runtime_objects',{}).get(row.get('native_object',{}).get('object_id'))
        if live is not None:row['native_object']=deepcopy(live);row['hp']=live['current_hp']
        if row.get('carry'):row['carry']['remaining']=max(0,int(row['carry']['until']-now))
        if row.get('pavilion'):row['pavilion']['remaining']=max(0,int(row['pavilion']['until']-now))
        camps=[row]
    if f.get('welcome'):f['welcome']['remaining']=max(0,int(f['welcome']['until']-now))
    if f.get('private_hearth_result'):
        f['private_hearth_result']['remaining']=max(0,int(f['private_hearth_result']['expires_at']-now))
        if not f['private_hearth_result']['remaining']:f.pop('private_hearth_result')
    return {**bundle,'hearthfire_setup':{'camps':camps,'recipient':f,'long_rests':session.state['actors'][aid]['long_rests']}}
