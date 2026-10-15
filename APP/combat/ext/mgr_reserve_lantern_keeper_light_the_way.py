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
_TRACE_VIEW=ContextVar("lantern_trace_visibility",default=False)
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
    choices={s for s in choices if isinstance(s,str) and s.startswith('tianxia.subpath.qi.')}
    ids=set(paths.get('path_feature_record_ids') or [])|set(paths.get('source_granted_subpath_feature_record_ids') or [])
    require(not choices and not any(s.startswith('tianxia.subpath.qi.') for s in ids),'The Qi Subpath slot is already occupied; selecting Lantern Keeper cannot retain another progression.')
    earned=[f for f,cl in LEVELS.items() if cl<=attained]
    paths.update(subpath_record_id=PARENT,subpath_record_ids=list(dict.fromkeys([*paths.get('subpath_record_ids',[]),PARENT])),
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
    chosen=set(paths.get('subpath_record_ids') or [])|{paths.get('subpath_record_id')};chosen={s for s in chosen if isinstance(s,str) and s.startswith('tianxia.subpath.qi.')}
    if chosen-{PARENT}:raise ValueError('The installed Qi Subpath conflicts with the committed Lantern Keeper selection.')
    attained=level(sheet)
    earned=[f for f,cl in LEVELS.items() if cl<=attained]
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        paths[key]=list(dict.fromkeys([*paths.get(key,[]),*saved.get(key,[]),*earned]))
    for key in ('subpath_record_id','subpath_record_ids','subpath_acquisition','bindings'):paths[key]=deepcopy(saved[key])
    return {**sheet,'path_and_subpath':paths}


def compiled_numbers(info):
    from ..path_numbers import path_numbers
    return path_numbers(info['owner_sheet'],info['numbers'],info['mods'],'tianxia.path.qi_cultivation')


@hook('compile_passives')
def ownership(rows,info):
    # Replace parser approximations for this family, retaining every other row.
    out=[r for r in rows if not str(r.get('feature_id','')).startswith(P)]
    if not any(f in info['owned_ids'] for f in LEVELS):return out
    n=compiled_numbers(info)
    cap=min(int(n.get('cl') or 1),level(info['owner_sheet']) or int(n.get('cl') or 1))
    return [*out,*[{'block':'lantern_keeper','feature_id':f,'numbers':n} for f,cl in LEVELS.items() if f in info['owned_ids'] and cap>=cl]]


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
        parameters={'description':text,'typed':{'source':feature,'manual_inline_choice':True,'numbers':compiled_numbers(info),
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
    if not any(f in info['owned_ids'] for f in LEVELS):return None
    n=compiled_numbers(info)
    cap=min(int(n.get('cl') or 1),level(info['owner_sheet']) or int(n.get('cl') or 1))
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
    description={LIGHT:'Move one Guiding Lantern up to 20 feet once during this turn, without an action or Qi; remain within 120 feet of you or another Lantern.',
        ROAD:'Reaction, 1 Qi, once per round: add your Proficiency Bonus to this failed qualifying save. On success the ally may move 5 feet without provoking.',
        PASSAGE:'Lantern Passage: Bonus Action, 3 Qi; carry one willing traveler for 2 additional Qi. Your field reduces these costs to 1 Qi each.',
        HOLD:'Reaction, 4 Qi, once per creature per scene: keep this ally Unconscious and Stable at 0 HP until the end of your next turn.',
        TEN:'Ten Thousand Lantern Road: 1-minute field requiring Concentration; granted travel uses no action and does not provoke.'}[feature]
    action_row=ActionDefinition(source_definition_id=feature,display_name=name,owner_id=owner.entity_id,
        economy='NONE',resolution_kind='TYPED',target_kind='SELF',parameters={'description':description})
    return Context(engine,owner,action_row,getattr(engine,'_active_intent',None),
        {'source':feature,'numbers':numbers(engine,owner),'duration':{'kind':'instant'},'effects':[],'riders':[]},[owner],owner,{})


def ally(engine,owner,target):
    from ..relations import relation,ALLY
    return relation(engine,owner,target)==ALLY


def live(engine,owner=None):
    from ..asset_anchor_runtime import members
    return [o for o in members(engine,owner_id=owner.entity_id if owner else None,group=TAG) if not (o.component or {}).get('empowerment_ended') and not (o.component or {}).get('suppressed') and not suppressed(engine,o)
            and (engine.state.round_number,engine.state.current_slot_index)<(int(o.component.get('expires_round',engine.state.round_number+1)),int(o.component.get('expires_slot',0)))]


def fields(engine,actor=None):
    from ..concentration import concentrating_on
    from ..spatial_areas import zone_contains
    return [z for z in placed.of(engine,FIELD) if (engine.state.round_number,engine.state.current_slot_index)<(int(placed.data(z).get('deadline_round',z.created_round+10)),int(placed.data(z).get('deadline_slot',0)))
            and (owner:=engine.state.actors.get(z.owner_id)) is not None and concentrating_on(owner,z.source_definition_id)
            and (actor is None or zone_contains(engine,actor,z))]


def inside(engine,point,zone):
    return 0<=(point.z-zone.center.z)*5<=60 and engine.grid.distance_ft(point.model_copy(update={'z':zone.center.z}),zone.center)<=60


def field_for(engine,owner,actor=None):
    return next((z for z in fields(engine,actor) if z.owner_id==owner.entity_id),None)


def near(engine,target,owner,feet):
    return [o for o in live(engine,owner) if engine._distance_actor_to_cell(target,o.position)<=feet]


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
    from ..senses import perceives_cell
    known=[o for o in options if position_of(o)==ctx.actor.position or perceives_cell(ctx.engine,ctx.actor,position_of(o))]
    chosen=pick(ctx,key,options,labels,subject=subject,optional=optional,automatic_options=known)
    return position_of(chosen[0]) if chosen else None


def create(ctx):
    from ..asset_anchor_runtime import create as asset_create,members
    from ..gate2_runtime_models import Position
    e,a=ctx.engine,ctx.actor
    real=[o for o in e.state.objects.values() if not o.destroyed and e.grid.distance_ft(a.position,o.position)<=30
          and not (o.component or {}).get('asset_anchor_runtime') and not (o.component or {}).get('artifact')]
    from .scoundrel_riders import possessions
    from ..carry import remaining_quantity
    carried=[i for i in possessions(e,a) if remaining_quantity(e,a,i)>0 and not any(i.get(flag) for flag in ('artifact','protected','sealed','fused'))
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
            prompt='Create Guiding Lantern: confirm this actual carried item is eligible. It remains the same item.',expires_on='UNTIL_REMOVED',automatic_options=[])
        if not admitted:
            placed.note(e,ctx.source,a,'No eligibility was declared: the actual item stays unchanged and no Guiding Lantern is created. The accepted Action and 1 Qi remain spent.')
            return
        old=RuntimeObjectState(object_id=key,object_kind='item',owner_id=a.entity_id,position=a.position,unattended=False,
            flammable=True,ac=None,current_hp=None,maximum_hp=None,component={'name':inventory.get('name','Real item')})
        point=a.position
    elif mode=='real':
        oid=pick(ctx,'real_item',[o.object_id for o in real],{o.object_id:(o.component or {}).get('name','Existing item') for o in real})[0]
        old=e.state.objects[oid]
        from ..fact_consent_admission import admit_choice
        admitted=admit_choice(ctx,a,ctx.source,'light_bearing_item',oid,['confirm'],labels={'confirm':'This actual item is a lantern, lamp, candle, torch, brazier or similar light-bearing item'},
            prompt='Create Guiding Lantern: confirm the real item is eligible. It remains this same item.',expires_on='UNTIL_REMOVED',readers=(),automatic_options=[])
        if not admitted:
            placed.note(e,ctx.source,a,'No eligibility was declared: the actual item stays unchanged and no Guiding Lantern is created. The accepted Action and 1 Qi remain spent.')
            return
        point=old.position
    else:
        point=choose_point(ctx,'lantern_location',points(e,a.position,30))
        if point is None:raise ValueError('No Lantern location was chosen.')
    profile={'name':'Guiding Lantern','kind':'guiding_lantern','group':TAG,'ac':13+int(ctx.numbers['pb']),
             'hp':2*int(ctx.numbers['cl']),'source_cl':int(ctx.numbers['cl']),'height_ft':1,'immune':['FIRE','POISON','PSYCHIC'],
             'occupies_space':False,'requires_support':False}
    component={'size':'tiny','blocks':False,'cover':False,'creature':False,'speed_ft':20,'hover':True,'bright_ft':10,'dim_ft':10,
               'condition_immunities':['charmed','frightened','poisoned','prone'],'save_modifier':int(ctx.numbers['pb'])+int(ctx.numbers.get('key_mod') or 0),
               'initiative':'creator','actions':[],'reactions':[],'tether_ft':120,'expires_round':e.state.round_number+4800,'expires_slot':e.state.current_slot_index,
               'plane':(old.component or {}).get('plane','material') if old else 'material','real_item':int(old is not None),**({'item_identity':inventory['object'],'inventory_owner':inventory['object'].split('|',1)[0],
               'item_key':inventory['key'],'carried_by':a.entity_id} if inventory else {})}
    if old:
        from ..asset_anchor_runtime import KEY
        component={**(old.component or {}),**component,'original':old.model_dump(mode='json'),'name':'Guiding Lantern',
            'source_cl':int(ctx.numbers['cl']),'created_by':ctx.source,KEY:{'owner':a.entity_id,'source':ctx.source,'group':TAG,'sequence':e.state.event_sequence+1,'lifetime':'8 hours'}}
        obj=old.model_copy(update={'owner_id':a.entity_id,'object_kind':'guiding_lantern','ac':profile['ac'],'current_hp':profile['hp'],
            'maximum_hp':profile['hp'],'damage_immunities':tuple(dict.fromkeys([*(old.damage_immunities or ()),*profile['immune']])),'component':component})
        e._update_object(obj,ctx.source,a.entity_id)
    else:obj=asset_create(e,a,ctx.source,profile,point,component=component,lifetime='8 hours')
    all_lanterns=[o for o in members(e,owner_id=a.entity_id,group=TAG) if not o.component.get('empowerment_ended')]
    for oldest in sorted(all_lanterns,key=lambda o:o.component['asset_anchor_runtime']['sequence'])[:-int(ctx.numbers['pb'])]:retire(e,oldest,ctx.source)


def retire(engine,obj,source):
    original=(obj.component or {}).get('original')
    if original and not obj.destroyed:
        from ..gate2_runtime_models import RuntimeObjectState
        restored=RuntimeObjectState.model_validate(original).model_copy(update={'position':obj.position,'owner_id':obj.owner_id,
            'component':{**obj.component,**(original.get('component') or {}),'empowerment_ended':1}})
        if type(restored.current_hp) is int:
            restored=restored.model_copy(update={'current_hp':min(restored.current_hp,obj.current_hp)})
        if obj.component.get('item_identity'):
            restored=restored.model_copy(update={'destroyed':bool(obj.component.get('carried_by')),
                'current_hp':0 if obj.component.get('carried_by') else restored.current_hp,'unattended':not bool(obj.component.get('carried_by')),
                'component':{**obj.component,'empowerment_ended':1}})
        engine._update_object(restored,source,obj.owner_id)
    else:
        from ..asset_anchor_runtime import retire as end
        end(engine,obj,source)


def move_lantern(ctx,optional=False):
    ctx=replace(ctx,action=ctx.action.model_copy(update={'display_name':'Move Guiding Lantern'}))
    e,a=ctx.engine,ctx.actor
    if used(e,a,'move_used') or not live(e,a):return
    options=live(e,a)
    from ..senses import perceives_object
    selected=pick(ctx,'moving_lantern',[o.object_id for o in options],{o.object_id:f'Guiding Lantern at ({o.position.x}, {o.position.y}), {o.position.z*5} feet high' for o in options},optional=optional,
        automatic_options=[o.object_id for o in options if perceives_object(e,a,o)])
    if not selected:return
    obj=e.state.objects[selected[0]]
    from .qi_path import armament_condition
    arm=armament_condition(a)
    linked=any(act.owner_id==a.entity_id and act.parameters.get('armament_control_ft')==60 for act in e.action_catalog.values())
    speed=30 if arm and linked and (obj.component or {}).get('domain_armament') else 20
    routes=asset_routes(e,obj.position,speed)
    cells=[p for p in routes if p!=obj.position and any(e.grid.distance_ft(p,q)<=120 for q in [a.position,*[o.position for o in live(e,a) if o.object_id!=obj.object_id]])
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
    from .needle import ai_controlled
    from ..senses import perceives_object,perceives_cell
    automatic=ai_controlled(e,a)
    for first in near(e,a,a,5):
        for second in live(e,a):
            if first is second or e.grid.distance_ft(first.position,second.position)>120 or first.component.get('plane')!=second.component.get('plane'):continue
            if blocked_endpoint(e,first.position) or blocked_endpoint(e,second.position):continue
            for p in points(e,second.position,5):
                if automatic and (p==a.position or not perceives_object(e,a,first) or not perceives_object(e,a,second) or not perceives_cell(e,a,p)):continue
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
    from ..senses import perceives_cell,perceives_object
    selected=pick(ctx,'passage_endpoints_and_arrival',list(keys),labels,automatic_options=[k for k,(f,s,p) in keys.items() if perceives_object(e,a,f) and perceives_object(e,a,s) and perceives_cell(e,a,p)])
    if not selected:return
    first,second,point=keys[selected[0]]
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
    from .effect_durations import round_token
    zone=placed.place(e,a,source=ctx.source,tag=FIELD,cells=[center],name='Ten Thousand Lantern Road',
        placed={'chosen':chosen,'saved':[],'until':round_token(e,10),'deadline_round':e.state.round_number+10,'deadline_slot':e.state.current_slot_index},numbers=ctx.numbers,duration_rounds=None,concentration=True,
        radial_volume=True,shape='cylinder',size_ft=60,extra={'height_ft':60})
    e._start_concentration(a,ctx.source)
    put(ctx,a,'field_used',{'label':'Ten Thousand Lantern Road: used once this scene'})


def no_barrier(e,path):
    from ..gate2_runtime_models import Position
    cells=[p if isinstance(p,Position) else Position.model_validate(p) for p in path]
    crossed={p for p in cells}
    for a,b in zip(cells,cells[1:]):
        crossed.update(Position(x=x,y=y,z=z) for x,y,z in e.grid.effect_ray_cells(a,b))
    return not any(blocked_endpoint(e,p) for p in crossed) and all(e.grid.line_of_physical_transmission(p,q) for p,q in zip(cells,cells[1:])) and not any(
        z.active and (z.trigger_profile.get('spatial_lock') or z.trigger_profile.get('sealed_formation'))
        and any((p.x,p.y,p.z) in {(c.x,c.y,c.z) for c in z.affected_cells} for p in crossed) for z in e.state.zones.values())


def move_ally(ctx,subject,feet,key,*,toward=None):
    from .granted_movement import choices
    e=ctx.engine
    paths=[c for c in choices(e,subject,feet) if c.destination!=subject.position and no_barrier(e,c.canonical_path or [subject.position,c.destination])
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
    targets=[t for t in e.state.actors.values() if t.active and ally(e,a,t) and field_for(e,a,t) is not None]
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
        ctx=replace(ctx,action=ctx.action.model_copy(update={'display_name':'Lantern Road','parameters':{'description':'At the start of your turn, move up to 15 feet toward another connected Lantern without an action or Opportunity Attacks. You must get closer and cannot cross solid barriers, Total Cover, sealed Formations or spatial locks.'}}))
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
    active=[z for z in fields(engine,actor) if (owner:=engine.state.actors.get(z.owner_id)) and ally(engine,owner,actor)]
    if not active:return None
    from ..gate2_runtime_models import Position
    return {(x,y) for y in range(engine.grid.height) for x in range(engine.grid.width)
        if any(inside(engine,Position(x=x,y=y,z=actor.position.z),z) for z in active)}


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
    if amount>0 and holder.actor.active and roll.dc is not None and result.total>=roll.dc:move_ally(context(engine,holder.actor,ROAD),roll.roller,5,'returning_flame_step')


def flame_ai(engine,holder,roll):
    from ..target_knowledge import located
    return located(engine,holder.actor,roll.roller)


register(Rule('lantern_returning_flame','Returning Flame',op='bonus',who='any',when='failed',reaction=True,
    limit='round',costs=((("qi",1),),),finder=flame_holders,guard=flame_guard,
    bonus=lambda e,h,r:int(h.numbers['pb']) if h.actor.active and h.actor.life_state not in ('DYING','STABLE') else 0,after_bonus=flame_after,
    ai=flame_ai,checkpoint='D20_ROLL_BONUS'))


@hook('zero_hp_settled')
def hold_soul(engine,target,damage_source,intent):
    if not any(owned(engine,a,HOLD) for a in engine.state.actors.values()):return None
    from ..pending_damage import current
    from .life_state import massive,is_deceased
    packet=current(engine)
    # Never infer a living body from inactivity or absorb instant-death damage.
    if packet and packet.source_flags&{'instant_death','body_destruction','disintegration','decapitation'}:return None
    if any(r['holder_id']==target.entity_id and set(r['tags'])&{'body_destroyed','instant_death'} for r in information_sources(engine)):return None
    if packet is None or packet.hp_before<=0 or is_deceased(target) or next((int(ev.payload['hp_damage']) for ev in reversed(engine.events) if ev.event_type=='DAMAGE_COMMITTED' and target.entity_id in ev.target_ids),packet.amount)-packet.hp_before>=massive(engine,target):return None
    from ..typed_reactions import can_react
    for owner in engine.state.actors.values():
        if not owned(engine,owner,HOLD) or not ally(engine,owner,target) or not near(engine,target,owner,30):continue
        if (owner.current_hp<=0 and owner.life_state!='CONSCIOUS') or not can_react(engine,owner) or owner.resources.get(QI,0)<4 or any(c.data.get('target')==target.entity_id for c in held(owner,'hold_used')):continue
        ctx=context(engine,owner,HOLD)
        from ..target_knowledge import located
        selected=pick(ctx,'hold_departing_soul',['hold'],{'hold':f'Spend your Reaction and 4 Qi to keep {target.display_name} Unconscious, Stable and Soul-Anchored until the end of your next turn'},optional=True,automatic_options=['hold'] if located(engine,owner,target) else [])
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
    return bool(obj and not obj.destroyed and not (obj.component or {}).get('empowerment_ended') and not (obj.component or {}).get('suppressed') and not suppressed(engine,obj))


@hook('damage_at_zero_failure_allowed')
def anchored_damage(engine,target,source):
    if any(anchor_live(engine,c) for c in held(target,'soul_anchor')):return False
    return None


@hook('effect_subject_allowed')
def soul_protection(ctx,row,subject):
    if not held(subject,'soul_anchor'):return None
    from ..observer_information import source_profile
    profile=source_profile(ctx.engine,ctx.source,row)
    soul_tags={'possession','soul_displacement','soul_capture','soul_consumption','involuntary_soul_movement'}
    if row.get('type') not in soul_tags and not (set(profile.get('tags',[]))&soul_tags) and row.get('condition') not in ('possessed','possession'):return None
    if profile.get('authority') in ('protected','artifact','secret','higher_authority','world_law') or row.get('severs_soul'):return None
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
            if arm and bound and (bound.destroyed or bound.component.get('empowerment_ended')):engine._remove_condition(owner,ARMED,PASSAGE)
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
        if not o.component.get('empowerment_ended') and (engine.state.round_number,engine.state.current_slot_index)>=(int(o.component.get('expires_round',engine.state.round_number+1)),int(o.component.get('expires_slot',0))):retire(engine,o,LIGHT)


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
        from ..observer_information import source_numbers,source_profile
        if source_profile(engine,source,{}).get('authority') in ('protected','artifact','secret','higher_authority','world_law'):return None
        n=source_numbers(engine,source,actor.entity_id if actor else '')
        if n.get('cl') is not None and n['cl']<field.trigger_profile['numbers']['cl']:return 1
    return None


# Native world-owner admission supplies otherwise unknown source facts; it does
# not let a player grant their own anatomy, spirit tags or teleport authority.
WORLD_TAGS={'spirit','incorporeal','possessing_entity','possession','visual_illusion','concealed_path','concealed_door','concealed_portal','formation_boundary','invisible','sealed_formation','spatial_lock','teleport_block','artifact_prison','body_destroyed','instant_death','asset_suppression'}|GUIDANCE|FIELD_SAVES


@hook('fact_admission_schema')
def lantern_schema(session,source,subject,kind):
    if source!=PARENT:return None
    if kind=='light_bearing_item':return {'value_type':'flag','maximum_seconds':28800,'description':'The subject identifies this exact actual item as a lantern, lamp, candle, torch, brazier or similar light-bearing item.'}
    if kind=='willing_traveler':return {'value_type':'flag','maximum_seconds':60,'description':'The subject personally agrees to this exact source-scoped travel declaration.'}
    if kind=='external_source':return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
        'description':'Record an actual external source, its explicit tags, CL, DC, plane, geometry and authority. Names do not establish these facts.'}
    return None


def sync_journey(session,aid):
    from ..canonical import canonical_sha256
    actor=session.state['actors'][aid];ledger=actor.get('source_states',{}).get(PARENT)
    if not ledger:return
    ledger['clock']=int(session.clock());ledger['journey']=session.state['journey_id']
    bundle=actor['bundle']
    bundle['lantern_keeper_state']=canonical({'state':ledger,'clock':int(session.clock()),'scene':session.state.get('scene_id') or session.state['journey_id']})
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


@hook('journey_initialize')
def initialize_journey(session,aid):
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT)
    if ledger and ledger.get('journey') and ledger['journey']!=session.state['journey_id']:
        previous=int(ledger.get('clock',0));now=int(session.clock())
        rows=json.loads(ledger.get('objects','[]'))
        for row in rows:
            if 'expires_at' in row.get('component',{}):row['component']['expires_at']=now+max(0,row['component']['expires_at']-previous)
        ledger['objects']=canonical(rows)
        sources=json.loads(ledger.get('external_sources','{}'))
        for entry in sources.values():entry['expires_at']=now+max(0,entry['expires_at']-previous)
        ledger['external_sources']=canonical(sources)
        field=json.loads(ledger.get('field','{}'))
        if field:
            field['expires_at']=now+max(0,field['expires_at']-previous)
            ledger['field']=canonical(field);ledger['field_until']=field['expires_at']
        if 'anchor_until' in ledger:ledger['anchor_until']=now+max(0,ledger['anchor_until']-previous)
    sync_journey(session,aid)


@hook('journey_acquired')
def acquired_journey(session,aid,source,receipt):
    if source==PARENT:sync_journey(session,aid)


@hook('journey_state_changed')
def update_journey(session,aid):
    if session.state['actors'][aid]['incapacitated']:
        ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT,{})
        ledger.pop('field',None)
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT)
    if ledger:
        rows=json.loads(ledger.get('objects','[]'))
        for row in rows:
            carrier=session.state['actors'].get(row.get('component',{}).get('carried_by'))
            if carrier and not row.get('destroyed',False):
                row['position']=dict(carrier['position']);session.state.setdefault('runtime_objects',{})[row['object_id']]=row
        ledger['objects']=canonical(rows)
    sync_journey(session,aid)


def journey_retire_record(row):
    component=row.get('component') or {}
    original=component.get('original')
    if original and not row.get('destroyed',False):
        old=deepcopy(original);old.update(position=row['position'],owner_id=row.get('owner_id'))
        if type(old.get('current_hp')) is int:old['current_hp']=min(old['current_hp'],row.get('current_hp',old['current_hp']))
        old['component']={**component,**old.get('component',{}),'empowerment_ended':1}
        if component.get('carried_by'):old.update(destroyed=True,current_hp=0)
        row.clear();row.update(old)
    else:row.update(destroyed=True,current_hp=0)


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT)
    if not ledger:return
    rows=json.loads(ledger.get('objects','[]'))
    now=int(session.clock())
    for row in rows:
        c=row.get('component') or {}
        if c.get('expires_at',now+1)<=now and not c.get('empowerment_ended') and not row.get('destroyed',False):
            journey_retire_record(row)
            session.state.setdefault('runtime_objects',{})[row['object_id']]=row
            session.emit('LANTERN_EMPOWERMENT_ENDED',aid,source=LIGHT,object_id=row['object_id'])
    ledger['objects']=canonical(rows)
    if ledger.get('field_until',0)<=now:ledger.pop('field',None)
    if ledger.get('anchors') and ledger.get('anchor_until',0)<=now:
        ledger.pop('anchors',None);ledger.pop('anchor_until',None)
        snapshot=session.state['actors'][aid].get('encounter_snapshot')
        if snapshot and snapshot['current_hp']==0 and snapshot['life_state']=='STABLE':snapshot['life_state']='DYING'
        session.emit('LANTERN_SOUL_ANCHOR_ENDED',aid,source=HOLD)
    sync_journey(session,aid)


