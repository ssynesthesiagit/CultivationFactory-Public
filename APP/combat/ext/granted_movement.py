"""Shared immediate granted movement for Reeling Step, Swaying Guard and Court.

Uses the native movement candidates/resolver, including terrain, dragging,
hazards and reactions. Native traversal sees only the grant; reaction effects
see the full remaining pool, with their changes retained in ordinary movement.
The willing native commit restores that pool before post-move reactions. The
mover-specific opportunity scope lasts only for this resolution.
The existing opportunity_allowed hook is inert outside that scope.
"""
from contextlib import contextmanager
from typing import Any

from . import hook


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


def choose(engine, mover, feet, source, *, key, name, threat, intent=None, ignored=()):
    """Choose among every native route/mode, including staying put.

    Unlike destination-only historical riders, this adapter preserves multiple
    legal movement modes at one endpoint and has no menu-size cutoff. It adds
    no movement resolver: the selected native candidate runs through move().
    """
    from .needle import ask, CHOICE, checkpoint_id, cell_id
    from ..target_knowledge import located
    paths = choices(engine, mover, feet)
    by_id, labels = {}, {}
    stay = cell_id(mover.position)
    labels[stay] = 'Stay in your current space'
    for path in paths:
        ident = cell_id(path.destination)
        mode = path.metadata.get('movement_mode', 'walk')
        if ident in labels:
            ident = 'route:' + path.candidate_id
        by_id[ident] = path
        p = path.destination
        labels[ident] = f'({p.x}, {p.y}, {p.z * 5} feet high): {mode.title()}, {path.movement_cost_ft} feet of movement'
    preferred = [stay]
    if threat is not None and located(engine, mover, threat) and by_id:
        preferred = [max(by_id, key=lambda k: engine.grid.distance_ft(threat.position, by_id[k].destination))]
    ignored = tuple(ignored)
    protection = ('without provoking Opportunity Attacks' if set(ignored) >= set(engine.state.actors)
                  else 'without Opportunity Attacks from ' + ', '.join(engine.state.actors[i].display_name for i in ignored)
                  if ignored else 'with ordinary Opportunity Attacks')
    picked = ask(engine, intent, checkpoint_id(engine, key, mover.entity_id), mover,
        CHOICE + key, list(labels), labels=labels, preferred=preferred, allow_decline=True,
        target_id=mover.entity_id, name=name,
        prompt=f'{name}: choose {mover.display_name}’s legal movement, up to {feet} feet {protection}, or stay put. No additional cost.',
        prompt_context={'cost': 'No additional cost'})
    if picked and picked[0] in by_id:
        move(engine, mover, by_id[picked[0]], intent or getattr(engine, '_active_intent', None), feet, list(ignored), name=name, source=source)
        return True
    return False


def legacy_reactors_along(engine: Any, mover: Any, candidate: Any, named: list[str]) -> list[str]:
    """Legacy reactors the real route could provoke, for its one-ID adapter.

    Every ignored ID also remains exempt through opportunity_allowed. The
    legacy single-creature field is only a compatibility aid; it never removes
    another named exemption or limits an otherwise legal movement grant.
    """
    from ..gate2_runtime_content import BASIC_MELEE
    from ..relations import ENEMY, relation

    typed = getattr(engine, "typed_actor_ids", set())
    legacy = [entity_id for entity_id in named if entity_id not in typed]
    path = list(getattr(candidate, "canonical_path", None) or [])
    if not path:  # no route to reason about: keep the widest protection the old code gave
        return legacy
    relevant: list[str] = []
    for entity_id in legacy:
        reactor = engine.state.actors.get(entity_id)
        if reactor is None or not reactor.active or relation(engine, reactor, mover) != ENEMY:
            continue
        params = (engine.reaction_parameters.get("reaction:core.opportunity_attack", {})
                  if entity_id in getattr(engine, "runtime_actor_ids", ())
                  else BASIC_MELEE.get(entity_id, {}))
        reach = int(params.get("reach_ft", 5))
        for previous, nxt in zip(path, path[1:]):
            if (engine._distance_actor_to_actor(mover, reactor, actor_position=previous) <= reach
                    and engine._distance_actor_to_actor(mover, reactor, actor_position=nxt) > reach):
                relevant.append(entity_id)
                break
    return relevant


def move(engine: Any, actor: Any, candidate: Any, intent: Any, feet: int,
         ignored: list[str], *, name: str = "Granted movement", source: str | None = None) -> None:
    """Resolve one separately capped path; restore pools and exemption scope."""
    grant = max(0, int(feet))
    if grant <= 0 or int(candidate.movement_cost_ft or 0) > grant:
        return
    previous = getattr(engine, "_granted_movement_oa", None)
    previous_budget = getattr(engine, "_granted_movement_budget", None)
    budget = {"actor": actor, "ordinary": actor.movement_remaining_ft, "grant": grant,
              "exposed": False, "committed": False, 'source': source}
    free = actor.turn_flags.pop("oa_free_ft", None)
    single = actor.turn_flags.pop("spark_step_ignore_oa_from", None)
    legacy = legacy_reactors_along(engine, actor, candidate, ignored)
    try:
        # Cost revalidation must never see or borrow ordinary movement.
        actor.movement_remaining_ft = grant
        engine._granted_movement_budget = budget
        engine._granted_movement_oa = (actor.entity_id, tuple(ignored))
        if legacy:
            actor.turn_flags["spark_step_ignore_oa_from"] = legacy[0]
        engine._resolve_movement(actor, candidate, intent, granted_ft=grant, ignore_oa_from=tuple(ignored), grant_source=source)
    finally:
        if not budget["committed"]:
            actor.movement_remaining_ft = budget["ordinary"]
        engine._granted_movement_budget = previous_budget
        engine._granted_movement_oa = previous
        actor.turn_flags.pop("oa_free_ft", None)
        if free is not None:
            actor.turn_flags["oa_free_ft"] = free
        actor.turn_flags.pop("spark_step_ignore_oa_from", None)
        if single is not None:
            actor.turn_flags["spark_step_ignore_oa_from"] = single


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
            or event.source_definition_id != (budget.get('source') or SYSTEM_MOVE) or payload.get("forced")
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
