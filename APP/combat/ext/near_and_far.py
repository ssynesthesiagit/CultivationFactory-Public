"""Law of Near and Far (Spirit Awakening Secret Law; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Law of Near and Far: Near and Far Relations, CL3 Name What Is Near, CL6 Make
the Blow Far, CL10 Collapse the Interval, CL14 Cast Them to the Far Side, CL18 World Without Between). No Spheres 5e or D&D 5.5e
counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json.

Relations (Secret Law text): Near / Far are conditions on the subject ("Near to ..."/"Far from ..."), up to PB of them for the scene
(one more ends one of your choice; a temporary Far from Far Relation does not count). The table keeps them between creatures;
Near objects, Assets and spaces are the GM's.

What runs:
  * Name What Is Near (Bonus Action, 60 feet, 1 Resonance): a willing or Resonance Marked creature becomes Near (a willing one may
    use its Reaction to step 5 feet toward you, asked). Once on each of your turns after you move at least 5 feet, you may move 10
    feet toward a Near creature within 120 feet without provoking (asked). Far Relation (Reaction, 1 Resonance, asked): a creature
    makes a melee attack on you -> its Charisma save; failed, Far from you until the start of your next turn: its melee reach against
    you is 5 feet shorter (an attack that no longer reaches fails).
  * Make the Blow Far (Reaction, 3 Resonance, asked): a creature attacks you or a creature Near to you, or targets it with a
    single-target hostile save -> Far for that trigger: a melee attack no longer reaches and fails; any other attack has
    Disadvantage; a save has Advantage. After it you may move the Near protected creature 10 feet toward you; if the attack missed or
    the save succeeded, Far Shore Counter (asked): the attacker is Resonance Marked until the end of your next turn, cannot take
    Reactions until the start of its next turn, or the protected creature moves 5 more feet.
  * Collapse the Interval (5 Resonance; a Bonus Action button, and an Action button that may carry willing creatures adjacent to you
    for 2 Resonance each): you arrive in a legal space adjacent to a Near creature within 120 feet (a translation, not a walk); then
    Interval Strike (once per turn, 2 Resonance, asked): a weapon attack in reach or Mind Spike from where you arrived.
  * Cast Them to the Far Side (Action, 60 feet, 7 Resonance, 1 minute): Charisma save; failed -> Far-Sided (repeat save at the end of
    its turns) with a Far-Side Anchor object within 30 feet (AC your DC, 5 x PB HP; destroying it ends the effect; one at a time):
    every other creature is 30 feet farther away for its attacks and hostile techniques (targets beyond its range + 30 are not
    offered), and it cannot make Opportunity Attacks. Success: until the start of your next turn its reach and technique ranges are
    10 feet shorter (minimum 5).
  * World Without Between (Action, 120 feet, a 40-foot sphere, Concentration): up to your Wisdom modifier willing creatures form the
    Near Constellation (asked), up to PB hostile creatures the Far Constellation (Charisma save each). Far members are 20 feet farther
    away for their hostile targeting and cannot make Opportunity Attacks; they repeat the save at the end of their turns, two
    successes ending it. Near members may move 10 feet toward another member at the start of their turns (asked) and count as Near
    for Collapse the Interval. "Rewrite the Constellation" buttons (once per turn): a Near member moves 20 feet, two willing Near
    members exchange places, or a hostile creature in the field saves against joining the Far Constellation. Make Sanctuary
    Unreachable (once, Reaction, asked): a hostile attack on a Near member fails and until the start of its next turn it is Far from
    every hostile creature in the field (they cannot target it; it cannot attack; it may move 20 feet toward another Near member).

Plug-in surface: effects near_name, near_collapse, near_far_side, near_world, near_rewrite; hooks compile_actions, candidate_allowed,
event, before_attack, hit_response, save, after_save, turn_end, turn_start. Shared helpers used: spirit_traditions (row/context/
numbers/feature_action/can_react/routes/choose_route/pick_creature/save/remove/action_named/run_action/mind_spike), needle,
rider_movement, zones, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.law_of_near_and_far.feature."
NAME = TRADITION + "name_what_is_near"
BLOW = TRADITION + "make_the_blow_far"
COLLAPSE = TRADITION + "collapse_the_interval"
FAR_SIDE = TRADITION + "cast_them_to_the_far_side"
WORLD = TRADITION + "world_without_between"
NEAR = "condition:typed.near_relation"
FAR = "condition:typed.far_relation"
FAR_SIDED = "condition:typed.far_sided"
WORLD_STATE = "condition:typed.world_without_between"
CONSTELLATION = "condition:typed.constellation"
SANCTUARY = "condition:typed.unreachable_sanctuary"
ANCHOR = "object:typed.far_side_anchor:"
RESONANCE = "resource:core.resonance"
_PENDING = "_c8_blow_far"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _pos(cell: Any) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=int(cell[0]), y=int(cell[1]))


# ---------------------------------------------------------------------------------------------------------- relations
def relations(engine: Any, law: Any, *, kind: str | None = None, temporary: bool = False) -> list[tuple[Any, Any]]:
    out = []
    for creature in engine.state.actors.values():
        for held in creature.conditions.values():
            if held.condition_id in ((NEAR, FAR) if kind is None else ((NEAR,) if kind == "near" else (FAR,))) and held.source_actor_id == law.entity_id:
                if temporary or not (held.data or {}).get("temporary"):
                    out.append((creature, held))
    return sorted(out, key=lambda pair: pair[1].applied_sequence)


def near(engine: Any, law: Any, creature: Any) -> bool:
    if creature is None or not creature.active:
        return False
    if any(c.condition_id == NEAR and c.source_actor_id == law.entity_id for c in creature.conditions.values()):
        return True
    return _member(creature, law, "near")  # the Near Constellation counts for Collapse the Interval


def far(creature: Any, law: Any) -> bool:
    return any(c.condition_id == FAR and c.source_actor_id == law.entity_id for c in creature.conditions.values())


def relate(engine: Any, law: Any, creature: Any, kind: str, intent: Any, *, temporary: bool = False, expires: str = "UNTIL_REMOVED") -> None:
    from . import needle

    for held in [c for c in creature.conditions.values() if c.condition_id in (NEAR, FAR) and c.source_actor_id == law.entity_id]:
        st.remove(engine, creature, held, "REPLACED")  # "cannot be both Near and Far to you at the same time"
    if not temporary:
        held = relations(engine, law)
        limit = max(1, int(st.numbers(engine, law).get("pb") or 2))
        if len(held) >= limit:  # "Creating a relation beyond the limit ends one of your choice"
            ids = [f"r{i}" for i in range(len(held))]
            chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "RELATION_TO_END", law.entity_id), law, "choice:needle.near_far.end_relation",
                                ids, labels={f"r{i}": str((c.data or {}).get("label")) for i, (_who, c) in enumerate(held)}, preferred=ids[:1],
                                prompt="Your Near and Far relations are full: which one ends?", name="Near and Far", feature_id=NAME)
            who, condition = held[ids.index(chosen[0])] if chosen and chosen[0] in ids else held[0]
            st.remove(engine, who, condition, "REPLACED")
    word = "Near to" if kind == "near" else "Far from"
    engine._apply_condition(creature, NEAR if kind == "near" else FAR, NAME, law.entity_id, expires_on=expires,
                            data={"label": f"{word} {law.display_name}", **({"temporary": 1} if temporary else {})})


def _step_toward(engine: Any, mover: Any, toward: Any, feet: int, intent: Any, name: str, feature: str, *, chooser: Any = None) -> None:
    routes = {c: v for c, v in st.routes(engine, mover, feet).items() if c != mover.position
              and engine._distance_actor_to_actor(mover, toward, actor_position=c) < engine._distance_actor_to_actor(mover, toward)}
    if not routes:
        return
    best = min(routes, key=lambda c: (engine._distance_actor_to_actor(mover, toward, actor_position=c), routes[c][1], c.y, c.x))
    path = st.choose_route(engine, chooser or mover, routes, intent, checkpoint=f"{name.upper().replace(' ', '_')}_STEP",
                           prompt=f"{name}: move toward {toward.display_name}?", name=name, feature=feature, preferred=best)
    if path is not None:
        from .rider_movement import step

        step(engine, mover, list(path), feature)


# ---------------------------------------------------------------------------------------------------------- Name What Is Near
@effect("near_name")
def name_near(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, law, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    relate(engine, law, target, "near", ctx.intent)
    if target.team_id == law.team_id and target is not law and st.can_react(target):
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "NEAR_ANSWER", target.entity_id), target, "choice:needle.near_far.near_answer",
                            ["step"], labels={"step": f"Use your Reaction to move 5 feet toward {law.display_name} without provoking"},
                            prompt=f"{law.display_name} names you Near.", preferred=[], allow_decline=True, default="decline",
                            name="Name What Is Near", feature_id=NAME, target_id=law.entity_id)
        if chosen:
            from ..paid_relocation import activation as relocation_activation
            with relocation_activation(engine, target, NAME, independent=True):
                target.reaction_available = False
                _step_toward(engine, target, law, 5, ctx.intent, "Name What Is Near", NAME)


@hook("event")
def near_movement(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Name What Is Near, once a turn: after moving at least 5 feet the Law may move 10 feet toward the Near creature without
    provoking Opportunity Attacks."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    law = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if (law is None or not law.active or "planned_cost_ft" not in payload or st.row(engine, law, "name_what_is_near") is None
            or engine.state.current_actor_id != law.entity_id or law.turn_flags.get("near_step") or len(payload.get("path") or []) < 2):
        return
    targets = [c for c, _held in relations(engine, law, kind="near") if c.active and c is not law and engine._distance_actor_to_actor(law, c) <= 120]
    if not targets:
        return
    target = min(targets, key=lambda c: (engine._distance_actor_to_actor(law, c), c.entity_id))
    law.turn_flags["near_step"] = True
    _step_toward(engine, law, target, 10, engine._active_intent, "Near Relation", NAME)


# ---------------------------------------------------------------------------------------------------------- attacks: Far Relation, Make the Blow Far, Sanctuary
@hook("before_attack")
def far_answers(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if attacker is None or defender is None or attacker.team_id == defender.team_id:
        return None
    reach = int(context.get("range_ft") or 5)
    melee = reach <= 10
    roll = f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"
    distance = engine._distance_actor_to_actor(attacker, defender)
    for law in list(engine.state.actors.values()):
        if not law.active or law.team_id != defender.team_id:
            continue
        if law is defender and melee and far(attacker, law) and distance > max(0, reach - 5):
            _pending_set(engine, attacker, defender, law, roll, "fails", counter=False)
            return {}  # a standing Far relation: its melee reach against you is 5 feet shorter
        if _sanctuary_answer(engine, law, attacker, defender, intent, context):
            _pending_set(engine, attacker, defender, law, roll, "fails", counter=False)
            return {}
        if not st.can_react(law):
            continue
        if law is defender and melee and st.row(engine, law, "name_what_is_near") is not None and law.resources.get(RESONANCE, 0) >= 1 \
                and not far(attacker, law) and _far_relation(engine, law, attacker, intent, context):
            if distance > max(0, reach - 5):
                _pending_set(engine, attacker, defender, law, roll, "fails", counter=False)
                return {}
            return None
        if (st.row(engine, law, "make_the_blow_far") is not None and law.resources.get(RESONANCE, 0) >= 3
                and (defender is law or near(engine, law, defender))):
            if _blow_far(engine, law, attacker, defender, intent, context):
                mode = "fails" if melee else "disadvantage"
                _pending_set(engine, attacker, defender, law, roll, mode, counter=True)
                return {"mode": "DISADVANTAGE"} if mode == "disadvantage" else {}
    return None


def _far_relation(engine: Any, law: Any, attacker: Any, intent: Any, context: dict[str, Any]) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "FAR_RELATION", attacker.entity_id, context.get("attack_index", 1)), law,
                        "choice:needle.near_far.far_relation", ["far"], labels={"far": f"Far Relation (Reaction, 1 Resonance): {attacker.display_name} makes a Charisma save"},
                        prompt=f"{attacker.display_name} attacks you in melee. On a failed save it is Far from you and its reach against you 5 feet shorter.",
                        preferred=[], allow_decline=True, default="decline", name="Far Relation", feature_id=NAME, target_id=attacker.entity_id)
    if not chosen:
        return False
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, law, NAME, independent=True):
        engine._spend_resource(law, RESONANCE, 1, NAME)
        law.reaction_available = False
        engine._append_event("REACTION_RESOLVED", NAME, actor_id=law.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Far Relation"})
        ctx = st.context(engine, law, st.feature_action(engine, law, NAME), [attacker], st.numbers(engine, law), intent)
        if st.save(ctx, attacker, "cha"):
            relate(engine, law, attacker, "far", intent, temporary=True, expires="START_OF_SOURCE_NEXT_TURN")
            return True
        return False


def _blow_far(engine: Any, law: Any, attacker: Any, protected: Any, intent: Any, context: dict[str, Any]) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "BLOW_FAR", attacker.entity_id, context.get("attack_index", 1)), law,
                        "choice:needle.near_far.blow_far", ["far"],
                        labels={"far": f"Make the Blow Far (Reaction, 3 Resonance): {attacker.display_name}'s attack on {protected.display_name} is Far"},
                        prompt="A melee attack made Far fails; any other attack has Disadvantage.", preferred=["far"], allow_decline=True,
                        name="Make the Blow Far", feature_id=BLOW, target_id=attacker.entity_id)
    if not chosen:
        return False
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, law, BLOW, independent=True):
        engine._spend_resource(law, RESONANCE, 3, BLOW)
        law.reaction_available = False
        engine._append_event("REACTION_RESOLVED", BLOW, actor_id=law.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Make the Blow Far"})
        from ..paid_relocation import capture, retain
        retain(engine, ("near_far_blow", law.entity_id, attacker.entity_id, protected.entity_id), capture(engine))
        return True


def _pending_set(engine: Any, attacker: Any, defender: Any, law: Any, roll: str, mode: str, *, counter: bool) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _PENDING)
    engine.__dict__[_PENDING] = {"attacker": attacker.entity_id, "defender": defender.entity_id, "law": law.entity_id, "mode": mode,
                                 "events": len(engine.events), "roll": roll, "counter": counter}
    if counter:
        from ..paid_relocation import retain_effect, take
        receipt = take(engine, ("near_far_blow", law.entity_id, attacker.entity_id, defender.entity_id))
        if receipt is not None:
            retain_effect(engine, engine.__dict__[_PENDING], receipt)


def _pending(engine: Any, attacker_id: str | None) -> dict[str, Any] | None:
    held = engine.__dict__.get(_PENDING)
    return held if held and held.get("attacker") == attacker_id else None


@hook("hit_response")
def far_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _PENDING)
    held = _pending(engine, getattr(attacker, "entity_id", None))
    if held is None or held.get("defender") != target.entity_id:
        return None
    rolled = [e for e in engine.events[int(held.get("events") or 0):] if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id]
    engine.__dict__.pop(_PENDING, None)
    if len(rolled) != 1 or str((rolled[0].payload or {}).get("reason") or "") != held.get("roll"):
        return None
    if held["mode"] == "fails":
        _after(engine, held, missed=True)
        from ..attack_outcomes import unconditional_miss

        return unconditional_miss()  # "it fails against that target": no AC was compared
    _after(engine, held, missed=False)
    return None


@hook("event")
def far_missed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _PENDING)
    if event_type != "ATTACK_ROLLED":
        return
    held = _pending(engine, kwargs.get("actor_id"))
    payload = kwargs.get("payload") or {}
    if held is None or str(payload.get("reason") or "") != held.get("roll") or payload.get("provisional_hit"):
        return
    engine.__dict__.pop(_PENDING, None)
    _after(engine, held, missed=True)


def _after(engine: Any, held: dict[str, Any], *, missed: bool) -> None:
    if not held.get("counter"):
        return
    law, attacker, protected = (engine.state.actors.get(held[k]) for k in ("law", "attacker", "defender"))
    if law is None or attacker is None or protected is None:
        return
    from ..paid_relocation import causal_scope, take_effect
    with causal_scope(engine, take_effect(engine, held)):
        _far_shore(engine, law, attacker, protected, missed)


def _far_shore(engine: Any, law: Any, attacker: Any, protected: Any, success: bool) -> None:
    """After Make the Blow Far: the Near protected creature may move 10 feet toward you; Far Shore Counter on a miss or a won save."""
    from . import needle

    intent = engine._active_intent
    extra = 0
    if success and attacker.active:
        options = {"mark": f"{attacker.display_name} becomes Resonance Marked until the end of your next turn",
                   "still": f"{attacker.display_name} cannot take Reactions until the start of its next turn",
                   **({"further": f"{protected.display_name} moves 5 more feet"} if protected is not law and near(engine, law, protected) else {})}
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "FAR_SHORE", attacker.entity_id), law, "choice:needle.near_far.far_shore",
                            list(options), labels=options, preferred=["still"], prompt="Far Shore Counter: choose one.", name="Far Shore Counter",
                            feature_id=BLOW, target_id=attacker.entity_id)
        pick = chosen[0] if chosen and chosen[0] in options else "still"
        ctx = st.context(engine, law, st.feature_action(engine, law, BLOW), [attacker], st.numbers(engine, law))
        if pick == "mark":
            _te().run_effects(ctx, [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                     "evidence": "the attacker becomes Resonance Marked until the end of your next turn"}])
        elif pick == "still":
            _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                                     "evidence": "the attacker cannot take Reactions until the start of its next turn"}])
        else:
            extra = 5
    if protected is not law and protected.active and near(engine, law, protected):
        _step_toward(engine, protected, law, 10 + extra, intent, "Make the Blow Far", BLOW, chooser=law)


@hook("save")
def blow_far_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    engine, source = ctx.engine, ctx.actor
    if subject is None or source is None or source.team_id == subject.team_id or len(ctx.targets or []) != 1:
        return None  # "a single-target hostile technique"
    for law in list(engine.state.actors.values()):
        if (not law.active or law.team_id != subject.team_id or st.row(engine, law, "make_the_blow_far") is None or not st.can_react(law)
                or law.resources.get(RESONANCE, 0) < 3 or not (subject is law or near(engine, law, subject))):
            continue
        from . import needle

        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BLOW_FAR_SAVE", source.entity_id, subject.entity_id), law,
                            "choice:needle.near_far.blow_far_save", ["far"],
                            labels={"far": f"Make the Blow Far (Reaction, 3 Resonance): {subject.display_name} saves with Advantage"},
                            prompt=f"{source.display_name} targets {subject.display_name} with a hostile technique.", preferred=["far"],
                            allow_decline=True, name="Make the Blow Far", feature_id=BLOW, target_id=source.entity_id)
        if not chosen:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, law, BLOW, independent=True):
            engine._spend_resource(law, RESONANCE, 3, BLOW)
            law.reaction_available = False
            engine._append_event("REACTION_RESOLVED", BLOW, actor_id=law.entity_id, target_ids=(source.entity_id,),
                                 payload={"checkpoint": "SAVE", "reaction_name": "Make the Blow Far"})
            from ..paid_relocation import capture, retain_effect
            pending = {"law": law.entity_id, "source": source.entity_id}
            retain_effect(engine, pending, capture(engine))
            subject.turn_flags["blow_far_save"] = pending
            return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("after_save")
def blow_far_saved(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    held = subject.turn_flags.pop("blow_far_save", None) if subject is not None else None
    if not held:
        return
    law, source = ctx.engine.state.actors.get(held["law"]), ctx.engine.state.actors.get(held["source"])
    if law is not None and source is not None:
        from ..paid_relocation import causal_scope, take_effect
        with causal_scope(ctx.engine, take_effect(ctx.engine, held)):
            _far_shore(ctx.engine, law, source, subject, not failed)


# ---------------------------------------------------------------------------------------------------------- Collapse the Interval
@hook("compile_actions")
def near_buttons(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    base = {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}
    if COLLAPSE in owned:
        for economy, label, carry in ((EconomyKind.BONUS_ACTION, "Collapse the Interval", False), (EconomyKind.ACTION, "Collapse the Interval (carry allies)", True)):
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.collapse_the_interval.{'action' if carry else 'bonus'}", display_name=label,
                owner_id=info["actor_id"], economy=economy, resolution_kind="TYPED", target_kind="SELF", costs=((RESONANCE, 5),),
                parameters={"typed": {**base, "source": COLLAPSE, "effects": [{"type": "near_collapse", "applies_to": "self", "carry": carry}]},
                            "expected_damage": 0, "near_collapse": True,
                            "description": "Collapse the Interval (5 Resonance): arrive in a legal space adjacent to a creature Near to you within 120 feet"
                                           + (", carrying willing creatures adjacent to you (2 Resonance each, up to your Wisdom modifier)" if carry else "")
                                           + ". Then Interval Strike (once per turn, 2 Resonance): a weapon attack or Mind Spike from there."}))
    if WORLD in owned:
        for key, label, kind in (("move", "Rewrite the Constellation: move a Near member 20 feet", "ALLY_OR_SELF"),
                                 ("exchange", "Rewrite the Constellation: exchange two Near members", "SELF"),
                                 ("far", "Rewrite the Constellation: bind a foe to the Far Constellation", "HOSTILE_ENTITY")):
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.rewrite_constellation.{key}", display_name=label, owner_id=info["actor_id"],
                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind=kind, range_ft=None if kind == "SELF" else 120,
                parameters={"typed": {**base, "source": WORLD, "effects": [{"type": "near_rewrite", "applies_to": "self" if kind == "SELF" else "target", "mode": key,
                                                                             **({"harmful": True} if kind == "HOSTILE_ENTITY" else {})}]},
                            "expected_damage": 0, "rewrite_constellation": key,
                            "description": "World Without Between (once on each of your turns): " + label.split(": ", 1)[1] + "."}))
    return out or None


def _near_targets(engine: Any, law: Any) -> list[Any]:
    return [c for c in engine.state.actors.values() if c is not law and near(engine, law, c) and engine._distance_actor_to_actor(law, c) <= 120]


@effect("near_collapse")
def collapse(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, law = ctx.engine, ctx.actor
    targets = _near_targets(engine, law)
    subject = st.pick_creature(engine, ctx.intent, law, targets, checkpoint="COLLAPSE_TO", choice_id="choice:needle.near_far.collapse_to",
                               prompt="Collapse the Interval: to which Near creature?", name="Collapse the Interval", feature_id=COLLAPSE,
                               preferred=min(targets, key=lambda c: (c.team_id == law.team_id, engine._distance_actor_to_actor(law, c), c.entity_id), default=None))
    if subject is None:
        return
    travelers = [law]
    if row.get("carry"):
        near_me = [a for a in engine.state.actors.values() if a.active and a is not law and a.team_id == law.team_id and engine._distance_actor_to_actor(law, a) <= 5]
        room = min(max(1, int(st.numbers(engine, law).get("key_mod") or 1)), len(near_me), int(law.resources.get(RESONANCE, 0)) // 2)
        if near_me and room:
            ids = [a.entity_id for a in near_me]
            chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "COLLAPSE_CARRY", law.entity_id), law, "choice:needle.near_far.collapse_carry",
                                ids, labels={a.entity_id: a.display_name for a in near_me}, preferred=[], minimum=0, maximum=room, allow_decline=True,
                                default="decline", prompt="Carry which willing creatures (2 Resonance each)?", name="Collapse the Interval", feature_id=COLLAPSE)
            carried = [a for a in near_me if a.entity_id in (chosen or [])][:room]
            if carried:
                engine._spend_resource(law, RESONANCE, 2 * len(carried), COLLAPSE)
                travelers += carried
    from .teleport_steps import destinations
    # The 120-foot rule selects the Near subject above. Arrival is constrained
    # by adjacency to that subject and the shared native teleport defenses;
    # measuring range again from each traveler's origin incorrectly removes
    # legal cells on the far side (especially for carried creatures).
    map_reach = max(engine.grid.width, engine.grid.height) * engine.grid.square_size_ft
    for traveler in travelers:
        spots = [p for p in destinations(engine, traveler, map_reach, viewer=law)
                 if engine._distance_actor_to_actor(traveler, subject, actor_position=p) <= 5]
        if not spots:
            continue
        ids = [needle.cell_id(p) for p in spots]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "COLLAPSE_DESTINATION", traveler.entity_id), law,
                            "choice:needle.near_far.collapse_destination", ids, labels={i: f"Arrive at {i.removeprefix('cell:')}" for i in ids},
                            preferred=ids[:1], minimum=1, maximum=1, name="Collapse the Interval", feature_id=COLLAPSE,
                            target_id=traveler.entity_id, prompt=f"Collapse the Interval: choose {traveler.display_name}'s legal arrival adjacent to {subject.display_name}.")
        if chosen:
            _te().teleport_subject(ctx, traveler, spots[ids.index(chosen[0])])
    _interval_strike(engine, law, ctx.intent)


def _interval_strike(engine: Any, law: Any, intent: Any) -> None:
    from . import needle

    if law.turn_flags.get("interval_strike") or law.resources.get(RESONANCE, 0) < 2:
        return
    foes = [c for c in engine.state.actors.values() if c.active and c.team_id != law.team_id]
    weapons = [engine.action_catalog[a] for a in law.action_ids if a in engine.action_catalog and ((engine.action_catalog[a].parameters or {}).get("typed") or {}).get("weapon")
               and engine.action_catalog[a].economy.value == "ACTION" and "echo_origin" not in a and int((engine.action_catalog[a].parameters or {}).get("expected_damage") or 0) > 0
               and ((engine.action_catalog[a].parameters or {}).get("typed") or {}).get("source") != "improvised_weapon"]
    spike = st.action_named(engine, law, "Mind Spike")
    options: dict[str, tuple[str, Any, Any]] = {}
    for foe in foes:
        for weapon in weapons:
            if engine._distance_actor_to_actor(law, foe) <= int(weapon.range_ft or weapon.reach_ft or 5):
                options.setdefault(f"w:{foe.entity_id}", (f"{weapon.display_name} on {foe.display_name}", weapon, foe))
        if spike is not None and engine._distance_actor_to_actor(law, foe) <= int(spike.range_ft or 60):
            options.setdefault(f"s:{foe.entity_id}", (f"Mind Spike on {foe.display_name}", None, foe))
    if not options:
        return
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "INTERVAL_STRIKE", law.entity_id), law, "choice:needle.near_far.interval_strike",
                        list(options), labels={k: v[0] for k, v in options.items()}, preferred=list(options)[:1], allow_decline=True,
                        prompt="Interval Strike (2 Resonance, once per turn)?", name="Interval Strike", feature_id=COLLAPSE)
    if not chosen or chosen[0] not in options:
        return
    law.turn_flags["interval_strike"] = True
    engine._spend_resource(law, RESONANCE, 2, COLLAPSE)
    _label, weapon, foe = options[chosen[0]]
    if weapon is not None:
        st.run_action(engine, law, weapon, foe, intent)
    else:
        st.mind_spike(engine, law, foe, intent)


# ---------------------------------------------------------------------------------------------------------- Cast Them to the Far Side
def _far_sided(creature: Any) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == FAR_SIDED), None)


@effect("near_far_side")
def far_side(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    engine, law, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    if not st.save(ctx, target, "cha", on_success=[
            {"type": "condition", "applies_to": "target", "condition": "reach_shortened", "duration": {"kind": "until_start_of_your_next_turn"},
             "evidence": "Reach and hostile technique range down 10 feet until the start of your next turn"}]):
        return
    for creature in engine.state.actors.values():  # "You can maintain one Far-Side Anchor at a time"
        for held in [c for c in creature.conditions.values() if c.condition_id == FAR_SIDED and c.source_actor_id == law.entity_id]:
            _end_far_side(engine, creature, held, "REPLACED")
    numbers = ctx.numbers or st.numbers(engine, law)
    hp = 5 * int(numbers.get("pb") or 2)
    near_cells = [c for c in st.routes(engine, target, 30) if c != target.position]
    spot = near_cells[-1] if near_cells else target.position
    anchor = RuntimeObjectState(object_id=f"{ANCHOR}{law.entity_id}:{target.entity_id}:{engine.state.event_sequence}", object_kind="FAR_SIDE_ANCHOR", position=spot,
                                unattended=True, flammable=False, owner_id=law.entity_id, ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp,
                                damage_immunities=("PSYCHIC",), component={"far_side_of": target.entity_id, "label": "Far-Side Anchor"})
    engine._update_object(anchor, ctx.source, law.entity_id)
    engine._apply_condition(target, FAR_SIDED, ctx.source, law.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                            data={"anchor": anchor.object_id, "rule": {"no_opportunity_attacks": True},
                                  "label": "Far-Sided: every other creature is 30 feet farther away for its attacks and hostile techniques"})


def _end_far_side(engine: Any, holder: Any, held: Any, reason: str) -> None:
    anchor = engine.state.objects.get(str((held.data or {}).get("anchor") or ""))
    st.remove(engine, holder, held, reason)
    if anchor is not None and not anchor.destroyed:
        engine._update_object(anchor.model_copy(update={"destroyed": True, "current_hp": 0}), FAR_SIDE, held.source_actor_id)


@hook("event")
def far_side_anchor_breaks(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(ANCHOR) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    holder = engine.state.actors.get(str((obj.get("component") or {}).get("far_side_of") or ""))
    held = _far_sided(holder) if holder is not None else None
    if held is not None and (held.data or {}).get("anchor") == obj.get("object_id"):
        st.remove(engine, holder, held, "ANCHOR_DESTROYED")  # "Destroying ... the Anchor ends Far-Sided immediately"


# ---------------------------------------------------------------------------------------------------------- World Without Between
def _world(law: Any) -> Any:
    return next((c for c in law.conditions.values() if c.condition_id == WORLD_STATE and c.source_actor_id == law.entity_id), None)


def _member(creature: Any, law: Any, side: str) -> bool:
    return any(c.condition_id == CONSTELLATION and c.source_actor_id == law.entity_id and (c.data or {}).get("side") == side for c in creature.conditions.values())


def _in_world(engine: Any, law: Any, creature: Any) -> bool:
    from .. import zones

    held = _world(law)
    zone = next((z for z in zones.typed_zones(engine) if held is not None and z.owner_id == law.entity_id and z.source_definition_id == held.source_definition_id), None)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _join(engine: Any, law: Any, creature: Any, side: str, source: str) -> None:
    engine._apply_condition(creature, CONSTELLATION, source, law.entity_id, expires_on="CONCENTRATION_END",
                            data={"side": side, "successes": 0, **({"rule": {"no_opportunity_attacks": True}} if side == "far" else {}),
                                  "label": f"{side.title()} Constellation ({law.display_name})"})


@effect("near_world")
def world(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, law = ctx.engine, ctx.actor
    held = _world(law)
    if held is not None:
        st.remove(engine, law, held, "REPLACED")
    engine._apply_condition(law, WORLD_STATE, ctx.source, law.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                            data={"label": "World Without Between"})
    numbers = st.numbers(engine, law)
    inside = [c for c in engine.state.actors.values() if c.active and _in_world(engine, law, c)]
    allies = [c for c in inside if c.team_id == law.team_id]
    foes = [c for c in inside if c.team_id != law.team_id]
    for group, count, side, prompt in ((allies, max(1, int(numbers.get("key_mod") or 1)), "near", "the Near Constellation (willing creatures)"),
                                       (foes, int(numbers.get("pb") or 2), "far", "the Far Constellation (hostile creatures)")):
        if not group:
            continue
        ids = [c.entity_id for c in group]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, f"CONSTELLATION_{side.upper()}", law.entity_id), law,
                            f"choice:needle.near_far.constellation_{side}", ids, labels={c.entity_id: c.display_name for c in group}, preferred=ids[:count],
                            minimum=0, maximum=min(count, len(ids)), default="all", allow_decline=True, prompt=f"World Without Between: who joins {prompt}?",
                            name="World Without Between", feature_id=WORLD)
        for creature in [c for c in group if c.entity_id in (chosen or [])][:count]:
            if side == "far" and not st.save(ctx, creature, "cha"):
                continue  # an unwilling creature that saves is not placed in the Far Constellation
            _join(engine, law, creature, side, ctx.source)


@hook("turn_start")
def constellation_step(engine: Any, actor: Any) -> None:
    """A Near member may move 10 feet toward another Near member at the start of its turns, without provoking."""
    from . import needle

    for law in engine.state.actors.values():
        if not law.active or not _member(actor, law, "near"):
            continue
        others = [c for c in engine.state.actors.values() if c is not actor and c.active and _member(c, law, "near")]
        if others:
            available = st.routes(engine, actor, 10)
            toward = {target.entity_id: {c: v for c, v in available.items() if c != actor.position
                      and engine._distance_actor_to_actor(actor, target, actor_position=c) < engine._distance_actor_to_actor(actor, target)}
                      for target in others}
            others = sorted((c for c in others if toward[c.entity_id]),
                            key=lambda c: (engine._distance_actor_to_actor(actor, c), c.entity_id))
            if others:
                chosen = needle.ask(engine, engine._active_intent,
                                    needle.checkpoint_id(engine, "CONSTELLATION_MEMBER", actor.entity_id), actor,
                                    "choice:needle.constellation_member", [c.entity_id for c in others],
                                    labels={c.entity_id: f"Move toward {c.display_name}" for c in others},
                                    preferred=[others[0].entity_id], allow_decline=True, default="first",
                                    prompt=f"Near Constellation: {actor.display_name} can move up to 10 feet toward another Near member at the start of this turn, without provoking opportunity attacks or spending movement. Move toward whom?",
                                    name="World Without Between", feature_id=WORLD)
                if not chosen:
                    return
                target = next(c for c in others if c.entity_id == chosen[0])
                routes = toward[target.entity_id]
                path = st.choose_route(engine, actor, routes, engine._active_intent, checkpoint="CONSTELLATION_STEP",
                                       prompt=f"Near Constellation: move {actor.display_name} up to 10 feet toward {target.display_name}, without provoking opportunity attacks or spending movement?", name="World Without Between",
                                       feature=WORLD) if routes else None
                if path is not None:
                    from .rider_movement import step

                    step(engine, actor, list(path), WORLD)
        return


@hook("turn_end")
def far_repeats(engine: Any, actor: Any) -> None:
    for held in [c for c in actor.conditions.values() if c.condition_id == CONSTELLATION and (c.data or {}).get("side") == "far"]:
        law = engine.state.actors.get(held.source_actor_id or "")
        if law is None or not actor.active:
            continue
        ctx = st.context(engine, law, st.feature_action(engine, law, WORLD), [actor], st.numbers(engine, law))
        if not st.save(ctx, actor, "cha"):
            successes = int(st.data_of(actor, held).get("successes") or 0) + 1
            st.set_data(actor, held, successes=successes)
            if successes >= 2:  # the designation ends after two successful saves during the activation
                st.remove(engine, actor, held, "ENDED")
    held = _far_sided(actor)
    if held is not None and actor.active:
        law = engine.state.actors.get(held.source_actor_id or "")
        if law is not None:
            ctx = st.context(engine, law, st.feature_action(engine, law, FAR_SIDE), [actor], st.numbers(engine, law))
            if not st.save(ctx, actor, "cha"):
                _end_far_side(engine, actor, held, "SAVED")  # the end-of-turn repeat save ends Far-Sided on a success


@effect("near_rewrite")
def rewrite(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, law = ctx.engine, ctx.actor
    law.turn_flags["rewrite_constellation"] = True  # "Once on each of your turns"
    mode = row.get("mode")
    if mode == "move" and ctx.target is not None:
        spots = {c: v for c, v in st.routes(engine, ctx.target, 20, all_creatures=False).items() if c != ctx.target.position}
        path = st.choose_route(engine, law, spots, ctx.intent, checkpoint="REWRITE_MOVE", prompt=f"Move {ctx.target.display_name} 20 feet to where?",
                               name="Rewrite the Constellation", feature=WORLD) if spots else None
        if path is not None:
            needle.step_to(engine, ctx.target, path[-1], WORLD)  # "by conceptual translation"
    elif mode == "exchange":
        members = [c for c in engine.state.actors.values() if c.active and _member(c, law, "near") and c.team_id == law.team_id]
        if len(members) >= 2:
            ids = [c.entity_id for c in members]
            chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "REWRITE_EXCHANGE", law.entity_id), law, "choice:needle.near_far.exchange",
                                ids, labels={c.entity_id: c.display_name for c in members}, preferred=ids[:2], minimum=2, maximum=2, default="all",
                                prompt="Exchange which two Near members?", name="Rewrite the Constellation", feature_id=WORLD)
            pair = [c for c in members if c.entity_id in (chosen or ids[:2])][:2]
            if len(pair) == 2:
                a, b = pair
                pa, pb = a.position, b.position
                a.position = pb
                b.position = pa
                for mover, start, end in ((a, pa, pb), (b, pb, pa)):
                    engine._append_event("MOVEMENT_COMMITTED", WORLD, actor_id=mover.entity_id,
                                         payload={"destination": end.model_dump(mode="json"), "cost_ft": 0, "footprint_step": True,
                                                  "path": [start.model_dump(mode="json"), end.model_dump(mode="json")]})
    elif mode == "far" and ctx.target is not None and ctx.target.active:
        if st.save(ctx, ctx.target, "cha"):
            _join(engine, law, ctx.target, "far", _world(law).source_definition_id if _world(law) is not None else ctx.source)


def _sanctuary_answer(engine: Any, law: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> bool:
    """Make Sanctuary Unreachable (once during the activation, your Reaction): a hostile attack on a Near member."""
    world_state = _world(law)
    if (world_state is None or st.data_of(law, world_state).get("sanctuary_used") or not st.can_react(law) or not _member(defender, law, "near")
            or not _in_world(engine, law, attacker)):
        return False
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "SANCTUARY", defender.entity_id), law, "choice:needle.near_far.sanctuary", ["far"],
                        labels={"far": f"Make Sanctuary Unreachable (once, your Reaction): {defender.display_name} becomes Far from every hostile creature"},
                        prompt=f"{attacker.display_name} strikes at {defender.display_name}.", preferred=["far"] if defender.current_hp <= defender.maximum_hp // 2 else [],
                        allow_decline=True, default="first" if defender.current_hp <= defender.maximum_hp // 2 else "decline",
                        name="Make Sanctuary Unreachable", feature_id=WORLD, target_id=defender.entity_id)
    if not chosen:
        return False
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, law, WORLD, independent=True):
        st.set_data(law, world_state, sanctuary_used=1)
        law.reaction_available = False
        ctx = st.context(engine, law, st.feature_action(engine, law, WORLD), [defender], st.numbers(engine, law))
        expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_start_of_next_turn"}}, defender, condition=True)
        engine._apply_condition(defender, SANCTUARY, WORLD, law.entity_id, expires_on=expires or "START_OF_TARGET_NEXT_TURN",
                                data={"label": "Unreachable Sanctuary: Far from every hostile creature in the field; it cannot attack"})
        others = [c for c in engine.state.actors.values() if c is not defender and c.active and _member(c, law, "near")]
        if others:
            _step_toward(engine, defender, min(others, key=lambda c: engine._distance_actor_to_actor(defender, c)), 20, intent, "Make Sanctuary Unreachable", WORLD)
        return True


# ---------------------------------------------------------------------------------------------------------- gates
def _far_penalty(engine: Any, actor: Any) -> int:
    """How much farther every other creature is for this creature's hostile targeting (Far-Sided 30, Far Constellation 20)."""
    penalty = 30 if _far_sided(actor) is not None else 0
    if any(c.condition_id == CONSTELLATION and (c.data or {}).get("side") == "far" for c in actor.conditions.values()):
        penalty = max(penalty, 20)
    return penalty


