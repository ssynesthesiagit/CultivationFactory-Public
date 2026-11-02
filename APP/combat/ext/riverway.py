"""Riverway progression: committed rescue, paired gates and the Imperial Field.

Ownership is sealed by the compiler from native acquired progression. All live
consumers require that exact row. Geometry, payment, transport, choices, expiry
and replay use the public native adapters; no engine monkey patches or synthetic
trigger receipts are installed. route_environment is shared with journey travel.
The active_field helper is shared with riverway_passage's Ferry pricing.
"""
from dataclasses import replace
from . import effect, hook, placed
from .needle import ask, checkpoint_id, cell_id
from .. import route_environment as environment

PREFIX = 'tianxia.subpath.qi.riverway_cultivator.feature.'
PASSAGE, FERRY, MOON, KNOWS, FIELD = [PREFIX + n for n in (
    'flowing_passage', 'ferry_the_wounded', 'moonlit_ferry', 'river_knows_the_way', 'imperial_river_field')]
LEVELS = {PASSAGE: 3, FERRY: 6, MOON: 10, KNOWS: 14, FIELD: 18}
QI = 'resource:core.qi'
FERRY_USED='once_per_round:typed.'+FERRY
GATES = 'riverway_gates'
FIELD_TAG = 'imperial_river'


@hook('choice_options')
def choice_options(engine,intent,checkpoint,reactor_id,choice_id,context):
    from .needle import option_spec
    return option_spec(choice_id,context,'choice:riverway.')


@hook('choice_reactors')
def choice_owners(engine):
    from ..tabletop_service import MANUAL_MODES
    if not any(owned(engine,a,FERRY) or owned(engine,a,MOON) or owned(engine,a,FIELD) or owned(engine,a,KNOWS)
               for a in engine.state.actors.values()):return ()
    return tuple(aid for aid,mode in (getattr(engine,'typed_control_modes',{}) or {}).items() if mode in MANUAL_MODES)


@hook('compile_passives')
def ownership(rows, info):
    additions = []
    for feature, minimum in LEVELS.items():
        numbers = info.get('numbers_by_source', {}).get(feature, info['numbers'])
        if feature in info['owned_ids'] and int(numbers.get('cl', 1)) >= minimum:
            additions.append({'block': 'riverway', 'feature_id': feature, 'min_cl':minimum, 'numbers': dict(numbers),
                              **({'trigger_owner': 'riverway'} if feature == FERRY else {})})
    return [*rows, *additions]


def owned(engine, actor, feature):
    from .activation_requirements import min_cl_ready
    return next((r for r in (getattr(engine,'typed_passive_rows',{}) or {}).get(actor.entity_id, ())
                 if r.get('block') == 'riverway' and r.get('feature_id') == feature
                 and min_cl_ready(actor,r) is not False), None)


def numbers(engine, actor, feature):
    from .activation_requirements import effective_numbers
    return effective_numbers(actor,(owned(engine, actor, feature) or {}).get('numbers', {}))


@hook('event',nested=True)
def suppression_changed(engine,kind,kwargs):
    if kind not in ('CONDITION_APPLIED','CONDITION_REMOVED','TURN_STARTED'):return
    water_traits(engine)
    for tag,feature in (('riverway_passage',PASSAGE),(GATES,MOON),(FIELD_TAG,FIELD)):
        for zone in placed.of(engine,tag):
            owner=engine.state.actors.get(zone.owner_id)
            if owner is None or not owned(engine,owner,feature):
                placed.drop(engine,zone,'CULTIVATION_UNAVAILABLE')
            elif tag=='riverway_passage' and placed.data(zone).get('greater') and not owned(engine,owner,KNOWS):
                placed.reshape(engine,zone,cells=list(zone.affected_cells[:6]),greater=0,starters=[])


def turn_key(engine):
    actor = engine.state.actors.get(engine.state.current_actor_id)
    return f'{engine.state.round_number}:{engine.state.current_slot_index}:{engine.state.current_actor_id}:{getattr(actor, "turns_started", 0)}'


