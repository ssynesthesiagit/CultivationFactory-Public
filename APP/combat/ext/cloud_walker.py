"""Cloud Walker's owned native movement and travel procedures.

Uses the public native movement, elapsed-time journey, consent, condition and
cost contracts. No ownership is inferred from names or sides. Timed receipts
are source-owned; plain actors and old bundles have no additional capability.
"""
from fractions import Fraction
from dataclasses import replace
from . import effect, hook
from .condition_ownership import remove_instance
from .qi_subpaths_five import CLOUD, FEATHER, cloud_step_protection, qi_path_numbers

STEP = CLOUD + 'cloud_step'
WIND = CLOUD + 'wind_walk'
LEAP = CLOUD + 'heavenly_leap'
IMMORTAL = CLOUD + 'cloud_immortal'
QI = 'resource:core.qi'
FORM = 'condition:typed.cloud_walker_form'
SEGMENT = 'condition:typed.cloud_walker_leap'
DESCENT = 'condition:typed.cloud_walker_descent'
CARRY = 'condition:typed.cloud_walker_carry'


def form(actor, mode=None):
    return next((c for c in actor.conditions.values() if c.condition_id == FORM
                 and (mode is None or c.data.get('mode') == mode)), None)


def stamp(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}'


@hook('compile_passives')
def family_rows(rows, info):
    if not any(f in info['owned_ids'] for f in (FEATHER,STEP,WIND,LEAP,IMMORTAL)):
        return rows
    numbers=qi_path_numbers(info)
    owned = [f for f,level in ((FEATHER,3),(STEP,6),(WIND,10),(LEAP,14),(IMMORTAL,18))
             if f in info['owned_ids'] and int(numbers['cl'])>=level]
    if not owned:
        return rows
    return [*rows, {'block': 'cloud_walker', 'features': owned, 'cl': int(numbers['cl']),
                   'choice_owner': True, 'numbers': numbers}]


def ownership(engine, actor):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                 if r.get('block') == 'cloud_walker'), {})


@hook('jump_distance_multiplier')
def feather_distance(engine, actor):
    return 3 if FEATHER in ownership(engine, actor).get('features', ()) else None


@hook('difficult_exempt')
def step_terrain(engine, actor):
    if not cloud_step_protection(engine, actor) and not form(actor, 'immortal'):
        return None
    from ..motion import TerrainExemption
    return TerrainExemption({(x,y) for x in range(engine.grid.width) for y in range(engine.grid.height)},
                            nonmagical_only=not bool(form(actor, 'immortal')))


@effect('cloud_walker_form')
def transform(ctx, row):
    from ..typed_executor import effect_expiry
    mode = row['mode']
    if mode not in {'wind','immortal'}:
        raise ValueError('Cloud Walker form must be travel mist or living cloud')
    target = ctx.target if row.get('applies_to') == 'target' else ctx.actor
    for held in list(target.conditions.values()):
        if held.condition_id == FORM:
            remove_instance(ctx.engine, target, held.instance_id, ctx.source)
    ctx.engine._apply_condition(target, FORM, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, target, condition=True), data={
            'mode': mode, 'source_cl': int(ctx.numbers['cl']), 'choice_owner': True,
            'fly_speed_ft': 40 if mode == 'wind' else 60, 'flight_hover': 1,
            'label': ('Wind Walk: travel mist for 1 hour; end as a Bonus Action' if mode == 'wind'
                      else 'Cloud Immortal: living cloud for 1 minute'),
            'rule': {'ignore_difficult': True} if mode == 'immortal' else {}})
    if mode=='immortal':
        from .physical_holds import source,end_hold
        for key,held in list(target.conditions.items()):
            physical,source_cl=source(ctx.engine,held)
            if physical and source_cl is not None and source_cl<=int(ctx.numbers['cl']):
                end_hold(replace(ctx,actor=target,target=target,targets=[target]),key)


@hook('technique_cost_discount')
def free_leap(engine, actor, source, costs):
    action = engine.action_catalog.get(source)
    if action and action.parameters.get('typed', {}).get('source') == LEAP and form(actor, 'immortal'):
        return {QI: min(3, costs.get(QI, 0))}
    return None


@hook('compile_actions')
def inherited_leap(info):
    if IMMORTAL not in info['owned_ids'] or LEAP in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=LEAP, display_name='Heavenly Leap',
        owner_id=info['actor_id'], economy='BONUS_ACTION', resolution_kind='TYPED', target_kind='SELF',
        costs=[(QI,3)], parameters={'cloud_inherited_leap':True, 'typed':{
            'manual_inline_choice': True, 'source':LEAP, 'numbers':qi_path_numbers(info), 'effects':[{'type':'cloud_walker_leap'}]}})]


