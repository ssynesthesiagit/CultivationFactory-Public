"""Living Quicksilver source procedures and five-feature consumers.

Uses the source-owner journey_acquisition/fact_consent_admission contracts,
Asset/Anchor runtime, ordinary object events, scoped effect_origins, Needle and
native effect resolution. No ownership means no registration of actions/pools,
no state and no choice. Body objects have no initiative or independent actions.
All durable state is primitive source-scoped data, carried by ordinary conditions
and the journey source_states boundary. No trigger can be supplied by a caller.
"""
from copy import deepcopy
from dataclasses import replace
import json
from . import hook, effect, note, ai_controlled
from ..gate2_runtime_models import ActionDefinition, ResourceDefinition, Position, DiceSpec
from ..journey import require, integer
from ..fact_consent_admission import read, canonical

FAMILY='tianxia.subpath.qi.living_quicksilver_immortal_embryo'
PREFIX=FAMILY+'.feature.'
NAMES=('living_mercury_body','divide_the_immortal_embryo','assimilate_the_pattern','thousandfold_quicksilver_court','undying_prima_materia')
FEATURES=tuple(PREFIX+n for n in NAMES)
LIVING,DIVIDE,ASSIMILATE,COURT,UNDYING=FEATURES
LEVELS=(3,6,10,14,18)
PARENT='tianxia.subpath.qi.mercurial_cultivator'
OLD=tuple(PARENT+'.feature.'+s for s in ('mercurial_qi','liquid_form','mercurial_adaptation','quicksilver_step','prima_materia'))
QI='resource:core.qi'; MASS='resource:named.quicksilver_mass'; BLOCK='living_quicksilver'
LEDGER='condition:typed.living_quicksilver_ledger'; FORM='condition:typed.undying_prima_materia'
MERCURIAL=('ACID','COLD','FIRE','LIGHTNING','POISON','THUNDER','BLUDGEONING','PIERCING','SLASHING')


def rows(engine,actor):
    return [r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,()) if r.get('block')==BLOCK]


def owns(engine,actor,feature=LIVING):
    return any(r.get('feature_id')==feature for r in rows(engine,actor))


def numbers(engine,actor):
    return next((r['numbers'] for r in rows(engine,actor)),{})


def level(engine,actor):
    return int(numbers(engine,actor).get('cl',0))


def ledger(actor):
    return next((c for c in actor.conditions.values() if c.condition_id==LEDGER),None)


def data(actor):
    held=ledger(actor)
    return deepcopy(held.data) if held else {}


def store(engine,actor,**changes):
    held=ledger(actor);value={'label':'Living Quicksilver Immortal Embryo',**data(actor),**changes}
    if held:engine._update_condition_data(actor,held,value,LIVING)
    else:engine._apply_condition(actor,LEDGER,LIVING,actor.entity_id,expires_on='UNTIL_REMOVED',data=value)


def transformed(actor):
    return next((c for c in actor.conditions.values() if c.condition_id==FORM),None)


def stamp(engine):
    return str(engine.state.round_number)+':'+str(engine.state.current_actor_id)+':'+str(engine.state.actors[engine.state.current_actor_id].turns_started)


def available(engine,actor,key,roundly=False):
    return data(actor).get(key)!= (int(engine.state.round_number) if roundly else stamp(engine))


def mark(engine,actor,key,roundly=False):
    store(engine,actor,**{key:int(engine.state.round_number) if roundly else stamp(engine)})


def choose(engine,actor,key,options,labels=None,*,prompt,optional=False,intent=None,known=None):
    from .needle import ask,checkpoint_id
    result=ask(engine,intent or getattr(engine,'_active_intent',None),checkpoint_id(engine,'QUICKSILVER',key,actor.entity_id),actor,
        'choice:needle.quicksilver.'+key,list(options),labels=labels or {o:o.replace('_',' ').title() for o in options},
        prompt=prompt,name='Living Quicksilver Immortal Embryo',feature_id=LIVING,allow_decline=optional,
        automatic=ai_controlled(engine,actor),automatic_options=known,default='decline' if optional else 'first')
    return result[0] if result else None


def gain(engine,actor,*,normal=True,count=1):
    if not owns(engine,actor) or MASS not in actor.resources:return 0
    if normal and not available(engine,actor,'mass_round',True):return 0
    n=min(count,max(0,int(actor.proficiency_bonus)-actor.resources[MASS]))
    if n:
        engine._gain_resource(actor,MASS,n,LIVING)
        if normal:mark(engine,actor,'mass_round',True)
    return n


def bodies(engine,actor,live=True):
    from ..asset_anchor_runtime import members
    return members(engine,actor.entity_id,BLOCK,live=live)


def cap(engine,actor):
    cl=level(engine,actor)
    return 3 if cl>=18 or transformed(actor) else 2 if cl>=10 else 1


def qi_action(action):
    typed=action.parameters.get('typed') or {}
    if type(typed.get('qi_powered')) is bool:return typed['qi_powered']
    source=str(typed.get('option_of') or typed.get('source') or '')
    from .insights7 import qi_powered
    return qi_powered(typed.get('sphere'),tuple(r for r,n in action.costs)) or source.startswith(('tianxia.subpath.qi.','tianxia.path.qi_cultivation.'))


def owning_qi_cl(sheet,fallback):
    from ..path_levels import path_row,effective_cl
    path='tianxia.path.qi_cultivation'
    row=path_row(sheet,path)
    if row is not None:
        # The public portable multi-Path contract uses effective_cl. Preserve
        # the earlier installed attainment field without inventing total CL.
        return effective_cl(sheet,path,fallback) if 'effective_cl' in row else row.get('attainment',0)
    paths=sheet.get('path_and_subpath') or {}
    selected=set(paths.get('path_record_ids') or ())|({paths['path_record_id']} if paths.get('path_record_id') else set())
    return int(sheet.get('identity',{}).get('cultivation_level',fallback)) if selected=={path} else fallback


@hook('compile_passives')
def compile_owned(passives,info):
    ids=set(info['owned_ids']);own=ids.intersection(FEATURES)
    if not own:return None
    require(not ids.intersection(OLD),'A Living Quicksilver Variant cannot retain its replaced Mercurial progression.')
    kept=[r for r in passives if r.get('feature_id') not in FEATURES]
    sealed=dict(info['numbers'])
    path_level=owning_qi_cl(info.get('owner_sheet') or {},sealed.get('cl',0))
    if integer(path_level,1):sealed['cl']=path_level
    return [*kept,*({'block':BLOCK,'feature_id':f,'numbers':dict(sealed)} for f in FEATURES if f in own)]


@hook('compile_resource_definitions')
def resources(resources,info):
    if LIVING not in info['owned_ids']:return None
    pb=int(info['pb'])
    return [*[r for r in resources if r.resource_id!=MASS],ResourceDefinition(resource_id=MASS,initial=(pb+1)//2,maximum=pb)]


@hook('compile_actions')
def commands(info):
    owned=set(info['owned_ids']);out=[]
    if LIVING not in owned:return None
    def add(key,name,source,economy='NONE',cost=(),target='SELF',reach=None,**params):
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.quicksilver.{key}",display_name=name,
            owner_id=info['actor_id'],economy=economy,resolution_kind='TYPED',target_kind=target,range_ft=reach,costs=cost,
            parameters={'typed':{'source':source,'numbers':dict(info['numbers']),'effects':[{'type':'quicksilver_command','command':key}],
                'duration':{'kind':'instant'},'qi_powered':True},'quicksilver_command':key,'expected_damage':0,**params}))
    add('armament','Mutable Armament: manifest or merge',LIVING,description='Once during your turn, manifest or merge the actual item selected after a Full Cultivation Session. No action or resource cost.')
    if DIVIDE in owned:
        for resource,n,label in ((QI,2,'2 Qi'),(MASS,1,'1 Quicksilver Mass')):
            add('create_'+('qi' if resource==QI else 'mass'),'Create Quicksilver Body: '+label,DIVIDE,'BONUS_ACTION',((resource,n),),'CELL',15,cell_placement={},description='Bonus Action: create one targetable Quicksilver Body in an unoccupied space within 15 feet. Costs '+label+'.')
        add('move','Move Quicksilver Bodies',DIVIDE,description='Once during your turn, move each Body up to its walking Speed. No action or resource cost.')
        for mode,label in (('hp','regain Hit Points'),('mass','regain Quicksilver Mass'),('condition','end Grappled or Restrained')):
            add('rejoin_'+mode,'Rejoin: '+label,DIVIDE,description='Once during your turn, destroy one adjacent Body and '+label+'. No action or resource cost; condition Source CL cannot exceed yours.')
    if UNDYING in owned:
        add('transform','Undying Prima Materia',UNDYING,'BONUS_ACTION',((QI,8),),description='Bonus Action, 8 Qi, once per scene: transform for 1 minute. Gain perfected Bodies, flight, defenses, configurations and Immortal Reconstitution.')
        for mode,label in (('attacks','two Domain Armament Attacks'),('guard','Guard Mode from two origins'),('technique','weapon-delivered technique and one attack')):
            add('sea_'+mode,'Weapon-Sea: '+label,UNDYING,'BONUS_ACTION',description='Weapon-Sea Configuration: '+label+'. Once-per-turn riders and the technique apply once; pay normal technique resources.')
    return out


@hook('compile_action')
def remove_partial_actions(action,info):
    typed=action.parameters.get('typed') or {}
    if LIVING not in info['owned_ids']:return None
    if typed.get('source') in FEATURES and 'quicksilver_command' not in action.parameters:
        return action.model_copy(update={'parameters':{**action.parameters,'setting_only':True,'player_only':True,'quicksilver_legacy':True},'economy':'NONE'})
    if typed.get('sphere') and not typed.get('attack_action'):
        params=deepcopy(action.parameters);params['typed']['qi_powered']=True
        return action.model_copy(update={'parameters':params})
    return None


@hook('candidate_allowed')
def command_allowed(engine,actor,candidate,action):
    if action is None:return None
    if action.parameters.get('quicksilver_legacy'):return False
    key=action.parameters.get('quicksilver_command')
    if not key:return None
    if not owns(engine,actor):return False
    if key.startswith('create_'):
        from ..asset_anchor_runtime import legal_placement
        return len(bodies(engine,actor))<cap(engine,actor) and candidate.destination is not None and legal_placement(engine,[candidate.destination],5)
    if key.startswith('rejoin_'):
        return available(engine,actor,'rejoin') and any(engine.grid.distance_ft(actor.position,o.position)<=5 for o in bodies(engine,actor))
    if key=='move':return available(engine,actor,'move') and bool(bodies(engine,actor))
    if key=='armament':return armament_available(engine,actor) and available(engine,actor,'armament_turn')
    if key=='transform':return not data(actor).get('transformation_used') and not transformed(actor)
    if key=='court_delivery':return bool(transformed(actor)) and data(actor).get('configuration')=='distributed' and available(engine,actor,'court_delivery') and bool(bodies(engine,actor))
    if key.startswith('sea_'):return bool(transformed(actor)) and data(actor).get('configuration')=='sea' and len(sea_origins(engine,actor))>=2
    return None


def create_body(engine,actor,position):
    from ..asset_anchor_runtime import create
    cl=level(engine,actor);perfect=bool(transformed(actor))
    return create(engine,actor,DIVIDE,{'name':actor.display_name+"'s Quicksilver Body",'kind':'CULTIVATION_ASSET','group':BLOCK,
        'ac':actor.armor_class+engine._ac_modifier(actor),'hp':(4 if perfect else 2)*cl,'source_cl':cl,'height_ft':5*engine._footprint(actor).width_cells,
        'resist':['POISON'],'immune':['PSYCHIC'],'requires_support':not perfect},position,component={'quicksilver_body':1,'size':actor.size_category,
            'width_cells':engine._footprint(actor).width_cells,'length_cells':engine._footprint(actor).height_cells,
            'speed_ft':engine._effective_speed(actor),'fly_speed_ft':50 if perfect else 0,'hover':int(perfect),
            'condition_immunities':['charmed','frightened','poisoned'],'save_bonus':int(actor.proficiency_bonus)+int(numbers(engine,actor).get('key_mod',0)),
            'tether_ft':60,'default_action':'Dodge','initiative':'creator_turn','commands':'creator_free_movement','allowed_actions':[],'allowed_reactions':['Exchange Substance'] if perfect else [],'duration':'until_destroyed_or_rejoined','at_zero':'destroyed','information_profile':{'tags':['cultivation_asset'],'source_cl':cl},'record_damage_components':1,'repair_allowed':False,'occupies_space':1,'perfected':int(perfect),'source_cl':cl})


def retire_body(engine,actor,obj,source=DIVIDE,*,destroyed=True):
    from ..asset_anchor_runtime import retire
    was_live=not obj.destroyed
    retire(engine,obj,source)
    if was_live and destroyed:gain(engine,actor)


