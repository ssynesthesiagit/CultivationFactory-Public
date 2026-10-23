"""The Flowing River sphere (owner 2026-09-28: "we need to automate every aspect before another playtest"; Tabik Damu,
Gu Xiangze and Shi Xunyun). Flowing Response had been compiled as one reaction carrying both of its modes and two talents'
effects at once.

Flowing Response (Reaction, once a round):
  Yield Against an Attack   a melee attack roll against it by a creature it can see: +PB AC against that attack only
                            (effect flowing_yield_attack, run by the generic "attacked" reaction); if the attack misses,
                            the response succeeds
  Yield Against Control     a creature within its reach makes it save (Strength or Dexterity) against being moved,
                            knocked Prone, Grappled or Restrained: Advantage on that save (the "save" hook); if it
                            succeeds, the response succeeds
  On a success: the chosen Response talent ("Flowing Response: <talent>", a free choice kept until changed; the AI takes
  the first it can use of Hand on the Wrist, River Takes the Spear, Bend the Blade, Empty Step), then, when the fighter
  chose "Flowing Response: step away", a 5-foot step (10 with Empty Step) away from the creature, provoking no
  Opportunity Attacks.
  Response talents: Hand on the Wrist (no Reactions until the start of its next turn), River Takes the Spear (against a
  weapon attack: a Strength save; no Opportunity Attacks with that weapon until the start of its next turn, and on a
  failure its next attack with it has Disadvantage), Bend the Blade (expend Martial Focus: the same attack roll against
  another creature within the attacker's reach; a hit has the attack's ordinary hit effects), Empty Step (the step is
  10 feet). Two Currents Meet (body 2026-09-29): expend Martial Focus to apply two different, known Response talents
  to the same success instead of one -- every pair is its own "Flowing Response: X + Y (Martial Focus)" toggle
  alongside the single-talent ones; not legal unless both are legal for the same triggering creature.
Empty Bank Evasion   on a Dexterity save against an effect it can see that deals damage, expend Martial Focus: no
                     damage on a success, half on a failure (the "evasion" hook)
Reed in Storm        a melee miss against it while it benefits from the Dodge action regains Martial Focus
Court of Returning Water  the Domain (a 30-foot area moving with it): Flowing Response twice a round, not twice in one
                     turn; Martial Focus regained once a round when a hostile creature misses it with a melee attack;
                     allies inside have Advantage on saves against Prone and forced movement; once per turn, a hostile
                     creature inside that misses with a melee attack makes a Dexterity save: Prone on a failure, Speed
                     -10 feet until the start of its next turn on a success. Moving creatures 10 feet within the
                     Domain and the 5-foot steps on a miss are the GM's.
Borrowed Momentum    a GM line when a Flowing River talent moves a creature (the table's Flowing River moves are GM's).
Patient Water        "When you take the Dodge Action and no hostile creature makes an attack roll against you before the start of
                     your next turn, regain Martial Focus at the start of that turn. You regain Martial Focus only if it is
                     currently absent." (rider lane C10, 2026-09-30; it was an immediate regain on Dodging): taking the Dodge action
                     puts a Patient Water mark on you; a hostile creature's attack roll against you takes it off; at the start of
                     your next turn a mark still there is spent and Martial Focus comes back if it is absent.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from typing import Any

from . import effect, hook

FOCUS = "resource:core.martial_focus"
RESPONSE = "TAL_FLOWING_RIVER_FLOWING_RESPONSE"
CHOICE = "condition:typed.flowing_response_choice"
STEP = "condition:typed.flowing_response_step"
NO_OA = "condition:typed.river_takes_the_spear"
SPEAR_DISADVANTAGE = "condition:typed.river_takes_the_spear_next"
COURT = "condition:typed.court_of_returning_water"
TALENTS = {"TAL_FLOWING_RIVER_HAND_ON_THE_WRIST": "Hand on the Wrist", "TAL_FLOWING_RIVER_RIVER_TAKES_THE_SPEAR": "River Takes the Spear",
           "TAL_FLOWING_RIVER_BEND_THE_BLADE": "Bend the Blade", "TAL_FLOWING_RIVER_EMPTY_STEP": "Empty Step"}
TWO_CURRENTS_MEET = "TAL_FLOWING_RIVER_TWO_CURRENTS_MEET"
DOUBLE_CURRENT = "insight.double-current-method"
DOUBLE_USED = "condition:typed.double_current_method_used"
PATIENT = "condition:typed.patient_water"
PATIENT_SOURCE = "passive:TAL_FLOWING_RIVER_PATIENT_WATER"
# Response talents typed as "when: success" modifiers on Flowing Response: they arrive as on_success wrappers on its row
# (success_deferred below) and run from _succeed like the ones above -- the chosen one, after a miss or a successful save.
RIDING = {"TAL_FLOWING_RIVER_RETURN_THE_GRIP": "Return the Grip", "TAL_FLOWING_RIVER_TURN_THE_FOOT": "Turn the Foot",
          "TAL_FLOWING_RIVER_DRAW_PAST": "Draw Past", "TAL_FLOWING_RIVER_SOFT_CAPTURE": "Soft Capture",
          "TAL_FLOWING_RIVER_CIRCULAR_THROW": "Circular Throw", "TAL_FLOWING_RIVER_WATER_WEARS_STONE": "Water Wears Stone",
          "TAL_FLOWING_RIVER_RETURN_THE_MOUNTAIN_TO_THE_MOUNTAIN": "Return the Mountain to the Mountain"}
NAMES = {**TALENTS, **RIDING}
_CONTROL_SCOPES: ContextVar[tuple[Any, ...]] = ContextVar("flowing_control_scopes", default=())


@hook("decision_text")
def double_current_description(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Explain offered pairs with shared owner text, without interpreting talent mechanics."""
    if context.get("reaction_source_id") != "choice:needle.double_current_method":
        return None
    actor = engine.state.actors.get(context.get("reactor_id"))
    if actor is None or not _rows_kind(engine, actor, "double_current_method"):
        return None
    trigger = context.get("choice_trigger") or {}
    by_name = {NAMES[talent]: talent for talent in _known(engine, actor)}
    descriptions = {}
    for key, label in (trigger.get("labels") or {}).items():
        names = label.split(" + ")
        if len(names) != 2 or any(name not in by_name for name in names):
            continue
        parts = []
        for name in names:
            # Keep the shared effects, saves, targets, duration and costs intact;
            # acquisition prerequisites do not help choose an already-known pair.
            body = " ".join(line.strip() for line in printed_rules.get(by_name[name], "").splitlines()
                            if line.strip() and not line.startswith(("#", "Prerequisite:")))
            parts.append(f"{name}: {body}")
        payment = ("Bend the Blade still costs its own 1 Martial Focus (one available use)."
                   if "Bend the Blade" in names else "No separate resource cost.")
        descriptions[key] = (" ".join(parts) + " No additional Action or Reaction; "
                             "no Martial Focus spent for pairing. " + payment)
    return {"option_descriptions": descriptions}


