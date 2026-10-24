"""Heaven-Anvil's source-owned impacts, Fractures and physical weapon delivery.

Geometry, dice, saves, damage, conditions, movement and zones use their native
engines. Fractures belong to one source actor, including on real map objects;
they never confer ownership of this school. No unowned actor acquires a benefit.
"""
from copy import deepcopy
from dataclasses import replace
from . import hook, effect

BASE = 'tianxia.subpath.qi.heaven_anvil_maul_cultivator.feature.'
IMPACT = BASE+'heaven_anvil_impact'
EARTH = BASE+'earthshaking_blow'
CORE = BASE+'hammer_the_core_out_of_rhythm'
METEOR = BASE+'hundred_hammer_meteor_foundry'
JUDGMENT = BASE+'heaven_anvil_judgment'
LEVELS = {IMPACT:3, EARTH:6, CORE:10, METEOR:14, JUDGMENT:18}
QI = 'resource:core.qi'
FRACTURE = 'condition:typed.mark.anvil_fracture.'
BLOCK = 'heaven_anvil'
# Catalog identities, never a display-name or Bludgeoning inference. Meteor
# hammer's heavy-impact mode needs a separate explicit source authorization.
MAUL_ITEMS = {'tianxia.mortal.weapon.'+name for name in ('chui','da_chui','zhan_chui')}


@hook('compile_passives')
def ownership(rows, info):
    cl = int(info['numbers'].get('cl') or 1)
    return [*rows, *[{'block':BLOCK,'feature_id':mid,'numbers':dict(info['numbers'])}
                    for mid in LEVELS if mid in info['owned_ids'] and cl >= LEVELS[mid]]]


def owned(engine, actor, mid):
    row=next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,())
              if r.get('block')==BLOCK and r.get('feature_id')==mid),None)
    if row is None or int(row.get('numbers',{}).get('cl',0))<LEVELS[mid]:return None
    from . import run_strict
    if False in run_strict('cultivation_feature_available',engine,actor,mid):return None
    limits=run_strict('cultivation_effective_cl',engine,actor,'tianxia.path.qi_cultivation')
    if any(type(v) is not int or v<0 for v in limits):raise ValueError('Effective cultivation CL must be a nonnegative integer.')
    if limits and min(limits)<LEVELS[mid]:return None
    return row


def number(engine, actor, key, default=0):
    row = next((owned(engine,actor,mid) for mid in LEVELS if owned(engine,actor,mid)),None)
    value=int((row or {}).get('numbers',{}).get(key) or default)
    if key=='cl':
        from . import run_strict
        limits=run_strict('cultivation_effective_cl',engine,actor,'tianxia.path.qi_cultivation')
        if any(type(v) is not int or v<0 for v in limits):raise ValueError('Effective cultivation CL must be a nonnegative integer.')
        return min([value,*limits])
    return value


def count(owner, target):
    if hasattr(target,'conditions'):
        return sum(int(c.data.get('count',1)) for c in target.conditions.values()
                   if c.condition_id.startswith(FRACTURE) and c.source_actor_id==owner.entity_id)
    return int((target.component or {}).get('anvil_fractures',{}).get(owner.entity_id,{}).get('count',0))


def set_count(engine, owner, target, value, source):
    value=max(0,min(4,int(value)))
    if hasattr(target,'conditions'):
        from .condition_ownership import remove_instance
        for c in list(target.conditions.values()):
            if c.condition_id.startswith(FRACTURE) and c.source_actor_id==owner.entity_id:
                remove_instance(engine,target,c.instance_id,source)
        if value:
            from ..typed_executor import mark_condition_id
            engine._apply_condition(target,mark_condition_id('Anvil Fracture',owner.entity_id),source,owner.entity_id,expires_on='UNTIL_REMOVED',
                data={'count':value,'source_cl':number(engine,owner,'cl',1),'dc':number(engine,owner,'save_dc',10),
                      'label':f'Anvil Fractures ({value}): ringing damage from {owner.display_name}; ends with the scene or repair'})
    else:
        component=deepcopy(target.component or {})
        fractures=component.setdefault('anvil_fractures',{})
        if value:fractures[owner.entity_id]={'count':value,'source_cl':number(engine,owner,'cl',1),'dc':number(engine,owner,'save_dc',10)}
        else:fractures.pop(owner.entity_id,None)
        engine._update_object(target.model_copy(update={'component':component}),source,owner.entity_id)


def add(ctx,target,n=1):
    set_count(ctx.engine,ctx.actor,target,count(ctx.actor,target)+n,ctx.source)


def pick(ctx,key,options,labels,prompt,*,minimum=1,maximum=1,decline=False,payment=None,preferred=None,subject=None):
    from .needle import ask,checkpoint_id,CHOICE
    subject = subject if subject is not None else ctx.target
    target_id = str(getattr(subject,'object_id',None) or getattr(subject,'entity_id',''))
    return ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'anvil',key,ctx.source,
        target_id),ctx.actor,CHOICE+'anvil_'+key,options,labels=labels,prompt=prompt,
        minimum=minimum,maximum=maximum,allow_decline=decline,payment=payment,preferred=preferred,
        target_id=target_id or None, prompt_context={'source_definition_id':ctx.action.source_definition_id,
            'action_name':ctx.action.display_name,'action_actor_id':ctx.actor.entity_id,'affected_id':target_id},
        feature_id=ctx.source,name=ctx.action.display_name)


