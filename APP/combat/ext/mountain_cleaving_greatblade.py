"""Mountain-Cleaving Greatblade: source-owned paid declarations.

Weapons use the existing item catalog, physical identity, grip and packet resolver.
Lines use piercing_areas; choices, saves, conditions and object commits use native
transactions. No name or damage-type inference grants weapon classification.
"""
from copy import deepcopy
from dataclasses import replace
from contextvars import ContextVar
from contextlib import contextmanager
_DESCENT_MOTION=ContextVar("greatblade_descent_motion",default=None)
_LATERAL=ContextVar('greatblade_lateral',default=None)
_BOUND_ATTACK=ContextVar('greatblade_bound_attack',default=None)
from . import hook, effect
from ..relations import relation,ENEMY

P = 'tianxia.subpath.qi.mountain_cleaving_greatblade_cultivator.feature.'
STROKE = P+'mountain_weight_stroke'
SWEEP = P+'broadside_mountain_sweep'
LINE = P+'mountain_cutting_line'
DESCENT = P+'heaven_weight_descent'
DIVIDE = P+'divide_mountain_and_river'
LEVELS = {STROKE:3, SWEEP:6, LINE:10, DESCENT:14, DIVIDE:18}
QI = 'resource:core.qi'
LOCK = 'condition:typed.greatblade_committed'


def choose(ctx, key, labels, prompt, *, optional=False, preferred=None, target=None, maximum=1):
    from .needle import ask, checkpoint_id
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'greatblade_'+key, ctx.source,
        (target or ctx.actor).entity_id), ctx.actor, 'choice:needle.greatblade_'+key,
        list(labels), labels=labels, minimum=0 if optional else 1, maximum=maximum,
        allow_decline=optional, default='decline' if optional else 'first',
        preferred=preferred or ([] if optional else list(labels)[:1]),
        target_id=(target or ctx.actor).entity_id, name=ctx.action.display_name, prompt=prompt)


@hook('subpath_acquisition')
def acquire(source, sheet):
    if source != P.removesuffix('.feature.'):return None
    import hashlib
    from .qiweaving_common import rules_text
    identity=sheet.get('identity') or {}
    paths=sheet.get('path_and_subpath') or {}
    profiles=[r for r in paths.get('paths',[]) if isinstance(r,dict) and r.get('path_id')=='tianxia.path.qi_cultivation']
    profile=profiles[0] if len(profiles)==1 else {}
    attained=next((profile[k] for k in ('effective_cl','attainment','owning_path_level') if k in profile),None)
    # Open School has no special source permission, but requires actual Qi Path attainment.
    legal=type(attained) is int and attained>=3 and profile.get('subpath_or_tradition_id')==source
    provenance=profile.get('subpath_or_tradition_acquisition_provenance') or {}
    legal=bool(legal and provenance.get('canonical_content_id')==source and provenance.get('recorded') is True
        and provenance.get('schema')=='TianxiaFactory.AcquisitionProvenance.v1'
        and provenance.get('source') in {'initial-character-creation','post-creation-authority-selection'})
    cl=min(int(identity.get('cultivation_level') or 1),attained) if legal else 0
    printed=rules_text()
    return {'name':'Mountain-Cleaving Greatblade Cultivator','legal':legal,'effective_cl':cl,
        'reasons':[] if legal else ['Choose this Open School through your acquired Qi Cultivation Path at CL3 or higher. It grants no weapon proficiency.'],
        'features':[{'id':f,'minimum_cl':level,'text_sha256':hashlib.sha256(printed[f].encode()).hexdigest()} for f,level in LEVELS.items()]}


def greatblade(typed):
    from factory_authoring.starting_kits import item_definition
    if not typed.get('weapon'):return False
    item=item_definition(str(typed.get('source') or ''))
    family=str(item.get('weapon_family') or '').lower()
    return item.get('srd_name')=='Greatsword' or family in {'greatsword','heavy saber','execution blade','odachi','great cleaver','two-handed falchion','oversized cultivated blade'} or item.get('greatblade_family') is True


def damage(count,sides=8,*,kind=None,flat=None):
    return {'type':'damage','applies_to':'target','greatblade_cultivation_packet':1,'damage_bonus_packet':True,**({'flat':flat} if flat is not None else {'dice':{'count':count,'sides':sides}}),
        'damage_types':[kind] if kind else ['slashing','force']}


def prone():return {'type':'condition','condition':'prone','applies_to':'target'}
def deny(duration='until_start_of_its_next_turn'):
    return {'type':'greatblade_reaction_denied','edge':'end' if 'end' in duration else 'start'}
def push(feet,**kw):return {'type':'forced_movement','applies_to':'target','distance_ft':feet,'direction':'away',**kw}


@hook('compile_passives')
def passives(rows,info):
    owned=[f for f,l in LEVELS.items() if f in info['owned_ids'] and school_cl(info)>=l]
    return [*rows, *[{'block':'greatblade_school','feature_id':f,'numbers':{**info['numbers'],'cl':school_cl(info)},'choice_owner':True} for f in owned]]


def school_cl(info):
    cl=int(info['numbers']['cl'])
    for p in (info.get('owner_sheet',{}).get('path_and_subpath') or {}).get('paths',[]):
        if isinstance(p,dict) and p.get('path_id')=='tianxia.path.qi_cultivation':
            for key in ('effective_cl','attainment','owning_path_level'):
                if key in p:
                    value=p[key]
                    if type(value) is not int or value<0:raise ValueError('Qi Path attainment must be a nonnegative whole number.')
                    return min(cl,value)
            return cl
    return cl


def owns(engine,actor,feature):
    from .body_modes_scene_resources import available
    row=next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,[])
        if r.get('block')=='greatblade_school' and r.get('feature_id')==feature),None)
    return row if row and available(engine,actor,feature,LEVELS[feature],path_id='tianxia.path.qi_cultivation',compiled_level=int(row['numbers']['cl'])) else None


def weapons(engine,actor):
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed
    return {key:a for key,a in available_weapons(engine,actor).items()
        if greatblade(a.parameters.get('typed') or {}) and weapon_allowed(engine,actor,a) is not False}


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    cl=school_cl(info); owned=[f for f,l in LEVELS.items() if f in info['owned_ids'] and cl>=l]
    if not owned:return None
    out=[]
    blades=[a for a in info['actions'] if greatblade(a.parameters.get('typed') or {}) and '#' not in a.source_definition_id]
    common={'greatblade_owned':owned,'greatblade_numbers':dict(info['numbers'])}
    def make(feature,key,label,economy,target,reach,cost,effects,*,base=None,area=None):
        params=deepcopy(base.parameters) if base else {}
        typed=deepcopy(params.get('typed') or {})
        typed.pop('attack_action',None)
        typed['hold_victory_until_resolved']=True
        typed.update(source=feature,numbers={**info['numbers'],**((base.parameters.get('typed') or {}).get('numbers') or {}),'cl':cl} if base else {**info['numbers'],'cl':cl},effects=effects,riders=[],duration={'kind':'instant'})
        potency=next((r for r in info.get('passives',[]) if r.get('block')=='technique_potency' and r.get('resource_id')==QI),None)
        if cost and potency:typed['numbers']['potency']=int(potency['bonus_value'])
        if area:typed['area']=area
        else:typed.pop('area',None)
        if base:typed['weapon_source_id']=base.source_definition_id
        params.update(common,typed=typed,greatblade_mode=key,expected_damage=20,**({'any_cell':True} if target=='CELL' else {}),
            description=label+': '+economy.replace('_',' ').title()+f', {cost} Qi.' if cost else label)
        descriptions={
            'stroke':f'Use one weapon attack as a Committed Stroke. It must be your first weapon attack this turn. On a hit add {2+int(cl>=11)+int(cl>=17)}d8 Slashing or Force damage, doubling only that extra damage against the printed structural targets. After this attack your Speed is 0 and you cannot make another weapon attack until this turn ends. No extra Qi cost.',
            'sweep':f'Action, 3 Qi: choose creatures or objects in a 15-foot cone from you or your wielded Greatblade Domain Armament. Make a separate greatblade attack against each. A hit deals normal weapon damage plus {2+int(cl>=11)+int(cl>=17)}d8 Slashing or Force and pushes it 5 feet away if it is no more than one size larger. One activation for all recipients.',
            'line':f'Action, 5 Qi: a 60-foot-long, 10-foot-wide line. Dexterity save: {10 if cl>=17 else 8}d8 Slashing or Force, Prone and no Reactions until its next turn starts on failure; half damage on success. Structural targets take double damage; destroyed barriers open the cut, and a surviving blocking barrier stops it.',
            'divide':'Action, 8 Qi, once per scene: a 300-foot-long, 20-foot-wide line. Dexterity save: 12d10 Slashing or Force, Prone, movement to the nearest legal side and no Reactions until its next turn ends on failure; half damage, 5-foot side movement and no Reactions until its next turn starts on success. Structural targets take triple damage.',
            'descent':'Bonus Action, 4 Qi, once per turn: launch up to 60 feet to a visible legal point, then physically descend up to 60 feet toward a visible target. Avoid Opportunity Attacks and falling damage during this movement. Make one greatblade attack within normal weapon reach. A hit adds 6d8 Slashing, Force or Bludgeoning; Strength save for Prone, push and Reaction denial. Chosen hostile creatures within 10 feet then make Dexterity saves against 3d8 Force and Prone, half damage on success.'}
        if key in descriptions:params['description']=descriptions[key]
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.greatblade.{key}"+(('.'+base.source_definition_id) if base else ''),
            owner_id=info['actor_id'],display_name=label,economy=economy,resolution_kind='TYPED',target_kind=target,range_ft=reach,
            costs=((QI,cost),) if cost else (),parameters=params)
    extra=2+int(cl>=11)+int(cl>=17)
    for blade in blades:
        base=deepcopy(blade.parameters['typed']); attack=next((deepcopy(e) for e in base['effects'] if e.get('type')=='attack'),None)
        if attack is None:continue
        attack['count']=1
        attack['finish_on_hit_after_defeat']=True
        if STROKE in owned:
            stroke=deepcopy(attack)
            stroke['on_hit'].append({'type':'greatblade_stroke_hit'})
            stroke.update(object_target='unattended',object_native_weapon=True,object_on_hit_effects=['greatblade_stroke_hit'],object_before_effects=['greatblade_commit'],object_after_effects=['greatblade_lock'])
            effects=[{'type':'greatblade_commit'},stroke,{'type':'greatblade_lock'}]
            action=make(STROKE,'stroke','Committed Stroke: '+blade.display_name,'ACTION','ANY_CREATURE',blade.range_ft,0,effects,base=blade)
            out.extend([action,action.model_copy(update={'source_definition_id':action.source_definition_id+'#object','target_kind':'OBJECT','display_name':action.display_name+' (object)'})])
            for technique in info['actions']:
                if not base.get('proficient') or not conduction_eligible(technique):continue
                delivered=deepcopy(attack)
                if technique.target_kind=='OBJECT':
                    delivered.update(object_target='any',object_native_weapon=True,object_on_hit_effects=['greatblade_conduction_object_hit'])
                    delivered['on_hit'].append({'type':'greatblade_conduction_object_hit'})
                variant=make(STROKE,'conduction.'+technique.source_definition_id,technique.display_name+' through '+blade.display_name,
                    technique.economy,technique.target_kind,blade.range_ft,0,[delivered],base=blade)
                delivery=deepcopy(variant.parameters['typed'])
                original=deepcopy(technique.parameters['typed'])
                delivery={**original,**delivery,'source':original.get('source'),'duration':{'kind':'instant'},
                    'numbers':{**original.get('numbers',{}),'attack_bonus':base['numbers']['attack_bonus']}}
                params={**deepcopy(technique.parameters),**variant.parameters,'typed':delivery,
                    'greatblade_delivered_action':technique.source_definition_id,
                    'description':technique.display_name+' through '+blade.display_name+': pay the technique’s full cost plus 1 Qi. One weapon attack at normal reach. A miss spends the full cost and delivers no technique or save. A hit deals normal weapon damage, then delivers the technique once.'}
                out.append(variant.model_copy(update={'costs':tuple(technique.costs)+((QI,1),),
                    'concentration':technique.concentration,'parameters':params}))
        if SWEEP in owned:
            sweep=deepcopy(attack);sweep['on_hit']=[*sweep.get('on_hit',[]),{**damage(extra),'dice_by_cl':[[1,10,2,8],[11,16,3,8],[17,20,4,8]]},push(5,max_size_larger=1),{'type':'greatblade_guard'}]
            out.append(make(SWEEP,'sweep','Mountain Sweep: '+blade.display_name,'ACTION','CELL',15,3,
                [{'type':'greatblade_sweep','attack':sweep}],base=blade,area={'shape':'cone','size_ft':15}))
        if DESCENT in owned:
            descent=deepcopy(attack);descent['on_hit']=[*descent.get('on_hit',[]),{**damage(6),'damage_types':['slashing','force','bludgeoning']},
                {'type':'save','ability':'str','applies_to':'target','on_fail':[prone(),push(15,optional_distance_ft=True),deny()],'on_success':[push(5)]}]
            descent['object_on_hit_effects']=['greatblade_descent_object_hit']
            descent['on_hit'].append({'type':'greatblade_descent_object_hit'})
            descent_action=make(DESCENT,'descent','Descending Execution: '+blade.display_name,'BONUS_ACTION','ANY_CREATURE',120,4,
                [{'type':'greatblade_descent','attack':descent}],base=blade)
            out.extend([descent_action,descent_action.model_copy(update={'source_definition_id':descent_action.source_definition_id+'#object',
                'display_name':descent_action.display_name+' (object or surface)','target_kind':'OBJECT',
                'parameters':{**descent_action.parameters,'greatblade_descent_object':1}})])
    for f,key,label,feet,width,cost,count,sides in [(LINE,'line','Mountain-Cutting Line',60,10,5,10 if cl>=17 else 8,8),
            (DIVIDE,'divide','Divide Mountain and River',300,20,8,12,10)]:
        if f not in owned:continue
        aftermath=[prone(),deny('until_end_of_its_next_turn' if f==DIVIDE else 'until_start_of_its_next_turn'),
            {'type':'greatblade_cut_defense','whole':int(f==DIVIDE)}]
        if f==DIVIDE:aftermath.insert(1,{'type':'greatblade_lateral','nearest_side':1})
        save={'type':'save','ability':'dex','applies_to':'creatures_in_area',
            'on_fail':[{**damage(count,sides),**({'dice_by_cl':[[1,16,8,8],[17,20,10,8]]} if f==LINE else {})},*aftermath],
            'on_success':[{'type':'half_damage'},*([{'type':'greatblade_lateral','distance_ft':5},deny()] if f==DIVIDE else [])]}
        out.append(make(f,key,label,'ACTION','CELL',feet,cost,[{'type':'piercing_area','effects':[save],
            'creature_scope':'all','ignore_partial_cover':True,'object_multiplier':3 if f==DIVIDE else 2,
            'object_profile':'greatblade_line','wall_sections':True,'object_scope':'all'}],area={'shape':'line','size_ft':feet,'width_ft':width,'parallel_front':True,'explicit_harmful_recipients':'other_creatures'}))
    if ARMAMENT in info['owned_ids'] and cl>=9:
        out.append(make(ARMAMENT,'armament_attack','Bound Greatblade Domain Armament Attack','BONUS_ACTION','ANY_CREATURE',35 if armament_reach(info)==65 else 25,0,[{'type':'greatblade_bound_attack'}]))
        for technique in info['actions']:
            if not conduction_eligible(technique):continue
            original=deepcopy(technique.parameters['typed'])
            variant=make(STROKE,'armament_conduction.'+technique.source_definition_id,
                technique.display_name+' through bound Greatblade Domain Armament',technique.economy,technique.target_kind,
                35 if armament_reach(info)==65 else 25,0,[{'type':'greatblade_bound_attack'}])
            typed={**original,**variant.parameters['typed'],'source':original.get('source'),
                'numbers':{**original.get('numbers',{}),'cl':cl},'duration':{'kind':'instant'}}
            out.append(variant.model_copy(update={'costs':tuple(technique.costs)+((QI,1),),
                'concentration':technique.concentration,'parameters':{**deepcopy(technique.parameters),**variant.parameters,
                    'typed':typed,'greatblade_delivered_action':technique.source_definition_id,
                    'description':technique.display_name+': pay its full cost plus 1 Qi. Deliver once through the actual bound Greatblade in Assault Mode. Move it as for its floating attack, then attack within 5 feet. A miss spends the full cost and produces no delivered technique or save; on a hit resolve weapon damage before the technique.'}}))
        out.append(make(ARMAMENT,'armament_handle','Call or release bound Greatblade','BONUS_ACTION','SELF',0,0,[{'type':'greatblade_bound_handle'}]))
        out.append(make(ARMAMENT,'armament_end_bond','End real Greatblade bond','NONE','SELF',0,0,[{'type':'greatblade_end_bond'}]))
        out.append(make(ARMAMENT,'armament_move','Move Greatblade Domain Armament','NONE','SELF',0,0,[{'type':'greatblade_armament_move'}]))
    return out


