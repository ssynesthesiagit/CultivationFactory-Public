"""Sky-Treading Tendon School riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Sky-Treading Tendon School (Thousand-Mile Legs, Heaven-Kicking Leg, Pursuit Without
Horizon, Body Crosses Heaven and their Normalized Procedures). Owned rows: ``{"type": "path_passive", "kind": "sky_treading",
"role": "legs" | "kick" | "crosses"}``; Pursuit Without Horizon's Reaction runs ``pursuit_without_horizon``.

"Moved this turn" is the creature's own willing movement since the current turn began (forced movement and teleports do not
count), so a Reaction's move on another creature's turn counts toward a strike later in that same turn.

Thousand-Mile Legs   Speed + 10; using Stomping Step makes ordinary (map) difficult terrain cost nothing extra until the end of
                     the turn; once during each of your turns, an unarmed hit after moving 20+ feet deals + Proficiency Bonus
                     (the attack's type) and then you may move 5 feet without provoking (asked).
Heaven-Kicking Leg   once per turn, an unarmed hit after moving 10+ feet this turn: 1 Stamina (asked), Strength save
                     (Advantage for a creature more than two sizes larger). Failure: you move it up to 15 feet to an open
                     space you can see (asked) and it cannot take Reactions until the start of its next turn; success: pushed
                     5 feet away.
Pursuit Without Horizon  after the Reaction (2 Stamina, once a round) answers a hostile creature's willing move of 10+ feet within
                     60 feet: move up to your Speed without provoking to a space closer to it (asked), then one unarmed strike
                     against it if it is within reach (a Granted Attack).
Body Crosses Heaven  once during each of your turns, an unarmed hit after moving 30+ feet: 2 Stamina (asked) for + 4d8 Force and a
                     Strength save. Failure: pushed up to 30 feet in a straight line you choose (asked) and Prone; success:
                     pushed 10 feet away. A push cut short by anything but a creature is a collision: the target takes
                     Proficiency Bonus Bludgeoning, and a map object there takes the same (combat/ext/objects.py deal).
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.sky_treading_tendon_school.feature."
STAMINA = "resource:core.stamina"
STOMPING = "body_refining.feature.stomping_step"
LIGHT_FEET = "condition:typed.ignore_difficult"
# The eight straight lines a push can take (Body Crosses Heaven: "in a direction you choose ... along a direct trajectory").
LINES = {"north": (0, -1), "north-east": (1, -1), "east": (1, 0), "south-east": (1, 1),
         "south": (0, 1), "south-west": (-1, 1), "west": (-1, 0), "north-west": (-1, -1)}


def _rows(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    return {str(row.get("role")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "sky_treading"}


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def moved_this_turn(engine: Any, actor: Any) -> int:
    """Feet of ``actor``'s own willing movement since the current turn began (no teleports, no forced movement)."""
    total = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("teleport"):
            total += max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
    return total


def _pay(ctx: Any, target: Any, row: dict[str, Any], cost: int, flag: str, name: str, label: str) -> bool:
    """Ask whether to spend ``cost`` Stamina on ``name``; spend it and mark the turn's use when accepted."""
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    if int(actor.resources.get(STAMINA, 0) or 0) < cost:
        return False
    key = row["feature_id"].rsplit(".", 1)[-1]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, key, target.entity_id), actor, "choice:needle." + key, ["use"],
                 labels={"use": label}, allow_decline=True, default="decline", target_id=target.entity_id, name=name,
                 prompt=f"{name}: {ctx.action.display_name} hit {target.display_name} after you moved. Spend {cost} Stamina?")
    if not picked:
        return False
    engine._spend_resource(actor, STAMINA, cost, row["feature_id"])
    actor.turn_flags[flag] = _stamp(engine)
    return True


def _kinds(ctx: Any) -> list[str]:
    weapon = ctx.typed.get("weapon") or {}
    return [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]


@hook("speed")
def legs_speed(engine: Any, actor: Any) -> int | None:
    return 10 if "legs" in _rows(engine, actor) else None