@hook('additional_action_definitions')
def repair_definitions(engine,actor):
    """Derive the fractured creature's repair choices, including after reload."""
    if not any(c.condition_id.startswith(FRACTURE) for c in actor.conditions.values()):return None
    from hashlib import sha256
    from ..gate2_runtime_models import ActionDefinition
    from ..typed_executor import CP_POOLS
    definitions=[]
    for pool in CP_POOLS:
        if pool not in actor.resources:continue
        sid='action:typed.'+sha256(actor.entity_id.encode()).hexdigest()[:10]+'.anvil_repair.'+pool.rsplit('.',1)[-1]
        definitions.append(ActionDefinition(source_definition_id=sid,owner_id=actor.entity_id,
            display_name='Repair an Anvil Fracture',economy='ACTION',resolution_kind='TYPED',target_kind='SELF',
            costs=((pool,2),),parameters={'anvil_repair':1,'typed':{'source':'anvil_repair','numbers':{},
                'effects':[{'type':'anvil_repair'}],'manual_inline_choice':True,'riders':[]},
                'description':'Action, 2 Cultivation Points: attempt a Constitution save against one fracture source’s save DC. Success removes one Fracture. Failure still spends the points.'}))
    return definitions


@hook('additional_actions')
def fracture_repair_options(engine,actor):
    if not any(c.condition_id.startswith(FRACTURE) for c in actor.conditions.values()):return None
    return [a.source_definition_id for a in engine.action_catalog.values()
            if a.owner_id==actor.entity_id and a.parameters.get('anvil_repair')]


@hook('candidate_allowed')
def admitted(engine,actor,candidate,action):
    if action is None:return None
    p=action.parameters or {};typed=p.get('typed') or {}; source=str(typed.get('source') or '')
    if p.get('anvil_repair'):
        return any(c.condition_id.startswith(FRACTURE) for c in actor.conditions.values())
    if source not in LEVELS:return None
    if not owned(engine,actor,source):return False
    if source==EARTH:
        # Native grounded support: an airborne user cannot strike empty air.
        from ..falling import supported
        return supported(engine,actor)
    return None


@effect('anvil_repair')
def repair(ctx,row):
    from ..typed_executor import run_effects
    sources={c.source_actor_id:c for c in ctx.actor.conditions.values() if c.condition_id.startswith(FRACTURE)}
    selected=pick(ctx,'repair',list(sources),{k:ctx.engine.state.actors[k].display_name for k in sources},
        'Repair Anvil Fractures: choose whose fracture to repair. The Action and 2 Cultivation Points are spent even if the Constitution save fails.')
    if selected:
        held=sources[selected[0]]
        dc=int(held.data['dc'])
        run_effects(replace(ctx,typed={**ctx.typed,'numbers':{**ctx.numbers,'save_dc':dc}}),[
            {'type':'save','ability':'con','applies_to':'self','on_fail':[],
             'on_success':[{'type':'anvil_repair_success','owner':selected[0]}]}])


@effect('anvil_repair_success')
def repaired(ctx,row):
    owner=ctx.engine.state.actors.get(row['owner'])
    if owner:set_count(ctx.engine,owner,ctx.actor,count(owner,ctx.actor)-1,ctx.source)


@hook('event')
def scene_ends(engine,event_type,kwargs):
    if event_type!='MATCH_ENDED':return
    for owner in engine.state.actors.values():
        for target in list(engine.state.actors.values())+list(engine.state.objects.values()):
            if count(owner,target):set_count(engine,owner,target,0,'system:scene_end')


def area_spec(mode):
    return {'shape':'cylinder','size_ft':15 if mode=='earth' else 10 if mode=='meteor' else 30,
            'height_ft':10 if mode=='earth' else 20 if mode=='meteor' else 40}


def point_choices(ctx,range_ft):
    from ..gate2_runtime_models import Position
    from ..targeting import line_of_effect
    # A point can be on any elevation, not just the caster's floor. Bound
    # enumeration by the native activation volume, then let native 3D range,
    # sight and physical effect rays admit it. No hidden creature is consulted.
    engine, actor = ctx.engine, ctx.actor
    volume = engine._effect_volume(actor)
    reach = range_ft // engine.grid.square_size_ft
    axes = [range(max(0,min(p[i] for p in volume)-reach),
                  min(limit,max(p[i] for p in volume)+reach+1))
            for i,limit in enumerate((engine.grid.width,engine.grid.height,
                                      max(p[2] for p in volume)+reach+1))]
    points = {}
    for x in axes[0]:
        for y in axes[1]:
            for z in axes[2]:
                point = Position(x=x,y=y,z=z)
                if (engine._effect_distance_to_cell(actor,point)<=range_ft
                        and engine._line_of_sight_actor_to_cell(actor,point)
                        and line_of_effect(engine,actor,destination=point)):
                    points[f'{x},{y}' if z==0 else f'{x},{y},{z}'] = point
    return points


