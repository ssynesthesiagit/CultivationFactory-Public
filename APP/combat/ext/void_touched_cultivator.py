"""Void-Touched Cultivator's acquired family state and the Void Step record.

Ownership is an exact recorded acquisition (native NS1R/Stage 2 provenance
projected into the fight bundle), never a Void Sphere or a similar name. The
permanent Void Scar is written at acquisition and travels on every family
action; without it the feature is inert.

Void Marks are shared typed state for every record of this Secret Law. They are
stored through the engine's ordinary mark namespace (owner-scoped condition
instance, integer ``count``, ``ends_with_scene``), so later records can read and
spend them with the existing mark helpers. They are not curses: nothing on the
table removes them except their own scene end or a future explicitly purifying
effect.

Only Void Step is implemented here. Empty Palm, Hollow Field, Erase, Law of
Nonexistence and the Deepen/Deep entries belong to later lanes.

Hooks used (all documented in combat/ext/__init__.py):
  compile_action              seal SELF teleport shape, the Scar and the CL gate
  candidate_allowed           once-per-turn and the inert-without-Scar guard
  candidate_unavailability    plain reason beside a veto
  resolution_final            record the use after a real activation
  teleport_landing_allowed    "visible or precisely known" destination query
  teleport_gate               printed crossing prohibitions, before any save
  teleport_landing_recovery   nearest legal space on the destination side
  teleport_settled            Trace of Nonexistence after the step committed
  mark_apply                  counted Void Mark (cap 3 per source)
  observer_information        the Scar and a marked target's Void sign
"""
from __future__ import annotations

from typing import Any

from . import hook

PARENT = "tianxia.subpath.qi.void_touched_cultivator"
PREFIX = PARENT + ".feature."
VOID_STEP = PREFIX + "void_step"
TIERS = {"void_step": 3, "empty_palm": 6, "hollow_field": 10,
         "erase": 14, "law_of_nonexistence": 18}
MARK_NAME = "Void Mark"
MARK_CAP = 3
USE_FLAG = "_void_step_turn"
TRACE_FLAG = "_void_trace_turn"
SEALED_FEATURES = {VOID_STEP}


def family_source(action: Any) -> str:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    source = str(typed.get("source") or "")
    return source if source.startswith(PREFIX) else ""


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _numbers(action: Any) -> dict[str, Any]:
    return _typed(action).get("numbers") or {}


def source_cl(action: Any) -> int:
    numbers = _numbers(action)
    return int(numbers.get("source_cl") or numbers.get("cl") or 1)


def _scar(typed: dict[str, Any]) -> str:
    value = typed.get("void_scar")
    return value if isinstance(value, str) else ""


def owns(action: Any, actor: Any) -> bool:
    """The exact acquired feature and its recorded permanent Scar, on this actor's row."""
    if family_source(action) not in SEALED_FEATURES or getattr(action, "owner_id", None) != actor.entity_id:
        return False
    return bool(_scar(_typed(action)))


def composed_scar(action: Any) -> str:
    return _scar(_typed(action))


def actor_scar(engine: Any, actor: Any) -> str:
    """The permanent Scar sealed into this actor's own family actions (pure, reload-safe)."""
    for action_id in getattr(actor, "action_ids", ()):
        action = engine.action_catalog.get(action_id)
        source = family_source(action)
        if source and source in SEALED_FEATURES:
            scar = composed_scar(action)
            if scar:
                return scar
    return ""


def mark_count(target: Any, owner_id: str) -> int:
    from ..typed_executor import mark_condition_id

    condition_id = mark_condition_id(MARK_NAME, owner_id)
    total = 0
    for condition in target.conditions.values():
        if condition.condition_id == condition_id:
            total += int((condition.data or {}).get("count") or 1)
    return total


def _add_mark(engine: Any, action: Any, owner: Any, target: Any) -> int:
    """Place one Void Mark from ``owner``: cap 3, one owner-scoped instance, scene lifetime."""
    from ..typed_executor import mark_condition_id

    condition_id = mark_condition_id(MARK_NAME, owner.entity_id)
    count = min(MARK_CAP, mark_count(target, owner.entity_id) + 1)
    for held in [c for c in target.conditions.values() if c.condition_id == condition_id]:
        engine._remove_condition_instance(target, held.instance_id, action.source_definition_id, expected=held)
    engine._apply_condition(
        target, condition_id, action.source_definition_id, owner.entity_id, expires_on=None,
        data={"count": count, "ends_with_scene": 1, "source_cl": source_cl(action),
              "sign": "a fixed Void absence: a silent outline or a missing shadow",
              "label": f"{count} Void Mark{'s' if count != 1 else ''} from {owner.display_name} — a fixed Void sign perceptible through Qi Sensing until the scene ends"})
    return count


