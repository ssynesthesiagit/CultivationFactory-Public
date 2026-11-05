"""Target-bound next-packet bonuses (Conductor's Palm and other typed benefits).

Effect: next_damage_bonus, applies_to: target, bonus: pb or integer,
damage_types: list, spheres: list, singleton: string, normal expiry fields.
Types and spheres are alternatives; sphere provenance comes from the compiled
action, never from damage color or weapon material. One singleton instance per
target across all casters replaces its predecessor. Condition state is plain
strings/integers/lists. Missing owned source or singleton is inert.

The damage query is pure. Consumption uses positive committed HP/temp-HP damage,
so immunity, zero packets and fully negated packets retain the benefit. Nested
event hooks are suppressed by the engine: queries also inspect committed events
since activation, and turn hooks remove stale markers. Snapshot + journal reload
is supported; event-only reconstruction of custom condition data is not claimed.
"""
from typing import Any

from . import effect, hook

PREFIX = "condition:typed.mark.next_damage_bonus:"


@hook("compile_actions")
def hostile_choices(info: dict) -> list | None:
    """Add the hostile domain to this effect's existing ally/self domain.

    Both actions retain the original economy, costs, source and duration.
    """
    out = []
    for action in info["actions"]:
        typed = (action.parameters or {}).get("typed") or {}
        if action.target_kind != "ALLY_OR_SELF" or not any(
                row.get("type") == "next_damage_bonus" for row in typed.get("effects") or []):
            continue
        out.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + ".hostile",
            "target_kind": "HOSTILE_ENTITY"}))
    return out or None


@hook("candidate_allowed")
def supported_targets(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if any(row.get("type") == "next_damage_bonus" for row in typed.get("effects") or []):
        if any(target_id not in getattr(engine, "typed_actor_ids", set()) for target_id in candidate.target_ids):
            return False
    return None


def qualifying(engine: Any, data: dict, kind: str, source: str | None) -> bool:
    action = engine.action_catalog.get(source or "")
    typed = (action.parameters or {}).get("typed") or {} if action else {}
    return (str(kind).lower() in data.get("damage_types", [])
            or typed.get("sphere") in data.get("spheres", []))


def consumed(engine: Any, target: Any, state: Any) -> bool:
    """Read actual commits, including those made inside another event hook."""
    data = state.data or {}
    for event in reversed(engine.events):
        if event.sequence <= int(data.get("after_sequence", 0)):
            break
        if (event.event_type == "DAMAGE_COMMITTED" and target.entity_id in event.target_ids
                and int(event.payload.get("reduced_to", 0)) > 0
                and qualifying(engine, data, event.payload.get("damage_type", ""), event.source_definition_id)):
            return True
    return False


@effect("next_damage_bonus")
def apply(ctx: Any, eff: dict) -> None:
    from ..typed_executor import _default_subject, effect_expiry
    from .riders_shared import remove_benefit_condition

    group = str(eff.get("singleton") or "")
    if not ctx.typed.get("source") or not group:
        return
    cid = PREFIX + group
    bonus = ctx.numbers.get("pb", 2) if eff.get("bonus") == "pb" else int(eff.get("bonus", 0))
    for target in _default_subject(ctx, eff, harmful=False):
        # The locked native/object damage paths have no additive seam.
        if target.entity_id not in getattr(ctx.engine, "typed_actor_ids", set()):
            continue
        for state in list(target.conditions.values()):
            if state.condition_id == cid:
                remove_benefit_condition(ctx.engine, target, state, "REPLACED")
        ctx.engine._apply_condition(target, cid, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, eff, target, condition=True),
            data={"bonus": int(bonus), "damage_types": list(eff.get("damage_types") or []),
                  "spheres": list(eff.get("spheres") or []),
                  "after_sequence": ctx.engine.events[-1].sequence if ctx.engine.events else 0,
                  "label": ctx.action.display_name})


@hook("incoming_damage_bonus")
def bonus(engine: Any, target: Any, amount: int, kind: str, source: str | None, actor_id: str | None) -> int:
    return sum(int((state.data or {}).get("bonus", 0)) for state in target.conditions.values()
               if state.condition_id.startswith(PREFIX) and not consumed(engine, target, state)
               and qualifying(engine, state.data or {}, kind, source))


def clear_consumed(engine: Any, target: Any) -> None:
    from .riders_shared import remove_benefit_condition

    for state in list(target.conditions.values()):
        if state.condition_id.startswith(PREFIX) and consumed(engine, target, state):
            remove_benefit_condition(engine, target, state, "CONSUMED")


@hook("event")
def committed(engine: Any, event_type: str, kwargs: dict) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is not None:
            clear_consumed(engine, target)


@hook("turn_start")
@hook("turn_end")
def sweep(engine: Any, actor: Any) -> None:
    for target in engine.state.actors.values():
        clear_consumed(engine, target)
