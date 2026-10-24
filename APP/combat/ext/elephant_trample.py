"""Elephant King's continuing straight advance, using ordinary movement.

First commit 20 feet in one straight line, then choose a continuing move through
hostiles. A turn-scoped recorded marker owns that one advance and its recipients.
Queries never roll or move anyone. Actual entry settles nearest creatures first;
no outside placement means stop before the occupied step, without damaging it.
"""
from dataclasses import replace
from . import hook, effect_permitted
from .states import active, context
from .ability_source import numbers_of
from ..gate2_runtime_models import Position

KING = 'world_bearing_elephant_king'
SOURCE = 'tianxia.subpath.body.white_elephant_sovereign_body.feature.' + KING
MARK = 'condition:typed.sovereign_trampling_advance'


def straight_run(engine, actor):
    """Latest contiguous straight voluntary run this owner turn, ending here."""
    steps = []
    for event in reversed(engine.events):
        if event.event_type == 'TURN_STARTED':
            break
        if event.event_type != 'MOVEMENT_COMMITTED' or event.actor_id != actor.entity_id:
            continue
        data = event.payload or {}
        if data.get('forced') or data.get('teleport'):
            break
        path = [Position(**p) for p in data.get('path') or ()]
        steps = list(zip(path, path[1:])) + steps
    candidate = getattr(engine, '_active_candidate', None)
    start = (candidate.canonical_path[0] if candidate is not None
             and candidate.actor_id == actor.entity_id and candidate.canonical_path else actor.position)
    end, heading, count = start, None, 0
    for a, b in reversed(steps):
        direction = (b.x-a.x, b.y-a.y, b.z-a.z)
        if b != end or a.z != b.z or not any(direction) or max(map(abs, direction)) != 1:
            break
        if heading is not None and direction != heading:
            break
        heading = direction
        count += engine.grid.square_size_ft
        end = a
    return heading, count


def marker(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == MARK), None)


def heading(engine, actor):
    held = marker(actor)
    if held is not None:
        direction = tuple(held.data['heading'])
        for event in engine.events:
            if event.sequence <= held.applied_sequence or event.event_type != 'MOVEMENT_COMMITTED' or event.actor_id != actor.entity_id:
                continue
            data = event.payload or {}
            path = [Position(**p) for p in data.get('path') or ()]
            if data.get('forced') or data.get('teleport') or any((b.x-a.x,b.y-a.y,b.z-a.z)!=direction for a,b in zip(path,path[1:])):
                return None
        return direction
    direction, feet = straight_run(engine, actor)
    return direction if feet >= 20 else None


def continuing(engine, actor, path):
    direction = heading(engine, actor)
    return bool(direction and path and all((b.x-a.x,b.y-a.y,b.z-a.z)==direction for a,b in zip(path,path[1:])))


def outside(engine, mover, target, path, *, observed=False):
    from ..target_knowledge import actors_for
    actors = actors_for(engine, mover) if observed else engine.state.actors.values()
    occupied = {cell for other in actors if other.active and other.entity_id != target.entity_id
                for cell in engine._actor_volume(other)}
    transit = set(occupied)
    forbidden = {cell for position in path for cell in engine._actor_volume(mover, position)}
    occupied |= forbidden
    options = [Position(x=x,y=y,z=target.position.z) for x in range(engine.grid.width) for y in range(engine.grid.height)]
    options.sort(key=lambda p:(engine.grid.distance_ft(target.position,p),p.y,p.x))
    # The endpoint must clear the whole planned route, while physical travel
    # may cross its as-yet empty cells. Walls and other bodies remain blockers.
    for p in options:
        if not engine.grid.volume_legal(p,footprint=engine._footprint(target),occupied_cells=occupied):
            continue
        route = engine.grid.shortest_path(target.position,p,
            occupied_cells={(x,y) for x,y,z in transit if z==target.position.z},
            max_cost_ft=engine.grid.width*engine.grid.height*engine.grid.square_size_ft,
            footprint=engine._footprint(target),
            edge_allowed=lambda a,b: engine.grid.volume_step_legal(a,b,footprint=engine._footprint(target),occupied_cells=transit))
        if route is not None:
            return route[0]
    return None


