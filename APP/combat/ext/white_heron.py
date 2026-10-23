"""White Heron Crescent Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, White Heron Crescent Body (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "heron", "role": "integration" | "guard" | "white_wing" | "moon"}``; Crescent-Body Integration also
carries the integrated-weapon row (group "polearm") and a reach_bonus row (combat/ext/reach_bonus.py). One-Legged Guard's Reaction
runs ``one_legged_guard``; Crescent Reaping Circle is an Attack-action variant (combat/ext/attack_lines.py, ``reaping_circle``); Moon
over the Reed Sea's action runs ``moon_over_the_reed_sea``; its stance is the named state "moon_reed_stance".

Heron's Passing Cut  once per turn, a Polearm hit after 10+ feet of willing movement this turn (asked, 1 Stamina): move 10 feet
                    without provoking, push it 10 feet, pull it 5 feet (to a square still within reach), or + 1d8/2d8/3d8
                    Slashing or Force.
One-Legged Guard    the Reaction (1 Stamina, once per round) before a melee attack from a creature within your Polearm's reach at
                    you or at a creature next to you: one Polearm attack (a Granted Attack); on a hit, asked: - PB on that attack
                    roll, move the protected creature 5 feet (the attack then misses if it no longer reaches), push the attacker
                    5 feet (likewise), or no Reactions for the attacker until its next turn.
Crescent Reaping Circle  "Crescent Reaping Circle (<Polearm>)": the Attack action with one attack spent on the sweep (2 Stamina, once
                    per turn): the hostile creatures you choose within the Polearm's reach make a Dexterity save (one weapon die
                    + CON + 3d8; on a failure you choose, for each, a 5-foot push or no Reactions; half on a success), then an
                    asked 10-foot move without provoking, then the remaining attacks.
White Wing Crosses the Reed Field  once during each of your turns after a Polearm hit (asked): move up to half your Speed through
                    that creature's space (at least 5 feet through it), then choose: a Polearm attack against a different creature
                    in reach (Granted), push it 10 feet, knock it Prone on a failed Strength save, or + 2 AC until your next turn.
Moon over the Reed Sea  a route of up to twice your Speed to the aimed square, through hostile creatures, without provoking: each
                    hostile creature you choose that comes within the Polearm's reach makes a Dexterity save (10d8, a push of up
                    to 15 feet you choose, no Reactions until the end of its next turn; or half, 5 feet, until the start of its
                    next turn); then the guarded stance until your next turn: + 2 AC, + 5 feet reach, and the first hostile creature
                    to come within your reach takes one attack that spends no Reaction.
Every hook returns early for a creature without these rows, flags or state.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.white_heron_crescent_body.feature."
REAPING = PREFIX + "crescent_reaping_circle"
STANCE = "moon_reed_stance"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "heron"}


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _polearm(typed: dict[str, Any]) -> bool:
    from .integrated_weapons import in_group

    return in_group(typed or {}, "polearm") and not (typed or {}).get("range_ft")


def _moved(engine: Any, actor: Any) -> int:
    total = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("teleport"):
            total += max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
    return total


def _polearm_attacks(engine: Any, actor: Any, target: Any | None, *, opportunity: bool = False) -> dict[str, Any]:
    """The owner's Polearm attack actions (and their integrated variants) that reach ``target``, the longest reach first."""
    from .reach_bonus import MARK, applies, current_reach

    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: (-int(a.range_ft or 5), a.source_definition_id)):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or not _polearm(typed) or (action.parameters or {}).get("player_only") \
                or str(getattr(action.economy, "value", action.economy)) != "ACTION" or ("#" in action.source_definition_id and "#integrated" not in action.source_definition_id):
            continue
        if not any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            continue
        rule = (action.parameters or {}).get(MARK)
        if rule and not applies(engine, actor, rule, opportunity=opportunity):
            continue
        reach = current_reach(engine, actor, action, opportunity=opportunity)
        if target is None or engine._distance_actor_to_actor(actor, target) <= reach:
            out[action.source_definition_id] = action.model_copy(update={"range_ft": reach})
    return out