def conduction_eligible(action):
    typed=action.parameters.get('typed') or {}
    return bool(any(pool==QI and n>0 for pool,n in action.costs) and action.target_kind in {'HOSTILE_ENTITY','ANY_CREATURE','ALLY_OR_SELF','OBJECT'}
        and 0<int(action.range_ft or 0)<=30 and not typed.get('area') and not typed.get('zone_spec') and not typed.get('weapon')
        and (typed.get('duration') or {}).get('kind') not in {'special','unknown'}
        and not any(e.get('type') in {'zone','summon','create_object','object_create','summon_creature','cultivation_asset','asset','create_zone','field','location'} for e in walk(typed.get('effects',[]))))


def walk(rows):
    for row in rows:
        if not isinstance(row,dict):continue
        yield row
        for k in ('on_fail','on_success','on_hit','effects'):
            yield from walk(row.get(k,[]) if isinstance(row.get(k,[]),list) else [])
        if isinstance(row.get('attack'),dict):yield from walk([row['attack']])


@hook('candidate_allowed')
def candidates(engine,actor,candidate,action):
    if action is None:return None
    mode=action.parameters.get('greatblade_mode','')
    locked=any(c.condition_id==LOCK for c in actor.conditions.values())
    typed=action.parameters.get('typed') or {}
    if locked and (mode=='armament_attack' or mode.startswith('armament_conduction.') or any(e.get('type')=='attack' for e in walk(typed.get('effects',[])))):return False
    if not mode:
        if action.parameters.get('armament')=='attack':
            from .qi_path import armament_condition
            held=armament_condition(actor)
            if held and held.data.get('bound_item_id') and owns(engine,actor,STROKE):return False
        return None
    if mode=='divide':
        from .body_modes_scene_resources import scene_record
        scene=scene_record(engine,actor,DIVIDE)
        if scene and scene.data.get('divide_used'):return False
    if mode=='stroke' and actor.turn_flags.get('greatblade_weapon_attacks'):return False
    if mode=='descent' and actor.turn_flags.get('greatblade_descent'):return False
    source=typed.get('source')
    required=STROKE if mode.startswith(('conduction.','armament_conduction.')) else {'stroke':STROKE,'sweep':SWEEP,'line':LINE,'descent':DESCENT,'divide':DIVIDE,'armament_attack':STROKE,'armament_handle':STROKE,'armament_end_bond':STROKE,'armament_move':STROKE}.get(mode)
    if required is None or not owns(engine,actor,required):return False
    if mode.startswith('armament_'):
        if not domain_access(engine,actor):return False
        if mode!='armament_move' and bond(engine,actor) is None:return False
        if mode=='armament_move' and (greatblade_armament(engine,actor) is None or actor.turn_flags.get('greatblade_armament_move') or engine.state.current_actor_id!=actor.entity_id):return False
        if mode=='armament_attack' or mode.startswith('armament_conduction.'):
            held=greatblade_armament(engine,actor)
            if held is None or held.data.get('mode')!='assault' or not candidate.metadata.get('effect_origin'):return False
    if source in LEVELS and not owns(engine,actor,source):return False
    if typed.get('weapon_source_id') and typed['weapon_source_id'] not in weapons(engine,actor):return False
    return None


@effect('greatblade_commit',harmful=False)
def commit(ctx,row):
    if ctx.actor.turn_flags.get('greatblade_weapon_attacks'):raise ValueError('Committed Stroke must be your first weapon attack this turn.')
    ctx.damage_cache['greatblade_commit']=1
    ctx.engine._apply_condition(ctx.actor,PENDING,ctx.source,ctx.actor.entity_id,expires_on='END_OF_CURRENT_TURN',
        data={'intent_id':ctx.intent.intent_id,'source':ctx.source,'label':'Committed Stroke declared before this attack.'})


@effect('greatblade_lock',harmful=False)
def lock(ctx,row):
    from ..typed_executor import run_effects
    if any(c.condition_id==LOCK for c in ctx.actor.conditions.values()):return
    ctx.engine._apply_condition(ctx.actor,LOCK,ctx.source,ctx.actor.entity_id,expires_on='END_OF_CURRENT_TURN',
        data={'rule':{'speed_zero':1},'intent_id':ctx.intent.intent_id,'label':'Committed Stroke: Speed 0 and no further weapon attacks until this turn ends.'})
    run_effects(ctx,[{'type':'speed','applies_to':'self','becomes':0,'duration':'until_end_of_turn'}])
    ctx.actor.movement_remaining_ft=0


@hook('attack_allowed')
def locked_attack(ctx,target,row):
    from .weapon_hits import is_weapon_hit
    if is_weapon_hit(ctx,row) and any(c.condition_id==LOCK for c in ctx.actor.conditions.values()):return False
    return None


@hook('event')
def count_attacks(engine,event_type,kwargs):
    if event_type!='ATTACK_ROLLED':return
    actor=engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or not owns(engine,actor,STROKE):return
    action=engine.action_catalog.get(kwargs.get('source_definition_id'))
    typed=action.parameters.get('typed') or {} if action else {}
    from ..weapon_delivery import delivery_kind
    attacks=[r for r in walk(typed.get('effects',[])) if r.get('type')=='attack']
    if any(delivery_kind(typed,r,action.parameters)=='weapon' for r in attacks) or typed.get('object_weapon') or action and action.parameters.get('greatblade_mode','').startswith(('armament_attack','armament_conduction.')):
        actor.turn_flags['greatblade_weapon_attacks']=int(actor.turn_flags.get('greatblade_weapon_attacks') or 0)+1


@effect('greatblade_stroke_hit')
def stroke_hit(ctx,row):
    from ..typed_executor import run_effects
    from .objects import deal
    obj=ctx.engine.state.objects.get(row.get('recipient_object_id'))
    bonus=damage(2+int(ctx.numbers['cl']>=11)+int(ctx.numbers['cl']>=17))
    if obj is not None:
        object_cleave(ctx,obj)


@hook('technique_start')
def conduction_declaration(engine,actor,action):
    if not action.parameters.get('greatblade_delivered_action') or action.target_kind=='OBJECT' or not (action.parameters.get('typed') or {}).get('weapon'):return None
    from ..typed_executor import Context,activation_reactions
    intent=getattr(engine,'_active_intent',None)
    if intent is None:raise ValueError('Greatblade Conduction requires a committed native activation intent.')
    targets=[engine.state.actors[k] for k in intent.target_ids if k in engine.state.actors]
    typed=deepcopy(action.parameters['typed'])
    return True if not activation_reactions(Context(engine,actor,action,intent,typed,targets,targets[0] if len(targets)==1 else None)) else None


def conduction(ctx):
    from ..typed_executor import run_effects
    source=ctx.action.parameters.get('greatblade_delivered_action')
    original=ctx.engine.action_catalog.get(source)
    if original is None or ctx.damage_cache.get('greatblade_conducted'):return
    ctx.damage_cache['greatblade_conducted']=1
    typed=deepcopy(original.parameters['typed'])
    if (typed.get('duration') or {}).get('concentration'):
        ctx.engine._start_concentration(ctx.actor,ctx.source)
    # The authorized weapon attack supplies delivery. The original technique's
    # attack payload is applied to this confirmed hit, without making another
    # attack or letting a miss produce its save/on-miss effects.
    effects=[]
    for effect in typed['effects']:
        effects.extend(effect.get('on_hit',[]) if effect.get('type')=='attack' else [effect])
    run_effects(replace(ctx,typed=typed,critical_hit=False,continue_after_defeat=True),effects)


@effect('greatblade_cleave')
def cleave(ctx,row):
    if ctx.target is not None:secondary_cleave(ctx,ctx.target)


@effect('greatblade_guard')
def guard(ctx,row):
    from ..typed_executor import run_effects
    if not owns(ctx.engine,ctx.actor,SWEEP) or ctx.target is None or ctx.actor.turn_flags.get('greatblade_guard') or ctx.actor.resources.get(QI,0)<1:return
    selected=choose(ctx,'guard',{'use':'Spend 1 Qi: Strength save; choose a guard-breaking consequence after the save.'},
        f'Break the Guard: {ctx.action.display_name} hit {ctx.target.display_name}. Spend 1 Qi, once per turn?',optional=True,target=ctx.target)
    if not selected:return
    run_effects(ctx,[{'type':'spend_resource','resource_id':QI,'flat':1,'applies_to':'self'}])
    ctx.actor.turn_flags['greatblade_guard']=1
    run_effects(ctx,[{'type':'save','ability':'str','applies_to':'target',
        'on_fail':[{'type':'greatblade_guard_result','failed':1}], 'on_success':[{'type':'greatblade_guard_result','failed':0}]}])


@effect('greatblade_guard_result')
def guard_result(ctx,row):
    from ..typed_executor import run_effects
    choices={'push':'Push 15 feet' if row['failed'] else 'Push 5 feet','reaction':'No Reactions until the start of its next turn'}
    if row['failed']:
        choices.update(prone='Knock Prone')
        if disarm_items(ctx):choices['disarm']='Drop one eligible held weapon, shield or implement'
        if shields(ctx.engine,ctx.target):choices['shield']='Reduce one shield AC bonus by 2 until your next turn starts'
    picked=choose(ctx,'guard_result',choices,f'Break the Guard: {ctx.target.display_name} '+('failed' if row['failed'] else 'succeeded')+' its Strength save. Choose one.',target=ctx.target)
    if not picked:return
    key=picked[0]
    effects={'push':[push(15 if row['failed'] else 5)],'reaction':[deny()],'prone':[prone()],
        'disarm':[{'type':'greatblade_disarm'}],
        'shield':[{'type':'greatblade_shield'}]}
    run_effects(ctx,effects[key])