@hook('candidate_allowed')
def leap_admission(engine, actor, candidate, action):
    if not action:
        return None
    typed = action.parameters.get('typed', {})
    if action.parameters.get('cloud_end_wind'):
        return bool(form(actor, 'wind'))
    source=typed.get('source')
    if source in {STEP,WIND,LEAP,IMMORTAL} and int(typed.get('numbers',{}).get('cl',0)) < {STEP:6,WIND:10,LEAP:14,IMMORTAL:18}[source]:
        return False
    if source == LEAP:
        return (actor.turn_flags.get('cloud_leap') != stamp(engine)
                and (not action.parameters.get('cloud_inherited_leap') or bool(form(actor, 'immortal'))))
    if form(actor, 'wind'):
        grip=action.parameters.get('equipment_grip') or {}
        if grip.get('held') or int(action.parameters.get('requires_hands') or 0)>1:
            return False
        from ..effect_harm import classify_effect
        # Ability-agnostic classification reads sealed effects, including nested
        # on-hit/options, rather than guessing hostility from a display name.
        effects = typed.get('effects') or []
        forbidden = {'attack','zone','aura','domain','summon_field'}
        def offense(rows):
            for row in rows:
                if row.get('type') in forbidden or classify_effect(row) is True:
                    return True
                if int(row.get('hands_required') or 0)>1:
                    return True
                if any(offense(row[k]) for k in ('effects','on_hit','on_fail','on_success') if isinstance(row.get(k),list)):
                    return True
            return False
        if action.attack_bonus is not None or action.damage is not None or action.resolution_kind in ('ATTACK','MELEE_ATTACK','RANGED_ATTACK') or offense(effects):
            return False
    return None


def adjacent_landings(engine, passenger, destination, *, observed=True, carrier=None):
    from ..gate2_runtime_models import Position
    viewer=carrier or passenger
    occupied=(engine._occupied_volumes_except(viewer.entity_id,observed=True,ignore_actor_ids=(passenger.entity_id,))
              if observed else {cell for other in engine.state.actors.values()
                  if other.entity_id not in {passenger.entity_id,viewer.entity_id} and other.active
                  and engine._on_battlefield(other) for cell in engine._actor_volume(other)})
    occupied = set(occupied) | set(engine._actor_volume(viewer, destination))
    out=[]
    for dx in (-1,0,1):
        for dy in (-1,0,1):
            for dz in (-1,0,1):
                if not (dx or dy or dz) or destination.z+dz<0 or not engine.grid.in_bounds((destination.x+dx,destination.y+dy)):
                    continue
                cell=Position(x=destination.x+dx,y=destination.y+dy,z=destination.z+dz)
                if engine.grid.volume_legal(cell, footprint=engine._footprint(passenger), occupied_cells=occupied):
                    out.append(cell)
    return out