@hook("action_completed")
def stomping_step(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Thousand-Mile Legs: after Stomping Step, ordinary difficult terrain costs nothing extra until the end of the turn."""
    if not str(source_definition_id).endswith(STOMPING) or "legs" not in _rows(engine, actor):
        return
    engine._apply_condition(actor, LIGHT_FEET, PREFIX + "thousand_mile_legs", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Thousand-Mile Legs: ordinary difficult terrain costs no extra movement this turn"})


@hook("after_hit")
def tendon_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None or not target.active or target.team_id == actor.team_id:
        return
    rows = _rows(engine, actor)
    if not rows:
        return
    from .. import typed_executor as te

    moved = moved_this_turn(engine, actor)
    mine = engine.state.current_actor_id == actor.entity_id
    stamp = _stamp(engine)
    dc = next((int(row["save_dc"]) for row in rows.values() if row.get("save_dc")), int(ctx.numbers.get("save_dc") or 10))
    sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': {**ctx.numbers, 'pb': int(actor.proficiency_bonus or 2), 'save_dc': dc}}, damage_cache={})
    legs = "legs" in rows and mine and moved >= 20 and actor.turn_flags.get("_round_thousand_mile") != stamp
    if legs:
        actor.turn_flags["_round_thousand_mile"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2), "damage_types": _kinds(ctx),
                              "evidence": "Thousand-Mile Legs: + Proficiency Bonus"}])
    if "crosses" in rows and mine and moved >= 30 and target.active and actor.turn_flags.get("_round_crosses_heaven") != stamp \
            and _pay(ctx, target, rows["crosses"], 2, "_round_crosses_heaven", "Body Crosses Heaven",
                     "Spend 2 Stamina: + 4d8 Force, then a Strength save or be hurled up to 30 feet and knocked Prone"):
        _crosses(sub, rows["crosses"], target)
    if "kick" in rows and moved >= 10 and target.active and actor.turn_flags.get("_round_heaven_kick") != stamp \
            and _pay(ctx, target, rows["kick"], 1, "_round_heaven_kick", "Heaven-Kicking Leg",
                     "Spend 1 Stamina: a Strength save or you kick it up to 15 feet and it loses its Reactions"):
        te.run_effects(sub, [{"type": "save", "ability": "str", "advantage_if_larger": 2, "evidence": "Heaven-Kicking Leg: Strength saving throw",
                              "on_fail": [{"type": "heaven_kick_move"},
                                          {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                              "on_success": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}]}])
    if legs and actor.active:
        _free_move(ctx, actor, 5, "choice:needle.thousand_mile_step", "Thousand-Mile Legs")


def _free_move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sky_step", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "thousand_mile_legs")


@effect("heaven_kick_move")
def heaven_kick_move(ctx: Any, row: dict[str, Any]) -> None:
    """Heaven-Kicking Leg's failed save: you choose an open space within 15 feet of it that you can see; it travels there."""
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import forced_route

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    found = engine.grid.reachable(target.position, movement_ft=15, occupied_cells=engine._occupied_cells_except(target.entity_id),
                                  difficult_cells=set(), footprint=engine._footprint(target))
    paths = {cell_id(cell): path for cell, (path, cost) in found.items() if cell != target.position and engine._line_of_sight_actor_to_cell(actor, cell)}
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "heaven_kick", target.entity_id), actor, "choice:needle.heaven_kick_destination", sorted(paths),
                 labels={k: "Kick it to " + k.removeprefix("cell:") for k in paths}, allow_decline=True, default="decline", target_id=target.entity_id,
                 prompt=f"Heaven-Kicking Leg: where do you kick {target.display_name} (up to 15 feet)?")
    if picked and picked[0] in paths:
        forced_route(engine, target, paths[picked[0]], PREFIX + "heaven_kicking_leg", actor)


# ---------------------------------------------------------------------------------------------- Body Crosses Heaven
def _crosses(ctx: Any, row: dict[str, Any], target: Any) -> None:
    from .. import typed_executor as te

    te.run_effects(ctx, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["force"],
                          "evidence": "Body Crosses Heaven: + 4d8 Force"},
                         {"type": "save", "ability": "str", "evidence": "Body Crosses Heaven: Strength saving throw",
                          "on_fail": [{"type": "crosses_heaven_hurl", "feet": 30}, {"type": "condition", "applies_to": "target", "condition": "prone"}],
                          "on_success": [{"type": "crosses_heaven_hurl", "feet": 10, "away": True}]}])