@effect('greatblade_sweep')
def sweep(ctx,row):
    from ..typed_executor import in_area,block_attack,simultaneous
    from ..action_geometry import point
    from ..space import position
    from ..target_knowledge import located
    from ..senses import perceives_object
    from ..object_geometry import target_cells
    from ..object_rules import label
    from .objects import resolve_direct_attack
    origin=point(ctx.engine,ctx.actor);aim=ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    if aim is None:return
    all_targets={a.entity_id:a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
        and any(in_area(ctx.engine,origin,aim,position(p),ctx.typed['area']) for p in ctx.engine._actor_volume(a))}
    all_targets.update({o.object_id:o for o in ctx.engine.state.objects.values() if not o.destroyed and o.current_hp is not None
        and any(in_area(ctx.engine,origin,aim,p,ctx.typed['area']) for p in target_cells(ctx.engine,o))})
    known={k:a for k,a in all_targets.items() if (located(ctx.engine,ctx.actor,a) if hasattr(a,'entity_id') else perceives_object(ctx.engine,ctx.actor,a))}
    labels={k:(a.display_name if hasattr(a,'entity_id') else label(a)) for k,a in known.items()}
    labels['all']='Every creature and object in the cone, including unseen recipients'
    selected=choose(ctx,'sweep_targets',labels,'Mountain Sweep: choose recipients in the 15-foot cone. Each receives one separate greatblade attack. Total cost: 3 Qi.',
        optional=True,maximum=len(labels),preferred=[k for k,a in known.items() if hasattr(a,'team_id') and relation(ctx.engine,ctx.actor,a)==ENEMY])
    selected=list(all_targets) if 'all' in selected else selected
    with simultaneous(ctx,[a for a in all_targets.values() if hasattr(a,'entity_id')]):
        for key in selected:
            target=all_targets[key]
            if hasattr(target,'entity_id'):
                block_attack(replace(ctx,target=target,targets=[target]),{**row['attack'],'reach_ft':15})
            else:
                attack=deepcopy(row['attack'])
                attack['on_hit']=[e for e in attack['on_hit'] if e.get('weapon_damage')]+[{'type':'greatblade_sweep_object'}]
                attack['object_on_hit_effects']=['greatblade_sweep_object']
                resolve_direct_attack(ctx,target,attack)


@effect('greatblade_descent')
def descent(ctx,row):
    from ..typed_executor import block_attack,run_effects
    from ..granted_movement import routes,resolve_path,Route
    from ..senses import perceives_cell
    from ..target_knowledge import can_see
    from .condition_ownership import remove_instance
    actor,engine=ctx.actor,ctx.engine
    primary=ctx.target or ctx.damage_cache.get('_object')
    if primary is None:return
    from ..object_geometry import target_cells
    from ..senses import perceives_object
    creature=hasattr(primary,'entity_id')
    if not (can_see(engine,actor,primary) if creature else perceives_object(engine,actor,primary)):return
    def distance(point):
        return engine._distance_actor_to_actor(actor,primary,actor_position=point) if creature else min(engine.grid.distance_ft(point,p) for p in target_cells(engine,primary))
    before=set(actor.conditions)
    engine._apply_condition(actor,'condition:typed.greatblade_descent_motion',ctx.source,actor.entity_id,
        expires_on='END_OF_CURRENT_TURN',data={'fly_speed_ft':60,'flight_hover':1,
            'label':'Descending Execution: physical movement across open air; no falling damage during the sequence.'})
    marker=next(k for k in actor.conditions if k not in before)
    motion_token=_DESCENT_MOTION.set((id(engine),actor.entity_id))
    try:
        lift=routes(engine,actor,60,mode='fly')
        lift={str(i):(point,path,cost,mode) for i,(point,(path,cost,mode)) in enumerate(lift.items())
            if perceives_cell(engine,actor,point) and distance(point)<=60}
        # Remaining at the initial legal point is the printed zero-foot option.
        if distance(actor.position)<=60:
            lift['stay']=(actor.position,Route((actor.position,),'fly'),0,'fly')
        labels={k:f'Launch to {p.x}, {p.y}, altitude {p.z*5} feet (up to 60 feet)' for k,(p,_,_,_) in lift.items()}
        selected=choose(ctx,'descent_launch',labels,'Descending Execution: choose a visible legal launch point up to 60 feet away. Then descend up to 60 feet; this is physical movement and cannot cross barriers.') if labels else []
        if not selected:raise ValueError('No legal Descending Execution launch point.')
        point,path,_,mode=lift[selected[0]]
        resolve_path(engine,actor,path,ctx.source,feet=60,intent=ctx.intent,provokes=False,mode=mode)
        if actor.position!=point:return
        reach=int(ctx.typed.get('reach_ft') or 5)
        land=routes(engine,actor,60,mode='fly')
        land={str(i):(p,path,cost,mode) for i,(p,(path,cost,mode)) in enumerate(land.items())
            if p.z<=point.z and perceives_cell(engine,actor,p)
            and distance(p)<=reach}
        if distance(actor.position)<=reach:
            land['stay']=(actor.position,Route((actor.position,),'fly'),0,'fly')
        labels={k:f'Descend to {p.x}, {p.y}, altitude {p.z*5} feet, within weapon reach' for k,(p,_,_,_) in land.items()}
        selected=choose(ctx,'descent_land',labels,'Descending Execution: choose a visible legal landing up to 60 feet from the launch point and within weapon reach of the primary target.') if labels else []
        if not selected:raise ValueError('No legal landing within weapon reach.')
        endpoint,path,_,mode=land[selected[0]]
        resolve_path(engine,actor,path,ctx.source,feet=60,intent=ctx.intent,provokes=False,mode=mode)
        ctx.actor.turn_flags['greatblade_descent']=1
        if actor.position!=endpoint:return
        # The weapon attack uses its normal reach after both physical movements.
        if creature:block_attack(ctx,{**row['attack'],'reach_ft':reach})
        else:
            from .objects import resolve_direct_attack
            resolve_direct_attack(ctx,primary,row['attack'])
        targets={a.entity_id:a for a in engine.state.actors.values() if a.active and relation(engine,actor,a)==ENEMY
            and (engine._distance_actor_to_actor(primary,a)<=10 if creature else min(engine._distance_actor_to_cell(a,p) for p in target_cells(engine,primary))<=10)}
        from ..target_knowledge import located
        known={k:a for k,a in targets.items() if located(engine,actor,a)}
        labels={k:a.display_name for k,a in known.items()}
        labels['all']='Every hostile creature within 10 feet, including unseen recipients'
        selected=choose(ctx,'descent_burst',labels,
            'Descending Execution: choose hostile creatures within 10 feet of the primary target. Dexterity save: 3d8 Force and Prone on failure; half damage on success.',optional=True,maximum=len(labels),preferred=list(known))
        selected=list(targets) if 'all' in selected else selected
        burst={'type':'save','ability':'dex','applies_to':'target',
            'on_fail':[damage(3,kind='force'),prone()],'on_success':[{'type':'half_damage'}]}
        for key in selected:
            target=targets[key]
            run_effects(replace(ctx,target=target,targets=[target],critical_hit=False),[burst])
    finally:
        # Native removal settles any unsupported landing. The motion marker
        # remains until after that settlement so this descent takes no fall damage.
        try:remove_instance(engine,actor,marker,ctx.source)
        finally:_DESCENT_MOTION.reset(motion_token)


@effect('greatblade_descent_hit')
def descent_hit(ctx,row):
    from ..typed_executor import run_effects
    if ctx.target is None:return
    run_effects(ctx,[{**damage(6),'damage_types':['slashing','force','bludgeoning']},{'type':'save','ability':'str','applies_to':'target',
        'on_fail':[prone(),push(15,optional_distance_ft=True),deny()],'on_success':[push(5)]}])


@effect('greatblade_lateral')
def lateral(ctx,row):
    from ..gate2_runtime_models import Position
    from ..typed_executor import block_forced_movement,in_area
    from ..action_geometry import point
    if ctx.target is None:return
    from .general_combat_riders import DIRECTIONS
    engine,subject=ctx.engine,ctx.target
    origin=point(engine,ctx.actor);aim=ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    if aim is None:return
    area={**ctx.typed['area'],'spreads':True}
    occupied=engine._occupied_volumes_except(subject.entity_id)
    candidates={}
    # The Line's side is lateral to its axis. Select the nearest physically
    # reachable square outside the full width, using the native volume contract.
    ax,ay=aim.x-origin.x,aim.y-origin.y
    side=ax*(subject.position.y-origin.y)-ay*(subject.position.x-origin.x)
    for name,(dx,dy) in DIRECTIONS.items():
        cross=ax*dy-ay*dx
        if cross==0 or side and side*cross<=0:continue
        # Perpendicular headings, not an escape along the far end of the Line.
        if abs(ax*dx+ay*dy)>abs(cross):continue
        previous=subject.position
        for steps in range(1,max(engine.grid.width,engine.grid.height)+1):
            end=Position(x=subject.position.x+dx*steps,y=subject.position.y+dy*steps,z=subject.position.z)
            if end.x<0 or end.y<0 or not engine.grid.volume_step_legal(previous,end,
                occupied_cells=occupied,footprint=engine._footprint(subject)):break
            previous=end
            if not row.get('nearest_side') or not any(in_area(engine,origin,aim,Position(x=x,y=y,z=z),area)
                for x,y,z in engine._actor_volume(subject,position=end)):
                candidates[name]=(steps*5,dx,dy);break
    if not candidates:return
    if row.get('nearest_side'):
        nearest=min(v[0] for v in candidates.values())
        candidates={k:v for k,v in candidates.items() if v[0]==nearest}
    picked=choose(ctx,'line_side',{k:f'Move {subject.display_name} {k} '+str(v[0] if row.get('nearest_side') else 5)+' feet to the nearest legal side' for k,v in candidates.items()},
        'Divide Mountain and River: choose among the nearest legal sides of the Line. No additional cost.',target=subject)
    if not picked:return
    feet,dx,dy=candidates[picked[0]]
    token=_LATERAL.set((id(engine),subject.entity_id,(dx,dy)))
    try:block_forced_movement(ctx,{'type':'forced_movement','applies_to':'target',
        'distance_ft':feet if row.get('nearest_side') else 5,'direction':'away'})
    finally:_LATERAL.reset(token)


@hook('forced_movement_direction')
def lateral_direction(ctx,subject,feet):
    held=_LATERAL.get()
    return held[2] if held and held[:2]==(id(ctx.engine),subject.entity_id) else None


def cultivation_check(ctx,dc,key):
    from .ability_source import cultivation_check as resolve
    with ctx.engine.d20_scope({'kind':'check','actor_id':ctx.actor.entity_id,'source_id':ctx.source,
            'source_actor_id':ctx.actor.entity_id,'dc':dc}):
        return resolve(ctx.engine,ctx.actor,ctx.numbers,dc,ctx.source,'Cultivation Check: '+key)


@effect('greatblade_cut_defense')
def cut_defense(ctx,row):
    from . import end_effect as ee
    from ..target_knowledge import can_see
    if ctx.damage_cache.get('greatblade_cut_defense') or not can_see(ctx.engine,ctx.actor,ctx.target):return
    eligible=ee.found(ctx.engine,ctx.target,{'select':'beneficial','defensive_only':True})
    # Source-qualified native cultivation only; ordinary armor and unknown
    # table modifiers cannot manufacture a cultivation system or save DC.
    groups={}
    for kind,key,item in eligible:
        action=ee.source_action(ctx,item)
        typed=(action.parameters.get('typed') or {}) if action else {}
        if not typed.get('source') or not typed.get('numbers',{}).get('save_dc'):continue
        if kind=='condition' and (item.data.get('concealed') or item.data.get('hidden')):continue
        groups.setdefault(item.source_definition_id,[]).append((kind,key,item,typed,action))
    labels={key:items[0][4].display_name for key,items in groups.items()}
    picked=choose(ctx,'cut_defense',labels,f'{ctx.action.display_name}: choose one identified active defensive cultivation '+
        ('system' if row.get('whole') else 'effect')+f' on {ctx.target.display_name}, or pass.',optional=True,target=ctx.target) if labels else []
    if not picked:return
    ctx.damage_cache['greatblade_cut_defense']=1
    entries=groups[picked[0]];typed=entries[0][3]
    mine=int(ctx.numbers['cl']);source_cl=int(typed['numbers']['cl']);dc=int(typed['numbers']['save_dc'])
    target_cl=next((int(b['cl']) for b in ctx.engine.typed_bundle_documents if b['actor_id']==ctx.target.entity_id),source_cl)
    whole=bool(row.get('whole'));rounds=1;boundary='start';by=ctx.actor;repeat=False
    if not whole:
        if source_cl>=mine and not cultivation_check(ctx,dc,'defense'):return
        # CL10 suppresses one active effect only, never all benefits of a Path,
        # Foundation, Method or Core. Choose its exact native benefit instance.
        if len(entries)>1:
            names={key:ee.name(item,kind) for kind,key,item,_,_ in entries}
            selected=choose(ctx,'defensive_benefit',names,'Mountain-Cutting Line: choose one active defensive benefit to suppress until your next turn starts.',target=ctx.target)
            entries=[entry for entry in entries if entry[1] in selected]
    elif target_cl<=mine-5:boundary='scene'
    elif target_cl<=mine:
        rounds=10;boundary='end';by=ctx.target;repeat=True
    else:
        boundary='end'
        if not cultivation_check(ctx,dc,'defensive_system'):
            names={key:ee.name(item,kind) for kind,key,item,_,_ in entries}
            selected=choose(ctx,'defensive_benefit',names,'Divide Mountain and River: choose one defensive benefit to suppress until the end of your next turn.',target=ctx.target)
            entries=[entry for entry in entries if entry[1] in selected]
    keys=[]
    for kind,key,item,_,_ in entries:
        ee.suppress(ctx.target,kind,key,item,rounds=rounds,by=by,engine=ctx.engine,boundary=boundary)
        keys.append(key)
    if boundary=='scene':
        ctx.engine._apply_condition(ctx.target,'condition:typed.greatblade_scene_restoration',ctx.source,ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED',data={'keys':keys,'label':'Restore these suppressed defensive benefits when this scene ends.'})
    if repeat:
        ctx.engine._apply_condition(ctx.target,'condition:typed.greatblade_system_recovery',ctx.source,ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED',data={'keys':keys,'dc':int(ctx.numbers['save_dc']),
                'label':'Defensive cultivation suppressed for 1 minute; Constitution save at each turn end to recover.'})


