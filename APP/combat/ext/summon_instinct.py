"""Summon orders and instinct, using the existing controlled-creature controller.

The ordinary native menu, knowledge context, AI restraint, option expansion and
intent executor remain authoritative. This provider adds only detached scoring
goals through ai_score_components; it never substitutes a second action resolver.
Commands use Needle checkpoints and persist one JSON-shaped next-turn order.
Free summons and mounts never enter summon_default_turn.
Guard actions with custom effects may publish parameters.summon_guard_action=True;
this provider also recognizes ordinary actions that apply the guarding condition.
Death servants publish that public action trait for their custom guard stance.
"""
from __future__ import annotations

from typing import Any
from ..gate2_runtime_models import ActorState, Position
from ..gate4_models import ComponentScore
from ..relations import ENEMY, relation
from . import hook

INSTINCT_RANGE_FT = 30
# Runaway-controller guard, not a menu/plan limit: every legal option remains
# available on each decision. Normal movement spends its finite allowance.
MAX_TURN_DECISIONS = 128
DIRECTIVE_KINDS = ("attack", "hold", "guard", "use", "hide", "follow")
SOURCE = "system:combat.summon_instinct"


@hook("summon_default_turn")
def take_default_turn(engine: Any, actor: ActorState, behavior: str) -> None:
    if actor.summon is not None:
        take_turn(engine, actor)


def set_directive(record, kind, *, target_id=None, action_id=None):
    """Store a one-turn order; IDs and integer square coordinates are JSON safe."""
    if kind not in DIRECTIVE_KINDS:
        raise ValueError(f"unknown summon directive: {kind}")
    if kind == "attack" and not target_id:
        raise ValueError("attack directive needs a target")
    if kind == "use" and not action_id:
        raise ValueError("use directive needs an action id")
    record["directive"] = {"kind": kind, "target_id": target_id, "action_id": action_id}


def _hostiles(engine, actor):
    from ..target_knowledge import knowledge
    return [other for other in engine.state.actors.values()
            if other.active and relation(engine, other, actor) == ENEMY
            and (known := knowledge(engine, actor, other)) is not None and known.mode == "DIRECT"]


@hook("choice_options")
def order_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    """Transport only this plug-in's order questions; unrelated choices remain untouched."""
    from .needle import option_spec
    return option_spec(choice_id, context, "choice:summon_order:")


@hook("command_resolved")
def command_orders(engine, owner, group, commanded_ids, intent, economy):
    """Each reached creature receives an owner-selected next-turn order.

    Manual control remains an explicit choice, preserving the entire stat-block
    menu for human and model pilots. AI preferences never remove any choices.
    """
    from .needle import ask, ai_controlled
    from ..target_knowledge import knowledge
    from ..senses import perceives_cell
    for cid in commanded_ids:
        creature = engine.state.actors[cid]
        record = creature.summon
        if not record or record.get("mountable") or record.get("command") == "free":
            continue
        prefix = f"choice:summon_order:{cid}"
        name = f"Command {creature.display_name}"
        def pick(suffix, options, labels, preferred=None):
            return ask(engine, intent, prefix + ":" + suffix, owner, prefix + ":" + suffix,
                       options, labels=labels, preferred=preferred, name=name, target_id=cid,
                       automatic=ai_controlled(engine, owner),
                       prompt=f"{name}: choose {suffix} for its next turn. Giving this command costs your Bonus Action.")
        kinds = ["manual", *DIRECTIVE_KINDS]
        enemies = _hostiles(engine, owner)
        preference = ("attack" if enemies else "follow") if ai_controlled(engine, owner) else "manual"
        kind = pick("order", kinds, {"manual": "Control its full turn yourself",
                    "attack": "Attack a chosen enemy", "hold": "Hold position and Dodge",
                    "guard": "Guard a creature or square; keep reactions ready",
                    "use": "Use one of its own actions or techniques",
                    "hide": "Take the Hide action if concealed", "follow": "Follow you safely"}, [preference])[0]
        if kind == "manual":
            record.pop("directive", None)
            continue
        target_id = action_id = None
        if kind in ("attack", "guard"):
            targets = [a for a in engine.state.actors.values() if a.active
                       and (k := knowledge(engine, owner, a)) is not None and k.mode == "DIRECT"
                       and (kind == "guard" or relation(engine, a, owner) == ENEMY)]
            labels = {a.entity_id: a.display_name for a in targets}
            if kind == "guard":
                # Every perceived square stays reachable, not just top-ranked cells.
                labels.update({f"square:{x}:{y}": f"Square ({x}, {y})"
                    for y in range(engine.grid.height) for x in range(engine.grid.width)
                    if perceives_cell(engine, owner, Position(x=x, y=y))})
            if not labels:
                kind = "hold"
            else:
                preferred = sorted(targets, key=lambda a: (engine._distance_actor_to_actor(owner, a), a.entity_id))
                target_id = pick("target", list(labels), labels, [preferred[0].entity_id] if preferred else None)[0]
        if kind == "use":
            actions = {aid: engine.action_catalog[aid].display_name for aid in creature.action_ids}
            # Basic stat-block combat options remain available too.
            actions.update({aid: engine.action_catalog[aid].display_name
                            for aid in ("system:combat.dodge", "system:combat.dash", "system:combat.disengage")})
            action_id = pick("action", list(actions), actions)[0]
        set_directive(record, kind, target_id=target_id, action_id=action_id)


