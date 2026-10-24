"""Heaven-Binding Chain Body: Meridian Tethers, Drag the Heavens, Thousand-Link Meridian Network and the Prison Tether (rider
lane C7, 2026-09-30: "i want everything we can automated").

Owned rows ``path_passive`` kind ``chain_tether`` with ``role``: "integration" (Chain-Body Integration: Meridian Tether),
"network" (Thousand-Link Meridian Network).

Meridian Tether   once per turn after the owner hits with a Chain weapon or an unarmed strike, 1 Stamina (asked): the target
                  makes a Strength save against the owner's Cultivation Save DC; on a failure it is Tethered
                  (``condition:typed.meridian_tether``) until the end of the owner's next turn. One Tether is kept (Proficiency
                  Bonus with the Network); a new one ends the oldest. While Tethered it cannot willingly move to a space more
                  than 20 feet from the owner (its Move squares are filtered by combat/ext/move_limits.py), and teleporting farther than that takes a
                  Cultivation Check (d20 + PB + key modifier) against the owner's DC: a failure stops the teleport. The Tether
                  ends when the owner is down or when the Tethered creature ends its turn more than 30 feet away.
Drag the Heavens  offered only against a creature the owner Tethers; its failed-save menu (pull 20 / move 20 toward it without
                  provoking / pull 10 and knock Prone / move it to a space within 20 feet) and successful-save menu (pull 5 /
                  move 5 toward it) are asked after the save (``chain_move_toward``, ``chain_rotate`` effects).
Thousand-Link     while any hostile creature is Tethered: those creatures treat the squares within the owner's reach as
                  difficult terrain (a computed zone), the owner cannot be Disarmed of a Chain weapon, and once per turn a hit
                  on a Tethered creature deals +2d8 Bludgeoning, Slashing or Force.
Prison Tether     Heaven-Binding Prison's failed save (``condition:typed.prison_tether``): the creature cannot willingly move
                  out of the prison, and it ends at the start of its turn once it is no longer Restrained by the prison.
Prison Anchor     the typed ``bound_object`` row in the prison's reviewed record makes the central Anchor (AC = the owner's
                  Cultivation Save DC, 5 x CL Hit Points, Resistance to Bludgeoning/Piercing/Slashing) at the zone's centre.
                  Destroying or suppressing it ends the prison, every Prison Tether and every Restrained condition it made.
Prison appearance each eligible unattended object in the cylinder takes one 4d8 Force packet when the prison appears.
Direction sense   at the start of the owner's turn the log names the direction of each creature it Tethers within 60 feet.
Integrated fists  Refined Iron Fist and Heavenly Fist apply through the integrated Chain Weapon: it counts as magical and
                  cultivation-powered (shared ``attack_magical`` hook), Heavenly Fist may deal Force (asked per strike), a
                  mundane disarm cannot take it, and its attacks double against an unattended object of no higher Source CL,
                  ignore that object's Resistance and treat its Damage Threshold as 0.
Every hook returns early for a creature without these rows or conditions.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .move_limits import register_tether

PREFIX = "tianxia.subpath.body.heaven_binding_chain_body.feature."
TETHER = "condition:typed.meridian_tether"
PRISON = "condition:typed.prison_tether"
STAMINA = "resource:core.stamina"
PRISON_SOURCE = PREFIX + "heaven_binding_prison"
REFINED_IRON_FIST = "tianxia.path.body_refining.feature.refined_iron_fist"
HEAVENLY_FIST = "tianxia.path.body_refining.feature.heavenly_fist"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "chain_tether"
            and str(row.get("feature_id") or "").startswith(PREFIX)}


def tethers_of(engine: Any, owner: Any) -> list[tuple[Any, Any]]:
    return sorted(((other, c) for other in engine.state.actors.values() if other.active for c in other.conditions.values()
                   if c.condition_id == TETHER and c.source_actor_id == owner.entity_id), key=lambda pair: pair[1].applied_sequence)


def _numbers(engine: Any, actor: Any) -> dict[str, int]:
    from .needle import numbers_of

    numbers = numbers_of(engine, actor)
    return {"pb": int(numbers.get("pb") or actor.proficiency_bonus or 2),
            "key_mod": int(numbers.get("key_mod") or 0),
            "save_dc": int(numbers.get("save_dc") or 8 + int(actor.proficiency_bonus or 2)),
            "cl": int(numbers.get("cl") or 1)}


# --------------------------------------------------------------------------------------------------- making a Tether
@effect("meridian_tether")
def tether(ctx: Any, row: dict[str, Any]) -> None:
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    held = tethers_of(engine, owner)
    keep = int(ctx.numbers.get("pb") or 2) if "network" in _roles(engine, owner) else 1
    for other, condition in [pair for pair in held if pair[0] is target] + held[:max(0, len(held) - keep + 1)]:
        if condition.instance_id in other.conditions:
            other.conditions.pop(condition.instance_id)
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=owner.entity_id, target_ids=(other.entity_id,),
                                 payload={"condition_id": TETHER, "instance_id": condition.instance_id, "reason": "REPLACED"})
    engine._apply_condition(target, TETHER, ctx.source, owner.entity_id, expires_on=f"END_OF_SOURCE_TURN_AT:{int(owner.turns_started) + 1}",
                            data={"label": f"Tethered to {owner.display_name}: cannot willingly move more than 20 feet from it", "max_ft": 20,
                                  "dc": int(ctx.numbers.get("save_dc") or 10),
                                  "source_cl": int(ctx.numbers.get("cl") or 1), "sense_ft": 60,
                                  "hostile_forced": 0})


@hook("after_hit")
def network_strike(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if (target is None or not target.active or "network" not in _roles(engine, actor)
            or not any(other.team_id != actor.team_id for other, _ in tethers_of(engine, actor))):
        return
    rolled = next((e.sequence for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor.entity_id), 0)
    if not any(c.condition_id == TETHER and c.source_actor_id == actor.entity_id and c.applied_sequence < rolled
               for c in target.conditions.values()):
        return  # a Tether made by this very hit does not count: it was not Tethered when hit
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if actor.turn_flags.get("_round_thousand_link") == stamp:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "thousand_link", target.entity_id), actor,
        "choice:needle.thousand_link", ["bludgeoning", "slashing", "force"], allow_decline=True,
        labels={kind: f"Add 2d8 {kind.title()} damage to the hit against {target.display_name} (once per turn)"
                for kind in ("bludgeoning", "slashing", "force")}, target_id=target.entity_id,
        prompt=f"Thousand-Link Meridian Network: {ctx.action.display_name} hit {target.display_name}; choose the rider's damage type or decline.")
    if not picked:
        return
    actor.turn_flags["_round_thousand_link"] = stamp
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [picked[0]],
                     "evidence": "Thousand-Link Meridian Network: once per turn +2d8 against a Tethered creature"}])


def _chain_or_unarmed(ctx: Any, kind: str) -> bool:
    from .integrated_weapons import in_group

    return kind == "unarmed" or in_group(ctx.typed, "chain")


@hook("after_hit")
def meridian_tether(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or "integration" not in _roles(engine, actor) or not _chain_or_unarmed(ctx, kind):
        return
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if actor.turn_flags.get("_round_meridian_tether") == stamp or actor.resources.get(STAMINA, 0) < 1:
        return
    from .needle import ask, checkpoint_id

    if not ask(engine, ctx.intent, checkpoint_id(engine, "meridian_tether", target.entity_id), actor, "choice:needle.meridian_tether", ["tether"],
               allow_decline=True, target_id=target.entity_id, labels={"tether": f"Spend 1 Stamina: {target.display_name} makes a Strength save or is Tethered"},
               prompt=f"Meridian Tether: {ctx.action.display_name} hit {target.display_name} (once per turn)."):
        return
    actor.turn_flags["_round_meridian_tether"] = stamp
    engine._spend_resource(actor, STAMINA, 1, PREFIX + "chain_body_integration")
    from .. import typed_executor as te

    nums = _numbers(engine, actor)
    sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': {**ctx.numbers, **nums}}, damage_cache={})
    sub = sub.with_source(PREFIX + "chain_body_integration")
    te.run_effects(sub, [{"type": "save", "ability": "str", "evidence": "Meridian Tether: Strength saving throw",
                          "on_fail": [{"type": "meridian_tether", "applies_to": "target"}], "on_success": []}])


# ------------------------------------------------------------------------------------------------ what a Tether does
def _bound(target: Any) -> list[Any]:
    return [c for c in target.conditions.values() if c.condition_id in (TETHER, PRISON)]


def _tether_reach(engine: Any, condition: Any, holder: Any = None) -> tuple[Any, int] | None:
    """Meridian Tether: within 20 feet (its max_ft) of its active owner (willing moves; combat/ext/move_limits.py checks them).
    ``holder`` is the tethered creature itself; the tether reads its owner, not the holder."""
    owner = engine.state.actors.get(condition.source_actor_id)
    return (owner.position, int((condition.data or {}).get("max_ft") or 20)) if owner is not None and owner.active else None


def _prison_reach(engine: Any, condition: Any, holder: Any = None) -> tuple[Any, int]:
    """Prison Tether: within the prison's radius of its centre. The prison's own zone, not the holder, decides it."""
    from ..gate2_runtime_models import Position

    center = (condition.data or {}).get("center") or {}
    return Position(x=int(center.get("x", 0)), y=int(center.get("y", 0))), int((condition.data or {}).get("radius_ft") or 30)


register_tether(TETHER, _tether_reach)
register_tether(PRISON, _prison_reach)


@hook("teleport_context_check")
def tether_teleport(engine: Any, actor: Any, start: Any, destination: Any, movement_context: str) -> bool | None:
    """Each separate active restraint contests departure, before spatial placement.

    Meridian restricts willing spatial movement; the shared producer supplies
    the actual WILLING/FORCED context. Prison bindings use their center rather
    than the caster's location. Failure leaves the paid activation on its side.
    """
    from .move_limits import tether as bound_radius

    for held in _bound(actor):
        if held.condition_id == TETHER and movement_context != "WILLING":
            continue
        owner = engine.state.actors.get(held.source_actor_id)
        radius = bound_radius(engine, held, actor)
        if owner is None or radius is None or engine.grid.distance_ft(destination, radius[0]) <= radius[1]:
            continue
        nums = _numbers(engine, actor)
        roll = engine.roll_check(modifier=nums['pb'] + nums['key_mod'], actor_id=actor.entity_id,
                                 reason=f'CHECK:{held.source_definition_id}')
        engine._record_roll(roll)
        dc = int((held.data or {}).get("dc") or _numbers(engine, owner)["save_dc"])
        engine._append_event("CHECK_ROLLED", held.source_definition_id, actor_id=actor.entity_id,
            target_ids=(owner.entity_id,), payload={"actor": roll.model_dump(mode="json"), "dc": dc,
            "success": roll.total >= dc, "skill": "Cultivation Check"})
        if roll.total < dc:
            note(engine, held.source_definition_id, actor,
                 f"{actor.display_name}'s spatial movement fails at the chain boundary; its activation and costs remain spent.")
            return False
    return None

@hook("turn_end")
def tether_ends(engine: Any, actor: Any) -> None:
    for condition in [c for c in actor.conditions.values() if c.condition_id == TETHER]:
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner is None or not owner.active or owner.life_state not in (None, "CONSCIOUS") or ((condition.data or {}).get("hostile_forced", 1) == 1
                and engine._distance_actor_to_actor(owner, actor) > 30):
            actor.conditions.pop(condition.instance_id)
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": TETHER, "instance_id": condition.instance_id, "reason": "TETHER_BROKEN"})
        elif (condition.data or {}).get("hostile_forced") == 1:
            # The end-turn check has settled this displacement inside 30 feet.
            # A later turn must establish its own hostile-displacement cause.
            engine._update_condition_data(actor, condition, {**condition.data, "hostile_forced": 0},
                                          condition.source_definition_id)


_COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")


def _direction(engine: Any, owner: Any, target: Any) -> str:
    """One of eight plain directions from ``owner`` toward ``target`` (a grid step, never an exact distance)."""
    dx = int(target.position.x) - int(owner.position.x)
    dy = int(target.position.y) - int(owner.position.y)
    if not (dx or dy):
        return "same space"
    import math

    # Compass clockwise from north: +x is east, +y is south.
    sector = int(round(math.degrees(math.atan2(dx, -dy)) / 45.0)) % 8
    return _COMPASS[sector]


@hook("turn_start")
def tether_direction_sense(engine: Any, actor: Any) -> None:
    """Meridian Tether: "You know its direction within 60 feet" -- reported on the owner's own turn, not inferred.

    Only the owner's own sense: no other actor and no creature beyond the recorded ``sense_ft`` is named. The log gives
    direction, never exact distance, and requires the same plane.
    """
    if "integration" not in _roles(engine, actor):
        return
    for target, condition in tethers_of(engine, actor):
        sense = int((condition.data or {}).get("sense_ft") or 0)
        if sense <= 0 or int(target.position.z or 0) != int(actor.position.z or 0):
            continue
        if engine._distance_actor_to_actor(actor, target) > sense:
            continue
        note(engine, condition.source_definition_id, actor,
             f"Meridian Tether: you sense {target.display_name} to the {_direction(engine, actor, target)} "
             f"(within {sense} feet).", targets=(target.entity_id,))


@hook("turn_start")
def prison_tether_ends(engine: Any, actor: Any) -> None:
    for condition in [c for c in actor.conditions.values() if c.condition_id == PRISON]:
        restrained = any(c.condition_id == "condition:typed.restrained" and c.source_definition_id == condition.source_definition_id
                         for c in actor.conditions.values())
        zone = engine.state.zones.get(str((condition.data or {}).get("zone_id") or ""))
        if not restrained or zone is None or not zone.active:
            actor.conditions.pop(condition.instance_id)
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": PRISON, "instance_id": condition.instance_id})


@effect("prison_tether")
def prison_tether(ctx: Any, row: dict[str, Any]) -> None:
    zone = next((z for z in ctx.engine.state.zones.values() if z.active and z.source_definition_id == ctx.source and z.owner_id == ctx.actor.entity_id), None)
    center = zone.center if zone is not None else (ctx.damage_cache.get("_checkpoint_aim") or ctx.actor.position)
    target = ctx.target
    if target is None or not target.active:
        return
    ctx.engine._apply_condition(target, PRISON, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Prison Tether: cannot willingly leave the Heaven-Binding Prison", "center": {"x": center.x, "y": center.y},
                                      "radius_ft": int(row.get("radius_ft") or 30), "zone_id": zone.zone_id if zone is not None else "",
                                      "dc": int(ctx.numbers.get("save_dc") or 10),
                                      "source_cl": int(ctx.numbers.get("cl") or 1)})


def _end_prison(engine: Any, zone_id: str, reason: str) -> None:
    """End one prison completely: its Restrained conditions, every Prison Tether for that zone, then the zone itself.

    Idempotent: the Anchor's destruction, its suppression and the zone's own removal all route here, and any one of them
    (a repeat save that empties the zone, the duration) must leave the others already-ended.
    """
    from .condition_ownership import remove_instance

    if not zone_id or engine.__dict__.get("_prison_ending") == zone_id:
        return
    engine.__dict__["_prison_ending"] = zone_id
    try:
        for actor in list(engine.state.actors.values()):
            for condition in list(actor.conditions.values()):
                if condition.condition_id != PRISON or str((condition.data or {}).get("zone_id") or "") != zone_id:
                    continue
                for held in [c for c in actor.conditions.values()
                             if c.condition_id == "condition:typed.restrained"
                             and c.source_definition_id == condition.source_definition_id]:
                    remove_instance(engine, actor, held.instance_id, held.source_definition_id)
                remove_instance(engine, actor, condition.instance_id, condition.source_definition_id)
        zone = engine.state.zones.get(zone_id)
        if zone is not None and zone.active:
            from .. import zones

            zones.remove(engine, zone, reason)
    finally:
        engine.__dict__.pop("_prison_ending", None)


@hook("state_event")
def prison_anchor_events(engine: Any, event: Any) -> None:
    """The prison ends when its central Anchor is destroyed or suppressed, and when the zone itself ends."""
    if event.event_type == "ZONE_REMOVED" and str(event.source_definition_id or "").endswith(PRISON_SOURCE):
        _end_prison(engine, str((event.payload or {}).get("zone_id") or ""), "PRISON_ENDED")
        return
    if event.event_type != "OBJECT_UPDATED":
        return
    obj = (event.payload or {}).get("object") or {}
    record = ((obj.get("component") or {}).get("bound") or {})
    if not str(record.get("source") or "").endswith(PRISON_SOURCE) or not (obj.get("destroyed") or obj.get("suppressed")):
        return
    reason = "ANCHOR_SUPPRESSED" if obj.get("suppressed") and not obj.get("destroyed") else "ANCHOR_DESTROYED"
    for zone_id in record.get("zones") or []:
        _end_prison(engine, str(zone_id), reason)


@hook("zone_created")
def prison_appearance_damage(ctx: Any, zone: Any) -> None:
    """Printed creature clause: each eligible unattended object in the cylinder takes one 4d8 Force packet on appearance.

    Creatures and permanent world terrain are not objects on the battlefield (a wall is map geometry, not an object), so
    the same unattended-object record the table's object rules use is the whole eligible set. The Anchor itself is made by
    the later ``bound_object`` row, so it cannot damage itself here.
    """
    if not str(ctx.source or "").endswith(PRISON_SOURCE):
        return
    engine = ctx.engine
    cells = {(cell.x, cell.y) for cell in zone.affected_cells or ()}
    objects = [obj for obj in sorted(engine.state.objects.values(), key=lambda row: row.object_id)
               if not obj.destroyed and obj.ac is not None and obj.current_hp is not None and obj.unattended
               and (obj.position.x, obj.position.y) in cells]
    if not objects:
        return
    from ..gate2_runtime_models import DiceSpec
    from .objects import deal

    for obj in objects:
        rolled = engine.roller.roll(DiceSpec(count=4, sides=8, modifier=0), actor_id=ctx.actor.entity_id,
                                    reason=f"DAMAGE:{ctx.source}:object", critical=False)
        engine._record_roll(rolled)
        deal(engine, ctx.actor, obj, [(int(rolled.total), "FORCE")], ctx.source)


# ------------------------------------------------------------------------------------------------ Drag the Heavens
@hook("candidate_allowed")
def drag_targets(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if typed.get("source") != PREFIX + "drag_the_heavens":
        return None
    tethered = {other.entity_id for other, _c in tethers_of(engine, actor)}
    return None if candidate.target_ids and set(candidate.target_ids) <= tethered else False


def _toward(engine: Any, mover: Any, anchor: Any, feet: int) -> list[Any] | None:
    from .rider_movement import routes

    closer = [path for path in routes(engine, mover, feet).values()
              if engine.grid.distance_ft(path[-1], anchor.position) < engine.grid.distance_ft(mover.position, anchor.position)]
    return min(closer, key=lambda path: (engine.grid.distance_ft(path[-1], anchor.position), len(path), path[-1].y, path[-1].x)) if closer else None


@effect("chain_move_toward")
def move_toward(ctx: Any, row: dict[str, Any]) -> None:
    """Move yourself up to ``distance_ft`` toward the target without provoking."""
    from .rider_movement import step

    if ctx.target is None:
        return
    path = _toward(ctx.engine, ctx.actor, ctx.target, int(row.get("distance_ft") or 5))
    if path:
        step(ctx.engine, ctx.actor, path, ctx.source)


@effect("chain_rotate")
def rotate(ctx: Any, row: dict[str, Any]) -> None:
    """Move the target to another unoccupied space within 20 feet of you (a forced route, asked)."""
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import forced_route

    engine, target = ctx.engine, ctx.target
    if target is None or not target.active:
        return
    found = engine.grid.reachable(target.position, movement_ft=int(row.get("distance_ft") or 20), occupied_cells=engine._occupied_cells_except(target.entity_id),
                                  difficult_cells=set(), footprint=engine._footprint(target))
    options = {cell_id(cell): path for cell, (path, _cost) in found.items()
               if cell != target.position and engine.grid.distance_ft(cell, ctx.actor.position) <= int(row.get("distance_ft") or 20)}
    if not options:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "chain_rotate", target.entity_id), ctx.actor, "choice:needle.chain_rotate", sorted(options),
                 labels={k: "Move it to " + k.removeprefix("cell:") for k in options}, target_id=target.entity_id,
                 prompt=f"Drag the Heavens: choose where {target.display_name} is swung (within 20 feet of you).")
    if picked:
        path = options[picked[0]]
        forced_route(engine, target, path, ctx.source, ctx.actor)
        # "Rotation interrupted by a new obstruction still needs its collision resolved": a legal route chosen before
        # the move can be blocked by something that moved into it. A shorter route caused by a reaction's own distance
        # reduction is not an obstruction (the step it would take is still legal).
        reached = next((index for index, cell in enumerate(path) if cell == target.position), None)
        if target.active and reached is not None and reached + 1 < len(path):
            blocked_at = path[reached + 1]
            if not engine.grid.step_legal(path[reached], blocked_at,
                                          occupied_cells=engine._occupied_cells_except(target.entity_id),
                                          footprint=engine._footprint(target)):
                _resolve_collision(ctx, target, blocked_at)


# ------------------------------------------------------------------------------------------ Thousand-Link Network
@hook("zones")
def tether_ground(engine: Any) -> list[Any]:
    from ..gate2_runtime_models import ZoneState

    out = []
    for owner in engine.state.actors.values():
        if not owner.active or "network" not in _roles(engine, owner):
            continue
        tethered = [other.entity_id for other, _c in tethers_of(engine, owner) if other.team_id != owner.team_id]
        if not tethered:
            continue
        reach = chain_reach(engine, owner)
        if reach is None:
            continue
        cells = tuple(cell for cell in _cells_near(engine, owner, reach))
        out.append(ZoneState(zone_id=f"zone:derived:thousand_link:{owner.entity_id}", source_definition_id=PREFIX + "thousand_link_meridian_network",
                             owner_id=owner.entity_id, center=owner.position, radius_cells=reach // engine.grid.square_size_ft, affected_cells=cells,
                             concentration_link=False, duration_rounds=None, created_round=engine.state.round_number,
                             trigger_profile={"kind": "TYPED", "name": "Thousand-Link Meridian Network", "difficult": "all",
                                              "difficult_target_ids": tethered, "triggers": [], "inside": [], "follows_owner": True,
                                              "visual": {"material": "chains"}}))
    return out


def _cells_near(engine: Any, owner: Any, reach: int) -> list[Any]:
    from ..gate2_runtime_models import Position

    span = reach // engine.grid.square_size_ft + 1
    out = []
    for y in range(max(0, owner.position.y - span), min(engine.grid.height, owner.position.y + span + 1)):
        for x in range(max(0, owner.position.x - span), min(engine.grid.width, owner.position.x + span + 1)):
            cell = Position(x=x, y=y)
            if cell != owner.position and engine._distance_actor_to_cell(owner, cell) <= reach:
                out.append(cell)
    return out


@hook("effect_subject_allowed")
def no_disarm(ctx: Any, eff: dict[str, Any], subject: Any) -> bool | None:
    """"You cannot be Disarmed of a Chain Weapon by an ordinary effect."

    Thousand-Link Network grants it while a hostile creature is Tethered; Heavenly Fist grants it to the integrated Chain
    Weapon through its own weapon clause. Both only protect an ordinary disarm of the Chain Weapon actually wielded.
    """
    if subject is None:
        return None
    disarms = any(isinstance(r, dict) and (r.get("type") == "drop_item" or r.get("condition") == "disarmed") for r in (eff or {}).get("on_fail") or [])
    if not disarms:
        return None
    from ..typed_executor import _best_weapon_action
    from .integrated_weapons import in_group

    weapon = ctx.engine.action_catalog.get(_best_weapon_action(ctx.engine, subject) or "")
    typed = (weapon.parameters or {}).get("typed") or {} if weapon is not None else {}
    if weapon is None or not in_group(typed, "chain"):
        return None
    if "network" in _roles(ctx.engine, subject) and tethers_of(ctx.engine, subject):
        return False
    return False if typed.get("heavenly_fist_integrated") else None

def _remove_tether(engine: Any, holder: Any, condition: Any, reason: str) -> None:
    from .condition_ownership import remove_instance

    remove_instance(engine, holder, condition.instance_id, condition.source_definition_id)
    note(engine, condition.source_definition_id, condition.source_actor_id,
         f"The Meridian Tether on {holder.display_name} ends: {reason}.", targets=(holder.entity_id,))


@hook("state_event")
def tether_source_events(engine: Any, event: Any) -> None:
    """Observe actual forced movement and incapacity, never a client trigger flag."""
    event_type = event.event_type
    if event_type not in {"MOVEMENT_COMMITTED", "CONDITION_APPLIED", "DAMAGE_COMMITTED", "LIFE_STATE_CHANGED", "ENTITY_DEFEATED"}:
        return
    kwargs = {"actor_id": event.actor_id, "source_definition_id": event.source_definition_id, "payload": event.payload}
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id"))
    path = payload.get("path") or []
    if event_type == "MOVEMENT_COMMITTED" and mover is not None and len(path) > 1 and path[0] != path[-1]:
        source = engine.action_catalog.get(kwargs.get("source_definition_id"))
        source_actor = engine.state.actors.get(payload.get("source_actor_id"))
        if source_actor is None:
            source_actor = engine.state.actors.get(getattr(source, "owner_id", None))
        for condition in list(mover.conditions.values()):
            if condition.condition_id != TETHER or type(condition.data.get("source_cl")) is not int:
                continue
            owner = engine.state.actors.get(condition.source_actor_id)
            hostile = int(bool(condition.data.get("hostile_forced") or (payload.get("forced") and source_actor is not None
                and source_actor.team_id != mover.team_id and owner is not None
                and engine._distance_actor_to_actor(owner, mover) > 30)))
            if condition.data.get("hostile_forced", 0) == hostile:
                continue
            engine._update_condition_data(mover, condition, {**condition.data, "hostile_forced": hostile},
                                          condition.source_definition_id)
    for holder in engine.state.actors.values():
        for condition in list(holder.conditions.values()):
            if condition.condition_id != TETHER or type(condition.data.get("source_cl")) is not int:
                continue
            owner = engine.state.actors.get(condition.source_actor_id)
            unconscious = owner is not None and any(c.condition_id in {
                "condition:typed.unconscious", "condition:core.unconscious"} for c in owner.conditions.values())
            if owner is None or not owner.active or owner.life_state not in (None, "CONSCIOUS") or unconscious:
                _remove_tether(engine, holder, condition, "its source is unconscious or gone")


@hook("compile_actions")
def release_actions(info: dict[str, Any]) -> list[Any] | None:
    """Source-owned, no-action release is available to manual owners and AI."""
    if PREFIX + "chain_body_integration" not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.release_meridian_tether",
        display_name="End one Meridian Tether (no action or cost)", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"source": PREFIX + "chain_body_integration", "numbers": info["numbers"],
            "effects": [{"type": "chain_release"}], "duration": {"kind": "instant"}},
            "chain_release": True, "expected_damage": 0})]


@hook("ai_score_components")
def release_score(context: Any, candidate: Any, option_ids: tuple[str, ...]) -> tuple[Any, ...] | None:
    """Keep release reachable; the automatic policy conservatively keeps bindings.

    There is no intrinsic combat benefit to ending one's restraint. A human or
    model pilot may still choose it for a specific plan; the deterministic AI
    must not discard a useful binding just because this is a free action. This
    uses only the acting creature's own action identity, never hidden targets.
    """
    if not str(candidate.source_definition_id).endswith(".release_meridian_tether"):
        return None
    from ..gate4_models import ComponentScore

    return (ComponentScore(component="keep_meridian_tether", value=-1000,
        explanation="Keep your Meridian Tether unless your plan calls for releasing it."),)


@hook("candidate_allowed")
def release_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.parameters.get("chain_release") and not tethers_of(engine, actor):
        return False
    return None


@effect("chain_release")
def release(ctx: Any, row: dict[str, Any]) -> None:
    if "integration" not in _roles(ctx.engine, ctx.actor):
        return
    from .needle import ask, checkpoint_id

    held = tethers_of(ctx.engine, ctx.actor)
    options = {c.instance_id: (target, c) for target, c in held}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "release_tether"), ctx.actor,
        "choice:needle.release_tether", list(options), allow_decline=True,
        labels={iid: f"End your Tether on {target.display_name}" for iid, (target, _) in options.items()},
        prompt="Meridian Tether: choose one of your bindings to end without an action or cost.")
    if picked:
        target, condition = options[picked[0]]
        _remove_tether(ctx.engine, target, condition, "willingly released by its source")


def chain_reach(engine: Any, owner: Any) -> int | None:
    """Current wielded chain reach, without requiring an available Reaction.

    Base possession/grip queries are public; turn-only bonuses never enlarge
    threatened space later. No chain in the owner's hands means no chain reach.
    """
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed
    from .integrated_weapons import in_group

    from ..attack_reach import maximum

    chains = [a for a in available_weapons(engine, owner).values()
        if in_group(a.parameters.get("typed") or {}, "chain") and not (a.parameters.get("typed") or {}).get("range_ft")
        and weapon_allowed(engine, owner, a) is not False]
    if not chains:
        return None
    own_turn = engine.state.current_actor_id == owner.entity_id
    # Condition-bound reach (attack_reach_bonus, e.g. Adamant Guardian) applies at any time; turn-only reach
    # applies only on the owner's own turn, never to an out-of-turn Opportunity Attack or threatened space.
    reach = max(maximum(engine, owner, a, base=int(a.reach_ft or 5), opportunity=not own_turn) for a in chains)
    if own_turn:
        roles = _roles(engine, owner)
        reach += 10 if "network" in roles else 5 if "integration" in roles else 0
    return reach


# ------------------------------------------------------------------- Refined Iron Fist / Heavenly Fist on the integrated chain
def _stamped(typed: dict[str, Any]) -> bool:
    """Whether this attack carries the compile-time mark this Subpath's integrated Chain Weapon received."""
    return bool((typed or {}).get("refined_iron_fist_integrated") or (typed or {}).get("heavenly_fist_integrated"))


