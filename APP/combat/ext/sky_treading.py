"""Sky-Treading Tendon School riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Sky-Treading Tendon School (Thousand-Mile Legs, Heaven-Kicking Leg, Pursuit Without
Horizon, Body Crosses Heaven and their Normalized Procedures). Owned rows: ``{"type": "path_passive", "kind": "sky_treading",
"role": "legs" | "kick" | "crosses"}``; Pursuit Without Horizon's Reaction runs ``pursuit_without_horizon``.

"Moved this turn" is the creature's own willing movement since the current turn began (forced movement and teleports do not
count), so a Reaction's move on another creature's turn counts toward a strike later in that same turn.

Thousand-Mile Legs   Walking Speed + 10; calculated jumps tripled without a running start. Stomping Step supplies temporary
                     liquid/wall support using native movement, expiring into ordinary falls, and makes ordinary difficult terrain cost nothing extra until the end of
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
Tread the Empty Sky  1 Stamina without an action while airborne on your turn: flight/Hover for that turn, then suspension
                     through your next turn. The existing turn_start_choice hook offers renewal to the suspended owner
                     through Needle's shared choice transport before movement; the hold's choice_owner marker enrolls
                     manual owners during AI turns. Automatic renewal uses only the owner's airborne state and Stamina.
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
    from .movement_clock import willing_distance
    from ..movement_steps import context
    total = int(willing_distance(engine, actor))
    # A native route records its final path after its per-step reactions. The
    # public checkpoint exposes only feet already traversed, never its plan.
    progress = context(engine, actor)
    if progress and not progress.get('forced'):
        total += max(0, int(progress.get('travelled_ft') or 0))
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


@hook('jump_run_start_free')
def thousand_mile_start(engine: Any, actor: Any) -> bool | None:
    return True if 'legs' in _rows(engine, actor) else None


@hook('jump_steps_multiplier')
def thousand_mile_jumps(engine: Any, actor: Any) -> int | None:
    return 3 if 'legs' in _rows(engine, actor) else None


def legs_traversing(engine: Any, actor: Any) -> bool:
    """Only the owner's current Stomping Step grants temporary surface support."""
    return ('legs' in _rows(engine, actor) and actor.active
            and any(c.condition_id == LIGHT_FEET and c.source_definition_id == PREFIX + 'thousand_mile_legs'
                    for c in actor.conditions.values()))


@hook('climbing')
def stomping_climb(engine: Any, actor: Any) -> dict[str, Any] | None:
    if legs_traversing(engine, actor):
        return {'climb_speed_ft': int(engine._effective_speed(actor)), 'climb_without_check': 1,
                'climb_terrain_faces': 1}
    return None


@hook('support_surface')
def stomping_support(engine: Any, actor: Any, position: Any) -> bool | None:
    if not legs_traversing(engine, actor):
        return None
    from ..roof_movement import faces
    if faces(engine, actor, position, include_virtual=False):
        return True
    # An authored finite liquid column supplies only its top surface, never air.
    spans = engine.grid.terrain_spans.get('LIQUID', {})
    if any(top == position.z * engine.grid.square_size_ft
           for cell in engine._actor_cells(actor, position)
           for bottom, top in spans.get(cell, ()) if top is not None):
        return True
    return None