def inside(engine, zone, position):
    if placed.data(zone).get('tag') == FIELD_TAG:
        return (0 <= position.z-zone.center.z < 8 and
                engine.grid.distance_ft(position.model_copy(update={'z': zone.center.z}), zone.center) <= 40)
    return position in zone.affected_cells


def fields(engine, owner=None):
    return placed.of(engine, FIELD_TAG, owner_id=owner.entity_id if owner else None)


def active_field(engine, owner):
    return next(iter(fields(engine, owner)), None)


def field_for(engine, actor):
    from ..zones import actor_inside_zone
    return [z for z in fields(engine) if actor.entity_id in placed.data(z).get('chosen', ()) and actor_inside_zone(engine,actor,z)]


def gate_points(engine, owner, *, near=None, subject=None):
    from ..gate2_runtime_models import Position
    center = near or owner.position
    distance = 5 if near else 60
    actor = subject or owner
    points = []
    # Gates are five-foot spaces. The native map has explicit finite altitude.
    volume=engine._actor_volume(actor)
    height=max(p[2] for p in volume)-actor.position.z+1
    reach=max(engine._footprint(actor).width_cells,engine._footprint(actor).height_cells)+1
    maximum_z = center.z+1 if near else max(p[2] for p in volume)+12
    minimum_z=max(0,center.z-height-1) if near else max(0,min(p[2] for p in volume)-12)
    ys=range(max(0,center.y-reach),min(engine.grid.height,center.y+reach+1)) if near else range(engine.grid.height)
    xs=range(max(0,center.x-reach),min(engine.grid.width,center.x+reach+1)) if near else range(engine.grid.width)
    for z in range(minimum_z,maximum_z + 1):
        for y in ys:
            for x in xs:
                p = Position(x=x, y=y, z=z)
                separation=engine._distance_actor_to_cell(actor,near,actor_position=p) if near else engine._distance_actor_to_cell(owner,p)
                if separation > distance or (near and separation==0):
                    continue
                if near and p == near:
                    continue
                if not engine.grid.volume_legal(p, footprint=engine._footprint(actor) if subject else None,
                        occupied_cells=engine._occupied_volumes_except(actor.entity_id) if subject else engine._occupied_volumes_except('')):
                    continue
                if not near and not engine._line_of_sight_actor_to_cell(owner, p):
                    continue
                points.append(p)
    return points


def pick_space(engine, chooser, source, name, points, *, subject=None, allow_decline=True, payment=None):
    options = {cell_id(p): p for p in points}
    picked = ask(engine, None, checkpoint_id(engine, name, source, (subject or chooser).entity_id), chooser,
        'choice:riverway.' + name, list(options), labels={k: f'{name}: {p.x},{p.y}, {p.z*5} feet high' for k, p in options.items()},
        prompt=f'{name}: choose a legal destination for {(subject or chooser).display_name}.',
        name=name, feature_id=source, target_id=(subject or chooser).entity_id,
        allow_decline=allow_decline, payment=payment)
    return options.get(picked[0]) if picked else None


@hook('compile_action')
def actions(action, info):
    typed = action.parameters.get('typed') or {}
    source = typed.get('source')
    if typed.get('riverway_command'):return None
    if source not in (MOON, FIELD):
        return None
    return action.model_copy(update={'target_kind': 'CELL', 'range_ft': 60 if source == MOON else 90,
        'parameters': {**action.parameters, 'any_cell': True,'cell_altitude_range_ft':60 if source==MOON else 90,
            'ai_empty_area_filter':False, 'typed': {**typed, 'manual_inline_choice': True,
            'effects': [{'type': 'riverway_gates' if source == MOON else 'riverway_field'}], 'options': [],
            'area': None, 'riders': [], 'duration': {'kind': 'instant'}}}})


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', {}) or {}).get('typed') or {}
    source = typed.get('source')
    if typed.get('riverway_command'):
        zone=active_field(engine,actor)
        return bool(zone and placed.data(zone).get('command_used')!=turn_key(engine))
    if source not in (MOON, FIELD):
        return None
    if not owned(engine, actor, source):
        return False
    point = candidate.destination
    if point is None:
        return False
    if source == FIELD:
        return actor.turn_flags.get('typed_round_riverway_scene') != 1
    return (engine._distance_actor_to_cell(actor,point)<=60
            and engine.grid.volume_legal(point,footprint=None,occupied_cells=engine._occupied_volumes_except(''))
            and engine._line_of_sight_actor_to_cell(actor,point))