@hook("success_deferred")
def response_succeeds_later(feature_id: str) -> bool | None:
    return True if feature_id == RESPONSE else None


def _riding(engine: Any, actor: Any) -> dict[str, list[dict[str, Any]]]:
    """Its Response talents that ride Flowing Response's success: talent id -> effects."""
    row = _response_row(engine, actor) or {}
    return {str(e.get("talent")): list(e.get("effects") or []) for e in row.get("effects") or []
            if isinstance(e, dict) and e.get("type") == "on_success"}


def _rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if row.get("block") == block]


def _known(engine: Any, actor: Any) -> list[str]:
    """Its Response talents, in the AI's order of preference."""
    owned = {row.get("feature_id") for row in _rows(engine, actor, "flowing_river")}
    riding = _riding(engine, actor)
    known = [talent for talent in TALENTS if talent in owned] + [talent for talent in RIDING if talent in riding]
    mountain = "TAL_FLOWING_RIVER_RETURN_THE_MOUNTAIN_TO_THE_MOUNTAIN"
    if mountain in known:
        known.remove(mountain)
        known.insert(known.index("TAL_FLOWING_RIVER_BEND_THE_BLADE") if "TAL_FLOWING_RIVER_BEND_THE_BLADE" in known else 0, mountain)
    return known


def _drop(engine: Any, creature: Any, condition_id: str, source: str, *, where: Any = None) -> None:
    for iid, condition in list(creature.conditions.items()):
        if condition.condition_id == condition_id and (where is None or where(condition)):
            creature.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(creature.entity_id,),
                                 payload={"condition_id": condition_id, "instance_id": iid})


def _response_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    from .. import typed_reactions

    return next((row for row in typed_reactions._rows(engine, actor.entity_id, "generic") if row.get("feature_id") == RESPONSE), None)


def _court(actor: Any) -> bool:
    return any(c.condition_id == COURT for c in actor.conditions.values())


# ------------------------------------------------------------------------------------------------ Yield Against an Attack
@effect("flowing_yield_attack")
def yield_attack(ctx: Any, eff: dict[str, Any]) -> None:
    engine, reactor, attacker = ctx.engine, ctx.actor, ctx.target
    if attacker is None:
        return
    pb = int(ctx.numbers.get("pb") or 2)
    engine._add_modifier(reactor, f"flowing_response:{attacker.entity_id}", "armor_class", "ADD", pb, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
    preserve_pending(engine, "_flowing_pending")
    engine.__dict__.setdefault("_flowing_pending", {})[(attacker.entity_id, reactor.entity_id)] = (
        {"second_pass": True} if eff.get("second_pass") else True)
    retain(engine, ("_flowing_pending", attacker.entity_id, reactor.entity_id), capture(engine))
    _mark_court_turn(engine, reactor)


def _mark_court_turn(engine: Any, reactor: Any) -> None:
    """Court of Returning Water: twice a round but not twice in one turn; the second use needs the Reaction back."""
    if _court(reactor):
        reactor.turn_flags[f"flowing_response_turn_round_{engine.state.round_number}"] = engine.state.current_actor_id


@hook("attack_resolved")
def after_attack(ctx: Any, target: Any, hit: bool, attack: dict[str, Any]) -> None:
    engine, attacker = ctx.engine, ctx.actor
    melee = not (ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5)
    preserve_pending(engine, "_flowing_pending")
    pending = engine.__dict__.get("_flowing_pending") or {}
    if pending.pop((attacker.entity_id, target.entity_id), None):
        with causal_scope(engine, take(engine, ("_flowing_pending", attacker.entity_id, target.entity_id))):
            for mid, modifier in list(target.modifiers.items()):
                if modifier.source_definition_id == f"flowing_response:{attacker.entity_id}" and modifier.target_field == "armor_class":
                    del target.modifiers[mid]  # "against the triggering melee attack" only
                    engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                                         payload={"modifier_id": mid, "reason": "ATTACK_RESOLVED"})
            if not hit and target.active and attacker.active:
                _succeed(engine, target, attacker, ctx=ctx, attack=attack)
    if hit or not melee or not target.active or attacker.team_id == target.team_id:
        return
    # Reed in Storm: a melee miss while it benefits from the Dodge action.
    if _rows_kind(engine, target, "reed_in_storm") and not any(
            row.get("block") == "river_second_pass" and row.get("kind") == "reed_in_storm"
            for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])) and any(c.condition_id == "condition:core.dodge" for c in target.conditions.values()):
        _regain_focus(engine, target, "passive:TAL_FLOWING_RIVER_REED_IN_STORM")
    # Court of Returning Water: Martial Focus once a round on a melee miss against it; the enemy's Dexterity save.
    if _court(target):
        key = f"court_focus_round_{engine.state.round_number}"
        if not target.turn_flags.get(key) and target.resources.get(FOCUS, 0) < 1:
            target.turn_flags[key] = True
            _regain_focus(engine, target, "passive:TAL_FLOWING_RIVER_COURT_OF_RETURNING_WATER")
    _court_punish(engine, attacker, missed=target)


