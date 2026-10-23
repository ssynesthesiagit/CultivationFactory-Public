"""Equal Measure Scripture (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "32. Equal Measure Scripture": Measures, CL3 Receive and Return, CL6 Exact
Counterweight, CL10 Threefold Recompense, CL14 The Scales Do Not Tremble, CL18 Court of Equal Heaven). No Spheres 5e or D&D 5.5e
counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json; every hook returns early
without them.

Measures (tradition text): three pools on the sheet, Impact / Motion / Intent (resource:named.measure_*), one of each, for the fight
(not Resonance).

What runs:
  * Receiving a Measure (with Receive and Return): once per round, after a hostile creature's Action or Bonus Action has fully
    resolved, you gain one Measure it qualified for, if it affected you or a willing creature bearing your Resonance Mark within
    30 feet: Impact -- it lost Hit Points equal to at least your Proficiency Bonus; Motion -- it was moved against its will, knocked
    Prone, Grappled or Restrained; Intent -- it failed an Intelligence, Wisdom or Charisma save, or was Charmed or Frightened. Several:
    you choose (asked; the AI takes the first you lack).
  * Measured Return: once on each of your turns, when your Mind Spike (on a failed save), weapon attack or unarmed strike damages a
    hostile creature, spend one Measure (asked): Impact +1d8 Psychic or Force and Temporary HP = Wisdom + PB; Motion -- move 10
    feet without provoking, or its Strength-or-Wisdom save (its better one) or move it 10 feet (5 on a success); Intent -- Resonance
    Mark until the end of your next turn and your chosen Spiritual Pressure.
  * Exact Counterweight (Reaction, 2 Resonance and the matching Measure; you or a willing marked ally within 30 feet; asked):
    Impact -- a hostile creature's damage packet is reduced by 3d8 + Wisdom; reduced to 0, the source (within 60 feet) takes
    Wisdom + PB Psychic and is Resonance Marked until the end of your next turn. Motion -- a hostile typed push or pull is cut by up
    to 20 feet, or a hostile typed Prone is prevented; either way the protected creature may then move 5 feet without provoking.
    Intent -- after seeing the d20 of a failed Intelligence, Wisdom or Charisma save against a hostile creature, add 1d6; turned into
    a success, the source gets your chosen Spiritual Pressure.
  * The Scales Do Not Tremble: Convert the Measure (Bonus Action, 1 Resonance, once per turn: one Measure becomes a kind you lack).
    Counterweight Becomes Counterstrike (once per round): when the counterweight fully succeeds (damage to 0, all movement or the
    Prone prevented, a failure turned into a success), one Martial Strike against the source as part of the Reaction (asked) -- a
    weapon attack in reach or Mind Spike with one damage die fewer.
  * Threefold Recompense (Action, 5 Resonance): a creature bearing your Resonance Mark; spend one to three different Measures
    (asked), then a Martial Strike (Mind Spike or a weapon attack in reach). Hit or failed save: + (2 + Measures)d8 Psychic or Force,
    and each spent Measure's rider -- Motion: its Strength-or-Wisdom save or you move it 15 feet; Intent: two different Spiritual
    Pressure effects. A successful Mind Spike save halves the added dice with Mind Spike's damage and gives no rider.
  * Court of Equal Heaven (Action, 10 Resonance, Concentration, 40-foot aura that moves with you): the allies you choose (asked;
    the AI chooses every ally). A hostile creature in the Domain gets one Debt (Impact / Motion / Intent, one of each; the first time
    each round) when one of its Actions or Bonus Actions does that kind of harm to a chosen ally in the Domain; Debts end when it
    leaves the Domain or the Domain ends. Any Hand May Answer: once per turn, when a chosen ally's typed technique damages an
    indebted creature, that ally may discharge one Debt (asked): Impact +3d8 Psychic or Force; Motion -- move 15 feet without
    provoking or its Strength-or-Wisdom save or be moved 15 feet (5 on a success); Intent -- your chosen Spiritual Pressure and the
    ally has Advantage on its next Intelligence, Wisdom or Charisma save before the start of its next turn. Nothing Without Answer:
    once per round Exact Counterweight may discharge the source's matching Debt instead of a Measure. Perfect Recompense: once per
    Court, "Threefold Recompense (Perfect Recompense)" costs no Resonance against a creature in the Domain and may discharge its
    Debts as Measures; with all three discharged and a hit or failed save, the target cannot take Reactions, has Speed 0 and has
    Disadvantage on its next Intelligence, Wisdom or Charisma save until the start of your next turn.

Plug-in surface: effects measure_convert, measure_recompense, measure_court; hooks compile_resources, compile_actions,
candidate_allowed, action_completed, damage_dealt, incoming_damage, forced_distance, condition_attempt, event; a d20_rewrite Rule
(equal_measure_intent_counterweight). Shared helpers used: spirit_traditions (row/context/numbers/feature_action/routes/choose_route/
pick_creature/can_react/action_named/run_action/mind_spike/save/remove), needle.ask, rider_movement.step, zones.typed_zones,
d20_rewrite (Rule/register/pool costs), typed_executor (Context/run_effects/bears_mark/mark_condition_id).
"""

from __future__ import annotations

from ..paid_relocation import activation