def choose_allies(ctx, name):
    from .. import stealth
    from ..relations import relation,ALLY
    allies = [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine,a,ctx.actor)==ALLY]
    picks = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, name, ctx.source), ctx.actor,
        'choice:riverway.'+name, [a.entity_id for a in allies], labels={a.entity_id: a.display_name for a in allies},
        minimum=0, maximum=len(allies), default_count=len(allies),
        preferred=[a.entity_id for a in allies if a is ctx.actor or stealth.sees(ctx.engine, ctx.actor, a)],
        prompt=name+': choose allies who gain its movement benefits.', name=name, feature_id=ctx.source)
    return picks


@effect('riverway_gates', harmful=False)
def create_gates(ctx, row):
    if not owned(ctx.engine, ctx.actor, MOON):
        return
    first = ctx.intent.destination
    choices = [p for p in gate_points(ctx.engine, ctx.actor) if p != first and ctx.engine.grid.distance_ft(first, p) <= 120]
    second = pick_space(ctx.engine, ctx.actor, MOON, 'Moonlit Ferry second gate', choices, allow_decline=False)
    if second is None:
        return
    for old in placed.of(ctx.engine, GATES, owner_id=ctx.actor.entity_id):
        placed.drop(ctx.engine, old, 'REPLACED')
    field = active_field(ctx.engine, ctx.actor)
    waived = bool(field and all(inside(ctx.engine, field, p) for p in (first, second)))
    if not waived:
        ctx.engine._start_concentration(ctx.actor, ctx.source)
    zone=placed.place(ctx.engine, ctx.actor, source=ctx.source, tag=GATES, cells=[first, second],
        name='Moonlit Ferry: willing entry teleports beside the other gate; once per turn',
        numbers=ctx.numbers, duration_rounds=10, concentration=not waived,
        placed={'waived': int(waived), 'used': {}}, color='#b5cafa')
    if not waived:bind_concentration(ctx,zone)


def bind_concentration(ctx,zone):
    """Use native exact-copy links and deadlines; no independent timer schema."""
    from .concentration_duration import limit_duration
    current=ctx.actor.concentration
    if current is not None and current.source_definition_id==ctx.source:
        current.zone_id=zone.zone_id
        timer=replace(ctx,typed={**ctx.typed,'duration':{'kind':'rounds','amount':zone.duration_rounds or 10}})
        limit_duration(timer,{})


