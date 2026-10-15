"""Physical ordinary routes from explicit object profiles, never ability IDs.

Consumers include Mason-created stairs/platforms and native GM-authored ladders.
Source objects own their geometry/lifetime. No ordinary_route marker means no
capability, extra surface, route edge or saved-state change.
"""
from . import hook
from .. import asset_anchor_runtime as assets
from ..object_geometry import target_cells


@hook('runtime_roof_surfaces')
def authored_route_roofs(engine):
    rows=[]
    for obj in assets.ordinary_route_objects(engine):
        c=obj.component
        if type(c.get('ordinary_route')) is not str or c.get('route_surfaces_external'):continue
        rows.append({'id':obj.object_id+':ordinary-route','height_ft':obj.position.z*5+obj.height_ft,
            'cells':[{'x':p.x,'y':p.y} for p in target_cells(engine,obj)]})
    return rows or None


@hook('climbing_faces')
def physical_route_faces(engine,actor,at):
    rows=[]
    for obj in assets.ordinary_route_objects(engine,actor):
        points=assets.ordinary_route_points(engine,obj)
        # A real adjacent face/riser supplies a grip up to its actual plane.
        if any(abs(x-cx)+abs(y-cy)<=1 and obj.position.z<=at.z<=z
               for x,y,z in points for cx,cy in engine._actor_cells(actor,at)):
            rows.append({'id':obj.object_id+':ordinary-face','climb_check':'none'})
    return rows or None


@hook('climbing_route_available')
def ordinary_slope_available(engine,actor):
    if any(o.component.get('ordinary_route')=='slope' for o in assets.ordinary_route_objects(engine,actor)):
        return True


@hook('climbing_route_step')
def ordinary_slope_step(engine,actor,previous,destination):
    if max(abs(destination.x-previous.x),abs(destination.y-previous.y),abs(destination.z-previous.z))!=1:return
    objects=[o for o in assets.ordinary_route_objects(engine,actor) if o.component.get('ordinary_route')=='slope']
    if not objects:return
    points={p for obj in objects for p in assets.ordinary_route_points(engine,obj)}
    def on_route(at):
        return any((x,y,at.z) in points for x,y in engine._actor_cells(actor,at))
    def supported(at):
        return at.z==0 or engine.grid.roof_supported(at,engine._footprint(actor))
    if (on_route(previous) or on_route(destination)) and supported(previous) and supported(destination):
        return {'normal_cost':1}
