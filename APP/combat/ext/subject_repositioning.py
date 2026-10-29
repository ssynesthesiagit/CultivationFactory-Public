"""Controller-chosen immediate subject movement, shared by typed movement/teleport.

No ability IDs: non-self movement/teleport rows opt in with
choose_subject_destination=true. Gates and reductions remain historical.
The actor chooses; range and placement use the subject, sight uses the actor.
New fights record subject_repositioning_policy=1 in genesis. Unstamped saves
retain the prior interpreter, including its old grants and placement riders.
Consumers are typed_executor's subject_reposition seam and teleport_steps'
public landing query. No mutable state beyond normal events/choices is stored.
"""
from . import hook


@hook("match_start")
def record_policy(engine):
    for event in engine.events:
        if event.event_type == "MATCH_CREATED":
            event.payload["subject_repositioning_policy"] = 1
            return


def enabled(engine):
    """Read the recorded fight policy; never adopt today's default on reload."""
    return any(event.event_type == "MATCH_CREATED" and
               event.payload.get("subject_repositioning_policy") == 1 for event in engine.events)


def physical_routes(engine, subject, cells, feet, occupiable=None):
    """Fewest-square legal routes from subject to each cell, within feet of physical distance.

    Every step validates the full footprint, volumes, roof geometry and observed
    occupancy the same way the forced resolver does, and every square must be one
    the subject can occupy (falling.can_occupy unless a predicate is given). Terrain
    multipliers and Speed are ignored, matching forced movement. Routes are keyed by (x, y, z)
    and end at the exact requested cell, including vertical/diagonal steps.
    """
    from collections import deque
    from ..falling import can_occupy
    from ..gate2_runtime_models import Position
    if occupiable is None:
        occupiable = lambda cell: can_occupy(engine, subject, cell)
    grid = engine.grid
    budget = max(0, int(feet)) // grid.square_size_ft
    start = subject.position
    occupied = engine._occupied_volumes_except(subject.entity_id)
    footprint = engine._footprint(subject)
    def key(cell):
        return (cell.x, cell.y, cell.z)
    paths = {key(start): (start,)}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        path = paths[key(cell)]
        if len(path) - 1 >= budget:
            continue
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (dx, dy, dz) == (0, 0, 0):
                        continue
                    nx, ny, nz = cell.x + dx, cell.y + dy, cell.z + dz
                    if nx < 0 or ny < 0 or nz < 0 or (nx, ny, nz) in paths:
                        continue
                    nxt = Position(x=nx, y=ny, z=nz)
                    if not grid.volume_step_legal(cell, nxt, occupied_cells=occupied, footprint=footprint) or not occupiable(nxt):
                        continue
                    paths[key(nxt)] = (*path, nxt)
                    queue.append(nxt)
    routes = {}
    for cell in cells:
        route = paths.get(key(cell))
        if route is not None and cell != start and route[-1] == cell:
            routes[key(cell)] = route
    return routes


