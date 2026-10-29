"""Unwritten Footprint (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Unwritten Footprint: CL3 Step No Record Keeps, CL6 Knife Between Thoughts, CL10 Steal
the Witness, CL14 No Trace Returns, CL18 Concept of the Missing Footstep). No Spheres 5e or D&D 5.5e counterpart. Ownership rows:
combat/rules/feature_blocks.d/riders_c8.json (Knife Between Thoughts, No Trace Returns: the plug-in answers).

"Unnoticed" at the table: a creature bearing ``condition:typed.unnoticing`` (source: you) does not notice you; you are also unnoticed
while you are Hidden. An Unwritten Trace is the mark "Unwritten Trace".

What runs:
  * Slip the Conclusion (typed, Bonus Action, 60 feet, 1 Resonance; a creature you have not damaged or targeted this turn): Wisdom save;
    failed -- an Unwritten Trace and it does not notice you until the start of your next turn (your damaging or targeting it ends that);
    then a 10-foot move of yours that it cannot punish (asked). Ambush Without Hatred (once a turn): your damage to a creature that did
    not notice you adds 1d6 Psychic (2d6 at CL10, 3d6 at CL18) and removes its Reactions until the start of its next turn.
  * Knife Between Thoughts: Between-Thought Strike (asked, 2 Resonance) before your Mind Spike or weapon attack on a traced creature --
    on a hit or failed save, Ambush Without Hatred applies anyway, it makes no Opportunity Attack against you until the start of your
    next turn, and you may move 10 feet without provoking; the trace is consumed. Misattribute the Blow (Reaction, 2 Resonance, asked):
    a traced creature attacks you or targets you with a single-target save technique -- you move 10 feet (asked), then its Wisdom save:
    failed, Disadvantage on the attack or Advantage on your save (an attack that no longer reaches misses); succeeded, +2 AC or +2 to
    the save; the trace is consumed.
  * Steal the Witness (typed, Action, 60 feet, 5 Resonance, Concentration): Wisdom save; failed -- you are Unwritten to it: it cannot
    target you with attacks or single-target techniques or make Opportunity Attacks against you, it repeats the save at the end of its
    turns, and your attack on it gives it an immediate repeat save first; succeeded -- an Unwritten Trace and no Reactions until the start
    of its next turn. Its allies may use an Action ("Point Out the Unwritten") for a repeat save with Advantage.
  * No Trace Returns: Erase the Last Passage (Reaction, 5 Resonance, asked) when an attack targets you: move up to half your Speed through
    occupied spaces (asked) -- a Grapple or Restraint on you is broken by a Cultivation Check first -- then Afterimage Victim (the attack
    strikes your afterimage: it misses you) or Cut the Acquisition (one mark a lower hostile creature put on you ends) (asked).
  * Concept of the Missing Footstep (typed zone, Bonus Action, 10 Resonance, 40 feet around you, Concentration): when you move, hostile
    creatures in it you choose make a Wisdom save once a turn -- failed, they do not notice you until you damage them or your turn ends;
    either way none of them makes an Opportunity Attack against you during that move. Cut Action From Witness (once a turn, asked, after
    you damage a creature in it): a creature that failed this round gains an Unwritten Trace and loses its Reactions until the start of
    your next turn. "Empty Space Assassination" (once, Action): move up to your Speed without provoking and Mind Spike (maximum dice) or a
    weapon attack on a creature in it that does not notice you -- a failed save or hit adds 6d8 Psychic and no Reactions until the end of
    your next turn; otherwise half the bonus.

Plug-in surface: effects unwritten_slip, unwritten_steal, unwritten_domain, unwritten_assassinate, unwritten_point_out; hooks
before_attack, hit_response, save, after_save_resolved, damage_dealt, technique_start, technique_used, event, turn_start, turn_end,
opportunity_allowed, opportunity_response, candidate_allowed, compile_actions, match_start, additional_actions. Shared helpers used: spirit_traditions
(context/numbers/feature_action/feature_of/pick_creature/routes/choose_route/can_react/save/remove/mind_spike/run_action/data_of/
set_data), end_effect (cultivation_dc, source_cl), rider_movement.step, needle, zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.unwritten_footprint.feature."
STEP = TRADITION + "step_no_record_keeps"
KNIFE = TRADITION + "knife_between_thoughts"
STEAL = TRADITION + "steal_the_witness"
ERASE = TRADITION + "no_trace_returns"
DOMAIN = TRADITION + "concept_of_the_missing_footstep"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
TRACE = "Unwritten Trace"
RESONANCE = "resource:core.resonance"
UNNOTICING = "condition:typed.unnoticing"
UNWRITTEN = "condition:typed.unwritten_to"
POINT_OUT = "system:combat.point_out_the_unwritten"
_KNIFE = "_unwritten_knife"
_MISATTRIBUTE = "_unwritten_misattribute"
_AFTERIMAGE = "_unwritten_afterimage"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _ctx(engine: Any, owner: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, owner, st.feature_action(engine, owner, feature), targets, _numbers(engine, owner), intent)


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    """Whether the creature has the feature: its ownership row, or an action of it."""
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    if any(r.get("feature_id") == feature for r in rows):
        return True
    return any(a.owner_id == actor.entity_id and st.feature_of(a) == feature for a in engine.action_catalog.values())


def traced(creature: Any, owner: Any) -> bool:
    return creature is not None and owner is not None and _te().bears_mark(creature, owner.entity_id, TRACE)


def _consume_trace(engine: Any, creature: Any, owner: Any, source: str) -> None:
    for held in [c for c in creature.conditions.values() if c.condition_id == _te().mark_condition_id(TRACE, owner.entity_id)]:
        st.remove(engine, creature, held, "CONSUMED")


def unnoticed(engine: Any, owner: Any, creature: Any) -> bool:
    """Whether ``creature`` does not notice ``owner`` right now."""
    if any(c.condition_id in (UNNOTICING, UNWRITTEN) and c.source_actor_id == owner.entity_id for c in creature.conditions.values()):
        return True
    return any(c.condition_id == "condition:typed.hidden" for c in owner.conditions.values())


def _notice(engine: Any, owner: Any, creature: Any, why: str) -> None:
    """A direct interaction ends "unnoticed" (Slip the Conclusion, Unrecorded Movement)."""
    for held in [c for c in creature.conditions.values() if c.condition_id == UNNOTICING and c.source_actor_id == owner.entity_id]:
        st.remove(engine, creature, held, why)


def _unnotice(engine: Any, owner: Any, creature: Any, source: str, until: str) -> None:
    _notice(engine, owner, creature, "REPLACED")
    engine._apply_condition(creature, UNNOTICING, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"until": until, "turn": int(owner.turns_started), "label": f"Does not notice {owner.display_name}"})


def _clear_step(engine: Any, walker: Any, feet: int, allowed_id: str | None, *, through: bool = False) -> dict[Any, Any]:
    """Squares within ``feet`` that no hostile creature other than ``allowed_id`` could punish with an Opportunity Attack on the way."""
    from .. import typed_reactions

    threats = [(c, int(typed_reactions.opportunity_reach(engine, c) or 5)) for c in engine.state.actors.values()
               if c.active and c.team_id != walker.team_id and c.reaction_available and c.entity_id != allowed_id]
    out = {}
    for cell, (path, cost) in st.routes(engine, walker, feet, all_creatures=through).items():
        if cell != walker.position and not any(engine.grid.distance_ft(a, foe.position) <= reach < engine.grid.distance_ft(b, foe.position)
                                               for foe, reach in threats for a, b in zip(path, path[1:])):
            out[cell] = (path, cost)
    return out


def _move(engine: Any, walker: Any, spots: dict[Any, Any], intent: Any, checkpoint: str, prompt: str, feature: str) -> bool:
    path = st.choose_route(engine, walker, spots, intent, checkpoint=checkpoint, prompt=prompt, name=prompt.split(":")[0], feature=feature) if spots else None
    if path is None:
        return False
    from .rider_movement import step

    step(engine, walker, list(path), feature)
    return True


# ---------------------------------------------------------------------------------------------------------- Step No Record Keeps
@effect("unwritten_slip")
def slip(ctx: Any, row: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    if st.save(ctx, target, "wis"):
        _te().run_effects(ctx, [{"type": "mark", "mark": TRACE, "applies_to": "target", "duration": {"kind": "until_removed"}, "evidence": "Place an Unwritten Trace on it."}])
        _unnotice(engine, owner, target, STEP, "start_of_your_next_turn")
    else:
        note(engine, STEP, owner, f"{target.display_name} feels its attribution blur and learns your direction (the GM tells it).", (target,))
    _move(engine, owner, _clear_step(engine, owner, 10, target.entity_id), ctx.intent, "SLIP_STEP",
          "Slip the Conclusion: move 10 feet without provoking it?", STEP)


@hook("damage_dealt")
def ambush_without_hatred(ctx: Any, target: Any, amount: int) -> None:
    """"Once on each of your turns when you deal damage to a creature that had not noticed you immediately before the attack or technique,
    add 1d6 Psychic damage and remove its Reactions until the start of its next turn\""""
    engine, owner = ctx.engine, ctx.actor
    if amount <= 0 or target is None or target.team_id == owner.team_id or not _owns(engine, owner, STEP):
        return
    knifed = engine.__dict__.get(_KNIFE) or {}
    forced = knifed.get("target") == target.entity_id and knifed.get("owner") == owner.entity_id
    before = owner.turn_flags.get("unnoticed_at_start") or {}
    was_unnoticed = forced or bool(before.get(target.entity_id))
    if was_unnoticed and not owner.turn_flags.get("ambush_without_hatred") and engine.state.current_actor_id == owner.entity_id:
        owner.turn_flags["ambush_without_hatred"] = True
        cl = int(_numbers(engine, owner).get("cl") or 1)
        dice = 3 if cl >= 18 else 2 if cl >= 10 else 1
        _te().run_effects(st.context(engine, owner, ctx.action, [target], ctx.numbers, ctx.intent),
                          [{"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 6}, "damage_types": ["psychic"], "evidence": f"add {dice}d6 Psychic damage"},
                           {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"}, "evidence": "remove its Reactions"}])
    _notice(engine, owner, target, "DAMAGED")  # "unless you directly interact with it" / "Until you next deal damage"


@hook("technique_start")
def remember_who_noticed(engine: Any, actor: Any, action: Any) -> None:
    """"had not noticed you immediately before the attack or technique": recorded as the technique begins."""
    actor.turn_flags["unnoticed_at_start"] = {c.entity_id: True for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and unnoticed(engine, actor, c)}
    _between_thought(engine, actor, action)
    return None


# ---------------------------------------------------------------------------------------------------------- Knife Between Thoughts
def _between_thought(engine: Any, owner: Any, action: Any) -> None:
    """Between-Thought Strike: "you may spend 2 Resonance before the roll\""""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _KNIFE)
    from . import needle

    engine.__dict__.pop(_KNIFE, None)
    if not _owns(engine, owner, KNIFE) or owner.resources.get(RESONANCE, 0) < 2 or action is None:
        return
    feature = st.feature_of(action)
    weapon = bool(((action.parameters or {}).get("typed") or {}).get("weapon"))
    if feature != MIND_SPIKE and not weapon:
        return
    intent = engine._active_intent
    target = engine.state.actors.get(next(iter(getattr(intent, "target_ids", None) or ()), "")) if intent is not None else None
    if target is None or not traced(target, owner):
        return
    if not needle.ask(engine, intent, needle.checkpoint_id(engine, "BETWEEN_THOUGHT", target.entity_id), owner, "choice:needle.unwritten.between_thought",
                      ["strike"], labels={"strike": "Between-Thought Strike (2 Resonance)"}, preferred=["strike"], allow_decline=True,
                      prompt=f"{target.display_name} bears your Unwritten Trace.", name="Knife Between Thoughts", feature_id=KNIFE, target_id=target.entity_id):
        return
    engine._spend_resource(owner, RESONANCE, 2, KNIFE)
    engine.__dict__[_KNIFE] = {"owner": owner.entity_id, "target": target.entity_id, "landed": False}