@hook('journey_scene_end')
def new_scene(session,previous,current):
    for aid,actor in session.state['actors'].items():
        ledger=actor.get('source_states',{}).get(PARENT)
        if ledger:
            ledger['scene']=current;ledger.pop('scene_limits',None);ledger.pop('revelation_locks',None);ledger.pop('revelation_results',None);ledger.pop('scene_allies',None)
            sync_journey(session,aid)


def journey_spend_qi(session,aid,amount,source):
    """Source command settlement after legal declarations, before benefits."""
    actor=session.state['actors'][aid]
    from ..journey import require
    require(actor['resources'].get(QI,0)>=amount,f'This Lantern Keeper activation costs {amount} Qi.')
    actor['resources'][QI]-=amount
    if actor['resources'][QI]==0:
        from .forged_exhaustion import add_journey
        add_journey(session,aid,1,source,allow_death=True)
    session.emit('LANTERN_QI_SPENT',aid,source=source,amount=amount,remaining=actor['resources'][QI])
    if actor['incapacitated']:
        session.tick(6);sync_journey(session,aid)
        return False
    return True


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
        require(set(v) in ({'source_rule','tags','source_cl','save_dc','position','plane','authority','duration_seconds'},{'source_rule','tags','source_cl','save_dc','position','plane','authority','duration_seconds','resolution'}),'Record all external source profile fields.')
        if 'resolution' in v:
            r=v['resolution']
            require(isinstance(r,dict) and set(r)=={'name','kind','ability','skill','subjects'} and r['kind'] in ('save','check') and r['ability'] in ('STR','DEX','CON','INT','WIS','CHA')
                and type(r['name']) is str and 0<len(r['name'])<=120 and type(r['skill']) is str and len(r['skill'])<=60
                and isinstance(r['subjects'],list) and len(set(r['subjects']))==len(r['subjects']) and set(r['subjects'])<=set(session.state['actors']),'Record the actual named source’s save/check, ability, skill and affected subjects.')
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
    active=[r for r in rows if not r.get('destroyed',False) and not r['component'].get('empowerment_ended') and r['component'].get('expires_at',0)>now]
    n=next(r['numbers'] for r in actor['bundle']['typed_passives'] if r.get('block')=='lantern_keeper')
    owner_point=Position.model_validate(actor['position'])
    if kind=='lantern_create':
        require(set(payload) in ({'position'},{'item_id','eligibility_scope'}),'Choose a projected Lantern position or one actual eligible light-bearing item.')
        from ..journey_assets import JourneyAssetContext
        e=JourneyAssetContext(session);owner=e.state.actors[aid];old=None;inventory=None
        if 'item_id' in payload:
            from ..fact_consent_admission import read
            fact=read(session,PARENT,aid,'light_bearing_item',payload['eligibility_scope'],aid)
            require(payload['eligibility_scope']==payload['item_id'] and fact is not None and fact['value']==1,'Identify this exact actual light-bearing item before empowerment.')
            from .scoundrel_riders import journey_inventory_context,possessions
            inventory_context=journey_inventory_context(session)
            from ..carry import remaining_quantity
            inventory=next((i for i in possessions(inventory_context,inventory_context.state.actors[aid]) if i['object']==payload['item_id'] and remaining_quantity(inventory_context,inventory_context.state.actors[aid],i)>0),None)
            old=e.state.objects.get(payload['item_id'])
            require(not old or old.destroyed or not (old.component or {}).get('asset_anchor_runtime'),'This actual item is already empowered.')
            if inventory:
                require(not any(inventory.get(flag) for flag in ('artifact','protected','sealed','fused')),'Resolve this actual item’s protected control before empowerment.')
                old=RuntimeObjectState(object_id=inventory['object'],object_kind='item',owner_id=aid,position=owner_point,
                    unattended=False,flammable=True,component={'name':inventory.get('name','Real item')})
            require(old is not None and not old.destroyed and not old.component.get('artifact'),'Choose one existing accessible nonartifact light-bearing item.')
            point=old.position
        else:point=Position.model_validate(payload['position'])
        require(session.grid.distance_ft(owner_point,point)<=30 and session.grid.volume_legal(point),'Choose a legal Lantern point within 30 feet.')
        require(actor['resources'].get(QI,0)>=1,'Create Guiding Lantern costs 1 Qi.')
        from ..journey_assets import JourneyAssetContext
        from ..asset_anchor_runtime import create as asset_create
        if not journey_spend_qi(session,aid,1,LIGHT):return True
        profile={'name':'Guiding Lantern','kind':'guiding_lantern','group':TAG,'ac':13+int(n['pb']),
            'hp':2*int(n['cl']),'source_cl':int(n['cl']),'height_ft':1,'immune':['FIRE','POISON','PSYCHIC'],
            'occupies_space':False,'requires_support':False}
        component={'size':'tiny','blocks':False,'cover':False,'creature':False,'speed_ft':20,'hover':True,'bright_ft':10,'dim_ft':10,
            'condition_immunities':['charmed','frightened','poisoned','prone'],'save_modifier':int(n['pb'])+int(n.get('key_mod') or 0),
            'initiative':'creator','actions':[],'reactions':[],'tether_ft':120,'expires_at':now+28800,'plane':'material','real_item':int(old is not None)}
        if old:
            from ..asset_anchor_runtime import KEY
            component={**old.component,**component,'original':old.model_dump(mode='json'),'created_by':LIGHT,'source_cl':int(n['cl']),
                KEY:{'owner':aid,'source':LIGHT,'group':TAG,'sequence':len(session.state['events'])+1,'lifetime':'8 hours'}}
            if inventory:component.update(item_identity=inventory['object'],inventory_owner=aid,item_key=inventory['key'],carried_by=aid)
            obj=old.model_copy(update={'owner_id':aid,'object_kind':'guiding_lantern','component':component,
                'ac':profile['ac'],'current_hp':profile['hp'],'maximum_hp':profile['hp'],
                'damage_immunities':tuple(dict.fromkeys([*(old.damage_immunities or ()),*profile['immune']]))})
            e._update_object(obj,LIGHT,aid)
        else:obj=asset_create(e,owner,LIGHT,profile,point,component=component,lifetime='8 hours')
        rows.append(obj.model_dump(mode='json'))
        for oldest in sorted(active+[rows[-1]],key=lambda r:r['component']['asset_anchor_runtime']['sequence'])[:-int(n['pb'])]:journey_retire_record(oldest)
        session.tick(6)
    elif kind=='lantern_move':
        require(set(payload)=={'object_id','position'},'Choose your exact Lantern and destination.')
        obj=next((o for o in active if o['object_id']==payload['object_id']),None)
        require(obj is not None and not journey_suppressed(session,obj),'Only your active unsuppressed Guiding Lantern can be moved.')
        from ..journey_assets import JourneyAssetContext
        point=Position.model_validate(payload['position']);old=Position.model_validate(obj['position'])
        require(asset_path(JourneyAssetContext(session),old,point,20) is not None,'Move the Lantern at most 20 feet through a legal flight route.')
        require(any(session.grid.distance_ft(point,p)<=120 for p in [owner_point,*[Position.model_validate(o['position']) for o in active if o is not obj]]),'Keep the Lantern within 120 feet of you or another Lantern.')
        if obj['component'].get('item_identity'):
            from .scoundrel_riders import relocate_journey_possession
            from ..journey_assets import JourneyAssetContext
            route=asset_path(JourneyAssetContext(session),old,point,20)
            require(route is not None and relocate_journey_possession(session,aid,obj['component']['item_identity'],route,LIGHT),'The actual item has no legal source-authorized custody route.')
            obj['component']['carried_by']=''
        obj['position']=point.model_dump(mode='json');session.tick(6)
    else:
        require(any(r.get('feature_id')==PASSAGE for r in actor['bundle']['typed_passives']),'Acquire Lantern Passage first.')
        base_keys={'first','second','position'};carry_keys={'traveler','traveler_arrival','consent_scope'}
        require(set(payload) in (base_keys,base_keys|carry_keys),'Declare both Lanterns, arrival and any one consenting traveler before travel.')
        first=next((o for o in active if o['object_id']==payload['first']),None);second=next((o for o in active if o['object_id']==payload['second']),None)
        require(first and second and first is not second,'Choose two of your active Lanterns.')
        p,q=Position.model_validate(first['position']),Position.model_validate(second['position']);arrival=Position.model_validate(payload['position'])
        require(session.grid.distance_ft(owner_point,p)<=5 and session.grid.distance_ft(p,q)<=120 and session.grid.distance_ft(q,arrival)<=5,'Respect Lantern Passage boarding, connection and arrival ranges.')
        require(not journey_suppressed(session,first) and not journey_suppressed(session,second) and first['component']['plane']==second['component']['plane'],'Suppressed Lanterns or different planes block passage.')
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
        if not journey_spend_qi(session,aid,cost,PASSAGE):return True
        actor['position']=arrival.model_dump(mode='json')
        if traveler is not None:traveler['position']=traveler_arrival.model_dump(mode='json')
        session.tick(6)
        session.emit('LANTERN_PASSAGE_COMMITTED',aid,source=PASSAGE,first=first['object_id'],second=second['object_id'],destination=actor['position'],qi_spent=cost)
    ledger['objects']=canonical(rows)
    for raw in rows:session.state.setdefault('runtime_objects',{})[raw['object_id']]=raw
    elapsed(session,aid,session.clock(),0,())
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
                if not obj.destroyed and not obj.component.get('empowerment_ended') and obj.component.get('expires_at',clock+1)<=clock:
                    obj=obj.model_copy(update={'destroyed':True,'current_hp':0,'component':{**obj.component,**({'empowerment_ended':1} if obj.component.get('carried_by') else {})}})
                c={**obj.component,'expires_round':engine.state.round_number+max(1,(obj.component.get('expires_at',clock)-clock+5)//6),'expires_slot':engine.state.current_slot_index}
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
            from .effect_durations import round_token
            remaining=max(1,(saved_field['expires_at']-clock+5)//6)
            placed.place(engine,owner,source=source,tag=FIELD,cells=[Position.model_validate(saved_field['center'])],name='Ten Thousand Lantern Road',
                placed={'chosen':saved_field['chosen'],'saved':saved_field.get('saved',[]),'activation_id':saved_field.get('activation_id',''),'until':round_token(engine,remaining),'deadline_round':engine.state.round_number+remaining,'deadline_slot':engine.state.current_slot_index},numbers=saved_field['numbers'],
                duration_rounds=None,concentration=True,radial_volume=True,
                shape='cylinder',size_ft=60,extra={'height_ft':60})
        for key,entry in json.loads(ledger.get('external_sources','{}')).items():
            if entry['expires_at']<=clock:continue
            from .effect_durations import round_token
            engine._apply_condition(owner,C+'world_challenge' if entry.get('resolution') else 'condition:information.source',entry['source_rule'],owner.entity_id,
                expires_on=round_token(engine,max(1,(entry['expires_at']-clock+5)//6)),data={
                ('world_profile' if entry.get('resolution') else 'information_profile'):{'tags':entry['tags'],'source_cl':entry['source_cl'],'save_dc':entry['save_dc'],'authority':entry['authority'],
                    'position':entry['position'],'plane':entry['plane']},**({'world_resolution':entry['resolution']} if entry.get('resolution') else {}),'world_receipt':entry['receipt'],'label':'Source-scoped external world effect'})

    for bundle in getattr(engine,'typed_bundle_documents',()):
        if not bundle.get('lantern_keeper_state'):continue
        saved=json.loads(bundle['lantern_keeper_state']);ledger=saved['state']
        target=engine.state.actors[bundle['actor_id']]
        if ledger.get('anchor_until',0)>saved['clock']:
            for raw in json.loads(ledger.get('anchors','[]')):
                owner=engine.state.actors.get(raw['source_actor_id'])
                if owner is None:continue
                from .effect_durations import token
                c=raw['data'];obj=engine.state.objects.get(c['anchor_id'])
                if obj and not obj.destroyed and not obj.component.get('empowerment_ended') and not suppressed(engine,obj):
                    put(context(engine,owner,HOLD),target,'soul_anchor',c,token('end',owner.entity_id,owner.turns_started+1))
                elif target.current_hp==0 and target.life_state=='STABLE':engine._set_life_state(target,'DYING',HOLD)


@hook('journey_encounter_settled')
def export_journey(session,aid,engine,actor):
    ledger=session.state['actors'][aid].get('source_states',{}).get(PARENT)
    anchors=held(actor,'soul_anchor')
    if not ledger and not anchors:return
    ledger=state(session,aid)
    now=int(session.clock());rows=[]
    if anchors:
        ledger['anchors']=canonical([c.model_dump(mode='json') for c in anchors]);ledger['anchor_until']=now+6
    else:ledger.pop('anchors',None);ledger.pop('anchor_until',None)
    entries=json.loads(ledger.get('external_sources','{}'))
    if entries:ledger['external_sources']=canonical(entries)
    if not owned(engine,actor,LIGHT):
        sync_journey(session,aid);return
    ledger['scene_allies']=canonical([a.entity_id for a in engine.state.actors.values() if ally(engine,actor,a)])
    for obj in engine.state.objects.values():
        if obj.owner_id!=aid or not (obj.component or {}).get('asset_anchor_runtime') or obj.component['asset_anchor_runtime']['group']!=TAG:continue
        c={**obj.component,'expires_at':now+max(0,int(obj.component['expires_round'])-engine.state.round_number)*6}
        rows.append(obj.model_copy(update={'component':c}).model_dump(mode='json'))
    ledger['objects']=canonical(rows)
    zone=field_for(engine,actor)
    if zone:
        field={'center':zone.center.model_dump(mode='json'),'chosen':placed.data(zone)['chosen'],'saved':placed.data(zone).get('saved',[]),
            'numbers':zone.trigger_profile['numbers'],'source':TEN,
            'expires_at':now+max(0,int(placed.data(zone).get('deadline_round',zone.created_round+10))-engine.state.round_number)*6,
            'activation_id':placed.data(zone).get('activation_id') or zone.zone_id}
        ledger['field']=canonical(field);ledger['field_until']=field['expires_at']
    else:ledger.pop('field',None)
    ledger['revelation_results']=canonical([c.model_dump(mode='json') for c in held(actor,'revelation_result')])
    ledger['scene_limits']=canonical([c.model_dump(mode='json') for c in actor.conditions.values() if c.condition_id in (C+'field_used',C+'hold_used')])
    sync_journey(session,aid)


@hook('journey_snapshot_actor')
def snapshot_without_source_limits(actor,session,aid,engine):
    own_world={i for i,c in actor.conditions.items() if c.condition_id in ('condition:information.source',C+'world_challenge') and c.data.get('world_receipt')}
    if not owned(engine,actor,LIGHT) and not own_world and not held(actor,'soul_anchor'):return None
    conditions={i:c for i,c in actor.conditions.items() if i not in own_world and c.condition_id not in (C+'field_used',C+'hold_used',C+'move_used',C+'passage_used',C+'guide_used',C+'revelation_result',C+'soul_anchor')}
    own_source={z.source_definition_id for z in placed.of(engine,FIELD,owner_id=aid)}
    return actor.model_copy(update={'conditions':conditions,**({'concentration':None} if actor.concentration and actor.concentration.source_definition_id in own_source else {})})


def information_sources(engine):
    from ..read_queries import memo
    return memo(engine,('lantern_keeper_native_sources',),lambda:derive_information_sources(engine))


def derive_information_sources(engine):
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
    if _TRACE_VIEW.get() or not viewer.active or viewer.life_state in ('DYING','STABLE'):return False
    token=_TRACE_VIEW.set(True)
    try:return senses.perceives_cell(engine,viewer,point)
    finally:_TRACE_VIEW.reset(token)


def revelations(engine,viewer):
    """Pure visible output; failure checks are resolved once at a native intent."""
    out=[]
    for owner in engine.state.actors.values():
        if not owned(engine,owner,LIGHT):continue
        lamps=live(engine,owner);zone=field_for(engine,owner)
        if not lamps and zone is None:continue
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
            if not set(row['tags'])&{'invisible','possession','possessing_entity','visual_illusion','concealed_path','concealed_door','concealed_portal','formation_boundary'}:continue
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
    from ..senses import is_creature
    if not is_creature(target) or not hasattr(target,'conditions') or not fields(engine):return None
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
                    if not (dx or dy or dz) or point.z+dz<0 or not engine.grid.in_bounds((point.x+dx,point.y+dy)):continue
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
    return 0 if any(o.destroyed and (o.component or {}).get('asset_anchor_runtime',{}).get('group')==TAG and not (o.component or {}).get('empowerment_ended') and (o.component or {}).get('item_identity')==(item.get('object') or actor.entity_id+'|'+item.get('key',''))
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
        require(isinstance(payload['chosen'],list) and len(set(payload['chosen']))==len(payload['chosen']) and set(payload['chosen'])<=journey_allies(session,aid),'Choose distinct present creatures for protection.')
        require(actor['resources'].get(QI,0)>=8,'Ten Thousand Lantern Road costs 8 Qi.')
        if not journey_spend_qi(session,aid,8,TEN):return True
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
        target=session.state['actors'].get(payload['traveler']);require(target is not None and payload['traveler'] in journey_allies(session,aid),'Choose an actual present ally; the world owner can record travel allies.')
        origin=Position.model_validate(target['position']);point=Position.model_validate(payload['position']);center=Position.model_validate(field['center'])
        require(0<=(origin.z-center.z)*5<=60 and session.grid.distance_ft(origin.model_copy(update={'z':center.z}),center)<=60,'The traveler must start inside your field.')
        from ..fact_consent_admission import read,digest
        expected=digest({'keeper':aid,'traveler':payload['traveler'],'position':payload['position'],'teleport':int(payload['teleport'])})
        require(payload['consent_scope']==expected,'Consent must name this exact keeper, traveler, destination and method.')
        consent=read(session,PARENT,payload['traveler'],'willing_traveler',expected,aid)
        require(consent is not None and consent['value']==1,'The traveler must personally declare willingness to this exact travel.')
        require(session.grid.distance_ft(origin,point)<=30,'Guide the traveler up to 30 feet.')
        if payload['teleport']:require(session.grid.line_of_physical_transmission(origin,point),'Teleportation cannot cross a solid barrier or Total Cover.')
        e=JourneyAssetContext(session)
        require(e.grid.placement_legal(point,footprint=e._footprint(payload['traveler']),occupied_cells={(a.position.x,a.position.y) for a in e.state.actors.values() if a.entity_id!=payload['traveler']}),'Choose a legal unoccupied arrival.')
        sources=[v for a in session.state['actors'].values() for v in json.loads(a.get('source_states',{}).get(PARENT,{}).get('external_sources','{}')).values() if v['expires_at']>now]
        require(not any(set(v['tags'])&{'spatial_lock','sealed_formation','teleport_block','artifact_prison'} and Position.model_validate(v['position']) in (origin,point) for v in sources),'A sealed boundary blocks this travel.')
        if payload['teleport']:
            require(actor['resources'].get(QI,0)>=1,'Teleporting the traveler costs 1 Qi.')
            if not journey_spend_qi(session,aid,1,TEN):return True
        else:
            # Native journey movement validates each traversed edge, terrain and
            # occupancy. The free grant changes no ordinary travel resource.
            require(journey_walk_path(session,payload['traveler'],point,30) is not None,'No legal thirty-foot physical route exists.')
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


@hook('condition_application_attempt')
def anchored_native_possession(engine,subject,condition_id,source,owner_id):
    if not held(subject,'soul_anchor'):return None
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
    names={C+s for s in ('move_used','passage_used','guide_used','road_used','field_used','hold_used','revelation_result','hazard_used','world_challenge','world_hazard_outcome')}
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in names]


@hook('event',nested=True)
def real_lantern_custody(engine,kind,kwargs):
    if kind not in ('CONDITION_REMOVED','CONDITION_APPLIED'):return
    from ..asset_anchor_runtime import members
    from .scoundrel_riders import possession_position
    for obj in list(members(engine,group=TAG)):
        identity=obj.component.get('item_identity')
        if not identity or obj.component.get('empowerment_ended'):continue
        actual=possession_position(engine,identity)
        if actual:
            carrier,point=actual
            if obj.component.get('carried_by')!=carrier or obj.position!=point:
                engine._update_object(obj.model_copy(update={'position':point,
                    'component':{**obj.component,'carried_by':carrier}}),LIGHT,obj.owner_id)


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
        session.tick(3600);gain=int(next(r['numbers']['cl'] for r in actor['bundle']['typed_passives'] if r.get('block')=='lantern_keeper'))
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


@hook('placed_deadline_expiring')
def field_duration_ends_concentration(engine,zone):
    if placed.data(zone).get('tag')!=FIELD:return
    owner=engine.state.actors.get(zone.owner_id)
    if owner and owner.concentration and owner.concentration.source_definition_id==zone.source_definition_id:
        engine._end_concentration(owner,'DURATION_ENDED')


def world_hazards(engine,subject):
    """Only authenticated native world-source declarations supply a challenge."""
    for holder in engine.state.actors.values():
        for c in holder.conditions.values():
            r=c.data.get('world_resolution')
            receipt=c.data.get('world_receipt')
            if c.condition_id in ('condition:information.source',C+'world_challenge') and receipt and isinstance(r,dict) and subject.entity_id in r['subjects']:
                if not any(u.data.get('receipt')==receipt for u in held(subject,'hazard_used')):
                    yield holder,c,r


def external_source_definitions(engine,actor):
    if not any(owned(engine,a,LIGHT) for a in engine.state.actors.values()):return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f'action:lantern-source:{c.data["world_receipt"]}:{actor.entity_id}',
        display_name='Face '+r['name'],owner_id=actor.entity_id,economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'free_primary':True,'description':f'{actor.display_name}: resolve {r["name"]} with the actual source’s {r["ability"]} {r["kind"]}; no action or Qi. One attempt for this source instance.',
            'typed':{'source':c.source_definition_id,'numbers':{'cl':(c.data.get('world_profile') or c.data['information_profile'])['source_cl'],'save_dc':(c.data.get('world_profile') or c.data['information_profile'])['save_dc']},'duration':{'kind':'instant'},'riders':[],
                'effects':[{'type':'lantern_world_hazard','instance':c.instance_id,'holder':holder.entity_id}]}})
        for holder,c,r in world_hazards(engine,actor)] or None


@hook('match_start',priority=100)
def install_external_source_challenges(engine):
    for actor in engine.state.actors.values():
        for action in external_source_definitions(engine,actor) or []:
            engine.action_catalog[action.source_definition_id]=action


@hook('additional_actions')
def external_source_challenges(engine,actor):
    return [a.source_definition_id for a in external_source_definitions(engine,actor) or []
            if a.source_definition_id in engine.action_catalog] or None


@effect('lantern_world_hazard',harmful=False)
def face_world_hazard(ctx,row):
    match=next(((holder,c,r) for holder,c,r in world_hazards(ctx.engine,ctx.actor)
        if c.instance_id==row['instance'] and holder.entity_id==row['holder']),None)
    if match is None:raise ValueError('This native external source no longer offers that unresolved challenge.')
    holder,c,r=match;e=ctx.engine;a=ctx.actor;profile=c.data.get('world_profile') or c.data['information_profile'];dc=profile['save_dc']
    if r['kind']=='save':
        roll=e._roll_save(a,r['ability'],dc,ctx.source,roll_context={'source_actor_id':holder.entity_id,'named':profile['tags']})
        if roll is None:return
    else:
        from ..ability_checks import ordinary_check_bonus
        from .needle import numbers_of
        bundle=next((b for b in getattr(e,'typed_bundle_documents',()) if b.get('actor_id')==a.entity_id),{})
        bonus=ordinary_check_bonus(e,a,r['ability'],r['skill'],numbers={**numbers_of(e,a),'ability_mods':bundle.get('ability_mods',{})})
        if bonus is None:raise ValueError('This creature’s native sheet must record the required ability or skill modifier.')
        with e.d20_scope({'kind':'check','actor_id':a.entity_id,'target_id':a.entity_id,'ability':r['ability'],
                'skill':r['skill'],'dc':dc,'source_id':ctx.source,'source_actor_id':holder.entity_id,'named':profile['tags']}):
            roll=e.roll_check(modifier=bonus,actor_id=a.entity_id,reason='CHECK:'+ctx.source,
                ability=r['ability'],skill=r['skill'] or None,hazards=tuple(profile['tags']))
        e._record_roll(roll)
        e._append_event('CHECK_ROLLED',ctx.source,actor_id=a.entity_id,payload={**roll.model_dump(mode='json'),
            'ability':r['ability'],'skill':r['skill'],'dc':dc,'success':roll.total>=dc,'name':r['name']})
    if roll.total<dc:
        e._apply_condition(a,C+'world_hazard_outcome',ctx.source,holder.entity_id,expires_on=c.expires_on,
            data={'information_profile':profile,'world_receipt':c.data['world_receipt'],'label':f'{r["name"]}: failed {r["kind"]}'})
    put(ctx,a,'hazard_used',{'receipt':c.data['world_receipt'],'label':f'{r["name"]}: source instance resolved'})
    placed.note(e,ctx.source,a,f'{a.display_name} {"succeeds" if roll.total>=dc else "fails"} against {r["name"]}.')


@hook('observer_source_profile')
def actual_world_challenge_profile(engine,source,data):
    action=engine.action_catalog.get(source)
    rows=(action.parameters.get('typed') or {}).get('effects',[]) if action else []
    row=next((r for r in rows if r.get('type')=='lantern_world_hazard'),None)
    if not row:return None
    holder=engine.state.actors.get(row['holder'])
    c=holder.conditions.get(row['instance']) if holder else None
    if c and c.data.get('world_receipt'):
        return dict(c.data.get('world_profile') or c.data['information_profile'])
    return None


@hook('fact_admission_schema')
def travel_allies_schema(session,source,subject,kind):
    if source==PARENT and kind=='travel_allies':
        return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
            'description':'Record the Keeper’s actual current allies for elapsed-time Lantern travel. Alliance never grants willingness.'}
    return None


