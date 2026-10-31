"""Vermilion Gate Guardian Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Vermilion Gate Guardian Body (Guarded Threshold, the five features and their Normalized
Procedures). Owned rows: ``{"type": "path_passive", "kind": "gate", "role": "guardian" | "shelter" | "twin" | "worlds"}``; Heaven's
Closed Gate's action runs ``closed_gate``; Shelter Behind the Gate's Reaction is a generic ally_forced_moved row.

Guarded Threshold   at the start of your turn (asked: which way it runs, then its middle square) a 15-foot straight line with a
                    square within 5 feet of you, until the start of your next turn (two with Twin Guardian Posts). It is drawn as
                    a zone whose squares are difficult terrain for hostile creatures. A creature crosses when a step of its path
                    goes from one side of the segment to the other (``crossings``; the zone code's own line test is unbounded).
Guardian at the Gate  when a hostile creature's move (willing or forced) crosses your threshold (asked; your Reaction, once per
                    move): it is put back on the square before the line, you make one unarmed strike or melee weapon attack
                    (a Granted Attack); a hit ends its move there (Speed 0 until the end of the turn, no Reactions until its next
                    turn; Twin Guardian Posts: one more asked result), a miss lets it finish the move.
Shelter Behind the Gate  an ally within 5 feet of your threshold: + 1 AC (as cover) against a ranged attack from the other side,
                    Advantage on a save against being pushed or pulled from the other side; the Reaction row answers only for an
                    ally within 10 feet of a threshold (hook ally_row_allowed).
Threshold Between Worlds  a hostile creature's own teleport across your threshold needs a Cultivation Check against your
                    Cultivation Save DC (hook teleport_check); a ranged attack across it gives a target within 5 feet of it
                    Half Cover.
Heaven's Closed Gate  a 30-foot circle round the square you stand on, for a minute: a hostile creature moving across its edge makes
                    a Strength or Charisma save (its better one): failure puts it back outside (or inside) at the edge, Speed 0 for
                    the turn and 4d8 Force; success lets it through and costs it 5 more feet. Its own teleports across need a
                    Cultivation Check. Ranged attacks from outside give creatures inside Three-Quarters Cover (Half Cover once two
                    of its four posts are destroyed; all four end it). The posts are map objects (AC your Cultivation Save DC,
                    3 x CL Hit Points, immune to Poison and Psychic).
Every hook returns early for a creature without these rows, thresholds or gate.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.vermilion_gate_guardian_body.feature."
THRESHOLDS = "_round_gate_thresholds"      # the owner's thresholds: [[ax, ay, bx, by], ...]
GATE = "_round_closed_gate"                # the owner's Heaven's Closed Gate: {"x", "y", "r", "until", "posts": [ids], "zone": id}
STAMINA = "resource:core.stamina"
ORIENTATIONS = {"east_west": (1, 0), "north_south": (0, 1), "diagonal_down": (1, 1), "diagonal_up": (1, -1)}


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "gate"}


def _row(engine: Any, actor: Any) -> dict[str, Any]:
    return next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("kind") == "gate"), {}) or {}


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _owners(engine: Any) -> list[Any]:
    return [a for a in engine.state.actors.values() if a.active and (a.turn_flags.get(THRESHOLDS) or a.turn_flags.get(GATE))]


# ---------------------------------------------------------------------------------------------------- the geometry
def _side(line: list[int], x: float, y: float) -> int:
    ax, ay, bx, by = line
    value = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
    return (value > 1e-9) - (value < -1e-9)


def _along(line: list[int], x: float, y: float) -> float:
    ax, ay, bx, by = line
    dx, dy = bx - ax, by - ay
    return ((x - ax) * dx + (y - ay) * dy) / float(dx * dx + dy * dy or 1)


def crossings(line: list[int], path: list[tuple[int, int]]) -> int | None:
    """The index of the path square just before the step that takes it to the other side of the segment (a square on the line
    itself counts as not yet across), or None."""
    last_side, last_index = 0, None
    for index, (x, y) in enumerate(path):
        side = _side(line, x, y)
        if side == 0:
            continue
        if last_side and side != last_side:
            px, py = path[last_index]
            mx, my = (px + x) / 2.0, (py + y) / 2.0
            ax, ay, bx, by = line
            slack = 0.5 / max(1.0, ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
            if -slack <= _along(line, mx, my) <= 1 + slack:
                return index - 1
        last_side, last_index = side, index
    return None


def _near_line(line: list[int], x: int, y: int, feet: int, square: int) -> bool:
    ax, ay, bx, by = line
    steps = max(abs(bx - ax), abs(by - ay))
    cells = [(ax + round((bx - ax) * i / steps), ay + round((by - ay) * i / steps)) for i in range(steps + 1)] if steps else [(ax, ay)]
    return any(max(abs(cx - x), abs(cy - y)) * square <= feet for cx, cy in cells)


def _line_cells(line: list[int]) -> list[tuple[int, int]]:
    ax, ay, bx, by = line
    steps = max(abs(bx - ax), abs(by - ay))
    return [(ax + round((bx - ax) * i / steps), ay + round((by - ay) * i / steps)) for i in range(steps + 1)] if steps else [(ax, ay)]


# ---------------------------------------------------------------------------------------------- placing thresholds
def _candidates(engine: Any, owner: Any, orientation: str) -> dict[str, list[int]]:
    from .needle import cell_id
    from ..gate2_runtime_models import Position

    dx, dy = ORIENTATIONS[orientation]
    square = engine.grid.square_size_ft
    out = {}
    for x in range(max(0, owner.position.x - 3), min(engine.grid.width, owner.position.x + 4)):
        for y in range(max(0, owner.position.y - 3), min(engine.grid.height, owner.position.y + 4)):
            line = [x - dx, y - dy, x + dx, y + dy]
            if not all(0 <= cx < engine.grid.width and 0 <= cy < engine.grid.height for cx, cy in _line_cells(line)):
                continue
            if not any(engine._distance_actor_to_cell(owner, Position(x=cx, y=cy)) <= square for cx, cy in _line_cells(line)):
                continue  # "with at least one point within your unarmed reach"
            out[cell_id(Position(x=x, y=y))] = line
    return out


def _place(engine: Any, owner: Any, intent: Any, index: int) -> list[int] | None:
    from .needle import ask, checkpoint_id

    foe = min((c for c in engine.state.actors.values() if c.active and c.team_id != owner.team_id),
              key=lambda c: (engine._distance_actor_to_actor(owner, c), c.entity_id), default=None)
    toward = (0, 0) if foe is None else ((foe.position.x > owner.position.x) - (foe.position.x < owner.position.x),
                                         (foe.position.y > owner.position.y) - (foe.position.y < owner.position.y))
    across = {(1, 0): "north_south", (-1, 0): "north_south", (0, 1): "east_west", (0, -1): "east_west",
              (1, 1): "diagonal_up", (-1, -1): "diagonal_up", (1, -1): "diagonal_down", (-1, 1): "diagonal_down"}.get(toward, "north_south")
    labels = {"east_west": "East to west", "north_south": "North to south", "diagonal_down": "Diagonal (top left to bottom right)",
              "diagonal_up": "Diagonal (bottom left to top right)"}
    picked = ask(engine, intent, checkpoint_id(engine, "threshold_way", owner.entity_id, str(index)), owner, "choice:needle.threshold_orientation",
                 list(labels), labels=labels, preferred=[across], target_id=owner.entity_id, name="Guarded Threshold",
                 prompt=f"Guarded Threshold{' (second)' if index else ''}: which way does the 15-foot line run?")
    orientation = picked[0] if picked and picked[0] in labels else across
    options = _candidates(engine, owner, orientation)
    if not options:
        return None
    from .needle import cell_id
    from ..gate2_runtime_models import Position

    from .map_positions import map_position

    ahead_cell = map_position(engine, owner.position.x + toward[0], owner.position.y + toward[1])
    ahead = cell_id(ahead_cell) if ahead_cell is not None else None
    preferred = [ahead] if ahead in options else [sorted(options)[0]]
    picked = ask(engine, intent, checkpoint_id(engine, "threshold_at", owner.entity_id, str(index)), owner, "choice:needle.threshold_center", sorted(options),
                 labels={k: "Centered on " + k.removeprefix("cell:") for k in options}, preferred=preferred, target_id=owner.entity_id,
                 name="Guarded Threshold", prompt="Guarded Threshold: which square is the middle of the line?")
    return options.get(picked[0] if picked and picked[0] in options else preferred[0])


def _clear(engine: Any, owner: Any) -> None:
    from .. import zones

    for zone in list(engine.state.zones.values()):
        if zone.active and zone.owner_id == owner.entity_id and (zone.trigger_profile or {}).get("gate_threshold"):
            zones.remove(engine, zone, "REPLACED")
    owner.turn_flags.pop(THRESHOLDS, None)


def _draw(engine: Any, owner: Any, line: list[int], index: int) -> None:
    from .. import zones
    from ..gate2_runtime_models import Position, ZoneState

    cells = tuple(Position(x=x, y=y) for x, y in _line_cells(line))
    zone_id = f"zone:gate:{owner.entity_id}:{engine.state.event_sequence + 1}:{index}"
    zone = ZoneState(zone_id=zone_id, source_definition_id=PREFIX + "guardian_at_the_gate", owner_id=owner.entity_id, center=cells[len(cells) // 2],
                     radius_cells=0, affected_cells=cells, concentration_link=False, duration_rounds=1, created_round=engine.state.round_number,
                     trigger_profile={"kind": zones.KIND, "name": "Guarded Threshold", "terrain": [], "difficult": "hostile", "obscured": None,
                                      "color": "#c0392b", "follows_owner": False, "shape": "painted", "size_ft": 5, "triggers": [], "talents": [],
                                      "inside": [], "visual": {"material": "sealed"}, "gate_threshold": True, "numbers": {}})
    engine.state.zones[zone_id] = zone
    engine._append_event("ZONE_CREATED", PREFIX + "guardian_at_the_gate", actor_id=owner.entity_id, payload={"zone": zone.model_dump(mode="json")})


@hook("turn_start_choice")
def place_thresholds(engine: Any, actor: Any) -> None:
    roles = _roles(engine, actor)
    if "guardian" not in roles or not actor.active:
        return
    intent = _intent(engine)
    _clear(engine, actor)
    lines = []
    for index in range(2 if "twin" in roles else 1):
        line = _place(engine, actor, intent, index)
        if line is not None:
            lines.append(line)
            _draw(engine, actor, line, index)
    actor.turn_flags[THRESHOLDS] = lines


# -------------------------------------------------------------------------------------------- Guardian at the Gate
def _melee_attacks(engine: Any, owner: Any, target: Any) -> dict[str, Any]:
    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != owner.entity_id or str(getattr(action.economy, "value", action.economy)) != "ACTION" or typed.get("range_ft") \
                or (action.parameters or {}).get("player_only") or ("#" in action.source_definition_id and "#integrated" not in action.source_definition_id):
            continue
        attack = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
        if attack is None or attack.get("attack_kind") not in ("unarmed", "weapon"):
            continue
        if engine._distance_actor_to_actor(owner, target) <= int(action.range_ft or 5):
            out[action.source_definition_id] = action
    return out


def _put(engine: Any, mover: Any, cell: tuple[int, int], source: str) -> None:
    from ..gate2_runtime_models import Position

    before = mover.position
    target = Position(x=cell[0], y=cell[1])
    if target == before:
        return
    mover.position = target
    engine._append_event("MOVEMENT_COMMITTED", source, actor_id=mover.entity_id,
                         payload={"destination": target.model_dump(mode="json"), "path": [before.model_dump(mode="json"), target.model_dump(mode="json")],
                                  "cost_ft": 0, "forced": True, "placed": True})


def _guardian(engine: Any, owner: Any, mover: Any, path: list[tuple[int, int]], index: int) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    if not owner.reaction_available:
        return
    final = (mover.position.x, mover.position.y)
    before = path[index]
    occupied = {c for other in engine.state.actors.values() if other.active and other.entity_id != mover.entity_id for c in engine._actor_cells(other)}
    if before in occupied:
        return
    from ..gate2_runtime_models import Position

    projected = mover.model_copy(update={"position": Position(x=before[0], y=before[1])})
    attacks = _melee_attacks(engine, owner, projected)  # "before it completes the crossing"
    if not attacks:
        return
    intent = _intent(engine)
    labels = {k: a.display_name for k, a in attacks.items()}
    picked = ask(engine, intent, checkpoint_id(engine, "guardian_at_the_gate", mover.entity_id), owner, "choice:needle.guardian_at_the_gate", list(labels),
                 labels=labels, allow_decline=True, default="first", preferred=[k for k in labels if ".natural." in k][:1] or list(labels)[:1],
                 target_id=mover.entity_id, name="Guardian at the Gate",
                 prompt=f"Guardian at the Gate: {mover.display_name} crosses your threshold. Reaction: strike it before it gets through?")
    if not picked or picked[0] not in attacks:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, PREFIX + "guardian_at_the_gate", independent=True):
        owner.reaction_available = False
        engine._append_event("REACTION_RESOLVED", PREFIX + "guardian_at_the_gate", actor_id=owner.entity_id, target_ids=(mover.entity_id,),
                             payload={"checkpoint": "THRESHOLD_CROSSED"})
        _put(engine, mover, before, PREFIX + "guardian_at_the_gate")
        action = attacks[picked[0]]
        typed = (action.parameters or {}).get("typed") or {}
        attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
        attack.update(count=1, granted_attack_root=True)
        hits_before = len([e for e in engine.events if e.event_type == "ATTACK_ROLLED"])
        te.run_effects(te.Context(engine, owner, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [mover], mover, {}), [attack])
        rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"][hits_before:]
        hit = any((e.payload or {}).get("provisional_hit") for e in rolled if e.actor_id == owner.entity_id)
        if not mover.active:
            return
        if not hit:
            _put(engine, mover, final, PREFIX + "guardian_at_the_gate")  # "On a miss, the crossing continues"
            return
        sub = te.Context(engine, owner, action, intent, typed, [mover], mover, {})
        te.run_effects(sub, [{"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN"},
                             {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
        mover.movement_remaining_ft = 0
        if "twin" in _roles(engine, owner) and mover.active:
            _twin_result(engine, owner, mover, sub, intent)


def _twin_result(engine: Any, owner: Any, mover: Any, sub: Any, intent: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    labels = {"push": "Push it 10 feet away from the threshold", "prone": "Knock it Prone", "force": "+ 2d8 Force",
              "mark": "Mark it: Disadvantage on attacks against anyone but you until the start of your next turn"}
    picked = ask(engine, intent, checkpoint_id(engine, "twin_posts", mover.entity_id), owner, "choice:needle.twin_guardian_posts", list(labels), labels=labels,
                 allow_decline=True, target_id=mover.entity_id, name="Twin Guardian Posts", prompt="Twin Guardian Posts: choose one additional result.")
    choice = picked[0] if picked and picked[0] in labels else None
    if choice == "push":
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "prone":
        te.run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "prone"}])
    elif choice == "force":
        te.run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["force"]}])
    elif choice == "mark":
        engine._apply_condition(mover, "condition:typed.gate_marked", PREFIX + "twin_guardian_posts", owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Marked by {owner.display_name}: Disadvantage on attacks against anyone else",
                                      "rule": {"attacks_others_have": "DISADVANTAGE"}})


@hook("event")
def threshold_crossed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not mover.active or payload.get("teleport") or payload.get("placed"):
        return
    path = [(int(p["x"]), int(p["y"])) for p in payload.get("path") or [] if isinstance(p, dict)]
    if len(path) < 2:
        return
    for owner in _owners(engine):
        if owner.team_id == mover.team_id or not mover.active:
            continue
        if owner.turn_flags.get(GATE) and not payload.get("forced"):
            if _closed_gate_crossing(engine, owner, mover, path):
                return
        if "guardian" in _roles(engine, owner):
            for line in owner.turn_flags.get(THRESHOLDS) or []:
                index = crossings(line, path)
                if index is not None:
                    _guardian(engine, owner, mover, path, index)  # "only once during the same movement"
                    break


# ---------------------------------------------------------------------------------------- Shelter, Worlds: cover and saves
def _other_side(line: list[int], a: Any, b: Any) -> bool:
    return _side(line, a.position.x, a.position.y) * _side(line, b.position.x, b.position.y) < 0


@hook("cover")
def threshold_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    best = None
    square = engine.grid.square_size_ft
    for owner in _owners(engine):
        roles = _roles(engine, owner)
        if owner.team_id == attacker.team_id:
            continue
        for line in owner.turn_flags.get(THRESHOLDS) or []:
            if not _other_side(line, attacker, target) or not _near_line(line, target.position.x, target.position.y, 5, square):
                continue
            if "worlds" in roles:
                best = max(best or 0, 2)  # Threshold Between Worlds: Half Cover
            if "shelter" in roles and target.team_id == owner.team_id and target.entity_id != owner.entity_id:
                best = max(best or 0, 1)  # Shelter Behind the Gate: + 1 AC
        gate = owner.turn_flags.get(GATE)
        if gate and target.team_id == owner.team_id and _inside(engine, gate, target.position) and not _inside(engine, gate, attacker.position):
            standing = sum(1 for pid in gate.get("posts") or [] if pid in engine.state.objects and not engine.state.objects[pid].destroyed)
            if standing:  # Three-Quarters Cover; Half Cover once two posts are destroyed
                best = max(best or 0, 5 if standing >= 3 else 2)
    return best


@hook("save")
def shelter_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Shelter Behind the Gate: Advantage against being pushed or pulled across the threshold (from the other side)."""
    if ctx is None or subject is None or "forced_movement" not in set(named or ()):
        return None
    engine = ctx.engine
    for owner in _owners(engine):
        if "shelter" not in _roles(engine, owner) or owner.team_id != subject.team_id or ctx.actor.team_id == owner.team_id:
            continue
        for line in owner.turn_flags.get(THRESHOLDS) or []:
            if _other_side(line, ctx.actor, subject) and _near_line(line, subject.position.x, subject.position.y, 5, engine.grid.square_size_ft):
                return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("ally_row_allowed")
