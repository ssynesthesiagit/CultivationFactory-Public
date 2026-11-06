"""Analyze's learned-characteristic record and Modify Characteristics (lane 14).

Records individual runtime characteristics, selected by the player after a
successful Analyze. No entire resistance category is revealed by one choice.
Eligible AC, walking-Speed, save, sense and resistance modifications use evented
modifiers; the newest replaces this Eye's previous modification only.
Ability scores and immunity replacement require additional runtime
stat/defense support and stay printed riders. Hooks: analyze_checked,
save_bonus (every saving throw, typed or legacy) and sense_range.
Shared with mind_hidden_eye.record_characteristic for explicit learning
notifications, riders14_eye for learned characteristics and maximum_hp_riders for
the single critical-hit Modify Characteristics choice and payment.
"""
from __future__ import annotations

from typing import Any

from . import hook
from .riders14_eye import COURT, has, held
from .eye_common import FOCUS, numbers_of
from .mind_hidden_eye import analyzed_by
from .condition_events import drop_condition as _drop

KNOWN = "condition:typed.eye_known_characteristic"
MODIFIED = "condition:typed.eye_modified_save"
SOURCE = "talent:eye.modify_characteristics"
CREATURE_TYPE = "Creature Type"
NATURE_REASON = "CHECK:analyze:nature"  # riders14_eye.chosen_analyze_roll's reason for a Nature roll


def characteristics(engine: Any, target: Any) -> dict[str, Any]:
    out = {"Armor Class": target.armor_class, "Walking Speed": engine._effective_speed(target)}
    out.update({f"{ability} saving throw": bonus for ability, bonus in target.saving_throws.items()})
    # Single entries only; conditional defenses and GM-hidden characteristics
    # remain information the GM must qualify, rather than guessed resistance.
    kinds = {str(k).upper() for k in target.damage_resistances}
    kinds.update(str(m.value).upper() for m in target.modifiers.values() if m.target_field == "damage_resistance")
    for kind in kinds:
        out[f"{kind} Resistance"] = kind
    from .. import senses

    out.update({f"{sense} Sense": row["range_ft"] for sense, row in senses.of(engine, target).items()})
    return out


def learn(engine: Any, actor: Any, target: Any, count: int = 1, *, notify: bool = True) -> list[str]:
    """The selected individual facts are evented; narrative characteristics stay GM choices."""
    from .needle import CHOICE, ask, checkpoint_id
    from .analyze_readings import characteristic_label

    available = characteristics(engine, target)
    options = [*available, *[f"GM information {n + 1}" for n in range(count)]]
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "EYE_LEARN", actor.entity_id, target.entity_id), actor,
                 CHOICE + "eye_learn", options, minimum=count, maximum=count,
                 name="Analyze: learn characteristics", feature_id="TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES", labels={key: characteristic_label(key) for key in options},
                 prompt=f"Analyze: learn {count} characteristic(s) of {target.display_name}", target_id=target.entity_id)
    for name in picked:
        if name in available:
            for iid, old in list(actor.conditions.items()):
                if old.condition_id == KNOWN and (old.data or {}).get("target_id") == target.entity_id and (old.data or {}).get("name") == name:
                    _drop(engine, actor, iid, "passive:eye.knowledge")
            engine._apply_condition(actor, KNOWN, "passive:eye.knowledge", actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"target_id": target.entity_id, "name": name, "value": available[name]})
        else:
            engine._append_event("GM_RIDER", "passive:eye.knowledge", actor_id=actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"rider": "Choose one narrative Analyzable Characteristic with the GM."})
    # GM selections request a fact; they do not confirm that one was learned.
    learned = [name for name in picked if name in available]
    if notify:
        notice_profiling(engine, actor, target, learned)
    return learned