def select_body(engine,actor,key,within,*,optional=False,intent=None):
    options={o.object_id:o for o in bodies(engine,actor) if engine.grid.distance_ft(actor.position,o.position)<=within}
    picked=choose(engine,actor,key,list(options),{k:v.component['name']+f' at ({v.position.x}, {v.position.y}), {v.current_hp} HP' for k,v in options.items()},prompt=f'{actor.display_name}: choose one Quicksilver Body within {within} feet.',optional=optional,intent=intent)
    return options.get(picked)


@effect('quicksilver_command')
def execute_command(ctx,row):
    engine,actor=ctx.engine,ctx.actor;key=row['command']
    require(owns(engine,actor),'Only the actual Living Quicksilver owner can use this command.')
    if key.startswith('create_'):
        require(len(bodies(engine,actor))<cap(engine,actor),'You already maintain your maximum Quicksilver Bodies.')
        create_body(engine,actor,ctx.destination)
    elif key.startswith('rejoin_'):
        require(available(engine,actor,'rejoin'),'Rejoin is once during each of your turns.')
        obj=select_body(engine,actor,'rejoin_body',5,intent=ctx.intent)
        require(obj is not None,'Rejoin requires an adjacent Body.')
        mode=key.removeprefix('rejoin_')
        if mode=='hp':engine._heal(actor,int(obj.current_hp),DIVIDE,actor.entity_id)
        elif mode=='mass':gain(engine,actor,normal=False)
        else:
            from ..observer_information import source_numbers
            def known_level(c):
                n=c.data.get('source_cl') or source_numbers(engine,c.source_definition_id,c.source_actor_id).get('cl')
                return n if type(n) is int else None
            options={c.instance_id:c for c in actor.conditions.values() if c.condition_id.removeprefix('condition:typed.').lower() in ('grappled','restrained') and known_level(c) is not None and known_level(c)<=level(engine,actor)}
            selected=choose(engine,actor,'rejoin_condition',list(options),prompt='Rejoin: choose one Grappled or Restrained condition whose Source CL is no higher than yours.')
            require(selected in options,'Choose a legal condition before absorbing the Body.')
            engine._remove_condition_instance(actor,selected,DIVIDE)
        retire_body(engine,actor,obj);mark(engine,actor,'rejoin')
    elif key=='move':
        move_bodies(engine,actor,ctx.intent);mark(engine,actor,'move')
    elif key=='armament':
        require(armament_available(engine,actor),'Mutable Armament needs the actual item and a legal physical hand when manifesting.')
        info=data(actor)['armament'];info['manifested']=1-int(info.get('manifested',0))
        if info['manifested']:
            from .hand_occupancy import free_hands
            parts=free_hands(engine,actor)
            picked=choose(engine,actor,'armament_hand',list(parts),{p:p.replace(':',' ').title() for p in parts},prompt=actor.display_name+': choose a free hand for '+info['name']+'. Manifesting costs no action or Qi and uses this turn’s Mutable Armament change.',intent=ctx.intent)
            require(picked in parts,'Choose a real free hand for the actual item.');info['hand']=picked
        else:info.pop('hand',None)
        store(engine,actor,armament=info);settle_armament(engine,actor,info);mark(engine,actor,'armament_turn')
        note(engine,LIVING,actor,actor.display_name+(' manifests ' if info['manifested'] else ' merges ')+info['name']+'. The actual item is retained.')
    elif key=='transform':
        require(not data(actor).get('transformation_used'),'Undying Prima Materia is once per scene.')
        store(engine,actor,transformation_used=1)
        from .effect_durations import round_token
        engine._apply_condition(actor,FORM,UNDYING,actor.entity_id,expires_on=round_token(engine,10),data={'label':'Undying Prima Materia: 1 minute','source_cl':level(engine,actor),'information_profile':{'tags':['transformation'],'source_cl':level(engine,actor)}})
        for obj in bodies(engine,actor):
            component={**obj.component,'perfected':1,'fly_speed_ft':50,'hover':1}
            engine._update_object(obj.model_copy(update={'maximum_hp':4*level(engine,actor),'current_hp':obj.current_hp,'component':component}),UNDYING,actor.entity_id)
    elif key=='court_delivery':deliver_bonus(ctx)
    elif key.startswith('sea_'):weapon_sea(ctx,key.removeprefix('sea_'))


def move_bodies(engine,actor,intent):
    """Source-specific commands follow each native grid step and terrain cost."""
    from collections import deque
    from ..asset_anchor_runtime import legal_placement,placement_view
    from ..senses import perceives_cell
    for obj in list(bodies(engine,actor)):
        view=placement_view(engine,ignore=(obj.object_id,))
        feet=50 if transformed(actor) else int(obj.component['speed_ft'])
        routes={obj.position:(0,[obj.position])};queue=deque([obj.position])
        while queue:
            old=queue.popleft();cost,path=routes[old]
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    for dz in ((-1,0,1) if transformed(actor) else (0,)):
                        if not(dx or dy or dz) or old.x+dx<0 or old.y+dy<0 or old.z+dz<0:continue
                        p=Position(x=old.x+dx,y=old.y+dy,z=old.z+dz)
                        extra=5 if transformed(actor) else 5*engine.grid.movement_step_multiplier(old,p,footprint=engine._footprint(actor))
                        cells=[Position(x=p.x+ox,y=p.y+oy,z=p.z) for ox in range(int(obj.component.get('width_cells',1))) for oy in range(int(obj.component.get('length_cells',1)))]
                        if cost+extra>feet or engine.grid.distance_ft(actor.position,p)>60 or not engine.grid.volume_step_legal(old,p,footprint=engine._footprint(actor)) or not legal_placement(view,cells,int(obj.height_ft or 5),require_support=not bool(transformed(actor))):continue
                        if p not in routes or routes[p][0]>cost+extra:routes[p]=(cost+extra,path+[p]);queue.append(p)
        opts={f'{p.x},{p.y},{p.z}':p for p in routes}
        picked=choose(engine,actor,'move_'+obj.object_id,list(opts),prompt=f'{obj.component["name"]}: choose a legal route up to {feet} feet, including staying put. No action cost.',intent=intent,
            known=[k for k,p in opts.items() if perceives_cell(engine,actor,p)])
        if picked:
            p=opts[picked];engine._update_object(obj.model_copy(update={'position':p}),DIVIDE,actor.entity_id)
            note(engine,DIVIDE,actor,'Quicksilver Body moves '+str(routes[p][0])+' feet.',path=[q.model_dump(mode='json') for q in routes[p][1]])


@hook('damage_defenses')
def defenses(engine,actor,kind,typed,source_actor_id):
    if not owns(engine,actor):return None
    kind=str(kind).upper();form=transformed(actor)
    result=[]
    if kind=='POISON':result.append({'kind':'immunity' if form else 'resistance','damage_types':['POISON']})
    if form and kind not in ('FORCE','PSYCHIC','RADIANT','VOID','POISON'):result.append({'kind':'resistance','damage_types':[kind]})
    origin=(typed or {}).get('damage_origin') or {}
    if kind=='POISON' and origin.get('ordinary')==1 and (origin.get('delivery')=='ingested' or origin.get('toxin_kind')=='metallic'):
        result.append({'kind':'immunity','damage_types':['POISON']})
    return result or None


@hook('save')
def grapple_save(ctx,subject,ability,named):
    if owns(ctx.engine,subject) and set(named or ())&{'grappled','restrained'}:return {'modes':['ADVANTAGE'],'bonus':0}
    return None


@hook('ability_check_hazards')
def grapple_check(engine,actor,ability,skill,hazards):
    if owns(engine,actor) and set(hazards)&{'grappled','restrained'}:return 'ADVANTAGE'
    return None


@hook('condition_attempt')
def physical_restraint(ctx,subject,row):
    name=str(row.get('condition') or '').lower()
    if owns(ctx.engine,subject) and transformed(subject):
        if name=='poisoned':return False
        if name in ('grappled','restrained'):
            from .physical_holds import ordinary
            if (ordinary(ctx.typed,row) or row.get('hold_kind')=='cultivated_physical' or row.get('physical') is True) and type(ctx.numbers.get('cl')) is int and ctx.numbers['cl']<level(ctx.engine,subject):return False
    return None


@hook('flight')
def flight(engine,actor):
    if owns(engine,actor) and transformed(actor):return {'fly_speed_ft':50,'flight_hover':1}
    return None


@hook('object_damage_defenses')
def body_defenses(engine,attacker,obj,packets,source):
    if not obj.component.get('quicksilver_body'):return None
    from ..weapon_delivery import delivery_kind
    from ..typed_reactions import ordinary_attack
    action=engine.action_catalog.get(source)
    typed=action.parameters.get('typed',{}) if action else {}
    ordinary=bool(action and (delivery_kind(typed,{},action.parameters)=='weapon' or (action.parameters.get('object_attack') and typed.get('object_weapon_group') not in (None,'','unarmed'))) and ordinary_attack(engine,typed,attacker.entity_id))
    kinds=['POISON',*(['BLUDGEONING','PIERCING','SLASHING'] if ordinary else [])]
    return [{'kind':'resistance','damage_types':kinds,'source':DIVIDE,'owner_id':obj.owner_id}]


@hook('event',nested=True)
def mass_events(engine,event_type,kwargs):
    if event_type=='DAMAGE_COMMITTED':
        p=kwargs.get('payload') or {}
        if str(p.get('damage_type','')).upper() not in MERCURIAL:return
        for aid in kwargs.get('target_ids') or ():
            actor=engine.state.actors.get(aid)
            if actor and owns(engine,actor) and int(p.get('rolled_or_pending_damage',0))>int(p.get('reduced_to',0)):
                # Own defenses, not another creature's reduction or a narrated type.
                if (str(p['damage_type']).upper()=='POISON' or transformed(actor)):gain(engine,actor)
    elif event_type=='OBJECT_UPDATED' and (kwargs.get('payload') or {}).get('damage'):
        doc=kwargs['payload']['object'];owner=engine.state.actors.get(doc.get('owner_id'))
        if doc.get('component',{}).get('quicksilver_body') and owner:
            damage=kwargs['payload']['damage']
            if any(part['damage_type'] in MERCURIAL and part['rolled_or_pending_damage']>part['reduced_to'] and any(r.get('source')==DIVIDE and r.get('owner_id')==owner.entity_id and part['damage_type'] in r.get('damage_types',[]) for r in damage.get('source_defenses',[])) for part in damage.get('components',[])):gain(engine,owner)
            if doc.get('destroyed'):gain(engine,owner)


@hook('action_completed')
def paid_mass(engine,actor,economy,source_definition_id):
    if not owns(engine,actor):return
    total=0
    for event in reversed(engine.events):
        if event.event_type=='INTENT_ACCEPTED' and event.actor_id==actor.entity_id:break
        if event.event_type=='RESOURCE_SPENT' and event.actor_id==actor.entity_id and event.payload.get('resource_id')==QI:
            action=engine.action_catalog.get(event.source_definition_id)
            typed=action.parameters.get('typed',{}) if action else {}
            source=typed.get('source','')
            if source.startswith(PREFIX) or typed.get('sphere')=='tianxia.sphere.transformation' or source.startswith(PARENT+'.feature.'):
                total+=int(event.payload.get('amount',0))
    if total>=3:gain(engine,actor)


def origin_records(engine,actor):
    from .qi_path import armament_condition,armament_point
    out=[{'id':'quicksilver:self','label':actor.display_name,'position':actor.position.model_dump(mode='json')}]
    out.extend({'id':o.object_id,'label':o.component['name'],'position':o.position.model_dump(mode='json')} for o in bodies(engine,actor))
    if armament_condition(actor):
        x,y=armament_point(actor);out.append({'id':'quicksilver:armament','label':'Mercurial Domain Armament','position':{'x':x,'y':y}})
    return out


@hook('effect_origins')
def body_origins(engine,actor,action):
    if not owns(engine,actor,DIVIDE) or not qi_action(action) or action.parameters.get('quicksilver_command'):return None
    return [r for r in origin_records(engine,actor) if r['id']!='quicksilver:self']


