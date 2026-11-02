"""Returning-Heaven Momentum Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Returning-Heaven Momentum Body (Momentum and the features, with their Normalized
Procedures). Momentum (resource:named.momentum, maximum PB, PB + 3 with Avalanche Meridian Circuit) is gained by
combat/ext/subpath_pools.py. Owned rows: ``{"type": "path_passive", "kind": "momentum", "role": "gather" | "store" |
"avalanche"}``; Store Impact is the compiled Reaction; Heaven-Returning Impact's action runs ``heaven_returning_impact``.

Gather and Return  once per turn after an unarmed hit, 1 Momentum (asked): + 1d8 Bludgeoning or Force (2d8 at CL11, 3d8 at
                   CL17) and one choice: push 5 feet, move 5 feet without provoking, +1 AC against it until your next turn, or
                   + 5 feet on the next push or pull you impose this turn. With Avalanche Meridian Circuit: 1 to 3 Momentum,
                   one asked choice per point (another die, 5 more feet of push, 5 feet of movement), repeats allowed.
Store the Collision  Store Movement (asked when a hostile push or pull is about to move you): your Reaction and 1 Stamina, 15 feet
                   less; at 0 feet the same effect's Prone does not land and you gain 1 Momentum. Store Impact is its compiled
                   Reaction (2d8 + CON off Bludgeoning, Force or Thunder damage; 1 Momentum when that brings it to 0). Once per
                   round between them.
Heaven-Returning Impact  move to the aimed space (a physical route, no Opportunity Attacks), then each creature within 5 feet of
                   the straight line from where you started makes a Dexterity save against one 6d10 + 1d10 per Momentum spent
                   Force roll: failure, full damage, pushed 20 feet away from the line, Prone and no Reactions until its next turn;
                   success, half and pushed 5 feet.
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.returning_heaven_momentum_body.feature."
MOMENTUM = "resource:named.momentum"
NEXT_PUSH = "condition:typed.gather_next_push"
STORE = PREFIX + "store_the_collision"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "momentum"}


def _cl(engine: Any, actor: Any) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("cl") or 1)


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "momentum_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "momentum")


# ----------------------------------------------------------------------------------------------- Gather and Return
@hook("after_hit")
def gather_and_return(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if kind != "unarmed" or "gather" not in roles or target is None or not target.active or target.team_id == actor.team_id:
        return
    if actor.turn_flags.get("_round_gather") == _stamp(engine) or int(actor.resources.get(MOMENTUM, 0) or 0) < 1:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    cl = _cl(engine, actor)
    dice = 3 if cl >= 17 else 2 if cl >= 11 else 1
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    if "avalanche" in roles:
        labels = {"die": f"Another d8 of damage", "push": "5 more feet of push", "move": "Move 5 feet without provoking"}
        picks: list[str] = []
        while len(picks) < 3 and int(actor.resources.get(MOMENTUM, 0) or 0) > len(picks):
            picked = ask(engine, ctx.intent, checkpoint_id(engine, "gather_avalanche", target.entity_id, len(picks)), actor, "choice:needle.gather_and_return",
                         list(labels), labels=labels, allow_decline=True, default="decline" if picks else "first", target_id=target.entity_id,
                         name="Gather and Return", prompt=f"Gather and Return (Avalanche): spend Momentum {len(picks) + 1} of up to 3 for one benefit?")
            if not picked or picked[0] not in labels:
                break
            picks.append(picked[0])
        if not picks:
            return
        actor.turn_flags["_round_gather"] = _stamp(engine)
        engine._spend_resource(actor, MOMENTUM, len(picks), PREFIX + "gather_and_return")
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": dice + picks.count("die"), "sides": 8},
                              "damage_types": ["bludgeoning", "force"], "evidence": "Gather and Return"}])
        if picks.count("push") and target.active:
            te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5 * picks.count("push"), "direction": "away"}])
        if picks.count("move"):
            _move(sub, actor, 5 * picks.count("move"), "choice:needle.gather_move", "Gather and Return")
        return
    labels = {"push": f"Push {target.display_name} 5 feet", "move": "Move 5 feet without provoking", "ac": f"+1 AC against {target.display_name}",
              "next_push": "+5 feet on the next push or pull you impose this turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "gather", target.entity_id), actor, "choice:needle.gather_and_return", list(labels),
                 labels=labels, allow_decline=True, target_id=target.entity_id, name="Gather and Return",
                 prompt=f"Gather and Return: {ctx.action.display_name} hit {target.display_name}. Spend 1 Momentum for + {dice}d8 and one choice?")
    if not picked or picked[0] not in labels:
        return
    actor.turn_flags["_round_gather"] = _stamp(engine)
    engine._spend_resource(actor, MOMENTUM, 1, PREFIX + "gather_and_return")
    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": dice, "sides": 8}, "damage_types": ["bludgeoning", "force"],
                          "evidence": "Gather and Return"}])
    choice = picked[0]
    if choice == "push" and target.active:
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    elif choice == "move":
        _move(sub, actor, 5, "choice:needle.gather_move", "Gather and Return")
    elif choice == "ac":
        te.run_effects(sub, [{"type": "ac_against", "amount": 1, "expires_on": "START_OF_SELF_NEXT_TURN"}])
    else:
        engine._apply_condition(actor, NEXT_PUSH, PREFIX + "gather_and_return", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": "Gather and Return: +5 feet on your next push or pull this turn"})


@hook("forced_movement_bonus")
def next_push(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> int:
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == NEXT_PUSH), None)
    if held is None:
        return 0
    ctx.actor.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "gather_and_return", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"condition_id": NEXT_PUSH, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return 5


# ---------------------------------------------------------------------------------------------- Store the Collision
def _store_ready(engine: Any, owner: Any) -> bool:
    from ..typed_executor import condition_rules

    key = "once_per_round:typed." + STORE
    return ("store" in _roles(engine, owner) and owner.turn_flags.get(key) != int(engine.state.round_number) and owner.active
            and owner.reaction_available and int(owner.resources.get("resource:core.stamina", 0) or 0) >= 1
            and not any(rule.get("no_reactions") for rule in condition_rules(owner)))


@hook("forced_movement_reduction")
def store_movement(ctx: Any, subject: Any) -> int:
    engine = ctx.engine
    if subject is not None:
        ctx.damage_cache.pop(("stored_movement", subject.entity_id, ctx.source), None)
    if subject is None or ctx.actor is subject or ctx.actor.team_id == subject.team_id or not _store_ready(engine, subject) \
            or int(ctx.forced_movement_distance_ft or 0) <= 0:
        return 0
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "store_movement", subject.entity_id), subject, "choice:needle.store_the_collision_move", ["store"],
                 labels={"store": "Reaction and 1 Stamina: 15 feet less (at 0, no Prone and 1 Momentum)"}, allow_decline=True,
                 target_id=subject.entity_id, name="Store the Collision",
                 prompt=f"Store the Collision: {ctx.action.display_name} would move {subject.display_name} {ctx.forced_movement_distance_ft} feet.")
    if not picked:
        return 0
    from .. import typed_reactions

    with activation(engine, subject, STORE):
        typed_reactions._open(engine, {"feature_id": STORE}, subject, (ctx.actor.entity_id,), "FORCED_MOVEMENT")
        subject.reaction_available = False
        subject.turn_flags["once_per_round:typed." + STORE] = int(engine.state.round_number)
        engine._spend_resource(subject, "resource:core.stamina", 1, STORE)
        distance = int(ctx.forced_movement_distance_ft or 0)
        if distance and distance <= 15:
            # Shared only by contexts of this resolving activation, never by the engine
            # or a later use of the same action. The associated Prone rider consumes it.
            ctx.damage_cache[("stored_movement", subject.entity_id, ctx.source)] = True
            from .subpath_pools import gain

            gain(engine, subject, MOMENTUM, STORE, normal=False)
        return 15


@hook("condition_attempt")
def stored_no_prone(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if subject is None:
        return None
    if str((effect_row or {}).get("condition") or "").lower() != "prone":
        return None
    return False if ctx.damage_cache.pop(("stored_movement", subject.entity_id, ctx.source), False) else None


@effect("momentum_gain")
def momentum_gain(ctx: Any, row: dict[str, Any]) -> None:
    """Store Impact brought the packet to 0: "gain 1 Momentum" (past the round's limit, not past the maximum)."""
    from .subpath_pools import gain

    gain(ctx.engine, ctx.actor, MOMENTUM, STORE, normal=False)


# ------------------------------------------------------------------------------------------ Heaven-Returning Impact
def _line(start: Any, end: Any) -> list[tuple[int, int]]:
    """The squares of the straight segment between two squares (Bresenham)."""
    x0, y0, x1, y1 = start.x, start.y, end.x, end.y
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, out = dx + dy, []
    while True:
        out.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return out
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


@effect("heaven_returning_impact")
def heaven_returning_impact(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import DiceSpec, Position

    engine, actor = ctx.engine, ctx.actor
    start = actor.position
    te.run_effects(ctx, [{"type": "move_to_aim", "distance_ft": 120, "radius_ft": 5}])
    spent = 3
    left = int(actor.resources.get(MOMENTUM, 0) or 0)
    if left:
        engine._spend_resource(actor, MOMENTUM, left, PREFIX + "heaven_returning_impact")  # "and all current Momentum"
        spent += left
    line = _line(start, actor.position)
    hit = [c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c is not actor
           and any(engine.grid.distance_ft(c.position, Position(x=x, y=y)) <= 5 for x, y in line)]
    if not hit:
        return
    roll = engine.roller.roll(DiceSpec(count=6 + spent, sides=10, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}")
    engine._record_roll(roll)
    for creature in hit:
        nearest = min(line, key=lambda cell: engine.grid.distance_ft(creature.position, Position(x=cell[0], y=cell[1])))
        sub = te.Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed, "_area_centre": nearest}, [creature], creature, {})
        te.run_effects(sub, [{"type": "save", "ability": "dex", "evidence": "Heaven-Returning Impact: Dexterity saving throw",
                              "on_fail": [{"type": "damage", "applies_to": "target", "flat": int(roll.total), "damage_types": ["force"]},
                                          {"type": "forced_movement", "applies_to": "target", "distance_ft": 20, "direction": "away_center"},
                                          {"type": "condition", "applies_to": "target", "condition": "prone"},
                                          {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                              "on_success": [{"type": "damage", "applies_to": "target", "flat": int(roll.total) // 2, "damage_types": ["force"]},
                                             {"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away_center"}]}])
    note(engine, ctx.source, actor, f"Heaven-Returning Impact: {6 + spent}d10 Force ({roll.total}) along the line.", hit)
