"""Black Current Walker (Spirit Awakening Tradition; subpaths worker 2026-09-28, rider lane C8 2026-09-30: "i want everything we can
automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "27. Black Current Walker": Soulwake, CL3 Enter the Black Current, CL6 Turn the
Pursuer, CL10 River-Cut Passage, CL14 No Bank Holds the River, CL18 Procession of the Black River, Normalized Execution Notes).
No Spheres 5e or D&D 5.5e counterpart. Ownership: Enter the Black Current's ``black_current_walker`` row (feature_blocks.d/
subpaths.json) and the ``spirit_tradition`` rows of feature_blocks.d/riders_c8.json; every hook returns early without them.

Shared pieces (public, used by every feature below):
  soulwake(actor) / record_wake(...)   "A Soulwake is the path through spaces you actually moved across during the current turn ...
                                       up to Proficiency Bonus contiguous spaces ... lasts until the start of your next turn ... only
                                       one at a time": a condition on the walker holding the ordered cells (integers only).
  routes / choose_route               (combat/ext/spirit_traditions.py) legal unoccupied ends within ``feet`` and the route to each; ``through`` lists creatures whose
                                       spaces the route may cross ("you cannot end there"); ``ignore_plain_difficult`` drops the map's
                                       (nonmagical) difficult terrain. A route never crosses walls (River-Cut draws a straight line over them).
  walk(...)                            commits a route square by square (combat/ext/rider_movement.py step: no Opportunity Attacks, zones
                                       and hazards still apply per square), then Wake Mark and No Bank's exchange/escape, then records the
                                       Soulwake.

What runs:
  * Flow After the Strike (CL3): once on each of your turns, right after you deal damage to a hostile creature with Mind Spike, a
    Spirit Awakening feature, an unarmed strike or a weapon attack, you may move 10 feet without provoking (15 feet, and through its
    space, if it is Resonance Marked by you); recorded as a Soulwake. Asked (a player on Ask me picks the square or stays; the AI
    stays). It used to grant 10 feet of ordinary movement that did provoke.
  * Wake Mark (CL3): when a Black Current movement passes through a hostile creature's space, you may spend 1 Resonance (once per turn
    per creature): Wisdom save; failed -- Resonance Marked until the end of your next turn and it cannot make Opportunity Attacks
    against you meanwhile; success -- Speed -5 until the start of your next turn.
  * Turn the Pursuer (CL6 Reaction, 2 Resonance): when a creature declares an attack on you, before its roll: move up to 10 feet
    without provoking (a new Soulwake). If you left its reach or range it misses (the core's recheck); otherwise +2 AC against that
    attack. Carry the Reed (+1 Resonance): one willing adjacent ally moves 5 feet (into the space you left, or another legal space).
    The AI uses it when a square out of the attacker's reach exists.
  * River-Cut Passage (CL10 Action, 5 Resonance): pick the end square (within your Speed); the route passes through creatures,
    ignores the map's difficult terrain, crosses walls, and draws no Opportunity Attacks; the whole route is the Soulwake. Then up to
    Proficiency Bonus creatures whose spaces you entered or passed adjacent to make a Dexterity save: failed -- 5d8 of the chosen type,
    Resonance Marked until the end of your next turn, moved 5 feet to a side of the route; success -- half. Moonlit Extraction: one
    willing ally you passed can be carried instead (placed next to your end square). Choices are asked; the AI strikes hostiles only.
  * No Bank Holds the River (CL14): +10 feet Speed; moving through a creature's space with a Black Current feature costs nothing extra
    (the routes above); once on each of your turns, entering the space of a Resonance Marked hostile creature lets you exchange
    positions with it (Wisdom save; a success leaves you passing through); a Black Current step taken while Grappled or Restrained
    first makes a Cultivation Check against the hold's DC (success ends that hold; failure, no movement).
    Undertow Pursuit (Reaction, 4 Resonance; the generic "moved at least 15 feet" row, Resonance Marked creature within 60 feet):
    move up to half your Speed (at most 60 feet) toward a legal space within 10 feet of where it stopped, then one of: Mind Spike
    with one damage die fewer, one weapon attack, one Spiritual Pressure effect without a save, or move a willing adjacent creature
    10 feet (asked; the AI imposes Spiritual Pressure).
  * Procession of the Black River (CL18 Bonus Action, 10 Resonance, Concentration, 1 minute): a 40-foot aura that moves with you.
    Allies inside: +10 feet Speed, ignore the map's difficult terrain, a 5-foot step without provoking at the start of their turn
    (asked), 2 x Proficiency Bonus Temporary HP the first time each round they move 15 feet or more. Hostile creatures: difficult
    terrain; the first time each round one ends a voluntary move less than 10 feet from where it began, it makes a Wisdom save --
    failed: 3d8 Psychic or Cold, no Reactions until the start of its next turn, pushed 10 feet away from you; success: Speed -10 until
    the end of its next turn. Ten Thousand Tributaries (once on each of your turns, free): move yourself or a willing creature in the
    Domain 20 feet without provoking; exchange two willing creatures; a Resonance Marked hostile makes a Wisdom save (moved 15 feet,
    5 on a success); or River-Cut Passage for no Resonance at half Speed and 3d8 (once per activation). River Leaves No Corpse Behind
    (once per activation, your Reaction): an ally in the Domain about to drop to 0 HP is moved up to 30 feet within the Domain and
    left at 1 HP.

Plug-in surface: effects black_current_river_cut, black_current_aside, black_current_undertow, black_current_tributary; hooks
compile_block, damage_dealt, before_attack, hit_response, speed, difficult_exempt, turn_start_choice, event,
would_drop, candidate_allowed. Shared helpers used: spirit_traditions (row/is_spirit_feature/context/pick_creature/can_react),
needle (ask/checkpoint_id/cell_id/position_of/step_to), rider_movement.step, d20_rewrite.pool_id, spirit_awakening.spiritual_pressure.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.black_current_walker.feature."
ENTER_THE_BLACK_CURRENT = TRADITION + "enter_the_black_current"
TURN = TRADITION + "turn_the_pursuer"
RIVER_CUT = TRADITION + "river_cut_passage"
NO_BANK = TRADITION + "no_bank_holds_the_river"
PROCESSION = TRADITION + "procession_of_the_black_river"
WAKE = "condition:typed.black_current_soulwake"
RESCUED = "condition:typed.black_river_rescued"
RESONANCE = "resource:core.resonance"
_PURSUER = "_c8_turn_the_pursuer"
_ROUTE = "_c8_river_cut_route"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


PURSUER = TURN
PURSUER_GUARD = "condition:typed.pursuer_attack_guard"


@hook("reaction_subject_allowed")
def pursuer_no_early_branch(engine: Any, actor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """The attack checkpoint owns this reaction, including older compiled rows."""
    if row.get("feature_id") == PURSUER and not row.get("pursuer_checkpoint"):
        return False
    return None


@effect("pursuer_attack_response")
def pursuer_marker(ctx: Any, eff: dict[str, Any]) -> None:
    """Compiled ownership marker; before_attack resolves the attack branch."""
    return


@hook("before_attack")
def turn_the_pursuer(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Only an actual attack can use the attack branch; never roll the entry save.

    The native checkpoint owns eligibility and one-attack AC; C8 movement
    helpers record the Soulwake and the optional Carry the Reed movement.
    """
    from .. import typed_reactions as reactions
    from ..stealth import sees
    from ..senses import pinpoints, perceives_without_sight

    row = next((r for r in reactions._rows(engine, defender.entity_id, "generic")
                if r.get("feature_id") == PURSUER), None)
    # The printed trigger says "perceive", including Tremorsense. Its explicit
    # check below replaces only a legacy sight qualifier, not other reaction gates.
    owned = st.row(engine, defender, "turn_the_pursuer")
    if ((row is None and owned is None) or not (sees(engine, defender, attacker) or pinpoints(engine, defender, attacker)
                           or perceives_without_sight(engine, defender, attacker))
            or (row is not None and (not reactions._can_trigger(engine, defender, row)
                or not reactions._generic_affordable(engine, defender, row)
                or not reactions._subject_ok(engine, defender, attacker,
                                             {**row, "pursuer_checkpoint": True, "requires_sight": False})))
            or (row is None and (not st.can_react(defender) or defender.resources.get(RESONANCE, 0) < 2))):
        return None
    from .needle import ask, checkpoint_id, free_cells, cell_id, position_of, step_to
    from .choice_prompt import action_context

    routes = st.routes(engine, defender, 10) if engine._effective_speed(defender) > 0 else {defender.position: ((defender.position,), 0)}
    cells = {cell: cost for cell, (_path, cost) in routes.items()}
    # Creating a new wake with this movement allows any legal reachable space.
    options = [cell_id(c) for c in sorted(cells, key=lambda c: (-engine.grid.distance_ft(c, attacker.position), c.y, c.x))]
    action = engine.action_catalog.get(context["source_id"])
    name = action.display_name if action else "attack"
    picked = ask(engine, intent, checkpoint_id(engine, "Turn the Pursuer", attacker.entity_id, defender.entity_id,
                                             context.get("attack_index", 1)), defender,
                 "choice:needle.black_current.turn_the_pursuer", options, allow_decline=True, default="first", name="Turn the Pursuer",
                 labels={cell_id(c): f"Move to {c.x},{c.y} ({cells[c]} feet); spend your Reaction and 2 Resonance" for c in cells},
                 target_id=defender.entity_id, prompt_context=action_context(engine, attacker, context["source_id"], defender),
                 prompt=f"Turn the Pursuer: {attacker.display_name}'s {name} targets {defender.display_name}. "
                        "Spend your Reaction and 2 Resonance (your Spirit resource) to move up to 10 feet without Opportunity Attacks? "
                        "The attack misses if it cannot reach you; otherwise gain +2 AC against this attack only.")
    if not picked or not can_step(engine, defender, TURN):
        return None
    with activation(engine, defender, PURSUER):
        if row is not None:
            reactions._open(engine, row, defender, (attacker.entity_id,), "ATTACK_DECLARED")
            reactions._spend_generic(engine, defender, row)
        else:
            engine._spend_resource(defender, RESONANCE, 2, TURN)
        defender.reaction_available = False
        left = defender.position
        path = routes[position_of(picked[0])][0]
        if len(path) > 1:
            walk(engine, defender, path, TURN, intent, wake_limit=2)
            _carry_the_reed(engine, defender, left, intent)
        engine._apply_condition(defender, PURSUER_GUARD, PURSUER, defender.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"attacker_id": attacker.entity_id, "attack_source": context["source_id"],
                                      "attack_index": int(context.get("attack_index", 1)),
                                      "label": "Turn the Pursuer: +2 AC against the triggering attack only"})
        engine._append_event("REACTION_RESOLVED", PURSUER, actor_id=defender.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "ac_bonus": 2})
        return {}  # The existing checkpoint rechecks legal targeting after movement.


