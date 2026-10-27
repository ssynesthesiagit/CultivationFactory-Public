"""Grief Eater (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Grief Eater: Sorrow Burdens, CL3 Taste of Sorrow, CL6 Eat the Bitter Memory,
CL10 Shared Burden, CL14 Weight of Mourning, CL18 Vessel of Ten Thousand Sorrows). No Spheres 5e or D&D 5.5e counterpart. Shared
Burden's Divide the Pain is combat/ext/damage_sharing.py and Carry the Echo a d20 rewrite in combat/ext/d20_rewrite_rules.py.
Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json (Taste of Sorrow); Shared Burden is owned
through its damage_sharing row; the actions and the Mourning Field need no row.

Sorrow Burdens (tradition text): a pool (resource:named.sorrow_burden), 0 to start, maximum PB, for the fight.

What runs:
  * Gaining a Sorrow Burden: when a creature within 60 feet that you can see becomes Bloodied, Frightened or Charmed, drops to 0 Hit
    Points or dies, you gain 1 (no more than 1 per turn). Taste of Sorrow (Reaction, asked; the AI uses it on foes): mark that
    creature until the end of your next turn -- an ally is willing, a foe gets a Wisdom save.
  * Eat the Bitter Memory (Action, touch, 3 Resonance, a willing creature that is Frightened or Charmed): Consume -- end it, gain 1
    Sorrow Burden, take 1d8 Psychic that nothing reduces; Suppress -- hide it until the end of your next turn, take 2d8 Psychic, and
    the creature has Advantage on its next save against it; Diagnose -- the GM's information.
  * Shared Burden -- Hold the Door (Reaction, 4 Resonance or 2 Sorrow Burdens, asked): an ally within 30 feet would become Charmed or
    Frightened by a hostile creature -- the condition waits until the end of its next turn and then lands, unless that creature is
    gone.
  * Weight of Mourning (Action, 60 feet, 6 Resonance and 1 Sorrow Burden; a creature that has damaged one of your allies, or dropped
    a creature to 0 Hit Points, this fight): Charisma save. Failed: Mourning Weight until two successful saves at the end of its
    turns -- half Speed, no Reactions, Disadvantage on attacks against the creatures it damaged, 2 x PB Psychic the first time each
    turn it uses an Action or Bonus Action against your side, and it cannot benefit from being Hidden against you. Success: Speed -10
    until the end of its next turn and your chosen Spiritual Pressure.
  * Vessel of Ten Thousand Sorrows (Bonus Action, 10 Resonance, the fight; a 30-foot Mourning Field that moves with you): the allies
    you choose (asked; the AI chooses all) in it take half Psychic damage and have Advantage on saves against Charmed and Frightened;
    once per round when one fails such a save you may take a Spiritual Pressure effect to let it reroll (asked); when you end,
    suppress or delay a hostile effect in the field with Eat the Bitter Memory, Shared Burden or Hold the Door, an ally in the field
    gains Temporary HP = Wisdom + PB. Mourning Offices, one per Sorrow Burden spent (asked): Funeral Bell -- the first time each round a
    hostile creature in the field deals Psychic or Necrotic damage, it is Resonance Marked and takes PB Psychic. Mourner's Embrace
    (once per Field, no action, on your turn): a hostile creature in it bearing Mourning Weight or your Resonance Mark makes a Charisma
    save -- failed: Restrained until the end of its next turn, and it chooses one of the printed four (asked of its side; "accept"
    is 8d10 + Wisdom Psychic and two different Spiritual Pressure effects; cease hostility filters harmful actions,
    speak resolves immediately, and a grief-linked movement destination remains unrepresented); success: half of 8d10 + Wisdom and
    one Spiritual Pressure effect.

Plug-in surface: effects grief_consume, grief_suppress, grief_weight, grief_vessel, grief_embrace; hooks event, action_completed,
condition_attempt, turn_end, speed, before_attack, save, incoming_damage, compile_actions, candidate_allowed, opportunity_allowed,
reaction_subject_allowed; a d20_rewrite Rule
(grief_vessel_reroll). Public helpers: ``gain_burden``, ``field_answer``. Shared helpers used: spirit_traditions (row/context/numbers/
feature_action/can_react/save/remove/suppress/delay_condition/land_delayed_condition/landing), needle.ask, stealth.sees, zones.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.grief_eater.feature."
TASTE = TRADITION + "taste_of_sorrow"
EAT = TRADITION + "eat_the_bitter_memory"
SHARED = TRADITION + "shared_burden"
WEIGHT = TRADITION + "weight_of_mourning"
VESSEL = TRADITION + "vessel_of_ten_thousand_sorrows"
BURDEN = "resource:named.sorrow_burden"
RESONANCE = "resource:core.resonance"
MOURNING = "condition:typed.mourning_weight"
FIELD = "condition:typed.mourning_field"
HOLD = "condition:typed.hold_the_door"
CALM = ("frightened", "charmed")
EMOTIONAL = ("charmed", "frightened", "possessed", "possession")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(row.get("feature_id") == feature for store in ("typed_passive_rows", "typed_reaction_rows")
               for row in (getattr(engine, store, None) or {}).get(actor.entity_id, []))


def gain_burden(engine: Any, eater: Any, source: str) -> bool:
    """1 Sorrow Burden, up to Proficiency Bonus, no more than 1 per turn."""
    token = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if eater.turn_flags.get("sorrow_round_gained") == token or eater.resources.get(BURDEN, 0) >= eater.resource_maximums.get(BURDEN, 0):
        return False
    eater.turn_flags["sorrow_round_gained"] = token
    engine._gain_resource(eater, BURDEN, 1, source)
    return True


def _unreduced(engine: Any, victim: Any, amount: int, source: str) -> None:
    """Psychic damage to the Grief Eater that "cannot be reduced" (Eat the Bitter Memory)."""
    if amount <= 0:
        return
    engine.__dict__["_damage_unreduced"] = victim.entity_id
    try:
        engine._commit_damage(victim, amount, "PSYCHIC", source, victim.entity_id, engine._active_intent, reaction_depth=1)
    finally:
        if engine.__dict__.get("_damage_unreduced") == victim.entity_id:
            engine.__dict__.pop("_damage_unreduced", None)


def _roll(engine: Any, actor: Any, count: int, sides: int, modifier: int, why: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=modifier), actor_id=actor.entity_id, reason=f"DAMAGE:{why}")
    engine._record_roll(roll)
    return int(roll.total)


# ------------------------------------------------------------------------------------------------ Sorrow Burdens, Taste of Sorrow
def _sorrow_moment(engine: Any, subject: Any) -> None:
    from .. import stealth

    for eater in list(engine.state.actors.values()):
        if not eater.active or st.row(engine, eater, "taste_of_sorrow") is None:
            continue
        if eater is not subject and (engine._distance_actor_to_actor(eater, subject) > 60 or not stealth.sees(engine, eater, subject)):
            continue
        gain_burden(engine, eater, TASTE)
        if subject is eater or not subject.active or not st.can_react(eater) or _te().bears_mark(subject, eater.entity_id, "Resonance"):
            continue
        from . import needle

        foe = subject.team_id != eater.team_id
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "TASTE_OF_SORROW", subject.entity_id), eater,
                            "choice:needle.grief_eater.taste", ["mark"], labels={"mark": f"Taste of Sorrow (your Reaction): {subject.display_name} "
                                                                                          + ("makes a Wisdom save or is" if foe else "is") + " Resonance Marked until the end of your next turn"},
                            prompt=f"{subject.display_name}'s sorrow is within reach.", preferred=["mark"] if foe else [], allow_decline=True,
                            default="first" if foe else "decline", name="Taste of Sorrow", feature_id=TASTE, target_id=subject.entity_id)
        if not chosen:
            continue
        with activation(engine, eater, TASTE):
            eater.reaction_available = False
            engine._append_event("REACTION_RESOLVED", TASTE, actor_id=eater.entity_id, target_ids=(subject.entity_id,),
                                 payload={"checkpoint": "SORROW", "reaction_name": "Taste of Sorrow"})
            ctx = st.context(engine, eater, st.feature_action(engine, eater, TASTE), [subject], st.numbers(engine, eater))
            mark = [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                     "evidence": "it becomes Resonance Marked by you until the end of your next turn"}]
            if foe:
                st.save(ctx, subject, "wis", on_fail=mark)
            else:
                _te().run_effects(ctx, mark)


@hook("event")
def sorrow_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "DAMAGE_COMMITTED":
        target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if target is None:
            return
        after, lost = int(payload.get("remaining_hp") or 0), int(payload.get("hp_damage") or 0)
        half = target.maximum_hp // 2
        if lost > 0 and (after == 0 or (after <= half < after + lost)):  # drops to 0, or newly Bloodied
            _sorrow_moment(engine, target)
    elif event_type == "CONDITION_APPLIED":
        target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if target is not None and str(payload.get("condition_id") or "").rsplit(".", 1)[-1].lower() in CALM:
            _sorrow_moment(engine, target)


# ---------------------------------------------------------------------------------------------------------- Eat the Bitter Memory
def _calm(target: Any) -> list[Any]:
    return [c for _, c in sorted(target.conditions.items()) if _name(c) in CALM]


def _pick_calm(engine: Any, eater: Any, target: Any, intent: Any, why: str) -> Any:
    from . import needle

    held = _calm(target)
    if len(held) <= 1:
        return held[0] if held else None
    ids = [f"c{i}" for i in range(len(held))]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "EAT_WHICH", target.entity_id), eater, "choice:needle.grief_eater.which",
                        ids, labels={f"c{i}": _name(c).title() for i, c in enumerate(held)}, preferred=ids[:1], prompt=f"{why}: which effect?",
                        name=why, feature_id=EAT, target_id=target.entity_id)
    return held[ids.index(chosen[0])] if chosen and chosen[0] in ids else held[0]


@effect("grief_consume")
def consume(ctx: Any, row: dict[str, Any]) -> None:
    engine, eater, target = ctx.engine, ctx.actor, ctx.target
    condition = _pick_calm(engine, eater, target, ctx.intent, "Eat the Bitter Memory") if target is not None else None
    if condition is None:
        return
    st.remove(engine, target, condition, "CONSUMED")
    gain_burden(engine, eater, EAT)
    _unreduced(engine, eater, _roll(engine, eater, 1, 8, 0, EAT), EAT)  # "1d8 Psychic damage per authority tier ... cannot be reduced"
    field_answer(engine, eater, target, ctx.intent)
    note(engine, EAT, eater, f"{eater.display_name} eats {target.display_name}'s {_name(condition).title()}.", (target,))


@effect("grief_suppress")
def suppress(ctx: Any, row: dict[str, Any]) -> None:
    engine, eater, target = ctx.engine, ctx.actor, ctx.target
    condition = _pick_calm(engine, eater, target, ctx.intent, "Eat the Bitter Memory") if target is not None else None
    if condition is None:
        return
    name = _name(condition)
    st.suppress(engine, target, condition, EAT, eater.entity_id, "Eat the Bitter Memory", clock=eater)  # "until the end of your next turn"
    _unreduced(engine, eater, _roll(engine, eater, 2, 8, 0, EAT), EAT)
    sub = st.context(engine, eater, ctx.action, [target], ctx.numbers, ctx.intent)
    _te().run_effects(sub, [{"type": "advantage", "applies_to": "target", "on": f"its next saving throw against being {name.title()}",
                             "duration": {"kind": "until_end_of_your_next_turn"},
                             "evidence": "The target gains Advantage on the next save it makes against that effect during the suppression."}])
    field_answer(engine, eater, target, ctx.intent)


@hook("candidate_allowed")
def grief_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    feature = st.feature_of(action)
    typed = (action.parameters or {}).get("typed") or {}
    kinds = {row.get("type") for row in typed.get("effects") or [] if isinstance(row, dict)}
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if feature == EAT and kinds & {"grief_consume", "grief_suppress"}:
        return None if target is not None and _calm(target) else False
    if feature == WEIGHT:
        return None if target is not None and _qualifies(engine, actor, target) else False
    if (action.parameters or {}).get("grief_embrace"):
        field = _field(actor)
        if field is None or st.data_of(actor, field).get("embrace_used") or engine.state.current_actor_id != actor.entity_id:
            return False
        return None if target is not None and _in_field(engine, actor, target) and (
            _mourning(target) is not None or _te().bears_mark(target, actor.entity_id, "Resonance")) else False
    return None


# ---------------------------------------------------------------------------------------------------------- Shared Burden: Hold the Door
@hook("condition_attempt")
def hold_the_door(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    name = str(effect_row.get("condition") or "").lower()
    engine = ctx.engine
    if name not in CALM or subject is None or ctx.actor.team_id == subject.team_id or st.landing(engine, subject):
        return None
    for eater in list(engine.state.actors.values()):
        if (not eater.active or eater is subject or eater.team_id != subject.team_id or not _owns(engine, eater, SHARED) or not st.can_react(eater)
                or engine._distance_actor_to_actor(eater, subject) > 30):
            continue
        pays = [*(["burdens"] if eater.resources.get(BURDEN, 0) >= 2 else []), *(["resonance"] if eater.resources.get(RESONANCE, 0) >= 4 else [])]
        if not pays:
            continue
        from . import needle

        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HOLD_THE_DOOR", subject.entity_id), eater, "choice:needle.grief_eater.hold_the_door",
                            pays, labels={"burdens": "Hold the Door: pay 2 Sorrow Burdens", "resonance": "Hold the Door: pay 4 Resonance"}, preferred=pays[:1],
                            allow_decline=True, name="Shared Burden (Hold the Door)", feature_id=SHARED, target_id=subject.entity_id,
                            prompt=f"{subject.display_name} would become {name.title()}. Hold the Door (your Reaction): it waits until the end of its next turn.")
        if not chosen or chosen[0] not in pays:
            continue
        with activation(engine, eater, SHARED):
            if chosen[0] == "burdens":
                engine._spend_resource(eater, BURDEN, 2, SHARED)
            else:
                engine._spend_resource(eater, RESONANCE, 4, SHARED)
            eater.reaction_available = False
            engine._append_event("REACTION_RESOLVED", SHARED, actor_id=eater.entity_id, target_ids=(subject.entity_id,),
                                 payload={"checkpoint": "CONDITION", "reaction_name": "Shared Burden (Hold the Door)"})
            engine._apply_condition(subject, HOLD, SHARED, eater.entity_id, expires_on="UNTIL_REMOVED",
                                    data={**st.delay_condition(ctx, effect_row, name), "turn": int(subject.turns_started),
                                          "label": f"Hold the Door: becoming {name.title()} waits until the end of its next turn"})
            field_answer(engine, eater, subject, ctx.intent)
            return False
    return None


@hook("turn_end")
def door_opens(engine: Any, actor: Any) -> None:
    for held in [c for c in actor.conditions.values() if c.condition_id == HOLD]:
        if actor.turns_started > int((held.data or {}).get("turn") or 0):
            data = dict(held.data or {})
            st.remove(engine, actor, held, "RESOLVED")
            if st.land_delayed_condition(engine, actor, data):
                note(engine, SHARED, actor, f"The held door opens: {actor.display_name} becomes {str(data.get('condition')).title()}.")
            else:
                note(engine, SHARED, actor, f"Hold the Door: the creature that would have {data.get('condition')} {actor.display_name} is gone.")


# ---------------------------------------------------------------------------------------------------------- Weight of Mourning
def _positive_harm_events(engine: Any, source: Any) -> list[Any]:
    """Direct damage by source, used for the scene-long Empty Chair relationship."""
    return [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == source.entity_id
            and int((e.payload or {}).get("hp_damage") or 0) + int((e.payload or {}).get("temporary_hp_absorbed") or 0) > 0]


def _qualifying_weight_event(engine: Any, eater: Any, target: Any) -> Any | None:
    """Latest visible damage act meeting Weight's printed ally-harm or drop requirement."""
    if target.team_id == eater.team_id:
        return None
    for event in reversed(engine.events):
        if event.event_type != "DAMAGE_COMMITTED" or event.actor_id != target.entity_id:
            continue
        payload = event.payload or {}
        victim = engine.state.actors.get(next(iter(event.target_ids or ()), ""))
        if victim is None:
            continue
        harmed = int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) > 0
        newly_dropped = int(payload.get("hp_before") or 0) > 0 and int(payload.get("remaining_hp") or 0) == 0
        if newly_dropped or (victim is not eater and victim.team_id == eater.team_id and harmed):
            return event
    return None