@hook('turn_end')
def recover_system(engine,actor):
    from .end_effect import restore_suppressed,SUPPRESSED_FLAG
    from .condition_ownership import remove_instance
    for held in list(actor.conditions.values()):
        if held.condition_id!='condition:typed.greatblade_system_recovery':continue
        rows=[r for r in actor.turn_flags.get(SUPPRESSED_FLAG,[]) if r['key'] in held.data['keys']]
        if rows:
            roll=engine._roll_save(actor,'CON',int(held.data['dc']),held.source_definition_id)
            if roll is None or roll.total<int(held.data['dc']):continue
            for r in rows:restore_suppressed(engine,actor,r)
        remove_instance(engine,actor,held.instance_id,held.source_definition_id)


@hook('compile_bundle')
def school_scene_profile(bundle,info):
    if not any(r.get('block')=='greatblade_school' and r.get('feature_id')==DIVIDE for r in bundle.get('typed_passives',[])) or school_cl(info)<18:return None
    return {**bundle,'greatblade_scene_profile':{'source':DIVIDE,'name':'Divide Mountain and River',
        'feature_levels':{DIVIDE:18},'path_id':'tianxia.path.qi_cultivation','compiled_level':school_cl(info),
        'action_sources':[a['source_definition_id'] for a in bundle['action_catalog'] if a.get('parameters',{}).get('greatblade_mode')=='divide']}}


@hook('body_mode_profiles')
def native_scene_profile(bundle):
    return [deepcopy(bundle['greatblade_scene_profile'])] if bundle.get('greatblade_scene_profile') else None


@hook('technique_accepted')
def mark_divide(engine,actor,action):
    if action.parameters.get('greatblade_mode')!='divide':return
    from .body_modes_scene_resources import scene_record,set_record
    held=scene_record(engine,actor,DIVIDE)
    if held is None:raise ValueError('Divide Mountain and River requires its native scene state.')
    set_record(engine,actor,DIVIDE,{**held.data,'divide_used':1,'label':'Divide Mountain and River has been used in this scene.'})


@hook('save')
def defensive_saves(ctx,subject,ability,named):
    if owns(ctx.engine,subject,DESCENT) and bastion_implement(ctx.engine,subject) and 'prone' in set(named or []):
        return {'bonus':0,'modes':['ADVANTAGE']}
    if not owns(ctx.engine,subject,SWEEP) or not set(named or [])&{'grappled','restrained','forced_movement'}:return None
    enemies=[a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine,subject,a)==ENEMY
        and ctx.engine._distance_actor_to_actor(subject,a)<=5]
    if len(enemies)>=2 and ctx.actor in enemies:return {'bonus':0,'modes':['ADVANTAGE']}
    return None


@hook('forced_movement_reduction')
def bastion(ctx,subject):
    return 15 if owns(ctx.engine,subject,DESCENT) and bastion_implement(ctx.engine,subject) else None


@hook('size_steps')
def bastion_size(engine,actor,role,purposes):
    if role=='resist' and purposes&{'forced','shove','drag'} and owns(engine,actor,DESCENT) and bastion_implement(engine,actor):return 1
    return None


@hook('piercing_object_profile')
def structural_defense(ctx,row,obj):
    if row.get('object_profile')!='greatblade_line' or ctx.typed.get('source') not in {LINE,DIVIDE}:return None
    from .objects import created_by
    component=obj.component or {};protected=set(component.get('protected_defenses') or [])
    creator=created_by(obj)
    original=ctx.engine.action_catalog.get(creator)
    numbers=(original.parameters.get('typed') or {}).get('numbers',{}) if original else {}
    level=component.get('source_cl',(component.get('spirit_asset') or {}).get('source_cl',numbers.get('cl')))
    dc=component.get('save_dc',numbers.get('save_dc'))
    threshold=not protected.intersection({'all','threshold','damage_threshold'})
    resistance=not protected.intersection({'all','resistance'})
    if ctx.typed['source']==DIVIDE:return {'ignore_threshold':threshold,'ignore_resistance':resistance}
    if type(level) is int and level<int(ctx.numbers['cl']):return {'ignore_threshold':threshold,'ignore_resistance':resistance}
    if not creator and type(level) is not int:return {'ignore_threshold':threshold}
    # Unknown cultivated authority cannot silently become mundane terrain.
    if type(level) is not int or type(dc) is not int:return {}
    return {'ignore_threshold':threshold} if cultivation_check(ctx,dc,'barrier:'+obj.object_id) else {}


@hook('piercing_object_resolved')
def structural_cut(ctx,row,obj,result):
    if row.get('object_profile')!='greatblade_line' or not result['destroyed']:return
    from .objects import created_by
    # Permanent geometry belongs to the actual destroyed section only.
    component=obj.component or {}
    if component.get('material') not in {'earth','stone','wood','ice','iron','steel','metal'} or created_by(obj):return
    after=ctx.engine.state.objects[obj.object_id]
    width,depth=(20,30) if ctx.typed.get('source')==DIVIDE else (10,10)
    from ..object_geometry import target_cells
    cells=target_cells(ctx.engine,obj)
    if cells:width=min(width,max(max(p.x for p in cells)-min(p.x for p in cells)+1,max(p.y for p in cells)-min(p.y for p in cells)+1)*5)
    ctx.engine._update_object(after.model_copy(update={'component':{**after.component,'greatblade_cut_width_ft':width,
        'greatblade_cut_depth_ft':min(depth,int(component.get('depth_ft') or obj.height_ft or 5)),
        'greatblade_cut_permanent':1}}),ctx.source,ctx.actor.entity_id)


def disarm_items(ctx):
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed
    from factory_authoring.starting_kits import item_definition
    from .. import acquisition_inventory as inv,carry
    choices={};items=inv.read(ctx.target)
    def permitted(typed,item,key):
        real=next((r for r in items.values() if r['inventory_key']==key),{})
        facts=(real.get('profile') or {}).get('facts') or {}
        restricted=typed.get('artifact') or typed.get('bound') or item.get('artifact') or item.get('bound') or real.get('bound') or real.get('domain_armament_owner') or facts.get('artifact')
        return not restricted or bool(item.get('permits_disarming') or facts.get('permits_disarming')==1)
    for identity,action in available_weapons(ctx.engine,ctx.target).items():
        typed=action.parameters.get('typed') or {};key=typed.get('inventory_key')
        item=item_definition(str(typed.get('source') or ''))
        if weapon_allowed(ctx.engine,ctx.target,action) is False or not permitted(typed,item,key):continue
        if item:choices[identity]={'label':action.display_name.removesuffix(' attack'),'weapon':identity,'item':key}
    from ..armour import shield_item_key
    shield_key=shield_item_key(ctx.engine,ctx.target)
    for item in (carry.carrying_of(ctx.engine,ctx.target.entity_id) or {}).get('items',[]):
        key=item['key'];definition=item_definition(str(item.get('item_id') or ''))
        real=next((r for r in items.values() if r['inventory_key']==key),{})
        is_implement=real.get('profile',{}).get('kind')=='implement'
        location=carry.owned_item_location(ctx.target,key)
        held=(key==shield_key and carry.holds(ctx.engine,ctx.target,key) or
              is_implement and (real.get('location')=='hand' or location and location.startswith('hand:')))
        if held and permitted({},definition,key):choices['item:'+key]={'label':item['name'],'item':key}
    return choices


@effect('greatblade_disarm')
def disarm(ctx,row):
    from .. import typed_executor as te
    choices=disarm_items(ctx)
    picked=choose(ctx,'disarm',{k:r['label'] for k,r in choices.items()},f'Break the Guard: choose one eligible held weapon, shield or implement for {ctx.target.display_name} to drop at its feet.',target=ctx.target) if choices else []
    if not picked:return
    selected=choices[picked[0]]
    if selected.get('item'):
        # The native Drop contract retires prior location, records the real
        # inventory key, reweighs encumbrance, disables its weapon and removes
        # shield AC. It neither creates another item nor consumes a use rider.
        te.block_drop_item(replace(ctx,actor=ctx.target,target=None,targets=[]),{'type':'drop_item','item':selected['item']})
    else:
        ctx.engine._apply_condition(ctx.target,'condition:typed.disarmed',ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'disables_action':selected['weapon'],'dropped_at':ctx.target.position.model_dump(mode='json'),'label':selected['label']+' dropped at its feet'})


def shields(engine,target):
    from ..armour import shield_bonus_earning,shield_item_key
    from . import run_strict
    out={}
    bonus=shield_bonus_earning(engine,target)
    if bonus:out['physical:'+str(shield_item_key(engine,target))]={'id':'physical','bonus':bonus,'label':'Held physical shield'}
    for rows in run_strict('shield_bonus_profiles',engine,target):
        if not isinstance(rows,list):raise ValueError('Shield profiles require a list')
        for row in rows:
            if not isinstance(row,dict) or not set(row)<={'id','label','modifier_id','bonus','field'} or row.get('field') not in {'armor_class','armor_class_vs_ranged','armor_class_vs_melee'} or type(row.get('bonus')) is not int or row['bonus']<0:
                raise ValueError('Invalid source-owned shield bonus profile')
            mod=target.modifiers.get(row.get('modifier_id'))
            if mod is None or mod.target_field!=row['field'] or mod.operation!='ADD':continue
            out[row['id']]=row
    return out


