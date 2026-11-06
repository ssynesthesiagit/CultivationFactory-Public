"""Sand-Born Footwork's owned terrain exemption, hiding and missed-OA square.

Uses Sand Terrain's public identity query, explicit represented environment
terrain, and the existing outcome/choice/zone contracts. No movement or native
attack behavior is replaced. The printed square has no stated expiry.
"""
from . import hook, note
from .needle import ask, checkpoint_id, option_spec, cell_id, position_of
from .passive_rows import row_of
from .sand_terrain import is_sand

FEATURE = "insight.sand-born-footwork"
BLOCK = "sand_born_footwork"
CHOICE = "choice:insights7.sand_born_footwork"
USED = "_round_sand_born_scene_used"
ENVIRONMENTS = {"dusty", "sandy", "desert", "ruin", "dry-earth", "dry earth"}


def owns(engine, actor):
    return row_of(engine, actor.entity_id, BLOCK, BLOCK) is not None


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "kind": BLOCK, "player_outcome":
                 "Ignore your own Sand Terrain's difficult footing; hide with Advantage in dusty, sandy, desert, ruin or dry-earth terrain; once per scene create adjacent Shallow Sand after an Opportunity Attack misses you."}]
    return None


@hook("choice_options")
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook("choice_reactors")
def choosers(engine):
    return tuple(a.entity_id for a in engine.state.actors.values() if owns(engine, a))


@hook("difficult_zone_exempt")
def own_sand(engine, actor, zone):
    if owns(engine, actor) and zone.owner_id == actor.entity_id and is_sand(engine, zone):
        return True
    return None


@hook("ability_check_hazards")
def hiding(engine, actor, ability, skill, hazards):
    if not owns(engine, actor) or ability != "DEX" or str(skill).casefold() != "stealth":
        return None
    if "visual_concealment" not in hazards and "hide" not in hazards:
        return None
    from .. import zones
    for zone in zones.typed_zones(engine):
        if not engine._footprint_intersects(actor, zone.affected_cells):
            continue
        terrain = {str(t).casefold() for t in zone.trigger_profile.get("terrain") or []}
        material = str((zone.trigger_profile.get("visual") or {}).get("material") or "").casefold()
        if is_sand(engine, zone) or terrain & ENVIRONMENTS or material in ENVIRONMENTS:
            return "ADVANTAGE"
    return None


@hook("after_miss_choice")
def missed_opportunity(ctx, target, spec):
    from ..gate2_runtime_models import Position
    from ..typed_executor import Context
    from .. import zones
    if (not target or not target.active or target.current_hp <= 0 or not owns(ctx.engine, target)
            or target.turn_flags.get(USED)):
        return
    notice = getattr(ctx, "attack_notice", None)
    if not (ctx.typed.get("opportunity_of") or ctx.source == "system:combat.opportunity_attack"
            or (notice and notice.opportunity)):
        return
    # All adjacent map spaces, including occupied ones: the rule creates terrain,
    # not a creature. No movement-route cap removes a printed square option.
    footprint = set(ctx.engine._actor_cells(target))
    perimeter = {(x + dx, y + dy) for x, y in footprint
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy} - footprint
    cells = [Position(x=x, y=y, z=target.position.z)
             for x, y in sorted(perimeter, key=lambda p: (p[1], p[0]))
             if ctx.engine.grid.in_bounds((x, y)) and (x, y) not in ctx.engine.grid.blocked]
    if not cells:
        return
    ids = [cell_id(c) for c in cells]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SAND_BORN_FOOTWORK", target.entity_id),
        target, CHOICE, ids, labels={cell_id(c): f"Create Shallow Sand in square ({c.x}, {c.y})" for c in cells},
        preferred=ids[:1], allow_decline=True,
        prompt=f"Sand-Born Footwork: {ctx.actor.display_name}'s Opportunity Attack misses {target.display_name}. "
               "Create one adjacent square of Shallow Sand Terrain? Once per scene; no action or resource cost.")
    if not chosen:
        return
    point = position_of(chosen[0])
    sub = Context(ctx.engine, target, ctx.action, ctx.intent,
                  {"source": FEATURE, "numbers": {}}, [], None, {}, effect_source=FEATURE)
    zones.create(sub, {"name": "Shallow Sand Terrain", "cells": [point], "size_ft": 5,
        "terrain": ["shallow sand terrain"], "visual": {"material": "sand"},
        "duration": {"kind": "until_removed"}, "difficult": "all"})
    target.turn_flags[USED] = 1
    note(ctx.engine, FEATURE, target, "Sand-Born Footwork: created one adjacent Shallow Sand Terrain square; "
         "the once-per-scene benefit is spent.")
