"""Opt-in surface targeting and rigid translation of retained ground areas.

Only reviewed rows carrying surface_bound=True participate. Ground is the arena
floor or an explicitly finite solid column, the same support falling uses.
Translation checks every retained cell along its route, preserving geometry,
source, duration, concentration, trigger counters and saved area identity.
"""
from copy import deepcopy
from . import effect, hook


def supported_at(engine, point):
    if not engine.grid.volume_legal(point):
        return False
    return point.z == 0 or engine.grid.terrain_at((point.x, point.y, point.z - 1), 'BLOCKED')


def _bound(action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return (typed.get('area') or {}).get('surface_bound') is True or any(
        row.get('surface_bound') is True for row in typed.get('effects') or [] if isinstance(row, dict))


@hook('candidate_allowed')
def surface_target(engine, actor, candidate, action):
    if not _bound(action):
        return None
    point = getattr(candidate, 'destination', None)
    if point is not None:
        return None if supported_at(engine, point) else False
    from ..falling import supported
    targets = [engine.state.actors[aid] for aid in candidate.target_ids if aid in engine.state.actors]
    return None if targets and all(supported(engine, target) for target in targets) else False


@hook('zone_subject_allowed')
def surface_recipient(engine, zone, creature):
    if not _bound(engine.action_catalog.get(zone.source_definition_id)):
        return None
    from ..falling import supported
    return None if creature.position.z == zone.center.z and supported(engine, creature) else False


def movable(engine, actor, source):
    from .. import zones, concentration
    def technique(action):
        typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
        return typed.get('option_of') or typed.get('source')
    wanted = technique(engine.action_catalog.get(source)) or source
    return [zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == actor.entity_id
            and (zone.source_definition_id == source or technique(engine.action_catalog.get(zone.source_definition_id)) == wanted)
            and zone.concentration_link and concentration.concentrating_on(actor, zone.source_definition_id)]


def translation(engine, zone, aim, maximum, minimum=0):
    """Pure translated positions, or None when any part lacks a continuous surface."""
    from ..gate2_runtime_models import Position
    if aim.z != zone.center.z or aim == zone.center or not minimum <= engine.grid.distance_ft(zone.center, aim) <= maximum:
        return None
    # A rigid area can turn a corner, but cannot cut a diagonal through solids.
    # Breadth-first search finds a continuous route within the printed budget.
    from collections import deque
    size = engine.grid.square_size_ft
    steps = maximum // size
    goal = (aim.x-zone.center.x, aim.y-zone.center.y)
    pending = deque([((0, 0), 0)])
    visited = {(0, 0)}

    def shifted(offset):
        result = []
        for cell in zone.affected_cells:
            x, y = cell.x+offset[0], cell.y+offset[1]
            if not engine.grid.in_bounds((x, y)):
                return None
            point = Position(x=x, y=y, z=cell.z)
            if not supported_at(engine, point):
                return None
            result.append(point)
        return result

    while pending:
        offset, distance = pending.popleft()
        if offset == goal:
            return shifted(offset)
        if distance >= steps:
            continue
        previous = shifted(offset)
        if previous is None:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not dx and not dy:
                    continue
                nxt = (offset[0]+dx, offset[1]+dy)
                if nxt in visited:
                    continue
                # Both orthogonal swept footprints must have floor as well as
                # free volume. Endpoint support alone can bridge empty air.
                if dx and dy and (shifted((offset[0]+dx, offset[1])) is None
                                  or shifted((offset[0], offset[1]+dy)) is None):
                    continue
                moved = shifted(nxt)
                if moved is None or any(not engine.grid.volume_step_legal(old, new)
                                        for old, new in zip(previous, moved)):
                    continue
                visited.add(nxt)
                pending.append((nxt, distance+1))
    return None


def destinations(engine, actor, action, spec):
    """Pure perceived endpoints around each owned area, without a casting-range cap."""
    from .. import targeting, area_knowledge
    from .map_positions import map_position
    points = {}
    steps = spec['max_ft'] // engine.grid.square_size_ft
    for zone in movable(engine, actor, spec['source']):
        for dx in range(-steps, steps+1):
            for dy in range(-steps, steps+1):
                aim = map_position(engine, zone.center.x+dx, zone.center.y+dy, z=zone.center.z)
                if aim is None or not targeting.line_of_effect(engine, actor, destination=aim) \
                        or not area_knowledge.origin_allowed(engine, actor, action, aim):
                    continue
                if translation(engine, zone, aim, spec['max_ft'], spec.get('min_ft', 0)) is not None:
                    points[(aim.x, aim.y, aim.z)] = aim
    return [points[key] for key in sorted(points)]


@hook('candidate_allowed')
def moving_surface(engine, actor, candidate, action):
    spec = (getattr(action, 'parameters', None) or {}).get('surface_translation')
    if spec is None:
        return None
    aim = getattr(candidate, 'destination', None)
    if aim is None:
        return bool(destinations(engine, actor, action, spec))
    return any(translation(engine, zone, aim, spec['max_ft'], spec.get('min_ft', 0)) is not None
               for zone in movable(engine, actor, spec['source']))


def placement_value(engine, actor, zone, cells):
    """Pure hostile placement preference using only currently perceived creatures.

    Utility is future exposure, never immediate damage or a finishing estimate.
    Unknown and remembered enemies supply no current location or hidden stats.
    """
    from .. import target_knowledge
    from ..relations import relation, ENEMY, ALLY
    from ..falling import supported
    occupied = {(p.x, p.y, p.z) for p in cells}
    value = 0
    for other in engine.state.actors.values():
        # Query the real creature's perception before reading its footprint.
        # A remembered projection deliberately strips hidden conditions and
        # must not be mistaken for a currently visible creature.
        if not target_knowledge.located(engine, actor, other) or not other.active:
            continue
        if other.position.z != zone.center.z or not supported(engine, other):
            continue
        if not occupied.intersection(engine._actor_volume(other)):
            continue
        side = relation(engine, actor, other)
        value += 4 if side == ENEMY else -8 if side == ALLY else -8
    return value


def preference(engine, actor, spec, aim):
    """Best improvement among eligible copies; stable geometry breaks ties."""
    scores = []
    for zone in movable(engine, actor, spec['source']):
        cells = translation(engine, zone, aim, spec['max_ft'], spec.get('min_ft', 0))
        if cells is not None:
            value = placement_value(engine, actor, zone, cells)
            old = placement_value(engine, actor, zone, zone.affected_cells)
            scores.append((value-old, value, -engine.grid.distance_ft(zone.center, aim)))
    return max(scores, default=(0, 0, 0))


def preferred_destinations(engine, actor, action, spec, points):
    if spec.get('ai_preference') != 'hostiles':
        return points
    return sorted(points, key=lambda p: (tuple(-v for v in preference(engine, actor, spec, p)), p.x, p.y, p.z))


@hook('ai_candidate_allowed')
def useful_translation(engine, actor, candidate, action):
    spec = (getattr(action, 'parameters', None) or {}).get('surface_translation')
    if not spec or spec.get('ai_preference') != 'hostiles':
        return None
    points = ([candidate.destination] if candidate.destination is not None
              else destinations(engine, actor, action, spec))
    return any((score := preference(engine, actor, spec, point))[0] > 0 and score[1] > 0 for point in points)


def destination_id(point):
    """Keep historical floor IDs; distinguish destinations on elevated planes."""
    return f"cell:{point.x},{point.y}" + (f",{point.z}" if point.z else "")


def copy_labels(engine, copies):
    """Readable identities and clocks from retained areas, without exposing IDs.

    Casting round orders copies; retained zone order breaks same-round ties.
    Number all owned movable copies before destination or AI preference sorting,
    so narrowing the eligible list cannot rename a player's existing copies.
    """
    labels = {}
    for number, zone in enumerate(sorted(copies, key=lambda z: z.created_round), 1):
        clock = f"cast in round {zone.created_round}"
        if zone.duration_rounds:
            remaining = max(0, zone.created_round + zone.duration_rounds - engine.state.round_number)
            clock += f"; {remaining} {'round' if remaining == 1 else 'rounds'} remaining"
        labels[zone.zone_id] = (f"{zone.trigger_profile.get('name') or 'Area'} — copy {number} ({clock}) "
                                f"at ({zone.center.x}, {zone.center.y})")
        if zone.center.z:
            labels[zone.zone_id] += f" at {zone.center.z * engine.grid.square_size_ft} feet above the arena floor"
    return labels


@effect('surface_translation', harmful=False)
def move_surface(ctx, row):
    from .. import zones
    from .retained_updates import record_zone_update
    aim = getattr(ctx.intent, 'destination', None)
    if aim is None:
        from .needle import ask, checkpoint_id, CHOICE
        points = preferred_destinations(ctx.engine, ctx.actor, ctx.action, row,
                                        destinations(ctx.engine, ctx.actor, ctx.action, row))
        if not points:
            return
        distance = ('up to ' if row.get('min_ft', 0) < row['max_ft'] else '') + f"{row['max_ft']} feet"
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'surface_destination', ctx.source),
                     ctx.actor, CHOICE+'surface_destination', [destination_id(point) for point in points],
                     preferred=[destination_id(points[0])], allow_decline=False,
                     labels={destination_id(point): f"Move the area's origin to ({point.x}, {point.y})"
                             + (f" at {point.z * ctx.engine.grid.square_size_ft} feet above the arena floor" if point.z else "") for point in points},
                     prompt=f"{ctx.action.display_name}: choose where to move the line, {distance} along a continuous surface. "
                            'Its width and direction remain the same. It cannot cross walls or empty air.')
        if not chosen:
            return
        aim = next(point for point in points if destination_id(point) == chosen[0])
    copies = movable(ctx.engine, ctx.actor, row['source'])
    eligible = [(zone, translation(ctx.engine, zone, aim, row['max_ft'], row.get('min_ft', 0)))
                for zone in copies]
    eligible = [(zone, cells) for zone, cells in eligible if cells is not None]
    if not eligible:
        return
    def copy_preference(pair):
        zone, cells = pair
        if row.get('ai_preference') != 'hostiles':
            return (0, 0, zone.zone_id)
        value = placement_value(ctx.engine, ctx.actor, zone, cells)
        old = placement_value(ctx.engine, ctx.actor, zone, zone.affected_cells)
        return (old-value, -value, zone.zone_id)
    eligible.sort(key=copy_preference)
    if len(eligible) > 1:
        from .needle import ask, checkpoint_id, CHOICE
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'surface_area', ctx.source),
                       ctx.actor, CHOICE+'surface_area', [zone.zone_id for zone, _ in eligible],
                       preferred=[eligible[0][0].zone_id], allow_decline=False,
                       labels=copy_labels(ctx.engine, copies),
                       prompt='Choose which of your concentrating areas to move. This uses the Bonus Action already chosen.')
        eligible = [pair for pair in eligible if pair[0].zone_id in selected]
    for zone, cells in eligible[:1]:
        dx, dy = aim.x-zone.center.x, aim.y-zone.center.y
        vertex = zone.trigger_profile.get('area_vertex')
        if vertex is not None:
            zone.trigger_profile = deepcopy(zone.trigger_profile)
            zone.trigger_profile['area_vertex'] = [vertex[0]+dx, vertex[1]+dy, vertex[2]]
        zone.center = aim
        zone.affected_cells = tuple(cells)
        record_zone_update(ctx.engine, zone)
        zones.sync_inside(ctx.engine, ctx.source)
        return
