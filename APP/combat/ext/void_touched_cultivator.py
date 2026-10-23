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

Void Step is implemented here. Empty Palm, Hollow Field and Erase are their own
plug-ins; the shared family helpers those records use (spending Void Marks, a
creature's Source CL, and the real cultivation systems a creature carries) live
here with a docstring naming those consumers. Law of Nonexistence and the
Deepen/Deep entries belong to later lanes.

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

import copy
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


# ------------------------------------------------------------------------------------------------ shared family helpers
# These readers are shared by the later records of this Secret Law. Consumers:
#   spend_marks             Deepen the Hollow (combat/ext/void_touched_hollow_field.py)
#                           and Erase Cultivation (combat/ext/void_touched_erase.py)
#   creature_cl             Hollow Field's repeat-save band and Erase's Deep Erasure bands
#   sphere_of_mechanic, systems, covers, take_system_rows, give_back_system_rows
#                           Hollow Field's Deepen the Hollow and Erase Cultivation, which
#                           both erase/suppress one real system and must take its live rows
#                           off the fight while it is unusable
# Each is pure or an evented engine mutation with the same contract the two records used
# before this extraction; no record-specific rule lives here.
SYSTEM = "condition:typed.suppressed_system"
SYSTEM_KINDS = {
    "sphere": "Sphere",
    "subpath": "Subpath",
    "method": "Method",
    "golden_core_form": "Golden Core Form",
    "nascent_soul": "Nascent Soul feature",
    "domain_armament": "Domain Armament system",
    "foundation": "Foundation active system",
    "path_recovery": "Path resource recovery feature",
    "secret_feature": "Secret or Immortal feature",
}


def spend_marks(engine: Any, owner: Any, target: Any, number: int, source: str, *, note: str = "") -> bool:
    """Spend ``number`` of ``owner``'s Void Marks from ``target`` (never doubles up).

    Shared by the family records that charge Void Marks at activation. The mark
    instance is the foundation's own owner-scoped counted condition, so a saved
    fight and a cold reload spend it the same way. ``note`` is the record's own
    plain-word prefix for the log line; the owner and the number are always named.
    """
    from ..typed_executor import mark_condition_id

    if mark_count(target, owner.entity_id) < number:
        return False
    condition_id = mark_condition_id(MARK_NAME, owner.entity_id)
    for instance_id, condition in list(target.conditions.items()):
        if condition.condition_id != condition_id:
            continue
        remaining = int((condition.data or {}).get("count") or 1) - number
        target.conditions.pop(instance_id)
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(target.entity_id,),
                             payload={"condition_id": condition_id, "instance_id": instance_id, "reason": "SPENT"})
        if remaining > 0:
            engine._apply_condition(target, condition_id, condition.source_definition_id, condition.source_actor_id,
                                    expires_on=condition.expires_on,
                                    data={**(condition.data or {}), "count": remaining,
                                          "label": f"{remaining} Void Mark{'s' if remaining != 1 else ''} from "
                                                   f"{owner.display_name} — a fixed Void sign perceptible through Qi "
                                                   f"Sensing until the scene ends"})
        engine._append_event("PASSIVE_TRIGGERED", source, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                             payload={"log": f"{note + ': ' if note else ''}{owner.display_name} spends {number} Void "
                                             f"Marks from {target.display_name}."})
        return True
    return False


def creature_cl(engine: Any, actor: Any) -> int:
    """The creature's Source CL, from its sealed typed numbers or its bundle."""
    from .ability_source import numbers_of

    numbers = numbers_of(engine, actor)
    cl = numbers.get("source_cl") or numbers.get("cl")
    if cl:
        return int(cl)
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == getattr(actor, "entity_id", None) and bundle.get("cl") is not None:
            return int(bundle["cl"])
    return 0


def sphere_of_mechanic(mechanic_id: str) -> str:
    """The Sphere a compiled talent belongs to, from the shipped typed authority.

    A passive talent has no catalog action, so its compiled passive row carries
    no sphere; the record's own typed entry is the only honest source. Read once
    and cached; no fight state and no runtime patching.
    """
    mapping = globals().get("_SPHERE_BY_MECHANIC")
    if mapping is None:
        import json

        from ..factory_compiler import TYPED_AUTHORITY

        try:
            mechanics = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8")).get("mechanics") or {}
        except (OSError, ValueError):
            mechanics = {}
        mapping = {str(key): str(row.get("sphere_id") or "") for key, row in mechanics.items()}
        globals()["_SPHERE_BY_MECHANIC"] = mapping
    return mapping.get(str(mechanic_id) or "", "")


