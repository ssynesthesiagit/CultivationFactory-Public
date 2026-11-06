"""Deterministic transitions over admitted facts, with no provider or I/O calls."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .models import (
    ACTIVITY_KINDS, Activity, Actor, Condition, EngineError, Reduction, World,
    identifier, integer, require, validate_condition, validate_reduction, validate_world,
)

GM_COMMANDS = {"advance_time", "apply_condition", "remove_condition", "damage",
               "interrupt_activity", "apply_reduction", "remove_reduction"}
PLAYER_COMMANDS = {"start_activity", "cancel_activity", "spend_hit_die", "finish_recovery",
                   "take_item", "drop_item", "drink_potion"}
COMMANDS = GM_COMMANDS | PLAYER_COMMANDS
CULTIVATION_KINDS = {"cultivation", "short_rest_cultivation"}
REST_INTERRUPTS = {"initiative", "damage", "non_cantrip_spell"}


def fields(payload: dict, required: set[str], optional: set[str] | None = None) -> None:
    require(isinstance(payload, dict) and required <= payload.keys()
            and payload.keys() <= required | (optional or set()), "INVALID_COMMAND_FIELDS")


def can_act(actor: Actor) -> None:
    require(not actor.dead and actor.hp > 0, "ACTOR_CANNOT_ACT")


def idle(actor: Actor) -> None:
    can_act(actor)
    require(actor.activity is None or actor.activity.status != "active", "ACTIVITY_IN_PROGRESS")


def item_available(world: World, actor: Actor, item_id: str) -> bool:
    item = world.items.get(item_id)
    return bool(item and item.quantity > 0 and item.owner_id is None
                and item.scene_id == actor.scene_id
                and (item.visible_to is None or actor.actor_id in item.visible_to))


def _emit(events: list[dict], world: World, kind: str, actor: Actor | None = None, **data: Any) -> None:
    events.append({"kind": kind, "elapsed_seconds": world.elapsed_seconds,
                   **({"actor_id": actor.actor_id} if actor else {}), **data})


def _short_benefits(world: World, actor: Actor, events: list[dict]) -> None:
    activity = actor.activity
    assert activity is not None
    benefit_id = f"{activity.activity_id}-short-{activity.segment_index}"
    if benefit_id in activity.short_benefit_ids or actor.dead:
        return
    activity.short_benefit_ids.append(benefit_id)
    activity.short_awarded = True
    actor.recovery_activity_id = activity.activity_id
    recovered = {}
    for key, pool in actor.paths.items():
        limit = 2 if pool.path == "body" else 1
        amount = pool.maximum // 2 if pool.path == "body" else pool.cl
        gained = min(amount, pool.maximum - pool.current)
        if pool.short_recoveries < limit:
            pool.current += gained
            pool.short_recoveries += 1
            recovered[key] = gained
    _emit(events, world, "short_rest_qualified", actor, activity_id=activity.activity_id,
          benefit_id=benefit_id, segment_index=activity.segment_index, recovered=recovered)


def _cultivation_benefits(world: World, actor: Actor, events: list[dict]) -> None:
    activity = actor.activity
    assert activity is not None
    activity.cultivation_awarded = True
    recovered = {}
    for key in activity.path_ids:
        pool = actor.paths[key]
        if not pool.cultivation_used:
            recovered[key] = pool.maximum - pool.current
            pool.current = pool.maximum
            pool.cultivation_used = True
    _emit(events, world, "cultivation_completed", actor,
          activity_id=activity.activity_id, recovered=recovered)


def _long_benefits(world: World, actor: Actor, events: list[dict]) -> None:
    actor.reductions = {k: r for k, r in actor.reductions.items() if not r.ends_on_long_rest}
    actor.hp = actor.hp_max
    for dice in actor.hit_dice.values():
        dice.remaining = dice.maximum
    for pool in actor.paths.values():
        amount = pool.maximum if pool.path == "body" else pool.maximum // 2
        pool.current = min(pool.maximum, pool.current + amount)
        pool.short_recoveries = 0
        pool.cultivation_used = False
    # One level total, even when several independent sources imposed Exhaustion.
    for key in sorted(actor.conditions):
        condition = actor.conditions[key]
        if condition.kind == "exhaustion" and condition.long_rest_recovery:
            condition.levels -= 1
            if condition.levels == 0:
                del actor.conditions[key]
            break
    actor.last_long_rest_at = world.elapsed_seconds
    actor.recovery_activity_id = None
    _emit(events, world, "long_rest_completed", actor, hp=actor.hp)


def _end(world: World, actor: Actor, status: str) -> None:
    assert actor.activity is not None
    actor.activity.status = status
    actor.activity.ended_at = world.elapsed_seconds


def _interrupt(world: World, actor: Actor, events: list[dict], reason: str, resume: bool = False) -> None:
    activity = actor.activity
    require(activity is not None and activity.status == "active", "NO_ACTIVE_ACTIVITY")
    require(type(resume) is bool and (not resume or activity.kind == "long_rest"), "INVALID_RESUMPTION")
    allowed = REST_INTERRUPTS | {"exertion_hour", "strenuous_activity", "unsafe", "unobserved", "cultivation_disrupted"}
    require(isinstance(reason, str) and reason in allowed, "INVALID_INTERRUPTION")
    if reason == "cultivation_disrupted":
        require(activity.kind in CULTIVATION_KINDS, "INVALID_INTERRUPTION")
    if resume:
        require(reason in REST_INTERRUPTS | {"exertion_hour"}
                and not actor.dead and actor.hp > 0, "INVALID_RESUMPTION")
    actor.recovery_activity_id = None
    # Unobserved time is not evidence of a qualified partial rest.
    # Each resumed segment starts a new one-hour qualification window. This
    # segment boundary is the source-derived implementation interpretation of
    # the preceding-rest Short Rest benefit, rather than an owner ruling.
    if activity.kind == "long_rest" and activity.segment_elapsed >= 3600 and reason in REST_INTERRUPTS | {"exertion_hour"}:
        _short_benefits(world, actor, events)
    if resume:
        activity.segment_index += 1
        activity.segment_elapsed = 0
        activity.required_seconds += 3600
        _emit(events, world, "long_rest_resumed", actor, reason=reason,
              segment_index=activity.segment_index, required_seconds=activity.required_seconds)
    else:
        _end(world, actor, "interrupted")
        _emit(events, world, "activity_interrupted", actor, reason=reason)


def _tick(world: World, modes: dict[str, str], events: list[dict]) -> None:
    for actor in world.actors.values():
        for key, condition in list(actor.conditions.items()):
            if condition.expires_at is not None and condition.expires_at <= world.elapsed_seconds:
                del actor.conditions[key]
                _emit(events, world, "condition_expired", actor, instance_id=key)
        activity = actor.activity
        if activity is None or activity.status != "active":
            continue
        # Zero HP is an unresolved dying/stabilization state in this slice.
        # Never let a generic clock advance complete a Long Rest and restore
        # HP until a future death/stabilization adapter supplies that rule.
        if activity.kind == "long_rest" and actor.hp <= 0:
            actor.recovery_activity_id = None
            _end(world, actor, "interrupted")
            _emit(events, world, "activity_interrupted", actor, reason="zero_hp")
            continue
        scene = world.scenes[actor.scene_id]
        mode = modes[actor.actor_id]
        if mode == "unobserved" or not scene.rest_allowed:
            _interrupt(world, actor, events, "unobserved" if mode == "unobserved" else "unsafe")
            continue
        activity.elapsed += 1
        activity.segment_elapsed += 1
        if activity.kind == "long_rest":
            if mode == "sleep":
                activity.sleeping += 1
            else:
                activity.light += 1
            if activity.light > 7200:
                _interrupt(world, actor, events, "strenuous_activity")
            elif activity.elapsed >= activity.required_seconds and activity.sleeping >= 21600:
                _long_benefits(world, actor, events)
                _end(world, actor, "completed")
        else:
            if mode == "cultivation":
                activity.cultivation_seconds += 1
            if activity.kind != "cultivation" and activity.elapsed >= 3600:
                _short_benefits(world, actor, events)
            if activity.kind in CULTIVATION_KINDS and activity.cultivation_seconds >= 7200:
                _cultivation_benefits(world, actor, events)
                _end(world, actor, "completed")
            elif activity.kind == "short_rest" and activity.elapsed >= 3600:
                _end(world, actor, "completed")


def transition(world: World, actor_id: str | None, kind: str, payload: dict,
               activity_id: str, roll_die: Callable[[int], int]) -> tuple[World, list[dict]]:
    """Return a new state and semantic events; discard both if validation fails.

    Authorization, transaction boundaries and durable roll receipts live in the
    service. A roll supplier is host-owned and is never read from command input.
    """
    require(kind in COMMANDS, "UNSUPPORTED_COMMAND")
    state = deepcopy(world)
    events: list[dict] = []
    actor = state.actors.get(actor_id) if actor_id is not None else None
    if kind == "advance_time":
        fields(payload, {"seconds", "modes"})
        require(actor_id is None, "UNEXPECTED_ACTOR")
        require(integer(payload["seconds"], 1, 86400), "INVALID_TIME_ADVANCE")
        modes = payload["modes"]
        active = {a.actor_id: a for a in state.actors.values() if a.activity and a.activity.status == "active"}
        require(isinstance(modes, dict) and set(modes) == set(active), "REST_OBSERVATION_REQUIRED")
        for key, active_actor in active.items():
            assert active_actor.activity
            rest_kind = active_actor.activity.kind
            allowed = ({"sleep", "light"} if rest_kind == "long_rest" else
                       {"cultivation"} if rest_kind in CULTIVATION_KINDS else {"light"})
            require(isinstance(modes[key], str) and modes[key] in allowed | {"unobserved"}, "INCOMPATIBLE_ACTIVITY_OBSERVATION")
        for _ in range(payload["seconds"]):
            state.elapsed_seconds += 1
            _tick(state, modes, events)
        _emit(events, state, "world_time_advanced", seconds=payload["seconds"])
    else:
        require(actor is not None, "ACTOR_NOT_FOUND")
        assert actor is not None
        if kind == "start_activity":
            fields(payload, {"kind"}, {"path_ids"})
            idle(actor)
            rest_kind = payload["kind"]
            require(isinstance(rest_kind, str) and rest_kind in ACTIVITY_KINDS, "UNSUPPORTED_ACTIVITY")
            scene = state.scenes[actor.scene_id]
            require(scene.rest_allowed, "REST_NOT_ALLOWED")
            path_ids = payload.get("path_ids", [])
            require(isinstance(path_ids, list) and all(identifier(p) for p in path_ids)
                    and len(set(path_ids)) == len(path_ids), "INVALID_PRACTICE_PATHS")
            if rest_kind in CULTIVATION_KINDS:
                require(scene.cultivation_allowed and bool(path_ids)
                        and set(path_ids) <= set(actor.cultivation_paths), "PRACTICE_NOT_ADMITTED")
                require(rest_kind != "short_rest_cultivation" or actor.light_cultivation, "PRACTICE_NOT_LIGHT")
            else:
                require(not path_ids, "UNEXPECTED_PRACTICE_PATHS")
            if rest_kind == "long_rest":
                require(actor.last_long_rest_at is None or state.elapsed_seconds >= actor.last_long_rest_at + 57600,
                        "LONG_REST_COOLDOWN")
            required = 28800 if rest_kind == "long_rest" else 7200 if rest_kind in CULTIVATION_KINDS else 3600
            actor.recovery_activity_id = None
            actor.activity = Activity(activity_id, rest_kind, state.elapsed_seconds,
                                      path_ids=path_ids, required_seconds=required)
            _emit(events, state, "activity_started", actor, activity_id=activity_id, activity=rest_kind)
        elif kind == "cancel_activity":
            fields(payload, set())
            require(actor.activity is not None and actor.activity.status == "active", "NO_ACTIVE_ACTIVITY")
            actor.recovery_activity_id = None
            _end(state, actor, "cancelled")
            _emit(events, state, "activity_cancelled", actor)
        elif kind == "finish_recovery":
            fields(payload, set())
            require(actor.recovery_activity_id is not None, "NO_RECOVERY_WINDOW")
            actor.recovery_activity_id = None
            _emit(events, state, "recovery_closed", actor)
        elif kind == "spend_hit_die":
            fields(payload, {"pool_id"})
            require(identifier(payload["pool_id"]), "INVALID_HIT_DICE_ID")
            require(not actor.dead and actor.recovery_activity_id is not None, "NO_RECOVERY_WINDOW")
            dice = actor.hit_dice.get(payload["pool_id"])
            require(dice is not None and dice.remaining > 0, "HIT_DICE_UNAVAILABLE")
            assert dice is not None
            roll = roll_die(dice.sides)
            require(integer(roll, 1, dice.sides), "INVALID_HOST_ROLL")
            gain = min(actor.hp_max - actor.hp, max(1, roll + actor.con_modifier))
            dice.remaining -= 1
            actor.hp += gain
            _emit(events, state, "hit_die_spent", actor, pool_id=payload["pool_id"],
                  sides=dice.sides, roll=roll, con_modifier=actor.con_modifier, healed=gain)
        elif kind in {"take_item", "drop_item", "drink_potion"}:
            fields(payload, {"item_id"})
            idle(actor)
            item_id = payload["item_id"]
            require(identifier(item_id), "INVALID_ITEM_ID")
            item = state.items.get(item_id)
            if kind == "take_item":
                require(item_available(state, actor, item_id), "ITEM_UNAVAILABLE")
                assert item is not None
                item.public_ownership = item.visible_to is None
                item.owner_id, item.scene_id = actor.actor_id, None
            else:
                require(item is not None and item.owner_id == actor.actor_id and item.quantity > 0,
                        "ITEM_UNAVAILABLE")
                assert item is not None
                if kind == "drop_item":
                    item.owner_id, item.scene_id = None, actor.scene_id
                    item.equipped = item.attuned = False
                    item.visible_to = None
                    item.public_ownership = True
                else:
                    require(item.kind == "healing_potion", "ITEM_NOT_HEALING_POTION")
                    rolls = [roll_die(4), roll_die(4)]
                    require(all(integer(r, 1, 4) for r in rolls), "INVALID_HOST_ROLL")
                    gain = min(actor.hp_max - actor.hp, sum(rolls) + 2)
                    item.quantity -= 1
                    actor.hp += gain
                    _emit(events, state, "potion_healing", actor, item_id=item_id, rolls=rolls, healed=gain)
            actor.recovery_activity_id = None
            _emit(events, state, kind, actor, item_id=item_id, quantity=item.quantity)
        elif kind == "interrupt_activity":
            fields(payload, {"reason"}, {"resume_long_rest"})
            _interrupt(state, actor, events, payload["reason"], payload.get("resume_long_rest", False))
        elif kind == "damage":
            fields(payload, {"amount", "source_id"}, {"resume_long_rest"})
            require(integer(payload["amount"], 1) and identifier(payload["source_id"]), "INVALID_DAMAGE")
            require(type(payload.get("resume_long_rest", False)) is bool, "INVALID_RESUMPTION")
            require(not actor.dead, "ACTOR_DEAD")
            actor.recovery_activity_id = None
            actor.hp = max(0, actor.hp - payload["amount"])
            if actor.activity and actor.activity.status == "active":
                resume = payload.get("resume_long_rest", False) and actor.hp > 0
                _interrupt(state, actor, events, "damage", resume)
                if actor.hp == 0:
                    # Damage is still an admitted committed fact, but the
                    # unsupported zero-HP continuation and recovery window
                    # must close even when the request asked to resume.
                    actor.recovery_activity_id = None
            else:
                require(not payload.get("resume_long_rest", False), "NO_ACTIVE_ACTIVITY")
            _emit(events, state, "damage_applied", actor, amount=payload["amount"], source_id=payload["source_id"])
        elif kind == "apply_condition":
            fields(payload, {"instance_id", "kind", "source_id"},
                   {"levels", "expires_at", "long_rest_recovery", "definition_id",
                    "definition_version", "source_hash", "applied_at"})
            condition = Condition(**payload)
            validate_condition(condition, state.elapsed_seconds)
            require(condition.instance_id not in actor.conditions, "CONDITION_INSTANCE_EXISTS")
            actor.conditions[condition.instance_id] = condition
            if actor.exhaustion >= 6:
                actor.dead, actor.hp, actor.recovery_activity_id = True, 0, None
                if actor.activity and actor.activity.status == "active":
                    _end(state, actor, "interrupted")
                _emit(events, state, "actor_died", actor, reason="exhaustion")
            _emit(events, state, "condition_applied", actor, instance_id=condition.instance_id, condition=condition.kind)
        elif kind == "remove_condition":
            fields(payload, {"instance_id", "source_id"})
            require(identifier(payload["source_id"]), "SOURCE_REQUIRED")
            require(identifier(payload["instance_id"]), "INVALID_CONDITION_ID")
            require(payload["instance_id"] in actor.conditions, "CONDITION_NOT_FOUND")
            del actor.conditions[payload["instance_id"]]
            _emit(events, state, "condition_removed", actor, **payload)
        elif kind == "apply_reduction":
            fields(payload, {"instance_id", "source_id", "stat", "amount"},
                   {"ends_on_long_rest", "definition_id", "definition_version", "source_hash", "applied_at"})
            reduction = Reduction(**payload)
            validate_reduction(reduction)
            require(reduction.instance_id not in actor.reductions, "REDUCTION_INSTANCE_EXISTS")
            actor.reductions[reduction.instance_id] = reduction
            actor.hp = min(actor.hp, actor.hp_max)
            _emit(events, state, "reduction_applied", actor, **payload)
        elif kind == "remove_reduction":
            fields(payload, {"instance_id", "source_id"})
            require(identifier(payload["source_id"]), "SOURCE_REQUIRED")
            require(identifier(payload["instance_id"]), "INVALID_REDUCTION_ID")
            require(payload["instance_id"] in actor.reductions, "REDUCTION_NOT_FOUND")
            del actor.reductions[payload["instance_id"]]
            _emit(events, state, "reduction_removed", actor, **payload)
    validate_world(state)
    return state, events