@effect('cloud_walker_leap')
def leap(ctx, row):
    from ..flight import reachable
    from .cloud_walker_environment import visible_destination
    from ..granted_movement import Route
    from .needle import ask, checkpoint_id, cell_id
    from .willing_targets import asks_consent
    from ..relations import relation
    from ..typed_reactions import physical_melee_reach
    from ..target_knowledge import knowledge
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get('cloud_leap') == stamp(engine):
        return
    # This is a real scoped movement capability, not a temporary engine patch.
    # It is removed after the segment, letting ordinary falling settle then.
    engine._apply_condition(actor, SEGMENT, ctx.source, actor.entity_id, expires_on='END_OF_CURRENT_TURN',
        data={'fly_speed_ft':120, 'flight_hover':1, 'label':'Heavenly Leap movement segment'})
    segment=next(c for c in actor.conditions.values() if c.condition_id==SEGMENT)
    try:
        paths={cell_id(p):(p,path) for p,(path,cost,mode) in reachable(engine,actor,grant_ft=120,mode='fly').items()
               if p!=actor.position and engine.grid.distance_ft(actor.position,p)<=120
               and engine._line_of_sight_actor_to_cell(actor,p) and visible_destination(engine,actor,p)
               and engine.grid.volume_legal(p,footprint=engine._footprint(actor),
                   occupied_cells=engine._occupied_volumes_except(actor.entity_id,observed=True))}
        if not paths:
            return
        chosen=ask(engine,ctx.intent,checkpoint_id(engine,'CLOUD_LEAP',actor.entity_id),actor,
            'choice:needle.cloud_leap_destination',sorted(paths),preferred=sorted(paths)[:1],
            labels={key:f'Move to ({p.x}, {p.y}), {p.z*5} feet high' for key,(p,path) in paths.items()},
            name='Heavenly Leap',prompt=f'{actor.display_name}: choose a visible unoccupied destination within 120 feet. '
            'Move without provoking; this is not teleportation. Carrying a willing companion costs 2 additional Qi.')
        if not chosen:
            return
        destination,path=paths[chosen[0]]
        passenger=None;landing=None
        if actor.resources.get(QI,0)>=2:
            available={a.entity_id:a for a in engine.state.actors.values() if a is not actor and a.active
                       and engine._distance_actor_to_actor(actor,a)<=max(5, physical_melee_reach(engine,actor) or 0)
                       and (known:=knowledge(engine,actor,a)) is not None and known.mode=='DIRECT'
                       and engine.grid.line_of_physical_transmission(actor.position,a.position)
                       and adjacent_landings(engine,a,destination,carrier=actor)}
            if available:
                pick=ask(engine,ctx.intent,checkpoint_id(engine,'CLOUD_PASSENGER',actor.entity_id),actor,
                    'choice:needle.cloud_leap_companion',sorted(available),preferred=[],allow_decline=True,default='decline',
                    labels={aid:f'Carry {a.display_name} (2 Qi)' for aid,a in available.items()},
                    name='Carry a Companion',prompt='Declare a companion before moving, or travel alone. '
                    'The companion must consent and fit beside your destination; carrying costs 2 Qi.')
                if pick:
                    other=available[pick[0]]
                    if asks_consent(engine,ctx.intent,other,'Heavenly Leap',
                        f'Let {actor.display_name} carry {other.display_name} to the chosen destination without provoking?',
                        prefer_accept=relation(engine,actor,other)=='ALLY',asker=actor):
                        cells=adjacent_landings(engine,other,destination,carrier=actor)
                        options={cell_id(p):p for p in cells}
                        selected=ask(engine,ctx.intent,checkpoint_id(engine,'CLOUD_LANDING',other.entity_id),actor,
                            'choice:needle.cloud_leap_landing',sorted(options),preferred=sorted(options)[:1],
                            labels={k:f'Place {other.display_name} at ({p.x}, {p.y}), {p.z*5} feet high' for k,p in options.items()},
                            name='Carry a Companion',prompt='Choose the companion’s unoccupied adjacent destination (2 Qi).')
                        if selected:
                            passenger,landing=other,options[selected[0]]
        carry_receipt=None
        if passenger is not None:
            # A carried creature is physically present for every committed step.
            # The scoped receipt authorizes boarding/sharing only with this
            # carrier; it never grants passage through unrelated creatures.
            engine._apply_condition(passenger,CARRY,ctx.source,actor.entity_id,
                expires_on='END_OF_CURRENT_TURN',data={'carrier_id':actor.entity_id,
                    'flight_suspended':1,'fly_speed_ft':120,'flight_hover':1,
                    'label':f'Carried by {actor.display_name} during Heavenly Leap'})
            carry_receipt=next(c for c in passenger.conditions.values() if c.condition_id==CARRY)
            board=reachable(engine,passenger,grant_ft=120,mode='fly').get(actor.position)
            if board is None:
                remove_instance(engine,passenger,carry_receipt.instance_id,ctx.source)
                carry_receipt=None;passenger=None
            else:
                engine._spend_resource(actor,QI,2,ctx.source)
                engine.move_path(passenger,Route(tuple(board[0]),'fly'),ctx.source,kind='granted',
                                 feet=120,intent=ctx.intent,provokes=False)
                if passenger.position!=actor.position:
                    remove_instance(engine,passenger,carry_receipt.instance_id,ctx.source)
                    carry_receipt=None;passenger=None
        actor.turn_flags['cloud_leap']=stamp(engine)
        try:
            engine.move_path(actor,Route(tuple(path),'fly'),ctx.source,kind='granted',feet=120,
                             intent=ctx.intent,provokes=False)
            if passenger is not None:
                # On interruption, place beside the actual arrival. The caller
                # retains its paid cost; a destroyed route cannot refund it.
                choices=adjacent_landings(engine,passenger,actor.position,observed=False,carrier=actor)
                if choices:
                    place=landing if actor.position==destination and landing in choices else min(choices,
                        key=lambda p:(engine.grid.distance_ft(actor.position,p),p.z,p.y,p.x))
                    from .needle import step_to
                    step_to(engine,passenger,place,ctx.source,forced=False)
                else:
                    place=nearest_legal(engine,passenger)
                    if place is not None:
                        from .needle import step_to
                        step_to(engine,passenger,place,ctx.source,forced=True)
        finally:
            if carry_receipt is not None:
                remove_instance(engine,passenger,carry_receipt.instance_id,ctx.source)
    finally:
        remove_instance(engine,actor,segment.instance_id,ctx.source)


@hook('turn_end')
def stationary_step(engine, actor):
    from ..falling import supported, displace
    from ..flight import profile
    from .movement_clock import physical_distance
    if not cloud_step_protection(engine,actor) or form(actor,'immortal') or supported(engine,actor):
        return
    if physical_distance(engine,actor,include_forced=True)>=5:
        return
    # Stop at the first supporting surface, not beneath a roof platform.
    for _ in range(min(12,actor.position.z)):
        if supported(engine,actor):
            break
        if not displace(engine,actor,-1,STEP,settle_after=False):
            break
    if not supported(engine,actor):
        engine._apply_condition(actor,DESCENT,STEP,actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'flight_suspended':1,'choice_owner':True,'label':'Cloud Step: suspended until your next turn; move again or fall'})


