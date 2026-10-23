"""Orbiting Shield Warden: source-owned implements, not scheduled creatures.

Uses native RuntimeObjectState for destructible Qi constructs, bound_objects for
prison anchors, and the public choice, roll, movement and placement contracts.
Only exact acquired features at their printed CL admit actions/passive rows.
All state is evented. Projection metadata never grants physical item ownership.
"""
from dataclasses import replace
from . import hook, effect, note

PREFIX = "tianxia.subpath.qi.orbiting_shield_warden.feature."
RAISE, DEFLECT, CONSTELLATION, BULWARK, NINE = [PREFIX + key for key in (
    "raise_the_orbiting_ward", "deflecting_orbit", "shield_constellation",
    "heaven_revolving_bulwark", "nine_shields_seal_heaven")]
LEVELS = dict(zip((RAISE, DEFLECT, CONSTELLATION, BULWARK, NINE), (3, 6, 10, 14, 18)))
QI = "resource:core.qi"
WARD = "condition:typed.orbiting_ward_control"
PROTECTED = "condition:typed.orbiting_ward_protected"
PRISON = "condition:typed.shield_imprisoned"
SLOWED = "condition:typed.shield_prison_saved"
TAG = "orbiting_warden"


def acquired(info):
    from .qi_path import path_numbers
    n=path_numbers(info)
    return [key for key, level in LEVELS.items() if key in info['owned_ids'] and n is not None
            and int(n['cl']) >= level]


@hook('compile_passives')
def ownership(rows, info):
    from .qi_path import path_numbers
    n=path_numbers(info)
    return [*rows, *({'block': TAG, 'feature_id': key, 'choice_owner':True, 'numbers': dict(n),
                    'armament_link':int('tianxia.path.qi_cultivation.feature.domain_armament_link' in info['owned_ids'] and int(n['cl'])>=13)}
                    for key in acquired(info))]


def profile(engine, actor, feature=None):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == TAG and (r.get('feature_id') == feature if feature is not None else r.get('feature_id') in (RAISE,CONSTELLATION))), None)


def numbers(engine, actor):
    return next((r['numbers'] for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == TAG), {})


def shields(engine, actor, *, inactive=False):
    return [obj for obj in engine.state.objects.values() if not obj.destroyed
            and (obj.component or {}).get(TAG, {}).get('owner') == actor.entity_id
            and not obj.component[TAG].get('formation_only')
            and obj.component[TAG].get('location','floating') == 'floating'
            and (inactive or not obj.suppressed and not asset_prisons(engine,obj)
                 and actor.turns_started>=int(obj.component[TAG].get('cracked_until_turn') or 0))]


def controls(actor):
    return [c for c in actor.conditions.values() if c.condition_id == WARD]


def protection(engine, target):
    for owner in engine.state.actors.values():
        if not owner.active or not profile(engine, owner):
            continue
        held = [o for o in shields(engine, owner) if not asset_prisons(engine,o) and o.component[TAG].get('protected') == target.entity_id and owner.turns_started<int(o.component[TAG].get('protected_until') or 0)
                and any(c.data.get('object_id') == o.object_id for c in controls(owner))]
        if held:
            yield owner, held


def update(engine, obj, source, **changes):
    data = {**obj.component[TAG], **changes}
    result = obj.model_copy(update={'component': {**obj.component, TAG: data}})
    engine._update_object(result, source, data['owner'])
    return result


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    owned = acquired(info)
    if not owned:
        return None
    from .qi_path import path_numbers
    info={**info,'numbers':path_numbers(info)}
    out = []
    def make(key, label, feature, economy='NONE', cost=0, target='SELF', reach=None, **extra):
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.warden.{key}",
            display_name=label, owner_id=info['actor_id'], economy=economy, resolution_kind='TYPED',
            target_kind=target, range_ft=reach, costs=((QI, cost),) if cost else (),
            parameters={'warden':key, 'description':label,
                'typed':{'source':feature, 'manual_inline_choice':True, 'numbers':dict(info['numbers']), 'effects':[{'type':'warden_command','command':key}],
                         'duration':({'kind':'minutes','amount':1,'concentration':True} if feature==NINE else {'kind':'instant'}), 'riders':[]}, **extra}))
    if RAISE in owned:
        make('manifest', 'Manifest Ward — Bonus Action, 1 Qi, one point within 30 feet, 8 hours', RAISE, 'BONUS_ACTION',1)
    if RAISE in owned or CONSTELLATION in owned:
        common=RAISE if RAISE in owned else CONSTELLATION
        make('move', 'Move Shields — once on your turn, up to 30 feet each, within 60 feet', common)
        make('dismiss', 'Dismiss Orbiting Shields', common)
    from .qi_path import ARMAMENT
    if ARMAMENT in info['owned_ids'] and int(info['numbers']['cl'])>=9:
        common=CONSTELLATION if CONSTELLATION in owned else RAISE
        make('release_bound', 'Release bound Shield — Bonus Action, one point within 30 feet',common,'BONUS_ACTION')
        make('call_bound', 'Call bound Shield — Bonus Action, requires a free hand and a clear route',common,'BONUS_ACTION')
        if CONSTELLATION not in owned:
            make('bound_mode','Bound Shield: change Guard or Assault Mode — once on your turn, no action',common)
            for dtype in ('force','bludgeoning'):
                make('bound_strike.'+dtype,'Bound Shield Domain Armament Attack: '+dtype.title()+' — Bonus Action, move up to 20 feet then attack',common,
                     'BONUS_ACTION')
    if DEFLECT in owned:
        make('deflect', 'Deflect the Projectile — triggered new Force attack, once per round',DEFLECT,target='HOSTILE_ENTITY',reach=60)
        n=info['numbers']
        typed={**out[-1].parameters['typed'],'range_ft':60,'effects':[{'type':'attack','attack_kind':'cultivation_ranged','count':1,
            'on_hit':[{'type':'damage','applies_to':'target','dice':{'count':5 if int(n['cl'])>=17 else 3,'sides':8},
                'formula':'key_ability_modifier','damage_types':['force']}]}]}
        out[-1]=out[-1].model_copy(update={'parameters':{**out[-1].parameters,'typed':typed}})
    if CONSTELLATION in owned:
        make('constellation', 'Manifest Constellation — Bonus Action, 3 Qi, up to three Shields, 8 hours', CONSTELLATION,'BONUS_ACTION',3)
        make('assign', 'Constellation Movement — change protected creatures and shield modes',CONSTELLATION)
        for dtype in ('force','bludgeoning'):
            make('strike.'+dtype, 'Revolving Shield Strike: '+dtype.title()+' — Bonus Action',CONSTELLATION,
                 'BONUS_ACTION',target='HOSTILE_ENTITY',reach=5)
    if NINE in owned:
        make('shelter', 'Nine Shields: Sheltered Heaven — Action, 8 Qi, 40-foot cylinder, 1 minute concentration',NINE,'ACTION',8)
        make('prison', 'Nine Shields: Imprisoning Earth — Action, 8 Qi, one creature or Large-or-smaller Cultivation Asset within 90 feet, 1 minute concentration',NINE,'ACTION',8,'ANY_CREATURE',90)
    return out


def choose(engine, actor, key, options, *, subject=None, labels=None, optional=True, maximum=1, preferred=None, prompt=None):
    from .rider_choices import pick
    from ..target_knowledge import can_see
    subject = subject or actor
    if labels is None:
        labels={option:(engine.state.actors[option].display_name if option in engine.state.actors else
                        'Point '+option.removeprefix('cell:') if option.startswith('cell:') else option.replace('_',' ').title()) for option in options}
    from ..senses import perceives_cell
    from .needle import position_of
    auto = [key for key in options if (can_see(engine,actor,engine.state.actors[key]) if key in engine.state.actors
        else perceives_cell(engine,actor,position_of(key)) if key.startswith('cell:') else True)]
    return pick(engine, actor, 'warden.'+key, 'Orbiting Shield Warden', list(options), subject=subject,
                labels=labels, optional=optional, maximum=maximum, preferred=preferred,
                prompt=prompt, automatic_options=auto)


