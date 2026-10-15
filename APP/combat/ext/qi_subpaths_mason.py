"""Emergency Repairs: native object commits and explicit Construct healing.

Only sealed emergency_repair actions opt in. Reinforcement is a source-clock
condition plus an object component receipt. Removing/expiring that condition
restores only the bonuses this receipt added, preserving unrelated changes.
Adjacent friendly creatures query the live receipt at their save's location.
"""
from typing import Any
from . import hook, effect

REPAIRS = 'tianxia.subpath.qi.mason_cultivator.feature.emergency_repairs'
REINFORCED = 'condition:typed.mason_reinforcement'
MARKER = 'mason_reinforcement'


def repairable(obj: Any) -> bool:
    return not obj.destroyed and assets.repair_allowed(obj, 0)


def reinforceable(obj: Any) -> bool:
    return repairable(obj) and bool((obj.component or {}).get('structure') or obj.object_kind in
        ('barrier','formation_anchor','vehicle','cart','rowboat','ballista'))


@hook('compile_actions')
def repair_variants(info: dict[str, Any]) -> list[Any] | None:
    if REPAIRS not in info['owned_ids'] or int(info['numbers'].get('cl',0))<6:
        return None
    from ..gate2_runtime_models import ActionDefinition
    typed={'source':REPAIRS,'numbers':info['numbers'],'duration':{'kind':'instant'},'effects':[{'type':'mason_repair_declaration'}], 'riders':[]}
    def action(key,label,target,economy,range_ft,cost,mode):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mason.{key}",
            display_name='Emergency Repairs: '+label,owner_id=info['actor_id'],economy=economy,
            resolution_kind='TYPED',target_kind=target,range_ft=range_ft,costs=(('resource:core.qi',cost),),
            parameters={'typed':typed,'emergency_repair':mode,'expected_damage':0, **({'include_destroyed_objects':True} if mode=='reconstruct' else {}), **({'player_only':True} if mode=='construct_hostile' else {}),
                'description': ('Action, 2 Qi: restore 3d8 plus your Qi key ability modifier Hit Points to the selected damaged object or Construct within 5 feet. Cannot exceed its maximum.' if mode!='reinforce' else 'Bonus Action, 1 Qi: one structure within 30 feet gains +2 AC and increases its Damage Threshold by your Proficiency Bonus until your next turn starts. Adjacent allies gain Advantage against Prone and forced movement. Repeated reinforcement does not stack.')})
    return [action('repair','Repair Structure','OBJECT','ACTION',5,2,'repair'),
            action('reinforce','Reinforce Position','OBJECT','BONUS_ACTION',30,1,'reinforce'),
            action('reconstruct','Repair Structure with sufficient material','OBJECT','ACTION',5,2,'reconstruct'),
            # Enumerate the printed creature domain so the sealed candidate
            # check can retain Neutral Constructs as valid manual recipients.
            action('construct','Repair Construct','ANY_CREATURE','ACTION',5,2,'construct'),
            action('construct_hostile','Repair Construct (other side)','HOSTILE_ENTITY','ACTION',5,2,'construct_hostile')]


@hook('object_targets')
def repair_targets(engine: Any, actor: Any, action: Any) -> list[str]:
    mode=action.parameters.get('emergency_repair')
    if mode not in ('repair','reinforce','reconstruct'):
        return []
    return [o.object_id for o in engine.state.objects.values() if
            (reinforceable(o) if mode=='reinforce' else reconstructable(engine,o) if mode=='reconstruct' else repairable(o)) and
            (mode!='repair' or o.current_hp<o.maximum_hp)]


@hook('candidate_allowed')
def repair_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    mode=(action.parameters if action is not None else {}).get('emergency_repair')
    if not mode:
        return None
    target_id=next(iter(candidate.target_ids),None)
    if mode in ('construct','construct_hostile'):
        from .creature_kinds import matches
        from ..relations import relation, ALLY, ENEMY
        target=engine.state.actors.get(target_id)
        expected = ENEMY if mode=='construct_hostile' else ALLY
        return target is not None and (relation(engine,actor,target)==expected if mode=='construct_hostile' else relation(engine,actor,target)!=ENEMY) and matches(target,['construct']) and target.current_hp<target.maximum_hp
    obj=engine.state.objects.get(target_id)
    return obj is not None and (reinforceable(obj) if mode=='reinforce' else reconstructable(engine,obj) if mode=='reconstruct' else repairable(obj))


@hook('object_action')
def repair_object(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    mode=action.parameters.get('emergency_repair')
    if mode not in ('repair','reinforce','reconstruct'):
        return None
    from .. import typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    typed=action.parameters['typed'];source=action.source_definition_id
    ctx=te.Context(engine,actor,action,intent,typed,[],None,{})
    if mode in ('repair','reconstruct'):
        declaration=None
        from ..object_geometry import target_cells
        sources=material_sources(engine,target_cells(engine,obj))
        if not sources:raise ValueError('Repair needs an actual material source.')
        material=pick(engine,actor,intent,'repair_material',sources,sources,'Emergency Repairs: declare the material source before restoring this structure.')[0]
        if mode=='reconstruct':
            if not reconstructable(engine,obj):raise ValueError('This destroyed object cannot be reconstructed by ordinary repairs.')
            confirmed=pick(engine,actor,intent,'repair_sufficient',('sufficient',),{'sufficient':'Declare that the named source supplies sufficient reconstruction material'},
                'Emergency Repairs cannot reconstruct a completely destroyed object without sufficient material. Confirm the selected material source is sufficient, or decline.',decline=True)
            if not confirmed:return True
            declaration={'actor':actor.entity_id,'authority':'native_source_owner','source':REPAIRS,'material_source':material,
                'expires_sequence':engine.state.event_sequence+1,'sufficient_material':True}
        amount=te._roll(ctx,DiceSpec(count=3,sides=8,modifier=int(ctx.numbers.get('key_mod') or 0)),'REPAIR')
        after=obj.model_copy(update={'current_hp':min(obj.maximum_hp,obj.current_hp+max(0,amount)),
            **({'destroyed':False,'component':{**(obj.component or {}),'repair_declaration':declaration}} if declaration and amount>0 else {})})
        engine._update_object(after,source,actor.entity_id)
        assets.refresh(engine)
        return True
    if not reinforceable(obj):
        return True
    old=(obj.component or {}).get(MARKER)
    if old:
        owner=engine.state.actors.get(old['owner'])
        if owner is not None and old['instance'] in owner.conditions:
            condition=owner.conditions.pop(old['instance'])
            engine._append_event('CONDITION_REMOVED',source,actor_id=owner.entity_id,target_ids=(owner.entity_id,),
                payload={'condition_id':condition.condition_id,'instance_id':condition.instance_id})
        obj=engine.state.objects[obj.object_id]
    pb=int(ctx.numbers.get('pb') or 0)
    object_name=str((obj.component or {}).get('display_name') or (obj.component or {}).get('name') or
                    obj.object_kind.replace('_',' '))
    engine._apply_condition(actor,REINFORCED,source,actor.entity_id,expires_on='START_OF_SOURCE_NEXT_TURN',
        data={'object_id':obj.object_id,'label':f"{object_name} — +2 AC, Damage Threshold +{pb} (ignores hits below its threshold); adjacent allies have Advantage against Prone and forced movement. Ends at {actor.display_name}'s next turn start."})
    instance=next(c.instance_id for c in reversed(list(actor.conditions.values())) if c.condition_id==REINFORCED and c.data.get('object_id')==obj.object_id)
    marker={'owner':actor.entity_id,'instance':instance,'ac':2,'threshold':pb}
    engine._update_object(obj.model_copy(update={'ac':int(obj.ac or 0)+2,'damage_threshold':int(obj.damage_threshold or 0)+pb,
        'component':{**(obj.component or {}),MARKER:marker}}),source,actor.entity_id)
    return True


@effect('mason_repair_declaration', harmful=False)
def repair_construct(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.action.parameters.get('emergency_repair') not in ('construct','construct_hostile') or ctx.target is None:
        return
    from .. import typed_executor as te
    te.run_effects(ctx,[{'type':'healing','applies_to':'target','dice':{'count':3,'sides':8,'bonus_formula':'key_ability_modifier'}}])


@hook('event')
def reinforcement_expired(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type!='CONDITION_REMOVED' or (kwargs.get('payload') or {}).get('condition_id')!=REINFORCED:
        return
    instance=(kwargs.get('payload') or {}).get('instance_id')
    for obj in list(engine.state.objects.values()):
        marker=(obj.component or {}).get(MARKER)
        if marker and marker['instance']==instance:
            component=dict(obj.component);component.pop(MARKER)
            engine._update_object(obj.model_copy(update={'ac':max(0,int(obj.ac or 0)-marker['ac']),
                'damage_threshold':max(0,int(obj.damage_threshold or 0)-marker['threshold']),
                'component':component}),REPAIRS,marker['owner'])


@hook('save')
def reinforced_save(ctx: Any, target: Any, ability: str, named: Any) -> dict | None:
    if not {'prone','forced_movement'} & set(named or ()):
        return None
    from ..object_geometry import target_cells
    from ..relations import relation, ALLY
    for obj in ctx.engine.state.objects.values():
        marker=(obj.component or {}).get(MARKER)
        if not marker or obj.destroyed:
            continue
        owner=ctx.engine.state.actors.get(marker['owner'])
        if owner is not None and relation(ctx.engine, target, owner)==ALLY and marker['instance'] in owner.conditions and any(
                ctx.engine.grid.distance_ft(target.position,cell)<=5 for cell in target_cells(ctx.engine,obj)):
            return {'modes':['ADVANTAGE']}
    return None

# The complete construction family shares the public Asset/Anchor runtime.
from .. import asset_anchor_runtime as assets
from ..gate2_runtime_models import Position
from . import needle
from ..relations import relation,ALLY

BASE = 'tianxia.subpath.qi.mason_cultivator.feature.'
BARRIER = BASE+'raise_barrier'
GREATER = BASE+'bridge_the_impossible'
CREW = BASE+'fortress_crew'
BASTION = BASE+'raise_the_imperial_bastion'
WORK = 'condition:typed.mason_work'
ACTIVE = 'condition:typed.mason_bastion'
BRACE = 'condition:typed.mason_brace'
# length, width, height (feet); a form's actual dimensions are declared at use.
FORMS = {'Low Wall':(10,1,3),'Tall Wall':(10,1,10),'Ramp':(15,10,10),
         'Platform':(10,10,10),'Great Bridge':(60,10,30),'Ascending Stair':(40,10,30),
         'Defensive Tower':(15,15,30),'Gatehouse':(30,10,10),
         'Watchtower':(10,10,10),'Bridge Section':(10,10,10)}


@hook('compile_passives')
def mason_ownership(rows,info):
    owned = [k for k,level in ((BARRIER,3),(REPAIRS,6),(GREATER,10),(CREW,14),(BASTION,18)) if k in info['owned_ids'] and int(info['numbers'].get('cl',0))>=level]
    if not owned:
        return rows
    return [*rows,{'block':'mason_native','owned':owned,'numbers':dict(info['numbers'])},*([{'block':'asset_mechanisms'}] if GREATER in owned else [])]


def mason(engine,actor,feature):
    return next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,())
                 if r.get('block')=='mason_native' and feature in r['owned']),None)