@effect('heaven_anvil_area')
def area(ctx,row):
    from ..typed_executor import run_effects, in_area
    from .. import zones
    from .objects import deal
    mode=row['mode']
    if not owned(ctx.engine,ctx.actor,str(ctx.typed.get('source') or '')):raise ValueError('This impact requires its acquired Heaven-Anvil feature.')
    if mode=='meteor':
        points=point_choices(ctx,90)
        selected=pick(ctx,'points',list(points),{k:f'Impact at {v.x}, {v.y}, height {v.z*ctx.engine.grid.square_size_ft} feet' for k,v in points.items()},
            'Meteor Hammerfall: choose up to your Proficiency Bonus impact points within 90 feet. Each deals 6d8 damage in a 10-foot radius; overlapping cylinders affect a creature once. Costs 5 Qi and your Action.',
            maximum=number(ctx.engine,ctx.actor,'pb',2))
        centers=[points[k] for k in selected]
    else:centers=[ctx.actor.position if mode=='earth' else ctx.destination or ctx.intent.destination]
    if not centers or any(p is None for p in centers):raise ValueError('Choose an impact point.')
    dtype=pick(ctx,'damage',['bludgeoning','force'],{'bludgeoning':'Bludgeoning','force':'Force'},
        f'{ctx.action.display_name}: choose Bludgeoning or Force damage for this activation.')[0]
    cl=number(ctx.engine,ctx.actor,'cl',1)
    dice={'count':5+2*int(cl>=11)+2*int(cl>=17) if mode=='earth' else 6 if mode=='meteor' else 12,
          'sides':10 if mode=='judgment' else 8}
    damage={'type':'damage','applies_to':'target','dice':dice,'damage_types':[dtype]}
    # One shared row/cache means one damage roll across every recipient and impact.
    affected=set();obj_ids=set();spec=area_spec(mode)
    from ..spatial_areas import actor_in_area
    from ..object_geometry import target_cells
    # Seal every impact's geometry before breaking any barrier or moving anyone.
    impacts=[(point,
        [s for s in ctx.engine.state.actors.values() if s.active and actor_in_area(ctx.engine,s,ctx.actor.position,point,spec)],
        [o for o in ctx.engine.state.objects.values() if not o.destroyed and o.current_hp is not None
            and any(in_area(ctx.engine,ctx.actor.position,point,p,spec) for p in target_cells(ctx.engine,o))])
        for point in centers]
    for point,creatures,objects in impacts:
        zones.create(ctx,{**spec,'difficult':'all','duration':{'kind':'special'},
            'source_profile':ctx.typed.get('anvil_ground_source'),
            'name':ctx.action.display_name+' — broken ground'},center=point,
            creation_key=f'anvil:{mode}:{point.x}:{point.y}:{point.z}')
        for subject in creatures:
            if not subject.active or subject.entity_id in affected:continue
            affected.add(subject.entity_id)
            save_center=next((p for p in centers if p==subject.position),point)
            inner=replace(ctx,target=subject,targets=[subject],destination=point,
                typed={**ctx.typed,'area':{},'anvil_mode':mode,'anvil_center':save_center.model_dump(mode='json')})
            fail=[damage,{'type':'condition','condition':'prone','applies_to':'target'},
                  {'type':'anvil_area_result','mode':mode,'failed':1,'center':point.model_dump(mode='json')}]
            success=[{'type':'half_damage'},
                     {'type':'anvil_area_result','mode':mode,'failed':0,'center':point.model_dump(mode='json')}]
            # half_damage consumes the fail branch's shared damage row in block_save.
            run_effects(inner,[{'type':'save','ability':'con' if mode=='judgment' else 'dex',
                'applies_to':'target','on_fail':fail,'on_success':success}])
        for old_object in objects:
            obj=ctx.engine.state.objects[old_object.object_id]
            if obj.destroyed or (mode!='meteor' and obj.object_id in obj_ids):continue
            obj_ids.add(obj.object_id)
            # The printed Artifact/Secret defense exception remains native.
            from ..typed_executor import roll_effect_damage
            rolled,kind=roll_effect_damage(ctx,damage)
            special=bool((obj.component or {}).get('artifact') or (obj.component or {}).get('secret'))
            deal(ctx.engine,ctx.actor,obj,[(rolled*(3 if mode=='judgment' else 2),kind)],ctx.source,
                ignore_threshold=not special,ignore_resistance=mode=='judgment' and not special)
            if mode=='judgment':set_count(ctx.engine,ctx.actor,ctx.engine.state.objects[obj.object_id],4,ctx.source)


@effect('anvil_area_result')
def area_result(ctx,row):
    from ..typed_executor import run_effects
    from ..gate2_runtime_models import Position
    mode=row['mode'];failed=bool(row['failed']);subject=ctx.target
    if subject is None:return
    if mode=='meteor':
        if failed:add(ctx,subject)
        return
    if mode=='judgment':
        set_count(ctx.engine,ctx.actor,subject,4 if failed else count(ctx.actor,subject)+1,ctx.source)
        if failed:
            run_effects(ctx,[{'type':'reaction_denied','applies_to':'target','duration':'until_end_of_next_turn'}])
    if mode=='earth' and failed:
        from .choice_costs import payable
        payment=payable(ctx.actor,QI,1)
        if payment and count(ctx.actor,subject)<4 and pick(ctx,'opening',['fracture'],{'fracture':'Apply one Anvil Fracture'},
            f'Hammer the Opening: spend 1 Qi to apply one Anvil Fracture to {subject.display_name} after its failed save?',decline=True,payment=payment):
            payment.pay(ctx.engine,ctx.actor,ctx.source);add(ctx,subject)
    center=Position.model_validate(row['center'])
    if mode=='judgment' and failed:
        judgment_edge(ctx,subject,center)
        return
    feet=10 if failed or mode=='judgment' else 5
    # Ordinary distance pushes retain the native collision/reaction path.
    inner=replace(ctx,destination=center,typed={**ctx.typed,'_area_centre':(center.x,center.y)})
    run_effects(inner,[{'type':'forced_movement','applies_to':'target','distance_ft':feet,'direction':'away_center'}])