def journey_allies(session,keeper):
    from ..fact_consent_admission import read
    result={keeper,*json.loads(session.state['actors'][keeper].get('source_states',{}).get(PARENT,{}).get('scene_allies','[]'))}
    fact=read(session,PARENT,keeper,'travel_allies',keeper,keeper)
    if fact:
        value=fact['value']
        if isinstance(value,dict) and set(value)=={'allies'} and isinstance(value['allies'],list) and all(isinstance(a,str) for a in value['allies']):
            result.update(set(value['allies'])&set(session.state['actors']))
    return result


def journey_sources(session):
    now=int(session.clock())
    return [v for a in session.state['actors'].values() for v in json.loads(a.get('source_states',{}).get(PARENT,{}).get('external_sources','{}')).values() if v['expires_at']>now]


def journey_suppressed(session,row):
    from ..gate2_runtime_models import Position
    return bool(row.get('component',{}).get('suppressed') or any('asset_suppression' in v['tags'] and
        Position.model_validate(v['position'])==Position.model_validate(row['position']) and
        v['plane']==row['component'].get('plane','material') for v in journey_sources(session)))


@hook('journey_step')
def field_journey_terrain(session,aid,previous,destination,regions):
    from ..gate2_runtime_models import Position
    now=int(session.clock())
    for keeper,actor in session.state['actors'].items():
        field=json.loads(actor.get('source_states',{}).get(PARENT,{}).get('field','{}'))
        if not field or field.get('expires_at',0)<=now or aid not in journey_allies(session,keeper):continue
        center=Position.model_validate(field['center'])
        if 0<=(destination.z-center.z)*5<=60 and session.grid.distance_ft(destination.model_copy(update={'z':center.z}),center)<=60:
            return {'ignore_difficult_terrain':True}
    return None


