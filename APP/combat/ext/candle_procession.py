"""Candle Procession's individually selected light origins.

The existing concentration-linked zone holds the selected candle squares, not
its generic area footprint. Its ordinary zone clock and event preserve them.
"""
from . import effect, hook

FEATURE = "TAL_WAX_CANDLE_PROCESSION"


@hook("zone_creation_profile")
def select_candles(zone, ctx):
    if ctx.typed.get("source") != FEATURE:
        return None

    from .. import senses, target_knowledge
    from ..gate2_runtime_models import Position
    from ..read_queries import read_frame
    from .needle import ask, cell_id, checkpoint_id
    from .placed import free_square

    engine, actor = ctx.engine, ctx.actor
    with read_frame(engine):
        known = [other for other in engine.state.actors.values()
                 if other.active and target_knowledge.located(engine, actor, other)]
        cells = [Position(x=x, y=y) for y in range(engine.grid.height) for x in range(engine.grid.width)]
        cells = [p for p in cells if (p.x, p.y) not in engine.grid.blocked
                 and not any(engine._footprint_intersects(other, (p,)) for other in known)
                 and engine._distance_actor_to_cell(actor, p) <= 60
                 and senses.perceives_cell(engine, actor, p)]
    options = {cell_id(p): p for p in cells}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "candle_procession", zone.zone_id), actor,
                 "choice:needle.candle_procession", list(options),
                 labels={key: f"Place a Candle Procession candle at ({p.x}, {p.y})"
                         for key, p in options.items()},
                 minimum=1, maximum=6, allow_decline=True, name="Candle Procession", feature_id=FEATURE,
                 prompt=f"Candle Procession: {actor.display_name} creates up to six candles in visible empty spaces within 60 feet. Choose their spaces; each sheds dim light for 10 feet.")
    selected = tuple(options[key] for key in picked if key in options and free_square(engine, options[key]))
    profile = dict(zone.trigger_profile)
    visual = dict(profile.get("visual") or {})
    visual.pop("light", None)
    profile["visual"] = visual
    profile["candle_origins"] = [[p.x, p.y] for p in selected]
    return zone.model_copy(update={"trigger_profile": profile, "affected_cells": selected,
                                   "center": selected[0] if selected else zone.center})


@hook("light_sources")
def candle_lights(engine):
    from .. import light_sources, lighting, zones
    bright, dim = lighting.radii(light_sources.light(FEATURE))
    return [lighting.LightSource(f"candle-procession:{zone.zone_id}", "Candle Procession",
                                 frozenset(tuple(p) for p in zone.trigger_profile.get("candle_origins", [])
                                           if any((cell.x, cell.y) == tuple(p) for cell in zone.affected_cells)),
                                 bright_ft=bright, dim_ft=dim)
            for zone in zones.typed_zones(engine)
            if "candle_origins" in (zone.trigger_profile or {})
            and zone.trigger_profile["candle_origins"]]

# Bonus Action: move each lit candle up to 20 ft (4 squares, Chebyshev, the metric of distance_cells).
MOVE_SQUARES = 4
REACH_FT = 60
FOOTING_FT = 5
FOOTING_FLAG = "candle_footing:"  # + zone id: the round an ally began its turn within 5 ft of a candle


def _owned(engine, actor):
    from .. import zones
    return [z for z in zones.typed_zones(engine)
            if z.active and z.owner_id == actor.entity_id and (z.trigger_profile or {}).get("candle_origins")]


def _lit(zone):
    """Saved origins whose squares are currently in the effective cells (a suppressed candle is dark and cannot move)."""
    live = {(c.x, c.y) for c in zone.affected_cells}
    return [tuple(p) for p in zone.trigger_profile["candle_origins"] if tuple(p) in live]


def _destinations(engine, actor, zone):
    """Legal (origin, square) moves: free, unoccupied, not a saved origin, within 20 ft of the candle, within 60 ft of the caster, perceived."""
    from .. import senses
    from ..gate2_runtime_models import Position
    from .needle import cell_id
    from .placed import free_square
    held = {tuple(p) for p in zone.trigger_profile["candle_origins"]}
    out = {}
    for origin in _lit(zone):
        for dy in range(-MOVE_SQUARES, MOVE_SQUARES + 1):
            for dx in range(-MOVE_SQUARES, MOVE_SQUARES + 1):
                x, y = origin[0] + dx, origin[1] + dy
                if not (0 <= x < engine.grid.width and 0 <= y < engine.grid.height):
                    continue  # Position is non-negative and the map has edges
                square = Position(x=x, y=y)
                if (square.x, square.y) in held or not free_square(engine, square):
                    continue
                if any(engine._footprint_intersects(other, (square,)) for other in engine.state.actors.values() if other.active):
                    continue
                if engine._distance_actor_to_cell(actor, square) > REACH_FT or not senses.perceives_cell(engine, actor, square):
                    continue
                out[f"candle:{origin[0]},{origin[1]}>{cell_id(square)}"] = (origin, square)
    return out