def _weight_witnesses(engine: Any, target: Any, qualifying_event: Any) -> list[str]:
    """All directly harmed creatures in the one qualifying native intent."""
    intent_id = qualifying_event.trigger_or_intent_id
    return list(dict.fromkeys(tid for event in engine.events
                              if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == target.entity_id
                              and event.trigger_or_intent_id == intent_id
                              and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
                              for tid in (event.target_ids or ())))


def _qualifies(engine: Any, eater: Any, target: Any) -> bool:
    """The printed requirement, as far as the table sees: it damaged one of your allies, or dropped a creature to 0 Hit Points,
    this fight (killing an Asset, emotional harm or a grief stain is the GM's)."""
    return _qualifying_weight_event(engine, eater, target) is not None


def _mourning(creature: Any) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == MOURNING), None)


@effect("grief_weight")
def weight(ctx: Any, row: dict[str, Any]) -> None:
    engine, eater, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    failed = st.save(ctx, target, "cha", on_success=[
        {"type": "speed", "applies_to": "target", "flat": -10, "duration": {"kind": "until_end_of_next_turn"},
         "evidence": "Its Speed is reduced by 10 feet ... until the end of its next turn"},
        {"type": "spiritual_pressure", "applies_to": "target", "evidence": "and it suffers one Spiritual Pressure effect"}])
    if not failed or not target.active:
        return
    held = _mourning(target)
    if held is not None:
        st.remove(engine, target, held, "REPLACED")
    engine._apply_condition(target, MOURNING, ctx.source, eater.entity_id, expires_on="UNTIL_REMOVED",
                            data={"harmed": _weight_witnesses(engine, target, _qualifying_weight_event(engine, eater, target)),
                                  "successes": 0, "rule": {"no_reactions": True},
                                  "label": "Mourning Weight: half Speed, no Reactions, Disadvantage against those it harmed, Psychic when it acts against them"})
    _te().run_effects(st.context(engine, eater, ctx.action, [target], ctx.numbers, ctx.intent),
                      [{"type": "exposed", "applies_to": "target", "duration": "until_removed", "benefits": "hidden", "against": "you",
                        "evidence": "it cannot become Hidden from you"}])
    note(engine, WEIGHT, eater, f"{target.display_name} carries the Weight of Mourning.", (target,))