def judgment_edge(ctx,subject,center):
    """Nearest reachable perimeter of the native round crater, from either side.

    The raster circle's boundary cells have an orthogonal neighbour outside it.
    Native forced routes own whole-body legality, detours, defenses and receipts;
    this destination rule has no invented displacement budget or radial-only ray.
    """
    from ..gate2_runtime_models import Position
    from .forced_destination import routes, ask
    from .needle import checkpoint_id, CHOICE
    from ..typed_executor import in_area
    grid=ctx.engine.grid
    plane=center.model_copy(update={'z':subject.position.z})
    # The grid's radius query returns a Chebyshev square, not the printed round
    # cylinder, so native typed area membership trims it to the round disk.
    # "spreads" only lets this perimeter query ignore collision; it creates no
    # area effect and moves nobody.
    spec={'shape':'cylinder','size_ft':15,'height_ft':grid.square_size_ft,'spreads':True}
    disk={(p.x,p.y) for p in grid.cells_in_radius(plane,15//grid.square_size_ft)
          if in_area(ctx.engine,plane,plane,p,spec)}
    edge=[Position(x=x,y=y,z=subject.position.z) for x,y in sorted(disk)
          if any(((x+dx-center.x)**2+(y+dy-center.y)**2)*grid.square_size_ft**2>15**2
                 for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))]
    if subject.position in edge:return
    legal=routes(ctx.engine,subject,None,goals=edge)
    if not legal:return
    nearest=min(grid.distance_ft(subject.position,p) for p in legal)
    legal={p:path for p,path in legal.items() if grid.distance_ft(subject.position,p)==nearest}
    ask(ctx.engine,ctx.intent,ctx.actor,subject,legal,source=ctx.source,
        checkpoint=checkpoint_id(ctx.engine,'anvil','crater_edge',ctx.source,subject.entity_id),
        choice_id=CHOICE+'anvil_crater_edge',name=ctx.action.display_name,ctx=ctx,
        prompt=f'Heaven-Anvil Judgment: move {subject.display_name} to the nearest legal edge of the 15-foot-radius crater.',
        prompt_context={'source_definition_id':ctx.action.source_definition_id,
                        'action_name':ctx.action.display_name,'action_actor_id':ctx.actor.entity_id,
                        'affected_id':subject.entity_id})


@hook('save')
def impact_save(ctx,subject,ability,named):
    mode=ctx.typed.get('anvil_mode')
    if mode=='meteor':
        center=ctx.typed.get('anvil_center') or {}
        if all(getattr(subject.position,k)==center.get(k,0) for k in ('x','y','z')):
            from ..gate2_runtime_models import DiceSpec
            roll=ctx.engine.roller.roll(DiceSpec(count=1,sides=4,modifier=0),actor_id=ctx.actor.entity_id,reason='ANVIL_CENTER_SAVE_PENALTY')
            ctx.engine._record_roll(roll)
            return {'bonus':-roll.total}
    if mode=='earth':
        from .hand_occupancy import occupancy
        from .qi_path import GUARD
        projected=any(m.source_definition_id==GUARD and m.target_field=='armor_class' for m in subject.modifiers.values())
        if projected or any(str(k).startswith('shield:') for group in occupancy(ctx.engine,subject).values() for k in group) or any((c.data or {}).get('projected_shield') or (c.data or {}).get('armor_shell') or (c.data or {}).get('defensive_stance') for c in subject.conditions.values()):
            return {'modes':['DISADVANTAGE']}
    return None


def maul_typed(typed):
    return bool(typed.get('weapon')) and str(typed.get('source') or '') in MAUL_ITEMS


def typed_maul_delivery(engine,typed):
    if maul_typed(typed):return True
    source=typed.get('weapon_source_id') or typed.get('delivered_by')
    parent=engine.action_catalog.get(source)
    return bool(parent and maul_typed((parent.parameters or {}).get('typed') or {}))


def maul(ctx):
    from .weapon_hits import weapon_identity
    action=ctx.engine.action_catalog.get(weapon_identity(ctx))
    return bool(action and maul_typed((action.parameters or {}).get('typed') or {}))