# ------------------------------------------------------------------------------------------------ admission / compilation
@hook("compile_action")
def compile_family(action: Any, info: dict[str, Any]) -> Any:
    from character_creation.acquisition_choices import recorded

    source = family_source(action)
    if not source:
        return None
    feature = source[len(PREFIX):]
    typed = dict(_typed(action))
    scar = recorded(info.get("owner_sheet") or {}, PARENT).get("void_scar") or ""
    typed.update(min_cl=TIERS.get(feature, 1), void_scar=scar)
    if not scar:
        typed["effects"] = []
        typed["riders"] = [*(typed.get("riders") or []),
                           "Acquire the Void-Touched Cultivator Secret Law through your Path progression to use this feature."]
        return action.model_copy(update={"parameters": {**action.parameters, "typed": typed}})
    updates: dict[str, Any] = {}
    if feature == "void_step":
        # Trace of Nonexistence chooses its creature after the departed and
        # arrived spaces are both committed, so the generic aimed mark is not
        # part of the step's aimed effects.
        typed["effects"] = [row for row in typed.get("effects") or [] if row.get("type") != "mark"]
        typed["range_ft"] = 30
        updates.update(target_kind="SELF", range_ft=30)
    return action.model_copy(update={**updates, "parameters": {**action.parameters, "typed": typed}})


def _turn(engine: Any, actor: Any) -> str:
    return f"{engine.state.round_number}:{actor.turns_started}"


