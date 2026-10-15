"""Lantern Keeper's five source rows (Qi R19, Shared Qi R4).

Acquisition and elapsed-time state use the public journey source contracts.
Assets, observers, consent, choices, movement, rolls and life state use their
native public interfaces. No feature ID is interpreted in engine/core.
"""
from copy import deepcopy
import json
from dataclasses import replace
from contextvars import ContextVar
_REVEALING=ContextVar("lantern_revelation_frames",default=frozenset())
from . import hook, effect, placed

PARENT='tianxia.subpath.qi.lantern_keeper'
P=PARENT+'.feature.'
LIGHT,ROAD,PASSAGE,HOLD,TEN=[P+s for s in ('light_the_way','lantern_road','lantern_passage','hold_the_departing_soul','ten_thousand_lantern_road')]
LEVELS=dict(zip((LIGHT,ROAD,PASSAGE,HOLD,TEN),(3,6,10,14,18)))
QI='resource:core.qi'
TAG='guiding_lantern'
FIELD='ten_thousand_lantern_road'
C='condition:typed.lantern_keeper.'
COMMANDS={'create':(LIGHT,'Create Guiding Lantern','ACTION'), 'move':(LIGHT,'Move Guiding Lantern','NONE'),
          'passage':(PASSAGE,'Lantern Passage','BONUS_ACTION'), 'armament':(PASSAGE,'Bind Lantern Domain Armament','NONE'),
          'field':(TEN,'Ten Thousand Lantern Road','ACTION'), 'guide':(TEN,'Guide the Traveler','NONE')}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'))


def state(session,aid):
    return session.state['actors'][aid].setdefault('source_states',{}).setdefault(PARENT,{})


def level(sheet):
    return next((int(row[k]) for row in (sheet.get('path_and_subpath') or {}).get('paths',[]) if row.get('path_id')=='tianxia.path.qi_cultivation'
                 for k in ('attainment','owning_path_level','effective_cl') if type(row.get(k)) is int),0)


@hook('journey_acquisition')
def acquire(session,aid,source,payload,sheet):
    if source!=PARENT:return None
    from ..journey import require
    require(payload=={},'Lantern Keeper is an Open School first Qi Subpath choice; it takes no earned-ID payload.')
    actor=session.state['actors'][aid];paths=deepcopy(sheet.get('path_and_subpath') or {})
    require(not actor['incapacitated'],'An incapacitated creature cannot select a Subpath.')
    require('tianxia.path.qi_cultivation' in set(paths.get('path_record_ids') or [])|{paths.get('path_record_id')},'Acquire the Qi Cultivation Path first.')
    attained=level(sheet)
    require(3<=attained<=int(sheet['identity']['cultivation_level']),'Qi Path attainment must be at least 3 and cannot exceed overall CL.')
    choices=set(paths.get('subpath_record_ids') or [])|{paths.get('subpath_record_id')}
    choices.discard(None)
    ids=set(paths.get('path_feature_record_ids') or [])|set(paths.get('source_granted_subpath_feature_record_ids') or [])
    require(not choices and not any(s.startswith('tianxia.subpath.qi.') for s in ids),'The Qi Subpath slot is already occupied; selecting Lantern Keeper cannot retain another progression.')
    earned=[f for f,cl in LEVELS.items() if cl<=attained]
    paths.update(subpath_record_id=PARENT,subpath_record_ids=[PARENT],
        subpath_acquisition={'source_rule':PARENT,'route':'open_school_first_choice','path_level':attained,'earned_features':earned},
        path_feature_record_ids=list(dict.fromkeys([*paths.get('path_feature_record_ids',[]),*earned])),
        source_granted_subpath_feature_record_ids=earned)
    paths['bindings']=[*paths.get('bindings',[]),{'path_id':'tianxia.path.qi_cultivation','subpath_id':PARENT}]
    sheet['path_and_subpath']=paths
    ledger=state(session,aid);ledger['acquired_paths']=canonical(paths)
    receipt=session.emit('LANTERN_KEEPER_ACQUIRED',aid,source=PARENT,earned_features=earned,path_attainment=attained)
    return {'sheet':sheet,'acquisition_id':f'{PARENT}:{len(session.state["events"])}'}


@hook('journey_source_sheet')
def acquired_overlay(sheet,session,aid):
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT,{})
    if not ledger.get('acquired_paths'):return None
    paths=deepcopy(sheet.get('path_and_subpath') or {});saved=json.loads(ledger['acquired_paths'])
    chosen=set(paths.get('subpath_record_ids') or [])|{paths.get('subpath_record_id')};chosen.discard(None)
    if chosen-{PARENT}:raise ValueError('The installed Qi Subpath conflicts with the committed Lantern Keeper selection.')
    attained=level(sheet)
    earned=[f for f,cl in LEVELS.items() if cl<=attained]
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        paths[key]=list(dict.fromkeys([*paths.get(key,[]),*saved.get(key,[]),*earned]))
    for key in ('subpath_record_id','subpath_record_ids','subpath_acquisition','bindings'):paths[key]=deepcopy(saved[key])
    return {**sheet,'path_and_subpath':paths}


@hook('compile_passives')
def ownership(rows,info):
    # Replace parser approximations for this family, retaining every other row.
    out=[r for r in rows if not str(r.get('feature_id','')).startswith(P)]
    paths=info['owner_sheet'].get('path_and_subpath') or {}
    cap=min(int(info['numbers'].get('cl') or 1),level(info['owner_sheet']) or int(info['numbers'].get('cl') or 1))
    return [*out,*[{'block':'lantern_keeper','feature_id':f,'numbers':dict(info['numbers'])} for f,cl in LEVELS.items() if f in info['owned_ids'] and cap>=cl]]


def action(info,command,old=None):
    from ..gate2_runtime_models import ActionDefinition
    feature,name,economy=COMMANDS[command]
    text={'create':'Spend 1 Qi to create or empower one Guiding Lantern within 30 feet for 8 hours.',
          'move':'Once during this turn, move one Guiding Lantern up to 20 feet; keep it within 120 feet of you or another Lantern.',
          'passage':'Spend 3 Qi (1 in your field) to teleport between legal Lantern endpoints; optionally carry one willing traveler for 2 additional Qi (1 in your field).',
          'armament':'Bind one Lantern to your manifested Domain Armament, at no additional Qi cost. It keeps its defenses, uses the faster movement, can attack in Assault Mode or protect in Guard Mode, and can launch your techniques from its space with their normal costs and limits. Destroying it ends both manifestations.',
          'field':'Spend 8 Qi once per scene: guiding lights fill a 60-foot-radius, 60-foot-high cylinder within 120 feet for 1 minute, with Concentration.',
          'guide':'Once during your turn, move one willing ally inside your field up to 30 feet without provoking; spend 1 Qi to teleport instead.'}[command]
    return ActionDefinition(source_definition_id=old.source_definition_id if old else f'action:typed.{info["short"]}.lantern.{command}',
        display_name=name,owner_id=old.owner_id if old else info['actor_id'],economy=economy,resolution_kind='TYPED',target_kind='SELF',costs=((QI,{'create':1,'passage':3,'field':8}[command]),) if command in ('create','passage','field') else (),
        parameters={'description':text,'typed':{'source':feature,'manual_inline_choice':True,'numbers':dict(info['numbers']),
            'duration':{'kind':'instant'},'riders':[],'effects':[{'type':'lantern_keeper','command':command}]}})


@hook('compile_action')
def replace_action(old,info):
    typed=old.parameters.get('typed') or {}
    if any(r.get('type')=='lantern_keeper' for r in typed.get('effects',[])):return None
    feature=typed.get('source')
    command={LIGHT:'create',PASSAGE:'passage',TEN:'field'}.get(feature)
    if command:return action(info,command,old)
    # No active parser approximations exist for Road/Hold; they are native hooks.
    return None


@hook('compile_actions')
def actions(info):
    cap=min(int(info['numbers'].get('cl') or 1),level(info['owner_sheet']) or int(info['numbers'].get('cl') or 1))
    have={(a.parameters.get('typed') or {}).get('source') for a in info['actions']}
    return [action(info,cmd) for cmd,(f,name,economy) in COMMANDS.items() if f in info['owned_ids'] and cap>=LEVELS[f]
            and (cmd not in ('create','passage','field') or f not in have)] or None


def owned(engine,actor,feature):
    return any(r.get('block')=='lantern_keeper' and r.get('feature_id')==feature for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,[]))


def numbers(engine,actor):
    return next((r['numbers'] for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,[]) if r.get('block')=='lantern_keeper'),{})


def held(actor,tag):
    return [c for c in actor.conditions.values() if c.condition_id==C+tag]


def put(ctx,subject,tag,data,expires='UNTIL_REMOVED'):
    return ctx.engine._apply_condition(subject,C+tag,ctx.source,ctx.actor.entity_id,expires_on=expires,data=data)


def remove(engine,actor,c):
    from .condition_ownership import remove_instance
    remove_instance(engine,actor,c.instance_id,c.source_definition_id)


def pick(ctx,key,options,labels=None,*,subject=None,optional=False,maximum=1,minimum=1,automatic_options=None):
    from .rider_choices import pick as choose
    return choose(ctx.engine,ctx.actor if subject is None else subject,'lantern_'+key,ctx.action.display_name,options,
        subject=subject or ctx.actor,labels=labels or {s:s.replace('_',' ').title() for s in options},intent=ctx.intent,
        optional=optional,maximum=maximum,minimum=minimum,preferred=options[:maximum],automatic_options=automatic_options,
        prompt=f'{ctx.action.display_name}: choose {key.replace("_"," ")}. '+str(ctx.action.parameters.get('description') or ''))


def context(engine,owner,feature):
    from ..typed_executor import Context
    from ..gate2_runtime_models import ActionDefinition
    name={LIGHT:'Light the Way',ROAD:'Returning Flame',PASSAGE:'Lantern Passage',HOLD:'Hold the Departing Soul',TEN:'Ten Thousand Lantern Road'}[feature]
    action_row=ActionDefinition(source_definition_id=feature,display_name=name,owner_id=owner.entity_id,
        economy='NONE',resolution_kind='TYPED',target_kind='SELF',parameters={'description':name})
    return Context(engine,owner,action_row,getattr(engine,'_active_intent',None),
        {'source':feature,'numbers':numbers(engine,owner),'duration':{'kind':'instant'},'effects':[],'riders':[]},[owner],owner,{})


def ally(engine,owner,target):
    from ..relations import relation,ALLY
    return relation(engine,owner,target)==ALLY


def live(engine,owner=None):
    from ..asset_anchor_runtime import members
    return [o for o in members(engine,owner_id=owner.entity_id if owner else None,group=TAG) if not (o.component or {}).get('suppressed') and not suppressed(engine,o)
            and engine.state.round_number<int(o.component.get('expires_round',engine.state.round_number+1))]


def fields(engine,actor=None):
    from ..concentration import concentrating_on
    return [z for z in placed.of(engine,FIELD) if engine.state.round_number<z.created_round+(z.duration_rounds or 10)
            and (owner:=engine.state.actors.get(z.owner_id)) is not None and concentrating_on(owner,z.source_definition_id)
            and (actor is None or inside(engine,actor.position,z))]