@hook('observer_information_rows')
def body_information(engine,viewer):
    if not owns(engine,viewer,COURT):return None
    result=[{'kind':'quicksilver_body','viewer_id':viewer.entity_id,'source_id':COURT,'authority_actor_id':viewer.entity_id,
             'details':{'name':o.component['name'],'position':o.position.model_dump(mode='json'),'hp':o.current_hp,'maximum_hp':o.maximum_hp,'source_cl':o.component['source_cl']}}
            for o in bodies(engine,viewer)]
    from ..observer_information import sources,direction
    from ..senses import of,reach
    from types import SimpleNamespace
    if 'qi_sensing' not in of(engine,viewer,unrestricted_only=True):return result
    seen=set()
    for origin in origin_records(engine,viewer):
        position=Position(**origin['position']);eye=viewer.model_copy(update={'position':position})
        for source in sources(engine):
            # Conventional conditions are not promoted to supernatural energy.
            # Only an explicit native energy/manifestation source qualifies.
            tags=set(source['tags'])
            if not tags&{'cultivation_asset','transformation','active_qi','cultivation_energy'} or source['profile'].get('concealment_success'):continue
            point=SimpleNamespace(position=source['position'],conditions={},perception_cell=True)
            distance=engine.grid.distance_ft(position,source['position'])
            if distance>reach(engine,eye,'qi_sensing',point,unrestricted_only=True):continue
            if not engine.grid.line_of_physical_transmission(position,source['position']):continue
            heading=direction(position,source['position']);key=(origin['id'],heading)
            if key in seen:continue
            seen.add(key)
            # Presence and direction only: never the source's identity, exact
            # occupied space, secret property, statistics or technique name.
            result.append({'kind':'qi_presence','viewer_id':viewer.entity_id,'source_id':COURT,'authority_actor_id':viewer.entity_id,
                'details':{'origin_id':origin['id'],'direction':heading,'presence':1}})
    return result


@hook('turn_start_choice')
def turn_choices(engine,actor):
    if not owns(engine,actor):return
    saved=data(actor).get('preserved',[])
    if saved and owns(engine,actor,ASSIMILATE):
        options={str(i):p for i,p in enumerate(saved)}
        selected=choose(engine,actor,'active_pattern',list(options),{i:p['label'] for i,p in options.items()},prompt=actor.display_name+': select one preserved pattern as your active pattern. No action or resource cost.',optional=True)
        if selected is not None:store(engine,actor,pattern=options[selected])
    if not transformed(actor):return
    gain(engine,actor,normal=False)
    if len(bodies(engine,actor))<cap(engine,actor):
        from .spirit_assets import legal_spaces
        options={f'{p.x},{p.y},{p.z}':p for p in legal_spaces(engine,actor.position,15)}
        selected=choose(engine,actor,'free_body',list(options),prompt=actor.display_name+': create one Quicksilver Body within 15 feet for no action or resource cost.')
        if selected:create_body(engine,actor,options[selected])
    mode=choose(engine,actor,'configuration',['converged','distributed','mirror','sea'],{
        'converged':'Converged Sovereign: absorb all Bodies; choose healing, Mass, AC or the next Qi roll for each',
        'distributed':'Distributed Court: move every Body and deliver one Bonus Action feature from one Body without your Bonus Action',
        'mirror':'Mirror-Metal Legion: hostile attacks have Disadvantage unless the attacker simultaneously perceives all Bodies with a sufficient sense',
        'sea':'Weapon-Sea Configuration: manifest equipment forms; use the Weapon-Sea Bonus Action options'},prompt=actor.display_name+': choose one configuration until the start of your next turn.')
    store(engine,actor,configuration=mode or 'mirror',configuration_turn=stamp(engine))
    if mode=='converged':
        for obj in list(bodies(engine,actor)):
            reward=choose(engine,actor,'absorb_'+obj.object_id,['hp','mass','ac','roll'],prompt='Absorb '+obj.component['name']+': choose 3d8 HP, 1 Mass, +1 AC until your next turn, or +2d8 to the next Qi damage or healing roll.')
            if reward=='hp':
                rolled=engine.roller.roll(DiceSpec(count=3,sides=8),actor_id=actor.entity_id,reason='QUICKSILVER_CONVERGED_HEALING');engine._record_roll(rolled);engine._heal(actor,rolled.total,UNDYING,actor.entity_id)
            elif reward=='mass':gain(engine,actor,normal=False)
            elif reward=='ac':engine._add_modifier(actor,UNDYING,'armor_class','ADD',1,'SELF',expires_on='START_OF_SOURCE_NEXT_TURN')
            else:store(engine,actor,roll_dice=int(data(actor).get('roll_dice',0))+2)
            retire_body(engine,actor,obj,UNDYING,destroyed=False)
    elif mode=='distributed':move_bodies(engine,actor,getattr(engine,'_active_intent',None))


def mirror_mode(ctx,owner):
    from ..relations import relation,ENEMY
    if relation(ctx.engine,ctx.actor,owner)!=ENEMY:return None
    if not owns(ctx.engine,owner,UNDYING) or not transformed(owner) or data(owner).get('configuration')!='mirror':return None
    from ..senses import reach,perceives_cell
    from types import SimpleNamespace
    # Evaluate the explicitly sufficient sense at every surviving Body, including
    # its effective range through darkness. General sight or an ally's eyes do
    # not establish the attacker's simultaneous Truesight exception.
    for obj in bodies(ctx.engine,owner):
        point=SimpleNamespace(position=obj.position,conditions={},perception_cell=True)
        if max(reach(ctx.engine,ctx.actor,sense,point,unrestricted_only=True) for sense in ('truesight','quicksilver_complete_perception'))<ctx.engine.grid.distance_ft(ctx.actor.position,obj.position):return 'DISADVANTAGE'
        if not perceives_cell(ctx.engine,ctx.actor,obj.position):return 'DISADVANTAGE'
    from ..senses import of
    if not any(sense in of(ctx.engine,ctx.actor,unrestricted_only=True) for sense in ('truesight','quicksilver_complete_perception')):return 'DISADVANTAGE'
    return None


@hook('attack_mode')
def mirror_defense(ctx,target):
    return mirror_mode(ctx,target)


@hook('object_attack_mode')
def mirror_body_defense(ctx,obj):
    if not obj.component.get('quicksilver_body'):return None
    owner=ctx.engine.state.actors.get(obj.owner_id)
    return mirror_mode(ctx,owner) if owner else None

# Native source access, persistent profile, cultivation and scene procedures.
@hook('fact_admission_schema')
def declarations(session,source,subject,kind):
    if source!=FAMILY or subject not in session.state['actors']:return None
    if kind in ('source_access','item_authority','sentient_item_consent','body_effect','barrier_authority','pattern_authority','cultivation_substitute'):
        return {'authority':'table_owner','value_type':'document','maximum_seconds':2592000,
            'description':'Record actual source access, item constraints, anatomy consequence or sealed barrier authority. This does not fabricate a mechanical trigger.'}
    if kind=='cultivation_environment':
        return {'value_type':'document','maximum_seconds':2592000,
            'description':'The actual controller records their own cultivation environment or sentient item consent; ownership, time and effects are validated separately.'}
    return None


def source_state(actor):
    return actor.setdefault('source_states',{}).setdefault(FAMILY,{})


def journey_owned(actor,feature=LIVING):
    return any(r.get('block')==BLOCK and r.get('feature_id')==feature for r in actor['bundle'].get('typed_passives',[]))


def overlay(sheet,state,session=None,actor_id=None):
    result=deepcopy(sheet)
    saved=state.get('acquired_paths')
    if not saved:return result
    if isinstance(saved,str):saved=json.loads(saved)
    attained=owning_qi_cl(result,0)
    acquisition=saved.get('subpath_acquisition') or {}
    previous=int(acquisition.get('path_level',0))
    if type(attained) is int and attained>previous:
        newly=[feature for feature,minimum in zip(FEATURES,LEVELS) if previous<minimum<=attained]
        saved['path_feature_record_ids']=list(dict.fromkeys([*saved.get('path_feature_record_ids',[]),*newly]))
        saved['subpath_acquisition']={**acquisition,'path_level':attained,'earned_features':list(dict.fromkeys([*acquisition.get('earned_features',[]),*newly]))}
        state['acquired_paths']=canonical(saved)
        if newly and session is not None:session.emit('QUICKSILVER_PROGRESSION_EARNED',actor_id,previous_qi_cl=previous,qi_cl=attained,earned_features=newly)
    paths=deepcopy(result.get('path_and_subpath') or {})
    for field in ('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids'):
        paths[field]=[s for s in paths.get(field,[]) if s not in OLD and not s.startswith(PREFIX)]
        paths[field]+=saved.get(field,[])
    for field in ('subpath_record_id','subpath_record_ids','subpath','subpaths','bindings','subpath_acquisition'):
        if field in saved:paths[field]=deepcopy(saved[field])
    paths['earned_feature_occurrences']=[r for r in paths.get('earned_feature_occurrences',[]) if r.get('feature_id') not in OLD]
    result['path_and_subpath']=paths
    return result


@hook('journey_source_sheet')
def acquired_overlay(sheet,session,actor_id):
    state=session.state['actors'][actor_id].get('source_states',{}).get(FAMILY,{})
    return overlay(sheet,state,session,actor_id) if state.get('acquired_paths') else None


def session_environment(session,actor_id,scope):
    fact=read(session,FAMILY,actor_id,'cultivation_environment',scope,actor_id)
    require(fact is not None and fact['value'].get('calm')==1,
        'A Full Cultivation Session needs the controller’s current calm-environment declaration.')
    require(not session.state['actors'][actor_id]['incapacitated'],'An incapacitated creature cannot cultivate.')
    require(fact['expires_at']>=session.clock()+7200,'The environment declaration must cover the whole two-hour session.')
    if fact['value'].get('ambient_qi')!=1:
        substitute=read(session,FAMILY,actor_id,'cultivation_substitute',fact['value'].get('substitute_scope',''),actor_id)
        require(substitute is not None and substitute['expires_at']>=session.clock()+7200,
            'Without sufficient ambient Qi, use a current native GM-approved substitute covering the whole session.')
        validate_substitute(session,substitute)
        fact['substitute_receipt']=substitute['receipt_id']
    return fact


def validate_substitute(session,record):
    value=record['value']
    require(set(value)=={'scene_id','source_description','appropriate'} and value['scene_id']==session.state['battlefield'].get('stable_id') and value['appropriate']==1 and type(value['source_description']) is str and 0<len(value['source_description'].strip())<=2000,
        'The native GM must identify an appropriate energy substitute at this actual mapped scene. This does not create or consume an inventory item.')


@hook('fact_admitted')
def substitute_admitted(session,record):
    if record['source']==FAMILY and record['kind']=='cultivation_substitute':validate_substitute(session,record)


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,sheet):
    if source!=FAMILY:return None
    actor=session.state['actors'][actor_id];state=source_state(actor)
    require(set(payload)<= {'access_scope','procedure','environment_scope'} and isinstance(payload.get('access_scope'),str),'Choose the source access and acquisition procedure.')
    access=read(session,FAMILY,actor_id,'source_access',payload['access_scope'],actor_id)
    require(access is not None,'The native world owner must grant actual Rare Variant access before acquisition.')
    value=access['value']
    require(set(value)=={'variant','route','source_rule'} and value['variant']==FAMILY and value['route'] in ('direct','conversion') and type(value['source_rule']) is str and value['source_rule'].strip(),'Supply this Variant, Direct or Conversion Entry and its legal Source Rule.')
    require(not actor['incapacitated'] and not state.get('acquired_paths'),'This creature cannot acquire this progression again.')
    paths=deepcopy(sheet.get('path_and_subpath') or {})
    ids=set(paths.get('path_feature_record_ids',[]))|set(paths.get('source_granted_subpath_feature_record_ids',[]))|set(paths.get('advancement_feature_record_ids',[]))
    path_level=owning_qi_cl(sheet,0)
    require(integer(path_level,3) and path_level<=sheet['identity']['cultivation_level'],'Acquire actual Qi Path attainment before its Variant progression.')
    selected=set(paths.get('subpath_record_ids',[]))|({paths['subpath_record_id']} if paths.get('subpath_record_id') else set())
    parent_ids=ids.intersection(OLD);procedure=payload.get('procedure','complete')
    if procedure=='train':
        require(value['route']=='conversion' and parent_ids and selected<={PARENT},'Conversion training requires the actual Mercurial parent.')
        session_environment(session,actor_id,payload.get('environment_scope'))
        session.tick(7200);state['training']=int(state.get('training',0))+1
        session.emit('QUICKSILVER_CONVERSION_SESSION',actor_id,access_receipt=access['receipt_id'],seconds=7200)
        return {'sheet':None,'acquisition_id':access['receipt_id']}
    require(procedure=='complete','Choose a complete acquisition or one training session.')
    if value['route']=='direct':
        require(not selected and not any(i.startswith('tianxia.subpath.qi.') for i in ids),'Direct Entry is the first Subpath choice; another progression cannot coexist.')
        earned=[f for f,l in zip(FEATURES,LEVELS) if l<=path_level]
    else:
        require(parent_ids and selected<={PARENT},'Conversion requires the actual attained Mercurial parent progression.')
        count=len(parent_ids);require(state.get('training',0)>=count,'Complete one Full Cultivation Session per attained parent feature.')
        state['training']-=count
        from ..gate2_rolls import DeterministicRollAuthority
        roller=DeterministicRollAuthority(session.state['journey_id']+':living_quicksilver_conversion',counter=int(state.get('roll_counter',0)))
        key=sheet['identity']['key_ability'];modifier=sheet['identity']['proficiency_bonus']+next((a['modifier'] for a in sheet['ability_scores_and_statistics']['abilities'] if a['ability']==key),0)
        roll=roller.d20(modifier=modifier,actor_id=actor_id,reason='QUICKSILVER_CONVERSION')
        state['roll_counter']=roller.counter;dc=10+sheet['identity']['proficiency_bonus']+count
        session.emit('QUICKSILVER_CONVERSION_ROLLED',actor_id,dc=dc,roll=canonical(roll.model_dump(mode='json')),sessions_spent=count)
        if roll.total<dc:return {'sheet':None,'acquisition_id':access['receipt_id']}
        earned=[new for old,new in zip(OLD,FEATURES) if old in parent_ids]
    for field in ('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids'):
        paths[field]=[s for s in paths.get(field,[]) if s not in OLD and not s.startswith(PREFIX)]
    paths['path_feature_record_ids']+=earned
    paths['subpath_record_id']=FAMILY;paths['subpath_record_ids']=[FAMILY]
    subpath={'subpath_id':FAMILY,'display_name':'Living Quicksilver Immortal Embryo','owning_path_id':'tianxia.path.qi_cultivation','source_packet_ids':[access['receipt_id']]}
    paths['subpath']=subpath;paths['subpaths']=[subpath]
    paths['bindings']=[b for b in paths.get('bindings',[]) if b.get('path_id')!='tianxia.path.qi_cultivation']+[{'path_id':'tianxia.path.qi_cultivation','subpath_id':FAMILY,'source_packet_ids':[access['receipt_id']]}]
    paths['subpath_acquisition']={'path_level':path_level,'source_rule':value['source_rule'],'route':value['route'],'access_receipt':access['receipt_id'],'earned_features':earned,'replaced_features':sorted(parent_ids)}
    paths['earned_feature_occurrences']=[r for r in paths.get('earned_feature_occurrences',[]) if r.get('feature_id') not in OLD]
    sheet['path_and_subpath']=paths;state['acquired_paths']=canonical(paths)
    if parent_ids:
        actor.get('source_states',{}).pop(PARENT,None)
        for recipient in session.state['actors'].values():
            snapshot=recipient.get('encounter_snapshot',{})
            if 'conditions' in snapshot:snapshot['conditions']={k:v for k,v in snapshot['conditions'].items() if not (json.loads(v).get('source_actor_id')==actor_id and json.loads(v).get('source_definition_id') in OLD)}
        for obj in session.state.get('runtime_objects',{}).values():
            if obj.get('owner_id')==actor_id and obj.get('component',{}).get('created_by') in OLD:obj.update(destroyed=True,current_hp=0)
    session.emit('QUICKSILVER_SOURCE_ACQUIRED',actor_id,access_receipt=access['receipt_id'],earned_features=earned,replaced_features=sorted(parent_ids),route=value['route'])
    return {'sheet':sheet,'acquisition_id':access['receipt_id']}