@hook("action_completed")
def stomping_step(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Thousand-Mile Legs: after Stomping Step, ordinary difficult terrain costs nothing extra until the end of the turn."""
    if not str(source_definition_id).endswith(STOMPING) or "legs" not in _rows(engine, actor):
        return
    engine._apply_condition(actor, LIGHT_FEET, PREFIX + "thousand_mile_legs", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Thousand-Mile Legs: cross liquids and walls; ordinary difficult terrain costs no extra movement until this turn ends. Fall if unsupported."})


@hook("attack_damage_bonus")
def thousand_mile_damage(ctx: Any, target: Any, effect: Any) -> int | None:
    """Add the once-per-turn PB to the confirmed unarmed strike's own damage packet."""
    engine, actor = ctx.engine, ctx.actor
    if (target is None or "legs" not in _rows(engine, actor)
            or engine.state.current_actor_id != actor.entity_id
            or target.team_id == actor.team_id or not target.active
            or moved_this_turn(engine, actor) < 20):
        return None
    stamp = _stamp(engine)
    if actor.turn_flags.get("_round_thousand_mile") == stamp:
        return None
    actor.turn_flags["_round_thousand_mile"] = stamp
    actor.turn_flags["_round_thousand_mile_pending"] = ctx.source
    return int(actor.proficiency_bonus or 2)


@hook("after_hit")
def tendon_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None:
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
    if "crosses" in rows and mine and moved >= 30 and target.active and target.team_id != actor.team_id and actor.turn_flags.get("_round_crosses_heaven") != stamp \
            and _pay(ctx, target, rows["crosses"], 2, "_round_crosses_heaven", "Body Crosses Heaven",
                     "Spend 2 Stamina: + 4d8 Force, then a Strength save or be hurled up to 30 feet and knocked Prone"):
        _crosses(sub, rows["crosses"], target)
    if "kick" in rows and moved >= 10 and target.active and target.team_id != actor.team_id and actor.turn_flags.get("_round_heaven_kick") != stamp \
            and _pay(ctx, target, rows["kick"], 1, "_round_heaven_kick", "Heaven-Kicking Leg",
                     "Spend 1 Stamina: a Strength save or you kick it up to 15 feet and it loses its Reactions"):
        te.run_effects(sub, [{"type": "save", "ability": "str", "advantage_if_larger": 2, "evidence": "Heaven-Kicking Leg: Strength saving throw",
                              "on_fail": [{"type": "heaven_kick_move"},
                                          {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                              "on_success": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}]}])


@hook('attack_completed')
def thousand_mile_followup(engine: Any, notice: Any, intent: Any) -> None:
    """The optional step follows the complete hit, including its attached damage."""
    actor = engine.state.actors[notice.attacker_id]
    if ('legs' not in _rows(engine, actor) or not notice.hit or notice.kind != 'unarmed'
            or actor.turn_flags.get('_round_thousand_mile') != _stamp(engine)
            or actor.turn_flags.get('_round_thousand_mile_pending') != notice.source_id):
        return
    actor.turn_flags.pop('_round_thousand_mile_pending', None)
    from .states import context
    ctx = context(engine, actor, notice.source_id, [engine.state.actors[notice.target_id]])
    ctx.intent = intent
    if actor.active:
        _free_move(ctx, actor, 5, 'choice:needle.thousand_mile_step', 'Thousand-Mile Legs')


def _free_move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id, cell_id
    from ..granted_movement import routes, resolve_path
    from ..roof_movement import routes as climbs
    from ..flight import jumps, horizontal_jumps
    from ..posture import allows_jumping

    found = routes(ctx.engine, mover, feet)
    paths = {cell_id(cell): route for cell, route in found.items()}
    other_modes = [climbs(ctx.engine, mover, grant_ft=feet)]
    if allows_jumping(mover):
        other_modes += [jumps(ctx.engine, mover, {}, grant_ft=feet), horizontal_jumps(ctx.engine, mover, grant_ft=feet)]
    for offered in other_modes:
        for cell, route in offered.items():
            key = cell_id(cell)
            if key in paths and paths[key][2] != route[2]:
                key += ':' + route[2]
            if key not in paths or route[1] < paths[key][1]:
                paths[key] = route
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sky_step", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: f"{route[2].title()} to {route[0][-1].x},{route[0][-1].y} at {route[0][-1].z * ctx.engine.grid.square_size_ft} ft. altitude"
                                                               for k, route in paths.items()}, target_id=mover.entity_id,
                 prompt=f"{name}: after {ctx.action.display_name} hits {ctx.target.display_name}, move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        path, cost, mode = paths[picked[0]]
        resolve_path(ctx.engine, mover, path, PREFIX + 'thousand_mile_legs', feet=feet,
                     intent=ctx.intent, provokes=False, mode=mode)


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

    # This paid feature owns its riders even when a plain strike triggered it.
    # The public named-source context retains the triggering damage packet.
    ctx = ctx.with_source(row['feature_id'])
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
    # This printed push uses a route helper instead of typed_executor's
    # forced_movement effect. Use the shared bonus seam for consistent rules.
    from .. import ext
    bonuses = ext.run("forced_movement_bonus", ctx, target, {"direction": "away"})
    feet += sum(int(value) for value in bonuses if value is not None)
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


TREAD = PREFIX + 'tread_the_empty_sky'
TREAD_HOLD = 'condition:typed.sky_tread'


@hook('flight')
def sky_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    # Incapacitated creatures remain conscious. This benefit ends with
    # consciousness; native flight prohibitions are applied by flight.profile.
    conscious = actor.active and actor.current_hp > 0 and actor.life_state in {None, 'CONSCIOUS'} and not any(
        c.condition_id.endswith('unconscious') for c in actor.conditions.values())
    if not conscious:
        return None
    if 'crosses' in _rows(engine, actor):
        return {'fly_speed_ft': max(0, int(engine._effective_speed(actor))), 'flight_hover': 1}
    held = next((c for c in actor.conditions.values() if c.condition_id == TREAD_HOLD), None)
    if held:
        active_turn = held.data['turn'] == _stamp(engine)
        return {'fly_speed_ft': max(0, int(engine._effective_speed(actor))) if active_turn else 0,
                'flight_hover': int(active_turn), 'flight_suspended': 1}
    return None


def _tread_ready(engine: Any, actor: Any) -> bool:
    from ..falling import supported
    from ..flight import profile
    return ('tread' in _rows(engine, actor) and actor.active and actor.current_hp > 0
            and engine.state.current_actor_id == actor.entity_id
            and not supported(engine, actor) and actor.resources.get('resource:core.stamina', 0) >= 1
            and actor.turn_flags.get('_round_sky_tread') != _stamp(engine)
            and actor.turn_flags.get('_round_sky_tread_closed') != _stamp(engine)
            and profile(engine, actor).can_ascend
            and not any(c.data.get('flight_disabled') or c.data.get('no_actions') for c in actor.conditions.values()))