def _rows_kind(engine: Any, actor: Any, kind: str) -> bool:
    return any(row.get("kind") == kind for row in _rows(engine, actor, "flowing_river"))


@hook("stand_cost")
def low_river_standing(engine: Any, actor: Any, ordinary: int) -> int | None:
    """Low River Stance uses the shared standing transition for five feet."""
    return 5 if _rows_kind(engine, actor, "low_river_stance") else None


def _regain_focus(engine: Any, actor: Any, source: str) -> None:
    if FOCUS in actor.resources and actor.resources.get(FOCUS, 0) < 1:
        engine._gain_resource(actor, FOCUS, 1, source)


# River Breaks the Charge is a GM rider. Its "mostly direct" approach needs
# adjudication; do not infer it from a MOVEMENT_COMMITTED endpoint or attach its
# four alternative outcomes to an ordinary Flowing Response attack/control save.


def _choice(engine: Any, actor: Any) -> list[str]:
    """The Response talent(s) chosen for the next Flowing Response (a free toggle kept until changed): one, or -- if
    Two Currents Meet is owned and the fighter picked a pair -- two, filtered to what is still actually known."""
    known = _known(engine, actor)
    for c in actor.conditions.values():
        if c.condition_id != CHOICE:
            continue
        data = c.data or {}
        pair = [str(talent) for talent in data.get("talents") or [] if str(talent) in known]
        if len(pair) == 2:
            return pair
        if str(data.get("talent")) in known:
            return [str(data["talent"])]
    return []


def _usable(engine: Any, reactor: Any, other: Any, ctx: Any, talent: str) -> bool:
    """Whether this Response talent has a legal target/trigger for this specific success ("Both talents must be legal
    for the same triggering creature", Two Currents Meet) -- Bend the Blade needs another creature in reach (and
    Martial Focus of its own, on top of Two Currents Meet's), River Takes the Spear needs a weapon attack."""
    if talent == "TAL_FLOWING_RIVER_BEND_THE_BLADE":
        return bool(_bend_targets(engine, reactor, other, ctx))
    if talent == "TAL_FLOWING_RIVER_RETURN_THE_MOUNTAIN_TO_THE_MOUNTAIN":
        return bool(_bend_targets(engine, reactor, other, ctx, return_mountain=True))
    if talent == "TAL_FLOWING_RIVER_RIVER_TAKES_THE_SPEAR":
        return ctx is not None and bool(ctx.typed.get("weapon"))
    return True


def _double_current(engine: Any, reactor: Any, other: Any, ctx: Any, attack: Any,
                    control: Any, trigger: str | None) -> list[str]:
    """Choose a legal pair at the existing success receipt, once per fight/scene.

    Ownership comes from the source-hashed compiled Flowing River row; native
    attack/save contexts supply trigger facts. No extra Action or Reaction is
    granted. Each talent retains its own payment and effect executor.
    """
    if not _rows_kind(engine, reactor, "double_current_method") or any(
            c.condition_id == DOUBLE_USED for c in reactor.conditions.values()):
        return []
    from itertools import combinations
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context
    from .hand_occupancy import free_hands, occupancy
    from . import query
    from ..typed_reactions import opportunity_reach

    def legal(talent: str) -> bool:
        if not _usable(engine, reactor, other, ctx, talent):
            return False
        if talent == "TAL_FLOWING_RIVER_BEND_THE_BLADE":
            return ctx is not None and attack is not None
        if talent == "TAL_FLOWING_RIVER_RETURN_THE_GRIP":
            typed = getattr(control, "typed", {}) or {}
            return typed.get("unarmed_option") in ("grapple", "shove_prone", "shove_push")
        if talent in ("TAL_FLOWING_RIVER_SOFT_CAPTURE", "TAL_FLOWING_RIVER_CIRCULAR_THROW"):
            if engine._distance_actor_to_actor(reactor, other) > int(opportunity_reach(engine, reactor) or 5):
                return False
        if talent == "TAL_FLOWING_RIVER_SOFT_CAPTURE":
            occupied = occupancy(engine, reactor)
            return bool(free_hands(engine, reactor, occupied=occupied) or any(
                part.get("id", "").startswith("body:") and part["id"] not in occupied
                for result in query("grappling_body_parts", engine, reactor)
                if isinstance(result, (list, tuple)) for part in result if isinstance(part, dict)))
        return True

    pairs = list(combinations([t for t in _known(engine, reactor) if legal(t)], 2))
    if not pairs:
        return []
    options = {str(i): pair for i, pair in enumerate(pairs)}
    source_ctx = ctx if ctx is not None else control
    action = source_ctx.action if source_ctx is not None else None
    moment = trigger or f"{other.display_name}'s {action.display_name if action else 'attack'} missed {reactor.display_name}."
    selected = ask(engine, getattr(engine, "_active_intent", None),
        checkpoint_id(engine, DOUBLE_CURRENT, reactor.entity_id, other.entity_id), reactor,
        "choice:needle.double_current_method", list(options), allow_decline=True,
        labels={key: f"{NAMES[pair[0]]} + {NAMES[pair[1]]}" for key, pair in options.items()},
        name="Double Current Method", feature_id=DOUBLE_CURRENT, target_id=other.entity_id,
        prompt=f"Double Current Method: {moment} Flowing Response succeeded. Choose two different known Response talents "
               f"against {other.display_name}, once per scene, without spending Martial Focus for the pair. "
               "Bend the Blade still costs its own 1 Martial Focus; each talent keeps its other requirements. "
               "Declining saves this use.",
        prompt_context=action_context(engine, other, action.source_definition_id, reactor, action=action) if action else None)
    if not selected:
        return []
    engine._apply_condition(reactor, DOUBLE_USED, DOUBLE_CURRENT, reactor.entity_id,
        expires_on="UNTIL_REMOVED", data={"label": "Double Current Method: used this scene"})
    return list(options[selected[0]])