def _end_weight(engine: Any, target: Any, held: Any) -> None:
    owner = held.source_actor_id
    st.remove(engine, target, held, "LIFTED")
    for condition in [c for c in target.conditions.values() if c.condition_id.startswith("condition:typed.exposed") and c.source_actor_id == owner
                      and c.source_definition_id == held.source_definition_id]:
        st.remove(engine, target, condition, "LIFTED")


@hook("turn_end")
def weight_repeat(engine: Any, actor: Any) -> None:
    held = _mourning(actor)
    if held is None or not actor.active:
        return
    owner = engine.state.actors.get(held.source_actor_id or "")
    if owner is None:
        return
    ctx = st.context(engine, owner, st.feature_action(engine, owner, WEIGHT), [actor], st.numbers(engine, owner))
    if st.save(ctx, actor, "cha"):
        return
    successes = int(st.data_of(actor, held).get("successes") or 0) + 1
    st.set_data(actor, held, successes=successes)
    if successes >= 2:  # "until it completes two successful saves at the end of its turns"
        _end_weight(engine, actor, held)


@hook("speed")
def weight_speed(engine: Any, actor: Any) -> int | None:
    return -(int(actor.speed_ft) // 2) if _mourning(actor) is not None else None


@hook("before_attack")
def weight_disadvantage(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    held = _mourning(attacker) if attacker is not None else None
    if held is None or defender is None or defender.entity_id not in ((held.data or {}).get("harmed") or []):
        return None
    return {"mode": "DISADVANTAGE"}  # "Disadvantage on attacks against creatures directly harmed by the qualifying act"


@hook("masked_conditions")
def mourning_concealment(engine: Any, viewer: Any, target: Any) -> dict[str, Any] | None:
    """Weight and Empty Chair suppress ordinary Hidden/Invisible only for their harmed witnesses."""
    if viewer is None or target is None or getattr(viewer, "perception_cell", False) or getattr(target, "perception_cell", False):
        return None
    hidden_ids = {"condition:typed.hidden"}
    invisible_id = "condition:typed.invisible"
    masks: set[str] = set()
    held = _mourning(target)
    if held is not None and (viewer.entity_id == held.source_actor_id or
                             viewer.entity_id in ((held.data or {}).get("harmed") or [])):
        masks.update(iid for iid, condition in target.conditions.items() if condition.condition_id in hidden_ids)
    if viewer.entity_id not in {tid for event in _positive_harm_events(engine, target) for tid in (event.target_ids or ())}:
        return {target.entity_id: masks} if masks else None
    for owner in engine.state.actors.values():
        field = _field(owner)
        if field is None or "empty_chair" not in ((field.data or {}).get("offices") or []) or not owner.active:
            continue
        # The Office confines the hostile creature, not the creatures it harmed, to the field.
        if target.team_id == owner.team_id or not _in_field(engine, owner, target):
            continue
        masks.update(iid for iid, condition in target.conditions.items() if condition.condition_id == invisible_id)
    return {target.entity_id: masks} if masks else None


# ---------------------------------------------------------------------------------------------------------- acting against us
def _activation(engine: Any, actor: Any) -> list[Any]:
    for index in range(len(engine.events) - 1, -1, -1):
        if engine.events[index].event_type == "INTENT_ACCEPTED" and engine.events[index].actor_id == actor.entity_id:
            return engine.events[index:]
    return []


@hook("action_completed")
def acted_against(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    if actor is None or not actor.active:
        return
    held = _mourning(actor)
    events = None
    if held is not None and actor.turn_flags.get("mourning_weight_hit") is None:
        owner = engine.state.actors.get(held.source_actor_id or "")
        events = _activation(engine, actor)
        struck = owner is not None and any(
            e.event_type in ("ATTACK_ROLLED", "SAVE_ROLLED", "DAMAGE_COMMITTED") and any(
                (engine.state.actors.get(t) is not None and engine.state.actors[t].team_id == owner.team_id) for t in (e.target_ids or ()))
            or (e.event_type == "SAVE_ROLLED" and engine.state.actors.get(e.actor_id or "") is not None and engine.state.actors[e.actor_id].team_id == owner.team_id)
            for e in events)
        if struck:
            actor.turn_flags["mourning_weight_hit"] = True  # "the first time each turn it uses a hostile feature"
            pb = int(st.numbers(engine, owner).get("pb") or 2)
            _te().run_effects(st.context(engine, owner, st.feature_action(engine, owner, WEIGHT), [actor], st.numbers(engine, owner)),
                              [{"type": "damage", "applies_to": "target", "flat": 2 * pb, "damage_types": ["psychic"],
                                "evidence": "it takes Psychic damage equal to 2 x Proficiency Bonus"}])
    for owner in engine.state.actors.values():
        field = _field(owner)
        if field is None or "funeral_bell" not in ((field.data or {}).get("offices") or []) or actor.team_id == owner.team_id or not _in_field(engine, owner, actor):
            continue
        token = f"funeral_bell_round_{owner.entity_id}"
        if actor.turn_flags.get(token) == engine.state.round_number:
            continue
        events = events if events is not None else _activation(engine, actor)
        if any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == actor.entity_id and str((e.payload or {}).get("damage_type") or "").upper() in ("PSYCHIC", "NECROTIC")
               and int((e.payload or {}).get("hp_damage") or 0) > 0 for e in events):
            actor.turn_flags[token] = engine.state.round_number  # "The first time each round"
            numbers = st.numbers(engine, owner)
            _te().run_effects(st.context(engine, owner, engine.action_catalog.get(field.source_definition_id) or st.feature_action(engine, owner, VESSEL),
                                         [actor], numbers),
                              [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                "evidence": "it becomes Resonance Marked by you"},
                               {"type": "damage", "applies_to": "target", "flat": int(numbers.get("pb") or 2), "damage_types": ["psychic"],
                                "evidence": "and takes Psychic damage equal to your Proficiency Bonus"}])


# ---------------------------------------------------------------------------------------------------------- the Mourning Field
def _field(owner: Any) -> Any:
    return next((c for c in owner.conditions.values() if c.condition_id == FIELD and c.source_actor_id == owner.entity_id), None)


def _zone(engine: Any, owner: Any) -> Any:
    from .. import zones

    field = _field(owner)
    if field is None:
        return None
    return next((z for z in zones.typed_zones(engine) if z.owner_id == owner.entity_id and z.source_definition_id == field.source_definition_id), None)


def _in_field(engine: Any, owner: Any, creature: Any) -> bool:
    zone = _zone(engine, owner)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _sheltered(engine: Any, creature: Any) -> list[Any]:
    """Field owners whose chosen allies include this creature, standing in their field."""
    return [owner for owner in engine.state.actors.values() if owner.active and _field(owner) is not None
            and creature.entity_id in ((_field(owner).data or {}).get("allies") or []) and _in_field(engine, owner, creature)]


def field_answer(engine: Any, eater: Any, subject: Any, intent: Any) -> None:
    """"When you use Eat the Bitter Memory, Shared Burden ... to remove, suppress, absorb, or delay a meaningful hostile effect in the field,
    choose one ally in the field. It gains Temporary Hit Points equal to Wisdom modifier + Proficiency Bonus.\""""
    if _field(eater) is None or not _in_field(engine, eater, subject):
        return
    allies = [a for a in engine.state.actors.values() if a.active and a.team_id == eater.team_id and _in_field(engine, eater, a)]
    ally = st.pick_creature(engine, intent, eater, allies, checkpoint="MOURNING_FIELD_TEMP", choice_id="choice:needle.grief_eater.field_temp_hp",
                            prompt="Mourning Field: which ally in the field gains Temporary Hit Points (Wisdom + Proficiency Bonus)?", name="Vessel of Ten Thousand Sorrows",
                            feature_id=VESSEL, preferred=min(allies, key=lambda a: (a.current_hp - a.maximum_hp, a.entity_id), default=None))
    if ally is not None:
        numbers = st.numbers(engine, eater)
        engine._grant_temp_hp(ally, int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2), VESSEL, eater.entity_id)