@hook("maneuvers")
def heavenly_fist_force_choice(info: dict[str, Any]) -> None:
    """Refined Iron Fist and Heavenly Fist applied to this Subpath's integrated Chain Weapon.

    Compile-time ownership is the only reliable record of a passive path feature (it has no runtime row or action), so this
    stamps the owning character's Chain attacks and object attacks with two default-absent keys the runtime hooks read:
    ``refined_iron_fist_integrated`` (counts as magical/cultivation-powered) and ``heavenly_fist_integrated`` (Force option,
    disarm protection, the object clause). No other weapon or character is touched; a fight that lacks the keys is inert.

    Heavenly Fist's "may deal Force damage instead of their normal damage type" is added to the weapon's own damage list so
    the shared per-strike choice can offer it (combat/typed_executor.attack_damage_type_choice); the base type stays first,
    so declining costs nothing.
    """
    owned = set(info.get("owned") or info.get("owned_ids") or ())
    if PREFIX + "chain_body_integration" not in owned:
        return
    refined = REFINED_IRON_FIST in owned
    heavenly = HEAVENLY_FIST in owned
    if not (refined or heavenly):
        return
    from .integrated_weapons import in_group

    for action in info.get("actions") or []:
        parameters = getattr(action, "parameters", None) or {}
        typed = parameters.get("typed") or {}
        weapon = typed.get("weapon")
        object_source = typed.get("object_weapon_source")
        chain = (bool(weapon) and in_group(typed, "chain")) or (
            object_source is not None and in_group({"weapon": typed.get("object_weapon") or {}, "source": object_source}, "chain"))
        if not chain:
            continue
        if weapon and not any(isinstance(effect, dict) and effect.get("type") == "attack" for effect in typed.get("effects") or []):
            continue
        if refined:
            typed["refined_iron_fist_integrated"] = True
        if not heavenly:
            continue
        typed["heavenly_fist_integrated"] = True
        if not weapon:
            continue
        kinds = [str(kind).upper() for kind in weapon.get("damage_types") or [weapon.get("damage_type") or "BLUDGEONING"]]
        if "FORCE" not in kinds:
            typed["weapon"] = {**weapon, "damage_types": [*(weapon.get("damage_types") or [weapon.get("damage_type") or "BLUDGEONING"]),
                                                         "FORCE"]}