@hook('attack_resolved')
def ring(ctx,target,hit,attack):
    if not hit or not owned(ctx.engine,ctx.actor,IMPACT) or not maul(ctx):return
    if ctx.actor.turn_flags.get('typed_once_turn:anvil_ring'):return
    from .choice_costs import payable
    payment=payable(ctx.actor,QI,1)
    if not payment:return
    if not pick(replace(ctx,target=target),'ring',['ring'],{'ring':'Ring the Anvil'},
        f'Ring the Anvil: spend 1 Qi after hitting {target.display_name}? Once per turn, add Bludgeoning or Force damage and apply one Fracture on a failed Constitution save.',
        decline=True,payment=payment):return
    payment.pay(ctx.engine,ctx.actor,IMPACT)
    ctx.actor.turn_flags['typed_once_turn:anvil_ring']=1
    from ..typed_executor import run_effects
    cl=number(ctx.engine,ctx.actor,'cl',1)
    dtype=pick(ctx,'ring_damage',['bludgeoning','force'],{'bludgeoning':'Bludgeoning','force':'Force'},'Ring the Anvil: choose the additional damage type.')[0]
    good=2 if cl>=11 else 1;bad=4 if cl>=17 else 3 if cl>=11 else 2
    run_effects(replace(ctx,target=target,targets=[target],effect_source=IMPACT,
        typed={**ctx.typed,'numbers':{**ctx.numbers,'save_dc':number(ctx.engine,ctx.actor,'save_dc',10)}}),[{'type':'save','ability':'con','applies_to':'target',
        'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':bad,'sides':8},'damage_types':[dtype]}, {'type':'anvil_add_fracture'}],
        'on_success':[{'type':'damage','applies_to':'target','dice':{'count':good,'sides':8},'damage_types':[dtype]}]}])


@effect('anvil_add_fracture')
def fracture(ctx,row):
    if ctx.target:add(ctx,ctx.target)


@hook('attack_bonus')
def pressure_attack(ctx,actor):
    target=ctx.target or ctx.damage_cache.get('_object')
    if getattr(target,'object_id',None):target=ctx.engine.state.objects.get(target.object_id,target)
    if owned(ctx.engine,actor,IMPACT) and target and maul(ctx) and count(actor,target)>=3:return 1
    return None


@hook('resistance_ignored')
def pressure_resistance(engine,kind,typed,source_actor_id,target=None):
    owner=engine.state.actors.get(source_actor_id)
    if owner is None or target is None or not owned(engine,owner,IMPACT):return None
    if str(kind).upper() not in {'FORCE','BLUDGEONING'} or count(owner,target)<4:return None
    if str((typed or {}).get('source') or '') in LEVELS or typed_maul_delivery(engine,typed or {}):return True
    return None


def wielding(engine,actor):
    from ..weapon_delivery import ready_weapons
    from .hand_occupancy import weapon_allowed
    return any(maul_typed((a.parameters or {}).get('typed') or {}) and weapon_allowed(engine,actor,a) is not False
               for a in ready_weapons(engine,actor).values())


@hook('damage_defenses')
def recoil_resistance(engine,target,kind,typed,source_actor_id):
    if kind=='THUNDER' and owned(engine,target,CORE) and wielding(engine,target):
        return [{'kind':'resistance','damage_types':['THUNDER'],'feature_id':CORE}]
    return None


@hook('damage_reduction')
def recoil_force(engine,target,kind,typed,source_actor_id,*args):
    if kind=='FORCE' and owned(engine,target,CORE) and wielding(engine,target) and target.turn_flags.get('anvil_recoil_round_used')!=engine.state.round_number:
        return number(engine,target,'pb',2)
    return None


@hook('event')
def recoil_spent(engine,event_type,kwargs):
    if event_type!='DAMAGE_COMMITTED':return
    p=kwargs.get('payload') or {}
    if p.get('damage_type')!='FORCE':return
    for aid in kwargs.get('target_ids') or ():
        target=engine.state.actors.get(aid)
        if target and owned(engine,target,CORE) and wielding(engine,target):
            target.turn_flags['anvil_recoil_round_used']=engine.state.round_number


@hook('save_mode')
def recoil_prone(engine,subject,ability,dc,source,context):
    if 'prone' in set(context.get('named') or ()) and owned(engine,subject,CORE) and wielding(engine,subject):
        return 'ADVANTAGE'
    return None


def technique_payload(action):
    """A qualified single-target delivery, derived from its sealed native action."""
    typed=(action.parameters or {}).get('typed') or {}
    if (typed.get('weapon') or typed.get('unarmed_option') or typed.get('area')
            or action.target_kind not in {'HOSTILE_ENTITY','ALLY_OR_SELF','OBJECT'}
            or (action.range_ft is not None and action.range_ft>30)):
        return None
    duration=typed.get('duration') or {}
    if duration.get('kind') not in {None,'instant','rounds','minutes','hours','one_minute','until_start_of_next_turn','until_end_of_next_turn'}:
        return None
    forbidden={'zone','summon','shape_zone','create_object','bound_object','formation','create_asset','movement','teleport','stance'}
    from .rider_helpers import effect_rows as walk
    # The shared iterator reads effect trees; classification is source data,
    # never an inference from the eventual damage type or action's name.
    effects=typed.get('effects') or []
    native_target_effects={'attack','save','damage','half_damage','condition','ongoing','healing','temp_hp',
        'mark','spend_mark','speed','resistance','immunity','vulnerability','reaction_denied','attack_modifier',
        'save_modifier','ability_check_modifier','healing_reduction','suppress_resistance','ignore_resistance'}
    if any(r.get('type') in forbidden or r.get('picks_destination') or r.get('type') not in native_target_effects
           for r in walk(effects)):return None
    if not effects:return None
    for row in walk(effects):
        scope=row.get('applies_to')
        if scope not in {None,'target'}:return None
        if scope is None and row.get('type') not in {'attack','save','half_damage','ignore_resistance'}:return None
    attacks=[r for r in effects if r.get('type')=='attack']
    if attacks:
        if len(attacks)!=1 or int(attacks[0].get('count') or 1)!=1:return None
        return [r for e in effects for r in (e.get('on_hit') or [] if e.get('type')=='attack' else [e])]
    return effects