def _pick(engine: Any, intent: Any, actor: Any, target: Any, name: str, *, optional: bool = False, opportunity: bool = False) -> Any:
    from .needle import ask, checkpoint_id

    attacks = _polearm_attacks(engine, actor, target, opportunity=opportunity)
    if not optional and len(attacks) <= 1:
        return next(iter(attacks.values()), None)
    preferred = [k for k in attacks if k.endswith("#integrated_con")] or list(attacks)
    picked = ask(engine, intent, checkpoint_id(engine, "heron_attack", target.entity_id), actor, "choice:needle.heron_polearm_attack", list(attacks),
                 labels={k: a.display_name for k, a in attacks.items()}, preferred=preferred[:1], target_id=target.entity_id, name=name,
                 allow_decline=optional,
                 prompt=(f"{name}: {target.display_name} entered your reach. Take one Polearm Opportunity Attack without spending your Reaction?"
                         if optional else f"{name}: which Polearm attack against {target.display_name}?"))
    return attacks.get(picked[0]) if picked else None


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any) -> bool:
    """One Granted Attack with ``action``; True on a hit."""
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return False
    attack.update(count=1, granted_attack_root=True)
    start = len(engine.events)
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [target], target, {}), [attack])
    return any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor.entity_id and (e.payload or {}).get("provisional_hit") for e in engine.events[start:])


def _free_move(engine: Any, intent: Any, actor: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(engine, actor, feet)
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "heron_move", actor.entity_id), actor, choice_id, sorted(paths), allow_decline=True, default="decline",
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id, name=name,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        step(engine, actor, paths[picked[0]], PREFIX + "heron")


# ----------------------------------------------------------------------------------- Heron's Passing Cut and White Wing
@hook("after_hit")
def heron_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles or target is None or not target.active or target.team_id == actor.team_id or not _polearm(ctx.typed):
        return
    stamp = _stamp(engine)
    mine = engine.state.current_actor_id == actor.entity_id
    if "integration" in roles and actor.turn_flags.get("_round_passing_cut") != stamp and _moved(engine, actor) >= 10 \
            and int(actor.resources.get(STAMINA, 0) or 0) >= 1:
        _passing_cut(ctx, target)
    if "white_wing" in roles and mine and target.active and actor.turn_flags.get("_round_white_wing") != stamp:
        _white_wing(ctx, target)


def _passing_cut(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import forced_route

    engine, actor = ctx.engine, ctx.actor
    cl = int((ctx.numbers or {}).get("cl") or 1)
    count = 3 if cl >= 17 else 2 if cl >= 11 else 1
    labels = {"move": "Move 10 feet without provoking", "push": "Push it 10 feet", "pull": "Pull it 5 feet toward you (still within reach)",
              "damage": f"+ {count}d8 Slashing or Force"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "passing_cut", target.entity_id), actor, "choice:needle.herons_passing_cut", list(labels), labels=labels,
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Heron's Passing Cut",
                 prompt=f"Heron's Passing Cut: your Polearm hit {target.display_name} on the move. 1 Stamina: choose one.")
    if not picked or picked[0] not in labels:
        return
    actor.turn_flags["_round_passing_cut"] = _stamp(engine)
    engine._spend_resource(actor, STAMINA, 1, PREFIX + "crescent_body_integration")
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    choice = picked[0]
    if choice == "move":
        _free_move(engine, ctx.intent, actor, 10, "choice:needle.passing_cut_move", "Heron's Passing Cut")
    elif choice == "push":
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "pull":
        reach = int(ctx.action.range_ft or 5)
        found = engine.grid.reachable(target.position, movement_ft=5, occupied_cells=engine._occupied_cells_except(target.entity_id), difficult_cells=set(),
                                      footprint=engine._footprint(target))
        here = engine.grid.distance_ft(actor.position, target.position)
        paths = {cell_id(c): p for c, (p, cost) in found.items() if c != target.position and engine.grid.distance_ft(actor.position, c) < here
                 and engine.grid.distance_ft(actor.position, c) <= reach}
        if paths:
            pick = ask(engine, ctx.intent, checkpoint_id(engine, "passing_pull", target.entity_id), actor, "choice:needle.passing_cut_pull", sorted(paths),
                       labels={k: "Pull it to " + k.removeprefix("cell:") for k in paths}, target_id=target.entity_id,
                       prompt="Heron's Passing Cut: where do you pull it?")
            if pick and pick[0] in paths:
                forced_route(engine, target, paths[pick[0]], PREFIX + "crescent_body_integration", actor)
    else:
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Heron's Passing Cut"}])