import copy
from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.equal_measure_scripture.feature."
RECEIVE = TRADITION + "receive_and_return"
COUNTER = TRADITION + "exact_counterweight"
RECOMPENSE = TRADITION + "threefold_recompense"
SCALES = TRADITION + "the_scales_do_not_tremble"
COURT = TRADITION + "court_of_equal_heaven"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
KINDS = ("impact", "motion", "intent")
LABEL = {"impact": "Impact", "motion": "Motion", "intent": "Intent"}
POOL = {kind: f"resource:named.measure_{kind}" for kind in KINDS}
DEBT = {kind: f"condition:typed.equal_court_debt_{kind}" for kind in KINDS}
COURT_STATE = "condition:typed.equal_court"
RESONANCE = "resource:core.resonance"
MENTAL = ("INT", "WIS", "CHA")
MOTION_CONDITIONS = ("prone", "grappled", "restrained")
INTENT_CONDITIONS = ("charmed", "frightened")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def held(actor: Any, kind: str) -> bool:
    return int(actor.resources.get(POOL[kind], 0) or 0) >= 1


def _gain(engine: Any, actor: Any, kind: str, source: str) -> None:
    engine._gain_resource(actor, POOL[kind], 1, source)


def _spend(engine: Any, actor: Any, kind: str, source: str) -> None:
    engine._spend_resource(actor, POOL[kind], 1, source)


@hook("compile_resources")
def measures(info: dict[str, Any]) -> list[Any] | None:
    if RECEIVE not in (info.get("owned_ids") or []):
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=POOL[kind], initial=0, maximum=1) for kind in KINDS]  # "one Measure of each kind"


# ------------------------------------------------------------------------------------------------ what an activation did
def _activation(engine: Any, actor: Any) -> list[Any]:
    """The events of ``actor``'s activation that just completed (from its INTENT_ACCEPTED)."""
    for index in range(len(engine.events) - 1, -1, -1):
        event = engine.events[index]
        if event.event_type == "INTENT_ACCEPTED" and event.actor_id == actor.entity_id:
            return engine.events[index:]
    return []


def _condition_name(condition_id: str) -> str:
    return str(condition_id or "").rsplit(".", 1)[-1].lower()


def qualified(engine: Any, source: Any, subject: Any, events: list[Any], threshold: int) -> list[str]:
    """Which kinds of hostile consequence ``source``'s activation (``events``) gave ``subject`` (the tradition's Measure tests)."""
    kinds = []
    lost = sum(int((e.payload or {}).get("hp_damage") or 0) for e in events
               if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == source.entity_id and subject.entity_id in (e.target_ids or ()))
    if lost and lost >= threshold:  # "lose Hit Points equal to at least your Proficiency Bonus"
        kinds.append("impact")
    for event in events:
        payload = event.payload or {}
        if subject.entity_id not in (event.target_ids or ()) and event.actor_id != subject.entity_id:
            continue
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == subject.entity_id and payload.get("forced") \
                and not payload.get("dragged_by") and len(payload.get("path") or []) > 1:
            kinds.append("motion")
        elif event.event_type == "CONDITION_APPLIED" and event.actor_id == source.entity_id and subject.entity_id in event.target_ids:
            name = _condition_name(payload.get("condition_id"))
            if name in MOTION_CONDITIONS:
                kinds.append("motion")
            elif name in INTENT_CONDITIONS:
                kinds.append("intent")
        elif event.event_type == "SAVE_ROLLED" and event.actor_id == subject.entity_id and payload.get("success") is False \
                and str(payload.get("reason") or "").rsplit(":", 1)[-1].upper() in MENTAL:
            kinds.append("intent")
    return list(dict.fromkeys(kinds))


def _protected(engine: Any, keeper: Any) -> list[Any]:
    """You and each willing creature bearing your Resonance Mark within 30 feet."""
    out = [keeper]
    for other in engine.state.actors.values():
        if other is not keeper and other.active and other.team_id == keeper.team_id and _te().bears_mark(other, keeper.entity_id, "Resonance") \
                and engine._distance_actor_to_actor(keeper, other) <= 30:
            out.append(other)
    return out


@hook("action_completed")
def receive(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    if actor is None:
        return
    events = None
    for keeper in list(engine.state.actors.values()):
        if not keeper.active or keeper.team_id == actor.team_id:
            continue
        if st.row(engine, keeper, "receive_and_return") is not None and keeper.turn_flags.get("measure_round_gained") != engine.state.round_number:
            events = events if events is not None else _activation(engine, actor)
            pb = int(st.numbers(engine, keeper).get("pb") or 2)
            kinds = []
            for subject in _protected(engine, keeper):
                kinds += qualified(engine, actor, subject, events, pb)
            kinds = [k for k in dict.fromkeys(kinds) if not held(keeper, k)]
            if kinds:
                pick = _choose_kind(engine, keeper, kinds, "choice:needle.equal_measure.receive", f"{actor.display_name}'s technique: gain which Measure?",
                                    "Receiving a Measure", RECEIVE, allow_decline=False)
                if pick:
                    _gain(engine, keeper, pick, RECEIVE)
                    keeper.turn_flags["measure_round_gained"] = engine.state.round_number  # "Once per round"
                    note(engine, RECEIVE, keeper, f"{keeper.display_name} receives a Measure of {LABEL[pick]} from {actor.display_name}.", (actor,))
        court = _court(keeper)
        if court is not None:
            events = events if events is not None else _activation(engine, actor)
            _debts(engine, keeper, court, actor, events)


def _choose_kind(engine: Any, chooser: Any, kinds: list[str], choice_id: str, prompt: str, name: str, feature: str, *,
                 allow_decline: bool = True, target_id: str | None = None) -> str | None:
    from . import needle

    if not kinds:
        return None
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, choice_id.rsplit(".", 1)[-1].upper(), chooser.entity_id), chooser,
                        choice_id, list(kinds), labels={k: LABEL[k] for k in kinds}, preferred=list(kinds)[:1], allow_decline=allow_decline,
                        prompt=prompt, name=name, feature_id=feature, target_id=target_id)
    return chosen[0] if chosen and chosen[0] in kinds else (None if allow_decline else kinds[0])