@hook("compile_actions")
def compile_move(info):
    """The owner's Bonus Action (inert for everyone who does not own the talent)."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    if FEATURE not in (info.get("owned_ids") or ()):
        return None
    short, actor_id = info["short"], info["actor_id"]
    return [ActionDefinition(
        source_definition_id=f"action:typed.{short}.candle_procession_move", display_name="Move Candles",
        owner_id=actor_id, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"expected_damage": 0, "candle_procession_move": 1,
                    "typed": {"effects": [{"type": "candle_procession_move"}], "numbers": {},
                              "duration": {"kind": "instant"}, "riders": [], "source": FEATURE}})]


@hook("candidate_allowed")
def move_allowed(engine, actor, candidate, action):
    if not (getattr(action, "parameters", None) or {}).get("candle_procession_move"):
        return None
    return any(_destinations(engine, actor, zone) for zone in _owned(engine, actor))


@effect("candle_procession_move")
def move_candles(ctx, eff):
    from .needle import ask, checkpoint_id
    from .placed import reshape
    engine, actor = ctx.engine, ctx.actor
    owned = _owned(engine, actor)
    if not owned:
        ctx.rider("Move Candles: no candles of yours are lit.")
        return
    zone = owned[0]
    options = _destinations(engine, actor, zone)
    if not options:
        ctx.rider("Move Candles: no candle can move to a legal space.")
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "candle_procession_move", zone.zone_id), actor,
                 "choice:needle.candle_procession_move", list(options),
                 labels={key: f"Move the candle at ({origin[0]}, {origin[1]}) to ({square.x}, {square.y})"
                         for key, (origin, square) in options.items()},
                 minimum=0, maximum=6, allow_decline=True, default="decline", name="Move Candles", feature_id=FEATURE,
                 prompt="Candle Procession: move each candle up to 20 feet. A candle cannot occupy a creature's space.")
    moves, taken = {}, set()
    for key in picked:
        if key not in options:
            continue
        origin, square = options[key]
        if origin in moves or (square.x, square.y) in taken:
            continue
        moves[origin] = square
        taken.add((square.x, square.y))
    if not moves:
        return
    origins = [[moves[o].x, moves[o].y] if o in moves else [o[0], o[1]]
               for o in (tuple(p) for p in zone.trigger_profile["candle_origins"])]
    cells = tuple(moves[(c.x, c.y)] if (c.x, c.y) in moves else c for c in zone.affected_cells)
    reshape(engine, zone, cells=cells, profile={"candle_origins": origins})


@hook("turn_start")
def footing_at_turn_start(engine, actor):
    """An ally who begins its turn within 5 ft of one of your candles earns that turn's footing."""
    from .. import zones
    if not actor.active:
        return None
    for zone in zones.typed_zones(engine):
        if not (zone.active and (zone.trigger_profile or {}).get("candle_origins")):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or owner is actor or owner.team_id != actor.team_id:
            continue
        if any(engine._distance_actor_to_cell(actor, c) <= FOOTING_FT for c in zone.affected_cells):
            actor.turn_flags[FOOTING_FLAG + zone.zone_id] = engine.state.round_number
    return None


@hook("difficult_exempt")
def ally_footing(engine, actor):
    """Allies who began their turn near a candle ignore Difficult Terrain within 5 ft of it (nonmagical only, shared helper)."""
    from .. import zones
    from .guiding_candle import footing_cells
    from . import placed
    if not actor.active:
        return None
    covered = set()
    for zone in zones.typed_zones(engine):
        if not (zone.active and (zone.trigger_profile or {}).get("candle_origins")):
            continue
        if actor.turn_flags.get(FOOTING_FLAG + zone.zone_id) != engine.state.round_number:
            continue
        for cell in zone.affected_cells:
            covered.update((c.x, c.y) for c in placed.area(engine, cell, "sphere", FOOTING_FT))
    return footing_cells(engine, actor, covered)