@effect('greatblade_shield')
def shield(ctx,row):
    profiles=shields(ctx.engine,ctx.target)
    selected=choose(ctx,'shield', {k:r['label']+': reduce its AC bonus by 2 until your next turn starts' for k,r in profiles.items()},
        'Break the Guard: choose one physical or projected shield whose AC bonus is reduced.',target=ctx.target) if profiles else []
    if not selected:return
    key=selected[0];profile=profiles[key]
    prior=[c for c in ctx.target.conditions.values() if c.condition_id=='condition:typed.greatblade_shield_loss' and c.data.get('shield_id')==key]
    remaining=max(0,profile['bonus']-sum(int(c.data['amount']) for c in prior))
    amount=min(2,remaining)
    if not amount:return
    data={'amount':amount,'shield_id':key,'label':'Shield AC bonus reduced by 2 until the greatblade user’s next turn starts.'}
    if profile.get('modifier_id'):
        before=set(ctx.target.modifiers)
        ctx.engine._add_modifier(ctx.target,ctx.source,profile['field'],'ADD',-amount,'SELF',expires_on='START_OF_SOURCE_NEXT_TURN')
        data.update(original_modifier=profile['modifier_id'],penalty_modifier=next(k for k in ctx.target.modifiers if k not in before))
    ctx.engine._apply_condition(ctx.target,'condition:typed.greatblade_shield_loss',ctx.source,ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN',data=data)


@hook('ac')
def shield_loss(engine,target):
    from ..armour import shield_bonus_earning,shield_item_key
    key='physical:'+str(shield_item_key(engine,target))
    return -min(shield_bonus_earning(engine,target),sum(int(c.data['amount']) for c in target.conditions.values()
        if c.condition_id=='condition:typed.greatblade_shield_loss' and c.data.get('shield_id')==key)) or None


@hook('event')
def projected_shield_ended(engine,event_type,kwargs):
    if event_type not in {'MODIFIER_REMOVED','CONDITION_REMOVED'}:return
    from .condition_ownership import remove_instance
    for actor in engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id!='condition:typed.greatblade_shield_loss' or not c.data.get('original_modifier'):continue
            if c.data['original_modifier'] not in actor.modifiers:
                penalty=actor.modifiers.pop(c.data['penalty_modifier'],None)
                if penalty:engine._append_event('MODIFIER_REMOVED',c.source_definition_id,actor_id=c.source_actor_id,
                    target_ids=(actor.entity_id,),payload={'modifier_id':penalty.modifier_id})
                remove_instance(engine,actor,c.instance_id,c.source_definition_id)


@hook('falling_damage')
def descent_fall(engine,target,defended,fall,intent):
    if _DESCENT_MOTION.get()==(id(engine),target.entity_id):return {'amount':0}
    return None


@hook('movement_attempt')
def committed_motion(engine,mover,previous,nxt,intent):
    held=pending(mover) or next((c for c in mover.conditions.values() if c.condition_id==LOCK),None)
    # Ordinary movement already consumes native Speed. This extra gate prevents
    # the triggering attack's own granted route from bypassing that restriction;
    # it does not veto an unrelated later Source Rule granting its own movement.
    if held and held.data.get('intent_id')==getattr(intent,'intent_id',None):
        return {'stop':True,'source_id':STROKE,'label':'Committed Stroke: the triggering attack cannot grant movement around Speed 0.'}
    return None


@hook('object_direct_packets')
def structural_hit_packets(ctx,obj,packets,critical):
    mode=ctx.action.parameters.get('greatblade_mode')
    if mode not in {'stroke','descent','sweep'}:return None
    from ..typed_executor import _damage_roll
    count=2+int(ctx.numbers['cl']>=11)+int(ctx.numbers['cl']>=17) if mode in {'stroke','sweep'} else 6
    amount,kind=_damage_roll(replace(ctx,critical_hit=critical),{**damage(count),**({'damage_types':['slashing','force','bludgeoning']} if mode=='descent' else {})})
    return [(amount,kind)] if mode=='sweep' else [(2*amount,kind)] if structural_target(obj) else [(amount,kind)]


@hook('object_direct_defenses')
def descent_threshold(ctx,obj):
    if ctx.action.parameters.get('greatblade_mode')=='descent':return {'ignore_threshold':True}
    return None


def object_cleave(ctx,obj):
    secondary_cleave(ctx,obj)


def secondary_cleave(ctx,primary):
    """One automatic-damage secondary, using native actor/object identity."""
    from .objects import deal
    from ..typed_executor import run_effects
    from ..target_knowledge import can_see
    from ..senses import perceives_object
    from ..object_geometry import target_cells
    from ..object_rules import label
    if ctx.actor.turn_flags.get('greatblade_cleave'):return
    reach=int(ctx.typed.get('reach_ft') or ctx.action.range_ft or 5)
    primary_cells=([primary.position] if hasattr(primary,'entity_id') else target_cells(ctx.engine,primary))
    def close(cells,points,feet):
        return min(ctx.engine.grid.distance_ft(a,b) for a in cells for b in points)<=feet
    entries={a.entity_id:a for a in ctx.engine.state.actors.values() if a.active and a is not primary
        and can_see(ctx.engine,ctx.actor,a) and close(primary_cells,[a.position],5)
        and ctx.engine._distance_actor_to_actor(ctx.actor,a)<=reach}
    entries.update({o.object_id:o for o in ctx.engine.state.objects.values() if not o.destroyed and o is not primary
        and o.current_hp is not None and perceives_object(ctx.engine,ctx.actor,o)
        and close(primary_cells,target_cells(ctx.engine,o),5)
        and close([ctx.actor.position],target_cells(ctx.engine,o),reach)})
    labels={key:(value.display_name if hasattr(value,'entity_id') else label(value)) for key,value in entries.items()}
    picked=choose(ctx,'cleave',labels,'Cleave the Near Side: choose one different creature or object within 5 feet of the hit and within weapon reach. It takes Proficiency Bonus + Qi key modifier Slashing or Force damage; no attack, save or additional cost.',optional=True) if labels else []
    if not picked:return
    ctx.actor.turn_flags['greatblade_cleave']=1
    target=entries[picked[0]];amount=int(ctx.numbers.get('pb') or 0)+int(ctx.numbers.get('key_mod') or 0)
    # This secondary is not a weapon attack or a delivered technique: it cannot
    # inherit potency, critical doubling, limited item riders or recursively cleave.
    typed={**ctx.typed,'numbers':{**ctx.numbers,'potency':0}}
    if hasattr(target,'entity_id'):
        run_effects(replace(ctx,target=target,targets=[target],typed=typed,critical_hit=False),[damage(0,flat=amount)])
    else:
        kind=choose(ctx,'cleave_damage',{'SLASHING':'Slashing','FORCE':'Force'},'Cleave the Near Side: choose Slashing or Force damage.')[0]
        deal(ctx.engine,ctx.actor,target,[(amount,kind)],ctx.source)


@effect('greatblade_sweep_object')
def sweep_object(ctx,row):
    from .object_displacement import destinations
    from ..action_geometry import point
    from ..dynamic_size import CATEGORIES,current_category
    obj=ctx.engine.state.objects.get(row.get('recipient_object_id'))
    if obj is None or obj.destroyed:return
    size=str((obj.component or {}).get('size') or '').title()
    if size not in CATEGORIES or CATEGORIES.index(size)>CATEGORIES.index(current_category(ctx.engine,ctx.actor))+1:return
    origin=point(ctx.engine,ctx.actor)
    dx=(obj.position.x>origin.x)-(obj.position.x<origin.x)
    dy=(obj.position.y>origin.y)-(obj.position.y<origin.y)
    wanted=obj.position.model_copy(update={'x':obj.position.x+dx,'y':obj.position.y+dy})
    if wanted!=obj.position and wanted in destinations(ctx.engine,obj,5):
        ctx.engine._update_object(obj.model_copy(update={'position':wanted}),ctx.source,ctx.actor.entity_id)


@hook('resolution_numbers')
def qi_numbers(ctx,numbers):
    if not ctx.action.parameters.get('greatblade_mode'):return None
    from .body_modes_scene_resources import effective_cl
    cl=effective_cl(ctx.engine,ctx.actor,'tianxia.path.qi_cultivation',int(numbers.get('cl') or 1))
    if cl==numbers.get('cl'):return None
    pb=2+(max(1,cl)-1)//4
    compiled=int(numbers.get('pb') or ctx.actor.proficiency_bonus)
    return {**numbers,'cl':cl,'pb':min(compiled,pb),
        **{key:int(numbers[key])-compiled+min(compiled,pb) for key in ('attack_bonus','save_dc') if key in numbers}}


@hook('damage_defenses')
def collision_resistance(engine,target,damage_type,typed,source_actor_id):
    from .damage_delivery import frame
    if owns(engine,target,DESCENT) and bastion_implement(engine,target) and frame(engine)['hazard']=='collision':
        return [{'kind':'resistance','damage_types':[damage_type],'feature_id':DESCENT}]
    return None


PENDING='condition:typed.greatblade_commit_pending'


def pending(actor):
    return next((c for c in actor.conditions.values() if c.condition_id==PENDING),None)


@hook('before_attack')
def declare_stroke(engine,actor,target,intent,context):
    if not owns(engine,actor,STROKE) or actor.turn_flags.get('greatblade_weapon_attacks') or pending(actor):return None
    action=engine.action_catalog.get(context.get('source_id'))
    if action is None or action.parameters.get('greatblade_mode')=='stroke':return None
    from ..typed_executor import Context
    from .weapon_hits import weapon_item,is_weapon_hit
    frame=_BOUND_ATTACK.get()
    typed=frame[3] if frame and frame[:3]==(id(engine),actor.entity_id,action.source_definition_id) else action.parameters.get('typed') or {}
    ctx=Context(engine,actor,action,intent,typed,[target],target)
    from .weapon_hits import weapon_identity
    base=engine.action_catalog.get(weapon_identity(ctx))
    if base is None or not greatblade(base.parameters.get('typed') or {}):return None
    picked=choose(ctx,'commit',{'commit':'Commit this stroke: extra Slashing or Force damage on a hit; no further weapon attacks or movement this turn'},
        f'Mountain-Weight Stroke: commit {action.display_name} against {target.display_name}? It must be your first weapon attack this turn. No additional Qi cost.',optional=True,target=target)
    if picked:
        engine._apply_condition(actor,PENDING,ctx.source,actor.entity_id,expires_on='END_OF_CURRENT_TURN',
            data={'intent_id':intent.intent_id,'source':ctx.source,'label':'Committed Stroke declared before this attack.'})
    return None


@hook('after_hit_choice')
def committed_hit(ctx,target,kind):
    held=pending(ctx.actor)
    committed=held is not None and held.data['intent_id']==ctx.intent.intent_id and held.data['source']==ctx.source
    hit_cache={k:v for k,v in ctx.damage_cache.items() if isinstance(k,str)}
    sub=ctx.on_hit_context(target,effect_source=STROKE,continue_after_defeat=True,damage_cache=hit_cache)
    if committed:
        from ..typed_executor import run_effects
        run_effects(sub,[damage(2+int(ctx.numbers['cl']>=11)+int(ctx.numbers['cl']>=17))])
    if ctx.action.parameters.get('greatblade_delivered_action'):conduction(replace(ctx,target=target,targets=[target]))
    ctx.damage_cache.update({k:v for k,v in hit_cache.items() if isinstance(k,str)})
    if committed:
        cleave(sub,{})
        guard(sub,{})


@hook('attack_resolved')
def committed_resolved(ctx,target,hit,row):
    held=pending(ctx.actor)
    if (held is not None and held.data['intent_id']==ctx.intent.intent_id and held.data['source']==ctx.source
            or ctx.action.parameters.get('greatblade_mode')=='stroke'):
        lock(ctx,{})
        if held is not None:
            from .condition_ownership import remove_instance
            remove_instance(ctx.engine,ctx.actor,held.instance_id,ctx.source)


@hook('turn_start')
def reset_current_turn_limits(engine,actor):
    # These printed limits name the current turn, including attacks/reactions
    # on another creature's turn. Scene use is an independent retained clock.
    for owner in engine.state.actors.values():
        if not any(r.get('block')=='greatblade_school' for r in getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,[])):continue
        for key in ('greatblade_weapon_attacks','greatblade_cleave','greatblade_guard','greatblade_descent','greatblade_armament_move'):
            owner.turn_flags.pop(key,None)


@hook('technique_used')
def divide_formations(ctx):
    if ctx.action.parameters.get('greatblade_mode')!='divide':return
    from .. import typed_executor as te,zone_sources
    from ..action_geometry import point
    from .area_suppression import suppress,save_dc
    from .effect_durations import token,round_token
    from ..observer_information import publish,source_profile,source_numbers
    engine,actor=ctx.engine,ctx.actor
    origin=point(engine,actor);aim=ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    if aim is None:return
    area=ctx.typed['area'];mine=int(ctx.numbers['cl'])
    for zone in list(engine.state.zones.values()):
        if not zone.active:continue
        crossed=[p for p in zone.affected_cells if te.in_area(engine,origin,aim,p,area)]
        if not crossed:continue
        profile=zone_sources.of(zone) or {}
        classification=source_profile(engine,zone.source_definition_id,zone.trigger_profile)
        # A Secret Law cannot be overcome by a numerical CL comparison. This
        # school supplies no Secret counter-authority of its own.
        if classification.get('authority')=='protected':continue
        numbers=source_numbers(engine,zone.source_definition_id,zone.owner_id)
        cl=profile.get('source_cl',numbers.get('cl'))
        dc=profile.get('save_dc',numbers.get('save_dc'))
        if type(cl) is not int or type(dc) is not int:continue
        success=True if cl<mine else cultivation_check(ctx,dc,'formation:'+zone.zone_id)
        if cl<mine or cl==mine and success:until=round_token(engine,10)
        elif cl==mine:until=token('start',actor.entity_id,actor.turns_started+1)
        elif success:until=token('end',actor.entity_id,actor.turns_started+1)
        else:
            from . import formations
            anchors=formations.objects_of(engine,zone) if zone.trigger_profile.get(formations.KEY) else []
            primary=next((o for o in anchors if (o.component or {}).get('role')=='eye'),None)
            publish(engine,actor,ctx.source,actor,'declaration',{
                'text':'Divide Mountain and River reveals this surviving effect at '+str(zone.center.x)+', '+str(zone.center.y)+
                    (('; primary Anchor at '+str(primary.position.x)+', '+str(primary.position.y)) if primary else '')+' until this scene ends.',
                'greatblade_scene_reading':1,'zone_id':zone.zone_id,'location':zone.center.model_dump(mode='json'),
                **({'anchor_id':primary.object_id,'anchor_location':primary.position.model_dump(mode='json')} if primary else {})},'UNTIL_REMOVED')
            continue
        record=suppress(engine,actor,zone,until,ctx.source,crossed)
        if record:
            cuts=list(zone.trigger_profile.get('greatblade_severed_links',[]))
            cuts.append({'source':ctx.source,'owner':actor.entity_id,'until':until,
                'origin':origin.model_dump(mode='json'),'aim':aim.model_dump(mode='json'),'width_ft':20,
                'suppression_key':record['key']})
            zone.trigger_profile={**zone.trigger_profile,'greatblade_severed_links':cuts}
            engine._append_event('ZONE_CREATED',zone.source_definition_id,actor_id=zone.owner_id,payload={'zone':zone.model_dump(mode='json')})