# ---------------------------------------------------------------------------------------------------------- Measured Return
def _martial(ctx: Any) -> str | None:
    """"Martial Strike": Mind Spike, a weapon attack or an unarmed strike (Spirit Awakening core)."""
    typed = ctx.typed or {}
    if typed.get("source") == MIND_SPIKE:
        return "spike"
    if typed.get("weapon") and typed.get("source") != "improvised_weapon" and any(
            isinstance(row, dict) and row.get("type") == "attack" for row in typed.get("effects") or []):
        return "weapon"
    return None


def _save_failed(engine: Any, source: str, subject: Any) -> bool:
    for event in reversed(engine.events):
        if event.event_type == "SAVE_ROLLED" and event.actor_id == subject.entity_id and str((event.payload or {}).get("reason") or "").startswith(f"SAVE:{source}"):
            return (event.payload or {}).get("success") is False
    return False


@hook("damage_dealt")
def measured_return(ctx: Any, target: Any, amount: int) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or target.team_id == actor.team_id:
        return
    _any_hand(ctx, target)
    kind_of_strike = _martial(ctx)
    if (st.row(engine, actor, "receive_and_return") is None or kind_of_strike is None or engine.state.current_actor_id != actor.entity_id
            or actor.turn_flags.get("measured_return") or (ctx.action.parameters or {}).get("measure_recompense")):
        return
    if kind_of_strike == "spike" and not _save_failed(engine, ctx.source, target):
        return  # "On a successful save, only Mind Spike's normal result occurs and the Measure is not spent"
    kinds = [k for k in KINDS if held(actor, k)]
    pick = _choose_kind(engine, actor, kinds, "choice:needle.equal_measure.measured_return",
                        f"Measured Return: spend a Measure on {target.display_name}?", "Measured Return", RECEIVE, target_id=target.entity_id)
    if pick is None:
        return
    actor.turn_flags["measured_return"] = True  # "Once on each of your turns"
    _spend(engine, actor, pick, RECEIVE)
    sub = st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent)
    numbers = ctx.numbers or st.numbers(engine, actor)
    if pick == "impact":
        _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["psychic", "force"],
                                 "evidence": "Weight for Weight: an additional 1d8 Psychic or Force damage"}])
        engine._grant_temp_hp(actor, int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2), RECEIVE, actor.entity_id)
    elif pick == "motion":
        _step_or_shove(engine, actor, target, sub, 10, 10, 5, "Step for Step", RECEIVE, "measured_return_motion")
    else:
        _te().run_effects(sub, [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                 "evidence": "Resonance Mark the target until the end of your next turn"},
                                {"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect"}])
    note(engine, RECEIVE, actor, f"Measured Return: {actor.display_name} spends a Measure of {LABEL[pick]} on {target.display_name}.", (target,))


def _step_or_shove(engine: Any, mover: Any, target: Any, sub: Any, step_ft: int, fail_ft: int, success_ft: int, name: str, feature: str, topic: str) -> None:
    from . import needle

    options = ["step", "shove"]
    labels = {"step": f"Move yourself up to {step_ft} feet without provoking", "shove": f"{target.display_name} makes a Strength or Wisdom save or you move it"}
    chosen = needle.ask(engine, sub.intent, needle.checkpoint_id(engine, topic.upper(), target.entity_id), mover, f"choice:needle.equal_measure.{topic}",
                        options, labels=labels, preferred=["shove"], prompt=f"{name}: choose one.", name=name, feature_id=feature, target_id=target.entity_id)
    if (chosen[0] if chosen else "shove") == "step":
        routes = st.routes(engine, mover, step_ft)
        path = st.choose_route(engine, mover, routes, sub.intent, checkpoint=f"{topic.upper()}_STEP", prompt=f"{name}: move where?", name=name, feature=feature)
        if path is not None:
            from .rider_movement import step

            step(engine, mover, list(path), feature)
        return
    st.save(sub, target, "str_or_wis",
            on_fail=[{"type": "forced_movement", "applies_to": "target", "distance_ft": fail_ft, "direction": "away",
                      "evidence": f"On a failure, move it up to {fail_ft} feet"}],
            on_success=[{"type": "forced_movement", "applies_to": "target", "distance_ft": success_ft, "direction": "away",
                         "evidence": f"On a success, move it {success_ft} feet"}] if success_ft else [])


# ---------------------------------------------------------------------------------------------------------- Exact Counterweight
def _payment(engine: Any, keeper: Any, kind: str, source: Any) -> str | None:
    """How the keeper pays the Measure: its own ("measure"), or the source's matching Debt (Nothing Without Answer, once per round)."""
    if held(keeper, kind):
        return "measure"
    court = _court(keeper)
    if (court is not None and source is not None and _debt(source, keeper, kind) is not None
            and keeper.turn_flags.get("court_answer_debt_round_") != engine.state.round_number):
        return "debt"
    return None


def _pay(engine: Any, keeper: Any, kind: str, source: Any, how: str) -> None:
    engine._spend_resource(keeper, RESONANCE, 2, COUNTER)
    keeper.reaction_available = False
    if how == "debt":
        keeper.turn_flags["court_answer_debt_round_"] = engine.state.round_number
        st.remove(engine, source, _debt(source, keeper, kind), "DISCHARGED")
    else:
        _spend(engine, keeper, kind, COUNTER)