def inside(engine,point,zone):
    return 0<=(point.z-zone.center.z)*5<=60 and engine.grid.distance_ft(point.model_copy(update={'z':zone.center.z}),zone.center)<=60


def field_for(engine,owner,actor=None):
    return next((z for z in fields(engine,actor) if z.owner_id==owner.entity_id),None)


def near(engine,target,owner,feet):
    return [o for o in live(engine,owner) if engine.grid.distance_ft(target.position,o.position)<=feet]


def stamp(engine):
    return f'{engine.state.round_number}:{engine.state.current_slot_index}:{engine.state.current_actor_id}'


def used(engine,actor,tag):
    return any(c.data.get('turn')==stamp(engine) for c in held(actor,tag))


def spend(ctx,amount):
    if ctx.actor.resources.get(QI,0)<amount:raise ValueError(f'{ctx.action.display_name} requires {amount} Qi.')
    ctx.engine._spend_resource(ctx.actor,QI,amount,ctx.source)


def points(engine,origin,feet):
    from ..gate2_runtime_models import Position
    r=feet//5
    return [p for z in range(max(0,origin.z-r),origin.z+r+1)
        for y in range(max(0,origin.y-r),min(engine.grid.height,origin.y+r+1))
        for x in range(max(0,origin.x-r),min(engine.grid.width,origin.x+r+1))
        if engine.grid.distance_ft(origin,p:=Position(x=x,y=y,z=z))<=feet and engine.grid.volume_legal(p)]


def choose_point(ctx,key,cells,*,subject=None,optional=False):
    from .needle import cell_options,position_of
    options,labels=cell_options(ctx.engine,subject or ctx.actor,{p:ctx.engine.grid.distance_ft((subject or ctx.actor).position,p) for p in cells},cap=len(cells))
    if not options:return None
    from ..target_knowledge import can_see
    known=[o for o in options if ctx.engine._line_of_sight_actor_to_cell(ctx.actor,position_of(o))]
    chosen=pick(ctx,key,options,labels,subject=subject,optional=optional,automatic_options=known)
    return position_of(chosen[0]) if chosen else None


def create(ctx):
    from ..asset_anchor_runtime import create as asset_create,members
    from ..gate2_runtime_models import Position
    e,a=ctx.engine,ctx.actor
    real=[o for o in e.state.objects.values() if not o.destroyed and e.grid.distance_ft(a.position,o.position)<=30
          and not (o.component or {}).get('asset_anchor_runtime') and not (o.component or {}).get('artifact')]
    from .scoundrel_riders import possessions
    carried=[i for i in possessions(e,a) if not any(i.get(flag) for flag in ('artifact','protected','sealed','fused'))
        and not any((o.component or {}).get('item_identity')==i['object'] and not o.destroyed for o in e.state.objects.values())]
    mode=pick(ctx,'lantern_form',['projected']+(['real'] if real else [])+(['carried'] if carried else []),
        {'projected':'Create a projected Qi Lantern','real':'Empower an existing light-bearing map item; no duplicate',
         'carried':'Empower one actual carried light-bearing item; keep the same item and custody'})[0]
    old=None
    inventory=None
    if mode=='carried':
        from ..gate2_runtime_models import RuntimeObjectState
        key=pick(ctx,'carried_light_bearing_item',[i['object'] for i in carried],{i['object']:i.get('name','Carried item') for i in carried})[0]
        inventory=next(i for i in carried if i['object']==key)
        from ..fact_consent_admission import admit_choice
        admitted=admit_choice(ctx,a,ctx.source,'light_bearing_item',key,['confirm'],
            labels={'confirm':'This actual carried item is a lantern, lamp, candle, torch, brazier or similar light-bearing item'},
            prompt='Create Guiding Lantern: confirm this actual carried item is eligible. It remains the same item.',expires_on='UNTIL_REMOVED')
        if not admitted:raise ValueError('The actual carried item requires an explicit eligibility declaration.')
        old=RuntimeObjectState(object_id=key,object_kind='item',owner_id=a.entity_id,position=a.position,unattended=False,
            flammable=True,ac=None,current_hp=None,maximum_hp=None,component={'name':inventory.get('name','Real item')})
        point=a.position
    elif mode=='real':
        oid=pick(ctx,'real_item',[o.object_id for o in real],{o.object_id:(o.component or {}).get('name','Existing item') for o in real})[0]
        old=e.state.objects[oid]
        from ..fact_consent_admission import admit_choice
        admitted=admit_choice(ctx,a,ctx.source,'light_bearing_item',oid,['confirm'],labels={'confirm':'This actual item is a lantern, lamp, candle, torch, brazier or similar light-bearing item'},
            prompt='Create Guiding Lantern: confirm the real item is eligible. It remains this same item.',expires_on='UNTIL_REMOVED',readers=(),automatic_options=[])
        if not admitted:raise ValueError('The chosen actual item needs an explicit eligibility declaration.')
        point=old.position
    else:
        point=choose_point(ctx,'lantern_location',points(e,a.position,30))
        if point is None:raise ValueError('No Lantern location was chosen.')
    profile={'name':'Guiding Lantern','kind':'guiding_lantern','group':TAG,'ac':13+int(ctx.numbers['pb']),
             'hp':2*int(ctx.numbers['cl']),'source_cl':int(ctx.numbers['cl']),'height_ft':1,'immune':['FIRE','POISON','PSYCHIC'],
             'occupies_space':False,'requires_support':False}
    component={'size':'tiny','blocks':False,'cover':False,'creature':False,'speed_ft':20,'hover':True,'bright_ft':10,'dim_ft':10,
               'condition_immunities':['charmed','frightened','poisoned','prone'],'save_modifier':int(ctx.numbers['pb'])+int(ctx.numbers.get('key_mod') or 0),
               'initiative':'creator','actions':[],'reactions':[],'tether_ft':120,'expires_round':e.state.round_number+4800,
               'plane':(old.component or {}).get('plane','material') if old else 'material','real_item':int(old is not None),**({'item_identity':inventory['object'],'inventory_owner':inventory['object'].split('|',1)[0],
               'item_key':inventory['key'],'carried_by':a.entity_id} if inventory else {})}
    if old:
        from ..asset_anchor_runtime import KEY
        component={**(old.component or {}),**component,'original':old.model_dump(mode='json'),'name':'Guiding Lantern',
            'source_cl':int(ctx.numbers['cl']),'created_by':ctx.source,KEY:{'owner':a.entity_id,'source':ctx.source,'group':TAG,'sequence':e.state.event_sequence+1,'lifetime':'8 hours'}}
        obj=old.model_copy(update={'owner_id':a.entity_id,'object_kind':'guiding_lantern','ac':profile['ac'],'current_hp':profile['hp'],
            'maximum_hp':profile['hp'],'damage_immunities':tuple(dict.fromkeys([*old.damage_immunities,*profile['immune']])),'component':component})
        e._update_object(obj,ctx.source,a.entity_id)
    else:obj=asset_create(e,a,ctx.source,profile,point,component=component,lifetime='8 hours')
    all_lanterns=members(e,owner_id=a.entity_id,group=TAG)
    for oldest in sorted(all_lanterns,key=lambda o:o.component['asset_anchor_runtime']['sequence'])[:-int(ctx.numbers['pb'])]:retire(e,oldest,ctx.source)


def retire(engine,obj,source):
    original=(obj.component or {}).get('original')
    if original and not obj.destroyed:
        from ..gate2_runtime_models import RuntimeObjectState
        restored=RuntimeObjectState.model_validate(original).model_copy(update={'position':obj.position})
        if obj.component.get('item_identity'):
            restored=restored.model_copy(update={'destroyed':bool(obj.component.get('carried_by')),
                'current_hp':0 if obj.component.get('carried_by') else restored.current_hp,'unattended':not bool(obj.component.get('carried_by'))})
        engine._update_object(restored,source,obj.owner_id)
    else:
        from ..asset_anchor_runtime import retire as end
        end(engine,obj,source)


def move_lantern(ctx,optional=False):
    e,a=ctx.engine,ctx.actor
    if used(e,a,'move_used') or not live(e,a):return
    options=live(e,a)
    selected=pick(ctx,'moving_lantern',[o.object_id for o in options],{o.object_id:f'Guiding Lantern at ({o.position.x}, {o.position.y}), {o.position.z*5} feet high' for o in options},optional=optional)
    if not selected:return
    obj=e.state.objects[selected[0]]
    from .qi_path import armament_condition
    arm=armament_condition(a)
    linked=any(act.owner_id==a.entity_id and act.parameters.get('armament_control_ft')==60 for act in e.action_catalog.values())
    speed=30 if arm and linked and (obj.component or {}).get('domain_armament') else 20
    routes=asset_routes(e,obj.position,speed)
    cells=[p for p in routes if any(e.grid.distance_ft(p,q)<=120 for q in [a.position,*[o.position for o in live(e,a) if o.object_id!=obj.object_id]])
]
    point=choose_point(ctx,'lantern_move_destination',cells,optional=True)
    if point is None or point==obj.position:return
    if obj.component.get('item_identity'):
        from .scoundrel_riders import possessions,relocate_possession,relocate_ground_possession
        from ..gate2_runtime_models import Position
        original=e.state.actors[obj.component['inventory_owner']]
        carrier=e.state.actors.get(obj.component.get('carried_by'))
        found=next((i for i in possessions(e,carrier) if i['object']==obj.component['item_identity']),None) if carrier else None
        path=asset_path(e,obj.position,point,speed)
        if not path:raise ValueError('This real Lantern has no legal physical route.')
        if found:
            if not relocate_possession(ctx,carrier,found,path,ignore_actor_space=True):raise ValueError('The actual carried item cannot be released along that route.')
        elif not relocate_ground_possession(ctx,original,obj.component['item_key'],path):raise ValueError('The real item is no longer at this Lantern position.')
        obj=obj.model_copy(update={'component':{**obj.component,'carried_by':''}})
    e._update_object(obj.model_copy(update={'position':point}),ctx.source,a.entity_id)
    put(ctx,a,'move_used',{'turn':stamp(e),'label':'Moved one Lantern this turn'})
    if (obj.component or {}).get('domain_armament') and arm:
        from .qi_path import move_armament
        move_armament(e,a,point,ctx.source,distance_ft=speed,max_distance_ft=120)


def landing(e,actor,point):
    return e.grid.placement_legal(point,footprint=e._footprint(actor),occupied_cells=e._occupied_cells_except(actor.entity_id))


def route_allowed(ctx,subject,start,end,teleport=True):
    from . import any_false
    from ..typed_executor import condition_rules
    if not landing(ctx.engine,subject,end):return False
    if any(r.get('no_teleport') for r in condition_rules(subject)) and teleport:return False
    if teleport and any(c.condition_id=='condition:typed.deny_teleport' for c in subject.conditions.values()):return False
    # Resolution gates can roll or ask. Never invoke them from a menu query.
    if blocked_endpoint(ctx.engine,start) or blocked_endpoint(ctx.engine,end):return False
    return True


def passage_options(ctx):
    e,a=ctx.engine,ctx.actor;out=[]
    for first in near(e,a,a,5):
        for second in live(e,a):
            if first is second or e.grid.distance_ft(first.position,second.position)>120 or first.component.get('plane')!=second.component.get('plane'):continue
            if blocked_endpoint(e,first.position) or blocked_endpoint(e,second.position):continue
            for p in points(e,second.position,5):
                if route_allowed(ctx,a,a.position,p):out.append((first,second,p))
    return out