@hook("ac")
def pursuer_attack_ac(engine: Any, target: Any) -> int | None:
    guards = [c for c in target.conditions.values() if c.condition_id == PURSUER_GUARD]
    if not guards:
        return None
    # d20_context derives AC by calling this hook again. Read only the native
    # scope's identity here, without invoking that derived AC calculation.
    frames = getattr(engine, "_d20_scopes", ())
    context = frames[-1] if frames else None
    if not context or context.get("kind") != "attack" or context.get("target_id") != target.entity_id:
        return None
    for c in guards:
        if (c.data.get("attacker_id") == context.get("actor_id")
                and c.data.get("attack_source") == context.get("source_id")
                and c.data.get("attack_index") == context.get("attack_index")):
            return 2
    return None


@hook("attack_roll_finished")
def pursuer_guard_finished(ctx: Any, target: Any, eff: Any, roll_id: str) -> None:
    """Remove the owned guard on hit, miss or an aborted typed attack."""
    for c in list(target.conditions.values()):
        if c.condition_id == PURSUER_GUARD and c.data.get("attacker_id") == ctx.actor.entity_id and c.data.get("attack_source") == ctx.source:
            ctx.engine._remove_condition(target, PURSUER_GUARD, PURSUER)


@hook("event")
def pursuer_guard_rolled(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Native AC is computed before ATTACK_ROLLED; also clean legacy rolls."""
    if event_type != "ATTACK_ROLLED":
        return
    targets = [engine.state.actors[t] for t in kwargs.get("target_ids") or () if t in engine.state.actors]
    if not any(c.condition_id == PURSUER_GUARD for target in targets for c in target.conditions.values()):
        return
    frames = getattr(engine, "_d20_scopes", ())
    context = frames[-1] if frames else None
    if not context or context.get("kind") != "attack":
        return
    for target in targets:
        for c in list(target.conditions.values()):
            if (c.condition_id == PURSUER_GUARD and c.data.get("attacker_id") == kwargs.get("actor_id")
                    and c.data.get("attack_source") == context.get("source_id")
                    and c.data.get("attack_index") == context.get("attack_index")):
                engine._remove_condition(target, PURSUER_GUARD, PURSUER)


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "black_current_walker" and row.get("kind") == "flow_after_the_strike"]


@hook("compile_block")
def black_current_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "black_current_walker":
        return None
    return [{**row, "block": "black_current_walker", "kind": spec.get("kind")}]


def _pb(engine: Any, actor: Any) -> int:
    return int(getattr(actor, "proficiency_bonus", 0) or 0) or 2


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    """The walker's compiled numbers (save DC, Proficiency Bonus, key modifier), read from one of its own typed actions."""
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        numbers = (((action.parameters or {}).get("typed") or {}).get("numbers") if action is not None else None) or {}
        if numbers.get("save_dc"):
            return dict(numbers)
    return {"pb": _pb(engine, actor), "save_dc": 8 + _pb(engine, actor), "key_mod": 0, "cl": 1}


def _feature_action(engine: Any, actor: Any, feature: str) -> Any:
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        if action is not None and st.feature_of(action) == feature:
            return action
    base = next(iter(engine.action_catalog.values()))
    return base.model_copy(update={"source_definition_id": feature, "display_name": feature.rsplit(".", 1)[-1].replace("_", " ").title(),
                                   "parameters": {"typed": {"numbers": _numbers(engine, actor), "effects": [], "riders": []}}})


def _ctx(engine: Any, actor: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, actor, _feature_action(engine, actor, feature), targets, _numbers(engine, actor), intent)


# ------------------------------------------------------------------------------------------------------------ Soulwake
def soulwake(actor: Any) -> list[tuple[int, int]]:
    held = next((c for c in actor.conditions.values() if c.condition_id == WAKE and c.source_actor_id == actor.entity_id), None)
    return [(int(x), int(y)) for x, y in ((held.data or {}).get("cells") or [])] if held is not None else []


def record_wake(engine: Any, actor: Any, path: list[Any], source: str, *, limit: int | None) -> None:
    cells = [(int(cell.x), int(cell.y)) for cell in path[1:]]
    if not cells:
        return
    if limit is not None:
        cells = cells[-limit:]
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == WAKE and held.source_actor_id == actor.entity_id:  # "creating another replaces it"
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": WAKE, "instance_id": iid, "reason": "REPLACED"})
    engine._apply_condition(actor, WAKE, source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"cells": [[x, y] for x, y in cells], "label": f"Soulwake ({len(cells)} spaces, until the start of your next turn)"})


