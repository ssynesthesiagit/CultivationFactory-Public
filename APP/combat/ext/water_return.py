"""Returning Streams resolves actual ended effects before offering healing.

Only the owned Returning Streams variants change. End It Early selects up to
three owner-created Water effects within 60 feet; instances from one activation
count as one effect, even when they affect several creatures. Move selects up to
three independent Water areas and relocates each up to 20 feet, preserving its
identity and remaining lifetime. Minor Return consumes its selected effect;
its menu also allows a different operation for each selected effect. Only
effects actually ended (including conversions) satisfy the healing prerequisite.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import CHOICE, ask, checkpoint_id

STREAMS = "TAL_WATER_TEN_THOUSAND_RETURNING_STREAMS"
COURT = "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"
RETURN = "WATER_BASE_RETURN_THE_FLOW"


def _source(engine: Any, source: str) -> str:
    action = engine.action_catalog.get(source)
    return str(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") or source)


def _court(engine: Any, actor: Any) -> Any:
    return next((z for z in engine.state.zones.values() if z.active and z.owner_id == actor.entity_id
                 and _source(engine, z.source_definition_id) == COURT
                 and actor.position in z.affected_cells), None)


def _effects(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    """Identify real Water activations, not arbitrary conditions or GM notes."""
    result: dict[str, dict[str, Any]] = {}
    # Derive provenance from original application events, not replay-only
    # upserts. One action definition can be activated several times, while one
    # activation can create several companion conditions/modifiers.
    from .retained_updates import is_retained_update

    activations = {}
    accepted = {}
    for event in engine.events:
        source = event.source_definition_id
        if event.event_type == "INTENT_ACCEPTED":
            accepted[(event.actor_id, source)] = event.sequence
        if is_retained_update(event.event_type, event.payload):
            continue
        key = event.payload.get("instance_id") or event.payload.get("modifier_id")
        if key and event.event_type in ("CONDITION_APPLIED", "MODIFIER_APPLIED"):
            activations.setdefault(key, accepted.get((event.actor_id, source), event.sequence))
        if event.event_type == "ZONE_CREATED":
            zone = event.payload.get("zone") or {}
            if zone.get("zone_id"):
                activations.setdefault(zone["zone_id"], accepted.get((event.actor_id, source), event.sequence))

    def water(source: str) -> bool:
        return _source(engine, source).startswith(("WATER_BASE_", "TAL_WATER_"))

    for zone in engine.state.zones.values():
        if zone.active and zone.owner_id == actor.entity_id and water(zone.source_definition_id) \
                and engine.grid.distance_ft(actor.position, zone.center) <= 60:
            result[zone.zone_id] = {"zone": zone, "label": str(zone.trigger_profile.get("name") or "Water area")}
    for holder in engine.state.actors.values():
        if not holder.active or engine.grid.distance_ft(actor.position, holder.position) > 60:
            continue
        for kind, instances in (("condition", holder.conditions), ("modifier", holder.modifiers)):
            for key, item in instances.items():
                if item.source_actor_id != actor.entity_id or not water(item.source_definition_id):
                    continue
                if kind == "modifier" and item.consumed:
                    continue
                # A zone's inside bookkeeping is part of that zone, not an extra effect.
                if (getattr(item, "data", None) or {}).get("zone_id") or \
                        getattr(item, "condition_id", "") == "condition:typed.concentration_held":
                    continue
                source = item.source_definition_id
                activation = activations.get(key, getattr(item, "applied_sequence", key))
                if any(z.active and z.owner_id == actor.entity_id and z.source_definition_id == source
                       and activations.get(z.zone_id) == activation
                       for z in engine.state.zones.values()):
                    continue
                group = f"effect:{source}@{activation}"
                action = engine.action_catalog.get(source)
                row = result.setdefault(group, {"instances": [], "label": getattr(action, 'display_name', 'Water effect')})
                row["instances"].append((holder, kind, key, item))
    for row in result.values():
        if row.get("instances"):
            names = list(dict.fromkeys(holder.display_name for holder, *_ in row["instances"]))
            row["label"] += " on " + ", ".join(names)
    return result


@hook("compile_action")
def returning_streams_action(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get("typed") or {}
    if STREAMS not in info["owned_ids"] or typed.get("source") != RETURN \
            or (typed.get("modifier") or {}).get("id") != STREAMS:
        return None
    effects = copy.deepcopy(typed.get("effects") or [])
    healing = [e for e in effects if e.get("source_modifier") == STREAMS]
    base = [e for e in effects if e.get("source_modifier") != STREAMS]
    if not healing:
        return None
    ending = any(e.get("type") == "zone" and e.get("remove") for e in base)
    moving = any(e.get("type") == "zone" and int(e.get("distance_ft") or 0) > 0 and not e.get("remove") for e in base)
    if moving:
        parameters = {**action.parameters, "typed": {**typed, "effects": [{"type": "water_returning_streams_move"}]}}
        return action.model_copy(update={"parameters": parameters})
    if not ending:
        preferred = "soak" if any(e.get("mark") == "Soaked" for e in base) else "ally"
        replacement = {"type": "water_returning_streams_minor", "preferred": preferred, "healing": healing}
        # Recorded map operations now resolve below. Unknown scenery gets its
        # own specific fallback; do not also emit the obsolete blanket rider.
        riders = [r for r in typed.get('riders') or []
                  if not str(r).startswith('Extinguishing an ordinary flame or regaining awareness of the nearest Water Source')]
        return action.model_copy(update={"target_kind": "SELF", "parameters": {**action.parameters, "typed": {**typed, "effects": [replacement], 'riders': riders}}})
    replacement = {"type": "water_returning_streams", "end": ending, "healing": healing}
    # The selected end operation replaces the old GM-only zone removal note.
    parameters = {**action.parameters, "typed": {**typed, "effects": [*([] if ending else base), replacement]}}
    return action.model_copy(update={"parameters": parameters})


def _end_effect(ctx: Any, row: dict[str, Any]) -> bool:
    """End one activation, including its linked concentration and bookkeeping."""
    from .. import concentration, zones

    if row.get("zone"):
        zone = row["zone"]
        if not zone.active:
            return False
        if ctx.actor.concentration and ctx.actor.concentration.zone_id == zone.zone_id:
            ctx.engine._end_concentration(ctx.actor, "RETURN_THE_FLOW")
        else:
            held = next((key for key, state in concentration.held(ctx.actor) if state.zone_id == zone.zone_id), None)
            if held:
                concentration.end_held(ctx.engine, ctx.actor, held, "RETURN_THE_FLOW")
            else:
                zones.remove(ctx.engine, zone, "RETURN_THE_FLOW")
        zones.sync_inside(ctx.engine, ctx.source)
        return True
    removed = False
    for holder, kind, instance, item in row["instances"]:
        if kind == "condition" and instance in holder.conditions:
            del holder.conditions[instance]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id,
                                     target_ids=(holder.entity_id,), payload={"condition_id": item.condition_id, "instance_id": instance})
            removed = True
        elif kind == "modifier" and instance in holder.modifiers:
            del holder.modifiers[instance]
            ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=ctx.actor.entity_id,
                                     target_ids=(holder.entity_id,), payload={"modifier_id": instance})
            removed = True
    return removed


def _heal(ctx: Any, spec: dict[str, Any], domain: Any, ended: int) -> None:
    from ..typed_executor import Context, run_effects

    if ended < 2 or not domain.active:
        return
    allies = {a.entity_id: a for a in ctx.engine.state.actors.values()
              if a.active and a.team_id == ctx.actor.team_id and a.position in domain.affected_cells}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_HEAL", ctx.actor.entity_id), ctx.actor,
                   CHOICE + "returning_streams_heal", list(allies), allow_decline=True,
                   labels={key: f"Restore {ctx.numbers.get('key_mod', 0) + ctx.numbers.get('pb', 0)} HP to {ally.display_name}" for key, ally in allies.items()},
                   name="Ten Thousand Returning Streams", feature_id=STREAMS,
                   prompt=f"Return the Flow ended {ended} Water effects. Ten Thousand Returning Streams: choose one ally inside your Court to heal (no extra Cultivation Point cost), or decline.")
    if selected:
        ally = allies[selected[0]]
        sub = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [ally], ally, ctx.damage_cache)
        run_effects(sub, spec["healing"])


def _destinations(engine: Any, zone: Any) -> dict[str, tuple[Any, tuple[Any, ...]]]:
    """Rigid translations on the table; no size, lifetime or trigger changes.

    This moves water, not creatures, so creatures are never carried through a
    wall or subjected to movement/entry triggers by this operation.
    Court of the Endless Tide is a printed Emanation from its creator, even
    when a saved zone lacks following metadata; Return cannot detach it.
    """
    from ..gate2_runtime_models import Position

    if _source(engine, zone.source_definition_id) == COURT or zone.trigger_profile.get("follows_owner") \
            or zone.trigger_profile.get("anchor_id"):
        return {}
    result = {}
    reach = 20 // engine.grid.square_size_ft
    for y in range(max(0, zone.center.y - reach), min(engine.grid.height, zone.center.y + reach + 1)):
        for x in range(max(0, zone.center.x - reach), min(engine.grid.width, zone.center.x + reach + 1)):
            center = Position(x=x, y=y)
            feet = engine.grid.distance_ft(zone.center, center)
            if not 0 < feet <= 20:
                continue
            dx, dy = x - zone.center.x, y - zone.center.y
            points = [(cell.x + dx, cell.y + dy) for cell in zone.affected_cells]
            if not points or not all(engine.grid.in_bounds(point) for point in points):
                continue
            result[f"{x},{y}"] = (center, tuple(Position(x=cx, y=cy) for cx, cy in points))
    return result


@hook("button_description")
def returning_streams_move_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("type") == "water_returning_streams_move" for e in effects):
        return None
    timing = "no Action or Bonus Action, once per turn" if row.get("economy") == "NONE" else "Bonus Action"
    return (f"Return the Flow, {timing}, no Cultivation Point cost: while inside your Court of the Endless Tide, "
            "choose up to three Water areas you created within 60 feet and move each up to 20 feet. "
            "Their size and remaining duration stay the same; creatures stay where they are. "
            "This option cannot move your Court or detach effects from creatures. Moving areas grants no healing.")


@effect("water_returning_streams_move")
def returning_streams_move(ctx: Any, spec: dict[str, Any]) -> None:
    if _court(ctx.engine, ctx.actor) is None:
        ctx.rider("Ten Thousand Returning Streams requires you to stand inside your Court of the Endless Tide.")
        return
    available = {key: row for key, row in _effects(ctx.engine, ctx.actor).items() if row.get("zone")}
    destinations = {key: _destinations(ctx.engine, row["zone"]) for key, row in available.items()}
    available = {key: row for key, row in available.items() if destinations[key]}
    if not available:
        ctx.rider("Return the Flow: no independent Water area of yours within 60 feet can move while keeping its whole area on this map.")
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_MOVE", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "returning_streams_move", list(available), maximum=3, allow_decline=True,
                 default_count=min(3, len(available)),
                 labels={key: f"Move {row['label']} up to 20 feet" for key, row in available.items()},
                 name="Ten Thousand Returning Streams", feature_id=STREAMS,
                 prompt=f"{ctx.actor.display_name} uses Return the Flow: Move Water Effect. Choose up to three of your Water areas within 60 feet. "
                        "Move each up to 20 feet, keeping its remaining duration; creatures stay where they are. No extra Cultivation Point cost.")
    for key in chosen:
        row, options = available[key], destinations[key]
        _move_area(ctx, key, row, options)


def _move_area(ctx: Any, key: str, row: dict[str, Any], options: dict[str, Any]) -> None:
    from .. import zones
    from .retained_updates import record_zone_update

    zone = row["zone"]
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_DESTINATION", key), ctx.actor,
                   CHOICE + "returning_streams_destination", list(options), allow_decline=True,
                   labels={key: f"Move {row['label']} {ctx.engine.grid.distance_ft(zone.center, value[0])} feet to square ({value[0].x}, {value[0].y})"
                           for key, value in options.items()},
                   name="Ten Thousand Returning Streams", feature_id=STREAMS,
                   prompt=f"{ctx.actor.display_name} uses Return the Flow: choose where to move {row['label']} (up to 20 feet), or leave it in place. "
                          "Its remaining duration stays the same; no extra Cultivation Point cost.")
    if not selected:
        return
    zone.center, zone.affected_cells = options[selected[0]]
    record_zone_update(ctx.engine, zone)
    zones.sync_inside(ctx.engine, ctx.source)
    ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
                             payload={"text": f"Return the Flow: {ctx.actor.display_name} moves {row['label']} to square "
                                              f"({zone.center.x}, {zone.center.y}); its remaining duration is unchanged."})


@hook("button_description")
def returning_streams_minor_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("type") == "water_returning_streams_minor" for e in effects):
        return None
    timing = "no Action or Bonus Action, once per turn" if row.get("economy") == "NONE" else "Bonus Action"
    return (f"Return the Flow, {timing}, no Cultivation Point cost: inside your Court of the Endless Tide, "
            "choose up to three of your Water effects within 60 feet. For each, move an independent area up to 20 feet "
            "without changing its remaining duration, end it, or consume it to soak one creature or move one ally "
            "in or adjacent to it 5 feet without Opportunity Attacks (each creature once per turn). "
            "Soaked lasts until the end of your next turn and enables Water talents that require a wet target. "
            "You may instead consume it to extinguish an ordinary flame nearby or sense the nearest obvious Water Source "
            "within 60 feet; the GM resolves flames and sources. Ending at least two effects, including consumed effects, "
            "lets you optionally heal one ally inside the Court by your Water ability modifier plus Proficiency Bonus.")


def _nearby(ctx: Any, row: dict[str, Any]) -> dict[str, Any]:
    zone = row.get("zone")
    cells = zone.affected_cells if zone else tuple(holder.position for holder, *_ in row["instances"])
    return {a.entity_id: a for a in ctx.engine.state.actors.values() if a.active
            and any(ctx.engine.grid.distance_ft(a.position, cell) <= 5 for cell in cells)}


def _moved_this_turn(ctx: Any, target: Any) -> bool:
    slot = f"{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}"
    return any(e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("returning_streams_moved") == target.entity_id
               and e.payload.get("turn") == slot for e in ctx.engine.events)


@effect("water_returning_streams_minor")
def returning_streams_minor(ctx: Any, spec: dict[str, Any]) -> None:
    from ..typed_executor import mark_condition_id
    from .effect_durations import token
    from .needle import cell_id, free_cells, position_of, step_to

    domain = _court(ctx.engine, ctx.actor)
    if domain is None:
        ctx.rider("Ten Thousand Returning Streams requires you to stand inside your Court of the Endless Tide.")
        return
    available = _effects(ctx.engine, ctx.actor)
    preferred = [key for key, row in available.items() if row.get("zone") is not domain]
    mode = (getattr(ctx.engine, "typed_control_modes", {}) or {}).get(ctx.actor.owner_id or ctx.actor.entity_id, "MANUAL")
    maximum = 3 if mode == "MANUAL" else min(3, len(preferred)) or 1
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_SELECT", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "returning_streams_select", list(available), maximum=maximum, preferred=preferred,
                 default_count=min(3, len(preferred)) or 1, allow_decline=True,
                 labels={key: row["label"] for key, row in available.items()}, name="Ten Thousand Returning Streams", feature_id=STREAMS,
                 prompt=f"{ctx.actor.display_name} uses Return the Flow. Choose up to three Water effects you created within 60 feet; "
                        "then choose separately whether to move, end or consume each for a minor effect. No extra Cultivation Point cost.")
    ended = 0
    for key in chosen:
        # An earlier ending can remove linked effects. Never convert a stale selection.
        row = _effects(ctx.engine, ctx.actor).get(key)
        if row is None:
            continue
        near = _nearby(ctx, row)
        allies = {aid: a for aid, a in near.items() if a.team_id == ctx.actor.team_id and not _moved_this_turn(ctx, a)}
        cells = {aid: {cell_id(p): p for p, cost in free_cells(ctx.engine, a, 5).items() if cost > 0}
                 for aid, a in allies.items()}
        allies = {aid: a for aid, a in allies.items() if cells[aid]}
        zone = row.get("zone")
        destinations = _destinations(ctx.engine, zone) if zone else {}
        from .water_map import ordinary_flames, obvious_sources, extinguish, flame_label
        effect_cells = zone.affected_cells if zone else tuple(holder.position for holder, *_ in row['instances'])
        flames = ordinary_flames(ctx.engine, ctx.actor, effect_cells)
        sources = obvious_sources(ctx.engine, ctx.actor)
        labels = {"end": f"End {row['label']} now", "flame": f"Consume {row['label']} to extinguish one ordinary flame in or adjacent to it",
                  "source": f"Consume {row['label']} to sense the nearest obvious Water Source within 60 feet"}
        if destinations:
            labels["move"] = f"Move {row['label']} up to 20 feet; keep its remaining duration"
        if near:
            labels["soak"] = f"Consume {row['label']} to soak one creature in or adjacent to it until the end of your next turn"
        if allies:
            labels["ally"] = f"Consume {row['label']} to move one nearby ally 5 feet without Opportunity Attacks"
        operation = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_OPERATION", key), ctx.actor,
                        CHOICE + "returning_streams_operation", list(labels), labels=labels, allow_decline=True,
                        preferred=[spec["preferred"]] if spec.get("preferred") in labels else ["end"],
                        name="Ten Thousand Returning Streams", feature_id=STREAMS,
                        prompt=f"{ctx.actor.display_name} uses Return the Flow on {row['label']}: move, end, or consume it for one minor effect? "
                               "Consuming ends the original effect; no extra Cultivation Point cost.")
        if not operation:
            continue
        operation = operation[0]
        if operation == "move":
            _move_area(ctx, key, row, destinations)
            continue
        if operation == "end":
            ended += int(_end_effect(ctx, row))
            continue
        target = None
        destination = None
        flame = None
        if operation == 'flame' and flames:
            selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'RETURNING_STREAMS_FLAME', key), ctx.actor,
                           CHOICE + 'returning_streams_flame', list(flames), allow_decline=True,
                           preferred=[oid for oid, obj in flames.items()
                                      if getattr(obj, 'team_id', None) == ctx.actor.team_id],
                           labels={oid: f'Extinguish ordinary flames on {flame_label(obj)}'
                                   for oid, obj in flames.items()},
                           name='Ten Thousand Returning Streams', feature_id=STREAMS,
                           prompt=f'Return the Flow: choose one ordinary flame in or adjacent to {row["label"]}. '
                                  'This consumes the Water effect; no extra Cultivation Point cost.')
            if not selected:
                continue
            flame = flames[selected[0]]
        if operation in ("soak", "ally"):
            targets = near if operation == "soak" else allies
            selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_TARGET", key), ctx.actor,
                           CHOICE + "returning_streams_target", list(targets), allow_decline=True,
                           labels={aid: ("Soak " if operation == "soak" else "Move ") + a.display_name for aid, a in targets.items()},
                           name="Ten Thousand Returning Streams", feature_id=STREAMS,
                           prompt=f"Return the Flow: choose which creature in or adjacent to {row['label']} to "
                                  + ("soak until the end of your next turn" if operation == "soak" else "move 5 feet without Opportunity Attacks")
                                  + "; consuming this Water effect costs no extra Cultivation Points.")
            if not selected:
                continue
            target = targets[selected[0]]
            if operation == "ally":
                selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS_ALLY_DESTINATION", key, target.entity_id), ctx.actor,
                               CHOICE + "returning_streams_ally_destination", list(cells[target.entity_id]), allow_decline=True,
                               labels={cell: f"Move {target.display_name} 5 feet to square ({p.x}, {p.y})" for cell, p in cells[target.entity_id].items()},
                               name="Ten Thousand Returning Streams", feature_id=STREAMS,
                               prompt=f"Return the Flow consumes {row['label']}: where does {target.display_name} move 5 feet without Opportunity Attacks? No extra Cultivation Point cost.")
                if not selected:
                    continue
                destination = position_of(selected[0])
        if not _end_effect(ctx, row):
            continue
        ended += 1
        if operation == "soak":
            # Use the shared exact turn deadline: legacy marker expiry is
            # evaluated only when typed code runs, so idle turns can retain it.
            condition_id = mark_condition_id("Soaked", ctx.actor.entity_id)
            ctx.engine._remove_condition(target, condition_id, ctx.source)
            ctx.engine._apply_condition(target, condition_id, ctx.source, ctx.actor.entity_id,
                                        expires_on=token("end", ctx.actor.entity_id, ctx.actor.turns_started + 1),
                                        data={"label": "Soaked: wet until the end of the user's next turn; enables Water talents requiring a wet target"})
        elif operation == "ally":
            step_to(ctx.engine, target, destination, ctx.source)
            ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"returning_streams_moved": target.entity_id,
                                              "turn": f"{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}",
                                              "text": f"Return the Flow: {target.display_name} moves 5 feet without Opportunity Attacks; {row['label']} ends."})
        elif operation == 'flame' and flame is not None:
            extinguish(ctx.engine, flame, ctx.source, ctx.actor)
        elif operation == 'source' and sources:
            point = next(iter(sources.values()))
            ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
                                     payload={'water_source': {'x': point.x, 'y': point.y, 'z': point.z},
                                              'text': f'Return the Flow: the nearest obvious Water Source within 60 feet is at square ({point.x}, {point.y}).'})
        else:
            ctx.rider(f"Return the Flow consumes {row['label']}. The GM resolves " + (
                "extinguishing one ordinary flame in or adjacent to it." if operation == "flame" else
                "awareness of the nearest obvious Water Source within 60 feet."))
    _heal(ctx, spec, domain, ended)


@effect("water_returning_streams")
def returning_streams(ctx: Any, spec: dict[str, Any]) -> None:
    domain = _court(ctx.engine, ctx.actor)
    if domain is None or not spec.get("end"):
        return
    available = _effects(ctx.engine, ctx.actor)
    preferred = [key for key, row in available.items() if row.get("zone") is not domain]
    # The ordinary AI selects the maximum number offered. Preserve its Court
    # when it can end other effects; players retain all three selections.
    mode = (getattr(ctx.engine, "typed_control_modes", {}) or {}).get(ctx.actor.owner_id or ctx.actor.entity_id, "MANUAL")
    maximum = 3 if mode == "MANUAL" else min(3, len(preferred)) or 1
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RETURNING_STREAMS", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "returning_streams_end", list(available), maximum=maximum,
                 preferred=preferred, default_count=min(3, len(preferred)) or 1,
                 labels={key: f"End {row['label']} now" for key, row in available.items()},
                 name="Ten Thousand Returning Streams", feature_id=STREAMS,
                 prompt=f"{ctx.actor.display_name} uses Return the Flow: End It Early. Choose up to three of your Water effects to end now. "
                        "Ending at least two lets you heal one ally inside your Court of the Endless Tide; no extra CP cost.")
    ended = 0
    for key in chosen:
        row = available.get(key)
        if not row:
            continue
        ended += int(_end_effect(ctx, row))
    _heal(ctx, spec, domain, ended)
