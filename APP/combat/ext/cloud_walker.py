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
from ..journey_falling import request_fall

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
def feather_distance_multiplier(engine, actor):
    if FEATHER not in ownership(engine, actor).get('features', ()):
        return None
    return 3


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
            'source_pb':int(ctx.numbers['pb']),'source_key_mod':int(ctx.numbers['key_mod']),
            'body_mode':'replacement','body_mode_temporary':1,'anatomy_source':WIND if mode=='wind' else IMMORTAL,
            **({'remaining_num':3600,'remaining_den':1,'started_round':ctx.engine.state.round_number,
                'started_slot':ctx.engine.state.current_slot_index,'clock_slots':len(ctx.engine.state.initiative_order)} if mode=='wind' else {}),
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
        return (engine._effective_speed(actor)>0 and actor.turn_flags.get('cloud_leap') != stamp(engine)
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


def passenger_edge(engine,passenger,previous,destination,occupied):
    """Physical passenger route, using its own body and every shared boundary."""
    from ..voluntary_movement import edge_allowed
    from .cloud_walker_environment import boundaries
    return (engine.grid.volume_legal(destination,footprint=engine._footprint(passenger),occupied_cells=occupied)
            and engine.grid.volume_step_legal(previous,destination,footprint=engine._footprint(passenger),occupied_cells=occupied)
            and edge_allowed(engine,passenger,previous,destination)
            and boundaries(engine,passenger,previous,destination,leap=True) is not False)


def companion_route(engine,passenger,carrier,path,destination):
    """Pure admission before consent/payment; no illegal passenger transit."""
    occupied=engine._occupied_volumes_except(passenger.entity_id,observed=True,ignore_actor_ids=(carrier.entity_id,))
    return (all(passenger_edge(engine,passenger,old,nxt,occupied) for old,nxt in zip(path,path[1:]))
            and bool(adjacent_landings(engine,passenger,destination,carrier=carrier)))


def landing_routes(engine, passenger, destination, *, observed=True, carrier=None):
    """All adjacent body placements, with physical routes out of sharing.

    Footprint bounds determine the search region; there is no option-count cap.
    Sharing permits the carrier's volume during transit only. Every other
    collision and source boundary is checked for the passenger's actual body.
    """
    from collections import deque
    from ..gate2_runtime_models import Position
    viewer=carrier or passenger
    occupied=(engine._occupied_volumes_except(viewer.entity_id,observed=True,ignore_actor_ids=(passenger.entity_id,))
              if observed else {cell for other in engine.state.actors.values()
                  if other.entity_id not in {passenger.entity_id,viewer.entity_id} and other.active
                  and engine._on_battlefield(other) for cell in engine._actor_volume(other)})
    carrier_cells=set(engine._actor_volume(viewer,destination))
    shape=engine._footprint(passenger)
    margin=max(shape.width_cells,shape.height_cells)
    bounds=[(min(c[i] for c in carrier_cells)-margin,max(c[i] for c in carrier_cells)+1) for i in range(3)]
    routes={destination:(destination,)};pending=deque([destination]);out={}
    while pending:
        old=pending.popleft()
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    if not (dx or dy or dz):continue
                    values=(old.x+dx,old.y+dy,old.z+dz)
                    if values[2]<0 or not all(lo<=v<=hi for v,(lo,hi) in zip(values,bounds)):continue
                    if not engine.grid.in_bounds(values[:2]):continue
                    cell=Position(x=values[0],y=values[1],z=values[2])
                    if cell in routes or not passenger_edge(engine,passenger,old,cell,occupied):continue
                    route=routes[old]+(cell,);routes[cell]=route;pending.append(cell)
                    volume=set(engine._actor_volume(passenger,cell))
                    if not volume & carrier_cells and engine._distance_actor_to_actor(viewer,passenger,
                            actor_position=destination,target_position=cell)<=5:
                        out[cell]=route
    return out


def adjacent_landings(engine, passenger, destination, *, observed=True, carrier=None):
    return list(landing_routes(engine,passenger,destination,observed=observed,carrier=carrier))


@effect('cloud_walker_leap')
def leap(ctx, row):
    from ..flight import reachable
    from .cloud_walker_environment import visible_destination
    from ..granted_movement import Route
    from .needle import ask, checkpoint_id, cell_id
    from ..fact_consent_admission import admit_choice, digest
    from .effect_durations import token
    from ..relations import relation
    from ..typed_reactions import physical_melee_reach
    from ..target_knowledge import knowledge
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get('cloud_leap') == stamp(engine):
        return
    # This is a real scoped movement capability, not a temporary engine patch.
    # It is removed after the segment, letting ordinary falling settle then.
    engine._apply_condition(actor, SEGMENT, ctx.source, actor.entity_id, expires_on='END_OF_CURRENT_TURN',
        data={'source_cl':int(ctx.numbers['cl']),'source_pb':int(ctx.numbers['pb']),'source_key_mod':int(ctx.numbers['key_mod']),'label':'Heavenly Leap movement segment'})
    segment=next(c for c in actor.conditions.values() if c.condition_id==SEGMENT)
    try:
        from ..read_queries import candidate_pass
        with candidate_pass(engine):
            paths={cell_id(p):(p,path) for p,(path,cost,mode) in reachable(engine,actor,grant_ft=120,mode='impulse').items()
                   if p!=actor.position and engine.grid.distance_ft(actor.position,p)<=120
                   and engine._line_of_sight_actor_to_cell(actor,p) and visible_destination(engine,actor,p)
                   and engine.grid.volume_legal(p,footprint=engine._footprint(actor),
                       occupied_cells=engine._occupied_volumes_except(actor.entity_id,observed=True))}
        if not paths:
            raise ValueError('Heavenly Leap needs a reachable visible unoccupied destination within 120 feet.')
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
                       and companion_route(engine,a,actor,path,destination)}
            if available:
                pick=ask(engine,ctx.intent,checkpoint_id(engine,'CLOUD_PASSENGER',actor.entity_id),actor,
                    'choice:needle.cloud_leap_companion',sorted(available),preferred=[],allow_decline=True,default='decline',
                    labels={aid:f'Carry {a.display_name} (2 Qi)' for aid,a in available.items()},
                    name='Carry a Companion',prompt='Declare a companion before moving, or travel alone. '
                    'The companion must consent and fit beside your destination; carrying costs 2 Qi.')
                if pick:
                    other=available[pick[0]]
                    own_view=knowledge(engine,other,actor)
                    automatic=(['accept'] if relation(engine,other,actor)=='ALLY'
                               and own_view is not None and own_view.mode=='DIRECT' else ['refuse'])
                    consent=admit_choice(ctx,other,LEAP,'heavenly_leap_carry',
                        digest({'caster':actor.entity_id,'passenger':other.entity_id,'turn':stamp(engine),
                                'destination':destination.model_dump(mode='json')}), ['accept','refuse'],
                        labels={'accept':'Accept being carried','refuse':'Refuse being carried'},
                        prompt=f'Let {actor.display_name} carry {other.display_name} to ({destination.x}, {destination.y}), '
                        f'{destination.z*5} feet high, without provoking? Carrying costs the caster 2 additional Qi.',
                        expires_on=token('end',actor.entity_id,actor.turns_started),readers=[actor.entity_id],
                        automatic_options=automatic)
                    if consent and consent['value']=='accept':
                        cells=adjacent_landings(engine,other,destination,carrier=actor)
                        options={cell_id(p):p for p in cells}
                        selected=ask(engine,ctx.intent,checkpoint_id(engine,'CLOUD_LANDING',other.entity_id),actor,
                            'choice:needle.cloud_leap_landing',sorted(options),preferred=sorted(options)[:1],
                            labels={k:f'Place {other.display_name} at ({p.x}, {p.y}), {p.z*5} feet high' for k,p in options.items()},
                            name='Carry a Companion',prompt='Choose the companion’s unoccupied adjacent destination (2 Qi).')
                        if selected:
                            passenger,landing=other,options[selected[0]]
        carry_receipt=None
        if passenger is not None and not adjacent_landings(engine,passenger,destination,observed=False,carrier=actor):
            passenger=None;landing=None
        if passenger is not None:
            # A carried creature is physically present for every committed step.
            # The scoped receipt authorizes boarding/sharing only with this
            # carrier; it never grants passage through unrelated creatures.
            engine._apply_condition(passenger,CARRY,ctx.source,actor.entity_id,
                expires_on='END_OF_CURRENT_TURN',data={'carrier_id':actor.entity_id,'source_cl':int(ctx.numbers['cl']),
                    'source_pb':int(ctx.numbers['pb']),'source_key_mod':int(ctx.numbers['key_mod']),'carry_released':0,
                    'label':f'Carried by {actor.display_name} during Heavenly Leap'})
            carry_receipt=next(c for c in passenger.conditions.values() if c.condition_id==CARRY)
            with candidate_pass(engine):
                board=reachable(engine,passenger,grant_ft=120,mode='impulse').get(actor.position)
            if board is None:
                remove_instance(engine,passenger,carry_receipt.instance_id,ctx.source)
                carry_receipt=None;passenger=None
            else:
                engine._spend_resource(actor,QI,2,ctx.source)
                engine.move_path(passenger,Route(tuple(board[0]),'impulse'),ctx.source,kind='granted',
                                 feet=120,intent=ctx.intent,provokes=False)
                if passenger.position!=actor.position:
                    remove_instance(engine,passenger,carry_receipt.instance_id,ctx.source)
                    carry_receipt=None;passenger=None
        actor.turn_flags['cloud_leap']=stamp(engine)
        departure=actor.position
        before_move=len(engine.events)
        try:
            engine.move_path(actor,Route(tuple(path),'impulse'),ctx.source,kind='granted',feet=120,
                             intent=ctx.intent,provokes=False)
            recover_leap(ctx,departure,destination,path,before_move,passenger)
            if passenger is not None:
                # Source failure recovery has settled the carrier's actual
                # arrival; the companion is placed beside that legal space.
                routes=landing_routes(engine,passenger,actor.position,observed=False,carrier=actor)
                choices=list(routes)
                if choices:
                    place=landing if actor.position==destination and landing in choices else min(choices,
                        key=lambda p:(engine.grid.distance_ft(actor.position,p),p.z,p.y,p.x))
                    route=routes[place]
                    feet=sum(engine.grid.distance_ft(old,nxt) for old,nxt in zip(route,route[1:]))
                    engine.move_path(passenger,Route(tuple(route),'impulse'),ctx.source,
                                     kind='granted',feet=feet,intent=ctx.intent,provokes=False)
                else:
                    place=nearest_legal(engine,passenger)
                    if place is not None:
                        from .needle import step_to
                        step_to(engine,passenger,place,ctx.source,forced=True)
        finally:
            import sys
            if sys.exc_info()[0] is None:
                if carry_receipt is not None:
                    engine._update_condition_data(passenger,carry_receipt,{**carry_receipt.data,'carry_released':1},ctx.source)
                remove_instance(engine,actor,segment.instance_id,ctx.source)
                if carry_receipt is not None:
                    remove_instance(engine,passenger,carry_receipt.instance_id,ctx.source)
    finally:
        import sys
        if sys.exc_info()[0] is None:
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
        before=actor.position
        if not displace(engine,actor,-1,STEP,settle_after=False,trigger_entry=True):
            break
        if actor.position!=before.model_copy(update={'z':before.z-1}) or not actor.active or actor.current_hp<=0 or not cloud_step_protection(engine,actor):
            break
    if not supported(engine,actor) and actor.active and actor.current_hp>0 and cloud_step_protection(engine,actor):
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