@hook("candidate_allowed")
def family_admission(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = family_source(action)
    if not source:
        return None
    if not composed_scar(action):
        return False
    if source == VOID_STEP and actor.turn_flags.get(USE_FLAG) == _turn(engine, actor):
        return False
    return None


@hook("candidate_unavailability")
def family_reason(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    if family_source(action) != VOID_STEP:
        return None
    if not composed_scar(action):
        return ("Void Step is not yours yet: acquire the Void-Touched Cultivator Secret Law through your "
                "Path progression, choosing its permanent Void Scar.")
    if actor.turn_flags.get(USE_FLAG) == _turn(engine, actor):
        return "Void Step has already been used this turn (limit: once per turn)."
    return None


@hook("resolution_final")
def record_use(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    if family_source(action) == VOID_STEP and composed_scar(action):
        actor.turn_flags[USE_FLAG] = _turn(engine, actor)


# ------------------------------------------------------------------------------------------------ destinations and crossings
def _route(engine: Any, start: Any, destination: Any) -> list[tuple[int, int]]:
    return [(cell[0], cell[1]) for cell in engine.grid.ray_cells(start, destination)]


def _committed_positions(engine: Any, actor: Any) -> tuple[Any, ...]:
    from ..gate2_runtime_models import Position
    from ..read_queries import memo

    def collect():
        seen, out = set(), []

        def add(position: Any) -> None:
            key = (position.x, position.y, position.z)
            if key not in seen:
                seen.add(key)
                out.append(position)

        add(actor.position)
        for event in engine.events:
            if getattr(event, "actor_id", None) != actor.entity_id:
                continue
            if getattr(event, "event_type", None) != "MOVEMENT_COMMITTED":
                continue
            for row in (event.payload or {}).get("path") or []:
                try:
                    add(Position.model_validate(row))
                except (TypeError, ValueError):
                    continue
        return tuple(out)

    return memo(engine, ("void_committed_positions", actor.entity_id), collect)


def precisely_known(engine: Any, actor: Any, cell: Any) -> bool:
    """A space this character has actually seen from a committed position this scene."""
    return any(engine.grid.line_of_sight(position, cell) for position in _committed_positions(engine, actor))


def _touches(route: list[tuple[int, int]], zone: Any) -> bool:
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    return any(cell in cells for cell in route)


def crossing_problem(engine: Any, actor: Any, start: Any, destination: Any, action: Any) -> str | None:
    """The first printed Void Step prohibition the straight crossing meets, or None.

    Reads only facts the table already keeps: the mover's no-teleport rules and
    spatial-lock condition, active zone rules (sealed barriers and planar /
    extradimensional boundaries), a sealed Formation's Source CL, and the solid
    material actually crossed (up to 5 feet of ordinary solid, and none of it
    sealed). There is no separate artifact/plane schema in the repository and
    this plug-in invents none.
    """
    from .. import zones
    from ..typed_executor import condition_rules
    from . import formations
    from .chains_sphere import SPATIAL  # the public condition identity of a spatial lock, not private state

    level = source_cl(action)
    route = _route(engine, start, destination)
    if any(rule.get("no_teleport") for rule in condition_rules(actor, engine=engine)):
        return "a seal or spatial lock on the traveller blocks teleportation."
    if any(condition.condition_id == SPATIAL for condition in actor.conditions.values()):
        return "a spatial lock holds the traveller."
    for zone in zones.typed_zones(engine):
        rule = (zone.trigger_profile or {}).get("rule") or {}
        if not (rule.get("no_teleport") or rule.get("no_extradimensional_movement")):
            continue
        if _touches(route, zone):
            return "a sealed barrier or planar boundary lies on the path."
    for zone in formations.arrays(engine):
        record = formations.record(zone)
        if "sealing_gate" not in (record.get("layers") or []):
            continue
        if _touches(route, zone) and int(record.get("cl") or 0) >= level:
            return "a sealed Formation whose Source CL equals or exceeds the traveller's bars the path."
    solid = [cell for cell in route[1:-1] if engine.grid.terrain_at((cell[0], cell[1], 0), "BLOCKED")]
    if len(solid) > 1:
        return "more than 5 feet of solid material lies between the spaces."
    if solid:
        from ..terrain_materials import query as materials_at

        for cell in solid:
            if any(record.get("sealed") for record in materials_at(engine, (cell[0], cell[1], 0))):
                return "the solid material is sealed or cultivated."
    return None


def _visible(engine: Any, actor: Any, cell: Any) -> bool:
    return engine._line_of_sight_actor_to_cell(actor, cell)


@hook("teleport_landing_allowed")
def void_step_landing(engine: Any, actor: Any, cell: Any, feet: int, action: Any) -> bool | None:
    if family_source(action) != VOID_STEP:
        return None
    if not composed_scar(action):
        return False
    if crossing_problem(engine, actor, actor.position, cell, action):
        return False
    return True if _visible(engine, actor, cell) or precisely_known(engine, actor, cell) else False


@hook("teleport_gate")
def void_step_gate(ctx: Any, start: Any, destination: Any) -> bool | None:
    if family_source(ctx.action) != VOID_STEP or not composed_scar(ctx.action):
        return None
    problem = crossing_problem(ctx.engine, ctx.actor, start, destination, ctx.action)
    if problem:
        ctx.rider(f"Void Step fails: {problem} Its Qi and Bonus Action are still spent.")
        return False
    return None


@hook("teleport_landing_recovery")
def void_step_recovery(ctx: Any, actor: Any, start: Any, destination: Any) -> Any | None:
    """Nearest legal unoccupied space within 10 feet of the destination, on the destination side."""
    from ..gate2_runtime_models import Position

    if family_source(ctx.action) != VOID_STEP or not composed_scar(ctx.action):
        return None
    reach = int(_typed(ctx.action).get("range_ft") or 30)
    occupied = ctx.engine._occupied_cells_except(actor.entity_id)
    options = []
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            cell = Position(x=destination.x + dx, y=destination.y + dy)
            if cell == start or ctx.engine.grid.distance_ft(destination, cell) > 10:
                continue
            if ctx.engine.grid.distance_ft(start, cell) > reach:
                continue
            if not ctx.engine.grid.placement_legal(cell, footprint=ctx.engine._footprint(actor), occupied_cells=occupied):
                continue
            if crossing_problem(ctx.engine, actor, start, cell, ctx.action):
                continue
            options.append((ctx.engine.grid.distance_ft(destination, cell), cell.y, cell.x, cell))
    return min(options)[3] if options else None


# ------------------------------------------------------------------------------------------------ Trace of Nonexistence
def _perceives(engine: Any, viewer: Any, target: Any) -> bool:
    from ..senses import perceives

    return viewer.entity_id == target.entity_id or perceives(engine, viewer, target)


@hook("teleport_settled")
def trace_after_step(ctx: Any, subject: Any, previous: Any, destination: Any, unwilling: Any) -> None:
    if subject is not ctx.actor or family_source(ctx.action) != VOID_STEP or not composed_scar(ctx.action):
        return
    engine = ctx.engine
    eligible = []
    for target in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if target is subject or not target.active or target.turn_flags.get(TRACE_FLAG) == _turn(engine, target):
            continue
        near_departure = engine._distance_actor_to_cell(target, previous) <= 5
        near_arrival = engine._distance_actor_to_cell(target, destination) <= 5
        if (near_departure or near_arrival) and _perceives(engine, subject, target):
            eligible.append(target)
    if not eligible:
        return
    by_id = {target.entity_id: target for target in eligible}
    chosen = None
    from .teleport_steps import player_controls

    if player_controls(engine, subject):
        from .needle import ask, checkpoint_id

        enemies = [target.entity_id for target in eligible
                   if target.team_id != subject.team_id]
        answer = ask(engine, ctx.intent, checkpoint_id(engine, "void_step_trace", subject.entity_id),
                     subject, "choice:needle.void_step_trace", list(by_id),
                     labels={key: target.display_name for key, target in by_id.items()},
                     preferred=enemies[:1] or list(by_id)[:1], allow_decline=True,
                     name="Void Step — Trace of Nonexistence",
                     prompt=(f"Void Step: {subject.display_name} disappeared and reappeared. Choose one creature "
                             "you can perceive within 5 feet of either the space it left or the space it reached. "
                             "It gains 1 Void Mark until the scene ends, at no additional Qi cost."))
        chosen = answer[0] if answer else None
    else:
        enemies = [target.entity_id for target in eligible if target.team_id != subject.team_id]
        chosen = (enemies or list(by_id))[0]
    if chosen is None:
        return
    target = by_id[chosen]
    _add_mark(engine, ctx.action, subject, target)
    target.turn_flags[TRACE_FLAG] = _turn(engine, target)
    engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=subject.entity_id,
                         target_ids=(target.entity_id,),
                         payload={"log": f"Trace of Nonexistence: {target.display_name} gains 1 Void Mark from "
                                         f"{subject.display_name}; one Trace mark per creature per turn."})


@hook("mark_apply")
def counted_void_mark(ctx: Any, effect_row: dict[str, Any], subject: Any, expires: Any, data: Any) -> bool | None:
    """Counted, owner-scoped Void Mark placement for every record of this Secret Law."""
    if str(effect_row.get("mark") or "").strip().lower() != MARK_NAME.lower():
        return None
    if not any(family_source(ctx.engine.action_catalog.get(key)) for key in getattr(ctx.actor, "action_ids", ())):
        return None
    _add_mark(ctx.engine, ctx.action, ctx.actor, subject)
    return True


# ------------------------------------------------------------------------------------------------ perceived signs
def _direction(engine: Any, a: Any, b: Any) -> str:
    dy, dx = b.y - a.y, b.x - a.x
    vertical = "above" if b.z > a.z else "below" if b.z < a.z else ""
    compass = {(0, -1): "north", (1, -1): "northeast", (1, 0): "east", (1, 1): "southeast",
               (0, 1): "south", (-1, 1): "southwest", (-1, 0): "west", (-1, -1): "northwest"}.get(
        ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0)), "here")
    if compass == "here" and not vertical:
        return "here"
    return " and ".join(part for part in (compass if compass != "here" else "", vertical) if part)