def journey_walk_path(session,aid,destination,feet):
    """Source grant over native journey steps; barriers stay authoritative."""
    import heapq
    from ..gate2_runtime_models import Position
    origin=Position.model_validate(session.state['actors'][aid]['position'])
    best={origin:0};paths={origin:(origin,)};queue=[(0,0,origin)];sequence=0
    locks={Position.model_validate(v['position']) for v in journey_sources(session) if set(v['tags'])&{'spatial_lock','sealed_formation'}}
    while queue:
        cost,_,point=heapq.heappop(queue)
        if cost!=best[point]:continue
        if point==destination:return paths[point]
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    if not (dx or dy or dz) or point.z+dz<0 or not session.grid.in_bounds((point.x+dx,point.y+dy)):continue
                    nxt=Position(x=point.x+dx,y=point.y+dy,z=point.z+dz)
                    if point in locks or nxt in locks:continue
                    try:multiplier=session.step_profile(aid,point,nxt)
                    except ValueError:continue
                    total=cost+session.grid.distance_ft(point,nxt)*multiplier
                    if total>feet or total>=best.get(nxt,feet+1):continue
                    best[nxt]=total;paths[nxt]=(*paths[point],nxt);sequence+=1;heapq.heappush(queue,(total,sequence,nxt))
    return None