def _knife_landed(engine: Any, owner: Any, target: Any, intent: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _KNIFE)
    knifed = engine.__dict__.get(_KNIFE) or {}
    if knifed.get("owner") != owner.entity_id or knifed.get("target") != target.entity_id or knifed.get("landed"):
        return
    knifed["landed"] = True
    engine._apply_condition(target, "condition:typed.cannot_punish_the_unwritten", KNIFE, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": f"Cannot find {owner.display_name}: no Opportunity Attack or Reaction at them"})
    _move(engine, owner, _clear_step(engine, owner, 10, None), intent, "BETWEEN_THOUGHT_STEP", "Between-Thought Strike: move 10 feet without provoking?", KNIFE)


@hook("reaction_allowed")
def knife_reactions(engine: Any, reactor: Any, other: Any) -> bool | None:
    """Between-Thought Strike forbids every Reaction aimed at this owner."""
    if other is None or reactor is None:
        return None
    return False if any(c.condition_id == "condition:typed.cannot_punish_the_unwritten"
                        and c.source_actor_id == other.entity_id for c in reactor.conditions.values()) else None


@hook("after_save_resolved")
def unwritten_after_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, _MISATTRIBUTE)
    engine, owner = ctx.engine, ctx.actor
    if subject is None or owner is None:
        return
    if failed:
        _knife_landed(engine, owner, subject, ctx.intent)
    held = (engine.__dict__.get(_MISATTRIBUTE) or {}).get(("save", ctx.source, subject.entity_id))
    if held is not None:
        engine.__dict__[_MISATTRIBUTE].pop(("save", ctx.source, subject.entity_id), None)