def willing(ctx,subject,kind):
    from ..fact_consent_admission import admit_choice
    from ..target_knowledge import located
    return admit_choice(ctx,subject,ctx.source,kind,ctx.intent.intent_id,['willing'],labels={'willing':f'{subject.display_name} willingly travels with {ctx.actor.display_name}'},
        prompt=f'{ctx.action.display_name}: {subject.display_name}, allow this travel? Refusing spends no additional Qi.',expires_on='END_OF_CURRENT_TURN',readers=[ctx.actor.entity_id],
        automatic_options=['willing'] if located(ctx.engine,subject,ctx.actor) else []) is not None


def passage(ctx):
    e,a=ctx.engine,ctx.actor
    options=passage_options(ctx)
    if not options:raise ValueError('Lantern Passage has no legal connected arrival; no Qi is spent.')
    keys={str(i):row for i,row in enumerate(options)}
    labels={k:f'From Lantern ({f.position.x}, {f.position.y}) to Lantern ({s.position.x}, {s.position.y}); arrive ({p.x}, {p.y}), {p.z*5} feet high' for k,(f,s,p) in keys.items()}
    selected=pick(ctx,'passage_endpoints_and_arrival',list(keys),labels)[0];first,second,point=keys[selected]
    cost=1 if field_for(e,a) else 3
    companion=None;arrival=None
    from ..target_knowledge import located
    candidates=[t for t in e.state.actors.values() if t is not a and t.active and e.grid.distance_ft(a.position,t.position)<=5]
    if candidates and a.resources.get(QI,0)>=(1 if cost==1 else 2):
        chosen=pick(ctx,'carry_traveler',[t.entity_id for t in candidates],{t.entity_id:f'Carry {t.display_name} for {1 if cost==1 else 2} additional Qi' for t in candidates},optional=True,automatic_options=[t.entity_id for t in candidates if located(e,a,t)])
        if chosen:
            t=e.state.actors[chosen[0]]
            cells=[p for p in points(e,point,5) if p!=point and route_allowed(ctx,t,t.position,p)]
            if cells and willing(ctx,t,'carry_traveler'):
                arrival=choose_point(ctx,'traveler_adjacent_arrival',cells)
                if arrival is not None:companion=t
    # Every endpoint, passenger and legal arrival is declared before spending or moving.
    if not route_allowed(ctx,a,a.position,point):raise ValueError('The destination became illegal before activation.')
    if companion:spend(ctx,1 if cost==1 else 2)
    if not activation_live(ctx):return
    put(ctx,a,'passage_used',{'turn':stamp(e),'label':'Lantern Passage used this turn'})
    from ..typed_executor import teleport_subject
    teleport_subject(ctx,a,point,forced=False)
    if companion and a.position==point:
        ends=[e.state.objects.get(first.object_id),e.state.objects.get(second.object_id)]
        if all(o is not None and not o.destroyed and not o.component.get('suppressed') for o in ends):
            teleport_subject(ctx,companion,arrival,forced=False)
        else:
            placed.note(e,ctx.source,a,f'Lantern Passage was interrupted before {companion.display_name} departed; the traveler remains at the origin.')


@effect('lantern_keeper',harmful=False)
def activate(ctx,row):
    cmd=row['command'];f=COMMANDS[cmd][0]
    if not owned(ctx.engine,ctx.actor,f):raise ValueError('This creature has not acquired that Lantern Keeper feature.')
    if not activation_live(ctx):return
    {'create':create,'move':move_lantern,'passage':passage,'armament':bind_armament,'field':activate_field,'guide':guide}[cmd](ctx)


@hook('candidate_allowed')
def admission(engine,actor,candidate,action_row):
    typed=(getattr(action_row,'parameters',{}) or {}).get('typed') or {}
    row=next((r for r in typed.get('effects',[]) if r.get('type')=='lantern_keeper'),None)
    if not row:return None
    cmd=row['command']
    if not owned(engine,actor,COMMANDS[cmd][0]):return False
    if cmd in ('move','passage','guide') and used(engine,actor,cmd+'_used'):return False
    if cmd=='create':return actor.resources.get(QI,0)>=1
    if cmd=='move':return bool(live(engine,actor))
    if cmd=='armament':
        from .qi_path import armament_condition
        return bool(live(engine,actor) and armament_condition(actor,include_suppressed=True))
    if cmd=='field':return actor.resources.get(QI,0)>=8 and not held(actor,'field_used')
    if cmd=='guide':return field_for(engine,actor) is not None
    if cmd=='passage':return actor.resources.get(QI,0)>=(1 if field_for(engine,actor) else 3) and bool(passage_options(context(engine,actor,PASSAGE)))
    return None


def bind_armament(ctx):
    from .qi_path import armament_condition,move_armament
    arm=armament_condition(ctx.actor,include_suppressed=True)
    if arm is None:raise ValueError('Manifest your acquired Domain Armament before binding a Lantern to it.')
    lamps=live(ctx.engine,ctx.actor)
    selected=pick(ctx,'domain_armament_lantern',[o.object_id for o in lamps],{o.object_id:f'Lantern at ({o.position.x}, {o.position.y})' for o in lamps})[0]
    for obj in lamps:
        ctx.engine._update_object(obj.model_copy(update={'component':{**obj.component,'domain_armament':int(obj.object_id==selected)}}),ctx.source,ctx.actor.entity_id)
    obj=ctx.engine.state.objects[selected]
    if not move_armament(ctx.engine,ctx.actor,obj.position,ctx.source,distance_ft=9999,max_distance_ft=9999,
            allow_occupied=True,control_range_ft=120,asset_id=obj.object_id):raise ValueError('The Lantern cannot bind at this point.')


@hook('effect_origins')
def remote_origin(engine,actor,action_row):
    if not owned(engine,actor,PASSAGE):return None
    typed=action_row.parameters.get('typed') or {}
    if (not str(typed.get('sphere') or '').startswith('tianxia.sphere.') and action_row.parameters.get('armament')!='attack') or typed.get('weapon'):return None
    return [{'id':o.object_id,'label':'Guiding Lantern Domain Armament','position':o.position.model_dump(mode='json')}
            for o in live(engine,actor) if o.component.get('domain_armament')]


def activate_field(ctx):
    e,a=ctx.engine,ctx.actor
    if held(a,'field_used'):raise ValueError('Ten Thousand Lantern Road is already spent this scene.')
    center=choose_point(ctx,'field_center',points(e,a.position,120))
    if center is None:raise ValueError('Choose the field center before activating.')
    eligible=[t for t in e.state.actors.values() if t.active and ally(e,a,t)]
    from ..target_knowledge import located
    chosen=pick(ctx,'protected_allies',[t.entity_id for t in eligible],{t.entity_id:t.display_name for t in eligible},minimum=0,maximum=len(eligible),optional=True,
        automatic_options=[t.entity_id for t in eligible if t is a or located(e,a,t)])
    for z in placed.of(e,FIELD,owner_id=a.entity_id):placed.drop(e,z,'REPLACED')
    zone=placed.place(e,a,source=ctx.source,tag=FIELD,cells=[center],name='Ten Thousand Lantern Road',
        placed={'chosen':chosen,'saved':[]},numbers=ctx.numbers,duration_rounds=10,concentration=True,
        radial_volume=True,shape='cylinder',size_ft=60,extra={'height_ft':60})
    e._start_concentration(a,ctx.source)
    put(ctx,a,'field_used',{'label':'Ten Thousand Lantern Road: used once this scene'})


def no_barrier(e,path):
    from ..gate2_runtime_models import Position
    cells=[p if isinstance(p,Position) else Position.model_validate(p) for p in path]
    return not any(blocked_endpoint(e,p) for p in cells) and all(e.grid.line_of_physical_transmission(p,q) for p,q in zip(cells,cells[1:])) and not any(
        z.active and (z.trigger_profile.get('spatial_lock') or z.trigger_profile.get('sealed_formation'))
        and any((p.x,p.y,p.z) in {(c.x,c.y,c.z) for c in z.affected_cells} for p in cells) for z in e.state.zones.values())


def move_ally(ctx,subject,feet,key,*,toward=None):
    from .granted_movement import choices
    e=ctx.engine
    paths=[c for c in choices(e,subject,feet) if no_barrier(e,c.canonical_path or [subject.position,c.destination])
           and (toward is None or e.grid.distance_ft(c.destination,toward)<e.grid.distance_ft(subject.position,toward))]
    if not paths:return False
    from .needle import cell_id
    opts={cell_id(c.destination):c for c in paths}
    labels={k:f'{subject.display_name}: move to ({c.destination.x}, {c.destination.y}), {c.destination.z*5} feet high; no Opportunity Attacks' for k,c in opts.items()}
    chosen=pick(ctx,key,list(opts),labels,subject=subject,optional=True)
    if not chosen:return False
    selected=opts[chosen[0]]
    e.grant_movement(subject,tuple(selected.canonical_path),ctx.source,feet=feet,intent=ctx.intent,provokes=False,
        mode=(selected.metadata or {}).get('movement_mode','walk'))
    return True


def guide(ctx):
    e,a=ctx.engine,ctx.actor;zone=field_for(e,a)
    if zone is None or e.state.current_actor_id!=a.entity_id or used(e,a,'guide_used'):return
    targets=[t for t in e.state.actors.values() if t.active and ally(e,a,t) and inside(e,t.position,zone)]
    if not targets:return
    from ..target_knowledge import located
    chosen=pick(ctx,'guided_ally',[t.entity_id for t in targets],{t.entity_id:t.display_name for t in targets},automatic_options=[t.entity_id for t in targets if t is a or located(e,a,t)])
    if not chosen:return
    target=e.state.actors[chosen[0]]
    if not willing(ctx,target,'guide_traveler'):return
    mode=pick(ctx,'travel_method',['walk']+(['teleport'] if a.resources.get(QI,0) else []),
        {'walk':'Move up to 30 feet without provoking','teleport':'Spend 1 Qi to teleport up to 30 feet without provoking'})[0]
    if mode=='walk':done=move_ally(ctx,target,30,'guide_destination')
    else:
        cells=[p for p in points(e,target.position,30) if route_allowed(ctx,target,target.position,p) and no_barrier(e,[target.position,p])]
        point=choose_point(ctx,'guided_teleport_destination',cells)
        done=point is not None and point!=target.position
        if done:
            spend(ctx,1)
            if not activation_live(ctx):return
            from ..typed_executor import teleport_subject
            teleport_subject(ctx,target,point,forced=False)
    if done:put(ctx,a,'guide_used',{'turn':stamp(e),'label':'Guide the Traveler used this turn'})


def connected(e,owner,first,second):
    if first.object_id==second.object_id or first.component.get('plane')!=second.component.get('plane'):return False
    field=field_for(e,owner)
    return e.grid.distance_ft(first.position,second.position)<=60 or bool(field and inside(e,first.position,field) and inside(e,second.position,field))