def crosses_breach(engine,zone,left,right):
    from .area_suppression import records
    live={r['key'] for r in records(zone)}
    for cut in zone.trigger_profile.get('greatblade_severed_links',[]):
        if cut['suppression_key'] not in live:continue
        o,a=cut['origin'],cut['aim'];dx,dy=a['x']-o['x'],a['y']-o['y']
        first=dx*(left.y-o['y'])-dy*(left.x-o['x'])
        second=dx*(right.y-o['y'])-dy*(right.x-o['x'])
        if first*second<=0:
            # Only crossing the physically severed section blocks a link; an
            # unrelated segment of the infinite mathematical axis has no effect.
            from ..gate2_runtime_models import Position
            from ..typed_executor import in_area
            origin=Position(**o);aim=Position(**a)
            if any(in_area(engine,origin,aim,Position(x=x,y=y,z=left.z),
                {'shape':'line','size_ft':300,'width_ft':20,'spreads':True})
                for x,y in engine.grid.ray_cells(left,right)):
                return True
    return False


@hook('linked_path_allowed')
def severed_formation_link(engine,zone,left,right,benefit):
    return False if crosses_breach(engine,zone,left,right) else None


def greatblade_armament(engine,actor):
    from .qi_path import armament_condition,armament_control_range
    from ..gate2_runtime_models import Position
    held=armament_condition(actor)
    if held is None:return None
    if held.data.get('form_family')=='greatblade':return held
    uid=held.data.get('bound_item_id')
    actual=bond(engine,actor) if uid else None
    if actual:
        owner,item=actual
        point=item_point(engine,owner,item)
        if item['id']==uid and item['location']=='floating' and not item['profile']['flags'].get('suppressed') and engine.grid.distance_ft(actor.position,point)<=armament_control_range(engine,actor):return held
    return None


def bastion_implement(engine,actor):
    if weapons(engine,actor):return True
    held=greatblade_armament(engine,actor)
    if held:
        from ..gate2_runtime_models import Position
        actual=bond(engine,actor) if held.data.get('bound_item_id') else None
        point=item_point(engine,*actual) if actual else Position(x=int(held.data['ax']),y=int(held.data['ay']),z=int(held.data.get('az',0)))
        return engine.grid.distance_ft(actor.position,point)<=10
    return False


@hook('armament_manifest_profile')
def greatblade_form(profile,ctx):
    if not owns(ctx.engine,ctx.actor,STROKE) or profile.get('bound_item_id'):return profile
    actual=bond(ctx.engine,ctx.actor) if domain_access(ctx.engine,ctx.actor) else None
    choices={'greatblade':'A projected Greatblade Domain Armament; no real item or item properties',
        'other':'Your ordinary projected Domain Armament'}
    if actual:choices['bound']='The actual bound '+actual[1]['name']+'; retains its real properties and durability'
    selected=choose(ctx,'armament_form',choices,'Domain Armament: choose a projected form or your actual bound item. Manifesting costs 1 Qi and lasts 1 hour.')
    if selected==['other']:return profile
    from .effect_durations import round_token
    session=getattr(ctx.engine,'scene_source_session',None)
    deadline=round_token(ctx.engine,600)
    result={**profile,'retain_identity':1,'expires_on':deadline,**({'expires_at':int(session.clock())+3600} if session else {}),'form_source':STROKE}
    if selected==['greatblade']:
        kind=choose(ctx,'projected_damage',{'bludgeoning':'Bludgeoning','piercing':'Piercing','slashing':'Slashing','force':'Force'},'Choose the projected Domain Armament damage type for this manifestation; it copies no real item properties.')[0]
        return {**result,'form_family':'greatblade','damage_type':kind,'label':'Projected Greatblade Domain Armament (Assault Mode)'}
    if selected==['bound'] and actual:
        from .. import acquisition_inventory as inv
        from ..gate2_runtime_models import Position
        from . import run_strict
        owner,old=actual;point=Position(x=profile['ax'],y=profile['ay'],z=int(profile.get('az',0)))
        obj=inv.object_for_item(ctx.engine,owner,old['id'],item_point(ctx.engine,owner,old),ctx.source)
        if not ctx.engine.grid.line_of_physical_transmission(obj.position,point) or any(v is False for v in run_strict('object_operation_gate',ctx.engine,ctx.actor,obj,'move',ctx.source,ctx.intent)):
            raise ValueError('The real bound item cannot pass through its blocked physical route.')
        items=inv.read(owner);item=items[old['id']]
        item.update(location='floating',holder=ctx.actor.entity_id,domain_armament_paused=0,domain_armament_expiry=deadline,domain_armament_mode=profile['mode'],**({'domain_armament_expires_at':int(session.clock())+3600} if session else {}))
        item.pop('hand',None)
        commit_bound_item(ctx.engine,owner,items,item,point,ctx.source)
        mode=choose(ctx,'bound_mode',{'assault':'Assault Mode','guard':'Guard Mode'},'Choose the actual bound Domain Armament mode; no additional cost.')[0]
        return {**result,'mode':mode,'bound_item_id':item['id'],'bound_item_owner':owner.entity_id,'label':'Real Greatblade Domain Armament ('+mode.title()+')'}
    return profile


@hook('effect_origins')
def greatblade_origins(engine,actor,action):
    mode=action.parameters.get('greatblade_mode','')
    if mode not in {'line','divide','sweep','armament_attack'} and not mode.startswith('armament_conduction.'):return None
    held=greatblade_armament(engine,actor)
    if held is None:return None
    if action.parameters.get('greatblade_mode')=='sweep' and not held.data.get('bound_item_id'):return None
    from ..gate2_runtime_models import Position
    from .qi_path import armament_control_range
    actual=bond(engine,actor) if held.data.get('bound_item_id') else None
    point=item_point(engine,*actual) if actual else Position(x=int(held.data['ax']),y=int(held.data['ay']),z=int(held.data.get('az',0)))
    if engine.grid.distance_ft(actor.position,point)>armament_control_range(engine,actor):return None
    return [{'id':'greatblade:'+held.instance_id,'label':'Your Greatblade Domain Armament','position':point.model_dump(mode='json')}]


@hook('journey_scene_end')
def new_scene(session,previous,current):
    from ..native_scene import engine_for,save_engine,KEY
    from .end_effect import SUPPRESSED_FLAG,restore_suppressed
    from .condition_ownership import remove_instance
    import json
    if KEY not in session.state and not any(a.get('encounter_snapshot') for a in session.state['actors'].values()):return
    engine=engine_for(session)
    changed=False
    for actor in engine.state.actors.values():
        for held in list(actor.conditions.values()):
            if held.condition_id=='condition:typed.greatblade_scene_restoration':
                for row in list(actor.turn_flags.get(SUPPRESSED_FLAG,[])):
                    if row['key'] in held.data['keys']:restore_suppressed(engine,actor,row)
            if held.condition_id in {'condition:typed.greatblade_scene_restoration'} or (held.data.get('details') or {}).get('greatblade_scene_reading'):
                remove_instance(engine,actor,held.instance_id,held.source_definition_id);changed=True
    if changed:save_engine(session,engine)
@hook('journey_native_actions')
def native_scene_actions(session,aid):
    rows=[a['source_definition_id'] for a in session.state['actors'][aid]['bundle']['action_catalog']
        if a.get('parameters',{}).get('greatblade_mode')]
    if any(a.get('parameters',{}).get('greatblade_mode')=='descent' for a in session.state['actors'][aid]['bundle']['action_catalog']):
        from .terrain_repair import CLEAR
        rows.append(CLEAR)
    return rows


@effect('greatblade_reaction_denied')
def reaction_denied(ctx,row):
    if ctx.target is None:return
    from .effect_durations import token
    from ..typed_executor import run_effects
    run_effects(ctx,[{'type':'condition','condition':'reaction_denied','applies_to':'target',
        'expires_on':token(row['edge'],ctx.target.entity_id,ctx.target.turns_started+1)}])


@hook('object_targets')
def descent_objects(engine,actor,action):
    if not action.parameters.get('greatblade_descent_object') and not (action.target_kind=='OBJECT' and action.parameters.get('greatblade_mode','').startswith('armament_conduction.')):return None
    return [o.object_id for o in engine.state.objects.values() if not o.destroyed and o.current_hp is not None and o.ac is not None]


@hook('object_action')
def descent_object_action(engine,actor,action,obj,candidate,intent):
    if not action.parameters.get('greatblade_descent_object') and not (action.target_kind=='OBJECT' and action.parameters.get('greatblade_mode','').startswith('armament_conduction.')):return None
    from ..typed_executor import Context,activation_reactions,run_effects
    from . import run_strict
    ctx=Context(engine,actor,action,intent,action.parameters['typed'],[],None)
    ctx.damage_cache['_object']=obj
    run_strict('technique_accepted',engine,actor,action)
    if any(reply is True for reply in run_strict('technique_start',engine,actor,action)):return True
    if not activation_reactions(ctx):return True
    from ..typed_executor import activation_hold
    with activation_hold(engine,ctx.typed):
        run_effects(ctx,ctx.typed['effects'])
        run_strict('technique_used',ctx)
    return True


@effect('greatblade_descent_object_hit')
def descent_object_hit(ctx,row):
    obj=ctx.engine.state.objects.get(row.get('recipient_object_id'))
    if obj is None:return
    # Source-qualified material belongs to the map/item producer. Merely naming
    # an impact point does not make an indestructible surface destructible.
    component=obj.component or {}
    if component.get('material') not in {'earth','stone','wood','ice','iron','steel','metal'}:return
    from .. import zones
    rubble=zones.create(replace(ctx,intent=ctx.intent.model_copy(update={'destination':obj.position})),{'name':'Heaven-Weight rubble or crater',
        'shape':'sphere','size_ft':10,'placed':True,'spreads':True,'difficult':'all',
        'terrain':['rubble'],'duration':{'kind':'permanent'},'profile':{'greatblade_repair_object':obj.object_id,'repair_tools':['tianxia.mortal.gear.shovel','tianxia.mortal.tool.mason_s_tools']}})
    if rubble is None:return
    # Rubble is an instantaneous mundane consequence and remains until native
    # repair removes it. It is not a continuing cultivation field to dispel.
    rubble.trigger_profile={**rubble.trigger_profile,'mundane':1}
    ctx.engine._append_event('ZONE_CREATED',ctx.source,actor_id=ctx.actor.entity_id,payload={'zone':rubble.model_dump(mode='json')})


@hook('journey_native_elapsed')
def armament_elapsed(session,engine,before,after):
    from .qi_path import armament_condition
    from .condition_ownership import remove_instance
    for actor in engine.state.actors.values():
        held=armament_condition(actor)
        if held and held.data.get('form_source')==STROKE and type(held.data.get('expires_at')) is int and held.data['expires_at']<=after:
            remove_instance(engine,actor,held.instance_id,held.source_definition_id)


@hook('before_attack')
def shield_penalties_follow_live_instance(engine,actor,target,intent,context):
    projected_shield_ended(engine,'MODIFIER_REMOVED',{})


@hook('terrain_repair_enabled')
def crater_repair(engine):
    return True if any(a.parameters.get('greatblade_mode')=='descent' for a in engine.action_catalog.values()) else None


# Real Greatblade Domain Armament: the acquired inventory is the sole item
# ledger; Journey activity clocks produce a bond, never a declaration flag.
BIND=STROKE+':bind-domain-armament'
ARMAMENT='tianxia.path.qi_cultivation.feature.domain_armament'


def domain_access(engine,actor):
    from .body_modes_scene_resources import available
    from ..alternative_payments import owned
    return bool(owns(engine,actor,STROKE) and owned(engine,actor,ARMAMENT)
        and available(engine,actor,ARMAMENT,9,path_id='tianxia.path.qi_cultivation',compiled_level=int(owns(engine,actor,STROKE)['numbers']['cl'])))


def item_entries(engine):
    from ..acquisition_inventory import read
    return [(owner,item) for owner in engine.state.actors.values() for item in read(owner).values()]


def bond(engine,actor):
    entries=[(owner,item) for owner,item in item_entries(engine) if item.get('domain_armament_owner')==actor.entity_id
        and not item['profile']['flags'].get('broken')]
    if len(entries)>1:raise ValueError('One creature cannot have two real Domain Armament bonds.')
    return entries[0] if entries else None


def item_point(engine,owner,item):
    from ..gate2_runtime_models import Position
    from .. import carry
    native=engine.state.objects.get('object:recorded_item:'+item['id'])
    if item['location'] in {'floating','space'}:
        if native:return native.position
        if item.get('position'):return Position.model_validate(item['position'])
    for held in owner.conditions.values():
        data=held.data or {}
        if data.get('item_key')==item['inventory_key'] or data.get('disables_action') in item.get('weapon_actions',[]):
            if data.get('dropped_at'):return Position.model_validate(data['dropped_at'])
            if data.get('held_by') in engine.state.actors:return engine.state.actors[data['held_by']].position
    return engine.state.actors.get(item['holder'],owner).position