@hook('turn_start_choice')
def step_resume(engine, actor):
    from ..falling import supported, drop
    from ..flight import profile, reachable
    from ..granted_movement import Route
    from .needle import ask, checkpoint_id, cell_id
    held=next((c for c in actor.conditions.values() if c.condition_id==DESCENT),None)
    if held is None:
        return
    independent=profile(engine,actor,excluding_conditions=(held.instance_id,))
    if not supported(engine,actor) and not independent.hover and not independent.suspended:
        routes={cell_id(p):(p,path,mode) for p,(path,cost,mode) in reachable(engine,actor).items() if p!=actor.position}
        picked=ask(engine,getattr(engine,'_active_intent',None),checkpoint_id(engine,'CLOUD_RESUME',actor.entity_id),actor,
            'choice:needle.cloud_step_resume',sorted(routes),preferred=sorted(routes)[:1],allow_decline=True,default='decline',
            labels={k:f'Move to ({p.x}, {p.y}), {p.z*5} feet high' for k,(p,path,mode) in routes.items()},
            name='Cloud Step',prompt=f'{actor.display_name} is unsupported. Move again using your movement, or begin falling normally.') if routes else []
        if picked:
            p,path,mode=routes[picked[0]]
            engine.move_path(actor,Route(tuple(path),mode),STEP,kind='willing',intent=getattr(engine,'_active_intent',None))
        else:
            remove_instance(engine,actor,held.instance_id,STEP)
            drop(engine,actor,getattr(engine,'_active_intent',None))
            return
    remove_instance(engine,actor,held.instance_id,STEP)


@hook('pass_through')
def wind_passage(engine, mover, occupant):
    return 'difficult' if form(mover) else None


@hook('damage_defenses')
def mist_defenses(engine, actor, kind, typed, source_actor_id):
    if form(actor,'wind') and str(kind).upper() in {'BLUDGEONING','PIERCING','SLASHING'}:
        from ..pending_damage import current
        from ..falling import SOURCE as FALLING_SOURCE
        packet=current(engine)
        native_fall=packet is not None and packet.target_id==actor.entity_id and packet.source_id==FALLING_SOURCE
        return [{'kind':'resistance','damage_types':[str(kind).upper()],'mundane_only':not native_fall}]
    if form(actor,'immortal') and str(kind).upper() not in {'FORCE','PSYCHIC','VOID'}:
        return [{'kind':'resistance','damage_types':[str(kind).upper()]}]
    return None


@hook('condition_attempt')
def physical_holds(ctx, subject, row):
    held=form(subject,'immortal')
    if not held or row.get('condition') not in ('grappled','restrained'):
        return None
    # Explicit delivery metadata is authoritative; a name never proves that
    # a restraint is physical. Native hand grapples provide their own typed tag.
    from .physical_holds import ordinary
    physical = ordinary(ctx.typed,row) or ctx.typed.get('physical_grapple') is True or row.get('physical') is True
    if physical and type(ctx.numbers.get('cl')) is int and ctx.numbers['cl']<=held.data['source_cl']:
        return False
    return None


@hook('event', nested=True)
def wind_zero_hp(engine, event_type, kwargs):
    if event_type!='DAMAGE_COMMITTED':
        return
    for aid in kwargs.get('target_ids') or ():
        actor=engine.state.actors.get(aid)
        held=form(actor,'wind') if actor else None
        if held and actor.current_hp<=0:
            remove_instance(engine,actor,held.instance_id,WIND)


def wind_end_definition(actor_id):
    """Ritual-produced recipient action, sealed in the ordinary native bundle."""
    from ..gate2_runtime_models import ActionDefinition
    return ActionDefinition(source_definition_id=WIND+'#end:'+actor_id,
        display_name='End Wind Walk (Bonus Action)',owner_id=actor_id,economy='BONUS_ACTION',
        resolution_kind='TYPED',target_kind='SELF',parameters={'cloud_end_wind':True,
            'typed':{'source':WIND,'effects':[{'type':'cloud_walker_end_wind'}]}})


@effect('cloud_walker_end_wind')
def end_wind(ctx, row):
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id==FORM and held.data.get('mode')=='wind':
            remove_instance(ctx.engine,ctx.actor,held.instance_id,ctx.source)


def journey_owned(session, aid, feature):
    return any(r.get('block')=='cloud_walker' and feature in r.get('features',())
               for r in session.state['actors'][aid]['bundle'].get('typed_passives',()))


def travel_mist(session, aid):
    return session.state['actors'][aid]['travel_effects'].get(WIND)


def near_ritual(session, caster, target):
    from ..gate2_runtime_models import Position
    a,b=session.state['actors'][caster],session.state['actors'][target]
    p,q=Position.model_validate(a['position']),Position.model_validate(b['position'])
    return (not b['incapacitated'] and session.grid.distance_ft(p,q)<=10
            and session.grid.line_of_sight(p,q) and session.grid.line_of_physical_transmission(p,q))