@hook("attack_magical")
def chain_body_magical(engine: Any, source_actor_id: str, typed: dict[str, Any]) -> bool | None:
    """Refined Iron Fist (CL5) and Heavenly Fist (CL17): the integrated Chain Weapon counts as magical/cultivation-powered.

    The shared defence reader (combat/typed_reactions._counts_as_mundane) asks this before applying a defence printed only
    against nonmagical attacks. Only the weapon stamped by ``maneuvers`` above answers; every other attack is untouched.
    """
    return True if _stamped(typed or {}) else None


@hook("attack_damage_type_choice")
def heavenly_fist_strike_type(ctx: Any, attack: dict[str, Any], target: Any, kinds: list[str], attack_index: int) -> str | None:
    """Heavenly Fist's Force replacement, asked of a player (AI takes the same pick the table would) for each chain strike."""
    engine, actor = ctx.engine, ctx.actor
    typed = ctx.typed or {}
    if target is None or "FORCE" not in {str(kind).upper() for kind in kinds} or len(kinds) < 2:
        return None
    if not typed.get("heavenly_fist_integrated"):
        return None
    from ..typed_executor import choose_damage_type
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    best = choose_damage_type(ctx, list(kinds), [target])
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "heavenly_fist_type", actor.entity_id, target.entity_id, attack_index),
                 actor, CHOICE + "heavenly_fist_type", list(kinds),
                 labels={kind: f"{str(kind).title()} damage" for kind in kinds}, preferred=[best],
                 target_id=target.entity_id, name="Heavenly Fist", feature_id=HEAVENLY_FIST,
                 prompt=f"Heavenly Fist: choose the damage type of your {ctx.action.display_name} against {target.display_name}. "
                        f"Force replaces the weapon's normal type; the dice and bonus do not change.",
                 prompt_context=action_context(engine, actor, ctx.source, target))
    return picked[0] if picked else None