def _context(engine, actor, directive):
    from ..gate4_context import build_decision_context
    from ..gate4_policy import PolicyLibrary
    from .ai_movement import personal_frame, perceived_movement_hazards
    policy = PolicyLibrary(engine.source_root).fallback()
    context = build_decision_context(engine, policy, for_ai=True, include_item_actions=bool(directive))
    frame = personal_frame(engine, actor, context.legal_candidates, policy)
    risks = perceived_movement_hazards(engine, actor, context.legal_candidates, frame)
    visible = {c.entity_id for c in frame.creatures if c.mode == "DIRECT"}
    candidates = tuple(c.model_copy(update={"metadata": {**c.metadata,
        **risks.get(c.candidate_id, {}),
        "reaction_exposure": [aid for aid in c.metadata.get("reaction_exposure", ()) if aid in visible]}})
        if c.kind == "MOVE" else c for c in context.legal_candidates)
    foes = _hostiles(engine, actor)
    goal = {"kind": "instinct", "hostiles": [a.entity_id for a in foes],
            "guard_actions": [aid for aid, info in context.tactics.get("actions", {}).items()
                              if any(c in ("guarding", "condition:typed.guarding")
                                     for c in info.get("conditions", ()))]}
    goal["guard_actions"].extend(aid for aid in actor.action_ids
                                if engine.action_catalog[aid].parameters.get("summon_guard_action")
                                and aid not in goal["guard_actions"])
    if directive:
        goal.update(directive)
    owner = engine.state.actors.get(actor.owner_id or "")
    owner_memory = next((c for c in frame.creatures if owner is not None and c.entity_id == owner.entity_id), None)
    if owner_memory is not None:
        x, y, z = owner_memory.position
        goal["owner_position"] = {"x": x, "y": y, "z": z}
    target = engine.state.actors.get(goal.get("target_id") or "")
    if target is not None and target.entity_id in visible:
        goal["target_position"] = target.position.model_dump()
    elif str(goal.get("target_id") or "").startswith("square:"):
        _, x, y = goal["target_id"].split(":")
        goal["target_position"] = {"x": int(x), "y": int(y), "z": 0}
    # Keep the ordinary controller ignorant of unseen creatures and enemy sheets.
    # Personal observations supply positions, never enemy HP, resources or defenses.
    actors = tuple(a if a.entity_id == actor.entity_id or relation(context, a, actor) != ENEMY
                   else a.model_copy(update={"current_hp": 100, "maximum_hp": 100,
                       "temporary_hp": 0, "armor_class": 0, "resources": {}, "conditions": ()})
                   for a in context.actors if a.entity_id == actor.entity_id or a.entity_id in visible)
    # A detached goal marks only this provider's local controller query.
    return context.model_copy(update={"legal_candidates": candidates, "actors": actors,
        "own_knowledge": frame,
        "tactics": {**context.tactics, "summon_goal": goal},
        "search_move_candidate_id": None})


