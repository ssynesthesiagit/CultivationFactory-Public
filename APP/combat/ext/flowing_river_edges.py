"""River Without Edges: Flowing Response may cross water, rubble, branches, falling ground.

The sealed Flowing River insight ``insight.river-without-edges`` (CL10+) prints one
passage permission: when Flowing Response grants movement, the fighter may cross
liquid surfaces, loose rubble, narrow branches, collapsing terrain or a hostile
creature's occupied space as Difficult Terrain, if a continuous physical path no
wider than its normal reach joins one supporting surface to the next. The surface
need not carry the fighter's full weight, but the movement must end in a legal
space that can support it. It is never flight, teleportation, or water walking
outside movement Flowing Response itself granted.

Seams, all default-inert and all scoped to one Flowing Response grant:

* ``material_traversal`` publishes the five printed surface classes as walkable,
  Difficult matter for this mechanism only (combat/terrain_materials.profiles).
* ``pass_through_grant`` publishes a hostile's occupied volume at Difficult cost for
  the same mechanism; native endpoint geometry keeps it an illegal stop.
* ``movement_end_blocked`` refuses a walker's endpoint on matter that cannot carry it
  (liquid); a flyer or hovering mover may end over ground-level water, so it is not
  restricted. ``movement_step_capability`` refuses an entry with no supporting surface beyond it
  inside the mover's normal reach.

Phasing is a ContextVar set around the one shared granted-step helper in
combat/ext/flowing_second_pass.py, so ordinary movement, forced movement,
teleportation and every other ability are untouched: outside that grant the hooks
have no provider answer at all.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from . import effect, hook

INSIGHT = 'insight.river-without-edges'
DECL = 'river_without_edges'
MODE = 'walk'
# Printed surface classes, as map material tags. Liquid is the one class that
# cannot carry a creature; the rest is matter a fighter can stand on. Matter this
# table does not record stays absent: the rule invents no surface.
LIQUID = frozenset({'water'})
STANDING = frozenset({'rubble', 'bamboo', 'collapsing'})
SURFACES = frozenset(LIQUID | STANDING)

_SCOPE: ContextVar[tuple] = ContextVar('river_without_edges_scope', default=())


@contextmanager
def crossing_scope(engine, mover):
    """Mark one Flowing Response movement grant. Transient; unwinds on pause or error."""
    token = _SCOPE.set((*_SCOPE.get(), (engine, mover.entity_id)))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def granted(engine, mover) -> bool:
    """Pure: this creature is inside a Flowing Response movement grant right now."""
    return any(scope is engine and entity == mover.entity_id for scope, entity in _SCOPE.get())


def owns(engine, actor) -> bool:
    """Pure: the compiled insight declaration row is on this character."""
    rows = (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, ())
    return any(row.get('block') == DECL for row in rows)


def active(engine, actor) -> bool:
    return owns(engine, actor) and bool(getattr(actor, 'active', False)) and granted(engine, actor)


@effect(DECL)
def declaration(ctx, eff):
    pass  # compiled passive declaration; the rule is read through the seams below


@hook('compile_actions')
def compile_declaration(info):
    for key in sorted(info['owned_ids']):
        for spec in (info['mechanics'].get(key) or {}).get('effects') or []:
            if spec.get('type') == DECL:
                info['passives'].append({'feature_id': key, 'block': DECL, 'kind': DECL,
                                        'numbers': dict(info['numbers'])})


def records(engine, cell):
    """Material rows recorded for one cell (map regions, zones, roof surfaces)."""
    from ..terrain_materials import query
    return list(query(engine, cell))


def surfaces(engine, cell) -> frozenset:
    return frozenset(str(row.get('material')) for row in records(engine, cell)) & SURFACES


def reach_ft(engine, actor) -> int:
    """The printed normal reach: the creature's own melee reach, or one square."""
    from ..typed_reactions import physical_melee_reach
    return max(engine.grid.square_size_ft, int(physical_melee_reach(engine, actor)
                                              or engine.grid.square_size_ft))


def carrying(engine, cell) -> bool:
    """A space this fight table can legally carry a creature on (its own footprint invariant)."""
    from ..gate2_runtime_models import Position
    return not engine.grid.terrain_at(Position(x=cell[0], y=cell[1], z=cell[2]), 'BLOCKED')