@hook('journey_command')
def journey_road_step(session,aid,kind,payload):
    if kind!='lantern_road_step':return None
    from ..journey import require
    from ..gate2_runtime_models import Position
    require(set(payload)=={'keeper','first','second','position'},'Declare the Keeper, connected Lanterns and arrival.')
    keeper=payload['keeper'];require(keeper in session.state['actors'] and aid in journey_allies(session,keeper),'Only an actual ally may use the Lantern Road.')
    actor=session.state['actors'][aid];owner=session.state['actors'][keeper]
    require(not actor['incapacitated'],'An incapacitated traveler cannot take this voluntary movement.')
    require(any(r.get('block')=='lantern_keeper' and r['feature_id']==ROAD for r in owner['bundle']['typed_passives']),'The Keeper must have acquired Lantern Road.')
    ledger=owner.get('source_states',{}).get(PARENT,{})
    live_rows=[r for r in json.loads(ledger.get('objects','[]')) if not r.get('destroyed',False) and not r['component'].get('empowerment_ended') and r['component']['expires_at']>int(session.clock()) and not journey_suppressed(session,r)]
    first=next((r for r in live_rows if r['object_id']==payload['first']),None);second=next((r for r in live_rows if r['object_id']==payload['second']),None)
    require(first is not None and second is not None and first is not second,'Choose two distinct live connected Lanterns.')
    p,q=Position.model_validate(first['position']),Position.model_validate(second['position']);origin=Position.model_validate(actor['position']);destination=Position.model_validate(payload['position'])
    field=json.loads(ledger.get('field','{}'));center=Position.model_validate(field['center']) if field else None
    field_connected=field.get('expires_at',0)>int(session.clock()) and all(0<=(v.z-center.z)*5<=60 and session.grid.distance_ft(v.model_copy(update={'z':center.z}),center)<=60 for v in (p,q))
    require(session.grid.distance_ft(p,q)<=60 or field_connected,'These Lanterns are not connected.')
    require(session.grid.distance_ft(origin,p)<=10 and session.grid.distance_ft(destination,q)<session.grid.distance_ft(origin,q),'Start within 10 feet of one Lantern and move closer to the other.')
    require(journey_walk_path(session,aid,destination,15) is not None,'Choose a legal fifteen-foot road route without barriers or locks.')
    actor['position']=destination.model_dump(mode='json');session.tick(6)
    from . import run_strict
    for other in session.state['actors']:run_strict('journey_state_changed',session,other)
    session.emit('LANTERN_ROAD_MOVEMENT',aid,source=ROAD,keeper=keeper,first=first['object_id'],second=second['object_id'],position=actor['position'])
    return True


