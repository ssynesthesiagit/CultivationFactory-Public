"""Default-inert mapped illumination from native, moving source emitters.

Light sources are queried from committed state, never copied into a second
zone. Consumers: scene_fields Hide basis and senses' sight/projection. A light
does not grant creature detection, bypass physical cover, or suppress magical
darkness. Absent mapped lighting preserves the historical sight policy.
"""
from . import ext
from .gate2_runtime_models import Position


def sources(engine):
    rows = [r for group in ext.run_strict('light_sources',engine) for r in group]
    for row in rows:
        if row['level'] not in ('bright','dim') or type(row['radius_ft']) is not int or row['radius_ft']<0:
            raise ValueError('Light sources require an intensity and integer radius.')
        Position.model_validate(row['position'])
    return rows


def level_at(engine, viewer, point):
    from .ext.scene_fields import facts
    cells = [r['value']['level'] for r in facts(engine,viewer,'lighting',mechanical=True)
             if [point.x,point.y,point.z] in r['value']['cells']]
    if not cells:
        return None
    rank = {'darkness':0,'dim':1,'bright':2}
    level = cells[-1]
    for light in sources(engine):
        holder = engine.state.actors.get(light.get('holder_id'))
        if holder is not None:
            from .ext.scene_fields import planes_differ
            if planes_differ(engine,viewer,holder):
                continue
        pos = Position.model_validate(light['position'])
        if engine.grid.distance_ft(point,pos)<=light['radius_ft'] and engine.grid.line_of_sight(pos,point):
            level = max((level,light['level']),key=rank.get)
    return level


def sight_blocked(engine, viewer, target):
    if level_at(engine,viewer,target.position)!='darkness':
        return False
    from . import senses
    return not any(s in {'darkvision','blindsight','truesight','spiritual_sense'}
                   and engine._distance_actor_to_actor(viewer,target)<=senses.reach(engine,viewer,s,target)
                   for s in senses.of(engine,viewer))
