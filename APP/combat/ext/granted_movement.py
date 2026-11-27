"""Shared immediate granted movement for Reeling Step, Swaying Guard and Court.

``ordered_step`` is shared by drunken_style and data-attached action riders.
Its validated ``granted_movement`` data chooses when the main effects and their
recipient resolve. ``before``/``after`` refer to the main effect relative to the
movement. Needle journals the order, recipient and path for reload/replay.

Uses the native movement candidates/resolver, including terrain, dragging,
hazards and reactions. Native traversal sees only the grant; reaction effects
see the full remaining pool, with their changes retained in ordinary movement.
The willing native commit restores that pool before post-move reactions. The
mover-specific opportunity scope lasts only for this resolution.
The existing opportunity_allowed hook is inert outside that scope.

The grant accounting itself is the documented ``granted_pool`` contract in
combat/granted_movement.py, shared with the engine's native granted movement.
"""
from contextlib import contextmanager, nullcontext
from typing import Any

from ..granted_movement import granted_pool
from . import effect, effect_permitted, hook

import copy
from dataclasses import replace
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class StepTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range_ft: StrictInt = Field(ge=0)
    exclude_self: bool = False
    target_sees_actor: bool = False


class OrderedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_choice: list[Literal["before", "after"]]
    distance_ft: StrictInt = Field(ge=0)
    name: str = Field(min_length=1)
    choice_key: str = Field(min_length=1)
    target: StepTarget | None = None
    exemption: Literal["target", "visible_creature", "none"] = "none"
    exempt_successful_save: bool = False
    effects: list[dict[str, Any]] = Field(default_factory=list)


def validate_step(row: dict) -> OrderedStep:
    """Validate the shared step at compilation and at direct effect entry."""
    step = OrderedStep.model_validate(row)
    if step.order_choice != ["before", "after"]:
        raise ValueError("granted_movement.order_choice must offer before and after")
    return step


@hook("compile_block")
def step_rider(block: str, spec: dict, row: dict, numbers: dict) -> list[dict] | None:
    if block != "granted_movement_rider":
        return None
    validate_step(spec["granted_movement"])
    return [{**row, "block": block, "action": spec["action"],
             "granted_movement": copy.deepcopy(spec["granted_movement"])}]


@hook("compile_action", priority=10)
def attach_step(action: Any, info: dict) -> Any:
    typed = (action.parameters or {}).get("typed") or {}
    for eff in typed.get("effects") or []:
        if "granted_movement" in eff:
            validate_step(eff["granted_movement"])
    riders = [row for row in info["passives"] if row.get("block") == "granted_movement_rider"
              and row.get("action") == typed.get("source")]
    if not riders:
        return None
    if len(riders) != 1:
        raise ValueError("An activation must declare one granted movement step")
    spec = copy.deepcopy(riders[0]["granted_movement"])
    validate_step(spec)
    # Wrap after ordinary action transforms have sealed any composed effects.
    # Keep the real recipient contract, including remote-condition gates. Only
    # the activation menu becomes self-directed; its recipient is picked later.
    main = action.model_dump(mode="json")
    params = copy.deepcopy(action.parameters)
    params.pop("target_requires_condition", None)
    params["typed"]["effects"] = [{"type": "ordered_granted_movement",
        "granted_movement": spec, "main_action": main,
        "technique_categories": ["movement"]}]
    return action.model_copy(update={"target_kind": "SELF", "range_ft": 0, "parameters": params})


@effect("ordered_granted_movement")
def action_step(ctx: Any, eff: dict) -> None:
    from ..gate2_runtime_models import ActionDefinition
    main = ActionDefinition.model_validate(eff["main_action"])
    ordered_step(ctx, eff["granted_movement"], main_action=main)