def _keepers(engine: Any, subject: Any, source: Any) -> list[Any]:
    """Exact Counterweight holders who may protect ``subject`` against ``source``."""
    if source is None or source.team_id == subject.team_id:
        return []
    return [k for k in engine.state.actors.values() if k.active and k.team_id == subject.team_id and st.row(engine, k, "exact_counterweight") is not None
            and st.can_react(k) and k.resources.get(RESONANCE, 0) >= 2 and subject in _protected(engine, k)]


@hook("incoming_damage")
def impact_counterweight(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    source = engine.state.actors.get(source_actor_id or "")
    if amount <= 0 or source is None:
        return None
    for keeper in _keepers(engine, target, source):
        how = _payment(engine, keeper, "impact", source)
        if how is None:
            continue
        from . import needle

        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "IMPACT_COUNTERWEIGHT", source.entity_id, target.entity_id), keeper,
                            "choice:needle.equal_measure.impact_counterweight", ["reduce"],
                            labels={"reduce": f"Impact Counterweight (Reaction, 2 Resonance, {'the Impact Debt' if how == 'debt' else 'your Impact Measure'}): reduce the {amount} damage by 3d8 + Wisdom"},
                            prompt=f"{source.display_name} deals {amount} damage to {target.display_name}.", preferred=["reduce"] if amount >= 10 else [],
                            allow_decline=True, default="first" if amount >= 10 else "decline", name="Exact Counterweight", feature_id=COUNTER,
                            target_id=target.entity_id)
        if not chosen:
            continue
        from ..gate2_runtime_models import DiceSpec

        with activation(engine, keeper, COUNTER):
            _pay(engine, keeper, "impact", source, how)
            numbers = st.numbers(engine, keeper)
            roll = engine.roller.roll(DiceSpec(count=3, sides=8, modifier=int(numbers.get("key_mod") or 0)), actor_id=keeper.entity_id,
                                      reason=f"DAMAGE_REDUCTION:{COUNTER}")
            engine._record_roll(roll)
            cut = min(amount, max(0, roll.total))
            engine._append_event("REACTION_RESOLVED", COUNTER, actor_id=keeper.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "DAMAGE_APPLICATION", "reaction_name": "Exact Counterweight (Impact)", "reduction": cut,
                                          "protects": target.entity_id})
            if cut >= amount and source.active and engine._distance_actor_to_actor(keeper, source) <= 60:
                ctx = st.context(engine, keeper, st.feature_action(engine, keeper, COUNTER), [source], numbers)
                _te().run_effects(ctx, [{"type": "damage", "applies_to": "target", "flat": int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2),
                                         "damage_types": ["psychic"], "evidence": "the source takes Psychic damage equal to your Wisdom modifier + Proficiency Bonus"},
                                        {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                         "evidence": "and becomes Resonance Marked until the end of your next turn"}])
                _counterstrike(engine, keeper, source)
            return cut
    return None


@hook("forced_distance")
def motion_counterweight(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if distance_ft <= 0 or source is None:
        return None
    for keeper in _keepers(engine, mover, source):
        how = _payment(engine, keeper, "motion", source)
        if how is None:
            continue
        from . import needle

        cut = min(20, distance_ft)
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "MOTION_COUNTERWEIGHT", source.entity_id, mover.entity_id), keeper,
                            "choice:needle.equal_measure.motion_counterweight", ["reduce"],
                            labels={"reduce": f"Motion Counterweight (Reaction, 2 Resonance): reduce the {distance_ft}-foot forced movement by {cut} feet"},
                            prompt=f"{source.display_name} forces {mover.display_name} to move.", preferred=["reduce"], allow_decline=True,
                            name="Exact Counterweight", feature_id=COUNTER, target_id=mover.entity_id)
        if not chosen:
            continue
        with activation(engine, keeper, COUNTER):
            _pay(engine, keeper, "motion", source, how)
            engine._append_event("REACTION_RESOLVED", COUNTER, actor_id=keeper.entity_id, target_ids=(mover.entity_id,),
                                 payload={"checkpoint": "FORCED_MOVEMENT", "reaction_name": "Exact Counterweight (Motion)", "reduction": cut})
            if cut >= distance_ft:
                _held_ground(engine, keeper, mover, source)
            return cut
    return None


@hook("condition_attempt")
def prone_counterweight(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if str(effect_row.get("condition") or "").lower() != "prone" or subject is None:
        return None
    engine, source = ctx.engine, ctx.actor
    for keeper in _keepers(engine, subject, source):
        how = _payment(engine, keeper, "motion", source)
        if how is None:
            continue
        from . import needle

        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PRONE_COUNTERWEIGHT", source.entity_id, subject.entity_id), keeper,
                            "choice:needle.equal_measure.prone_counterweight", ["prevent"],
                            labels={"prevent": f"Motion Counterweight (Reaction, 2 Resonance): {subject.display_name} is not knocked Prone"},
                            prompt=f"{source.display_name} would knock {subject.display_name} Prone.", preferred=["prevent"], allow_decline=True,
                            name="Exact Counterweight", feature_id=COUNTER, target_id=subject.entity_id)
        if not chosen:
            continue
        with activation(engine, keeper, COUNTER):
            _pay(engine, keeper, "motion", source, how)
            engine._append_event("REACTION_RESOLVED", COUNTER, actor_id=keeper.entity_id, target_ids=(subject.entity_id,),
                                 payload={"checkpoint": "CONDITION", "reaction_name": "Exact Counterweight (Motion)", "prevented": "prone"})
            _held_ground(engine, keeper, subject, source)
            return False
    return None