@hook('turn_start_choice')
def roads_at_start(engine,actor):
    for owner in engine.state.actors.values():
        if not owned(engine,owner,ROAD) or not ally(engine,owner,actor) or not actor.active:continue
        ctx=context(engine,owner,ROAD)
        zone=field_for(engine,owner,actor)
        if zone:move_ally(ctx,actor,15,'field_start_step')
        lamps=live(engine,owner)
        destinations={o.object_id:o for start in near(engine,actor,owner,10) for o in lamps if connected(engine,owner,start,o)}
        if destinations and not used(engine,actor,'road_used'):
            selected=pick(ctx,'road_destination_lantern',list(destinations),{k:f'Approach Lantern at ({o.position.x}, {o.position.y})' for k,o in destinations.items()},subject=actor,optional=True)
            if selected and move_ally(ctx,actor,15,'road_step',toward=destinations[selected[0]].position):
                put(ctx,actor,'road_used',{'turn':stamp(engine),'label':'Lantern Road movement used this turn'})
    for owner in engine.state.actors.values():
        if owner is not actor and owned(engine,owner,LIGHT) and live(engine,owner):move_lantern(context(engine,owner,LIGHT),optional=True)


@hook('difficult_exempt')
def field_terrain(engine,actor):
    if not any((owner:=engine.state.actors.get(z.owner_id)) and ally(engine,owner,actor) for z in fields(engine,actor)):return None
    return {(x,y) for y in range(engine.grid.height) for x in range(engine.grid.width)}


GUIDANCE={'frightened','lost','direction_altering_illusion','distance_altering_illusion','supernatural_disorientation','concealed_direction_forced_movement'}
FIELD_SAVES={'charmed','frightened','possession','corruption','supernatural_disorientation','involuntary_soul_movement'}


@hook('save_mode')
def guiding_saves(engine,actor,ability,dc,source,metadata):
    tags={str(t).removeprefix('condition:typed.').removeprefix('category:') for t in metadata.get('named',[])}
    for owner in engine.state.actors.values():
        if owned(engine,owner,LIGHT) and ally(engine,owner,actor) and near(engine,actor,owner,10) and tags&GUIDANCE:return 'ADVANTAGE'
    for z in fields(engine,actor):
        if actor.entity_id in placed.data(z).get('chosen',[]) and tags&FIELD_SAVES:return 'ADVANTAGE'
    return None


@hook('ability_check_hazards')
def guidance_checks(engine,actor,ability,skill,hazards):
    if set(hazards)&GUIDANCE and any(owned(engine,o,LIGHT) and ally(engine,o,actor) and near(engine,actor,o,10) for o in engine.state.actors.values()):return 'ADVANTAGE'
    return None


# Returning Flame composes with ordinary proficiency and a single die rewrite.
from .d20_rewrite import Rule,Holder,register


def flame_holders(engine):
    return [Holder(a,ROAD,{},ROAD,numbers(engine,a)) for a in engine.state.actors.values() if owned(engine,a,ROAD)]


def flame_guard(engine,holder,roll):
    return bool(roll.kind=='save' and set(roll.named)&{'charmed','frightened','possession','supernatural_disorientation'}
        and ally(engine,holder.actor,roll.roller) and near(engine,roll.roller,holder.actor,10)
        and str(roll.ability).lower() not in ('death','training','breakthrough'))


def flame_after(engine,holder,roll,result,amount):
    if roll.dc is not None and result.total>=roll.dc:move_ally(context(engine,holder.actor,ROAD),roll.roller,5,'returning_flame_step')


def flame_ai(engine,holder,roll):
    from ..target_knowledge import located
    return located(engine,holder.actor,roll.roller)


register(Rule('lantern_returning_flame','Returning Flame',op='bonus',who='team',when='failed',reaction=True,
    limit='round',costs=((("qi",1),),),finder=flame_holders,guard=flame_guard,
    bonus=lambda e,h,r:int(h.numbers['pb']),after_bonus=flame_after,
    ai=flame_ai,checkpoint='D20_ROLL_BONUS'))


@hook('zero_hp_settled')
def hold_soul(engine,target,damage_source,intent):
    from ..pending_damage import current
    from .life_state import massive,is_deceased
    packet=current(engine)
    # Never infer a living body from inactivity or absorb instant-death damage.
    if packet and packet.source_flags&{'instant_death','body_destruction','disintegration','decapitation'}:return None
    if any(r['holder_id']==target.entity_id and set(r['tags'])&{'body_destroyed','instant_death','asset_suppression','lost','direction_altering_illusion','distance_altering_illusion','concealed_direction_forced_movement','supernatural_disorientation','corruption','involuntary_soul_movement'} for r in information_sources(engine)):return None
    if packet is None or packet.hp_before<=0 or is_deceased(target) or next((int(ev.payload['hp_damage']) for ev in reversed(engine.events) if ev.event_type=='DAMAGE_COMMITTED' and target.entity_id in ev.target_ids),packet.amount)-packet.hp_before>=massive(engine,target):return None
    from ..typed_reactions import can_react
    for owner in engine.state.actors.values():
        if not owned(engine,owner,HOLD) or not ally(engine,owner,target) or not near(engine,target,owner,30):continue
        if (owner.current_hp<=0 and owner.life_state!='CONSCIOUS') or not can_react(engine,owner) or owner.resources.get(QI,0)<4 or any(c.data.get('target')==target.entity_id for c in held(owner,'hold_used')):continue
        ctx=context(engine,owner,HOLD)
        selected=pick(ctx,'hold_departing_soul',['hold'],{'hold':f'Spend your Reaction and 4 Qi to keep {target.display_name} Unconscious, Stable and Soul-Anchored until the end of your next turn'},optional=True)
        if not selected:continue
        anchors=near(engine,target,owner,30)
        selected_anchor=pick(ctx,'soul_anchor_lantern',[o.object_id for o in anchors],
            {o.object_id:f'Anchor {target.display_name} to the Lantern at ({o.position.x}, {o.position.y}); Reaction and 4 Qi, until the end of your next turn' for o in anchors})
        if not selected_anchor:continue
        anchor=next((o for o in near(engine,target,owner,30) if o.object_id==selected_anchor[0]),None)
        if anchor is None:continue
        spend(ctx,4)
        if not activation_live(ctx):return None
        from ..typed_reactions import spend_reaction,publish_reaction_used
        spend_reaction(engine,owner,{'feature_id':HOLD})
        engine._append_event('REACTION_RESOLVED',HOLD,actor_id=owner.entity_id,payload={'checkpoint':'DEPARTING_SOUL'})
        publish_reaction_used(engine,owner,{'feature_id':HOLD,'name':'Hold the Departing Soul'})
        from .effect_durations import token
        expires=token('end',owner.entity_id,owner.turns_started+1)
        put(ctx,target,'soul_anchor',{'anchor_id':anchor.object_id,'source_cl':int(numbers(engine,owner)['cl']),
            'label':'Soul-Anchored: Unconscious and Stable at 0 HP; no death saving throws or damage failures until the end of the keeper’s next turn'},expires)
        put(ctx,owner,'hold_used',{'target':target.entity_id,'label':f'Hold the Departing Soul used on {target.display_name} this scene'})
        from .life_state import UNCONSCIOUS
        if not any(c.condition_id==UNCONSCIOUS for c in target.conditions.values()):
            engine._apply_condition(target,UNCONSCIOUS,HOLD,owner.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Unconscious at 0 HP'})
        engine._set_life_state(target,'STABLE',HOLD)
        return None
    return None


def anchor_live(engine,c):
    obj=engine.state.objects.get(c.data.get('anchor_id'))
    return bool(obj and not obj.destroyed and not (obj.component or {}).get('suppressed') and not suppressed(engine,obj))


@hook('damage_at_zero_failure_allowed')
def anchored_damage(engine,target,source):
    if any(anchor_live(engine,c) for c in held(target,'soul_anchor')):return False
    return None


@hook('effect_subject_allowed')
def soul_protection(ctx,row,subject):
    from ..observer_information import source_profile
    profile=source_profile(ctx.engine,ctx.source,row)
    soul_tags={'possession','soul_displacement','soul_capture','soul_consumption','involuntary_soul_movement'}
    if row.get('type') not in soul_tags and not (set(profile.get('tags',[]))&soul_tags) and row.get('condition') not in ('possessed','possession'):return None
    if profile.get('authority') in ('protected','artifact','secret','higher_authority') or row.get('severs_soul'):return None
    for c in held(subject,'soul_anchor'):
        if anchor_live(ctx.engine,c) and type(ctx.numbers.get('cl')) is int and ctx.numbers['cl']<c.data['source_cl']:return False
    return None


def end_anchor(engine,actor,c):
    remove(engine,actor,c)
    if actor.current_hp==0 and actor.life_state=='STABLE':engine._set_life_state(actor,'DYING',HOLD)


@hook('event',nested=True)
def changed(engine,kind,kwargs):
    if kind in ('OBJECT_UPDATED','CONDITION_APPLIED','CONDITION_REMOVED','HEALING_APPLIED') and any(held(a,'soul_anchor') or owned(engine,a,PASSAGE) for a in engine.state.actors.values()):
        for actor in engine.state.actors.values():
            for c in list(held(actor,'soul_anchor')):
                if not anchor_live(engine,c):end_anchor(engine,actor,c)
        # The normal expiry removed the anchor: Stable must resume Dying.
        if kind=='CONDITION_REMOVED' and kwargs.get('payload',{}).get('condition_id')==C+'soul_anchor':
            for aid in kwargs.get('target_ids',()):
                actor=engine.state.actors.get(aid)
                if actor and actor.current_hp==0 and actor.life_state=='STABLE' and not held(actor,'soul_anchor'):engine._set_life_state(actor,'DYING',HOLD)
        for owner in engine.state.actors.values():
            from .qi_path import armament_condition,ARMED
            arm=armament_condition(owner,include_suppressed=True)
            bound=engine.state.objects.get(arm.data.get('bound_asset_id')) if arm else None
            if arm and bound and bound.destroyed:engine._remove_condition(owner,ARMED,PASSAGE)
            elif arm and bound:
                inactive=int(bool(bound.component.get('suppressed') or suppressed(engine,bound)))
                if int(arm.data.get('asset_suppressed',0))!=inactive:
                    engine._remove_condition(owner,ARMED,PASSAGE)
                    engine._apply_condition(owner,ARMED,arm.source_definition_id,owner.entity_id,expires_on='UNTIL_REMOVED',
                        data={**arm.data,'asset_suppressed':inactive})


@hook('turn_end')
def expire_lanterns(engine,actor):
    from ..asset_anchor_runtime import members
    for o in list(members(engine,owner_id=actor.entity_id,group=TAG)):
        if engine.state.round_number>=int(o.component.get('expires_round',engine.state.round_number+1)):retire(engine,o,LIGHT)


@hook('would_drop')
def refuses_extinction(engine,target,pending,source_actor_id):
    from ..damage_allocation import available_temporary_hp,maximum_packet_before_hp_floor
    from ..pending_damage import current
    packet=current(engine)
    if target.current_hp<=0 or pending-available_temporary_hp(engine,target,pending,source_actor_id)-target.current_hp>=target.maximum_hp:return None
    if packet and set(packet.source_flags)&{'instant_death','body_destruction','disintegration','decapitation'}:return None
    for z in fields(engine,target):
        owner=engine.state.actors[z.owner_id]
        if not ally(engine,owner,target) or target.entity_id in placed.data(z).get('saved',[]):continue
        placed.update(engine,z,saved=[*placed.data(z).get('saved',[]),target.entity_id])
        ctx=context(engine,owner,TEN)
        put(ctx,target,'extinction_step',{'feet':10,'temporary_hp':2*int(z.trigger_profile['numbers']['pb']),'label':'Flame Refuses Extinction: gain Temporary HP and optionally move 10 feet without provoking after this damage'})
        return maximum_packet_before_hp_floor(engine,target,pending,1,source_actor_id)
    return None


@hook('state_event')
def extinction_settled(engine,event):
    if event.event_type!='DAMAGE_COMMITTED':return
    from ..typed_executor import run_effects
    for aid in event.target_ids:
        target=engine.state.actors.get(aid)
        if not target:continue
        for c in list(held(target,'extinction_step')):
            owner=engine.state.actors.get(c.source_actor_id)
            if owner is None:continue
            ctx=context(engine,owner,TEN)
            run_effects(replace(ctx,targets=[target],target=target),[{'type':'temp_hp','applies_to':'target','flat':c.data['temporary_hp']}])
            remove(engine,target,c)
            move_ally(ctx,target,10,'flame_refuses_extinction_step')


@hook('object_hp_floor')
def indestructible_lights(engine,actor,obj,taken,source):
    if not (obj.component or {}).get('asset_anchor_runtime') or obj.component['asset_anchor_runtime']['group']!=TAG:return None
    owner=engine.state.actors.get(obj.owner_id)
    field=field_for(engine,owner) if owner else None
    if field and inside(engine,obj.position,field):
        from ..observer_information import source_numbers
        n=source_numbers(engine,source,actor.entity_id if actor else '')
        if n.get('cl') is not None and n['cl']<field.trigger_profile['numbers']['cl']:return 1
    return None


# Native world-owner admission supplies otherwise unknown source facts; it does
# not let a player grant their own anatomy, spirit tags or teleport authority.
WORLD_TAGS={'spirit','incorporeal','possessing_entity','possession','visual_illusion','concealed_path','concealed_door','concealed_portal','formation_boundary','invisible','sealed_formation','spatial_lock','teleport_block','artifact_prison','body_destroyed','instant_death','asset_suppression'}


@hook('fact_admission_schema')
def lantern_schema(session,source,subject,kind):
    if source!=PARENT:return None
    if kind=='willing_traveler':return {'value_type':'flag','maximum_seconds':60,'description':'The subject personally agrees to this exact source-scoped travel declaration.'}
    if kind=='external_source':return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
        'description':'Record an actual external source, its explicit tags, CL, DC, plane, geometry and authority. Names do not establish these facts.'}
    return None


