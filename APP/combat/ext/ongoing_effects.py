"""Explicit ongoing effects with one shared repeat save.

A condition holds the whole effect, so a successful repeat save or lost Concentration
ends its restrictions and its turn-start payload together. Reapplying an unmarked
condition from the same action and creature refreshes that source-owned instance.
Only reviewed typings that explicitly opt into the ``ongoing`` block use this path.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook


@effect("ongoing")
def apply_ongoing(ctx: Any, effect: dict[str, Any]) -> None:
    from ..typed_executor import CONDITION_PREFIX, _default_subject, condition_immune, effect_expiry, mark_condition_id, rules
    from .. import typed_reactions

    for subject in _default_subject(ctx, effect, harmful=True):
        name = str(effect.get("base_condition") or effect.get("condition") or "")
        # Immune creatures, and a Reaction answering "a condition is about to be gained", stop it (sw-lightning review).
        if not effect.get("base_condition") and name and (condition_immune(ctx.engine, subject, name) or
                                                          typed_reactions.offer_condition_gained(ctx.engine, subject, ctx.actor, name)):
            continue
        data = {"rule": copy.deepcopy(effect.get("rule") or {}),
                # A slow the effect states ("Speed is reduced by 10 feet") lives in the condition (typed_executor._effective_speed).
                "speed_delta": int(effect.get("speed_delta") or 0),
                "ongoing_effects": copy.deepcopy(effect.get("turn_start_effects") or []),
                "numbers": dict(ctx.numbers), "damage_save": effect.get("damage_save"),
                "damage_save_exclude_source": effect.get("damage_save_exclude_source"),
                "damage_save_exclude_summons": list(effect.get("damage_save_exclude_summons") or [])}
        if effect.get("repeat_save"):
            data["repeat_save"] = {**effect["repeat_save"], "dc": int(ctx.numbers.get("save_dc") or 10)}
        base_condition = effect.get("base_condition")
        if base_condition and not condition_immune(ctx.engine, subject, base_condition) and not \
                typed_reactions.offer_condition_gained(ctx.engine, subject, ctx.actor, base_condition):
            data["rule"] = {**rules()["conditions"][base_condition], **data["rule"]}
        condition_id = (mark_condition_id(effect["mark"], ctx.actor.entity_id) if effect.get("mark")
                        else CONDITION_PREFIX + str(effect["condition"]))
        if effect.get("mark"):
            ctx.engine._remove_condition(subject, condition_id, ctx.source)
        else:
            # Reapplying the same unmarked ongoing condition from the same
            # action/source refreshes that effect instead of stacking ticks.
            for iid, old in list(subject.conditions.items()):
                if (old.condition_id == condition_id
                        and old.source_definition_id == ctx.source
                        and old.source_actor_id == ctx.actor.entity_id):
                    subject.conditions.pop(iid)
                    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id,
                                             target_ids=(subject.entity_id,),
                                             payload={"condition_id": condition_id, "instance_id": iid,
                                                      "reason": "REFRESHED"})
        ctx.engine._apply_condition(subject, condition_id, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, effect, subject, condition=True), data=data)
        if data["rule"].get("no_reactions"):
            subject.reaction_available = False


@hook("turn_start")
def ongoing_turn_start(engine: Any, actor: Any) -> None:
    from ..typed_executor import Context, is_active_typed_condition, run_effects

    for condition in list(actor.conditions.values()):
        if not is_active_typed_condition(condition):
            continue
        data = condition.data or {}
        effects = data.get("ongoing_effects")
        source = engine.state.actors.get(condition.source_actor_id)
        action = engine.action_catalog.get(condition.source_definition_id)
        if not effects or source is None or action is None or not actor.active:
            continue
        typed = {"numbers": data["numbers"], "duration": {"kind": "instant"}, "effects": effects}
        run_effects(Context(engine, source, action, None, typed, [actor], actor, {}), effects)


@hook("event", nested=True)
def ongoing_damage_save(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    from ..typed_executor import is_active_typed_condition

    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None or not target.active:
            continue
        for condition in list(target.conditions.values()):
            if not is_active_typed_condition(condition):
                continue
            data = condition.data or {}
            when, repeat = data.get("damage_save"), data.get("repeat_save") or {}
            if not when or not repeat:
                continue
            attacker = engine.state.actors.get(kwargs.get("actor_id"))
            if when == "creature" and attacker is None:
                continue
            if data.get("damage_save_exclude_source") and kwargs.get("actor_id") == condition.source_actor_id:
                continue
            if attacker is not None and (attacker.summon or {}).get("owner") == condition.source_actor_id and \
                    (attacker.summon or {}).get("source") in data.get("damage_save_exclude_summons", []):
                continue
            # "Another creature" refers to the damaging actor, including damage
            # from that creature's ongoing effect. Ability identity is not a
            # printed exception; explicit caster exclusions are handled above.
            if when == "another_creature" and (attacker is None or attacker.entity_id == target_id):
                continue
            roll = engine._roll_save(target, str(repeat["ability"]), int(repeat["dc"]),
                                     condition.source_definition_id, extra_mode="ADVANTAGE")
            if roll.total >= int(repeat["dc"]):
                # Another caster can maintain the same named effect on this target.
                removed = target.conditions.pop(condition.instance_id, None)
                if removed is not None:
                    engine._append_event("CONDITION_REMOVED", condition.source_definition_id,
                                         actor_id=condition.source_actor_id, target_ids=(target_id,),
                                         payload={"condition_id": condition.condition_id,
                                                  "instance_id": condition.instance_id, "repeat_save": True})