def _journey_actor_cells(session, aid):
    """Footprint-aware occupied cell set for a journey actor, including altitude.

    Uses the actor's recorded size category to expand its anchor position into
    every cell the creature actually occupies, so range checks see the nearest
    occupied cells rather than a single anchor corner.
    """
    from ..dynamic_size import CATEGORIES, WIDTHS, category_name
    actor = session.state['actors'][aid]
    pos = actor['position']
    width = WIDTHS[CATEGORIES.index(category_name(actor.get('size')))]
    z = pos.get('z', 0)
    return [(pos['x'] + dx, pos['y'] + dy, z) for dx in range(width) for dy in range(width)]


def near_ritual(session, caster, target):
    """Footprint-aware 10-foot ritual range, including altitude.

    Shared with the invitation, consent and completion paths so a Large or
    multi-square creature's nearest occupied cell decides range, matching the
    native creature-to-creature distance used in combat.
    """
    return session.grid.distance_between_cell_sets_ft(
        _journey_actor_cells(session, caster),
        _journey_actor_cells(session, target)) <= 10


def wind_scope(session, caster, target):
    from ..fact_consent_admission import digest
    ritual=session.state['actors'][caster]['cloud_ritual']
    return digest({'source':WIND,'caster':caster,'target':target,
                   'ritual_id':ritual.get('ritual_id',str(ritual['end_num'])+'/'+str(ritual['end_den'])),
                   'duration_seconds':3600,'completion_range_ft':10})


