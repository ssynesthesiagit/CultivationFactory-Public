"""The Space sphere's Cut the Road Behind You (owner 2026-09-29: "i want everything we can automated"): after a creature teleports it may
seal the route it took, and other creatures cannot follow through it without beating the sealer.  Owner rules:
LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md ("Cut the Road Behind You", "No Road Behind Me") and
authority/typed_mechanics/rules_text.json.  Where the text is silent a default is named below; Spheres 5e and D&D 5.5e were not needed.

Rules ("Cut the Road Behind You", Seal Art, Bonus Action, 4 CP):
- "After you teleport, use a gate, exit a pocket space, or pass through a spatial boundary, you may seal the route behind you."  Only teleports
  are tracked: the table has no gates, pockets or boundaries (a rider).  A teleport is any of the creature's own MOVEMENT_COMMITTED events
  marked ``teleport``; the trace is the last one since the end of the creature's previous turn (default: "after you teleport" lets a
  Reaction teleport on another's turn be sealed on the next turn).  One seal to a trace.
- "Until the start of your next turn, creatures cannot follow through the same teleport trace ... unless they succeed on a Cultivation Check
  against your CSDC."  "At CL 20, the seal lasts until the end of your next turn."
  The seal is a placement (combat/ext/placed.py, tag "seal") on the trace's departure square, remembering where the road ended and the sealer's
  Cultivation Save DC.  A creature FOLLOWS when its own teleport begins within SEAL_NEAR_FT of the departure and ends within SEAL_NEAR_FT of the
  arrival (default: "the same trace" is the road between those two places, two squares of slack at each end).  It makes a Cultivation Check
  (d20 + Proficiency Bonus + its key ability modifier) against the DC: on a success it follows and the seal stands for the next; on a failure
  its teleport does not happen (the ability is spent -- the text names no other price).  Every creature but the sealer is held, allies too
  (the text says "creatures"; default).
- "No Road Behind Me" (CL 10+, Space sphere): "Once per long rest, you may also use Cut the Road Behind You without spending CP" -- a second
  button, used once per fight.  Its first paragraph (erase the visible trace of a Space departure; Disadvantage on checks to track it unless the
  tracker has Spatial Awareness, Divination, Stars or an equivalent sense) is a tracking check the table does not run: a rider.

Buttons (a player's; the built-in AI never teleports, combat/gate4_context.py): "Cut the Road Behind You (4 CP)" and, with No Road Behind Me,
"... (No Road Behind Me, free)".  Both are legal only on the sealer's own turn with a trace to seal.  The seal is drawn on the map with its DC and
the road's ends in its name; a plain log line says what was sealed and, at each follower, whether the check let it through.

Hook added to the framework by this module: ``teleport_gate`` (typed_executor._teleport; documented in combat/ext/__init__.py) -- nothing
told a plug-in that a creature was about to teleport, and the seal has to stop the move before it happens (a saved fight replays the same
events: the check is a recorded roll).  Uses ``turn_end`` (a CL 20 seal ends with its sealer's turn) and ``candidate_allowed``.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, placed, run as run_hooks

CUT = "tianxia.talent.space.cut_the_road_behind_you"
NO_ROAD = "TAL_SPACE_NO_ROAD_BEHIND_ME"
FREE_USED = "condition:typed.seal_free_used"
COST_CP = 4  # "Cost: 4 CP."
NO_ROAD_CL = 10  # "Prerequisite: Space sphere, CL 10+."
LONG_CL = 20  # "At CL 20, the seal lasts until the end of your next turn."
SEAL_NEAR_FT = 10  # default: how near a teleport must begin to the sealed departure and end to the sealed arrival to be "the same trace"
COLOR = "#8a6cf2"


# ------------------------------------------------------------------------------------------------------------ the kit
def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == owner.entity_id and params.get("seal_kit"):
            typed = params.get("typed") or {}
            return {"action": action, "numbers": typed.get("numbers") or {}, "pool": params.get("seal_pool") or "resource:core.qi",
                    "source": action.source_definition_id}
    return None


def last_trace(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The actor's most recent teleport since the end of its previous turn: {"sequence", "from", "to"} (Positions), else None."""
    from ..gate2_runtime_models import Position

    for event in reversed(engine.events):
        if event.event_type == "TURN_ENDED" and event.actor_id == actor.entity_id:
            return None
        payload = event.payload or {}
        path = payload.get("path") or []
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and payload.get("teleport") and len(path) >= 2:
            return {"sequence": event.sequence, "from": Position(**path[0]), "to": Position(**path[-1])}
    return None


def _seals(engine: Any) -> list[Any]:
    return placed.of(engine, "seal")


def _sealed(engine: Any, owner: Any, trace: dict[str, Any]) -> bool:
    return any(z.owner_id == owner.entity_id and placed.data(z).get("sequence") == trace["sequence"] for z in _seals(engine))


def _near(engine: Any, a: Any, b: Any) -> bool:
    return engine.grid.distance_ft(a, b) <= SEAL_NEAR_FT


def following(engine: Any, traveller: Any, start: Any, destination: Any) -> list[Any]:
    """The seals a teleport from ``start`` to ``destination`` by ``traveller`` would follow (its own are none)."""
    from ..gate2_runtime_models import Position

    out = []
    for zone in _seals(engine):
        d = placed.data(zone)
        if zone.owner_id == traveller.entity_id or not d.get("from") or not d.get("to"):
            continue
        if _near(engine, start, Position(x=d["from"][0], y=d["from"][1])) and _near(engine, destination, Position(x=d["to"][0], y=d["to"][1])):
            out.append(zone)
    return out


