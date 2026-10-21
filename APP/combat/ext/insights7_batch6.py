"""Owned Insights 7 creation, sound-check and pursuit refinements.

No source facts are inferred from artwork or enemy statistics. Creation choices
use the newly constructed zone; check hazards are the check's declared causes.
Red Sash repairs the omitted printed pursuit movement only for its owners.
"""
from . import hook, note
from .passive_rows import row_of
from .needle import ask, checkpoint_id, option_spec, cell_id

BLOCK = "insights7_batch6"
ROAD = "insight.road-and-wall-adept"
SILENT = "insight.silent-foundation"
SASH = "insight.red-sash-pursuer"
PURSUIT = "tianxia.talent.sabers.red_trail_pursuit"
CHOICE = "choice:insights7.batch6."


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor else None


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, "kind": row["feature_id"], "numbers": dict(numbers),
             "choice_owner": 1, "player_outcome": spec["outcome"]}]


@hook("choice_options")
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook("choice_reactors")
def reactors(engine):
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if any(owned(engine, a, f) for f in (ROAD, SILENT, SASH)))


@hook("zone_creation_profile")
def earth_creation(zone, ctx):
    row = owned(ctx.engine, ctx.actor, ROAD)
    if (not row or ctx.typed.get("sphere") != "tianxia.sphere.earth"
            or ctx.actor.turn_flags.get("_round_ins7d_road_used")):
        return None
    profile = zone.trigger_profile
    # Read the represented creation, not a creature's concealed narrative.
    # Non-wall Earth terrain creators name their road/ramp/etc. in the zone.
    category = str(profile.get("creation_kind") or profile.get("shape") or "").lower()
    if category not in {"wall", "road", "ramp", "shelter", "ridge", "seal"}:
        import re
        match = re.search(r"\b(wall|road|ramp|shelter|ridge|seal)\b", str(profile.get("name") or ""), re.I)
        category = match.group(1).lower() if match else ""
    if not profile.get("wall") and category not in {"wall", "road", "ramp", "shelter", "ridge", "seal"}:
        return None
    from ..gate2_runtime_models import Position
    from .docket_walls import stats
    base = stats(zone)
    occupied = set(zone.affected_cells)
    cells = {Position(x=p.x + dx, y=p.y + dy, z=p.z)
             for p in occupied for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy
             if ctx.engine.grid.in_bounds((p.x + dx, p.y + dy))
             and (p.x + dx, p.y + dy) not in ctx.engine.grid.blocked}
    cells -= occupied
    # Additional geometry obeys the same source's range and cannot be placed
    # through a represented physical barrier. Keep every legal section.
    reach = ctx.action.range_ft
    cells = sorted((p for p in cells if (reach is None or ctx.engine.grid.distance_ft(ctx.actor.position, p) <= reach)
                    and ctx.engine.grid.line_of_physical_transmission(zone.center, p)), key=lambda p: (p.y, p.x, p.z))
    labels = {}
    if base:
        labels["hp"] = f"Increase the creation's Hit Points by {int(row['numbers']['cl'])}"
    durations = {10: 100, 100: 600, 600: 14400}
    if zone.duration_rounds in durations:
        labels["duration"] = {10: "Last 10 minutes instead of 1 minute", 100: "Last 1 hour instead of 10 minutes",
                              600: "Last 24 hours instead of 1 hour"}[zone.duration_rounds]
    if cells:
        labels["section"] = "Create one additional 5-foot section or space"
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "INS7D_ROAD", zone.zone_id), ctx.actor,
        CHOICE + "road", list(labels), labels=labels, preferred=list(labels)[:1], allow_decline=True,
        prompt=f"Road-and-Wall Adept: {ctx.actor.display_name} creates {profile.get('name') or ctx.action.display_name} "
               f"with {ctx.action.display_name}. Choose one improvement for this creation, once per scene; no extra action or CP.")
    if not picked:
        return None
    choice = picked[0]
    if choice == "section":
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "INS7D_ROAD_SECTION", zone.zone_id), ctx.actor,
            CHOICE + "road_section", [cell_id(p) for p in cells],
            labels={cell_id(p): f"Add a 5-foot section at ({p.x}, {p.y})" for p in cells},
            preferred=[cell_id(cells[0])], allow_decline=True,
            prompt=f"Road-and-Wall Adept: choose one adjacent legal space for {ctx.action.display_name}'s extra section. No extra cost.")
        if not selected:
            return None
        zone = zone.model_copy(update={"affected_cells": tuple(zone.affected_cells) +
                                      (next(p for p in cells if cell_id(p) == selected[0]),)})
    elif choice == "duration":
        zone = zone.model_copy(update={"duration_rounds": durations[zone.duration_rounds]})
    else:
        wall = profile["wall"]
        zone.trigger_profile = {**profile, "wall": {**wall, "object": {**wall["object"],
            "hp": str(base["hp"] + int(row["numbers"]["cl"]))}}}
    ctx.actor.turn_flags["_round_ins7d_road_used"] = 1
    note(ctx.engine, ROAD, ctx.actor, f"Road-and-Wall Adept: {labels[choice]} for {ctx.action.display_name}.", choice=choice)
    return zone


def silent_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        row = owned(engine, actor, SILENT)
        if row:
            yield Holder(actor, SILENT, row, SILENT, row["numbers"])


def sound_failure(engine, holder, rc):
    context = engine.d20_context(rc.roll) or {}
    return (rc.ability == "DEX" and str(context.get("skill") or "").lower() == "stealth"
            and bool(set(context.get("hazards") or ()) & {"sound", "hearing", "noise"}))