def _succeed(engine: Any, reactor: Any, other: Any, *, ctx: Any = None, attack: dict[str, Any] | None = None, trigger: str | None = None, control: Any = None) -> None:
    """The response succeeded: one Response talent -- two, if Two Currents Meet is owned, chosen, both are legal for
    this creature, and Martial Focus can be spent for the combo -- then the step."""
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{RESPONSE}", actor_id=reactor.entity_id, target_ids=(other.entity_id,),
                         payload={"trigger": "Flowing Response succeeds"})
    known = _known(engine, reactor)
    free_pair = _double_current(engine, reactor, other, ctx, attack, control, trigger)
    chosen = free_pair or [talent for talent in _choice(engine, reactor) if _usable(engine, reactor, other, ctx, talent)]
    if free_pair:
        pass
    elif len(chosen) == 2 and reactor.resources.get(FOCUS, 0) >= 1:
        engine._spend_resource(reactor, FOCUS, 1, f"passive:{TWO_CURRENTS_MEET}")
    else:
        chosen = chosen[:1]
    if not chosen:
        chosen = [talent for talent in known if _usable(engine, reactor, other, ctx, talent)][:1]
    step = 10 if "TAL_FLOWING_RIVER_EMPTY_STEP" in chosen else 5
    context = _reactor_context(engine, reactor, other)
    from .. import typed_executor

    # The new sealed attack response follows the printed order: choose movement,
    # then apply the Response talent at the resulting positions. Older bundles
    # retain their historical automatic step and effect ordering.
    new_step = any(e.get("type") == "flowing_yield_attack" and e.get("second_pass")
                   for e in (_response_row(engine, reactor) or {}).get("effects") or [])
    if new_step and any(c.condition_id == STEP for c in reactor.conditions.values()) and reactor.active:
        from .flowing_second_pass import missed_attack, step as choose_step
        if trigger is None and ctx is not None:
            trigger = missed_attack(ctx, reactor)
        choose_step(context, reactor, other, step, "Flowing Response", trigger=trigger)

    for talent in chosen:
        from dataclasses import replace

        context = replace(context, typed={**context.typed, "_rider_response_talent": talent})
        if talent == "TAL_FLOWING_RIVER_HAND_ON_THE_WRIST":
            typed_executor.run_effects(context, [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SELF_NEXT_TURN",
                                                  "evidence": "the triggering creature cannot take Reactions until the start of its next turn"}])
        elif talent == "TAL_FLOWING_RIVER_RIVER_TAKES_THE_SPEAR" and ctx is not None and ctx.typed.get("weapon"):
            typed_executor.run_effects(context, [{"type": "save", "ability": "str", "applies_to": "target",
                                                  "on_fail": [{"type": "river_takes_the_spear", "weapon": ctx.source, "disadvantage": True}],
                                                  "on_success": [{"type": "river_takes_the_spear", "weapon": ctx.source, "disadvantage": False}]}])
        elif talent in ("TAL_FLOWING_RIVER_BEND_THE_BLADE", "TAL_FLOWING_RIVER_RETURN_THE_MOUNTAIN_TO_THE_MOUNTAIN") and ctx is not None and attack is not None:
            _bend(engine, reactor, other, ctx, attack, response_context=context, talent=talent)
        elif talent == "TAL_FLOWING_RIVER_EMPTY_STEP":
            context.rider("Empty Step: Flowing Response's step is 10 feet.")
        elif talent in RIDING:
            typed_executor.run_effects(context, _riding(engine, reactor).get(talent) or [])
    if len(chosen) == 2:
        name = "Double Current Method" if free_pair else "Two Currents Meet"
        cost = "no Martial Focus spent for the pair" if free_pair else "Martial Focus expended"
        context.rider(f"{name}: applied {NAMES[chosen[0]]} and {NAMES[chosen[1]]} "
                      f"to the same successful response ({cost}).")
    if not new_step and any(c.condition_id == STEP for c in reactor.conditions.values()) and reactor.active:
        typed_executor.run_effects(context, [{"type": "reaction_move", "distance_ft": step, "direction": "away",
                                              "evidence": f"you may move {step} feet without provoking Opportunity Attacks from the triggering creature"}])


def _reactor_context(engine: Any, reactor: Any, other: Any) -> Any:
    from .. import typed_reactions

    row = _response_row(engine, reactor) or {"feature_id": RESPONSE, "name": "Flowing Response", "effects": [], "numbers": {}}
    return typed_reactions._generic_context(engine, reactor, other, {**row, "effects": []}, getattr(engine, "_active_intent", None))