@effect("grief_vessel")
def vessel(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, owner = ctx.engine, ctx.actor
    allies = [a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and a is not owner]
    ids = [a.entity_id for a in allies]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "MOURNING_FIELD_ALLIES", owner.entity_id), owner, "choice:needle.grief_eater.field_allies",
                        ids, labels={a.entity_id: a.display_name for a in allies}, preferred=ids, minimum=0, maximum=len(ids), default="all",
                        allow_decline=True, prompt="Mourning Field: which allies does it shelter?", name="Vessel of Ten Thousand Sorrows",
                        feature_id=VESSEL) if ids else []
    offices = {"funeral_bell": "Office of the Funeral Bell", "wake": "Office of the Wake (the GM's)", "empty_chair": "Office of the Empty Chair (the GM's)",
               "returning_names": "Office of Returning Names (the GM's)"}
    burdens = int(owner.resources.get(BURDEN, 0) or 0)
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "MOURNING_OFFICES", owner.entity_id), owner, "choice:needle.grief_eater.offices",
                        list(offices), labels=offices, preferred=["funeral_bell"], minimum=0, maximum=min(4, burdens), default="first",
                        allow_decline=True, prompt=f"Spend Sorrow Burdens (you have {burdens}): one Mourning Office each.", name="Vessel of Ten Thousand Sorrows",
                        feature_id=VESSEL) if burdens else []
    picked = [key for key in picked if key in offices][:burdens]
    if picked:
        engine._spend_resource(owner, BURDEN, len(picked), VESSEL)
    held = _field(owner)
    if held is not None:
        st.remove(engine, owner, held, "REPLACED")
    engine._apply_condition(owner, FIELD, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"allies": [a for a in chosen if a in ids], "offices": picked, "embrace_used": 0,
                                  "label": "Mourning Field: " + (", ".join(offices[k] for k in picked) if picked else "no Office")})