@effect('riverway_field', harmful=False)
def create_field(ctx, row):
    if not owned(ctx.engine, ctx.actor, FIELD) or ctx.actor.turn_flags.get('typed_round_riverway_scene') == 1:
        return
    chosen = choose_allies(ctx, 'Imperial River Field')
    for old in fields(ctx.engine, ctx.actor):
        placed.drop(ctx.engine, old, 'REPLACED')
    # Existing gates entirely inside this field now share its Concentration.
    for gates in placed.of(ctx.engine, GATES, owner_id=ctx.actor.entity_id):
        if all(0 <= p.z-ctx.intent.destination.z < 8 and
               ctx.engine.grid.distance_ft(p.model_copy(update={'z': ctx.intent.destination.z}), ctx.intent.destination) <= 40 for p in gates.affected_cells):
            gates.concentration_link = False
            placed.update(ctx.engine, gates, waived=1)
            from .. import concentration
            copies=[state for _,state in concentration.held(ctx.actor)]
            if ctx.actor.concentration is not None:copies.append(ctx.actor.concentration)
            for copy in copies:
                if copy.source_definition_id==gates.source_definition_id:
                    concentration.end_copy(ctx.engine,ctx.actor,copy.started_sequence,'FIELD_SUSTAINS_FERRY',retain_zone=True)
    ctx.engine._start_concentration(ctx.actor, ctx.source)
    from ..gate2_runtime_models import Position
    center = ctx.intent.destination
    cells = [center, *[Position(x=x,y=y,z=z) for z in range(center.z,center.z+8)
        for y in range(max(0,center.y-8),min(ctx.engine.grid.height,center.y+9))
        for x in range(max(0,center.x-8),min(ctx.engine.grid.width,center.x+9))
        if (x,y,z)!=(center.x,center.y,center.z)]]
    zone = placed.place(ctx.engine, ctx.actor, source=ctx.source, tag=FIELD_TAG, cells=cells,
        name='Imperial River Field: chosen allies +10 Speed; hostile difficult terrain; 1 minute',
        numbers=ctx.numbers, duration_rounds=10, concentration=True,
        placed={'chosen': chosen, 'command_used': '', 'distance_used': ''}, color='#5babc9', shape='cylinder', size_ft=40, difficult='hostile', extra={'footprint_height_ft':40})
    ctx.actor.turn_flags['typed_round_riverway_scene'] = 1
    bind_concentration(ctx,zone)


@hook('speed')
def speed(engine, actor):
    return 10 if field_for(engine, actor) else None


@hook('swim_speed')
def swimming(engine,actor):
    return engine._effective_speed(actor) if owned(engine,actor,KNOWS) else None


@hook('difficult_exempt')
def difficult_exempt(engine, actor):
    return {(x, y) for z in fields(engine) if actor.entity_id in placed.data(z).get('chosen',()) for y in range(engine.grid.height) for x in range(engine.grid.width)
            if inside(engine, z, actor.position.model_copy(update={'x': x, 'y': y}))} or None


def physical_routes(engine, actor, feet, *, barriers=('spatial_lock','sealed_formation')):
    from .forced_destination import routes
    return routes(engine, actor, feet, vertical=True, step_allowed=lambda a, b: environment.permits(engine.grid, a, b,barriers=barriers)
                  and engine.grid.line_of_physical_transmission(a, b))


def relocate(engine, owner, subject, source, feet, *, willing=False, points=None, name=None, chooser=None,before_move=None):
    from ..movement_paths import resolve
    from ..typed_executor import teleport_subject
    name = name or 'Riverway movement'
    from .ability_source import mechanic_at
    feature=mechanic_at(engine,source) or source
    ctx = placed.context(engine, owner, source, numbers(engine, owner, feature), [subject])
    routes = physical_routes(engine, subject, feet,barriers=()) if points is None else None
    available = [subject.position, *routes] if routes is not None else points
    destination = pick_space(engine, chooser or owner, source, name, available, subject=subject)
    if destination is None:
        return False
    if willing:
        from .. import senses
        route=routes.get(destination,(subject.position,destination)) if routes is not None else (subject.position,destination)
        safe=all(senses.perceives_cell(engine,subject,p) for p in route)
        consent = ask(engine, None, checkpoint_id(engine, name, source, subject.entity_id, cell_id(destination),'consent'), subject,
            'choice:riverway.consent', ['accept'], labels={'accept': f'Accept {name}: move to {destination.x},{destination.y}, {destination.z*5} feet high'},
            prompt=f'{name}: {subject.display_name}, {owner.display_name} offers to move you from {subject.position.x},{subject.position.y} to {destination.x},{destination.y}, {destination.z*5} feet high, without provoking. No extra Qi or ordinary movement is spent.',
            allow_decline=True,automatic=bool(safe),target_id=subject.entity_id, name=name, feature_id=source)
        if not consent:return False
    if before_move is not None:before_move()
    if routes is None:
        teleport_subject(ctx, subject, destination, forced=False)
    elif destination != subject.position:
        resolve(engine, subject, routes[destination], source, kind='forced', source_actor_id=owner.entity_id, ctx=ctx)
    return subject.position == destination