# ------------------------------------------------------------------------------------------------------------- routes
def _line(start: Any, end: Any) -> list[Any]:
    """Grid squares on the straight line from start to end (a route across walls, River-Cut's "you can move across walls")."""
    from ..gate2_runtime_models import Position

    x0, y0, x1, y1 = start.x, start.y, end.x, end.y
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, cells = dx + dy, [Position(x=x0, y=y0)]
    while (x0, y0) != (x1, y1):
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
        cells.append(Position(x=x0, y=y0))
    return cells


def _through_creatures(engine: Any, actor: Any, path: list[Any]) -> list[Any]:
    cells = {(cell.x, cell.y) for cell in path[1:]}
    return [other for other in engine.state.actors.values()
            if other.active and other.entity_id != actor.entity_id and cells & set(engine._actor_cells(other))]


# -------------------------------------------------------------------------------------------------------------- walk
def _grip(actor: Any) -> Any:
    from ..typed_executor import CONDITION_PREFIX

    return next((c for c in actor.conditions.values() if c.condition_id in (CONDITION_PREFIX + "grappled", CONDITION_PREFIX + "restrained")), None)


def can_step(engine: Any, actor: Any, source: str) -> bool:
    """A Black Current step is movement: it needs Speed. While Grappled or Restrained, No Bank Holds the River's walker first makes
    a Cultivation Check against the hold's DC; a success ends that hold, a failure means the movement fails."""
    grip = _grip(actor)
    if grip is None:
        return engine._effective_speed(actor) > 0
    if st.row(engine, actor, "no_bank_holds_the_river") is None:
        return False
    numbers = _numbers(engine, actor)
    dc = int((grip.data or {}).get("escape_dc") or (grip.data or {}).get("dc") or numbers.get("save_dc") or 10)
    bonus = int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0)
    roll = engine.roll_check(modifier=bonus, actor_id=actor.entity_id, reason=f'CHECK:{NO_BANK}:grip')
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", NO_BANK, actor_id=actor.entity_id,
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Cultivation Check (Continuous Current)"})
    if not success:
        note(engine, NO_BANK, actor, f"{actor.display_name}'s spiritual step fails to slip the hold (Cultivation Check {roll.total} against DC {dc}).")
        return False
    for iid, held in list(actor.conditions.items()):
        if held is grip:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": grip.condition_id, "instance_id": iid, "reason": "ESCAPED"})
    note(engine, NO_BANK, actor, f"{actor.display_name}'s spiritual step slips the hold (Cultivation Check {roll.total} against DC {dc}).")
    return engine._effective_speed(actor) > 0


def walk(engine: Any, actor: Any, path: tuple[Any, ...], source: str, intent: Any, *, wake_limit: int | None) -> None:
    """Commit a Black Current route, with Wake Mark on the hostile creatures it passes through and No Bank's exchange."""
    from .rider_movement import step

    path = list(path)
    if len(path) < 2:
        return
    exchange = _exchange_point(engine, actor, path)
    if exchange is not None:
        index, creature = exchange
        step(engine, actor, path[:index], source)
        if actor.active and actor.position == path[index - 1] and _try_exchange(engine, actor, creature, source, intent):
            record_wake(engine, actor, path[:index + 1], source, limit=wake_limit)
            return
        step(engine, actor, path[index - 1:], source)
    else:
        step(engine, actor, path, source)
    passed = [c for c in _through_creatures(engine, actor, path[:-1]) if c.team_id != actor.team_id]
    for creature in passed:
        _wake_mark(engine, actor, creature, intent)
    record_wake(engine, actor, path, source, limit=wake_limit)


def _exchange_point(engine: Any, actor: Any, path: list[Any]) -> tuple[int, Any] | None:
    if st.row(engine, actor, "no_bank_holds_the_river") is None or engine.state.current_actor_id != actor.entity_id:
        return None
    if actor.turn_flags.get("black_current_exchange"):
        return None
    for index, cell in enumerate(path[1:], start=1):
        for other in engine.state.actors.values():
            if (other.active and other.team_id != actor.team_id and (cell.x, cell.y) in set(engine._actor_cells(other))
                    and _te().bears_mark(other, actor.entity_id, "Resonance")):
                return index, other
    return None