@hook("save")
def field_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _sheltered(ctx.engine, subject) or not (set(named or ()) & set(EMOTIONAL)):
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]}  # "Advantage on saves against Charmed, Frightened, possession ..."


@hook("incoming_damage")
def field_resistance(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    if amount <= 1 or str(damage_type).upper() != "PSYCHIC" or not _sheltered(engine, target):
        return None
    return amount - amount // 2  # Resistance to Psychic damage


def _field_holders(engine: Any) -> list[Any]:
    from .d20_rewrite import Holder

    out = []
    for owner in engine.state.actors.values():
        field = _field(owner)
        if owner.active and field is not None:
            out.append(Holder(owner, VESSEL, {"name": "Mourning Field"}, f"{VESSEL}:field", st.numbers(engine, owner)))
    return out


def _reroll_guard(engine: Any, holder: Any, rc: Any) -> bool:
    return rc.roller.entity_id in ((_field(holder.actor).data or {}).get("allies") or []) and _in_field(engine, holder.actor, rc.roller) \
        and bool(set(rc.named or ()) & set(EMOTIONAL))


def _reroll_price(engine: Any, holder: Any, rc: Any, result: Any) -> None:
    """"you may take one ordinary Spiritual Pressure effect to let it reroll"."""
    ctx = st.context(engine, holder.actor, st.feature_action(engine, holder.actor, VESSEL), [holder.actor], holder.numbers)
    _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "you take one ordinary Spiritual Pressure effect"}])


