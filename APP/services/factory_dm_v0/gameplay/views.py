"""Allowlisted gameplay reads shared by menus and proposed freeform actions."""
from dataclasses import asdict
from copy import deepcopy

from .integration import mechanics_world, resolve
from .models import require
from .profile import identity
from .rules import item_available


def modifiers(actor):
    poisoned = any(c.kind == "poisoned" for c in actor.conditions.values())
    return {"exhaustion": actor.exhaustion, "d20_modifier": -2 * actor.exhaustion,
            "speed": max(0, actor.speed - 5 * actor.exhaustion),
            "disadvantage_on": ["attack", "ability_check"] if poisoned else [],
            "hit_die_modifier": actor.con_modifier}


def costs_effects(world, actor, kind, payload):
    if kind == "spend_hit_die":
        pool = actor.hit_dice[payload["pool_id"]]
        return {"costs": {"hit_dice": {payload["pool_id"]: 1}},
                "effects": {"hp": {"dice": [pool.sides], "modifier": actor.con_modifier,
                                    "minimum": 1, "cap": actor.hp_max}}}
    if kind == "drink_potion":
        return {"costs": {"items": {payload["item_id"]: 1}},
                "effects": {"hp": {"dice": [4, 4], "modifier": 2, "cap": actor.hp_max}}}
    if kind == "start_activity":
        rest = payload["kind"]
        return {"costs": {}, "effects": {"starts_activity": rest, "immediate_hp": 0,
                "immediate_seconds": 0, "rest_milestone_seconds": 3600 if rest in
                {"short_rest", "short_rest_cultivation"} else None,
                "cultivation_milestone_seconds": 7200 if "cultivation" in rest else None,
                "long_rest_minimum_seconds": 28800 if rest == "long_rest" else None}}
    return {"costs": {}, "effects": {"operation": kind, **payload}}


def player_projection(state, revision, principal_id, actor_id):
    world = mechanics_world(state)
    actor = world.actors[actor_id]
    suggestions = []
    candidates = []
    for kind in ("short_rest", "cultivation", "short_rest_cultivation", "long_rest"):
        payload = {"kind": kind}
        if "cultivation" in kind:
            payload["path_ids"] = sorted(actor.cultivation_paths)
        candidates.append(("start_activity", payload))
    candidates.extend((k, {}) for k in ("cancel_activity", "finish_recovery"))
    candidates.extend(("spend_hit_die", {"pool_id": k}) for k in sorted(actor.hit_dice))
    for item in world.items.values():
        if item_available(world, actor, item.instance_id):
            candidates.append(("take_item", {"item_id": item.instance_id}))
        if item.owner_id == actor_id:
            candidates.append(("drop_item", {"item_id": item.instance_id}))
            if item.kind == "healing_potion":
                candidates.append(("drink_potion", {"item_id": item.instance_id}))
    for kind, payload in candidates:
        command = {"principal_id": principal_id, "actor_id": actor_id, "kind": kind,
                   "payload": payload, "expected_revision": revision, "request_id": "suggestion",
                   "profile": identity()}
        try:
            resolve(state, command, lambda sides: 1)
        except ValueError:
            continue
        suggestions.append({"kind": kind, "payload": payload, "actor_id": actor_id,
                            "expected_revision": revision, "profile": identity(),
                            "available": True, "difficulty": None,
                            **costs_effects(world, actor, kind, payload)})
    character = next(c for c in state.characters if c.character_id == actor_id)
    known = {k.fact_id for k in character.knowledge}
    for scene in state.scenes:
        if scene.open and scene.location_id == character.location_id and actor_id in scene.participants:
            known.update(scene.public_facts)
    # Canon requires the same provenance knowledge as V0; global canon is not public.
    facts = [{"fact_id": f.fact_id, "subject_id": f.subject_id, "predicate": f.predicate, "value": f.value}
             for f in state.world_facts if f.public or f.fact_id in known]
    canon = [{"entry_id": c.entry_id, "claim": asdict(c.claim)}
             for c in state.canon if c.provenance.source_id in known]
    def item_read(i):
        return {"instance_id": i.instance_id, "label": i.label, "quantity": i.quantity,
                "owner_id": i.owner_id}
    return {
        "campaign_id": world.world_id, "revision": revision, "elapsed_seconds": world.elapsed_seconds,
        "profile": identity(),
        "actor": {"actor_id": actor_id, "name": actor.name, "hp": actor.hp, "hp_max": actor.hp_max,
                  "dead": actor.dead, "mechanics": modifiers(actor),
                  "hit_dice": {k: asdict(d) for k, d in actor.hit_dice.items()},
                  "paths": {k: asdict(p) for k, p in actor.paths.items()},
                  "conditions": [{"instance_id": c.instance_id, "kind": c.kind, "levels": c.levels,
                                  "expires_at": c.expires_at, "long_rest_recovery": c.long_rest_recovery}
                                 for c in actor.conditions.values()],
                  "reductions": [{"instance_id": r.instance_id, "stat": r.stat, "amount": r.amount}
                                 for r in actor.reductions.values()],
                  "activity": asdict(actor.activity) if actor.activity else None,
                  "recovery_activity_id": actor.recovery_activity_id},
        "location": {"location_id": actor.scene_id, "name": world.scenes[actor.scene_id].title},
        "party_here": [{"actor_id": a.actor_id, "name": a.name} for a in world.actors.values()
                       if a.actor_id != actor_id and a.scene_id == actor.scene_id],
        "inventory": [item_read(i) for i in world.items.values() if i.owner_id == actor_id and i.quantity],
        "nearby_items": [item_read(i) for i in world.items.values() if item_available(world, actor, i.instance_id)],
        "public_items": [item_read(i) for i in world.items.values() if i.public_ownership and i.quantity
                         and ((i.owner_id in world.actors and world.actors[i.owner_id].scene_id == actor.scene_id)
                              or i.scene_id == actor.scene_id)],
        "known_facts": facts, "known_canon": canon, "suggestions": suggestions,
        "freeform": {"requires_structured_proposal": True, "expected_revision": revision,
                     "profile": identity(), "unmapped_actions": "unsupported"},
    }


def projection(state, revision, principal_id, actor_id=None):
    require(state.gameplay is not None, "GAMEPLAY_NOT_BOUND")
    member = state.gameplay["members"].get(principal_id)
    require(member is not None, "MEMBER_REQUIRED")
    if actor_id is not None:
        require(actor_id in state.gameplay["actors"], "ACTOR_NOT_FOUND")
        require(member["role"] == "gm" or actor_id in member["actor_ids"], "ACTOR_UNAUTHORIZED")
        return deepcopy(player_projection(state, revision, principal_id, actor_id))
    require(member["role"] == "gm", "ACTOR_REQUIRED")
    world = mechanics_world(state)
    return {"campaign_id": world.world_id, "revision": revision,
            "elapsed_seconds": world.elapsed_seconds, "profile": identity(),
            "actors": {aid: asdict(a) for aid, a in world.actors.items()},
            "items": {iid: asdict(i) for iid, i in world.items.items()},
            "world_facts": [_primitive_fact(f) for f in state.world_facts]}


def _primitive_fact(fact):
    return asdict(fact)