def _try_exchange(engine: Any, actor: Any, creature: Any, source: str, intent: Any) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "BLACK_CURRENT_EXCHANGE", creature.entity_id), actor,
                        "choice:needle.black_current.exchange", ["exchange"],
                        labels={"exchange": f"Exchange positions with {creature.display_name} (it makes a Wisdom save)"},
                        prompt=f"Continuous Current: {actor.display_name} enters the space of {creature.display_name}, Resonance Marked by you. "
                               "Try to exchange positions with it? On a failed Wisdom save you swap places; on a success you pass through.",
                        preferred=[], allow_decline=True, default="decline", name="No Bank Holds the River: exchange positions",
                        feature_id=NO_BANK, target_id=creature.entity_id)
    if not chosen:
        return False
    actor.turn_flags["black_current_exchange"] = True
    here, there = actor.position, creature.position
    footprint_a, footprint_c = engine._footprint(actor), engine._footprint(creature)
    others = engine._occupied_cells_except(actor.entity_id) - set(engine._actor_cells(creature))
    fits = (engine.grid.placement_legal(there, footprint=footprint_a, occupied_cells=others)
            and engine.grid.placement_legal(here, footprint=footprint_c, occupied_cells=others))
    ctx = _ctx(engine, actor, NO_BANK, [creature], intent)
    failed = _save(ctx, creature, "wis")
    if not failed or not fits:
        note(engine, NO_BANK, actor, f"The exchange with {creature.display_name} fails; {actor.display_name} passes through its space.")
        return False
    creature.position = here  # a simultaneous spiritual displacement (Normalized Execution Notes): evented for both below
    actor.position = there
    engine._append_event("MOVEMENT_COMMITTED", NO_BANK, actor_id=creature.entity_id,
                         payload={"destination": here.model_dump(mode="json"), "cost_ft": 0, "forced": True,
                                  "path": [there.model_dump(mode="json"), here.model_dump(mode="json")]})
    engine._append_event("MOVEMENT_COMMITTED", NO_BANK, actor_id=actor.entity_id,
                         payload={"destination": there.model_dump(mode="json"), "cost_ft": 0, "without_provoking": True,
                                  "path": [here.model_dump(mode="json"), there.model_dump(mode="json")]})
    from .. import zones

    zones.sync_inside(engine, NO_BANK)
    note(engine, NO_BANK, actor, f"{actor.display_name} and {creature.display_name} exchange positions (Continuous Current).", (creature,))
    return True


def _save(ctx: Any, subject: Any, ability: str, on_fail: list[Any] | None = None, on_success: list[Any] | None = None) -> bool:
    """Run one typed save for ``subject``; True when it failed."""
    before = len(ctx.engine.events)
    sub = st.context(ctx.engine, ctx.actor, ctx.action, [subject], ctx.numbers, ctx.intent)
    _te().block_save(sub, {"type": "save", "ability": ability, "applies_to": "target", "on_fail": on_fail or [], "on_success": on_success or []})
    rolled = [e for e in ctx.engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == subject.entity_id]
    if not rolled:
        return False
    payload = rolled[-1].payload or {}
    if "success" in payload:
        return not payload["success"]
    return int((payload.get("roll") or payload).get("total") or 0) < int(payload.get("dc") or 0)


def _wake_mark(engine: Any, actor: Any, creature: Any, intent: Any) -> None:
    if not _rows(engine, actor) or not creature.active:
        return
    flag = f"wake_mark:{creature.entity_id}"
    if actor.turn_flags.get(flag) or actor.resources.get(RESONANCE, 0) < 1:
        return
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "WAKE_MARK", creature.entity_id), actor, "choice:needle.black_current.wake_mark",
                        ["mark"], labels={"mark": f"Wake Mark {creature.display_name} (1 Resonance; it makes a Wisdom save)"},
                        prompt=f"Wake Mark: your Black Current movement passed through {creature.display_name}'s space. Spend 1 Resonance? "
                               "On a failed Wisdom save it becomes Resonance Marked until the end of your next turn and cannot make "
                               "Opportunity Attacks against you; on a success its Speed drops by 5 feet until the start of your next turn.",
                        preferred=["mark"], allow_decline=True, name="Wake Mark", feature_id=ENTER_THE_BLACK_CURRENT, target_id=creature.entity_id)
    if not chosen:
        return
    actor.turn_flags[flag] = True
    engine._spend_resource(actor, RESONANCE, 1, ENTER_THE_BLACK_CURRENT)
    ctx = _ctx(engine, actor, ENTER_THE_BLACK_CURRENT, [creature], intent)
    until = {"duration": {"kind": "until_end_of_your_next_turn"}}
    _save(ctx, creature, "wis",
          on_fail=[{"type": "mark", "mark": "Resonance", "applies_to": "target", **until, "evidence": "It becomes Resonance Marked until the end of your next turn"},
                   {"type": "reaction_denied", "applies_to": "target", **until,
                    "evidence": "cannot take opportunity attacks against you during that duration"}],
          on_success=[{"type": "speed", "applies_to": "target", "flat": -5, "expires_on": "START_OF_SOURCE_NEXT_TURN",
                       "evidence": "Its Speed is reduced by 5 feet until the start of your next turn"}])


# ------------------------------------------------------------------------------------------------- Flow After the Strike
def _qualifies(ctx: Any) -> bool:
    effect_row = getattr(ctx, "attack_effect", None) or {}
    if ctx.action.display_name == "Mind Spike" or st.is_spirit_feature(ctx.action):
        return True
    # Printed: "an unarmed strike, or a weapon attack with a weapon you are proficient with". A compiled weapon row
    # carries the character's own training, so a non-proficient weapon no longer counts as a qualifying strike.
    return (effect_row.get("attack_kind") in ("unarmed", "natural_weapon") or ".natural." in ctx.source
            or st.proficient_weapon(ctx.typed))


@hook("damage_dealt")
def flow_after_the_strike(ctx: Any, target: Any, amount: int) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not _rows(engine, actor) or actor.turn_flags.get("flow_after_the_strike") or engine.state.current_actor_id != actor.entity_id:
        return
    if amount <= 0 or target is None or target.team_id == actor.team_id or not actor.active or not _qualifies(ctx):
        return
    marked = _te().bears_mark(target, actor.entity_id, "Resonance")
    feet = 15 if marked else 10
    if not can_step(engine, actor, ENTER_THE_BLACK_CURRENT):
        return
    options = st.routes(engine, actor, feet, through=(target,) if marked and target.active else ())
    path = st.choose_route(engine, actor, options, ctx.intent, checkpoint="FLOW_AFTER_THE_STRIKE",
                         prompt=f"Flow After the Strike: after damaging {target.display_name} with {ctx.action.display_name}, "
                                f"{actor.display_name} may move up to {feet} feet without provoking Opportunity Attacks"
                                + (" (and through its space: it is Resonance Marked by you)." if marked else "."),
                         name="Flow After the Strike", feature=ENTER_THE_BLACK_CURRENT)
    if path is None:
        return
    actor.turn_flags["flow_after_the_strike"] = True
    walk(engine, actor, path, ENTER_THE_BLACK_CURRENT, ctx.intent, wake_limit=_pb(engine, actor))