def binding_eligible(session,engine,actor,owner,item):
    from .. import acquisition_inventory as inv
    from ..fact_consent_admission import read
    from ..targeting import line_of_effect
    if not domain_access(engine,actor) or item.get('domain_armament_owner') not in (None,'',actor.entity_id):return False
    p=item['profile'];flags=p['flags']
    bases=[engine.action_catalog[k] for k in item.get('weapon_actions',[]) if k in engine.action_catalog]
    # A recorded real weapon retains its native catalog classification and
    # actual proficiency. Owning this School never supplies proficiency.
    if not bases or not any(greatblade(a.parameters.get('typed') or {}) for a in bases):return False
    if owner is actor and not any(greatblade(a.parameters.get('typed') or {}) and a.parameters['typed'].get('proficient') for a in bases):return False
    if p['kind']!='weapon' or flags.get('projection') or not p.get('object_profile') or not flags.get('prerequisites_met') or p['attunement_slots'] and (not item['attuned'] or item.get('attuned_by',owner.entity_id)!=actor.entity_id):return False
    if any(flags.get(k) for k in ('broken','consumed','suppressed')) or inv.resonance_refused(item,'bind',int(owns(engine,actor,STROKE)['numbers']['cl'])):return False
    if owner is not actor:
        permission=read(session,STROKE,owner.entity_id,'domain_armament_permission',item['id'],actor.entity_id)
        if not permission or permission['value']!=1:return False
        # Permission is not proficiency; the borrower needs a native usable
        # weapon profile of the same item class with recorded proficiency.
        sources={a.parameters['typed'].get('source') for a in bases}
        if not any(a.parameters['typed'].get('source') in sources and a.parameters['typed'].get('proficient') for a in weapons(engine,actor).values()):return False
    if flags.get('sentient'):
        subject=p['facts'].get('sentient_actor_id') or item['id']
        consent=read(session,STROKE,subject,'domain_armament_sentient_consent',item['id'],actor.entity_id)
        if not consent or consent['value']!=1:return False
    point=item_point(engine,owner,item)
    return engine._distance_actor_to_cell(actor,point)<=5 and line_of_effect(engine,actor,destination=point)


@hook('fact_admission_subjects')
def item_fact_subjects(session,source,kind):
    if source!=STROKE or kind!='domain_armament_sentient_consent':return None
    return [item['id'] for a in session.state['actors'].values() for item in a.get('recorded_inventory',a['bundle'].get('acquisition_inventory',{})).values()
        if item['profile']['flags'].get('sentient') and not item['profile']['facts'].get('sentient_actor_id')]


@hook('fact_admission_schema')
def binding_fact_schema(session,source,subject,kind):
    if source!=STROKE:return None
    if kind=='domain_armament_permission' and subject in session.state['actors']:
        return {'value_type':'flag','maximum_seconds':3600,'description':'The actual item owner permits this recorded item to be bound; no proficiency or item is granted.'}
    if kind=='domain_armament_sentient_consent':
        subjects=item_fact_subjects(session,source,kind) or []
        if subject in session.state['actors'] or subject in subjects:
            return {'value_type':'flag','maximum_seconds':3600,'authority':'table_owner' if subject in subjects else 'subject',
                'description':'Record the sentient item’s actual consent to this bond, independently of the wielder’s wishes.'}


@hook('fact_admission_scope_validate')
def binding_fact_scope(session,source,subject,kind,scope,value):
    if source!=STROKE or kind not in {'domain_armament_permission','domain_armament_sentient_consent'}:return None
    entries=[i for a in session.state['actors'].values() for i in a.get('recorded_inventory',a['bundle'].get('acquisition_inventory',{})).values() if i['id']==scope]
    if len(entries)!=1:return False
    item=entries[0]
    return item['owner']==subject if kind=='domain_armament_permission' else bool(item['profile']['flags'].get('sentient') and subject==(item['profile']['facts'].get('sentient_actor_id') or item['id']))


@hook('activity_spec')
def binding_spec(session,aid,source,parameters):
    if source!=BIND:return None
    from ..journey import require
    from ..native_scene import engine_for
    require(set(parameters)=={'item'},'Choose one real acquired item for the ten-minute binding.')
    engine=engine_for(session);actor=engine.state.actors[aid]
    entries=[(o,i) for o,i in item_entries(engine) if i['id']==parameters['item']]
    require(len(entries)==1 and binding_eligible(session,engine,actor,*entries[0]),'Binding requires a real greatblade, lawful permission, proficiency, prerequisites, attunement, sentient consent and uninterrupted physical touch.')
    return {'seconds':600,'label':'bind '+entries[0][1]['name']+' as the one real Greatblade Domain Armament (10 uninterrupted minutes touching it; no Qi cost)'}


@hook('activity_validate')
def validate_binding(session,aid,row):
    if row['source']==BIND:binding_spec(session,aid,BIND,row['parameters'])


@hook('activity_finished')
def finish_binding(session,aid,row):
    if row['source']!=BIND:return
    from ..native_scene import engine_for,save_engine
    from .. import acquisition_inventory as inv
    engine=engine_for(session);actor=engine.state.actors[aid]
    validate_binding(session,aid,row)
    for owner in engine.state.actors.values():
        items=inv.read(owner);changed=False
        for item in items.values():
            if item.get('domain_armament_owner')==aid:
                item.pop('domain_armament_owner');item['version']+=1;changed=True
            if item['id']==row['parameters']['item']:
                item['domain_armament_owner']=aid;item['domain_armament_source']=STROKE
                item['version']+=1;changed=True
        if changed:
            inv.write(engine,owner,items,STROKE)
            outside=session.state['actors'][owner.entity_id]
            outside['recorded_inventory']=deepcopy(items);outside['bundle']['acquisition_inventory']=deepcopy(items)
    save_engine(session,engine)
    session.emit('GREATBLADE_ITEM_BOUND',aid,item_id=row['parameters']['item'],seconds_worked=row['worked_seconds'],source=STROKE)


@hook('activity_command_interrupts')
def binding_interrupts(session,who,row,aid,kind,payload):
    if row['source']!=BIND:return None
    return kind in {'native_scene_action','native_scene_procedure','inventory_profile','inventory_attune','inventory_interact'} and (aid==who or payload.get('item')==row['parameters']['item'])


