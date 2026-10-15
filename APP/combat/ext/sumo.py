"""Sumo riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Sumo (Rooted Stance, Sumo Strike, Ring Breaker, Yokozuna Presence, Immovable God and
their Normalized Procedures). Rooted Stance is the stance condition ``condition:typed.stance.rooted_stance`` (its ending on
movement and Unconscious: combat/ext/docket_terrain.py; Yokozuna Presence's aura: docket_terrain's aura block). Owned row:
``{"type": "path_passive", "kind": "sumo", "role": "immovable"}``. Sumo Strike is a path_riders ``paid_hit`` row running
``sumo_push``; Ring Breaker's action runs ``ring_breaker_push`` and ``ring_breaker_step_in``; ``sumo_mark`` names the
activation whose pushes collide.

Rooted Stance      Advantage on checks to escape a grapple (hook escape_mode); counts one size larger when grappling or shoving
                   and when resisting forced movement (hook size_steps); forced movement on it is 5 feet shorter, once per
                   movement (hook forced_distance).
Immovable God      always Rooted while conscious (entered at the start of its turns and again whenever it ends, no Bonus
                   Action); two more sizes larger for the same things; forced movement from a lower Source CL (a typed
                   fighter's CL, any other creature 0) does not move it, nor does a lower-CL effect knock it Prone (hook
                   condition_attempt); from an equal or higher one, an opposed Cultivation Check (d20 + Proficiency Bonus + key
                   modifier each; a tie leaves it where it is); once during each of its turns, after 10+ feet of willing
                   movement, an asked unarmed strike (a Granted Attack) against a creature that came within its reach during
                   the movement.
Sumo Strike        push 10 feet, or, against a creature more than one size larger, a Strength save: 10 feet or 5; a collision
                   deals 1d6 Bludgeoning (2d6 at CL11, 3d6 at CL17) to the target and to what it hit: a map object, or a
                   creature that fails a Dexterity save.
Ring Breaker       failure: pushed up to 20 feet (you choose how far), Prone, and you may step into its former space;
                   success: pushed 5 feet, and you may step in if it left. A collision with a solid surface deals 3d8
                   Bludgeoning to the target; with a creature, that creature makes a Dexterity save: 3d8 and Prone, or half.
Every hook returns early for a creature without the stance, row or marker.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.sumo.feature."
ROOTED = "condition:typed.stance.rooted_stance"


def _rooted(actor: Any) -> bool:
    return actor is not None and any(c.condition_id == ROOTED for c in actor.conditions.values())


def _immovable(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == "path_rider" and row.get("kind") == "sumo" and row.get("role") == "immovable"
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), []))


def _cl(engine: Any, actor_id: str) -> int:
    """A fighter's Source CL: a typed fighter's CL; anything else is mundane (0)."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
    return int((bundle or {}).get("cl") or 0)


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _conscious(actor: Any) -> bool:
    return actor.active and not any(c.condition_id == "condition:typed.unconscious" for c in actor.conditions.values())


# ------------------------------------------------------------------------------------------------------ Rooted Stance
@hook("escape_mode")
def rooted_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _rooted(escaper) else None  # "Advantage on checks ... against Grapples"


@hook("size_steps")
def rooted_size(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    """"Count as one size larger for Grappling, Shoving ... and resisting forced movement" (Immovable God: two more)."""
    if role == "act" and not set(purposes) & {"grapple", "shove"}:
        return None  # its own push that is not a grapple or shove
    steps = (1 if _rooted(creature) else 0) + (2 if _immovable(engine, creature) else 0)
    return steps or None


def _opposed(engine: Any, mover: Any, source: Any) -> bool:
    """Immovable God's opposed Cultivation Check against the source; True when the movement fails."""
    def bonus(creature: Any) -> int:
        key = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("key_mod") or 0)
                    for a in engine.action_catalog.values() if a.owner_id == creature.entity_id
                    and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("key_mod") is not None), 0)
        return int(creature.proficiency_bonus or 0) + key

    mine = engine.roll_check(modifier=bonus(mover), actor_id=mover.entity_id, reason='CHECK:immovable_god:cultivation')
    engine._record_roll(mine)
    theirs = engine.roll_check(
        modifier=bonus(source),
        actor_id=source.entity_id,
        reason='CHECK:immovable_god:cultivation',
    )
    engine._record_roll(theirs)
    held = int(mine.total) >= int(theirs.total)  # a tie leaves things as they were: it stays put
    note(engine, PREFIX + "immovable_god", mover, f"Immovable God: {mover.display_name}'s Cultivation Check {mine.total} against "
         f"{source.display_name}'s {theirs.total}: {'it does not move' if held else 'the movement goes ahead'}.", (mover.entity_id, source.entity_id))
    return held