@hook('journey_options')
def journey_lantern_options(session,aid):
    if session.state['phase']!='travel':return None
    actor=session.state['actors'][aid]
    if actor['incapacitated']:return None
    rows=actor['bundle']['typed_passives'];owned_features={r['feature_id'] for r in rows if r.get('block')=='lantern_keeper'}
    if LIGHT not in owned_features:return None
    options=[]
    def offer(kind,payload,text):
        options.append({'id':kind+':'+str(len(options)),'kind':kind,'payload':payload,'label':actor['name']+': '+text,'auto_select':0})
    if actor['resources'].get(QI,0)>=1:
        offer('lantern_create',{'position':actor['position']},'Create a Guiding Lantern here for 1 Qi; Action, lasts 8 hours.')
    ledger=actor.get('source_states',{}).get(PARENT,{})
    from ..gate2_runtime_models import Position
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session)
    lamps=[r for r in json.loads(ledger.get('objects','[]')) if not r.get('destroyed',False) and not r['component'].get('empowerment_ended') and r['component']['expires_at']>int(session.clock()) and not journey_suppressed(session,r)]
    for obj in lamps:
        point=Position.model_validate(obj['position'])
        for nxt in asset_routes(context,point,20):
            if nxt==point or not any(session.grid.distance_ft(nxt,p)<=120 for p in [Position.model_validate(actor['position']),*[Position.model_validate(o['position']) for o in lamps if o is not obj]]):continue
            offer('lantern_move',{'object_id':obj['object_id'],'position':nxt.model_dump(mode='json')},f'Move the Guiding Lantern at ({point.x}, {point.y}) to ({nxt.x}, {nxt.y}), {nxt.z*5} feet high; no Qi, once in six seconds.')
    uses=actor.get('travel_uses',{})
    if uses.get('qi.short_rest')!=actor['long_rests']:
        offer('lantern_qi_short_rest',{},'Rest for one hour to regain Qi equal to your owning Qi Path level; once before your next Long Rest.')
    if TEN in owned_features and actor['resources'].get(QI,0)>=8 and not any(r['condition_id']==C+'field_used' for r in json.loads(ledger.get('scene_limits','[]'))):
        offer('lantern_field',{'position':actor['position'],'chosen':sorted(journey_allies(session,aid))},'Create Ten Thousand Lantern Road here for 8 Qi; Action, Concentration, lasts one minute, once this scene.')
    return options or None


@hook('journey_properties')
def field_journey_deadline(session,aid):
    from ..gate2_runtime_models import Position
    point=Position.model_validate(session.state['actors'][aid]['position']);now=session.clock();ends=[]
    for keeper,actor in session.state['actors'].items():
        field=json.loads(actor.get('source_states',{}).get(PARENT,{}).get('field','{}'))
        if not field or field.get('expires_at',0)<=now or aid not in journey_allies(session,keeper):continue
        center=Position.model_validate(field['center'])
        if 0<=(point.z-center.z)*5<=60 and session.grid.distance_ft(point.model_copy(update={'z':center.z}),center)<=60:ends.append(field['expires_at'])
    return {'expiry_num':min(ends),'expiry_den':1} if ends else None
