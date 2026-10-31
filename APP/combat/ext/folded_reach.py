"""Space Folded Reach and Folded Weapon Line: a visible, next-strike origin.

Uses action_geometry's shared effect_origins/attack_limit contract. No creature
moves, no inflated reach, and physical caster perception bounds AI knowledge.
The condition holds the printed distance and optional weapon-only enhancement;
normal attacks/touches also consume the next-use grant. Other actors are inert.
"""
from __future__ import annotations

import json
from typing import Any

from . import effect, hook
from .condition_ownership import remove_instance

STATE = "condition:typed.folded_reach"
_MECHANICS: dict[str, Any] = {}


def _mechanics():
    if not _MECHANICS:
        from .. import factory_compiler
        _MECHANICS.update(json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"])
    return _MECHANICS


def _state(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == STATE), None)


@effect("folded_reach")
def fold(ctx, row):
    for key, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == STATE:
            remove_instance(ctx.engine, ctx.actor, key, ctx.source)
    feet = int(row.get("distance_ft") or 10)
    cl = int(ctx.numbers.get("cl") or 1)
    for low, high, distance in row.get("distance_ft_by_cl") or []:
        if low <= cl <= high:
            feet = int(distance)
            break
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
        expires_on="END_OF_CURRENT_TURN",
        data={"extra_ft": feet, "attack_limit": int(row.get("attack_limit") or 1), "label": "Folded Reach",
              "reading": f"Your next melee attack or touch effect this turn may start at a visible point within {feet} feet. Its normal range and cover apply from there."})


def _foldable(action):
    if action is None:
        return False
    typed = (action.parameters or {}).get("typed") or {}
    if (action.parameters or {}).get("basic"):
        return False
    if action.target_kind not in ("HOSTILE_ENTITY", "ALLY_OR_SELF", "ALLY", "ANY_ENTITY", "HOSTILE_ENTITY_OR_SELF"):
        return False
    attacks = [e for e in typed.get("effects") or [] if e.get("type") == "attack"]
    if attacks:
        return (not typed.get("long_range_ft")
                and all(e.get("attack_kind") == "unarmed" or
                        (typed.get("weapon") and e.get("attack_kind") in ("weapon", "melee", "cultivation_melee"))
                        for e in attacks))
    mechanic = _mechanics().get(typed.get("source")) or {}
    return (mechanic.get("range") or {}).get("kind") == "touch"


@hook("effect_origins")
def folded_origins(engine, actor, action):
    state = _state(actor)
    if state is None or not _foldable(action):
        return None
    from .. import senses
    from ..gate2_runtime_models import Position
    typed = action.parameters.get("typed") or {}
    weapon = bool(typed.get("weapon")) or any(e.get("attack_kind") == "unarmed" for e in typed.get("effects") or [])
    feet = int(state.data["extra_ft"])
    if state.data.get("weapon_only") and not weapon:
        feet -= int(state.data.get("weapon_bonus_ft") or 0)
    radius = feet // engine.grid.square_size_ft
    body = engine._actor_volume(actor)
    xs, ys, zs = zip(*body)
    out = []
    from ..targeting import line_of_effect
    for z in range(max(0, min(zs) - radius), max(zs) + radius + 1):
        for y in range(max(0, min(ys) - radius), min(engine.grid.height, max(ys) + radius + 1)):
            for x in range(max(0, min(xs) - radius), min(engine.grid.width, max(xs) + radius + 1)):
                point = Position(x=x, y=y, z=z)
                if (engine.grid.distance_between_cell_sets_ft(body, (point,)) > feet
                        or not senses.perceives_cell(engine, actor, point)
                        or not engine.grid.placement_legal(point)
                        or not line_of_effect(engine, actor, destination=point)):
                    continue
                out.append({"id": f"fold:{state.instance_id}:{x},{y},{point.z}",
                            "label": f"Folded Reach: strike from {x},{y}, {z * 5} feet up",
                            "position": {"x": point.x, "y": point.y, "z": point.z},
                            "attack_limit": int(state.data.get("attack_limit") or 1)})
    return out or None


@hook("candidate_allowed")
def folded_target_known(engine, actor, candidate, action):
    origin = (candidate.metadata or {}).get("effect_origin") or {}
    if not str(origin.get("id") or "").startswith("fold:"):
        return None
    from ..action_geometry import activate
    from ..target_knowledge import located
    with activate(engine, actor, action.source_definition_id, None):
        # An origin isn't an extra pair of eyes. A known target can be struck
        # around partial cover, but not an unknown creature around a corner.
        return all((target := engine.state.actors.get(tid)) is not None
                   and located(engine, actor, target) for tid in candidate.target_ids)