@hook("analyze_checked")
def learn_characteristic(engine: Any, actor: Any, target: Any, payload: dict[str, Any]) -> None:
    if actor is None or not has(engine, actor, "analysis_limits"):
        return
    if not payload.get("success"):
        return
    count = 1
    if has(engine, actor, "thorough_analysis"):
        count += int(numbers_of(engine, actor).get("pb") or 2) // 2
    rolled = payload.get("actor") or {}
    if has(engine, actor, "folklorist") and int(rolled.get("total") or 0) >= int(payload.get("dc") or 0) + 5:
        count += 1
    if target is not None:
        domain = held(actor, COURT)
        extra = int(domain is not None and engine._distance_actor_to_actor(actor, target) <= 60)
        learned = learn(engine, actor, target, count + extra, notify=False)
        if has(engine, actor, "biological_insight") and rolled.get("reason") == NATURE_REASON:
            learned += learn_creature_type(engine, actor, target, notify=False)
        # One attempt includes its counted and free facts before offering payment.
        notice_profiling(engine, actor, target, learned)


def learn_creature_type(engine: Any, actor: Any, target: Any, *, notify: bool = True) -> list[str]:
    """Biological Insight: a successful Nature Analyze learns the target's printed creature type for free.

    The fact is not one of the counted picks above and is recorded without a prompt. A target with no printed
    creature type yields nothing, so the table never invents one.
    """
    from ..creature_types import types_for

    kinds = types_for(target)
    if not kinds:
        return []
    for iid, old in list(actor.conditions.items()):
        if old.condition_id == KNOWN and (old.data or {}).get("target_id") == target.entity_id and (old.data or {}).get("name") == CREATURE_TYPE:
            _drop(engine, actor, iid, "passive:eye.knowledge")
    engine._apply_condition(actor, KNOWN, "passive:eye.knowledge", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"target_id": target.entity_id, "name": CREATURE_TYPE, "value": ", ".join(kinds), "free": True})
    if notify:
        notice_profiling(engine, actor, target, [CREATURE_TYPE])
    return [CREATURE_TYPE]


NOTICE_RANGE = 120
NOTICE = "condition:typed.eye_notice"
NOTICE_CHOICE = "eye_profile"
NOTICE_LIMIT = "Notice Profiling does not detect ordinary observation, guessing, or knowledge a creature possessed before entering range."


def notice_profiling(engine: Any, learner: Any, owner: Any, names: Any) -> None:
    """Notice Profiling: an explicit learn of the owner's characteristics within 120 feet is known to the owner while
    the owner holds Martial Focus. The owner may then expend that Focus to learn which of its characteristics were
    learned this round and by which creatures in range.

    Shared notification for counted/free Analyze facts and mind_hidden_eye's
    public recorded-learning path. Call only after an explicit fact is learned,
    never for an Analyzed mark or an unconfirmed narrative selection.
    Knowledge is held as one evented condition per owner, expiring at the next round's first slot. It is not a separate event type, so saved
    fights replay through the existing condition events. Only explicit learns are recorded, so ordinary observation,
    guessing, and older knowledge are not detected by construction.
    """
    from .needle import CHOICE, ask, checkpoint_id
    from .analyze_readings import characteristic_label
    from . import ai_controlled
    from .choice_costs import Payment

    names = list(names or ())
    if learner is owner or not names or not has(engine, owner, "notice_profiling") or owner.resources.get(FOCUS, 0) < 1:
        return
    if engine._distance_actor_to_actor(learner, owner) > NOTICE_RANGE:
        return
    round_number = engine.state.round_number
    labels = [characteristic_label(name) for name in dict.fromkeys(names)]
    notes = _notice_state(owner, round_number)
    notes["notices"].append({"learner": learner.entity_id, "learner_name": learner.display_name, "characteristics": labels})
    # A previous payment revealed a snapshot, not later facts learned after
    # Focus was regained. Keep that paid answer, but ask again for the new one.
    notes["revealed"] = False
    _set_notice_state(engine, owner, round_number, notes)
    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return
    action = engine.action_catalog.get(getattr(engine, "_active_action_source_id", None))
    action_name = action.display_name if action is not None else "a feature that learns characteristics"
    payment = Payment(FOCUS, 1)
    picked = ask(engine, intent, checkpoint_id(engine, "EYE_PROFILE", owner.entity_id, learner.entity_id), owner,
                 CHOICE + NOTICE_CHOICE, ["profile"], allow_decline=True,
                 automatic=ai_controlled(engine, owner), preferred=["profile"],
                 name="Notice Profiling", feature_id="TAL_THE_HIDDEN_EYE_NOTICE_PROFILING",
                 labels={"profile": "Expend Martial Focus to reveal this round's learned characteristics"},
                 target_id=owner.entity_id, payment=payment,
                 # The table must not append the learner's identity before payment.
                 prompt_context={"action_name": action_name, "action_actor_id": ""},
                 prompt=f"Notice Profiling: {action_name} learned a characteristic about you within 120 feet. "
                        "Expend Martial Focus (your combat readiness) to learn which of your characteristics were learned "
                        "this round and which creatures learned them? Declining keeps your Focus and reveals no details.")
    if not picked:
        return
    # AI deliberately prefers the information it can sense through this talent.
    payment.pay(engine, owner, "passive:eye.notice_profiling")
    notes = _notice_state(owner, round_number)
    notes["revealed"] = True
    notes["revealed_notices"] = list(notes["notices"])
    _set_notice_state(engine, owner, round_number, notes)


