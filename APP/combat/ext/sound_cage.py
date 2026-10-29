"""Sonic Cage's repeat save and Thunder rider, using existing effects/event/turn hooks.

``sound_cage_repeat`` follows the ordinary Restrained effect and records its instance
and DC. Only this new typed row opts in; old saved cages keep their core repeat save.
Thunder damage actually taken (including Temporary HP) leaves a source-specific
pending condition. It affects one save against that caster's cage, never other CON
saves. Its integer deadline is the holder's next turn; turn_end removes it after
the repeat save, and loss of the linked restraint removes both tracking conditions.
Tracking conditions use UNTIL_REMOVED: their lifetime follows the linked restraint,
so they cannot be deleted twice by a concentration/expiry sweep's captured list.
All stored data is evented; no methods or functions are patched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, run
from ..typed_executor import Context

FEATURE = "TAL_SOUND_SONIC_CAGE"
REPEAT = "condition:typed.sonic_cage_repeat"
THUNDER = "condition:typed.sonic_cage_thunder"
RESTRAINED = "condition:typed.restrained"


def remove_instance(engine: Any, actor: Any, condition: Any) -> None:
    if actor.conditions.pop(condition.instance_id, None) is not None:
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id,
                             actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id,
                                      "instance_id": condition.instance_id})


def linked(actor: Any, condition: Any) -> Any:
    held = actor.conditions.get(condition.data.get("restrained_id"))
    return held if held is not None and held.condition_id == RESTRAINED \
        and held.source_actor_id == condition.source_actor_id \
        and held.source_definition_id == condition.source_definition_id else None


@effect("sound_cage_repeat")
def track_cage(ctx: Context, eff: dict[str, Any]) -> None:
    if ctx.typed.get("source") != FEATURE or ctx.target is None:
        return
    # The immediately preceding ordinary condition effect owns immunity/reactions.
    held = [c for c in ctx.target.conditions.values() if c.condition_id == RESTRAINED
            and c.source_actor_id == ctx.actor.entity_id and c.source_definition_id == ctx.source
            and c.applied_sequence > int(ctx.damage_cache.get("_cage_before", -1))]
    if not held:
        return
    restraint = max(held, key=lambda c: c.applied_sequence)
    if any(c.condition_id == REPEAT and c.data.get("restrained_id") == restraint.instance_id
           for c in ctx.target.conditions.values()):
        return
    ctx.engine._apply_condition(ctx.target, REPEAT, ctx.source, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED",
                                data={"restrained_id": restraint.instance_id,
                                      "dc": int(ctx.numbers.get("save_dc") or 10)})


@hook("event")
def cage_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type in {"CONDITION_REMOVED", "ENTITY_DEFEATED"}:
        for actor in engine.state.actors.values():
            for condition in list(actor.conditions.values()):
                if condition.condition_id in {REPEAT, THUNDER} and (not actor.active or not linked(actor, condition)):
                    remove_instance(engine, actor, condition)
        return
    if event_type != "DAMAGE_COMMITTED" or str(payload.get("damage_type")).upper() != "THUNDER" \
            or int(payload.get("reduced_to") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or not actor.active:
            continue
        for cage in list(actor.conditions.values()):
            if cage.condition_id != REPEAT or not linked(actor, cage):
                continue
            for old in list(actor.conditions.values()):
                if old.condition_id == THUNDER and old.data.get("restrained_id") == cage.data["restrained_id"]:
                    remove_instance(engine, actor, old)
            engine._apply_condition(actor, THUNDER, cage.source_definition_id, cage.source_actor_id,
                                    expires_on="UNTIL_REMOVED",
                                    data={"restrained_id": cage.data["restrained_id"],
                                          "deadline": int(actor.turns_started) + 1})


def pending(actor: Any, source_actor_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == THUNDER
            and c.source_actor_id == source_actor_id and linked(actor, c)
            and int(c.data["deadline"]) >= actor.turns_started]


@hook("save")
def cage_save_mode(ctx: Context, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx.typed.get("source") == FEATURE:
        ctx.damage_cache["_cage_before"] = int(ctx.engine.state.event_sequence)
        if pending(subject, ctx.actor.entity_id):
            return {"modes": ["DISADVANTAGE"]}
    return None


@hook("after_save")
def consume_thunder(ctx: Context, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if ctx.typed.get("source") == FEATURE:
        for condition in pending(subject, ctx.actor.entity_id):
            remove_instance(ctx.engine, subject, condition)


@hook("turn_end")
def repeat_cage_save(engine: Any, actor: Any) -> None:
    for cage in list(actor.conditions.values()):
        if cage.condition_id != REPEAT:
            continue
        restraint = linked(actor, cage)
        caster = engine.state.actors.get(cage.source_actor_id)
        action = engine.action_catalog.get(cage.source_definition_id)
        if restraint is None or not actor.active or caster is None or action is None:
            remove_instance(engine, actor, cage)
            continue
        ctx = Context(engine, caster, action, engine._active_intent,
                      action.parameters["typed"], [actor], actor, {})
        modes: set[str] = set()
        bonus = 0
        for extra in run("save", ctx, actor, "CON", {"restrained"}):
            bonus += int(extra.get("bonus") or 0)
            modes.update(extra.get("modes") or ())
        dc = int(cage.data["dc"]) - bonus
        roll = engine._roll_save(actor, "CON", dc, cage.source_definition_id,
                                 extra_mode=next(iter(modes)) if len(modes) == 1 else None)
        failed = roll.total < dc
        run("after_save", ctx, actor, "CON", {"restrained"}, failed)
        if not failed:
            remove_instance(engine, actor, restraint)
            remove_instance(engine, actor, cage)
    for condition in list(actor.conditions.values()):
        if condition.condition_id == THUNDER and (not linked(actor, condition)
                or not actor.active or int(condition.data["deadline"]) <= actor.turns_started):
            remove_instance(engine, actor, condition)


@hook("nominal_slot_boundary")
def nominal_thunder(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint != "END_OF_TURN":
        return
    from .effect_durations import custom_turn_due
    for condition in list(actor.conditions.values()):
        if condition.condition_id == THUNDER and custom_turn_due(actor, condition.data["deadline"],
                actor.turn_flags, condition.instance_id, nominal=True):
            remove_instance(engine, actor, condition)