@effect("folded_weapon_line")
def enhance(ctx, row):
    state = _state(ctx.actor)
    if state is None:
        return
    data = {**state.data, "extra_ft": int(state.data["extra_ft"]) + int(row["distance_ft"]),
            "weapon_bonus_ft": int(row["distance_ft"]), "weapon_only": 1,
            "line_on_hit": row.get("on_hit") or [], "line_on_miss": row.get("on_miss") or [],
            "label": "Folded Weapon Line",
            "reading": "Your next melee weapon attack or Unarmed Strike this turn strikes from a visible folded point; on a hit the target cannot take Reactions until its next turn starts."}
    remove_instance(ctx.engine, ctx.actor, state.instance_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
                               expires_on="END_OF_CURRENT_TURN", data=data)


def _consume(ctx):
    state = _state(ctx.actor)
    if state is None or not _foldable(ctx.action):
        return
    from ..action_geometry import commit_usage
    commit_usage(ctx.engine, ctx.actor, ctx.source)
    if ctx.strike_record is not None:
        ctx.strike_record["folded_grant"] = dict(state.data)
    remove_instance(ctx.engine, ctx.actor, state.instance_id, ctx.source)


@hook("event")
def consume_on_roll(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    from .attack_scope import capture_roll
    frame = capture_roll(engine, kwargs)
    if frame is not None:
        _consume(frame["context"])


@hook("effect_resolution_scope")
def folded_resolution(ctx, row):
    if _state(ctx.actor) is None or not _foldable(ctx.action):
        return None
    attack = row.get("type") == "attack"
    if not attack and any(e.get("type") == "attack" for e in ctx.typed.get("effects") or []):
        return None
    from contextlib import ExitStack, contextmanager
    from ..action_geometry import activate, origins, record_for
    @contextmanager
    def scope():
        with ExitStack() as stack:
            # Reactions and granted attacks have no primary-action origin menu.
            # They still get the printed optional point, without changing their
            # physical trigger reach or revealing an unknown target.
            if str(ctx.action.economy) in {"REACTION", "NONE"} and record_for(ctx.engine, ctx.actor, ctx.source) is None:
                from .needle import ask, checkpoint_id
                from ..targeting import line_of_effect
                points = []
                for origin in origins(ctx.engine, ctx.actor, ctx.action):
                    with activate(ctx.engine, ctx.actor, ctx.source, origin, action=ctx.action):
                        reach = int(ctx.typed.get("reaction_range_ft") or ctx.action.range_ft or ctx.action.reach_ft or 5)
                        if all(ctx.engine._effect_distance(ctx.actor, target) <= reach and
                               line_of_effect(ctx.engine, ctx.actor, target=target) for target in ctx.targets):
                            points.append(origin)
                chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "folded_origin", ctx.source),
                    ctx.actor, "choice:space.folded_origin", [p["id"] for p in points],
                    labels={p["id"]: p["label"] for p in points}, allow_decline=True,
                    default="decline", name="Folded Reach", target_id=ctx.target.entity_id if ctx.target else ctx.actor.entity_id,
                    prompt=f"Folded Reach: choose a visible point from which {ctx.actor.display_name}'s "
                           f"{ctx.action.display_name} starts, or use its ordinary origin. No extra action or CP.")
                if chosen:
                    origin = next(p for p in points if p["id"] == chosen[0])
                    stack.enter_context(activate(ctx.engine, ctx.actor, ctx.source, origin, action=ctx.action))
            if not attack:
                _consume(ctx)
            yield
    return scope()


@hook("attack_resolved")
def folded_line_outcome(ctx, target, hit, row):
    # Concealment misses have no attack d20, but still spend the next attack.
    _consume(ctx)
    record = ctx.strike_record or {}
    data = record.get("folded_grant") or {}
    if not data.get("weapon_only") or not _foldable(ctx.action):
        return
    if not ctx.typed.get("weapon") and row.get("attack_kind") != "unarmed":
        return
    # Exactly the next strike, not each Extra Attack or later effect block.
    if record.get("folded_line_spent"):
        return
    record["folded_line_spent"] = True
    from dataclasses import replace
    from ..typed_executor import run_effects
    run_effects(replace(ctx, targets=[target], target=target),
                data.get("line_on_hit" if hit else "line_on_miss") or [])


@hook("technique_used")
def spend_fold(ctx):
    if _state(ctx.actor) is None or not _foldable(ctx.action):
        return
    for key, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == STATE:
            remove_instance(ctx.engine, ctx.actor, key, ctx.source)