def _held_ground(engine: Any, keeper: Any, protected: Any, source: Any) -> None:
    """"If all forced movement is prevented or the protected creature avoids the condition, it may move 5 feet to a legal space
    without provoking opportunity attacks from the source." Then Counterweight Becomes Counterstrike."""
    routes = {c: v for c, v in st.routes(engine, protected, 5).items() if c != protected.position}
    if routes and protected.active:
        path = st.choose_route(engine, protected, routes, engine._active_intent, checkpoint="COUNTERWEIGHT_STEP",
                               prompt=f"Exact Counterweight: {protected.display_name} may move 5 feet without provoking.", name="Exact Counterweight",
                               feature=COUNTER)
        if path is not None:
            from .rider_movement import step

            step(engine, protected, list(path), COUNTER)
    _counterstrike(engine, keeper, source)


def _intent_guard(engine: Any, holder: Any, rc: Any) -> bool:
    keeper, roller, source = holder.actor, rc.roller, getattr(rc, "source_actor", None)
    if source is None or source.team_id == keeper.team_id or roller not in _protected(engine, keeper):
        return False
    if str(rc.ability or "").upper()[:3] not in MENTAL:
        return False
    return _payment(engine, keeper, "intent", source) is not None


def _intent_pay(engine: Any, holder: Any, rc: Any) -> None:
    """The matching Measure (the Rule's own costs are the 2 Resonance and the Reaction); Nothing Without Answer: the Debt instead."""
    source = getattr(rc, "source_actor", None)
    how = _payment(engine, holder.actor, "intent", source)
    if how == "debt":
        holder.actor.turn_flags["court_answer_debt_round_"] = engine.state.round_number
        st.remove(engine, source, _debt(source, holder.actor, "intent"), "DISCHARGED")
    elif how == "measure":
        _spend(engine, holder.actor, "intent", COUNTER)


def _intent_bonus(engine: Any, holder: Any, rc: Any) -> int:
    """"add 1d6 to the roll after seeing the d20 but before the outcome is finalized"."""
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=holder.actor.entity_id, reason=f"SAVE_BONUS:{COUNTER}")
    engine._record_roll(roll)
    return int(roll.total)


def _intent_after(engine: Any, holder: Any, rc: Any, result: Any) -> None:
    source = getattr(rc, "source_actor", None)
    if source is None or not source.active or rc.dc is None:
        return
    outcome = (getattr(engine, "_typed_roll_outcome", None) or {}).get(rc.roller.entity_id)  # the +1d6 rides the table's outcome override
    if outcome != "success" and (outcome is not None or int(getattr(result, "total", 0) or 0) < int(rc.dc)):
        return  # "If the added die changes a failure into a success"
    if engine._distance_actor_to_actor(holder.actor, source) <= 60:
        ctx = st.context(engine, holder.actor, st.feature_action(engine, holder.actor, COUNTER), [source], st.numbers(engine, holder.actor))
        _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect on the source"}])
    _counterstrike(engine, holder.actor, source)


def _intent_ai(engine: Any, holder: Any, rc: Any) -> bool:
    return rc.dc is not None and 0 < int(rc.dc) - int(rc.roll.total) <= 6  # a d6 can turn this failure into a success


def _register_rules() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("equal_measure_intent_counterweight", "Exact Counterweight (Intent)", feature=COUNTER, rolls=("save",), who="team", range_ft=30,
                  when="failed", op="choose", choose=lambda engine, holder, rc: rc.natural, bonus=_intent_bonus, costs=((("resonance", 2),),),
                  reaction=True, abilities=MENTAL, guard=_intent_guard, ai=_intent_ai, on_use=_intent_pay, after=_intent_after))


_register_rules()


def _counterstrike(engine: Any, keeper: Any, source: Any) -> None:
    """Counterweight Becomes Counterstrike (CL14, once per round): one Martial Strike against the source as part of the Reaction."""
    if (source is None or not source.active or not keeper.active or st.row(engine, keeper, "the_scales_do_not_tremble") is None
            or keeper.turn_flags.get("counterstrike_round_") == engine.state.round_number):
        return
    options = _strike_options(engine, keeper, source, spike_dice=-1)
    if not options:
        return
    from . import needle

    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "COUNTERSTRIKE", source.entity_id), keeper,
                        "choice:needle.equal_measure.counterstrike", list(options), labels={k: v[0] for k, v in options.items()},
                        preferred=list(options)[:1], allow_decline=True, prompt=f"Counterweight Becomes Counterstrike: a Martial Strike against {source.display_name}?",
                        name="Counterweight Becomes Counterstrike", feature_id=SCALES, target_id=source.entity_id)
    if not chosen or chosen[0] not in options:
        return
    keeper.turn_flags["counterstrike_round_"] = engine.state.round_number
    options[chosen[0]][1]()