@hook('journey_options')
def wind_options(session, aid):
    if session.state['phase']!='travel':
        return None
    actor=session.state['actors'][aid]
    options=[]
    def add(kind,payload,label,auto=0):
        options.append({'id':kind+':'+str(len(options)),'kind':kind,'payload':payload,
                        'label':label,'auto_select':auto})
    if travel_mist(session,aid):
        add('cloud_wind_end',{},f'{actor["name"]}: end Wind Walk on yourself as a Bonus Action (no Qi).')
    ritual=actor.get('cloud_ritual')
    if journey_owned(session,aid,WIND) and not actor['incapacitated'] and not ritual and actor['resources'].get(QI,0)>=5:
        add('cloud_wind_begin',{},f'{actor["name"]}: begin Wind Walk, a 10-minute ritual costing 5 Qi; travel mist lasts 1 hour.')
    if ritual and not actor['incapacitated'] and session.clock()==Fraction(ritual['end_num'],ritual['end_den']):
        count=sum(answer in {'pending','accept'} and near_ritual(session,aid,target)
                  for target,answer in ritual['invitations'].items())
        pb=next(r['numbers']['pb'] for r in actor['bundle']['typed_passives'] if r.get('block')=='cloud_walker')
        if count<pb:
            for target,other in sorted(session.state['actors'].items()):
                if target!=aid and target not in ritual['invitations'] and near_ritual(session,aid,target):
                    add('cloud_wind_invite',{'target_id':target},f'Wind Walk: ask {other["name"]} to become travel mist for 1 hour; no additional Qi.')
        if all(v!='pending' for v in ritual['invitations'].values()):
            add('cloud_wind_finish',{},f'{actor["name"]}: finish Wind Walk; transform yourself and consenting creatures still within 10 feet for 1 hour.')
    for caster,other in sorted(session.state['actors'].items()):
        r=other.get('cloud_ritual')
        if r and r['invitations'].get(aid)=='pending' and near_ritual(session,caster,aid):
            for accept,verb in ((True,'Accept'),(False,'Decline')):
                add('cloud_wind_reply',{'caster_id':caster,'accept':accept},
                    f'{verb} {other["name"]}’s Wind Walk: {actor["name"]} becomes travel mist for 1 hour. '
                    'Fly 40 feet with Hover; no attacks, harmful features, fields, auras, Domains, weapons, shields or two-handed manipulation.',
                    auto=int(actor['control_mode']=='LOCAL_AUTO' and accept))
                options[-1]['auto_priority']=0
    return options or None


@hook('journey_command')
def wind_command(session, aid, kind, payload):
    if not kind.startswith('cloud_wind_'):
        return None
    from ..journey import require
    actor=session.state['actors'][aid]
    require(any(o['kind']==kind and o['payload']==payload for o in wind_options(session,aid) or ()),
            'Choose a currently available Wind Walk action; ownership, time, range and recipient consent are required.')
    if kind=='cloud_wind_begin':
        actor['resources'][QI]-=5
        end=session.clock()+600
        actor['cloud_ritual']={'end_num':end.numerator,'end_den':end.denominator,'invitations':{}}
        session.emit('CLOUD_WIND_RITUAL',aid,source=WIND,qi_cost=5,end_num=end.numerator,end_den=end.denominator)
    elif kind=='cloud_wind_invite':
        actor['cloud_ritual']['invitations'][payload['target_id']]='pending'
        session.emit('CLOUD_WIND_INVITATION',aid,source=WIND,target_id=payload['target_id'],expires_at=int(session.clock())+1)
    elif kind=='cloud_wind_reply':
        caster=payload['caster_id'];ritual=session.state['actors'][caster]['cloud_ritual']
        ritual['invitations'][aid]='accept' if payload['accept'] else 'refuse'
        session.emit('CLOUD_WIND_CONSENT',aid,source=WIND,caster_id=caster,accepted=int(payload['accept']))
    elif kind=='cloud_wind_finish':
        ritual=actor['cloud_ritual'];expires=session.clock()+3600
        targets=[aid,*[target for target,v in ritual['invitations'].items() if v=='accept' and near_ritual(session,aid,target)]]
        for target in targets:
            recipient=session.state['actors'][target]
            receipt={'source_actor_id':aid,'expiry_num':expires.numerator,'expiry_den':expires.denominator,
                     'source_cl':next(r['cl'] for r in actor['bundle']['typed_passives'] if r.get('block')=='cloud_walker')}
            recipient['travel_effects'][WIND]=receipt
            recipient['cloud_walker_saved']={}
            end_action=wind_end_definition(target)
            bundle=recipient['bundle']
            if end_action.source_definition_id not in bundle['actor_template']['action_ids']:
                bundle['action_catalog'].append(end_action.model_dump(mode='json'))
                bundle['actor_template']['action_ids'].append(end_action.source_definition_id)
            # This family-owned continuation declaration is copied unchanged by
            # journey_start_combat; it is produced only by the paid ritual.
            recipient['bundle']['cloud_walker_travel']=dict(receipt,remaining_seconds=3600,remaining_num=3600,remaining_den=1)
        del actor['cloud_ritual']
        session.emit('CLOUD_WIND_TRANSFORMED',aid,source=WIND,target_ids=targets,expiry_num=expires.numerator,expiry_den=expires.denominator,
                     text='Wind Walk: travel mist, Fly Speed 40 feet and Hover, for 1 hour.')
    else:
        actor['travel_effects'].pop(WIND,None)
        actor['bundle'].pop('cloud_walker_travel',None)
        session.emit('CLOUD_WIND_ENDED',aid,source=WIND,economy='BONUS_ACTION')
    return True


