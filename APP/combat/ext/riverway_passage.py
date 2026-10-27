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
