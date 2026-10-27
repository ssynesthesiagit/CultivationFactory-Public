"""Public test documentation omitted."""

from __future__ import annotations

from ..paid_relocation import activation

import copy
from typing import Any, Sequence

from . import effect, hook
from .placed import notice, note
from ..speed_contributions import effective_speed

MOUNTED = "condition:typed.mounted"  # on the rider; source_actor_id is the mount
CARRYING = "condition:typed.carrying"  # on the mount; source_actor_id is the rider
PRONE = "condition:typed.prone"
RHYTHM = "condition:typed.battle_rhythm"  # One Rider, One Beast: on the rider and on its beast; source_actor_id is the other one
SRC = "system:combat.mounts"
BLOCK = "mounts"
FOCUS = "resource:core.martial_focus"
DC_TO_STAY = 10  # 5.5e: DC 10 Dexterity saving throw to stay in the saddle

RIDER_PACKAGE = "BEASTMASTERY_BASE_RIDER_PACKAGE"
MOUNT_TRAINING = "tianxia.talent.beastmastery.mount_training"
ONE_RIDER = "TAL_BEASTMASTERY_ONE_RIDER_ONE_BEAST"
BEASTBACK = "TAL_BEASTMASTERY_BEASTBACK_RELAY"
GREAT_CHARGE = "TAL_BEASTMASTERY_GREAT_BEAST_CHARGE"
IGNORE_DIFFICULT = "condition:typed.ignore_difficult"


# ------------------------------------------------------------------------------------------------ who is riding whom
def _condition(actor: Any, condition_id: str) -> Any | None:
    return next((row for row in actor.conditions.values() if row.condition_id == condition_id), None)


def mount_of(engine: Any, rider: Any) -> Any | None:
    """The mount this creature is riding, when both halves of the bond are in place and the mount is on the map."""
    held = _condition(rider, MOUNTED)
    if held is None:
        return None
    mount = engine.state.actors.get(held.source_actor_id)
    if mount is None or not mount.active or not rider.active:
        return None
    back = _condition(mount, CARRYING)
    return mount if back is not None and back.source_actor_id == rider.entity_id else None


def rider_of(engine: Any, mount: Any) -> Any | None:
    held = _condition(mount, CARRYING)
    if held is None:
        return None
    rider = engine.state.actors.get(held.source_actor_id)
    if rider is None or not rider.active or not mount.active:
        return None
    back = _condition(rider, MOUNTED)
    return rider if back is not None and back.source_actor_id == mount.entity_id else None


def _mount_movement_spent(rider: Any, mount: Any) -> int:
    """Movement already spent with this controlled mount during the rider's current turn."""
    return max(0, int(rider.turn_flags.get(f"mount_movement_spent_ft:{mount.entity_id}") or 0))


def _spend_mount_movement(rider: Any, mount: Any, distance_ft: int) -> None:
    if distance_ft > 0:
        key = f"mount_movement_spent_ft:{mount.entity_id}"
        rider.turn_flags[key] = _mount_movement_spent(rider, mount) + int(distance_ft)


@hook('turn_movement_allowance')
def mounted_allowance(engine: Any, actor: Any, speed: int) -> int | None:
    """The controlled mount supplies the pool even during base-engine genesis."""
    mount = mount_of(engine, actor)
    if mount is None or not controlled(mount) or speed <= 0:
        return None
    # Use Gate4's complete effective Speed: mounted_speed replaces the rider's
    # base Speed, then all rider bonuses and reductions are composed around it.
    # Rebuilding that value from base speeds drops those contributions.
    feet = max(0, int(effective_speed(engine, actor)))
    actor.turn_flags[f"mount_movement_speed_ft:{mount.entity_id}"] = feet
    return feet


@hook('technique_used')
def mounted_speed_changed(ctx: Any) -> None:
    """Apply a rider's own technique's Speed change to the unspent mounted pool.

    Speed changes replace part of the initial allowance; they are not extra
    movement grants in the ledger. Keep movement already spent and Dash grants.
    Immobilization/restoration remains owned by movement_budget.
    """
    engine, actor = ctx.engine, ctx.actor
    mount = mount_of(engine, actor)
    if mount is None or not controlled(mount) or engine.state.current_actor_id != actor.entity_id:
        return
    key = f"mount_movement_speed_ft:{mount.entity_id}"
    speed = max(0, int(effective_speed(engine, actor)))
    previous = int(actor.turn_flags.get(key, speed))
    if speed <= 0 or previous <= 0 or speed == previous:
        return
    actor.turn_flags[key] = speed
    _grant(engine, actor, speed - previous, ctx.source, replacement=True)


@hook('ordinary_movement_limit')
def mounted_remaining(engine: Any, actor: Any) -> int | None:
    """Bound steering by this mount's spent ledger plus explicit extra grants.

    Restoration and replacing the pool on remount are not extra allowances.
    Dash and printed movement grants remain legal. Independent granted paths
    validate their own pool outside this ordinary-movement query.
    """
    mount = mount_of(engine, actor)
    if mount is None or not controlled(mount):
        return None
    mounted_speed_ft = max(0, int(effective_speed(engine, actor)))
    extra = 0
    for event in reversed(engine.events):
        if event.event_type == 'TURN_STARTED' and event.actor_id == actor.entity_id:
            break
        if event.actor_id != actor.entity_id:
            continue
        if event.event_type == 'MOVEMENT_GRANTED' and not event.payload.get('allowance_replaced'):
            extra += max(0, int(event.payload.get('distance_ft') or 0))
        elif event.event_type == 'INTENT_ACCEPTED':
            action = engine.action_catalog.get(event.source_definition_id)
            if action is not None and action.resolution_kind == 'DASH':
                extra += mounted_speed_ft
    return max(0, mounted_speed_ft + extra - _mount_movement_spent(actor, mount))


def controlled(mount: Any) -> bool:
    """5.5e: a trained mount is a Controlled Mount, any other an Independent one."""
    return bool((mount.summon or {}).get("trained"))


def _rows(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("kind")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK}


def _cells(engine: Any, actor: Any) -> set[tuple[int, int]]:
    return set(engine._actor_cells(actor))


def _say(engine: Any, actor: Any, text: str) -> None:
    note(engine, SRC, actor, text)


def _walk_speed(engine: Any, actor: Any) -> int:
    """The creature's own Speed, ignoring any mount it rides."""
    from ..gate2_engine import Gate2Engine

    return int(Gate2Engine._effective_speed(engine, actor))


def _cost(engine: Any, rider: Any) -> int:
    return _walk_speed(engine, rider) // 2  # 5.5e: half your Speed, rounded down


def turn_passes(engine: Any, mount: Any) -> bool:
    """A Controlled Mount takes no turn of its own while it carries its rider (the rider directs it: combat/summons.py)."""
    return rider_of(engine, mount) is not None and controlled(mount)


# ------------------------------------------------------------------------------------------------ shared space
@hook("shared_occupancy")
def shared_space(engine: Any, left: Any, right: Any) -> dict[str, str] | None:
    for rider, mount in ((left, right), (right, left)):
        if mount_of(engine, rider) is mount and rider_of(engine, mount) is rider:
            return {"rider_id": rider.entity_id, "mount_id": mount.entity_id}
    return None


# ------------------------------------------------------------------------------------------------ binding
def bind(engine: Any, rider: Any, mount: Any, *, why: str = "") -> None:
    engine._apply_condition(rider, MOUNTED, SRC, mount.entity_id, expires_on="UNTIL_REMOVED",
                            data={"mount": mount.entity_id, "label": f"Mounted on {mount.display_name}"})
    engine._apply_condition(mount, CARRYING, SRC, rider.entity_id, expires_on="UNTIL_REMOVED",
                            data={"rider": rider.entity_id, "label": f"Carrying {rider.display_name}"})
    _say(engine, rider, why or f"{rider.display_name} rides {mount.display_name}.")


def start_bond(rider: Any, mount: Any) -> None:
    """The rider starts the fight in the saddle. Written straight into the two creatures before the match exists
    (combat/summons.py add_to_match): the fight is created by the base engine, whose events run no plug-in, and the saved
    starting state carries the bond, so a saved fight and its replay start the same way."""
    from ..gate2_runtime_models import ConditionInstance

    for target, condition_id, source, data in (
            (rider, MOUNTED, mount, {"mount": mount.entity_id, "label": f"Mounted on {mount.display_name}"}),
            (mount, CARRYING, rider, {"rider": rider.entity_id, "label": f"Carrying {rider.display_name}"})):
        instance_id = f"condition-instance:{condition_id}:{target.entity_id}:0"
        target.conditions[instance_id] = ConditionInstance(
            instance_id=instance_id, condition_id=condition_id, source_definition_id=SRC, source_actor_id=source.entity_id,
            target_id=target.entity_id, applied_sequence=0, expires_on="UNTIL_REMOVED", data=data)