def sync_journey(session,actor_id):
    actor=session.state['actors'][actor_id]
    if not journey_owned(actor):return
    state=source_state(actor)
    # Bundle opt-in is the source owner's existing transport into native genesis.
    actor['bundle']['living_quicksilver_setup']=deepcopy(state)
    from ..canonical import canonical_sha256
    actor['bundle'].pop('bundle_sha256',None);actor['bundle']['bundle_sha256']=canonical_sha256(actor['bundle'])


@hook('journey_initialize')
def initialize_journey(session,actor_id):
    if journey_owned(session.state['actors'][actor_id]):sync_journey(session,actor_id)


@hook('journey_acquired')
def acquired(session,actor_id,source,acquisition_id):
    if source==FAMILY:sync_journey(session,actor_id)


@hook('journey_options')
def journey_options(session,actor_id):
    from ..fact_consent_admission import KEY
    actor=session.state['actors'][actor_id]
    if not journey_owned(actor) or actor['incapacitated']:return None
    scopes=list(dict.fromkeys(r['scope'] for r in session.state.get(KEY,[]) if
        r['source']==FAMILY and r['subject']==actor_id and r['kind']=='cultivation_environment'))
    options=[{'id':'quicksilver_short_rest','kind':'short_rest','payload':{},'auto_select':0,
        'label':actor['name']+': take a one-hour Short Rest; regain Qi equal to your Qi Cultivation CL once per long rest.'}];state=source_state(actor)
    history=state.get('recorded_history',[]);saved=state.get('preserved',[])
    maximum=actor['bundle']['actor_template']['proficiency_bonus']
    for scope in scopes:
        try:session_environment(session,actor_id,scope)
        except ValueError:continue
        base={'environment_scope':scope}
        options.append({'id':'quicksilver_cultivate:'+scope,'kind':'quicksilver_cultivate','payload':base,'auto_select':0,
            'label':actor['name']+': complete two uninterrupted hours of Full Cultivation in the declared environment. Recover all missing Qi once per long rest.'})
        if journey_owned(actor,ASSIMILATE):
            for index,pattern in enumerate(history):
                if pattern in saved:continue
                replacements=list(range(len(saved))) if len(saved)>=maximum else [-1]
                for replace_index in replacements:
                    payload={**base,'preserve':index}
                    if replace_index>=0:payload['replace']=replace_index
                    options.append({'id':'quicksilver_preserve:'+scope+':'+str(index)+':'+str(replace_index),
                        'kind':'quicksilver_cultivate','payload':payload,'auto_select':0,
                        'label':actor['name']+': two-hour Full Cultivation to preserve '+pattern['label']+
                            ('; replace '+saved[replace_index]['label'] if replace_index>=0 else '')+'.'})
    return options


@hook('journey_command')
def cultivation(session,actor_id,kind,payload):
    if kind!='quicksilver_cultivate':return None
    actor=session.state['actors'][actor_id]
    require(journey_owned(actor),'This creature has not acquired Living Mercury Body.')
    require(set(payload)<={'environment_scope','appearance','item_scope','consent_scope','preserve','replace'},'Choose only the printed cultivation options.')
    fact=session_environment(session,actor_id,payload.get('environment_scope'));state=source_state(actor)
    require(fact['expires_at']>=int(session.clock())+7200,'The environment declaration must cover the whole two-hour session.')
    appearance=payload.get('appearance',state.get('appearance',{}))
    require(isinstance(appearance,dict) and set(appearance)<={'appearance','hair','coloration','voice_resonance','surface_details'} and all(type(v) is str and len(v)<=2000 for v in appearance.values()),'Only nonfunctional superficial details may change.')
    item=None
    if payload.get('item_scope'):
        authority=read(session,FAMILY,actor_id,'item_authority',payload['item_scope'],actor_id)
        require(authority is not None,'The native item owner must supply its actual use and artifact constraints.')
        item=deepcopy(authority['value'])
        require(set(item)=={'item_id','name','kind','held','legal_use','sentient','artifact_merge'} and item['kind'] in ('weapon','shield','implement') and item['held']==1 and item['legal_use']==1 and item['artifact_merge']=='allowed','Choose an actual held weapon, shield or implement you can legally use and whose artifact rules permit merging.')
        # Identity must occur in the installed inventory, not just a declaration.
        inventory=actor['bundle'].get('carrying',{}).get('items',[])
        matches=[r for r in inventory if r.get('key')==item['item_id']]
        require(len(matches)==1,'Select the exact acquired inventory item, not an item type or duplicate.')
        require(not journey_item_lost(session,actor_id,matches[0]),'The committed native item ledger records this item dropped or held by someone else; recover it before merging.')
        item['item_key']=matches[0]['key'];item['weapon_action']=matches[0].get('weapon_action','')
        from .scoundrel_riders import object_id
        item['object_id']=object_id(actor_id,item['item_key'])
        if item['sentient']:
            consent=read(session,FAMILY,actor_id,'sentient_item_consent',payload.get('consent_scope',''),actor_id)
            require(consent and consent['value']=={'item_id':item['item_id'],'consent':1},'A sentient item must actually consent.')
        item={**item,'manifested':0}
    preserved=deepcopy(state.get('preserved',[]))
    if 'preserve' in payload:
        history=state.get('recorded_history',[]);index=payload['preserve']
        require(journey_owned(actor,ASSIMILATE) and integer(index) and index<len(history),'Choose one previously recorded native pattern.')
        pattern=history[index]
        if pattern not in preserved:
            maximum=actor['bundle']['actor_template']['proficiency_bonus']
            if len(preserved)>=maximum:
                index=payload.get('replace');require(integer(index) and index<len(preserved),'Choose one preserved pattern to replace at your Proficiency Bonus maximum.');preserved.pop(index)
            preserved.append(deepcopy(pattern))
    session.tick(7200)
    state.update(appearance=appearance,preserved=preserved)
    recover_qi(session,actor_id,'full')
    if item:
        previous=state.get('armament')
        if previous and previous.get('item_key')!=item['item_key']:
            snapshot=actor.get('encounter_snapshot',{})
            if 'conditions' in snapshot:
                snapshot['conditions']={key:encoded for key,encoded in snapshot['conditions'].items()
                    if not former_armament_location(encoded,actor_id,previous['item_key'])}
            session.emit('QUICKSILVER_ARMAMENT_RELEASED',actor_id,item_id=previous['item_id'])
        state['armament']=item
    session.emit('QUICKSILVER_FULL_CULTIVATION',actor_id,seconds=7200,environment_receipt=fact['receipt_id'],substitute_receipt=fact.get('substitute_receipt',''),appearance=appearance,preserved=preserved,item_id=item['item_id'] if item else '')
    sync_journey(session,actor_id)
    return True


@hook('journey_scene_end')
def end_scene(session,previous,current):
    for aid,actor in session.state['actors'].items():
        if not journey_owned(actor):continue
        state=source_state(actor)
        for key in ('transformation_used','replacement_used','mass_round','configuration','configuration_turn','roll_dice'):
            state.pop(key,None)
        pb=actor['bundle']['actor_template']['proficiency_bonus'];actor['resources'][MASS]=(pb+1)//2
        sync_journey(session,aid)


@hook('match_initialize',priority=100)
def initialize_combat(engine):
    initialized=False
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None or not owns(engine,actor):continue
        initialized=True
        setup=deepcopy(bundle.get('living_quicksilver_setup') or {})
        setup.pop('acquired_paths',None)
        store(engine,actor,**setup)
        if setup.get('armament'):settle_armament(engine,actor,setup['armament'])
    return True if initialized else None


@hook('journey_encounter_settled')
def retain_state(session,actor_id,engine,actor):
    if not owns(engine,actor):return
    source_state(session.state['actors'][actor_id]).update(data(actor))
    sync_journey(session,actor_id)


@hook('journey_snapshot_actor')
def strip_duplicate_ledger(actor,session,actor_id,engine):
    if not owns(engine,actor):return None
    result=actor.model_copy(deep=True)
    result.conditions={k:v for k,v in result.conditions.items() if v.condition_id!=LEDGER}
    return result

# Patterns are derived from the resolved source tree and committed effects.
def walk_effects(effects):
    for row in effects or ():
        if not isinstance(row,dict):continue
        yield row
        for key in ('effects','on_hit','on_fail','on_success','on_miss'):
            yield from walk_effects(row.get(key) or [])


def patterns_of(ctx):
    result=[]
    def add(kind,value,label):
        pattern={'kind':kind,'value':deepcopy(value),'label':label,'source':ctx.typed.get('source') or ctx.source,
                 'source_cl':int(ctx.numbers.get('cl') or 0),'save_dc':int(ctx.numbers.get('save_dc') or 0),
                 'authority':list(ctx.typed.get('authority_tags') or ctx.typed.get('tags') or [])}
        if pattern not in result:result.append(pattern)
    for row in walk_effects(ctx.typed.get('effects')):
        kind=row.get('type')
        if kind in ('damage','extra_damage'):
            for value in row.get('damage_types') or []:add('damage',str(value).upper(),str(value).title()+' damage')
        if kind in ('flight','movement_mode','climb_speed','swim_speed'):
            mode=row.get('mode') or ('fly' if kind=='flight' else 'climb' if kind=='climb_speed' else 'swim')
            add('movement',{'mode':mode,'speed_ft':min(60,int(row.get('fly_speed_ft') or row.get('speed_ft') or row.get('distance_ft') or 0))},mode.title()+' movement')
        if kind=='resistance':
            for value in row.get('damage_types') or []:add('resistance',str(value).upper(),str(value).title()+' Resistance against one packet')
        if kind=='damage_reduction' and integer(row.get('flat'),1):add('reduction',row['flat'],'Damage reduction '+str(row['flat']))
        if kind in ('push','pull') or (kind=='condition' and row.get('condition') in ('prone','grappled','restrained')) or kind=='no_reactions':
            clean={k:deepcopy(v) for k,v in row.items() if k in ('type','condition','distance_ft','save_ability','duration','expires_on','physical')}
            add('rider',clean,str(row.get('condition') or kind).replace('_',' ').title())
        if kind in ('concealment','revelation') or (kind=='condition' and row.get('condition') in ('invisible','revealed')):
            clean={k:deepcopy(v) for k,v in row.items() if k in ('type','condition','range_ft','sense','distance_ft')}
            add('information',clean,kind.title()+' structure')
    area=ctx.typed.get('area')
    if area and area.get('shape'):add('area',{'shape':area['shape'],'size_ft':int(area.get('size_ft') or 0)},area['shape'].title()+' area shape')
    from ..weapon_delivery import delivery_kind
    if delivery_kind(ctx.typed,{},ctx.action.parameters)=='weapon':add('weapon',{'delivery':'weapon'},'Weapon delivery')
    return result