@hook("object_damage_profile")
def heavenly_fist_object_damage(engine: Any, actor: Any, obj: Any, packets: Any, source: str) -> dict[str, Any] | None:
    """Heavenly Fist against an unattended object of no higher Source CL: double damage, no B/P/S/Force Resistance, no
    Damage Threshold. Only this Subpath's integrated Chain Weapon attacks qualify.

    An object with no recorded Source CL is an ordinary object (Source CL 0); an explicit higher one is resolved normally.
    Artifact, Immortal, Void and permanent-terrain protections are never bypassed, as the printed exclusion says.
    """
    if actor is None or obj is None or not obj.unattended:
        return None
    action = engine.action_catalog.get(str(source or ""))
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    weapon = typed.get("object_weapon") or typed.get("weapon")
    if not weapon or not typed.get("heavenly_fist_integrated"):
        return None
    from .integrated_weapons import in_group

    if not in_group({"weapon": weapon, "source": typed.get("object_weapon_source") or typed.get("source")}, "chain"):
        return None
    component = obj.component or {}
    if any(component.get(key) for key in ("artifact", "immortal", "void", "permanent", "world_scale")):
        return None
    if int(component.get("source_cl") or 0) > _numbers(engine, actor)["cl"]:
        return None
    return {"multiplier": 2, "ignore_threshold": True, "ignore_resistance": True}