@hook('movement_step_settled')
@hook('forced_movement_step')
def enter_gate(engine, mover, previous, destination, intent, forced=False):
    if not mover.active or mover.position!=destination:
        return
    for gates in placed.of(engine, GATES):
        before=set(engine._actor_volume(mover,previous));after=set(engine._actor_volume(mover,destination))
        entered=next((p for p in gates.affected_cells if (p.x,p.y,p.z) in after and (p.x,p.y,p.z) not in before),None)
        if entered is None:continue
        used = dict(placed.data(gates).get('used', {}))
        if used.get(mover.entity_id) == turn_key(engine):
            continue
        owner = engine.state.actors.get(gates.owner_id)
        if owner is None or not owned(engine, owner, MOON):
            continue
        other = next(p for p in gates.affected_cells if p != entered)
        if not environment.permits(engine.grid, destination, other, teleport=True):
            continue
        points = [p for p in gate_points(engine, owner, near=other, subject=mover)
                  if environment.permits(engine.grid, destination, p, teleport=True)]
        if not points:
            continue
        # The passenger owns both consent and arrival, even on another actor's turn.
        landing = pick_space(engine, mover, MOON, 'Moonlit Ferry arrival', points, subject=mover)
        if landing is None:
            continue
        from ..typed_executor import teleport_subject
        used[mover.entity_id] = turn_key(engine)
        placed.update(engine, gates, used=used)
        ctx = placed.context(engine, owner, gates.source_definition_id, gates.trigger_profile.get('numbers', {}), [mover])
        teleport_subject(ctx, mover, landing, forced=False)
        if mover.position!=landing:
            used.pop(mover.entity_id,None)
            placed.update(engine,gates,used=used)


@hook('teleport_settled')
def teleported_entry(ctx,mover,previous,destination,unwilling):
    enter_gate(ctx.engine,mover,previous,destination,ctx.intent)
    without_distance(ctx.engine,mover,previous,mover.position,ctx.intent)


@hook('movement_step_settled')
@hook('forced_movement_step')
def without_distance(engine, mover, previous, destination, intent):
    if mover.position != destination:
        return
    for zone in fields(engine):
        from ..zones import actor_inside_zone
        if not actor_inside_zone(engine,mover,zone,destination) or placed.data(zone).get('distance_used') == turn_key(engine):
            continue
        owner = engine.state.actors[zone.owner_id]
        from ..gate2_runtime_models import Position
        points = [Position(x=x, y=y, z=z) for z in range(zone.center.z, zone.center.z+8)
                  for y in range(max(0, destination.y-4), min(engine.grid.height, destination.y+5))
                  for x in range(max(0, destination.x-4), min(engine.grid.width, destination.x+5))]
        points = [p for p in points if p != destination and actor_inside_zone(engine,mover,zone,p)
                  and engine.grid.distance_ft(destination, p) <= 20 and environment.permits(engine.grid, destination, p, teleport=True)
                  and engine.grid.volume_legal(p, footprint=engine._footprint(mover), occupied_cells=engine._occupied_volumes_except(mover.entity_id))]
        before=placed.data(zone).get('distance_used','');reserved=[]
        def reserve():
            placed.update(engine, zone, distance_used=turn_key(engine));reserved.append(1)
        completed=relocate(engine,owner,mover,zone.source_definition_id,20,points=points,willing=True,
                           name='River Without Distance',before_move=reserve)
        if reserved and not completed:placed.update(engine,zone,distance_used=before)