@hook('technique_used',priority=200)
def record_pattern(ctx):
    if not qi_action(ctx.action):return
    from ..target_knowledge import can_see
    from ..relations import relation,ENEMY
    first=ctx.technique_event_start
    if type(first) is not int or not 0<=first<=len(ctx.engine.events):return
    changed=set();settled_types=[]
    for event in ctx.engine.events[first:]:
        if event.source_definition_id!=ctx.source:continue
        if event.event_type in ('DAMAGE_COMMITTED','CONDITION_APPLIED','MODIFIER_APPLIED','MOVEMENT_COMMITTED','OBJECT_UPDATED','SAVE_ROLLED'):
            changed.update(event.target_ids)
            if event.event_type in ('SAVE_ROLLED','MOVEMENT_COMMITTED'):changed.add(event.actor_id)
            if event.event_type=='DAMAGE_COMMITTED':
                kind=event.payload.get('damage_type')
                if type(kind) is str and kind.upper() not in settled_types:settled_types.append(kind.upper())
            elif event.event_type=='OBJECT_UPDATED':
                for part in (event.payload.get('damage') or {}).get('components',[]):
                    if part['damage_type'] not in settled_types:settled_types.append(part['damage_type'])
    patterns=patterns_of(ctx)
    # Observe the resolved components (including real conversions/choices),
    # never an unchosen type merely listed in the source's possible menu.
    templates=[p for p in patterns if p['kind']=='damage']
    if templates:
        patterns=[{**deepcopy(templates[0]),'value':kind,'label':kind.title()+' damage'} for kind in settled_types]+[p for p in patterns if p['kind']!='damage']
    authority=source_declaration(ctx.engine,ctx.actor.entity_id,ctx.typed.get('source') or ctx.source,'pattern_authority')
    if authority:
        for pattern in patterns:pattern['authority']=list(dict.fromkeys([*pattern['authority'],*authority['categories']]))
    if not patterns:return
    for owner in list(ctx.engine.state.actors.values()):
        if not owns(ctx.engine,owner,ASSIMILATE) or not owner.reaction_available or owner.resources.get(QI,0)<3 or not available(ctx.engine,owner,'record_round',True):continue
        if relation(ctx.engine,ctx.actor,owner)!=ENEMY:continue
        if not ({owner.entity_id}|{o.object_id for o in bodies(ctx.engine,owner)}).intersection(changed):continue
        if not can_see(ctx.engine,owner,ctx.actor):continue
        options={str(i):p for i,p in enumerate(patterns)}
        selected=choose(ctx.engine,owner,'record_pattern',list(options),{i:p['label'] for i,p in options.items()},
            prompt=f'{owner.display_name} was affected by {ctx.action.display_name}. Record one visible or sensed pattern? Costs your Reaction and 3 Qi, once per round.',optional=True,intent=ctx.intent)
        if selected is None:continue
        pattern=options[selected]
        ctx.engine._spend_resource(owner,QI,3,ASSIMILATE);owner.reaction_available=False;mark(ctx.engine,owner,'record_round',True);gain(ctx.engine,owner)
        ctx.engine._append_event('REACTION_RESOLVED',ASSIMILATE,actor_id=owner.entity_id,target_ids=(ctx.actor.entity_id,),payload={'pattern_kind':pattern['kind'],'pattern_source':pattern['source']})
        protected={'secret','immortal','legendary','artifact','bloodline-exclusive','bloodline_exclusive','soul-exclusive','soul_exclusive','conceptual'}
        tags={str(t).lower() for t in pattern['authority']}
        # Source classifications come from the actual typed authority, never from names.
        if tags&protected:
            require(pattern['save_dc']>0,'A protected pattern needs its actual source save DC.')
            from .ability_source import cultivation_check
            if not cultivation_check(ctx.engine,owner,numbers(ctx.engine,owner),pattern['save_dc'],ASSIMILATE,'Assimilate the protected pattern'):
                note(ctx.engine,ASSIMILATE,owner,'The pattern exceeds your current assimilation. You do not record it.');continue
        history=data(owner).get('recorded_history',[])
        if pattern not in history:history.append(deepcopy(pattern))
        saved=deepcopy(data(owner).get('preserved',[]))
        if pattern not in saved and len(saved)>=int(owner.proficiency_bonus):
            choices={str(i):p for i,p in enumerate(saved)}
            index=choose(ctx.engine,owner,'replace_preserved',list(choices),{i:p['label'] for i,p in choices.items()},
                prompt=owner.display_name+': your Living Treasury is at its Proficiency Bonus maximum. Replace one preserved pattern with '+pattern['label']+'.',intent=ctx.intent)
            require(index in choices,'Select one preserved pattern to replace.')
            saved[int(index)]=deepcopy(pattern)
        store(ctx.engine,owner,pattern=pattern,recorded_history=history,preserved=saved);gain(ctx.engine,owner)


@hook('before_target_reactions',priority=-100)
def prepare_activation(ctx):
    if not owns(ctx.engine,ctx.actor) or not qi_action(ctx.action) or ctx.action.parameters.get('quicksilver_command'):return
    if ctx.damage_cache.get('quicksilver_prepared'):return
    ctx.damage_cache['quicksilver_prepared']=1
    pattern=data(ctx.actor).get('pattern')
    if pattern and owns(ctx.engine,ctx.actor,ASSIMILATE) and available(ctx.engine,ctx.actor,'express_turn'):
        costs=['free'] if transformed(ctx.actor) else ([QI] if ctx.actor.resources.get(QI,0)>=2 else [])+([MASS] if ctx.actor.resources.get(MASS,0)>=1 else [])
        if costs:
            chosen=choose(ctx.engine,ctx.actor,'express_pattern',costs,{QI:'Pay 2 Qi',MASS:'Pay 1 Quicksilver Mass','free':'Express Pattern for no Qi or Mass'},
                prompt=f'{ctx.actor.display_name}: express {pattern["label"]} through {ctx.action.display_name}? Once per turn.',optional=True,intent=ctx.intent)
            if chosen:
                if chosen!='free':ctx.engine._spend_resource(ctx.actor,chosen,2 if chosen==QI else 1,ASSIMILATE)
                ctx.damage_cache['quicksilver_expression']=deepcopy(pattern);mark(ctx.engine,ctx.actor,'express_turn')
                apply_expression(ctx,pattern)
    multiple_origins(ctx)


def apply_expression(ctx,pattern):
    kind,value=pattern['kind'],pattern['value']
    if kind=='movement':
        mode=value['mode'];speed=min(60,int(value['speed_ft']))
        grant={'label':'Express Pattern: '+pattern['label']}
        if mode=='fly':grant.update(fly_speed_ft=speed,flight_hover=0)
        elif mode=='climb':grant['climb_speed_ft']=speed
        elif mode=='swim':grant['swim_speed_ft']=speed
        else:require(False,'The recorded movement mode is not mechanically represented.')
        ctx.engine._apply_condition(ctx.actor,'condition:typed.quicksilver_movement',ASSIMILATE,ctx.actor.entity_id,expires_on='END_OF_CURRENT_TURN',data=grant)
    elif kind in ('resistance','reduction'):
        ctx.engine._apply_condition(ctx.actor,'condition:typed.quicksilver_packet_defense',ASSIMILATE,ctx.actor.entity_id,
            expires_on='END_OF_CURRENT_TURN',data={'kind':kind,'value':value,'label':'Express Pattern: one triggering damage packet'})
    elif kind=='information':
        from ..typed_executor import run_effects
        row={**value,'applies_to':'self','expires_on':'START_OF_SOURCE_NEXT_TURN'}
        if row['type'] in ('concealment','revelation'):row={'type':'condition','condition':'invisible' if row['type']=='concealment' else 'revealed','applies_to':'self','expires_on':'START_OF_SOURCE_NEXT_TURN'}
        run_effects(ctx,[row])
    elif kind=='area':
        old=ctx.typed.get('area') or {}
        require(old and old.get('size_ft'),'Expressing an area requires an area activation.')
        # Preserve the activation's largest printed linear dimension.
        area={**old,'shape':value['shape'],'size_ft':min(int(value['size_ft']),int(old['size_ft']))}
        ctx.typed['area']=area
        aim=ctx.damage_cache.get('_checkpoint_aim') or ctx.actor.position
        from ..typed_executor import area_cells
        from ..action_geometry import point
        cells=set(area_cells(ctx.engine,point(ctx.engine,ctx.actor),aim,area,include_altitude=True))
        ctx.targets[:]=[a for a in ctx.engine.state.actors.values() if a.active and a.position in cells]
        ctx.target=ctx.targets[0] if len(ctx.targets)==1 else None
    elif kind=='weapon':
        from ..weapon_delivery import ready_weapons
        require(bool(ready_weapons(ctx.engine,ctx.actor)),'A recorded delivery cannot fabricate a usable weapon or a weapon technique.')
        require(ctx.typed.get('weapon') or ctx.typed.get('weapon_delivery'),'This activation does not authorize weapon delivery.')


def conversion(ctx,kinds,targets):
    if not owns(ctx.engine,ctx.actor) or not qi_action(ctx.action) or ctx.action.parameters.get('quicksilver_command'):return None
    pattern=ctx.damage_cache.get('quicksilver_expression')
    if pattern and pattern['kind']=='damage' and not ctx.damage_cache.get('quicksilver_expression_damage'):
        ctx.damage_cache['quicksilver_expression_damage']=1
        return pattern['value']
    if not available(ctx.engine,ctx.actor,'conversion_turn'):return None
    cost=0 if transformed(ctx.actor) else 1
    if ctx.actor.resources.get(QI,0)<cost:return None
    picked=choose(ctx.engine,ctx.actor,'conversion',MERCURIAL,{k:k.title() for k in MERCURIAL},prompt=f'{ctx.actor.display_name}: convert one damage component of {ctx.action.display_name} to one Mercurial Type? Costs {cost} Qi, once per turn; first qualifying weapon attack only.',optional=True,intent=ctx.intent)
    if picked:
        if cost:ctx.engine._spend_resource(ctx.actor,QI,cost,LIVING)
        mark(ctx.engine,ctx.actor,'conversion_turn')
    return picked


@hook('damage_roll_bonus')
def converged_roll(ctx,row,kinds):
    if not owns(ctx.engine,ctx.actor) or not qi_action(ctx.action):return None
    count=int(data(ctx.actor).get('roll_dice',0))
    if not count:return None
    roll=ctx.engine.roller.roll(DiceSpec(count=count,sides=8),actor_id=ctx.actor.entity_id,reason='QUICKSILVER_CONVERGED_DAMAGE');ctx.engine._record_roll(roll)
    store(ctx.engine,ctx.actor,roll_dice=0)
    return roll.total


@hook('healing_roll_resolved')
def converged_healing(ctx,row,amount):
    bonus=converged_roll(ctx,row,())
    return amount+bonus if bonus else None


@hook('damage_dealt')
def expressed_rider(ctx,subject,amount):
    pattern=ctx.damage_cache.get('quicksilver_expression')
    if amount<=0 or not pattern or pattern['kind']!='rider' or ctx.damage_cache.get('quicksilver_rider_applied'):return
    if ctx.origin_save is not None and not ctx.failed_save:return
    from ..typed_executor import run_effects
    ctx.damage_cache['quicksilver_rider_applied']=1
    run_effects(replace(ctx,target=subject,targets=[subject]),[{**deepcopy(pattern['value']),'applies_to':'target'}])


@hook('before_damage_defenses')
def expression_packet(engine,target,amount,kind,source,source_actor_id):
    from ..pending_damage import current,packet_scratch
    packet,scratch=current(engine),packet_scratch(engine)
    if packet is None or scratch is None or packet.target_id!=target.entity_id:return
    key=('quicksilver_pattern_defense',target.entity_id,str(kind).upper())
    if key in scratch:return
    held=next((c for c in target.conditions.values() if c.condition_id=='condition:typed.quicksilver_packet_defense'),None)
    if not held:return
    value=held.data['value'];category=held.data['kind']
    if category=='resistance' and str(value).upper()!=str(kind).upper():return
    scratch[key]=deepcopy(held.data)
    engine._remove_condition_instance(target,held.instance_id,ASSIMILATE)