@hook("movement_attempt")
def network_opportunity(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> None:
    """The actual willing step, not expanding reach or a forced/spatial route."""
    from .. import typed_reactions as reactions
    from .. import stealth

    if int(engine.grid.distance_ft(previous, nxt)) < 5:
        return
    for owner in engine.state.actors.values():
        if owner is mover or not owner.active or "network" not in _roles(engine, owner):
            continue
        held = tethers_of(engine, owner)
        if not any(target is mover for target, _ in held) or not any(
                target.team_id != owner.team_id for target, _ in held):
            continue
        reach = chain_reach(engine, owner)
        if reach is None or engine._distance_actor_to_actor(owner, mover) > reach or not stealth.sees(engine, owner, mover):
            continue
        row = reactions.opportunity_reaction_row(engine, owner)
        profile_row, profile, profile_reach = reactions.opportunity_profile(engine, owner)
        # Shared current OA reach: the compiled profile plus condition-bound bonuses, independent of Reaction availability.
        attack_reach = reactions.physical_melee_reach(engine, owner)
        if attack_reach is None:
            attack_reach = profile_reach
        if (profile_row is None or profile is None
                or engine._distance_actor_to_actor(owner, mover) > attack_reach
                or not reactions.can_use_reaction(engine, owner, mover, row)):
            continue
        # Only the movement trigger is overridden. OA prohibitions, protection
        # responses, the saved reaction plan and Ask-me consent remain shared.
        if reactions.wants_opportunity_attack(engine, owner, mover, consent_display={
                "display_name": "Thousand-Link Meridian Network",
                "display_trigger": f"{mover.display_name} willingly moves within your chain reach",
                "display_summary": f"Make one Opportunity Attack against {mover.display_name}.",
                "display_cost": "Your normal Reaction", "display_uses_reaction": True}):
            reactions.spend_reaction(engine, owner, row)
            reactions.opportunity_attack(engine, owner, mover, intent, trigger="movement")
    return None


def _resolve_collision(ctx: Any, target: Any, blocked_at: Any) -> None:
    """One collision packet for a forced route that stopped at a real obstruction.

    The moved creature and a damageable surface take Bludgeoning damage equal to the owner's Proficiency Bonus; a second
    creature makes one Dexterity save and takes the same on a failure. Undefined/permanent world terrain is not a surface.
    One packet per affected creature per activation, shared by the pull and the interrupted rotation.
    """
    from ..object_geometry import target_cells
    from .. import typed_executor as te
    from .objects import deal

    engine = ctx.engine
    key = "chain_collision:" + target.entity_id
    if ctx.damage_cache.get(key):
        return
    volume = set(engine._actor_volume(target, position=blocked_at))
    creatures = sorted((other for other in engine.state.actors.values() if other.active and other is not target
        and engine._on_battlefield(other)
        and not engine._shared_occupancy_pair(target.entity_id, other.entity_id)
        and volume.intersection(engine._actor_volume(other))), key=lambda a: a.entity_id)
    objects = sorted((obj for obj in engine.state.objects.values() if not obj.destroyed and obj.current_hp is not None
        and (obj.component or {}).get("blocks") is True
        and any((cell.x, cell.y, cell.z) in volume for cell in target_cells(engine, obj))), key=lambda obj: obj.object_id)
    if not creatures and not objects:
        return  # Undefined/permanent world terrain is not a damageable surface.
    ctx.damage_cache[key] = 1
    amount = int(ctx.numbers.get("pb") or ctx.actor.proficiency_bonus)
    child = ctx.on_hit_context(target, damage_cache={}, critical_hit=False).with_source(PREFIX + "drag_the_heavens")
    te.run_effects(child, [{"type": "damage", "applies_to": "target", "flat": amount, "damage_types": ["bludgeoning"]}])
    if creatures:
        other = creatures[0]
        te.run_effects(ctx.on_hit_context(other, damage_cache={}, critical_hit=False,
            explicit_self_recipient=other is ctx.actor), [{"type": "save", "ability": "dex",
            "on_fail": [{"type": "damage", "applies_to": "target", "flat": amount, "damage_types": ["bludgeoning"]}],
            "on_success": []}])
    elif objects:
        deal(engine, ctx.actor, objects[0], [(amount, "BLUDGEONING")], ctx.source)


@hook("forced_movement_collision")
def drag_collision(ctx: Any, target: Any, blocked_at: Any, untraveled_ft: int) -> None:
    """One actual blocked pull; mere adjacency and reaction-shortened routes are inert."""
    from .ability_source import mechanic_of
    if mechanic_of(ctx.action) != PREFIX + "drag_the_heavens" or untraveled_ft <= 0:
        return
    _resolve_collision(ctx, target, blocked_at)


@hook("movement_source_requested")
def tether_movement_source(engine: Any, mover: Any, source: str) -> bool | None:
    """Only new native Meridian records request a real forced-movement causer."""
    return True if any(c.condition_id == TETHER and type(c.data.get("source_cl")) is int
                       for c in mover.conditions.values()) else None