def _notice_state(owner: Any, round_number: int) -> dict[str, Any]:
    """This round's notices (empty for an earlier round), as stored on the owner's condition."""
    current = next((c for c in owner.conditions.values() if c.condition_id == NOTICE), None)
    data = dict(current.data) if current is not None else {}
    if current is None or int(data.get("round") or 0) != round_number:
        return {"round": round_number, "notices": [], "revealed": False, "revealed_notices": []}
    notices = list(data.get("notices") or [])
    # Older paid trackers predate snapshots; their existing answer is retained.
    revealed = data.get("revealed_notices", notices if data.get("revealed") else [])
    return {"round": round_number, "notices": notices, "revealed": bool(data.get("revealed")),
            "revealed_notices": list(revealed or [])}


def _set_notice_state(engine: Any, owner: Any, round_number: int, state: dict[str, Any]) -> None:
    for iid, old in list(owner.conditions.items()):
        if old.condition_id == NOTICE:
            _drop(engine, owner, iid, "passive:eye.notice_profiling")
    from .effect_durations import SLOT_AT

    data = dict(state)
    if data.get("revealed_notices"):
        result = "; ".join(f"{row['learner_name']} learned {', '.join(row['characteristics'])}"
                           for row in data["revealed_notices"])
        data["label"] = f"Notice Profiling — this round: {result}."
        data["reading"] = "You expended Martial Focus to reveal these details. This record ends when the next round starts. " + NOTICE_LIMIT
        if not data.get("revealed"):
            data["reading"] += " Another characteristic was learned; its details have not been revealed."
    else:
        data["label"] = "Notice Profiling: a characteristic about you was learned this round."
        data["reading"] = "Details have not been revealed. Expend Martial Focus when notified to identify the learners and characteristics. This record ends when the next round starts. " + NOTICE_LIMIT
    engine._apply_condition(owner, NOTICE, "passive:eye.notice_profiling", owner.entity_id,
                            expires_on=f"{SLOT_AT}:{round_number + 1}:0", data=data)


@hook("turn_start")
def expire_legacy_notices(engine: Any, actor: Any) -> None:
    """Old saved Notice trackers used UNTIL_REMOVED; expire those at the round boundary too.

    Only this ability's stored condition qualifies. Fresh records use the shared
    slot clock and have normally already expired before this hook runs.
    """
    for owner in engine.state.actors.values():
        for iid, condition in list(owner.conditions.items()):
            if condition.condition_id == NOTICE and int((condition.data or {}).get("round") or 0) < engine.state.round_number:
                _drop(engine, owner, iid, "passive:eye.notice_profiling")