@hook("technique_used")
def knife_resolved(ctx: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, _KNIFE)
    knifed = ctx.engine.__dict__.pop(_KNIFE, None)
    if knifed and knifed.get("owner") == ctx.actor.entity_id:
        target = ctx.engine.state.actors.get(knifed.get("target") or "")
        if target is not None:
            _consume_trace(ctx.engine, target, ctx.actor, KNIFE)  # "Whether the attack succeeds or fails, consume the target's Unwritten Trace"


@hook("before_attack")
def unwritten_before_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    from . import needle

    if attacker is None or defender is None or attacker.team_id == defender.team_id:
        return None
    # Steal the Witness: a direct attack on the Unwritten target gives it an immediate repeat save.
    for held in [c for c in defender.conditions.values() if c.condition_id == UNWRITTEN and c.source_actor_id == attacker.entity_id]:
        if not st.save(_ctx(engine, attacker, STEAL, [defender], intent), defender, "wis"):
            st.remove(engine, defender, held, "NOTICED")
    # Knife Between Thoughts: Misattribute the Blow; No Trace Returns: Erase the Last Passage.
    result = _misattribute(engine, attacker, defender, intent, "attack")
    if result is not None:
        return result
    return _erase(engine, attacker, defender, intent, context)


def _misattribute(engine: Any, source: Any, owner: Any, intent: Any, kind: str) -> dict[str, Any] | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _AFTERIMAGE)
    from . import needle

    if not _owns(engine, owner, KNIFE) or not traced(source, owner) or not st.can_react(owner) or owner.resources.get(RESONANCE, 0) < 2:
        return None
    if not needle.ask(engine, intent, needle.checkpoint_id(engine, "MISATTRIBUTE", source.entity_id), owner, "choice:needle.unwritten.misattribute",
                      ["misattribute"], labels={"misattribute": f"Misattribute the Blow (Reaction, 2 Resonance): move 10 feet; {source.display_name} makes a Wisdom save"},
                      preferred=["misattribute"], allow_decline=True, prompt=f"{source.display_name} targets you.", name="Knife Between Thoughts",
                      feature_id=KNIFE, target_id=source.entity_id):
        return None
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, KNIFE, independent=True):
        owner.reaction_available = False
        engine._spend_resource(owner, RESONANCE, 2, KNIFE)
        engine._append_event("REACTION_RESOLVED", KNIFE, actor_id=owner.entity_id, target_ids=(source.entity_id,),
                             payload={"checkpoint": "TARGETED", "reaction_name": "Misattribute the Blow"})
        spots = {c: v for c, v in st.routes(engine, owner, 10).items() if c != owner.position}
        _move(engine, owner, spots, intent, "MISATTRIBUTE_MOVE", "Misattribute the Blow: move 10 feet to a legal space?", KNIFE)
        failed = st.save(_ctx(engine, owner, KNIFE, [source], intent), source, "wis")
        _consume_trace(engine, source, owner, KNIFE)  # "Misattribute the Blow consumes the trace."
        if kind == "attack":
            if failed:
                return {"mode": "DISADVANTAGE"}
            engine.__dict__[_AFTERIMAGE] = {"attacker": source.entity_id, "defender": owner.entity_id, "plus_two": True}
            return {}
        return {"bonus": 0, "modes": ["ADVANTAGE"]} if failed else {"bonus": 2}