def _line(engine: Any, start: Any, direction: tuple[int, int], feet: int) -> list[Any]:
    from ..gate2_runtime_models import Position

    out, x, y = [start], start.x, start.y
    for _ in range(feet // engine.grid.square_size_ft):
        x, y = x + direction[0], y + direction[1]
        if not (0 <= x < engine.grid.width and 0 <= y < engine.grid.height):
            break
        out.append(Position(x=x, y=y))
    return out


def _away(actor: Any, target: Any) -> tuple[int, int]:
    dx = (target.position.x > actor.position.x) - (target.position.x < actor.position.x)
    dy = (target.position.y > actor.position.y) - (target.position.y < actor.position.y)
    return (dx, dy) if dx or dy else (0, -1)


@effect("crosses_heaven_hurl")
def crosses_heaven_hurl(ctx: Any, row: dict[str, Any]) -> None:
    """The push: failure, up to 30 feet along a straight line you choose (asked: a square on one of the eight lines);
    success, 10 feet directly away. Stopped short by anything but a creature, it collides."""
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import forced_route

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    feet = int(row.get("feet") or 10)
    if row.get("away"):
        path = _line(engine, target.position, _away(actor, target), feet)
    else:
        options = {}
        for name, direction in LINES.items():
            line = _line(engine, target.position, direction, feet)
            for i in range(1, len(line)):
                options[cell_id(line[i])] = (line[: i + 1], f"Hurl it {name} to {line[i].x},{line[i].y} ({i * engine.grid.square_size_ft} ft)")
        if not options:
            return
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "crosses_heaven", target.entity_id), actor, "choice:needle.crosses_heaven_direction",
                     sorted(options), labels={k: v[1] for k, v in options.items()}, allow_decline=True, default="decline", target_id=target.entity_id,
                     prompt=f"Body Crosses Heaven: {target.display_name} failed its save. Choose a straight line and how far to hurl it (up to {feet} feet); "
                            "it stops at the first wall or creature, and slamming into a wall or object hurts.")
        if not picked or picked[0] not in options:
            return
        path = options[picked[0]][0]
    if len(path) < 2:
        return
    forced_route(engine, target, path, PREFIX + "body_crosses_heaven", actor)
    if not target.active or target.position == path[-1]:
        return
    try:
        stopped = path.index(target.position)
    except ValueError:
        return  # something else moved it off the line
    blocked_at = path[stopped + 1]
    if engine.grid.step_legal(target.position, blocked_at, occupied_cells=engine._occupied_cells_except(target.entity_id), footprint=engine._footprint(target)):
        return  # shortened by a reaction, not stopped by anything
    if any(c.active and c.entity_id != target.entity_id and (blocked_at.x, blocked_at.y) in engine._actor_cells(c) for c in engine.state.actors.values()):
        return  # "Another creature is not a solid surface for this clause"
    _collide(ctx, target, blocked_at)


def _collide(ctx: Any, target: Any, blocked_at: Any) -> None:
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    pb = int(actor.proficiency_bonus or 2)
    note(engine, PREFIX + "body_crosses_heaven", actor, f"Body Crosses Heaven: {target.display_name} slams into a solid surface.", (target.entity_id,))
    te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                   [{"type": "damage", "applies_to": "target", "flat": pb, "damage_types": ["bludgeoning"], "evidence": "Body Crosses Heaven: collision"}])
    from .objects import blocker_at
    obj = blocker_at(engine, blocked_at)  # the object that stopped it, not one sharing its square
    if obj is not None:
        from .objects import deal

        deal(engine, actor, obj, [(pb, "BLUDGEONING")], PREFIX + "body_crosses_heaven")


# ------------------------------------------------------------------------------------------- Pursuit Without Horizon
def _unarmed_strikes(engine: Any, actor: Any, target: Any) -> dict[str, Any]:
    from ..typed_reactions import attack_reaches

    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or ".natural." not in action.source_definition_id or (action.parameters or {}).get("player_only"):
            continue
        if "#" in action.source_definition_id or not any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                                         for e in typed.get("effects") or []):
            continue
        if engine._distance_actor_to_actor(actor, target) <= int(action.range_ft or 5) or attack_reaches(engine, actor, target, {"attack_kind": "unarmed"}):
            out[action.source_definition_id] = action
    return out


@effect("pursuit_without_horizon")
def pursuit_without_horizon(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    engine, actor, other = ctx.engine, ctx.actor, ctx.target
    if other is None or not other.active:
        return
    now = engine._distance_actor_to_actor(actor, other)
    paths = {k: p for k, p in routes(engine, actor, int(engine._effective_speed(actor))).items() if engine.grid.distance_ft(p[-1], other.position) < now}
    if paths:
        nearest = min(paths, key=lambda k: (engine.grid.distance_ft(paths[k][-1], other.position), len(paths[k]), k))
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "pursuit", actor.entity_id), actor, "choice:needle.pursuit_without_horizon", sorted(paths),
                     labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, preferred=[nearest], target_id=actor.entity_id,
                     name="Pursuit Without Horizon",
                     prompt=f"Pursuit Without Horizon: chase {other.display_name}. Move up to your Speed without provoking, ending closer to it.")
        chosen = picked[0] if picked and picked[0] in paths else nearest
        step(engine, actor, paths[chosen], PREFIX + "pursuit_without_horizon")
    else:
        note(engine, PREFIX + "pursuit_without_horizon", actor, f"Pursuit Without Horizon: {actor.display_name} cannot get any closer to {other.display_name}.")
        return
    if not actor.active or not other.active or engine.state.terminal_result is not None:
        return
    strikes = _unarmed_strikes(engine, actor, other)
    if not strikes:
        return
    key = next(iter(strikes))
    if len(strikes) > 1:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "pursuit_strike", other.entity_id), actor, "choice:needle.pursuit_strike", sorted(strikes),
                     labels={k: a.display_name for k, a in strikes.items()}, target_id=other.entity_id, name="Pursuit Without Horizon",
                     prompt=f"Pursuit Without Horizon: which unarmed strike against {other.display_name}?")
        key = picked[0] if picked and picked[0] in strikes else key
    action = strikes[key]
    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    te.run_effects(te.Context(engine, actor, action, ctx.intent, {**typed, "effects": [attack], "granted_attack": True}, [other], other, {}), [attack])