def systems(engine: Any, creature: Any) -> list[dict[str, str]]:
    """Every major system this creature actually carries, in printed order.

    Read from the creature's own compiled actions and passive rows; a system it
    does not have is never offered (so a Method, which this table does not
    compile as a fight row, offers nothing).
    """
    found: dict[tuple[str, str], str] = {}

    def add(kind: str, value: str, label: str) -> None:
        if value and (kind, value) not in found:
            found[(kind, value)] = label

    rows: list[tuple[str, str, str, Any]] = []
    for action_id in getattr(creature, "action_ids", ()):
        action = engine.action_catalog.get(action_id)
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        rows.append((str(typed.get("source") or ""), str(typed.get("sphere") or ""),
                     str(getattr(action, "display_name", "") or ""), action))
    for store in ("typed_passive_rows", "typed_reaction_rows"):
        for row in (getattr(engine, store, {}) or {}).get(creature.entity_id, []) or []:
            rows.append((str(row.get("feature_id") or ""), "", str(row.get("name") or ""), None))
    for source, sphere, name, compiled_action in rows:
        if ".feature." in source:
            from . import source_eligibility

            # Compiled action ids are action:typed.<actor>.<mechanic>, not the
            # mechanic id carried in typed.source. Keep the actual action row;
            # passive-only features still resolve through their printed record.
            action = compiled_action or source_eligibility.catalog_action(engine, source)
            power = source_eligibility.printed_power(action) if action is not None else None
            if power is None and compiled_action is None:
                printed = source_eligibility.printed_text(source)
                power = ({"source": source}, printed) if printed else None
            if power and source_eligibility.protected_power(power[0], power[1], extra_categories=("Secret", "Immortal")):
                add("secret_feature", source, name or _title(source.rsplit(".", 1)[-1]))
        sphere = sphere or sphere_of_mechanic(source)
        if sphere:
            add("sphere", sphere, _title(sphere.rsplit(".", 1)[-1]))
        if source.startswith("tianxia.subpath."):
            add("subpath", source.split(".feature.")[0], _title(source.split(".feature.")[0].rsplit(".", 1)[-1]))
        if ".method." in source or source.startswith("tianxia.method."):
            add("method", source.split(".feature.")[0], _title(source.rsplit(".", 1)[-1]))
        if source.startswith("form.") or "feature.golden_core_form" in source or "feature.second_golden_core_form" in source:
            add("golden_core_form", "tianxia.path.qi_cultivation.feature.golden_core_form", "Golden Core Form")
        if "feature.nascent_soul" in source or source.startswith("nascent."):
            add("nascent_soul", "tianxia.path.qi_cultivation.feature.nascent_soul", "Nascent Soul")
        if source.startswith("armament.") or "feature.domain_armament" in source:
            add("domain_armament", "armament.", "Domain Armament")
        if source.startswith("foundation."):
            add("foundation", source.rsplit(".", 1)[0], _title(source.rsplit(".", 1)[0].rsplit(".", 1)[-1]))
        if _is_recovery(source, name):
            add("path_recovery", source, name or "Path resource recovery")
    order = {kind: index for index, kind in enumerate(SYSTEM_KINDS)}
    return [{"kind": kind, "value": value, "label": f"{SYSTEM_KINDS[kind]}: {found[(kind, value)]}"}
            for kind, value in sorted(found, key=lambda key: (order.get(key[0], 99), key[1]))]


def covers(record: dict[str, Any], source: str, sphere: str = "") -> bool:
    """Whether a recorded system (kind/value) is the source or sphere of this row."""
    kind, value = str(record.get("kind") or ""), str(record.get("value") or "")
    if not value:
        return False
    if kind == "sphere":
        return sphere == value or source.startswith(value)
    if kind == "domain_armament":
        return source.startswith("armament.") or "feature.domain_armament" in source
    if kind == "golden_core_form":
        return source.startswith("form.") or "feature.golden_core_form" in source
    if kind == "nascent_soul":
        return "feature.nascent_soul" in source or source.startswith("nascent.")
    return source == value or source.startswith(value + ".")


def take_system_rows(engine: Any, target: Any, kind: str, value: str) -> dict[str, Any]:
    """Take the suppressed system's live passive/reaction rows off the fight, keeping them on the record.

    Shared by Deepen the Hollow and Erase Cultivation. The returned snapshot is
    stored on the suppression condition (integers and strings only) so the rows
    can be given back when the record ends; ``give_back_system_rows`` is
    idempotent because a cold reload rebuilds the rows from the sealed bundle.
    """
    taken: dict[str, Any] = {"passive": [], "reaction": []}
    for store, key in (("typed_passive_rows", "passive"), ("typed_reaction_rows", "reaction")):
        rows = (getattr(engine, store, {}) or {}).get(target.entity_id) or []
        keep = []
        for row in rows:
            source = str(row.get("feature_id") or "")
            sphere = str(row.get("sphere") or "") or sphere_of_mechanic(source)
            if covers({"kind": kind, "value": value}, source, sphere):
                taken[key].append(copy.deepcopy(row))
            else:
                keep.append(row)
        getattr(engine, store)[target.entity_id] = keep
    return taken


def give_back_system_rows(engine: Any, target: Any, data: dict[str, Any]) -> None:
    """Put a system's retained rows back, skipping any the bundle already rebuilt."""
    rows = data.get("rows") or {}
    for store, key in (("typed_passive_rows", "passive"), ("typed_reaction_rows", "reaction")):
        current = list((getattr(engine, store, {}) or {}).get(target.entity_id) or [])
        known = {str(row.get("feature_id")) for row in current}
        for row in rows.get(key) or []:
            if str(row.get("feature_id")) not in known:
                current.append(copy.deepcopy(row))
        getattr(engine, store)[target.entity_id] = current


def _title(text: str) -> str:
    return " ".join(word.capitalize() for word in str(text).replace("_", " ").split())


def _is_recovery(source: str, name: str) -> bool:
    text = f"{source} {name}".lower()
    return bool(source) and ("recover" in text or "regain" in text)
