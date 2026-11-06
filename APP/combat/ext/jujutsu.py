"""Jujutsu Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Jujutsu (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "jujutsu", "role": "redirect_force" | "gentle_fist"}``; Throw's action runs ``jujutsu_throw``;
Empty Body is the named state "empty_body". Harmonious Body is played by combat/ext/redirect_reactions.py (lane H2).

Redirect Force  after a typed melee attack by a creature within your reach misses you: your Reaction (none while Empty Body
                lasts), once per round, one choice (asked): push the attacker 5 feet into an unoccupied space, move yourself 5
                feet without provoking, move around the attacker to another unoccupied space next to it (at most 20 feet of
                walking: the ring around a Medium creature), or Advantage on your next Grapple or Shove against it before the end
                of your next turn (its save against that attempt has Disadvantage, as the table runs Grapple and Shove).
Gentle Fist     when your unarmed hit's damage is about to land on a Factory fighter: 1 Stamina, once per turn (asked) -- the
                attack deals no damage; then its Constitution save: two different effects on a failure, one on a success
                (asked): Speed halved, Disadvantage on its next attack roll, no Reactions, or Disadvantage on its next Strength
                or Dexterity save (asked which) -- each until the start of your next turn.
Throw           (Bonus Action, 2 Stamina, a creature you Grapple) its Strength or Dexterity save: failure, thrown up to 15 feet
                to an unoccupied space you choose, 3d8 Bludgeoning, Prone, your Grapple on it ends; success, moved 5 feet and
                you may end the Grapple (asked).
Empty Body      state "empty_body" (1 minute): Advantage on Dexterity saves (typed) and on escaping Grappled or Restrained,
                Opportunity Attacks against you have Disadvantage, after a melee miss you may move 5 feet without provoking,
                Redirect Force without your Reaction, and once per round a melee miss may be sent at another creature in the
                attacker's reach with the same roll (asked; a redirected attack is never redirected again).
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note, run_checkpoint

PREFIX = "tianxia.subpath.body.jujutsu.feature."
EMPTY = "empty_body"
HOLD_EDGE = "condition:typed.redirect_force_advantage"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "jujutsu"}


def _empty(engine: Any, actor: Any) -> bool:
    from .states import active

    return actor is not None and bool(active(engine, actor, EMPTY))


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _melee(ctx: Any) -> bool:
    return not ctx.typed.get("range_ft") and "ranged" not in str(next((e.get("attack_kind") for e in ctx.typed.get("effects") or []
                                                                         if isinstance(e, dict) and e.get("type") == "attack"), "") or "")


def _can_react(engine: Any, actor: Any) -> bool:
    from ..typed_reactions import can_react

    return can_react(engine, actor)


def _cells(engine: Any, mover: Any, feet: int, *, forced: bool) -> dict[str, list[Any]]:
    from .needle import cell_id

    if forced:
        found = engine.grid.reachable(mover.position, movement_ft=feet, occupied_cells=engine._occupied_cells_except(mover.entity_id),
                                      difficult_cells=set(), footprint=engine._footprint(mover))
        return {cell_id(cell): path for cell, (path, cost) in found.items() if cell != mover.position}
    from .rider_movement import routes

    return routes(engine, mover, feet)


def _pick_cell(engine: Any, intent: Any, chooser: Any, mover: Any, paths: dict[str, Any], choice_id: str, prompt: str, *, decline: bool = True) -> list[Any] | None:
    from .needle import ask, checkpoint_id

    if not paths:
        return None
    picked = ask(engine, intent, checkpoint_id(engine, "jujutsu_cell", mover.entity_id), chooser, choice_id, sorted(paths),
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, allow_decline=decline, default="decline" if decline else "first",
                 target_id=mover.entity_id, prompt=prompt)
    return paths.get(picked[0]) if picked else None


# ------------------------------------------------------------------------------------------- misses against you
@hook("after_miss")
def melee_miss(ctx: Any, target: Any) -> None:
    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or not _melee(ctx):
        return
    roles, empty = _roles(engine, target), _empty(engine, target)
    if not roles and not empty:
        return
    if empty:
        _empty_step(ctx, target)
        _empty_redirect(ctx, target)
    if "redirect_force" in roles and attacker.active:
        _redirect_force(ctx, target, attacker)


def _redirect_force(ctx: Any, owner: Any, attacker: Any) -> None:
    from ..typed_reactions import attack_reaches
    from .needle import ask, checkpoint_id
    from .rider_movement import forced_route, step

    engine = ctx.engine
    empty = _empty(engine, owner)
    if owner.turn_flags.get("_round_redirect_force") == int(engine.state.round_number) or not (empty or _can_react(engine, owner)):
        return
    if not attack_reaches(engine, owner, attacker, {"attack_kind": "unarmed"}):
        return
    labels = {"advantage": f"Advantage on your next Grapple or Shove against {attacker.display_name}",
              "push": f"Move {attacker.display_name} 5 feet", "step": "Move yourself 5 feet without provoking",
              "around": f"Move around {attacker.display_name} to another space next to it"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "redirect_force", attacker.entity_id), owner, "choice:needle.redirect_force", list(labels),
                 labels=labels, allow_decline=True, target_id=attacker.entity_id, name="Redirect Force",
                 prompt=f"Redirect Force: {attacker.display_name} missed you{'' if empty else ' (your Reaction)'}.")
    if not picked or picked[0] not in labels:
        return
    with activation(engine, owner, PREFIX + "redirect_force"):
        owner.turn_flags["_round_redirect_force"] = int(engine.state.round_number)
        if not empty:
            from .. import typed_reactions

            typed_reactions._open(engine, {"feature_id": PREFIX + "redirect_force"}, owner, (attacker.entity_id,), "ATTACK_MISSED")
            owner.reaction_available = False
        choice = picked[0]
        if choice == "advantage":
            from .effect_durations import token

            engine._apply_condition(attacker, HOLD_EDGE, PREFIX + "redirect_force", owner.entity_id, expires_on=token("end", owner.entity_id, int(owner.turns_started) + 1),
                                    data={"label": f"Redirect Force: {owner.display_name}'s next Grapple or Shove against it has Advantage"})
        elif choice == "push":
            paths = {k: p for k, p in _cells(engine, attacker, 5, forced=True).items()}
            path = _pick_cell(engine, ctx.intent, owner, attacker, paths, "choice:needle.redirect_force_push", f"Redirect Force: where does {attacker.display_name} go?", decline=False)
            if path:
                first_event = len(engine.events)
                forced_route(engine, attacker, path, PREFIX + "redirect_force", owner)
                # A legal selected route can still be fully prevented by a defense.
                # Notify successful redirection only after this push commits a step;
                # another reaction's relocation is not evidence of this push.
                if any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == attacker.entity_id
                       and event.source_definition_id == PREFIX + "redirect_force" and event.payload.get("forced")
                       for event in engine.events[first_event:]):
                    run_checkpoint("jujutsu_redirect_or_throw", engine, owner, attacker, PREFIX + "redirect_force", ctx)
        else:
            paths = _cells(engine, owner, 5 if choice == "step" else 20, forced=False)
            if choice == "around":
                paths = {k: p for k, p in paths.items() if engine.grid.distance_ft(p[-1], attacker.position) <= 5 and len(p) > 1}
            path = _pick_cell(engine, ctx.intent, owner, owner, paths, "choice:needle.redirect_force_move", "Redirect Force: where do you move?", decline=False)
            if path:
                step(engine, owner, path, PREFIX + "redirect_force")


def _grapple_or_shove(ctx: Any) -> bool:
    for row in ctx.typed.get("effects") or []:
        if isinstance(row, dict) and row.get("type") == "save" and row.get("max_size_larger") is not None:
            return True
    return False


@hook("save")
def redirect_force_edge(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """The Advantage on your Grapple or Shove: the target's save against it has Disadvantage (used up by that attempt)."""
    if subject is None or ctx.actor is subject or not _grapple_or_shove(ctx):
        return None
    held = next((c for c in subject.conditions.values() if c.condition_id == HOLD_EDGE and c.source_actor_id == ctx.actor.entity_id), None)
    if held is None:
        return None
    subject.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "redirect_force", actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": HOLD_EDGE, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