@hook('journey_properties')
def wind_travel_properties(session, aid):
    held=travel_mist(session,aid)
    if held:
        return {'fly_speed_ft':40,'hover':1,'expiry_num':held['expiry_num'],'expiry_den':held['expiry_den']}
    return None


@hook('journey_step')
def wind_travel_step(session, aid, old, nxt, regions):
    if travel_mist(session,aid):
        return {'supported_kinds':['cliff','river','water','vertical_surface'], 'airborne':True}
    return None


@hook('journey_elapsed')
def wind_elapsed(session, aid, before, seconds, moving):
    actor=session.state['actors'][aid]
    held=travel_mist(session,aid)
    if held:
        left=Fraction(held['expiry_num'],held['expiry_den'])-session.clock()
        if left<=0:
            actor['travel_effects'].pop(WIND,None);actor['bundle'].pop('cloud_walker_travel',None)
            session.emit('CLOUD_WIND_ENDED',aid,source=WIND,reason='one hour elapsed')
        else:
            # A fractional final second remains exact in the journey; combat
            # rounds use the ordinary native six-second boundary clock.
            actor['bundle']['cloud_walker_travel']={**held,'remaining_seconds':(left.numerator+left.denominator-1)//left.denominator,
                'remaining_num':left.numerator,'remaining_den':left.denominator}
    ritual=actor.get('cloud_ritual')
    if ritual and session.clock()>Fraction(ritual['end_num'],ritual['end_den']):
        del actor['cloud_ritual']
        session.emit('CLOUD_WIND_RITUAL_ENDED',aid,source=WIND,reason='completion checkpoint passed without finishing')
    elif ritual and ritual.get('invitations') and session.clock()>before:
        # Willingness is scoped to this completion checkpoint, never a standing
        # ally flag or consent that survives elapsed time or relocation.
        ritual['invitations']={}


@hook('match_initialize')
def bind_wind_walk(engine):
    from ..typed_executor import clock_expiry
    for bundle in engine.typed_bundle_documents:
        receipt=bundle.get('cloud_walker_travel')
        if not receipt or receipt.get('remaining_seconds',0)<=0:
            continue
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None or form(actor,'wind'):
            continue
        rounds=(receipt['remaining_seconds']+5)//6
        engine._apply_condition(actor,FORM,WIND,receipt['source_actor_id'],
            expires_on=clock_expiry(engine,'rounds',rounds),data={
                'mode':'wind','source_cl':receipt['source_cl'],'choice_owner':True,
                'remaining_seconds':receipt['remaining_seconds'],'started_round':engine.state.round_number,
                'remaining_num':receipt.get('remaining_num',receipt['remaining_seconds']),
                'remaining_den':receipt.get('remaining_den',1),
                'fly_speed_ft':40,'flight_hover':1,'label':'Wind Walk: travel mist; end as a Bonus Action'})


@hook('compile_action')
def family_action_numbers(action, info):
    typed=action.parameters.get('typed',{})
    if typed.get('source') not in {STEP,WIND,LEAP,IMMORTAL}:
        return None
    return action.model_copy(update={'parameters':{**action.parameters,'typed':{
        **typed,'numbers':qi_path_numbers(info),
        **({'manual_inline_choice':True} if typed.get('source')==LEAP else {})}}})


@hook('turn_end')
def occupied_cloud_end(engine, actor):
    held=form(actor,'immortal')
    if held is None:
        return
    occupied=actual_occupied(engine,actor)
    if not set(engine._actor_volume(actor)) & set(occupied):
        return
    from ..gate2_runtime_models import DiceSpec
    from .needle import step_to
    destination=nearest_legal(engine,actor)
    if destination is not None:
        step_to(engine,actor,destination,IMMORTAL,forced=True)
    roll=engine.roller.roll(DiceSpec(count=4,sides=10),actor_id=actor.entity_id,reason='CLOUD_IMMORTAL_OCCUPIED_FORCE')
    engine._record_roll(roll)
    engine._append_event('DAMAGE_ROLLED',IMMORTAL,actor_id=actor.entity_id,target_ids=(actor.entity_id,),payload=roll.model_dump(mode='json'))
    engine._commit_damage(actor,roll.total,'FORCE',IMMORTAL,actor.entity_id,
                          getattr(engine,'_active_intent',None),reaction_depth=3)


@hook('defense_description')
def cloud_defense_description(engine, actor):
    held=form(actor)
    if held is None:
        return None
    from ..factory_compiler import _DAMAGE_TYPES
    kinds=([k for k in _DAMAGE_TYPES if k not in {'FORCE','PSYCHIC','VOID'}]
           if held.data['mode']=='immortal' else ['BLUDGEONING','PIERCING','SLASHING'])
    return [{'feature_id':held.source_definition_id,'damage_types':kinds,
             'source':'Cloud Immortal' if held.data['mode']=='immortal' else 'Wind Walk (nonmagical damage)',
             'expires_on':held.expires_on}]