@hook('compile_actions')
def conduction(info):
    if IMPACT not in info['owned_ids'] or int(info['numbers'].get('cl') or 1)<3:return None
    from ..gate2_runtime_models import ActionDefinition
    out=[]
    weapons=[a for a in info['actions'] if maul_typed((a.parameters or {}).get('typed') or {})
        and ((a.parameters or {}).get('typed') or {}).get('proficient') and '#' not in a.source_definition_id]
    for technique in info['actions']:
        typed=technique.parameters.get('typed') or {}
        # Resource provenance is independent of price. Explicit activation
        # metadata, a Qi source Path or the shared Qi-sphere classification
        # also admits genuinely free techniques; an actor's primary pool alone
        # never turns an unrelated free technique into a Qi-powered one.
        from .insights7 import qi_powered
        source=typed.get('option_of') or typed.get('source') or ''
        record=info['mechanics'].get(source) or {}
        is_qi=(qi_powered(typed.get('sphere') or record.get('sphere_id'),tuple(r for r,n in technique.costs))
               or record.get('path_id')=='tianxia.path.qi_cultivation')
        if not (typed['qi_powered'] if type(typed.get('qi_powered')) is bool else is_qi):continue
        if str(typed.get('source') or '') in {IMPACT,CORE}:continue
        payload=technique_payload(technique)
        if payload is None:continue
        for weapon in weapons:
            wt=weapon.parameters['typed']
            weapon_attack=next(e for e in wt['effects'] if e.get('type')=='attack')
            weapon_riders=deepcopy([e for e in weapon_attack.get('on_hit') or [] if not e.get('weapon_damage')])
            variant=deepcopy(typed)
            variant.update(weapon=deepcopy(wt['weapon']),weapon_source_id=weapon.source_definition_id,
                delivered_by=weapon.source_definition_id,anvil_conduction=1,
                effects=[{'type':'attack','attack_kind':'weapon_melee','count':1,'on_hit':[
                    {'type':'damage','applies_to':'target','weapon_damage':True},
                    *([{'type':'anvil_weapon_riders','effects':weapon_riders}] if weapon_riders else []),
                    *deepcopy(payload)],
                    'on_miss':([{'type':'anvil_weapon_riders','effects':deepcopy(weapon_attack['on_miss'])}]
                        if weapon_attack.get('on_miss') else [])}])
            variant['numbers']={**variant['numbers'],'attack_bonus':wt['numbers']['attack_bonus']}
            out.append(technique.model_copy(update={'source_definition_id':technique.source_definition_id+'#anvil_'+weapon.source_definition_id.rsplit('.',1)[-1],
                'display_name':technique.display_name+' through '+weapon.display_name,
                'range_ft':weapon.range_ft,'costs':(*technique.costs,(QI,1)),
                'parameters':{**technique.parameters,'typed':variant,'anvil_weapon':weapon.source_definition_id,
                    'description':'Activate this technique through your wielded, proficient maul. Pay the complete technique cost plus 1 Qi. One maul attack deals its normal weapon damage and delivers the technique only on a hit; a miss still spends the full cost.'}}))
    return out or None


@hook('candidate_allowed')
def conduction_admission(engine,actor,candidate,action):
    weapon_id=(getattr(action,'parameters',None) or {}).get('anvil_weapon')
    if weapon_id:
        from ..weapon_delivery import ready_weapons
        return bool(owned(engine,actor,IMPACT) and weapon_id in ready_weapons(engine,actor))
    return None


@hook('size_steps')
def recoil_size(engine,actor,role,purposes):
    if role=='resist' and 'forced' in purposes and owned(engine,actor,CORE) and wielding(engine,actor):return 1
    return None


@hook('ac')
def pressure_shield(engine,target):
    from .attack_scope import current
    frame=current(engine)
    if not frame or frame['target_id']!=target.entity_id:return None
    ctx=frame['context'];owner=ctx.actor
    if not owned(engine,owner,IMPACT) or count(owner,target)<2 or not maul(ctx):return None
    from .. import carry
    from factory_authoring.starting_kits import item_definition
    # Only catalogued mortal physical shields qualify for this exception.
    mundane=any(str(i.get('item_id') or '').startswith('tianxia.mortal.')
        and item_definition(i['item_id']).get('armor_category')=='shield' and carry.holds(engine,target,i['key'])
        for i in (carry.carrying_of(engine,target.entity_id) or {}).get('items',[]))
    if mundane:
        return -max((int(r.get('amount') or 0) for r in engine.typed_passive_rows.get(target.entity_id,()) if r.get('block')=='shield_ac'),default=0)
    return None