@hook('damage_defenses')
def expression_defense(engine,target,kind,typed,source_actor_id):
    from ..pending_damage import current,packet_scratch
    packet,scratch=current(engine),packet_scratch(engine)
    if packet is None or scratch is None or packet.target_id!=target.entity_id:return None
    row=scratch.get(('quicksilver_pattern_defense',target.entity_id,str(kind).upper()))
    if not row:return None
    return [{'kind':'resistance','damage_types':[str(row['value']).upper()]}] if row['kind']=='resistance' else [{'kind':'reduction','damage_types':[str(kind).upper()],'amount':int(row['value'])}]


def multiple_origins(ctx):
    if not owns(ctx.engine,ctx.actor,COURT) or not ctx.typed.get('area') or not available(ctx.engine,ctx.actor,'multiple_turn'):return
    extra=0 if transformed(ctx.actor) else 2
    if ctx.actor.resources.get(QI,0)<extra:return
    from ..action_geometry import point,record_for
    first=point(ctx.engine,ctx.actor)
    origins=[r for r in origin_records(ctx.engine,ctx.actor) if Position(**r['position'])!=first]
    options={r['id']:r for r in origins}
    selected=choose(ctx.engine,ctx.actor,'multiple_origins',list(options),{k:v['label'] for k,v in options.items()},
        prompt=f'{ctx.actor.display_name}: resolve {ctx.action.display_name} from one additional legal origin? Pay its cost once plus {extra} Qi. Overlap affects each creature once, with Disadvantage on one save.',optional=True,intent=ctx.intent)
    if selected is None:return
    from ..typed_executor import area_cells
    area=ctx.typed['area'];second=Position(**options[selected]['position']);aim=ctx.damage_cache.get('_checkpoint_aim') or first
    first_cells=set(area_cells(ctx.engine,first,aim,area,include_altitude=True))
    second_cells=set(area_cells(ctx.engine,second,aim,area,include_altitude=True))
    # Native recipient policy and per-payload safeguards are still enforced by
    # the executor after the geometric union; no repeated effects per overlap.
    ctx.damage_cache['quicksilver_overlap']=[a.entity_id for a in ctx.engine.state.actors.values() if a.position in first_cells&second_cells]
    ctx.damage_cache['quicksilver_origins']=[first,second]
    ctx.targets[:]=[a for a in ctx.engine.state.actors.values() if a.active and a.position in first_cells|second_cells]
    ctx.target=ctx.targets[0] if len(ctx.targets)==1 else None
    if extra:ctx.engine._spend_resource(ctx.actor,QI,extra,COURT)
    mark(ctx.engine,ctx.actor,'multiple_turn')
    note(ctx.engine,COURT,ctx.actor,ctx.action.display_name+' resolves from two different origins; each creature is affected once.',origins=[p.model_dump(mode='json') for p in (first,second)])


@hook('save')
def overlapping_save(ctx,subject,ability,named):
    if subject.entity_id in ctx.damage_cache.get('quicksilver_overlap',[]):return {'bonus':0,'modes':['DISADVANTAGE']}
    return None


def teleport_context(engine,owner,source,intent=None):
    from ..typed_executor import Context
    action=next((a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id and (a.parameters.get('typed') or {}).get('source')==source),None)
    action=action or next(a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id)
    return Context(engine,owner,action,intent or getattr(engine,'_active_intent',None),{'source':source,'numbers':numbers(engine,owner)},[],None)


def teleport_permitted(ctx,actor,destination):
    from ..typed_executor import condition_rules
    from . import run_strict
    if any(r.get('no_teleport') for r in condition_rules(actor)):return False
    if False in run_strict('subject_teleport_attempt',ctx,actor,actor.position,destination):return False
    if False in run_strict('teleport_gate',ctx,actor.position,destination):return False
    if False in run_strict('teleport_check',ctx.engine,actor,actor.position,destination):return False
    if False in run_strict('teleport_context_check',ctx.engine,actor,actor.position,destination,'WILLING'):return False
    return True


def exchange(engine,owner,obj,source,intent):
    from ..typed_executor import teleport_subject
    ctx=teleport_context(engine,owner,DIVIDE,intent)
    if not teleport_permitted(ctx,owner,obj.position):return False
    # Remove only the arriving Body from occupancy for the atomic exchange.
    old=owner.position;destination=obj.position
    engine._update_object(obj.model_copy(update={'position':old}),DIVIDE,owner.entity_id)
    teleport_subject(ctx,owner,destination)
    if owner.position!=destination:
        engine._update_object(obj,DIVIDE,owner.entity_id);return False
    return True


def exchange_reaction_available(engine,owner,obj):
    return owner.reaction_available or bool(transformed(owner) and obj.component.get('reaction_round')!=engine.state.round_number)


def spend_exchange_reaction(engine,owner,obj,intent=None):
    choices=[]
    if owner.reaction_available:choices.append('owner')
    if transformed(owner) and obj.component.get('reaction_round')!=engine.state.round_number:choices.append('body')
    require(choices,'Exchange Substance needs your Reaction or this perfected Body’s Reaction.')
    selected=choose(engine,owner,'exchange_reaction',choices,{'owner':'Use your Reaction','body':'Use this perfected Body’s Reaction'},
        prompt=owner.display_name+': choose whose Reaction powers Exchange Substance. The once-per-round feature limit still applies.',intent=intent) if len(choices)>1 else choices[0]
    if selected=='owner':owner.reaction_available=False
    else:
        obj=obj.model_copy(update={'component':{**obj.component,'reaction_round':engine.state.round_number}})
        engine._update_object(obj,DIVIDE,owner.entity_id)
    return obj


@hook('hit_response',priority=-100)
def exchange_self_hit(engine,attacker,target,spec,total,natural,effective_ac):
    if not owns(engine,target,DIVIDE) or not available(engine,target,'exchange_round',True):return None
    cost=0 if transformed(target) else 1
    if target.resources.get(MASS,0)<cost:return None
    options=[o for o in bodies(engine,target) if engine.grid.distance_ft(target.position,o.position)<=60 and exchange_reaction_available(engine,target,o)]
    if not options:return None
    selected=choose(engine,target,'exchange_substance',[o.object_id for o in options],{o.object_id:o.component['name'] for o in options},
        prompt=f'{attacker.display_name} hits {target.display_name}. Exchange positions with one Body within 60 feet? Reaction, {cost} Quicksilver Mass, once per round; the same roll resolves against the arriving Body.',optional=True)
    if not selected:return None
    obj=next(o for o in options if o.object_id==selected)
    obj=spend_exchange_reaction(engine,target,obj,getattr(engine,'_active_intent',None))
    if cost:engine._spend_resource(target,MASS,cost,DIVIDE)
    mark(engine,target,'exchange_round',True)
    if not exchange(engine,target,obj,DIVIDE,getattr(engine,'_active_intent',None)):return None
    arriving=engine.state.objects[obj.object_id]
    # Same attack roll, no independent re-roll or extra attack. Native object
    # damage resolves the actual attack dice, Critical Hit and Body defenses.
    reach=int(spec.get('range_ft') or spec.get('reach_ft') or 5)
    from ..action_geometry import point
    legal=(engine.grid.distance_ft(point(engine,attacker),arriving.position)<=reach
        and engine.grid.line_of_sight(point(engine,attacker),arriving.position)
        and engine.grid.line_of_physical_transmission(point(engine,attacker),arriving.position))
    if legal and natural!=1 and (natural==20 or total>=int(arriving.ac)):
        dice=spec.get('damage')
        if isinstance(dice,dict):dice=DiceSpec(**dice)
        if dice:
            roll=engine.roller.roll(dice,actor_id=attacker.entity_id,reason='DAMAGE:'+str(spec.get('source_definition_id'))+':exchange',critical=natural==20);engine._record_roll(roll)
            from .objects import deal
            deal(engine,attacker,arriving,[(roll.total,str(spec.get('damage_type') or 'UNTYPED'))],str(spec.get('source_definition_id')))
    engine._append_event('REACTION_RESOLVED',DIVIDE,actor_id=target.entity_id,target_ids=(arriving.object_id,),payload={'same_attack_total':total,'arriving_legal':int(legal),'log':'Exchange Substance: the original attack resolves against the arriving Quicksilver Body using the same roll.'})
    return {'hit':False,'miss_reason':'forced'}


def reconstruction_blocked(engine,target,source):
    action=engine.action_catalog.get(source);typed=(action.parameters.get('typed') or {}) if action else {}
    continuity={**(typed.get('continuity_outcome') or {}),**(source_declaration(engine,action.owner_id,typed.get('source') or source,'body_effect',target.entity_id) if action else {})}
    return bool(continuity.get('erases_all_substance') or continuity.get('destroys_soul_and_embryo') or continuity.get('captures_soul_and_embryo') or continuity.get('prevents_reconstruction') or
        (continuity.get('superior_authority') in ('void','samsara','conceptual') and continuity.get('defeated_defense')==1))


def reconstitute(engine,target,source,intent=None):
    if not owns(engine,target,UNDYING) or not transformed(target) or reconstruction_blocked(engine,target,source):return False
    points={o.object_id:o.position for o in bodies(engine,target)}
    points['current']=target.position
    selected=choose(engine,target,'reconstitution_space',list(points),{k:'Current space' if k=='current' else 'Destroyed Body’s former space' for k in points},
        prompt=f'{target.display_name}: Immortal Reconstitution destroys every surviving Body, ends the transformation, restores {5*target.proficiency_bonus} HP, empties Qi, and adds 1 Exhaustion. Choose where to re-form.',intent=intent)
    for obj in list(bodies(engine,target)):retire_body(engine,target,obj,UNDYING)
    engine._remove_condition(target,FORM,UNDYING)
    # Reconstruction is a new body in a former space, not a teleport subject to
    # teleport locks. The source explicitly names the legal former positions.
    old=target.position;target.position=points.get(selected,target.position)
    if target.position!=old:engine._append_event('MOVEMENT_COMMITTED',UNDYING,actor_id=target.entity_id,payload={'path':[old.model_dump(mode='json'),target.position.model_dump(mode='json')],'destination':target.position.model_dump(mode='json'),'cost_ft':0,'reconstruction':True})
    from .life_state import heal_to
    heal_to(engine,target,5*int(target.proficiency_bonus),UNDYING,target.entity_id)
    if target.resources.get(QI,0):engine._spend_resource(target,QI,target.resources[QI],UNDYING)
    from .forged_exhaustion import add
    add(engine,target,1,UNDYING)
    note(engine,UNDYING,target,target.display_name+' re-forms through Immortal Reconstitution. Undying Prima Materia ends; Qi becomes 0 and Exhaustion increases by 1.')
    return True


@hook('lethal_damage',priority=-100)
def prevent_zero(engine,target,remaining,kind,source,source_actor_id,intent):
    if not owns(engine,target):return None
    if transformed(target) and not reconstruction_blocked(engine,target,source):
        # Settle the lethal packet before reconstructing; a floor prevents it
        # consuming the newly restored HP. The post-commit receipt does the heal.
        store(engine,target,reconstitution_pending=source)
        return min(target.current_hp,1)
    if not owns(engine,target,COURT) or data(target).get('replacement_used') or not target.reaction_available or target.resources.get(MASS,0)<2:return None
    if remaining-target.temporary_hp-target.current_hp>=target.maximum_hp:return None
    obj=select_body(engine,target,'replacement_body',120,optional=True,intent=intent)
    if not obj:return None
    ctx=teleport_context(engine,target,COURT,intent)
    target.reaction_available=False;engine._spend_resource(target,MASS,2,COURT);store(engine,target,replacement_used=1)
    destination=obj.position;retire_body(engine,target,obj,COURT)
    from ..typed_executor import teleport_subject
    teleport_subject(ctx,target,destination)
    for c in list(target.conditions.values()):
        if c.condition_id.removeprefix('condition:typed.').lower() in ('grappled','restrained'):engine._remove_condition_instance(target,c.instance_id,COURT)
    # Temporary HP is granted after this same packet settles, so it cannot
    # accidentally absorb its own triggering damage.
    store(engine,target,replacement_temp_pending=2*int(target.proficiency_bonus))
    return 1


@hook('event',nested=True,priority=100)
def settle_survival(engine,event_type,kwargs):
    if event_type!='DAMAGE_COMMITTED':return
    for aid in kwargs.get('target_ids') or ():
        target=engine.state.actors.get(aid)
        if not target or not owns(engine,target):continue
        state=data(target)
        if state.get('reconstitution_pending'):
            source=state['reconstitution_pending'];store(engine,target,reconstitution_pending='')
            reconstitute(engine,target,source,getattr(engine,'_active_intent',None))
        elif state.get('replacement_temp_pending'):
            n=state['replacement_temp_pending'];store(engine,target,replacement_temp_pending=0)
            engine._grant_temp_hp(target,n,COURT,target.entity_id)


from .life_state import handler as death_handler