def _empty_step(ctx: Any, owner: Any) -> None:
    paths = _cells(ctx.engine, owner, 5, forced=False)
    path = _pick_cell(ctx.engine, ctx.intent, owner, owner, paths, "choice:needle.empty_body_step",
                      f"Empty Body: {ctx.actor.display_name} missed; you may move 5 feet without provoking.")
    if path:
        from .rider_movement import step

        step(ctx.engine, owner, path, PREFIX + EMPTY)


def _empty_redirect(ctx: Any, owner: Any) -> None:
    """Once per round, the missed melee attack goes at another creature in the attacker's reach with the same roll."""
    from ..typed_executor import Context, run_effects
    from .needle import ask, checkpoint_id

    engine, attacker = ctx.engine, ctx.actor
    if owner.turn_flags.get("_round_empty_redirect") == int(engine.state.round_number) or getattr(engine, "_jujutsu_redirecting", False):
        return
    roll = getattr(ctx, "attack_result", None) or next((e.payload for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED"
                                                        and e.actor_id == attacker.entity_id), None) or {}
    total, natural = int(roll.get("modified_total") or roll.get("total") or 0), int(roll.get("natural_result") or 0)
    reach = int(ctx.action.range_ft or 5)
    others = [row for row in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if row.active and row.entity_id not in (owner.entity_id, attacker.entity_id)
              and engine._distance_actor_to_actor(attacker, row) <= reach]
    if not others:
        return
    ac = {row.entity_id: row.armor_class + engine._ac_modifier(row) for row in others}
    others.sort(key=lambda row: (row.team_id != attacker.team_id, not (natural != 1 and total >= ac[row.entity_id]), ac[row.entity_id], row.entity_id))
    labels = {row.entity_id: f"{row.display_name} (AC {ac[row.entity_id]}, the roll was {total})" for row in others}
    best = others[0]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "empty_redirect", owner.entity_id), owner, "choice:needle.empty_body_redirect", list(labels),
                 labels=labels, preferred=[best.entity_id], allow_decline=True, default="decline", target_id=attacker.entity_id, name="Empty Body",
                 automatic=best.team_id == attacker.team_id and natural != 1 and total >= ac[best.entity_id],
                 prompt=f"Empty Body: send {attacker.display_name}'s missed attack at another creature in its reach?")
    chosen = next((row for row in others if picked and row.entity_id == picked[0]), None)
    if chosen is None:
        return
    owner.turn_flags["_round_empty_redirect"] = int(engine.state.round_number)
    hit = natural != 1 and (natural == 20 or total >= ac[chosen.entity_id])
    note(engine, PREFIX + EMPTY, owner, f"Empty Body: {attacker.display_name}'s attack ({total}) goes at {chosen.display_name} and {'hits' if hit else 'misses'}.",
         (attacker, chosen))
    attack = next((row for row in ctx.typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    if not hit or attack is None:
        return
    on_hit = [row for row in attack.get("on_hit") or [] if isinstance(row, dict)]
    if not any(row.get("type") == "damage" for row in on_hit) and not attack.get("no_damage"):
        on_hit = [{"type": "damage", "weapon_damage": True}, *on_hit]
    engine._jujutsu_redirecting = True  # a redirected attack is not redirected again
    try:
        run_effects(Context(engine, attacker, ctx.action, ctx.intent, ctx.typed, [chosen], chosen, {}), on_hit)
    finally:
        engine._jujutsu_redirecting = False


@hook("escape_mode")
def empty_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _empty(engine, escaper) else None


@hook("escape_save_mode")
def empty_escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _empty(engine, escaper) else None


@hook("attack_mode")
def empty_opportunity(ctx: Any, target: Any) -> str | None:
    if target is None or not _empty(ctx.engine, target):
        return None
    return "DISADVANTAGE" if ctx.typed.get("opportunity_of") or getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id else None


# ---------------------------------------------------------------------------------------------------- Gentle Fist
@hook("damage_pending")
def gentle_fist_pending(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    actor = engine.state.actors.get(str(source_actor_id or ""))
    if actor is None or packet.get("actor") != actor.entity_id or packet.get("target") != target.entity_id:
        return None
    held = engine.__dict__.get("_gentle_fist")
    if held == (actor.entity_id, target.entity_id, source_definition_id):
        return 0  # the triggering attack deals no damage at all
    if packet.get("kind") != "unarmed" or packet.get("source") != source_definition_id or "gentle_fist" not in _roles(engine, actor):
        return None
    if actor.turn_flags.get("_round_gentle_fist") == _stamp(engine) or int(actor.resources.get(STAMINA, 0) or 0) < 1 or target.team_id == actor.team_id:
        return None
    from .needle import ask, checkpoint_id

    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "gentle_fist", target.entity_id),
                 actor, "choice:needle.gentle_fist", ["gentle"], labels={"gentle": "1 Stamina: deal no damage; its Constitution save for Gentle Fist effects"},
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Gentle Fist",
                 prompt=f"Gentle Fist: your unarmed strike hit {target.display_name}.")
    if not picked:
        return None
    actor.turn_flags["_round_gentle_fist"] = _stamp(engine)
    engine._spend_resource(actor, STAMINA, 1, PREFIX + "gentle_fist")
    engine.__dict__["_gentle_fist"] = (actor.entity_id, target.entity_id, source_definition_id)
    return 0


@hook("after_hit")
def gentle_fist_effects(ctx: Any, target: Any, kind: str) -> None:
    engine = ctx.engine
    if engine.__dict__.get("_gentle_fist") != (ctx.actor.entity_id, getattr(target, "entity_id", None), ctx.source):
        return
    engine.__dict__["_gentle_fist"] = None
    if target is None or not target.active:
        return
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "save", "ability": "con", "evidence": "Gentle Fist: Constitution saving throw",
                     "on_fail": [{"type": "gentle_fist_effects", "count": 2}], "on_success": [{"type": "gentle_fist_effects", "count": 1}]}])