@hook("save")
def unwritten_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Misattribute the Blow against "a single-target hostile technique"; Steal the Witness's repeat save when you target it."""
    engine, source = ctx.engine, ctx.actor
    if subject is None or source is None or source.team_id == subject.team_id:
        return None
    for held in [c for c in subject.conditions.values() if c.condition_id == UNWRITTEN and c.source_actor_id == source.entity_id]:
        if not st.save(_ctx(engine, source, STEAL, [subject], ctx.intent), subject, "wis"):
            st.remove(engine, subject, held, "NOTICED")
    if len(ctx.targets or ()) > 1 or engine.__dict__.get("_unwritten_resolving"):
        return None
    engine.__dict__["_unwritten_resolving"] = True
    try:
        return _misattribute(engine, source, subject, ctx.intent, "save")
    finally:
        engine.__dict__.pop("_unwritten_resolving", None)


@hook("hit_response")
def unwritten_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _AFTERIMAGE)
    held = engine.__dict__.get(_AFTERIMAGE)
    if not isinstance(held, dict) or held.get("attacker") != getattr(attacker, "entity_id", None) or held.get("defender") != target.entity_id:
        return None
    engine.__dict__.pop(_AFTERIMAGE, None)
    if held.get("plus_two"):
        return None if natural == 20 or total >= effective_ac + 2 else (effective_ac + 2, False)  # "You gain +2 AC against the attack"
    note(engine, ERASE, target, f"Afterimage Victim: {attacker.display_name}'s attack strikes an afterimage where {target.display_name} stood.", (attacker,))
    from ..attack_outcomes import unconditional_miss

    return unconditional_miss()


