"""Analyze's learned-characteristic record and Modify Characteristics (lane 14).

Records individual runtime characteristics, selected by the player after a
successful Analyze. No entire resistance category is revealed by one choice.
Eligible AC, walking-Speed, save, sense and resistance modifications use evented
modifiers; the newest replaces this Eye's previous modification only.
Ability scores and immunity replacement require additional runtime
stat/defense support and stay printed riders. Hooks: analyze_checked,
save_bonus (every saving throw, typed or legacy) and sense_range.
Shared with riders14_eye for learned characteristics and maximum_hp_riders for
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


def learn(engine: Any, actor: Any, target: Any, count: int = 1) -> None:
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
        learn(engine, actor, target, count + extra)


def modification_options(actor: Any, target: Any) -> list[str]:
    """Previously learned individual runtime characteristics, shared with maximum_hp_riders."""
    return list(dict.fromkeys(str(c.data.get('name')) for c in actor.conditions.values()
                             if c.condition_id == KNOWN and c.data.get('target_id') == target.entity_id))


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