def _white_wing(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import step
    from .frightened_movement import path_allowed

    engine, actor = ctx.engine, ctx.actor
    half = int(engine._effective_speed(actor)) // 2
    square = engine.grid.square_size_ft
    here = engine.grid.distance_ft(actor.position, target.position)
    into = 2 * square if here <= square else None  # entering its space is difficult terrain
    if into is None or into > half:
        return  # "If you cannot complete at least 5 feet of legal movement through the triggering creature's space ..."
    occupied = engine._occupied_cells_except(actor.entity_id) - set(engine._actor_cells(target))
    found = engine.grid.reachable(target.position, movement_ft=half - into, occupied_cells=occupied, difficult_cells=engine._hostile_difficult_cells(actor),
                                  footprint=engine._footprint(actor))
    blocked = engine._occupied_cells_except(actor.entity_id)
    paths = {cell_id(c): [actor.position, *p] for c, (p, cost) in found.items()
             if c != target.position and (c.x, c.y) not in blocked and path_allowed(engine, actor, [actor.position, *p])}
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing", target.entity_id), actor, "choice:needle.white_wing_move", sorted(paths),
                 labels={k: "Pass through to " + k.removeprefix("cell:") for k in paths}, allow_decline=True, default="decline", target_id=target.entity_id,
                 name="White Wing Crosses the Reed Field", prompt=f"White Wing Crosses the Reed Field: pass through {target.display_name}'s space?")
    if not picked or picked[0] not in paths:
        return
    actor.turn_flags["_round_white_wing"] = _stamp(engine)
    step(engine, actor, paths[picked[0]], PREFIX + "white_wing_crosses_the_reed_field")
    if not actor.active:
        return
    others = {c.entity_id: c for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and c.entity_id != target.entity_id
              and _polearm_attacks(engine, actor, c)}
    labels = {**({"attack": "One Polearm attack against a different creature in reach"} if others else {}), "push": f"Push {target.display_name} 10 feet",
              "prone": f"Knock {target.display_name} Prone if it fails a Strength save", "ac": "+ 2 AC until the start of your next turn"}
    choice = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing_result", target.entity_id), actor, "choice:needle.white_wing_result", list(labels),
                 labels=labels, target_id=target.entity_id, name="White Wing Crosses the Reed Field", prompt="White Wing Crosses the Reed Field: choose one.")
    choice = choice[0] if choice and choice[0] in labels else "ac"
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    if choice == "attack":
        pick = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing_other", actor.entity_id), actor, "choice:needle.white_wing_target", list(others),
                   labels={k: c.display_name for k, c in others.items()}, target_id=actor.entity_id, prompt="White Wing: attack whom?")
        other = others.get(pick[0] if pick else next(iter(others)))
        action = _pick(engine, ctx.intent, actor, other, "White Wing Crosses the Reed Field") if other is not None else None
        if action is not None:
            _granted(engine, actor, action, other, ctx.intent)
    elif choice == "push" and target.active:
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "prone" and target.active:
        te.run_effects(sub, [{"type": "save", "ability": "str", "evidence": "White Wing: Strength saving throw",
                              "on_fail": [{"type": "condition", "applies_to": "target", "condition": "prone"}], "on_success": []}])
    else:
        engine._add_modifier(actor, PREFIX + "white_wing_crosses_the_reed_field", "armor_class", "ADD", 2, "SELF", expires_on="START_OF_SOURCE_NEXT_TURN")


# ------------------------------------------------------------------------------------------------------ One-Legged Guard
def _pending(engine: Any) -> dict[str, Any]:
    return getattr(engine, "_typed_pending_attack", None) or {}