@hook("forced_distance")
def rooted_forced(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if mover is None:
        return None
    if _immovable(engine, mover) and source is not None and source.entity_id != mover.entity_id:
        if _cl(engine, source.entity_id) < _cl(engine, mover.entity_id):
            note(engine, PREFIX + "immovable_god", mover, f"Immovable God: {source.display_name} cannot move {mover.display_name}.", (mover.entity_id,))
            return distance_ft
        if _opposed(engine, mover, source):
            return distance_ft
    return 5 if _rooted(mover) else None  # "Reduce forced movement affecting you by 5 feet"


@hook("condition_attempt")
def immovable_prone(ctx: Any, subject: Any, effect: Any) -> bool | None:
    """An effect whose Source CL is lower than yours cannot knock you Prone."""
    if str((effect or {}).get("condition") or "").lower() != "prone" or subject is None or not _immovable(ctx.engine, subject):
        return None
    if ctx.actor is subject or _cl(ctx.engine, ctx.actor.entity_id) >= _cl(ctx.engine, subject.entity_id):
        return None
    return False


def _enter(engine: Any, actor: Any) -> None:
    """Immovable God: enter Rooted Stance without an action (the stance's own effects, as its button runs them)."""
    if _rooted(actor) or not _conscious(actor):
        return
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                   and ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "rooted_stance"), None)
    if action is None:
        return
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    ctx = te.Context(engine, actor, action, getattr(engine, "_active_intent", None), typed, [actor], actor, {})
    te.run_effects(ctx, typed.get("effects") or [])


@hook("turn_start")
def immovable_rooted(engine: Any, actor: Any) -> None:
    if _immovable(engine, actor):
        _enter(engine, actor)


@hook("event")
def immovable_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The stance comes back as soon as it can (Rooted Stance's own ending on movement is docket_terrain.py's event hook, which
    runs first in this same dispatch; a removal made inside an event hook is not itself dispatched), and the strike after moving."""
    if event_type == "HEALING_APPLIED":
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None and _immovable(engine, actor):
            _enter(engine, actor)  # conscious again: "it automatically resumes when the conditions are again met"
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not _immovable(engine, actor) or not actor.active:
        return
    _enter(engine, actor)
    payload = kwargs.get("payload") or {}
    if payload.get("forced") or payload.get("teleport") or payload.get("dragged_by") or engine.state.current_actor_id != actor.entity_id:
        return
    stamp = _stamp(engine)
    path = payload.get("path") or []
    moved = max(0, len(path) - 1) * engine.grid.square_size_ft
    record = actor.turn_flags.get("_round_immovable_moved") or {}
    total = (int(record.get("ft") or 0) if record.get("stamp") == stamp else 0) + moved
    actor.turn_flags["_round_immovable_moved"] = {"stamp": stamp, "ft": total}
    if total < 10 or actor.turn_flags.get("_round_immovable_strike") == stamp or len(path) < 2:
        return
    _entered_strike(engine, actor, path[0])


def _unarmed_strike(engine: Any, actor: Any) -> Any:
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == actor.entity_id and ".natural." in action.source_definition_id and "#" not in action.source_definition_id \
                and not (action.parameters or {}).get("player_only") and any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                                                            for e in typed.get("effects") or []):
            return action
    return None


def _entered_strike(engine: Any, actor: Any, start: Any) -> None:
    """"make one unarmed strike against one creature that entered your reach during that movement" (Granted Attack)."""
    from ..gate2_runtime_models import Position
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    action = _unarmed_strike(engine, actor)
    if action is None:
        return
    reach = int(action.range_ft or 5)
    origin = Position.model_validate(start) if isinstance(start, dict) else start
    before = engine._actor_cells(actor, origin)
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= reach and engine._line_of_sight_actor_to_actor(actor, c)
            and engine.grid.distance_between_cell_sets(before, engine._actor_cells(c)) * engine.grid.square_size_ft > reach}
    if not foes:
        return
    intent = getattr(engine, "_active_intent", None)
    actor.turn_flags["_round_immovable_strike"] = _stamp(engine)  # asked once a turn: a declined strike is not offered again
    picked = ask(engine, intent, checkpoint_id(engine, "immovable_god", actor.entity_id), actor, "choice:needle.immovable_god", list(foes),
                 labels={k: c.display_name for k, c in foes.items()}, allow_decline=True, target_id=actor.entity_id, name="Immovable God",
                 prompt="Immovable God: make an unarmed strike against a creature that came within your reach?")
    if not picked or picked[0] not in foes:
        return
    foe = foes[picked[0]]
    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [foe], foe, {}), [attack])


# ------------------------------------------------------------------------------------------ Sumo Strike and Ring Breaker
@effect("sumo_mark")
def sumo_mark(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_sumo"] = str(row.get("feature") or "")


@effect("sumo_push")
def sumo_push(ctx: Any, row: dict[str, Any]) -> None:
    """Sumo Strike: "Push the target 10 feet. If the target is more than one size larger than you, it makes a Strength saving
    throw. On a failure, push it 10 feet; on a success, 5 feet."."""
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active:
        return
    push = lambda ft: {"type": "forced_movement", "applies_to": "target", "distance_ft": ft, "direction": "away"}
    if te.size_width(ctx, target, "subject", {}) > te.size_width(ctx, ctx.actor, "actor", {}) + 1:
        te.run_effects(ctx, [{"type": "save", "ability": "str", "evidence": "Sumo Strike: Strength saving throw", "on_fail": [push(10)], "on_success": [push(5)]}])
    else:
        te.run_effects(ctx, [push(10)])