@hook("subject_reposition")
def reposition(ctx, row):
    if row.get("applies_to") not in {"target", "ally", "creatures_in_area", "enemies_in_area"} or not enabled(ctx.engine):
        return None
    teleport = row.get("type") == "teleport" or row.get("mode") == "teleport"
    if row.get("choose_subject_destination") is not True:
        return None  # gates, reductions and ordinary grants retain their semantics
    from ..typed_executor import condition_rules, teleport_subject
    from ..movement_paths import resolve
    from .. import zones
    from .teleport_steps import destinations, payment_text
    from . import needle

    engine, controller = ctx.engine, ctx.actor
    token = row.get("distance_ft")
    feet = (engine._effective_speed(controller) if token == "speed" else
            engine._effective_speed(controller) // 2 if token == "half_speed" else int(token or 0))
    for low, high, value in row.get("distance_ft_by_cl") or []:
        if low <= int(ctx.numbers.get("cl") or 1) <= high:
            feet = int(value)
            break
    subjects = [ctx.target] if ctx.target is not None else list(ctx.targets)
    for subject in subjects:
        if subject is None or not subject.active or feet <= 0:
            continue
        if row.get("applies_to") == "ally" and subject.team_id != controller.team_id:
            continue
        if row.get("applies_to") == "enemies_in_area" and subject.team_id == controller.team_id:
            continue
        hop = f"subject:{subject.entity_id}:{ctx.source}:{feet}:{'teleport' if teleport else 'move'}"
        if hop in ctx.hop_completed:
            continue
        if teleport and any(rule.get("no_teleport") for rule in condition_rules(subject)):
            ctx.rider(f"{ctx.action.display_name}: {subject.display_name} cannot teleport while sealed.")
            continue
        # Only the explicit air-displacement row (destination_requires_sight=false) opens
        # altitude landings and physical-square routes. Every other subject row keeps
        # its ground-plane enumeration and terrain-cost routes.
        altitude = row.get("destination_requires_sight", True) is False
        requires_sight = not altitude
        cells = destinations(engine, subject, feet, viewer=controller, requires_sight=requires_sight,
                             include_altitude=altitude)
        # A physical reposition needs a legal continuous path, unlike a teleport.
        routes = {}
        if not teleport and altitude:
            routes = physical_routes(engine, subject, cells, feet)
            cells = [cell for cell in cells if (cell.x, cell.y, cell.z) in routes]
        elif not teleport:
            for cell in cells:
                if feet == engine.grid.square_size_ft:
                    if engine.grid.volume_step_legal(subject.position, cell,
                            occupied_cells=engine._occupied_volumes_except(subject.entity_id),
                            footprint=engine._footprint(subject)):
                        routes[(cell.x, cell.y, cell.z)] = (subject.position, cell)
                elif subject.position.z == 0:
                    route = engine.grid.shortest_path(subject.position, cell,
                        occupied_cells=engine._occupied_cells_except(subject.entity_id),
                        max_cost_ft=feet, footprint=engine._footprint(subject),
                        edge_allowed=lambda a, b: engine.grid.volume_step_legal(a, b,
                            occupied_cells=engine._occupied_volumes_except(subject.entity_id),
                            footprint=engine._footprint(subject)))
                    if route is not None:
                        routes[(cell.x, cell.y, cell.z)] = route[0]
            cells = [cell for cell in cells if (cell.x, cell.y, cell.z) in routes]
        if row.get("destination_must_be_safe"):
            hazard = zones.hazard_test(engine, subject, movement_mode="teleport", immediate_only=True)
            cells = [cell for cell in cells if not set(engine._actor_cells(subject, cell)) & engine.grid.qi_hazard
                     and not (hazard and hazard(cell))]
        if not cells:
            ctx.rider(f"{ctx.action.display_name}: no legal visible square is available for {subject.display_name}.")
            continue
        # Harmful displacement separates the hostile from its allies; a friendly
        # subject retreats from enemies. Legal cells and deterministic ties only.
        from ..target_knowledge import can_see
        peers = [other for other in engine.state.actors.values() if other.active
                 and other.entity_id != subject.entity_id and other.team_id != controller.team_id]
        peers = [other for other in peers if can_see(engine, controller, other)]
        def score(cell):
            return min((engine.grid.distance_ft(cell, other.position) for other in peers),
                       default=engine.grid.distance_ft(cell, controller.position))
        order = sorted(cells, key=lambda cell: (-score(cell), cell.y, cell.x, cell.z))
        verb = "teleport" if teleport else "move"
        try:
            chosen = needle.ask(engine, ctx.intent,
                needle.checkpoint_id(engine, "subject_destination", hop),
                controller, "choice:needle.subject_destination", [needle.cell_id(cell) for cell in order],
                labels={needle.cell_id(cell): f"{verb.title()} {subject.display_name} to {cell.x},{cell.y}"
                    + (f", {cell.z * engine.grid.square_size_ft} feet high" if altitude else "") for cell in order},
                preferred=[needle.cell_id(order[0])], allow_decline=True,
                name=str(ctx.action.display_name), target_id=subject.entity_id,
                prompt_context={"affected_id": subject.entity_id, "action_name": str(ctx.action.display_name)},
                prompt=f"{ctx.action.display_name}: choose an unoccupied square "
                       + (f"{controller.display_name} can see " if requires_sight else "") + f"within {feet} feet of "
                       f"{subject.display_name}'s starting square. {verb.title()} {subject.display_name} there without spending movement"
                       + (" or provoking Opportunity Attacks" if teleport or row.get("no_opportunity_attacks") else "")
                       + f", or leave them in place; {payment_text(ctx)}.")
        except ValueError as exc:
            # Only a rejected destination (needle.InvalidCellOption) is the controller's
            # error; any other ValueError is a genuine bug and surfaces.
            if not isinstance(exc, needle.InvalidCellOption):
                raise
            # An invalid controller destination aborts the whole transaction,
            # including any already-previewed reaction payment.
            from . import CheckpointError
            raise CheckpointError('Choose a legal destination from the listed squares.') from exc
        if not chosen:
            ctx.hop_completed.add(hop)
            continue
        destination = needle.position_of(chosen[0])
        if destination not in cells:
            continue
        if teleport:
            forced = row.get("forced") if isinstance(row.get("forced"), bool) else None
            teleport_subject(ctx, subject, destination, movement_context="FORCED",
                             unwilling=bool(row.get("unwilling", row.get("applies_to") == "target")),
                             forced=forced)
        else:
            resolve(engine, subject, routes[(destination.x, destination.y, destination.z)], ctx.source, kind="forced",
                    feet=feet, intent=ctx.intent, source_actor_id=controller.entity_id, ctx=ctx)
        ctx.hop_completed.add(hop)
    return True