@hook("candidate_allowed")
def near_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (action.parameters or {}) if action is not None else {}
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if params.get("near_collapse"):
        return None if _near_targets(engine, actor) else False
    mode = params.get("rewrite_constellation")
    if mode:
        if _world(actor) is None or actor.turn_flags.get("rewrite_constellation"):
            return False
        if mode == "move":
            return None if target is not None and _member(target, actor, "near") else False
        if mode == "exchange":
            return None if sum(1 for c in engine.state.actors.values() if c.active and _member(c, actor, "near") and c.team_id == actor.team_id) >= 2 else False
        return None if target is not None and _in_world(engine, actor, target) and not _member(target, actor, "far") else False
    if action is not None and st.feature_of(action) == NAME and target is not None:
        return None if target.team_id == actor.team_id or _te().bears_mark(target, actor.entity_id, "Resonance") else False  # "willing ... or Resonance Marked"
    if target is None or target.team_id == actor.team_id or action is None:
        return None
    if any(c.condition_id == SANCTUARY for c in target.conditions.values()):
        return False  # "Hostile single-target effects lose it as a legal target"
    if any(c.condition_id == SANCTUARY for c in actor.conditions.values()) and int(params.get("expected_damage") or 0) > 0:
        return False  # "It cannot make attacks or use hostile techniques while protected"
    reach = action.range_ft if action.range_ft is not None else action.reach_ft
    if reach is None:
        return None
    reach = int(reach)
    if any(c.condition_id == "condition:typed.reach_shortened" for c in actor.conditions.values()):
        reach = max(5, reach - 10)
    penalty = _far_penalty(engine, actor)
    if penalty or reach != int(action.range_ft if action.range_ft is not None else action.reach_ft):
        return False if engine._distance_actor_to_actor(actor, target) + penalty > reach else None
    return None
