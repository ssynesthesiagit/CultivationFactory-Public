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
    return not obj.destroyed and assets.repair_allowed(obj, 0,preview=True)


def reinforceable(obj: Any) -> bool:
    return not obj.destroyed and obj.current_hp is not None and obj.maximum_hp is not None and bool((obj.component or {}).get('structure') or (obj.component or {}).get('formation_anchor') or obj.object_kind.lower() in
        ('barrier','formation_anchor','formation_eye','formation_node','vehicle','cart','rowboat','ballista'))


@hook('compile_actions')
def repair_variants(info: dict[str, Any]) -> list[Any] | None:
    info={**info,'numbers':mason_path_numbers(info)}
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
        if not assets.repair_allowed(obj,int(ctx.numbers['cl']),material=mode=='reconstruct'):
            from . import note
            note(engine,REPAIRS,actor,'Emergency Repairs cannot restore this damage through ordinary Hit Point repair.',targets=(obj.object_id,))
            return True
        if not repair_authority(ctx,obj):return True
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
    if not repair_authority(ctx,obj):return True
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
    from ..object_geometry import aim_cells
    from ..relations import relation, ALLY
    for obj in ctx.engine.state.objects.values():
        marker=(obj.component or {}).get(MARKER)
        if not marker or obj.destroyed:
            continue
        owner=ctx.engine.state.actors.get(marker['owner'])
        if owner is not None and relation(ctx.engine, target, owner)==ALLY and marker['instance'] in owner.conditions and any(
                ctx.engine.grid.distance_ft(target.position,cell)<=5 for cell in aim_cells(ctx.engine,obj)):
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
    return [*rows,{'block':assets.KEY},{'block':'mason_native','owned':owned,'numbers':dict(info['numbers'])},*([{'block':'asset_mechanisms'}] if GREATER in owned else [])]


def mason(engine,actor,feature):
    return next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,())
                 if r.get('block')=='mason_native' and feature in r['owned']),None)


@hook('compile_actions')
def construction_actions(info):
    info={**info,'numbers':mason_path_numbers(info)}
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
                    'mason_build':feature,'mason_form':form,'expected_damage':0,'placement_surfaces':True,
                    **({'any_cell':True,'ai_empty_area_filter':False} if feature==GREATER else {'cell_placement':{}}),
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