@hook("ai_score_components")
def instinct_score(context, candidate, option_ids):
    """Goal preference only: all native candidates/options stay in the context."""
    goal = context.tactics.get("summon_goal")
    if goal is None:
        return None
    from ..gate2_grid import SquareGrid
    actor = next(a for a in context.actors if a.entity_id == context.active_actor_id)
    def distance(position, target):
        return SquareGrid.distance_cells(position, target) * 5
    foes = [a for a in context.actors if a.entity_id in goal["hostiles"]]
    kind = goal["kind"]
    target_id = goal.get("target_id")
    target_position = Position.model_validate(goal["target_position"]) if goal.get("target_position") else None
    strikes = [c for c in context.legal_candidates if c.kind == "ACTION"
               and any(t in goal["hostiles"] for t in c.target_ids)
               and (kind != "attack" or target_id in c.target_ids)]
    nearest_strike = min((distance(actor.position, a.position) for a in foes
                         if any(a.entity_id in c.target_ids for c in strikes)), default=None)
    value = -1000000
    if candidate.kind in ("END_TURN", "HOLD_POSITION"):
        value = 0
    elif kind == "use" and candidate.source_definition_id == goal.get("action_id"):
        value = 500000
    elif kind == "guard" and candidate.source_definition_id in goal["guard_actions"]:
        value = 200000
    elif kind in ("hold", "guard") and candidate.source_definition_id == "system:combat.dodge":
        value = 100000
    elif kind in ("instinct", "attack") and candidate in strikes:
        distances = [distance(actor.position, a.position) for a in foes if a.entity_id in candidate.target_ids]
        if distances and min(distances) == nearest_strike:
            value = 500000
    if candidate.kind == "MOVE":
        unsafe = candidate.metadata.get("hazard_exposure") or candidate.metadata.get("reaction_exposure")
        destination = candidate.destination
        toward, within = None, 5
        if kind == "guard":
            toward = target_position
        elif kind == "follow":
            toward = Position.model_validate(goal["owner_position"]) if goal.get("owner_position") else None
        elif kind == "attack":
            toward = target_position if not strikes else None
        elif kind == "instinct":
            if foes and not strikes:
                toward = min(foes, key=lambda a: (distance(actor.position, a.position), a.entity_id)).position
            elif not foes and goal.get("owner_position"):
                toward, within = Position.model_validate(goal["owner_position"]), INSTINCT_RANGE_FT
        if toward is not None and destination is not None and not unsafe:
            before, after = distance(actor.position, toward), distance(destination, toward)
            if before > within and after < before:
                value = 300000 - after * 100 - candidate.movement_cost_ft
    return (ComponentScore(component="summon_order", value=value,
                           explanation="Follow the next-turn order, or approach the nearest visible enemy safely."),)


def _execute(engine, intent):
    """Keep the enclosing table transaction and its answered reactions intact."""
    names = ("_active_intent", "_active_candidate", "_active_action_source_id")
    previous = tuple(getattr(engine, key, None) for key in names)
    outer = previous[0]
    if outer is not None:
        intent = intent.model_copy(update={"reaction_decisions": outer.reaction_decisions})
    try:
        engine.execute_intent(intent, within_transaction=True)
    finally:
        for key, value in zip(names, previous):
            setattr(engine, key, value)


def _unengaged_hold_text(engine, actor, goal):
    """Say where an unengaged summon actually ended up, never claiming proximity it lacks."""
    owner_position = goal.get("owner_position")
    if owner_position is None:
        return "has no enemy in sight and holds position"
    owner = Position.model_validate(owner_position)
    feet = engine.grid.distance_ft(actor.position, owner)
    if feet <= 5:
        return "has no enemy in sight and stays near its owner"
    if feet <= INSTINCT_RANGE_FT:
        return "has no enemy in sight and holds position within 30 feet of its owner"
    return "has no enemy in sight and cannot get closer to its owner safely, so it holds position"