# ----------------------------------------------------------------------------------------------------- Turn the Pursuer
def _carry_the_reed(engine: Any, walker: Any, left: Any, intent: Any) -> None:
    if walker.resources.get(RESONANCE, 0) < 1:
        return
    near = [other for other in engine.state.actors.values() if other.active and other.team_id == walker.team_id and other is not walker
            and engine.grid.distance_ft(left, other.position) <= 5]
    if not near:
        return
    ally = st.pick_creature(engine, intent, walker, near, checkpoint="CARRY_THE_REED", choice_id="choice:needle.black_current.carry_the_reed",
                            prompt=f"Carry the Reed (1 more Resonance): move one willing creature next to where {walker.display_name} stood "
                                   "5 feet (into the space you left or another legal space) without provoking?",
                            name="Carry the Reed", feature_id=TURN, allow_decline=True)
    if ally is None:
        return
    options = st.routes(engine, ally, 5)
    path = st.choose_route(engine, walker, options, intent, checkpoint="CARRY_THE_REED_TO", prompt=f"Carry the Reed: where does {ally.display_name} move?",
                         name="Carry the Reed", feature=TURN, preferred=left if left in options else None, stay=False)
    if path is None:
        return
    from .rider_movement import step

    engine._spend_resource(walker, RESONANCE, 1, TURN)
    step(engine, ally, list(path), TURN)
    note(engine, TURN, walker, f"Carry the Reed: {ally.display_name} moves 5 feet with {walker.display_name}.", (ally,))


# -------------------------------------------------------------------------------------------------- River-Cut Passage
@effect("black_current_river_cut")
def river_cut(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    destination = ctx.destination if ctx.destination is not None else getattr(ctx.intent, "destination", None)
    if destination is None or destination == actor.position or not can_step(engine, actor, ctx.source):
        return
    feet = engine._effective_speed(actor) // (2 if row.get("half_speed") else 1)
    options = st.routes(engine, actor, feet, all_creatures=True, ignore_plain_difficult=True)
    path = next((p for spot, (p, _c) in options.items() if spot == destination), None)
    if path is None:  # "you can move across walls": straight over what blocks the ordinary route
        path = tuple(_line(actor.position, destination))
        if (len(path) - 1) * engine.grid.square_size_ft > feet:
            return
    path = list(path)
    route_cells = {(cell.x, cell.y) for cell in path}
    passed = [other for other in engine.state.actors.values() if other.active and other.entity_id != actor.entity_id and any(
        max(abs(cx - rx), abs(cy - ry)) <= 1 for cx, cy in engine._actor_cells(other) for rx, ry in route_cells)]
    from .rider_movement import step

    step(engine, actor, path, ctx.source)
    record_wake(engine, actor, path, ctx.source, limit=None)  # "with no normal Proficiency Bonus space limit for this activation"
    passed = [other for other in passed if other.active]
    count = int(ctx.numbers.get("pb") or 2)
    allies = [other for other in passed if other.team_id == actor.team_id]
    carried = st.pick_creature(engine, ctx.intent, actor, allies, checkpoint="MOONLIT_EXTRACTION", choice_id="choice:needle.black_current.extraction",
                               prompt="Moonlit Extraction: carry one willing ally you passed with you instead of striking it?",
                               name="Moonlit Extraction", feature_id=RIVER_CUT, allow_decline=True) if allies else None
    if carried is not None:
        spots = st.routes(engine, carried, 200, all_creatures=True)
        near = [cell for cell in spots if cell != carried.position and engine.grid.distance_ft(cell, actor.position) <= 5]
        if near:
            from .needle import step_to

            step_to(engine, carried, min(near, key=lambda c: (c.y, c.x)), ctx.source)
            note(engine, ctx.source, actor, f"Moonlit Extraction: {actor.display_name} carries {carried.display_name} along the current.", (carried,))
            count -= 1
    candidates = [other for other in passed if other is not carried]
    if not candidates or count <= 0:
        return
    from . import needle

    by_id = {other.entity_id: other for other in candidates}
    preferred = [other.entity_id for other in candidates if other.team_id != actor.team_id][:count]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "RIVER_CUT", actor.entity_id), actor, "choice:needle.black_current.river_cut",
                        list(by_id), labels={key: other.display_name for key, other in by_id.items()}, preferred=preferred, minimum=0,
                        maximum=count, allow_decline=True, default="all", default_count=len(preferred),
                        prompt=f"River-Cut Passage: choose up to {count} creatures whose spaces you entered or passed next to; each makes a "
                               "Dexterity save.", name="River-Cut Passage", feature_id=RIVER_CUT)
    struck = [by_id[key] for key in chosen if key in by_id]
    if not struck:
        return
    engine.__dict__[_ROUTE] = [[cell.x, cell.y] for cell in path]
    try:
        sub = st.context(engine, actor, ctx.action, struck, ctx.numbers, ctx.intent)
        _te().run_effects(sub, row.get("effects") or [])
    finally:
        engine.__dict__.pop(_ROUTE, None)


@effect("black_current_aside")
def aside(ctx: Any, row: dict[str, Any]) -> None:
    """"is moved 5 feet to either side of your route if a legal space exists": the walker picks the square (the AI the one farthest
    from the route)."""
    engine, subject = ctx.engine, ctx.target
    route = {tuple(cell) for cell in engine.__dict__.get(_ROUTE) or []}
    if subject is None or not subject.active or not route:
        return
    options = {cell: v for cell, v in st.routes(engine, subject, 5, all_creatures=False).items()
               if cell != subject.position and (cell.x, cell.y) not in route}
    if not options:
        return
    far = max(options, key=lambda c: (min(max(abs(c.x - x), abs(c.y - y)) for x, y in route), -c.y, -c.x))
    path = st.choose_route(engine, ctx.actor, options, ctx.intent, checkpoint="RIVER_CUT_ASIDE",
                         prompt=f"River-Cut Passage: {subject.display_name} failed its save. Move it 5 feet to which side of your route?",
                         name="River-Cut Passage", feature=RIVER_CUT, preferred=far, stay=False)
    if path is None:
        return
    from .needle import step_to

    step_to(engine, subject, path[-1], ctx.source)


# --------------------------------------------------------------------------------------------- No Bank Holds the River
@hook("speed")
def continuous_current(engine: Any, actor: Any) -> int | None:
    return 10 if st.row(engine, actor, "no_bank_holds_the_river") is not None else None