@hook('pass_through')
def trample_permission(engine, mover, occupant):
    if (engine.state.current_actor_id != mover.entity_id or not active(engine,mover,KING)
            or occupant.team_id == mover.team_id or heading(engine,mover) is None):
        return None
    candidate = getattr(engine,'_active_candidate',None)
    path = candidate.canonical_path if candidate is not None and candidate.actor_id == mover.entity_id else (mover.position,)
    if not continuing(engine,mover,path) or outside(engine,mover,occupant,path,observed=True) is None:
        return None
    return 'free'


@hook('candidate_allowed')
def continuing_trample_candidate(engine, actor, candidate, action):
    if not active(engine,actor,KING) or not candidate.canonical_path:
        return None
    from ..target_knowledge import actors_for
    path = candidate.canonical_path
    crossed = {cell for p in path[1:] for cell in engine._actor_volume(actor,p)}
    if not any(other.team_id != actor.team_id and crossed & set(engine._actor_volume(other)) for other in actors_for(engine,actor) if other.active):
        return None
    return continuing(engine,actor,path)


@hook('movement_attempt')
def trample_enter(engine, mover, previous, nxt, intent):
    if not active(engine,mover,KING) or engine.state.current_actor_id != mover.entity_id:
        return None
    before, after = set(engine._actor_volume(mover,previous)),set(engine._actor_volume(mover,nxt))
    targets = [other for other in engine.state.actors.values() if other.active and other.team_id != mover.team_id
               and set(engine._actor_volume(other)) & after and not set(engine._actor_volume(other)) & before]
    if not targets:
        return None
    candidate = getattr(engine,'_active_candidate',None)
    path = candidate.canonical_path if candidate is not None else (previous,nxt)
    if not continuing(engine,mover,path):
        return {'stop':True,'source_id':SOURCE,'label':'Sovereign Trampling Advance requires 20 feet in a straight line, followed by movement in that same direction.'}
    direction = heading(engine,mover)
    from .. import typed_executor as te
    from ..movement_paths import resolve
    for target in sorted(targets,key=lambda a:(engine._distance_actor_to_actor(mover,a),a.entity_id)):
        route = outside(engine,mover,target,path)
        held = marker(mover)
        affected = list((held.data if held else {}).get('affected') or ())
        if route is None:
            return {'stop':True,'source_id':SOURCE,'label':f'Sovereign Trampling Advance stops: {target.display_name} has no legal space outside your path.'}
        ctx = replace(context(engine,mover,active(engine,mover,KING).source_definition_id,[target],numbers_of(engine,mover)),intent=intent).with_source(SOURCE)
        if target.entity_id not in affected:
            te.run_effects(ctx,[{'type':'save','ability':'dex','evidence':'Sovereign Trampling Advance: Dexterity saving throw',
                'on_fail':[{'type':'damage','dice':{'count':4,'sides':8},'damage_types':['bludgeoning'],'applies_to':'target'},
                           {'type':'condition','condition':'prone','applies_to':'target'}],
                'on_success':[{'type':'half_damage','applies_to':'target','damage_types':['bludgeoning']}]}])
            affected.append(target.entity_id)
        data = {'label':'Sovereign Trampling Advance: continue straight; each enemy saves once this turn',
                'heading':list(direction),'affected':affected}
        if held is None:
            engine._apply_condition(mover,MARK,SOURCE,mover.entity_id,expires_on='END_OF_CURRENT_TURN',data=data)
        else:
            mover.conditions[held.instance_id] = held.model_copy(update={'data':data})
            engine._append_event('CONDITION_APPLIED',SOURCE,actor_id=mover.entity_id,target_ids=(mover.entity_id,),
                payload={'condition_id':MARK,'instance_id':held.instance_id,'expires_on':held.expires_on})
        planned = {cell for position in path for cell in engine._actor_volume(mover,position)}
        if target.active and set(engine._actor_volume(target)) & planned:
            # Save/damage responses may have changed positions or terrain.
            route = outside(engine,mover,target,path)
            if route is not None and effect_permitted(ctx,{'type':'forced_movement','applies_to':'target'},[target]):
                resolve(engine,target,route,SOURCE,kind='forced',intent=intent,source_actor_id=mover.entity_id,ctx=ctx)
            if set(engine._actor_volume(target)) & planned:
                return {'stop':True,'source_id':SOURCE,'label':f'{target.display_name} remains in your path; your advance stops before its space.'}
    return None
