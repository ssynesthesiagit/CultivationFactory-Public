"""A short teleport a creature makes outside its own action (rider lane C4, 2026-09-30). Shared: used by combat/ext/void_riders.py
(Hollow Path Step, Void-Walking Guard, Void-Sovereign Incarnation, Court of the Empty Horizon's steps); any plug-in may use it.
Shadow self escapes use its visibility query and optional landing filter; typed_executor and the table menu use
its documented destination hooks. player_controls and destination_allowed are pure queries shared by those consumers.

  {"type": "reaction_teleport", "distance_ft": 20, "evidence": "..."}
        The user teleports to an unoccupied square it can see within ``distance_ft`` (Void, "Empty Step and Teleportation":
        "it requires an unoccupied destination you can see; it does not provoke Opportunity Attacks; it cannot cross Total
        Cover"). The square is asked of the user through the bounded choice transport (Ask me / Auto; staying put is always an
        option); the default is the square farthest from the triggering creature (the context's target). The step itself is the
        ordinary typed teleport (typed_executor block_movement with the chosen destination), so teleport locks
        (teleport_gate / teleport_check hooks) and zone entry still apply.

``destinations(engine, actor, feet)`` is the public query behind it: unoccupied, in-grid, not blocked squares within ``feet``
that the actor can see.

``ask_destination(ctx, reach)`` is the shared "where do you want to land?" question behind every self-teleport
(Empty Step and the rest): the printed rule is "Teleport to an unoccupied space you can see within range", so the
square is the user's to choose. It rides the bounded choice transport (``needle.ask``), which is the same Ask me / Auto
channel a reaction uses: a player is asked, an AI answers for itself, and because the answer is carried on the intent,
a reaction that interrupts between paying the cost and choosing does not lose it (combat/choice_checkpoints.py
``dynamic_choice`` replays it). Declining means staying put, with the ability's cost already spent. It is inert when
nothing is answering: an AI combatant, no transport, no options, or no reach return ``Destination(None, False)`` and
the caller keeps its own behaviour, so a saved fight replays unchanged.

The question is asked ONCE per represented hop (``hop_key``), not once per effect row: several abilities spell out one
teleport twice (a ``teleport`` row and the parser's ``movement(mode=teleport)`` row for the same hop) and the executor
runs both, so a question per row asks twice and pays for two hops.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from . import effect, hook

#: What a destination question produced. ``square`` is the chosen cell, or None to stay put; ``asked`` says a
#: player was actually put on the spot (True for both using a square and declining to). A caller that has to word
#: its "nothing happened" line needs to tell a decline apart from a fight nobody is answering in, and only the
#: transport knows that: ``needle.ask`` returns an empty list for both.
Destination = NamedTuple("Destination", [("square", Any), ("asked", bool)])

#: The choice ids this module asks a square through, so a table picks the square on the map (see ``map_pick``).
DESTINATION_CHOICES = ("choice:needle.teleport_destination", "choice:needle.reaction_teleport",
                       "choice:needle.subject_destination")


def destinations(engine: Any, actor: Any, feet: int, *, where: str | None = None, action: Any = None,
                 viewer: Any = None) -> list[Any]:
    """Legal landings for actor's body/origin, visible to viewer (default actor).

    Self menus and subject_repositioning share this query; only sight changes
    when a controller chooses a destination for a different subject.
    """
    from ..gate2_runtime_models import Position
    reach = max(0, int(feet)) // engine.grid.square_size_ft
    occupied = engine._occupied_cells_except(actor.entity_id)
    out = []
    for y in range(max(0, actor.position.y - reach), min(engine.grid.height, actor.position.y + reach + 1)):
        for x in range(max(0, actor.position.x - reach), min(engine.grid.width, actor.position.x + reach + 1)):
            cell = Position(x=x, y=y)
            if destination_allowed(engine, actor, cell, feet, where=where, action=action,
                                   occupied_cells=occupied, viewer=viewer):
                out.append(cell)
    return out


def destination_allowed(engine: Any, actor: Any, cell: Any, feet: int, *, where: str | None = None,
                        action: Any = None, occupied_cells=None, viewer: Any = None,
                        check_candidate: bool = True) -> bool:
    """Single-cell form of the shared query; used by destinations and candidate_allowed.

    Query-only projected footprints are never registered, mutated or persisted.
    This avoids enumerating the whole map again for every menu candidate.
    ``check_candidate=False`` is for the candidate hook itself: retain the
    action-specific landing rule without recursively re-entering that hook.
    """
    from .. import senses, zones, motion
    if cell is None or cell == actor.position or engine.grid.distance_ft(actor.position, cell) > feet:
        return False
    if not engine.grid.placement_legal(cell, footprint=engine._footprint(actor),
                                       occupied_cells=(engine._occupied_cells_except(actor.entity_id)
                                                       if occupied_cells is None else occupied_cells)):
        return False
    viewer = actor if viewer is None else viewer
    # General seam (Void Step and any other printed destination rule): an
    # ability that states its own "visible or precisely known" condition owns
    # the perception half of this query after reach and occupancy. True admits
    # a cell the shared sight rule would reject, False refuses one it would
    # accept; None keeps the shared sight rule unchanged.
    from .. import ext
    override = ext.run_strict("teleport_landing_allowed", engine, actor, cell, feet, action)
    if any(value is False for value in override):
        return False
    admitted = any(value is True for value in override)
    if not admitted:
        if not engine._line_of_sight_actor_to_cell(viewer, cell):
            return False
        seen = actor.model_copy(update={"position": cell, "conditions": {}})
        blinded_conditions = set(senses.rules().get("blinded_conditions") or [])
        blinded = any(c.condition_id in blinded_conditions for c in viewer.conditions.values())
        if blinded and not senses.perceives_without_sight(engine, viewer, seen):
            return False
        if zones.hidden_from(engine, viewer, seen):
            return False
    if where == "darkness" and not (motion.obscured(engine, actor) and motion.obscured_at(engine, cell)):
        return False
    if check_candidate and action is not None and action.target_kind == "SELF":
        # Reuse each owning plug-in's pure menu restrictions (anchors, arrays,
        # conditions). Do not regenerate candidates after payment: their economy
        # gates would incorrectly remove the action that is already resolving.
        from .. import ext
        from ..gate2_runtime_models import CandidateKind
        kind = {"BONUS_ACTION": CandidateKind.BONUS_ACTION, "REACTION": CandidateKind.REACTION,
                "NONE": CandidateKind.OPTIONAL_RIDER}.get(str(action.economy), CandidateKind.ACTION)
        candidate = engine._candidate(kind, actor, action.source_definition_id, action.display_name,
                                      target_ids=(actor.entity_id,), destination=cell,
                                      metadata={"teleport": True, "expected_damage": 0})
        if ext.any_false("candidate_allowed", engine, actor, candidate, action):
            return False
    return True


def player_controls(engine: Any, actor: Any) -> bool:
    """Use the native explicit-player control modes; headless/AI replays are inert."""
    return getattr(engine, "typed_control_modes", {}).get(actor.entity_id) in {
        "MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}


@hook("self_teleport_destination")
def bound_destination(ctx: Any, row: dict[str, Any], reach: int) -> Destination | None:
    """A menu-bound square is a candidate default, not the player's answer."""
    if not player_controls(ctx.engine, ctx.actor):
        return None
    answer = ask_destination(ctx, reach, name=str(ctx.action.display_name))
    if not answer.asked and getattr(ctx.engine, "_gate4_reaction_provider", None) is None:
        return None  # no player transport: preserve explicit headless/replay binding
    # No legal landing cell must never fall back to the stale candidate default.
    return Destination(answer.square, True)