def _register_rules() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("grief_vessel_reroll", "Mourning Field (reroll for a Spiritual Pressure)", rolls=("save",), who="ally", when="failed", limit="round",
                  checkpoint="D20_REROLL_ALLY", finder=_field_holders, guard=_reroll_guard, after=_reroll_price))


_register_rules()


@hook("compile_actions")
def embrace_action(info: dict[str, Any]) -> list[Any] | None:
    if VESSEL not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.mourners_embrace", display_name="Mourner's Embrace", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=30,
        parameters={"typed": {"effects": [{"type": "grief_embrace", "applies_to": "target", "harmful": True}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": [], "source": VESSEL},
                    "expected_damage": 22, "grief_embrace": True,
                    "description": "Mourning Field (once per Field, on your turn): a hostile creature in the field bearing Mourning Weight or your "
                                   "Resonance Mark makes a Charisma save. Failed: Restrained until the end of its next turn, and it chooses one of: cease "
                                   "hostile action this turn; move toward what the grief is tied to; speak one belief about the harm; take 8d10 + your "
                                   "Wisdom modifier Psychic and two Spiritual Pressure effects. Success: half that damage and one Spiritual Pressure effect."})]


@effect("grief_embrace")
def embrace(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    field = _field(owner)
    if field is None or target is None or not target.active:
        return
    st.set_data(owner, field, embrace_used=1)  # "Once during the activation"
    numbers = ctx.numbers or st.numbers(engine, owner)
    failed = st.save(ctx, target, "cha")
    if not failed:
        amount = _roll(engine, owner, 8, 10, int(numbers.get("key_mod") or 0), VESSEL) // 2
        _te().run_effects(st.context(engine, owner, ctx.action, [target], numbers, ctx.intent),
                          [{"type": "damage", "applies_to": "target", "flat": amount, "damage_types": ["psychic"], "evidence": "half the listed damage"},
                           {"type": "spiritual_pressure", "applies_to": "target", "evidence": "and suffers one Spiritual Pressure effect"}])
        return
    sub = st.context(engine, owner, ctx.action, [target], numbers, ctx.intent)
    _te().run_effects(sub, [{"type": "condition", "applies_to": "target", "condition": "restrained", "duration": {"kind": "until_end_of_next_turn"},
                             "evidence": "It is Restrained by manifested grief until the end of its next turn"}])
    options = {"cease": "Cease hostile action for this turn", "move": "Move toward a creature, corpse, place or object tied to the grief",
               "speak": "Speak one statement it believes about the harm", "accept": "Accept 8d10 + Wisdom Psychic damage and two Spiritual Pressure effects"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "MOURNERS_EMBRACE", target.entity_id), target, "choice:needle.grief_eater.embrace",
                        list(options), labels=options, preferred=["speak"], prompt=f"Mourner's Embrace: {target.display_name} must choose one.",
                        name="Mourner's Embrace", feature_id=VESSEL, target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in options else "speak"
    if pick == "accept":
        _te().run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 10}, "formula": "key_ability_modifier",
                                 "damage_types": ["psychic"], "evidence": "8d10 + Wisdom modifier Psychic damage"},
                                {"type": "spiritual_pressure", "applies_to": "target", "evidence": "two different Spiritual Pressure effects"},
                                {"type": "spiritual_pressure", "applies_to": "target", "different": True, "evidence": "two different Spiritual Pressure effects"}])
    elif pick == "cease":
        lower = int(st.numbers(engine, owner).get("cl") or 0) - int(st.numbers(engine, target).get("cl") or 0) >= 5
        engine._apply_condition(target, "condition:typed.mourner_cease", ctx.source, owner.entity_id,
                                expires_on="UNTIL_REMOVED" if lower else "END_OF_CURRENT_TURN",
                                data={"lower": lower, "dc": int(numbers.get("save_dc") or 10),
                                      "label": "Mourner's Embrace: cease hostile action"})
    elif pick == "speak":
        note(engine, VESSEL, target, f"{target.display_name} speaks one statement it believes about the harm.")
    else:
        ctx.rider(f"Mourner's Embrace: {target.display_name} chooses to move toward what the grief is tied to; that destination is not recorded.")