def _channel(engine: Any, observer: Any, target: Any) -> str | None:
    """The observer's conceptual channel for a Void sign: Qi Sensing or Secret perception."""
    from .. import senses

    for sense, label in (("qi_sensing", "Qi Sensing"), ("spiritual_sense", "Secret perception"),
                         ("spiritual_truesight", "Secret perception"), ("truesight", "Secret perception")):
        reach = senses.reach(engine, observer, sense, target)
        if reach > 0 and engine._distance_actor_to_actor(observer, target) <= reach:
            return label
    return None


@hook("observer_information")
def void_signs(engine: Any, observer: Any) -> list[dict[str, Any]]:
    if not getattr(observer, "active", False):
        return []
    facts = []
    for target in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if not target.active or target.entity_id == observer.entity_id:
            continue
        mine = mark_count(target, observer.entity_id)
        if mine and engine._distance_actor_to_actor(observer, target) <= 5280:
            facts.append({"ability": "Void Mark",
                          "text": (f"{target.display_name} bears {mine} of your Void Marks; you know its direction "
                                   f"({_direction(engine, observer.position, target.position)}) while it stays within "
                                   "1 mile on this plane. The sign itself is a fixed Void absence until the scene ends.")})
        elif any(mark_count(target, other.entity_id) for other in engine.state.actors.values()
                 if other.entity_id != observer.entity_id):
            channel = _channel(engine, observer, target)
            if channel:
                facts.append({"ability": channel,
                              "text": f"{target.display_name} carries a Void Mark: a fixed Void absence perceptible through {channel}."})
        scar = actor_scar(engine, target)
        if scar:
            channel = _channel(engine, observer, target)
            if channel:
                facts.append({"ability": channel,
                              "text": f"{target.display_name} bears a permanent Void Scar visible through {channel}: {scar}"})
    return facts