def _strike_options(engine: Any, actor: Any, target: Any, *, spike_dice: int = 0, effects_for: Any = None) -> dict[str, tuple[str, Any]]:
    """Martial Strikes the actor can make on ``target`` now: {key: (label, run)}."""
    out: dict[str, tuple[str, Any]] = {}
    intent = engine._active_intent
    spike = st.action_named(engine, actor, "Mind Spike")
    if spike is not None and engine._distance_actor_to_actor(actor, target) <= int(spike.range_ft or 60):
        out["spike"] = ("Mind Spike" + (" (one damage die fewer)" if spike_dice < 0 else ""),
                        lambda: st.mind_spike(engine, actor, target, intent, dice_delta=spike_dice))
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
        if (action is None or action.economy.value != "ACTION" or not typed.get("weapon") or typed.get("source") == "improvised_weapon"
                or not any(isinstance(r, dict) and r.get("type") == "attack" for r in typed.get("effects") or [])
                or "echo_origin" in action_id or int((action.parameters or {}).get("expected_damage") or 0) <= 0):
            continue
        if engine._distance_actor_to_actor(actor, target) <= int(action.range_ft or action.reach_ft or 5):
            out[action_id] = (action.display_name, (lambda a=action: st.run_action(engine, actor, a, target, intent)))
    return out


# ---------------------------------------------------------------------------------------------------------- Convert the Measure
@hook("compile_actions")
def measure_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    if SCALES in owned:
        for source in KINDS:
            for into in KINDS:
                if source == into:
                    continue
                out.append(ActionDefinition(
                    source_definition_id=f"action:typed.{info['short']}.measure_convert.{source}_{into}",
                    display_name=f"Convert the Measure: {LABEL[source]} to {LABEL[into]}", owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION,
                    resolution_kind="TYPED", target_kind="SELF", costs=((RESONANCE, 1),),
                    parameters={"typed": {"effects": [{"type": "measure_convert", "applies_to": "self", "from": source, "to": into}],
                                          "numbers": info["numbers"], "duration": {"kind": "instant"},
                                          "riders": [], "source": SCALES},
                                "expected_damage": 0, "measure_convert": [source, into],
                                "description": f"The Scales Do Not Tremble (Bonus Action, 1 Resonance, once per turn): your {LABEL[source]} Measure becomes "
                                               f"{LABEL[into]} (you cannot hold two of one kind)."}))
    if COURT in owned and RECOMPENSE in owned:
        base = next((a for a in info["actions"] if ((a.parameters or {}).get("typed") or {}).get("source") == RECOMPENSE), None)
        if base is not None:
            typed = copy.deepcopy((base.parameters or {}).get("typed") or {})
            typed["effects"] = [{**row, "perfect": True} for row in typed.get("effects") or []]
            out.append(base.model_copy(update={
                "source_definition_id": f"{base.source_definition_id}.perfect", "display_name": "Threefold Recompense (Perfect Recompense)", "costs": (),
                "parameters": {**(base.parameters or {}), "typed": typed, "perfect_recompense": True,
                               "description": "Court of Equal Heaven (once per activation): Threefold Recompense without its Resonance cost against a "
                                              "creature in the Domain; its Debts may be discharged as though they were Measures."}}))
    return out or None


@hook("candidate_allowed")
def measure_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (action.parameters or {}) if action is not None else {}
    if params.get("measure_convert"):
        source, into = params["measure_convert"]
        if actor.turn_flags.get("measure_converted") or not held(actor, source) or held(actor, into):
            return False
        return None
    typed = params.get("typed") or {}
    if typed.get("source") == RECOMPENSE:
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        if target is None or not _te().bears_mark(target, actor.entity_id, "Resonance") or not _strike_options(engine, actor, target):
            return False
        if params.get("perfect_recompense"):
            court = _court(actor)
            if court is None or st.data_of(actor, court).get("perfect_used") or not _in_domain(engine, actor, target):
                return False
            return None if any(held(actor, k) or _debt(target, actor, k) is not None for k in KINDS) else False
        return None if any(held(actor, k) for k in KINDS) else False
    return None


@effect("measure_convert")
def convert(ctx: Any, row: dict[str, Any]) -> None:
    source, into = str(row.get("from")), str(row.get("to"))
    if not held(ctx.actor, source) or held(ctx.actor, into):
        return
    ctx.actor.turn_flags["measure_converted"] = True  # "Once per turn"
    _spend(ctx.engine, ctx.actor, source, SCALES)
    _gain(ctx.engine, ctx.actor, into, SCALES)