@hook("candidate_allowed")
def cease_hostility(engine, actor, candidate, action):
    if action is None:
        return None
    if not _cease_hostility_active(engine, actor):
        return None
    typed = (action.parameters or {}).get("typed") or {}
    from ..effect_harm import classify_effect
    if action.target_kind == "HOSTILE_ENTITY" or action.resolution_kind in ("ATTACK", "MULTI_ATTACK") or any(classify_effect(row, recursive=True) is True for row in typed.get("effects") or []):
        return False
    return None


def _cease_hostility_active(engine, actor):
    """Whether the printed cease-hostility restriction still applies to this creature."""
    for condition in actor.conditions.values():
        if condition.condition_id != "condition:typed.mourner_cease":
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        if not (condition.data or {}).get("lower") or (owner is not None and _field(owner) is not None and _in_field(engine, owner, actor)):
            return True
    return False


@hook("opportunity_allowed")
def cease_hostility_opportunity(engine, reactor, mover):
    """A cease-hostility creature cannot make its hostile opportunity attack."""
    if _cease_hostility_active(engine, reactor):
        return False
    return None


@hook("reaction_subject_allowed")
def cease_hostility_reaction(engine, reactor, other, row):
    """Keep defensive reactions available while suppressing offensive reactions against a creature."""
    if not _cease_hostility_active(engine, reactor) or other is None:
        return None
    from ..effect_harm import classify_effect
    if any(classify_effect(effect, recursive=True) is True for effect in row.get("effects") or []):
        return False
    return None