def sync_journey(session,aid):
    from ..canonical import canonical_sha256
    actor=session.state['actors'][aid];ledger=actor.get('source_states',{}).get(PARENT)
    if not ledger:return
    bundle=actor['bundle']
    bundle['lantern_keeper_state']=canonical({'state':ledger,'clock':int(session.clock()),'scene':session.state.get('scene_id') or session.state['journey_id']})
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


@hook('journey_initialize')
def initialize_journey(session,aid):
    sync_journey(session,aid)


@hook('journey_acquired')
def acquired_journey(session,aid,source,receipt):
    if source==PARENT:sync_journey(session,aid)


@hook('journey_state_changed')
def update_journey(session,aid):
    if session.state['actors'][aid]['incapacitated']:
        ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT,{})
        ledger.pop('field',None)
    sync_journey(session,aid)


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT)
    if not ledger:return
    rows=json.loads(ledger.get('objects','[]'))
    now=int(session.clock())
    for row in rows:
        c=row.get('component') or {}
        if c.get('expires_at',now+1)<=now:
            row['destroyed']=True;row['current_hp']=0
    ledger['objects']=canonical(rows)
    if ledger.get('field_until',0)<=now:ledger.pop('field',None)
    sync_journey(session,aid)


@hook('journey_scene_end')
def new_scene(session,previous,current):
    for aid,actor in session.state['actors'].items():
        ledger=actor.get('source_states',{}).get(PARENT)
        if ledger:
            ledger['scene']=current;ledger.pop('scene_limits',None);ledger.pop('revelation_locks',None);ledger.pop('revelation_results',None)
            sync_journey(session,aid)


@hook('journey_command')
def journey_commands(session,aid,kind,payload):
    if kind not in ('lantern_create','lantern_record_external_source','lantern_move','lantern_passage'):return None
    from ..journey import require
    from ..gate2_runtime_models import Position,RuntimeObjectState
    actor=session.state['actors'][aid]
    if kind=='lantern_record_external_source':
        from ..fact_consent_admission import read
        require(set(payload)=={'scope'},'Choose one admitted external source scope.')
        fact=read(session,PARENT,aid,'external_source',payload['scope'],aid)
        require(fact is not None,'The native world owner must first record that external source.')
        v=fact['value']
        require(set(v)=={'source_rule','tags','source_cl','save_dc','position','plane','authority','duration_seconds'},'Record all external source profile fields.')
        require(type(v['source_rule']) is str and bool(v['source_rule'].strip()) and isinstance(v['tags'],list) and set(v['tags'])<=WORLD_TAGS,'Supply explicit printed source tags, never a name-based classification.')
        require(type(v['source_cl']) is int and v['source_cl']>0 and type(v['save_dc']) is int and v['save_dc']>0,'Record the actual Source CL and save DC.')
        require(v['authority'] in ('ordinary','artifact','secret','higher_authority','world_law') and type(v['plane']) is str and v['plane'],'Record the actual source authority and plane.')
        require(type(v['duration_seconds']) is int and 0<v['duration_seconds']<=fact['expires_at']-int(session.clock()),'The native source cannot outlast its owner declaration.')
        Position.model_validate(v['position'])
        ledger=state(session,aid)
        entries=json.loads(ledger.get('external_sources','{}'));entries[payload['scope']]={**v,'receipt':fact['receipt_id'],'expires_at':int(session.clock())+v['duration_seconds']}
        ledger['external_sources']=canonical(entries)
        session.emit('LANTERN_EXTERNAL_SOURCE_COLLECTED',aid,source=PARENT,scope=payload['scope'],receipt=fact['receipt_id'])
        sync_journey(session,aid);return True
    require(any(r.get('block')=='lantern_keeper' and r['feature_id']==LIGHT for r in actor['bundle']['typed_passives']), 'Acquire Light the Way before commanding Lanterns.')
    require(not actor['incapacitated'],'An incapacitated Keeper cannot command Lanterns.')
    ledger=state(session,aid);now=int(session.clock())
    rows=json.loads(ledger.get('objects','[]'))
    active=[r for r in rows if not r['destroyed'] and r['component']['expires_at']>now]
    n=next(r['numbers'] for r in actor['bundle']['typed_passives'] if r.get('block')=='lantern_keeper')
    owner_point=Position.model_validate(actor['position'])
    if kind=='lantern_create':
        require(set(payload)=={'position'},'Choose the projected Lantern position. Real-item empowerment is also available at the table.')
        point=Position.model_validate(payload['position'])
        require(session.grid.distance_ft(owner_point,point)<=30 and session.grid.volume_legal(point),'Choose a legal Lantern point within 30 feet.')
        require(actor['resources'].get(QI,0)>=1,'Create Guiding Lantern costs 1 Qi.')
        require(actor['resources'][QI]>1 or actor['exhaustion']<5,'Resolve a lethal Qi-depletion expenditure in native combat before travel.')
        from ..journey_assets import JourneyAssetContext
        from ..asset_anchor_runtime import create as asset_create
        e=JourneyAssetContext(session);owner=e.state.actors[aid]
        obj=asset_create(e,owner,LIGHT,{'name':'Guiding Lantern','kind':'guiding_lantern','group':TAG,'ac':13+int(n['pb']),
            'hp':2*int(n['cl']),'source_cl':int(n['cl']),'height_ft':1,'immune':['FIRE','POISON','PSYCHIC'],
            'occupies_space':False,'requires_support':False},point,
            component={'size':'tiny','blocks':False,'cover':False,'creature':False,'speed_ft':20,'hover':True,'bright_ft':10,'dim_ft':10,
                'condition_immunities':['charmed','frightened','poisoned','prone'],'save_modifier':int(n['pb'])+int(n.get('key_mod') or 0),
                'initiative':'creator','actions':[],'reactions':[],'tether_ft':120,'expires_at':now+28800,'plane':'material','real_item':0},lifetime='8 hours')
        rows.append(obj.model_dump(mode='json'));actor['resources'][QI]-=1
        for old in sorted(active+[rows[-1]],key=lambda r:r['component']['asset_anchor_runtime']['sequence'])[:-int(n['pb'])]:old['destroyed']=True;old['current_hp']=0
        if actor['resources'][QI]==0:actor['exhaustion']+=1
        session.emit('LANTERN_QI_SPENT',aid,source=LIGHT,amount=1,remaining=actor['resources'][QI])
        session.tick(6)
    elif kind=='lantern_move':
        require(set(payload)=={'object_id','position'},'Choose your exact Lantern and destination.')
        obj=next((o for o in active if o['object_id']==payload['object_id']),None)
        require(obj is not None,'Only your active Guiding Lantern can be moved.')
        point=Position.model_validate(payload['position']);old=Position.model_validate(obj['position'])
        require(session.grid.distance_ft(old,point)<=20 and session.grid.volume_legal(point) and session.grid.line_of_physical_transmission(old,point),'Move the Lantern at most 20 feet through a clear route.')
        require(any(session.grid.distance_ft(point,p)<=120 for p in [owner_point,*[Position.model_validate(o['position']) for o in active if o is not obj]]),'Keep the Lantern within 120 feet of you or another Lantern.')
        obj['position']=point.model_dump(mode='json');session.tick(6)
    else:
        require(any(r.get('feature_id')==PASSAGE for r in actor['bundle']['typed_passives']),'Acquire Lantern Passage first.')
        base_keys={'first','second','position'};carry_keys={'traveler','traveler_arrival','consent_scope'}
        require(set(payload) in (base_keys,base_keys|carry_keys),'Declare both Lanterns, arrival and any one consenting traveler before travel.')
        first=next((o for o in active if o['object_id']==payload['first']),None);second=next((o for o in active if o['object_id']==payload['second']),None)
        require(first and second and first is not second,'Choose two of your active Lanterns.')
        p,q=Position.model_validate(first['position']),Position.model_validate(second['position']);arrival=Position.model_validate(payload['position'])
        require(session.grid.distance_ft(owner_point,p)<=5 and session.grid.distance_ft(p,q)<=120 and session.grid.distance_ft(q,arrival)<=5,'Respect Lantern Passage boarding, connection and arrival ranges.')
        require(not first['component'].get('suppressed') and not second['component'].get('suppressed') and first['component']['plane']==second['component']['plane'],'Suppressed Lanterns or different planes block passage.')
        from ..journey_assets import JourneyAssetContext
        ctx=JourneyAssetContext(session)
        require(ctx.grid.placement_legal(arrival,footprint=ctx._footprint(aid),occupied_cells={ (a.position.x,a.position.y) for a in ctx.state.actors.values() if a.entity_id!=aid}),'Choose an unoccupied legal arrival space.')
        sources=[v for a in session.state['actors'].values() for v in json.loads(a.get('source_states',{}).get(PARENT,{}).get('external_sources','{}')).values() if v['expires_at']>now]
        require(not any(set(v['tags'])&{'spatial_lock','sealed_formation','teleport_block','artifact_prison'} and Position.model_validate(v['position']) in (owner_point,arrival,p,q) for v in sources),'A native sealed endpoint blocks this passage; no Qi is spent.')
        field=json.loads(ledger.get('field','{}'));cost=1 if field and field.get('expires_at',0)>now else 3
        traveler=None;traveler_arrival=None
        if carry_keys<=set(payload):
            from ..fact_consent_admission import read,digest
            traveler=session.state['actors'].get(payload['traveler'])
            require(traveler is not None and payload['traveler']!=aid,'Choose one other present traveler.')
            traveler_arrival=Position.model_validate(payload['traveler_arrival'])
            require(session.grid.distance_ft(owner_point,Position.model_validate(traveler['position']))<=5
                and 0<session.grid.distance_ft(arrival,traveler_arrival)<=5,'The traveler boards within 5 feet and arrives in an adjacent separate space.')
            require(ctx.grid.placement_legal(traveler_arrival,footprint=ctx._footprint(payload['traveler']),occupied_cells={
                (a.position.x,a.position.y) for a in ctx.state.actors.values() if a.entity_id not in (aid,payload['traveler'])}|{(arrival.x,arrival.y)}),
                'The traveler needs a legal unoccupied adjacent arrival before activation.')
            expected=digest({'keeper':aid,'traveler':payload['traveler'],'first':payload['first'],'second':payload['second'],
                'position':payload['position'],'traveler_arrival':payload['traveler_arrival']})
            require(payload['consent_scope']==expected,'Traveler consent must name these exact endpoints and arrivals.')
            consent=read(session,PARENT,payload['traveler'],'willing_traveler',expected,aid)
            require(consent is not None and consent['value']==1,'The traveler must personally declare willingness to this passage.')
            cost+=1 if cost==1 else 2
        require(actor['resources'].get(QI,0)>=cost,f'Lantern Passage costs {cost} Qi for these travelers.')
        actor['resources'][QI]-=cost
        if actor['resources'][QI]==0:actor['exhaustion']+=1
        actor['position']=arrival.model_dump(mode='json')
        if traveler is not None:traveler['position']=traveler_arrival.model_dump(mode='json')
        session.tick(6)
        session.emit('LANTERN_PASSAGE_COMMITTED',aid,source=PASSAGE,first=first['object_id'],second=second['object_id'],destination=actor['position'],qi_spent=cost)
    ledger['objects']=canonical(rows)
    for raw in rows:session.state.setdefault('runtime_objects',{})[raw['object_id']]=raw
    sync_journey(session,aid);return True