@hook('pass_through_stop')
def cloud_occupied_stop(engine, mover, occupant):
    return True if form(mover,'immortal') else None


@hook('equipment_use_allowed')
def mist_equipment(engine, actor, kind):
    return False if kind in {'weapon','shield'} and form(actor,'wind') else None


@hook('attack_allowed')
def mist_attack(ctx, target, effect):
    return False if form(ctx.actor,'wind') else None


@hook('row_allowed')
def mist_reaction(engine, actor, row):
    if not form(actor,'wind'):
        return None
    from ..effect_harm import rows,classify_effect
    if row.get('block')=='opportunity' or any(classify_effect(r) is True or r.get('type') in {'zone','aura','domain'} for r in rows(row.get('effects') or [])):
        return False
    return None


def carried_pair(engine, left, right):
    return any(c.condition_id==CARRY and c.data.get('carrier_id')==right.entity_id
               for c in left.conditions.values()) or any(
        c.condition_id==CARRY and c.data.get('carrier_id')==left.entity_id for c in right.conditions.values())


@hook('pass_through')
def carried_transit(engine, mover, occupant):
    return 'free' if carried_pair(engine,mover,occupant) else None


@hook('pass_through_stop')
def carried_stop(engine, mover, occupant):
    return True if carried_pair(engine,mover,occupant) else None


@hook('pass_through_allowed')
def leap_cannot_cross_creatures(engine, mover, occupant):
    if any(c.condition_id==SEGMENT for c in mover.conditions.values()) and not carried_pair(engine,mover,occupant):
        return False
    return None


@hook('movement_step_settled')
def carry_arrival(engine, mover, previous, nxt, intent):
    from .needle import step_to
    for passenger in engine.state.actors.values():
        held=next((c for c in passenger.conditions.values() if c.condition_id==CARRY
                   and c.data.get('carrier_id')==mover.entity_id),None)
        if held is None:
            continue
        if mover.position!=nxt:
            return {'stop':True,'source_id':LEAP,'label':'Heavenly Leap was interrupted before the companion could follow.'}
        occupied=engine._occupied_volumes_except(passenger.entity_id,ignore_actor_ids=(mover.entity_id,))
        if not engine.grid.volume_legal(nxt,footprint=engine._footprint(passenger),occupied_cells=occupied):
            return {'stop':True,'source_id':LEAP,'label':f'Heavenly Leap stops: {passenger.display_name} cannot fit along this route.'}
        if not engine.grid.volume_step_legal(passenger.position,nxt,footprint=engine._footprint(passenger),occupied_cells=occupied):
            return {'stop':True,'source_id':LEAP,'label':f'Heavenly Leap stops at a barrier blocking {passenger.display_name}.'}
        step_to(engine,passenger,nxt,held.source_definition_id,forced=False)
    return None


@hook('event',nested=True)
def cloud_lifecycle(engine, event_type, kwargs):
    if event_type not in {'CONDITION_APPLIED','CONDITION_REMOVED','CONCENTRATION_ENDED'}:
        return
    from .life_state import UNCONSCIOUS
    for actor in engine.state.actors.values():
        pending=next((c for c in actor.conditions.values() if c.condition_id==DESCENT),None)
        if pending and not cloud_step_protection(engine,actor):
            remove_instance(engine,actor,pending.instance_id,STEP)
        held=form(actor,'immortal')
        if held and any(c.condition_id in {UNCONSCIOUS,'condition:typed.unconscious','condition:core.unconscious','unconscious'}
                        for c in actor.conditions.values()):
            remove_instance(engine,actor,held.instance_id,IMMORTAL)


@hook('journey_auto_blocked')
def wind_pending_player(session, aid):
    ritual=session.state['actors'][aid].get('cloud_ritual')
    return True if ritual and any(v=='pending' for v in ritual['invitations'].values()) else None


@hook('opportunity_allowed')
def immortal_opportunity(engine, reactor, mover):
    return False if form(mover,'immortal') else None


