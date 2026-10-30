"""Flowing Passage: a chosen grounded path and its movement-only benefits.

Only reviewed riverway_passage rows opt in. Creation chooses contiguous visible
supported cells around obstacles, then an ally roster. One owned minute-long
placement remains. No actor moves during placement. Nonmagical difficult ground
on its cells is exempt; live membership supplies +5 Speed. A full native route
inside the Passage prevents the first otherwise eligible hostile opportunity
attack once per turn. Pure quotes never consume the allowance. Actual movement
uses the native movement_attempt seam and records its waiver.
"""
from . import effect, hook, placed

FEATURE='tianxia.subpath.qi.riverway_cultivator.feature.flowing_passage'
TAG='riverway_passage'
USED='typed_once_turn:riverway_passage'
FERRY='tianxia.subpath.qi.riverway_cultivator.feature.ferry_the_wounded'
FERRY_CHOICE='reaction:typed.'+FERRY
FERRY_USED='once_per_round:typed.'+FERRY
QI='resource:core.qi'


@hook('compile_reactions')
def ferry_reaction(rows, info):
    """Own the settled-damage rescue, independently of prose classification.

    Ferry is not a generic before-damage mitigation/retaliation. Seal its native
    admission row even when the phrase classifier cannot read the source text;
    replace any generic interpretation so payment and delivery have one owner.
    The shared compiler still applies Auto / Ask me / Off and priority settings.
    """
    if FERRY not in info['owned_ids']:
        return rows
    numbers = info['numbers_by_source'].get(FERRY, info['numbers'])
    return [*[row for row in rows if row.get('feature_id') != FERRY],
            {'feature_id': FERRY, 'block': 'generic', 'name': 'Ferry the Wounded',
             'kind': 'ally_damaged', 'range_ft': 30, 'once': 'round',
             'costs': [{'resource_id': QI, 'amount': 2}], 'effects': [],
             'numbers': dict(numbers), 'reaction_attack': False,
             'target_kind': 'ALLY_OR_SELF'}]


@hook('ally_row_allowed')
def ferry_after_damage_only(engine, reactor, subject, row):
    """Ferry moves a wounded ally; it never reduces a pending damage packet."""
    return False if row.get('feature_id') == FERRY else None


@hook('choice_options')
def ferry_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    from .needle import option_spec
    return option_spec(choice_id, context, FERRY_CHOICE) if choice_id == FERRY_CHOICE else None


@hook('choice_reactors')
def ferry_choosers(engine):
    from ..tabletop_service import MANUAL_MODES
    if not any(row.get('feature_id') == FERRY for rows in
               getattr(engine, 'typed_reaction_rows', {}).values() for row in rows):
        return ()
    return tuple(aid for aid, mode in getattr(engine, 'typed_control_modes', {}).items()
                 if mode in MANUAL_MODES)


def ferry_routes(engine, target):
    """Physical displacement, including aerial choices; never a teleport.

    The normal forced path owns collision and forced-movement defenses. Authored
    sealed Formation/spatial-lock regions are absolute source prohibitions here.
    Every occupied voxel must cross legally, including a Large ally's edges.
    """
    from .forced_destination import routes
    from ..route_environment import permits
    def edge(a, b):
        old = engine._actor_volume(target, a)
        dx, dy, dz = b.x-a.x, b.y-a.y, b.z-a.z
        for x, y, z in old:
            start = a.model_copy(update={'x': x, 'y': y, 'z': z})
            end = start.model_copy(update={'x': x+dx, 'y': y+dy, 'z': z+dz})
            if not permits(engine.grid, start, end) or not engine.grid.line_of_physical_transmission(start, end):
                return False
        return True
    return routes(engine, target, 10, vertical=True, step_allowed=edge)