@hook("candidate_allowed")
def player_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Narrow player self-teleport menus through the same query as the picker.

    Gate4's historical enumeration stays untouched for built-in AI and saves.
    """
    if (not player_controls(engine, actor) or not (candidate.metadata or {}).get("teleport")
            or not self_teleport_action(action)):
        return None
    from ..typed_executor import teleport_reach
    reach = teleport_reach(engine, actor, action)
    if reach is None:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    return destination_allowed(engine, actor, candidate.destination, reach, where=teleport_requirement(typed),
                               action=action, check_candidate=False)


def self_teleport_action(action: Any) -> bool:
    """Actual self teleports, excluding the shared picks_destination placement flag.

    Domain Armament and summon commands use that flag too; placing another
    creature/object must keep its native placement rather than submit a default.
    """
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return any(isinstance(row, dict) and row.get("applies_to") in (None, "self")
               and (row.get("type") == "teleport" or
                    (row.get("type") == "movement" and row.get("mode") == "teleport"))
               for row in typed.get("effects") or [])


@hook("action_destination_choice")
def action_destination_choice(engine: Any, action: Any) -> bool | None:
    """Ordinary player self teleports choose in resolution, once, on the map."""
    actor = engine.state.actors.get(action.owner_id)
    if actor is None or not player_controls(engine, actor) or not self_teleport_action(action):
        return None
    from ..typed_executor import teleport_reach
    return True if teleport_reach(engine, actor, action) is not None else None


def hop_reach(ctx: Any, row: dict[str, Any], reach: int) -> int:
    """Resolve a range-only parser duplicate to one unambiguous self-teleport.

    Explicit distances retain their own identities. A null-distance ``within_range``
    movement row represents the explicit teleport only when all self teleport rows
    agree on its reach; ambiguous multi-hop actions keep separate identities.
    """
    if (row.get("type") != "movement" or row.get("mode") != "teleport"
            or row.get("distance_ft") is not None or not row.get("within_range")):
        return reach
    reaches = set()
    for other in ctx.typed.get("effects") or []:
        if other.get("type") != "teleport" or other.get("applies_to") not in (None, "self"):
            continue
        token = other.get("distance_ft")
        if token == "speed":
            reaches.add(ctx.engine._effective_speed(ctx.actor))
        elif token == "half_speed":
            reaches.add(ctx.engine._effective_speed(ctx.actor) // 2)
        elif str(token or "").isdigit():
            reaches.add(int(token))
    return next(iter(reaches)) if len(reaches) == 1 else reach


def teleport_requirement(typed: dict[str, Any]) -> str | None:
    """Read the bound-menu contract: top-level requirement takes precedence."""
    return typed.get("teleport_where") or next(
        (row.get("where") for row in typed.get("effects") or []
         if row.get("type") == "teleport" and row.get("where")), None)


def hop_key(ctx: Any, reach: int) -> str:
    """The identity of one represented hop, so its answer is asked once and shared.

    Empty Step, Sand Burrow Step and Fold Step each carry a ``teleport`` row *and* the parser's
    ``movement(mode=teleport)`` row for one hop; the compiler copies both (combat/factory_compiler.py) and the
    executor runs both rows of one Context, so a question per row asks twice and, with the answer, teleports twice
    for one payment. The key is the use (intent), the creature that moves, the ability, the reach and the aimed
    target: every row spelling out the same teleport for that use shares it, and a second, genuinely different hop
    (the same ability again for a different target) does not.
    """
    intent = getattr(ctx, "intent", None) or getattr(getattr(ctx, "engine", None), "_active_intent", None)
    actor = getattr(ctx, "actor", None)
    return ":".join(["teleport_hop", str(getattr(intent, "intent_id", "") or ""),
                     str(getattr(actor, "entity_id", "") or ""), str(getattr(ctx, "source", "") or ""),
                     str(int(reach or 0)),
                     ",".join(str(getattr(target, "entity_id", "")) for target in (getattr(ctx, "targets", None) or []))])


def payment_text(ctx: Any) -> str:
    """Describe the compiled economy slot and resource pools paid for this use."""
    action = ctx.action
    economy = str(action.economy)
    slot = {"ACTION": "the Action", "BONUS_ACTION": "the Bonus Action", "REACTION": "the Reaction"}.get(economy)
    paid = [slot] if slot else []
    for resource, amount in action.costs:
        if amount > 0:
            name = resource.rsplit(".", 1)[-1].replace("_", " ").title()
            paid.append(f"{amount} {name} from its resource pool")
    return (" and ".join(paid) + (" remains" if len(paid) == 1 else " remain") + " spent either way") if paid else "no action or resource is spent"


@hook("choice_map_pick")
def map_pick(engine: Any, choice: dict, context: dict) -> dict | None:
    """A teleport's landing square is picked by clicking the map, not from a list of squares.

    Owner, round 24: "For any teleportation you can just click on an available square on the grid rather than
    a tooltip." A teleport is the one decision whose options are *places* rather than creatures or
    consequences, so the main map already draws them: the table highlights every legal square and the player
    clicks one, the same way Darkness and the other area placements are placed (Esc cancels).

    This is a presentation vote, not a rule: the squares, their option ids, their labels and the
    stay-put option are the transport's, and the answer rides the same candidate/destination binding as
    before, so nothing about what is legal or what happens next changes. It fires only for the registered
    destination questions this module asks (``DESTINATION_CHOICES``), so it is inert for every other choice
    in the game, for an AI combatant (which is never asked at all) and for any table that does not run this
    plug-in. The general seam lives in ``combat/choice_presentation.py`` ``map_pick``.
    """
    if str((context or {}).get("reaction_source_id") or "") not in DESTINATION_CHOICES:
        return None
    if (context or {}).get("reaction_source_id") == "choice:needle.subject_destination":
        subject = engine.state.actors.get((context or {}).get("affected_id"))
        name = subject.display_name if subject is not None else "the affected creature"
        return {"instruction": f"Click a highlighted square to move {name} there, or press Esc to leave them in place.",
                "cancel_label": "Leave them here"}
    return {"instruction": "Click a highlighted square to land there, or press Esc to stay where you are.",
            "cancel_label": "Stay here"}


def ask_destination(ctx: Any, reach: int, *, name: str = "", destination_filter: Any = None) -> "Destination":
    """Ask who is asking where to land; ``Destination`` says the square and whether anyone was asked.

    Shared by every self-teleport: combat/typed_executor.py ``block_movement`` calls it when a self-scoped
    teleport row has no square bound to the action. The question is asked through the bounded choice transport, so
    it is a real player decision: it pauses, it is labelled with the ability and the creature, and a reaction that
    interrupts between paying the cost and choosing does not drop it. Only a person answers it -- an AI combatant,
    an engine with no recorded control mode, no transport, and an ability with nowhere legal to land all keep the
    caller's own behaviour, so saved fights replay unchanged. Declining stays put (the cost is spent either way);
    ``asked`` tells the caller which of the two happened, so it can word its line for the case that really occurred.
    One hop is asked once, however many rows spell it out (see ``hop_key``).
    """
    from .needle import CHOICE, answered, ask, cell_id, checkpoint_id, position_of

    engine, actor = getattr(ctx, "engine", None), getattr(ctx, "actor", None)
    hops = getattr(ctx, "hop_destination", None)
    key = hop_key(ctx, reach)
    if isinstance(hops, dict) and key in hops:
        return hops[key]  # another row already spelled out this same hop; the one answer stands
    nothing = Destination(None, False)
    if engine is None or actor is None or not getattr(actor, "active", False) or int(reach or 0) <= 0:
        return nothing
    # Only a person answers this question. An AI combatant keeps whatever automatic choice it already had, and an
    # engine with no recorded control mode (a headless replay, the built-in AI) keeps the old behaviour, so saved
    # fights replay unchanged. Same test combat/gate2_engine.py uses for "explicit player movement".
    if not player_controls(engine, actor):
        return nothing
    cells = destinations(engine, actor, int(reach), where=teleport_requirement(ctx.typed), action=ctx.action)
    if destination_filter is not None:
        cells = [cell for cell in cells if destination_filter(cell)]
    if not cells:
        return nothing
    order = sorted(cells, key=lambda cell: (cell.y, cell.x))
    options = [cell_id(cell) for cell in order]
    label = name or str(getattr(getattr(ctx, "action", None), "display_name", "") or "Teleport")
    choice_id = CHOICE + "teleport_destination"
    checkpoint = checkpoint_id(engine, "teleport_destination", actor.entity_id)
    chosen = ask(engine, ctx.intent, checkpoint, actor, choice_id, options,
                 labels={cell_id(cell): f"Teleport to {cell.x},{cell.y}" for cell in order},
                 preferred=options[:1], allow_decline=True, name=label, default="decline",
                 target_id=actor.entity_id, prompt_context={"affected_id": actor.entity_id, "action_name": label},
                 prompt=(f"{label}: {actor.display_name} chooses an unoccupied square it can see, up to {reach} feet "
                         f"away, and teleports there, or stays where it is. A teleport costs no movement; "
                         f"{payment_text(ctx)}."))
    answer = Destination(position_of(chosen[0]) if chosen else None, answered(engine, checkpoint, actor, choice_id))
    if isinstance(hops, dict):
        hops[key] = answer
    return answer


@effect("reaction_teleport")
def reaction_teleport(ctx: Any, row: dict[str, Any]) -> bool:
    """Resolve the shared hop; return whether a legal destination was accepted.

    Optional grants may commit their own cost/allowance only after True. A
    declined landing or absence of visible legal squares returns False.
    Ordinary effect callers may ignore the result; their behavior is unchanged.
    """
    from dataclasses import replace

    from ..typed_executor import run_effects
    from .needle import CHOICE, ask, cell_id, checkpoint_id, position_of

    feet = int(row.get("distance_ft") or 0)
    actor = ctx.actor
    if not actor.active or feet <= 0:
        return False
    cells = destinations(ctx.engine, actor, feet, where=row.get("where"))
    if not cells:
        return False
    away = ctx.target if ctx.target is not None and ctx.target is not actor else None
    order = sorted(cells, key=lambda cell: (-(ctx.engine.grid.distance_ft(cell, away.position) if away is not None else 0), cell.y, cell.x))
    if not player_controls(ctx.engine, actor):
        order = order[:16]  # retain the historical AI choice inputs exactly
    options = [cell_id(cell) for cell in order]
    name = str(row.get("name") or ctx.action.display_name)
    # A hop granted by a Reaction names what set it off, in the printed words, so the question names the
    # ability, the triggering action and the creature.  The row's own ``trigger`` is kept when it has one.
    # combat/ext/trigger_source names the action actually in flight and the creature that used it, so the
    # question says "after Mo Ruo's Sever the Standard" instead of the row's own generic phrase.  A row with
    # no ``trigger`` is still named by the real action in flight; without one in flight the row keeps its
    # own words exactly as before.
    from . import trigger_source

    trigger = trigger_source.described(ctx, str(row.get("trigger") or ""), label=name, with_creature=True)
    opening = f"{name}: after {trigger}," if trigger else f"{name}:"
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "reaction_teleport", actor.entity_id), actor, CHOICE + "reaction_teleport",
                 options, labels={cell_id(cell): f"Teleport to {cell.x},{cell.y}" for cell in order}, preferred=options[:1], allow_decline=True,
                 name=name, prompt=f"{opening} {actor.display_name} may teleport up to {feet} feet to a square it can see (or stay where it is).")
    if not chosen:
        return False
    moved = replace(ctx, destination=position_of(chosen[0]))
    if player_controls(ctx.engine, actor):
        moved.hop_destination[hop_key(moved, feet)] = Destination(moved.destination, True)
    run_effects(moved, [{"type": "teleport", "applies_to": "self", "distance_ft": feet, "evidence": row.get("evidence") or f"teleport up to {feet} feet"}])
    return True