@hook('save_bonus')
def concentration_pressure(engine,target,ability,dc,source,intent):
    context=engine.d20_context() or {}
    if 'concentration' not in str(source).lower():return None
    owner=engine.state.actors.get(context.get('source_actor_id'))
    if owner is None or not owned(engine,owner,IMPACT) or count(owner,target)<3:return None
    damage_source=context.get('damage_source_id')
    action=engine.action_catalog.get(damage_source)
    typed=(getattr(action,'parameters',None) or {}).get('typed') or {}
    if typed.get('source') not in LEVELS and not typed_maul_delivery(engine,typed):return None
    key='typed_once_turn:anvil_concentration:'+owner.entity_id
    if target.turn_flags.get(key):return None
    from ..gate2_runtime_models import DiceSpec
    roll=engine.roller.roll(DiceSpec(count=1,sides=4,modifier=0),actor_id=owner.entity_id,reason='ANVIL_CONCENTRATION_PRESSURE')
    engine._record_roll(roll);target.turn_flags[key]=1
    return -roll.total




@hook('object_hit')
def ring_object(ctx,obj,kind):
    if not obj.unattended or not owned(ctx.engine,ctx.actor,IMPACT) or not maul(ctx) or ctx.actor.turn_flags.get('typed_once_turn:anvil_ring'):return
    from .choice_costs import payable
    payment=payable(ctx.actor,QI,1)
    if not payment:return
    cl=number(ctx.engine,ctx.actor,'cl',1)
    dice=4 if cl>=17 else 3 if cl>=11 else 2
    name=str((obj.component or {}).get('name') or 'Unattended object')
    trigger=f'{ctx.action.display_name} hitting {name}'
    benefit=(f'One Anvil Fracture (up to four from you, until scene end or repair): your maul attacks and Heaven-Anvil features '
             f'reduce its ordinary damage threshold by {number(ctx.engine,ctx.actor,"pb",2)}; at two, maul attacks ignore '
             'nonartifact physical shields; at three, maul attacks gain +1 to hit and your damage subtracts 1d4 from its first '
             'Concentration save each turn; at four, ignore ordinary Bludgeoning and Force resistance, not immunity.')
    if not pick(ctx,'ring_object',['ring'],{'ring':'Ring the Anvil'},
        f'Ring the Anvil after {trigger}: spend 1 Qi, once per turn, to add {dice}d8 Bludgeoning or Force damage with no save? '+benefit,
        decline=True,payment=payment,subject=obj):return
    payment.pay(ctx.engine,ctx.actor,IMPACT);ctx.actor.turn_flags['typed_once_turn:anvil_ring']=1
    from ..typed_executor import roll_effect_damage
    from .objects import deal
    dtype=pick(ctx,'ring_object_damage',['bludgeoning','force'],{'bludgeoning':'Bludgeoning','force':'Force'},
        f'Ring the Anvil after {trigger}: choose the type of the added {dice}d8 damage (1 Qi, once per turn, no save). '+benefit,subject=obj)[0]
    amount,damage_type=roll_effect_damage(ctx,{'type':'damage','dice':{'count':dice,'sides':8},'damage_types':[dtype]})
    live=ctx.engine.state.objects[obj.object_id]
    deal(ctx.engine,ctx.actor,live,[(amount,damage_type)],ctx.source)
    add(ctx,ctx.engine.state.objects[obj.object_id])


@hook('object_damage_policy')
def object_pressure(engine,actor,obj,packets,source,policy):
    if not owned(engine,actor,IMPACT) or not count(actor,obj):return None
    action=engine.action_catalog.get(source)
    typed=(getattr(action,'parameters',None) or {}).get('typed') or {}
    from ..weapon_delivery import weapon_identity
    parent=engine.action_catalog.get(weapon_identity(engine,source,typed,owner_id=actor.entity_id))
    pt=(getattr(parent,'parameters',None) or {}).get('typed') or {}
    if not (maul_typed(pt) or typed.get('source') in LEVELS):return None
    if (obj.component or {}).get('artifact') or (obj.component or {}).get('secret'):return None
    result={'reduce_threshold':max(int(policy.get('reduce_threshold',0)),number(engine,actor,'pb',2))}
    if count(actor,obj)>=4:result['ignore_resistance_types']=('BLUDGEONING','FORCE')
    return result


@hook('mark_apply')
def native_fracture(ctx,row,subject,expires,data):
    if str(row.get('mark') or '').lower()!='anvil fracture':return None
    if not any(owned(ctx.engine,ctx.actor,mid) for mid in LEVELS):return None
    add(ctx,subject)
    return True


@hook('mark_consume')
def consume_fracture(ctx,row,subject):
    if str(row.get('mark') or '').lower()!='anvil fracture':return None
    if not any(owned(ctx.engine,ctx.actor,mid) for mid in LEVELS):return None
    value=count(ctx.actor,subject)
    if value<=0:return False
    set_count(ctx.engine,ctx.actor,subject,value-1,ctx.source)
    return True


@hook('object_weapon_provenance')
def object_delivery_identity(info,weapon_id):
    cl=int(info['numbers'].get('cl') or 1)
    if not weapon_id or IMPACT not in info['owned_ids'] or cl<3:return None
    physical={r['action_id'] for r in info.get('weapon_kinds',())}
    action=next((a for a in info.get('actions',()) if a.source_definition_id==weapon_id),None)
    if weapon_id in physical or action is not None and action.parameters.get('requires_held_weapon'):
        return True
    return None