@hook('event', nested=True)
def ferry_wounded(engine, kind, kwargs):
    """React to actual HP/Temporary HP loss in the surrounding transaction.

    Pauses unwind the damage and all nested effects; the real table retries the
    same attack with its journaled answers. Only the settled event opens Ferry.
    """
    payload = kwargs.get('payload') or {}
    if kind != 'DAMAGE_COMMITTED' or (int(payload.get('hp_damage') or 0)
            + int(payload.get('temporary_hp_absorbed') or 0)) <= 0:
        return
    from .. import senses, typed_reactions, falling
    from ..relations import relation, ALLY
    from ..movement_paths import resolve
    from .choice_costs import payable
    from .needle import ask, checkpoint_id, cell_id
    for aid in kwargs.get('target_ids', ()):
        target = engine.state.actors.get(aid)
        if target is None or not target.active:
            continue
        for owner in engine.state.actors.values():
            row = next((r for r in getattr(engine, 'typed_reaction_rows', {}).get(owner.entity_id, ())
                        if r.get('feature_id') == FERRY), None)
            if row is None:
                continue
            if (owner is target or relation(engine, owner, target) != ALLY
                    or not typed_reactions.can_use_reaction(engine, owner, target, row)
                    or engine._distance_actor_to_actor(owner, target) > 30
                    or not senses.perceives(engine, owner, target)
                    or owner.turn_flags.get(FERRY_USED) == engine.state.round_number):
                continue
            payment = payable(owner, QI, 2)
            if payment is None:
                continue
            origin = target.position
            # "Up to 10 feet" also permits remaining here. A chosen zero route
            # is distinct from a failed attempt to reach another destination.
            routes = {origin: (origin,), **ferry_routes(engine, target)}
            options = {cell_id(p): p for p in routes}
            if not options:
                continue
            known = [key for key, p in options.items()
                     if all(senses.perceives_cell(engine, owner, step) for step in routes[p])]
            from ..zones import actor_inside_zone
            passages = placed.of(engine, TAG, owner_id=owner.entity_id)
            preferred = sorted(known, key=lambda key: (
                not falling.supported(engine, target, options[key]),
                not any(actor_inside_zone(engine, target, z, options[key]) for z in passages),
                options[key] == origin))
            source = engine.action_catalog.get(kwargs.get('source_definition_id'))
            trigger_name = source.display_name if source is not None else 'the triggering damage'
            picks = ask(engine, None, checkpoint_id(engine, 'ferry_after_damage',
                len(engine.events), aid, owner.entity_id), owner, FERRY_CHOICE, list(options),
                labels={key: (f'Keep {target.display_name} in their current space' if p == origin else
                              f'Move {target.display_name} to {p.x},{p.y}, {p.z*5} feet high without provoking')
                        for key, p in options.items()},
                name='Ferry the Wounded', feature_id=FERRY, target_id=aid,
                prompt=f'Ferry the Wounded: after {target.display_name} takes damage from '
                    f'{trigger_name}, spend your Reaction '
                    'and 2 Qi to move them up to 10 feet? Arrival in your Flowing Passage grants '
                    'Temporary Hit Points equal to your Proficiency Bonus. Once per round.',
                allow_decline=True, payment=payment, automatic_options=known, preferred=preferred)
            if not picks:
                continue
            destination = options[picks[0]]
            with typed_reactions.reaction_activation(engine, owner, target, row,
                                                     range_subject=target) as permitted:
                if not permitted:
                    continue
                typed_reactions.open_reaction(engine, row, owner, (aid,), 'AFTER_DAMAGE')
                typed_reactions.spend_reaction(engine, owner, row)
                if not typed_reactions.pay_reaction_costs(engine, owner, row):
                    continue
                ctx = typed_reactions.triggered_context(engine, owner, target, row)
                moved = resolve(engine, target, routes[destination], FERRY, kind='forced',
                                source_actor_id=owner.entity_id, ctx=ctx)
                # Native fall settlement is part of the rescue, before the arrival
                # reward. An unsupported aerial choice remains available, but does
                # not leave a nonflying passenger suspended or reward a false landing.
                falling.settle(engine, FERRY)
                arrived = bool(target.position == destination and (moved or destination == origin))
                # A native movement defender may shorten the requested route.
                # The reward depends on where the passenger actually settles, not
                # whether they reached the selected destination.
                if any(actor_inside_zone(engine, target, z) for z in
                       placed.of(engine, TAG, owner_id=owner.entity_id)):
                    engine._grant_temp_hp(target, int((row.get('numbers') or {}).get('pb')
                                                     or owner.proficiency_bonus), FERRY, owner.entity_id)
                engine._append_event('REACTION_RESOLVED', FERRY, actor_id=owner.entity_id,
                    target_ids=(aid,), payload={'checkpoint': 'AFTER_DAMAGE', 'arrived': int(arrived)})


def _cell_ok(engine,owner,cell):
    from .. import falling
    return (engine.grid.in_bounds((cell.x,cell.y)) and engine.grid.distance_ft(owner.position,cell)<=30
            and engine.grid.volume_legal(cell,footprint=None)
            and falling.supported(engine,owner,cell) and engine._line_of_sight_actor_to_cell(owner,cell))


@hook('compile_action')
def passage_action(action,info):
    if any(e.get('type')=='riverway_passage' for e in (action.parameters.get('typed') or {}).get('effects',[])):
        return action.model_copy(update={'target_kind':'CELL','range_ft':30,'parameters':{**action.parameters,'any_cell':True}})


@hook('candidate_allowed')
def passage_point(engine,actor,candidate,action):
    if action and any(e.get('type')=='riverway_passage' for e in (action.parameters.get('typed') or {}).get('effects',[])):
        return candidate.destination is not None and _cell_ok(engine,actor,candidate.destination)


