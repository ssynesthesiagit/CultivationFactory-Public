"""Timed damage riders declared by the owning compiled ability.

``rider_damage_state`` stores ``dealt_melee_hit``, ``received_melee_hit``,
``grappler_turn_start`` or ``near_hostile_turn_start`` effects on the bearer.
``own_turn_start`` runs declared effects at the bearer's turn start (for
selected-target aura riders such as Crown of the Inferno).
The first three share a per-creature/per-turn allowance when ``once_per_turn``
is true. A nearby start trigger may instead use ``once_per_round``: the first
eligible hostile creature's turn spends it, never activation. State and damage
use ordinary condition events and reducers, preserving replay.

Owner sources: Magma Armor, Obsidian Skin, Furnace Mantle, rules_text.json.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .owned_effects import remove_conditions

PREFIX = "condition:typed.rider_damage_state."


@effect("rider_damage_state")
def activate(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te

    for holder in te._default_subject(ctx, spec, harmful=False):
        name = PREFIX + te._mark_slug(spec["name"])
        remove_conditions(ctx.engine, holder, ctx.source, ctx.actor.entity_id, name)
        ctx.engine._apply_condition(holder, name, ctx.source, ctx.actor.entity_id,
                                    expires_on=te.effect_expiry(ctx, spec, holder, condition=True),
                                    data={"spec": copy.deepcopy(spec), "numbers": dict(ctx.numbers), "label": spec["name"]})


def _states(holder: Any):
    return [condition for condition in holder.conditions.values() if condition.condition_id.startswith(PREFIX)]


@hook("hit_response")
def hit_states(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> None:
    # Damage can end Concentration before the typed after_hit hook. Preserve
    # the states present when this hit was declared; a subsequently cancelled
    # hit has no after_hit and therefore pays no retaliation.
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_rider_hit_states")
    own, received = _states(attacker), _states(target)
    if not own and not received:
        # A prior cancelled hit may have left a snapshot; never revive an
        # expired rider on this pair's next unrelated hit.
        engine.__dict__.get("_rider_hit_states", {}).pop((attacker.entity_id, target.entity_id), None)
        return
    engine.__dict__.setdefault("_rider_hit_states", {})[(attacker.entity_id, target.entity_id)] = (own, received)


def _melee(ctx: Any, kind: str) -> bool:
    from .. import typed_executor as te

    if kind == "unarmed":
        return True
    if kind == "weapon":
        return not ctx.typed.get("range_ft") and not ctx.source.endswith("#thrown")
    attacks = [row.get("attack_kind") for row in te._walk_rows(ctx.typed.get("effects") or []) if row.get("type") == "attack"]
    return bool(attacks) and all(name in {"cultivation_melee", "melee", "unarmed"} for name in attacks)


def _fire(engine: Any, holder: Any, subject: Any, condition: Any, rows: list[dict[str, Any]], *, round_only: bool = False,
          from_event: bool = False) -> None:
    from .. import typed_executor as te

    if not rows or not subject.active:
        return
    spec = condition.data["spec"]
    if spec.get("requires_condition") and not any(
            c.condition_id == te.CONDITION_PREFIX + spec["requires_condition"]
            and c.source_definition_id == condition.source_definition_id and c.source_actor_id == condition.source_actor_id
            for c in holder.conditions.values()):
        return
    flag = f"rider_damage:{condition.condition_id}_round_{engine.state.round_number}"
    if not round_only:
        flag += f"_turn_{engine.state.current_slot_index}_{subject.entity_id}"
    limited = round_only or spec.get("once_per_turn")
    if limited and holder.turn_flags.get(flag):
        return
    if limited:
        holder.turn_flags[flag] = True
    source = engine.state.actors.get(condition.source_actor_id)
    action = engine.action_catalog.get(condition.source_definition_id)
    if source is not None and action is not None:
        from ..gate2_runtime_models import ActionIntent

        intent = getattr(engine, "_active_intent", None) or ActionIntent(
            intent_id=f"rider-trigger:{engine.state.event_sequence}", actor_id=source.entity_id,
            decision_id="rider-trigger", candidate_id=action.source_definition_id,
            state_version=engine.state.state_version, target_ids=(subject.entity_id,))
        ctx = te.Context(engine, source, action, intent, {"numbers": condition.data["numbers"]}, [subject], subject, {})
        if from_event:
            from .event_rider_damage import run_event_effects
            run_event_effects(ctx, rows)
        else:
            te.run_effects(ctx, rows)


@hook("after_hit")
def melee_hit(ctx: Any, target: Any, kind: str) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_rider_hit_states")
    captured = ctx.engine.__dict__.get("_rider_hit_states", {}).pop((ctx.actor.entity_id, target.entity_id), None)
    if not _melee(ctx, kind):
        return
    own, received = captured or (_states(ctx.actor), _states(target))
    for condition in own:
        allowed = condition.data["spec"].get("dealt_kinds")
        if not allowed or kind in allowed:
            _fire(ctx.engine, ctx.actor, target, condition, condition.data["spec"].get("dealt_melee_hit") or [])
    for condition in received:
        spec = condition.data["spec"]
        if not spec.get("received_hostile_only") or ctx.actor.team_id != target.team_id:
            _fire(ctx.engine, target, ctx.actor, condition, spec.get("received_melee_hit") or [])


@hook("turn_start")
def start(engine: Any, actor: Any) -> None:
    from .. import typed_executor as te

    for holder in engine.state.actors.values():
        if not holder.active:
            continue
        for condition in _states(holder):
            spec = condition.data["spec"]
            if actor.entity_id == holder.entity_id:
                _fire(engine, holder, holder, condition, spec.get("own_turn_start") or [], from_event=True)
            if any(c.condition_id == te.CONDITION_PREFIX + "grappled" and c.source_actor_id == actor.entity_id
                   for c in holder.conditions.values()):
                _fire(engine, holder, actor, condition, spec.get("grappler_turn_start") or [], from_event=True)
            near = spec.get("near_hostile_turn_start") or {}
            if near and actor.team_id != holder.team_id and engine._distance_actor_to_actor(holder, actor) <= int(near["radius_ft"]):
                _fire(engine, holder, actor, condition, near.get("effects") or [], round_only=bool(near.get("once_per_round")), from_event=True)