@effect("river_takes_the_spear")
def river_takes_the_spear(ctx: Any, eff: dict[str, Any]) -> None:
    creature = ctx.target
    if creature is None:
        return
    ctx.engine._apply_condition(creature, NO_OA, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"weapon": eff.get("weapon"), "label": "No Opportunity Attacks with that weapon (River Takes the Spear)"})
    if eff.get("disadvantage"):
        ctx.engine._apply_condition(creature, SPEAR_DISADVANTAGE, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                    data={"weapon": eff.get("weapon"), "label": "Its next attack with that weapon has Disadvantage (River Takes the Spear)"})


@hook("attack_mode")
def spear_disadvantage(ctx: Any, target: Any) -> str | None:
    for condition in ctx.actor.conditions.values():
        if condition.condition_id == SPEAR_DISADVANTAGE and (condition.data or {}).get("weapon") == ctx.source:
            _drop(ctx.engine, ctx.actor, SPEAR_DISADVANTAGE, ctx.source, where=lambda c: (c.data or {}).get("weapon") == ctx.source)
            return "DISADVANTAGE"
    return None


@hook("opportunity_allowed")
def spear_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if any(c.condition_id == NO_OA for c in reactor.conditions.values()) else None


def _bend_targets(engine: Any, reactor: Any, attacker: Any, ctx: Any, *, return_mountain: bool = False) -> list[Any]:
    """Targets for the two River redirects; allegiance is only an AI preference."""
    if ctx is None or reactor.resources.get(FOCUS, 0) < 1:
        return []
    from ..typed_reactions import opportunity_reach
    from ..target_knowledge import located
    from ..targeting import line_of_effect

    if return_mountain:
        # A clear path is not itself proof that a committed melee attack can
        # reach a creature. Keep Return's 30-foot limit, then apply the reach
        # recorded on the actual action that produced this attack.
        attack_reach = int(ctx.typed.get("reach_ft") or ctx.action.reach_ft or 5)
        targets = [row for row in engine.state.actors.values() if row.active and row.entity_id != reactor.entity_id
                   and located(engine, reactor, row) and engine._distance_actor_to_actor(reactor, row) <= 30
                   and engine._distance_actor_to_actor(attacker, row) <= attack_reach
                   and _redirect_path_clear(engine, attacker, row)]
    else:
        reach = int(opportunity_reach(engine, attacker) or 5)
        original_range = int(ctx.typed.get("range_ft") or ctx.action.range_ft or ctx.action.reach_ft or 5)
        targets = [row for row in engine.state.actors.values() if row.active and row.entity_id != reactor.entity_id
                   and located(engine, reactor, row) and line_of_effect(engine, attacker, target=row)
                   and engine._distance_actor_to_actor(attacker, row) <= min(reach, original_range)]
    return sorted(targets, key=lambda row: (row.team_id == reactor.team_id,
                  row.entity_id == attacker.entity_id, engine._distance_actor_to_actor(attacker, row), row.entity_id))


def _redirect_path_clear(engine: Any, attacker: Any, target: Any) -> bool:
    """Return the redirected attack's ordinary physical line of effect.

    Return the Mountain cannot use a sight-exempt route to pass through Total
    Cover or a sealed Barrier. Surface-contact routes remain valid when their
    shared geometry validator confirms both sight and physical clearance.
    """
    from ..shot_geometry import route
    from ..targeting import line_of_effect

    path = route(engine, attacker, target)
    if path and path.get("ignore_sight"):
        from ..effect_cover import rays
        from ..shot_geometry import contact_path

        points = contact_path(path)
        return all(next(rays(engine, (start,), (end,), purpose="effect"), None) is not None
                   for start, end in zip(points, points[1:]))
    return line_of_effect(engine, attacker, target=target)


def _bend(engine: Any, reactor: Any, attacker: Any, ctx: Any, attack: dict[str, Any], *,
          response_context: Any = None, talent: str = "TAL_FLOWING_RIVER_BEND_THE_BLADE") -> None:
    return_mountain = talent == "TAL_FLOWING_RIVER_RETURN_THE_MOUNTAIN_TO_THE_MOUNTAIN"
    name = NAMES[talent]
    targets = _bend_targets(engine, reactor, attacker, ctx, return_mountain=return_mountain)
    if not targets:
        return
    roll = next((event for event in reversed(engine.events[-40:]) if event.event_type == "ATTACK_ROLLED" and event.actor_id == attacker.entity_id
                 and reactor.entity_id in (event.target_ids or ())), None)
    if roll is None:
        return
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context
    selected = ask(engine, ctx.intent,
        checkpoint_id(engine, "river_bend_target", attacker.entity_id, reactor.entity_id), reactor,
        "choice:needle.river_bend_target", [row.entity_id for row in targets],
        labels={row.entity_id: f"{row.display_name} ({'the attacker' if row is attacker else 'your ally' if row.team_id == reactor.team_id else 'another creature'})"
                for row in targets},
        prompt=(f"{name}: {attacker.display_name}'s {ctx.action.display_name} missed {reactor.display_name}. "
                + ("Spend 1 Martial Focus to redirect the same attack roll to a creature within 30 feet of you "
                   "along a physically clear path. If it misses, that creature takes Bludgeoning damage equal to your "
                   "Proficiency Bonus. The attack cannot pass through Total Cover or a sealed Barrier. "
                   if return_mountain else "Spend 1 Martial Focus to redirect the same attack roll against one creature other than you "
                   "within the attacker's reach and the attack's original range. No extra Action or Reaction is spent.")),
        name=name, feature_id=talent,
        target_id=attacker.entity_id,
        prompt_context=action_context(engine, attacker, ctx.source, reactor, action=ctx.action))
    if not selected:
        return
    chosen = next(row for row in targets if row.entity_id == selected[0])
    engine._spend_resource(reactor, FOCUS, 1, f"passive:{talent}")
    total = int((roll.payload or {}).get("modified_total") or 0)
    natural = int((roll.payload or {}).get("natural_result") or 0)
    ac = chosen.armor_class + engine._ac_modifier(chosen)
    hit = natural != 1 and (natural == 20 or total >= ac)
    engine._append_event("PASSIVE_TRIGGERED", f"passive:{talent}", actor_id=reactor.entity_id,
                         target_ids=(attacker.entity_id, chosen.entity_id), payload={"trigger": name, "total": total, "ac": ac, "hit": hit})
    if not hit:
        if return_mountain and response_context is not None:
            from .. import typed_executor

            miss_context = response_context.on_hit_context(chosen).with_source(f"passive:{talent}")
            typed_executor.run_effects(miss_context, [{"type": "damage", "applies_to": "target", "flat": 0,
                                                       "formula": "pb", "damage_types": ["bludgeoning"],
                                                       "evidence": "the redirected target takes Bludgeoning damage equal to your Proficiency Bonus"}])
        return
    from .. import typed_executor

    on_hit = [row for row in attack.get("on_hit") or [] if isinstance(row, dict)]
    if not any(row.get("type") == "damage" for row in on_hit) and not attack.get("no_damage"):
        on_hit = [{"type": "damage", "weapon_damage": True}, *on_hit]
    typed_executor.run_effects(typed_executor.Context(engine, attacker, ctx.action, ctx.intent, ctx.typed, [chosen], chosen, {}), on_hit)


