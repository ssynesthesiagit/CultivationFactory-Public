"""Last-Inch Palm (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Last-Inch Palm: Spirit-Touch Unarmed Strike, Handspan Subject, CL3 The Last
Inch, CL6 Nothing Crosses Unanswered, CL10 Palm Across Emptiness, CL14 Inside Every Guard, CL18 World of One Handspan). No Spheres 5e
or D&D 5.5e counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json.

Handspan Subject (tradition text): a condition on one creature ("Handspan Subject of ..."), until the end of your next turn (the
scene after a failed Palm Across Emptiness); designating another ends it. Inside your World of One Handspan every hostile creature in
the Domain also counts.

What runs:
  * Spirit-Touch Unarmed Strike (a button: Wisdom for attack and damage, 1d8 Bludgeoning or Psychic): reach 5 feet, 10 feet against
    your Handspan Subject (Handspan Reach), 30 feet against it with Inside Every Guard, anywhere in your World of One Handspan.
  * Designating the Subject (once on each of your turns, asked): a creature within 10 feet that your Spirit-Touch strike damages,
    that fails against your Mind Spike, or that your Resonance Mark lands on.
  * Last-Inch Step (Reaction, once per round, asked): your Subject within 15 feet ends a move inside or outside your 10-foot reach ->
    move 5 feet without provoking it: stay adjacent, back off 5 feet, or impose Heavy Soul or Stilled Intent (marked subject).
  * Nothing Crosses Unanswered (Reaction, 2 Resonance, asked; 30 feet with Inside Every Guard): your Subject within 15 feet makes a
    melee attack on you or a creature adjacent to you -> its Wisdom save first. Failed: the attack needs 10 more feet of reach -- it
    fails unless its reach covers that; if it still reaches, Disadvantage and no Reactions until the start of its next turn.
    Success: +2 AC against it. After it, you may move 5 feet without provoking it; if it failed or missed, Palm at the Threshold
    (asked): Mind Spike one die fewer, move it 5 feet on a failed Strength-or-Wisdom save, or your chosen Spiritual Pressure.
  * Palm Across Emptiness: on the target as its Handspan Subject (the reviewed rows plus the designation: the scene on a failed save,
    until the end of your next turn on a success); offered only on your Subject or a creature bearing your Resonance Mark.
  * Inside Every Guard: Contact Without Adjacency (reach above; Nothing Crosses Unanswered at 30 feet). Follow the Contact (once per
    round, asked): your Subject moves of its own will within 60 feet -> you move up to 15 feet (no more than it moved) without
    provoking it, toward a space within 10 feet of where it stopped. "Open the Gripping Hand" (Bonus Action, 2 Resonance): Grappled or
    Restrained by your Subject -> a Cultivation Check against its escape DC ends that hold.
  * World of One Handspan (Bonus Action, 10 Resonance, Concentration, 30-foot aura): hostile creatures in it count as Handspan
    Subjects; Contact Cannot Be Stolen (the first time each round each of them makes a melee attack on an ally in the Domain: its
    Wisdom save -- failed, Disadvantage, or the attack fails when it is more than 5 feet away; success, no Reactions until the start
    of its next turn); "Ten Thousand Hands" buttons, once per turn -- Palm (no Resonance, 3d8 + Wisdom), a strike on up to PB
    Subjects, carry an ally 15 feet without provoking, or a Subject's Wisdom save (moved 15 feet, 5 on a success).

Plug-in surface: effects handspan_designate, handspan_grip, handspan_world, handspan_palm, handspan_hands_strike, handspan_hands_carry,
handspan_hands_move; hooks compile_actions, candidate_allowed, damage_dealt, mark_applied, after_save, event, before_attack,
hit_response. Shared helpers used: spirit_traditions (row/context/numbers/feature_action/can_react/routes/choose_route/pick_creature/
save/remove/mind_spike), needle, rider_movement, zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.last_inch_palm.feature."
LAST_INCH = TRADITION + "the_last_inch"
NOTHING = TRADITION + "nothing_crosses_unanswered"
PALM = TRADITION + "palm_across_emptiness"
GUARD = TRADITION + "inside_every_guard"
WORLD = TRADITION + "world_of_one_handspan"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
SUBJECT = "condition:typed.handspan_subject"
WORLD_STATE = "condition:typed.world_of_one_handspan"
RESONANCE = "resource:core.resonance"
_PENDING = "_c8_nothing_crosses"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _pos(cell: Any) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=int(cell[0]), y=int(cell[1]))


# ---------------------------------------------------------------------------------------------------------- the Handspan Subject
def _world(palm: Any) -> Any:
    return next((c for c in palm.conditions.values() if c.condition_id == WORLD_STATE and c.source_actor_id == palm.entity_id), None)


def in_world(engine: Any, palm: Any, creature: Any) -> bool:
    from .. import zones

    held = _world(palm)
    zone = next((z for z in zones.typed_zones(engine) if held is not None and z.owner_id == palm.entity_id
                 and z.source_definition_id == held.source_definition_id), None)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


def is_subject(engine: Any, palm: Any, creature: Any) -> bool:
    if creature is None or not creature.active:
        return False
    if any(c.condition_id == SUBJECT and c.source_actor_id == palm.entity_id for c in creature.conditions.values()):
        return True
    return creature.team_id != palm.team_id and _world(palm) is not None and in_world(engine, palm, creature)  # "All Within Reach of the Spirit"


def designate(engine: Any, palm: Any, creature: Any, *, scene: bool = False) -> None:
    for holder in list(engine.state.actors.values()):
        for held in [c for c in holder.conditions.values() if c.condition_id == SUBJECT and c.source_actor_id == palm.entity_id]:
            st.remove(engine, holder, held, "REPLACED")  # "Designating another ends the previous designation"
    if scene:
        expires = "UNTIL_REMOVED"
    else:
        ctx = st.context(engine, palm, st.feature_action(engine, palm, LAST_INCH), [creature], st.numbers(engine, palm))
        expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_your_next_turn"}}, creature, condition=True)
    engine._apply_condition(creature, SUBJECT, LAST_INCH, palm.entity_id, expires_on=expires,
                            data={"label": f"Handspan Subject of {palm.display_name}" + (" (the scene)" if scene else "")})


def _offer_designation(engine: Any, palm: Any, creature: Any, why: str, intent: Any) -> None:
    if (creature is None or not creature.active or creature is palm or st.row(engine, palm, "the_last_inch") is None
            or engine.state.current_actor_id != palm.entity_id or palm.turn_flags.get("handspan_designated")
            or engine._distance_actor_to_actor(palm, creature) > 10 or is_subject(engine, palm, creature)):
        return
    from . import needle

    chosen = needle.ask(engine, intent or engine._active_intent, needle.checkpoint_id(engine, "HANDSPAN", creature.entity_id), palm, "choice:needle.last_inch.designate",
                        ["designate"], labels={"designate": f"Make {creature.display_name} your Handspan Subject until the end of your next turn"},
                        prompt=f"{why}. Designate it as your Handspan Subject?", preferred=["designate"] if creature.team_id != palm.team_id else [],
                        allow_decline=True, default="first" if creature.team_id != palm.team_id else "decline", name="Handspan Subject",
                        feature_id=LAST_INCH, target_id=creature.entity_id)
    if chosen:
        palm.turn_flags["handspan_designated"] = True  # "Once on each of your turns"
        designate(engine, palm, creature)


@effect("handspan_designate")
def designate_row(ctx: Any, row: dict[str, Any]) -> None:
    """Palm Across Emptiness: it "becomes your Handspan Subject until the end of the scene" (failed) / "until the end of your next turn"."""
    if ctx.target is not None and ctx.target.active:
        designate(ctx.engine, ctx.actor, ctx.target, scene=bool(row.get("scene")))


@hook("damage_dealt")
def strike_designates(ctx: Any, target: Any, amount: int) -> None:
    if (ctx.action.parameters or {}).get("spirit_touch") and amount > 0:
        _offer_designation(ctx.engine, ctx.actor, target, f"Your Spirit-Touch strike damages {target.display_name}", ctx.intent)


@hook("mark_applied")
def mark_designates(ctx: Any, name: str, subject: Any) -> None:
    te = _te()
    if subject is not None and te.mark_condition_id(str(name), ctx.actor.entity_id) == te.mark_condition_id("Resonance", ctx.actor.entity_id):
        _offer_designation(ctx.engine, ctx.actor, subject, f"Your Resonance Mark lands on {subject.display_name}", ctx.intent)


@hook("after_save")
def spike_designates(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if failed and (ctx.typed or {}).get("source") == MIND_SPIKE:
        _offer_designation(ctx.engine, ctx.actor, subject, f"{subject.display_name} fails against your Mind Spike", ctx.intent)


# ---------------------------------------------------------------------------------------------------------- Spirit-Touch strike
def strike_reach(engine: Any, palm: Any, target: Any) -> int:
    if is_subject(engine, palm, target):
        if _world(palm) is not None and in_world(engine, palm, target):
            return 60  # "from anywhere in the Domain" (a 30-foot aura around you)
        return 30 if st.row(engine, palm, "inside_every_guard") is not None else 10
    return 5


@hook("compile_actions")
def palm_buttons(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    base = {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}
    if LAST_INCH in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.spirit_touch_strike", display_name="Spirit-Touch Unarmed Strike", owner_id=info["actor_id"],
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
            parameters={"typed": {**base, "source": LAST_INCH, "effects": [{"type": "attack", "attack_kind": "unarmed", "count": 1,
                         "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "formula": "key_ability_modifier",
                                     "damage_types": ["bludgeoning", "psychic"], "evidence": "1d8 + Wisdom modifier Bludgeoning or Psychic"}], "on_miss": []}]},
                        "expected_damage": 8, "spirit_touch": True,
                        "description": "Spirit-Touch Unarmed Strike: an unarmed strike using Wisdom for attack and damage (1d8 Bludgeoning or Psychic). Reach 5 "
                                       "feet; 10 feet against your Handspan Subject (30 with Inside Every Guard; anywhere in your World of One Handspan)."}))
    if GUARD in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.open_the_gripping_hand", display_name="Open the Gripping Hand", owner_id=info["actor_id"],
            economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", costs=((RESONANCE, 2),),
            parameters={"typed": {**base, "source": GUARD, "effects": [{"type": "handspan_grip", "applies_to": "self"}]}, "expected_damage": 0,
                        "handspan_grip": True,
                        "description": "Inside Every Guard (Bonus Action, 2 Resonance): Grappled or Restrained by your Handspan Subject -- a Cultivation Check "
                                       "against its escape DC ends that hold."}))
    if WORLD in owned:
        hands = [("palm", "Palm Across Emptiness (no Resonance, 3d8 + Wisdom)", "HOSTILE_ENTITY", 60, [{"type": "handspan_palm", "applies_to": "target", "harmful": True}], 15),
                 ("strike", "strike up to PB Handspan Subjects", "SELF", None, [{"type": "handspan_hands_strike", "applies_to": "self"}], 16),
                 ("carry", "carry a willing creature 15 feet", "ALLY_OR_SELF", 60, [{"type": "handspan_hands_carry", "applies_to": "target"}], 0),
                 ("move", "move a Handspan Subject", "HOSTILE_ENTITY", 60, [{"type": "handspan_hands_move", "applies_to": "target", "harmful": True}], 0)]
        for key, label, kind, reach, effects, damage in hands:
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.ten_thousand_hands.{key}", display_name=f"Ten Thousand Hands: {label}",
                owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=kind, range_ft=reach,
                parameters={"typed": {**base, "source": WORLD, "effects": effects}, "expected_damage": damage, "ten_thousand_hands": key,
                            "description": f"World of One Handspan (Action, once per turn): {label}."}))
    return out or None


@hook("candidate_allowed")
def palm_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (action.parameters or {}) if action is not None else {}
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if params.get("spirit_touch"):
        if target is None or engine._distance_actor_to_actor(actor, target) > strike_reach(engine, actor, target):
            return False
        return None if engine._line_of_sight_actor_to_actor(actor, target) else False
    if params.get("handspan_grip"):
        return None if _grips(engine, actor) else False
    hands = params.get("ten_thousand_hands")
    if hands:
        if _world(actor) is None or actor.turn_flags.get("ten_thousand_hands"):
            return False
        if hands in ("palm", "move"):
            return None if target is not None and is_subject(engine, actor, target) and in_world(engine, actor, target) else False
        if hands == "carry":
            return None if target is not None and in_world(engine, actor, target) else False
        return None if any(is_subject(engine, actor, c) and in_world(engine, actor, c) for c in engine.state.actors.values()) else False
    if action is not None and st.feature_of(action) == PALM:
        return None if target is not None and (is_subject(engine, actor, target) or _te().bears_mark(target, actor.entity_id, "Resonance")) else False
    return None


# ---------------------------------------------------------------------------------------------------------- Last-Inch Step, Follow the Contact
@hook("event")
def subject_moves(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    path = payload.get("path") or []
    if mover is None or not mover.active or payload.get("forced") or payload.get("dragged_by") or len(path) < 2:
        return
    start = _pos((path[0]["x"], path[0]["y"]))
    for palm in list(engine.state.actors.values()):
        if not palm.active or palm is mover or not is_subject(engine, palm, mover):
            continue
        before = engine._distance_actor_to_actor(mover, palm, actor_position=start)
        after = engine._distance_actor_to_actor(mover, palm)
        if st.row(engine, palm, "the_last_inch") is not None and after <= 15 and ((before > 10) != (after > 10)):
            _last_inch_step(engine, palm, mover)
        if st.row(engine, palm, "inside_every_guard") is not None and after <= 60:
            _follow(engine, palm, mover, (len(path) - 1) * engine.grid.square_size_ft)


def _last_inch_step(engine: Any, palm: Any, subject: Any) -> None:
    if not st.can_react(palm) or palm.turn_flags.get("last_inch_step_round_") == engine.state.round_number:
        return
    from . import needle

    routes = {cell: v for cell, v in st.routes(engine, palm, 5).items() if cell != palm.position}
    adjacent = {c: v for c, v in routes.items() if engine._distance_actor_to_actor(palm, subject, actor_position=c) <= 5}
    farther = {c: v for c, v in routes.items() if engine._distance_actor_to_actor(palm, subject, actor_position=c) > engine._distance_actor_to_actor(palm, subject)}
    options = {**({"adjacent": "Step 5 feet and stay adjacent to it"} if adjacent else {}), **({"away": "Step 5 feet farther from it"} if farther else {}),
               **({"pressure": "Impose Heavy Soul or Stilled Intent on it (Resonance Marked)"} if _te().bears_mark(subject, palm.entity_id, "Resonance") else {})}
    if not options:
        return
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "LAST_INCH_STEP", subject.entity_id), palm, "choice:needle.last_inch.step",
                        list(options), labels=options, preferred=["pressure"] if "pressure" in options else [], allow_decline=True,
                        default="first" if "pressure" in options else "decline", name="Last-Inch Step", feature_id=LAST_INCH, target_id=subject.entity_id,
                        prompt=f"Last-Inch Step (Reaction, once per round): {subject.display_name} moves at the edge of your reach.")
    if not chosen or chosen[0] not in options:
        return
    with activation(engine, palm, LAST_INCH):
        palm.reaction_available = False
        palm.turn_flags["last_inch_step_round_"] = engine.state.round_number
        engine._append_event("REACTION_RESOLVED", LAST_INCH, actor_id=palm.entity_id, target_ids=(subject.entity_id,),
                             payload={"checkpoint": "MOVEMENT", "reaction_name": "Last-Inch Step"})
        from .rider_movement import step

        if chosen[0] == "pressure":
            choice = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "LAST_INCH_PRESSURE", subject.entity_id), palm,
                                "choice:needle.last_inch.step_pressure", ["heavy_soul", "stilled_intent"],
                                labels={"heavy_soul": "Heavy Soul (-10 feet Speed)", "stilled_intent": "Stilled Intent (no Reactions)"}, preferred=["stilled_intent"],
                                prompt="Which Spiritual Pressure?", name="Last-Inch Step", feature_id=LAST_INCH, target_id=subject.entity_id)
            _te().run_effects(st.context(engine, palm, st.feature_action(engine, palm, LAST_INCH), [subject], st.numbers(engine, palm)),
                              [{"type": "spiritual_pressure", "applies_to": "target", "option": (choice or ["stilled_intent"])[0], "evidence": "impose Heavy Soul or Stilled Intent"}])
            path = st.choose_route(engine, palm, routes, engine._active_intent, checkpoint="LAST_INCH_STEP_MOVE", prompt="Last-Inch Step: move 5 feet?",
                                   name="Last-Inch Step", feature=LAST_INCH) if routes else None
        else:
            pool = adjacent if chosen[0] == "adjacent" else farther
            best = min(pool, key=lambda c: (pool[c][1], c.y, c.x))
            path = st.choose_route(engine, palm, pool, engine._active_intent, checkpoint="LAST_INCH_STEP_MOVE", prompt="Last-Inch Step: to which square?",
                                   name="Last-Inch Step", feature=LAST_INCH, preferred=best, stay=False)
        if path is not None:
            step(engine, palm, list(path), LAST_INCH)


def _follow(engine: Any, palm: Any, subject: Any, moved: int) -> None:
    if palm.turn_flags.get("follow_contact_round_") == engine.state.round_number or engine._effective_speed(palm) <= 0:
        return
    reach = min(15, moved)  # "cannot exceed the distance the subject moved"
    routes = {c: v for c, v in st.routes(engine, palm, reach).items() if c != palm.position and engine._distance_actor_to_cell(subject, c) <= 10}
    if not routes:
        return
    best = min(routes, key=lambda c: (engine._distance_actor_to_cell(subject, c), routes[c][1], c.y, c.x))
    path = st.choose_route(engine, palm, routes, engine._active_intent, checkpoint="FOLLOW_THE_CONTACT",
                           prompt=f"Follow the Contact (once per round): move up to {reach} feet after {subject.display_name}?", name="Follow the Contact",
                           feature=GUARD, preferred=best, stay=True)
    if path is None:
        return
    palm.turn_flags["follow_contact_round_"] = engine.state.round_number
    from .rider_movement import step

    step(engine, palm, list(path), GUARD)


# ---------------------------------------------------------------------------------------------------------- Nothing Crosses Unanswered
@hook("before_attack")
def nothing_crosses(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if attacker is None or defender is None or attacker.team_id == defender.team_id:
        return None
    reach = int(context.get("range_ft") or 5)
    if reach > 10:
        return None  # a melee attack (the table's reach)
    for palm in list(engine.state.actors.values()):
        if not palm.active or palm.team_id != defender.team_id or not is_subject(engine, palm, attacker):
            continue
        if palm is not defender and engine._distance_actor_to_actor(palm, defender) > 5:
            continue  # "you or a willing creature adjacent to you"
        if st.row(engine, palm, "nothing_crosses_unanswered") is not None and st.can_react(palm) and palm.resources.get(RESONANCE, 0) >= 2:
            limit = 30 if st.row(engine, palm, "inside_every_guard") is not None else 15
            if engine._distance_actor_to_actor(palm, attacker) <= limit:
                answer = _nothing_crosses(engine, palm, attacker, defender, intent, context, reach)
                if answer is not None:
                    return answer
        if _world(palm) is not None and in_world(engine, palm, attacker) and in_world(engine, palm, defender):
            answer = _contact_not_stolen(engine, palm, attacker, defender, context, reach)
            if answer is not None:
                return answer
    return None


def _nothing_crosses(engine: Any, palm: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any], reach: int) -> dict[str, Any] | None:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "NOTHING_CROSSES", attacker.entity_id, context.get("attack_index", 1)), palm,
                        "choice:needle.last_inch.nothing_crosses", ["answer"],
                        labels={"answer": f"Nothing Crosses Unanswered (Reaction, 2 Resonance): {attacker.display_name} makes a Wisdom save first"},
                        prompt=f"{attacker.display_name} attacks {defender.display_name}. On a failed save the attack needs 10 more feet of reach.",
                        preferred=["answer"], allow_decline=True, name="Nothing Crosses Unanswered", feature_id=NOTHING, target_id=attacker.entity_id)
    if not chosen:
        return None
    with activation(engine, palm, NOTHING):
        engine._spend_resource(palm, RESONANCE, 2, NOTHING)
        palm.reaction_available = False
        engine._append_event("REACTION_RESOLVED", NOTHING, actor_id=palm.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Nothing Crosses Unanswered"})
        ctx = st.context(engine, palm, st.feature_action(engine, palm, NOTHING), [attacker], st.numbers(engine, palm), intent)
        failed = st.save(ctx, attacker, "wis")
        distance = engine._distance_actor_to_actor(attacker, defender)
        mode = "fails" if failed and reach < distance + 10 else "disadvantage" if failed else "ac"
        preserve_pending(engine, _PENDING)
        engine.__dict__[_PENDING] = {"attacker": attacker.entity_id, "defender": defender.entity_id, "palm": palm.entity_id, "mode": mode,
                                     "events": len(engine.events), "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"}
        retain(engine, _PENDING, capture(engine))
        if failed:
            _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                                     "evidence": "the source cannot take Reactions until the start of its next turn"}])
        return {"mode": "DISADVANTAGE"} if mode == "disadvantage" else {}


def _contact_not_stolen(engine: Any, palm: Any, attacker: Any, defender: Any, context: dict[str, Any], reach: int) -> dict[str, Any] | None:
    key = f"contact_not_stolen_round_{palm.entity_id}"
    if attacker.turn_flags.get(key) == engine.state.round_number:
        return None
    attacker.turn_flags[key] = engine.state.round_number  # "The first time each round"
    ctx = st.context(engine, palm, engine.action_catalog.get(_world(palm).source_definition_id) or st.feature_action(engine, palm, WORLD), [attacker],
                     st.numbers(engine, palm))
    if st.save(ctx, attacker, "wis"):
        if engine._distance_actor_to_actor(attacker, defender) > 5:
            preserve_pending(engine, _PENDING)
            engine.__dict__[_PENDING] = {"attacker": attacker.entity_id, "defender": defender.entity_id, "palm": palm.entity_id, "mode": "fails",
                                         "events": len(engine.events), "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}",
                                         "world": True}
            retain(engine, _PENDING, None)
            return {}
        return {"mode": "DISADVANTAGE"}
    _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                             "evidence": "the source cannot take Reactions until the start of its next turn"}])
    return None


def _pending(engine: Any, attacker_id: str | None) -> dict[str, Any] | None:
    held = engine.__dict__.get(_PENDING)
    return held if held and held.get("attacker") == attacker_id else None


@hook("hit_response")
def nothing_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    held = _pending(engine, getattr(attacker, "entity_id", None))
    if held is None or held.get("defender") != target.entity_id:
        return None
    rolled = [e for e in engine.events[int(held.get("events") or 0):] if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id]
    with causal_scope(engine, take(engine, _PENDING)):
        preserve_pending(engine, _PENDING)
        engine.__dict__.pop(_PENDING, None)
        if len(rolled) != 1 or str((rolled[0].payload or {}).get("reason") or "") != held.get("roll"):
            return None
        if held["mode"] == "fails":
            _after(engine, held, missed=True)
            from ..attack_outcomes import unconditional_miss

            return unconditional_miss()  # "it fails against the protected creature": no AC was compared
        if held["mode"] == "ac" and natural != 20 and total < effective_ac + 2:
            _after(engine, held, missed=True)
            return effective_ac + 2, False
        _after(engine, held, missed=False)
        return None


@hook("event")
def nothing_missed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED":
        return
    held = _pending(engine, kwargs.get("actor_id"))
    payload = kwargs.get("payload") or {}
    if held is None or str(payload.get("reason") or "") != held.get("roll") or payload.get("provisional_hit"):
        return
    with causal_scope(engine, take(engine, _PENDING)):
        preserve_pending(engine, _PENDING)
        engine.__dict__.pop(_PENDING, None)
        _after(engine, held, missed=True)


def _after(engine: Any, held: dict[str, Any], *, missed: bool) -> None:
    """After the trigger: a free 5-foot move, and Palm at the Threshold when it failed or missed."""
    if held.get("world"):
        return  # Contact Cannot Be Stolen "does not activate Palm at the Threshold"
    palm, attacker = engine.state.actors.get(held["palm"]), engine.state.actors.get(held["attacker"])
    protected = engine.state.actors.get(held["defender"])
    if palm is None or attacker is None or not palm.active:
        return
    from . import needle

    if missed and attacker.active:
        spike = st.action_named(engine, palm, "Mind Spike")
        options = {**({"spike": "Mind Spike against it, one damage die fewer"} if spike is not None and engine._distance_actor_to_actor(palm, attacker) <= int(spike.range_ft or 60) else {}),
                   "shove": "It makes a Strength or Wisdom save or moves 5 feet", "pressure": "Your chosen Spiritual Pressure effect"}
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "PALM_AT_THRESHOLD", attacker.entity_id), palm, "choice:needle.last_inch.threshold",
                            list(options), labels=options, preferred=["spike"] if "spike" in options else ["pressure"], allow_decline=True,
                            prompt="Palm at the Threshold: answer the failed contact?", name="Palm at the Threshold", feature_id=NOTHING, target_id=attacker.entity_id)
        pick = chosen[0] if chosen and chosen[0] in options else None
        ctx = st.context(engine, palm, st.feature_action(engine, palm, NOTHING), [attacker], st.numbers(engine, palm))
        if pick == "spike":
            st.mind_spike(engine, palm, attacker, engine._active_intent, dice_delta=-1)
        elif pick == "shove":
            st.save(ctx, attacker, "str_or_wis", on_fail=[{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away",
                                                          "evidence": "move it 5 feet on a failed Strength or Wisdom saving throw"}])
        elif pick == "pressure":
            _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect"}])
    routes = {c: v for c, v in st.routes(engine, palm, 5).items() if c != palm.position and (
        (protected is not None and engine._distance_actor_to_actor(palm, protected, actor_position=c) <= 5)
        or engine._distance_actor_to_actor(palm, attacker, actor_position=c) <= 5)}
    path = st.choose_route(engine, palm, routes, engine._active_intent, checkpoint="NOTHING_CROSSES_MOVE",
                           prompt="Nothing Crosses Unanswered: move 5 feet (adjacent to the protected creature or the subject)?", name="Nothing Crosses Unanswered",
                           feature=NOTHING) if routes else None
    if path is not None:
        from .rider_movement import step

        step(engine, palm, list(path), NOTHING)


# ---------------------------------------------------------------------------------------------------------- Open the Gripping Hand
def _grips(engine: Any, palm: Any) -> list[Any]:
    return [c for c in palm.conditions.values() if c.condition_id.rsplit(".", 1)[-1] in ("grappled", "restrained")
            and is_subject(engine, palm, engine.state.actors.get(c.source_actor_id or ""))]


@effect("handspan_grip")
def open_the_hand(ctx: Any, row: dict[str, Any]) -> None:
    from .end_effect import cultivation_dc

    engine, palm = ctx.engine, ctx.actor
    holds = _grips(engine, palm)
    if not holds or palm.turn_flags.get("gripping_hand_tried"):
        return
    hold = holds[0]
    source = engine.state.actors.get(hold.source_actor_id or "")
    dc = int((hold.data or {}).get("escape_dc") or (cultivation_dc(engine, source) if source is not None else 10))
    numbers = st.numbers(engine, palm)
    roll = engine.roll_check(
        modifier=int(numbers.get('pb') or 2) + int(numbers.get('key_mod') or 0),
        actor_id=palm.entity_id,
        reason=f'CHECK:{GUARD}:grip',
    )
    engine._record_roll(roll)
    engine._append_event("CHECK_ROLLED", GUARD, actor_id=palm.entity_id, payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc,
                                                                                "check": "Cultivation Check (Open the Gripping Hand)"})
    if roll.total >= dc:
        st.remove(engine, palm, hold, "ESCAPED")
    else:
        palm.turn_flags["gripping_hand_tried"] = True  # "You cannot attempt Open the Gripping Hand against the same effect again during the turn"


# ---------------------------------------------------------------------------------------------------------- World of One Handspan
@effect("handspan_world")
def world(ctx: Any, row: dict[str, Any]) -> None:
    held = _world(ctx.actor)
    if held is not None:
        st.remove(ctx.engine, ctx.actor, held, "REPLACED")
    ctx.engine._apply_condition(ctx.actor, WORLD_STATE, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                                data={"label": "World of One Handspan: every hostile creature in the Domain is your Handspan Subject"})


def _hands(ctx: Any) -> None:
    ctx.actor.turn_flags["ten_thousand_hands"] = True  # "Limit: Once per turn"


@effect("handspan_palm")
def hands_palm(ctx: Any, row: dict[str, Any]) -> None:
    """Palm Across Emptiness "without spending Resonance, but its damage becomes 3d8 + Wisdom modifier" (no Touch the Spirit)."""
    from . import needle

    engine, palm, target = ctx.engine, ctx.actor, ctx.target
    _hands(ctx)
    if target is None or not target.active:
        return
    expressions = {"draw": "Draw Into the Palm: pull it adjacent to you", "cast": "Cast Beyond Contact: move it up to 20 feet away",
                   "hold": "Hold at the Last Inch: Speed 0 and no Reactions until the start of your next turn"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HANDS_PALM", target.entity_id), palm, "choice:needle.last_inch.hands_palm",
                        list(expressions), labels=expressions, preferred=["hold"], prompt="Ten Thousand Hands: which contact expression on a failed save?",
                        name="Ten Thousand Hands", feature_id=WORLD, target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in expressions else "hold"
    rows = {"draw": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 30, "direction": "toward", "evidence": "Move it to a legal space adjacent to you"}],
            "cast": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 20, "direction": "away", "evidence": "Move it up to 20 feet away from you"}],
            "hold": [{"type": "speed", "applies_to": "target", "becomes": 0, "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "Its Speed becomes 0"},
                     {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "it cannot take Reactions"}]}[pick]
    failed = st.save(ctx, target, "wis",
                     on_fail=[{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "formula": "key_ability_modifier",
                               "damage_types": ["psychic", "force"], "evidence": "3d8 + Wisdom modifier Psychic or Force damage"}, *rows],
                     on_success=[{"type": "half_damage", "applies_to": "target", "evidence": "It takes half damage"}])
    designate(engine, palm, target, scene=failed)


@effect("handspan_hands_strike")
def hands_strike(ctx: Any, row: dict[str, Any]) -> None:
    """"one Spirit-Touch Unarmed Strike against up to your Proficiency Bonus different hostile Handspan Subjects in the Domain\""""
    engine, palm = ctx.engine, ctx.actor
    _hands(ctx)
    strike = next((engine.action_catalog[a] for a in palm.action_ids if a in engine.action_catalog and (engine.action_catalog[a].parameters or {}).get("spirit_touch")), None)
    if strike is None:
        return
    from . import needle
    from ..target_knowledge import can_see

    subjects = sorted((c for c in engine.state.actors.values() if c.active and c.team_id != palm.team_id
                       and is_subject(engine, palm, c) and in_world(engine, palm, c) and can_see(engine, palm, c)
                       and engine._line_of_sight_actor_to_actor(palm, c)), key=lambda c: (c.current_hp, c.entity_id))
    ids = [c.entity_id for c in subjects]
    count = min(len(ids), max(1, int(st.numbers(engine, palm).get("pb") or 2)))
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HANDS_STRIKE_SUBJECTS", palm.entity_id), palm,
                        "choice:needle.last_inch.hands_subjects", ids, labels={c.entity_id: c.display_name for c in subjects},
                        preferred=ids[:count], minimum=0, maximum=count, default="all", allow_decline=True,
                        prompt=f"Ten Thousand Hands: choose up to {count} different hostile creatures inside the field created by World of One Handspan.",
                        name="Ten Thousand Hands", feature_id=WORLD) if ids else []
    for subject in [c for c in subjects if c.entity_id in chosen]:
        st.run_action(engine, palm, strike, subject, ctx.intent)