@effect("ring_breaker_push")
def ring_breaker_push(ctx: Any, row: dict[str, Any]) -> None:
    """"push the target up to 20 feet": you choose how far along the line away from you."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    most = int(row.get("up_to") or 5)
    square = ctx.engine.grid.square_size_ft
    options = [str(ft) for ft in range(most, 0, -square)]
    feet = most
    if len(options) > 1:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ring_breaker", target.entity_id), ctx.actor, "choice:needle.ring_breaker_distance",
                     options, labels={o: f"Push it {o} feet" for o in options}, target_id=target.entity_id, name="Ring Breaker",
                     prompt=f"Ring Breaker: how far do you push {target.display_name} (up to {most} feet)?")
        feet = int(picked[0]) if picked and picked[0] in options else most
    ctx.damage_cache["_ring_breaker_from"] = (target.position.x, target.position.y)
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


@effect("ring_breaker_step_in")
def ring_breaker_step_in(ctx: Any, row: dict[str, Any]) -> None:
    """"you may enter its former space" (only if it actually left, and the space is legal for you)."""
    from ..gate2_runtime_models import Position
    from .needle import ask, checkpoint_id
    from .rider_movement import step

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    spot = ctx.damage_cache.get("_ring_breaker_from")
    if spot is None or target is None or not actor.active:
        return
    former = Position(x=spot[0], y=spot[1])
    start = actor.position
    if target.position == former or engine.grid.distance_ft(start, former) > engine.grid.square_size_ft \
            or not engine.grid.placement_legal(former, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "ring_breaker_step", actor.entity_id), actor, "choice:needle.ring_breaker_step", ["enter"],
                 labels={"enter": f"Step into {former.x},{former.y}"}, allow_decline=True, default="decline", target_id=actor.entity_id, name="Ring Breaker",
                 prompt="Ring Breaker: step into the space it was driven from?")
    if not picked:
        return
    engine._resolve_leave_reach(actor, start, former, ctx.intent)  # an ordinary step: it can provoke
    if actor.active and actor.position == start:
        step(engine, actor, [start, former], PREFIX + "ring_breaker")


@hook("collision")
def sumo_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    kind = ctx.damage_cache.get("_sumo")
    if kind not in ("sumo_strike", "ring_breaker") or target is None or not target.active:
        return
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    done = ctx.damage_cache.setdefault("_sumo_collided", [])
    spot = (blocked_at.x, blocked_at.y)
    other = next((c for c in engine.state.actors.values() if c.active and c.entity_id != target.entity_id and spot in engine._actor_cells(c)), None)
    cl = _cl(engine, actor.entity_id)
    dice = {"count": 3, "sides": 8} if kind == "ring_breaker" else {"count": 3 if cl >= 17 else 2 if cl >= 11 else 1, "sides": 6}
    name = "Ring Breaker" if kind == "ring_breaker" else "Sumo Strike"
    hurt = {"type": "damage", "applies_to": "target", "dice": dice, "damage_types": ["bludgeoning"], "evidence": f"{name}: collision"}

    def hit(creature: Any, rows: list[dict[str, Any]]) -> None:
        if creature.active and creature.entity_id not in done:
            done.append(creature.entity_id)
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, {}), rows)

    if other is None:
        note(engine, PREFIX + kind, actor, f"{name}: {target.display_name} slams into a solid surface.", (target.entity_id,))
        hit(target, [hurt])
        from .objects import blocker_at
        obj = blocker_at(engine, blocked_at)  # the object that stopped it, not one sharing its square
        if obj is not None and kind == "sumo_strike":  # Sumo Strike: "both take" -- the map object it hit as well
            from ..gate2_runtime_models import DiceSpec
            from .objects import deal

            roll = engine.roller.roll(DiceSpec(count=dice["count"], sides=dice["sides"], modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{PREFIX}{kind}:object")
            engine._record_roll(roll)
            deal(engine, actor, obj, [(int(roll.total), "BLUDGEONING")], PREFIX + kind)
        return
    note(engine, PREFIX + kind, actor, f"{name}: {target.display_name} is driven into {other.display_name}.", (target.entity_id, other.entity_id))
    if kind == "ring_breaker":
        hit(other, [{"type": "save", "ability": "dex", "evidence": "Ring Breaker: the second creature's Dexterity saving throw",
                     "on_fail": [hurt, {"type": "condition", "applies_to": "target", "condition": "prone"}],
                     "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["bludgeoning"]}]}])
        return
    hit(target, [hurt])
    hit(other, [{"type": "save", "ability": "dex", "evidence": "Sumo Strike: the second creature's Dexterity saving throw", "on_fail": [hurt], "on_success": []}])