def unbind(engine: Any, rider: Any, mount: Any) -> None:
    engine._remove_condition(rider, MOUNTED, SRC)
    engine._remove_condition(mount, CARRYING, SRC)


def _landing(engine: Any, rider: Any, mount: Any, *, fear_legal: bool = False) -> Any | None:
    """The nearest free square within 5 feet of the mount (5.5e), preferring where the rider already is."""
    from ..gate2_runtime_models import Position

    around = _cells(engine, mount)
    taken = engine._occupied_cells_except(rider.entity_id) | around
    reach = {(x + dx, y + dy) for x, y in around for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    free = [cell for cell in reach if engine.grid.in_bounds(cell) and cell not in engine.grid.blocked and cell not in taken]
    if not free:
        return None
    here = rider.position
    free.sort(key=lambda cell: (engine.grid.distance_ft(cell, here), cell[1], cell[0]))
    if fear_legal:
        from ..gate2_runtime_models import Position
        free = [cell for cell in free if _fear_legal(engine, rider, Position(x=cell[0], y=cell[1]))]
    if not free:
        return None
    best = free[0]
    return Position(x=best[0], y=best[1])


def _fear_legal(engine: Any, actor: Any, destination: Any) -> bool:
    from .frightened_movement import path_allowed
    return path_allowed(engine, actor, [actor.position, destination])


def _saddle_destination(engine: Any, rider: Any, mount: Any) -> Any | None:
    """Select the nearest footprint cell allowed by visible Frightened sources."""
    from ..gate2_runtime_models import Position
    inside = sorted(_cells(engine, mount), key=lambda cell: (engine.grid.distance_ft(cell, rider.position), cell[1], cell[0]))
    return next((Position(x=x, y=y) for x, y in inside
                 if _fear_legal(engine, rider, Position(x=x, y=y))), None)


def dismount(engine: Any, rider: Any, mount: Any, *, fall: bool = False, why: str = "") -> None:
    """The rider leaves the saddle: a fall lands it Prone in the nearest free square within 5 feet of the mount."""
    if fall:
        # The rider's cells only stop counting as shared once the bond is gone, so find the square first.
        spot = _landing(engine, rider, mount)
    else:
        spot = None
    unbind(engine, rider, mount)
    if fall:
        if spot is None:  # nowhere to land: it stays where it is, still in the mount's space; nothing legal to do but keep the bond
            bind(engine, rider, mount, why=f"{rider.display_name} has no room to fall clear and stays in the saddle.")
            return
        _move(engine, rider, spot, why=SRC, extra={"thrown_from": mount.entity_id})
        engine._apply_condition(rider, PRONE, SRC, mount.entity_id, expires_on="STAND_UP")
    _say(engine, rider, why or f"{rider.display_name} dismounts from {mount.display_name}.")


def _move(engine: Any, actor: Any, destination: Any, *, why: str, cost: int = 0, extra: dict[str, Any] | None = None,
          forced: bool = True, path: Sequence[Any] | None = None) -> None:
    """Place a creature (evented: the replay reducer sets ``position`` from MOVEMENT_COMMITTED).

    Single-creature relocations -- mounting, dismounting, a fall, being carried and
    One Rider, One Beast's follow-up -- go through here. Overrun uses the same placement helper for
    both creatures before reconciling either. These calls reconcile the
    moved creature's areas. Without it an aura the rider or mount owns stayed on the square it was cast
    on when the pair moved as a unit; normal movement gets the same call from
    ``combat/typed_reactions.on_moved_geometry`` (owner 2026-10-02). ``forced`` keeps the printed
    distinction: a pushed/placed creature enters zones but does not make a "moving more than 10 feet
    through" save, while movement the creature chose (mounting, dismounting, an Overrun, a step taken as
    a Reaction) is willing movement and both counts towards that threshold and asks the save.
    ``path`` records the whole route when the movement is more than one straight step (an Overrun's),
    so the terrain's cumulative distance is read from the real walk. A carried creature's route is its
    mover's own shifted onto its side of the pair (``_carried_route``), and it inherits the mover's
    ``forced``: a mount walking where its rider directed it moved by choice, exactly as its rider did."""
    from .. import zones

    start = _relocate(engine, actor, destination, why=why, cost=cost, extra=extra, forced=forced, path=path)
    zones.on_moved(engine, actor, start, destination, forced=forced)


def _relocate(engine: Any, actor: Any, destination: Any, *, why: str, cost: int = 0,
              extra: dict[str, Any] | None = None, forced: bool = True,
              path: Sequence[Any] | None = None) -> Any:
    """Record placement and return the old square; the caller must reconcile zone movement.

    Normally used by ``_move``. Overrun records both placements before reconciling either,
    so entry effects see a mounted pair sharing its destination, including when a save causes a fall.
    """
    start = actor.position
    actor.position = destination
    route = list(path) if path else [start, destination]
    engine._append_event("MOVEMENT_COMMITTED", why, actor_id=actor.entity_id,
                         payload={"destination": destination.model_dump(mode="json"),
                                  "path": [point.model_dump(mode="json") for point in route],
                                  "cost_ft": cost, "forced": forced, **(extra or {})})
    return start


def _fits(engine: Any, mount: Any, anchor: Any) -> bool:
    return engine.grid.placement_legal(anchor, footprint=engine._footprint(mount), occupied_cells=engine._occupied_cells_except(mount.entity_id))


def _tup(anchor: Any, dx: int, dy: int) -> tuple[int, int]:
    return (anchor[0] + dx, anchor[1] + dy) if isinstance(anchor, tuple) else (anchor.x + dx, anchor.y + dy)


def _shifted(anchor: Any, dx: int, dy: int) -> Any | None:
    """The square ``dx, dy`` from ``anchor`` as a Position (None when it falls off the map's corner: Position is never negative)."""
    from ..gate2_runtime_models import Position

    x, y = _tup(anchor, dx, dy)
    return Position(x=x, y=y) if x >= 0 and y >= 0 else None


def _pos(cell: tuple[int, int]) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=cell[0], y=cell[1])


def _delta(payload: dict[str, Any], mover: Any) -> tuple[int, int]:
    from ..gate2_runtime_models import Position

    path = [Position(**row) for row in payload.get("path") or [] if isinstance(row, dict)]
    start = path[0] if path else mover.position
    return mover.position.x - start.x, mover.position.y - start.y


def _carried_route(payload: dict[str, Any], carried_start: Any) -> list[Any] | None:
    """The squares the carried creature actually walked: the mover's own recorded route, each square
    shifted onto the carried creature's side of the pair, so a per-step rule (terrain the pair walks
    through) reads the real walk instead of one hop from where it started to where it stopped. The
    carried creature has not moved yet, so its current square is where its own route begins. None when
    the mover recorded no route, which leaves ``_move`` its straight start-to-end pair."""
    from ..gate2_runtime_models import Position

    points = [Position(**row) for row in payload.get("path") or [] if isinstance(row, dict)
              and "x" in row and "y" in row]
    if len(points) < 2:
        return None
    dx = carried_start.x - points[0].x
    dy = carried_start.y - points[0].y
    route = [Position(x=point.x + dx, y=point.y + dy) for point in points if point.x + dx >= 0 and point.y + dy >= 0]
    return route if len(route) >= 2 else None


# ------------------------------------------------------------------------------------------------ the fall save
def _fall_save(engine: Any, rider: Any, reason: str) -> bool:
    """5.5e: a DC 10 Dexterity saving throw to stay in the saddle. True when the rider fell."""
    roll = engine._roll_save(rider, "DEX", DC_TO_STAY, SRC)
    if roll is None:
        return False
    fell = roll.total < DC_TO_STAY
    _say(engine, rider, f"{rider.display_name} {'fails' if fell else 'makes'} the DC {DC_TO_STAY} Dexterity save to stay mounted ({reason}): "
                        f"{roll.total}.")
    return fell


# ------------------------------------------------------------------------------------------------ events
@hook("event")
def on_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "MOVEMENT_COMMITTED":
        _on_moved(engine, kwargs)
    elif event_type in ("ENTITY_DEFEATED", "SUMMON_DISMISSED"):
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        if actor is not None and not actor.active:
            _on_gone(engine, actor)