@hook("event")
def unwritten_attack_rolled(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _AFTERIMAGE)
    preserve_pending(engine, _KNIFE)
    if event_type == "ATTACK_ROLLED" and not (kwargs.get("payload") or {}).get("provisional_hit"):
        held = engine.__dict__.get(_AFTERIMAGE)
        if isinstance(held, dict) and held.get("attacker") == kwargs.get("actor_id"):
            engine.__dict__.pop(_AFTERIMAGE, None)
    if event_type == "DAMAGE_COMMITTED":
        knifed = engine.__dict__.get(_KNIFE) or {}
        owner = engine.state.actors.get(knifed.get("owner") or "")
        if owner is not None and kwargs.get("actor_id") == owner.entity_id and knifed.get("target") in (kwargs.get("target_ids") or ()):
            _knife_landed(engine, owner, engine.state.actors[knifed["target"]], engine._active_intent)


# ---------------------------------------------------------------------------------------------------------- No Trace Returns
def _erase(engine: Any, attacker: Any, owner: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Erase the Last Passage (Reaction, 5 Resonance): "an attack targets you\""""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _AFTERIMAGE)
    from . import needle
    from .end_effect import cultivation_dc, source_cl

    if not _owns(engine, owner, ERASE) or not st.can_react(owner) or owner.resources.get(RESONANCE, 0) < 5:
        return None
    if not needle.ask(engine, intent, needle.checkpoint_id(engine, "ERASE_PASSAGE", attacker.entity_id), owner, "choice:needle.unwritten.erase",
                      ["erase"], labels={"erase": "Erase the Last Passage (Reaction, 5 Resonance): move up to half your Speed by spiritual step"},
                      preferred=["erase"], allow_decline=True, prompt=f"{attacker.display_name} attacks you.", name="No Trace Returns", feature_id=ERASE,
                      target_id=attacker.entity_id):
        return None
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, ERASE, independent=True):
        owner.reaction_available = False
        engine._spend_resource(owner, RESONANCE, 5, ERASE)
        engine._append_event("REACTION_RESOLVED", ERASE, actor_id=owner.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Erase the Last Passage"})
        held_fast = [c for c in owner.conditions.values() if str(c.condition_id).rsplit(".", 1)[-1] in ("grappled", "restrained")]
        free = True
        for hold in held_fast:  # Ghost Through the Hold: "make a Cultivation Check against the restraint's escape DC"
            grappler = engine.state.actors.get(hold.source_actor_id or "")
            dc = cultivation_dc(engine, grappler) if grappler is not None else 10
            numbers = _numbers(engine, owner)
            roll = engine.roll_check(
                modifier=int(numbers.get('pb') or 2) + int(numbers.get('key_mod') or 0),
                actor_id=owner.entity_id,
                reason=f'CHECK:{ERASE}',
            )
            engine._record_roll(roll)
            engine._append_event("CHECK_ROLLED", ERASE, actor_id=owner.entity_id, payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc,
                                                                                          "check": "Cultivation Check (Ghost Through the Hold)"})
            if roll.total >= dc:
                st.remove(engine, owner, hold, "ESCAPED")
            else:
                free = False
        if free:
            half = max(5, engine._effective_speed(owner) // 2)
            spots = {c: v for c, v in st.routes(engine, owner, half, all_creatures=True).items() if c != owner.position}
            _move(engine, owner, spots, intent, "ERASE_MOVE", "Erase the Last Passage: where does the spiritual step end?", ERASE)
        ctx = _ctx(engine, owner, ERASE, [owner], intent)
        marks = [c for c in owner.conditions.values() if c.condition_id.startswith(_te().MARK_PREFIX) and c.source_actor_id
                 and (lambda s: s is not None and s.team_id != owner.team_id)(engine.state.actors.get(c.source_actor_id)) and source_cl(ctx, c) < int(_numbers(engine, owner).get("cl") or 1)]
        options = {"afterimage": f"Afterimage Victim: {attacker.display_name}'s attack strikes an afterimage",
                   **({"cut": f"Cut the Acquisition: end the {str(marks[0].condition_id).split('.')[-2].replace('_', ' ')} mark on you"} if marks else {})}
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "ERASE_RESULT", owner.entity_id), owner, "choice:needle.unwritten.erase_result",
                            list(options), labels=options, preferred=["afterimage"], prompt="Erase the Last Passage: choose one result.", name="No Trace Returns",
                            feature_id=ERASE)
        if (chosen or ["afterimage"])[0] == "cut" and marks:
            st.remove(engine, owner, marks[0], "CUT")
            return {}
        engine.__dict__[_AFTERIMAGE] = {"attacker": attacker.entity_id, "defender": owner.entity_id}
        return {}