@hook("row_allowed")
def guard_needs_reach(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """One-Legged Guard: only against a creature within your Polearm's reach (off your turn: no turn-only reach)."""
    if not str(row.get("feature_id") or "").endswith("one_legged_guard"):
        return None
    attacker = engine.state.actors.get(str(_pending(engine).get("attacker") or ""))
    return None if attacker is not None and _polearm_attacks(engine, actor, attacker, opportunity=True) else False


@hook("ally_row_allowed")
def guard_needs_reach_ally(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    if not str(row.get("feature_id") or "").endswith("one_legged_guard"):
        return None
    attacker = engine.state.actors.get(str(_pending(engine).get("attacker") or ""))
    near = engine._distance_actor_to_actor(reactor, subject) <= engine.grid.square_size_ft
    return None if near and attacker is not None and _polearm_attacks(engine, reactor, attacker, opportunity=True) else False


@effect("one_legged_guard")
def one_legged_guard(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import step
    from .frightened_movement import path_allowed

    engine, me, attacker = ctx.engine, ctx.actor, ctx.target
    protected = engine.state.actors.get(str(_pending(engine).get("target") or (ctx.typed or {}).get("protects") or me.entity_id))
    if attacker is None or protected is None:
        return
    action = _pick(engine, ctx.intent, me, attacker, "One-Legged Guard", opportunity=True)
    if action is None or not _granted(engine, me, action, attacker, ctx.intent) or not attacker.active:
        return
    labels = {"minus": f"- {int(me.proficiency_bonus or 2)} on its attack roll", "move": f"Move {protected.display_name} 5 feet",
              "push": f"Push {attacker.display_name} 5 feet", "deny": f"{attacker.display_name} cannot take Reactions until its next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "one_legged_guard", attacker.entity_id), me, "choice:needle.one_legged_guard", list(labels),
                 labels=labels, target_id=attacker.entity_id, name="One-Legged Guard", prompt="One-Legged Guard: your Polearm hit. Choose one.")
    choice = picked[0] if picked and picked[0] in labels else "minus"
    if choice == "minus":
        protected.turn_flags["_one_legged_guard"] = {"attacker": attacker.entity_id, "minus": int(me.proficiency_bonus or 2)}
    elif choice == "move":
        found = engine.grid.reachable(protected.position, movement_ft=5, occupied_cells=engine._occupied_cells_except(protected.entity_id),
                                      difficult_cells=set(), footprint=engine._footprint(protected))
        # The protected creature chooses willing travel, so its fear (not the
        # guard's) must allow the route before the destination is offered.
        paths = {cell_id(c): p for c, (p, cost) in found.items()
                 if c != protected.position and path_allowed(engine, protected, p)}
        if paths:
            pick = ask(engine, ctx.intent, checkpoint_id(engine, "guard_move", protected.entity_id), protected if protected.team_id == me.team_id else me,
                       "choice:needle.one_legged_guard_move", sorted(paths), labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                       allow_decline=True, default="first", target_id=protected.entity_id, prompt="One-Legged Guard: step 5 feet out of the blow?")
            if pick and pick[0] in paths:
                step(engine, protected, paths[pick[0]], PREFIX + "one_legged_guard")  # the executor rechecks the attack's reach
    elif choice == "push":
        te.run_effects(te.Context(engine, me, action, ctx.intent, (action.parameters or {}).get("typed") or {}, [attacker], attacker, {}),
                       [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
        from ..typed_reactions import attack_reaches

        if not attack_reaches(engine, attacker, protected, {"attack_kind": "melee"}):
            protected.turn_flags["_one_legged_guard"] = {"attacker": attacker.entity_id, "miss": True}  # "If moved outside its reach ... misses"
    else:
        te.run_effects(te.Context(engine, me, action, ctx.intent, (action.parameters or {}).get("typed") or {}, [attacker], attacker, {}),
                       [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


@hook("hit_response")
def guard_turns_the_blow(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    record = target.turn_flags.get("_one_legged_guard")
    if not record or record.get("attacker") != attacker.entity_id:
        return None
    target.turn_flags.pop("_one_legged_guard", None)
    if record.get("miss"):
        from ..attack_outcomes import unconditional_miss

        return unconditional_miss()
    minus = int(record.get("minus") or 0)
    if natural != 20 and total - minus < effective_ac:
        return effective_ac + minus, False  # equivalent threshold for this one attack; retain terminal eligibility
    return None


@hook("attack_resolved")
def guard_record_ends(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if target is not None and (target.turn_flags.get("_one_legged_guard") or {}).get("attacker") == ctx.actor.entity_id:
        target.turn_flags.pop("_one_legged_guard", None)


# ------------------------------------------------------------------------------------------------ Crescent Reaping Circle
@hook("compile_actions")
def reaping_circle_actions(info: dict[str, Any]) -> list[Any] | None:
    if REAPING not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from .attack_lines import line_variants

    bases = [a for a in info["actions"] if a.economy == EconomyKind.ACTION and _polearm((a.parameters or {}).get("typed") or {})]
    return line_variants(info, REAPING, bases, replace=1, area=None, stamina=2, name="Crescent Reaping Circle", lead="reaping_circle") or None


@effect("reaping_circle")
def reaping_circle(ctx: Any, row: dict[str, Any]) -> None:
    """The sweep: chosen hostile creatures within the Polearm's reach (with this turn's reach increases) save; you choose each failed
    creature's push or Reaction denial; then the asked 10-foot move."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    from .reach_bonus import current_reach

    base_id = ctx.typed.get("attack_line_of")
    base = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and a.source_definition_id == base_id), None)
    reach = current_reach(engine, actor, base) if base is not None else int(row.get("reach_ft") or 5)
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= reach and engine._line_of_sight_actor_to_actor(actor, c)}
    if foes:
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "reaping_targets", actor.entity_id), actor, "choice:needle.reaping_circle_targets", list(foes),
                     labels={k: c.display_name for k, c in foes.items()}, minimum=1, maximum=len(foes), default_count=len(foes), allow_decline=True,
                     target_id=actor.entity_id, name="Crescent Reaping Circle", prompt="Crescent Reaping Circle: which hostile creatures in reach does the sweep take?") or []
        for key in [k for k in foes if k in chosen]:
            foe = foes[key]
            save = copy.deepcopy(row.get("save") or {})
            save["on_fail"] = [r for r in save.get("on_fail") or [] if isinstance(r, dict) and r.get("type") in ("damage", "extra_damage")] + [{"type": "reaping_rider"}]
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [foe], foe, {}), [save])
    if actor.active:
        _free_move(engine, ctx.intent, actor, 10, "choice:needle.reaping_circle_move", "Crescent Reaping Circle")


@effect("reaping_rider")
def reaping_rider(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    foe = ctx.target
    if foe is None or not foe.active:
        return
    labels = {"push": f"Push {foe.display_name} 5 feet", "deny": f"{foe.display_name} cannot take Reactions until its next turn"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "reaping_rider", foe.entity_id), ctx.actor, "choice:needle.reaping_circle_rider", list(labels),
                 labels=labels, target_id=foe.entity_id, name="Crescent Reaping Circle", prompt=f"Crescent Reaping Circle: {foe.display_name} failed its save. Choose one.")
    if (picked[0] if picked else "push") == "push":
        te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    else:
        te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


# ------------------------------------------------------------------------------------------------- Moon over the Reed Sea
def _moon_paths(engine: Any, actor: Any) -> dict[tuple[int, int], list[Any]]:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_moon_paths")
    from .frightened_movement import path_allowed

    key = ("moon", actor.entity_id, actor.position.x, actor.position.y, int(engine.state.event_sequence))
    cache = engine.__dict__.setdefault("_moon_paths", {})
    if key not in cache:
        cache.clear()
        hostile = {c for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id for c in engine._actor_cells(other)}
        occupied = engine._occupied_cells_except(actor.entity_id) - hostile  # through hostile spaces, as difficult terrain
        found = engine.grid.reachable(actor.position, movement_ft=2 * int(engine._effective_speed(actor)), occupied_cells=occupied,
                                      difficult_cells=hostile | set(engine._hostile_difficult_cells(actor)), footprint=engine._footprint(actor))
        cache[key] = {(c.x, c.y): p for c, (p, cost) in found.items() if (c.x, c.y) not in engine._occupied_cells_except(actor.entity_id)}
    # Cache geometry only; fear/visibility is queried for both menu and effect.
    return {cell: path for cell, path in cache[key].items() if path_allowed(engine, actor, path)}


@hook("compile_actions")
def moon_aim(info: dict[str, Any]) -> None:
    for action in info["actions"]:
        if ((action.parameters or {}).get("typed") or {}).get("source") == PREFIX + "moon_over_the_reed_sea" and action.target_kind == "CELL":
            action.parameters["any_cell"] = True  # this character's own action, being compiled
            action.parameters["moon_reed"] = True


@hook("candidate_allowed")
def moon_reachable(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("moon_reed") or getattr(candidate, "destination", None) is None:
        return None
    return None if (candidate.destination.x, candidate.destination.y) in _moon_paths(engine, actor) else False


@effect("moon_over_the_reed_sea")
def moon_over_the_reed_sea(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .effect_durations import token
    from .needle import ask, checkpoint_id
    from .rider_movement import step
    from .states import PREFIX as STATE, slug

    engine, actor = ctx.engine, ctx.actor
    aim = ctx.damage_cache.get("_checkpoint_aim") or ctx.destination
    path = _moon_paths(engine, actor).get((aim.x, aim.y)) if aim is not None else None
    if not path:
        return
    reach = max([int(a.range_ft or 5) for a in _polearm_attacks(engine, actor, None).values()] or [5])
    square = engine.grid.square_size_ft
    first: dict[str, int] = {}
    for index, cell in enumerate(path):
        for other in engine.state.actors.values():
            if other.active and other.team_id != actor.team_id and other.entity_id not in first \
                    and engine.grid.distance_between_cell_sets(engine._actor_cells(actor, cell), engine._actor_cells(other)) * square <= reach:
                first[other.entity_id] = index
    chosen: list[str] = []
    if first:
        order = sorted(first, key=lambda k: (first[k], k))
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "moon_reed", actor.entity_id), actor, "choice:needle.moon_over_the_reed_sea", order,
                     labels={k: engine.state.actors[k].display_name for k in order}, minimum=1, maximum=len(order), default_count=len(order),
                     allow_decline=True, target_id=actor.entity_id, name="Moon over the Reed Sea",
                     prompt="Moon over the Reed Sea: which hostile creatures along the way does the crescent take?") or []
    walked = actor.position
    for index, cell in enumerate(path[1:], start=1):
        if not actor.active or actor.position != walked:
            break
        step(engine, actor, [walked, cell], PREFIX + "moon_over_the_reed_sea")
        walked = cell
        for key in [k for k in chosen if first.get(k) == index] + ([k for k in chosen if first.get(k) == 0] if index == 1 else []):
            foe = engine.state.actors[key]
            if not foe.active:
                continue
            sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [foe], foe, {})
            te.run_effects(sub, [{"type": "save", "ability": "dex", "evidence": "Moon over the Reed Sea: Dexterity saving throw",
                                  "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 10, "sides": 8}, "damage_types": ["slashing", "force"]},
                                              {"type": "reaction_denied", "applies_to": "target", "expires_on": token("end", foe.entity_id, int(foe.turns_started) + 1)},
                                              {"type": "moon_push", "up_to": 15}],
                                  "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["slashing", "force"]},
                                                 {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"},
                                                 {"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}]}])
    if actor.active:  # the guarded stance until the start of your next turn
        engine._apply_condition(actor, STATE + slug(STANCE), PREFIX + "moon_over_the_reed_sea", actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Moon over the Reed Sea: guarded stance (+2 AC, +5 ft reach, one free attack)", "name": STANCE})
        engine._add_modifier(actor, PREFIX + "moon_over_the_reed_sea", "armor_class", "ADD", 2, "SELF", expires_on="START_OF_SOURCE_NEXT_TURN")
        actor.turn_flags["_round_moon_free_strike"] = True


@effect("moon_push")
def moon_push(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    foe = ctx.target
    if foe is None or not foe.active:
        return
    options = ["15", "10", "5", "0"]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "moon_push", foe.entity_id), ctx.actor, "choice:needle.moon_push_distance", options,
                 labels={o: f"Push {foe.display_name} {o} feet" if o != "0" else f"Leave {foe.display_name} in place" for o in options},
                 target_id=foe.entity_id, name="Moon over the Reed Sea", prompt=f"Moon over the Reed Sea: {foe.display_name} failed its save. Push it how far (up to 15 feet)?")
    feet = int(picked[0]) if picked and picked[0] in options else 15
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


@hook("event")
def moon_free_strike(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The stance's "first hostile creature entering your reach provokes one Opportunity Attack that does not consume your
    Reaction" (entering, not standing there as the reach grows)."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    path = (kwargs.get("payload") or {}).get("path") or []
    if mover is None or not mover.active or len(path) < 2:
        return
    from ..gate2_runtime_models import Position
    from .states import active

    for guard in engine.state.actors.values():
        if guard.team_id == mover.team_id or not guard.turn_flags.get("_round_moon_free_strike") or not active(engine, guard, STANCE):
            continue
        attacks = _polearm_attacks(engine, guard, mover, opportunity=True)
        if not attacks:
            continue
        reach = max(int(a.range_ft or 5) for a in attacks.values())
        start = Position.model_validate(path[0])
        if engine.grid.distance_between_cell_sets(engine._actor_cells(guard), engine._actor_cells(mover, start)) * engine.grid.square_size_ft <= reach:
            continue  # it was already within reach
        action = _pick(engine, _intent(engine), guard, mover, "Moon over the Reed Sea", optional=True, opportunity=True)
        guard.turn_flags.pop("_round_moon_free_strike", None)
        if action is not None:
            _granted(engine, guard, action, mover, _intent(engine))
        return