def command_current(engine, owner, zone):
    if placed.data(zone).get('command_used') == turn_key(engine):
        return
    from ..zones import actor_inside_zone
    roster = [a for a in engine.state.actors.values() if a.active and actor_inside_zone(engine,a,zone)]
    from ..relations import relation,ALLY,ENEMY
    options = {f'{mode}:{a.entity_id}': (mode, a) for a in roster
               for mode in (('Carry', 'Buoy', 'Wash Away') if relation(engine,a,owner)==ALLY else ('Sweep',) if relation(engine,a,owner)==ENEMY else ())}
    labels = {k: f'{mode}: {a.display_name}' for k, (mode, a) in options.items()}
    pick = ask(engine, None, checkpoint_id(engine, 'Command the Current', zone.zone_id), owner,
        'choice:riverway.command', list(options), labels=labels, name='Command the Current', feature_id=FIELD,
        prompt='Command the Current: once this turn, carry a willing ally 15 feet, sweep a foe, grant twice proficiency temporary HP, or repeat a restraint save. No extra action or Qi.', allow_decline=True)
    if not pick:
        return
    mode, target = options[pick[0]]
    placed.update(engine, zone, command_used=turn_key(engine))
    source = zone.source_definition_id
    if mode == 'Carry':
        if not relocate(engine, owner, target, source, 15, willing=True, name='Command the Current — Carry'):
            placed.update(engine,zone,command_used='')
    elif mode == 'Buoy':
        engine._grant_temp_hp(target, 2*int(zone.trigger_profile['numbers'].get('pb', owner.proficiency_bonus)), source, owner.entity_id)
    elif mode == 'Sweep':
        dc = int(zone.trigger_profile['numbers'].get('save_dc', 10))
        roll = engine._roll_save(target, 'STR', dc, source)
        feet = 5 if roll and roll.total >= dc else 15
        direction = ask(engine, None, checkpoint_id(engine, 'Sweep direction', target.entity_id), owner,
            'choice:riverway.sweep', ['push', 'pull'], labels={'push': 'Push away 15 feet (5 on a successful Strength save)', 'pull': 'Pull toward you 15 feet (5 on a successful Strength save)'},
            prompt=f'Command the Current — Sweep {target.display_name}: push or pull?', name='Command the Current')
        from ..typed_executor import _push
        ctx = placed.context(engine, owner, source, zone.trigger_profile['numbers'], [target])
        _push(ctx, target, feet, pull=bool(direction and direction[0] == 'pull'))
    else:
        conditions = [c for c in target.conditions.values() if c.condition_id.rsplit('.', 1)[-1].lower() in ('grappled', 'restrained', 'prone')]
        options = {c.instance_id: c for c in conditions}
        pick = ask(engine, None, checkpoint_id(engine, 'Wash Away', target.entity_id), owner,
            'choice:riverway.wash', list(options), labels={k: c.condition_id.rsplit('.', 1)[-1].title() for k,c in options.items()},
            prompt=f'Wash Away: choose one Grappled, Restrained or Prone effect on {target.display_name}.', name='Wash Away')
        if not pick:
            placed.update(engine,zone,command_used='')
            return
        condition = options[pick[0]]
        save = condition.data.get('repeat_save') or condition.data.get('origin_save')
        if not save:
            from .ability_source import numbers_of
            source_actor = engine.state.actors.get(condition.source_actor_id)
            source_dc = condition.data.get('escape_dc',condition.data.get('dc'))
            if source_dc is None:
                action=engine.action_catalog.get(condition.source_definition_id)
                source_dc=(((getattr(action,'parameters',{}) or {}).get('typed') or {}).get('numbers') or {}).get('save_dc')
            if source_dc is None:
                from ..table_facts import records
                declared=[answer.check_dc for fact in records(engine,owner).values()
                    if fact.subject_id==target.entity_id and fact.source_reference==condition.instance_id
                    for key,answer in fact.answers.items() if key=='restraint_source' and answer.check_dc is not None]
                if len(set(declared))==1:source_dc=declared[0]
            if source_dc is None:
                raise ValueError('Wash Away needs the source DC; record the actual restraint source before resolving it.')
            ability = ask(engine, None, checkpoint_id(engine, 'Wash Away ability', target.entity_id), target,
                'choice:riverway.wash_ability', ['STR', 'DEX'], labels={'STR': 'Strength with Advantage', 'DEX': 'Dexterity with Advantage'},
                prompt=f'Wash Away: {target.display_name}, choose Strength or Dexterity against the source DC.', name='Wash Away')
            save = {'ability': ability[0], 'dc': source_dc}
        engine.resolve_repeat_save(target,condition.instance_id,condition,save,'Wash Away',extra_mode='ADVANTAGE')