def supported_beyond(engine, actor, crossed, *, came_from=None) -> bool:
    """Is carrying matter just past the crossing, inside normal reach?

    The printed test is a continuous physical path no wider than the mover's normal
    reach from one supporting surface to the next, so the class matter being crossed
    must be at most that wide and must open onto carrying matter on its far side.
    """
    start = (came_from.x, came_from.y, came_from.z) if came_from is not None else None
    limit = reach_ft(engine, actor)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cell = (crossed[0] + dx, crossed[1] + dy, crossed[2])
            if cell == crossed or cell == start or not engine.grid.in_bounds(cell[:2]):
                continue
            if engine.grid.distance_ft(crossed, cell[:2]) > limit:
                continue
            if start is not None and (engine.grid.distance_cells(start, cell)
                                      <= engine.grid.distance_cells(start, crossed)):
                continue  # must be past the crossing, not back on the near side
            if surfaces(engine, cell) & LIQUID:
                continue
            if carrying(engine, cell):
                return True
    return False


@hook('material_traversal')
def crossing_matter(engine, actor):
    if not active(engine, actor):
        return None
    return {'mode': MODE, 'materials': tuple(sorted(SURFACES)),
            'difficult_materials': tuple(sorted(SURFACES))}


@hook('pass_through_grant')
def hostile_space(engine, mover, occupant):
    """A hostile's occupied space is Difficult Terrain for this crossing only."""
    if not active(engine, mover) or not getattr(occupant, 'active', False):
        return None
    if getattr(occupant, 'team_id', None) == mover.team_id:
        return None
    if not supported_beyond(engine, mover, (occupant.position.x, occupant.position.y, occupant.position.z),
                            came_from=mover.position):
        return None
    return ('difficult', set(engine._actor_volume(occupant)))


def neighbourhood(engine, actor):
    """Every cell inside the printed reach of this mover, at its own height."""
    here = actor.position
    limit = reach_ft(engine, actor) // engine.grid.square_size_ft + 1
    return [(here.x + dx, here.y + dy, here.z)
            for dx in range(-limit, limit + 1) for dy in range(-limit, limit + 1)
            if engine.grid.in_bounds((here.x + dx, here.y + dy))]


def flies(engine, actor) -> bool:
    """Pure: this mover has a fly Speed or Hover, so native placement lets it end over water."""
    from .. import flight
    profile = flight.profile(engine, actor)
    return bool(profile.speed_ft or profile.hover)


@hook('movement_end_blocked')
def unendable(engine, actor):
    """A walker's crossing may not end on liquid, or on any class matter the table cannot stand on."""
    if not active(engine, actor) or flies(engine, actor):
        return None
    ends = set()
    for cell in neighbourhood(engine, actor):
        crossed = surfaces(engine, cell)
        if crossed and (crossed & LIQUID or not carrying(engine, cell)):
            ends.add(cell)
    return frozenset(ends)


@hook('movement_passage_cells')
def permitted_entry(engine, actor):
    """The cells this one grant may enter although the map (or a creature) refuses them.

    Only matter with a continuous physical path to a supporting surface inside the
    mover's normal reach qualifies, and the endpoint filter still forbids stopping
    on it: the printed clause allows a crossing, never a resting place.
    """
    if not active(engine, actor):
        return None
    cells = set()
    for cell in neighbourhood(engine, actor):
        if surfaces(engine, cell) and passage(engine, actor, cell) is not None:
            cells.add(cell)
    for other in getattr(engine.state, 'actors', {}).values():
        if (other.entity_id == actor.entity_id or not getattr(other, 'active', False)
                or getattr(other, 'team_id', None) == actor.team_id):
            continue
        if hostile_space(engine, actor, other) is not None:
            cells |= set(engine._actor_volume(other))
    return frozenset(cells)


@hook('movement_step_capability')
def crossing_continues(engine, actor, previous, destination, mode):
    """A crossing step needs carrying matter beyond it inside normal reach."""
    if mode != MODE or not active(engine, actor):
        return None
    crossed = (destination.x, destination.y, destination.z)
    if not surfaces(engine, crossed):
        return None
    return supported_beyond(engine, actor, crossed, came_from=previous)


def passage(engine, mover, cell, *, came_from=None):
    """Public pure query: 'difficult' when this crossing is legal for the mover now."""
    if not active(engine, mover) or not surfaces(engine, cell):
        return None
    if not supported_beyond(engine, mover, cell, came_from=came_from or mover.position):
        return None
    return 'difficult'