@effect("black_current_undertow")
def undertow(ctx: Any, row: dict[str, Any]) -> None:
    """Undertow Pursuit: the generic "moved at least 15 feet" reaction row has already checked the trigger, the Resonance Mark, the
    range and paid 4 Resonance; this is the pursuit and the one follow-up."""
    intent = ctx.intent or ctx.engine._active_intent  # the generic moved row runs without its own intent
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active or not can_step(engine, actor, ctx.source):
        return
    feet = min(60, engine._effective_speed(actor) // 2)
    # "The destination must be a legal space within 10 feet of the target's resolved destination and no more than 60 feet from
    # your origin" (Undertow Pursuit Record); with none in reach the pursuit fails -- "Resonance is spent because the pursuit was
    # attempted" -- and there is no arrival to choose a follow-up from.
    options = {cell: v for cell, v in st.routes(engine, actor, feet, through=()).items()
               if engine.grid.distance_ft(cell, target.position) <= 10}
    if not options:
        note(engine, NO_BANK, actor, f"Undertow Pursuit: no legal space within 10 feet of {target.display_name} is within reach; the pursuit fails.", (target,))
        return
    if actor.position not in options or len(options) > 1:
        best = min(options, key=lambda c: (engine.grid.distance_ft(c, target.position), options[c][1], c.y, c.x))
        path = st.choose_route(engine, actor, options, intent, checkpoint="UNDERTOW_PURSUIT",
                             prompt=f"Undertow Pursuit: move up to {feet} feet toward {target.display_name} (to within 10 feet of where it stopped).",
                             name="Undertow Pursuit", feature=NO_BANK, preferred=best, stay=actor.position in options)
        if path is not None:
            walk(engine, actor, path, NO_BANK, intent, wake_limit=_pb(engine, actor))
        elif actor.position not in options:
            return
    from . import needle

    labels = {"pressure": f"Impose your Spiritual Pressure effect on {target.display_name} (no save)",
              "spike": f"Mind Spike against {target.display_name}, one damage die fewer",
              "weapon": f"One weapon attack against {target.display_name}",
              "carry": "Move one willing creature next to you 10 feet along your Soulwake"}
    offered = ["pressure", *(["spike"] if _action_named(engine, actor, "Mind Spike") else []),
               *(["weapon"] if _weapon_actions(engine, actor, target) else []), "carry"]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "UNDERTOW_CHOICE", target.entity_id), actor, "choice:needle.black_current.undertow",
                        offered, labels={k: labels[k] for k in offered}, preferred=["pressure"], allow_decline=True,
                        prompt="Undertow Pursuit: after arriving, choose one.", name="Undertow Pursuit", feature_id=NO_BANK, target_id=target.entity_id)
    pick = chosen[0] if chosen else None
    if pick == "pressure":
        _te().run_effects(st.context(engine, actor, ctx.action, [target], ctx.numbers, intent), [{"type": "spiritual_pressure", "applies_to": "target"}])
    elif pick == "spike":
        _mind_spike_minus_one(ctx, target)
    elif pick == "weapon":
        weapons = _weapon_actions(engine, actor, target)
        if weapons:
            _run_action(engine, actor, weapons[0], target, intent)
    elif pick == "carry":
        _carry_along_wake(engine, actor, intent)


def _action_named(engine: Any, actor: Any, name: str) -> Any:
    return next((engine.action_catalog[a] for a in actor.action_ids if a in engine.action_catalog and engine.action_catalog[a].display_name == name), None)


def _weapon_actions(engine: Any, actor: Any, target: Any) -> list[Any]:
    out = []
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
        if action is None or typed.get("weapon") is None or typed.get("proficient") is False or action.economy.value != "ACTION" or "#" in action_id:
            continue
        reach = int(action.reach_ft or action.range_ft or 5)
        if engine.grid.distance_ft(actor.position, target.position) <= reach:
            out.append(action)
    return sorted(out, key=lambda a: -int((a.parameters or {}).get("expected_damage") or 0))


def _run_action(engine: Any, actor: Any, action: Any, target: Any, intent: Any, effects: list[Any] | None = None) -> None:
    typed = dict((action.parameters or {}).get("typed") or {})
    typed["numbers"] = dict(typed.get("numbers") or {})
    ctx = _te().Context(engine, actor, action, intent, typed, [target], target, {})
    _te().run_effects(ctx, effects if effects is not None else typed.get("effects") or [])


def _mind_spike_minus_one(ctx: Any, target: Any) -> None:
    import copy

    spike = _action_named(ctx.engine, ctx.actor, "Mind Spike")
    if spike is None:
        return
    effects = copy.deepcopy(((spike.parameters or {}).get("typed") or {}).get("effects") or [])
    for row in _rows_in(effects):
        if row.get("type") == "damage" and row.get("dice_by_cl"):
            row["dice_by_cl"] = [[low, high, max(0, count - 1), sides] for low, high, count, sides in row["dice_by_cl"]]
        elif row.get("type") == "damage" and isinstance(row.get("dice"), dict):
            row["dice"] = {**row["dice"], "count": max(0, int(row["dice"].get("count") or 1) - 1)}
    _run_action(ctx.engine, ctx.actor, spike, target, ctx.intent, effects)


def _rows_in(effects: Any):
    for row in effects or []:
        if isinstance(row, dict):
            yield row
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _rows_in(row.get(key))


def _carry_along_wake(engine: Any, actor: Any, intent: Any) -> None:
    near = [o for o in engine.state.actors.values() if o.active and o.team_id == actor.team_id and o is not actor
            and engine.grid.distance_ft(o.position, actor.position) <= 5]
    ally = st.pick_creature(engine, intent, actor, near, checkpoint="UNDERTOW_CARRY", choice_id="choice:needle.black_current.undertow_carry",
                            prompt="Undertow Pursuit: which willing creature next to you moves 10 feet along your Soulwake?",
                            name="Undertow Pursuit", feature_id=NO_BANK, allow_decline=True)
    if ally is None:
        return
    wake = set(soulwake(actor))
    options = {cell: v for cell, v in st.routes(engine, ally, 10).items() if cell == ally.position or (cell.x, cell.y) in wake}
    path = st.choose_route(engine, actor, options, intent, checkpoint="UNDERTOW_CARRY_TO", prompt=f"Where along your Soulwake does {ally.display_name} move?",
                         name="Undertow Pursuit", feature=NO_BANK, stay=False)
    if path is not None:
        from .rider_movement import step

        step(engine, ally, list(path), NO_BANK)


# ------------------------------------------------------------------------------------------ Procession of the Black River
def _domain(engine: Any, owner: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == PROCESSION), None)


def _domains_over(engine: Any, creature: Any) -> list[tuple[Any, Any]]:
    """(owner, zone) for every Black River Domain the creature stands in."""
    out = []
    for owner in engine.state.actors.values():
        if owner.active and st.row(engine, owner, "procession_of_the_black_river") is not None:
            zone = _domain(engine, owner)
            if zone is not None and engine._footprint_intersects(creature, zone.affected_cells):
                out.append((owner, zone))
    return out


def _allied_current(engine: Any, creature: Any) -> list[tuple[Any, Any]]:
    return [(owner, zone) for owner, zone in _domains_over(engine, creature) if owner.team_id == creature.team_id]


@hook("speed")
def allied_current_speed(engine: Any, actor: Any) -> int | None:
    return 10 if _allied_current(engine, actor) else None