@effect("handspan_hands_carry")
def hands_carry(ctx: Any, row: dict[str, Any]) -> None:
    engine, palm, target = ctx.engine, ctx.actor, ctx.target
    _hands(ctx)
    if target is None or not target.active:
        return
    routes = {c: v for c, v in st.routes(engine, target, 15).items() if c != target.position}
    path = st.choose_route(engine, palm, routes, ctx.intent, checkpoint="HANDS_CARRY", prompt=f"Ten Thousand Hands: carry {target.display_name} where?",
                           name="Ten Thousand Hands", feature=WORLD) if routes else None
    if path is not None:
        from .rider_movement import step

        step(engine, target, list(path), WORLD)


@effect("handspan_hands_move")
def hands_move(ctx: Any, row: dict[str, Any]) -> None:
    _hands(ctx)
    if ctx.target is None or not ctx.target.active:
        return
    st.save(ctx, ctx.target, "wis",
            on_fail=[{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away", "evidence": "moving it up to 15 feet on a failure"}],
            on_success=[{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away", "evidence": "or 5 feet on a success"}])


@effect("handspan_draw")
def draw_into_palm(ctx: Any, row: dict[str, Any]) -> None:
    """Choose actual adjacent contact; two size categories grant the printed second save."""
    from . import forced_destination, needle

    target = ctx.target
    if target is None or not target.active:
        return
    engine, palm = ctx.engine, ctx.actor
    sizes = ("TINY", "SMALL", "MEDIUM", "LARGE", "HUGE", "GARGANTUAN")
    mine = str(getattr(palm, "transformed_size_category", None) or getattr(palm, "size_category", "MEDIUM")).upper()
    theirs = str(getattr(target, "transformed_size_category", None) or getattr(target, "size_category", "MEDIUM")).upper()
    large = mine in sizes and theirs in sizes and sizes.index(theirs) - sizes.index(mine) >= 2
    reduced = large and not st.save(ctx, target, "str")
    if reduced:
        # Printed reduced move: "10 feet toward you" is a distance, so the walk is capped there and the
        # creature is offered the squares that land it as close to you as that cap allows.
        routes = forced_destination.routes(engine, target, 10,
            step_allowed=(lambda a, b: engine._distance_actor_to_actor(target, palm, actor_position=b)
                                      < engine._distance_actor_to_actor(target, palm, actor_position=a)))
        if routes:
            closest = min(engine._distance_actor_to_actor(target, palm, actor_position=c) for c in routes)
            routes = {c: path for c, path in routes.items()
                      if engine._distance_actor_to_actor(target, palm, actor_position=c) == closest}
    else:
        # Printed full move: "Move it to a legal space adjacent to you" states where it ends up, not how far
        # it walks -- the 30 feet above is this action's Range, not a travel budget. Every legal space
        # beside the caster is therefore offered, including the ones on the far side that need a longer
        # detour to reach.
        routes = forced_destination.routes(engine, target, None,
            goals=forced_destination.adjacent_spaces(engine, palm, target))
    forced_destination.ask(engine, ctx.intent, palm, target, routes, source=ctx.source,
        checkpoint=needle.checkpoint_id(engine, "HANDSPAN_DRAW", target.entity_id),
        choice_id="choice:needle.last_inch.draw_destination", ctx=ctx, name="Draw Into the Palm",
        prompt=f"Draw Into the Palm: choose a legal space {'within 10 feet toward you' if reduced else 'adjacent to you'} for {target.display_name}.")