@hook('compile_actions')
def construction_actions(info):
    from ..gate2_runtime_models import ActionDefinition
    actions=[]
    for feature,forms,reach,cost in ((BARRIER,('Low Wall','Tall Wall','Ramp','Platform'),30,1),
            (GREATER,('Great Bridge','Ascending Stair','Defensive Tower','Gatehouse'),60,4),
            (BASTION,('Raise Sections',),90,8)):
        if feature not in info['owned_ids'] or int(info['numbers'].get('cl',0))<{BARRIER:3,GREATER:10,BASTION:18}[feature]:
            continue
        for form in forms:
            label = {BARRIER:'Raise Barrier',GREATER:'Bridge the Impossible',BASTION:'Raise the Imperial Bastion'}[feature]
            actions.append(ActionDefinition(source_definition_id=f'action:typed.{info["short"]}.mason.{feature.rsplit(".",1)[1]}.{form.lower().replace(" ","_")}',
                display_name=label+': '+form,owner_id=info['actor_id'],economy='ACTION',resolution_kind='TYPED',
                target_kind='CELL',range_ft=reach,costs=(('resource:core.qi',cost),),parameters={
                    'typed':{'source':feature,'numbers':dict(info['numbers']),'duration':{'kind':'instant'},
                        'manual_inline_choice':True,'effects':[{'type':'mason_construction','feature':feature,'form':form}],'riders':[]},
                    'mason_build':feature,'mason_form':form,'expected_damage':0,'cell_placement':{},
                    'description':f'Action, {cost} Qi: {label}. Choose exact spaces, dimensions and material support. '+
                        ('Up to four sections within a 40-foot-radius, 40-foot-high cylinder, for 1 minute with Concentration; once per scene.' if feature==BASTION else
                         'Create a supported structure for 1 hour. It cannot appear through creatures or solid objects.')}))
    return actions or None


def pick(engine,actor,intent,key,options,labels,prompt,*,decline=False,maximum=1,preferred=None):
    from ..target_knowledge import located
    from ..senses import perceives_cell
    automatic=[option for option in options if
        (located(engine,actor,engine.state.actors[option]) if option in engine.state.actors else
         perceives_cell(engine,actor,engine.state.objects[option].position) if option in engine.state.objects else True)]
    return needle.ask(engine,intent,needle.checkpoint_id(engine,'mason_'+key,actor.entity_id),actor,
        needle.CHOICE+'mason_'+key,list(options),labels=labels,prompt=prompt,name='Mason Cultivator',
        feature_id=BASTION if 'command' in key else BARRIER,allow_decline=decline,maximum=maximum,
        preferred=preferred,automatic_options=automatic)


def family(engine,owner,group=None):
    return [o for o in assets.members(engine,owner.entity_id,group) if (o.component or {}).get('mason')]


