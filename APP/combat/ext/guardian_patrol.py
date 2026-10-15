"""Guardian: Patrol Practice and its Zone talents (rider lane C16, 2026-09-30). Rules text: the owner's Sphere Compendium, "Patrol
Practice" and the Zone talents (authority/typed_mechanics/rules_text.json). Shared Guardian helpers: combat/ext/guardian_chassis.py
(Guardian's Focus), combat/ext/granted_moves.py (the response's move).

Patrol -- "Action. Duration: Until the start of your next turn. Establish a Patrol Zone centered on yourself. The Patrol Zone extends a
  distance equal to: your melee reach + 10 feet. When a hostile creature you can perceive moves into, out of, or through your Patrol
  Zone, you may make one Patrol Response." The typed effect ``guardian_patrol`` puts the Patrol on the Guardian (a condition ending at
  the start of its next turn) with its Patrol Movement ("your total Patrol Movement before the start of your next turn equals your
  Speed") and its chosen Zone talent ("Choose one Patrol Zone talent you know whenever you establish Patrol"; two with Complex
  Patrol, which expends Martial Focus). The zone is an aura around the Guardian (it moves with it).
Patrol Response -- "move up to your remaining Patrol Movement into a legal space that brings the triggering creature within your melee
  reach; make one opportunity attack against that creature. The first Patrol Response you make before the start of your next turn
  requires your Reaction" and CL 5 / 11 / 17 give 1 / 2 / 3 more each round that do not; "may be made only once per triggering
  creature's turn". Asked of the Guardian (Use / Decline; the built-in AI always responds), after the creature's move has been
  committed: the table offers no reaction in the middle of a move (census row 12 seam request), so the response comes when the move
  ends -- wherever the creature then stands. The response move provokes no opportunity attacks here (granted_moves; the printed
  "provokes opportunity attacks normally" needs the same locked movement seam).
Zone talents:
  Steel Hedge        hostile creatures treat the Patrol Zone as difficult terrain (an aura worked out from the fight, never stored)
  Assist the Line    allies inside the Patrol Zone gain +1 AC (one Assist the Line at a time)
  Clear Path         allies other than you do not provoke opportunity attacks from hostile creatures for moving through the zone
  Stand Still        a Patrol attack hit: the creature's Speed is 0 until the start of its next turn
  Singularity Patrol a hostile creature starting its turn inside: Strength save or it is pulled 5 feet toward you (10 at CL 11),
                     stopping next to you, without opportunity attacks
Swift Guardian -- "activate Patrol as a Bonus Action" for Martial Focus: the button "Patrol (Swift Guardian: Bonus Action)".
Guardian's Focus -- "you hit with a Patrol attack": regain Martial Focus (combat/ext/guardian_chassis.regain_focus).
Not built here: Disruptive Patrol and Punishing Rebuke (a response in the middle of another creature's technique or attack -- census
rows 8 and 12), Singularity Patrol's doubled cost for moving away (per-step movement cost, row 12).
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .guardian import row
from .needle import CHOICE, ask, checkpoint_id, incapacitated

PATROL = "condition:typed.guardian_patrol"
PATROL_ID = "GUARDIAN_BASE_PATROL_PRACTICE"
FOCUS = "resource:core.martial_focus"
ZONE_TALENTS = {  # kind -> (talent id, plain label); the order is the built-in AI's preference
    "stand_still": ("TAL_GUARDIAN_STAND_STILL", "Stand Still: a creature your Patrol attack hits has Speed 0 until its next turn starts"),
    "steel_hedge": ("TAL_GUARDIAN_STEEL_HEDGE", "Steel Hedge: hostile creatures treat your Patrol Zone as difficult terrain"),
    "singularity_patrol": ("TAL_GUARDIAN_SINGULARITY_PATROL",
                           "Singularity Patrol: a hostile creature starting its turn in the zone makes a Strength save or is pulled toward you"),
    "assist_the_line": ("tianxia.talent.guardian.assist_the_line", "Assist the Line: allies in your Patrol Zone gain +1 AC"),
    "clear_path": ("tianxia.talent.guardian.clear_path",
                   "Clear Path: allies moving through your Patrol Zone provoke no opportunity attacks from hostile creatures"),
}


def patrol(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == PATROL), None)


def _zones(actor: Any) -> set[str]:
    held = patrol(actor)
    return set(str((held.data or {}).get("zones") or "").split(",")) - {""} if held is not None else set()


def _reach(engine: Any, actor: Any) -> int:
    from ..typed_reactions import physical_melee_reach

    return int(physical_melee_reach(engine, actor) or 5)


def radius(engine: Any, actor: Any) -> int:
    """"your melee reach + 10 feet"."""
    return _reach(engine, actor) + 10


def _patrollers(engine: Any) -> list[Any]:
    return [actor for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if actor.active and patrol(actor) is not None]


def inside(engine: Any, guardian: Any, creature: Any, position: Any = None) -> bool:
    if position is None:
        return engine._distance_actor_to_actor(guardian, creature) <= radius(engine, guardian)
    cells = engine._actor_cells(creature, position)
    return engine.grid.distance_between_cell_sets_ft(cells, engine._actor_cells(guardian)) <= radius(engine, guardian)


def _extra_responses(cl: int) -> int:
    return 3 if cl >= 17 else 2 if cl >= 11 else 1 if cl >= 5 else 0


# ------------------------------------------------------------------------------------------------ establishing Patrol
@effect("guardian_patrol")
def establish(ctx: Any, eff: dict[str, Any]) -> None:
    engine, me = ctx.engine, ctx.actor
    known = [kind for kind in ZONE_TALENTS if row(engine, me, f"zone_{kind}") is not None]
    complex_ok = row(engine, me, "complex_patrol") is not None and me.resources.get(FOCUS, 0) >= 1 and len(known) >= 2
    chosen: list[str] = []
    if len(known) == 1:
        chosen = known
    elif known:
        labels = {kind: ZONE_TALENTS[kind][1] for kind in known}
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "PATROL_ZONE", me.entity_id), me, CHOICE + "patrol_zone", known,
                     labels=labels, preferred=known[:2 if complex_ok else 1], minimum=1, maximum=2 if complex_ok else 1,
                     default_count=2 if complex_ok else 1,
                     name="Patrol Zone talent", target_id=me.entity_id,
                     prompt="Patrol: choose the Zone talent this Patrol uses" + (" (two with Complex Patrol, which spends Martial Focus)"
                                                                                 if complex_ok else "") + ".")
        chosen = [kind for kind in chosen if kind in labels][:2 if complex_ok else 1]
        if len(chosen) == 2:
            engine._spend_resource(me, FOCUS, 1, "TAL_GUARDIAN_COMPLEX_PATROL")
    old = patrol(me)
    if old is not None:
        from .rider_support import remove_instance

        remove_instance(engine, me, old.instance_id, ctx.source)
    for key in [key for key in me.turn_flags if key.startswith("guardian_round_patrol")]:
        me.turn_flags.pop(key, None)
    speed = int(engine._effective_speed(me))
    names = ", ".join(ZONE_TALENTS[kind][1].split(":")[0] for kind in chosen) or "no Zone talent"
    engine._apply_condition(me, PATROL, ctx.source, me.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={
        "zones": ",".join(chosen), "movement": speed, "radius_ft": radius(engine, me),
        "label": f"Patrol: a hostile creature moving into, out of or through the {radius(engine, me)}-foot Patrol Zone around "
                 f"{me.display_name} may be answered with a move and an opportunity attack ({names}); until {me.display_name}'s next turn"})
    note(engine, ctx.source, me, f"{me.display_name} establishes a Patrol ({radius(engine, me)} feet; {names}; {speed} feet of Patrol Movement).")


@hook("compile_actions")
def swift_patrol(info: dict[str, Any]) -> list[Any] | None:
    """Swift Guardian: "activate Patrol as a Bonus Action" for Martial Focus (its Challenge clause is combat/ext/guardian.py's)."""
    import copy

    from ..gate2_runtime_models import EconomyKind

    if "TAL_GUARDIAN_SWIFT_GUARDIAN" not in set(info.get("owned_ids") or ()):
        return None
    base = next((a for a in info.get("actions") or () if ((a.parameters or {}).get("typed") or {}).get("source") == PATROL_ID
                 and "#" not in a.source_definition_id), None)
    if base is None:
        return None
    return [base.model_copy(update={"source_definition_id": base.source_definition_id + "#swift", "economy": EconomyKind.BONUS_ACTION,
                                    "display_name": "Patrol (Swift Guardian: Bonus Action; spend Martial Focus, your readiness point)",
                                    "costs": (*tuple(base.costs or ()), (FOCUS, 1)), "parameters": copy.deepcopy(base.parameters)})]


# ------------------------------------------------------------------------------------------------ Patrol Responses
def _response_cost(engine: Any, guardian: Any, mover: Any) -> str | None:
    """"reaction", "extra", or None when no response is left."""
    from ..typed_reactions import _can_react

    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{mover.entity_id}"
    if guardian.turn_flags.get("guardian_round_patrol_turn") == turn:
        return None  # "may be made only once per triggering creature's turn"
    if not guardian.turn_flags.get("guardian_round_patrol_first"):
        return "reaction" if _can_react(engine, guardian) else None
    from .guardian_chassis import cultivation_level

    extra = guardian.turn_flags.get("guardian_round_patrol_extra") or ""
    used = int(extra.split(":")[1]) if extra.startswith(f"{engine.state.round_number}:") else 0
    return "extra" if used < _extra_responses(cultivation_level(engine, guardian)) else None


def _path(kwargs: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import Position

    payload = kwargs.get("payload") or {}
    cells = payload.get("path") or ([payload["destination"]] if payload.get("destination") else [])
    return [Position.model_validate(cell) for cell in cells]


@hook("event")
def patrol_watch(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("forced") or payload.get("teleport") or payload.get("reaction"):
        return
    patrollers = _patrollers(engine)
    mover = engine.state.actors.get(kwargs.get("actor_id")) if patrollers else None
    if mover is None or not mover.active:
        return
    path = _path(kwargs)
    for guardian in patrollers:
        if guardian.team_id == mover.team_id or guardian.entity_id == mover.entity_id or incapacitated(guardian):
            continue
        if not any(inside(engine, guardian, mover, cell) for cell in path):
            continue
        _respond(engine, guardian, mover)
        if not mover.active:
            return


def _respond(engine: Any, guardian: Any, mover: Any) -> None:
    from .. import stealth
    from ..typed_reactions import opportunity_attack, _opportunity_row
    from .granted_moves import commit, destinations

    if _opportunity_row(engine, guardian) is None or not stealth.sees(engine, guardian, mover):
        return
    held = patrol(guardian)
    budget = int((held.data or {}).get("movement") or 0) - int(guardian.turn_flags.get("guardian_round_patrol_moved") or 0)
    reach = _reach(engine, guardian)

    def in_reach(position: Any) -> bool:
        return engine._distance_actor_to_actor(guardian, mover, actor_position=position) <= reach

    spots = destinations(engine, guardian, max(0, budget), in_reach)
    if not spots:
        return
    spot, path, moved = spots[0]
    if moved:
        note(engine, PATROL_ID, guardian,
             f"Patrol Response movement for {guardian.display_name} is unavailable until movement validates opportunity attacks.", (mover,))
        return
    cost = _response_cost(engine, guardian, mover)
    if cost is None:
        return
    what = "your Reaction" if cost == "reaction" else "an extra Patrol Response (no Reaction)"
    step = f"move {engine.grid.distance_ft(guardian.position, spot)} feet of your Patrol Movement and " if moved else ""
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "PATROL_RESPONSE", guardian.entity_id, mover.entity_id),
                 guardian, CHOICE + "patrol_response", ["respond"],
                 labels={"respond": f"Patrol Response: {step}make an opportunity attack against {mover.display_name}"},
                 prompt=f"Patrol Response ({what}): {mover.display_name} moved through your Patrol Zone. "
                        f"{(step[0].upper() + step[1:] + 'make') if step else 'Make'} an opportunity attack against it?",
                 preferred=["respond"], allow_decline=True, target_id=guardian.entity_id, name="Patrol Response")
    if picked != ["respond"]:
        return
    with activation(engine, guardian, PATROL_ID):
        guardian.turn_flags["guardian_round_patrol_turn"] = f"{engine.state.round_number}:{engine.state.current_slot_index}:{mover.entity_id}"
        if cost == "reaction":
            guardian.turn_flags["guardian_round_patrol_first"] = 1
            guardian.reaction_available = False
        else:
            extra = guardian.turn_flags.get("guardian_round_patrol_extra") or ""
            used = int(extra.split(":")[1]) if extra.startswith(f"{engine.state.round_number}:") else 0
            guardian.turn_flags["guardian_round_patrol_extra"] = f"{engine.state.round_number}:{used + 1}"
        engine._append_event("REACTION_RESOLVED", PATROL_ID, actor_id=guardian.entity_id, target_ids=(mover.entity_id,),
                             payload={"reaction": "patrol_response", "extra": int(cost == "extra"),
                                      "gate3_reaction_available_after": bool(guardian.reaction_available)})
        if moved:
            guardian.turn_flags["guardian_round_patrol_moved"] = int(guardian.turn_flags.get("guardian_round_patrol_moved") or 0) + int(moved)
            commit(engine, guardian, path, PATROL_ID)
        note(engine, PATROL_ID, guardian, f"Patrol Response: {guardian.display_name} answers {mover.display_name}'s movement through its Patrol "
             "Zone with an opportunity attack.", (mover,))
        previous = getattr(engine, "_guardian_patrol_attack_target", None)
        engine._guardian_patrol_attack_target = mover.entity_id
        try:
            opportunity_attack(engine, guardian, mover, getattr(engine, "_active_intent", None), trigger="movement")
        finally:
            engine._guardian_patrol_attack_target = previous


@hook("after_hit")
def patrol_hit(ctx: Any, target: Any, kind: str) -> None:
    """Grant Patrol's hit rewards only from the settled attack outcome notification."""
    engine, guardian = ctx.engine, ctx.actor
    if (target is None or getattr(engine, "_guardian_patrol_attack_target", None) != target.entity_id
            or patrol(guardian) is None):
        return
    target = engine.state.actors.get(target.entity_id, target)
    from .guardian_chassis import regain_focus

    regain_focus(engine, guardian, "a Patrol attack hit")
    if "stand_still" in _zones(guardian) and target.active:
        from ..typed_executor import run_effects
        from .states import context

        ctx = context(engine, guardian, "TAL_GUARDIAN_STAND_STILL", [target])
        run_effects(ctx, [{"type": "speed", "becomes": 0, "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                           "evidence": "Stand Still: a Patrol attack hit reduces its Speed to 0 until the start of its next turn"}])
        note(engine, "TAL_GUARDIAN_STAND_STILL", guardian, f"Stand Still: {target.display_name}'s Speed is 0 until the start of its next turn.", (target,))


# ------------------------------------------------------------------------------------------------ Zone talents
@hook("zones", present=lambda engine: any("steel_hedge" in _zones(owner) for owner in _patrollers(engine)))
def steel_hedge(engine: Any) -> list[Any] | None:
    from .. import zones
    from ..gate2_runtime_models import Position, ZoneState

    out = []
    for guardian in _patrollers(engine):
        if "steel_hedge" not in _zones(guardian):
            continue
        reach = radius(engine, guardian)
        cells = tuple(Position(x=x, y=y) for y in range(engine.grid.height) for x in range(engine.grid.width)
                      if engine._distance_actor_to_cell(guardian, Position(x=x, y=y)) <= reach)
        out.append(ZoneState(
            zone_id=f"zone:aura:{guardian.entity_id}:TAL_GUARDIAN_STEEL_HEDGE", source_definition_id="TAL_GUARDIAN_STEEL_HEDGE",
            owner_id=guardian.entity_id, center=guardian.position, radius_cells=reach // engine.grid.square_size_ft, affected_cells=cells,
            concentration_link=False, duration_rounds=None, created_round=0,
            trigger_profile={"kind": zones.KIND, "name": "Steel Hedge: the Patrol Zone is difficult terrain for hostile creatures", "terrain": [],
                             "difficult": "hostile", "obscured": None, "color": zones.terrain_rules().get("default_color"), "follows_owner": True,
                             "shape": "emanation", "size_ft": reach, "triggers": [], "move_through": None, "talents": [], "inside": [],
                             "aura": True, "visual": {"material": "aura"}, "numbers": {}}))
    return out or None


@hook("ac")
def assist_the_line(engine: Any, target: Any) -> int:
    return 1 if any("assist_the_line" in _zones(g) and g.entity_id != target.entity_id and g.team_id == target.team_id
                    and inside(engine, g, target) for g in _patrollers(engine)) else 0


@hook("opportunity_allowed")
def clear_path(engine: Any, reactor: Any, mover: Any) -> bool | None:
    for guardian in _patrollers(engine):
        if ("clear_path" in _zones(guardian) and guardian.entity_id != mover.entity_id and guardian.team_id == mover.team_id
                and reactor.team_id != guardian.team_id and inside(engine, guardian, mover)):
            return False
    return None


@hook("turn_start")
def singularity_pull(engine: Any, actor: Any) -> None:
    for guardian in _patrollers(engine):
        if "singularity_patrol" not in _zones(guardian) or guardian.team_id == actor.team_id or not actor.active \
                or not inside(engine, guardian, actor) or engine._distance_actor_to_actor(guardian, actor) <= 5:
            continue
        from ..typed_executor import run_effects
        from .guardian_chassis import cultivation_level
        from .states import context

        feet = 10 if cultivation_level(engine, guardian) >= 11 else 5
        ctx = context(engine, guardian, "TAL_GUARDIAN_SINGULARITY_PATROL", [actor])
        run_effects(ctx, [{"type": "save", "ability": "str", "applies_to": "target",
                           "evidence": "Singularity Patrol: a hostile creature starting its turn in the Patrol Zone makes a Strength save",
                           "on_fail": [{"type": "forced_movement", "applies_to": "target", "direction": "toward", "distance_ft": feet,
                                        "evidence": f"Singularity Patrol: pulled {feet} feet toward the Guardian, stopping next to it"}],
                           "on_success": []}])