# ------------------------------------------------------------------------------------------------ Yield Against Control
_CONTROL = {"forced_movement", "prone", "grappled", "restrained"}


@hook("save")
def yield_control(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    engine, source = ctx.engine, ctx.actor
    modes: list[str] = []
    # Court of Returning Water: allies of its creator inside it have Advantage against Prone and forced movement.
    if source.team_id != subject.team_id and {"prone", "forced_movement"} & {str(row).lower() for row in named or ()}:
        from .. import zones

        for zone in zones.typed_zones(engine):
            owner = engine.state.actors.get(zone.owner_id)
            if zone.trigger_profile.get("court_of_returning_water") and owner is not None and owner.team_id == subject.team_id \
                    and owner.entity_id != subject.entity_id and zones._inside(engine, subject, zone):
                modes.append("ADVANTAGE")
                break
    choice = str(ability or "").upper()[:3]
    if choice in ("STR", "DEX") and source.team_id != subject.team_id and _CONTROL & {str(row).lower() for row in named or ()}:
        row = _response_row(engine, subject)
        from .. import typed_reactions

        reach = int(typed_reactions.opportunity_reach(engine, subject) or 5)
        if row is not None and engine._distance_actor_to_actor(subject, source) <= reach and _available(engine, subject, row) \
                and typed_reactions._consent(engine, row, subject, "SAVE_PENDING"):
            with activation(engine, subject, row["feature_id"]):
                typed_reactions._open(engine, row, subject, (source.entity_id,), "SAVE_PENDING")
                typed_reactions._spend_generic(engine, subject, row)
                typed_reactions.spend_reaction(engine, subject, row)
                _mark_court_turn(engine, subject)
                preserve_pending(engine, "_flowing_control")
                engine.__dict__.setdefault("_flowing_control", {})[subject.entity_id] = source.entity_id
                retain(engine, ("_flowing_control", subject.entity_id), capture(engine))
                modes.append("ADVANTAGE")
    return {"bonus": 0, "modes": modes} if modes else None


def _available(engine: Any, actor: Any, row: dict[str, Any]) -> bool:
    from .. import typed_reactions

    if typed_reactions._can_trigger(engine, actor, row):
        return True
    # Court of Returning Water: a second use in the round, not in the same turn (its Reaction must be back).
    if _court(actor) and actor.reaction_available:
        used_turn = actor.turn_flags.get(f"flowing_response_turn_round_{engine.state.round_number}")
        return used_turn is not None and used_turn != engine.state.current_actor_id
    return False


@hook("effect_resolution_scope")
def control_effect_scope(ctx: Any, effect: dict[str, Any]) -> Any:
    """Keep Flowing Response after the actual triggering effect, including
    opposed-save effects. The executor's documented effect_resolution_scope
    supplies the boundary; after_save_resolved supplies final success below.
    Context-local callbacks vanish on canceled previews and never enter saves.
    Engines without a compiled Flowing Response row are inert.
    """
    if not any(row.get("feature_id") == RESPONSE
               for rows in (getattr(ctx.engine, "typed_reaction_rows", {}) or {}).values() for row in rows):
        return None

    @contextmanager
    def scope():
        pending = []
        token = _CONTROL_SCOPES.set((*_CONTROL_SCOPES.get(), (ctx.engine, pending)))
        try:
            yield
        finally:
            _CONTROL_SCOPES.reset(token)
        for deliver in pending:
            deliver()

    return scope()


@hook("after_save_resolved")
def control_resolved(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    preserve_pending(ctx.engine, "_flowing_control")
    pending = ctx.engine.__dict__.get("_flowing_control") or {}
    source_id = pending.pop(subject.entity_id, None)
    cause = take(ctx.engine, ("_flowing_control", subject.entity_id))
    if source_id is None or failed:
        return

    def deliver():
        with causal_scope(ctx.engine, cause):
            other = ctx.engine.state.actors.get(source_id)
            if subject.active and other is not None and other.active:
                _succeed(ctx.engine, subject, other, control=ctx,
                    trigger=f"{subject.display_name} made a successful saving throw against {other.display_name}'s {ctx.action.display_name}.")

    frame = next((frame for frame in reversed(_CONTROL_SCOPES.get()) if frame[0] is ctx.engine), None)
    if frame is None:
        deliver()  # A direct final-save call has no enclosing effect to finish.
    else:
        frame[1].append(deliver)


# ------------------------------------------------------------------------------------------------ Empty Bank Evasion
@hook("history_event_metadata")
def empty_bank_manual_remainder(event: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The evasion hook applies the damage change; only its optional movement is
    manual. Adapt the exact producer text without changing old fight events.
    """
    if event.get("event_type") != "GM_RIDER":
        return None
    text = str((event.get("payload") or {}).get("rider") or "")
    if not text.startswith("Empty Bank Evasion: "):
        return None
    movement = "; it may move 10 feet without provoking Opportunity Attacks from the creature (GM)."
    if text.endswith(movement):
        outcome = text[:-len(movement)]
        if outcome.endswith(" takes no damage"):
            who = outcome[len("Empty Bank Evasion: "):-len(" takes no damage")]
            return {"rider_display_text": f"Empty Bank Evasion: {who} may move 10 feet without provoking "
                    "Opportunity Attacks from the creature that forced the saving throw."}
    if text.endswith(" takes half damage"):
        return {"history_hidden": True}
    return None


@hook("evasion")
def empty_bank(ctx: Any, subject: Any, ability: str, failed: bool, fail_effects: list[dict[str, Any]]) -> bool | None:
    if any(row.get("block") == "river_second_pass" and row.get("kind") == "empty_bank"
           for row in (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(subject.entity_id, [])):
        return None  # the new sealed declaration owns consent and post-effect movement
    if str(ability or "").upper()[:3] != "DEX" or not _rows_kind(ctx.engine, subject, "empty_bank_evasion"):
        return None
    if not any(isinstance(row, dict) and row.get("type") == "damage" for row in fail_effects) or subject.resources.get(FOCUS, 0) < 1:
        return None
    from .. import stealth

    if not stealth.sees(ctx.engine, subject, ctx.actor):
        return None  # "an effect you can see"
    with activation(ctx.engine, subject, "passive:TAL_FLOWING_RIVER_EMPTY_BANK_EVASION"):
        ctx.engine._spend_resource(subject, FOCUS, 1, "passive:TAL_FLOWING_RIVER_EMPTY_BANK_EVASION")
        ctx.rider(f"Empty Bank Evasion: {subject.display_name} takes {'half' if failed else 'no'} damage"
                  + ("" if failed else "; it may move 10 feet without provoking Opportunity Attacks from the creature (GM).") )
        return True


# ------------------------------------------------------------------------------------------------ Court of Returning Water
@effect("court_of_returning_water")
def court(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    engine._apply_condition(actor, COURT, ctx.source, actor.entity_id, expires_on=f"END_OF_SOURCE_TURN_AT:{actor.turns_started + 10}",
                            data={"label": "Court of Returning Water: Flowing Response twice a round"})
    from .. import zones

    zone = zones.create(ctx, {"name": "Court of Returning Water", "shape": "sphere", "size_ft": 30, "centered_on_self": True,
                              "duration": {"kind": "minutes", "amount": 1, "concentration": False}, "terrain": [], "difficult": None,
                              "obscured": None, "color": "#5dade2", "follows_owner": True, "move_through": None,
                              "visual": {"material": "domain", "obscured": None, "light": None, "darkness": False}, "triggers": []})
    if zone is not None:
        zone.trigger_profile = {**zone.trigger_profile, "court_of_returning_water": True}
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=actor.entity_id, payload={"zone": zone.model_dump(mode="json")})


def _court_punish(engine: Any, enemy: Any, *, missed: Any) -> None:
    """Once per turn, a hostile creature inside the Domain that misses with a melee attack makes a Dexterity save."""
    from .. import zones

    for zone in zones.typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if not zone.trigger_profile.get("court_of_returning_water") or owner is None or not owner.active or owner.team_id == enemy.team_id \
                or not zones._inside(engine, enemy, zone):
            continue
        from ..typed_executor import condition_rules

        if any(rule.get("no_actions") for rule in condition_rules(owner)):
            continue  # "The Domain ends early if you become Incapacitated"
        key = f"court_punish_{zone.zone_id}"
        turn = engine.state.round_number * 1000 + engine.state.current_slot_index
        if owner.turn_flags.get(key + "_round_") == turn:
            continue
        owner.turn_flags[key + "_round_"] = turn
        context = _reactor_context(engine, owner, enemy)
        context.typed["numbers"] = dict(zone.trigger_profile.get("numbers") or {})
        from .. import typed_executor

        typed_executor.run_effects(context, [{"type": "save", "ability": "dex", "applies_to": "target",
                                              "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target",
                                                           "evidence": "Failed Save: Move it 10 feet to one legal space inside the Domain, or give it the Prone condition."}],
                                              "on_success": [{"type": "speed", "flat": -10, "applies_to": "target", "expires_on": "START_OF_SELF_NEXT_TURN",
                                                              "evidence": "Successful Save: Its Speed is reduced by 10 feet until the start of its next turn."}]}])
        return


# ------------------------------------------------------------------------------------------------ choices and rows
@hook("compile_block")
def flowing_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "flowing_river":
        return None
    return [{**row, "block": "flowing_river", "kind": spec.get("kind")}]


@hook("compile_actions")
def flowing_choices(info: dict[str, Any]) -> list[Any] | None:
    if RESPONSE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    known = [talent for talent in NAMES if talent in info["owned_ids"]]
    out = []
    make = lambda key, label, eff: ActionDefinition(  # noqa: E731
        source_definition_id=f"action:typed.{info['short']}.flowing_response.{key}", display_name=label, owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [eff], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True, "setting_only": True})
    for talent in known:
        out.append(make(talent.rsplit("_", 3)[-1].lower() + str(len(out)), f"Flowing Response: {NAMES[talent]}",
                        {"type": "flowing_choice", "talent": talent}))
    # Two Currents Meet ("expend Martial Focus to apply two different Response talents you know to the same
    # successful response"): every pair of known Response talents, as its own choosable toggle.
    if TWO_CURRENTS_MEET in info["owned_ids"] and len(known) >= 2:
        for index, first in enumerate(known):
            for second in known[index + 1:]:
                label = f"Flowing Response: {NAMES[first]} + {NAMES[second]} (Martial Focus)"
                key = f"pair_{first.rsplit('_', 3)[-1].lower()}_{second.rsplit('_', 3)[-1].lower()}"
                out.append(make(key, label, {"type": "flowing_choice", "talents": [first, second]}))
    out.append(make("step_on", "Flowing Response: step away", {"type": "flowing_step", "on": True}))
    out.append(make("step_off", "Flowing Response: hold ground", {"type": "flowing_step", "on": False}))
    return out


@effect("flowing_choice")
def flowing_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    talents = eff.get("talents")
    if talents:
        data = {"talents": list(talents), "label": f"Flowing Response applies {' + '.join(NAMES.get(str(t), '') for t in talents)} "
                                                    "(Martial Focus, Two Currents Meet)"}
    else:
        data = {"talent": eff.get("talent"), "label": f"Flowing Response applies {NAMES.get(str(eff.get('talent')), '')}"}
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)


@effect("flowing_step")
def flowing_step(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, STEP, ctx.source)
    if eff.get("on"):
        ctx.engine._apply_condition(ctx.actor, STEP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Flowing Response: step away after a success"})


# ------------------------------------------------------------------------------------------------ Patient Water
@hook("action_completed")
def patient_water_dodge(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    if source_definition_id != "system:combat.dodge" or not _rows_kind(engine, actor, "patient_water"):
        return
    _drop(engine, actor, PATIENT, PATIENT_SOURCE)
    engine._apply_condition(actor, PATIENT, PATIENT_SOURCE, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Patient Water: if no hostile creature makes an attack roll against you before the start of "
                                           "your next turn, you regain Martial Focus then"})


@hook("event")
def patient_water_attacked(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED" or not engine.events:
        return
    event = engine.events[-1]
    attacker = engine.state.actors.get(str(event.actor_id or ""))
    for target_id in event.target_ids or ():
        target = engine.state.actors.get(target_id)
        if target is not None and attacker is not None and attacker.team_id != target.team_id \
                and any(c.condition_id == PATIENT for c in target.conditions.values()):
            _drop(engine, target, PATIENT, PATIENT_SOURCE)


@hook("turn_start")
def patient_water_regain(engine: Any, actor: Any) -> None:
    if not any(c.condition_id == PATIENT for c in actor.conditions.values()):
        return
    _drop(engine, actor, PATIENT, PATIENT_SOURCE)
    _regain_focus(engine, actor, PATIENT_SOURCE)


@hook("after_miss")
def native_response_miss(ctx: Any, target: Any) -> None:
    _native_response_complete(ctx, target, False)


@hook("after_hit")
def native_response_hit(ctx: Any, target: Any, kind: str) -> None:
    _native_response_complete(ctx, target, True)


def _native_response_complete(ctx: Any, target: Any, hit: bool) -> None:
    """New sealed responses finish native attacks through existing notifications."""
    notice = getattr(ctx, "attack_notice", None)
    if notice is None:
        return
    pending = ctx.engine.__dict__.get("_flowing_pending", {})
    key = (ctx.actor.entity_id, target.entity_id)
    mark = pending.get(key)
    if not isinstance(mark, dict) or not mark.get("second_pass"):
        return  # legacy saved rows retain their historical behavior
    pending.pop(key)
    for mid, modifier in list(target.modifiers.items()):
        if modifier.source_definition_id == f"flowing_response:{ctx.actor.entity_id}" and modifier.target_field == "armor_class":
            del target.modifiers[mid]
            ctx.engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=target.entity_id,
                target_ids=(target.entity_id,), payload={"modifier_id": mid, "reason": "ATTACK_RESOLVED"})
    if not hit and target.active and ctx.actor.active:
        _succeed(ctx.engine, target, ctx.actor, ctx=ctx, attack=ctx.attack_effect or {})


@hook("before_attack")
def native_response_declared(engine: Any, attacker: Any, reactor: Any, intent: Any, trigger: dict[str, Any]) -> dict[str, Any] | None:
    """Offer newly sealed attack responses on native declarations as on typed ones."""
    from .attack_scope import current
    from .. import typed_reactions

    if current(engine) is not None:
        return None  # the typed declared-attack route already owns this response
    row = _response_row(engine, reactor)
    if row is None or not any(e.get("type") == "flowing_yield_attack" and e.get("second_pass")
                              for e in row.get("effects") or []):
        return None
    action = trigger.get("action") or engine.action_catalog.get(trigger.get("source_id"))
    if action is None or action.reach_ft is None or not _available(engine, reactor, row):
        return None
    if not typed_reactions._subject_ok(engine, reactor, attacker, row):
        return None
    if not typed_reactions.declaration_priority_ok(engine, reactor, attacker, row, ranged=False):
        return None
    if not typed_reactions._consent(engine, row, reactor, "ATTACK_DECLARED", trigger={
            "actor_id": attacker.entity_id, "target_id": reactor.entity_id,
            "source_id": trigger.get("source_id"), "action_name": action.display_name}):
        return None
    typed_reactions._open(engine, row, reactor, (attacker.entity_id,), "ATTACK_DECLARED")
    typed_reactions._spend_generic(engine, reactor, row)
    typed_reactions.spend_reaction(engine, reactor, row)
    yield_attack(_reactor_context(engine, reactor, attacker), {"second_pass": True})
    return {}
