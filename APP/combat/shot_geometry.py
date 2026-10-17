"""Scoped attack routes and cover reduction; never moves or reveals an actor.

Routes bind integer cells to the accepted candidate. Consumers identify the
ability permitting a route; ordinary routes must have clear segments. Explicit
ignore_sight routes are for source-backed attacks that need location, not sight.
"""
from contextlib import contextmanager
from copy import deepcopy
from . import ext
from .gate2_runtime_models import Position


@contextmanager
def scope(engine, actor, action, bound=None):
    old = getattr(engine, '_shot_geometry', None)
    engine._shot_geometry = {'actor_id':actor.entity_id,'action':action,'bound':bound,'cache':{}}
    try:
        yield
    finally:
        engine._shot_geometry = old


def action(engine, actor):
    frame = getattr(engine, '_shot_geometry', None)
    return frame['action'] if frame and frame['actor_id']==actor.entity_id else None


@contextmanager
def attack_scope(engine, actor, source_id):
    current=action(engine,actor)
    if current is not None and current.source_definition_id==source_id:
        yield
    else:
        old=getattr(engine,'_shot_geometry',None)
        engine._shot_geometry=None
        try:
            yield
        finally:
            engine._shot_geometry=old


def valid(engine, actor, target, row):
    path=[Position(**p) for p in row['path']]
    from .action_geometry import point
    if path[0] != point(engine, actor) or path[-1] != target.position:
        return False
    if row.get('ignore_sight'):
        return True  # the owning provider must enforce its printed barrier exceptions
    from .space import point as coordinates
    obscured = engine._obscured_cells()
    if any(engine.grid.terrain_at(p, 'BLOCKED') or engine.grid.terrain_at(p, 'SIGHT_BLOCKED') or
           (p.x,p.y) in obscured or coordinates(p) in obscured for p in path[1:-1]):
        return False
    return all(engine.grid.line_of_sight(a,b,obscured_cells=obscured) for a,b in zip(path,path[1:]))


def route(engine, actor, target, supplied_action=None):
    frame=getattr(engine,'_shot_geometry',None)
    if supplied_action is not None and (action(engine,actor) is None or action(engine,actor).source_definition_id!=supplied_action.source_definition_id):
        with scope(engine,actor,supplied_action):
            return route(engine,actor,target)
    if not frame or frame['actor_id']!=actor.entity_id:
        return None
    bound=frame.get('bound')
    if bound and bound.get('target_id')==target.entity_id and bound.get('route'):
        return bound['route']
    key=(target.entity_id,target.position.x,target.position.y,target.position.z)
    if key in frame['cache']:
        return frame['cache'][key]
    replies=ext.run_strict('sight_path',engine,actor,target)
    routes=[]
    for row in replies:
        if not isinstance(row,dict) or set(row)-{'source_id','label','path','ignore_sight'}:
            raise ValueError('sight_path requires a route record')
        if not all(isinstance(row.get(k),str) and row[k] for k in ('source_id','label')) or type(row.get('ignore_sight',False)) is not bool:
            raise ValueError('sight_path needs source, label and a boolean sight exception')
        path=row.get('path')
        if not isinstance(path,list) or not 2<=len(path)<=8:
            raise ValueError('sight_path requires two to eight integer cells')
        for cell in path:
            if (not isinstance(cell,dict) or not {'x','y'} <= set(cell) <= {'x','y','z'}
                    or any(type(cell[k]) is not int for k in cell) or cell.get('z',0)<0
                    or not engine.grid.in_bounds((cell['x'],cell['y']))):
                raise ValueError('invalid sight_path cell')
        if valid(engine,actor,target,row):
            routes.append(deepcopy(row))
    chosen=min(routes,key=lambda r:(length(engine,r),r['source_id'],[(p['y'],p['x'],p.get('z',0)) for p in r['path']])) if routes else None
    frame['cache'][key]=chosen
    return chosen


def length(engine,row):
    points=[Position(**p) for p in row['path']]
    return sum(engine.grid.distance_ft(a,b) for a,b in zip(points,points[1:]))


def sight(engine,actor,target):
    row=route(engine,actor,target)
    return valid(engine,actor,target,row) if row else None


def valid_for_attack(engine, actor, target):
    """Recheck accepted endpoints/segments after reactions; never bind a new route."""
    frame=getattr(engine,'_shot_geometry',None)
    if not frame or frame['actor_id']!=actor.entity_id:
        return True
    bound=frame.get('bound')
    if bound and bound.get('route'):
        return bound.get('target_id')==target.entity_id and valid(engine,actor,target,bound['route'])
    row=route(engine,actor,target)
    return row is None or valid(engine,actor,target,row)


def source_cells(engine,actor,target):
    if not valid_for_attack(engine,actor,target):
        return ()
    row=route(engine,actor,target)
    if row:
        # Invalid accepted geometry never becomes a straight shot for cover.
        last = row['path'][-2]
        return ((last['x'],last['y'],last['z']),) if last.get('z') else ((last['x'],last['y']),)
    from .action_geometry import point
    if point(engine, actor).z or target.position.z or engine.grid.finite_heights:
        return engine._effect_volume(actor)
    return engine._effect_cells(actor)


def reduce_cover(engine,actor,target,cover):
    replies=ext.run_strict('cover_reduction',engine,actor,target,cover)
    if any(type(n) is not int or n<0 for n in replies):
        raise ValueError('cover_reduction must return None or nonnegative integer steps')
    levels=[0,2,5,99]
    if not replies or sum(replies)==0:
        return cover
    level=next((i for i,value in enumerate(levels) if cover<=value),3)
    return levels[max(0,level-sum(replies))]


def receipt(engine,actor,target):
    row=route(engine,actor,target)
    raw=engine._raw_cover_bonus_actor_to_actor(actor,target)
    final=reduce_cover(engine,actor,target,raw)
    if not row and final==raw:
        return {}
    return {'shot_geometry':{'target_id':target.entity_id,'route':deepcopy(row),'cover_before':raw,'cover_after':final}}