def silence_bonus(engine, holder, rc):
    from .. import zones
    from ..spatial_areas import zone_contains
    for zone in zones.typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        source = (action.parameters.get("typed") or {}).get("source") if action else None
        if (zone.owner_id == holder.actor.entity_id and source in {"TAL_SOUND_DAMPEN_SOUND", "TAL_SOUND_TRUE_SILENCE"}
                and zone_contains(engine, holder.actor, zone)):
            return int(holder.numbers["pb"])
    return 0


from .d20_rewrite import Rule, register
register(Rule("ins7d_silent_foundation", "Silent Foundation", rolls=("check",), when="failed",
    limit="fight", checkpoint="D20_REROLL_CHECK", finder=silent_holders, guard=sound_failure,
    bonus=silence_bonus, ai=lambda engine, holder, rc: True))


@hook("compile_bundle")
def pursuit_movement(bundle, info):
    if not any(r.get("block") == BLOCK and r.get("kind") == SASH for r in bundle.get("typed_passives") or []):
        return None
    for row in bundle.get("typed_reactions") or []:
        if row.get("feature_id") != PURSUIT:
            continue
        # A future reviewed base movement must not produce a second move.
        effects = row.get("effects") or []
        row.update(kind="moved", requires_mark=None, ins7d_pursuit=1)
        row["effects"] = [{"type": "movement", "distance_ft": "half_speed", "applies_to": "self",
                           "ins7d_pursuit_step": 1}] + [e for e in effects
            if e.get("type") not in {"movement", "reaction_move", "ins7d_pursuit_step"}]
    return bundle


@hook("after_hit")
def record_saber_hit(ctx, target, kind):
    if not owned(ctx.engine, ctx.actor, SASH) or kind != "weapon":
        return
    from .weapon_hits import weapon_has_family
    if ctx.typed.get("sphere") == "tianxia.sphere.sabers" or weapon_has_family(ctx, "saber"):
        ctx.actor.turn_flags["_round_ins7d_saber_hit:" + target.entity_id] = int(ctx.engine.state.round_number)
        note(ctx.engine, SASH, ctx.actor, f"Red Trail Pursuit: {ctx.actor.display_name} has hit {target.display_name} "
             "with a saber this round.", targets=(target,), hit_round=int(ctx.engine.state.round_number))


@hook("reaction_subject_allowed")
def pursuit_trigger(engine, reactor, other, row):
    if not row.get("ins7d_pursuit") or not owned(engine, reactor, SASH):
        return None
    if not other or reactor.turn_flags.get("_round_ins7d_saber_hit:" + other.entity_id) != engine.state.round_number:
        return False
    event = next((e for e in reversed(engine.events) if e.event_type == "MOVEMENT_COMMITTED"), None)
    if not event or event.actor_id != other.entity_id or event.payload.get("forced"):
        return False
    from ..gate2_runtime_models import Position
    path = event.payload.get("path") or []
    return bool(len(path) > 1 and engine.grid.distance_ft(reactor.position, Position(**path[-1]))
                > engine.grid.distance_ft(reactor.position, Position(**path[0])))


@hook("subject_reposition")
def pursuit_movement_subject(ctx, spec):
    if not spec.get("ins7d_pursuit_step") or not owned(ctx.engine, ctx.actor, SASH):
        return None
    pursuit_step(ctx, spec)
    return True


def pursuit_step(ctx, spec):
    if ctx.source != PURSUIT or not owned(ctx.engine, ctx.actor, SASH) or ctx.target is None:
        return
    from .granted_movement import choices, move
    from .needle import ai_controlled
    from ..target_knowledge import located
    from ..typed_executor import bears_mark
    if ai_controlled(ctx.engine, ctx.actor) and not located(ctx.engine, ctx.actor, ctx.target):
        return
    feet = ctx.engine._effective_speed(ctx.actor) // 2 + 5
    gap = ctx.engine._distance_actor_to_actor(ctx.actor, ctx.target)
    paths = [p for p in choices(ctx.engine, ctx.actor, feet)
             if ctx.engine.grid.distance_ft(p.destination, ctx.target.position) < gap]
    if not paths:
        return
    paths.sort(key=lambda p: (ctx.engine.grid.distance_ft(p.destination, ctx.target.position), p.movement_cost_ft,
                             p.destination.y, p.destination.x))
    # Native candidate identity includes the route and movement mode. An
    # endpoint can legally be reached by several mechanically distinct paths.
    by_id = {p.candidate_id: p for p in paths}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "INS7D_SASH", ctx.target.entity_id), ctx.actor,
        CHOICE + "sash", list(by_id), labels={k: f"{p.metadata.get('movement_mode', 'walk').replace('_', ' ').capitalize()} toward {ctx.target.display_name} to ({p.destination.x}, {p.destination.y}), height {p.destination.z * 5} feet"
                                             for k, p in by_id.items()}, preferred=list(by_id)[:1], allow_decline=True,
        prompt=f"Red Sash Pursuer: Red Trail Pursuit against {ctx.target.display_name} lets {ctx.actor.display_name} move "
               f"up to {feet} feet (half Speed plus 5). Choose a legal destination toward that creature; this uses the "
               "triggering Reaction and costs no Qi. Only that creature's Opportunity Attack is prevented if it bears your Saber Wound.")
    if picked:
        ignored = [ctx.target.entity_id] if bears_mark(ctx.target, ctx.actor.entity_id, "Saber Wound") else []
        move(ctx.engine, ctx.actor, by_id[picked[0]], ctx.intent, feet, ignored, name="Red Trail Pursuit")