@hook('compile_action')
def source_area_terrain(action,info):
    typed=(action.parameters or {}).get('typed') or {}
    if typed.get('source') not in {EARTH,METEOR,JUDGMENT}:return None
    if not any(e.get('type')=='heaven_anvil_area' for e in typed.get('effects') or []):return None
    native=deepcopy(typed)
    # The source effect places each paid impact through zones.create. Disable
    # only this declaration's heuristic single-area terrain producer.
    provenance=(native.get('zone_spec') or {}).get('source_profile')
    if provenance:native['anvil_ground_source']={**provenance,'duration_kind':'special'}
    native.pop('zone_spec',None)
    return action.model_copy(update={'parameters':{**action.parameters,'typed':native}})

# Canonical decoded record hashes, including each printed record separator.
SOURCE_HASHES = {
    EARTH:'6c4d320fb1b23012bb2758f947a554784fe82034e169892df105c9fbf9ff36d4',
    CORE:'ef9757b38fa5732f41a945256acff2bb5112071f845fb308577c101db55af61b',
    IMPACT:'f2e48a83fe99bd4c779d912d0c75afc74e02b16a4edfb14196cc56c807b16377',
    JUDGMENT:'fd657780ccfc2b3b21e745c55dea45ee4cfe6054984985283b6e9f389dab91a6',
    METEOR:'294b09f7bd83fad5ce17d85b81ef99cce76b16afea6732f69bb0242e6435475c'}
SCHOOL=BASE.removesuffix('.feature.')
QI_PATH='tianxia.path.qi_cultivation'


def qi_level(sheet):
    """Read the existing Path profile; explicit effective CL precedes attainment."""
    identity=sheet.get('identity') or {};paths=sheet.get('path_and_subpath') or {}
    overall=identity.get('cultivation_level')
    if type(overall) is not int or overall<1:return 0
    profiles=paths.get('paths') or []
    if isinstance(profiles,dict):profiles=list(profiles.values())
    qi=next((r for r in profiles if isinstance(r,dict) and r.get('path_id')==QI_PATH),None)
    if qi is not None:
        attained=next((qi[k] for k in ('effective_cl','attainment','owning_path_level') if k in qi),None)
        return min(overall,attained) if type(attained) is int and attained>=0 else 0
    if profiles:return 0
    ids=set(identity.get('path_ids') or paths.get('path_record_ids') or [])
    if paths.get('path_record_id'):ids.add(paths['path_record_id'])
    return overall if (QI_PATH in ids if ids else identity.get('path')=='Qi Cultivation') else 0


@hook('subpath_acquisition')
def acquire_school(source,sheet):
    if source!=SCHOOL:return None
    level=qi_level(sheet);paths=sheet.get('path_and_subpath') or {}
    selected=set(paths.get('subpath_record_ids') or [])
    if paths.get('subpath_record_id'):selected.add(paths['subpath_record_id'])
    selected.update(r['subpath_id'] for r in paths.get('subpaths') or []
                    if isinstance(r,dict) and isinstance(r.get('subpath_id'),str))
    # This Open School consumes its Qi Path's Subpath choice. It never replaces
    # a different progression, and no feature or sphere is granted on that basis.
    other=any(k.startswith('tianxia.subpath.qi.') and k!=SCHOOL for k in selected)
    legal=level>=3 and not other
    return {'name':'Heaven-Anvil Maul Cultivator','legal':legal,'effective_cl':level,
        'reasons':[] if legal else ['Requires an acquired Qi Cultivation Path at effective CL3 or higher and its available Subpath choice.'],
        'features':[{'id':mid,'minimum_cl':cl,'text_sha256':SOURCE_HASHES[mid]} for mid,cl in LEVELS.items()]}


@hook('compile_bundle')
def source_progression_level(bundle,info):
    if not any(r.get('block')==BLOCK for r in bundle.get('typed_passives',[])):return None
    level=qi_level(info['owner_sheet'])
    result=deepcopy(bundle)
    for row in result.get('typed_passives',[]):
        if row.get('block')==BLOCK:row['numbers']={**row.get('numbers',{}),'cl':level}
    return result


@hook('compile_action')
def source_action_level(action,info):
    typed=(action.parameters or {}).get('typed') or {}
    if typed.get('source') not in LEVELS:return None
    return action.model_copy(update={'parameters':{**action.parameters,'typed':{**typed,
        'numbers':{**typed.get('numbers',{}),'cl':qi_level(info['owner_sheet'])}}}})


@effect('anvil_weapon_riders')
def conduction_weapon_riders(ctx,row):
    """The real weapon retains its own enchantments, mastery and save statistics."""
    if not ctx.typed.get('anvil_conduction') or not owned(ctx.engine,ctx.actor,IMPACT):return
    from ..typed_executor import run_effects
    source=ctx.typed['weapon_source_id'];weapon=ctx.engine.action_catalog[source]
    run_effects(replace(ctx,action=weapon,typed=weapon.parameters['typed'],effect_source=source),deepcopy(row['effects']))