def locations(engine, actor, start, feet, *, initial=False, near=None, control=60, placement=False):
    """Native volume geometry for non-actor Hover; no second mover or scheduler."""
    from ..gate2_runtime_models import Position
    from ..targeting import line_of_effect
    from ..footprints import ActorFootprintDefinition
    footprint=ActorFootprintDefinition.rectangle(1,1,footprint_id='footprint:warden.small',source_definition_id=RAISE)
    def controlled(a,b):
        return engine.grid.distance_ft(actor.position,b)<=control
    if initial or placement:
        occupied={cell for other in engine.state.actors.values() if other.active for cell in engine._actor_volume(other)} if initial else set()
        cells=[]
        for z in range(max(0,start.z-feet//5),start.z+feet//5+1):
            for y in range(max(0,start.y-feet//5),min(engine.grid.height,start.y+feet//5+1)):
                for x in range(max(0,start.x-feet//5),min(engine.grid.width,start.x+feet//5+1)):
                    cell=Position(x=x,y=y,z=z)
                    if (engine.grid.distance_ft(start,cell)<=feet and controlled(start,cell)
                            and engine.grid.volume_legal(cell,footprint=footprint,occupied_cells=occupied)
                            and line_of_effect(engine,actor,destination=cell)):
                        cells.append(cell)
    else:
        routes=engine.grid.reachable(start,movement_ft=feet,footprint=footprint,volume=True,edge_allowed=controlled)
        cells=[start,*routes]
    return [p for p in cells if controlled(start,p) and (near is None or engine.grid.distance_ft(near.position,p)<=5)]


def point_choice(engine, owner, key, cells, *, optional=False, subject=None):
    from .needle import cell_id, position_of
    opts={cell_id(c,include_altitude=True):c for c in cells}
    picked=choose(engine,owner,key,list(opts),subject=subject,labels={k:f"Point ({c.x}, {c.y}, {c.z*5} feet high)" for k,c in opts.items()},optional=optional)
    return opts[picked[0]] if picked else None


def destroy(engine,obj,source):
    if not obj.component[TAG].get('projected'):
        # Ending a manifestation never destroys the actual inventory item.
        if obj.destroyed:
            return
        update(engine,obj.model_copy(update={'unattended':True}),source,location='fallen',protected='')
        owner=engine.state.actors.get(obj.owner_id)
        if owner and bound_shield(owner):
            drop_bound(engine,owner,bound_shield(owner),obj.position,source)
        return
    if not obj.destroyed:
        engine._update_object(obj.model_copy(update={'destroyed':True,'current_hp':0}),source,obj.component[TAG]['owner'])


def clear(engine,actor,source,*,preserve_real=False):
    from .condition_ownership import remove_instance
    if preserve_real:
        for obj in shields(engine,actor,inactive=True):
            if not obj.component[TAG].get('projected'):
                update(engine,obj,source,location='carried',protected='')
    for c in controls(actor):
        remove_instance(engine,actor,c.instance_id,source)
    for obj in shields(engine,actor,inactive=True):
        destroy(engine,obj,source)


def manifest(ctx,count):
    from ..gate2_runtime_models import RuntimeObjectState
    from .effect_durations import round_token
    engine,owner=ctx.engine,ctx.actor
    points=[]
    for i in range(count):
        cells=locations(engine,owner,owner.position,30,initial=True)
        point=point_choice(engine,owner,f'manifest.{i}',cells,optional=i>0)
        if point is None:
            break
        points.append(point)
    if not points:
        raise ValueError('Choose an unoccupied point within 30 feet for the Ward.')
    n=ctx.numbers
    bond=bound_shield(owner)
    picked=[]
    if bond and bound_available(engine,owner,bond):
        picked=choose(engine,owner,'manifest.bound',['projected','bound'],optional=False,
            labels={'projected':'Use projected Wards only','bound':'Release the actual bound shield in place of one Ward'})
    clear(engine,owner,ctx.source,preserve_real=picked==['bound'])
    if picked==['bound']:
        release_bound(ctx,points.pop(0))
    for point in points:
        oid=f"object:warden.{owner.entity_id}.{engine.state.event_sequence+1}"
        engine._apply_condition(owner,WARD,ctx.source,owner.entity_id,expires_on=round_token(engine,4800),
            data={'object_id':oid,'label':'Orbiting Ward — 8 hours; ends if destroyed, replaced, dismissed or Unconscious'})
        obj=RuntimeObjectState(object_id=oid,object_kind='QI_CONSTRUCT',owner_id=owner.entity_id,position=point,unattended=True,flammable=False,
            ac=14+int(n['pb']),current_hp=3*int(n['cl']),maximum_hp=3*int(n['cl']),
            damage_immunities=('POISON','PSYCHIC'),component={'name':'Orbiting Ward','size':'small','blocks':False,
                'resist':['BLUDGEONING','PIERCING','SLASHING'],'kind':'cultivation_implement','qi_construct':1,'source_cl':int(n['cl']),'created_by':ctx.source,
                TAG:{'owner':owner.entity_id,'source_cl':int(n['cl']),'mode':'guard','protected':'','projected':1,'protected_until':0}})
        engine._update_object(obj,ctx.source,owner.entity_id)


def assign(engine,owner,obj,key):
    if asset_prisons(engine,obj):
        return update(engine,obj,RAISE,protected='') if obj.component[TAG].get('protected') else obj
    targets=[a for a in engine.state.actors.values() if a.active and engine.grid.distance_ft(obj.position,a.position)<=5]
    ids=[a.entity_id for a in targets]
    from ..relations import relation, ALLY
    picked=choose(engine,owner,'protect.'+key,ids,labels={a.entity_id:a.display_name for a in targets},
                  preferred=[a.entity_id for a in targets if relation(engine,owner,a)==ALLY],
                  prompt='Assign Protection: choose one creature within 5 feet of this Shield. It gains +2 AC against ranged attack rolls until your next turn starts. Additional Shields grant Layers instead of stacking AC.') if ids else []
    return update(engine,obj,RAISE,protected=picked[0] if picked else '',protected_until=owner.turns_started+1)


def move_shield(engine,owner,obj,feet,key,*,near=None,escort=True):
    from .object_subjects import movement_held
    from . import run_strict
    if movement_held(obj) or False in run_strict('object_operation_gate',engine,owner,obj,'move',RAISE,getattr(engine,'_active_intent',None)):
        return obj
    control=shield_control(engine,owner,obj)
    if not obj.component[TAG].get('projected') and control==30:
        feet=min(feet,20)
    point=point_choice(engine,owner,key,locations(engine,owner,obj.position,feet,near=near,control=control),optional=True,subject=near)
    if point is None or point==obj.position:
        return obj
    obj=obj.model_copy(update={'position':point})
    engine._update_object(obj,RAISE,owner.entity_id)
    if escort and profile(engine,owner,DEFLECT):
        escort_step(engine,owner,obj,key)
    return obj


def escort_step(engine,owner,obj,key):
    from .willing_targets import asks_consent
    from .granted_movement import choices, move
    from .rider_choices import intent_for
    from .needle import cell_id
    if owner.turn_flags.get('once_per_turn:warden_escort'):
        return
    nearby=[a for a in engine.state.actors.values() if a.active and not a.turn_flags.get('once_per_turn:warden_escorted')
            and engine.grid.distance_ft(obj.position,a.position)<=5]
    selected=choose(engine,owner,'escort.target.'+key,[a.entity_id for a in nearby],labels={a.entity_id:a.display_name for a in nearby}) if nearby else []
    if not selected:
        return
    target=engine.state.actors[selected[0]]
    if not asks_consent(engine,intent_for(engine),target,DEFLECT,'Shield-Step Escort: accept a 5-foot move without Opportunity Attacks?',prefer_accept=target.team_id==owner.team_id,asker=owner):
        return
    paths=[p for p in choices(engine,target,5) if engine.grid.distance_ft(obj.position,p.destination)<=5]
    opts={cell_id(p.destination):p for p in paths}
    picked=choose(engine,owner,'escort.step.'+key,list(opts),subject=target) if opts else []
    if picked:
        move(engine,target,opts[picked[0]],intent_for(engine),5,list(engine.state.actors),name='Shield-Step Escort')
        owner.turn_flags['once_per_turn:warden_escort']=1
        target.turn_flags['once_per_turn:warden_escorted']=1


@effect('warden_command',harmful=False)
def command(ctx,row):
    engine,owner=ctx.engine,ctx.actor
    do=row.get('command')
    feature=ctx.typed.get('source')
    if not profile(engine,owner,feature):
        raise ValueError('This Shield Warden feature is not acquired at its required Cultivation Level.')
    if do in ('manifest','constellation'):
        manifest(ctx,3 if do=='constellation' else 1)
    elif do=='dismiss':
        clear(engine,owner,ctx.source)
    elif do=='release_bound':
        point=point_choice(engine,owner,'bound.release',locations(engine,owner,owner.position,30,initial=True))
        release_bound(ctx,point)
    elif do=='call_bound':
        call_bound(ctx)
    elif do=='bound_mode':
        obj=next(o for o in shields(engine,owner) if not o.component[TAG].get('projected'))
        selected=choose(engine,owner,'bound.mode',['guard','assault'],optional=False,
            labels={'guard':'Guard Mode — protect a creature within 5 feet','assault':'Assault Mode — permit a Domain Armament Attack'})
        update(engine,obj,ctx.source,mode=selected[0],protected='')
        owner.turn_flags['warden_bound_mode']=1
    elif str(do).startswith('bound_strike.'):
        bound_strike(ctx,str(do).split('.')[1])
    elif do in ('move','assign'):
        key='warden_move' if do=='move' else 'warden_assign'
        if owner.turn_flags.get(key):
            raise ValueError('You already used Constellation Movement this turn.')
        initial_real=any(not o.component[TAG].get('projected') for o in shields(engine,owner))
        for obj in shields(engine,owner):
            if do=='assign' and not obj.component[TAG].get('projected'):
                from .hand_occupancy import free_hands
                if free_hands(engine,owner):
                    use=choose(engine,owner,'bound.use',['floating','wielded'],optional=False,
                        labels={'floating':'Keep this actual Shield floating','wielded':'Wield this actual Shield in a free hand; no action or Qi'})
                    if use==['wielded']:
                        call_bound(ctx)
                        continue
            if do=='move':
                move_shield(engine,owner,obj,30,'move.'+obj.object_id)
            else:
                assign(engine,owner,obj,obj.object_id)
                modes=choose(engine,owner,'mode.'+obj.object_id,['guard','assault'],optional=False,
                    labels={'guard':'Guard Mode — protect a nearby creature','assault':'Assault Mode — permit Revolving Shield Strike'})
                update(engine,engine.state.objects[obj.object_id],ctx.source,mode=modes[0])
        if do=='assign' and not initial_real:
            bond=bound_shield(owner)
            if bond and bound_available(engine,owner,bond):
                use=choose(engine,owner,'bound.use',['carried','floating'],optional=False,
                    labels={'carried':'Keep the actual Shield in hand or carried','floating':'Release the actual Shield within 30 feet; no action or Qi'})
                if use==['floating']:
                    point=point_choice(engine,owner,'bound.release',locations(engine,owner,owner.position,30,initial=True))
                    release_bound(ctx,point)
        owner.turn_flags[key]=1
    elif str(do).startswith('strike.'):
        strike(ctx,str(do).split('.')[1])
    elif do=='prison' and ctx.typed.get('recipient_object_id'):
        imprison_asset(ctx,engine.state.objects[ctx.typed['recipient_object_id']])
    elif do in ('shelter','prison'):
        formation(ctx,do)


@hook('candidate_allowed')
def allowed(engine,actor,candidate,action):
    do=(action.parameters if action else {}).get('warden')
    if not do:
        return None
    feature=action.parameters['typed']['source']
    if not profile(engine,actor,feature):
        return False
    if do in ('release_bound','call_bound'):
        bond=bound_shield(actor)
        if bond is None:
            return False
        if do=='release_bound':
            return bound_available(engine,actor,bond) and not any(not o.component[TAG].get('projected') for o in shields(engine,actor))
        from .hand_occupancy import free_hands
        return bool(free_hands(engine,actor)) and any(not o.component[TAG].get('projected') for o in shields(engine,actor))
    if do=='bound_mode':
        return any(not o.component[TAG].get('projected') for o in shields(engine,actor)) and not actor.turn_flags.get('warden_bound_mode')
    if do.startswith('bound_strike.'):
        held=[o for o in shields(engine,actor) if not o.component[TAG].get('projected') and o.component[TAG]['mode']=='assault'
              and (not imprisoned(actor) or o.position in prison_cells(engine,actor))]
        origin=(candidate.metadata or {}).get('effect_origin')
        if action.target_kind!='SELF':
            # The public attack-recipient query projects this SELF parent to
            # its actual creature attack; its origin must still be published.
            return bool(origin and any(o.object_id==origin['id'] for o in held))
        return not origin and bool(held)
    if do=='deflect':
        return False  # the missed-attack consumer alone may activate it
    if do=='assign' and not actor.turn_flags.get('warden_assign') and bound_shield(actor) and bound_available(engine,actor,bound_shield(actor)):
        return True
    if do in ('move','assign','dismiss'):
        return bool(shields(engine,actor)) and not actor.turn_flags.get('warden_'+('move' if do=='move' else 'assign'))
    if do.startswith('strike.'):
        return any(o.component[TAG]['mode']=='assault' and not asset_prisons(engine,o) for o in shields(engine,actor))
    if do in ('shelter','prison'):
        return not actor.turn_flags.get('_round_warden_nine_scene')
    return None


@hook('turn_end')
def end_turn(engine,owner):
    if not profile(engine,owner):
        return
    for obj in shields(engine,owner):
        if obj.component[TAG]['mode']=='guard':
            assign(engine,owner,obj,obj.object_id)
    refresh_layers(engine,owner)


@hook('turn_start')
def refresh(engine,owner):
    if not profile(engine,owner):
        return
    refresh_layers(engine,owner,refill=True)


@hook('state_event')
def lifecycle(engine,event):
    if event.event_type not in ('CONDITION_REMOVED','CONDITION_APPLIED','MOVEMENT_COMMITTED','OBJECT_UPDATED','DAMAGE_COMMITTED'):
        return
    for owner in list(engine.state.actors.values()):
        if not profile(engine,owner):
            continue
        ids={c.data['object_id'] for c in controls(owner)}
        from ..typed_executor import condition_rules
        unconscious=any(c.condition_id in ('condition:unconscious','condition:typed.unconscious','condition:core.unconscious','unconscious') for c in owner.conditions.values())
        for obj in list(shields(engine,owner,inactive=True)):
            if obj.object_id not in ids or unconscious or owner.life_state in ('DYING','STABLE'):
                destroy(engine,obj,RAISE)
            elif engine.grid.distance_ft(owner.position,obj.position)>shield_control(engine,owner,obj):
                if not obj.component[TAG].get('projected'):
                    destroy(engine,obj,RAISE)
                    continue
                from .object_subjects import movement_held
                if movement_held(obj):
                    continue
                cells=locations(engine,owner,owner.position,60)
                if cells:
                    nearest=min(cells,key=lambda c:(engine.grid.distance_ft(obj.position,c),c.y,c.x))
                    engine._update_object(obj.model_copy(update={'position':nearest}),RAISE,owner.entity_id)


def paid_response(engine,owner,recipient,feature,cost,*,reaction=True,action=None,range_origin=None):
    """Enter the shared native declaration before any source cost or effect."""
    from contextlib import contextmanager
    from ..typed_reactions import reaction_activation,spend_reaction
    from ..activation_payments import reaction_completed
    from . import run_strict
    row={'feature_id':feature,'name':action.display_name if action else 'Orbiting Shield Warden response',
         'numbers':numbers(engine,owner),'effects':[], 'free':not reaction,
         'range_ft':action.range_ft if action else None,
         'costs':[{'resource_id':QI,'amount':cost}] if cost else []}
    if action is not None:
        row['source_action_id']=action.source_definition_id
    @contextmanager
    def transaction():
        with reaction_activation(engine,owner,recipient,row,range_origin=range_origin) as ctx:
            if ctx is None:
                yield None
                return
            engine._spend_costs(owner,ctx.action.costs,ctx.source)
            if reaction:
                spend_reaction(engine,owner,row)
            if not reaction_completed(engine,owner,ctx.source,consumes_reaction=reaction):
                yield None
                return
            yield ctx
            if ctx.damage_cache.get('warden_response_resolved'):
                run_strict('technique_used',ctx)
                from ..paid_relocation import settle_activation
                settle_activation(engine,owner,ctx.source)
    return transaction()


@hook('hit_response')
def guard(engine,attacker,target,spec,total,natural,effective_ac):
    ranged=is_ranged_strike(engine,spec)
    protected=list(protection(engine,target))
    if not protected:
        return None
    from ..armour import shield_bonus_earning
    bonus=max((shield_guard_bonus(engine,o) for _,objs in protected for o in objs),default=2)
    ac=effective_ac+(max(0,bonus-max(shield_bonus_earning(engine,target),provided_shield_bonus(engine,target))) if ranged else 0)
    if natural<20 and total<ac:
        remember_deflection(engine,attacker,target,spec,protected,ac,effective_ac,total)
        return {'armor_class':ac,'hit':False,'miss_reason':'armor_class'}
    from ..typed_reactions import can_react,spend_reaction
    from .attack_reduction import park
    from ..gate2_runtime_models import DiceSpec
    for owner,objs in protected:
        if not profile(engine,owner,RAISE):
            continue
        cost=0 if active_formation(engine,owner) else 1
        if owner.turn_flags.get('_round_warden_interpose')==engine.state.round_number or not can_react(engine,owner) or owner.resources.get(QI,0)<cost:
            continue
        legal=[o for o in objs if locations(engine,owner,o.position,15,near=target)]
        if not legal:
            continue
        mode=choose(engine,owner,'interpose.'+str(engine.state.event_sequence),['turn','absorb'],subject=target,
             labels={'turn':f'Turn the Blow: +{owner.proficiency_bonus} AC against this attack, {cost} Qi and Reaction',
                     'absorb':f'Absorb the Blow: reduce damage by dice plus your key modifier, {cost} Qi and Reaction'})
        if not mode:
            continue
        with paid_response(engine,owner,target,RAISE,cost) as paid:
            if paid is None:
                continue
            obj=move_shield(engine,owner,legal[0],15,'interpose.move',near=target,escort=False)
            if engine.grid.distance_ft(obj.position,target.position)>5:
                continue
            owner.turn_flags['_round_warden_interpose']=engine.state.round_number
            if mode==['turn']:
                ac+=int(owner.proficiency_bonus)
            else:
                n=numbers(engine,owner);cl=int(n['cl'])
                roll=engine.roller.roll(DiceSpec(count=2+int(cl>=11)+int(cl>=17),sides=8,modifier=int(n.get('key_mod') or 0)),actor_id=owner.entity_id,reason='Warden Absorb the Blow')
                engine._record_roll(roll)
                park(target,attacker.entity_id,max(0,roll.total),RAISE,engine=engine)
            paid.damage_cache['warden_response_resolved']=1
            note(engine,RAISE,owner,f"Warden's Interposition protects {target.display_name} for {cost} Qi and a Reaction.",[target])
            # Shield-Step Escort follows the qualifying Interposition movement.
            if profile(engine,owner,DEFLECT):
                escort_step(engine,owner,obj,'interpose.escort.'+obj.object_id)
            if natural<20 and total<ac:
                remember_deflection(engine,attacker,target,spec,[(owner,objs)],ac,effective_ac,total)
                return {'armor_class':ac,'hit':False,'miss_reason':'armor_class'}
    return None


@hook('save')
def brace(ctx,subject,ability,named):
    if brace_categories(ctx,named) and any(profile(ctx.engine,o,DEFLECT) for o,_ in protection(ctx.engine,subject)):
        return {'modes':['ADVANTAGE']}
    return None


@hook('save_final')
def save_outcome(ctx,subject,ability,named,failed):
    if not failed and brace_categories(ctx,named) and any(profile(ctx.engine,o,DEFLECT) for o,_ in protection(ctx.engine,subject)):
        ctx.damage_cache['warden_braced:'+subject.entity_id]=1


@hook('forced_movement_reduction')
def brace_reduce(ctx,subject):
    return 10 if ctx.damage_cache.get('warden_braced:'+subject.entity_id) else None


def active_formation(engine,owner):
    from . import placed
    return next(iter(placed.of(engine,TAG,owner_id=owner.entity_id)),None)


def bound_strike(ctx,dtype):
    """Move first, then choose a perceived legal recipient; no speculative target peek.

    Every legal route remains in the movement choice. Target choices are built
    only after that choice, avoiding a point-by-creature Cartesian menu.
    """
    from ..action_geometry import activate
    from ..attack_declaration import can_target
    from ..typed_executor import run_effects
    from ..relations import relation,ENEMY
    engine,owner=ctx.engine,ctx.actor
    obj=next((o for o in shields(engine,owner) if not o.component[TAG].get('projected') and o.component[TAG]['mode']=='assault'),None)
    if obj is None:
        raise ValueError('Choose the actual floating Shield in Assault Mode.')
    point=point_choice(engine,owner,'bound.attack.move',locations(engine,owner,obj.position,20,
        control=shield_control(engine,owner,obj)),optional=True)
    if point is not None and point!=obj.position:
        obj=obj.model_copy(update={'position':point})
        engine._update_object(obj,ctx.source,owner.entity_id)
        if profile(engine,owner,DEFLECT):
            escort_step(engine,owner,obj,'bound.attack.move')
    typed,attack=shield_attack(ctx,obj,dtype)
    action=ctx.action.model_copy(update={'target_kind':'ANY_CREATURE','range_ft':5})
    with activate(engine,owner,ctx.source,shield_origin(obj)):
        # Recipient legality is for the delivered attack, not the SELF parent
        # that already spent this Bonus Action and collected its movement.
        targets=[a for a in engine.state.actors.values() if a.active and can_target(engine,owner,a,ctx.source,
            action=action,typed_profile={**typed,'effects':[attack]},range_ft=5)]
        selected=choose(engine,owner,'bound.attack.target',[a.entity_id for a in targets],optional=False,
            labels={a.entity_id:a.display_name for a in targets},
            preferred=[a.entity_id for a in targets if relation(engine,owner,a)==ENEMY],
            prompt='Bound Shield Domain Armament Attack: choose one perceived creature within 5 feet of the Shield after its movement. The Bonus Action is already spent; no Qi cost.') if targets else []
        if selected:
            target=engine.state.actors[selected[0]]
            run_effects(replace(ctx,action=action,typed=typed,targets=[target],target=target),[attack])


def strike(ctx,dtype):
    from ..typed_executor import run_effects
    target=ctx.target
    if target is None:
        return
    objs=[o for o in shields(ctx.engine,ctx.actor) if o.component[TAG]['mode']=='assault' and not asset_prisons(ctx.engine,o)
          and ctx.engine.grid.distance_ft(o.position,target.position)<=5]
    picked=choose(ctx.engine,ctx.actor,'strike.shield',[o.object_id for o in objs],optional=False,
        labels={o.object_id:'Orbiting Ward' for o in objs}) if objs else []
    if not picked:
        raise ValueError('Choose a Shield in Assault Mode within 5 feet of the target.')
    obj=ctx.engine.state.objects[picked[0]]
    from ..action_geometry import activate
    typed,attack=shield_attack(ctx,obj,dtype)
    with activate(ctx.engine,ctx.actor,ctx.source,shield_origin(obj)):
        run_effects(replace(ctx,typed=typed),[attack])
    obj=move_shield(ctx.engine,ctx.actor,obj,15,'strike.move')
    assign(ctx.engine,ctx.actor,obj,'strike.protect')


def formation(ctx,mode):
    from . import placed
    from .bound_objects import place
    from .effect_durations import round_token
    from .passive_rows import known_level
    from ..typed_executor import run_effects
    engine,owner=ctx.engine,ctx.actor
    if owner.turn_flags.get('_round_warden_nine_scene'):
        raise ValueError('Nine Shields Seal Heaven can be used only once per scene.')
    if mode=='shelter':
        cells=locations(engine,owner,owner.position,90,control=90,placement=True)
        center=point_choice(engine,owner,'shelter.center',cells)
        targets=[a for a in engine.state.actors.values() if a.active and a.team_id==owner.team_id
                 and engine.grid.distance_ft(center,a.position)<=40 and abs(a.position.z-center.z)*5<=40]
        picked=choose(engine,owner,'shelter.allies',[a.entity_id for a in targets],
            labels={a.entity_id:a.display_name for a in targets},maximum=len(targets),optional=True) if targets else []
        zone=placed.place(engine,owner,source=ctx.source,tag=TAG,cells=center,name='Formation of the Sheltered Heaven',
            placed={'mode':mode,'chosen':picked,'source_cl':int(ctx.numbers['cl']),'save_dc':int(ctx.numbers['save_dc']),
                    'benefited':[],'cracked_id':'','last_intercession_round':-1,'until':round_token(engine,10)},
            duration_rounds=None,concentration=True,shape='cylinder',size_ft=40,radial_volume=True,
            extra={'height_ft':40},numbers=ctx.numbers)
    else:
        target=ctx.target
        if target is None:
            raise ValueError('Choose one creature within 90 feet.')
        run_effects(ctx,[{'type':'save','ability':'STR_OR_CHA','target_choice':True,'applies_to':'target',
            'on_fail':[{'type':'warden_prison_result','success':False}],
            'on_success':[{'type':'warden_prison_result','success':True}]}])
        zone=placed.place(engine,owner,source=ctx.source,tag=TAG,cells=target.position,name='Formation of the Imprisoning Earth',
            placed={'mode':mode,'target':target.entity_id,'source_cl':int(ctx.numbers['cl']),'until':round_token(engine,10)},duration_rounds=None,concentration=True,numbers=ctx.numbers)
    held=shields(engine,owner,inactive=True)
    manifestations=[{'id':o.object_id,'object_id':o.object_id,'position':o.position.model_dump(mode='json')} for o in held]
    manifestations.extend({'id':f'warden.nine.{zone.zone_id}.{i}','position':zone.center.model_dump(mode='json')}
                          for i in range(len(manifestations),9))
    placed.update(engine,zone,manifestations=manifestations)
    owner.turn_flags['_round_warden_nine_scene']=1



@effect('warden_prison_result')
def prison_result(ctx,row):
    from .bound_objects import place
    from .effect_durations import round_token
    from .passive_rows import known_level
    engine,owner,target=ctx.engine,ctx.actor,ctx.target
    if target is None or not profile(engine,owner,NINE):
        return
    if row.get('success'):
        engine._apply_condition(target,SLOWED,ctx.source,owner.entity_id,expires_on='END_OF_SOURCE_NEXT_TURN',
            data={'rule':{'no_reactions':True},'label':'Shield Prison: Speed halved, no willing teleport or Reactions until the end of the Warden’s next turn'})
        engine._add_modifier(target,ctx.source,'speed_halved','ADD',1,'SELF',expires_on='END_OF_SOURCE_NEXT_TURN')
        return
    level=known_level(engine,target)
    lower=level is not None and int(ctx.numbers['cl'])-level>=6
    engine._apply_condition(target,PRISON,ctx.source,owner.entity_id,expires_on=round_token(engine,10),
        data={'source_cl':int(ctx.numbers['cl']),'save_dc':int(ctx.numbers['save_dc']),
            'ability':ctx.origin_save['ability'],'lower_by_six':int(lower),'rule':{'speed_zero':True},
            'label':'Shield-Imprisoned: Speed 0; cannot teleport, phase or affect outside; Total Cover from outside unless a sealed barrier can be penetrated'})
    condition=next(c for c in reversed(list(target.conditions.values())) if c.condition_id==PRISON and c.source_actor_id==owner.entity_id)
    anchor=place(ctx,{'name':'Shield Prison Anchor','ac':'save_dc','hp':'9*cl','native_lifecycle':True,
        'resist':[],
        'immune':['POISON','PSYCHIC']},holder=target,instance_ids=[condition.instance_id],position=target.position)
    engine._update_object(anchor.model_copy(update={'damage_threshold':2*int(ctx.numbers['pb'])}),ctx.source,owner.entity_id)
    engine._update_condition_data(target,condition,{**condition.data,'anchor_id':anchor.object_id},ctx.source)


@hook('turn_end')
def prison_repeat(engine,target):
    from ..typed_executor import Context,run_effects
    from .rider_choices import intent_for
    for c in list(target.conditions.values()):
        if c.condition_id!=PRISON or c.data.get('lower_by_six') or c.data.get('suspended'):
            continue
        owner=engine.state.actors.get(c.source_actor_id)
        action=engine.action_catalog.get(c.source_definition_id)
        if owner is None or action is None:
            continue
        typed={**action.parameters['typed'],'warden_prison_repeat':1,'numbers':{**numbers(engine,owner),'save_dc':int(c.data['save_dc'])}}
        ctx=Context(engine,owner,action,intent_for(engine),typed,[target],target,{})
        run_effects(ctx,[{'type':'save','ability':c.data['ability'],'applies_to':'target',
            'on_fail':[],'on_success':[{'type':'warden_prison_release','instance':c.instance_id}]}])


@effect('warden_prison_release',harmful=False)
def prison_release(ctx,row):
    from .condition_ownership import remove_instance
    if ctx.target and row['instance'] in ctx.target.conditions:
        held=ctx.target.conditions[row['instance']]
        if held.condition_id==PRISON and held.source_actor_id==ctx.actor.entity_id:
            remove_instance(ctx.engine,ctx.target,held.instance_id,ctx.source)


def prison_asset_eligible(obj):
    from .object_subjects import eligible
    from ..dynamic_size import category_name
    return not obj.destroyed and category_name(obj.component.get('size')).lower() in ('tiny','small','medium','large') and (
        eligible(obj) and (obj.object_kind=='SPIRIT_ASSET' or obj.component.get('spiritual_profile',{}).get('cultivation_asset')==1)
        or obj.component.get('qi_construct')==1 or bool(obj.component.get(TAG,{}).get('projected')))


@hook('object_targets')
def prison_asset_targets(engine,actor,action):
    if (action.parameters or {}).get('warden')=='prison' and profile(engine,actor,NINE):
        from .object_subjects import known_to
        from ..senses import perceives_object
        return [o.object_id for o in engine.state.objects.values() if prison_asset_eligible(o)
            and (known_to(o,actor) or o.component.get('qi_construct')==1 or o.component.get(TAG,{}).get('projected'))
            and perceives_object(engine,actor,o)]
    return None


@hook('object_action')
def prison_asset_action(engine,actor,action,obj,candidate,intent):
    if (action.parameters or {}).get('warden')!='prison' or not profile(engine,actor,NINE):
        return None
    if not prison_asset_eligible(obj):
        raise ValueError('Imprisoning Earth requires one Large-or-smaller Cultivation Asset.')
    from ..typed_executor import resolve_typed
    typed={**action.parameters['typed'],'recipient_object_id':obj.object_id}
    resolve_typed(engine,actor,None,action.model_copy(update={'parameters':{**action.parameters,'typed':typed}}),candidate,intent)
    return True


def asset_prison_save(ctx,obj,ability=None):
    from .object_subjects import save
    if ability is None:
        decider=ctx.engine.state.actors.get(obj.owner_id) or ctx.actor
        picked=choose(ctx.engine,decider,'prison.asset.save.'+obj.object_id,['STR','CHA'],subject=decider,
            labels={'STR':'Strength saving throw','CHA':'Charisma saving throw'},optional=False,
            prompt='Imprisoning Earth: choose Strength or Charisma for '+obj.component.get('name','this Cultivation Asset')+'. A failed save imprisons it for up to 1 minute; success halves its Speed and prevents willing teleport and Reactions until the end of the Warden’s next turn.')
        ability=picked[0]
    return save(ctx,obj,ability),ability


def imprison_asset(ctx,obj):
    from . import placed
    from .bound_objects import place
    from .effect_durations import round_token
    from .object_subjects import put
    engine,owner=ctx.engine,ctx.actor
    failed,ability=asset_prison_save(ctx,obj)
    if not failed:
        put(engine,obj,owner,'speed_halved',{'id':'warden_prison_saved','source_cl':int(ctx.numbers['cl']),
            'no_willing_teleport':1,'no_reactions':1},ctx.source,boundary='end')
        owner.turn_flags['_round_warden_nine_scene']=1
        return
    level=(obj.component.get('spirit_asset') or {}).get('source_cl',obj.component.get('source_cl'))
    if level is None:
        level=(obj.component.get('spiritual_profile') or {}).get('source_cl')
    lower=type(level) is int and int(ctx.numbers['cl'])-level>=6
    zone=placed.place(engine,owner,source=ctx.source,tag=TAG,cells=obj.position,name='Formation of the Imprisoning Earth',
        placed={'mode':'prison','target_object':obj.object_id,'source_cl':int(ctx.numbers['cl']),
            'save_dc':int(ctx.numbers['save_dc']),'ability':ability,'lower_by_six':int(lower),'until':round_token(engine,10)},
        duration_rounds=None,concentration=True,numbers=ctx.numbers)
    anchor=place(ctx,{'name':'Shield Prison Anchor','ac':'save_dc','hp':'9*cl','native_lifecycle':True,
        'immune':['POISON','PSYCHIC']},zone_ids=[zone.zone_id],position=obj.position)
    engine._update_object(anchor.model_copy(update={'damage_threshold':2*int(ctx.numbers['pb'])}),ctx.source,owner.entity_id)
    placed.update(engine,zone,anchor_id=anchor.object_id)
    for kind in ('speed_zero','shield_prison'):
        put(engine,obj,owner,kind,{'id':zone.zone_id,'zone_id':zone.zone_id,
            'source_cl':int(ctx.numbers['cl'])},ctx.source)
    held=shields(engine,owner,inactive=True)
    manifests=[{'id':o.object_id,'object_id':o.object_id,'position':o.position.model_dump(mode='json')} for o in held]
    manifests.extend({'id':f'warden.nine.{zone.zone_id}.{i}','position':obj.position.model_dump(mode='json')} for i in range(len(manifests),9))
    placed.update(engine,zone,manifestations=manifests)
    owner.turn_flags['_round_warden_nine_scene']=1


def asset_prisons(engine,obj):
    from .object_subjects import records
    rows=[]
    for r in records(obj,'shield_prison'):
        zone=engine.state.zones.get(r['data']['zone_id'])
        anchor=engine.state.objects.get(placed_data(zone).get('anchor_id')) if zone else None
        if zone and zone.active and anchor and not anchor.destroyed and not anchor.suppressed:
            rows.append(zone)
    return rows


def placed_data(zone):
    from .placed import data
    return data(zone)


@hook('state_event')
def asset_prison_cleanup(engine,event):
    if event.event_type not in ('OBJECT_UPDATED','ZONE_REMOVED','CONCENTRATION_ENDED'):
        return
    from .object_subjects import KEY,records
    from . import placed
    for obj in list(engine.state.objects.values()):
        rows=records(obj)
        kept=[]
        for r in rows:
            zid=r['data'].get('zone_id') if r['kind'] in ('shield_prison','speed_zero') else None
            zone=engine.state.zones.get(zid) if zid else None
            if zid and (zone is None or not zone.active or obj.destroyed):
                if zone and zone.active:
                    placed.drop(engine,zone,'SUBJECT_DESTROYED')
                continue
            if zone and r['kind']=='speed_zero':
                anchor=engine.state.objects.get(placed_data(zone).get('anchor_id'))
                suspended=int(anchor is not None and bool(anchor.suppressed))
                if suspended or r['data'].get('suspended'):
                    r={**r,'data':{**r['data'],'suspended':suspended}}
            kept.append(r)
        if kept!=rows:
            current=engine.state.objects[obj.object_id]
            engine._update_object(current.model_copy(update={'component':{**current.component,KEY:kept}}),obj.component.get('created_by') or NINE,obj.owner_id)


@hook('turn_end')
def asset_prison_repeat(engine,actor):
    from . import placed
    from ..typed_executor import Context
    from .rider_choices import intent_for
    for obj in list(engine.state.objects.values()):
        if obj.owner_id!=actor.entity_id:
            continue
        for zone in asset_prisons(engine,obj):
            data=placed.data(zone)
            if data.get('lower_by_six'):
                continue
            owner=engine.state.actors[zone.owner_id]
            action=engine.action_catalog[zone.source_definition_id]
            ctx=Context(engine,owner,action,intent_for(engine),{**action.parameters['typed'],
                'numbers':{**numbers(engine,owner),'save_dc':data['save_dc']}},[],None)
            failed,_=asset_prison_save(ctx,obj,data['ability'])
            if not failed:
                placed.drop(engine,zone,'SUCCESSFUL_REPEAT_SAVE')


@hook('object_operation_gate')
def imprisoned_asset_operation(engine,actor,obj,operation,source_id,intent):
    if asset_prisons(engine,obj) and operation in ('move','teleport','phase','change_plane'):
        return False
    from .object_subjects import records
    if operation=='teleport' and any(r['data'].get('no_willing_teleport') for r in records(obj,'speed_halved')):
        return False
    return None


@hook('object_damage_admission')
def prison_asset_cover(engine,actor,obj,packets,source,*,area_scope_resolved=False):
    if asset_prisons(engine,obj) and not penetrating(engine.action_catalog.get(source)):
        return False
    return None


@hook('candidate_allowed')
def imprisoned_asset_origin(engine,actor,candidate,action):
    origin=(candidate.metadata or {}).get('effect_origin') or {}
    obj=engine.state.objects.get(str(origin.get('id') or '').removeprefix(LINK_ORIGIN))
    if obj and asset_prisons(engine,obj):
        from .object_subjects import geometry
        proxy=geometry(engine,obj)
        if any(t!=obj.object_id for t in candidate.target_ids) or (candidate.destination is not None and candidate.destination not in prison_cells(engine,proxy)):
            return False
        typed=((action.parameters or {}).get('typed') or {}) if action else {}
        if (typed.get('area') or typed.get('zone') or typed.get('zone_spec')) and not contained_field(engine,proxy,typed,candidate.destination):
            return False
    return None


def imprisoned(target):
    return [c for c in target.conditions.values() if c.condition_id==PRISON and not c.data.get('suspended')]


def prison_cells(engine,actor):
    """The prison surrounds the held body's occupied volume, not a fixed radius."""
    from ..gate2_runtime_models import Position
    return {Position(x=x,y=y,z=z) for x,y,z in engine._actor_volume(actor)}


def contained_field(engine,actor,typed,aim=None):
    """Printed rule: a prisoner cannot create/maintain a field beyond its prison."""
    from ..typed_executor import area_cells
    area=typed.get('area') or typed.get('zone_spec') or typed.get('zone') or {}
    if not isinstance(area,dict):
        area={}
    if not area.get('size_ft'):
        area={**area,'shape':area.get('shape','cube'),'size_ft':typed.get('size_ft',5)}
    return set(area_cells(engine,actor.position,aim or actor.position,area,include_altitude=True)) <= prison_cells(engine,actor)


@hook('state_event')
def prison_existing_fields(engine,event):
    if event.event_type not in ('CONDITION_APPLIED','ZONE_CREATED'):
        return
    from .. import zones
    for actor in engine.state.actors.values():
        if not imprisoned(actor):
            continue
        for zone in list(engine.state.zones.values()):
            if zone.active and zone.owner_id==actor.entity_id and not set(zones.area_cells(engine,zone)) <= prison_cells(engine,actor):
                zones.remove(engine,zone,'SHIELD_PRISON_BOUNDARY')


def penetrating(action):
    return bool(action and ((action.parameters or {}).get('typed') or {}).get('penetrates_sealed_cultivation_barriers'))


@hook('recipient_allowed')
def prison_recipients(engine,actor,target,action):
    if actor.entity_id!=target.entity_id:
        if imprisoned(actor):
            return False
        if imprisoned(target) and not penetrating(action):
            return False
    return None


@hook('effect_subject_allowed')
def prison_subject(ctx,row,target):
    if ctx.typed.get('warden_prison_repeat') and any(c.source_actor_id==ctx.actor.entity_id for c in imprisoned(target)):
        return None
    return prison_recipients(ctx.engine,ctx.actor,target,ctx.action)


@hook('candidate_allowed')
def prison_actions(engine,actor,candidate,action):
    if not imprisoned(actor):
        return None
    if candidate.destination is not None and candidate.destination not in prison_cells(engine,actor):
        return False
    origin=(candidate.metadata or {}).get('effect_origin')
    if origin:
        from ..gate2_runtime_models import Position
        if Position.model_validate(origin['position']) not in prison_cells(engine,actor):
            return False
    typed=((action.parameters or {}).get('typed') or {}) if action else {}
    if (typed.get('area') or typed.get('zone') or typed.get('zone_spec')) and not contained_field(engine,actor,typed,candidate.destination):
        return False
    return None


@hook('condition_attempt')
def prison_phase(ctx,subject,row):
    if imprisoned(subject) and row.get('condition') in ('incorporeal','phased','possessing'):
        return False
    return None


@hook('zone_subject_allowed')
def prison_zones(engine,zone,target):
    owner=engine.state.actors.get(zone.owner_id)
    action=engine.action_catalog.get(zone.source_definition_id)
    if not penetrating(action) and imprisoned(target) and (owner is None or owner.entity_id!=target.entity_id):
        return False
    if owner and imprisoned(owner):
        from ..zones import area_cells
        if not set(area_cells(engine,zone)) <= prison_cells(engine,owner):
            return False
    return None


@hook('teleport_context_check')
def prison_teleport(engine,actor,start,destination,movement_context):
    if movement_context=='WILLING' and (imprisoned(actor) or any(c.condition_id==SLOWED for c in actor.conditions.values())):
        return False
    return None


def sheltered(engine,target):
    from . import placed
    for zone in placed.of(engine,TAG):
        data=placed.data(zone)
        if data.get('mode')!='shelter' or target.entity_id not in data.get('chosen',[]):
            continue
        # Cylinder height extends upwards from its chosen ground point.
        if engine.grid.distance_ft(target.position.model_copy(update={'z':zone.center.z}),zone.center)<=40 and 0<=(target.position.z-zone.center.z)*5<=40:
            yield zone


@hook('ac')
def shelter_ac(engine,target):
    return 3 if any(sheltered(engine,target)) else None


@hook('save')
def shelter_save(ctx,target,ability,named):
    if set(named or ()) & {'prone','grappled','restrained','forced_movement','unwilling_teleportation'} and any(sheltered(ctx.engine,target)):
        return {'modes':['ADVANTAGE']}
    return None


@hook('damage_defenses')
def shelter_resist(engine,target,kind,typed,source_actor_id):
    if not any(sheltered(engine,target)):
        return None
    from .damage_delivery import frame
    delivery=frame(engine)
    ranged=any(e.get('type')=='attack' and 'ranged' in str(e.get('attack_kind')) for e in typed.get('effects') or [])
    if typed.get('area') or delivery.get('area') or ranged:
        return [{'kind':'resistance','damage_types':['ALL']}]
    return None


@hook('turn_start')
def shelter_step(engine,target):
    if any(sheltered(engine,target)):
        from .rider_choices import step
        step(engine,target,'warden.shelter_step','Sheltered Heaven: move up to 10 feet without Opportunity Attacks',target,10,NINE,
             ignored_oa=list(engine.state.actors))


@hook('would_drop')
def intercession(engine,target,pending,source_actor_id):
    from . import placed
    from .rider_choices import step
    from .damage_allocation import available_temporary_hp
    for zone in sheltered(engine,target):
        data=placed.data(zone)
        if target.entity_id in data.get('benefited',[]) or data.get('last_intercession_round')==engine.state.round_number:
            continue
        temp=available_temporary_hp(engine,target,pending,source_actor_id)
        # The replacement excludes a packet that kills outright by massive damage.
        if pending-temp-target.current_hp>=target.maximum_hp:
            continue
        owner=engine.state.actors[zone.owner_id]
        manifests=formation_manifestations(engine,zone)
        if not manifests:
            continue
        picked=choose(engine,owner,'intercession.shield',[r['id'] for r in manifests],optional=False,
            labels={r['id']:'Shield '+str(i+1)+' — disappears until your next turn' for i,r in enumerate(manifests)})
        broken=next(r for r in manifests if r['id']==picked[0])
        if broken.get('object_id'):
            update(engine,engine.state.objects[broken['object_id']],NINE,cracked_until_turn=owner.turns_started+1)
        placed.update(engine,zone,benefited=[*data.get('benefited',[]),target.entity_id],
            last_intercession_round=engine.state.round_number,cracked_id=broken['id'],cracked_until_turn=owner.turns_started+1)
        note(engine,NINE,owner,f'Heavenly Intercession keeps {target.display_name} at 1 Hit Point. One Shield cracks until your next turn.',[target])
        # Native movement choice is constrained to legal spaces inside the field.
        from .granted_movement import choices,move
        from .needle import cell_id
        from .rider_choices import intent_for
        paths={cell_id(p.destination):p for p in choices(engine,target,15)
               if engine.grid.distance_ft(p.destination,zone.center)<=40 and 0<=(p.destination.z-zone.center.z)*5<=40}
        picked=choose(engine,owner,'intercession.move',list(paths),subject=target) if paths else []
        if picked: move(engine,target,paths[picked[0]],intent_for(engine),15,list(engine.state.actors),name='Heavenly Intercession')
        return max(0,target.current_hp+temp-1)
    return pending


@hook('effect_origins')
def nine_origins(engine,actor,action):
    zone=active_formation(engine,actor)
    if zone is None:
        return None
    typed=(action.parameters or {}).get('typed') or {}
    if str(typed.get('sphere') or '').rsplit('.',1)[-1] not in ('shield','protection','force','formations','formation'):
        return None
    return [{'id':r['id'],'label':f'Ninefold Command: manifestation {i+1}',
             'position':r['position']} for i,r in enumerate(formation_manifestations(engine,zone))]


def formation_manifestations(engine,zone):
    from . import placed
    data=placed.data(zone)
    owner=engine.state.actors.get(zone.owner_id)
    if owner is None:
        return []
    out=[]
    for row in data.get('manifestations',[]):
        if row['id']==data.get('cracked_id') and owner.turns_started<int(data.get('cracked_until_turn') or 0):
            continue
        if row.get('object_id'):
            obj=engine.state.objects.get(row['object_id'])
            if obj is None or obj.destroyed or obj.suppressed:
                continue
            row={**row,'position':obj.position.model_dump(mode='json')}
        out.append(row)
    return out


@hook('state_event')
def prison_anchor_state(engine,event):
    if event.event_type!='OBJECT_UPDATED':
        return
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if c.condition_id!=PRISON or not c.data.get('anchor_id'):
                continue
            obj=engine.state.objects.get(c.data['anchor_id'])
            suspended=int(obj is not None and bool(obj.suppressed))
            if suspended!=int(c.data.get('suspended') or 0):
                engine._update_condition_data(target,c,{**c.data,'suspended':suspended,
                    'rule':{} if suspended else {'speed_zero':True}},c.source_definition_id)


@hook('state_event')
def prison_concentration(engine,event):
    if event.event_type!='CONCENTRATION_ENDED':
        return
    from .condition_ownership import remove_instance
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if c.condition_id==PRISON and c.source_actor_id==event.actor_id and c.source_definition_id==event.source_definition_id:
                remove_instance(engine,target,c.instance_id,c.source_definition_id)



def remember_deflection(engine,attacker,target,spec,protected,ac,before,total):
    if not is_ranged_strike(engine,spec) or total<before:
        return
    from .attack_scope import current
    scope=current(engine)
    ids=[owner.entity_id for owner,_ in protected if profile(engine,owner,DEFLECT)]
    spec['warden_deflection_owners']=list(dict.fromkeys([*spec.get('warden_deflection_owners',[]),*ids]))
    if scope is not None and scope['context'].typed.get('source')!=DEFLECT:
        scope['context'].damage_cache['warden_deflect:'+target.entity_id]=ids


@hook('after_miss_choice')
def deflect_projectile(ctx,target,spec):
    if target is None or ctx.typed.get('source')==DEFLECT or not is_ranged_strike(ctx.engine,spec):
        return
    from ..typed_executor import Context,run_effects
    from ..target_knowledge import can_see
    from ..action_geometry import activate
    from ..targeting import line_of_effect
    from .rider_choices import intent_for
    engine=ctx.engine
    causes=deflection_causes(ctx,target,spec)
    for oid in causes:
        owner=engine.state.actors.get(oid)
        if owner is None or not profile(engine,owner,DEFLECT) or owner.turn_flags.get('_round_warden_deflect')==engine.state.round_number:
            continue
        cost=0 if active_formation(engine,owner) else 2
        if owner.resources.get(QI,0)<cost:
            continue
        action=next((a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id and a.parameters.get('warden')=='deflect'),None)
        if action is None:
            raise ValueError('The acquired Deflect the Projectile attack declaration is unavailable.')
        from ..senses import object_perceives
        origins=[o for o in shields(engine,owner) if o.component[TAG].get('protected')==target.entity_id]
        options={}
        for obj in origins:
            with activate(engine,owner,action.source_definition_id,shield_origin(obj)):
                for other in engine.state.actors.values():
                    if other.active and engine.grid.distance_ft(obj.position,other.position)<=60 and object_perceives(engine,obj,other) and line_of_effect(engine,owner,target=other):
                        options[obj.object_id+'|'+other.entity_id]=(obj,other)
        picked=choose(engine,owner,'deflect.target',list(options),subject=target,
            labels={k:f"Deflect the Projectile: new Force attack at {a.display_name}, {cost} Qi, once per round" for k,(_,a) in options.items()}) if options else []
        if not picked:
            continue
        obj,victim=options[picked[0]]
        action=next((a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id and a.parameters.get('warden')=='deflect'),None)
        if action is None:
            raise ValueError('The acquired Deflect the Projectile attack declaration is unavailable.')
        with paid_response(engine,owner,victim,DEFLECT,cost,reaction=False,action=action,range_origin=shield_origin(obj)) as child:
            if child is None:
                continue
            owner.turn_flags['_round_warden_deflect']=engine.state.round_number
            with activate(engine,owner,child.source,shield_origin(obj)):
                run_effects(child,child.typed['effects'])
            child.damage_cache['warden_response_resolved']=1


LAYERS='condition:typed.constellation_layers'


def layer_grants(engine,target):
    return [c for c in target.conditions.values() if c.condition_id==LAYERS and int(c.data.get('remaining') or 0)>0
            and (owner:=engine.state.actors.get(c.source_actor_id)) is not None and profile(engine,owner,CONSTELLATION)
            and sum(o.component[TAG].get('protected')==target.entity_id for o in shields(engine,owner))>1]


def refresh_layers(engine,owner,*,refill=False):
    if not profile(engine,owner,CONSTELLATION):
        return
    from .condition_ownership import remove_instance
    for target in engine.state.actors.values():
        old=next((c for c in target.conditions.values() if c.condition_id==LAYERS and c.source_actor_id==owner.entity_id),None)
        count=sum(o.component[TAG].get('protected')==target.entity_id for o in shields(engine,owner))
        capacity=min(2,max(0,count-1))
        other=sum(max(0,int(c.data.get('remaining') or 0)) for c in target.conditions.values()
                  if c.condition_id==LAYERS and c.source_actor_id!=owner.entity_id)
        prior=int(old.data.get('remaining') or 0) if old else 0
        old_capacity=int(old.data.get('capacity') or 0) if old else 0
        remaining=min(capacity,2-other,capacity if refill else prior+max(0,capacity-old_capacity))
        if old:
            remove_instance(engine,target,old.instance_id,CONSTELLATION)
        if capacity:
            engine._apply_condition(target,LAYERS,CONSTELLATION,owner.entity_id,expires_on='START_OF_SOURCE_NEXT_TURN',
                data={'remaining':max(0,remaining),'capacity':capacity,'pb':int(owner.proficiency_bonus),'source_cl':int(numbers(engine,owner)['cl']),
                    'label':f'Constellation: {max(0,remaining)} Layers; spend to reduce damage or forced movement, resist a hold, or stop a lower-level disarm'})


def spend_layer(engine,target,kind,*,source_cl=None):
    from .condition_ownership import remove_instance
    for c in layer_grants(engine,target):
        if source_cl is not None and int(c.data['source_cl'])<=source_cl:
            continue
        owner=engine.state.actors[c.source_actor_id]
        picked=choose(engine,owner,'layer.'+kind+'.'+str(engine.state.event_sequence),['use'],subject=target,
            labels={'use':{'damage':f'Reduce this damage packet by {c.data["pb"]}',
                'movement':'Reduce this forced movement by 10 feet','save':'Advantage on this Prone, Grappled or Restrained save',
                'disarm':'Prevent this lower-level Disarm attempt'}[kind]})
        if not picked:
            continue
        n=int(c.data['remaining'])-1
        remove_instance(engine,target,c.instance_id,CONSTELLATION)
        engine._apply_condition(target,LAYERS,c.source_definition_id,c.source_actor_id,expires_on=c.expires_on,
            data={**c.data,'remaining':n})
        return int(c.data['pb'])
    return 0


@hook('damage_response_reduction')
def layer_damage(engine,target,amount,kind,source,source_actor_id):
    reduced=0
    for _ in range(2):
        if amount<=reduced:break
        used=spend_layer(engine,target,'damage')
        if not used:break
        reduced+=used
    return reduced or None


@hook('forced_movement_reduction')
def layer_movement(ctx,target):
    reduced=0
    for _ in range(2):
        if not spend_layer(ctx.engine,target,'movement'):break
        reduced+=10
    return reduced or None


@hook('save')
def layer_save(ctx,target,ability,named):
    if {'prone','grappled','restrained'} & set(named or ()) and spend_layer(ctx.engine,target,'save'):
        return {'modes':['ADVANTAGE']}
    return None


BULWARK_HELD='condition:typed.warden_bulwark'


def activation_key(engine,source):
    from ..paid_relocation import current_activation
    from .damage_delivery import frame
    delivery=frame(engine)
    if delivery['event'] and delivery['identity']==source:
        return 'delivery:'+delivery['event']+':'+str(source)
    activation=current_activation(engine)
    return activation.activation_id+':'+str(source) if activation is not None else ''


def bulwark_for(engine,target,source):
    key=activation_key(engine,source)
    return [c for c in target.conditions.values() if c.condition_id==BULWARK_HELD and c.data.get('activation')==key]


def close_bulwark(ctx,effect):
    from ..typed_reactions import can_react,spend_reaction
    from ..activation_payments import reaction_completed
    from ..relations import relation,ENEMY,ALLY
    engine=ctx.engine
    multi=bool(ctx.typed.get('area')) or len(ctx.targets)>1
    if not multi or effect.get('type') not in ('attack','save','damage'):
        return
    key=activation_key(engine,ctx.source)
    if not key:
        return
    if ctx.damage_cache.get('warden_bulwark_checked:'+key):
        return
    ctx.damage_cache['warden_bulwark_checked:'+key]=1
    affected=[a for a in ([ctx.target] if ctx.target else ctx.targets) if a is not None]
    for owner in engine.state.actors.values():
        objs=shields(engine,owner)
        if not profile(engine,owner,BULWARK) or not objs or relation(engine,owner,ctx.actor)!=ENEMY:
            continue
        cost=2 if active_formation(engine,owner) else 4
        if owner.turn_flags.get('_round_warden_bulwark')==engine.state.round_number or not can_react(engine,owner) or owner.resources.get(QI,0)<cost:
            continue
        if not any(relation(engine,owner,a)==ALLY and any(engine.grid.distance_ft(o.position,a.position)<=30 for o in objs) for a in affected):
            continue
        targets=[a for a in engine.state.actors.values() if a.active and any(engine.grid.distance_ft(o.position,a.position)<=30 for o in objs)
                 and any(locations(engine,owner,o.position,120,near=a) for o in objs)]
        picked=choose(engine,owner,'bulwark.targets.'+key,[a.entity_id for a in targets],maximum=min(int(owner.proficiency_bonus),len(targets)),
            labels={a.entity_id:a.display_name for a in targets},
            preferred=[a.entity_id for a in targets if relation(engine,owner,a)==ALLY],
            prompt=f'Close the Bulwark: Reaction, {cost} Qi, once per round. Choose up to {owner.proficiency_bonus} creatures within 30 feet of a Shield. They gain your Proficiency Bonus to this save, Resistance, and reduced forced movement; attacks instead have Disadvantage and one hit is resisted.') if targets else []
        if not picked:
            continue
        with paid_response(engine,owner,affected[0] if affected else owner,BULWARK,cost) as paid:
            if paid is None:
                continue
            owner.turn_flags['_round_warden_bulwark']=engine.state.round_number
            moved=[]
            for obj in objs:
                cells={c for tid in picked for c in locations(engine,owner,obj.position,120,near=engine.state.actors[tid])}
                point=point_choice(engine,owner,'bulwark.move.'+obj.object_id,list(cells),optional=True)
                if point is not None:
                    obj=obj.model_copy(update={'position':point})
                    engine._update_object(obj,BULWARK,owner.entity_id)
                    moved.append(obj)
            for tid in picked:
                engine._apply_condition(engine.state.actors[tid],BULWARK_HELD,BULWARK,owner.entity_id,expires_on='END_OF_CURRENT_TURN',
                    data={'activation':key,'source':ctx.source,'pb':int(owner.proficiency_bonus),'hit_used':0,
                          'label':'Close the Bulwark: protection against the triggering effect only'})
            paid.damage_cache['warden_response_resolved']=1
            # Shield-Step Escort follows any Ward moved by Close the Bulwark.
            if profile(engine,owner,DEFLECT):
                for obj in moved:
                    escort_step(engine,owner,obj,'bulwark.escort.'+obj.object_id)


@hook('effect_resolution_scope')
def bulwark_scope(ctx,row):
    if not any(profile(ctx.engine,a,BULWARK) for a in ctx.engine.state.actors.values()):
        return None
    from contextlib import contextmanager
    @contextmanager
    def scoped():
        close_bulwark(ctx,row)
        yield
    return scoped()


@hook('save')
def bulwark_save(ctx,target,ability,named):
    held=bulwark_for(ctx.engine,target,ctx.source)
    return {'bonus':max(int(c.data['pb']) for c in held)} if held else None


@hook('attack_mode')
def bulwark_attack(ctx,target):
    return 'DISADVANTAGE' if bulwark_for(ctx.engine,target,ctx.source) else None


@hook('damage_defenses')
def bulwark_resistance(engine,target,kind,typed,source_actor_id):
    from .damage_delivery import identity
    held=bulwark_for(engine,target,identity(engine))
    attack=engine.damage_context()
    if any(not c.data.get('hit_used') or attack is not None and c.data.get('hit_roll_id')==attack.roll_id for c in held):
        return [{'kind':'resistance','damage_types':['ALL']}]
    return None


@hook('save_final')
def bulwark_saved(ctx,target,ability,named,failed):
    if bulwark_for(ctx.engine,target,ctx.source):
        ctx.damage_cache['warden_bulwark_save:'+target.entity_id]='failed' if failed else 'success'


@hook('forced_movement_reduction')
def bulwark_displacement(ctx,target):
    result=ctx.damage_cache.get('warden_bulwark_save:'+target.entity_id)
    distance=int(getattr(ctx,'forced_movement_distance_ft',0) or 0)
    return distance if result=='success' else (distance+1)//2 if result=='failed' else None


@hook('final_damage')
def bulwark_hit_consumed(engine,target,amount,kind,source,source_actor_id,intent):
    # Bind the first actual packet to its native hit. Every later component of
    # that same roll retains Resistance; a different hit cannot borrow it.
    attack=engine.damage_context()
    if attack is None or attack.target_id!=target.entity_id:
        return None
    for c in bulwark_for(engine,target,source):
        if not c.data.get('hit_used'):
            engine._update_condition_data(target,c,{**c.data,'hit_used':1,'hit_roll_id':attack.roll_id},BULWARK)
    return None


TRAPPED='condition:typed.warden_caught_manifestation'


def catch_weapon(engine,target,amount,kind,source,source_actor_id,intent):
    if amount!=0:
        return None
    held=bulwark_for(engine,target,source)
    attacker=engine.state.actors.get(source_actor_id)
    action=engine.action_catalog.get(source)
    if not held or attacker is None or action is None:
        return None
    typed=(action.parameters or {}).get('typed') or {}
    attacks=[e for e in typed.get('effects') or [] if e.get('type')=='attack']
    # A discrete, native one-roll ranged declaration is the manifestation;
    # a damage name or display-name substring never creates that provenance.
    if typed.get('area') or len(attacks)!=1 or any(int(e.get('count') or 1)!=1 for e in attacks) or not any(
            'ranged' in str(e.get('attack_kind')) or typed.get('range_ft') for e in attacks):
        return None
    from .passive_rows import known_level
    from .ability_source import cultivation_check
    from ..weapon_delivery import weapon_identity
    from .effect_durations import token
    incoming=delivery_profile(engine,action,attacker.entity_id)
    level=incoming.get('source_cl')
    if level is None:
        return None
    for c in held:
        owner=engine.state.actors[c.source_actor_id]
        key=activation_key(engine,source)
        if owner.turn_flags.get('warden_catch:'+key):
            continue
        own_level=int(numbers(engine,owner)['cl'])
        physical=weapon_identity(engine,source,typed,action.parameters,owner_id=source_actor_id) if typed.get('weapon') and not typed.get('ammunition') else ''
        options=['restrain' if physical else 'disperse'] if level<own_level else ['trap'] if level==own_level else ['check']
        picked=choose(engine,owner,'catch.'+key,options,subject=target,labels={
            'restrain':'Restrain the permanent weapon; it remains its owner’s property',
            'disperse':'Disperse this lower-level projected manifestation',
            'trap':'Trap this equal-level manifestation until your next turn starts',
            'check':'Make a Cultivation Check against the higher-level effect’s save DC to trap it'})
        if not picked:
            continue
        owner.turn_flags['warden_catch:'+key]=1
        if picked==['check']:
            dc=incoming.get('save_dc')
            if not isinstance(dc,int) or not cultivation_check(engine,owner,numbers(engine,owner),dc,BULWARK,'Catch the Heaven-Sent Weapon',[]):
                continue
        expires=token('start',owner.entity_id,owner.turns_started+1)
        # A permanent object is restrained rather than destroyed; no inventory
        # transfer, copy or loot record is created. Dispersal blocks the current
        # manifestation only, never the source's ability to create another later.
        engine._apply_condition(attacker,TRAPPED,BULWARK,owner.entity_id,expires_on=expires,
            data={'activation':key,'source':source,'disables_action':physical or '',
                  'label':'Heaven-Sent manifestation caught: no damage or riders; permanent items remain owned; harmless release at the Warden’s next turn start'})
    return None


@hook('effect_allowed')
def caught_riders(ctx,row):
    if any(c.condition_id==TRAPPED and c.data.get('activation')==activation_key(ctx.engine,ctx.source)
           for c in ctx.actor.conditions.values()):
        return False
    return None


@hook('candidate_allowed')
def restrained_weapon(engine,actor,candidate,action):
    if action is None:
        return None
    from ..weapon_delivery import weapon_identity
    typed=(action.parameters or {}).get('typed') or {}
    identity=weapon_identity(engine,action.source_definition_id,typed,action.parameters,owner_id=actor.entity_id)
    if identity and any(c.condition_id==TRAPPED and c.data.get('disables_action')==identity for c in actor.conditions.values()):
        return False
    return None


@hook('cover')
def shelter_cover(engine,attacker,target):
    for zone in sheltered(engine,target):
        if engine.grid.distance_ft(attacker.position.model_copy(update={'z':zone.center.z}),zone.center)>40 or not 0<=(attacker.position.z-zone.center.z)*5<=40:
            return 2
    return None


@hook('resource_gain_allowed')
def prison_recovery(engine,actor,resource_id,amount,source_id):
    if amount>0 and resource_id.startswith('resource:core.') and resource_id in (
            'resource:core.qi','resource:core.stamina','resource:core.resonance') and any(c.data.get('lower_by_six') for c in imprisoned(actor)):
        return False
    return None


@hook('cost_available')
def prison_activation_cost(engine,actor,resource_id,amount,context):
    if amount>2 and resource_id in ('resource:core.qi','resource:core.stamina','resource:core.resonance') and any(c.data.get('lower_by_six') for c in imprisoned(actor)):
        return False
    return None


@hook('effect_allowed')
def prison_field(ctx,row):
    if not imprisoned(ctx.actor):
        return None
    if row.get('type') in ('teleport','change_plane'):
        return False
    if row.get('type') in ('zone','area','create_zone','field') and not contained_field(
            ctx.engine,ctx.actor,{**ctx.typed,**row},ctx.destination):
        return False
    return None



def inside_shelter(engine,zone,point):
    flat=point.model_copy(update={'z':zone.center.z})
    return engine.grid.distance_ft(flat,zone.center)<=40 and 0<=(point.z-zone.center.z)*5<=40


@hook('effect_subject_allowed')
def shelter_boundary(ctx,row,target):
    from . import placed
    from .passive_rows import known_level
    from .ability_source import cultivation_check
    from ..action_geometry import point
    from ..gate2_runtime_models import Position
    from ..relations import relation,ENEMY
    typed=ctx.typed
    ranged=(row.get('type')=='attack' and ('ranged' in str(row.get('attack_kind')) or typed.get('range_ft')))
    area=typed.get('area') or {}
    remote=point(ctx.engine,ctx.actor)!=ctx.actor.position
    if not (ranged or area.get('shape') in ('line','cone') or remote):
        return None
    incoming=delivery_profile(ctx.engine,ctx.action,ctx.actor.entity_id)
    level=incoming.get('source_cl')
    if level is None:
        return None  # Unknown native source authority remains unknown.
    for zone in placed.of(ctx.engine,TAG):
        data=placed.data(zone)
        if data.get('mode')!='shelter':
            continue
        owner=ctx.engine.state.actors[zone.owner_id]
        if relation(ctx.engine,owner,ctx.actor)!=ENEMY:
            continue
        origin=point(ctx.engine,ctx.actor)
        path=[Position(x=x,y=y,z=z) for x,y,z in ctx.engine.grid.effect_ray_cells(origin,target.position)]
        membership=[inside_shelter(ctx.engine,zone,p) for p in path]
        if not membership or len(set(membership))<2:
            continue
        key='warden_boundary:'+zone.zone_id+':'+activation_key(ctx.engine,ctx.source)
        if key not in ctx.damage_cache:
            own_level=int(data['source_cl'])
            if level<own_level:
                picked=choose(ctx.engine,owner,'boundary.permit.'+key,['permit'],subject=target,
                    labels={'permit':'Permit this lower-level hostile effect to cross Sheltered Heaven'})
                ctx.damage_cache[key]=bool(picked)
            elif level==own_level:
                ctx.damage_cache[key]=cultivation_check(ctx.engine,ctx.actor,typed.get('numbers') or {},int(data['save_dc']),ctx.source,'Cross Sheltered Heaven',[])
            else:
                picked=choose(ctx.engine,owner,'boundary.check.'+key,['check'],subject=target,
                    labels={'check':'Try a Cultivation Check against this higher-level effect’s save DC to stop it'})
                dc=incoming.get('save_dc')
                ctx.damage_cache[key]=not(picked and isinstance(dc,int) and cultivation_check(ctx.engine,owner,numbers(ctx.engine,owner),dc,NINE,'Sheltered Heaven boundary',[]))
        if not ctx.damage_cache[key]:
            return False
    return None


@hook('condition_attempt')
def layer_disarm(ctx,subject,row):
    if row.get('condition')!='disarmed':
        return None
    from .passive_rows import known_level
    source_cl=known_level(ctx.engine,ctx.actor)
    if source_cl is None:
        return None
    if any(int(c.data['source_cl'])>source_cl for c in layer_grants(ctx.engine,subject)) and spend_layer(ctx.engine,subject,'disarm',source_cl=source_cl):
        return False
    return None



LINK_ORIGIN='warden.link:'


@hook('effect_origins')
def linked_shield_origins(engine,actor,action):
    constellation=profile(engine,actor,CONSTELLATION)
    row=constellation or profile(engine,actor)
    if not row or not row.get('armament_link') or action.target_kind=='SELF':
        return None
    typed=(action.parameters or {}).get('typed') or {}
    source=typed.get('source') or ''
    if not (typed.get('sphere') or source.startswith(('tianxia.path.qi_cultivation.','tianxia.subpath.qi.'))):
        return None
    if (action.parameters.get('warden') or typed.get('weapon') or typed.get('consumes_physical_object')
            or typed.get('body_centered_aura') or typed.get('remote_origin_forbidden')):
        return None
    if nine_origins(engine,actor,action):
        return None  # Ninefold Command already supplies these origins without the Link surcharge.
    return [{**shield_origin(obj),'id':LINK_ORIGIN+obj.object_id,
             'label':'Domain Armament Link: Shield origin (+1 Qi)'} for obj in shields(engine,actor)
             if not asset_prisons(engine,obj) and (constellation or not obj.component[TAG].get('projected'))]


@hook('technique_additional_costs')
def shield_link_cost(engine,actor,source,listed):
    from ..action_geometry import record_for
    origin=record_for(engine,actor,source) or {}
    if profile(engine,actor) and str(origin.get('id','')).startswith(LINK_ORIGIN):
        return {QI:1}
    return None


def shield_origin(obj):
    return {'id':obj.object_id,'label':'Orbiting Shield: '+('projected Ward' if obj.component[TAG].get('projected') else 'bound shield'),
            'position':obj.position.model_dump(mode='json')}


@hook('effect_origins')
def shield_attack_origins(engine,actor,action):
    do=(action.parameters or {}).get('warden')
    if str(do).startswith('bound_strike.') and profile(engine,actor):
        return [shield_origin(o) for o in shields(engine,actor) if not o.component[TAG].get('projected') and o.component[TAG]['mode']=='assault']
    if do=='deflect' and profile(engine,actor,DEFLECT):
        return [shield_origin(o) for o in shields(engine,actor) if not asset_prisons(engine,o)]
    if str(do).startswith('strike.') and profile(engine,actor,CONSTELLATION):
        return [shield_origin(o) for o in shields(engine,actor) if o.component[TAG]['mode']=='assault' and not asset_prisons(engine,o)]
    return None



def is_ranged_strike(engine,spec):
    from ..attack_delivery import is_ranged
    typed=spec.get('typed') or {}
    from .attack_scope import current
    scope=current(engine)
    effect=scope['effect'] if scope else {}
    return is_ranged(effect.get('attack_kind') or spec.get('attack_kind'),spec.get('range_ft'),typed.get('weapon'))


JOURNEY_KEY='source:orbiting_shield_warden'


def journey_profile(session,aid,feature=None):
    return next((r for r in session.state['actors'][aid]['bundle'].get('typed_passives',[])
                 if r.get('block')==TAG and (r.get('feature_id')==feature if feature is not None else r.get('feature_id') in (RAISE,CONSTELLATION))),None)


DRAFT='source:orbiting_shield_warden:placement_choice'


def journey_locations(session,aid,start,feet,*,initial=False):
    from ..journey_assets import JourneyAssetContext
    context=JourneyAssetContext(session)
    return locations(context,context.state.actors[aid],start,feet,initial=initial)


def journey_deadline(state):
    from fractions import Fraction
    return Fraction(state['expires_num'],state['expires_den']) if 'expires_num' in state else Fraction(state['expires_at'])


def journey_clock_record(session,state,remaining=None):
    from fractions import Fraction
    left=Fraction(remaining) if remaining is not None else max(Fraction(0),journey_deadline(state)-session.clock())
    deadline=session.clock()+left
    return {**state,'clock_session':session.state['journey_id'],
            'expires_at':deadline.numerator//deadline.denominator,
            'expires_num':deadline.numerator,'expires_den':deadline.denominator,
            'remaining_num':left.numerator,'remaining_den':left.denominator}


@hook('journey_initialize')
def journey_rebase_wards(session,aid):
    from fractions import Fraction
    states=session.state['actors'][aid].get('source_states',{})
    held=states.get(JOURNEY_KEY)
    states.pop(DRAFT,None)
    if held and held.get('clock_session')!=session.state['journey_id']:
        from ..journey import require
        require('remaining_num' in held and 'remaining_den' in held,
                'This source continuation needs its committed remaining Ward lifetime; an absolute prior scene clock cannot be reused.')
        states[JOURNEY_KEY]=journey_clock_record(session,held,Fraction(held['remaining_num'],held['remaining_den']))


@hook('journey_options')
def journey_options(session,aid):
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][aid]
    if actor['incapacitated'] or not journey_profile(session,aid):
        return None
    origin=Position.model_validate(actor['position'])
    current=actor.get('source_states',{}).get(JOURNEY_KEY)
    draft=actor.get('source_states',{}).get(DRAFT)
    def option(identity,kind,payload,label):
        return {'id':identity,'kind':kind,'auto_select':0,'payload':payload,'label':label}
    out=[]
    if draft:
        if draft['mode']=='move':
            index=len(draft['points'])
            start=Position.model_validate(current['shields'][index]['position']) if current and index<len(current['shields']) else None
            points=journey_locations(session,aid,start,30) if start is not None else []
        else:
            points=journey_locations(session,aid,origin,30,initial=True)
        if len(draft['points']) < (len(current['shields']) if draft['mode']=='move' and current else 3):
            out.extend(option('warden:point:'+str(p),'warden_choose_point',{'point':p.model_dump(mode='json')},
                f"Shield {len(draft['points'])+1}: point ({p.x}, {p.y}, {p.z*5} feet high)") for p in points)
        if draft['mode']=='constellation' or current and len(draft['points'])==len(current['shields']):
            out.append(option('warden:confirm','warden_confirm',{},
                'Confirm '+str(len(draft['points']))+' Shields: '+('3 Qi, 8 hours' if draft['mode']=='constellation' else 'move each up to 30 feet, once this six-second turn')))
        out.append(option('warden:cancel','warden_cancel',{},'Cancel these placement choices; spend no Qi'))
        return out
    if journey_profile(session,aid,RAISE) and actor['resources'].get(QI,0)>=1:
        out.extend(option('warden:manifest:'+str(p),'warden_manifest',{'points':[p.model_dump(mode='json')]},
            f'Manifest Ward at ({p.x}, {p.y}, {p.z*5} feet high): 1 Qi, lasts 8 hours')
            for p in journey_locations(session,aid,origin,30,initial=True))
    if journey_profile(session,aid,CONSTELLATION) and actor['resources'].get(QI,0)>=3:
        out.append(option('warden:constellation','warden_begin',{'mode':'constellation'},'Choose up to three projected Shields: 3 Qi on confirmation, lasts 8 hours'))
    if current:
        out.append(option('warden:move','warden_begin',{'mode':'move'},'Choose each Shield’s destination up to 30 feet away; remain within 60 feet'))
        out.append(option('warden:dismiss','warden_dismiss',{},'Dismiss your Orbiting Shields'))
    return out


@hook('journey_command')
def journey_placement_choice(session,aid,kind,payload):
    if kind not in ('warden_begin','warden_choose_point','warden_confirm','warden_cancel'):
        return None
    from ..journey import require
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][aid]
    require(journey_profile(session,aid) and not actor['incapacitated'],'Acquire a live Shield Warden profile before choosing placement.')
    states=actor.setdefault('source_states',{})
    current=states.get(JOURNEY_KEY)
    if kind=='warden_begin':
        require(set(payload)=={'mode'} and payload['mode'] in ('constellation','move'),'Choose Constellation or movement.')
        require(payload['mode']!='constellation' or journey_profile(session,aid,CONSTELLATION),'Acquire Shield Constellation first.')
        require(payload['mode']!='move' or current,'Manifest Shields before moving them.')
        states[DRAFT]={'mode':payload['mode'],'points':[]}
    elif kind=='warden_cancel':
        require(not payload,'Cancellation takes no extra parameters.')
        states.pop(DRAFT,None)
    else:
        draft=states.get(DRAFT)
        require(draft is not None,'Begin a native Shield placement choice first.')
        if kind=='warden_choose_point':
            require(set(payload)=={'point'},'Choose one explicit native point.')
            point=Position.model_validate(payload['point'])
            index=len(draft['points'])
            count=len(current['shields']) if draft['mode']=='move' and current else 3
            require(index<count,'Confirm or cancel the completed choice.')
            start=Position.model_validate(current['shields'][index]['position']) if draft['mode']=='move' else Position.model_validate(actor['position'])
            require(point in journey_locations(session,aid,start,30,initial=draft['mode']!='move'),'Choose a currently legal source point along a native route.')
            draft['points'].append(point.model_dump(mode='json'))
        else:
            require(not payload,'Confirmation takes no extra parameters.')
            journey_command(session,aid,'warden_move' if draft['mode']=='move' else 'warden_constellation',{'points':draft['points']})
            states.pop(DRAFT,None)
    from copy import deepcopy
    session.emit('WARDEN_PLACEMENT_CHOICE',aid,source=CONSTELLATION,choice=deepcopy(states.get(DRAFT,{})))
    return True


@hook('journey_command')
def journey_command(session,aid,kind,payload):
    if kind not in ('warden_manifest','warden_constellation','warden_move','warden_dismiss'):
        return None
    from ..journey import require,integer
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][aid]
    row=journey_profile(session,aid,CONSTELLATION if kind=='warden_constellation' else RAISE if kind=='warden_manifest' else None)
    require(row is not None and not actor['incapacitated'],'This creature cannot use that Orbiting Shield Warden feature.')
    states=actor.setdefault('source_states',{})
    current=states.get(JOURNEY_KEY,{})
    if kind=='warden_dismiss':
        require(not payload,'Dismissal takes no extra parameters.')
        states.pop(JOURNEY_KEY,None)
        session.emit('WARDEN_DISMISSED',aid,source=RAISE)
        return True
    require(set(payload)=={'points'} and isinstance(payload['points'],list),'Choose explicit Shield points on the native map.')
    origin=Position.model_validate(actor['position'])
    points=[]
    for raw in payload['points']:
        require(isinstance(raw,dict) and set(raw)<={'x','y','z'} and {'x','y'}<=set(raw)
                and all(integer(v) for v in raw.values()),'Shield points use whole nonnegative map coordinates.')
        point=Position.model_validate(raw)
        require(session.grid.volume_legal(point),'The Shield must occupy a legal point.')
        points.append(point)
    if kind=='warden_move':
        require(current and len(points)==len(current['shields']),'Choose one destination for each active Shield.')
        for point,old in zip(points,current['shields']):
            require(point in journey_locations(session,aid,Position.model_validate(old['position']),30),
                    'Move each Shield along a legal native route of at most 30 feet and remain within 60 feet.')
            old['position']=point.model_dump(mode='json')
        # Outside initiative the actual elapsed six-second turn pays the native
        # once-per-turn movement boundary; elapsed time also expires the Ward.
        session.tick(6)
    else:
        limit=3 if kind=='warden_constellation' else 1
        require((0 if kind=='warden_constellation' else 1)<=len(points)<=limit,'Choose a legal number of projected Shields.')
        legal=journey_locations(session,aid,origin,30,initial=True)
        require(all(p in legal for p in points),
                'Manifest into unoccupied points within 30 feet.')
        session.spend_resource(aid,QI,3 if kind=='warden_constellation' else 1,row['feature_id'])
        n=row['numbers']
        current={'expires_at':int(session.clock())+28800,'shields':[{
            'identity':f"ward:{aid}:{len(session.state['events'])}:{i}",
            'position':point.model_dump(mode='json'),'hp':3*int(n['cl']),'max_hp':3*int(n['cl']),
            'ac':14+int(n['pb']),'mode':'guard','source_cl':int(n['cl'])} for i,point in enumerate(points)]}
        current=journey_clock_record(session,current,28800)
        states[JOURNEY_KEY]=current
    from copy import deepcopy
    session.emit('WARDEN_STATE_COMMITTED',aid,source=row['feature_id'],state=deepcopy(current))
    return True


@hook('journey_elapsed')
def journey_expire(session,aid,previous,seconds,moving):
    actor=session.state['actors'][aid]
    current=actor.get('source_states',{}).get(JOURNEY_KEY)
    if current and session.clock()>=journey_deadline(current):
        del actor['source_states'][JOURNEY_KEY]
        session.emit('WARDEN_EXPIRED',aid,source=RAISE)
    elif current:
        actor['source_states'][JOURNEY_KEY]=journey_clock_record(session,current)


@hook('journey_state_changed')
def journey_incapacitated(session,aid):
    actor=session.state['actors'][aid]
    if actor['incapacitated'] and actor.get('source_states',{}).pop(JOURNEY_KEY,None):
        session.emit('WARDEN_ENDED_UNCONSCIOUS',aid,source=RAISE)


@hook('journey_combat_bundle')
def journey_bundle(bundle,session,aid):
    from copy import deepcopy
    state=session.state['actors'][aid].get('source_states',{}).get(JOURNEY_KEY)
    bond=session.state['actors'][aid].get('source_states',{}).get(BOND)
    if not journey_profile(session,aid):
        return bundle
    result=deepcopy(bundle)
    if bond:
        result.setdefault('journey_setup',{})['warden_bond']=deepcopy(bond)
    if state and session.clock()<journey_deadline(state):
        result['journey_setup']={**result.get('journey_setup',{}),'warden':deepcopy(state),
                                 'warden_remaining_seconds':max(0,(journey_deadline(state)-session.clock()).__ceil__())}
    return result


def journey_identity(owner,setup,row,i):
    # A real item keeps the identity used by release and Bound Shield selection.
    if row.get('real') and setup.get('warden_bond'):
        from .scoundrel_riders import object_id
        bond=setup['warden_bond']
        return object_id(bond['inventory_owner'],bond['item_key'])
    return f"object:warden.journey.{owner.entity_id}.{i}"


def restore_object(engine,owner,setup,row,oid):
    from ..gate2_runtime_models import RuntimeObjectState,Position
    if row.get('real') and setup.get('warden_bond'):
        bond=setup['warden_bond']; stat=bond['profile']
        engine._update_object(RuntimeObjectState(object_id=oid,object_kind='BOUND_SHIELD',owner_id=owner.entity_id,
            position=Position.model_validate(row['position']),unattended=False,flammable=False,ac=int(stat['ac']),
            current_hp=int(row['hp']),maximum_hp=int(stat['hp']),damage_threshold=stat['threshold'],
            damage_immunities=tuple(stat['immune']),
            component={'name':shield_name(bond['item']),'size':'small','kind':'shield','item':True,
                'cultivation_implement':True,'blocks':False,'resist':stat['resist'],'artifact':stat['artifact'],
                'source_cl':stat['source_cl'],'created_by':RAISE,'bound_item':dict(bond['item']),
                TAG:{'owner':owner.entity_id,'source_cl':stat['source_cl'],'mode':row['mode'],'projected':0,
                    'protected':'','protected_until':0,'location':'floating'}}),RAISE,owner.entity_id)
        return
    engine._update_object(RuntimeObjectState(object_id=oid,object_kind='QI_CONSTRUCT',owner_id=owner.entity_id,
        position=Position.model_validate(row['position']),unattended=True,flammable=False,ac=int(row['ac']),
        current_hp=int(row['hp']),maximum_hp=int(row['max_hp']),damage_immunities=('POISON','PSYCHIC'),
        component={'name':'Orbiting Ward','size':'small','blocks':False,'kind':'cultivation_implement',
            'resist':['BLUDGEONING','PIERCING','SLASHING'],'source_cl':int(row['source_cl']),'created_by':RAISE,TAG:{'owner':owner.entity_id,'source_cl':int(row['source_cl']),
                'mode':row['mode'],'projected':1,'protected':'','protected_until':0}}),RAISE,owner.entity_id)


@hook('match_initialize')
def journey_restore(engine):
    from ..gate2_runtime_models import RuntimeObjectState,Position
    from .effect_durations import round_token
    initialized=False
    for bundle in engine.typed_bundle_documents:
        setup=bundle.get('journey_setup') or {}
        state=setup.get('warden')
        owner=engine.state.actors.get(bundle['actor_id'])
        if owner is not None and profile(engine,owner) and setup.get('warden_bond'):
            engine._apply_condition(owner,BOUND,RAISE,owner.entity_id,expires_on='UNTIL_REMOVED',data={**setup['warden_bond'],
                'label':'Bound Shield — actual item; the bond lasts until ended or the item is destroyed'})
            initialized=True
        if not state or owner is None or not profile(engine,owner) or int(setup.get('warden_remaining_seconds') or 0)<=0:
            continue
        for i,row in enumerate(state['shields']):
            oid=journey_identity(owner,setup,row,i)
            engine._apply_condition(owner,WARD,RAISE,owner.entity_id,
                expires_on=round_token(engine,(int(setup['warden_remaining_seconds'])+5)//6),
                data={'object_id':oid,'label':'Orbiting Ward — remaining elapsed duration from the journey'})
            restore_object(engine,owner,setup,row,oid)
        initialized=True
    return True if initialized else None


@hook('journey_snapshot_actor')
def journey_snapshot(actor,session,aid,engine):
    if not profile(engine,actor):
        return actor
    # These exact construct clocks move to the source continuation record.
    # Other timed effects remain subject to the ordinary continuation checks.
    result=actor.model_copy(deep=True)
    result.conditions={iid:c for iid,c in result.conditions.items() if c.condition_id!=WARD}
    return result


def journey_row(obj):
    tag=obj.component[TAG]
    return {'identity':obj.object_id,'position':obj.position.model_dump(mode='json'),'hp':int(obj.current_hp),'max_hp':int(obj.maximum_hp),
        'ac':int(obj.ac),'mode':tag['mode'],'source_cl':int(tag['source_cl']),'real':0 if tag.get('projected') else 1}


@hook('journey_encounter_settled')
def journey_export(session,aid,engine,actor):
    if not profile(engine,actor):
        return
    from .effect_durations import parse_round
    states=session.state['actors'][aid].setdefault('source_states',{})
    active=shields(engine,actor,inactive=True)
    if not active:
        states.pop(JOURNEY_KEY,None)
        return
    slots=max(1,len(engine.state.initiative_order))
    remaining=[]
    for control in controls(actor):
        parsed=parse_round(control.expires_on)
        if parsed:
            rounds,slot=parsed
            ticks=(rounds-engine.state.round_number)*slots+slot-engine.state.current_slot_index
            remaining.append(max(0,(ticks*6+slots-1)//slots))
    if not remaining or min(remaining)<=0:
        states.pop(JOURNEY_KEY,None)
        return
    states[JOURNEY_KEY]=journey_clock_record(session,{'shields':[journey_row(o) for o in active]},min(remaining))
    from copy import deepcopy
    session.emit('WARDEN_ENCOUNTER_CONTINUED',aid,source=RAISE,state=deepcopy(states[JOURNEY_KEY]))



@hook('final_damage')
def record_catch_packet(engine,target,amount,kind,source,source_actor_id,intent):
    if not bulwark_for(engine,target,source):
        return None
    from .attack_scope import current
    scope=current(engine)
    if scope is not None and scope['target_id']==target.entity_id and scope['source']==source:
        cache=scope['context'].damage_cache
        key='warden_catch_packet:'+target.entity_id
        cache[key]=int(cache.get(key) or 0)+int(amount)
        cache['warden_catch_seen:'+target.entity_id]=1
    return None


@hook('damage_defended')
def catch_resistance_applied(engine,target,kind,source,source_actor_id,defenses):
    if not defenses.get('resist') or not bulwark_for(engine,target,source):
        return
    from .attack_scope import current
    scope=current(engine)
    if scope is not None and scope['target_id']==target.entity_id and scope['source']==source:
        scope['context'].damage_cache['warden_catch_resisted:'+target.entity_id]=1


@hook('attack_resolved')
def catch_complete_hit(ctx,target,hit,effect):
    if not hit:
        return
    key=target.entity_id
    if ctx.damage_cache.get('warden_catch_seen:'+key) and ctx.damage_cache.get('warden_catch_resisted:'+key) and ctx.damage_cache.get('warden_catch_packet:'+key)==0:
        catch_weapon(ctx.engine,target,0,'',ctx.source,ctx.actor.entity_id,ctx.intent)


@hook('object_damage_defenses')
def prison_anchor_resistance(engine, attacker, obj, packets, source):
    """Resist every native damage kind except the printed three exceptions."""
    from .bound_objects import bound
    record=bound(obj)
    if not record:
        return None
    owner=engine.state.actors.get(record.get('owner'))
    action=engine.action_catalog.get(record.get('source'))
    if owner is None or not profile(engine,owner,NINE) or action is None or action.parameters.get('warden')!='prison':
        return None
    holder=engine.state.actors.get(record.get('holder'))
    actor_prison=holder is not None and any(i in holder.conditions and holder.conditions[i].condition_id==PRISON for i in record.get('conditions',[]))
    asset_prison=any(placed_data(engine.state.zones[z]).get('target_object') for z in record.get('zones',[]) if z in engine.state.zones)
    if not actor_prison and not asset_prison:
        return None
    types=sorted({str(kind).upper() for _,kind in packets}-{'FORCE','PSYCHIC','VOID'})
    return [{'kind':'resistance','damage_types':types}] if types else None


def delivery_profile(engine,action,owner_id):
    """Shared source authority; ordinary items never inherit the attacker's CL."""
    from ..observer_information import source_profile,source_numbers
    typed=(action.parameters or {}).get('typed') or {}
    data=source_profile(engine,action.source_definition_id,typed)
    numbers=source_numbers(engine,action.source_definition_id,owner_id)
    level=data.get('source_cl')
    if type(level) is not int and not typed.get('weapon'):
        level=numbers.get('cl')
    return {**data,'source_cl':level if type(level) is int else None,
            'save_dc':data.get('save_dc',numbers.get('save_dc'))}


def brace_categories(ctx,named):
    if {'prone','forced_movement'} & set(named or ()):
        return True
    from ..observer_information import source_profile
    authored=source_profile(ctx.engine,ctx.source,ctx.typed)
    return 'shield_brace_allowed' in authored.get('tags',[])


def deflection_causes(ctx,target,spec):
    """Only committed AC state and this actual rolled miss establish causation."""
    engine=ctx.engine
    ids=list(dict.fromkeys([*spec.get('warden_deflection_owners',[]),
        *ctx.damage_cache.get('warden_deflect:'+target.entity_id,[])]))
    roll_id=spec.get('attack_roll_id') or (getattr(ctx,'attack_result',None) or {}).get('roll_id')
    found=next(((i,e) for i,e in reversed(list(enumerate(engine.events)))
        if e.event_type=='ATTACK_ROLLED' and e.actor_id==ctx.actor.entity_id
        and target.entity_id in e.target_ids and (not roll_id or e.payload.get('roll_id')==roll_id)),None)
    if found is None:
        return ids
    index,event=found
    natural=int(event.payload.get('natural_result') or 0)
    if natural==1 or natural>=int(spec.get('critical_threshold') or 20):
        return []
    from ..attack_outcomes import attack_outcome
    receipt=attack_outcome(engine,ctx.actor.entity_id,index)
    ac=int((receipt or {}).get('armor_class') or event.payload.get('target_ac') or 0)
    total=int(event.payload.get('modified_total',event.payload.get('total',0)))
    for e in engine.events[index+1:]:
        if e.payload.get('roll_id')==event.payload.get('roll_id') and type(e.payload.get('modified_total')) is int:
            total=e.payload['modified_total']
    from ..observer_information import source_profile
    from .qi_path import GUARD
    qi_armor='tianxia.path.qi_cultivation.feature.qi_armor'
    for owner,_ in protection(engine,target):
        if owner.entity_id in ids or not profile(engine,owner,DEFLECT):
            continue
        provided=0
        for m in target.modifiers.values():
            if m.source_actor_id!=owner.entity_id or m.operation!='ADD' or m.target_field not in ('armor_class','armor_class_vs_ranged'):
                continue
            explicit=source_profile(engine,m.source_definition_id,{})
            if m.source_definition_id in (qi_armor,GUARD) or 'shield_bonus' in explicit.get('tags',[]):
                provided+=max(0,int(m.value))
        if provided and ac-provided<=total<ac:
            ids.append(owner.entity_id)
    return ids


def provided_shield_bonus(engine,target):
    """Only explicit shield bonuses share the nonstacking shield ceiling."""
    from .qi_path import GUARD
    from ..observer_information import source_profile
    return max([0,*[max(0,int(m.value)) for m in target.modifiers.values()
        if m.target_field=='armor_class_vs_ranged' and m.operation=='ADD'
        and (m.source_definition_id==GUARD or 'shield_bonus' in
             source_profile(engine,m.source_definition_id,{}).get('tags',[]))]])


@hook('activation_accounting')
def account_warden_responses(engine):
    return True if any(profile(engine,a) for a in engine.state.actors.values()) else None


@hook('technique_used')
def settle_warden_action(ctx):
    if (ctx.action.parameters or {}).get('warden') and profile(ctx.engine,ctx.actor,ctx.typed.get('source')):
        from ..paid_relocation import settle_activation
        settle_activation(ctx.engine,ctx.actor,ctx.source)


@hook('activation_settled')
def warden_settlement(engine,owner,view):
    action=engine.action_catalog.get(view.source_id)
    feature=((action.parameters or {}).get('typed') or {}).get('source') if action else view.source_id
    if feature not in LEVELS or not profile(engine,owner,feature):
        return
    engine._append_event('PASSIVE_TRIGGERED',view.source_id,actor_id=owner.entity_id,
        payload={'activation_settlement':{'activation_id':view.activation_id,'actor_id':owner.entity_id,'source_id':view.source_id,
            'payments':list(view.payments),'refunds':list(view.refunds),'net_payments':list(view.net_payments)},
            'log':'Orbiting Shield Warden activation resolved; its actual resource payments and refunds are settled.'})


# Source-owned real-item binding. This uses the existing inventory, activity and
# fact-admission contracts; it is not another inventory or generic rite ledger.
BOND='source:orbiting_shield_warden:bound_item'
BOUND='condition:typed.warden_bound_item'


def shield_name(item):
    from factory_authoring.starting_kits import item_definition
    name=item.get('name') or ''
    return (item_definition(item.get('item_id','')) or {}).get('name','Shield') if name.startswith('tianxia.') else (name or 'Shield')


def bound_shield(actor):
    """The real, admitted ten-minute bond; never inferred from inventory alone."""
    return next((c.data for c in actor.conditions.values() if c.condition_id==BOUND),None)


def shield_control(engine,owner,obj):
    row=profile(engine,owner) or {}
    return 60 if obj.component[TAG].get('projected') or profile(engine,owner,CONSTELLATION) or row.get('armament_link') else 30


def bound_available(engine,owner,bond):
    from .scoundrel_riders import possessions,object_id
    identity=object_id(bond['inventory_owner'],bond['item_key'])
    obj=engine.state.objects.get(identity)
    if obj is not None and (obj.destroyed or obj.suppressed):
        return False
    filed=engine.state.actors.get(bond['inventory_owner'])
    if obj is not None and filed is not None and any(c.data.get('object_id')==identity and c.data.get('object_location')=='external'
            and c.data.get('held_by')==owner.entity_id for c in filed.conditions.values()):
        return engine.grid.distance_ft(owner.position,obj.position)<=shield_control(engine,owner,obj)
    return any(r.get('object')==identity for a in engine.state.actors.values()
               if engine.grid.distance_ft(owner.position,a.position)<=5 for r in possessions(engine,a))


def bound_location(engine,owner,bond,location,source):
    """Write the existing exact-item relocation ledger, shared by AC and hands."""
    from .scoundrel_riders import object_id,DISARMED
    from .condition_ownership import remove_instance
    filed=engine.state.actors[bond['inventory_owner']]
    identity=object_id(filed.entity_id,bond['item_key'])
    previous=[c.instance_id for c in filed.conditions.values() if c.data.get('object_id')==identity]
    engine._apply_condition(filed,DISARMED,source,owner.entity_id,expires_on='UNTIL_REMOVED',
        data={'item_key':bond['item_key'],'item_name':shield_name(bond['item']),
              'owner':filed.entity_id,'object_id':identity,'held_by':owner.entity_id,
              'object_location':location,**({'hand':location[5:]} if location.startswith('hand:') else {}),
              **({'disables_action':bond['item']['weapon_action']} if bond['item'].get('weapon_action') and not (filed.entity_id==owner.entity_id and location.startswith('hand:')) else {})})
    for instance in previous:
        remove_instance(engine,filed,instance,source)
    from .. import carry
    for actor in {filed.entity_id:filed,owner.entity_id:owner}.values():
        carry.refresh(engine,actor,source)


def drop_bound(engine,owner,bond,point,source):
    from .. import carry
    from .scoundrel_riders import object_id
    from .condition_ownership import remove_instance
    filed=engine.state.actors[bond['inventory_owner']]
    identity=object_id(filed.entity_id,bond['item_key'])
    previous=[c.instance_id for c in filed.conditions.values() if c.data.get('object_id')==identity]
    # Publish the replacement before removing the old ledger row. Otherwise
    # state-event readers briefly restore default hands and move the actual
    # falling object back to its old owner's body.
    engine._apply_condition(filed,carry.DROPPED,source,owner.entity_id,expires_on='UNTIL_REMOVED',
        data={'item_key':bond['item_key'],'item_name':shield_name(bond['item']),'owner':filed.entity_id,
              'object_id':identity,'dropped_at':point.model_dump(mode='json'),
              **({'disables_action':bond['item']['weapon_action']} if bond['item'].get('weapon_action') else {})})
    for instance in previous:
        remove_instance(engine,filed,instance,source)
    for actor in {filed.entity_id:filed,owner.entity_id:owner}.values():
        carry.refresh(engine,actor,source)


@hook('state_event')
def carried_bound_item_position(engine,event):
    if event.event_type not in ('MOVEMENT_COMMITTED','CONDITION_APPLIED','CONDITION_REMOVED'):
        return
    from .scoundrel_riders import possessions
    for obj in list(engine.state.objects.values()):
        tag=(obj.component or {}).get(TAG) or {}
        if not tag or tag.get('projected') or tag.get('location','floating')=='floating' or obj.destroyed:
            continue
        holder=next((a for a in engine.state.actors.values() if any(r.get('object')==obj.object_id for r in possessions(engine,a))),None)
        if holder is not None and (holder.position!=obj.position or obj.unattended):
            engine._update_object(obj.model_copy(update={'position':holder.position,'unattended':False}),RAISE,obj.owner_id)


def release_bound(ctx,point):
    from ..gate2_runtime_models import RuntimeObjectState
    from .effect_durations import round_token
    from .scoundrel_riders import object_id
    engine,owner=ctx.engine,ctx.actor
    bond=bound_shield(owner)
    if bond is None or not bound_available(engine,owner,bond) or point is None:
        raise ValueError('The actual bound Shield must be available within reach before releasing it.')
    held=shields(engine,owner)
    limit=3 if profile(engine,owner,CONSTELLATION) else 1
    if len(held)>=limit:
        selected=choose(engine,owner,'bound.replace',[o.object_id for o in held],optional=False,
            labels={o.object_id:'Replace this projected Ward' for o in held})
        obj=engine.state.objects[selected[0]]
        if not obj.component[TAG].get('projected'):
            raise ValueError('This real shield is already floating; it cannot be duplicated.')
        from .condition_ownership import remove_instance
        for c in list(controls(owner)):
            if c.data['object_id']==obj.object_id:
                remove_instance(engine,owner,c.instance_id,ctx.source)
    if not profile(engine,owner,CONSTELLATION):
        # Before the printed three-Shield exception, the base Path maintains
        # one Domain Armament: releasing the real item ends its projection.
        from .qi_path import armament_condition
        from .condition_ownership import remove_instance
        prior_armament=armament_condition(owner)
        if prior_armament is not None:
            remove_instance(engine,owner,prior_armament.instance_id,ctx.source)
    identity=object_id(bond['inventory_owner'],bond['item_key'])
    prior=engine.state.objects.get(identity)
    stat=bond['profile']
    bound_location(engine,owner,bond,'external',ctx.source)
    engine._apply_condition(owner,WARD,ctx.source,owner.entity_id,expires_on=round_token(engine,4800 if profile(engine,owner,CONSTELLATION) else 600),
        data={'object_id':identity,'label':'Bound Orbiting Shield — actual item, not a projection'})
    obj=RuntimeObjectState(object_id=identity,object_kind='BOUND_SHIELD',owner_id=owner.entity_id,position=point,
        unattended=False,flammable=False,ac=stat['ac'],current_hp=prior.current_hp if prior else stat['hp'],
        maximum_hp=stat['hp'],damage_threshold=stat['threshold'],damage_immunities=tuple(stat['immune']),
        component={'name':shield_name(bond['item']),'size':'small','kind':'shield',
            'item':True,'cultivation_implement':True,'blocks':False,'resist':stat['resist'],
            'artifact':stat['artifact'],'source_cl':stat['source_cl'],'created_by':ctx.source,
            'bound_item':bond['item'],TAG:{'owner':owner.entity_id,'source_cl':stat['source_cl'],
                'mode':'guard','protected':'','projected':0,'protected_until':0,'location':'floating'}})
    engine._update_object(obj,ctx.source,owner.entity_id)


@hook('technique_used')
def replace_bound_with_base_projection(ctx):
    if (ctx.action.parameters or {}).get('armament')!='manifest' or not profile(ctx.engine,ctx.actor) or profile(ctx.engine,ctx.actor,CONSTELLATION):
        return
    from .qi_path import armament_condition
    from .condition_ownership import remove_instance
    if armament_condition(ctx.actor) is None:
        return
    for obj in list(shields(ctx.engine,ctx.actor,inactive=True)):
        if obj.component[TAG].get('projected'):
            continue
        for condition in list(controls(ctx.actor)):
            if condition.data['object_id']==obj.object_id:
                remove_instance(ctx.engine,ctx.actor,condition.instance_id,ctx.source)
        current=ctx.engine.state.objects[obj.object_id]
        if current.component[TAG].get('location','floating')=='floating':
            destroy(ctx.engine,current,ctx.source)


def call_bound(ctx):
    from .hand_occupancy import free_hands
    from .condition_ownership import remove_instance
    engine,owner=ctx.engine,ctx.actor
    obj=next((o for o in shields(engine,owner) if not o.component[TAG].get('projected')),None)
    hands=free_hands(engine,owner)
    if obj is None or not hands or owner.position not in locations(engine,owner,obj.position,60):
        raise ValueError('Calling the actual shield requires a free hand and an unobstructed route.')
    update(engine,obj,ctx.source,location='carried',protected='')
    for c in list(controls(owner)):
        if c.data['object_id']==obj.object_id:
            remove_instance(engine,owner,c.instance_id,ctx.source)
    bound_location(engine,owner,bound_shield(owner),'hand:'+hands[0],ctx.source)
    obj=engine.state.objects[obj.object_id]
    engine._update_object(obj.model_copy(update={'position':owner.position,
        'component':{**obj.component,TAG:{**obj.component[TAG],'location':'wielded','protected':''}}}),ctx.source,owner.entity_id)


@hook('compile_bundle')
def seal_bound_shield_properties(bundle,info):
    """Keep admitted treasure refinement with its actual inventory identity.

    Native armor compilation has the full item record; inventory alone otherwise
    retains only its name/attunement flags. No stats are inferred from that name.
    Only Warden bundles need this source-owned read-only item projection.
    """
    if not any(r.get('block')==TAG for r in bundle.get('typed_passives',[])):
        return bundle
    from copy import deepcopy
    records={'treasure_armor':(info.get('kit') or {}).get('resolved_treasure_armor')}
    records.update({'given.'+str(i):r.get('record') for i,r in enumerate(info.get('owner_items') or [])})
    result=deepcopy(bundle)
    for item in result.get('carrying',{}).get('items',[]):
        record=records.get(item['key']) or {}
        if item.get('shield') and (record.get('chassis') or {}).get('armor_category')=='shield':
            refinement=int(record.get('refinement_bonus') or 0)
            item['warden_shield_profile']={'shield_bonus':2+refinement,'refinement_bonus':refinement,
                'body_refinement_bonus':refinement if item['key']=='treasure_armor' else 0}
    return result


@hook('ac')
def external_shield_refinement(engine,target,**kwargs):
    """The actual shield's refinement is not also body AC while it is away."""
    from ..carry import lost_to_another_hand
    if not profile(engine,target):
        return None
    from ..carry import carrying_of
    penalty=sum(int(item.get('warden_shield_profile',{}).get('body_refinement_bonus') or 0)
        for item in (carrying_of(engine,target.entity_id) or {}).get('items',[])
        if lost_to_another_hand(target,item['key']))
    return -penalty if penalty else None


def shield_guard_bonus(engine,obj):
    if obj.component[TAG].get('projected'):
        return 2
    return int(obj.component.get('bound_item',{}).get('warden_shield_profile',{}).get('shield_bonus',2))


def shield_attack(ctx,obj,dtype):
    """Use the actual item's sealed weapon profile when it has one, else bound-shield dice."""
    from copy import deepcopy
    cl=int(ctx.numbers['cl'])
    item=obj.component.get('bound_item') or {}
    weapon=ctx.engine.action_catalog.get(item.get('weapon_action'))
    if not obj.component[TAG].get('projected') and weapon is not None:
        typed=(weapon.parameters or {}).get('typed') or {}
        attack=next((r for r in typed.get('effects',[]) if r.get('type')=='attack'),None)
        if attack is not None and (typed.get('weapon') or {}).get('damage'):
            armament_count=3 if cl>=17 else 2 if cl>=13 else 1
            profile=deepcopy(typed['weapon'])
            damage=profile['damage']
            if armament_count*9>int(damage['count'])*(int(damage['sides'])+1):
                damage.update(count=armament_count,sides=8)
            damage['modifier']=int(damage.get('modifier') or 0)-int(profile.get('ability_modifier') or 0)+int(ctx.numbers['key_mod'])
            source={**ctx.typed,'weapon':profile,'numbers':{**ctx.numbers,
                'attack_bonus':int(ctx.numbers['attack_bonus'])+int(typed.get('magic_bonus') or 0)}}
            return source,{**deepcopy(attack),'attack_kind':'cultivation_melee','count':1}
    return ctx.typed,{'type':'attack','attack_kind':'cultivation_melee','count':1,'on_hit':[{'type':'damage',
        'applies_to':'target','dice':{'count':3 if cl>=17 else 2 if cl>=13 else 1,'sides':8},
        'formula':'key_ability_modifier','damage_types':[dtype]}]}



@hook('compile_action')
def seal_warden_equipment(action,info):
    if (action.parameters or {}).get('warden') not in ('manifest','constellation'):
        return action
    from copy import deepcopy
    from .shield_training import trained
    typed={**action.parameters['typed'],'warden_equipment':{
        'shield_proficiency':int(trained(info)),
        'items':deepcopy(info['carrying'].get('items') or [])}}
    return action.model_copy(update={'parameters':{**action.parameters,'typed':typed}})


def journey_equipment(session,aid):
    actor=session.state['actors'][aid]
    return next((((a.get('parameters') or {}).get('typed') or {}).get('warden_equipment',{})
        for a in actor['bundle']['action_catalog'] if (a.get('parameters') or {}).get('warden') in ('manifest','constellation')),{})


def native_item(session,inventory_owner,key):
    from ..journey import require
    actor=session.state['actors'].get(inventory_owner)
    require(actor is not None,'Name the actual inventory owner in this journey.')
    item=next((r for r in actor['bundle'].get('carrying',{}).get('items',[]) if r['key']==key),None)
    require(item is not None and item.get('shield') and int(item.get('quantity') or 0)==1,
            'Choose one actual shield in this creature’s admitted inventory; a projected Ward is not an item.')
    return item


def item_scope(inventory_owner,key):
    return 'item:'+inventory_owner+'|'+key


@hook('fact_admission_schema')
def warden_item_facts(session,source,subject,kind):
    from .qi_path import ARMAMENT
    if source!=ARMAMENT or subject not in session.state['actors']:
        return None
    if not any(journey_profile(session,aid) for aid in session.state['actors']):
        return None
    if kind=='shield_item_profile':
        return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
                'description':'The GM records this actual shield’s printed durability, Source CL, source restrictions and sentient-item decision, with its governing Source Rule.'}
    if kind=='shield_binding_permission':
        return {'value_type':'flag','maximum_seconds':86400,'authority':'subject',
                'description':'The actual inventory owner grants or refuses this named creature permission to touch and bind this specific shield.'}
    return None


def binding_admission(session,aid,parameters):
    from ..journey import require
    from ..fact_consent_admission import read,digest
    from .qi_path import ARMAMENT
    require(set(parameters)=={'inventory_owner','item_key'} and all(type(v) is str and v for v in parameters.values()),
            'Choose the actual inventory owner and shield item.')
    owner,key=parameters['inventory_owner'],parameters['item_key']
    actor=session.state['actors'][aid]
    require(journey_profile(session,aid) is not None and not actor['incapacitated'],
            'Only an acquired Orbiting Shield Warden can use this source binding procedure.')
    require(any(r.get('block')=='qi_path' and r.get('kind')=='domain_armament'
                for r in actor['bundle'].get('typed_passives',[])),
            'You must first acquire the Qi Path’s Domain Armament integration.')
    require(journey_equipment(session,aid).get('shield_proficiency')==1,
            'This school does not grant physical shield proficiency; acquire a real proficiency source first.')
    item=native_item(session,owner,key)
    from ..gate2_runtime_models import Position
    # The public geometry adapter reads the existing inventory and native
    # encounter transfer ledger. Inventory ownership alone is not possession.
    from ..journey_assets import JourneyAssetContext
    from .scoundrel_riders import possessions,object_id
    context=JourneyAssetContext(session)
    physical=object_id(owner,key)
    holders=[a for a in context.state.actors.values() if any(r.get('object')==physical for r in possessions(context,a))]
    require(len(holders)==1 and session.grid.distance_ft(Position.model_validate(actor['position']),holders[0].position)<=5,
            'You must remain touching the actual shield for all ten uninterrupted minutes; a dropped or taken item is not in its original inventory owner’s hands.')
    if item.get('attunement_slots'):
        require(owner==aid and item.get('attuned'),
                'The binding cultivator must personally meet the shield’s actual attunement requirement.')
    scope=item_scope(owner,key)
    if owner!=aid:
        permission=read(session,ARMAMENT,owner,'shield_binding_permission',scope+'|binder:'+aid,aid)
        require(permission is not None and permission['value']==1,
                'The actual owner must grant this specific binding permission through their native consent declaration.')
    for other_id,other in session.state['actors'].items():
        prior=other.get('source_states',{}).get(BOND)
        require(not prior or (prior['inventory_owner'],prior['item_key'])!=(owner,key) or other_id==aid,
                'This actual shield is already bound as another creature’s Domain Armament.')
    record=read(session,ARMAMENT,owner,'shield_item_profile',scope,aid)
    require(record is not None,'The GM must collect the item’s source-scoped printed profile before binding; no Ward statistics are substituted.')
    value=record['value']
    fields={'item_sha256','source_rule','source_cl','ac','hp','threshold','resist','immune','sentience','artifact'}
    require(set(value)==fields and value['item_sha256']==digest(item),
            'The item profile must remain bound to this exact admitted inventory record.')
    require(type(value['source_rule']) is str and bool(value['source_rule'].strip()),'Cite the item’s actual governing Source Rule.')
    require(all(type(value[k]) is int and value[k]>=minimum for k,minimum in
            [('source_cl',0),('ac',0),('hp',1),('threshold',0),('artifact',0)]) and value['artifact'] in (0,1),
            'Item authority, durability and artifact classification use validated whole numbers.')
    require(value['sentience'] in ('nonsentient','sentient_willing','sentient_refuses'),
            'The GM must record the actual sentient item’s decision, without assuming consent.')
    require(value['sentience']!='sentient_refuses','A sentient item that refuses cannot be bound.')
    require(all(isinstance(value[k],list) and len(value[k])==len(set(value[k]))
                and all(type(t) is str and t and t==t.upper() for t in value[k]) for k in ('resist','immune')),
            'Use the actual printed resistance and immunity classifications.')
    return item,record


@hook('activity_spec')
def shield_binding_activity(session,aid,source,parameters):
    from .qi_path import ARMAMENT
    if source!=ARMAMENT or not journey_profile(session,aid):
        return None
    item,_=binding_admission(session,aid,parameters)
    return {'seconds':600,'label':'Bind '+shield_name(item)+' as your actual Domain Armament; remain touching it for ten uninterrupted minutes'}


@hook('activity_validate')
def validate_shield_binding(session,aid,row):
    from .qi_path import ARMAMENT
    if row['source']==ARMAMENT and journey_profile(session,aid):
        binding_admission(session,aid,row['parameters'])


@hook('activity_finished')
def finish_shield_binding(session,aid,row):
    from .qi_path import ARMAMENT
    if row['source']!=ARMAMENT or not journey_profile(session,aid):
        return
    from copy import deepcopy
    item,record=binding_admission(session,aid,row['parameters'])
    bond={**deepcopy(row['parameters']),'item':source_primitives(item),'profile':deepcopy(record['value']),
          'profile_receipt_id':record['receipt_id'],'bound_at':int(session.clock()),'location':'carried'}
    session.state['actors'][aid].setdefault('source_states',{})[BOND]=bond
    session.emit('WARDEN_REAL_ITEM_BOUND',aid,source=ARMAMENT,bond=deepcopy(bond))


@hook('activity_command_interrupts')
def interrupt_item_contact(session,worker,row,who,kind,payload):
    from .qi_path import ARMAMENT
    if row['source']!=ARMAMENT or not journey_profile(session,worker):
        return None
    if who==row['parameters']['inventory_owner'] and kind in ('move','set_down','request_carry','incapacitated'):
        return True
    return None


def source_primitives(value):
    """Immutable inventory views use the journey's recognized integer flags."""
    if type(value) is bool:return int(value)
    if type(value) in (int,str):return value
    if isinstance(value,list):return [source_primitives(v) for v in value]
    if isinstance(value,dict):return {k:source_primitives(v) for k,v in value.items() if v is not None}
    raise ValueError('A source continuation cannot persist an opaque inventory value.')
