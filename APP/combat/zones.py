"""Ground and area effects that stay on the map (owner 2026-09-27 playtest: "We need a visual layer to show terrain
effects that show what youre doing to the ground"; Ashfall "had nothing under it").

An ability that leaves an area behind -- Ashfall's "The area becomes Ash Terrain", a cloud, a field -- places a zone
(the engine's ZoneState, kind "TYPED") for its duration: it ends with the Concentration that holds it, or when its
rounds run out at its creator's turn. The compiler (combat/factory_compiler.py _zone_abilities) writes each such
ability's ``zone_spec``: its named terrain (combat/rules/terrain.json), difficult terrain, obscurement, and the
effects that happen to a creature that enters it or starts its turn inside -- the ability's own ("a creature that
enters the area ... makes a save") and an attached talent's (Soot in the Lungs, "a hostile creature entering Ashfall
for the first time on a turn or starting its turn inside"). Each trigger happens once per turn to a creature. The
table draws every active zone (static/tabletop/board.js).

Moments a trigger's ``on`` may list: enter, start, cross, technique, and ``prone`` -- a creature
knocked Prone inside the area (combat/ext/wax.py fires it).

An area printed as a number of cubes rather than one ("At CL 5, the area becomes two connected 10-foot cubes") carries
``blocks`` in its spec, and :func:`block_cells` is the shared geometry: ``blocks`` cube-shaped blocks of ``size_ft`` laid
in one straight run whose blocks share a face. The run's direction is :func:`run_axis` -- across the line from the area's
user through its aim point, so the area reads as the screen its printed shape describes -- and that direction is written
into the area's own ``trigger_profile`` as ``blocks_along``, so a moved or re-centred run keeps the shape it was made
with instead of re-deciding its direction from wherever its owner now stands. ``blocks`` 1 or absent is the plain cube.
``combat/factory_compiler.py`` ``_area_blocks_for_cl`` resolves a printed ``blocks_by_cl`` table into that integer, and the
count is written into the area's own ``trigger_profile`` so a table commit and reload -- and a later re-centring
(combat/ext/zone_mover.py, combat/ext/tabik_dark.py) -- keep the same squares. Consumed by combat/ext/smoke_veil.py
(Smoke Veil) for the Smoke sphere; any area with the printed wording may use it.

Named ``move_through`` rules count physical distance in the zone across a creature's committed voluntary movement
events since the current table turn's ``TURN_STARTED`` event, matching the zone system's once-per-turn trigger clock.
Their recorded integer grid paths are the replayable source of truth; forced movement and teleports do not add distance.

An area's persisted ``spreads`` geometry selects shared square-by-square flood-fill: the area can flow around solid
surfaces through connected open cells, while blocked cells remain outside it. This is a shape property, independent of
the effect's source or name, and survives ordinary table commits and cold reloads.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from . import senses
from .ext import damage_delivery
from .gate2_runtime_models import ActorState, Position, ZoneState

RULES_PATH = Path(__file__).resolve().parent / "rules" / "terrain.json"
KIND = "TYPED"
_TERRAIN_SNAPSHOT = ContextVar('combat_terrain_snapshot', default=None)


@contextmanager
def terrain_snapshot():
    """Freeze editable terrain source for one request, including nested calls.

    This caches only the source document, never areas, actor positions, usage
    receipts or hook answers. Reads outside a request remain fresh. Consumers
    treat the shared request source as read-only, like typed mechanic rules.
    """
    if _TERRAIN_SNAPSHOT.get() is not None:
        yield
        return
    token = _TERRAIN_SNAPSHOT.set({})
    try:
        yield
    finally:
        _TERRAIN_SNAPSHOT.reset(token)


def terrain_rules() -> dict[str, Any]:
    snapshot = _TERRAIN_SNAPSHOT.get()
    if snapshot is None:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    if RULES_PATH not in snapshot:
        snapshot[RULES_PATH] = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return snapshot[RULES_PATH]


def run_axis(center: Position, origin: Position) -> str:
    """Which way a run of connected blocks lies: ``"x"`` for a run that steps east-west, ``"y"`` for north-south.

    The run runs across the line from the area's user (``origin``) through its aim point, so the area reads as the
    screen its printed shape describes: an area aimed at a point to the user's east or west gets a north-south run
    (a wall facing the user), and a user standing on the aim point gets an east-west one. Named so the axis can be
    written into the area's own profile and read back, so a moved area keeps the shape it was made with."""
    return "x" if abs(center.y - origin.y) > abs(center.x - origin.x) else "y"