@hook("status_description")
def notice_status(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Name this evented record's ability and deadline without disclosing unpaid facts."""
    if row.get("condition_id") != NOTICE:
        return None
    return {"source_ability": "Notice Profiling", "duration": "until the next round starts",
            "handling": "The table records explicit learned facts; narrative characteristics require GM confirmation."}


def modification_options(actor: Any, target: Any) -> list[str]:
    """Previously learned individual runtime characteristics, shared with maximum_hp_riders.

    Free facts (Biological Insight's creature type) are information only, so they are never a modification.
    """
    return list(dict.fromkeys(str(c.data.get('name')) for c in actor.conditions.values()
                             if c.condition_id == KNOWN and c.data.get('target_id') == target.entity_id
                             and not (c.data or {}).get("free")))


def clear_modification(engine: Any, actor: Any, target: Any) -> None:
    """Replace this Eye's earlier modification, shared by every modification choice."""
    # This source prefix is stable and scoped by the caster, avoiding another
    # cultivator's independent use or an unrelated AC/Speed effect.
    source = f"{SOURCE}.{actor.entity_id}"
    for mid, modifier in list(target.modifiers.items()):
        if modifier.source_definition_id == source:
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REPLACED"})
    for iid, old in list(target.conditions.items()):
        if old.condition_id == MODIFIED and old.source_actor_id == actor.entity_id:
            _drop(engine, target, iid, source)


def apply_modification(ctx: Any, target: Any, name: str) -> None:
    """Apply one paid, known characteristic choice; maximum_hp_riders owns payment."""
    from ..typed_executor import Context, run_effects
    engine, actor = ctx.engine, ctx.actor
    source = f'{SOURCE}.{actor.entity_id}'
    action = ctx.action.model_copy(update={"source_definition_id": source})
    modified_ctx = Context(engine, actor, action, ctx.intent, {"numbers": ctx.numbers, "duration": {"kind": "hours", "amount": 1}}, [target], target)
    common = {"applies_to": "target", "duration": "one_hour"}
    if name == "Armor Class":
        run_effects(modified_ctx, [{**common, "type": "ac_bonus", "flat": -2}])
    elif name == "Walking Speed":
        run_effects(modified_ctx, [{**common, "type": "speed", "flat": -10}])
    elif name.endswith(" saving throw"):
        from ..typed_executor import effect_expiry
        engine._apply_condition(target, MODIFIED, source, actor.entity_id,
            expires_on=effect_expiry(modified_ctx, common, target), data={"ability": name[:3], "penalty": 2})
    elif name.endswith(" Resistance"):
        run_effects(modified_ctx, [{**common, "type": "suppress_resistance", "damage_types": [name.removesuffix(" Resistance")]}])
    elif name.endswith(" Sense"):
        from ..typed_executor import effect_expiry

        engine._add_modifier(target, source, "eye_sense_range", "ADD", name.removesuffix(" Sense"), "ALWAYS",
                             expires_on=effect_expiry(modified_ctx, common, target))


@hook("save_bonus")
def modified_saves(engine: Any, target: Any, ability: str, dc: Any, source_id: Any, intent: Any) -> int | None:
    """Apply the stored penalty to every saving throw of that ability -- typed, legacy and Concentration alike -- through the
    all-source save_bonus seam (rider lane C14; it was typed saves only, through the typed ``save`` hook)."""
    penalty = sum(int(c.data.get("penalty") or 0) for c in target.conditions.values()
                  if c.condition_id == MODIFIED and c.data.get("ability") == str(ability).upper()[:3])
    return -penalty if penalty else None


@hook("sense_range")
def modified_sense(engine: Any, actor: Any, sense: str) -> int:
    return -10 * sum(m.target_field == "eye_sense_range" and m.value == sense for m in actor.modifiers.values())