def continuity(engine,target,cause,source):
    if reconstitute(engine,target,source):return True
    if not owns(engine,target,COURT) or not bodies(engine,target):return False
    action=engine.action_catalog.get(source);typed=action.parameters.get('typed',{}) if action else {}
    consequence={**(typed.get('continuity_outcome') or {}),**(source_declaration(engine,action.owner_id,typed.get('source') or source,'body_effect',target.entity_id) if action else {})}
    if cause==consequence.get('cause') and cause in ('decapitation','dismemberment','segment_destruction') and not reconstruction_blocked(engine,target,source) and not consequence.get('erases_embryo'):
        note(engine,COURT,target,target.display_name+' survives bodily destruction because living substance remains in a Quicksilver Body.')
        return True
    return False


@hook('compile_actions',priority=200)
def distributed_options(info):
    if UNDYING not in info['owned_ids']:return None
    result=[]
    for action in info['actions']:
        if str(action.economy)!='BONUS_ACTION' or action.parameters.get('quicksilver_command'):continue
        params=deepcopy(action.parameters);params['quicksilver_delivery']=1
        result.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'.quicksilver_court',
            'display_name':'Distributed Court: '+action.display_name,'economy':'NONE','parameters':params}))
    return result


@hook('candidate_allowed')
def distributed_candidate(engine,actor,candidate,action):
    if action is None or not action.parameters.get('quicksilver_delivery'):return None
    if not owns(engine,actor,UNDYING) or not transformed(actor) or data(actor).get('configuration')!='distributed' or not available(engine,actor,'court_delivery'):return False
    record=candidate.metadata.get('effect_origin') or {}
    return record.get('id') in {o.object_id for o in bodies(engine,actor)}


@hook('technique_accepted')
def mark_distributed(engine,actor,action):
    if action.parameters.get('quicksilver_delivery'):
        require(owns(engine,actor,UNDYING) and available(engine,actor,'court_delivery'),'Distributed Court grants one delivery during this turn.')
        mark(engine,actor,'court_delivery')


def deliver_bonus(ctx):
    # Each compiled Bonus Action has its own free-delivery sibling, preserving
    # complete native target, costs, use-limit and origin validation.
    note(ctx.engine,UNDYING,ctx.actor,'Choose one of the Distributed Court feature options in the action menu; each names its normal cost and its Body origin.')


def armament_attack(ctx,origin,used_targets=None):
    from ..typed_executor import run_effects
    from ..action_geometry import activate
    from ..attack_declaration import can_target
    action=next((a for a in ctx.engine.action_catalog.values() if a.owner_id==ctx.actor.entity_id and a.display_name=='Domain Armament Attack'),None)
    require(action is not None,'Weapon-Sea requires an actually acquired Domain Armament Attack.')
    options={a.entity_id:a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
        and ctx.engine.grid.distance_ft(Position(**origin['position']),a.position)<=5}
    from ..target_knowledge import can_see
    target=choose(ctx.engine,ctx.actor,'sea_target_'+origin['id'],list(options),{k:v.display_name for k,v in options.items()},prompt='Weapon-Sea: choose a creature within 5 feet of '+origin['label']+' for one ordinary Domain Armament Attack.',intent=ctx.intent,known=[k for k,v in options.items() if can_see(ctx.engine,ctx.actor,v)])
    require(target is not None,'Choose a legal Domain Armament Attack target.')
    typed=deepcopy(action.parameters['typed'])
    # The ordinary Armament hit profile, not its movement selector, supplies
    # the printed attack/damage. It is one attack with shared turn riders.
    effects=[r for r in typed.get('effects',[]) if r.get('type')=='attack']
    if not effects:
        effects=[{'type':'attack','attack_kind':'cultivation_melee','count':1,'on_hit':[{'type':'damage','dice':{'count':3 if level(ctx.engine,ctx.actor)>=17 else 2 if level(ctx.engine,ctx.actor)>=13 else 1,'sides':8},'formula':'key_ability_modifier','damage_types':['force'],'applies_to':'target'}],'on_miss':[]}]
    with activate(ctx.engine,ctx.actor,ctx.source,origin):
        sub=replace(ctx,targets=[options[target]],target=options[target],typed={**typed,'effects':effects,'source':typed.get('source') or ctx.source})
        run_effects(sub,effects)


def weapon_sea(ctx,mode):
    require(transformed(ctx.actor) and data(ctx.actor).get('configuration')=='sea','Choose Weapon-Sea at the start of this turn.')
    origins={r['id']:r for r in sea_origins(ctx.engine,ctx.actor)}
    first=choose(ctx.engine,ctx.actor,'sea_first',list(origins),{k:v['label'] for k,v in origins.items()},prompt='Weapon-Sea: choose the first origin.',intent=ctx.intent)
    second=choose(ctx.engine,ctx.actor,'sea_second',[k for k in origins if k!=first],{k:v['label'] for k,v in origins.items() if k!=first},prompt='Weapon-Sea: choose a different second origin.',intent=ctx.intent)
    require(first is not None and second is not None,'Choose two different legal origins.')
    if mode=='guard':
        grants={}
        for key in (first,second):
            pos=Position(**origins[key]['position']);options={a.entity_id:a for a in ctx.engine.state.actors.values() if a.active and ctx.engine.grid.distance_ft(pos,a.position)<=5}
            chosen=choose(ctx.engine,ctx.actor,'sea_guard_'+key,list(options),{k:a.display_name for k,a in options.items()},prompt='Weapon-Sea Guard Mode: protect one creature within 5 feet of '+origins[key]['label']+' with +2 AC against ranged attacks until your next turn starts. The protection ends if it leaves every protecting origin.',optional=True,intent=ctx.intent)
            if chosen:grants.setdefault(chosen,[]).append(key)
        for aid,keys in grants.items():
            target=ctx.engine.state.actors[aid]
            for held in list(target.conditions.values()):
                if held.condition_id==SEA_GUARD and held.source_actor_id==ctx.actor.entity_id:ctx.engine._remove_condition_instance(target,held.instance_id,UNDYING)
            ctx.engine._apply_condition(target,SEA_GUARD,UNDYING,ctx.actor.entity_id,expires_on='START_OF_SOURCE_NEXT_TURN',
                data={'origins':keys,'label':'Weapon-Sea Guard Mode: +2 AC against ranged attacks while within 5 feet of a protecting origin'})
        return
    if mode=='technique':
        from ..typed_executor import run_effects
        from ..action_geometry import activate
        from ..weapon_delivery import delivery_kind
        actions={a.source_definition_id:a for a in ctx.engine.action_catalog.values() if a.owner_id==ctx.actor.entity_id and qi_action(a) and not a.parameters.get('quicksilver_delivery') and not a.parameters.get('quicksilver_command') and delivery_kind(a.parameters.get('typed',{}),{},a.parameters)=='weapon' and all(ctx.actor.resources.get(r,0)>=n for r,n in a.costs)}
        selected=choose(ctx.engine,ctx.actor,'sea_technique',list(actions),{k:a.display_name for k,a in actions.items()},prompt='Weapon-Sea: choose one authorized weapon-delivered technique. Pay its full normal costs; its riders apply once.',intent=ctx.intent)
        require(selected is not None,'Acquire an authorized weapon-delivered technique before choosing this option.')
        action=actions[selected]
        options={a.entity_id:a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor and ctx.engine.grid.distance_ft(Position(**origins[first]['position']),a.position)<=int(action.range_ft or action.reach_ft or 5)}
        target=choose(ctx.engine,ctx.actor,'sea_technique_target',list(options),{k:a.display_name for k,a in options.items()},prompt='Weapon-Sea: choose one legal target for '+action.display_name+'.',intent=ctx.intent)
        require(target is not None,'This delivered technique needs a legal target.')
        for r,n in action.costs:ctx.engine._spend_resource(ctx.actor,r,n,selected)
        with activate(ctx.engine,ctx.actor,selected,origins[first]):
            sub=replace(ctx,action=action,typed=deepcopy(action.parameters['typed']),targets=[options[target]],target=options[target])
            run_effects(sub,sub.typed['effects'])
        armament_attack(ctx,origins[second])
    else:
        armament_attack(ctx,origins[first]);armament_attack(ctx,origins[second])


@hook('perception_origins')
def distributed_perception(engine,viewer):
    if not owns(engine,viewer,COURT):return None
    return [{'id':o.object_id,'position':o.position.model_dump(mode='json')} for o in bodies(engine,viewer)]