def nearest_legal(engine, actor):
    """Nearest actual free volume, with stable ties and no hidden identity leak."""
    from ..gate2_runtime_models import Position
    occupied=actual_occupied(engine,actor)
    tops=[a.position.z+engine._footprint(a).width_cells for a in engine.state.actors.values() if a.active]
    tops.extend((top+4)//5 for spans in engine.grid.terrain_spans.get('BLOCKED',{}).values()
                for bottom,top in spans if top is not None)
    tops.extend(r.walk_ft//5+1 for r in engine.grid.roof_surfaces)
    ceiling=max([actor.position.z+1,*tops])
    candidates=[]
    for z in range(ceiling+1):
        for x in range(engine.grid.width):
            for y in range(engine.grid.height):
                p=Position(x=x,y=y,z=z)
                if engine.grid.volume_legal(p,footprint=engine._footprint(actor),occupied_cells=occupied):
                    candidates.append(p)
    return min(candidates,key=lambda p:(engine.grid.distance_ft(actor.position,p),p.z,p.y,p.x),default=None)


@hook('event',nested=True)
def return_from_cloud(engine, event_type, kwargs):
    ended=kwargs.get('ended_effect') or {}
    if event_type!='CONDITION_REMOVED' or ended.get('condition_id')!=FORM:
        return
    from .needle import step_to
    for aid in kwargs.get('target_ids') or ():
        actor=engine.state.actors.get(aid)
        if actor is None or not actor.active:
            continue
        occupied=engine._occupied_volumes_except(aid)
        if not engine.grid.volume_legal(actor.position,footprint=engine._footprint(actor),occupied_cells=occupied):
            destination=nearest_legal(engine,actor)
            if destination is not None:
                step_to(engine,actor,destination,ended['source_definition_id'],forced=True)


@hook('journey_state_changed')
def detach_wind_at_combat_entry(session, aid):
    if session.state['phase']!='combat':
        return
    actor=session.state['actors'][aid]
    if travel_mist(session,aid):
        # journey_start_combat has already copied the produced bundle into the
        # encounter. Do not retain a stale travel grant that could resurrect an
        # effect dismissed or lost at zero HP in that encounter.
        actor['travel_effects'].pop(WIND,None)
        actor['bundle'].pop('cloud_walker_travel',None)
        session.emit('CLOUD_WIND_BOUND_TO_ENCOUNTER',aid,source=WIND)


@hook('shared_space')
def cloud_shared_space(engine, left, right):
    if not (form(left,'immortal') or form(right,'immortal') or carried_pair(engine,left,right)):
        return None
    return True if set(engine._actor_volume(left)) & set(engine._actor_volume(right)) else None


def actual_occupied(engine, actor):
    """Physical occupancy for mandatory recovery, including authorized sharing."""
    return {cell for other in engine.state.actors.values()
            if other.entity_id!=actor.entity_id and other.active and engine._on_battlefield(other)
            for cell in engine._actor_volume(other)}


@hook('journey_encounter_export')
def wind_encounter_export(session, engine, creature, effects_ended):
    """Export only the real Wind Walk instance, never re-create a dismissed form."""
    held=form(creature,'wind')
    if held is None:
        return None
    actor=session.state['actors'][creature.entity_id]
    if not effects_ended and creature.current_hp>0:
        elapsed=max(0,engine.state.round_number-int(held.data['started_round']))*6
        left=max(Fraction(0),Fraction(held.data['remaining_num'],held.data['remaining_den'])-elapsed)
        if left:
            end=session.clock()+left
            receipt={'source_actor_id':held.source_actor_id,'source_cl':held.data['source_cl'],
                     'expiry_num':end.numerator,'expiry_den':end.denominator}
            actor['travel_effects'][WIND]=receipt
            actor['cloud_walker_saved']={}
            actor['bundle']['cloud_walker_travel']={**receipt,'remaining_seconds':(left.numerator+left.denominator-1)//left.denominator,
                'remaining_num':left.numerator,'remaining_den':left.denominator}
            session.emit('CLOUD_WIND_RETURNED_TO_TRAVEL',creature.entity_id,source=WIND,
                         remaining_num=left.numerator,remaining_den=left.denominator,condition_instance=held.instance_id,
                         match_id=session.state['match_id'])
    return [held.instance_id]


@hook('journey_persist')
def wind_persist(session, aid):
    held=travel_mist(session,aid)
    # An explicit empty receipt is necessary to retire a previously persisted
    # source state when the next journey saves after dismissal or expiration.
    if held or 'cloud_walker_saved' in session.state['actors'][aid]:
        left=Fraction(held['expiry_num'],held['expiry_den'])-session.clock() if held else 0
        return {'cloud_walker_saved':{**held,'remaining_num':left.numerator,'remaining_den':left.denominator} if held and left>0 else {}}
    return None


@hook('journey_initialize')
def wind_new_journey(session, aid):
    actor=session.state['actors'][aid]
    receipt=actor.get('cloud_walker_saved')
    if not receipt:
        return
    # A completed journey exports remaining time, not its obsolete local clock.
    left=Fraction(receipt.get('remaining_num',0),receipt.get('remaining_den',1))
    if left<=0:
        return
    end=session.clock()+left
    held={k:v for k,v in receipt.items() if k not in {'remaining_num','remaining_den'}}
    held.update(expiry_num=end.numerator,expiry_den=end.denominator)
    actor['travel_effects'][WIND]=held
    actor['bundle']['cloud_walker_travel']={**held,'remaining_seconds':(left.numerator+left.denominator-1)//left.denominator,
        'remaining_num':left.numerator,'remaining_den':left.denominator}
    action=wind_end_definition(aid)
    if action.source_definition_id not in actor['bundle']['actor_template']['action_ids']:
        actor['bundle']['action_catalog'].append(action.model_dump(mode='json'))
        actor['bundle']['actor_template']['action_ids'].append(action.source_definition_id)