def _blocked_move_text(engine, actor, sequence):
    """Say a move did not happen and why, in the engine's own words when it gave one."""
    events = [e for e in engine.events if e.sequence > sequence]
    for event in reversed(events):
        payload = event.payload or {}
        text = str(payload.get("rider") or payload.get("log") or "").strip()
        if not text:
            continue
        if text.startswith(actor.display_name):
            text = text[len(actor.display_name):].lstrip(" :;,-")
        for prefix in ("stops here:", "stops:"):
            if text.startswith(prefix):
                text = text[len(prefix):].lstrip()
                break
        return "could not move: " + text.removesuffix(".")
    if any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor.entity_id
           and (e.payload or {}).get("interrupted") for e in events):
        return "could not move: a reaction stopped its move"
    return "could not move: the way is blocked"


def take_turn(engine: Any, actor: ActorState) -> None:
    """Use native controlled-creature decisions, re-planning after each safe move."""
    from ..gate4_controller import LocalDeterministicController
    from .. import stealth
    # Keep the order visible to native option-listing policies throughout the turn.
    # Consume it only after successful execution; enclosing rollback retains it on a pause.
    directive = actor.summon.get("directive")
    kind = (directive or {}).get("kind")
    why = f"follows its order: {kind}" if directive else "acts on instinct"
    if kind == "hide":
        if actor.action_available and stealth.can_hide(engine, actor):
            stealth.hide(engine, actor, (actor.dexterity_score - 10) // 2, SOURCE)
            actor.action_available = False
            result = "takes the Hide action"
        else:
            result = "cannot hide in plain sight and holds position"
    else:
        result = None
        for _ in range(MAX_TURN_DECISIONS):
            context = _context(engine, actor, directive)
            choice = LocalDeterministicController().choose_primary_action(context)
            candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
            if candidate.kind in ("END_TURN", "HOLD_POSITION"):
                # A turn that already moved keeps its move description.
                if result is None:
                    if directive:
                        result = "holds position, keeping its reactions available"
                    elif context.tactics["summon_goal"]["hostiles"]:
                        result = "cannot reach a visible enemy safely and holds"
                    else:
                        result = _unengaged_hold_text(engine, actor, context.tactics["summon_goal"])
                break
            if candidate.kind == "MOVE":
                before = actor.position
                destination = candidate.destination
                sequence = engine.state.event_sequence
                _execute(engine, choice.intent)
                if actor.position == before:
                    # A stopped move must never read as a completed one.
                    result = _blocked_move_text(engine, actor, sequence)
                    break
                if directive:
                    result = "moves toward its ordered position"
                elif context.tactics["summon_goal"]["hostiles"]:
                    result = "moves toward the nearest enemy"
                else:
                    result = "moves back toward its owner"
                if engine.state.terminal_result is not None:
                    break
                if destination is not None and actor.position != destination:
                    # A reaction displaced the creature; the engine already
                    # ended that move. Do not start a second move this turn.
                    result = "stops moving after a reaction displaces it, keeping its reactions available"
                    break
                continue
            _execute(engine, choice.intent)
            action = engine.action_catalog.get(candidate.source_definition_id)
            action_name = action.display_name if action is not None else candidate.display_name
            target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
            result = (f"attacks {target.display_name} with {action_name}"
                      if target and relation(engine, actor, target) == ENEMY and kind != "use"
                      else f"uses {action_name}")
            break
        else:
            # The turn-start caller closes action/movement after this hook.
            # A broken controller/free-move cycle must not strand the table.
            result = "stops moving and ends its turn, keeping its reactions available"
    engine._append_event("SUMMON_TURN", SOURCE, actor_id=actor.entity_id,
                         payload={"text": f"{actor.display_name} {why}: {result}."})
    actor.summon.pop("directive", None)