@hook('event',nested=True)
def end_perfection(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED' or (kwargs.get('payload') or {}).get('condition_id')!=FORM:return
    owner=engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None:return
    for obj in bodies(engine,owner):
        maximum=2*int(obj.component['source_cl'])
        ctx={**obj.component,'perfected':0,'fly_speed_ft':0,'hover':0}
        engine._update_object(obj.model_copy(update={'maximum_hp':maximum,'current_hp':min(maximum,int(obj.current_hp)),'component':ctx}),UNDYING,owner.entity_id)


@hook('object_hit_response')
def exchange_body_hit(ctx,obj,total,natural):
    if not obj.component.get('quicksilver_body'):return None
    owner=ctx.engine.state.actors.get(obj.owner_id)
    if owner is None or not owns(ctx.engine,owner,DIVIDE) or not available(ctx.engine,owner,'exchange_round',True):return None
    cost=0 if transformed(owner) else 1
    body_reaction=bool(transformed(owner)) and obj.component.get('reaction_round')!=ctx.engine.state.round_number
    if not owner.reaction_available and not body_reaction or owner.resources.get(MASS,0)<cost:return None
    if ctx.engine.grid.distance_ft(owner.position,obj.position)>60:return None
    accepted=choose(ctx.engine,owner,'body_exchange',['exchange'],{'exchange':'Exchange Substance: swap with the hit Body'},prompt=f'{ctx.actor.display_name} hits {obj.component["name"]}. Exchange positions so {owner.display_name} faces the same attack roll? Costs {cost} Mass and '+('your or the perfected Body’s Reaction.' if body_reaction else 'your Reaction.'),optional=True,intent=ctx.intent)
    if accepted is None:return None
    obj=spend_exchange_reaction(ctx.engine,owner,obj,ctx.intent)
    if cost:ctx.engine._spend_resource(owner,MASS,cost,DIVIDE)
    mark(ctx.engine,owner,'exchange_round',True)
    if not exchange(ctx.engine,owner,obj,DIVIDE,ctx.intent):return None
    reach=int(ctx.action.range_ft or ctx.action.reach_ft or 5)
    from ..action_geometry import point
    legal=(ctx.engine.grid.distance_ft(point(ctx.engine,ctx.actor),owner.position)<=reach and ctx.engine.grid.line_of_sight(point(ctx.engine,ctx.actor),owner.position) and ctx.engine.grid.line_of_physical_transmission(point(ctx.engine,ctx.actor),owner.position))
    if legal and natural!=1 and (natural==20 or total>=owner.armor_class+ctx.engine._ac_modifier(owner)):
        weapon=ctx.typed.get('object_weapon') or ctx.typed.get('weapon') or {}
        dice=weapon.get('damage')
        if dice:
            roll=ctx.engine.roller.roll(DiceSpec(**dice),actor_id=ctx.actor.entity_id,reason='DAMAGE:'+ctx.source+':arriving',critical=natural==20);ctx.engine._record_roll(roll)
            ctx.engine._commit_damage(owner,roll.total,str(weapon.get('damage_type') or 'UNTYPED'),ctx.source,ctx.actor.entity_id,ctx.intent,reaction_depth=0)
    ctx.engine._append_event('REACTION_RESOLVED',DIVIDE,actor_id=owner.entity_id,target_ids=(owner.entity_id,),payload={'same_attack_total':total,'arriving_legal':int(legal),'log':'Exchange Substance resolves the same attack roll against the arriving owner.'})
    return False


def settle_armament(engine,actor,item):
    """Retain one actual carried identity, with native grip/possession updates."""
    from ..carry import clear_owned_item_location
    key=item['item_key'];clear_owned_item_location(engine,actor,key,LIVING)
    engine._apply_condition(actor,'condition:typed.quicksilver_item_location',LIVING,actor.entity_id,
        expires_on='UNTIL_REMOVED',data={'item_key':key,'held_by':actor.entity_id,'owner':actor.entity_id,
        'object_id':item.get('object_id',''),'object_location':'hand:'+item.get('hand','hand:right') if item.get('manifested') else 'merged',
        'label':item['name']+(' manifested' if item.get('manifested') else ' merged into the Quicksilver Body')})
    weapon=item.get('weapon_action')
    if weapon and weapon in engine.action_catalog:
        from .equipment_hands import set_weapon_readiness
        set_weapon_readiness(engine,actor,weapon,bool(item.get('manifested')),source=LIVING,source_actor_id=actor.entity_id,hand=item.get('hand'))


@hook('candidate_allowed')
def merged_item_guard(engine,actor,candidate,action):
    if not owns(engine,actor) or action is None:return None
    item=data(actor).get('armament')
    if not item or item.get('manifested'):return None
    # A merged item cannot be independently targeted, dropped or drawn through
    # another menu. Its owner's once-per-turn manifestation retains that identity.
    grip=action.parameters.get('equipment_grip') or {}
    if grip.get('weapon')==item.get('weapon_action'):return False
    if any(r.get('item')==item.get('item_key') for r in walk_effects((action.parameters.get('typed') or {}).get('effects'))):return False
    return None


@hook('condition_immune')
def poisoned_immunity(engine,actor,name):
    if str(name).lower()=='poisoned' and owns(engine,actor,UNDYING) and transformed(actor):return True
    return None


death_handler(continuity,priority=-200)


@hook('damage_component_type')
def converted_component(engine,actor,target_ids,source,amount,kind,*,ctx=None,spec=None,intent=None,attack_index=0):
    if not owns(engine,actor):return None
    action=engine.action_catalog.get(source)
    if action is None or not qi_action(action):return None
    typed=(spec or {}).get('typed') or action.parameters.get('typed') or {}
    from ..weapon_delivery import delivery_kind
    if delivery_kind(typed,{},action.parameters)=='weapon' and attack_index>1:
        delivery=typed.get('weapon_delivery') or {}
        if not isinstance(delivery,dict) or not delivery.get('multiple_attacks'):return None
    if ctx is None:
        from ..typed_executor import Context
        targets=[engine.state.actors[tid] for tid in target_ids if tid in engine.state.actors]
        ctx=Context(engine,actor,action,intent or getattr(engine,'_active_intent',None),deepcopy(typed),targets,targets[0] if len(targets)==1 else None)
    if not ctx.damage_cache.get('quicksilver_prepared'):prepare_activation(ctx)
    return conversion(ctx,(kind,),[engine.state.actors[t] for t in target_ids if t in engine.state.actors])


@hook('effect_resolution_scope')
def activation_scope(ctx,row):
    if not owns(ctx.engine,ctx.actor) or not qi_action(ctx.action) or ctx.action.parameters.get('quicksilver_command'):return None
    from contextlib import contextmanager
    @contextmanager
    def scope():
        prepare_activation(ctx)
        yield
    return scope()



def recover_qi(session,actor_id,method):
    actor=session.state['actors'][actor_id]
    if not journey_owned(actor):return
    state=source_state(actor);rest=int(actor['long_rests'])
    maximum=next((r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id']==QI),0)
    if method in ('full','short'):
        key=method+'_recovery_rest'
        if state.get(key)==rest:return
        state[key]=rest
    attained=int(next(r['numbers']['cl'] for r in actor['bundle']['typed_passives'] if r.get('block')==BLOCK))
    amount=maximum if method=='full' else maximum//2 if method=='long' else attained
    before=actor['resources'][QI]
    actor['resources'][QI]=min(maximum,before+amount)
    session.emit('RESOURCE_GAINED',actor_id,source='tianxia.path.qi_cultivation',resource_id=QI,
        amount=actor['resources'][QI]-before,remaining=actor['resources'][QI],recovery_method=method)


@hook('journey_rest')
def ordinary_long_rest(session,actor_id):
    if not journey_owned(session.state['actors'][actor_id]):return
    recover_qi(session,actor_id,'long');sync_journey(session,actor_id)


@hook('journey_command')
def short_rest(session,actor_id,kind,payload):
    if kind!='quicksilver_short_rest':return None
    actor=session.state['actors'][actor_id]
    require(journey_owned(actor) and not actor['incapacitated'] and not payload,'Choose a conscious Living Quicksilver cultivator for a one-hour Short Rest.')
    from .rest_procedures import short_rest as native_short_rest
    return native_short_rest(session,actor_id,'short_rest',payload)


@hook('journey_rest_completed')
def short_rest_completed(session,actor_id,kind):
    if kind=='short' and journey_owned(session.state['actors'][actor_id]):
        recover_qi(session,actor_id,'short');sync_journey(session,actor_id)


@hook('escape_save_mode')
@hook('escape_mode')
def liquid_escape(engine,actor,grips):
    if owns(engine,actor) and any(c.condition_id.removeprefix('condition:typed.') in ('grappled','restrained') for c in grips):return 'ADVANTAGE'
    return None


# Classification is supplied by the native world owner and bound to the actual
# source. These records never supply the hostile impact/death/attack trigger.
DECLARATIONS='condition:typed.quicksilver_source_declarations'
PROTECTED_CATEGORIES={'secret','immortal','legendary','artifact','bloodline-exclusive','soul-exclusive','conceptual'}


def validate_classification(record):
    value=record['value']
    if record['kind']=='pattern_authority':
        require(set(value)=={'categories'} and isinstance(value['categories'],list) and all(type(v) is str and v in PROTECTED_CATEGORIES for v in value['categories']) and len(value['categories'])==len(set(value['categories'])),
            'Classify only the actual source’s Secret, Immortal, Legendary, artifact, bloodline-exclusive, soul-exclusive or conceptual pattern authority.')
    else:
        flags={'erases_all_substance','destroys_soul_and_embryo','captures_soul_and_embryo','prevents_reconstruction','defeated_defense','erases_embryo'}
        require(set(value)<=flags|{'cause','superior_authority','target_id'} and type(value.get('target_id')) is str and value['target_id'] and len(value)>1 and all(type(value[k]) is int and value[k] in (0,1) for k in set(value)&flags),
            'Record explicit source-qualified continuity authority using integer flags.')
        require('cause' not in value or value['cause'] in ('decapitation','dismemberment','segment_destruction','complete_destruction','soul_destruction','void_erasure','secret_law_embryo'),
            'Choose the actual anatomical or continuity consequence; damage names do not establish one.')
        require('superior_authority' not in value or value['superior_authority'] in ('void','samsara','conceptual'),
            'A superior continuity authority must be explicitly Void, Samsara or conceptual.')
        require(not value.get('defeated_defense') or value.get('superior_authority'), 'A defeated defense needs the actual superior authority.')


def sync_classifications(session,actor_id):
    from ..fact_consent_admission import KEY
    actor=session.state['actors'][actor_id];records=[]
    keys=list(dict.fromkeys((r['kind'],r['scope']) for r in session.state.get(KEY,()) if r['source']==FAMILY and r['subject']==actor_id and r['kind'] in ('pattern_authority','body_effect')))
    for kind,scope in keys:
        record=read(session,FAMILY,actor_id,kind,scope,actor_id)
        if record:
            validate_classification(record)
            records.append({**record,'remaining_seconds':int(record['expires_at']-session.clock())})
    bundle=actor['bundle']
    if not records and 'living_quicksilver_declarations' not in bundle:return
    bundle['living_quicksilver_declarations']=records
    from ..canonical import canonical_sha256
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


@hook('fact_admitted')
def classification_admitted(session,record):
    if record['source']!=FAMILY or record['kind'] not in ('pattern_authority','body_effect'):return
    validate_classification(record)
    if record['kind']=='body_effect':
        require(record['value']['target_id'] in session.state['actors'],'Bind the continuity declaration to one actual creature in this scene.')
        require(record['scope'].endswith('|'+record['value']['target_id']),'Bind continuity scope as the actual source ID followed by | and the target ID.')
    sync_classifications(session,record['subject'])


@hook('journey_elapsed')
def classification_elapsed(session,actor_id,before,seconds,moving):
    sync_classifications(session,actor_id)


@hook('match_initialize',priority=110)
def initialize_classifications(engine):
    from .effect_durations import round_token
    initialized=False
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for record in bundle.get('living_quicksilver_declarations',()):
            if record['remaining_seconds']<=0:continue
            validate_classification(record)
            engine._apply_condition(actor,DECLARATIONS,FAMILY,actor.entity_id,
                expires_on=round_token(engine,max(1,(record['remaining_seconds']+5)//6)),
                data={'record':canonical(record),'label':'Private source authority declaration'})
            initialized=True
    return True if initialized else None


def source_declaration(engine,source_actor_id,source,kind,target_id=None):
    actor=engine.state.actors.get(source_actor_id)
    if not actor:return {}
    records=[json.loads(c.data['record']) for c in actor.conditions.values() if c.condition_id==DECLARATIONS]
    records=[r for r in records if r['kind']==kind and r['scope']==(source+'|'+str(target_id) if kind=='body_effect' else source) and r['subject']==source_actor_id and 6*(engine.state.round_number-1)<r['remaining_seconds'] and (kind!='body_effect' or r['value']['target_id']==target_id)]
    return deepcopy(max(records,key=lambda r:r['sequence'])['value']) if records else {}


@hook('presentation_hidden_conditions')
def hide_source_classifications(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id==DECLARATIONS]


SEA_GUARD='condition:typed.quicksilver_sea_guard'


def sea_origins(engine,actor):
    # Weapon-Sea manifests each Body and the actual Domain Armament. It does
    # not silently manufacture a second origin from the owner's bare self.
    return [r for r in origin_records(engine,actor) if r['id']!='quicksilver:self']


SEA_MODIFIER='passive:'+UNDYING+'.guard'


@hook('event',nested=True)
def sea_guard_boundary(engine,event_type,kwargs):
    if event_type not in ('MOVEMENT_COMMITTED','OBJECT_UPDATED','CONDITION_APPLIED','CONDITION_REMOVED','MODIFIER_APPLIED','MODIFIER_REMOVED'):return
    if engine.__dict__.get('_quicksilver_guard_reconciling'):return
    from .qi_path import GUARD
    engine._quicksilver_guard_reconciling=True
    try:
        for target in list(engine.state.actors.values()):
            helds=[c for c in target.conditions.values() if c.condition_id==SEA_GUARD]
            modifiers=[m for m in target.modifiers.values() if m.source_definition_id==SEA_MODIFIER]
            if not helds and not modifiers:continue
            valid=[]
            for held in helds:
                owner=engine.state.actors.get(held.source_actor_id)
                origins=sea_origins(engine,owner) if owner and transformed(owner) else []
                if any(r['id'] in held.data['origins'] and engine.grid.distance_ft(target.position,Position(**r['position']))<=5 for r in origins):valid.append(held)
                else:engine._remove_condition_instance(target,held.instance_id,UNDYING)
            # The named Guard Mode benefit is +2, even if two origins or two
            # cultivators protect the same recipient. Keep all valid sources so
            # one source ending cannot silently erase another's protection.
            external=any(m.source_definition_id==GUARD and m.target_field=='armor_class_vs_ranged' and m.operation=='ADD' and int(m.value)>=2 for m in target.modifiers.values())
            source=min(valid,key=lambda c:c.applied_sequence).source_actor_id if valid and not external else None
            keeper=None
            for modifier in modifiers:
                if source and modifier.source_actor_id==source and keeper is None:keeper=modifier
                else:engine._remove_modifier_instance(target,modifier.modifier_id,UNDYING)
            if source and keeper is None:
                engine._add_modifier(target,SEA_MODIFIER,'armor_class_vs_ranged','ADD',2,'SELF',expires_on='START_OF_SOURCE_NEXT_TURN',source_actor_id=source)
    finally:engine._quicksilver_guard_reconciling=False



def armament_available(engine,actor):
    item=data(actor).get('armament')
    if not item or not owns(engine,actor):return False
    from .scoundrel_riders import possessions,held_possessions,object_id
    identity=item.get('object_id') or object_id(actor.entity_id,item['item_key'])
    if item.get('manifested'):
        return any(row['object']==identity for row in held_possessions(engine,actor))
    if not any(row['object']==identity and row.get('location')=='merged' for row in possessions(engine,actor)):return False
    from .hand_occupancy import free_hands,holding_hands
    return len(free_hands(engine,actor))>=holding_hands(engine,item.get('weapon_action') or '')


@hook('possession_operation_allowed')
def merged_possession_operation(engine,actor,holder,item,operation,source):
    if not owns(engine,holder):return None
    selected=data(holder).get('armament')
    if not selected or selected.get('manifested'):return None
    from .scoundrel_riders import object_id
    actual=item.get('object') or item.get('object_id') or object_id(holder.entity_id,item.get('key',''))
    expected=selected.get('object_id') or object_id(holder.entity_id,selected['item_key'])
    return False if actual==expected else None



def former_armament_location(encoded,actor_id,key):
    row=json.loads(encoded);info=row.get('data') or {}
    return row.get('condition_id')=='condition:typed.quicksilver_item_location' and info.get('item_key')==key and info.get('held_by')==actor_id


def journey_item_lost(session,actor_id,item):
    from .scoundrel_riders import object_id
    expected=object_id(actor_id,item['key'])
    for filed,creature in session.state['actors'].items():
        for encoded in creature.get('encounter_snapshot',{}).get('conditions',{}).values():
            row=json.loads(encoded);info=row.get('data') or {}
            actual=info.get('object_id') or object_id(info.get('owner') or filed,info.get('item_key',''))
            if actual==expected and (info.get('dropped_at') or info.get('held_by') not in (None,actor_id)):return True
            if filed==actor_id and item.get('weapon_action') and info.get('disables_action')==item['weapon_action'] and not info.get('object_location'):return True
    return False