def shelter_reaction_range(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """The Reaction answers only for an ally within 10 feet of one of your thresholds."""
    if not str(row.get("feature_id") or "").endswith("shelter_behind_the_gate"):
        return None
    lines = reactor.turn_flags.get(THRESHOLDS) or []
    return True if any(_near_line(line, subject.position.x, subject.position.y, 10, engine.grid.square_size_ft) for line in lines) else False


def _check(engine: Any, owner: Any, mover: Any, why: str) -> bool:
    """A Cultivation Check (d20 + PB + key modifier) against the owner's Cultivation Save DC; True on a success."""
    key = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("key_mod") or 0) for a in engine.action_catalog.values()
                if a.owner_id == mover.entity_id and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("key_mod") is not None), 0)
    dc = int(_row(engine, owner).get("save_dc") or 10)
    roll = engine.roll_check(
        modifier=int(mover.proficiency_bonus or 0) + key,
        actor_id=mover.entity_id,
        reason=f'CHECK:{PREFIX}{why}',
    )
    engine._record_roll(roll)
    ok = int(roll.total) >= dc
    note(engine, PREFIX + why, owner, f"{mover.display_name}'s Cultivation Check {roll.total} against DC {dc}: "
         f"{'it slips through' if ok else 'the threshold holds it back'}.", (mover.entity_id,))
    return ok


