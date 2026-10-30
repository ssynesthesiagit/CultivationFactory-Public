"""Candle Procession's individually selected light origins.

The existing concentration-linked zone holds the selected candle squares, not
its generic area footprint. Its ordinary zone clock and event preserve them.
"""
from . import hook

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
    result = []
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        origins = profile.get("candle_origins")
        if origins is None:
            continue
        # Area suppression removes squares from affected_cells. A candle emits
        # only while its own placed square remains part of the active zone.
        available = {(cell.x, cell.y) for cell in zone.affected_cells}
        origins = frozenset(tuple(cell) for cell in origins if tuple(cell) in available)
        if origins:
            result.append(lighting.LightSource(f"candle-procession:{zone.zone_id}", "Candle Procession", origins,
                                               bright_ft=bright, dim_ft=dim))
    return result