@hook('turn_start_choice')
def start_turn(engine, actor):
    from .rider_step import step
    from ..zones import actor_inside_zone
    restore_gate_requirements(engine)
    for zone in fields(engine):
        owner = engine.state.actors[zone.owner_id]
        if actor.entity_id in placed.data(zone).get('chosen', ()) and actor_inside_zone(engine,actor,zone):
            ctx = placed.context(engine, actor, zone.source_definition_id, zone.trigger_profile['numbers'])
            step(ctx, {'distance_ft': 5, 'no_oa': True, 'label': 'Imperial River Field'})
        command_current(engine, owner, zone)


@hook('ability_check_mode')
def navigation(engine, actor, ability, skill, against):
    if owned(engine, actor, KNOWS) and str(skill).lower() in ('navigate river', 'navigate canal', 'navigate flood', 'navigate delta', 'navigate swamp', 'navigate coastline', 'navigate water route'):
        return 'ADVANTAGE'


@hook('compile_bundle')
def embodied_water(bundle, info):
    if not any(r.get('block')=='riverway' and r.get('feature_id')==KNOWS for r in bundle.get('typed_passives',())):
        return bundle
    bundle['riverway_water'] = {'swim_equals_walk':1,'air_breathing':1,'water_breathing':1}
    return bundle


@hook('match_initialize')
def water_traits(engine):
    condition_id='condition:typed.riverway_water'
    for actor in engine.state.actors.values():
        instances=[c for c in actor.conditions.values() if c.condition_id==condition_id]
        ready=owned(engine,actor,KNOWS)
        if ready and not instances:
            engine._apply_condition(actor,condition_id,KNOWS,actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'physiology':{'water_breathing':1},'label':'River Knows the Way: breathe air and water; Swim Speed equals walking Speed'})
        elif not ready:
            for c in instances:engine._remove_condition_instance(actor,c.instance_id,KNOWS)


