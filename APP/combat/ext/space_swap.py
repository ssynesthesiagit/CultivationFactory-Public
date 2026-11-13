"""Short Swap's exchange of spaces (AUTO23 Space sphere lane, 2026-10-04; AUTO23f1 fixes).

Owner text (authority/typed_mechanics/rules_text.json, tianxia.talent.space.short_swap):
"Choose one willing creature you can see within range. You and the target teleport, swapping spaces.
Both spaces must be unoccupied by other creatures and large enough to safely hold the arriving creature.
Short Swap cannot force an unwilling creature to move."

Before AUTO23 the talent was typed as a plain ``teleport`` aimed at the target, so only the creature that
was picked moved: the user stayed where it was.  This effect moves both creatures in one exchange.

Rules honoured here, all from the printed lines:
* "You and the target teleport, swapping spaces" -- both positions are written once, each with its own
  MOVEMENT_COMMITTED record, so a saved fight replays the exchange (two events, integers only).
* "Both spaces must be unoccupied by other creatures and large enough to safely hold the arriving
  creature" -- every cell the arriving creature's own body needs is judged (its whole footprint, at the
  height it arrives on): inside the map, not inside blocking terrain, and not standing where a third
  creature stands.  The two creatures leaving are not in each other's way, so a Large creature may
  exchange places with a Medium one.  An exchange that cannot be made in full is not made at all.
* "Short Swap cannot force an unwilling creature to move" -- the creature that would be moved is the one
  whose agreement the printed line asks for, so it is that creature who is asked, through the shared
  choice transport.  A creature on the user's own side that nobody can answer still goes along (its own
  side named it in "choose one willing creature"); for any other creature, silence is not consent and
  nothing moves.  The printed prohibition wins.
* "within range" (30 feet, the printed Range) is checked before anything moves.
* Both hops are teleports, so both answer every teleport lock: the sealed-creature rule a creature
  carries (Dimensional Seal's cannot teleport), Cut the Road Behind You's sealed road and a Sealing
  Gate, asked exactly as they are for any other teleport.

AUTO23f1 fixed three things in the first version of this module: the footprint test listed the *other*
creature's own departing cells as obstacles (so a Large creature could never exchange places), the
height of the arriving square was never tested, and the printed prohibition against forcing an
unwilling creature was left as a reminder while the effect moved any creature at all.

Inert without Short Swap: the effect only exists in a compiled action built from this record, and
every hook-free helper is private to this module.  No other ability, creature or saved fight is
touched; the fight map, hit points, resources and conditions are unchanged apart from the two
positions.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

DEFAULT_REACH_FT = 30  # "Range: 30 feet."


@hook("compile_actions")
def bonus_swap(info: dict[str, Any]) -> list[Any] | None:
    """Offer the printed CL 10 alternative only for newly reviewed swap rows.

    Cloning the actual action retains targeting, power-source costs and admission
    requirements. Old sealed rows without this metadata are unchanged.
    """
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import EconomyKind

    out = []
    for action in info.get("actions") or []:
        if action.owner_id != info["actor_id"] or action.economy != EconomyKind.ACTION:
            continue
        typed = (action.parameters or {}).get("typed") or {}
        row = next((r for r in typed.get("effects") or []
                    if r.get("type") == "space_swap" and r.get("bonus_action_min_cl")), None)
        numbers = typed.get("numbers") or info["numbers"]
        if row is None or int(numbers.get("cl") or 1) < int(row["bonus_action_min_cl"]):
            continue
        pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
        # The compiler may select another valid pool for the actual action.
        pools = set(RESOURCE_IDS.values())
        costs = tuple((resource, amount + 1 if resource in pools else amount)
                      for resource, amount in action.costs)
        if not any(resource in pools for resource, _ in costs):
            costs = (*costs, (pool, 2))
        cp = sum(amount for resource, amount in costs if resource in pools)
        out.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + "+bonus_swap",
            "display_name": f"{action.display_name} (Bonus Action, {cp} CP)",
            "economy": EconomyKind.BONUS_ACTION, "costs": costs}))
    return out or None


def _teleport_locked(engine: Any, actor: Any) -> bool:
    """Whether this creature is sealed against teleporting at all (Dimensional Seal and its own kin)."""
    from ..typed_executor import condition_rules

    return any(rule.get("no_teleport") for rule in condition_rules(actor))


def _willing(ctx: Any, other: Any) -> bool:
    """"Short Swap cannot force an unwilling creature to move."

    The creature that is about to be moved is the one whose agreement the printed line asks for, so it is
    that creature who is asked, through the bounded choice transport: a player controlling it answers on its
    own turn and on the caster's turn alike, and an AI answers for itself.  A creature on the caster's own
    side that nobody can answer still goes along -- its own side is the one that named it in the printed
    "choose one willing creature you can see".  For any other creature silence is *not* consent: the printed
    prohibition wins and nothing moves.
    """
    from . import needle

    own_side = getattr(other, "team_id", None) == getattr(ctx.actor, "team_id", None)
    from ..factory_compiler import RESOURCE_IDS

    bonus = str(ctx.action.economy) == 'BONUS_ACTION'
    cp = sum(amount for resource, amount in ctx.action.costs if resource in set(RESOURCE_IDS.values()))
    payment = f"Bonus Action and {cp} CP" if bonus else "Action and 1 CP"
    agree = "choice:needle.space_swap_agree"
    chosen = needle.ask(ctx.engine, ctx.intent,
                        needle.checkpoint_id(ctx.engine, "space_swap_willing", ctx.actor.entity_id, other.entity_id),
                        other, agree, [agree], labels={agree: f"{other.display_name} goes along with the exchange"},
                        preferred=[agree], allow_decline=True, name=ctx.action.display_name,
                        default="first" if own_side else "decline", target_id=other.entity_id,
                        prompt=f"{ctx.action.display_name}: {ctx.actor.display_name} may exchange places with "
                               f"{other.display_name} ({ctx.actor.display_name} to {other.position.x},"
                               f"{other.position.y}, and {other.display_name} to {ctx.actor.position.x},"
                               f"{ctx.actor.position.y}), which costs {ctx.actor.display_name} their "
                               f"{payment}. "
                               f"Short Swap cannot force an unwilling creature to move: does "
                               f"{other.display_name} agree to be moved?")
    return bool(chosen)


@effect("space_swap")
def space_swap(ctx: Any, eff: dict[str, Any]) -> None:
    """Swap the user's square with a willing creature's square (Short Swap)."""
    from dataclasses import replace

    from .. import ext, zones
    from ..space import volume
    from ..technique_interception import movement_committed

    engine, user, other = ctx.engine, ctx.actor, ctx.target
    name = ctx.action.display_name
    if other is None or other is user or not other.active:
        ctx.rider(f"{name}: choose one willing creature to exchange places with; nothing happens.")
        return
    here, there = user.position, other.position
    reach = int(eff.get("distance_ft") or DEFAULT_REACH_FT)
    if engine.grid.distance_ft(here, there) > reach:
        ctx.rider(f"{name}: {other.display_name} is out of reach; nothing happens.")
        return
    # "Both spaces must be unoccupied by other creatures and large enough to safely hold the arriving
    # creature": every cell the arrival's own body needs, at the height it arrives on.  Both creatures are
    # leaving, so neither is in the other's way, but each arrival must also clear the square the *other* one
    # is arriving on -- a Large body does not fit in the square a Medium creature is about to stand in.
    others = engine._occupied_volumes_except(user.entity_id, ignore_actor_ids=(other.entity_id,))
    arriving = set(volume(there, footprint=engine._footprint(user)))
    for mover, cell, in_the_way in ((user, there, set()), (other, here, arriving)):
        if not engine.grid.volume_legal(cell, footprint=engine._footprint(mover),
                                        occupied_cells=others | in_the_way):
            ctx.rider(f"{name}: {mover.display_name}'s whole body will not fit safely in {cell.x}, {cell.y} "
                      "(the map, a wall or another creature is in the way); nothing happens.")
            return
    if not _willing(ctx, other):
        ctx.rider(f"{name}: {other.display_name} is not willing to be moved, and Short Swap cannot force an "
                  "unwilling creature to move; nothing happens.")
        return
    # Both hops are teleports, so both answer every teleport lock (the sealed-creature rule, a sealed
    # road from Cut the Road Behind You, a Sealing Gate).  Nothing moves if either hop is refused.
    for mover, start, end, hop in ((user, here, there, ctx),
                                   (other, there, here, replace(ctx, actor=other, targets=[other], target=None))):
        if _teleport_locked(engine, mover):
            ctx.rider(f"{name}: {mover.display_name} is sealed against teleporting right now; nothing happens.")
            return
        if ext.has("teleport_gate") and ext.any_false("teleport_gate", hop, start, end):
            return
        if False in ext.run("teleport_check", engine, mover, start, end):
            return
    user.position, other.position = there, here
    feet = engine.grid.distance_ft(here, there)
    for mover, start, end in ((user, here, there), (other, there, here)):
        movement_committed(engine, mover.entity_id, ctx.source, user.entity_id, feet)
        engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=mover.entity_id,
                             payload={"destination": end.model_dump(mode="json"),
                                      "path": [start.model_dump(mode="json"), end.model_dump(mode="json")],
                                      "cost_ft": 0, "teleport": True})
        zones.on_moved(engine, mover, start, end, forced=True)
    from . import note

    note(engine, ctx.source, user,
         f"Short Swap: {user.display_name} and {other.display_name} exchange places "
         f"({there.x}, {there.y}) and ({here.x}, {here.y}).", (user, other))