@hook("turn_end")
def cease_repeat(engine, actor):
    for held in list(actor.conditions.values()):
        if held.condition_id != "condition:typed.mourner_cease" or not (held.data or {}).get("lower"):
            continue
        owner = engine.state.actors.get(held.source_actor_id)
        if owner is None or _field(owner) is None or not _in_field(engine, owner, actor):
            st.remove(engine, actor, held, "LEFT_FIELD")
        else:
            sub = st.context(engine, owner, st.feature_action(engine, owner, VESSEL), [actor], st.numbers(engine, owner))
            if not st.save(sub, actor, "cha"):
                st.remove(engine, actor, held, "SUCCESSFUL_SAVE")

@hook("movement_step")
def cease_leaves_field(engine, mover, previous, destination, intent):
    for held in list(mover.conditions.values()):
        if held.condition_id == "condition:typed.mourner_cease":
            owner = engine.state.actors.get(held.source_actor_id)
            if owner is None or _field(owner) is None or not _in_field(engine, owner, mover):
                st.remove(engine, mover, held, "LEFT_FIELD")


@hook("event", nested=True)
def cease_field_geometry_changed(engine, event_type, kwargs):
    """End a lower-CL cease-hostility condition as soon as either side leaves its Field.

    Movement receipts cover voluntary, forced and teleport movement; checking all retained
    subjects also handles the Field owner moving the zone away from them.
    """
    if event_type != "MOVEMENT_COMMITTED":
        return
    for subject in engine.state.actors.values():
        for held in list(subject.conditions.values()):
            if held.condition_id != "condition:typed.mourner_cease" or not (held.data or {}).get("lower"):
                continue
            owner = engine.state.actors.get(held.source_actor_id)
            if owner is None or _field(owner) is None or not _in_field(engine, owner, subject):
                st.remove(engine, subject, held, "LEFT_FIELD")