@hook('compile_actions')
def observation_action(info):
    from ..gate2_runtime_models import ActionDefinition
    rows=[]
    if any(r.get('block')=='riverway' and r.get('feature_id')==FIELD for r in info['passives']):
        rows.append(ActionDefinition(source_definition_id=f'action:riverway.{info["short"]}.command',
            owner_id=info['actor_id'],display_name='Command the Current',economy='NONE',resolution_kind='TYPED',target_kind='SELF',
            parameters={'typed':{'source':FIELD,'riverway_command':1,'effects':[{'type':'riverway_command'}],
                'numbers':info['numbers'],'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}))
    if any(r.get('block')=='riverway' and r.get('feature_id')==KNOWS for r in info['passives']):
        rows.append(ActionDefinition(source_definition_id=f'action:riverway.{info["short"]}.water',
        owner_id=info['actor_id'], display_name='River Knows the Way: read connected water',
        economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'typed':{'source':KNOWS,'effects':[{'type':'riverway_water_knowledge'}],
            'numbers':info['numbers'],'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}))
    return rows or None


@effect('riverway_command',harmful=False)
def command_effect(ctx,row):
    zone=active_field(ctx.engine,ctx.actor)
    if zone:command_current(ctx.engine,ctx.actor,zone)


@hook('event',nested=True)
def off_turn_commands(engine,kind,kwargs):
    if kind not in ('ACTION_RESOLVED','MOVEMENT_COMMITTED','CONDITION_APPLIED'):return
    if getattr(engine,'_active_intent',None) is None:return
    for zone in fields(engine):
        owner=engine.state.actors.get(zone.owner_id)
        if owner and owner.entity_id!=engine.state.current_actor_id and owner.active:
            command_current(engine,owner,zone)


@hook('intent_resolved')
def resolved_commands(engine,actor,candidate,intent,start_sequence):
    for zone in fields(engine):
        owner=engine.state.actors.get(zone.owner_id)
        if owner and owner.active and owner.entity_id!=actor.entity_id:
            command_current(engine,owner,zone)


@effect('riverway_water_knowledge', harmful=False)
def read_water(ctx, row):
    if not owned(ctx.engine,ctx.actor,KNOWS):return
    ctx.engine._append_event('PASSIVE_TRIGGERED', KNOWS, actor_id=ctx.actor.entity_id,
        payload={'text':'River Knows the Way: your private water reading is refreshed.',
                 'observer_id':ctx.actor.entity_id})


@hook('observer_information')
def water_observation(engine,viewer):
    if not owned(engine,viewer,KNOWS):return []
    facts=environment.water_knowledge(engine.grid,viewer.position)
    lines=[]
    for fact in facts:
        descriptions=[]
        if 'flow' in fact:descriptions.append('flow: '+fact['flow'])
        for name in environment.PROPERTIES:
            if name in fact:descriptions.append(('is ' if fact[name] else 'is not ')+name.replace('_',' '))
        lines.append('Water at '+fact['space']+': '+', '.join(descriptions)+'.')
    return [{'kind':'declaration','ability':'River Knows the Way',
        'text':' '.join(lines) or 'No connected water facts are known.', 'water_facts':facts}]


@hook('event', nested=True)
def field_ended(engine, kind, kwargs):
    if kind not in ('ZONE_REMOVED','CONCENTRATION_ENDED'):
        return
    if kind=='ZONE_REMOVED':
        removed=engine.state.zones.get((kwargs.get('payload') or {}).get('zone_id'))
        if removed is None or placed.data(removed).get('tag') not in (FIELD_TAG,GATES):return
        from .. import concentration
        owner=engine.state.actors.get(removed.owner_id)
        if owner is None:return
        copies=[state for _,state in concentration.held(owner)]
        if owner.concentration is not None:copies.append(owner.concentration)
        for copy in copies:
            if copy.zone_id==removed.zone_id:
                concentration.end_copy(engine,owner,copy.started_sequence,'ROUTE_ENDED')
        return
    from .ability_source import mechanic_at
    if mechanic_at(engine,str(kwargs.get('source_definition_id') or ''))==FIELD:
        restore_gate_requirements(engine)


def restore_gate_requirements(engine):
    # Native Concentration/duration owns field removal. A surviving gate pair
    # resumes its original Concentration requirement instead of becoming eternal.
    for gates in placed.of(engine, GATES):
        if not placed.data(gates).get('waived'):
            continue
        owner = engine.state.actors.get(gates.owner_id)
        field = active_field(engine, owner) if owner else None
        if field and all(inside(engine, field, p) for p in gates.affected_cells):
            continue
        if owner is None or not owner.active:
            placed.drop(engine, gates, 'OWNER_UNAVAILABLE')
        else:
            gates.concentration_link = True
            placed.update(engine, gates, waived=0)
            engine._start_concentration(owner, gates.source_definition_id)
            ctx=placed.context(engine,owner,gates.source_definition_id,gates.trigger_profile.get('numbers',{}))
            # Keep the original creation deadline when the Field ends early.
            remaining=max(1,int(gates.duration_rounds or 10)-(engine.state.round_number-gates.created_round))
            current=owner.concentration
            if current:current.zone_id=gates.zone_id
            from .concentration_duration import limit_duration
            limit_duration(replace(ctx,typed={**ctx.typed,'duration':{'kind':'rounds','amount':remaining}}),{})
