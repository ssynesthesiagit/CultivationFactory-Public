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


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "chain_tether"}


def tethers_of(engine: Any, owner: Any) -> list[tuple[Any, Any]]:
    return sorted(((other, c) for other in engine.state.actors.values() if other.active for c in other.conditions.values()
                   if c.condition_id == TETHER and c.source_actor_id == owner.entity_id), key=lambda pair: pair[1].applied_sequence)


def _numbers(engine: Any, actor: Any) -> dict[str, int]:
    numbers = next((((a.parameters or {}).get("typed") or {}).get("numbers") or {} for a in engine.action_catalog.values()
                    if a.owner_id == actor.entity_id and ((a.parameters or {}).get("typed") or {}).get("numbers")), {})
    return {"pb": int(numbers.get("pb") or actor.proficiency_bonus or 2), "key_mod": int(numbers.get("key_mod") or 0),
            "save_dc": int(numbers.get("save_dc") or 8 + int(actor.proficiency_bonus or 2)), "cl": int(numbers.get("cl") or 1)}


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
                                  "dc": int(ctx.numbers.get("save_dc") or 10)})


@hook("after_hit")
def network_strike(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or "network" not in _roles(engine, actor):
        return
    rolled = next((e.sequence for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor.entity_id), 0)
    if not any(c.condition_id == TETHER and c.source_actor_id == actor.entity_id and c.applied_sequence < rolled
               for c in target.conditions.values()):
        return  # a Tether made by this very hit does not count: it was not Tethered when hit
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if actor.turn_flags.get("_round_thousand_link") == stamp:
        return
    actor.turn_flags["_round_thousand_link"] = stamp
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["bludgeoning", "slashing", "force"],
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


@hook("teleport_check")
def tether_teleport(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    held = next((c for c in _bound(actor) if c.condition_id == TETHER), None)
    owner = engine.state.actors.get(held.source_actor_id) if held is not None else None
    if owner is None or not owner.active or engine.grid.distance_ft(destination, owner.position) <= 20:
        return None
    nums = _numbers(engine, actor)
    roll = engine.roll_check(
        modifier=nums['pb'] + nums['key_mod'],
        actor_id=actor.entity_id,
        reason=f'CHECK:{held.source_definition_id}',
    )
    engine._record_roll(roll)
    dc = int((held.data or {}).get("dc") or 10)
    engine._append_event("CHECK_ROLLED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(owner.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc, "skill": "Cultivation Check"})
    if roll.total >= dc:
        return None
    note(engine, held.source_definition_id, actor, f"Meridian Tether: {actor.display_name}'s teleport beyond 20 feet of {owner.display_name} fails.")
    return False


@hook("turn_end")
def tether_ends(engine: Any, actor: Any) -> None:
    for condition in [c for c in actor.conditions.values() if c.condition_id == TETHER]:
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner is None or not owner.active or owner.life_state is not None or engine._distance_actor_to_actor(owner, actor) > 30:
            actor.conditions.pop(condition.instance_id)
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": TETHER, "instance_id": condition.instance_id, "reason": "TETHER_BROKEN"})


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
                                      "radius_ft": int(row.get("radius_ft") or 30), "zone_id": zone.zone_id if zone is not None else ""})


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
        forced_route(engine, target, options[picked[0]], ctx.source, ctx.actor)


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
        from ..typed_reactions import opportunity_reach

        reach = int(opportunity_reach(engine, owner) or 5)
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
    """"You cannot be Disarmed of a Chain Weapon by an ordinary effect" while a hostile creature is Tethered."""
    if subject is None or "network" not in _roles(ctx.engine, subject) or not tethers_of(ctx.engine, subject):
        return None
    disarms = any(isinstance(r, dict) and (r.get("type") == "drop_item" or r.get("condition") == "disarmed") for r in (eff or {}).get("on_fail") or [])
    if not disarms:
        return None
    from ..typed_executor import _best_weapon_action
    from .integrated_weapons import in_group

    weapon = ctx.engine.action_catalog.get(_best_weapon_action(ctx.engine, subject) or "")
    return False if weapon is not None and in_group((weapon.parameters or {}).get("typed") or {}, "chain") else None
