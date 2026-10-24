"""Immediate source-granted movement on an admitted native travel scene.

Consumers supply their actual feature ownership, payment, surface permission
and distance. The journey already contains only the admitted travel party;
hostile participants and attacks require its ordinary native encounter caller.
No caller means no action, elapsed time, position, state or event changes.
The existing journey_step query owns surface support. This helper never grants
flight, passage through party members, walls, body-sized obstructions or consent.
An explicit journey_granted_passage subscriber can admit transient passage;
occupied endpoints always remain forbidden.
"""
from .journey import require
from .gate2_runtime_models import Position
from .footprint_registry import resolve_actor_footprint
from .dynamic_size import shape, category_name


def footprint(session, aid):
    actor=session.state['actors'][aid]
    original,_=resolve_actor_footprint(aid)
    return shape(original,category_name(actor.get('size') or actor['bundle']['actor_template'].get('size_category')))


def occupied(session, aid, *, except_ids=()):
    out=set()
    for other,row in session.state['actors'].items():
        if other==aid or other in except_ids or row.get('carried_by'):continue
        pos=Position.model_validate(row['position'])
        from .space import volume
        out.update(volume(pos,footprint(session,other)))
    return out


def speed(session,aid):
    """Current native Speed, using real retained conditions and sealed passives.

    A query-only view invokes the same public composition as walking/mounts.
    No template write, elapsed-time inference or supplied movement receipt.
    """
    from .journey_equipment import projection
    from .speed_contributions import effective_speed
    engine,actor=projection(session,aid)
    return max(0,int(effective_speed(engine,actor)))


def step_cost(session, aid, old, nxt):
    from .ext import query
    from .space import volume
    permitted=set();difficult=set()
    for other,row in session.state['actors'].items():
        if other==aid or row.get('carried_by'):continue
        replies=query('journey_granted_passage',session,aid,other)
        require(all(reply in ('free','difficult') for reply in replies),'A journey passage must be free or difficult.')
        if replies:
            permitted.add(other)
            if 'free' not in replies:difficult.update(volume(Position.model_validate(row['position']),footprint(session,other)))
    cost=session.step_profile(aid,old,nxt,occupied=False)
    require(session.grid.volume_step_legal(old,nxt,footprint=footprint(session,aid),occupied_cells=occupied(session,aid,except_ids=permitted)),
            'A wall, another creature or a space too small for your body blocks that step.')
    if set(volume(nxt,footprint(session,aid)))&difficult:cost=max(2,cost)
    return int(session.grid.distance_ft(old,nxt))*cost


def resolve(session, aid, path, *, feet, source, seconds):
    """Validate the full physical route before committing movement or time.

    Caller pays only after preflight in its outer revision transaction. Every
    step uses the admitted map and actual footprint. The helper records actual
    movement and one explicit action-time advance, never overland pace credits.
    """
    require(type(feet) is int and feet>=0 and type(seconds) is int and seconds>=0
            and type(source) is str and bool(source),'A granted route needs a source, whole-foot budget and elapsed seconds.')
    actor=session.state['actors'][aid]
    require(not actor['incapacitated'] and not actor.get('carried_by'),'This creature cannot move voluntarily now.')
    require(isinstance(path,(list,tuple)) and bool(path),'Choose a continuous route, including your starting square.')
    positions=[Position.model_validate(p) if isinstance(p,dict) else p for p in path]
    require(all(isinstance(p,Position) for p in positions) and positions[0]==Position.model_validate(actor['position']),
            'The route must start in your actual current space.')
    cost=sum(step_cost(session,aid,a,b) for a,b in zip(positions,positions[1:]))
    require(cost<=feet,'This route exceeds the granted movement distance, including difficult terrain.')
    require(session.grid.volume_legal(positions[-1],footprint=footprint(session,aid),occupied_cells=occupied(session,aid)),
            'The granted route must end in a legal unoccupied space.')
    for previous,nxt in zip(positions,positions[1:]):
        actor['position']=nxt.model_dump(mode='json')
        session.emit('GRANTED_MOVEMENT_STEP',aid,source=source,previous=previous.model_dump(mode='json'),
            position=actor['position'],distance_ft=int(session.grid.distance_ft(previous,nxt)))
    session.tick(seconds,(aid,))
    session.emit('GRANTED_MOVEMENT_COMMITTED',aid,source=source,path=[p.model_dump(mode='json') for p in positions],
        distance_ft=sum(int(session.grid.distance_ft(a,b)) for a,b in zip(positions,positions[1:])),
        movement_cost_ft=cost,seconds_taken=seconds)
    return cost