@hook("teleport_check")
def threshold_teleport(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    for owner in _owners(engine):
        if owner.team_id == actor.team_id:
            continue
        crossed = "worlds" in _roles(engine, owner) and any(crossings(line, [(start.x, start.y), (destination.x, destination.y)]) is not None
                                                             for line in owner.turn_flags.get(THRESHOLDS) or [])
        gate = owner.turn_flags.get(GATE)
        crossed = crossed or bool(gate and _inside(engine, gate, start) != _inside(engine, gate, destination))
        if crossed and not _check(engine, owner, actor, "threshold_between_worlds"):
            return False  # Failed Spatial Movement: it stays where it was
    return None


# ------------------------------------------------------------------------------------------------- Heaven's Closed Gate
def _inside(engine: Any, gate: dict[str, Any], position: Any) -> bool:
    """Inside the Gate's circle (round, as the table's spheres and cylinders are: combat/typed_executor.py in_area)."""
    return ((position.x - int(gate["x"])) ** 2 + (position.y - int(gate["y"])) ** 2) ** 0.5 * engine.grid.square_size_ft <= int(gate["r"]) + 1e-9


@effect("closed_gate")
def closed_gate(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position, RuntimeObjectState

    engine, owner = ctx.engine, ctx.actor
    old = owner.turn_flags.get(GATE)
    if old:
        _end_gate(engine, owner, "REPLACED")  # "You may maintain only one Heaven's Closed Gate"
    cl = int(ctx.numbers.get("cl") or 1)
    dc = int(ctx.numbers.get("save_dc") or 10)
    center = owner.position
    radius = int(row.get("radius_ft") or 30)
    posts = []
    reach = radius // engine.grid.square_size_ft
    for name, (dx, dy) in (("north", (0, -1)), ("east", (1, 0)), ("south", (0, 1)), ("west", (-1, 0))):
        x = max(0, min(engine.grid.width - 1, center.x + dx * reach))
        y = max(0, min(engine.grid.height - 1, center.y + dy * reach))
        pid = f"object:gate:{owner.entity_id}:{name}:{engine.state.event_sequence + 1}"
        post = RuntimeObjectState(object_id=pid, object_kind="gate_post", position=Position(x=x, y=y), unattended=True, flammable=False, ac=dc,
                                  current_hp=3 * cl, maximum_hp=3 * cl, damage_immunities=("POISON", "PSYCHIC"),
                                  component={"name": f"Gate post ({name})", "blocks": False})
        engine.state.objects[pid] = post
        engine._append_event("OBJECT_UPDATED", PREFIX + "heaven_s_closed_gate", actor_id=owner.entity_id, target_ids=(pid,),
                             payload={"object": post.model_dump(mode="json"), "created": True})
        posts.append(pid)
    owner.turn_flags[GATE] = {"x": center.x, "y": center.y, "r": radius, "until": te.clock_expiry(engine, "minutes", 1), "posts": posts,
                              "round": int(engine.state.round_number), "ends_round": int(engine.state.round_number) + 10, "dc": dc}
    note(engine, PREFIX + "heaven_s_closed_gate", owner, f"Heaven's Closed Gate: a vast threshold rises {radius} feet around {owner.display_name}.")


def _end_gate(engine: Any, owner: Any, reason: str) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    gate = owner.turn_flags.pop(GATE, None)
    if not gate:
        return
    for pid in gate.get("posts") or []:  # the projected posts vanish with it
        post = engine.state.objects.get(pid)
        if post is not None and not post.destroyed:
            gone = RuntimeObjectState.model_validate(post.model_copy(update={"destroyed": True}).model_dump(mode="json"))
            engine.state.objects[pid] = gone
            engine._append_event("OBJECT_UPDATED", PREFIX + "heaven_s_closed_gate", actor_id=owner.entity_id, target_ids=(pid,),
                                 payload={"object": gone.model_dump(mode="json"), "ended": True})
    note(engine, PREFIX + "heaven_s_closed_gate", owner, f"Heaven's Closed Gate ends ({reason.lower().replace('_', ' ')}).")


@hook("turn_start")
def gate_runs_out(engine: Any, actor: Any) -> None:
    gate = actor.turn_flags.get(GATE)
    if gate and int(engine.state.round_number) >= int(gate.get("ends_round") or 0):
        _end_gate(engine, actor, "EXPIRED")


@hook("event")
def gate_posts(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "OBJECT_UPDATED":
        return
    for owner in list(_owners(engine)):
        gate = owner.turn_flags.get(GATE)
        if gate and all(pid in engine.state.objects and engine.state.objects[pid].destroyed for pid in gate.get("posts") or []):
            _end_gate(engine, owner, "POSTS_DESTROYED")  # "destroying all four ends the Gate"


def _closed_gate_crossing(engine: Any, owner: Any, mover: Any, path: list[tuple[int, int]]) -> bool:
    """True when the Gate stopped the move (the Guardian's threshold then has nothing left to answer)."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position

    gate = owner.turn_flags.get(GATE) or {}
    flags = mover.turn_flags.get("_round_gate_blocked") or {}
    sides = [_inside(engine, gate, Position(x=x, y=y)) for x, y in path]
    index = next((i for i in range(1, len(sides)) if sides[i] != sides[i - 1]), None)
    if index is None:
        return False
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    final = (mover.position.x, mover.position.y)
    before = path[index - 1]
    action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id
                   and ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "heaven_s_closed_gate"), None)
    if action is None:
        return False
    typed = {**((action.parameters or {}).get("typed") or {}), "effects": []}
    typed["numbers"] = {**(typed.get("numbers") or {}), "save_dc": int(gate.get("dc") or 10)}
    blocked = flags.get(owner.entity_id) == stamp  # "cannot attempt to cross again that turn"
    box: dict[str, Any] = {}
    if not blocked:
        better = "STR" if int((mover.saving_throws or {}).get("STR", 0)) >= int((mover.saving_throws or {}).get("CHA", 0)) else "CHA"
        sub = te.Context(engine, owner, action, _intent(engine), typed, [mover], mover, box)
        te.run_effects(sub, [{"type": "save", "ability": better.lower(), "evidence": "Heaven's Closed Gate: Strength or Charisma saving throw (its choice)",
                              "on_fail": [{"type": "gate_held"}], "on_success": []}])
        if not box.get("_gate_held"):
            mover.movement_remaining_ft = max(0, int(mover.movement_remaining_ft or 0) - engine.grid.square_size_ft)  # the edge is difficult terrain
            return False
    _put(engine, mover, before, PREFIX + "heaven_s_closed_gate")
    if final == (mover.position.x, mover.position.y):
        return True
    mover.turn_flags["_round_gate_blocked"] = {**flags, owner.entity_id: stamp}
    sub = te.Context(engine, owner, action, _intent(engine), typed, [mover], mover, {})
    te.run_effects(sub, [{"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN"}]
                   + ([] if blocked else [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["force"]}]))
    mover.movement_remaining_ft = 0
    return True


@effect("gate_held")
def gate_held(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_gate_held"] = True


def _shelter_owners_for_standing(engine: Any, actor: Any) -> list[Any]:
    square = int(engine.grid.square_size_ft)
    owners = []
    for owner in _owners(engine):
        if owner.entity_id == actor.entity_id or owner.team_id != actor.team_id or "shelter" not in _roles(engine, owner):
            continue
        if any(_near_line(line, actor.position.x, actor.position.y, 5, square)
               for line in owner.turn_flags.get(THRESHOLDS) or []):
            owners.append(owner)
    return owners


@hook("stand_cost_offer")
def shelter_standing_offer(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """Pure preview quote; actual use waits for the owner's transaction decision."""
    if normal_cost > 5 and _shelter_owners_for_standing(engine, actor):
        return 5
    return None


@hook("stand_cost_decision")
def shelter_standing_decision(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """Ask each qualifying Gate owner before applying its optional ally benefit."""
    if normal_cost <= 5:
        return None
    from .needle import ask, checkpoint_id, ai_controlled
    from ..senses import perceives

    intent = _intent(engine)
    accepted = False
    for owner in _shelter_owners_for_standing(engine, actor):
        if ai_controlled(engine, owner) and not perceives(engine, owner, actor):
            continue
        picked = ask(engine, intent, checkpoint_id(engine, "shelter_standing", owner.entity_id, actor.entity_id),
                     owner, "choice:gate.shelter_standing", ["accept"], labels={"accept": "Let this ally stand for 5 feet"},
                     preferred=["accept"], allow_decline=True, target_id=actor.entity_id,
                     name="Shelter Behind the Gate",
                     prompt=f"{actor.display_name} is standing up near your threshold. Let them stand for 5 feet of movement?")
        accepted = accepted or picked == ["accept"]
    return 5 if accepted else None


@hook("stand_cost_fallback_decision")
def shelter_standing_fallback(engine: Any, actor: Any, discounted_cost: int, ordinary_cost: int) -> bool | None:
    """Get the acting creature's approval before charging the ordinary fallback."""
    owners = _shelter_owners_for_standing(engine, actor)
    if not owners or ordinary_cost <= discounted_cost:
        return None
    from .needle import ask, checkpoint_id
    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "shelter_standing_fallback", actor.entity_id),
                 actor, "choice:combat.standing_fallback", ["confirm"],
                 labels={"confirm": f"Spend {ordinary_cost} feet instead"}, preferred=["confirm"],
                 allow_decline=True, target_id=actor.entity_id, name="Stand up",
                 prompt=f"The Gate owner declined the discount. Stand for {ordinary_cost} feet of movement?")
    return picked == ["confirm"]


@hook("choice_options")
def shelter_standing_choice_options(engine: Any, intent: Any, checkpoint: str, reactor_id: str,
                                    choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if choice_id == "choice:combat.standing_fallback":
        return {"option_ids": ["confirm"], "minimum_selections": 1, "maximum_selections": 1,
                "allow_decline": True, "automatic_use": True, "preferred_option_ids": ["confirm"]}
    if choice_id != "choice:gate.shelter_standing":
        return None
    return {"option_ids": ["accept"], "minimum_selections": 1, "maximum_selections": 1,
            "allow_decline": True, "automatic_use": True, "preferred_option_ids": ["accept"]}


@hook("object_damage_defenses")
def gate_post_resistance(engine: Any, actor: Any, obj: Any, packets: Any, source: Any) -> list[dict[str, Any]] | None:
    if obj.object_kind != "gate_post":
        return None
    for owner in _owners(engine):
        gate = owner.turn_flags.get(GATE) or {}
        if obj.object_id in (gate.get("posts") or []):
            return [{"kind": "resistance", "damage_types": ["BLUDGEONING", "PIERCING", "SLASHING", "FORCE"]}]
    return None
