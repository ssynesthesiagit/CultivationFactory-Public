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

# Bonus Action: each candle can move up to 20 feet.
MOVE_SQUARES = 4


def _owned(engine, actor):
    from .. import zones
    return [z for z in zones.typed_zones(engine)
            if z.active and z.owner_id == actor.entity_id and (z.trigger_profile or {}).get("candle_origins")]


def _destinations(engine, zone, index):
    """Destinations for one candle, including other candles' squares and unlit squares."""
    from ..gate2_runtime_models import Position
    from .needle import cell_id
    from .placed import free_square

    origin = zone.trigger_profile["candle_origins"][index]
    out = {}
    for dy in range(-MOVE_SQUARES, MOVE_SQUARES + 1):
        for dx in range(-MOVE_SQUARES, MOVE_SQUARES + 1):
            x, y = origin[0] + dx, origin[1] + dy
            if not (0 <= x < engine.grid.width and 0 <= y < engine.grid.height):
                continue
            square = Position(x=x, y=y)
            if (dx == 0 and dy == 0) or not free_square(engine, square):
                continue
            if any(engine._footprint_intersects(other, (square,))
                   for other in engine.state.actors.values() if other.active):
                continue
            out[cell_id(square)] = square
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
    return any(_destinations(engine, zone, i) for zone in _owned(engine, actor)
               for i in range(len(zone.trigger_profile["candle_origins"])))


@effect("candle_procession_move")
def move_candles(ctx, eff):
    from .needle import ask, checkpoint_id
    from .placed import reshape
    engine, actor = ctx.engine, ctx.actor
    owned = _owned(engine, actor)
    if not owned:
        ctx.rider("Move Candles: no candles of yours are lit.")
        return
    for zone in owned:
        original = [tuple(p) for p in zone.trigger_profile["candle_origins"]]
        origins = list(original)
        for i, origin in enumerate(original):
            options = _destinations(engine, zone, i)
            if not options:
                continue
            picked = ask(engine, ctx.intent, checkpoint_id(engine, "candle_procession_move", zone.zone_id, i), actor,
                         "choice:needle.candle_procession_move", list(options),
                         labels={key: f"Move the candle at ({origin[0]}, {origin[1]}) to ({p.x}, {p.y})"
                                 for key, p in options.items()},
                         minimum=0, maximum=1, allow_decline=True, default="decline",
                         name="Move Candles", feature_id=FEATURE,
                         prompt=f"Candle Procession: move the candle at ({origin[0]}, {origin[1]}) up to 20 feet, or leave it there.")
            if picked and picked[0] in options:
                p = options[picked[0]]
                origins[i] = (p.x, p.y)
        if origins == original:
            continue
        # Suppression records refer to squares. Move their saved squares along with
        # the candle, so expiry restores the new origin instead of a ghost.
        def moved(cells):
            result = []
            for cell in cells:
                matches = [origins[i] for i, origin in enumerate(original) if origin == tuple(cell)]
                result.extend([list(p) for p in (matches or [tuple(cell)])])
            return result
        records = [{**row, "cells": moved(row.get("cells", [])),
                    "order": moved(row.get("order", []))}
                   for row in zone.trigger_profile.get("suppressed", [])]
        cells = moved((c.x, c.y) for c in zone.affected_cells)
        profile = {"candle_origins": [list(p) for p in origins]}
        if records:
            profile["suppressed"] = records
        reshape(engine, zone, cells=cells, center=zone.center, profile=profile)
