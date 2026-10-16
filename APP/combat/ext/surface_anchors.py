"""Exact-cell location adapters over native body, equipment and object identity.

Earth's mixed Foundation spaces use these references, rather than manufacturing
objects or a second Anchor/durability model. Optional cell_anchors profile data
is sealed by the existing zone_created hook. No profile means no state/events.
"""
from . import hook
from .surface_identities import position
from .retained_updates import record_zone_update


def sync(engine):
    from ..gate2_runtime_models import Position
    from .. import zones
    changed = False
    for zone in list(engine.state.zones.values()):
        anchors = zone.trigger_profile.get('cell_anchors')
        if not zone.active or not anchors: continue
        cells = []
        for anchor in anchors:
            point = position(engine, anchor)
            if point is None: continue
            x, y, z = point.x + anchor.get('dx', 0), point.y + anchor.get('dy', 0), point.z + anchor.get('dz', 0)
            if z >= 0 and engine.grid.in_bounds((x,y)):
                cells.append(Position(x=x,y=y,z=z))
        cells = tuple(cells)
        if cells != zone.affected_cells:
            zone.affected_cells = cells
            if cells: zone.center = cells[0]
            record_zone_update(engine,zone)
            changed = True
    if changed: zones.sync_inside(engine,'surface:location_update')


@hook('movement_landed')
def landed(engine,mover,previous,destination,intent,forced):
    sync(engine)


@hook('teleport_settled')
def teleported(ctx,subject,previous,destination,unwilling):
    sync(ctx.engine)


@hook('state_event')
def changed(engine,event):
    if event.event_type in ('OBJECT_UPDATED','CONDITION_APPLIED','CONDITION_REMOVED','MOVEMENT_COMMITTED','TELEPORT_COMMITTED'):
        sync(engine)