def _cl(engine: Any, owner: Any, kit: dict[str, Any]) -> int:
    return int(kit["numbers"].get("cl") or 0) or 1


# ------------------------------------------------------------------------------------------------------------ the buttons
@hook("compile_actions")
def seal_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info["owned_ids"])
    if CUT not in owned:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")

    def make(key: str, name: str, free: bool) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=EconomyKind.BONUS_ACTION,
            resolution_kind="TYPED", target_kind="SELF", range_ft=None,
            parameters={"typed": {"effects": [{"type": "seal_cut", "free": free}], "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
                                  "source": CUT},
                        "expected_damage": 0, "player_only": True, "seal_kit": True, "seal_pool": pool, "seal_free": free})

    out = [make("seal.cut", f"Cut the Road Behind You ({COST_CP} CP)", False)]
    if NO_ROAD in owned and int(numbers.get("cl") or 0) >= NO_ROAD_CL:
        out.append(make("seal.free", "Cut the Road Behind You (No Road Behind Me, free)", True))
    return out


@hook("candidate_allowed")
def seal_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if not params.get("seal_kit"):
        return None
    trace = last_trace(engine, actor)
    if trace is None or _sealed(engine, actor, trace) or engine.state.current_actor_id != actor.entity_id:
        return False
    if params.get("seal_free"):
        return not any(c.condition_id == FREE_USED for c in actor.conditions.values())
    return actor.resources.get(params.get("seal_pool") or "resource:core.qi", 0) >= COST_CP


@effect("seal_cut")
def cut(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    trace = last_trace(engine, owner)
    if kit is None or trace is None or _sealed(engine, owner, trace):
        ctx.rider("Cut the Road Behind You: there is no teleport of yours left to seal.")
        return
    if eff.get("free"):
        engine._apply_condition(owner, FREE_USED, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED")  # "Once per long rest"
    else:
        engine._spend_resource(owner, kit["pool"], COST_CP, ctx.source)
    long = _cl(engine, owner, kit) >= LONG_CL
    start, end = trace["from"], trace["to"]
    dc = int(ctx.numbers.get("save_dc") or 10)  # the sealer's Cultivation Save DC
    around = [(c.x, c.y) for c in placed.area(engine, start, "sphere", SEAL_NEAR_FT)]
    cells = [(start.x, start.y)] + [c for c in around if c != (start.x, start.y)]
    ends = "the end of its next turn" if long else "the start of its next turn"
    data = {"owner": owner.entity_id, "from": [start.x, start.y], "to": [end.x, end.y], "dc": dc, "sequence": trace["sequence"],
            "until": "end" if long else "start"}
    placed.place(engine, owner, source=kit["source"], tag="seal", cells=cells, numbers=kit["numbers"], shape="sphere", size_ft=SEAL_NEAR_FT,
                 duration_rounds=None if long else 1, color=COLOR,
                 name=f"{owner.display_name}'s sealed road ({start.x},{start.y} to {end.x},{end.y}; Cultivation Check against {dc} to follow it; "
                      f"until {ends})", placed=data)
    placed.note(engine, ctx.source, owner, f"{owner.display_name} seals the road from ({start.x}, {start.y}) to ({end.x}, {end.y}) until {ends}: "
                f"a creature that teleports along it makes a Cultivation Check against {dc} or stays where it was.")


@hook("turn_end")
def seal_lapses(engine: Any, actor: Any) -> None:
    """A CL 20 seal lasts until the end of its sealer's next turn (a shorter one ends at the start of that turn: zones.on_turn_start)."""
    for zone in _seals(engine):
        d = placed.data(zone)
        if zone.owner_id == actor.entity_id and d.get("until") == "end" and engine.state.round_number > zone.created_round:
            placed.drop(engine, zone, "DURATION_ENDED")


# ------------------------------------------------------------------------------------------------------------ following the road
@hook("teleport_gate")
def follow_the_road(ctx: Any, start: Any, destination: Any) -> bool | None:
    """A teleport along a sealed road: "creatures cannot follow ... unless they succeed on a Cultivation Check against your CSDC"."""
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_seal_verdict")
    engine, actor = ctx.engine, ctx.actor
    last = getattr(engine, "_seal_verdict", None)
    if last is not None and last[0] is ctx and last[1] == destination:
        return last[2]  # one teleport ability can carry two teleport rows (Fold Step): the check is made once
    engine._seal_verdict = (ctx, destination, None)
    for zone in following(engine, actor, start, destination):
        d = placed.data(zone)
        dc = int(d.get("dc") or 10)
        modifier = int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0) + sum(run_hooks("check_bonus", ctx, actor))
        roll = engine.roll_check(modifier=modifier, actor_id=actor.entity_id, reason=f'CHECK:{ctx.source}')
        engine._record_roll(roll)
        success = roll.total >= dc
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Cultivation Check"})
        sealer = engine.state.actors.get(zone.owner_id)
        whose = f"{sealer.display_name}'s" if sealer is not None else "the"
        if not success:
            placed.note(engine, ctx.source, actor, f"{actor.display_name} cannot follow {whose} sealed road (Cultivation Check {roll.total} against {dc}): "
                        f"the teleport fails and it stays at ({start.x}, {start.y}).")
            engine._seal_verdict = (ctx, destination, False)
            return False
        placed.note(engine, ctx.source, actor, f"{actor.display_name} follows {whose} sealed road (Cultivation Check {roll.total} against {dc}).")
    return None