def cell_rectangle(position,length,width,rotation=0):
    nx,ny=(max(1,(length+4)//5),max(1,(width+4)//5))
    if rotation==90:nx,ny=ny,nx
    return [Position(x=position.x+x,y=position.y+y,z=position.z) for y in range(ny) for x in range(nx)]


@hook('candidate_allowed')
def build_candidate(engine,actor,candidate,action):
    p=action.parameters if action is not None else {}
    feature=p.get('mason_build')
    if not feature:
        return None
    if not mason(engine,actor,feature) or candidate.destination is None:
        return False
    if feature==BASTION and any(c.condition_id=='condition:typed.mason_scene_use' for c in actor.conditions.values()):
        return False
    # Minimum legal form; exact dimensions and every occupied volume are checked
    # again after the owner's declaration, before the transaction can commit.
    return assets.legal_placement(engine,[candidate.destination],1,observer=actor)


def material_sources(engine,cells):
    options={}
    for c in cells:
        if assets.stable(engine,c):
            key='terrain:'+needle.cell_id(c)
            options[key]=f'Stable terrain/support at ({c.x}, {c.y}, {c.z})'
    from ..object_geometry import target_cells
    for obj in engine.state.objects.values():
        if not obj.destroyed and (obj.component or {}).get('structure') and any(
                engine.grid.distance_ft(c,s)<=5 for c in cells for s in target_cells(engine,obj)):
            options[obj.object_id]=(obj.component or {}).get('name') or obj.object_kind
    return options


def declare(ctx,feature,form,position,index=0):
    engine,actor=ctx.engine,ctx.actor
    maxl,maxw,maxh=FORMS[form]
    rotation=pick(engine,actor,ctx.intent,f'orientation_{index}',('0','90'),{'0':'East–west','90':'North–south'},
        f'{form}: choose its orientation before construction.')[0]
    # Fixed wall/tower/gate dimensions remain fixed; the printed "up to" forms
    # retain every integer dimension, including shorter/narrower works.
    variable=form in ('Ramp','Platform','Great Bridge','Ascending Stair')
    dims=[]
    for axis,limit in (('length',maxl),('width',maxw),('height',maxh)):
        opts=[str(i) for i in range(1,limit+1)] if variable or form=='Defensive Tower' and axis=='height' else [str(limit)]
        selected=pick(engine,actor,ctx.intent,f'{axis}_{index}',opts,{v:v+' feet' for v in opts},
            f'{form}: choose {axis}, up to {limit} feet.',preferred=[str(limit)])[0]
        dims.append(int(selected))
    length,width,height=dims
    cells=cell_rectangle(position,length,1 if form=='Gatehouse' else width,int(rotation))
    if form=='Defensive Tower':
        xs={c.x for c in cells};ys={c.y for c in cells}
        cells=[c for c in cells if c.x in (min(xs),max(xs)) or c.y in (min(ys),max(ys))]
    if not assets.legal_placement(engine,cells,height):
        raise ValueError(f'{form} needs unoccupied spaces connected to stable support.')
    if form=='Great Bridge':
        end=cells[-1]
        if not assets.stable(engine,position) or not assets.stable(engine,end):
            raise ValueError('Great Bridge requires stable support at both named endpoints.')
    sources=material_sources(engine,cells)
    if not sources:raise ValueError('Choose an actual stable terrain or structure material source.')
    material=pick(engine,actor,ctx.intent,f'material_{index}',sources,sources,
        f'{form}: choose its material source before raising it.')[0]
    load=''
    if feature==GREATER:
        load=pick(engine,actor,ctx.intent,f'load_{index}',('ordinary','unloaded'),
            {'ordinary':'Creatures and ordinary carried equipment','unloaded':'No crossing until a load is declared'},
            'Bridge the Impossible: declare the legal load before creatures cross.')[0]
    return {'form':form,'length_ft':length,'width_ft':width,'height_ft':height,
            'rotation':int(rotation),'material_source':material,'legal_load':load},cells


def lifetime(ctx,feature,group):
    from .effect_durations import round_token
    condition=ACTIVE if feature==BASTION else WORK
    ctx.engine._apply_condition(ctx.actor,condition,ctx.source,ctx.actor.entity_id,
        expires_on=round_token(ctx.engine,10 if feature==BASTION else 600),
        data={'group':group,'label':('Imperial Bastion — 1 minute, Concentration' if feature==BASTION else 'Mason structure — 1 hour')})
    return next(c for c in reversed(list(ctx.actor.conditions.values())) if c.condition_id==condition and c.data.get('group')==group)


def put_section(ctx,feature,declaration,position,group,condition,*,part=0):
    numbers=ctx.numbers;cl=int(numbers['cl']);pb=int(numbers['pb'])
    greater=feature==GREATER;bastion=feature==BASTION
    resist=['BLUDGEONING','PIERCING','SLASHING']
    if bastion:resist=['ACID','BLUDGEONING','COLD','FIRE','LIGHTNING','NECROTIC','PIERCING','POISON','RADIANT','SLASHING','THUNDER']
    form=declaration['form']
    profile={'name':('Bastion ' if bastion else '')+form,'kind':'barrier' if feature==BARRIER else 'structure',
        'ac':18 if bastion else 17 if greater else 15,'hp':(6 if bastion else 8 if greater else 4)*cl,
        'threshold':(2 if greater or bastion else 1)*pb,'source_cl':cl,'group':group,
        'height_ft':declaration['height_ft'],'resist':resist,'immune':['POISON','PSYCHIC']}
    component={**({'mechanism':{'name':'Gatehouse gate mechanism','open':0}} if declaration.get('gate_section') else {}),
        'mason':{'feature':feature,'form':form,'declaration':declaration,'part':part,
                'collapse_used':False},'structure':True,'target_full_height':True,'air_passage':bool(declaration.get('entrance')),'blocks':form in ('Low Wall','Tall Wall','Defensive Tower','Watchtower','Gatehouse') and not declaration.get('entrance'),
        'width_cells':max(1,(declaration['length_ft']+4)//5),
        'length_cells':max(1,(declaration['width_ft']+4)//5),'rotation':declaration['rotation'],
        'cover':'half' if form=='Low Wall' else 'three_quarters' if form in ('Defensive Tower','Watchtower') else 'total',
        'saving_throw_modifier':pb+int(numbers.get('key_mod',0)),
        'condition_immunities':['CHARMED','FRIGHTENED','POISONED','PRONE'],
        'speed_ft':0,'initiative':'creator_turn','command':'printed_source_only','legal_actions':[],
        'legal_reactions':[],'at_zero':'broken','size_ft':[declaration['length_ft'],declaration['width_ft']],
        'ordinary_route':form in ('Ramp','Platform','Ascending Stair','Defensive Tower','Watchtower','Gatehouse','Great Bridge','Bridge Section'),
        'support_height_ft':declaration['height_ft']}
    return assets.create(ctx.engine,ctx.actor,ctx.source,profile,position,component=component,lifetime=condition.instance_id)


def end_group(engine,owner,group,source,intent=None,*,relocate=False):
    works=family(engine,owner,group)
    if relocate:
        from ..falling import supported
        ids={o.object_id for o in works}
        roofs=[r for r in engine.grid.roof_surfaces if any(r.id.startswith(oid+':') for oid in ids)]
        remaining=assets.without_objects(engine,ids)
        levels={0,*[r.walk_ft//5 for r in remaining.grid.roof_surfaces]}
        for spans in remaining.grid.terrain_spans.get('BLOCKED',{}).values():
            levels.update(top//5 for bottom,top in spans if top is not None and top%5==0)
        for actor in engine.state.actors.values():
            if not actor.active or not any(r.walk_ft==actor.position.z*5 and r.solid_at(actor.position.x,actor.position.y) for r in roofs):continue
            occupied=engine._occupied_volumes_except(actor.entity_id)
            legal=[]
            for z in sorted(levels):
                for y in range(engine.grid.height):
                    for x in range(engine.grid.width):
                        p=Position(x=x,y=y,z=z)
                        if (supported(remaining,actor,p) and remaining.grid.volume_legal(p,footprint=engine._footprint(actor),occupied_cells=occupied)
                            and engine.grid.volume_legal(p,footprint=engine._footprint(actor),occupied_cells=occupied)):
                            legal.append(p)
            if not legal:raise ValueError('No legal support is available for occupants of the replaced structure.')
            nearest=min(engine.grid.distance_ft(actor.position,p) for p in legal)
            spaces={needle.cell_id(p):p for p in legal if engine.grid.distance_ft(actor.position,p)==nearest}
            chosen=pick(engine,actor,intent,'replacement_'+actor.entity_id,spaces,
                {k:f'Nearest legal support ({p.x}, {p.y}), {p.z*5} feet high' for k,p in spaces.items()},
                f'{actor.display_name}: choose the nearest legal support before the old structure disappears.')[0]
            needle.step_to(engine,actor,spaces[chosen],source)
    for obj in works:assets.retire(engine,obj,source)


@effect('mason_construction',harmful=False)
def construct(ctx,row):
    feature=row['feature'];engine,actor=ctx.engine,ctx.actor
    if not mason(engine,actor,feature):return
    position=ctx.intent.destination
    if position is None:raise ValueError('Choose the first structure space.')
    group=f'mason:{actor.entity_id}:{engine.state.event_sequence+1}'
    if feature==BASTION:
        if any(c.condition_id=='condition:typed.mason_scene_use' for c in actor.conditions.values()):
            raise ValueError('Raise the Imperial Bastion is limited to once per scene.')
        count=int(pick(engine,actor,ctx.intent,'count',('1','2','3','4'),{str(i):f'{i} sections' for i in range(1,5)},
            'Imperial Bastion: raise up to four sections, 8 Qi, 1 minute with Concentration.')[0])
        forms=('Low Wall','Tall Wall','Ramp','Platform','Watchtower','Bridge Section')
    else:count=1;forms=(row['form'],)
    # Resolve declarations before replacing any old structure.
    declarations=[]
    for index in range(count):
        form=pick(engine,actor,ctx.intent,f'form_{index}',forms,{f:f for f in forms},'Choose this Bastion section form.')[0] if feature==BASTION else forms[0]
        spot=position
        if index:
            spots={needle.cell_id(Position(x=x,y=y,z=position.z)):Position(x=x,y=y,z=position.z)
                for x,y in ((x,y) for y in range(engine.grid.height) for x in range(engine.grid.width)) if engine.grid.distance_ft(position,Position(x=x,y=y,z=position.z))<=40
                and assets.legal_placement(engine,[Position(x=x,y=y,z=position.z)],1)}
            choice=pick(engine,actor,ctx.intent,f'space_{index}',spots,{k:f'({p.x}, {p.y}, {p.z})' for k,p in spots.items()},
                'Choose an unoccupied supported space inside the Bastion cylinder.')[0]
            spot=spots[choice]
        declaration,cells=declare(ctx,feature,form,spot,index)
        if feature==BASTION and any(engine.grid.distance_ft(position,c)>40 or c.z*5+declaration['height_ft']>position.z*5+40 for c in cells):
            raise ValueError('Every section must fit the 40-foot-radius, 40-foot-high cylinder.')
        declarations.append((declaration,spot))
    if feature==GREATER:
        groups={o.component[assets.KEY]['group'] for o in family(engine,actor) if o.component['mason']['feature']==GREATER}
        for old in groups:end_group(engine,actor,old,ctx.source,ctx.intent,relocate=True)
    if feature==BARRIER:
        works=[o for o in family(engine,actor) if o.component['mason']['feature']==BARRIER]
        while len(works)>=int(ctx.numbers['pb']):
            oldest=min(works,key=lambda o:o.component[assets.KEY]['sequence']);assets.retire(engine,oldest,ctx.source);works.remove(oldest)
    if feature==BASTION:
        engine._start_concentration(actor,ctx.source)
    condition=lifetime(ctx,feature,group)
    for declaration,spot in declarations:
        if feature==GREATER:put_greater(ctx,declaration,spot,group,condition)
        else:put_section(ctx,feature,declaration,spot,group,condition)
    if feature==BASTION:
        allies=[a for a in engine.state.actors.values() if a.active and relation(engine,actor,a)==ALLY and engine.grid.distance_ft(position,a.position)<=40]
        chosen=pick(engine,actor,ctx.intent,'allies',[a.entity_id for a in allies],{a.entity_id:a.display_name for a in allies},
            'Imperial Bastion: choose allies who receive its protection while inside the cylinder.',decline=True,maximum=len(allies))
        condition.data.update({'chosen_allies':chosen,'center':position.model_dump(mode='json')})
        from .retained_updates import record_instance_update
        record_instance_update(engine,actor,'condition',condition.instance_id,condition)
        engine._apply_condition(actor,'condition:typed.mason_scene_use',ctx.source,actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Imperial Bastion used this scene'})



@hook('event',nested=True)
def masonry_lifecycle(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED':return
    payload=kwargs.get('payload') or {};iid=payload.get('instance_id')
    condition_id=payload.get('condition_id','');ended=set()
    for obj in list(assets.members(engine,live=False)):
        marker=obj.component[assets.KEY]
        if marker['lifetime']!=iid:continue
        assets.retire(engine,obj,marker['source'])
        if condition_id==ACTIVE:ended.add((obj.owner_id,marker['source']))
    # Duration and explicit scene ending also release this exact Concentration
    # copy, including a copy held behind another current technique.
    from .. import concentration
    for owner_id,source in ended:
        owner=engine.state.actors.get(owner_id)
        if owner is None:continue
        if owner.concentration is not None and owner.concentration.source_definition_id==source:
            engine._end_concentration(owner,'EFFECT_ENDED')
        for key,held in list(concentration.held(owner)):
            if held.source_definition_id==source:concentration.end_held(engine,owner,key,'EFFECT_ENDED')


@hook('object_hp_floor')
def bastion_cannot_collapse(engine,attacker,obj,taken,source):
    state=(obj.component or {}).get('mason')
    if not state or state['feature']!=BASTION or state['collapse_used'] or obj.destroyed or taken<int(obj.current_hp or 0):return
    state={**state,'collapse_used':True}
    after=obj.model_copy(update={'component':{**obj.component,'mason':state}})
    engine._update_object(after,source,obj.owner_id)
    # deal's final snapshot must include the consumed receipt as well.
    obj.component=after.component
    return 1


def adjacent(engine,actor,obj):
    from ..object_geometry import target_cells
    return any(engine.grid.distance_ft(actor.position,c)<=5 for c in target_cells(engine,obj))


def protected(engine,actor):
    for owner in engine.state.actors.values():
        if relation(engine,owner,actor)!=ALLY:continue
        if mason(engine,owner,CREW):
            for obj in family(engine,owner):
                if obj.component['mason']['feature'] in (BARRIER,GREATER) and adjacent(engine,actor,obj):yield obj,False
        for c in owner.conditions.values():
            if c.condition_id!=ACTIVE or actor.entity_id not in c.data.get('chosen_allies',[]):continue
            center=Position.model_validate(c.data['center'])
            if engine.grid.distance_ft(center,actor.position)>40 or not center.z<=actor.position.z<=center.z+8:continue
            for obj in family(engine,owner,c.data['group']):yield obj,True


@hook('save')
def fortress_save(ctx,target,ability,named):
    if {'prone','forced_movement'} & set(named or ()) and (next(protected(ctx.engine,target),None) or list(bastion_fields(ctx.engine,target))):return {'modes':['ADVANTAGE']}


@hook('stand_cost')
def fortress_stand(engine,actor,normal_cost):
    if any(not bastion for obj,bastion in protected(engine,actor)):return min(5,normal_cost)


@hook('climbing')
def fortress_climb(engine,actor):
    if any(adjacent(engine,actor,obj) and (b or obj.component.get('ordinary_route')) for obj,b in protected(engine,actor)):
        return {'climb_without_check':True}


def bastion_fields(engine,actor,*,contains=True):
    for owner in engine.state.actors.values():
        if relation(engine,owner,actor)!=ALLY:continue
        for c in owner.conditions.values():
            if c.condition_id!=ACTIVE or actor.entity_id not in c.data.get('chosen_allies',[]):continue
            center=Position.model_validate(c.data['center'])
            if not contains or engine.grid.distance_ft(center,actor.position)<=40 and center.z<=actor.position.z<center.z+8:
                yield c,center


@hook('difficult_exempt')
def bastion_terrain(engine,actor):
    cells=set()
    for condition,center in bastion_fields(engine,actor,contains=False):
        if not center.z<=actor.position.z<center.z+8:continue
        from .. import zones
        for zone in zones.typed_zones(engine):
            profile=zone.trigger_profile
            if not zone.active or not profile.get('difficult'):continue
            material=str((profile.get('visual') or {}).get('material') or '').lower()
            if material not in ('rubble','stone','earth','siege'):continue
            cells.update((c.x,c.y) for c in zone.affected_cells
                if engine.grid.distance_ft(center,Position(x=c.x,y=c.y,z=center.z))<=40)
    return cells


@hook('effect_cover')
def fortress_cover(engine,attacker,target,ray):
    if not ray.get('ranged') or ray.get('purpose')!='attack':return
    start=ray.get('start');end=ray.get('end')
    if start is None or end is None:return
    from ..object_geometry import target_cells
    # Only an actually intervening section grants this cover; adjacency alone
    # never grants it against attacks from the same side.
    for obj,b in protected(engine,target):
        for c in target_cells(engine,obj):
            dx=end[0]-start[0];dy=end[1]-start[1]
            denominator=dx*dx+dy*dy
            if not denominator:continue
            dot=(c.x-start[0])*dx+(c.y-start[1])*dy
            cross=(c.x-start[0])*dy-(c.y-start[1])*dx
            if not 0<dot<denominator or 4*cross*cross>denominator:continue
            height_numerator=start[2]*denominator+(end[2]-start[2])*dot
            if obj.position.z*5*denominator<=height_numerator*5<(obj.position.z*5+obj.height_ft)*denominator:return 2



def roll_work(engine,actor,numbers,reason):
    from ..gate2_runtime_models import DiceSpec
    roll=engine.roller.roll(DiceSpec(count=3,sides=8,modifier=int(numbers.get('key_mod',0))),
        actor_id=actor.entity_id,reason=reason)
    engine._record_roll(roll)
    return max(0,roll.total)


def intervention(engine,target,amount,source,attacker):
    from .. import typed_reactions
    from .rider_choices import intent_for
    from .choice_costs import payable
    from ..object_rules import label
    if amount<=0:return amount
    action=engine.action_catalog.get(source)
    if (action.parameters.get('typed',{}) if action else {}).get('destroys_artifacts') and (getattr(target,'component',None) or {}).get('artifact'):
        return amount
    for owner in engine.state.actors.values():
        row=mason(engine,owner,CREW)
        if not row:continue
        from . import ai_controlled
        if ai_controlled(engine,owner):
            from ..target_knowledge import located
            from ..senses import perceives_cell
            if (not located(engine,owner,target) if hasattr(target,'entity_id') else not perceives_cell(engine,owner,target.position)):continue
        if not row or not typed_reactions.can_react(engine,owner,{'feature_id':CREW}):continue
        if owner.turn_flags.get('mason_intervention_round_use')==engine.state.round_number:continue
        if engine.grid.distance_ft(owner.position,target.position)>60:continue
        payment=payable(owner,'resource:core.qi',2)
        if payment is None:continue
        target_id=getattr(target,'entity_id',None) or target.object_id
        name=getattr(target,'display_name',None) or label(target)
        chosen=needle.ask(engine,intent_for(engine),needle.checkpoint_id(engine,'mason_intervention',owner.entity_id,target_id,source),
            owner,needle.CHOICE+'mason_intervention',['protect'],labels={'protect':'Reaction and 2 Qi: reduce damage by 3d8 + key modifier'},
            name="Mason's Intervention",feature_id=CREW,target_id=target_id,allow_decline=True,payment=payment,
            prompt=f"Mason's Intervention: {name} takes {amount} damage from {action.display_name if action else 'an ongoing effect'}. Spend your Reaction and 2 Qi to reduce it by 3d8 + key modifier? Once per round.")
        if not chosen:continue
        payment.pay(engine,owner,CREW);typed_reactions.spend_reaction(engine,owner,{'feature_id':CREW})
        owner.turn_flags['mason_intervention_round_use']=engine.state.round_number
        reduced=min(amount,roll_work(engine,owner,row['numbers'],'MASON_INTERVENTION'))
        amount-=reduced
        engine._append_event('REACTION_RESOLVED',CREW,actor_id=owner.entity_id,target_ids=(target_id,),
            payload={'ability':"Mason's Intervention",'reduction':reduced})
        if amount==0:
            if hasattr(target,'object_id'):
                engine._update_object(target.model_copy(update={'component':{**(target.component or {}),
                    'mason_trigger_protection':{'source':source,'attacker':getattr(attacker,'entity_id','')}}}),CREW,owner.entity_id)
            else:
                engine._apply_condition(target,'condition:typed.mason_trigger_protection',source,owner.entity_id,
                    expires_on='UNTIL_REMOVED',data={'trigger_source':source,'label':"Mason's Intervention: protected against this effect's forced movement or collapse"})
            allies=[a for a in engine.state.actors.values() if a.active and engine.grid.distance_ft(a.position,target.position)<=5]
            choices={a.entity_id:a.display_name for a in allies}
            recipient=pick(engine,owner,intent_for(engine),'intervention_step',choices,choices,
                f"Mason's Intervention stopped all damage to {name}. Choose one adjacent creature that may move 5 feet without provoking.",decline=True)
            if recipient:free_step(engine,engine.state.actors[recipient[0]],5,source,intent_for(engine))
            break
    return amount


@hook('object_damage_settlement')
def intervention_object(engine,attacker,obj,amount,source):
    return intervention(engine,obj,amount,source,attacker)


@hook('final_damage')
def intervention_construct(engine,target,amount,damage_type,source,attacker_id,intent):
    from .creature_kinds import matches
    if not matches(target,['construct']):return
    left=intervention(engine,target,amount,source,engine.state.actors.get(attacker_id))
    return {'reduction':amount-left} if left!=amount else None


@hook('object_operation_gate')
def intervention_object_motion(engine,actor,obj,operation,source,intent):
    marker=(obj.component or {}).get('mason_trigger_protection')
    if marker and marker['source']==source and operation in ('move','break'):return False


@hook('forced_movement_reduction')
def intervention_creature_motion(ctx,subject):
    if any(c.condition_id=='condition:typed.mason_trigger_protection' and c.data.get('trigger_source')==ctx.source for c in subject.conditions.values()):
        return int(ctx.forced_movement_distance_ft or 0)


@hook('technique_used')
def intervention_clear(ctx):
    for obj in list(ctx.engine.state.objects.values()):
        if (obj.component or {}).get('mason_trigger_protection'):
            comp=dict(obj.component);comp.pop('mason_trigger_protection')
            ctx.engine._update_object(obj.model_copy(update={'component':comp}),CREW,obj.owner_id)
    for actor in ctx.engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id=='condition:typed.mason_trigger_protection':ctx.engine._remove_condition_instance(actor,c.instance_id,CREW)


def free_step(engine,creature,feet,source,intent,*,near=None):
    from .granted_movement import choices,move
    routes=choices(engine,creature,feet)
    if near is not None:
        from ..object_geometry import target_cells
        structure_cells=[c for o in near for c in target_cells(engine,o)]
        routes=[r for r in routes if all(any(engine.grid.distance_ft(p,c)<=5 for c in structure_cells) for p in r.canonical_path)]
    options={r.candidate_id:r for r in routes}
    chosen=pick(engine,creature,intent,'free_step_'+creature.entity_id,options,
        {k:f'Move to ({r.destination.x}, {r.destination.y}, {r.destination.z}), {r.movement_cost_ft} feet' for k,r in options.items()},
        f'{creature.display_name} may move up to {feet} feet without provoking. Choose a path or decline.',decline=True)
    if chosen:move(engine,creature,options[chosen[0]],intent,feet,list(engine.state.actors),name="Mason's granted movement")


@hook('turn_start_choice')
def master_builder_command(engine,actor):
    from .rider_choices import intent_for
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition
    condition=next((c for c in actor.conditions.values() if c.condition_id==ACTIVE),None)
    if not condition or not mason(engine,actor,BASTION):return
    works=family(engine,actor,condition.data['group']);intent=intent_for(engine)
    if not works:return
    options=['Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender']
    selected=pick(engine,actor,intent,'command',options,{o:o for o in options},
        f'{actor.display_name}: Master Builder’s Command at the start of your turn. Choose Repair, Reconfigure, Raise New Work, Covered Advance or Brace the Defender; no Action or Qi cost.')
    if not selected:return
    operation=selected[0];row=mason(engine,actor,BASTION)
    action=next(a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and a.parameters.get('mason_build')==BASTION)
    ctx=te.Context(engine,actor,action,intent,action.parameters['typed'],[],None,{})
    if operation=='Repair':
        targets={o.object_id:o for o in engine.state.objects.values() if
            assets.repair_allowed(o,row['numbers']['cl']) and not o.destroyed and o.current_hp<o.maximum_hp and
            (o in works or o.object_kind.lower()=='cultivation_asset' and o.owner_id in engine.state.actors and relation(engine,actor,engine.state.actors[o.owner_id])==ALLY)}
        choices={k:(o.component or {}).get('name',o.object_kind) for k,o in targets.items()}
        chosen=pick(engine,actor,intent,'command_repair',choices,choices,'Repair one Bastion section or allied Asset for 3d8 + key modifier HP, up to maximum.',decline=True)
        if chosen:
            obj=targets[chosen[0]];hp=min(obj.maximum_hp,obj.current_hp+roll_work(engine,actor,row['numbers'],'MASTER_BUILDER_REPAIR'))
            engine._update_object(obj.model_copy(update={'current_hp':hp}),BASTION,actor.entity_id)
    elif operation=='Reconfigure':
        choices={o.object_id:o.component['name'] for o in works}
        chosen=pick(engine,actor,intent,'command_section',choices,choices,'Choose one section to move or rotate up to 15 feet while supported.',decline=True)
        if not chosen:return
        obj=engine.state.objects[chosen[0]]
        from ..object_geometry import target_cells
        states=reconfiguration_states(engine,obj)
        chosen=pick(engine,actor,intent,'command_reconfigure',states,{k:f'({o.position.x}, {o.position.y}), rotation {o.component["rotation"]} degrees' for k,o in states.items()},'Choose a supported path and orientation for this section.',decline=True)
        if chosen:
            engine._update_object(states[chosen[0]],BASTION,actor.entity_id)
            from .. import zones
            zones.sync_walls(engine)
    elif operation=='Raise New Work':
        center=Position.model_validate(condition.data['center'])
        cells={needle.cell_id(Position(x=x,y=y,z=center.z)):Position(x=x,y=y,z=center.z)
            for y in range(engine.grid.height) for x in range(engine.grid.width)
            if engine.grid.distance_ft(center,Position(x=x,y=y,z=center.z))<=40 and
            assets.legal_placement(engine,cell_rectangle(Position(x=x,y=y,z=center.z),10,1),3)}
        chosen=pick(engine,actor,intent,'command_new_work',cells,{k:f'Low Wall at ({p.x}, {p.y})' for k,p in cells.items()},
            'Create one temporary Low Wall, maintaining up to your Proficiency Bonus; it disappears with the Bastion.',decline=True)
        if not chosen:return
        temporary=[o for o in works if o.component['mason'].get('temporary')]
        while len(temporary)>=int(row['numbers']['pb']):
            old=min(temporary,key=lambda o:o.component[assets.KEY]['sequence']);assets.retire(engine,old,BASTION);temporary.remove(old)
        declaration,_=declare(ctx,BARRIER,'Low Wall',cells[chosen[0]],99)
        obj=put_section(ctx,BARRIER,declaration,cells[chosen[0]],condition.data['group'],condition)
        obj.component['mason']['temporary']=True
        engine._update_object(obj,BASTION,actor.entity_id)
    else:
        advance_works=family(engine,actor)
        allies={a.entity_id:a for a in engine.state.actors.values() if a.active and relation(engine,actor,a)==ALLY and
                (any(adjacent(engine,a,o) for o in advance_works) if operation=='Covered Advance' else engine.grid.distance_ft(actor.position,a.position)<=5)}
        chosen=pick(engine,actor,intent,'command_ally',allies,{k:a.display_name for k,a in allies.items()},
            f'{operation}: choose one {"willing ally along or adjacent to your structures" if operation=="Covered Advance" else "adjacent ally to gain +2 AC until your next turn"}.',decline=True)
        if not chosen:return
        ally=allies[chosen[0]]
        if operation=='Covered Advance':
            consent=pick(engine,ally,intent,'command_consent',('move',),{'move':'Accept movement up to 15 feet without provoking'},
                f'{ally.display_name}: accept Covered Advance? Move along or adjacent to the structures, up to 15 feet without provoking.',decline=True)
            if consent:free_step(engine,ally,15,BASTION,intent,near=advance_works)
        else:
            engine._apply_condition(ally,BRACE,BASTION,actor.entity_id,expires_on='START_OF_SOURCE_NEXT_TURN',
                data={'label':'Brace the Defender — +2 AC until the Mason’s next turn'})


@hook('ac')
def brace_ac(engine,target):
    return 2 if any(c.condition_id==BRACE for c in target.conditions.values()) else None


@hook('support_surface')
def masonry_support(engine,actor,position):
    from ..object_geometry import target_cells
    required={(x,y) for x,y in engine._actor_cells(actor,position)}
    for obj in assets.members(engine):
        if not (obj.component or {}).get('ordinary_route'):continue
        top=obj.position.z+(obj.height_ft+4)//5
        if position.z==top and required<={(c.x,c.y) for c in target_cells(engine,obj)}:return True


@effect('mason_native_declaration',harmful=False)
def masonry_declaration(ctx,row):
    """Ownership-only reviewed marker; native menus own every activation."""
    return None


@hook('choice_reactors')
def masonry_choosers(engine):
    if any(mason(engine,a,CREW) or mason(engine,a,BASTION) for a in engine.state.actors.values()):
        return list(engine.state.actors)
    return []


@hook('event',nested=True)
def bastion_concentration_ends(engine,event_type,kwargs):
    if event_type!='CONCENTRATION_ENDED':return
    owner=engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None:return
    source=kwargs.get('source_definition_id');started=(kwargs.get('payload') or {}).get('started_sequence',0)
    for c in list(owner.conditions.values()):
        if c.condition_id==ACTIVE and c.source_definition_id==source and c.applied_sequence>=started:
            engine._remove_condition_instance(owner,c.instance_id,source)


@hook('runtime_roof_surfaces')
def masonry_surfaces(engine):
    from ..object_geometry import target_cells
    result=[]
    for obj in assets.members(engine):
        if not obj.component.get('mason'):continue
        declaration=obj.component['mason']['declaration'];form=declaration['form']
        cells=target_cells(engine,obj)
        if declaration.get('floor_cells'):
            cells=[Position(x=x,y=y,z=obj.position.z) for x,y in declaration['floor_cells']]
        if form in ('Ramp','Ascending Stair'):
            axis='y' if declaration['rotation'] else 'x'
            extent=max(getattr(c,axis) for c in cells)-min(getattr(c,axis) for c in cells)+1
            origin=min(getattr(c,axis) for c in cells)
            for i in range(extent):
                height=max(5,((obj.height_ft*(i+1)//extent+4)//5)*5)
                group=[{'x':c.x,'y':c.y} for c in cells if getattr(c,axis)==origin+i]
                result.append({'id':obj.object_id+f':ramp:{i}','height_ft':obj.position.z*5+height,'cells':group})
        else:
            levels=[obj.height_ft]
            if form in ('Defensive Tower','Watchtower'):levels=[max(5,obj.height_ft//2),obj.height_ft]
            for index,height in enumerate(levels):
                result.append({'id':obj.object_id+f':level:{index}','height_ft':obj.position.z*5+height,
                    'cells':[{'x':c.x,'y':c.y} for c in cells]})
    return result


@hook('climbing')
def masonry_ordinary_routes(engine,actor):
    # A printed stair or ladder supplies an ordinary route for anyone, before
    # Fortress Crew's additional ally benefit is considered.
    if any(o.component.get('ordinary_route') and adjacent(engine,actor,o) for o in assets.members(engine)):
        return {'climb_without_check':True}


def journey_mason(session,aid,feature):
    bundle=session.state['actors'][aid]['bundle']
    return next((r for r in bundle.get('typed_passives',bundle.get('typed_passive_rows',[]))
        if r.get('block')=='mason_native' and feature in r.get('owned',[])),None)


@hook('journey_options')
def journey_work_options(session,aid):
    actor=session.state['actors'][aid]
    result=[]
    for action in actor['bundle'].get('action_catalog',[]):
        p=action.get('parameters') or {};feature=p.get('mason_build')
        if feature:
            result.append({'id':action['source_definition_id'],'kind':'mason_build','source':feature,
                'payload':{'source':feature,'form':p['mason_form']},'auto_select':0,
                'label':action['display_name']+' — declare exact position, dimensions, orientation, and material source; '+
                    ('8 Qi, 1 minute with Concentration, once per scene.' if feature==BASTION else f'{1 if feature==BARRIER else 4} Qi, 1 hour.')})
    return result or None


@hook('journey_command')
def journey_build(session,aid,kind,payload):
    if kind!='mason_build':return None
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    from types import SimpleNamespace
    source=payload.get('source')
    action=next((a for a in session.state['actors'][aid]['bundle'].get('action_catalog',[]) if
        (a.get('parameters') or {}).get('mason_build')==source and (a.get('parameters') or {}).get('mason_form')==payload.get('form')),None)
    require(action is not None,'This creature has not acquired that Mason form at its effective CL.')
    require(set(payload)==({'source','form','sections','chosen_allies'} if source==BASTION else {'source','form','sections'}),'Declare source, form, exact sections and Bastion allies when applicable.')
    require(isinstance(payload['sections'],list) and 1<=len(payload['sections'])<=(4 if source==BASTION else 1),
        'Choose one work, or up to four Bastion sections.')
    actor=session.state['actors'][aid];cost=8 if source==BASTION else 4 if source==GREATER else 1
    require(actor['resources'].get('resource:core.qi',0)>=cost,'Not enough Qi for this construction.')
    require(source!=BASTION or not actor['travel_uses'].get(BASTION),'Imperial Bastion has already been used in this scene.')
    geometry=JourneyAssetContext(session);owner=geometry.state.actors[aid];numbers=action['parameters']['typed']['numbers']
    group=f'journey:{session.state["journey_id"]}:{len(session.state["events"])}'
    ctx=SimpleNamespace(engine=geometry,actor=owner,source=action['source_definition_id'],numbers=numbers)
    lifetime=SimpleNamespace(instance_id=group)
    center=Position.model_validate(payload['sections'][0]['position'])
    if source==BASTION:
        require(isinstance(payload['chosen_allies'],list) and len(set(payload['chosen_allies']))==len(payload['chosen_allies']) and all(a in session.state['actors'] for a in payload['chosen_allies']),'Choose actual scene participants as designated allies.')
    for section in payload['sections']:
        require(set(section)=={'position','form','length_ft','width_ft','height_ft','rotation','material_source','legal_load'},'Declare all section dimensions, material and load.')
        form=section['form'];allowed=('Low Wall','Tall Wall','Ramp','Platform','Watchtower','Bridge Section') if source==BASTION else (payload['form'],)
        require(form in allowed,'Choose a printed form for this source.')
        require(form in FORMS,'Unknown Mason form.')
        for key,limit in zip(('length_ft','width_ft','height_ft'),FORMS[form]):
            require(type(section[key]) is int and 1<=section[key]<=limit,'Dimensions exceed the printed form.')
        if form in ('Low Wall','Tall Wall','Gatehouse','Watchtower','Bridge Section'):
            require(tuple(section[k] for k in ('length_ft','width_ft','height_ft'))==FORMS[form],'This printed form has fixed dimensions.')
        require(section['rotation'] in (0,90),'Choose a 0 or 90 degree orientation.')
        p=Position.model_validate(section['position']);reach=90 if source==BASTION else 60 if source==GREATER else 30
        require(session.grid.distance_ft(owner.position,p)<=reach,'Construction is beyond this feature’s range.')
        cells=cell_rectangle(p,section['length_ft'],section['width_ft'],section['rotation'])
        require(section['material_source'] in material_sources(geometry,cells),'Choose an actual committed terrain or structure material source.')
        if form=='Great Bridge':
            require(assets.stable(geometry,p) and assets.stable(geometry,cells[-1]),'A Great Bridge needs both endpoints supported.')
            require(section['legal_load'] in ('ordinary','unloaded'),'Declare a legal load before crossing.')
        if source==BASTION:
            require(all(session.grid.distance_ft(center,c)<=40 and center.z<=c.z and c.z*5+section['height_ft']<=center.z*5+40 for c in cells),'Every Bastion section must fit its cylinder.')
        declaration={k:v for k,v in section.items() if k!='position'}
        if source==GREATER:
            for old in family(geometry,owner):
                if old.component['mason']['feature']==GREATER:assets.retire(geometry,old,ctx.source)
        if source==BARRIER:
            existing=[o for o in family(geometry,owner) if o.component['mason']['feature']==BARRIER]
            while len(existing)>=int(numbers['pb']):
                old=min(existing,key=lambda o:o.component[assets.KEY]['sequence']);assets.retire(geometry,old,ctx.source);existing.remove(old)
        if source==GREATER:put_greater(ctx,declaration,p,group,lifetime)
        else:put_section(ctx,source,declaration,p,group,lifetime)
        deadline=session.clock()+(60 if source==BASTION else 3600)
        for obj in family(geometry,owner,group):
            marker={**obj.component[assets.KEY],'expires_num':deadline.numerator,'expires_den':deadline.denominator,
                **({'chosen_allies':payload['chosen_allies'],'center':center.model_dump(mode='json')} if source==BASTION else {})}
            geometry._update_object(obj.model_copy(update={'component':{**obj.component,assets.KEY:marker}}),ctx.source,aid)
    actor['resources']['resource:core.qi']-=cost
    if source==BASTION:actor['travel_uses'][BASTION]=1
    session.emit('MASON_CONSTRUCTION',aid,source=source,qi_cost=cost,economy='ACTION',
        text=f'{owner.display_name} spends {cost} Qi and raises the declared supported work.')
    return True


@hook('journey_elapsed')
def journey_work_expiry(session,aid,previous,seconds,moving_ids):
    from fractions import Fraction
    from ..journey_assets import JourneyAssetContext
    geometry=None
    for row in list(session.state.get('runtime_objects',{}).values()):
        marker=(row.get('component') or {}).get(assets.KEY)
        if row.get('owner_id')!=aid or not marker or row.get('destroyed'):continue
        if session.clock()>=Fraction(marker['expires_num'],marker['expires_den']):
            geometry=geometry or JourneyAssetContext(session)
            assets.retire(geometry,geometry.state.objects[row['object_id']],marker['source'])


@hook('journey_state_changed')
def journey_bind_works(session,aid):
    # Losing Concentration outside combat is a committed incapacitation fact,
    # never inferred from inactivity or from another participant's condition.
    if not session.state['actors'][aid]['incapacitated']:return
    from ..journey_assets import JourneyAssetContext
    geometry=JourneyAssetContext(session)
    for obj in assets.members(geometry,aid):
        if obj.component.get('mason',{}).get('feature')==BASTION:assets.retire(geometry,obj,BASTION)


@hook('journey_combat_bundle')
def journey_work_bundle(bundle,session,aid):
    from fractions import Fraction
    actor=session.state['actors'][aid];rows=[]
    for obj in session.state.get('runtime_objects',{}).values():
        if obj.get('owner_id')!=aid or obj.get('destroyed'):continue
        marker=(obj.get('component') or {}).get(assets.KEY)
        if not marker or not (obj.get('component') or {}).get('mason'):continue
        remaining=Fraction(marker['expires_num'],marker['expires_den'])-session.clock()
        if remaining>0:rows.append({'object':obj,'remaining_num':remaining.numerator,'remaining_den':remaining.denominator})
    used=bool(actor['travel_uses'].get(BASTION))
    if not rows and not used:return
    return {**bundle,'asset_anchor_setup':rows,'mason_scene_used':used}


@hook('match_initialize')
def journey_import_works(engine):
    from fractions import Fraction
    from .effect_durations import round_token
    found=False
    groups={}
    for bundle in getattr(engine,'typed_bundle_documents',[]):
        owner=engine.state.actors.get(bundle['actor_id'])
        if owner is None:continue
        if bundle.get('mason_scene_used') and mason(engine,owner,BASTION):
            engine._apply_condition(owner,'condition:typed.mason_scene_use',BASTION,owner.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Imperial Bastion used this scene'})
        for row in bundle.get('asset_anchor_setup',[]):
            from ..gate2_runtime_models import RuntimeObjectState
            obj=RuntimeObjectState.model_validate(row['object']);state=obj.component.get('mason',{})
            if obj.owner_id!=owner.entity_id or not mason(engine,owner,state.get('feature')):
                raise ValueError('Journey work must bind its actual acquired source and owner.')
            remaining=Fraction(row['remaining_num'],row['remaining_den'])
            rounds=max(1,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator))
            group=obj.component[assets.KEY]['group']
            key=(owner.entity_id,group)
            if key not in groups:
                is_bastion=state['feature']==BASTION
                if is_bastion:engine._start_concentration(owner,obj.component['created_by'])
                data={'group':group,'label':'Journey construction — remaining source duration'}
                if is_bastion:data.update(chosen_allies=obj.component[assets.KEY].get('chosen_allies',[]),center=obj.component[assets.KEY]['center'])
                engine._apply_condition(owner,ACTIVE if is_bastion else WORK,obj.component['created_by'],owner.entity_id,
                    expires_on=round_token(engine,rounds),data=data)
                groups[key]=next(reversed(owner.conditions.values()))
            c=groups[key]
            obj=obj.model_copy(update={'component':{**obj.component,assets.KEY:{**obj.component[assets.KEY],'lifetime':c.instance_id}}})
            engine._update_object(obj,obj.component['created_by'],owner.entity_id);found=True
    if found:
        from .. import zones
        zones.sync_walls(engine)
    return found or None


def reconstructable(engine,obj):
    if not obj.destroyed or not assets.repair_allowed(obj,0,material=True):return False
    marker=(obj.component or {}).get(assets.KEY)
    if marker and marker.get('lifetime'):
        owner=engine.state.actors.get(obj.owner_id)
        if owner is None or marker['lifetime'] not in owner.conditions:return False
    return True


@hook('compile_actions')
def mason_scene_declaration(info):
    if BASTION not in info['owned_ids'] or int(info['numbers']['cl'])<18:return
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f'action:typed.{info["short"]}.mason.scene_end',
        display_name='Mason: Declare the scene ended',owner_id=info['actor_id'],economy='NONE',
        resolution_kind='TYPED',target_kind='SELF',parameters={'player_only':True,
            'description':'Declare that this continuous meaningful situation has actually ended. Ends your Bastion and resets only its once-per-scene use; no Qi or other resources recover.',
            'typed':{'source':BASTION,'numbers':info['numbers'],'duration':{'kind':'instant'},
                     'effects':[{'type':'mason_scene_end'}],'riders':[]}})]


@effect('mason_scene_end',harmful=False)
def mason_scene_ended(ctx,row):
    confirmed=pick(ctx.engine,ctx.actor,ctx.intent,'scene_end',('ended',),
        {'ended':'Declare that the continuous meaningful situation has ended'},
        'Has this scene actually ended? This declaration ends your Imperial Bastion and resets its scene use. Waiting, resting or reloading alone does not end a scene.',decline=True)
    if not confirmed:return
    for c in list(ctx.actor.conditions.values()):
        if c.condition_id in (ACTIVE,'condition:typed.mason_scene_use'):
            ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,BASTION)
    from . import note
    note(ctx.engine,BASTION,ctx.actor,'The Mason declares this meaningful situation ended; Imperial Bastion may be used in the next scene.',
        details={'declaration_actor':ctx.actor.entity_id,'authority':'native_source_owner','source_scope':BASTION,
                 'expires':'next_scene','declaration':'scene_ended'})


@hook('journey_command')
def journey_mason_scene_end(session,aid,kind,payload):
    if kind!='mason_scene_end':return
    from ..journey import require
    require(any((a.get('parameters') or {}).get('mason_build')==BASTION for a in session.state['actors'][aid]['bundle'].get('action_catalog',[])),
        'This creature does not own Imperial Bastion.')
    require(set(payload)=={'ended','reason'} and payload['ended'] is True and isinstance(payload['reason'],str)
        and 0<len(payload['reason'].strip())<=500,'Declare that this meaningful situation ended and give its reason.')
    from ..journey_assets import JourneyAssetContext
    geometry=JourneyAssetContext(session)
    for obj in assets.members(geometry,aid):
        if obj.component['mason']['feature']==BASTION:assets.retire(geometry,obj,BASTION)
    session.state['actors'][aid]['travel_uses'].pop(BASTION,None)
    session.emit('MASON_SCENE_DECLARED_ENDED',aid,source=BASTION,authority='native_source_owner',reason=payload['reason'],expires='next_scene')
    return True


def put_greater(ctx,declaration,spot,group,condition):
    """Partition a printed structure into independently targetable sections.

    Towers use perimeter runs of at most ten feet, an ordinary entrance, and
    two walkable levels. Gatehouses use wall/gate/wall and an elevated walkway.
    Linear bridges and stairs partition their printed length every ten feet.
    Combat and elapsed-time journeys share this exact producer.
    """
    if declaration['form']=='Defensive Tower':
        floor=[(c.x,c.y) for c in cell_rectangle(spot,15,15)]
        # Entrance first prevents even a transient airtight sealed volume.
        parts=[(0,1,5,1,90,True),(0,0,10,1,0,False),(2,0,5,1,0,False),
               (0,2,10,1,0,False),(2,2,5,1,0,False),(2,1,5,1,90,False)]
        entrance_obj=None
        for index,(dx,dy,length,width,rotation,entrance) in enumerate(parts):
            p=Position(x=spot.x+dx,y=spot.y+dy,z=spot.z)
            d={**declaration,'length_ft':length,'width_ft':width,'rotation':rotation,'entrance':entrance,
               **({} if entrance else {})}
            made=put_section(ctx,GREATER,d,p,group,condition,part=index)
            if entrance:entrance_obj=made
        declaration_record={**entrance_obj.component['mason']['declaration'],'floor_cells':floor}
        entrance_obj=entrance_obj.model_copy(update={'component':{**entrance_obj.component,'mason':{**entrance_obj.component['mason'],'declaration':declaration_record}}})
        ctx.engine._update_object(entrance_obj,ctx.source,ctx.actor.entity_id)
        assets.refresh(ctx.engine)
        return
    length=declaration['length_ft'];offset=0
    while offset<length:
        part={**declaration,'length_ft':min(10,length-offset),
              **({'width_ft':1,'gate_section':offset==10} if declaration['form']=='Gatehouse' else {})}
        point=Position(x=spot.x+(offset//5 if not declaration['rotation'] else 0),
                       y=spot.y+(offset//5 if declaration['rotation'] else 0),z=spot.z)
        put_section(ctx,GREATER,part,point,group,condition,part=offset//10)
        offset+=10


def reconfiguration_states(engine,obj):
    """Every supported five-foot translation and both native orientations.

    Validate every intermediate full footprint and diagonal side footprint;
    one off-map option cannot abort the otherwise legal start-turn menu.
    """
    from ..object_geometry import target_cells,diagonal_swept_cells
    states={}
    for dx in range(-3,4):
        for dy in range(-3,4):
            for rotation in (0,90):
                x,y=obj.position.x+dx,obj.position.y+dy
                if not engine.grid.in_bounds((x,y)):continue
                p=Position(x=x,y=y,z=obj.position.z)
                proposed=obj.model_copy(update={'position':p,'component':{**obj.component,'rotation':rotation}})
                if engine.grid.distance_ft(obj.position,p)>15:continue
                steps=max(abs(dx),abs(dy),1);previous=obj.position;legal=True
                for i in range(1,steps+1):
                    at=Position(x=obj.position.x+round(dx*i/steps),y=obj.position.y+round(dy*i/steps),z=p.z)
                    moving=proposed.model_copy(update={'position':previous})
                    try:
                        cells=list(target_cells(engine,proposed.model_copy(update={'position':at})))
                        sx,sy=at.x-previous.x,at.y-previous.y
                        if sx and sy:
                            swept=diagonal_swept_cells(engine,moving,sx,sy)
                            if swept is None:legal=False;break
                            cells.extend(Position(x=cx,y=cy,z=p.z) for cx,cy in swept if (cx,cy) not in {(c.x,c.y) for c in cells})
                        if not assets.legal_placement(engine,cells,obj.height_ft,ignore=(obj.object_id,)):
                            legal=False;break
                    except ValueError:
                        legal=False;break
                    previous=at
                if legal:states[f'{p.x},{p.y},{rotation}']=proposed
    return states


@hook('journey_regions')
def masonry_journey_routes(session,cell):
    if not session.state.get('runtime_objects'):return
    from ..journey_assets import JourneyAssetContext
    from ..object_geometry import target_cells
    context=JourneyAssetContext(session);rows=[]
    for obj in assets.members(context):
        if not obj.component.get('ordinary_route'):continue
        if not obj.position.z<=cell.z<=obj.position.z+(obj.height_ft+4)//5:continue
        if any(max(abs(cell.x-c.x),abs(cell.y-c.y))<=1 for c in target_cells(context,obj)):
            rows.append({'id':obj.object_id+':route','kind':'vertical_surface','ordinary':True,
                'requires_support':True,'movement_cost':1,'source_object':obj.object_id})
    return rows


@hook('journey_step')
def masonry_journey_step(session,aid,old,nxt,regions):
    if any(row.get('source_object') in session.state.get('runtime_objects',{}) for row in regions):
        return {'supported_kinds':['vertical_surface']}