@effect('sky_tread')
def activate_tread(ctx: Any, row: dict[str, Any]) -> None:
    from .condition_ownership import remove_instance
    engine, actor = ctx.engine, ctx.actor
    if not _tread_ready(engine, actor):
        return
    engine._spend_resource(actor, 'resource:core.stamina', 1, TREAD)
    actor.turn_flags['_round_sky_tread'] = _stamp(engine)
    previous = [c.instance_id for c in actor.conditions.values() if c.condition_id == TREAD_HOLD]
    engine._apply_condition(actor, TREAD_HOLD, TREAD, actor.entity_id, expires_on='UNTIL_REMOVED',
                           data={'turn': _stamp(engine), 'round': int(engine.state.round_number), 'choice_owner': 1,
                                 'label': 'Tread the Empty Sky: flight this turn; suspended until your next turn ends'})
    for instance in previous:
        remove_instance(engine, actor, instance, TREAD)


@hook('compile_actions')
def tread_button(info: dict[str, Any]) -> list[Any] | None:
    if TREAD not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=TREAD, display_name='Tread the Empty Sky (1 Stamina, no action)',
        owner_id=info['actor_id'], economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'sky_tread_button': True, 'player_only': True, 'typed': {'source': TREAD,
            'effects': [{'type': 'sky_tread'}], 'numbers': info['numbers'], 'riders': []}})]


@hook('candidate_allowed')
def tread_button_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.parameters.get('sky_tread_button'):
        return _tread_ready(engine, actor)
    return None


@hook('falling')
def tread_before_fall(engine: Any, actors: Any, intent: Any) -> None:
    from .needle import ask, checkpoint_id
    from .states import context
    for actor in actors:
        if not _tread_ready(engine, actor):
            continue
        if ask(engine, intent, checkpoint_id(engine, 'sky_tread_fall', actor.entity_id), actor,
               'choice:needle.sky_tread', ['tread'], allow_decline=True, preferred=['tread'],
               labels={'tread': 'Spend 1 Stamina: fly and Hover this turn; remain suspended'},
               prompt=f'Tread the Empty Sky: {actor.display_name} is airborne. Spend 1 Stamina to stay aloft?'):
            ctx = context(engine, actor, TREAD, [actor]);ctx.intent = intent
            activate_tread(ctx, {})


@hook('turn_start_choice')
def tread_renewal(engine: Any, actor: Any) -> None:
    """Offer the suspended owner renewed flight before movement or expiry.

    The existing owner-scoped transport asks manual/Ask-me owners even when
    another actor's end-turn intent starts this turn. Automatic owners prefer
    staying aloft based only on their own suspension and available Stamina.
    Declining leaves the button available until the printed turn-end deadline.
    """
    if (not any(c.condition_id == TREAD_HOLD and c.data['turn'] != _stamp(engine)
                for c in actor.conditions.values()) or not _tread_ready(engine, actor)):
        return
    from .needle import ask, checkpoint_id
    from .states import context
    intent = getattr(engine, '_active_intent', None)
    if ask(engine, intent, checkpoint_id(engine, 'sky_tread_renewal', actor.entity_id), actor,
           'choice:needle.sky_tread', ['tread'], allow_decline=True, preferred=['tread'],
           name='Tread the Empty Sky', feature_id=TREAD, target_id=actor.entity_id,
           labels={'tread': 'Spend 1 Stamina: fly and Hover this turn; stay suspended until your next turn ends'},
           prompt=f'Tread the Empty Sky: {actor.display_name}\'s turn is starting while suspended. '
                  'Spend 1 Stamina, without an action, to renew flight and Hover this turn? '
                  'If you remain unsupported without renewing, you fall at the end of this turn.',
           prompt_context={'cost': '1 Stamina', 'paying_pool': STAMINA}):
        ctx = context(engine, actor, TREAD, [actor]); ctx.intent = intent
        activate_tread(ctx, {})


@hook('turn_end')
def tread_ends(engine: Any, actor: Any) -> None:
    if 'tread' in _rows(engine, actor):
        actor.turn_flags['_round_sky_tread_closed'] = _stamp(engine)
    from .condition_ownership import remove_instance
    for c in list(actor.conditions.values()):
        if c.condition_id == TREAD_HOLD and c.data['turn'] != _stamp(engine):
            remove_instance(engine, actor, c.instance_id, TREAD)


@hook('opportunity_allowed')
def tread_below(engine: Any, reactor: Any, mover: Any) -> bool | None:
    if any(c.condition_id == TREAD_HOLD and c.data['turn'] == _stamp(engine) for c in mover.conditions.values()):
        if (mover.position.z - reactor.position.z - ctx_height(engine, reactor)) * 5 >= 10:
            return False
    return None


def ctx_height(engine: Any, actor: Any) -> int:
    return max(engine._footprint(actor).width_cells, engine._footprint(actor).height_cells) - 1