# ---------------------------------------------------------------------------------------------------------- Threefold Recompense
@effect("measure_recompense")
def recompense(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    perfect = bool(row.get("perfect"))
    court = _court(actor) if perfect else None
    sources = {k: ("measure" if held(actor, k) else "debt") for k in KINDS
               if held(actor, k) or (perfect and _debt(target, actor, k) is not None)}
    if not sources:
        return
    labels = {k: f"{LABEL[k]} ({'your Measure' if how == 'measure' else 'its Debt'})" for k, how in sources.items()}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "RECOMPENSE", target.entity_id), actor, "choice:needle.equal_measure.recompense",
                        list(sources), labels=labels, preferred=list(sources), minimum=1, maximum=3, default="all",
                        prompt="Threefold Recompense: spend which Measures (one, two or three different ones)?", name="Threefold Recompense",
                        feature_id=RECOMPENSE, target_id=target.entity_id)
    spent = [k for k in (chosen or list(sources)) if k in sources][:3]
    if court is not None:
        st.set_data(actor, court, perfect_used=1)  # "Once during the activation"
    discharged = 0
    for kind in spent:
        if sources[kind] == "measure":
            _spend(engine, actor, kind, RECOMPENSE)
        else:
            st.remove(engine, target, _debt(target, actor, kind), "DISCHARGED")
            discharged += 1
    options = _strike_options(engine, actor, target)
    if not options:
        return
    pick = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "RECOMPENSE_STRIKE", target.entity_id), actor, "choice:needle.equal_measure.recompense_strike",
                      list(options), labels={k: v[0] for k, v in options.items()}, preferred=list(options)[-1:],
                      prompt="Threefold Recompense: which Martial Strike?", name="Threefold Recompense", feature_id=RECOMPENSE, target_id=target.entity_id)
    key = pick[0] if pick and pick[0] in options else list(options)[-1]
    added = [{"type": "damage", "applies_to": "target", "dice": {"count": 2 + len(spent), "sides": 8}, "damage_types": ["psychic", "force"],
              "bypass_temporary_hp": "impact" in spent,
              "evidence": f"plus {2 + len(spent)}d8 Psychic or Force damage (2d8 + 1d8 for each Measure spent)"}]
    riders: list[dict[str, Any]] = []
    if "motion" in spent:
        riders.append({"type": "measure_recompense_motion", "applies_to": "target"})
    if "intent" in spent:
        riders += [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "two different ordinary Spiritual Pressure effects"},
                   {"type": "spiritual_pressure", "applies_to": "target", "different": True, "evidence": "two different ordinary Spiritual Pressure effects"}]
    if perfect and discharged == 3:
        riders += [{"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "cannot take Reactions"},
                   {"type": "speed", "applies_to": "target", "becomes": 0, "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "has Speed 0"},
                   {"type": "disadvantage", "applies_to": "target", "on": "its next Intelligence, Wisdom, or Charisma saving throw",
                    "duration": {"kind": "until_start_of_your_next_turn"}, "evidence": "has Disadvantage on its next Intelligence, Wisdom, or Charisma saving throw"}]
    source = engine.action_catalog.get(key) if key != "spike" else st.action_named(engine, actor, "Mind Spike")
    typed = copy.deepcopy((source.parameters or {}).get("typed") or {})
    effects = typed.get("effects") or []
    for effect_row in effects:
        branch = {"attack": ["on_hit"], "save": ["on_fail"]}.get(effect_row.get("type") if isinstance(effect_row, dict) else "")
        if branch:
            before = [{"type": "measure_recompense_motion_before", "applies_to": "target", "before_save_damage": True}] if "motion" in spent else []
            for outcome in branch:
                effect_row[outcome] = [*before, *(effect_row.get(outcome) or [])]
            effect_row[branch[0]] = [*(effect_row.get(branch[0]) or []), *added, *riders]  # save-for-half keeps its ordinary damage packet
            break
    parameters = {**(source.parameters or {}), "measure_recompense": True}
    strike = source.model_copy(update={"parameters": parameters})
    sub = _te().Context(engine, actor, strike, ctx.intent, typed, [target], target, {})
    _te().run_effects(sub, effects)


@effect("measure_recompense_motion")
def recompense_motion(ctx: Any, row: dict[str, Any]) -> None:
    """After-damage choice: move the target on a failed Strength or Wisdom save."""
    if ctx.target is None or not ctx.target.active or ctx.damage_cache.get("measure_motion") == "step":
        return
    st.save(st.context(ctx.engine, ctx.actor, ctx.action, [ctx.target], ctx.numbers, ctx.intent), ctx.target, "str_or_wis",
            on_fail=[{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away",
                      "evidence": "move the target up to 15 feet after damage on a failed Strength or Wisdom saving throw"}])


# ---------------------------------------------------------------------------------------------------------- Court of Equal Heaven
def _court(owner: Any) -> Any:
    return next((c for c in owner.conditions.values() if c.condition_id == COURT_STATE and c.source_actor_id == owner.entity_id), None)


def _zone(engine: Any, owner: Any) -> Any:
    from .. import zones

    court = _court(owner)
    if court is None:
        return None
    return next((z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id and z.source_definition_id == court.source_definition_id), None)


def _in_domain(engine: Any, owner: Any, creature: Any) -> bool:
    zone = _zone(engine, owner)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _debt(creature: Any, owner: Any, kind: str) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == DEBT[kind] and c.source_actor_id == owner.entity_id), None)


@effect("measure_court")
def court(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    allies = [a for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id and a is not actor]
    ids = [a.entity_id for a in allies]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "COURT_ALLIES", actor.entity_id), actor, "choice:needle.equal_measure.court_allies",
                        ids, labels={a.entity_id: a.display_name for a in allies}, preferred=ids, minimum=0, maximum=len(ids), default="all",
                        allow_decline=True, prompt="Court of Equal Heaven: which allies are chosen?", name="Court of Equal Heaven",
                        feature_id=COURT) if ids else []
    held_court = _court(actor)
    if held_court is not None:
        st.remove(engine, actor, held_court, "REPLACED")
    engine._apply_condition(actor, COURT_STATE, ctx.source, actor.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                            data={"allies": [a for a in chosen if a in ids], "label": "Court of Equal Heaven: Debts, Any Hand May Answer"})


def _chosen(owner: Any, creature: Any) -> bool:
    court = _court(owner)
    return court is not None and creature.entity_id in ((court.data or {}).get("allies") or [])