def wind_answers(session,caster):
    from ..fact_consent_admission import read
    ritual=session.state['actors'][caster].get('cloud_ritual')
    if not ritual:return {}
    answers={}
    for target in ritual['invitations']:
        record=read(session,WIND,target,'wind_walk_willingness',wind_scope(session,caster,target),caster)
        answers[target]=('accept' if record['value']==1 else 'refuse') if record else 'pending'
    return answers


@hook('fact_admission_schema')
def wind_admission(session,source,subject,kind):
    if source!=WIND or kind!='wind_walk_willingness':return None
    if not any(journey_owned(session,caster,WIND) and subject in actor.get('cloud_ritual',{}).get('invitations',{})
               for caster,actor in session.state['actors'].items()):return None
    return {'value_type':'flag','maximum_seconds':1,
            'description':'Consent to this exact Wind Walk ritual at its completion checkpoint.'}


@hook('journey_options')
def wind_options(session, aid):
    if session.state['phase']!='travel':
        return None
    actor=session.state['actors'][aid]
    options=[]
    def add(kind,payload,label,auto=0):
        options.append({'id':kind+':'+str(len(options)),'kind':kind,'payload':payload,
                        'label':label,'auto_select':auto})
    if travel_mist(session,aid) and not actor['incapacitated']:
        add('cloud_wind_end',{},f'{actor["name"]}: end Wind Walk on yourself as a Bonus Action (no Qi).')
    ritual=actor.get('cloud_ritual')
    if journey_owned(session,aid,WIND) and not actor['incapacitated'] and not ritual and actor['resources'].get(QI,0)>=5:
        add('cloud_wind_begin',{},f'{actor["name"]}: begin Wind Walk, a 10-minute ritual costing 5 Qi; travel mist lasts 1 hour.')
    if ritual and not actor['incapacitated'] and session.clock()==Fraction(ritual['end_num'],ritual['end_den']):
        count=sum(answer in {'pending','accept'} and near_ritual(session,aid,target)
                  for target,answer in wind_answers(session,aid).items())
        pb=next(r['numbers']['pb'] for r in actor['bundle']['typed_passives'] if r.get('block')=='cloud_walker')
        if count<pb:
            for target,other in sorted(session.state['actors'].items()):
                if target!=aid and target not in ritual['invitations'] and near_ritual(session,aid,target):
                    add('cloud_wind_invite',{'target_id':target},f'Wind Walk: ask {other["name"]} to become travel mist for 1 hour; no additional Qi.')
        for target in ritual['invitations']:
            add('cloud_wind_exclude',{'target_id':target},f'Wind Walk: leave {session.state["actors"][target]["name"]} out of this ritual; no additional Qi.')
        if count<=pb and all(v!='pending' for v in wind_answers(session,aid).values()):
            add('cloud_wind_finish',{},f'{actor["name"]}: finish Wind Walk; transform yourself and consenting creatures still within 10 feet for 1 hour.')
    for caster,other in sorted(session.state['actors'].items()):
        r=other.get('cloud_ritual')
        if r and aid in r['invitations'] and near_ritual(session,caster,aid):
            for accept,verb in ((True,'Accept'),(False,'Decline')):
                add('cloud_wind_reply',{'caster_id':caster,'accept':accept},
                    f'{verb} {other["name"]}’s Wind Walk: {actor["name"]} becomes travel mist for 1 hour. '
                    'Fly 40 feet with Hover; no attacks, harmful features, fields, auras, Domains, weapons, shields or two-handed manipulation.',
                    auto=int(actor['control_mode']=='LOCAL_AUTO' and accept and wind_answers(session,caster).get(aid)=='pending'))
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
        from ..fact_consent_admission import digest
        actor['cloud_ritual']={'end_num':end.numerator,'end_den':end.denominator,'invitations':{},
            'ritual_id':digest({'caster':aid,'sequence':len(session.state['events'])+1,'end_num':end.numerator,'end_den':end.denominator})}
        session.emit('CLOUD_WIND_RITUAL',aid,source=WIND,qi_cost=5,end_num=end.numerator,end_den=end.denominator)
    elif kind=='cloud_wind_invite':
        actor['cloud_ritual']['invitations'][payload['target_id']]='pending'
        session.emit('CLOUD_WIND_INVITATION',aid,source=WIND,target_id=payload['target_id'],expires_at=int(session.clock())+1)
    elif kind=='cloud_wind_reply':
        from ..fact_consent_admission import declare
        caster=payload['caster_id'];ritual=session.state['actors'][caster]['cloud_ritual']
        receipt=declare(session,aid,{'source':WIND,'subject':aid,'kind':'wind_walk_willingness',
            'scope':wind_scope(session,caster,aid),'value':int(payload['accept']),
            'expires_at':int(session.clock())+1,'readers':[caster]})
        ritual['invitations'][aid]=wind_answers(session,caster)[aid]
        session.emit('CLOUD_WIND_CONSENT',aid,source=WIND,caster_id=caster,receipt_id=receipt)
    elif kind=='cloud_wind_exclude':
        del actor['cloud_ritual']['invitations'][payload['target_id']]
        session.emit('CLOUD_WIND_INVITATION_WITHDRAWN',aid,source=WIND,target_id=payload['target_id'])
    elif kind=='cloud_wind_finish':
        ritual=actor['cloud_ritual'];expires=session.clock()+3600
        targets=[aid,*[target for target,v in wind_answers(session,aid).items() if v=='accept' and near_ritual(session,aid,target)]]
        transformed=[]
        for target in targets:
            recipient=session.state['actors'][target]
            snapshot=recipient.get('encounter_snapshot')
            if snapshot is not None and snapshot['current_hp']<=0:
                session.emit('CLOUD_WIND_ENDED',target,source=WIND,reason='zero Hit Points')
                continue
            origin=next(r for r in actor['bundle']['typed_passives'] if r.get('block')=='cloud_walker')
            receipt={'source_actor_id':aid,'expiry_num':expires.numerator,'expiry_den':expires.denominator,
                     'source_cl':origin['cl'],'source_pb':int(origin['numbers']['pb']),
                     'source_key_mod':int(origin['numbers']['key_mod'])}
            transformed.append(target)
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
            save_wind_state(session,target)
        del actor['cloud_ritual']
        session.emit('CLOUD_WIND_TRANSFORMED',aid,source=WIND,target_ids=transformed,expiry_num=expires.numerator,expiry_den=expires.denominator,
                     text='Wind Walk: travel mist, Fly Speed 40 feet and Hover, for 1 hour.')
    else:
        actor['travel_effects'].pop(WIND,None)
        actor['bundle'].pop('cloud_walker_travel',None)
        session.emit('CLOUD_WIND_ENDED',aid,source=WIND,economy='BONUS_ACTION')
        request_fall(session,aid,WIND)
    save_wind_state(session,aid)
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
            request_fall(session,aid,WIND)
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
    save_wind_state(session,aid)


