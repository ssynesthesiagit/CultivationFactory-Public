"""Shared immediate granted movement for Reeling Step, Swaying Guard and Court.

Uses the native movement candidates/resolver, including terrain, dragging,
hazards and reactions. Native traversal sees only the grant; reaction effects
see the full remaining pool, with their changes retained in ordinary movement.
The willing native commit restores that pool before post-move reactions. The
mover-specific opportunity scope lasts only for this resolution.
The existing opportunity_allowed hook is inert outside that scope.

The grant accounting itself is the documented ``granted_pool`` contract in
combat/granted_movement.py, shared with the engine's native granted movement.
"""
from contextlib import contextmanager
from typing import Any

from ..granted_movement import granted_pool
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


def legacy_reactors_along(engine: Any, mover: Any, candidate: Any, named: list[str]) -> list[str]:
    """Which of ``named`` are *legacy* fighters the chosen path could actually provoke, as ids.

    Every id a clause names stays exempt through the ``opportunity_allowed`` hook below, and the engine consults
    that hook for *every* reactor before it decides how to ask one -- legacy fighters included, as documented at
    ``ext/__init__.py`` ("the existing pure opportunity_allowed query also applies to legacy reactors"). What is
    *not* covered for legacy fighters is the resolver's other single-creature exemption,
    ``spark_step_ignore_oa_from``, which names one id and is the slot this preflight is sizing: a second relevant
    legacy enemy has nowhere to go and the move becomes a GM rider instead. Restricting the preflight to the
    chosen route is what keeps a fighter across the arena from consuming that one slot (review AUTO8r2, R5): such
    a fighter is named, so it is still fully exempt through the hook, but it could never have reacted and must not
    cost the step its exemption slot. Do not widen the engine's flag to fix anything here: the hook is the general
    seam, and it is already correct for legacy reactors.

    Relevance mirrors the engine's own leave-reach test (``gate2_engine._resolve_leave_reach``) step for step: a
    reactor counts when some square of the route is inside its reach and the next square is not. The whole route
    is considered even though a hazard may stop the mover earlier, because naming a fighter that a completed
    route could not have provoked costs nothing while missing one that could is a real bug.
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
         ignored: list[str], *, name: str = "Granted movement",
         movement_context: dict | None = None) -> None:
    """Resolve one separately capped path; restore pools and exemption scope."""
    grant = max(0, int(feet))
    if grant <= 0 or int(candidate.movement_cost_ft or 0) > grant:
        return
    previous = getattr(engine, "_granted_movement_oa", None)
    free = actor.turn_flags.pop("oa_free_ft", None)
    single = actor.turn_flags.pop("spark_step_ignore_oa_from", None)
    legacy = legacy_reactors_along(engine, actor, candidate, ignored)
    if len(set(legacy)) > 1:
        # The native resolver's single-creature exemption (``spark_step_ignore_oa_from``) names one id, and a
        # legacy fighter also needs that slot: the ``opportunity_allowed`` hook below exempts every id a clause
        # names, legacy included, but the flag is a separate single-id path the engine checks on its own. So this
        # rider is only reachable when more than one *legacy* enemy standing somewhere along the chosen route is
        # in reach, and every one of them is already exempt through the hook.
        from . import note
        if free is not None:
            actor.turn_flags["oa_free_ft"] = free
        if single is not None:
            actor.turn_flags["spark_step_ignore_oa_from"] = single
        # A clause printed for every enemy (Court of Ten Thousand Steps) can name more than two. The two-creature
        # wording is kept verbatim so fights recorded before this lane -- Swaying Guard's own two-creature grant --
        # still replay byte for byte.
        named = "both chosen creatures" if len(set(legacy)) == 2 else "all of those creatures"
        note(engine, candidate.source_definition_id, actor,
             f"The GM must resolve {name}'s move: it avoids Opportunity Attacks from {named}, "
             "which this table cannot yet automate together.")
        return
    try:
        engine._granted_movement_oa = (actor.entity_id, tuple(ignored))
        if legacy:
            actor.turn_flags["spark_step_ignore_oa_from"] = legacy[0]
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