def ordered_step(ctx: Any, row: dict, *, feet: int | None = None,
                 main_action: Any = None, trigger: str = "", movement_scope: Any = None) -> Any:
    """Run one typed main effect before/after a separately capped native path.

    Returns its recipient context (or None). Explicit target data is used by
    Reeling Step; attached riders retain the main action’s native eligibility.
    No chosen recipient or exemption outlives this invocation. An optional
    movement_scope factory encloses path choices/resolution only, not the main
    effect (e.g. a caller’s terrain permission for this particular movement).
    The folded self-movement queries its own effect permissions; denying that
    optional portion must not suppress the main effect with the wrapper.
    """
    from .rider_choices import pick
    from .needle import cell_id
    from .choice_prompt import action_context
    from ..typed_executor import run_effects
    from .. import stealth

    spec = validate_step(row)
    engine, actor = ctx.engine, ctx.actor
    feet = spec.distance_ft if feet is None else feet
    key, name = spec.choice_key, spec.name
    trigger = trigger or ctx.action.display_name
    order = pick(engine, actor, key + "_order", name, spec.order_choice, subject=actor,
        optional=False, preferred=["before"],
        labels={"before": "Choose the target and resolve the effect before moving",
                "after": "Move first, then choose the target and resolve the effect"},
        trigger=f"{trigger}: choose when the main effect happens relative to your optional move of up to {feet} feet")
    order = (order or ["before"])[0]
    ignored = []

    def choose_exemption():
        if spec.exemption != "visible_creature":
            return
        watchers = sorted((f for f in engine.state.actors.values()
                           if f.active and f is not actor and stealth.sees(engine, actor, f)),
                          key=lambda f: (f.team_id == actor.team_id, engine._distance_actor_to_actor(actor, f), f.entity_id))
        if watchers:
            chosen = pick(engine, actor, key + "_oa", name, [f.entity_id for f in watchers], subject=actor,
                optional=False, preferred=[next((f.entity_id for f in watchers if f.entity_id not in ignored), watchers[0].entity_id)], trigger=trigger,
                labels={f.entity_id: f"Only this granted move avoids {f.display_name}’s Opportunity Attacks" for f in watchers})
            ignored.extend(chosen or [watchers[0].entity_id])

    def resolve_main():
        if not actor.active:
            return None
        if main_action is not None:
            from ..recipients import allowed
            targets = [t for t in engine.state.actors.values() if allowed(engine, actor, t, main_action)]
            effects = (main_action.parameters.get("typed") or {}).get("effects") or []
        else:
            target = spec.target
            if target is None:
                raise ValueError("A granted movement step needs a main-effect target contract")
            targets = [t for t in engine.state.actors.values() if t.active
                       and (not target.exclude_self or t is not actor)
                       and engine._distance_actor_to_actor(actor, t) <= target.range_ft
                       and (not target.target_sees_actor or stealth.sees(engine, t, actor))]
            effects = spec.effects
        targets.sort(key=lambda t: (t.team_id == actor.team_id, engine._distance_actor_to_actor(actor, t), t.entity_id))
        if not targets:
            return None
        chosen = pick(engine, actor, key + "_test", name, [t.entity_id for t in targets], subject=actor,
            optional=False, preferred=[targets[0].entity_id], trigger=f"{trigger}: choose its target now",
            labels={t.entity_id: f"{ctx.action.display_name}: {t.display_name}" for t in targets},
            prompt_context=action_context(engine, actor, ctx.source, actor, action=ctx.action))
        target = next(t for t in targets if t.entity_id == (chosen or [targets[0].entity_id])[0])
        sub = replace(ctx, target=target, targets=[target],
                      action=main_action or ctx.action,
                      typed=(main_action.parameters["typed"] if main_action else ctx.typed))
        start = len(engine.events)
        run_effects(sub, copy.deepcopy(effects))
        if spec.exemption == "target":
            ignored.append(target.entity_id)
        if spec.exempt_successful_save and any(e.event_type == "SAVE_ROLLED" and e.actor_id == target.entity_id
                and e.source_definition_id == ctx.source and e.payload.get("success") for e in engine.events[start:]):
            ignored.append(target.entity_id)
        return sub

    sub = resolve_main() if order == "before" else None
    movement = {"type": "movement", "applies_to": "self", "distance_ft": feet}
    if actor.active and effect_permitted(ctx, movement, [actor]):
        choose_exemption()
        with movement_scope() if movement_scope else nullcontext():
            paths = choices(engine, actor, feet)
            labels = {cell_id(c.destination): f"Move to {c.destination.x},{c.destination.y} ({c.movement_cost_ft} feet)" for c in paths}
            stay = cell_id(actor.position)
            labels[stay] = "Stay put (0 feet)"
            chosen = pick(engine, actor, key + "_move", name, list(labels), subject=actor, labels=labels,
                          trigger=f"{trigger} grants up to {feet} feet; immunity applies only to this move")
            if chosen and chosen[0] != stay:
                path = next(c for c in paths if cell_id(c.destination) == chosen[0])
                move(engine, actor, path, ctx.intent, feet, ignored, name=name)
    return resolve_main() if order == "after" else sub


def choices(engine: Any, actor: Any, feet: int) -> list[Any]:
    """Native legal paths using only the caller's printed grant; listing is read-only.

    A fixed-distance feature may grant more movement than the creature's current
    Speed. Speed-based callers pass their current Speed as ``feet`` themselves.
    """
    if not actor.active:
        return []
    grant = max(0, int(feet))
    if grant <= 0:
        return []
    budget = actor.movement_remaining_ft
    try:
        actor.movement_remaining_ft = grant
        from . import any_false
        return [c for c in engine._movement_candidates(actor)
                if int(c.movement_cost_ft or 0) <= grant
                if not any_false("candidate_allowed", engine, actor, c,
                                 engine.action_catalog.get(c.source_definition_id))]
    finally:
        actor.movement_remaining_ft = budget