def _debts(engine: Any, owner: Any, court_state: Any, source: Any, events: list[Any]) -> None:
    """Debts of the Aggressor: one Debt the first time each round the source's activation harms a chosen ally in the Domain."""
    if source.team_id == owner.team_id or not _in_domain(engine, owner, source):
        return
    token = f"court_debt_round_{owner.entity_id}"
    if source.turn_flags.get(token) == engine.state.round_number:
        return
    kinds = []
    for ally in engine.state.actors.values():
        if _chosen(owner, ally) and _in_domain(engine, owner, ally):
            kinds += qualified(engine, source, ally, events, 1)
    kinds = [k for k in dict.fromkeys(kinds) if _debt(source, owner, k) is None]  # "one Debt of each kind"
    if not kinds:
        return
    pick = _choose_kind(engine, owner, kinds, "choice:needle.equal_measure.debt", f"{source.display_name} incurs which Debt?", "Debts of the Aggressor",
                        COURT, allow_decline=False, target_id=source.entity_id)
    if pick is None:
        return
    source.turn_flags[token] = engine.state.round_number
    engine._apply_condition(source, DEBT[pick], court_state.source_definition_id, owner.entity_id, expires_on="CONCENTRATION_END",
                            data={"label": f"Debt of {LABEL[pick]} ({owner.display_name}'s Court of Equal Heaven)"})


@hook("event")
def debts_leave(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Debts ... end when the creature leaves the Domain"."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if mover is None:
        return
    for kind in KINDS:
        for held_debt in [c for c in mover.conditions.values() if c.condition_id == DEBT[kind]]:
            owner = engine.state.actors.get(held_debt.source_actor_id)
            if owner is None or not _in_domain(engine, owner, mover):
                st.remove(engine, mover, held_debt, "LEFT_DOMAIN")


def _any_hand(ctx: Any, target: Any) -> None:
    """Any Hand May Answer: once on each turn, a chosen ally's damage to an indebted creature may discharge one Debt."""
    engine, ally = ctx.engine, ctx.actor
    if (ctx.action.parameters or {}).get("measure_answer"):
        return
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id != ally.team_id or _court(owner) is None or not _chosen(owner, ally):
            continue
        token = f"{engine.state.round_number}:{engine.state.current_actor_id}"
        if owner.turn_flags.get("court_answer_round_") == token or ally.turn_flags.get("court_benefit_round_") == token:
            continue
        kinds = [k for k in KINDS if _debt(target, owner, k) is not None]
        pick = _choose_kind(engine, ally, kinds, "choice:needle.equal_measure.any_hand", f"Any Hand May Answer: discharge one of {target.display_name}'s Debts?",
                            "Any Hand May Answer", COURT, target_id=target.entity_id)
        if pick is None:
            continue
        owner.turn_flags["court_answer_round_"] = token
        ally.turn_flags["court_benefit_round_"] = token
        st.remove(engine, target, _debt(target, owner, pick), "DISCHARGED")
        answer = ctx.action.model_copy(update={"parameters": {**(ctx.action.parameters or {}), "measure_answer": True}})
        sub = st.context(engine, ally, answer, [target], ctx.numbers, ctx.intent)
        if pick == "impact":
            _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["psychic", "force"],
                                     "evidence": "Any Hand May Answer (Impact): an additional 3d8 Psychic or Force damage"}])
        elif pick == "motion":
            _step_or_shove(engine, ally, target, sub, 15, 15, 5, "Any Hand May Answer", COURT, "any_hand_motion")
        else:
            owner_ctx = st.context(engine, owner, st.feature_action(engine, owner, COURT), [target], st.numbers(engine, owner), ctx.intent)
            _te().run_effects(owner_ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "Impose one ordinary Spiritual Pressure effect"}])
            _te().run_effects(st.context(engine, ally, answer, [ally], ctx.numbers, ctx.intent),
                              [{"type": "advantage", "applies_to": "self", "on": "its next Intelligence, Wisdom, or Charisma saving throw",
                                "duration": {"kind": "until_start_of_next_turn"},
                                "evidence": "grant the ally Advantage on its next Intelligence, Wisdom, or Charisma saving throw before the start of its next turn"}])
        note(engine, COURT, ally, f"Any Hand May Answer: {ally.display_name} discharges {target.display_name}'s Debt of {LABEL[pick]}.", (target,))
        return


@effect("measure_recompense_motion_before")
def recompense_motion_before(ctx: Any, row: dict[str, Any]) -> None:
    """Confirmed hit/failed save: choose the before-damage step or after-damage push."""
    from . import needle

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    routes = st.routes(engine, actor, engine.grid.width * engine.grid.height * engine.grid.square_size_ft) if engine._effective_speed(actor) > 0 else {}
    routes = {cell: value for cell, value in routes.items()
              if cell != actor.position and engine._distance_actor_to_actor(actor.model_copy(update={"position": cell}), target) <= 5}
    options = ["push", *(["step"] if routes else [])]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "RECOMPENSE_MOTION", target.entity_id), actor,
                        "choice:needle.equal_measure.recompense_motion", options,
                        labels={"push": "After damage: target saves against being moved 15 feet",
                                "step": "Before damage: move beside the target"}, preferred=["push"],
                        prompt="Motion Recompense: move yourself before damage, or move the target after damage?",
                        name="Threefold Recompense", feature_id=RECOMPENSE, target_id=target.entity_id)
    ctx.damage_cache["measure_motion"] = chosen[0] if chosen else "push"
    if ctx.damage_cache["measure_motion"] != "step":
        return
    path = st.choose_route(engine, actor, routes, ctx.intent, checkpoint="RECOMPENSE_ADJACENT",
                           prompt="Motion Recompense: choose a legal space beside the target.",
                           name="Threefold Recompense", feature=RECOMPENSE, stay=False,
                           target_id=target.entity_id)
    if path is not None:
        feet = routes[path[-1]][1]
        engine.grant_movement(actor, list(path), RECOMPENSE, feet=feet, intent=ctx.intent,
                              provokes=True, ignore_oa_from=(target.entity_id,))
