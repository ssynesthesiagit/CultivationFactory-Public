"""A talent's own timed state, named, so other rules can ask whether it is running (rider lane 1, 2026-09-29: "i want everything
we can automated").

Many "For the duration: ..." talents (a Body, an Incarnation, a Court) carry a bullet that is not a stat but a trigger ("When a
creature misses you with an Opportunity Attack, you may place a Charge on that creature") or that another talent reads ("while
Lightning-God Body ... is active").  The typed rows of the talent already give the numbers (Speed, Resistance, Advantage) for the
duration; what they lack is a way to say "this is on".  Two effects, riding any typed ability:

  {"type": "state", "name": "lightning_god_body", "duration": "one_minute"}
        Puts "condition:typed.state.<name>" on the user for the ability's (or the row's own) duration, ending when a new use of the
        same state starts.  ``data.numbers`` keeps the Proficiency Bonus and Cultivation Level it was made with.
  {"type": "if_state", "names": ["lightning_god_body", ...], "effects": [...]}
        Runs ``effects`` only while the user has one of these states on.
  ``ends_if_incapacitated: true`` on a state ends it and its source's benefits when Incapacitated (including Stunned).
  ``effect_kind`` may explicitly classify the created temporary effect as a
  ward, barrier, transformation, aura, stance or damage_reduction. It is copied
  into the native condition rule for source-qualified effect consumers; names
  and flavour never supply a classification. Missing metadata is unchanged.
  ``range_for: {"<mechanic id>": 300}`` replaces those abilities' ranges while the state runs, including free copies.
  {"type": "if_moved", "min_ft": 30, "once_per_turn": "wings", "effects": [...]}
        Runs after that much willing movement, with no approach requirement; only a qualifying hit spends the turn limit.
  ``declares_only: true`` on a state row declares the named state and its ``free_use`` copies without putting the state on
  its user, for a printed line whose state belongs to a *different* ability: The Empty Bowl Watches' "while Digestive Mantle
  is active, you can use Taste the Qi without spending a Bonus Action" declares the Mantle's state, which the Mantle itself
  puts on (combat/ext/hunger_riders.py).  Absent the flag a state row behaves exactly as before.

``active(engine, actor, *names)`` is the plug-in-side question (the condition instance or None).
Shared helper module (consumers: gravity.py, for Weight Shift's modes and Gravity's own timed states): ``active`` and ``PREFIX``.
Shared helper also used by reach_bonus.py and black_thorn_demon_body.py to gate state-bound benefits.
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook
from .owned_effects import remove_conditions

PREFIX = "condition:typed.state."


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def active(engine: Any, actor: Any, *names: str) -> Any:
    wanted = {PREFIX + slug(name) for name in names}
    return next((condition for condition in actor.conditions.values() if condition.condition_id in wanted), None)


def context(engine: Any, actor: Any, source_id: str, targets: list[Any], numbers: dict[str, Any] | None = None) -> Any:
    """A typed_executor.Context for ``actor`` outside an action of its own (an event hook): the action whose source is ``source_id``
    (any of the actor's own actions when none), the given targets, and ``numbers`` (Proficiency Bonus, Cultivation Level)."""
    from .. import typed_executor as te

    action = next((row for row in engine.action_catalog.values() if row.source_definition_id == source_id), None) \
        or next(iter(engine.action_catalog.values()))
    return te.Context(engine, actor, action, None, {"numbers": dict(numbers or {})}, list(targets), targets[0] if targets else None, {})


@effect("state")
def state(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    if eff.get("declares_only"):
        return  # a declaration only: another ability owns this state (see the module docstring).
    engine, actor = ctx.engine, ctx.actor
    kind = eff.get('effect_kind')
    if kind is not None and kind not in {'ward', 'barrier', 'transformation', 'aura', 'stance', 'damage_reduction'}:
        raise ValueError('A state effect_kind must explicitly name a supported temporary effect category')
    name = str(eff.get("name") or ctx.action.display_name)
    condition_id = PREFIX + slug(name)
    remove_conditions(engine, actor, ctx.source, actor.entity_id, condition_id)
    engine._apply_condition(actor, condition_id, ctx.source, actor.entity_id,
                            expires_on=te.effect_expiry(ctx, eff, actor, condition=True) or "UNTIL_REMOVED",
                            data={"label": str(eff.get("label") or name.replace("_", " ").title()), "name": name,
                                  **({'rule': {'effect_kind': kind}} if kind is not None else {}),
                                  "ends_if_incapacitated": bool(eff.get("ends_if_incapacitated")),
                                  **({"ends_if_unconscious": True} if eff.get("ends_if_unconscious") else {}),
                                  "range_for": dict(eff.get("range_for") or {}),
                                  "numbers": {"pb": int(ctx.numbers.get("pb") or 0), "cl": int(ctx.numbers.get("cl") or 1)}})


@effect("if_state")
def if_state(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    if active(ctx.engine, ctx.actor, *[str(name) for name in eff.get("names") or []]):
        te.run_effects(ctx, eff.get("effects") or [])


@hook("compile_actions")
def state_ranges(info: dict[str, Any]) -> list[Any] | None:
    """Precompile wider siblings, gated by the active state, so the legal-target listing uses the correct range."""
    import copy

    made = []
    for key in info["owned_ids"]:
        mechanic = info["mechanics"].get(key) or {}
        for spec in mechanic.get("effects") or []:
            if spec.get("type") != "state" or not spec.get("range_for"):
                continue
            for action in info["actions"]:
                typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
                feet = spec["range_for"].get(typed.get("source"))
                if feet is None:
                    continue
                typed["range_ft"] = int(feet)
                made.append(action.model_copy(update={"source_definition_id": action.source_definition_id + "+range_" + slug(spec["name"]),
                                                     "range_ft": int(feet), "parameters": {**action.parameters, "typed": typed,
                                                                                           "state_range_rule": {"state": spec["name"]}}}))
    return made or None


@hook("candidate_allowed")
def state_range_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    parameters = action.parameters or {}
    rule = parameters.get("state_range_rule")
    if rule:
        return None if any(active(engine, actor, state) for state in rule.get('states', [rule.get('state')])) else False
    source = (parameters.get("typed") or {}).get("source")
    if any(c.condition_id.startswith(PREFIX) and source in ((c.data or {}).get("range_for") or {})
           for c in actor.conditions.values()):
        return False
    return None


@effect("if_moved")
def if_moved(ctx: Any, eff: dict[str, Any]) -> None:
    """Run after enough willing movement this turn, spending the limit only on a qualifying hit.

    {"type": "if_moved", "min_ft": 30, "once_per_turn": "wings", "effects": [...]}
    Uses the existing event-based distance counter; movement need not approach the target.
    """
    from .hold_still import moved_ft
    from .. import typed_executor as te

    if moved_ft(ctx.engine, ctx.actor) < int(eff.get("min_ft") or 0):
        return
    flag = "typed_moved_hit:" + str(eff.get("once_per_turn") or "")
    if eff.get("once_per_turn"):
        if ctx.actor.turn_flags.get(flag):
            return
        ctx.actor.turn_flags[flag] = True
    te.run_effects(ctx, eff.get("effects") or [])


@effect("if_sphere")
def if_sphere(ctx: Any, eff: dict[str, Any]) -> None:
    """A stance rider for a named sphere; spend its per-turn limit only on that sphere's hit.

    {"type": "if_sphere", "ids": ["tianxia.sphere.lightning"], "once_per_turn": "body_becomes_thunder", "effects": [...]}
    """
    from .. import typed_executor as te

    if ctx.typed.get("sphere") not in (eff.get("ids") or []):
        return
    flag = "typed_sphere_hit:" + str(eff.get("once_per_turn") or "")
    if eff.get("once_per_turn"):
        if ctx.actor.turn_flags.get(flag):
            return
        ctx.actor.turn_flags[flag] = True
    te.run_effects(ctx, eff.get("effects") or [])


@hook("event")
def end_incapacitated_states(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """End explicitly opted-in states on Incapacitated or Unconscious."""
    if event_type not in ("CONDITION_APPLIED", "DAMAGE_COMMITTED", "TURN_STARTED"):
        return
    from .. import typed_executor as te

    for actor in list(engine.state.actors.values()):
        incapacitated = any(rule.get("no_actions") for rule in te.condition_rules(actor))
        unconscious = actor.life_state in ("DYING", "STABLE") or any(str(c.condition_id).endswith("unconscious") for c in actor.conditions.values())
        if not incapacitated and not unconscious:
            continue
        sources = {c.source_definition_id for c in actor.conditions.values()
                   if c.condition_id.startswith(PREFIX) and ((incapacitated and (c.data or {}).get("ends_if_incapacitated"))
                                                             or (unconscious and (c.data or {}).get("ends_if_unconscious")))}
        unconscious_sources = {c.source_definition_id for c in actor.conditions.values()
                               if unconscious and c.condition_id.startswith(PREFIX) and (c.data or {}).get("ends_if_unconscious")}
        for holder in list(engine.state.actors.values()):
            for source in sources:
                remove_conditions(engine, holder, source, actor.entity_id, reason="INCAPACITATED")
            for mid, modifier in list(holder.modifiers.items()):
                if modifier.source_definition_id in sources and modifier.source_actor_id == actor.entity_id:
                    del holder.modifiers[mid]
                    engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id,
                                         target_ids=(holder.entity_id,), payload={"modifier_id": mid, "reason": "INCAPACITATED"})
        # New opt-in lifecycle also ends areas created by that same activation.
        # Historical incapacitated-only states retain their existing contract.
        from .. import zones
        for zone in list(engine.state.zones.values()):
            if zone.active and zone.owner_id == actor.entity_id and zone.source_definition_id in unconscious_sources:
                zones.remove(engine, zone, "UNCONSCIOUS")