@hook("attack_resolved")
def gentle_fist_done(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    held = ctx.engine.__dict__.get("_gentle_fist")
    if held and held[0] == ctx.actor.entity_id:
        ctx.engine.__dict__["_gentle_fist"] = None


@effect("gentle_fist_effects")
def gentle_fist_choice(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    count = int(row.get("count") or 1)
    labels = {"speed": "Its Speed is halved", "attack": "Disadvantage on its next attack roll", "reactions": "It cannot take Reactions",
              "save": "Disadvantage on its next Strength or Dexterity saving throw"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "gentle_fist_effects", target.entity_id), ctx.actor, "choice:needle.gentle_fist_effects",
                 list(labels), labels=labels, minimum=count, maximum=count, target_id=target.entity_id, name="Gentle Fist",
                 prompt=f"Gentle Fist: choose {'two different effects' if count == 2 else 'one effect'} on {target.display_name} until the start of your next turn.")
    until = "START_OF_SOURCE_NEXT_TURN"
    for choice in [k for k in labels if k in (picked or list(labels)[:count])][:count]:
        if choice == "speed":
            te.run_effects(ctx, [{"type": "speed", "applies_to": "target", "halved": True, "expires_on": until}])
        elif choice == "attack":
            te.run_effects(ctx, [{"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "expires_on": until}])
        elif choice == "reactions":
            te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": until}])
        else:
            which = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "gentle_fist_save", target.entity_id), ctx.actor, "choice:needle.gentle_fist_save",
                        ["Strength", "Dexterity"], target_id=target.entity_id, prompt=f"Gentle Fist: {target.display_name}'s next Strength or Dexterity save?")
            te.run_effects(ctx, [{"type": "disadvantage", "applies_to": "target", "on": f"its next {(which or ['Strength'])[0]} saving throw", "expires_on": until}])


# ---------------------------------------------------------------------------------------------------------- Throw
def _grip(target: Any, owner: Any) -> Any:
    return next((c for c in target.conditions.values() if c.condition_id.endswith(".grappled") and c.source_actor_id == owner.entity_id), None)


@hook("candidate_allowed")
def throw_needs_your_grapple(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    if not any(isinstance(e, dict) and e.get("type") == "jujutsu_throw" for e in typed.get("effects") or []):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    return None if targets and all(t is not None and _grip(t, actor) is not None for t in targets) else False


def _release(engine: Any, owner: Any, target: Any) -> None:
    held = _grip(target, owner)
    if held is not None:
        target.conditions.pop(held.instance_id, None)
        engine._append_event("CONDITION_REMOVED", PREFIX + "throw", actor_id=owner.entity_id, target_ids=(target.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": held.instance_id, "reason": "THROWN"})


@effect("jujutsu_throw")
def jujutsu_throw(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active or _grip(target, ctx.actor) is None:
        return
    te.run_effects(ctx, [{"type": "save", "ability": "STR_OR_DEX", "evidence": "Throw: Strength or Dexterity saving throw (the target's choice)",
                          "on_fail": [{"type": "jujutsu_throw_move", "feet": 15, "thrown": True}],
                          "on_success": [{"type": "jujutsu_throw_move", "feet": 5, "thrown": False}]}])


@effect("jujutsu_throw_move")
def jujutsu_throw_move(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .rider_movement import forced_route

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    feet, thrown = int(row.get("feet") or 5), bool(row.get("thrown"))
    if thrown:
        _release(engine, owner, target)  # it leaves your hands as it flies
    paths = _cells(engine, target, feet, forced=True)
    path = _pick_cell(engine, ctx.intent, owner, target, paths, "choice:needle.throw_destination",
                      f"Throw: where does {target.display_name} land (up to {feet} feet)?", decline=False)
    if path:
        forced_route(engine, target, path, PREFIX + "throw", owner)
    if thrown:
        te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["bludgeoning"]},
                             {"type": "condition", "applies_to": "target", "condition": "prone"}])
        # General seam: the Throw succeeded (the target failed its save). Default-inert --
        # a plug-in observes the resolution (combat/ext/__init__.py documents the contract).
        run_checkpoint("jujutsu_redirect_or_throw", engine, owner, target, PREFIX + "throw", ctx)
        return
    if _grip(target, owner) is None:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "throw_release", target.entity_id), owner, "choice:needle.throw_release", ["release"],
                 labels={"release": f"End your Grapple on {target.display_name}"}, allow_decline=True, default="decline", target_id=target.entity_id,
                 prompt="Throw: the save succeeded. End the Grapple?")
    if picked:
        _release(engine, owner, target)