def move(engine: Any, actor: Any, candidate: Any, intent: Any, feet: int,
         ignored: list[str], *, name: str = "Granted movement", nonprovoking: bool = False,
         movement_context: dict | None = None) -> bool:
    """Resolve one separately capped path; report movement and restore scoped state."""
    grant = max(0, int(feet))
    if grant <= 0 or int(candidate.movement_cost_ft or 0) > grant:
        return False
    start = actor.position
    previous = getattr(engine, "_granted_movement_oa", None)
    free = actor.turn_flags.pop("oa_free_ft", None)
    single = actor.turn_flags.pop("spark_step_ignore_oa_from", None)
    # Unrestricted nonprovoking grants use the native all-reactor hook, rather
    # than the historical limited named-creature legacy preflight.
    if nonprovoking:
        ignored = list(engine.state.actors)
    try:
        engine._granted_movement_oa = (actor.entity_id, tuple(ignored))
        # Cost revalidation must never see or borrow ordinary movement; the
        # shared contract exposes the grant and keeps anything the mover gains
        # while it resolves in the ordinary pool.
        with granted_pool(engine, actor, grant):
            engine._resolve_movement(actor, candidate, intent, granted_ft=grant,
                                     movement_context=movement_context)
    finally:
        engine._granted_movement_oa = previous
        actor.turn_flags.pop("oa_free_ft", None)
        if free is not None:
            actor.turn_flags["oa_free_ft"] = free
        actor.turn_flags.pop("spark_step_ignore_oa_from", None)
        if single is not None:
            actor.turn_flags["spark_step_ignore_oa_from"] = single
    return actor.position != start


@hook("effect_resolution_scope")
def reaction_budget(ctx: Any, effect: dict[str, Any]) -> Any:
    """Shared Reeling Step/Swaying Guard accounting during nested typed effects."""
    budget = getattr(ctx.engine, "_granted_movement_budget", None)
    if budget is None or budget["committed"] or budget["exposed"]:
        return None
    return _reaction_pool(budget)


@contextmanager
def _reaction_pool(budget: dict[str, Any]):
    actor = budget["actor"]
    allowance = actor.movement_remaining_ft
    budget["exposed"] = True
    actor.movement_remaining_ft += budget["ordinary"]
    try:
        yield
    finally:
        remaining = actor.movement_remaining_ft
        # Gains belong to ordinary movement, never to the selected grant.
        # Spend ordinary movement first, then the separate grant. The native
        # resolver reads this remaining grant on its next path step.
        before = allowance + budget["ordinary"]
        # A nested effect can change the mover's pool in either direction.
        # Positive changes are ordinary movement; they never enlarge the
        # separately selected grant.
        budget["ordinary"] += max(0, remaining - before)
        loss = max(0, before - remaining)
        ordinary_loss = min(budget["ordinary"], loss)
        budget["ordinary"] -= ordinary_loss
        budget["grant"] = max(0, budget["grant"] - (loss - ordinary_loss))
        actor.movement_remaining_ft = min(allowance, remaining)
        budget["exposed"] = False


@hook("event", nested=True, priority=-100)
def granted_path_committed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Restore ordinary feet at this grant's own commit, before other observers."""
    budget = getattr(engine, "_granted_movement_budget", None)
    # Nested native movement can commit for a different creature. It neither
    # consumes nor restores this mover's extension pool.
    if (budget is None or event_type != "MOVEMENT_COMMITTED"
            or kwargs.get("actor_id") != budget["actor"].entity_id):
        return
    if budget["committed"] or budget["exposed"]:
        return
    from ..gate2_engine import SYSTEM_MOVE
    event = engine.events[-1]
    payload = kwargs.get("payload") or {}
    if (kwargs.get("actor_id") != budget["actor"].entity_id
            or event.source_definition_id != SYSTEM_MOVE or payload.get("forced")
            or "planned_cost_ft" not in payload):
        return
    budget["committed"] = True
    # Legacy attacks can enter the native dying/stable lifecycle without a
    # typed effect scope. That lifecycle explicitly ends all turn movement.
    budget["actor"].movement_remaining_ft = 0 if budget["actor"].life_state is not None else budget["ordinary"]


@hook("opportunity_allowed")
def exempt(engine: Any, reactor: Any, mover: Any) -> bool | None:
    scope = getattr(engine, "_granted_movement_oa", None)
    if scope is not None and scope[0] == mover.entity_id and reactor.entity_id in scope[1]:
        return False
    return None