# ---------------------------------------------------------------------------------------------------------- Steal the Witness
@effect("unwritten_steal")
def steal(ctx: Any, row: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    if st.save(ctx, target, "wis"):
        engine._apply_condition(target, UNWRITTEN, ctx.source, owner.entity_id, expires_on="CONCENTRATION_END" if owner.concentration is not None else "UNTIL_REMOVED",
                                data={"label": f"{owner.display_name} is Unwritten to it: it cannot target them"})
        return
    _te().run_effects(ctx, [{"type": "mark", "mark": TRACE, "applies_to": "target", "duration": {"kind": "until_removed"}, "evidence": "Place an Unwritten Trace on it"},
                            {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"}, "evidence": "remove its Reactions until the start of its next turn"}])


def _unwritten_owner(engine: Any, creature: Any) -> Any:
    held = next((c for c in creature.conditions.values() if c.condition_id == UNWRITTEN), None)
    owner = engine.state.actors.get(held.source_actor_id or "") if held is not None else None
    if held is not None and (owner is None or owner.concentration is None):
        st.remove(engine, creature, held, "CONCENTRATION_ENDED")
        return None
    return owner


@hook("turn_end")
def unwritten_turn_end(engine: Any, actor: Any) -> None:
    owner = _unwritten_owner(engine, actor)
    if owner is not None and not st.save(_ctx(engine, owner, STEAL, [actor]), actor, "wis"):
        for held in [c for c in actor.conditions.values() if c.condition_id == UNWRITTEN]:
            st.remove(engine, actor, held, "SAVED")  # "At the end of each of its turns, it repeats the save, ending the effect on a success."
    # "Until you next ... end your turn without cover or concealment": Unrecorded Movement's unnoticing ends with your turn.
    for creature in engine.state.actors.values():
        for held in [c for c in creature.conditions.values() if c.condition_id == UNNOTICING and c.source_actor_id == actor.entity_id
                     and (c.data or {}).get("until") == "end_of_your_turn" and not any(x.condition_id == "condition:typed.hidden" for x in actor.conditions.values())]:
            st.remove(engine, creature, held, "TURN_ENDED")


@hook("turn_start")
def unwritten_turn_start(engine: Any, actor: Any) -> None:
    for creature in engine.state.actors.values():
        for held in [c for c in creature.conditions.values() if c.condition_id == UNNOTICING and c.source_actor_id == actor.entity_id
                     and (c.data or {}).get("until") == "start_of_your_next_turn"]:
            st.remove(engine, creature, held, "EXPIRED")  # Slip the Conclusion: "Until the start of your next turn"


@hook("opportunity_allowed")
def unwritten_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    if reactor is None or mover is None:
        return None
    if any(c.condition_id in (UNWRITTEN, UNNOTICING, "condition:typed.cannot_punish_the_unwritten") and c.source_actor_id == mover.entity_id for c in reactor.conditions.values()):
        return False
    # Observe an already chosen witness; hypothetical routes never choose or save.
    zone = domain_of(engine, mover)
    if zone is not None and reactor.team_id != mover.team_id and engine._footprint_intersects(reactor, zone.affected_cells):
        return False if mover.turn_flags.get(f"unrecorded:{reactor.entity_id}") == "chosen" else None
    return None


@hook("opportunity_response")
def _unrecorded_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """Unrecorded Movement: a chosen hostile creature in the Domain makes its save as you move; either way it takes no Opportunity Attack
    against you during that movement."""
    if reactor is None or mover is None:
        return None
    zone = domain_of(engine, mover)
    if zone is None or reactor.team_id == mover.team_id or not engine._footprint_intersects(reactor, zone.affected_cells):
        return None
    if _witness(engine, mover, reactor, engine._active_intent):
        return False
    return None


# ---------------------------------------------------------------------------------------------------------- Concept of the Missing Footstep
def domain_of(engine: Any, owner: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == DOMAIN), None)


def _witness(engine: Any, owner: Any, creature: Any, intent: Any) -> bool:
    """"Each chosen creature makes a Wisdom saving throw once per turn" (asked whether to choose it)."""
    from . import needle

    key = f"unrecorded:{creature.entity_id}"
    if owner.turn_flags.get(key):
        return owner.turn_flags.get(key) == "chosen"
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "UNRECORDED", creature.entity_id), owner, "choice:needle.unwritten.unrecorded",
                        ["choose"], labels={"choose": f"Unrecorded Movement: {creature.display_name} makes a Wisdom save; no Opportunity Attacks against this movement"}, preferred=["choose"], allow_decline=True,
                        prompt=f"Concept of the Missing Footstep — Unrecorded Movement: as {owner.display_name} moves, choose {creature.display_name}? No cost; a failed Wisdom save leaves you unnoticed until you damage or touch it, or end your turn without cover or concealment.",
                        name="Concept of the Missing Footstep", feature_id=DOMAIN, target_id=creature.entity_id)
    owner.turn_flags[key] = "chosen" if chosen else "declined"
    if not chosen:
        return False
    if st.save(_ctx(engine, owner, DOMAIN, [creature], intent), creature, "wis"):
        _unnotice(engine, owner, creature, DOMAIN, "end_of_your_turn")
        creature.turn_flags["failed_footstep_round_"] = engine.state.round_number
    return True


@hook("event")
def unrecorded_movement(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if owner is None or engine.state.current_actor_id != owner.entity_id or int(payload.get("planned_cost_ft") or payload.get("cost_ft") or 0) < 5:
        return
    zone = domain_of(engine, owner)
    if zone is None:
        return
    for creature in sorted(engine.state.actors.values(), key=lambda c: c.entity_id):
        if creature.active and creature.team_id != owner.team_id and engine._footprint_intersects(creature, zone.affected_cells):
            _witness(engine, owner, creature, engine._active_intent)


@hook("damage_dealt")
def cut_action_from_witness(ctx: Any, target: Any, amount: int) -> None:
    """Cut Action From Witness: "Once on each of your turns after you damage a creature ... choose one Witness that failed a save against the
    Domain this round" -- it gains an Unwritten Trace and cannot take Reactions until the start of your next turn (the memory choices are the GM's)."""
    engine, owner = ctx.engine, ctx.actor
    zone = domain_of(engine, owner)
    if zone is None or amount <= 0 or owner.turn_flags.get("cut_action") or engine.state.current_actor_id != owner.entity_id:
        return
    witnesses = [c for c in engine.state.actors.values() if c.active and c.turn_flags.get("failed_footstep_round_") == engine.state.round_number]
    if not witnesses:
        return
    witness = st.pick_creature(engine, ctx.intent, owner, witnesses, checkpoint="CUT_ACTION", choice_id="choice:needle.unwritten.cut_action",
                               prompt="Cut Action From Witness: which Witness gains an Unwritten Trace and loses its Reactions?", name="Concept of the Missing Footstep",
                               feature_id=DOMAIN, allow_decline=True)
    if witness is None:
        return
    owner.turn_flags["cut_action"] = True
    _te().run_effects(_ctx(engine, owner, DOMAIN, [witness], ctx.intent),
                      [{"type": "mark", "mark": TRACE, "applies_to": "target", "duration": {"kind": "until_removed"}, "evidence": "it gains an Unwritten Trace"},
                       {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "cannot take Reactions until the start of your next turn"}])


@effect("unwritten_assassinate")
def assassinate(ctx: Any, row: dict[str, Any]) -> None:
    """Empty Space Assassination: "Move up to your Speed by spiritual step and make one of the following against it\""""
    from . import needle

    engine, owner = ctx.engine, ctx.actor
    zone = domain_of(engine, owner)
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if zone is None or target is None:
        return
    owner.turn_flags["assassination_round_"] = True  # "Once during the activation"
    spots = {c: v for c, v in st.routes(engine, owner, engine._effective_speed(owner)).items() if c != owner.position}
    _move(engine, owner, spots, ctx.intent, "ASSASSINATION_STEP", "Empty Space Assassination: step where?", DOMAIN)
    weapon = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id and ((a.parameters or {}).get("typed") or {}).get("weapon")
                   and "#" not in a.source_definition_id and engine._target_in_range(owner, target, a)), None)
    options = {"spike": "Mind Spike with maximum damage dice", **({"weapon": f"Strike with {weapon.display_name}"} if weapon is not None else {})}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "ASSASSINATION", target.entity_id), owner, "choice:needle.unwritten.assassination",
                        list(options), labels=options, preferred=["spike"], prompt="Empty Space Assassination", name="Concept of the Missing Footstep", feature_id=DOMAIN)
    before = len(engine.events)
    if (chosen or ["spike"])[0] == "weapon" and weapon is not None:
        st.run_action(engine, owner, weapon, target, ctx.intent)
    else:
        st.mind_spike(engine, owner, target, ctx.intent, maximize=True)
    landed = any(e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ()) and e.actor_id == owner.entity_id for e in engine.events[before:])
    rows = [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 8}, "damage_types": ["psychic"], "evidence": "add 6d8 Psychic damage"}]
    if landed:
        _te().run_effects(st.context(engine, owner, ctx.action, [target], ctx.numbers, ctx.intent),
                          [*rows, {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                   "evidence": "it loses Reactions until the end of your next turn"}])
    else:
        from ..gate2_runtime_models import DiceSpec

        roll = engine.roller.roll(DiceSpec(count=6, sides=8, modifier=0), actor_id=owner.entity_id, reason=f"DAMAGE:{DOMAIN}")
        engine._record_roll(roll)
        engine._commit_damage(target, int(roll.total) // 2, "PSYCHIC", ctx.source, owner.entity_id, ctx.intent, reaction_depth=1)  # "it takes half the bonus damage"
        _notice(engine, owner, target, "NOTICED")


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("match_start")
def point_out_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[POINT_OUT] = ActionDefinition(
        source_definition_id=POINT_OUT, display_name="Point Out the Unwritten", owner_id="*", economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="SELF", parameters={"typed": {"effects": [{"type": "unwritten_point_out"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                                        "expected_damage": 0, "unwritten_point_out": True,
                                        "description": "Steal the Witness counterplay: point the Unwritten one out to an ally within 30 feet that cannot find them; it repeats "
                                                       "its Wisdom save with Advantage."})


def _blinded_allies(engine: Any, actor: Any) -> list[Any]:
    return [c for c in engine.state.actors.values() if c.active and c is not actor and c.team_id == actor.team_id and engine._distance_actor_to_actor(actor, c) <= 30
            and _unwritten_owner(engine, c) is not None]


@hook("additional_actions")
def point_out_offered(engine: Any, actor: Any) -> list[str]:
    return [POINT_OUT] if _blinded_allies(engine, actor) else []


@effect("unwritten_point_out")
def point_out(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    for ally in _blinded_allies(engine, actor):
        owner = _unwritten_owner(engine, ally)
        if owner is None:
            continue
        engine._apply_condition(ally, "condition:typed.save_against", POINT_OUT, actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                data={"rule": {"save_against": {"mode": "ADVANTAGE", "abilities": ["WIS"], "next": True}}, "label": "Pointed out: Advantage on the repeat save"})
        if not st.save(_ctx(engine, owner, STEAL, [ally], ctx.intent), ally, "wis"):
            for held in [c for c in ally.conditions.values() if c.condition_id == UNWRITTEN]:
                st.remove(engine, ally, held, "POINTED_OUT")
        return


@hook("compile_actions")
def assassination_button(info: dict[str, Any]) -> list[Any] | None:
    if DOMAIN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.unwritten.assassination", display_name="Empty Space Assassination",
                             owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=120,
                             parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": DOMAIN + ":assassination",
                                                   "effects": [{"type": "unwritten_assassinate", "applies_to": "target", "harmful": True}]},
                                         "expected_damage": 0, "unwritten_assassination": True,
                                         "description": "Concept of the Missing Footstep (once): step up to your Speed without provoking and Mind Spike (maximum dice) or a "
                                                        "weapon attack on a creature in the Domain that does not notice you; a hit or failed save adds 6d8 Psychic."})]


@hook("candidate_allowed")
def unwritten_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    targets = tuple(getattr(candidate, "target_ids", None) or ())
    # Unwritten to it: "it cannot voluntarily target you with attacks or single-target techniques"
    for held in [c for c in actor.conditions.values() if c.condition_id == UNWRITTEN]:
        if held.source_actor_id in targets and len(targets) == 1 and _unwritten_owner(engine, actor) is not None:
            return False
    if action is None:
        return None
    target = engine.state.actors.get(next(iter(targets), ""))
    if (action.parameters or {}).get("unwritten_assassination"):
        zone = domain_of(engine, actor)
        return None if (zone is not None and not actor.turn_flags.get("assassination_round_") and target is not None
                        and engine._footprint_intersects(target, zone.affected_cells) and unnoticed(engine, actor, target)) else False
    if st.feature_of(action) == STEP and target is not None and target.team_id != actor.team_id:
        # Slip the Conclusion: "a creature ... that you have not directly damaged, touched, or addressed since the start of your current turn"
        start = int(actor.turn_flags.get("turn_events_start") or 0)
        touched = any(e.actor_id == actor.entity_id and target.entity_id in (e.target_ids or ()) and e.event_type in ("DAMAGE_COMMITTED", "INTENT_ACCEPTED")
                      for e in engine.events[start:])
        return False if touched else None
    return None


@hook("turn_start")
def turn_marker(engine: Any, actor: Any) -> None:
    if not _owns(engine, actor, STEP):
        return
    actor.turn_flags["turn_events_start"] = len(engine.events)