def family(engine,owner,group=None,*,live=True):
    return [o for o in assets.members(engine,owner.entity_id,group,live=live) if (o.component or {}).get('mason')]


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
    geometry=replacement_preview(engine,actor) if feature==GREATER else engine
    return assets.legal_placement(geometry,[candidate.destination],1,observer=actor)


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
    geometry=replacement_preview(engine,actor) if feature==GREATER else engine
    if not assets.legal_placement(geometry,cells,height):
        raise ValueError(f'{form} needs unoccupied spaces connected to stable support.')
    if form=='Great Bridge':
        end=cells[-1]
        if not assets.stable(geometry,position) or not assets.stable(geometry,end):
            raise ValueError('Great Bridge requires stable support at both named endpoints.')
    sources=material_sources(engine,cells)
    if not sources:raise ValueError('Choose an actual stable terrain or structure material source.')
    material=pick(engine,actor,ctx.intent,f'material_{index}',sources,sources,
        f'{form}: choose its material source before raising it.')[0]
    load=''
    if feature==GREATER:
        load=pick(engine,actor,ctx.intent,f'load_{index}',('ordinary',),
            {'ordinary':'Declared legal load: creatures and their ordinary carried equipment'},
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
        'height_ft':declaration['height_ft'],'resist':resist,'immune':['POISON','PSYCHIC'],'forbid_airtight':int(feature==BARRIER)}
    component={**({'mechanism':{'name':'Gatehouse gate mechanism','open':0}} if declaration.get('gate_section') else {}),
        'mason':{'feature':feature,'form':form,'declaration':declaration,'part':part,
                'collapse_used':False},'structure':True,'forbid_airtight':int(feature==BARRIER),'target_full_height':True,'air_passage':bool(declaration.get('entrance')),'blocks':form in ('Low Wall','Tall Wall','Defensive Tower','Watchtower','Gatehouse') and not declaration.get('entrance'),
        'width_cells':max(1,(declaration['length_ft']+4)//5),
        'length_cells':max(1,(declaration['width_ft']+4)//5),'rotation':declaration['rotation'],
        'cover':'half' if form=='Low Wall' else 'three_quarters' if form in ('Defensive Tower','Watchtower') else 'total',
        'saving_throw_modifier':pb+int(numbers.get('key_mod',0)),
        'condition_immunities':['CHARMED','FRIGHTENED','POISONED','PRONE'],
        'speed_ft':0,'initiative':'creator_turn','command':'printed_source_only','legal_actions':[],
        'legal_reactions':[],'at_zero':'broken','size_ft':[declaration['length_ft'],declaration['width_ft']],
        'ordinary_route':('slope' if form in ('Ramp','Ascending Stair') else 'ladder') if form in ('Ramp','Platform','Ascending Stair','Defensive Tower','Watchtower','Gatehouse','Great Bridge','Bridge Section') else '',
        'route_surfaces_external':1,
        'profile_description':f"{declaration['length_ft']} feet long, {declaration['width_ft']} feet wide, {declaration['height_ft']} feet high; Source cultivation level {cl}; "+('1 minute, Concentration' if bastion else '1 hour')+('; declared legal load: creatures and their ordinary carried equipment' if greater else '')+('. '+form+' grants '+('Half Cover' if form=='Low Wall' else 'Three-Quarters Cover through arrow slits' if form in ('Defensive Tower','Watchtower') else 'Total Cover when it completely blocks sight and effect') if form in ('Low Wall','Tall Wall','Defensive Tower','Watchtower') else ''),
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
    # Native accepted-intent execution is atomic. Sequential Bastion sections
    # can support later sections; a pending/invalid choice rolls the whole
    # activation back. Greater replacement still declares before evacuation.
    condition=None
    if feature==BASTION:
        engine._start_concentration(actor,ctx.source)
        condition=lifetime(ctx,feature,group)
    declarations=[]
    for index in range(count):
        form=pick(engine,actor,ctx.intent,f'form_{index}',forms,{f:f for f in forms},'Choose this Bastion section form.')[0] if feature==BASTION else forms[0]
        spot=position
        if index:
            spots=field_support_spaces(engine,actor,ctx.action,position)
            choice=pick(engine,actor,ctx.intent,f'space_{index}',spots,{k:f'({p.x}, {p.y}, {p.z})' for k,p in spots.items()},
                'Choose an unoccupied supported space inside the Bastion cylinder.')[0]
            spot=spots[choice]
        declaration,cells=declare(ctx,feature,form,spot,index)
        if feature==BASTION and any(engine.grid.distance_ft(position,c)>40 or c.z*5+declaration['height_ft']>position.z*5+40 for c in cells):
            raise ValueError('Every section must fit the 40-foot-radius, 40-foot-high cylinder.')
        declarations.append((declaration,spot))
        if feature==BASTION:put_section(ctx,feature,declaration,spot,group,condition)
    if feature==GREATER:
        groups={o.component[assets.KEY]['group'] for o in family(engine,actor) if o.component['mason']['feature']==GREATER}
        for old in groups:end_group(engine,actor,old,ctx.source,ctx.intent,relocate=True)
    if feature==BARRIER:
        works=[o for o in maintained_family(engine,actor) if o.component['mason']['feature']==BARRIER and not o.component['mason'].get('temporary')]
        while len(works)>=int(ctx.numbers['pb']):
            oldest=min(works,key=lambda o:o.component[assets.KEY]['sequence']);assets.retire(engine,oldest,ctx.source);works.remove(oldest)
    if feature!=BASTION:
        condition=lifetime(ctx,feature,group)
        for declaration,spot in declarations:
            if feature==GREATER:put_greater(ctx,declaration,spot,group,condition)
            else:put_section(ctx,feature,declaration,spot,group,condition)
    if feature==BASTION:
        allies=[a for a in engine.state.actors.values() if a.active and relation(engine,actor,a)==ALLY]
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
    from ..object_geometry import aim_cells
    return any(engine.grid.distance_ft(actor.position,c)<=5 for c in aim_cells(engine,obj))


def protected(engine,actor):
    for owner in engine.state.actors.values():
        if relation(engine,owner,actor)!=ALLY:continue
        if mason(engine,owner,CREW):
            for obj in family(engine,owner):
                if obj.component['mason']['feature'] in (BARRIER,GREATER) and adjacent(engine,actor,obj):yield obj,False
        for c in owner.conditions.values():
            if c.condition_id!=ACTIVE or actor.entity_id not in c.data.get('chosen_allies',[]):continue
            center=Position.model_validate(c.data['center'])
            if engine.grid.distance_ft(center,actor.position)>40 or not center.z<=actor.position.z<center.z+8:continue
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
    component=getattr(target,'component',None) or {}
    declared=component.get('artifact_destruction_sources',[])
    printed=(action.parameters.get('typed',{}) if action else {}).get('source')
    if component.get('artifact') and (source in declared or printed in declared):return amount
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
        from ..object_geometry import aim_cells
        structure_cells=[c for o in near for c in aim_cells(engine,o)]
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
    options=['Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender']
    selected=pick(engine,actor,intent,'command',options,{o:o for o in options},
        f'{actor.display_name}: Master Builder’s Command at the start of your turn. Choose Repair, Reconfigure, Raise New Work, Covered Advance or Brace the Defender; no Action or Qi cost.')
    if not selected:return
    operation=selected[0];row=mason(engine,actor,BASTION)
    action=next(a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and a.parameters.get('mason_build')==BASTION)
    ctx=te.Context(engine,actor,action,intent,action.parameters['typed'],[],None,{})
    if operation=='Repair':
        targets={o.object_id:o for o in engine.state.objects.values() if
            assets.repair_allowed(o,row['numbers']['cl'],preview=True) and not o.destroyed and o.current_hp<o.maximum_hp and
            (o in works or assets.is_asset(o) and o.owner_id in engine.state.actors and relation(engine,actor,engine.state.actors[o.owner_id])==ALLY)}
        choices={k:(o.component or {}).get('name',o.object_kind) for k,o in targets.items()}
        chosen=pick(engine,actor,intent,'command_repair',choices,choices,'Repair one Bastion section or allied Asset for 3d8 + key modifier HP, up to maximum.',decline=True)
        if chosen:
            obj=targets[chosen[0]]
            if not assets.repair_allowed(obj,row['numbers']['cl']):return
            hp=min(obj.maximum_hp,obj.current_hp+roll_work(engine,actor,row['numbers'],'MASTER_BUILDER_REPAIR'))
            engine._update_object(obj.model_copy(update={'current_hp':hp}),BASTION,actor.entity_id)
    elif operation=='Reconfigure':
        choices={o.object_id:o.component['name'] for o in works}
        chosen=pick(engine,actor,intent,'command_section',choices,choices,'Choose one section to move or rotate up to 15 feet while supported.',decline=True)
        if not chosen:return
        obj=engine.state.objects[chosen[0]]
        from ..object_geometry import target_cells
        states=reconfiguration_states(engine,obj)
        chosen=pick(engine,actor,intent,'command_reconfigure',states,{k:f'({o.position.x}, {o.position.y}), {o.position.z*5} feet high, rotation {o.component["rotation"]} degrees' for k,o in states.items()},'Choose a supported path and orientation for this section.',decline=True)
        if chosen:
            engine._update_object(states[chosen[0]],BASTION,actor.entity_id)
            from .. import zones
            zones.sync_walls(engine)
    elif operation=='Raise New Work':
        center=Position.model_validate(condition.data['center'])
        cells=field_support_spaces(engine,actor,action,center,height=3)
        chosen=pick(engine,actor,intent,'command_new_work',cells,{k:f'Low Wall at ({p.x}, {p.y})' for k,p in cells.items()},
            'Create one temporary Low Wall, maintaining up to your Proficiency Bonus; it disappears with the Bastion.',decline=True)
        if not chosen:return
        temporary=[o for o in maintained_family(engine,actor) if o.component['mason'].get('temporary') and o.component[assets.KEY]['group']==condition.data['group']]
        while len(temporary)>=int(row['numbers']['pb']):
            old=min(temporary,key=lambda o:o.component[assets.KEY]['sequence']);assets.retire(engine,old,BASTION);temporary.remove(old)
        declaration,declared_cells=declare(ctx,BARRIER,'Low Wall',cells[chosen[0]],99)
        if any(engine.grid.distance_ft(center,p)>40 or p.z*5+3>center.z*5+40 for p in declared_cells):raise ValueError('Temporary work must fit the Bastion cylinder.')
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
            from ..fact_consent_admission import admit_choice
            consent=admit_choice(ctx,ally,BASTION,'covered_advance',condition.instance_id,['move'],
                labels={'move':'Accept movement up to 15 feet without provoking'},
                prompt=f'{ally.display_name}: accept Covered Advance? Move along or adjacent to the structures, up to 15 feet without provoking.',
                expires_on='END_OF_HOLDER_NEXT_TURN',readers=(actor.entity_id,),automatic_options=['move'])
            if consent:
                free_step(engine,ally,15,BASTION,intent,near=advance_works)
                from ..fact_consent_admission import CONDITION,canonical
                for c in list(ally.conditions.values()):
                    if c.condition_id==CONDITION and c.data.get('record')==canonical(consent):engine._remove_condition_instance(ally,c.instance_id,BASTION)
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
                # Independent damage sections retain the whole stair's slope.
                total=max(1,(declaration.get('slope_length_ft',declaration['length_ft'])+4)//5)
                offset=declaration.get('slope_offset_ft',0)//5
                rise=declaration.get('slope_height_ft',obj.height_ft)
                height=max(5,((rise*(offset+i+1)+total*5-1)//(total*5))*5)
                group=[{'x':c.x,'y':c.y} for c in cells if getattr(c,axis)==origin+i]
                result.append({'id':obj.object_id+f':ramp:{i}','height_ft':obj.position.z*5+height,'cells':group})
        else:
            levels=[obj.height_ft]
            if form=='Defensive Tower':levels=[max(5,obj.height_ft//2),obj.height_ft]
            for index,height in enumerate(levels):
                result.append({'id':obj.object_id+f':level:{index}','height_ft':obj.position.z*5+height,
                    'cells':[{'x':c.x,'y':c.y} for c in cells]})
    return result


@hook('climbing')
def masonry_ordinary_routes(engine,actor):
    # A printed stair or ladder supplies an ordinary route for anyone, before
    # Fortress Crew's additional ally benefit is considered.
    if assets.ordinary_route_near(engine,actor):return {'climb_without_check':True}


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
        require(type(section['rotation']) is int and section['rotation'] in (0,90),'Choose a 0 or 90 degree orientation.')
        p=Position.model_validate(section['position']);reach=90 if source==BASTION else 60 if source==GREATER else 30
        require(session.grid.distance_ft(owner.position,p)<=reach,'Construction is beyond this feature’s range.')
        cells=cell_rectangle(p,section['length_ft'],section['width_ft'],section['rotation'])
        require(section['material_source'] in material_sources(geometry,cells),'Choose an actual committed terrain or structure material source.')
        if form=='Great Bridge':
            require(assets.stable(geometry,p) and assets.stable(geometry,cells[-1]),'A Great Bridge needs both endpoints supported.')
        if source==GREATER:
            require(section['legal_load']=='ordinary','Declare the legal load of this Greater Structure before creatures cross.')
        if source==BASTION:
            require(all(session.grid.distance_ft(center,c)<=40 and center.z<=c.z and c.z*5+section['height_ft']<=center.z*5+40 for c in cells),'Every Bastion section must fit its cylinder.')
        declaration={k:v for k,v in section.items() if k!='position'}
        if source==GREATER:
            for previous_group in {o.component[assets.KEY]['group'] for o in family(geometry,owner) if o.component['mason']['feature']==GREATER}:
                journey_replace_group(session,geometry,owner,previous_group,ctx.source)
        if source==BARRIER:
            existing=[o for o in maintained_family(geometry,owner) if o.component['mason']['feature']==BARRIER and not o.component['mason'].get('temporary')]
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
    if source==BASTION:
        actor['travel_uses'][BASTION]=1
        due=session.clock()+6
        actor['mason_command_due']=[due.numerator,due.denominator]
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
        if row.get('owner_id')!=aid or not marker or marker.get('ended'):continue
        if marker.get('ended') or session.clock()>=Fraction(marker['expires_num'],marker['expires_den']):
            geometry=geometry or JourneyAssetContext(session)
            assets.retire(geometry,geometry.state.objects[row['object_id']],marker['source'])


@hook('journey_state_changed')
def journey_bind_works(session,aid):
    # Losing Concentration outside combat is a committed incapacitation fact,
    # never inferred from inactivity or from another participant's condition.
    if not session.state['actors'][aid]['incapacitated']:return
    from ..journey_assets import JourneyAssetContext
    geometry=JourneyAssetContext(session)
    groups={o.component[assets.KEY]['group'] for o in assets.members(geometry,aid,live=False) if o.component.get('mason',{}).get('feature')==BASTION}
    for obj in assets.members(geometry,aid,live=False):
        if obj.component[assets.KEY]['group'] in groups:assets.retire(geometry,obj,BASTION)


@hook('journey_combat_bundle')
def journey_work_bundle(bundle,session,aid):
    from fractions import Fraction
    actor=session.state['actors'][aid];rows=[]
    for obj in session.state.get('runtime_objects',{}).values():
        if obj.get('owner_id')!=aid:continue
        marker=(obj.get('component') or {}).get(assets.KEY)
        if not marker or marker.get('ended') or not (obj.get('component') or {}).get('mason'):continue
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
    return assets.reconstruction_allowed(engine,obj)


@hook('compile_actions')
def mason_scene_declaration(info):
    info={**info,'numbers':mason_path_numbers(info)}
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
              **({'slope_length_ft':length,'slope_height_ft':declaration['height_ft'],'slope_offset_ft':offset}
                 if declaration['form']=='Ascending Stair' else {}),
              **({'width_ft':1,'gate_section':offset==10} if declaration['form']=='Gatehouse' else {})}
        point=Position(x=spot.x+(offset//5 if not declaration['rotation'] else 0),
                       y=spot.y+(offset//5 if declaration['rotation'] else 0),z=spot.z)
        put_section(ctx,GREATER,part,point,group,condition,part=offset//10)
        offset+=10


def reconfiguration_states(engine,obj):
    """Supported native routes up to fifteen feet, or rotation at the same site.

    Breadth-first search retains legal routes around obstacles rather than
    requiring a clear straight line. Every swept volume is checked against real
    creatures/solids; the chosen route is persisted in the section snapshot.
    """
    from collections import deque
    from itertools import product
    from ..object_geometry import target_cells
    shadow=assets.without_objects(engine,(obj.object_id,));states={}
    def snapshot(p,rotation,path):
        return obj.model_copy(update={'position':p,'component':{**obj.component,'rotation':rotation,
            'mason':{**obj.component['mason'],'declaration':{**obj.component['mason']['declaration'],'rotation':rotation},'last_reconfiguration_path':[c.model_dump(mode='json') for c in path]}}})
    rotation=int(obj.component.get('rotation',0));start=obj.position
    other=90 if rotation==0 else 0
    rotated=snapshot(start,other,[start])
    oldcells=target_cells(shadow,obj)
    try:newcells=target_cells(shadow,rotated)
    except ValueError:newcells=()
    # Native right-angle rotation sweeps its bounding footprint.
    xs=[c.x for c in (*oldcells,*newcells)];ys=[c.y for c in (*oldcells,*newcells)]
    swept=[Position(x=x,y=y,z=start.z) for x in range(min(xs),max(xs)+1) for y in range(min(ys),max(ys)+1)]
    if newcells and assets.legal_placement(shadow,swept,obj.height_ft):states[f'{start.x},{start.y},{other}']=rotated
    queue=deque([(start,[start])]);seen={(start.x,start.y,start.z)}
    deltas=[d for d in product((-1,0,1),repeat=3) if any(d)]
    while queue:
        previous,path=queue.popleft()
        if len(path)>3:continue
        moving=snapshot(previous,rotation,path)
        for dx,dy,dz in deltas:
            x,y,z=previous.x+dx,previous.y+dy,previous.z+dz;key=(x,y,z)
            if key in seen or z<0 or not shadow.grid.in_bounds((x,y)):continue
            p=Position(x=x,y=y,z=z);proposed=snapshot(p,rotation,[*path,p])
            try:proposed_cells=target_cells(shadow,proposed)
            except ValueError:continue
            if not assets.legal_placement(shadow,proposed_cells,obj.height_ft):continue
            # The small translation sweeps the bounding native body. Checking
            # it without a support demand prevents corner/vertical tunnelling.
            cells=[*target_cells(shadow,moving),*proposed_cells]
            xs=[c.x for c in cells];ys=[c.y for c in cells];base=min(previous.z,z)
            volume=[Position(x=xx,y=yy,z=base) for xx in range(min(xs),max(xs)+1) for yy in range(min(ys),max(ys)+1)]
            if not assets.legal_placement(shadow,volume,obj.height_ft+abs(dz)*5,require_support=False):continue
            seen.add(key);queue.append((p,[*path,p]))
            token=f'{p.x},{p.y},{rotation}' if z==start.z else f'{p.x},{p.y},{z},{rotation}'
            states[token]=proposed
    return states


@hook('journey_regions')
def masonry_journey_routes(session,cell):
    if not session.state.get('runtime_objects') and not any(
        row.get('ordinary_route') in ('ladder','slope') for row in session.state['battlefield'].get('map_objects',())):return
    from ..journey_assets import JourneyAssetContext
    from ..object_geometry import target_cells
    context=JourneyAssetContext(session);rows=[]
    for obj in assets.ordinary_route_objects(context):
        if not obj.position.z<=cell.z<=obj.position.z+(obj.height_ft+4)//5:continue
        if any(max(abs(cell.x-c.x),abs(cell.y-c.y))<=1 for c in target_cells(context,obj)):
            rows.append({'id':obj.object_id+':route','kind':'vertical_surface','ordinary':True,
                'requires_support':True,'movement_cost':1,'source_object':obj.object_id})
    return rows


@hook('journey_step')
def masonry_journey_step(session,aid,old,nxt,regions):
    if not any(row.get('source_object') for row in regions):return
    from ..journey_assets import JourneyAssetContext
    ids={o.object_id for o in assets.ordinary_route_objects(JourneyAssetContext(session))}
    if any(row.get('source_object') in ids for row in regions):
        return {'supported_kinds':['vertical_surface']}


def repair_authority(ctx,obj):
    """Resolve the printed Source CL bands for cultivated construction targets.

    Ordinary objects require no contest. Superior authority (3+ CL higher)
    requires the shared Cultivation Check; explicit creator/absolute repair
    protections remain admission gates and cannot be erased by numerical CL.
    Restoring HP never changes the target's owner, function, trigger or source.
    """
    if not (obj.component or {}).get('repair_contested'):return True
    profile=assets.source_profile(ctx.engine,obj)
    if profile['source_cl']<int(ctx.numbers['cl'])+3:return True
    from ..save_dcs import save_dc
    owner=ctx.engine.state.actors.get(profile['owner'])
    dc=int((obj.component or {}).get('repair_save_dc') or (save_dc(ctx.engine,owner,'cultivation') if owner is not None else 10+profile['source_cl']//2))
    with ctx.engine.d20_scope({'kind':'check','check_kind':'cultivation','actor_id':ctx.actor.entity_id,
            'target_id':obj.object_id,'source_id':ctx.source,'source_actor_id':ctx.actor.entity_id,'dc':dc,
            'reason':'CULTIVATION_AUTHORITY'}):
        roll=ctx.engine.roller.d20(modifier=int(ctx.numbers['pb'])+int(ctx.numbers.get('key_mod',0)),
            actor_id=ctx.actor.entity_id,reason='CULTIVATION_CHECK:'+ctx.source)
    ctx.engine._record_roll(roll)
    success=roll.total>=dc
    ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(obj.object_id,),
        payload={'actor':roll.model_dump(mode='json'),'dc':dc,'success':success,'check':'Cultivation Check',
                 'against':'higher Source CL construction','source_cl':int(ctx.numbers['cl']),'opposed_source':'private cultivated construction' if obj.component.get('asset_declaration',{}).get('visibility')=='gm' else str(profile['source_cl'])})
    return success


@hook('journey_encounter_settled')
def journey_return_works(session,aid,engine,creature):
    """Export committed section damage and source clocks; never modify the fight."""
    if aid!=next(iter(session.state["actors"])):return
    from fractions import Fraction
    from ..journey_assets import JourneyAssetContext
    geometry=JourneyAssetContext(session)
    slots=max(1,len(engine.state.initiative_order))
    now=(engine.state.round_number-1)*slots+engine.state.current_slot_index
    for owner in engine.state.actors.values():
        if owner.entity_id not in session.state['actors']:continue
        actor=session.state['actors'][owner.entity_id]
        if any(c.condition_id=='condition:typed.mason_scene_use' for c in owner.conditions.values()):actor['travel_uses'][BASTION]=1
        # The encounter's source-owned objects are authoritative, including
        # destruction and the first-zero receipt. No pre-combat copy can heal.
        for obj in family(engine,owner,live=False):
            marker=obj.component[assets.KEY];condition=owner.conditions.get(marker.get('lifetime'))
            remaining=Fraction(0)
            if condition and str(condition.expires_on).startswith('START_OF_SLOT_AT:'):
                _,r,slot=condition.expires_on.split(':')
                remaining=max(Fraction(0),Fraction(((int(r)-1)*slots+int(slot)-now)*6,slots))
            deadline=session.clock()+remaining
            c={**obj.component,assets.KEY:{**marker,'expires_num':deadline.numerator,'expires_den':deadline.denominator}}
            copy=obj.model_copy(update={'component':c,**({'destroyed':True,'current_hp':0} if remaining<=0 else {})})
            geometry._update_object(copy,marker['source'],owner.entity_id)
    geometry.asset_runtime_refresh()


@hook('journey_snapshot_actor')
def journey_exported_actor(actor,session,aid,engine):
    # Omit ONLY source clocks which the preceding export has persisted. This
    # copy is for the continuation snapshot; the immutable encounter is intact.
    exported={c.instance_id for c in actor.conditions.values() if c.condition_id in (WORK,ACTIVE) and
        any(o.owner_id==actor.entity_id and o.component.get(assets.KEY,{}).get('lifetime')==c.instance_id
            for o in family(engine,actor,live=False))}
    exported.update(c.instance_id for c in actor.conditions.values() if c.condition_id=='condition:typed.mason_scene_use')
    exported.update(c.instance_id for c in actor.conditions.values() if c.condition_id==REINFORCED and
        any(o.component.get(MARKER,{}).get('instance')==c.instance_id for o in engine.state.objects.values()))
    exported.update(c.instance_id for c in actor.conditions.values() if c.condition_id==BRACE and
        c.source_actor_id in engine.state.actors and mason(engine,engine.state.actors[c.source_actor_id],BASTION))
    if not exported:return
    copy=actor.model_copy(deep=True)
    sources={actor.conditions[k].source_definition_id for k in exported}
    from ..concentration import held
    exported.update(k for k,state in held(actor) if state.source_definition_id in sources)
    copy.conditions={k:c for k,c in copy.conditions.items() if k not in exported}
    if copy.concentration is not None and copy.concentration.source_definition_id in sources:copy.concentration=None
    return copy


def within_work_range(engine,actor,obj,feet):
    """Use native physical target surfaces for a work's range, including decks."""
    from ..object_geometry import aim_cells
    return any(engine.grid.distance_ft(actor.position,p)<=feet for p in aim_cells(engine,obj))


@hook('journey_options')
def journey_repair_options(session,aid):
    if not journey_mason(session,aid,REPAIRS):return
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session);actor=context.state.actors[aid]
    rows=[]
    for obj in context.state.objects.values():
        if obj.current_hp is None or obj.maximum_hp is None or obj.current_hp>=obj.maximum_hp:continue
        if not within_work_range(context,actor,obj,5):continue
        if not assets.repair_allowed(obj,0,material=obj.destroyed,preview=True):continue
        if obj.destroyed and not reconstructable(context,obj):continue
        rows.append({'id':'mason_repair:'+obj.object_id,'kind':'mason_repair','auto_select':0,
            'payload':{'object_id':obj.object_id},'label':f"Emergency Repairs: {obj.component.get('name',obj.object_kind)} — Action, touch, 2 Qi, 3d8 + key modifier HP. Declare material source"+(' and sufficient reconstruction material.' if obj.destroyed else '.')})
    return rows or None


@hook('journey_command')
def journey_repair_work(session,aid,kind,payload):
    if kind!='mason_repair':return
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    from ..gate2_rolls import DeterministicRollAuthority
    from ..gate2_runtime_models import DiceSpec
    row=journey_mason(session,aid,REPAIRS)
    require(row is not None,'Acquire Emergency Repairs at CL6 before repairing structures.')
    require(set(payload) in ({'object_id','material_source'},{'object_id','material_source','sufficient_material'}),
        'Declare the exact object and material source, and sufficient material for complete reconstruction.')
    context=JourneyAssetContext(session);actor=context.state.actors[aid];obj=context.state.objects.get(payload['object_id'])
    require(obj is not None and within_work_range(context,actor,obj,5),'Repair Structure requires a qualifying target within touch range.')
    require(assets.repair_allowed(obj,row['numbers']['cl'],material=payload.get('sufficient_material') is True),'This damage requires specialist repair, creator permission, or sufficient reconstruction material.')
    require(not obj.destroyed or reconstructable(context,obj),'Reconstruction requires a live source lifetime and currently unoccupied, supported space.')
    require(payload['material_source'] in material_sources(context,__import__('combat.object_geometry',fromlist=['target_cells']).target_cells(context,obj)), 'Name an actual terrain or structure material source.')
    require(not obj.component.get('repair_contested'),'Resolve opposed cultivation repair through the native encounter Cultivation Check.')
    require(actor.resources.get('resource:core.qi',0)>=2,'Repair Structure costs 2 Qi.')
    actor.resources['resource:core.qi']-=2
    roll=DeterministicRollAuthority(f"{session.state['journey_id']}:{session.state['revision']}:{len(session.state['events'])}:{aid}:{REPAIRS}").roll(
        DiceSpec(count=3,sides=8,modifier=int(row['numbers'].get('key_mod',0))),actor_id=aid,reason=REPAIRS)
    session.emit('ROLL_RECORDED',aid,source=REPAIRS,roll=roll.model_dump(mode='json'))
    comp={**obj.component,'repair_declaration':{'actor':aid,'authority':'native_source_owner','source':REPAIRS,
        'material_source':payload['material_source'],'sufficient_material':payload.get('sufficient_material',False),'expiry':'this_repair'}}
    context._update_object(obj.model_copy(update={'current_hp':min(obj.maximum_hp,obj.current_hp+max(0,roll.total)),
        'destroyed':False,'component':comp}),REPAIRS,aid)
    context.asset_runtime_refresh()
    session.tick(6)
    session.emit('MASON_REPAIR',aid,source=REPAIRS,object_id=obj.object_id,qi_cost=2,economy='ACTION',
        text=f"{actor.display_name} spends 2 Qi and an Action repairing {obj.component.get('name',obj.object_kind)} for {roll.total} HP, capped at maximum.")
    return True


@hook('journey_options')
def journey_reinforce_options(session,aid):
    if not journey_mason(session,aid,REPAIRS):return
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session);actor=context.state.actors[aid]
    return [{'id':'mason_reinforce:'+obj.object_id,'kind':'mason_reinforce','auto_select':0,
        'payload':{'object_id':obj.object_id},'label':'Reinforce Position: '+obj.component.get('name',obj.object_kind)+
        ' — Bonus Action, 1 Qi, +2 AC and increases Damage Threshold by your Proficiency Bonus (hits below the threshold deal no damage) until your next turn (6 seconds in travel); adjacent allies have Advantage against Prone and forced movement.'}
        for obj in context.state.objects.values() if reinforceable(obj) and within_work_range(context,actor,obj,30)] or None


@hook('journey_command')
def journey_reinforce_work(session,aid,kind,payload):
    if kind!='mason_reinforce':return
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    row=journey_mason(session,aid,REPAIRS)
    require(row is not None and set(payload)=={'object_id'},'Acquire Emergency Repairs and choose one structure.')
    context=JourneyAssetContext(session);actor=context.state.actors[aid];obj=context.state.objects.get(payload['object_id'])
    require(obj is not None and reinforceable(obj) and within_work_range(context,actor,obj,30),'Reinforce a structure, Barrier, vehicle section or Formation Anchor within 30 feet.')
    require(not obj.component.get('repair_contested'),'Resolve opposed cultivation reinforcement through the native encounter.')
    require(actor.resources.get('resource:core.qi',0)>=1,'Reinforce Position costs 1 Qi.')
    actor.resources['resource:core.qi']-=1
    old=obj.component.get(MARKER,{})
    end=session.clock()+6;pb=int(row['numbers']['pb'])
    marker={'owner':aid,'ac':2,'threshold':pb,'expires_num':end.numerator,'expires_den':end.denominator,'source':REPAIRS}
    context._update_object(obj.model_copy(update={'ac':obj.ac-int(old.get('ac',0))+2,
        'damage_threshold':int(obj.damage_threshold or 0)-int(old.get('threshold',0))+pb,
        'component':{**obj.component,MARKER:marker}}),REPAIRS,aid)
    session.emit('MASON_REINFORCEMENT',aid,source=REPAIRS,qi_cost=1,economy='BONUS_ACTION',object_id=obj.object_id,
        text='Reinforce Position: +2 AC, Damage Threshold +PB, adjacent ally protection; expires at the next source turn.')
    return True


@hook('journey_elapsed')
def journey_reinforce_expiry(session,aid,previous,seconds,moving_ids):
    from fractions import Fraction
    from ..journey_assets import JourneyAssetContext
    context=None
    for raw in list(session.state.get('runtime_objects',{}).values()):
        marker=raw['component'].get(MARKER)
        if not marker or marker['owner']!=aid or 'expires_num' not in marker:continue
        if session.clock()<Fraction(marker['expires_num'],marker['expires_den']):continue
        context=context or JourneyAssetContext(session);obj=context.state.objects[raw['object_id']]
        comp=dict(obj.component);comp.pop(MARKER)
        context._update_object(obj.model_copy(update={'ac':obj.ac-marker['ac'],
            'damage_threshold':obj.damage_threshold-marker['threshold'],'component':comp}),marker['source'],aid)


@hook('match_initialize')
def journey_import_reinforcement(engine):
    from fractions import Fraction
    from .effect_durations import round_token
    found=False
    for obj in list(engine.state.objects.values()):
        marker=obj.component.get(MARKER)
        if not marker or 'expires_num' not in marker:continue
        owner=engine.state.actors.get(marker['owner'])
        if owner is None or not mason(engine,owner,REPAIRS):raise ValueError('Reinforcement requires its acquired source owner.')
        remaining=Fraction(marker['expires_num'],marker['expires_den'])
        # The journey bundle carries its clock origin alongside the snapshot.
        clock=next((b.get('mason_journey_clock',[0,1]) for b in engine.typed_bundle_documents if b['actor_id']==owner.entity_id),[0,1])
        remaining-=Fraction(*clock)
        if remaining<=0:
            comp=dict(obj.component);comp.pop(MARKER)
            engine._update_object(obj.model_copy(update={'ac':obj.ac-marker['ac'],'damage_threshold':obj.damage_threshold-marker['threshold'],'component':comp}),REPAIRS,owner.entity_id)
            continue
        rounds=max(1,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator))
        engine._apply_condition(owner,REINFORCED,REPAIRS,owner.entity_id,expires_on=round_token(engine,rounds),
            data={'object_id':obj.object_id,'label':'Reinforce Position — remaining source duration'})
        condition=next(reversed(owner.conditions.values()))
        imported={k:v for k,v in marker.items() if k not in ('expires_num','expires_den')};imported['instance']=condition.instance_id
        engine._update_object(obj.model_copy(update={'component':{**obj.component,MARKER:imported}}),REPAIRS,owner.entity_id)
        found=True
    return found or None


@hook('journey_combat_bundle')
def journey_reinforcement_clock(bundle,session,aid):
    if any(row['component'].get(MARKER,{}).get('owner')==aid for row in session.state.get('runtime_objects',{}).values()):
        return {**bundle,'mason_journey_clock':[session.clock().numerator,session.clock().denominator]}


def journey_active_bastion(session,aid):
    from fractions import Fraction
    rows=[r for r in session.state.get('runtime_objects',{}).values() if r.get('owner_id')==aid and
        r['component'].get('mason',{}).get('feature')==BASTION and not r['component'][assets.KEY].get('ended') and
        Fraction(r['component'][assets.KEY]['expires_num'],r['component'][assets.KEY]['expires_den'])>session.clock()]
    return rows


@hook('journey_time_gate')
def journey_builder_clock(session,seconds):
    from fractions import Fraction
    from ..journey import require
    for aid,actor in session.state['actors'].items():
        if not journey_active_bastion(session,aid) or actor['incapacitated']:continue
        due=Fraction(*actor.get('mason_command_due',[0,1]))
        require(session.clock()+seconds<=due,'Master Builder’s Command is due at the next source turn. Advance only to that time, then choose a command before advancing again.')


@hook('journey_options')
def journey_builder_options(session,aid):
    from fractions import Fraction
    if not journey_active_bastion(session,aid):return
    due=Fraction(*session.state['actors'][aid].get('mason_command_due',[0,1]))
    if session.clock()<due:return [{'id':'mason_next_turn','kind':'wait','auto_select':0,
        'payload':{'seconds':int(due-session.clock())},'label':'Advance to the next Mason turn; choose Master Builder’s Command.'}]
    return [{'id':'mason_command:'+option,'kind':'mason_command','auto_select':0,'payload':{'command':option},
        'label':'Master Builder’s Command: '+option+' — declare the qualifying target, supported destination or willing ally route.'}
        for option in ('Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender')]


@hook('fact_admission_schema')
def journey_advance_consent_schema(session,source,subject,kind):
    if source!=BASTION or kind!='covered_advance':return
    if not any(journey_active_bastion(session,aid) for aid in session.state['actors']):return
    return {'value_type':'flag','maximum_seconds':6,'description':'Accept one exact Master Builder Covered Advance route; refusal remains legal.'}


@hook('journey_command')
def journey_builder_command(session,aid,kind,payload):
    if kind!='mason_command':return
    from fractions import Fraction
    from ..journey import require
    from ..journey_assets import JourneyAssetContext
    from ..gate2_rolls import DeterministicRollAuthority
    from ..gate2_runtime_models import DiceSpec
    rows=journey_active_bastion(session,aid);actor=session.state['actors'][aid]
    require(rows and session.clock()>=Fraction(*actor.get('mason_command_due',[0,1])),'Master Builder’s Command is available at the start of the source turn.')
    require(not actor['incapacitated'],'An incapacitated Mason cannot command the Bastion.')
    context=JourneyAssetContext(session);owner=context.state.actors[aid];row=journey_mason(session,aid,BASTION)
    require(row is not None,'Acquire Raise the Imperial Bastion.')
    group=rows[0]['component'][assets.KEY]['group'];works=family(context,owner,group)
    command=payload.get('command')
    allowed={'Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender'}
    require(command in allowed,'Choose one printed Master Builder command.')
    source=BASTION
    if command=='Repair':
        require(set(payload)=={'command','object_id'},'Choose one section or allied Asset.')
        obj=context.state.objects.get(payload['object_id'])
        require(obj is not None and (obj in works or assets.is_asset(obj) and obj.owner_id in session.state['actors']) and not obj.destroyed and assets.repair_allowed(obj,row['numbers']['cl']), 'Repair one live section or allied Asset; ordinary repair restrictions still apply.')
        roll=DeterministicRollAuthority(f"{session.state['journey_id']}:{session.state['revision']}:{source}:command").roll(
            DiceSpec(count=3,sides=8,modifier=int(row['numbers']['key_mod'])),actor_id=aid,reason=source)
        session.emit('ROLL_RECORDED',aid,source=source,roll=roll.model_dump(mode='json'))
        context._update_object(obj.model_copy(update={'current_hp':min(obj.maximum_hp,obj.current_hp+max(0,roll.total))}),source,aid)
    elif command=='Reconfigure':
        require(set(payload)=={'command','object_id','destination'},'Choose one section and supported destination/orientation.')
        obj=context.state.objects.get(payload['object_id']);require(obj in works,'Choose one of this Bastion’s sections.')
        states=reconfiguration_states(context,obj);key=payload['destination']
        require(key in states,'Move or rotate within 15 feet, fully supported and without passing through creatures.')
        context._update_object(states[key],source,aid);context.asset_runtime_refresh()
    elif command=='Raise New Work':
        require(set(payload)=={'command','section'},'Declare one Low Wall with exact geometry and material.')
        d=payload['section'];require(isinstance(d,dict) and set(d)=={'position','material_source','rotation'},'Declare Low Wall position, material source and orientation.')
        p=Position.model_validate(d['position']);center=Position.model_validate(rows[0]['component'][assets.KEY]['center'])
        require(context.grid.distance_ft(center,p)<=40 and center.z<=p.z<center.z+8,'Keep temporary work inside the Bastion cylinder.')
        require(type(d['rotation']) is int and d['rotation'] in (0,90) and d['material_source'] in material_sources(context,cell_rectangle(p,10,1,d['rotation'])),'Use a supported actual material source.')
        temporary=[o for o in maintained_family(context,owner) if o.component['mason'].get('temporary') and o.component[assets.KEY]['group']==group]
        while len(temporary)>=int(row['numbers']['pb']):
            old=min(temporary,key=lambda o:o.component[assets.KEY]['sequence']);assets.retire(context,old,source);temporary.remove(old)
        from types import SimpleNamespace
        ctx=SimpleNamespace(engine=context,actor=owner,numbers=row['numbers'],source=source)
        declaration={'form':'Low Wall','length_ft':10,'width_ft':1,'height_ft':3,'rotation':d['rotation'],'material_source':d['material_source'],'legal_load':''}
        obj=put_section(ctx,BARRIER,declaration,p,group,SimpleNamespace(instance_id=group))
        state={**obj.component['mason'],'temporary':True};marker={**obj.component[assets.KEY],**{k:rows[0]['component'][assets.KEY][k] for k in ('expires_num','expires_den','center','chosen_allies')}}
        context._update_object(obj.model_copy(update={'component':{**obj.component,'mason':state,assets.KEY:marker}}),source,aid)
    elif command=='Covered Advance':
        require(set(payload)=={'command','ally_id','path'},'Choose a willing ally and exact route up to 15 feet.')
        ally=payload['ally_id'];path=payload['path'];require(ally in session.state['actors'] and isinstance(path,list) and path,'Choose an actual ally and a nonempty route.')
        from ..fact_consent_admission import read,canonical
        scope=canonical({'group':group,'ally':ally,'path':path})
        consent=read(session,BASTION,ally,'covered_advance',scope,aid)
        require(consent is not None and consent['value']==1,'The ally’s controller must declare source-scoped acceptance of this exact Covered Advance route.')
        old=Position.model_validate(session.state['actors'][ally]['position']);distance=0
        for raw in path:
            p=Position.model_validate(raw);session.step_profile(ally,old,p);distance+=context.grid.distance_ft(old,p)
            require(distance<=15 and any(context.grid.distance_ft(p,c)<=5 for o in family(context,owner) for c in __import__('combat.object_geometry',fromlist=['aim_cells']).aim_cells(context,o)),'Covered Advance follows or stays adjacent to the structures for at most 15 feet.')
            old=p
        session.state['actors'][ally]['position']=old.model_dump(mode='json')
        session.emit('GRANTED_MOVEMENT',ally,source=source,feet=distance,no_opportunity_attacks=1,path=path)
    else:
        require(set(payload)=={'command','ally_id'},'Choose one adjacent ally.')
        ally=payload['ally_id'];require(ally in context.state.actors and context.grid.distance_ft(owner.position,context.state.actors[ally].position)<=5,'Brace one adjacent ally.')
        end=session.clock()+6
        actor.setdefault('mason_journey_braces',{})[ally]=[end.numerator,end.denominator]
    due=session.clock()+6;actor['mason_command_due']=[due.numerator,due.denominator]
    session.emit('MASTER_BUILDER_COMMAND',aid,source=source,command=command,group=group,text='Master Builder’s Command: '+command)
    return True


@hook('choice_reactors')
def mason_manual_reaction_owners(engine):
    from ..tabletop_service import MANUAL_MODES
    modes=getattr(engine,'typed_control_modes',{}) or {}
    return tuple(a.entity_id for a in engine.state.actors.values() if modes.get(a.entity_id) in MANUAL_MODES and mason(engine,a,CREW))


def continuation_seconds(engine,condition):
    from fractions import Fraction
    slots=max(1,len(engine.state.initiative_order));current=engine.state.current_slot_index
    name=str(condition.expires_on or '')
    if name.startswith('START_OF_SLOT_AT:'):
        _,r,slot=name.split(':')
        return max(Fraction(0),Fraction(((int(r)-engine.state.round_number)*slots+int(slot)-current)*6,slots))
    if name=='START_OF_SOURCE_NEXT_TURN' and condition.source_actor_id in engine.state.initiative_order:
        slot=engine.state.initiative_order.index(condition.source_actor_id)
        return Fraction((slot-current)%slots or slots,slots)*6
    return Fraction(0)


@hook('journey_encounter_settled')
def journey_return_reinforcement_and_brace(session,aid,engine,creature):
    if aid!=next(iter(session.state["actors"])):return
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session)
    for obj in list(engine.state.objects.values()):
        marker=obj.component.get(MARKER)
        if not marker:continue
        owner=engine.state.actors.get(marker['owner'])
        condition=owner.conditions.get(marker.get('instance')) if owner else None
        if condition is None:continue
        end=session.clock()+continuation_seconds(engine,condition)
        exported={**marker,'expires_num':end.numerator,'expires_den':end.denominator,'source':REPAIRS}
        context._update_object(obj.model_copy(update={'component':{**obj.component,MARKER:exported}}),REPAIRS,owner.entity_id)
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id!=BRACE or condition.source_actor_id not in session.state['actors']:continue
            end=session.clock()+continuation_seconds(engine,condition)
            session.state['actors'][condition.source_actor_id].setdefault('mason_journey_braces',{})[actor.entity_id]=[end.numerator,end.denominator]
    for aid,actor in session.state['actors'].items():
        if journey_active_bastion(session,aid):
            from fractions import Fraction
            slot=engine.state.initiative_order.index(aid);current=engine.state.current_slot_index;slots=len(engine.state.initiative_order)
            due=session.clock()+Fraction((slot-current)%slots or slots,slots)*6
            actor['mason_command_due']=[due.numerator,due.denominator]


@hook('journey_combat_bundle')
def journey_brace_bundle(bundle,session,aid):
    from fractions import Fraction
    braces=[]
    for target,end in session.state['actors'][aid].get('mason_journey_braces',{}).items():
        remaining=Fraction(*end)-session.clock()
        if remaining>0:braces.append({'target':target,'num':remaining.numerator,'den':remaining.denominator})
    if braces:return {**bundle,'mason_brace_setup':braces}


@hook('match_initialize')
def journey_import_brace(engine):
    from fractions import Fraction
    from .effect_durations import round_token
    found=False
    for bundle in getattr(engine,'typed_bundle_documents',[]):
        owner=engine.state.actors.get(bundle['actor_id'])
        for row in bundle.get('mason_brace_setup',[]):
            if owner is None or not mason(engine,owner,BASTION) or row['target'] not in engine.state.actors:
                raise ValueError('Brace the Defender requires its acquired source owner and actual recipient.')
            remaining=Fraction(row['num'],row['den']);rounds=max(1,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator))
            engine._apply_condition(engine.state.actors[row['target']],BRACE,BASTION,owner.entity_id,
                expires_on=round_token(engine,rounds),data={'label':'Brace the Defender — +2 AC, remaining source duration'})
            found=True
    return found or None


def journey_replacement_spaces(context,owner,group):
    from ..falling import supported
    works=family(context,owner,group);ids={o.object_id for o in works}
    roofs=[r for r in context.grid.roof_surfaces if any(r.id.startswith(oid+':') for oid in ids)]
    shadow=assets.without_objects(context,ids)
    levels={0,*[r.walk_ft//5 for r in shadow.grid.roof_surfaces]}
    for spans in shadow.grid.terrain_spans.get('BLOCKED',{}).values():
        levels.update(top//5 for bottom,top in spans if top is not None and top%5==0)
    choices={}
    for actor in context.state.actors.values():
        if not any(r.walk_ft==actor.position.z*5 and r.solid_at(actor.position.x,actor.position.y) for r in roofs):continue
        occupied={c for other in context.state.actors.values() if other.entity_id!=actor.entity_id for c in context._actor_volume(other)}
        legal=[]
        for z in sorted(levels):
            for y in range(context.grid.height):
                for x in range(context.grid.width):
                    p=Position(x=x,y=y,z=z)
                    if supported(shadow,actor,p) and shadow.grid.volume_legal(p,footprint=context._footprint(actor),occupied_cells=occupied) and context.grid.volume_legal(p,footprint=context._footprint(actor),occupied_cells=occupied):legal.append(p)
        if not legal:raise ValueError('The replaced structure has no nearest legal supporting space for an occupant.')
        distance=min(context.grid.distance_ft(actor.position,p) for p in legal)
        choices[actor.entity_id]=[p for p in legal if context.grid.distance_ft(actor.position,p)==distance]
    return choices


def journey_declared_replacement_spaces(session,context,owner,group):
    """Offer sequential legal choices after earlier controller declarations.

    This is a query-only preview. Earlier valid, source-scoped receipts reserve
    their proposed native volumes for later occupants' menus. Actual movement
    still revalidates every receipt sequentially in the committed transaction.
    A missing/invalid receipt supplies no reservation and grants no movement.
    """
    from copy import copy
    from ..fact_consent_admission import read
    preview=copy(context);preview.state=copy(context.state)
    preview.state.actors={aid:copy(actor) for aid,actor in context.state.actors.items()}
    result={}
    for aid in journey_replacement_spaces(context,owner,group):
        spaces=journey_replacement_spaces(preview,owner,group).get(aid,[])
        result[aid]=spaces
        receipt=read(session,GREATER,aid,'nearest_support',group,owner.entity_id)
        if receipt is None or set(receipt['value'])!={'position'}:continue
        try:p=Position.model_validate(receipt['value']['position'])
        except (ValueError,KeyError,TypeError):continue
        if p in spaces:preview.state.actors[aid].position=p
    return result


@hook('journey_options')
def journey_replacement_choices(session,aid):
    if not session.state.get('runtime_objects'):return
    from ..journey_assets import JourneyAssetContext
    from ..fact_consent_admission import canonical
    context=JourneyAssetContext(session);options=[]
    for owner in context.state.actors.values():
        groups={o.component[assets.KEY]['group'] for o in family(context,owner) if o.component['mason']['feature']==GREATER}
        for group in groups:
            for p in journey_declared_replacement_spaces(session,context,owner,group).get(aid,[]):
                options.append({'id':'mason_replacement:'+group+':'+needle.cell_id(p),'kind':'declare_fact','auto_select':0,
                    'payload':{'source':GREATER,'subject':aid,'kind':'nearest_support','scope':group,
                        'value':{'position':p.model_dump(mode='json')},'expires_at':int(session.clock())+6,'readers':[owner.entity_id]},
                    'label':f"If this Greater Structure is replaced, choose nearest legal support ({p.x}, {p.y}), {p.z*5} feet high. This choice expires in 6 seconds."})
    return options or None


@hook('fact_admission_schema')
def journey_nearest_support_schema(session,source,subject,kind):
    if source!=GREATER or kind!='nearest_support' or not session.state.get('runtime_objects'):return
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session)
    if not any(journey_mason(session,a,GREATER) and any(o.component['mason']['feature']==GREATER for o in family(context,context.state.actors[a])) for a in session.state['actors']):return
    return {'value_type':'document','maximum_seconds':6,'description':'Choose your own nearest legal supporting space before replacement.'}


def journey_replace_group(session,context,owner,group,source):
    from ..journey import require
    from ..fact_consent_admission import read
    choices=journey_replacement_spaces(context,owner,group)
    for aid in choices:
        # Earlier chosen relocations reserve their actual native volumes.
        # A conflicting receipt rejects the whole transaction; its controller
        # can choose again while the old structure still exists.
        spaces=journey_replacement_spaces(context,owner,group).get(aid,[])
        receipt=read(session,GREATER,aid,'nearest_support',group,owner.entity_id)
        require(receipt is not None and set(receipt['value'])=={'position'},'Each occupant must choose its own nearest legal supporting space before the Greater Structure is replaced.')
        p=Position.model_validate(receipt['value']['position'])
        require(p in spaces,'The occupant’s declared space is no longer nearest and legal; choose again.')
        session.state['actors'][aid]['position']=p.model_dump(mode='json')
        context.state.actors[aid].position=p
        session.emit('GREATER_STRUCTURE_REPLACEMENT_MOVEMENT',aid,source=source,group=group,position=p.model_dump(mode='json'),
            text=f"{context.state.actors[aid].display_name} moves to their chosen nearest legal support before the old work disappears.")
    for old in family(context,owner,group):assets.retire(context,old,source)



def mason_path_numbers(info):
    """Use the acquired Qi Path's explicit effective CL and key on multi-Path sheets."""
    numbers=dict(info['numbers']);sheet=info.get('owner_sheet') or {}
    qi=next((p for p in (sheet.get('path_and_subpath') or {}).get('paths',[]) if isinstance(p,dict) and p.get('path_id')=='tianxia.path.qi_cultivation'),None)
    if qi is None:return numbers
    numbers['cl']=int(qi['effective_cl'])
    key=str(qi.get('key_ability') or 'INT').upper()[:3]
    mods=info.get('mods')
    if mods is None:
        mods={a['ability']:int(a.get('modifier',(int(a['score'])-10)//2)) for a in (sheet.get('ability_scores_and_statistics') or {}).get('abilities',[])}
    numbers['key_mod']=int(mods.get(key,0));numbers['attack_bonus']=numbers['pb']+numbers['key_mod'];numbers['save_dc']=8+numbers['attack_bonus']
    return numbers


@hook('compile_bundle')
def mason_path_passives(bundle,info):
    paths=(info.get('owner_sheet',{}).get('path_and_subpath') or {}).get('paths',[])
    if not any(isinstance(p,dict) and p.get('path_id')=='tianxia.path.qi_cultivation' for p in paths):return
    rows=bundle.get('typed_passives',[]);existing=[r for r in rows if r.get('block')=='mason_native']
    if not existing:return
    numbers=mason_path_numbers(info);levels={BARRIER:3,REPAIRS:6,GREATER:10,CREW:14,BASTION:18}
    owned=[feature for r in existing for feature in r['owned'] if int(numbers['cl'])>=levels[feature]]
    remaining=[r for r in rows if r.get('block') not in ('mason_native','asset_mechanisms',assets.KEY)]
    if owned:remaining.append({'block':assets.KEY})
    if owned:remaining.append({'block':'mason_native','owned':list(dict.fromkeys(owned)),'numbers':numbers})
    if GREATER in owned:remaining.append({'block':'asset_mechanisms'})
    return {**bundle,'typed_passives':remaining}



def replacement_preview(engine,owner):
    """Pure placement view after the printed mandatory occupant evacuation.

    The final create still validates the actual committed positions after each
    occupant's choice. This view makes replacing a work at its own site legal.
    """
    from copy import copy
    works=[o for o in family(engine,owner) if o.component['mason']['feature']==GREATER]
    if not works:return engine
    ids={o.object_id for o in works}
    roofs=[r for r in engine.grid.roof_surfaces if any(r.id.startswith(oid+':') for oid in ids)]
    moving={a.entity_id for a in engine.state.actors.values() if any(r.walk_ft==a.position.z*5 and r.solid_at(a.position.x,a.position.y) for r in roofs)}
    shadow=assets.without_objects(engine,ids)
    actors={k:a for k,a in shadow.state.actors.items() if k not in moving}
    if hasattr(shadow.state,'model_copy'):shadow.state=shadow.state.model_copy(update={'actors':actors})
    else:
        shadow.state=copy(shadow.state);shadow.state.actors=actors
    return shadow


@hook('journey_scene_end')
def mason_native_scene_end(session,previous,current):
    """Consume the native table-owner boundary; never infer a scene from rest."""
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session)
    for aid,actor in session.state['actors'].items():
        groups={o.component[assets.KEY]['group'] for o in assets.members(context,aid,live=False)
            if o.component.get('mason',{}).get('feature')==BASTION}
        for obj in assets.members(context,aid,live=False):
            if obj.component[assets.KEY]['group'] in groups:assets.retire(context,obj,BASTION)
        actor['travel_uses'].pop(BASTION,None)
        actor.pop('mason_command_due',None);actor.pop('mason_journey_braces',None)



def field_support_spaces(engine,actor,action,center,*,height=1):
    from ..cell_placement import support_levels
    levels=support_levels(engine,actor,action,[center.z])
    spaces={}
    for z in levels:
        if not center.z<=z or z*5+height>center.z*5+40:continue
        for y in range(engine.grid.height):
            for x in range(engine.grid.width):
                p=Position(x=x,y=y,z=z)
                if engine.grid.distance_ft(center,p)<=40 and assets.legal_placement(engine,[p],height):spaces[needle.cell_id(p)]=p
    return spaces



def maintained_family(engine,owner):
    """Broken sections keep their source slot until retired or the source ends."""
    return [o for o in family(engine,owner,live=False) if not o.component[assets.KEY].get('ended')]