@hook('match_start',priority=90)
def import_journey(engine):
    from ..gate2_runtime_models import RuntimeObjectState
    for bundle in getattr(engine,'typed_bundle_documents',()):
        text=bundle.get('lantern_keeper_state')
        if not text:continue
        saved=json.loads(text);ledger=saved['state'];clock=saved['clock'];owner=engine.state.actors[bundle['actor_id']]
        if owned(engine,owner,LIGHT):
            for raw in json.loads(ledger.get('objects','[]')):
                obj=RuntimeObjectState.model_validate(raw)
                if obj.destroyed or obj.component.get('expires_at',clock)<=clock:continue
                c={**obj.component,'expires_round':engine.state.round_number+max(1,(obj.component['expires_at']-clock+5)//6)}
                engine._update_object(obj.model_copy(update={'component':c}),LIGHT,owner.entity_id)
            for raw in json.loads(ledger.get('scene_limits','[]'))+json.loads(ledger.get('revelation_results','[]')):
                tag=raw['condition_id'].removeprefix(C)
                put(context(engine,owner,LIGHT),owner,tag,raw['data'])
        saved_field=json.loads(ledger.get('field','{}'))
        if owned(engine,owner,TEN) and saved_field and saved_field['expires_at']>clock:
            from ..gate2_runtime_models import Position
            source=next((a.source_definition_id for a in engine.action_catalog.values() if a.owner_id==owner.entity_id
                         and (a.parameters.get('typed') or {}).get('source')==TEN),TEN)
            engine._start_concentration(owner,source)
            placed.place(engine,owner,source=source,tag=FIELD,cells=[Position.model_validate(saved_field['center'])],name='Ten Thousand Lantern Road',
                placed={'chosen':saved_field['chosen'],'saved':saved_field.get('saved',[]),'activation_id':saved_field.get('activation_id','')},numbers=saved_field['numbers'],
                duration_rounds=max(1,(saved_field['expires_at']-clock+5)//6),concentration=True,radial_volume=True,
                shape='cylinder',size_ft=60,extra={'height_ft':60})
        for key,entry in json.loads(ledger.get('external_sources','{}')).items():
            if entry['expires_at']<=clock:continue
            from .effect_durations import round_token
            engine._apply_condition(owner,'condition:information.source',entry['source_rule'],owner.entity_id,
                expires_on=round_token(engine,max(1,(entry['expires_at']-clock+5)//6)),data={
                'information_profile':{'tags':entry['tags'],'source_cl':entry['source_cl'],'save_dc':entry['save_dc'],'authority':entry['authority'],
                    'position':entry['position'],'plane':entry['plane']},'world_receipt':entry['receipt'],'label':'Source-scoped external world effect'})


@hook('journey_encounter_settled')
def export_journey(session,aid,engine,actor):
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT)
    if not ledger:return
    now=int(session.clock());rows=[]
    entries=json.loads(ledger.get('external_sources','{}'))
    elapsed=max(0,engine.state.round_number-1)*6
    for entry in entries.values():entry['expires_at']=max(now,entry['expires_at']-elapsed)
    if entries:ledger['external_sources']=canonical(entries)
    if not owned(engine,actor,LIGHT):
        sync_journey(session,aid);return
    for obj in engine.state.objects.values():
        if obj.owner_id!=aid or not (obj.component or {}).get('asset_anchor_runtime') or obj.component['asset_anchor_runtime']['group']!=TAG:continue
        c={**obj.component,'expires_at':now+max(0,int(obj.component['expires_round'])-engine.state.round_number)*6}
        rows.append(obj.model_copy(update={'component':c}).model_dump(mode='json'))
    ledger['objects']=canonical(rows)
    zone=field_for(engine,actor)
    if zone:
        field={'center':zone.center.model_dump(mode='json'),'chosen':placed.data(zone)['chosen'],'saved':placed.data(zone).get('saved',[]),
            'numbers':zone.trigger_profile['numbers'],'source':TEN,
            'expires_at':now+max(0,zone.created_round+(zone.duration_rounds or 10)-engine.state.round_number)*6,
            'activation_id':placed.data(zone).get('activation_id') or zone.zone_id}
        ledger['field']=canonical(field);ledger['field_until']=field['expires_at']
    else:ledger.pop('field',None)
    ledger['revelation_results']=canonical([c.model_dump(mode='json') for c in held(actor,'revelation_result')])
    ledger['scene_limits']=canonical([c.model_dump(mode='json') for c in actor.conditions.values() if c.condition_id in (C+'field_used',C+'hold_used')])
    sync_journey(session,aid)


@hook('journey_snapshot_actor')
def snapshot_without_source_limits(actor,session,aid,engine):
    own_world={i for i,c in actor.conditions.items() if c.condition_id=='condition:information.source' and c.data.get('world_receipt')}
    if not owned(engine,actor,LIGHT) and not own_world:return None
    conditions={i:c for i,c in actor.conditions.items() if i not in own_world and c.condition_id not in (C+'field_used',C+'hold_used',C+'move_used',C+'passage_used',C+'guide_used',C+'revelation_result')}
    own_source={z.source_definition_id for z in placed.of(engine,FIELD,owner_id=aid)}
    return actor.model_copy(update={'conditions':conditions,**({'concentration':None} if actor.concentration and actor.concentration.source_definition_id in own_source else {})})


def information_sources(engine):
    from ..observer_information import sources
    rows=sources(engine)
    from .creature_kinds import matches
    for actor in engine.state.actors.values():
        traits=set()
        if matches(actor,{'incorporeal'}):traits.add('incorporeal')
        if matches(actor,{'possessing entity'}):traits.add('possessing_entity')
        invisible=any(c.condition_id=='condition:typed.invisible' for c in actor.conditions.values())
        if invisible and matches(actor,{'spirit'}):traits.add('spirit')
        if traits:
            from ..observer_information import source_numbers
            n=source_numbers(engine,'',actor.entity_id)
            rows.append({'id':actor.entity_id,'revision':':'.join(sorted(actor.conditions)), 'tags':sorted(traits),
                'holder_id':actor.entity_id,'position':actor.position,'profile':{},'cl':n.get('cl'),'dc':n.get('save_dc')})
    for row in rows:
        condition=row.get('condition')
        if condition is not None and condition.data.get('world_receipt'):
            row['id']='world:'+condition.data['world_receipt'];row['revision']=condition.data['world_receipt']
        if row['profile'].get('position'):
            from ..gate2_runtime_models import Position
            row['position']=Position.model_validate(row['profile']['position'])
    return rows


def visible_trace(engine,viewer,point):
    from .. import senses
    if any(c.condition_id in set(senses.rules().get('blinded_conditions',[])) for c in viewer.conditions.values()):return False
    return engine._line_of_sight_actor_to_cell(viewer,point)


def revelations(engine,viewer):
    """Pure visible output; failure checks are resolved once at a native intent."""
    out=[]
    for owner in engine.state.actors.values():
        if not owned(engine,owner,LIGHT):continue
        lamps=live(engine,owner);zone=field_for(engine,owner)
        for row in information_sources(engine):
            point=row['position'];tags=set(row['tags']);profile=row['profile']
            if profile.get('plane','material')!='material':continue
            if not visible_trace(engine,viewer,point):continue
            bright=any(engine.grid.distance_ft(o.position,point)<=10 for o in lamps)
            in_field=bool(zone and inside(engine,point,zone))
            if not bright and not in_field:continue
            cl=int(numbers(engine,owner)['cl']);source_cl=row.get('cl')
            kinds=[]
            if bright:
                if tags&{'spirit','incorporeal','possessing_entity','possession'}:kinds.append('Luminous spirit trace')
                if source_cl is not None and source_cl<cl:
                    if 'possession' in tags:kinds.append('Second flame: active possession')
                    if 'visual_illusion' in tags:kinds.append('Flickering visual illusion')
            if in_field:
                if 'invisible' in tags:kinds.append('Visible outline')
                if tags&{'possession','possessing_entity'}:kinds.append('Second shadow')
                if 'visual_illusion' in tags:kinds.append('Flickering visual illusion')
                if tags&{'concealed_path','concealed_door','concealed_portal','formation_boundary'}:kinds.append('Luminous concealed route or boundary trace')
            if not kinds:continue
            key=f'{row["id"]}:{row["revision"]}:{(placed.data(zone).get('activation_id') or zone.zone_id) if zone else "bright"}'
            decision=next((c for c in held(owner,'revelation_result') if c.data['key']==key),None)
            resisted=in_field and source_cl is not None and source_cl>cl
            if resisted and (decision is None or not decision.data['success']):
                if decision is None or viewer.entity_id!=owner.entity_id:continue
                out.append({'kind':'concealment_exists','viewer_id':viewer.entity_id,'source_id':TEN,'details':{'text':'Something is concealed; its exact location and nature are unknown.'}})
            else:
                out.append({'kind':'resonance','viewer_id':viewer.entity_id,'source_id':LIGHT if not in_field else TEN,
                    'details':{'text':'; '.join(dict.fromkeys(kinds)),'position':point.model_dump(mode='json')}})
    return out


@hook('observer_information_rows')
def reveal_readings(engine,viewer):
    rows=revelations(engine,viewer)
    for owner in engine.state.actors.values():
        if not owned(engine,owner,ROAD):continue
        lamps=live(engine,owner)
        for i,first in enumerate(lamps):
            for second in lamps[i+1:]:
                if connected(engine,owner,first,second) and visible_trace(engine,viewer,first.position) and visible_trace(engine,viewer,second.position):
                    rows.append({'kind':'resonance','viewer_id':viewer.entity_id,'source_id':ROAD,
                        'details':{'text':'A visible road of faint light connects these Guiding Lanterns.',
                            'from':first.position.model_dump(mode='json'),'to':second.position.model_dump(mode='json')}})
    return rows


@hook('technique_used')
def reveal_contests(ctx):
    for owner in ctx.engine.state.actors.values():
        zone=field_for(ctx.engine,owner)
        if not zone:continue
        for row in information_sources(ctx.engine):
            if not inside(ctx.engine,row['position'],zone) or row.get('cl') is None or row['cl']<=int(numbers(ctx.engine,owner)['cl']):continue
            key=f'{row["id"]}:{row["revision"]}:{placed.data(zone).get("activation_id") or zone.zone_id}'
            if any(c.data.get('key')==key for c in held(owner,'revelation_result')):continue
            if not set(row['tags'])&{'invisible','possession','possessing_entity','visual_illusion','concealed_path','concealed_door','concealed_portal','formation_boundary'}:continue
            if row.get('dc') is None:continue
            frame=(id(ctx.engine),owner.entity_id,key)
            if frame in _REVEALING.get():continue
            from .ability_source import cultivation_check
            token=_REVEALING.set(_REVEALING.get()|{frame})
            try:
                success=cultivation_check(ctx.engine,owner,numbers(ctx.engine,owner),row['dc'],TEN,'Ten Thousand Revelations Cultivation Check')
                put(context(ctx.engine,owner,TEN),owner,'revelation_result',{'key':key,'success':int(success),'label':'Ten Thousand Revelations: source-specific check result'})
            finally:_REVEALING.reset(token)


@hook('masked_conditions')
def outline_visibility(engine,viewer,target):
    if not hasattr(target,'conditions'):return None
    point=target.position.model_dump(mode='json')
    if any(r['details'].get('position')==point and 'Visible outline' in r['details'].get('text','') for r in revelations(engine,viewer)):
        return {target.entity_id:{iid for iid,c in target.conditions.items() if c.condition_id=='condition:typed.invisible'}}
    return None


@hook('row_allowed')
def no_approximate_reactions(engine,actor,row):
    if row.get('block')=='generic' and str(row.get('feature_id','')).startswith(P):return False
    return None


@hook('turn_start')
def clear_turn_ledgers(engine,actor):
    for subject in engine.state.actors.values():
        for tag in ('move_used','passage_used','guide_used','road_used'):
            for c in list(held(subject,tag)):
                if c.data.get('turn')!=stamp(engine):remove(engine,subject,c)


@hook('darkness_lifted')
def lantern_illumination(engine,zone,viewer,seen):
    from .darkness_scope import scope
    if scope(engine,zone)!='ordinary':return None
    if seen is None:return None
    return True if any(engine.grid.distance_ft(o.position,seen.position)<=20 and engine.grid.line_of_physical_transmission(o.position,seen.position) for o in live(engine)) else None


def asset_routes(engine,start,feet):
    """One bounded native fly traversal, retaining every legal endpoint."""
    from collections import deque
    from ..gate2_runtime_models import Position
    queue=deque([start]);best={start:0};paths={start:(start,)}
    while queue:
        point=queue.popleft();cost=best[point]
        if cost>=feet:continue
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    if not (dx or dy or dz) or point.z+dz<0:continue
                    nxt=Position(x=point.x+dx,y=point.y+dy,z=point.z+dz)
                    if not engine.grid.in_bounds((nxt.x,nxt.y)) or not engine.grid.volume_step_legal(point,nxt):continue
                    total=cost+engine.grid.distance_ft(point,nxt)
                    if total>feet or total>=best.get(nxt,feet+1):continue
                    best[nxt]=total;paths[nxt]=(*paths[point],nxt);queue.append(nxt)
    return paths


def asset_path(engine,start,end,feet):
    return asset_routes(engine,start,feet).get(end)


@hook('carried_item_remaining')
def real_item_destroyed(engine,actor,item):
    return 0 if any(o.destroyed and (o.component or {}).get('item_identity')==actor.entity_id+'|'+item.get('key','')
        for o in engine.state.objects.values()) else None


@hook('movement_step_settled')
@hook('forced_movement_step')
def carried_lantern_follows(engine,mover,previous,destination,intent):
    from ..asset_anchor_runtime import members
    for obj in list(members(engine,group=TAG)):
        if obj.component.get('carried_by')==mover.entity_id:
            engine._update_object(obj.model_copy(update={'position':destination}),LIGHT,obj.owner_id)


@hook('journey_command')
def journey_field_and_guide(session,aid,kind,payload):
    if kind not in ('lantern_field','lantern_guide'):return None
    from ..journey import require
    from ..gate2_runtime_models import Position
    from ..journey_assets import JourneyAssetContext
    actor=session.state['actors'][aid];ledger=state(session,aid);now=int(session.clock())
    rows=actor['bundle']['typed_passives']
    require(not actor['incapacitated'] and any(r.get('block')=='lantern_keeper' and r['feature_id']==TEN for r in rows),'Acquire Ten Thousand Lantern Road and remain able to act.')
    n=next(r['numbers'] for r in rows if r.get('block')=='lantern_keeper')
    if kind=='lantern_field':
        require(set(payload)=={'position','chosen'},'Declare the field center and chosen allies.')
        limits=json.loads(ledger.get('scene_limits','[]'))
        require(not any(r['condition_id']==C+'field_used' for r in limits),'Ten Thousand Lantern Road is already used this scene.')
        point=Position.model_validate(payload['position']);origin=Position.model_validate(actor['position'])
        require(session.grid.distance_ft(origin,point)<=120 and session.grid.volume_legal(point),'Place the field center within 120 feet.')
        require(isinstance(payload['chosen'],list) and len(set(payload['chosen']))==len(payload['chosen']) and set(payload['chosen'])<=set(session.state['actors']),'Choose distinct present creatures for protection.')
        require(actor['resources'].get(QI,0)>=8,'Ten Thousand Lantern Road costs 8 Qi.')
        actor['resources'][QI]-=8
        if actor['resources'][QI]==0:actor['exhaustion']+=1
        session.tick(6)
        field={'center':point.model_dump(mode='json'),'chosen':payload['chosen'],'numbers':n,'saved':[],
            'expires_at':int(session.clock())+60,'source':TEN,'activation_id':f'{PARENT}:{aid}:{len(session.state["events"])}'}
        ledger['field']=canonical(field);ledger['field_until']=field['expires_at']
        ledger['scene_limits']=canonical([*limits,{'condition_id':C+'field_used','data':{'label':'Ten Thousand Lantern Road used this scene'}}])
        session.emit('LANTERN_FIELD_ACTIVATED',aid,source=TEN,center=field['center'],chosen=payload['chosen'],expires_at=field['expires_at'],qi_spent=8)
    else:
        require(set(payload)=={'traveler','position','consent_scope','teleport'},'Declare the willing traveler, destination, exact consent scope and movement method.')
        require(type(payload['teleport']) is bool,'Choose ordinary travel or teleportation explicitly.')
        field=json.loads(ledger.get('field','{}'))
        require(field and field['expires_at']>now,'Your concentrated Lantern field is no longer active.')
        target=session.state['actors'].get(payload['traveler']);require(target is not None,'Choose a present traveler.')
        origin=Position.model_validate(target['position']);point=Position.model_validate(payload['position']);center=Position.model_validate(field['center'])
        require(0<=(origin.z-center.z)*5<=60 and session.grid.distance_ft(origin.model_copy(update={'z':center.z}),center)<=60,'The traveler must start inside your field.')
        from ..fact_consent_admission import read,digest
        expected=digest({'keeper':aid,'traveler':payload['traveler'],'position':payload['position'],'teleport':int(payload['teleport'])})
        require(payload['consent_scope']==expected,'Consent must name this exact keeper, traveler, destination and method.')
        consent=read(session,PARENT,payload['traveler'],'willing_traveler',expected,aid)
        require(consent is not None and consent['value']==1,'The traveler must personally declare willingness to this exact travel.')
        require(session.grid.distance_ft(origin,point)<=30 and session.grid.line_of_physical_transmission(origin,point),'Guide up to 30 feet without crossing a solid barrier or Total Cover.')
        e=JourneyAssetContext(session)
        require(e.grid.placement_legal(point,footprint=e._footprint(payload['traveler']),occupied_cells={(a.position.x,a.position.y) for a in e.state.actors.values() if a.entity_id!=payload['traveler']}),'Choose a legal unoccupied arrival.')
        sources=[v for a in session.state['actors'].values() for v in json.loads(a.get('source_states',{}).get(PARENT,{}).get('external_sources','{}')).values() if v['expires_at']>now]
        require(not any(set(v['tags'])&{'spatial_lock','sealed_formation','teleport_block','artifact_prison'} and Position.model_validate(v['position']) in (origin,point) for v in sources),'A sealed boundary blocks this travel.')
        if payload['teleport']:
            require(actor['resources'].get(QI,0)>=1,'Teleporting the traveler costs 1 Qi.')
            actor['resources'][QI]-=1
            if actor['resources'][QI]==0:actor['exhaustion']+=1
        else:
            # Native journey movement validates each traversed edge, terrain and
            # occupancy. The free grant changes no ordinary travel resource.
            found=session.grid.shortest_path(origin,point,max_cost_ft=30,occupied_cells={(a.position.x,a.position.y) for a in e.state.actors.values() if a.entity_id!=payload['traveler']},footprint=e._footprint(payload['traveler']))
            require(found is not None,'No legal thirty-foot physical route exists.')
            path,_=found
            for old,nxt in zip(path,path[1:]):session.step_profile(payload['traveler'],old,nxt)
        target['position']=point.model_dump(mode='json');session.tick(6)
        session.emit('LANTERN_TRAVELER_GUIDED',aid,source=TEN,traveler=payload['traveler'],destination=target['position'],teleport=int(payload['teleport']),consent_receipt=consent['receipt_id'])
    sync_journey(session,aid);return True


@hook('technique_cost_discount')
def passage_field_price(engine,actor,source,listed):
    action_row=engine.action_catalog.get(source)
    if action_row is None:return None
    typed=action_row.parameters.get('typed') or {}
    if typed.get('source')==PASSAGE and owned(engine,actor,PASSAGE) and field_for(engine,actor) and listed.get(QI,0)>=2:
        return {QI:2}
    return None


@hook('teleport_settled')
def carried_lantern_teleports(ctx,subject,previous,destination,unwilling):
    carried_lantern_follows(ctx.engine,subject,previous,destination,ctx.intent)


@hook('condition_admission')
def anchored_native_possession(engine,subject,condition_id,source,owner_id):
    if condition_id not in ('condition:typed.possessed','condition:typed.possession'):return None
    from ..observer_information import source_numbers,source_profile
    profile=source_profile(engine,source,{})
    if profile.get('authority') in ('protected','artifact','secret','higher_authority','world_law'):return None
    n=source_numbers(engine,source,owner_id)
    if n.get('cl') is not None and any(anchor_live(engine,c) and n['cl']<c.data['source_cl'] for c in held(subject,'soul_anchor')):return False
    return None


def suppressed(engine,obj):
    return any('asset_suppression' in row['tags'] and row['position']==obj.position
               and row['profile'].get('plane','material')==obj.component.get('plane','material')
               for row in information_sources(engine))


@hook('armament_endpoint_allowed')
def bound_lantern_endpoint(engine,owner,point):
    from .qi_path import armament_condition
    from ..gate2_runtime_models import Position
    arm=armament_condition(owner)
    if not owned(engine,owner,PASSAGE) or arm is None:return None
    obj=engine.state.objects.get(arm.data.get('bound_asset_id'))
    if obj is None or not obj.component.get('domain_armament'):return None
    p=point if isinstance(point,Position) else Position(x=point[0],y=point[1],z=point[2] if len(point)>2 else 0)
    # Owner travel does not move an already placed Lantern. A new Lantern
    # destination still obeys its own printed owner-or-other-Lantern tether.
    return p==obj.position or any(engine.grid.distance_ft(p,q)<=120 for q in [owner.position,*[o.position for o in live(engine,owner) if o.object_id!=obj.object_id]])


@hook('candidate_allowed')
def bound_armament_target(engine,actor,candidate,action_row):
    if action_row is None or action_row.parameters.get('armament')!='attack' or not owned(engine,actor,PASSAGE):return None
    from .qi_path import armament_condition
    arm=armament_condition(actor)
    obj=engine.state.objects.get(arm.data.get('bound_asset_id')) if arm else None
    if obj is None:return None
    if obj.destroyed or suppressed(engine,obj) or obj.component.get('suppressed'):return False
    origin=(candidate.metadata or {}).get('effect_origin') or {}
    if origin.get('id')!=obj.object_id:return False
    return all((target:=engine.state.actors.get(aid)) is not None and engine.grid.distance_ft(obj.position,target.position)<=5 for aid in candidate.target_ids)


@hook('nominal_slot_boundary')
def lantern_duration_boundary(engine,actor,checkpoint):
    for owner in engine.state.actors.values():
        if owned(engine,owner,LIGHT):expire_lanterns(engine,owner)


@hook('armament_asset_relocating')
def preserve_bound_real_item(engine,owner,obj,point,source):
    if not owned(engine,owner,PASSAGE) or not obj.component.get('domain_armament'):return None
    if obj.destroyed or suppressed(engine,obj) or obj.component.get('suppressed'):return False
    if point==obj.position:return None
    if not obj.component.get('item_identity'):return None
    from .scoundrel_riders import possessions,relocate_possession,relocate_ground_possession
    ctx=context(engine,owner,PASSAGE)
    ctx=replace(ctx,effect_source=source)
    original=engine.state.actors[obj.component['inventory_owner']]
    carrier=engine.state.actors.get(obj.component.get('carried_by'))
    item=next((i for i in possessions(engine,carrier) if i['object']==obj.component['item_identity']),None) if carrier else None
    path=asset_path(engine,obj.position,point,max(20,int(engine.grid.distance_ft(obj.position,point))))
    if not path:return False
    return relocate_possession(ctx,carrier,item,path,ignore_actor_space=True) if item else relocate_ground_possession(ctx,original,obj.component['item_key'],path)


@hook('candidate_allowed')
def suppressed_binding_not_new_manifest(engine,actor,candidate,action_row):
    if action_row is None or action_row.parameters.get('armament')!='manifest':return None
    from .qi_path import armament_condition
    arm=armament_condition(actor,include_suppressed=True)
    if arm and arm.data.get('bound_asset_id') and arm.data.get('asset_suppressed'):return False
    return None


@hook('state_event')
def committed_revelations(engine,event):
    if event.event_type not in ('INTENT_ACCEPTED','MOVEMENT_COMMITTED','CONDITION_APPLIED','ZONE_CREATED'):return
    if getattr(engine,'_active_intent',None) is None:return
    owner=next((a for a in engine.state.actors.values() if owned(engine,a,TEN) and field_for(engine,a)),None)
    if owner is not None:reveal_contests(context(engine,owner,TEN))


@hook('presentation_hidden_conditions')
def private_lantern_ledgers(engine,actor):
    names={C+s for s in ('move_used','passage_used','guide_used','road_used','field_used','hold_used','revelation_result')}
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in names]


@hook('event',nested=True)
def real_lantern_custody(engine,kind,kwargs):
    if kind!='CONDITION_REMOVED':return
    from ..asset_anchor_runtime import members
    from .scoundrel_riders import possessions
    for obj in list(members(engine,group=TAG)):
        identity=obj.component.get('item_identity')
        if not identity:continue
        carrier=next((a for a in engine.state.actors.values() if any(i.get('object')==identity for i in possessions(engine,a))),None)
        if carrier and (obj.component.get('carried_by')!=carrier.entity_id or obj.position!=carrier.position):
            engine._update_object(obj.model_copy(update={'position':carrier.position,
                'component':{**obj.component,'carried_by':carrier.entity_id}}),LIGHT,obj.owner_id)


def blocked_endpoint(engine,point):
    if any(set(row['tags'])&{'spatial_lock','sealed_formation','teleport_block','artifact_prison'} and row['position']==point
           for row in information_sources(engine)):return True
    return any(z.active and (z.trigger_profile.get('spatial_lock') or z.trigger_profile.get('sealed_formation') or z.trigger_profile.get('blocks_teleport'))
               and any(point==p for p in z.affected_cells) for z in engine.state.zones.values())


def activation_live(ctx):
    from ..typed_executor import condition_rules
    live=ctx.actor.active and ctx.actor.life_state not in ('DYING','STABLE') and not any(r.get('no_actions') for r in condition_rules(ctx.actor))
    if not live:placed.note(ctx.engine,ctx.source,ctx.actor,f'{ctx.action.display_name}: {ctx.actor.display_name} cannot finish after paying its cost; the payment remains spent.')
    return live


@hook('state_event')
def qi_depleted(engine,event):
    if event.event_type!='RESOURCE_SPENT' or event.payload.get('resource_id')!=QI or event.payload.get('remaining')!=0 or int(event.payload.get('amount') or 0)<=0:return
    actor=engine.state.actors.get(event.actor_id)
    if actor is None or not owned(engine,actor,LIGHT):return
    from .forged_exhaustion import add
    add(engine,actor,1,event.source_definition_id)


@hook('fact_admission_schema')
def cultivation_environment(session,source,subject,kind):
    if source==PARENT and kind=='cultivation_environment':return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
        'description':'The native world owner confirms a reasonably calm environment and sufficient ambient Qi or an appropriate substitute for the actual two-hour session.'}
    return None


def journey_qi_recovery(session,aid,amount,procedure):
    actor=session.state['actors'][aid]
    maximum=next((p['maximum'] for p in actor['bundle']['actor_template']['resources'] if p['resource_id']==QI),0)
    before=actor['resources'].get(QI,0)
    actor['resources'][QI]=min(maximum,before+amount)
    session.emit('LANTERN_QI_RECOVERED',aid,source=PARENT,procedure=procedure,amount=actor['resources'][QI]-before,
        remaining=actor['resources'][QI],long_rest=actor['long_rests'])
    sync_journey(session,aid)


@hook('journey_rest')
def lantern_long_rest(session,aid):
    actor=session.state['actors'][aid]
    if not any(r.get('block')=='lantern_keeper' and r.get('feature_id')==LIGHT for r in actor['bundle']['typed_passives']):return
    maximum=next(p['maximum'] for p in actor['bundle']['actor_template']['resources'] if p['resource_id']==QI)
    journey_qi_recovery(session,aid,maximum//2,'long_rest')


@hook('journey_command')
def lantern_cultivation_recovery(session,aid,kind,payload):
    if kind not in ('lantern_qi_short_rest','lantern_qi_cultivation_session'):return None
    from ..journey import require
    actor=session.state['actors'][aid]
    require(not actor['incapacitated'] and any(r.get('block')=='lantern_keeper' and r['feature_id']==LIGHT for r in actor['bundle']['typed_passives']),
        'An acquired Lantern Keeper must be able to perform this Qi recovery procedure.')
    key='qi.short_rest' if kind=='lantern_qi_short_rest' else 'qi.full_cultivation_session'
    uses=actor['travel_uses'];rest=actor['long_rests']
    require(uses.get(key,-1)!=rest,'This Qi recovery procedure was already used before your next Long Rest.')
    if kind=='lantern_qi_short_rest':
        require(not payload,'A Short Rest lasts one actual hour.')
        session.tick(3600);gain=int(actor['bundle']['cl'])
    else:
        require(set(payload)=={'environment_scope'},'Choose the native world-owner cultivation environment declaration.')
        from ..fact_consent_admission import read
        declaration=read(session,PARENT,aid,'cultivation_environment',payload['environment_scope'],aid)
        require(declaration is not None and declaration['value']=={'calm':1,'ambient_qi_or_substitute':1},'Confirm a calm environment and sufficient ambient Qi or an appropriate substitute.')
        session.tick(7200)
        require(read(session,PARENT,aid,'cultivation_environment',payload['environment_scope'],aid) is not None,'The environment must remain valid through the entire two-hour session.')
        gain=next(p['maximum'] for p in actor['bundle']['actor_template']['resources'] if p['resource_id']==QI)
    uses[key]=rest
    journey_qi_recovery(session,aid,gain,'short_rest' if key=='qi.short_rest' else 'full_cultivation_session')
    return True


@hook('candidate_allowed')
def retire_parser_approximations(engine,actor,candidate,action_row):
    typed=(getattr(action_row,'parameters',{}) or {}).get('typed') or {}
    if str(typed.get('source','')).startswith(P) and not any(r.get('type')=='lantern_keeper' for r in typed.get('effects',[])):return False
    return None


@hook('reaction_rows')
def retire_parser_reactions(engine,actor_id,block,rows):
    if not any(str(r.get('feature_id','')).startswith(P) for r in rows):return None
    return [r for r in rows if not str(r.get('feature_id','')).startswith(P)]


@hook('pinpoint_target')
def trace_location(engine,viewer,target):
    if not hasattr(target,'conditions'):return None
    qualifying=[r for r in information_sources(engine) if r['holder_id']==target.entity_id and
        set(r['tags'])&{'spirit','incorporeal','possessing_entity','possession','invisible'}]
    if not qualifying:return None
    point=target.position.model_dump(mode='json')
    return True if any(r['details'].get('position')==point and any(word in r['details'].get('text','') for word in
        ('Luminous spirit trace','Second flame','Second shadow','Visible outline')) for r in revelations(engine,viewer)) else None