@hook("difficult_exempt")
def allied_current_footing(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    return st.plain_difficult(engine) if _allied_current(engine, actor) else None


@hook("turn_start_choice")
def allied_current_step(engine: Any, actor: Any) -> None:
    if not actor.active or not _allied_current(engine, actor) or engine._effective_speed(actor) <= 0:
        return
    options = st.routes(engine, actor, 5)
    if len(options) <= 1:
        return
    path = st.choose_route(engine, actor, options, None, checkpoint="ALLIED_CURRENT", name="Procession of the Black River", feature=PROCESSION,
                         prompt=f"Allied Current: {actor.display_name} starts its turn in the Black River Domain and may move 5 feet without "
                                "provoking Opportunity Attacks.")
    if path is not None:
        from .rider_movement import step

        step(engine, actor, list(path), PROCESSION)


@hook("event")
def black_river_movement(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    payload = kwargs.get("payload") or {}
    if mover is None or not mover.active or payload.get("forced") or payload.get("dragged_by"):
        return
    path = payload.get("path") or []
    if len(path) < 2:
        return
    moved = (len(path) - 1) * engine.grid.square_size_ft
    for owner, zone in _domains_over(engine, mover):
        round_key = f"black_river_round_{owner.entity_id}"
        if owner.team_id == mover.team_id and moved >= 15 and mover.turn_flags.get(round_key + "_temp") != engine.state.round_number:
            mover.turn_flags[round_key + "_temp"] = engine.state.round_number
            amount = 2 * int((zone.trigger_profile.get("numbers") or {}).get("pb") or 2)
            engine._grant_temp_hp(mover, amount, PROCESSION, owner.entity_id)
            note(engine, PROCESSION, owner, f"Allied Current: {mover.display_name} gains {amount} Temporary Hit Points.", (mover,))
        elif owner.team_id != mover.team_id and engine.state.current_actor_id == mover.entity_id:
            start, end = path[0], path[-1]
            displaced = max(abs(int(end["x"]) - int(start["x"])), abs(int(end["y"]) - int(start["y"]))) * engine.grid.square_size_ft
            if displaced >= 10 or mover.turn_flags.get(round_key + "_bank") == engine.state.round_number:
                continue
            mover.turn_flags[round_key + "_bank"] = engine.state.round_number
            _hostile_bank(engine, owner, zone, mover)


def _hostile_bank(engine: Any, owner: Any, zone: Any, creature: Any) -> None:
    ctx = _ctx(engine, owner, PROCESSION, [creature])
    ctx.typed["numbers"] = dict(zone.trigger_profile.get("numbers") or ctx.numbers)
    _save(ctx, creature, "wis",
          on_fail=[{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["psychic", "cold"],
                    "evidence": "It takes 3d8 Psychic or Cold damage"},
                   {"type": "condition", "applies_to": "target", "condition": "reaction_denied", "expires_on": "START_OF_TARGET_NEXT_TURN",
                    "evidence": "cannot take Reactions"},
                   {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away",
                    "evidence": "is pulled or pushed 10 feet along the current"}],
          on_success=[{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_end_of_next_turn",
                       "evidence": "Its Speed is reduced by 10 feet until the end of its next turn"}])


@hook("candidate_allowed")
def procession_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    tributary = ((action.parameters or {}) if action is not None else {}).get("black_river_tributary")
    if not tributary:
        return None
    if _domain(engine, actor) is None or actor.turn_flags.get("black_river_tributary"):
        return False
    if tributary == "river_cut":
        zone = _domain(engine, actor)
        if any(c.condition_id == "condition:typed.black_river_free_cut" and c.source_actor_id == actor.entity_id
               and (c.data or {}).get("zone_id") == (zone.zone_id if zone else None) for c in actor.conditions.values()):
            return False
    return None


@hook("compile_actions")
def tributary_actions(info: dict[str, Any]) -> list[Any] | None:
    if PROCESSION not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = info["numbers"]
    base = {"numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": PROCESSION}
    rows = [
        ("move", "Move in the current", "ALLY_OR_SELF", 40, [{"type": "black_current_tributary", "mode": "move"}],
         "Move yourself or one willing creature in the Domain up to 20 feet without provoking Opportunity Attacks."),
        ("exchange", "Exchange two creatures", "ALLY_OR_SELF", 40, [{"type": "black_current_tributary", "mode": "exchange"}],
         "Exchange the positions of two willing creatures in the Domain."),
        ("sweep", "Sweep a marked foe", "HOSTILE_ENTITY", 40, [
            {"type": "if_marked", "mark": "Resonance", "applies_to": "target", "effects": [
                {"type": "save", "applies_to": "target", "ability": "wis",
                 "on_fail": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away", "evidence": "moving it 15 feet on a failure"}],
                 "on_success": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away", "evidence": "or 5 feet on a success"}]}]},
            {"type": "black_current_tributary", "mode": "spent"}],
         "One Resonance Marked hostile creature in the Domain makes a Wisdom save: moved 15 feet on a failure, 5 feet on a success."),
    ]
    out = []
    for key, label, target_kind, reach, effects, text in rows:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.black_river_tributary.{key}", display_name=f"Ten Thousand Tributaries: {label}",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind=target_kind, range_ft=reach,
            parameters={"typed": {**base, "effects": effects}, "expected_damage": 0, "black_river_tributary": key,
                        "description": f"Procession of the Black River, once on each of your turns (free): {text}"}))
    for damage in ("psychic", "slashing", "cold"):
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.black_river_tributary.river_cut_{damage}",
            display_name=f"Ten Thousand Tributaries: River-Cut Passage ({damage.title()}, free)", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
            parameters={"typed": {**base, "effects": [
                {"type": "black_current_tributary", "mode": "river_cut"},
                {"type": "black_current_river_cut", "applies_to": "self", "picks_destination": True, "distance_ft": "half_speed", "half_speed": True,
                 "effects": [{"type": "save", "applies_to": "target", "ability": "dex",
                              "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": [damage],
                                           "evidence": "its damage becomes 3d8"},
                                          {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                           "evidence": "becomes Resonance Marked until the end of your next turn"},
                                          {"type": "black_current_aside", "applies_to": "target"}],
                              "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": [damage]}]}]}]},
                "expected_damage": 13, "black_river_tributary": "river_cut",
                "description": "Procession of the Black River, once per activation (free): River-Cut Passage without spending Resonance, moving up "
                               f"to half your Speed; failed saves take 3d8 {damage.title()}."}))
    return out