@hook('match_initialize')
def bind_wind_walk(engine):
    from ..asset_anchor_runtime import remaining_lifetime_token
    for bundle in engine.typed_bundle_documents:
        receipt=bundle.get('cloud_walker_travel')
        if not receipt or receipt.get('remaining_seconds',0)<=0:
            continue
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None or form(actor,'wind'):
            continue
        # The encounter compiler derives its catalog from the immutable actor
        # template, not the journey bundle's mutable catalog. Install the
        # ritual-produced continuation in the native encounter catalog before
        # the additional_actions hook can expose its ID.
        action=wind_end_definition(actor.entity_id)
        engine.action_catalog[action.source_definition_id]=action
        if action.source_definition_id not in actor.action_ids:
            actor.action_ids=(*actor.action_ids, action.source_definition_id)
        left=Fraction(receipt.get('remaining_num',receipt['remaining_seconds']),receipt.get('remaining_den',1))
        engine._apply_condition(actor,FORM,WIND,receipt['source_actor_id'],
            expires_on=remaining_lifetime_token(engine,left),data={
                'mode':'wind','source_cl':receipt['source_cl'],'choice_owner':True,
                'body_mode':'replacement','body_mode_temporary':1,'anatomy_source':WIND,
                **{k:receipt[k] for k in ('source_pb','source_key_mod') if k in receipt},
                'remaining_seconds':receipt['remaining_seconds'],'started_round':engine.state.round_number,
                'started_slot':engine.state.current_slot_index,'clock_slots':len(engine.state.initiative_order),
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
    kinds=([k for k in ('ACID','BLUDGEONING','COLD','FIRE','LIGHTNING','NECROTIC',
                         'PIERCING','POISON','RADIANT','SLASHING','THUNDER')]
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
    if any(c.condition_id in {SEGMENT,CARRY} for c in mover.conditions.values()) and not carried_pair(engine,mover,occupant):
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
        if not passenger_edge(engine,passenger,passenger.position,nxt,occupied):
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
    return True if ritual and any(v=='pending' for v in wind_answers(session,aid).values()) else None


@hook('opportunity_allowed')
def immortal_opportunity(engine, reactor, mover):
    return False if form(mover,'immortal') or form(reactor,'wind') else None


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
    if event_type!='CONDITION_REMOVED' or ended.get('condition_id') not in {FORM,CARRY}:
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
        save_wind_state(session,aid)
        return
    actor=session.state['actors'][aid]
    if travel_mist(session,aid):
        # journey_start_combat has already copied the produced bundle into the
        # encounter. Do not retain a stale travel grant that could resurrect an
        # effect dismissed or lost at zero HP in that encounter.
        actor['travel_effects'].pop(WIND,None)
        actor['bundle'].pop('cloud_walker_travel',None)
        save_wind_state(session,aid)
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


@hook('journey_encounter_settled')
def wind_encounter_export(session, aid, engine, creature):
    """Export only the real Wind Walk instance, never re-create a dismissed form."""
    held=form(creature,'wind')
    actor=session.state['actors'][aid]
    ended=False
    for event in reversed(session.state['events']):
        if event['kind']=='ENTER_COMBAT':break
        if event['kind']=='ENCOUNTER_EFFECTS_RESOLVED' and event['actor_id']==aid:ended=True
    if held is None:
        save_wind_state(session,aid)
        return
    if not ended and creature.current_hp>0:
        left=wind_remaining(engine,held)
        if left:
            end=session.clock()+left
            receipt={'source_actor_id':held.source_actor_id,'source_cl':held.data['source_cl'],
                     **{k:held.data[k] for k in ('source_pb','source_key_mod') if k in held.data},
                     'expiry_num':end.numerator,'expiry_den':end.denominator}
            actor['travel_effects'][WIND]=receipt
            actor['cloud_walker_saved']={}
            actor['bundle']['cloud_walker_travel']={**receipt,'remaining_seconds':(left.numerator+left.denominator-1)//left.denominator,
                'remaining_num':left.numerator,'remaining_den':left.denominator}
            session.emit('CLOUD_WIND_RETURNED_TO_TRAVEL',creature.entity_id,source=WIND,
                         remaining_num=left.numerator,remaining_den=left.denominator,condition_instance=held.instance_id,
                         match_id=session.state['match_id'])
    save_wind_state(session,aid)


@hook('journey_snapshot_actor')
def wind_snapshot_actor(creature, session, aid, engine):
    held=form(creature,'wind')
    if held is None:return None
    snapshot=creature.model_copy(deep=True)
    del snapshot.conditions[held.instance_id]
    return snapshot


def save_wind_state(session, aid):
    held=travel_mist(session,aid)
    # An explicit empty receipt is necessary to retire a previously persisted
    # source state when the next journey saves after dismissal or expiration.
    actor=session.state['actors'][aid]
    if held or WIND in actor.get('source_states',{}) or 'cloud_walker_saved' in actor:
        left=Fraction(held['expiry_num'],held['expiry_den'])-session.clock() if held else 0
        actor.setdefault('source_states',{})[WIND]=({**held,'remaining_num':left.numerator,'remaining_den':left.denominator}
                                                  if held and left>0 else {})
    return None


@hook('journey_initialize')
def wind_new_journey(session, aid):
    actor=session.state['actors'][aid]
    receipt=actor.get('source_states',{}).get(WIND,actor.get('cloud_walker_saved'))
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


@hook('journey_scene_end')
def cloud_scene_end(session, previous, current):
    """Only the native table-owner Scene boundary restores this printed use."""
    for aid,actor in session.state['actors'].items():
        if not journey_owned(session,aid,IMMORTAL):continue
        restored=[]
        for action in actor['bundle']['action_catalog']:
            if action.get('parameters',{}).get('typed',{}).get('source')!=IMMORTAL:continue
            for rid,amount in action.get('costs',()):
                if rid.startswith('resource:uses.') and rid in actor['resources']:
                    actor['resources'][rid]=1;restored.append(rid)
        if restored:
            actor.setdefault('source_states',{})[IMMORTAL]={'scene_id':current}
            session.emit('CLOUD_IMMORTAL_SCENE_RECHARGED',aid,source=IMMORTAL,
                         previous_scene=previous,next_scene=current)


def wind_remaining(engine, held):
    """Exact source-time conversion from the existing fixed round/slot clock.

    One complete round is six seconds. The native initiative slots are stable;
    the source records its application slot so moving between journey and combat
    cannot round a fractional remaining duration up to another full round.
    """
    slots=max(1,int(held.data.get('clock_slots') or len(engine.state.initiative_order)))
    elapsed=Fraction(6*(engine.state.round_number-int(held.data['started_round'])))
    elapsed+=Fraction(6*(engine.state.current_slot_index-int(held.data.get('started_slot',0))),slots)
    return max(Fraction(0),Fraction(held.data['remaining_num'],held.data['remaining_den'])-max(Fraction(0),elapsed))


def expire_wind_clock(engine):
    for creature in engine.state.actors.values():
        held=form(creature,'wind')
        if held and 'remaining_num' in held.data and wind_remaining(engine,held)<=0:
            remove_instance(engine,creature,held.instance_id,WIND)


@hook('turn_start',priority=-99)
def wind_clock_start(engine, actor):
    expire_wind_clock(engine)


@hook('nominal_slot_boundary')
def wind_clock_omitted(engine, actor, checkpoint):
    if checkpoint=='START_OF_TURN':expire_wind_clock(engine)


@hook('movement_step_capability')
def leap_impulse_step(engine,actor,previous,destination,mode):
    if mode!='impulse':return None
    return True if any(c.condition_id==SEGMENT or (c.condition_id==CARRY and not c.data.get('carry_released'))
                       for c in actor.conditions.values()) else None


@hook('support_surface')
def leap_segment_support(engine,actor,position):
    # Defer ordinary falling until this physical movement segment settles. This
    # grants neither a Fly Speed nor Hover nor a permanent/harvestable platform.
    return True if any(c.condition_id==SEGMENT or (c.condition_id==CARRY and not c.data.get('carry_released'))
                       for c in actor.conditions.values()) else None


def recover_leap(ctx, origin, destination, path, before, passenger):
    """Shared Qi R4 interrupted transit, after native committed movement only.

    A source-owned suppression receipt implements the more specific Cloud Walker
    gravity failure. Other interruptions after departure keep payment, recover
    to the nearest legal origin-side space and deal the printed unrealized dice.
    Initial rejection is handled transactionally before departure, without harm.
    """
    engine,actor=ctx.engine,ctx.actor
    receipt=next((e for e in reversed(engine.events[before:]) if e.event_type=='MOVEMENT_COMMITTED'
                  and e.actor_id==actor.entity_id and e.source_definition_id==ctx.source),None)
    if actor.position==destination or receipt is None or not receipt.payload.get('interrupted'):
        return
    if len(receipt.payload.get('path',()))<2:
        return
    # The exact native suppression records its source-specific failure branch.
    segments={c.instance_id for c in actor.conditions.values() if c.condition_id==SEGMENT
              and c.source_definition_id==ctx.source}
    suppressed=next((c for c in actor.conditions.values() if c.condition_id=='condition:typed.cloud_route_suppressed'
                     and c.data.get('grant_id') in segments),None)
    if suppressed is not None and suppressed.data.get('failure_kind')=='gravity':
        engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=actor.entity_id,
            payload={'route_failure':'fall','opposing_source':suppressed.source_definition_id,
                     'label':'The higher-authority gravity field stops Heavenly Leap; both travelers begin falling.'})
        return
    from ..gate2_runtime_models import Position,DiceSpec
    from .needle import step_to
    occupied=actual_occupied(engine,actor)
    prefix=[Position.model_validate(p) for p in receipt.payload['path']]
    safe=[p for p in prefix if engine.grid.volume_legal(p,footprint=engine._footprint(actor),occupied_cells=occupied)]
    if safe:
        recovery=min(safe,key=lambda p:(engine.grid.distance_ft(actor.position,p),engine.grid.distance_ft(origin,p),p.z,p.y,p.x))
    else:
        candidates=[Position(x=x,y=y,z=origin.z) for x in range(engine.grid.width) for y in range(engine.grid.height)]
        recovery=min((p for p in candidates if engine.grid.volume_legal(p,footprint=engine._footprint(actor),occupied_cells=occupied)
                      and engine.grid.line_of_physical_transmission(origin,p)),
                     key=lambda p:(engine.grid.distance_ft(origin,p),p.y,p.x),default=None)
    if recovery is not None:
        step_to(engine,actor,recovery,ctx.source,forced=True)
        if passenger is not None:step_to(engine,passenger,recovery,ctx.source,forced=True)
    # Native receipt path counts actual geometric travel, independent of terrain.
    unrealized=max(0,(len(path)-len(prefix))*engine.grid.square_size_ft)
    dice=min(10,unrealized//10)
    engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=actor.entity_id,
        payload={'route_failure':'origin_side','unrealized_ft':unrealized,
                 'label':f'Heavenly Leap was interrupted: return to the nearest legal origin-side space; {dice}d6 Force damage.'})
    for target in (actor,passenger):
        if target is None or not dice:continue
        roll=engine.roller.roll(DiceSpec(count=dice,sides=6),actor_id=target.entity_id,reason='CLOUD_LEAP_INTERRUPTED_FORCE')
        engine._record_roll(roll)
        engine._append_event('DAMAGE_ROLLED',ctx.source,actor_id=actor.entity_id,target_ids=(target.entity_id,),payload=roll.model_dump(mode='json'))
        engine._commit_damage(target,roll.total,'FORCE',ctx.source,actor.entity_id,ctx.intent,reaction_depth=3)


@hook('button_description')
def cloud_button_description(row):
    parameters=row.get('parameters') or {}
    source=(parameters.get('typed') or {}).get('source')
    if parameters.get('cloud_end_wind'):
        return 'Bonus Action, no Qi: end Wind Walk on yourself and return to your ordinary body. Unsupported flight then falls normally.'
    if source==STEP:
        return ('Bonus Action, 2 Qi; Concentration, up to 1 minute. Fly Speed 20 feet without Hover. '
            'Opportunity Attacks against you have Disadvantage; ignore nonmagical difficult terrain. '
            'You may stand on mist, smoke, rain and ordinary clouds during your turn. If you end a turn airborne '
            'without moving at least 5 feet that turn, descend up to 60 feet, landing standing on support. '
            'If still unsupported, remain airborne until your next turn starts; move again or begin falling.')
    if source==LEAP:
        return ('Bonus Action, 3 Qi, once per turn: move physically to one visible unoccupied destination within 120 feet '
            'without provoking Opportunity Attacks. Cross air, liquids and vertical surfaces and pass over creatures; '
            'do not pass through creatures, solid barriers, Total Cover, sealed Formations or undersized spaces. '
            'Declare one willing companion within reach before departure; carrying costs 2 extra Qi and requires '
            'an unoccupied adjacent landing. Cloud Immortal waives only your 3 Qi cost. This movement is not teleportation.')
    if source==IMMORTAL:
        return ('Bonus Action, 8 Qi, once per scene; living cloud for 1 minute. Fly Speed 60 feet and Hover. '
            'Resistance to all damage except Force, Psychic and Void. Ignore difficult terrain, move through creatures '
            'as difficult terrain, and pass through openings at least 1 inch wide; airtight barriers and solid matter block you. '
            'Do not provoke Opportunity Attacks. Physical Grappled or Restrained effects of no higher Source CL cannot hold you. '
            'Cloud Step is active without Concentration. Use Heavenly Leap once each turn without its 3 Qi cost; '
            'a companion still costs 2 Qi. End your turn in an occupied space: move to the nearest legal space and take '
            '4d10 Force damage, which Cloud Walker features cannot reduce.')
    return None


@hook('movement_edge_allowed',present=lambda engine:any(c.condition_id==CARRY for a in engine.state.actors.values() for c in a.conditions.values()))
def carried_edge(engine,mover,previous,destination):
    """Revalidate all current passengers before the carrier commits an edge."""
    for passenger in engine.state.actors.values():
        if not any(c.condition_id==CARRY and c.data.get('carrier_id')==mover.entity_id
                   for c in passenger.conditions.values()):continue
        occupied=engine._occupied_volumes_except(passenger.entity_id,ignore_actor_ids=(mover.entity_id,))
        if not passenger_edge(engine,passenger,previous,destination,occupied):return False
    return None


@hook('journey_passage')
def wind_journey_passage(session,aid,occupant_id,previous,destination):
    return 'difficult' if travel_mist(session,aid) else None


@hook('event',nested=True)
def leap_base_payment(engine,event_type,kwargs):
    if event_type!='RESOURCE_SPENT' or (kwargs.get('payload') or {}).get('resource_id')!=QI:return
    action=engine.action_catalog.get(kwargs.get('source_definition_id'))
    if not action or action.parameters.get('typed',{}).get('source')!=LEAP:return
    actor=engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or action.owner_id!=actor.entity_id or form(actor,'immortal') is None:return
    scope=stamp(engine)
    if actor.turn_flags.get('cloud_leap_base_seen')==scope:return
    # Leap's one printed base debit precedes its optional companion surcharge.
    # Keep the resolved reduction even if the granting form ends in transit.
    actor.turn_flags['cloud_leap_base_seen']=scope
    listed=sum(amount for resource,amount in action.costs if resource==QI)
    if (kwargs.get('payload') or {})['amount']<listed:
        actor.turn_flags['cloud_leap_base_reduced']=scope


@hook('technique_refund_allowed')
def leap_reduction_cannot_stack_with_efficiency(engine,actor,source,resource,amount,refund_source):
    if refund_source!='passive:tianxia.path.qi_cultivation.feature.golden_core_efficiency':return None
    action=engine.action_catalog.get(source)
    if (resource==QI and action and action.parameters.get('typed',{}).get('source')==LEAP
            and actor.turn_flags.get('cloud_leap_base_reduced')==stamp(engine)):
        # CL11 expressly forbids stacking with another reduction. The native
        # payment event, not the form's continued presence, owns this fact.
        return False
    return None