def block_cells(engine: Any, center: Position, spec: dict[str, Any], vertex: Position | None = None) -> tuple[Position, ...]:
    """An area printed as a number of connected cubes ("the area becomes two connected 10-foot cubes"; the same
    wording any sphere uses for panes, panels or a Domain). General geometry, not an ability's rule: ``blocks``
    is the number of cube-shaped blocks, each ``size_ft`` on a side, laid in one straight run whose blocks share
    a face. The run's direction is ``blocks_along`` -- the ``run_axis`` this area was made with, stored in its own
    profile -- so a run that is moved or re-centred keeps the shape it was made with instead of re-deciding its
    direction from wherever its owner happens to stand. One block is the plain cube, so a record without ``blocks``
    is unchanged. Squares outside the map are dropped; if that would empty the run, the plain cube is returned
    instead, so the area always keeps its aim square."""
    blocks = int(spec.get("blocks") or 1)
    size = max(5, int(spec.get("size_ft") or 5))
    per = max(1, size // engine.grid.square_size_ft)
    if blocks <= 1:
        return ()
    along = (1, 0) if str(spec.get("blocks_along") or run_axis(center, vertex or center)) == "x" else (0, 1)
    total, start = blocks * per, -(blocks * per // 2)
    out = []
    for step in range(total):
        for depth in range(per):  # each block is a cube `size` feet on a side, not a row of squares
            x = center.x + along[0] * (start + step) + along[1] * (depth - (per - 1) // 2)
            y = center.y + along[1] * (start + step) + along[0] * (depth - (per - 1) // 2)
            if engine.grid.in_bounds((x, y)):
                out.append(Position(x=x, y=y, z=center.z))
    return tuple(out)


def _cells(engine: Any, center: Position, spec: dict[str, Any], vertex: Position | None = None) -> tuple[Position, ...]:
    """The squares an area covers: a sphere or emanation is round, a cube square (or a straight run of connected
    cubes when the spec names how many, see ``block_cells``), a line or cone runs from its user (``vertex``) through
    the aim point -- or from the point it was laid down at, when the compiled area is ``placed``
    (combat/typed_executor.py in_area)."""
    from .area_projection import cells as area_cells

    shape = str(spec.get("shape") or "sphere")
    area = {"shape": shape, "size_ft": int(spec.get("size_ft") or 5), "width_ft": spec.get("width_ft"),
            "spreads": bool(spec.get("spreads"))}  # Darkness "spreads around corners, and cannot extend through walls"
    if spec.get("height_ft") is not None:
        area["height_ft"] = spec["height_ft"]
    if spec.get('include_origin'):
        area['include_origin'] = True
    if spec.get("placed"):  # the shape is laid down at its aim point, so it keeps that placement once it is on the map
        area["placed"] = True
    elif shape in ("line", "cone") and (vertex is None or vertex == center):
        area["shape"] = "sphere"  # no direction to run in
    if shape in ("cube", "square") and int(spec.get("blocks") or 1) > 1:
        run = block_cells(engine, center, spec, vertex)
        if run:
            return run
    cells = area_cells(engine, vertex or center, center, area)
    if not cells and shape in ("line", "cone") and vertex == center:
        # A line or cone laid down on the square its own user stands on has no direction to run
        # in, and no printed rule says which way it should. It therefore covers no square rather
        # than a made-up one: combat/typed_executor.py aim_gives_direction is why the table never
        # offers that aim in the first place, and a fight saved before this rule keeps the squares
        # it stored instead of silently shrinking to one.
        return ()
    return cells or (center,)


def _duration_rounds(duration: dict[str, Any]) -> int | None:
    kind, amount = str(duration.get("kind") or ""), int(duration.get("amount") or 1)
    from .typed_executor import duration_round_count

    counted = duration_round_count(kind, amount)
    if counted is not None:
        return counted
    if kind in ("until_start_of_next_turn", "until_end_of_next_turn", "turn"):
        return 1
    return None  # the scene, "until dispelled", Concentration alone: the whole fight


def wall_cells(engine: Any, origin: Position, center: Position, length_ft: int, thick_ft: int = 5) -> tuple[Position, ...]:
    """A straight wall through ``center`` standing across the line from ``origin`` (its user): between the user and
    what lies beyond (owner 2026-09-27: walls "should be able to be placed and block los ... as well as movement").
    It runs along the grid, ``length_ft`` long and ``thick_ft`` deep away from the user."""
    size = engine.grid.square_size_ft
    count, thick = max(1, int(length_ft) // size), max(1, int(thick_ft) // size)
    dx, dy = center.x - origin.x, center.y - origin.y
    if abs(dx) >= abs(dy):
        along, away = (0, 1), (1 if dx >= 0 else -1, 0)
    else:
        along, away = (1, 0), (0, 1 if dy >= 0 else -1)
    cells = []
    for step in range(-(count // 2), count - count // 2):
        for depth in range(thick):
            x, y = center.x + along[0] * step + away[0] * depth, center.y + along[1] * step + away[1] * depth
            if engine.grid.in_bounds((x, y)):
                cells.append(Position(x=x, y=y))
    return tuple(cells) or (center,)


WALL_PLAN = "condition:typed.wall_plan"


def wall_plan(actor: ActorState) -> list[tuple[int, int]]:
    """The squares its next wall runs through, in order (docket 2026-09-28: the player chooses a wall's direction and
    bends; "Wall point", combat/ext/docket_walls.py)."""
    row = next((condition for condition in actor.conditions.values() if condition.condition_id == WALL_PLAN), None)
    return [tuple(point) for point in ((row.data or {}).get("points") or [])] if row is not None else []


def clear_wall_plan(engine: Any, actor: ActorState, source: str) -> None:
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == WALL_PLAN:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})


def wall_cells_for(engine: Any, actor: ActorState, center: Position, length_ft: int, thick_ft: int = 5) -> tuple[Position, ...]:
    """The squares of a wall its user raises at ``center``: straight across its line (wall_cells), or, when it laid out
    points, from ``center`` through each point in turn -- as long as the wall's length allows. A thicker wall (10 feet)
    adds the squares beside the path on the side away from its user."""
    from .action_geometry import point
    origin = point(engine, actor)
    points = wall_plan(actor)
    if not points:
        return wall_cells(engine, origin, center, length_ft, thick_ft)
    size = engine.grid.square_size_ft
    count, thick = max(1, int(length_ft) // size), max(1, int(thick_ft) // size)
    path: list[tuple[int, int]] = [(center.x, center.y)]
    for x, y in points:
        for cell in engine.grid.ray_cells(Position(x=path[-1][0], y=path[-1][1]), Position(x=int(x), y=int(y)))[1:]:
            if len(path) >= count:
                break
            if cell not in path:
                path.append(cell)
    cells = list(path)
    for depth in range(1, thick):
        for index, (x, y) in enumerate(path):
            nx, ny = path[min(index + 1, len(path) - 1)] if len(path) > 1 else (x + 1, y)
            px, py = path[max(index - 1, 0)] if len(path) > 1 else (x, y)
            dx, dy = (nx - px) or 0, (ny - py) or 0
            normal = (-(1 if dy > 0 else -1 if dy < 0 else 0), 1 if dx > 0 else -1 if dx < 0 else 0)
            away = [(x + normal[0] * depth * sign, y + normal[1] * depth * sign) for sign in (1, -1)]
            far = max(away, key=lambda cell: (abs(cell[0] - origin.x) + abs(cell[1] - origin.y), cell))
            if far not in cells:
                cells.append(far)
    return tuple(Position(x=x, y=y) for x, y in cells if engine.grid.in_bounds((x, y))) or (center,)


def sync_walls(engine: Any, *, excluded_zone_ids: tuple[str, ...] = ()) -> None:
    """Lay the active walls onto the battle grid: a solid wall's squares are impassable and hide what is behind them,
    a wall of smoke or darkness only hides, a wall of wind or sand gives cover, a dune or a low wall costs extra
    movement. The map's own walls stay as drawn. Squares a creature stands in stay open until it leaves. Called
    whenever a zone appears, ends or a creature moves, and when a saved fight is loaded (the grid is rebuilt from the
    map then; the walls come back from the fight's zones)."""
    grid = engine.grid
    from .sight_lines import bind, cross_segments, source
    from .terrain_occlusion import CROSS_POLICY
    line_sources = []
    from copy import deepcopy
    base = getattr(engine, "_wall_base", None)
    if base is None:  # the map's own costs, not an unimpeded mover's stripped ones (combat/motion.py terrain_for)
        costs = grid.__dict__.get("unimpeded_full_costs", grid.base_movement_cost)
        base = (frozenset(grid.blocked), frozenset(grid.opaque), frozenset(grid.cover), dict(costs))
        engine._wall_base = base
        engine._wall_base_heights = deepcopy(grid.terrain_heights)
        engine._wall_base_spans = deepcopy(grid.terrain_spans)
        engine._wall_base_occluders = deepcopy(grid.occluder_spans)
        engine._wall_base_centerline = set(grid.centerline_cells)
    blocked, opaque, cover, cost = set(base[0]), set(base[1]), set(base[2]), dict(base[3])
    occluder = deepcopy(getattr(engine, "_wall_base_occluders", grid.occluder_spans))
    centerline = set(getattr(engine, "_wall_base_centerline", grid.centerline_cells))
    heights = deepcopy(getattr(engine, "_wall_base_heights", {}))
    spans = deepcopy(getattr(engine, "_wall_base_spans", {}))
    def add_height(kind, cells, rule, plus=False):
        height = rule.get("height_ft")
        bottom = int(rule.get("base_altitude_ft", 0))
        if height is not None and (type(height) is not int or height < 0):
            raise ValueError("wall height must be nonnegative integer feet")
        top = bottom+height if height is not None else None
        if plus:
            # Freestanding scenery: sight is the centre plus through its squares. Movement and
            # physical blocking keep the full footprint (BLOCKED spans below, unchanged).
            line_sources.append(source(cells, 'SIGHT_BLOCKED', bottom if height is not None else 0, top,
                                       zone.trigger_profile.get('name') or 'Object',
                                       segments=cross_segments(cells), tag=rule.get('sight_class', 'object')))
            for cell in cells:
                occluder.setdefault(cell, []).append(('centerline', bottom if height is not None else 0, top))
                centerline.add(cell)
        elif kind in {'BLOCKED', 'SIGHT_BLOCKED'}:
            line_sources.append(source(cells, kind, bottom if height is not None else 0, top,
                                       zone.trigger_profile.get('name') or 'Wall',
                                       tag=rule.get('sight_class', 'wall')))
        for cell in cells:
            prior = heights.setdefault(kind, {})
            prior[cell] = height if cell not in prior else None if prior[cell] is None or height is None else max(prior[cell], height)
            spans.setdefault(kind, {}).setdefault(cell, []).append((bottom, bottom+height) if height is not None else (0, None))
    deep: set[tuple[int, int]] = set()  # Three-Quarters Cover (Dune Wall, Wind Wall; gate4_engine _cover_bonus_actor_to_actor)
    wall_cost: dict[tuple[int, int], int] = {}  # what an ability-made wall's own squares cost to cross, kept apart from the
    # map's ground so a terrain exemption can discount one without erasing the other (combat/motion.py wall_traversal_cost)
    walls = [zone for zone in typed_zones(engine) if zone.trigger_profile.get("wall") and zone.zone_id not in excluded_zone_ids]
    if walls:
        occupied = {cell for actor in engine.state.actors.values() if actor.active
                    for cell in grid.footprint_cells(actor.position, engine._footprint(actor.entity_id))}
        for zone in walls:
            rule = zone.trigger_profile["wall"]
            cells = {(cell.x, cell.y) for cell in zone.affected_cells} - {tuple(row["cell"]) for row in zone.trigger_profile.get("openings") or []}
            overlapping = occupied
            if rule.get("height_ft") is not None:
                bottom = int(rule.get("base_altitude_ft", 0))
                top = bottom + int(rule["height_ft"])
                overlapping = {(x, y) for actor in engine.state.actors.values() if actor.active
                               for x, y, z in engine._actor_volume(actor) if bottom <= z*5 < top}
            if rule.get("blocks_movement"):
                blocked |= cells - overlapping
                add_height("BLOCKED", cells - overlapping, rule)
            if rule.get("blocks_sight"):
                opaque |= cells
                add_height("SIGHT_BLOCKED", cells, rule)
            if rule.get("cover"):
                cover |= cells
                add_height("SIMPLE_COVER", cells, rule)
                if rule["cover"] == "three_quarters":
                    deep |= cells
            if rule.get("move_cost"):
                for cell in cells:
                    wall_cost[cell] = max(wall_cost.get(cell, 1), int(rule["move_cost"]))
                    cost[cell] = max(cost.get(cell, 1), int(rule["move_cost"]))
    if "unimpeded_full_costs" in grid.__dict__:  # an unimpeded mover is moving: it keeps ignoring the map's difficult squares
        from .motion import mover_exempt_cells, unimpeded, wall_traversal_cost

        # Named squares are re-read here too: a mid-move zone change must not turn an area-scoped exemption back into
        # the whole-map one (or vice versa).
        mover = engine.state.actors.get(str(grid.__dict__.get("unimpeded_mover") or ""))
        live = mover_exempt_cells(engine, mover)
        # A wall's own price to cross survives an AREA-scoped terrain exemption (``live`` is a set of squares, not the
        # whole-map ``None``): "4 feet of movement for every 1 foot moved" is what crossing the wall costs, not ground
        # underfoot, so the Court's "nonmagical Difficult Terrain costs no extra movement" never discounted it.
        grid.unimpeded_full_costs, cost = cost, unimpeded(cost, live, wall_cost if live is not None else None)
        # combat/motion.py repriced() skips repricing a step when the mover's live exempt squares equal the ones it
        # installed at the start of the move, so the recorded squares must be the ones this map was actually built with.
        # Leaving the intent's opening value here made a refresh while the mover stood outside the area leave a map that
        # charges it for squares the cache says are already free, and it would then overcharge or stop short.
        grid.unimpeded_cells = live
    grid.wall_traversal_cost = wall_cost  # the wall layer, for combat/motion.py repriced/terrain_for mid-move
    grid.blocked, grid.opaque, grid.cover, grid.base_movement_cost = blocked, opaque, cover, cost
    grid.terrain_heights, grid.terrain_spans = heights, spans
    bind(grid, line_sources)
    grid.finite_heights = bool(getattr(grid, 'roof_surfaces', ())) or any(
        height is not None for values in heights.values() for height in values.values())
    engine.__dict__["_cover_three_quarters"] = deep  # derived from the fight's zones, like the grid itself


def query_grid(engine: Any, *, excluded_zone_ids: tuple[str, ...] = ()) -> Any:
    """Independent derived grid for one source-qualified geometry query.

    Movable native objects can omit their own blocking zone while retaining
    overlapping map terrain and every other wall. The live engine/grid and
    authoritative zones are untouched; defaults preserve ordinary sync_walls.
    """
    from copy import copy
    view = copy(engine)
    view.grid = copy(engine.grid)
    sync_walls(view, excluded_zone_ids=excluded_zone_ids)
    return view.grid


def create(ctx: Any, spec: dict[str, Any]) -> ZoneState | None:
    """Place the zone an ability leaves (once per activation) at its aim point, or around its user."""
    engine, actor = ctx.engine, ctx.actor
    from .action_geometry import point
    origin = point(engine, actor)
    if ctx.damage_cache.get(("zone_created", ctx.source)):
        return None
    ctx.damage_cache[("zone_created", ctx.source)] = True
    destination = getattr(ctx.intent, "destination", None)
    targets = [row for row in getattr(ctx, "targets", None) or [] if row is not None and row.entity_id != actor.entity_id]
    if spec.get("centered_on_self"):
        center = origin
    elif destination is not None:
        center = destination
    else:  # an ability aimed at a creature leaves its ground where that creature stands, not under its user
        center = targets[0].position if targets else origin
    zone_id = f"zone:typed:{actor.entity_id}:{engine.state.event_sequence + 1}"
    wall = spec.get("wall")
    if spec.get("menu_parts"):
        from .ext import menus  # the parts a choose-N menu's picked options give the area (combat/ext/menus.py)

        spec = menus.zone_parts(ctx, spec)
    spec = _shaped(ctx, spec)
    zone = prospective_zone(ctx, spec, center, zone_id=zone_id)
    from . import ext
    zone = ext.transform("zone_creation_profile", zone, ctx)
    if wall and (wall.get("object") or {}).get("hp") is not None:
        from .ext.durability import creation_bonus
        from .ext.docket_walls import stats as wall_stats
        bonus = creation_bonus(ctx, "barrier")
        if bonus:
            base_hp = wall_stats(zone)["hp"]
            zone.trigger_profile["wall"] = {**zone.trigger_profile["wall"],
                "object": {**wall["object"], "hp": str(base_hp + bonus)}}
    if wall:
        clear_wall_plan(engine, actor, ctx.source)  # the points it laid out are used up
    from . import ext
    ext.run_strict("zone_created", ctx, zone)
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", ctx.source, actor_id=actor.entity_id, payload={"zone": zone.model_dump(mode="json")})
    conc = actor.concentration
    if zone.concentration_link and conc is not None and conc.source_definition_id == ctx.source:
        if conc.zone_id and conc.zone_id in engine.state.zones and conc.zone_id != zone.zone_id:
            remove(engine, engine.state.zones[conc.zone_id], "REPLACED")
        conc.zone_id = zone.zone_id  # ending the Concentration removes the zone (gate2_engine._end_concentration)
    if wall:
        sync_walls(engine)
    sync_inside(engine, ctx.source)
    return zone


def prospective_zone(ctx: Any, spec: dict[str, Any], center: Position, *, zone_id: str | None = None) -> ZoneState:
    """Pure zone construction shared by actual placement and area-safety previews.

    The caller supplies the effective shape/spec. No payment, event or state
    mutation occurs; geometry, source provenance and recipient predicates match
    the zone that creation commits.
    """
    engine, actor = ctx.engine, ctx.actor
    from .action_geometry import point
    origin = point(engine, actor)
    zone_id = zone_id or f"zone:typed:{actor.entity_id}:{engine.state.event_sequence + 1}"
    duration = spec.get("duration") or {}
    wall = spec.get("wall")
    # Exact cells are a public geometry seam for effects whose area follows an
    # existing footprint. The caller supplies Position values; they are saved
    # with the zone and participate in the same suppression and terrain rules.
    cells = (tuple(spec["cells"]) if spec.get("cells") is not None else
        wall_cells_for(engine, actor, center, int(spec.get("size_ft") or 5), int(wall.get("thick_ft") or 5)) if wall else
        _cells(engine, center, spec, origin))
    from . import zone_sources

    source_profile = zone_sources.capture(spec.get("source_profile"), ctx.numbers)
    zone = ZoneState(
        zone_id=zone_id, source_definition_id=ctx.source, owner_id=actor.entity_id, center=center,
        radius_cells=0 if wall else max(0, int(spec.get("size_ft") or 5) // engine.grid.square_size_ft), affected_cells=cells,
        concentration_link=bool(duration.get("concentration")), duration_rounds=_duration_rounds(duration),
        created_round=engine.state.round_number,
        trigger_profile={"kind": KIND, "name": spec.get("name"), "terrain": list(spec.get("terrain") or []),
                         **({"end_after_owner_turn": actor.turns_started + 1}
                            if duration.get("kind") == "until_end_of_your_next_turn" else {}),
                         "difficult": spec.get("difficult"), "obscured": spec.get("obscured"), "color": spec.get("color"),
                         "follows_owner": bool(spec.get("follows_owner")), "shape": spec.get("shape"), "size_ft": spec.get("size_ft"),
                         **({"height_ft": spec["height_ft"]} if spec.get("height_ft") is not None else {}),
                         # General cone geometry choice survives projection and reload.
                         **({'include_origin': 1} if spec.get('include_origin') else {}),
                         **({"blocks": int(spec["blocks"]),
                             "blocks_along": run_axis(center, origin)} if int(spec.get("blocks") or 1) > 1 else {}),
                         **({"area_vertex": [actor.position.x, actor.position.y, actor.position.z],
                             "width_ft": spec.get("width_ft")} if spec.get("shape") in {"line", "cone"} else {}),
                         **({"spreads": True} if spec.get("spreads") else {}),
                         # A shape laid down at its aim point keeps that placement in the saved fight, so a reloaded
                         # or re-centered area covers the same squares it did when it was cast (a plain 1, never a
                         # float or object: the fight state is JSON-canonical).
                         **({"placed": 1} if spec.get("placed") else {}),
                         "triggers": copy.deepcopy(spec.get("triggers") or []), "move_through": spec.get("move_through"),
                         "talents": list(spec.get("talents") or []), "inside": copy.deepcopy(spec.get("inside") or []),
                         **({"inside_text": list(spec.get("inside_text") or [])} if spec.get("inside_text") else {}),
                         "augments": str((ctx.typed.get("modifier") or {}).get("name") or "").split(" + ") if ctx.typed.get("augments") else [],
                         # The same augments as mechanic ids, so a reader (a plug-in's zone_visual, a client)
                         # can tell which typed rows shaped the area without matching the display names above.
                         "augment_ids": [str(key) for key in ctx.typed.get("augments") or []],
                         "visual": copy.deepcopy(spec.get("visual") or {"material": "generic"}),
                         # A plug-in's own configuration for this area (the material a Ward excludes, the families it
                         # repels). A plain JSON dict copied onto the zone and recorded by the ZONE_CREATED event like
                         # every other profile field, so a saved fight reloads with it; absent for every other area.
                         **({"profile": copy.deepcopy(spec["profile"])} if isinstance(spec.get("profile"), dict) else {}),
                         "numbers": dict(ctx.numbers), **({"wall": dict(wall)} if wall else {}),
                         **({"source_profile": source_profile} if source_profile is not None else {})},
    )
    return zone


# ------------------------------------------------------------------ the talents that shape an area, and what it does inside
SHAPING = "condition:typed.shaping"
ZONE_EFFECT = "condition:typed.zone_effect"


def shaping_of(actor: ActorState, family: str) -> list[str] | None:
    """The talents its user chose for this kind of area ("Shape Darkness"), or None when it has not chosen."""
    for condition in actor.conditions.values():
        if condition.condition_id == SHAPING and (condition.data or {}).get("zone") == family:
            return list((condition.data or {}).get("talents") or [])
    return None


def shape_costs(spec: dict[str, Any], talents: list[str]) -> dict[str, int]:
    """What the chosen talents cost on top of the area itself (Pitch Black: "Pay the normal CP cost of every applied
    talent", and its own 1 CP)."""
    shapes = spec.get("shapes") or {}
    rows = [row for talent in talents for row in (shapes.get(talent) or {}).get("costs") or []]
    if len(talents) > 1:
        rows += list((spec.get("pair") or {}).get("costs") or [])
    need: dict[str, int] = {}
    for resource, amount in rows:
        need[str(resource)] = need.get(str(resource), 0) + int(amount)
    return {resource: amount for resource, amount in need.items() if amount}


def uses_default_shape(engine: Any, actor: Any) -> bool:
    """Only an explicitly AI-controlled caster (or its companion) gets an unchosen talent."""
    modes = getattr(engine, "typed_control_modes", {}) or {}
    owner = actor.owner_id if not actor.primary_combatant else None
    return modes.get(owner or actor.entity_id) in {"LOCAL_AUTO", "API_AUTO"}


def _shaped(ctx: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """An area with the talents that change it (owner 2026-09-27: Numbing Darkness; "pure darkness and pitch black should
    be usable together with any of the darknesses like numbing or hungry"). "Only one Darkness talent normally modifies
    one Darkness area" -- the user's choice (Shape Darkness), or the compiler's default for an unchosen AI caster; Pitch
    Black adds Pure Darkness to one other. Their costs are paid here; a choice it cannot afford leaves the area plain."""
    shaped, need = shaped_spec(ctx.engine, ctx.actor, spec)
    for resource, amount in need.items():
        ctx.engine._spend_resource(ctx.actor, resource, amount, ctx.source)
    return shaped


def shaped_spec(engine: Any, actor: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Pure selected/default zone talents and their affordable additional costs.

    Shared by creation and area-safety previews. The caller accounts for
    activation costs before querying; this function never spends or mutates.
    """
    shapes = spec.get("shapes") or {}
    if not shapes:
        return spec, {}
    chosen = shaping_of(actor, str(spec.get("family") or ""))
    if chosen is None:
        chosen = (spec.get("default_shape") or []) if uses_default_shape(engine, actor) else []
    chosen = [talent for talent in chosen if talent in shapes]
    need = shape_costs(spec, chosen)
    if any(actor.resources.get(resource, 0) < amount for resource, amount in need.items()):
        chosen, need = [], {}
    if not chosen:
        return spec, {}
    rows = [shapes[talent] for talent in chosen]
    veil = next((row["obscured"] for row in rows if row.get("obscured") == "heavy"), None) or next((row["obscured"] for row in rows if row.get("obscured")), None)
    through = next((row["move_through"] for row in rows if row.get("move_through")), None)  # Shadow Slick
    # What the chosen talents' printed inside-clauses say (Pure Darkness's halved senses): text for the zone card, kept
    # apart from ``inside`` so it never becomes a condition on a creature (sync_inside reads that list).
    clauses = [clause for row in rows for clause in row.get("inside_text") or []]
    return {**spec, "talents": [row["name"] for row in rows], **({"obscured": veil} if veil and not spec.get("obscured") else {}),
            **({"move_through": through} if through else {}),
            **({"inside_text": clauses} if clauses else {}),
            "triggers": [*(spec.get("triggers") or []), *[trigger for row in rows for trigger in row.get("triggers") or []]],
            "inside": [*(spec.get("inside") or []), *[rule for row in rows for rule in row.get("inside") or []]]}, need


def prospective_effects(engine: Any, zone: ZoneState, creature: ActorState) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Pure applicable delayed effect groups for area-safety placement risk.

    Use runtime immunity, ownership and per-trigger recipient gates. Each
    group represents a possible exposure, not every future turn summed.

    Every group is returned as ``(trigger_or_rule, effects)`` so a caller reads
    the reviewed roster of the rule that produced the packet (its ``roster`` key,
    see ``_applies``/``roster_scope``). ``_applies`` filters triggers, so the
    surviving groups cannot be lined up against the profile's trigger list by
    position: a misaligned pairing would scope one trigger's packet by another
    trigger's roster. The move-through rule is a group of its own and is never
    dropped from the list.
    """
    if clear_sighted(engine, zone, creature) or not subject_allowed(engine, zone, creature):
        return []
    groups = [(trigger, trigger.get('effects') or []) for trigger in zone.trigger_profile.get('triggers') or []
              if _applies(engine, zone, creature, trigger)]
    rule = zone.trigger_profile.get('move_through')
    if rule and _applies(engine, zone, creature, rule):
        groups.append((rule, _through_effects(rule)))
    return groups


def current_inside_grants(engine: Any, actor: ActorState) -> dict[str, tuple[ZoneState, dict[str, Any]]]:
    """Pure continuous grants at the actor's current position, before reconciliation.

    Return zone/row pairs keyed like persisted zone-effect conditions. Apply the
    reconciler's geometry, active-actor, recipient, immunity and newest-copy
    policy without emitting events or reading stale inside conditions. Consumers
    may query during landed movement before sync_inside updates stored grants.

    Within one read-only query frame the answer for one unchanged projected
    creature is shared: several plug-in hooks ask this same question for the
    same square (terrain exemption, Speed, continuous effects). Held objects keep
    their identity alive for the frame, so a recycled id cannot alias a stale
    answer. Outside a query frame every call computes afresh.
    """
    from .read_queries import shared_query
    from .space import point

    key = ('zone_inside_grants', id(actor), point(actor.position), bool(actor.active))
    return shared_query(engine, key, lambda: _current_inside_grants(engine, actor), refs=(actor,))


def _current_inside_grants(engine: Any, actor: ActorState) -> dict[str, tuple[ZoneState, dict[str, Any]]]:
    from . import concentration

    newest: dict[tuple[str, str, str, str], tuple[int, ZoneState, dict[str, Any]]] = {}
    if actor.active:
        for zone in typed_zones(engine):
            if not zone.trigger_profile.get("inside") or not _inside(engine, actor, zone):
                continue
            if clear_sighted(engine, zone, actor) or not subject_allowed(engine, zone, actor):
                continue
            order = int(zone.zone_id.rsplit(":", 1)[-1]) if zone.zone_id.rsplit(":", 1)[-1].isdigit() else 0
            technique = concentration.technique_of(engine, zone.source_definition_id)
            # Same technique's effect applies once, from its newest eligible copy.
            for row in zone.trigger_profile["inside"]:
                if not continuous_rule_applies(engine, zone, actor, row):
                    continue
                same = (zone.owner_id, technique, str(row.get("id")), str(row.get("name")))
                if same not in newest or order > newest[same][0]:
                    newest[same] = (order, zone, row)
    return {f"{zone.zone_id}|{row.get('id')}": (zone, row) for _order, zone, row in newest.values()}


def sync_inside(engine: Any, source: str = "zone", *, removals_only: bool = False) -> None:
    """Reconcile continuous area effects, including nested ending cascades.

    A removal subscriber may reconcile again before its parent finishes. Mark
    that pass dirty and settle it afterward instead of replaying a stale plan.
    Individual effect endings use removals_only to retire obsolete membership
    without recreating a continuous effect that was deliberately suppressed or
    removed. Area/movement callers retain full reconciliation. A nested full
    request upgrades the pending pass. No pending state is serialized; errors
    unwind the owning transaction.
    """
    if getattr(engine, "_syncing_zone_inside", False):
        engine._zone_inside_dirty = True
        if not removals_only:
            engine._zone_inside_full = True
        return
    engine._syncing_zone_inside = True
    engine._zone_inside_full = not removals_only
    try:
        for _ in range(64):
            engine._zone_inside_dirty = False
            _sync_inside_pass(engine, source, removals_only=not engine._zone_inside_full)
            if not engine._zone_inside_dirty:
                return
        from .ext import CheckpointError
        raise CheckpointError("Area effects did not settle; the action was cancelled.")
    finally:
        engine._syncing_zone_inside = False
        engine._zone_inside_dirty = False
        engine._zone_inside_full = False


def _sync_inside_pass(engine: Any, source: str, *, removals_only: bool) -> None:
    """What an area does to every creature inside it for as long as it stays there ("Creatures inside your Darkness have
    Disadvantage on Strength, Dexterity, and Constitution ability checks and saving throws"): a condition carrying that
    rule, added when a creature is inside and taken away when it leaves or the area ends. Called after anything moves,
    and whenever an area is made, moved or ended; each change is an event, so a reloaded fight has them too.
    The pure zone_subject_allowed veto also excludes continuous rows and their
    modifiers. Owning plug-ins call this reconciler when eligibility changes:
    only zone-derived effects are removed, and eligible effects resume once."""
    for actor in engine.state.actors.values():
        want = current_inside_grants(engine, actor)
        have = {str((condition.data or {}).get("key")): iid for iid, condition in actor.conditions.items() if condition.condition_id == ZONE_EFFECT}
        for key, iid in have.items():
            if key not in want:
                condition = actor.conditions.get(iid)
                if condition is None:
                    continue
                # Disarm membership before nested modifier/condition observers
                # reconcile this same area; keep the exact removed provenance.
                del actor.conditions[iid]
                for mid in condition.data.get("zone_modifiers") or []:
                    engine._remove_modifier_instance(actor, mid, condition.source_definition_id, actor_id=actor.entity_id,
                        payload={"modifier_id": mid, "reason": "LEFT_ZONE"})
                engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid},
                                     _ended_effect=condition.model_dump(mode="json"))
        if removals_only:
            continue
        for key, (zone, row) in want.items():
            if key not in have and not any(c.condition_id == ZONE_EFFECT and (c.data or {}).get("key") == key
                                           for c in actor.conditions.values()):
                before = set(actor.modifiers)
                for modifier in row.get("modifiers") or []:
                    engine._add_modifier(actor, zone.source_definition_id, modifier["field"], "SET", modifier["value"],
                                         "WHILE_INSIDE_ZONE", expires_on="UNTIL_REMOVED")
                engine._apply_condition(actor, ZONE_EFFECT, zone.source_definition_id, zone.owner_id, expires_on="UNTIL_REMOVED",
                                        data={"key": key, "zone_id": zone.zone_id, "name": row.get("name"), "reading": row.get("reading"),
                                              "rule": dict(row.get("rule") or {}), "muffles": bool(row.get("muffles")),
                                              "zone_modifiers": sorted(set(actor.modifiers) - before)})


def muffled(engine: Any, actor: ActorState) -> bool:
    """Whether it stands where sound is dimmed (Pure Darkness: "Wisdom (Perception) checks relying on hearing have
    Disadvantage")."""
    return any(condition.condition_id == ZONE_EFFECT and (condition.data or {}).get("muffles") for condition in actor.conditions.values())


def remove(engine: Any, zone: ZoneState, reason: str) -> None:
    if not zone.active:
        return
    zone.active = False
    engine._append_event("ZONE_REMOVED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone_id": zone.zone_id, "reason": reason})
    # Native ending dispatch owns wall aftermath and inside reconciliation once.


def typed_zones(engine: Any) -> list[ZoneState]:
    from .read_queries import shared_query

    def collect():
        return [zone for zone in sorted(engine.state.zones.values(), key=lambda row: row.zone_id)
                if zone.active and zone.trigger_profile.get("kind") == KIND] + map_zones(engine) + _hooked_zones(engine)

    return list(shared_query(engine, ('typed_zones',), collect))


def _hooked_zones(engine: Any) -> list[ZoneState]:
    """Areas a plug-in works out from the fight as it stands, never stored (an aura centered on its owner: combat/ext
    hook "zones", docket 2026-09-28)."""
    from . import ext

    if not ext.has("zones"):
        return []
    return [zone for rows in ext.run("zones", engine) for zone in rows or []]


def _inside(engine: Any, actor: ActorState, zone: ZoneState, position: Position | None = None) -> bool:
    """Membership for one unchanged projected creature and one area.

    Membership is a pure query over the creature's volume and the area's stored
    geometry, so a read-only frame shares it between the hooks that ask the same
    question (obscurement, continuous grants, terrain exemption). Both objects
    stay referenced for the frame; outside a frame every call computes afresh.
    """
    from .read_queries import shared_query
    from .space import point

    key = ('zone_inside', id(actor), id(zone), point(actor.position),
           point(position) if position is not None else None)
    from .spatial_areas import zone_contains
    return shared_query(engine, key, lambda: zone_contains(engine, actor, zone, at=position),
                        refs=(actor, zone))


def actor_inside_zone(engine: Any, actor: ActorState, zone: ZoneState, position: Position | None = None) -> bool:
    """Whether ``actor`` (at ``position`` or its current cell) lies inside ``zone``.

    Public name for plug-ins; delegates to the same area test the engine uses.
    """
    return _inside(engine, actor, zone, position)


def _hostile(engine: Any, zone: ZoneState, actor: ActorState) -> bool:
    if zone.owner_id == MAP_OWNER:
        return True  # the map's own terrain takes no side
    owner = engine.state.actors.get(zone.owner_id)
    if owner is not None and zone.trigger_profile.get("formation"):
        from .ext import formations  # a formation array's keyed creatures are not its hostile ones (Gate Keeper)

        return formations.hostile_to(engine, zone, actor)
    return owner is not None and owner.team_id != actor.team_id


MAP_OWNER = "map"


def map_zones(engine: Any) -> list[ZoneState]:
    """Named terrain painted on a tabletop map (owner 2026-09-28: "a map editor mode so i can make maps with the
    materials"; combat/tabletop.py to_battlefield "map_terrain"): an area with that terrain's rules (difficult ground,
    obscurement, what moving through it does) for the whole fight. Like the map's walls and grid, it is read from the
    fight's sealed arena, so a reloaded or replayed fight has exactly the same ground. Entry/start usage alone is
    persisted as inactive MAP_TERRAIN_USAGE records, excluded from gameplay zone queries; the ground stays derived.
    It has no creator: the map's own save DC and Proficiency Bonus stand in, and it takes no side."""
    cached = engine.__dict__.get("_map_zones")
    if cached is not None:
        for zone in cached:
            persisted = engine.state.zones.get(zone.zone_id)
            if persisted is not None:
                zone.per_turn_triggered = copy.deepcopy(persisted.per_turn_triggered)
            enter_start = (terrain_rules().get("terrains", {}).get(
                str((zone.trigger_profile.get("terrain") or [""])[0])) or {}).get("enter_start") or {}
            if enter_start and not enter_start.get("from_ability"):
                _restore_legacy_map_usage(engine, zone)
        return cached
    rows = (getattr(engine, "battlefield_document", None) or {}).get("map_terrain") or []
    terrains = terrain_rules().get("terrains") or {}
    cached = []
    for index, row in enumerate(rows):
        rule = terrains.get(str(row.get("terrain") or ""))
        cells = tuple(Position(x=int(x), y=int(y)) for x, y in row.get("cells") or [] if engine.grid.in_bounds((int(x), int(y))))
        if not rule or not cells:
            continue
        enter_start = rule.get("enter_start") or {}
        triggers = []
        if enter_start and not enter_start.get("from_ability"):
            triggers.append({
                "id": f"zone:map:{index + 1}:terrain", "name": "terrain",
                "on": ["enter", "start"], "who": enter_start.get("who") or "hostile",
                "effects": [{
                    "type": "save", "ability": enter_start.get("ability") or "DEX",
                    "on_fail": copy.deepcopy(enter_start.get("on_fail") or []),
                    "on_success": copy.deepcopy(enter_start.get("on_success") or []),
                }],
            })
        zone_id = f"zone:map:{index + 1}"
        persisted_usage = engine.state.zones.get(zone_id)
        usage = copy.deepcopy(persisted_usage.per_turn_triggered) if persisted_usage else {}
        cached.append(ZoneState(
            zone_id=f"zone:map:{index + 1}", source_definition_id="system:battlefield.terrain", owner_id=MAP_OWNER, center=cells[0],
            radius_cells=0, affected_cells=cells, concentration_link=False, duration_rounds=None, created_round=0,
            per_turn_triggered=usage,
            trigger_profile={"kind": KIND, "name": str(row["terrain"]).title(), "terrain": [row["terrain"]],
                             "difficult": "all" if rule.get("difficult") else None, "obscured": rule.get("obscured"), "color": rule.get("color"),
                             "follows_owner": False, "shape": "painted", "size_ft": 5, "triggers": triggers,
                             "move_through": copy.deepcopy(rule.get("move_through")), "talents": [], "inside": [], "map": True,
                             "natural_haze": bool(row.get("natural_haze")),
                             "visual": {"material": rule.get("material") or "generic"},
                             "numbers": {"save_dc": int(row.get("save_dc") or 13), "pb": int(row.get("pb") or 2), "cl": 1}},
        ))
    engine.__dict__["_map_zones"] = cached
    for zone in cached:
        enter_start = (terrain_rules().get("terrains", {}).get(
            str((zone.trigger_profile.get("terrain") or [""])[0])) or {}).get("enter_start") or {}
        if enter_start and not enter_start.get("from_ability"):
            _restore_legacy_map_usage(engine, zone)
    return cached


def _restore_legacy_map_usage(engine: Any, zone: ZoneState) -> None:
    """Restore current-turn map hazards from pre-snapshot PASSIVE_TRIGGERED events."""
    trigger_id = f"{zone.zone_id}:terrain"
    turn_started_at = max((i for i, event in enumerate(engine.events)
                           if event.event_type == "TURN_STARTED"), default=-1)
    for event in engine.events[turn_started_at + 1:]:
        if event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("zone_id") == zone.zone_id:
            for creature_id in event.target_ids:
                zone.per_turn_triggered[f"{trigger_id}:{creature_id}"] = _turn_key(engine)


def _marked_by_owner(zone: ZoneState, actor: ActorState, mark: str) -> bool:
    """"creatures bearing your Beauty Mark treat the area as difficult terrain" (Aura of Unapproachable Elegance): difficult only for
    a creature that bears the named mark the zone's creator placed (the zone's ``difficult`` is "marked:<mark name>")."""
    from .typed_executor import bears_mark

    return bears_mark(actor, zone.owner_id, mark)


def zone_is_difficult(engine: Any, zone: ZoneState, actor: ActorState, *, nonmagical_ignored: bool | None = None) -> bool:
    """Whether this one area costs ``actor`` extra movement, read with exactly the rules difficult_cells uses.

    Public seam (docket 2026-10-05): an ability that exempts its own ground still has to know whether
    *another* area on the same square charges this creature, because difficult_cells unions every area's
    squares before subtracting exemptions. Such a plug-in asks here instead of reading ``difficult`` again,
    so ground that does not reach this creature -- a policy aimed at other creatures, a marked-creature
    policy whose mark this creature does not bear, ground it ignores as nonmagical -- is never mistaken for
    ground that still costs. ``nonmagical_ignored`` passes the one answer difficult_cells already computed
    (combat/motion.py ignores_difficult) so a fight with many map terrains asks it once per creature.

    Whole-square exemptions (the ``difficult_exempt`` plug-in hook) are decided by difficult_cells, not here:
    this answers one area's own policy, so it is safe to call from such a hook.
    """
    # A route search asks the same recipient policy for every destination.
    # Non-projected actors/areas are unchanged during this pure query; projected
    # footprint subjects retain distinct identity and position. Hold references
    # to prevent temporary-object id reuse. Outside a query nothing is cached.
    from .read_queries import memo
    from .space import point
    return memo(engine, ('zone_difficult_policy', id(zone), id(actor), point(actor.position), nonmagical_ignored),
                lambda: (zone, actor, _zone_is_difficult(engine, zone, actor,
                                         nonmagical_ignored=nonmagical_ignored)))[2]


def _zone_is_difficult(engine, zone, actor, *, nonmagical_ignored=None):
    """Uncached policy body for zone_is_difficult's call-local query seam."""
    from . import motion

    if motion.ignores_area_difficult(engine, actor):
        return False  # Juggernaut: "ignore difficult terrain" -- the map's and any area's
    targets = zone.trigger_profile.get("difficult_target_ids")
    if targets is not None and actor.entity_id not in targets:
        return False
    rule = zone.trigger_profile.get("difficult")
    from . import ext

    if ext.has("difficult_zone_exempt") and any(
            answer is True for answer in ext.run("difficult_zone_exempt", engine, actor, zone)):
        return False
    if isinstance(rule, dict):
        return _applies(engine, zone, actor, rule)
    if zone.owner_id == MAP_OWNER and rule:
        plain = motion.ignores_difficult(engine, actor) if nonmagical_ignored is None else nonmagical_ignored
        if plain:
            return False  # terrain painted on the map is nonmagical (Unimpeded Positioning, Silent Step)
    return bool(rule == "all" or rule == "hostile" and _hostile(engine, zone, actor)
                or (isinstance(rule, str) and rule.startswith("marked:")
                    and _marked_by_owner(zone, actor, rule[7:])))


def difficult_cells(engine: Any, actor: ActorState) -> set[tuple[int, int]]:
    """Squares that cost double to ``actor``: all, hostile, or explicitly targeted terrain.

    Optional ``difficult_target_ids`` restricts either terrain policy to those
    actor ids. Absent the field, existing areas keep their usual policy. This
    supports creature-specific Forms and other individually targeted areas.

    Two ways an ability can excuse ground, and they answer different
    questions. ``difficult_zone_exempt`` is asked about one area at a time and
    decides whether that area's ground costs anything, so it survives an
    overlap: a square one area excuses still costs when a second, unexcused
    difficult area covers the same ground (Source's Quarry Walker over stony
    map rubble, with a magical stone area laid over it). ``difficult_exempt``
    instead names squares outright ("ignore difficult terrain"), which beats
    every area, so it is applied to the finished set.
    """
    from .motion import exempt_cells

    cells, ability = _difficult_sources(engine, actor)
    if cells:
        cells -= exempt_cells(engine, actor)
    if ability:
        ability -= exempt_cells(engine, actor, terrain="magical")
    return cells | ability


def nonmagical_difficult_cells(engine: Any, actor: ActorState) -> set[tuple[int, int]]:
    """Map-owned difficult ground without applicable ability-created overlap.

    Earth Packed Road Step uses this pure source query while answering
    difficult_exempt. It never calls that hook or subtracts its exemptions.
    Movement pricing uses the same source classification below.
    """
    cells, ability = _difficult_sources(engine, actor)
    return cells - ability


def explicitly_nonmagical_difficult_cells(engine: Any, actor: ActorState) -> set[tuple[int, int]]:
    """Squares where every applicable difficult-ground source is explicitly mundane.

    Map-painted terrain is nonmagical. For character-created areas, only a
    sealed ``mundane: 1`` source qualifies; magical and unknown sources keep
    the square costly when they overlap mundane ground. This is a pure source
    classification query for effects that exempt nonmagical terrain, including
    movement abilities that cover both map terrain and mundane areas.
    """
    from .ext.area_suppression import magical

    mundane: set[tuple[int, int]] = set()
    other: set[tuple[int, int]] = set()
    for zone in typed_zones(engine):
        if not zone_is_difficult(engine, zone, actor):
            continue
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        if zone.owner_id == MAP_OWNER or magical(zone) is False:
            mundane.update(cells)
        else:
            other.update(cells)
    return mundane - other


def _difficult_sources(engine: Any, actor: ActorState) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Shared applicable map/ability terrain sources before square exemptions."""
    from . import ext
    from .motion import ignores_area_difficult, ignores_difficult

    cells: set[tuple[int, int]] = set()
    ability: set[tuple[int, int]] = set()  # ground an ability made: only a benefit that ignores ALL difficult
    # terrain covers it, so it is subtracted with the "magical" scope below
    if ignores_area_difficult(engine, actor):
        return cells, ability  # Juggernaut: "ignore difficult terrain" -- the map's and any area's
    plain = None  # whether it ignores nonmagical difficult terrain (combat/motion.py), asked once
    for zone in typed_zones(engine):
        made = zone.owner_id != MAP_OWNER
        if plain is None and not made and zone.trigger_profile.get("difficult"):
            plain = ignores_difficult(engine, actor)
        if zone_is_difficult(engine, zone, actor, nonmagical_ignored=plain):
            (ability if made else cells).update((cell.x, cell.y) for cell in zone.affected_cells)
    return cells, ability


def _turn_key(engine: Any) -> int:
    return engine.state.round_number * 1000 + engine.state.current_slot_index


def subject_allowed(engine: Any, zone: ZoneState, creature: ActorState) -> bool:
    """Pure eligibility for a map/typed zone's triggered and continuous effects.

    Plug-ins may veto before rolls, trigger accounting or effects; no handler
    preserves existing zone behavior. Zone ownership stays explicit even when
    map terrain uses its recipient as a synthetic caster for typed arithmetic.
    sync_inside reconciles its owned conditions/modifiers through this same
    query; plug-ins must request reconciliation when their eligibility changes.
    """
    from . import ext

    return not ext.has("zone_subject_allowed") or not any(
        answer is False for answer in ext.run("zone_subject_allowed", engine, zone, creature))
def _runtime_marks(zone: ZoneState, creature: ActorState) -> dict[str, int]:
    """Counters live in recorded state, never the derived map-zone cache.

    Actor runtime receipts capture/restore these primitive turn flags. Map
    geometry stays sealed; queries never create counters.
    """
    if zone.trigger_profile.get('map'):
        return creature.turn_flags.setdefault('map_zone_runtime:' + zone.zone_id, dict(zone.per_turn_triggered))
    return zone.per_turn_triggered


def _run(engine: Any, zone: ZoneState, creature: ActorState, trigger: dict[str, Any], moment: str) -> None:
    from .paid_relocation import activation

    # Standing areas are separate deliveries, including the creator's own
    # older areas. Map terrain has no creature responsible for its effects.
    owner = None if zone.owner_id == MAP_OWNER else engine.state.actors.get(zone.owner_id)
    with activation(engine, owner, zone.source_definition_id, independent=True):
        _run_trigger(engine, zone, creature, trigger, moment)


def delayed_area_effect_context(engine: Any, zone: ZoneState, creature: ActorState, *, typed: dict[str, Any],
                                owner: Any, action: Any, intent: Any, moment: str) -> Any:
    """Build the shared context for a delayed area effect activation.

    A zone trigger is a new activation, separate from the action that created
    the zone. Stored creator numbers remain sealed for saves and damage, but
    Qi Technique Potency was paid for the creating action and must not be
    added again. Native zone triggers and plug-in dispatchers both use this
    helper so the delayed-activation rule stays consistent across areas.
    """
    from . import ext, typed_executor
    ctx = typed_executor.Context(engine, owner, action, intent, typed, [creature], creature,
                                 {"_potency_used": True})
    ext.run_strict("zone_trigger_context", ctx, zone, creature, moment)
    return ctx


def _run_trigger(engine: Any, zone: ZoneState, creature: ActorState, trigger: dict[str, Any], moment: str) -> None:
    """One trigger on one creature, once per turn (per zone and trigger); once per round when the talent says so (Hungry
    Darkness: "A creature may take this damage only once per round, regardless of how often it enters or leaves");
    ``requires_mark`` gates before spending a trigger; ``once_per_creature`` limits it to this activation.
    ``first_each_round``: once per round for the whole area, whichever creature comes first."""
    if not subject_allowed(engine, zone, creature):
        return
    if trigger.get("requires_mark") and not _marked_by_owner(zone, creature, str(trigger["requires_mark"])):
        return
    key = f"{trigger.get('id') or trigger.get('name')}:{creature.entity_id}"
    when = -engine.state.round_number if trigger.get("per_round") else _turn_key(engine)
    marks = _runtime_marks(zone, creature)
    if trigger.get("first_each_round"):
        # "The first hostile creature each round that enters the area or starts its turn there" (Wax's Soft Spread, riders lane 5):
        # one creature a round for the whole area, not one per creature.
        key, when = f"{trigger.get('id') or trigger.get('name')}:first", -engine.state.round_number
    if marks.get(key) == when or trigger.get("once_per_creature") and key in marks:
        return
    marks[key] = when
    # The map's own terrain has no creator: what it does to a creature is worked out as that creature's (its numbers are
    # the map's DC and Proficiency Bonus).
    owner = creature if zone.owner_id == MAP_OWNER else engine.state.actors.get(zone.owner_id)
    action = engine.action_catalog.get(zone.source_definition_id) or (_map_action(creature) if zone.owner_id == MAP_OWNER else None)
    if owner is None or action is None:
        return
    typed = {"effects": copy.deepcopy(trigger.get("effects") or []), "numbers": dict(zone.trigger_profile.get("numbers") or {}),
             "weapon": None, "duration": {"kind": "instant"}, "riders": [], "source": trigger.get("id") or zone.source_definition_id,
             "_area_centre": (zone.center.x, zone.center.y)}  # "pulled 10 feet toward the center" (typed_executor._push)
    from .area_recipients import delayed_area_context
    typed.update(delayed_area_context(engine, zone, typed["effects"], who=trigger.get("roster")))
    payload = {"zone_id": zone.zone_id, "trigger": trigger.get("name"), "moment": moment}
    if zone.owner_id == MAP_OWNER and moment in {"enter", "start"}:
        # Map zones are derived from the sealed battlefield, so persist only their usage record.
        # PASSIVE_TRIGGERED already replays a zone_after snapshot into state.zones.
        usage = zone.model_copy(deep=True)
        usage.active = False
        usage.trigger_profile["kind"] = "MAP_TERRAIN_USAGE"
        usage.per_turn_triggered.update(marks)
        engine.state.zones[usage.zone_id] = usage
        payload["zone_after"] = usage.model_dump(mode="json")
    engine._append_event("PASSIVE_TRIGGERED", zone.source_definition_id, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                         payload=payload)
    # Turn-boundary payloads retain the accepted transaction's player answers.
    # A zone trigger is its own activation, not the Qi-powered activation that placed the area, so it
    # never spends that activation's Qi Technique Potency. The creator's numbers (including
    # "potency") are stored on the area, so the flag is what keeps the key modifier off the save.
    ctx = delayed_area_effect_context(engine, zone, creature, typed=typed, owner=owner, action=action,
                                      intent=getattr(engine, "_active_intent", None), moment=moment)
    # What an area does to a creature is one general kind of delivery (a standing area, named by its
    # zone id), so a printed "damage from an environmental hazard" limit can tell an area from a
    # creature's own attack. Transient and restored; combat/ext/damage_delivery.py.
    with damage_delivery.delivering(engine, typed["source"], hazard=damage_delivery.AREA, area=zone.zone_id):
        from . import typed_executor
        typed_executor.run_effects(ctx, typed["effects"])


def clear_sighted(engine: Any, zone: ZoneState, creature: ActorState) -> bool:
    """Whether one of the creature's own abilities makes it immune to the negative effects this area's talents create
    (Clearsight: "the target is immune to negative effects created by your Darkness talents"). A pure query asked for
    the area's own creator by the continuous inside rows (``sync_inside``), the area's triggers (``_fire``), movement
    through the area, the AI hazard test and the Dark sphere's Darkvision reading (``combat/senses.py``). The owning
    plug-in decides, through the documented ``zone_talent_immune`` hook, so no ability is named here."""
    from . import ext

    if not ext.has("zone_talent_immune"):
        return False
    return any(ext.run("zone_talent_immune", engine, zone, creature))


def _map_action(creature: ActorState) -> Any:
    from .gate2_runtime_models import ActionDefinition, EconomyKind

    return ActionDefinition(source_definition_id="system:battlefield.terrain", display_name="Map terrain", owner_id=creature.entity_id,
                            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", parameters={})


def _applies(engine: Any, zone: ZoneState, creature: ActorState, trigger: dict[str, Any], *, default_who="hostile") -> bool:
    """Shared trigger/continuous recipients, owner harm policy and eligibility veto.

    Triggers default to foes; continuous rules default to everyone. Benefits and
    unclassified rules retain their saved roster. Owner overrides never bypass
    zone_recipient_allowed, zone_subject_allowed or talent immunity.
    """
    # General owner/data recipient seam for delayed area harm. Mixed packets
    # keep their original roster; their leaf effects use the transient context.
    # Only a hazard packet that is delivered (a trigger, or a move-through rule
    # carrying its own effects) takes the area's harm roster. A continuous
    # "inside" row states its own roster and is not a delivery: Pure Darkness's
    # hearing clause applies to everyone inside, its maker included, however
    # hostile the area's damage trigger is.
    # A trigger whose roster the reviewed data declares keeps it: the roster is
    # its own key ("roster"), not the derived "who" policy above. The seam fills
    # in a packet whose recipients are unscoped, it does not replace an explicit
    # "any"/"ally" roster with the enemies-only default (2026-10-20: Turbulent
    # Field's reviewed "who": "any" was narrowed to hostile, so neither
    # teammates nor the Field's own owner could trigger it). A compiler-derived
    # "who" (for example its enemies-only fallback) is only eligibility policy,
    # so a printed "each creature" packet still reaches everyone.
    declared = trigger.get("roster")
    who = declared or trigger.get("who") or default_who
    effects = trigger.get("effects") or []
    from .area_recipients import delayed_area_context
    from .effect_harm import classify_effect
    # A reviewed roster names who may take the packet, but an owner ruling
    # (area_recipient_overrides) outranks it, exactly as scoped_area applies
    # the ruling before the roster for the packet's own recipients.
    if effects:
        harmful_packet = all(classify_effect(row, ignore_self=True) is True for row in effects)
        # Only a harmful packet takes the area's harm roster. A benefit-only
        # trigger declared for allies keeps its own roster: the area's printed
        # "each creature" harm scope is permission for its harm, not for a
        # healing row, so reading it here would widen a benefit to enemies.
        context = delayed_area_context(engine, zone, effects, who=declared) if harmful_packet else None
        if context:
            scope = context["area"].get("harmful_recipient_override", context["area"].get("harmful_recipients"))
            if scope == "all":
                who = "any"
            elif scope == "hostile" or declared is None:
                who = "hostile"
    elif classify_effect(trigger) is True:
        # A harmful continuous "inside" row states its own roster, but an owner
        # ruling on the area still outranks it, exactly as it outranks the row's
        # own packet when the ruling narrows or widens who the harm reaches.
        # Only an actual ruling changes this row's eligibility: a benefit or an
        # unclassified row keeps its saved roster untouched.
        context = delayed_area_context(engine, zone, [trigger])
        if context:
            from .area_recipient_rules import recipient_override
            ruling = recipient_override(context.get("area_recipient_context") or {})
            if ruling:
                who = "any" if ruling["recipients"] == "everyone" else "hostile"
    from .zone_subjects import allowed
    return (who == "any" or (who == "ally") != _hostile(engine, zone, creature)) and allowed(engine, zone, creature, trigger)


def _fire(engine: Any, zone: ZoneState, creature: ActorState, moment: str) -> None:
    if not creature.active or engine.state.terminal_result is not None or clear_sighted(engine, zone, creature):
        return
    for trigger in zone.trigger_profile.get("triggers") or []:
        if moment in (trigger.get("on") or []) and _applies(engine, zone, creature, trigger):
            _run(engine, zone, creature, trigger, moment)
            if not creature.active or engine.state.terminal_result is not None:
                return


def continuous_rule_applies(engine: Any, zone: ZoneState, creature: ActorState, rule: dict[str, Any]) -> bool:
    """Pure continuous-rule policy for reconciliation and terrain plug-ins.

    Geometry is checked by the caller. Harmful owner rulings and all existing
    subject/talent/row vetoes apply; benefits keep their declared recipients.
    """
    return (not clear_sighted(engine, zone, creature) and subject_allowed(engine, zone, creature)
            and _applies(engine, zone, creature, rule, default_who="any"))


def fire_trigger(engine: Any, zone: ZoneState, creature: ActorState, moment: str) -> None:
    """Run a zone's declared trigger with its normal eligibility/usage guards.

    Public seam for custom moments (for example a creature using a technique);
    entry and turn-start triggers use the same guarded dispatcher internally.
    No trigger matching the moment means no effect.
    """
    _fire(engine, zone, creature, moment)


def expire_owned_zones(engine: Any, actor: ActorState) -> None:
    """Shared real/nominal slot expiry; no damage, movement or zone-entry callbacks."""
    for zone in typed_zones(engine):
        if zone.owner_id == actor.entity_id and zone.duration_rounds and engine.state.round_number - zone.created_round >= zone.duration_rounds:
            remove(engine, zone, "DURATION_ENDED")


def on_turn_start(engine: Any, actor: ActorState) -> None:
    """A creature's turn begins: its own zones whose rounds have run out end; openings it made in a wall close; it may
    start its turn inside a zone."""
    close_openings(engine, actor)
    sync_walls(engine)
    expire_owned_zones(engine, actor)
    # Owner data can change without movement or a service restart. Reconcile
    # continuous harm before start-turn packets use that same current policy.
    sync_inside(engine, "zone")
    for zone in typed_zones(engine):
        if actor.active and _inside(engine, actor, zone):
            _fire(engine, zone, actor, "start")


def attack_mode(engine: Any, attacker: ActorState, target: ActorState) -> str | None:
    """Heavily obscured areas and magical darkness (2024 rules): a creature is effectively Blinded to what is inside the
    area. An attack at a target inside one has Disadvantage (the attacker can't see it); an attacker inside one attacking
    out has Advantage (the target can't see it); both inside, or neither, cancel out."""
    modes = attack_modes(engine, attacker, target)
    return modes[0] if len(modes) == 1 else None


def attack_modes(engine: Any, attacker: ActorState, target: ActorState) -> tuple[str, ...]:
    """Pure uncancelled obscuration contributions for selective removal.

    Being unable to see the target and being unseen by it are independent. Keep
    both until the native removal policy runs; attack_mode retains the original
    combined result for callers that do not remove individual contributions.
    """
    through = _through_obscuring_wall(engine, attacker, target)
    heavy = _heavy(engine)
    attacker_blocked = observer_blocked(engine, attacker, target)
    target_blocked = observer_blocked(engine, target, attacker)
    if not heavy and not attacker_blocked and not target_blocked:
        return ('DISADVANTAGE',) if through else ()
    unseen_target = through or attacker_blocked or any(_blocks(engine, zone, attacker, target) for zone in heavy)
    unseen_attacker = target_blocked or any(_blocks(engine, zone, target, attacker) for zone in heavy)
    return tuple(mode for mode, applies in (('DISADVANTAGE', unseen_target), ('ADVANTAGE', unseen_attacker)) if applies)


def _blocks(engine: Any, zone: ZoneState, viewer: ActorState, seen: ActorState, *, sight_only: bool = False) -> bool:
    """Whether the area keeps ``viewer`` from seeing ``seen``: it can't see into it, and two creatures inside can't see
    each other; one inside sees out. Directional Darkness ("Creatures outside see inward clearly") turns that around:
    those outside see in, and those inside can't see out."""
    if obscuration_ignored(engine, zone, viewer, seen):
        return False
    profile = zone.trigger_profile
    if viewer.entity_id in profile.get("lightly_obscured_viewer_ids", ()) or obscurement_ignored(engine, zone, viewer, seen):
        return False
    if profile.get("owner_sees") and (viewer.entity_id == zone.owner_id or (
            profile.get("team_sees") and (owner := engine.state.actors.get(zone.owner_id)) is not None and owner.team_id == viewer.team_id)):
        return False  # "You see normally through your own Smoke Veil" (and the creatures it chose see it only lightly obscured)
    inward = (profile.get("visual") or {}).get("sees") == "inward"
    viewer_in, seen_in = _inside(engine, viewer, zone), _inside(engine, seen, zone)
    if (viewer_in or seen_in) and senses.pierces(engine, zone, viewer, seen, sight_only=sight_only):
        return False  # Darkvision through plain Darkness, Blindsight, Truesight within range (combat/senses.py)
    if (viewer_in or seen_in) and (profile.get("visual") or {}).get("darkness") and _lifted(engine, zone, viewer, seen):
        return False  # a plug-in's light that suppresses this darkness here (combat/ext/radiance.py)
    if viewer_in and seen_in:
        return True
    if seen_in:
        return not inward
    return viewer_in and inward


def obscurement_ignored(engine: Any, zone: ZoneState, viewer: ActorState, seen: ActorState) -> bool:
    """Pure observer/subject exemption from this area's visual obscurement only."""
    from . import ext
    return ext.has("obscurement_ignored") and any(answer is True for answer in
        ext.run_strict("obscurement_ignored", engine, zone, viewer, seen))


def _lifted(engine: Any, zone: ZoneState, viewer: ActorState, seen: ActorState) -> bool:
    from . import ext

    return ext.has("darkness_lifted") and any(ext.run("darkness_lifted", engine, zone, viewer, seen))


def _heavy(engine: Any) -> list[ZoneState]:
    """Areas heavily obscured, or magically dark, for everyone in them.

    The list is fixed for one unchanged set of areas, so a read-only frame shares
    it between every observer/target pair it checks.
    """
    from .read_queries import shared_query

    return list(shared_query(engine, ('zone_heavy',), lambda: [
        zone for zone in typed_zones(engine)
        if not zone.trigger_profile.get("wall")
        and (zone.trigger_profile.get("obscured") == "heavy"
             or (zone.trigger_profile.get("visual") or {}).get("darkness"))]))


def hidden_from(engine: Any, viewer: ActorState, target: ActorState, *, sight_only: bool = False) -> bool:
    """Whether ``viewer`` can't see ``target`` for obscurement: it stands in darkness or a heavy cloud, or behind a wall of
    smoke or darkness from the viewer (line of sight itself is the grid's; combat/stealth.py).

    ``sight_only`` passes the visual-only sense filter through both area and wall
    policy. Ownership, direction, light suppression and observer restrictions
    are shared unchanged; the default retains combat sight permissions.
    """
    from .read_queries import shared_query
    from .space import point

    # A scoped plug-in sight route can be action-specific, exactly as in
    # senses.perceives, so the owning action is part of this answer's inputs.
    frame = getattr(engine, '_shot_geometry', None)
    sight_action = (str(frame['action'].source_definition_id)
                    if frame and frame.get('actor_id') == viewer.entity_id else None)
    key = ('zones.hidden_from', id(viewer), point(viewer.position),
           id(target), point(target.position), sight_only, sight_action,
           tuple(sorted(str(c.condition_id) for c in viewer.conditions.values())),
           tuple(sorted(str(c.condition_id) for c in target.conditions.values())))
    return shared_query(engine, key, lambda: (
        observer_blocked(engine, viewer, target, sight_only=sight_only)
        or _through_obscuring_wall(engine, viewer, target, sight_only=sight_only)
        or any(_blocks(engine, zone, viewer, target, sight_only=sight_only) for zone in _heavy(engine))),
        refs=(viewer, target))



def observer_blocked(engine: Any, viewer: ActorState, target: ActorState, *, sight_only: bool = False) -> bool:
    """Pure observer restriction, sharing the perception query's sense filter."""
    from . import ext
    query_options = {"sight_only": True} if sight_only else {}
    return ext.has('zone_view_blocked') and any(answer is True for zone in typed_zones(engine)
        for answer in ext.run_strict('zone_view_blocked', engine, zone, viewer, target, **query_options))


def _through_obscuring_wall(engine: Any, attacker: ActorState, target: ActorState, *, sight_only: bool = False) -> bool:
    """An attack whose line crosses a wall of smoke, darkness or rain the attacker can't see through (Wall of Smoke:
    "ranged attacks that pass through ... have Disadvantage if the attacker relies on sight"; Monsoon Wall hides only
    from its creator's foes)."""
    for zone in typed_zones(engine):
        rule = zone.trigger_profile.get("wall") or {}
        who = rule.get("obscures")
        if (not who or (who == "hostile" and not _hostile(engine, zone, attacker))
                or obscurement_ignored(engine, zone, attacker, target)
                or obscuration_ignored(engine, zone, attacker, target)):
            continue
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        from .space import ray
        height = rule.get("height_ft")
        base = rule.get("base_altitude_ft", zone.center.z * 5)
        crosses = any((x,y) in cells and (height is None or base <= z*5 < base+height)
                      for x,y,z in ray(attacker.position, target.position)[1:-1])
        if crosses and not senses.pierces_wall(engine, zone, attacker, target, sight_only=sight_only):  # Blindsight through smoke (combat/senses.py)
            return True
    return False


def ordinary_visual_wall_between(engine: Any, viewer: ActorState, seen: ActorState) -> bool:
    """Whether an ordinary visual wall crosses the observer's ray.

    This query intentionally ignores magical walls and preserves physical line
    of sight: it reports concealment geometry only. Observer effects that lift
    ordinary visual concealment can use it for both endpoint areas and walls.
    """
    from .space import ray
    for zone in typed_zones(engine):
        profile = zone.trigger_profile or {}
        wall = profile.get('wall') or {}
        visual = profile.get('visual') or {}
        material = str(wall.get('material') or visual.get('material') or '').lower()
        if not wall.get('obscures') or material not in {'smoke', 'fog', 'mist', 'steam', 'sand', 'rain', 'darkness'}:
            continue
        from .ext.darkness_scope import scope
        if scope(engine, zone) != 'ordinary':
            continue
        cells = {(p.x, p.y) for p in zone.affected_cells}
        height = wall.get('height_ft')
        base = wall.get('base_altitude_ft', zone.center.z * 5)
        if any((x, y) in cells and (height is None or base <= z * 5 < base + height)
               for x, y, z in ray(viewer.position, seen.position)[1:-1]):
            return True
    return False


# ------------------------------------------------------------------ what a wall leaves, and getting through one
def on_zone_removed(engine: Any, zone_id: str) -> None:
    """A wall that leaves ground when it ends (Lava Wall: "its space becomes Molten Terrain until the start of your next
    turn or Obsidian Terrain for 1 minute"). Once per wall, whichever path ended it."""
    zone = engine.state.zones.get(zone_id)
    done = engine.__dict__.setdefault("_walls_left", set())
    rule = ((zone.trigger_profile.get("wall") or {}).get("leaves") if zone is not None else None) or None
    if zone is None or not rule or zone_id in done:
        return
    done.add(zone_id)
    terrain = terrain_rules().get("terrains", {}).get(str(rule.get("terrain") or ""))
    if not terrain:
        return
    left_id = f"{zone_id}:left"
    left = ZoneState(
        zone_id=left_id, source_definition_id=zone.source_definition_id, owner_id=zone.owner_id, center=zone.center, radius_cells=0,
        affected_cells=tuple(zone.affected_cells), concentration_link=False, duration_rounds=_duration_rounds(rule.get("duration") or {}),
        created_round=engine.state.round_number,
        trigger_profile={"kind": KIND, "name": str(rule["terrain"]).title(), "terrain": [rule["terrain"]], "difficult": terrain.get("difficult"),
                         "obscured": terrain.get("obscured"), "color": terrain.get("color"), "follows_owner": False, "shape": "wall",
                         "size_ft": zone.trigger_profile.get("size_ft"), "triggers": [], "move_through": copy.deepcopy(terrain.get("move_through")),
                         "visual": {"material": terrain.get("material") or "rubble"}, "numbers": dict(zone.trigger_profile.get("numbers") or {})},
    )
    engine.state.zones[left_id] = left
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": left.model_dump(mode="json")})


_SIZES = ("TINY", "SMALL", "MEDIUM", "LARGE", "HUGE", "GARGANTUAN")


def _movement_history(engine: Any) -> tuple[dict[str, int], dict[str, list[Any]]]:
    """Index zone creation and this turn's movement once per event-list version.

    The index is transient engine cache data: it is never part of fight state or replay output.
    """
    events = engine.events
    cache = getattr(engine, "_zone_movement_history_cache", None)
    last = events[-1] if events else None
    # A rolled-back reply can truncate and refill the list to the same length; the last event object tells them apart.
    key = (id(engine.state), id(events), len(events), id(last), getattr(last, "sequence", None))
    if cache is not None and cache[0] == key:
        return cache[1], cache[2]

    created: dict[str, int] = {}
    for event in events:
        if event.event_type == "ZONE_CREATED":
            zone_id = (event.payload or {}).get("zone", {}).get("zone_id")
            if zone_id:
                created.setdefault(zone_id, event.sequence)

    movements: dict[str, list[Any]] = {}
    for event in reversed(events):
        if event.event_type == "TURN_STARTED":
            break
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id:
            movements.setdefault(event.actor_id, []).append(event)
    engine._zone_movement_history_cache = (key, created, movements)
    return created, movements


def breachable(engine: Any, actor: ActorState, result: str) -> tuple[ZoneState, Position] | None:
    """The nearest section beside ``actor`` of a wall it may try to get through (Dune Wall: a Large or larger creature
    forces through; Puzzle Wall: any creature beside it works the puzzle)."""
    width = int(getattr(engine._footprint(actor.entity_id), "width_cells", 1) or 1)
    size = {1: "MEDIUM", 2: "LARGE", 3: "HUGE"}.get(width, "GARGANTUAN")  # a footprint's squares across
    best = None
    for zone in typed_zones(engine):
        rule = (zone.trigger_profile.get("wall") or {}).get("breach") or {}
        if rule.get("result") != result:
            continue
        if rule.get("min_size") and _SIZES.index(size if size in _SIZES else "MEDIUM") < _SIZES.index(str(rule["min_size"]).upper()):
            continue
        opened = {tuple(row["cell"]) for row in zone.trigger_profile.get("openings") or []}
        for cell in zone.affected_cells:
            if (cell.x, cell.y) in opened:
                continue
            distance = engine.grid.distance_ft(actor.position, cell)
            key = (distance, abs(cell.x - actor.position.x) + abs(cell.y - actor.position.y))  # the section in front before a corner
            if distance <= engine.grid.square_size_ft and (best is None or key < best[0]):
                best = (key, zone, cell)
    return (best[1], best[2]) if best else None


def breach(engine: Any, actor: ActorState, zone: ZoneState, cell: Position) -> None:
    """A successful check: Dune Wall's section collapses; Puzzle Wall opens until the start of the creature's next turn."""
    result = ((zone.trigger_profile.get("wall") or {}).get("breach") or {}).get("result")
    if result == "collapse":
        zone.affected_cells = tuple(other for other in zone.affected_cells if other != cell)
    else:
        zone.trigger_profile = {**zone.trigger_profile, "openings": [*(zone.trigger_profile.get("openings") or []),
                                                                     {"cell": [cell.x, cell.y], "by": actor.entity_id}]}
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
    if not zone.affected_cells:
        remove(engine, zone, "COLLAPSED")
    sync_walls(engine)


def close_openings(engine: Any, actor: ActorState) -> None:
    """Openings a creature made close at the start of its next turn."""
    for zone in typed_zones(engine):
        openings = zone.trigger_profile.get("openings") or []
        kept = [row for row in openings if row.get("by") != actor.entity_id]
        if len(kept) != len(openings):
            zone.trigger_profile = {**zone.trigger_profile, "openings": kept}
            engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})


def _crosses_line(zone: ZoneState, start: Position, end: Position) -> bool:
    """Whether this move took ``start`` and ``end`` to opposite sides of a line-shaped zone (Earthbind
    Line: "The first time on a turn that a hostile creature crosses the line" -- distinct from merely
    entering or leaving the line's own cells, which the "enter" moment above already covers, and true
    even when the mover jumps or teleports clean over the line without ever standing in it). The line's
    own affected cells give its direction (first cell to last); a side is the sign of the cross product of
    that direction against the point, so two points strictly on opposite sides have opposite signs. A
    point ON the line itself (side 0) never counts as "having crossed" -- charge-worker 2026-09-28,
    combat/ext/__init__.py has no hook for this, so it lives beside the zone code it extends."""
    cells = zone.affected_cells
    if len(cells) < 2:
        return False
    ax, ay, bx, by = cells[0].x, cells[0].y, cells[-1].x, cells[-1].y
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return False

    def side(point: Position) -> int:
        value = dx * (point.y - ay) - dy * (point.x - ax)
        return (value > 0) - (value < 0)

    start_side, end_side = side(start), side(end)
    return start_side != 0 and end_side != 0 and start_side != end_side


def _movement_distance_through_zone(engine: Any, mover: ActorState, zone: ZoneState,
                                    extra_path: tuple[Position, Position] | None = None,
                                    fallback_path: tuple[Position, Position] | None = None) -> tuple[int, bool]:
    """Distance traveled in a zone this table turn, read from recorded movement paths; return whether the current path
    intersects the zone. Used by move-through resolution and AI hazard prediction, so split moves share one rule."""
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    if not cells:
        return 0, False
    created, movements = _movement_history(engine)
    zone_created = created.get(zone.zone_id, 0)
    total, current_intersects, found_current_event = 0, False, False
    for event in movements.get(mover.entity_id, ()):
        payload = event.payload or {}
        path = [Position(x=int(point["x"]), y=int(point["y"])) for point in payload.get("path") or []
                if isinstance(point, dict) and "x" in point and "y" in point]
        if fallback_path is None:
            is_current = not found_current_event
            found_current_event = True
        else:
            is_current = bool(path and path[0] == fallback_path[0] and path[-1] == fallback_path[1])
            found_current_event = found_current_event or is_current
        if event.sequence <= zone_created:
            continue
        # Only movement the creature did not choose is left out of the cumulative count. "carried_by"
        # says who carried it, not that it was involuntary: a mount walking where its rider directed it
        # is walking by choice (a mount rider's controlled move, a mount's own move carrying its rider),
        # so its travel through terrain counts exactly as its rider's does. A push, drag or teleport is
        # still excluded by the flags that actually mean "moved against its will".
        if payload.get("forced") or payload.get("teleport"):
            continue
        for start, end in zip(path, path[1:]):
            if (start.x, start.y) in cells or (end.x, end.y) in cells:
                total += int(engine.grid.distance_ft(start, end))
                if is_current:
                    current_intersects = True
    if extra_path is not None:
        start, end = extra_path
        if (start.x, start.y) in cells or (end.x, end.y) in cells:
            total += int(engine.grid.distance_ft(start, end))
            current_intersects = True
    elif fallback_path is not None and not found_current_event:
        # Some established internal callers resolve a hypothetical move directly without first committing a table
        # movement event. Preserve their single-move behavior; table movement always uses its recorded path above.
        start, end = fallback_path
        if (start.x, start.y) in cells or (end.x, end.y) in cells:
            total += int(engine.grid.distance_ft(start, end))
            current_intersects = True
    return total, current_intersects


def _through_effects(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """What a named terrain does to a creature that moves through it: Ash Terrain's "moving more than 10 feet through ...
    makes a Constitution saving throw", or Shattered Glass's damage for moving through at all (no save)."""
    if rule.get("effects") and not rule.get("ability"):
        return copy.deepcopy(rule["effects"])
    return [{"type": "save", "ability": rule.get("ability") or "CON", "on_fail": copy.deepcopy(rule.get("on_fail") or []), "on_success": []}]


def _hurts(effects: Any, numbers: dict[str, Any]) -> bool:
    """Whether what a trigger does deals damage to the creature it works on, on any branch of it (a save's failure, an
    attack's hit). Damage that is the creator's own (``applies_to`` "self") and what waits for a later trigger does not."""
    from . import typed_executor

    cl = int(numbers.get("cl") or 1)
    return any(row.get("type") in ("damage", "extra_damage") and row.get("applies_to") != "self" and not row.get("deferred")
               and cl >= int(row.get("min_cl") or 0) for row in typed_executor._walk_rows(effects))


def geometry_snapshot(engine: Any, actor: ActorState) -> dict[str, bool]:
    """Pure zone membership before changing an anchor or footprint."""
    return {zone.zone_id: _inside(engine, actor, zone) for zone in typed_zones(engine)}


def geometry_changed(engine: Any, actor: ActorState, previous_inside: dict[str, bool]) -> None:
    """Reconcile recorded geometry without inventing a path or movement reactions.

    Capture membership before mutation, record the new geometry, then call this
    in the same transaction. Expansion can enter a zone without moving its anchor.
    Entry, attached zones, wall openings, inside effects and sight remain native.
    This does not spend movement, cross a line, or count willing travel distance.
    """
    for zone in typed_zones(engine):
        if not previous_inside.get(zone.zone_id, False) and _inside(engine, actor, zone):
            _fire(engine, zone, actor, 'enter')
    _sync_geometry(engine, actor)


def on_moved(engine: Any, mover: ActorState, start: Position, end: Position, *, forced: bool = False,
             triggers: bool = True, finalize: bool = True, landed_step: bool = False,
             entry_at: Position | None = None, reappeared: bool = False) -> None:
    """After a move: entering a zone, crossing a line-shaped one, and a named terrain's "moving more than
    10 feet through" save (Ash Terrain). Being pushed or pulled in counts as entering ("Being moved through
    Molten Terrain can trigger the terrain if the movement causes the creature to enter it"); the terrains'
    moving-through rules are for willing movement. landed_step=True records a
    native segment before the final path event; the default reads already
    committed paths for legacy callers. Both share the per-turn distance receipt.
    Snapshot arrival membership before any area displaces the mover. Other
    overlapping entry/leave triggers still apply if the mover remains eligible;
    stale path-crossing work does not. Nested movement owns its new entries.
    entry_at opts into a committed segment endpoint for deferred mounted entry;
    following areas and inside conditions still use the live position.
    Traversal consults zone_recipient_allowed with the original move_through
    rule before spending its trigger or rolling; a veto leaves independent
    enter/start damage and the physical distance receipt intact."""
    from .zone_subjects import allowed

    live_endpoint = mover.position if entry_at is not None else end
    arrivals = [(zone, engine.state.zones.get(zone.zone_id) is zone,
                 False if reappeared else _inside(engine, mover, zone, start), _inside(engine, mover, zone, entry_at if entry_at is not None else end))
                for zone in list(typed_zones(engine))] if triggers else ()
    # Optional entry consumers share every committed route, including teleports.
    # Read-only routes with triggers=False do not create entry opportunities.
    if triggers:
        from . import ext
        for reply in ext.run_strict("zone_arrival", engine, mover, start,
                                    entry_at if entry_at is not None else end, forced):
            if reply is not None:
                raise ValueError("zone_arrival providers must return None")
    for zone, stored, was, now in arrivals:
        if not mover.active or engine.state.terminal_result is not None:
            break
        if stored:
            if engine.state.zones.get(zone.zone_id) is not zone or not zone.active:
                continue
        else:
            # Map terrain and hook areas need not live in state.zones. Hooks
            # may rebuild an equivalent projection each time they are queried.
            zone = next((current for current in typed_zones(engine)
                         if current.zone_id == zone.zone_id and current.active), None)
        if zone is None:
            continue
        inside = _inside(engine, mover, zone)
        if now and not was and (inside or (entry_at is not None and mover.position == live_endpoint)):
            _fire(engine, zone, mover, "enter")
        if was and not now and not inside:
            _fire(engine, zone, mover, "leave")
        if not mover.active or mover.position != live_endpoint:
            continue
        if zone.trigger_profile.get("shape") == "line" and _path_crosses_line(zone, mover, start, end):
            _fire(engine, zone, mover, "cross")
        rule = zone.trigger_profile.get("move_through")
        # "min_ft": "half_speed" -- Shadow Slick's "more than half its Speed"; "who": "any" -- every creature, not only foes.
        least = engine._effective_speed(mover) // 2 if (rule or {}).get("min_ft") == "half_speed" else int((rule or {}).get("min_ft", 10))
        distance, intersects = _movement_distance_through_zone(engine, mover, zone, fallback_path=(start, end))
        if rule and not forced:
            key = f'move_distance:{mover.entity_id}'
            turn_key = key + ':turn'
            marks = _runtime_marks(zone, mover)
            if landed_step:
                # The complete MOVEMENT_COMMITTED path is recorded after its
                # checkpoints. Count each landed segment now, retaining the
                # recorded-path query for old callers and pure AI prediction.
                intersects = was or now
                if marks.get(turn_key) == _turn_key(engine):
                    distance = marks.get(key, 0) + (engine.grid.distance_ft(start, end) if intersects else 0)
            marks[key] = int(distance)
            marks[turn_key] = _turn_key(engine)
        crossed = distance >= least if (rule or {}).get("inclusive") else distance > least
        if rule and not forced and intersects and ((rule.get("who") == "any" and not clear_sighted(engine, zone, mover)) or _hostile(engine, zone, mover)) \
                and crossed and allowed(engine, zone, mover, rule):
            _run(engine, zone, mover, {"id": f"{zone.zone_id}:move_through", "name": "moving through the terrain",
                 # A reviewed roster on the rule scopes this delivery exactly as a
                 # trigger's does, so area-risk previews and execution agree.
                 **({"roster": str(rule["roster"]).strip().lower()} if rule.get("roster") else {}),
                 "effects": _through_effects(rule)},
                 "move_through")
    _sync_geometry(engine, mover, finalize=finalize)


def _sync_geometry(engine: Any, mover: ActorState, *, finalize: bool = True) -> None:
    if any((follows_now(engine, zone) and zone.owner_id == mover.entity_id) or zone.trigger_profile.get("anchor_id") == mover.entity_id
           for zone in typed_zones(engine)):
        follow(engine, mover)
    if any(zone.trigger_profile.get("wall") for zone in typed_zones(engine)):
        sync_walls(engine)  # the square it left in a wall closes
    sync_inside(engine, "move")
    from . import stealth

    if finalize:
        stealth.after_move(engine, mover)


def _path_crosses_line(zone, mover, start, end):
    """Remember the last non-line side so two adjacent steps can cross a line."""
    if len(zone.affected_cells) < 2:
        return False
    a, b = zone.affected_cells[0], zone.affected_cells[-1]
    def side(p):
        n = (b.x-a.x)*(p.y-a.y) - (b.y-a.y)*(p.x-a.x)
        return (n > 0) - (n < 0)
    first, last = side(start), side(end)
    key = f"cross_side:{mover.entity_id}"
    prior = first or zone.per_turn_triggered.get(key, 0)
    if last or first:
        zone.per_turn_triggered[key] = last or first
    return bool(prior and last and prior != last)


def on_step(engine, mover, start, end, *, forced=False, interrupt_harm=True):
    """Resolve one landed step; return whether its zone effects stop this path.

    Called by the movement_step consumer and native typed pushes. No typed zone
    is an exact no-op. Player pauses propagate to the existing transaction.
    Damage includes absorbed Temporary HP; forced paths ignore preexisting Speed0.
    interrupt_harm=False resolves the same effects for a push/pull whose printed
    distance is not shortened by damage, Prone or Speed loss. Death/displacement
    still stops that path; willing and dragged paths retain their interruption.
    """
    if not any(typed_zones(engine)):
        return False
    from .typed_executor import condition_rules
    before = len(engine.events)
    speed = engine._effective_speed(mover)
    rules_before = list(condition_rules(mover))
    prone = any(row.get("ends_on_stand_up") for row in rules_before)
    incapacitated = any(row.get("no_actions") for row in rules_before)
    on_moved(engine, mover, start, end, forced=forced, finalize=False, landed_step=True)
    damaged = any(ev.event_type == "DAMAGE_COMMITTED" and mover.entity_id in ev.target_ids
                  and int(ev.payload.get("reduced_to", 0)) > 0 for ev in engine.events[before:])
    return (not mover.active or mover.position != end
            or (interrupt_harm and (damaged or (speed > 0 and engine._effective_speed(mover) <= 0)
            or (not incapacitated and any(row.get("no_actions") for row in condition_rules(mover)))
            or (not prone and any(row.get("ends_on_stand_up") for row in condition_rules(mover))))))


def hazard_test(engine: Any, creature: ActorState, *,
                movement_mode: Literal["walking", "teleport", "forced"] = "walking",
                immediate_only: bool = False,
                zone_states: Iterable[ZoneState] | None = None) -> Callable[[Position], bool] | None:
    """For an AI choosing a movement endpoint, test whether it exposes ``creature`` to zone damage: entry or start effects,
    crossing a line, or cumulative distance through damaging terrain this table turn. Named-terrain distance uses prior
    committed movement paths plus the proposed step. Teleport and forced modes retain endpoint and line risks but skip
    move_through, matching on_moved(forced=True) and recorded movement distance. Walking is the unchanged default.
    None when no map zone would hurt the creature. immediate_only excludes
    start-only damage for destination rules that forbid immediate harm; absent
    it retains the historical AI entry/start risk query. zone_states optionally
    supplies a caller's perceived geometry/effects projection; None retains
    native zones. This pure seam shares footprint, crossing and distance
    semantics with personal AI previews without widening their knowledge."""
    ends: list[tuple[frozenset[tuple[int, int]], bool]] = []  # squares that hurt on ending a step in them; and whether it stands in them
    lines: list[ZoneState] = []
    terrains: list[tuple[ZoneState, frozenset[tuple[int, int]], bool, int]] = []  # zone, squares, standing, feet threshold
    for zone in typed_zones(engine) if zone_states is None else zone_states:
        if not zone.affected_cells or clear_sighted(engine, zone, creature):
            continue
        profile = zone.trigger_profile
        numbers = profile.get("numbers") or {}
        squares = frozenset((cell.x, cell.y) for cell in zone.affected_cells)
        moments = {moment for trigger in profile.get("triggers") or []
                   if _applies(engine, zone, creature, trigger) and _hurts(trigger.get("effects"), numbers) for moment in trigger.get("on") or []}
        if moments & ({"enter"} if immediate_only else {"enter", "start"}):
            ends.append((squares, engine._footprint_intersects(creature, zone.affected_cells)))
        if "cross" in moments and profile.get("shape") == "line":
            lines.append(zone)
        rule = profile.get("move_through")
        if movement_mode == "walking" and rule and (rule.get("who") == "any" or _hostile(engine, zone, creature)) and _hurts(_through_effects(rule), numbers):
            least = engine._effective_speed(creature) // 2 if rule.get("min_ft") == "half_speed" else int(rule.get("min_ft", 10))
            terrains.append((zone, squares, engine._footprint_intersects(creature, zone.affected_cells), least))
    if not (ends or lines or terrains):
        return None
    here = creature.position
    # One query may test hundreds of destinations and shared path prefixes.
    # Union equivalent non-standing enter/start hazards once; membership in
    # any original zone is exactly membership in this union.
    dangerous_cells = frozenset(cell for squares, standing in ends if not standing for cell in squares)

    def hurts_there(destination: Position) -> bool:
        cells = set(engine._actor_cells(creature, destination))
        if cells & dangerous_cells or any(_crosses_line(zone, here, destination) for zone in lines):
            return True
        for zone, squares, standing, least in terrains:
            through, intersects = _movement_distance_through_zone(engine, creature, zone, (here, destination))
            if through > least and (standing or cells & squares or intersects):
                return True
        return False

    return hurts_there


def moves_with_owner(zone: ZoneState) -> bool:
    """An aura that moves with its creator, or an area anchored to a creature (see follow)."""
    return bool(zone.trigger_profile.get("follows_owner") or zone.trigger_profile.get("anchor_id"))


def follows_now(engine: Any, zone: ZoneState) -> bool:
    """Whether this area rides its owner right now (see follow).

    General seam (owner 2026-10-13, Body as Center: "The area moves with
    you only until the start of your next turn"): the recorded
    ``follows_owner`` decides, and the ``zone_follows`` hook (combat/ext)
    may end the ride early -- a plug-in answers False once its recorded
    turn has passed, so the area then stays where it is for the rest of
    its duration. Default inert: with no subscriber every recorded
    follower rides exactly as before.
    """
    if not zone.trigger_profile.get("follows_owner"):
        return False
    from . import ext

    for answer in ext.run_strict("zone_follows", engine, zone):
        if type(answer) is not bool:
            raise ValueError("zone_follows must return None or a boolean")
        if answer is False:
            return False
    return True


def area_cells(engine: Any, zone: ZoneState) -> tuple[Position, ...]:
    """The squares an area that moves (moves_with_owner) covers around its current center, before any suppression.

    Stationary placed areas (including Earthbind Line) use stored ``affected_cells`` during
    play. The placed reconstruction below uses the owner's current position, not cast-time
    facing, and omits width: moving/anchored placed lines and cones are unsupported until
    facing, width and a complete footprint are persisted and tested. If the owner is absent
    or on the center, return the stored cells without inventing a direction. That fallback
    also preserves any suppression; it cannot reconstruct cells already removed by it.
    Unplaced areas retain their existing center-based reconstruction.
    """
    owner = getattr(engine.state, "actors", {}).get(zone.owner_id)
    placed = bool(zone.trigger_profile.get("placed"))
    if placed and (owner is None or (owner.position.x, owner.position.y) == (zone.center.x, zone.center.y)):
        return tuple(zone.affected_cells)  # nothing left to give it a direction; the stored squares stand
    return _cells(engine, zone.center, {"size_ft": zone.trigger_profile.get("size_ft"), "shape": zone.trigger_profile.get("shape"),
                                        "spreads": zone.trigger_profile.get("spreads"),
                                        **({'include_origin': 1} if zone.trigger_profile.get('include_origin') else {}),
                                        **({"blocks": int(zone.trigger_profile["blocks"]),
                                            "blocks_along": zone.trigger_profile.get("blocks_along")}
                                           if int(zone.trigger_profile.get("blocks") or 1) > 1 else {}),
                                        **({"placed": True} if placed else {})},
                  owner.position if placed and owner is not None else None)


def _unsuppressed(zone: ZoneState, cells: tuple[Position, ...]) -> tuple[Position, ...]:
    """General seam (rider lane C14, combat/ext/area_suppression.py): squares a suppression holds stay out of a re-centered
    area. ``trigger_profile["suppressed"]`` lists records; one with ``all`` empties the area, others name their squares.
    No record (every area but a suppressed one) leaves ``cells`` exactly as computed."""
    rows = zone.trigger_profile.get("suppressed") or []
    if not rows:
        return cells
    if any(int(row.get("all") or 0) for row in rows):
        return ()
    held = {tuple(cell) for row in rows for cell in row.get("cells") or []}
    return tuple(cell for cell in cells if (cell.x, cell.y) not in held)


def follow(engine: Any, owner: ActorState) -> None:
    """An aura that moves with its creator ("It moves with you") is re-centered after the creator moves; so is an area
    anchored to a creature (Clinging Darkness: "The Darkness is anchored to the creature or object and moves with it")."""
    for zone in typed_zones(engine):
        rides = (zone.owner_id == owner.entity_id and follows_now(engine, zone)) or zone.trigger_profile.get("anchor_id") == owner.entity_id
        if not rides or zone.center == owner.position:
            continue
        zone.center = owner.position
        zone.affected_cells = _unsuppressed(zone, area_cells(engine, zone))
        # The same zone id, re-centred in place: a quiet record (history_hidden) that the reducer replays via zone_after,
        # so a move adds no ZONE_CREATED line (only the creation logs once).
        engine._append_event("PASSIVE_TRIGGERED", zone.source_definition_id, actor_id=owner.entity_id,
                             payload={"zone_id": zone.zone_id, "zone_after": zone.model_dump(mode="json"), "history_hidden": 1})
    sync_inside(engine, "move")


def obscuration_ignored(engine: Any, zone: ZoneState, viewer: ActorState, seen: ActorState) -> bool:
    """Pure opt-in removal of one area's visual concealment for one observer."""
    from . import ext
    replies = ext.run_strict('zone_obscuration_ignored', engine, zone, viewer, seen)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('zone_obscuration_ignored must return None or a boolean')
    return any(reply is True for reply in replies)
