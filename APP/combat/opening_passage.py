"""Source-qualified body passage through explicitly authored object openings.

movement_opening_width(engine, actor) -> positive integer milliinches | None
opts this actor into opening geometry. No provider returns the original grid.
The projection is local to movement, never sight, targeting or other actors.
An opening crosses the named object's full thickness in its anchor voxel;
it does not remove an overlapping wall, object, roof or cultivated field.
transit_stop_allowed(engine, actor) -> bool | None defers overlap recovery to
the owning provider's turn-boundary settlement. Default movement still requires
an unoccupied endpoint. Both queries are pure and must gate actual live state.
"""
from . import ext
from .gate2_grid import SquareGrid
from .read_queries import pure,memo
from .space import point


def may_stop(engine,actor):
    answers=ext.run_strict('transit_stop_allowed',engine,actor)
    if any(type(a) is not bool for a in answers):
        raise ValueError('transit_stop_allowed requires boolean answers')
    return True in answers and False not in answers


class OpeningGrid(SquareGrid):
    """Read-only movement projection; original geometry remains authoritative."""
    def __init__(self,original,cells):
        self.__dict__.update(original.__dict__)
        self.original=original
        self.finite_heights=True
        self.opening_cells=frozenset(cells)

    def terrain_at(self,cell,kind):
        if kind=='BLOCKED' and point(cell) in self.opening_cells:
            return False
        return self.original.terrain_at(cell,kind)


@pure
def grid_for(engine,actor):
    answers=ext.run_strict('movement_opening_width',engine,actor)
    if any(type(a) is not int or not 1<=a<=60000 for a in answers):
        raise ValueError('Opening capability requires positive integer milliinches')
    if not answers:return engine.grid
    return grid_with_minimum(engine,min(answers))


@pure
def grid_with_minimum(engine,minimum):
    """Shared explicit area/body opening requirement; no ownership is inferred."""
    if type(minimum) is not int or not 1<=minimum<=60000:
        raise ValueError('Opening capability requires positive integer milliinches')
    def calculate():
        from . import zones
        solids=[z for z in zones.typed_zones(engine) if z.active and (z.trigger_profile.get('wall') or {}).get('blocks_movement')]
        eligible={o.object_id for o in engine.state.objects.values() if not o.destroyed
            and type(o.component.get('opening_width_milliinch')) is int and o.component['opening_width_milliinch']>=minimum}
        if not eligible:return engine.grid
        static=SquareGrid(engine.battlefield_document)
        potential=set();barred=set()
        for zone in solids:
            rule=zone.trigger_profile['wall'];bottom=int(rule.get('base_altitude_ft',0))//5
            height=rule.get('height_ft');top=(bottom+(height+4)//5) if height is not None else 201
            openings={tuple(row['cell']) for row in zone.trigger_profile.get('openings') or ()}
            cells={(p.x,p.y,z) for p in zone.affected_cells if (p.x,p.y) not in openings for z in range(bottom,top)}
            if zone.trigger_profile.get('object') in eligible:
                obj=engine.state.objects[zone.trigger_profile['object']]
                opening=point(obj.position)
                potential.add(opening)
                barred|=cells-{opening}
            else:barred|=cells
        permitted={c for c in potential-barred if not static.terrain_at(c,'BLOCKED')}
        return OpeningGrid(engine.grid,permitted) if permitted else engine.grid
    return memo(engine,('opening_passage_geometry',minimum),calculate)


def solid_grid(engine):
    """Settlement geometry also counts walls temporarily omitted under occupants."""
    from . import zones
    from copy import deepcopy
    doc=deepcopy(engine.battlefield_document)
    for zone in zones.typed_zones(engine):
        wall=zone.trigger_profile.get('wall') or {}
        if not zone.active or not wall.get('blocks_movement'):continue
        row={'region_id':zone.zone_id,'terrain_type':'BLOCKED','movement_cost':0,
             'cells':[{'x':p.x,'y':p.y} for p in zone.affected_cells
                      if (p.x,p.y) not in {tuple(o['cell']) for o in zone.trigger_profile.get('openings') or ()}]}
        if wall.get('height_ft') is not None:
            row.update(height_ft=wall['height_ft'],base_altitude_ft=wall.get('base_altitude_ft',0))
        doc['terrain_regions'].append(row)
    return SquareGrid(doc)


def legal_transit_position(engine,actor,position=None,*,observed=False):
    """Pure temporary placement grant, including each actual passage scope.

    Native route admission, post-commit invariants and transit recovery share
    this check. The source still owns its turn-boundary legal-end settlement.
    An opt-in alone never bypasses an ungranted occupant or solid obstruction.
    """
    if not may_stop(engine,actor):return False
    from .creature_passage import volume_geometry
    return grid_for(engine,actor).volume_legal(position or actor.position,
        footprint=engine._footprint(actor),
        occupied_cells=volume_geometry(engine,actor,observed=observed)[0])