@hook("event", nested=True)
def on_prone_applied(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Handle root and companion Prone events; actors without a mount bond are inert."""
    if event_type != "CONDITION_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("condition_id") != PRONE or payload.get("retained_instance_update"):
        return
    for target_id in kwargs.get("target_ids") or ():
        _on_prone(engine, engine.state.actors.get(target_id))


def _on_gone(engine: Any, actor: Any) -> None:
    """A rider that falls in battle or a mount that dies or leaves ends the bond; the survivor is on its feet where it stands."""
    for condition_id in (MOUNTED, CARRYING):
        held = _condition(actor, condition_id)
        if held is None:
            continue
        other = engine.state.actors.get(held.source_actor_id)
        engine._remove_condition(actor, condition_id, SRC)
        if other is not None:
            engine._remove_condition(other, CARRYING if condition_id == MOUNTED else MOUNTED, SRC)
            if other.active:
                _say(engine, other, f"{actor.display_name} is out of the fight: {other.display_name} is no longer mounted.")


def _on_prone(engine: Any, target: Any) -> None:
    """5.5e: a mount knocked Prone, or a rider knocked Prone while mounted, makes the save or falls."""
    if target is None:
        return
    rider = mount_of(engine, target) and target or rider_of(engine, target)
    if rider is None:
        return
    mount = mount_of(engine, rider)
    if mount is None:
        return
    if _fall_save(engine, rider, "knocked Prone"):
        if _cells(engine, rider) <= _cells(engine, mount):
            dismount(engine, rider, mount, fall=True, why=f"{rider.display_name} is thrown from {mount.display_name} and lands Prone.")
        else:  # already moving out of the saddle's square: it comes off where it is
            unbind(engine, rider, mount)
            _say(engine, rider, f"{rider.display_name} is thrown from {mount.display_name}.")


def _on_moved(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if any(payload.get(key) for key in ("carried_by", "thrown_from", "overrun", "mounting", "dismounting")):
        return  # what this plug-in itself moved
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not mover.active:
        return
    mount = mount_of(engine, mover)
    if mount is not None and controlled(mount) and not (payload.get("forced") or payload.get("teleport")):
        _spend_mount_movement(mover, mount, int(payload.get("cost_ft") or 0))
    dx, dy = _delta(payload, mover)
    forced = bool(payload.get("forced")) or bool(payload.get("teleport"))
    if mount is not None:  # the mover is a rider
        if not (dx or dy):
            return
        if forced or not controlled(mount):
            # It was moved, or walked off an independent mount it does not steer: it is no longer in the saddle.
            if not (_cells(engine, mover) <= _cells(engine, mount)):
                unbind(engine, mover, mount)
                _say(engine, mover, f"{mover.display_name} leaves {mount.display_name}'s back.")
            return
        anchor = _shifted(mount.position, dx, dy)  # the mount goes where its rider directs
        if anchor is None or not _fits(engine, mount, anchor):
            unbind(engine, mover, mount)
            _say(engine, mover, f"{mount.display_name} cannot follow there: {mover.display_name} is no longer mounted.")
            return
        _move(engine, mount, anchor, why=SRC, extra={"carried_by": mover.entity_id}, forced=forced,
              path=_carried_route(payload, mount.position))
        return
    rider = rider_of(engine, mover)
    if rider is None or not (dx or dy):
        return
    if payload.get("forced") and not payload.get("teleport"):
        if _fall_save(engine, rider, f"{mover.display_name} was moved against its will"):
            _move_rider_off(engine, rider, mover)
            return
    place = _shifted(rider.position, dx, dy)
    if place is None:
        unbind(engine, rider, mover)
        return
    _move(engine, rider, place, why=SRC, extra={"carried_by": mover.entity_id}, forced=forced,
          path=_carried_route(payload, rider.position))


def _move_rider_off(engine: Any, rider: Any, mount: Any) -> None:
    dismount(engine, rider, mount, fall=True, why=f"{rider.display_name} is thrown from {mount.display_name} and lands Prone.")


# ------------------------------------------------------------------------------------------------ speed and the menu
@hook("movement_step_surcharge")
def mounted_crawling_cost(engine: Any, actor: Any, mode: str) -> int | None:
    """A controlled Prone mount crawls: each foot costs one extra foot.

    Charge the rider's movement pool that carries this pair. Terrain remains
    additive, and standing/dismounting removes the surcharge on the next query.
    An independent mount pays through its own movement, not the rider's.
    """
    if mode != "walk":
        return None
    mount = mount_of(engine, actor)
    if mount is None or not controlled(mount) or _condition(mount, PRONE) is None:
        return None
    return engine.grid.square_size_ft


@hook("speed")
def mounted_speed(engine: Any, actor: Any) -> int | None:
    """A rider steering a controlled mount moves at the mount's Speed (5.5e).  What lowers the rider's own Speed (a slowing
    effect on the rider) still applies on top of the mount's, and a mount that cannot move (grappled) carries a rider that
    cannot either."""
    mount = mount_of(engine, actor)
    if mount is None or not controlled(mount):
        return _rhythm_speed(engine, actor)
    walk = _walk_speed(engine, actor)
    theirs = int(effective_speed(engine, mount))  # includes the mount's modifiers even during base-engine genesis
    from ..speed_contributions import SpeedContribution

    delta = max(0, theirs + walk - actor.speed_ft) - walk if theirs > 0 else -walk
    return SpeedContribution([(SRC, f"Riding {mount.display_name}", delta)])


# ------------------------------------------------------------------------------------------------ One Rider, One Beast
def _partner(engine: Any, actor: Any) -> Any | None:
    """The other half of a pair keeping One Rider, One Beast's rhythm (both carry the condition, each naming the other)."""
    held = _condition(actor, RHYTHM)
    if held is None:
        return None
    other = engine.state.actors.get(held.source_actor_id)
    if other is None or not other.active or not actor.active:
        return None
    back = _condition(other, RHYTHM)
    return other if back is not None and back.source_actor_id == actor.entity_id else None


def _rhythm_speed(engine: Any, actor: Any) -> int | None:
    """Owner: "use the higher Speed between you and the mount for both participants"."""
    other = _partner(engine, actor)
    if other is None:
        return None
    mine, theirs = _walk_speed(engine, actor), _walk_speed(engine, other)
    return theirs - mine if mine > 0 and theirs > mine else None


def _willing_beast(engine: Any, rider: Any) -> Any | None:
    """The mount One Rider, One Beast names: the one under the rider, else the nearest of its own mountable creatures."""
    under = mount_of(engine, rider)
    if under is not None:
        return under
    beasts = [beast for beast in engine.state.actors.values() if beast.active and beast is not rider
              and (beast.summon or {}).get("owner") == rider.entity_id and (beast.summon or {}).get("mountable")
              and rider_of(engine, beast) is None]
    return min(beasts, key=lambda beast: (engine._distance_actor_to_actor(rider, beast), beast.entity_id), default=None)


@hook("technique_used")
def one_rider_one_beast(ctx: Any) -> None:
    """One Rider, One Beast (owner text: Bonus Action, Expend Martial Focus, 1 minute, once per long rest): "You and one willing
    mount enter perfect battle rhythm. For the duration: use the higher Speed between you and the mount for both participants;
    both gain +2 AC; both gain Advantage on Dexterity saving throws; both ignore nonmagical difficult terrain; neither provokes
    Opportunity Attacks from movement; once per turn after either participant hits, the other may move 10 feet or make one Shove
    as a Reaction."  The typed action already gives the rider its +2 AC and Advantage; here the beast gets the same, and the pair
    is bound by one condition (the difficult-terrain and Dexterity-save rules read it; Speed, opportunity attacks and the
    follow-up below read it too)."""
    if str((ctx.typed or {}).get("source") or "") != ONE_RIDER:
        return
    from dataclasses import replace

    from .. import typed_executor

    engine, rider = ctx.engine, ctx.actor
    beast = _willing_beast(engine, rider)
    if beast is None:
        ctx.rider("One Rider, One Beast: no willing mount is in the fight to share the rhythm.")
        return
    lasting = next((row for row in ctx.typed.get("effects") or [] if row.get("type") == "ac_bonus"), {"duration": ctx.typed.get("duration")})
    for row in ctx.typed.get("effects") or []:
        if row.get("type") == "ac_bonus":
            typed_executor.BLOCKS["ac_bonus"](replace(ctx, target=beast), {**row, "applies_to": "target"})
    for who, other in ((rider, beast), (beast, rider)):
        engine._remove_condition(who, RHYTHM, ctx.source)
        engine._apply_condition(who, RHYTHM, ctx.source, other.entity_id,
                                expires_on=typed_executor.effect_expiry(ctx, lasting, who, condition=True) or "UNTIL_REMOVED",
                                data={"label": f"Battle rhythm with {other.display_name}"})
    rider.turn_flags["disengaged"] = True  # "neither provokes Opportunity Attacks from movement" -- from this turn on
    notice(ctx, f"{rider.display_name} and {beast.display_name} fall into perfect battle rhythm: the higher Speed for both, +2 AC, Advantage on "
              "Dexterity saves, difficult terrain ignored, no Opportunity Attacks from their movement.")


@hook("turn_start")
def rhythm_turn(engine: Any, actor: Any) -> None:
    if _partner(engine, actor) is not None:
        actor.turn_flags["disengaged"] = True  # their movement provokes no Opportunity Attacks


@hook("turn_start")
def relay_turn(engine: Any, actor: Any) -> None:
    """Beastback Relay (owner text): "When you begin your turn riding one willing mount, transfer onto another willing mount within
    15 feet without spending an Action" -- the transfer is open from the start of a turn that began in the saddle."""
    if "beastback_relay" in _rows(engine, actor) and mount_of(engine, actor) is not None:
        actor.turn_flags["relay_open"] = True


@hook("after_hit")
def rhythm_hit(ctx: Any, target: Any, kind: str) -> None:
    """Once per turn after either one hits, the other may move 10 feet or Shove as a Reaction (the two buttons below)."""
    engine, hitter = ctx.engine, ctx.actor
    other = _partner(engine, hitter)
    if other is None or hitter.turn_flags.get("rhythm_used") or not target.active or target.team_id == hitter.team_id:
        return
    hitter.turn_flags["rhythm_open"] = other.entity_id


def _step_toward(engine: Any, actor: Any) -> Any | None:
    """Where ``actor`` ends up moving up to 10 feet toward the nearest foe (5.5e grid: shortest way, ties by square); None when
    no reachable square is any nearer to one."""
    foes = [foe for foe in engine.state.actors.values() if foe.active and foe.team_id != actor.team_id]
    if not foes:
        return None

    def gap(cells: Any) -> int:
        return min(engine.grid.distance_between_cell_sets_ft(cells, engine._actor_cells(foe)) for foe in foes)

    here = gap(engine._actor_cells(actor))
    footprint = engine._footprint(actor)
    best: tuple[int, int, int] | None = None
    from .frightened_movement import path_allowed
    for goal, (path, _cost) in engine.grid.reachable(actor.position, movement_ft=10, occupied_cells=engine._occupied_cells_except(actor.entity_id),
                                      difficult_cells=engine._hostile_difficult_cells(actor), footprint=footprint).items():
        if not path_allowed(engine, actor, path):
            continue
        cells = engine.grid.footprint_cells(goal, footprint)
        rank = (gap(cells), goal.y, goal.x)
        if rank[0] < here and (best is None or rank < best):
            best = rank
    return None if best is None else _pos((best[2], best[1]))


def _route_ok(engine: Any, rider: Any, mount: Any, path: Any) -> bool:
    """Every step of the rider's route must also be a legal step for the mount's whole footprint."""
    steps = list(path)
    if len(steps) < 2:
        return True
    occupied = engine._occupied_cells_except(mount.entity_id)
    footprint = engine._footprint(mount)
    dx, dy = mount.position.x - rider.position.x, mount.position.y - rider.position.y
    for a, b in zip(steps, steps[1:]):
        if not engine.grid.step_legal(_tup(a, dx, dy), _tup(b, dx, dy), occupied_cells=occupied, footprint=footprint):
            return False
    return True


DASH_ID, DISENGAGE_ID = "system:combat.dash", "system:combat.disengage"


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from ..gate2_runtime_models import CandidateKind

    mount = mount_of(engine, actor)
    if candidate.kind == CandidateKind.MOVE:
        if mount is None:
            return None
        if not controlled(mount):
            return False  # an independent mount goes where it likes; the rider only comes along
        return _route_ok(engine, actor, mount, candidate.canonical_path)
    if candidate.source_definition_id in (DASH_ID, DISENGAGE_ID):
        return False if mount is not None and controlled(mount) else None  # the mount's own Dash / Disengage stand in (below)
    role = ((getattr(action, "parameters", None) or {}).get("mount_role")) if action is not None else None
    if not role:
        return None
    return _role_open(engine, actor, mount, candidate, role, action)


def _spent(actor: Any, flag: str) -> bool:
    return bool(actor.turn_flags.get(flag))


def _saddle_round_receipt(engine: Any, rider: Any) -> bool:
    """New Shared Saddle Rhythm rows opt into an integer per-round receipt.

    Old sealed rows retain their original Boolean flag. The engine preserves
    round flags across owner turns, so eligibility must compare the round.
    """
    return any(row.get('block') == BLOCK and row.get('kind') == 'saddle_rhythm' and row.get('round_receipt')
               for row in getattr(engine, 'typed_passive_rows', {}).get(rider.entity_id, []))


def _role_open(engine: Any, actor: Any, mount: Any, candidate: Any, role: str, action: Any) -> bool:
    target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
    if role == "up":
        if mount is not None or target is None or target is actor or not target.active or rider_of(engine, target) is not None:
            return False
        if (target.summon or {}).get("owner") != actor.entity_id or not (target.summon or {}).get("mountable"):
            return False
        if len(engine._actor_cells(actor)) >= len(engine._actor_cells(target)):
            return False  # 5.5e: at least one size larger
        return _walk_speed(engine, actor) > 0 and actor.movement_remaining_ft >= _cost(engine, actor)
    if role == "down":
        return mount is not None and actor.movement_remaining_ft >= _cost(engine, actor)
    if role.startswith("rhythm2_"):
        other = _partner(engine, actor)
        if other is None or actor.turn_flags.get("rhythm_open") != other.entity_id or actor.turn_flags.get("rhythm_used"):
            return False
        from .. import typed_reactions

        if not typed_reactions._can_react(engine, other):  # "as a Reaction": the other one's own
            return False
        return _step_toward(engine, other) is not None if role == "rhythm2_move" else target is not None and _near_mount(engine, other, target)
    if role == "relay":
        return _relay_open(engine, actor, mount, target)
    if mount is None or not controlled(mount):
        return False  # only a Controlled Mount takes the rider's directions
    if role == "charge":
        return _charge_reach(engine, actor, mount, target)
    if role == "charge_strike":
        return bool(actor.turn_flags.get("charge_open")) and not _spent(actor, "charge_strike_used") and target is not None \
            and (_near_mount(engine, mount, target) or engine._distance_actor_to_actor(actor, target) <= engine.grid.square_size_ft)
    if role == "charge_overrun":
        return bool(actor.turn_flags.get("charge_open")) and not _spent(actor, "charge_overrun_used") and target is not None \
            and _near_mount(engine, mount, target) and _overrun_plan(engine, actor, mount, target) is not None
    if role in ("dash", "disengage", "dodge"):
        return not _spent(actor, "mount_action_used")
    if role == "skirmish":
        return not _spent(actor, "mount_bonus_used")
    if role in ("shove_push", "shove_prone"):
        return not _spent(actor, "mount_action_used") and target is not None and _near_mount(engine, mount, target)
    if role in ("run_down", "run_down_bonus"):
        flag = "mount_action_used" if role == "run_down" else "mount_bonus_used"
        return not _spent(actor, flag) and target is not None and _near_mount(engine, mount, target) \
            and _overrun_plan(engine, actor, mount, target) is not None
    if role.startswith("trample_"):
        return not _spent(actor, "trampling_line_used") and actor.turn_flags.get("mount_overrun_target") == (target.entity_id if target else None)
    if role.startswith("rhythm_"):
        used = actor.turn_flags.get('saddle_rhythm_round_used')
        spent = used == engine.state.round_number if _saddle_round_receipt(engine, actor) else bool(used)
        return bool(actor.turn_flags.get("saddle_rhythm_open")) and not spent
    return False


def _relay_open(engine: Any, rider: Any, mount: Any, other: Any) -> bool:
    """Beastback Relay: from the start of a turn ridden, onto another willing mount within 15 feet -- one of the rider's own mountable
    creatures with nobody on it -- once."""
    if mount is None or other is None or other is mount or not rider.turn_flags.get("relay_open"):
        return False
    if not other.active or (other.summon or {}).get("owner") != rider.entity_id or not (other.summon or {}).get("mountable"):
        return False
    if rider_of(engine, other) is not None or len(_cells(engine, rider)) >= len(_cells(engine, other)):
        return False
    return engine.grid.distance_between_cell_sets_ft(_cells(engine, rider), _cells(engine, other)) <= 15 \
        and rider.movement_remaining_ft >= _cost(engine, rider)


def _charge_reach(engine: Any, rider: Any, mount: Any, target: Any) -> bool:
    """Great Beast Charge's chosen creature: one the pair can get to -- the mount's Speed, plus what movement is left, plus the
    reach of the closing attack."""
    if target is None or not target.active or target.team_id == rider.team_id:
        return False
    span = int(engine._effective_speed(mount)) + rider.movement_remaining_ft + engine.grid.square_size_ft
    return engine.grid.distance_between_cell_sets_ft(_cells(engine, mount), _cells(engine, target)) <= span


def _near_mount(engine: Any, mount: Any, target: Any) -> bool:
    return target.active and target.team_id != mount.team_id and engine.grid.distance_between_cell_sets_ft(
        engine._actor_cells(mount), engine._actor_cells(target)) <= engine.grid.square_size_ft


@hook("ai_candidate_allowed")
def offered_ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    return None


@hook("candidate_allowed")
def fear_allows_saddle_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Willing saddle placement may not bring a frightened rider closer to a visible source."""
    effects = ((getattr(action, "parameters", {}) or {}).get("typed") or {}).get("effects") or []
    kinds = {str(row.get("type")) for row in effects if isinstance(row, dict)}
    definition_id = str(getattr(action, "source_definition_id", "")
                        or getattr(candidate, "source_definition_id", ""))
    if "mount_up" in kinds or "mount_relay" in kinds or definition_id.endswith((".mount.up", ".mount.relay")):
        mount = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        if mount is None:
            return None
        destination = _saddle_destination(engine, actor, mount)
        if destination is None:
            return False
    elif "mount_down" in kinds or definition_id.endswith(".mount.down"):
        mount = mount_of(engine, actor)
        if mount is None:
            return None
        destination = _landing(engine, actor, mount, fear_legal=True)
        if destination is None:
            return False
    else:
        return None
    return _fear_legal(engine, actor, destination)


# ------------------------------------------------------------------------------------------------ the actions
@hook("button_description")
def mount_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    kinds = {eff.get("type") for eff in effects}
    if "mount_up" in kinds:
        return "During your move, mount a willing creature within 5 feet that is at least one size larger than you. This costs half your Speed in movement, with no action or cultivation point cost. You move with your mount while riding it."
    if "mount_down" in kinds:
        return "During your move, dismount into an adjacent legal space. This costs half your Speed in movement, with no action or cultivation point cost. You no longer move with the mount."
    return None


@hook("compile_actions")
def mount_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info["owned_ids"])
    if RIDER_PACKAGE not in owned and MOUNT_TRAINING not in owned:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    kinds = {str(row.get("kind")) for row in info.get("passives") or [] if row.get("block") == BLOCK}
    cl = int(numbers.get("cl") or 1)

    def make(key: str, name: str, role: str, effects: list[dict[str, Any]], *, kind: str = "SELF", reach: int | None = None,
             economy: Any = EconomyKind.NONE, **parameters: Any) -> ActionDefinition:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.mount.{key}", display_name=name, owner_id=actor_id, economy=economy,
            resolution_kind="TYPED", target_kind=kind, range_ft=reach,
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                                  "source": f"mounts.{key}"},
                        "expected_damage": 0, "player_only": True, "mount_role": role, **parameters})

    out = [make("up", "Mount", "up", [{"type": "mount_up"}], kind="ALLY_OR_SELF", reach=5),
           make("down", "Dismount", "down", [{"type": "mount_down"}], requires_condition=MOUNTED)]
    for key, name, role, what in (("dash", "Mount: Dash", "dash", "dash"), ("disengage", "Mount: Disengage", "disengage", "disengage"),
                                  ("dodge", "Mount: Dodge", "dodge", "dodge")):
        out.append(make(key, name, role, [{"type": "mount_do", "do": what}], requires_condition=MOUNTED))
    if "skirmish_rider" in kinds:
        out.append(make("skirmish", "Mount: Disengage (Bonus Action)", "skirmish", [{"type": "mount_do", "do": "disengage", "bonus": True}],
                        requires_condition=MOUNTED))
    if "mounted_maneuvers" in kinds:
        for key, name, effect_row in (
                ("shove_push", "Mount: Shove (push 5 ft)", {"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}),
                ("shove_prone", "Mount: Shove (Prone)", {"type": "condition", "condition": "prone", "applies_to": "target"})):
            out.append(make(key, name, key, [{"type": "mount_shove", "on_fail": [effect_row]}], kind="HOSTILE_ENTITY", reach=10,
                            requires_condition=MOUNTED))
    if "run_down" in kinds:
        out.append(make("run_down", "Mount: Overrun (Action)", "run_down", [{"type": "mount_overrun"}], kind="HOSTILE_ENTITY", reach=10,
                        requires_condition=MOUNTED))
        out.append(make("run_down_bonus", "Mount: Overrun (Bonus Action)", "run_down_bonus", [{"type": "mount_overrun", "bonus": True}],
                        kind="HOSTILE_ENTITY", reach=60, requires_condition=MOUNTED))
    if "trampling_line" in kinds and cl >= 7:
        for key, name, row in (
                ("trample_push", "Trampling Line: push 10 ft", {"type": "forced_movement", "distance_ft": 10, "direction": "away", "applies_to": "target"}),
                ("trample_prone", "Trampling Line: Prone", {"type": "condition", "condition": "prone", "applies_to": "target"}),
                ("trample_damage", "Trampling Line: Bludgeoning damage",
                 {"type": "damage", "flat": int(numbers.get("pb") or 2), "damage_types": ["bludgeoning"]}),
                ("trample_move", "Trampling Line: mount moves 10 more ft", None)):
            out.append(make(key, name, key, [{"type": "trampling_line", "row": row}], kind="HOSTILE_ENTITY", reach=60, requires_condition=MOUNTED))
    if "saddle_rhythm" in kinds and cl >= 7:
        for key, name, pick in (("rhythm_focus", "Shared Saddle Rhythm: regain Martial Focus", "focus"),
                                ("rhythm_move", "Shared Saddle Rhythm: move 5 ft, no Opportunity Attacks", "move"),
                                ("rhythm_temp", "Shared Saddle Rhythm: mount gains Temporary HP", "temp")):
            out.append(make(key, name, key, [{"type": "saddle_rhythm", "pick": pick}], requires_condition=MOUNTED))
    if ONE_RIDER in owned:
        for key, name, kind, row in (
                ("rhythm2_move", "One Rider, One Beast: the other moves 10 ft (Reaction)", "SELF", None),
                ("rhythm2_push", "One Rider, One Beast: the other Shoves, push 5 ft (Reaction)", "HOSTILE_ENTITY",
                 {"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}),
                ("rhythm2_prone", "One Rider, One Beast: the other Shoves, Prone (Reaction)", "HOSTILE_ENTITY",
                 {"type": "condition", "condition": "prone", "applies_to": "target"})):
            out.append(make(key, name, key, [{"type": "rhythm_reaction", "row": row}], kind=kind, reach=60 if row else None,
                            requires_condition=RHYTHM))
    if "beastback_relay" in kinds:
        out.append(make("relay", "Beastback Relay: transfer to another mount", "relay", [{"type": "mount_relay"}], kind="ALLY_OR_SELF", reach=15,
                        requires_condition=MOUNTED))
    if "great_beast_charge" in kinds:
        strike = [copy.deepcopy(row) for row in ((info.get("mechanics") or {}).get(GREAT_CHARGE) or {}).get("effects") or []
                  if isinstance(row, dict) and row.get("type") == "attack"]
        out.append(make("charge", "Great Beast Charge", "charge", [{"type": "beast_charge"}], kind="HOSTILE_ENTITY", reach=130,
                        economy=EconomyKind.ACTION, requires_condition=MOUNTED))
        if strike:
            out.append(make("charge_strike", "Great Beast Charge: the closing attack", "charge_strike", strike, kind="HOSTILE_ENTITY", reach=10,
                            requires_condition=MOUNTED))
        out.append(make("charge_overrun", "Great Beast Charge: Overrun through the target", "charge_overrun", [{"type": "mount_overrun", "free": True}],
                        kind="HOSTILE_ENTITY", reach=10, requires_condition=MOUNTED))
    return out


@hook("compile_block")
def compile_mount_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2),
             **({'round_receipt': 1} if spec.get('round_receipt') else {})}]


def _target(ctx: Any) -> Any | None:
    return ctx.target or next(iter(ctx.targets or []), None)


def _grant(engine: Any, actor: Any, delta: int, source: str, *, replacement: bool = False) -> None:
    before = actor.movement_remaining_ft
    actor.movement_remaining_ft = max(0, before + delta)
    engine._append_event("MOVEMENT_GRANTED", source, actor_id=actor.entity_id, payload={"distance_ft": actor.movement_remaining_ft - before,
        **({'allowance_replaced': True} if replacement else {})})


@effect("mount_up")
def mount_up(ctx: Any, eff: dict[str, Any]) -> None:
    engine, rider, mount = ctx.engine, ctx.actor, _target(ctx)
    if mount is None or mount_of(engine, rider) is not None:
        return
    cost = _cost(engine, rider)
    # The mount's space holds the rider's: it steps into the nearest square of the mount's footprint.
    spot = _saddle_destination(engine, rider, mount)
    if spot is None:
        notice(ctx, f"{rider.display_name} is too frightened to mount {mount.display_name}.")
        return
    rider.movement_remaining_ft = max(0, rider.movement_remaining_ft - cost)
    engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=rider.entity_id, payload={"distance_ft": -cost})
    if spot != rider.position:
        # 5.5e "During your move, you can mount a creature that is within 5 feet of you": the rider chose this
        # step, so it is willing movement -- it counts towards a terrain's "more than 10 feet through" save.
        _move(engine, rider, spot, why=ctx.source, extra={"mounting": mount.entity_id}, forced=False)
    bind(engine, rider, mount, why=f"{rider.display_name} mounts {mount.display_name} (half of its Speed: {cost} ft).")
    if controlled(mount):
        # A Controlled Mount moves as its rider directs, on its own Speed (5.5e).
        remaining = max(0, int(engine._effective_speed(mount)) - _mount_movement_spent(rider, mount))
        _grant(engine, rider, remaining - rider.movement_remaining_ft, ctx.source, replacement=True)


@effect("mount_down")
def mount_down(ctx: Any, eff: dict[str, Any]) -> None:
    engine, rider = ctx.engine, ctx.actor
    mount = mount_of(engine, rider)
    if mount is None:
        return
    cost = _cost(engine, rider)
    spot = _landing(engine, rider, mount, fear_legal=True)
    if spot is None:
        if _landing(engine, rider, mount) is None:
            ctx.rider(f"{rider.display_name} has no free square beside {mount.display_name} to dismount to.")
        else:
            notice(ctx, f"{rider.display_name} is too frightened to dismount toward the source of fear.")
        return
    if not _fear_legal(engine, rider, spot):
        notice(ctx, f"{rider.display_name} is too frightened to dismount toward the source of fear.")
        return
    walk = _walk_speed(engine, rider)
    pool = max(0, min(rider.movement_remaining_ft, walk) - cost)
    unbind(engine, rider, mount)
    # Dismounting is ordinary movement the rider chose ("During your move, you can ... dismount"), so its
    # feet count towards a named terrain's "moving more than 10 feet through" save and it can ask that save.
    _move(engine, rider, spot, why=ctx.source, extra={"dismounting": mount.entity_id}, forced=False)
    _grant(engine, rider, pool - rider.movement_remaining_ft, ctx.source)
    _say(engine, rider, f"{rider.display_name} dismounts from {mount.display_name} (half of its Speed: {cost} ft).")


@effect("mount_relay")
def mount_relay(ctx: Any, eff: dict[str, Any]) -> None:
    """Beastback Relay (owner text, Rider, CL 12+): "When you begin your turn riding one willing mount, transfer onto another willing
    mount within 15 feet without spending an Action. This movement: does not provoke Opportunity Attacks; may occur during movement;
    allows one mounted attack before or after the transfer."  The transfer is a dismount and a mount (5.5e: half the rider's Speed,
    the mount side of it; no Action, no Opportunity Attack -- it is placed, not walked).  The "one mounted attack" is the rider's
    ordinary Attack action, which this engine already lets come before or after any move, so it grants no extra attack."""
    engine, rider, fresh = ctx.engine, ctx.actor, _target(ctx)
    old = mount_of(engine, rider)
    if old is None or fresh is None:
        return
    cost = _cost(engine, rider)
    spot = _saddle_destination(engine, rider, fresh)
    if spot is None:
        notice(ctx, f"{rider.display_name} is too frightened to transfer to {fresh.display_name}.")
        return
    rider.turn_flags["relay_open"] = False
    remaining = max(0, rider.movement_remaining_ft - cost)
    unbind(engine, rider, old)
    _move(engine, rider, spot, why=ctx.source, extra={"mounting": fresh.entity_id})
    bind(engine, rider, fresh, why=f"{rider.display_name} transfers from {old.display_name} to {fresh.display_name} (Beastback Relay, no Action).")
    # A Controlled Mount moves on its own Speed: what movement is left is bounded by the new steed's.
    mount_remaining = max(0, int(engine._effective_speed(fresh)) - _mount_movement_spent(rider, fresh))
    _grant(engine, rider, (min(remaining, mount_remaining) if controlled(fresh) else remaining) - rider.movement_remaining_ft,
           ctx.source, replacement=True)


@effect("beast_charge")
def beast_charge(ctx: Any, eff: dict[str, Any]) -> None:
    """Great Beast Charge (owner text, Rider, Action, Joint Action): "You and your mount move up to the mount's Speed. During this
    movement: ignore nonmagical difficult terrain; do not provoke Opportunity Attacks from one chosen creature; move through one hostile
    creature's space if your mount succeeds on Overrun. At the end, you or the mount makes one melee attack." -- the chosen creature is
    the one charged.  The movement is the mount's Speed on top of what is left; the closing attack and the Overrun are the two follow-up
    buttons that open now (a Controlled Mount takes the rider's direction, as everywhere else)."""
    engine, rider, target = ctx.engine, ctx.actor, _target(ctx)
    mount = mount_of(engine, rider)
    if mount is None or target is None:
        return
    speed = int(engine._effective_speed(mount))
    _grant(engine, rider, speed, ctx.source)
    engine._remove_condition(rider, IGNORE_DIFFICULT, ctx.source)
    engine._apply_condition(rider, IGNORE_DIFFICULT, ctx.source, rider.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Great Beast Charge: difficult terrain ignored"})
    rider.turn_flags["spark_step_ignore_oa_from"] = target.entity_id  # engine: no Opportunity Attack from that creature this turn
    rider.turn_flags["charge_open"] = target.entity_id
    rider.turn_flags["charge_strike_used"] = False
    rider.turn_flags["charge_overrun_used"] = False
    notice(ctx, f"{rider.display_name} and {mount.display_name} charge {target.display_name}: up to {speed} feet more, difficult terrain "
              f"ignored, no Opportunity Attack from {target.display_name}; a melee attack closes the charge.")


def _mount_turn(ctx: Any, bonus: bool, free: bool = False) -> Any | None:
    mount = mount_of(ctx.engine, ctx.actor)
    if mount is None:
        return None
    if free:  # inside Great Beast Charge: the Overrun is part of the charge, not one of the mount's own actions
        ctx.actor.turn_flags["charge_overrun_used"] = True
    else:
        ctx.actor.turn_flags["mount_bonus_used" if bonus else "mount_action_used"] = True
    return mount


@effect("mount_do")
def mount_do(ctx: Any, eff: dict[str, Any]) -> None:
    engine, rider = ctx.engine, ctx.actor
    mount = _mount_turn(ctx, bool(eff.get("bonus")))
    if mount is None:
        return
    what = str(eff["do"])
    if what == "dash":
        _grant(engine, rider, int(engine._effective_speed(rider)), ctx.source)
        rider.turn_flags["dash_used"] = True
        notice(ctx, f"{mount.display_name} takes the Dash action: {rider.display_name} has that much more movement.")
    elif what == "disengage":
        rider.turn_flags["disengaged"] = True
        notice(ctx, f"{mount.display_name} takes the Disengage action: its movement this turn provokes no Opportunity Attacks.")
    else:
        engine._remove_condition(mount, "condition:core.dodge", ctx.source)
        engine._apply_condition(mount, "condition:core.dodge", ctx.source, mount.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
        notice(ctx, f"{mount.display_name} takes the Dodge action.")
    if "saddle_rhythm" in _rows(engine, rider):
        rider.turn_flags["saddle_rhythm_open"] = True  # Shared Saddle Rhythm's choice is now open


def _str_mod(mount: Any) -> int:
    from ..ability_checks import ability_modifier

    return ability_modifier(mount, "STR")


@effect("mount_shove")
def mount_shove(ctx: Any, eff: dict[str, Any]) -> None:
    """Mounted Maneuvers: the mount's Attack action is a Shove. A Shove is the 2024 Unarmed Strike option: the target (no more
    than one size larger) makes a Strength or Dexterity save against 8 + Proficiency Bonus + the shover's Strength modifier --
    here the mount's."""
    target = _target(ctx)
    mount = _mount_turn(ctx, False)
    if mount is None or target is None:
        return
    _shove(ctx, mount, target, eff["on_fail"])


def _shove(ctx: Any, shover: Any, target: Any, on_fail: list[dict[str, Any]]) -> None:
    """``shover`` (a mount) Shoves ``target``: the rider's Proficiency Bonus and the mount's Strength modifier set the DC."""
    from .. import typed_executor

    numbers = {**ctx.typed["numbers"], "save_dc": 8 + int(ctx.actor.proficiency_bonus) + _str_mod(shover)}
    inner = typed_executor.Context(ctx.engine, shover, ctx.action, ctx.intent, {**ctx.typed, "numbers": numbers}, [target], target, ctx.damage_cache)
    notice(ctx, f"{shover.display_name} shoves {target.display_name} (DC {numbers['save_dc']}).")
    typed_executor.run_effects(inner, [{"type": "save", "ability": "STR_OR_DEX", "max_size_larger": 1, "on_fail": copy.deepcopy(on_fail)}])


@effect("rhythm_reaction")
def rhythm_reaction(ctx: Any, eff: dict[str, Any]) -> None:
    """One Rider, One Beast's follow-up: after one of the pair hits, the other moves 10 feet or Shoves as a Reaction (once a turn)."""
    engine, hitter = ctx.engine, ctx.actor
    other = engine.state.actors.get(str(hitter.turn_flags.get("rhythm_open") or ""))
    if other is None or not other.active:
        return
    with activation(engine, other, ctx.source):
        other.reaction_available = False
        hitter.turn_flags["rhythm_used"] = True
        hitter.turn_flags["rhythm_open"] = ""
        if eff.get("row") is None:
            spot = _step_toward(engine, other)
            if spot is not None:
                _move(engine, other, spot, why=ctx.source, forced=False)
                notice(ctx, f"{other.display_name} moves up to 10 feet as a Reaction, in step with {hitter.display_name}.")
            return
        target = _target(ctx)
        if target is not None:
            _shove(ctx, other, target, [eff["row"]])


@hook("save")
def mounted_shove_dc(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Mounted Maneuvers: "When you Shove while mounted, use the mount's Strength modifier." The rider's own Shove: the mount's
    modifier for the rider's, through the DC (a negative bonus for the target raises it)."""
    option = str((ctx.typed or {}).get("unarmed_option") or "")
    if not option.startswith("shove") or "mounted_maneuvers" not in _rows(ctx.engine, ctx.actor):
        return None
    mount = mount_of(ctx.engine, ctx.actor)
    if mount is None:
        return None
    dc = int((ctx.numbers or {}).get("save_dc") or 0)
    swap = 8 + int(ctx.actor.proficiency_bonus) + _str_mod(mount)
    return {"bonus": dc - swap} if dc != swap else None


@hook("save")
def mounted_target_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Dragon-Felling Chop (owner text): "If the target is mounted, climbing, or flying by wings rather than hovering, it has
    Disadvantage on the save." A creature riding a mount is mounted; the climbing and flying halves have no state to read."""
    modifier = (ctx.typed or {}).get("modifier") or {}
    if str(modifier.get("id") or "") != "TAL_AXES_DRAGON_FELLING_CHOP" or mount_of(ctx.engine, subject) is None:
        return None
    return {"modes": ["DISADVANTAGE"]}


# ------------------------------------------------------------------------------------------------ Overrun
def _overrun_plan(engine: Any, rider: Any, mount: Any, target: Any) -> dict[str, Any] | None:
    """Where the mount ends up passing through ``target``'s space: straight on past it, the target's own squares costing double
    (owner: "treat that space as difficult terrain"), never ending in an occupied space. None when there is no room."""
    tx = sum(x for x, _ in engine._actor_cells(target)) / max(1, len(engine._actor_cells(target)))
    ty = sum(y for _, y in engine._actor_cells(target)) / max(1, len(engine._actor_cells(target)))
    mx = sum(x for x, _ in engine._actor_cells(mount)) / max(1, len(engine._actor_cells(mount)))
    my = sum(y for _, y in engine._actor_cells(mount)) / max(1, len(engine._actor_cells(mount)))
    step = ((tx > mx) - (tx < mx), (ty > my) - (ty < my))
    if step == (0, 0):
        return None
    theirs = _cells(engine, target)
    occupied = engine._occupied_cells_except(mount.entity_id)
    footprint = engine._footprint(mount)
    square = engine.grid.square_size_ft
    anchor, cost, path = (mount.position.x, mount.position.y), 0, [(mount.position.x, mount.position.y)]
    for _ in range(8):
        nxt = _tup(anchor, *step)
        overlap = theirs & set(footprint.occupied_cells(nxt))
        if not engine.grid.step_legal(anchor, nxt, occupied_cells=occupied - theirs, footprint=footprint):
            return None
        cost += square * (2 if overlap or (theirs & set(footprint.occupied_cells(anchor))) else 1)
        anchor = nxt
        path.append(nxt)
        if not (theirs & set(footprint.occupied_cells(anchor))) and engine.grid.placement_legal(anchor, footprint=footprint, occupied_cells=occupied):
            break
    else:
        return None
    if cost > rider.movement_remaining_ft:
        return None
    return {"anchor": _pos(anchor), "path": [_pos(cell) for cell in path], "cost": cost,
            "delta": (anchor[0] - mount.position.x, anchor[1] - mount.position.y)}


def _mod(actor: Any, skill: str, ability: str) -> int:
    from ..ability_checks import ability_modifier

    return int((actor.skills or {}).get(skill, ability_modifier(actor, ability)))


@effect("mount_overrun")
def mount_overrun(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    engine, rider, target = ctx.engine, ctx.actor, _target(ctx)
    mount = _mount_turn(ctx, bool(eff.get("bonus")), bool(eff.get("free")))
    if mount is None or target is None:
        return
    # Athletics contested by the target's Athletics (owner's Overrun): Advantage if the mount is larger, Disadvantage if smaller.
    mine, theirs = len(engine._actor_cells(mount)), len(engine._actor_cells(target))
    modes = {"ADVANTAGE"} if mine > theirs else {"DISADVANTAGE"} if mine < theirs else set()
    modes.update(typed_executor.check_modes(mount, "STR", "Athletics", engine=engine))
    mode = next(iter(modes)) if len(modes) == 1 else "NORMAL"
    bonus = _str_mod(mount)
    checker, ability, skill = mount, "STR", "Athletics"
    if "acrobatic_mount" in _rows(engine, rider):  # "Wisdom (Animal Handling) substitutes for the mount's Athletics"
        checker, ability, skill = rider, "WIS", "Animal Handling"
        bonus = _mod(rider, skill, ability)
    # Explicit source/skill metadata lets pre-roll choices identify the actual
    # substituted check. No metadata is inferred from a mount's unrelated kit.
    with engine.d20_scope({"kind": "check", "actor_id": checker.entity_id,
                           "target_id": target.entity_id, "source_id": ctx.source,
                           "ability": ability, "skill": skill}):
        ours = engine.roller.d20(modifier=bonus, actor_id=checker.entity_id, reason=f"CHECK:{ctx.source}", mode=mode)
    engine._record_roll(ours)
    with engine.d20_scope({"kind": "check", "actor_id": target.entity_id,
                           "target_id": mount.entity_id, "source_id": ctx.source,
                           "ability": "STR", "skill": "Athletics"}):
        against = engine.roll_check(
            modifier=_mod(target, 'Athletics', 'STR'),
            actor_id=target.entity_id,
            reason=f'CHECK:{ctx.source}',
            ability='STR',
            skill='Athletics',
            against_creature=mount,
        )
    engine._record_roll(against)
    won = ours.total >= against.total  # ties go to the one who acted, as a contest's ties stay as they were
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=mount.entity_id, target_ids=(target.entity_id,),
                         payload={"actor": ours.model_dump(mode="json"), "target": against.model_dump(mode="json"), "skill": "Athletics", "target_skill": "Athletics", "success": won})
    if not won:
        notice(ctx, f"{mount.display_name} fails to overrun {target.display_name} ({ours.total} against {against.total}).")
        return
    plan = _overrun_plan(engine, rider, mount, target)
    if plan is None:
        notice(ctx, f"{mount.display_name} overruns {target.display_name} but has no room to come out the other side.")
        return
    # The rider directs this movement, and the mount physically follows the
    # route. Either frightened creature can veto a path that brings it closer
    # to a visible source. Keep the translated rider path aligned with the
    # mount's anchor path so shared occupancy remains intact.
    from .frightened_movement import path_allowed
    mount_path = plan["path"]
    rider_path = [_shifted(rider.position, point.x - mount.position.x,
                            point.y - mount.position.y) for point in mount_path]
    if not path_allowed(engine, mount, mount_path) or any(point is None for point in rider_path) \
            or not path_allowed(engine, rider, rider_path):
        notice(ctx, f"{mount.display_name} cannot overrun along a path forbidden by fear.")
        return
    _through(engine, rider, mount, plan, ctx.source, rider_path)
    if rider.active and mount.active and mount_of(engine, rider) is mount:
        rider.turn_flags["mount_overrun_target"] = target.entity_id
    notice(ctx, f"{mount.display_name} overruns {target.display_name} ({ours.total} against {against.total}) and passes through its space.")


def _through(engine: Any, rider: Any, mount: Any, plan: dict[str, Any], source: str,
             rider_path: Sequence[Any] | None = None) -> None:
    """Carry the pair along the overrun path: one committed move each (the rider pays the movement).

    Both creatures are placed and recorded before either entry callback runs, so a
    Domain or an Aura the rider or the mount owns travels with them instead of standing on the square the
    pair charged off (owner 2026-10-02, MMX64).  ``forced=False``: an Overrun is movement the rider chose
    -- "attempt to move through one hostile creature's space" -- so a named terrain reads it as willing
    movement, which is the class its moving-through rule is written for.  ``path`` keeps the whole route
    the pair actually walked, so that distance is read from the real walk rather than from one straight
    step between the ends.

    ``rider_path`` is the mount's plan translated onto the rider's own squares -- the very route the fear
    check above approved -- and the rider records it as its own.  Recording only the two ends instead
    (``_relocate``'s default) would let the pair disagree about the same travel: terrain covering only the
    last two squares of a longer charge would read as the full straight hop, and terrain lying between the
    ends would read as never entered (MMX65r).  Optional so a caller that has no translated route keeps
    the old pair. Reconcile each recorded charge endpoint separately from any subsequent forced fall;
    entry remains due at the charge endpoint without replacing the live landing or its forced path."""
    from .. import zones

    dx, dy = plan["delta"]
    destination = _shifted(rider.position, dx, dy) or rider.position
    rider.movement_remaining_ft = max(0, rider.movement_remaining_ft - int(plan["cost"]))
    if controlled(mount):
        _spend_mount_movement(rider, mount, int(plan["cost"]))
    mount_start = _relocate(engine, mount, plan["anchor"], why=source, path=plan["path"],
                            forced=False, extra={"overrun": True})
    rider_start = _relocate(engine, rider, destination, why=source, cost=int(plan["cost"]), forced=False,
                            path=rider_path, extra={"overrun": True, "carried_by": mount.entity_id})
    for actor, start, end in ((mount, mount_start, plan["anchor"]), (rider, rider_start, destination)):
        # Reconcile the recorded charge, separately from any callback-induced forced fall.
        # Using the landing as the charge endpoint loses entry and invents an unmatched voluntary
        # path. entry_at retains the charge's entry, but keeps occupancy/auras at the live
        # position; it never places the rider back in the saddle. Per-turn guards prevent repeats.
        if actor.active:
            zones.on_moved(engine, actor, start, end, forced=False, entry_at=end)


@effect("trampling_line")
def trampling_line(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    engine, rider, target = ctx.engine, ctx.actor, _target(ctx)
    mount = mount_of(engine, rider)
    if mount is None or target is None:
        return
    rider.turn_flags["trampling_line_used"] = True
    row = eff.get("row")
    if row is None:  # "allow the mount to move 10 additional feet"
        _grant(engine, rider, 10, ctx.source)
        notice(ctx, f"Trampling Line: {mount.display_name} may move 10 more feet.")
        return
    inner = typed_executor.Context(engine, rider, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
    notice(ctx, f"Trampling Line on {target.display_name}.")
    typed_executor.run_effects(inner, [copy.deepcopy({**row, "applies_to": "target"})])


@effect("saddle_rhythm")
def saddle_rhythm(ctx: Any, eff: dict[str, Any]) -> None:
    engine, rider = ctx.engine, ctx.actor
    mount = mount_of(engine, rider)
    if mount is None:
        return
    rider.turn_flags["saddle_rhythm_round_used"] = engine.state.round_number if _saddle_round_receipt(engine, rider) else True
    rider.turn_flags.pop("saddle_rhythm_open", None)
    pick = eff.get("pick")
    if pick == "focus":
        if FOCUS in rider.resources and rider.resources.get(FOCUS, 0) < rider.resource_maximums.get(FOCUS, 0):
            engine._gain_resource(rider, FOCUS, 1, ctx.source)
    elif pick == "temp":
        engine._grant_temp_hp(mount, int(ctx.numbers.get("pb") or rider.proficiency_bonus), ctx.source, rider.entity_id)
    else:
        rider.turn_flags["oa_free_ft"] = int(rider.turn_flags.get("oa_free_ft") or 0) + 5
        _grant(engine, rider, 5, ctx.source)
        notice(ctx, "Shared Saddle Rhythm: the pair may move 5 more feet without provoking Opportunity Attacks.")


# ------------------------------------------------------------------------------------------------ what the pair gets
def _save_halves(ctx: Any, fail_effects: list[dict[str, Any]]) -> bool:
    """Whether the save being made is one whose success halves the damage (the effect's ``on_success`` has ``half_damage``)."""
    stack: list[Any] = [ctx.typed.get("effects") or []]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == "save" and (node.get("on_fail") is fail_effects or node.get("on_fail") == fail_effects):
                return any(isinstance(row, dict) and row.get("type") == "half_damage" for row in node.get("on_success") or [])
            stack.extend(value for value in node.values() if isinstance(value, (list, dict)))
        elif isinstance(node, list):
            stack.extend(node)
    return False


@hook("evasion")
def skillful_riding(ctx: Any, subject: Any, ability: str, failed: bool, fail_effects: list[dict[str, Any]]) -> bool | None:
    """Skillful Riding (Rider Package): "while you ride a willing mount, when the mount makes a Dexterity saving throw for half
    damage it takes no damage on a success and half damage on a failure" -- the mount's own save while its rider has the Package."""
    if str(ability or "").upper()[:3] != "DEX" or not any(isinstance(row, dict) and row.get("type") == "damage" for row in fail_effects):
        return None
    rider = rider_of(ctx.engine, subject)
    if rider is None or "rider_package" not in _rows(ctx.engine, rider) or not _save_halves(ctx, fail_effects):
        return None
    notice(ctx, f"Skillful Riding: {subject.display_name} takes {'half' if failed else 'no'} damage.")
    return True


@hook("attack_mode")
def mounted_offense(ctx: Any, target: Any) -> str | None:
    """Mounted Offense: while mounted, Advantage on melee attacks against unmounted creatures smaller than your mount."""
    engine, actor = ctx.engine, ctx.actor
    if target is None or "mounted_offense" not in _rows(engine, actor):
        return None
    mount = mount_of(engine, actor)
    if mount is None or mount_of(engine, target) is not None:
        return None
    reach = ctx.action.reach_ft if ctx.action.reach_ft is not None else ctx.action.range_ft
    if reach is None or reach > 10 or (ctx.typed or {}).get("ranged"):
        return None
    return "ADVANTAGE" if len(engine._actor_cells(target)) < len(engine._actor_cells(mount)) else None