@hook('journey_options')
def binding_options(session,aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return None
    bundle=session.state['actors'][aid]['bundle']
    if not any(a.get('parameters',{}).get('greatblade_mode') for a in bundle['action_catalog']):return None
    from ..native_scene import engine_for
    engine=engine_for(session);actor=engine.state.actors[aid]
    if not domain_access(engine,actor):return None
    return [{'id':'greatblade:bind:'+item['id'],'kind':'activity_start','auto_select':0,
        'payload':{'source':BIND,'parameters':{'item':item['id']}},
        'label':'Bind '+item['name']+': 10 uninterrupted minutes touching this real item, no Qi cost; replaces your previous bond.'}
        for owner,item in item_entries(engine) if binding_eligible(session,engine,actor,owner,item)]


def armament_reach(info):
    return 65 if 'tianxia.path.qi_cultivation.feature.domain_armament_link' in info['owned_ids'] else 35


def commit_bound_item(engine,owner,items,item,point,source):
    from .. import acquisition_inventory as inv
    item['position']=point.model_dump(mode='json');item['version']+=1;item['placement_declared']=1
    inv.write(engine,owner,items,source)
    return inv.object_for_item(engine,owner,item['id'],point,source)


@effect('greatblade_bound_handle',harmful=False)
def handle_bound(ctx,row):
    from .. import acquisition_inventory as inv
    from .qi_path import armament_condition,armament_control_range,ARMED
    from .hand_occupancy import free_hands
    from .object_displacement import destinations
    from ..gate2_runtime_models import Position
    from . import run_strict
    from .effect_durations import round_token
    actual=bond(ctx.engine,ctx.actor)
    if not actual:return
    owner,item=actual;items=inv.read(owner);item=items[item['id']]
    obj=inv.object_for_item(ctx.engine,owner,item['id'],item_point(ctx.engine,owner,item),ctx.source)
    if any(v is False for v in run_strict('object_operation_gate',ctx.engine,ctx.actor,obj,'move',ctx.source,ctx.intent)):return
    calling=item['location']=='floating'
    choices={}
    if calling:
        if not free_hands(ctx.engine,ctx.actor) or not ctx.engine.grid.line_of_physical_transmission(obj.position,ctx.actor.position):return
        choices={'hand':'Call the actual item into one legal free hand; the floating Armament ends'}
    else:
        control=armament_control_range(ctx.engine,ctx.actor)
        choices={str(i):p for i,p in enumerate(destinations(ctx.engine,obj,control))
            if ctx.engine.grid.distance_ft(ctx.actor.position,p)<=control}
    labels=choices if calling else {k:f'Release the actual item to {p.x},{p.y}, altitude {p.z*5} feet' for k,p in choices.items()}
    selected=choose(ctx,'bound_position',labels,'Call or release the real bound Greatblade as a Bonus Action. It travels physically along an unobstructed path; no Qi cost.') if labels else []
    if not selected:return
    if calling:
        hand=free_hands(ctx.engine,ctx.actor)[0]
        item.update(location='hand',holder=ctx.actor.entity_id,hand=hand,domain_armament_paused=0)
        commit_bound_item(ctx.engine,owner,items,item,ctx.actor.position,ctx.source)
        ctx.engine._remove_condition(ctx.actor,ARMED,ctx.source)
    else:
        point=choices[selected[0]]
        mode=choose(ctx,'bound_mode',{'assault':'Assault Mode: authorized floating attacks','guard':'Guard Mode: protect one nearby creature against ranged attacks'},'Choose the released Domain Armament mode. It lasts 1 hour; the actual item is never duplicated.')[0]
        item.update(location='floating',holder=ctx.actor.entity_id,domain_armament_paused=0,domain_armament_expiry=round_token(ctx.engine,600),domain_armament_mode=mode,**({'domain_armament_expires_at':int(ctx.engine.scene_source_session.clock())+3600} if getattr(ctx.engine,'scene_source_session',None) else {}))
        item.pop('hand',None)
        commit_bound_item(ctx.engine,owner,items,item,point,ctx.source)
        ctx.engine._remove_condition(ctx.actor,ARMED,ctx.source)
        ctx.engine._apply_condition(ctx.actor,ARMED,ctx.source,ctx.actor.entity_id,expires_on=round_token(ctx.engine,600),
            data={'mode':mode,'ax':point.x,'ay':point.y,'az':point.z,'reach_ft':armament_control_range(ctx.engine,ctx.actor),
                'bound_item_id':item['id'],'bound_item_owner':owner.entity_id,'retain_identity':1,'form_source':STROKE,
                **({'expires_at':int(ctx.engine.scene_source_session.clock())+3600} if getattr(ctx.engine,'scene_source_session',None) else {}),
                'label':'Real Greatblade Domain Armament ('+mode.title()+')'})


@effect('greatblade_end_bond',harmful=False)
def end_bond(ctx,row):
    from .. import acquisition_inventory as inv
    actual=bond(ctx.engine,ctx.actor)
    if not actual:return
    owner,old=actual;items=inv.read(owner);item=items[old['id']]
    if item['location']=='floating':
        item['location']='space';item['holder']=owner.entity_id
        point=item_point(ctx.engine,owner,old)
        item.pop('domain_armament_owner',None)
        commit_bound_item(ctx.engine,owner,items,item,point,ctx.source)
    else:
        item.pop('domain_armament_owner',None);item['version']+=1
        inv.write(ctx.engine,owner,items,ctx.source)
    from .qi_path import ARMED
    ctx.engine._remove_condition(ctx.actor,ARMED,ctx.source)


@effect('greatblade_bound_attack')
def bound_attack(ctx,row):
    from .. import acquisition_inventory as inv
    from ..typed_executor import block_attack
    from .qi_path import armament_control_range,ARMED,armament_condition
    from .object_displacement import destinations
    from ..action_geometry import activate
    from .condition_ownership import remove_instance
    primary=ctx.target or ctx.damage_cache.get('_object')
    if primary is None:return
    from ..object_geometry import target_cells
    creature=hasattr(primary,'entity_id')
    actual=bond(ctx.engine,ctx.actor);held=greatblade_armament(ctx.engine,ctx.actor)
    if actual is None or held is None or held.data['mode']!='assault':return
    owner,item=actual;obj=inv.object_for_item(ctx.engine,owner,item['id'],item_point(ctx.engine,owner,item),ctx.source)
    feet=30 if armament_control_range(ctx.engine,ctx.actor)==60 else 20
    places={str(i):p for i,p in enumerate(destinations(ctx.engine,obj,feet))
        if ctx.engine.grid.distance_ft(ctx.actor.position,p)<=armament_control_range(ctx.engine,ctx.actor)
        and (ctx.engine._distance_actor_to_cell(primary,p)<=5 if creature else min(ctx.engine.grid.distance_ft(c,p) for c in target_cells(ctx.engine,primary))<=5)}
    selected=choose(ctx,'bound_attack_position',{k:f'Move the real Greatblade to {p.x},{p.y}, altitude {p.z*5} feet; attack within 5 feet' for k,p in places.items()},
        f'Domain Armament Attack: move the actual bound item up to {feet} feet, then make one Cultivation Attack. Bonus Action; no Qi or item charge cost.') if places else []
    if not selected:return
    point=places[selected[0]]
    items=inv.read(owner);item=items[item['id']]
    commit_bound_item(ctx.engine,owner,items,item,point,ctx.source)
    data={**held.data,'ax':point.x,'ay':point.y,'az':point.z}
    from .qi_path import update_armament
    update_armament(ctx.engine,ctx.actor,data,ctx.source)
    base=next((ctx.engine.action_catalog[k] for k in item.get('weapon_actions',[]) if k in ctx.engine.action_catalog and greatblade(ctx.engine.action_catalog[k].parameters.get('typed') or {})),None)
    if base is None:return
    typed=deepcopy(base.parameters['typed']);weapon=typed['weapon']
    domain_dice=3 if ctx.numbers['cl']>=17 else 2 if ctx.numbers['cl']>=13 else 1
    original=weapon['damage'];count,sides=int(original['count']),int(original['sides'])
    if domain_dice*4.5>count*(sides+1)/2:count,sides=domain_dice,8
    # Keep the real printed refinement, damage types and legal automatic on-hit
    # properties. Cultivation key replaces the ordinary weapon ability once.
    refinement=int(weapon.get('refinement') or item.get('printed_refinement') or 0)
    weapon['damage']={'count':count,'sides':sides,'modifier':int(ctx.numbers['key_mod'])+refinement}
    weapon['ability_modifier']=int(ctx.numbers['key_mod'])
    typed.update(source=ctx.typed.get('source') if ctx.action.parameters.get('greatblade_delivered_action') else ARMAMENT,weapon_source_id=base.source_definition_id,numbers={**ctx.numbers,'attack_bonus':int(ctx.numbers['pb'])+int(ctx.numbers['key_mod'])+refinement})
    attack=deepcopy(next(e for e in typed['effects'] if e.get('type')=='attack'))
    attack.update(count=1,attack_kind='cultivation_melee',reach_ft=5)
    token=_BOUND_ATTACK.set((id(ctx.engine),ctx.actor.entity_id,ctx.action.source_definition_id,typed))
    try:
        with activate(ctx.engine,ctx.actor,ctx.source,{'id':'greatblade:'+armament_condition(ctx.actor).instance_id,'label':'Your Greatblade Domain Armament','position':point.model_dump(mode='json')}):
            if creature:block_attack(replace(ctx,typed=typed),attack)
            else:
                from .objects import resolve_direct_attack
                attack.update(object_native_weapon=True,object_on_hit_effects=['greatblade_conduction_object_hit'])
                attack['on_hit'].append({'type':'greatblade_conduction_object_hit'})
                resolve_direct_attack(replace(ctx,typed=typed),primary,attack)
    finally:_BOUND_ATTACK.reset(token)


@hook('armament_drift')
def bound_item_falls(engine,actor,held,*,resume=True):
    if not held.data.get('bound_item_id') or not any(r.get('feature_id')==STROKE and r.get('block')=='greatblade_school' for r in engine.typed_passive_rows.get(actor.entity_id,[])):return None
    from .. import acquisition_inventory as inv
    from .qi_path import ARMED
    actual=bond(engine,actor)
    if actual:
        owner,old=actual;items=inv.read(owner);item=items[old['id']]
        point=item_point(engine,owner,old)
        # It falls in its actual local legal space; it is never pulled back
        # through a wall or duplicated beside the cultivator.
        while point.z>0 and not engine.grid.roof_supported(point) and not engine.grid.terrain_at((point.x,point.y,point.z-1),'BLOCKED'):
            below=point.model_copy(update={'z':point.z-1})
            if not engine.grid.volume_step_legal(point,below):break
            point=below
        item.update(location='space',domain_armament_paused=int(resume),domain_armament_mode=held.data['mode'],domain_armament_expiry=held.expires_on)
        commit_bound_item(engine,owner,items,item,point,held.source_definition_id)
    engine._remove_condition(actor,ARMED,held.source_definition_id)
    return True


@hook('event')
def real_armament_ended(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED':return
    from .qi_path import ARMED
    from ..gate2_runtime_models import ConditionInstance
    old=kwargs.get('ended_effect') or {}
    if old.get('condition_id')!=ARMED or not old.get('data',{}).get('bound_item_id'):return
    actor=engine.state.actors.get(old.get('source_actor_id'))
    actual=bond(engine,actor) if actor is not None else None
    if actual and actual[1]['location']=='floating':bound_item_falls(engine,actor,ConditionInstance.model_validate(old),resume=False)


@hook('weapon_hand_policy')
def floating_real_weapon(engine,actor,action,effect):
    frame=_BOUND_ATTACK.get()
    if frame is None or frame[:3]!=(id(engine),actor.entity_id,action.source_definition_id):return None
    actual=bond(engine,actor);held=greatblade_armament(engine,actor)
    if actual is None or held is None or held.data.get('mode')!='assault':return False
    owner,item=actual
    return bool(item['location']=='floating' and frame[3].get('weapon_source_id') in item.get('weapon_actions',[]) and not item['profile']['flags'].get('suppressed'))


@effect('greatblade_armament_move',harmful=False)
def move_focus(ctx,row):
    from .qi_path import armament_control_range,update_armament
    from ..gate2_runtime_models import Position
    from .object_displacement import destinations_from
    from .. import acquisition_inventory as inv
    held=greatblade_armament(ctx.engine,ctx.actor)
    if held is None or ctx.actor.turn_flags.get('greatblade_armament_move'):return
    actual=bond(ctx.engine,ctx.actor) if held.data.get('bound_item_id') else None
    origin=item_point(ctx.engine,*actual) if actual else Position(x=held.data['ax'],y=held.data['ay'],z=held.data.get('az',0))
    feet=30 if armament_control_range(ctx.engine,ctx.actor)==60 else 20
    places={str(i):p for i,p in enumerate(destinations_from(ctx.engine,origin,feet,object_id='object:recorded_item:'+actual[1]['id'] if actual else None))
        if ctx.engine.grid.distance_ft(ctx.actor.position,p)<=armament_control_range(ctx.engine,ctx.actor)}
    selected=choose(ctx,'armament_move',{k:f'Move to {p.x},{p.y}, altitude {p.z*5} feet' for k,p in places.items()},
        f'Move your Greatblade Domain Armament up to {feet} feet along a clear physical route. Once during your turn; no Action or Qi cost.') if places else []
    if not selected:return
    point=places[selected[0]]
    if actual:
        from . import run_strict
        owner,old=actual;obj=ctx.engine.state.objects.get('object:recorded_item:'+old['id'])
        if obj and any(v is False for v in run_strict('object_operation_gate',ctx.engine,ctx.actor,obj,'move',ctx.source,ctx.intent)):return
        items=inv.read(owner);commit_bound_item(ctx.engine,owner,items,items[old['id']],point,ctx.source)
    update_armament(ctx.engine,ctx.actor,{**held.data,'ax':point.x,'ay':point.y,'az':point.z},ctx.source)
    ctx.actor.turn_flags['greatblade_armament_move']=1


@hook('piercing_wall_profile')
def structural_wall(ctx,row,zone,section):
    if row.get('object_profile')!='greatblade_line' or ctx.typed.get('source') not in {LINE,DIVIDE}:return None
    from ..zone_sources import of
    profile=of(zone) or {};numbers=zone.trigger_profile.get('numbers') or {}
    level=profile.get('source_cl',numbers.get('cl'));dc=profile.get('save_dc',numbers.get('save_dc'))
    protected=set(zone.trigger_profile.get('protected_defenses') or [])
    threshold=not protected.intersection({'all','threshold','damage_threshold'})
    resistance=not protected.intersection({'all','resistance'})
    if ctx.typed['source']==DIVIDE:return {'ignore_threshold':threshold,'ignore_resistance':resistance}
    if type(level) is int and level<int(ctx.numbers['cl']):return {'ignore_threshold':threshold,'ignore_resistance':resistance}
    if type(level) is not int or type(dc) is not int:return {}
    key='greatblade_wall_check:'+zone.zone_id
    if key not in ctx.damage_cache:ctx.damage_cache[key]=cultivation_check(ctx,dc,'barrier:'+zone.zone_id)
    return {'ignore_threshold':threshold} if ctx.damage_cache[key] else {}



def structural_target(obj):
    from ..object_rules import has_tag
    from .spirit_assets import TAG
    return obj.unattended or any(has_tag(obj,k) for k in ('vehicle','structure','temporary_barrier','formation_anchor','cultivation_asset')) or bool((obj.component or {}).get(TAG))


@contextmanager
def cultivated_packet(ctx):
    previous=ctx.damage_source_flags
    ctx.damage_source_flags=(*previous,'greatblade_cultivation')
    try:yield
    finally:ctx.damage_source_flags=previous


@hook('effect_resolution_scope')
def cultivation_damage_scope(ctx,row):
    if row.get('greatblade_cultivation_packet') and owns(ctx.engine,ctx.actor,STROKE):return cultivated_packet(ctx)


@hook('attack_magical')
def cultivation_packet_authority(engine,source_actor_id,typed):
    from ..pending_damage import current
    packet=current(engine);actor=engine.state.actors.get(source_actor_id)
    if packet is None or packet.source_actor_id!=source_actor_id or 'greatblade_cultivation' not in packet.source_flags:return None
    return True if actor is not None and owns(engine,actor,STROKE) else None


_BOUND_SYNC=ContextVar('greatblade_bound_sync',default=None)


@hook('event')
def actual_bound_control(engine,event_type,kwargs):
    """Follow the one real item's committed displacement and control state."""
    if event_type not in {'MOVEMENT_COMMITTED','OBJECT_UPDATED','CONDITION_APPLIED','CONDITION_REMOVED','TURN_STARTED'} or _BOUND_SYNC.get()==id(engine):return
    from .. import acquisition_inventory as inv
    from .qi_path import armament_condition,armament_control_range,update_armament
    from .effect_durations import due
    from . import run_strict
    token=_BOUND_SYNC.set(id(engine))
    try:
        for actor in engine.state.actors.values():
            actual=bond(engine,actor)
            if actual is None:continue
            owner,old=actual;held=armament_condition(actor)
            point=item_point(engine,owner,old)
            obj=engine.state.objects.get('object:recorded_item:'+old['id'])
            blocked=bool(old['profile']['flags'].get('suppressed') or not domain_access(engine,actor)
                or engine.grid.distance_ft(actor.position,point)>armament_control_range(engine,actor)
                or obj and any(v is False for v in run_strict('object_operation_gate',engine,actor,obj,'control',held.source_definition_id if held else ARMAMENT,None)))
            if old['location']=='floating' and held and held.data.get('bound_item_id')==old['id']:
                if blocked:
                    from .body_modes_scene_resources import unconscious
                    bound_item_falls(engine,actor,held,resume=not unconscious(actor))
                elif (held.data['ax'],held.data['ay'],held.data.get('az',0))!=(point.x,point.y,point.z):
                    update_armament(engine,actor,{**held.data,'ax':point.x,'ay':point.y,'az':point.z},held.source_definition_id)
            elif old.get('domain_armament_paused') and not blocked and held is None:
                expiry=old.get('domain_armament_expiry')
                if not expiry or due(engine,expiry):continue
                session=getattr(engine,'scene_source_session',None)
                if session and old.get('domain_armament_expires_at',0)<=session.clock():continue
                items=inv.read(owner);item=items[old['id']]
                item.update(location='floating',holder=actor.entity_id,domain_armament_paused=0)
                commit_bound_item(engine,owner,items,item,point,ARMAMENT)
                from .qi_path import ARMED
                engine._apply_condition(actor,ARMED,ARMAMENT,actor.entity_id,expires_on=expiry,data={
                    'mode':item.get('domain_armament_mode','assault'),'ax':point.x,'ay':point.y,'az':point.z,
                    'reach_ft':armament_control_range(engine,actor),'bound_item_id':item['id'],
                    'bound_item_owner':owner.entity_id,'retain_identity':1,'form_source':STROKE,
                    **({'expires_at':item['domain_armament_expires_at']} if 'domain_armament_expires_at' in item else {}),
                    'label':'Real Greatblade Domain Armament (control restored)'})
    finally:_BOUND_SYNC.reset(token)


@effect('greatblade_conduction_object_hit')
def conduction_object(ctx,row):
    """The original paid native object effect follows its one weapon hit."""
    original=ctx.engine.action_catalog.get(ctx.action.parameters.get('greatblade_delivered_action'))
    obj=ctx.engine.state.objects.get(row.get('recipient_object_id'))
    if original is None or obj is None or ctx.damage_cache.get('greatblade_conducted'):return
    ctx.damage_cache['greatblade_conducted']=1
    from ..typed_executor import run_effects
    typed=deepcopy(original.parameters['typed'])
    if (typed.get('duration') or {}).get('concentration'):ctx.engine._start_concentration(ctx.actor,ctx.source)
    rows=[]
    for effect in typed['effects']:
        rows.extend(effect.get('on_hit',[]) if effect.get('type')=='attack' else [effect])
    # The authorized greatblade hit already supplies the original technique's
    # attack delivery; retain its native object defenses and consequences.
    for effect in walk(rows):
        if effect.get('type')=='object_damage':effect.pop('attack_roll',None)
    ctx.damage_cache['_object']=obj
    run_effects(replace(ctx,typed=typed,critical_hit=False),rows)