@effect('riverway_passage',harmful=False)
def passage(ctx,row):
    from ..gate2_runtime_models import Position
    from .. import stealth
    from .needle import ask,checkpoint_id,cell_id
    start=getattr(ctx.intent,'destination',None)
    if start is None or not _cell_ok(ctx.engine,ctx.actor,start):return
    cells=[start]
    for index in range(1,6):
        end=cells[-1]
        choices=[]
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                if not dx and not dy:continue
                point=Position(x=end.x+dx,y=end.y+dy,z=end.z)
                if point not in cells and _cell_ok(ctx.engine,ctx.actor,point) and ctx.engine.grid.volume_step_legal(end,point):
                    choices.append(point)
        options={cell_id(p):p for p in choices}
        if not options:break
        pick=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'flowing_passage_cell',ctx.source,str(index)),ctx.actor,
                 'choice:needle.flowing_passage_cell.'+str(index),['end',*options],
                 labels={'end':'Finish the Passage here',**{key:f'Extend to {p.x},{p.y}' for key,p in options.items()}},
                 preferred=[next(iter(options))],prompt='Flowing Passage: extend by one adjacent space or finish')
        if not pick or pick[0]=='end':break
        cells.append(options[pick[0]])
    allies=[a for a in ctx.engine.state.actors.values() if a.active and a.team_id==ctx.actor.team_id]
    perceived=[a.entity_id for a in allies if a is ctx.actor or stealth.sees(ctx.engine,ctx.actor,a)]
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'flowing_passage_allies',ctx.source),ctx.actor,
               'choice:needle.flowing_passage_allies',[a.entity_id for a in allies],
               labels={a.entity_id:a.display_name for a in allies},minimum=0,maximum=len(allies),default_count=len(allies),
               preferred=perceived,automatic_options=perceived,prompt='Flowing Passage: choose allies who can follow your current')
    for old in placed.of(ctx.engine,TAG,owner_id=ctx.actor.entity_id):placed.drop(ctx.engine,old,'REPLACED')
    placed.place(ctx.engine,ctx.actor,source=ctx.source,tag=TAG,cells=cells,name='Flowing Passage (chosen allies: +5 Speed, nonmagical difficult terrain)',
                 placed={'chosen':chosen},numbers=ctx.numbers,duration_rounds=10,color='#80bce2',shape='line',size_ft=len(cells)*5)


def _for(engine,actor):
    from .. import zones
    return [z for z in placed.of(engine,TAG) if actor.entity_id in placed.data(z).get('chosen',[]) and zones._inside(engine,actor,z)]


@hook('speed')
def current_speed(engine,actor):
    return 5 if _for(engine,actor) else None


@hook('difficult_exempt')
def current_ground(engine,actor):
    from .. import zones
    cells={(p.x,p.y) for z in placed.of(engine,TAG) if actor.entity_id in placed.data(z).get('chosen',[]) for p in z.affected_cells}
    return zones.explicitly_nonmagical_difficult_cells(engine,actor)&cells if cells else None


@hook('movement_attempt')
def follow_current(engine,mover,previous,nxt,intent):
    from ..movement_steps import route
    context=route(engine,mover)
    if not context:return
    for zone in _for(engine,mover):
        squares={(p.x,p.y,p.z) for p in zone.affected_cells}
        if not all((p.x,p.y,p.z) in squares for p in context['path']):continue
        owner=engine.state.actors.get(zone.owner_id)
        key=f'{USED}:{engine.state.round_number}:{engine.state.current_actor_id}'
        if owner is None or owner.turn_flags.get(key):continue
        eligible=engine.opportunity_eligible(mover,previous,nxt,ignore_oa_from=context['ignore_oa_from'])
        if eligible:
            reactor=min(eligible,key=lambda aid:engine._initiative_rank(engine.state.actors[aid]))
            mover.turn_flags[USED]={'reactor':reactor,'intent_id':intent.intent_id}
            owner.turn_flags[key]=True
            placed.note(engine,zone.source_definition_id,mover,'Follow the Current: the first hostile creature cannot make an Opportunity Attack against this movement.')
            return


@hook('opportunity_allowed')
def current_waiver(engine,reactor,mover):
    from ..movement_steps import route
    context=route(engine,mover)
    used=mover.turn_flags.get(USED) or {}
    if not context or used.get('reactor')!=reactor.entity_id or used.get('intent_id')!=context.get('intent_id'):return None
    for zone in placed.of(engine,TAG):
        squares={(p.x,p.y,p.z) for p in zone.affected_cells}
        if mover.entity_id in placed.data(zone).get('chosen',[]) and all((p.x,p.y,p.z) in squares for p in context['path']):
            return False
