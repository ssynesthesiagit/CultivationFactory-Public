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
from ..relations import relation, ALLY, ENEMY

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
    return [a for a in engine.state.actors.values() if a.active and (_roles(engine, a) or any(x.owner_id==a.entity_id and ((x.parameters or {}).get("typed") or {}).get("source")==PREFIX+"heaven_s_closed_gate" for x in engine.action_catalog.values())) and (a.turn_flags.get(THRESHOLDS) or a.turn_flags.get(GATE))]


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
            va = (line[2]-line[0])*(py-line[1])-(line[3]-line[1])*(px-line[0])
            vb = (line[2]-line[0])*(y-line[1])-(line[3]-line[1])*(x-line[0])
            t = va / (va-vb)
            mx, my = px+t*(x-px), py+t*(y-py)
            ax, ay, bx, by = line
            slack = 0.5 / max(1.0, ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
            if -slack <= _along(line, mx, my) <= 1 + slack:
                return index - 1
        last_side, last_index = side, index
    return None


def _near_line(line: list[int], x: int, y: int, feet: int, square: int) -> bool:
    t = max(0, min(1, _along(line, x, y)))
    dx, dy = x-line[0]-t*(line[2]-line[0]), y-line[1]-t*(line[3]-line[1])
    return (dx*dx+dy*dy)*square*square <= feet*feet


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
    """Two actual ground endpoints; every grid-representable legal segment is reachable."""
    from .needle import ask, checkpoint_id, cell_id
    from ..gate2_runtime_models import Position
    reach = 15 if "twin" in _roles(engine, owner) else max([5, *[int(a.range_ft or 5) for a in
        _melee_attacks(engine, owner, owner).values() if any(e.get('attack_kind')=='unarmed'
        for e in ((a.parameters or {}).get('typed') or {}).get('effects',[]))]])
    cells = {(x,y):Position(x=x,y=y) for x in range(engine.grid.width) for y in range(engine.grid.height)
        if not engine.grid.terrain_at(Position(x=x,y=y), 'BLOCKED')}
    possible = {}
    for a,pa in cells.items():
        ends = []
        for b in ((a[0]+dx,a[1]+dy) for dx in range(-3,4) for dy in range(-3,4)):
            if b not in cells:continue
            if a == b or ((a[0]-b[0])**2+(a[1]-b[1])**2)*engine.grid.square_size_ft**2 > 225:continue
            line = [*a,*b]
            if _near_line(line,owner.position.x,owner.position.y,reach,engine.grid.square_size_ft):ends.append(b)
        if ends:possible[a]=ends
    if not possible:return None
    ids = {cell_id(cells[a]):a for a in possible}
    first = ask(engine,intent,checkpoint_id(engine,'threshold_first',owner.entity_id,index),owner,
        'choice:needle.threshold_first',list(ids),labels={k:'First endpoint '+k.removeprefix('cell:') for k in ids},
        preferred=sorted(ids,key=lambda k:(engine.grid.distance_ft(owner.position,cells[ids[k]]),k))[:1],
        allow_decline=True,name='Guarded Threshold',prompt='Place a Guarded Threshold until your next turn: choose its first ground endpoint, or decline.')
    if not first:return None
    a=ids[first[0]]; ends={cell_id(cells[b]):b for b in possible[a]}
    last=ask(engine,intent,checkpoint_id(engine,'threshold_last',owner.entity_id,index),owner,
        'choice:needle.threshold_last',list(ends),labels={k:'Second endpoint '+k.removeprefix('cell:') for k in ends},
        name='Guarded Threshold',prompt='Choose the second ground endpoint, no more than 15 feet from the first.')
    return [*a,*ends[last[0]]]


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
    target = Position(x=cell[0], y=cell[1], z=cell[2] if len(cell)>2 else mover.position.z)
    if target == before:
        return
    mover.position = target
    engine._append_event("MOVEMENT_COMMITTED", source, actor_id=mover.entity_id,
                         payload={"destination": target.model_dump(mode="json"), "path": [before.model_dump(mode="json"), target.model_dump(mode="json")],
                                  "cost_ft": 0, "forced": True, "placed": True})


def _guardian(engine: Any, owner: Any, mover: Any, path: list[tuple[int, int]], index: int) -> bool:
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
        action = attacks[picked[0]]
        typed = (action.parameters or {}).get("typed") or {}
        attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
        attack.update(count=1, granted_attack_root=True)
        hits_before = len([e for e in engine.events if e.event_type == "ATTACK_ROLLED"])
        cache={'gate_guardian_owner':owner.entity_id,'gate_guardian_target':mover.entity_id}
        te.run_effects(te.Context(engine, owner, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [mover], mover, cache), [attack])
        rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"][hits_before:]
        hit = bool(cache.get("gate_confirmed_hit"))
        if not mover.active:
            return
        if not hit:
            return False
        sub = te.Context(engine, owner, action, intent, typed, [mover], mover, cache)
        te.run_effects(sub, [{"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN"},
                             {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
        mover.movement_remaining_ft = 0
        nearest_origin(engine, owner, mover, path[index], mover.turn_flags.get('_round_gate_crossed_line'), mover.turn_flags.get('_round_gate_origin_side'))
        if "twin" in _roles(engine, owner) and mover.active:
            _twin_result(engine, owner, mover, sub, intent)
        return True


def _twin_result(engine: Any, owner: Any, mover: Any, sub: Any, intent: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    labels = {"push": "Push it 10 feet away from the threshold", "prone": "Knock it Prone", "force": "+ 2d8 Force",
              "mark": "Mark it: Disadvantage on attacks against anyone but you until the start of your next turn"}
    choice=sub.damage_cache.get('gate_twin_choice')
    if choice is None:
        picked = ask(engine, intent, checkpoint_id(engine, "twin_posts", mover.entity_id), owner, "choice:needle.twin_guardian_posts", list(labels), labels=labels,
                     allow_decline=False, target_id=mover.entity_id, name="Twin Guardian Posts", prompt="Twin Guardian Posts: choose one additional result.")
        choice = picked[0]
    if choice == "push":
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "prone":
        te.run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "prone"}])
    elif choice == "force":
        return  # Delivered as an attached packet at the confirmed-hit boundary.
    elif choice == "mark":
        engine._apply_condition(mover, "condition:typed.gate_marked", PREFIX + "twin_guardian_posts", owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Marked by {owner.display_name}: Disadvantage on attacks against anyone else",
                                      "rule": {"attacks_others_have": "DISADVANTAGE"}})


# ---------------------------------------------------------------------------------------- Shelter, Worlds: cover and saves
def _other_side(line: list[int], a: Any, b: Any) -> bool:
    return crossings(line, [(a.position.x,a.position.y),(b.position.x,b.position.y)]) is not None


def threshold_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    best = None
    square = engine.grid.square_size_ft
    for owner in _owners(engine):
        roles = _roles(engine, owner)
        for line in owner.turn_flags.get(THRESHOLDS) or []:
            if not _other_side(line, attacker, target) or not _near_line(line, target.position.x, target.position.y, 5, square):
                continue
            if "worlds" in roles:
                best = max(best or 0, 2)  # Threshold Between Worlds: Half Cover

        gate = owner.turn_flags.get(GATE)
        if gate and _inside(engine, gate, target.position) and not _inside(engine, gate, attacker.position):
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
        if "shelter" not in _roles(engine, owner) or relation(engine,owner,subject)!=ALLY or relation(engine,owner,ctx.actor)!=ENEMY:
            continue
        for line in owner.turn_flags.get(THRESHOLDS) or []:
            if forced_crosses(ctx,subject,line) and _near_line(line, subject.position.x, subject.position.y, 5, engine.grid.square_size_ft):
                if _choose_benefit(engine,owner,subject,"Advantage resisting this crossing push or pull"):
                    return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("ally_row_allowed")
def shelter_reaction_range(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """The Reaction answers only for an ally within 10 feet of one of your thresholds."""
    if not str(row.get("feature_id") or "").endswith("shelter_behind_the_gate"):
        return None
    lines = reactor.turn_flags.get(THRESHOLDS) or []
    return False  # The family producer below owns consent, complete-distance reduction and placement.


def _check(engine: Any, owner: Any, mover: Any, why: str) -> bool:
    from .ability_source import cultivation_check, numbers_of
    gate=owner.turn_flags.get(GATE) or {}
    dc=int(gate.get('dc') if why=='heaven_s_closed_gate' else _row(engine,owner).get('save_dc') or 10)
    return cultivation_check(engine,mover,numbers_of(engine,mover),dc,PREFIX+why)


@hook("teleport_check")
def threshold_teleport(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    for owner in _owners(engine):
        if relation(engine,owner,actor)!=ENEMY:
            continue
        crossed = "worlds" in _roles(engine, owner) and any(plane_crossing(line,start,destination,10,engine.grid.square_size_ft)
                                                             for line in owner.turn_flags.get(THRESHOLDS) or [])
        gate = owner.turn_flags.get(GATE)
        crossed = crossed or bool(gate and _inside(engine, gate, start) != _inside(engine, gate, destination))
        if crossed and not _check(engine, owner, actor, "heaven_s_closed_gate" if gate and _inside(engine,gate,start)!=_inside(engine,gate,destination) else "threshold_between_worlds"):
            return False  # Failed Spatial Movement: it stays where it was
    return None


# ------------------------------------------------------------------------------------------------- Heaven's Closed Gate
def _inside(engine: Any, gate: dict[str, Any], position: Any) -> bool:
    """Inside the Gate's circle (round, as the table's spheres and cylinders are: combat/typed_executor.py in_area)."""
    return int(gate.get("z",0)) <= position.z <= int(gate.get("z",0))+30//engine.grid.square_size_ft and ((position.x - int(gate["x"])) ** 2 + (position.y - int(gate["y"])) ** 2) ** 0.5 * engine.grid.square_size_ft <= int(gate["r"]) + 1e-9


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
    from ..senses import perceives
    from .needle import ask,checkpoint_id
    eligible={a.entity_id:a for a in engine.state.actors.values() if a.active and relation(engine,owner,a)==ALLY and a.entity_id!=owner.entity_id and perceives(engine,owner,a)}
    selected=ask(engine,ctx.intent,checkpoint_id(engine,'closed_gate_allies',owner.entity_id),owner,
        'choice:needle.closed_gate_allies',list(eligible),labels={k:a.display_name for k,a in eligible.items()},
        minimum=0,maximum=len(eligible),default='all',allow_decline=True,name="Heaven's Closed Gate",
        prompt="Choose any willing allies you perceive to cross Heaven's Closed Gate freely for 1 minute.") if eligible else []
    allies=[k for k in selected if _willing(engine,owner,eligible[k],PREFIX+'heaven_s_closed_gate',str(ctx.intent.intent_id))]
    radius = int(row.get("radius_ft") or 30)
    posts = []
    reach = radius // engine.grid.square_size_ft
    for name, (dx, dy) in (("north", (0, -1)), ("east", (1, 0)), ("south", (0, 1)), ("west", (-1, 0))):
        x = max(0, min(engine.grid.width - 1, center.x + dx * reach))
        y = max(0, min(engine.grid.height - 1, center.y + dy * reach))
        pid = f"object:gate:{owner.entity_id}:{name}:{engine.state.event_sequence + 1}"
        post = RuntimeObjectState(object_id=pid, object_kind="gate_post", position=Position(x=x, y=y), unattended=True, flammable=False, ac=dc,
                                  current_hp=3 * cl, maximum_hp=3 * cl, damage_immunities=("POISON", "PSYCHIC"),
                                  component={"name": f"Gate post ({name})", "blocks": False, "body_anchor": True, "owner_id": owner.entity_id, "source_cl": cl, "size": "MEDIUM", "occupies_space": False, "harvestable": False, "can_act": False, "damage_transfers": False})
        engine.state.objects[pid] = post
        engine._append_event("OBJECT_UPDATED", PREFIX + "heaven_s_closed_gate", actor_id=owner.entity_id, target_ids=(pid,),
                             payload={"object": post.model_dump(mode="json"), "created": True})
        posts.append(pid)
    owner.turn_flags[GATE] = {"x": center.x, "y": center.y, "z": center.z, "r": radius, "until": te.clock_expiry(engine, "minutes", 1), "posts": posts,
                              "allies": allies, "source_cl": cl, "round": int(engine.state.round_number), "ends_round": int(engine.state.round_number) + 10, "dc": dc}
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
    sides = [_inside(engine, gate, Position(x=p[0], y=p[1], z=p[2] if len(p)>2 else mover.position.z)) for p in path]
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
        from .needle import ask,checkpoint_id
        choices=ask(engine,_intent(engine),checkpoint_id(engine,'closed_gate_save',owner.entity_id,mover.entity_id),mover,
            'choice:needle.closed_gate_save',['str','cha'],labels={'str':'Strength saving throw','cha':'Charisma saving throw'},
            preferred=[better.lower()],target_id=mover.entity_id,name="Heaven's Closed Gate",
            prompt=f"{mover.display_name}: choose Strength or Charisma to cross Heaven's Closed Gate. Failure: 4d8 Force damage and Speed 0 for this turn.")
        better=choices[0].upper()
        sub = te.Context(engine, owner, action, _intent(engine), typed, [mover], mover, box)
        te.run_effects(sub, [{"type": "save", "ability": better.lower(), "evidence": "Heaven's Closed Gate: Strength or Charisma saving throw (its choice)",
                              "on_fail": [{"type": "gate_held"}], "on_success": []}])
        if not box.get("_gate_held"):
            mover.movement_remaining_ft = max(0, int(mover.movement_remaining_ft or 0) - engine.grid.square_size_ft)  # the edge is difficult terrain
            return False
    _put(engine, mover, before, PREFIX + "heaven_s_closed_gate")
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
        if owner.entity_id == actor.entity_id or relation(engine,owner,actor)!=ALLY or "shelter" not in _roles(engine, owner):
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


PARENT = PREFIX.removesuffix('.feature.')
LEVELS = {'guardian': 3, 'shelter': 6, 'twin': 10, 'worlds': 14}
FEATURES = ('guardian_at_the_gate','shelter_behind_the_gate','twin_guardian_posts','threshold_between_worlds','heaven_s_closed_gate')


@hook('journey_acquisition_options')
def gate_learning_options(session, actor_id, source, sheet):
    if source != PARENT:return None
    return [{'id':'choose','label':'Choose Vermilion Gate Guardian Body as your Body Refining Subpath. Open School; gain only features earned by your Body Path level.'}]


@hook('journey_acquisition')
def gate_acquire(session, actor_id, source, payload, sheet):
    if source != PARENT:return None
    from ..journey import require
    from ..canonical import canonical_sha256
    from copy import deepcopy
    require(payload == {'choice':'choose'}, 'Choose this Open School Subpath through its native menu.')
    paths = sheet.get('path_and_subpath') or {}
    attained = next((int(r['attainment']) for r in paths.get('paths',[]) if r.get('path_id')=='tianxia.path.body_refining' and type(r.get('attainment')) is int),0)
    require(attained >= 3, 'Vermilion Gate Guardian Body requires Body Refining Path level 3.')
    require(not session.state['actors'][actor_id]['incapacitated'], 'An incapacitated creature cannot choose a Subpath.')
    require(not paths.get('subpath_record_id') and not paths.get('subpath_record_ids') and not any(
        sid.startswith('tianxia.subpath.body.') for sid in paths.get('path_feature_record_ids',[])),
        'Choose only one Body Refining Subpath; an existing progression cannot be retained or reset.')
    result=deepcopy(sheet);p=result.setdefault('path_and_subpath',{})
    p['subpath_record_id']=PARENT;p['subpath_record_ids']=[PARENT]
    p['path_feature_record_ids']=list(p.get('path_feature_record_ids',[]))+[PREFIX+f for f,cl in zip(FEATURES,(3,6,10,14,18)) if cl<=attained]
    receipt=canonical_sha256({'actor':actor_id,'source':PARENT,'path_level':attained,'revision':session.state['revision']})
    session.state['actors'][actor_id].setdefault('source_states',{})[PARENT]={'acquired_sheet':result,'receipt':receipt,'source_cl':attained}
    session.emit('SUBPATH_ACQUIRED',actor_id,source=PARENT,path_level=attained,acquisition_id=receipt)
    return {'sheet':result,'acquisition_id':receipt}


@hook('journey_source_sheet')
def gate_source_sheet(sheet, session, actor_id):
    from copy import deepcopy
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if not state:return None
    result=deepcopy(sheet);p=result.setdefault('path_and_subpath',{})
    old=state['acquired_sheet']['path_and_subpath']
    for key in ('subpath_record_id','subpath_record_ids'):p[key]=deepcopy(old[key])
    p['path_feature_record_ids']=list(dict.fromkeys([*p.get('path_feature_record_ids',[]),*old['path_feature_record_ids']]))
    return result


def _ctx(engine, owner, source):
    from ..typed_executor import Context
    action=next((a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id),None)
    return Context(engine,owner,action,_intent(engine),{'source':source,'numbers':_row(engine,owner)},[],owner,{})


def _willing(engine, owner, ally, source, scope):
    from .recipient_consent import willing
    name="Shelter Behind the Gate" if source.endswith('shelter_behind_the_gate') else "Heaven's Closed Gate"
    proposal="reduce this forced movement by 15 feet; if reduced to 0, cancel its Prone rider and choose a nearest threshold space" if name.startswith('Shelter') else "cross this stationary Gate freely for 1 minute"
    return willing(engine,ally,owner,source,name,proposal,intent=_intent(engine))


def _choose_benefit(engine, owner, ally, kind):
    from .needle import ask,checkpoint_id
    from ..senses import perceives
    if not perceives(engine,owner,ally):
        from .needle import ai_controlled
        if ai_controlled(engine,owner):return False
    return bool(ask(engine,_intent(engine),checkpoint_id(engine,'shelter_'+kind,owner.entity_id,ally.entity_id),owner,
        'choice:needle.shelter_'+kind,['protect'],labels={'protect':'Choose this ally for Shelter Behind the Gate'},
        name='Shelter Behind the Gate',target_id=ally.entity_id,allow_decline=True,
        prompt=f'Shelter Behind the Gate: choose {ally.display_name} for {kind.replace("_"," ")}? No action or Stamina cost.'))


@hook('movement_attempt')
@hook('forced_movement_attempt')
def gate_before_step(engine, mover, previous, nxt, intent):
    from ..movement_steps import context
    from ..gate2_runtime_models import Position
    step=context(engine,mover)
    # Side memory is scoped to this real continuous native route, never a turn.
    if int(step.get('travelled_ft',0))==0:
        mover.turn_flags['_round_gate_route']={'seen':[], 'sides':{}}
    route=mover.turn_flags.setdefault('_round_gate_route',{'seen':[],'sides':{}})
    for owner in _owners(engine):
        if owner.entity_id==mover.entity_id or relation(engine,owner,mover)!=ENEMY:continue
        gate=owner.turn_flags.get(GATE)
        if gate and not step.get("forced") and mover.entity_id not in gate.get('allies',[]):
            # The existing resolver operates against pre-step positions now.
            if _closed_gate_crossing(engine,owner,mover,[(previous.x,previous.y,previous.z),(nxt.x,nxt.y,nxt.z)]):
                return {'stop':True,'source_id':PREFIX+'heaven_s_closed_gate','label':"Heaven's Closed Gate ends this movement at the boundary."}
        if 'guardian' not in _roles(engine,owner) or owner.entity_id in route['seen']:continue
        for index,line in enumerate(owner.turn_flags.get(THRESHOLDS) or []):
            if min(previous.z,nxt.z)*engine.grid.square_size_ft >= (10 if 'worlds' in _roles(engine,owner) else 5):continue
            key=owner.entity_id+':'+str(index)
            side=route['sides'].get(key) or _side(line,previous.x,previous.y)
            after=_side(line,nxt.x,nxt.y)
            if side:route['sides'][key]=side
            if side and after and side!=after and -0.5<=_along(line,nxt.x,nxt.y)<=1.5:
                route['seen'].append(owner.entity_id)
                mover.turn_flags['_round_gate_crossed_line']=list(line)
                mover.turn_flags['_round_gate_origin_side']=side
                if _guardian(engine,owner,mover,[(previous.x,previous.y),(nxt.x,nxt.y)],0):
                    return {'stop':True,'source_id':PREFIX+'guardian_at_the_gate','label':'Guardian at the Gate hits: movement ends before the threshold.'}
                break


@hook('forced_movement_reduction')
def shelter_native_reaction(ctx, subject):
    from .needle import ask,checkpoint_id
    engine=ctx.engine;distance=int(ctx.forced_movement_distance_ft or 0)
    if distance<=0:return None
    for owner in _owners(engine):
        if owner.entity_id==subject.entity_id or relation(engine,owner,subject)!=ALLY or 'shelter' not in _roles(engine,owner):continue
        if not owner.reaction_available or owner.resources.get(STAMINA,0)<1 or owner.turn_flags.get('_round_gate_shelter')==engine.state.round_number:continue
        lines=[line for line in owner.turn_flags.get(THRESHOLDS) or [] if _near_line(line,subject.position.x,subject.position.y,10,engine.grid.square_size_ft)]
        if not lines:continue
        source=PREFIX+'shelter_behind_the_gate'
        if not _willing(engine,owner,subject,source,str(ctx.intent.intent_id)):continue
        picked=ask(engine,ctx.intent,checkpoint_id(engine,'shelter_reaction',owner.entity_id,subject.entity_id),owner,
            'choice:needle.shelter_reaction',['protect'],labels={'protect':'Reaction: spend 1 Stamina to reduce movement by 15 feet'},
            allow_decline=True,target_id=subject.entity_id,name='Shelter Behind the Gate',
            prompt=f'Shelter Behind the Gate: reduce {subject.display_name}\'s {distance}-foot forced movement by 15 feet? Costs your Reaction and 1 Stamina, once per round.')
        if not picked:continue
        engine._spend_resource(owner,STAMINA,1,source);owner.reaction_available=False
        owner.turn_flags['_round_gate_shelter']=engine.state.round_number
        if distance<=15:
            from ..gate2_runtime_models import Position
            from .needle import cell_id
            options={}
            for line in lines:
                for x in range(engine.grid.width):
                    for y in range(engine.grid.height):
                        p=Position(x=x,y=y,z=subject.position.z)
                        if _near_line(line,x,y,5,engine.grid.square_size_ft) and engine.grid.volume_step_legal(p,p,occupied_cells=engine._occupied_volumes_except(subject.entity_id),footprint=engine._footprint(subject)):
                            options[cell_id(p)]=p
            if options:
                near=min(engine.grid.distance_ft(subject.position,p) for p in options.values())
                options={k:p for k,p in options.items() if engine.grid.distance_ft(subject.position,p)==near}
                picked=ask(engine,ctx.intent,checkpoint_id(engine,'shelter_landing',owner.entity_id,subject.entity_id),subject,
                    'choice:needle.shelter_landing',list(options),labels={k:'Land adjacent to the threshold at '+k.removeprefix('cell:') for k in options},
                    name='Shelter Behind the Gate',prompt=f'{subject.display_name}: choose the nearest legal space adjacent to the threshold. This movement is reduced to 0.')
                p=options[picked[0]];_put(engine,subject,(p.x,p.y),source)
            ctx.damage_cache.setdefault('_gate_cancel_prone',[]).append(subject.entity_id)
        engine._append_event('REACTION_RESOLVED',source,actor_id=owner.entity_id,target_ids=(subject.entity_id,),payload={'distance_before':distance,'distance_after':max(0,distance-15),'checkpoint':'FORCED_MOVEMENT'})
        return 15
    return None


@hook('condition_attempt')
def shelter_cancel_same_movement_prone(ctx, subject, effect):
    if effect.get('type')!='condition' or str(effect.get('condition')).lower()!='prone':return None
    ids=ctx.damage_cache.get('_gate_cancel_prone',[])
    if subject is not None and subject.entity_id in ids:
        ids.remove(subject.entity_id)
        return False
    return None


@hook('before_attack')
def shelter_attack_choice(engine, attacker, target, intent, context):
    """Optional +1 AC is independent of cover and belongs to this attack alone."""
    from .attack_defenses import grant
    spec=context.get('attack_spec')
    from ..attack_delivery import is_ranged
    if spec is None or not is_ranged(context.get('effect') or spec,context.get('range_ft')):return None
    for owner in _owners(engine):
        if 'shelter' not in _roles(engine,owner) or relation(engine,owner,target)!=ALLY or target.entity_id==owner.entity_id:continue
        if any(_other_side(line,attacker,target) and _near_line(line,target.position.x,target.position.y,5,engine.grid.square_size_ft)
               for line in owner.turn_flags.get(THRESHOLDS) or []):
            if _choose_benefit(engine,owner,target,'+1 AC against this ranged attack'):
                grant(spec,target,PREFIX+'shelter_behind_the_gate',1)
                break
    return None


def nearest_origin(engine, owner, mover, before, line, side):
    """Place after attack damage, choosing among nearest full legal origin spaces."""
    if not line or not side:return
    from ..gate2_runtime_models import Position
    from .needle import ask,checkpoint_id,cell_id
    cells={}
    for x in range(engine.grid.width):
        for y in range(engine.grid.height):
            p=Position(x=x,y=y,z=mover.position.z)
            if _side(line,x,y)!=side:continue
            if not engine.grid.volume_step_legal(p,p,occupied_cells=engine._occupied_volumes_except(mover.entity_id),footprint=engine._footprint(mover)):continue
            cells[cell_id(p)]=p
    if not cells:return  # Failed Spatial Movement retains the originating position.
    near=min((p.x-before[0])**2+(p.y-before[1])**2 for p in cells.values())
    cells={k:p for k,p in cells.items() if (p.x-before[0])**2+(p.y-before[1])**2==near}
    picked=ask(engine,_intent(engine),checkpoint_id(engine,'guardian_landing',owner.entity_id,mover.entity_id),owner,
        'choice:needle.guardian_landing',list(cells),labels={k:'Nearest legal origin-side space '+k.removeprefix('cell:') for k in cells},
        target_id=mover.entity_id,name='Guardian at the Gate',prompt=f'Place {mover.display_name} in a nearest legal space before the threshold after the attack damage.')
    p=cells[picked[0]];_put(engine,mover,(p.x,p.y,p.z),PREFIX+'guardian_at_the_gate')


@hook('damage_packet_selection')
def twin_confirmed_hit(ctx,target,packet_kinds):
    if ctx.damage_cache.get('gate_guardian_owner')!=ctx.actor.entity_id or ctx.damage_cache.get('gate_guardian_target')!=target.entity_id or 'twin' not in _roles(ctx.engine,ctx.actor):return
    if ctx.damage_cache.get('gate_twin_choice') is not None:return
    from .needle import ask,checkpoint_id
    from ..typed_executor import run_effects
    labels={'push':'Push 10 feet away from the crossed threshold','prone':'Knock Prone','force':'Add 2d8 Force damage to this attack','mark':'Disadvantage attacking anyone else until your next turn'}
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'twin_posts',target.entity_id),ctx.actor,
        'choice:needle.twin_guardian_posts',list(labels),labels=labels,name='Twin Guardian Posts',target_id=target.entity_id,
        prompt=f'Twin Guardian Posts: Guardian at the Gate hits {target.display_name}. Choose exactly one additional result.')
    choice=picked[0];ctx.damage_cache['gate_twin_choice']=choice
    if choice=='force':
        run_effects(ctx.on_hit_context(target),[{'type':'damage','applies_to':'target','dice':{'count':2,'sides':8},'damage_types':['force']}])


@hook('forced_movement_direction')
def twin_push_direction(ctx,target,distance):
    if ctx.damage_cache.get('gate_twin_choice')!='push' or ctx.damage_cache.get('gate_guardian_target')!=target.entity_id:return None
    line=target.turn_flags.get('_round_gate_crossed_line');side=target.turn_flags.get('_round_gate_origin_side')
    if not line or not side:return None
    dx,dy=-(line[3]-line[1])*side,(line[2]-line[0])*side
    return ((dx>0)-(dx<0),(dy>0)-(dy<0))


@hook('attack_result')
def guardian_confirmed_result(ctx,target,hit,critical):
    if ctx.damage_cache.get('gate_guardian_owner')==ctx.actor.entity_id and ctx.damage_cache.get('gate_guardian_target')==target.entity_id:
        ctx.damage_cache['gate_confirmed_hit']=bool(hit)


def plane_crossing(line,start,end,height,square):
    """One finite vertical segment-plane intersection, with height in feet."""
    va=(line[2]-line[0])*(start.y-line[1])-(line[3]-line[1])*(start.x-line[0])
    vb=(line[2]-line[0])*(end.y-line[1])-(line[3]-line[1])*(end.x-line[0])
    if va*vb>=0:return False
    t=va/(va-vb);x=start.x+t*(end.x-start.x);y=start.y+t*(end.y-start.y)
    z=start.z+t*(end.z-start.z)
    return 0<=_along(line,x,y)<=1 and 0<=z*square<=height


@hook('effect_cover')
def gate_ray_cover(engine,source,target,ray):
    """Cover follows each actual attack/effect origin ray, without faction filters."""
    from ..gate2_runtime_models import Position
    if ray.get('purpose')=='attack' and not ray.get('ranged'):return None
    a=ray['start'];b=ray['end'];start=Position(x=a[0],y=a[1],z=a[2] if len(a)>2 else 0)
    end=Position(x=b[0],y=b[1],z=b[2] if len(b)>2 else 0)
    best=0
    for owner in _owners(engine):
        if ray.get('purpose')=='attack' and 'worlds' in _roles(engine,owner):
            if any(plane_crossing(line,start,end,10,engine.grid.square_size_ft) and
                   _near_line(line,end.x,end.y,5,engine.grid.square_size_ft) for line in owner.turn_flags.get(THRESHOLDS) or []):best=max(best,2)
        gate=owner.turn_flags.get(GATE)
        if gate and not _inside(engine,gate,start) and _inside(engine,gate,end):
            standing=sum(1 for pid in gate['posts'] if pid in engine.state.objects and not engine.state.objects[pid].destroyed)
            if standing:best=max(best,5 if standing>=3 else 2)
    return best or None


def forced_crosses(ctx,subject,line):
    """Derive the declared push/pull route from its real typed fail branch."""
    from ..gate2_runtime_models import Position
    def rows(items):
        for row in items:
            if not isinstance(row,dict):continue
            yield row
            yield from rows(row.get('on_fail') or [])
    for row in rows(ctx.typed.get('effects') or []):
        if row.get('type')!='forced_movement':continue
        dx=(subject.position.x>ctx.actor.position.x)-(subject.position.x<ctx.actor.position.x)
        dy=(subject.position.y>ctx.actor.position.y)-(subject.position.y<ctx.actor.position.y)
        if row.get('direction') in ('toward','pull'):dx,dy=-dx,-dy
        feet=int(row.get('distance_ft') or 0);steps=feet//ctx.engine.grid.square_size_ft
        end=Position(x=max(0,subject.position.x+dx*steps),y=max(0,subject.position.y+dy*steps),z=subject.position.z)
        if plane_crossing(line,subject.position,end,10 if 'worlds' in _roles(ctx.engine,ctx.actor) else 5,ctx.engine.grid.square_size_ft):return True
    return False


@hook('compile_passives')
def seal_gate_passives(passives,info):
    result=[]
    for row in passives:
        if row.get('kind')=='gate' and str(row.get('feature_id','')).startswith(PREFIX):
            row={**row,'recipient_consent_choices':1}
            if row.get('role')=='shelter':row['trigger_owner']='vermilion_gate'
        result.append(row)
    return result