@effect("black_current_tributary")
def tributary(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    actor.turn_flags["black_river_tributary"] = True  # "Ten Thousand Tributaries is one operation per turn"
    mode = row.get("mode")
    zone = _domain(engine, actor)
    if mode == "river_cut" and zone is not None:
        engine._apply_condition(actor, "condition:typed.black_river_free_cut", ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"zone_id": zone.zone_id, "label": "Black River Domain: the free River-Cut option is used"})
        return
    subject = ctx.target or actor
    if zone is None or not engine._footprint_intersects(subject, zone.affected_cells):
        return
    if mode == "move":
        if subject is not actor and subject.team_id != actor.team_id:
            return
        options = {cell: v for cell, v in st.routes(engine, subject, 20).items()}
        path = st.choose_route(engine, actor, options, ctx.intent, checkpoint="TRIBUTARY_MOVE", name="Ten Thousand Tributaries", feature=PROCESSION,
                             prompt=f"Ten Thousand Tributaries: move {subject.display_name} up to 20 feet without provoking.", stay=False)
        if path is not None:
            from .rider_movement import step

            step(engine, subject, list(path), PROCESSION)
    elif mode == "exchange":
        others = [o for o in engine.state.actors.values() if o.active and o is not subject and o.team_id == actor.team_id
                  and engine._footprint_intersects(o, zone.affected_cells)]
        other = st.pick_creature(engine, ctx.intent, actor, others, checkpoint="TRIBUTARY_EXCHANGE", choice_id="choice:needle.black_current.exchange2",
                                 prompt=f"Ten Thousand Tributaries: exchange {subject.display_name} with which willing creature?",
                                 name="Ten Thousand Tributaries", feature_id=PROCESSION, allow_decline=True)
        if other is None:
            return
        a, b = subject.position, other.position
        rest = engine._occupied_cells_except(subject.entity_id) - set(engine._actor_cells(other))
        if not (engine.grid.placement_legal(b, footprint=engine._footprint(subject), occupied_cells=rest)
                and engine.grid.placement_legal(a, footprint=engine._footprint(other), occupied_cells=rest)):
            return
        subject.position, other.position = b, a
        for creature, start, end in ((subject, a, b), (other, b, a)):
            engine._append_event("MOVEMENT_COMMITTED", PROCESSION, actor_id=creature.entity_id,
                                 payload={"destination": end.model_dump(mode="json"), "cost_ft": 0, "without_provoking": True, "exchange": True,
                                          "path": [start.model_dump(mode="json"), end.model_dump(mode="json")]})
        from .. import zones

        zones.sync_inside(engine, PROCESSION)


@hook("would_drop")
def no_corpse_behind(engine: Any, target: Any, pending: int, source_actor_id: str) -> int | None:
    if not target.active or any(c.condition_id == RESCUED for c in target.conditions.values()):
        return None
    for owner, zone in _allied_current(engine, target):
        if not st.can_react(owner) or any(c.condition_id == "condition:typed.black_river_rescue_used" and c.source_actor_id == owner.entity_id
                                          and (c.data or {}).get("zone_id") == zone.zone_id for c in owner.conditions.values()):
            continue
        spots = {cell: v for cell, v in st.routes(engine, target, 30).items() if cell != target.position
                 and (cell.x, cell.y) in {(c.x, c.y) for c in zone.affected_cells}}
        from . import needle

        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "NO_CORPSE", target.entity_id), owner,
                            "choice:needle.black_current.no_corpse", ["rescue"],
                            labels={"rescue": f"River Leaves No Corpse Behind: {target.display_name} is moved and left at 1 HP (your Reaction)"},
                            prompt=f"{target.display_name} would drop to 0 Hit Points in your Black River Domain. Use your Reaction to move it up "
                                   "to 30 feet within the Domain and leave it at 1 Hit Point instead? (Once per activation.)",
                            preferred=["rescue"], allow_decline=True, name="River Leaves No Corpse Behind", feature_id=PROCESSION,
                            target_id=target.entity_id)
        if not chosen:
            continue
        with activation(engine, owner, PROCESSION):
            owner.reaction_available = False
            engine._apply_condition(owner, "condition:typed.black_river_rescue_used", PROCESSION, owner.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"zone_id": zone.zone_id, "label": "River Leaves No Corpse Behind used this activation"})
            engine._apply_condition(target, RESCUED, PROCESSION, owner.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Rescued by the Black River: cannot benefit again until a full cultivation session"})
            if spots:
                far = max(spots, key=lambda c: (engine.grid.distance_ft(c, target.position), -c.y, -c.x))
                path = st.choose_route(engine, owner, spots, engine._active_intent, checkpoint="NO_CORPSE_TO", name="River Leaves No Corpse Behind",
                                     feature=PROCESSION, prompt=f"Where in the Domain does {target.display_name} go?", preferred=far, stay=False)
                if path is not None:
                    from .needle import step_to

                    step_to(engine, target, path[-1], PROCESSION)
            note(engine, PROCESSION, owner, f"River Leaves No Corpse Behind: {target.display_name} is swept away and left at 1 Hit Point.", (target,))
            return max(0, int(target.current_hp) - 1)
    return None


@hook("event")
def undertow_relocated(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Pursuit after an actual teleport or forced route, including short moves."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if not (payload.get("forced") or payload.get("teleport")):
        return
    target = engine.state.actors.get(kwargs.get("actor_id"))
    path = payload.get("path") or []
    if target is None or not target.active or len(path) < 2 or path[0] == path[-1]:
        return
    from ..gate2_runtime_models import Position
    from ..target_knowledge import located
    from . import needle
    start = Position.model_validate(path[0])
    for walker in engine.state.actors.values():
        if (walker is target or not walker.active or st.row(engine, walker, "no_bank_holds_the_river") is None or
                not st.can_react(walker) or walker.resources.get(RESONANCE, 0) < 4 or
                not _te().bears_mark(target, walker.entity_id, "Resonance") or
                engine.grid.distance_ft(walker.position, start) > 60 or not located(engine, walker, target)):
            continue
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "UNDERTOW_RELOCATED", target.entity_id), walker,
                            "choice:needle.black_current.undertow_relocated", ["pursue"],
                            labels={"pursue": "Undertow Pursuit: 4 Resonance and your Reaction; follow the marked creature"},
                            preferred=["pursue"] if walker.team_id != target.team_id else [], allow_decline=True,
                            default="first" if walker.team_id != target.team_id else "decline", name="Undertow Pursuit", feature_id=NO_BANK,
                            target_id=target.entity_id,
                            prompt=f"{target.display_name} {'teleported' if payload.get('teleport') else 'was forcibly moved'}. Follow it?")
        if not chosen:
            continue
        with activation(engine, walker, NO_BANK):
            engine._spend_resource(walker, RESONANCE, 4, NO_BANK)
            walker.reaction_available = False
            action = st.feature_action(engine, walker, NO_BANK)
            undertow(st.context(engine, walker, action, [target], intent=engine._active_intent), {})
            engine._append_event("REACTION_RESOLVED", NO_BANK, actor_id=walker.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "MOVEMENT_COMMITTED", "reaction_name": "Undertow Pursuit"})
